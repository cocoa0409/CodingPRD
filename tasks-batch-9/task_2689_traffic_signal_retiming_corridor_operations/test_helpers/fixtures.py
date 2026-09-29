"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, and uses the lenient success validator so a broken precondition surfaces as
a setup failure rather than as a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_certifying_engineer_headers,
    make_field_technician_headers,
    make_public_requester_headers,
    make_timing_engineer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["timing_engineer_headers"]
REVIEWER = TEST_USERS["certifying_engineer_headers"]
TECHNICIAN = TEST_USERS["field_technician_headers"]
LIAISON = TEST_USERS["citizen_liaison_headers"]

AUTHOR_ID = "timing-eng-author"
REVIEWER_ID = "cert-eng-reviewer"
AUTHOR = make_timing_engineer_headers(AUTHOR_ID)
INDEPENDENT_REVIEWER = make_certifying_engineer_headers(REVIEWER_ID)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock to the given instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def create_intersection(**overrides) -> dict:
    return get_success_data(
        api_client.create_intersection(f.intersection_payload(**overrides), ADMIN)
    )


def read_intersection(intersection_id: str) -> dict:
    return get_success_data(api_client.get_intersection(intersection_id, ADMIN))


def patch_intersection(intersection_id: str, **payload) -> dict:
    return get_success_data(api_client.update_intersection(intersection_id, payload, ADMIN))


def intersection_version(intersection_id: str) -> int:
    return read_intersection(intersection_id)["version"]


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------
def create_corridor(**overrides) -> dict:
    return get_success_data(api_client.create_corridor(f.corridor_payload(**overrides), ADMIN))


def read_corridor(corridor_id: str) -> dict:
    return get_success_data(api_client.get_corridor(corridor_id, ADMIN))


def enrol_member(corridor_id: str, intersection_id: str, sequence_index: int, **overrides) -> dict:
    payload = f.corridor_member_payload(intersection_id, sequence_index, **overrides)
    return get_success_data(api_client.create_corridor_member(corridor_id, payload, ADMIN))


def screen_corridor(corridor_id: str) -> dict:
    return get_success_data(api_client.screen_corridor(corridor_id, ADMIN))


