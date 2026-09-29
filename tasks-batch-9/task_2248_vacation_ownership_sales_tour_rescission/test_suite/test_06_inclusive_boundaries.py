"""Boundaries one unit wide: half-cents, the final millisecond and inclusive floors."""

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
FL_DEADLINE = "2026-08-24T23:59:59.999Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]


# ---------------------------------------------------------------------------
# The required down payment rounds half-up and compares inclusively
# ---------------------------------------------------------------------------


def _cleared_presentation_ready_to_sign():
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_cleared_presentation(
        rep_count=1, issue_incentive_gift=False, check_in_at=CHECK_IN_UTC
    )
    fx.pin_clock(EXECUTION_UTC)
    return scene


def _sign_for(scene, purchase_price_cents, down_payment_cents):
    return api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            scene["presentation"]["id"],
            product_type="DEEDED_INTEREST",
            state_code="FL",
            purchase_price_cents=purchase_price_cents,
            down_payment_cents=down_payment_cents,
            pos_delivered_at=POS_DELIVERED_AT,
        ),
        make_sales_representative_headers(scene["assigned_rep_id"]),
    )


def test_a_half_cent_requirement_rounds_up_and_refuses_the_cent_below_it():
    """A 320000.5-cent requirement becomes 320001, so 320000 is one cent short.

    The PRD states: "If the submitted `down_payment_cents` is below that
    requirement, the execution is rejected with `ERR_DOWN_PAYMENT_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/down_payment_required_inclusive_boundary_one_cent
    """
    scene = _cleared_presentation_ready_to_sign()

    refused = _sign_for(scene, 3_200_005, 320_000)
    validate_error(refused, ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT.value, 422)

    accepted = validate_success(_sign_for(scene, 3_200_005, 320_001), 201)
    assert accepted["down_payment_required_cents"] == 320_001
    assert accepted["escrow_collected_cents"] == 320_001


def test_the_accepted_cent_flows_through_the_whole_financial_chain():
    """Paying exactly the rounded-up requirement is accepted and priced from it.

    The PRD states: "`down_payment_required_cents` is the total multiplied by the
    applicable rate, rounded half-up to a whole cent."

    Design: Difficulty/boundary_precision_check/down_payment_required_inclusive_boundary_one_cent
    """
    scene = _cleared_presentation_ready_to_sign()

    agreement = validate_success(_sign_for(scene, 3_200_005, 320_001), 201)
    assert agreement["total_due_cents"] == 3_200_005
    assert agreement["base_financed_cents"] == 2_880_004
    assert agreement["doc_stamp_cents"] == 10_080
    assert agreement["closing_cost_fee_cents"] == 139_980
    assert agreement["financed_amount_cents"] == 3_019_984


# ---------------------------------------------------------------------------
# The deadline is inclusive of its final millisecond
# ---------------------------------------------------------------------------


def _two_florida_agreements_past_their_deadline():
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_parallel_cleared_presentations(count=2, issue_incentive_gift=False)
    fx.pin_clock(EXECUTION_UTC)
    scene["agreements"] = [
        fx.execute_agreement(
            scene["presentations"][index]["id"],
            scene["assigned_rep_ids"][index],
            state_code="FL",
            product_type="DEEDED_INTEREST",
            pos_delivered_at=POS_DELIVERED_AT,
        )
        for index in range(2)
    ]
    fx.pin_clock("2026-08-25T08:00:00Z")
    return scene


def test_a_postmark_on_the_final_millisecond_is_still_timely():
    """23:59:59.999Z is inside the window and validates the cancellation.

    The PRD states: "`is_timely` is then true when `effective_utc` is at or before
    the agreement's frozen `rescission_deadline_utc`; equality counts as timely."

    Design: Difficulty/boundary_precision_check/rescission_deadline_inclusive_millisecond_boundary
    """
    scene = _two_florida_agreements_past_their_deadline()
    agreement = scene["agreements"][0]
    assert_instant_equals(
        agreement["rescission_deadline_utc"], FL_DEADLINE, "rescission_deadline_utc"
    )
    assert agreement["business_day_rolled"] is False

    request = fx.intake_rescission(
        agreement["id"], "CERTIFIED_MAIL", postmark_utc=FL_DEADLINE
    )
    assert request["timeliness_basis"] == "POSTMARK"
    assert_instant_equals(request["effective_utc"], FL_DEADLINE, "effective_utc")
    assert request["is_timely"] is True

    adjudicated = fx.adjudicate_rescission(request["id"])
    assert adjudicated["status"] == "VALIDATED"

    voided = fx.read_agreement(agreement["id"])
    assert voided["rescission_status"] == "RESCINDED"
    assert voided["fulfillment_status"] == "VOIDED"


