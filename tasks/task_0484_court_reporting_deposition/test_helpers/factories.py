"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_case_payload(**overrides) -> dict:
    defaults = {
        "caption": "Doe v Acme Corp",
        "docket_number": "D-DEFAULT-1",
        "jurisdiction": "STATE_CA",
        "noticing_attorney_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_attorney_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Attorney",
        "firm_name": "Test LLP",
        "bar_state": "CA",
        "email": "attorney-default@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_resource_payload(**overrides) -> dict:
    # certifications / realtime_capable are optional (PRD §3.1); included only
    # when the caller overrides them, otherwise the server applies its defaults.
    defaults = {
        "full_name": "Test Resource",
        "kind": "REPORTER",
        "hourly_appearance_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(**overrides) -> dict:
    # requires_* and interpreter_language are optional (PRD §3.2); included only
    # when overridden.
    defaults = {
        "case_id": None,
        "deponent_name": "Witness W",
        "scheduled_start": "2026-06-01T09:00:00Z",
        "scheduled_end": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "resource_id": None,
        "role": "REPORTER",
        "expected_job_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_realtime_stream_payload(**overrides) -> dict:
    defaults = {"reporter_assignment_id": None}
    defaults.update(overrides)
    return defaults


def create_transcript_order_payload(**overrides) -> dict:
    # certified_copy is optional (PRD §3.8, defaults true); included only when
    # overridden.
    defaults = {
        "job_id": None,
        "ordering_attorney_id": None,
        "turnaround_tier": "STANDARD",
        "estimated_pages": 30,
    }
    defaults.update(overrides)
    return defaults


def create_exhibit_payload(**overrides) -> dict:
    # confidential is optional (PRD §3.9, defaults false); included only when
    # overridden.
    defaults = {
        "marked_label": "Exhibit 1",
        "page_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_errata_payload(**overrides) -> dict:
    defaults = {
        "corrections": [{"page": 1, "line": 1, "from_text": "x", "to_text": "y"}],
        "reason": "transcription error",
    }
    defaults.update(overrides)
    return defaults


def create_certify_payload(**overrides) -> dict:
    defaults = {"final_pages": 30}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    # bill_to_attorney_id is optional (PRD §3.14); included only when overridden.
    defaults = {
        "job_id": None,
        "transcript_order_id": None,
    }
    defaults.update(overrides)
    return defaults
