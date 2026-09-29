"""The two long cascades: acceptance and monitoring-visit completion.

Each one walks several entity hops away from the endpoint that was called, and
the far end of the walk touches a row the caller never named.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    CLOCK_2026_10_12,
    TEST_USERS,
    accept_as_landowner,
    api_client,
    assert_source_ledger_conserved,
    commitment_on,
    commitments_of,
    complete_visit,
    draft_amendment,
    list_negotiation_log,
    list_requirements,
    read_amendment,
    read_application,
    read_easement,
    read_source,
    schedule_visit,
    set_clock,
    setup_recorded_easement,
    setup_two_applications_competing_for_headroom,
    submit_amendment,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _competing_pair_after_first_acceptance() -> dict:
    """Accept the first of two plans reserved against the same LOCAL headroom.

    The LOCAL appropriation carries a `fully_obligated_threshold_pct` of 0.50, so
    the first obligation of 56,127,723 cents crosses the 30,000,000 obligation
    floor and drives the source out of `ACTIVE`.
    """
    scenario = setup_two_applications_competing_for_headroom(local_threshold_pct=0.50)
    set_clock(CLOCK_2026_10_12)
    scenario["accepted_a"] = accept_as_landowner(
        scenario["application_a"]["id"], scenario["landowner_a"]["id"]
    )
    return scenario


class TestAcceptanceCascade:
    """Acceptance walks from the application out to a competitor's plan."""

    def test_acceptance_obligates_the_plan_and_logs_the_agreed_price(self):
        """Levels one and two: the application and its own commitments.

        PRD §3.7: "An `ACCEPTANCE` entry is appended to the negotiation log
        carrying the agreed price as its `amount_cents`, and the application
        moves to `ACCEPTED`. Every funding commitment on the application in
        `RESERVED` flips `RESERVED → OBLIGATED`, and `funding_plan_status` moves
        `FUNDED → OBLIGATED`."

        Design: Difficulty/transitive_cascade/acceptance_cascades_six_levels_and_lapses_a_sibling_reservation
        """
        scenario = _competing_pair_after_first_acceptance()
        accepted = scenario["accepted_a"]
        assert accepted["status"] == "ACCEPTED"
        assert accepted["agreed_price_cents"] == 175_550_000
        assert accepted["funding_plan_status"] == "OBLIGATED"

        entries = list_negotiation_log(accepted["id"], {"limit": 100})
        assert entries[-1]["kind"] == "ACCEPTANCE"
        assert entries[-1]["amount_cents"] == 175_550_000

        commitments = commitments_of(accepted["id"])
        assert len(commitments) == 3
        assert {row["status"] for row in commitments} == {"OBLIGATED"}

    def test_acceptance_recomputes_the_source_ledgers_and_flips_local_out_of_active(
        self,
    ):
        """Levels three and four: the parent sources and their obligation floor.

        PRD §3.7: "Each parent source has `committed_cents`, `reserved_cents` and
        `available_cents` recomputed and its `version` incremented. Any source
        whose `committed_cents` has now reached the floor of `authorized_cents`
        times `fully_obligated_threshold_pct` flips `ACTIVE → FULLY_OBLIGATED`;
        that flip lapses every remaining `RESERVED` commitment held against that
        source by *other* applications, with `lapse_reason`
        `SOURCE_FULLY_OBLIGATED`; and each of those other applications
        consequently flips `FUNDED → UNDERFUNDED` with its own `version`
        incremented."

        Design: Difficulty/transitive_cascade/acceptance_cascades_six_levels_and_lapses_a_sibling_reservation
        """
        scenario = _competing_pair_after_first_acceptance()
        sources = scenario["sources"]

        local = read_source(sources["local"]["id"])
        assert local["committed_cents"] == 56_127_723
        assert local["available_cents"] == 3_872_277
        # floor(60,000,000 x 0.50) is 30,000,000, which 56,127,723 has passed.
        assert local["status"] == "FULLY_OBLIGATED"
        assert local["version"] > sources["local"]["version"]
        assert_source_ledger_conserved(local)

        state = read_source(sources["state"]["id"])
        federal = read_source(sources["federal"]["id"])
        assert state["committed_cents"] == 64_145_970
        assert state["available_cents"] == 55_854_030
        assert federal["committed_cents"] == 40_091_232
        assert federal["available_cents"] == 159_908_768
        # Their own obligation floors sit far above what one plan obligates.
        assert state["status"] == "ACTIVE"
        assert federal["status"] == "ACTIVE"
        assert_source_ledger_conserved(state)
        assert_source_ledger_conserved(federal)

    def test_the_flip_lapses_the_competitors_reservation_and_underfunds_its_plan(self):
        """Levels five and six: a row the accepting caller never named.

        PRD §3.7: "that flip lapses every remaining `RESERVED` commitment held
        against that source by *other* applications, with `lapse_reason`
        `SOURCE_FULLY_OBLIGATED`; and each of those other applications
        consequently flips `FUNDED → UNDERFUNDED` with its own `version`
        incremented."

        Design: Difficulty/transitive_cascade/acceptance_cascades_six_levels_and_lapses_a_sibling_reservation
        """
        scenario = _competing_pair_after_first_acceptance()
        sibling = scenario["application_b"]
        sources = scenario["sources"]

        lapsed = commitment_on(sibling["id"], sources["local"]["id"])
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_reason"] == "SOURCE_FULLY_OBLIGATED"

        # Only the commitment against the newly obligated source is touched.
        for key in ("state", "federal"):
            untouched = commitment_on(sibling["id"], sources[key]["id"])
            assert untouched["status"] == "RESERVED"
            assert untouched["lapse_reason"] is None

        after = read_application(sibling["id"])
        assert after["funding_plan_status"] == "UNDERFUNDED"
        assert after["version"] > sibling["version"]
        # The sibling's own acquisition status is untouched by another
        # application's acceptance.
        assert after["status"] == "OFFER_ISSUED"

    def test_acceptance_opens_the_pre_closing_file(self):
        """The same call also creates the closing requirements.

        PRD §3.7: "Two closing requirements are always created — one of
        `requirement_type` `TITLE_COMMITMENT` and one of `BOUNDARY_SURVEY` —
        plus a third of `MORTGAGE_SUBORDINATION` if and only if the parcel's
        `mortgage_lienholder_name` is non-null, in which case that lienholder's
        name is copied onto the requirement as `lienholder_name`."

        Design: Difficulty/transitive_cascade/acceptance_cascades_six_levels_and_lapses_a_sibling_reservation
        """
        scenario = _competing_pair_after_first_acceptance()
        accepted = scenario["accepted_a"]
        assert accepted["closing_status"] == "PENDING_REQUIREMENTS"
        assert accepted["requirement_total"] == 3
        assert accepted["requirement_satisfied_count"] == 0

        by_type = {
            row["requirement_type"]: row
            for row in list_requirements(accepted["id"], {"limit": 100})
        }
        assert set(by_type) == {
            "TITLE_COMMITMENT",
            "BOUNDARY_SURVEY",
            "MORTGAGE_SUBORDINATION",
        }
        assert {row["status"] for row in by_type.values()} == {"OUTSTANDING"}
        assert (
            by_type["MORTGAGE_SUBORDINATION"]["lienholder_name"]
            == scenario["parcel_a"]["mortgage_lienholder_name"]
        )


