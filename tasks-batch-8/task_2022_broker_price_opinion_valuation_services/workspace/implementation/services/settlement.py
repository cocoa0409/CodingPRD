"""Late-fee settlement (scaffold 1.3 'late_fee', PRD 3.7)."""

from decimal import Decimal, ROUND_HALF_UP

SECONDS_PER_DAY = Decimal(86400)
MAX_BPS_PER_DAY = 2000


def settle_order_completion(order: dict, client: dict, completed_at) -> None:
    """Populate days_late, late_penalty_cents, net_payable_cents, is_rush_breach."""
    sla = order["sla_due_at"]
    if sla is None or completed_at <= sla:
        days_late = 0
    else:
        elapsed = Decimal(str((completed_at - sla).total_seconds()))
        days_late = int((elapsed / SECONDS_PER_DAY).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if days_late < 0:
            days_late = 0

    if days_late == 0:
        late_penalty_cents = 0
    else:
        bps_per_day = client["late_penalty_bps_per_day"]
        raw = (
            Decimal(order["agreed_fee_cents"])
            * Decimal(bps_per_day)
            * Decimal(days_late)
            / Decimal(10000)
        )
        late_penalty_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if late_penalty_cents > order["agreed_fee_cents"]:
            late_penalty_cents = order["agreed_fee_cents"]

    net_payable = order["agreed_fee_cents"] - late_penalty_cents
    if net_payable < 0:
        net_payable = 0

    order["days_late"] = days_late
    order["late_penalty_cents"] = late_penalty_cents
    order["net_payable_cents"] = net_payable
    order["is_rush_breach"] = bool(
        order["priority"] == "RUSH" and sla is not None and completed_at > sla
    )
