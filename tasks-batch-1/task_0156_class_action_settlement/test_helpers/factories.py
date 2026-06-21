"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CASE_CAPTION": "In re Test Settlement",
    "GROSS_FUND_CENTS": 100000,
    "ATTORNEY_FEE_CENTS": 0,
    "ADMIN_COST_CENTS": 0,
    "DISTRIBUTION_METHOD": "PRO_RATA",
    "CLAIM_FILING_DEADLINE": "2026-02-01T00:00:00Z",
    "OBJECTION_DEADLINE": "2026-01-20T00:00:00Z",
    "CY_PRES_FLOOR_CENTS": 0,
}


def create_settlement_payload(**overrides) -> dict:
    """Build a POST /settlements body. Required inputs always present;
    optional tier amounts and cy_pres_floor included so the body is valid for
    both PRO_RATA and TIERED methods unless a test overrides them."""
    payload = {
        "case_caption": DEFAULTS["CASE_CAPTION"],
        "gross_fund_cents": DEFAULTS["GROSS_FUND_CENTS"],
        "attorney_fee_cents": DEFAULTS["ATTORNEY_FEE_CENTS"],
        "admin_cost_cents": DEFAULTS["ADMIN_COST_CENTS"],
        "distribution_method": DEFAULTS["DISTRIBUTION_METHOD"],
        "claim_filing_deadline": DEFAULTS["CLAIM_FILING_DEADLINE"],
        "objection_deadline": DEFAULTS["OBJECTION_DEADLINE"],
        "cy_pres_floor_cents": DEFAULTS["CY_PRES_FLOOR_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_class_member_payload(**overrides) -> dict:
    """Build a POST /settlements/{id}/class-members body. full_name + email are
    required; claimant_tier and tin_on_file are optional (server defaults to
    TIER_B / false respectively)."""
    payload = {
        "full_name": "Test Member",
        "email": "member@example.com",
        "tin_on_file": True,
    }
    payload.update(overrides)
    return payload


def create_notice_payload(**overrides) -> dict:
    payload = {
        "channel": "EMAIL",
        "delivery_status": "DELIVERED",
    }
    payload.update(overrides)
    return payload


def create_claim_payload(settlement_id, class_member_id, **overrides) -> dict:
    payload = {
        "settlement_id": settlement_id,
        "class_member_id": class_member_id,
        "claimed_loss_cents": 5000,
    }
    payload.update(overrides)
    return payload


def file_claim_self_serve_payload(settlement_id, **overrides) -> dict:
    """Body for POST /class-members/{id}/file-claim (member pinned from path)."""
    payload = {
        "settlement_id": settlement_id,
        "claimed_loss_cents": 5000,
    }
    payload.update(overrides)
    return payload


def create_deficiency_payload(**overrides) -> dict:
    payload = {
        "reason_code": "MISSING_PROOF",
        "cure_deadline": "2026-02-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_opt_out_payload(settlement_id, class_member_id, **overrides) -> dict:
    payload = {
        "settlement_id": settlement_id,
        "class_member_id": class_member_id,
    }
    payload.update(overrides)
    return payload


def create_objection_payload(settlement_id, class_member_id, **overrides) -> dict:
    payload = {
        "settlement_id": settlement_id,
        "class_member_id": class_member_id,
        "grounds": "fees too high",
    }
    payload.update(overrides)
    return payload


def create_distribution_batch_payload(settlement_id, **overrides) -> dict:
    payload = {
        "settlement_id": settlement_id,
        "sequence_no": 1,
    }
    payload.update(overrides)
    return payload


def create_cy_pres_designation_payload(**overrides) -> dict:
    payload = {
        "recipient_name": "Test Charity",
        "share_bps": 10000,
    }
    payload.update(overrides)
    return payload
