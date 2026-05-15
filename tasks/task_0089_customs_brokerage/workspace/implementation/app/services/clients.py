"""ClientCompany service."""
from __future__ import annotations

from typing import Any, Optional

from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import (
    ensure_country,
    ensure_currency,
    ensure_email,
    ensure_enum,
    ensure_string,
    occ_check,
)


CLIENT_STATUSES = {"ACTIVE", "ARCHIVED"}


def _uniqueness_check(legal_name: str, tax_id: str, exclude_id: Optional[str] = None) -> None:
    store = get_store()
    for cid, c in store.clients.items():
        if c.get("status") == "ARCHIVED":
            continue
        if exclude_id and cid == exclude_id:
            continue
        if c.get("legal_name") == legal_name:
            raise ApiError("ERR_INVALID_INPUT", f"legal_name {legal_name!r} already exists.")
        if c.get("tax_id") == tax_id:
            raise ApiError("ERR_INVALID_INPUT", f"tax_id {tax_id!r} already exists.")


def create_client(body: dict[str, Any]) -> dict[str, Any]:
    legal_name = ensure_string(body.get("legal_name"), "legal_name", 1, 200)
    tax_id = ensure_string(body.get("tax_id"), "tax_id", 1, 40)
    country_code = ensure_country(body.get("country_code"), "country_code")
    contact_email = ensure_email(body.get("contact_email"), "contact_email")
    default_settlement_currency = ensure_currency(
        body.get("default_settlement_currency"), "default_settlement_currency"
    )
    _uniqueness_check(legal_name, tax_id)
    record = common_fields_create()
    record.update(
        {
            "legal_name": legal_name,
            "tax_id": tax_id,
            "country_code": country_code,
            "contact_email": contact_email,
            "default_settlement_currency": default_settlement_currency,
            "status": "ACTIVE",
        }
    )
    get_store().clients[record["id"]] = record
    return record


def get_client(client_id: str) -> dict[str, Any]:
    c = get_store().clients.get(client_id)
    if not c:
        raise ApiError("ERR_NOT_FOUND", f"Client {client_id!r} not found.")
    return c


def list_clients(
    status: Optional[str], limit: int, offset: int
) -> list[dict[str, Any]]:
    items = list(get_store().clients.values())
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items.sort(key=lambda c: c.get("created_at") or "")
    return items


def update_client(client_id: str, body: dict[str, Any]) -> dict[str, Any]:
    client = get_client(client_id)
    occ_check(client, body.get("version"))
    # tax_id is immutable
    if "tax_id" in body and body["tax_id"] != client.get("tax_id"):
        raise ApiError("ERR_INVALID_INPUT", "tax_id is immutable.")

    new_legal_name = client.get("legal_name")
    new_tax_id = client.get("tax_id")
    if "legal_name" in body:
        new_legal_name = ensure_string(body["legal_name"], "legal_name", 1, 200)
    if "contact_email" in body:
        client["contact_email"] = ensure_email(body["contact_email"], "contact_email")
    if "default_settlement_currency" in body:
        client["default_settlement_currency"] = ensure_currency(
            body["default_settlement_currency"], "default_settlement_currency"
        )
    if "status" in body:
        client["status"] = ensure_enum(body["status"], "status", CLIENT_STATUSES)

    # uniqueness re-check if legal_name changing
    if new_legal_name != client.get("legal_name"):
        _uniqueness_check(new_legal_name, new_tax_id, exclude_id=client_id)
        client["legal_name"] = new_legal_name

    bump_version(client)
    return client
