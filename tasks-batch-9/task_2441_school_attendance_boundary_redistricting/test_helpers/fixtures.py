"""Setup builders: every precondition is constructed through the public API.

Each test starts against an empty database, so nothing here may assume a record
already exists. Composite builders return a plain dict of ids and records so a
test can pick out exactly the handles it needs.

Guarded writes (projection runs, assignments, program placements) carry an
expected-version token. Because each accepted write bumps the parent's version,
every builder here re-reads the parent immediately before the next guarded write
instead of caching a stale number.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adoption_payload,
    create_area_adjacency_payload,
    create_assignment_payload,
    create_comment_payload,
    create_housing_development_payload,
    create_planning_area_payload,
    create_projection_run_payload,
    create_scenario_payload,
    create_school_payload,
    create_study_payload,
    create_transfer_request_payload,
    program_placement,
    travel_option,
)
from .test_users import (
    TEST_USERS,
    make_guardian_headers,
)
from .types import ENTITLEMENT_LADDER

PLANNER = TEST_USERS["planner_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["officer_headers"]
GUARDIAN = TEST_USERS["guardian_headers"]

RIVERBEND_CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def set_clock(current_utc, client=api_client, headers=PLANNER):
    """Move the logical clock to ``current_utc``."""
    return get_success_data(client.set_current_utc(current_utc, headers))


def create_study(client=api_client, headers=PLANNER, **overrides) -> dict:
    """Create a boundary study in SETUP."""
    return get_success_data(
        client.create_study(create_study_payload(**overrides), headers), 201
    )


def create_school(study_id, client=api_client, headers=PLANNER, **overrides) -> dict:
    """Add one school to a study that is still in SETUP."""
    return get_success_data(
        client.create_school(study_id, create_school_payload(**overrides), headers), 201
    )


def create_planning_area(
    study_id, current_school_id, travel_options, client=api_client, headers=PLANNER, **overrides
) -> dict:
    """Add one planning area to a study that is still in SETUP."""
    return get_success_data(
        client.create_planning_area(
            create_planning_area_payload(
                study_id, current_school_id, travel_options, **overrides
            ),
            headers,
        ),
        201,
    )


def create_adjacency(
    area_id, neighbor_area_id, client=api_client, headers=PLANNER, **overrides
) -> dict:
    """Record one adjacency edge between two planning areas."""
    return get_success_data(
        client.create_area_adjacency(
            create_area_adjacency_payload(area_id, neighbor_area_id, **overrides), headers
        ),
        201,
    )


def lock_study(study_id, client=api_client, headers=PLANNER) -> dict:
    """Freeze the study inventory, moving it out of SETUP."""
    return get_success_data(client.lock_study_data(study_id, headers))


def study_version(study_id, client=api_client, headers=PLANNER) -> int:
    """Read the study's current version for a guarded write."""
    return get_success_data(client.get_study(study_id, headers))["version"]


def scenario_version(scenario_id, client=api_client, headers=PLANNER) -> int:
    """Read the scenario's current version for a guarded write."""
    return get_success_data(client.get_scenario(scenario_id, headers))["version"]


def create_housing_development(area_id, client=api_client, headers=PLANNER, **overrides) -> dict:
    """Add one housing development to a planning area."""
    return get_success_data(
        client.create_housing_development(
            area_id, create_housing_development_payload(**overrides), headers
        ),
        201,
    )


def advance_entitlement(development_id, to_status, client=api_client, headers=PLANNER) -> dict:
    """Advance a development one rung along the entitlement ladder."""
    return get_success_data(
        client.advance_entitlement(development_id, {"to_status": to_status}, headers)
    )


def advance_entitlement_to(
    development_id, target_status, from_status=None, client=api_client, headers=PLANNER
) -> dict:
    """Walk the entitlement ladder rung by rung until ``target_status`` is reached."""
    start = ENTITLEMENT_LADDER.index(from_status) if from_status else 0
    end = ENTITLEMENT_LADDER.index(target_status)
    record = None
    for status in ENTITLEMENT_LADDER[start + 1 : end + 1]:
        record = advance_entitlement(development_id, status, client, headers)
    return record


def create_projection_run(study_id, client=api_client, headers=PLANNER, **overrides) -> dict:
    """Run a projection, re-reading the study version first."""
    expected = overrides.pop(
        "expected_study_version", study_version(study_id, client, headers)
    )
    return get_success_data(
        client.create_projection_run(
            study_id, create_projection_run_payload(expected, **overrides), headers
        ),
        201,
    )


