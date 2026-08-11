from flask import Blueprint

import calc
import core
import gates
import serialize
from core import fail, get, now, touch
from gates import check_state

bp = Blueprint("findings", __name__)

FILTERS = ["visit_id", "property_id", "status", "severity"]
READ_ROLES = ["Dispatcher", "FieldTech", "AccountManager", "PlatformAdmin", "Owner", "Auditor"]


@bp.get("/property-care/findings")
def list_findings():
    gates.begin(READ_ROLES)
    return gates.list_response("findings", FILTERS, serialize.finding)


@bp.get("/property-care/findings/<fid>")
def read_finding(fid):
    role, user_id = gates.begin(READ_ROLES)
    finding = gates.fetch_path("findings", fid)
    prop = get("properties", finding["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.finding(finding))


@bp.post("/property-care/findings/<fid>/triage")
def triage(fid):
    gates.begin(["Dispatcher"])
    finding = gates.fetch_path("findings", fid)
    check_state("finding", finding, ["OPEN", "MONITORING"])
    source = finding["status"]
    if source == "OPEN":
        parent = get("visits", finding.get("visit_id"))
        if parent is None or parent["status"] != "COMPLETED":
            fail("ERR_PARENT_VISIT_NOT_COMPLETED", "The parent visit is not COMPLETED.")
    else:
        anchor = finding.get("triaged_at")
        recheck = False
        for v in calc.children("visits", "property_id", finding["property_id"]):
            if v["status"] == "COMPLETED" and v["completed_at"] is not None and \
                    (anchor is None or v["completed_at"] > anchor):
                recheck = True
                break
        if not recheck:
            fail("ERR_NO_RECHECK_VISIT", "No later completed visit exists on this property.")
        finding["monitor_recheck_count"] += 1

    prop = get("properties", finding["property_id"])
    finding["status"] = "TRIAGED"
    finding["triaged_at"] = now()
    finding["escalation_score"] = calc.finding_escalation_score(finding, prop)
    touch(finding)
    return core.ok(serialize.finding(finding))


@bp.post("/property-care/findings/<fid>/monitor")
def monitor(fid):
    gates.begin(["Dispatcher"])
    finding = gates.fetch_path("findings", fid)
    check_state("finding", finding, ["TRIAGED"])
    if finding["severity"] not in ("LOW", "MEDIUM"):
        fail("ERR_SEVERITY_TOO_HIGH_TO_MONITOR", "Only LOW or MEDIUM findings may be monitored.")
    finding["status"] = "MONITORING"
    touch(finding)
    return core.ok(serialize.finding(finding))


@bp.post("/property-care/findings/<fid>/dismiss")
def dismiss(fid):
    role, user_id = gates.begin(["Dispatcher", "Owner"])
    finding = gates.fetch_path("findings", fid)
    prop = get("properties", finding["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    check_state("finding", finding, ["TRIAGED", "MONITORING"])
    for wo in calc.children("work_orders", "finding_id", finding["id"]):
        if wo["status"] not in ("REJECTED", "VOID"):
            fail("ERR_FINDING_HAS_LIVE_WORK_ORDER", "A live work order exists on this finding.")
    finding["status"] = "DISMISSED"
    finding["dismissed_at"] = now()
    touch(finding)
    return core.ok(serialize.finding(finding))
