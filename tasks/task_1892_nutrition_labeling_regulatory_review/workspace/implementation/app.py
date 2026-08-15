#!/usr/bin/env python3
"""Nutrition Labeling & Regulatory Review API — Flask reference implementation.

Storage is in-memory only (module-level dicts keyed by id). Every process boot
starts with a completely empty store; nothing is seeded. All behavior follows
workspace/PRD.md: response envelope, auth headers, RBAC with client-chain
scoping, state machines with cascade side effects, deterministic calculations
(Decimal, round-half-up), optimistic concurrency on Product.version, and the
logical clock (default 2026-08-01T00:00:00Z).
"""

import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# =============================================================================
# In-memory store — starts empty on every boot (no seeding)
# =============================================================================

db = {
    "clients": {},
    "products": {},
    "ingredients": {},
    "recipes": {},
    "lab_analyses": {},
    "nutrient_panels": {},
    "racc_assignments": {},
    "label_versions": {},
    "claims": {},
    "market_variants": {},
    "format_checks": {},
    "artwork_audits": {},
    "audit_findings": {},
}
_seq = [0]  # monotonic creation counter (stable "created_at ascending" order)
_clock = {"dt": None}  # logical clock; None => default 2026-08-01T00:00:00Z

# =============================================================================
# Domain constants
# =============================================================================

ROLES = {
    "PlatformAdmin",
    "ClientRep",
    "LabelAnalyst",
    "RegulatoryReviewer",
    "QualityManager",
    "ComplianceAuditor",
}
ENTITY_BACKED_ROLES = {"ClientRep", "QualityManager"}  # X-User-ID == Client.id
ALL_GET_ROLES = sorted(ROLES)

MARKETS = {"US_FDA", "CA_CFIA"}
PRODUCT_CATEGORIES = {
    "BAKED_GOOD", "BEVERAGE", "CEREAL", "SNACK",
    "DAIRY", "SAUCE", "CONFECTION", "FROZEN_DESSERT",
}
ALLERGENS = {
    "MILK", "EGGS", "FISH", "SHELLFISH", "TREE_NUTS",
    "PEANUTS", "WHEAT", "SOYBEAN", "SESAME",
}
DECLARED_FORMATS = {"STANDARD_VERTICAL", "SIMPLIFIED", "TABULAR", "LINEAR"}
CLAIM_TYPES = {
    "LOW_FAT", "FAT_FREE", "LOW_SODIUM",
    "HIGH_FIBER", "SUGAR_FREE", "LOW_CALORIE",
}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
FIELD_REFS = {
    "INGREDIENT_LIST", "CONTAINS_STATEMENT", "NUTRITION_VALUES",
    "SERVING_SIZE", "CLAIM_TEXT", "FORMAT",
}
SCORING_METHODS = {"BINARY", "WEIGHTED"}
PANEL_METHODS = {"DATABASE", "LAB"}

NUTRIENTS = ["kcal", "fat", "satfat", "chol", "sodium", "carb", "fiber", "sugar", "protein"]
NFIELD = {
    "kcal": "kcal_per_100g",
    "fat": "fat_g_per_100g",
    "satfat": "satfat_g_per_100g",
    "chol": "chol_mg_per_100g",
    "sodium": "sodium_mg_per_100g",
    "carb": "carb_g_per_100g",
    "fiber": "fiber_g_per_100g",
    "sugar": "sugar_g_per_100g",
    "protein": "protein_g_per_100g",
}

_RACC_ROW = {
    "BAKED_GOOD": 55, "BEVERAGE": 240, "CEREAL": 40, "SNACK": 30,
    "DAIRY": 170, "SAUCE": 30, "CONFECTION": 40, "FROZEN_DESSERT": 90,
}
RACC_TABLE = {"US_FDA": dict(_RACC_ROW), "CA_CFIA": dict(_RACC_ROW)}

# Claim thresholds on the per-RACC value: claim_type -> (nutrient, threshold, cmp)
CLAIM_SPEC = {
    "FAT_FREE": ("fat", Decimal("0.5"), "lt"),
    "LOW_FAT": ("fat", Decimal("3.0"), "le"),
    "SUGAR_FREE": ("sugar", Decimal("0.5"), "lt"),
    "LOW_SODIUM": ("sodium", Decimal("140"), "le"),
    "HIGH_FIBER": ("fiber", Decimal("5.0"), "ge"),
    "LOW_CALORIE": ("kcal", Decimal("40"), "le"),
}
# Per-serving disqualifiers in pinned check order: (nutrient, code, limit)
DISQUALIFIERS = [
    ("fat", "FAT", Decimal("13.0")),
    ("satfat", "SATFAT", Decimal("4.0")),
    ("chol", "CHOL", Decimal("60.0")),
    ("sodium", "SODIUM", Decimal("480.0")),
]
CA_UNREGULATED_CLAIMS = {"SUGAR_FREE", "LOW_CALORIE"}

