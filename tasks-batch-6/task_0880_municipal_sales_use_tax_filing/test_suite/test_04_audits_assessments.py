"""Audits, nexus discovery, assessment penalty/interest variants, close cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_auditor_headers,
    register_taxpayer, create_active_taxpayer, create_jurisdiction,
    create_filed_return, set_clock,
    open_field_audit, open_nexus_audit, close_audit_assessed,
    create_late_filing_assessment, find_assessment_for_audit,
    create_open_refund_claim, get_return, get_refund_claim,
)


def test_late_filing_assessment_penalty_interest_total(api):
    """PRD §3.5: "For a `LATE_FILING`, the `penalty_cents` is ten percent of the base —
    base multiplied by 1000 basis points, divided by 10000, rounded half-up — but never
    more than a cap of 500000 cents (five thousand dollars); the penalty is the smaller
    of the computed amount and that cap."
    PRD §3.5: "The `interest_cents` is then one percent per month applied to the sum of
    base and penalty: `(tax_deficiency_cents + penalty_cents)` multiplied by 100 basis
    points, divided by 10000, multiplied by the number of months late, rounded half-up."

    Design: Difficulty/dual_variant_calc/assessment_penalty_variant_audit_vs_late
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    asmt = create_late_filing_assessment(api, tp["id"], tax_deficiency_cents=100000,
                                         original_due_date="2026-01-20T00:00:00Z")
    assert asmt["penalty_cents"] == 10000
    assert asmt["interest_cents"] == 3300
    assert asmt["total_due_cents"] == 113300


def test_audit_deficiency_assessment_penalty_interest_total(api):
    """PRD §3.5: "For an `AUDIT_DEFICIENCY`, the `penalty_cents` is twenty-five percent of
    the base — base multiplied by 2500 basis points, divided by 10000, rounded half-up —
    with no cap."
    PRD §3.5: "The `interest_cents` is then one percent per month applied to the sum of
    base and penalty: `(tax_deficiency_cents + penalty_cents)` multiplied by 100 basis
    points, divided by 10000, multiplied by the number of months late, rounded half-up."

    Design: Difficulty/dual_variant_calc/assessment_penalty_variant_audit_vs_late
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    audit = open_field_audit(api, tp["id"], period_key="2026-Q1")
    close_audit_assessed(api, audit["id"], tax_deficiency_cents=100000,
                         original_due_date="2026-01-20T00:00:00Z")
    asmt = find_assessment_for_audit(api, audit["id"])
    assert asmt["penalty_cents"] == 25000
    assert asmt["interest_cents"] == 3750
    assert asmt["total_due_cents"] == 128750


def test_interest_charged_on_base_plus_penalty(api):
    """PRD §3.5: "The `interest_cents` is then one percent per month applied to the sum of
    base and penalty: `(tax_deficiency_cents + penalty_cents)` multiplied by 100 basis
    points, divided by 10000, multiplied by the number of months late, rounded half-up.
    Interest is always charged on base plus penalty, never on the base alone."

    Design: Difficulty/combinatorial_formula/assessment_interest_on_base_plus_penalty
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    audit = open_field_audit(api, tp["id"], period_key="2026-Q1")
    close_audit_assessed(api, audit["id"], tax_deficiency_cents=100000,
                         original_due_date="2026-01-20T00:00:00Z")
    asmt = find_assessment_for_audit(api, audit["id"])
    # 3750 = (100000 + 25000) * 100 / 10000 * 3; interest-on-base-alone would be 3000.
    assert asmt["interest_cents"] == 3750


def test_audit_deficiency_penalty_and_total_pinned(api):
    """PRD §3.5: "For an `AUDIT_DEFICIENCY`, the `penalty_cents` is twenty-five percent of
    the base — base multiplied by 2500 basis points, divided by 10000, rounded half-up —
    with no cap."
    PRD §3.5: "Every assessment records `penalty_cents`, `interest_cents`, and a
    `total_due_cents` equal to `tax_deficiency_cents + penalty_cents + interest_cents`".

    Design: Difficulty/combinatorial_formula/assessment_interest_on_base_plus_penalty
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    audit = open_field_audit(api, tp["id"], period_key="2026-Q1")
    close_audit_assessed(api, audit["id"], tax_deficiency_cents=100000,
                         original_due_date="2026-01-20T00:00:00Z")
    asmt = find_assessment_for_audit(api, audit["id"])
    assert asmt["penalty_cents"] == 25000
    assert asmt["total_due_cents"] == 128750


def test_late_filing_penalty_capped(api):
    """PRD §3.5: "For a `LATE_FILING`, the `penalty_cents` is ten percent of the base —
    base multiplied by 1000 basis points, divided by 10000, rounded half-up — but never
    more than a cap of 500000 cents (five thousand dollars); the penalty is the smaller
    of the computed amount and that cap."

    Design: Corner/calculations/late_filing_penalty_cap_applied
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-01-20T00:00:00Z")  # equal to original_due_date -> 0 months late
    asmt = create_late_filing_assessment(api, tp["id"], tax_deficiency_cents=6000000,
                                         original_due_date="2026-01-20T00:00:00Z")
    assert asmt["penalty_cents"] == 500000
    assert asmt["interest_cents"] == 0
    assert asmt["total_due_cents"] == 6500000