def decide_corridor(corridor_id: str, decision: str = "SELECT", **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(api_client.corridor_selection_decision(corridor_id, body, ADMIN))


def setup_corridor_with_members(intersections=None, distances=None, **corridor_overrides) -> dict:
    """Create a corridor and enrol one intersection per entry of `intersections`.

    `intersections` is a list of override dicts (one per member, in corridor
    order); `distances` optionally gives distance_from_prev_ft per member (the
    first member is always enrolled at exactly 0).
    Returns {"corridor", "intersections", "members"}.
    """
    specs = intersections if intersections is not None else [{}]
    corridor = create_corridor(**corridor_overrides)
    built, members = [], []
    for idx, spec in enumerate(specs):
        inter = create_intersection(**spec)
        built.append(inter)
        extra = {}
        if idx == 0:
            extra["distance_from_prev_ft"] = 0
        elif distances is not None:
            extra["distance_from_prev_ft"] = distances[idx]
        members.append(enrol_member(corridor["id"], inter["id"], idx + 1, **extra))
    return {
        "corridor": read_corridor(corridor["id"]),
        "intersections": built,
        "members": members,
    }


def setup_selected_corridor(intersections=None, distances=None, **corridor_overrides) -> dict:
    """Corridor with members, screened and then SELECTED under the programming variant."""
    ctx = setup_corridor_with_members(intersections=intersections, distances=distances,
                                      **corridor_overrides)
    screen_corridor(ctx["corridor"]["id"])
    ctx["corridor"] = decide_corridor(ctx["corridor"]["id"], "SELECT")
    return ctx


# ---------------------------------------------------------------------------
# Requesters and complaints
# ---------------------------------------------------------------------------
def create_requester(**overrides) -> dict:
    return get_success_data(api_client.create_requester(f.requester_payload(**overrides), LIAISON))


def file_complaint(requester_id: str, corridor_id: str, headers=None, **overrides) -> dict:
    payload = f.complaint_payload(requester_id, corridor_id, **overrides)
    return get_success_data(api_client.create_complaint(payload, headers or LIAISON))


def triage_complaint(complaint_id: str, disposition: str = "TRIAGE", **payload) -> dict:
    body = {"disposition": disposition}
    body.update(payload)
    return get_success_data(api_client.triage_complaint(complaint_id, body, LIAISON))


def link_complaint(complaint_id: str, project_id: str) -> dict:
    return get_success_data(
        api_client.link_complaint(complaint_id, {"project_id": project_id}, LIAISON)
    )


def resolve_complaint(complaint_id: str, **payload) -> dict:
    return get_success_data(api_client.resolve_complaint(complaint_id, LIAISON, payload or None))


def reopen_complaint(complaint_id: str, **payload) -> dict:
    return get_success_data(api_client.reopen_complaint(complaint_id, LIAISON, payload or None))


def setup_requester_with_complaint(corridor_id: str, **complaint_overrides) -> dict:
    """One requester plus one OPEN complaint against the given corridor."""
    requester = create_requester()
    complaint = file_complaint(requester["id"], corridor_id, **complaint_overrides)
    return {"requester": requester, "complaint": complaint,
            "requester_headers": make_public_requester_headers(requester["id"])}


# ---------------------------------------------------------------------------
# Retiming projects and the before study
# ---------------------------------------------------------------------------
def open_project(corridor_id: str, **overrides) -> dict:
    payload = f.retiming_project_payload(corridor_id, **overrides)
    return get_success_data(api_client.create_retiming_project(payload, ENGINEER))


def read_project(project_id: str) -> dict:
    return get_success_data(api_client.get_retiming_project(project_id, ADMIN))


def project_version(project_id: str) -> int:
    return read_project(project_id)["version"]


def record_count(intersection_id: str, project_id: str, **overrides) -> dict:
    payload = f.turning_movement_count_payload(project_id, **overrides)
    return get_success_data(
        api_client.create_turning_movement_count(intersection_id, payload, TECHNICIAN)
    )


def record_run(project_id: str, **overrides) -> dict:
    payload = f.travel_time_run_payload(**overrides)
    return get_success_data(api_client.create_travel_time_run(project_id, payload, TECHNICIAN))


def advance_project(project_id: str) -> dict:
    return get_success_data(api_client.advance_project(project_id, ENGINEER))


def setup_project_in_data_collection(intersections=None, distances=None,
                                     corridor_overrides=None, **project_overrides) -> dict:
    """SELECTED corridor + members + a project sitting in DATA_COLLECTION."""
    ctx = setup_selected_corridor(intersections=intersections, distances=distances,
                                  **(corridor_overrides or {}))
    ctx["project"] = open_project(ctx["corridor"]["id"], **project_overrides)
    return ctx


def eligible_intersections(ctx) -> list:
    """The corridor members' intersections whose posture is READY or RESTRICTED."""
    return [
        read_intersection(i["id"])
        for i in ctx["intersections"]
        if read_intersection(i["id"])["operational_posture"] in ("READY", "RESTRICTED")
    ]


def complete_before_study(ctx, count_overrides=None, run_overrides=None) -> dict:
    """One BEFORE count at every eligible member, plus one BEFORE travel time run."""
    project_id = ctx["project"]["id"]
    counts = []
    for inter in eligible_intersections(ctx):
        counts.append(record_count(inter["id"], project_id, **(count_overrides or {})))
    runs = [record_run(project_id, **(run_overrides or {}))]
    ctx.setdefault("counts", []).extend(counts)
    ctx.setdefault("runs", []).extend(runs)
    return ctx


def setup_project_in_plan_development(intersections=None, distances=None,
                                      corridor_overrides=None, count_overrides=None,
                                      run_overrides=None, **project_overrides) -> dict:
    """A project advanced out of DATA_COLLECTION into PLAN_DEVELOPMENT."""
    ctx = setup_project_in_data_collection(intersections=intersections, distances=distances,
                                           corridor_overrides=corridor_overrides,
                                           **project_overrides)
    complete_before_study(ctx, count_overrides=count_overrides, run_overrides=run_overrides)
    ctx["project"] = advance_project(ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Timing plans and phase splits
# ---------------------------------------------------------------------------
DEFAULT_SPLITS = [
    {"phase_number": 1, "split_sec": 30},
    {"phase_number": 2, "split_sec": 30},
    {"phase_number": 4, "split_sec": 30},
    {"phase_number": 6, "split_sec": 30},
]


def draft_plan(project_id: str, intersection_id: str, headers=None, **overrides) -> dict:
    """Draft a timing plan, reading the project's current version for the OCC guard."""
    version = overrides.pop("expected_project_version", None)
    if version is None:
        version = project_version(project_id)
    payload = f.timing_plan_payload(project_id, intersection_id, version, **overrides)
    return get_success_data(api_client.create_timing_plan(payload, headers or AUTHOR))


def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_timing_plan(plan_id, ADMIN))


def add_split(plan_id: str, phase_number: int, **overrides) -> dict:
    payload = f.phase_split_payload(plan_id, phase_number, **overrides)
    return get_success_data(api_client.create_phase_split(plan_id, payload, AUTHOR))


def add_pedestrian_split(plan_id: str, phase_number: int, **overrides) -> dict:
    payload = f.pedestrian_phase_split_payload(plan_id, phase_number, **overrides)
    return get_success_data(api_client.create_phase_split(plan_id, payload, AUTHOR))


def add_splits(plan_id: str, splits=None) -> list:
    """Add a list of split specs (dicts carrying phase_number plus overrides)."""
    built = []
    for spec in (splits if splits is not None else DEFAULT_SPLITS):
        spec = dict(spec)
        phase_number = spec.pop("phase_number")
        if spec.get("is_pedestrian_phase"):
            built.append(add_pedestrian_split(plan_id, phase_number, **spec))
        else:
            built.append(add_split(plan_id, phase_number, **spec))
    return built


def read_splits(plan_id: str) -> list:
    return get_success_data(api_client.list_phase_splits(plan_id, ADMIN))


def read_ped_checks(plan_id: str) -> list:
    return get_success_data(api_client.list_pedestrian_checks(plan_id, ADMIN))


def setup_draft_plan(intersections=None, plan_overrides=None, splits=None,
                     count_overrides=None, **project_kwargs) -> dict:
    """PLAN_DEVELOPMENT project + one DRAFT plan with phase splits on member 1."""
    ctx = setup_project_in_plan_development(intersections=intersections,
                                            count_overrides=count_overrides, **project_kwargs)
    plan = draft_plan(ctx["project"]["id"], ctx["intersections"][0]["id"],
                      **(plan_overrides or {}))
    ctx["splits"] = add_splits(plan["id"], splits)
    ctx["plan"] = read_plan(plan["id"])
    ctx["plans"] = [ctx["plan"]]
    return ctx


def coordinate_project(project_id: str) -> dict:
    return get_success_data(api_client.coordinate_project(project_id, ENGINEER))


def setup_coordinated_plan(intersections=None, plan_overrides=None, splits=None,
                           count_overrides=None, **project_kwargs) -> dict:
    """A single plan taken through the corridor coordination pipeline."""
    ctx = setup_draft_plan(intersections=intersections, plan_overrides=plan_overrides,
                           splits=splits, count_overrides=count_overrides, **project_kwargs)
    coordinate_project(ctx["project"]["id"])
    ctx["project"] = read_project(ctx["project"]["id"])
    ctx["plan"] = read_plan(ctx["plan"]["id"])
    ctx["plans"] = [ctx["plan"]]
    ctx["splits"] = read_splits(ctx["plan"]["id"])
    ctx["ped_checks"] = read_ped_checks(ctx["plan"]["id"])
    return ctx


def submit_plan(plan_id: str) -> dict:
    return get_success_data(api_client.submit_timing_plan(plan_id, ENGINEER))


def certify_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.certify_timing_plan(plan_id, headers or INDEPENDENT_REVIEWER))


