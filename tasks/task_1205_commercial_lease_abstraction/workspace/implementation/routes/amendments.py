"""Amendment endpoints."""

from flask import Blueprint

from db import db, new_resource, touch
from errors import err
from response import success_object
from services import calc
from services.validate import (
    body, req_int, req_enum, req_date, opt_int, opt_string, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("amendments", __name__)

AMENDMENT_KINDS = {
    "EXTENSION", "CONTRACTION", "EXPANSION",
    "ASSIGNMENT", "RENT_CHANGE", "USE_CHANGE",
}


@bp.post("/lease-admin/leases/<lease_id>/amendments")
def create_amendment(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    kind = req_enum(data, "kind", AMENDMENT_KINDS)
    effective_date = req_date(data, "effective_date")

    # Kind-specific payload requirements (pipeline step 4).
    new_expiration_date = None
    new_leased_sf = None
    new_base_rent_annual_cents = None
    new_tenant_legal_name = None
    if kind == "EXTENSION":
        new_expiration_date = req_date(data, "new_expiration_date")
    else:
        if data.get("new_expiration_date") is not None:
            err("ERR_INVALID_REQUEST",
                "new_expiration_date is only allowed for kind=EXTENSION")
    if kind in ("EXPANSION", "CONTRACTION"):
        new_leased_sf = req_int(data, "new_leased_sf", min_v=1)
    else:
        if data.get("new_leased_sf") is not None:
            err("ERR_INVALID_REQUEST",
                "new_leased_sf is only allowed for EXPANSION or CONTRACTION")
    if kind == "RENT_CHANGE":
        new_base_rent_annual_cents = req_int(
            data, "new_base_rent_annual_cents", min_v=0)
    else:
        if data.get("new_base_rent_annual_cents") is not None:
            err("ERR_INVALID_REQUEST",
                "new_base_rent_annual_cents is only allowed for RENT_CHANGE")
    if kind == "ASSIGNMENT":
        from services.validate import req_string
        new_tenant_legal_name = req_string(data, "new_tenant_legal_name")
    else:
        if data.get("new_tenant_legal_name") is not None:
            err("ERR_INVALID_REQUEST",
                "new_tenant_legal_name is only allowed for ASSIGNMENT")

    # Temporal well-formedness (pipeline step 5): effective_date must not
    # precede the lease's commencement_date.
    if calc.d(effective_date) < calc.d(lease["commencement_date"]):
        err("ERR_INVALID_DATE_RANGE",
            "effective_date must not precede the lease's commencement_date")

    aid, common = new_resource()
    amendment = {
        **common,
        "lease_id": lease_id,
        "kind": kind,
        "effective_date": effective_date,
        "new_expiration_date": new_expiration_date,
        "new_leased_sf": new_leased_sf,
        "new_base_rent_annual_cents": new_base_rent_annual_cents,
        "new_tenant_legal_name": new_tenant_legal_name,
        "status": "PROPOSED",
    }
    db["amendments"][aid] = amendment
    return success_object(amendment, status=201)


@bp.get("/lease-admin/leases/<lease_id>/amendments")
def list_lease_amendments(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [a for a in db["amendments"].values() if a["lease_id"] == lease_id],
        filters=[
            (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/amendments/<amendment_id>")
def get_amendment(amendment_id):
    return success_object(
        get_child_or_404("amendments", amendment_id, "Amendment"))


@bp.get("/lease-admin/amendments")
def list_amendments_filtered():
    return list_response(db["amendments"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/amendments/<amendment_id>/approve")
def approve_amendment(amendment_id):
    amendment = get_child_or_404("amendments", amendment_id, "Amendment")
    data = body()
    expected = req_int(data, "expected_lease_version", min_v=0)
    if amendment["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", "Approve requires status == PROPOSED")
    lease = db["leases"][amendment["lease_id"]]
    if lease["status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE",
            "Amendment approval requires Lease.status == ACTIVE")
    # OCC precondition (pipeline step 14).
    if expected != lease["version"]:
        err("ERR_STALE_VERSION",
            "expected_lease_version does not match the lease's current version")
    amendment["status"] = "APPROVED"
    touch(amendment)
    touch(lease)
    return success_object(amendment)


@bp.post("/lease-admin/amendments/<amendment_id>/apply")
def apply_amendment(amendment_id):
    amendment = get_child_or_404("amendments", amendment_id, "Amendment")
    if amendment["status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Apply requires status == APPROVED")
    lease = db["leases"][amendment["lease_id"]]
    prop = db["properties"][lease["property_id"]]
    kind = amendment["kind"]

    # Per-kind directional validation.
    if kind == "EXTENSION":
        if calc.d(amendment["new_expiration_date"]) <= \
           calc.d(lease["expiration_date"]):
            err("ERR_EXTENSION_MUST_EXTEND",
                "EXTENSION must set new_expiration_date after the current expiration")
    elif kind == "EXPANSION":
        if amendment["new_leased_sf"] <= lease["leased_sf"]:
            err("ERR_EXPANSION_MUST_EXPAND",
                "EXPANSION must set new_leased_sf above the current leased_sf")
        # Aggregate-capacity guard (pipeline step 11).
        others = sum(
            l["leased_sf"] for l in db["leases"].values()
            if l["property_id"] == lease["property_id"]
            and l["id"] != lease["id"] and l["status"] == "ACTIVE")
        if amendment["new_leased_sf"] + others > prop["total_rentable_sf"]:
            err("ERR_PROPERTY_OVERCOMMITTED",
                "EXPANSION would overcommit the property's rentable square footage")
    elif kind == "CONTRACTION":
        if amendment["new_leased_sf"] >= lease["leased_sf"]:
            err("ERR_CONTRACTION_MUST_CONTRACT",
                "CONTRACTION must set new_leased_sf below the current leased_sf")

    old_expiration = lease["expiration_date"]

    # Apply the field rewrite per kind.
    if kind == "EXTENSION":
        lease["expiration_date"] = amendment["new_expiration_date"]
    elif kind in ("EXPANSION", "CONTRACTION"):
        lease["leased_sf"] = amendment["new_leased_sf"]
    elif kind == "RENT_CHANGE":
        lease["base_rent_annual_cents"] = \
            amendment["new_base_rent_annual_cents"]
    elif kind == "ASSIGNMENT":
        lease["tenant_legal_name"] = amendment["new_tenant_legal_name"]
    amendment["status"] = "APPLIED"
    touch(amendment)

    # Cascade: EXTENSION retires the old EXPIRATION date and creates the new.
    if kind == "EXTENSION":
        for cd in db["critical_dates"].values():
            if cd["lease_id"] == lease["id"] and \
               cd["kind"] == "EXPIRATION" and \
               cd["status"] == "PENDING" and \
               cd["due_date"] == old_expiration:
                cd["status"] = "WAIVED"
                touch(cd)
        nid, common = new_resource()
        db["critical_dates"][nid] = {
            **common,
            "lease_id": lease["id"],
            "kind": "EXPIRATION",
            "due_date": amendment["new_expiration_date"],
            "advance_notice_days": 0,
            "status": "PENDING",
            "linked_amendment_id": None,
        }

    # Cascade: RENT_CHANGE recomputes schedule lines starting on/after the
    # effective date against the new annual base rent.
    if kind == "RENT_CHANGE":
        eff = calc.d(amendment["effective_date"])
        for line in db["rent_schedule_lines"].values():
            if line["lease_id"] == lease["id"] and \
               calc.d(line["period_start"]) >= eff:
                step = None
                if line["escalation_step_id"]:
                    step = db["escalation_steps"].get(
                        line["escalation_step_id"])
                line["base_rent_cents"] = \
                    amendment["new_base_rent_annual_cents"]
                line["effective_rent_cents"] = \
                    calc.escalated_rent_for_period(line, step)
                touch(line)
    # The apply itself is a single Lease mutation: one version increment.
    calc.recompute_cached_annual_rent(lease)
    touch(lease)
    return success_object(amendment)


@bp.post("/lease-admin/amendments/<amendment_id>/reject")
def reject_amendment(amendment_id):
    amendment = get_child_or_404("amendments", amendment_id, "Amendment")
    if amendment["status"] not in ("PROPOSED", "APPROVED"):
        err("ERR_INVALID_STATE",
            "Reject requires status PROPOSED or APPROVED")
    amendment["status"] = "REJECTED"
    touch(amendment)
    return success_object(amendment)
