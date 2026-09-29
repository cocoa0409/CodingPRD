"""Plan, member, coverage, provider, contract and authorization configuration —
including the two opposed interval conventions."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_coverage,
    create_benefit_plan_payload,
    create_contract_payload,
    create_coverage_payload,
    create_fee_schedule_rate_payload,
    create_member_payload,
    draft_contract,
    get_contract,
    get_member,
    issue_authorization,
    revoke_authorization,
    setup_environment,
    setup_member_with_bounded_coverage,
    setup_provider_with_draft_contract,
    terminate_coverage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CLAIMS_EXAMINER,
    NETWORK_MANAGER,
    PLAN_ADMIN,
    UTILIZATION_REVIEWER,
)


class TestCoverageHalfOpenInterval:
    def test_a_segment_starting_on_an_existing_term_date_is_accepted(self, api):
        """PRD §3.2: "Because the interval is half-open, **adjacency is permitted**: a new
        segment whose `effective_date` equals an existing segment's `term_date` is accepted,
        since the existing segment excludes its own end date."
        PRD §2.6: "A **coverage segment** spans a *half-open* interval: it begins on
        `effective_date` inclusively and ends at `term_date` exclusively."

        Design: Difficulty/resource_temporal_overlap/coverage_half_open_interval_allows_adjacency_but_rejects_intersection
        """
        env = setup_member_with_bounded_coverage()
        response = api.create_coverage(
            env["member"]["id"],
            create_coverage_payload(
                effective_date="2026-06-01", cob_order="SECONDARY", other_payer_name="Other Health"
            ),
            PLAN_ADMIN,
        )
        adjacent = validate_success(response, 201)
        assert adjacent["effective_date"] == "2026-06-01"
        assert adjacent["status"] == "ACTIVE"

    def test_a_segment_that_genuinely_intersects_is_rejected(self, api):
        """PRD §3.2: "Any genuine intersection is rejected with `ERR_COVERAGE_OVERLAP`, and
        an existing open-ended segment — one whose `term_date` is null — blocks every later
        `effective_date` outright, because it contains all of them."

        Design: Difficulty/resource_temporal_overlap/coverage_half_open_interval_allows_adjacency_but_rejects_intersection
        """
        env = setup_member_with_bounded_coverage()
        add_coverage(
            env["member"]["id"],
            effective_date="2026-06-01",
            cob_order="SECONDARY",
            other_payer_name="Other Health",
        )
        response = api.create_coverage(
            env["member"]["id"],
            create_coverage_payload(
                effective_date="2026-05-31", term_date="2026-07-01", cob_order="PRIMARY"
            ),
            PLAN_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_COVERAGE_OVERLAP.value)

        _rows, meta = validate_paginated(api.list_coverages(env["member"]["id"], PLAN_ADMIN))
        assert meta["total_count"] == 2, "Only the adjacent segment joined the original"


class TestContractClosedIntervalBuffer:
    def test_a_contract_starting_the_day_after_an_existing_one_ends_conflicts(self, api):
        """PRD §3.1: "Adjacency is therefore **rejected** here — a contract starting the very
        day after an existing contract ends still conflicts, which is the opposite of the
        coverage-segment rule in §3.2."
        PRD §3.1: "The comparison is made against every existing contract for that
        provider-and-plan pair whose `status` is not `TERMINATED`, and a violation returns
        `ERR_CONTRACT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/contract_closed_interval_requires_one_clear_day_so_adjacency_conflicts
        """
        env = setup_provider_with_draft_contract()
        response = api.create_contract(
            create_contract_payload(
                env["provider"]["id"],
                env["plan"]["id"],
                effective_date="2026-07-01",
                term_date="2026-12-31",
                pricing_method="PCT_OF_FEE_SCHEDULE",
                contract_pct=0.800,
            ),
            NETWORK_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_CONTRACT_WINDOW_CONFLICT.value)
        assert get_contract(env["contract"]["id"])["status"] == "DRAFT", (
            "A DRAFT contract still blocks the window"
        )

    def test_one_full_clear_calendar_day_of_separation_is_accepted(self, api):
        """PRD §3.1: "The rule requires at least one full clear calendar day between them: a
        new contract is acceptable only when its `effective_date` falls at least two days
        after an existing contract's `term_date`, or when its own `term_date` falls at least
        two days before that existing contract's `effective_date`."

        Design: Difficulty/resource_temporal_overlap/contract_closed_interval_requires_one_clear_day_so_adjacency_conflicts
        """
        env = setup_provider_with_draft_contract()
        response = api.create_contract(
            create_contract_payload(
                env["provider"]["id"],
                env["plan"]["id"],
                effective_date="2026-07-02",
                term_date="2026-12-31",
                pricing_method="PCT_OF_FEE_SCHEDULE",
                contract_pct=0.800,
            ),
            NETWORK_MANAGER,
        )
        buffered = validate_success(response, 201)
        assert buffered["effective_date"] == "2026-07-02"
        assert buffered["status"] == "DRAFT", "Contracts are always born in DRAFT"

        _rows, meta = validate_paginated(
            api.list_contracts(NETWORK_MANAGER, params={"provider_id": env["provider"]["id"]})
        )
        assert meta["total_count"] == 2


class TestPlanAndMemberCreation:
    def test_a_plan_created_with_only_required_fields_falls_back_to_every_default(self, api):
        """PRD §3.1: "Five further settings are optional and fall back to defaults when
        omitted: `plan_year_start_date`, the ISO date on which the plan year opens, defaults
        to `2026-01-01`; `copay_office_visit_cents`, the flat copay charged instead of a
        deductible draw on office-visit procedure codes, defaults to 2500 cents — twenty-five
        dollars; `out_of_network_penalty_pct`, the allowed-amount reduction applied to
        unconstrained out-of-network pricing, defaults to 0.30; `timely_filing_days`, the
        filing window, defaults to 90 days and must be at least 1; and `cob_method`, which
        selects the coordination-of-benefits arithmetic and is either `COME_OUT_WHOLE` (the
        default) or `NON_DUPLICATION`."
        PRD §2.4: "`version` is an integer that starts at `1` when the row is created and
        increases by exactly one on every mutation the server performs on that row, including
        mutations the row suffers as a side effect of an operation aimed at some other
        resource."

        Design: Corner/entities/create_benefit_plan_applies_every_declared_default
        """
        payload = create_benefit_plan_payload(
            plan_code="DEF-1",
            name="Defaults Plan",
            deductible_individual_cents=50000,
            oop_max_individual_cents=300000,
            coinsurance_member_pct=0.20,
        )
        plan = validate_success(api.create_benefit_plan(payload, PLAN_ADMIN), 201)
        assert plan["copay_office_visit_cents"] == 2500
        assert plan["out_of_network_penalty_pct"] == pytest.approx(0.30)
        assert plan["timely_filing_days"] == 90
        assert plan["cob_method"] == "COME_OUT_WHOLE"
        assert plan["plan_year_start_date"] == "2026-01-01"
        assert plan["version"] == 1

    def test_enrolling_a_member_creates_a_zeroed_accumulator_for_the_plan_year(self, api):
        """PRD §3.2: "Enrolment has one side effect worth stating explicitly: it creates a
        **benefit accumulator** for that member covering the calendar year of the plan's
        `plan_year_start_date`, with `deductible_applied_cents`, `oop_applied_cents` and
        `remitted_claim_count` all at zero."
        PRD §3.2: "A member's `status` is not client-supplied; it begins at `ACTIVE` and is
        either `ACTIVE` or `TERMINATED`, moving to `TERMINATED` when no coverage segment of
        that member contains the current logical clock date and returning to `ACTIVE` when a
        segment that does contain it is created."

        Design: Corner/entities/create_member_auto_creates_plan_year_accumulator_at_zero
        """
        env = setup_environment(
            plan_overrides={"plan_code": "ACC-1", "name": "Accumulator Plan"},
            with_member=False,
            with_provider=False,
            coverages=None,
        )
        member = validate_success(
            api.create_member(
                create_member_payload(env["plan"]["id"], member_number="M-ACC-1"), PLAN_ADMIN
            ),
            201,
        )
        assert member["status"] == "ACTIVE"

        rows, meta = validate_paginated(api.list_accumulators(member["id"], PLAN_ADMIN))
        assert meta["total_count"] == 1
        assert rows[0]["plan_year"] == 2026
        assert rows[0]["deductible_applied_cents"] == 0
        assert rows[0]["oop_applied_cents"] == 0
        assert rows[0]["remitted_claim_count"] == 0

    def test_enrolment_without_plan_id_returns_missing_required_field(self, api):
        """PRD §2.8: "6. **Required fields** — every field the endpoint declares as required
        is present in the body; otherwise `ERR_MISSING_REQUIRED_FIELD` (400). This applies to
        every write endpoint."
        PRD §3.2: "A member is created with a `member_number` — unique across all members,
        with collisions rejected as `ERR_DUPLICATE_MEMBER_NUMBER` — and a `plan_id` naming
        the benefit plan whose constants will price and cost-share this member's claims."

        Design: Corner/entities/create_member_missing_required_plan_id_returns_missing_required_field
        """
        validate_error(
            api.create_member({"member_number": "M-MISSING-1"}, PLAN_ADMIN),
            ApiErrorId.ERR_MISSING_REQUIRED_FIELD.value,
        )
        _rows, meta = validate_paginated(api.list_members(PLAN_ADMIN))
        assert meta["total_count"] == 0

    def test_reusing_a_member_number_returns_duplicate_member_number(self, api):
        """PRD §3.2: "A member is created with a `member_number` — unique across all members,
        with collisions rejected as `ERR_DUPLICATE_MEMBER_NUMBER` — and a `plan_id` naming
        the benefit plan whose constants will price and cost-share this member's claims."

        Design: Corner/validations/reusing_a_member_number_returns_duplicate_member_number
        """
        env = setup_environment(
            plan_overrides={"plan_code": "VAL-2", "name": "Validation Plan Two"},
            member_overrides={"member_number": "M-VAL-2"},
            coverages=None,
            with_provider=False,
        )
        validate_error(
            api.create_member(
                create_member_payload(env["plan"]["id"], member_number="M-VAL-2"), PLAN_ADMIN
            ),
            ApiErrorId.ERR_DUPLICATE_MEMBER_NUMBER.value,
        )
        _rows, meta = validate_paginated(
            api.list_members(PLAN_ADMIN, params={"plan_id": env["plan"]["id"]})
        )
        assert meta["total_count"] == 1


class TestCoverageAndRateConfiguration:
    def test_a_cob_order_outside_the_declared_set_returns_invalid_field_value(self, api):
        """PRD §2.8: "7. **Field well-formedness** — reported as `ERR_INVALID_FIELD_VALUE`
        (400) on every write endpoint. A value is well formed when: enum members belong to
        their declared set; every units figure is at least 1; every cents figure is at least
        0; every percentage lies within its declared bounds; dates are ISO `YYYY-MM-DD`; an
        interval's end is not earlier than its start; `contract_pct` is present when
        `pricing_method` is `PCT_OF_FEE_SCHEDULE` and `case_rate_cents` is present when
        `pricing_method` is `CASE_RATE`; `secondary_code` is present when `edit_type` is
        `BUNDLING` or `MUTUALLY_EXCLUSIVE`; and `max_units` is present when `edit_type` is
        `UNITS_LIMIT`."
        PRD §3.2: "A `PlanAdmin` adds a segment to a member by supplying its `effective_date`
        and its `cob_order` — this plan's position in the coordination-of-benefits order, one
        of `PRIMARY`, `SECONDARY` or `TERTIARY`."

        Design: Corner/entities/coverage_with_invalid_cob_order_enum_returns_invalid_field_value
        """
        env = setup_environment(
            plan_overrides={"plan_code": "TC-1", "name": "Type Constraint Plan"},
            member_overrides={"member_number": "M-TC-1"},
            coverages=None,
            with_provider=False,
        )
        validate_error(
            api.create_coverage(
                env["member"]["id"],
                create_coverage_payload(effective_date="2026-01-01", cob_order="QUATERNARY"),
                PLAN_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_FIELD_VALUE.value,
        )
        _rows, meta = validate_paginated(api.list_coverages(env["member"]["id"], PLAN_ADMIN))
        assert meta["total_count"] == 0

    def test_republishing_the_same_code_and_effective_date_returns_duplicate_fee_rate(
        self, api
    ):
        """PRD §3.1: "A plan may hold many rates for the same procedure code with different
        effective dates — that is how a mid-year fee schedule revision is expressed — but the
        combination of plan, `procedure_code` and `effective_date` must be unique; a repeat
        is rejected with `ERR_DUPLICATE_FEE_RATE`."

        Design: Corner/validations/republishing_the_same_plan_code_and_effective_date_returns_duplicate_fee_rate
        """
        env = setup_environment(
            plan_overrides={"plan_code": "VAL-3", "name": "Validation Plan Three"},
            rates=[("73721", 40000, "2026-01-01")],
            with_member=False,
            with_provider=False,
            coverages=None,
        )
        validate_error(
            api.create_fee_schedule_rate(
                env["plan"]["id"],
                create_fee_schedule_rate_payload(
                    procedure_code="73721", allowed_amount_cents=44000, effective_date="2026-01-01"
                ),
                NETWORK_MANAGER,
            ),
            ApiErrorId.ERR_DUPLICATE_FEE_RATE.value,
        )
        revision = validate_success(
            api.create_fee_schedule_rate(
                env["plan"]["id"],
                create_fee_schedule_rate_payload(
                    procedure_code="73721", allowed_amount_cents=44000, effective_date="2026-02-01"
                ),
                NETWORK_MANAGER,
            ),
            201,
        )
        assert revision["effective_date"] == "2026-02-01"

        _rows, meta = validate_paginated(
            api.list_fee_schedule_rates(
                env["plan"]["id"], NETWORK_MANAGER, params={"procedure_code": "73721"}
            )
        )
        assert meta["total_count"] == 2


class TestContractAndAuthorizationStateGuards:
    def test_a_percent_contract_without_contract_pct_returns_invalid_field_value(self, api):
        """PRD §3.1: "A percent-of-fee-schedule contract must carry `contract_pct`, a
        multiplier that must be greater than 0 and no greater than 5; a case-rate contract
        must carry `case_rate_cents`, a flat claim-level allowed amount of zero or more.
        Supplying neither companion field, or the wrong one for the chosen method, is an
        `ERR_INVALID_FIELD_VALUE` rejection."

        Design: Corner/validations/contract_without_contract_pct_returns_invalid_field_value
        """
        env = setup_environment(
            plan_overrides={"plan_code": "VAL-7", "name": "Validation Plan Seven"},
            provider_overrides={"npi": "3000000007", "name": "VAL7 Group"},
            with_member=False,
            coverages=None,
        )
        validate_error(
            api.create_contract(
                create_contract_payload(
                    env["provider"]["id"],
                    env["plan"]["id"],
                    effective_date="2026-01-01",
                    term_date="2026-06-30",
                    pricing_method="PCT_OF_FEE_SCHEDULE",
                    contract_pct=None,
                ),
                NETWORK_MANAGER,
            ),
            ApiErrorId.ERR_INVALID_FIELD_VALUE.value,
        )
        case_rate = validate_success(
            api.create_contract(
                create_contract_payload(
                    env["provider"]["id"],
                    env["plan"]["id"],
                    effective_date="2026-01-01",
                    term_date="2026-06-30",
                    pricing_method="CASE_RATE",
                    case_rate_cents=50000,
                ),
                NETWORK_MANAGER,
            ),
            201,
        )
        assert case_rate["pricing_method"] == "CASE_RATE"

        _rows, meta = validate_paginated(
            api.list_contracts(NETWORK_MANAGER, params={"provider_id": env["provider"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_activating_an_already_active_contract_returns_contract_not_draft(self, api):
        """PRD §3.1: "Activation moves a contract `DRAFT → ACTIVE` and is refused with
        `ERR_CONTRACT_NOT_DRAFT` on a contract in any other status; the engine also confirms
        at activation that the method's companion field is populated — a percent-of-fee-schedule
        contract must have a non-null `contract_pct`, a case-rate contract a non-null
        `case_rate_cents`."

        Design: Corner/state_machines/activate_an_already_active_contract_returns_contract_not_draft
        """
        env = setup_environment(
            plan_overrides={"plan_code": "SM-3", "name": "State Machine Plan Three"},
            provider_overrides={"npi": "2000000009", "name": "SM3 Group"},
            with_member=False,
            coverages=None,
        )
        contract = draft_contract(
            env["provider"]["id"],
            env["plan"]["id"],
            effective_date="2026-01-01",
            term_date="2026-12-31",
            pricing_method="PCT_OF_FEE_SCHEDULE",
            contract_pct=0.900,
        )
        activated = activate_contract(contract["id"])
        assert activated["status"] == "ACTIVE"

        validate_error(
            api.activate_contract(contract["id"], NETWORK_MANAGER),
            ApiErrorId.ERR_CONTRACT_NOT_DRAFT.value,
        )
        assert get_contract(contract["id"])["status"] == "ACTIVE"

    def test_terminating_a_draft_contract_returns_contract_not_active(self, api):
        """PRD §3.1: "Termination moves a contract `ACTIVE → TERMINATED`, overwrites
        `term_date` with the supplied date, and is refused with `ERR_CONTRACT_NOT_ACTIVE`
        from any other status; claims adjudicated afterwards fall back to the
        `FEE_SCHEDULE_PRICED` variant, which reintroduces the out-of-network penalty for
        out-of-network providers."
        PRD §3.1: "Contract listings may be narrowed by `provider_id`, by `plan_id`, or by
        `status`."

        Design: Corner/endpoints/terminating_a_draft_contract_returns_contract_not_active
        """
        env = setup_environment(
            plan_overrides={"plan_code": "EP-4", "name": "Endpoint Plan Four"},
            provider_overrides={"npi": "4000000004", "name": "EP4 Group"},
            with_member=False,
            coverages=None,
        )
        contract = draft_contract(
            env["provider"]["id"],
            env["plan"]["id"],
            effective_date="2026-01-01",
            term_date="2026-06-30",
            pricing_method="PCT_OF_FEE_SCHEDULE",
            contract_pct=0.900,
        )
        assert contract["status"] == "DRAFT"

        validate_error(
            api.terminate_contract(contract["id"], {"term_date": "2026-04-01"}, NETWORK_MANAGER),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
        )
        after = get_contract(contract["id"])
        assert after["status"] == "DRAFT"
        assert after["term_date"] == "2026-06-30", "The refused termination changed nothing"

        rows, meta = validate_paginated(
            api.list_contracts(
                NETWORK_MANAGER, params={"plan_id": env["plan"]["id"], "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == contract["id"]

    def test_revoking_an_already_revoked_authorization_is_refused(self, api):
        """PRD §3.3: "A `UtilizationReviewer` may revoke an authorization whose `status` is
        `ACTIVE` or `PARTIALLY_CONSUMED`, applying `ACTIVE → REVOKED` or
        `PARTIALLY_CONSUMED → REVOKED`; `REVOKED` is terminal, and attempting to revoke one
        that is already `EXHAUSTED` or `REVOKED` is refused with
        `ERR_AUTHORIZATION_NOT_REVOCABLE`."
        PRD §3.3: "Revocation does **not** release units that have already been consumed:
        `units_consumed` is frozen at whatever value it held."

        Design: Corner/state_machines/revoke_an_already_revoked_authorization_returns_authorization_not_revocable
        """
        env = setup_environment(
            plan_overrides={"plan_code": "SM-4", "name": "State Machine Plan Four"},
            provider_overrides={"npi": "2000000010", "name": "SM4 Imaging"},
            member_overrides={"member_number": "M-SM-4"},
        )
        authorization = issue_authorization(
            env["member"]["id"],
            env["provider"]["id"],
            procedure_code="73721",
            authorized_units=4,
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        )
        revoked = revoke_authorization(authorization["id"])
        assert revoked["status"] == "REVOKED"

        validate_error(
            api.revoke_authorization(authorization["id"], UTILIZATION_REVIEWER),
            ApiErrorId.ERR_AUTHORIZATION_NOT_REVOCABLE.value,
        )
        assert validate_success(
            api.get_authorization(authorization["id"], UTILIZATION_REVIEWER)
        )["units_consumed"] == 0

    def test_terminating_an_already_terminated_coverage_is_refused(self, api):
        """PRD §3.2: "The `PlanAdmin` supplies the `term_date` at which the segment closes;
        that date must not be earlier than the segment's `effective_date`, and an earlier one
        is refused as `ERR_INVALID_FIELD_VALUE`; a segment already in `TERMINATED` cannot be
        terminated again — that attempt returns `ERR_COVERAGE_ALREADY_TERMINATED`."
        PRD §3.2: "Fifth, as a separate direct effect of the termination, the member's
        `status` becomes `TERMINATED` when no remaining coverage segment of that member
        contains the current logical clock date."

        Design: Corner/state_machines/terminate_an_already_terminated_coverage_returns_coverage_already_terminated
        """
        env = setup_environment(
            plan_overrides={"plan_code": "SM-5", "name": "State Machine Plan Five"},
            member_overrides={"member_number": "M-SM-5"},
            with_provider=False,
        )
        first = terminate_coverage(env["coverage"]["id"], "2026-02-15")
        assert first["status"] == "TERMINATED"
        assert first["term_date"] == "2026-02-15"

        validate_error(
            api.terminate_coverage(
                env["coverage"]["id"], {"term_date": "2026-04-01"}, PLAN_ADMIN
            ),
            ApiErrorId.ERR_COVERAGE_ALREADY_TERMINATED.value,
        )
        rows = validate_success(api.list_coverages(env["member"]["id"], PLAN_ADMIN))
        assert rows[0]["term_date"] == "2026-02-15", "The second date was not applied"
        assert get_member(env["member"]["id"])["status"] == "TERMINATED"


class TestConfigurationReads:
    def test_configuration_rows_read_back_by_id_and_through_their_filtered_lists(self, api):
        """PRD §3.2: "Members may be listed and narrowed by `plan_id`, by `member_number`, or
        by `status`."
        PRD §3.1: "When the rates of a plan are listed they may be narrowed by
        `procedure_code`."
        PRD §3.3: "Authorizations may be listed and narrowed by `member_id`, `provider_id`,
        `procedure_code` or `status`."
        PRD §3.2: "A member's coverage segments may be listed and narrowed by `status`."

        Design: Corner/endpoints/configuration_resources_are_readable_by_id_and_through_filtered_lists
        """
        env = setup_environment(
            plan_overrides={
                "plan_code": "EP-5",
                "name": "Endpoint Plan Five",
                "deductible_individual_cents": 50000,
                "oop_max_individual_cents": 300000,
                "coinsurance_member_pct": 0.20,
            },
            provider_overrides={"npi": "4000000005", "name": "EP5 Imaging"},
            member_overrides={"member_number": "M-EP-5"},
            rates=[("73721", 40000, "2026-01-01")],
        )
        authorization = issue_authorization(
            env["member"]["id"],
            env["provider"]["id"],
            procedure_code="73721",
            authorized_units=4,
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        )

        plan = validate_success(api.get_benefit_plan(env["plan"]["id"], CLAIMS_EXAMINER))
        assert plan["plan_code"] == "EP-5"
        assert plan["deductible_individual_cents"] == 50000

        provider = validate_success(api.get_provider(env["provider"]["id"], CLAIMS_EXAMINER))
        assert provider["npi"] == "4000000005"
        assert provider["network_status"] == "IN_NETWORK"

        member = validate_success(api.get_member(env["member"]["id"], CLAIMS_EXAMINER))
        assert member["member_number"] == "M-EP-5"
        assert member["plan_id"] == env["plan"]["id"]

        members, members_meta = validate_paginated(
            api.list_members(CLAIMS_EXAMINER, params={"plan_id": env["plan"]["id"]})
        )
        assert members_meta["total_count"] == 1
        assert members[0]["id"] == env["member"]["id"]

        coverages, coverages_meta = validate_paginated(
            api.list_coverages(env["member"]["id"], CLAIMS_EXAMINER)
        )
        assert coverages_meta["total_count"] == 1
        assert coverages[0]["id"] == env["coverage"]["id"]

        rates, rates_meta = validate_paginated(
            api.list_fee_schedule_rates(
                env["plan"]["id"], CLAIMS_EXAMINER, params={"procedure_code": "73721"}
            )
        )
        assert rates_meta["total_count"] == 1
        assert rates[0]["id"] == env["rates"][0]["id"]

        authorizations, auth_meta = validate_paginated(
            api.list_authorizations(
                CLAIMS_EXAMINER,
                params={"member_id": env["member"]["id"], "provider_id": env["provider"]["id"]},
            )
        )
        assert auth_meta["total_count"] == 1
        assert authorizations[0]["id"] == authorization["id"]
