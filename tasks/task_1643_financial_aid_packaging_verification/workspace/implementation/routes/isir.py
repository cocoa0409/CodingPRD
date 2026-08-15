"""ISIR import and register endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_FIELD_CONSTRAINT, ERR_DUPLICATE,
    ERR_RECEIVED_AT_OUT_OF_WINDOW, ERR_PREREQUISITE_MISSING,
    ERR_PARENT_STATE_BLOCKS,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.calc import compute_efc, deterministic_verification_selected
from services.core import new_record, public, touch
from util import CLOCK, minus_one_year, parse_instant
from validate import (
    get_body, req_int, req_str, opt_bool, require_path_resource,
    deferred_body_ref, is_valid_instant,
)

bp = Blueprint("isir", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
REQUIRED_DOC_TYPES = ("TAX_RETURN_TRANSCRIPT", "W2", "HOUSEHOLD_FORM")


def _open_verification_case(student_id, aid_year_id, isir_id):
    """A selected import opens a VerificationCase in DOCUMENTS_REQUESTED with
    the three required V1 documents in REQUESTED (PRD 3.4)."""
    case = new_record("verification_cases", {
        "student_id": student_id,
        "aid_year_id": aid_year_id,
        "isir_id": isir_id,
        "tracking_group": "V1",
        "status": "DOCUMENTS_REQUESTED",
        "waived_reason": None,
        "resolution_notes": None,
        "completed_at": None,
    })
    for doc_type in REQUIRED_DOC_TYPES:
        new_record("verification_documents", {
            "verification_case_id": case["id"],
            "doc_type": doc_type,
            "status": "REQUESTED",
            "rejection_reason": None,
            "received_at": None,
        })
    return case


def _loop_verification_case(case, isir_id):
    """A newly selected import loops a COMPLETED_CORRECTION_SENT or
    COMPLETED_SATISFIED case back to DOCUMENTS_REQUESTED for re-verification:
    required documents re-arm to REQUESTED and completed_at clears."""
    case["status"] = "DOCUMENTS_REQUESTED"
    case["isir_id"] = isir_id
    case["completed_at"] = None
    for doc in db.verification_documents.values():
        if (doc["verification_case_id"] == case["id"]
                and doc["doc_type"] in REQUIRED_DOC_TYPES):
            changed = (doc["status"] != "REQUESTED" or doc["received_at"] is not None)
            doc["status"] = "REQUESTED"
            doc["received_at"] = None
            # rejection_reason is retained as history on previously rejected rows.
            if changed:
                touch(doc)
    touch(case)


@bp.post("/isir-records")
def import_isir():
    authorized(["AidOfficer"])
    body = get_body()
    # Rung 4: body foreign keys (absent keys defer to the rung-9 shape check).
    student = deferred_body_ref("students", body, "student_id")
    aid_year = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 6: parent-aggregate gate — never once the aid year is CLOSED.
    if aid_year is not None and aid_year["status"] == "CLOSED":
        raise_error(ERR_PARENT_STATE_BLOCKS,
                    "the aid year is CLOSED to student-level writes")
    # Rung 9: shape (presence of the FK fields is validated here).
    req_str(body, "student_id")
    req_str(body, "aid_year_id")
    transaction_number = req_int(body, "transaction_number", minimum=1)
    received_at_raw = body.get("received_at")
    if not isinstance(received_at_raw, str) or not received_at_raw.strip() \
            or not is_valid_instant(received_at_raw):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid datetime field: received_at")
    household_size = req_int(body, "household_size")
    number_in_college = req_int(body, "number_in_college")
    agi = req_int(body, "agi_cents")
    untaxed = req_int(body, "untaxed_income_cents")
    assets = req_int(body, "asset_net_worth_cents")
    cps_flag = opt_bool(body, "cps_selection_flag", False)
    # Rung 10: field-level domain constraints.
    floor = 2 if student["dependency_status"] == "DEPENDENT" else 1
    if household_size < floor:
        raise_error(ERR_FIELD_CONSTRAINT,
                    f"household_size must be at least {floor} for a "
                    f"{student['dependency_status']} student")
    if number_in_college < 1 or number_in_college > household_size:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "number_in_college must be at least 1 and no more than household_size")
    for field, value in (("agi_cents", agi), ("untaxed_income_cents", untaxed),
                         ("asset_net_worth_cents", assets)):
        if value < 0:
            raise_error(ERR_FIELD_CONSTRAINT, f"{field} must be non-negative")
    # Rung 11: the (student_id, aid_year_id, transaction_number) triple is unique.
    for rec in db.isir_records.values():
        if (rec["student_id"] == student["id"]
                and rec["aid_year_id"] == aid_year["id"]
                and rec["transaction_number"] == transaction_number):
            raise_error(ERR_DUPLICATE,
                        "an ISIR record with this transaction_number already exists "
                        "for this student and aid year")
    # Rung 12: receipt window — at or before the logical clock and no earlier
    # than one year before the aid year's own created_at.
    received_dt = parse_instant(received_at_raw)
    if received_dt > CLOCK.now():
        raise_error(ERR_RECEIVED_AT_OUT_OF_WINDOW,
                    "received_at is after the current logical-clock reading")
    window_floor = minus_one_year(parse_instant(aid_year["created_at"]))
    if received_dt < window_floor:
        raise_error(ERR_RECEIVED_AT_OUT_OF_WINDOW,
                    "received_at is earlier than one year before the aid year's creation")
    # Rung 13: import requires the aid year to be OPEN.
    if aid_year["status"] != "OPEN":
        raise_error(ERR_PREREQUISITE_MISSING,
                    "ISIR import requires the aid year to be OPEN")

    # --- side effects -------------------------------------------------------
    efc_provisional = compute_efc(
        student["dependency_status"], household_size, number_in_college,
        agi, untaxed, assets)
    priority_deadline = parse_instant(aid_year["priority_deadline"])
    cohort = "PRIORITY" if received_dt <= priority_deadline else "STANDARD"
    selected = cps_flag or deterministic_verification_selected(
        student["ssn"], aid_year["year_code"], aid_year["verification_tracking_flag_rate"])
    selection = "SELECTED" if selected else "NOT_SELECTED"

    # The newcomer becomes current only when no other record for the pair
    # carries a higher transaction_number (PRD 3.3); an out-of-order import is
    # born superseded and triggers no downstream effects.
    existing_max = 0
    prior_current = None
    for other in db.isir_records.values():
        if (other["student_id"] == student["id"]
                and other["aid_year_id"] == aid_year["id"]):
            existing_max = max(existing_max, other["transaction_number"])
            if other["is_current"]:
                prior_current = other
    becomes_current = transaction_number > existing_max
    if becomes_current and prior_current is not None:
        prior_current["is_current"] = False
        touch(prior_current)

    rec = new_record("isir_records", {
        "student_id": student["id"],
        "aid_year_id": aid_year["id"],
        "transaction_number": transaction_number,
        "received_at": received_at_raw,
        "cohort": cohort,
        "household_size": household_size,
        "number_in_college": number_in_college,
        "agi_cents": agi,
        "untaxed_income_cents": untaxed,
        "asset_net_worth_cents": assets,
        "cps_selection_flag": cps_flag,
        "efc_provisional_cents": efc_provisional,
        "efc_verified_cents": None,
        "efc_official_cents": efc_provisional,
        "is_current": becomes_current,
        "verification_selection": selection,
    })

    if not becomes_current:
        return success_object(public(rec), status=201)

    if selected:
        existing = None
        for case in db.verification_cases.values():
            if (case["student_id"] == student["id"]
                    and case["aid_year_id"] == aid_year["id"]):
                if existing is None or case["_seq"] > existing["_seq"]:
                    existing = case
        if existing is not None and existing["status"] in (
                "COMPLETED_CORRECTION_SENT", "COMPLETED_SATISFIED"):
            _loop_verification_case(existing, rec["id"])
        elif existing is not None and existing["status"] in (
                "DOCUMENTS_REQUESTED", "DOCUMENTS_RECEIVED", "UNDER_REVIEW"):
            pass  # a case is already mid-flight; it remains the active case
        else:
            _open_verification_case(student["id"], aid_year["id"], rec["id"])

    # A RESOLVED_REQUIRES_CORRECTION conflicting-info case closes itself when a
    # new current ISIR's subject-field value equals the claimed value.
    for case in db.conflicting_info_cases.values():
        if (case["student_id"] == student["id"]
                and case["aid_year_id"] == aid_year["id"]
                and case["status"] == "RESOLVED_REQUIRES_CORRECTION"
                and case["claimed_value_cents"] is not None):
            subject = case["subject_field"]
            if subject in rec and isinstance(rec[subject], int) \
                    and rec[subject] == case["claimed_value_cents"]:
                case["status"] = "RESOLVED"
                touch(case)

    return success_object(public(rec), status=201)


@bp.get("/isir-records")
def list_isir_records():
    authorized(DIRECTOR_OFFICER)
    from validate import opt_query_bool
    return list_response("isir_records", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
        "is_current": opt_query_bool("is_current"),
    })


@bp.get("/isir-records/<rid>")
def get_isir_record(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("isir_records", rid)
    return success_object(public(rec))
