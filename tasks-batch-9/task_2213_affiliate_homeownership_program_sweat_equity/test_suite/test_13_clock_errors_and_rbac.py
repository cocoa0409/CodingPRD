"""The logical clock, one envelope per HTTP class, and the three-rung authorization ladder."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    ADMIN,
    COMMITTEE_ALICE,
    COORDINATOR,
    COORDINATOR_USER_ID,
    CREW_LEAD,
    NO_HEADERS,
    OFFICER,
    make_headers,
    make_volunteer_headers,
)


def test_the_logical_clock_refuses_a_repeated_or_a_backward_instant(api):
    """The comparator is strictly greater-than, so standing still is as bad as going back.

    "A `ProgramAdmin` moves it by supplying `current_utc`; the clock may only move
    forward, so a `current_utc` that is not strictly after the present value is
    rejected with `ERR_CLOCK_MUST_ADVANCE` (HTTP 422). The endpoint returns the clock
    state."

    One millisecond is enough to satisfy it.

    Design: Corner/validations/the_logical_clock_refuses_a_repeated_or_backward_instant
    """
    X.setup_program(api)
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")

    # The instant the clock already holds is not strictly after itself.
    validate_error(
        api.set_clock("2026-08-05T00:00:00.000Z", headers=ADMIN), E.ERR_CLOCK_MUST_ADVANCE, 422
    )
    validate_error(
        api.set_clock(C.INITIAL_CLOCK, headers=ADMIN), E.ERR_CLOCK_MUST_ADVANCE, 422
    )

    validate_success(api.set_clock("2026-08-05T00:00:00.001Z", headers=ADMIN))

    # The new instant is the one every subsequent write is stamped with.
    program = X.setup_program(api, affiliate_name="Northgate Habitat", service_area_code="HAYS")
    assert program["created_at"] == "2026-08-05T00:00:00.001Z"


def test_every_http_class_in_the_catalog_is_reachable_and_shares_one_error_envelope(api):
    """401, 403, 404, 409, 412 and 422 in one test, all six shaped identically.

    "Both must be present and non-empty; a request that omits either — on any
    endpoint other than the logical-clock endpoint — is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)." And: "The `meta` object for error
    responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/every_http_class_in_the_catalog_is_reachable_with_one_error_envelope
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer_one = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    volunteer_two = X.setup_volunteer(api, program["id"], full_name="Omar Vance")
    shift = X.setup_open_shift(api, site["id"])
    spent_version = X.shift_version(api, shift["id"])
    X.reserve_volunteer_seat(api, shift["id"], volunteer_one["id"])
    household = X.setup_household(api, program["id"], household_name="Doss")

    probes = [
        # 401 — no headers at all on an endpoint that is not the clock.
        (api.get_program(program["id"], headers=NO_HEADERS), E.ERR_MISSING_AUTH_HEADERS, 401),
        # 403 — a recognised role that intake does not list.
        (
            api.create_household(
                F.household_payload(program["id"], household_name="Volunteer Intake"),
                headers=make_volunteer_headers(volunteer_two["id"]),
            ),
            E.ERR_ROLE_NOT_PERMITTED,
            403,
        ),
        # 404 — a path identifier that resolves to nothing.
        (
            api.get_household(C.PROBE_NOT_FOUND_UUID, headers=COORDINATOR),
            E.ERR_HOUSEHOLD_NOT_FOUND,
            404,
        ),
        # 409 — a legal endpoint reached from an illegal state.
        (
            api.refer_to_committee(household["id"], F.referral_payload(), headers=COORDINATOR),
            E.ERR_TRANSITION_NOT_ALLOWED,
            409,
        ),
        # 412 — a version the first accepted seat already spent.
        (
            api.create_assignment(
                F.assignment_payload(shift["id"], spent_version, volunteer_id=volunteer_two["id"]),
                headers=CREW_LEAD,
            ),
            E.ERR_STALE_SHIFT_VERSION,
            412,
        ),
        # 422 — a payload-shape failure.
        (
            api.list_households({"program_id": program["id"], "limit": 500}, headers=COORDINATOR),
            E.ERR_VALIDATION,
            422,
        ),
    ]

    assert len(probes) == 6
    assert sorted(status for _, _, status in probes) == [401, 403, 404, 409, 412, 422]
    for response, error_id, status in probes:
        validate_error(response, error_id, status)
        A.assert_error_envelope_shape(response)


