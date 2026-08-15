"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
the harness restarts the server before each test, so nothing carries over.
Setup steps use the lenient get_success_data() validator so a broken
precondition reports as a clear "Setup step failed" instead of a confusing
assertion mismatch.

Segregation-of-duties identities (PRD §2.1): the reviewer/confirmer user id
always differs from the submitter/recorder user id. The UtilityOwnerRep role
is entity-backed: its headers are built from the real UtilityOwner.id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    as_built_payload,
    change_order_payload,
    compaction_test_payload,
    discharge_permit_payload,
    discharge_reading_payload,
    inspection_payload,
    locate_ticket_payload,
    pipe_segment_payload,
    pothole_payload,
    project_payload,
    shallow_segment_payload,
    shallow_trench_plan_payload,
    shutdown_window_payload,
    trench_plan_payload,
    unforeseen_condition_payload,
    utility_owner_payload,
)
from .test_users import (
    FOREMAN_USER,
    INSPECTOR_SECOND,
    INSPECTOR_USER,
    OPS_ADMIN,
    PM_SECOND,
    PM_USER,
    PROJECT_MANAGER,
    SAFETY_USER,
    FOREMAN,
    INSPECTOR,
    make_foreman_headers,
    make_inspector_headers,
    make_project_manager_headers,
    make_safety_officer_headers,
    make_utility_owner_rep_headers,
)

# Default logical-clock target that activates the standard ticket
# (legal_start_at 2026-08-03T00:00:00Z).
ACTIVE_TICKET_CLOCK = "2026-08-03T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: thin single-call helpers
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (OpsAdmin only, PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS_ADMIN))


def create_project(**overrides) -> dict:
    return get_success_data(
        api_client.create_project(project_payload(**overrides), PROJECT_MANAGER)
    )


def create_utility_owner(**overrides) -> dict:
    return get_success_data(
        api_client.create_utility_owner(utility_owner_payload(**overrides), OPS_ADMIN)
    )


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, PROJECT_MANAGER))


def get_segment(segment_id: str) -> dict:
    return get_success_data(api_client.get_pipe_segment(segment_id, FOREMAN))


def get_owner(owner_id: str) -> dict:
    return get_success_data(api_client.get_utility_owner(owner_id, OPS_ADMIN))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_locate_ticket(ticket_id, PROJECT_MANAGER))


def get_window(window_id: str) -> dict:
    return get_success_data(api_client.get_shutdown_window(window_id, PROJECT_MANAGER))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_discharge_permit(permit_id, PROJECT_MANAGER))


def get_condition(condition_id: str) -> dict:
    return get_success_data(
        api_client.get_unforeseen_condition(condition_id, PROJECT_MANAGER)
    )


def get_change_order(order_id: str) -> dict:
    return get_success_data(api_client.get_change_order(order_id, PROJECT_MANAGER))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_trench_safety_plan(plan_id, FOREMAN))


def get_pothole(pothole_id: str) -> dict:
    return get_success_data(
        api_client.get_pothole_verification(pothole_id, PROJECT_MANAGER)
    )


def get_as_built(package_id: str) -> dict:
    return get_success_data(api_client.get_as_built_package(package_id, PROJECT_MANAGER))


# ---------------------------------------------------------------------------
# Tier 1/2: project, owner, ticket, pothole context
# ---------------------------------------------------------------------------

def create_locate_ticket(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_locate_ticket(
            locate_ticket_payload(project_id, **overrides), PROJECT_MANAGER
        )
    )


