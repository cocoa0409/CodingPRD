"""Corner — calculations section.

Specific franchise_tax and late_fee corner cases, and the BOI 30-day grace
window for AMENDMENT/ANNUAL_REFRESH triggers.
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    file_annual_report,
    create_draft_boi_disclosure,
    make_filer_headers,
)


def test_franchise_tax_correct_for_ca_llc_zero_band(api):
    """PRD §3.8: "California charges 800 dollars for every entity type"
    PRD §3.8: "California 80000 cents"

    Design: Corner/calculations/franchise_tax_correct_for_ca_llc_zero_band
    """
    set_clock("2025-03-01T00:00:00Z")
    be, _ = setup_active_llc(
        legal_name="QUEBEC CA LLC", formation_state_code="CA", revenue_band="ZERO"
    )
    ar = create_draft_annual_report(be, 2024)
    filed = file_annual_report(be, ar["id"])
    # CA LLC ZERO: base=80000, mult=100, raw=80000, floor=80000 -> 80000.
    assert filed["franchise_tax_amount_cents"] == 80000


def test_franchise_tax_tier_boundary_micro_eq_zero(api):
    """PRD §3.8: "`ZERO` and `MICRO` are 1.00x (multiplier 100)"
    PRD §3.8: "Delaware charges 300 dollars for `LLC` and `LP` entities"

    Design: Corner/calculations/franchise_tax_tier_boundary_micro_eq_zero
    """
    set_clock("2025-03-01T00:00:00Z")
    be, _ = setup_active_llc(
        legal_name="ROMEO MICRO LLC", formation_state_code="DE", revenue_band="MICRO"
    )
    ar = create_draft_annual_report(be, 2024)
    filed = file_annual_report(be, ar["id"])
    # DE LLC MICRO: same as ZERO (mult=100). base=30000, raw=30000, floor=17500 -> 30000.
    assert filed["franchise_tax_amount_cents"] == 30000


def test_late_fee_zero_for_tx(api):
    """PRD §3.9: "Texas no late fee at all (0)"
    PRD §3.9: "The accrued amount is then the per-day fee in integer cents
    multiplied by the integer days-late count."

    Design: Corner/calculations/late_fee_zero_for_tx
    """
    set_clock("2024-12-01T00:00:00Z")
    be, _ = setup_active_llc(
        legal_name="SIERRA TX LLC", formation_state_code="TX", revenue_band="ZERO"
    )
    ar = create_draft_annual_report(be, 2024)
    # Advance past April-15-2025 to make the AR delinquent.
    set_clock("2025-05-01T00:00:00Z")
    filed = file_annual_report(be, ar["id"])
    assert filed["late_fee_cents"] == 0


def test_boi_filing_deadline_amendment_uses_30_day_grace(api):
    """PRD §3.11: "When the `triggering_event` is `AMENDMENT` or `ANNUAL_REFRESH`,
    the deadline base is the current clock UTC at the disclosure's creation
    moment and the grace window is 30 whole days."
    PRD §3.11: "The day arithmetic is whole-day at UTC; the deadline is the base
    instant plus the appropriate number of days. The deadline comparison is
    inclusive on the deadline second"

    Design: Corner/calculations/boi_filing_deadline_amendment_uses_30_day_grace
    """
    set_clock("2026-02-01T00:00:00Z")
    be, _ = setup_active_llc(
        legal_name="TANGO LLC", formation_state_code="DE", revenue_band="ZERO"
    )
    boi = create_draft_boi_disclosure(be, triggering_event="ANNUAL_REFRESH")
    # PRD §3.11: "the deadline is the base instant plus the appropriate number
    # of days." For ANNUAL_REFRESH, base is creation clock UTC (2026-02-01T00:00:00Z)
    # and grace is 30 days → deadline = 2026-03-03T00:00:00Z. The comparison
    # is inclusive on the deadline second.
    set_clock("2026-03-03T00:00:00Z")
    res = api.submit_boi_disclosure(boi["id"], make_filer_headers(be["id"]))
    body = validate_success(res, 200)
    assert body["status"] == "SUBMITTED"
