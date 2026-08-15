"""Contract lifecycle + nested practice items, advance payments, modifications."""
from datetime import timedelta

from flask import Blueprint

import serializers
from db import STORE, new_id, now
from errors import ApiError
from helpers import (
    apply_filters, as_dt, as_enum, as_int, body, get_applicant,
    get_application, get_contract, get_item, paginate, req_field, sorted_created,
    stamp_new, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list
from routes.programs import PRACTICE_CODES
from services import calc, ledger
from util import dec, is_num

bp = Blueprint("contracts", __name__)

MOD_KINDS = {"EXTEND_DEADLINE", "ADD_PRACTICE", "DROP_PRACTICE"}
CANCELLABLE = ("PLANNED", "INSTALLED", "CERTIFICATION_FAILED")
TERMINAL_CERT = ("CANCELLED", "EXPIRED", "CERTIFICATION_REVOKED")


def _make_item(contract, practice_code, planned_quantity, deadline, applicant_row, program):
    """Resolve the rate, snapshot the applicable rate, compute the scheduled
    amount. Shared by draft item creation and ADD_PRACTICE approval."""
    rate_row = calc.rate_for_code(contract["program_id"], practice_code)
    if rate_row is None:
        raise ApiError(
            "ERR_RATE_NOT_FOUND", 422,
            f"No payment schedule rate for {practice_code} in this program",
        )
    applicable = calc.applicable_rate_cents(rate_row, applicant_row)
    scheduled = calc.scheduled_amount_cents(planned_quantity, applicable)
    item = {
        "id": new_id(),
        "contract_id": contract["id"],
        "payment_schedule_rate_id": rate_row["id"],
        "practice_code": practice_code,
        "planned_quantity": planned_quantity,
        "unit": rate_row["unit"],
        "applicable_rate_cents": applicable,
        "scheduled_amount_cents": scheduled,
        "implementation_deadline": deadline,
        "certification_status": "PLANNED",
        "certified_quantity": None,
        "certified_by_user_id": None,
        "certified_at": None,
        "payment_status": "UNPAID",
        "paid_amount_cents": 0,
        "_held_cents": scheduled,
        "_rate_id": rate_row["id"],
    }
    stamp_new(item)
    STORE.items[item["id"]] = item
    return item


# ---------------- Contract CRUD ----------------

@bp.post("/eqip/contracts")
@require_roles("ConservationPlanner")
def create_contract(_uid, _role):
    data = body()
    application_id = req_field(data, "application_id")
    app = get_application(application_id)
    if app["status"] != "SELECTED":
        raise ApiError(
            "ERR_APPLICATION_NOT_SELECTED", 409,
            "contract creation requires a SELECTED application",
        )
    c = {
        "id": new_id(),
        "program_id": app["program_id"],
        "application_id": app["id"],
        "applicant_id": app["applicant_id"],
        "pool_id": app["funded_pool_id"],
        "obligated_amount_cents": 0,
        "paid_amount_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(c)
    STORE.contracts[c["id"]] = c
    app["status"] = "CONTRACTED"
    touch(app)
    return ok(serializers.contract(c), 201)


@bp.get("/eqip/contracts/<cid>")
@require_roles(*ANY_ROLE)
def get_one_contract(cid, _uid, _role):
    return ok(serializers.contract(get_contract(cid)))


@bp.get("/eqip/contracts")
@require_roles(*ANY_ROLE)
def list_contracts(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.contracts.values()),
        [("program_id", "program_id"), ("application_id", "application_id"),
         ("applicant_id", "applicant_id"), ("pool_id", "pool_id"),
         ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.contract(c) for c in page], meta)


# ---------------- Practice items (nested creation/list) ----------------

@bp.post("/eqip/contracts/<cid>/practice-items")
@require_roles("ConservationPlanner")
def add_practice_item(cid, _uid, _role):
    contract = get_contract(cid)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", 409, "adding items requires contract DRAFT")
    data = body()
    practice_code = as_enum(req_field(data, "practice_code"), "practice_code", PRACTICE_CODES)
    qty = req_field(data, "planned_quantity")
    if not is_num(qty) or dec(qty) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "planned_quantity must be a number > 0")
    deadline = as_dt(req_field(data, "implementation_deadline"), "implementation_deadline")

    app = get_application(contract["application_id"])
    planned = {p["practice_code"]: p["quantity"] for p in app["planned_practices"]}
    if practice_code not in planned:
        raise ApiError(
            "ERR_PRACTICE_NOT_IN_APPLICATION", 422,
            "practice_code does not appear in the source application's planned_practices",
        )
    if dec(qty) > dec(planned[practice_code]):
        raise ApiError(
            "ERR_QUANTITY_EXCEEDS_APPLICATION", 422,
            "planned_quantity exceeds the quantity planned in the application",
        )
    applicant_row = get_applicant(contract["applicant_id"])
    program = STORE.programs[contract["program_id"]]
    item = _make_item(contract, practice_code, qty, deadline, applicant_row, program)
    calc.recompute_contract_obligated(contract)
    touch(contract)
    return ok(serializers.item(item), 201)


