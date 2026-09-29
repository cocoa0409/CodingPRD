"""Registering a center, configuring its tiers, and declaring the immutable dictionary.

Registration seeds every derived field the rest of the program reads, activation tiers are
unique per code, and dictionary rules are configuration that can never be rewritten.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    AbstractionStatus,
    AgreementStatus,
    CycleStatus,
    CycleType,
    DesignationLevel,
    DictionaryFieldName,
    ERROR_WEIGHT_CRITICAL,
    ERROR_WEIGHT_MINOR,
    InclusionStatus,
    NationalVerificationStatus,
    PiEventType,
    PiOrigin,
    PiSeverity,
    PiStatus,
    ReadinessPosture,
    RuleSeverity,
    StateDesignationStatus,
    TierCode,
    TriageReviewStatus,
    assert_activation_tier,
    assert_center_defaults,
    assert_data_dictionary_rule,
    assert_decimal,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_system_admin_headers,
    make_trauma_program_manager_headers,
)


class TestCenterRegistrationDefaults:
    """A new center arrives with its whole derived surface already seeded."""

    def test_registration_seeds_every_system_and_computed_field(
        self, api: ApiClient
    ) -> None:
        """Four inputs are enough: the statuses, the score and all seven counters are minted.

        Design: Corner/entities/create_trauma_center_returns_all_system_and_computed_defaults
        """
        fx.anchor_clock(api)

        response = api.create_trauma_center(
            f.trauma_center_payload(
                name="Northgate Trauma",
                state_code="OR",
                designation_level=DesignationLevel.LEVEL_I,
                verification_cycle_start_date="2026-01-01T00:00:00Z",
            ),
            make_system_admin_headers(),
        )
        center = validate_success(response, 201)

        assert center["name"] == "Northgate Trauma"
        assert center["state_code"] == "OR"
        assert center["designation_level"] == DesignationLevel.LEVEL_I
        assert_center_defaults(center)
        assert (
            center["national_verification_status"]
            == NationalVerificationStatus.NOT_VERIFIED
        )
        assert center["state_designation_status"] == StateDesignationStatus.NOT_DESIGNATED
        assert center["readiness_posture"] == ReadinessPosture.READY


class TestActivationTierConfiguration:
    """Tier codes come from a closed set, and each code is configurable once."""

    def test_an_unknown_tier_code_is_refused_as_an_enum_violation(
        self, api: ApiClient
    ) -> None:
        """A code outside the declared three is 422, a different answer than a missing field.

        Design: Corner/entities/unknown_tier_code_enum_member_returns_invalid_enum_value
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Ironwood Trauma",
            state_code="AL",
            designation_level=DesignationLevel.LEVEL_III,
        )

        refused = api.create_activation_tier(
            center["id"],
            f.activation_tier_payload(
                tier_code="TIER_0_ALERT",
                surgeon_response_limit_minutes=15,
                specialty_response_limit_minutes=30,
                iss_threshold=16,
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        validate_error(refused, E.INVALID_ENUM_VALUE, 422)

        assert (
            get_success_data(
                api.list_activation_tiers(
                    center["id"], make_trauma_program_manager_headers(center["id"])
                )
            )
            == []
        )

    def test_a_second_tier_with_the_same_code_is_a_duplicate_configuration(
        self, api: ApiClient
    ) -> None:
        """The rejected redefinition does not silently rewrite the original limits.

        Design: Corner/validations/duplicate_tier_code_for_one_center_returns_duplicate_configuration
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Hawthorn Trauma",
            state_code="NC",
            designation_level=DesignationLevel.LEVEL_I,
        )
        tier = fx.create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_1_FULL,
            surgeon_response_limit_minutes=15,
            specialty_response_limit_minutes=30,
            iss_threshold=16,
        )
        assert_activation_tier(tier, center["id"])

        refused = api.create_activation_tier(
            center["id"],
            f.activation_tier_payload(
                tier_code=TierCode.TIER_1_FULL,
                surgeon_response_limit_minutes=20,
                specialty_response_limit_minutes=45,
                iss_threshold=16,
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        validate_error(refused, E.DUPLICATE_CONFIGURATION, 409)

        rows = get_success_data(
            api.list_activation_tiers(
                center["id"],
                make_trauma_program_manager_headers(center["id"]),
                {"tier_code": TierCode.TIER_1_FULL},
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == tier["id"]
        assert rows[0]["surgeon_response_limit_minutes"] == 15
        assert rows[0]["specialty_response_limit_minutes"] == 30


class TestDataDictionaryImmutability:
    """Dictionary rules are configuration: weighted by severity and never versioned."""

    def test_rules_carry_a_severity_weight_and_no_version(self, api: ApiClient) -> None:
        """A critical rule weighs four points and a minor rule one, with no version field.

        Design: Corner/entities/data_dictionary_rule_is_immutable_and_carries_no_version
        """
        fx.anchor_clock(api)

        critical = fx.create_rule(
            api,
            f.range_rule_payload(
                field_name=DictionaryFieldName.GCS_ARRIVAL,
                min_value=3,
                max_value=15,
                severity=RuleSeverity.CRITICAL,
            ),
        )
        minor = fx.create_rule(
            api,
            f.conformance_rule_payload(
                field_name=DictionaryFieldName.MECHANISM_CODE,
                allowed_codes=["MVC", "FALL", "GSW", "STAB", "BURN"],
                severity=RuleSeverity.MINOR,
            ),
        )

        for rule in (critical, minor):
            assert_data_dictionary_rule(rule)
        assert critical["error_weight"] == ERROR_WEIGHT_CRITICAL
        assert minor["error_weight"] == ERROR_WEIGHT_MINOR

        criticals = get_success_data(
            api.list_data_dictionary_rules(
                make_system_admin_headers(), {"severity": RuleSeverity.CRITICAL}
            )
        )
        assert [row["id"] for row in criticals] == [critical["id"]]


class TestDeclaredInitialStates:
    """Every entity with a lifecycle starts where its lifecycle says it starts."""

    def test_fresh_entities_occupy_their_declared_opening_states(
        self, api: ApiClient
    ) -> None:
        """A case, a cycle, an event and an agreement are all created at the top of their ladders.

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
        """
        fx.anchor_clock(api)
        referring, tier = fx.center_with_tier(
            api,
            name="Alder Grove Trauma",
            state_code="WI",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        receiving = fx.create_center(
            api,
            name="Lakefront Regional Trauma",
            state_code="WI",
            designation_level=DesignationLevel.LEVEL_I,
        )

        case = fx.create_case(
            api,
            referring["id"],
            tier["id"],
            mrn="MRN-AG1",
            arrival_at="2026-07-25T10:00:00Z",
            injury_severity_score=24,
            los_hours=55.00,
        )
        assert case["abstraction_status"] == AbstractionStatus.PENDING
        assert case["triage_review_status"] == TriageReviewStatus.UNREVIEWED
        assert case["inclusion_status"] == InclusionStatus.INCLUDED

        cycle = fx.create_cycle(
            api,
            referring["id"],
            cycle_type=CycleType.STATE_DESIGNATION,
            site_visit_date="2026-11-12T13:00:00Z",
        )
        assert cycle["status"] == CycleStatus.PREP
        assert_decimal(cycle["readiness_score"], 88.00, "readiness_score")

        event = fx.create_pi_event(
            api,
            referring["id"],
            event_type=PiEventType.MORTALITY_REVIEW,
            severity=PiSeverity.LOW,
        )
        assert event["status"] == PiStatus.IDENTIFIED
        assert event["origin"] == PiOrigin.MANUAL
        assert event["review_round"] == 1
        assert event["closed_at"] is None
        assert_instant(
            event["loop_closure_due_at"], "2026-09-30T00:00:00Z", "loop_closure_due_at"
        )

        agreement = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            guaranteed_acceptance_minutes=60,
        )
        assert agreement["agreement_status"] == AgreementStatus.DRAFT
        assert agreement["activated_at"] is None
        assert agreement["terminated_at"] is None
