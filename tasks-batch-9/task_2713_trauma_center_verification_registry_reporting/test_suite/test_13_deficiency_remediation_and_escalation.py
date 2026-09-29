"""Deficiency escalation as a cascade, and the concurrency token that guards remediation.

A contingency decision is not a single write: it re-dates every critical finding, opens a
system event for each one, and can suspend the center on the strength of the count alone.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    CycleStatus,
    CycleType,
    Decision,
    DeficiencyClass,
    DeficiencyStatus,
    DesignationLevel,
    NationalVerificationStatus,
    PiEventType,
    PiOrigin,
    ReadinessPosture,
    SURVEYOR_1,
    StateDesignationStatus,
    assert_decimal,
    assert_instant,
    assert_readiness_read,
    factories as f,
    fixtures as fx,
    make_system_admin_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)


def _cycle_under_review_with_two_criticals(api: ApiClient):
    """A national cycle deliberating on two critical findings from its site visit."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Iron Range Trauma",
        state_code="MN",
        designation_level=DesignationLevel.LEVEL_I,
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-09-10T13:00:00Z",
    )
    fx.submit_cycle(api, cycle)
    fx.book_surveyor(
        api,
        cycle,
        surveyor_user_id=SURVEYOR_1,
        window_start="2026-09-10T08:00:00Z",
        window_end="2026-09-10T17:00:00Z",
    )
    fx.schedule_site_visit(api, cycle, "2026-09-10T08:00:00Z")
    fx.begin_review(api, cycle)
    first, second = fx.deficiencies_of_class(
        api,
        cycle,
        ["CD-02-01", "CD-02-02"],
        deficiency_class=DeficiencyClass.TYPE_I_CRITICAL,
        remediation_due_at="2026-09-25T00:00:00Z",
    )
    return center, fx.get_cycle(api, cycle["id"]), first, second


class TestContingencyCascade:
    """One decision propagates through findings, events, counters and posture."""

    def test_the_contingency_decision_escalates_every_critical_finding(
        self, api: ApiClient
    ) -> None:
        """The cycle and the center both record contingency, and both findings escalate.

        Design: Difficulty/transitive_cascade/contingency_escalation_to_posture_suspension
        """
        center, cycle, first, second = _cycle_under_review_with_two_criticals(api)

        decided = fx.decide_cycle(
            api,
            cycle,
            decision=Decision.CONTINGENCY,
            decision_effective_date="2026-09-01T00:00:00Z",
        )
        assert decided["status"] == CycleStatus.CONTINGENCY
        assert_instant(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")

        after_center = fx.get_center(api, center["id"])
        assert (
            after_center["national_verification_status"]
            == NationalVerificationStatus.CONTINGENCY
        )
        assert (
            after_center["state_designation_status"]
            == StateDesignationStatus.NOT_DESIGNATED
        ), "a national decision never touches the state designation"

        for deficiency in (first, second):
            escalated = fx.get_deficiency(api, cycle["id"], deficiency["id"])
            assert escalated["status"] == DeficiencyStatus.ESCALATED
            assert_instant(
                escalated["remediation_due_at"],
                "2026-08-31T00:00:00Z",
                "remediation_due_at",
            )

    def test_the_escalations_open_one_system_event_each_and_suspend_the_center(
        self, api: ApiClient
    ) -> None:
        """Two escalations produce two linked events and a suspended posture.

        Design: Difficulty/transitive_cascade/contingency_escalation_to_posture_suspension
        """
        center, cycle, first, second = _cycle_under_review_with_two_criticals(api)

        fx.decide_cycle(
            api,
            cycle,
            decision=Decision.CONTINGENCY,
            decision_effective_date="2026-09-01T00:00:00Z",
        )

        events = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"center_id": center["id"]})
        )
        assert len(events) == 2
        for event in events:
            assert event["event_type"] == PiEventType.DEFICIENCY_ESCALATION
            assert event["origin"] == PiOrigin.SYSTEM_AUTO
        assert {event["source_deficiency_id"] for event in events} == {
            first["id"],
            second["id"],
        }

        after_center = fx.get_center(api, center["id"])
        assert after_center["open_pi_event_count"] == 2
        assert after_center["escalated_critical_deficiency_count"] == 2
        assert after_center["readiness_posture"] == ReadinessPosture.SUSPENDED

        assert_readiness_read(
            fx.get_readiness(api, cycle["id"]),
            None,
            deficiency_penalty=30,
            outreach_penalty=18.00,
            pi_penalty=8,
            readiness_score=44.00,
            submit_eligible=False,
        )


class TestRemediationConcurrencyToken:
    """The remediation packet carries the parent cycle's version, not the deficiency's."""

    def test_a_stale_cycle_version_rejects_the_remediation_packet(
        self, api: ApiClient
    ) -> None:
        """The version captured at cycle creation is refused once the cycle has moved on.

        Design: Corner/complexity_layers/stale_cycle_version_rejects_the_remediation_packet
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Millbrook Trauma",
            state_code="IN",
            designation_level=DesignationLevel.LEVEL_II,
        )
        cycle = fx.create_cycle(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-10-27T13:00:00Z",
        )
        assert_decimal(cycle["readiness_score"], 82.00, "readiness_score")
        stale_version = cycle["version"]

        fx.submit_cycle(api, cycle)
        fx.book_surveyor(
            api,
            cycle,
            surveyor_user_id="u_surveyor_3",
            window_start="2026-10-27T08:00:00Z",
            window_end="2026-10-27T17:00:00Z",
        )
        fx.schedule_site_visit(api, cycle, "2026-10-27T13:00:00Z")
        fx.begin_review(api, cycle)
        deficiency = fx.record_deficiency(
            api,
            cycle,
            criterion_code="CD-05-9",
            deficiency_class=DeficiencyClass.TYPE_III_MINOR,
            remediation_due_at="2026-11-27T00:00:00Z",
        )

        refused = api.submit_remediation(
            deficiency["id"],
            f.remediation_payload(
                stale_version, "Registry abstraction backlog cleared to within 30 days."
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        validate_error(refused, E.STALE_CYCLE_VERSION, 412)

        untouched = fx.get_deficiency(api, cycle["id"], deficiency["id"])
        assert untouched["status"] == DeficiencyStatus.OPEN
        assert untouched["remediation_note"] is None

        current_version = fx.get_cycle(api, cycle["id"])["version"]
        assert current_version > stale_version, (
            "the cycle advanced while the packet was being prepared"
        )

        accepted = api.submit_remediation(
            deficiency["id"],
            f.remediation_payload(
                current_version,
                "Registry abstraction backlog cleared to within 30 days.",
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        remediated = validate_success(accepted, 200)
        assert remediated["status"] == DeficiencyStatus.REMEDIATION_SUBMITTED

        assert fx.get_cycle(api, cycle["id"])["open_type_iii_count"] == 1
