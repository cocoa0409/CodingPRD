"""Shared lookup and guard helpers used by every route module.

Path identifiers resolve strictly left to right and the first segment that does
not resolve determines the error (PRD 2.6).  Body references resolve the same
way, in the order the endpoint declares its input fields.
"""
from db import store
from errors import ApiError
from services import compute as K


def _find(collection, key, error_id, label):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id, "%s '%s' was not found." % (label, key))
    return row


def get_pollutant(pid):
    return _find(store.pollutants, pid, "ERR_POLLUTANT_NOT_FOUND", "Pollutant")


def get_method(mid):
    return _find(store.reference_methods, mid, "ERR_REFERENCE_METHOD_NOT_FOUND", "Reference method")


def get_network(nid):
    return _find(store.networks, nid, "ERR_NETWORK_NOT_FOUND", "Monitoring network")


def get_site(sid):
    return _find(store.sites, sid, "ERR_SITE_NOT_FOUND", "Monitoring site")


def get_monitor(mid):
    return _find(store.monitors, mid, "ERR_MONITOR_NOT_FOUND", "Monitor")


def get_batch(bid):
    return _find(store.data_batches, bid, "ERR_DATA_BATCH_NOT_FOUND", "Data batch")


def get_invalidation(iid):
    return _find(store.invalidations, iid, "ERR_INVALIDATION_NOT_FOUND", "Data invalidation")


def get_demonstration(did):
    return _find(store.demonstrations, did, "ERR_DEMONSTRATION_NOT_FOUND", "Demonstration")


def get_design_value(dvid):
    return _find(store.design_values, dvid, "ERR_DESIGN_VALUE_NOT_FOUND", "Design value")


def get_assessment(aid):
    return _find(store.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND", "Network assessment")


def get_change_request(cid):
    return _find(store.change_requests, cid, "ERR_CHANGE_REQUEST_NOT_FOUND", "Change request")


def get_package(pid):
    return _find(store.packages, pid, "ERR_PACKAGE_NOT_FOUND", "Certification package")


# --------------------------------------------------------------------------
# state guards -- the terminal check runs before the from-state check, per the
# transition prose of PRD 3.1 and 3.5
# --------------------------------------------------------------------------
def ensure_not_terminal(current, terminal_states, label="record"):
    if current in terminal_states:
        raise ApiError(
            "ERR_ALREADY_TERMINAL",
            "The %s is already in terminal state %s." % (label, current),
        )


def ensure_from_state(current, allowed, label="record"):
    if current not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The %s is in state %s; this transition requires one of %s."
            % (label, current, ", ".join(sorted(allowed))),
        )


def invalid_state(message):
    raise ApiError("ERR_INVALID_STATE", message)


def require_method_designated(method):
    """PRD 3.1: designation_status in {DESIGNATED, CONDITIONAL}, effective_from
    at or before the clock, withdrawn_on null or strictly after the clock."""
    if not K.method_is_currently_designated(method):
        raise ApiError(
            "ERR_METHOD_NOT_DESIGNATED",
            "The governing reference method is not currently designated.",
        )


def network_of(site):
    return store.networks.get(site["network_id"]) if site is not None else None
