"""Declared transitions: their preconditions, their stamps and their refusals."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    make_sales_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"
FUNDING_UTC = "2026-08-25T00:00:00Z"
CANCELLATION_UTC = "2026-08-20T12:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
ADJUDICATOR = TEST_USERS["contract_admin_adjudicator_headers"]
DISBURSER = TEST_USERS["contract_admin_disburser_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]
UNDERWRITER = TEST_USERS["contract_admin_underwriter_headers"]


# ---------------------------------------------------------------------------
# Booking: check-in, no-show and the states that follow them
# ---------------------------------------------------------------------------


def test_check_in_binds_the_rotation_winner_and_accrues_the_gift():
    """The winner flips to ON_TOUR while the loser and the tour counters stand still.

    The PRD states: "On success the booking moves `SCHEDULED → CHECKED_IN`,
    `assigned_rep_id` is set to the winner, `checked_in_at` is stamped from the
    logical clock, and the winner moves `ACTIVE → ON_TOUR` with `last_assigned_at`
    stamped."

    The PRD states: "The gallery's `available_rep_count` does not change, because
    an `ON_TOUR` representative still counts as available inventory."

    Design: Corner/state_machines/booking_check_in_flips_representative_and_accrues_gift
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(rep_count=2)
    first_rep, second_rep = scene["reps"]

    fx.pin_clock(CHECK_IN_UTC)
    booking = validate_success(
        api.check_in_tour_booking(
            scene["booking"]["id"], fac.check_in_payload(True), GALLERY
        )
    )
    assert booking["status"] == "CHECKED_IN"
    assert booking["assigned_rep_id"] == first_rep["id"]
    assert_instant_equals(booking["checked_in_at"], CHECK_IN_UTC, "checked_in_at")
    assert booking["gift_issued"] is True
    assert booking["gift_value_cents"] == 12500

    winner = fx.read_representative(first_rep["id"])
    assert winner["status"] == "ON_TOUR"
    assert_instant_equals(winner["last_assigned_at"], CHECK_IN_UTC, "last_assigned_at")
    assert winner["tours_taken_count"] == 0

    loser = fx.read_representative(second_rep["id"])
    assert loser["status"] == "ACTIVE"
    assert loser["tours_taken_count"] == 0

    assert fx.read_channel(scene["channel"]["id"])["gift_liability_cents"] == 12500

    gallery = fx.read_gallery(scene["gallery"]["id"])
    assert gallery["available_rep_count"] == 2
    assert gallery["status"] == "OPEN"
    assert gallery["booked_slot_count"] == 1


