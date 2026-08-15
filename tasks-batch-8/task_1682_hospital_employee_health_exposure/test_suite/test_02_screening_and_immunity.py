"""Pre-placement screening pipeline, immunity titers, and OCC supersede."""
from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_screening,
    assert_titer_result,
    complete_component_payload,
    create_titer_payload,
    decide_screening,
    get_employee,
    make_cleared_employee,
    open_screening,
    record_immune_titers,
    record_titer,
    register_employee,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTiterInterpretationVariants:
    def test_quantitative_below_threshold_is_non_immune(self, api, nurse_headers):
        """PRD §3.2: "For a `QUANTITATIVE` assay, the supplied `numeric_value`
        is compared against a per-disease threshold — 10.0 for `HEP_B`, 1.0 for
        `MEASLES`, 1.0 for `MUMPS`, 10.0 for `RUBELLA`, and 1.0 for
        `VARICELLA` — on the raw value with no rounding: a value at or above
        the threshold yields `IMMUNE`, and a value below it yields
        `NON_IMMUNE`; the boundary is inclusive, so a value exactly equal to
        the threshold is `IMMUNE`."

        Design: Difficulty/dual_variant_calc/titer_quantitative_vs_qualitative_divergence
        """
        emp = register_employee("E-DV1", full_name="Dana Vari")
        titer = record_titer(emp["id"], "HEP_B", numeric_value=8.0,
                             resulted_at="2026-07-22T09:00:00Z")
        assert_titer_result(titer)
        assert titer["immunity_status"] == "NON_IMMUNE", (
            "8.0 < 10.0 HEP_B threshold must interpret NON_IMMUNE"
        )

    def test_qualitative_label_ignores_numeric_value(self, api, nurse_headers):
        """PRD §3.2: "For a `QUALITATIVE` assay, the label alone decides:
        `REACTIVE` becomes `IMMUNE`, `NON_REACTIVE` becomes `NON_IMMUNE`, and
        `EQUIVOCAL` becomes `EQUIVOCAL`; the `numeric_value` is ignored for
        qualitative assays even when supplied, so the same numeric data can
        produce opposite outcomes under the two assay types."

        Design: Difficulty/dual_variant_calc/titer_quantitative_vs_qualitative_divergence
        """
        emp = register_employee("E-DV1Q", full_name="Dana Qual")
        quant = record_titer(emp["id"], "HEP_B", numeric_value=8.0,
                             resulted_at="2026-07-22T09:00:00Z")
        qual = record_titer(emp["id"], "HEP_B", assay_type="QUALITATIVE",
                            numeric_value=8.0, qualitative_result="REACTIVE",
                            resulted_at="2026-07-22T10:00:00Z")
        assert quant["immunity_status"] == "NON_IMMUNE"
        assert qual["immunity_status"] == "IMMUNE", (
            "REACTIVE label decides IMMUNE; the supplied 8.0 is ignored"
        )
        assert quant["immunity_status"] != qual["immunity_status"]

    def test_threshold_boundary_is_inclusive(self, api, nurse_headers):
        """PRD §3.2: "the boundary is inclusive, so a value exactly equal to
        the threshold is `IMMUNE`."

        Design: Corner/calculations/titer_threshold_inclusive_boundary
        """
        emp = register_employee("E-CL1", full_name="Thresh Old")
        at = record_titer(emp["id"], "HEP_B", numeric_value=10.0,
                          resulted_at="2026-07-22T09:00:00Z")
        below = record_titer(emp["id"], "HEP_B", numeric_value=9.99,
                             resulted_at="2026-07-22T10:00:00Z")
        assert at["immunity_status"] == "IMMUNE", "10.0 == threshold is IMMUNE"
        assert below["immunity_status"] == "NON_IMMUNE", "9.99 < 10.0 is NON_IMMUNE"

    def test_immunity_status_computed_at_record_time(self, api, nurse_headers):
        """PRD §3.2: "Interpretation happens at record time and lands on the
        computed `immunity_status`."

        Design: Corner/entities/titer_immunity_computed_server_side
        """
        emp = register_employee("E-EN5", full_name="Comp Uted")
        created = record_titer(emp["id"], "HEP_B", numeric_value=12.0,
                               resulted_at="2026-07-22T09:00:00Z")
        assert created["immunity_status"] == "IMMUNE", "12.0 >= 10.0 is IMMUNE"
        read = validate_success(api.get_titer_result(created["id"], nurse_headers))
        assert read["immunity_status"] == "IMMUNE"

    def test_titer_result_is_append_only(self, api, nurse_headers):
        """PRD §2.5: "The `TiterResult` resource is the sole exception: it is
        an append-only laboratory record carrying only `id` and `created_at`.
        It has no `updated_at` and no `version`, and no endpoint modifies it
        after creation."

        Design: Corner/entities/titer_result_immutable_record
        """
        emp = register_employee("E-EN6", full_name="Imm Utable", job_category="TECH",
                                department="LAB")
        created = record_titer(emp["id"], "VARICELLA", numeric_value=3.1,
                               resulted_at="2026-07-22T09:00:00Z")
        read = validate_success(api.get_titer_result(created["id"], nurse_headers))
        assert_titer_result(read)
        assert "version" not in read, "append-only record must not carry version"
        assert "updated_at" not in read, "append-only record must not carry updated_at"

    def test_titer_future_resulted_at_rejected(self, api, nurse_headers):
        """PRD §3.2: "the lab's `resulted_at` timestamp, which must not be
        after the current logical clock time (`ERR_FUTURE_RESULT_DATE`)."

        Design: Corner/validations/titer_future_result_rejected
        """
        emp = register_employee("E-V5", full_name="Fut Ure")
        resp = api.create_titer_result(
            emp["id"],
            create_titer_payload(numeric_value=15.0,
                                 resulted_at="2026-08-02T00:00:00Z"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FUTURE_RESULT_DATE)

        data, meta = validate_paginated(
            api.list_titer_results(nurse_headers, params={"employee_id": emp["id"]})
        )
        assert meta["total_count"] == 0 and data == []


class TestTiterReferentialVsTemporal:
    def test_mismatch_wins_over_future_result_date(self, api, nurse_headers):
        """PRD §2.8: "Every endpoint applies its checks in a single pinned
        order, and a failure surfaces the error of the earliest failing
        category rather than a later one." Referential coherence (category 8,
        `ERR_SCREENING_EMPLOYEE_MISMATCH`) precedes temporal ranges (category
        9, `ERR_FUTURE_RESULT_DATE`).

        Design: Difficulty/priority_pair_validation_conflict/titer_referential_beats_temporal
        """
        emp_a = register_employee("E-PP2A", full_name="Ref Err")
        emp_b = register_employee("E-PP2B", full_name="Temp Err", job_category="TECH",
                                  department="LAB")
        scr_a = open_screening(emp_a)

        # One request carrying BOTH a cross-employee screening_id and a future
        # resulted_at: the referential error must win.
        resp = api.create_titer_result(
            emp_b["id"],
            create_titer_payload(numeric_value=15.0,
                                 resulted_at="2027-01-01T00:00:00Z",
                                 screening_id=scr_a["id"]),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCREENING_EMPLOYEE_MISMATCH)

        data, meta = validate_paginated(
            api.list_titer_results(nurse_headers, params={"employee_id": emp_b["id"]})
        )
        assert meta["total_count"] == 0 and data == []

    def test_screening_employee_mismatch_isolated(self, api, nurse_headers):
        """PRD §3.2: "A titer may optionally carry a `screening_id` linking it
        to the pre-placement screening it satisfies; when present, that
        screening must belong to the same employee, or the record is rejected
        with `ERR_SCREENING_EMPLOYEE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/titer_referential_beats_temporal
        """
        emp_a = register_employee("E-PP2C", full_name="Ref Solo")
        emp_b = register_employee("E-PP2D", full_name="Ref Other", job_category="TECH",
                                  department="LAB")
        scr_a = open_screening(emp_a)

        resp = api.create_titer_result(
            emp_b["id"],
            create_titer_payload(numeric_value=15.0,
                                 resulted_at="2026-07-22T09:00:00Z",
                                 screening_id=scr_a["id"]),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCREENING_EMPLOYEE_MISMATCH)


class TestScreeningDecision:
    def test_cleared_decision_activates_employee(self, api, nurse_headers,
                                                 physician_headers):
        """PRD §3.2: "A successful decision stamps `decided_by_user_id` and
        `decided_at`, and a `CLEARED` decision transitions the employee from
        `PREPLACEMENT` to `ACTIVE` when the employee is still in
        `PREPLACEMENT`."

        Design: Corner/state_machines/screening_clear_activates_employee
        """
        emp = register_employee("E-SM1", full_name="Acti Vate")
        scr = open_screening(emp)
        for component, at in (("PHYSICAL", "2026-07-20T09:00:00Z"),
                              ("TB_BASELINE", "2026-07-21T09:00:00Z")):
            validate_success(api.complete_screening_component(
                scr["id"], complete_component_payload(component, completed_at=at),
                nurse_headers,
            ))
        record_immune_titers(emp["id"])

        decided = decide_screening(scr["id"], "CLEARED")
        assert decided["status"] == "CLEARED"
        assert decided["decided_at"] is not None
        assert decided["decided_by_user_id"] is not None

        emp_after = get_employee(emp["id"])
        assert emp_after["status"] == "ACTIVE", (
            "CLEARED decision must auto-transition PREPLACEMENT -> ACTIVE"
        )

    def test_decide_on_terminal_screening_rejected(self, api, nurse_headers,
                                                   physician_headers):
        """PRD §3.2: "both `CLEARED` and `FAILED` are terminal, as is the
        `VOID` state reached through supersession." and "A `CLEARED` decision
        requires the screening to be `IN_PROGRESS` (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/screening_decide_twice_rejected
        """
        emp = register_employee("E-SM2", full_name="Two Decide")
        scr = open_screening(emp)
        failed = decide_screening(scr["id"], "FAILED")
        assert failed["status"] == "FAILED"

        resp = api.decide_screening(scr["id"], {"outcome": "CLEARED"}, physician_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        read = validate_success(api.get_screening(scr["id"], physician_headers))
        assert read["status"] == "FAILED"
        assert get_employee(emp["id"])["status"] == "PREPLACEMENT"

    def test_component_completion_repeat_rejected(self, api, nurse_headers):
        """PRD §3.2: "A component may be completed only once; repeating one is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/screening_component_repeat_rejected
        """
        emp = register_employee("E-SM3", full_name="Rep Eat")
        scr = open_screening(emp)
        validate_success(api.complete_screening_component(
            scr["id"],
            complete_component_payload("PHYSICAL", completed_at="2026-07-20T09:00:00Z"),
            nurse_headers,
        ))

        resp = api.complete_screening_component(
            scr["id"],
            complete_component_payload("PHYSICAL", completed_at="2026-07-25T09:00:00Z"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        read = validate_success(api.get_screening(scr["id"], nurse_headers))
        assert_instant(read["physical_completed_at"], "2026-07-20T09:00:00")

    def test_clear_blocked_by_unestablished_immunity(self, api, nurse_headers,
                                                     physician_headers):
        """PRD §3.2: "requires immunity to be established for each of the two
        required diseases, `HEP_B` and `VARICELLA`: the latest titer for the
        employee and disease — chosen as the row with the greatest
        `resulted_at`, with ties broken in favor of the row with the greatest
        `created_at` — must have `immunity_status` `IMMUNE`, otherwise the
        decision is rejected with `ERR_IMMUNITY_NOT_ESTABLISHED`."

        Design: Corner/validations/screening_clear_blocked_by_immunity
        """
        emp = register_employee("E-V12", full_name="Not Immune")
        scr = open_screening(emp)
        for component, at in (("PHYSICAL", "2026-07-20T09:00:00Z"),
                              ("TB_BASELINE", "2026-07-21T09:00:00Z")):
            validate_success(api.complete_screening_component(
                scr["id"], complete_component_payload(component, completed_at=at),
                nurse_headers,
            ))
        record_titer(emp["id"], "HEP_B", numeric_value=15.0,
                     resulted_at="2026-07-22T09:00:00Z")
        # VARICELLA 0.5 < 1.0 threshold -> latest titer is NON_IMMUNE.
        record_titer(emp["id"], "VARICELLA", numeric_value=0.5,
                     resulted_at="2026-07-22T09:30:00Z")

        resp = api.decide_screening(scr["id"], {"outcome": "CLEARED"}, physician_headers)
        validate_error(resp, ApiErrorId.ERR_IMMUNITY_NOT_ESTABLISHED)

        read = validate_success(api.get_screening(scr["id"], physician_headers))
        assert read["status"] == "IN_PROGRESS"
        assert get_employee(emp["id"])["status"] == "PREPLACEMENT"

    def test_clear_blocked_by_missing_med_eval_when_required(self, api,
                                                             nurse_headers,
                                                             physician_headers):
        """PRD §3.2: "requires `physical_completed_at` and
        `tb_baseline_completed_at` to be set — plus `med_eval_completed_at`
        when the employee's `requires_respirator` is true — with any missing
        component rejected as `ERR_COMPONENT_INCOMPLETE`"

        Design: Corner/validations/screening_clear_blocked_by_med_eval
        """
        emp = register_employee("E-V13", full_name="Needs Resp",
                                requires_respirator=True)
        scr = open_screening(emp)
        for component, at in (("PHYSICAL", "2026-07-20T09:00:00Z"),
                              ("TB_BASELINE", "2026-07-21T09:00:00Z")):
            validate_success(api.complete_screening_component(
                scr["id"], complete_component_payload(component, completed_at=at),
                nurse_headers,
            ))
        record_immune_titers(emp["id"])

        resp = api.decide_screening(scr["id"], {"outcome": "CLEARED"}, physician_headers)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_INCOMPLETE)

        read = validate_success(api.get_screening(scr["id"], physician_headers))
        assert read["status"] == "IN_PROGRESS"

    def test_clear_succeeds_without_med_eval_when_not_required(self, api,
                                                               nurse_headers,
                                                               physician_headers):
        """PRD §3.2: "The medical evaluation component is required only for
        employees whose `requires_respirator` is true."

        Design: Corner/validations/screening_clear_succeeds_without_med_eval_when_not_required
        """
        emp = register_employee("E-V14", full_name="No Resp Needed",
                                job_category="OTHER", department="ADM")
        scr = open_screening(emp)
        for component, at in (("PHYSICAL", "2026-07-20T09:00:00Z"),
                              ("TB_BASELINE", "2026-07-21T09:00:00Z")):
            validate_success(api.complete_screening_component(
                scr["id"], complete_component_payload(component, completed_at=at),
                nurse_headers,
            ))
        record_immune_titers(emp["id"])

        decided = decide_screening(scr["id"], "CLEARED")
        assert decided["status"] == "CLEARED"
        assert get_employee(emp["id"])["status"] == "ACTIVE"


class TestScreeningOptimisticConcurrency:
    def test_stale_version_rejected_and_fresh_create_supersedes(self, api,
                                                                nurse_headers,
                                                                physician_headers):
        """PRD §2.7: "If the employee's current `version` has advanced since
        that observation, the request is rejected with
        `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412), and this stale-version
        rejection is evaluated before any business check on the request."
        PRD §3.2: "Opening a screening is a create-with-supersede: any
        screening already `IN_PROGRESS` for the same employee automatically
        becomes `VOID`, the superseded screening's linked titer results remain
        immutable and still count toward immunity interpretation, and the
        employee's `version` increments."

        Design: Corner/complexity_layers/occ_stale_version_and_supersede
        """
        emp = register_employee("E-L1", full_name="Occ Test")
        v_created = emp["version"]

        scr_a = open_screening(emp)

        # Second create carrying the pre-first-create version: stale.
        stale = api.create_screening(
            emp["id"], {"expected_employee_version": v_created}, nurse_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_EMPLOYEE_VERSION)

        # Re-observe, then create with the fresh version: succeeds and
        # supersedes the first screening.
        emp_mid = get_employee(emp["id"])
        scr_b = validate_success(api.create_screening(
            emp["id"], {"expected_employee_version": emp_mid["version"]}, nurse_headers
        ), expected_status=201)
        assert scr_b["status"] == "IN_PROGRESS"

        scr_a_after = validate_success(api.get_screening(scr_a["id"], nurse_headers))
        assert scr_a_after["status"] == "VOID", (
            "superseded screening must become VOID"
        )

        emp_after = get_employee(emp["id"])
        assert emp_after["version"] == v_created + 2, (
            "each successful screening open increments the employee version once"
        )
