"""Cross-entity lookup helpers."""

import db


def matching_cycle_for_read(read, statuses=None):
    """Find the BillingCycle whose property+utility+period align with a read.

    The read's utility is taken from its meter. Optionally filter by status set.
    Returns the first match, or None.
    """
    meter = db.meters.get(read["meter_id"])
    if meter is None:
        return None
    utility_id = meter["utility_id"]
    for cycle in db.billing_cycles.values():
        if (cycle["property_id"] == read["property_id"]
                and cycle["utility_id"] == utility_id
                and cycle["period_label"] == read["period_label"]):
            if statuses is None or cycle["status"] in statuses:
                return cycle
    return None
