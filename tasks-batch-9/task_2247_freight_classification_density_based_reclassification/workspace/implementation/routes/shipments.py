"""Bills of lading, their lines, billing and closure."""
from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import BILLING_STATUSES, CLASS_STATUSES
from errors import fail
from routes import _helpers as h
from services import notices, rating

bp = Blueprint("shipments", __name__)

SHIPMENT_READ_ROLES = (
    "Shipper",
    "PricingAnalyst",
    "ClassificationAuditor",
    "TerminalOperator",
    "DisputeReviewer",
    "FreightInspector",
)
LINE_READ_ROLES = (
    "Shipper",
    "PricingAnalyst",
    "ClassificationAuditor",
    "FreightInspector",
    "TerminalOperator",
    "DisputeReviewer",
)

CLOSABLE_CLASS_STATUSES = ("DECLARED", "CAPTURED", "RECLASSED")


def effective_tariff(pickup_at):
    """{PUBLISHED, SUPERSEDED} with effective_at <= pickup, ranked effective_at DESC, created_at DESC."""
    rows = db.all_rows(
        "tariff_versions",
        lambda t: t["status"] in ("PUBLISHED", "SUPERSEDED") and t["effective_at"] <= pickup_at,
    )
    if not rows:
        return None
    rows.sort(key=lambda t: (t["effective_at"], t["created_at"], t["_seq"]))
    return rows[-1]


def active_program(customer_id):
    rows = db.all_rows(
        "rate_programs",
        lambda p: p["customer_id"] == customer_id and p["status"] == "ACTIVE",
    )
    return rows[-1] if rows else None


# ---------------------------------------------------------------------------
# shipments
# ---------------------------------------------------------------------------
@bp.post("/ltl/shipments")
def create_shipment():
    auth.authenticate(("Shipper",))
    body = validation.body()
    customer = validation.fk(body, "customer_id", "customers", "ERR_CUSTOMER_NOT_FOUND")
    terminal = validation.fk(body, "origin_terminal_id", "terminals", "ERR_TERMINAL_NOT_FOUND")
    if customer is None:
        validation.req_str(body, "customer_id")
    if terminal is None:
        validation.req_str(body, "origin_terminal_id")

    auth.require_owner(customer["id"])

    pro_number = validation.req_str(body, "pro_number")
    pickup_at = validation.req_datetime(body, "pickup_at")
    bol_weight = validation.req_int(body, "bol_declared_total_weight_lb", minimum=1)

    if customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")
    if customer["billing_posture"] == "CREDIT_HOLD":
        fail("ERR_CUSTOMER_CREDIT_HOLD", "The customer account is on CREDIT_HOLD.")

    for other in db.all_rows("shipments"):
        if other["pro_number"] == pro_number:
            fail("ERR_DUPLICATE_PRO_NUMBER", "pro_number %s is already in use." % pro_number)

    program = active_program(customer["id"])
    if program is None:
        fail("ERR_NO_ACTIVE_RATE_PROGRAM", "The customer has no ACTIVE rate program.")

    tariff = effective_tariff(pickup_at)
    if tariff is None:
        fail("ERR_NO_EFFECTIVE_TARIFF", "No tariff version is effective at pickup_at.")

    row = db.insert(
        "shipments",
        {
            "customer_id": customer["id"],
            "origin_terminal_id": terminal["id"],
            "rate_program_id": program["id"],
            "tariff_version_id": tariff["id"],
            "pro_number": pro_number,
            "pickup_at": pickup_at,
            "bol_declared_total_weight_lb": bol_weight,
            "class_status": "DECLARED",
            "billing_status": "UNBILLED",
            "line_count": 0,
            "declared_total_weight_lb": 0,
            "measured_total_weight_lb": None,
            "weight_variance_pct": None,
            "reweigh_required": False,
            "declared_vs_found_class_delta_count": 0,
            "original_charge_cents": 0,
            "assessed_total_cents": 0,
            "open_notice_count": 0,
            "billed_at": None,
        },
    )
    return response.created(serialize.shipment(row))


