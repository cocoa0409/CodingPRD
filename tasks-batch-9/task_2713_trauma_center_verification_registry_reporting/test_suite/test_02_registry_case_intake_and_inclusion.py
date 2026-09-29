"""Opening registry cases: the read-back surface, the listing, and inclusion at intake.

Intake is where the cohort partition is decided, where the MRN uniqueness scope is one
center rather than the whole registry, and where the two referenced resources are
distinguished from one another in the rejection they produce.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    ABSTRACTOR_1_USER_ID,
    AbstractionStatus,
    CycleType,
    DEFAULT_TRAVEL_BUFFER_HOURS,
    DesignationLevel,
    EdDisposition,
    InclusionReason,
    InclusionStatus,
    OMIT,
    TierCode,
    TriageReviewStatus,
    assert_cohort_partition,
    assert_registry_case,
    assert_surveyor_booking,
    factories as f,
    fixtures as fx,
    make_registry_abstractor_headers,
    make_registry_validator_headers,
    make_system_admin_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)

UNKNOWN_CENTER_ID = "22222222-2222-2222-2222-222222222222"
UNKNOWN_TIER_ID = "33333333-3333-3333-3333-333333333333"
SURVEYOR_9 = "u_surveyor_9"


class TestRegistryCaseReadBack:
    """Everything a case is asked for and everything it derives is on the read."""

    def test_a_fresh_case_reads_back_its_inputs_and_its_derived_fields(
        self, api: ApiClient
    ) -> None:
        """Both state dimensions, the effective severity and the cohort verdict are present.

        Design: Corner/entities/get_registry_case_returns_stored_and_derived_values
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Redstone Trauma",
            state_code="UT",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
            surgeon_response_limit_minutes=15,
            specialty_response_limit_minutes=30,
            iss_threshold=16,
        )
        created = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-RS1",
            arrival_at="2026-07-22T03:30:00Z",
            injury_severity_score=22,
            los_hours=48.00,
        )

        case = validate_success(
            api.get_registry_case(created["id"], make_registry_validator_headers()), 200
        )
        assert_registry_case(case, center["id"])
        assert case["mrn"] == "MRN-RS1"
        assert case["activation_tier_id"] == tier["id"]
        assert case["injury_severity_score"] == 22
        assert case["abstraction_status"] == AbstractionStatus.PENDING
        assert case["triage_review_status"] == TriageReviewStatus.UNREVIEWED
        assert case["locked_at"] is None
        assert case["transfer_out_to_center_id"] is None
        assert case["effective_iss"] == 22, (
            "with no validated abstraction the effective severity is the intake score"
        )
        assert case["inclusion_status"] == InclusionStatus.INCLUDED
        assert case["inclusion_reason"] == InclusionReason.MEETS_INCLUSION_CRITERIA