def test_audit_close_cascades_return_assessed_and_issued_assessment(api):
    """PRD §3.5: "First, the system creates an `Assessment` of `assessment_type`
    `AUDIT_DEFICIENCY`, ... in `status` `ISSUED`".
    PRD §3.5: "Second, if a `return_id` was supplied, that `TaxReturn` is driven from
    `FILED` to `ASSESSED`."

    Design: Difficulty/transitive_cascade/audit_close_cascades_assessment_return_refund
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    set_clock(api, "2026-04-01T00:00:00Z")
    from test_helpers import create_return_line
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    audit = open_field_audit(api, tp["id"], period_key="2026-Q1")
    set_clock(api, "2026-04-20T00:00:00Z")
    audit_after = close_audit_assessed(api, audit["id"], tax_deficiency_cents=100000,
                                       original_due_date="2026-01-20T00:00:00Z",
                                       return_id=filed["id"])
    assert audit_after["status"] == "CLOSED_ASSESSED"
    asmt = find_assessment_for_audit(api, audit["id"])
    assert asmt["status"] == "ISSUED"
    assert asmt["total_due_cents"] == 128750
    ret_after = get_return(api, filed["id"])
    assert ret_after["status"] == "ASSESSED"


def test_audit_close_cascade_voids_open_refund(api):
    """PRD §3.5: "Third, because the return became `ASSESSED`, any `RefundClaim` on that
    return still in `OPEN` is voided to `VOIDED`."

    Design: Difficulty/transitive_cascade/audit_close_cascades_assessment_return_refund
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    set_clock(api, "2026-04-01T00:00:00Z")
    from test_helpers import create_return_line
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    claim = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                     claim_amount_cents=5000)
    audit = open_field_audit(api, tp["id"], period_key="2026-Q1")
    set_clock(api, "2026-04-20T00:00:00Z")
    close_audit_assessed(api, audit["id"], tax_deficiency_cents=100000,
                         original_due_date="2026-01-20T00:00:00Z", return_id=filed["id"])
    claim_after = get_refund_claim(api, claim["id"])
    assert claim_after["status"] == "VOIDED"


def test_nexus_established_at_exact_threshold(api):
    """PRD §3.5: "computes `nexus_established` as true exactly when the measured
    `gross_receipts_cents` is greater than or equal to the nexus threshold of 10000000
    cents (one hundred thousand dollars); receipts equal to the threshold do establish nexus."

    Design: Difficulty/boundary_precision_check/nexus_established_at_exact_threshold
    """
    tp = register_taxpayer(api)
    audit = open_nexus_audit(api, tp["id"], gross_receipts_cents=10000000)
    assert audit["nexus_established"] is True


def test_nexus_established_above_threshold(api):
    """PRD §3.5: "computes `nexus_established` as true exactly when the measured
    `gross_receipts_cents` is greater than or equal to the nexus threshold of 10000000
    cents (one hundred thousand dollars); receipts equal to the threshold do establish nexus."

    Design: Difficulty/boundary_precision_check/nexus_established_at_exact_threshold
    """
    tp = register_taxpayer(api)
    audit = open_nexus_audit(api, tp["id"], gross_receipts_cents=10000001)
    assert audit["nexus_established"] is True


def test_nexus_below_threshold_not_established(api):
    """PRD §3.5: "computes `nexus_established` as true exactly when the measured
    `gross_receipts_cents` is greater than or equal to the nexus threshold of 10000000
    cents (one hundred thousand dollars); receipts equal to the threshold do establish nexus."

    Design: Corner/calculations/nexus_below_threshold_not_established
    """
    tp = register_taxpayer(api)
    audit = open_nexus_audit(api, tp["id"], gross_receipts_cents=9999999)
    assert audit["nexus_established"] is False


def test_close_already_closed_audit_rejected(api):
    """PRD §3.5: "Closing an audit requires it to be `OPEN` (otherwise `ERR_AUDIT_NOT_OPEN`)".

    Design: Corner/state_machines/close_terminal_audit_rejected
    """
    tp = register_taxpayer(api)
    audit = open_nexus_audit(api, tp["id"], gross_receipts_cents=5000000)
    validate_success(api.close_audit(audit["id"], {"outcome": "NO_CHANGE"},
                                     make_auditor_headers("aud-1")))
    resp = api.close_audit(audit["id"], {"outcome": "NO_CHANGE"}, make_auditor_headers("aud-1"))
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_OPEN, expected_status=409)
