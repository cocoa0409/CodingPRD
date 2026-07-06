"""Payload factories — one per creatable entity, input fields only.

Only client-supplied (source: input) fields are included; computed fields
(status, ytd_spend_cents, subtotal_cents, total_cost_cents, version, etc.)
are never set by the client.
"""

_email_seq = [0]
_name_seq = [0]


def unique_email(prefix: str = "user") -> str:
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@example.com"


def unique_name(prefix: str = "Acct") -> str:
    _name_seq[0] += 1
    return f"{prefix} {_name_seq[0]}"


def create_account_payload(name=None, billing_email=None,
                           monthly_budget_cents=1_000_000,
                           approval_threshold_cents=100_000) -> dict:
    """POST /corporate-accounts."""
    return {
        "name": name if name is not None else unique_name("Acct"),
        "billing_email": billing_email if billing_email is not None else unique_email("acct"),
        "monthly_budget_cents": monthly_budget_cents,
        "approval_threshold_cents": approval_threshold_cents,
    }


def create_sku_payload(name="Component", unit_cost_cents=500,
                       is_perishable=False, shelf_life_days=None,
                       on_hand_qty=100) -> dict:
    """POST /component-skus. shelf_life_days required only when is_perishable is true."""
    payload = {
        "name": name,
        "unit_cost_cents": unit_cost_cents,
        "is_perishable": is_perishable,
        "on_hand_qty": on_hand_qty,
    }
    if shelf_life_days is not None:
        payload["shelf_life_days"] = shelf_life_days
    return payload


def create_template_payload(name="Test Basket", category="CORPORATE_WELCOME",
                            base_price_cents=4000, is_perishable=False,
                            shelf_life_days=None, components=None,
                            active=True) -> dict:
    """POST /gift-basket-templates."""
    payload = {
        "name": name,
        "category": category,
        "base_price_cents": base_price_cents,
        "is_perishable": is_perishable,
        "components": components if components is not None else [],
        "active": active,
    }
    if shelf_life_days is not None:
        payload["shelf_life_days"] = shelf_life_days
    return payload


def create_station_payload(name="Station", daily_capacity=1000) -> dict:
    """POST /assembly-stations."""
    return {"name": name, "daily_capacity": daily_capacity}


def create_shipping_zone_payload(zone_code="US-CENTRAL",
                                 country_codes=None,
                                 carrier="SwiftShip",
                                 base_rate_cents=500,
                                 per_kg_rate_cents=100,
                                 transit_days_min=2,
                                 transit_days_max=5,
                                 blackout_dates=None) -> dict:
    """POST /shipping-zones."""
    return {
        "zone_code": zone_code,
        "country_codes": country_codes if country_codes is not None else ["US"],
        "carrier": carrier,
        "base_rate_cents": base_rate_cents,
        "per_kg_rate_cents": per_kg_rate_cents,
        "transit_days_min": transit_days_min,
        "transit_days_max": transit_days_max,
        "blackout_dates": blackout_dates if blackout_dates is not None else [],
    }


def create_branding_profile_payload(name="Kit", logo_url="https://cdn.example/logo.png",
                                    accent_color="#112233", card_stock="MATTE",
                                    expected_corporate_account_version=1) -> dict:
    """POST /corporate-accounts/{id}/branding-profiles."""
    return {
        "name": name,
        "logo_url": logo_url,
        "accent_color": accent_color,
        "card_stock": card_stock,
        "expected_corporate_account_version": expected_corporate_account_version,
    }


def create_order_payload(template_id, occasion="ONBOARDING",
                         branding_profile_id=None, scheduled_send_date=None,
                         expected_corporate_account_version=1) -> dict:
    """POST /corporate-accounts/{id}/orders."""
    payload = {
        "template_id": template_id,
        "occasion": occasion,
        "expected_corporate_account_version": expected_corporate_account_version,
    }
    if branding_profile_id is not None:
        payload["branding_profile_id"] = branding_profile_id
    if scheduled_send_date is not None:
        payload["scheduled_send_date"] = scheduled_send_date
    return payload


def recipient_row(full_name="Rec Name", email=None,
                  shipping_address_line1="1 Main St", city="Austin",
                  state_code="TX", postal_code="73301", country_code="US",
                  quantity=1) -> dict:
    """One row for POST /orders/{id}/recipients/import."""
    return {
        "full_name": full_name,
        "email": email if email is not None else unique_email("rec"),
        "shipping_address_line1": shipping_address_line1,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
        "country_code": country_code,
        "quantity": quantity,
    }


def submit_for_approval_payload(requested_by_user_id="emp-req-1",
                                station_id=None, scheduled_date=None) -> dict:
    """POST /orders/{id}/submit-for-approval. station_id/scheduled_date are
    required whenever the order might auto-approve."""
    payload = {"requested_by_user_id": requested_by_user_id}
    if station_id is not None:
        payload["station_id"] = station_id
    if scheduled_date is not None:
        payload["scheduled_date"] = scheduled_date
    return payload


def budget_decision_payload(decision, approver_user_id="fin-appr-1",
                            decision_reason=None, station_id=None,
                            scheduled_date=None) -> dict:
    """POST /orders/{id}/budget-decision."""
    payload = {"decision": decision, "approver_user_id": approver_user_id}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    if station_id is not None:
        payload["station_id"] = station_id
    if scheduled_date is not None:
        payload["scheduled_date"] = scheduled_date
    return payload


def message_proof_payload(message_text="Hello!",
                          submitted_by_user_id="emp-msg-1") -> dict:
    """POST /recipients/{id}/message-proof."""
    return {
        "message_text": message_text,
        "submitted_by_user_id": submitted_by_user_id,
    }


def proof_decision_payload(decision, decided_by_user_id="proof-appr-1") -> dict:
    """POST /message-proofs/{id}/decision."""
    return {"decision": decision, "decided_by_user_id": decided_by_user_id}


def create_shipment_payload(zone_id, ship_date) -> dict:
    """POST /recipients/{id}/shipments."""
    return {"zone_id": zone_id, "ship_date": ship_date}
