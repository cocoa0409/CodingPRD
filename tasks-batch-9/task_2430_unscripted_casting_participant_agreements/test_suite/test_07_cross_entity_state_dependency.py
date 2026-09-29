"""Transitions that are legal on their own row but blocked by the state of a
different entity, and that succeed unchanged once that other entity moves.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_money,
    get_agreement,
    get_applicant,
    get_production,
    get_shoot_block,
    record_screening_items,
    setup_applicant,
    setup_drafted_agreement,
    setup_location,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_shoot_block,
    validate_error,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]

SEASON_COVERAGE = {
    "coverage_start_utc": "2026-09-15T00:00:00Z",
    "coverage_end_utc": "2026-12-15T00:00:00Z",
}

# INTERVIEW, BACKGROUND_CHECK and PSYCH_EVAL all pass, but the medical exam is
# only conditional, which defers that dimension alone.
CLEARED_BUT_DEFERRED = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("PSYCH_EVAL", "PASS", 0, CO2),
    ("MEDICAL_EXAM", "CONDITIONAL", 0, CO1),
)


class TestAgreementSendReadsApplicantMedicalStatus:
    """ParticipantAgreement -> Applicant: the send gate reads a dimension that
    lives on the applicant, not on the agreement."""

    def _drafted_for_a_deferred_applicant(self, title: str, season_number: int):
        production = setup_production(
            title=title, season_number=season_number, minor_participant_cap=0
        )
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=0
        )
        applicant = setup_applicant(
            call["id"], legal_name="Quinn Abara", date_of_birth="1993-03-03"
        )
        assert applicant["psych_eval_required"] is True
        record_screening_items(applicant["id"], CLEARED_BUT_DEFERRED)

        screened = get_applicant(applicant["id"])
        assert screened["screening_status"] == "CLEARED"
        assert screened["medical_status"] == "DEFERRED"

        agreement = setup_drafted_agreement(applicant["id"], production["id"])
        assert agreement["status"] == "DRAFTED"
        return production, applicant, agreement

    def test_a_deferred_medical_dimension_refuses_the_send(self, api):
        """PRD §2.6: "On agreement send and agreement execution, the applicant's
        `medical_status` is `CLEARED`, otherwise
        `ERR_MEDICAL_CLEARANCE_MISSING` (422)."
        PRD §3.4: "Recording a `MEDICAL_EXAM` item with outcome `CONDITIONAL`
        moves `medical_status` to `DEFERRED` from either `NOT_STARTED` or
        `PENDING`, and a deferred applicant cannot have an agreement sent to
        them until a passing exam is recorded."
        PRD §3.4: "Medical clearance runs on its own dimension and neither gates
        nor is gated by the screening dimension — only the agreement send gate
        reads both together."

        Design: Difficulty/cross_entity_state_dependency/agreement_send_blocked_by_applicant_medical_deferred
        """
        _production, applicant, agreement = self._drafted_for_a_deferred_applicant(
            "Island Trials S9", 9
        )

        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_MEDICAL_CLEARANCE_MISSING.value,
            422,
        )

        # The agreement's own row is a perfectly legal DRAFTED source state.
        after = get_agreement(agreement["id"])
        assert after["status"] == "DRAFTED"
        assert_money(after["provisional_stipend_cents"], 0, "provisional stipend")
        # And the screening dimension was cleared the whole time.
        assert get_applicant(applicant["id"])["screening_status"] == "CLEARED"

    def test_a_passing_exam_moves_the_dimension_and_the_same_send_succeeds(self, api):
        """PRD §3.4: "Recording a `MEDICAL_EXAM` item with outcome `PASS` moves
        `medical_status` to `CLEARED` from any of `NOT_STARTED`, `PENDING`,
        `DEFERRED` or `EXPIRED`, and stamps that item's `expires_at` 30 days
        after its `recorded_at`."
        PRD §3.6: "Sending requires that the agreement be in `DRAFTED` or
        `REVISED` status, that its `welfare_hold` be false, that the production's
        posture not be `FROZEN`, that the applicant's `screening_status` be
        `CLEARED` and their `medical_status` be `CLEARED`".
        PRD §3.6: "On success the provisional stipend variant is written to
        `provisional_stipend_cents` — recomputed from the revised terms when the
        send follows a revision — and the status becomes `SENT`."

        Design: Difficulty/cross_entity_state_dependency/agreement_send_blocked_by_applicant_medical_deferred
        """
        _production, applicant, agreement = self._drafted_for_a_deferred_applicant(
            "Island Trials S9 Repaired", 10
        )
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_MEDICAL_CLEARANCE_MISSING.value,
            422,
        )

        record_screening_items(applicant["id"], [("MEDICAL_EXAM", "PASS", 0, CO1)])
        repaired = get_applicant(applicant["id"])
        assert repaired["medical_status"] == "CLEARED"
        assert repaired["screening_status"] == "CLEARED"

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        assert sent["status"] == "SENT"
        # Episode count max(2, 10) = 10 at tier 1.30: 1,300,000 base, 130,000
        # hazard, a two-appearance press reserve and the reunion charge.
        assert_money(
            sent["provisional_stipend_cents"], 1_630_000, "provisional stipend"
        )


class TestShootBlockRollReadsWelfareProtocolStatus:
    """ShootBlock -> WelfareProtocol: coverage that exists but is only planned
    is not coverage."""

    def _scheduled_block_over_a_planned_protocol(self, title: str, season_number: int):
        production = setup_production(
            title=title, season_number=season_number, minor_participant_cap=0
        )
        stage = setup_location(
            name="Stage A", capacity=500, filming_permit_number="PRM-1001"
        )
        protocol = setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=1_000_000,
            **SEASON_COVERAGE,
        )
        assert protocol["status"] == "PLANNED"
        block = setup_shoot_block(
            production["id"],
            stage["id"],
            block_kind="STUDIO",
            start_utc="2026-10-10T08:00:00Z",
            end_utc="2026-10-10T12:00:00Z",
            participant_agreement_ids=[],
            expected_crowd_headcount=0,
            onset_minor_hours=0,
        )
        assert block["status"] == "SCHEDULED"
        return production, protocol, block

    def test_a_merely_planned_duty_of_care_protocol_refuses_the_roll(self, api):
        """PRD §2.6: "On shoot-block roll, an `ACTIVE` `DUTY_OF_CARE_OFFICER`
        protocol covers the whole block interval, otherwise
        `ERR_DUTY_OF_CARE_UNCOVERED` (422)."
        PRD §3.8: "The production must hold a welfare protocol of kind
        `DUTY_OF_CARE_OFFICER` in `ACTIVE` status whose `coverage_start_utc` is
        at or before the block's `start_utc` and whose `coverage_end_utc` is at
        or after the block's `end_utc`; partial coverage is not coverage, and the
        failure is `ERR_DUTY_OF_CARE_UNCOVERED`."

        Design: Difficulty/cross_entity_state_dependency/shoot_block_roll_blocked_by_planned_duty_of_care_protocol
        """
        production, _protocol, block = self._scheduled_block_over_a_planned_protocol(
            "Island Trials S10", 10
        )

        validate_error(
            api.roll_shoot_block(block["id"], PA),
            ApiErrorId.ERR_DUTY_OF_CARE_UNCOVERED.value,
            422,
        )
        after = get_shoot_block(block["id"])
        assert after["status"] == "SCHEDULED"
        assert after["version"] == block["version"], (
            "a refused roll leaves the block row entirely untouched"
        )
        # The protocol's cost is committed even while it is only planned.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_060_000,
            "committed welfare",
        )

    def test_activating_the_same_protocol_admits_the_identical_roll(self, api):
        """PRD §3.7: "Activation moves a protocol `PLANNED → ACTIVE` and is
        admitted only from `PLANNED`, only when an insurance rider carries its
        certificate, and only while `coverage_end_utc` is still later than the
        logical clock — coverage that is already over cannot be activated."
        PRD §3.7: "Notably, because `PLANNED` and `ACTIVE` rows both count,
        activating a protocol leaves the subtotal unchanged, and because
        cancelled rows drop out, cancelling one removes its cost exactly."
        PRD §3.8: "Rolling moves a block `SCHEDULED → ROLLING` and is the on-set
        safety gate."

        Design: Difficulty/cross_entity_state_dependency/shoot_block_roll_blocked_by_planned_duty_of_care_protocol
        """
        production, protocol, block = self._scheduled_block_over_a_planned_protocol(
            "Island Trials S10 Covered", 11
        )
        validate_error(
            api.roll_shoot_block(block["id"], PA),
            ApiErrorId.ERR_DUTY_OF_CARE_UNCOVERED.value,
            422,
        )

        activated = validate_success(api.activate_welfare_protocol(protocol["id"], WO1))
        assert activated["status"] == "ACTIVE"

        rolled = validate_success(api.roll_shoot_block(block["id"], PA))
        assert rolled["status"] == "ROLLING"
        # Nothing on the block changed between the two attempts; only the
        # protocol did, and activation left the welfare figure alone.
        assert rolled["start_utc"] == block["start_utc"]
        assert rolled["end_utc"] == block["end_utc"]
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_060_000,
            "committed welfare",
        )