FACILITY_BUFFER = timedelta(seconds=86400)
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# Errors and envelope helpers
# =============================================================================


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _ts_now():
    """ISO 8601 UTC with three fractional digits (wall clock for resource stamps)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _ts_now()}


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, code=200):
    page, pag = _paginate(items)
    meta = _meta()
    meta.update(pag)
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(500)
def _handle_500(_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Internal server error"},
    }
    return jsonify(body), 500


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_forbidden(msg="Role not allowed for this endpoint or outside own client chain"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def err_state(msg):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


# =============================================================================
# Generic resource helpers
# =============================================================================


def _new_record(**fields):
    _seq[0] += 1
    ts = _ts_now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _seq[0],
    }
    rec.update(fields)
    return rec


def _touch(rec):
    """Every mutation (client- or system-initiated) bumps version + updated_at."""
    rec["version"] += 1
    rec["updated_at"] = _ts_now()


def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid("offset must be an integer")
        offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def _sorted(items):
    return sorted(items, key=lambda r: r["_seq"])


# =============================================================================
# Decimal helpers (never float math for compliance quantities)
# =============================================================================


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def nearest(v, step):
    """Nearest multiple of step, halves round up: floor(v/step + 0.5) * step."""
    v, step = D(v), D(step)
    return ((v / step) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR) * step


def _num_out(dec):
    return float(dec)


# =============================================================================
# Auth / RBAC
# =============================================================================


def _auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and must name a recognized role",
        )
    return uid, role


def _require_role(role, allowed):
    if role not in allowed:
        raise err_forbidden()


def _enforce_scope(role, uid, client_id):
    if role in ENTITY_BACKED_ROLES and uid != client_id:
        raise err_forbidden("Entity-backed caller may only touch own client chain")


# --- client-chain resolvers -------------------------------------------------


def _cid_of_product(p):
    return p["client_id"]


def _cid_of_recipe(r):
    return db["products"][r["product_id"]]["client_id"]


def _cid_of_lab(la):
    return _cid_of_recipe(db["recipes"][la["recipe_id"]])


def _cid_of_panel(pn):
    return _cid_of_recipe(db["recipes"][pn["recipe_id"]])


def _cid_of_racc(ra):
    return db["products"][ra["product_id"]]["client_id"]


def _cid_of_label(lv):
    return db["products"][lv["product_id"]]["client_id"]


def _cid_of_claim(c):
    return _cid_of_label(db["label_versions"][c["label_version_id"]])


def _cid_of_variant(v):
    return _cid_of_label(db["label_versions"][v["label_version_id"]])


def _cid_of_fcheck(f):
    return _cid_of_label(db["label_versions"][f["label_version_id"]])


def _cid_of_audit(a):
    return a["client_id"]


def _cid_of_finding(f):
    return db["artwork_audits"][f["audit_id"]]["client_id"]


# =============================================================================
# Request body validation helpers
# =============================================================================


def _body():
    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        raise err_invalid("Request body must be a JSON object")
    return parsed


def _req(body, name):
    if name not in body or body[name] is None:
        raise err_invalid("Missing required field: %s" % name)
    return body[name]


def _as_str(v, name):
    if not isinstance(v, str) or v == "":
        raise err_invalid("Field %s must be a non-empty string" % name)
    return v


def _as_num(v, name, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid("Field %s must be a number" % name)
    if positive and not v > 0:
        raise err_invalid("Field %s must be greater than zero" % name)
    return v


def _as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def _as_int_version(v, name):
    if isinstance(v, bool):
        raise err_invalid("Field %s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise err_invalid("Field %s must be an integer" % name)


def _parse_dt(v, name):
    if not isinstance(v, str):
        raise err_invalid("Field %s must be an ISO8601 datetime string" % name)
    text = v.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise err_invalid("Field %s is not a valid ISO8601 datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso_z(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000)
    else:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return base + "Z"


def _logical_clock():
    return _clock["dt"] if _clock["dt"] is not None else DEFAULT_CLOCK_DT


# =============================================================================
# Lookups
# =============================================================================


def _get_client(cid):
    c = db["clients"].get(cid)
    if c is None:
        raise err_not_found("Client not found")
    return c


def _get_product(pid):
    p = db["products"].get(pid)
    if p is None:
        raise err_not_found("Product not found")
    return p


def _get_recipe(rid):
    r = db["recipes"].get(rid)
    if r is None:
        raise err_not_found("Recipe not found")
    return r


def _get_lab(lid):
    la = db["lab_analyses"].get(lid)
    if la is None:
        raise err_not_found("LabAnalysis not found")
    return la


def _get_panel(pid):
    pn = db["nutrient_panels"].get(pid)
    if pn is None:
        raise err_not_found("NutrientPanel not found")
    return pn


def _get_label(lvid):
    lv = db["label_versions"].get(lvid)
    if lv is None:
        raise err_not_found("LabelVersion not found")
    return lv


def _get_claim(cid):
    c = db["claims"].get(cid)
    if c is None:
        raise err_not_found("ClaimAssessment not found")
    return c


def _get_variant(vid):
    v = db["market_variants"].get(vid)
    if v is None:
        raise err_not_found("MarketVariant not found")
    return v


def _get_audit(aid):
    a = db["artwork_audits"].get(aid)
    if a is None:
        raise err_not_found("ArtworkAudit not found")
    return a


def _locked_recipe_of_product(product_id):
    for r in db["recipes"].values():
        if r["product_id"] == product_id and r["status"] == "LOCKED":
            return r
    return None


def _claims_of_label(label_id):
    return [c for c in db["claims"].values() if c["label_version_id"] == label_id]


# =============================================================================
# Derived content_status (computed field on LabelVersion)
# =============================================================================


def _content_status(lv):
    """NEEDS_REVISION when any claim is SUSPENDED, the pinned panel snapshot is
    STALE, or the pinned basis's recipe is no longer LOCKED; else READY.
    FormatCheck outcomes never affect this flag."""
    for c in _claims_of_label(lv["id"]):
        if c["status"] == "SUSPENDED":
            return "NEEDS_REVISION"
    snap_id = lv.get("panel_snapshot_id")
    if snap_id:
        panel = db["nutrient_panels"].get(snap_id)
        if panel is None or panel["status"] != "CURRENT":
            return "NEEDS_REVISION"
        recipe = db["recipes"].get(panel["recipe_id"])
        if recipe is None or recipe["status"] != "LOCKED":
            return "NEEDS_REVISION"
    return "READY"


def _pub_label(lv):
    out = _pub(lv)
    out["content_status"] = _content_status(lv)
    return out


# =============================================================================
# Cascades
# =============================================================================


def _stale_panels_and_suspend_claims(panels):
    """CURRENT -> STALE for the given panels, then ELIGIBLE claims whose basis
    panel went stale flip to SUSPENDED. Label content_status is derived."""
    staled = set()
    for p in panels:
        if p["status"] == "CURRENT":
            p["status"] = "STALE"
            _touch(p)
            staled.add(p["id"])
    if not staled:
        return
    for c in db["claims"].values():
        if c.get("basis_panel_id") in staled and c["status"] == "ELIGIBLE":
            c["status"] = "SUSPENDED"
            _touch(c)


# =============================================================================
# Calculations
# =============================================================================


def _compute_panel_raw_database(recipe):
    raw_sum = {n: Decimal(0) for n in NUTRIENTS}
    total_qty = Decimal(0)
    for line in recipe["lines"]:
        ing = db["ingredients"].get(line["ingredient_id"])
        if ing is None:
            raise err_not_found("Recipe line ingredient not found")
        for n in NUTRIENTS:
            val = ing.get(NFIELD[n])
            if val is None:
                raise ApiError(
                    "ERR_NUTRIENT_PROFILE_INCOMPLETE",
                    422,
                    "Ingredient %s has an incomplete nutrient profile" % ing["id"],
                )
            raw_sum[n] += D(val) * D(line["quantity_g"]) / 100
        total_qty += D(line["quantity_g"])
    final_mass = total_qty * D(recipe["yield_factor"])
    return {n: (raw_sum[n] / final_mass * 100) for n in NUTRIENTS}


def _compute_panel_raw_lab(recipe):
    la_id = recipe.get("latest_validated_lab_analysis_id")
    la = db["lab_analyses"].get(la_id) if la_id else None
    if la is None or la["status"] != "VALIDATED":
        raise ApiError(
            "ERR_NO_VALIDATED_LAB_ANALYSIS",
            422,
            "Recipe has no VALIDATED lab analysis",
        )
    return la, {n: D(la[NFIELD[n]]) for n in NUTRIENTS}


def _evaluate_claim(claim_type, market, raw, racc_g, serving_g, panel_id):
    """Synchronous claim evaluation. Returns the mutable result fields."""
    if market == "CA_CFIA" and claim_type in CA_UNREGULATED_CLAIMS:
        return {
            "status": "NOT_REQUIRED",
            "evaluated_value_per_racc": None,
            "threshold_value": None,
            "disqualified_by": None,
            "basis_panel_id": None,
        }
    per_racc = {n: rhu2(raw[n] * D(racc_g) / 100) for n in NUTRIENTS}
    per_serv = {n: rhu2(raw[n] * D(serving_g) / 100) for n in NUTRIENTS}
    nut, thr, cmp_op = CLAIM_SPEC[claim_type]
    disqualified_by = "NONE"
    eligible = True
    for n, code, limit in DISQUALIFIERS:
        if per_serv[n] > limit:  # strictly greater disqualifies
            disqualified_by = code
            eligible = False
            break
    if eligible:
        v = per_racc[nut]
        passed = {"lt": v < thr, "le": v <= thr, "ge": v >= thr}[cmp_op]
        eligible = bool(passed)
    return {
        "status": "ELIGIBLE" if eligible else "INELIGIBLE",
        "evaluated_value_per_racc": _num_out(per_racc[nut]),
        "threshold_value": _num_out(thr),
        "disqualified_by": disqualified_by,
        "basis_panel_id": panel_id,
    }


def _latest_current_panel(recipe_id, method):
    cands = [
        p for p in db["nutrient_panels"].values()
        if p["recipe_id"] == recipe_id and p["method"] == method and p["status"] == "CURRENT"
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: p["_seq"])


def _reevaluate_suspended_claims(recipe, panel):
    """A new CURRENT panel re-evaluates SUSPENDED claims on labels of this
    recipe's product whose nutrient_basis matches the panel method."""
    product_id = recipe["product_id"]
    for lv in db["label_versions"].values():
        if lv["product_id"] != product_id or lv["nutrient_basis"] != panel["method"]:
            continue
        suspended = [
            c for c in _claims_of_label(lv["id"]) if c["status"] == "SUSPENDED"
        ]
        if not suspended:
            continue
        ra = db["racc_assignments"].get(lv["racc_assignment_id"])
        if ra is None:
            continue
        for c in suspended:
            result = _evaluate_claim(
                c["claim_type"], lv["market_code"], panel["_raw"],
                ra["racc_g"], ra["serving_size_g"], panel["id"],
            )
            c.update(result)
            _touch(c)


