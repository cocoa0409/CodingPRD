"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_POLICY_PERIOD = {
    "period_start": "2026-01-01T00:00:00Z",
    "period_end": "2026-12-31T23:59:59Z",
}
DEFAULT_ENTRY_WINDOW = {
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}
DEFAULT_DATE_OF_LOSS = "2026-03-10T00:00:00Z"


def create_carrier_payload(**overrides) -> dict:
    defaults = {"name": "ZeroTax Mutual", "tax_rate": 0}
    defaults.update(overrides)
    return defaults


def create_price_list_entry_payload(**overrides) -> dict:
    defaults = {
        "category_code": "GEN-1",
        "trade": "GENERAL",
        "kind": "LABOR",
        "unit": "EA",
        "unit_price_cents": 200,
    }
    defaults.update(DEFAULT_ENTRY_WINDOW)
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Sam Owner", "email": "sam@example.com"}
    defaults.update(overrides)
    return defaults


def create_policy_payload(customer_id: str, carrier_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "carrier_id": carrier_id,
        "policy_number": "POL-1",
        "coverage_a_limit_cents": 5000000,
        "deductible_type": "FLAT",
        "flat_deductible_cents": 50000,
        "recoverable_depreciation": True,
    }
    defaults.update(DEFAULT_POLICY_PERIOD)
    defaults.update(overrides)
    # PRD §3.2: the deductible field must match deductible_type — supplying the
    # wrong field for the declared type is rejected with ERR_INVALID_REQUEST.
    # The FLAT default above must not leak into a PERCENT_OF_COVERAGE_A payload
    # built purely via overrides (unless the caller explicitly passed it to
    # exercise the rejection path).
    if defaults["deductible_type"] == "PERCENT_OF_COVERAGE_A" \
            and "flat_deductible_cents" not in overrides:
        defaults.pop("flat_deductible_cents", None)
    if defaults["deductible_type"] == "FLAT" \
            and "deductible_pct" not in overrides:
        defaults.pop("deductible_pct", None)
    return defaults


def create_claim_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "cause_of_loss": "FIRE",
        "date_of_loss": DEFAULT_DATE_OF_LOSS,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "type": "INITIAL",
        "assignee_id": "tech-1",
        "scheduled_start": "2026-05-02T09:00:00Z",
        "scheduled_end": "2026-05-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_moisture_reading_payload(**overrides) -> dict:
    defaults = {
        "area": "kitchen",
        "material": "drywall",
        "reading_value": 13,
        "dry_standard": 12,
        "recorded_at": "2026-05-02T09:10:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "tag": "AREA",
        "file_ref": "photo.jpg",
        "captured_at": "2026-05-02T09:05:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(expected_claim_version: int) -> dict:
    return {"expected_claim_version": expected_claim_version}


def create_estimate_line_payload(price_list_entry_id: str, qty, **overrides) -> dict:
    defaults = {"price_list_entry_id": price_list_entry_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def create_negotiation_round_payload(dispositions: list) -> dict:
    return {"dispositions": dispositions}


def create_append_dispositions_payload(expected_round_version: int, dispositions: list) -> dict:
    return {
        "expected_negotiation_round_version": expected_round_version,
        "dispositions": dispositions,
    }


def create_respond_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def create_supplement_payload(narrative: str = "Hidden damage found") -> dict:
    return {"narrative": narrative}


def create_code_upgrade_payload(**overrides) -> dict:
    defaults = {
        "code_citation": "NEC 210.12",
        "description": "AFCI breakers",
        "estimated_cost_cents": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_work_authorization_payload(
    direct_pay_assignment: bool = True, deductible_acknowledged: bool = True
) -> dict:
    return {
        "direct_pay_assignment": direct_pay_assignment,
        "deductible_acknowledged": deductible_acknowledged,
    }


def create_payment_payload(payment_type: str, amount_cents: int) -> dict:
    return {"type": payment_type, "amount_cents": amount_cents}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
