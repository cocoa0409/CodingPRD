"""Payload factories — one per creatable entity, input fields only."""


def create_work_payload(**overrides) -> dict:
    payload = {
        "title": "Test Work",
        "work_type": "LITERARY",
        "year_of_creation": 2024,
        "author_name": "Ann Author",
        "owner_shares": [{"name": "Ann Author", "share_bps": 10000}],
    }
    payload.update(overrides)
    return payload


def create_application_payload(work_id, **overrides) -> dict:
    payload = {
        "work_id": work_id,
        "filing_basis": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "deposit_type": "ELECTRONIC",
        "copy_count": 1,
    }
    payload.update(overrides)
    return payload


def pay_fee_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def issue_correspondence_payload(**overrides) -> dict:
    payload = {"issue_code": "CLAIM_UNCLEAR", "message": "Please clarify."}
    payload.update(overrides)
    return payload


def respond_correspondence_payload(**overrides) -> dict:
    payload = {"message": "Clarified."}
    payload.update(overrides)
    return payload


def create_recordation_payload(work_id, expected_work_version, **overrides) -> dict:
    payload = {
        "work_id": work_id,
        "transferor_name": "Ann Author",
        "transferee_name": "New Owner",
        "execution_date": "2026-05-02T00:00:00Z",
        "expected_work_version": expected_work_version,
    }
    payload.update(overrides)
    return payload


def create_license_payload(work_id, **overrides) -> dict:
    payload = {
        "work_id": work_id,
        "licensee_name": "Licensee Co",
        "license_type": "NON_EXCLUSIVE",
        "right_type": "REPRODUCTION",
        "territory": "US",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2027-01-01T00:00:00Z",
        "grant_date": "2026-01-01T00:00:00Z",
        "royalty_rate_bps": 1500,
        "royalty_basis": "GROSS",
    }
    payload.update(overrides)
    return payload


def create_royalty_statement_payload(license_id, **overrides) -> dict:
    payload = {
        "license_id": license_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "gross_revenue_cents": 22220,
    }
    payload.update(overrides)
    return payload


def create_dmca_takedown_payload(work_id, **overrides) -> dict:
    payload = {
        "work_id": work_id,
        "complainant_name": "Complaining Party",
        "infringing_url": "http://example.com/infringing",
    }
    payload.update(overrides)
    return payload


def create_counter_notice_payload(takedown_id, **overrides) -> dict:
    payload = {
        "takedown_id": takedown_id,
        "subscriber_name": "Subscriber",
        "statement": "Good-faith statement contesting the takedown.",
    }
    payload.update(overrides)
    return payload


def create_termination_payload(license_id, **overrides) -> dict:
    payload = {
        "license_id": license_id,
        "terminating_party_name": "Ann Author",
        "notice_served_date": "2020-06-01T00:00:00Z",
        "effective_date": "2025-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
