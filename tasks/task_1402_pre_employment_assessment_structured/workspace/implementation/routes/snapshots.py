"""Adverse-impact snapshots: four-fifths rule with pinned rounding order
(PRD §3.7, calculations.adverse_impact_ratio)."""
from decimal import Decimal, ROUND_HALF_UP

import db
import serializers
import util
from errors import api_err, err_not_found
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, new_id, next_seq, paginate, req_enum, sort_records

bp = Blueprint("snapshots", __name__)

GROUPS = ["GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D"]
PROVISIONAL_STATUSES = {"SCHEDULED", "ACCOMMODATION_HOLD", "IN_PROGRESS",
                        "COMPLETED", "NO_SHOW"}
FOUR_FIFTHS = Decimal("0.8000")
MIN_GROUP_N = 2
PROJECTED_SELECTION_COMPOSITE = Decimal("0.7000")
Q4 = Decimal("0.0001")


def _round4dec(x):
    return x.quantize(Q4, rounding=ROUND_HALF_UP)


@bp.post("/talent/cycles/<cid>/adverse-impact-snapshots")
def create_snapshot(cid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    cyc = db.stores["cycles"].get(cid)
    if cyc is None:
        raise err_not_found("AssessmentCycle not found")
    # Posture gate (tier 7) precedes body shape validation (tier 16):
    # ACTIVE, SCORING, DECIDED, or FROZEN
    if cyc["posture"] not in ("ACTIVE", "SCORING", "DECIDED", "FROZEN"):
        raise api_err("ERR_CYCLE_NOT_ACTIVE",
                      "Snapshots require posture ACTIVE, SCORING, DECIDED, or FROZEN")
    body = util.get_body()
    snapshot_type = req_enum(body, "snapshot_type", ["PROVISIONAL", "FINAL"])

    # Gather the cycle's assessments joined to candidate group_code
    assessments = [a for a in db.stores["assessments"].values() if a["cycle_id"] == cid]
    decisions = {(d["candidate_id"]): d for d in db.stores["decisions"].values()
                 if d["cycle_id"] == cid}

    def in_applicant_set(a):
        if snapshot_type == "PROVISIONAL":
            return a["admin_status"] in PROVISIONAL_STATUSES
        return a["admin_status"] == "COMPLETED"

    def is_selected(a):
        dec = decisions.get(a["candidate_id"])
        if dec is not None and dec["decision"] == "ADVANCE":
            return True
        if snapshot_type == "PROVISIONAL":
            # projected selection: completed with composite >= 0.7000, undecided
            if dec is None and a["admin_status"] == "COMPLETED":
                comp = a.get("composite_score")
                if comp is not None and Decimal(str(comp)) >= PROJECTED_SELECTION_COMPOSITE:
                    return True
        return False

    # UNDISCLOSED breakdown entry (excluded from every denominator)
    undisclosed = [a for a in assessments
                   if in_applicant_set(a)
                   and db.stores["candidates"].get(a["candidate_id"], {}).get("group_code") == "UNDISCLOSED"]

    breakdowns = []
    included = []  # (group_code, applicants, selected, selection_rate Decimal)
    for g in GROUPS:
        group_assessments = [a for a in assessments
                             if in_applicant_set(a)
                             and db.stores["candidates"].get(a["candidate_id"], {}).get("group_code") == g]
        applicants = len(group_assessments)
        selected = sum(1 for a in group_assessments if is_selected(a))
        if applicants < MIN_GROUP_N:
            breakdowns.append({
                "group_code": g,
                "applicants": applicants,
                "selected": selected,
                "selection_rate": None,
                "impact_ratio": None,
                "excluded_reason": "INSUFFICIENT_N",
            })
            continue
        rate = _round4dec(Decimal(selected) / Decimal(applicants))
        breakdowns.append({
            "group_code": g,
            "applicants": applicants,
            "selected": selected,
            "selection_rate": float(rate),
            "impact_ratio": None,  # filled below
            "excluded_reason": None,
        })
        included.append((g, applicants, selected, rate))

    # Highest rate group: max rate; ties -> larger applicants -> group_code ASC
    highest_code = None
    if included:
        ranked = sorted(included, key=lambda t: (-t[3], -t[1], t[0]))
        top = ranked[0]
        max_rate = top[3]
        if max_rate == 0:
            # NO_SELECTIONS: every included group null ratio, flagged false
            for b in breakdowns:
                if b["excluded_reason"] is None:
                    b["selection_rate"] = b["selection_rate"]
                    b["impact_ratio"] = None
                    b["excluded_reason"] = "NO_SELECTIONS"
            flagged = False
        else:
            highest_code = top[0]
            flagged = False
            rates_by_group = {t[0]: t[3] for t in included}
            for b in breakdowns:
                if b["excluded_reason"] is not None:
                    continue
                ratio = _round4dec(rates_by_group[b["group_code"]] / max_rate)
                b["impact_ratio"] = float(ratio)
                if ratio < FOUR_FIFTHS:
                    flagged = True
    else:
        flagged = False

    if undisclosed:
        breakdowns.append({
            "group_code": "UNDISCLOSED",
            "applicants": len(undisclosed),
            "selected": sum(1 for a in undisclosed if is_selected(a)),
            "selection_rate": None,
            "impact_ratio": None,
            "excluded_reason": "UNDISCLOSED",
        })

    now = db.get_now()
    rec = {
        "id": new_id(),
        "cycle_id": cid,
        "snapshot_type": snapshot_type,
        "group_breakdowns": breakdowns,
        "highest_rate_group_code": highest_code,
        "flagged": flagged,
        "computed_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["snapshots"][rec["id"]] = rec

    # Flagged FINAL freezes the cycle when monitoring enabled (PRD §3.7)
    if (snapshot_type == "FINAL" and flagged
            and cyc["posture"] in ("ACTIVE", "SCORING")):
        instrument = db.stores["instruments"].get(cyc["instrument_id"])
        if instrument is not None and instrument.get("adverse_impact_monitor_enabled", True):
            cyc["frozen_from_posture"] = cyc["posture"]
            cyc["posture"] = "FROZEN"
            cyc["frozen_reason"] = "ADVERSE_IMPACT"
            bump(cyc)
    return success_object(serializers.snapshot(rec), 201)


@bp.get("/talent/cycles/<cid>/adverse-impact-snapshots")
def list_snapshots(cid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer", "TalentAssessmentAdmin", "HiringManager"])
    cyc = db.stores["cycles"].get(cid)
    if cyc is None:
        raise err_not_found("AssessmentCycle not found")
    recs = [serializers.snapshot(s) for s in sort_records(
        [s for s in db.stores["snapshots"].values() if s["cycle_id"] == cid])]
    return paginate(recs)


@bp.get("/talent/adverse-impact-snapshots/<sid>")
def get_snapshot(sid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer", "TalentAssessmentAdmin"])
    s = db.stores["snapshots"].get(sid)
    if s is None:
        raise err_not_found("AdverseImpactSnapshot not found")
    return success_object(serializers.snapshot(s))
