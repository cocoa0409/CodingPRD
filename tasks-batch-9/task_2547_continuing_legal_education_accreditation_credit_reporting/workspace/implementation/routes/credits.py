"""Credit records, board adjudication and sponsor-filed rosters (PRD 3.5)."""
from flask import Blueprint

import calc
import constants as C
import db
import listing
import middleware
import response
import util
from errors import fail
from routes.attorneys import load_attorney
from routes.courses import load_course
from services import cascades

bp = Blueprint("credits", __name__)

CLAIM_METHODS = ["ROSTER", "ATTENDANCE_CODE", "CERTIFICATE", "AFFIRMATION"]
METHOD_PAIRING = {
    "ROSTER": "ROSTER",
    "ATTENDANCE_CODE": "ATTENDANCE_CODE",
    "CERTIFICATE": "CERTIFICATE",
    "AFFIRMATION_ONLY": "AFFIRMATION",
}
ADJUDICATION_ACTIONS = ["VERIFY", "REJECT", "VOID"]
LIVE_RECORD_STATUSES = ("PENDING_VERIFICATION", "VERIFIED")


def load_record(record_id):
    record = db.get("credit_records", record_id)
    if record is None:
        fail("ERR_CREDIT_RECORD_NOT_FOUND", "No credit record matches that identifier.")
    return record


def _new_record(fields):
    base = {
        "attorney_id": None,
        "cycle_id": None,
        "course_id": None,
        "attendance_report_id": None,
        "reciprocity_claim_id": None,
        "affirmation_id": None,
        "source": "IN_STATE",
        "verification_method": None,
        "certificate_reference": None,
        "attended_minutes": 0,
        "completion_date": None,
        "credited_ethics_minutes": 0,
        "credited_technology_minutes": 0,
        "credited_bias_minutes": 0,
        "credited_general_minutes": 0,
        "credited_minutes": 0,
        "countable_minutes": 0,
        "effective_format": None,
        "status": "PENDING_VERIFICATION",
        "void_reason": None,
    }
    base.update(fields)
    return db.insert("credit_records", base)


