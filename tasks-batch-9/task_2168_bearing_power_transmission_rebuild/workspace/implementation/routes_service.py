"""Installations and warranty claims."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import ledger
import store
import validate as v
import views
from auth import (ALL_ROLES, CLAIM_ACTIONS, INSTALLATION_ACTIONS, authenticate,
                  require_action_role, require_roles)
from errors import fail
from response import created, listing, ok

bp = Blueprint("service", __name__)

INSTALLATION_ADVANCE = {"RECORD_HOURS", "FAIL", "REMOVE"}
CLAIM_ADVANCE = {"REVIEW", "REQUEST_INFO", "RESUBMIT", "ISSUE_CREDIT"}
DECISIONS = {"APPROVE", "DENY"}

OPEN_CLAIM_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED")


def path_installation(iid):
    rec = store.get("installations", iid)
    if rec is None:
        fail("ERR_INSTALLATION_NOT_FOUND", "Installation %s not found" % iid)
    return rec


def path_claim(cid):
    rec = store.get("claims", cid)
    if rec is None:
        fail("ERR_CLAIM_NOT_FOUND", "Warranty claim %s not found" % cid)
    return rec


# ---------------------------------------------------------------------------
# installations
# ---------------------------------------------------------------------------
@bp.post("/shop/installations")
def create_installation():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    core_id = v.req_fk(body, "core_unit_id")
    asset_id = v.req_fk(body, "customer_asset_id")
    order_id = v.req_fk(body, "rebuild_order_id")
    expected = v.req_int(body, "expected_asset_version")

    core = store.get("core_units", core_id)
    if core is None:
        fail("ERR_CORE_UNIT_NOT_FOUND", "Core unit %s not found" % core_id)
    asset = store.get("assets", asset_id)
    if asset is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s not found" % asset_id)
    order = store.get("orders", order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "Rebuild order %s not found" % order_id)

    if expected != asset["version"]:
        fail("ERR_STALE_VERSION", "expected_asset_version does not match")

    if core["status"] == "SCRAPPED" or core.get("condition_grade") == "SCRAP":
        fail("ERR_CORE_SCRAPPED", "the core is scrap")
    if (core["status"] != "SHIPPED"
            or order["work_status"] != "DELIVERED"
            or order["core_unit_id"] != core_id
            or order["customer_asset_id"] != asset_id):
        fail("ERR_UNIT_NOT_DELIVERED", "the rebuilt unit has not been delivered")

    now = store.logical_now()
    last_off = calc.last_off_service(asset_id)
    if last_off is not None:
        if now < last_off + timedelta(hours=calc.CHANGEOVER_BUFFER_HOURS):
            fail("ERR_INSTALL_BUFFER_VIOLATION", "the 24-hour changeover buffer has not elapsed")

    for existing in calc.installations_of_asset(asset_id):
        if existing["status"] in ("INSTALLED", "RUNNING"):
            fail("ERR_ASSET_OCCUPIED", "the asset already carries a live unit")

    standard = store.get("standards", core["clearance_standard_id"])
    rec = store.base_record()
    rec.update({
        "core_unit_id": core_id,
        "customer_asset_id": asset_id,
        "rebuild_order_id": order_id,
        "in_service_start_at": store.logical_now_iso(),
        "run_hours": Decimal(0),
        "status": "INSTALLED",
        "removed_at": None,
        "failed_at": None,
        "warranty_hours_snapshot": standard["warranty_hours"] if standard else None,
        "warranty_months_snapshot": standard["warranty_months"] if standard else None,
        "covered_base_cents_snapshot": order.get("covered_base_cents"),
    })
    store.insert("installations", rec)
    store.touch(asset)
    return created(views.render("installations", rec))


@bp.get("/shop/installations/<iid>")
def read_installation(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = path_installation(iid)
    views.require_owner(role, uid, "installations", rec)
    return ok(views.render("installations", rec))


@bp.get("/shop/installations")
def list_installations():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = v.pagination()
    rows = store.all_rows("installations")
    for key in ("core_unit_id", "customer_asset_id", "rebuild_order_id", "status"):
        value = v.qparam(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows = views.scope_rows(role, uid, "installations", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("installations", page), limit, offset, total)


@bp.post("/shop/installations/<iid>/advance")
def advance_installation(iid):
    uid, role = authenticate()
    require_roles(role, ["ShopAdmin", "Customer"])
    raw = v.body()
    require_action_role(role, raw.get("action"), INSTALLATION_ACTIONS)
    inst = path_installation(iid)
    action = v.req_enum(raw, "action", INSTALLATION_ADVANCE)
    delta = None
    if action == "RECORD_HOURS":
        delta = v.req_num(raw, "run_hours_delta", exclusive_min=0)
    else:
        delta = v.opt_num(raw, "run_hours_delta", None, exclusive_min=0)

    views.require_owner(role, uid, "installations", inst)

    if action == "RECORD_HOURS":
        if inst["status"] not in ("INSTALLED", "RUNNING"):
            fail("ERR_INSTALLATION_INVALID_STATE", "installation is terminal")
        inst["run_hours"] = Decimal(inst["run_hours"]) + delta
        inst["status"] = "RUNNING"
    elif action == "FAIL":
        if inst["status"] not in ("INSTALLED", "RUNNING"):
            fail("ERR_INSTALLATION_INVALID_STATE", "installation is terminal")
        inst["status"] = "FAILED_IN_SERVICE"
        inst["failed_at"] = store.logical_now_iso()
    else:
        if inst["status"] not in ("INSTALLED", "RUNNING"):
            fail("ERR_INSTALLATION_INVALID_STATE", "installation is terminal")
        inst["status"] = "REMOVED_PLANNED"
        inst["removed_at"] = store.logical_now_iso()
    store.touch(inst)
    return ok(views.render("installations", inst))


# ---------------------------------------------------------------------------
# warranty claims
# ---------------------------------------------------------------------------
@bp.post("/shop/warranty-claims")
def create_claim():
    uid, role = authenticate()
    require_roles(role, ["Customer", "ShopAdmin"])
    body = v.body()
    installation_id = v.req_fk(body, "installation_id")
    claimed_reason = v.req_str(body, "claimed_reason")

    inst = store.get("installations", installation_id)
    if inst is None:
        fail("ERR_INSTALLATION_NOT_FOUND", "Installation %s not found" % installation_id)

    views.require_owner(role, uid, "installations", inst)

    if inst["status"] != "FAILED_IN_SERVICE":
        fail("ERR_WARRANTY_NOT_ELIGIBLE", "the unit has not failed in service")

    elapsed_days = calc.elapsed_days_of(inst)
    hours_limit = int(inst["warranty_hours_snapshot"])
    months_limit = int(inst["warranty_months_snapshot"]) * calc.DAYS_PER_WARRANTY_MONTH
    if not (Decimal(inst["run_hours"]) < Decimal(hours_limit) and elapsed_days < months_limit):
        fail("ERR_WARRANTY_EXPIRED", "the warranty has expired")

    for sibling in store.all_rows("claims"):
        if sibling["installation_id"] == installation_id and sibling["status"] in OPEN_CLAIM_STATES:
            fail("ERR_DUPLICATE_CLAIM", "an open claim already exists on this installation")

    working = calc.warranty_pro_rata(inst)
    rec = store.base_record()
    rec.update({
        "installation_id": installation_id,
        "claimed_reason": claimed_reason,
        "status": "SUBMITTED",
        "submitted_at": store.logical_now_iso(),
        "adjudication_note": None,
        "adjudicated_by_user_id": None,
        "info_note": None,
    })
    rec.update(working)
    store.insert("claims", rec)
    return created(views.render("claims", rec))


@bp.get("/shop/installations/<iid>/warranty-claims")
def list_installation_claims(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    inst = path_installation(iid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "installations", inst)
    rows = [c for c in store.all_rows("claims") if c["installation_id"] == inst["id"]]
    status = v.qparam("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("claims", page), limit, offset, total)


@bp.get("/shop/warranty-claims/<cid>")
def read_claim(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = path_claim(cid)
    views.require_owner(role, uid, "claims", rec)
    return ok(views.render("claims", rec))


@bp.post("/shop/warranty-claims/<cid>/advance")
def advance_claim(cid):
    uid, role = authenticate()
    require_roles(role, ["ShopAdmin", "Customer"])
    raw = v.body()
    require_action_role(role, raw.get("action"), CLAIM_ACTIONS)
    claim = path_claim(cid)
    action = v.req_enum(raw, "action", CLAIM_ADVANCE)
    info_note = v.opt_str(raw, "info_note", None)

    views.require_owner(role, uid, "claims", claim)

    if action == "REVIEW":
        if claim["status"] != "SUBMITTED":
            fail("ERR_CLAIM_INVALID_STATE", "claim is not SUBMITTED")
        claim["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_INFO":
        if claim["status"] != "UNDER_REVIEW":
            fail("ERR_CLAIM_INVALID_STATE", "claim is not UNDER_REVIEW")
        claim["status"] = "INFO_REQUESTED"
        claim["info_note"] = info_note
    elif action == "RESUBMIT":
        if claim["status"] != "INFO_REQUESTED":
            fail("ERR_CLAIM_INVALID_STATE", "claim is not INFO_REQUESTED")
        claim["status"] = "UNDER_REVIEW"
        claim["info_note"] = info_note
    else:
        if claim["status"] != "APPROVED":
            fail("ERR_CLAIM_INVALID_STATE", "claim is not APPROVED")
        claim["status"] = "CREDITED"
        store.touch(claim)
        _issue_credit(claim)
        return ok(views.render("claims", claim))

    store.touch(claim)
    return ok(views.render("claims", claim))


def _issue_credit(claim):
    inst = store.get("installations", claim["installation_id"])
    order = store.get("orders", inst["rebuild_order_id"]) if inst else None
    if order is None:
        return
    customer = store.get("customers", order["customer_id"])
    ledger.post_note(
        order["customer_id"], "WARRANTY_PRORATA", claim["pro_rata_credit_cents"],
        warranty_claim_id=claim["id"], memo="warranty pro-rata credit",
    )
    ledger.settle(customer, reprice=False)


@bp.post("/shop/warranty-claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    uid, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    claim = path_claim(cid)
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    note = v.opt_str(body, "adjudication_note", None)

    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_INVALID_STATE", "claim is not UNDER_REVIEW")

    inst = store.get("installations", claim["installation_id"])
    inspection = calc.accepted_inspection_of_order(inst["rebuild_order_id"]) if inst else None
    if inspection is not None and inspection.get("accepted_by_user_id") == uid:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the inspection acceptor may not adjudicate this claim")

    claim["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    claim["adjudicated_by_user_id"] = uid
    claim["adjudication_note"] = note
    store.touch(claim)
    return ok(views.render("claims", claim))