@bp.get("/eqip/contracts/<cid>/practice-items")
@require_roles(*ANY_ROLE)
def list_contract_items(cid, _uid, _role):
    get_contract(cid)
    items = [i for i in sorted_created(STORE.items.values()) if i["contract_id"] == cid]
    page, meta = paginate(items)
    return ok_list([serializers.item(i) for i in page], meta)


# ---------------- Obligation / endings ----------------

@bp.post("/eqip/contracts/<cid>/obligate")
@require_roles("ProgramAdmin")
def obligate_contract(cid, _uid, _role):
    contract = get_contract(cid)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", 409, "obligate requires contract DRAFT")
    contract_items = [i for i in STORE.items.values() if i["contract_id"] == cid]
    if len(contract_items) == 0:
        raise ApiError("ERR_CONTRACT_EMPTY", 409, "obligate requires at least one practice item")
    calc.recompute_contract_obligated(contract)
    pool = STORE.pools[contract["pool_id"]]
    if contract["obligated_amount_cents"] > ledger.pool_available(pool):
        raise ApiError(
            "ERR_POOL_INSUFFICIENT_FUNDS", 402,
            "obligated amount exceeds the pool's available balance",
        )
    pool["obligated_cents"] += contract["obligated_amount_cents"]
    touch(pool)
    app = STORE.applications.get(contract["application_id"])
    if app is not None and app["status"] == "CONTRACTED":
        app["status"] = "OBLIGATED"
        touch(app)
    contract["status"] = "OBLIGATED"
    touch(contract)
    return ok(serializers.contract(contract))


