"""On-time in-full scorecards and the repeat-offender corrective action
pipeline (PRD 3.7 and 3.8)."""

from decimal import Decimal

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    BUYING_DECISIONS,
    CAP_MAX_SUBMISSIONS,
    MEASUREMENT_VARIANTS,
    ROLE_CATEGORY_BUYER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VENDOR,
    SCORECARD_PERIOD_GAP_DAYS,
    ApiError,
    authenticate,
    body_dict,
    clock,
    days,
    invalid,
    new_record,
    object_response,
    opt_decimal,
    opt_int,
    req_dt,
    req_enum,
    req_str,
    store,
    touch,
)
from derive import (
    cap_due_at,
    measure_scorecard,
    reconcile_vendor,
    repeat_offender_escalation,
    select_predecessor_cap_id,
)

bp = Blueprint("performance", __name__)

OFFICER = (ROLE_COMPLIANCE_OFFICER,)
VENDOR = (ROLE_VENDOR,)
BUYER = (ROLE_CATEGORY_BUYER,)

LIVE_PERIOD_STATES = ("OPEN", "MEASURED", "FINALIZED")


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------


@bp.post("/compliance/scorecards")
def open_scorecard():
    authenticate(OFFICER)
    body = body_dict()
    vendor_id = req_str(body, "vendor_id")
    period_code = req_str(body, "period_code", 1, 16)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end <= period_start:
        raise invalid("Field 'period_end' must be later than 'period_start'.")
    tolerance_early_days = opt_int(body, "tolerance_early_days", 0, 14, default=2)
    tolerance_late_days = opt_int(body, "tolerance_late_days", 0, 14, default=0)
    fill_tolerance_pct = opt_decimal(
        body, "fill_tolerance_pct", 0, 10, default=Decimal("2.00")
    )

    vendor = lookup.vendor(vendor_id)

    gap = days(SCORECARD_PERIOD_GAP_DAYS)
    for existing in store.scorecards.values():
        if existing["vendor_id"] != vendor["id"]:
            continue
        if existing["status"] not in LIVE_PERIOD_STATES:
            continue
        if (
            period_start <= existing["period_end"] + gap
            and existing["period_start"] <= period_end + gap
        ):
            raise ApiError(
                "ERR_SCORECARD_PERIOD_OVERLAP",
                "This period overlaps or adjoins an existing measurement period.",
            )

    scorecard = new_record(
        vendor_id=vendor["id"],
        period_code=period_code,
        period_start=period_start,
        period_end=period_end,
        tolerance_early_days=tolerance_early_days,
        tolerance_late_days=tolerance_late_days,
        fill_tolerance_pct=fill_tolerance_pct,
        measurement_variant=None,
        status="OPEN",
        measured_po_count=0,
        on_time_count=0,
        in_full_count=0,
        otif_count=0,
        on_time_pct=Decimal("0.00"),
        fill_rate_pct=Decimal("0.00"),
        otif_pct=Decimal("0.00"),
        composite_score=Decimal("0.00"),
        cap_required=False,
        measured_at=None,
        finalized_at=None,
    )
    store.scorecards[scorecard["id"]] = scorecard
    return object_response(ser.scorecard_out(scorecard), 201)


@bp.post("/compliance/scorecards/<identifier>/measure")
def measure(identifier):
    authenticate(OFFICER)
    body = body_dict()
    variant = req_enum(body, "measurement_variant", MEASUREMENT_VARIANTS)

    scorecard = lookup.scorecard(identifier)
    if scorecard["status"] == "FINALIZED":
        raise ApiError(
            "ERR_SCORECARD_ALREADY_FINALIZED",
            "A finalized scorecard may not be measured again.",
        )

    figures = measure_scorecard(scorecard, variant)
    if figures is None:
        raise ApiError(
            "ERR_SCORECARD_NO_MEASURABLE_ORDERS",
            "The period contains no measurable purchase orders.",
        )

    scorecard.update(figures)
    escalation = repeat_offender_escalation(
        scorecard["vendor_id"], scorecard["period_end"], figures["composite_score"]
    )
    scorecard["cap_required"] = escalation["cap_required"]
    scorecard["measurement_variant"] = variant
    scorecard["measured_at"] = clock.now()
    scorecard["status"] = "MEASURED"
    touch(scorecard)
    return object_response(ser.scorecard_out(scorecard))


