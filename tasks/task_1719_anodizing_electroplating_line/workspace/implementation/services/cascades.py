"""Cascading side effects shared across bath lifecycle and exceedance flows.

Cascaded mutations count as ordinary mutations: each affected resource gets its
own updated_at refresh and version increment.
"""
from db import store
from helpers import touch
from services.chemistry import CHEMISTRY_TO_ANALYTE


def cascade_bath_quarantine(bath, cause):
    """Quarantine a bath (manual or exceedance). Caller must have verified the
    bath is ACTIVE. Sets quarantine_cause, moves ROUTED work orders on the bath
    to ROUTE_HELD. A RUNNING load is NOT aborted.
    """
    bath["status"] = "QUARANTINED"
    bath["quarantine_cause"] = cause
    touch(bath)
    _hold_routed_work_orders(bath["id"])


def cascade_bath_exhausted(bath):
    """ACTIVE -> EXHAUSTED on capacity reached; ROUTED work orders -> ROUTE_HELD."""
    bath["status"] = "EXHAUSTED"
    touch(bath)
    _hold_routed_work_orders(bath["id"])


def cascade_bath_released_to_active(bath):
    """ROUTE_HELD work orders on this bath return to ROUTED (only when the bath
    actually reaches ACTIVE)."""
    for wo in store.work_orders.values():
        if wo.get("bath_id") == bath["id"] and wo["status"] == "ROUTE_HELD":
            wo["status"] = "ROUTED"
            touch(wo)


def cascade_bath_dumped(bath):
    """Work orders in ROUTED or ROUTE_HELD linked to a dumped bath stay in or
    move to ROUTE_HELD."""
    for wo in store.work_orders.values():
        if wo.get("bath_id") == bath["id"] and wo["status"] in ("ROUTED", "ROUTE_HELD"):
            if wo["status"] != "ROUTE_HELD":
                wo["status"] = "ROUTE_HELD"
                touch(wo)


def _hold_routed_work_orders(bath_id):
    for wo in store.work_orders.values():
        if wo.get("bath_id") == bath_id and wo["status"] == "ROUTED":
            wo["status"] = "ROUTE_HELD"
            touch(wo)


def exceedance_cascade(permit, exceeded_analytes):
    """Flip the permit to EXCEEDED, set exceedance_active, and quarantine every
    ACTIVE bath whose chemistry family maps to any exceeded analyte; their
    ROUTED work orders move to ROUTE_HELD. All atomic within the request.
    """
    permit["status"] = "EXCEEDED"
    permit["exceedance_active"] = True
    touch(permit)
    for bath in store.baths.values():
        if bath["status"] != "ACTIVE":
            continue
        analyte = CHEMISTRY_TO_ANALYTE.get(bath["chemistry_family"])
        if analyte is not None and analyte in exceeded_analytes:
            cascade_bath_quarantine(bath, "DISCHARGE_EXCEEDANCE")


def permit_blocks_chemistry(chemistry_family):
    """True when some DischargePermit has exceedance_active true and a limit on
    the analyte this chemistry family maps to."""
    analyte = CHEMISTRY_TO_ANALYTE.get(chemistry_family)
    if analyte is None:
        return False
    for permit in store.permits.values():
        if not permit.get("exceedance_active"):
            continue
        for limit in permit["limits"]:
            if limit["analyte_code"] == analyte:
                return True
    return False
