"""Path identifiers, body foreign keys, single-row reads, and reverse reachability."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    ADMIN,
    COMMITTEE_ALICE,
    COMMITTEE_ALICE_USER_ID,
    COORDINATOR,
    COORDINATOR_USER_ID,
    CREW_LEAD,
    OFFICER,
)

#: A well-formed identifier that belongs to no table in this service.
ABSENT = C.PROBE_UUID


def test_the_intake_side_names_the_table_it_could_not_find(api):
    """Six reads of the same absent identifier, six different error ids.

    "Every path identifier resolves, left to right — the matching not-found error
    (404)." The catalogue spells out what "matching" means: the household side of
    the surface carries `ERR_PROGRAM_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND` and
    `ERR_ENROLLMENT_NOT_FOUND`, each at HTTP 404.

    Design: Corner/entities/path_id_not_found_on_intake_side_reads
    """
    X.setup_program(api)

    validate_error(api.get_program(ABSENT, headers=ADMIN), E.ERR_PROGRAM_NOT_FOUND, 404)
    validate_error(api.get_household(ABSENT, headers=COORDINATOR), E.ERR_HOUSEHOLD_NOT_FOUND, 404)
    validate_error(api.get_member(ABSENT, headers=COORDINATOR), E.ERR_MEMBER_NOT_FOUND, 404)
    validate_error(api.get_review(ABSENT, headers=COMMITTEE_ALICE), E.ERR_REVIEW_NOT_FOUND, 404)
    validate_error(api.get_entry(ABSENT, headers=COORDINATOR), E.ERR_ENTRY_NOT_FOUND, 404)
    validate_error(api.get_enrollment(ABSENT, headers=COORDINATOR), E.ERR_ENROLLMENT_NOT_FOUND, 404)

    # Each refusal is a genuine error envelope, never a 200 with an empty body.
    A.assert_error_envelope_shape(api.get_household(ABSENT, headers=COORDINATOR))


def test_the_construction_and_finance_side_name_their_own_tables(api):
    """The other half of the surface is just as specific about what is missing.

    "Every path identifier resolves, left to right — the matching not-found error
    (404)." Here the matching ids are `ERR_SITE_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND` and `ERR_GRANT_NOT_FOUND`.

    Design: Corner/entities/path_id_not_found_on_construction_and_finance_reads
    """
    X.setup_program(api)

    validate_error(api.get_build_site(ABSENT, headers=ADMIN), E.ERR_SITE_NOT_FOUND, 404)
    validate_error(api.get_shift(ABSENT, headers=CREW_LEAD), E.ERR_SHIFT_NOT_FOUND, 404)
    validate_error(api.get_volunteer(ABSENT, headers=CREW_LEAD), E.ERR_VOLUNTEER_NOT_FOUND, 404)
    validate_error(api.get_assignment(ABSENT, headers=CREW_LEAD), E.ERR_ASSIGNMENT_NOT_FOUND, 404)
    validate_error(api.get_application(ABSENT, headers=OFFICER), E.ERR_APPLICATION_NOT_FOUND, 404)
    validate_error(api.get_grant_award(ABSENT, headers=ADMIN), E.ERR_GRANT_NOT_FOUND, 404)

    A.assert_error_envelope_shape(api.get_grant_award(ABSENT, headers=ADMIN))


def test_a_body_foreign_key_is_resolved_before_the_version_guard_or_any_business_rule(api):
    """Six creates naming an absent parent, and the seat probe carries a live version.

    "Every foreign key in the request body resolves, in the endpoint's declared
    input order — the matching not-found error (404). This applies to every creating
    endpoint that carries foreign keys." That check sits at priority 6, ahead of the
    optimistic-concurrency guard at priority 9, so a seat request naming an absent
    shift is a 404 and not a 412 even though it supplies the shift's current
    version.

    Design: Corner/entities/body_foreign_keys_must_resolve_before_business_rules_run
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    member = X.add_member(api, household["id"])
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"])
    live_version = X.shift_version(api, shift["id"])

    validate_error(
        api.create_household(F.household_payload(ABSENT, household_name="Orphan"), headers=COORDINATOR),
        E.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_member(
            F.member_payload(
                ABSENT,
                full_name="Orphan Member",
                relationship=C.RELATIONSHIP_DEPENDENT,
                birth_date="2015-01-01T00:00:00.000Z",
                is_adult_occupant=False,
            ),
            headers=COORDINATOR,
        ),
        E.ERR_HOUSEHOLD_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_entry(
            F.entry_payload(household["id"], ABSENT, hours_claimed=4.0), headers=COORDINATOR
        ),
        E.ERR_MEMBER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_cost_entry(F.cash_cost_payload(ABSENT, amount_cents=1_000_000), headers=CREW_LEAD),
        E.ERR_SITE_NOT_FOUND,
        404,
    )
    # A live, unspent shift version — and still a 404, because priority 6 outranks 9.
    validate_error(
        api.create_assignment(
            F.assignment_payload(ABSENT, live_version, volunteer_id=volunteer["id"]), headers=CREW_LEAD
        ),
        E.ERR_SHIFT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_assignment(
            F.assignment_payload(shift["id"], live_version, volunteer_id=ABSENT), headers=CREW_LEAD
        ),
        E.ERR_VOLUNTEER_NOT_FOUND,
        404,
    )

    reread_shift = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert reread_shift["confirmed_general_count"] == 0
    reread_volunteer = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    A.assert_committed_hours(reread_volunteer, 0.0)
    assert member["household_id"] == household["id"]


