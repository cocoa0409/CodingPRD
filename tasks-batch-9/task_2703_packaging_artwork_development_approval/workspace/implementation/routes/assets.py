"""PRD 3.3 - market/component artwork variants."""
from flask import Blueprint, request

import calc
from core import new_row, rows
from errors import fail
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    load,
    need_bool,
    need_code_array,
    need_enum,
    need_int,
    need_nonempty,
    need_string,
    ok,
    paginate,
    raw_body,
)
from serialize import asset_json

bp = Blueprint("assets", __name__)


@bp.route("/artwork-assets", methods=["POST"])
def create_asset():
    auth(["PackagingCoordinator"])
    raw = raw_body()
    reference = raw.get("brief_id")
    if isinstance(reference, str) and reference:
        load("briefs", reference)

    body = body_fields(
        ["brief_id", "market_code", "language_codes", "component_type", "substrate_class",
         "plate_budget_cents"],
        ["brand_critical_color"],
    )
    brief_id = need_nonempty(body, "brief_id")
    market_code = need_string(body, "market_code", 2, 2, calc.MARKET_CODE_PATTERN)
    language_codes = need_code_array(body, "language_codes", calc.LANGUAGE_CODE_PATTERN, 1, 6)
    component_type = need_enum(body, "component_type", calc.COMPONENT_TYPES)
    substrate_class = need_enum(body, "substrate_class", calc.SUBSTRATE_CLASSES)
    plate_budget_cents = need_int(body, "plate_budget_cents", 0)
    brand_critical = need_bool(body, "brand_critical_color", default=False)

    brief = load("briefs", brief_id)

    for existing in rows("assets"):
        if (
            existing["brief_id"] == brief["id"]
            and existing["market_code"] == market_code
            and existing["component_type"] == component_type
        ):
            fail(
                "ERR_DUPLICATE_ASSET_VARIANT",
                "an asset for this brief, market and component already exists",
            )

    if market_code not in brief["market_codes"]:
        fail("ERR_MARKET_CODE_NOT_IN_BRIEF", "market_code is not covered by the brief")
    for language in language_codes:
        if language not in brief["language_codes"]:
            fail(
                "ERR_LANGUAGE_CODE_NOT_IN_BRIEF",
                "language_code %s is not covered by the brief" % language,
            )

    row = new_row(
        "assets",
        {
            "brief_id": brief["id"],
            "market_code": market_code,
            "language_codes": language_codes,
            "component_type": component_type,
            "substrate_class": substrate_class,
            "brand_critical_color": brand_critical,
            "plate_budget_cents": plate_budget_cents,
            "standard_unit_cost_cents": calc.STANDARD_UNIT_COST_CENTS[component_type],
            "obsolescence_state": "ACTIVE",
            "version_counter": 0,
            "current_approved_version_id": None,
        },
    )
    return created(asset_json(row))


@bp.route("/artwork-assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    auth(ALL_ROLES)
    return ok(asset_json(load("assets", asset_id)))


@bp.route("/artwork-assets", methods=["GET"])
def list_assets():
    auth(ALL_ROLES)
    brief_id = filter_exists("briefs", "brief_id")
    approved_id = filter_exists("versions", "current_approved_version_id")
    items = rows("assets")
    if brief_id:
        items = [a for a in items if a["brief_id"] == brief_id]
    if approved_id:
        items = [a for a in items if a.get("current_approved_version_id") == approved_id]
    market_code = request.args.get("market_code")
    if market_code:
        items = [a for a in items if a["market_code"] == market_code]
    obsolescence_state = request.args.get("obsolescence_state")
    if obsolescence_state:
        items = [a for a in items if a["obsolescence_state"] == obsolescence_state]
    items = sorted(items, key=lambda a: (a["created_at"], a["_seq"]))
    return paginate(items, asset_json)
