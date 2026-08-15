"""Feed order routes: submit, validate, reject, cancel, ship; plus reads."""

from flask import Blueprint, request

import errors
import util
import clock
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate

bp = Blueprint("feed_orders", __name__)


def _drug_label_indications_match(drug, intended_use_label):
    """The drug has no explicit indications text field; the labeled identity is
    its label_name. A submission's free-text intended_use_label matches the
    label when it references the drug's label_name."""
    if not isinstance(intended_use_label, str):
        return False
    return drug.get("label_name", "") in intended_use_label


@bp.post("/vfd/feed-mills/<mid>/feed-orders")
def create_feed_order(mid):
    user_id, _ = require_roles("FeedMillOperator")
    mill = core.get_feed_mill(mid)
    body = util.get_json_body()
    vfd_authorization_id = util.require_field(body, "vfd_authorization_id")
    producer_id = util.require_field(body, "producer_id")
    animal_count = util.require_int(body, "animal_count")
    tons_of_feed = util.require_int(body, "tons_of_feed")
    intended_use_label = util.require_field(body, "intended_use_label")

    vfd = core.get_vfd(vfd_authorization_id)
    producer = core.get_producer(producer_id)

    # entity-backed identity: FeedMillOperator acts as the mill in the path
    if user_id != mill["id"]:
        raise errors.forbidden("X-User-ID must equal the feed mill id")

    # order producer must match VFD producer
    if vfd.get("producer_id") != producer_id:
        raise errors.invalid_request("producer_id must match VfdAuthorization.producer_id")

    # priority 15: producer active
    if producer["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_PRODUCER_SUSPENDED,
                              "Producer status is SUSPENDED or DEBARRED", 409)

    # priority 6: extra-label guard at submission
    drug = core.get_drug(vfd["drug_id"])
    if not _drug_label_indications_match(drug, intended_use_label):
        raise errors.ApiError(errors.ERR_EXTRA_LABEL_USE,
                              "intended_use_label does not match drug label indications", 422)

    order = util.new_entity({
        "feed_mill_id": mill["id"],
        "vfd_authorization_id": vfd_authorization_id,
        "producer_id": producer_id,
        "animal_count": animal_count,
        "tons_of_feed": tons_of_feed,
        "intended_use_label": intended_use_label,
        "status": "SUBMITTED",
    })
    store.feed_orders[order["id"]] = order
    return success_object(order, 201)


@bp.get("/vfd/feed-orders/<oid>")
def get_feed_order(oid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_feed_order(oid))


@bp.get("/vfd/feed-mills/<mid>/feed-orders")
def list_mill_feed_orders(mid):
    require_roles("Inspector", "FeedMillOperator", "Producer")
    core.get_feed_mill(mid)
    items = [o for o in store.feed_orders.values() if o.get("feed_mill_id") == mid]
    for param in ("status", "producer_id", "vfd_authorization_id"):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if o.get(param) == val]
    return _paginate(items)


@bp.get("/vfd/feed-orders")
def list_feed_orders():
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    items = list(store.feed_orders.values())
    for param in ("status", "producer_id", "vfd_authorization_id", "feed_mill_id"):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if o.get(param) == val]
    return _paginate(items)


@bp.post("/vfd/feed-orders/<oid>/validate")
def validate_feed_order(oid):
    user_id, _ = require_roles("FeedMillOperator")
    order = core.get_feed_order(oid)
    if user_id != order.get("feed_mill_id"):
        raise errors.forbidden("X-User-ID must equal the order's feed_mill_id")

    body = util.get_json_body()
    expected_version = body.get("expected_vfd_authorization_version")
    if expected_version is None:
        raise errors.invalid_request("expected_vfd_authorization_version is required")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("expected_vfd_authorization_version must be an integer")

    if order["status"] != "SUBMITTED":
        raise errors.invalid_state("FeedOrder must be SUBMITTED to validate")

    vfd = core.get_vfd(order["vfd_authorization_id"])
    producer = core.get_producer(order["producer_id"])
    drug = core.get_drug(vfd["drug_id"])
    group = core.get_animal_group(vfd["animal_group_id"])

    # Eight validation checks in PRD 3.5 priority order:
    # 1. VFD status usable
    if vfd["status"] not in ("ISSUED", "PARTIALLY_USED"):
        raise errors.ApiError(errors.ERR_VFD_NOT_USABLE,
                              "VFD status not in {ISSUED, PARTIALLY_USED}", 409)
    # 2. clock strictly before expiration
    if clock.now() >= util.parse_iso(vfd["expiration_date"], "expiration_date"):
        raise errors.ApiError(errors.ERR_VFD_EXPIRED,
                              "Logical clock >= VFD expiration_date", 409)
    # 3. producer active
    if producer["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_PRODUCER_SUSPENDED,
                              "Producer status is SUSPENDED or DEBARRED", 409)
    # 4. quota
    if order["animal_count"] > vfd["remaining_animal_count"]:
        raise errors.ApiError(errors.ERR_VFD_QUOTA_EXCEEDED,
                              "Order animal_count exceeds VFD remaining_animal_count", 409)
    # 5. species/class pair
    pair = f"{group['species']}:{group['production_class']}"
    if pair not in drug.get("allowed_species_classes", []):
        raise errors.ApiError(errors.ERR_SPECIES_CLASS_MISMATCH,
                              "Animal group species:class not on drug label", 422)
    # 6. extra-label guard
    if not _drug_label_indications_match(drug, order["intended_use_label"]):
        raise errors.ApiError(errors.ERR_EXTRA_LABEL_USE,
                              "intended_use_label does not match drug label indications", 422)
    # 7. no OPEN residue case on this producer
    for case in store.residue_cases.values():
        if case.get("producer_id") == producer["id"] and case.get("status") == "OPEN":
            raise errors.ApiError(errors.ERR_RESIDUE_CASE_OPEN,
                                  "Producer has an OPEN ResidueCase blocking validation", 422)
    # 8. ACTIVE VCPR covering (vfd.vet_id, vfd.producer_id)
    vcpr_ok = any(
        v.get("vet_id") == vfd["vet_id"]
        and v.get("producer_id") == vfd["producer_id"]
        and v.get("status") == "ACTIVE"
        for v in store.vcp_verifications.values()
    )
    if not vcpr_ok:
        raise errors.ApiError(errors.ERR_VCPR_NOT_VERIFIED,
                              "No ACTIVE VCPR covering (vet, producer) at validation time", 422)

    # OCC (priority 18)
    if expected_version != vfd["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION,
                              "expected_vfd_authorization_version does not match current VFD version",
                              412)

    # --- success side effects ---
    order["status"] = "VALIDATED"
    util.touch(order)

    # WithdrawalPlan, PROVISIONAL
    plan = util.new_entity({
        "feed_order_id": order["id"],
        "provisional_market_date": core.compute_provisional_market_date(
            drug["withdrawal_hours"], group["earliest_market_date"]),
        "withdrawal_window_hours": drug["withdrawal_hours"],
        "status": "PROVISIONAL",
    })
    store.withdrawal_plans[plan["id"]] = plan

    # VFD quota debit + version increment
    vfd["remaining_animal_count"] -= order["animal_count"]
    util.touch(vfd)
    if vfd["remaining_animal_count"] == 0:
        vfd["status"] = "FULLY_USED"
        util.touch(vfd)
    elif vfd["status"] == "ISSUED":
        vfd["status"] = "PARTIALLY_USED"
        util.touch(vfd)

    # Mill pending count
    mill = core.get_feed_mill(order["feed_mill_id"])
    mill["pending_order_count"] = mill.get("pending_order_count", 0) + 1
    util.touch(mill)

    return success_object(order)