def return_plan(plan_id: str, reason: str = "Splits do not reflect the field", headers=None) -> dict:
    return get_success_data(
        api_client.return_timing_plan(plan_id, {"reason": reason}, headers or INDEPENDENT_REVIEWER)
    )


def waive_check(check_id: str, justification: str = "Curb extension already funded",
                headers=None) -> dict:
    return get_success_data(
        api_client.waive_pedestrian_check(
            check_id, {"waiver_justification": justification}, headers or INDEPENDENT_REVIEWER
        )
    )


def setup_submitted_plan(**kwargs) -> dict:
    ctx = setup_coordinated_plan(**kwargs)
    ctx["plan"] = submit_plan(ctx["plan"]["id"])
    ctx["plans"] = [ctx["plan"]]
    return ctx


def setup_certified_plan(**kwargs) -> dict:
    ctx = setup_submitted_plan(**kwargs)
    ctx["plan"] = certify_plan(ctx["plan"]["id"])
    ctx["plans"] = [ctx["plan"]]
    return ctx


# ---------------------------------------------------------------------------
# Implementation, fine tuning, evaluation
# ---------------------------------------------------------------------------
def implement_project(project_id: str) -> dict:
    return get_success_data(api_client.implement_project(project_id, ENGINEER))


def setup_implemented_project(plan_overrides=None, splits=None, **kwargs) -> dict:
    """Every eligible member carries a CERTIFIED plan, then the project is implemented."""
    ctx = setup_project_in_plan_development(**kwargs)
    plans = []
    for inter in eligible_intersections(ctx):
        plan = draft_plan(ctx["project"]["id"], inter["id"], **(plan_overrides or {}))
        add_splits(plan["id"], splits)
        plans.append(plan)
    coordinate_project(ctx["project"]["id"])
    certified = []
    for plan in plans:
        submit_plan(plan["id"])
        certified.append(certify_plan(plan["id"]))
    ctx["project"] = implement_project(ctx["project"]["id"])
    ctx["plans"] = [read_plan(p["id"]) for p in certified]
    ctx["plan"] = ctx["plans"][0]
    ctx["intersections"] = [read_intersection(i["id"]) for i in ctx["intersections"]]
    ctx["corridor"] = read_corridor(ctx["corridor"]["id"])
    return ctx


