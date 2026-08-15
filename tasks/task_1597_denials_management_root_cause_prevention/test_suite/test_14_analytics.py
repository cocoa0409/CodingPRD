"""Overturn-rate analytics: per-row cells and the pooled totals row (PRD §3.8)."""
from test_helpers import (
    attach_document,
    make_appeal,
    make_denial,
    make_queued_denial,
    make_remittance_code,
    record_outcome,
    set_clock,
    setup_catalog,
    setup_denial_with_submitted_appeal,
    validate_success,
)

TOTALS_CITE = (
    'PRD §3.8: "The response carries `group_by`, the `rows` array, and a `totals` object '
    'whose percentage is computed from the unrounded aggregate counts pooled across all '
    'rows — 100 times the pooled overturned-plus-half-partial sum divided by the pooled '
    'resolved count, rounded half-up to two decimals in a single rounding — and is never '
    'the sum or average of the rounded per-row percentages."'
)


def _two_category_outcomes(api, catalog):
    """CLM-302 (CODING): level-1 UPHELD then level-2 OVERTURNED in full.
    CLM-303 (REGISTRATION): level-1 OVERTURNED in full."""
    # CODING denial: two resolved appeals, one overturned
    d_a = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-302", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    ap1 = make_appeal(d_a["id"])
    attach_document(ap1["id"], "CLINICAL_NOTES", file_reference="doc-a1-notes")
    validate_success(api.generate_letter(ap1["id"], _spec()))
    validate_success(api.submit_appeal(ap1["id"], _spec()))
    record_outcome(ap1["id"], "UPHELD", 0)
    ap2 = make_appeal(d_a["id"])
    attach_document(ap2["id"], "CLINICAL_NOTES", file_reference="doc-a2-notes")
    attach_document(ap2["id"], "PHYSICIAN_LETTER", file_reference="doc-a2-letter")
    validate_success(api.generate_letter(ap2["id"], _spec()))
    validate_success(api.submit_appeal(ap2["id"], _spec()))
    record_outcome(ap2["id"], "OVERTURNED", 100000)
    # REGISTRATION denial: one resolved appeal, overturned
    reg_code = make_remittance_code(
        code="CO-45", category="REGISTRATION", default_department="REGISTRATION",
    )
    d_b = make_queued_denial(
        catalog["payer"]["id"], reg_code["id"],
        claim_number="CLM-303", denied_amount_cents=50000, billed_amount_cents=60000,
        service_date="2026-07-12",
    )
    ap_b = make_appeal(d_b["id"])
    attach_document(ap_b["id"], "CLINICAL_NOTES", file_reference="doc-b1-notes")
    validate_success(api.generate_letter(ap_b["id"], _spec()))
    validate_success(api.submit_appeal(ap_b["id"], _spec()))
    record_outcome(ap_b["id"], "OVERTURNED", 50000)


def _spec():
    from test_helpers import TEST_USERS
    return TEST_USERS["specialist_headers"]


def test_overturn_report_per_row_cells(api, manager_headers):
    """PRD §3.8: "Each row reports `resolved_count`, `overturned_count`, and
    `partial_count`, and computes `overturn_rate_pct` as 100 times the sum of fully
    overturned appeals plus one half the partially overturned appeals, divided by the
    resolved count, rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/overturn_report_pooled_rounding_order
    """
    catalog = setup_catalog(
        levels=(1, 2),
        policy_overrides_by_level={
            2: {"required_attachment_types": ["CLINICAL_NOTES", "PHYSICIAN_LETTER"]},
        },
    )
    _two_category_outcomes(api, catalog)
    data = validate_success(
        api.get_overturn_rates(manager_headers, params={"group_by": "category"})
    )
    assert data["group_by"] == "category"
    rows = data["rows"]
    assert len(rows) == 2
    coding = [r for r in rows if r["resolved_count"] == 2][0]
    registration = [r for r in rows if r["resolved_count"] == 1][0]
    assert coding["overturned_count"] == 1
    assert coding["overturn_rate_pct"] == 50.00
    assert registration["overturned_count"] == 1
    assert registration["overturn_rate_pct"] == 100.00