def test_one_millisecond_later_is_late_and_the_void_cascade_never_runs():
    """2026-08-25T00:00:00.000Z misses the window by a single millisecond.

    The PRD states: "`rescission_deadline_utc` is that final date at
    `23:59:59.999Z`."

    Design: Difficulty/boundary_precision_check/rescission_deadline_inclusive_millisecond_boundary
    """
    scene = _two_florida_agreements_past_their_deadline()
    agreement = scene["agreements"][1]
    assert_instant_equals(
        agreement["rescission_deadline_utc"], FL_DEADLINE, "rescission_deadline_utc"
    )

    request = fx.intake_rescission(
        agreement["id"], "CERTIFIED_MAIL", postmark_utc="2026-08-25T00:00:00.000Z"
    )
    assert request["timeliness_basis"] == "POSTMARK"
    assert_instant_equals(
        request["effective_utc"], "2026-08-25T00:00:00.000Z", "effective_utc"
    )
    assert request["is_timely"] is False

    adjudicated = fx.adjudicate_rescission(request["id"])
    assert adjudicated["status"] == "REJECTED_LATE"

    untouched = fx.read_agreement(agreement["id"])
    assert untouched["rescission_status"] == "OPEN"
    assert untouched["fulfillment_status"] == "AWAITING_FUNDING"

    _rows, meta = validate_paginated(api.list_retraining_assignments(GALLERY))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# The compliance clear floor is inclusive on the passing side
# ---------------------------------------------------------------------------


def _presentation_scoring_exactly_seventy():
    """Two MAJOR findings on a fully disclosed record: 100 - 30 - 0 = 70."""
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=2, issue_incentive_gift=False, check_in_at=CHECK_IN_UTC
    )
    presentation_id = scene["presentation"]["id"]
    fx.acknowledge_required_disclosures(presentation_id, scene["assigned_rep_id"])
    for claim_code in ("GUARANTEED_RESALE", "RENTAL_INCOME_PROMISE"):
        observed = fx.read_presentation(presentation_id)
        fx.file_claim_finding(
            presentation_id,
            "MAJOR",
            observed["version"],
            claim_code=claim_code,
            headers=OFFICER_BRAVO,
        )
    scene["presentation"] = fx.read_presentation(presentation_id)
    return scene


def test_a_score_of_exactly_seventy_can_still_be_cleared():
    """The gate reads "at least 70", so the floor itself passes.

    The PRD states: "A `CLEAR` decision — reachable from `UNREVIEWED` and from
    `FLAGGED`, closing the review loop in both directions — additionally requires
    that the presentation's `compliance_score` has reached at least 70 and that no
    finding on it carries `severity` `EGREGIOUS`; failing either condition rejects
    the decision with `ERR_PRESENTATION_NOT_CLEARED`."

    Design: Difficulty/boundary_precision_check/compliance_clear_floor_inclusive_boundary
    """
    scene = _presentation_scoring_exactly_seventy()
    presentation = scene["presentation"]
    assert presentation["prohibited_claim_points"] == 30
    assert presentation["compliance_score"] == 70
    assert presentation["review_status"] == "UNREVIEWED"

    cleared = fx.review_presentation(presentation["id"], "CLEAR", OFFICER_ALPHA)
    assert cleared["review_status"] == "CLEARED"
    assert fx.read_gallery(scene["gallery"]["id"])["status"] == "OPEN"


