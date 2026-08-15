"""PayBand lifecycle: create/price/approve/publish/reopen/overlap-report (§3.4-§3.5)."""
from decimal import Decimal
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, stale_version, program_state_forbids,
    flsa_salary_basis_violation, band_overlap_exceeds_policy,
    progression_below_policy, duplicate_band, referenced_entity_state,
)
from services.common import (
    now_iso, require_fields, parse_pagination, sort_by_created_at, paginate,
    bump, parse_non_negative_number, FLSA_ANNUAL_MINIMUM_CENTS,
)
from services import clock, pricing
from services.employee_health import recompute_employee_health

bp = Blueprint("bands", __name__)

BAND_STATES = ["DRAFT", "PRICED", "COMP_APPROVED", "PUBLISHED", "SUPERSEDED"]
PRICING_VARIANTS = ["PROVISIONAL", "OFFICIAL"]
TARGET_PERCENTILES = ["P50", "P62_5", "P75"]


def band_view(b):
    return {k: b[k] for k in ("id", "comp_program_id", "job_family_id", "job_level_id",
                              "geo_zone_id", "target_percentile", "spread_pct",
                              "policy_adjustment_factor", "pricing_variant",
                              "market_composite_cents", "composite_cut_count",
                              "midpoint_cents", "min_cents", "max_cents",
                              "geo_ratio_snapshot", "priced_at", "status",
                              "superseded_by_band_id",
                              "created_at", "updated_at", "version")}


def get_band_or_404(bid):
    b = store.pay_bands.get(bid)
    if b is None:
        raise not_found("pay band not found")
    return b


@bp.route("/comp/pay-bands", methods=["POST"])
def create_band():
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["comp_program_id", "job_family_id", "job_level_id",
                          "geo_zone_id", "target_percentile", "spread_pct"])
    prog_id = body["comp_program_id"]
    fam_id = body["job_family_id"]
    lvl_id = body["job_level_id"]
    geo_id = body["geo_zone_id"]
    # Existence left-to-right
    if prog_id not in store.programs:
        raise not_found("comp program not found")
    if fam_id not in store.job_families:
        raise not_found("job family not found")
    if lvl_id not in store.job_levels:
        raise not_found("job level not found")
    if geo_id not in store.geo_zones:
        raise not_found("geo zone not found")
    # Enum
    tp = body["target_percentile"]
    if tp not in TARGET_PERCENTILES:
        raise invalid_enum("target_percentile is not a declared member")
    spread = parse_non_negative_number(body["spread_pct"], "spread_pct")
    paf = body.get("policy_adjustment_factor", 1.0)
    paf = parse_non_negative_number(paf, "policy_adjustment_factor")
    # Referenced state: family must not be RETIRED
    if store.job_families[fam_id]["status"] == "RETIRED":
        raise referenced_entity_state("job family is RETIRED")
    # Uniqueness among non-SUPERSEDED
    for b in store.pay_bands.values():
        if (b["comp_program_id"] == prog_id and b["job_family_id"] == fam_id
                and b["job_level_id"] == lvl_id and b["geo_zone_id"] == geo_id
                and b["status"] != "SUPERSEDED"):
            raise duplicate_band()
    now = now_iso()
    b = {"id": new_id(), "comp_program_id": prog_id, "job_family_id": fam_id,
         "job_level_id": lvl_id, "geo_zone_id": geo_id,
         "target_percentile": tp, "spread_pct": float(spread),
         "policy_adjustment_factor": float(paf),
         "pricing_variant": None, "market_composite_cents": None,
         "composite_cut_count": None, "midpoint_cents": None,
         "min_cents": None, "max_cents": None, "geo_ratio_snapshot": None,
         "priced_at": None, "status": "DRAFT", "superseded_by_band_id": None,
         "created_at": now, "updated_at": now, "version": 1}
    store.pay_bands[b["id"]] = b
    return success_object(band_view(b), 201)


