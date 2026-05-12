"""Evidence + custody chain + rebuttal endpoints."""

import clock
import db
import errors
import helpers
import response
import serializers
from flask import Blueprint
from middleware import auth_required, get_actor, acting_lawyer
from services import audit, posture


bp = Blueprint("evidence", __name__)


VALID_EVIDENCE_TYPES = {"DOCUMENTARY", "PHYSICAL", "DIGITAL", "TESTIMONIAL"}
VALID_CUSTODY_ACTIONS = {"COLLECTED", "TRANSFERRED", "EXAMINED", "SUBMITTED", "RETURNED"}


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


def _custody_chain(evidence_id):
    return sorted(
        (ce for ce in db.custody_events.values() if ce["evidence_id"] == evidence_id),
        key=lambda ce: ce["occurred_at"],
    )


@bp.route("/evidence", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def create_evidence():
    body = helpers.get_json_body()
    case_id = helpers.require_str(body, "case_id")
    evidence_type = helpers.require_enum(body, "evidence_type", VALID_EVIDENCE_TYPES)
    if "collected_at" not in body:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "collected_at is required.")
    try:
        collected_at = clock.parse_iso(body["collected_at"])
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "collected_at must be ISO 8601.")
    collected_by_lawyer_id = helpers.require_str(body, "collected_by_lawyer_id")
    case_fact_refs = body.get("case_fact_refs", []) or []
    if not isinstance(case_fact_refs, list):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "case_fact_refs must be an array.")

    case = db.cases.get(case_id)
    if case is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Case {case_id} not found.")
    _ensure_not_archived(case)
    if collected_by_lawyer_id not in db.lawyers:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, "collected_by_lawyer_id not found.")

    if case["posture"] == "FROZEN":
        errors.raise_error(errors.ERR_CASE_POSTURE_FROZEN, "Case is FROZEN; cannot create evidence.")

    eid = db.new_id()
    common = helpers.common_create()
    evidence = {
        "id": eid,
        "case_id": case_id,
        "evidence_type": evidence_type,
        "collected_at": collected_at,
        "collected_by_lawyer_id": collected_by_lawyer_id,
        "case_fact_refs": list(case_fact_refs),
        "status": "COLLECTED",
        "submitted_at": None,
        "rebuttal_count": 0,
        **common,
    }
    db.evidence_rows[eid] = evidence

    # Auto-append the initial custody event.
    cev_id = db.new_id()
    cev = {
        "id": cev_id,
        "evidence_id": eid,
        "actor_lawyer_id": collected_by_lawyer_id,
        "action": "COLLECTED",
        "occurred_at": collected_at,
        "location": None,
        "created_at": clock.now(),
    }
    db.custody_events[cev_id] = cev

    audit.append(
        subject_type="EVIDENCE", subject_id=eid, action="EVIDENCE_COLLECTED",
        payload_snapshot={"evidence_type": evidence_type},
    )
    posture.recompute(case)
    return response.created(serializers.evidence_dict(evidence))


@bp.route("/evidence/<eid>/custody-events", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def append_custody_event(eid):
    evidence = db.evidence_rows.get(eid)
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Evidence {eid} not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)

    body = helpers.get_json_body()
    actor_lawyer_id = helpers.require_str(body, "actor_lawyer_id")
    action = helpers.require_enum(body, "action", VALID_CUSTODY_ACTIONS)
    if "occurred_at" not in body:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "occurred_at is required.")
    try:
        occurred_at = clock.parse_iso(body["occurred_at"])
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "occurred_at must be ISO 8601.")
    location = body.get("location")
    if location is not None and not isinstance(location, str):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "location must be a string.")

    if actor_lawyer_id not in db.lawyers:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, "actor_lawyer_id not found.")

    chain = _custody_chain(eid)
    if chain:
        latest = chain[-1]
        if occurred_at <= latest["occurred_at"]:
            errors.raise_error(
                errors.ERR_CUSTODY_CHAIN_BROKEN,
                "occurred_at must be strictly greater than the previous custody event.",
            )

    cid = db.new_id()
    cev = {
        "id": cid,
        "evidence_id": eid,
        "actor_lawyer_id": actor_lawyer_id,
        "action": action,
        "occurred_at": occurred_at,
        "location": location,
        "created_at": clock.now(),
    }
    db.custody_events[cid] = cev

    # Bump evidence version since the chain materially changed.
    helpers.bump(evidence)
    audit.append(
        subject_type="CUSTODY_EVENT", subject_id=cid, action="CUSTODY_APPENDED",
        payload_snapshot={"action": action},
    )
    return response.created(serializers.custody_event_dict(cev))


