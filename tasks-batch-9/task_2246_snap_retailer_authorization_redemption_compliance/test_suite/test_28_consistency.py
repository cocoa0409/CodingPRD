"""Immediate consistency: every derived field is visible in the response that
causes it, and the cascade up to the owner rollup is visible in the same instant.
"""
from test_helpers import (
    ADMIN,
    AUG_01,
    api_client,
    assert_fields,
    assert_inspector_minutes,
    assert_instant,
    assert_row_count,
    authorized_store,
    findings_payload,
    four_closed_periods,
    issue_determination,
    ok,
    pending_visit_application,
    refresh_owner,
    refresh_store,
    replied_case,
    INV_PASS,
)


def test_every_derived_field_is_visible_in_the_same_response_that_causes_it():
    """The findings response itself already carries all six computed verification
    fields, and the very next reads of the application, the inspector and the visit
    -- with no intervening write -- already show the advanced status, the released
    minutes and a body identical to the one the write returned.

    The findings write computes all six figures at once: "The count of qualifying
    categories becomes `verified_qualifying_categories`; the count of those
    qualifying categories that carry at least one perishable variety among the deep
    varieties that made them qualify becomes `verified_perishable_categories`; and
    `verified_criterion_a_pass` is true when `verified_qualifying_categories` equals
    4 and `verified_perishable_categories` is at least 2." "Two shelf measurements
    are derived at the same moment." And the same write moves two other aggregates:
    "Submitting findings also sets `findings_submitted_at` to the current
    logical-clock instant and releases the visit's `window_minutes` from the
    inspector's `committed_minutes`." "When `verified_criterion_a_pass` is true
    **and** `shelf_discrepancy_flag` is false, the application advances from
    `PENDING_VISIT` to `UNDER_REVIEW`, its `verified_criterion_pass` is set to true,
    and its `hold_reason_code` is cleared."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_causes_it
    """
    context = pending_visit_application()

    findings = ok(
        api_client.submit_findings(
            context.visit["id"],
            findings_payload(
                observed_staple_shelf_linear_feet=30,
                observed_inventory_lines=INV_PASS,
            ),
            context.inspector_h,
        )
    )

    for field in (
        "verified_qualifying_categories",
        "verified_perishable_categories",
        "verified_criterion_a_pass",
        "depth_of_stock_pass",
        "shelf_discrepancy_bps",
        "shelf_discrepancy_flag",
    ):
        assert findings[field] is not None, (field, findings)
    assert_fields(
        findings,
        {
            "status": "FINDINGS_SUBMITTED",
            "verified_qualifying_categories": 4,
            "verified_perishable_categories": 3,
            "verified_criterion_a_pass": True,
            "depth_of_stock_pass": True,
            "shelf_discrepancy_bps": 0,
            "shelf_discrepancy_flag": False,
        },
        "findings response body",
    )
    assert_instant(findings["findings_submitted_at"], AUG_01, "findings_submitted_at")

    application = ok(
        api_client.get_application(context.application["id"], context.owner_h)
    )
    assert_fields(
        application,
        {"status": "UNDER_REVIEW", "verified_criterion_pass": True},
        "application read straight after the findings",
    )

    inspector = ok(api_client.get_inspector(context.inspector["id"], ADMIN))
    assert_inspector_minutes(inspector, 0)

    reread = ok(api_client.get_store_visit(context.visit["id"], context.inspector_h))
    assert reread == findings, (reread, findings)


def test_cascaded_cross_aggregate_fields_are_immediate_too():
    """The determination response carries the case's own penalty figures, and in the
    same instant the ledger endpoint and the owner rollup -- a grandparent of the
    case -- already reflect them, with the store's sanction dimension unmoved by the
    determination.

    One write re-derives all three levels: "for `CMP_IN_LIEU` only -- computes
    `cmp_basis_variant`, `cmp_basis_period_ids`, `avg_monthly_redemption_cents`,
    `monthly_penalty_cents`, `cmp_amount_cents` and `cmp_capped`, then writes a
    `CMP_ASSESSED` ledger entry for the full `cmp_amount_cents` and re-derives the
    case's `cmp_outstanding_cents`, the owner's `cmp_outstanding_cents` and the
    owner's `sanction_flag`." The rollup's own rule decides the flag: "`sanction_flag`
    is then decided by an **ordered** test, not an independent one: it reads
    `PERMANENTLY_DISQUALIFIED` when the permanent-disqualification count is at least
    1, otherwise `HAS_ACTIVE_CMP_DEBT` when the outstanding penalty total is greater
    than zero, otherwise `CLEAR`." And the ledger row carries the running balance: "a
    `balance_after_cents` giving the running balance through that row."

    Design: Corner/consistency_model/cascaded_cross_aggregate_fields_are_immediate_too
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    case = replied_case(context, with_election=True)

    determined = issue_determination(case["id"], "CMP_IN_LIEU")
    assert_fields(
        determined,
        {
            "status": "DETERMINED",
            "sanction_type": "CMP_IN_LIEU",
            "cmp_amount_cents": 423456,
            "cmp_outstanding_cents": 423456,
        },
        "determination response body",
    )

    entries = assert_row_count(api_client.list_penalty_ledger(case["id"], ADMIN), 1)
    assert_fields(
        entries[0],
        {
            "entry_type": "CMP_ASSESSED",
            "amount_cents": 423456,
            "balance_after_cents": 423456,
        },
        "ledger row read in the same instant",
    )

    assert_fields(
        refresh_owner(context.owner_id),
        {"cmp_outstanding_cents": 423456, "sanction_flag": "HAS_ACTIVE_CMP_DEBT"},
        "owner rollup read in the same instant",
    )
    assert refresh_store(context.store_id)["sanction_status"] == "CHARGED"