@bp.route("/comp/pay-bands", methods=["GET"])
def list_bands():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.pay_bands.values())
    for arg in ("comp_program_id", "job_family_id", "job_level_id", "geo_zone_id",
                "superseded_by_band_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [b for b in rows if b.get(arg) == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in BAND_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [b for b in rows if b["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([band_view(b) for b in page], limit, offset, total)


@bp.route("/comp/pay-bands/<bid>", methods=["GET"])
def get_band(bid):
    get_auth()
    return success_object(band_view(get_band_or_404(bid)))


@bp.route("/comp/pay-bands/<bid>/price", methods=["POST"])
def price_band(bid):
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["pricing_variant", "expected_pay_band_version"])
    variant = body["pricing_variant"]
    if variant not in PRICING_VARIANTS:
        raise invalid_enum("pricing_variant is not a declared member")
    b = get_band_or_404(bid)
    # OCC (tier 5)
    expected = body["expected_pay_band_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_pay_band_version must be an integer")
    if expected != b["version"]:
        raise stale_version()
    # Posture gate (tier 6)
    prog = store.programs.get(b["comp_program_id"])
    if prog is None:
        raise not_found("comp program not found")
    if prog["status"] not in ("PRICING", "MAPPING_OPEN"):
        raise program_state_forbids("band price requires program in PRICING or MAPPING_OPEN")
    # Transition legality (tier 7)
    if b["status"] == "SUPERSEDED":
        raise already_terminal("band is SUPERSEDED")
    if b["status"] not in ("DRAFT", "PRICED"):
        raise invalid_state_transition("price declared only from DRAFT or PRICED")
    pricing_date = pricing._to_date(prog["pricing_as_of_date"])
    pricing.price_band(b, variant, pricing_date)
    b["priced_at"] = clock.now_iso()
    bump(b)
    return success_object(band_view(b))


@bp.route("/comp/pay-bands/<bid>/approve", methods=["POST"])
def approve_band(bid):
    require_roles("CompManager")
    b = get_band_or_404(bid)
    if b["status"] == "SUPERSEDED":
        raise already_terminal("band is SUPERSEDED")
    if b["status"] != "PRICED":
        raise invalid_state_transition("approve declared only from PRICED")
    if b["pricing_variant"] != "OFFICIAL":
        raise invalid_state_transition("band must be priced OFFICIAL before approval")
    # FLSA safety: any APPROVED EXEMPT profile in family+level => min >= annual floor
    for p in store.job_profiles.values():
        if (p["job_family_id"] == b["job_family_id"]
                and p["job_level_id"] == b["job_level_id"]
                and p["status"] == "APPROVED"
                and p["flsa_classification"] == "EXEMPT"):
            if b["min_cents"] < FLSA_ANNUAL_MINIMUM_CENTS:
                raise flsa_salary_basis_violation()
    # Overlap / progression vs adjacent-lower
    lower_id, ov_r, prog_r, unrounded_ovl, unrounded_prog = pricing.overlap_figures(b)
    if lower_id is not None:
        max_ovl_allowed, min_prog_required = pricing.approval_policy_limits(b, lower_id)
        if unrounded_ovl > max_ovl_allowed:
            raise band_overlap_exceeds_policy()
        if unrounded_prog < min_prog_required:
            raise progression_below_policy()
    b["status"] = "COMP_APPROVED"
    bump(b)
    return success_object(band_view(b))


@bp.route("/comp/pay-bands/<bid>/publish", methods=["POST"])
def publish_band(bid):
    require_roles("CompManager")
    b = get_band_or_404(bid)
    prog = store.programs.get(b["comp_program_id"])
    if prog is None:
        raise not_found("comp program not found")
    # Posture gate before transition legality per validation order (tier 6 before 7)
    if b["status"] == "SUPERSEDED":
        raise already_terminal("band is SUPERSEDED")
    if prog["status"] not in ("PRICING", "MAPPING_OPEN"):
        raise program_state_forbids("band publish requires program in PRICING or MAPPING_OPEN")
    if b["status"] != "COMP_APPROVED":
        raise invalid_state_transition("publish declared only from COMP_APPROVED")
    b["status"] = "PUBLISHED"
    bump(b)
    # Recompute compa/range for matching ACTIVE employees
    for e in store.employees.values():
        if e["status"] != "ACTIVE":
            continue
        profile = store.job_profiles.get(e["job_profile_id"])
        if profile is None:
            continue
        if (profile["job_family_id"] == b["job_family_id"]
                and profile["job_level_id"] == b["job_level_id"]
                and e["geo_zone_id"] == b["geo_zone_id"]):
            recompute_employee_health(e)
            bump(e)
    return success_object(band_view(b))


@bp.route("/comp/pay-bands/<bid>/reopen", methods=["POST"])
def reopen_band(bid):
    require_roles("CompManager")
    b = get_band_or_404(bid)
    if b["status"] == "SUPERSEDED":
        raise already_terminal("band is SUPERSEDED")
    if b["status"] != "COMP_APPROVED":
        raise invalid_state_transition("reopen declared only from COMP_APPROVED")
    b["status"] = "DRAFT"
    bump(b)
    return success_object(band_view(b))


@bp.route("/comp/pay-bands/<bid>/overlap-report", methods=["GET"])
def overlap_report(bid):
    get_auth()
    b = get_band_or_404(bid)
    lower_id, ov_r, prog_r, _, _ = pricing.overlap_figures(b)
    return success_object({
        "lower_band_id": lower_id,
        "overlap_pct_to_lower": ov_r,
        "progression_pct_from_lower": prog_r,
    })