@bp.post("/compliance/scorecards/<identifier>/finalize")
def finalize(identifier):
    authenticate(OFFICER)
    body_dict()

    scorecard = lookup.scorecard(identifier)
    if scorecard["status"] == "FINALIZED":
        raise ApiError(
            "ERR_SCORECARD_ALREADY_FINALIZED", "This scorecard is already finalized."
        )
    if scorecard["status"] != "MEASURED":
        raise ApiError(
            "ERR_SCORECARD_NOT_MEASURED", "The scorecard must be measured before finalization."
        )

    vendor = store.vendors.get(scorecard["vendor_id"])
    escalation = repeat_offender_escalation(
        scorecard["vendor_id"], scorecard["period_end"], scorecard["composite_score"]
    )

    # Cascade link 1.
    scorecard["status"] = "FINALIZED"
    scorecard["finalized_at"] = clock.now()
    touch(scorecard)

    if vendor is None:
        return object_response(ser.scorecard_out(scorecard))

    # Cascade link 2.
    vendor["repeat_offender_flag"] = escalation["repeat_offender_flag"]

    # Cascade link 3.
    if scorecard["cap_required"]:
        issued_at = clock.now()
        level = escalation["escalation_level"]
        cap = new_record(
            vendor_id=vendor["id"],
            trigger_scorecard_id=scorecard["id"],
            predecessor_cap_id=select_predecessor_cap_id(vendor["id"]),
            status="ISSUED",
            escalation_level=level,
            repeat_count=escalation["repeat_count"],
            milestone_text=None,
            committed_completion_at=None,
            due_at=cap_due_at(issued_at, level),
            buying_decision="NONE",
            submission_round=0,
            issued_at=issued_at,
            decided_at=None,
            escalated_at=None,
            closed_at=None,
            review_note=None,
            escalation_note=None,
            closure_note=None,
        )
        store.caps[cap["id"]] = cap

        # Cascade link 4.
        if vendor["status"] == "ACTIVE":
            vendor["status"] = "PROBATION"

    reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.scorecard_out(scorecard))


# ---------------------------------------------------------------------------
# Corrective action plans
# ---------------------------------------------------------------------------


@bp.post("/compliance/corrective-action-plans/<identifier>/submit")
def submit_cap(identifier):
    user_id, _role = authenticate(VENDOR)
    body = body_dict()
    milestone_text = req_str(body, "milestone_text", 1, 1000)
    committed_completion_at = req_dt(body, "committed_completion_at")

    cap = lookup.cap(identifier)
    if cap["vendor_id"] != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION", "A vendor may only submit its own remediation plan."
        )
    if cap["status"] not in ("ISSUED", "REJECTED"):
        raise ApiError(
            "ERR_CAP_NOT_AWAITING_SUBMISSION", "This plan is not awaiting a submission."
        )
    if cap["submission_round"] >= CAP_MAX_SUBMISSIONS:
        raise ApiError(
            "ERR_CAP_SUBMISSION_LIMIT_EXCEEDED", "The submission limit has been reached."
        )
    if committed_completion_at > cap["due_at"]:
        raise ApiError(
            "ERR_CAP_COMMITMENT_PAST_DUE",
            "committed_completion_at may not fall later than the plan's due_at.",
        )

    cap["status"] = "VENDOR_SUBMITTED"
    cap["milestone_text"] = milestone_text
    cap["committed_completion_at"] = committed_completion_at
    cap["submission_round"] = cap["submission_round"] + 1
    touch(cap)
    return object_response(ser.cap_out(cap))


