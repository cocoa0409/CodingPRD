"""Declared shapes: defaults, derived fields, reads, filters and refused inputs."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_append_only_shape,
    assert_instant_equals,
    assert_sales_gallery,
    assert_tour_channel,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
TOUR_DAY_UTC = "2026-08-16T07:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]


def test_a_new_channel_reports_every_declared_field_at_its_opening_value():
    """The counters open at 0 and the rate arrives from the empty-denominator branch.

    The PRD states: "A freshly registered channel opens in `status` `ACTIVE` with
    `booked_count`, `toured_count`, `no_show_count` and `gift_liability_cents` all
    at 0, and `historical_no_show_rate` at `0.0000` — the latter arriving through
    the empty-denominator branch rather than through any division."

    Design: Corner/entities/tour_channel_create_returns_all_declared_fields
    """
    fx.pin_clock(CLOCK_START)

    response = api.create_tour_channel(
        fac.create_tour_channel_payload(requires_married_household=True), MARKETING
    )
    channel = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_tour_channel(channel)
    assert channel["version"] == 1
    assert channel["name"] == "Off-Property Contact"
    assert channel["channel_code"] == "OFF_PROPERTY_CONTACT"
    assert channel["incentive_gift_value_cents"] == 12500
    assert channel["min_age"] == 30
    assert channel["min_household_income_cents"] == 5_000_000
    assert channel["min_qualification_score"] == 55
    assert channel["requires_married_household"] is True
    assert channel["status"] == "ACTIVE"
    assert channel["booked_count"] == 0
    assert channel["toured_count"] == 0
    assert channel["no_show_count"] == 0
    assert channel["historical_no_show_rate"] == 0.0
    assert channel["gift_liability_cents"] == 0
    assert_instant_equals(channel["created_at"], CLOCK_START, "created_at")


def test_the_married_household_flag_defaults_to_false_and_gates_when_set():
    """One single household is bookable on the default channel and refused on the other.

    The PRD states: "An optional `requires_married_household` flag defaults to
    false; when it is set, only married households may be booked on the channel."

    Design: Corner/entities/tour_channel_requires_married_household_default_false
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    prospect = fx.create_prospect(
        household_name="Sorensen Household",
        primary_age=45,
        household_income_cents=15_000_000,
        marital_status="SINGLE",
    )

    open_desk = fx.create_channel(name="Open Desk")
    couples_desk = fx.create_channel(
        name="Couples Only Desk",
        channel_code="TELEMARKETING",
        incentive_gift_value_cents=9500,
        requires_married_household=True,
    )
    assert open_desk["requires_married_household"] is False
    assert couples_desk["requires_married_household"] is True

    accepted = validate_success(
        api.create_tour_booking(
            fac.create_tour_booking_payload(
                open_desk["id"],
                prospect["id"],
                gallery["id"],
                scheduled_start_utc=TOUR_DAY_UTC,
            ),
            MARKETING,
        ),
        201,
    )
    assert accepted["qualification_score"] == 70

    refused = api.create_tour_booking(
        fac.create_tour_booking_payload(
            couples_desk["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc="2026-08-16T10:00:00Z",
        ),
        MARKETING,
    )
    validate_error(refused, ApiErrorId.ERR_PROSPECT_BELOW_MINIMUM_CRITERIA.value, 422)


def test_a_gallery_created_without_a_buffer_allows_back_to_back_tours():
    """With the default buffer of 0 the adjacent 11:00 start is legal and 10:59 is not.

    The PRD states: "A `GalleryManager` creates a sales gallery with a `name` of 1
    to 120 characters, a `site_code` of 3 to 8 uppercase characters that is globally
    unique across galleries, a `concurrent_tour_capacity` from 1 through 20
    inclusive, a `presentation_minutes` length from 30 through 480 inclusive, and an
    optional `buffer_minutes` turnaround from 0 through 120 inclusive that defaults
    to 0."

    Design: Corner/entities/sales_gallery_buffer_minutes_default_zero
    """
    fx.pin_clock(CLOCK_START)
    gallery = validate_success(
        api.create_sales_gallery(
            {
                "name": "Zero Buffer Gallery",
                "site_code": "ZBGAL",
                "concurrent_tour_capacity": 1,
                "presentation_minutes": 120,
            },
            GALLERY,
        ),
        201,
    )
    assert gallery["buffer_minutes"] == 0

    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-16T09:00:00Z",
    )

    def book_at(start):
        return api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=start
            ),
            MARKETING,
        )

    validate_error(
        book_at("2026-08-16T10:59:00Z"),
        ApiErrorId.ERR_GALLERY_CAPACITY_EXCEEDED.value,
        409,
    )

    adjacent = validate_success(book_at("2026-08-16T11:00:00Z"), 201)
    assert_instant_equals(
        adjacent["scheduled_start_utc"], "2026-08-16T11:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        adjacent["scheduled_end_utc"], "2026-08-16T13:00:00Z", "scheduled_end_utc"
    )
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 2


