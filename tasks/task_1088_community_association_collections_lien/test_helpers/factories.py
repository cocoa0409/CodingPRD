"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STATE_CODE": "CA",
    "UNIT_NUMBER": "1",
    "OWNER_NAME": "Test Owner",
    "DUE_DATE": "2026-01-01T00:00:00Z",
}


def create_association_payload(**overrides) -> dict:
    defaults = {"name": "Test HOA", "state_code": DEFAULTS["STATE_CODE"]}
    defaults.update(overrides)
    return defaults


def create_account_payload(association_id, **overrides) -> dict:
    defaults = {
        "association_id": association_id,
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "owner_name": DEFAULTS["OWNER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(account_id, amount_cents, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "charge_type": "REGULAR",
        "amount_cents": amount_cents,
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(account_id, amount_cents, received_date, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "received_date": received_date,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(account_id, notice_type, **overrides) -> dict:
    defaults = {"account_id": account_id, "notice_type": notice_type}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(account_id, total_amount_cents, installment_cents,
                                num_installments, first_due_date,
                                expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "total_amount_cents": total_amount_cents,
        "installment_cents": installment_cents,
        "num_installments": num_installments,
        "first_due_date": first_due_date,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_lien_payload(account_id, **overrides) -> dict:
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


def create_foreclosure_referral_payload(account_id, lien_id, **overrides) -> dict:
    defaults = {"account_id": account_id, "lien_id": lien_id, "attorney_name": "Doe & Firm"}
    defaults.update(overrides)
    return defaults


def create_bankruptcy_case_payload(account_id, filed_date, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "chapter": "CH13",
        "case_number": "26-0001",
        "filed_date": filed_date,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(association_id, period_start, period_end,
                              expected_association_version, **overrides) -> dict:
    defaults = {
        "association_id": association_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_association_version": expected_association_version,
    }
    defaults.update(overrides)
    return defaults
