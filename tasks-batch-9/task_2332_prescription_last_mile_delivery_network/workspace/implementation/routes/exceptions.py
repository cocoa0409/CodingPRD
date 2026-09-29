"""Exception cases: hand-opened intake, review, the three-branch fork, and closure."""

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from constants import DISPOSITIONS, EXCEPTION_TYPES
from db import db, new_row, touch
from errors import api_error
from middleware import ROLE_OPS, ROLE_PHARMACY, require_roles
from services import cascades
from services import derive
from services import money
from services import reservations
from services import windows as window_service

bp = Blueprint("exceptions", __name__)


@bp.post("/exception-cases")
@require_roles(ROLE_OPS, ROLE_PHARMACY)
def open_case():
    body = v.json_body()
    delivery_id = v.string_field(body, "delivery_id")
    exception_type = v.enum_field(body, "exception_type", EXCEPTION_TYPES)
    notes = v.string_field(body, "notes", required=False, default=None, max_len=1000)

    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise api_error("ERR_DELIVERY_NOT_FOUND")

    if delivery["custody_status"] == "CANCELLED":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "A cancelled delivery has nothing left to except.")

    case = new_row()
    case["delivery_id"] = delivery["id"]
    case["reship_delivery_id"] = None
    case["exception_type"] = exception_type
    case["status"] = "OPEN"
    case["opened_by_ops_user_id"] = (middleware.actor_id()
                                    if middleware.actor_role() == ROLE_OPS else None)
    case["adjudicated_by_ops_user_id"] = None
    case["disposition"] = None
    case["credit_cents"] = 0
    case["notes"] = notes
    db.exception_cases[case["id"]] = case
    return response.single(serializers.exception_case(case), 201)


def _load_case(case_id):
    case = db.exception_cases.get(case_id)
    if case is None:
        raise api_error("ERR_EXCEPTION_CASE_NOT_FOUND")
    return case


@bp.post("/exception-cases/<case_id>/start-review")
@require_roles(ROLE_OPS)
def start_review(case_id):
    case = _load_case(case_id)
    if case["status"] != "OPEN":
        raise api_error("ERR_INVALID_EXCEPTION_STATE",
                        "Only an OPEN case may be taken up for adjudication.")
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return response.single(serializers.exception_case(case), 200)


@bp.post("/exception-cases/<case_id>/close")
@require_roles(ROLE_OPS)
def close_case(case_id):
    case = _load_case(case_id)
    if case["status"] not in {"RESHIP_AUTHORIZED", "CREDIT_ISSUED", "DENIED"}:
        raise api_error("ERR_INVALID_EXCEPTION_STATE",
                        "Only an adjudicated case may be closed.")
    case["status"] = "CLOSED"
    touch(case)
    return response.single(serializers.exception_case(case), 200)


@bp.post("/exception-cases/<case_id>/adjudicate")
@require_roles(ROLE_OPS)
def adjudicate(case_id):
    case = _load_case(case_id)
    delivery = db.deliveries.get(case["delivery_id"])
    order = db.pharmacy_orders.get(delivery["order_id"])
    current_window = db.delivery_windows.get(delivery["window_id"])

    body = v.json_body()
    disposition = v.enum_field(body, "disposition", DISPOSITIONS)
    expected_version = v.int_field(body, "expected_delivery_version", minimum=0)
    reship_window_id = v.string_field(body, "reship_window_id", required=False, default=None)
    notes = v.string_field(body, "notes", required=False, default=None, max_len=1000)

    reship_window = None
    if reship_window_id is not None:
        reship_window = db.delivery_windows.get(reship_window_id)
        if reship_window is None:
            raise api_error("ERR_WINDOW_NOT_FOUND")

    # Rung 11: segregation of duties inside the NetworkOps role.
    actor = middleware.actor_id()
    if case["opened_by_ops_user_id"] and case["opened_by_ops_user_id"] == actor:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "The operator who opened this case may not adjudicate it.")
    for assignment in db.courier_assignments.values():
        if (assignment["delivery_id"] == delivery["id"]
                and assignment["revoked_by_ops_user_id"] == actor):
            raise api_error("ERR_SEGREGATION_OF_DUTIES",
                            "An operator who revoked a courier off this delivery may "
                            "not adjudicate it.")

    if delivery["settlement_status"] != "PROVISIONAL":
        raise api_error("ERR_INVALID_SETTLEMENT_STATE",
                        "Only a PROVISIONAL delivery may be adjudicated.")
    if case["status"] != "UNDER_REVIEW":
        raise api_error("ERR_INVALID_EXCEPTION_STATE",
                        "Only an UNDER_REVIEW case may be adjudicated.")

    grant = None
    values = None
    if disposition == "RESHIP" and reship_window is not None:
        grant = money.select_grant(order, reship_window)

    if expected_version != delivery["version"]:
        raise api_error("ERR_STALE_DELIVERY_VERSION",
                        "The delivery has moved since it was last read.")

    if disposition == "RESHIP":
        if delivery["custody_status"] not in {"RETURN_PENDING", "RETURNED"}:
            raise api_error("ERR_INVALID_CUSTODY_STATE",
                            "A reship requires the bag to be pending return or returned.")
        if reship_window is not None:
            zone = reservations.zone_of(reship_window)
            if reship_window["zone_id"] != current_window["zone_id"]:
                raise api_error("ERR_ZONE_MISMATCH",
                                "The reship window must sit in the original window's zone.")
            reservations.assert_mode_match(current_window, reship_window)
            reservations.assert_no_duplicate_active(order,
                                                    exclude_delivery_id=delivery["id"])
            if reship_window["status"] != "OPEN" or derive.available_slots(reship_window) < 1:
                raise api_error("ERR_WINDOW_FULL",
                                "The reship window has no available slots.")
            values = money.plan_allocation(order, reship_window, zone,
                                           delivery["handling_class"], "PROVISIONAL",
                                           None, grant)

        already_reshipped = any(d["reship_of_delivery_id"] == delivery["id"]
                                for d in db.deliveries.values())
        if reship_window is None or already_reshipped:
            raise api_error("ERR_OVERRIDE_ADJUDICATION_CONFLICT",
                            "A reship requires a reship_window_id and only one reship "
                            "may be spawned per delivery.")

        reship = reservations.new_delivery(order, reship_window,
                                          reship_of_delivery_id=delivery["id"])
        window_service.occupancy_changed(reship_window)
        cascades.commit_allocation(reship, values)
        case["reship_delivery_id"] = reship["id"]
        case["status"] = "RESHIP_AUTHORIZED"
        case["credit_cents"] = 0
    elif disposition == "CREDIT":
        allocation = derive.active_allocation(delivery)
        credit = allocation["fee_subtotal_cents"] if allocation else 0
        cascades.close_out_allocation(delivery, "VOIDED")
        delivery["settlement_status"] = "WAIVED"
        delivery["fee_subtotal_cents"] = 0
        case["credit_cents"] = credit
        case["status"] = "CREDIT_ISSUED"
    else:  # DENY
        case["credit_cents"] = 0
        case["status"] = "DENIED"

    case["disposition"] = disposition
    case["adjudicated_by_ops_user_id"] = actor
    if notes is not None:
        case["notes"] = notes
    touch(case)
    touch(delivery)
    return response.single(serializers.exception_case(case), 200)