def test_exclusive_operations_are_refused_to_every_other_role_while_shared_ones_are_not(api):
    """Six cross-role writes bounce, and the two genuinely shared writes go through.

    "`FamilyServicesCoordinator` owns applicant intake, income and housing
    documentation, homebuyer education delivery, and the sweat equity hour ledger.
    `SelectionCommitteeMember` scores applicants and may retract its own reviews, and
    holds no write access to hours, sites, or mortgages." And the volunteer seat is
    the exception that proves the rule: it "holds no exclusive operation, because
    every write it performs is one a `ConstructionManager` may also perform on its
    behalf".

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_while_shared_ones_are_not
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")

    validate_error(
        api.create_household(
            F.household_payload(program["id"], household_name="Intake By Crew"), headers=CREW_LEAD
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_build_site(
            F.build_site_payload(program["id"], parcel_number="P-2002", street_address="44 Oak St"),
            headers=COORDINATOR,
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_shift(F.shift_payload(site["id"]), headers=OFFICER),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_review(F.review_payload(household["id"], C.DIMENSION_NEED), headers=ADMIN),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_enrollment(F.enrollment_payload(household["id"]), headers=COMMITTEE_ALICE),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_cost_entry(
            F.cash_cost_payload(site["id"], amount_cents=50_000),
            headers=make_volunteer_headers(volunteer["id"]),
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # None of the six refusals left a row behind.
    households, household_meta = validate_paginated(
        api.list_households({"program_id": program["id"]}, headers=COORDINATOR)
    )
    assert household_meta["total_count"] == 1
    assert [row["household_name"] for row in households] == [household["household_name"]]
    _, site_meta = validate_paginated(api.list_build_sites({"program_id": program["id"]}, headers=ADMIN))
    assert site_meta["total_count"] == 1
    _, shift_meta = validate_paginated(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD))
    assert shift_meta["total_count"] == 0
    _, review_meta = validate_paginated(
        api.list_reviews({"household_id": household["id"]}, headers=ADMIN)
    )
    assert review_meta["total_count"] == 0
    _, enrollment_meta = validate_paginated(
        api.list_enrollments({"household_id": household["id"]}, headers=COORDINATOR)
    )
    assert enrollment_meta["total_count"] == 0

    # The shared writes: a volunteer profile and a cost line accept either owner.
    admin_volunteer = validate_success(
        api.create_volunteer(
            F.volunteer_payload(program["id"], full_name="Priya Raman"), headers=ADMIN
        ),
        201,
    )
    assert admin_volunteer["status"] == C.VOLUNTEER_ACTIVE
    crew_cost = validate_success(
        api.create_cost_entry(
            F.cash_cost_payload(site["id"], amount_cents=50_000, category=C.COST_CATEGORY_MATERIALS),
            headers=CREW_LEAD,
        ),
        201,
    )
    admin_cost = validate_success(
        api.create_cost_entry(
            F.cash_cost_payload(site["id"], amount_cents=30_000, category=C.COST_CATEGORY_PERMITS),
            headers=ADMIN,
        ),
        201,
    )
    assert crew_cost["status"] == C.COST_RECORDED
    assert admin_cost["status"] == C.COST_RECORDED
    _, cost_meta = validate_paginated(api.list_cost_entries({"build_site_id": site["id"]}, headers=ADMIN))
    assert cost_meta["total_count"] == 2


def test_the_auth_ladder_checks_headers_then_the_role_name_then_permission_before_the_body(api):
    """One malformed intake body replayed four ways climbs the ladder one rung at a time.

    "Both must be present and non-empty; a request that omits either — on any
    endpoint other than the logical-clock endpoint — is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401). A header value that is not one of the seven
    role names below is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). A recognised role
    that is not listed among the addressed endpoint's authorized roles is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    The body is missing `household_size` throughout, so only the last of the four
    calls — the one that clears all three rungs — ever gets to say so.

    Design: Corner/rbac/auth_ladder_checks_headers_then_role_name_then_permission_before_the_body
    """
    program = X.setup_program(api)
    malformed = F.household_payload(program["id"], household_name="Ladder")
    malformed.pop("household_size")

    validate_error(
        api.create_household(malformed, headers=NO_HEADERS), E.ERR_MISSING_AUTH_HEADERS, 401
    )
    validate_error(
        api.create_household(malformed, headers=make_headers(COORDINATOR_USER_ID, "Auditor")),
        E.ERR_UNKNOWN_ROLE,
        401,
    )
    validate_error(
        api.create_household(malformed, headers=OFFICER), E.ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(api.create_household(malformed, headers=COORDINATOR), E.ERR_VALIDATION, 422)

    _, meta = validate_paginated(
        api.list_households({"program_id": program["id"]}, headers=COORDINATOR)
    )
    assert meta["total_count"] == 0


def test_an_entity_backed_identity_must_resolve_and_may_only_address_its_own_seat(api):
    """A volunteer that does not exist, a volunteer reaching for somebody else's seat, and the owner.

    "For both entity-backed roles, an `X-User-ID` that matches no row of the backing
    entity is rejected with `ERR_IDENTITY_NOT_FOUND` (HTTP 403), and an identity that
    resolves but addresses a row belonging to somebody else is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Identity resolution comes first: the unknown id never reaches the ownership test.

    Design: Corner/rbac/entity_backed_identity_must_resolve_and_may_only_address_its_own_seat
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer_a = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    volunteer_b = X.setup_volunteer(api, program["id"], full_name="Omar Vance")
    shift = X.setup_open_shift(api, site["id"])
    unspent_version = X.shift_version(api, shift["id"])

    # An identity that matches no volunteer profile at all.
    validate_error(
        api.create_assignment(
            F.assignment_payload(shift["id"], unspent_version, volunteer_id=volunteer_a["id"]),
            headers=make_volunteer_headers(C.PROBE_IDENTITY_UUID),
        ),
        E.ERR_IDENTITY_NOT_FOUND,
        403,
    )
    # A real identity reaching for another profile's seat.
    validate_error(
        api.create_assignment(
            F.assignment_payload(shift["id"], unspent_version, volunteer_id=volunteer_a["id"]),
            headers=make_volunteer_headers(volunteer_b["id"]),
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # Neither refusal spent the shift version, so the owner's own request stands.
    seat = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], unspent_version, volunteer_id=volunteer_b["id"]),
            headers=make_volunteer_headers(volunteer_b["id"]),
        ),
        201,
    )
    assert seat["status"] == C.ASSIGNMENT_RESERVED
    assert seat["volunteer_id"] == volunteer_b["id"]

    validate_error(
        api.cancel_assignment(
            seat["id"],
            F.cancellation_payload(cancellation_reason="Tried to release a seat that is not mine"),
            headers=make_volunteer_headers(volunteer_a["id"]),
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    still_held = validate_success(api.get_assignment(seat["id"], headers=CREW_LEAD))
    assert still_held["status"] == C.ASSIGNMENT_RESERVED

    released = validate_success(
        api.cancel_assignment(
            seat["id"],
            F.cancellation_payload(cancellation_reason="Family emergency, cannot attend the build day"),
            headers=make_volunteer_headers(volunteer_b["id"]),
        )
    )
    assert released["status"] == C.ASSIGNMENT_CANCELLED

    _, meta = validate_paginated(api.list_assignments({"shift_id": shift["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 1
