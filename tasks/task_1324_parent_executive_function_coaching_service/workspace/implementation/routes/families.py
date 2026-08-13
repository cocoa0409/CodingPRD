"""Family endpoints: create, read, list, transition, payments."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope, get_body,
                        require_fields, get_entity, touch, new_common, family_pub,
                        list_response)
from response import success_object
from services import billing

bp = Blueprint("families", __name__)


@bp.post("/families")
def create_family():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    body = get_body()
    require_fields(body, ["account_name", "primary_email"])
    fam = new_common()
    fam.update({
        "account_name": body["account_name"],
        "primary_email": body["primary_email"],
        "status": "INTAKE",
        "total_charged_cents": 0,
        "total_refunded_cents": 0,
        "total_paid_cents": 0,
        "outstanding_balance_cents": 0,
        "billing_status": "CURRENT",
    })
    db.families[fam["id"]] = fam
    return success_object(family_pub(fam), 201)


@bp.get("/families/<fid>")
def get_family(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    fam = get_entity("family", fid)
    return success_object(family_pub(fam), 200)


@bp.get("/families")
def list_families():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    return list_response(list(db.families.values()), family_pub, paginate=True)


@bp.post("/families/<fid>/transition")
def family_transition(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    fam = get_entity("family", fid)
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["ACTIVE", "SUSPENDED", "CLOSED"], "to_state")

    if to == "ACTIVE":
        if fam["status"] == "INTAKE":
            has_client = any(c["family_id"] == fid for c in db.clients.values())
            if not has_client:
                E.raise_error(E.ERR_FAMILY_NO_CLIENTS,
                              "Family activation requires at least one client")
        elif fam["status"] == "SUSPENDED":
            if billing.family_outstanding(fam) > billing.DELINQUENCY_THRESHOLD_CENTS:
                E.raise_error(E.ERR_FAMILY_DELINQUENT,
                              "Outstanding balance exceeds the delinquency threshold")
        else:
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition family from %s to ACTIVE" % fam["status"])
        fam["status"] = "ACTIVE"
        touch(fam)
        billing.recompute_family_plan_postures(fid)

    elif to == "SUSPENDED":
        if fam["status"] != "ACTIVE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition family from %s to SUSPENDED" % fam["status"])
        billing.suspend_family(fam)

    else:  # CLOSED
        if fam["status"] not in ("ACTIVE", "SUSPENDED"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition family from %s to CLOSED" % fam["status"])
        family_client_ids = [c["id"] for c in db.clients.values() if c["family_id"] == fid]
        if any(p["client_id"] in family_client_ids and p["status"] == "ACTIVE"
               for p in db.plans.values()):
            E.raise_error(E.ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES,
                          "Family has an ACTIVE coaching plan")
        if any(p["family_id"] == fid and p["status"] == "ACTIVE"
               for p in db.packages.values()):
            E.raise_error(E.ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES,
                          "Family has an ACTIVE package")
        if any(e["client_id"] in family_client_ids and e["status"] in ("ENROLLED", "WAITLISTED")
               for e in db.enrollments.values()):
            E.raise_error(E.ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES,
                          "Family has an ENROLLED or WAITLISTED workshop enrollment")
        # Closure cascade.
        for c in db.clients.values():
            if c["family_id"] == fid and c["status"] in ("INTAKE", "ACTIVE", "PAUSED"):
                c["status"] = "DISCHARGED"
                touch(c)
        for ct in db.contacts.values():
            if ct["family_id"] == fid and ct["status"] == "ACTIVE":
                ct["status"] = "INACTIVE"
                touch(ct)
        for cg in db.consents.values():
            if cg["family_id"] == fid and cg["status"] in ("PENDING_SIGNATURE", "ACTIVE"):
                cg["status"] = "REVOKED"
                touch(cg)
        # Seal SHARED notes of this family's clients.
        for n in db.notes.values():
            owner = db.clients.get(n["client_id"])
            if owner is not None and owner["family_id"] == fid and n["status"] in ("SHARED", "FINALIZED"):
                n["status"] = "SEALED"
                touch(n)
        fam["status"] = "CLOSED"
        touch(fam)

    return success_object(family_pub(fam), 200)


@bp.post("/families/<fid>/payments")
def record_payment(fid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    require_family_scope(auth, fid)
    fam = get_entity("family", fid)
    if fam["status"] == "CLOSED":
        E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is CLOSED")
    body = get_body()
    require_fields(body, ["amount_cents"])
    mw.int_check(body["amount_cents"], "amount_cents", minimum=1)
    fam["total_paid_cents"] += body["amount_cents"]
    billing.recompute_family_billing(fam)
    touch(fam)
    return success_object(family_pub(fam), 201)
