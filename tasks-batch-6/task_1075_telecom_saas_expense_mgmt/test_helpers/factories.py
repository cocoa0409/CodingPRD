"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VENDOR_NAME": "Acme SaaS",
    "VENDOR_TYPE": "SAAS",
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2026-12-31T00:00:00Z",
    "RENEWAL_NOTICE_DAYS": 60,
    "SERVICE_TYPE": "SAAS_SUBSCRIPTION",
    "LICENSE_TYPE": "PER_SEAT",
    "UNIT_RATE_CENTS": 2000,
    "CONTRACTED_QUANTITY": 60,
    "ACTIVE_QUANTITY": 42,
    "PERIOD_START": "2026-06-01T00:00:00Z",
    "PERIOD_END": "2026-06-30T00:00:00Z",
    "BILLING_START": "2026-06-01T00:00:00Z",
    "BILLING_END": "2026-07-01T00:00:00Z",
    "BILLED_QUANTITY": 60,
    "BILLED_AMOUNT_CENTS": 100000,
}


def create_vendor_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["VENDOR_NAME"], "vendor_type": DEFAULTS["VENDOR_TYPE"]}
    payload.update(overrides)
    return payload


def create_contract_payload(vendor_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "renewal_notice_days": DEFAULTS["RENEWAL_NOTICE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_service_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "service_type": DEFAULTS["SERVICE_TYPE"],
        "license_type": DEFAULTS["LICENSE_TYPE"],
        "unit_rate_cents": DEFAULTS["UNIT_RATE_CENTS"],
        "contracted_quantity": DEFAULTS["CONTRACTED_QUANTITY"],
        "active_quantity": DEFAULTS["ACTIVE_QUANTITY"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_line_item_payload(service_id, **overrides) -> dict:
    payload = {
        "service_id": service_id,
        "billing_period_start": DEFAULTS["BILLING_START"],
        "billing_period_end": DEFAULTS["BILLING_END"],
        "billed_quantity": DEFAULTS["BILLED_QUANTITY"],
        "billed_amount_cents": DEFAULTS["BILLED_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(disputed_amount_cents, claimed_credit_cents, **overrides) -> dict:
    payload = {
        "disputed_amount_cents": disputed_amount_cents,
        "claimed_credit_cents": claimed_credit_cents,
    }
    payload.update(overrides)
    return payload


def respond_dispute_payload(response_type, offered_credit_cents, **overrides) -> dict:
    payload = {"response_type": response_type, "offered_credit_cents": offered_credit_cents}
    payload.update(overrides)
    return payload


def resubmit_dispute_payload(claimed_credit_cents, **overrides) -> dict:
    payload = {"claimed_credit_cents": claimed_credit_cents}
    payload.update(overrides)
    return payload


def create_cost_center_payload(code, gl_account, owner_user_id, **overrides) -> dict:
    payload = {"code": code, "gl_account": gl_account, "owner_user_id": owner_user_id}
    payload.update(overrides)
    return payload


def create_recommendation_payload(rec_type, target_quantity, expected_service_version, **overrides) -> dict:
    payload = {
        "rec_type": rec_type,
        "target_quantity": target_quantity,
        "expected_service_version": expected_service_version,
    }
    payload.update(overrides)
    return payload


def allocations_payload(entries) -> dict:
    """entries: list of {'cost_center_id': ..., 'weight_pct': ...}."""
    return {"allocations": entries}