@bp.post("/eqip/contracts/<cid>/terminate")
@require_roles("ProgramAdmin")
def terminate_contract(cid, _uid, _role):
    contract = get_contract(cid)
    if contract["status"] not in ("DRAFT", "OBLIGATED"):
        raise ApiError(
            "ERR_CONTRACT_NOT_OBLIGATED", 409,
            "terminate requires contract DRAFT or OBLIGATED (frozen under modification review)",
        )
    if contract["status"] == "OBLIGATED":
        for r in STORE.payment_requests.values():
            if r["contract_id"] == cid and r["status"] == "DISBURSED":
                raise ApiError(
                    "ERR_DISBURSED_PAYMENTS_EXIST", 409,
                    "terminate is blocked while a payment request is DISBURSED",
                )
        pool = STORE.pools.get(contract["pool_id"])
        for item in [i for i in STORE.items.values() if i["contract_id"] == cid]:
            if item["certification_status"] in CANCELLABLE:
                ledger.cancel_item(item, pool, release=True)
        for adv in [a for a in STORE.advances.values() if a["contract_id"] == cid]:
            if adv["outstanding_cents"] > 0:
                ledger.force_advance_return_due(adv)
        for r in [x for x in STORE.payment_requests.values() if x["contract_id"] == cid]:
            if r["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
                r["status"] = "REJECTED"
                touch(r)
        for m in [x for x in STORE.modifications.values() if x["contract_id"] == cid]:
            if m["status"] == "REQUESTED":
                m["status"] = "REJECTED"
                touch(m)
        calc.recompute_contract_obligated(contract)
    else:
        # DRAFT termination: cancel items, touch no pool funds.
        for item in [i for i in STORE.items.values() if i["contract_id"] == cid]:
            if item["certification_status"] not in TERMINAL_CERT:
                item["certification_status"] = "CANCELLED"
                touch(item)
        calc.recompute_contract_obligated(contract)
    contract["status"] = "TERMINATED"
    touch(contract)
    return ok(serializers.contract(contract))


@bp.post("/eqip/contracts/<cid>/complete")
@require_roles("ProgramAdmin")
def complete_contract(cid, _uid, _role):
    contract = get_contract(cid)
    if contract["status"] != "OBLIGATED":
        raise ApiError("ERR_CONTRACT_NOT_OBLIGATED", 409, "complete requires contract OBLIGATED")
    contract_items = [i for i in STORE.items.values() if i["contract_id"] == cid]
    for i in contract_items:
        cert_ok = (
            (i["certification_status"] == "CERTIFIED"
             and i["payment_status"] in ("PAID", "RECOUPED"))
            or i["certification_status"] in ("CANCELLED", "EXPIRED")
        )
        if not cert_ok:
            raise ApiError(
                "ERR_ITEMS_NOT_FINAL", 409,
                "every item must be CERTIFIED+PAID/RECOUPED, CANCELLED or EXPIRED",
            )
    for adv in STORE.advances.values():
        if adv["contract_id"] == cid and adv["status"] in ("ISSUED", "RETURN_DUE", "ESCALATED"):
            raise ApiError(
                "ERR_ADVANCE_OUTSTANDING", 409,
                "an advance on this contract is still outstanding",
            )
    for r in STORE.payment_requests.values():
        if r["contract_id"] == cid and r["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            raise ApiError(
                "ERR_PAYMENT_REQUEST_ACTIVE", 409,
                "a payment request on this contract is still active",
            )
    for m in STORE.modifications.values():
        if m["contract_id"] == cid and m["status"] == "REQUESTED":
            raise ApiError(
                "ERR_PENDING_MODIFICATION_EXISTS", 409,
                "a REQUESTED modification exists on this contract",
            )
    pool = STORE.pools.get(contract["pool_id"])
    if pool is not None:
        residual = sum(i.get("_held_cents", 0) for i in contract_items)
        if residual:
            pool["obligated_cents"] -= residual
            touch(pool)
            for i in contract_items:
                i["_held_cents"] = 0
    contract["status"] = "COMPLETED"
    touch(contract)
    return ok(serializers.contract(contract))


# ---------------- Advance payments (nested) ----------------

@bp.post("/eqip/contracts/<cid>/advance-payments")
@require_roles("PaymentOfficer")
def issue_advance(cid, _uid, _role):
    contract = get_contract(cid)
    data = body()
    item_id = req_field(data, "practice_item_id")
    item = get_item(item_id)
    if item["contract_id"] != cid:
        raise ApiError(
            "ERR_PRACTICE_ITEM_NOT_FOUND", 404,
            "practice item does not belong to this contract",
        )
    # Gates in the order given by PRD 3.6.
    if contract["status"] != "OBLIGATED":
        raise ApiError("ERR_CONTRACT_NOT_OBLIGATED", 409, "advance issuance requires contract OBLIGATED")
    if item["certification_status"] != "PLANNED":
        raise ApiError("ERR_ITEM_NOT_PLANNED", 409, "advance issuance requires item PLANNED")
    applicant_row = get_applicant(contract["applicant_id"])
    if not applicant_row["historically_underserved"]:
        raise ApiError(
            "ERR_NOT_HISTORICALLY_UNDERSERVED", 422,
            "advance payment requires a historically underserved applicant",
        )
    if ledger.advance_for_item(item["id"]) is not None:
        raise ApiError(
            "ERR_ADVANCE_ALREADY_ISSUED", 409,
            "the practice item already has an advance",
        )
    for adv in STORE.advances.values():
        if adv["contract_id"] == cid and adv["outstanding_cents"] > 0:
            raise ApiError(
                "ERR_ADVANCE_OUTSTANDING", 409,
                "another advance on this contract still has money outstanding",
            )
    issued = req_field(data, "issued_cents")
    issued = as_int(issued, "issued_cents")
    if issued < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "issued_cents must be >= 1")
    program = STORE.programs[contract["program_id"]]
    cap = calc.advance_cap_cents(program, item)
    if issued > cap:
        raise ApiError(
            "ERR_ADVANCE_CAP_EXCEEDED", 422,
            "issued_cents exceeds the program advance cap for this item",
        )
    pool = STORE.pools[contract["pool_id"]]
    pool["obligated_cents"] -= issued
    pool["paid_cents"] += issued
    touch(pool)
    item["_held_cents"] = item.get("_held_cents", item["scheduled_amount_cents"]) - issued
    item["payment_status"] = "ADVANCE_HELD"
    touch(item)
    adv = {
        "id": new_id(),
        "contract_id": cid,
        "applicant_id": contract["applicant_id"],
        "practice_item_id": item["id"],
        "issued_cents": issued,
        "issued_at": now(),
        "expenditure_due_date": now() + timedelta(days=90),
        "applied_cents": 0,
        "returned_cents": 0,
        "outstanding_cents": issued,
        "status": "ISSUED",
    }
    stamp_new(adv)
    STORE.advances[adv["id"]] = adv
    return ok(serializers.advance(adv), 201)


