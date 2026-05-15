"""Cross-request races (PRD §2.11) — explicit serialization points with
PRD-named loser error_ids."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_settlement_payload,
    api_client,
    assert_exactly_one_succeeds,
    emit_customs_response,
    emit_customs_response_payload,
    make_filing_officer_headers,
    make_settlement_officer_headers,
    respond_query_payload,
    run_race,
    setup_declaration_in_pre_validated,
    setup_declaration_in_queried,
    setup_settlement_in_advanced,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §2.11 — Two filings on the same PRE_VALIDATED declaration
# ===========================================================================
class TestFilingRace:

    def test_two_filings_one_wins_with_explicit_loser_error(self, api):
        """PRD §2.11: "When two FilingOfficer operators simultaneously
        attempt to file the same PRE_VALIDATED declaration, the server
        serializes on Filing creation under the declaration: exactly one
        succeeds, and the loser receives ERR_FILING_ALREADY_EXISTS with
        HTTP 409."

        Claim: two concurrent /file calls → one 2xx, one 4xx whose
        error_id is ERR_FILING_ALREADY_EXISTS.
        """
        ctx = setup_declaration_in_pre_validated(reviewer_id="reviewer-race")
        dec = ctx["declaration"]
        # Use two DISTINCT filing officer ids (PRD §2.9 SoD: filer must
        # differ from pre-validate reviewer).
        h_a = make_filing_officer_headers("filer-a-race")
        h_b = make_filing_officer_headers("filer-b-race")
        # Omit `version` so PRD §2.5 optimistic-concurrency check is
        # skipped — otherwise the version-check (priority above state
        # and filing-creation per PRD §2.10) would short-circuit the
        # loser to ERR_VERSION_CONFLICT before the filing-creation
        # serialization point PRD §2.11 names. Both calls therefore
        # race to the filing-creation serialization point.
        op_a = lambda: api.file_declaration(
            dec["id"], action_with_version_payload(), h_a,
        )
        op_b = lambda: api.file_declaration(
            dec["id"], action_with_version_payload(), h_b,
        )
        results = run_race(op_a, op_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_FILING_ALREADY_EXISTS.value],
        )


# ===========================================================================
# §2.11 — RELEASE event vs respond-query race on the same filing
# ===========================================================================
class TestReleaseVsRespondQueryRace:

    def test_release_event_vs_respond_query(self, api, system_admin_headers):
        """PRD §2.11: "When a RELEASE customs response and a query-response
        action race for the same FILED/QUERIED filing, the server
        serializes on the filing's response_type field, and the loser
        is rejected with ERR_INVALID_STATE and HTTP 409 because the
        precondition on its target state no longer holds."

        Claim: concurrent CUSTOMS_RESPONSE=RELEASE (system) +
        /respond-query (FilingOfficer) on a QUERIED filing → one wins,
        loser receives ERR_INVALID_STATE.

        Setup: declaration in QUERIED. Note the RELEASE event needs the
        filing manifest to be MATCHED to succeed under V-FIL-MANIFEST.
        """
        # setup_declaration_in_queried() defaults to match_manifest=True,
        # so the filing already has manifest_match_status=MATCHED before
        # the QUERY response moved response_type to QUERY. The race below
        # is therefore PRD §2.11's "FILED/QUERIED filing" scenario with
        # all preconditions other than response_type already satisfied.
        ctx = setup_declaration_in_queried()
        dec = ctx["declaration"]
        filing = ctx["filing"]

        def op_release():
            return api.emit_event(
                emit_customs_response_payload(
                    filing_id=filing["id"], response_type="RELEASE",
                ),
                system_admin_headers,
            )

        def op_respond():
            return api.respond_query(
                dec["id"],
                respond_query_payload(response_note="ok",
                                      version=dec["version"]),
                TEST_USERS["filing_officer_headers"],
            )

        results = run_race(op_release, op_respond)
        # PRD §2.11 names ERR_INVALID_STATE as the loser-side error if
        # one of the two fails. But race ordering can produce both
        # succeeding (e.g., respond-query first → AWAITING → RELEASE
        # succeeds). The implementation-faithful invariant is: at least
        # one succeeds, and any failure must be ERR_INVALID_STATE.
        from test_helpers import assert_at_least_one_succeeds
        assert_at_least_one_succeeds(*results)
        for r in results:
            if r.status_code >= 400:
                validate_error_is_one_of(r, [
                    ApiErrorId.ERR_INVALID_STATE.value,
                ])


# ===========================================================================
# §2.11 — Two advances on the same FINAL settlement
# ===========================================================================
class TestAdvanceRace:

    def test_two_advances_one_wins_with_explicit_loser_error(self, api):
        """PRD §2.11: "When two SettlementOfficer operators concurrently
        attempt to advance the same FINAL settlement, the server
        serializes on advance_paid_at and the loser receives
        ERR_SETTLEMENT_ALREADY_ADVANCED with HTTP 409."

        Claim: two concurrent /advance calls → one 2xx, one 4xx whose
        error_id is ERR_SETTLEMENT_ALREADY_ADVANCED.
        """
        from test_helpers import (
            setup_declaration_released_via_emit,
        )
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        # Two distinct SettlementOfficer ids, both differing from filer.
        h_a = make_settlement_officer_headers("settle-a-race")
        h_b = make_settlement_officer_headers("settle-b-race")
        # Omit `version` (PRD §2.5 escape hatch) so both requests reach
        # the advance_paid_at serialization point PRD §2.11 specifies;
        # otherwise the version check (PRD §2.10 priority) would deliver
        # ERR_VERSION_CONFLICT instead of ERR_SETTLEMENT_ALREADY_ADVANCED.
        op_a = lambda: api.advance_settlement(
            s["id"], advance_settlement_payload(), h_a,
        )
        op_b = lambda: api.advance_settlement(
            s["id"], advance_settlement_payload(), h_b,
        )
        results = run_race(op_a, op_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [
            ApiErrorId.ERR_SETTLEMENT_ALREADY_ADVANCED.value,
        ])


# ===========================================================================
# §2.11 — Withdraw vs Advance race
# ===========================================================================
class TestWithdrawVsAdvanceRace:

    def test_withdraw_vs_advance(self, api):
        """PRD §2.11: "When declaration withdrawal races with settlement
        advance on the same declaration, the server serializes on the
        settlement's status field; if advance wins first, the subsequent
        withdrawal returns ERR_SETTLEMENT_HAS_ADVANCE with HTTP 409, and
        if withdrawal wins first, the subsequent advance returns
        ERR_INVALID_STATE with HTTP 409."

        Claim: concurrent /withdraw + /advance on a declaration with a
        FINAL settlement → exactly one succeeds; the loser receives one
        of the two PRD-named outcomes.

        Setup: declaration INSPECTING → PENALTY → FINAL settlement
        + REJECTED declaration with RejectionRecord (withdrawal-eligible).
        """
        from datetime import timedelta as _td
        from test_helpers import (
            advance_clock_to, locate_settlement_for_declaration,
            record_inspection_outcome, reset_clock_to_epoch,
            setup_inspection_case,
        )
        from test_helpers.fixtures import TEST_EPOCH
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY",
            declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is not None

        def op_withdraw():
            # Omit version (PRD §2.5 escape hatch) so the race reaches
            # the settlement.status serialization point PRD §2.11
            # names; otherwise the version check (PRD §2.10 priority)
            # would short-circuit the loser to ERR_VERSION_CONFLICT.
            return api.withdraw_declaration(
                dec["id"], action_with_version_payload(),
                TEST_USERS["broker_ops_headers"],
            )

        def op_advance():
            return api.advance_settlement(
                settlement["id"],
                advance_settlement_payload(),
                make_settlement_officer_headers("settle-race-a"),
            )

        results = run_race(op_withdraw, op_advance)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [
            ApiErrorId.ERR_SETTLEMENT_HAS_ADVANCE.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])
