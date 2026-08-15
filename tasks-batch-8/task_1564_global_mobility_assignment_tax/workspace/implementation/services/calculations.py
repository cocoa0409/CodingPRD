"""Calculation rules (scaffold §1.3 / PRD §3). All money is integer cents;
rounding is round-half-up applied at exactly the pinned step of each rule."""
from util import round_half_up_int

# hypothetical_tax constants
BRACKET1_TOP_CENTS = 5000000
BRACKET2_TOP_CENTS = 10000000
EXEMPTION_PER_FAMILY_MEMBER_CENTS = 200000
# employer_tax_gross_up constants
HOST_TAX_RATE_NUMER = 40   # 40%
MAX_ITERATIONS = 50
# employer_social_security constants
SOCSEC_RATE_NUMER = 765    # 7.65%
SOCSEC_RATE_DENOM = 10000


def annual_tax(gross_cents: int, family_size: int) -> int:
    """Tiered annual hypothetical tax with personal exemption (round half up once)."""
    taxable = max(0, gross_cents - family_size * EXEMPTION_PER_FAMILY_MEMBER_CENTS)
    tax_x100 = (
        10 * min(taxable, BRACKET1_TOP_CENTS)
        + 20 * min(max(taxable - BRACKET1_TOP_CENTS, 0), BRACKET1_TOP_CENTS)
        + 30 * max(taxable - BRACKET2_TOP_CENTS, 0)
    )
    return round_half_up_int(tax_x100, 100)


def hypothetical_tax_provisional(total_gross_cents: int, family_size: int) -> int:
    """PROVISIONAL variant: annualize the period gross (x12), apply brackets,
    divide by 12 — annual figure rounded first, monthly division rounded second."""
    return round_half_up_int(annual_tax(total_gross_cents * 12, family_size), 12)


def hypothetical_tax_final(filed_total_gross_cents: int, family_size: int) -> int:
    """FINAL variant: brackets applied once to the filed annual gross."""
    return annual_tax(filed_total_gross_cents, family_size)


def employer_tax_gross_up(host_gross_cents: int) -> int:
    """Fixed-point gross-up at 40% — the pinned iteration MUST be used (the
    closed form is forbidden; per-iteration rounding is observable)."""
    t = round_half_up_int(HOST_TAX_RATE_NUMER * host_gross_cents, 100)
    for _ in range(MAX_ITERATIONS):
        t_next = round_half_up_int(HOST_TAX_RATE_NUMER * (host_gross_cents + t), 100)
        if t_next == t:
            return t
        t = t_next
    return t


def employer_social_security(host_gross_cents: int, coc_exempt: bool) -> int:
    if coc_exempt:
        return 0
    return round_half_up_int(host_gross_cents * SOCSEC_RATE_NUMER, SOCSEC_RATE_DENOM)


def split_gross(total_gross_cents: int, home_payroll_pct: int):
    """Home share is rounded half up; host takes the residual (conservation)."""
    home = round_half_up_int(total_gross_cents * home_payroll_pct, 100)
    return home, total_gross_cents - home


def cola_daily_rate(per_diem_daily_cents: int, cola_pct: int) -> int:
    """Round the COLA-adjusted daily rate FIRST, then multiply by days (pinned)."""
    return round_half_up_int(per_diem_daily_cents * (100 + cola_pct), 100)


def compute_record_fields(*, total_gross_cents, per_diem_days, housing_receipts_cents,
                          home_payroll_pct, coc_exempt, per_diem_daily_cents,
                          cola_pct, housing_monthly_cap_cents, family_size):
    """All computed money fields of a ShadowPayrollRecord (creation / DRAFT recompute)."""
    home_gross_cents, host_gross_cents = split_gross(total_gross_cents, home_payroll_pct)
    per_diem_cents = cola_daily_rate(per_diem_daily_cents, cola_pct) * per_diem_days
    housing_cents = min(housing_monthly_cap_cents, housing_receipts_cents)
    return {
        "home_gross_cents": home_gross_cents,
        "host_gross_cents": host_gross_cents,
        "per_diem_cents": per_diem_cents,
        "housing_cents": housing_cents,
        "hypothetical_tax_cents": hypothetical_tax_provisional(total_gross_cents, family_size),
        "employer_host_tax_cents": employer_tax_gross_up(host_gross_cents),
        "employer_socsec_cents": employer_social_security(host_gross_cents, coc_exempt),
    }


def months_touched(start_date, planned_end_date) -> int:
    """Calendar months touched by the closed window [start_date, planned_end_date]."""
    return (planned_end_date.year - start_date.year) * 12 \
        + (planned_end_date.month - start_date.month) + 1


def monthly_cost_cents(home_base_annual_cents, host_payroll_pct, coc_exempt,
                       per_diem_daily_cents, cola_pct, housing_monthly_cap_cents):
    """cost_projection_total per-month employer cost (pinned rounding at each step)."""
    host_share_annual = round_half_up_int(home_base_annual_cents * host_payroll_pct, 100)
    host_monthly = round_half_up_int(host_share_annual, 12)
    return (
        host_monthly
        + employer_tax_gross_up(host_monthly)
        + employer_social_security(host_monthly, coc_exempt)
        + cola_daily_rate(per_diem_daily_cents, cola_pct) * 30
        + housing_monthly_cap_cents
    )