def _canonical_statements(recipe):
    """Canonical ingredient statement + Contains statement for a recipe's lines.

    Sort: quantity_g DESC, then ingredient.created_at ASC, then name ASC.
    """
    lines = list(recipe["lines"])

    def sort_key(line):
        ing = db["ingredients"][line["ingredient_id"]]
        return (D(line["quantity_g"]) * -1, ing["_seq"], ing["name"])

    ordered = sorted(lines, key=sort_key)
    names = [db["ingredients"][l["ingredient_id"]]["name"] for l in ordered]
    statement = ", ".join(names)
    tags = []
    for l in ordered:
        for t in db["ingredients"][l["ingredient_id"]].get("allergen_tags", []):
            if t not in tags:
                tags.append(t)
    contains = "Contains: " + (", ".join(tags) if tags else "None") + "."
    canonical_order = [
        {"ingredient_id": l["ingredient_id"], "quantity_g": l["quantity_g"]}
        for l in ordered
    ]
    return statement, contains, canonical_order


def _run_format_check(label, product):
    area = D(product["total_surface_area_sq_in"])
    pdp = D(product["pdp_area_sq_in"])
    if area <= D("12.0"):
        allowed = ["LINEAR"]
    elif area <= D("40.0"):
        allowed = ["SIMPLIFIED", "TABULAR", "STANDARD_VERTICAL"]
    else:
        allowed = ["STANDARD_VERTICAL"]
    min_type = Decimal("0.03125") if pdp <= Decimal("5.0") else Decimal("0.0625")
    violations = []
    if label["declared_format"] not in allowed:
        violations.append("FORMAT_NOT_ALLOWED_FOR_PACKAGE")
    if D(label["declared_type_size_in"]) < min_type:
        violations.append("TYPE_SIZE_BELOW_MIN")
    fc = _new_record(
        label_version_id=label["id"],
        result="PASS" if not violations else "FAIL",
        violations=violations,
        allowed_formats=allowed,
        min_type_size_in=float(min_type),
    )
    db["format_checks"][fc["id"]] = fc
    return fc


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; None end = infinity; adjacency allowed."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


# =============================================================================
# Client endpoints
# =============================================================================


