"""State-machine transitions and lifecycle: quote revise cycle, install-job
complete/abort fork, cross-entity gating (scope finalize, crew scheduling),
design reject branch, callback resolution, terminal-state lockdown, time-gated
transitions, version increments, and immediate rollup visibility.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty: non_linear_state_machine ────────────────────────────────────
def test_quote_revise_spawns_draft_successor(api):
    """PRD §3.6: "Revision moves the original quote from `SENT` to `REVISED`,
    creates a successor quote in `DRAFT` that clones the original's
    `design_layout_id` and `base_prep_scope_id` (and accepts an optional new
    `promo_code` and `deposit_pct`), and sets the original's
    `superseded_by_quote_id` to the successor's id — a cyclic loop back to a fresh
    `DRAFT` row."

    Design: Difficulty/non_linear_state_machine/quote_revise_cycle_spawns_successor
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    q1 = ctx["quote"]["id"]
    successor = validate_success(
        api_client.revise_quote(pid, q1, {"deposit_pct": 0.20}, SALES),
        expected_status=201,
    )
    assert successor["status"] == "DRAFT", "successor is a fresh DRAFT quote"
    assert successor["deposit_pct"] == 0.20


def test_quote_revise_marks_original_revised_and_superseded(api):
    """PRD §3.6: "Revision moves the original quote from `SENT` to `REVISED`,
    creates a successor quote in `DRAFT` that clones the original's
    `design_layout_id` and `base_prep_scope_id` (and accepts an optional new
    `promo_code` and `deposit_pct`), and sets the original's
    `superseded_by_quote_id` to the successor's id — a cyclic loop back to a fresh
    `DRAFT` row."

    Design: Difficulty/non_linear_state_machine/quote_revise_cycle_spawns_successor
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    q1 = ctx["quote"]["id"]
    successor = validate_success(
        api_client.revise_quote(pid, q1, {"deposit_pct": 0.20}, SALES), expected_status=201
    )
    original = validate_success(api_client.get_quote(pid, q1, SALES))
    assert original["status"] == "REVISED"
    assert original["superseded_by_quote_id"] == successor["id"]


def test_complete_install_activates_warranty_and_advances_project(api):
    """PRD §3.9: "Completion moves the job's `status` from `IN_PROGRESS` to
    `COMPLETED` (the first cascade hop); bubbles the project's workflow dimension
    from `SCHEDULED` to `INSTALLED`; activates any `PENDING` warranty plan on the
    project by moving it from `PENDING` to `ACTIVE`, setting its `start_at` to the
    completed job's `scheduled_end` and its `expires_at` to the start plus its
    coverage window (the second cascade hop); nudges the project's
    `finance_status` to `BALANCE_DUE`; and increments both the install job's
    `version` and the project's `version`."

    Design: Difficulty/non_linear_state_machine/install_job_branch_complete_vs_abort_divergent_effects
    """
    ctx = fx.setup_scheduled_project(
        warranty_tier="BASIC",
        scheduled_start="2026-04-05T09:00:00Z",
        scheduled_end="2026-04-05T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    fx.set_clock("2026-04-05T09:00:00Z")
    validate_success(api_client.start_install_job(pid, jid, SCHED))
    job = validate_success(api_client.complete_install_job(pid, jid, SCHED))
    assert job["status"] == "COMPLETED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "INSTALLED"
    assert project["finance_status"] == "BALANCE_DUE"
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    assert data[0]["status"] == "ACTIVE", "COMPLETE branch activates the PENDING warranty"


def test_abort_install_does_not_activate_warranty(api):
    """PRD §3.9: "unlike completion, an abort activates no warranty and makes no
    finance change — it only frees the crew."

    Design: Difficulty/non_linear_state_machine/install_job_branch_complete_vs_abort_divergent_effects
    """
    from test_helpers import validate_paginated
    ctx = fx.setup_scheduled_project(
        warranty_tier="BASIC",
        scheduled_start="2026-04-05T09:00:00Z",
        scheduled_end="2026-04-05T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    job = validate_success(api_client.abort_install_job(pid, jid, SCHED))
    assert job["status"] == "ABORTED"
    data, _meta = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    assert data[0]["status"] == "PENDING", "ABORT branch leaves the warranty PENDING"


# ─── Difficulty: cross_entity_state_dependency ───────────────────────────────
def test_finalize_scope_blocked_when_design_still_draft(api):
    """PRD §3.4: "A `SalesRep` finalizes a scope only while it is in `DRAFT` status
    and only when the design layout it references is `ACCEPTED`"
    PRD §3.6: "Any state transition attempted against a quote that is not in the
    required starting state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/finalize_scope_requires_accepted_design
    """
    # MEASURED project with a DRAFT (un-accepted) design and a DRAFT scope on it.
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    design = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    scope = fx.create_base_prep_scope(pid, design["id"], base_depth_in=3)
    resp = api_client.finalize_base_prep_scope(pid, scope["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api_client.list_base_prep_scopes(pid, SALES))
    assert data[0]["status"] == "DRAFT", "scope stays DRAFT after rejected finalize"


def test_finalize_scope_succeeds_after_design_accepted(api):
    """PRD §3.4: "A `SalesRep` finalizes a scope only while it is in `DRAFT` status
    and only when the design layout it references is `ACCEPTED`; finalization moves
    the scope's `status` from `DRAFT` to `FINALIZED`, freezes the excavation and
    drainage cost figures at their finalize-time values, and increments the scope's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/finalize_scope_requires_accepted_design
    """
    # Once the referenced design is ACCEPTED, finalize is permitted.
    ctx = fx.setup_designed_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=3)
    finalized = validate_success(api_client.finalize_base_prep_scope(pid, scope["id"], SALES))
    assert finalized["status"] == "FINALIZED"


def test_schedule_putting_green_uncertified_crew_rejected(api):
    """PRD §3.8: "The assigned crew must be certified for the project's variant — a
    `PUTTING_GREEN` project requires the crew's `certified_putting`, and a
    `PLAYGROUND` project requires the crew's `certified_playground` — and the crew
    must be active; a crew lacking the required certification or marked inactive is
    rejected with `ERR_CREW_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_install_requires_deposit_paid_and_certified_crew
    """
    # PUTTING_GREEN project deposit-paid (net 420). Crew not certified_putting.
    ctx = fx.setup_deposit_paid_project(
        variant="PUTTING_GREEN",
        base_depth_in=4,
        deposit_cents=180558,
        measure_overrides={"gross_area_sqft": 400, "longest_run_ft": 10, "slope_pct": 1.0},
        turf_overrides={"price_per_sqft_cents": 700, "putting_rated": True, "pile_height_mm": 15, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 120, "coverage_lbs_per_sqft": 3},
    )
    pid = ctx["project"]["id"]
    crew = fx.create_crew(name="Uncertified Crew", daily_capacity_sqft=2000, certified_putting=False)
    resp = api_client.create_install_job(
        pid,
        f.create_install_job_payload(crew["id"], "2026-04-20T09:00:00Z", "2026-04-20T17:00:00Z"),
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED.value)
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "DEPOSIT_PAID"
    assert project["variant"] == "PUTTING_GREEN"


def test_schedule_putting_green_certified_crew_succeeds(api):
    """PRD §3.8: "The assigned crew must be certified for the project's variant — a
    `PUTTING_GREEN` project requires the crew's `certified_putting`, and a
    `PLAYGROUND` project requires the crew's `certified_playground` — and the crew
    must be active; a crew lacking the required certification or marked inactive is
    rejected with `ERR_CREW_NOT_CERTIFIED`."
    PRD §3.8: "A successful scheduling creates the install job in `SCHEDULED`
    status, copies the project's `billable_area_sqft` onto the job's
    `install_area_sqft`, advances the project's workflow dimension from
    `DEPOSIT_PAID` to `SCHEDULED`, and increments the project's `version`."

    Design: Difficulty/cross_entity_state_dependency/schedule_install_requires_deposit_paid_and_certified_crew
    """
    ctx = fx.setup_deposit_paid_project(
        variant="PUTTING_GREEN",
        base_depth_in=4,
        deposit_cents=180558,
        measure_overrides={"gross_area_sqft": 400, "longest_run_ft": 10, "slope_pct": 1.0},
        turf_overrides={"price_per_sqft_cents": 700, "putting_rated": True, "pile_height_mm": 15, "roll_width_ft": 15},
        infill_overrides={"price_per_sqft_cents": 120, "coverage_lbs_per_sqft": 3},
    )
    pid = ctx["project"]["id"]
    crew = fx.create_crew(name="Certified Putting Crew", daily_capacity_sqft=2000, certified_putting=True)
    job = validate_success(
        api_client.create_install_job(
            pid,
            f.create_install_job_payload(crew["id"], "2026-04-20T09:00:00Z", "2026-04-20T17:00:00Z"),
            SCHED,
        ),
        expected_status=201,
    )
    assert job["status"] == "SCHEDULED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "SCHEDULED"


# ─── Corner: state_machines ──────────────────────────────────────────────────
def test_reject_design_sets_rejected_no_project_advance(api):
    """PRD §3.2: "Rejecting a design is the sibling branch: a `SalesRep` may reject
    a design while it is in `DRAFT` status, which moves its `status` from `DRAFT`
    to `REJECTED`, increments only the design's `version`, and makes no change at
    the project level — it is a pure branch divergence with none of the acceptance
    cascade."

    Design: Corner/state_machines/design_reject_branch_sets_rejected_no_project_change
    """
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    design = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    rejected = validate_success(api_client.reject_design_layout(pid, design["id"], SALES))
    assert rejected["status"] == "REJECTED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "MEASURED", "reject makes no project-level change"
    assert project["variant"] is None


def test_resolve_covered_callback_recomputes_open_count(api):
    """PRD §3.11: "Resolving moves an `IN_PROGRESS` callback to `RESOLVED`,
    recomputes the project's `open_callback_count`, and — if the callback is
    billable — creates a `BALANCE` payment for its `charge_cents` in `PENDING`
    status; resolving increments the project's `version`."
    PRD §3.11: "The workmanship reasons `SEAM_LIFT`, `WRINKLE`, and `DRAINAGE`
    always qualify under an active plan."

    Design: Corner/state_machines/callback_open_to_resolved_recomputes_open_count
    """
    ctx = fx.setup_paid_in_full_project(warranty_tier="PREMIUM")
    pid = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    from test_helpers import validate_paginated
    wdata, _ = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    warranty_id = wdata[0]["id"]
    cb = validate_success(
        api_client.create_callback(
            pid, f.create_callback_payload("SEAM_LIFT", warranty_plan_id=warranty_id), cust
        ),
        expected_status=201,
    )
    assert cb["billable"] is False
    assert cb["charge_cents"] == 0
    validate_success(api_client.start_callback(pid, cb["id"], SCHED))
    resolved = validate_success(api_client.resolve_callback(pid, cb["id"], SCHED))
    assert resolved["status"] == "RESOLVED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["open_callback_count"] == 0


def test_accept_void_sibling_quote_rejected(api):
    """PRD §3.6: "Acceptance moves the quote from `SENT` to `ACCEPTED`; voids every
    other non-terminal quote on the project (any sibling quote in `DRAFT`, `SENT`,
    or `REVISED` moves to `VOID`)"
    PRD §3.6: "Any state transition attempted against a quote that is not in the
    required starting state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_quote_void_cannot_transition
    """
    ctx = fx.setup_finalized_scope_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    did, sid = ctx["design"]["id"], ctx["scope"]["id"]
    cust_id = ctx["customer"]["id"]
    q1 = fx.create_quote(pid, did, sid, deposit_pct=0.30)
    fx.send_quote(pid, q1["id"])
    q2 = fx.create_quote(pid, did, sid, deposit_pct=0.40)
    fx.send_quote(pid, q2["id"])
    v = fx.project_version(pid)
    fx.accept_quote(pid, q1["id"], cust_id, expected_version=v)
    # q2 is now VOID.
    q2_read = validate_success(api_client.get_quote(pid, q2["id"], SALES))
    assert q2_read["status"] == "VOID"
    v_now = fx.project_version(pid)
    resp = api_client.accept_quote(pid, q2["id"], f.accept_quote_payload(v_now), make_customer_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_install_before_scheduled_start_rejected(api):
    """PRD §3.9: "A `Scheduler` starts a job that is `SCHEDULED`, but only once the
    logical clock has reached the job's `scheduled_start`"
    PRD §3.9: "A start, complete, or abort attempted against a job not in the
    required state is rejected with `ERR_INVALID_STATE`."
    PRD §3.13: "At server startup the clock reads exactly 2026-04-01T00:00:00Z and
    never falls back to wall-clock time before it is first set."

    Design: Corner/state_machines/start_install_before_scheduled_start_invalid_state
    """
    ctx = fx.setup_scheduled_project(
        scheduled_start="2026-05-01T09:00:00Z",
        scheduled_end="2026-05-01T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    # Clock left at startup default 2026-04-01, before scheduled_start 2026-05-01.
    resp = api_client.start_install_job(pid, jid, SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api_client.list_install_jobs(pid, ADMIN))
    assert data[0]["status"] == "SCHEDULED"


def test_sent_quote_expires_after_ttl(api):
    """PRD §3.6: "A quote that has been `SENT` and not accepted expires once the
    logical clock reaches its creation time plus the quote time-to-live of 30 days;
    on that condition a `SENT` quote moves to `EXPIRED` and its `version`
    increments."

    Design: Corner/state_machines/quote_sent_to_expired_after_ttl
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    qid = ctx["quote"]["id"]
    # Created at clock default 2026-04-01; advance well past 30 days.
    fx.set_clock("2026-12-31T00:00:00Z")
    quote = validate_success(api_client.get_quote(pid, qid, ADMIN))
    assert quote["status"] == "EXPIRED"


# ─── Corner: entities (creation/defaults) + cross_cutting/version + consistency ─
def test_create_project_defaults(api):
    """PRD §3.1: "A freshly created project starts with `workflow_status` of
    `DRAFT` and `finance_status` of `UNBILLED`, and every computed rollup —
    billable area, contract total, deposit and balance paid, refunded amount,
    outstanding balance, and open callback count — begins at zero, with `variant`
    and the contract figure unset until later milestones."

    Design: Corner/entities/create_project_returns_201_with_defaults
    """
    customer = fx.create_customer()
    project = validate_success(
        api_client.create_project(f.create_project_payload(customer["id"], site_address="1 Test St"), SALES),
        expected_status=201,
    )
    assert project["workflow_status"] == "DRAFT"
    assert project["finance_status"] == "UNBILLED"
    assert project["version"] == 1
    assert project["billable_area_sqft"] == 0
    assert project["open_callback_count"] == 0


def test_site_measure_defaults_applied(api):
    """PRD §3.1: "an optional `obstruction_area_sqft` for non-turf cutouts such as
    trees and beds (which must be at least zero and defaults to zero), the
    `longest_run_ft` (the longest straight dimension, greater than zero), the
    `slope_pct` (the average grade percentage, at least zero), and an optional
    `soil_drains_freely` flag (defaulting to true)."
    PRD §3.1: "Each new measure is created with a `status` of `RECORDED`"

    Design: Corner/entities/site_measure_defaults_applied_when_omitted
    """
    customer = fx.create_customer()
    project = fx.create_project(customer["id"])
    measure = validate_success(
        api_client.create_site_measure(
            project["id"],
            {"gross_area_sqft": 600, "longest_run_ft": 20, "slope_pct": 1.0},
            SALES,
        ),
        expected_status=201,
    )
    assert measure["obstruction_area_sqft"] == 0
    assert measure["soil_drains_freely"] is True
    assert measure["status"] == "RECORDED"


def test_project_version_increments_on_first_measure(api):
    """PRD §2.4: "a `version` field, a system-managed integer that starts at 1 and
    increases by one on every mutation."
    PRD §3.1: "Recording the very first measure advances the project from `DRAFT`
    to `MEASURED` and increments the project's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    customer = fx.create_customer()
    project = validate_success(
        api_client.create_project(f.create_project_payload(customer["id"]), SALES),
        expected_status=201,
    )
    assert project["version"] == 1
    fx.create_site_measure(project["id"])
    reread = validate_success(api_client.get_project(project["id"], ADMIN))
    assert reread["version"] == 2
    assert reread["workflow_status"] == "MEASURED"


def test_accept_design_immediately_exposes_rollups(api):
    """PRD §3.2: "A successful acceptance moves the design's `status` from `DRAFT`
    to `ACCEPTED`; copies the design's `variant` onto the project's `variant`;
    recomputes the project's `billable_area_sqft` as the accepted design's net
    area; advances the project's workflow dimension from `MEASURED` to `DESIGNED`"

    Design: Corner/consistency_model/immediate_visibility_of_computed_rollups
    """
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    design = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    accepted = validate_success(api_client.accept_design_layout(pid, design["id"], SALES))
    assert accepted["status"] == "ACCEPTED"
    # Same-flow re-read shows the rollups immediately.
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["billable_area_sqft"] == 648.0
    assert project["variant"] == "STANDARD"
    assert project["workflow_status"] == "DESIGNED"