@bp.get("/ltl/shipments/<shipment_id>")
def read_shipment(shipment_id):
    auth.authenticate(SHIPMENT_READ_ROLES)
    row = validation.path_row("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    auth.require_shipper_owner(row["customer_id"])
    return response.ok(serialize.shipment(row))


@bp.get("/ltl/shipments")
def list_shipments():
    auth.authenticate(SHIPMENT_READ_ROLES)
    rows = h.shipper_scope(db.all_rows("shipments"), "customer_id")
    rows = h.apply_filters(
        rows,
        (
            ("customer_id", "customer_id", None),
            ("origin_terminal_id", "origin_terminal_id", None),
            ("rate_program_id", "rate_program_id", None),
            ("tariff_version_id", "tariff_version_id", None),
            ("class_status", "class_status", CLASS_STATUSES),
            ("billing_status", "billing_status", BILLING_STATUSES),
        ),
    )
    return h.paged(rows, serialize.shipment)


# ---------------------------------------------------------------------------
# shipment lines
# ---------------------------------------------------------------------------
@bp.post("/ltl/shipments/<shipment_id>/lines")
def create_line(shipment_id):
    auth.authenticate(("Shipper",))
    shipment = validation.path_row("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body = validation.body()
    profile = validation.fk(
        body, "commodity_profile_id", "commodity_profiles", "ERR_COMMODITY_PROFILE_NOT_FOUND"
    )
    auth.require_owner(shipment["customer_id"])

    line_no = validation.req_int(body, "line_no", minimum=1)
    if profile is None:
        validation.req_str(body, "commodity_profile_id")
    raw_class = body.get("declared_class_code")
    if raw_class is None or not validation.is_number(raw_class):
        fail("ERR_INVALID_REQUEST", "declared_class_code must be a number.")
    weight = validation.req_int(body, "declared_weight_lb", minimum=1)
    pieces = validation.req_int(body, "pieces", minimum=1)
    raw_length = validation.req_number(body, "declared_length_in")
    raw_width = validation.req_number(body, "declared_width_in")
    raw_height = validation.req_number(body, "declared_height_in")

    declared_class = validation.as_class_code(raw_class, "declared_class_code")
    length = validation.as_dimension(raw_length, "declared_length_in")
    width = validation.as_dimension(raw_width, "declared_width_in")
    height = validation.as_dimension(raw_height, "declared_height_in")

    if shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is CLOSED.")
    if shipment["billing_status"] != "UNBILLED":
        fail("ERR_SHIPMENT_ALREADY_BILLED", "The shipment is already billed.")

    for other in rating.lines_of(shipment["id"]):
        if other["line_no"] == line_no:
            fail("ERR_DUPLICATE_LINE_NO", "line_no %s already exists on this shipment." % line_no)

    if profile["tariff_version_id"] != shipment["tariff_version_id"]:
        fail(
            "ERR_TARIFF_MISMATCH",
            "The commodity profile belongs to a different tariff version than the shipment.",
        )

    cubic_ft, density = rating.cube_and_density(length, width, height, pieces, weight)
    row = db.insert(
        "shipment_lines",
        {
            "shipment_id": shipment["id"],
            "line_no": line_no,
            "commodity_profile_id": profile["id"],
            "declared_class_code": declared_class,
            "declared_weight_lb": weight,
            "pieces": pieces,
            "declared_length_in": length,
            "declared_width_in": width,
            "declared_height_in": height,
            "declared_cubic_ft": cubic_ft,
            "declared_density_pcf": density,
            "measured_weight_lb": None,
            "measured_length_in": None,
            "measured_width_in": None,
            "measured_height_in": None,
            "measured_cubic_ft": None,
            "measured_density_pcf": None,
            "found_class_code": None,
            "effective_class_code": None,
            "classification_source": "BOL_DECLARED",
            "class_floor_applied": False,
            "line_charge_cents": 0,
        },
    )
    rating.recompute_line_class(shipment, row)

    lines = rating.lines_of(shipment["id"])
    shipment["line_count"] = len(lines)
    shipment["declared_total_weight_lb"] = sum(int(line["declared_weight_lb"]) for line in lines)
    db.touch(shipment)

    rating.recompute_line_charges(shipment)
    rating.refresh_delta_count(shipment, lines)
    notices.refresh_draft_notices(shipment)
    return response.created(serialize.shipment_line(row))


@bp.get("/ltl/shipment-lines/<line_id>")
def read_line(line_id):
    auth.authenticate(LINE_READ_ROLES)
    row = validation.path_row("shipment_lines", line_id, "ERR_SHIPMENT_LINE_NOT_FOUND")
    shipment = h.shipment_of(row)
    if shipment is not None:
        auth.require_shipper_owner(shipment["customer_id"])
    return response.ok(serialize.shipment_line(row))


@bp.get("/ltl/shipment-lines")
def list_lines():
    auth.authenticate(LINE_READ_ROLES)
    rows = db.all_rows("shipment_lines")
    if auth.is_shipper():
        me = auth.user_id()
        rows = [
            row
            for row in rows
            if (h.shipment_of(row) or {}).get("customer_id") == me
        ]
    rows = h.apply_filters(
        rows,
        (
            ("shipment_id", "shipment_id", None),
            ("commodity_profile_id", "commodity_profile_id", None),
        ),
    )
    return h.paged(rows, serialize.shipment_line)


# ---------------------------------------------------------------------------
# billing lifecycle
# ---------------------------------------------------------------------------
@bp.post("/ltl/shipments/<shipment_id>/bill")
def bill_shipment(shipment_id):
    auth.authenticate(("PricingAnalyst",))
    shipment = validation.path_row("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    if shipment["billing_status"] != "UNBILLED":
        fail("ERR_SHIPMENT_ALREADY_BILLED", "The shipment is already billed.")

    customer = db.get("customers", shipment["customer_id"])
    if customer is not None and customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")

    if int(shipment["line_count"] or 0) < 1:
        fail("ERR_NO_SHIPMENT_LINES", "The shipment carries no lines.")

    charge = rating.shipment_charge(shipment, "DECLARED")
    shipment["original_charge_cents"] = charge
    shipment["assessed_total_cents"] = charge
    shipment["billing_status"] = "BILLED"
    shipment["billed_at"] = clock.now()
    db.touch(shipment)
    return response.ok(serialize.shipment(shipment))


@bp.post("/ltl/shipments/<shipment_id>/close")
def close_shipment(shipment_id):
    auth.authenticate(("PricingAnalyst",))
    shipment = validation.path_row("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")

    if shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is already CLOSED.")
    if shipment["billing_status"] == "UNBILLED":
        fail("ERR_SHIPMENT_NOT_BILLED", "The shipment has not been billed yet.")
    if shipment["class_status"] not in CLOSABLE_CLASS_STATUSES:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "class_status %s cannot be confirmed." % shipment["class_status"],
        )
    if int(shipment["open_notice_count"] or 0) > 0:
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment still carries an open notice.")

    shipment["billing_status"] = "CLOSED"
    shipment["class_status"] = "CLASS_CONFIRMED"
    db.touch(shipment)
    return response.ok(serialize.shipment(shipment))