@bp.route("/cle/credit-records", methods=["POST"])
def claim_credit():
    user_id, _role = middleware.require_roles([C.ROLE_ATTORNEY])
    body = middleware.body_json()

    # Step 4: body foreign-key existence, in the pinned field order.
    course = load_course(body.get("course_id")) if middleware.present(body, "course_id") else None
    attorney = load_attorney(body.get("attorney_id")) if middleware.present(body, "attorney_id") else None

    # Step 5: ownership.
    if attorney is not None and attorney["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "An attorney may only claim credit for itself.")

    # Step 6: request shape.
    if attorney is None:
        fail("ERR_INVALID_REQUEST", "attorney_id is required.")
    if course is None:
        fail("ERR_INVALID_REQUEST", "course_id is required.")
    method = middleware.req_enum(body, "verification_method", CLAIM_METHODS)
    attended_minutes = middleware.req_int(body, "attended_minutes", 0)
    if attended_minutes <= 0:
        fail("ERR_INVALID_REQUEST", "attended_minutes must be greater than zero.")
    completion_date = middleware.req_instant(body, "completion_date")
    certificate_reference = middleware.opt_str(body, "certificate_reference", 1, None, None)
    attendance_code = middleware.opt_str(body, "attendance_code", 1, None, None)
    if method == "CERTIFICATE" and certificate_reference is None:
        fail("ERR_INVALID_REQUEST", "certificate_reference is required with the CERTIFICATE method.")

    cycle = cascades.cycle_for_instant(attorney["id"], completion_date)

    # Step 9: administrative suspension of the resolved cycle.
    if cycle is not None and cycle.get("administrative_status") == "ADMIN_SUSPENDED":
        fail("ERR_CYCLE_ADMIN_SUSPENDED", "That cycle accepts no credit-bearing write.")

    # Step 13: regulatory standing.
    if course.get("status") != "APPROVED":
        fail("ERR_COURSE_NOT_APPROVED", "Credit may only be claimed for an APPROVED course.")
    provider = db.get("providers", course.get("provider_id"))
    if provider is not None and provider.get("accreditation_status") not in ("ACCREDITED", "PROBATIONARY"):
        fail("ERR_PROVIDER_NOT_IN_GOOD_STANDING", "The sponsoring provider is not in good standing.")
    if attorney.get("status") not in ("ACTIVE", "EXEMPT"):
        fail("ERR_ATTORNEY_NOT_IN_GOOD_STANDING", "The attorney is not in good standing.")

    # Step 14: referential coherence.
    if cycle is not None and cycle.get("attorney_id") != attorney["id"]:
        fail("ERR_CYCLE_ATTORNEY_MISMATCH", "The resolved cycle belongs to another attorney.")

    # Step 15: temporal coherence.
    if cycle is None:
        fail("ERR_OUTSIDE_COMPLIANCE_PERIOD", "No compliance period of that attorney covers the completion date.")
    expires_at = util.parse_dt(course.get("expires_at"))
    if expires_at is not None and completion_date > expires_at:
        fail("ERR_COURSE_APPROVAL_EXPIRED", "The completion date falls after the course's approval expiry.")

    # Step 16: uniqueness, pairing and floor constraints.
    for existing in db.all_rows("credit_records"):
        if existing.get("attorney_id") != attorney["id"]:
            continue
        if existing.get("course_id") != course["id"]:
            continue
        if existing.get("status") in LIVE_RECORD_STATUSES:
            fail("ERR_DUPLICATE_CREDIT_RECORD", "That attorney already holds a live claim for this course.")
    if method == "ROSTER":
        fail(
            "ERR_VERIFICATION_METHOD_NOT_PERMITTED",
            "Roster records are minted only by the sponsor's roster cascade.",
        )
    if METHOD_PAIRING.get(course.get("attendance_verification_method")) != method:
        fail(
            "ERR_VERIFICATION_METHOD_NOT_PERMITTED",
            "That verification method is not the declared partner of the course's commitment.",
        )
    if method == "ATTENDANCE_CODE":
        if attendance_code is None or attendance_code != course.get("attendance_code"):
            fail("ERR_ATTENDANCE_CODE_INVALID", "The supplied attendance code does not match.")
    prorated = calc.category_proration(course, attended_minutes)
    if prorated["credited_minutes"] < C.MIN_CREDITABLE_MINUTES:
        fail("ERR_BELOW_MINIMUM_CREDIT", "The claim credits fewer than 30 minutes.")

    fields = {
        "attorney_id": attorney["id"],
        "cycle_id": cycle["id"],
        "course_id": course["id"],
        "source": "IN_STATE",
        "verification_method": method,
        "certificate_reference": certificate_reference,
        "attended_minutes": attended_minutes,
        "completion_date": util.iso(completion_date),
        "effective_format": calc.effective_format(course, method),
        "status": "PENDING_VERIFICATION",
    }
    fields.update(prorated)
    record = _new_record(fields)
    if method == "ATTENDANCE_CODE":
        cascades.mark_verified(record)
    else:
        cascades.rerun_cycle(cycle)
    return response.success(db.serialize(record), 201)


@bp.route("/cle/credit-records/<record_id>", methods=["GET"])
def read_record(record_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    return response.success(db.serialize(load_record(record_id)), 200)


@bp.route("/cle/credit-records", methods=["GET"])
def list_records():
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    rows = listing.apply_filters(
        db.all_rows("credit_records"),
        [
            "attorney_id",
            "cycle_id",
            "course_id",
            "attendance_report_id",
            "reciprocity_claim_id",
            "affirmation_id",
            "status",
        ],
    )
    return listing.page(listing.sort_by(rows, "completion_date"))


@bp.route("/cle/credit-records/<record_id>/adjudication", methods=["POST"])
def adjudicate(record_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    record = load_record(record_id)
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", ADJUDICATION_ACTIONS)
    void_reason = middleware.opt_str(body, "void_reason", 1, None, None)

    status = record.get("status")
    course = db.get("courses", record.get("course_id"))
    if action == "VERIFY":
        if status != "PENDING_VERIFICATION":
            fail("ERR_INVALID_STATE_TRANSITION", "VERIFY is not declared from %s." % status)
        if course is not None and course.get("status") not in ("APPROVED", "EXPIRED"):
            fail("ERR_INVALID_STATE_TRANSITION", "The course is neither APPROVED nor EXPIRED.")
        cascades.mark_verified(record)
    elif action == "REJECT":
        if status != "PENDING_VERIFICATION":
            fail("ERR_INVALID_STATE_TRANSITION", "REJECT is not declared from %s." % status)
        cascades.mark_rejected(record, void_reason)
    else:  # VOID
        if status != "VERIFIED":
            fail("ERR_INVALID_STATE_TRANSITION", "VOID applies only to a VERIFIED record.")
        cascades.mark_voided(record, void_reason)
    return response.success(db.serialize(record), 200)


# --------------------------------------------------------- sponsor-filed roster
@bp.route("/cle/attendance-reports", methods=["POST"])
def file_roster():
    user_id, _role = middleware.require_roles([C.ROLE_PROVIDER_ADMIN])
    body = middleware.body_json()

    # Step 4: body foreign-key existence.
    course = load_course(body.get("course_id")) if middleware.present(body, "course_id") else None

    # Step 6: request shape.
    if course is None:
        fail("ERR_INVALID_REQUEST", "course_id is required.")
    session_date = middleware.req_instant(body, "session_date")
    raw_entries = middleware.req_list(body, "entries")
    entries = []
    for element in raw_entries:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "Each roster entry must be an object.")
        bar_number = middleware.req_str(element, "bar_number", 1, None)
        minutes = middleware.req_int(element, "attended_minutes", 0)
        entries.append({"bar_number": bar_number, "attended_minutes": minutes})

    # Step 13: regulatory standing.
    if course.get("status") != "APPROVED":
        fail("ERR_COURSE_NOT_APPROVED", "Rosters may only be filed against an APPROVED course.")
    provider = db.get("providers", course.get("provider_id"))
    if provider is not None and provider.get("accreditation_status") not in ("ACCREDITED", "PROBATIONARY"):
        fail("ERR_PROVIDER_NOT_IN_GOOD_STANDING", "The sponsoring provider is not in good standing.")

    # Step 14: referential coherence.
    if course.get("provider_id") != user_id:
        fail("ERR_COURSE_PROVIDER_MISMATCH", "That course is sponsored by another provider.")

    # Step 15: temporal coherence — the hard filing window.
    lateness = calc.roster_lateness(session_date)
    if lateness is None:
        fail("ERR_ROSTER_WINDOW_CLOSED", "The ninety-day roster window has closed.")

    # Step 16: cardinality.
    if len(entries) == 0:
        fail("ERR_EMPTY_ROSTER", "entries must contain at least one element.")

    total_minutes = int(course.get("total_minutes") or 0)
    roster = db.insert(
        "attendance_reports",
        {
            "course_id": course["id"],
            "session_date": util.iso(session_date),
            "session_end": util.iso(util.add_minutes(session_date, total_minutes)),
            "entries": entries,
            "entry_count": len(entries),
            "accepted_entry_count": 0,
            "rejected_entry_count": 0,
            "submitted_at": util.now_iso(),
            "due_at": util.iso(lateness["due_at"]),
            "days_late": lateness["days_late"],
            "status": lateness["status"],
        },
    )

    if provider is not None:
        updates = {
            "attendance_reports_total_count": int(provider.get("attendance_reports_total_count") or 0) + 1
        }
        if lateness["status"] == "ACCEPTED_LATE":
            updates["attendance_reports_late_count"] = (
                int(provider.get("attendance_reports_late_count") or 0) + 1
            )
        cascades.set_fields(provider, updates)
        cascades.refresh_risk(provider)

    accepted = 0
    for entry in entries:
        attorney = None
        for candidate in db.all_rows("attorneys"):
            if candidate.get("bar_number") == entry["bar_number"]:
                attorney = candidate
                break
        if attorney is None:
            continue
        cycle = cascades.cycle_for_instant(attorney["id"], session_date)
        if cycle is None:
            continue
        duplicate = False
        for existing in db.all_rows("credit_records"):
            if existing.get("attorney_id") != attorney["id"]:
                continue
            if existing.get("course_id") != course["id"]:
                continue
            if existing.get("status") in LIVE_RECORD_STATUSES:
                duplicate = True
                break
        if duplicate:
            continue
        fields = {
            "attorney_id": attorney["id"],
            "cycle_id": cycle["id"],
            "course_id": course["id"],
            "attendance_report_id": roster["id"],
            "source": "IN_STATE",
            "verification_method": "ROSTER",
            "attended_minutes": entry["attended_minutes"],
            "completion_date": util.iso(session_date),
            "effective_format": calc.effective_format(course, "ROSTER"),
            "status": "VERIFIED",
        }
        fields.update(calc.category_proration(course, entry["attended_minutes"]))
        record = _new_record(fields)
        cascades.mark_verified(record)
        accepted += 1

    cascades.set_fields(
        roster,
        {"accepted_entry_count": accepted, "rejected_entry_count": len(entries) - accepted},
    )
    return response.success(db.serialize(roster), 201)
