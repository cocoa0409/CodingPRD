"""Cross-entity cascades and conserved-quantity invariants: the four-level cancel
cascade, the filing-accept bubble chain, stakeout schedule/cancel fee conservation,
accept/reassign capacity conservation, and the skip-trace LOCATED address bubble.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_server_headers,
    setup_reference_data,
    setup_active_assignment,
    setup_submitted_filing,
    assert_fee_equals_nonvoided_lines,
    find_lines,
    get_request,
    get_invoice_lines,
    get_server_entity,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────────
def test_cancel_request_depth4_voids_stakeout_line_and_recomputes_fee(api):
    """PRD 3.10: "At level one, the current `ACTIVE` assignment is cancelled
    (`ACTIVE → CANCELLED`). At level two, that assignment cancellation ...
    transitions every `SCHEDULED` stakeout under that assignment to `CANCELLED`.
    At level three, each cancelled stakeout voids its `STAKEOUT` invoice line (the
    line's `voided` flag becomes true). At level four, the request's
    `final_fee_cents` is recomputed over the surviving non-voided lines."

    Design: Difficulty/transitive_cascade/cancel_request_depth4_void_stakeout_line_recompute_fee
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Lake", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1},
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
    )
    svr = make_server_headers(server["id"])
    stk = get_success_data(
        api.create_stakeout(
            asg["id"],
            {"window_start_utc": "2026-01-02T06:00:00Z", "window_end_utc": "2026-01-02T10:00:00Z"},
            svr,
        )
    )
    pre = get_request(sr["id"])
    # BASE 7500 + PRINTING 75 + STAKEOUT 12000 = 19575.
    assert pre["final_fee_cents"] == 19575, f"pre-cancel fee should be 19575, got {pre['final_fee_cents']}"

    cancelled = validate_success(api.cancel_request(sr["id"], DISPATCHER), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["final_fee_cents"] == 7575, f"post-cancel fee should be 7575, got {cancelled['final_fee_cents']}"

    asg_after = validate_success(api.get_assignment(asg["id"], DISPATCHER))
    assert asg_after["status"] == "CANCELLED"
    stk_after = get_success_data(api.list_assignment_stakeouts(asg["id"], DISPATCHER))[0]
    assert stk_after["status"] == "CANCELLED"
    lines = get_invoice_lines(sr["id"])
    stakeout_lines = find_lines(lines, "STAKEOUT", include_voided=True)
    assert len(stakeout_lines) == 1 and stakeout_lines[0]["voided"] is True, "STAKEOUT line must be voided"


def test_filing_accepted_depth3_bubbles_request_and_affidavit_to_filed(api):
    """PRD 3.9: "Acceptance — `SUBMITTED → ACCEPTED` — bubbles the request up
    `SERVED → FILED` and moves the affidavit `NOTARIZED → FILED`."

    Design: Difficulty/transitive_cascade/filing_accepted_depth3_request_filed_then_server_score_recompute
    """
    county, server, client, sr, aff, filing = _setup_submitted_filing_glenn(api)
    accepted = validate_success(api.set_filing_state(filing["id"], {"to_status": "ACCEPTED"}, DISPATCHER), 200)
    assert accepted["status"] == "ACCEPTED"
    sr_after = get_request(sr["id"])
    assert sr_after["status"] == "FILED", f"request should bubble to FILED, got {sr_after['status']}"
    aff_after = get_success_data(api.get_affidavit(aff["id"], DISPATCHER))
    assert aff_after["status"] == "FILED", f"affidavit should bubble to FILED, got {aff_after['status']}"


def _setup_submitted_filing_glenn(api):
    county, server, client, sr, asg, aff, filing = setup_submitted_filing(
        deposit_cents=50_000,
        county_overrides={"name": "Glenn", "state_code": "CA", "e_file_enabled": True,
                          "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2},
        notary_user_id="notary-3",
    )
    return county, server, client, sr, aff, filing


# ─── Queue A: compensating_invariant ──────────────────────────────────────
def test_stakeout_schedule_then_cancel_conserves_fee(api):
    """PRD 3.6: "Setting it to `CANCELLED` ... voids this stakeout's `STAKEOUT`
    invoice line (its `voided` flag becomes true) and recomputes the request's
    `final_fee_cents`."
    PRD 3.12: a `voided` flag "excludes the line from totals once its underlying
    billable is cancelled or superseded."

    Design: Difficulty/compensating_invariant/stakeout_schedule_cancel_conserves_invoice_total_money
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Inyo", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1},
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
    )
    svr = make_server_headers(server["id"])
    stk = get_success_data(
        api.create_stakeout(
            asg["id"],
            {"window_start_utc": "2026-01-02T06:00:00Z", "window_end_utc": "2026-01-02T08:00:00Z"},
            svr,
        )
    )
    mid = get_request(sr["id"])
    assert mid["final_fee_cents"] == 19575, f"after scheduling stakeout fee should be 19575, got {mid['final_fee_cents']}"

    cancelled = validate_success(api.set_stakeout_state(stk["id"], {"to_status": "CANCELLED"}, svr), 200)
    assert cancelled["status"] == "CANCELLED"
    sr_after = get_request(sr["id"])
    assert sr_after["final_fee_cents"] == 7575, f"after cancel fee should return to 7575, got {sr_after['final_fee_cents']}"
    lines = get_invoice_lines(sr["id"])
    assert_fee_equals_nonvoided_lines(sr_after, lines)


def test_accept_then_reassign_conserves_active_assignment_count(api):
    """PRD 3.3: the auto-advance to ACTIVE "increments the server's
    `active_assignment_count` by one"; and reassigning means "the server's
    `active_assignment_count` is decremented by one (with no change to
    `completed_count`...)".
    PRD 3.1: "`active_assignment_count` is, by invariant, exactly the number of
    assignments in `ACTIVE` status whose `server_id` is this server".

    Design: Difficulty/compensating_invariant/accept_then_reassign_conserves_server_active_count_capacity
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Mono", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1}
    )
    mid = get_server_entity(server["id"])
    assert mid["active_assignment_count"] == 1, f"after accept count should be 1, got {mid['active_assignment_count']}"

    validate_success(api.reassign(sr["id"], DISPATCHER), 200)
    asg_after = validate_success(api.get_assignment(asg["id"], DISPATCHER))
    assert asg_after["status"] == "REASSIGNED"
    after = get_server_entity(server["id"])
    assert after["active_assignment_count"] == 0, f"after reassign count should return to 0, got {after['active_assignment_count']}"


def test_cancel_cascade_decrements_server_active_count(api):
    """PRD 3.10: "At level two, that assignment cancellation decrements the
    server's `active_assignment_count` by one and recomputes the server's
    `reliability_score`". This is the level-2 effect of the cancel cascade, distinct
    from the level-3/4 invoice-line voiding asserted elsewhere.

    Design: Difficulty/transitive_cascade/cancel_request_depth4_void_stakeout_line_recompute_fee
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Lake2", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1},
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
    )
    svr = make_server_headers(server["id"])
    get_success_data(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T06:00:00Z", "window_end_utc": "2026-01-02T10:00:00Z"}, svr
        )
    )
    mid = get_server_entity(server["id"])
    assert mid["active_assignment_count"] == 1
    get_success_data(api.cancel_request(sr["id"], DISPATCHER))
    after = get_server_entity(server["id"])
    assert after["active_assignment_count"] == 0, "cancel cascade must free the server's active slot"


def test_filing_accepted_does_not_complete_request(api):
    """PRD 3.9: "Acceptance — `SUBMITTED → ACCEPTED` — bubbles the request up
    `SERVED → FILED`". The bubble stops at FILED; the request is not yet COMPLETED
    (completion is a separate dispatcher action, PRD 3.11).

    Design: Difficulty/transitive_cascade/filing_accepted_depth3_request_filed_then_server_score_recompute
    """
    county, server, client, sr, aff, filing = _setup_submitted_filing_glenn(api)
    # Before accept the request is SERVED.
    assert get_request(sr["id"])["status"] == "SERVED"
    get_success_data(api.set_filing_state(filing["id"], {"to_status": "ACCEPTED"}, DISPATCHER))
    sr_after = get_request(sr["id"])
    assert sr_after["status"] == "FILED", "filing acceptance bubbles to FILED, not COMPLETED"


def test_stakeout_cancel_voids_only_stakeout_line(api):
    """PRD 3.6: "Setting it to `CANCELLED` ... voids this stakeout's `STAKEOUT`
    invoice line (its `voided` flag becomes true)". The BASE/PRINTING lines stay
    non-voided; only the STAKEOUT line is voided.

    Design: Difficulty/compensating_invariant/stakeout_schedule_cancel_conserves_invoice_total_money
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Inyo2", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1},
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
    )
    svr = make_server_headers(server["id"])
    stk = get_success_data(
        api.create_stakeout(
            asg["id"], {"window_start_utc": "2026-01-02T06:00:00Z", "window_end_utc": "2026-01-02T08:00:00Z"}, svr
        )
    )
    get_success_data(api.set_stakeout_state(stk["id"], {"to_status": "CANCELLED"}, svr))
    lines = get_invoice_lines(sr["id"])
    stakeout_lines = find_lines(lines, "STAKEOUT", include_voided=True)
    assert len(stakeout_lines) == 1 and stakeout_lines[0]["voided"] is True
    base = find_lines(lines, "BASE")
    assert len(base) == 1 and base[0]["voided"] is False, "BASE line must remain non-voided"


