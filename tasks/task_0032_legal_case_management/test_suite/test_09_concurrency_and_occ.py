"""Optimistic concurrency control and PRD-defined race outcomes.

PRD §2.5 (OCC), §3.3 / §3.4 / §3.5 / §3.6 (race outcomes).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    DEFAULT_NOW,
    add_minutes,
    advance_clock,
    api_client,
    append_custody,
    assert_exactly_one_succeeds,
    collect_evidence,
    create_custody_event_payload,
    create_rebuttal_payload,
    issue_bill_for,
    payment_event_payload,
    run_race,
    setup_case_at_awaiting_settlement,
    setup_draft_in_review,
    setup_submitted_evidence,
    setup_three_lawyers_and_active_case,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ---------------------------------------------------------------------------
# OCC version mismatch (PRD §2.5)
# ---------------------------------------------------------------------------
def test_stale_version_on_adjust_rejected(api):
    """PRD §2.5: 'Mutating endpoints accept an optional version field in
    the request body. When present, the server compares it to the row's
    stored version and, on mismatch, rejects the request with
    ERR_VERSION_MISMATCH (HTTP 409).'

    Claim: PATCH adjust with stale version → ERR_VERSION_MISMATCH.
    """
    bundle = setup_three_lawyers_and_active_case()
    from test_helpers import log_time_entry, adjust_time_entry_payload
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    # First adjust succeeds and increments version.
    first = validate_success(
        api.adjust_time_entry(
            entry["id"],
            adjust_time_entry_payload(adjustment_minutes=0,
                                      version=entry["version"]),
            bundle["partner_headers"],
        ),
        200,
    )
    # Second adjust with original (stale) version.
    res = api.adjust_time_entry(
        entry["id"],
        adjust_time_entry_payload(adjustment_minutes=10,
                                  version=entry["version"]),
        bundle["partner_headers"],
    )
    validate_error(res, "ERR_VERSION_MISMATCH", expected_status=409)


# ---------------------------------------------------------------------------
# Race: two payment events on the same bill
# ---------------------------------------------------------------------------
def test_two_payment_events_one_wins_one_duplicate(api,
                                                   system_integrator_headers):
    """PRD §3.6: 'Two simultaneous payment events for the same bill
    serialize so that exactly one wins; the loser is rejected with
    ERR_PAYMENT_DUPLICATE.'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    bill_id = issued["id"]
    amount = issued["total_due_cents"]

    def _emit():
        return api.emit_payment(
            payment_event_payload(bill_id=bill_id, amount_cents=amount),
            system_integrator_headers,
        )

    results = run_race(_emit, _emit)
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    # PRD pins the loser's error_id explicitly:
    body = loser.json()
    assert body["data"]["error_id"] == "ERR_PAYMENT_DUPLICATE"


# ---------------------------------------------------------------------------
# Race: two custody events with the same occurred_at
# ---------------------------------------------------------------------------
def test_two_custody_events_same_occurred_at_one_loses(api):
    """PRD §3.5: 'Two lawyers who race to append a custody event with the
    same occurred_at will see the second rejected for the same reason;
    the rule serves both as a per-request validator and as the
    serialization point for concurrent appends.'

    Claim: exactly one append succeeds; the loser receives
    ERR_CUSTODY_CHAIN_BROKEN.
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(DEFAULT_NOW)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=DEFAULT_NOW,
        actor_headers=bundle["partner_headers"],
    )
    occurred = add_minutes(DEFAULT_NOW, 5)

    def _append():
        return api.append_custody_event(
            e["id"],
            create_custody_event_payload(
                actor_lawyer_id=bundle["partner"]["id"],
                action="EXAMINED",
                occurred_at=occurred,
            ),
            bundle["partner_headers"],
        )

    results = run_race(_append, _append)
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    body = loser.json()
    assert body["data"]["error_id"] == "ERR_CUSTODY_CHAIN_BROKEN"


# ---------------------------------------------------------------------------
# Race: two partner-signoffs on the same draft
# ---------------------------------------------------------------------------
def test_two_partner_signoff_one_wins_one_invalid_state(api):
    """PRD §3.3: 'Two simultaneous partner-signoff attempts on the same
    IN_REVIEW draft serialize so that exactly one wins; the loser observes
    the draft as no longer IN_REVIEW and is rejected with
    ERR_INVALID_STATE.'
    """
    bundle = setup_draft_in_review()
    # Drive senior pass so signoff is permissible.
    validate_success(
        api.senior_pass(bundle["draft"]["id"], bundle["senior_headers"]), 200
    )
    validate_success(
        api.submit_draft_for_review(bundle["draft"]["id"],
                                    bundle["junior_headers"]), 200
    )
    # Register a second partner so two non-drafter partners can race.
    from test_helpers import make_partner_lawyer
    partner2, partner2_headers = make_partner_lawyer(
        bootstrap_partner_headers=bundle["partner_headers"],
    )

    def _p1():
        return api.partner_signoff(
            bundle["draft"]["id"], bundle["partner_headers"]
        )

    def _p2():
        return api.partner_signoff(
            bundle["draft"]["id"], partner2_headers
        )

    results = run_race(_p1, _p2)
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    body = loser.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
