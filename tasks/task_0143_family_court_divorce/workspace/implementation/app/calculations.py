"""Pure calculation helpers per PRD §3.5–§3.6.

All inputs and outputs are integer cents. Rounding is round-half-up, performed
exactly once at the end of each formula step as the PRD prescribes.
"""
from decimal import ROUND_HALF_UP, Decimal


# --- rounding utility ----------------------------------------------------

def _round_half_up(value) -> int:
    """Round a Decimal (or anything Decimal-coercible) half-up to an int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- marriage duration ---------------------------------------------------

def marriage_duration_years(marriage_date, separation_date) -> int:
    """floor((separation_date - marriage_date).days / 365.25)."""
    delta_days = (separation_date - marriage_date).days
    # Floor division on Decimal handles the 365.25 case exactly.
    quotient = (Decimal(delta_days) / Decimal("365.25"))
    # Decimal floor: use ROUND_FLOOR through quantize.
    from decimal import ROUND_FLOOR
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_FLOOR))


# --- child support -------------------------------------------------------

def _basic_support_income_shares(combined: int) -> int:
    """Tiered combined-income schedule, single rounding step at end."""
    c = Decimal(combined)
    if c <= 200000:
        raw = c * Decimal("0.17")
    elif c <= 500000:
        raw = Decimal(200000) * Decimal("0.17") + (c - 200000) * Decimal("0.20")
    elif c <= 1000000:
        raw = (
            Decimal(200000) * Decimal("0.17")
            + Decimal(300000) * Decimal("0.20")
            + (c - 500000) * Decimal("0.22")
        )
    else:
        raw = (
            Decimal(200000) * Decimal("0.17")
            + Decimal(300000) * Decimal("0.20")
            + Decimal(500000) * Decimal("0.22")
            + (c - 1000000) * Decimal("0.10")
        )
    return _round_half_up(raw)


def child_support_amount(
    jurisdiction_state: str,
    p_disclosure: dict,
    r_disclosure: dict,
    plan: dict,
):
    """Compute (monthly_amount_cents, guideline_model, obligor_role).

    obligor_role is one of "PETITIONER" or "RESPONDENT".

    Per §3.5: if either net income tie, the obligor is the Respondent.
    """
    p_net = int(p_disclosure["net_monthly_income_cents"])
    r_net = int(r_disclosure["net_monthly_income_cents"])
    combined = p_net + r_net

    addons = (
        int(p_disclosure["monthly_childcare_cents"])
        + int(r_disclosure["monthly_childcare_cents"])
        + int(p_disclosure["monthly_health_insurance_cents"])
        + int(r_disclosure["monthly_health_insurance_cents"])
    )

    if jurisdiction_state in {"CA", "NY", "IL"}:
        guideline = "INCOME_SHARES"
        basic = _basic_support_income_shares(combined)
        total_basic = basic + addons

        if combined == 0:
            # Degenerate: both have zero net — no obligation either way.
            return 0, guideline, "RESPONDENT"

        # Tie or Respondent higher → Respondent is the obligor.
        if r_net >= p_net:
            obligor = "RESPONDENT"
            obligor_net = r_net
            obligor_overnights = int(plan["respondent_overnights_per_year"])
        else:
            obligor = "PETITIONER"
            obligor_net = p_net
            obligor_overnights = int(plan["petitioner_overnights_per_year"])

        # All Decimal so the single round-half-up is at the end.
        income_share = Decimal(obligor_net) / Decimal(combined)
        overnight_share = Decimal(obligor_overnights) / Decimal(365)
        factor = income_share - (Decimal("0.5") * overnight_share)
        monthly_raw = Decimal(total_basic) * factor
        monthly = _round_half_up(monthly_raw)
        if monthly < 0:
            monthly = 0
        return monthly, guideline, obligor

    # TX, FL, WA → percent-of-obligor
    guideline = "PERCENT_OBLIGOR"
    if r_net >= p_net:
        obligor = "RESPONDENT"
        obligor_net = r_net
    else:
        obligor = "PETITIONER"
        obligor_net = p_net

    if obligor_net <= 200000:
        pct = Decimal("0.20")
    elif obligor_net <= 500000:
        pct = Decimal("0.22")
    elif obligor_net <= 1000000:
        pct = Decimal("0.25")
    else:
        pct = Decimal("0.27")

    base_piece = _round_half_up(Decimal(obligor_net) * pct)
    if combined > 0:
        addon_piece = _round_half_up(Decimal(addons) * (Decimal(obligor_net) / Decimal(combined)))
    else:
        addon_piece = 0
    monthly = base_piece + addon_piece
    if monthly < 0:
        monthly = 0
    return monthly, guideline, obligor


# --- spousal support -----------------------------------------------------

def spousal_support_amount(
    p_disclosure: dict,
    r_disclosure: dict,
    duration_years: int,
):
    """Returns (monthly_amount_cents, obligor_role).

    Eligibility (duration >= 5) is enforced by the caller as a validation;
    this routine assumes it is already eligible.
    """
    p_net = int(p_disclosure["net_monthly_income_cents"])
    r_net = int(r_disclosure["net_monthly_income_cents"])
    higher = max(p_net, r_net)
    lower = min(p_net, r_net)
    gap = higher - lower

    if duration_years < 10:
        pct = Decimal("0.30")
    elif duration_years < 20:
        pct = Decimal("0.35")
    else:
        pct = Decimal("0.40")

    monthly = _round_half_up(Decimal(gap) * pct)
    cap = _round_half_up(Decimal(higher) * Decimal("0.40"))
    if monthly > cap:
        monthly = cap
    if monthly < 0:
        monthly = 0

    # Obligor is the higher earner. Tie → Respondent (consistent with §3.5 tie rule).
    if r_net >= p_net:
        obligor = "RESPONDENT"
    else:
        obligor = "PETITIONER"
    return monthly, obligor


# --- asset division ------------------------------------------------------

def asset_division(
    jurisdiction_state: str,
    p_disclosure: dict,
    r_disclosure: dict,
):
    """Returns (petitioner_share_cents, respondent_share_cents, division_model).

    Pinned invariant: petitioner_share + respondent_share == net_pool.
    """
    p_assets = int(p_disclosure["assets_total_cents"])
    r_assets = int(r_disclosure["assets_total_cents"])
    p_debts = int(p_disclosure["debts_total_cents"])
    r_debts = int(r_disclosure["debts_total_cents"])
    gross_pool = p_assets + r_assets
    net_pool = gross_pool - p_debts - r_debts

    if jurisdiction_state in {"CA", "TX", "WA"}:
        model = "COMMUNITY_PROPERTY"
        # Floor division for signed values: use Python's // which is floor.
        half = net_pool // 2
        extra = net_pool - 2 * half
        return half + extra, half, model

    # NY, FL, IL → equitable distribution
    model = "EQUITABLE_DISTRIBUTION"
    p_inc = int(p_disclosure["net_monthly_income_cents"])
    r_inc = int(r_disclosure["net_monthly_income_cents"])
    total = p_inc + r_inc
    if total == 0:
        p_share = net_pool // 2
    else:
        # Multiply first, then integer divide — pinned by §3.6.
        p_share = (net_pool * r_inc) // total
    r_share = net_pool - p_share
    return p_share, r_share, model
