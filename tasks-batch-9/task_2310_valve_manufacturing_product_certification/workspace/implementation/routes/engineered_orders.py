"""Engineered-to-order programmes: review, pricing and documentation (PRD 3.8)."""

from flask import Blueprint

import calcs
import domain
from auth import ANY, require_action_role, require_roles
from calcs import dec
from db import clock_iso, db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    DOC_TYPES,
    SPECIAL_SERVICES,
    TORQUE_SOURCES,
    filter_value,
    get_body,
    get_bool,
    get_enum,
    get_enum_array,
    get_int,
    get_number,
    get_string,
    paginate,
    parse_pagination,
)

bp = Blueprint("engineered_orders", __name__)

REVIEW_ACTION_ROLES = {
    "SUBMIT_REVIEW": ["ProductEngineer"],
    "REQUEST_CLARIFICATION": ["QualityManager"],
    "APPROVE": ["QualityManager"],
    "REJECT": ["QualityManager"],
}
LIFECYCLE_ACTION_ROLES = {
    "RELEASE_TO_PRODUCTION": ["ProductEngineer"],
    "RESUME": ["ProductEngineer"],
    "CANCEL": ["ProductEngineer"],
    "CLOSE": ["QualityManager"],
    "ISSUE_DOC_PACKAGE": ["QualityManager"],
    "VOID_DOC_PACKAGE": ["QualityManager"],
}


@bp.post("/valve-mfg/engineered-orders")
def create_order():
    require_roles(["ProductEngineer"])
    body = get_body()
    order_code = get_string(body, "order_code")
    model_id = get_string(body, "model_id")
    ordered_qty = get_int(body, "ordered_qty", minimum=1)
    unit_price_cents = get_int(body, "unit_price_cents", minimum=1)
    customer_credit_limit_cents = get_int(body, "customer_credit_limit_cents", minimum=0)
    datasheet_break_torque_nm = get_number(
        body,
        "datasheet_break_torque_nm",
        required=False,
        default=None,
        exclusive_minimum=0,
    )
    datasheet_torque_source = get_enum(
        body, "datasheet_torque_source", TORQUE_SOURCES, required=False, default=None
    )
    requested_special_services = get_enum_array(
        body, "requested_special_services", SPECIAL_SERVICES, required=False, default=[]
    )
    expedite_requested = get_bool(
        body, "expedite_requested", required=False, default=False
    )

    domain.find_model(model_id)

    for row in db.orders.values():
        if row["order_code"] == order_code:
            raise api_error(
                "ERR_DUPLICATE_CODE", "order_code '%s' is already in use" % order_code
            )

    row = new_row(
        {
            "order_code": order_code,
            "model_id": model_id,
            "ordered_qty": ordered_qty,
            "unit_price_cents": unit_price_cents,
            "customer_credit_limit_cents": customer_credit_limit_cents,
            "datasheet_break_torque_nm": datasheet_break_torque_nm,
            "datasheet_torque_source": datasheet_torque_source,
            "requested_special_services": requested_special_services,
            "expedite_requested": expedite_requested,
            "datasheet_revision_no": 1,
            "clarification_round_count": 0,
            "status": "DRAFT",
            "pinned_model_id": None,
            "pinned_model_spec_revision": None,
            "gross_quoted_cents": None,
            "net_billable_cents": None,
            "credit_issued_cents": 0,
            "documents": [],
            "doc_package_status": "ASSEMBLING",
            "held_reason": None,
        }
    )
    db.orders[row["id"]] = row
    return object_response(domain.serialize_order(row), 201)


@bp.get("/valve-mfg/engineered-orders")
def list_orders():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.orders.values()))
    for param in ("status", "model_id", "pinned_model_id", "doc_package_status"):
        value = filter_value(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_order(r) for r in page], limit, offset, total)


@bp.get("/valve-mfg/engineered-orders/<order_id>")
def get_order(order_id):
    require_roles(ANY)
    row = domain.find_order(order_id)
    return object_response(domain.serialize_order(row))


@bp.post("/valve-mfg/engineered-orders/<order_id>/datasheet-revisions")
def datasheet_revisions(order_id):
    require_roles(["ProductEngineer"])
    body = get_body()
    torque = get_number(body, "datasheet_break_torque_nm", exclusive_minimum=0)
    source = get_enum(body, "datasheet_torque_source", TORQUE_SOURCES)
    expected_version = get_int(body, "expected_engineered_order_version", minimum=0)

    order = domain.find_order(order_id)

    if order["status"] != "CLARIFICATION_REQUESTED":
        raise api_error(
            "ERR_STATE_INVALID",
            "a datasheet revision requires status CLARIFICATION_REQUESTED (current: %s)"
            % order["status"],
        )
    if expected_version != order["version"]:
        raise api_error(
            "ERR_STALE_ORDER_VERSION",
            "expected_engineered_order_version %s does not match the order's current version %s"
            % (expected_version, order["version"]),
        )

    order["datasheet_break_torque_nm"] = torque
    order["datasheet_torque_source"] = source
    order["datasheet_revision_no"] = order.get("datasheet_revision_no", 1) + 1
    order["status"] = "UNDER_REVIEW"
    touch(order)
    return object_response(domain.serialize_order(order))