@bp.post("/compliance/corrective-action-plans/<identifier>/decide")
def decide_cap(identifier):
    authenticate(OFFICER)
    body = body_dict()
    decision = req_enum(body, "decision", ("ACCEPT", "REJECT"))
    review_note = req_str(body, "review_note", 1, 1000)

    cap = lookup.cap(identifier)
    if cap["status"] != "VENDOR_SUBMITTED":
        raise ApiError("ERR_CAP_NOT_DECIDABLE", "Only a submitted plan may be decided.")

    cap["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    cap["review_note"] = review_note
    cap["decided_at"] = clock.now()
    touch(cap)
    return object_response(ser.cap_out(cap))


@bp.post("/compliance/corrective-action-plans/<identifier>/escalate")
def escalate_cap(identifier):
    authenticate(BUYER)
    body = body_dict()
    buying_decision = req_enum(body, "buying_decision", BUYING_DECISIONS)
    escalation_note = req_str(body, "escalation_note", 1, 1000)

    cap = lookup.cap(identifier)
    if cap["status"] != "REJECTED":
        raise ApiError("ERR_CAP_NOT_ESCALATABLE", "Only a rejected plan may be escalated.")
    if buying_decision == "NONE":
        raise ApiError(
            "ERR_CAP_ESCALATION_LEVEL_TOO_LOW",
            "A buying decision of NONE is not accepted at escalation.",
        )
    if buying_decision == "SOURCING_HOLD" and cap["escalation_level"] < 2:
        raise ApiError(
            "ERR_CAP_ESCALATION_LEVEL_TOO_LOW",
            "A sourcing hold requires an escalation level of at least 2.",
        )

    cap["status"] = "ESCALATED"
    cap["buying_decision"] = buying_decision
    cap["escalation_note"] = escalation_note
    cap["escalated_at"] = clock.now()
    touch(cap)

    vendor = store.vendors.get(cap["vendor_id"])
    if (
        buying_decision == "SOURCING_HOLD"
        and vendor is not None
        and vendor["status"] == "PROBATION"
    ):
        vendor["status"] = "SOURCING_HOLD"
        reconcile_vendor(vendor, force_bump=True)
    elif vendor is not None:
        reconcile_vendor(vendor)
    return object_response(ser.cap_out(cap))


@bp.post("/compliance/corrective-action-plans/<identifier>/close")
def close_cap(identifier):
    authenticate(OFFICER)
    body = body_dict()
    outcome = req_enum(body, "outcome", ("SUCCESS", "FAILED"))
    closure_note = req_str(body, "closure_note", 1, 1000)

    cap = lookup.cap(identifier)
    if cap["status"] not in ("ACCEPTED", "ESCALATED"):
        raise ApiError(
            "ERR_CAP_NOT_CLOSABLE", "Only an accepted or escalated plan may be closed."
        )

    was_escalated = cap["status"] == "ESCALATED"
    was_accepted = cap["status"] == "ACCEPTED"
    vendor = store.vendors.get(cap["vendor_id"])
    open_before = vendor["open_cap_count"] if vendor is not None else 0

    cap["status"] = "CLOSED_SUCCESS" if outcome == "SUCCESS" else "CLOSED_UNREMEDIATED"
    cap["closure_note"] = closure_note
    cap["closed_at"] = clock.now()
    touch(cap)

    if vendor is None:
        return object_response(ser.cap_out(cap))

    restored = False
    if outcome == "SUCCESS":
        if (
            was_escalated
            and cap["buying_decision"] == "SOURCING_HOLD"
            and vendor["status"] == "SOURCING_HOLD"
        ):
            vendor["status"] = "PROBATION"
            restored = True
        elif was_accepted and open_before == 1 and vendor["status"] == "PROBATION":
            vendor["status"] = "ACTIVE"
            restored = True

    reconcile_vendor(vendor, force_bump=restored)
    return object_response(ser.cap_out(cap))
