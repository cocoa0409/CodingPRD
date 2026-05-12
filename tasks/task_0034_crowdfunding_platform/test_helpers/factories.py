"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 verbatim. Each factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_email(prefix: str = "backer") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"


def unique_name(prefix: str = "Name") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def unique_token(prefix: str = "tok") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def unique_tier_label(prefix: str = "Tier") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def unique_user_id(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Initiator (PRD §3.1)
# ---------------------------------------------------------------------------
def create_initiator_payload(
    *,
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    bank_account_id: Optional[str] = None,
    qualification_doc_uri: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or unique_name("Initiator"),
    }
    if tax_id is not None:
        payload["tax_id"] = tax_id
    if bank_account_id is not None:
        payload["bank_account_id"] = bank_account_id
    if qualification_doc_uri is not None:
        payload["qualification_doc_uri"] = qualification_doc_uri
    payload.update(overrides)
    return payload


def verify_kyc_payload(*, decision: str = "VERIFIED",
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Backer (PRD §3.1)
# ---------------------------------------------------------------------------
def create_backer_payload(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    default_shipping_address: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": display_name or unique_name("Backer"),
        "email": email or unique_email("backer"),
    }
    if default_shipping_address is not None:
        payload["default_shipping_address"] = default_shipping_address
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Project (PRD §3.2)
# ---------------------------------------------------------------------------
def create_project_payload(
    *,
    title: Optional[str] = None,
    category: str = "TECH",
    description_md: str = "## Description\n\nA crowdfunding project.",
    media_uris: Optional[List[str]] = None,
    risk_disclosure: str = "There are inherent risks with all crowdfunding.",
    funding_model: str = "ALL_OR_NOTHING",
    funding_target_cents: int = 1_000_000,
    deadline: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title or unique_name("Project Title"),
        "category": category,
        "description_md": description_md,
        "media_uris": media_uris if media_uris is not None else [
            "https://media.example.test/image-1.jpg"
        ],
        "risk_disclosure": risk_disclosure,
        "funding_model": funding_model,
        "funding_target_cents": funding_target_cents,
    }
    if deadline is not None:
        payload["deadline"] = deadline
    payload.update(overrides)
    return payload


def patch_project_payload(*, version: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """Build a PATCH /projects/{id} body. PRD §3.2 lists editable fields:
    title, description_md, media_uris, risk_disclosure, funding_model,
    funding_target_cents, deadline. All optional in the body.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reward (PRD §3.2)
# ---------------------------------------------------------------------------
def create_reward_payload(
    *,
    tier_label: Optional[str] = None,
    pledge_amount_cents: int = 5_000,
    reward_type: str = "PHYSICAL",
    inventory_limit: Optional[int] = None,
    estimated_delivery: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tier_label": tier_label or unique_tier_label("Tier"),
        "pledge_amount_cents": pledge_amount_cents,
        "reward_type": reward_type,
    }
    if inventory_limit is not None:
        payload["inventory_limit"] = inventory_limit
    if estimated_delivery is not None:
        payload["estimated_delivery"] = estimated_delivery
    payload.update(overrides)
    return payload


def patch_reward_payload(*, version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Add-on item (PRD §3.2)
# ---------------------------------------------------------------------------
def create_add_on_item_payload(
    *,
    name: Optional[str] = None,
    price_cents: int = 1_000,
    requires_shipping: Optional[bool] = None,
    inventory_limit: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_name("AddOn"),
        "price_cents": price_cents,
    }
    if requires_shipping is not None:
        payload["requires_shipping"] = requires_shipping
    if inventory_limit is not None:
        payload["inventory_limit"] = inventory_limit
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Order (PRD §3.4)
# ---------------------------------------------------------------------------
def create_order_payload(
    *,
    project_id: str,
    reward_id: str,
    add_ons: Optional[List[Dict[str, Any]]] = None,
    shipping_address: Optional[Dict[str, Any]] = None,
    payment_method_token: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "reward_id": reward_id,
        "payment_method_token": payment_method_token or unique_token(),
    }
    if add_ons is not None:
        payload["add_ons"] = add_ons
    if shipping_address is not None:
        payload["shipping_address"] = shipping_address
    payload.update(overrides)
    return payload


def patch_order_payload(*, version: Optional[int] = None,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def add_on_line(add_on_item_id: str, quantity: int = 1) -> Dict[str, Any]:
    return {"add_on_item_id": add_on_item_id, "quantity": quantity}


def default_shipping_address() -> Dict[str, Any]:
    return {
        "line1": "123 Backer Lane",
        "city": "Test City",
        "postal_code": "00000",
        "country": "US",
    }


# ---------------------------------------------------------------------------
# Progress update (PRD §3.9)
# ---------------------------------------------------------------------------
def create_progress_update_payload(
    *,
    title: Optional[str] = None,
    body_md: str = "Progress so far",
    visibility: str = "PUBLIC",
    milestone_label: Optional[str] = None,
    is_delay_notice: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title or unique_name("Update"),
        "body_md": body_md,
        "visibility": visibility,
    }
    if milestone_label is not None:
        payload["milestone_label"] = milestone_label
    if is_delay_notice is not None:
        payload["is_delay_notice"] = is_delay_notice
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Refund request (PRD §3.8)
# ---------------------------------------------------------------------------
def create_refund_request_payload(
    *,
    order_id: str,
    reason: str = "DISPUTE",
    requested_amount_cents: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
    }
    payload.update(overrides)
    return payload


def reject_refund_payload(*, rejection_reason: str = "Not eligible",
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement batch (PRD §3.11)
# ---------------------------------------------------------------------------
def create_settlement_batch_payload(
    *,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Review decisions
# ---------------------------------------------------------------------------
def review_payload(*, decision: str, message: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if message is not None:
        payload["message"] = message
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logistics shipment line
# ---------------------------------------------------------------------------
def shipment_line(value_cents: int, **overrides: Any) -> Dict[str, Any]:
    line: Dict[str, Any] = {"value_cents": value_cents}
    line.update(overrides)
    return line


__all__ = [
    "unique_email",
    "unique_name",
    "unique_token",
    "unique_tier_label",
    "unique_user_id",
    "create_initiator_payload",
    "verify_kyc_payload",
    "create_backer_payload",
    "create_project_payload",
    "patch_project_payload",
    "create_reward_payload",
    "patch_reward_payload",
    "create_add_on_item_payload",
    "create_order_payload",
    "patch_order_payload",
    "add_on_line",
    "default_shipping_address",
    "create_progress_update_payload",
    "create_refund_request_payload",
    "reject_refund_payload",
    "create_settlement_batch_payload",
    "review_payload",
    "shipment_line",
]
