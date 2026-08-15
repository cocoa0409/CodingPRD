"""InfectionCases: create / list / get / begin-review / adjudicate / reopen."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_CASE_NOT_ADJUDICATABLE,
    ERR_CASE_NOT_REOPENABLE,
    ERR_CASE_NOT_REVIEWABLE,
    ERR_DEVICE_DAY_RULE_NOT_MET,
    ERR_DEVICE_EPISODE_NOT_FOUND,
    ERR_DOE_NOT_HAI_DAY_RULE,
    ERR_DOE_OUTSIDE_IWP,
    ERR_EPISODE_PATIENT_MISMATCH,
    ERR_INFECTION_CASE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_ADMITTED,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROCEDURE_NOT_FOUND,
    ERR_PROCEDURE_PATIENT_MISMATCH,
    ERR_REPEAT_INFECTION_TIMEFRAME,
    ERR_SSI_WINDOW_EXPIRED,
    ERR_SUMMARY_LOCKED,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import (
    find_covering_summary,
    new_entity,
    recompute_covering_summary,
    recompute_summary,
    run_cluster_detection,
    MUTABLE_SUMMARY_STATUSES,
    touch,
)
from services.serializers import case_view
from util import cal_date, end_of_day_utc, midnight_utc
from validate import body, opt_dt, opt_string, pagination_args, req_dt, req_enum, req_string

bp = Blueprint("cases", __name__)

CASE_TYPES = {"CLABSI", "CAUTI", "SSI", "OTHER_BSI"}
SSI_DEPTHS = {"SURFACE", "DEEP", "ORGAN_SPACE"}
ADJUDICATE_OUTCOMES = {"ADJUDICATED_HAI", "RULED_OUT"}


@bp.post("/api/infection-cases")
def create_case():
    require_roles(["InfectionPreventionist"])
    b = body()
    for f in ("patient_id", "case_type", "suspected_organism", "first_positive_specimen_at"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    patient_id = b.get("patient_id")
    if not isinstance(patient_id, str) or not patient_id:
        raise_err(ERR_INVALID_REQUEST, "patient_id must be a string")
    case_type = req_enum(b, "case_type", CASE_TYPES)
    suspected_organism = req_string(b, "suspected_organism")
    specimen_at = req_dt(b, "first_positive_specimen_at")

    # Conditional-required pairings (schema tier).
    sp_id = b.get("surgical_procedure_id")
    ep_id = b.get("linked_device_episode_id")
    if case_type == "SSI":
        if sp_id is None:
            raise_err(ERR_INVALID_REQUEST, "surgical_procedure_id is required for SSI")
    else:
        if sp_id is not None:
            raise_err(ERR_INVALID_REQUEST, "surgical_procedure_id must be absent unless case_type is SSI")
    if case_type in ("CLABSI", "CAUTI"):
        if ep_id is None:
            raise_err(ERR_INVALID_REQUEST, "linked_device_episode_id is required for CLABSI/CAUTI")
    else:
        if ep_id is not None:
            raise_err(ERR_INVALID_REQUEST, "linked_device_episode_id must be absent unless case_type is CLABSI/CAUTI")
    if sp_id is not None and (not isinstance(sp_id, str) or not sp_id):
        raise_err(ERR_INVALID_REQUEST, "surgical_procedure_id must be a string")
    if ep_id is not None and (not isinstance(ep_id, str) or not ep_id):
        raise_err(ERR_INVALID_REQUEST, "linked_device_episode_id must be a string")

    # Existence (payload declaration order: patient_id, surgical_procedure_id, linked_device_episode_id)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    proc = None
    if sp_id is not None:
        proc = db.surgical_procedures.get(sp_id)
        if proc is None:
            raise_err(ERR_PROCEDURE_NOT_FOUND, "surgical procedure id does not exist")
    ep = None
    if ep_id is not None:
        ep = db.device_episodes.get(ep_id)
        if ep is None:
            raise_err(ERR_DEVICE_EPISODE_NOT_FOUND, "device episode id does not exist")

    if patient["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")

    # Temporal: RIT repeat-infection block (priority 7 sub-order (a)).
    spec_date = cal_date(specimen_at)
    for e in db.infection_cases.values():
        if (
            e["patient_id"] == patient_id
            and e["case_type"] == case_type
            and e["status"] == "ADJUDICATED_HAI"
            and e["date_of_event"] is not None
        ):
            doe_date = cal_date(e["date_of_event"])
            if doe_date <= spec_date <= doe_date + timedelta(days=13):
                raise_err(ERR_REPEAT_INFECTION_TIMEFRAME, "specimen date falls inside a 14-day RIT window")

    # Referential: linked rows must belong to the same patient.
    if ep is not None and ep["patient_id"] != patient_id:
        raise_err(ERR_EPISODE_PATIENT_MISMATCH, "linked device episode belongs to a different patient")
    if proc is not None and proc["patient_id"] != patient_id:
        raise_err(ERR_PROCEDURE_PATIENT_MISMATCH, "surgical procedure belongs to a different patient")

    # IWP: specimen date -3d 00:00:00Z .. +3d 23:59:59Z (closed)
    iwp_start = midnight_utc(spec_date - timedelta(days=3))
    iwp_end = end_of_day_utc(spec_date + timedelta(days=3))

    case = new_entity({
        "patient_id": patient_id,
        "unit_id": patient["current_unit_id"],
        "case_type": case_type,
        "suspected_organism": suspected_organism,
        "first_positive_specimen_at": specimen_at,
        "surgical_procedure_id": sp_id,
        "linked_device_episode_id": ep_id,
        "infection_window_start": iwp_start,
        "infection_window_end": iwp_end,
        "date_of_event": None,
        "is_hai": None,
        "rit_blocked_until": None,
        "ssi_depth": None,
        "status": "SUSPECTED",
        "adjudicated_by_user_id": None,
        "adjudication_rationale": None,
    })
    db.infection_cases[case["id"]] = case
    return success_object(case_view(case), 201)


@bp.get("/api/infection-cases")
def list_cases():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    sp_id = request.args.get("surgical_procedure_id")
    ep_id = request.args.get("linked_device_episode_id")

    def _match(c):
        if unit_id is not None and c["unit_id"] != unit_id:
            return False
        if patient_id is not None and c["patient_id"] != patient_id:
            return False
        if status is not None and c["status"] != status:
            return False
        if sp_id is not None and c["surgical_procedure_id"] != sp_id:
            return False
        if ep_id is not None and c["linked_device_episode_id"] != ep_id:
            return False
        return True

    items = [c for c in db.infection_cases.values() if _match(c)]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([case_view(c) for c in page], total, limit, offset)


@bp.get("/api/infection-cases/<cid>")
def get_case(cid):
    require_roles(ALL_ROLES)
    c = db.infection_cases.get(cid)
    if c is None:
        raise_err(ERR_INFECTION_CASE_NOT_FOUND, "infection case id does not exist")
    return success_object(case_view(c))


@bp.post("/api/infection-cases/<cid>/begin-review")
def begin_review(cid):
    require_roles(["InfectionPreventionist"])
    c = db.infection_cases.get(cid)
    if c is None:
        raise_err(ERR_INFECTION_CASE_NOT_FOUND, "infection case id does not exist")
    if c["status"] not in ("SUSPECTED", "REOPENED"):
        raise_err(ERR_CASE_NOT_REVIEWABLE, "begin-review requires status SUSPECTED or REOPENED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(case_view(c))


def _attribute_unit(patient, doe):
    """Transfer-out rule (calculation date_of_event_unit_attribution, step 4)."""
    covering = None
    for s in patient["unit_stays"]:
        arrived = s["arrived_at"]
        departed = s["departed_at"]
        if arrived <= doe and (departed is None or doe < departed):
            covering = s
            break
    if covering is None:
        return patient["unit_id"]
    doe_date = cal_date(doe)
    if cal_date(covering["arrived_at"]) == doe_date:
        # find previous stay whose departure calendar date equals DOE date
        idx = patient["unit_stays"].index(covering)
        if idx > 0:
            prev = patient["unit_stays"][idx - 1]
            if prev["departed_at"] is not None and cal_date(prev["departed_at"]) == doe_date:
                return prev["unit_id"]
    return covering["unit_id"]


@bp.post("/api/infection-cases/<cid>/adjudicate")
def adjudicate(cid):
    user_id, _ = require_roles(["InfectionPreventionist"])
    b = body()

    # Schema tier (priority 3) — before path existence (priority 4).
    if "outcome" not in b or b["outcome"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: outcome")
    outcome = req_enum(b, "outcome", ADJUDICATE_OUTCOMES)
    rationale = req_string(b, "rationale", min_len=10)
    if outcome == "ADJUDICATED_HAI":
        if b.get("date_of_event") is None:
            raise_err(ERR_INVALID_REQUEST, "date_of_event is required for ADJUDICATED_HAI")
    else:
        if b.get("date_of_event") is not None:
            raise_err(ERR_INVALID_REQUEST, "date_of_event must be absent when outcome is RULED_OUT")
    doe = None
    if b.get("date_of_event") is not None:
        doe = req_dt(b, "date_of_event")
    ssi_depth = b.get("ssi_depth")
    if ssi_depth is not None and ssi_depth not in SSI_DEPTHS:
        raise_err(ERR_INVALID_REQUEST, "ssi_depth must be SURFACE | DEEP | ORGAN_SPACE")

    # Existence tier (priority 4)
    c = db.infection_cases.get(cid)
    if c is None:
        raise_err(ERR_INFECTION_CASE_NOT_FOUND, "infection case id does not exist")

    # Conditional schema that depends on the case (case_type) — evaluated at the
    # schema tier relative to other rules but necessarily after case resolution.
    if outcome == "ADJUDICATED_HAI" and c["case_type"] == "SSI":
        if ssi_depth is None:
            raise_err(ERR_INVALID_REQUEST, "ssi_depth is required when adjudicating SSI to ADJUDICATED_HAI")
    else:
        if ssi_depth is not None:
            raise_err(ERR_INVALID_REQUEST, "ssi_depth must be absent unless adjudicating an SSI case to ADJUDICATED_HAI")

    # State tier
    if c["status"] != "UNDER_REVIEW":
        raise_err(ERR_CASE_NOT_ADJUDICATABLE, "adjudicate requires status UNDER_REVIEW")

    patient = db.patients[c["patient_id"]]

    if outcome == "RULED_OUT":
        c["status"] = "RULED_OUT"
        c["is_hai"] = False
        c["adjudicated_by_user_id"] = user_id
        c["adjudication_rationale"] = rationale
        touch(c)
        return success_object(case_view(c))

    # outcome == ADJUDICATED_HAI — temporal rules in pinned sub-order (b)-(e).
    # (b) DOE inside IWP
    if not (c["infection_window_start"] <= doe <= c["infection_window_end"]):
        raise_err(ERR_DOE_OUTSIDE_IWP, "date_of_event outside infection window period")
    # (c) HAI day rule: admit date = day 1; DOE date >= admit date + 2 days
    admit_date = cal_date(patient["admitted_at"])
    if cal_date(doe) < admit_date + timedelta(days=2):
        raise_err(ERR_DOE_NOT_HAI_DAY_RULE, "date_of_event before admission date + 2 days")
    # (d) SSI surveillance window
    if c["case_type"] == "SSI":
        proc = db.surgical_procedures[c["surgical_procedure_id"]]
        window = 90 if proc["implant"] else 30
        proc_date = cal_date(proc["performed_at"])
        if cal_date(doe) > proc_date + timedelta(days=window - 1):
            raise_err(ERR_SSI_WINDOW_EXPIRED, "date_of_event beyond the SSI surveillance window")
    # (e) device day rule
    if c["case_type"] in ("CLABSI", "CAUTI"):
        ep = db.device_episodes[c["linked_device_episode_id"]]
        placed_date = cal_date(ep["placed_at"])
        doe_date = cal_date(doe)
        placed_ok = placed_date <= doe_date - timedelta(days=2)
        covers = ep["placed_at"] <= doe and (ep["removed_at"] is None or ep["removed_at"] >= doe)
        if not (placed_ok and covers):
            raise_err(ERR_DEVICE_DAY_RULE_NOT_MET, "device episode not placed >= 2 days before DOE or not covering DOE")

    # Unit attribution (transfer-out rule)
    attributed_unit = _attribute_unit(patient, doe)

    # Covering-summary lock (priority 5.5): case unit at attribution, month of DOE
    covering = find_covering_summary(attributed_unit, doe)
    if covering is not None and covering["status"] not in MUTABLE_SUMMARY_STATUSES:
        raise_err(ERR_SUMMARY_LOCKED, "covering MonthlySummary is locked for this unit-month")

    # Commit the adjudication
    doe_date = cal_date(doe)
    c["date_of_event"] = doe
    c["is_hai"] = True
    c["rit_blocked_until"] = end_of_day_utc(doe_date + timedelta(days=13))
    c["adjudicated_by_user_id"] = user_id
    c["adjudication_rationale"] = rationale
    if c["case_type"] == "SSI":
        c["ssi_depth"] = ssi_depth
    c["unit_id"] = attributed_unit
    c["status"] = "ADJUDICATED_HAI"
    touch(c)

    # Cascade: summary recompute then cluster detection (which may recompute posture)
    if covering is not None and covering["status"] in MUTABLE_SUMMARY_STATUSES:
        recompute_summary(covering)
    run_cluster_detection(attributed_unit, c["suspected_organism"])

    return success_object(case_view(c))


@bp.post("/api/infection-cases/<cid>/reopen")
def reopen_case(cid):
    require_roles(["InfectionPreventionist"])
    b = body()
    if "reason" not in b or b["reason"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reason")
    req_string(b, "reason", min_len=10)
    c = db.infection_cases.get(cid)
    if c is None:
        raise_err(ERR_INFECTION_CASE_NOT_FOUND, "infection case id does not exist")

    if c["status"] not in ("ADJUDICATED_HAI", "RULED_OUT"):
        raise_err(ERR_CASE_NOT_REOPENABLE, "reopen requires status ADJUDICATED_HAI or RULED_OUT")

    # Covering summary: month of DOE for adjudicated; month of specimen for ruled out
    if c["status"] == "ADJUDICATED_HAI":
        anchor = c["date_of_event"]
    else:
        anchor = c["first_positive_specimen_at"]
    covering = find_covering_summary(c["unit_id"], anchor)
    if covering is not None and covering["status"] not in MUTABLE_SUMMARY_STATUSES:
        raise_err(ERR_SUMMARY_LOCKED, "covering MonthlySummary is locked for this unit-month")

    c["date_of_event"] = None
    c["is_hai"] = None
    c["rit_blocked_until"] = None
    c["status"] = "REOPENED"
    touch(c)

    if covering is not None and covering["status"] in MUTABLE_SUMMARY_STATUSES:
        recompute_summary(covering)

    return success_object(case_view(c))
