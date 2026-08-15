"""Payer appeal policy half-open window geometry (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    create_policy_payload,
    make_payer,
    validate_error,
    validate_paginated,
    validate_success,
)

WINDOW_RULE_CITE = (
    'PRD §3.1: "Windows are half-open: for a given payer and level, two policies\' windows '
    'must never overlap, though adjacency is permitted — one policy\'s `effective_to` may '
    'equal the next policy\'s `effective_from`. A creation that would overlap an existing '
    'same-payer, same-level window fails with `ERR_POLICY_WINDOW_OVERLAP`."'
)


def _payer_with_first_window(api, director_headers):
    payer = make_payer()
    validate_success(
        api.create_payer_appeal_policy(
            create_policy_payload(
                payer["id"], 1, effective_from="2026-01-01", effective_to="2026-06-01",
            ),
            director_headers,
        ),
        expected_status=201,
    )
    return payer


def test_policy_window_adjacency_allowed(api, director_headers):
    """PRD §3.1: "Windows are half-open: for a given payer and level, two policies' windows
    must never overlap, though adjacency is permitted — one policy's `effective_to` may equal
    the next policy's `effective_from`. A creation that would overlap an existing same-payer,
    same-level window fails with `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency
    """
    payer = _payer_with_first_window(api, director_headers)
    adjacent = validate_success(
        api.create_payer_appeal_policy(
            create_policy_payload(
                payer["id"], 1, timely_filing_days=45, response_window_days=21,
                effective_from="2026-06-01",
            ),
            director_headers,
        ),
        expected_status=201,
    )
    assert adjacent["effective_from"] == "2026-06-01", (
        "the prior window [2026-01-01, 2026-06-01) excludes 2026-06-01"
    )
    assert adjacent["level_number"] == 1


def test_policy_window_overlap_rejected(api, director_headers):
    """PRD §3.1: "Windows are half-open: for a given payer and level, two policies' windows
    must never overlap, though adjacency is permitted — one policy's `effective_to` may equal
    the next policy's `effective_from`. A creation that would overlap an existing same-payer,
    same-level window fails with `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency
    """
    payer = _payer_with_first_window(api, director_headers)
    validate_success(
        api.create_payer_appeal_policy(
            create_policy_payload(
                payer["id"], 1, timely_filing_days=45, response_window_days=21,
                effective_from="2026-06-01",
            ),
            director_headers,
        ),
        expected_status=201,
    )
    resp = api.create_payer_appeal_policy(
        create_policy_payload(
            payer["id"], 1, timely_filing_days=30, response_window_days=21,
            required_attachment_types=[],
            effective_from="2026-05-31", effective_to="2026-07-01",
        ),
        director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP, expected_status=409)
    rows, meta = validate_paginated(
        api.list_payer_appeal_policies(director_headers, params={"payer_id": payer["id"]})
    )
    assert meta["total_count"] == 2, "exactly the two legal policies exist"