def create_scenario(
    study_id, projection_run_id, program_placements=None, client=api_client, headers=PLANNER, **overrides
) -> dict:
    """Create a boundary scenario in DRAFT."""
    return get_success_data(
        client.create_scenario(
            create_scenario_payload(
                study_id, projection_run_id, program_placements, **overrides
            ),
            headers,
        ),
        201,
    )


def assign_area(
    scenario_id, area_id, assigned_school_id, client=api_client, headers=PLANNER, **overrides
) -> dict:
    """Assign one area to one school, re-reading the scenario version first."""
    expected = overrides.pop(
        "expected_scenario_version", scenario_version(scenario_id, client, headers)
    )
    return get_success_data(
        client.create_assignment(
            create_assignment_payload(
                scenario_id, area_id, assigned_school_id, expected, **overrides
            ),
            headers,
        ),
        201,
    )


def assign_areas(scenario_id, pairs, client=api_client, headers=PLANNER) -> list:
    """Assign a sequence of ``(area_id, school_id)`` pairs in order."""
    return [
        assign_area(scenario_id, area_id, school_id, client, headers)
        for area_id, school_id in pairs
    ]


def replace_program_placements(
    scenario_id, placements, client=api_client, headers=PLANNER, **overrides
) -> dict:
    """Replace a scenario's program placements, re-reading its version first."""
    expected = overrides.pop(
        "expected_scenario_version", scenario_version(scenario_id, client, headers)
    )
    payload = {
        "program_placements": placements,
        "expected_scenario_version": expected,
    }
    payload.update(overrides)
    return get_success_data(client.replace_program_placements(scenario_id, payload, headers))


def submit_for_review(scenario_id, client=api_client, headers=PLANNER, **payload) -> dict:
    """Send a DRAFT scenario into review."""
    return get_success_data(
        client.submit_scenario_for_review(scenario_id, headers, payload or None)
    )


def open_engagement(study_id, client=api_client, headers=COORDINATOR) -> dict:
    """Open the public comment window on a study."""
    return get_success_data(client.open_engagement(study_id, headers))


def advance_to_board(scenario_id, client=api_client, headers=COORDINATOR, **payload) -> dict:
    """Send a reviewed scenario to the board."""
    return get_success_data(
        client.advance_scenario_to_board(scenario_id, headers, payload or None)
    )


def request_revision(scenario_id, cited_comment_ids, client=api_client, headers=COORDINATOR, **overrides) -> dict:
    """Return a scenario to its author for revision, citing comments."""
    payload = {"cited_comment_ids": list(cited_comment_ids)}
    payload.update(overrides)
    return get_success_data(client.request_scenario_revision(scenario_id, payload, headers))


def create_comment(scenario_id, client=api_client, headers=GUARDIAN, **overrides) -> dict:
    """File one public comment against a scenario."""
    return get_success_data(
        client.create_comment(create_comment_payload(scenario_id, **overrides), headers), 201
    )


def triage_comment(comment_id, theme, priority, client=api_client, headers=COORDINATOR) -> dict:
    """Assign a theme and priority to a submitted comment."""
    return get_success_data(
        client.triage_comment(comment_id, {"theme": theme, "priority": priority}, headers)
    )


def create_adoption(study_id, scenario_id, client=api_client, headers=BOARD, **overrides) -> dict:
    """Record a board vote adopting a scenario."""
    return get_success_data(
        client.create_adoption(
            create_adoption_payload(study_id, scenario_id, **overrides), headers
        ),
        201,
    )


def activate_adoption(adoption_id, client=api_client, headers=OFFICER) -> dict:
    """Put an adoption into effect. Only a TransferOfficer may do this."""
    return get_success_data(client.activate_adoption(adoption_id, headers))


def close_transfer_window(adoption_id, client=api_client, headers=OFFICER) -> dict:
    """Close an adoption's transfer window."""
    return get_success_data(client.close_transfer_window(adoption_id, headers))


def create_transfer_request(
    adoption_id, area_id, requested_school_id, client=api_client, headers=None, **overrides
) -> dict:
    """File one transfer request as a guardian."""
    return get_success_data(
        client.create_transfer_request(
            create_transfer_request_payload(
                adoption_id, area_id, requested_school_id, **overrides
            ),
            headers or GUARDIAN,
        ),
        201,
    )


def decide_transfer(request_id, decision, client=api_client, headers=OFFICER, **overrides) -> dict:
    """Decide one transfer request."""
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(client.decide_transfer_request(request_id, payload, headers))


