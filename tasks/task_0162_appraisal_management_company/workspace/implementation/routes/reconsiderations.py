"""Reconsideration of Value endpoints: create, get, start-review, resolve."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import calculations as calc
from services import domain, serialize, validate

bp = Blueprint("reconsiderations", __name__)


# ---------------------------------------------------------------------------
# POST /amc/orders/{id}/reconsiderations  — open an ROV on a delivered order
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/reconsiderations", methods=["POST"])
def create_rov(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"LenderUser", "AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")

    data = validate.body()

    # State legality (priority 7): ROV opened on a delivered order. The order's
    # appraised_value_cents is set at DELIVERED; it must be present.
    if order["status"] not in ("DELIVERED", "COMPLETED") or order.get("appraised_value_cents") is None:
        raise errors.invalid_state("Order is not delivered.")

    # Field-shape (priority 14).
    requested = data.get("requested_value_cents")
    if requested is None:
        raise errors.invalid_request("requested_value_cents is required.")
    if isinstance(requested, bool) or not isinstance(requested, int):
        raise errors.invalid_request("requested_value_cents must be an integer.")
    if requested <= 0:
        raise errors.invalid_request("requested_value_cents must be > 0.")

    delta_pct, requires_second = calc.rov_value_delta(
        requested, order["appraised_value_cents"])

    rov = {
        "order_id": oid,
        "requested_value_cents": requested,
        "value_delta_pct": delta_pct,
        "requires_second_review": requires_second,
        "resolution": "REQUESTED",
        "new_value_cents": None,
    }
    db.stamp_create(rov)
    db.reconsiderations[rov["id"]] = rov
    return response.ok_object(serialize.public(rov), 201)


# ---------------------------------------------------------------------------
# GET /amc/reconsiderations/{id}
# ---------------------------------------------------------------------------
@bp.route("/amc/reconsiderations/<rid>", methods=["GET"])
def get_rov(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    rov = db.reconsiderations.get(rid)
    if rov is None:
        raise errors.not_found("Reconsideration not found.")
    return response.ok_object(serialize.public(rov), 200)


# ---------------------------------------------------------------------------
# POST /amc/reconsiderations/{id}/start-review
# ---------------------------------------------------------------------------
@bp.route("/amc/reconsiderations/<rid>/start-review", methods=["POST"])
def start_review(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    rov = db.reconsiderations.get(rid)
    if rov is None:
        raise errors.not_found("Reconsideration not found.")

    # State legality (priority 7): REQUESTED -> UNDER_REVIEW, order DELIVERED.
    if rov["resolution"] != "REQUESTED":
        raise errors.invalid_state("Reconsideration is not REQUESTED.")
    order = db.orders.get(rov["order_id"])
    if order is None or order["status"] != "DELIVERED":
        raise errors.invalid_state("Owning order is not DELIVERED.")

    rov["resolution"] = "UNDER_REVIEW"
    db.touch(rov)
    return response.ok_object(serialize.public(rov), 200)


# ---------------------------------------------------------------------------
# POST /amc/reconsiderations/{id}/resolve
# ---------------------------------------------------------------------------
@bp.route("/amc/reconsiderations/<rid>/resolve", methods=["POST"])
def resolve(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    rov = db.reconsiderations.get(rid)
    if rov is None:
        raise errors.not_found("Reconsideration not found.")

    data = validate.body()

    # State legality (priority 7).
    if rov["resolution"] != "UNDER_REVIEW":
        raise errors.invalid_state("Reconsideration is not UNDER_REVIEW.")

    order = db.orders.get(rov["order_id"])
    new_value = data.get("new_value_cents")

    # Determine fork: VALUE_CHANGED (new_value present > 0) vs VALUE_UPHELD.
    if new_value is not None:
        # Field-shape on new_value (priority 14).
        if isinstance(new_value, bool) or not isinstance(new_value, int):
            raise errors.invalid_request("new_value_cents must be an integer.")
        if new_value <= 0:
            raise errors.invalid_request("new_value_cents must be > 0.")

        # Second-review requirement (priority 12).
        if rov["requires_second_review"]:
            if not _has_passing_second_review(order):
                raise errors.err(errors.ERR_SECOND_REVIEW_REQUIRED,
                                 "A passing post-delivery compliance review is required.")

        rov["resolution"] = "VALUE_CHANGED"
        rov["new_value_cents"] = new_value
        db.touch(rov)

        # Cascade: Order.appraised_value_cents = new_value; FeeSplit recompute.
        if order is not None:
            order["appraised_value_cents"] = new_value
            db.touch(order)
            fee_split = domain.fee_split_for_order(order["id"])
            if fee_split is not None:
                domain.recompute_fee_split(order, fee_split, fee_split["variant"])
                db.touch(fee_split)
    else:
        # VALUE_UPHELD: no value change, no fee-split recompute.
        rov["resolution"] = "VALUE_UPHELD"
        db.touch(rov)

    return response.ok_object(serialize.public(rov), 200)


def _has_passing_second_review(order):
    """A second post-delivery ComplianceReview on the order's report is PASS or
    CONDITIONAL. We count any review beyond the first that delivered the order."""
    if order is None:
        return False
    oid = order["id"]
    # Reports for this order's assignments.
    report_ids = set()
    for a in db.assignments.values():
        if a.get("order_id") == oid:
            for rpt in db.reports.values():
                if rpt.get("assignment_id") == a["id"]:
                    report_ids.add(rpt["id"])
    reviews = [c for c in db.compliance_reviews.values() if c.get("report_id") in report_ids]
    # The first PASS/CONDITIONAL review delivered the order; a *second* such
    # passing review is what unlocks VALUE_CHANGED. Require >= 2 PASS/CONDITIONAL.
    passing = [c for c in reviews if c["outcome"] in ("PASS", "CONDITIONAL")]
    return len(passing) >= 2
