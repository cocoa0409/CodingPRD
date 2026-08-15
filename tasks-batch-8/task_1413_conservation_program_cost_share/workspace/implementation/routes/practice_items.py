"""ContractPracticeItem: read, PATCH (OCC), install/certify/fail."""
from datetime import timedelta

from flask import Blueprint

import serializers
from db import STORE, new_id, now
from errors import ApiError
from helpers import (
    apply_filters, as_dt, body, get_application, get_contract,
    get_item, paginate, req_field, sorted_created, stamp_new, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list
from services import calc
from util import dec, is_num

bp = Blueprint("practice_items", __name__)


@bp.get("/eqip/practice-items/<iid>")
@require_roles(*ANY_ROLE)
def get_one_item(iid, _uid, _role):
    return ok(serializers.item(get_item(iid)))


@bp.get("/eqip/practice-items")
@require_roles(*ANY_ROLE)
def list_items(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.items.values()),
        [("contract_id", "contract_id"),
         ("payment_schedule_rate_id", "payment_schedule_rate_id"),
         ("certification_status", "certification_status"),
         ("payment_status", "payment_status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.item(i) for i in page], meta)


@bp.patch("/eqip/practice-items/<iid>")
@require_roles("ConservationPlanner")
def patch_item(iid, _uid, _role):
    item = get_item(iid)
    contract = get_contract(item["contract_id"])
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", 409, "item edits require contract DRAFT")
    data = body()
    expected = req_field(data, "expected_item_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_item_version must be an integer")
    if expected != item["version"]:
        raise ApiError(
            "ERR_STALE_ITEM_VERSION", 412,
            "expected_item_version does not match the item's current version",
        )
    if "planned_quantity" in data and data["planned_quantity"] is not None:
        qty = data["planned_quantity"]
        if not is_num(qty) or dec(qty) <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "planned_quantity must be a number > 0")
        app = get_application(contract["application_id"])
        planned = {p["practice_code"]: p["quantity"] for p in app["planned_practices"]}
        if item["practice_code"] in planned and dec(qty) > dec(planned[item["practice_code"]]):
            raise ApiError(
                "ERR_QUANTITY_EXCEEDS_APPLICATION", 422,
                "planned_quantity exceeds the quantity planned in the application",
            )
        item["planned_quantity"] = qty
    if "implementation_deadline" in data and data["implementation_deadline"] is not None:
        item["implementation_deadline"] = as_dt(data["implementation_deadline"], "implementation_deadline")
    # scheduled_amount recomputed against the frozen rate snapshot.
    new_sched = calc.scheduled_amount_cents(item["planned_quantity"], item["applicable_rate_cents"])
    if new_sched != item["scheduled_amount_cents"]:
        item["_held_cents"] = item.get("_held_cents", 0) + (new_sched - item["scheduled_amount_cents"])
        item["scheduled_amount_cents"] = new_sched
    calc.recompute_contract_obligated(contract)
    touch(contract)
    touch(item)
    return ok(serializers.item(item))


@bp.post("/eqip/practice-items/<iid>/report-installed")
@require_roles("Applicant")
def report_installed(iid, _uid, _role):
    item = get_item(iid)
    contract = get_contract(item["contract_id"])
    check_owner(contract["applicant_id"], _uid)
    if contract["status"] != "OBLIGATED":
        raise ApiError(
            "ERR_CONTRACT_NOT_PAYABLE", 409,
            "report-installed requires contract OBLIGATED",
        )
    if item["certification_status"] not in ("PLANNED", "CERTIFICATION_FAILED"):
        raise ApiError(
            "ERR_ITEM_NOT_INSTALLABLE", 409,
            "report-installed requires PLANNED or CERTIFICATION_FAILED",
        )
    if now() > item["implementation_deadline"]:
        raise ApiError("ERR_DEADLINE_PASSED", 409, "the implementation deadline has passed")
    item["certification_status"] = "INSTALLED"
    touch(item)
    return ok(serializers.item(item))


@bp.post("/eqip/practice-items/<iid>/certify")
@require_roles("ConservationPlanner")
def certify_item(iid, _uid, _role):
    item = get_item(iid)
    contract = get_contract(item["contract_id"])
    if item["certification_status"] != "INSTALLED":
        raise ApiError("ERR_ITEM_NOT_INSTALLED", 409, "certify requires item INSTALLED")
    if contract["status"] != "OBLIGATED":
        raise ApiError(
            "ERR_CONTRACT_NOT_PAYABLE", 409,
            "the contract is frozen or not in a payable posture",
        )
    data = body()
    cq = req_field(data, "certified_quantity")
    if not is_num(cq) or dec(cq) < 1 or dec(cq) > dec(item["planned_quantity"]):
        raise ApiError(
            "ERR_CERTIFIED_QUANTITY_INVALID", 422,
            "certified_quantity must be >= 1 and <= planned_quantity",
        )
    certified_at = now()
    if certified_at > item["implementation_deadline"]:
        raise ApiError("ERR_DEADLINE_PASSED", 409, "the implementation deadline has passed")
    # Half-open obligation overlap: an ACTIVE / VIOLATION_REVIEW obligation on
    # the same parcel + practice blocks only when its end_date is strictly
    # after the new certification instant.
    app = get_application(contract["application_id"])
    for ob in STORE.obligations.values():
        if ob["parcel_id"] != app["parcel_id"] or ob["practice_code"] != item["practice_code"]:
            continue
        if ob["status"] in ("ACTIVE", "VIOLATION_REVIEW") and ob["end_date"] > certified_at:
            raise ApiError(
                "ERR_OBLIGATION_OVERLAP", 409,
                "an active maintenance obligation overlaps this certification",
            )
    rate_row = STORE.rates.get(item["payment_schedule_rate_id"])
    lifespan = rate_row["lifespan_years"] if rate_row is not None else 1
    item["certification_status"] = "CERTIFIED"
    item["certified_quantity"] = cq
    item["certified_by_user_id"] = _uid
    item["certified_at"] = certified_at
    touch(item)
    ob = {
        "id": new_id(),
        "contract_id": contract["id"],
        "practice_item_id": item["id"],
        "parcel_id": app["parcel_id"],
        "practice_code": item["practice_code"],
        "start_date": certified_at,
        "end_date": certified_at + timedelta(days=365 * lifespan),
        "reported_by_user_id": None,
        "status": "ACTIVE",
    }
    stamp_new(ob)
    STORE.obligations[ob["id"]] = ob
    return ok(serializers.item(item))


@bp.post("/eqip/practice-items/<iid>/fail-certification")
@require_roles("ConservationPlanner")
def fail_certification(iid, _uid, _role):
    item = get_item(iid)
    contract = get_contract(item["contract_id"])
    if item["certification_status"] != "INSTALLED":
        raise ApiError("ERR_ITEM_NOT_INSTALLED", 409, "fail-certification requires item INSTALLED")
    if contract["status"] != "OBLIGATED":
        raise ApiError(
            "ERR_CONTRACT_NOT_PAYABLE", 409,
            "the contract is frozen or not in a payable posture",
        )
    item["certification_status"] = "CERTIFICATION_FAILED"
    touch(item)
    return ok(serializers.item(item))