def test_every_single_row_read_returns_the_row_the_chain_wrote(api):
    """Nine aggregates, nine object envelopes, and not one stale snapshot.

    "Endpoints that create a new resource return HTTP 201 on success. Every other
    successful endpoint — reads, lists, state transitions, ledger postings, reports,
    and the logical clock — returns HTTP 200. Unless a section above states
    otherwise, each of these responses carries the created or updated resource in
    `data`", and "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/read_endpoints_return_the_stored_row_for_every_aggregate
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member, review = built["household"], built["members"][0], built["reviews"][0]
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"])
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    enrollment = X.setup_enrollment(api, household["id"], required_module_count=2)
    entry = X.claim_hours(api, household["id"], member["id"], hours_claimed=12.0)
    award = X.setup_grant(
        api,
        program["id"],
        award_code="G-2026-01",
        donor_name="Cedar Foundation",
        amount_cents=2_500_000,
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        households_served_target=3,
    )

    read_member = A.assert_object_envelope(api.get_member(member["id"], headers=COORDINATOR))
    assert read_member["id"] == member["id"]
    assert read_member["relationship"] == C.RELATIONSHIP_APPLICANT
    assert read_member["is_adult_occupant"] is True
    assert read_member["status"] == C.MEMBER_ACTIVE
    A.assert_hours_equal(read_member["credited_hours_to_date"], 0.0)

    read_review = A.assert_object_envelope(api.get_review(review["id"], headers=COMMITTEE_ALICE))
    assert read_review["id"] == review["id"]
    assert read_review["dimension"] == C.DIMENSION_NEED
    assert read_review["score"] == 80.0
    assert read_review["recommendation"] == C.RECOMMENDATION_ADVANCE
    assert read_review["reviewer_user_id"] == COMMITTEE_ALICE_USER_ID
    assert read_review["status"] == C.REVIEW_SUBMITTED

    read_entry = A.assert_object_envelope(api.get_entry(entry["id"], headers=COORDINATOR))
    assert read_entry["id"] == entry["id"]
    assert read_entry["status"] == C.ENTRY_CLAIMED
    A.assert_hours_equal(read_entry["hours_claimed"], 12.0)
    assert read_entry["credit_weight"] is None
    assert read_entry["hours_credited"] is None
    assert read_entry["claimed_by_user_id"] == COORDINATOR_USER_ID
    assert read_entry["verified_by_user_id"] is None

    read_site = A.assert_object_envelope(api.get_build_site(site["id"], headers=ADMIN))
    assert read_site["id"] == site["id"]
    assert read_site["readiness_status"] == C.SITE_READY_TO_BUILD
    assert read_site["title_cleared"] is True
    assert read_site["environmental_cleared"] is True
    assert read_site["utilities_cleared"] is True
    assert read_site["safety_posture"] == C.POSTURE_CLEAR
    assert read_site["assigned_household_id"] is None

    read_shift = A.assert_object_envelope(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert read_shift["id"] == shift["id"]
    assert read_shift["status"] == C.SHIFT_OPEN
    assert read_shift["duration_hours"] == 4.0
    assert read_shift["volunteer_slots"] == 2
    # The seat is only RESERVED, and RESERVED seats are excluded from the count.
    assert read_shift["confirmed_general_count"] == 0
    assert read_shift["fill_ratio"] == 0

    read_volunteer = A.assert_object_envelope(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert read_volunteer["id"] == volunteer["id"]
    assert read_volunteer["status"] == C.VOLUNTEER_ACTIVE
    assert read_volunteer["is_minor"] is False
    assert read_volunteer["trade_certifications"] == []
    # The RESERVED seat already books the shift's whole span.
    A.assert_committed_hours(read_volunteer, 4.0, strikes=0)

    read_seat = A.assert_object_envelope(api.get_assignment(seat["id"], headers=CREW_LEAD))
    assert read_seat["id"] == seat["id"]
    assert read_seat["shift_id"] == shift["id"]
    assert read_seat["volunteer_id"] == volunteer["id"]
    assert read_seat["role"] == C.SEAT_GENERAL
    assert read_seat["status"] == C.ASSIGNMENT_RESERVED
    assert read_seat["checked_in_at"] is None
    assert read_seat["household_member_id"] is None

    read_enrollment = A.assert_object_envelope(api.get_enrollment(enrollment["id"], headers=COORDINATOR))
    assert read_enrollment["id"] == enrollment["id"]
    assert read_enrollment["curriculum_code"] == C.CURRICULUM_HOMEBUYER_CORE
    assert read_enrollment["status"] == C.ENROLLMENT_ENROLLED
    assert read_enrollment["required_module_count"] == 2
    assert read_enrollment["passed_module_count"] == 0
    assert read_enrollment["missed_session_count"] == 0
    assert read_enrollment["completed_on"] is None
    assert read_enrollment["expires_on"] is None

    read_award = A.assert_object_envelope(api.get_grant_award(award["id"], headers=ADMIN))
    assert read_award["id"] == award["id"]
    assert read_award["award_code"] == "G-2026-01"
    assert read_award["households_served_target"] == 3
    assert read_award["status"] == C.GRANT_OPEN
    assert read_award["restricted_to_in_kind_reporting"] is False


def test_every_child_is_reachable_from_its_parent_and_only_from_its_parent(api):
    """Twelve filtered lists find their own row and exclude the neighbour's.

    "Unless a specific report states otherwise, list results are ordered by
    `created_at` ascending. The `meta` block of a list response carries `limit`,
    `offset`, `total_count` (the number of rows matching the filters before the
    window is applied) and `has_more` (true when rows remain beyond the current
    window)."

    Design: Corner/entities/every_foreign_key_is_reverse_reachable_from_its_parent
    """
    program = X.setup_program(api)
    other_program = X.setup_program(api, affiliate_name="Northgate Habitat", service_area_code="HAYS")
    other_household = X.setup_household(api, other_program["id"], household_name="Unrelated")
    other_site = X.setup_site(
        api,
        other_program["id"],
        parcel_number="P-9001",
        street_address="9 Elm Ct",
        acquisition_cost_cents=3_000_000,
        appraised_value_cents=12_000_000,
    )

    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    site = X.setup_ready_site(api, program["id"])
    cost = X.add_cash_cost(api, site["id"], amount_cents=1_000_000)
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"])
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    enrollment = X.setup_enrollment(api, household["id"], required_module_count=2)
    entry = X.claim_hours(api, household["id"], member["id"], hours_claimed=12.0)
    application = X.setup_draft_application(api, household["id"], site["id"])
    award = X.setup_grant(api, program["id"], award_code="G-2026-01")

    def only(response, expected_id):
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (meta, rows)
        assert [row["id"] for row in rows] == [expected_id], rows
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, meta
        return rows[0]

    only(api.list_programs({"service_area_code": C.CANONICAL_SERVICE_AREA}, headers=ADMIN), program["id"])
    only(api.list_households({"program_id": program["id"]}, headers=ADMIN), household["id"])
    only(api.list_members({"household_id": household["id"]}, headers=COORDINATOR), member["id"])
    only(api.list_entries({"household_id": household["id"]}, headers=COORDINATOR), entry["id"])
    only(api.list_build_sites({"program_id": program["id"]}, headers=ADMIN), site["id"])
    only(api.list_cost_entries({"build_site_id": site["id"]}, headers=CREW_LEAD), cost["id"])
    only(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD), shift["id"])
    only(api.list_volunteers({"program_id": program["id"]}, headers=CREW_LEAD), volunteer["id"])
    only(api.list_assignments({"shift_id": shift["id"]}, headers=CREW_LEAD), seat["id"])
    only(api.list_enrollments({"household_id": household["id"]}, headers=COORDINATOR), enrollment["id"])
    only(api.list_grant_awards({"program_id": program["id"]}, headers=ADMIN), award["id"])
    filed = only(
        api.list_applications({"household_id": household["id"]}, headers=OFFICER), application["id"]
    )
    assert filed["status"] == C.APP_DRAFT

    reviews, review_meta = validate_paginated(
        api.list_reviews({"household_id": household["id"]}, headers=ADMIN)
    )
    assert review_meta["total_count"] == 6
    assert all(row["household_id"] == household["id"] for row in reviews)

    # The neighbouring program's rows were never in scope for any of those filters.
    other_households, other_meta = validate_paginated(
        api.list_households({"program_id": other_program["id"]}, headers=ADMIN)
    )
    assert other_meta["total_count"] == 1
    assert other_households[0]["id"] == other_household["id"]
    other_sites, other_site_meta = validate_paginated(
        api.list_build_sites({"program_id": other_program["id"]}, headers=ADMIN)
    )
    assert other_site_meta["total_count"] == 1
    assert other_sites[0]["id"] == other_site["id"]
