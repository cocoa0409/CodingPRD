"""FrameLine endpoints (PRD §3.2, §3.3, §2.8)."""
from flask import Blueprint

import errors
import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import calc, domain
from routes.orders import find_order_or_404, assert_customer_owns_order

bp = Blueprint("frame_lines", __name__)

GLASS_TYPES = {"REGULAR", "CONSERVATION", "MUSEUM"}
MOUNTING_TYPES = {"NONE", "PLAIN", "DRY_MOUNT", "CONSERVATION_HINGE"}


def _find_line_or_404(line_id):
    l = db.frame_lines.get(line_id)
    if l is None:
        errors.raise_err(errors.ERR_LINE_NOT_FOUND, "FrameLine not found")
    return l


# ---------------------------------------------------------------------------
# ADD line (OCC-guarded on order version)
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/frame-lines", methods=["POST"])
def add_line(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner",))
    o = find_order_or_404(order_id)
    body = validate.get_json_body()

    # priority 4: request well-formedness (required fields + types) BEFORE OCC?
    # Per PRD §2.6 the OCC check (priority 5) comes AFTER body well-formedness
    # (priority 4). So validate body first, then OCC, then state.
    expected_version = validate.require(body, "expected_order_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "expected_order_version must be an integer")

    artwork_label = validate.as_string(validate.require(body, "artwork_label"), "artwork_label")
    nominal_w = validate.as_positive_number(
        validate.require(body, "nominal_width_in"), "nominal_width_in"
    )
    nominal_h = validate.as_positive_number(
        validate.require(body, "nominal_height_in"), "nominal_height_in"
    )
    molding_rate = validate.as_nonneg_number(
        validate.require(body, "molding_rate_per_ui"), "molding_rate_per_ui"
    )

    mat_border = validate.opt(body, "mat_border_in", 2)
    validate.as_nonneg_number(mat_border, "mat_border_in")
    mat_layers = validate.opt(body, "mat_layers", 1)
    if isinstance(mat_layers, bool) or not isinstance(mat_layers, int) or mat_layers < 1:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "mat_layers must be an integer >= 1")
    glass_type = validate.opt(body, "glass_type", "REGULAR")
    validate.as_enum(glass_type, "glass_type", GLASS_TYPES)
    mounting_type = validate.opt(body, "mounting_type", "NONE")
    validate.as_enum(mounting_type, "mounting_type", MOUNTING_TYPES)
    conservation = validate.opt(body, "conservation_package", False)
    validate.as_bool(conservation, "conservation_package")
    is_fragile = validate.opt(body, "is_fragile", False)
    validate.as_bool(is_fragile, "is_fragile")

    # priority 5: OCC
    if expected_version != o["version"]:
        errors.raise_err(errors.ERR_STALE_ORDER_VERSION, "Stale order version")

    # priority 6: order must be editable (INTAKE or QUOTED)
    if o["production_status"] not in ("INTAKE", "QUOTED"):
        errors.raise_err(errors.ERR_ORDER_NOT_EDITABLE, "Order not editable")

    l = {
        "order_id": order_id,
        "artwork_label": artwork_label,
        "nominal_width_in": nominal_w,
        "nominal_height_in": nominal_h,
        "measured_width_in": None,
        "measured_height_in": None,
        "mat_border_in": mat_border,
        "mat_layers": mat_layers,
        "glass_type": glass_type,
        "molding_rate_per_ui": molding_rate,
        "mounting_type": mounting_type,
        "conservation_package": conservation,
        "is_fragile": is_fragile,
        "line_status": "DRAFT",
        "estimate_subtotal": 0,
        "final_subtotal": 0,
    }
    domain.stamp_create(l)
    sub = calc.line_cost(l, "NOMINAL")
    l["estimate_subtotal"] = calc.to_float(sub)
    db.frame_lines[l["id"]] = l

    # recompute order fragility + bump order version
    domain.recompute_has_fragile_line(o)
    domain.touch(o)

    return ok_object(domain.serialize_line(l), status=201)


@bp.route("/framing-orders/<order_id>/frame-lines", methods=["GET"])
def list_order_lines(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk", "FrameProductionTech", "Customer"))
    o = find_order_or_404(order_id)
    assert_customer_owns_order(auth, o)
    limit, offset = validate.parse_pagination()
    items = domain.order_lines(order_id)
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_line(l) for l in page], limit, offset, total)


@bp.route("/frame-lines/<line_id>", methods=["GET"])
def get_line(line_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk", "FrameProductionTech", "Customer"))
    l = _find_line_or_404(line_id)
    if auth.role == "Customer":
        o = db.framing_orders.get(l["order_id"])
        if o is None or auth.user_id != o["customer_id"]:
            errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Customer may only access own line")
    return ok_object(domain.serialize_line(l))


# ---------------------------------------------------------------------------
# MEASURE: DRAFT -> MEASURED
# ---------------------------------------------------------------------------
@bp.route("/frame-lines/<line_id>/measure", methods=["POST"])
def measure_line(line_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner",))
    l = _find_line_or_404(line_id)
    body = validate.get_json_body()

    o = db.framing_orders.get(l["order_id"])

    # state: order editable
    if o is None or o["production_status"] not in ("INTAKE", "QUOTED"):
        errors.raise_err(errors.ERR_ORDER_NOT_EDITABLE, "Order not editable")

    # line must be DRAFT to measure
    if l["line_status"] != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Line is not in DRAFT")

    mw = validate.require(body, "measured_width_in")
    mh = validate.require(body, "measured_height_in")
    if not validate.is_number(mw) or mw <= 0 or not validate.is_number(mh) or mh <= 0:
        errors.raise_err(errors.ERR_INVALID_DIMENSIONS, "Measured dimensions must be > 0")

    l["measured_width_in"] = mw
    l["measured_height_in"] = mh
    sub = calc.line_cost(l, "MEASURED")
    l["final_subtotal"] = calc.to_float(sub)
    l["line_status"] = "MEASURED"
    domain.touch(l)
    return ok_object(domain.serialize_line(l))


# ---------------------------------------------------------------------------
# VOID: DRAFT -> VOID
# ---------------------------------------------------------------------------
@bp.route("/frame-lines/<line_id>/void", methods=["POST"])
def void_line(line_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner",))
    l = _find_line_or_404(line_id)

    o = db.framing_orders.get(l["order_id"])
    if o is None or o["production_status"] not in ("INTAKE", "QUOTED"):
        errors.raise_err(errors.ERR_ORDER_NOT_EDITABLE, "Order not editable")

    if l["line_status"] != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Line is not in DRAFT")

    l["line_status"] = "VOID"
    domain.touch(l)

    domain.recompute_has_fragile_line(o)
    return ok_object(domain.serialize_line(l))
