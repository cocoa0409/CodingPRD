"""Weight certifications: the two-basis compliance dimension (PRD section 3.8)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, cascade, lookup

certifications_bp = Blueprint("certifications", __name__, url_prefix="/upfit")


@certifications_bp.route("/weight-certifications", methods=["POST"])
def create_certification():
    caller = middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    basis = v.req_enum(payload, "basis", v.CERT_BASIS)
    expected_version = v.req_int(payload, "expected_upfit_order_version")

    order = lookup.upfit_order(upfit_order_id)

    # 7. optimistic concurrency on the order the caller last observed
    if expected_version != order.get("version"):
        raise ApiError(
            "ERR_STALE_UPFIT_ORDER_VERSION",
            "Expected upfit order version %s but the order is at version %s."
            % (expected_version, order.get("version")),
        )

    projection = calc.weight_projection(order, basis)
    model = lookup.governing_chassis_model(order)

    # 50 / 51 / 52. a certification that would document an illegal truck is
    # never persisted; the same three gates as release, in the same order
    if projection["gvw_lb"] > model["gvwr_lb"]:
        raise ApiError(
            "ERR_GVWR_EXCEEDED",
            "Certified GVW %s lb exceeds the model's GVWR %s lb."
            % (projection["gvw_lb"], model["gvwr_lb"]),
        )
    if projection["rear_axle_load_lb"] > model["rear_gawr_lb"]:
        raise ApiError(
            "ERR_REAR_GAWR_EXCEEDED",
            "Certified rear axle load %s lb exceeds the rear GAWR %s lb."
            % (projection["rear_axle_load_lb"], model["rear_gawr_lb"]),
        )
    if projection["front_axle_load_lb"] > model["front_gawr_lb"]:
        raise ApiError(
            "ERR_FRONT_GAWR_EXCEEDED",
            "Certified front axle load %s lb exceeds the front GAWR %s lb."
            % (projection["front_axle_load_lb"], model["front_gawr_lb"]),
        )

    row = db.insert(
        db.weight_certifications,
        {
            "upfit_order_id": order["id"],
            "basis": basis,
            "front_axle_load_lb": projection["front_axle_load_lb"],
            "rear_axle_load_lb": projection["rear_axle_load_lb"],
            "gvw_lb": projection["gvw_lb"],
            "payload_capacity_lb": projection["payload_capacity_lb"],
            "included_component_count": projection["included_component_count"],
            "status": "DRAFT",
            "created_by_user_id": caller.user_id,
            "approved_by_user_id": None,
            "voided_reason": None,
        },
    )

    # drafting supersedes: every earlier row of this basis is voided, DRAFT or
    # APPROVED alike, and an approved one drags the dimension back with it
    cascade.void_certifications(
        order,
        "SUPERSEDED_BY_NEWER_DRAFT",
        basis=basis,
        include_drafts=True,
        exclude_id=row["id"],
    )
    db.touch(order)
    return response.object_response(db.serialize(row), 201)


@certifications_bp.route(
    "/weight-certifications/<weight_certification_id>/approve", methods=["POST"]
)
def approve_certification(weight_certification_id):
    caller = middleware.require(middleware.ROLE_COMPLIANCE_OFFICER)
    cert = lookup.weight_certification(weight_certification_id)

    # 4. nobody certifies their own numbers; this sits above every state check
    middleware.enforce_segregation(
        caller,
        cert.get("created_by_user_id"),
        "The approver may not be the engineer who drafted the certification.",
    )

    order = db.upfit_orders.get(cert["upfit_order_id"])
    compliance = (order or {}).get("compliance_status")

    # 40. the compliance dimension advances in exactly two steps
    if cert["basis"] == "AS_DESIGNED":
        if compliance != "NOT_STARTED":
            raise ApiError(
                "ERR_ORDER_INVALID_STATE",
                "An AS_DESIGNED approval requires compliance_status NOT_STARTED; "
                "this order is %s." % compliance,
            )
    else:
        if compliance != "DESIGN_CERTIFIED":
            raise ApiError(
                "ERR_ORDER_INVALID_STATE",
                "An AS_MEASURED approval requires compliance_status DESIGN_CERTIFIED; "
                "this order is %s." % compliance,
            )
        # a measured basis is meaningless on a bare chassis
        mounted = order.get("body_install_status") == "INSTALLED" or any(
            inst["status"] in calc.PHYSICAL_INSTALL_STATUSES
            for inst in lookup.installations_of(order["id"])
        )
        if not mounted:
            raise ApiError(
                "ERR_ORDER_INVALID_STATE",
                "An AS_MEASURED approval requires a mounted body or at least one "
                "mounted equipment item.",
            )

    # 45. the certification's own from-state
    if cert["status"] != "DRAFT":
        raise ApiError(
            "ERR_CERTIFICATION_INVALID_STATE",
            "Only a DRAFT certification may be approved; this one is %s." % cert["status"],
        )

    cert["status"] = "APPROVED"
    cert["approved_by_user_id"] = caller.user_id
    db.touch(cert)
    order["compliance_status"] = (
        "DESIGN_CERTIFIED" if cert["basis"] == "AS_DESIGNED" else "MEASURED_CERTIFIED"
    )
    db.touch(order)
    return response.object_response(db.serialize(cert), 200)


@certifications_bp.route("/weight-certifications/<weight_certification_id>", methods=["GET"])
def get_certification(weight_certification_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    cert = lookup.weight_certification(weight_certification_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(cert["upfit_order_id"]))
    return response.object_response(db.serialize(cert), 200)


@certifications_bp.route("/weight-certifications", methods=["GET"])
def list_certifications():
    caller = middleware.require(*middleware.ALL_ROLES)
    upfit_order_id = v.filter_str("upfit_order_id")
    basis = v.filter_enum("basis", v.CERT_BASIS)
    status = v.filter_enum("status", v.CERT_STATUS)

    rows = middleware.scope_filter_by_order(caller, list(db.weight_certifications.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)
