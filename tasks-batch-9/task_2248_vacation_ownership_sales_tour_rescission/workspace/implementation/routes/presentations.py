"""Sales presentations, disclosure acknowledgments, prohibited-claim findings
and compliance review (PRD 3.6)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_booking, get_presentation, page
from store import db, ordered

bp = Blueprint("presentations", __name__)


@bp.post("/sales-presentations")
def create_presentation():
    user_id, _ = auth.require(auth.SALES_REPRESENTATIVE)
    data = validators.body()
    booking_id = validators.identifier(data, "booking_id")
    reference = validators.string(data, "recorded_ack_reference", 4, 64)

    booking = get_booking(booking_id)
    if booking["assigned_rep_id"] != user_id:
        fail(
            errors.ERR_REPRESENTATIVE_MISMATCH,
            "the acting representative is not assigned to this booking",
        )
    if booking["status"] != "CHECKED_IN":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not CHECKED_IN")
    for existing in db.presentations.values():
        if existing["booking_id"] == booking["id"]:
            fail(
                errors.ERR_PRESENTATION_ALREADY_EXISTS,
                "a presentation already exists for this booking",
            )

    now = db.now()
    presentation = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "booking_id": booking["id"],
        "rep_id": booking["assigned_rep_id"],
        "window_start_utc": booking["scheduled_start_utc"],
        "window_end_utc": booking["scheduled_end_utc"],
        "started_at": now,
        "recorded_ack_reference": reference,
        "required_disclosure_count": 3,
        "disclosure_ack_count": 0,
        "disclosure_status": "PENDING",
        "review_status": "UNREVIEWED",
        "prohibited_claim_points": 0,
        "compliance_score": 70,
        "reviewed_by_user_id": None,
        "flag_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.presentations[presentation["id"]] = presentation
    return created(presentation)


@bp.post("/disclosure-acknowledgments")
def create_acknowledgment():
    user_id, _ = auth.require(auth.SALES_REPRESENTATIVE)
    data = validators.body()
    presentation_id = validators.identifier(data, "presentation_id")
    code = validators.enum(data, "disclosure_code", calc.DISCLOSURE_CODES)
    acknowledged = validators.boolean(data, "acknowledged_by_prospect")
    offset_seconds = validators.integer(data, "recording_timestamp_offset_seconds", 0)

    presentation = get_presentation(presentation_id)
    if presentation["rep_id"] != user_id:
        fail(
            errors.ERR_REPRESENTATIVE_MISMATCH,
            "the acting representative does not own this presentation",
        )
    if presentation["disclosure_status"] not in ("PENDING", "PARTIAL"):
        fail(
            errors.ERR_INVALID_PRESENTATION_STATE,
            "disclosure_status no longer accepts appends",
        )
    for existing in db.acknowledgments.values():
        if (
            existing["presentation_id"] == presentation["id"]
            and existing["disclosure_code"] == code
        ):
            fail(
                errors.ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED,
                "%s has already been acknowledged" % code,
            )

    now = db.now()
    ack = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "presentation_id": presentation["id"],
        "disclosure_code": code,
        "acknowledged_by_prospect": acknowledged,
        "recording_timestamp_offset_seconds": offset_seconds,
        "acknowledged_at": now,
        "counts_toward_required": bool(
            acknowledged and code in calc.REQUIRED_DISCLOSURE_CODES
        ),
        "created_at": now,
    }
    db.acknowledgments[ack["id"]] = ack
    derive.recompute_disclosures(presentation)
    return created(ack)


@bp.post("/prohibited-claim-findings")
def create_finding():
    user_id, _ = auth.require(auth.COMPLIANCE_OFFICER)
    data = validators.body()
    presentation_id = validators.identifier(data, "presentation_id")
    claim_code = validators.enum(data, "claim_code", calc.CLAIM_CODES)
    severity = validators.enum(data, "severity", tuple(calc.SEVERITY_PENALTY_POINTS))
    expected_version = validators.integer(data, "expected_presentation_version", 1)

    presentation = get_presentation(presentation_id)
    if presentation["version"] != expected_version:
        fail(
            errors.ERR_STALE_PRESENTATION_VERSION,
            "presentation version is %d" % presentation["version"],
        )

    now = db.now()
    finding = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "presentation_id": presentation["id"],
        "claim_code": claim_code,
        "severity": severity,
        "penalty_points": calc.SEVERITY_PENALTY_POINTS[severity],
        "reported_by_user_id": user_id,
        "detected_at": now,
        "created_at": now,
    }
    db.findings[finding["id"]] = finding

    derive.recompute_claim_points(presentation)
    # The append always advances the presentation version, even when neither
    # the point total nor the score happened to move.
    derive.touch(presentation)
    derive.maybe_auto_flag(presentation)
    return created(finding)


@bp.post("/sales-presentations/<presentation_id>/review")
def review_presentation(presentation_id):
    user_id, _ = auth.require(auth.COMPLIANCE_OFFICER)
    data = validators.body()
    decision = validators.enum(data, "decision", ("CLEAR", "FLAG"))
    presentation = get_presentation(presentation_id)

    current = presentation["review_status"]
    if decision == "CLEAR":
        if current not in ("UNREVIEWED", "FLAGGED"):
            fail(
                errors.ERR_INVALID_PRESENTATION_STATE,
                "review_status %s cannot be cleared" % current,
            )
    else:
        if current != "UNREVIEWED":
            fail(
                errors.ERR_INVALID_PRESENTATION_STATE,
                "review_status %s cannot be flagged manually" % current,
            )

    findings = derive.presentation_findings(presentation["id"])
    for finding in findings:
        if finding["reported_by_user_id"] == user_id:
            fail(
                errors.ERR_SEGREGATION_OF_DUTIES,
                "a reporting officer may not review this presentation",
            )

    if decision == "CLEAR":
        if presentation["compliance_score"] < calc.COMPLIANCE_CLEAR_FLOOR:
            fail(
                errors.ERR_PRESENTATION_NOT_CLEARED,
                "compliance_score is below %d" % calc.COMPLIANCE_CLEAR_FLOOR,
            )
        for finding in findings:
            if finding["severity"] == "EGREGIOUS":
                fail(
                    errors.ERR_PRESENTATION_NOT_CLEARED,
                    "an EGREGIOUS finding blocks clearance",
                )
        derive.setf(presentation, "review_status", "CLEARED")
        derive.setf(presentation, "reviewed_by_user_id", user_id)
    else:
        derive.setf(presentation, "reviewed_by_user_id", user_id)
        derive.enter_flagged(presentation)
    return ok(presentation)


@bp.post("/sales-presentations/<presentation_id>/complete")
def complete_presentation(presentation_id):
    user_id, _ = auth.require(auth.SALES_REPRESENTATIVE)
    presentation = get_presentation(presentation_id)
    if presentation["rep_id"] != user_id:
        fail(
            errors.ERR_REPRESENTATIVE_MISMATCH,
            "the acting representative does not own this presentation",
        )

    booking = db.bookings.get(presentation["booking_id"])
    if booking is None or booking["status"] != "CHECKED_IN":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not CHECKED_IN")
    if presentation["review_status"] == "UNREVIEWED":
        fail(
            errors.ERR_INVALID_PRESENTATION_STATE,
            "the presentation has not been reviewed",
        )
    if presentation["disclosure_status"] != "COMPLETE":
        fail(errors.ERR_DISCLOSURES_INCOMPLETE, "disclosure_status is not COMPLETE")

    derive.setf(booking, "status", "TOURED")
    rep = db.reps.get(presentation["rep_id"])
    if rep is not None:
        if rep["status"] == "ON_TOUR":
            derive.setf(rep, "status", "ACTIVE")
        derive.setf(rep, "tours_taken_count", rep["tours_taken_count"] + 1)
    channel = db.channels.get(booking["channel_id"])
    if channel is not None:
        derive.setf(channel, "toured_count", channel["toured_count"] + 1)
        derive.recompute_channel_rate(channel)
    return ok(presentation)


@bp.get("/sales-presentations/<presentation_id>")
def read_presentation(presentation_id):
    auth.require_any()
    return ok(get_presentation(presentation_id))


@bp.get("/sales-presentations")
def list_presentations():
    auth.require_any()
    limit, offset = page()
    rows = collect(db.presentations, (("booking_id", "booking_id"), ("rep_id", "rep_id")))
    return listing(rows, limit, offset)


@bp.get("/sales-presentations/<presentation_id>/disclosure-acknowledgments")
def list_acknowledgments(presentation_id):
    auth.require_any()
    limit, offset = page()
    presentation = get_presentation(presentation_id)
    code = validators.query_enum("disclosure_code", calc.DISCLOSURE_CODES)
    rows = [
        ack
        for ack in ordered(db.acknowledgments.values())
        if ack["presentation_id"] == presentation["id"]
        and (code is None or ack["disclosure_code"] == code)
    ]
    return listing(rows, limit, offset)


@bp.get("/sales-presentations/<presentation_id>/prohibited-claim-findings")
def list_findings(presentation_id):
    auth.require_any()
    limit, offset = page()
    presentation = get_presentation(presentation_id)
    severity = validators.query_enum("severity", tuple(calc.SEVERITY_PENALTY_POINTS))
    rows = [
        finding
        for finding in ordered(db.findings.values())
        if finding["presentation_id"] == presentation["id"]
        and (severity is None or finding["severity"] == severity)
    ]
    return listing(rows, limit, offset)
