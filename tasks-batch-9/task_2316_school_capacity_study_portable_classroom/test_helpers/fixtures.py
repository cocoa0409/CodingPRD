"""Composite state builders.

Every builder drives the public API only, in the order the PRD prescribes, and
returns the ids it created.  The harness restarts the server before each test,
so each builder starts from an empty district and a logical clock reading
`2026-08-01T00:00:00Z`.
"""

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    CERTIFIER_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
)

DEFAULT_CLOCK = "2027-03-01T00:00:00Z"
DEFAULT_PROJECTIONS: Tuple[Tuple[int, int], ...] = ((6, 20), (7, 20), (8, 20))
DEFAULT_ROOM_AREAS: Tuple[float, ...] = (900, 900)


# --------------------------------------------------------------------- primitives
def set_clock(api, to_iso8601: str) -> str:
    data = get_success_data(api.set_clock(f.clock_payload(to_iso8601), ADMIN_HEADERS))
    return data["current_utc"]


def create_policy(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_class_size_policy(f.policy_payload(**overrides), ADMIN_HEADERS)
    )


def create_school(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_school(f.school_payload(**overrides), ADMIN_HEADERS)
    )


def create_room(api, school_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_room(f.room_payload(school_id, **overrides), ADMIN_HEADERS)
    )


def create_set_aside(api, school_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_program_set_aside(
            f.set_aside_payload(school_id, **overrides), ADMIN_HEADERS
        )
    )


def create_projection(api, school_id: str, grade_level: int, projected_students: int,
                      **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_enrollment_projection(
            f.projection_payload(school_id, grade_level, projected_students, **overrides),
            PLANNER_HEADERS,
        )
    )


def create_budget(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_capital_budget(f.budget_payload(**overrides), ADMIN_HEADERS)
    )


def create_crew(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_installation_crew(f.crew_payload(**overrides), ADMIN_HEADERS)
    )


def create_site(api, school_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_placement_site(f.site_payload(school_id, **overrides), ADMIN_HEADERS)
    )


def assess_pad(api, site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.assess_placement_site(
            site_id, f.assess_site_payload(**overrides), PLANNER_HEADERS
        )
    )


def create_unit(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_portable_unit(f.unit_payload(**overrides), ASSET_HEADERS)
    )


def record_condition(api, unit_id: str, condition_status: str,
                     condition_grade: str) -> Dict[str, Any]:
    return get_success_data(
        api.record_condition(
            unit_id, f.condition_payload(condition_status, condition_grade),
            ASSET_HEADERS,
        )
    )


def school_version(api, school_id: str) -> int:
    return get_success_data(api.get_school(school_id, ADMIN_HEADERS))["version"]


def study_version(api, study_id: str) -> int:
    return get_success_data(api.get_capacity_study(study_id, PLANNER_HEADERS))["version"]


