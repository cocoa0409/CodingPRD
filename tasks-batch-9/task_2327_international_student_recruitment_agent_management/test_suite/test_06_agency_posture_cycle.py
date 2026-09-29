"""De-escalation is not a return trip.

An agency in good standing is placed on probation by hand, which suspends its
active contract and tears down that contract's territory and draft disclosures.
Reinstating the agency lands it on the intermediate standing rather than back
where it started, and none of the cascade damage is undone.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_occupancy


@pytest.fixture()
def probated_partner(client):
    """An agency driven from good standing straight to probation."""
    agency = fx.register_agency(
        client,
        legal_name="Sunrise Education Consultants",
        home_country_code="IN",
    )
    fx.clear_agency(client, agency["id"])
    program = fx.create_program(client)
    contract = fx.draft_contract(client, agency["id"])
    fx.append_schedule(client, contract["id"], contract["version"])
    territory = fx.assign_territory(client, contract["id"])
    fx.activate_contract(client, agency["id"], contract["id"])

    application = fx.create_application(
        client,
        agency["id"],
        program["id"],
        student_ref="STU-1001",
        student_residence_country="IN",
    )
    fx.issue_and_acknowledge_disclosure(
        client, agency["id"], application["id"], "applicant-1001"
    )

    fx.posture_action(
        client,
        agency["id"],
        C.POSTURE_PLACE_ON_PROBATION,
        "Pattern of misdirected student payments under review",
    )

    return {
        "agency_id": agency["id"],
        "contract_id": contract["id"],
        "assignment_id": territory["id"],
        "application_id": application["id"],
    }


class TestAgencyPostureCycle:
    def test_reinstatement_lands_on_watch_and_leaves_the_other_dimension_alone(
        self, client, probated_partner
    ):
        """The de-escalation stops one step short of good standing.

        "`REINSTATE` is the de-escalation and it lands on `WATCH`, never on
        `GOOD_STANDING`: from `PROBATION` or from `SUSPENDED` the agency returns
        to `WATCH`, and only when `rolling_risk_score` is strictly below 65.00."

        "The two run independently: every combination of the two dimensions is
        reachable except that neither terminal can be left."

        Design: Difficulty/non_linear_state_machine/agency_posture_probation_reinstate_lands_on_watch
        """
        env = probated_partner

        fx.posture_action(
            client,
            env["agency_id"],
            C.POSTURE_REINSTATE,
            "Investigation closed without adverse finding",
        )

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["compliance_posture"] == C.POSTURE_WATCH, (
            "reinstatement must not restore GOOD_STANDING"
        )
        assert agency["vetting_state"] == C.VETTING_CLEARED
        assert agency["last_posture_reason"] == (
            "Investigation closed without adverse finding"
        )

    def test_reinstating_the_agency_does_not_unwind_the_probation_cascade(
        self, client, probated_partner
    ):
        """Contract, territory and disclosure all stay where probation left them.

        "the probation transition suspends every contract of that agency that is
        in `ACTIVE`, recording `POSTURE_PROBATION` as each contract's
        `suspension_reason`, which in turn releases those contracts' active
        territories and invalidates their `DRAFT` applications' disclosures"

        "Reinstatement restores the contract only — territory assignments
        released by the suspension are gone for good and must be re-created if
        the agency is to recruit in those countries again."

        Design: Difficulty/non_linear_state_machine/agency_posture_probation_reinstate_lands_on_watch
        """
        env = probated_partner

        fx.posture_action(
            client,
            env["agency_id"],
            C.POSTURE_REINSTATE,
            "Investigation closed without adverse finding",
        )

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_SUSPENDED, (
            "restoring the agency's standing is not a contract lifecycle action"
        )
        assert (
            contract["suspension_reason"] == C.SUSPENSION_REASON_POSTURE_PROBATION
        )

        assignments = fx.read_assignments(client, env["contract_id"])
        released = [a for a in assignments if a["id"] == env["assignment_id"]]
        assert len(released) == 1, f"expected the one assignment, got {assignments!r}"
        assert released[0]["status"] == C.ASSIGNMENT_RELEASED
        assert released[0]["released_on"] == C.DEFAULT_CLOCK_DATE

        application = fx.read_application(client, env["application_id"])
        assert application["disclosure_state"] == C.DISCLOSURE_INVALIDATED

    def test_the_released_exclusive_slot_carries_no_surviving_cooloff_shadow(
        self, client, probated_partner
    ):
        """A cascade release frees the country immediately.

        "Occupancy is computed only from assignments still in `ACTIVE`; rows in
        `RELEASED` or `EXPIRED` contribute neither occupancy nor any lingering
        shadow."

        "`exclusive_slot_available`, which is true exactly when
        `exclusive_active_count` is zero, `non_exclusive_active_count` is zero,
        and either `exclusive_cooloff_until` is null or the requested instant
        falls at or after it"

        Design: Difficulty/non_linear_state_machine/agency_posture_probation_reinstate_lands_on_watch
        """
        occupancy = fx.read_occupancy(client, "IN", "2026-09-01")
        assert_occupancy(
            occupancy,
            country_code="IN",
            at_date="2026-09-01",
            exclusive_active_count=0,
            non_exclusive_active_count=0,
            exclusive_cooloff_until=None,
            exclusive_slot_available=True,
        )
