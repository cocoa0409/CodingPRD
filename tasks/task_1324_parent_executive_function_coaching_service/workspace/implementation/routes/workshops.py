"""Workshop and WorkshopEnrollment endpoints."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope, get_body,
                        require_fields, get_entity, touch, new_common, workshop_pub,
                        enrollment_pub, list_response)
from response import success_object
from services import workshops as ws_svc

bp = Blueprint("workshops", __name__)


@bp.post("/workshops")
def create_workshop():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    body = get_body()
    require_fields(body, ["title", "coach_id", "capacity", "window_start",
                          "window_end", "price_cents"])
    get_entity("coach", body["coach_id"])
    mw.int_check(body["capacity"], "capacity", minimum=1)
    mw.int_check(body["price_cents"], "price_cents", minimum=0)
    ws = mw.parse_dt(body["window_start"], "window_start")
    we = mw.parse_dt(body["window_end"], "window_end")
    if we <= ws:
        E.raise_error(E.ERR_VALIDATION, "window_end must be after window_start")
    w = new_common()
    w.update({
        "title": body["title"],
        "coach_id": body["coach_id"],
        "capacity": body["capacity"],
        "window_start": db.iso(ws),
        "window_end": db.iso(we),
        "window_start_dt": ws,
        "window_end_dt": we,
        "price_cents": body["price_cents"],
        "seats_taken": 0,
        "status": "DRAFT",
    })
    db.workshops[w["id"]] = w
    return success_object(workshop_pub(w), 201)


@bp.get("/workshops/<wid>")
def get_workshop(wid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    w = get_entity("workshop", wid)
    return success_object(workshop_pub(w), 200)


@bp.get("/workshops")
def list_workshops():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    return list_response(list(db.workshops.values()), workshop_pub, paginate=True)


@bp.post("/workshops/<wid>/transition")
def workshop_transition(wid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    w = get_entity("workshop", wid)
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["OPEN", "LOCKED", "COMPLETED", "CANCELLED"], "to_state")

    if to == "OPEN":
        if w["status"] != "DRAFT":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition workshop from %s to OPEN" % w["status"])
        coach = db.coaches[w["coach_id"]]
        if coach["status"] == "INACTIVE":
            E.raise_error(E.ERR_INVALID_STATE, "Facilitating coach is INACTIVE")
        if w["window_start_dt"] <= db.clock:
            E.raise_error(E.ERR_SESSION_IN_PAST,
                          "window_start must be strictly in the future")
        w["status"] = "OPEN"

    elif to == "LOCKED":
        if w["status"] != "OPEN":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition workshop from %s to LOCKED" % w["status"])
        w["status"] = "LOCKED"

    elif to == "COMPLETED":
        if w["status"] != "LOCKED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition workshop from %s to COMPLETED" % w["status"])
        if db.clock < w["window_end_dt"]:
            E.raise_error(E.ERR_WORKSHOP_WINDOW_NOT_ENDED,
                          "Workshop window has not ended")
        for e in db.enrollments.values():
            if e["workshop_id"] == wid and e["status"] == "WAITLISTED":
                e["status"] = "DROPPED"
                e["waitlist_position"] = None
                touch(e)
        w["status"] = "COMPLETED"

    else:  # CANCELLED
        if w["status"] not in ("OPEN", "LOCKED"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition workshop from %s to CANCELLED" % w["status"])
        for e in sorted((e for e in db.enrollments.values() if e["workshop_id"] == wid),
                        key=lambda e: (e["created_at"], e["seq"])):
            if e["status"] == "ENROLLED":
                ws_svc.refund_enrollment(e, w, honor_money_window=False)
                w["seats_taken"] -= 1
            elif e["status"] == "WAITLISTED":
                e["status"] = "DROPPED"
                e["waitlist_position"] = None
                touch(e)
        w["status"] = "CANCELLED"

    touch(w)
    return success_object(workshop_pub(w), 200)


@bp.post("/workshops/<wid>/enrollments")
def create_enrollment(wid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    w = get_entity("workshop", wid)
    body = get_body()
    require_fields(body, ["client_id"])
    client = get_entity("client", body["client_id"])
    require_family_scope(auth, client["family_id"])
    fam = db.families[client["family_id"]]

    # State gates (priority 8, 9, 13).
    if fam["status"] != "ACTIVE":
        E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is not ACTIVE")
    if client["status"] != "ACTIVE":
        E.raise_error(E.ERR_CLIENT_NOT_ACTIVE, "Client is not ACTIVE")
    if w["status"] != "OPEN":
        if w["status"] == "LOCKED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Workshop is LOCKED; roster is frozen")
        E.raise_error(E.ERR_WORKSHOP_NOT_OPEN, "Workshop is not OPEN")
    # Duplicate (priority 21) before track linkage (priority 22).
    if any(e["workshop_id"] == wid and e["client_id"] == client["id"]
           and e["status"] in ("ENROLLED", "WAITLISTED")
           for e in db.enrollments.values()):
        E.raise_error(E.ERR_DUPLICATE_ENROLLMENT,
                      "A non-terminal enrollment already exists for this client")
    if client["track"] not in ("GROUP", "HYBRID"):
        E.raise_error(E.ERR_TRACK_MISMATCH,
                      "Client track must be GROUP or HYBRID for workshop enrollment")

    e = new_common()
    e.update({
        "workshop_id": wid,
        "client_id": client["id"],
        "status": "ENROLLED",
        "waitlist_position": None,
        "billing_source": "NONE",
        "charged_cents": 0,
        "package_id": None,
    })
    db.enrollments[e["id"]] = e
    if w["seats_taken"] < w["capacity"]:
        ws_svc.apply_enrollment_billing(e, w, client["family_id"])
        w["seats_taken"] += 1
    else:
        e["status"] = "WAITLISTED"
        e["billing_source"] = "NONE"
        e["charged_cents"] = 0
    touch(w)
    ws_svc.renumber_waitlist(wid)
    return success_object(enrollment_pub(e), 201)


@bp.get("/workshops/<wid>/enrollments")
def list_workshop_enrollments(wid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    get_entity("workshop", wid)
    rows = [e for e in db.enrollments.values() if e["workshop_id"] == wid]
    return list_response(rows, enrollment_pub, paginate=False)


@bp.get("/clients/<cid>/enrollments")
def list_client_enrollments(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    rows = [e for e in db.enrollments.values() if e["client_id"] == cid]
    return list_response(rows, enrollment_pub, paginate=False)


@bp.post("/enrollments/<eid>/drop")
def drop_enrollment(eid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    e = get_entity("enrollment", eid)
    client = db.clients[e["client_id"]]
    require_family_scope(auth, client["family_id"])
    w = db.workshops[e["workshop_id"]]
    # Workshop gate (priority 13) fires before the enrollment aggregate gate (p15).
    if w["status"] != "OPEN":
        if w["status"] == "LOCKED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Workshop is LOCKED; roster is frozen")
        E.raise_error(E.ERR_WORKSHOP_NOT_OPEN, "Workshop is not OPEN")
    if e["status"] in ("DROPPED", "REFUNDED"):
        E.raise_error(E.ERR_ENROLLMENT_NOT_DROPPABLE,
                      "Enrollment is %s and cannot be dropped" % e["status"])

    if e["status"] == "ENROLLED":
        client_fam_id = client["family_id"]
        # Refund by source.
        if e["billing_source"] == "MONEY":
            from services import billing
            from datetime import timedelta
            if db.clock <= w["window_start_dt"] - timedelta(days=ws_svc.WORKSHOP_REFUND_WINDOW_DAYS):
                fam = db.families[client_fam_id]
                billing.refund_family(fam, e["charged_cents"])
                touch(fam)
        elif e["billing_source"] == "PACKAGE_CREDIT":
            from services import billing
            pkg = db.packages.get(e["package_id"])
            # ACTIVE and EXHAUSTED packages accept the returned credit (revival);
            # EXPIRED / REFUNDED packages yield no compensation.
            if pkg is not None and pkg["status"] in ("ACTIVE", "EXHAUSTED"):
                pkg["credits_consumed"] -= 1
                touch(pkg)
                billing.recompute_package_status(pkg)
        e["status"] = "DROPPED"
        e["waitlist_position"] = None
        touch(e)
        w["seats_taken"] -= 1
        touch(w)
        ws_svc.promote_waitlist_head(w)
    else:  # WAITLISTED drop: never charged.
        e["status"] = "DROPPED"
        e["waitlist_position"] = None
        touch(e)
    ws_svc.renumber_waitlist(w["id"])
    return success_object(enrollment_pub(e), 200)