@bp.get("/eqip/contracts/<cid>/advance-payments")
@require_roles(*ANY_ROLE)
def list_contract_advances(cid, _uid, _role):
    get_contract(cid)
    items = [a for a in sorted_created(STORE.advances.values()) if a["contract_id"] == cid]
    page, meta = paginate(items)
    return ok_list([serializers.advance(a) for a in page], meta)


# ---------------- Contract modifications (nested) ----------------

@bp.post("/eqip/contracts/<cid>/modifications")
@require_roles("Applicant")
def request_modification(cid, _uid, _role):
    contract = get_contract(cid)
    check_owner(contract["applicant_id"], _uid)
    if contract["status"] != "OBLIGATED":
        raise ApiError(
            "ERR_CONTRACT_NOT_OBLIGATED", 409,
            "modification request requires contract OBLIGATED",
        )
    data = body()
    kind = as_enum(req_field(data, "kind"), "kind", MOD_KINDS)

    item = None
    new_deadline = None
    new_code = None
    new_qty = None
    if kind in ("EXTEND_DEADLINE", "DROP_PRACTICE"):
        item_id = req_field(data, "practice_item_id")
        item = get_item(item_id)
        if item["contract_id"] != cid:
            raise ApiError(
                "ERR_PRACTICE_ITEM_NOT_FOUND", 404,
                "practice item does not belong to this contract",
            )
    if kind in ("EXTEND_DEADLINE", "ADD_PRACTICE"):
        new_deadline = as_dt(req_field(data, "new_deadline"), "new_deadline")
    if kind == "ADD_PRACTICE":
        new_code = as_enum(req_field(data, "new_practice_code"), "new_practice_code", PRACTICE_CODES)
        new_qty = req_field(data, "new_quantity")
        if not is_num(new_qty) or dec(new_qty) <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "new_quantity must be a number > 0")
    if kind == "EXTEND_DEADLINE":
        # Request-time validation: item extendable + deadline bounds. The
        # clock-based window check is deferred to approve time.
        if item["certification_status"] not in CANCELLABLE:
            raise ApiError(
                "ERR_ITEM_NOT_EXTENDABLE", 409,
                "EXTEND_DEADLINE requires item PLANNED, INSTALLED or CERTIFICATION_FAILED",
            )
        if new_deadline <= item["implementation_deadline"] or \
                new_deadline > item["implementation_deadline"] + timedelta(days=365):
            raise ApiError(
                "ERR_EXTENSION_TOO_LONG", 422,
                "new_deadline must be after the current deadline and within +365 days",
            )

    m = {
        "id": new_id(),
        "contract_id": cid,
        "kind": kind,
        "practice_item_id": item["id"] if item is not None else None,
        "new_deadline": new_deadline,
        "new_practice_code": new_code,
        "new_quantity": new_qty,
        "requested_by_user_id": _uid,
        "status": "REQUESTED",
    }
    stamp_new(m)
    STORE.modifications[m["id"]] = m
    contract["status"] = "MODIFICATION_PENDING"
    touch(contract)
    return ok(serializers.modification(m), 201)


@bp.get("/eqip/contracts/<cid>/modifications")
@require_roles(*ANY_ROLE)
def list_contract_modifications(cid, _uid, _role):
    get_contract(cid)
    items = [m for m in sorted_created(STORE.modifications.values()) if m["contract_id"] == cid]
    page, meta = paginate(items)
    return ok_list([serializers.modification(m) for m in page], meta)
