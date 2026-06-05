from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db

APPEAL_TIER_WINDOW_DAYS = {1: 30, 2: 30, 3: 45}
EXPEDITE_FACTOR = Decimal("0.25")


def round_half_up(value):
    """Round a Decimal to a whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_sla_due_at(request, payer):
    """sla_due_at = review_started_at + (base_hours + clock_paused_hours) hours.

    base_hours is whole-hour integer arithmetic; result resolved to the second.
    """
    started = request.get("_review_started_dt")
    if started is None:
        return
    if request.get("is_expedited"):
        base_hours = payer["expedited_sla_hours"]
    else:
        base_hours = payer["standard_sla_hours"]
    total_hours = base_hours + request.get("clock_paused_hours", 0)
    due = started + timedelta(hours=total_hours)
    request["_sla_due_dt"] = due


def compute_member_cost_share(request, member):
    """member_cost_share_cents = procedure_share + summed evidence shares.

    Rounding is applied PER LINE ITEM (and per-unit for procedure) BEFORE summing.
    """
    rate = Decimal(str(member["coinsurance_rate"]))

    if request["status"] == "APPROVED":
        effective_units = request.get("approved_units", 0)
    else:
        effective_units = request["requested_units"]

    per_unit_share = round_half_up(Decimal(request["unit_cost_cents"]) * rate)
    procedure_share = per_unit_share * effective_units

    evidence_share = 0
    for ev in db.evidence.values():
        if ev["request_id"] == request["id"]:
            evidence_share += round_half_up(Decimal(ev["line_item_cost_cents"]) * rate)

    request["member_cost_share_cents"] = procedure_share + evidence_share


def compute_appeal_deadline(appeal, request):
    """appeal_deadline_at = filed_at + window_days days; resolved to the second."""
    tier_window = APPEAL_TIER_WINDOW_DAYS[appeal["tier"]]
    factor = EXPEDITE_FACTOR if request.get("is_expedited") else Decimal("1.0")
    window_days = Decimal(tier_window) * factor
    seconds = float(window_days) * 86400.0
    deadline = appeal["_filed_dt"] + timedelta(seconds=seconds)
    appeal["_deadline_dt"] = deadline
