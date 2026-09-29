"""Procedure bookings: slot geometry, lifecycle and pathology intake."""
from flask import Blueprint

from core import by_seq, db, fail, iso, new_record, parse_instant, touch
from core import respond_list, respond_object
from calcs import (
    OCCUPYING_BOOKING_STATUSES,
    PREPROCEDURE_MAX_UNSCREENED_ASA_CLASS,
    POOR_PREP_BBPS_MAX,
    occupancy_bounds,
    recompute_session_ledger,
)
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    pagination,
    req_id,
    req_instant,
    req_int,
    req_string,
)
from services import (
    apply_final_pricing,
    booking_claim,
    create_claim_for_booking,
    derive_findings,
    get_booking,
    get_clinician,
    get_episode,
    get_session,
    no_specimen_closure,
    recompute_patient_counts,
    validate_specimens,
    void_claim,
)

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = (
    "BOOKED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", "ABORTED_INADEQUATE_PREP", "CANCELLED",
)


@bp.post("/endoscopy-sessions/<session_id>/procedure-bookings")
def create_booking(session_id):
    auth("ReferralCoordinator", "PracticeAdmin")
    data = body()
    episode_id = req_id(data, "episode_id")
    performing_endoscopist_id = req_id(data, "performing_endoscopist_id")
    slot_start = req_instant(data, "slot_start_utc")
    duration_minutes = req_int(data, "duration_minutes", 15, 120)
    expected_session_version = req_int(data, "expected_session_version")

    session = get_session(session_id)
    episode = get_episode(episode_id)
    endoscopist = get_clinician(performing_endoscopist_id)

    if episode["clinical_status"] != "OPEN":
        fail("ERR_INVALID_EPISODE_STATE",
             "Booking requires an OPEN episode, not %s." % episode["clinical_status"])
    if session["status"] not in ("PUBLISHED", "COVERAGE_CONFIRMED"):
        fail("ERR_SESSION_NOT_ACCEPTING_BOOKINGS",
             "A block in %s accepts no bookings." % session["status"])
    if expected_session_version != session["version"]:
        fail("ERR_STALE_SESSION_VERSION",
             "expected_session_version %s does not match %s."
             % (expected_session_version, session["version"]))

    patient = db.patients[episode["patient_id"]]
    if patient["asa_class"] > PREPROCEDURE_MAX_UNSCREENED_ASA_CLASS:
        referral = db.referrals.get(episode["referral_id"]) if episode["referral_id"] else None
        if referral is None or referral["status"] != "ACCEPTED_OFFICE_VISIT":
            fail("ERR_PREPROCEDURE_RISK_UNCLEARED",
                 "An ASA %d patient requires an ACCEPTED_OFFICE_VISIT referral."
                 % patient["asa_class"])
    if endoscopist["clinician_type"] != "ENDOSCOPIST":
        fail("ERR_CLINICIAN_TYPE_MISMATCH", "A booking must be performed by an ENDOSCOPIST.")
    if episode["eligibility_status"] != "ELIGIBLE":
        fail("ERR_EPISODE_NOT_ELIGIBLE",
             "The episode is %s." % episode["eligibility_status"])

    slot_end, occupancy_end = occupancy_bounds(
        slot_start, duration_minutes, session["turnover_minutes"]
    )
    window_start = parse_instant(session["window_start_utc"])
    window_end = parse_instant(session["window_end_utc"])
    if slot_start < window_start or occupancy_end > window_end:
        fail("ERR_SLOT_OUTSIDE_SESSION_WINDOW",
             "The occupancy interval must sit inside the block window.")

    for other in db.bookings.values():
        if other["session_id"] != session["id"]:
            continue
        if other["status"] not in OCCUPYING_BOOKING_STATUSES:
            continue
        other_start = parse_instant(other["slot_start_utc"])
        other_end = parse_instant(other["occupancy_end_utc"])
        if slot_start < other_end and other_start < occupancy_end:
            fail("ERR_SLOT_OVERLAP", "The occupancy interval overlaps booking %s." % other["id"])

    live = [
        b for b in db.bookings.values()
        if b["session_id"] == session["id"] and b["status"] != "CANCELLED"
    ]
    if len(live) >= session["max_procedures"]:
        fail("ERR_SESSION_CAPACITY_EXCEEDED",
             "The block already holds %d bookings." % len(live))

    booking = new_record({
        "episode_id": episode["id"],
        "session_id": session["id"],
        "performing_endoscopist_id": performing_endoscopist_id,
        "slot_start_utc": data["slot_start_utc"],
        "duration_minutes": duration_minutes,
        "slot_end_utc": iso(slot_end),
        "occupancy_end_utc": iso(occupancy_end),
        "status": "BOOKED",
        "prep_quality_bbps": None,
        "polyps_removed_count": None,
        "largest_polyp_mm": None,
        "specimen_count": None,
        "planned_classification": None,
        "final_classification": None,
        "cancellation_reason": None,
        "released_minutes": 0,
    })
    db.bookings[booking["id"]] = booking

    recompute_session_ledger(session)
    episode["clinical_status"] = "PROCEDURE_SCHEDULED"
    touch(episode)
    create_claim_for_booking(booking, session, episode, patient)
    touch(session)
    return respond_object(booking, 201)