def setup_project_with_active_ticket(
    *,
    legal_start_at: str = ACTIVE_TICKET_CLOCK,
    with_verified_pothole: bool = True,
    pothole_overrides: dict | None = None,
    project_overrides: dict | None = None,
    owner_overrides: dict | None = None,
) -> dict:
    """Project (ACTIVE) + utility owner + locate ticket driven to ACTIVE via
    the clock, plus (optionally) one fully verified pothole.

    Returns {"project", "owner", "ticket", "pothole"} (pothole may be None).
    """
    project = create_project(**(project_overrides or {}))
    owner = create_utility_owner(**(owner_overrides or {}))
    ticket = create_locate_ticket(project["id"], legal_start_at=legal_start_at)
    get_success_data(api_client.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))
    advance_clock(legal_start_at)
    ticket = get_ticket(ticket["id"])

    pothole = None
    if with_verified_pothole:
        po = {"design_depth_in": 60, "design_offset_in": 12}
        po.update(pothole_overrides or {})
        pothole = get_success_data(
            api_client.create_pothole_verification(
                pothole_payload(project["id"], ticket["id"], **po), PROJECT_MANAGER
            )
        )
        get_success_data(
            api_client.perform_pothole(
                pothole["id"],
                {
                    "measured_depth_in": po["design_depth_in"],
                    "measured_offset_in": po["design_offset_in"],
                },
                FOREMAN,
            )
        )
        pothole = get_success_data(
            api_client.verify_pothole(pothole["id"], PROJECT_MANAGER)
        )

    return {"project": project, "owner": owner, "ticket": ticket, "pothole": pothole}


# ---------------------------------------------------------------------------
# Tier 2/3: pipe segment pipeline
# ---------------------------------------------------------------------------

def create_segment(project: dict, owner: dict, *, shallow: bool = False,
                   **overrides) -> dict:
    factory = shallow_segment_payload if shallow else pipe_segment_payload
    return get_success_data(
        api_client.create_pipe_segment(
            factory(project["id"], owner["id"], **overrides), FOREMAN
        )
    )


def create_approved_plan(
    project: dict,
    segment: dict,
    *,
    shallow: bool = False,
    submitter_id: str = FOREMAN_USER,
    reviewer_id: str = SAFETY_USER,
    **overrides,
) -> dict:
    """Draft -> submit -> approve a trench safety plan for the segment."""
    factory = shallow_trench_plan_payload if shallow else trench_plan_payload
    plan = get_success_data(
        api_client.create_trench_safety_plan(
            factory(project["id"], segment["id"], **overrides),
            make_foreman_headers(submitter_id),
        )
    )
    get_success_data(
        api_client.submit_trench_safety_plan(
            plan["id"], make_foreman_headers(submitter_id)
        )
    )
    return get_success_data(
        api_client.review_trench_safety_plan(
            plan["id"], "APPROVE", make_safety_officer_headers(reviewer_id)
        )
    )


def mark_segment_ready(segment_id: str) -> dict:
    return get_success_data(api_client.mark_segment_ready(segment_id, FOREMAN))


def start_segment_install(segment_id: str) -> dict:
    return get_success_data(api_client.start_install(segment_id, FOREMAN))


def complete_segment_install(segment_id: str) -> dict:
    return get_success_data(api_client.complete_install(segment_id, FOREMAN))


def record_installation_inspection(
    segment_id: str, *, recorder_id: str = INSPECTOR_USER, **overrides
) -> dict:
    return get_success_data(
        api_client.create_installation_inspection(
            inspection_payload(segment_id, **overrides),
            make_inspector_headers(recorder_id),
        )
    )


def confirm_installation_inspection(
    inspection_id: str, *, confirmer_id: str = INSPECTOR_SECOND
) -> dict:
    return get_success_data(
        api_client.confirm_inspection(
            inspection_id, make_inspector_headers(confirmer_id)
        )
    )


def record_confirmed_inspection(segment_id: str, **overrides) -> dict:
    """Record + confirm an inspection (distinct recorder/confirmer, PRD §3.4).

    The computed result follows the supplied measurements — pass or fail.
    """
    inspection = record_installation_inspection(segment_id, **overrides)
    return confirm_installation_inspection(inspection["id"])


def start_segment_backfill(segment_id: str) -> dict:
    return get_success_data(api_client.start_backfill(segment_id, FOREMAN))


