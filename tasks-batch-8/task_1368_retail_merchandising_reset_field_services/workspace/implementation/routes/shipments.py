from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("shipments", __name__)
COLL = "shipments"

# scan_result -> (allowed from-states, to-state, penalty points or None)
SCAN_TRANSITIONS = {
    "IN_TRANSIT": ({"LABEL_CREATED", "IN_TRANSIT", "DELIVERY_EXCEPTION"}, "IN_TRANSIT", None),
    "EXCEPTION": ({"LABEL_CREATED", "IN_TRANSIT"}, "DELIVERY_EXCEPTION", services.DELIVERY_EXCEPTION_PENALTY),
    "DELIVERED": ({"IN_TRANSIT", "DELIVERY_EXCEPTION"}, "DELIVERED", None),  # late fee handled separately
    "LOST": ({"IN_TRANSIT"}, "LOST", services.LOST_PENALTY),
}


def _get_shipment_or_404(sid):
    s = db.collections[COLL].get(sid)
    if s is None:
        raise errors.not_found("fixture shipment not found")
    return s


@bp.post("/fixture-shipments")
def create_shipment():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    # Priority 3: existence, left-to-right.
    project = None
    pid = body.get("project_id")
    if pid is not None:
        if not isinstance(pid, str) or pid not in db.collections["projects"]:
            raise errors.not_found("project not found")
        project = db.collections["projects"][pid]
    ps = None
    psid = body.get("project_store_id")
    if psid is not None:
        if not isinstance(psid, str) or psid not in db.collections["project_stores"]:
            raise errors.not_found("project-store row not found")
        ps = db.collections["project_stores"][psid]
    # Priority 5: cross-entity ownership.
    if project is not None and ps is not None and ps["project_id"] != pid:
        raise errors.cross_entity_mismatch("project_store does not belong to project")
    # Priority 13: input sanitization.
    if project is None:
        raise errors.invalid_request("project_id is required")
    if ps is None:
        raise errors.invalid_request("project_store_id is required")
    carrier = mw.req_str(body, "carrier")
    tracking = mw.req_str(body, "tracking_number")
    promised_raw = body.get("promised_date")
    promised = mw.parse_date(promised_raw) if promised_raw is not None else None
    if promised is None:
        raise errors.invalid_request("promised_date is required and must be an ISO date")
    s = db.base_fields()
    s.update({
        "project_id": pid,
        "project_store_id": psid,
        "carrier": carrier,
        "tracking_number": tracking,
        "status": "LABEL_CREATED",
        "promised_date": promised_raw,
    })
    db.collections[COLL][s["id"]] = s
    return resp.success_object(db.serialize(s), 201)


@bp.get("/fixture-shipments")
def list_shipments():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [s for s in items
                 if (services.get_project(s["project_id"]) or {}).get("client_id") == uid]
    for key in ("project_id", "project_store_id", "status"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [s for s in items if s.get(key) == v]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/fixture-shipments/<sid>")
def get_shipment(sid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    s = _get_shipment_or_404(sid)
    if role == "Client":
        project = services.get_project(s["project_id"])
        if project is None or project["client_id"] != uid:
            raise errors.unauthorized("client acting on another client's project")
    return resp.success_object(db.serialize(s))


@bp.post("/fixture-shipments/<sid>/scan")
def scan_shipment(sid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    s = _get_shipment_or_404(sid)
    body = mw.get_body()
    scan_result = body.get("scan_result")
    transition = SCAN_TRANSITIONS.get(scan_result) if isinstance(scan_result, str) else None
    # Priority 4: state legality (depends on the requested scan transition).
    if transition is not None:
        allowed_from, to_state, penalty = transition
        if s["status"] not in allowed_from:
            raise errors.invalid_state(
                f"scan {scan_result} not allowed from {s['status']}")
    # Priority 13: input sanitization.
    if transition is None:
        raise errors.invalid_request(
            "scan_result is required and must be one of IN_TRANSIT, DELIVERED, EXCEPTION, LOST")
    allowed_from, to_state, penalty = transition
    s["status"] = to_state
    db.touch(s)
    # Penalties re-derive the project posture.
    project = services.get_project(s["project_id"])
    if project is not None:
        if scan_result == "DELIVERED":
            promised = mw.parse_date(s.get("promised_date"))
            if promised is not None and db.now().date() > promised:
                services.add_penalty(project, services.LATE_DELIVERY_PENALTY)
        elif penalty is not None:
            services.add_penalty(project, penalty)
    return resp.success_object(db.serialize(s))