def test_reading_a_gallery_shows_the_version_the_roster_cascade_left_behind():
    """Adding one representative refreshes available_rep_count and lifts version to 2.

    The PRD states: "Every entity touched by a cascade has its `updated_at`
    refreshed and its `version` incremented, exactly as if it had been the direct
    target."

    Design: Corner/entities/sales_gallery_get_returns_stored_entity
    """
    fx.pin_clock(CLOCK_START)
    created = fx.create_gallery()
    assert created["version"] == 1
    fx.create_representatives(created["id"], 1)

    response = api.get_sales_gallery(created["id"], MARKETING)
    gallery = validate_success(response)
    assert response.json()["response_type"] == "object"

    assert_sales_gallery(gallery)
    assert gallery["id"] == created["id"]
    assert gallery["name"] == "Orlando Sales Gallery"
    assert gallery["site_code"] == "ORLGAL"
    assert gallery["concurrent_tour_capacity"] == 4
    assert gallery["presentation_minutes"] == 120
    assert gallery["buffer_minutes"] == 30
    assert gallery["status"] == "OPEN"
    assert gallery["available_rep_count"] == 1
    assert gallery["booked_slot_count"] == 0
    assert gallery["version"] == 2


def test_the_representative_list_pages_within_the_gallery_filter():
    """total_count counts the filtered set of three, and has_more tracks the page.

    The PRD states: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` counts every record
    matching the supplied filters before pagination is applied and `has_more` is
    true exactly when records matching the filters remain beyond the current page."

    Design: Corner/entities/sales_representative_list_filtered_pagination
    """
    fx.pin_clock(CLOCK_START)
    first_gallery = fx.create_gallery()
    second_gallery = fx.create_gallery(
        name="Davenport Sales Gallery", site_code="DAVGAL", concurrent_tour_capacity=2
    )
    roster = fx.create_representatives(first_gallery["id"], 3)
    outsider = fx.create_representative(
        second_gallery["id"],
        full_name="Tom Bexley",
        license_number="FL-SL-410080",
        rotation_position=1,
    )

    first_page, first_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY, params={"gallery_id": first_gallery["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY, params={"gallery_id": first_gallery["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    listed_ids = {row["id"] for row in first_page + second_page}
    assert listed_ids == {rep["id"] for rep in roster}
    assert outsider["id"] not in listed_ids

    suspended, suspended_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY,
            params={"gallery_id": first_gallery["id"], "status": "SUSPENDED"},
        )
    )
    assert suspended == []
    assert suspended_meta["total_count"] == 0
    assert suspended_meta["has_more"] is False


