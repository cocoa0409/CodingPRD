"""Outages, the SLA credit boundary, dismissal, and the derived credit balance."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_outage_event_payload,
    list_account_credits,
    setup_active_self_install_account, setup_resolved_outage,
)

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]


# ===========================================================================
# Queue A — boundary_precision_check: outage SLA minutes inclusive boundary
# ===========================================================================
def test_outage_at_240_minutes_qualifies_for_credit(api):
    """PRD §3.6: "issuing a credit requires the outage to be `RESOLVED` with `duration_minutes` of at least 240, and an attempt to credit an outage whose duration is below that threshold is rejected with `ERR_OUTAGE_BELOW_SLA`."

    A 240-minute outage is inclusive of the threshold and may be credited.

    Design: Difficulty/boundary_precision_check/outage_sla_minutes_inclusive_boundary
    """
    ctx = setup_resolved_outage(240, started_at_iso="2026-06-05T00:00:00Z")
    assert ctx["outage"]["duration_minutes"] == 240, \
        f"outage duration must be 240, got {ctx['outage']['duration_minutes']}"
    credited = validate_success(api.issue_outage_credit(ctx["outage"]["id"], NETOPS))
    assert credited["status"] == "CREDITED", \
        f"240-minute outage must reach CREDITED, got {credited['status']}"


def test_outage_at_239_minutes_below_sla_rejected(api):
    """PRD §3.6: "an attempt to credit an outage whose duration is below that threshold is rejected with `ERR_OUTAGE_BELOW_SLA`."

    A 239-minute outage is one minute below the 240 threshold.

    Design: Difficulty/boundary_precision_check/outage_sla_minutes_inclusive_boundary
    """
    ctx = setup_resolved_outage(239, started_at_iso="2026-06-06T00:00:00Z")
    assert ctx["outage"]["duration_minutes"] == 239, \
        f"outage duration must be 239, got {ctx['outage']['duration_minutes']}"
    resp = api.issue_outage_credit(ctx["outage"]["id"], NETOPS)
    validate_error(resp, ApiErrorId.ERR_OUTAGE_BELOW_SLA, expected_status=409)


# ===========================================================================
# Queue B — calculations: sub-SLA outage dismissed contributes nothing
# ===========================================================================
def test_dismissed_sub_sla_outage_creates_no_credit(api):
    """PRD §3.6: "Dismissing a `RESOLVED` outage moves it to `DISMISSED` with no further effect and is the path used for sub-threshold or otherwise non-qualifying outages."

    Design: Corner/calculations/outage_below_sla_dismiss_then_no_credit
    """
    ctx = setup_resolved_outage(120, started_at_iso="2026-06-05T00:00:00Z")
    assert ctx["outage"]["duration_minutes"] == 120, \
        f"outage duration must be 120, got {ctx['outage']['duration_minutes']}"
    dismissed = validate_success(api.dismiss_outage(ctx["outage"]["id"], NETOPS))
    assert dismissed["status"] == "DISMISSED", \
        f"outage must be DISMISSED, got {dismissed['status']}"
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    outage_credits = [c for c in credits if c["source_type"] == "OUTAGE"]
    assert outage_credits == [], \
        f"a dismissed sub-SLA outage must yield no OUTAGE credit, got {outage_credits}"


# ===========================================================================
# Queue B — cross_cutting: derived credit balance reconciles after outage credit
# ===========================================================================
def test_credit_balance_reconciles_after_outage_credit(api):
    """PRD §3.6: "the account's `credit_balance_cents` is recomputed to reflect it."
    PRD §3.11: "The account's `credit_balance_cents` is always the sum of the `amount_cents` of that account's un-applied credits."

    A 300-minute outage on an 8999-cent plan yields rhu(8999*300/43200)=62.

    Design: Corner/cross_cutting_complexity_layers/derived_credit_balance_reconciles_after_outage_credit
    """
    ctx = setup_resolved_outage(
        300, started_at_iso="2026-06-05T00:00:00Z",
        plan_overrides={"monthly_fee_cents": 8999, "overage_policy": "BILL",
                        "included_gb": 1000, "contract_term_months": 0, "etf_full_cents": 0})
    get_success_data(api.issue_outage_credit(ctx["outage"]["id"], NETOPS))
    acct = validate_success(api.get_account(ctx["account"]["id"], AGENT))
    assert acct["credit_balance_cents"] == 62, \
        f"credit_balance_cents must reconcile to 62, got {acct['credit_balance_cents']}"


# ===========================================================================
# Queue B — state_machines: outage resolve precondition
# ===========================================================================
def test_outage_resolve_end_before_start_rejected(api):
    """PRD §3.6: "The resolve request supplies the `ended_at_iso`, which must be strictly after the `started_at_iso`".
    PRD §3.12: "an interval whose end is not after its start, yields `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/outage_resolve_end_before_start_returns_invalid_request
    """
    ctx = setup_active_self_install_account()
    outage = get_success_data(api.create_outage_event(
        create_outage_event_payload(ctx["account"]["id"], ctx["cycle"]["id"],
                                    started_at_iso="2026-06-05T06:00:00Z"), NETOPS))
    resp = api.resolve_outage(outage["id"], {"ended_at_iso": "2026-06-05T05:00:00Z"}, NETOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


# ===========================================================================
# Queue B — errors: outage started outside cycle window
# ===========================================================================
def test_outage_started_outside_cycle_window_rejected(api):
    """PRD §3.6: "The `started_at_iso` must lie within the named cycle's window; an outage logged outside the window is rejected with `ERR_OUTAGE_OUTSIDE_CYCLE` (HTTP 422)."

    Design: Corner/errors/outage_started_outside_cycle_rejected
    """
    ctx = setup_active_self_install_account()
    resp = api.create_outage_event(
        create_outage_event_payload(ctx["account"]["id"], ctx["cycle"]["id"],
                                    started_at_iso="2026-07-05T00:00:00Z"), NETOPS)
    validate_error(resp, ApiErrorId.ERR_OUTAGE_OUTSIDE_CYCLE, expected_status=422)
