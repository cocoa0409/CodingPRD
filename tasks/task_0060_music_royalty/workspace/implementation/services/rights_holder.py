"""RightsHolder service."""

from datetime import date

from db import store
from errors import raise_err
from clock import clock
from util import (
    get_str, get_enum, parse_iso_date, COUNTRY_RE,
)

HOLDER_KINDS = {"INDIVIDUAL", "ORGANIZATION"}
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}


def serialize(h: dict) -> dict:
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "legal_name": h["legal_name"],
        "holder_kind": h["holder_kind"],
        "date_of_birth": h.get("date_of_birth"),
        "is_minor": h["is_minor"],
        "guardian_holder_id": h.get("guardian_holder_id"),
        "tax_jurisdiction": h["tax_jurisdiction"],
        "payout_currency": h["payout_currency"],
        "bank_account_token": h["bank_account_token"],
        "bank_account_revoked": h.get("bank_account_revoked", False),
    }


def _compute_is_minor(holder_kind: str, date_of_birth_str):
    if holder_kind != "INDIVIDUAL":
        return False
    if not date_of_birth_str:
        return False
    dob = parse_iso_date(date_of_birth_str)
    today = clock.now().date()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years < 18


def create_rights_holder(body: dict) -> dict:
    legal_name = get_str(body, "legal_name", min_len=1, max_len=200)
    holder_kind = get_enum(body, "holder_kind", HOLDER_KINDS)
    tax_jurisdiction = get_str(body, "tax_jurisdiction", min_len=2, max_len=2)
    if not COUNTRY_RE.match(tax_jurisdiction):
        raise_err("ERR_VALIDATION", "tax_jurisdiction must be 2 uppercase letters")
    payout_currency = get_enum(body, "payout_currency", CURRENCIES)
    bank_account_token = get_str(body, "bank_account_token", min_len=1, max_len=64)

    dob_str = body.get("date_of_birth")
    if holder_kind == "INDIVIDUAL":
        if not dob_str:
            raise_err("ERR_VALIDATION", "date_of_birth required for INDIVIDUAL")
        # validate format
        parse_iso_date(dob_str)
    else:
        dob_str = None

    is_minor = _compute_is_minor(holder_kind, dob_str)

    guardian_holder_id = body.get("guardian_holder_id")
    if is_minor:
        # Required and must reference a valid adult.
        if not guardian_holder_id:
            raise_err("ERR_MINOR_REQUIRES_GUARDIAN", "Guardian required for minor")
        with store.lock:
            guardian = store.rights_holders.get(guardian_holder_id)
        if not guardian:
            raise_err("ERR_MINOR_REQUIRES_GUARDIAN", "Guardian not found")
        # Must be ORGANIZATION OR (INDIVIDUAL AND is_minor == false)
        if not (guardian["holder_kind"] == "ORGANIZATION" or
                (guardian["holder_kind"] == "INDIVIDUAL" and guardian["is_minor"] is False)):
            raise_err("ERR_MINOR_REQUIRES_GUARDIAN", "Invalid guardian")
    else:
        # Allow guardian_holder_id to be supplied but only kept if not minor? Keep as supplied (or null).
        # The PRD only requires it when minor; if supplied for non-minor, we still store it (but it's optional).
        if guardian_holder_id is not None:
            # If guardian_holder_id is supplied, it should reference an existing holder.
            with store.lock:
                if guardian_holder_id not in store.rights_holders:
                    raise_err("ERR_NOT_FOUND", "Guardian not found")

    with store.lock:
        row = store.common_fields()
        row.update({
            "legal_name": legal_name,
            "holder_kind": holder_kind,
            "date_of_birth": dob_str,
            "is_minor": is_minor,
            "guardian_holder_id": guardian_holder_id,
            "tax_jurisdiction": tax_jurisdiction,
            "payout_currency": payout_currency,
            "bank_account_token": bank_account_token,
            "bank_account_revoked": False,
        })
        store.rights_holders[row["id"]] = row
    return serialize(row)


def get_rights_holder(holder_id: str) -> dict:
    with store.lock:
        h = store.rights_holders.get(holder_id)
        if not h:
            raise_err("ERR_NOT_FOUND", "RightsHolder not found")
        return serialize(h)


def list_rights_holders(args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    holder_kind = args.get("holder_kind")
    is_minor_q = args.get("is_minor")
    tax_jurisdiction = args.get("tax_jurisdiction")

    with store.lock:
        rows = list(store.rights_holders.values())

    if holder_kind:
        rows = [r for r in rows if r["holder_kind"] == holder_kind]
    if is_minor_q is not None:
        truthy = is_minor_q.lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["is_minor"] is truthy]
    if tax_jurisdiction:
        rows = [r for r in rows if r["tax_jurisdiction"] == tax_jurisdiction]

    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(r) for r in page], total, limit, offset
