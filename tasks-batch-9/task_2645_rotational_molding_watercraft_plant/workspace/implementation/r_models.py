"""ProductModel and Mold routes."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, q3, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter, str_filter

bp = Blueprint("models", __name__)

READ_ROLES = auth.READ_ALL_ROLES
MOLD_READ_ROLES = ("PlantAdmin", "MoldingOperator", "QualityInspector", "LogisticsPlanner")

MODEL_CREATE = {
    "model_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "hull_type": {"type": "enum", "required": True, "values": rt.HULL_TYPES},
    "size_class": {"type": "enum", "required": True, "values": rt.SIZE_CLASSES},
    "resin_grade": {"type": "enum", "required": True, "values": rt.RESIN_GRADES},
    "master_color_code": {"type": "string", "required": True, "min_len": 2, "max_len": 16},
    "max_color_delta_e": {"type": "dec", "places": 2, "gt": 0, "default": "1.50"},
    "required_additive_package_code": {"type": "string", "required": True,
                                       "min_len": 2, "max_len": 16},
    "max_regrind_pct": {"type": "dec", "places": 2, "min": 0, "max": 100, "default": "30.00"},
    "min_melt_index_g10min": {"type": "dec", "places": 2, "gt": 0, "default": "2.50"},
    "max_melt_index_g10min": {"type": "dec", "places": 2, "gt": 0, "default": "6.00"},
    "nominal_charge_kg": {"type": "dec", "places": 3, "required": True, "gt": 0},
    "charge_tolerance_pct": {"type": "dec", "places": 2, "gt": 0, "max": 25, "default": "5.00"},
    "min_cooling_minutes": {"type": "int", "required": True, "min": 1},
    "target_wall_thickness_mm": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "wall_thickness_min_mm": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "wall_cv_max_pct": {"type": "dec", "places": 2, "gt": 0, "default": "12.00"},
    "impact_test_min_joules": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "gross_cube_m3": {"type": "dec", "places": 4, "required": True, "gt": 0},
    "nest_factor": {"type": "dec", "places": 4, "required": True,
                    "min": "0.1000", "max": "1.0000"},
    "unit_weight_kg": {"type": "dec", "places": 3, "required": True, "gt": 0},
    "msrp_cents": {"type": "int", "required": True, "min": 1},
    "warranty_basis": {"type": "enum", "required": True, "values": rt.WARRANTY_BASES},
    "initial_warranty_reserve_cents": {"type": "int", "required": True, "min": 0},
    "seasonal_family": {"type": "string", "required": True, "min_len": 2, "max_len": 32},
}

MODEL_PATCH = dict(
    (name, dict(MODEL_CREATE[name], required=False))
    for name in ("max_color_delta_e", "max_regrind_pct", "min_melt_index_g10min",
                 "max_melt_index_g10min", "nominal_charge_kg", "charge_tolerance_pct",
                 "min_cooling_minutes", "target_wall_thickness_mm",
                 "wall_thickness_min_mm", "wall_cv_max_pct", "impact_test_min_joules",
                 "gross_cube_m3", "nest_factor", "unit_weight_kg", "msrp_cents")
)
for _rule in MODEL_PATCH.values():
    _rule.pop("default", None)


def _model_band_checks(values):
    if values["max_melt_index_g10min"] <= values["min_melt_index_g10min"]:
        fail("ERR_INVALID_QUANTITY",
             "max_melt_index_g10min must be strictly greater than min_melt_index_g10min.")
    if values["wall_thickness_min_mm"] >= values["target_wall_thickness_mm"]:
        fail("ERR_INVALID_QUANTITY",
             "wall_thickness_min_mm must be strictly less than target_wall_thickness_mm.")


@bp.route("/product-models", methods=["POST"])
def create_product_model():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, MODEL_CREATE)
    checks.add(22.5, lambda: _model_band_checks(coerce(body, MODEL_CREATE)))
    checks.add(26, lambda: rt.unique_code("product_models", "model_code",
                                          body.get("model_code")))
    checks.run()
    row = coerce(body, MODEL_CREATE)
    row["warranty_reserve_cents"] = row["initial_warranty_reserve_cents"]
    row["warranty_paid_cents"] = 0
    core.insert("product_models", row)
    return rt.one("product_models", row, 201)


@bp.route("/product-models", methods=["GET"])
def list_product_models():
    auth.authenticate(READ_ROLES)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("product_models")
        rows = rt.filter_eq(rows, "hull_type", enum_filter("hull_type", rt.HULL_TYPES))
        rows = rt.filter_eq(rows, "size_class", enum_filter("size_class", rt.SIZE_CLASSES))
        rows = rt.filter_eq(rows, "resin_grade", enum_filter("resin_grade", rt.RESIN_GRADES))
        rows = rt.filter_eq(rows, "warranty_basis",
                            enum_filter("warranty_basis", rt.WARRANTY_BASES))
        rows = rt.filter_eq(rows, "seasonal_family", str_filter("seasonal_family"))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("product_models", items[0])


@bp.route("/product-models/<product_model_id>", methods=["GET"])
def read_product_model(product_model_id):
    auth.authenticate(READ_ROLES)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("product_models", product_model_id)))
    checks.run()
    return rt.one("product_models", holder["row"])


@bp.route("/product-models/<product_model_id>", methods=["PATCH"])
def patch_product_model(product_model_id):
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("product_models", product_model_id)))
    add_schema(checks, body, MODEL_PATCH)

    def band():
        merged = dict(holder["row"])
        for name, value in coerce(body, MODEL_PATCH).items():
            if name in body and body[name] is not None:
                merged[name] = value
        _model_band_checks(merged)

    checks.add(22.5, band)
    checks.run()
    row = holder["row"]
    supplied = coerce(body, MODEL_PATCH)
    for name in MODEL_PATCH:
        if name in body and body[name] is not None:
            row[name] = supplied[name]
    touch(row)
    return rt.one("product_models", row)


# --------------------------------------------------------------------------
# Mould tools.
# --------------------------------------------------------------------------
MOLD_CREATE = {
    "mold_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "product_model_id": {"type": "string", "required": True},
    "size_class": {"type": "enum", "required": True, "values": rt.SIZE_CLASSES},
    "cavity_count": {"type": "int", "required": True, "min": 1, "max": 4},
    "nominal_charge_kg": {"type": "dec", "places": 3, "required": True, "gt": 0},
    "service_interval_cycles": {"type": "int", "required": True, "min": 1},
    "replaces_mold_id": {"type": "string", "required": False},
}


@bp.route("/molds", methods=["POST"])
def create_mold():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, MOLD_CREATE)

    def resolve_model():
        holder["model"] = rt.find("product_models", body.get("product_model_id"))

    def resolve_prior():
        if body.get("replaces_mold_id") is not None:
            holder["prior"] = rt.find("molds", body.get("replaces_mold_id"))

    def charge_consistency():
        model = holder["model"]
        expected = q3(model["nominal_charge_kg"] * Decimal(body["cavity_count"]))
        if q3(body["nominal_charge_kg"]) != expected:
            fail("ERR_VALIDATION",
                 "nominal_charge_kg must equal the model's nominal charge times "
                 "cavity_count (%s)." % expected)

    def size_class_matches():
        if body["size_class"] != holder["model"]["size_class"]:
            fail("ERR_MOLD_SIZE_CLASS_MISMATCH",
                 "Tool size_class must equal the hull model's size_class.")

    def replacement_legal():
        prior = holder.get("prior")
        if prior is None:
            return
        if prior["product_model_id"] != body["product_model_id"]:
            fail("ERR_INVALID_MOLD_REPLACEMENT",
                 "The replaced tool belongs to another hull model.")
        if prior["status"] != "RETIRED":
            fail("ERR_INVALID_MOLD_REPLACEMENT", "The replaced tool is not RETIRED.")

    checks.add(11, resolve_model)
    checks.add(11.5, resolve_prior)
    checks.add(23.5, charge_consistency)
    checks.add(26, lambda: rt.unique_code("molds", "mold_code", body.get("mold_code")))
    checks.add(60, size_class_matches)
    checks.add(67, replacement_legal)
    checks.run()
    row = coerce(body, MOLD_CREATE)
    row["cycles_since_service"] = 0
    row["status"] = "AVAILABLE"
    core.insert("molds", row)
    return rt.one("molds", row, 201)


@bp.route("/molds", methods=["GET"])
def list_molds():
    auth.authenticate(MOLD_READ_ROLES)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("molds")
        rows = rt.filter_eq(rows, "product_model_id", str_filter("product_model_id"))
        rows = rt.filter_eq(rows, "replaces_mold_id", str_filter("replaces_mold_id"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.MOLD_STATUSES))
        rows = rt.filter_eq(rows, "size_class", enum_filter("size_class", rt.SIZE_CLASSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("molds", items[0])


@bp.route("/molds/<mold_id>", methods=["GET"])
def read_mold(mold_id):
    auth.authenticate(MOLD_READ_ROLES)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("molds", mold_id)))
    checks.run()
    return rt.one("molds", holder["row"])


HOLD_SPEC = {"hold_note": {"type": "string", "required": False, "max_len": 500}}
SERVICE_SPEC = {"service_note": {"type": "string", "required": False, "max_len": 500}}
RETIRE_SPEC = {"retire_reason": {"type": "string", "required": True,
                                 "min_len": 1, "max_len": 500}}


def _mold_action(mold_id, spec, allowed_statuses, error_id="ERR_MOLD_NOT_AVAILABLE"):
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("molds", mold_id)))
    add_schema(checks, body, spec)

    def state():
        if holder["row"]["status"] not in allowed_statuses:
            fail(error_id, "Tool status is %s." % holder["row"]["status"])

    checks.add(44, state)
    return holder, body, checks


@bp.route("/molds/<mold_id>/service-hold", methods=["POST"])
def mold_service_hold(mold_id):
    holder, body, checks = _mold_action(mold_id, HOLD_SPEC, ("AVAILABLE",))
    checks.run()
    mold = holder["row"]
    mold["status"] = "MAINTENANCE"
    if body.get("hold_note") is not None:
        mold["hold_note"] = body["hold_note"]
    touch(mold)
    svc.abort_scheduled_cycles(
        lambda c: c.get("mold_id") == mold["id"],
        "MOLD_SERVICE_DUE", "MOLD_SERVICE_DUE",
    )
    svc.sweep_unblock_resin()
    return rt.one("molds", mold)


@bp.route("/molds/<mold_id>/complete-service", methods=["POST"])
def mold_complete_service(mold_id):
    holder, body, checks = _mold_action(mold_id, SERVICE_SPEC, ("MAINTENANCE",))
    checks.run()
    mold = holder["row"]
    mold["status"] = "AVAILABLE"
    mold["cycles_since_service"] = 0
    if body.get("service_note") is not None:
        mold["service_note"] = body["service_note"]
    touch(mold)
    return rt.one("molds", mold)


@bp.route("/molds/<mold_id>/retire", methods=["POST"])
def mold_retire(mold_id):
    holder, body, checks = _mold_action(
        mold_id, RETIRE_SPEC, ("AVAILABLE", "MAINTENANCE"))

    def no_active_cycles():
        for cycle in core.rows("molding_cycles"):
            if cycle.get("mold_id") == holder["row"]["id"] and \
                    cycle["status"] in ("SCHEDULED", "OVEN_RUNNING", "COOLING"):
                fail("ERR_MOLD_HAS_ACTIVE_CYCLES",
                     "The tool still carries an active cycle.")

    checks.add(45, no_active_cycles)
    checks.run()
    mold = holder["row"]
    mold["status"] = "RETIRED"
    mold["retire_reason"] = body["retire_reason"]
    touch(mold)
    return rt.one("molds", mold)
