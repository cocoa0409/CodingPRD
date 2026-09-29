"""Conflict identification, prior-rights adjudication, permitting and joint trench
declaration (PRD sections 3.3, 3.4, 3.6)."""
from flask import Blueprint

import calc
import db as store
import enums
import serializers as ser
import services
from errors import ApiError
from middleware import authenticate, check_owner_scope, must_get, owner_id_of_determination
from response import created, ok
from validation import (bad, body_json, field_datetime, field_enum, field_id, field_int,
                        field_number, field_str)

bp = Blueprint("conflicts_write", __name__)


# ============================================================ conflicts ======

@bp.post("/uro/conflicts")
def create_conflict():
    authenticate(("UtilityCoordinator",))
    body = body_json()
    project_id = field_id(body, "project_id")
    facility_id = field_id(body, "facility_id")
    field_number(body, "conflict_station", minimum=0)
    deficiency = field_int(body, "clearance_deficiency_in", minimum=0)
    depends_on = field_id(body, "depends_on_conflict_id", required=False)

    project = must_get("project", project_id)
    must_get("facility", facility_id)
    if depends_on is not None:
        must_get("conflict", depends_on)
    services.guard_project_open(project)

    rec = store.base_record()
    rec.update({
        "project_id": project_id,
        "facility_id": facility_id,
        "depends_on_conflict_id": depends_on,
        "conflict_station": body["conflict_station"],
        "clearance_deficiency_in": deficiency,
        "resolution_type": None,
        "state_share_pct": None,
        "status": "IDENTIFIED",
    })
    store.db.conflicts[rec["id"]] = rec

    if project["status"] in ("PLANNING", "LETTING_READY"):
        project["status"] = "CLEARANCE_ACTIVE"
    services.recompute_project(project)
    return created(ser.conflict_out(rec))


@bp.post("/uro/conflicts/<conflict_id>/set-resolution")
def set_resolution(conflict_id):
    authenticate(("UtilityCoordinator",))
    body = body_json()
    resolution_type = field_enum(body, "resolution_type", enums.RESOLUTION_TYPE)

    conflict = must_get("conflict", conflict_id)
    if conflict["status"] != "IDENTIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A resolution may only be selected while the conflict is IDENTIFIED.")
    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    conflict["resolution_type"] = resolution_type
    conflict["status"] = "RESOLUTION_SELECTED"
    services.touch(conflict)
    services.recompute_project(project)
    return ok(ser.conflict_out(conflict))


@bp.post("/uro/conflicts/<conflict_id>/certify-cleared")
def certify_cleared(conflict_id):
    authenticate(("UtilityCoordinator",))
    body = body_json()
    field_str(body, "certification_note", required=False, min_len=0, max_len=2000,
              allow_blank=True)

    conflict = must_get("conflict", conflict_id)
    resolution = conflict["resolution_type"]
    relocate_branch = resolution == "RELOCATE"

    if relocate_branch:
        if conflict["status"] != "RELOCATION_SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A relocated conflict may only be certified from RELOCATION_SCHEDULED.")
        completed = [c for c in store.commitments_of_conflict(conflict_id)
                     if c["status"] == "COMPLETE"]
        if not completed:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No schedule commitment of the conflict has reached COMPLETE.")
    elif resolution in ("PROTECT_IN_PLACE", "ABANDON", "NO_CONFLICT"):
        if conflict["status"] != "RESOLUTION_SELECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A non-relocation conflict may only be certified from "
                           "RESOLUTION_SELECTED.")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The conflict has no selected resolution type.")

    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    if conflict["depends_on_conflict_id"] is not None:
        predecessor = store.db.conflicts.get(conflict["depends_on_conflict_id"])
        if predecessor is None or predecessor["status"] != "CLEARED":
            raise ApiError("ERR_DEPENDENCY_NOT_CLEARED",
                           "The predecessor conflict is not CLEARED.")

    conflict["status"] = "CLEARED"
    services.touch(conflict)

    if relocate_branch:
        for determination in store.determinations_of_conflict(conflict_id):
            if determination["status"] == "ISSUED":
                determination["status"] = "FINAL"
                services.touch(determination)

    services.recompute_project(project)
    return ok(ser.conflict_out(conflict))


# ========================================================= prior rights ======

