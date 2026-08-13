"""Discharge exclusion evaluation, the reinstatement loop, the RESPONDED-case
override lock, and the post-sample exclusion cascade (PRD §2.8, §3.2, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_case,
    assert_discharge,
    create_discharge_payload,
    get_case,
    get_cycle,
    get_success_data,
    get_vendor,
    import_cases,
    import_discharges,
    make_program,
    make_provider,
    make_steward_headers,
    make_unit,
    make_vendor,
    make_cycle,
    record_response,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_success,
)


class TestReinstatementLoop:
    def test_discharge_reinstate_excluded_to_eligible(self, api):
        """PRD §3.2: "A discharge with any reasons becomes `EXCLUDED`; one with
        none becomes `ELIGIBLE`."
        PRD §3.2: "A discharge can also be reinstated from `EXCLUDED` to
        `ELIGIBLE` when the corrected data yields no reasons"

        Design: Corner/state_machines/discharge_reinstate_excluded_to_eligible
        """
        program = make_program(name="P-SM7")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        discharge = get_success_data(api.create_discharge(
            create_discharge_payload(
                program["id"], unit["id"], provider["id"], mrn="M-900",
                discharge_disposition="EXPIRED", age_years=80),
            make_steward_headers()))
        first = get_success_data(api.evaluate_discharge(
            discharge["id"], {}, make_steward_headers()))
        assert first["status"] == "EXCLUDED"
        assert first["exclusion_reasons"] == ["EXPIRED"]

        reinstated = get_success_data(api.evaluate_discharge(
            discharge["id"], {"discharge_disposition": "HOME"},
            make_steward_headers()))
        assert reinstated["status"] == "ELIGIBLE"
        assert reinstated["exclusion_reasons"] == []

    def test_reinstate_clears_reasons_after_corrected_override(self, api):
        """PRD §3.2: "Evaluation runs automatically per item inside the bulk
        import and on demand when a `DataSteward` evaluates a discharge,
        optionally supplying corrected source fields — any of
        `discharge_disposition`, `primary_dx_group`, `age_years`,
        `address_country`, `no_publicity_flag`, `custody_status`, `admit_date`,
        or `discharge_date` — which are applied before the rules re-run."
        PRD §3.2: "A discharge can also be reinstated from `EXCLUDED` to
        `ELIGIBLE` when the corrected data yields no reasons"

        Design: Corner/state_machines/discharge_reinstate_excluded_to_eligible
        """
        program = make_program(name="P-SM7B")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        discharge = get_success_data(api.create_discharge(
            create_discharge_payload(
                program["id"], unit["id"], provider["id"], mrn="M-901",
                primary_dx_group="PSYCHIATRIC"),
            make_steward_headers()))
        excluded = get_success_data(api.evaluate_discharge(
            discharge["id"], {}, make_steward_headers()))
        assert excluded["status"] == "EXCLUDED"
        assert excluded["exclusion_reasons"] == ["PSYCH_DX"]

        reinstated = get_success_data(api.evaluate_discharge(
            discharge["id"], {"primary_dx_group": "MEDICAL"},
            make_steward_headers()))
        assert_discharge(reinstated)
        assert reinstated["status"] == "ELIGIBLE"
        assert reinstated["exclusion_reasons"] == []


class TestOverrideLockedWhenResponded:
    def test_discharge_override_locked_when_responded(self, api):
        """PRD §3.2: "When corrected fields are supplied, the override is
        blocked while any linked sample case has reached `RESPONDED`, surfacing
        `ERR_DISCHARGE_LOCKED_BY_SAMPLE`; a re-evaluation without overrides is
        always permitted."

        Design: Corner/validations/discharge_override_locked_when_responded
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V24"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        record_response(case_id, ctx["vendor"]["id"])

        res = api.evaluate_discharge(
            ctx["discharge_ids"][0], {"primary_dx_group": "PSYCHIATRIC"},
            make_steward_headers())
        validate_error(res, ApiErrorId.ERR_DISCHARGE_LOCKED_BY_SAMPLE)

        discharge = get_success_data(api.get_discharge(
            ctx["discharge_ids"][0], make_steward_headers()))
        assert discharge["status"] == "ELIGIBLE"
        assert get_case(case_id)["status"] == "RESPONDED"

    def test_discharge_override_lock_preserves_discharge_and_case(self, api):
        """PRD §3.2: "When corrected fields are supplied, the override is
        blocked while any linked sample case has reached `RESPONDED`, surfacing
        `ERR_DISCHARGE_LOCKED_BY_SAMPLE`; a re-evaluation without overrides is
        always permitted."

        Design: Corner/validations/discharge_override_locked_when_responded
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V24B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        record_response(case_id, ctx["vendor"]["id"], score=3)

        validate_error(
            api.evaluate_discharge(
                ctx["discharge_ids"][0], {"age_years": 12},
                make_steward_headers()),
            ApiErrorId.ERR_DISCHARGE_LOCKED_BY_SAMPLE)
        discharge = get_success_data(api.get_discharge(
            ctx["discharge_ids"][0], make_steward_headers()))
        assert discharge["status"] == "ELIGIBLE"
        assert discharge["age_years"] == 65
        assert_case(get_case(case_id))
        assert get_case(case_id)["status"] == "RESPONDED"


class TestDischargeExclusionCascade:
    def test_discharge_exclusion_cascade(self, api):
        """PRD §3.2: "Moving a discharge from `ELIGIBLE` to `EXCLUDED` drives
        every linked sample case in `SAMPLED` or `IN_FIELD` to
        `EXCLUDED_POST_SAMPLE`; each such case still `CHARGED` flips to
        `CREDITED` and its `postage_cost_cents` are credited back to the
        vendor's `cycle_budget_remaining_cents`, and the cycle's counters are
        recomputed."
        PRD §3.2: "the diagnosis group is `PSYCHIATRIC` (`PSYCH_DX`)"

        Design: Difficulty/transitive_cascade/discharge_exclusion_cascade
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-TC2"), "FIELDING", discharge_count=2,
            postage_cost_cents=100)
        vendor = ctx["vendor"]
        cycle = ctx["cycle"]
        assert get_vendor(vendor["id"])["cycle_budget_remaining_cents"] == 99800

        evaluated = validate_success(
            api.evaluate_discharge(
                ctx["discharge_ids"][0], {"primary_dx_group": "PSYCHIATRIC"},
                make_steward_headers()),
            200)
        # Hop A: the discharge itself flips.
        assert evaluated["status"] == "EXCLUDED"
        assert evaluated["exclusion_reasons"] == ["PSYCH_DX"]
        # Hop B: the linked IN_FIELD case is force-transitioned and credited.
        case0 = get_case(ctx["case_ids"][0])
        assert case0["status"] == "EXCLUDED_POST_SAMPLE"
        assert case0["billing_status"] == "CREDITED"
        # Hop C: the vendor ledger is credited and the counters recomputed.
        assert get_vendor(vendor["id"])["cycle_budget_remaining_cents"] == 99900
        cycle_after = get_cycle(cycle["id"])
        assert cycle_after["eligible_denominator"] == 1
        assert cycle_after["sampled_count"] == 2
        assert get_case(ctx["case_ids"][1])["status"] == "IN_FIELD"

    def test_discharge_exclusion_cascade_snapshot_unchanged(self, api):
        """PRD §3.2: "Moving a discharge from `ELIGIBLE` to `EXCLUDED` drives
        every linked sample case in `SAMPLED` or `IN_FIELD` to
        `EXCLUDED_POST_SAMPLE`; each such case still `CHARGED` flips to
        `CREDITED` and its `postage_cost_cents` are credited back to the
        vendor's `cycle_budget_remaining_cents`, and the cycle's counters are
        recomputed."
        PRD §3.3: "the cycle's `sampled_count` is frozen to the number of cases
        that entered the field"

        Design: Difficulty/transitive_cascade/discharge_exclusion_cascade
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-TC2B"), "FIELDING", discharge_count=2,
            postage_cost_cents=100)
        vendor_id = ctx["vendor"]["id"]
        cycle_id = ctx["cycle"]["id"]

        get_success_data(api.evaluate_discharge(
            ctx["discharge_ids"][0], {"primary_dx_group": "PSYCHIATRIC"},
            make_steward_headers()))
        cycle_after = get_cycle(cycle_id)
        # eligible_denominator recomputed (drops the excluded case); the
        # sampled_count snapshot taken at start-fielding is unchanged.
        assert cycle_after["eligible_denominator"] == 1
        assert cycle_after["sampled_count"] == 2
        assert cycle_after["completed_responses"] == 0
        assert cycle_after["response_rate"] == 0.0
        assert get_vendor(vendor_id)["cycle_budget_remaining_cents"] == 99900
        case0 = get_case(ctx["case_ids"][0])
        assert case0["status"] == "EXCLUDED_POST_SAMPLE"
        assert case0["billing_status"] == "CREDITED"
