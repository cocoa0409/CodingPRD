"""PRD 3.1 - briefing the pack."""
from flask import Blueprint, request

import calc
from core import new_row, now_iso, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    load,
    need_code_array,
    need_enum,
    need_object,
    need_string,
    ok,
    paginate,
)
from serialize import brief_json

bp = Blueprint("briefs", __name__)

_STRUCTURAL_KEYS = ("component_type", "dimensions_mm", "substrate_class", "print_process")


def _validate_structural_spec(spec):
    for key in _STRUCTURAL_KEYS:
        if key not in spec or spec[key] is None:
            invalid("structural_spec.%s is required" % key)
    if spec["component_type"] not in calc.COMPONENT_TYPES:
        invalid("structural_spec.component_type is not a declared member")
    if spec["substrate_class"] not in calc.SUBSTRATE_CLASSES:
        invalid("structural_spec.substrate_class is not a declared member")
    if spec["print_process"] not in calc.PRINT_PROCESSES:
        invalid("structural_spec.print_process is not a declared member")
    dims = spec["dimensions_mm"]
    if not isinstance(dims, dict):
        invalid("structural_spec.dimensions_mm must be an object")
    for edge in ("l", "w", "h"):
        value = dims.get(edge)
        if not isinstance(value, int) or isinstance(value, bool):
            invalid("structural_spec.dimensions_mm.%s must be an integer" % edge)
    return spec


def _validate_net_contents(decl):
    value = decl.get("metric_value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        invalid("net_contents_declaration.metric_value must be a number")
    if value <= 0:
        invalid("net_contents_declaration.metric_value must be greater than zero")
    if decl.get("metric_uom") not in calc.METRIC_UOMS:
        invalid("net_contents_declaration.metric_uom is not a declared member")
    us_value = decl.get("us_value")
    us_uom = decl.get("us_uom")
    if us_value is None:
        return decl
    if not isinstance(us_value, (int, float)) or isinstance(us_value, bool):
        invalid("net_contents_declaration.us_value must be a number")
    if us_uom not in calc.US_UOMS:
        invalid("net_contents_declaration.us_uom is not a declared member")
    return decl


@bp.route("/briefs", methods=["POST"])
def create_brief():
    auth(["PackagingCoordinator"])
    body = body_fields(
        [
            "sku_code",
            "product_name",
            "regulatory_scheme",
            "market_codes",
            "language_codes",
            "required_element_codes",
            "structural_spec",
            "net_contents_declaration",
        ]
    )
    sku_code = need_string(body, "sku_code", 4, 32)
    product_name = need_string(body, "product_name", 3, 120)
    scheme = need_enum(body, "regulatory_scheme", calc.REGULATORY_SCHEMES)
    market_codes = need_code_array(body, "market_codes", calc.MARKET_CODE_PATTERN, 1, 6)
    language_codes = need_code_array(body, "language_codes", calc.LANGUAGE_CODE_PATTERN, 1, 6)
    element_codes = need_code_array(
        body, "required_element_codes", None, 1, 7, members=calc.ELEMENT_CODES
    )
    spec = _validate_structural_spec(need_object(body, "structural_spec"))
    declaration = _validate_net_contents(need_object(body, "net_contents_declaration"))

    for existing in rows("briefs"):
        if existing["sku_code"] == sku_code:
            fail("ERR_DUPLICATE_SKU_CODE", "sku_code %s is already registered" % sku_code)

    row = new_row(
        "briefs",
        {
            "sku_code": sku_code,
            "product_name": product_name,
            "regulatory_scheme": scheme,
            "market_codes": market_codes,
            "language_codes": language_codes,
            "required_element_codes": element_codes,
            "structural_spec": spec,
            "net_contents_declaration": declaration,
            "status": "DRAFT",
            "review_note": None,
            "approved_by_user_id": None,
            "approved_at": None,
        },
    )
    return created(brief_json(row))


@bp.route("/briefs/<brief_id>", methods=["GET"])
def get_brief(brief_id):
    auth(ALL_ROLES)
    return ok(brief_json(load("briefs", brief_id)))


@bp.route("/briefs", methods=["GET"])
def list_briefs():
    auth(ALL_ROLES)
    items = rows("briefs")
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    # PRD 2.3: briefs are the collection returned newest first.
    items = sorted(items, key=lambda b: (b["created_at"], b["_seq"]), reverse=True)
    return paginate(items, brief_json)


@bp.route("/briefs/<brief_id>", methods=["PATCH"])
def patch_brief(brief_id):
    auth(["PackagingCoordinator"])
    brief = load("briefs", brief_id)
    body = body_fields(
        [],
        [
            "product_name",
            "market_codes",
            "language_codes",
            "required_element_codes",
            "structural_spec",
            "net_contents_declaration",
        ],
    )
    updates = {}
    if "product_name" in body:
        updates["product_name"] = need_string(body, "product_name", 3, 120)
    if "market_codes" in body:
        updates["market_codes"] = need_code_array(
            body, "market_codes", calc.MARKET_CODE_PATTERN, 1, 6
        )
    if "language_codes" in body:
        updates["language_codes"] = need_code_array(
            body, "language_codes", calc.LANGUAGE_CODE_PATTERN, 1, 6
        )
    if "required_element_codes" in body:
        updates["required_element_codes"] = need_code_array(
            body, "required_element_codes", None, 1, 7, members=calc.ELEMENT_CODES
        )
    if "structural_spec" in body:
        updates["structural_spec"] = _validate_structural_spec(
            need_object(body, "structural_spec")
        )
    if "net_contents_declaration" in body:
        updates["net_contents_declaration"] = _validate_net_contents(
            need_object(body, "net_contents_declaration")
        )

    if brief["status"] != "DRAFT":
        fail("ERR_BRIEF_STATE_INVALID", "only a DRAFT brief may be edited")

    brief.update(updates)
    touch(brief)
    return ok(brief_json(brief))


@bp.route("/briefs/<brief_id>/decision", methods=["POST"])
def decide_brief(brief_id):
    user_id, _role = auth(["RegulatoryReviewer"])
    brief = load("briefs", brief_id)
    body = body_fields(["decision"], ["review_note"])
    decision = need_enum(body, "decision", ("APPROVED", "REJECTED"))
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        invalid("review_note must be a string")
    if decision == "REJECTED" and (review_note is None or not review_note.strip()):
        invalid("a rejection requires a non-empty review_note")

    if brief["status"] != "DRAFT":
        fail("ERR_BRIEF_STATE_INVALID", "only a DRAFT brief may be decided")
    if not brief["required_element_codes"]:
        invalid("approval requires at least one required element code")
    if not (brief["net_contents_declaration"].get("metric_value") or 0) > 0:
        invalid("approval requires a positive declared metric_value")

    brief["status"] = decision
    brief["review_note"] = review_note
    brief["approved_by_user_id"] = user_id
    brief["approved_at"] = now_iso()
    touch(brief)
    return ok(brief_json(brief))
