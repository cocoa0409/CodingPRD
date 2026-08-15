"""LOI economics + negotiation cycle (PRD §3.3) with OCC on submit/counter
(PRD §2.6) and the accept/execute cascades (PRD §2.9).
"""
from flask import Blueprint

from db import store, new_entity, public, touch
from errors import (
    ApiError, ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_SITE_NOT_LISTED, ERR_COMPLIANCE_NOT_CLEARED,
    ERR_HARD_MINIMUMS_NOT_MET, ERR_NO_COMPLETED_TOUR, ERR_LOI_ALREADY_OPEN,
    ERR_SF_OUT_OF_RANGE, ERR_INSUFFICIENT_SF, ERR_FREE_RENT_OVER_CAP,
    ERR_NER_BELOW_FLOOR,
)
from middleware import (
    authenticate, body, require_fields, check_enums, get_fk, get_path,
    COMMISSION_BASES, ALL_ROLES,
)
from response import success_object
from routes import list_response
from services import calc, cascades
from services.calc import D, rhu2

bp = Blueprint("lois", __name__)

ECONOMICS_FIELDS = (
    "base_rate_psf", "ti_allowance_psf", "free_rent_months",
    "escalation_pct", "term_years", "leased_sf",
)


def _requirement_owned_by(loi, uid):
    req = store.requirements[loi["requirement_id"]]
    if req["tenant_rep_id"] != uid:
        raise ApiError(ERR_FORBIDDEN,
                       "X-User-ID does not own the linked requirement", 403)
    return req