def test_the_no_show_transition_waits_for_the_scheduled_start_instant():
    """Two seconds of logical time separate a refusal from an accepted no-show.

    The PRD states: "Marking a no-show is available only from `SCHEDULED`, and only
    once the logical clock has reached or passed the booking's
    `scheduled_start_utc`; an early attempt is rejected with
    `ERR_INVALID_BOOKING_STATE`."

    Design: Corner/state_machines/booking_no_show_before_scheduled_start_precondition
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(rep_count=1)
    booking_id = scene["booking"]["id"]

    validate_error(
        api.mark_tour_booking_no_show(booking_id, MARKETING),
        ApiErrorId.ERR_INVALID_BOOKING_STATE.value,
        409,
    )

    fx.pin_clock("2026-08-14T06:59:59Z")
    validate_error(
        api.mark_tour_booking_no_show(booking_id, MARKETING),
        ApiErrorId.ERR_INVALID_BOOKING_STATE.value,
        409,
    )

    fx.pin_clock(CHECK_IN_UTC)
    marked = validate_success(api.mark_tour_booking_no_show(booking_id, MARKETING))
    assert marked["status"] == "NO_SHOW"

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["no_show_count"] == 1
    assert channel["toured_count"] == 0
    assert channel["historical_no_show_rate"] == 1.0
    assert channel["status"] == "ACTIVE"
    assert channel["booked_count"] == 1

    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 0


def test_a_no_show_booking_accepts_none_of_the_four_remaining_transitions():
    """Check-in, cancel, reschedule and a repeat no-show all bounce off NO_SHOW.

    The PRD states: "The target resource is in a state from which the requested
    transition exists — `ERR_INVALID_BOOKING_STATE`,
    `ERR_INVALID_PRESENTATION_STATE`, `ERR_INVALID_AGREEMENT_STATE`,
    `ERR_INVALID_FINANCING_STATE`, `ERR_INVALID_RESCISSION_REQUEST_STATE`,
    `ERR_INVALID_CLOSING_PACKAGE_STATE` or `ERR_INVALID_RETRAINING_STATE` (409), on
    every action endpoint."

    Design: Corner/state_machines/booking_after_no_show_invalid_transitions
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(rep_count=1)
    booking_id = scene["booking"]["id"]

    fx.pin_clock(CHECK_IN_UTC)
    assert fx.mark_no_show(booking_id)["status"] == "NO_SHOW"

    refusals = [
        api.check_in_tour_booking(booking_id, fac.check_in_payload(True), GALLERY),
        api.cancel_tour_booking(
            booking_id, fac.cancel_booking_payload("PROSPECT_WITHDREW"), MARKETING
        ),
        api.open_reschedule_request(
            booking_id,
            fac.reschedule_request_payload("PROSPECT_REQUESTED_NEW_DATE"),
            MARKETING,
        ),
        api.mark_tour_booking_no_show(booking_id, MARKETING),
    ]
    for response in refusals:
        validate_error(response, ApiErrorId.ERR_INVALID_BOOKING_STATE.value, 409)

    booking = fx.read_booking(booking_id)
    assert booking["status"] == "NO_SHOW"
    assert booking["assigned_rep_id"] is None
    assert booking["gift_issued"] is False
    assert booking["reschedule_count"] == 0
    assert booking["cancel_reason"] is None

    representative = fx.read_representative(scene["reps"][0]["id"])
    assert representative["status"] == "ACTIVE"
    assert representative["tours_taken_count"] == 0

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["no_show_count"] == 1
    assert channel["gift_liability_cents"] == 0


# ---------------------------------------------------------------------------
# Presentation: two dimensions opening, gating and completing
# ---------------------------------------------------------------------------


