"""ShipmentDocument service."""
from __future__ import annotations

from typing import Any, Optional

from ..calculations import compute_authenticity_score, to_float2
from ..constants import CURRENCIES, DOC_TYPES
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import (
    ensure_enum,
    ensure_non_negative_number,
    ensure_string,
    occ_check,
)


def attach_document(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    declaration = store.declarations.get(declaration_id)
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", f"Declaration {declaration_id!r} not found.")

    doc_type = ensure_enum(body.get("doc_type"), "doc_type", DOC_TYPES)
    storage_uri = ensure_string(body.get("storage_uri"), "storage_uri", 1, 500)

    declared_total_value = body.get("declared_total_value")
    declared_total_currency = body.get("declared_total_currency")
    if declared_total_value is not None:
        declared_total_value = ensure_non_negative_number(
            declared_total_value, "declared_total_value"
        )
    if declared_total_currency is not None:
        if not isinstance(declared_total_currency, str) or declared_total_currency not in CURRENCIES:
            raise ApiError(
                "ERR_INVALID_INPUT",
                "declared_total_currency must be a supported currency.",
            )

    # If there is an existing stub (storage_uri empty) of the same doc_type
    # under this declaration, replace it (operator is fulfilling the follow-up).
    existing_stub = None
    for d in store.documents.values():
        if (
            d.get("declaration_id") == declaration_id
            and d.get("doc_type") == doc_type
            and not d.get("storage_uri")
        ):
            existing_stub = d
            break

    if existing_stub is not None:
        existing_stub["storage_uri"] = storage_uri
        existing_stub["declared_total_value"] = (
            float(declared_total_value) if declared_total_value is not None else None
        )
        existing_stub["declared_total_currency"] = declared_total_currency
        bump_version(existing_stub)
        record = existing_stub
    else:
        record = common_fields_create()
        record.update(
            {
                "declaration_id": declaration_id,
                "doc_type": doc_type,
                "storage_uri": storage_uri,
                "declared_total_value": (
                    float(declared_total_value) if declared_total_value is not None else None
                ),
                "declared_total_currency": declared_total_currency,
                "authenticity_score": None,
                "authenticity_status": "UNSCREENED",
                "follow_up_requested_at": None,
            }
        )
        store.documents[record["id"]] = record

    # Provisional authenticity screen
    siblings = [
        d
        for d in store.documents.values()
        if d.get("declaration_id") == declaration_id and d.get("id") != record["id"]
    ]
    score, status = compute_authenticity_score(
        record, siblings, declaration.get("declared_currency")
    )
    record["authenticity_score"] = float(score)
    record["authenticity_status"] = status
    return record


def get_document(document_id: str) -> dict[str, Any]:
    d = get_store().documents.get(document_id)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"Document {document_id!r} not found.")
    return d


def screen_document(document_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    doc = get_document(document_id)
    occ_check(doc, body.get("version"))

    declaration = store.declarations.get(doc.get("declaration_id"))
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", "Parent declaration not found.")

    siblings = [
        d
        for d in store.documents.values()
        if d.get("declaration_id") == doc.get("declaration_id") and d.get("id") != document_id
    ]
    score, status = compute_authenticity_score(
        doc, siblings, declaration.get("declared_currency")
    )
    doc["authenticity_score"] = float(score)
    doc["authenticity_status"] = status
    bump_version(doc)
    return doc
