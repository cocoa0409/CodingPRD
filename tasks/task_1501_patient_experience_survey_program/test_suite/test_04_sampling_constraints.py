"""Sampling-time guard rail: state beats fiscal, safety beats referential, and
each individual case-creation rule (PRD §2.6, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_sample_case_payload,
    get_success_data,
    get_vendor,
    import_discharges,
    make_cycle,
    make_program,
    make_provider,
    make_steward_headers,
    make_unit,
    make_vendor,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]


def _sampling_open_ctx(name, vendor_budget_cents=100000, admin_mode="MAIL_ONLY",
                       discharge_count=1, **cycle_overrides):
    return setup_cycle_in_state(
        setup_program(name=name, admin_mode=admin_mode,
                      vendor_budget_cents=vendor_budget_cents),
        "SAMPLING_OPEN", discharge_count=discharge_count, **cycle_overrides)


class TestPriorityPairStateBeatsFiscal:
    def test_state_beats_fiscal_on_sample_create(self, api):
        """PRD §2.6: "Every mutation request passes through a fixed validation
        pipeline. When several checks would fail, the earliest check in this
        order produces the error:" with "7. **State-machine preconditions.**"
        preceding "12. **Fiscal.** The vendor budget check comes last
        (`ERR_VENDOR_BUDGET_EXCEEDED`)."
        PRD §3.3: "the cycle must be `SAMPLING_OPEN`
        (`ERR_CYCLE_NOT_SAMPLING_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_sample_create
        """
        prog_ctx = setup_program(name="P-PP1", vendor_budget_cents=100)
        program = prog_ctx["program"]
        cycle_a = make_cycle(program["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cycle_a["id"], ADMIN))
        d_ids = import_discharges(
            program["id"], prog_ctx["unit"]["id"], prog_ctx["provider"]["id"],
            2, mrn_prefix="M")
        # Drain the vendor's entire 100c budget with cycle A's first case.
        validate_success(api.create_sample_case(
            create_sample_case_payload(cycle_a["id"], d_ids[0],
                                       postage_cost_cents=100),
            STEWARD), 201)
        assert get_vendor(prog_ctx["vendor"]["id"])[
            "cycle_budget_remaining_cents"] == 0
        cycle_b = make_cycle(
            program["id"], label="Q2", cycle_index=2,
            discharge_window_start="2026-07-01",
            discharge_window_end="2026-07-31",
            fielding_start_date="2026-09-01", fielding_end_date="2026-09-30")
        assert cycle_b["status"] == "DRAFT"

        res = api.create_sample_case(
            create_sample_case_payload(cycle_b["id"], d_ids[1],
                                       postage_cost_cents=50),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_CYCLE_NOT_SAMPLING_OPEN)
        data, _meta = validate_paginated(api.list_sample_cases(
            ADMIN, params={"discharge_id": d_ids[1]}))
        assert data == []

    def test_state_error_not_fiscal_error_reported(self, api):
        """PRD §2.6: "When several checks would fail, the earliest check in
        this order produces the error:" with "7. **State-machine
        preconditions.**" preceding "12. **Fiscal.** The vendor budget check
        comes last (`ERR_VENDOR_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_sample_create
        """
        prog_ctx = setup_program(name="P-PP1B", vendor_budget_cents=100)
        program = prog_ctx["program"]
        cycle_a = make_cycle(program["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cycle_a["id"], ADMIN))
        d_ids = import_discharges(
            program["id"], prog_ctx["unit"]["id"], prog_ctx["provider"]["id"],
            2, mrn_prefix="M")
        get_success_data(api.create_sample_case(
            create_sample_case_payload(cycle_a["id"], d_ids[0],
                                       postage_cost_cents=100),
            STEWARD))
        cycle_b = make_cycle(
            program["id"], label="Q2", cycle_index=2,
            discharge_window_start="2026-07-01",
            discharge_window_end="2026-07-31",
            fielding_start_date="2026-09-01", fielding_end_date="2026-09-30")

        res = api.create_sample_case(
            create_sample_case_payload(cycle_b["id"], d_ids[1],
                                       postage_cost_cents=50),
            STEWARD)
        error = validate_error(res, ApiErrorId.ERR_CYCLE_NOT_SAMPLING_OPEN)
        assert error["error_id"] != ApiErrorId.ERR_VENDOR_BUDGET_EXCEEDED
        assert res.status_code == 409


class TestPriorityPairSafetyBeatsReferential:
    def _two_programs_with_excluded_discharge(self, api):
        p1 = setup_program(name="P-PP2-A")
        cycle = make_cycle(p1["program"]["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cycle["id"], ADMIN))
        p2_program = make_program(name="P-PP2-B")
        p2_unit = make_unit(p2_program["id"], name="Unit 9", unit_code="U9")
        p2_provider = make_provider(p2_program["id"], full_name="Dr B",
                                    npi="NPI9")
        d2_ids = import_discharges(
            p2_program["id"], p2_unit["id"], p2_provider["id"], 1,
            mrn_prefix="X", discharge_disposition="EXPIRED", age_years=80)
        return p1, cycle, d2_ids

    def test_safety_beats_referential_on_sample_create(self, api):
        """PRD §2.6: "Every mutation request passes through a fixed validation
        pipeline. When several checks would fail, the earliest check in this
        order produces the error:" with "8. **Patient protection.** Only
        `ELIGIBLE` discharges may be sampled (`ERR_DISCHARGE_NOT_ELIGIBLE`)."
        preceding "9. **Referential scope.** Body-referenced resources belong
        to the same program aggregate (`ERR_CROSS_PROGRAM_REFERENCE`,
        `ERR_UNIT_RESPONSE_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_sample_create
        """
        _p1, cycle, d2_ids = self._two_programs_with_excluded_discharge(api)
        res = api.create_sample_case(
            create_sample_case_payload(cycle["id"], d2_ids[0]),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_NOT_ELIGIBLE)
        assert res.status_code == 422

    def test_excluded_cross_program_discharge_reports_safety(self, api):
        """PRD §2.6: "8. **Patient protection.** Only `ELIGIBLE` discharges may
        be sampled (`ERR_DISCHARGE_NOT_ELIGIBLE`)." precedes "9. **Referential
        scope.** Body-referenced resources belong to the same program aggregate
        (`ERR_CROSS_PROGRAM_REFERENCE`, `ERR_UNIT_RESPONSE_MISMATCH`)."
        PRD §3.2: "A discharge with any reasons becomes `EXCLUDED`"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_sample_create
        """
        _p1, cycle, d2_ids = self._two_programs_with_excluded_discharge(api)
        discharge = get_success_data(api.get_discharge(d2_ids[0], ADMIN))
        assert discharge["status"] == "EXCLUDED"
        assert discharge["exclusion_reasons"] == ["EXPIRED"]

        res = api.create_sample_case(
            create_sample_case_payload(cycle["id"], d2_ids[0]),
            STEWARD)
        error = validate_error(res, ApiErrorId.ERR_DISCHARGE_NOT_ELIGIBLE)
        assert error["error_id"] != ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE
        assert res.status_code == 422


class TestCrossProgramReference:
    def test_cross_program_reference_single_failure(self, api):
        """PRD §3.3: "the discharge must belong to the same program as the
        cycle (`ERR_CROSS_PROGRAM_REFERENCE`)"

        Design: Corner/validations/cross_program_reference_single_failure
        """
        p1 = setup_program(name="P-V4A")
        cycle = make_cycle(p1["program"]["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cycle["id"], ADMIN))
        p2_program = make_program(name="P-V4B")
        p2_unit = make_unit(p2_program["id"], name="Unit 9", unit_code="U9")
        p2_provider = make_provider(p2_program["id"], full_name="Dr B",
                                    npi="NPI9")
        # This discharge is fully ELIGIBLE — only the referential rule fails.
        d2_ids = import_discharges(
            p2_program["id"], p2_unit["id"], p2_provider["id"], 1,
            mrn_prefix="X")
        assert get_success_data(api.get_discharge(d2_ids[0], ADMIN))[
            "status"] == "ELIGIBLE"

        res = api.create_sample_case(
            create_sample_case_payload(cycle["id"], d2_ids[0]),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)
        assert res.status_code == 400

    def test_cross_program_discharge_rejected_with_no_case_created(self, api):
        """PRD §3.3: "the discharge must belong to the same program as the
        cycle (`ERR_CROSS_PROGRAM_REFERENCE`)"
        PRD §2.6: "9. **Referential scope.** Body-referenced resources belong
        to the same program aggregate (`ERR_CROSS_PROGRAM_REFERENCE`,
        `ERR_UNIT_RESPONSE_MISMATCH`)."

        Design: Corner/validations/cross_program_reference_single_failure
        """
        p1 = setup_program(name="P-V4C")
        cycle = make_cycle(p1["program"]["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cycle["id"], ADMIN))
        p2_program = make_program(name="P-V4D")
        p2_unit = make_unit(p2_program["id"], name="Unit 9", unit_code="U9")
        p2_provider = make_provider(p2_program["id"], full_name="Dr B",
                                    npi="NPI9")
        d2_ids = import_discharges(
            p2_program["id"], p2_unit["id"], p2_provider["id"], 1,
            mrn_prefix="X")

        validate_error(
            api.create_sample_case(
                create_sample_case_payload(cycle["id"], d2_ids[0]), STEWARD),
            ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)
        data, _meta = validate_paginated(api.list_sample_cases(
            ADMIN, params={"discharge_id": d2_ids[0]}))
        assert data == []


class TestModeAllowedByAdminMode:
    def _mail_only_and_mixed_programs(self, api):
        p1 = setup_program(name="P-V5A", admin_mode="MAIL_ONLY")
        cy1 = make_cycle(p1["program"]["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cy1["id"], ADMIN))
        d1 = import_discharges(
            p1["program"]["id"], p1["unit"]["id"], p1["provider"]["id"], 1,
            mrn_prefix="M")
        p2 = setup_program(name="P-V5B", admin_mode="MIXED_MODE")
        cy2 = make_cycle(p2["program"]["id"], label="Q1", cycle_index=1)
        get_success_data(api.open_sampling(cy2["id"], ADMIN))
        d2 = import_discharges(
            p2["program"]["id"], p2["unit"]["id"], p2["provider"]["id"], 1,
            mrn_prefix="N")
        return (p1, cy1, d1), (p2, cy2, d2)

    def test_mode_not_allowed_by_admin_mode(self, api):
        """PRD §3.1: "The administration mode constrains which survey mode may
        be assigned to sample cases later: a `MAIL_ONLY` program permits only
        `MAIL` cases, a `PHONE_ONLY` program permits only `PHONE` cases, and a
        `MIXED_MODE` program permits either."
        PRD §3.3: "the `mode_assigned` must be permitted by the program's
        `admin_mode` (`ERR_MODE_NOT_ALLOWED`)"

        Design: Corner/validations/mode_not_allowed_by_admin_mode
        """
        (_p1, cy1, d1), (_p2, cy2, d2) = self._mail_only_and_mixed_programs(api)
        res = api.create_sample_case(
            create_sample_case_payload(cy1["id"], d1[0], mode_assigned="PHONE"),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_MODE_NOT_ALLOWED)
        assert res.status_code == 422

        created = validate_success(
            api.create_sample_case(
                create_sample_case_payload(cy2["id"], d2[0],
                                           mode_assigned="PHONE"),
                STEWARD),
            201)
        assert created["mode_assigned"] == "PHONE"

    def test_phone_case_rejected_in_mail_only_program_only(self, api):
        """PRD §3.1: "a `MAIL_ONLY` program permits only `MAIL` cases, a
        `PHONE_ONLY` program permits only `PHONE` cases, and a `MIXED_MODE`
        program permits either."

        Design: Corner/validations/mode_not_allowed_by_admin_mode
        """
        (_p1, cy1, d1), (_p2, cy2, d2) = self._mail_only_and_mixed_programs(api)
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(cy1["id"], d1[0],
                                           mode_assigned="PHONE"),
                STEWARD),
            ApiErrorId.ERR_MODE_NOT_ALLOWED)
        data, _meta = validate_paginated(api.list_sample_cases(
            ADMIN, params={"cycle_id": cy1["id"]}))
        assert data == []
        created = validate_success(
            api.create_sample_case(
                create_sample_case_payload(cy2["id"], d2[0],
                                           mode_assigned="PHONE"),
                STEWARD),
            201)
        assert created["mode_assigned"] == "PHONE"


class TestSamplingWindow:
    def test_discharge_outside_sampling_window(self, api):
        """PRD §3.3: "the `discharge_date` must fall within the cycle's
        sampling window, both boundaries inclusive
        (`ERR_DISCHARGE_OUTSIDE_WINDOW`)"

        Design: Corner/validations/discharge_outside_sampling_window
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V6"), "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 1,
            mrn_prefix="M", admit_date="2026-07-01",
            discharge_date="2026-07-05")
        res = api.create_sample_case(
            create_sample_case_payload(ctx["cycle"]["id"], d_ids[0]), STEWARD)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_OUTSIDE_WINDOW)
        assert res.status_code == 422

    def test_discharge_window_boundaries_are_inclusive(self, api):
        """PRD §3.3: "the `discharge_date` must fall within the cycle's
        sampling window, both boundaries inclusive
        (`ERR_DISCHARGE_OUTSIDE_WINDOW`)"

        Design: Corner/validations/discharge_outside_sampling_window
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V6B"), "SAMPLING_OPEN", discharge_count=0)
        # discharge_date exactly on the window end (inclusive) is samplable;
        # admit two days earlier to keep the stay overnight.
        d_in = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 1,
            mrn_prefix="IN", admit_date="2026-06-28",
            discharge_date="2026-06-30")
        created = validate_success(
            api.create_sample_case(
                create_sample_case_payload(ctx["cycle"]["id"], d_in[0]),
                STEWARD),
            201)
        assert created["status"] == "SAMPLED"
        # One day past the window end is outside it.
        d_out = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 1,
            mrn_prefix="OUT", admit_date="2026-06-30",
            discharge_date="2026-07-02")
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(ctx["cycle"]["id"], d_out[0]),
                STEWARD),
            ApiErrorId.ERR_DISCHARGE_OUTSIDE_WINDOW)


class TestDischargeAlreadySampled:
    def test_discharge_already_sampled(self, api):
        """PRD §3.3: "the discharge must not already be referenced by a sample
        case in any non-`VOIDED` cycle (`ERR_DISCHARGE_ALREADY_SAMPLED`)"

        Design: Corner/validations/discharge_already_sampled
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V7"), "SAMPLING_OPEN", discharge_count=1)
        cycle_id = ctx["cycle"]["id"]
        d_id = ctx["discharge_ids"][0]
        # Setup already sampled d_id into cycle_id; the second attempt is rejected.
        res = api.create_sample_case(
            create_sample_case_payload(cycle_id, d_id), STEWARD)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_ALREADY_SAMPLED)

    def test_discharge_already_sampled_in_another_cycle(self, api):
        """PRD §3.3: "the discharge must not already be referenced by a sample
        case in any non-`VOIDED` cycle (`ERR_DISCHARGE_ALREADY_SAMPLED`)"

        Design: Corner/validations/discharge_already_sampled
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V7B"), "SAMPLING_OPEN", discharge_count=1)
        program = ctx["program"]
        d_id = ctx["discharge_ids"][0]
        # Setup already sampled d_id into ctx["cycle"]; a second, non-VOIDED
        # cycle of the same program rejects the re-sample.
        cycle2 = make_cycle(
            program["id"], label="Q2", cycle_index=2,
            discharge_window_start="2026-06-01",
            discharge_window_end="2026-06-30",
            fielding_start_date="2026-09-01", fielding_end_date="2026-09-30")
        get_success_data(api.open_sampling(cycle2["id"], ADMIN))
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(cycle2["id"], d_id), STEWARD),
            ApiErrorId.ERR_DISCHARGE_ALREADY_SAMPLED)
        data, _meta = validate_paginated(api.list_sample_cases(
            ADMIN, params={"discharge_id": d_id}))
        assert len(data) == 1


class TestSampleTargetReached:
    def test_sample_target_reached(self, api):
        """PRD §3.3: "the cycle must have remaining sample capacity, where the
        count of its cases in `SAMPLED`, `IN_FIELD`, `RESPONDED`,
        `NONRESPONSE`, or `UNDELIVERABLE` has not yet reached
        `target_sample_size` (`ERR_SAMPLE_TARGET_REACHED`)"

        Design: Corner/validations/sample_target_reached
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V8"), "SAMPLING_OPEN", discharge_count=0,
            target_sample_size=1)
        cycle_id = ctx["cycle"]["id"]
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 2,
            mrn_prefix="M", admit_date="2026-06-01",
            discharge_date="2026-06-03")
        validate_success(
            api.create_sample_case(
                create_sample_case_payload(cycle_id, d_ids[0]),
                STEWARD),
            201)

        res = api.create_sample_case(
            create_sample_case_payload(cycle_id, d_ids[1]),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_SAMPLE_TARGET_REACHED)
        assert res.status_code == 422

    def test_sample_target_boundary_is_at_capacity(self, api):
        """PRD §3.3: "the cycle must have remaining sample capacity, where the
        count of its cases in `SAMPLED`, `IN_FIELD`, `RESPONDED`,
        `NONRESPONSE`, or `UNDELIVERABLE` has not yet reached
        `target_sample_size` (`ERR_SAMPLE_TARGET_REACHED`)"

        Design: Corner/validations/sample_target_reached
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V8B"), "SAMPLING_OPEN", discharge_count=0,
            target_sample_size=2)
        cycle_id = ctx["cycle"]["id"]
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 3,
            mrn_prefix="M", admit_date="2026-06-01",
            discharge_date="2026-06-03")
        # Cases 1 and 2 fit; case 3 would exceed target 2.
        validate_success(
            api.create_sample_case(
                create_sample_case_payload(cycle_id, d_ids[0]),
                STEWARD),
            201)
        validate_success(
            api.create_sample_case(
                create_sample_case_payload(cycle_id, d_ids[1]),
                STEWARD),
            201)
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(cycle_id, d_ids[2]),
                STEWARD),
            ApiErrorId.ERR_SAMPLE_TARGET_REACHED)


class TestVendorBudgetExceeded:
    def test_vendor_budget_exceeded_single(self, api):
        """PRD §3.3: "the `postage_cost_cents` must not exceed the vendor's
        `cycle_budget_remaining_cents` (`ERR_VENDOR_BUDGET_EXCEEDED`)"

        Design: Corner/validations/vendor_budget_exceeded_single
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V9", vendor_budget_cents=100),
            "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 1,
            mrn_prefix="M", admit_date="2026-06-01",
            discharge_date="2026-06-03")
        res = api.create_sample_case(
            create_sample_case_payload(
                ctx["cycle"]["id"], d_ids[0],
                postage_cost_cents=150),
            STEWARD)
        validate_error(res, ApiErrorId.ERR_VENDOR_BUDGET_EXCEEDED)
        assert res.status_code == 402
        assert get_vendor(ctx["vendor"]["id"])[
            "cycle_budget_remaining_cents"] == 100

    def test_vendor_budget_boundary_at_exact_remaining(self, api):
        """PRD §3.3: "the `postage_cost_cents` must not exceed the vendor's
        `cycle_budget_remaining_cents` (`ERR_VENDOR_BUDGET_EXCEEDED`)"
        PRD §2.8: "All budget arithmetic is exact integer cents."

        Design: Corner/validations/vendor_budget_exceeded_single
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V9B", vendor_budget_cents=100),
            "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 2,
            mrn_prefix="M", admit_date="2026-06-01",
            discharge_date="2026-06-03")
        # postage exactly equal to the remaining budget does not exceed it.
        created = validate_success(
            api.create_sample_case(
                create_sample_case_payload(
                    ctx["cycle"]["id"], d_ids[0],
                    postage_cost_cents=100),
                STEWARD),
            201)
        assert created["billing_status"] == "CHARGED"
        assert get_vendor(ctx["vendor"]["id"])[
            "cycle_budget_remaining_cents"] == 0
        # The next case exceeds the now-zero remaining budget.
        validate_error(
            api.create_sample_case(
                create_sample_case_payload(
                    ctx["cycle"]["id"], d_ids[1],
                    postage_cost_cents=1),
                STEWARD),
            ApiErrorId.ERR_VENDOR_BUDGET_EXCEEDED)


class TestExcludedDischargeSafetyAlone:
    def test_excluded_discharge_sampling_safety_alone(self, api):
        """PRD §2.6: "8. **Patient protection.** Only `ELIGIBLE` discharges may
        be sampled (`ERR_DISCHARGE_NOT_ELIGIBLE`)."
        PRD §3.2: "the disposition is `SNF` (`SNF_DISCHARGE`)"

        Design: Corner/validations/excluded_discharge_sampling_safety_alone
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V29"), "SAMPLING_OPEN", discharge_count=0)
        payload = {
            "program_id": ctx["program"]["id"],
            "count": 1,
            "template": {
                "mrn_prefix": "M",
                "unit_id": ctx["unit"]["id"],
                "provider_id": ctx["provider"]["id"],
                "admit_date": "2026-06-01",
                "discharge_date": "2026-06-03",
                "discharge_disposition": "SNF",
                "primary_dx_group": "MEDICAL",
                "payer": "MEDICARE",
                "age_years": 85,
                "address_country": "US",
                "no_publicity_flag": False,
                "custody_status": "NONE",
            },
        }
        result = validate_success(api.import_discharges(payload, STEWARD), 201)
        assert result["excluded_count"] == 1
        d_id = result["discharge_ids"][0]

        res = api.create_sample_case(
            create_sample_case_payload(ctx["cycle"]["id"], d_id), STEWARD)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_NOT_ELIGIBLE)
        assert res.status_code == 422

    def test_excluded_discharge_sampling_rejected_same_program(self, api):
        """PRD §2.6: "8. **Patient protection.** Only `ELIGIBLE` discharges may
        be sampled (`ERR_DISCHARGE_NOT_ELIGIBLE`)."
        PRD §3.3: "the discharge must be `ELIGIBLE`
        (`ERR_DISCHARGE_NOT_ELIGIBLE`)"

        Design: Corner/validations/excluded_discharge_sampling_safety_alone
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V29B"), "SAMPLING_OPEN", discharge_count=0)
        d_ids = import_discharges(
            ctx["program"]["id"], ctx["unit"]["id"], ctx["provider"]["id"], 2,
            mrn_prefix="M", discharge_disposition="SNF", age_years=85)
        for d_id in d_ids:
            assert get_success_data(api.get_discharge(d_id, ADMIN))[
                "status"] == "EXCLUDED"
            res = api.create_sample_case(
                create_sample_case_payload(ctx["cycle"]["id"], d_id), STEWARD)
            validate_error(res, ApiErrorId.ERR_DISCHARGE_NOT_ELIGIBLE)
