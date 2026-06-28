"""Quotes (PRD 3.5, 3.6). Pricing, the minimum floor, deposits, and the
send/revise/accept/expire lifecycle with OCC on acceptance."""

from flask import Blueprint, request

from clock import clock
from common import (
    get_json_body,
    iso_format,
    paginate,
    public,
    require_fields,
    require_number,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import (
    get_child_or_404,
    get_project_or_404,
    ref_design_or_404,
    ref_scope_or_404,
)
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success
from services.calculations import (
    DEPOSIT_MAX_PCT,
    DEPOSIT_MIN_PCT,
    compute_deposit_amount,
    compute_quote_pricing,
)
from services.project_service import expire_quote_if_due

bp = Blueprint("quotes", __name__)


def _price_quote(quote, design, scope):
    """Compute and store all quote money components on the quote record."""
    turf = db.turf_products.get(design["turf_product_id"])
    infill = db.infill_products.get(design["infill_product_id"])
    pricing = compute_quote_pricing(
        net_area_sqft=design["net_area_sqft"],
        variant=design["variant"],
        turf_price_per_sqft_cents=turf["price_per_sqft_cents"],
        infill_price_per_sqft_cents=infill["price_per_sqft_cents"],
        excavation_cost_cents=scope["excavation_cost_cents"],
        drainage_cost_cents=scope["drainage_cost_cents"],
        promo_code=quote.get("promo_code"),
    )
    quote.update(pricing)
    quote["variant_kind"] = design["variant"]
    quote["deposit_amount_cents"] = compute_deposit_amount(
        pricing["total_cents"], quote["deposit_pct"]
    )


def _validate_deposit_pct(body, default):
    if "deposit_pct" not in body or body["deposit_pct"] is None:
        return default
    v = require_number(body, "deposit_pct")
    # Range check on the accepted input domain (priority 6) — before clamping.
    if v < DEPOSIT_MIN_PCT or v > DEPOSIT_MAX_PCT:
        raise err("ERR_INVALID_REQUEST", "deposit_pct must be within 0.10..0.50.")
    return v


@bp.route("/projects/<project_id>/quotes", methods=["POST"])
def create_quote(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["design_layout_id", "base_prep_scope_id"])
    design = ref_design_or_404(body["design_layout_id"], project_id)
    scope = ref_scope_or_404(body["base_prep_scope_id"], project_id)

    promo_code = None
    if "promo_code" in body and body["promo_code"] is not None:
        promo_code = require_string(body, "promo_code")
    deposit_pct = _validate_deposit_pct(body, 0.30)

    rec = {
        "project_id": project_id,
        "design_layout_id": design["id"],
        "base_prep_scope_id": scope["id"],
        "promo_code": promo_code,
        "deposit_pct": deposit_pct,
        "status": "DRAFT",
        "superseded_by_quote_id": None,
        # Logical-clock instant at creation — the TTL anchor for expiry (PRD 3.6).
        "_logical_created_at": iso_format(clock.now()),
    }
    _price_quote(rec, design, scope)
    stamp_new(rec)
    db.quotes[rec["id"]] = rec
    return success(public(rec), status=201)


def _serialize_quote(quote):
    expire_quote_if_due(quote)
    return public(quote)


@bp.route("/projects/<project_id>/quotes", methods=["GET"])
def list_quotes(project_id):
    uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    items = [q for q in db.quotes.values() if q["project_id"] == project_id]
    for field in ("design_layout_id", "base_prep_scope_id", "superseded_by_quote_id", "status"):
        val = request.args.get(field)
        if val is not None:
            # Apply lazy expiry before status filtering so EXPIRED is visible.
            for q in items:
                expire_quote_if_due(q)
            items = [q for q in items if q.get(field) == val]
    data, pagination = paginate(items, _serialize_quote)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/quotes/<quote_id>", methods=["GET"])
def get_quote(project_id, quote_id):
    uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    quote = get_child_or_404(db.quotes, quote_id, project_id, "Quote")
    return success(_serialize_quote(quote), status=200)


@bp.route("/projects/<project_id>/quotes/<quote_id>/send", methods=["POST"])
def send_quote(project_id, quote_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    project = get_project_or_404(project_id)
    quote = get_child_or_404(db.quotes, quote_id, project_id, "Quote")
    expire_quote_if_due(quote)

    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not in DRAFT status.")

    # The referenced base-prep scope must be FINALIZED (priority 17).
    scope = db.base_prep_scopes.get(quote["base_prep_scope_id"])
    if scope is None or scope["status"] != "FINALIZED":
        raise err("ERR_SCOPE_NOT_FINALIZED", "Quote's base prep scope is not FINALIZED.")

    # Freeze the total (final variant) from the then-current scope + design.
    design = db.design_layouts.get(quote["design_layout_id"])
    _price_quote(quote, design, scope)

    quote["status"] = "SENT"
    touch(quote)

    # PRD 3.6: "Sending ... advances the project's workflow dimension from
    # DESIGNED to QUOTED, and increments the project's version." The workflow
    # advance only applies when the project is still DESIGNED, but the version
    # increment is a coordinate, unconditional effect of every send (the PRD
    # attaches no "first send only" qualifier, unlike the "very first measure"
    # clause in 3.1).
    if project["workflow_status"] == "DESIGNED":
        project["workflow_status"] = "QUOTED"
    touch(project)

    return success(public(quote), status=200)


@bp.route("/projects/<project_id>/quotes/<quote_id>/revise", methods=["POST"])
def revise_quote(project_id, quote_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    quote = get_child_or_404(db.quotes, quote_id, project_id, "Quote")
    expire_quote_if_due(quote)

    if quote["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not in SENT status.")

    # Project must have no ACCEPTED quote.
    for q in db.quotes.values():
        if q["project_id"] == project_id and q["status"] == "ACCEPTED":
            raise err("ERR_INVALID_STATE", "Project already has an ACCEPTED quote.")

    body = get_json_body()
    promo_code = quote.get("promo_code")
    if "promo_code" in body and body["promo_code"] is not None:
        promo_code = require_string(body, "promo_code")
    deposit_pct = _validate_deposit_pct(body, quote["deposit_pct"])

    design = db.design_layouts.get(quote["design_layout_id"])
    scope = db.base_prep_scopes.get(quote["base_prep_scope_id"])

    successor = {
        "project_id": project_id,
        "design_layout_id": quote["design_layout_id"],
        "base_prep_scope_id": quote["base_prep_scope_id"],
        "promo_code": promo_code,
        "deposit_pct": deposit_pct,
        "status": "DRAFT",
        "superseded_by_quote_id": None,
        "_logical_created_at": iso_format(clock.now()),
    }
    _price_quote(successor, design, scope)
    stamp_new(successor)
    db.quotes[successor["id"]] = successor

    quote["status"] = "REVISED"
    quote["superseded_by_quote_id"] = successor["id"]
    touch(quote)

    return success(public(successor), status=201)


@bp.route("/projects/<project_id>/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(project_id, quote_id):
    uid, role = get_auth()
    require_role(role, {"Customer", "OpsAdmin"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    quote = get_child_or_404(db.quotes, quote_id, project_id, "Quote")
    expire_quote_if_due(quote)

    body = get_json_body()
    require_fields(body, ["expected_project_version"])
    expected = body["expected_project_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be an integer.")

    # State (priority 8): quote must be SENT and finance UNBILLED.
    if quote["status"] != "SENT" or project["finance_status"] != "UNBILLED":
        raise err("ERR_INVALID_STATE", "Quote is not acceptable in its current state.")

    # OCC (priority 9): expected_project_version must match Project.version.
    if expected != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "Project version is stale.")

    quote["status"] = "ACCEPTED"
    touch(quote)

    # Void every other non-terminal quote on the project.
    for q in db.quotes.values():
        if (
            q["project_id"] == project_id
            and q["id"] != quote["id"]
            and q["status"] in ("DRAFT", "SENT", "REVISED")
        ):
            q["status"] = "VOID"
            touch(q)

    project["finance_status"] = "DEPOSIT_DUE"
    touch(project)

    return success(public(quote), status=200)
