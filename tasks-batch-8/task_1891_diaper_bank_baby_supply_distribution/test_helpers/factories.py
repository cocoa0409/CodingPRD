"""Payload factories — one per entity, input fields only.

Optional fields with PRD-declared defaults (restriction, formula_variant,
discount_pct, consent_on_file, privacy_restricted) are omitted from the payload
unless the caller supplies them, so tests exercise the server-side defaults.

Human-meaningful codes (agency_code, grant_code, household_code) are unique per
creation call via process-local counters; every test runs against a fresh
server, so counters never collide with persisted state.
"""
import itertools

from .constants import (
    CURRENT_PERIOD,
    DEFAULT_EVENT_ENDS,
    DEFAULT_EVENT_STARTS,
    DEFAULT_SHIFT_ENDS,
    DEFAULT_SHIFT_STARTS,
    GRANT_WINDOW_END,
    GRANT_WINDOW_START,
)

_agency_seq = itertools.count(1)
_grant_seq = itertools.count(1)
_household_seq = itertools.count(1)
_donor_seq = itertools.count(1)
_vendor_seq = itertools.count(1)
_shift_seq = itertools.count(1)


def supply_line(size_code, quantity) -> dict:
    """One {size_code, quantity} line (intake batches and issuances)."""
    return {"size_code": size_code, "quantity": quantity}


def purchase_line(size_code, quantity, unit_cost_cents) -> dict:
    """One {size_code, quantity, unit_cost_cents} purchase-order line."""
    return {"size_code": size_code, "quantity": quantity,
            "unit_cost_cents": unit_cost_cents}


def create_agency_payload(**overrides) -> dict:
    n = next(_agency_seq)
    defaults = {
        "name": f"Agency {n}",
        "agency_code": f"AG-{n:04d}",
        "contact_email": f"agency{n}@example.org",
        "children_served_monthly": 300,
        "storage_capacity_units": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    n = next(_grant_seq)
    defaults = {
        "funder_name": f"Funder {n}",
        "grant_code": f"GR-{n:04d}",
        "total_amount_cents": 100000,
        "start_date": GRANT_WINDOW_START,
        "end_date": GRANT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_intake_batch_payload(donor_name=None, lines=None, **overrides) -> dict:
    n = next(_donor_seq)
    payload = {
        "donor_name": donor_name if donor_name is not None else f"Donor {n}",
        "lines": lines if lines is not None else [supply_line("SIZE_1", 100)],
    }
    payload.update(overrides)
    return payload


def create_purchase_order_payload(grant_id, lines=None, vendor_name=None,
                                  discount_pct=None, **overrides) -> dict:
    n = next(_vendor_seq)
    payload = {
        "grant_id": grant_id,
        "vendor_name": vendor_name if vendor_name is not None else f"Wholesale Co {n}",
        "lines": lines if lines is not None else [purchase_line("SIZE_1", 1, 1000)],
    }
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    payload.update(overrides)
    return payload


def create_allocation_run_payload(period=CURRENT_PERIOD, formula_variant=None,
                                  **overrides) -> dict:
    payload = {"period": period}
    if formula_variant is not None:
        payload["formula_variant"] = formula_variant
    payload.update(overrides)
    return payload


def create_event_payload(host_agency_id, site_name="T-Site",
                         starts_at=DEFAULT_EVENT_STARTS,
                         ends_at=DEFAULT_EVENT_ENDS, **overrides) -> dict:
    payload = {
        "host_agency_id": host_agency_id,
        "site_name": site_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def create_issuance_payload(household_id, lines=None, **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "lines": lines if lines is not None else [supply_line("SIZE_1", 10)],
    }
    payload.update(overrides)
    return payload


def create_household_payload(household_code=None, children_sizes=None,
                             consent_on_file=None, privacy_restricted=None,
                             **overrides) -> dict:
    n = next(_household_seq)
    payload = {
        "household_code": household_code if household_code is not None else f"HH-{n:04d}",
        "children_sizes": list(children_sizes) if children_sizes is not None else ["SIZE_1"],
    }
    if consent_on_file is not None:
        payload["consent_on_file"] = consent_on_file
    if privacy_restricted is not None:
        payload["privacy_restricted"] = privacy_restricted
    payload.update(overrides)
    return payload


def create_volunteer_shift_payload(title=None, starts_at=DEFAULT_SHIFT_STARTS,
                                   ends_at=DEFAULT_SHIFT_ENDS, capacity=2,
                                   **overrides) -> dict:
    n = next(_shift_seq)
    payload = {
        "title": title if title is not None else f"Shift {n}",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


def create_signup_payload(volunteer_email, volunteer_name="Vol Unteer",
                          **overrides) -> dict:
    payload = {
        "volunteer_email": volunteer_email,
        "volunteer_name": volunteer_name,
    }
    payload.update(overrides)
    return payload


def create_adjustment_payload(size_code, new_on_hand_units, reason,
                              expected_inventory_version, **overrides) -> dict:
    payload = {
        "size_code": size_code,
        "new_on_hand_units": new_on_hand_units,
        "reason": reason,
        "expected_inventory_version": expected_inventory_version,
    }
    payload.update(overrides)
    return payload
