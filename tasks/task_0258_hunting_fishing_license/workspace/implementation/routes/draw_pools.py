"""DrawPool endpoints incl. the draw-execution cascade (PRD §3.4, §3.8)."""
from flask import Blueprint, request

import serialize
from db import store, parse_dt
from errors import (
    err, ERR_INVALID_STATE, ERR_STALE_POOL_VERSION, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_enum, as_int, parse_pagination, paginate,
)
from services.core import (
    get_species_season_or_404, get_license_product_or_404, get_draw_pool_or_404,
    compute_priority_score, compute_license_fee, check_residency_restriction,
    MAX_PREFERENCE_POINTS,
)

bp = Blueprint("draw_pools", __name__)

SCORING_MODELS = {"SQUARED", "LINEAR"}


@bp.route("/draw-pools", methods=["POST"])
@require_roles("DrawOfficer")
def create_draw_pool():
    body = get_json_body()
    species_season_id = as_nonempty_str(body, "species_season_id", required=True)
    license_product_id = as_nonempty_str(body, "license_product_id", required=True)
    quota = as_int(body, "quota", required=True, minimum=0)
    entry_deadline = as_nonempty_str(body, "entry_deadline", required=True)
    scoring_model = as_enum(
        body, "scoring_model", SCORING_MODELS, required=False, default="SQUARED"
    )

    try:
        parse_dt(entry_deadline)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "entry_deadline is not a valid ISO 8601 datetime")

    # FK existence in body order (PRD §2.5).
    get_species_season_or_404(species_season_id)
    get_license_product_or_404(license_product_id)

    record = {
        "species_season_id": species_season_id,
        "license_product_id": license_product_id,
        "quota": quota,
        "scoring_model": scoring_model,
        "status": "ACCEPTING",
        "awarded_count": 0,
        "entry_deadline": entry_deadline,
    }
    store.stamp_new(record)
    store.draw_pools[record["id"]] = record
    return success(serialize.draw_pool(record), status=201, response_type="object")


@bp.route("/draw-pools/<id>", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def get_draw_pool(id):
    record = get_draw_pool_or_404(id)
    return success(serialize.draw_pool(record), status=200, response_type="object")


@bp.route("/draw-pools", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def list_draw_pools():
    limit, offset = parse_pagination()
    items = list(store.draw_pools.values())
    season_id = request.args.get("species_season_id")
    if season_id is not None:
        items = [r for r in items if r["species_season_id"] == season_id]
    product_id = request.args.get("license_product_id")
    if product_id is not None:
        items = [r for r in items if r["license_product_id"] == product_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.draw_pool(r) for r in page], limit, offset, total
    )


@bp.route("/draw-pools/<id>/close-entries", methods=["POST"])
@require_roles("DrawOfficer")
def close_entries(id):
    record = get_draw_pool_or_404(id)
    # State precedence before the temporal precondition (PRD §2.6 / §3.4).
    if record["status"] != "ACCEPTING":
        raise err(ERR_INVALID_STATE, "Pool is not ACCEPTING")
    # Only once the clock is at or past entry_deadline (PRD §3.4).
    now = store.now()
    if now < parse_dt(record["entry_deadline"]):
        raise err(ERR_INVALID_STATE, "Entry deadline has not yet passed")
    record["status"] = "CLOSED"
    store.touch(record)
    return success(serialize.draw_pool(record), status=200, response_type="object")


@bp.route("/draw-pools/<id>/execute-draw", methods=["POST"])
@require_roles("DrawOfficer")
def execute_draw(id):
    body = get_json_body()
    # expected_draw_pool_version is mandatory on this endpoint (PRD §2.7).
    expected = as_int(body, "expected_draw_pool_version", required=True)

    record = get_draw_pool_or_404(id)

    # State (priority 4) before OCC (priority 5) per PRD §2.6.
    if record["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE, "Pool is not CLOSED")
    if expected != record["version"]:
        raise err(ERR_STALE_POOL_VERSION, "Stale DrawPool version")

    # The bound SpeciesSeason must be OPEN at execution time (PRD §3.8).
    season = store.species_seasons.get(record["species_season_id"])
    if season is None or season["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Bound SpeciesSeason is not OPEN")

    product = store.license_products[record["license_product_id"]]

    # Gather SUBMITTED applications for this pool.
    submitted = [
        a for a in store.draw_applications.values()
        if a["draw_pool_id"] == record["id"] and a["status"] == "SUBMITTED"
    ]

    # Compute priority_score per application from frozen snapshots (PRD §3.8).
    for a in submitted:
        a["priority_score"] = compute_priority_score(
            a["points_at_entry"], a["bonus_at_entry"], record["scoring_model"]
        )

    # Rank by priority_score DESC, tie-break created_at ASC (then creation seq).
    ranked = sorted(
        submitted,
        key=lambda a: (-a["priority_score"], a["created_at"], a["_seq"]),
    )

    quota = record["quota"]
    awarded = ranked[:quota]
    losers = ranked[quota:]

    # Award the top quota: AWARDED -> mint License -> reset points (cascade).
    for a in awarded:
        a["status"] = "AWARDED"
        applicant = store.applicants[a["applicant_id"]]
        # Residency restriction still applies to the minted TAG (PRD §3.5).
        check_residency_restriction(product, applicant)
        fee = compute_license_fee(product, applicant, "DRAW_AWARD")
        lic = {
            "applicant_id": a["applicant_id"],
            "license_product_id": record["license_product_id"],
            "draw_application_id": a["id"],
            "issued_via": "DRAW_AWARD",
            "fee_charged_cents": fee,
            "status": "ISSUED",
            "superseded_by_id": None,
        }
        store.stamp_new(lic)
        store.licenses[lic["id"]] = lic
        a["issued_license_id"] = lic["id"]
        store.touch(a)
        # Reset preference_points to 0 and bump applicant version (PRD §3.8).
        applicant["preference_points"] = 0
        store.touch(applicant)

    # Remaining SUBMITTED -> UNSUCCESSFUL, +1 point clamped to cap.
    for a in losers:
        a["status"] = "UNSUCCESSFUL"
        store.touch(a)
        applicant = store.applicants[a["applicant_id"]]
        applicant["preference_points"] = min(
            applicant["preference_points"] + 1, MAX_PREFERENCE_POINTS
        )
        store.touch(applicant)

    # Finalize pool.
    record["awarded_count"] = len(awarded)
    record["status"] = "DRAWN"
    store.touch(record)  # version increment is the concurrency advance.
    return success(serialize.draw_pool(record), status=200, response_type="object")