def test_five_points_below_the_floor_auto_flags_and_refuses_the_same_clear():
    """A third MINOR finding drops the score to 65 and closes the clear path.

    The PRD states: "The floor is inclusive on the passing side — a fully
    disclosed presentation carrying exactly two `MAJOR` findings scores 70 and is
    *not* auto-flagged, while a third `MINOR` finding drops it to 65 and flags
    it."

    Design: Difficulty/boundary_precision_check/compliance_clear_floor_inclusive_boundary
    """
    scene = _presentation_scoring_exactly_seventy()
    presentation_id = scene["presentation"]["id"]
    fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)

    observed = fx.read_presentation(presentation_id)
    fx.file_claim_finding(
        presentation_id,
        "MINOR",
        observed["version"],
        claim_code="UNLIMITED_AVAILABILITY",
        headers=OFFICER_BRAVO,
    )

    flagged = fx.read_presentation(presentation_id)
    assert flagged["prohibited_claim_points"] == 35
    assert flagged["compliance_score"] == 65
    assert flagged["review_status"] == "FLAGGED"
    assert flagged["flag_count"] == 1

    representative = fx.read_representative(scene["assigned_rep_id"])
    assert representative["compliance_strike_count"] == 1
    assert representative["status"] != "SUSPENDED"

    refused = api.review_sales_presentation(
        presentation_id, fac.review_payload("CLEAR"), OFFICER_ALPHA
    )
    validate_error(refused, ApiErrorId.ERR_PRESENTATION_NOT_CLEARED.value, 422)
    assert fx.read_gallery(scene["gallery"]["id"])["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Qualification: the income tier and the score gate are both inclusive
# ---------------------------------------------------------------------------


def _strict_channel_with_three_households():
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel(
        name="Strict Qualification Desk",
        channel_code="OFF_PROPERTY_CONTACT",
        incentive_gift_value_cents=12500,
        min_age=30,
        min_household_income_cents=5_000_000,
        min_qualification_score=70,
    )
    return {
        "gallery": gallery,
        "channel": channel,
        "on_tier": fx.create_prospect(
            household_name="Okafor Household",
            primary_age=30,
            household_income_cents=7_500_000,
            marital_status="MARRIED",
        ),
        "one_cent_below_tier": fx.create_prospect(
            household_name="Nakamura Household",
            primary_age=30,
            household_income_cents=7_499_999,
            marital_status="MARRIED",
        ),
        "one_year_too_young": fx.create_prospect(
            household_name="Delgado Household",
            primary_age=29,
            household_income_cents=7_500_000,
            marital_status="MARRIED",
        ),
    }


def _book_for(scene, prospect_key):
    return api.create_tour_booking(
        fac.create_tour_booking_payload(
            scene["channel"]["id"],
            scene[prospect_key]["id"],
            scene["gallery"]["id"],
            scheduled_start_utc=CHECK_IN_UTC,
        ),
        MARKETING,
    )


def test_an_income_exactly_on_the_tier_scores_the_channel_minimum_and_books():
    """7500000 cents earns 25 points and the resulting 70 clears a minimum of 70.

    The PRD states: "Income is tiered: a household income of at least 15000000
    cents (150,000 dollars) earns 45 points, at least 10000000 cents earns 35, at
    least 7500000 cents earns 25, at least 5000000 cents earns 15, and anything
    below that earns 0."

    Design: Difficulty/boundary_precision_check/qualification_score_at_channel_minimum_inclusive
    """
    scene = _strict_channel_with_three_households()

    booking = validate_success(_book_for(scene, "on_tier"), 201)
    assert booking["qualification_score"] == 70
    assert booking["qualification_penalty_points"] == 0
    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 1


def test_one_cent_below_the_tier_scores_sixty_and_one_year_below_the_age_never_scores():
    """The two refusals are different rules: the score gate and the hard minimum.

    The PRD states: "If the resulting `qualification_score` is below the channel's
    `min_qualification_score`, the booking is rejected with
    `ERR_PROSPECT_NOT_QUALIFIED`."

    Design: Difficulty/boundary_precision_check/qualification_score_at_channel_minimum_inclusive
    """
    scene = _strict_channel_with_three_households()

    validate_error(
        _book_for(scene, "one_cent_below_tier"),
        ApiErrorId.ERR_PROSPECT_NOT_QUALIFIED.value,
        422,
    )
    validate_error(
        _book_for(scene, "one_year_too_young"),
        ApiErrorId.ERR_PROSPECT_BELOW_MINIMUM_CRITERIA.value,
        422,
    )

    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 0
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 0
