"""Rental license lifecycle routes."""
from flask import Blueprint
from store import store, new_entity, touch
from auth import require_role, body, as_int
from errors import err
from lookups import get_property, get_license
from envelope import success
from serializers import license_dict
from domain import refresh_license, open_critical_count
from calc import license_fee
from timeutil import add_years

bp = Blueprint("licenses", __name__)


def _mint_license_number():
    n = len(store.licenses) + 1
    return f"LIC-{n:08d}"


def _has_passed_periodic(pid):
    return any(
        i["property_id"] == pid and i["inspection_type"] == "PERIODIC" and i["status"] == "PASSED"
        for i in store.inspections.values()
    )


@bp.post("/rental-licenses")
def issue_license():
    require_role({"Registrar"})
    data = body()
    # Existence of referenced property (priority 5), if provided.
    if data.get("property_id") is not None:
        get_property(data["property_id"])
    # Structural validation (priority 6).
    if data.get("property_id") is None:
        raise err("ERR_VALIDATION", "Missing required field: property_id")
    term_years = data.get("term_years", 1)
    if term_years is None:
        term_years = 1
    if isinstance(term_years, bool) or not isinstance(term_years, int) or term_years not in (1, 2, 3):
        raise err("ERR_VALIDATION", "term_years must be one of {1, 2, 3}")
    expected = as_int(data, "expected_property_version")
    prop = store.properties[data["property_id"]]
    # OCC (priority 18).
    if expected != prop["version"]:
        raise err("ERR_STALE_VERSION", "Stale property version")

    fee, lead_applied = license_fee(prop["unit_count"], prop["year_built"], term_years, late=False)
    lic = new_entity(store.licenses, {
        "property_id": prop["id"],
        "license_number": _mint_license_number(),
        "term_years": term_years,
        "status": "PENDING_PAYMENT",
        "fee_cents": fee,
        "lead_surcharge_applied": lead_applied,
        "issued_at": None,
        "expires_at": None,
        "renewal_count": 0,
        "last_paid_cents": 0,
    })
    prop["current_license_id"] = lic["id"]
    touch(prop)
    return success(license_dict(lic), status=201)


@bp.post("/rental-licenses/<lid>/pay")
def pay_license(lid):
    uid, role = require_role({"Landlord"})
    lic = get_license(lid)
    prop = store.properties[lic["property_id"]]
    if uid != prop["landlord_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the owning landlord may pay")
    refresh_license(lic)
    if lic["status"] != "PENDING_PAYMENT":
        raise err("ERR_INVALID_STATE", "License is not PENDING_PAYMENT")
    if open_critical_count(prop["id"]) > 0:
        raise err("ERR_UNSAFE_HABITABILITY", "Property has open critical violations")
    if not _has_passed_periodic(prop["id"]):
        raise err("ERR_NO_PASSED_INSPECTION", "Property has no passed periodic inspection")
    data = body()
    amount = as_int(data, "amount_cents")
    if amount != lic["fee_cents"]:
        raise err("ERR_FEE_MISMATCH", "amount_cents does not equal fee_cents")

    now = store.now()
    lic["status"] = "ACTIVE"
    lic["issued_at"] = now
    lic["expires_at"] = add_years(now, lic["term_years"])
    lic["last_paid_cents"] = lic["fee_cents"]
    touch(lic)
    prop["total_fees_paid_cents"] += lic["fee_cents"]
    prop["current_license_id"] = lic["id"]
    touch(prop)
    return success(license_dict(lic), status=200)


@bp.post("/rental-licenses/<lid>/renew")
def renew_license(lid):
    uid, role = require_role({"Landlord", "Registrar"})
    lic = get_license(lid)
    prop = store.properties[lic["property_id"]]
    if role == "Landlord" and uid != prop["landlord_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the owning landlord may renew")
    refresh_license(lic)
    if lic["status"] not in ("ACTIVE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "License is not ACTIVE or EXPIRED")
    if open_critical_count(prop["id"]) > 0:
        raise err("ERR_UNSAFE_HABITABILITY", "Property has open critical violations")
    data = body()
    expected = as_int(data, "expected_license_version")
    if expected != lic["version"]:
        raise err("ERR_STALE_VERSION", "Stale license version")

    now = store.now()
    late = bool(lic.get("expires_at")) and now > lic["expires_at"]
    fee, lead_applied = license_fee(prop["unit_count"], prop["year_built"], lic["term_years"], late=late)
    lic["fee_cents"] = fee
    lic["lead_surcharge_applied"] = lead_applied
    lic["status"] = "ACTIVE"
    lic["issued_at"] = now
    lic["expires_at"] = add_years(now, lic["term_years"])
    lic["renewal_count"] += 1
    lic["last_paid_cents"] = fee
    touch(lic)
    prop["total_fees_paid_cents"] += fee
    return success(license_dict(lic), status=200)


@bp.post("/rental-licenses/<lid>/refund")
def refund_license(lid):
    require_role({"Registrar"})
    lic = get_license(lid)
    prop = store.properties[lic["property_id"]]
    refresh_license(lic)
    if lic["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "License is not ACTIVE")

    prop["total_fees_paid_cents"] -= lic.get("last_paid_cents", 0)
    lic["status"] = "PENDING_PAYMENT"
    lic["issued_at"] = None
    lic["expires_at"] = None
    if prop.get("current_license_id") == lic["id"]:
        prop["current_license_id"] = None
    touch(lic)
    return success(license_dict(lic), status=200)
