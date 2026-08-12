from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_LAWN_NOT_FOUND, ERR_SOIL_TEST_NOT_FOUND, ERR_PLAN_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_PRODUCT_INACTIVE, ERR_SOIL_TEST_NOT_ANALYZED,
    ERR_PLAN_NOT_DRAFT, ERR_PLAN_NOT_ACTIVATABLE, ERR_LAWN_ARCHIVED,
    ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_plan
from services import find_product_by_sku, compute_plan_provisional
from util import req_str, req_int, fmt_dt3

bp = Blueprint("plans", __name__)

READ_ROLES = ["Customer", "Agronomist", "PlatformAdmin"]


def _validate_plan_lines(plan_lines):
    if not isinstance(plan_lines, list):
        raise_err(ERR_INVALID_REQUEST, "Field 'plan_lines' must be an array")
    for line in plan_lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "Each plan line must be an object")
        sku = line.get("product_sku")
        if not isinstance(sku, str) or not sku.strip():
            raise_err(ERR_INVALID_REQUEST, "Each plan line requires a 'product_sku' string")
        qty = line.get("qty_units")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise_err(ERR_INVALID_REQUEST, "Each plan line requires 'qty_units' as a positive integer")
        month = line.get("target_month")
        if isinstance(month, bool) or not isinstance(month, int) or not (1 <= month <= 12):
            raise_err(ERR_INVALID_REQUEST, "Each plan line requires 'target_month' as an integer 1..12")


def _check_line_skus(plan_lines):
    # existence band first (404), then the active constraint (409)
    for line in plan_lines:
        if find_product_by_sku(line["product_sku"]) is None:
            raise_err(ERR_PRODUCT_NOT_FOUND,
                      "Plan line sku '%s' does not exist in the catalog" % line["product_sku"])
    for line in plan_lines:
        if not find_product_by_sku(line["product_sku"]).active:
            raise_err(ERR_PRODUCT_INACTIVE,
                      "Plan line sku '%s' is inactive" % line["product_sku"])


def _get_plan_or_404(pid):
    rec = store.plans.get(pid)
    if rec is None:
        raise_err(ERR_PLAN_NOT_FOUND, "Plan not found")
    return rec


@bp.route("/api/plans", methods=["POST"])
def create_plan():
    body = get_body()
    lawn_id = req_str(body, "lawn_id")
    soil_test_id = req_str(body, "soil_test_id")
    season_year = req_int(body, "season_year")
    if "plan_lines" not in body:
        raise_err(ERR_INVALID_REQUEST, "Field 'plan_lines' is required")
    plan_lines = body["plan_lines"]
    _validate_plan_lines(plan_lines)

    authenticate(["Agronomist"])

    if lawn_id not in store.lawns:
        raise_err(ERR_LAWN_NOT_FOUND, "Lawn not found")
    kit = store.soil_tests.get(soil_test_id)
    if kit is None:
        raise_err(ERR_SOIL_TEST_NOT_FOUND, "Soil test not found")
    _check_line_skus(plan_lines)
    # cross-entity referential state (band 9)
    if kit.status != "ANALYZED":
        raise_err(ERR_SOIL_TEST_NOT_ANALYZED, "Plan creation requires an ANALYZED soil test")

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        lawn_id=lawn_id, soil_test_id=soil_test_id, season_year=season_year,
        plan_lines=plan_lines, status="DRAFT",
        provisional_value_cents=0, committed_value_cents=None,
        discount_pct_locked=None, supersedes_plan_id=None, activated_at=None,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    rec.provisional_value_cents = compute_plan_provisional(rec)
    store.plans[rec.id] = rec
    return ok(ser_plan(rec), 201)


@bp.route("/api/plans/<pid>", methods=["GET"])
def get_plan(pid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_plan_or_404(pid)
    lawn = store.lawns.get(rec.lawn_id)
    check_ownership(uid, role, lawn.customer_id if lawn else None)
    return ok(ser_plan(rec))


@bp.route("/api/plans", methods=["GET"])
def list_plans():
    uid, role = authenticate(READ_ROLES)
    items = list(store.plans.values())
    if role == "Customer":
        own_lawns = {l.id for l in store.lawns.values() if l.customer_id == uid}
        items = [p for p in items if p.lawn_id in own_lawns]
    for param in ("lawn_id", "soil_test_id", "supersedes_plan_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if getattr(p, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_plan(p) for p in page], total, limit, offset)


@bp.route("/api/plans/<pid>/submit-review", methods=["POST"])
def submit_review(pid):
    authenticate(["Agronomist"])
    rec = _get_plan_or_404(pid)
    if rec.status != "DRAFT":
        raise_err(ERR_PLAN_NOT_DRAFT, "submit-review requires DRAFT")
    rec.status = "PENDING_REVIEW"
    touch(rec)
    return ok(ser_plan(rec))


@bp.route("/api/plans/<pid>", methods=["PATCH"])
def patch_plan(pid):
    body = get_body()
    plan_lines = body.get("plan_lines")
    if plan_lines is not None:
        _validate_plan_lines(plan_lines)
    season_year = body.get("season_year")
    if season_year is not None and (isinstance(season_year, bool) or not isinstance(season_year, int)):
        raise_err(ERR_INVALID_REQUEST, "Field 'season_year' must be an integer")

    authenticate(["Agronomist"])
    rec = _get_plan_or_404(pid)
    if rec.status not in ("DRAFT", "PENDING_REVIEW"):
        raise_err(ERR_PLAN_NOT_DRAFT, "Edit requires DRAFT or PENDING_REVIEW")
    if plan_lines is not None:
        _check_line_skus(plan_lines)
        rec.plan_lines = plan_lines
        rec.provisional_value_cents = compute_plan_provisional(rec)
    if season_year is not None:
        rec.season_year = season_year
    if rec.status == "PENDING_REVIEW":
        rec.status = "DRAFT"  # revision cycle
    touch(rec)
    return ok(ser_plan(rec))


@bp.route("/api/plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    body = get_body()
    if "expected_lawn_version" not in body:
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_lawn_version' is required")
    expected = body["expected_lawn_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_lawn_version' must be an integer")

    uid, role = authenticate(["Customer"])
    rec = _get_plan_or_404(pid)
    lawn = store.lawns.get(rec.lawn_id)
    check_ownership(uid, role, lawn.customer_id if lawn else None)
    if rec.status != "PENDING_REVIEW":
        raise_err(ERR_PLAN_NOT_ACTIVATABLE, "activate requires PENDING_REVIEW")
    if lawn is None or lawn.status != "ACTIVE":
        raise_err(ERR_LAWN_ARCHIVED, "Operation requires an ACTIVE lawn")
    kit = store.soil_tests.get(rec.soil_test_id)
    if kit is None or kit.status != "ANALYZED":
        raise_err(ERR_SOIL_TEST_NOT_ANALYZED, "Activation requires an ANALYZED soil test")
    if expected != lawn.version:
        raise_err(ERR_STALE_VERSION, "expected_lawn_version does not match the lawn's current version")

    # supersede the lawn's previously ACTIVE plan, if any
    prev = None
    for p in store.plans.values():
        if p.lawn_id == rec.lawn_id and p.status == "ACTIVE" and p.id != rec.id:
            prev = p
            break
    if prev is not None:
        prev.status = "SUPERSEDED"
        touch(prev)
    rec.supersedes_plan_id = prev.id if prev is not None else None
    rec.activated_at = now()
    rec.raw["activated_at"] = fmt_dt3(rec.activated_at)
    rec.status = "ACTIVE"
    touch(rec)
    touch(lawn)
    return ok(ser_plan(rec))
