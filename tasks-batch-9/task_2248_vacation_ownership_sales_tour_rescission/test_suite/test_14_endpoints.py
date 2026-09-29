"""Declared surfaces: round trips, scoped subresources, actions and computed reads."""

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
CLOCK_START_PINNED = "2026-08-01T00:00:00.000Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
SECOND_TOUR_UTC = "2026-08-15T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"
INTAKE_UTC = "2026-08-20T12:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
ADJUDICATOR = TEST_USERS["contract_admin_adjudicator_headers"]
ANY_REP = TEST_USERS["sales_representative_headers"]


def test_a_prospect_round_trips_its_four_fields_inside_the_object_envelope():
    """The read-back carries the submitted quartet, a false owner flag and version 1.

    The PRD states: "A `MarketingManager` registers a prospect household with a
    `household_name` of 1 to 120 characters, a `primary_age` from 18 through 99
    inclusive, a `household_income_cents` figure of at least 0, and a
    `marital_status` of either `MARRIED` or `SINGLE`."

    The PRD states: "The household also carries a computed `is_existing_owner` flag,
    which starts false and becomes true as soon as at least one purchase agreement
    naming that household has a `fulfillment_status` of `FUNDED`, `RECORDED`,
    `DOCS_DELIVERED` or `TRADED_IN`."

    The PRD states: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, fixed when the record is first written."

    The PRD states: "`version` (integer): an integer that starts at 1 and increments
    by one on every mutation of the record."

    The PRD states: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    The PRD states: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/prospect_create_and_read_round_trip
    """
    fx.pin_clock(CLOCK_START)
    created = validate_success(
        api.create_prospect(
            fac.create_prospect_payload(
                household_name="Alvarez Household",
                primary_age=45,
                household_income_cents=10_000_000,
                marital_status="MARRIED",
            ),
            MARKETING,
        ),
        201,
    )
    assert created["id"] is not None

    response = api.get_prospect(created["id"], ANY_REP)
    stored = validate_success(response)
    assert stored["id"] == created["id"]
    assert stored["household_name"] == "Alvarez Household"
    assert stored["primary_age"] == 45
    assert stored["household_income_cents"] == 10_000_000
    assert stored["marital_status"] == "MARRIED"
    assert stored["is_existing_owner"] is False
    assert stored["version"] == 1
    assert stored["created_at"] == CLOCK_START_PINNED
    assert stored["updated_at"] == CLOCK_START_PINNED

    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    for pagination_key in ("limit", "offset", "total_count", "has_more"):
        assert pagination_key not in body["meta"]