def test_reassign_leaves_completed_count_unchanged(api):
    """PRD 3.3: reassigning decrements active_assignment_count "with no change to
    `completed_count`, since the work was not completed". A reassigned (walked)
    assignment grants no completion credit.

    Design: Difficulty/compensating_invariant/accept_then_reassign_conserves_server_active_count_capacity
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Mono2", "state_code": "CA", "e_file_enabled": False, "min_diligent_attempts": 1}
    )
    before = get_server_entity(server["id"])
    assert before["completed_count"] == 0
    validate_success(api.reassign(sr["id"], DISPATCHER), 200)
    after = get_server_entity(server["id"])
    assert after["completed_count"] == 0, "reassign grants no completion credit"


# ─── Queue B: skip-trace LOCATED address bubble ───────────────────────────
def test_skiptrace_located_updates_request_service_address(api):
    """PRD 3.7: "On success the trace's `located_address` is set to the supplied
    value, and as a divergent side effect the parent request's `service_address`
    is updated to that located address so subsequent attempts target the confirmed
    location."

    Design: Corner/state_machines/skiptrace_located_updates_request_address_bubble
    """
    county, server, client = setup_reference_data(
        deposit_cents=0,
        county_overrides={"name": "Lassen", "state_code": "CA", "min_diligent_attempts": 1},
    )
    svr = make_server_headers(server["id"])
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "old addr", "service_lat": 40.4, "service_lng": -120.6,
             "skip_trace_requested": True}, DISPATCHER
        )
    )
    st = get_success_data(
        api.create_skip_trace(sr["id"], {"candidate_addresses": ["123 Found Ln", "999 Other Rd"]}, DISPATCHER)
    )
    get_success_data(api.set_skip_trace_state(st["id"], {"to_status": "IN_PROGRESS"}, svr))
    located = validate_success(
        api.set_skip_trace_state(st["id"], {"to_status": "LOCATED", "located_address": "123 Found Ln"}, svr), 200
    )
    assert located["status"] == "LOCATED"
    assert located["located_address"] == "123 Found Ln"
    sr_after = get_request(sr["id"])
    assert sr_after["service_address"] == "123 Found Ln", "request service_address must be overwritten to located address"