@bp.route("/evidence/<eid>/submit", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def submit_evidence(eid):
    evidence = db.evidence_rows.get(eid)
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Evidence {eid} not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(evidence, body.get("version"))

    if evidence["status"] != "COLLECTED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Evidence must be COLLECTED to submit.")
    if case is None or case["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Parent case must be ACTIVE.")
    if case["posture"] not in {"OPEN", "RESTRICTED"}:
        errors.raise_error(errors.ERR_INVALID_STATE, "Case posture must be OPEN or RESTRICTED.")

    chain = _custody_chain(eid)
    # Strict-increasing already ensured at append; verify again for race safety
    # and the additional rule: last action must not be RETURNED.
    for i in range(1, len(chain)):
        if chain[i]["occurred_at"] <= chain[i - 1]["occurred_at"]:
            errors.raise_error(
                errors.ERR_CUSTODY_CHAIN_BROKEN,
                "Custody chain is not strictly increasing.",
            )
    if chain and chain[-1]["action"] == "RETURNED":
        errors.raise_error(
            errors.ERR_CUSTODY_CHAIN_BROKEN,
            "Last custody event is RETURNED; evidence cannot be submitted.",
        )

    if evidence["collected_at"] > clock.now():
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "collected_at must be <= now.",
        )

    now = clock.now()
    evidence["submitted_at"] = now
    evidence["status"] = "SUBMITTED"
    helpers.bump(evidence)

    # Append a SUBMITTED custody event by acting lawyer.
    user_id, _ = get_actor()
    actor = user_id
    cid = db.new_id()
    submit_time = now
    if chain and submit_time <= chain[-1]["occurred_at"]:
        # Defensive: ensure strictly increasing even when wall clock collides.
        from datetime import timedelta
        submit_time = chain[-1]["occurred_at"] + timedelta(microseconds=1000)
    cev = {
        "id": cid,
        "evidence_id": eid,
        "actor_lawyer_id": actor,
        "action": "SUBMITTED",
        "occurred_at": submit_time,
        "location": None,
        "created_at": clock.now(),
    }
    db.custody_events[cid] = cev

    audit.append(
        subject_type="EVIDENCE", subject_id=eid, action="EVIDENCE_SUBMITTED",
    )
    posture.recompute(case)
    return response.ok(serializers.evidence_dict(evidence))


@bp.route("/evidence/<eid>/exclude", methods=["POST"])
@auth_required("PartnerLawyer")
def exclude_evidence(eid):
    evidence = db.evidence_rows.get(eid)
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Evidence {eid} not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(evidence, body.get("version"))

    if evidence["status"] != "COLLECTED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Partner-veto exclude requires COLLECTED.")

    evidence["status"] = "EXCLUDED"
    helpers.bump(evidence)
    audit.append(
        subject_type="EVIDENCE", subject_id=eid, action="EVIDENCE_EXCLUDED",
    )
    if case is not None:
        posture.recompute(case)
    return response.ok(serializers.evidence_dict(evidence))