@bp.post("/valve-mfg/engineered-orders/<order_id>/review-actions")
def review_actions(order_id):
    _user_id, role = require_roles(["ProductEngineer", "QualityManager"])
    body = get_body()
    action = get_enum(body, "action", list(REVIEW_ACTION_ROLES.keys()))
    require_action_role(role, action, REVIEW_ACTION_ROLES)

    order = domain.find_order(order_id)
    model = db.valve_models.get(order["model_id"])
    requested = order.get("requested_special_services") or []

    if action == "SUBMIT_REVIEW":
        if order["status"] != "DRAFT":
            raise api_error(
                "ERR_STATE_INVALID",
                "SUBMIT_REVIEW requires status DRAFT (current: %s)" % order["status"],
            )
        if order.get("datasheet_break_torque_nm") is None:
            raise api_error(
                "ERR_STATE_INVALID",
                "datasheet_break_torque_nm must be present before review",
            )
        allowed = (model or {}).get("required_special_services") or []
        missing = [s for s in requested if s not in allowed]
        if missing:
            raise api_error(
                "ERR_SPECIAL_SERVICE_NOT_QUALIFIED",
                "the design does not offer: %s" % ", ".join(missing),
            )
        order["status"] = "UNDER_REVIEW"
        touch(order)

    elif action == "REQUEST_CLARIFICATION":
        if order["status"] != "UNDER_REVIEW":
            raise api_error(
                "ERR_STATE_INVALID",
                "REQUEST_CLARIFICATION requires status UNDER_REVIEW (current: %s)"
                % order["status"],
            )
        if order.get("clarification_round_count", 0) >= calcs.MAX_CLARIFICATION_ROUNDS:
            raise api_error(
                "ERR_CLARIFICATION_ROUNDS_EXHAUSTED",
                "the order has already used its %s clarification rounds"
                % calcs.MAX_CLARIFICATION_ROUNDS,
            )
        order["clarification_round_count"] = order.get("clarification_round_count", 0) + 1
        order["status"] = "CLARIFICATION_REQUESTED"
        touch(order)

    elif action == "APPROVE":
        if order["status"] != "UNDER_REVIEW":
            raise api_error(
                "ERR_STATE_INVALID",
                "APPROVE requires status UNDER_REVIEW (current: %s)" % order["status"],
            )
        if model is None or model["status"] != "RELEASED":
            raise api_error(
                "ERR_MODEL_NOT_RELEASED", "the base design is not RELEASED"
            )
        qualified = domain.model_qualified_special_services(model)
        missing = [s for s in requested if s not in qualified]
        if missing:
            raise api_error(
                "ERR_SPECIAL_SERVICE_NOT_QUALIFIED",
                "the design has no valid type test for: %s" % ", ".join(missing),
            )
        gross = calcs.eto_order_price_cents(
            order["unit_price_cents"],
            order["ordered_qty"],
            requested,
            order.get("expedite_requested", False),
        )
        order["status"] = "APPROVED"
        order["pinned_model_id"] = model["id"]
        order["pinned_model_spec_revision"] = model["spec_revision"]
        order["gross_quoted_cents"] = gross
        order["net_billable_cents"] = gross
        order["credit_issued_cents"] = 0
        touch(order)

    else:  # REJECT
        if order["status"] not in ("UNDER_REVIEW", "CLARIFICATION_REQUESTED"):
            raise api_error(
                "ERR_STATE_INVALID",
                "REJECT requires status UNDER_REVIEW or CLARIFICATION_REQUESTED "
                "(current: %s)" % order["status"],
            )
        order["status"] = "REJECTED"
        touch(order)

    return object_response(domain.serialize_order(order))


