"""Recall notices (draft/publish/close/reads) and recall matches (ack/dismiss/remedy/reads)."""
from flask import Blueprint, request

import store
import serializers as S
from calc import SEVERITY_WEIGHT, recompute_recall_exposure
from store import touch
from common import (
    bad_request, get_body, new_common, ok, ok_list, paginate, require_auth,
    require_enum, require_int, require_str, require_household_member, resolve_or_404,
)
from errors import ApiError
from util import parse_dt

bp_recalls = Blueprint("recalls", __name__)

RECALL_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "ManufacturerAgent", "PlatformAdmin"]
SEVERITIES = {"LOW", "HIGH", "CRITICAL"}
REMEDIES = {"REPAIR", "REPLACE", "REFUND"}


def _household_of_match(match):
    product = store.products.get(match["product_id"])
    if product is None:
        return None
    return store.households.get(product["household_id"])


# --------------------------------------------------------- recall notices ----
@bp_recalls.route("/recall-notices", methods=["POST"])
def create_recall_notice():
    role, uid = require_auth(["ManufacturerAgent"])
    body = get_body()

    manufacturer_id = body.get("manufacturer_id")
    if manufacturer_id is not None and manufacturer_id not in store.manufacturers:
        raise ApiError("ERR_NOT_FOUND")
    if not isinstance(manufacturer_id, str) or manufacturer_id == "":
        raise bad_request("manufacturer_id is required.")

    affected_model_number = require_str(body, "affected_model_number")
    serial_range_start = require_int(body, "serial_range_start")
    serial_range_end = require_int(body, "serial_range_end")
    if serial_range_start > serial_range_end:
        raise bad_request("serial_range_start must be <= serial_range_end.")
    severity = require_enum(body, "severity", SEVERITIES)
    remedy_type = require_enum(body, "remedy_type", REMEDIES)
    for f in ("effective_from", "effective_to"):
        if not isinstance(body.get(f), str):
            raise bad_request("%s is required." % f)
        try:
            parse_dt(body.get(f))
        except (ValueError, TypeError):
            raise bad_request("%s must be a valid ISO 8601 timestamp." % f)

    rec = new_common()
    rec.update({
        "manufacturer_id": manufacturer_id,
        "affected_model_number": affected_model_number,
        "serial_range_start": serial_range_start,
        "serial_range_end": serial_range_end,
        "severity": severity,
        "remedy_type": remedy_type,
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "status": "DRAFT",
        "matched_product_count": 0,
    })
    store.recall_notices[rec["id"]] = rec
    return ok(S.recall_notice(rec), 201)


@bp_recalls.route("/recall-notices/<rid>/publish", methods=["POST"])
def publish_recall(rid):
    require_auth(["ManufacturerAgent"])
    notice = resolve_or_404(store.recall_notices, rid)
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    a_start = parse_dt(notice["effective_from"])
    a_end = parse_dt(notice["effective_to"])
    for other in store.recall_notices.values():
        if other["id"] == rid or other["status"] != "PUBLISHED":
            continue
        if other["manufacturer_id"] != notice["manufacturer_id"]:
            continue
        if other["affected_model_number"] != notice["affected_model_number"]:
            continue
        b_start = parse_dt(other["effective_from"])
        b_end = parse_dt(other["effective_to"])
        # closed intervals: touching endpoints overlap
        if a_start <= b_end and b_start <= a_end:
            raise ApiError("ERR_RECALL_WINDOW_OVERLAP")

    weight = SEVERITY_WEIGHT[notice["severity"]]
    affected_households = {}
    match_count = 0
    for product in list(store.products.values()):
        if product["registration_status"] != "REGISTERED":
            continue
        if product["manufacturer_id"] != notice["manufacturer_id"]:
            continue
        if product["model_number"] != notice["affected_model_number"]:
            continue
        if not (notice["serial_range_start"] <= product["serial_number"] <= notice["serial_range_end"]):
            continue
        match = new_common()
        match.update({
            "recall_notice_id": rid,
            "product_id": product["id"],
            "severity_weight": weight,
            "status": "MATCHED",
        })
        store.recall_matches[match["id"]] = match
        match_count += 1
        product["recall_status"] = "RECALLED"
        touch(product)
        hh = store.households.get(product["household_id"])
        if hh is not None:
            affected_households[hh["id"]] = hh

    notice["matched_product_count"] = match_count
    for hh in affected_households.values():
        recompute_recall_exposure(hh)

    notice["status"] = "PUBLISHED"
    touch(notice)
    return ok(S.recall_notice(notice))


