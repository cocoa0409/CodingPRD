"""Fielding posture gates, response intake rules, the vendor budget ledger,
the completed_responses compensating pair, immediate consistency, and the
logical clock default (PRD §2.4, §2.6–§2.8, §3.3–§3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case,
    assert_response,
    create_response_payload,
    create_sample_case_payload,
    get_case,
    get_cycle,
    get_response,
    get_success_data,
    get_vendor,
    import_cases,
    import_discharges,
    make_cycle,
    make_program,
    make_provider,
    make_steward_headers,
    make_unit,
    make_vendor,
    make_vendor_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]


class TestOpenSamplingGates:
    def test_no_active_vendor_blocks_open_sampling(self, api):
        """PRD §3.3: "The cycle must currently be `DRAFT` (otherwise
        `ERR_INVALID_STATE`), and the program must have an `ACTIVE` vendor
        (otherwise `ERR_NO_ACTIVE_VENDOR`), because cases cannot be charged
        without a vendor to bill."
        PRD §3.1: "Suspension moves the vendor from `ACTIVE` to `SUSPENDED`"

        Design: Corner/validations/no_active_vendor_blocks_open_sampling
        """
        prog_ctx = setup_program(name="P-V10", with_org=False)
        get_success_data(api.suspend_vendor(prog_ctx["vendor"]["id"], ADMIN))
        cycle = make_cycle(prog_ctx["program"]["id"], label="Q1",
                           cycle_index=1)
        res = api.open_sampling(cycle["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_VENDOR)
        assert get_cycle(cycle["id"])["status"] == "DRAFT"

    def test_no_active_vendor_when_vendor_suspended(self, api):
        """PRD §3.3: "the program must have an `ACTIVE` vendor (otherwise
        `ERR_NO_ACTIVE_VENDOR`), because cases cannot be charged without a
        vendor to bill."
        PRD §3.1: "When the suspended vendor was the program's only `ACTIVE`
        vendor, `active_vendor_id` is recomputed to null."

        Design: Corner/validations/no_active_vendor_blocks_open_sampling
        """
        prog_ctx = setup_program(name="P-V10B", with_org=False)
        program = prog_ctx["program"]
        suspended = get_success_data(
            api.suspend_vendor(prog_ctx["vendor"]["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert get_success_data(api.get_program(program["id"], ADMIN))[
            "active_vendor_id"] is None

        cycle = make_cycle(program["id"], label="Q1", cycle_index=1)
        validate_error(api.open_sampling(cycle["id"], ADMIN),
                       ApiErrorId.ERR_NO_ACTIVE_VENDOR)
        assert get_cycle(cycle["id"])["status"] == "DRAFT"


class TestStartFieldingGates:
    def test_no_cases_sampled_blocks_fielding(self, api):
        """PRD §3.3: "Starting fielding moves the cycle from `SAMPLING_OPEN`
        to `FIELDING`; the cycle must be `SAMPLING_OPEN` (otherwise
        `ERR_CYCLE_NOT_SAMPLING_OPEN`) and at least one case must be in
        `SAMPLED` (otherwise `ERR_NO_CASES_SAMPLED`)."

        Design: Corner/validations/no_cases_sampled_blocks_fielding
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V11"), "SAMPLING_OPEN", discharge_count=0)
        res = api.start_fielding(ctx["cycle"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_NO_CASES_SAMPLED)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "SAMPLING_OPEN"

    def test_start_fielding_without_cases_leaves_cycle_open(self, api):
        """PRD §3.3: "Starting fielding moves the cycle from `SAMPLING_OPEN`
        to `FIELDING`; the cycle must be `SAMPLING_OPEN` (otherwise
        `ERR_CYCLE_NOT_SAMPLING_OPEN`) and at least one case must be in
        `SAMPLED` (otherwise `ERR_NO_CASES_SAMPLED`)."

        Design: Corner/validations/no_cases_sampled_blocks_fielding
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V11B"), "SAMPLING_OPEN", discharge_count=0)
        validate_error(api.start_fielding(ctx["cycle"]["id"], ADMIN),
                       ApiErrorId.ERR_NO_CASES_SAMPLED)
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "SAMPLING_OPEN"
        assert cycle["sampled_count"] == 0


class TestIntakeShapeAndUniqueness:
    def test_invalid_enum_member_rejected(self, api):
        """PRD §2.6: "5. **Request shape.** Required fields present, unknown
        fields rejected, types correct, enum members valid, dates ISO-formatted,
        composite scores within 1 to 4 (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "the `mode_assigned` (`MAIL` or `PHONE`)"

        Design: Corner/validations/invalid_enum_member_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V3", admin_mode="MIXED_MODE"),
            "SAMPLING_OPEN", discharge_count=1)
        res = api.create_sample_case(
            create_sample_case_payload(
                ctx["cycle"]["id"], ctx["discharge_ids"][0],
                mode_assigned="FAX"),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert res.status_code == 400

    def test_invalid_mode_member_rejected_before_creation(self, api):
        """PRD §2.6: "5. **Request shape.** Required fields present, unknown
        fields rejected, types correct, enum members valid, dates ISO-formatted,
        composite scores within 1 to 4 (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/invalid_enum_member_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V3B", admin_mode="MIXED_MODE"),
            "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 1,
            mrn_prefix="M", admit_date="2026-06-01",
            discharge_date="2026-06-03")
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(
                    ctx["cycle"]["id"], d_ids[0],
                    mode_assigned="FAX"),
                STEWARD),
            ApiErrorId.ERR_INVALID_REQUEST)
        data, _meta = validate_paginated(api.list_sample_cases(
            ADMIN, params={"cycle_id": ctx["cycle"]["id"]}))
        assert data == []

    def test_second_response_rejected(self, api):
        """PRD §3.4: "Intake is refused when ... the case already has a live
        response — one in `ACCEPTED`, `PENDING_REVIEW`, or `INCLUDED`
        (`ERR_RESPONSE_ALREADY_EXISTS`)."

        Design: Corner/validations/second_response_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V15"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        record_response(case_id, ctx["vendor"]["id"])

        res = api.create_response(
            create_response_payload(case_id, mode_used="MAIL",
                                    nurse_comm_score=2, doctor_comm_score=2,
                                    cleanliness_score=2,
                                    overall_rating_score=2),
            make_vendor_headers(ctx["vendor"]["id"]))
        validate_error(res, ApiErrorId.ERR_RESPONSE_ALREADY_EXISTS)
        data, _meta = validate_paginated(
            api.list_case_responses(case_id, ADMIN))
        assert len(data) == 1

    def test_one_live_response_per_case(self, api):
        """PRD §3.4: "Intake is refused when ... the case already has a live
        response — one in `ACCEPTED`, `PENDING_REVIEW`, or `INCLUDED`
        (`ERR_RESPONSE_ALREADY_EXISTS`)."

        Design: Corner/validations/second_response_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V15B"), "FIELDING", discharge_count=2)
        case_id = ctx["case_ids"][0]
        first = record_response(case_id, ctx["vendor"]["id"], score=3)
        assert first["status"] == "ACCEPTED"

        res = api.create_response(
            create_response_payload(
                case_id, mode_used="MAIL",
                nurse_comm_score=4, doctor_comm_score=4,
                cleanliness_score=4, overall_rating_score=4),
            make_vendor_headers(ctx["vendor"]["id"]))
        validate_error(res, ApiErrorId.ERR_RESPONSE_ALREADY_EXISTS)
        assert res.status_code == 409
        data, _meta = validate_paginated(
            api.list_case_responses(case_id, ADMIN))
        assert len(data) == 1
        assert data[0]["id"] == first["id"]


class TestIntakeCaseAndCycleState:
    def test_intake_on_undeliverable_case_rejected(self, api):
        """PRD §3.4: "Intake is refused when the case is not `IN_FIELD`
        (`ERR_CASE_NOT_IN_FIELD`)"
        PRD §3.4: "A `VendorOperator` marks a case undeliverable, moving it
        from `IN_FIELD` to `UNDELIVERABLE`"

        Design: Corner/validations/intake_on_undeliverable_case_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V26"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        get_success_data(api.mark_undeliverable(
            case_id, make_vendor_headers(ctx["vendor"]["id"])))
        assert get_case(case_id)["status"] == "UNDELIVERABLE"

        res = api.create_response(
            create_response_payload(case_id),
            make_vendor_headers(ctx["vendor"]["id"]))
        validate_error(res, ApiErrorId.ERR_CASE_NOT_IN_FIELD)

    def test_intake_on_undeliverable_case_cycle_still_fielding(self, api):
        """PRD §3.4: "Intake is refused when the case is not `IN_FIELD`
        (`ERR_CASE_NOT_IN_FIELD`), when the cycle is not `FIELDING`
        (`ERR_CYCLE_NOT_FIELDING`)"
        PRD §2.6: "Within this tier, cycle-posture errors are checked before
        entity-local state errors, so, for example, a closed cycle surfaces its
        `ERR_CYCLE_NOT_FIELDING` rather than a case-level error."

        Design: Corner/validations/intake_on_undeliverable_case_rejected
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V26B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        get_success_data(api.mark_undeliverable(
            case_id, make_vendor_headers(ctx["vendor"]["id"])))
        # The cycle is still FIELDING, so the case-local check is reached.
        assert get_cycle(ctx["cycle"]["id"])["status"] == "FIELDING"
        res = api.create_response(
            create_response_payload(
                case_id, mode_used="MAIL",
                nurse_comm_score=2, doctor_comm_score=2,
                cleanliness_score=2, overall_rating_score=2),
            make_vendor_headers(ctx["vendor"]["id"]))
        validate_error(res, ApiErrorId.ERR_CASE_NOT_IN_FIELD)
        assert res.status_code == 409

    def test_intake_after_close_reports_cycle_posture(self, api):
        """PRD §2.6: "Within this tier, cycle-posture errors are checked before
        entity-local state errors, so, for example, a closed cycle surfaces its
        `ERR_CYCLE_NOT_FIELDING` rather than a case-level error."
        PRD §3.4: "Intake is refused when the case is not `IN_FIELD`
        (`ERR_CASE_NOT_IN_FIELD`), when the cycle is not `FIELDING`
        (`ERR_CYCLE_NOT_FIELDING`)"

        Design: Corner/validations/intake_after_close_reports_cycle_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V25"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        assert get_cycle(ctx["cycle"]["id"])["status"] == "RECONCILIATION"
        assert get_case(case_id)["status"] == "NONRESPONSE"

        res = api.create_response(
            create_response_payload(case_id),
            make_vendor_headers(ctx["vendor"]["id"]))
        validate_error(res, ApiErrorId.ERR_CYCLE_NOT_FIELDING)

    def test_intake_after_close_posture_error_not_case_error(self, api):
        """PRD §2.6: "Within this tier, cycle-posture errors are checked before
        entity-local state errors, so, for example, a closed cycle surfaces its
        `ERR_CYCLE_NOT_FIELDING` rather than a case-level error."

        Design: Corner/validations/intake_after_close_reports_cycle_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V25B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))

        res = api.create_response(
            create_response_payload(case_id),
            make_vendor_headers(ctx["vendor"]["id"]))
        error = validate_error(res, ApiErrorId.ERR_CYCLE_NOT_FIELDING)
        assert error["error_id"] != ApiErrorId.ERR_CASE_NOT_IN_FIELD
        assert res.status_code == 409


class TestAdjudicateGatedByCyclePosture:
    def test_adjudicate_gated_by_cycle_posture(self, api):
        """PRD §3.5: "A `DataSteward` adjudicates a response in
        `PENDING_REVIEW` by supplying a `decision` of `INCLUDE` or `EXCLUDE`;
        the response must be `PENDING_REVIEW`
        (`ERR_RESPONSE_NOT_PENDING_REVIEW`) and the cycle must be
        `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`)."
        PRD §3.4: "when the calendar date of `received_at` falls after the
        cycle's `fielding_end_date`, the response is marked `is_late` and
        starts in `PENDING_REVIEW`"

        Design: Difficulty/cross_entity_state_dependency/adjudicate_gated_by_cycle_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CE1"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        set_clock("2026-09-05T00:00:00Z")
        late = record_response(case_id, ctx["vendor"]["id"])
        assert late["is_late"] is True
        assert late["status"] == "PENDING_REVIEW"
        assert get_cycle(ctx["cycle"]["id"])["status"] == "FIELDING"

        res = api.adjudicate_response(late["id"], {"decision": "INCLUDE"},
                                      STEWARD)
        validate_error(res, ApiErrorId.ERR_CYCLE_NOT_RECONCILING)
        assert get_response(late["id"])["status"] == "PENDING_REVIEW"

    def test_pending_review_response_waits_for_reconciliation(self, api):
        """PRD §2.7: "Adjudication of late responses requires
        `RECONCILIATION`"
        PRD §3.5: "the response must be `PENDING_REVIEW`
        (`ERR_RESPONSE_NOT_PENDING_REVIEW`) and the cycle must be
        `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`)."

        Design: Difficulty/cross_entity_state_dependency/adjudicate_gated_by_cycle_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CE1B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        set_clock("2026-09-05T00:00:00Z")
        late = record_response(case_id, ctx["vendor"]["id"])
        assert late["status"] == "PENDING_REVIEW"

        validate_error(
            api.adjudicate_response(late["id"], {"decision": "INCLUDE"},
                                    STEWARD),
            ApiErrorId.ERR_CYCLE_NOT_RECONCILING)
        assert get_response(late["id"])["status"] == "PENDING_REVIEW"

        # Once the cycle reaches RECONCILIATION the same call succeeds.
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        adjudicated = validate_success(
            api.adjudicate_response(late["id"], {"decision": "INCLUDE"},
                                    STEWARD),
            200)
        assert adjudicated["status"] == "INCLUDED"


class TestVendorBudgetCompensatingPair:
    def test_vendor_budget_charge_credit_conservation(self, api):
        """PRD §2.8: "The invariant is a compensating pair: a charge followed
        by its credit leaves `cycle_budget_remaining_cents` exactly unchanged,
        and at all times `cycle_budget_cents` equals
        `cycle_budget_remaining_cents` plus the sum of `CHARGED` postage."
        PRD §3.4: "The case's `billing_status` flips from `CHARGED` to
        `CREDITED`, its postage is credited back to the vendor's remaining
        budget"

        Design: Difficulty/compensating_invariant/vendor_budget_charge_credit_conservation
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CI1"), "SAMPLING_OPEN", discharge_count=1,
            postage_cost_cents=100)
        # Setup already sampled the discharge at 100c; use the case it made.
        case_ids = ctx["case_ids"]
        vendor_id = ctx["vendor"]["id"]
        assert get_vendor(vendor_id)["cycle_budget_remaining_cents"] == 99900
        get_success_data(api.start_fielding(ctx["cycle"]["id"], ADMIN))

        credited = validate_success(
            api.mark_undeliverable(case_ids[0], make_vendor_headers(vendor_id)),
            200)
        assert credited["billing_status"] == "CREDITED"
        assert credited["status"] == "UNDELIVERABLE"
        assert get_vendor(vendor_id)["cycle_budget_remaining_cents"] == 100000

    def test_charge_then_credit_leaves_no_drift(self, api):
        """PRD §2.8: "The invariant is a compensating pair: a charge followed
        by its credit leaves `cycle_budget_remaining_cents` exactly unchanged,
        and at all times `cycle_budget_cents` equals
        `cycle_budget_remaining_cents` plus the sum of `CHARGED` postage. All
        budget arithmetic is exact integer cents."

        Design: Difficulty/compensating_invariant/vendor_budget_charge_credit_conservation
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CI1B"), "FIELDING", discharge_count=1,
            postage_cost_cents=100)
        vendor_id = ctx["vendor"]["id"]
        case_id = ctx["case_ids"][0]
        # After the charge the invariant reads 100000 == 99900 + 100.
        mid = get_vendor(vendor_id)
        assert mid["cycle_budget_cents"] == (
            mid["cycle_budget_remaining_cents"] + 100)

        validate_success(
            api.mark_undeliverable(case_id, make_vendor_headers(vendor_id)),
            200)
        # After the compensating credit the invariant reads 100000 == 100000 + 0.
        final = get_vendor(vendor_id)
        assert final["cycle_budget_remaining_cents"] == 100000
        assert final["cycle_budget_cents"] == (
            final["cycle_budget_remaining_cents"] + 0)
        case = get_case(case_id)
        assert case["billing_status"] == "CREDITED"
        assert case["status"] == "UNDELIVERABLE"


class TestCompletedResponsesCompensatingPair:
    def test_completed_responses_intake_void_conservation(self, api):
        """PRD §3.5: "The intake-plus-void pair is exactly compensating: after
        both complete, `completed_responses` returns to its prior value with no
        drift, because only responses in `ACCEPTED` or `INCLUDED` ever count."
        PRD §3.5: "A `DataSteward` voids a response, supplying a `reason`, only
        while the response is `ACCEPTED` (`ERR_RESPONSE_NOT_VOIDABLE`) and only
        while the response's cycle is in `FIELDING` or `RECONCILIATION`
        (`ERR_CYCLE_LOCKED`)."

        Design: Difficulty/compensating_invariant/completed_responses_intake_void_conservation
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CI2"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]
        assert get_cycle(cycle_id)["completed_responses"] == 0

        response = record_response(case_id, ctx["vendor"]["id"])
        after_intake = get_cycle(cycle_id)
        assert after_intake["completed_responses"] == 1
        assert after_intake["response_rate"] == 100.0

        voided = validate_success(
            api.void_response(response["id"], {"reason": "duplicate submission"},
                              STEWARD),
            200)
        assert voided["status"] == "VOIDED"
        after_void = get_cycle(cycle_id)
        assert after_void["completed_responses"] == 0
        assert get_case(case_id)["status"] == "RESPONDED"

    def test_intake_plus_void_restores_prior_counter(self, api):
        """PRD §3.5: "The intake-plus-void pair is exactly compensating: after
        both complete, `completed_responses` returns to its prior value with no
        drift, because only responses in `ACCEPTED` or `INCLUDED` ever count."
        PRD §3.5: "The response moves to `VOIDED`, and the cycle's
        `completed_responses` is recomputed downward."

        Design: Difficulty/compensating_invariant/completed_responses_intake_void_conservation
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CI2B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]

        response = record_response(case_id, ctx["vendor"]["id"], score=3)
        assert get_cycle(cycle_id)["completed_responses"] == 1
        get_success_data(api.void_response(
            response["id"], {"reason": "fraudulent duplicate"}, STEWARD))

        cycle = get_cycle(cycle_id)
        assert cycle["completed_responses"] == 0
        assert cycle["response_rate"] == 0.0
        assert get_response(response["id"])["status"] == "VOIDED"
        assert get_case(case_id)["status"] == "RESPONDED"


class TestImmediateConsistency:
    def test_mutations_visible_in_same_request(self, api):
        """PRD §1: "Derived counters and rates are recomputed immediately on
        every mutation, so reading a cycle always reflects the current truth."
        PRD §3.3: "Every `SAMPLED` case transitions to `IN_FIELD`, the cycle's
        `sampled_count` is frozen to the number of cases that entered the
        field, and the `eligible_denominator` is recomputed — those cases now
        count toward it."

        Design: Corner/consistency_model/mutations_visible_in_same_request
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CM1"), "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 2,
            mrn_prefix="M")
        case_ids = import_cases(ctx["cycle"]["id"], d_ids)

        fielding = validate_success(
            api.start_fielding(ctx["cycle"]["id"], ADMIN), 200)
        assert fielding["status"] == "FIELDING"
        assert fielding["sampled_count"] == 2
        assert fielding["eligible_denominator"] == 2
        assert get_case(case_ids[0])["status"] == "IN_FIELD"

    def test_start_fielding_response_carries_updated_counters(self, api):
        """PRD §1: "Derived counters and rates are recomputed immediately on
        every mutation, so reading a cycle always reflects the current truth."
        PRD §3.3: "Every `SAMPLED` case transitions to `IN_FIELD`, the cycle's
        `sampled_count` is frozen to the number of cases that entered the
        field, and the `eligible_denominator` is recomputed — those cases now
        count toward it."

        Design: Corner/consistency_model/mutations_visible_in_same_request
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CM1B"), "FIELDING", discharge_count=2)
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "FIELDING"
        assert cycle["sampled_count"] == 2
        assert cycle["eligible_denominator"] == 2
        for case_id in ctx["case_ids"]:
            assert get_case(case_id)["status"] == "IN_FIELD"


class TestLogicalClockDefault:
    def test_logical_clock_default_is_fixed(self, api):
        """PRD §2.4: "At startup, before any explicit set, the logical clock
        reads exactly `2026-08-01T00:00:00Z`; it must never fall back to the
        host wall clock."
        PRD §3.4: "Accepted intake stamps `received_at` from the logical
        clock"; "an on-time response starts in `ACCEPTED`."

        Design: Corner/cross_cutting_layers/logical_clock_default_is_fixed
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CC2"), "FIELDING", discharge_count=1)
        # The clock is never set in this test.
        response = record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        assert response["received_at"] == "2026-08-01T00:00:00Z"
        assert response["is_late"] is False
        assert response["status"] == "ACCEPTED"

    def test_response_received_at_uses_clock_not_wall_time(self, api):
        """PRD §2.4: "The server maintains a logical clock that governs every
        temporal decision in the platform. At startup, before any explicit set,
        the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never
        fall back to the host wall clock."
        PRD §2.4: "The logical clock stamps `received_at` on response intake"

        Design: Corner/cross_cutting_layers/logical_clock_default_is_fixed
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CC2B"), "FIELDING", discharge_count=2)
        first = record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        second = record_response(ctx["case_ids"][1], ctx["vendor"]["id"])
        # Neither intake touched the clock: both stamp the fixed default.
        assert first["received_at"] == "2026-08-01T00:00:00Z"
        assert second["received_at"] == "2026-08-01T00:00:00Z"
        assert first["is_late"] is False
        assert second["is_late"] is False
