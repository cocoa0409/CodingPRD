"""How each resource comes back over the wire.

Creation defaults, server-minted properties, derived counters at rest, filtered
and paged listings, and the per-collection not-found and schema-band errors that
guard every read and write.
"""

from test_helpers import (
    ApiErrorId,
    CORPS_DIRECTOR_HEADERS,
    MEMBERSHIP_COORDINATOR_HEADERS,
    NON_EXISTENT_UUID,
    TOUR_MANAGER_HEADERS,
    assert_common_fields,
    assert_facility_agreement,
    assert_host_school,
    assert_member,
    assert_season,
    assert_site_booking,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

REHEARSAL_SHAPE = dict(
    travel_miles_from_previous=0,
    uniform_trunks=0,
    instrument_cases=0,
    prop_units=0,
    truck_count=1,
    rehearsal_minutes=120,
    heat_index_f=80,
)


def test_a_new_season_opens_with_every_rollup_at_zero(api):
    """The five ledger rollups, the epoch and the ledger status all start clean.

    PRD: "A freshly opened season starts with `billing_epoch` at 0, every ledger
    rollup — `tuition_charged_cents`, `tuition_collected_cents`,
    `late_fee_collected_cents`, `housing_cost_cents` and `tour_revenue_cents` — at
    0, and `ledger_status` at `OPEN`."

    Design: Corner/entities/season_creation_returns_201_with_zeroed_ledgers_and_open_status
    """
    response = api.create_season(f.season_payload(), CORPS_DIRECTOR_HEADERS)
    assert response.status_code == 201, response.text
    season = validate_success(response, 201)

    assert_season(season, name="2027 Tour", year=2027, tuition_base_cents=399900,
                  billing_epoch=0, ledger_status="OPEN", version=1,
                  tuition_charged_cents=0, tuition_collected_cents=0,
                  late_fee_collected_cents=0, housing_cost_cents=0,
                  tour_revenue_cents=0)
    assert "_" not in season["id"], "the id carries no type prefix"


def test_a_host_school_reads_back_exactly_as_catalogued(api):
    """The stored inputs are echoed and both derived counters sit at zero.

    PRD: "A new school begins with `booked_block_count` and `reserved_bed_nights`
    both at 0; both are derived counters the server maintains, the first counting
    the school's rehearsal blocks whose `status` is `HELD` or `CONFIRMED` and the
    second summing the nights of active stays across all of the school's
    agreements."

    Design: Corner/entities/host_school_retrieval_returns_stored_representation
    """
    created = fx.create_school(api, name="Rockford High School", city="Rockford",
                               state_code="IL", sleeping_space_count=30,
                               capacity_per_space=12, rehearsal_field_count=2,
                               has_air_conditioning=True)

    fetched = validate_success(api.get_host_school(created["id"], TOUR_MANAGER_HEADERS))
    assert_host_school(fetched, name="Rockford High School", city="Rockford",
                       state_code="IL", sleeping_space_count=30,
                       capacity_per_space=12, rehearsal_field_count=2,
                       has_air_conditioning=True, booked_block_count=0,
                       reserved_bed_nights=0, version=1)


def test_the_stop_listing_filters_then_pages_in_creation_order(api):
    """A status filter narrows the set before limit and offset slice it.

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending."

    Design: Corner/entities/tour_stop_listing_filters_by_season_and_status_with_pagination
    """
    season = fx.create_season(api)
    fx.create_rehearsal_stop(api, season["id"], venue_name="Stop One", city="Rockford",
                             state_code="IL", arrive_at="2027-06-18T08:00:00Z",
                             depart_at="2027-06-18T20:00:00Z", **REHEARSAL_SHAPE)
    second = fx.create_rehearsal_stop(api, season["id"], venue_name="Stop Two",
                                      city="Dubuque", state_code="IA",
                                      arrive_at="2027-06-19T08:00:00Z",
                                      depart_at="2027-06-19T20:00:00Z",
                                      **REHEARSAL_SHAPE)
    third = fx.create_rehearsal_stop(api, season["id"], venue_name="Stop Three",
                                     city="Peoria", state_code="IL",
                                     arrive_at="2027-06-20T08:00:00Z",
                                     depart_at="2027-06-20T20:00:00Z",
                                     **REHEARSAL_SHAPE)
    fx.cancel_stop(api, third["id"], "route change")

    stops, meta = validate_paginated(api.list_tour_stops(
        TOUR_MANAGER_HEADERS,
        params={"season_id": season["id"], "status": "PLANNED", "limit": 1,
                "offset": 1},
    ))
    assert [stop["id"] for stop in stops] == [second["id"]]
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta


NOT_FOUND_READS = [
    ("/seasons", ApiErrorId.SEASON_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/members", ApiErrorId.MEMBER_NOT_FOUND, MEMBERSHIP_COORDINATOR_HEADERS),
    ("/member-contracts", ApiErrorId.CONTRACT_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/payment-plans", ApiErrorId.PAYMENT_PLAN_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/tuition-payments", ApiErrorId.TUITION_PAYMENT_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/host-schools", ApiErrorId.HOST_SCHOOL_NOT_FOUND, TOUR_MANAGER_HEADERS),
    ("/facility-agreements", ApiErrorId.FACILITY_AGREEMENT_NOT_FOUND, TOUR_MANAGER_HEADERS),
    ("/housing-assignments", ApiErrorId.HOUSING_ASSIGNMENT_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/tour-stops", ApiErrorId.TOUR_STOP_NOT_FOUND, TOUR_MANAGER_HEADERS),
    ("/site-bookings", ApiErrorId.SITE_BOOKING_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/volunteers", ApiErrorId.VOLUNTEER_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/staff-assignments", ApiErrorId.STAFF_ASSIGNMENT_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
    ("/show-settlements", ApiErrorId.SHOW_SETTLEMENT_NOT_FOUND, CORPS_DIRECTOR_HEADERS),
]


def test_each_collection_owns_its_own_not_found_error(api):
    """Thirteen reads against an empty store, thirteen distinct error ids.

    PRD: "Each collection has its own not-found error, so the response identifies
    which link in the chain broke: `ERR_SEASON_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_PAYMENT_PLAN_NOT_FOUND`,
    `ERR_TUITION_PAYMENT_NOT_FOUND`, `ERR_HOST_SCHOOL_NOT_FOUND`,
    `ERR_FACILITY_AGREEMENT_NOT_FOUND`, `ERR_HOUSING_ASSIGNMENT_NOT_FOUND`,
    `ERR_TOUR_STOP_NOT_FOUND`, `ERR_SITE_BOOKING_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, and
    `ERR_SHOW_SETTLEMENT_NOT_FOUND`."

    Design: Corner/entities/unknown_path_ids_return_not_found_per_collection
    """
    seen = set()
    for collection, expected_error, headers in NOT_FOUND_READS:
        response = api.call("GET", f"{collection}/{NON_EXISTENT_UUID}", None, headers)
        validate_error(response, expected_error, 404)
        body = response.json()["data"]
        assert isinstance(body.get("message"), str) and body["message"], (
            f"{collection} must return a human-readable message"
        )
        seen.add(body["error_id"])
    assert len(seen) == len(NOT_FOUND_READS), (
        f"expected {len(NOT_FOUND_READS)} distinct error ids, got {sorted(seen)}"
    )


def test_a_missing_required_field_outranks_an_unresolvable_parent(api):
    """Schema validation fires at rung 3, long before the FK is resolved.

    PRD: "Every required body field is present, carries its declared JSON type,
    and every enum-typed field carries a declared member of that enum; unknown
    fields are ignored; integer cent fields must arrive as JSON integers and never
    as decimals or numeric strings."

    Design: Corner/entities/member_create_missing_required_fields_returns_invalid_request
    """
    season = fx.create_season(api)

    missing_section = api.create_member(
        f.member_payload(season["id"], full_name="Avery Nakamura",
                         date_of_birth="2005-03-04", section=f.OMIT),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )
    validate_error(missing_section, ApiErrorId.INVALID_REQUEST, 400)

    missing_dob = api.create_member(
        f.member_payload(NON_EXISTENT_UUID, full_name="Avery Nakamura",
                         date_of_birth=f.OMIT),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )
    validate_error(missing_dob, ApiErrorId.INVALID_REQUEST, 400)

    members, _meta = validate_paginated(
        api.list_members(MEMBERSHIP_COORDINATOR_HEADERS)
    )
    assert members == [], "a rejected registration writes no member"
    assert fx.get_season(api, season["id"])["version"] == 1


def test_a_drafted_agreement_pins_no_rate_and_bills_nothing(api):
    """Every negotiated figure stays null or zero until the signature lands.

    PRD: "A draft lands in `status` `DRAFT` with `counter_round` at 0,
    `countered_nightly_rate_cents` and `effective_nightly_rate_cents` null, and
    `occupied_bed_nights`, `billable_bed_nights` and `billable_cents` all at 0."

    Design: Corner/entities/facility_agreement_defaults_applied_on_create
    """
    season = fx.create_season(api)
    school = fx.create_school(api, name="Rockford High School", city="Rockford",
                              state_code="IL")
    agreement = fx.draft_agreement(api, school["id"], season["id"],
                                   nightly_rate_cents=500,
                                   minimum_billable_beds=100)

    assert_facility_agreement(agreement, status="DRAFT", counter_round=0,
                              countered_nightly_rate_cents=None,
                              effective_nightly_rate_cents=None,
                              occupied_bed_nights=0, billable_bed_nights=0,
                              billable_cents=0)
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 0
    assert_host_school(fx.get_school(api, school["id"]), booked_block_count=0,
                       reserved_bed_nights=0)


def test_client_supplied_values_for_derived_member_fields_are_discarded(api):
    """Membership standing, minority and the money fields are all server-owned.

    PRD: "Registration writes `membership_status` as `APPLICANT`, `medical_status`
    as `CLEARED`, every money field on the member — `tuition_charged_cents`,
    `tuition_paid_cents`, `tuition_balance_cents` and `refund_due_cents` — as 0,
    and `withdrawal_date`, `withdrawal_obligation_cents` and `audition_score` as
    null, with `withdrawal_obligation_basis` at `NONE`."

    Design: Corner/entities/member_computed_ledger_fields_input_ignored
    """
    season = fx.create_season(api)
    member = validate_success(api.create_member(
        f.member_payload(season["id"], full_name="Jamie Torres",
                         date_of_birth="2010-09-01", section="COLOR_GUARD",
                         tuition_charged_cents=1, membership_status="ON_TOUR",
                         is_minor=False),
        MEMBERSHIP_COORDINATOR_HEADERS,
    ), 201)

    assert_member(member, membership_status="APPLICANT", medical_status="CLEARED",
                  is_minor=True, tuition_charged_cents=0, tuition_paid_cents=0,
                  tuition_balance_cents=0, refund_due_cents=0,
                  withdrawal_obligation_basis="NONE", version=1)


def test_the_four_common_properties_are_minted_by_the_server(api):
    """A create body that supplies id, timestamps and version is overruled.

    PRD: "`version` is an integer that starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource, including mutations
    the server performs on its own initiative as a cascade of some other request."

    Design: Corner/entities/system_fields_are_server_minted_input_ignored
    """
    school = validate_success(api.create_host_school(
        f.host_school_payload(name="Dubuque Senior High", city="Dubuque",
                              state_code="IA", sleeping_space_count=20,
                              capacity_per_space=10, rehearsal_field_count=1,
                              has_air_conditioning=False,
                              id="hs_client_supplied",
                              created_at="1999-01-01T00:00:00.000Z",
                              updated_at="1999-01-01T00:00:00.000Z",
                              version=77),
        TOUR_MANAGER_HEADERS,
    ), 201)

    assert_common_fields(school, expected_version=1)
    assert is_valid_uuid(school["id"]) and school["id"] != "hs_client_supplied"
    assert school["created_at"] == "2026-08-01T00:00:00.000Z", school["created_at"]
    assert school["updated_at"] == school["created_at"]


def test_three_schema_band_rules_report_three_different_errors(api):
    """An inverted window, a bad enum and a zero rate are distinct failures.

    PRD: "Ordered date and instant pairs are strictly increasing: a season's
    `spring_training_end_date` must be later than its `spring_training_start_date`
    and its `tour_departure_date` must also be later than its
    `spring_training_start_date`; a facility agreement's `end_date` must be later
    than its `start_date`; a stop's `depart_at` must be later than its `arrive_at`;
    a rehearsal block's `block_end_at` must be later than its `block_start_at`; a
    shift's `shift_end_at` must be later than its `shift_start_at`; and a stay's
    `check_out_date` must be later than its `check_in_date`."

    Design: Corner/entities/inverted_date_pairs_and_bad_enum_values_are_rejected
    """
    season = fx.create_season(api)
    school = fx.create_school(api, name="Rockford High School", city="Rockford",
                              state_code="IL")

    inverted = api.create_facility_agreement(
        f.facility_agreement_payload(school["id"], season["id"],
                                     start_date="2027-06-05",
                                     end_date="2027-05-10",
                                     nightly_rate_cents=500,
                                     minimum_billable_beds=100),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(inverted, ApiErrorId.INVALID_DATE_RANGE, 400)

    bad_enum = api.create_member(
        f.member_payload(season["id"], full_name="Avery Nakamura",
                         date_of_birth="2005-03-04", section="BAGPIPES"),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )
    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST, 400)

    zero_rate = api.create_facility_agreement(
        f.facility_agreement_payload(school["id"], season["id"],
                                     nightly_rate_cents=0,
                                     minimum_billable_beds=100),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(zero_rate, ApiErrorId.AMOUNT_NOT_POSITIVE, 400)

    agreements, _meta = validate_paginated(
        api.list_facility_agreements(TOUR_MANAGER_HEADERS)
    )
    assert agreements == [], "no agreement survives the two rejections"
    members, _meta = validate_paginated(api.list_members(MEMBERSHIP_COORDINATOR_HEADERS))
    assert members == [], "no member survives the enum rejection"


def test_each_unresolvable_body_key_reports_its_own_parent_type(api):
    """Four writes, four different parents, four different not-found errors.

    PRD: "The same family of not-found errors is reused: a body referencing a
    nonexistent host school reports `ERR_HOST_SCHOOL_NOT_FOUND`, one referencing a
    nonexistent agreement reports `ERR_FACILITY_AGREEMENT_NOT_FOUND`, and a
    `previous_stop_id` that resolves to nothing reports `ERR_TOUR_STOP_NOT_FOUND`."

    Design: Corner/entities/body_foreign_keys_must_resolve_or_return_404
    """
    season = fx.create_season(api)
    stop = fx.create_rehearsal_stop(api, season["id"], venue_name="Stop One",
                                    city="Rockford", state_code="IL",
                                    arrive_at="2027-06-18T08:00:00Z",
                                    depart_at="2027-06-18T20:00:00Z",
                                    **REHEARSAL_SHAPE)

    bad_season = api.create_member(
        f.member_payload(NON_EXISTENT_UUID, full_name="Avery Nakamura",
                         date_of_birth="2005-03-04"),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )
    validate_error(bad_season, ApiErrorId.SEASON_NOT_FOUND, 404)

    bad_school = api.create_facility_agreement(
        f.facility_agreement_payload(NON_EXISTENT_UUID, season["id"],
                                     nightly_rate_cents=500,
                                     minimum_billable_beds=100),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(bad_school, ApiErrorId.HOST_SCHOOL_NOT_FOUND, 404)

    bad_previous = api.create_tour_stop(
        f.rehearsal_stop_payload(season["id"], venue_name="Orphan Stop",
                                 city="Peoria", state_code="IL",
                                 previous_stop_id=NON_EXISTENT_UUID,
                                 arrive_at="2027-06-19T08:00:00Z",
                                 depart_at="2027-06-19T20:00:00Z",
                                 travel_miles_from_previous=60,
                                 uniform_trunks=0, instrument_cases=0,
                                 prop_units=0, truck_count=1,
                                 rehearsal_minutes=120, heat_index_f=80),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(bad_previous, ApiErrorId.TOUR_STOP_NOT_FOUND, 404)

    bad_volunteer = api.create_staff_assignment(
        f.staff_assignment_payload(NON_EXISTENT_UUID, stop["id"], "DRIVE",
                                   "2027-06-18T09:00:00Z", "2027-06-18T19:00:00Z"),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(bad_volunteer, ApiErrorId.VOLUNTEER_NOT_FOUND, 404)

    for lister in (api.list_members(MEMBERSHIP_COORDINATOR_HEADERS),
                   api.list_facility_agreements(TOUR_MANAGER_HEADERS),
                   api.list_staff_assignments(TOUR_MANAGER_HEADERS)):
        rows, _meta = validate_paginated(lister)
        assert rows == [], "no child row survives an unresolvable foreign key"


def test_a_block_must_agree_with_its_agreement_on_school_and_season(api):
    """Resolving each key is not enough; the keys must also cohere.

    PRD: "Rung 28 requires that a rehearsal block's `host_school_id` equal the
    referenced agreement's `host_school_id`, reporting
    `ERR_AGREEMENT_SCHOOL_MISMATCH`."

    Design: Corner/entities/site_booking_school_must_match_its_agreement_school
    """
    season_one = fx.create_season(api)
    season_two = fx.create_season(api, name="2027 B Corps Tour",
                                  tuition_base_cents=299900)
    school_b = fx.create_school(api, name="Dubuque Senior High", city="Dubuque",
                                state_code="IA", sleeping_space_count=20,
                                capacity_per_space=10, rehearsal_field_count=1,
                                has_air_conditioning=False)
    built = fx.signed_agreement_with_school(
        api, season_one["id"], usage_type="TOUR_REHEARSAL",
        start_date="2027-06-18", end_date="2027-06-25", nightly_rate_cents=400,
        minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    school_a, agreement = built["school"], built["agreement"]
    stop_one = fx.create_rehearsal_stop(api, season_one["id"],
                                        venue_name="Season 1 Stop", city="Rockford",
                                        state_code="IL",
                                        arrive_at="2027-06-19T08:00:00Z",
                                        depart_at="2027-06-19T20:00:00Z",
                                        **REHEARSAL_SHAPE)
    stop_two = fx.create_rehearsal_stop(api, season_two["id"],
                                        venue_name="Season 2 Stop", city="Peoria",
                                        state_code="IL",
                                        arrive_at="2027-06-19T08:00:00Z",
                                        depart_at="2027-06-19T20:00:00Z",
                                        **REHEARSAL_SHAPE)

    wrong_school = api.create_site_booking(
        f.site_booking_payload(stop_one["id"], school_b["id"], agreement["id"],
                              "2027-06-19T10:00:00Z", "2027-06-19T14:00:00Z",
                              indoor=False),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(wrong_school, ApiErrorId.AGREEMENT_SCHOOL_MISMATCH, 409)

    wrong_season = api.create_site_booking(
        f.site_booking_payload(stop_two["id"], school_a["id"], agreement["id"],
                              "2027-06-19T10:00:00Z", "2027-06-19T14:00:00Z",
                              indoor=False),
        TOUR_MANAGER_HEADERS,
    )
    validate_error(wrong_season, ApiErrorId.SEASON_MISMATCH, 409)

    booking = fx.create_booking(api, stop_one["id"], school_a["id"], agreement["id"],
                                "2027-06-19T10:00:00Z", "2027-06-19T14:00:00Z",
                                indoor=False)
    assert_site_booking(booking, status="HELD")
    assert_host_school(fx.get_school(api, school_a["id"]), booked_block_count=1)
    assert_host_school(fx.get_school(api, school_b["id"]), booked_block_count=0)