@bp_recalls.route("/recall-notices/<rid>/close", methods=["POST"])
def close_recall(rid):
    require_auth(["ManufacturerAgent"])
    notice = resolve_or_404(store.recall_notices, rid)
    if notice["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE")
    notice["status"] = "CLOSED"
    touch(notice)
    return ok(S.recall_notice(notice))


@bp_recalls.route("/recall-notices/<rid>", methods=["GET"])
def get_recall_notice(rid):
    require_auth(RECALL_READ_ROLES)
    rec = resolve_or_404(store.recall_notices, rid)
    return ok(S.recall_notice(rec))


@bp_recalls.route("/recall-notices", methods=["GET"])
def list_recall_notices():
    require_auth(RECALL_READ_ROLES)
    mid = request.args.get("manufacturer_id")
    records = list(store.recall_notices.values())
    if mid is not None:
        records = [r for r in records if r["manufacturer_id"] == mid]
    items, pagination = paginate(records, S.recall_notice)
    return ok_list(items, pagination)


# ---------------------------------------------------------- recall matches ----
@bp_recalls.route("/recall-matches/<mid>/acknowledge", methods=["POST"])
def acknowledge_match(mid):
    role, uid = require_auth(["HouseholdOwner", "HouseholdMember"])
    match = resolve_or_404(store.recall_matches, mid)
    hh = _household_of_match(match)
    if hh is not None:
        require_household_member(uid, hh["id"])
    if match["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE")
    notice = store.recall_notices.get(match["recall_notice_id"])
    if notice is None or notice["status"] != "PUBLISHED":
        raise ApiError("ERR_RECALL_NOT_LIVE")
    match["status"] = "ACKNOWLEDGED"
    touch(match)
    return ok(S.recall_match(match))


@bp_recalls.route("/recall-matches/<mid>/dismiss", methods=["POST"])
def dismiss_match(mid):
    role, uid = require_auth(["HouseholdOwner"])
    match = resolve_or_404(store.recall_matches, mid)
    hh = _household_of_match(match)
    if hh is not None:
        require_household_member(uid, hh["id"], require_owner=True)
    if match["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE")
    match["status"] = "DISMISSED"
    touch(match)
    if hh is not None:
        recompute_recall_exposure(hh)
    return ok(S.recall_match(match))


@bp_recalls.route("/recall-matches/<mid>/remedy", methods=["POST"])
def remedy_match(mid):
    require_auth(["ManufacturerAgent", "ConciergeAgent"])
    match = resolve_or_404(store.recall_matches, mid)
    if match["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE")
    match["status"] = "REMEDIED"
    touch(match)
    product = store.products.get(match["product_id"])
    if product is not None:
        product["recall_status"] = "REMEDIED"
        touch(product)
    hh = _household_of_match(match)
    if hh is not None:
        recompute_recall_exposure(hh)
    return ok(S.recall_match(match))


@bp_recalls.route("/recall-matches/<mid>", methods=["GET"])
def get_recall_match(mid):
    require_auth(RECALL_READ_ROLES)
    rec = resolve_or_404(store.recall_matches, mid)
    return ok(S.recall_match(rec))


@bp_recalls.route("/recall-matches", methods=["GET"])
def list_recall_matches():
    require_auth(RECALL_READ_ROLES)
    notice_id = request.args.get("recall_notice_id")
    product_id = request.args.get("product_id")
    records = list(store.recall_matches.values())
    if notice_id is not None:
        records = [m for m in records if m["recall_notice_id"] == notice_id]
    if product_id is not None:
        records = [m for m in records if m["product_id"] == product_id]
    items, pagination = paginate(records, S.recall_match)
    return ok_list(items, pagination)
