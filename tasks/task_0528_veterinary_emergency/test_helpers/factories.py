"""Payload factories — one per entity, input fields only."""


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "name": "Rex",
        "species": "CANINE",
        "weight_kg": 30,
        "owner_user_id": "owner-1",
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "chief_complaint": "collapse",
    }
    defaults.update(overrides)
    return defaults


def triage_payload(triage_level: str = "YELLOW", **overrides) -> dict:
    defaults = {"triage_level": triage_level}
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "to_department": "CARDIOLOGY",
        "accepting_dvm_id": "dvm-cardio",
        "reason": "murmur",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(line_items=None, **overrides) -> dict:
    if line_items is None:
        line_items = [{"code": "TX", "description": "care", "qty": 1, "unit_price_cents": 100000}]
    defaults = {"line_items": line_items}
    defaults.update(overrides)
    return defaults


def issue_estimate_payload(expected_visit_version: int, **overrides) -> dict:
    defaults = {"expected_visit_version": expected_visit_version}
    defaults.update(overrides)
    return defaults


def create_authorization_payload(estimate_id: str, approved_ceiling_cents: int, **overrides) -> dict:
    defaults = {
        "estimate_id": estimate_id,
        "approved_ceiling_cents": approved_ceiling_cents,
    }
    defaults.update(overrides)
    return defaults


def create_hospitalization_payload(**overrides) -> dict:
    defaults = {
        "ward": "ICU",
        "cage_number": 1,
        "admit_at": "2026-05-01T08:00:00Z",
        "planned_discharge_at": "2026-05-02T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def release_hospitalization_payload(released_at: str, **overrides) -> dict:
    defaults = {"released_at": released_at}
    defaults.update(overrides)
    return defaults


def create_procedure_payload(**overrides) -> dict:
    defaults = {
        "modality": "IMAGING_CT",
        "resource_room": "CT_SUITE",
        "start_at": "2026-05-01T09:00:00Z",
        "end_at": "2026-05-01T09:30:00Z",
        "price_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(invoice_id: str, provider: str = "CARECREDIT",
                                term_months: int = 6, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "provider": provider,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def activate_payment_plan_payload(expected_visit_version: int, **overrides) -> dict:
    defaults = {"expected_visit_version": expected_visit_version}
    defaults.update(overrides)
    return defaults
