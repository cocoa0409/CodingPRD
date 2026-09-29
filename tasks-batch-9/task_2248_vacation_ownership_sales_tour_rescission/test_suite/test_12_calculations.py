"""Declared arithmetic: tier constants, pinned orders, clamps and empty branches."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_agreement_financials_chain,
    assert_compliance_score_expression,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
TOUR_DAY_UTC = "2026-08-16T07:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
AFTERNOON_UTC = "2026-08-14T12:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
UNDERWRITER = TEST_USERS["contract_admin_underwriter_headers"]


# ---------------------------------------------------------------------------
# Qualification scoring
# ---------------------------------------------------------------------------


def test_the_affinity_bonus_is_earned_by_the_channel_code_and_then_capped():
    """One household scores 100 on a referral desk and 90 on an off-property desk.

    The PRD states: "And an affinity bonus of 20 points is granted when the
    channel's `channel_code` is either `IN_HOUSE_REFERRAL` or `OWNER_UPGRADE`."

    The PRD states: "The five buckets are summed, then the sum is **capped at 100
    first**, and only then is the no-show penalty subtracted."

    The PRD states: "An `is_existing_owner` household earns 25 points."

    Design: Corner/calculations/qualification_affinity_bonus_and_hundred_point_cap
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    affinity_channel = fx.create_channel(
        name="Owner Referral Desk",
        channel_code="IN_HOUSE_REFERRAL",
        incentive_gift_value_cents=9900,
    )
    plain_channel = fx.create_channel()
    prospect = fx.create_prospect(
        household_name="Bergstrom Household",
        primary_age=45,
        household_income_cents=15_000_000,
        marital_status="MARRIED",
    )

    with_bonus = fx.create_booking(
        affinity_channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc=TOUR_DAY_UTC,
    )
    without_bonus = fx.create_booking(
        plain_channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-16T12:00:00Z",
    )

    assert with_bonus["qualification_score"] == 100
    assert without_bonus["qualification_score"] == 90
    assert with_bonus["qualification_penalty_points"] == 0
    assert without_bonus["qualification_penalty_points"] == 0

    assert fx.read_channel(affinity_channel["id"])["historical_no_show_rate"] == 0.0
    assert fx.read_channel(plain_channel["id"])["historical_no_show_rate"] == 0.0
    assert fx.read_prospect(prospect["id"])["is_existing_owner"] is False


