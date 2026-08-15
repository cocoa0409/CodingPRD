"""CathCase endpoints, including STEMI activation and AUC attestation."""
from flask import Blueprint, g, request

from db import STORE, logical_now
from errors import (
    ApiError,
    ERR_AUC_ORDERING_CONFLICT,
    ERR_AUC_REQUIRED,
    ERR_BED_INVALID_STATE,
    ERR_BED_NOT_FOUND,
    ERR_CASE_INVALID_STATE,
    ERR_CASE_NOT_FOUND,
    ERR_EQUIPMENT_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_NO_RECOVERY_BED,
    ERR_NO_STEMI_ROOM,
    ERR_NOT_PERFORMING_PHYSICIAN,
    ERR_ROOM_NOT_ACTIVE,
    ERR_ROOM_NOT_FOUND,
    ERR_ROOM_WINDOW_CONFLICT,
    ERR_STAFF_NOT_FOUND,
    ERR_STAFF_ROLE_MISMATCH,
    ERR_STAFFING_INCOMPLETE,
    ERR_STALE_CASE_VERSION,
)
from helpers import (
    AUC_SCORES,
    PRIORITIES,
    PROCEDURE_TYPES,
    get_payload,
    is_int_valued,
    new_id,
    opt_code_list,
    paginate,
    req_dt,
    req_enum,
    req_num,
    req_str,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import (
    bump_case,
    case_out,
    compute_case_end,
    compute_contrast_limit_ml,
    new_entity,
    occupy_bed_for_case,
    release_assignments_for_case,
    release_bed_for_case,
    release_usages_for_case,
    reserve_bed_for_case,
    room_window_conflict,
    select_recovery_bed,
    select_stemi_room,
    touch,
)

bp = Blueprint("cases", __name__)


def _get_case_or_404(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    return case


def _base_case_dict(data):
    return {
        "patient_mrn": data["patient_mrn"],
        "procedure_type": data["procedure_type"],
        "priority": data["priority"],
        "performing_physician_id": data["performing_physician_id"],
        "weight_kg": data["weight_kg"],
        "serum_creatinine": data["serum_creatinine"],
        "equipment_needs": data["equipment_needs"],
        "lab_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "actual_start": None,
        "actual_end": None,
        "contrast_limit_ml": compute_contrast_limit_ml(
            data["weight_kg"], data["serum_creatinine"]
        ),
        "cumulative_contrast_ml": 0,
        "cumulative_radiation_mgy": 0,
        "radiation_alert": False,
        "bump_count": 0,
        "auc_status": "NOT_DOCUMENTED",
        "auc_score": None,
        "auc_criterion_code": None,
        "ordering_physician_id": None,
        "status": "POSTED",
    }


@bp.route("/cath-lab/cases", methods=["POST"])
@require_roles("CathLabScheduler", "InterventionalCardiologist")
def create_case():
    data = get_payload()
    # Priority 3: body FK existence before remaining shape checks.
    physician_ref = data.get("performing_physician_id")
    physician = None
    if isinstance(physician_ref, str):
        physician = STORE["staff"].get(physician_ref)
        if physician is None:
            raise ApiError(
                ERR_STAFF_NOT_FOUND,
                "No StaffMember with the given performing_physician_id",
                404,
            )
    # Priority 4: request shape.
    patient_mrn = req_str(data, "patient_mrn")
    procedure_type = req_enum(data, "procedure_type", PROCEDURE_TYPES)
    priority = req_enum(data, "priority", PRIORITIES)
    performing_physician_id = req_str(data, "performing_physician_id")
    weight_kg = req_num(data, "weight_kg", gt=0)
    serum_creatinine = req_num(data, "serum_creatinine", gt=0)
    equipment_needs = opt_code_list(data, "equipment_needs")
    scheduled_start = None
    if priority == "STEMI":
        scheduled_start = req_dt(data, "scheduled_start")
    elif data.get("scheduled_start") is not None:
        # Tolerated but ignored for ELECTIVE/URGENT postings (created POSTED).
        scheduled_start = req_dt(data, "scheduled_start")
        scheduled_start = None
    # Priority 8: performing physician must be an INTERVENTIONAL_CARDIOLOGIST.
    if physician["staff_role"] != "INTERVENTIONAL_CARDIOLOGIST":
        raise ApiError(
            ERR_STAFF_ROLE_MISMATCH,
            "performing_physician_id must reference an INTERVENTIONAL_CARDIOLOGIST",
            422,
        )

    fields = {
        "patient_mrn": patient_mrn,
        "procedure_type": procedure_type,
        "priority": priority,
        "performing_physician_id": performing_physician_id,
        "weight_kg": weight_kg,
        "serum_creatinine": serum_creatinine,
        "equipment_needs": equipment_needs,
    }

    if priority != "STEMI":
        case = new_entity()
        case["id"] = new_id()
        case.update(_base_case_dict(fields))
        STORE["cases"][case["id"]] = case
        return success(case_out(case), 201)

    # ---- STEMI activation (PRD 3.2) ----
    scheduled_end = compute_case_end(procedure_type, priority, equipment_needs, scheduled_start)
    selected = select_stemi_room(equipment_needs, scheduled_start, scheduled_end)
    if selected is None:
        raise ApiError(
            ERR_NO_STEMI_ROOM,
            "No eligible room for STEMI activation",
            409,
        )
    room, victims = selected
    bed = select_recovery_bed()
    if bed is None:
        raise ApiError(ERR_NO_RECOVERY_BED, "No AVAILABLE recovery bed", 409)

    # Both selectors succeeded; now persist and apply side effects atomically.
    case = new_entity()
    case["id"] = new_id()
    case.update(_base_case_dict(fields))
    case["status"] = "SCHEDULED"
    case["lab_id"] = room["id"]
    case["scheduled_start"] = scheduled_start
    case["scheduled_end"] = scheduled_end
    STORE["cases"][case["id"]] = case
    reserve_bed_for_case(bed, case)
    for victim in victims:
        bump_case(victim)
    return success(case_out(case), 201)


@bp.route("/cath-lab/cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cases():
    status = request.args.get("status")
    priority = request.args.get("priority")
    lab_id = request.args.get("lab_id")
    performing_physician_id = request.args.get("performing_physician_id")
    ordering_physician_id = request.args.get("ordering_physician_id")
    items = []
    for c in STORE["cases"].values():
        if status is not None and c["status"] != status:
            continue
        if priority is not None and c["priority"] != priority:
            continue
        if lab_id is not None and c["lab_id"] != lab_id:
            continue
        if performing_physician_id is not None and c["performing_physician_id"] != performing_physician_id:
            continue
        if ordering_physician_id is not None and c["ordering_physician_id"] != ordering_physician_id:
            continue
        items.append(c)
    items.sort(key=lambda c: c["_seq"])
    page, pg = paginate(items)
    return success([case_out(c) for c in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/cases/<case_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_case(case_id):
    return success(case_out(_get_case_or_404(case_id)), 200)


@bp.route("/cath-lab/cases/<case_id>/schedule", methods=["POST"])
@require_roles("CathLabScheduler")
def schedule_case(case_id):
    case = _get_case_or_404(case_id)
    data = get_payload()
    # Priority 3: body FK existence, in listed order (lab_id, then bed_id).
    lab_ref = data.get("lab_id")
    room = None
    if isinstance(lab_ref, str):
        room = STORE["rooms"].get(lab_ref)
        if room is None:
            raise ApiError(ERR_ROOM_NOT_FOUND, "No CathLabRoom with the given lab_id", 404)
    bed_ref = data.get("bed_id")
    bed = None
    if isinstance(bed_ref, str):
        bed = STORE["beds"].get(bed_ref)
        if bed is None:
            raise ApiError(ERR_BED_NOT_FOUND, "No RecoveryBed with the given bed_id", 404)
    # Priority 4: shape.
    lab_id = req_str(data, "lab_id")
    scheduled_start = req_dt(data, "scheduled_start")
    if bed_ref is not None and not isinstance(bed_ref, str):
        raise ApiError(ERR_INVALID_REQUEST, "bed_id must be a string", 400)
    # Priority 5: case from-state, then explicit bed state.
    if case["status"] not in ("POSTED", "BUMPED"):
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Only a POSTED or BUMPED case can be scheduled",
            409,
        )
    if bed is not None and bed["status"] != "AVAILABLE":
        raise ApiError(
            ERR_BED_INVALID_STATE,
            "Explicit bed_id must reference an AVAILABLE bed",
            409,
        )
    # Priority 6: elective AUC gate (survives a bump).
    if case["priority"] == "ELECTIVE" and case["auc_status"] != "DOCUMENTED":
        raise ApiError(
            ERR_AUC_REQUIRED,
            "ELECTIVE case scheduling requires documented appropriate-use criteria",
            422,
        )
    scheduled_end = compute_case_end(
        case["procedure_type"], case["priority"], case["equipment_needs"], scheduled_start
    )
    # Priority 7: buffered room window conflict.
    if room_window_conflict(lab_id, scheduled_start, scheduled_end):
        raise ApiError(
            ERR_ROOM_WINDOW_CONFLICT,
            "The requested window conflicts with a committed case on the room",
            409,
        )
    # Priority 8: room ACTIVE, then equipment subset.
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, "Target room is not ACTIVE", 409)
    if not set(case["equipment_needs"]).issubset(set(room["equipment_profile"])):
        raise ApiError(
            ERR_EQUIPMENT_MISMATCH,
            "case equipment_needs is not a subset of the room equipment_profile",
            422,
        )
    # Priority 9: bed selector fallback.
    if bed is None:
        bed = select_recovery_bed()
        if bed is None:
            raise ApiError(ERR_NO_RECOVERY_BED, "No AVAILABLE recovery bed", 409)

    case["lab_id"] = lab_id
    case["scheduled_start"] = scheduled_start
    case["scheduled_end"] = scheduled_end
    case["status"] = "SCHEDULED"
    touch(case)
    reserve_bed_for_case(bed, case)
    return success(case_out(case), 200)


@bp.route("/cath-lab/cases/<case_id>/cancel", methods=["POST"])
@require_roles("CathLabScheduler")
def cancel_case(case_id):
    case = _get_case_or_404(case_id)
    if case["status"] not in ("POSTED", "SCHEDULED", "BUMPED"):
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Only a POSTED, SCHEDULED, or BUMPED case can be cancelled",
            409,
        )
    if case["status"] == "SCHEDULED":
        release_bed_for_case(case_id)
        release_assignments_for_case(case_id)
        release_usages_for_case(case_id)
    case["status"] = "CANCELLED"
    case["lab_id"] = None
    case["scheduled_start"] = None
    case["scheduled_end"] = None
    touch(case)
    return success(case_out(case), 200)


@bp.route("/cath-lab/cases/<case_id>/start", methods=["POST"])
@require_roles("InterventionalCardiologist")
def start_case(case_id):
    case = _get_case_or_404(case_id)
    # Priority 5: from-state.
    if case["status"] != "SCHEDULED":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Only a SCHEDULED case can be started",
            409,
        )
    # Priority 8: identity, room, staffing (in PRD 3.7 order).
    if g.user_id != case["performing_physician_id"]:
        raise ApiError(
            ERR_NOT_PERFORMING_PHYSICIAN,
            "Only the performing physician may start the case",
            403,
        )
    room = STORE["rooms"].get(case["lab_id"])
    if room is None or room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, "Assigned room is not ACTIVE", 409)
    has_scrub = False
    has_circulator = False
    for a in STORE["assignments"].values():
        if a["case_id"] == case_id and a["status"] == "ASSIGNED":
            if a["role_in_case"] == "SCRUB":
                has_scrub = True
            elif a["role_in_case"] == "CIRCULATOR":
                has_circulator = True
    if not (has_scrub and has_circulator):
        raise ApiError(
            ERR_STAFFING_INCOMPLETE,
            "Case start requires at least one ASSIGNED SCRUB and one ASSIGNED CIRCULATOR",
            422,
        )
    case["status"] = "IN_PROGRESS"
    case["actual_start"] = logical_now()
    touch(case)
    return success(case_out(case), 200)


