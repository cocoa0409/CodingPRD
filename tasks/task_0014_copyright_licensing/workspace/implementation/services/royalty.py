"""Royalty calculation: calc:royalty_payable."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_royalty(license_obj: dict, gross_revenue_cents: int, variant: str) -> dict:
    """Return {earned_royalty_cents, advance_recouped_cents, net_payable_cents}.

    Order:
      1) revenue_share = round_half_up(gross * bps / 10000)
      2) earned = max(revenue_share, MG)  [PROVISIONAL: skip max]
      3) remaining_advance = max(0, advance - cumulative_recouped)
      4) advance_recouped = min(earned, remaining_advance)
      5) net_payable = earned - advance_recouped (>= 0)
      [PROVISIONAL: net_payable = max(0, revenue_share - remaining_advance)]
    """
    gross = Decimal(int(gross_revenue_cents))
    bps = Decimal(int(license_obj.get("revenue_share_bps", 0)))
    mg = int(license_obj.get("minimum_guarantee_cents", 0))
    advance = int(license_obj.get("advance_cents", 0))
    cumulative = int(license_obj.get("cumulative_advance_recouped_cents", 0))

    revenue_share = round_half_up_int(gross * bps / Decimal(10000))
    remaining_advance = max(0, advance - cumulative)

    if variant == "PROVISIONAL":
        # Provisional ignores MG; never settles.
        # advance_recouped applies to revenue_share only
        advance_recouped = min(revenue_share, remaining_advance)
        # earned royalty for storage stays the revenue_share (no MG floor)
        earned = revenue_share
        net_payable = max(0, revenue_share - remaining_advance)
    else:  # FINAL (default)
        earned = max(revenue_share, mg)
        advance_recouped = min(earned, remaining_advance)
        net_payable = earned - advance_recouped

    return {
        "earned_royalty_cents": int(earned),
        "advance_recouped_cents": int(advance_recouped),
        "net_payable_cents": int(net_payable),
    }