def test_the_acknowledgment_projection_never_leaks_a_sibling_presentation():
    """Three rows for the first tour, one for the filter, one for the second tour.

    The PRD states: "The two event collections are additionally readable as
    projections of their presentation: the acknowledgment projection accepts an
    optional `disclosure_code` filter and the finding projection an optional
    `severity` filter, both alongside `limit` and `offset`."

    The PRD states: "Unless a specific endpoint says otherwise, every list is sorted
    by `created_at` in ascending order."

    The PRD states: "A recorded disclosure acknowledgment and a prohibited-claim
    finding each carry only `id` and `created_at`."

    The PRD states: "Neither has an `updated_at` field and neither has a `version`
    field, because neither is ever modified after it is appended."

    The PRD states: "Each append stamps `acknowledged_at` from the logical clock and
    computes a `counts_toward_required` flag, which is true only when the code is one
    of the three *required* disclosures — `RESCISSION_RIGHTS`,
    `PUBLIC_OFFERING_STATEMENT_DELIVERY` and `NOT_AN_INVESTMENT` — and
    `acknowledged_by_prospect` is true."

    Design: Corner/endpoints/presentation_acknowledgment_subresource_is_scoped_and_filterable
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    first_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )
    second_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=SECOND_TOUR_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    fx.check_in(first_booking["id"], issue_incentive_gift=False)
    first = fx.open_presentation(first_booking["id"], representative["id"])
    first_ack = fx.acknowledge_disclosure(
        first["id"], representative["id"], "RESCISSION_RIGHTS"
    )
    fx.acknowledge_disclosure(
        first["id"],
        representative["id"],
        "PUBLIC_OFFERING_STATEMENT_DELIVERY",
        recording_timestamp_offset_seconds=240,
    )
    fx.acknowledge_disclosure(
        first["id"],
        representative["id"],
        "NOT_AN_INVESTMENT",
        recording_timestamp_offset_seconds=360,
    )
    fx.review_presentation(first["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(first["id"], representative["id"])

    fx.pin_clock(SECOND_TOUR_UTC)
    fx.check_in(second_booking["id"], issue_incentive_gift=False)
    second = fx.open_presentation(
        second_booking["id"], representative["id"], recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_disclosure(
        second["id"],
        representative["id"],
        "RESCISSION_RIGHTS",
        recording_timestamp_offset_seconds=90,
    )

    rows, meta = validate_paginated(
        api.list_presentation_disclosure_acknowledgments(first["id"], OFFICER_ALPHA)
    )
    assert meta["total_count"] == 3
    assert rows[0]["id"] == first_ack["id"]
    assert rows[0]["recording_timestamp_offset_seconds"] == 120
    assert rows[0]["counts_toward_required"] is True
    for row in rows:
        assert "id" in row
        assert "created_at" in row
        assert "version" not in row
        assert "updated_at" not in row

    filtered, filtered_meta = validate_paginated(
        api.list_presentation_disclosure_acknowledgments(
            first["id"], OFFICER_ALPHA, params={"disclosure_code": "NOT_AN_INVESTMENT"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["disclosure_code"] == "NOT_AN_INVESTMENT"

    sibling, sibling_meta = validate_paginated(
        api.list_presentation_disclosure_acknowledgments(second["id"], OFFICER_ALPHA)
    )
    assert sibling_meta["total_count"] == 1
    assert sibling[0]["disclosure_code"] == "RESCISSION_RIGHTS"

    reread = fx.read_presentation(second["id"])
    assert reread["disclosure_ack_count"] == 1
    # PRD 3.6: "The dimension advances `PENDING -> PARTIAL` whenever the count is
    # above 0 but still below `required_disclosure_count`."
    assert reread["disclosure_status"] == "PARTIAL"


def test_cancelling_a_scheduled_tour_releases_the_slot_and_closes_the_booking():
    """The reason is recorded, the slot ledger falls to zero, and check-in is refused.

    The PRD states: "Cancellation is reachable from three states and always records
    the supplied `reason` as `cancel_reason`."

    The PRD states: "From `SCHEDULED` and from `RESCHEDULE_PENDING` it simply
    recomputes the gallery's `booked_slot_count`, compensating exactly for the
    occupancy taken at creation."

    The PRD states: "A gallery's `booked_slot_count` is recomputed as the number of
    bookings at that gallery whose `status` is `SCHEDULED`, `RESCHEDULE_PENDING`,
    `CHECKED_IN` or `TOURED`; bookings in `NO_SHOW` and `CANCELLED` are excluded."

    The PRD states: "It requires the booking to be `SCHEDULED`, the gallery to be
    `OPEN`, and the channel to be `ACTIVE`."

    The PRD states: "The target resource is in a state from which the requested
    transition exists — `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_PRESENTATION_STATE`,
    `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_FINANCING_STATE`,
    `ERR_INVALID_RESCISSION_REQUEST_STATE`, `ERR_INVALID_CLOSING_PACKAGE_STATE` or
    `ERR_INVALID_RETRAINING_STATE` (409), on every action endpoint."

    Design: Corner/endpoints/booking_cancel_action_releases_slot_and_closes_the_booking
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )

    before = fx.read_gallery(gallery["id"])
    assert before["booked_slot_count"] == 1
    assert before["available_rep_count"] == 1

    cancelled = validate_success(
        api.cancel_tour_booking(
            booking["id"],
            fac.cancel_booking_payload("prospect withdrew after the confirmation call"),
            MARKETING,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "prospect withdrew after the confirmation call"
    assert cancelled["assigned_rep_id"] is None
    assert cancelled["gift_issued"] is False
    assert cancelled["gift_value_cents"] == 0

    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 0

    fx.pin_clock(CHECK_IN_UTC)
    revival = api.check_in_tour_booking(
        booking["id"], fac.check_in_payload(True), GALLERY
    )
    validate_error(revival, ApiErrorId.ERR_INVALID_BOOKING_STATE.value, 409)
    assert fx.read_booking(booking["id"])["status"] == "CANCELLED"

    untouched_rep = fx.read_representative(representative["id"])
    assert untouched_rep["status"] == "ACTIVE"
    assert untouched_rep["tours_taken_count"] == 0


def test_a_perfect_rate_on_a_sample_of_one_is_reported_but_not_actionable():
    """The analysis read shows 1.0 against a min_sample of 2 and creates no assignment.

    The PRD states: "The window is the closed interval running from 90 days before
    the logical clock through the logical clock itself, with both endpoints inclusive,
    and membership is decided on an agreement's `executed_at`."

    The PRD states: "Retraining is required when the denominator has reached at least
    2 *and* the rate has reached at least `0.5000`."

    The PRD states: "Both guards are inclusive, which is exactly why 1 rescission out
    of exactly 2 in-window agreements — a rate of `0.5000` on a sample of 2 — does
    trigger retraining, while 1 out of 1 — a rate of `1.0000` on a sample of 1 — does
    not."

    The PRD states: "The computed analysis read echoes `representative_id`,
    `window_start_utc`, `window_end_utc`, `executed_count`, `rescinded_count`,
    `cancellation_rate`, the `min_sample` of 2, and the `retraining_required` verdict,
    and it is available only to a `GalleryManager`, a `ComplianceOfficer` and a
    `PlatformAdmin`."

    Design: Corner/endpoints/rescission_analysis_read_at_sample_of_one_is_not_actionable
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
    gallery_id = scene["gallery"]["id"]

    fx.pin_clock(INTAKE_UTC)
    request = fx.intake_rescission(agreement["id"], "HAND_DELIVERED")
    validated = validate_success(
        api.adjudicate_rescission_request(request["id"], ADJUDICATOR)
    )
    assert validated["is_timely"] is True
    assert validated["status"] == "VALIDATED"
    assert fx.read_agreement(agreement["id"])["rescission_status"] == "RESCINDED"

    analysis = validate_success(api.get_rescission_analysis(rep_id, OFFICER_ALPHA))
    assert analysis["representative_id"] == rep_id
    assert_instant_equals(
        analysis["window_start_utc"], "2026-05-22T12:00:00Z", "window_start_utc"
    )
    assert_instant_equals(analysis["window_end_utc"], INTAKE_UTC, "window_end_utc")
    assert analysis["executed_count"] == 1
    assert analysis["rescinded_count"] == 1
    assert analysis["cancellation_rate"] == 1.0
    assert analysis["min_sample"] == 2
    assert analysis["retraining_required"] is False

    rows, meta = validate_paginated(
        api.list_retraining_assignments(OFFICER_ALPHA, params={"rep_id": rep_id})
    )
    assert meta["total_count"] == 0
    assert rows == []

    representative = fx.read_representative(rep_id)
    assert representative["status"] == "ACTIVE"
    assert representative["cancellation_rate"] == 1.0

    gallery = fx.read_gallery(gallery_id)
    assert gallery["status"] == "OPEN"
    assert gallery["available_rep_count"] == 1


def test_the_gift_flag_alone_decides_whether_a_check_in_accrues_liability():
    """The false branch accrues nothing while the true branch copies 12500 exactly.

    The PRD states: "Its single body field is `issue_incentive_gift`, a boolean
    recording whether the prospect walked away with the channel's gift."

    The PRD states: "When `issue_incentive_gift` is true, `gift_issued` is set to
    true, `gift_value_cents` is copied from the channel's
    `incentive_gift_value_cents` as of that instant, and the channel's
    `gift_liability_cents` is recomputed."

    The PRD states: "When it is false, `gift_issued` stays false and
    `gift_value_cents` stays 0, and the channel's liability is untouched."

    The PRD states: "A channel's `gift_liability_cents` is recomputed as the sum of
    `gift_value_cents` over that channel's bookings that have `gift_issued` set to
    true and whose `status` is `CHECKED_IN` or `TOURED`; bookings in `CANCELLED`,
    `NO_SHOW`, `SCHEDULED` and `RESCHEDULE_PENDING` contribute nothing."

    The PRD states: "The candidate pool is every representative whose `gallery_id`
    names the booking's gallery, whose `status` is exactly `ACTIVE` — `ON_TOUR`,
    `RETRAINING` and `SUSPENDED` representatives are all excluded — and who survives
    a calendar-exclusivity test."

    The PRD states: "The gallery's `available_rep_count` does not change, because an
    `ON_TOUR` representative still counts as available inventory."

    Design: Corner/endpoints/check_in_gift_flag_selects_the_liability_branch
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    roster = fx.create_representatives(gallery["id"], 2)
    channel = fx.create_channel()
    first_prospect = fx.create_prospect()
    second_prospect = fx.create_prospect(
        household_name="Bhatt Household",
        primary_age=52,
        household_income_cents=12_000_000,
        marital_status="MARRIED",
    )
    giftless_booking = fx.create_booking(
        channel["id"],
        first_prospect["id"],
        gallery["id"],
        scheduled_start_utc=CHECK_IN_UTC,
    )
    gifted_booking = fx.create_booking(
        channel["id"],
        second_prospect["id"],
        gallery["id"],
        scheduled_start_utc=CHECK_IN_UTC,
    )

    fx.pin_clock(CHECK_IN_UTC)
    giftless = validate_success(
        api.check_in_tour_booking(
            giftless_booking["id"], fac.check_in_payload(False), GALLERY
        )
    )
    assert giftless["status"] == "CHECKED_IN"
    assert giftless["gift_issued"] is False
    assert giftless["gift_value_cents"] == 0
    assert giftless["assigned_rep_id"] == roster[0]["id"]

    quiet_summary = validate_success(
        api.get_channel_no_show_summary(channel["id"], MARKETING)
    )
    assert quiet_summary["gift_liability_cents"] == 0

    gifted = validate_success(
        api.check_in_tour_booking(
            gifted_booking["id"], fac.check_in_payload(True), GALLERY
        )
    )
    assert gifted["gift_issued"] is True
    assert gifted["gift_value_cents"] == 12500
    assert gifted["assigned_rep_id"] == roster[1]["id"]

    accrued_summary = validate_success(
        api.get_channel_no_show_summary(channel["id"], MARKETING)
    )
    assert accrued_summary["gift_liability_cents"] == 12500

    reread = fx.read_gallery(gallery["id"])
    assert reread["booked_slot_count"] == 2
    assert reread["available_rep_count"] == 2
