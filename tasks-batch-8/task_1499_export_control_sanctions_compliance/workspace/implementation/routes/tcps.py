"""Technology control plan endpoints with enclave overlap rules and
termination cascade to access grants."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CLASSIFICATION_REQUIRED,
    ERR_INVALID_STATE,
    ERR_TCP_PERIOD_OVERLAP,
    ERR_VALIDATION,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_enum,
    v_date,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response

bp = Blueprint("tcps", __name__)

LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3")


def _closed_overlap(a_from, a_to, b_from, b_to):
    """Closed-interval overlap: a shared endpoint date counts as overlap."""
    return a_from <= b_to and b_from <= a_to


@bp.post("/compliance/tcps")
def create_tcp():
    auth("ComplianceAnalyst")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("product_id", db.PRODUCTS),))
    # Priority 4: request shape
    no_unknown(body, {"name", "enclave_id", "product_id", "segregation_level", "effective_from", "effective_to"})
    name = v_str(need(body, "name"), "name")
    enclave_id = v_str(need(body, "enclave_id"), "enclave_id")
    product_id = v_str(need(body, "product_id"), "product_id")
    level = v_enum(need(body, "segregation_level"), "segregation_level", LEVELS)
    eff_from = v_date(need(body, "effective_from"), "effective_from")
    eff_to = v_date(need(body, "effective_to"), "effective_to")
    if eff_from > eff_to:
        raise ApiError(ERR_VALIDATION, "effective_from must not be after effective_to", 400)
    find(db.PRODUCTS, product_id, "Product")
    tcp = {
        "name": name,
        "enclave_id": enclave_id,
        "product_id": product_id,
        "segregation_level": level,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
    }
    db.stamp_new(tcp)
    db.TCPS[tcp["id"]] = tcp
    return ok(db.pub(tcp), "object", 201)


@bp.get("/compliance/tcps/<tid>")
def get_tcp(tid):
    auth()
    tcp = find(db.TCPS, tid, "TechnologyControlPlan")
    return ok(db.pub(tcp), "object", 200)


@bp.get("/compliance/tcps")
def list_tcps():
    auth()
    filters = {
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
        "enclave_id": request.args.get("enclave_id"),
    }
    items = filtered_sorted(db.TCPS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/tcps/<tid>/set-status")
def set_tcp_status(tid):
    auth("ComplianceAnalyst")
    tcp = find(db.TCPS, tid, "TechnologyControlPlan")
    body = get_body()
    no_unknown(body, {"to"})
    to = v_enum(need(body, "to"), "to", ("ACTIVE", "SUSPENDED", "TERMINATED"))
    if to == "ACTIVE":
        if tcp["status"] not in ("DRAFT", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, "TCP cannot be activated from %s" % tcp["status"], 409)
        for other in db.TCPS.values():
            if (
                other["id"] != tcp["id"]
                and other["enclave_id"] == tcp["enclave_id"]
                and other["status"] in ("ACTIVE", "SUSPENDED")
                and _closed_overlap(
                    tcp["effective_from"], tcp["effective_to"],
                    other["effective_from"], other["effective_to"],
                )
            ):
                raise ApiError(
                    ERR_TCP_PERIOD_OVERLAP,
                    "Another ACTIVE|SUSPENDED TCP overlaps on enclave %s" % tcp["enclave_id"],
                    409,
                )
        if tcp["status"] == "DRAFT":
            product = find(db.PRODUCTS, tcp["product_id"], "Product")
            if product["status"] != "CLASSIFIED":
                raise ApiError(
                    ERR_CLASSIFICATION_REQUIRED,
                    "Product %s has no ACTIVE classification" % product["id"],
                    409,
                )
        tcp["status"] = "ACTIVE"
        db.touch(tcp)
    elif to == "SUSPENDED":
        if tcp["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "TCP is not ACTIVE", 409)
        tcp["status"] = "SUSPENDED"
        db.touch(tcp)
    else:  # TERMINATED
        if tcp["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, "TCP cannot be terminated from %s" % tcp["status"], 409)
        tcp["status"] = "TERMINATED"
        db.touch(tcp)
        # Cascade: REQUESTED grants -> DENIED; APPROVED|ACTIVE -> REVOKED;
        # each ACTIVE grant decrements its party's active_grant_count.
        for grant in db.GRANTS.values():
            if grant["tcp_id"] != tcp["id"]:
                continue
            if grant["status"] == "REQUESTED":
                grant["status"] = "DENIED"
                db.touch(grant)
            elif grant["status"] in ("APPROVED", "ACTIVE"):
                was_active = grant["status"] == "ACTIVE"
                grant["status"] = "REVOKED"
                db.touch(grant)
                if was_active:
                    party = db.PARTIES.get(grant["party_id"])
                    if party is not None:
                        party["active_grant_count"] -= 1
                        db.touch(party)
    return ok(db.pub(tcp), "object", 200)