def test_a_new_presentation_opens_pending_and_unreviewed_and_only_once():
    """The opening score of 70 is the disclosure gap alone, and the booking is claimed.

    The PRD states: "It opens with `required_disclosure_count` fixed at 3,
    `disclosure_ack_count` at 0, `disclosure_status` `PENDING`, `review_status`
    `UNREVIEWED`, `prohibited_claim_points` at 0, `flag_count` at 0,
    `reviewed_by_user_id` null, and `compliance_score` at 70 — which is 100 less 0
    claim points less 30 points of disclosure gap."

    The PRD states: "At most one presentation may exist per booking; a second
    attempt is rejected with `ERR_PRESENTATION_ALREADY_EXISTS`."

    Design: Corner/state_machines/sales_presentation_initial_state_pending_unreviewed
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_checked_in_tour(
        rep_count=1, issue_incentive_gift=False, check_in_at=CHECK_IN_UTC
    )
    rep_id = scene["assigned_rep_id"]

    presentation = validate_success(
        api.create_sales_presentation(
            fac.create_sales_presentation_payload(scene["booking"]["id"]),
            make_sales_representative_headers(rep_id),
        ),
        201,
    )
    assert presentation["disclosure_status"] == "PENDING"
    assert presentation["review_status"] == "UNREVIEWED"
    assert presentation["required_disclosure_count"] == 3
    assert presentation["disclosure_ack_count"] == 0
    assert presentation["prohibited_claim_points"] == 0
    assert presentation["flag_count"] == 0
    assert presentation["compliance_score"] == 70
    assert presentation["rep_id"] == scene["reps"][0]["id"]
    assert_instant_equals(
        presentation["window_start_utc"], CHECK_IN_UTC, "window_start_utc"
    )
    assert_instant_equals(
        presentation["window_end_utc"], EXECUTION_UTC, "window_end_utc"
    )
    assert_instant_equals(presentation["started_at"], CHECK_IN_UTC, "started_at")
    assert presentation["reviewed_by_user_id"] is None
    assert presentation["version"] == 1

    repeat = api.create_sales_presentation(
        fac.create_sales_presentation_payload(
            scene["booking"]["id"], recorded_ack_reference="REC-0002"
        ),
        make_sales_representative_headers(rep_id),
    )
    validate_error(repeat, ApiErrorId.ERR_PRESENTATION_ALREADY_EXISTS.value, 409)


def test_completion_needs_all_three_disclosures_and_a_review_that_has_happened():
    """Two acknowledgments are not enough, and neither is a record nobody reviewed.

    The PRD states: "It requires the booking to be `CHECKED_IN`, requires
    `disclosure_status` to be `COMPLETE` — otherwise `ERR_DISCLOSURES_INCOMPLETE` —
    and requires `review_status` to be anything other than `UNREVIEWED`, otherwise
    `ERR_INVALID_PRESENTATION_STATE`."

    Design: Corner/state_machines/presentation_complete_disclosure_and_review_preconditions
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=1, issue_incentive_gift=False, check_in_at=CHECK_IN_UTC
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]
    rep_headers = make_sales_representative_headers(rep_id)

    for code in ("RESCISSION_RIGHTS", "PUBLIC_OFFERING_STATEMENT_DELIVERY"):
        fx.acknowledge_disclosure(presentation_id, rep_id, code)

    # Both preconditions are broken at once here. PRD 2.9 pins the state gate
    # (priority 8, `ERR_INVALID_PRESENTATION_STATE`) ahead of disclosure
    # completeness (priority 16, `ERR_DISCLOSURES_INCOMPLETE`), and "Where several
    # checks could fire on one request, the earlier one always wins", so the
    # unreviewed record reports the state gate.
    validate_error(
        api.complete_sales_presentation(presentation_id, rep_headers),
        ApiErrorId.ERR_INVALID_PRESENTATION_STATE.value,
        409,
    )

    partial = fx.read_presentation(presentation_id)
    assert partial["disclosure_status"] == "PARTIAL"
    assert partial["disclosure_ack_count"] == 2
    assert partial["compliance_score"] == 90

    reviewed = fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)
    assert reviewed["review_status"] == "CLEARED"
    assert reviewed["reviewed_by_user_id"] == "officer-alpha"

    # With the state gate satisfied, the disclosure shortfall is what surfaces.
    validate_error(
        api.complete_sales_presentation(presentation_id, rep_headers),
        ApiErrorId.ERR_DISCLOSURES_INCOMPLETE.value,
        422,
    )

    fx.acknowledge_disclosure(
        presentation_id,
        rep_id,
        "NOT_AN_INVESTMENT",
        recording_timestamp_offset_seconds=360,
    )
    disclosed = fx.read_presentation(presentation_id)
    assert disclosed["disclosure_status"] == "COMPLETE"
    assert disclosed["disclosure_ack_count"] == 3
    assert disclosed["compliance_score"] == 100

    completed = validate_success(
        api.complete_sales_presentation(presentation_id, rep_headers)
    )
    assert completed["id"] == presentation_id
    assert fx.read_booking(scene["booking"]["id"])["status"] == "TOURED"