# ---------------------------------------------------------------------------
# Generic study builder — for districts other than the shared Riverbend set
# ---------------------------------------------------------------------------
def setup_study_with_inventory(
    study_payload=None,
    school_payloads=(),
    area_builders=(),
    adjacency_specs=(),
    clock=RIVERBEND_CLOCK,
    lock=True,
    client=api_client,
    headers=PLANNER,
) -> dict:
    """Build a study plus its schools, areas and adjacency edges from scratch.

    ``school_payloads`` are keyword-override dicts for ``create_school_payload``;
    each must carry a distinct ``name``. ``area_builders`` are callables that
    receive ``school_ids`` (school name -> id) and return keyword-override dicts
    carrying at least ``area_code``, ``current_school_id`` and ``travel_options``.
    ``adjacency_specs`` are ``(area_code, neighbor_area_code)`` pairs, optionally
    with a third element giving ``shared_boundary_length_ft``.
    """
    if clock is not None:
        set_clock(clock, client, headers)
    study = create_study(client, headers, **(study_payload or {}))

    schools = {}
    for overrides in school_payloads:
        school = create_school(study["id"], client, headers, **overrides)
        schools[school["name"]] = school
    school_ids = {name: record["id"] for name, record in schools.items()}

    areas = {}
    for builder in area_builders:
        overrides = builder(school_ids)
        current_school_id = overrides.pop("current_school_id")
        travel_options = overrides.pop("travel_options")
        area = create_planning_area(
            study["id"], current_school_id, travel_options, client, headers, **overrides
        )
        areas[area["area_code"]] = area
    area_ids = {code: record["id"] for code, record in areas.items()}

    adjacencies = []
    for spec in adjacency_specs:
        code, neighbor_code = spec[0], spec[1]
        extra = {"shared_boundary_length_ft": spec[2]} if len(spec) > 2 else {}
        adjacencies.append(
            create_adjacency(
                area_ids[code], area_ids[neighbor_code], client, headers, **extra
            )
        )

    if lock:
        study = lock_study(study["id"], client, headers)

    return {
        "study": study,
        "study_id": study["id"],
        "schools": schools,
        "school_ids": school_ids,
        "areas": areas,
        "area_ids": area_ids,
        "adjacencies": adjacencies,
    }


# ---------------------------------------------------------------------------
# The shared Riverbend ladder
#
# Every stage builds on the one above it and returns the same context dict,
# extended with the records that stage created.
# ---------------------------------------------------------------------------
RIVERBEND_SCHOOLS = (
    {
        "name": "Cedar Elementary",
        "level": "ELEMENTARY",
        "core_capacity_seats": 500,
        "portable_capacity_seats": 40,
        "program_types": ["DUAL_LANGUAGE"],
    },
    {
        "name": "Birch Elementary",
        "level": "ELEMENTARY",
        "core_capacity_seats": 400,
        "portable_capacity_seats": 0,
    },
)


def _riverbend_areas():
    def a01(school_ids):
        return {
            "area_code": "A-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Cedar Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 90,
            "ell_student_count": 40,
            "median_household_income_usd": 78000,
            "annual_absorption_cap_units": 120,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 0.6, 10, True),
                travel_option(school_ids["Birch Elementary"], 2.2, 22, False),
            ],
        }

    def a02(school_ids):
        return {
            "area_code": "A-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Cedar Elementary"],
            "resident_student_count": 200,
            "frl_student_count": 100,
            "ell_student_count": 30,
            "median_household_income_usd": 52000,
            "annual_absorption_cap_units": 150,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 1.4, 9, False),
                travel_option(school_ids["Birch Elementary"], 0.8, 12, True),
            ],
        }

    def a03(school_ids):
        return {
            "area_code": "A-03",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Birch Elementary"],
            "resident_student_count": 150,
            "frl_student_count": 30,
            "ell_student_count": 10,
            "median_household_income_usd": 96000,
            "annual_absorption_cap_units": 90,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 3.0, 26, False),
                travel_option(school_ids["Birch Elementary"], 0.9, 14, True),
            ],
        }

    return (a01, a02, a03)


def riverbend_area_builders():
    """The three canonical Riverbend area builders, for reuse with a variant study."""
    return _riverbend_areas()


def _shorthand(ctx: dict) -> dict:
    """Add the short handles the tests read most often."""
    ctx["cedar"] = ctx["schools"]["Cedar Elementary"]
    ctx["cedar_id"] = ctx["cedar"]["id"]
    ctx["birch"] = ctx["schools"]["Birch Elementary"]
    ctx["birch_id"] = ctx["birch"]["id"]
    ctx["a1"] = ctx["areas"]["A-01"]
    ctx["a1_id"] = ctx["a1"]["id"]
    ctx["a2"] = ctx["areas"]["A-02"]
    ctx["a2_id"] = ctx["a2"]["id"]
    ctx["a3"] = ctx["areas"]["A-03"]
    ctx["a3_id"] = ctx["a3"]["id"]
    return ctx