def test_overturn_report_totals_pooled_rounding(api, manager_headers):
    """PRD §3.8: "The response carries `group_by`, the `rows` array, and a `totals` object
    whose percentage is computed from the unrounded aggregate counts pooled across all rows —
    100 times the pooled overturned-plus-half-partial sum divided by the pooled resolved
    count, rounded half-up to two decimals in a single rounding — and is never the sum or
    average of the rounded per-row percentages."

    Design: Difficulty/combinatorial_formula/overturn_report_pooled_rounding_order
    """
    catalog = setup_catalog(
        levels=(1, 2),
        policy_overrides_by_level={
            2: {"required_attachment_types": ["CLINICAL_NOTES", "PHYSICIAN_LETTER"]},
        },
    )
    _two_category_outcomes(api, catalog)
    data = validate_success(
        api.get_overturn_rates(manager_headers, params={"group_by": "category"})
    )
    totals = data["totals"]
    assert totals["resolved_count"] == 3
    # Pooled raw: (1 + 1) / 3 = 66.666... -> 66.67, NOT the 75.00 average of rounded cells.
    assert totals["overturn_rate_pct"] == 66.67
    assert totals["overturn_rate_pct"] != 75.00


def test_overturn_rate_zero_denominator_row_by_payer(api, auditor_headers):
    """PRD §3.8: "Every group with at least one resolved appeal contributes a row; a group
    that has denials but zero resolved appeals in the window still appears, with
    `resolved_count` zero and `overturn_rate_pct` null — never zero and never an error."

    Design: Difficulty/boundary_precision_check/overturn_rate_zero_denominator_null
    """
    catalog = setup_catalog(levels=())
    make_denial(catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-1201")
    data = validate_success(
        api.get_overturn_rates(auditor_headers, params={"group_by": "payer"})
    )
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["resolved_count"] == 0
    assert row["overturned_count"] == 0
    assert row["partial_count"] == 0
    assert row["overturn_rate_pct"] is None


def test_overturn_rate_zero_denominator_row_by_category(api, auditor_headers):
    """PRD §3.8: "Every group with at least one resolved appeal contributes a row; a group
    that has denials but zero resolved appeals in the window still appears, with
    `resolved_count` zero and `overturn_rate_pct` null — never zero and never an error."

    Design: Difficulty/boundary_precision_check/overturn_rate_zero_denominator_null
    """
    catalog = setup_catalog(levels=())
    make_denial(catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-1201")
    data = validate_success(
        api.get_overturn_rates(auditor_headers, params={"group_by": "category"})
    )
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["resolved_count"] == 0
    assert row["overturn_rate_pct"] is None


def test_analytics_window_filter(api, manager_headers):
    """PRD §3.8: "The row set covers appeals in `OVERTURNED`, `PARTIALLY_OVERTURNED`, or
    `UPHELD` whose `outcome_recorded_at` date falls within the optional `from_date` and
    `to_date` bounds — both inclusive, and either bound may be omitted to leave that side
    unbounded — grouped by the denial's payer or by the denial's frozen category."

    Design: Corner/endpoints/analytics_window_filter
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2405",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    set_clock("2026-08-10T00:00:00Z")
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    unbounded = validate_success(
        api.get_overturn_rates(manager_headers, params={"group_by": "payer"})
    )
    assert len(unbounded["rows"]) == 1
    assert unbounded["rows"][0]["resolved_count"] == 1
    assert unbounded["rows"][0]["overturn_rate_pct"] == 100.00
    windowed = validate_success(
        api.get_overturn_rates(
            manager_headers, params={"group_by": "payer", "from_date": "2026-08-11"},
        )
    )
    assert len(windowed["rows"]) == 1
    assert windowed["rows"][0]["resolved_count"] == 0
    assert windowed["rows"][0]["overturn_rate_pct"] is None