def field_tuning(project_id: str, action: str) -> dict:
    return get_success_data(api_client.project_field_tuning(project_id, {"action": action}, ADMIN))


def setup_field_tuning_project(**kwargs) -> dict:
    ctx = setup_implemented_project(**kwargs)
    ctx["project"] = field_tuning(ctx["project"]["id"], "START")
    return ctx


def log_observation(project_id: str, intersection_id: str, headers=None, **overrides) -> dict:
    payload = f.field_observation_payload(project_id, intersection_id, **overrides)
    return get_success_data(api_client.create_field_observation(payload, headers or TECHNICIAN))


def resolve_observation(observation_id: str, resolution_status: str = "ADDRESSED") -> dict:
    return get_success_data(
        api_client.update_field_observation(
            observation_id, {"resolution_status": resolution_status}, TECHNICIAN
        )
    )


def setup_evaluation_project(**kwargs) -> dict:
    """Project carried through FIELD_TUNING into EVALUATION with last_tuning_completed_at set."""
    ctx = setup_field_tuning_project(**kwargs)
    ctx["project"] = field_tuning(ctx["project"]["id"], "COMPLETE")
    return ctx


def create_evaluation(project_id: str, headers=None, **overrides) -> dict:
    version = overrides.pop("expected_project_version", None)
    if version is None:
        version = project_version(project_id)
    payload = f.performance_evaluation_payload(version, **overrides)
    return get_success_data(
        api_client.create_performance_evaluation(project_id, payload, headers or REVIEWER)
    )


