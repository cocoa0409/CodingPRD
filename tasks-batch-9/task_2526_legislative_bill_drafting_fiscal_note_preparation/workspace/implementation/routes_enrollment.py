"""Technical corrections and signature routing on an enrolled bill
(PRD S3.9)."""

from flask import Blueprint

from auth import endpoint, require_senior
from counters import recompute_enrollment_counts
from envelope import object_response
from errors import fail
from lookups import get_correction, get_enrollment, require_active_session
import serializers as S
from store import create_row, db, touch
from validation import body, req_bool, req_enum, req_int, req_str

bp = Blueprint("enrollment", __name__)

CORRECTABLE_STATES = ("PREPARED", "ORIGIN_SIGNED", "SECOND_SIGNED")
SIGNATURE_ROLES = ("SPEAKER", "SENATE_PRESIDENT", "GOVERNOR_TRANSMITTAL")


def _session_of_enrollment(enrollment):
    bill = db.bills.get(enrollment["bill_id"])
    return db.sessions.get(bill["session_id"]) if bill else None


def _other_presiding_officer(origin_role):
    return "SENATE_PRESIDENT" if origin_role == "SPEAKER" else "SPEAKER"


# ---------------------------------------------------------------------------
# technical corrections
# ---------------------------------------------------------------------------


@bp.post("/enrolled-bills/<eid>/technical-corrections")
@endpoint(("Drafter", "ReviewCounsel"))
def create_correction(user_id, role, eid):
    enrollment = get_enrollment(eid)
    payload = body()
    expected = req_int(payload, "expected_enrolled_bill_version")
    correction_type = req_enum(
        payload, "correction_type", ("TYPO", "CITATION", "CROSS_REFERENCE", "NUMBERING")
    )
    description = req_str(payload, "description")
    is_substantive = req_bool(payload, "is_substantive")
    if expected != enrollment["version"]:
        fail("ERR_STALE_ENROLLMENT_VERSION")
    require_active_session(_session_of_enrollment(enrollment))
    if enrollment["status"] not in CORRECTABLE_STATES:
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if is_substantive:
        fail("ERR_SUBSTANTIVE_CORRECTION_FORBIDDEN")

    correction = create_row(
        "technical_corrections",
        {
            "enrolled_bill_id": enrollment["id"],
            "proposed_by_drafter_id": user_id,
            "applied_by_drafter_id": None,
            "correction_type": correction_type,
            "description": description,
            "is_substantive": False,
            "status": "PROPOSED",
            "applied_utc": None,
        },
    )
    recompute_enrollment_counts(enrollment["id"])
    touch(enrollment)
    return object_response(S.technical_correction_out(correction), 201)


@bp.post("/technical-corrections/<cid>/apply")
@endpoint(("ReviewCounsel",))
def apply_correction(user_id, role, cid):
    require_senior(user_id)
    correction = get_correction(cid)
    enrollment = db.enrolled_bills.get(correction["enrolled_bill_id"])
    require_active_session(
        _session_of_enrollment(enrollment) if enrollment else None
    )
    if correction["status"] != "PROPOSED":
        fail("ERR_INVALID_CORRECTION_STATE")
    if enrollment is None or enrollment["status"] == "TRANSMITTED":
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if correction["proposed_by_drafter_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    correction["status"] = "APPLIED"
    correction["applied_by_drafter_id"] = user_id
    correction["applied_utc"] = db.now_iso()
    touch(correction)
    recompute_enrollment_counts(enrollment["id"])
    touch(enrollment)
    return object_response(S.technical_correction_out(correction))


# ---------------------------------------------------------------------------
# signature routing
# ---------------------------------------------------------------------------


@bp.post("/enrolled-bills/<eid>/signatures")
@endpoint(("Clerk",))
def record_signature(user_id, role, eid):
    enrollment = get_enrollment(eid)
    payload = body()
    signature_role = req_enum(payload, "signature_role", SIGNATURE_ROLES)
    require_active_session(_session_of_enrollment(enrollment))
    if enrollment["status"] == "TRANSMITTED":
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if signature_role != enrollment["expected_next_signature"]:
        fail("ERR_SIGNATURE_OUT_OF_ORDER")

    if enrollment["status"] == "PREPARED":
        enrollment["status"] = "ORIGIN_SIGNED"
        enrollment["origin_signed_utc"] = db.now_iso()
        enrollment["expected_next_signature"] = _other_presiding_officer(
            enrollment["origin_signature_role"]
        )
    elif enrollment["status"] == "ORIGIN_SIGNED":
        enrollment["status"] = "SECOND_SIGNED"
        enrollment["second_signed_utc"] = db.now_iso()
        enrollment["expected_next_signature"] = "GOVERNOR_TRANSMITTAL"
    else:
        if enrollment["open_corrections_count"] > 0:
            fail("ERR_UNAPPLIED_CORRECTIONS")
        enrollment["status"] = "TRANSMITTED"
        enrollment["transmitted_utc"] = db.now_iso()
        enrollment["expected_next_signature"] = "NONE"
        bill = db.bills.get(enrollment["bill_id"])
        if bill is not None and bill["legislative_status"] == "ENROLLED":
            bill["legislative_status"] = "TRANSMITTED"
            touch(bill)
    touch(enrollment)
    return object_response(S.enrolled_bill_out(enrollment))
