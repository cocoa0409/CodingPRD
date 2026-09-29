"""Role denials, anonymous access, per-user segregation and role-scoped reads."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_index,
    assert_line_states,
    assert_pay_factor,
    assert_project_states,
    assert_scenario_funding,
)
from test_helpers.constants import (
    AREA_MAPLE,
    DEFAULT_CLOCK,
    FUNDING_STANDARD,
    MAPLE_TOTAL,
    PCI_MAPLE_MODEL,
    SEG_MAPLE,
    SOURCE_SURVEY_MEASURED,
    UNCOMMITTED_AFTER_MAPLE_AWARD,
)
from test_helpers.factories import (
    acceptance_decision_payload,
    award_payload,
    schedule_notice_payload,
    segment_payload,
)
from test_helpers.test_users import (
    ENGINEER,
    INSPECTOR_ACCEPTOR,
    INSPECTOR_DECIDER,
    INSPECTOR_DECIDER_USER_ID,
    INSPECTOR_WITNESS,
    INSPECTOR_WITNESS_USER_ID,
    OFFICER,
    OFFICER_ADOPT_USER_ID,
    OFFICER_ADOPTER,
    OFFICER_AWARDER,
    RESIDENT,
)

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
ANONYMOUS: dict = {}
OVER_MAX_LIMIT = 101
FUTURE_CLOCK = "2027-01-01T00:00:00Z"

PASS_DENSITY_PCT = 96.0
BONUS_IRI = 60.0
DESIGN_THICKNESS_IN = 2.00
BONUS_PAY_FACTOR = 1.0200
WITNESS_NOTE = "I cored it and it passed"
DECIDER_NOTE = "reviewed cores and QA report"

NOTICE_START = "2026-09-01T00:00:00Z"
NOTICE_END = "2026-09-30T00:00:00Z"
ACCESS_MAINTAINED = "MAINTAINED"


# ----------------------------------------------------------------------
# Role denials on writes
# ----------------------------------------------------------------------


def test_a_resident_may_read_the_network_but_may_not_load_a_segment(api):
    """The write is refused before the body is ever considered, and nothing is created.

    PRD: "A `Resident` is a member of the public who may report a pavement complaint
    and read the public-facing network, project-line and complaint views."

    PRD: "If the declared role is not one of the six recognised roles, or is
    recognised but not permitted for the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    PRD: "The network can be listed with filters on `geo_zone`, `functional_class` and
    `condition_band`, which is how an engineer assembles the candidate list for a
    geographic bundle, and every role in the system may read the inventory."

    PRD: "A `PavementEngineer` owns the technical program: pavement inventory loading,
    survey campaigns and quality control of distress data, survey sealing and candidate
    generation, treatment overrides, contractor registration, project scoping and
    bundling, resident notices, cut-permit decisions, and complaint triage and
    closure."

    The body is valid in every respect, so only the caller's role can be what
    answered — and the identical body from the engineer is then accepted.

    Design: Corner/rbac/resident_cannot_create_a_network_segment
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    body = segment_payload(SEG_MAPLE)

    validate_error(
        api.create_segment(body, RESIDENT), ApiErrorId.UNAUTHORIZED, 403
    )

    _rows, meta = validate_paginated(
        api.list_segments(RESIDENT, {"geo_zone": "Z1", "limit": 100})
    )
    assert meta["total_count"] == 0

    created = validate_success(api.create_segment(body, ENGINEER), 201)
    assert_area(created["area_sy"], AREA_MAPLE)
    assert_index(created["condition_index"], PCI_MAPLE_MODEL)


