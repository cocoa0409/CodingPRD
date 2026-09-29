"""A for-cause termination fans out rather than running in a line.

One call releases the territory, re-parents custody of every in-flight file to
the nominated successor while writing one transition record each, forfeits the
accrued commission because the reason is for cause, rebuilds the agency balance
from what survives, and debars the agency.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, one_entry


@pytest.fixture()
def terminable_partner_pair(client):
    """A partner with money and files in flight, plus an eligible successor."""
    partner = fx.build_active_partner(client)

    successor = fx.register_agency(
        client,
        legal_name="Global Pathways Partners",
        home_country_code="IN",
        beneficial_owner_count=1,
        reference_check_count=2,
    )
    fx.clear_agency(client, successor["id"])
    successor_contract = fx.draft_contract(
        client,
        successor["id"],
        contract_ref="CTR-2026-002",
        exclusivity_model=C.EXCLUSIVITY_NON_EXCLUSIVE_ONLY,
        annual_commission_cap_cents=4000000,
    )
    fx.append_schedule(
        client,
        successor_contract["id"],
        successor_contract["version"],
        deposit_rate_bps=350,
        enrollment_rate_bps=450,
        census_rate_bps=200,
        persistence_rate_bps=100,
        clawback_window_days=90,
    )
    fx.activate_contract(client, successor["id"], successor_contract["id"])

    deposited = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-1001",
        passport_hash="hash-passport-1001",
        applicant_user_id="applicant-1001",
    )
    fx.submit_application(client, partner["agency_id"], deposited["application_id"])
    admitted = fx.admit_application(client, deposited["application_id"])

    untouched_draft = fx.create_application(
        client,
        partner["agency_id"],
        partner["program_id"],
        student_ref="STU-1002",
        student_residence_country="IN",
    )
    fx.issue_disclosure(client, partner["agency_id"], untouched_draft["id"])

    fx.set_clock(client, "2026-09-05T00:00:00Z")
    fx.register_milestone(
        client,
        deposited["application_id"],
        C.MILESTONE_DEPOSIT_PAID,
        "2026-09-05",
        admitted["version"],
    )

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "contract_id": partner["contract_id"],
        "assignment_id": partner["territory_id"],
        "successor_id": successor["id"],
        "successor_contract_id": successor_contract["id"],
        "deposited_application_id": deposited["application_id"],
        "draft_application_id": untouched_draft["id"],
    }


@pytest.fixture()
def terminated_for_cause(client, terminable_partner_pair):
    """Fire the for-cause termination that opens the four-hop cascade."""
    fx.terminate_contract(
        client,
        terminable_partner_pair["contract_id"],
        C.TERMINATION_FOR_CAUSE,
        "2026-09-05",
        "Confirmed prohibited claims in three markets",
        successor_agency_id=terminable_partner_pair["successor_id"],
    )
    return terminable_partner_pair


class TestTerminationTransitionCascade:
    def test_termination_stamps_the_reason_and_releases_the_territory(
        self, client, terminated_for_cause
    ):
        """Hop one, and the stamps the request itself carries.

        "The `effective_date` is stamped into `terminated_on` and the reason into
        `termination_reason_code`."

        "Every territory assignment on the contract still in `ACTIVE` is
        `RELEASED`."

        Design: Difficulty/transitive_cascade/contract_termination_for_cause_file_transition_cascade
        """
        env = terminated_for_cause

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_TERMINATED
        assert contract["termination_reason_code"] == C.TERMINATION_FOR_CAUSE
        assert contract["terminated_on"] == "2026-09-05"

        assignments = fx.read_assignments(client, env["contract_id"])
        released = [a for a in assignments if a["id"] == env["assignment_id"]]
        assert len(released) == 1, f"expected the one assignment, got {assignments!r}"
        assert released[0]["status"] == C.ASSIGNMENT_RELEASED
        assert released[0]["released_on"] == "2026-09-05"

    def test_each_in_flight_file_is_re_parented_with_its_own_transition_record(
        self, client, terminated_for_cause
    ):
        """Hop two: custody moves, the recruiting agency of record does not.

        "Every application whose `custody_agency_id` is the terminated contract's
        agency and whose `status` is `DRAFT`, `SUBMITTED`, `ADMITTED` or
        `DEPOSIT_PAID` has its `custody_agency_id` reassigned to
        `successor_agency_id`, or to null when the field was omitted, has its
        `disclosure_state` driven to `INVALIDATED`, and gets one file-transition
        record appended."

        "the `application_status_at_transition` observed at the moment of the
        move, and `disclosure_reset`, which is always true because the transition
        necessarily invalidates the prior agent-relationship disclosure"

        Design: Difficulty/transitive_cascade/contract_termination_for_cause_file_transition_cascade
        """
        env = terminated_for_cause

        transitions = fx.read_transitions(client, trigger_contract_id=env["contract_id"])
        assert len(transitions) == 2, (
            f"one record per in-flight file was expected, got {transitions!r}"
        )
        for record in transitions:
            assert record["from_agency_id"] == env["agency_id"]
            assert record["to_agency_id"] == env["successor_id"]
            assert (
                record["reason_code"] == C.TRANSITION_REASON_TERMINATION_FOR_CAUSE
            )
            assert record["disclosure_reset"] is True

        by_application = {r["application_id"]: r for r in transitions}
        assert (
            by_application[env["deposited_application_id"]][
                "application_status_at_transition"
            ]
            == C.APPLICATION_DEPOSIT_PAID
        )
        assert (
            by_application[env["draft_application_id"]][
                "application_status_at_transition"
            ]
            == C.APPLICATION_DRAFT
        )

        deposited = fx.read_application(client, env["deposited_application_id"])
        assert deposited["custody_agency_id"] == env["successor_id"]
        assert deposited["agency_id"] == env["agency_id"]
        assert deposited["status"] == C.APPLICATION_DEPOSIT_PAID
        assert deposited["disclosure_state"] == C.DISCLOSURE_INVALIDATED

        draft = fx.read_application(client, env["draft_application_id"])
        assert draft["custody_agency_id"] == env["successor_id"]
        assert draft["disclosure_state"] == C.DISCLOSURE_INVALIDATED

    def test_for_cause_forfeits_every_candidate_and_the_balance_falls_to_zero(
        self, client, terminated_for_cause
    ):
        """Hops three and four: nothing vests, and the balance is rebuilt.

        "If the `reason_code` is `FOR_CAUSE`, every candidate is forfeited —
        nothing vests when the university terminates for cause."

        "Each forfeiture records a `void_reason` formed by prefixing the reason
        code with `TERMINATION_`"

        "The agency's `net_earned_commission_cents` is recomputed in full from
        the surviving rows."

        Design: Difficulty/transitive_cascade/contract_termination_for_cause_file_transition_cascade
        """
        env = terminated_for_cause

        entries = fx.read_entries(
            client, application_id=env["deposited_application_id"]
        )
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert entry["state"] == C.ENTRY_FORFEITED
        assert entry["void_reason"] == C.TRANSITION_REASON_TERMINATION_FOR_CAUSE
        assert_cents(entry["amount_cents"], 113828, "amount_cents")

        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"], 0, "net_earned_commission_cents"
        )
        assert_cents(agency["clawback_liability_cents"], 0, "clawback_liability_cents")

    def test_for_cause_debars_the_agency_and_spares_the_successor(
        self, client, terminated_for_cause
    ):
        """The extra consequence, and the limit of its reach.

        "When the `reason_code` is `FOR_CAUSE`, one further consequence follows:
        the agency's `compliance_posture` moves to `DEBARRED`, which itself
        suspends that agency's other contracts in `ACTIVE` as described in §3.8."

        "A nominated successor is vetted before anything moves.
        `successor_agency_id`, when provided, must name a *different* agency,
        whose `vetting_state` is `CLEARED`, whose `compliance_posture` is
        `GOOD_STANDING` or `WATCH`, and which holds at least one contract in
        `ACTIVE`."

        Design: Difficulty/transitive_cascade/contract_termination_for_cause_file_transition_cascade
        """
        env = terminated_for_cause

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["compliance_posture"] == C.POSTURE_DEBARRED
        assert agency["vetting_state"] == C.VETTING_CLEARED

        successor_contract = fx.read_contract(client, env["successor_contract_id"])
        assert successor_contract["status"] == C.CONTRACT_ACTIVE
        successor = fx.read_agency(client, env["successor_id"])
        assert successor["compliance_posture"] == C.POSTURE_GOOD_STANDING