def _visit_completion_over_a_pending_amendment() -> dict:
    """Complete an over-allowance visit on an easement with an amendment in review.

    The easement is recorded on 2026-12-15 with an impervious allowance of
    139,392 square feet. The amendment is submitted while the easement is still
    `COMPLIANT`, then the clock moves to 2027-06-03 for the visit.
    """
    scenario = setup_recorded_easement()
    easement_id = scenario["easement"]["id"]
    amendment = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
    scenario["amendment"] = submit_amendment(amendment["id"])
    assert scenario["amendment"]["status"] == "UNDER_REVIEW"

    set_clock("2027-06-03T00:00:00Z")
    scenario["visit"] = schedule_visit(
        easement_id,
        window_start="2027-06-03T00:00:00Z",
        window_end="2027-06-10T00:00:00Z",
    )
    scenario["completed_visit"] = complete_visit(scenario["visit"]["id"], 142_000)
    return scenario


class TestVisitCompletionCascade:
    """Completing one visit reaches a violation, the easement and an amendment."""

    def test_the_completion_opens_a_violation_attributed_to_the_visit(self):
        """Levels one and two: the visit itself and the violation it spawns.

        PRD §3.8: "On a `CONFIRMED_VIOLATION`, completion opens a violation
        automatically: a `Violation` is created against the easement, attributed
        to this visit through `monitoring_visit_id`, with `violation_type`
        `IMPERVIOUS_EXCEEDANCE`, with `excess_sqft` equal to the observed
        coverage less the allowance, and with `status` `OPEN`."

        Design: Difficulty/transitive_cascade/visit_completion_cascades_five_levels_and_suspends_a_pending_amendment
        """
        scenario = _visit_completion_over_a_pending_amendment()
        visit = scenario["completed_visit"]
        assert visit["status"] == "COMPLETED"
        assert visit["observed_impervious_sqft"] == 142_000
        assert visit["finding"] == "CONFIRMED_VIOLATION"
        assert visit["completed_at"].startswith("2027-06-03")

        spawned = get_success_data(
            api_client.list_visit_violations(visit["id"], ADMIN, {"limit": 100})
        )
        assert len(spawned) == 1
        violation = spawned[0]
        assert violation["monitoring_visit_id"] == visit["id"]
        assert violation["easement_id"] == scenario["easement"]["id"]
        assert violation["violation_type"] == "IMPERVIOUS_EXCEEDANCE"
        # 142,000 observed against a 139,392 allowance.
        assert violation["excess_sqft"] == 2_608
        assert violation["status"] == "OPEN"
        # 2,608 is strictly above 2,000, so the 90-day MAJOR clock applies.
        assert violation["severity"] == "MAJOR"
        assert violation["opened_on"].startswith("2027-06-03")
        assert violation["cure_deadline_on"].startswith("2027-09-01")

    def test_the_violation_flips_compliance_and_raises_the_stewardship_hold(self):
        """Levels three and four: the easement's compliance dimension.

        PRD §3.8: "That in turn flips the easement's `compliance_status`
        `COMPLIANT → VIOLATION_OPEN`, sets `stewardship_hold` to true, and
        recomputes `open_violation_count`; and because the hold is now on, every
        amendment on that easement in `UNDER_REVIEW` flips
        `UNDER_REVIEW → SUSPENDED` with `suspended_reason` `VIOLATION_OPEN` and
        `pending_amendment_count` is recomputed downward."

        Design: Difficulty/transitive_cascade/visit_completion_cascades_five_levels_and_suspends_a_pending_amendment
        """
        scenario = _visit_completion_over_a_pending_amendment()
        easement = read_easement(scenario["easement"]["id"])
        assert easement["compliance_status"] == "VIOLATION_OPEN"
        assert easement["stewardship_hold"] is True
        assert easement["open_violation_count"] == 1
        assert easement["version"] > scenario["easement"]["version"]

        # The monitoring dimension is still re-anchored on the completion.
        assert easement["last_monitored_on"].startswith("2027-06-03")
        # 2027-06-03 advanced by the 365-day interval across a leap February.
        assert easement["next_monitoring_due_on"].startswith("2028-06-02")
        assert easement["stewardship_status"] == "MONITORING_CURRENT"
        # The deed dimension is untouched.
        assert easement["status"] == "RECORDED"
        assert easement["impervious_allowance_sqft"] == 139_392

    def test_the_hold_suspends_the_amendment_that_was_under_review(self):
        """Level five: an amendment the completing monitor never named.

        PRD §3.8: "and because the hold is now on, every amendment on that
        easement in `UNDER_REVIEW` flips `UNDER_REVIEW → SUSPENDED` with
        `suspended_reason` `VIOLATION_OPEN` and `pending_amendment_count` is
        recomputed downward."

        Design: Difficulty/transitive_cascade/visit_completion_cascades_five_levels_and_suspends_a_pending_amendment
        """
        scenario = _visit_completion_over_a_pending_amendment()
        amendment = read_amendment(scenario["amendment"]["id"])
        assert amendment["status"] == "SUSPENDED"
        assert amendment["suspended_reason"] == "VIOLATION_OPEN"
        assert amendment["version"] > scenario["amendment"]["version"]

        easement = read_easement(scenario["easement"]["id"])
        assert easement["pending_amendment_count"] == 0
        assert easement["amendment_count"] == 0

    def test_an_observation_at_the_allowance_runs_none_of_the_cascade(self):
        """The comparison is strict, so the cascade has an exact off switch.

        PRD §3.8: "An observation exactly equal to the allowance is compliant;
        using a non-strict comparison here is the off-by-one wrong variant."

        Design: Difficulty/transitive_cascade/visit_completion_cascades_five_levels_and_suspends_a_pending_amendment
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        amendment = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        submitted = submit_amendment(amendment["id"])

        set_clock("2027-06-03T00:00:00Z")
        visit = schedule_visit(
            easement_id,
            window_start="2027-06-03T00:00:00Z",
            window_end="2027-06-10T00:00:00Z",
        )
        completed = complete_visit(visit["id"], 139_392)
        assert completed["finding"] == "NO_ISSUE"
        assert (
            get_success_data(
                api_client.list_visit_violations(visit["id"], ADMIN, {"limit": 100})
            )
            == []
        )

        easement = read_easement(easement_id)
        assert easement["compliance_status"] == "COMPLIANT"
        assert easement["stewardship_hold"] is False
        assert easement["open_violation_count"] == 0
        assert easement["pending_amendment_count"] == 1
        assert read_amendment(submitted["id"])["status"] == "UNDER_REVIEW"
        # The stewardship reset still happens on a clean visit.
        assert easement["last_monitored_on"].startswith("2027-06-03")
        assert easement["protected_acres"] == pytest.approx(160.00, abs=0.01)
