"""Job creation, list pagination envelope, and body-validation / existence errors."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    create_config, create_draft_job, create_job_payload,
    make_customer_headers, ADMIN, api_client,
)

WINDOW_START = "2026-03-11T09:00:00Z"
WINDOW_END = "2026-03-11T12:00:00Z"


def test_create_job_returns_201_draft_owned_by_customer(api):
    """PRD §3.3: "A `Customer` creates a job, which begins in status `DRAFT`." PRD §3.3: "The
    job's `customer_id` is taken from the acting customer's `X-User-ID`."

    Design: Corner/endpoints/job_create_returns_201_with_fields
    """
    rate_card, policy, customer = create_config(api)
    resp = api.create_job(
        create_job_payload(rate_card["id"], policy["id"], crew_size=2, estimated_hours=3.0,
                           window_start=WINDOW_START, window_end=WINDOW_END),
        make_customer_headers(customer["id"]),
    )
    job = validate_success(resp, 201)
    assert job["status"] == "DRAFT"
    assert job["customer_id"] == customer["id"]


def test_list_jobs_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` reflects the total
    number of matching resources before pagination and `has_more` indicates whether further
    pages remain."

    Two jobs for one customer, filtered with limit 1, return a 1-item page with total_count 2
    and has_more true.

    Design: Corner/endpoints/list_jobs_pagination_envelope
    """
    rate_card, policy, customer = create_config(api)
    create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                     window_start=WINDOW_START, window_end=WINDOW_END)
    create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                     window_start="2026-03-12T09:00:00Z", window_end="2026-03-12T11:00:00Z")
    resp = api.list_jobs(make_customer_headers(customer["id"]),
                         params={"customer_id": customer["id"], "limit": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    body = resp.json()
    assert body["response_type"] == "array"
    assert "api_request_id" in body["meta"] and "api_request_timestamp" in body["meta"]


def test_get_unknown_job_returns_not_found(api):
    """PRD §2.8: "the server validates existence left-to-right, path identifiers first and
    then body foreign keys, and rejects the first missing reference with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_nonexistent_job_returns_not_found
    """
    resp = api.get_job(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_job_missing_rate_card_id_rejected(api):
    """PRD §2.8: "Malformed request bodies — a missing required field, a value of the wrong
    type, or an enum value outside the allowed set — are rejected with `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/job_create_missing_required_returns_invalid_request
    """
    rate_card, policy, customer = create_config(api)
    payload = {
        "insurance_policy_id": policy["id"],
        "job_type": "MOVE",
        "crew_size": 1,
        "estimated_hours": 2.0,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
    }
    resp = api.create_job(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_job_type_mismatch_with_rate_card_rejected(api):
    """PRD §3.3: "At creation the system validates that `job_type` equals the referenced rate
    card's `job_type`, that `crew_size` is at least 1, that `estimated_hours` is greater than
    0, and that `window_end` is strictly later than `window_start`; any violation is rejected
    with `ERR_INVALID_REQUEST`."

    Job job_type LOAD against a MOVE rate card violates the equality rule.

    Design: Corner/entities/job_create_type_mismatch_rejected
    """
    rate_card, policy, customer = create_config(api)  # rate card is MOVE
    resp = api.create_job(
        create_job_payload(rate_card["id"], policy["id"], job_type="LOAD", crew_size=1,
                           estimated_hours=2.0, window_start=WINDOW_START, window_end=WINDOW_END),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
