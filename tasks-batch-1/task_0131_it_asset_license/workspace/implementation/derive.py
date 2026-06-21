"""Derived-field recomputation (PRD 2.6).

These keep derived fields consistent on every mutation / read that could affect
them. Whenever a derived field is recomputed as part of handling a request, the
owning resource is treated as mutated (version++/updated_at refresh) — but ONLY
when the recompute actually changes a value (so a pure read that finds nothing
changed does not gratuitously bump version).
"""
import db
import clock
from calculations import depreciation


def recompute_asset_support_status(asset):
    """Resolve support_status from coverage spanning the current server clock.

    IN_WARRANTY / LEASED when an ACTIVE (or RENEWED) coverage whose window spans
    the clock exists (warranty vs lease); OUT_OF_WARRANTY when coverage existed
    but the clock is past its end; UNCOVERED when no coverage ever applied
    (PRD 3.2). Coverage past its end is treated as expired for support purposes.
    Returns True if the value changed.
    """
    now = clock.get_now()
    has_warranty = False
    has_lease = False
    had_any_coverage = False
    for cov in db.warranty_leases.values():
        if cov["hardware_asset_id"] != asset["id"]:
            continue
        if cov["status"] in ("ACTIVE", "RENEWED"):
            had_any_coverage = True
            if cov["coverage_start"] <= now <= cov["coverage_end"]:
                if cov["coverage_type"] == "WARRANTY":
                    has_warranty = True
                else:
                    has_lease = True

    if has_warranty:
        new_status = "IN_WARRANTY"
    elif has_lease:
        new_status = "LEASED"
    elif had_any_coverage:
        new_status = "OUT_OF_WARRANTY"
    else:
        new_status = "UNCOVERED"

    if asset.get("support_status") != new_status:
        asset["support_status"] = new_status
        return True
    return False


def recompute_asset_depreciation(asset, final=False, as_of=None):
    """Recompute accumulated_depreciation_cents and net_book_value_cents.

    Provisional unless final=True. Returns True if any value changed.
    """
    if as_of is None:
        as_of = clock.get_now()
    accumulated, nbv = depreciation(asset, as_of, final=final)
    changed = (
        asset.get("accumulated_depreciation_cents") != accumulated
        or asset.get("net_book_value_cents") != nbv
    )
    asset["accumulated_depreciation_cents"] = accumulated
    asset["net_book_value_cents"] = nbv
    return changed


def refresh_asset_on_read(asset):
    """On every read of an asset, refresh provisional depreciation + support
    status against the current clock. A change counts as a mutation (PRD 2.6).

    Disposed assets keep their finalized depreciation/proceeds/gain-loss — they
    are not recomputed provisionally once disposed.
    """
    changed = False
    if asset["status"] != "DISPOSED":
        if recompute_asset_depreciation(asset):
            changed = True
    if recompute_asset_support_status(asset):
        changed = True
    if changed:
        db.touch(asset)
    return asset


def employee_open_checkout_count(employee_id):
    """Live count of OPEN checkouts for an employee (PRD 2.6)."""
    return sum(
        1
        for c in db.assignment_checkouts.values()
        if c["employee_id"] == employee_id and c["status"] == "OPEN"
    )


def recompute_entitlement_units(entitlement):
    """Keep available_units = entitled_units - consumed_units consistent.

    consumed_units is maintained incrementally on install activate/uninstall;
    here we just (re)derive available_units. Returns True if changed.
    """
    available = entitlement["entitled_units"] - entitlement["consumed_units"]
    if entitlement.get("available_units") != available:
        entitlement["available_units"] = available
        return True
    return False
