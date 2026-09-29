"""Which refusal wins when a request breaks more than one rule, and who may act at all.

The cases here separate authorisation from existence, scope from role, and the
center-wide posture gate from the state checks that sit beside it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    AbstractionStatus,
    ActionType,
    CompletionStatus,
    CycleStatus,
    CycleType,
    Decision,
    DeficiencyClass,
    DeficiencyStatus,
    DesignationLevel,
    DIRECTOR_1_USER_ID,
    NationalVerificationStatus,
    PiEventType,
    PiSeverity,
    PiStatus,
    ReadinessPosture,
    TierCode,
    TriageReviewStatus,
    ValidationStatus,
    VALIDATOR_1_USER_ID,
    ABSTRACTOR_1_USER_ID,
    assert_instant,
    assert_pi_partition,
    factories as f,
    fixtures as fx,
    make_registry_abstractor_headers,
    make_registry_validator_headers,
    make_state_designation_officer_headers,
    make_system_admin_headers,
    make_trauma_medical_director_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)

STATE_OFFICER_1 = "u_state_1"
ABSENT_CYCLE_ID = "00000000-0000-0000-0000-000000000000"


class TestPostureGateOnRegistryLocking:
    """A denied national decision freezes a registry lock on a different entity."""

    def test_lock_after_a_denied_national_decision_is_refused_as_posture_suspended(
        self, api: ApiClient
    ) -> None:
        """The denial suspends the center, and the suspension is what blocks the lock.

        Design: Corner/validations/locking_a_case_after_a_denied_decision_returns_posture_suspended
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Anvil Rock Trauma",
            state_code="WV",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        cycle = fx.cycle_under_review(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-09-14T13:00:00Z",
            surveyor_user_id="u_surveyor_5",
            window_start="2026-09-14T08:00:00Z",
            window_end="2026-09-14T17:00:00Z",
        )
        fx.decide_cycle(
            api,
            cycle,
            decision=Decision.DENIED,
            decision_effective_date="2026-09-20T00:00:00Z",
        )
        case, _ = fx.case_validated(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-AR1",
            arrival_at="2026-07-30T16:00:00Z",
            injury_severity_score=33,
            los_hours=90.00,
            iss_abstracted=33,
            gcs_arrival=6,
            mechanism_code="MVC",
            ed_departure_at="2026-07-30T19:00:00Z",
        )

        refused = api.lock_registry_case(
            case["id"], make_trauma_program_manager_headers(center["id"])
        )
        validate_error(refused, E.POSTURE_SUSPENDED, 409)

        after_center = fx.get_center(api, center["id"])
        assert (
            after_center["national_verification_status"]
            == NationalVerificationStatus.SUSPENDED
        )
        assert after_center["readiness_posture"] == ReadinessPosture.SUSPENDED

        after_cycle = fx.get_cycle(api, cycle["id"])
        assert after_cycle["status"] == CycleStatus.DENIED
        assert_instant(
            after_cycle["decision_effective_date"],
            "2026-09-20T00:00:00Z",
            "decision_effective_date",
        )

        after_case = fx.get_case(api, case["id"])
        assert after_case["abstraction_status"] == AbstractionStatus.VALIDATED
        assert after_case["locked_at"] is None


class TestProgramManagerCenterScope:
    """The program manager's identity header is itself the authorisation scope."""

    def test_cycle_creation_for_a_peer_center_is_a_scope_violation(
        self, api: ApiClient
    ) -> None:
        """The same body is refused for a peer center and accepted for the manager's own.

        Design: Corner/rbac/program_manager_cannot_open_a_cycle_for_another_center
        """
        fx.anchor_clock(api)
        first = fx.create_center(
            api,
            name="Quarry Hill Trauma",
            state_code="VT",
            designation_level=DesignationLevel.LEVEL_III,
        )
        second = fx.create_center(
            api,
            name="Birchmont Trauma",
            state_code="VT",
            designation_level=DesignationLevel.LEVEL_II,
        )
        body = f.verification_cycle_payload(
            center_id=first["id"],
            cycle_type=CycleType.STATE_DESIGNATION,
            site_visit_date="2026-10-14T13:00:00Z",
        )

        refused = api.create_verification_cycle(
            body, make_trauma_program_manager_headers(second["id"])
        )
        validate_error(refused, E.CENTER_SCOPE_VIOLATION, 403)

        accepted = api.create_verification_cycle(
            body, make_trauma_program_manager_headers(first["id"])
        )
        cycle = validate_success(accepted, 201)
        assert cycle["center_id"] == first["id"]
        assert cycle["status"] == CycleStatus.PREP

        owned = get_success_data(
            api.list_center_verification_cycles(
                first["id"], make_trauma_program_manager_headers(first["id"])
            )
        )
        assert [row["id"] for row in owned] == [cycle["id"]]


