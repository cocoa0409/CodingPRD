"""Payload factories — one per entity, client-supplied input fields only."""

# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------

def branch_payload(**overrides) -> dict:
    payload = {
        "code": "STL",
        "name": "St Louis DC",
        "region_code": "MW",
    }
    payload.update(overrides)
    return payload


def branch_patch_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------

def part_payload(**overrides) -> dict:
    payload = {
        "part_number": "W10-PUMP",
        "oem_code": "WHIRLPOOL",
        "description": "Drain pump assembly",
        "category": "MECHANICAL",
        "list_price_cents": 12999,
        "weight_grams": 5200,
    }
    payload.update(overrides)
    return payload


def supersession_payload(superseded_by_part_id: str, expected_part_version: int) -> dict:
    return {
        "superseded_by_part_id": superseded_by_part_id,
        "expected_part_version": expected_part_version,
    }


# ---------------------------------------------------------------------------
# ModelPartXref
# ---------------------------------------------------------------------------

def model_part_xref_payload(part_id: str, **overrides) -> dict:
    payload = {
        "model_number": "WTW5000DW1",
        "part_id": part_id,
        "position_code": "P-14",
        "xref_source": "OEM_PUBLICATION",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PricingTier
# ---------------------------------------------------------------------------

def pricing_tier_payload(**overrides) -> dict:
    payload = {
        "tier_code": "GOLD",
        "name": "Gold Contract",
        "discount_pct_electrical": 0.15,
        "discount_pct_mechanical": 0.20,
        "discount_pct_cosmetic": 0.25,
        "discount_pct_sealed_system": 0.10,
        "min_annual_volume_cents": 5000000,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServicerAccount
# ---------------------------------------------------------------------------

def servicer_account_payload(pricing_tier_id: str, **overrides) -> dict:
    payload = {
        "business_name": "Ace Appliance Repair",
        "oem_authorizations": ["WHIRLPOOL"],
        "pricing_tier_id": pricing_tier_id,
        "credit_terms": "NET_30",
        "credit_limit_cents": 10000000,
        "core_liability_limit_cents": 10000000,
    }
    payload.update(overrides)
    return payload


def servicer_account_patch_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TechnicianCertification
# ---------------------------------------------------------------------------

def technician_certification_payload(servicer_account_id: str, **overrides) -> dict:
    payload = {
        "servicer_account_id": servicer_account_id,
        "technician_name": "Dana Ruiz",
        "oem_code": "WHIRLPOOL",
        "cert_level": "ADVANCED",
        "training_completed_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def revocation_payload(reason: str = "technician left the business") -> dict:
    return {"revocation_reason": reason}


# ---------------------------------------------------------------------------
# InventoryRecord
# ---------------------------------------------------------------------------

def inventory_record_payload(branch_id: str, part_id: str, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "part_id": part_id,
        "on_hand_units": 10,
    }
    payload.update(overrides)
    return payload


def inventory_adjustment_payload(delta_units: int, reason: str = "cycle count") -> dict:
    return {"delta_units": delta_units, "adjustment_reason": reason}


# ---------------------------------------------------------------------------
# PriceFile / PriceFileLine
# ---------------------------------------------------------------------------

def price_file_payload(**overrides) -> dict:
    payload = {
        "file_version": 20260801,
        "effective_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def price_file_line_payload(part_id: str, new_list_price_cents: int, **overrides) -> dict:
    payload = {
        "part_id": part_id,
        "new_list_price_cents": new_list_price_cents,
    }
    payload.update(overrides)
    return payload


def rollback_payload(reason: str = "published in error") -> dict:
    return {"rollback_reason": reason}


# ---------------------------------------------------------------------------
# PartOrder / OrderLine
# ---------------------------------------------------------------------------

def will_call_order_payload(servicer_account_id: str, pickup_branch_id: str,
                            **overrides) -> dict:
    payload = {
        "servicer_account_id": servicer_account_id,
        "fulfillment_mode": "WILL_CALL",
        "pickup_branch_id": pickup_branch_id,
    }
    payload.update(overrides)
    return payload


def drop_ship_order_payload(servicer_account_id: str, ship_to_zip: str,
                            **overrides) -> dict:
    payload = {
        "servicer_account_id": servicer_account_id,
        "fulfillment_mode": "OVERNIGHT_DROP_SHIP",
        "ship_to_zip": ship_to_zip,
    }
    payload.update(overrides)
    return payload


def order_line_payload(requested_part_id: str, quantity: int,
                       expected_part_order_version: int) -> dict:
    return {
        "requested_part_id": requested_part_id,
        "quantity": quantity,
        "expected_part_order_version": expected_part_order_version,
    }


def credit_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def cancellation_payload(reason: str = "servicer changed their mind") -> dict:
    return {"cancellation_reason": reason}


# ---------------------------------------------------------------------------
# SubstituteRequest
# ---------------------------------------------------------------------------

def substitute_approval_payload(substitute_part_id: str, **overrides) -> dict:
    payload = {
        "decision": "APPROVE",
        "substitute_part_id": substitute_part_id,
    }
    payload.update(overrides)
    return payload


def substitute_rejection_payload(**overrides) -> dict:
    payload = {"decision": "REJECT"}
    payload.update(overrides)
    return payload


def substitute_withdrawal_payload(
    reason: str = "servicer sourced the part elsewhere",
) -> dict:
    return {"withdrawal_reason": reason}


# ---------------------------------------------------------------------------
# WarrantyClaim
# ---------------------------------------------------------------------------

def warranty_claim_payload(servicer_account_id: str, order_line_id: str,
                           **overrides) -> dict:
    payload = {
        "servicer_account_id": servicer_account_id,
        "order_line_id": order_line_id,
        "defect_code": "PUMP-SEIZED",
        "appliance_model_number": "WTW5000DW1",
    }
    payload.update(overrides)
    return payload


def oem_response_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def resubmit_payload(additional_info: str = "photographs of the failed part") -> dict:
    return {"additional_info": additional_info}


# ---------------------------------------------------------------------------
# ReturnAuthorization
# ---------------------------------------------------------------------------

def return_authorization_payload(servicer_account_id: str, order_line_id: str,
                                 quantity: int, reason_code: str,
                                 return_branch_id: str, **overrides) -> dict:
    payload = {
        "servicer_account_id": servicer_account_id,
        "order_line_id": order_line_id,
        "quantity": quantity,
        "reason_code": reason_code,
        "return_branch_id": return_branch_id,
    }
    payload.update(overrides)
    return payload


def return_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
