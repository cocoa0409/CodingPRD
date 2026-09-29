"""Protest filing gates and the re-scoping cycle.

PRD §3.6: "This closes the cycle `SUBMITTED → PROTEST_PERIOD → UNDER_PROTEST →
REVISION_REQUESTED → SUBMITTED`, which may run at most twice."
"""
import pytest
from test_helpers import (
    assert_same_instant,
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    ANALYST,
    HEARING_OFFICER,
    create_protest_payload,
    make_claimant_headers,
    publish_application,
    read_application,
    read_right,
    resubmit_application,
    set_clock,
    setup_protested_application,
)


class TestRevisionCycleHoldsEscrowAndShortensTheWindow:
    """PRD §3.6 / §3.4 — one full pass around the revision loop.

    A 60.00 AF application is published on 2026-03-01, drawing a 30-day window,
    protested on 2026-03-05, sent back for re-scoping, resubmitted on 2026-03-10
    at 100.00 AF and republished.
    """

    def _under_protest(self):
        return setup_protested_application(
            requested_af=60.00, claimed_injury_af=12.00
        )

    def test_revision_request_freezes_the_escrow_and_clears_the_deadline(self):
        """PRD §3.6: "The application moves `UNDER_PROTEST → REVISION_REQUESTED`
        and `protest_deadline` is cleared to null so the republished application
        receives a fresh, shorter window."

        PRD §3.6: "Two things deliberately do not happen: the escrow is not
        released — it stays in place across the revision and is swapped
        atomically on resubmission, so no ledger bucket on the right moves and the
        right's `version` is not bumped — and the outstanding protests are held
        exactly where they are, so `unresolved_protest_count` does not move
        either."

        Design: Difficulty/non_linear_state_machine/transfer_application_revision_cycle
        """
        bundle = self._under_protest()
        assert bundle["application"]["status"] == "UNDER_PROTEST"
        assert_same_instant(bundle["application"]["protest_deadline"], "2026-03-31T00:00:00Z", "protest_deadline")

        application = get_success_data(
            api_client.request_revision(
                bundle["application"]["id"],
                "Re-scope the requested volume and re-notice.",
                HEARING_OFFICER,
            )
        )

        assert application["status"] == "REVISION_REQUESTED"
        assert application["protest_deadline"] is None
        assert application["escrowed_af"] == pytest.approx(60.00, abs=0.01)
        assert application["revision_round"] == 0, (
            "the round counter advances on resubmission, not on the request"
        )
        assert application["unresolved_protest_count"] == 1
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(60.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(135.00, abs=0.01)
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "FILED"

    def test_resubmission_swaps_the_escrow_and_recomputes_the_analysis(self):
        """PRD §3.4: "the new `requested_af` must be no greater than the right's
        `transferable_af` plus the application's existing `escrowed_af`, because
        the existing escrow is being exchanged rather than double-counted."

        135.00 still transferable plus the 60.00 already escrowed admits the new
        100.00 AF request. PRD §3.4: "the right's `encumbered_af` first decreases
        by the old escrow and then increases by the new requested volume" — 100.00
        encumbered against 95.00 transferable — and the analysis is recomputed, so
        `gross_depletion_af` moves to 100.00 * 0.78 = 78.00.

        Design: Difficulty/non_linear_state_machine/transfer_application_revision_cycle
        """
        bundle = self._under_protest()
        get_success_data(
            api_client.request_revision(
                bundle["application"]["id"], "Re-scope and re-notice.", HEARING_OFFICER
            )
        )
        set_clock("2026-03-10T00:00:00Z")

        application = resubmit_application(
            bundle["application"]["id"], bundle["right"]["id"], 100.00
        )

        assert application["status"] == "SUBMITTED"
        assert application["revision_round"] == 1
        assert application["requested_af"] == pytest.approx(100.00, abs=0.01)
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(78.00, abs=0.01)

    def test_republication_after_a_revision_grants_a_fifteen_day_window(self):
        """PRD §3.5: "`protest_deadline` is stamped from the logical clock at
        thirty days out on a first publication, when `revision_round` is 0, and at
        fifteen days out on every republication after a revision, when
        `revision_round` is 1 or more — a revised application gets a materially
        shorter window because the basin has already had its first look."

        Republished from a clock of 2026-03-10 with `revision_round` at 1, the new
        deadline lands on 2026-03-25, not on 2026-04-09. The protest held across
        the revision is still outstanding.

        Design: Difficulty/non_linear_state_machine/transfer_application_revision_cycle
        """
        bundle = self._under_protest()
        get_success_data(
            api_client.request_revision(
                bundle["application"]["id"], "Re-scope and re-notice.", HEARING_OFFICER
            )
        )
        set_clock("2026-03-10T00:00:00Z")
        resubmit_application(bundle["application"]["id"], bundle["right"]["id"], 100.00)

        application = publish_application(bundle["application"]["id"])

        assert application["status"] == "PROTEST_PERIOD"
        assert_same_instant(application["protest_deadline"], "2026-03-25T00:00:00Z", "protest_deadline")
        assert application["revision_round"] == 1
        assert application["unresolved_protest_count"] == 1
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "FILED"


class TestProtestWindowGateOutranksTheDuplicateGate:
    """PRD §3.6 — "Three further gates guard the filing, and their relative order
    is what decides ambiguous cases."

    The same protestant that already holds a `FILED` protest tries to file a
    second one twice: once one second before the deadline and once at the deadline
    instant itself.
    """

    def _protested(self):
        return setup_protested_application(
            requested_af=60.00, claimed_injury_af=12.00
        )

    def _refile(self, bundle):
        return api_client.create_protest(
            create_protest_payload(
                bundle["application"]["id"], bundle["protestant"]["id"], 12.00
            ),
            make_claimant_headers(bundle["protestant"]["id"]),
        )

    def test_duplicate_protest_is_reported_while_the_window_is_still_open(self):
        """PRD §3.6: "And no existing protest on the application may already carry
        the same `protestant_claimant_id`, regardless of that earlier protest's
        status, with a repeat being `ERR_DUPLICATE_PROTEST` (HTTP 409)."

        At 2026-03-30T23:59:59Z the clock is still strictly before the
        2026-03-31T00:00:00Z deadline, so only the duplicate rule is broken and
        that is the error returned.

        Design: Difficulty/priority_pair_validation_conflict/protest_deadline_beats_duplicate_protest
        """
        bundle = self._protested()
        set_clock("2026-03-30T23:59:59Z")

        response = self._refile(bundle)

        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_PROTEST.value, expected_status=409
        )
        assert read_application(bundle["application"]["id"])[
            "unresolved_protest_count"
        ] == 1

    def test_closed_window_is_reported_ahead_of_the_duplicate(self):
        """PRD §3.6: "The temporal gate outranks the duplicate gate: a protestant
        who files a second protest *after* the deadline has passed breaks both
        rules at once and receives the window error, not the duplicate error."

        PRD §3.6: "filing at exactly the deadline instant is late and yields
        `ERR_PROTEST_WINDOW_CLOSED` (HTTP 422)." The clock is set to exactly
        2026-03-31T00:00:00Z, so both rules are broken and the window rule wins.
        No second protest row is created either way.

        Design: Difficulty/priority_pair_validation_conflict/protest_deadline_beats_duplicate_protest
        """
        bundle = self._protested()
        set_clock("2026-03-31T00:00:00Z")

        response = self._refile(bundle)

        validate_error(
            response, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value, expected_status=422
        )
        listed, _meta = validate_paginated(
            api_client.list_protests(
                ANALYST, params={"transfer_application_id": bundle["application"]["id"]}
            )
        )
        assert len(listed) == 1, (
            "the refused filing must leave exactly the one original protest"
        )
        assert listed[0]["id"] == bundle["protest"]["id"]
        assert read_application(bundle["application"]["id"])[
            "unresolved_protest_count"
        ] == 1