def test_a_well_formed_but_unminted_gallery_id_is_a_not_found():
    """The read resolves the path parameter and reports the gallery-specific code.

    The PRD states: "Existence of path-parameter resources, validated strictly left
    to right, yielding HTTP 404 with the code for the *first* identifier in the path
    that does not resolve: `ERR_CHANNEL_NOT_FOUND`, `ERR_GALLERY_NOT_FOUND`,
    `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_PROSPECT_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_FINANCING_APPLICATION_NOT_FOUND`,
    `ERR_RESCISSION_REQUEST_NOT_FOUND`, `ERR_REFUND_DISBURSEMENT_NOT_FOUND`,
    `ERR_CLOSING_PACKAGE_NOT_FOUND` or `ERR_RETRAINING_ASSIGNMENT_NOT_FOUND`."

    Design: Corner/entities/sales_gallery_get_unknown_id_not_found
    """
    fx.pin_clock(CLOCK_START)

    response = api.get_sales_gallery(UNKNOWN_UUID, GALLERY)
    validate_error(response, ApiErrorId.ERR_GALLERY_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""


def test_a_channel_without_min_age_is_refused_and_leaves_its_code_free():
    """min_age has no default, so the create fails and never claims the channel code.

    The PRD states: "Request shape: every required field present, types correct,
    enum members legal, numeric ranges honoured, `limit` within 1 to 100, `offset`
    at least 0, and every datetime field a valid ISO 8601 UTC instant —
    `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/tour_channel_create_without_min_age_missing_required
    """
    fx.pin_clock(CLOCK_START)

    incomplete = {
        "name": "Off-Property Contact",
        "channel_code": "OFF_PROPERTY_CONTACT",
        "incentive_gift_value_cents": 12500,
        "min_household_income_cents": 5_000_000,
        "min_qualification_score": 55,
    }
    validate_error(
        api.create_tour_channel(incomplete, MARKETING),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    complete = fx.create_channel()
    assert complete["channel_code"] == "OFF_PROPERTY_CONTACT"
    assert complete["min_age"] == 30


def test_a_marital_status_outside_the_declared_pair_is_refused():
    """SEPARATED is not a member, while MARRIED creates a household that owns nothing.

    The PRD states: "A `MarketingManager` registers a prospect household with a
    `household_name` of 1 to 120 characters, a `primary_age` from 18 through 99
    inclusive, a `household_income_cents` figure of at least 0, and a
    `marital_status` of either `MARRIED` or `SINGLE`."

    Design: Corner/entities/prospect_create_marital_status_invalid_enum
    """
    fx.pin_clock(CLOCK_START)

    validate_error(
        api.create_prospect(
            fac.create_prospect_payload(marital_status="SEPARATED"), MARKETING
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    prospect = validate_success(
        api.create_prospect(
            fac.create_prospect_payload(marital_status="MARRIED"), MARKETING
        ),
        201,
    )
    assert prospect["marital_status"] == "MARRIED"
    assert prospect["is_existing_owner"] is False


def test_a_booking_takes_its_length_from_the_gallery_and_its_score_from_the_formula():
    """A 90-minute gallery ends the tour at 08:30 while the score freezes at 80.

    The PRD states: "The booking's `scheduled_end_utc` is derived as the start plus
    the gallery's `presentation_minutes`, and the booking opens in `status`
    `SCHEDULED` with `assigned_rep_id`, `reschedule_reason`, `cancel_reason` and
    `checked_in_at` all null, `gift_issued` false, `gift_value_cents` 0 and
    `reschedule_count` 0."

    Design: Corner/entities/tour_booking_computed_fields_from_gallery_and_channel
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery(
        name="Ninety Minute Gallery", site_code="NMGAL", presentation_minutes=90
    )
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()

    booking = validate_success(
        api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel["id"],
                prospect["id"],
                gallery["id"],
                scheduled_start_utc=TOUR_DAY_UTC,
            ),
            MARKETING,
        ),
        201,
    )
    assert_instant_equals(
        booking["scheduled_end_utc"], "2026-08-16T08:30:00Z", "scheduled_end_utc"
    )
    assert booking["qualification_score"] == 80
    assert booking["qualification_penalty_points"] == 0
    assert booking["gift_issued"] is False
    assert booking["gift_value_cents"] == 0
    assert booking["reschedule_count"] == 0
    assert booking["assigned_rep_id"] is None

    assert fx.read_channel(channel["id"])["booked_count"] == 1
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 1


def test_client_supplied_state_and_score_do_not_survive_booking_creation():
    """A payload claiming TOURED, a rep, a score of 5 and version 99 changes nothing.

    The PRD states: "Qualification is evaluated once, when the booking is created,
    and both of its outputs are frozen onto the booking at that instant."

    Design: Corner/entities/tour_booking_create_system_fields_ignored_input
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()

    booking = validate_success(
        api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel["id"],
                prospect["id"],
                gallery["id"],
                scheduled_start_utc=TOUR_DAY_UTC,
                status="TOURED",
                assigned_rep_id=representative["id"],
                qualification_score=5,
                version=99,
            ),
            MARKETING,
        ),
        201,
    )
    assert booking["status"] == "SCHEDULED"
    assert booking["assigned_rep_id"] is None
    assert booking["qualification_score"] == 80
    assert booking["version"] == 1
    assert booking["id"] != representative["id"]

    stored = fx.read_booking(booking["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["assigned_rep_id"] is None


def test_compliance_history_rows_carry_no_version_and_no_updated_at():
    """An acknowledgment and a finding are appended, and neither is a versioned row.

    The PRD states: "A recorded disclosure acknowledgment and a prohibited-claim
    finding each carry only `id` and `created_at`. Neither has an `updated_at` field
    and neither has a `version` field, because neither is ever modified after it is
    appended."

    Design: Corner/entities/append_only_event_children_carry_no_version_field
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=TOUR_DAY_UTC,
        booking_overrides={"scheduled_start_utc": TOUR_DAY_UTC},
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]

    acknowledgment = fx.acknowledge_disclosure(
        presentation_id, rep_id, "RESCISSION_RIGHTS"
    )
    assert_append_only_shape(acknowledgment)

    finding = fx.file_claim_finding(
        presentation_id,
        "MINOR",
        fx.read_presentation(presentation_id)["version"],
        claim_code="GUARANTEED_RESALE",
        headers=OFFICER_BRAVO,
    )
    assert_append_only_shape(finding)

    rows, meta = validate_paginated(
        api.list_presentation_disclosure_acknowledgments(presentation_id, OFFICER_ALPHA)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == acknowledgment["id"]

    presentation = fx.read_presentation(presentation_id)
    assert presentation["disclosure_ack_count"] == 1
    assert presentation["disclosure_status"] == "PARTIAL"
    assert presentation["compliance_score"] == 75


def test_an_unminted_prospect_is_reported_before_an_unminted_gallery():
    """Both foreign keys are wrong, and the prospect rung comes first.

    The PRD states: "Existence of foreign keys supplied in a request body, validated
    in this declaration order and yielding HTTP 404 for the first one that does not
    resolve: `channel_id` yields `ERR_CHANNEL_NOT_FOUND`, `prospect_id` yields
    `ERR_PROSPECT_NOT_FOUND`, `gallery_id` yields `ERR_GALLERY_NOT_FOUND`,
    `booking_id` yields `ERR_BOOKING_NOT_FOUND`, `presentation_id` yields
    `ERR_PRESENTATION_NOT_FOUND`, `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`,
    `traded_in_agreement_id` also yields `ERR_AGREEMENT_NOT_FOUND`,
    `rescission_request_id` yields `ERR_RESCISSION_REQUEST_NOT_FOUND`, and `rep_id`
    yields `ERR_REPRESENTATIVE_NOT_FOUND`."

    Design: Corner/entities/tour_booking_create_unknown_prospect_id_not_found
    """
    fx.pin_clock(CLOCK_START)
    channel = fx.create_channel()

    refused = api.create_tour_booking(
        fac.create_tour_booking_payload(
            channel["id"],
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            scheduled_start_utc=TOUR_DAY_UTC,
        ),
        MARKETING,
    )
    validate_error(refused, ApiErrorId.ERR_PROSPECT_NOT_FOUND.value, 404)

    assert fx.read_channel(channel["id"])["booked_count"] == 0