@bp.post("/vfd/feed-orders/<oid>/reject")
def reject_feed_order(oid):
    user_id, _ = require_roles("FeedMillOperator")
    order = core.get_feed_order(oid)
    if user_id != order.get("feed_mill_id"):
        raise errors.forbidden("X-User-ID must equal the order's feed_mill_id")
    if order["status"] != "SUBMITTED":
        raise errors.invalid_state("FeedOrder must be SUBMITTED to reject")
    body = util.get_json_body()
    reason = body.get("rejection_reason")
    if reason is None:
        raise errors.invalid_request("rejection_reason is required")
    order["status"] = "REJECTED"
    order["rejection_reason"] = reason
    util.touch(order)
    return success_object(order)


def _compensating_return(order):
    """VALIDATED -> CANCELLED compensation per PRD 2.8."""
    vfd = core.get_vfd(order["vfd_authorization_id"])
    vfd["remaining_animal_count"] += order["animal_count"]
    util.touch(vfd)
    mill = core.get_feed_mill(order["feed_mill_id"])
    mill["pending_order_count"] = max(0, mill.get("pending_order_count", 0) - 1)
    util.touch(mill)


@bp.post("/vfd/feed-orders/<oid>/cancel")
def cancel_feed_order(oid):
    user_id, role = require_roles("Producer", "Inspector")
    order = core.get_feed_order(oid)
    if order["status"] not in ("SUBMITTED", "VALIDATED"):
        raise errors.invalid_state("FeedOrder must be SUBMITTED or VALIDATED to cancel")
    if role == "Producer" and user_id != order.get("producer_id"):
        raise errors.forbidden("X-User-ID must equal order.producer_id")
    was_validated = order["status"] == "VALIDATED"
    order["status"] = "CANCELLED"
    util.touch(order)
    if was_validated:
        _compensating_return(order)
    return success_object(order)


@bp.post("/vfd/feed-orders/<oid>/ship")
def ship_feed_order(oid):
    user_id, _ = require_roles("FeedMillOperator")
    order = core.get_feed_order(oid)
    if user_id != order.get("feed_mill_id"):
        raise errors.forbidden("X-User-ID must equal the order's feed_mill_id")
    if order["status"] != "VALIDATED":
        raise errors.invalid_state("FeedOrder must be VALIDATED to ship")
    vfd = core.get_vfd(order["vfd_authorization_id"])
    # clock strictly before expiration
    if clock.now() >= util.parse_iso(vfd["expiration_date"], "expiration_date"):
        raise errors.ApiError(errors.ERR_VFD_EXPIRED,
                              "Logical clock >= VFD expiration_date", 409)
    # ACK covering (mill, drug)
    ack_ok = any(
        a.get("feed_mill_id") == order["feed_mill_id"]
        and a.get("covers_drug_id") == vfd["drug_id"]
        and a.get("status") == "ACKNOWLEDGED"
        for a in store.distributor_acknowledgments.values()
    )
    if not ack_ok:
        raise errors.ApiError(errors.ERR_ACK_MISSING,
                              "No ACKNOWLEDGED DistributorAcknowledgment covers (feed_mill, drug)", 422)
    body = util.get_json_body()
    tons_shipped = util.require_int(body, "tons_shipped")

    order["status"] = "SHIPPED"
    util.touch(order)

    shipment = util.new_entity({
        "feed_order_id": order["id"],
        "tons_shipped": tons_shipped,
        "shipped_at": util.logical_now_iso(),
        "status": "IN_TRANSIT",
    })
    store.feed_shipments[shipment["id"]] = shipment
    return success_object(shipment)