def setup_ready_segment(*, shallow: bool = False, segment_overrides=None,
                        plan_overrides=None, project_overrides=None,
                        owner_overrides=None) -> dict:
    """Active-ticket context + segment + APPROVED plan + mark-ready.

    Returns {"project", "owner", "ticket", "pothole", "segment", "plan"}.
    """
    ctx = setup_project_with_active_ticket(
        project_overrides=project_overrides, owner_overrides=owner_overrides
    )
    segment = create_segment(ctx["project"], ctx["owner"], shallow=shallow,
                             **(segment_overrides or {}))
    plan = create_approved_plan(ctx["project"], segment, shallow=shallow,
                                **(plan_overrides or {}))
    segment = mark_segment_ready(segment["id"])
    ctx.update({"segment": segment, "plan": plan})
    return ctx


def setup_installing_segment(*, shallow: bool = False, segment_overrides=None,
                             plan_overrides=None, project_overrides=None,
                             owner_overrides=None) -> dict:
    """Ready context driven one step further: segment INSTALLING."""
    ctx = setup_ready_segment(shallow=shallow, segment_overrides=segment_overrides,
                              plan_overrides=plan_overrides,
                              project_overrides=project_overrides,
                              owner_overrides=owner_overrides)
    ctx["segment"] = start_segment_install(ctx["segment"]["id"])
    return ctx


def setup_installed_segment(*, shallow: bool = False, segment_overrides=None,
                            plan_overrides=None, project_overrides=None,
                            owner_overrides=None) -> dict:
    """Segment driven READY -> INSTALLING -> INSTALLED."""
    ctx = setup_installing_segment(shallow=shallow,
                                   segment_overrides=segment_overrides,
                                   plan_overrides=plan_overrides,
                                   project_overrides=project_overrides,
                                   owner_overrides=owner_overrides)
    ctx["segment"] = complete_segment_install(ctx["segment"]["id"])
    return ctx


def setup_backfilling_segment(*, shallow: bool = True, segment_overrides=None,
                              plan_overrides=None, project_overrides=None,
                              owner_overrides=None) -> dict:
    """Segment in BACKFILLING behind a CONFIRMED PASS inspection.

    Defaults to the shallow 2-lift CLASS_D segment so completion needs only
    two accepted lifts.
    """
    ctx = setup_installed_segment(shallow=shallow,
                                  segment_overrides=segment_overrides,
                                  plan_overrides=plan_overrides,
                                  project_overrides=project_overrides,
                                  owner_overrides=owner_overrides)
    if shallow:
        ctx["inspection"] = record_confirmed_inspection(
            ctx["segment"]["id"], slope_measured_pct=0.5, cover_depth_ft=1.0
        )
    else:
        ctx["inspection"] = record_confirmed_inspection(ctx["segment"]["id"])
    ctx["segment"] = start_segment_backfill(ctx["segment"]["id"])
    return ctx


def record_compaction_test(segment_id: str, lift_number: int, *,
                           recorder_id: str = FOREMAN_USER, **overrides) -> dict:
    return get_success_data(
        api_client.create_compaction_test(
            compaction_test_payload(segment_id, lift_number, **overrides),
            make_foreman_headers(recorder_id),
        )
    )


def review_compaction_test(test_id: str, decision: str, *,
                           reviewer_id: str = INSPECTOR_USER) -> dict:
    return get_success_data(
        api_client.review_compaction_test(
            test_id, decision, make_inspector_headers(reviewer_id)
        )
    )


def record_accepted_pass_test(segment_id: str, lift_number: int, *,
                              proctor: float = 100.0, field: float = 90.0,
                              **overrides) -> dict:
    """Record a PASS compaction test and have an inspector ACCEPT it."""
    test = record_compaction_test(
        segment_id, lift_number, proctor_max_density_pcf=proctor,
        field_density_pcf=field, **overrides,
    )
    return review_compaction_test(test["id"], "ACCEPT")