def create_study(api, school_id: str, policy_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.study_payload(
        school_id, policy_id, school_version(api, school_id), **overrides
    )
    return get_success_data(api.create_capacity_study(payload, PLANNER_HEADERS))


def submit_study(api, study_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_study(study_id, {}, PLANNER_HEADERS))


def certify_study(api, study_id: str) -> Dict[str, Any]:
    return get_success_data(api.certify_study(study_id, {}, CERTIFIER_HEADERS))


def return_study(api, study_id: str,
                 correction_note: str = "Revise the projections.") -> Dict[str, Any]:
    return get_success_data(
        api.return_study(study_id, {"correction_note": correction_note},
                         CERTIFIER_HEADERS)
    )


def reopen_study(api, study_id: str) -> Dict[str, Any]:
    return get_success_data(api.reopen_study(study_id, {}, PLANNER_HEADERS))


def create_request(api, study_id: str, site_id: str, budget_id: str,
                   **overrides: Any) -> Dict[str, Any]:
    payload = f.placement_request_payload(
        study_id, site_id, budget_id, study_version(api, study_id), **overrides
    )
    return get_success_data(api.create_placement_request(payload, PLANNER_HEADERS))


def permit_ids_by_type(api, request_id: str) -> Dict[str, str]:
    response = api.list_permits(
        PERMIT_HEADERS, {"placement_request_id": request_id, "limit": 100}
    )
    rows = get_success_data(response)
    return {row["permit_type"]: row["id"] for row in rows}


def approve_permit(api, permit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_permit(permit_id, f.permit_decision_payload("APPROVED"),
                          OFFICIAL_HEADERS)
    )


def approve_all_permits(api, request_id: str,
                        skip: Sequence[str] = ()) -> Dict[str, str]:
    """Approve every permit of the request except the named disciplines."""
    permits = permit_ids_by_type(api, request_id)
    for permit_type, permit_id in permits.items():
        if permit_type in skip:
            continue
        approve_permit(api, permit_id)
    return permits


def create_schedule(api, request_id: str, crew_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_installation_schedule(
            f.schedule_payload(request_id, crew_id, **overrides), SCHEDULER_HEADERS
        )
    )


# --------------------------------------------------------------------- campus
def build_campus(
    api,
    *,
    clock: Optional[str] = DEFAULT_CLOCK,
    school_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    policy_id: Optional[str] = None,
    room_areas: Iterable[float] = DEFAULT_ROOM_AREAS,
    room_types: Optional[Sequence[str]] = None,
    projections: Iterable[Tuple[int, int]] = DEFAULT_PROJECTIONS,
    budget_cents: Optional[int] = 500_000_000,
) -> Dict[str, Any]:
    """A campus with its policy, rooms, projections and appropriation in place."""
    if clock is not None:
        set_clock(api, clock)

    ctx: Dict[str, Any] = {}
    if policy_id is None:
        policy = create_policy(api, **(policy_overrides or {}))
        ctx["policy_id"] = policy["id"]
    else:
        ctx["policy_id"] = policy_id

    school = create_school(api, **(school_overrides or {}))
    ctx["school_id"] = school["id"]
    ctx["school"] = school

    areas = list(room_areas)
    types = list(room_types) if room_types else ["STANDARD_CLASSROOM"] * len(areas)
    ctx["room_ids"] = [
        create_room(api, school["id"], area_sqft=area, room_type=room_type)["id"]
        for area, room_type in zip(areas, types)
    ]

    ctx["projection_ids"] = [
        create_projection(api, school["id"], grade, students)["id"]
        for grade, students in projections
    ]

    if budget_cents is not None:
        budget = create_budget(api, authorized_cents=budget_cents)
        ctx["budget_id"] = budget["id"]
    return ctx


def build_mixed_room_campus(api, *, clock: str = DEFAULT_CLOCK,
                            name: str = "Ridgeview Middle") -> Dict[str, Any]:
    """A campus whose room mix makes the two loading variants diverge.

    Seven rooms (three standard classrooms of 900, 900 and 720 sqft, a
    1000 sqft science lab, a 650 sqft SPED resource room, an 840 sqft
    art/music room and a gym), two set-asides (SPED_SELF_CONTAINED over the
    SPED resource room and CTE_LAB over the science lab) and four projection
    rows in which a DEVELOPER_YIELD row for grade 6 competes with a
    COHORT_SURVIVAL row.
    """
    set_clock(api, clock)
    policy = create_policy(api)
    school = create_school(api, name=name)
    ctx: Dict[str, Any] = {
        "policy_id": policy["id"],
        "school_id": school["id"],
        "school": school,
        "room_ids": [],
    }
    for room_number, room_type, area in (
        ("R101", "STANDARD_CLASSROOM", 900),
        ("R102", "STANDARD_CLASSROOM", 900),
        ("R103", "STANDARD_CLASSROOM", 720),
        ("L201", "SCIENCE_LAB", 1000),
        ("S301", "SPED_RESOURCE", 650),
        ("A401", "ART_MUSIC", 840),
        ("G001", "GYM", 5000),
    ):
        ctx["room_ids"].append(
            create_room(api, school["id"], room_number=room_number,
                        room_type=room_type, area_sqft=area)["id"]
        )

    create_set_aside(api, school["id"], program_type="SPED_SELF_CONTAINED",
                     reserved_room_type="SPED_RESOURCE", reserved_room_count=1,
                     seats_excluded_per_room=12)
    create_set_aside(api, school["id"], program_type="CTE_LAB",
                     reserved_room_type="SCIENCE_LAB", reserved_room_count=1,
                     seats_excluded_per_room=8)

    create_projection(api, school["id"], 6, 44, source="COHORT_SURVIVAL")
    create_projection(api, school["id"], 6, 52, source="DEVELOPER_YIELD")
    create_projection(api, school["id"], 7, 42)
    create_projection(api, school["id"], 8, 40)

    ctx["budget_id"] = create_budget(api)["id"]
    return ctx


def build_certified_study(
    api,
    ctx: Dict[str, Any],
    *,
    method: str = "DISTRICT_POLICY",
    certify: bool = True,
    **study_overrides: Any,
) -> Dict[str, Any]:
    """Open, submit and (optionally) certify a study on an existing campus."""
    study = create_study(
        api, ctx["school_id"], ctx["policy_id"], method=method, **study_overrides
    )
    ctx["study_id"] = study["id"]
    ctx["study_submitted"] = submit_study(api, study["id"])
    if certify:
        ctx["study_certified"] = certify_study(api, study["id"])
    return ctx


# --------------------------------------------------------------------- request ladder
STAGES = (
    "draft",
    "site_assessed",
    "permit_pending",
    "permitted",
    "scheduled",
    "in_progress",
    "installed",
)


def build_request_context(
    api,
    *,
    stage: str = "permitted",
    clock: Optional[str] = DEFAULT_CLOCK,
    school_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    room_areas: Iterable[float] = DEFAULT_ROOM_AREAS,
    room_types: Optional[Sequence[str]] = None,
    projections: Iterable[Tuple[int, int]] = DEFAULT_PROJECTIONS,
    budget_cents: int = 500_000_000,
    method: str = "DISTRICT_POLICY",
    certify: bool = True,
    pad_overrides: Optional[Dict[str, Any]] = None,
    assess_pad_for: Optional[str] = "SINGLE_24x40",
    unit_overrides: Optional[Dict[str, Any]] = None,
    with_unit: bool = True,
    crew_overrides: Optional[Dict[str, Any]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    start_clock: Optional[str] = None,
    complete_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive one placement request up to `stage` and return every id created.

    Stages, in order: `draft`, `site_assessed`, `permit_pending`, `permitted`,
    `scheduled`, `in_progress`, `installed`.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    target = STAGES.index(stage)

    ctx = build_campus(
        api,
        clock=clock,
        school_overrides=school_overrides,
        policy_overrides=policy_overrides,
        room_areas=room_areas,
        room_types=room_types,
        projections=projections,
        budget_cents=budget_cents,
    )

    site = create_site(api, ctx["school_id"], **(pad_overrides or {}))
    ctx["site_id"] = site["id"]
    if assess_pad_for is not None:
        ctx["site_assessment"] = assess_pad(
            api, site["id"], candidate_size_class=assess_pad_for
        )

    if with_unit:
        unit = create_unit(api, **(unit_overrides or {}))
        ctx["unit_id"] = unit["id"]

    crew = create_crew(api, **(crew_overrides or {}))
    ctx["crew_id"] = crew["id"]

    build_certified_study(api, ctx, method=method, certify=certify)

    overrides = dict(request_overrides or {})
    if with_unit and "portable_unit_id" not in overrides:
        overrides["portable_unit_id"] = ctx["unit_id"]
    request = create_request(
        api, ctx["study_id"], ctx["site_id"], ctx["budget_id"], **overrides
    )
    ctx["request_id"] = request["id"]
    ctx["request_created"] = request
    if target == STAGES.index("draft"):
        return ctx

    get_success_data(api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS))
    if target == STAGES.index("site_assessed"):
        return ctx

    get_success_data(api.submit_permits(ctx["request_id"], {}, PERMIT_HEADERS))
    ctx["permit_ids"] = permit_ids_by_type(api, ctx["request_id"])
    if target == STAGES.index("permit_pending"):
        return ctx

    approve_all_permits(api, ctx["request_id"])
    if target == STAGES.index("permitted"):
        return ctx

    schedule = create_schedule(
        api, ctx["request_id"], ctx["crew_id"], **(schedule_overrides or {})
    )
    ctx["schedule_id"] = schedule["id"]
    if target == STAGES.index("scheduled"):
        return ctx

    if start_clock is not None:
        set_clock(api, start_clock)
    get_success_data(api.start_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS))
    if target == STAGES.index("in_progress"):
        return ctx

    if complete_clock is not None:
        set_clock(api, complete_clock)
    get_success_data(api.complete_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS))
    return ctx


# --------------------------------------------------------------------- pytest fixtures
@pytest.fixture(scope="session")
def api():
    return api_client


@pytest.fixture
def campus(api):
    """Callable building a campus with its policy, rooms, projections and budget."""
    def _build(**kwargs: Any) -> Dict[str, Any]:
        return build_campus(api, **kwargs)
    return _build


@pytest.fixture
def request_context(api):
    """Callable driving a placement request to a named stage."""
    def _build(**kwargs: Any) -> Dict[str, Any]:
        return build_request_context(api, **kwargs)
    return _build


@pytest.fixture
def draft_request(api):
    return build_request_context(api, stage="draft")


@pytest.fixture
def permitted_request(api):
    return build_request_context(api, stage="permitted")


@pytest.fixture
def scheduled_request(api):
    return build_request_context(api, stage="scheduled")


@pytest.fixture
def installed_request(api):
    return build_request_context(
        api,
        stage="installed",
        start_clock="2027-06-15T00:00:00Z",
        complete_clock="2027-06-25T00:00:00Z",
    )
