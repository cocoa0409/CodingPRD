"""Cascading side effects: lot invalidation, trade invalidation, vendor
revocation, vintage-expiry sweep, and posture re-derivation."""
import db
from services import calculations


def _touch(row):
    row["version"] += 1
    row["updated_at"] = db.now_utc()


def invalidate_lot(lot):
    """ACTIVE -> INVALIDATED with full cascade to ObligationYear counters and
    ACCEPTED ComplianceReports for the affected years.

    Pending allocations are released from their batches (batches stay SUBMITTED
    and fail decide with ERR_INSUFFICIENT_RINS).
    """
    if lot["status"] == "INVALIDATED":
        return
    lot["invalidated_qty"] = lot["rin_qty"] - lot["retired_qty"] - lot["expired_qty"]
    lot["attached_qty"] = 0
    lot["separated_qty"] = 0
    lot["pending_retired_qty"] = 0
    lot["available_qty"] = 0
    lot["status"] = "INVALIDATED"
    _touch(lot)

    # Re-derive retirement counters for every obligation year of this account
    # whose ACCEPTED batches had allocations on this lot, then posture.
    affected_year_ids = set()
    for batch in db.retirement_batches.values():
        if batch["status"] != "ACCEPTED":
            continue
        for alloc in batch["allocations"]:
            if alloc["rin_lot_id"] == lot["id"]:
                affected_year_ids.add(batch["obligation_year_id"])
                break

    for year_id in affected_year_ids:
        year = db.obligation_years.get(year_id)
        if year is None:
            continue
        calculations.rederive_year_retirement_counters(year)
        calculations.rederive_posture(year)
        _touch(year)
        # ACCEPTED reports for that year -> REJECTED with amendment_required = true
        for report in db.compliance_reports.values():
            if report["obligation_year_id"] == year_id and report["status"] == "ACCEPTED":
                report["status"] = "REJECTED"
                report["amendment_required"] = True
                _touch(report)


def invalidate_trade(trade):
    """DELIVERED/VERIFIED -> INVALIDATED; cascades into the PURCHASED lot."""
    if trade["transfer_status"] == "INVALIDATED":
        return
    trade["transfer_status"] = "INVALIDATED"
    _touch(trade)
    for lot in db.rin_lots.values():
        if lot.get("trade_id") == trade["id"]:
            invalidate_lot(lot)


def revoke_vendor_cascade(vendor):
    """Every trade of the vendor with transfer DELIVERED or VERIFIED -> INVALIDATED."""
    for trade in list(db.rin_trades.values()):
        if trade["vendor_id"] != vendor["id"]:
            continue
        if trade["transfer_status"] in ("DELIVERED", "VERIFIED"):
            invalidate_trade(trade)


def expire_lot(lot):
    """ACTIVE -> EXPIRED per rin_vintage_expiry."""
    if lot["status"] != "ACTIVE":
        return
    lot["expired_qty"] = lot["rin_qty"] - lot["retired_qty"] - lot["invalidated_qty"]
    lot["attached_qty"] = 0
    lot["separated_qty"] = 0
    lot["pending_retired_qty"] = 0
    lot["available_qty"] = 0
    lot["status"] = "EXPIRED"
    _touch(lot)


def vintage_expiry_sweep():
    """Expire all ACTIVE lots whose vintage deadline has passed."""
    now = db.now_utc()
    for lot in list(db.rin_lots.values()):
        if lot["status"] != "ACTIVE":
            continue
        deadline = db.march31_deadline(lot["vintage_year"] + 2)
        if now > deadline:
            expire_lot(lot)


def rederive_all_postures():
    for year in db.obligation_years.values():
        posture = calculations.derive_posture(year)
        if posture != year["compliance_posture"]:
            year["compliance_posture"] = posture
            _touch(year)