@bp.post("/valve-mfg/engineered-orders/<order_id>/lifecycle-actions")
def lifecycle_actions(order_id):
    _user_id, role = require_roles(["ProductEngineer", "QualityManager"])
    body = get_body()
    action = get_enum(body, "action", list(LIFECYCLE_ACTION_ROLES.keys()))
    require_action_role(role, action, LIFECYCLE_ACTION_ROLES)

    order = domain.find_order(order_id)

    if action == "RELEASE_TO_PRODUCTION":
        if order["status"] != "APPROVED":
            raise api_error(
                "ERR_STATE_INVALID",
                "RELEASE_TO_PRODUCTION requires status APPROVED (current: %s)"
                % order["status"],
            )
        if domain.order_spec_stale(order):
            raise api_error(
                "ERR_PINNED_SPEC_STALE",
                "the pinned design has moved on since approval",
            )
        if int(order["gross_quoted_cents"] or 0) > int(
            order["customer_credit_limit_cents"]
        ):
            raise api_error(
                "ERR_CREDIT_LIMIT_EXCEEDED",
                "the quoted total exceeds the customer's credit limit",
            )
        order["status"] = "IN_PRODUCTION"
        order["held_reason"] = None
        touch(order)

    elif action == "RESUME":
        if order["status"] != "HELD":
            raise api_error(
                "ERR_STATE_INVALID",
                "RESUME requires status HELD (current: %s)" % order["status"],
            )
        for unit in sort_rows(domain.units_of_order(order["id"])):
            domain.refresh_unit(unit)
            if unit.get("cert_status") == "DECERTIFIED":
                raise api_error(
                    "ERR_STATE_INVALID",
                    "a unit of this order is still DECERTIFIED",
                )
        for unit in sort_rows(domain.units_of_order(order["id"])):
            lic = db.licenses.get(unit.get("monogram_license_id") or "")
            if lic is None:
                continue
            domain.refresh_license(lic)
            if domain.license_posture(lic) == "FROZEN":
                raise api_error(
                    "ERR_LICENSE_POSTURE_BLOCKED",
                    "a governing monogram license is FROZEN",
                )
        order["status"] = "IN_PRODUCTION"
        order["held_reason"] = None
        touch(order)

    elif action == "CLOSE":
        if order["status"] != "IN_PRODUCTION":
            raise api_error(
                "ERR_STATE_INVALID",
                "CLOSE requires status IN_PRODUCTION (current: %s)" % order["status"],
            )
        if order["doc_package_status"] != "ISSUED":
            raise api_error(
                "ERR_DOC_PACKAGE_INCOMPLETE",
                "the documentation package is %s, not ISSUED"
                % order["doc_package_status"],
            )
        if domain.order_certified_unit_count(order) < order["ordered_qty"]:
            raise api_error(
                "ERR_ORDER_UNITS_INCOMPLETE",
                "fewer certified units than the ordered quantity",
            )
        order["status"] = "CLOSED"
        touch(order)

    elif action == "CANCEL":
        if order["status"] not in ("APPROVED", "IN_PRODUCTION", "HELD"):
            raise api_error(
                "ERR_STATE_INVALID",
                "CANCEL is not available from status %s" % order["status"],
            )
        gross = int(order.get("gross_quoted_cents") or 0)
        net, credit = calcs.cancellation_split(gross, order["status"])
        order["net_billable_cents"] = net
        order["credit_issued_cents"] = credit
        order["status"] = "CANCELLED"
        if order["doc_package_status"] == "ISSUED":
            order["doc_package_status"] = "VOIDED"
            order["held_reason"] = "DOC_PACKAGE_VOIDED"
        touch(order)

    elif action == "ISSUE_DOC_PACKAGE":
        if order["status"] not in ("IN_PRODUCTION", "HELD"):
            raise api_error(
                "ERR_STATE_INVALID",
                "ISSUE_DOC_PACKAGE requires status IN_PRODUCTION or HELD (current: %s)"
                % order["status"],
            )
        if order["doc_package_status"] != "COMPLETE":
            raise api_error(
                "ERR_DOC_PACKAGE_INCOMPLETE",
                "the documentation package is %s, not COMPLETE"
                % order["doc_package_status"],
            )
        if domain.order_certified_unit_count(order) < order["ordered_qty"]:
            raise api_error(
                "ERR_ORDER_UNITS_INCOMPLETE",
                "fewer certified units than the ordered quantity",
            )
        order["doc_package_status"] = "ISSUED"
        touch(order)

    else:  # VOID_DOC_PACKAGE
        if order["doc_package_status"] != "ISSUED":
            raise api_error(
                "ERR_STATE_INVALID",
                "VOID_DOC_PACKAGE requires doc_package_status ISSUED (current: %s)"
                % order["doc_package_status"],
            )
        order["doc_package_status"] = "VOIDED"
        order["held_reason"] = "DOC_PACKAGE_VOIDED"
        if order["status"] == "IN_PRODUCTION":
            order["status"] = "HELD"
        touch(order)

    return object_response(domain.serialize_order(order))


@bp.post("/valve-mfg/engineered-orders/<order_id>/documents")
def append_document(order_id):
    require_roles(["QualityManager"])
    body = get_body()
    doc_type = get_enum(body, "doc_type", DOC_TYPES)
    doc_ref = get_string(body, "doc_ref")

    order = domain.find_order(order_id)

    order["documents"] = list(order.get("documents") or []) + [
        {"doc_type": doc_type, "doc_ref": doc_ref, "added_at": clock_iso()}
    ]
    if order["doc_package_status"] == "VOIDED":
        order["doc_package_status"] = "ASSEMBLING"
    completeness = domain.order_documentation_completeness(order)
    if order["doc_package_status"] == "ASSEMBLING" and dec(completeness) == dec("100"):
        order["doc_package_status"] = "COMPLETE"
    touch(order)
    return object_response(domain.serialize_order(order))