@bp.route("/cath-lab/cases/<case_id>/complete", methods=["POST"])
@require_roles("InterventionalCardiologist")
def complete_case(case_id):
    case = _get_case_or_404(case_id)
    if case["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Only an IN_PROGRESS case can be completed",
            409,
        )
    if g.user_id != case["performing_physician_id"]:
        raise ApiError(
            ERR_NOT_PERFORMING_PHYSICIAN,
            "Only the performing physician may complete the case",
            403,
        )
    case["status"] = "COMPLETED"
    case["actual_end"] = logical_now()
    touch(case)
    # Settle everything the case was holding (each resource reconciled
    # independently with its own version bump, PRD 2.9).
    occupy_bed_for_case(case)
    release_assignments_for_case(case_id)
    release_usages_for_case(case_id)
    return success(case_out(case), 200)


@bp.route("/cath-lab/cases/<case_id>/auc-attestation", methods=["POST"])
@require_roles("InterventionalCardiologist")
def auc_attestation(case_id):
    case = _get_case_or_404(case_id)
    data = get_payload()
    # Priority 3: body FK existence.
    ordering_ref = data.get("ordering_physician_id")
    if isinstance(ordering_ref, str) and ordering_ref not in STORE["staff"]:
        raise ApiError(
            ERR_STAFF_NOT_FOUND,
            "No StaffMember with the given ordering_physician_id",
            404,
        )
    # Priority 4: shape.
    ordering_physician_id = req_str(data, "ordering_physician_id")
    auc_score = req_enum(data, "auc_score", AUC_SCORES)
    criterion_code = req_str(data, "criterion_code")
    expected_case_version = data.get("expected_case_version")
    if not is_int_valued(expected_case_version):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "expected_case_version is required and must be a whole number",
            400,
        )
    # Priority 6: segregation of duties, both directions.
    if (
        ordering_physician_id == case["performing_physician_id"]
        or g.user_id != ordering_physician_id
    ):
        raise ApiError(
            ERR_AUC_ORDERING_CONFLICT,
            "Ordering physician must differ from the performing physician and the "
            "acting user must be the ordering physician",
            403,
        )
    # Priority 10: optimistic concurrency on the case version.
    if int(expected_case_version) != case["version"]:
        raise ApiError(
            ERR_STALE_CASE_VERSION,
            "expected_case_version does not match the case's current version",
            412,
        )
    case["auc_status"] = "DOCUMENTED"
    case["auc_score"] = auc_score
    case["auc_criterion_code"] = criterion_code
    case["ordering_physician_id"] = ordering_physician_id
    touch(case)
    return success(case_out(case), 201)
