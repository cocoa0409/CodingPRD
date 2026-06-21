"""Payload factories — one per entity, input fields only."""


def create_employer_payload(**overrides) -> dict:
    """Employer input fields: legal_name, mro_user_id required; dot_regulated,
    net_terms_days, current_date optional with PRD defaults."""
    defaults = {
        "legal_name": "Test Employer",
        "mro_user_id": "mro-1",
    }
    defaults.update(overrides)
    return defaults


def panel(panel_code, required_for_job_category, price_cents, recheck_interval_days=0) -> dict:
    """A single protocol panel object."""
    return {
        "panel_code": panel_code,
        "required_for_job_category": required_for_job_category,
        "price_cents": price_cents,
        "recheck_interval_days": recheck_interval_days,
    }


def create_protocol_payload(employer_id, panels, effective_date="2026-01-01", **overrides) -> dict:
    """Protocol input: employer_id, effective_date, panels."""
    defaults = {
        "employer_id": employer_id,
        "effective_date": effective_date,
        "panels": panels,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(employer_id, **overrides) -> dict:
    """Worker input: employer_id, full_name, job_category, dob."""
    defaults = {
        "employer_id": employer_id,
        "full_name": "Test Worker",
        "job_category": "OP",
        "dob": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(employer_id, worker_id, encounter_type, **overrides) -> dict:
    """Encounter input: employer_id, worker_id, encounter_type, optional panel_code."""
    defaults = {
        "employer_id": employer_id,
        "worker_id": worker_id,
        "encounter_type": encounter_type,
    }
    defaults.update(overrides)
    return defaults


def create_drug_screen_payload(encounter_id, specimen_seal_intact=True, **overrides) -> dict:
    """DrugScreen input: encounter_id, specimen_seal_intact."""
    defaults = {
        "encounter_id": encounter_id,
        "specimen_seal_intact": specimen_seal_intact,
    }
    defaults.update(overrides)
    return defaults


def create_custody_event_payload(drug_screen_id, step, **overrides) -> dict:
    """CustodyEvent input: drug_screen_id, step, optional note."""
    defaults = {
        "drug_screen_id": drug_screen_id,
        "step": step,
    }
    defaults.update(overrides)
    return defaults


def create_injury_case_payload(encounter_id, treatment_level, injury_date="2026-01-02", **overrides) -> dict:
    """InjuryCase input: encounter_id, injury_date, treatment_level, optional days_away/days_restricted."""
    defaults = {
        "encounter_id": encounter_id,
        "injury_date": injury_date,
        "treatment_level": treatment_level,
    }
    defaults.update(overrides)
    return defaults


def create_work_status_payload(injury_case_id, disposition, valid_from, valid_to, **overrides) -> dict:
    """WorkStatus input: injury_case_id, disposition, valid_from, valid_to, optional restriction_text."""
    defaults = {
        "injury_case_id": injury_case_id,
        "disposition": disposition,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    defaults.update(overrides)
    return defaults


def create_surveillance_exam_payload(encounter_id, **overrides) -> dict:
    """SurveillanceExam input: encounter_id plus measurements appropriate to the exam kind."""
    defaults = {
        "encounter_id": encounter_id,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(encounter_id, determination, **overrides) -> dict:
    """Clearance input: encounter_id, determination, optional restriction_text."""
    defaults = {
        "encounter_id": encounter_id,
        "determination": determination,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(employer_id, period_start="2026-03-01", period_end="2026-03-31", **overrides) -> dict:
    """Invoice input: employer_id, period_start, period_end."""
    defaults = {
        "employer_id": employer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(employer_id, to_iso8601) -> dict:
    """Clock-set input: employer_id, to_iso8601."""
    return {"employer_id": employer_id, "to_iso8601": to_iso8601}
