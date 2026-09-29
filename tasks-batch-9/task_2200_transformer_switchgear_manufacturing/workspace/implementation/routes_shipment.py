"""Staged shipment releases and site storage agreements (PRD 3.7)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import BOOLEAN, DATETIME, INTEGER, STRING, f

bp = Blueprint("shipment", __name__)

DISPATCHED = ("IN_TRANSIT", "DELIVERED", "CANCELLED")


def _releases(order_id):
    return sorted(store.where("release", engineered_order_id=order_id),
                  key=lambda r: r.get("stage_index") or 0)


def _open_agreements(release_id):
    return [a for a in store.where("storage", shipment_release_id=release_id)
            if a.get("status") == "OPEN"]


def _issued_label(order):
    for lab in store.where("label", engineered_order_id=order["id"]):
        if lab.get("status") == "ISSUED":
            return lab
    return None


# --------------------------------------------------------------------------- #
# shipment releases
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/shipment-releases", methods=["POST"])
def create_release(oid):
    rbac.authenticate("POST /engineered-orders/{id}/shipment-releases")
    order = common.resolve("order", oid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("stage_index", INTEGER, required=True, minimum=1),
        f("stage_share_bp", INTEGER, required=True, minimum=1, maximum=10000),
        f("is_final_stage", BOOLEAN, default=False),
        f("expected_engineered_order_version", INTEGER, required=True),
    ])
    validation.check_order_version(data, order)
    common.check_order_not_cancelled(order)
    siblings = [r for r in _releases(oid) if r.get("status") != "CANCELLED"]
    total = sum(r.get("stage_share_bp") or 0 for r in siblings) + data["stage_share_bp"]
    if total != 10000:
        raise ApiError("ERR_STAGE_SHARE_TOTAL_INVALID",
                       "the stage shares on the order would total %d basis points" % total)
    if data["is_final_stage"]:
        for r in siblings:
            if r.get("is_final_stage"):
                raise ApiError("ERR_MULTIPLE_FINAL_STAGES",
                               "release %s is already the final stage" % r["id"])
    highest = 0
    previous = None
    for r in _releases(oid):
        if r.get("stage_index") == data["stage_index"]:
            raise ApiError("ERR_STAGE_INDEX_OUT_OF_SEQUENCE",
                           "stage_index %d already exists on the order" % data["stage_index"])
        if (r.get("stage_index") or 0) > highest:
            highest = r.get("stage_index") or 0
            previous = r
    if data["stage_index"] != highest + 1:
        raise ApiError("ERR_STAGE_INDEX_OUT_OF_SEQUENCE",
                       "stage_index must be dense from 1; expected %d" % (highest + 1))
    if previous is not None and previous.get("status") not in DISPATCHED:
        raise ApiError("ERR_STAGE_INDEX_OUT_OF_SEQUENCE",
                       "stage %d has not yet been dispatched" % previous.get("stage_index"))
    release = {
        "engineered_order_id": oid,
        "stage_index": data["stage_index"],
        "stage_share_bp": data["stage_share_bp"],
        "stage_billing_cents": 0,
        "status": "HELD",
        "is_final_stage": data["is_final_stage"],
        "cleared_at": None,
        "shipped_at": None,
        "delivered_at": None,
        "carrier_reference": None,
        "storage_fee_accrued_cents": 0,
    }
    store.insert("release", release)
    calc.stage_billing_allocation(order)
    for r in _releases(oid):
        if r["id"] != release["id"]:
            store.touch("release", r)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.created(store.public(release))


@bp.route("/engineered-orders/<oid>/shipment-releases", methods=["GET"])
def list_order_releases(oid):
    rbac.authenticate("GET /engineered-orders/{id}/shipment-releases")
    common.resolve("order", oid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(_releases(oid), {
        "status": common.qstr("status"),
        "is_final_stage": common.qbool("is_final_stage"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/shipment-releases/<rid>", methods=["GET"])
def get_release(rid):
    rbac.authenticate("GET /shipment-releases/{id}")
    return envelope.ok(store.public(common.resolve("release", rid)))


@bp.route("/shipment-releases/<rid>/clear", methods=["POST"])
def clear_release(rid):
    rbac.authenticate("POST /shipment-releases/{id}/clear")
    release = common.resolve("release", rid)
    order = common.resolve("order", release.get("engineered_order_id"))
    common.check_state("release", release, ("HELD",))
    common.check_order_not_cancelled(order)
    common.check_order_fulfillment(order, ("FAT_COMPLETE", "SHIPPING"))
    posture.check_posture_blocked(order)
    label = _issued_label(order)
    if label is not None \
            and label.get("pinned_drawing_revision") != order.get("released_drawing_revision"):
        raise ApiError("ERR_LABEL_STALE",
                       "the issued label pins a superseded drawing revision")
    if label is None:
        raise ApiError("ERR_LABEL_NOT_ISSUED", "no compliance label on the order is ISSUED")
    for other in _releases(order["id"]):
        if (other.get("stage_index") or 0) < (release.get("stage_index") or 0) \
                and other.get("status") not in DISPATCHED:
            raise ApiError("ERR_STAGE_INDEX_OUT_OF_SEQUENCE",
                           "stage %s has not yet been dispatched" % other.get("stage_index"))
    release["status"] = "CLEARED"
    release["cleared_at"] = clock.now_str()
    calc.stage_billing_allocation(order)
    store.touch("release", release)
    for r in _releases(order["id"]):
        if r["id"] != rid:
            store.touch("release", r)
    posture.refresh(order)
    return envelope.ok(store.public(release))


@bp.route("/shipment-releases/<rid>/stage", methods=["POST"])
def stage_release(rid):
    rbac.authenticate("POST /shipment-releases/{id}/stage")
    release = common.resolve("release", rid)
    order = common.resolve("order", release.get("engineered_order_id"))
    common.check_state("release", release, ("CLEARED",))
    common.check_order_not_cancelled(order)
    release["status"] = "STAGED"
    release["_staged_at"] = clock.now_str()
    store.touch("release", release)
    posture.refresh(order)
    return envelope.ok(store.public(release))


@bp.route("/shipment-releases/<rid>/ship", methods=["POST"])
def ship_release(rid):
    rbac.authenticate("POST /shipment-releases/{id}/ship")
    release = common.resolve("release", rid)
    order = common.resolve("order", release.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("carrier_reference", STRING, required=True)])
    if not data["carrier_reference"].strip():
        raise ApiError("ERR_MISSING_REQUIRED_FIELD", "carrier_reference must be non-empty")
    common.check_state("release", release, ("STAGED",))
    common.check_order_not_cancelled(order)
    posture.check_posture_blocked(order)
    label = _issued_label(order)
    if label is None:
        raise ApiError("ERR_LABEL_NOT_ISSUED", "no compliance label on the order is ISSUED")
    if _open_agreements(rid):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a site storage agreement on the stage is still OPEN")
    money = posture.money(order)
    if money["billed_to_date_cents"] + (release.get("stage_billing_cents") or 0) \
            > money["net_contract_value_cents"]:
        raise ApiError("ERR_BILLING_EXCEEDS_CONTRACT",
                       "billing this stage would exceed the net contract value")
    release["status"] = "IN_TRANSIT"
    release["shipped_at"] = clock.now_str()
    release["carrier_reference"] = data["carrier_reference"]
    store.touch("release", release)
    if order.get("fulfillment_status") == "FAT_COMPLETE":
        order["fulfillment_status"] = "SHIPPING"
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(release))


@bp.route("/shipment-releases/<rid>/deliver", methods=["POST"])
def deliver_release(rid):
    rbac.authenticate("POST /shipment-releases/{id}/deliver")
    release = common.resolve("release", rid)
    order = common.resolve("order", release.get("engineered_order_id"))
    common.check_state("release", release, ("IN_TRANSIT",))
    common.check_order_not_cancelled(order)
    release["status"] = "DELIVERED"
    release["delivered_at"] = clock.now_str()
    store.touch("release", release)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(release))


# --------------------------------------------------------------------------- #
# site storage agreements
# --------------------------------------------------------------------------- #

@bp.route("/shipment-releases/<rid>/site-storage-agreements", methods=["POST"])
def create_agreement(rid):
    rbac.authenticate("POST /shipment-releases/{id}/site-storage-agreements")
    release = common.resolve("release", rid)
    order = common.resolve("order", release.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [
        f("storage_start_at", DATETIME, required=True),
        f("storage_end_at", DATETIME),
        f("crate_count", INTEGER, required=True, minimum=1),
        f("insured_value_cents", INTEGER, required=True, minimum=0),
    ])
    common.check_state("release", release, ("STAGED",))
    common.check_order_not_cancelled(order)
    if _open_agreements(rid):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "an agreement on the stage is already OPEN")
    start = clock.sec(clock.parse(data["storage_start_at"]))
    end = clock.sec(clock.parse(data.get("storage_end_at"))) if data.get("storage_end_at") else None
    staged_at = clock.sec(clock.parse(release.get("_staged_at")))
    if end is not None and end <= start:
        raise ApiError("ERR_STORAGE_PERIOD_INVALID",
                       "storage_end_at must be strictly after storage_start_at")
    if staged_at is not None and start < staged_at:
        raise ApiError("ERR_STORAGE_PERIOD_INVALID",
                       "storage_start_at precedes the stage being staged")
    agreement = {
        "shipment_release_id": rid,
        "storage_start_at": data["storage_start_at"],
        "storage_end_at": data.get("storage_end_at"),
        "billable_days": 0,
        "crate_count": data["crate_count"],
        "insured_value_cents": data["insured_value_cents"],
        "status": "OPEN",
        "storage_subtotal_cents": 0,
        "insurance_surcharge_cents": 0,
        "long_stay_discount_cents": 0,
        "total_fee_cents": 0,
        "waived_by_user_id": None,
    }
    if agreement["storage_end_at"]:
        agreement.update(calc.storage_fee(agreement))
    store.insert("storage", agreement)
    release["status"] = "SITE_STORAGE"
    store.touch("release", release)
    posture.refresh(order)
    return envelope.created(store.public(agreement))


@bp.route("/shipment-releases/<rid>/site-storage-agreements", methods=["GET"])
def list_release_agreements(rid):
    rbac.authenticate("GET /shipment-releases/{id}/site-storage-agreements")
    common.resolve("release", rid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("storage", shipment_release_id=rid),
                               {"status": common.qstr("status")})
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/site-storage-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    rbac.authenticate("GET /site-storage-agreements/{id}")
    return envelope.ok(store.public(common.resolve("storage", aid)))


@bp.route("/site-storage-agreements/<aid>/close", methods=["POST"])
def close_agreement(aid):
    rbac.authenticate("POST /site-storage-agreements/{id}/close")
    agreement = common.resolve("storage", aid)
    release = common.resolve("release", agreement.get("shipment_release_id"))
    order = common.resolve("order", release.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("storage_end_at", DATETIME)])
    common.check_state("storage", agreement, ("OPEN",))
    if release.get("status") != "SITE_STORAGE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the stage is %s" % release.get("status"))
    effective = data.get("storage_end_at") or agreement.get("storage_end_at") or clock.now_str()
    start = clock.sec(clock.parse(agreement.get("storage_start_at")))
    end = clock.sec(clock.parse(effective))
    if end is None or end <= start or end > clock.sec(clock.now()):
        raise ApiError("ERR_STORAGE_PERIOD_INVALID",
                       "storage_end_at must be after the start and not in the future")
    agreement["storage_end_at"] = effective
    agreement.update(calc.storage_fee(agreement))
    agreement["status"] = "CLOSED"
    store.touch("storage", agreement)
    release["status"] = "STAGED"
    release["storage_fee_accrued_cents"] = (release.get("storage_fee_accrued_cents") or 0) \
        + (agreement.get("total_fee_cents") or 0)
    store.touch("release", release)
    posture.refresh(order)
    return envelope.ok(store.public(agreement))


@bp.route("/site-storage-agreements/<aid>/waive", methods=["POST"])
def waive_agreement(aid):
    rbac.authenticate("POST /site-storage-agreements/{id}/waive")
    agreement = common.resolve("storage", aid)
    release = common.resolve("release", agreement.get("shipment_release_id"))
    order = common.resolve("order", release.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("waived_by_user_id", STRING, required=True)])
    common.check_state("storage", agreement, ("OPEN",))
    agreement["status"] = "WAIVED"
    agreement["billable_days"] = 0
    agreement["storage_subtotal_cents"] = 0
    agreement["insurance_surcharge_cents"] = 0
    agreement["long_stay_discount_cents"] = 0
    agreement["total_fee_cents"] = 0
    agreement["waived_by_user_id"] = data["waived_by_user_id"]
    store.touch("storage", agreement)
    if release.get("status") == "SITE_STORAGE":
        release["status"] = "STAGED"
        store.touch("release", release)
    posture.refresh(order)
    return envelope.ok(store.public(agreement))