class TestRegistryCaseListing:
    """The listing is scoped by center and paged by limit and offset."""

    def test_the_listing_filters_by_center_and_walks_its_pages(
        self, api: ApiClient
    ) -> None:
        """Three cases at one center page two then one, and the partner's case never appears.

        Design: Corner/entities/list_registry_cases_filters_by_center_and_paginates
        """
        fx.anchor_clock(api)
        first_center, first_tier = fx.center_with_tier(
            api,
            name="Prairie Trauma",
            state_code="ND",
            designation_level=DesignationLevel.LEVEL_III,
            tier_code=TierCode.TIER_1_FULL,
        )
        second_center, second_tier = fx.center_with_tier(
            api,
            name="Quarry Trauma",
            state_code="ND",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        mine = [
            fx.create_case(
                api,
                first_center["id"],
                first_tier["id"],
                mrn=mrn,
                arrival_at=arrival_at,
                injury_severity_score=iss,
                los_hours=30.00,
            )["id"]
            for mrn, arrival_at, iss in (
                ("MRN-P1", "2026-07-01T01:00:00Z", 18),
                ("MRN-P2", "2026-07-02T01:00:00Z", 19),
                ("MRN-P3", "2026-07-03T01:00:00Z", 20),
            )
        ]
        theirs = fx.create_case(
            api,
            second_center["id"],
            second_tier["id"],
            mrn="MRN-Q1",
            arrival_at="2026-07-01T01:00:00Z",
            injury_severity_score=18,
            los_hours=30.00,
        )

        first_page = api.list_registry_cases(
            make_system_admin_headers(),
            {"center_id": first_center["id"], "limit": 2, "offset": 0},
        )
        rows, meta = validate_paginated(first_page)
        assert first_page.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        second_page = api.list_registry_cases(
            make_system_admin_headers(),
            {"center_id": first_center["id"], "limit": 2, "offset": 2},
        )
        tail, tail_meta = validate_paginated(second_page)
        assert len(tail) == 1
        assert tail_meta["total_count"] == 3
        assert tail_meta["has_more"] is False

        seen = [row["id"] for row in rows] + [row["id"] for row in tail]
        assert set(seen) == set(mine)
        assert theirs["id"] not in seen


class TestRegistryCaseIntakeValidation:
    """A required input is a 400, and the two unknown references differ from each other."""

    def test_a_case_without_an_arrival_instant_is_an_invalid_request(
        self, api: ApiClient
    ) -> None:
        """The arrival instant drives the abstraction window, so its absence is fatal.

        Design: Corner/entities/create_registry_case_without_arrival_at_returns_invalid_request
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Bayside Trauma",
            state_code="RI",
            designation_level=DesignationLevel.LEVEL_III,
            tier_code=TierCode.TIER_2_MODIFIED,
            surgeon_response_limit_minutes=30,
            specialty_response_limit_minutes=60,
            iss_threshold=9,
        )

        refused = api.create_registry_case(
            f.registry_case_payload(
                center_id=center["id"],
                activation_tier_id=tier["id"],
                mrn="MRN-BS1",
                arrival_at=OMIT,
                injury_severity_score=14,
                los_hours=20.00,
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.INVALID_REQUEST, 400)

        assert (
            get_success_data(
                api.list_registry_cases(
                    make_system_admin_headers(), {"center_id": center["id"]}
                )
            )
            == []
        )
        assert_cohort_partition(
            fx.get_center(api, center["id"]), included=0, excluded=0
        )

    def test_an_unknown_center_is_a_center_not_found_rather_than_a_reference_failure(
        self, api: ApiClient
    ) -> None:
        """The path-bearing owner has its own existence error, distinct from the tier's.

        Design: Corner/entities/create_registry_case_under_unknown_center_returns_center_not_found
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Mesa Verde Trauma",
            state_code="NM",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )

        refused = api.create_registry_case(
            f.registry_case_payload(
                center_id=UNKNOWN_CENTER_ID,
                activation_tier_id=tier["id"],
                mrn="MRN-MV1",
                arrival_at="2026-07-19T05:00:00Z",
                injury_severity_score=21,
                los_hours=48.00,
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.CENTER_NOT_FOUND, 404)
        assert refused.json()["data"]["error_id"] != E.REFERENCED_RESOURCE_NOT_FOUND, (
            "the owning center has its own existence error"
        )

        assert (
            get_success_data(
                api.list_registry_cases(
                    make_system_admin_headers(), {"center_id": center["id"]}
                )
            )
            == []
        )

    def test_an_unknown_activation_tier_is_a_referenced_resource_failure(
        self, api: ApiClient
    ) -> None:
        """A tier that was never configured is a reference the intake cannot resolve.

        Design: Corner/entities/create_registry_case_with_unknown_activation_tier_returns_referenced_resource_not_found
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Kettle Falls Trauma",
            state_code="ID",
            designation_level=DesignationLevel.LEVEL_III,
        )

        refused = api.create_registry_case(
            f.registry_case_payload(
                center_id=center["id"],
                activation_tier_id=UNKNOWN_TIER_ID,
                mrn="MRN-KF1",
                arrival_at="2026-07-17T07:00:00Z",
                injury_severity_score=19,
                los_hours=36.00,
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.REFERENCED_RESOURCE_NOT_FOUND, 404)

        assert (
            get_success_data(
                api.list_activation_tiers(
                    center["id"], make_trauma_program_manager_headers(center["id"])
                )
            )
            == []
        )
        assert (
            get_success_data(
                api.list_registry_cases(
                    make_system_admin_headers(), {"center_id": center["id"]}
                )
            )
            == []
        )

    def test_the_same_mrn_collides_within_a_center_but_not_across_centers(
        self, api: ApiClient
    ) -> None:
        """MRN uniqueness is scoped to one center, so the partner may reuse the number.

        Design: Corner/validations/duplicate_mrn_at_same_center_returns_duplicate_case_mrn
        """
        fx.anchor_clock(api)
        first_center, first_tier = fx.center_with_tier(
            api,
            name="Dovetail Trauma",
            state_code="GA",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        second_center, second_tier = fx.center_with_tier(
            api,
            name="Peachtree Regional Trauma",
            state_code="GA",
            designation_level=DesignationLevel.LEVEL_I,
            tier_code=TierCode.TIER_1_FULL,
        )
        fx.create_case(
            api,
            first_center["id"],
            first_tier["id"],
            mrn="MRN-DP1",
            arrival_at="2026-07-08T08:00:00Z",
            injury_severity_score=18,
            los_hours=40.00,
        )

        refused = api.create_registry_case(
            f.registry_case_payload(
                center_id=first_center["id"],
                activation_tier_id=first_tier["id"],
                mrn="MRN-DP1",
                arrival_at="2026-07-09T08:00:00Z",
                injury_severity_score=19,
                los_hours=41.00,
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.DUPLICATE_CASE_MRN, 409)

        accepted = api.create_registry_case(
            f.registry_case_payload(
                center_id=second_center["id"],
                activation_tier_id=second_tier["id"],
                mrn="MRN-DP1",
                arrival_at="2026-07-10T08:00:00Z",
                injury_severity_score=20,
                los_hours=42.00,
            ),
            make_registry_abstractor_headers(),
        )
        elsewhere = validate_success(accepted, 201)
        assert elsewhere["mrn"] == "MRN-DP1"
        assert elsewhere["center_id"] == second_center["id"]

        assert_cohort_partition(
            fx.get_center(api, first_center["id"]), included=1, excluded=0
        )
        assert_cohort_partition(
            fx.get_center(api, second_center["id"]), included=1, excluded=0
        )


class TestIntakeDefaultsAndInclusion:
    """Omitted optionals take their declared defaults; the tier decides the cohort floor."""

    def test_omitted_optionals_are_filled_from_their_declared_defaults(
        self, api: ApiClient
    ) -> None:
        """A case without a disposition admits, and a booking without a buffer takes a day.

        Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Foxglove Trauma",
            state_code="WA",
            designation_level=DesignationLevel.LEVEL_I,
            tier_code=TierCode.TIER_1_FULL,
        )
        cycle = fx.cycle_submitted(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-10-01T13:00:00Z",
        )

        created = api.create_registry_case(
            f.registry_case_payload(
                center_id=center["id"],
                activation_tier_id=tier["id"],
                mrn="MRN-FG1",
                arrival_at="2026-07-28T09:00:00Z",
                injury_severity_score=17,
                los_hours=40.00,
                ed_disposition=OMIT,
            ),
            make_registry_abstractor_headers(),
        )
        case = validate_success(created, 201)
        assert case["ed_disposition"] == EdDisposition.ADMIT
        assert case["transfer_in_from_center_id"] is None
        assert case["abstraction_status"] == AbstractionStatus.PENDING
        assert case["inclusion_status"] == InclusionStatus.INCLUDED

        booked = api.create_surveyor_booking(
            cycle["id"],
            f.surveyor_booking_payload(
                surveyor_user_id=SURVEYOR_9,
                window_start="2026-10-01T08:00:00Z",
                window_end="2026-10-01T17:00:00Z",
            ),
            make_verification_reviewer_headers(),
        )
        booking = validate_success(booked, 201)
        assert_surveyor_booking(booking, cycle["id"])
        assert booking["travel_buffer_hours"] == DEFAULT_TRAVEL_BUFFER_HOURS

    def test_a_consult_tier_case_below_the_injury_floor_is_excluded_at_intake(
        self, api: ApiClient
    ) -> None:
        """The same severity is excluded on the consult tier and included on the full tier.

        Design: Corner/calculations/tier_three_case_below_injury_threshold_is_excluded_on_creation
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Rosewood Trauma",
            state_code="MS",
            designation_level=DesignationLevel.LEVEL_III,
        )
        consult = fx.create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_3_CONSULT,
            surgeon_response_limit_minutes=60,
            specialty_response_limit_minutes=120,
            iss_threshold=0,
        )
        full = fx.create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_1_FULL,
            surgeon_response_limit_minutes=15,
            specialty_response_limit_minutes=30,
            iss_threshold=16,
        )

        excluded = fx.create_case(
            api,
            center["id"],
            consult["id"],
            mrn="MRN-RW1",
            arrival_at="2026-07-05T14:00:00Z",
            injury_severity_score=3,
            los_hours=6.00,
            ed_disposition=EdDisposition.DISCHARGE,
        )
        assert excluded["inclusion_status"] == InclusionStatus.EXCLUDED
        assert excluded["inclusion_reason"] == InclusionReason.BELOW_INJURY_THRESHOLD
        assert excluded["effective_iss"] == 3

        included = fx.create_case(
            api,
            center["id"],
            full["id"],
            mrn="MRN-RW2",
            arrival_at="2026-07-06T14:00:00Z",
            injury_severity_score=3,
            los_hours=6.00,
            ed_disposition=EdDisposition.DISCHARGE,
        )
        assert included["inclusion_status"] == InclusionStatus.INCLUDED
        assert included["inclusion_reason"] == InclusionReason.MEETS_INCLUSION_CRITERIA

        assert_cohort_partition(
            fx.get_center(api, center["id"]), included=1, excluded=1
        )

        rates = fx.get_triage_rates(api, center["id"])
        assert rates["denominator_case_count"] == 1, (
            "only the included case sits in the rate denominator"
        )


class TestSharedCaseCreationRoles:
    """Case intake is open to two roles, and both produce the same result."""

    def test_both_declared_roles_may_open_a_case(self, api: ApiClient) -> None:
        """The manager's case and the abstractor's case are both accepted and both counted.

        Design: Corner/rbac/shared_case_creation_is_accepted_for_both_declared_roles
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Ironvale Trauma",
            state_code="OH",
            designation_level=DesignationLevel.LEVEL_I,
            tier_code=TierCode.TIER_1_FULL,
        )

        by_manager = api.create_registry_case(
            f.registry_case_payload(
                center_id=center["id"],
                activation_tier_id=tier["id"],
                mrn="MRN-IV1",
                arrival_at="2026-07-29T09:00:00Z",
                injury_severity_score=17,
                los_hours=30.00,
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        managers_case = validate_success(by_manager, 201)
        assert managers_case["inclusion_status"] == InclusionStatus.INCLUDED

        by_abstractor = api.create_registry_case(
            f.registry_case_payload(
                center_id=center["id"],
                activation_tier_id=tier["id"],
                mrn="MRN-IV2",
                arrival_at="2026-07-29T15:00:00Z",
                injury_severity_score=18,
                los_hours=34.00,
            ),
            make_registry_abstractor_headers(ABSTRACTOR_1_USER_ID),
        )
        abstractors_case = validate_success(by_abstractor, 201)
        assert abstractors_case["inclusion_status"] == InclusionStatus.INCLUDED

        assert_cohort_partition(
            fx.get_center(api, center["id"]), included=2, excluded=0
        )
        rows = get_success_data(
            api.list_registry_cases(
                make_system_admin_headers(), {"center_id": center["id"]}
            )
        )
        assert {row["id"] for row in rows} == {
            managers_case["id"],
            abstractors_case["id"],
        }
