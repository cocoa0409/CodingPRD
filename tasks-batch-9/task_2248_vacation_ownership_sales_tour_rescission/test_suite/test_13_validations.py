"""Declared refusals: uniqueness scopes, ordered gates and re-read postures."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
AFTERNOON_UTC = "2026-08-14T12:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"
FUNDING_UTC = "2026-08-25T00:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]


# ---------------------------------------------------------------------------
# Uniqueness scopes
# ---------------------------------------------------------------------------


def test_the_channel_code_is_claimed_globally_while_the_name_is_not():
    """A repeated code is refused, a repeated name is created, and nothing is rewritten.

    The PRD states: "The channel classification `channel_code` is one of
    `OFF_PROPERTY_CONTACT`, `IN_HOUSE_REFERRAL`, `MINI_VAC_PACKAGE`, `TELEMARKETING`
    or `OWNER_UPGRADE`, and it must be globally unique — a second channel claiming a
    code already in use is rejected with `ERR_CHANNEL_CODE_TAKEN`."

    The PRD states: "An optional `requires_married_household` flag defaults to false;
    when it is set, only married households may be booked on the channel."

    The PRD states: "`version` (integer): an integer that starts at 1 and increments
    by one on every mutation of the record."

    Design: Corner/validations/channel_code_global_uniqueness_conflict
    """
    fx.pin_clock(CLOCK_START)
    original = fx.create_channel()

    duplicate_code = api.create_tour_channel(
        fac.create_tour_channel_payload(
            name="Boardwalk Kiosk Team",
            channel_code="OFF_PROPERTY_CONTACT",
            incentive_gift_value_cents=9900,
            min_age=25,
            min_household_income_cents=4_000_000,
            min_qualification_score=40,
        ),
        MARKETING,
    )
    validate_error(duplicate_code, ApiErrorId.ERR_CHANNEL_CODE_TAKEN.value, 409)

    duplicate_name = validate_success(
        api.create_tour_channel(
            fac.create_tour_channel_payload(
                name="Off-Property Contact",
                channel_code="MINI_VAC_PACKAGE",
                incentive_gift_value_cents=19900,
            ),
            MARKETING,
        ),
        201,
    )
    assert duplicate_name["channel_code"] == "MINI_VAC_PACKAGE"
    assert duplicate_name["name"] == original["name"]

    untouched = fx.read_channel(original["id"])
    assert untouched["incentive_gift_value_cents"] == 12500
    assert untouched["min_age"] == 30
    assert untouched["min_qualification_score"] == 55
    assert untouched["version"] == 1
    assert untouched["status"] == "ACTIVE"
    assert untouched["requires_married_household"] is False


def test_the_rotation_position_is_claimed_only_inside_its_own_gallery():
    """Position one collides in Orlando and is free in Las Vegas.

    The PRD states: "Representatives are added to a gallery's rotation by a
    `GalleryManager`, who supplies the `gallery_id` of the hosting gallery, a
    `full_name` of 1 to 120 characters, a `license_number` of 4 to 32 characters that
    is globally unique, and a `rotation_position` ordinal from 1 through 99 inclusive
    that must be unique within that gallery — a collision is rejected with
    `ERR_ROTATION_POSITION_TAKEN`."

    The PRD states: "A new representative starts in `status` `ACTIVE`, with
    `tours_taken_count`, `executed_agreement_count`, `rescinded_agreement_count` and
    `compliance_strike_count` at 0, `cancellation_rate` at `0.0000`, and
    `last_assigned_at` null until their first check-in assignment."

    Design: Corner/validations/rotation_position_uniqueness_scoped_to_one_gallery
    """
    fx.pin_clock(CLOCK_START)
    orlando = fx.create_gallery()
    las_vegas = fx.create_gallery(
        name="Las Vegas Sales Gallery", site_code="LVSGAL"
    )

    incumbent = fx.create_representative(orlando["id"])

    collision = api.create_sales_representative(
        fac.create_sales_representative_payload(
            orlando["id"],
            full_name="Marco Iyer",
            license_number="FL-SL-410078",
            rotation_position=1,
        ),
        GALLERY,
    )
    validate_error(collision, ApiErrorId.ERR_ROTATION_POSITION_TAKEN.value, 409)

    elsewhere = fx.create_representative(
        las_vegas["id"],
        full_name="Priya Raman",
        license_number="NV-SL-810079",
        rotation_position=1,
    )
    assert elsewhere["rotation_position"] == 1
    assert elsewhere["gallery_id"] == las_vegas["id"]

    rows, meta = validate_paginated(
        api.list_sales_representatives(GALLERY, params={"gallery_id": orlando["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [incumbent["id"]]

    stored = fx.read_representative(incumbent["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["tours_taken_count"] == 0
    assert stored["executed_agreement_count"] == 0
    assert stored["rescinded_agreement_count"] == 0
    assert stored["compliance_strike_count"] == 0
    assert stored["cancellation_rate"] == 0.0
    assert stored["last_assigned_at"] is None


# ---------------------------------------------------------------------------
# Ordered qualification gates
# ---------------------------------------------------------------------------


def test_the_hard_minimums_answer_before_the_scored_threshold_does():
    """A rich single household fails the married floor before its score of 70 is read.

    The PRD states: "The first phase is three hard minimums, all of which must pass
    before any scoring happens."

    The PRD states: "The prospect's `primary_age` must not be below the channel's
    `min_age`; the prospect's `household_income_cents` must not be below the
    channel's `min_household_income_cents`; and if the channel's
    `requires_married_household` flag is set, the prospect's `marital_status` must be
    `MARRIED`."

    The PRD states: "Any of those three failing rejects the booking with
    `ERR_PROSPECT_BELOW_MINIMUM_CRITERIA`."

    The PRD states: "If the resulting `qualification_score` is below the channel's
    `min_qualification_score`, the booking is rejected with
    `ERR_PROSPECT_NOT_QUALIFIED`."

    Design: Corner/validations/prospect_hard_minimum_criteria_precede_score_threshold
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    open_channel = fx.create_channel()
    couples_channel = fx.create_channel(
        name="Mini-Vac Package",
        channel_code="MINI_VAC_PACKAGE",
        incentive_gift_value_cents=19900,
        requires_married_household=True,
    )

    too_young = fx.create_prospect(
        household_name="Nolan Household",
        primary_age=24,
        household_income_cents=3_000_000,
        marital_status="SINGLE",
    )
    modest = fx.create_prospect(
        household_name="Whitfield Household",
        primary_age=45,
        household_income_cents=6_000_000,
        marital_status="SINGLE",
    )
    wealthy_single = fx.create_prospect(
        household_name="Okafor Household",
        primary_age=45,
        household_income_cents=15_000_000,
        marital_status="SINGLE",
    )
    qualifying = fx.create_prospect()

    def book(channel_id, prospect_id):
        return api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel_id,
                prospect_id,
                gallery["id"],
                scheduled_start_utc=CHECK_IN_UTC,
            ),
            MARKETING,
        )

    validate_error(
        book(open_channel["id"], too_young["id"]),
        ApiErrorId.ERR_PROSPECT_BELOW_MINIMUM_CRITERIA.value,
        422,
    )
    validate_error(
        book(couples_channel["id"], wealthy_single["id"]),
        ApiErrorId.ERR_PROSPECT_BELOW_MINIMUM_CRITERIA.value,
        422,
    )
    validate_error(
        book(open_channel["id"], modest["id"]),
        ApiErrorId.ERR_PROSPECT_NOT_QUALIFIED.value,
        422,
    )

    accepted = validate_success(book(open_channel["id"], qualifying["id"]), 201)
    assert accepted["qualification_score"] == 80
    assert accepted["qualification_penalty_points"] == 0

    rows, meta = validate_paginated(
        api.list_tour_bookings(MARKETING, params={"gallery_id": gallery["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 1


def test_the_sixty_minute_lead_time_is_inclusive_and_reapplies_on_the_commit():
    """One second short is refused, the exact hour is admitted, and the commit re-checks.

    The PRD states: "The requested start must be at least 60 minutes — one full hour
    — after the logical clock, otherwise the request is rejected with
    `ERR_TOUR_SLOT_IN_PAST`."

    The PRD states: "That leg re-checks everything the original booking checked —
    gallery `OPEN`, channel `ACTIVE`, the 60-minute lead time, and the capacity
    overlap test against the new interval with this booking itself excluded from the
    occupying set — then replaces `scheduled_start_utc`, recomputes
    `scheduled_end_utc` from the gallery's presentation length, and increments
    `reschedule_count` by one."

    Design: Corner/validations/booking_lead_time_sixty_minute_inclusive_temporal_gate
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    channel = fx.create_channel()
    prospect = fx.create_prospect()

    def book(start):
        return api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=start
            ),
            MARKETING,
        )

    validate_error(
        book("2026-07-31T23:00:00Z"), ApiErrorId.ERR_TOUR_SLOT_IN_PAST.value, 422
    )
    validate_error(
        book("2026-08-01T00:59:59Z"), ApiErrorId.ERR_TOUR_SLOT_IN_PAST.value, 422
    )

    booking = validate_success(book("2026-08-01T01:00:00Z"), 201)
    assert_instant_equals(
        booking["scheduled_start_utc"], "2026-08-01T01:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        booking["scheduled_end_utc"], "2026-08-01T03:00:00Z", "scheduled_end_utc"
    )

    pending = validate_success(
        api.open_reschedule_request(
            booking["id"],
            fac.reschedule_request_payload("prospect asked for a later slot"),
            MARKETING,
        )
    )
    assert pending["status"] == "RESCHEDULE_PENDING"

    too_soon = api.commit_reschedule(
        booking["id"],
        fac.reschedule_commit_payload("2026-08-01T00:30:00Z"),
        MARKETING,
    )
    validate_error(too_soon, ApiErrorId.ERR_TOUR_SLOT_IN_PAST.value, 422)

    unchanged = fx.read_booking(booking["id"])
    assert unchanged["status"] == "RESCHEDULE_PENDING"
    assert unchanged["reschedule_count"] == 0
    assert_instant_equals(
        unchanged["scheduled_start_utc"], "2026-08-01T01:00:00Z", "scheduled_start_utc"
    )


# ---------------------------------------------------------------------------
# Execution and funding gates
# ---------------------------------------------------------------------------


def test_the_statement_window_is_measured_from_the_execution_instant():
    """Thirty-one days early is refused while two days late is accepted and anchors.

    The PRD states: "The public offering statement must have been delivered inside a
    bounded window around signing: `pos_delivered_at` must be no earlier than 30 days
    before `executed_at` and no later than 3 days after `executed_at`."

    The PRD states: "A delivery instant outside that window is rejected with
    `ERR_POS_NOT_DELIVERED`."

    The PRD states: "The anchor instant, recorded as `rescission_anchor_utc`, is
    chosen by `anchor_mode`: under `EXECUTION` it is the agreement's `executed_at`;
    under `POS_DELIVERY` it is the agreement's `pos_delivered_at`; under
    `LATER_OF_EXECUTION_OR_POS` it is whichever of those two instants is later."

    Design: Corner/validations/pos_delivery_window_conditional_on_execution_instant
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_cleared_presentation(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        review_headers=OFFICER_ALPHA,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    presentation_id = scene["presentation"]["id"]
    rep_headers = fx.make_sales_representative_headers(scene["assigned_rep_id"])

    fx.pin_clock(EXECUTION_UTC)
    stale_statement = api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            presentation_id,
            state_code="FL",
            purchase_price_cents=3_200_000,
            down_payment_cents=320_000,
            pos_delivered_at="2026-07-14T09:00:00Z",
        ),
        rep_headers,
    )
    validate_error(stale_statement, ApiErrorId.ERR_POS_NOT_DELIVERED.value, 422)

    agreement = fx.execute_agreement(
        presentation_id,
        scene["assigned_rep_id"],
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at="2026-08-16T10:00:00Z",
    )
    assert_instant_equals(agreement["executed_at"], EXECUTION_UTC, "executed_at")
    assert_instant_equals(
        agreement["pos_delivered_at"], "2026-08-16T10:00:00Z", "pos_delivered_at"
    )
    assert agreement["anchor_mode"] == "LATER_OF_EXECUTION_OR_POS"
    assert_instant_equals(
        agreement["rescission_anchor_utc"],
        "2026-08-16T10:00:00Z",
        "rescission_anchor_utc",
    )
    assert_instant_equals(
        agreement["rescission_deadline_utc"],
        "2026-08-26T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert agreement["business_day_rolled"] is False

    rows, meta = validate_paginated(
        api.list_purchase_agreements(INTAKE, params={"presentation_id": presentation_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [agreement["id"]]


def test_funding_waits_for_an_approval_that_covers_the_financed_amount():
    """A capped approval of 3005982 refuses the 3019980 draw until a richer one lands.

    The PRD states: "When the agreement's `financed_amount_cents` is above 0, an
    `APPROVED` financing application must exist for it, otherwise
    `ERR_FINANCING_NOT_APPROVED`; and when such an application exists, its
    `approved_amount_cents` must be at least the agreement's `financed_amount_cents`,
    otherwise `ERR_FINANCING_AMOUNT_SHORTFALL`."

    The PRD states: "A worked figure: a `total_due_cents` of 3200000 with
    `closing_cost_fee_cents` of 139980, a score of 760, a requested amount of 3019980
    and a 120-month term gives an `ltv_cap_cents` of 3172981, an
    `approved_amount_cents` of 3019980 and a `monthly_payment_cents` of 41583; the
    identical request at a score of 700 gives an `ltv_cap_cents` of 3005982 and an
    `approved_amount_cents` of 3005982, which falls short of a
    `financed_amount_cents` of 3019980."

    The PRD states: "It also creates the closing package for the agreement in
    `status` `AWAITING_RECORDING`, deriving `instrument_type` as `DEED` when the
    agreement's `product_type` is `DEEDED_INTEREST` and as `RTU_CERTIFICATE` when it
    is `RIGHT_TO_USE`, with `recording_jurisdiction`, `recording_reference`,
    `recorded_at`, `delivery_method` and `documents_delivered_at` all null."

    Design: Corner/validations/financing_shortfall_refuses_funding_until_full_approval
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
        agreement_overrides={
            "state_code": "FL",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]
    rep_id = scene["assigned_rep_id"]
    assert agreement["financed_amount_cents"] == 3_019_980

    capped = fx.submit_financing(
        agreement["id"],
        rep_id,
        fx.read_agreement(agreement["id"])["version"],
        requested_amount_cents=3_019_980,
        applicant_fico=700,
        term_months=120,
    )
    capped = fx.decide_financing(capped["id"], "APPROVE")
    assert capped["apr_bps"] == 1399
    assert capped["max_ltv_rate"] == 0.90
    assert capped["ltv_cap_cents"] == 3_005_982
    assert capped["approved_amount_cents"] == 3_005_982

    fx.pin_clock(FUNDING_UTC)
    fx.sweep_rescissions()
    assert fx.read_agreement(agreement["id"])["rescission_status"] == "EXPIRED"

    short = api.fund_purchase_agreement(
        agreement["id"], fac.fund_payload(3_019_980), FUNDER
    )
    validate_error(short, ApiErrorId.ERR_FINANCING_AMOUNT_SHORTFALL.value, 422)
    assert (
        fx.read_agreement(agreement["id"])["fulfillment_status"] == "AWAITING_FUNDING"
    )

    sufficient = fx.submit_financing(
        agreement["id"],
        rep_id,
        fx.read_agreement(agreement["id"])["version"],
        requested_amount_cents=3_019_980,
        applicant_fico=760,
        term_months=120,
    )
    sufficient = fx.decide_financing(sufficient["id"], "APPROVE")
    assert sufficient["apr_bps"] == 1099
    assert sufficient["max_ltv_rate"] == 0.95
    assert sufficient["ltv_cap_cents"] == 3_172_981
    assert sufficient["approved_amount_cents"] == 3_019_980
    assert sufficient["monthly_payment_cents"] == 41583
    assert fx.read_financing_application(capped["id"])["status"] == "WITHDRAWN"

    funded = fx.fund_agreement(agreement["id"], 3_019_980)
    assert funded["fulfillment_status"] == "FUNDED"
    assert funded["funding_reference"] == "WIRE-77120"

    rows, meta = validate_paginated(
        api.list_closing_packages(FUNDER, params={"agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["instrument_type"] == "DEED"
    assert rows[0]["status"] == "AWAITING_RECORDING"


# ---------------------------------------------------------------------------
# Retraining and posture gates
# ---------------------------------------------------------------------------


def test_the_module_count_is_only_compared_on_a_completing_close():
    """Three of four is refused, four exactly passes, and a failing close counts nothing.

    The PRD states: "A `COMPLETE` close requires `modules_completed` to be at least
    `required_module_count`, otherwise it is rejected with
    `ERR_MODULE_COUNT_SHORTFALL`."

    The PRD states: "On success it stamps `closed_at`, records the module count, moves
    the assignment `IN_PROGRESS → COMPLETED`, and then runs a three-step restoration:
    the representative's `compliance_strike_count` is reset to 0 — the only mechanism
    in the system that resets strikes; the representative returns to `ACTIVE`, but
    only when no other assignment for them still sits in `ASSIGNED` or `IN_PROGRESS`;
    and the gallery's `available_rep_count` is recomputed, so a `RESTRICTED` gallery
    whose count has reached at least 1 returns to `OPEN`."

    The PRD states: "A `FAIL` close also stamps `closed_at` and records
    `modules_completed`, but moves the assignment `IN_PROGRESS → FAILED`, leaves the
    representative wherever they are — `RETRAINING` or `SUSPENDED` — and preserves
    their strike count untouched."

    Design: Corner/validations/retraining_module_count_gate_applies_only_to_complete
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    roster = fx.create_representatives(gallery["id"], 2)

    completing = fx.assign_retraining(
        roster[0]["id"],
        fx.read_representative(roster[0]["id"])["version"],
        "DISCLOSURE_GAP",
        required_module_count=4,
    )
    failing = fx.assign_retraining(
        roster[1]["id"],
        fx.read_representative(roster[1]["id"])["version"],
        "DISCLOSURE_GAP",
        required_module_count=4,
    )
    fx.start_retraining(completing["id"])
    fx.start_retraining(failing["id"])

    short = api.close_retraining_assignment(
        completing["id"], fac.close_retraining_payload("COMPLETE", 3), OFFICER_ALPHA
    )
    validate_error(short, ApiErrorId.ERR_MODULE_COUNT_SHORTFALL.value, 422)

    still_open = fx.read_retraining_assignment(completing["id"])
    assert still_open["status"] == "IN_PROGRESS"
    assert still_open["modules_completed"] == 0
    assert still_open["cycle_index"] == 1
    assert still_open["closed_at"] is None

    closed = fx.close_retraining(completing["id"], "COMPLETE", 4)
    assert closed["status"] == "COMPLETED"
    assert closed["modules_completed"] == 4
    assert_instant_equals(closed["closed_at"], CLOCK_START, "closed_at")

    restored = fx.read_representative(roster[0]["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["compliance_strike_count"] == 0

    failed = fx.close_retraining(failing["id"], "FAIL", 0)
    assert failed["status"] == "FAILED"
    assert failed["modules_completed"] == 0
    assert fx.read_representative(roster[1]["id"])["status"] == "RETRAINING"


def test_the_gallery_posture_is_re_read_by_every_call_that_touches_a_booking():
    """A booking made while open waits out RESTRICTED and CLOSED, then checks in.

    The PRD states: "Whenever `available_rep_count` changes, the posture is
    re-derived: an `OPEN` gallery whose count has reached 0 becomes `RESTRICTED`, and
    a `RESTRICTED` gallery whose count has reached at least 1 becomes `OPEN`."

    The PRD states: "Both `RESTRICTED` and `CLOSED` refuse booking creation, check-in
    and reschedule commits with `ERR_GALLERY_NOT_OPEN`."

    The PRD states: "Requesting `OPEN` from `CLOSED` re-derives rather than obeys:
    with at least one available representative the gallery lands on `OPEN`, and with
    no available representatives it lands on `RESTRICTED`."

    The PRD states: "It requires the booking to be `SCHEDULED`, the gallery to be
    `OPEN`, and the channel to be `ACTIVE`."

    Design: Corner/validations/gallery_posture_gate_reevaluated_at_every_downstream_step
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )

    assignment = fx.assign_retraining(
        representative["id"],
        fx.read_representative(representative["id"])["version"],
        "DISCLOSURE_GAP",
    )
    fx.start_retraining(assignment["id"])
    assert fx.read_representative(representative["id"])["status"] == "RETRAINING"

    restricted = fx.read_gallery(gallery["id"])
    assert restricted["available_rep_count"] == 0
    assert restricted["status"] == "RESTRICTED"

    fx.pin_clock(CHECK_IN_UTC)
    while_restricted = api.check_in_tour_booking(
        booking["id"], fac.check_in_payload(True), GALLERY
    )
    validate_error(while_restricted, ApiErrorId.ERR_GALLERY_NOT_OPEN.value, 409)

    closed = fx.set_gallery_status(gallery["id"], "CLOSED")
    assert closed["status"] == "CLOSED"

    while_closed = api.check_in_tour_booking(
        booking["id"], fac.check_in_payload(True), GALLERY
    )
    validate_error(while_closed, ApiErrorId.ERR_GALLERY_NOT_OPEN.value, 409)

    refused_booking = api.create_tour_booking(
        fac.create_tour_booking_payload(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=AFTERNOON_UTC,
        ),
        MARKETING,
    )
    validate_error(refused_booking, ApiErrorId.ERR_GALLERY_NOT_OPEN.value, 409)

    waiting = fx.read_booking(booking["id"])
    assert waiting["status"] == "SCHEDULED"
    assert waiting["checked_in_at"] is None
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 1

    fx.close_retraining(assignment["id"], "COMPLETE", 4)
    assert fx.read_representative(representative["id"])["status"] == "ACTIVE"
    assert fx.read_gallery(gallery["id"])["status"] == "CLOSED"

    reopened = fx.set_gallery_status(gallery["id"], "OPEN")
    assert reopened["status"] == "OPEN"
    assert reopened["available_rep_count"] == 1

    admitted = validate_success(
        api.check_in_tour_booking(booking["id"], fac.check_in_payload(True), GALLERY)
    )
    assert admitted["status"] == "CHECKED_IN"
    assert admitted["assigned_rep_id"] == representative["id"]
    assert_instant_equals(admitted["checked_in_at"], CHECK_IN_UTC, "checked_in_at")
    assert admitted["gift_issued"] is True
    assert admitted["gift_value_cents"] == 12500
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 1