def test_completion_bubbles_out_to_the_booking_channel_and_representative():
    """One call moves four records, and the gift liability survives as TOURED accrues.

    The PRD states: "Completion advances the booking `CHECKED_IN → TOURED`, returns
    the representative `ON_TOUR → ACTIVE` and raises their `tours_taken_count` by
    one, raises the channel's `toured_count` by one and recomputes the channel's
    `historical_no_show_rate`."

    The PRD states: "The gallery's `booked_slot_count` is unchanged, because
    `TOURED` remains an occupying status for the day."

    Design: Corner/state_machines/presentation_complete_bubbles_to_booking_channel_and_representative
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_cleared_presentation(
        rep_count=1, issue_incentive_gift=True, check_in_at=CHECK_IN_UTC
    )

    fx.complete_presentation(scene["presentation"]["id"], scene["assigned_rep_id"])

    assert fx.read_booking(scene["booking"]["id"])["status"] == "TOURED"

    representative = fx.read_representative(scene["assigned_rep_id"])
    assert representative["status"] == "ACTIVE"
    assert representative["tours_taken_count"] == 1

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["toured_count"] == 1
    assert channel["no_show_count"] == 0
    assert channel["historical_no_show_rate"] == 0.0
    assert channel["gift_liability_cents"] == 12500

    gallery = fx.read_gallery(scene["gallery"]["id"])
    assert gallery["booked_slot_count"] == 1
    assert gallery["available_rep_count"] == 1


# ---------------------------------------------------------------------------
# Agreement: two dimensions, the sweep epoch and funding
# ---------------------------------------------------------------------------


def test_an_all_cash_agreement_expires_and_funds_on_independent_dimensions():
    """The sweep moves one dimension, funding moves the other, and neither repeats.

    The PRD states: "A `PlatformAdmin` advances it, and every agreement whose
    `rescission_status` is `OPEN` and whose `rescission_deadline_utc` lies strictly
    behind the logical clock moves `OPEN → EXPIRED`."

    The PRD states: "Funding advances `fulfillment_status` `AWAITING_FUNDING →
    FUNDED`, stamps `funded_at` from the logical clock, records the
    `funding_reference`, and sets `total_collected_cents` to
    `escrow_collected_cents` plus `collected_amount_cents`."

    Design: Corner/state_machines/agreement_parallel_dimensions_advance_independently_all_cash
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        agreement_overrides={
            "product_type": "RIGHT_TO_USE",
            "state_code": "FL",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 3_200_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]
    agreement_id = agreement["id"]
    assert agreement["total_due_cents"] == 3_200_000
    assert agreement["down_payment_required_cents"] == 320_000
    assert agreement["base_financed_cents"] == 0
    assert agreement["doc_stamp_cents"] == 0
    assert agreement["closing_cost_fee_cents"] == 0
    assert agreement["financed_amount_cents"] == 0
    assert agreement["escrow_collected_cents"] == 3_200_000

    fx.pin_clock(FUNDING_UTC)
    first_sweep = fx.sweep_rescissions()
    assert first_sweep["swept_count"] == 1
    assert first_sweep["expired_agreement_ids"] == [agreement_id]

    expired = fx.read_agreement(agreement_id)
    assert expired["rescission_status"] == "EXPIRED"
    assert expired["fulfillment_status"] == "AWAITING_FUNDING"

    second_sweep = fx.sweep_rescissions()
    assert second_sweep["swept_count"] == 0
    assert second_sweep["expired_agreement_ids"] == []

    funded = validate_success(
        api.fund_purchase_agreement(
            agreement_id, fac.fund_payload(0, funding_reference="FND-0002"), FUNDER
        )
    )
    assert funded["fulfillment_status"] == "FUNDED"
    assert_instant_equals(funded["funded_at"], FUNDING_UTC, "funded_at")
    assert funded["funding_reference"] == "FND-0002"
    assert funded["total_collected_cents"] == 3_200_000
    assert funded["rescission_status"] == "EXPIRED"

    assert fx.read_prospect(scene["prospect"]["id"])["is_existing_owner"] is True

    packages, meta = validate_paginated(
        api.list_closing_packages(FUNDER, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
    assert packages[0]["instrument_type"] == "RTU_CERTIFICATE"

    validate_error(
        api.fund_purchase_agreement(
            agreement_id, fac.fund_payload(0, funding_reference="FND-0003"), FUNDER
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )
    assert fx.read_agreement(agreement_id)["funding_reference"] == "FND-0002"


# ---------------------------------------------------------------------------
# Financing: the declined branch writes nothing and closes the loop
# ---------------------------------------------------------------------------


def test_a_declined_application_keeps_every_underwriting_field_null():
    """The decline stamps only who decided and when, and DECLINED accepts no retry.

    The PRD states: "The `SUBMITTED → DECLINED` branch populates nothing at all:
    `apr_bps`, `max_ltv_rate`, `ltv_cap_cents`, `approved_amount_cents` and
    `monthly_payment_cents` all remain null."

    The PRD states: "The application must be `SUBMITTED`, otherwise the request is
    rejected with `ERR_INVALID_FINANCING_STATE`."

    Design: Corner/state_machines/financing_decline_leaves_underwriting_fields_null
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
    )
    agreement = fx.read_agreement(scene["agreement"]["id"])

    application = fx.submit_financing(
        agreement["id"],
        scene["assigned_rep_id"],
        agreement["version"],
        applicant_fico=700,
    )
    assert application["status"] == "SUBMITTED"
    assert application["apr_bps"] is None
    assert application["approved_amount_cents"] is None

    declined = validate_success(
        api.decide_financing_application(
            application["id"], fac.financing_decision_payload("DECLINE"), UNDERWRITER
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["apr_bps"] is None
    assert declined["max_ltv_rate"] is None
    assert declined["ltv_cap_cents"] is None
    assert declined["approved_amount_cents"] is None
    assert declined["monthly_payment_cents"] is None
    assert_instant_equals(declined["decided_at"], EXECUTION_UTC, "decided_at")
    assert declined["decided_by_user_id"] == "admin-underwriter"

    validate_error(
        api.decide_financing_application(
            application["id"], fac.financing_decision_payload("APPROVE"), UNDERWRITER
        ),
        ApiErrorId.ERR_INVALID_FINANCING_STATE.value,
        409,
    )


# ---------------------------------------------------------------------------
# Closing: record then deliver, each bubbling the agreement upward
# ---------------------------------------------------------------------------


def test_the_closing_package_must_be_recorded_before_it_can_be_delivered():
    """Delivery first is refused, and each accepted step lifts the agreement with it.

    The PRD states: "Recording supplies a `recording_reference` and a
    `recording_jurisdiction`; it requires the package to be `AWAITING_RECORDING` and
    the agreement to be `FUNDED`, moves the package `AWAITING_RECORDING →
    RECORDED`, stamps `recorded_at`, and re-derives the agreement `FUNDED →
    RECORDED`."

    The PRD states: "Delivery supplies a `delivery_method` of `COURIER`,
    `ELECTRONIC_PORTAL` or `CERTIFIED_MAIL`; it requires the package to be
    `RECORDED`, moves the package `RECORDED → DELIVERED`, stamps
    `documents_delivered_at`, and re-derives the agreement `RECORDED →
    DOCS_DELIVERED`, which is terminal for the fulfillment dimension and is also
    the only state from which the interest can later be surrendered in a trade-in."

    Design: Corner/state_machines/closing_package_record_then_deliver_bubbles_agreement_fulfillment
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_funded_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
    )
    package_id = scene["closing_package"]["id"]
    agreement_id = scene["agreement"]["id"]
    assert scene["closing_package"]["instrument_type"] == "DEED"
    assert scene["closing_package"]["status"] == "AWAITING_RECORDING"

    validate_error(
        api.deliver_closing_package(
            package_id, fac.deliver_closing_package_payload("COURIER"), FUNDER
        ),
        ApiErrorId.ERR_INVALID_CLOSING_PACKAGE_STATE.value,
        409,
    )

    recorded = validate_success(
        api.record_closing_package(
            package_id,
            fac.record_closing_package_payload(
                recording_reference="OR-BK-9921-PG-114",
                recording_jurisdiction="Orange County FL",
            ),
            FUNDER,
        )
    )
    assert recorded["status"] == "RECORDED"
    assert recorded["recording_reference"] == "OR-BK-9921-PG-114"
    assert_instant_equals(recorded["recorded_at"], FUNDING_UTC, "recorded_at")
    assert fx.read_agreement(agreement_id)["fulfillment_status"] == "RECORDED"

    validate_error(
        api.record_closing_package(
            package_id,
            fac.record_closing_package_payload(
                recording_reference="OR-BK-9921-PG-115",
                recording_jurisdiction="Orange County FL",
            ),
            FUNDER,
        ),
        ApiErrorId.ERR_INVALID_CLOSING_PACKAGE_STATE.value,
        409,
    )
    assert (
        fx.read_closing_package(package_id)["recording_reference"]
        == "OR-BK-9921-PG-114"
    )

    delivered = validate_success(
        api.deliver_closing_package(
            package_id, fac.deliver_closing_package_payload("COURIER"), FUNDER
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivery_method"] == "COURIER"
    assert_instant_equals(
        delivered["documents_delivered_at"], FUNDING_UTC, "documents_delivered_at"
    )

    agreement = fx.read_agreement(agreement_id)
    assert agreement["fulfillment_status"] == "DOCS_DELIVERED"
    assert agreement["rescission_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Refund: one disbursement per request, settled exactly once
# ---------------------------------------------------------------------------


def test_the_refund_can_be_created_and_settled_only_once_per_cancellation():
    """Every repeat of the adjudication, the create and the settle is refused.

    The PRD states: "The request must be `VALIDATED`, otherwise
    `ERR_INVALID_RESCISSION_REQUEST_STATE`, and only one disbursement may exist per
    request, with a second attempt rejected as `ERR_REFUND_ALREADY_ISSUED`."

    The PRD states: "It supplies a `settlement_reference`, moves the disbursement
    `PENDING → ISSUED`, stamps `settled_at`, advances the rescission request
    `VALIDATED → REFUNDED`, and writes the agreement's `retained_cents` as
    `gift_recapture_cents` plus `doc_fee_retained_cents`."

    Design: Corner/state_machines/refund_disbursement_repeat_calls_rejected_after_settlement
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=2,
        issue_incentive_gift=True,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        agreement_overrides={
            "product_type": "DEEDED_INTEREST",
            "state_code": "FL",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement_id = scene["agreement"]["id"]

    fx.pin_clock(CANCELLATION_UTC)
    request = fx.intake_rescission(agreement_id, "HAND_DELIVERED")
    request_id = request["id"]
    assert fx.adjudicate_rescission(request_id)["status"] == "VALIDATED"

    validate_error(
        api.adjudicate_rescission_request(request_id, ADJUDICATOR),
        ApiErrorId.ERR_INVALID_RESCISSION_REQUEST_STATE.value,
        409,
    )

    disbursement = validate_success(
        api.create_refund_disbursement(
            fac.create_refund_disbursement_payload(request_id, "ACH"), DISBURSER
        ),
        201,
    )
    assert disbursement["refund_policy_applied"] == "STATUTORY_FULL"
    assert disbursement["base_refund_cents"] == 320_000
    assert disbursement["gift_recapture_cents"] == 0
    assert disbursement["doc_fee_retained_cents"] == 0
    assert disbursement["disbursed_amount_cents"] == 320_000

    validate_error(
        api.create_refund_disbursement(
            fac.create_refund_disbursement_payload(request_id, "CHECK"), DISBURSER
        ),
        ApiErrorId.ERR_REFUND_ALREADY_ISSUED.value,
        409,
    )

    settled = validate_success(
        api.settle_refund_disbursement(
            disbursement["id"], fac.settle_payload("ACH-88231"), DISBURSER
        )
    )
    assert settled["status"] == "ISSUED"
    assert settled["settlement_reference"] == "ACH-88231"
    assert_instant_equals(settled["settled_at"], CANCELLATION_UTC, "settled_at")
    assert fx.read_rescission_request(request_id)["status"] == "REFUNDED"

    validate_error(
        api.settle_refund_disbursement(
            disbursement["id"], fac.settle_payload("ACH-88232"), DISBURSER
        ),
        ApiErrorId.ERR_INVALID_RESCISSION_REQUEST_STATE.value,
        409,
    )
    assert (
        fx.read_disbursement(disbursement["id"])["settlement_reference"] == "ACH-88231"
    )

    # Settlement moved the request `VALIDATED -> REFUNDED`, so a further create no
    # longer reaches the uniqueness rule: PRD 2.9 pins the state gate (priority 8,
    # "The request must be `VALIDATED`, otherwise
    # `ERR_INVALID_RESCISSION_REQUEST_STATE`") ahead of priority 11
    # (`ERR_REFUND_ALREADY_ISSUED`), and the earlier check always wins.
    validate_error(
        api.create_refund_disbursement(
            fac.create_refund_disbursement_payload(request_id, "ACH"), DISBURSER
        ),
        ApiErrorId.ERR_INVALID_RESCISSION_REQUEST_STATE.value,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_refund_disbursements(
            INTAKE, params={"rescission_request_id": request_id}
        )
    )
    assert meta["total_count"] == 1

    agreement = fx.read_agreement(agreement_id)
    assert agreement["rescission_status"] == "RESCINDED"
    assert agreement["fulfillment_status"] == "VOIDED"
    assert agreement["retained_cents"] == 0


# ---------------------------------------------------------------------------
# Retraining: the completing close is the only strike reset in the system
# ---------------------------------------------------------------------------


def test_a_completed_retraining_resets_the_strike_and_closes_the_loop():
    """Three modules of four is a shortfall; the fourth restores the rotation.

    The PRD states: "A `COMPLETE` close requires `modules_completed` to be at least
    `required_module_count`, otherwise it is rejected with
    `ERR_MODULE_COUNT_SHORTFALL`."

    The PRD states: "On success it stamps `closed_at`, records the module count,
    moves the assignment `IN_PROGRESS → COMPLETED`, and then runs a three-step
    restoration: the representative's `compliance_strike_count` is reset to 0 — the
    only mechanism in the system that resets strikes; the representative returns to
    `ACTIVE`, but only when no other assignment for them still sits in `ASSIGNED` or
    `IN_PROGRESS`; and the gallery's `available_rep_count` is recomputed, so a
    `RESTRICTED` gallery whose count has reached at least 1 returns to `OPEN`."

    Design: Corner/state_machines/retraining_complete_resets_strike_count_across_entities
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=2, issue_incentive_gift=False, check_in_at=CHECK_IN_UTC
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]

    fx.acknowledge_required_disclosures(presentation_id, rep_id)
    assert fx.review_presentation(presentation_id, "FLAG", OFFICER_ALPHA)[
        "review_status"
    ] == "FLAGGED"
    fx.complete_presentation(presentation_id, rep_id)

    struck = fx.read_representative(rep_id)
    assert struck["compliance_strike_count"] == 1
    assignment = fx.assign_retraining(
        rep_id,
        struck["version"],
        "PROHIBITED_CLAIM_POINTS",
        required_module_count=4,
    )
    assert assignment["strike_count_at_assignment"] == 1
    assignment_id = assignment["id"]
    assert fx.start_retraining(assignment_id)["status"] == "IN_PROGRESS"
    assert fx.read_representative(rep_id)["status"] == "RETRAINING"

    validate_error(
        api.close_retraining_assignment(
            assignment_id, fac.close_retraining_payload("COMPLETE", 3), OFFICER_ALPHA
        ),
        ApiErrorId.ERR_MODULE_COUNT_SHORTFALL.value,
        422,
    )
    unchanged = fx.read_retraining_assignment(assignment_id)
    assert unchanged["status"] == "IN_PROGRESS"
    assert unchanged["modules_completed"] == 0

    completed = validate_success(
        api.close_retraining_assignment(
            assignment_id, fac.close_retraining_payload("COMPLETE", 4), OFFICER_ALPHA
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["modules_completed"] == 4
    assert_instant_equals(completed["closed_at"], CHECK_IN_UTC, "closed_at")
    assert completed["cycle_index"] == 1

    restored = fx.read_representative(rep_id)
    assert restored["status"] == "ACTIVE"
    assert restored["compliance_strike_count"] == 0

    gallery = fx.read_gallery(scene["gallery"]["id"])
    assert gallery["available_rep_count"] == 2
    assert gallery["status"] == "OPEN"

    validate_error(
        api.close_retraining_assignment(
            assignment_id, fac.close_retraining_payload("FAIL", 4), OFFICER_ALPHA
        ),
        ApiErrorId.ERR_INVALID_RETRAINING_STATE.value,
        409,
    )