def test_the_engineer_who_owns_every_other_project_write_may_not_award(api):
    """Award is money, so it is refused by role even for the project's own author.

    PRD: "A `BudgetOfficer` owns the money: scenario adoption, manual allocations,
    award and award cancellation."

    PRD: "Awarding is a `BudgetOfficer` action that moves `delivery_status` from
    `BID_READY` to `AWARDED`, naming the `contractor_id` receiving the work and the
    `award_amount_cents` of the contract."

    PRD: "If the declared role is not one of the six recognised roles, or is
    recognised but not permitted for the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    The amount is exactly the estimate and the funding is untouched, so no tolerance,
    funding, standing or capacity rule can be what refused it.

    Design: Corner/rbac/pavement_engineer_cannot_award_a_project
    """
    ctx = fixtures.maple_bid_ready(api)
    project_id = ctx["project"]["id"]
    body = award_payload(ctx["contractor"]["id"], MAPLE_TOTAL)

    validate_error(
        api.award_project(project_id, body, ENGINEER), ApiErrorId.UNAUTHORIZED, 403
    )

    refused = fixtures.read_project(api, project_id)
    assert refused["delivery_status"] == "BID_READY"
    assert refused["award_amount_cents"] is None
    assert_scenario_funding(
        fixtures.read_scenario(api, ctx["scenario"]["id"]), FUNDING_STANDARD, 0, FUNDING_STANDARD
    )

    awarded = validate_success(api.award_project(project_id, body, OFFICER_AWARDER))
    assert awarded["delivery_status"] == "AWARDED"


def test_an_inspector_may_not_declare_the_contractors_substantial_completion(api):
    """Completion is the firm's own assertion, so even the future signer is refused.

    PRD: "A `Contractor` is the awarded paving firm and may only declare substantial
    completion on its own project."

    PRD: "An `Inspector` owns pavement quality acceptance: submitting test
    measurements, deciding tests and signing final project acceptance."

    PRD: "If the declared role is not one of the six recognised roles, or is
    recognised but not permitted for the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    PRD: "The transition stamps `substantial_completion_at` from the logical clock and
    computes `days_late` as the number of whole days from `planned_end_date` to
    `substantial_completion_at`, floored at zero — an early or on-time finish records
    zero."

    PRD: "The composite score is 0.45 times the quality component plus 0.30 times the
    schedule component plus 0.25 times the remediation component, rounded to one
    decimal place."

    The refusal is a role refusal rather than an ownership one, and no lateness is
    recorded against the firm.

    Design: Corner/rbac/inspector_cannot_report_substantial_completion
    """
    ctx = fixtures.maple_in_construction(api)
    project_id = ctx["project"]["id"]

    validate_error(
        api.substantial_completion(project_id, {}, INSPECTOR_ACCEPTOR),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    project = fixtures.read_project(api, project_id)
    assert project["delivery_status"] == "IN_CONSTRUCTION"
    assert project["substantial_completion_at"] is None
    assert project["days_late"] == 0

    scorecard = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )
    assert scorecard["interim_performance_score"] == 100.0
    assert scorecard["interim_schedule_component"] == 100.00
    assert scorecard["days_late_total"] == 0


# ----------------------------------------------------------------------
# Authentication precedes every other check
# ----------------------------------------------------------------------


