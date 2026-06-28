"""Resource resolution and ownership helpers (PRD 2.9)."""
from db import store
from errors import err


def get_plan(pid):
    r = store.monitoring_plans.get(pid)
    if r is None:
        raise err("ERR_NOT_FOUND", "MonitoringPlan not found: %s" % pid)
    return r


def get_subscriber(sid):
    r = store.subscribers.get(sid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Subscriber not found: %s" % sid)
    return r


def get_contract(cid):
    r = store.contracts.get(cid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Contract not found: %s" % cid)
    return r


def get_device(did):
    r = store.devices.get(did)
    if r is None:
        raise err("ERR_NOT_FOUND", "Device not found: %s" % did)
    return r


def get_contact(cid):
    r = store.emergency_contacts.get(cid)
    if r is None:
        raise err("ERR_NOT_FOUND", "EmergencyContact not found: %s" % cid)
    return r


def get_alarm(aid):
    r = store.alarm_events.get(aid)
    if r is None:
        raise err("ERR_NOT_FOUND", "AlarmEvent not found: %s" % aid)
    return r


def get_dispatch(did):
    r = store.dispatch_actions.get(did)
    if r is None:
        raise err("ERR_NOT_FOUND", "DispatchAction not found: %s" % did)
    return r


def get_equipment_return(rid):
    r = store.equipment_returns.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "EquipmentReturn not found: %s" % rid)
    return r


def get_agent_shift(sid):
    r = store.agent_shifts.get(sid)
    if r is None:
        raise err("ERR_NOT_FOUND", "AgentShift not found: %s" % sid)
    return r


def get_hold(hid):
    r = store.monitoring_holds.get(hid)
    if r is None:
        raise err("ERR_NOT_FOUND", "MonitoringHold not found: %s" % hid)
    return r


def devices_for_contract(contract_id):
    return [d for d in store.devices.values() if d["contract_id"] == contract_id]


def contacts_for_subscriber(subscriber_id):
    return [c for c in store.emergency_contacts.values() if c["subscriber_id"] == subscriber_id]


def active_contacts_for_subscriber(subscriber_id):
    return [c for c in contacts_for_subscriber(subscriber_id) if c["active"]]


# ---- ownership (PRD 2.1, 2.9) ----
def require_owner_subscriber(role, user_id, subscriber_id):
    """For subscriber-scoped writes: X-User-ID must equal subscriber_id (priority 4)."""
    if role == "Subscriber" and user_id != subscriber_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Subscriber does not own this resource")
