"""Transport-domain helpers: PCS requirement, charge synthesis."""

from db import store
from services import calc
from services.common import init_common
from services.ledger import reconcile_transport_ledger


def pcs_requirement(transport):
    """PCS REQUIRED for a non-emergency transport from N or R origin (PRD §3.4).

    Returns "REQUIRED" or "NOT_REQUIRED".
    """
    if transport.get("emergency_indicator"):
        return "NOT_REQUIRED"
    if transport.get("origin_modifier") in ("N", "R"):
        return "REQUIRED"
    return "NOT_REQUIRED"


def synthesize_charges(transport):
    """Resolve HCPCS lines and create the two Charge rows, then reconcile.

    Called on IMPORTED -> CODED. Sets level_of_service must already be applied.
    """
    los = transport["level_of_service"]
    emergency = transport.get("emergency_indicator", False)
    base_code = calc.resolve_base_code(los, emergency)

    base_billed = calc.compute_base_billed(base_code)
    base_charge = {
        "transport_id": transport["id"],
        "charge_type": "BASE_RATE",
        "hcpcs_code": base_code,
        "units": 1,
        "billed_amount_cents": base_billed,
    }
    init_common(base_charge)
    store.charges[base_charge["id"]] = base_charge

    mileage_billed = calc.compute_mileage_billed(
        transport["loaded_miles"], transport.get("is_rural_pickup", False)
    )
    mileage_charge = {
        "transport_id": transport["id"],
        "charge_type": "MILEAGE",
        "hcpcs_code": calc.MILEAGE_CODE,
        "units": transport["loaded_miles"],
        "billed_amount_cents": mileage_billed,
    }
    init_common(mileage_charge)
    store.charges[mileage_charge["id"]] = mileage_charge

    reconcile_transport_ledger(transport)
