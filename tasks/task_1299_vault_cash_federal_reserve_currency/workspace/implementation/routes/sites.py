"""VaultSite endpoints."""
from flask import Blueprint, request

from db import DB, new_id, clock_date_str
from errors import ApiError
from middleware import auth, ALL_ROLES, require_site_scope
from response import ok, ok_list
from services import (
    stamp_new, touch, public, append_ledger, derive_site_exposure,
    derive_site_posture,
)
from util import (
    body, required, as_int, as_str, as_enum, pagination_args,
)

bp = Blueprint("sites", __name__)

SITE_TYPES = {"CENTRAL", "BRANCH"}


def _get_site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/vault-sites")
def create_site():
    auth(["CashOperationsAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    site_type = as_enum(required(data, "site_type"), "site_type", SITE_TYPES)
    vault_limit = as_int(required(data, "vault_limit_cents"), "vault_limit_cents")
    insurance = as_int(
        required(data, "insurance_coverage_cents"), "insurance_coverage_cents"
    )
    dock_capacity = as_int(required(data, "dock_capacity"), "dock_capacity")
    if dock_capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "dock_capacity must be >= 1")
    opening_fit = as_int(data.get("opening_fit_cents", 0), "opening_fit_cents")
    opening_unfit = as_int(data.get("opening_unfit_cents", 0), "opening_unfit_cents")

    site = stamp_new({
        "id": new_id(),
        "name": name,
        "site_type": site_type,
        "vault_limit_cents": vault_limit,
        "insurance_coverage_cents": insurance,
        "dock_capacity": dock_capacity,
        "opening_fit_cents": opening_fit,
        "opening_unfit_cents": opening_unfit,
        "on_hand_fit_cents": 0,
        "on_hand_unfit_cents": 0,
        "reserved_out_cents": 0,
        "in_transit_inbound_cents": 0,
        "pending_inbound_order_cents": 0,
        "on_hand_total_cents": 0,
        "insurance_headroom_cents": insurance,
        "posture": "NORMAL",
    })
    DB["vault_sites"][site["id"]] = site

    # Nonzero openings post OPENING_BALANCE ledger entries on the clock date.
    # These are part of the creation itself, so the site still reports version 1.
    if opening_fit:
        append_ledger(
            site["id"], clock_date_str(), "OPENING_BALANCE", opening_fit, "FIT",
            touch_site=False,
        )
    if opening_unfit:
        append_ledger(
            site["id"], clock_date_str(), "OPENING_BALANCE", opening_unfit, "UNFIT",
            touch_site=False,
        )
    derive_site_exposure(site)
    derive_site_posture(site)
    return ok(public(site), status=201)


@bp.get("/vault-cash/vault-sites")
def list_sites():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_type = request.args.get("site_type")
    posture = request.args.get("posture")
    rows = list(DB["vault_sites"].values())
    if site_type is not None:
        rows = [s for s in rows if s["site_type"] == site_type]
    if posture is not None:
        rows = [s for s in rows if s["posture"] == posture]
    # Site-scoped staff only see their own home site.
    if principal.role in ("VaultCustodian", "FedCoordinator", "AtmAnalyst", "ComplianceOfficer"):
        rows = [s for s in rows if s["id"] == principal.home_site_id]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(rows)
    return ok_list([public(s) for s in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/vault-sites/<siteId>")
def get_site(siteId):
    principal = auth(ALL_ROLES)
    site = _get_site_or_404(siteId)
    require_site_scope(principal, site["id"])
    return ok(public(site))


@bp.patch("/vault-cash/vault-sites/<siteId>")
def patch_site(siteId):
    auth(["CashOperationsAdmin"])
    site = _get_site_or_404(siteId)
    data = body()
    expected = as_int(
        required(data, "expected_vault_site_version"), "expected_vault_site_version"
    )
    if expected != site["version"]:
        raise ApiError(
            "ERR_STALE_VAULT_SITE_VERSION",
            412,
            "expected_vault_site_version does not match current site version",
        )
    if "name" in data and data["name"] is not None:
        site["name"] = as_str(data["name"], "name")
    if "vault_limit_cents" in data and data["vault_limit_cents"] is not None:
        site["vault_limit_cents"] = as_int(data["vault_limit_cents"], "vault_limit_cents")
    if "insurance_coverage_cents" in data and data["insurance_coverage_cents"] is not None:
        site["insurance_coverage_cents"] = as_int(
            data["insurance_coverage_cents"], "insurance_coverage_cents"
        )
    if "dock_capacity" in data and data["dock_capacity"] is not None:
        dc = as_int(data["dock_capacity"], "dock_capacity")
        if dc < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "dock_capacity must be >= 1")
        site["dock_capacity"] = dc
    derive_site_exposure(site)
    derive_site_posture(site)
    touch(site)
    return ok(public(site))