@bp.post("/api/lois")
def create_loi():
    authenticate(["TenantRep"])
    b = body()
    # Priority 4 (existence), input-list order: requirement_id then site_id.
    req = get_fk(b, "requirement_id", store.requirements)
    site = get_fk(b, "site_id", store.sites)
    require_fields(b, [
        ("requirement_id", "string", True),
        ("site_id", "string", True),
        ("term_years", "int", True),
        ("leased_sf", "int", True),
        ("base_rate_psf", "number", True),
        ("ti_allowance_psf", "number", True),
        ("free_rent_months", "int", True),
        ("escalation_pct", "number", True),
        ("commission_basis", "string", False),
    ])
    if req is None:
        req = store.requirements[b["requirement_id"]]
    if site is None:
        site = store.sites[b["site_id"]]
    check_enums(b, [("commission_basis", COMMISSION_BASES)])
    if not (1 <= b["term_years"] <= 30):
        raise ApiError(ERR_INVALID_REQUEST, "term_years must be in 1..30", 400)
    # Priority 10: the site must be LISTED.
    if site["status"] != "LISTED":
        raise ApiError(ERR_SITE_NOT_LISTED,
                       f"Site is in status {site['status']}", 409)
    # Priority 12: LOI-creation battery, in this fixed order (PRD §2.8.12).
    if not calc.hard_minimums_met(site, req):
        raise ApiError(ERR_HARD_MINIMUMS_NOT_MET,
                       "Site fails the requirement's hard minimums", 422)
    toured = any(
        t["requirement_id"] == req["id"] and t["site_id"] == site["id"]
        and t["status"] == "COMPLETED"
        for t in store.tours.values())
    if not toured:
        raise ApiError(ERR_NO_COMPLETED_TOUR,
                       "No COMPLETED tour exists for this requirement/site pair", 409)
    open_loi = any(
        l["requirement_id"] == req["id"] and l["site_id"] == site["id"]
        and l["status"] in ("DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED")
        for l in store.lois.values())
    if open_loi:
        raise ApiError(ERR_LOI_ALREADY_OPEN,
                       "Another LOI for this requirement/site pair is open", 409)
    if not (req["min_sf"] <= b["leased_sf"] <= req["max_sf"]):
        raise ApiError(ERR_SF_OUT_OF_RANGE,
                       "leased_sf is outside the requirement's [min_sf, max_sf]", 422)
    if site["available_sf"] < b["leased_sf"]:
        raise ApiError(ERR_INSUFFICIENT_SF,
                       "site.available_sf is less than leased_sf", 422)
    ent = new_entity({
        "requirement_id": req["id"],
        "site_id": site["id"],
        "term_years": b["term_years"],
        "leased_sf": b["leased_sf"],
        "base_rate_psf": D(b["base_rate_psf"]),
        "ti_allowance_psf": D(b["ti_allowance_psf"]),
        "free_rent_months": b["free_rent_months"],
        "escalation_pct": D(b["escalation_pct"]),
        "commission_basis": b.get("commission_basis") or "GROSS_AGGREGATE",
        "aggregate_rent_total": None,
        "net_effective_rent_psf": None,
        "negotiation_round": 0,
        "rent_commencement_date": None,
        "abatement_days": 0,
        "status": "DRAFT",
    })
    calc.recompute_loi_economics(ent)
    store.lois[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/lois")
def list_lois():
    authenticate(ALL_ROLES)
    return list_response(store.lois.values(), [
        ("requirement_id", lambda e: e["requirement_id"]),
        ("site_id", lambda e: e["site_id"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/lois/<lid>")
def get_loi(lid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.lois, lid, "LOI")))


@bp.post("/api/lois/<lid>/submit")
def submit_loi(lid):
    """DRAFT -> SUBMITTED or COUNTERED -> SUBMITTED, optionally revising terms."""
    uid, _ = authenticate(["TenantRep"])
    loi = get_path(store.lois, lid, "LOI")
    # Priority 3: the representative must own the linked requirement.
    _requirement_owned_by(loi, uid)
    b = body()
    require_fields(b, [
        ("expected_loi_version", "int", True),
        ("base_rate_psf", "number", False),
        ("ti_allowance_psf", "number", False),
        ("free_rent_months", "int", False),
        ("escalation_pct", "number", False),
        ("term_years", "int", False),
        ("leased_sf", "int", False),
    ])
    if "term_years" in b and b["term_years"] is not None and not (1 <= b["term_years"] <= 30):
        raise ApiError(ERR_INVALID_REQUEST, "term_years must be in 1..30", 400)
    if "leased_sf" in b and b["leased_sf"] is not None and b["leased_sf"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "leased_sf must be positive", 400)
    # Priority 8: state legality.
    if loi["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot submit an LOI in status {loi['status']}", 409)
    # Priority 9: OCC.
    if b["expected_loi_version"] != loi["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_loi_version does not match the LOI's current version", 412)
    # Effective terms after applying any in-call revision.
    eff = {k: loi[k] for k in ECONOMICS_FIELDS}
    for k in ECONOMICS_FIELDS:
        if k in b and b[k] is not None:
            eff[k] = b[k]
    # Priority 16/24: effective free_rent_months may not exceed twelve.
    if eff["free_rent_months"] > 12:
        raise ApiError(ERR_FREE_RENT_OVER_CAP,
                       "Effective free_rent_months exceeds 12", 422)
    for k in ECONOMICS_FIELDS:
        loi[k] = D(eff[k]) if k in ("base_rate_psf", "ti_allowance_psf", "escalation_pct") else eff[k]
    loi["status"] = "SUBMITTED"
    loi["negotiation_round"] += 1
    calc.recompute_loi_economics(loi)
    touch(loi)
    return success_object(public(loi))


@bp.post("/api/lois/<lid>/counter")
def counter_loi(lid):
    """SUBMITTED -> COUNTERED with a full replacement economics payload."""
    authenticate(["LeasingManager"])
    loi = get_path(store.lois, lid, "LOI")
    b = body()
    require_fields(b, [
        ("expected_loi_version", "int", True),
        ("base_rate_psf", "number", True),
        ("ti_allowance_psf", "number", True),
        ("free_rent_months", "int", True),
        ("escalation_pct", "number", True),
    ])
    if loi["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot counter an LOI in status {loi['status']}", 409)
    if b["expected_loi_version"] != loi["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_loi_version does not match the LOI's current version", 412)
    # The four counter values replace the standing terms outright; round and
    # version each increment on every successful counter (PRD §2.6, §3.3) —
    # the increment is unconditional, even when the counter restates the
    # standing economics.
    loi["base_rate_psf"] = D(b["base_rate_psf"])
    loi["ti_allowance_psf"] = D(b["ti_allowance_psf"])
    loi["free_rent_months"] = b["free_rent_months"]
    loi["escalation_pct"] = D(b["escalation_pct"])
    loi["status"] = "COUNTERED"
    loi["negotiation_round"] += 1
    calc.recompute_loi_economics(loi)
    touch(loi)
    return success_object(public(loi))


def _accept_preconditions(loi):
    """Shared accept battery for SUBMITTED and COUNTERED (PRD §3.3, in order)."""
    if loi["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot accept an LOI in status {loi['status']}", 409)
    site = store.sites[loi["site_id"]]
    if site["status"] != "LISTED":
        raise ApiError(ERR_SITE_NOT_LISTED,
                       f"Site is in status {site['status']}", 409)
    if site["available_sf"] < loi["leased_sf"]:
        raise ApiError(ERR_INSUFFICIENT_SF,
                       "site.available_sf is less than leased_sf", 422)
    floor = rhu2(D("0.60") * D(site["asking_rate_psf"]))
    if D(loi["net_effective_rent_psf"]) < floor:
        raise ApiError(ERR_NER_BELOW_FLOOR,
                       "net_effective_rent_psf is below 60% of the asking rate", 422)
    return site


@bp.post("/api/lois/<lid>/accept")
def accept_loi(lid):
    authenticate(["LeasingManager"])
    loi = get_path(store.lois, lid, "LOI")
    _accept_preconditions(loi)
    cascades.accept_loi_cascade(loi)
    return success_object(public(loi))


@bp.post("/api/lois/<lid>/reject")
def reject_loi(lid):
    authenticate(["LeasingManager"])
    loi = get_path(store.lois, lid, "LOI")
    if loi["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot reject an LOI in status {loi['status']}", 409)
    loi["status"] = "REJECTED"
    touch(loi)
    return success_object(public(loi))


@bp.post("/api/lois/<lid>/withdraw")
def withdraw_loi(lid):
    uid, _ = authenticate(["TenantRep"])
    loi = get_path(store.lois, lid, "LOI")
    _requirement_owned_by(loi, uid)
    if loi["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot withdraw an LOI in status {loi['status']}", 409)
    was = loi["status"]
    loi["status"] = "WITHDRAWN"
    touch(loi)
    if was == "ACCEPTED":
        # Compensating release: site RESERVED -> LISTED, GRANTED options -> RELEASED.
        cascades.withdraw_accepted_loi_cascade(loi)
    return success_object(public(loi))


@bp.post("/api/lois/<lid>/execute")
def execute_loi(lid):
    authenticate(["AssetManager"])
    loi = get_path(store.lois, lid, "LOI")
    if loi["status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot execute an LOI in status {loi['status']}", 409)
    # Priority 11: twin compliance gates — CLEARED ENVIRONMENTAL + ZONING_USE
    # reviews for the LOI's (site_id, requirement_id) pair.
    for rtype in ("ENVIRONMENTAL", "ZONING_USE"):
        cleared = any(
            r["site_id"] == loi["site_id"] and r["requirement_id"] == loi["requirement_id"]
            and r["review_type"] == rtype and r["status"] == "CLEARED"
            for r in store.reviews.values())
        if not cleared:
            raise ApiError(ERR_COMPLIANCE_NOT_CLEARED,
                           f"No CLEARED {rtype} review for the LOI's site/requirement pair", 409)
    cascades.execute_loi_cascade(loi)
    return success_object(public(loi))