def _recompute_provisional(determination):
    variant, provisional, _current = calc.determination_shares(determination)
    determination["evidence_variant"] = variant
    determination["provisional_state_share_pct"] = provisional


@bp.post("/uro/prior-rights")
def create_determination():
    authenticate(("RightOfWayAdjudicator",))
    body = body_json()
    conflict_id = field_id(body, "conflict_id")
    claimed_basis = field_enum(body, "claimed_basis", enums.OCCUPANCY_BASIS)
    narrative = field_str(body, "narrative", min_len=1, max_len=2000)

    conflict = must_get("conflict", conflict_id)
    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    rec = store.base_record()
    rec.update({
        "conflict_id": conflict_id,
        "claimed_basis": claimed_basis,
        "narrative": narrative,
        "evidence_variant": None,
        "provisional_state_share_pct": 0,
        "final_state_share_pct": None,
        "appeal_round": 0,
        "first_issued_by_user_id": None,
        "status": "DRAFT",
    })
    _recompute_provisional(rec)
    store.db.determinations[rec["id"]] = rec
    return created(ser.determination_out(rec))


@bp.post("/uro/prior-rights/<determination_id>/submit-for-review")
def submit_determination(determination_id):
    authenticate(("RightOfWayAdjudicator",))
    body_json()
    determination = must_get("determination", determination_id)
    if determination["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A determination may only be submitted for review from DRAFT.")
    conflict = store.db.conflicts.get(determination["conflict_id"])
    services.guard_project_open(store.project_of_conflict(conflict) if conflict else None)

    determination["status"] = "UNDER_REVIEW"
    services.touch(determination)
    return ok(ser.determination_out(determination))


@bp.post("/uro/prior-rights/<determination_id>/return-for-revision")
def return_determination(determination_id):
    authenticate(("RightOfWayAdjudicator",))
    body = body_json()
    field_str(body, "revision_note", min_len=1, max_len=2000)

    determination = must_get("determination", determination_id)
    if determination["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A determination may only be returned from UNDER_REVIEW.")
    conflict = store.db.conflicts.get(determination["conflict_id"])
    services.guard_project_open(store.project_of_conflict(conflict) if conflict else None)

    determination["status"] = "RETURNED_FOR_REVISION"
    services.touch(determination)
    return ok(ser.determination_out(determination))


