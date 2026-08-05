"""Resolutions: RMA coordination, dispatch, complete/fail, reads."""
from flask import Blueprint, request

import store
import serializers as S
import calc
from store import touch
from common import (
    get_body, ok, ok_list, paginate, require_auth, resolve_or_404,
)
from errors import ApiError
from util import new_id

bp_resolutions = Blueprint("resolutions", __name__)

RES_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "ManufacturerAgent", "PlatformAdmin"]


def _manufacturer_of(res):
    claim = store.claims.get(res["claim_id"])
    if claim is None:
        return None
    product = store.products.get(claim["product_id"])
    if product is None:
        return None
    return store.manufacturers.get(product["manufacturer_id"])


@bp_resolutions.route("/resolutions/<rid>/request-rma", methods=["POST"])
def request_rma(rid):
    require_auth(["ConciergeAgent"])
    res = resolve_or_404(store.resolutions, rid)
    manufacturer = _manufacturer_of(res)
    if manufacturer is not None and not manufacturer["coordination_enabled"]:
        raise ApiError("ERR_COORDINATION_DISABLED")
    res["rma_status"] = "REQUESTED"
    touch(res)
    return ok(S.resolution(res))


@bp_resolutions.route("/resolutions/<rid>/authorize-rma", methods=["POST"])
def authorize_rma(rid):
    require_auth(["ManufacturerAgent"])
    res = resolve_or_404(store.resolutions, rid)
    res["rma_status"] = "AUTHORIZED"
    res["rma_number"] = "RMA-" + new_id()[:8].upper()
    touch(res)
    return ok(S.resolution(res))


@bp_resolutions.route("/resolutions/<rid>/dispatch", methods=["POST"])
def dispatch(rid):
    require_auth(["ConciergeAgent"])
    res = resolve_or_404(store.resolutions, rid)
    body = get_body()
    replacement_product_id = body.get("replacement_product_id")

    # existence of provided body id (priority 4)
    if replacement_product_id is not None and replacement_product_id not in store.products:
        raise ApiError("ERR_NOT_FOUND")
    # state (priority 5)
    if res["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    # RMA authorization gate (business)
    if res["mode"] == "REPLACEMENT":
        manufacturer = _manufacturer_of(res)
        if manufacturer is not None and manufacturer["rma_required"] and res["rma_status"] != "AUTHORIZED":
            raise ApiError("ERR_RMA_NOT_AUTHORIZED")
    # replacement id required (well-formedness, last)
    if res["mode"] == "REPLACEMENT" and (not isinstance(replacement_product_id, str) or replacement_product_id == ""):
        raise ApiError("ERR_INVALID_REQUEST", "replacement_product_id is required for a REPLACEMENT dispatch.")

    res["status"] = "DISPATCHED"
    if res["mode"] == "REPLACEMENT":
        res["replacement_product_id"] = replacement_product_id
    touch(res)
    return ok(S.resolution(res))


@bp_resolutions.route("/resolutions/<rid>/complete", methods=["POST"])
def complete(rid):
    require_auth(["ConciergeAgent"])
    res = resolve_or_404(store.resolutions, rid)
    if res["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE")

    res["status"] = "COMPLETED"
    claim = store.claims.get(res["claim_id"])
    if claim is not None:
        claim["status"] = "RESOLVED"
        claim["settlement_total_cents"] = res["settlement_total_cents"]
        touch(claim)
        if claim["claim_type"] == "RECALL" and claim.get("recall_match_id"):
            match = store.recall_matches.get(claim["recall_match_id"])
            if match is not None:
                match["status"] = "REMEDIED"
                touch(match)
                product = store.products.get(match["product_id"])
                if product is not None:
                    product["recall_status"] = "REMEDIED"
                    touch(product)
                    hh = store.households.get(product["household_id"])
                    if hh is not None:
                        calc.recompute_recall_exposure(hh)
        product = store.products.get(claim["product_id"])
        if product is not None:
            hh = store.households.get(product["household_id"])
            if hh is not None:
                calc.recompute_active_claim_count(hh)
    touch(res)
    return ok(S.resolution(res))


@bp_resolutions.route("/resolutions/<rid>/fail", methods=["POST"])
def fail(rid):
    require_auth(["ConciergeAgent"])
    res = resolve_or_404(store.resolutions, rid)
    if res["status"] not in ("PENDING", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE")
    res["status"] = "FAILED"
    touch(res)
    return ok(S.resolution(res))


@bp_resolutions.route("/resolutions/<rid>", methods=["GET"])
def get_resolution(rid):
    require_auth(RES_READ_ROLES)
    rec = resolve_or_404(store.resolutions, rid)
    return ok(S.resolution(rec))


@bp_resolutions.route("/resolutions", methods=["GET"])
def list_resolutions():
    require_auth(RES_READ_ROLES)
    claim_id = request.args.get("claim_id")
    replacement_product_id = request.args.get("replacement_product_id")
    records = list(store.resolutions.values())
    if claim_id is not None:
        records = [r for r in records if r["claim_id"] == claim_id]
    if replacement_product_id is not None:
        records = [r for r in records if r["replacement_product_id"] == replacement_product_id]
    items, pagination = paginate(records, S.resolution)
    return ok_list(items, pagination)
