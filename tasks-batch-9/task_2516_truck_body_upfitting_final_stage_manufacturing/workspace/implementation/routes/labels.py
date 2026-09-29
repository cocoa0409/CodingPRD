"""Compliance labels: the immutable terminal step of the compliance dimension
(PRD section 3.8).  A label row carries only id and created_at — no updated_at
and no version — and a correction is a new row plus a voided predecessor."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, lookup

labels_bp = Blueprint("labels", __name__, url_prefix="/upfit")


@labels_bp.route("/compliance-labels", methods=["POST"])
def create_compliance_label():
    caller = middleware.require(middleware.ROLE_COMPLIANCE_OFFICER)
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    weight_certification_id = v.req_str(payload, "weight_certification_id")
    supersedes_label_id = v.opt_str(payload, "supersedes_label_id")

    order = lookup.upfit_order(upfit_order_id)
    cert = lookup.weight_certification(weight_certification_id)
    predecessor = None
    if supersedes_label_id is not None:
        predecessor = lookup.compliance_label(supersedes_label_id)

    # 4. the issuer may not be the officer who approved the numbers
    middleware.enforce_segregation(
        caller,
        cert.get("approved_by_user_id"),
        "The label issuer may not be the officer who approved the certification.",
    )

    # 40. issuance window
    if order["compliance_status"] not in ("MEASURED_CERTIFIED", "LABELED"):
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Labels are issued at MEASURED_CERTIFIED or LABELED; this order is %s."
            % order["compliance_status"],
        )

    # 48. a correction must name a label that is still standing
    if predecessor is not None and predecessor.get("voided_at") is not None:
        raise ApiError(
            "ERR_LABEL_ALREADY_SUPERSEDED",
            "Label %s has already been superseded." % supersedes_label_id,
        )

    # 54. only a scale-verified basis may be labeled
    if cert["basis"] != "AS_MEASURED":
        raise ApiError(
            "ERR_MEASURED_CERTIFICATION_REQUIRED",
            "A compliance label may only cite an AS_MEASURED certification.",
        )

    # 90. the cited certification must belong to this order
    if cert["upfit_order_id"] != order["id"]:
        raise ApiError(
            "ERR_CERTIFICATION_ORDER_MISMATCH",
            "Certification %s belongs to a different upfit order." % weight_certification_id,
        )

    # 91. and it must be approved
    if cert["status"] != "APPROVED":
        raise ApiError(
            "ERR_CERTIFICATION_NOT_APPROVED",
            "Certification %s is %s, not APPROVED." % (weight_certification_id, cert["status"]),
        )

    # 92. at most one standing label per order
    active = [l for l in lookup.labels_of(order["id"]) if l.get("voided_at") is None]
    if active and predecessor is None:
        raise ApiError(
            "ERR_LABEL_ALREADY_ACTIVE",
            "This order already carries a standing label; name it in supersedes_label_id.",
        )

    label_type, responsible_party = calc.label_responsibility(order)
    model = lookup.governing_chassis_model(order) or {}

    if predecessor is not None:
        predecessor["voided_at"] = db.clock_now_iso()

    row = db.insert(
        db.compliance_labels,
        {
            "upfit_order_id": order["id"],
            "weight_certification_id": weight_certification_id,
            "supersedes_label_id": supersedes_label_id,
            "label_type": label_type,
            "responsible_party": responsible_party,
            "certified_gvwr_lb": model.get("gvwr_lb"),
            "certified_front_gawr_lb": model.get("front_gawr_lb"),
            "certified_rear_gawr_lb": model.get("rear_gawr_lb"),
            "certified_payload_lb": cert.get("payload_capacity_lb"),
            "issued_by_user_id": caller.user_id,
            "voided_at": None,
        },
        common_fields=False,
    )
    if order["compliance_status"] == "MEASURED_CERTIFIED":
        order["compliance_status"] = "LABELED"
    db.touch(order)
    return response.object_response(db.serialize(row), 201)


@labels_bp.route("/compliance-labels/<compliance_label_id>", methods=["GET"])
def get_compliance_label(compliance_label_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    label = lookup.compliance_label(compliance_label_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(label["upfit_order_id"]))
    return response.object_response(db.serialize(label), 200)


@labels_bp.route("/compliance-labels", methods=["GET"])
def list_compliance_labels():
    caller = middleware.require(*middleware.ALL_ROLES)
    upfit_order_id = v.filter_str("upfit_order_id")
    weight_certification_id = v.filter_str("weight_certification_id")
    supersedes_label_id = v.filter_str("supersedes_label_id")
    label_type = v.filter_enum("label_type", v.LABEL_TYPE)
    responsible_party = v.filter_enum("responsible_party", v.RESPONSIBLE_PARTY)

    rows = middleware.scope_filter_by_order(caller, list(db.compliance_labels.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if weight_certification_id is not None:
        rows = [r for r in rows if r["weight_certification_id"] == weight_certification_id]
    if supersedes_label_id is not None:
        rows = [r for r in rows if r["supersedes_label_id"] == supersedes_label_id]
    if label_type is not None:
        rows = [r for r in rows if r["label_type"] == label_type]
    if responsible_party is not None:
        rows = [r for r in rows if r["responsible_party"] == responsible_party]
    return response.paginate(rows)