@bp.get("/procedure-bookings/<booking_id>")
def read_booking(booking_id):
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Endoscopist",
         "BillingSpecialist", "QualityOfficer")
    return respond_object(get_booking(booking_id))


@bp.get("/procedure-bookings")
def list_bookings():
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Endoscopist",
         "BillingSpecialist", "QualityOfficer")
    limit, offset = pagination()
    episode_id = filter_value("episode_id")
    session_id = filter_value("session_id")
    endoscopist_id = filter_value("performing_endoscopist_id")
    status = filter_enum("status", BOOKING_STATUSES)
    rows = by_seq(list(db.bookings.values()))
    if episode_id is not None:
        rows = [r for r in rows if r["episode_id"] == episode_id]
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if endoscopist_id is not None:
        rows = [r for r in rows if r["performing_endoscopist_id"] == endoscopist_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


def _own_booking(user_id, booking):
    if user_id != booking["performing_endoscopist_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the performing endoscopist may act on this booking.")


@bp.post("/procedure-bookings/<booking_id>/check-in")
def check_in(booking_id):
    auth("PatientNavigator")
    booking = get_booking(booking_id)
    if booking["status"] != "BOOKED":
        fail("ERR_INVALID_BOOKING_STATE",
             "Check-in is not admitted from %s." % booking["status"])
    episode = db.episodes[booking["episode_id"]]
    if episode["navigation_status"] != "PREP_CONFIRMED":
        fail("ERR_PREP_NOT_CONFIRMED",
             "The episode's navigation_status is %s." % episode["navigation_status"])
    booking["status"] = "CHECKED_IN"
    touch(booking)
    return respond_object(booking)


@bp.post("/procedure-bookings/<booking_id>/start")
def start_procedure(booking_id):
    user_id, _role = auth("Endoscopist")
    booking = get_booking(booking_id)
    _own_booking(user_id, booking)
    if booking["status"] != "CHECKED_IN":
        fail("ERR_INVALID_BOOKING_STATE", "Start is not admitted from %s." % booking["status"])
    clinician = db.clinicians[booking["performing_endoscopist_id"]]
    if clinician["credential_status"] != "ACTIVE":
        fail("ERR_CLINICIAN_CREDENTIAL_SUSPENDED",
             "The performing clinician's credential is SUSPENDED.")
    session = db.sessions[booking["session_id"]]
    if session["anesthesia_mode"] == "MAC" and session["status"] != "COVERAGE_CONFIRMED":
        fail("ERR_ANESTHESIA_COVERAGE_REQUIRED",
             "A MAC block must be COVERAGE_CONFIRMED to start a procedure.")
    booking["status"] = "IN_PROGRESS"
    touch(booking)
    return respond_object(booking)


@bp.post("/procedure-bookings/<booking_id>/complete")
def complete_procedure(booking_id):
    user_id, _role = auth("Endoscopist")
    data = body()
    prep_quality_bbps = req_int(data, "prep_quality_bbps", 0, 9)
    polyps_removed_count = req_int(data, "polyps_removed_count", 0, None)
    largest_polyp_mm = req_int(data, "largest_polyp_mm", 0, None)
    specimen_count = req_int(data, "specimen_count", 0, None)

    booking = get_booking(booking_id)
    _own_booking(user_id, booking)
    if booking["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_BOOKING_STATE",
             "Completion is not admitted from %s." % booking["status"])

    booking["prep_quality_bbps"] = prep_quality_bbps
    booking["polyps_removed_count"] = polyps_removed_count
    booking["largest_polyp_mm"] = largest_polyp_mm
    booking["specimen_count"] = specimen_count
    booking["status"] = "COMPLETED"

    episode = db.episodes[booking["episode_id"]]
    episode["navigation_status"] = "NAVIGATION_COMPLETE"
    if specimen_count >= 1:
        episode["clinical_status"] = "PATHOLOGY_PENDING"
    else:
        no_specimen_closure(booking, episode)
    touch(episode)
    touch(booking)
    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        recompute_patient_counts(patient)
    return respond_object(booking)


@bp.post("/procedure-bookings/<booking_id>/abort")
def abort_procedure(booking_id):
    user_id, _role = auth("Endoscopist")
    data = body()
    prep_quality_bbps = req_int(data, "prep_quality_bbps", 0, 9)
    cancellation_reason = req_string(data, "cancellation_reason")

    booking = get_booking(booking_id)
    _own_booking(user_id, booking)
    if booking["status"] not in ("CHECKED_IN", "IN_PROGRESS"):
        fail("ERR_INVALID_BOOKING_STATE", "Abort is not admitted from %s." % booking["status"])

    booking["prep_quality_bbps"] = prep_quality_bbps
    booking["cancellation_reason"] = cancellation_reason
    booking["status"] = "ABORTED_INADEQUATE_PREP"

    episode = db.episodes[booking["episode_id"]]
    episode["clinical_status"] = "OPEN"
    if prep_quality_bbps <= POOR_PREP_BBPS_MAX:
        episode["navigation_status"] = "PREP_AT_RISK"
        episode["prep_attestation"] = "NONE"
    touch(episode)

    claim = booking_claim(booking["id"])
    if claim is not None and claim["status"] in ("PROVISIONAL_PRICED", "REPRICED"):
        apply_final_pricing(claim, touch_booking=False)
    touch(booking)
    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        recompute_patient_counts(patient)
    return respond_object(booking)


@bp.post("/procedure-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    auth("ReferralCoordinator", "PracticeAdmin")
    data = body()
    cancellation_reason = req_string(data, "cancellation_reason")

    booking = get_booking(booking_id)
    if booking["status"] != "BOOKED":
        fail("ERR_INVALID_BOOKING_STATE",
             "Cancellation is not admitted from %s." % booking["status"])

    session = db.sessions[booking["session_id"]]
    booking["status"] = "CANCELLED"
    booking["cancellation_reason"] = cancellation_reason
    booking["released_minutes"] = booking["duration_minutes"] + session["turnover_minutes"]
    touch(booking)

    recompute_session_ledger(session)
    episode = db.episodes[booking["episode_id"]]
    episode["clinical_status"] = "OPEN"
    touch(episode)

    claim = booking_claim(booking["id"])
    if claim is not None and claim["status"] in ("PROVISIONAL_PRICED", "REPRICED"):
        void_claim(claim)
    touch(session)
    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        recompute_patient_counts(patient)
    return respond_object(booking)


@bp.post("/procedure-bookings/<booking_id>/pathology-reports")
def receive_report(booking_id):
    auth("Pathologist")
    data = body()
    accession_number = req_string(data, "accession_number", minlen=1, maxlen=32)
    specimens = validate_specimens(data, "specimens")
    high_grade_dysplasia = opt_bool(data, "high_grade_dysplasia", False)

    booking = get_booking(booking_id)
    if booking["status"] != "COMPLETED":
        fail("ERR_INVALID_BOOKING_STATE",
             "A pathology report requires a COMPLETED booking, not %s." % booking["status"])

    for other in db.reports.values():
        if other["accession_number"] == accession_number:
            fail("ERR_DUPLICATE_IDENTIFIER",
                 "accession_number %s already exists." % accession_number)

    findings = derive_findings(specimens)
    report = new_record({
        "booking_id": booking["id"],
        "accession_number": accession_number,
        "specimens": specimens,
        "high_grade_dysplasia": high_grade_dysplasia,
        "adenoma_count": findings["adenoma_count"],
        "sessile_serrated_count": findings["sessile_serrated_count"],
        "largest_adenoma_mm": findings["largest_adenoma_mm"],
        "villous_component": findings["villous_component"],
        "adenocarcinoma_present": findings["adenocarcinoma_present"],
        "status": "RECEIVED",
        "amendment_count": 0,
        "finalized_at": None,
        "routed_to_endoscopist_id": None,
        "amendment_reason": None,
    })
    db.reports[report["id"]] = report
    return respond_object(report, 201)
