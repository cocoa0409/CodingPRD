"""Supplier lifecycle and pre-screening calculation."""

from clock import clock, parse_iso
from db import bump_version, common_fields_create, db
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)


MIN_CREDIT_SCORE = 600


def get_supplier_or_404(supplier_id: str) -> dict:
    s = db.suppliers.get(supplier_id)
    if not s:
        raise_error(ERR_NOT_FOUND, f"supplier '{supplier_id}' not found")
    return s


def get_supplier_or_ref_404(supplier_id: str) -> dict:
    from errors import ERR_REFERENCE_NOT_FOUND
    s = db.suppliers.get(supplier_id)
    if not s:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"supplier '{supplier_id}' not found")
    return s


def create_supplier(legal_name: str, tax_id: str, qualifications):
    qualifications = qualifications or []
    if not isinstance(qualifications, list):
        raise_error(ERR_VALIDATION, "qualifications must be array")
    if not isinstance(legal_name, str) or not legal_name:
        raise_error(ERR_VALIDATION, "legal_name must be non-empty string")
    if not isinstance(tax_id, str) or not tax_id:
        raise_error(ERR_VALIDATION, "tax_id must be non-empty string")
    # Uniqueness checks
    for existing in db.suppliers.values():
        if existing["legal_name"] == legal_name:
            raise_error(ERR_VALIDATION, "legal_name already in use")
        if existing["tax_id"] == tax_id:
            raise_error(ERR_VALIDATION, "tax_id already in use")
    s = {
        "id": db.new_id(),
        **common_fields_create(),
        "legal_name": legal_name,
        "tax_id": tax_id,
        "registration_status": "PENDING",
        "blacklist_until": None,
        "credit_score": 600,
        "qualifications": list(qualifications),
    }
    db.suppliers[s["id"]] = s
    return s


def verify_supplier(supplier_id: str):
    s = get_supplier_or_404(supplier_id)
    if s["registration_status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "supplier is not PENDING")
    s["registration_status"] = "VERIFIED"
    bump_version(s)
    return s


def blacklist_supplier(supplier_id: str, blacklist_until_iso: str):
    s = get_supplier_or_404(supplier_id)
    # parse / validate
    if not isinstance(blacklist_until_iso, str) or not blacklist_until_iso:
        raise_error(ERR_VALIDATION, "blacklist_until must be non-empty ISO string")
    try:
        parse_iso(blacklist_until_iso)
    except Exception:
        raise_error(ERR_VALIDATION, "blacklist_until is not a valid ISO timestamp")
    s["registration_status"] = "BLACKLISTED"
    s["blacklist_until"] = blacklist_until_iso
    bump_version(s)
    # side effect: disqualify all SUBMITTED bids by this supplier
    for bid in db.bids.values():
        if bid["supplier_id"] == supplier_id and bid["bid_status"] == "SUBMITTED":
            bid["bid_status"] = "DISQUALIFIED"
            bump_version(bid)
    return s


# ---------------------------------------------------------------------------
# Pre-screening eligibility (calculation.prescreen_eligibility)
# ---------------------------------------------------------------------------


def is_currently_blacklisted(s: dict) -> bool:
    """A supplier is currently blacklisted iff blacklist_until > current clock."""
    bu = s.get("blacklist_until")
    if not bu:
        return False
    try:
        bu_dt = parse_iso(bu)
    except Exception:
        return False
    return bu_dt > clock.now()


def prescreen_eligibility(supplier: dict, project: dict) -> bool:
    """All four sub-checks must hold."""
    if supplier["registration_status"] != "VERIFIED":
        return False
    # blacklist_until null OR <= current clock
    bu = supplier.get("blacklist_until")
    if bu is not None:
        try:
            bu_dt = parse_iso(bu)
        except Exception:
            return False
        if bu_dt > clock.now():
            return False
    if int(supplier.get("credit_score", 0)) < MIN_CREDIT_SCORE:
        return False
    req = set(project.get("required_qualifications") or [])
    have = set(supplier.get("qualifications") or [])
    if not req.issubset(have):
        return False
    return True
