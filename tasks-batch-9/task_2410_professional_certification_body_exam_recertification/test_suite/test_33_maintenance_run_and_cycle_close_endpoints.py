"""The sweep endpoint's dry run, commit and idempotent rerun, and the close endpoint's pair
of independent preconditions."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success


def _a_stale_seat_and_a_lapsing_eligibility(api):
    """One SCHEDULED seat on a session that has ended, and its APPROVED application, both
    left behind by a clock standing at 2027-08-02."""
    state = fx.pipeline_through_scheduled_seat(api)
    application = fx.read_application(api, state.application_id)
    assert application["status"] == "APPROVED"
    assert str(application["eligibility_expires_on"]).startswith("2027-08-01")
    assert application["attempts_consumed"] == 0
    session = fx.read_session(api, state.session_id)
    assert str(session["ends_at"]).startswith("2026-08-10T04:00:00")
    assert session["seats_reserved"] == 1

    fx.set_clock(api, "2027-08-02T00:00:00Z")
    return state


def _cycle_at_zero_credits(api):
    """A freshly minted credential whose first cycle has collected nothing."""
    state = fx.pipeline_through_certificant(api)
    cycle = fx.read_cycle(api, state.cycle_id)
    assert cycle["status"] == "OPEN"
    assert cycle["required_credits"] == 12
    assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
    return state


def _close(api, state, expected_certificant_version):
    return api.close_cycle(state.cycle_id,
                           f.close_cycle_payload(expected_certificant_version),
                           state.owner_headers)


class TestMaintenanceRunSweep:
    """Two steps in one call, a dry run that only looks, and a rerun that finds nothing."""

    def test_the_dry_run_names_both_rows_and_mutates_neither(self, api):
        """The report already lists the stale seat and the expired eligibility, yet the seat
        is still SCHEDULED, the application still APPROVED and the attempt still unconsumed.

        PRD §3.13: "When `dry_run` is true the run computes and reports exactly the same six
        lists while mutating nothing at all, which makes it safe to inspect before
        committing."

        PRD §3.13: "The run answers with a report object rather than an entity: `run_at`
        records the logical-clock instant of the run, and six identifier lists record what it
        touched — `no_show_registration_ids`, `expired_application_ids`, `lapsed_cycle_ids`,
        `expired_certificant_ids`, `reactivated_certificant_ids`, and `unbarred_candidate_ids`."

        Design: Corner/endpoints/recertification_run_sweeps_no_shows_and_expired_applications_then_reports_nothing_on_a_rerun
        """
        state = _a_stale_seat_and_a_lapsing_eligibility(api)

        report = fx.run_maintenance(api, dry_run=True)

        assert report["no_show_registration_ids"] == [state.registration_id]
        assert report["expired_application_ids"] == [state.application_id]
        ax.assert_maintenance_run_report(report)
        assert str(report["run_at"]).startswith("2027-08-02T00:00:00")

        assert fx.read_registration(api, state.registration_id)["seat_status"] == "SCHEDULED"
        application = fx.read_application(api, state.application_id)
        assert application["status"] == "APPROVED"
        assert application["attempts_consumed"] == 0
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 1

    def test_the_committed_run_frees_the_seat_burns_the_attempt_and_expires_the_eligibility(
            self, api):
        """One call does both steps: the seat becomes a NO_SHOW that releases capacity while
        still consuming an attempt, and the application expires — with the two credential
        lists empty because no certificant was ever minted.

        PRD §3.13: "**Step one — registrations.** Every registration whose `seat_status` is
        `SCHEDULED` and whose held session's `ends_at` the logical clock has passed moves to
        `NO_SHOW`. The seat is released, so the session's `seats_reserved` decreases by 1, and
        the attempt is nevertheless consumed: the owning application's `attempts_consumed`
        increases by 1 even though no score will ever exist."

        PRD §3.13: "**Step two — applications.** Every application whose `status` is
        `APPROVED` and whose `eligibility_expires_on` the logical clock has passed moves to
        `EXPIRED`."

        Design: Corner/endpoints/recertification_run_sweeps_no_shows_and_expired_applications_then_reports_nothing_on_a_rerun
        """
        state = _a_stale_seat_and_a_lapsing_eligibility(api)
        fx.run_maintenance(api, dry_run=True)

        report = fx.run_maintenance(api)

        assert report["no_show_registration_ids"] == [state.registration_id]
        assert report["expired_application_ids"] == [state.application_id]
        assert report["lapsed_cycle_ids"] == []
        assert report["expired_certificant_ids"] == []

        assert fx.read_registration(api, state.registration_id)["seat_status"] == "NO_SHOW"
        application = fx.read_application(api, state.application_id)
        assert application["status"] == "EXPIRED"
        assert application["attempts_consumed"] == 1
        session = fx.read_session(api, state.session_id)
        assert session["seats_reserved"] == 0
        ax.assert_seat_ledger_within_bounds(session)

    def test_the_immediate_rerun_reports_nothing_and_changes_nothing(self, api):
        """Each step considers only rows still in the state it acts on, so the second call
        finds no candidates and every swept row keeps exactly the value the first call left.

        PRD §3.13: "Because setting the logical clock is inert, every time-driven transition
        in this system is materialised by one idempotent operations checkpoint, triggered by a
        `ProgramAdmin`."

        PRD §3.13: "Because step three runs before step four and each step considers only rows
        in the state the earlier steps left behind, a cycle that lapses in step three is never
        also reactivated in step four of the same run."

        Design: Corner/endpoints/recertification_run_sweeps_no_shows_and_expired_applications_then_reports_nothing_on_a_rerun
        """
        state = _a_stale_seat_and_a_lapsing_eligibility(api)
        fx.run_maintenance(api)

        rerun = fx.run_maintenance(api)

        assert rerun["no_show_registration_ids"] == []
        assert rerun["expired_application_ids"] == []
        ax.assert_maintenance_run_report(rerun)

        assert fx.read_registration(api, state.registration_id)["seat_status"] == "NO_SHOW"
        application = fx.read_application(api, state.application_id)
        assert application["status"] == "EXPIRED"
        assert application["attempts_consumed"] == 1
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 0


class TestCycleClosePreconditions:
    """Credits first, then the concurrency token; only the call that satisfies both closes."""

    def test_an_unsatisfied_cycle_is_refused_even_with_a_current_version_token(self, api):
        """The token is the certificant's real version, so the sole objection is that nothing
        has been accrued, and the credential's expiry does not move.

        PRD §3.11: "Closing a satisfied cycle is available to the holder or to a
        `ProgramAdmin`, requires `expected_certificant_version` as described in §2.5, and
        demands both that the cycle's `status` be `SATISFIED` — otherwise
        `ERR_CREDITS_NOT_SATISFIED` — and that the owning certificant's `status` be `ACTIVE` —
        otherwise `ERR_CERTIFICANT_NOT_ACTIVE`."

        PRD §2.7: "39. **Credit sufficiency.** A cycle is closable only once its credits meet
        its requirement, or a passing re-examination is on file → otherwise
        `ERR_CREDITS_NOT_SATISFIED` (422)."

        Design: Corner/endpoints/cycle_close_is_refused_until_credits_are_satisfied_and_then_needs_the_current_certificant_version
        """
        state = _cycle_at_zero_credits(api)

        refused = _close(api, state, state.certificant_version)

        error = validate_error(refused, ApiErrorId.ERR_CREDITS_NOT_SATISFIED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value
        assert fx.read_cycle(api, state.cycle_id)["status"] == "OPEN"
        certificant = fx.read_certificant(api, state.certificant_id)
        assert str(certificant["valid_through"]).startswith("2027-08-10")
        assert certificant["version"] == state.certificant_version

    def test_a_satisfied_cycle_with_a_stale_token_is_refused_on_the_version(self, api):
        """Approving twelve credits carries the cycle to SATISFIED, and the close one version
        behind the certificant is refused without bumping anything.

        PRD §2.5: "Closing a recertification cycle — `POST /recertification-cycles/{id}/close`
        — requires `expected_certificant_version` carrying the client's last observed
        `version` of the owning `Certificant`. If the certificant's current `version` differs,
        the close is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        PRD §3.11: "A `CEU`-path cycle is `SATISFIED` exactly when its `credits_applied` is
        greater than or equal to its `required_credits`, with exact equality satisfying"

        Design: Corner/endpoints/cycle_close_is_refused_until_credits_are_satisfied_and_then_needs_the_current_certificant_version
        """
        state = _cycle_at_zero_credits(api)
        satisfied = fx.satisfied_cycle(api, state)
        assert float(satisfied["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert satisfied["status"] == "SATISFIED"
        current_version = fx.read_certificant(api, state.certificant_id)["version"]

        refused = _close(api, state, current_version - 1)

        error = validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert error["error_id"] != ApiErrorId.ERR_CREDITS_NOT_SATISFIED.value
        assert fx.read_cycle(api, state.cycle_id)["status"] == "SATISFIED"
        assert fx.read_certificant(api, state.certificant_id)["version"] == current_version

    def test_the_current_token_closes_the_cycle_and_opens_its_successor(self, api):
        """With both conditions met the cycle closes forfeiting its surplus, the credential's
        validity advances a year with a version bump, and a second cycle opens carrying
        nothing in.

        PRD §3.11: "**Hop one:** `carryover_credits_out` is computed. Take the surplus as
        `credits_applied` minus `required_credits`; if the cycle's `accrual_basis_snapshot` is
        `STRICT_CYCLE`, or the surplus is zero or negative, then `carryover_credits_out` is
        0.00"

        PRD §3.11: "**Hop three:** because `valid_through` advanced, a successor cycle is
        opened with `cycle_number` one greater than the closing cycle's, `starts_on` equal to
        the closing cycle's `ends_on`, `carryover_credits_in` equal to the closing cycle's
        `carryover_credits_out`, and `required_credits` and `accrual_basis_snapshot` freshly
        re-pinned from the program as it stands now; the certificant's `current_cycle_id` is
        repointed at the successor."

        Design: Corner/endpoints/cycle_close_is_refused_until_credits_are_satisfied_and_then_needs_the_current_certificant_version
        """
        state = _cycle_at_zero_credits(api)
        fx.satisfied_cycle(api, state)
        current_version = fx.read_certificant(api, state.certificant_id)["version"]
        _close(api, state, current_version - 1)

        closed = validate_success(_close(api, state, current_version), 200)

        assert closed["status"] == "CLOSED"
        assert float(closed["carryover_credits_out"]) == pytest.approx(0.00, abs=0.01)

        certificant = fx.read_certificant(api, state.certificant_id)
        assert str(certificant["valid_through"]).startswith("2028-08-10")
        assert certificant["version"] == current_version + 1
        assert certificant["current_cycle_id"] != state.cycle_id

        rows, meta = validate_paginated(api.list_certificant_recertification_cycles(
            state.certificant_id, fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 2
        successor = [row for row in rows if row["id"] != state.cycle_id][0]
        assert successor["id"] == certificant["current_cycle_id"]
        assert successor["status"] == "OPEN"
        assert successor["cycle_number"] == 2
        assert successor["required_credits"] == 12
        assert float(successor["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)
        ax.assert_recertification_cycle(successor)