def test_a_header_less_request_is_refused_before_the_role_and_shape_checks(api):
    """Even the all-roles clock endpoint and an out-of-bounds listing answer 401 first.

    PRD: "Every request — including the logical-clock endpoint — must carry two
    headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act."

    PRD: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    PRD: "Both identity headers present and non-empty, else `ERR_UNAUTHENTICATED`."

    PRD: "A `limit` outside the range 1 through 100, or a negative `offset`, is a
    malformed request and yields `ERR_INVALID_REQUEST`."

    PRD: "An administrative test-driving capability sets the clock to a supplied
    `current_utc` instant and is open to all six roles."

    A caller cannot probe the pagination bounds anonymously: the out-of-bounds page
    size never reaches the shape check.

    Design: Corner/rbac/request_missing_the_x_user_id_header_returns_unauthenticated
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    segment = fixtures.create_segment(api, SEG_MAPLE)

    validate_error(
        api.set_clock_raw({"current_utc": FUTURE_CLOCK}, ANONYMOUS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_segments(ANONYMOUS, {"limit": OVER_MAX_LIMIT}),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    still_there = fixtures.read_segment(api, segment["id"])
    assert_index(still_there["condition_index"], PCI_MAPLE_MODEL)


# ----------------------------------------------------------------------
# Segregation of duties is per user, not per role
# ----------------------------------------------------------------------


def test_the_officer_who_adopted_the_program_may_not_award_from_it(api):
    """Same role, same body, same target: only the user id distinguishes the two calls.

    PRD: "The budget officer whose `X-User-ID` was recorded as the funding scenario's
    `adopted_by_user_id` may not award a project from that scenario."

    PRD: "Two segregation-of-duties rules follow from those recorded identifiers, and
    both reject with `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    PRD: "Recall from §2.1 that the officer who adopted the scenario may not award
    from it."

    Design: Corner/rbac/award_by_the_officer_who_adopted_the_scenario_rejected
    """
    ctx = fixtures.maple_bid_ready(api)
    project_id = ctx["project"]["id"]
    scenario_id = ctx["scenario"]["id"]
    body = award_payload(ctx["contractor"]["id"], MAPLE_TOTAL)
    assert ctx["scenario"]["adopted_by_user_id"] == OFFICER_ADOPT_USER_ID

    validate_error(
        api.award_project(project_id, body, OFFICER_ADOPTER),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    refused = fixtures.read_project(api, project_id)
    assert refused["delivery_status"] == "BID_READY"
    assert refused["award_amount_cents"] is None
    assert refused["contractor_id"] is None
    assert_scenario_funding(
        validate_success(api.get_scenario(scenario_id, OFFICER)),
        FUNDING_STANDARD,
        0,
        FUNDING_STANDARD,
    )

    awarded = validate_success(api.award_project(project_id, body, OFFICER_AWARDER))
    assert awarded["delivery_status"] == "AWARDED"
    assert_scenario_funding(
        validate_success(api.get_scenario(scenario_id, OFFICER)),
        FUNDING_STANDARD,
        MAPLE_TOTAL,
        UNCOMMITTED_AFTER_MAPLE_AWARD,
    )


def test_the_witness_inspector_may_not_decide_the_test_they_witnessed(api):
    """Four eyes on acceptance: the numbers pass, the actor does not.

    PRD: "The inspector who witnessed the coring of an acceptance test may not be the
    inspector who decides that test, and may not be the inspector who signs the
    enclosing project's final acceptance."

    PRD: "Every decision requires `test_status` to be `SUBMITTED`, else
    `ERR_TEST_ALREADY_DECIDED`, and requires the deciding `X-User-ID` to differ from
    the test's `witness_inspector_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "Otherwise `computed_pay_factor` is the product of the three factors, capped
    at 1.02, rounded to four decimal places — the cap applies after multiplication, so
    a test with bonus smoothness, full density and full thickness yields exactly
    1.0200 — and `computed_outcome` is `PASS` when the pay factor is at least 0.95 and
    `FAIL` otherwise."

    PRD: "Every test starts with `test_status` `SUBMITTED`, `decided_by_user_id` null
    and `decision_note` null, and each submission increments the line's `test_count`."

    PRD: "A `PASS` decision moves the test to `PASSED`, records `decided_by_user_id`
    and `decision_note`, moves the line's `work_state` from `IN_PROGRESS` to
    `WORK_COMPLETE` provided the decided test carries the highest `test_round` on that
    line, and copies the test's `computed_pay_factor` onto the line's `pay_factor`."

    PRD: "The project's quality dimension may then bubble from `TESTING` to
    `QUALITY_ACCEPTED`, which happens exactly when `open_remediation_count` is zero and
    every non-removed line on the project has reached `WORK_COMPLETE`; reaching
    `QUALITY_ACCEPTED` is what unlocks final acceptance."

    Design: Corner/rbac/witness_inspector_cannot_decide_the_test_they_witnessed
    """
    ctx = fixtures.maple_in_construction(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    submitted = fixtures.submit_test(
        api,
        line_id,
        core_density_pct=PASS_DENSITY_PCT,
        iri_in_per_mi=BONUS_IRI,
        thickness_in=DESIGN_THICKNESS_IN,
        witness=INSPECTOR_WITNESS_USER_ID,
    )
    assert_pay_factor(submitted, BONUS_PAY_FACTOR, "PASS")
    assert submitted["witness_inspector_user_id"] == INSPECTOR_WITNESS_USER_ID

    validate_error(
        api.decide_acceptance_test(
            submitted["id"], acceptance_decision_payload("PASS", WITNESS_NOTE), INSPECTOR_WITNESS
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    undecided = validate_success(api.get_acceptance_test(submitted["id"], INSPECTOR_WITNESS))
    assert undecided["test_status"] == "SUBMITTED"
    assert undecided["decided_by_user_id"] is None

    decided = validate_success(
        api.decide_acceptance_test(
            submitted["id"], acceptance_decision_payload("PASS", DECIDER_NOTE), INSPECTOR_DECIDER
        )
    )
    assert decided["test_status"] == "PASSED"
    assert decided["decided_by_user_id"] == INSPECTOR_DECIDER_USER_ID

    line = fixtures.read_line(api, line_id)
    assert_line_states(line, "WORK_COMPLETE", "DELIVERED")
    assert line["pay_factor"] == BONUS_PAY_FACTOR
    assert_project_states(
        fixtures.read_project(api, ctx["project"]["id"]),
        "IN_CONSTRUCTION",
        "QUALITY_ACCEPTED",
    )


# ----------------------------------------------------------------------
# The resident's read surface stops at the street
# ----------------------------------------------------------------------


def test_a_resident_reads_the_street_facing_line_but_not_the_money_behind_it(api):
    """One FK chain, two answers: the line and its segment are public, the program is not.

    PRD: "A `Resident` is a member of the public who may report a pavement complaint
    and read the public-facing network, project-line and complaint views."

    PRD: "| GET | `/pavement/project-segments/{id}` | Read one project line |
    PavementEngineer, BudgetOfficer, UtilityCoordinator, Inspector, Contractor,
    Resident |"

    PRD: "| GET | `/pavement/budget-scenarios/{id}` | Read one budget scenario |
    BudgetOfficer, PavementEngineer, Inspector |"

    PRD: "| GET | `/pavement/projects/{id}` | Read one resurfacing project |
    PavementEngineer, BudgetOfficer, UtilityCoordinator, Inspector, Contractor |"

    PRD: "`SCHEDULE` moves `notice_state` from `PENDING` to `SCHEDULED` and publishes
    the restriction: the engineer supplies `parking_restriction_start` and
    `parking_restriction_end` for the no-parking window, and a `driveway_access_plan`
    of `MAINTAINED` when driveways stay usable throughout, `LIMITED_NIGHTLY` when
    access is restored each night, or `BLOCKED_WITH_ALT` when access is blocked and an
    alternative is arranged."

    PRD: "**First**, for every accepted observation on the survey, the referenced
    segment's `condition_index` is overwritten with that observation's
    `measured_condition_index`, its `condition_index_source` is set to
    `SURVEY_MEASURED`, and its `condition_band` is recomputed from the new value."

    The project's own id is disclosed on the line the resident may read, and reading it
    is still refused — the grant is per endpoint, not per reachable row.

    Design: Corner/rbac/resident_read_of_a_line_allowed_but_scenario_read_forbidden
    """
    ctx = fixtures.maple_bid_ready(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    project_id = ctx["project"]["id"]
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    validate_success(
        api.notice(
            line_id,
            schedule_notice_payload(NOTICE_START, NOTICE_END, ACCESS_MAINTAINED),
            ENGINEER,
        )
    )

    line = validate_success(api.get_project_segment(line_id, RESIDENT))
    assert line["notice_state"] == "SCHEDULED"
    assert line["parking_restriction_start"].startswith("2026-09-01T00:00:00")
    assert line["driveway_access_plan"] == ACCESS_MAINTAINED
    assert line["project_id"] == project_id

    segment = validate_success(api.get_segment(segment_id, RESIDENT))
    assert segment["condition_index_source"] == SOURCE_SURVEY_MEASURED

    validate_error(
        api.get_scenario(ctx["scenario"]["id"], RESIDENT), ApiErrorId.UNAUTHORIZED, 403
    )
    validate_error(
        api.get_project(project_id, RESIDENT), ApiErrorId.UNAUTHORIZED, 403
    )
