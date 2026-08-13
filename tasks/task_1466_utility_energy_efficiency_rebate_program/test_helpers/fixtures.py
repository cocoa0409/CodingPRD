"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: every TradeAlly-initiated call on an owned resource is
made with make_trade_ally_headers(ally["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK, TEST_DEFAULTS, THRESHOLDS
from .factories import (
    create_application_payload,
    create_evaluation_adjustment_payload,
    create_inspection_completion_payload,
    create_inspection_schedule_payload,
    create_line_item_payload,
    create_measure_payload,
    create_program_year_payload,
    create_savings_claim_payload,
    create_trade_ally_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_inspector_headers,
    make_regulator_headers,
    make_trade_ally_headers,
)

ADMIN = TEST_USERS["admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
PROCESSOR = TEST_USERS["processor_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


# ─── Tier 1: State Progression ────────────────────────────────────────────


def set_clock(to_iso8601: str = TEST_CLOCK) -> dict:
    """Drive the server logical clock. Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_program_year(budget_cap_cents=None, savings_goal_kwh=None, **overrides) -> dict:
    """Create a ProgramYear in DRAFT. Returns the created entity."""
    payload = create_program_year_payload(**overrides)
    if budget_cap_cents is not None:
        payload["budget_cap_cents"] = budget_cap_cents
    if savings_goal_kwh is not None:
        payload["savings_goal_kwh"] = savings_goal_kwh
    return get_success_data(api_client.create_program_year(payload, ADMIN))


def add_measure(program_year_id: str, base_rate_cents=None, deemed_kwh_per_unit=None, **overrides) -> dict:
    """Add a Measure to a program-year catalog. Returns the created entity."""
    payload = create_measure_payload(program_year_id, **overrides)
    if base_rate_cents is not None:
        payload["base_rate_cents"] = base_rate_cents
    if deemed_kwh_per_unit is not None:
        payload["deemed_kwh_per_unit"] = deemed_kwh_per_unit
    return get_success_data(api_client.create_measure(payload, ADMIN))


def open_program_year(program_year_id: str) -> dict:
    """DRAFT → OPEN. Returns the updated ProgramYear."""
    return get_success_data(api_client.open_program_year(program_year_id, ADMIN))


def create_open_program(budget_cap_cents=None, savings_goal_kwh=None,
                        measure_specs=None, set_logical_clock=True):
    """ProgramYear with a measure catalog, opened. Returns (program_year, measures).

    measure_specs: list of kwargs dicts for add_measure; defaults to one standard
    measure (base_rate 10000, deemed 100).
    """
    if set_logical_clock:
        set_clock()
    py = create_program_year(
        budget_cap_cents=budget_cap_cents, savings_goal_kwh=savings_goal_kwh
    )
    specs = measure_specs if measure_specs is not None else [{}]
    measures = [add_measure(py["id"], **spec) for spec in specs]
    py = open_program_year(py["id"])
    return py, measures


def create_ally(**overrides) -> dict:
    """Enroll a TradeAlly (PENDING). Returns the created entity."""
    return get_success_data(api_client.create_trade_ally(create_trade_ally_payload(**overrides), ADMIN))


def create_active_ally(**overrides) -> dict:
    """Enroll + activate a TradeAlly. Returns the ACTIVE entity."""
    ally = create_ally(**overrides)
    return get_success_data(api_client.activate_trade_ally(ally["id"], ADMIN))


# ─── Tier 2: Entity Hierarchy ──────────────────────────────────────────────


def create_draft_application(program_year: dict, ally: dict, **overrides) -> dict:
    """Create a DRAFT application owned by `ally` (ownership-threaded)."""
    payload = create_application_payload(program_year["id"], ally["id"], **overrides)
    return get_success_data(
        api_client.create_application(payload, make_trade_ally_headers(ally["id"]))
    )


def add_line_item(application: dict, measure: dict, quantity: int = 1, ally: dict = None) -> dict:
    """Add a line item to a DRAFT application as its owning ally."""
    owner = ally["id"] if ally else application["trade_ally_id"]
    payload = create_line_item_payload(application["id"], measure["id"], quantity=quantity)
    return get_success_data(
        api_client.create_line_item(payload, make_trade_ally_headers(owner))
    )


def attach_savings_claim(line_item: dict, ally: dict, claim_method="DEEMED",
                         pre_annual_kwh=None, post_annual_kwh=None) -> dict:
    """Attach a savings claim to a line item as the owning ally."""
    overrides = {"claim_method": claim_method}
    if pre_annual_kwh is not None:
        overrides["pre_annual_kwh"] = pre_annual_kwh
    if post_annual_kwh is not None:
        overrides["post_annual_kwh"] = post_annual_kwh
    payload = create_savings_claim_payload(line_item["id"], **overrides)
    return get_success_data(
        api_client.create_savings_claim(payload, make_trade_ally_headers(ally["id"]))
    )


# ─── Tier 3: Full Lifecycle Shortcuts ──────────────────────────────────────


def submit_application(application: dict, ally: dict = None) -> dict:
    """DRAFT → SUBMITTED as the owning ally. Returns the submitted application."""
    owner = ally["id"] if ally else application["trade_ally_id"]
    return get_success_data(
        api_client.submit_application(application["id"], make_trade_ally_headers(owner))
    )


def build_submitted_application(program_year: dict, ally: dict, measure: dict,
                                quantity: int = 1, claim=None, **app_overrides):
    """DRAFT → +line → optional savings claim → SUBMITTED.

    claim: None (no claim), "DEEMED", or ("MEASURED", pre, post).
    Returns (application, line_item).
    """
    app = create_draft_application(program_year, ally, **app_overrides)
    line = add_line_item(app, measure, quantity=quantity, ally=ally)
    if claim == "DEEMED":
        attach_savings_claim(line, ally, "DEEMED")
    elif isinstance(claim, tuple) and claim[0] == "MEASURED":
        attach_savings_claim(line, ally, "MEASURED",
                             pre_annual_kwh=claim[1], post_annual_kwh=claim[2])
    app = submit_application(app, ally)
    return app, line


def verify_application(application: dict, inspector_user_id: str = "test-inspector-1") -> dict:
    """SUBMITTED/POST_INSPECTION → VERIFIED. Returns the verified application."""
    return get_success_data(
        api_client.verify_application(application["id"], make_inspector_headers(inspector_user_id))
    )


def build_verified_application(program_year: dict, ally: dict, measure: dict,
                               inspector_user_id: str = "test-inspector-1", **kwargs):
    """Full chain through VERIFIED. Returns (application, line_item)."""
    app, line = build_submitted_application(program_year, ally, measure, **kwargs)
    app = verify_application(app, inspector_user_id)
    return app, line


def approve_application(application: dict, admin_user_id: str = "test-admin-1") -> dict:
    """VERIFIED → APPROVED. Returns the approved application."""
    return get_success_data(
        api_client.approve_application(application["id"], make_admin_headers(admin_user_id))
    )


def build_approved_application(program_year: dict, ally: dict, measure: dict, **kwargs):
    """Full chain through APPROVED. Returns (application, line_item)."""
    app, line = build_verified_application(program_year, ally, measure, **kwargs)
    app = approve_application(app)
    return app, line


def pay_application(application: dict) -> dict:
    """APPROVED → PAID. Returns the paid application."""
    return get_success_data(api_client.pay_application(application["id"], PROCESSOR))


def build_paid_application(program_year: dict, ally: dict, measure: dict, **kwargs):
    """Full chain through PAID. Returns (application, line_item)."""
    app, line = build_approved_application(program_year, ally, measure, **kwargs)
    app = pay_application(app)
    return app, line


# ─── Tier 4: Inspection-Obligation Targeting ───────────────────────────────


def build_application_requiring_inspection(program_year: dict, ally: dict,
                                           large_measure: dict, **app_overrides):
    """Application flagged inspection_required via the large-claim override
    (measure deemed_kwh_per_unit >= 10000), then PRE inspection scheduled.

    Returns (application, line_item, pre_inspection). Application lands in
    PRE_INSPECTION.
    """
    app, line = build_submitted_application(
        program_year, ally, large_measure, quantity=1, **app_overrides
    )
    assert app["inspection_required"] is True, (
        f"Setup failed: expected inspection_required=True, got {app['inspection_required']}"
    )
    insp = get_success_data(
        api_client.schedule_pre_inspection(
            app["id"], create_inspection_schedule_payload(), ADMIN
        )
    )
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    return app, line, insp


def complete_inspection(inspection: dict, outcome="PASSED", fail_reason=None,
                        inspector_user_id: str = "test-inspector-1") -> dict:
    """Complete a PENDING inspection. Returns the completed Inspection."""
    overrides = {}
    if fail_reason is not None:
        overrides["fail_reason"] = fail_reason
    payload = create_inspection_completion_payload(outcome=outcome, **overrides)
    return get_success_data(
        api_client.complete_inspection(
            inspection["id"], payload, make_inspector_headers(inspector_user_id)
        )
    )


def build_post_inspection_application(program_year: dict, ally: dict, large_measure: dict,
                                      **app_overrides):
    """Application walked SUBMITTED → PRE_INSPECTION → (PRE PASSED) → POST_INSPECTION.

    Returns (application, line_item, pre_inspection).
    """
    app, line, pre = build_application_requiring_inspection(
        program_year, ally, large_measure, **app_overrides
    )
    complete_inspection(pre, "PASSED")
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    return app, line, pre


def drive_inspection_history(program_year: dict, ally: dict, large_measure: dict,
                             outcomes: list):
    """Complete one PRE inspection per outcome ("PASSED"/"FAILED") for the ally.

    Each outcome drives a fresh application (large-claim measure, so every
    application is inspection-required) through submit → schedule → complete.
    Returns list of (application, inspection).
    """
    results = []
    for i, outcome in enumerate(outcomes, start=1):
        app, line, insp = build_application_requiring_inspection(
            program_year, ally, large_measure,
            service_address=f"{1000 + i} Performance Way",
            invoice_date="2026-08-10",
        )
        completed = complete_inspection(
            insp, outcome,
            fail_reason="Install failed verification" if outcome == "FAILED" else None,
        )
        results.append((app, completed))
    return results


# ─── Tier 5: Finalization / Terminal State ─────────────────────────────────


def build_closed_program_with_paid_app(budget_cap_cents=None, savings_goal_kwh=None,
                                       measure_specs=None, quantity: int = 5,
                                       claim="DEEMED"):
    """Open program → one application verified + approved → close (auto-pays it).

    Returns (program_year, measures, ally, application, line_item).
    """
    py, measures = create_open_program(
        budget_cap_cents=budget_cap_cents,
        savings_goal_kwh=savings_goal_kwh,
        measure_specs=measure_specs,
    )
    ally = create_active_ally()
    app, line = build_approved_application(
        py, ally, measures[0], quantity=quantity, claim=claim
    )
    py = get_success_data(api_client.close_program_year(py["id"], ADMIN))
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    return py, measures, ally, app, line


def build_reported_program(realization_rate_pct=80, **kwargs):
    """Full lifecycle through REPORTED. Returns (program_year, adjustment, app)."""
    py, measures, ally, app, line = build_closed_program_with_paid_app(**kwargs)
    adj = get_success_data(
        api_client.create_evaluation_adjustment(
            create_evaluation_adjustment_payload(
                py["id"], realization_rate_pct=realization_rate_pct
            ),
            REGULATOR,
        )
    )
    py = get_success_data(api_client.report_program_year(py["id"], REGULATOR))
    return py, adj, app


def get_program_year(program_year_id: str) -> dict:
    return get_success_data(api_client.get_program_year(program_year_id, ADMIN))


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, ADMIN))


def get_trade_ally(ally_id: str) -> dict:
    return get_success_data(api_client.get_trade_ally(ally_id, ADMIN))


def get_line_item(line_item_id: str) -> dict:
    return get_success_data(api_client.get_line_item(line_item_id, ADMIN))


def get_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, ADMIN))


def get_savings_claim(savings_claim_id: str) -> dict:
    return get_success_data(api_client.get_savings_claim(savings_claim_id, ADMIN))


def list_line_items_for_application(application_id: str) -> list:
    res = api_client.list_line_items(ADMIN, params={"application_id": application_id})
    body = res.json()
    return body["data"]
