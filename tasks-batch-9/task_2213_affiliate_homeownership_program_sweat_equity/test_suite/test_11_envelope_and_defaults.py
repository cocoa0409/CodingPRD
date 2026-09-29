"""Response envelopes, declared defaults, payload domains, and states at birth."""

import uuid

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, COORDINATOR, CREW_LEAD

_BAKARI = {
    "household_name": "Bakari",
    "household_size": 2,
    "current_bedroom_count": 2,
    "habitability_deficiency_count": 1,
    "self_reported_annual_income_cents": 3_000_000,
    "self_reported_housing_cost_cents": 60_000,
    "monthly_debt_payment_cents": 30_000,
    "credit_score": 640,
    "on_time_housing_payment_months": 24,
}
_COSTA = {
    "household_name": "Costa",
    "household_size": 3,
    "current_bedroom_count": 1,
    "habitability_deficiency_count": 2,
    "self_reported_annual_income_cents": 3_300_000,
    "self_reported_housing_cost_cents": 120_000,
    "monthly_debt_payment_cents": 20_000,
    "credit_score": 660,
    "on_time_housing_payment_months": 30,
}


def test_an_intake_returns_an_object_envelope_with_every_system_field_at_its_opening_value(api):
    """The 201 body is the whole opening posture of a family's file.

    "The new file opens with `selection_status` of `DRAFT`, `partnership_readiness`
    of `NOT_READY`, `documentation_status` of `INCOMPLETE`, and
    `adult_occupant_count` of 1. Everything computed is empty at this point:
    `verified_annual_income_cents` and `verified_housing_cost_cents` are null,
    `need_score`, `ability_to_pay_score`, `willingness_score`,
    `composite_selection_score`, `score_basis`, and `sweat_equity_required_hours`
    are null, `sweat_equity_credited_hours` and `family_member_credited_hours` are
    0, `sweat_equity_satisfied` is false, and `closing_date` and
    `denial_reason_code` are null."

    The adult count of 1 is there before anybody is on the roster.

    Design: Corner/entities/household_intake_returns_object_envelope_with_initial_system_fields
    """
    program = X.setup_program(api)

    response = api.create_household(F.household_payload(program["id"]), headers=COORDINATOR)

    household = A.assert_object_envelope(response, 201)
    # A server-minted identifier, not an echo of anything the client sent.
    uuid.UUID(household["id"])
    assert household["program_id"] == program["id"]
    assert household["household_name"] == "Alvarez"
    assert household["selection_status"] == C.SELECTION_DRAFT
    assert household["partnership_readiness"] == C.READINESS_NOT_READY
    assert household["documentation_status"] == C.DOC_INCOMPLETE
    assert household["adult_occupant_count"] == 1
    for field in (
        "verified_annual_income_cents",
        "verified_housing_cost_cents",
        "need_score",
        "ability_to_pay_score",
        "willingness_score",
        "composite_selection_score",
        "score_basis",
        "sweat_equity_required_hours",
        "closing_date",
        "denial_reason_code",
    ):
        assert household[field] is None, field
    A.assert_hours_equal(household["sweat_equity_credited_hours"], 0.0)
    A.assert_hours_equal(household["family_member_credited_hours"], 0.0)
    assert household["sweat_equity_satisfied"] is False

    rows, meta = validate_paginated(
        api.list_members({"household_id": household["id"]}, headers=COORDINATOR)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """Four different creates leave their optional fields out and get the documented values.

    "`sweat_equity_base_hours_required` is the hour requirement placed on a partner
    household with a single adult occupant; it defaults to 300 hours and may be
    anywhere from 0 through 500 hours carried to two decimal places.
    `committee_quorum` is the number of distinct committee reviewers required *per
    scoring dimension* before a selection decision may be issued; it defaults to 3
    and may be set anywhere from 2 through 9."

    A member carries "an optional `is_adult_occupant` flag that defaults to false";
    a shift "an optional `required_trade_slots` count of skilled positions from 0
    through 10 that defaults to 0"; an award "an optional
    `restricted_to_in_kind_reporting` flag defaulting to false".

    Design: Corner/entities/optional_inputs_fall_back_to_declared_field_defaults
    """
    program = validate_success(
        api.create_program(
            {
                "affiliate_name": "Northgate Habitat",
                "service_area_code": "HAYS",
                "ami_median_income_cents": 6_000_000,
                "subsidy_pool_cents": 5_000_000,
            },
            headers=ADMIN,
        ),
        201,
    )
    assert program["sweat_equity_base_hours_required"] == C.DEFAULT_SWEAT_EQUITY_BASE_HOURS
    assert program["committee_quorum"] == C.DEFAULT_COMMITTEE_QUORUM
    assert program["status"] == C.PROGRAM_STATUS_ACTIVE
    assert program["donated_material_fmv_cents"] == 0
    assert program["households_served_count"] == 0
    A.assert_pool_state(
        program,
        pool_cents=5_000_000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=5_000_000,
        posture=C.POSTURE_OPEN,
    )

    household = X.setup_household(api, program["id"])
    member = validate_success(
        api.create_member(
            {
                "household_id": household["id"],
                "full_name": "Mateo Alvarez",
                "relationship": C.RELATIONSHIP_DEPENDENT,
                "birth_date": "2014-05-02T00:00:00.000Z",
            },
            headers=COORDINATOR,
        ),
        201,
    )
    assert member["is_adult_occupant"] is False
    assert member["status"] == C.MEMBER_ACTIVE
    A.assert_hours_equal(member["credited_hours_to_date"], 0.0)

    site = X.setup_ready_site(api, program["id"])
    shift = validate_success(
        api.create_shift(
            F.shift_payload(
                site["id"],
                start_at="2026-08-05T08:00:00.000Z",
                end_at="2026-08-05T12:00:00.000Z",
                volunteer_slots=4,
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert shift["required_trade_slots"] == 0
    assert shift["required_trade"] is None
    assert shift["status"] == C.SHIFT_SCHEDULED
    assert shift["duration_hours"] == 4.0
    assert shift["confirmed_general_count"] == 0
    assert shift["confirmed_trade_count"] == 0
    assert shift["fill_ratio"] == 0
    assert shift["safety_briefing_completed"] is False

    award = validate_success(
        api.create_grant_award(
            F.grant_payload(
                program["id"],
                award_code="G-2026-01",
                donor_name="Cedar Foundation",
                amount_cents=2_500_000,
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-08-31T00:00:00.000Z",
                households_served_target=3,
            ),
            headers=ADMIN,
        ),
        201,
    )
    assert award["restricted_to_in_kind_reporting"] is False
    assert award["status"] == C.GRANT_OPEN


def test_client_supplied_system_fields_never_become_the_stored_row(api):
    """An intake that tries to award itself a selection is either refused or ignored.

    The opening posture of a file is the server's to write: "The new file opens with
    `selection_status` of `DRAFT`, `partnership_readiness` of `NOT_READY`,
    `documentation_status` of `INCOMPLETE`, and `adult_occupant_count` of 1", and
    the scores are null until screening computes them. A body carrying `SELECTED`,
    `VERIFIED`, a need score, an adult count and a version may be rejected as
    malformed, but it may never be stored.

    Design: Corner/entities/household_create_system_and_computed_client_input_ignored
    """
    program = X.setup_program(api)
    payload = F.household_payload(
        program["id"],
        household_name="Okafor",
        household_size=3,
        current_bedroom_count=1,
        habitability_deficiency_count=2,
        self_reported_annual_income_cents=3_600_000,
        self_reported_housing_cost_cents=150_000,
        monthly_debt_payment_cents=30_000,
        credit_score=700,
        on_time_housing_payment_months=36,
        selection_status=C.SELECTION_SELECTED,
        documentation_status=C.DOC_VERIFIED,
        need_score=100,
        adult_occupant_count=9,
        version=77,
    )

    response = api.create_household(payload, headers=COORDINATOR)

    if response.status_code == 422:
        validate_error(response, E.ERR_VALIDATION, 422)
        _, meta = validate_paginated(
            api.list_households({"program_id": program["id"]}, headers=COORDINATOR)
        )
        assert meta["total_count"] == 0
        return

    household = validate_success(response, 201)
    assert household["selection_status"] == C.SELECTION_DRAFT
    assert household["documentation_status"] == C.DOC_INCOMPLETE
    assert household["need_score"] is None
    assert household["adult_occupant_count"] == 1
    assert household["version"] != 77
    assert household["created_at"] == C.INITIAL_CLOCK

    reread = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert reread["selection_status"] == C.SELECTION_DRAFT
    assert reread["documentation_status"] == C.DOC_INCOMPLETE
    assert reread["need_score"] is None
    assert reread["adult_occupant_count"] == 1
    assert reread["version"] != 77


def test_the_household_window_slides_and_the_status_filter_narrows_it(api):
    """Two windows partition the same three rows, and a filter counts before windowing.

    "`limit` defaults to 10, may not be smaller than 1, and may not be larger than
    100; `offset` defaults to 0 and may not be negative." And: "The `meta` block of
    a list response carries `limit`, `offset`, `total_count` (the number of rows
    matching the filters before the window is applied) and `has_more` (true when
    rows remain beyond the current window)."

    Design: Corner/entities/household_list_pagination_window_and_status_filter
    """
    program = X.setup_program(api)
    alvarez = X.setup_household(api, program["id"])
    bakari = X.setup_household(api, program["id"], **_BAKARI)
    costa = X.setup_household(api, program["id"], **_COSTA)
    X.add_member(api, costa["id"], full_name="Nina Costa", birth_date="1990-01-04T00:00:00.000Z")
    X.submit_household(api, costa["id"])

    first = A.assert_pagination_meta(
        api.list_households({"program_id": program["id"], "limit": 2, "offset": 0}, headers=COORDINATOR),
        expected_limit=2,
        expected_offset=0,
        expected_total=3,
        expected_has_more=True,
    )
    assert len(first) == 2
    second = A.assert_pagination_meta(
        api.list_households({"program_id": program["id"], "limit": 2, "offset": 2}, headers=COORDINATOR),
        expected_limit=2,
        expected_offset=2,
        expected_total=3,
        expected_has_more=False,
    )
    assert len(second) == 1

    windowed = [row["id"] for row in first] + [row["id"] for row in second]
    assert sorted(windowed) == sorted([alvarez["id"], bakari["id"], costa["id"]])
    assert len(set(windowed)) == 3

    drafts, draft_meta = validate_paginated(
        api.list_households(
            {"program_id": program["id"], "selection_status": C.SELECTION_DRAFT}, headers=COORDINATOR
        )
    )
    assert draft_meta["total_count"] == 2
    draft_ids = {row["id"] for row in drafts}
    assert costa["id"] not in draft_ids
    assert draft_ids == {alvarez["id"], bakari["id"]}


def test_a_limit_past_the_ceiling_a_limit_below_the_floor_and_a_negative_offset_are_refused(api):
    """The pagination window has three edges, and all three are payload-shape failures.

    "A `limit` outside the inclusive range of 1 through 100, or a negative `offset`,
    is a payload-shape failure and is rejected with `ERR_VALIDATION` (HTTP 422)."
    An unparameterised call takes the documented defaults instead.

    Design: Corner/entities/pagination_limit_above_maximum_and_negative_offset_rejected
    """
    program = X.setup_program(api)
    X.setup_household(api, program["id"])

    validate_error(
        api.list_households({"program_id": program["id"], "limit": 101}, headers=COORDINATOR),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.list_households({"program_id": program["id"], "limit": 0}, headers=COORDINATOR),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.list_households({"program_id": program["id"], "offset": -1}, headers=COORDINATOR),
        E.ERR_VALIDATION,
        422,
    )

    rows = A.assert_pagination_meta(
        api.list_households(headers=COORDINATOR),
        expected_limit=C.DEFAULT_LIMIT,
        expected_offset=C.DEFAULT_OFFSET,
        expected_total=1,
        expected_has_more=False,
    )
    assert len(rows) == 1


def test_enum_and_numeric_domains_are_enforced_before_anything_is_written(api):
    """Five malformed bodies across three entities, and not one row to show for them.

    Intake bounds the family: "the `household_size` counting every person who will
    occupy the home (at least 1, at most 12) ... the tri-merge middle `credit_score`
    (300 through 850)". A member's `relationship` is "one of `APPLICANT`,
    `CO_APPLICANT`, `DEPENDENT`, `EXTENDED_FAMILY`, or `FRIEND_OF_FAMILY`". A shift
    carries "a `start_at` and an `end_at` where the end is strictly after the start
    and the span is at most 10 hours".

    Design: Corner/entities/enum_and_numeric_domain_violations_are_rejected
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    site = X.setup_ready_site(api, program["id"])

    validate_error(
        api.create_household(
            F.household_payload(program["id"], household_name="Too Large", household_size=13),
            headers=COORDINATOR,
        ),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.create_household(
            F.household_payload(program["id"], household_name="Thin File", credit_score=290),
            headers=COORDINATOR,
        ),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.create_member(
            F.member_payload(household["id"], full_name="Kin Alvarez", relationship="COUSIN"),
            headers=COORDINATOR,
        ),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.create_shift(
            F.shift_payload(
                site["id"], start_at="2026-08-05T12:00:00.000Z", end_at="2026-08-05T08:00:00.000Z"
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.create_shift(
            F.shift_payload(
                site["id"], start_at="2026-08-06T08:00:00.000Z", end_at="2026-08-06T19:00:00.000Z"
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_VALIDATION,
        422,
    )

    _, household_meta = validate_paginated(
        api.list_households({"program_id": program["id"]}, headers=COORDINATOR)
    )
    assert household_meta["total_count"] == 1
    _, member_meta = validate_paginated(
        api.list_members({"household_id": household["id"]}, headers=COORDINATOR)
    )
    assert member_meta["total_count"] == 0
    _, shift_meta = validate_paginated(
        api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD)
    )
    assert shift_meta["total_count"] == 0


def test_a_create_missing_a_required_field_leaves_no_row_behind(api):
    """A program without its income denominator and a site without its appraisal.

    A program is opened by "declaring the affiliate's `affiliate_name` (1 to 120
    characters, unique across programs), the `service_area_code` of the county it
    builds in (2 to 10 uppercase characters), the `ami_median_income_cents` that
    will serve as the denominator of every income-band test". A site records "the
    `acquisition_cost_cents` the affiliate paid for the lot, and the
    `appraised_value_cents` the home is expected to be worth as completed, which
    must be at least 1,000,000 cents". Priority 8 requires "required fields
    present".

    Design: Corner/entities/program_create_missing_required_field_rejected
    """
    program = X.setup_program(api)

    validate_error(
        api.create_program(
            {
                "affiliate_name": "Missing AMI Habitat",
                "service_area_code": "BASTROP",
                "subsidy_pool_cents": 5_000_000,
                "sweat_equity_base_hours_required": 12,
                "committee_quorum": 2,
            },
            headers=ADMIN,
        ),
        E.ERR_VALIDATION,
        422,
    )
    validate_error(
        api.create_build_site(
            {
                "program_id": program["id"],
                "parcel_number": "P-2002",
                "street_address": "44 Oak St",
                "acquisition_cost_cents": 4_000_000,
            },
            headers=ADMIN,
        ),
        E.ERR_VALIDATION,
        422,
    )

    _, program_meta = validate_paginated(
        api.list_programs({"service_area_code": "BASTROP"}, headers=ADMIN)
    )
    assert program_meta["total_count"] == 0
    _, site_meta = validate_paginated(api.list_build_sites({"program_id": program["id"]}, headers=ADMIN))
    assert site_meta["total_count"] == 0


def test_every_new_row_is_born_in_its_declared_initial_state(api):
    """Four rows, five state dimensions, and no transition call anywhere.

    A household's two dimensions start apart: "The new file opens with
    `selection_status` of `DRAFT`, `partnership_readiness` of `NOT_READY`". A site
    starts on paper however much was paid for it: "A new site opens in `RAW_LAND`
    readiness with a `CLEAR` safety posture, with `title_cleared`,
    `environmental_cleared`, and `utilities_cleared` all false, with
    `assigned_household_id` and `pre_hold_readiness_status` null". A shift "opens in
    `SCHEDULED` status" — opening it is a separate hop — and "A seat opens in
    `RESERVED` status with `checked_in_at` null".

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    program = X.setup_program(api)
    host_site = X.setup_ready_site(
        api, program["id"], parcel_number="P-2002", street_address="44 Oak St"
    )
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")

    household = validate_success(
        api.create_household(F.household_payload(program["id"]), headers=COORDINATOR), 201
    )
    A.assert_two_state_dimensions(household, C.SELECTION_DRAFT, C.READINESS_NOT_READY)

    site = validate_success(
        api.create_build_site(F.build_site_payload(program["id"]), headers=ADMIN), 201
    )
    assert site["readiness_status"] == C.SITE_RAW_LAND
    assert site["title_cleared"] is False
    assert site["environmental_cleared"] is False
    assert site["utilities_cleared"] is False
    assert site["safety_posture"] == C.POSTURE_CLEAR
    assert site["pre_hold_readiness_status"] is None

    shift = validate_success(api.create_shift(F.shift_payload(host_site["id"]), headers=CREW_LEAD), 201)
    assert shift["status"] == C.SHIFT_SCHEDULED

    assignment = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], shift["version"], volunteer_id=volunteer["id"]),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert assignment["status"] == C.ASSIGNMENT_RESERVED
    assert assignment["checked_in_at"] is None
