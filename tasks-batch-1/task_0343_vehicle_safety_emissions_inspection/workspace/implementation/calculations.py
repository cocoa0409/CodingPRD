"""Calculation rules (PRD §3.4-§3.12, SCAFFOLD 1.3). Integer cents; Decimal for the one rounding case."""
from decimal import Decimal, ROUND_HALF_UP

import db

# Constants (SCAFFOLD 1.3)
MAX_STORED_DTC = 0           # any stored DTC fails
MAX_INCOMPLETE_MONITORS = 1  # >= 2 incomplete monitors fails
OBD_SURCHARGE_CENTS = 1000
STATE_ENV_FEE_CENTS = 200
STATE_REMIT_RATE = Decimal("0.075")


def evaluate_obd_result(test):
    """OBD-II verdict (PRD §3.4). Clean-ECU threshold check, in pinned order."""
    if test["mil_on"]:
        return "FAIL"
    if test["dtc_count"] > MAX_STORED_DTC:
        return "FAIL"
    if test["readiness_monitors_incomplete"] > MAX_INCOMPLETE_MONITORS:
        return "FAIL"
    return "PASS"


def evaluate_safety_result(record_id):
    """Aggregate over all ChecklistResult rows for the record (PRD §3.5)."""
    for cr in db.checklist_results.values():
        if cr["record_id"] == record_id and cr["outcome"] == "FAIL":
            return "FAIL"
    return "PASS"


def _eligible_repair_orders(record_id):
    """VERIFIED, emissions_related repair orders for the record (PRD §3.7)."""
    return [
        ro for ro in db.repair_orders.values()
        if ro["record_id"] == record_id
        and ro["emissions_related"] is True
        and ro["status"] == "VERIFIED"
    ]


def compute_qualifying_repair_spend(record_id, cost_basis):
    """Qualifying repair spend under the chosen basis (PRD §3.7, SCAFFOLD compute_qualifying_repair_spend)."""
    eligible = _eligible_repair_orders(record_id)
    documented = sum(ro["documented_cost_cents"] for ro in eligible)
    if cost_basis == "DOCUMENTED_ONLY":
        return documented
    estimated = sum(ro["estimated_cost_cents"] for ro in eligible)
    return documented + estimated


def compute_inspection_fee(record, profile, chain_head):
    """Total fee frozen onto fee_cents at the decide transition (PRD §3.6).

    Pinned step order:
      base = profile.base_fee_cents
      emissions_surcharge = 1000 if obd_required else 0
      service_subtotal = base + emissions_surcharge
      reinspection relief: index == 1 AND within window -> service_subtotal = 0
      fee_cents = service_subtotal + STATE_ENV_FEE_CENTS
    """
    base = profile["base_fee_cents"]
    emissions_surcharge = OBD_SURCHARGE_CENTS if profile["obd_required"] else 0
    service_subtotal = base + emissions_surcharge

    is_free_reinspection = False
    if record["reinspection_index"] == 1 and chain_head is not None:
        clock = db.current_clock()
        head_created = _parse_iso(chain_head["created_at"])
        if clock is not None:
            elapsed = (clock - head_created).total_seconds()
            window_seconds = profile["reinspection_window_days"] * 86400
            if elapsed <= window_seconds:
                is_free_reinspection = True

    if is_free_reinspection:
        service_subtotal = 0

    return service_subtotal + STATE_ENV_FEE_CENTS


def compute_state_surcharge_for_fee(fee_cents):
    """Per-line / per-record surcharge with round-half-up to whole cents (PRD §3.12).

    Returns (service_portion_cents, line_surcharge_cents).
    """
    service_portion = max(fee_cents - STATE_ENV_FEE_CENTS, 0)
    raw = Decimal(service_portion) * STATE_REMIT_RATE
    surcharge = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return service_portion, surcharge


def compute_batch_totals(batch_id):
    """Recompute line_count and total_reported_fee_cents (PRD §3.11)."""
    lines = [ln for ln in db.state_report_lines.values() if ln["batch_id"] == batch_id]
    line_count = len(lines)
    total = sum(ln["fee_cents"] for ln in lines)
    return line_count, total


def _parse_iso(s):
    from datetime import datetime, timezone
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
