"""Package locker release and fee finalization helpers."""
from db import db
from common import touch
import calculations as calc
import clock
from services import billing


def release_locker(package):
    """Release the locker assigned to the package: OCCUPIED -> AVAILABLE."""
    locker_id = package.get("locker_unit_id")
    if not locker_id:
        return
    locker = db.locker_units.get(locker_id)
    if locker is not None and locker["status"] == "OCCUPIED":
        locker["status"] = "AVAILABLE"
        locker["current_package_id"] = None
        touch(locker)
    package["locker_unit_id"] = None


def recompute_provisional_overstay(package, facility):
    """Provisional overstay against the facility's live clock; bumps version."""
    notified = clock.parse_iso(package.get("notified_at")) if package.get("notified_at") else None
    ref = clock.parse_iso(facility["current_utc"])
    locker = db.locker_units.get(package.get("locker_unit_id"))
    size_tier = locker["size_tier"] if locker else package["size_tier"]
    package["overstay_fee_cents"] = calc.overstay_fee_cents(
        notified, ref, size_tier, facility["time_zone"])


def finalize_overstay(package, facility, resolved_instant):
    """Final overstay against resolved_at; returns the frozen amount."""
    notified = clock.parse_iso(package.get("notified_at")) if package.get("notified_at") else None
    locker = db.locker_units.get(package.get("locker_unit_id"))
    size_tier = locker["size_tier"] if locker else package["size_tier"]
    fee = calc.overstay_fee_cents(notified, resolved_instant, size_tier, facility["time_zone"])
    package["overstay_fee_cents"] = fee
    return fee


def post_resolution_charges(package, agreement, invoice):
    """Post OVERSTAY (if>0) then OVERSIZE (if>0) charges for a resolved package."""
    overstay = package.get("overstay_fee_cents", 0)
    oversize = package.get("oversize_fee_cents", 0)
    if overstay > 0:
        billing.post_ledger_entry(invoice, "CHARGE", "OVERSTAY", overstay, package["id"])
    if oversize > 0:
        billing.post_ledger_entry(invoice, "CHARGE", "OVERSIZE", oversize, package["id"])


def invoice_for_agreement(agreement_id):
    for inv in db.invoices.values():
        if inv["rental_agreement_id"] == agreement_id:
            return inv
    return None
