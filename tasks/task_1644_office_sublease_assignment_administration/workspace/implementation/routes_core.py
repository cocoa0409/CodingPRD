"""Party, Building, and Lease endpoints."""
from flask import Blueprint

import db
from db import store, new_id, touch, new_common
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles, ALL_ROLES, ADMIN_READ
from validation import parse_body, require_path_entity

bp = Blueprint("core", __name__)

PARTY_KINDS = ["LANDLORD", "TENANT", "SUBTENANT", "ASSIGNEE"]


# ---------------------------------------------------------------------------
# Party
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/parties")
def create_party():
    uid, role, _ = get_context()
    require_roles(["AssetManager"])
    body = parse_body({
        "legal_name": ("string", True, None),
        "party_kind": ("enum", True, PARTY_KINDS),
        "credit_rating_bps": ("integer", True, None),
    }, allow_empty=False)
    cb = body["credit_rating_bps"]
    if cb < 0 or cb > 10000:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "credit_rating_bps must be between 0 and 10000")
    party = {
        "id": new_id(),
        "legal_name": body["legal_name"],
        "party_kind": body["party_kind"],
        "credit_rating_bps": cb,
    }
    new_common(party)
    store.parties[party["id"]] = party
    return created(party)


@bp.get("/sublease-admin/parties")
def list_parties():
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    rows = list(store.parties.values())
    rows = paginate.filter(rows, "party_kind")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/parties/<party_id>")
def get_party(party_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.parties, party_id))


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/buildings")
def create_building():
    uid, role, _ = get_context()
    require_roles(["AssetManager"])
    body = parse_body({
        "name": ("string", True, None),
        "total_rentable_sf": ("integer", True, None),
        "loss_factor_bps": ("integer", True, None),
    }, allow_empty=False)
    if body["total_rentable_sf"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "total_rentable_sf must be strictly positive")
    lf = body["loss_factor_bps"]
    if lf < 0 or lf > 5000:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "loss_factor_bps must be between 0 and 5000")
    building = {
        "id": new_id(),
        "name": body["name"],
        "total_rentable_sf": body["total_rentable_sf"],
        "loss_factor_bps": lf,
    }
    new_common(building)
    store.buildings[building["id"]] = building
    return created(building)


@bp.get("/sublease-admin/buildings/<building_id>")
def get_building(building_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.buildings, building_id))


@bp.get("/sublease-admin/buildings/<building_id>/leases")
def get_building_leases(building_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.buildings, building_id)
    rows = [l for l in store.leases.values() if l["building_id"] == building_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/leases")
def create_lease():
    uid, role, _ = get_context()
    require_roles(["AssetManager"])
    body = parse_body({
        "building_id": ("string", True, None),
        "tenant_party_id": ("string", True, None),
        "landlord_party_id": ("string", True, None),
        "base_rent_per_rsf_annual_cents": ("integer", True, None),
        "leased_rsf": ("integer", True, None),
        "consent_window_business_days": ("integer", True, None),
        "deemed_approval_enabled": ("boolean", True, None),
        "profit_share_tier1_pct_bps": ("integer", True, None),
        "profit_share_tier1_threshold_annual_cents": ("integer", True, None),
        "profit_share_tier2_pct_bps": ("integer", True, None),
    }, allow_empty=False)

    # FK referential integrity (priority 4)
    building = store.buildings.get(body["building_id"])
    if building is None:
        raise ApiError("ERR_FK_MISMATCH", 422, "Referenced building does not exist")
    tenant = store.parties.get(body["tenant_party_id"])
    if tenant is None or tenant["party_kind"] != "TENANT":
        raise ApiError("ERR_FK_MISMATCH", 422,
                       "tenant_party_id must reference a party of kind TENANT")
    landlord = store.parties.get(body["landlord_party_id"])
    if landlord is None or landlord["party_kind"] != "LANDLORD":
        raise ApiError("ERR_FK_MISMATCH", 422,
                       "landlord_party_id must reference a party of kind LANDLORD")

    # Fiscal coherence (priority 10)
    if body["base_rent_per_rsf_annual_cents"] <= 0:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "base_rent_per_rsf_annual_cents must be strictly positive")
    if body["leased_rsf"] <= 0:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "leased_rsf must be strictly positive")
    cwd = body["consent_window_business_days"]
    if cwd < 1 or cwd > 60:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "consent_window_business_days must be between 1 and 60")
    if body["profit_share_tier2_pct_bps"] < body["profit_share_tier1_pct_bps"]:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "profit_share_tier2_pct_bps must be >= profit_share_tier1_pct_bps")

    lease = {
        "id": new_id(),
        "building_id": body["building_id"],
        "tenant_party_id": body["tenant_party_id"],
        "landlord_party_id": body["landlord_party_id"],
        "base_rent_per_rsf_annual_cents": body["base_rent_per_rsf_annual_cents"],
        "leased_rsf": body["leased_rsf"],
        "consent_window_business_days": cwd,
        "deemed_approval_enabled": body["deemed_approval_enabled"],
        "profit_share_tier1_pct_bps": body["profit_share_tier1_pct_bps"],
        "profit_share_tier1_threshold_annual_cents": body["profit_share_tier1_threshold_annual_cents"],
        "profit_share_tier2_pct_bps": body["profit_share_tier2_pct_bps"],
        "status": "ACTIVE",
        "cumulative_profit_share_cents": 0,
        "open_transfer_count": 0,
    }
    new_common(lease)
    store.leases[lease["id"]] = lease
    return created(lease)


@bp.get("/sublease-admin/leases/<lease_id>")
def get_lease(lease_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.leases, lease_id))


@bp.get("/sublease-admin/leases")
def list_leases():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = list(store.leases.values())
    rows = paginate.filter(rows, "landlord_party_id")
    rows = paginate.filter(rows, "tenant_party_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/leases/<lease_id>/transfer-requests")
def get_lease_transfers(lease_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.leases, lease_id)
    rows = [t for t in store.transfer_requests.values() if t["lease_id"] == lease_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/leases/<lease_id>/settlements")
def get_lease_settlements(lease_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.leases, lease_id)
    rows = [s for s in store.settlements.values() if s["lease_id"] == lease_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/leases/<lease_id>/demised-areas")
def get_lease_demised_areas(lease_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.leases, lease_id)
    rows = [a for a in store.demised_areas.values() if a["lease_id"] == lease_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)