@bp.route("/evidence/<eid>/rebuttals", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def file_rebuttal(eid):
    evidence = db.evidence_rows.get(eid)
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Evidence {eid} not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)

    body = helpers.get_json_body()
    filed_by_lawyer_id = helpers.require_str(body, "filed_by_lawyer_id")
    ground = helpers.require_str(body, "ground", min_len=1, max_len=500)

    if filed_by_lawyer_id not in db.lawyers:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, "filed_by_lawyer_id not found.")

    if evidence["status"] not in {"SUBMITTED", "REBUTTED"}:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Rebuttal can only be filed against SUBMITTED or REBUTTED evidence.",
        )

    rid = db.new_id()
    now = clock.now()
    rebuttal = {
        "id": rid,
        "evidence_id": eid,
        "filed_by_lawyer_id": filed_by_lawyer_id,
        "ground": ground,
        "status": "OPEN",
        "created_at": now,
    }
    db.evidence_rebuttals[rid] = rebuttal

    evidence["rebuttal_count"] = evidence["rebuttal_count"] + 1
    if evidence["status"] == "SUBMITTED":
        evidence["status"] = "REBUTTED"
        audit.append(
            subject_type="EVIDENCE", subject_id=eid, action="EVIDENCE_REBUTTED",
        )
    helpers.bump(evidence)

    if case is not None:
        posture.recompute(case)
    return response.created(serializers.rebuttal_dict(rebuttal))


def _resolve_evidence_after_rebuttal_change(evidence):
    """After a rebuttal status change, possibly transition evidence:
       - If all rebuttals on this evidence are resolved (UPHELD/DISMISSED),
         and any are UPHELD, the evidence transitions to EXCLUDED.
         Otherwise (only DISMISSED), evidence falls back to SUBMITTED.
    """
    rebuttals = [r for r in db.evidence_rebuttals.values() if r["evidence_id"] == evidence["id"]]
    if not rebuttals:
        return
    if any(r["status"] == "OPEN" for r in rebuttals):
        return  # Not fully resolved.

    if any(r["status"] == "UPHELD" for r in rebuttals):
        if evidence["status"] != "EXCLUDED":
            evidence["status"] = "EXCLUDED"
            helpers.bump(evidence)
            audit.append(
                subject_type="EVIDENCE", subject_id=evidence["id"],
                action="EVIDENCE_EXCLUDED",
            )
    else:
        if evidence["status"] == "REBUTTED":
            evidence["status"] = "SUBMITTED"
            helpers.bump(evidence)


@bp.route("/rebuttals/<rid>/uphold", methods=["POST"])
@auth_required("PartnerLawyer")
def uphold_rebuttal(rid):
    rebuttal = db.evidence_rebuttals.get(rid)
    if rebuttal is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Rebuttal {rid} not found.")
    evidence = db.evidence_rows.get(rebuttal["evidence_id"])
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Underlying evidence not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)

    if rebuttal["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only OPEN rebuttals can be upheld.")

    rebuttal["status"] = "UPHELD"
    _resolve_evidence_after_rebuttal_change(evidence)

    if case is not None:
        posture.recompute(case)
    return response.ok(serializers.rebuttal_dict(rebuttal))


@bp.route("/rebuttals/<rid>/dismiss", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def dismiss_rebuttal(rid):
    rebuttal = db.evidence_rebuttals.get(rid)
    if rebuttal is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Rebuttal {rid} not found.")
    evidence = db.evidence_rows.get(rebuttal["evidence_id"])
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Underlying evidence not found.")
    case = db.cases.get(evidence["case_id"])
    if case is not None:
        _ensure_not_archived(case)

    if rebuttal["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only OPEN rebuttals can be dismissed.")

    rebuttal["status"] = "DISMISSED"
    _resolve_evidence_after_rebuttal_change(evidence)

    if case is not None:
        posture.recompute(case)
    return response.ok(serializers.rebuttal_dict(rebuttal))


@bp.route("/evidence/<eid>", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def read_evidence(eid):
    evidence = db.evidence_rows.get(eid)
    if evidence is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Evidence {eid} not found.")
    return response.ok(serializers.evidence_dict(evidence))