class TestDesignationAuthorityPartition:
    """Two roles share one operation list, so cycle_type alone partitions the authority."""

    def test_state_officer_cannot_record_a_deficiency_on_a_national_cycle(
        self, api: ApiClient
    ) -> None:
        """The refusal names the authority mismatch, not a missing role permission.

        Design: Corner/rbac/state_officer_cannot_record_deficiencies_on_a_national_cycle
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Halcyon Trauma",
            state_code="AZ",
            designation_level=DesignationLevel.LEVEL_I,
        )
        cycle = fx.cycle_under_review(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-10-20T13:00:00Z",
            surveyor_user_id="u_surveyor_2",
            window_start="2026-10-20T08:00:00Z",
            window_end="2026-10-20T17:00:00Z",
        )
        body = f.criteria_deficiency_payload(
            criterion_code="CD-11-3",
            deficiency_class=DeficiencyClass.TYPE_III_MINOR,
            remediation_due_at="2026-11-20T00:00:00Z",
        )

        refused = api.create_criteria_deficiency(
            cycle["id"], body, make_state_designation_officer_headers(STATE_OFFICER_1)
        )
        validate_error(refused, E.DESIGNATION_AUTHORITY_MISMATCH, 403)
        assert refused.json()["data"]["error_id"] != E.ROLE_NOT_PERMITTED, (
            "the operation is in the state officer's shared list"
        )

        accepted = api.create_criteria_deficiency(
            cycle["id"], body, make_verification_reviewer_headers()
        )
        deficiency = validate_success(accepted, 201)
        assert deficiency["status"] == DeficiencyStatus.OPEN

        after = fx.get_cycle(api, cycle["id"])
        assert after["open_type_iii_count"] == 1
        assert after["open_type_i_count"] == 0


class TestSegregationOfDutiesOnAdjudication:
    """Adjudication compares identities, not roles."""

    def test_validator_acting_under_the_abstractors_identity_is_refused(
        self, api: ApiClient
    ) -> None:
        """A legitimate validator role cannot bless a submission made under its own id.

        Design: Corner/rbac/validator_identity_equal_to_the_abstractor_is_refused
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Sablewood Trauma",
            state_code="AL",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case, abstraction = fx.case_abstracted(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-SW1",
            arrival_at="2026-07-26T11:00:00Z",
            injury_severity_score=21,
            los_hours=48.00,
            iss_abstracted=21,
            gcs_arrival=9,
            mechanism_code="FALL",
            ed_departure_at="2026-07-26T14:00:00Z",
        )

        refused = api.validate_abstraction(
            abstraction["id"],
            make_registry_validator_headers(ABSTRACTOR_1_USER_ID),
        )
        validate_error(refused, E.SEGREGATION_OF_DUTIES, 409)

        untouched = fx.get_abstraction(api, case["id"], abstraction["id"])
        assert untouched["validation_status"] == ValidationStatus.SUBMITTED
        assert (
            fx.get_case(api, case["id"])["abstraction_status"]
            == AbstractionStatus.ABSTRACTED
        )

        accepted = api.validate_abstraction(
            abstraction["id"], make_registry_validator_headers(VALIDATOR_1_USER_ID)
        )
        adjudicated = validate_success(accepted, 200)
        assert adjudicated["validation_status"] == ValidationStatus.VALIDATED
        assert adjudicated["validated_by_user_id"] == VALIDATOR_1_USER_ID
        assert (
            fx.get_case(api, case["id"])["abstraction_status"]
            == AbstractionStatus.VALIDATED
        )


