"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "COURT_NAME": "Housing Court",
    "JURISDICTION": "J1",
    "HEARING_DAILY_CAPACITY": 2,
    "LANDLORD_NAME": "Acme Property LLC",
    "LANDLORD_EMAIL": "landlord@example.com",
    "TENANT_NAME": "Jane Tenant",
    "TENANT_EMAIL": "tenant@example.com",
    "HOUSEHOLD_INCOME_CENTS": 200000,
    "HOUSEHOLD_SIZE": 3,
    "OFFICER_NAME": "Deputy Smith",
    "BADGE_NUMBER": "B1",
    "AGENCY": "County Sheriff",
    "PROVIDER_NAME": "Aid Program",
}


def create_court_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COURT_NAME"],
        "jurisdiction_code": DEFAULTS["JURISDICTION"],
        "hearing_daily_capacity": DEFAULTS["HEARING_DAILY_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_landlord_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["LANDLORD_NAME"],
        "email": DEFAULTS["LANDLORD_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_tenant_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TENANT_NAME"],
        "email": DEFAULTS["TENANT_EMAIL"],
        "household_income_cents": DEFAULTS["HOUSEHOLD_INCOME_CENTS"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_officer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["OFFICER_NAME"],
        "badge_number": DEFAULTS["BADGE_NUMBER"],
        "agency": DEFAULTS["AGENCY"],
    }
    payload.update(overrides)
    return payload


def create_case_payload(court_id, landlord_id, tenant_id,
                        filing_type="NONPAYMENT", **overrides) -> dict:
    payload = {
        "court_id": court_id,
        "landlord_id": landlord_id,
        "tenant_id": tenant_id,
        "filing_type": filing_type,
    }
    payload.update(overrides)
    return payload


def create_answer_payload(case_id, defenses=None, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "defenses": defenses if defenses is not None else ["RENT_PAID"],
    }
    payload.update(overrides)
    return payload


def create_referral_payload(case_id, referral_type, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "referral_type": referral_type,
        "provider_name": DEFAULTS["PROVIDER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_mediation_session_payload(case_id, mediator_user_id, scheduled_at, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "mediator_user_id": mediator_user_id,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def create_payment_plan_payload(case_id, total_cents, installment_count,
                                expected_case_version, proposed_by="LANDLORD",
                                first_due_date="2026-05-20T00:00:00Z", **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "proposed_by": proposed_by,
        "total_cents": total_cents,
        "installment_count": installment_count,
        "first_due_date": first_due_date,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_hearing_payload(case_id, court_id, scheduled_start, scheduled_end,
                           hearing_type="INITIAL", **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "court_id": court_id,
        "hearing_type": hearing_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_judgment_payload(case_id, judgment_type, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "judgment_type": judgment_type,
    }
    payload.update(overrides)
    return payload


def create_lockout_order_payload(case_id, judgment_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "judgment_id": judgment_id,
    }
    payload.update(overrides)
    return payload


def create_sealing_request_payload(case_id, basis, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "basis": basis,
    }
    payload.update(overrides)
    return payload
