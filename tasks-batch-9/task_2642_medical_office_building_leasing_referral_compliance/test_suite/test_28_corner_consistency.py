"""Consistency-model tests.

Two halves of one contract: a write's own response already carries everything
its cascade recomputed, and advancing the logical clock changes no status until
a daily close is run explicitly.
"""
from test_helpers import (
    LEASING_AGENT,
    PROPERTY_MANAGER,
    assert_invoice_breakdown,
    assert_mix_figures,
    expected_invoice_total,
    round_money,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_writes_are_immediately_visible_and_the_clock_alone_changes_nothing(api):
    """Execution's cascade is visible at once; the clock alone moves no status.

    PRD: "The system is immediately consistent."
    PRD: "Every derived field an operation affects is recomputed and persisted
    within that same request; there is no deferred reconciliation, no eventual
    settlement and no background worker other than the explicit daily close."
    PRD: "A caller that reads a building immediately after executing a lease in
    it sees the new tenant-mix figures."
    PRD: "Reading a resource never mutates it, never advances its `version` and
    never opens a compliance case; only the operations described in §3 and the
    daily close do that."
    PRD: "Advancing the clock changes the reference instant for lease
    commencement, appraisal expiry, invoice aging, the rolling risk window,
    remediation deadlines and shared-space windows — but it changes no entity's
    status by itself."
    PRD: "Status changes that depend only on the passage of time are produced
    exclusively by the daily close, a separate `PortfolioAdmin` capability that
    accepts an optional `close_note` and sweeps the whole estate against the
    clock's current reading."
    PRD: "A small number of fields are live rather than stored: `days_past_due`
    on an invoice is recomputed against the clock on every read, so it grows even
    on days when no close has run."
    PRD: "Its frozen counterpart, `days_past_due_at_flag`, is written once and
    never revised."

    Design: Corner/consistency_model/writes_are_immediately_visible_and_the_clock_alone_changes_nothing
    """
    ctx = fx.certified_lease(api)
    building_id = ctx["building"]["id"]
    suite_id = ctx["suite"]["id"]
    tenant_id = ctx["tenant"]["id"]
    lease_id = ctx["lease"]["id"]

    # The write's own response body already reports its result.
    executed = validate_success(
        api.execute_lease(lease_id, {"execution_note": "Countersigned"}, LEASING_AGENT), 200)
    assert executed["status"] == "EXECUTED", (
        "the execute response must itself report EXECUTED, got {}".format(executed["status"]))

    # The cascade is visible on the very next read, with nothing in between.
    suite = fx.read_suite(api, suite_id)
    assert suite["occupancy_status"] == "RESERVED", (
        "expected RESERVED immediately after execution, got {}".format(
            suite["occupancy_status"]))

    first_read = fx.read_building(api, building_id)
    assert_mix_figures(first_read, anchor_sf=0, independent_sf=5000, leased_sf=5000,
                       vacant_sf=95000, anchor_share_pct=0.0000, posture="BALANCED")

    # A repeat read neither recomputes nor converges: same version, same figures.
    second_read = fx.read_building(api, building_id)
    assert second_read["version"] == first_read["version"], (
        "a read must not advance the building version, got {} then {}".format(
            first_read["version"], second_read["version"]))
    assert_mix_figures(second_read, anchor_sf=0, independent_sf=5000, leased_sf=5000,
                       vacant_sf=95000, anchor_share_pct=0.0000, posture="BALANCED")
    for field in ("anchor_rentable_sf", "independent_rentable_sf", "leased_rentable_sf",
                  "vacant_rentable_sf", "anchor_share_pct", "tenant_mix_posture"):
        assert second_read[field] == first_read[field], (
            "{} changed between two identical reads: {} then {}".format(
                field, first_read[field], second_read[field]))

    # Reaching term_start does not commence the lease; an explicit act does.
    fx.set_clock_date(api, "2026-09-01")
    still_executed = fx.read_lease(api, lease_id)
    assert still_executed["status"] == "EXECUTED", (
        "passing term_start must not commence a lease, got {}".format(
            still_executed["status"]))
    assert still_executed["version"] == executed["version"], (
        "advancing the clock must not advance the lease version, got {}".format(
            still_executed["version"]))

    commenced = fx.commence(api, lease_id)
    assert commenced["status"] == "ACTIVE", (
        "expected ACTIVE after an explicit commencement, got {}".format(commenced["status"]))

    invoice = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    expected = expected_invoice_total(150000.00, 9.60, 5000)
    assert expected["total_amount"] == 16500.00, (
        "expected a total of 16500.00, got {}".format(expected["total_amount"]))
    assert_invoice_breakdown(invoice, expected)
    assert invoice["status"] == "ISSUED", (
        "a new invoice begins in ISSUED, got {}".format(invoice["status"]))
    assert invoice["days_past_due"] == 0, (
        "expected days_past_due 0 at issue, got {}".format(invoice["days_past_due"]))
    assert invoice["days_past_due_at_flag"] is None, (
        "expected days_past_due_at_flag null at issue")
    assert invoice["delinquency_tier_weight"] == 0, (
        "expected delinquency_tier_weight 0 at issue, got {}".format(
            invoice["delinquency_tier_weight"]))

    # Fifteen days past due and five days past grace, with no close run.
    fx.set_clock_date(api, "2026-09-20")
    before_rows, _before_meta = validate_paginated(
        api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    before = before_rows[0]
    assert before["id"] == invoice["id"]
    assert before["days_past_due"] == 15, (
        "days_past_due is live and must read 15, got {}".format(before["days_past_due"]))
    assert before["status"] == "ISSUED", (
        "the clock alone must not flag an invoice, got {}".format(before["status"]))
    assert before["days_past_due_at_flag"] is None, (
        "days_past_due_at_flag must stay null until a close flags the invoice")
    assert before["delinquency_tier_weight"] == 0, (
        "expected delinquency_tier_weight 0 before the close, got {}".format(
            before["delinquency_tier_weight"]))

    before_tenant = fx.read_tenant(api, tenant_id)
    assert before_tenant["referral_compliance_risk_score"] == 0, (
        "expected a rolling score of 0 before the close, got {}".format(
            before_tenant["referral_compliance_risk_score"]))
    assert before_tenant["strict_cumulative_risk_score"] == 0, (
        "expected a strict score of 0 before the close, got {}".format(
            before_tenant["strict_cumulative_risk_score"]))
    assert before_tenant["delinquency_event_count"] == 0, (
        "expected no delinquency events before the close, got {}".format(
            before_tenant["delinquency_event_count"]))
    assert before_tenant["compliance_watch_status"] == "CLEAR", (
        "expected CLEAR before the close, got {}".format(
            before_tenant["compliance_watch_status"]))

    # The explicit close is what turns the passage of time into a status change.
    fx.run_daily_close(api)

    after_rows, _after_meta = validate_paginated(
        api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    after = after_rows[0]
    assert after["status"] == "DELINQUENT", (
        "expected DELINQUENT after the close, got {}".format(after["status"]))
    assert after["days_past_due_at_flag"] == 15, (
        "expected days_past_due_at_flag 15, got {}".format(after["days_past_due_at_flag"]))
    assert after["delinquency_tier_weight"] == 15, (
        "a day count of 15 freezes a weight of 15, got {}".format(
            after["delinquency_tier_weight"]))
    assert after["days_past_due"] == 15, (
        "expected days_past_due 15, got {}".format(after["days_past_due"]))
    assert round_money(after["total_amount"]) == 16500.00, (
        "flagging must not re-price the invoice, got {}".format(after["total_amount"]))

    after_tenant = fx.read_tenant(api, tenant_id)
    assert after_tenant["referral_compliance_risk_score"] == 15, (
        "expected a rolling score of 15 on the first read after the close, got {}".format(
            after_tenant["referral_compliance_risk_score"]))
    assert after_tenant["strict_cumulative_risk_score"] == 15, (
        "expected a strict score of 15, got {}".format(
            after_tenant["strict_cumulative_risk_score"]))
    assert after_tenant["delinquency_event_count"] == 1, (
        "expected one delinquency event, got {}".format(
            after_tenant["delinquency_event_count"]))
    assert after_tenant["compliance_watch_status"] == "CLEAR", (
        "15 is below the 45 watch threshold, so the tenant stays CLEAR, got {}".format(
            after_tenant["compliance_watch_status"]))