def certify_evaluation(evaluation_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.certify_performance_evaluation(evaluation_id, headers or REVIEWER)
    )


def close_project(project_id: str, disposition: str = "CLOSED", **payload) -> dict:
    body = {"disposition": disposition}
    body.update(payload)
    return get_success_data(api_client.close_project(project_id, body, ADMIN))


# ---------------------------------------------------------------------------
# Priority configurations
# ---------------------------------------------------------------------------
def propose_config(intersection_id: str, headers=None, **overrides) -> dict:
    version = overrides.pop("expected_intersection_version", None)
    if version is None:
        version = intersection_version(intersection_id)
    payload = f.priority_config_payload(intersection_id, version, **overrides)
    return get_success_data(api_client.create_priority_config(payload, headers or ENGINEER))


def approve_config(config_id: str, decision: str = "APPROVE", headers=None, **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(
        api_client.approve_priority_config(config_id, body, headers or REVIEWER)
    )


def deploy_config(config_id: str) -> dict:
    return get_success_data(api_client.deploy_priority_config(config_id, ADMIN))


def suspend_config(config_id: str, **payload) -> dict:
    return get_success_data(api_client.suspend_priority_config(config_id, ADMIN, payload or None))


def read_configs_at(intersection_id: str) -> list:
    return get_success_data(api_client.list_intersection_priority_configs(intersection_id, ADMIN))


def setup_intersection_with_deployed_plan(**kwargs) -> dict:
    """An intersection whose timing plan is DEPLOYED, so a priority budget exists."""
    return setup_implemented_project(**kwargs)


def setup_approved_config(ctx=None, config_overrides=None, **kwargs) -> dict:
    """Deployed-plan intersection plus one APPROVED (not yet deployed) configuration."""
    ctx = ctx or setup_intersection_with_deployed_plan(**kwargs)
    intersection_id = ctx["intersections"][0]["id"]
    config = propose_config(intersection_id, **(config_overrides or {}))
    ctx.setdefault("configs", []).append(approve_config(config["id"]))
    ctx["config"] = ctx["configs"][-1]
    return ctx


def setup_deployed_config(ctx=None, config_overrides=None, **kwargs) -> dict:
    """Deployed-plan intersection plus one DEPLOYED priority configuration."""
    ctx = setup_approved_config(ctx=ctx, config_overrides=config_overrides, **kwargs)
    ctx["config"] = deploy_config(ctx["config"]["id"])
    ctx["configs"][-1] = ctx["config"]
    ctx["intersections"][0] = read_intersection(ctx["intersections"][0]["id"])
    return ctx


# ---------------------------------------------------------------------------
# The canonical four-phase split set used by the arithmetic scenarios
# ---------------------------------------------------------------------------
# Drafted at cycle 90 with a drafted split total of 86 seconds; phase 4 is the
# only pedestrian phase, and its 62.0 ft crossing at 3.5 fps requires exactly
# 17.8 s of pedestrian clearance.
CANONICAL_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 21, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 12,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 4.0, "ped_clear_sec": 17.8, "crosswalk_length_ft": 62.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

# Same set, but phase 4 provides one tenth of a second less clearance than the
# 17.8 s its crossing requires, so the pipeline mints one FAIL check.
CANONICAL_SPLITS_PED_SHORT = [
    dict(spec, ped_clear_sec=17.7) if spec["phase_number"] == 4 else dict(spec)
    for spec in CANONICAL_SPLITS
]

# Two non-pedestrian phases: drafted total 42, so a coordinated cycle of 105
# rescales them to 53 and 52.
CANONICAL_SPLITS_TWO_PHASE = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 21, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

CANONICAL_PLAN = {"cycle_length_sec": 90}
CANONICAL_COUNT = {"phase_volumes": {"1": 350, "2": 500, "4": 250, "6": 180}}


def setup_canonical_coordinated_plan(splits=None, **kwargs):
    """One READY member, one BEFORE count, one drafted plan, then coordinate."""
    return setup_coordinated_plan(
        plan_overrides=dict(CANONICAL_PLAN),
        splits=splits if splits is not None else CANONICAL_SPLITS,
        **kwargs,
    )


def setup_canonical_implemented_project(splits=None, **kwargs):
    """The canonical single-member corridor carried all the way to IMPLEMENTED."""
    return setup_implemented_project(
        plan_overrides=dict(CANONICAL_PLAN),
        splits=splits if splits is not None else CANONICAL_SPLITS,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Readers for the entities that are only reachable through a listing
# ---------------------------------------------------------------------------
def _pick(rows, row_id: str) -> dict:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"row {row_id} is not present in the listing")


def corridor_complaints(corridor_id: str, headers=None, **params) -> list:
    return get_success_data(
        api_client.list_corridor_complaints(corridor_id, headers or LIAISON, params or None)
    )


def read_complaint(corridor_id: str, complaint_id: str) -> dict:
    return _pick(corridor_complaints(corridor_id), complaint_id)


def requester_complaints(requester_id: str, headers=None, **params) -> list:
    return get_success_data(
        api_client.list_requester_complaints(requester_id, headers or LIAISON, params or None)
    )


def read_requester(requester_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_requester(requester_id, headers or LIAISON))


def project_complaints(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_complaints(project_id, ADMIN, params or None)
    )


def project_counts(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_turning_movement_counts(project_id, ADMIN, params or None)
    )


def intersection_counts(intersection_id: str, **params) -> list:
    return get_success_data(
        api_client.list_intersection_turning_movement_counts(
            intersection_id, ADMIN, params or None
        )
    )


def project_runs(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_travel_time_runs(project_id, ADMIN, params or None)
    )


def project_plans(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_timing_plans(project_id, ADMIN, params or None)
    )


def intersection_plans(intersection_id: str, **params) -> list:
    return get_success_data(
        api_client.list_intersection_timing_plans(intersection_id, ADMIN, params or None)
    )


def corridor_members(corridor_id: str, **params) -> list:
    return get_success_data(
        api_client.list_corridor_members(corridor_id, ADMIN, params or None)
    )


def intersection_memberships(intersection_id: str, **params) -> list:
    return get_success_data(
        api_client.list_intersection_corridor_memberships(
            intersection_id, ADMIN, params or None
        )
    )


def project_observations(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_field_observations(project_id, ADMIN, params or None)
    )


def read_observation(project_id: str, observation_id: str) -> dict:
    return _pick(project_observations(project_id), observation_id)


def intersection_observations(intersection_id: str, **params) -> list:
    return get_success_data(
        api_client.list_intersection_field_observations(
            intersection_id, ADMIN, params or None
        )
    )


def project_evaluations(project_id: str, **params) -> list:
    return get_success_data(
        api_client.list_project_performance_evaluations(project_id, ADMIN, params or None)
    )


def read_evaluation(project_id: str, evaluation_id: str) -> dict:
    return _pick(project_evaluations(project_id), evaluation_id)


def read_config(intersection_id: str, config_id: str) -> dict:
    return _pick(read_configs_at(intersection_id), config_id)


def read_split(plan_id: str, phase_number: int) -> dict:
    for row in read_splits(plan_id):
        if row["phase_number"] == phase_number:
            return row
    raise AssertionError(f"plan {plan_id} has no phase {phase_number}")


def effective_splits(plan_id: str) -> dict:
    return {row["phase_number"]: row["effective_split_sec"] for row in read_splits(plan_id)}