@bp.post("/uro/prior-rights/<determination_id>/revise")
def revise_determination(determination_id):
    authenticate(("RightOfWayAdjudicator",))
    body = body_json()
    claimed_basis = field_enum(body, "claimed_basis", enums.OCCUPANCY_BASIS, required=False)
    narrative = field_str(body, "narrative", required=False, min_len=1, max_len=2000)

    determination = must_get("determination", determination_id)
    if determination["status"] not in ("RETURNED_FOR_REVISION", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a returned or appealed determination may be revised.")
    conflict = store.db.conflicts.get(determination["conflict_id"])
    services.guard_project_open(store.project_of_conflict(conflict) if conflict else None)

    if claimed_basis is not None:
        determination["claimed_basis"] = claimed_basis
    if narrative is not None:
        determination["narrative"] = narrative
    determination["status"] = "DRAFT"
    variant, provisional, _current = calc.determination_shares(determination,
                                                              force_variant="RECORD_BASIS")
    determination["evidence_variant"] = variant
    determination["provisional_state_share_pct"] = provisional
    services.touch(determination)
    return ok(ser.determination_out(determination))


@bp.post("/uro/prior-rights/<determination_id>/issue")
def issue_determination(determination_id):
    user_id, _role = authenticate(("RightOfWayAdjudicator",))
    body_json()
    determination = must_get("determination", determination_id)

    # rung 7: segregation of duties on any re-issue that followed an appeal
    if determination["appeal_round"] >= 1 \
            and determination["first_issued_by_user_id"] is not None \
            and determination["first_issued_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The adjudicator who first issued this determination may not re-issue it.")

    if determination["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A determination may only be issued from UNDER_REVIEW.")
    conflict = store.db.conflicts.get(determination["conflict_id"])
    allowed_conflict_states = ("RESOLUTION_SELECTED",)
    if determination["appeal_round"] >= 1:
        allowed_conflict_states = ("RESOLUTION_SELECTED", "RESPONSIBILITY_SET")
    if conflict is None or conflict["status"] not in allowed_conflict_states:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The conflict is not in a state that accepts an issued determination.")

    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    variant, _provisional, current = calc.determination_shares(determination)
    determination["evidence_variant"] = variant
    determination["final_state_share_pct"] = current
    determination["status"] = "ISSUED"
    if determination["first_issued_by_user_id"] is None:
        determination["first_issued_by_user_id"] = user_id
    services.touch(determination)

    conflict["state_share_pct"] = current
    if conflict["status"] == "RESOLUTION_SELECTED":
        conflict["status"] = "RESPONSIBILITY_SET"
    services.touch(conflict)
    services.recompute_project(project)
    return ok(ser.determination_out(determination))


@bp.post("/uro/prior-rights/<determination_id>/appeal")
def appeal_determination(determination_id):
    authenticate(("UtilityOwnerRep",))
    body = body_json()
    field_str(body, "appeal_note", min_len=1, max_len=2000)

    determination = must_get("determination", determination_id)
    check_owner_scope(owner_id_of_determination(determination))

    if determination["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an ISSUED determination may be appealed.")
    conflict = store.db.conflicts.get(determination["conflict_id"])
    services.guard_project_open(store.project_of_conflict(conflict) if conflict else None)

    if determination["appeal_round"] >= calc.APPEAL_LIMIT:
        raise ApiError("ERR_APPEAL_LIMIT_EXCEEDED",
                       "The determination has already been appealed once.")

    determination["appeal_round"] += 1
    determination["status"] = "APPEALED"
    services.touch(determination)
    return ok(ser.determination_out(determination))


# ============================================================== permits ======

@bp.post("/uro/permits")
def create_permit():
    authenticate(("UtilityCoordinator",))
    body = body_json()
    conflict_id = field_id(body, "conflict_id")
    permit_type = field_enum(body, "permit_type", enums.PERMIT_TYPE)
    expires_raw, _expires_dt = field_datetime(body, "expires_on")

    conflict = must_get("conflict", conflict_id)
    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    rec = store.base_record()
    rec.update({
        "conflict_id": conflict_id,
        "permit_type": permit_type,
        "applied_on": store.db.clock_raw,
        "granted_on": None,
        "expires_on": expires_raw,
        "decision_note": None,
        "status": "APPLIED",
    })
    store.db.permits[rec["id"]] = rec
    return created(ser.permit_out(rec))


@bp.post("/uro/permits/<permit_id>/decide")
def decide_permit(permit_id):
    authenticate(("UtilityCoordinator",))
    body = body_json()
    decision = field_enum(body, "decision", enums.PERMIT_DECISION)
    note = field_str(body, "decision_note", required=False, min_len=0, max_len=500,
                     allow_blank=True)

    permit = must_get("permit", permit_id)
    if permit["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The permit record has already been decided.")
    conflict = store.db.conflicts.get(permit["conflict_id"])
    services.guard_project_open(store.project_of_conflict(conflict) if conflict else None)

    if note is not None:
        permit["decision_note"] = note
    if decision == "GRANT":
        permit["status"] = "GRANTED"
        permit["granted_on"] = store.db.clock_raw
    else:
        permit["status"] = "DENIED"
    services.touch(permit)
    return ok(ser.permit_out(permit))


# =================================================== joint trench slots ======

@bp.post("/uro/joint-trench-slots")
def create_slot():
    authenticate(("ConstructionEngineer",))
    body = body_json()
    project_id = field_id(body, "project_id")
    segment_code = field_str(body, "segment_code", min_len=1, max_len=24)
    start_raw, start_dt = field_datetime(body, "trench_open_start")
    end_raw, end_dt = field_datetime(body, "trench_open_end")
    if end_dt <= start_dt:
        bad("Field 'trench_open_end' must be strictly later than 'trench_open_start'.")
    max_occupants = field_int(body, "max_occupants", minimum=1)

    project = must_get("project", project_id)
    services.guard_project_open(project)

    rec = store.base_record()
    rec.update({
        "project_id": project_id,
        "segment_code": segment_code,
        "trench_open_start": start_raw,
        "trench_open_end": end_raw,
        "_trench_open_start_dt": start_dt,
        "_trench_open_end_dt": end_dt,
        "max_occupants": max_occupants,
    })
    store.db.slots[rec["id"]] = rec
    return created(ser.slot_out(rec))
