"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "HIRED_AT": "2026-05-01T00:00:00Z",
    "NDA_EFFECTIVE": "2026-01-01T00:00:00Z",
    "NDA_EXPIRY": "2027-01-01T00:00:00Z",
    "GRANT_EXPIRES": "2026-12-01T00:00:00Z",
    "PLANNED_DISCLOSURE": "2026-07-01T00:00:00Z",
}


def create_asset_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "title": f"Asset {n}",
        "description": f"Description for asset {n}",
        "classification": "INTERNAL",
        "owner_department": "ENG",
        "exposure_estimate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_measure_payload(asset_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "asset_id": asset_id,
        "measure_type": "POLICY",
        "title": f"Measure {n}",
        "evidence_uri": f"s3://ev/m{n}.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_counterparty_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"Counterparty {n} Ltd",
        "counterparty_type": "VENDOR",
    }
    defaults.update(overrides)
    return defaults


def create_nda_payload(counterparty_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "counterparty_id": counterparty_id,
        "template_version": f"t{n}",
        "governing_law": "DE",
        "effective_date": DEFAULTS["NDA_EFFECTIVE"],
        "expiry_date": DEFAULTS["NDA_EXPIRY"],
        "survival_months": 6,
        "classification_ceiling": "CROWN_JEWEL",
    }
    defaults.update(overrides)
    return defaults


def create_obligation_payload(nda_id, **overrides) -> dict:
    defaults = {
        "nda_id": nda_id,
        "obligation_type": "NON_DISCLOSURE",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Employee {n}",
        "email": f"employee{n}@example.com",
        "department": "ENG",
        "role_title": "Engineer",
        "access_clearance": "STANDARD",
        "hired_at": DEFAULTS["HIRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_exit_interview_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "scheduled_start": "2026-05-10T10:00:00Z",
        "scheduled_end": "2026-05-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(employee_id, asset_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "asset_id": asset_id,
        "justification": "Need-to-know justification",
        "expires_at": DEFAULTS["GRANT_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(asset_id, nda_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "nda_id": nda_id,
        "purpose": "Business purpose",
        "marking_protocol": "STAMPED_CONFIDENTIAL",
        "planned_disclosure_date": DEFAULTS["PLANNED_DISCLOSURE"],
    }
    defaults.update(overrides)
    return defaults


def create_forensic_review_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "trigger_reason": "POLICY",
    }
    defaults.update(overrides)
    return defaults


def create_demand_letter_payload(forensic_review_id, claim_lines, **overrides) -> dict:
    defaults = {
        "forensic_review_id": forensic_review_id,
        "claim_lines": claim_lines,
        "response_deadline_days": 14,
    }
    defaults.update(overrides)
    return defaults


def create_preservation_notice_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_matter_ref": f"M-2026-{n:03d}",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(review_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "review_id": review_id,
        "source": "ACCESS_LOG",
        "sha256": f"{n % 16:x}" * 64,
        "byte_size": 1024,
    }
    defaults.update(overrides)
    return defaults


def create_training_assignment_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "module": "CLEAN_DESK",
        "due_at": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_clean_desk_audit_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "department": f"DEPT{n}",
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