def setup_complete_segment(*, shallow: bool = True) -> dict:
    """Shallow segment driven all the way to COMPLETE (2 accepted PASS lifts).

    Returns the context plus "segment" in COMPLETE status.
    """
    ctx = setup_backfilling_segment(shallow=shallow)
    segment_id = ctx["segment"]["id"]
    lifts_required = ctx["segment"]["lifts_required"]
    for lift in range(1, lifts_required + 1):
        record_accepted_pass_test(segment_id, lift)
    ctx["segment"] = get_success_data(api_client.complete_segment(segment_id, FOREMAN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: as-built packages and closeout
# ---------------------------------------------------------------------------

def create_as_built(segment: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_as_built_package(
            as_built_payload(segment["id"], **overrides), PROJECT_MANAGER
        )
    )


def setup_closeout_ready_project() -> dict:
    """Full golden path: COMPLETE segment + ACCEPTED as-built, nothing open.

    Returns {"project", "owner", "ticket", "pothole", "segment", "plan",
             "inspection", "as_built"}.
    """
    ctx = setup_complete_segment()
    as_built = create_as_built(ctx["segment"])
    get_success_data(api_client.submit_as_built_package(as_built["id"], PROJECT_MANAGER))
    as_built = get_success_data(
        api_client.review_as_built_package(
            as_built["id"], "ACCEPT",
            make_utility_owner_rep_headers(ctx["owner"]["id"]),
        )
    )
    ctx["as_built"] = as_built
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: shutdown windows
# ---------------------------------------------------------------------------

def propose_shutdown_window(
    project: dict,
    owner: dict,
    segment: dict,
    window_start: str,
    window_end: str,
    *,
    expected_project_version: int | None = None,
) -> dict:
    """Create a PROPOSED window; refreshes the project version when omitted."""
    if expected_project_version is None:
        expected_project_version = get_project(project["id"])["version"]
    return get_success_data(
        api_client.create_shutdown_window(
            shutdown_window_payload(
                project["id"], owner["id"], segment["id"],
                expected_project_version,
                window_start=window_start, window_end=window_end,
            ),
            PROJECT_MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: discharge permits and readings
# ---------------------------------------------------------------------------

def create_discharge_permit(project: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_discharge_permit(
            discharge_permit_payload(project["id"], **overrides), PROJECT_MANAGER
        )
    )


def record_discharge_reading(permit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_discharge_reading(
            discharge_reading_payload(permit_id, **overrides), FOREMAN
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: unforeseen conditions and change orders
# ---------------------------------------------------------------------------

def create_unforeseen_condition(project: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_unforeseen_condition(
            unforeseen_condition_payload(project["id"], **overrides),
            PROJECT_MANAGER,
        )
    )


def create_change_order(
    project: dict,
    owner: dict,
    condition: dict,
    *,
    expected_project_version: int | None = None,
    **pricing,
) -> dict:
    """Create a DRAFT change order; refreshes the project version when omitted."""
    if expected_project_version is None:
        expected_project_version = get_project(project["id"])["version"]
    return get_success_data(
        api_client.create_change_order(
            change_order_payload(
                project["id"], condition["id"], owner["id"],
                expected_project_version, **pricing,
            ),
            PROJECT_MANAGER,
        )
    )


def submit_change_order(order_id: str, *, submitter_id: str = PM_USER) -> dict:
    return get_success_data(
        api_client.submit_change_order(
            order_id, make_project_manager_headers(submitter_id)
        )
    )


def approve_small_change_order(order_id: str, *, reviewer_id: str = PM_SECOND) -> dict:
    """Approve a below-threshold change order as a second ProjectManager."""
    return get_success_data(
        api_client.review_change_order(
            order_id, "APPROVE", make_project_manager_headers(reviewer_id)
        )
    )


def setup_approved_change_order(*, pricing=None, project_overrides=None) -> dict:
    """Project + owner + OPEN condition + APPROVED change order (287500 cents
    provisional by default). Returns {"project", "owner", "condition", "co"}."""
    project = create_project(**(project_overrides or {}))
    owner = create_utility_owner()
    condition = create_unforeseen_condition(project, description="rock at 8 ft")
    co = create_change_order(project, owner, condition, **(pricing or {}))
    submit_change_order(co["id"])
    co = approve_small_change_order(co["id"])
    return {"project": project, "owner": owner, "condition": condition, "co": co}