class TestExclusiveTriageAdjudication:
    """Triage adjudication is the medical director's alone."""

    def test_abstractor_cannot_adjudicate_the_triage_decision(
        self, api: ApiClient
    ) -> None:
        """Even the abstractor who opened the case is refused, and the dimension holds.

        Design: Corner/rbac/abstractor_cannot_perform_the_directors_exclusive_triage_review
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Tallgrass Trauma",
            state_code="KS",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-TG1",
            arrival_at="2026-07-28T07:00:00Z",
            injury_severity_score=26,
            los_hours=55.00,
        )
        body = f.triage_review_payload(TriageReviewStatus.OVER_TRIAGE_CONFIRMED)

        refused = api.triage_review_case(
            case["id"], body, make_registry_abstractor_headers()
        )
        validate_error(refused, E.ROLE_NOT_PERMITTED, 403)
        assert (
            fx.get_case(api, case["id"])["triage_review_status"]
            == TriageReviewStatus.UNREVIEWED
        )

        accepted = api.triage_review_case(
            case["id"], body, make_trauma_medical_director_headers()
        )
        reviewed = validate_success(accepted, 200)
        assert reviewed["triage_review_status"] == TriageReviewStatus.OVER_TRIAGE_CONFIRMED


class TestStateErrorPrecedesTemporalWindow:
    """A case that is both adjudicated and out of window answers with the state error."""

    def _validated_case_now_out_of_window(self, api: ApiClient):
        """A case validated inside its window, then left behind by the clock."""
        fx.anchor_clock(api, "2026-05-02T00:00:00Z")
        center, tier = fx.center_with_tier(
            api,
            name="Coalfield Trauma",
            state_code="WV",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case, abstraction = fx.case_validated(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-W1",
            arrival_at="2026-05-01T08:00:00Z",
            injury_severity_score=21,
            los_hours=50.00,
            iss_abstracted=21,
            gcs_arrival=10,
            mechanism_code="MVC",
            ed_departure_at="2026-05-01T11:00:00Z",
        )
        fx.move_clock(api, "2026-08-01T00:00:00Z")
        return center, fx.get_case(api, case["id"]), abstraction

    def test_the_adjudicated_state_is_what_refuses_the_replayed_abstraction(
        self, api: ApiClient
    ) -> None:
        """Both the state rule and the sixty day window are breached; the state rule answers.

        Design: Difficulty/priority_pair_validation_conflict/locked_dimension_state_error_precedes_closed_abstraction_window
        """
        center, case, _ = self._validated_case_now_out_of_window(api)
        assert case["abstraction_status"] == AbstractionStatus.VALIDATED

        refused = api.create_abstraction(
            case["id"],
            f.abstraction_payload(
                expected_case_version=case["version"],
                iss_abstracted=21,
                gcs_arrival=10,
                mechanism_code="MVC",
                ed_departure_at="2026-05-01T11:00:00Z",
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.CASE_NOT_ABSTRACTABLE, 409)
        assert refused.json()["data"]["error_id"] != E.ABSTRACTION_WINDOW_CLOSED, (
            "the sixty day window is also breached, but it is not what answers"
        )

    def test_the_refusal_leaves_the_case_and_its_single_record_untouched(
        self, api: ApiClient
    ) -> None:
        """No version is consumed and no second abstraction record appears.

        Design: Difficulty/priority_pair_validation_conflict/locked_dimension_state_error_precedes_closed_abstraction_window
        """
        _, case, abstraction = self._validated_case_now_out_of_window(api)
        version_before = case["version"]

        validate_error(
            api.create_abstraction(
                case["id"],
                f.abstraction_payload(
                    expected_case_version=version_before,
                    iss_abstracted=21,
                    gcs_arrival=10,
                    mechanism_code="MVC",
                    ed_departure_at="2026-05-01T11:00:00Z",
                ),
                make_registry_abstractor_headers(),
            ),
            E.CASE_NOT_ABSTRACTABLE,
            409,
        )

        after = fx.get_case(api, case["id"])
        assert after["abstraction_status"] == AbstractionStatus.VALIDATED
        assert after["version"] == version_before

        records = get_success_data(
            api.list_abstractions(case["id"], make_registry_abstractor_headers())
        )
        assert [row["id"] for row in records] == [abstraction["id"]]


class TestOpenActionsPrecedeSegregationOfDuties:
    """The closing director owns the only action, and that action is still open."""

    def _loop_owned_by_the_closing_director(self, api: ApiClient):
        """An event at ACTION_PLANNED whose single open action belongs to its director."""
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Sandhill Trauma",
            state_code="NE",
            designation_level=DesignationLevel.LEVEL_II,
        )
        event, action = fx.pi_loop_at_action_planned(
            api,
            center["id"],
            event_type=PiEventType.TRANSFER_DELAY,
            severity=PiSeverity.MEDIUM,
            action_type=ActionType.EDUCATION,
            owner_user_id=DIRECTOR_1_USER_ID,
            due_at="2026-09-01T00:00:00Z",
        )
        return center, event, action

    def test_the_unverified_action_is_what_refuses_the_closure(
        self, api: ApiClient
    ) -> None:
        """The closer owns the action, yet the answer is the unverified-actions error.

        Design: Difficulty/priority_pair_validation_conflict/open_action_safety_error_precedes_segregation_of_duties
        """
        center, event, action = self._loop_owned_by_the_closing_director(api)
        assert action["owner_user_id"] == DIRECTOR_1_USER_ID
        assert action["completion_status"] == CompletionStatus.OPEN

        refused = api.close_pi_loop(
            event["id"],
            f.close_loop_payload("Closing my own action without verification."),
            make_trauma_medical_director_headers(DIRECTOR_1_USER_ID),
        )
        validate_error(refused, E.OPEN_ACTIONS_BLOCK_LOOP_CLOSURE, 409)
        assert refused.json()["data"]["error_id"] != E.SEGREGATION_OF_DUTIES, (
            "the duties rule also fires, but it is reported second"
        )

        untouched = fx.get_event(api, event["id"])
        assert untouched["status"] == PiStatus.ACTION_PLANNED
        assert untouched["closed_at"] is None
        assert untouched["verified_action_count"] == 0
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )

    def test_the_duties_error_surfaces_once_the_action_is_verified(
        self, api: ApiClient
    ) -> None:
        """Removing the first breach exposes the second: the owner still may not close.

        Design: Difficulty/priority_pair_validation_conflict/open_action_safety_error_precedes_segregation_of_duties
        """
        center, event, action = self._loop_owned_by_the_closing_director(api)

        fx.complete_action(api, action)
        fx.verify_action(api, action)
        assert (
            fx.get_corrective_action(api, event["id"], action["id"])["completion_status"]
            == CompletionStatus.VERIFIED
        )
        assert fx.get_event(api, event["id"])["verified_action_count"] == 1

        refused = api.close_pi_loop(
            event["id"],
            f.close_loop_payload("Closing my own action after verification."),
            make_trauma_medical_director_headers(DIRECTOR_1_USER_ID),
        )
        validate_error(refused, E.SEGREGATION_OF_DUTIES, 409)

        still_open = fx.get_event(api, event["id"])
        assert still_open["status"] == PiStatus.ACTION_PLANNED
        assert still_open["closed_at"] is None
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )


class TestRolePrecedesExistence:
    """Authorisation is decided before any lookup can leak an identifier's absence."""

    def test_an_unpermitted_role_is_refused_before_the_cycle_is_looked_up(
        self, api: ApiClient
    ) -> None:
        """An abstractor submitting a cycle that cannot exist is told about the role.

        Design: Difficulty/priority_pair_validation_conflict/role_auth_error_precedes_missing_cycle_existence_check
        """
        fx.anchor_clock(api)
        fx.create_center(
            api,
            name="Blue Hills Trauma",
            state_code="MO",
            designation_level=DesignationLevel.LEVEL_III,
        )

        refused = api.submit_verification_cycle(
            ABSENT_CYCLE_ID, make_registry_abstractor_headers()
        )
        validate_error(refused, E.ROLE_NOT_PERMITTED, 403)
        assert refused.json()["data"]["error_id"] != E.CYCLE_NOT_FOUND, (
            "the lookup never runs, so the absence is never disclosed"
        )

    def test_a_permitted_role_reaches_the_existence_check_on_the_same_identifier(
        self, api: ApiClient
    ) -> None:
        """The manager is permitted to submit, so the same id answers not-found instead.

        Design: Difficulty/priority_pair_validation_conflict/role_auth_error_precedes_missing_cycle_existence_check
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Blue Hills Trauma",
            state_code="MO",
            designation_level=DesignationLevel.LEVEL_III,
        )

        refused = api.submit_verification_cycle(
            ABSENT_CYCLE_ID, make_trauma_program_manager_headers(center["id"])
        )
        validate_error(refused, E.CYCLE_NOT_FOUND, 404)

        assert (
            get_success_data(api.list_verification_cycles(make_system_admin_headers()))
            == []
        ), "no cycle was created by either refusal"