def test_the_four_income_tiers_are_read_at_their_exact_lower_bounds():
    """Four households sitting on the thresholds score 70, 60, 50 and 40.

    The PRD states: "Income is tiered: a household income of at least 15000000
    cents (150,000 dollars) earns 45 points, at least 10000000 cents earns 35, at
    least 7500000 cents earns 25, at least 5000000 cents earns 15, and anything
    below that earns 0."

    The PRD states: "A `primary_age` at or above the channel's `min_age` earns 25
    points, which every prospect that survived phase one necessarily does."

    Design: Corner/calculations/qualification_income_tier_constants_applied
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel(min_qualification_score=15)

    expected = {
        15_000_000: 70,
        10_000_000: 60,
        7_500_000: 50,
        5_000_000: 40,
    }
    for label, (income, score) in zip("ABCD", expected.items()):
        prospect = fx.create_prospect(
            household_name=f"Tier {label} Household",
            primary_age=45,
            household_income_cents=income,
            marital_status="SINGLE",
        )
        booking = fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=TOUR_DAY_UTC,
        )
        assert booking["qualification_score"] == score
        assert booking["qualification_penalty_points"] == 0

    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 4
    assert fx.read_channel(channel["id"])["booked_count"] == 4


# ---------------------------------------------------------------------------
# The gift ledger and the no-show ratio
# ---------------------------------------------------------------------------


def test_the_gift_ledger_holds_its_total_when_a_tour_becomes_toured():
    """Two gifted tours sum to 25000 while a third scheduled tour adds nothing.

    The PRD states: "A channel's `gift_liability_cents` is recomputed as the sum of
    `gift_value_cents` over that channel's bookings that have `gift_issued` set to
    true and whose `status` is `CHECKED_IN` or `TOURED`; bookings in `CANCELLED`,
    `NO_SHOW`, `SCHEDULED` and `RESCHEDULE_PENDING` contribute nothing."

    The PRD states: "When it is false, `gift_issued` stays false and
    `gift_value_cents` stays 0, and the channel's liability is untouched."

    Design: Corner/calculations/gift_liability_ledger_counts_only_checked_in_and_toured
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 2)
    channel = fx.create_channel(incentive_gift_value_cents=12500)
    prospect = fx.create_prospect()
    morning = [
        fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=CHECK_IN_UTC,
        )
        for _ in range(2)
    ]
    afternoon = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc=AFTERNOON_UTC,
    )

    fx.pin_clock(CHECK_IN_UTC)
    fx.check_in(morning[0]["id"], True)
    assert fx.read_channel(channel["id"])["gift_liability_cents"] == 12500

    second = fx.check_in(morning[1]["id"], True)
    assert fx.read_channel(channel["id"])["gift_liability_cents"] == 25000

    rep_id = second["assigned_rep_id"]
    presentation = fx.open_presentation(
        morning[1]["id"], rep_id, recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(presentation["id"], rep_id)
    fx.review_presentation(presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(presentation["id"], rep_id)

    assert fx.read_booking(morning[1]["id"])["status"] == "TOURED"
    assert fx.read_channel(channel["id"])["gift_liability_cents"] == 25000

    idle = fx.read_booking(afternoon["id"])
    assert idle["status"] == "SCHEDULED"
    assert idle["gift_issued"] is False
    assert idle["gift_value_cents"] == 0

    assert fx.read_channel(channel["id"])["booked_count"] == 3
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 3


def test_a_cancelled_booking_leaves_the_ratio_on_its_empty_denominator_branch():
    """Neither counter moved, so the rate is 0.0000 and the denominator reads 0.

    The PRD states: "Its denominator is the sum of `toured_count` and
    `no_show_count`; bookings sitting in `SCHEDULED`, `RESCHEDULE_PENDING`,
    `CHECKED_IN` or `CANCELLED` contribute to neither counter and therefore to
    neither side of the ratio."

    The PRD states: "When the denominator is 0 the rate is `0.0000`."

    The PRD states: "Alongside the raw record, the channel exposes a computed
    no-show summary read that echoes `channel_id`, the channel `status`,
    `booked_count`, `toured_count`, `no_show_count`, the `denominator` actually used
    for the ratio, `historical_no_show_rate`, the outstanding `gift_liability_cents`,
    and a `suspend_threshold_met` boolean that is true exactly when `booked_count`
    has reached at least 4 and the rate has reached at least `0.5000`."

    Design: Corner/calculations/channel_no_show_rate_empty_denominator_branch
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(
        rep_count=1, booking_overrides={"scheduled_start_utc": TOUR_DAY_UTC}
    )
    channel_id = scene["channel"]["id"]

    cancelled = fx.cancel_booking(scene["booking"]["id"], "PROSPECT_WITHDREW")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "PROSPECT_WITHDREW"

    channel = fx.read_channel(channel_id)
    assert channel["toured_count"] == 0
    assert channel["no_show_count"] == 0
    assert channel["historical_no_show_rate"] == 0.0
    assert channel["booked_count"] == 1
    assert channel["status"] == "ACTIVE"

    summary = validate_success(api.get_channel_no_show_summary(channel_id, MARKETING))
    assert summary["channel_id"] == channel_id
    assert summary["status"] == "ACTIVE"
    assert summary["booked_count"] == 1
    assert summary["toured_count"] == 0
    assert summary["no_show_count"] == 0
    assert summary["denominator"] == 0
    assert summary["historical_no_show_rate"] == 0.0
    assert summary["gift_liability_cents"] == 0
    assert summary["suspend_threshold_met"] is False

    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 0


# ---------------------------------------------------------------------------
# Compliance arithmetic
# ---------------------------------------------------------------------------


def test_only_acknowledged_required_codes_move_the_disclosure_count():
    """Two appended rows leave the count at 0, and the required code lifts it to 1.

    The PRD states: "Each append stamps `acknowledged_at` from the logical clock and
    computes a `counts_toward_required` flag, which is true only when the code is one
    of the three *required* disclosures — `RESCISSION_RIGHTS`,
    `PUBLIC_OFFERING_STATEMENT_DELIVERY` and `NOT_AN_INVESTMENT` — and
    `acknowledged_by_prospect` is true."

    The PRD states: "After each append, `disclosure_ack_count` is recomputed as the
    number of *distinct* required codes acknowledged with `acknowledged_by_prospect`
    true, and the presentation's `compliance_score` is recomputed."

    The PRD states: "The four legal codes are `RESCISSION_RIGHTS`,
    `PUBLIC_OFFERING_STATEMENT_DELIVERY`, `NOT_AN_INVESTMENT` and
    `MAINTENANCE_FEE_ESCALATION`, and each code may be appended at most once per
    presentation — a repeat is rejected with `ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED`."

    Design: Corner/calculations/disclosure_ack_count_counts_only_acknowledged_required_codes
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]
    rep_headers = fx.make_sales_representative_headers(rep_id)

    optional = fx.acknowledge_disclosure(
        presentation_id,
        rep_id,
        "MAINTENANCE_FEE_ESCALATION",
        recording_timestamp_offset_seconds=60,
    )
    assert optional["counts_toward_required"] is False

    refused = fx.acknowledge_disclosure(
        presentation_id,
        rep_id,
        "RESCISSION_RIGHTS",
        acknowledged_by_prospect=False,
        recording_timestamp_offset_seconds=120,
    )
    assert refused["counts_toward_required"] is False

    presentation = fx.read_presentation(presentation_id)
    assert presentation["disclosure_ack_count"] == 0
    assert presentation["disclosure_status"] == "PENDING"
    assert presentation["compliance_score"] == 70

    repeat = api.create_disclosure_acknowledgment(
        fac.create_disclosure_acknowledgment_payload(
            presentation_id,
            "RESCISSION_RIGHTS",
            acknowledged_by_prospect=True,
            recording_timestamp_offset_seconds=180,
        ),
        rep_headers,
    )
    validate_error(
        repeat, ApiErrorId.ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED.value, 409
    )

    counted = fx.acknowledge_disclosure(
        presentation_id,
        rep_id,
        "PUBLIC_OFFERING_STATEMENT_DELIVERY",
        recording_timestamp_offset_seconds=240,
    )
    assert counted["counts_toward_required"] is True

    presentation = fx.read_presentation(presentation_id)
    assert presentation["disclosure_ack_count"] == 1
    assert presentation["disclosure_status"] == "PARTIAL"
    assert presentation["compliance_score"] == 80
    assert_compliance_score_expression(presentation)

    rows, meta = validate_paginated(
        api.list_presentation_disclosure_acknowledgments(presentation_id, OFFICER_ALPHA)
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3


def test_two_egregious_findings_drive_the_score_to_zero_and_no_further():
    """The raw expression reads negative ten while the stored score reports zero.

    The PRD states: "The compliance score is a single expression: 100, less the
    presentation's `prohibited_claim_points`, less 10 points for each required
    disclosure still unacknowledged (that is, ten times the difference between
    `required_disclosure_count` and `disclosure_ack_count`), floored at 0."

    The PRD states: "The `prohibited_claim_points` total is itself the sum of
    `penalty_points` over every prohibited-claim finding on the presentation, where
    `penalty_points` is derived from the finding's `severity`: a `MINOR` finding
    costs 5 points, a `MAJOR` finding costs 15, and an `EGREGIOUS` finding costs
    40."

    The PRD states: "A `CLEAR` decision — reachable from `UNREVIEWED` and from
    `FLAGGED`, closing the review loop in both directions — additionally requires
    that the presentation's `compliance_score` has reached at least 70 and that no
    finding on it carries `severity` `EGREGIOUS`; failing either condition rejects
    the decision with `ERR_PRESENTATION_NOT_CLEARED`."

    Design: Corner/calculations/compliance_score_floors_at_zero_never_negative
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=2,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    presentation_id = scene["presentation"]["id"]

    first = fx.file_claim_finding(
        presentation_id,
        "EGREGIOUS",
        fx.read_presentation(presentation_id)["version"],
        claim_code="GUARANTEED_APPRECIATION",
        headers=OFFICER_BRAVO,
    )
    assert first["penalty_points"] == 40

    presentation = fx.read_presentation(presentation_id)
    assert presentation["prohibited_claim_points"] == 40
    assert presentation["compliance_score"] == 30

    second = fx.file_claim_finding(
        presentation_id,
        "EGREGIOUS",
        presentation["version"],
        claim_code="RENTAL_INCOME_PROMISE",
        headers=OFFICER_BRAVO,
    )
    assert second["penalty_points"] == 40

    presentation = fx.read_presentation(presentation_id)
    assert presentation["prohibited_claim_points"] == 80
    assert presentation["compliance_score"] == 0
    assert presentation["disclosure_ack_count"] == 0
    assert presentation["disclosure_status"] == "PENDING"
    assert presentation["review_status"] == "FLAGGED"
    assert_compliance_score_expression(presentation)

    refused = api.review_sales_presentation(
        presentation_id, fac.review_payload("CLEAR"), OFFICER_ALPHA
    )
    validate_error(refused, ApiErrorId.ERR_PRESENTATION_NOT_CLEARED.value, 422)


# ---------------------------------------------------------------------------
# Rotation ranking
# ---------------------------------------------------------------------------


def test_the_tour_counter_outranks_the_rotation_position_in_the_ordering():
    """Position 1 wins the tie, and then position 3 wins on the lower tour count.

    The PRD states: "Candidates are then ordered by `tours_taken_count` ascending,
    with `rotation_position` ascending as the first tie-break and `created_at`
    ascending as the second; the randomly minted `id` is never consulted at any
    level of that chain."

    Design: Corner/calculations/rotation_selection_ranks_tours_taken_before_rotation_position
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    later_position = fx.create_representative(
        gallery["id"],
        full_name="Priya Raman",
        license_number="FL-SL-410079",
        rotation_position=3,
    )
    first_position = fx.create_representative(
        gallery["id"],
        full_name="Dana Reyes",
        license_number="FL-SL-410077",
        rotation_position=1,
    )
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    morning = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )
    afternoon = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=AFTERNOON_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    checked_in = fx.check_in(morning["id"], False)
    assert checked_in["assigned_rep_id"] == first_position["id"]

    presentation = fx.open_presentation(morning["id"], first_position["id"])
    fx.acknowledge_required_disclosures(presentation["id"], first_position["id"])
    fx.review_presentation(presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(presentation["id"], first_position["id"])

    rested = fx.read_representative(first_position["id"])
    assert rested["tours_taken_count"] == 1
    assert rested["status"] == "ACTIVE"

    fx.pin_clock(AFTERNOON_UTC)
    second = fx.check_in(afternoon["id"], False)
    assert second["assigned_rep_id"] == later_position["id"]

    winner = fx.read_representative(later_position["id"])
    assert winner["status"] == "ON_TOUR"
    assert winner["tours_taken_count"] == 0

    posture = fx.read_gallery(gallery["id"])
    assert posture["available_rep_count"] == 2
    assert posture["status"] == "OPEN"


def test_an_on_tour_representative_empties_the_pool_until_the_tour_is_cancelled():
    """The gallery still counts one available rep while the candidate pool is empty.

    The PRD states: "The candidate pool is every representative whose `gallery_id`
    names the booking's gallery, whose `status` is exactly `ACTIVE` — `ON_TOUR`,
    `RETRAINING` and `SUSPENDED` representatives are all excluded — and who survives
    a calendar-exclusivity test."

    The PRD states: "If the pool is empty, check-in is rejected with
    `ERR_NO_ELIGIBLE_REPRESENTATIVE`."

    The PRD states: "A cancellation from `CHECKED_IN` additionally returns the
    assigned representative `ON_TOUR → ACTIVE` and recomputes the channel's
    `gift_liability_cents`, which reverses the check-in accrual exactly because
    `CANCELLED` is not an accruing status."

    Design: Corner/calculations/rotation_selection_excludes_on_tour_representatives_empty_pool
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    morning = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )
    afternoon = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=AFTERNOON_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    fx.check_in(morning["id"], False)
    assert fx.read_representative(representative["id"])["status"] == "ON_TOUR"
    posture = fx.read_gallery(gallery["id"])
    assert posture["available_rep_count"] == 1
    assert posture["status"] == "OPEN"

    fx.pin_clock(AFTERNOON_UTC)
    refused = api.check_in_tour_booking(
        afternoon["id"], fac.check_in_payload(False), GALLERY
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_REPRESENTATIVE.value, 409)

    released = fx.cancel_booking(morning["id"], "PROSPECT_LEFT_EARLY")
    assert released["status"] == "CANCELLED"
    freed = fx.read_representative(representative["id"])
    assert freed["status"] == "ACTIVE"
    assert freed["tours_taken_count"] == 0

    admitted = validate_success(
        api.check_in_tour_booking(afternoon["id"], fac.check_in_payload(False), GALLERY)
    )
    assert admitted["status"] == "CHECKED_IN"
    assert admitted["assigned_rep_id"] == representative["id"]

    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 1


# ---------------------------------------------------------------------------
# Underwriting arithmetic
# ---------------------------------------------------------------------------


def test_the_underwritable_floor_is_inclusive_and_the_lowest_tier_caps_the_loan():
    """Six-nineteen has no approve branch while six-twenty prices at 1699 and 0.80.

    The PRD states: "An `APPROVE` decision is unavailable when `applicant_fico` is
    below 620 — that request is rejected with `ERR_INVALID_REQUEST` — and is also
    refused when the agreement's `rescission_status` is `RESCINDED`, which yields
    `ERR_INVALID_AGREEMENT_STATE`."

    The PRD states: "Submission supersedes: every prior application on the same
    agreement sitting in `SUBMITTED` or `APPROVED` moves to `WITHDRAWN`, processed in
    `created_at` ascending order, with its computed underwriting fields left exactly
    as they were."

    The PRD states: "The `SUBMITTED → APPROVED` branch prices the loan from a FICO
    tier: a score of at least 740 sets `apr_bps` to 1099 and `max_ltv_rate` to 0.95;
    at least 680 sets 1399 and 0.90; at least 620 sets 1699 and 0.80."

    The PRD states: "`ltv_cap_cents` is the sum of the agreement's `total_due_cents`
    and `closing_cost_fee_cents`, multiplied by `max_ltv_rate`, rounded half-up to a
    whole cent."

    The PRD states: "`approved_amount_cents` is the smaller of
    `requested_amount_cents` and `ltv_cap_cents`."

    The PRD states: "The monthly payment is a standard amortisation: the monthly rate
    is `apr_bps` divided by 10000 and then divided by 12, held as an exact rational
    value with no intermediate rounding; `monthly_payment_cents` is
    `approved_amount_cents` multiplied by that monthly rate, divided by the quantity
    obtained by subtracting from one the value of one plus the monthly rate raised to
    the power of the negative of `term_months`, with a single half-up rounding to a
    whole cent applied once to that final quotient."

    Design: Corner/calculations/financing_underwriting_lowest_fico_tier_and_below_minimum
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
        agreement_overrides={
            "product_type": "DEEDED_INTEREST",
            "state_code": "FL",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]
    rep_id = scene["assigned_rep_id"]
    assert agreement["total_due_cents"] == 3_200_000
    assert agreement["closing_cost_fee_cents"] == 139_980
    assert agreement["financed_amount_cents"] == 3_019_980

    below_floor = fx.submit_financing(
        agreement["id"],
        rep_id,
        fx.read_agreement(agreement["id"])["version"],
        requested_amount_cents=3_019_980,
        applicant_fico=619,
        term_months=120,
    )
    assert below_floor["status"] == "SUBMITTED"

    refused = api.decide_financing_application(
        below_floor["id"], fac.financing_decision_payload("APPROVE"), UNDERWRITER
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    untouched = fx.read_financing_application(below_floor["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["apr_bps"] is None
    assert untouched["decided_at"] is None

    at_floor = fx.submit_financing(
        agreement["id"],
        rep_id,
        fx.read_agreement(agreement["id"])["version"],
        requested_amount_cents=3_019_980,
        applicant_fico=620,
        term_months=120,
    )
    assert fx.read_financing_application(below_floor["id"])["status"] == "WITHDRAWN"

    approved = fx.decide_financing(at_floor["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["apr_bps"] == 1699
    assert approved["max_ltv_rate"] == 0.80
    assert approved["ltv_cap_cents"] == 2_671_984
    assert approved["approved_amount_cents"] == 2_671_984
    assert approved["monthly_payment_cents"] == 46422


# ---------------------------------------------------------------------------
# Rescission window arithmetic
# ---------------------------------------------------------------------------


def test_a_nevada_sale_anchors_on_execution_and_never_rolls_its_deadline():
    """The statement delivered four days earlier is validated and then ignored.

    The PRD states: "Each agreement's `state_code` selects one row of the following
    fixed rule table, and that row's values are frozen onto the agreement at
    execution as `statutory_rescission_days`, `anchor_mode` and `refund_policy`:"

    The PRD states: "The anchor instant, recorded as `rescission_anchor_utc`, is
    chosen by `anchor_mode`: under `EXECUTION` it is the agreement's `executed_at`;
    under `POS_DELIVERY` it is the agreement's `pos_delivered_at`; under
    `LATER_OF_EXECUTION_OR_POS` it is whichever of those two instants is later."

    The PRD states: "For jurisdictions whose row permits rolling, the resulting date
    is advanced one day at a time for as long as it falls on a Saturday, falls on a
    Sunday, or matches a date in the federal-holiday calendar below, and
    `business_day_rolled` is set to true if at least one such advance occurred; for
    jurisdictions whose row does not permit rolling, no advance happens and
    `business_day_rolled` stays false."

    The PRD states: "A dedicated computed read explains the window without
    recomputing it, echoing `agreement_id`, `state_code`, `anchor_mode`, the
    `anchor_utc` instant that was selected, `statutory_days`, `business_day_rolled`,
    `rescission_deadline_utc`, the current `rescission_status`, the current
    `clock_now`, and an `is_open_now` boolean that is true exactly when
    `rescission_status` is `OPEN` and the logical clock is at or before the
    deadline."

    Design: Corner/calculations/rescission_deadline_nevada_execution_anchor_variant_selected
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        gallery_overrides={
            "name": "Las Vegas Sales Gallery",
            "site_code": "LVSGAL",
        },
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
        agreement_overrides={
            "product_type": "DEEDED_INTEREST",
            "state_code": "NV",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]

    assert agreement["anchor_mode"] == "EXECUTION"
    assert agreement["statutory_rescission_days"] == 5
    assert agreement["refund_policy"] == "STATUTORY_FULL"
    assert_instant_equals(
        agreement["rescission_anchor_utc"], EXECUTION_UTC, "rescission_anchor_utc"
    )
    assert_instant_equals(
        agreement["rescission_deadline_utc"],
        "2026-08-19T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert agreement["business_day_rolled"] is False

    inside = validate_success(api.get_rescission_window(agreement["id"], INTAKE))
    assert inside["state_code"] == "NV"
    assert inside["anchor_mode"] == "EXECUTION"
    assert inside["statutory_days"] == 5
    assert inside["business_day_rolled"] is False
    assert_instant_equals(inside["anchor_utc"], EXECUTION_UTC, "anchor_utc")
    assert_instant_equals(inside["clock_now"], EXECUTION_UTC, "clock_now")
    assert inside["rescission_status"] == "OPEN"
    assert inside["is_open_now"] is True

    fx.pin_clock("2026-08-20T00:00:00Z")
    outside = validate_success(api.get_rescission_window(agreement["id"], INTAKE))
    assert_instant_equals(
        outside["rescission_deadline_utc"],
        "2026-08-19T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert outside["is_open_now"] is False

    sweep = fx.sweep_rescissions()
    assert sweep["swept_count"] == 1
    assert sweep["expired_agreement_ids"] == [agreement["id"]]
    assert fx.read_agreement(agreement["id"])["rescission_status"] == "EXPIRED"


def test_the_roll_loop_steps_past_a_saturday_and_past_a_federal_holiday():
    """One deadline advances two days off a Saturday, the other one day off a holiday.

    The PRD states: "For jurisdictions whose row permits rolling, the resulting date
    is advanced one day at a time for as long as it falls on a Saturday, falls on a
    Sunday, or matches a date in the federal-holiday calendar below, and
    `business_day_rolled` is set to true if at least one such advance occurred; for
    jurisdictions whose row does not permit rolling, no advance happens and
    `business_day_rolled` stays false."

    The PRD states: "The federal-holiday calendar is fixed: 2026-07-03, 2026-09-07,
    2026-11-26, 2026-12-25, 2027-01-01, 2028-07-04, 2028-09-04, 2028-11-23,
    2028-12-25, 2029-01-01, 2029-07-04, 2029-09-03, 2029-11-22, 2029-12-25."

    The PRD states: "`rescission_deadline_utc` is that final date at
    `23:59:59.999Z`."

    Design: Corner/calculations/rescission_deadline_weekend_and_federal_holiday_roll
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    august = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-12T07:00:00Z",
    )
    september = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-31T07:00:00Z",
    )
    rep_id = representative["id"]

    fx.pin_clock("2026-08-12T07:00:00Z")
    fx.check_in(august["id"], False)
    first = fx.open_presentation(august["id"], rep_id)
    fx.acknowledge_required_disclosures(first["id"], rep_id)
    fx.review_presentation(first["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(first["id"], rep_id)

    fx.pin_clock("2026-08-12T09:00:00Z")
    florida = fx.execute_agreement(
        first["id"],
        rep_id,
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at="2026-08-10T10:00:00Z",
    )
    assert florida["statutory_rescission_days"] == 10
    assert florida["anchor_mode"] == "LATER_OF_EXECUTION_OR_POS"
    assert_instant_equals(
        florida["rescission_anchor_utc"],
        "2026-08-12T09:00:00Z",
        "rescission_anchor_utc",
    )
    assert_instant_equals(
        florida["rescission_deadline_utc"],
        "2026-08-24T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert florida["business_day_rolled"] is True

    fx.pin_clock("2026-08-31T07:00:00Z")
    fx.check_in(september["id"], False)
    second = fx.open_presentation(
        september["id"], rep_id, recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(second["id"], rep_id)
    fx.review_presentation(second["id"], "CLEAR", OFFICER_ALPHA)

    fx.pin_clock("2026-08-31T09:00:00Z")
    california = fx.execute_agreement(
        second["id"],
        rep_id,
        state_code="CA",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at="2026-08-28T10:00:00Z",
    )
    assert california["statutory_rescission_days"] == 7
    assert california["anchor_mode"] == "LATER_OF_EXECUTION_OR_POS"
    assert california["refund_policy"] == "STATUTORY_FULL"
    assert_instant_equals(
        california["rescission_anchor_utc"],
        "2026-08-31T09:00:00Z",
        "rescission_anchor_utc",
    )
    assert_instant_equals(
        california["rescission_deadline_utc"],
        "2026-09-08T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert california["business_day_rolled"] is True


# ---------------------------------------------------------------------------
# Contract financials
# ---------------------------------------------------------------------------


def test_the_down_payment_tiers_are_inclusive_at_their_top_and_bottom_edges():
    """A five-million total demands twelve percent; a cent below two million wants eight.

    The PRD states: "The required down payment is tiered on that total: a
    `total_due_cents` of at least 5000000 requires 12 percent, at least 2000000
    requires 10 percent, and anything below that requires 8 percent."

    The PRD states: "`down_payment_required_cents` is the total multiplied by the
    applicable rate, rounded half-up to a whole cent."

    The PRD states: "If the submitted `down_payment_cents` is below that
    requirement, the execution is rejected with `ERR_DOWN_PAYMENT_INSUFFICIENT`."

    The PRD states: "Otherwise `doc_stamp_cents` is `base_financed_cents` multiplied
    by a documentary stamp rate of 0.0035, rounded half-up to a whole cent, and
    `closing_cost_fee_cents` is a flat 129900 cents plus that stamp."

    Design: Corner/calculations/agreement_financials_top_and_bottom_down_payment_tiers
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    august = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-12T07:00:00Z",
    )
    september = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-31T07:00:00Z",
    )
    rep_id = representative["id"]
    rep_headers = fx.make_sales_representative_headers(rep_id)

    fx.pin_clock("2026-08-12T07:00:00Z")
    fx.check_in(august["id"], False)
    first = fx.open_presentation(august["id"], rep_id)
    fx.acknowledge_required_disclosures(first["id"], rep_id)
    fx.review_presentation(first["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(first["id"], rep_id)

    fx.pin_clock("2026-08-12T09:00:00Z")
    short_by_one = api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            first["id"],
            purchase_price_cents=5_000_000,
            down_payment_cents=599_999,
            pos_delivered_at="2026-08-10T10:00:00Z",
        ),
        rep_headers,
    )
    validate_error(
        short_by_one, ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT.value, 422
    )

    top_tier = fx.execute_agreement(
        first["id"],
        rep_id,
        purchase_price_cents=5_000_000,
        down_payment_cents=600_000,
        pos_delivered_at="2026-08-10T10:00:00Z",
    )
    assert top_tier["total_due_cents"] == 5_000_000
    assert top_tier["down_payment_required_cents"] == 600_000
    assert top_tier["base_financed_cents"] == 4_400_000
    assert top_tier["doc_stamp_cents"] == 15_400
    assert top_tier["closing_cost_fee_cents"] == 145_300
    assert top_tier["financed_amount_cents"] == 4_545_300
    assert top_tier["escrow_collected_cents"] == 600_000
    assert_agreement_financials_chain(top_tier)

    fx.pin_clock("2026-08-31T07:00:00Z")
    fx.check_in(september["id"], False)
    second = fx.open_presentation(
        september["id"], rep_id, recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(second["id"], rep_id)
    fx.review_presentation(second["id"], "CLEAR", OFFICER_ALPHA)

    fx.pin_clock("2026-08-31T09:00:00Z")
    also_short = api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            second["id"],
            purchase_price_cents=1_999_999,
            down_payment_cents=159_999,
            pos_delivered_at="2026-08-28T10:00:00Z",
        ),
        rep_headers,
    )
    validate_error(also_short, ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT.value, 422)

    bottom_tier = fx.execute_agreement(
        second["id"],
        rep_id,
        purchase_price_cents=1_999_999,
        down_payment_cents=160_000,
        pos_delivered_at="2026-08-28T10:00:00Z",
    )
    assert bottom_tier["down_payment_required_cents"] == 160_000
    assert bottom_tier["base_financed_cents"] == 1_839_999
    assert bottom_tier["doc_stamp_cents"] == 6_440
    assert bottom_tier["closing_cost_fee_cents"] == 136_340
    assert bottom_tier["financed_amount_cents"] == 1_976_339
    assert_agreement_financials_chain(bottom_tier)
