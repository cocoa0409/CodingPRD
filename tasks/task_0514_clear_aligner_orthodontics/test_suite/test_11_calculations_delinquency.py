"""Delinquency calculation corner cases (PRD §3.7)."""
from test_helpers import (
    validate_success,
    setup_plan_approved, create_financing,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]


def _activate_at_default_clock(api, contracted_check=240000):
    """Build a PLAN_APPROVED case (contracted 240000), set clock to the default
    instant, then activate financing (apr 0, term 12). Returns the financing id.
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=300000)
    assert ctx["case"]["total_contracted_cents"] == contracted_check
    validate_success(api.set_clock("2026-05-01T00:00:00Z", BILLING), 200)
    fin = create_financing(ctx["case"]["id"], term_months=12, down_payment_cents=0, apr_bps=0)
    validate_success(
        api.activate_financing_plan(
            fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
        ),
        200,
    )
    return fin["id"]


def test_three_late_installments_default(api):
    """PRD §3.7 Delinquency state: "When the late count is 3 or more - the
    default threshold being 3 - the state is `DEFAULTED`."
    PRD §3.7 Delinquency sweep: "moves each one whose `due_at` plus a grace
    period of 5 days is at or before the current logical clock from `SCHEDULED`
    to `LATE`".

    With the clock advanced past the third installment's due+grace, a sweep marks
    installments 1-3 LATE (>= threshold 3), so delinquency_state becomes
    DEFAULTED while billing_state stays ACTIVE.

    Design: Corner/calculations/delinquency_default_threshold_three_late
    """
    fin_id = _activate_at_default_clock(api)
    validate_success(api.set_clock("2026-08-10T00:00:00Z", BILLING), 200)
    swept = validate_success(api.run_delinquency_sweep(fin_id, BILLING), 200)
    assert swept["delinquency_state"] == "DEFAULTED", swept["delinquency_state"]
    assert swept["billing_state"] == "ACTIVE", swept["billing_state"]


def test_payment_post_recovers_from_delinquent_to_current(api):
    """PRD §3.7 Delinquency state: "evaluated after a payment posts (when a
    formerly-late installment has cleared), the recount of remaining late
    installments may move the plan back from `DELINQUENT` toward `CURRENT`, a
    genuine recovery".
    PRD §3.7 Delinquency state: "When the late count is 0, the state is
    `CURRENT`."

    After a sweep marks installment 1 LATE (DELINQUENT), posting installment 1
    clears the only LATE row, so the recount returns CURRENT - the instantaneous
    recovery variant.

    Design: Corner/calculations/delinquency_recovery_on_payment_post
    """
    fin_id = _activate_at_default_clock(api)
    validate_success(api.set_clock("2026-06-10T00:00:00Z", BILLING), 200)
    swept = validate_success(api.run_delinquency_sweep(fin_id, BILLING), 200)
    assert swept["delinquency_state"] == "DELINQUENT"
    validate_success(api.post_installment_payment(fin_id, 1, BILLING), 200)
    fin = validate_success(api.get_financing_plan(fin_id, BILLING), 200)
    assert fin["delinquency_state"] == "CURRENT", fin["delinquency_state"]
    assert fin["billing_state"] == "ACTIVE", fin["billing_state"]