def riverbend_locked(client=api_client, headers=PLANNER, clock=RIVERBEND_CLOCK, **study_overrides) -> dict:
    """Riverbend USD with two schools, three areas, two adjacency edges, data locked."""
    ctx = setup_study_with_inventory(
        study_payload=study_overrides or None,
        school_payloads=RIVERBEND_SCHOOLS,
        area_builders=_riverbend_areas(),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        clock=clock,
        lock=True,
        client=client,
        headers=headers,
    )
    return _shorthand(ctx)


def riverbend_scenario_draft(client=api_client, headers=PLANNER, variant="COHORT_SURVIVAL", **kwargs) -> dict:
    """Riverbend locked, plus one projection run and one DRAFT scenario, no assignments."""
    ctx = riverbend_locked(client, headers, **kwargs)
    run = create_projection_run(ctx["study_id"], client, headers, variant=variant)
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(ctx["cedar_id"], 30)],
        client,
        headers,
    )
    ctx.update(
        {"run": run, "run_id": run["id"], "scenario": scenario, "scenario_id": scenario["id"]}
    )
    return ctx


def riverbend_scenario_assigned(client=api_client, headers=PLANNER, **kwargs) -> dict:
    """The DRAFT scenario with all three areas assigned: A-01 and A-02 to Cedar, A-03 to Birch."""
    ctx = riverbend_scenario_draft(client, headers, **kwargs)
    ctx["assignments"] = assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
        client,
        headers,
    )
    return ctx


def riverbend_under_review(client=api_client, headers=PLANNER, **kwargs) -> dict:
    """The assigned scenario submitted for review."""
    ctx = riverbend_scenario_assigned(client, headers, **kwargs)
    ctx["scenario"] = submit_for_review(ctx["scenario_id"], client, headers)
    return ctx


def riverbend_engagement_open(client=api_client, headers=PLANNER, coordinator=COORDINATOR, **kwargs) -> dict:
    """The study moved into engagement so the comment window is open."""
    ctx = riverbend_under_review(client, headers, **kwargs)
    ctx["study"] = open_engagement(ctx["study_id"], client, coordinator)
    return ctx


def riverbend_board_ready(client=api_client, headers=PLANNER, coordinator=COORDINATOR, **kwargs) -> dict:
    """The scenario advanced to the board."""
    ctx = riverbend_engagement_open(client, headers, coordinator, **kwargs)
    ctx["scenario"] = advance_to_board(ctx["scenario_id"], client, coordinator)
    return ctx


def riverbend_adopted(
    client=api_client, headers=PLANNER, coordinator=COORDINATOR, board=BOARD, **kwargs
) -> dict:
    """The board-ready scenario adopted, leaving the adoption pending its effective date."""
    adoption_overrides = kwargs.pop("adoption_overrides", None) or {}
    ctx = riverbend_board_ready(client, headers, coordinator, **kwargs)
    defaults = {
        "effective_date": "2027-07-01T00:00:00Z",
        "effective_school_year": 2028,
        "regime_years": 3,
        "transfer_deadline_date": "2027-08-15T00:00:00Z",
        "transfer_cap_pct": 84.1,
        "variance_tolerance_pct": 5.0,
        "votes_for": 5,
        "votes_against": 2,
        "votes_abstain": 0,
        "board_member_count": 7,
    }
    defaults.update(adoption_overrides)
    adoption = create_adoption(ctx["study_id"], ctx["scenario_id"], client, board, **defaults)
    ctx.update({"adoption": adoption, "adoption_id": adoption["id"]})
    return ctx


def riverbend_transfer_requests(specs, ctx=None, client=api_client, **kwargs) -> dict:
    """File a batch of transfer requests against an adoption.

    ``specs`` are dicts carrying ``guardian`` (caller token), ``area_id``,
    ``requested_school_id`` and any request field overrides. The returned context
    gains a ``transfer_requests`` list in filing order.
    """
    ctx = ctx if ctx is not None else riverbend_adopted(client=client, **kwargs)
    requests = []
    for spec in specs:
        spec = dict(spec)
        guardian = spec.pop("guardian")
        area_id = spec.pop("area_id")
        requested_school_id = spec.pop("requested_school_id")
        requests.append(
            create_transfer_request(
                ctx["adoption_id"],
                area_id,
                requested_school_id,
                client,
                make_guardian_headers(guardian),
                **spec,
            )
        )
    ctx["transfer_requests"] = requests
    return ctx
