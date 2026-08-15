"""Business logic: calculations (SCAFFOLD 1.3), derived aggregates, cascades (SCAFFOLD 1.2).

All mutations cascade immediately in-request (PRD 1: no eventual consistency).
System timestamps on entities use wall-clock formatting per PRD 2.4; workflow
timestamps (admission_date, withdrawal_date, default occurred_at) use the
logical clock per PRD 2.5.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import new_id, now_ts, parse_dt, fmt_dt, rhu_cents, duty_amount, CLOCK

# ---------------------------------------------------------------------------
# Global constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

HTS_RATE_TABLE = {
    "0401.10": Decimal("0.05"),
    "8542.31": Decimal("0.04"),
    "9503.00": Decimal("0.12"),
    "8708.29": Decimal("0.025"),
}
MPF_AD_VALOREM_RATE = Decimal("0.003464")
MPF_MIN_CENTS = 3000
MPF_MAX_CENTS = 60000
ENTRY_WEEK_DAYS = 7
AUDIT_THRESHOLD_PCT = Decimal("0.5")

ZONE_STATUSES = {"PRIVILEGED_FOREIGN", "NON_PRIVILEGED_FOREIGN", "DOMESTIC", "ZONE_RESTRICTED"}


def wall_now() -> datetime:
    return parse_dt(now_ts())


def touch(entity):
    """Bump updated_at and version on a common-fields entity (PRD 2.4)."""
    entity["updated_at"] = wall_now()
    entity["version"] += 1


def new_common():
    now = wall_now()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


# ---------------------------------------------------------------------------
# Lot valuation (SCAFFOLD 1.3 duty_assessment resolution rules)
# ---------------------------------------------------------------------------

def lot_duty_rate(zone_status: str, hts_code: str) -> Decimal:
    if zone_status == "DOMESTIC":
        return Decimal("0")
    return HTS_RATE_TABLE[hts_code]


def recompute_zone_aggregates(zone):
    """deferred_duty_exposure: per-lot round_half_up(qoh x unit_value x rate) summed over
    IN_ZONE lots; active_lot_count counts IN_ZONE lots (SCAFFOLD 1.3 deferred_duty_exposure)."""
    exposure = 0
    count = 0
    for lot in db["lots"].values():
        if lot["zone_id"] == zone["id"] and lot["status"] == "IN_ZONE":
            exposure += duty_amount(lot["quantity_on_hand"], lot["unit_value_cents"], lot["duty_rate"])
            count += 1
    zone["deferred_duty_exposure_cents"] = exposure
    zone["active_lot_count"] = count
    touch(zone)


def recompute_entry_totals(entry):
    """weekly_entry_settlement (SCAFFOLD 1.3): members are attached CONSUMPTION
    withdrawals in {FILED, DUTY_PAID}. Per-line rounding pinned: round duty per
    line first, then sum. Live-recomputed on membership/member-status changes."""
    members = [
        w for w in db["withdrawals"].values()
        if w["weekly_entry_id"] == entry["id"]
        and w["withdrawal_type"] == "CONSUMPTION"
        and w["status"] in ("FILED", "DUTY_PAID")
    ]
    if not members:
        entry["entered_value_cents"] = 0
        entry["duty_total_cents"] = 0
        entry["mpf_uncapped_cents"] = 0
        entry["mpf_cents"] = 0
        entry["per_shipment_mpf_cents"] = 0
        entry["mpf_savings_cents"] = 0
        touch(entry)
        return
    entered_value = 0
    duty_total = 0
    per_shipment_mpf = 0
    for w in members:
        lot = db["lots"][w["lot_id"]]
        line_value = w["quantity"] * lot["unit_value_cents"]  # exact integer cents
        line_duty = rhu_cents(Decimal(line_value) * lot["duty_rate"])  # round per line FIRST
        entered_value += line_value
        duty_total += line_duty
        line_mpf = rhu_cents(Decimal(line_value) * MPF_AD_VALOREM_RATE)
        per_shipment_mpf += min(max(line_mpf, MPF_MIN_CENTS), MPF_MAX_CENTS)
    mpf_uncapped = rhu_cents(Decimal(entered_value) * MPF_AD_VALOREM_RATE)
    mpf = min(max(mpf_uncapped, MPF_MIN_CENTS), MPF_MAX_CENTS)
    entry["entered_value_cents"] = entered_value
    entry["duty_total_cents"] = duty_total
    entry["mpf_uncapped_cents"] = mpf_uncapped
    entry["mpf_cents"] = mpf
    entry["per_shipment_mpf_cents"] = per_shipment_mpf
    entry["mpf_savings_cents"] = per_shipment_mpf - mpf
    touch(entry)


# ---------------------------------------------------------------------------
# Admission ADMITTED side effect: create the inventory lot (SCAFFOLD 1.2)
# ---------------------------------------------------------------------------

def create_lot_from_admission(admission):
    lot = new_common()
    lot.update({
        "zone_id": admission["zone_id"],
        "admission_id": admission["id"],
        "source_manipulation_id": None,
        "importer_ref": admission["importer_ref"],
        "hts_code": admission["hts_code"],
        "zone_status": admission["zone_status"],
        "admitted_quantity": admission["quantity"],
        "quantity_on_hand": admission["quantity"],
        "reserved_quantity": 0,
        "cumulative_withdrawn": 0,
        "cumulative_consumed": 0,
        "unit_value_cents": admission["unit_value_cents"],
        "duty_rate": lot_duty_rate(admission["zone_status"], admission["hts_code"]),
        "status": "IN_ZONE",
    })
    db["lots"][lot["id"]] = lot
    return lot


def admit_deferred_estimate(admission) -> int:
    """Deferred-duty estimate of the lot an admission would create (bond check)."""
    rate = lot_duty_rate(admission["zone_status"], admission["hts_code"])
    return duty_amount(admission["quantity"], admission["unit_value_cents"], rate)


# ---------------------------------------------------------------------------
# Withdrawal lot debit / compensation helpers (SCAFFOLD 1.2 Withdrawal)
# ---------------------------------------------------------------------------

def debit_lot_for_withdrawal(withdrawal):
    lot = db["lots"][withdrawal["lot_id"]]
    lot["quantity_on_hand"] -= withdrawal["quantity"]
    lot["cumulative_withdrawn"] += withdrawal["quantity"]
    if lot["quantity_on_hand"] == 0 and lot["status"] == "IN_ZONE":
        lot["status"] = "DEPLETED"
    touch(lot)
    return lot


def restore_lot_for_withdrawal(withdrawal):
    lot = db["lots"][withdrawal["lot_id"]]
    lot["quantity_on_hand"] += withdrawal["quantity"]
    lot["cumulative_withdrawn"] -= withdrawal["quantity"]
    if lot["status"] == "DEPLETED" and lot["quantity_on_hand"] > 0:
        lot["status"] = "IN_ZONE"
    touch(lot)
    return lot


# ---------------------------------------------------------------------------
# Manipulation completion: output lot valuation (SCAFFOLD 1.3 manipulation_output_valuation)
# ---------------------------------------------------------------------------

def create_output_lot(order, source_lot):
    # Rounding order pinned: round input share first, add value_added, then round
    # the per-unit division.
    input_share = rhu_cents(Decimal(order["input_quantity"]) * Decimal(source_lot["unit_value_cents"]))
    output_basis = input_share + order["value_added_cents"]
    unit_value = rhu_cents(Decimal(output_basis) / Decimal(order["output_quantity"]))

    src_status = source_lot["zone_status"]
    if src_status == "PRIVILEGED_FOREIGN":
        rate = source_lot["duty_rate"]  # locked rate carries over
    elif src_status in ("NON_PRIVILEGED_FOREIGN", "ZONE_RESTRICTED"):
        rate = HTS_RATE_TABLE[order["output_hts_code"]]
    else:  # DOMESTIC
        rate = Decimal("0")

    lot = new_common()
    lot.update({
        "zone_id": order["zone_id"],
        "admission_id": None,
        "source_manipulation_id": order["id"],
        "importer_ref": source_lot["importer_ref"],
        "hts_code": order["output_hts_code"],
        "zone_status": src_status,
        "admitted_quantity": order["output_quantity"],
        "quantity_on_hand": order["output_quantity"],
        "reserved_quantity": 0,
        "cumulative_withdrawn": 0,
        "cumulative_consumed": 0,
        "unit_value_cents": unit_value,
        "duty_rate": rate,
        "status": "IN_ZONE",
    })
    db["lots"][lot["id"]] = lot
    return lot


# ---------------------------------------------------------------------------
# Audit-hold cascade (SCAFFOLD 1.2 Zone posture transitions, PRD 3.7)
# ---------------------------------------------------------------------------

def enter_audit_hold(zone):
    """NORMAL -> AUDIT_HOLD: freeze OPEN entries; detach their FILED withdrawals
    (forced back to DRAFT, weekly_entry_id cleared, lot quantity restored)."""
    zone["compliance_posture"] = "AUDIT_HOLD"
    touch(zone)
    for entry in list(db["weekly_entries"].values()):
        if entry["zone_id"] == zone["id"] and entry["status"] == "OPEN":
            entry["status"] = "FROZEN"
            touch(entry)
            for w in list(db["withdrawals"].values()):
                if w["weekly_entry_id"] == entry["id"] and w["status"] == "FILED":
                    w["status"] = "DRAFT"
                    w["weekly_entry_id"] = None
                    restore_lot_for_withdrawal(w)
                    touch(w)
    recompute_zone_aggregates(zone)


def exit_audit_hold(zone):
    """AUDIT_HOLD -> NORMAL: FROZEN entries return to OPEN; detached withdrawals
    stay DRAFT and are NOT re-attached."""
    zone["compliance_posture"] = "NORMAL"
    touch(zone)
    for entry in list(db["weekly_entries"].values()):
        if entry["zone_id"] == zone["id"] and entry["status"] == "FROZEN":
            entry["status"] = "OPEN"
            touch(entry)


# ---------------------------------------------------------------------------
# Reconciliation variance (SCAFFOLD 1.3 reconciliation_variance)
# ---------------------------------------------------------------------------

def compute_reconciliation_variance(recon, zone):
    year = recon["zone_year"]
    window_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    window_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    receipts = 0
    for a in db["admissions"].values():
        if (a["zone_id"] == zone["id"] and a["status"] == "ADMITTED"
                and a["admission_date"] is not None
                and window_start <= a["admission_date"] < window_end):
            receipts += a["quantity"] * a["unit_value_cents"]

    withdrawals_value = 0
    for w in db["withdrawals"].values():
        if (w["zone_id"] == zone["id"] and w["status"] in ("FILED", "DUTY_PAID", "EXPORTED")
                and w["withdrawal_date"] is not None
                and window_start <= w["withdrawal_date"] < window_end):
            lot = db["lots"][w["lot_id"]]
            withdrawals_value += w["quantity"] * lot["unit_value_cents"]

    book_ending = recon["beginning_value_cents"] + receipts - withdrawals_value
    discrepancy = recon["physical_ending_value_cents"] - book_ending
    if book_ending == 0:
        pct = Decimal("0") if recon["physical_ending_value_cents"] == 0 else Decimal("100")
    else:
        pct = (Decimal(abs(discrepancy)) / Decimal(book_ending) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    audit_flagged = pct > AUDIT_THRESHOLD_PCT  # strictly greater; exactly 0.5 does NOT flag

    recon["book_receipts_value_cents"] = receipts
    recon["book_withdrawals_value_cents"] = withdrawals_value
    recon["book_ending_value_cents"] = book_ending
    recon["discrepancy_cents"] = discrepancy
    recon["discrepancy_pct"] = pct
    recon["audit_flagged"] = audit_flagged


# ---------------------------------------------------------------------------
# Misc window helpers
# ---------------------------------------------------------------------------

def entry_week_end(week_start: datetime) -> datetime:
    return week_start + timedelta(days=ENTRY_WEEK_DAYS)