@app.route("/api/clients", methods=["POST"])
def create_client():
    uid, role = _auth()
    _require_role(role, ["PlatformAdmin"])
    body = _body()
    name = _as_str(_req(body, "name"), "name")
    home_market_code = _as_enum(_req(body, "home_market_code"), "home_market_code", MARKETS)
    rec = _new_record(name=name, home_market_code=home_market_code)
    db["clients"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/clients/<cid>", methods=["GET"])
def get_client(cid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    client = _get_client(cid)
    _enforce_scope(role, uid, client["id"])
    return ok_object(_pub(client))


# =============================================================================
# Product endpoints
# =============================================================================


@app.route("/api/clients/<cid>/products", methods=["POST"])
def create_product(cid):
    uid, role = _auth()
    _require_role(role, ["ClientRep"])
    client = _get_client(cid)
    _enforce_scope(role, uid, client["id"])
    body = _body()
    name = _as_str(_req(body, "name"), "name")
    category = _as_enum(_req(body, "product_category"), "product_category", PRODUCT_CATEGORIES)
    net_weight_g = _as_num(_req(body, "net_weight_g"), "net_weight_g", positive=True)
    tsa = _as_num(_req(body, "total_surface_area_sq_in"), "total_surface_area_sq_in", positive=True)
    pdp = _as_num(_req(body, "pdp_area_sq_in"), "pdp_area_sq_in", positive=True)
    hu_name = body.get("household_unit_name")
    if hu_name is not None:
        hu_name = _as_str(hu_name, "household_unit_name")
    hu_weight = body.get("household_unit_weight_g")
    if hu_weight is not None:
        hu_weight = _as_num(hu_weight, "household_unit_weight_g", positive=True)
    rec = _new_record(
        client_id=client["id"],
        name=name,
        product_category=category,
        net_weight_g=net_weight_g,
        household_unit_name=hu_name,
        household_unit_weight_g=hu_weight,
        total_surface_area_sq_in=tsa,
        pdp_area_sq_in=pdp,
    )
    db["products"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/products/<pid>", methods=["GET"])
def get_product(pid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    product = _get_product(pid)
    _enforce_scope(role, uid, _cid_of_product(product))
    return ok_object(_pub(product))


@app.route("/api/clients/<cid>/products", methods=["GET"])
def list_products(cid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    client = _get_client(cid)
    _enforce_scope(role, uid, client["id"])
    items = [p for p in db["products"].values() if p["client_id"] == cid]
    return ok_list([_pub(p) for p in _sorted(items)])


# =============================================================================
# Ingredient endpoints
# =============================================================================


@app.route("/api/clients/<cid>/ingredients", methods=["POST"])
def create_ingredient(cid):
    uid, role = _auth()
    _require_role(role, ["ClientRep"])
    client = _get_client(cid)
    _enforce_scope(role, uid, client["id"])
    body = _body()
    name = _as_str(_req(body, "name"), "name")
    tags = body.get("allergen_tags", [])
    if not isinstance(tags, list) or any(t not in ALLERGENS for t in tags):
        raise err_invalid("allergen_tags must be a list of recognized allergen codes")
    fields = {}
    for n in NUTRIENTS:
        fname = NFIELD[n]
        v = body.get(fname)
        fields[fname] = None if v is None else _as_num(v, fname)
    rec = _new_record(
        client_id=client["id"],
        name=name,
        allergen_tags=list(tags),
        **fields,
    )
    db["ingredients"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/clients/<cid>/ingredients", methods=["GET"])
def list_ingredients(cid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    client = _get_client(cid)
    _enforce_scope(role, uid, client["id"])
    items = [i for i in db["ingredients"].values() if i["client_id"] == cid]
    return ok_list([_pub(i) for i in _sorted(items)])


# =============================================================================
# Recipe endpoints
# =============================================================================


@app.route("/api/products/<pid>/recipes", methods=["POST"])
def create_recipe(pid):
    uid, role = _auth()
    _require_role(role, ["ClientRep"])
    product = _get_product(pid)
    _enforce_scope(role, uid, _cid_of_product(product))
    body = _body()
    # Structural minimum so references can be resolved (existence precedes shape).
    raw_lines = body.get("lines")
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, dict) and isinstance(line.get("ingredient_id"), str):
                ing = db["ingredients"].get(line["ingredient_id"])
                if ing is None or ing["client_id"] != product["client_id"]:
                    raise err_not_found("Recipe line ingredient not found in client catalogue")
    name = _as_str(_req(body, "name"), "name")
    yield_factor = body.get("yield_factor", 1.0)
    yield_factor = _as_num(yield_factor, "yield_factor")
    if not (D(yield_factor) > 0 and D(yield_factor) <= D("1.2")):
        raise err_invalid("yield_factor must be in (0, 1.2]")
    if not isinstance(raw_lines, list) or len(raw_lines) < 1:
        raise err_invalid("lines must contain at least one line")
    lines = []
    seen = set()
    for line in raw_lines:
        if not isinstance(line, dict):
            raise err_invalid("each recipe line must be an object")
        iid = _as_str(_req(line, "ingredient_id"), "ingredient_id")
        qty = _as_num(_req(line, "quantity_g"), "quantity_g", positive=True)
        if iid in seen:
            raise err_invalid("recipe lines must reference distinct ingredients")
        seen.add(iid)
        lines.append({"ingredient_id": iid, "quantity_g": qty})
    rec = _new_record(
        product_id=product["id"],
        name=name,
        yield_factor=yield_factor,
        lines=lines,
        status="DRAFT",
        latest_validated_lab_analysis_id=None,
    )
    db["recipes"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/recipes/<rid>", methods=["GET"])
def get_recipe(rid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    return ok_object(_pub(recipe))


@app.route("/api/products/<pid>/recipes", methods=["GET"])
def list_recipes_of_product(pid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    product = _get_product(pid)
    _enforce_scope(role, uid, _cid_of_product(product))
    items = [r for r in db["recipes"].values() if r["product_id"] == pid]
    return ok_list([_pub(r) for r in _sorted(items)])


@app.route("/api/recipes", methods=["GET"])
def list_recipes():
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    items = list(db["recipes"].values())
    flt = request.args.get("latest_validated_lab_analysis_id")
    if flt is not None:
        items = [r for r in items if r.get("latest_validated_lab_analysis_id") == flt]
    if role in ENTITY_BACKED_ROLES:
        items = [r for r in items if _cid_of_recipe(r) == uid]
    return ok_list([_pub(r) for r in _sorted(items)])


@app.route("/api/recipes/<rid>/lock", methods=["POST"])
def lock_recipe(rid):
    uid, role = _auth()
    _require_role(role, ["ClientRep"])
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    if recipe["status"] != "DRAFT":
        raise err_state("Only a DRAFT recipe can be locked")
    recipe["status"] = "LOCKED"
    _touch(recipe)
    # Cascade: supersede any other LOCKED sibling of the same product.
    for sib in db["recipes"].values():
        if (
            sib["product_id"] == recipe["product_id"]
            and sib["id"] != recipe["id"]
            and sib["status"] == "LOCKED"
        ):
            sib["status"] = "SUPERSEDED"
            _touch(sib)
            panels = [p for p in db["nutrient_panels"].values() if p["recipe_id"] == sib["id"]]
            _stale_panels_and_suspend_claims(panels)
    return ok_object(_pub(recipe))


@app.route("/api/recipes/<rid>/ingredient-statement", methods=["GET"])
def get_ingredient_statement(rid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    locked = _locked_recipe_of_product(recipe["product_id"])
    if locked is None:
        raise ApiError(
            "ERR_RECIPE_NOT_LOCKED", 409,
            "The product has no currently LOCKED recipe",
        )
    statement, contains, canonical_order = _canonical_statements(locked)
    return ok_object({
        "ingredient_statement_text": statement,
        "contains_text": contains,
        "canonical_order": canonical_order,
    })


# =============================================================================
# LabAnalysis endpoints
# =============================================================================


@app.route("/api/recipes/<rid>/lab-analyses", methods=["POST"])
def create_lab_analysis(rid):
    uid, role = _auth()
    _require_role(role, ["ClientRep"])
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    body = _body()
    lab_report_ref = _as_str(_req(body, "lab_report_ref"), "lab_report_ref")
    fields = {}
    for n in NUTRIENTS:
        fname = NFIELD[n]
        fields[fname] = _as_num(_req(body, fname), fname)
    rec = _new_record(
        recipe_id=recipe["id"],
        lab_report_ref=lab_report_ref,
        status="SUBMITTED",
        reviewed_by=None,
        **fields,
    )
    db["lab_analyses"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/recipes/<rid>/lab-analyses", methods=["GET"])
def list_lab_analyses(rid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    items = [la for la in db["lab_analyses"].values() if la["recipe_id"] == rid]
    return ok_list([_pub(la) for la in _sorted(items)])


@app.route("/api/lab-analyses/<lid>/review", methods=["POST"])
def review_lab_analysis(lid):
    uid, role = _auth()
    _require_role(role, ["RegulatoryReviewer"])
    la = _get_lab(lid)
    body = _body()
    outcome = _as_enum(_req(body, "outcome"), "outcome", {"VALIDATED", "REJECTED"})
    if la["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_LAB_REVIEW_ALREADY_DECIDED", 409,
            "Lab analysis has already been decided",
        )
    recipe = db["recipes"][la["recipe_id"]]
    if outcome == "VALIDATED" and recipe["status"] != "LOCKED":
        raise ApiError(
            "ERR_RECIPE_NOT_LOCKED", 409,
            "Validation requires the parent recipe to be LOCKED",
        )
    la["reviewed_by"] = uid
    if outcome == "REJECTED":
        la["status"] = "REJECTED"
        _touch(la)
        return ok_object(_pub(la))
    # VALIDATED cascade
    la["status"] = "VALIDATED"
    _touch(la)
    recipe["latest_validated_lab_analysis_id"] = la["id"]
    _touch(recipe)
    for other in db["lab_analyses"].values():
        if (
            other["recipe_id"] == recipe["id"]
            and other["id"] != la["id"]
            and other["status"] == "VALIDATED"
        ):
            other["status"] = "SUPERSEDED"
            _touch(other)
            panels = [
                p for p in db["nutrient_panels"].values()
                if p["method"] == "LAB" and p.get("basis_lab_analysis_id") == other["id"]
            ]
            _stale_panels_and_suspend_claims(panels)
    return ok_object(_pub(la))


# =============================================================================
# NutrientPanel endpoints
# =============================================================================


@app.route("/api/recipes/<rid>/nutrient-panels", methods=["POST"])
def create_nutrient_panel(rid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    recipe = _get_recipe(rid)
    body = _body()
    method = _as_enum(_req(body, "method"), "method", PANEL_METHODS)
    if recipe["status"] != "LOCKED":
        raise ApiError(
            "ERR_RECIPE_NOT_LOCKED", 409,
            "Panel computation requires a LOCKED recipe",
        )
    basis_lab_analysis_id = None
    if method == "DATABASE":
        raw = _compute_panel_raw_database(recipe)
    else:
        la, raw = _compute_panel_raw_lab(recipe)
        basis_lab_analysis_id = la["id"]
    declared = {NFIELD[n]: _num_out(rhu2(raw[n])) for n in NUTRIENTS}
    rec = _new_record(
        recipe_id=recipe["id"],
        method=method,
        status="CURRENT",
        basis_lab_analysis_id=basis_lab_analysis_id,
        **declared,
    )
    rec["_raw"] = raw  # unrounded per-100g vector; authoritative downstream
    db["nutrient_panels"][rec["id"]] = rec
    _reevaluate_suspended_claims(recipe, rec)
    return ok_object(_pub(rec), 201)


@app.route("/api/recipes/<rid>/nutrient-panels", methods=["GET"])
def list_panels_of_recipe(rid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    recipe = _get_recipe(rid)
    _enforce_scope(role, uid, _cid_of_recipe(recipe))
    items = [p for p in db["nutrient_panels"].values() if p["recipe_id"] == rid]
    flt = request.args.get("method")
    if flt is not None:
        items = [p for p in items if p["method"] == flt]
    return ok_list([_pub(p) for p in _sorted(items)])


@app.route("/api/nutrient-panels/<pid>", methods=["GET"])
def get_panel(pid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    panel = _get_panel(pid)
    _enforce_scope(role, uid, _cid_of_panel(panel))
    return ok_object(_pub(panel))


@app.route("/api/nutrient-panels", methods=["GET"])
def list_panels():
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    items = list(db["nutrient_panels"].values())
    flt = request.args.get("basis_lab_analysis_id")
    if flt is not None:
        items = [p for p in items if p.get("basis_lab_analysis_id") == flt]
    if role in ENTITY_BACKED_ROLES:
        items = [p for p in items if _cid_of_panel(p) == uid]
    return ok_list([_pub(p) for p in _sorted(items)])


# =============================================================================
# RaccAssignment endpoints
# =============================================================================


@app.route("/api/products/<pid>/racc-assignments", methods=["POST"])
def create_racc_assignment(pid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    product = _get_product(pid)
    body = _body()
    market_code = _as_enum(_req(body, "market_code"), "market_code", MARKETS)
    for existing in db["racc_assignments"].values():
        if existing["product_id"] == pid and existing["market_code"] == market_code:
            raise ApiError(
                "ERR_RACC_ALREADY_ASSIGNED", 409,
                "A RaccAssignment already exists for this product and market",
            )
    racc_g = RACC_TABLE[market_code].get(product["product_category"])
    if racc_g is None:
        raise ApiError(
            "ERR_RACC_CATEGORY_UNKNOWN", 422,
            "product_category is absent from the market RACC table",
        )
    racc = D(racc_g)
    net = D(product["net_weight_g"])
    ratio = net / racc  # against RACC, not against serving size
    if ratio < D("2.0"):
        label_mode = "SINGLE_SERVING"
    elif ratio <= D("3.0"):
        label_mode = "DUAL_COLUMN"
    else:
        label_mode = "STANDARD"

    if label_mode == "SINGLE_SERVING":
        serving_size_g = product["net_weight_g"]
        serving_household_units = 1
        servings_per_container = 1
    else:
        w = product.get("household_unit_weight_g")
        if market_code == "US_FDA":
            if w is None or D(w) <= 0:
                raise ApiError(
                    "ERR_SERVING_SIZE_UNRESOLVABLE", 422,
                    "household_unit_weight_g is required for serving computation",
                )
            units = nearest(racc / D(w), Decimal("0.5"))
            serving_size_g = _num_out(rhu2(units * D(w)))
            serving_household_units = _num_out(units)
        else:  # CA_CFIA: metric-first
            step = Decimal("5") if racc >= D("50") else Decimal("1")
            serving = nearest(racc, step)
            serving_size_g = _num_out(serving)
            if w is None or D(w) <= 0:
                raise ApiError(
                    "ERR_SERVING_SIZE_UNRESOLVABLE", 422,
                    "household_unit_weight_g is required for serving computation",
                )
            serving_household_units = _num_out(rhu2(serving / D(w)))
        n = net / D(serving_size_g)
        if n < D("2"):
            servings_per_container = 1
        elif n <= D("5"):
            servings_per_container = _num_out(nearest(n, Decimal("0.5")))
        else:
            servings_per_container = _num_out(nearest(n, Decimal("1")))
    rec = _new_record(
        product_id=product["id"],
        market_code=market_code,
        racc_g=racc_g,
        label_mode=label_mode,
        serving_size_g=serving_size_g,
        serving_household_units=serving_household_units,
        servings_per_container=servings_per_container,
    )
    db["racc_assignments"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/products/<pid>/racc-assignments", methods=["GET"])
def list_racc_assignments(pid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    product = _get_product(pid)
    _enforce_scope(role, uid, _cid_of_product(product))
    items = [r for r in db["racc_assignments"].values() if r["product_id"] == pid]
    return ok_list([_pub(r) for r in _sorted(items)])


# =============================================================================
# LabelVersion endpoints
# =============================================================================


@app.route("/api/products/<pid>/label-versions", methods=["POST"])
def create_label_version(pid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    product = _get_product(pid)
    body = _body()
    # Body-supplied FK existence precedes shape checks (PRD §2.8).
    ra_raw = body.get("racc_assignment_id")
    ra = None
    if isinstance(ra_raw, str):
        ra = db["racc_assignments"].get(ra_raw)
        if ra is None:
            raise err_not_found("racc_assignment_id does not exist")
    market_code = _as_enum(_req(body, "market_code"), "market_code", MARKETS)
    nutrient_basis = _as_enum(_req(body, "nutrient_basis"), "nutrient_basis", PANEL_METHODS)
    ra_id = _as_str(_req(body, "racc_assignment_id"), "racc_assignment_id")
    if ra is None:
        ra = db["racc_assignments"].get(ra_id)
        if ra is None:
            raise err_not_found("racc_assignment_id does not exist")
    declared_format = _as_enum(_req(body, "declared_format"), "declared_format", DECLARED_FORMATS)
    declared_type_size_in = _as_num(
        _req(body, "declared_type_size_in"), "declared_type_size_in", positive=True
    )
    ingredient_statement_text = _as_str(
        _req(body, "ingredient_statement_text"), "ingredient_statement_text"
    )
    contains_text = _as_str(_req(body, "contains_text"), "contains_text")
    expected = _as_int_version(
        _req(body, "expected_product_version"), "expected_product_version"
    )
    if expected != product["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_product_version does not match the product's current version",
        )
    if ra["product_id"] != product["id"] or ra["market_code"] != market_code:
        raise ApiError(
            "ERR_RACC_MARKET_MISMATCH", 422,
            "racc_assignment_id must belong to the same product and market",
        )
    # One draft per product+market: withdraw the existing DRAFT.
    for other in db["label_versions"].values():
        if (
            other["product_id"] == product["id"]
            and other["market_code"] == market_code
            and other["review_status"] == "DRAFT"
        ):
            other["review_status"] = "WITHDRAWN"
            _touch(other)
    rec = _new_record(
        product_id=product["id"],
        market_code=market_code,
        nutrient_basis=nutrient_basis,
        racc_assignment_id=ra_id,
        declared_format=declared_format,
        declared_type_size_in=declared_type_size_in,
        ingredient_statement_text=ingredient_statement_text,
        contains_text=contains_text,
        review_status="DRAFT",
        release_status="NOT_RELEASED",
        panel_snapshot_id=None,
        review_round=0,
        prepared_by=uid,
        approved_by=None,
        superseded_by_id=None,
    )
    db["label_versions"][rec["id"]] = rec
    _touch(product)
    return ok_object(_pub_label(rec), 201)


@app.route("/api/label-versions/<lvid>", methods=["GET"])
def get_label_version(lvid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    return ok_object(_pub_label(lv))


@app.route("/api/products/<pid>/label-versions", methods=["GET"])
def list_label_versions_of_product(pid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    product = _get_product(pid)
    _enforce_scope(role, uid, _cid_of_product(product))
    items = [l for l in db["label_versions"].values() if l["product_id"] == pid]
    return ok_list([_pub_label(l) for l in _sorted(items)])


@app.route("/api/label-versions", methods=["GET"])
def list_label_versions():
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    items = list(db["label_versions"].values())
    for param in ("racc_assignment_id", "panel_snapshot_id", "superseded_by_id"):
        flt = request.args.get(param)
        if flt is not None:
            items = [l for l in items if l.get(param) == flt]
    if role in ENTITY_BACKED_ROLES:
        items = [l for l in items if _cid_of_label(l) == uid]
    return ok_list([_pub_label(l) for l in _sorted(items)])


@app.route("/api/label-versions/<lvid>/submit-review", methods=["POST"])
def submit_review(lvid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    lv = _get_label(lvid)
    if lv["review_status"] != "DRAFT":
        raise err_state("Only a DRAFT label can be submitted for review")
    locked = _locked_recipe_of_product(lv["product_id"])
    if locked is None:
        raise ApiError(
            "ERR_RECIPE_NOT_LOCKED", 409,
            "The product has no currently LOCKED recipe",
        )
    panel = _latest_current_panel(locked["id"], lv["nutrient_basis"])
    if panel is None:
        raise ApiError(
            "ERR_PANEL_NOT_CURRENT", 409,
            "No CURRENT nutrient panel exists for the locked recipe and nutrient basis",
        )
    statement, contains, _order = _canonical_statements(locked)
    if lv["contains_text"].strip() != contains:
        raise ApiError(
            "ERR_ALLERGEN_STATEMENT_INCOMPLETE", 422,
            "contains_text does not equal the canonical allergen statement",
        )
    if lv["ingredient_statement_text"].strip() != statement:
        raise ApiError(
            "ERR_INGREDIENT_ORDER_VIOLATION", 422,
            "ingredient_statement_text does not equal the canonical descending-weight ordering",
        )
    lv["panel_snapshot_id"] = panel["id"]
    lv["review_round"] += 1
    lv["review_status"] = "IN_REVIEW"
    _touch(lv)
    product = db["products"][lv["product_id"]]
    _run_format_check(lv, product)
    return ok_object(_pub_label(lv))


@app.route("/api/label-versions/<lvid>/approve", methods=["POST"])
def approve_label(lvid):
    uid, role = _auth()
    _require_role(role, ["RegulatoryReviewer"])
    lv = _get_label(lvid)
    if uid == lv["prepared_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION", 403,
            "Approver must differ from the analyst who prepared the label",
        )
    if lv["review_status"] != "IN_REVIEW":
        raise ApiError(
            "ERR_LABEL_NOT_IN_REVIEW", 409,
            "Approval requires review_status IN_REVIEW",
        )
    if _content_status(lv) != "READY":
        raise ApiError(
            "ERR_CONTENT_REVISION_REQUIRED", 409,
            "Label content requires revision before approval",
        )
    lv["approved_by"] = uid
    lv["review_status"] = "APPROVED"
    _touch(lv)
    return ok_object(_pub_label(lv))


@app.route("/api/label-versions/<lvid>/reject", methods=["POST"])
def reject_label(lvid):
    uid, role = _auth()
    _require_role(role, ["RegulatoryReviewer"])
    lv = _get_label(lvid)
    _body()  # optional reason; declared content is deliberately retained
    if lv["review_status"] != "IN_REVIEW":
        raise ApiError(
            "ERR_LABEL_NOT_IN_REVIEW", 409,
            "Rejection requires review_status IN_REVIEW",
        )
    lv["review_status"] = "DRAFT"
    lv["approved_by"] = None
    _touch(lv)
    return ok_object(_pub_label(lv))


@app.route("/api/label-versions/<lvid>/release", methods=["POST"])
def release_label(lvid):
    uid, role = _auth()
    _require_role(role, ["QualityManager"])
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    body = _body()
    expected = _as_int_version(
        _req(body, "expected_product_version"), "expected_product_version"
    )
    product = db["products"][lv["product_id"]]
    if expected != product["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_product_version does not match the product's current version",
        )
    # Release gates in the pinned order.
    if not (lv["review_status"] == "APPROVED" and lv["release_status"] == "NOT_RELEASED"):
        raise ApiError(
            "ERR_LABEL_NOT_APPROVED", 409,
            "Release requires review_status APPROVED and release_status NOT_RELEASED",
        )
    if _content_status(lv) != "READY":
        raise ApiError(
            "ERR_CONTENT_REVISION_REQUIRED", 409,
            "Label content requires revision before release",
        )
    for c in _claims_of_label(lv["id"]):
        if c["status"] not in ("ELIGIBLE", "NOT_REQUIRED"):
            raise ApiError(
                "ERR_CLAIMS_NOT_RESOLVED", 409,
                "All claims must be ELIGIBLE or NOT_REQUIRED before release",
            )
    checks = [
        f for f in db["format_checks"].values() if f["label_version_id"] == lv["id"]
    ]
    latest_check = max(checks, key=lambda f: f["_seq"]) if checks else None
    if latest_check is None or latest_check["result"] != "PASS":
        raise ApiError(
            "ERR_FORMAT_CHECK_FAILED", 409,
            "The latest format check must PASS before release",
        )
    lv["release_status"] = "RELEASED"
    _touch(lv)
    for other in db["label_versions"].values():
        if (
            other["product_id"] == lv["product_id"]
            and other["market_code"] == lv["market_code"]
            and other["id"] != lv["id"]
            and other["release_status"] == "RELEASED"
        ):
            other["release_status"] = "SUPERSEDED"
            other["superseded_by_id"] = lv["id"]
            _touch(other)
    _touch(product)
    return ok_object(_pub_label(lv))


@app.route("/api/label-versions/<lvid>/withdraw", methods=["POST"])
def withdraw_label(lvid):
    uid, role = _auth()
    _require_role(role, ["QualityManager"])
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    _body()  # optional reason
    if lv["release_status"] != "RELEASED":
        raise err_state("Only a RELEASED label can be withdrawn")
    lv["release_status"] = "WITHDRAWN"
    _touch(lv)
    # Compensating action: restore the label this one superseded.
    for other in db["label_versions"].values():
        if other.get("superseded_by_id") == lv["id"]:
            other["release_status"] = "RELEASED"
            other["superseded_by_id"] = None
            _touch(other)
    product = db["products"][lv["product_id"]]
    _touch(product)
    return ok_object(_pub_label(lv))


# =============================================================================
# ClaimAssessment endpoints
# =============================================================================


@app.route("/api/label-versions/<lvid>/claims", methods=["POST"])
def create_claim(lvid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    lv = _get_label(lvid)
    body = _body()
    claim_type = _as_enum(_req(body, "claim_type"), "claim_type", CLAIM_TYPES)
    if lv["review_status"] not in ("DRAFT", "IN_REVIEW"):
        raise err_state("Claims may only be declared while the label is DRAFT or IN_REVIEW")
    locked = _locked_recipe_of_product(lv["product_id"])
    if locked is None:
        raise ApiError(
            "ERR_RECIPE_NOT_LOCKED", 409,
            "Claim evaluation requires a LOCKED recipe",
        )
    if lv["market_code"] == "CA_CFIA" and claim_type in CA_UNREGULATED_CLAIMS:
        result = {
            "status": "NOT_REQUIRED",
            "evaluated_value_per_racc": None,
            "threshold_value": None,
            "disqualified_by": None,
            "basis_panel_id": None,
        }
    else:
        panel = _latest_current_panel(locked["id"], lv["nutrient_basis"])
        if panel is None:
            raise ApiError(
                "ERR_PANEL_NOT_CURRENT", 409,
                "No CURRENT nutrient panel exists for the locked recipe and nutrient basis",
            )
        ra = db["racc_assignments"].get(lv["racc_assignment_id"])
        result = _evaluate_claim(
            claim_type, lv["market_code"], panel["_raw"],
            ra["racc_g"], ra["serving_size_g"], panel["id"],
        )
    rec = _new_record(
        label_version_id=lv["id"],
        claim_type=claim_type,
        **result,
    )
    db["claims"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/label-versions/<lvid>/claims", methods=["GET"])
def list_claims_of_label(lvid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    items = _claims_of_label(lvid)
    return ok_list([_pub(c) for c in _sorted(items)])


@app.route("/api/claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    claim = _get_claim(cid)
    _enforce_scope(role, uid, _cid_of_claim(claim))
    return ok_object(_pub(claim))


@app.route("/api/claims", methods=["GET"])
def list_claims():
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    items = list(db["claims"].values())
    flt = request.args.get("basis_panel_id")
    if flt is not None:
        items = [c for c in items if c.get("basis_panel_id") == flt]
    if role in ENTITY_BACKED_ROLES:
        items = [c for c in items if _cid_of_claim(c) == uid]
    return ok_list([_pub(c) for c in _sorted(items)])


# =============================================================================
# MarketVariant endpoints
# =============================================================================


def _variant_window_overlap_check(product_id, market_code, start, end, exclude_id=None):
    for v in db["market_variants"].values():
        if v["id"] == exclude_id or v["status"] == "RETIRED":
            continue
        base = db["label_versions"].get(v["label_version_id"])
        if base is None:
            continue
        if base["product_id"] != product_id or v["market_code"] != market_code:
            continue
        if _windows_overlap(start, end, v["_start_dt"], v["_end_dt"]):
            raise ApiError(
                "ERR_MARKET_WINDOW_OVERLAP", 409,
                "Effective window overlaps another non-RETIRED variant for this product and market",
            )


@app.route("/api/label-versions/<lvid>/market-variants", methods=["POST"])
def create_market_variant(lvid):
    uid, role = _auth()
    _require_role(role, ["LabelAnalyst"])
    lv = _get_label(lvid)
    body = _body()
    market_code = _as_enum(_req(body, "market_code"), "market_code", MARKETS)
    effective_start_raw = _as_str(_req(body, "effective_start"), "effective_start")
    start_dt = _parse_dt(effective_start_raw, "effective_start")
    effective_end_raw = body.get("effective_end")
    end_dt = None
    if effective_end_raw is not None:
        end_dt = _parse_dt(effective_end_raw, "effective_end")
    translated = body.get("translated_contains_text")
    if translated is not None:
        translated = _as_str(translated, "translated_contains_text")
    # Priority 6: uniqueness, then overlap.
    for v in db["market_variants"].values():
        if (
            v["label_version_id"] == lv["id"]
            and v["market_code"] == market_code
            and v["status"] != "RETIRED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_MARKET_VARIANT", 409,
                "A non-RETIRED variant already exists for this label and market",
            )
    product = db["products"][lv["product_id"]]
    _variant_window_overlap_check(product["id"], market_code, start_dt, end_dt)
    # Priority 7: window coherence.
    if end_dt is not None and end_dt <= start_dt:
        raise ApiError(
            "ERR_WINDOW_INVALID", 422,
            "effective_end must be strictly after effective_start",
        )
    # Priority 8: target market must differ from the base label's market.
    if market_code == lv["market_code"]:
        raise ApiError(
            "ERR_SAME_MARKET_VARIANT", 422,
            "Variant target market must differ from the base label's market",
        )
    rec = _new_record(
        label_version_id=lv["id"],
        market_code=market_code,
        effective_start=effective_start_raw,
        effective_end=effective_end_raw,
        translated_contains_text=translated,
        status="DRAFT",
    )
    rec["_start_dt"] = start_dt
    rec["_end_dt"] = end_dt
    db["market_variants"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/label-versions/<lvid>/market-variants", methods=["GET"])
def list_market_variants(lvid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    items = [v for v in db["market_variants"].values() if v["label_version_id"] == lvid]
    return ok_list([_pub(v) for v in _sorted(items)])


@app.route("/api/market-variants/<vid>/activate", methods=["POST"])
def activate_variant(vid):
    uid, role = _auth()
    _require_role(role, ["QualityManager"])
    variant = _get_variant(vid)
    _enforce_scope(role, uid, _cid_of_variant(variant))
    if variant["status"] != "DRAFT":
        raise err_state("Only a DRAFT variant can be activated")
    base = db["label_versions"][variant["label_version_id"]]
    if base["review_status"] != "APPROVED":
        raise ApiError(
            "ERR_LABEL_NOT_APPROVED", 409,
            "Variant activation requires the base label to be APPROVED",
        )
    product = db["products"][base["product_id"]]
    _variant_window_overlap_check(
        product["id"], variant["market_code"],
        variant["_start_dt"], variant["_end_dt"], exclude_id=variant["id"],
    )
    now = _logical_clock()
    if not (variant["_start_dt"] <= now and (variant["_end_dt"] is None or now < variant["_end_dt"])):
        raise ApiError(
            "ERR_VARIANT_NOT_IN_WINDOW", 409,
            "The logical clock is outside the variant's effective window",
        )
    variant["status"] = "ACTIVE"
    _touch(variant)
    return ok_object(_pub(variant))


@app.route("/api/market-variants/<vid>/retire", methods=["POST"])
def retire_variant(vid):
    uid, role = _auth()
    _require_role(role, ["QualityManager"])
    variant = _get_variant(vid)
    _enforce_scope(role, uid, _cid_of_variant(variant))
    if variant["status"] != "ACTIVE":
        raise err_state("Only an ACTIVE variant can be retired")
    variant["status"] = "RETIRED"
    _touch(variant)
    return ok_object(_pub(variant))


# =============================================================================
# FormatCheck endpoints
# =============================================================================


@app.route("/api/label-versions/<lvid>/format-checks", methods=["GET"])
def list_format_checks(lvid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    lv = _get_label(lvid)
    _enforce_scope(role, uid, _cid_of_label(lv))
    items = [f for f in db["format_checks"].values() if f["label_version_id"] == lvid]
    return ok_list([_pub(f) for f in _sorted(items)])


# =============================================================================
# ArtworkAudit / AuditFinding endpoints
# =============================================================================


@app.route("/api/clients/<cid>/artwork-audits", methods=["POST"])
def create_artwork_audit(cid):
    uid, role = _auth()
    _require_role(role, ["ComplianceAuditor"])
    client = _get_client(cid)
    body = _body()
    # Body-supplied FK existence precedes shape checks (PRD §2.8).
    product = None
    if isinstance(body.get("product_id"), str):
        product = db["products"].get(body["product_id"])
        if product is None:
            raise err_not_found("product_id does not exist")
    label = None
    if isinstance(body.get("label_version_id"), str):
        label = db["label_versions"].get(body["label_version_id"])
        if label is None:
            raise err_not_found("label_version_id does not exist")
    product_id = _as_str(_req(body, "product_id"), "product_id")
    if product is None:
        product = db["products"].get(product_id)
        if product is None:
            raise err_not_found("product_id does not exist")
    label_version_id = _as_str(_req(body, "label_version_id"), "label_version_id")
    if label is None:
        label = db["label_versions"].get(label_version_id)
        if label is None:
            raise err_not_found("label_version_id does not exist")
    facility_code = _as_str(_req(body, "facility_code"), "facility_code")
    scheduled_start_raw = _as_str(_req(body, "scheduled_start"), "scheduled_start")
    start_dt = _parse_dt(scheduled_start_raw, "scheduled_start")
    scheduled_end_raw = _as_str(_req(body, "scheduled_end"), "scheduled_end")
    end_dt = _parse_dt(scheduled_end_raw, "scheduled_end")
    scoring_method = body.get("scoring_method", "WEIGHTED")
    scoring_method = _as_enum(scoring_method, "scoring_method", SCORING_METHODS)
    # Priority 6: facility scheduling with one-day buffer.
    for other in db["artwork_audits"].values():
        if other["facility_code"] != facility_code:
            continue
        if other["status"] not in ("SCHEDULED", "FINDINGS_LOGGED"):
            continue
        ok_before = end_dt <= other["_start_dt"] - FACILITY_BUFFER
        ok_after = start_dt >= other["_end_dt"] + FACILITY_BUFFER
        if not (ok_before or ok_after):
            raise ApiError(
                "ERR_FACILITY_SCHEDULE_OVERLAP", 409,
                "Facility has another audit within the one-day scheduling buffer",
            )
    # Priority 7: window coherence.
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_WINDOW_INVALID", 422,
            "scheduled_end must be strictly after scheduled_start",
        )
    # Priority 8: audit scope consistency.
    if (
        product["client_id"] != client["id"]
        or label["product_id"] != product["id"]
        or label["release_status"] != "RELEASED"
    ):
        raise ApiError(
            "ERR_AUDIT_SCOPE_INCONSISTENT", 422,
            "Product must belong to the path client and the label version must belong to the product and be RELEASED",
        )
    rec = _new_record(
        client_id=client["id"],
        product_id=product_id,
        label_version_id=label_version_id,
        facility_code=facility_code,
        scheduled_start=scheduled_start_raw,
        scheduled_end=scheduled_end_raw,
        scoring_method=scoring_method,
        status="SCHEDULED",
        conformance_score=None,
        result=None,
    )
    rec["_start_dt"] = start_dt
    rec["_end_dt"] = end_dt
    db["artwork_audits"][rec["id"]] = rec
    return ok_object(_pub(rec), 201)


@app.route("/api/artwork-audits/<aid>", methods=["GET"])
def get_artwork_audit(aid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    audit = _get_audit(aid)
    _enforce_scope(role, uid, _cid_of_audit(audit))
    return ok_object(_pub(audit))


@app.route("/api/artwork-audits", methods=["GET"])
def list_artwork_audits():
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    items = list(db["artwork_audits"].values())
    for param in ("client_id", "product_id", "label_version_id"):
        flt = request.args.get(param)
        if flt is not None:
            items = [a for a in items if a.get(param) == flt]
    if role in ENTITY_BACKED_ROLES:
        items = [a for a in items if a["client_id"] == uid]
    return ok_list([_pub(a) for a in _sorted(items)])


@app.route("/api/artwork-audits/<aid>/findings", methods=["POST"])
def create_audit_finding(aid):
    uid, role = _auth()
    _require_role(role, ["ComplianceAuditor"])
    audit = _get_audit(aid)
    body = _body()
    severity = _as_enum(_req(body, "severity"), "severity", SEVERITIES)
    field_ref = _as_enum(_req(body, "field_ref"), "field_ref", FIELD_REFS)
    on_pack_text = _as_str(_req(body, "on_pack_text"), "on_pack_text")
    approved_text = _as_str(_req(body, "approved_text"), "approved_text")
    if audit["status"] not in ("SCHEDULED", "FINDINGS_LOGGED"):
        raise err_state("Findings may only be logged while the audit is SCHEDULED or FINDINGS_LOGGED")
    rec = _new_record(
        audit_id=audit["id"],
        severity=severity,
        field_ref=field_ref,
        on_pack_text=on_pack_text,
        approved_text=approved_text,
    )
    db["audit_findings"][rec["id"]] = rec
    if audit["status"] == "SCHEDULED":
        audit["status"] = "FINDINGS_LOGGED"
        _touch(audit)
    return ok_object(_pub(rec), 201)


@app.route("/api/artwork-audits/<aid>/findings", methods=["GET"])
def list_audit_findings(aid):
    uid, role = _auth()
    _require_role(role, ALL_GET_ROLES)
    audit = _get_audit(aid)
    _enforce_scope(role, uid, _cid_of_audit(audit))
    items = [f for f in db["audit_findings"].values() if f["audit_id"] == aid]
    return ok_list([_pub(f) for f in _sorted(items)])


@app.route("/api/artwork-audits/<aid>/close", methods=["POST"])
def close_artwork_audit(aid):
    uid, role = _auth()
    _require_role(role, ["ComplianceAuditor"])
    audit = _get_audit(aid)
    if audit["status"] != "FINDINGS_LOGGED":
        raise err_state("An audit can only be closed from FINDINGS_LOGGED")
    findings = [f for f in db["audit_findings"].values() if f["audit_id"] == aid]
    if audit["scoring_method"] == "BINARY":
        score = 100 if not findings else 0
        result = "PASS" if score == 100 else "FAIL"
    else:  # WEIGHTED
        deduction = (
            10 * sum(1 for f in findings if f["severity"] == "CRITICAL")
            + 4 * sum(1 for f in findings if f["severity"] == "MAJOR")
            + 1 * sum(1 for f in findings if f["severity"] == "MINOR")
        )
        score = max(0, 100 - deduction)
        result = "PASS" if score >= 90 else "FAIL"
    audit["conformance_score"] = score
    audit["result"] = result
    audit["status"] = "CLOSED"
    _touch(audit)
    return ok_object(_pub(audit))


# =============================================================================
# Logical clock (test-driving utility)
# =============================================================================


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = _auth()
    _require_role(role, ["PlatformAdmin"])
    body = _body()
    to_iso8601 = _as_str(_req(body, "to_iso8601"), "to_iso8601")
    dt = _parse_dt(to_iso8601, "to_iso8601")
    _clock["dt"] = dt
    return ok_object({"current_utc": _iso_z(dt)})


# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
