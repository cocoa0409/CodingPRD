"""Autopay OCC: stale-version rejection and correct-version acceptance;
list endpoints (documents pagination default, ballots filter)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    api_client,
    setup_homeowner_with_autopay,
    setup_open_motion,
    create_homeowner,
    create_document,
    create_ballot_payload,
    set_clock,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue B — errors / stale_version_on_autopay_supersede
# ===========================================================================
def test_second_autopay_with_stale_version_rejected(api):
    """PRD §2.10: "The autopay-mandate creation endpoint (see §3.3) requires
    the payload to include `expected_homeowner_version`, carrying the client's
    last observed `version` of the target `Homeowner`. If
    `expected_homeowner_version` does not equal the target homeowner's
    current `version` at the moment the create is processed, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_version_on_autopay_supersede
    """
    homeowner = create_homeowner("hocc@ex.com", "H OCC")
    original_version = homeowner["version"]
    resp = api.create_autopay_mandate(
        homeowner["id"],
        {"expected_homeowner_version": original_version,
         "max_charge_cents": 50000},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_success(resp, expected_status=201)
    # Second create with the SAME (now stale) version.
    resp = api.create_autopay_mandate(
        homeowner["id"],
        {"expected_homeowner_version": original_version,
         "max_charge_cents": 75000},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_correct_version_accepted
# ===========================================================================
def test_autopay_with_correct_version_increments_and_supersedes(api):
    """PRD §2.10: "A successful create supersedes any active mandate and
    increments the homeowner's `version` by one — so the very next such
    request from any client using the previously-observed version will fail
    this check."
    PRD §3.3: "On success the server flips any prior `ACTIVE` mandate for
    this homeowner to `SUPERSEDED`, creates the new mandate with `status`
    set to `ACTIVE`, and increments the homeowner's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_accepted
    """
    homeowner, first_mandate = setup_homeowner_with_autopay(
        email="hoccp@ex.com", full_name="H OCC P", max_charge_cents=40000
    )
    assert homeowner["version"] == 2  # incremented from 1 by first mandate

    resp = api.create_autopay_mandate(
        homeowner["id"],
        {"expected_homeowner_version": homeowner["version"],
         "max_charge_cents": 80000},
        make_homeowner_headers(homeowner["id"]),
    )
    m2 = validate_success(resp, expected_status=201)
    assert m2["status"] == "ACTIVE"

    resp = api.list_autopay_mandates(
        homeowner["id"], make_homeowner_headers(homeowner["id"])
    )
    mandates = validate_success(resp)
    assert len(mandates) == 2


# ===========================================================================
# Queue B — endpoints / pagination_defaults_on_documents_list
# ===========================================================================
def test_documents_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; if not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."

    Design: Corner/endpoints/pagination_defaults_on_documents_list
    """
    for i in range(1, 12):
        create_document(title=f"doc-{i:02d}", category="POLICY",
                        content_url=f"u{i}")
    resp = api.list_documents(_MANAGER)
    page1 = validate_success(resp)
    assert len(page1) == 10
    resp = api.list_documents(_MANAGER, params={"offset": 10})
    page2 = validate_success(resp)
    assert len(page2) == 1


# ===========================================================================
# Queue B — endpoints / filtered_list_ballots_by_homeowner
# ===========================================================================
def test_ballots_filter_by_homeowner(api):
    """PRD §3.7: "Reverse-reachability lists — the ballots cast on a motion,
    the ballots cast by a homeowner (filterable by `homeowner_id` or
    `motion_id`), and the retrieval of a single ballot — are available to
    the acting homeowner, board members, and the manager."

    Design: Corner/endpoints/filtered_list_ballots_by_homeowner
    """
    board_member, m1 = setup_open_motion(
        board_email="bmfl@ex.com",
        title="M1", category="POLICY",
        voting_window_start="2026-04-01T00:00:00Z",
        voting_window_end="2026-04-05T00:00:00Z",
        eligible_voter_count=5, quorum_pct=40,
    )
    resp = api.create_motion(
        {"title": "M2", "description": "D2", "category": "ELECTION",
         "voting_window_start": "2026-04-10T00:00:00Z",
         "voting_window_end": "2026-04-15T00:00:00Z",
         "eligible_voter_count": 5, "quorum_pct": 40},
        make_board_member_headers(board_member["id"]),
    )
    m2 = validate_success(resp, expected_status=201)
    v1 = create_homeowner("v1@ex.com", "V1")
    v2 = create_homeowner("v2@ex.com", "V2")

    set_clock("2026-04-02T00:00:00Z")
    api.cast_ballot(
        m1["id"], create_ballot_payload(v1["id"], choice="YES"),
        make_homeowner_headers(v1["id"]),
    )
    api.cast_ballot(
        m1["id"], create_ballot_payload(v2["id"], choice="NO"),
        make_homeowner_headers(v2["id"]),
    )
    set_clock("2026-04-11T00:00:00Z")
    api.cast_ballot(
        m2["id"], create_ballot_payload(v1["id"], choice="YES"),
        make_homeowner_headers(v1["id"]),
    )
    api.cast_ballot(
        m2["id"], create_ballot_payload(v2["id"], choice="YES"),
        make_homeowner_headers(v2["id"]),
    )
    resp = api.list_ballots(_MANAGER, params={"homeowner_id": v1["id"]})
    data = validate_success(resp)
    assert len(data) == 2
