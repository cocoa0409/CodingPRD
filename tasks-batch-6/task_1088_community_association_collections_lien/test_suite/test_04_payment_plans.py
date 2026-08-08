"""Payment plans: breach/reinstate cycle, interval overlap vs adjacency,
completion precondition, breach threshold, OCC staleness, and the delinquency gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]


# --- non_linear_state_machine / nlsm_plan_breach_reinstate_cycle (queue A, >=2 tests) ---

def test_plan_breach_when_two_installments_missed(api):
    """PRD §3.5: "A plan may be moved `ACTIVE → BREACHED` only when `missed_count` is at
    least 2; a breach attempted below that threshold is refused with `ERR_PLAN_NOT_BREACHABLE`.
    Breaching returns the account from `PAYMENT_PLAN` to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/nlsm_plan_breach_reinstate_cycle
    """
    base = fixtures.setup_active_plan(api)  # clock 2026-05-01, plan first_due 2026-06-01
    plan_id, acct_id = base["plan"]["id"], base["account"]["id"]
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")  # all 3 installments due, paid 0 -> missed 3
    breached = validate_success(api.transition_payment_plan(plan_id, "BREACHED", AGENT))
    assert breached["status"] == "BREACHED"
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"


def test_plan_reinstate_after_catchup(api):
    """PRD §3.5: "Reinstating a `BREACHED` plan to `ACTIVE` requires that the account has
    caught up — `missed_count` back below 2 — and moves the account to `PAYMENT_PLAN`."

    Design: Difficulty/non_linear_state_machine/nlsm_plan_breach_reinstate_cycle
    """
    base = fixtures.setup_active_plan(api)
    plan_id, acct_id = base["plan"]["id"], base["account"]["id"]
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    validate_success(api.transition_payment_plan(plan_id, "BREACHED", AGENT))
    fixtures.create_payment(api, acct_id, 40000, "2026-08-01T00:00:00Z")  # missed -> 1 (<2)
    reinstated = validate_success(api.transition_payment_plan(plan_id, "ACTIVE", AGENT))
    assert reinstated["status"] == "ACTIVE"
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "PAYMENT_PLAN"


# --- resource_temporal_overlap / ov_plan_overlap_strict (queue A, >=2 tests) ---

def test_plan_final_due_date_computed(api):
    """PRD §3.5: "The plan's `final_due_date` is computed as the `first_due_date` plus thirty
    days for each installment beyond the first — that is, plus (`num_installments` minus one)
    times 30 days"

    Design: Difficulty/resource_temporal_overlap/ov_plan_overlap_strict
    """
    base = fixtures.setup_draft_plan(api)  # first_due 2026-06-01, num 3
    assert base["plan"]["final_due_date"] == "2026-07-31T00:00:00Z", base["plan"]["final_due_date"]


def test_second_plan_strict_overlap_rejected(api):
    """PRD §3.5: "A new plan may not be created if that interval strictly overlaps the
    interval of any non-terminal plan already on the account; such a collision yields
    `ERR_PLAN_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ov_plan_overlap_strict
    """
    base = fixtures.setup_draft_plan(api)  # plan1 [2026-06-01, 2026-07-31]
    acct_id = base["account"]["id"]
    v = base["account_version"]
    resp = api.create_payment_plan({
        "account_id": acct_id, "total_amount_cents": 30000, "installment_cents": 30000,
        "num_installments": 1, "first_due_date": "2026-07-01T00:00:00Z",
        "expected_account_version": v,
    }, AGENT)
    validate_error(resp, ApiErrorId.ERR_PLAN_OVERLAP.value)


# --- Queue B ---

def test_plan_adjacency_touching_endpoint_allowed(api):
    """PRD §3.5: "A new plan may not be created if that interval strictly overlaps the
    interval of any non-terminal plan already on the account; such a collision yields
    `ERR_PLAN_OVERLAP`."

    Design: Corner/validations/plan_adjacency_touching_endpoint_allowed
    """
    base = fixtures.setup_draft_plan(api)  # plan1 final_due 2026-07-31
    acct_id = base["account"]["id"]
    v = base["account_version"]
    resp = api.create_payment_plan({
        "account_id": acct_id, "total_amount_cents": 30000, "installment_cents": 30000,
        "num_installments": 1, "first_due_date": "2026-07-31T00:00:00Z",
        "expected_account_version": v,
    }, AGENT)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_plan_complete_requires_full_payment(api):
    """PRD §3.5: "A plan may be completed (`ACTIVE → COMPLETED`) only when `amount_paid_cents`
    has reached `total_amount_cents`, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/plan_complete_requires_full_payment
    """
    base = fixtures.setup_active_plan(api)  # no payments -> amount_paid 0 < total 60000
    resp = api.transition_payment_plan(base["plan"]["id"], "COMPLETED", AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_plan_breach_below_threshold_rejected(api):
    """PRD §3.5: "A plan may be moved `ACTIVE → BREACHED` only when `missed_count` is at
    least 2; a breach attempted below that threshold is refused with `ERR_PLAN_NOT_BREACHABLE`."

    Design: Corner/errors/error_plan_not_breachable_triggered
    """
    base = fixtures.setup_active_plan(api)  # clock 2026-05-01, first_due 2026-06-01 -> missed 0
    resp = api.transition_payment_plan(base["plan"]["id"], "BREACHED", AGENT)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_BREACHABLE.value)


def test_plan_create_stale_account_version_rejected(api):
    """PRD §2.6: "If it does not equal the account's current `version` — because another
    writer has since posted a payment, recorded a lien, or drafted a superseding plan and
    thereby advanced the account — the create is refused with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting/occ_plan_create_stale_account_version
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Xyl HOA"})
    acct_v0 = acct["version"]
    fixtures.create_assessment(api, acct["id"], 60000)
    validate_success(api.transition_account(acct["id"], "DELINQUENT", AGENT))  # bumps version
    resp = api.create_payment_plan({
        "account_id": acct["id"], "total_amount_cents": 60000, "installment_cents": 20000,
        "num_installments": 3, "first_due_date": "2026-06-01T00:00:00Z",
        "expected_account_version": acct_v0,
    }, AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_mark_delinquent_not_overdue_rejected(api):
    """PRD §3.1: "at least one assessment must be in `OPEN` or `PARTIAL` with a `due_date` at
    or before the logical-clock now (otherwise `ERR_NOT_DELINQUENT`)."

    Design: Corner/validations/mark_delinquent_not_overdue_returns_not_delinquent
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Lark HOA"})
    fixtures.create_assessment(api, acct["id"], 10000, due_date="2026-12-01T00:00:00Z")
    resp = api.transition_account(acct["id"], "DELINQUENT", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_DELINQUENT.value)
