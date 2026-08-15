"""Record helpers, lookup helpers, and parent-chain resolution."""

from db import store, new_id
from errors import not_found, reference_not_found, posture_blocked


def base_record():
    """Common system fields (PRD §2.4): id, created_at, updated_at, version=1."""
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    """Refresh updated_at and increment version on a mutation."""
    rec["updated_at"] = store.now_str()
    rec["version"] += 1


def set_fields(rec, **fields):
    """Set fields; bump version/updated_at only when a value actually changes."""
    changed = False
    for k, v in fields.items():
        if rec.get(k) != v:
            rec[k] = v
            changed = True
    if changed:
        touch(rec)
    return changed


def public(rec):
    """Strip internal fields (leading underscore) from the wire representation.
    Dates serialize as YYYY-MM-DD; datetimes as ISO 8601 UTC with 3 fractional
    digits."""
    from datetime import date, datetime
    from db import fmt_ts
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---- lookup helpers (path existence, PRD §2.6 priority 3) ----

def _get(table, rid, msg):
    rec = table.get(rid)
    if rec is None:
        raise not_found(msg)
    return rec


def get_contractor(cid):
    return _get(store.contractors, cid, "Contractor not found")


def get_technician(tid):
    return _get(store.technicians, tid, "Technician not found")


def get_license(lid):
    return _get(store.license_records, lid, "LicenseRecord not found")


def get_property(pid):
    return _get(store.properties, pid, "Property not found")


def get_system(sid):
    return _get(store.systems, sid, "ProtectedSystem not found")


def get_device(did):
    return _get(store.devices, did, "Device not found")


def get_plan(plid):
    return _get(store.plans, plid, "InspectionPlan not found")


def get_event(eid):
    return _get(store.events, eid, "InspectionEvent not found")


def get_deficiency(did):
    return _get(store.deficiencies, did, "Deficiency not found")


def get_impairment(iid):
    return _get(store.impairments, iid, "Impairment not found")


def get_report(rid):
    return _get(store.reports, rid, "MarshalReport not found")


def get_backflow_test(bid):
    return _get(store.backflow_tests, bid, "BackflowTest not found")


def get_pump_test(pid):
    return _get(store.pump_tests, pid, "FirePumpTest not found")


def get_alarm_case(aid):
    return _get(store.false_alarm_cases, aid, "FalseAlarmCase not found")


def get_permit(pid):
    return _get(store.permits, pid, "ModificationPermit not found")


# ---- body FK reference existence (priority 4) ----

def ref_technician(tid):
    rec = store.technicians.get(tid)
    if rec is None:
        raise reference_not_found("lead_technician_id references a non-existent Technician")
    return rec


def ref_system(sid):
    rec = store.systems.get(sid)
    if rec is None:
        raise reference_not_found("system_id references a non-existent ProtectedSystem")
    return rec


def ref_device(did, field="device_id"):
    rec = store.devices.get(did)
    if rec is None:
        raise reference_not_found(f"{field} references a non-existent Device")
    return rec


def ref_contractor(cid):
    rec = store.contractors.get(cid)
    if rec is None:
        raise reference_not_found("contractor_id references a non-existent Contractor")
    return rec


def ref_event(eid, field="coordinated_event_id"):
    rec = store.events.get(eid)
    if rec is None:
        raise reference_not_found(f"{field} references a non-existent InspectionEvent")
    return rec


# ---- parent-chain resolution ----

def contractor_of_property(prop):
    return store.contractors.get(prop["contractor_id"])


def contractor_of_system(sys):
    prop = store.properties.get(sys["property_id"])
    return contractor_of_property(prop) if prop else None


def contractor_of_plan(plan):
    prop = store.properties.get(plan["property_id"])
    return contractor_of_property(prop) if prop else None


def contractor_of_event(ev):
    plan = store.plans.get(ev["plan_id"])
    return contractor_of_plan(plan) if plan else None


def property_of_system(sys):
    return store.properties.get(sys["property_id"])


def property_of_plan(plan):
    return store.properties.get(plan["property_id"])


def property_of_event(ev):
    plan = store.plans.get(ev["plan_id"])
    return store.properties.get(plan["property_id"]) if plan else None


# ---- parent-scope state gates (PRD §2.6 priority 6) ----

def require_contractor_active(con):
    """A DEACTIVATED contractor rejects all child writes."""
    if con is not None and con["status"] != "ACTIVE":
        raise posture_blocked("Contractor is DEACTIVATED; all child writes are rejected")


def require_property_active(prop):
    if prop is not None and prop["status"] != "ACTIVE":
        raise posture_blocked("Property is ARCHIVED; child writes are rejected")


def gate_contractor_chain(con, prop=None):
    require_contractor_active(con)
    require_property_active(prop)
