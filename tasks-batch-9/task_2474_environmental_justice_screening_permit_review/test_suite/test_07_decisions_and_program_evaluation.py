"""Permit decisions, the emissions ledgers they book, and program evaluation.

Issuance is the only event that moves the two load ledgers, denial is the only
substantive refusal that must be justified from the record, and the program
evaluation report is what the office shows for all of it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_DENIED,
    APP_ISSUED,
    APP_PENDING_DECISION,
    APP_WITHDRAWN,
    ApiErrorId,
    AREA_LOAD_CAP_MULTIPLIER,
    BASIS_APPLICATION_DATE,
    BASIS_DECISION_DATE,
    CONDITION_ADDITIONAL_CONTROL,
    CONDITION_VOIDED,
    DECISION_DENIED,
    DEFICIENCY_NO_ACCESSIBLE_MEETING,
    DENIAL_BASIS_INCOMPLETE_ASSESSMENT,
    DENIAL_BASIS_UNMITIGABLE,
    DESIGNATION_OVERBURDENED,
    DISPOSITION_DENY,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    MEETING_CANCELLED,
    PLAN_CANCELLED,
    PLAN_CLOSED,
    ADEQUACY_COMPLIANT,
    ADEQUACY_DEFICIENT,
    TRACK_STANDARD,
    add_condition,
    add_meeting,
    advance_to_decision,
    assert_amount,
    assert_amounts,
    assert_created,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_ledgers,
    assert_object_envelope,
    assert_ratio,
    assert_rejected,
    build_area_k_assessment_accepted,
    build_area_k_screened,
    close_plan,
    decision_payload,
    find_condition,
    find_decision,
    find_meeting,
    make_applicant_headers,
    open_plan,
    program_evaluation_params,
    read_application,
    read_area,
    read_facility,
    read_plan,
    read_venue,
    set_clock,
    validate_success,
    withdraw_payload,
)


class TestAreaLoadCap:
    """PRD §2.12 refuses an issuance that would breach the community ceiling."""

    def test_issuing_beyond_the_area_load_cap_is_rejected(
        self, api, area_i_pending_decision
    ):
        """A 20.00 tpy permit cannot fit under an 11.50 tpy ceiling.

        PRD §2.12: "An area may never be permitted beyond **1.15 times** its
        existing aggregate load: issuance is refused when the area's
        `permitted_load_tpy` plus the application's `approved_net_emissions_tpy`
        would exceed `baseline_load_tpy` multiplied by 1.15 and rounded half up to
        2 decimals."
        PRD §3.7: "Finally the area load cap of §2.12 must hold, or the request is
        refused with `ERR_AREA_LOAD_CAP_EXCEEDED`."

        Design: Corner/validations/area_load_cap_exceeded_on_standard_track_issue
        """
        state = area_i_pending_decision
        area = read_area(api, state["area_id"])
        assert_amount(area.get("baseline_load_tpy"), 10.00, "baseline_load_tpy")
        # 10.00 x 1.15 leaves room for 11.50 tpy in total.
        assert AREA_LOAD_CAP_MULTIPLIER == 1.15, "the area load cap multiplier is 1.15"

        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"], disposition="ISSUE"
            ),
            MANAGER_HEADERS,
        )

        assert_rejected(response, ApiErrorId.AREA_LOAD_CAP_EXCEEDED)

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_PENDING_DECISION)
        assert_field(application, "review_track", TRACK_STANDARD)
        assert_amount(
            application.get("approved_net_emissions_tpy"),
            0.00,
            "approved_net_emissions_tpy",
        )

        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=0.00,
            existing_load_tpy=0.00,
        )
        assert_empty_listing(
            api.list_application_decisions(state["app_id"], MANAGER_HEADERS)
        )


class TestDenialBasisSupport:
    """PRD §3.7 makes the agency prove its denial from the record."""

    def test_denial_basis_the_record_does_not_support_is_rejected(
        self, api, area_j_pending_decision
    ):
        """A zero residual index cannot support an unmitigable-impact denial.

        PRD §3.7: "A `DENY` disposition requires a `denial_basis`, and the basis
        must be supported by the record on exactly one of three grounds:
        `UNMITIGABLE_DISPROPORTIONATE_IMPACT` requires the application's
        `residual_impact_index` to be **at least 60.00**; `INADEQUATE_PARTICIPATION`
        requires the participation plan's `adequacy_status` to be `DEFICIENT`; and
        `INCOMPLETE_ASSESSMENT` requires the governing assessment's
        `data_confidence` to be `LOW`." and "A basis the record does not support is
        refused with `ERR_DENIAL_BASIS_UNSUPPORTED`."

        Design: Corner/validations/denial_basis_unsupported_by_the_record_rejected
        """
        state = area_j_pending_decision
        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_DENY,
                denial_basis=DENIAL_BASIS_UNMITIGABLE,
            ),
            MANAGER_HEADERS,
        )

        assert_rejected(response, ApiErrorId.DENIAL_BASIS_UNSUPPORTED)

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_PENDING_DECISION)
        assert_amount(
            application.get("residual_impact_index"), 0.00, "residual_impact_index"
        )
        assert_empty_listing(
            api.list_application_decisions(state["app_id"], MANAGER_HEADERS)
        )


class TestSupportedDenial:
    """PRD §3.7 books nothing when a permit is refused."""

    def test_denial_on_an_incomplete_assessment_leaves_both_ledgers_untouched(
        self, api, clock
    ):
        """A `LOW`-confidence assessment supports the denial and moves no tonnage.

        PRD §3.7: "A `DENY` disposition requires a `denial_basis`, and the basis
        must be supported by the record on exactly one of three grounds:
        `UNMITIGABLE_DISPROPORTIONATE_IMPACT` requires the application's
        `residual_impact_index` to be **at least 60.00**; `INADEQUATE_PARTICIPATION`
        requires the participation plan's `adequacy_status` to be `DEFICIENT`; and
        `INCOMPLETE_ASSESSMENT` requires the governing assessment's
        `data_confidence` to be `LOW`."
        PRD §3.7: "A supported denial moves the application `PENDING_DECISION →
        DENIED`, which is terminal, and writes a decision in `status` `DENIED` with
        `approved_net_emissions_tpy` 0.00 and the residual snapshot recorded." and
        "Denial books nothing: the facility's `existing_load_tpy` and the area's
        `permitted_load_tpy` are left exactly as they were."
        PRD §3.7: "The decision record carries `residual_index_at_decision`, a
        snapshot of the application's `residual_impact_index` at decision time, and
        `decided_by_user_id`, the deciding manager's `X-User-ID`."
        PRD §3.4: "If that count is zero, `NO_ACCESSIBLE_MEETING` is appended."

        Design: Corner/endpoints/denial_on_incomplete_assessment_leaves_both_ledgers_untouched
        """
        state = build_area_k_assessment_accepted(api)
        open_plan(api, state, "2026-08-01")
        set_clock(api, "2026-08-31T00:00:00Z")
        closed = close_plan(api, state)
        assert_fields(
            closed,
            {
                "status": PLAN_CLOSED,
                "adequacy_status": ADEQUACY_DEFICIENT,
                "deficiency_codes": [DEFICIENCY_NO_ACCESSIBLE_MEETING],
            },
        )
        advance_to_decision(api, state)

        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_DENY,
                denial_basis=DENIAL_BASIS_INCOMPLETE_ASSESSMENT,
            ),
            MANAGER_HEADERS,
        )

        decision = assert_created(response)
        assert_object_envelope(response)
        assert_fields(
            decision,
            {
                "disposition": DISPOSITION_DENY,
                "denial_basis": DENIAL_BASIS_INCOMPLETE_ASSESSMENT,
                "status": DECISION_DENIED,
                "decided_by_user_id": MANAGER_USER_ID,
            },
        )
        assert_amounts(
            decision,
            {
                "residual_index_at_decision": 7.50,
                "approved_net_emissions_tpy": 0.00,
            },
        )

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_DENIED)
        assert_amount(
            application.get("approved_net_emissions_tpy"),
            0.00,
            "approved_net_emissions_tpy",
        )

        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=0.00,
            existing_load_tpy=0.00,
        )
        assert_field(
            find_decision(api, state["app_id"], decision["id"]), "status", DECISION_DENIED
        )


class TestWithdrawalCascade:
    """PRD §3.9 tears the whole enhanced-track apparatus down in one call."""

    def test_withdraw_cancels_the_plan_the_meeting_and_the_condition(self, api, clock):
        """One withdraw releases the venue slot and voids the mitigation credit.

        PRD §3.9: "**Withdrawal** is the applicant's exit and is terminal." and "On
        the enhanced track the full cascade runs: the application's participation
        plan moves from `PLANNED`, `OPEN`, `EXTENDED` or `CLOSED` to `CANCELLED`;
        every `SCHEDULED` public meeting of that plan moves to `CANCELLED`, each
        decrementing its venue's `booked_meeting_count` by 1 and the plan's
        `meeting_count` by 1; every assessment in `DRAFT`, `SUBMITTED_FOR_QA`,
        `RETURNED` or `ACCEPTED` moves to `VOIDED`; every `ACTIVE` permit condition
        moves to `VOIDED`; the application's `total_mitigation_credit_tpy`,
        `pre_mitigation_index` and `residual_impact_index` are recomputed over what
        remains; the area's `open_plan_count` is recomputed; and the application's
        `version` increments by 1."

        Design: Corner/endpoints/withdraw_cascades_plan_meeting_and_condition_teardown
        """
        state = build_area_k_screened(api, with_venue=True)
        condition = add_condition(
            api, state, CONDITION_ADDITIONAL_CONTROL, reduction_tpy=5.00, enforceable=True
        )
        open_plan(api, state, "2026-08-01")
        meeting = add_meeting(api, state, "2026-08-20T18:00:00Z", "2026-08-20T20:00:00Z")
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 1)

        response = api.withdraw_application(
            state["app_id"],
            make_applicant_headers(state["facility_id"]),
            payload=withdraw_payload(reason="Applicant re-siting the plant"),
        )

        withdrawn = validate_success(response)
        assert_field(withdrawn, "status", APP_WITHDRAWN)
        assert_amounts(
            withdrawn,
            {
                "total_mitigation_credit_tpy": 0.00,
                "residual_impact_index": 0.00,
            },
        )

        assert_field(read_plan(api, state["plan_id"]), "status", PLAN_CANCELLED)
        assert_field(
            find_meeting(api, state["plan_id"], meeting["id"]), "status", MEETING_CANCELLED
        )
        assert_field(
            find_condition(api, state["app_id"], condition["id"]), "status", CONDITION_VOIDED
        )
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 0)
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 0)


class TestProgramEvaluationZeroGuards:
    """PRD §3.9 never divides by an empty decided population."""

    def test_evaluation_over_an_empty_population_returns_zeroed_metrics(
        self, api, area_g
    ):
        """With nothing decided anywhere, every figure reports its zero guard.

        PRD §3.9: "`DECISION_DATE`, the default used when `basis` is omitted,
        filters on the governing decision's `created_at` date."
        PRD §3.9: "The report echoes the `basis` in use and returns seven figures."
        and "`total_decided` counts the population inside the window." and
        "`issued_count` and `denied_count` split it by the application's `status`."
        PRD §3.9: "`denial_rate` is 0.0000 when `total_decided` is zero, and
        otherwise `denied_count` divided by `total_decided`, rounded half up to four
        decimals." and "`mean_residual_index` is 0.00 when `total_decided` is zero,
        and otherwise the sum of the in-window applications' `residual_impact_index`
        values divided by `total_decided`, rounded half up to two decimals."
        PRD §3.9: "`total_mitigation_credit_tpy` is the sum of those applications'
        `total_mitigation_credit_tpy` values, rounded half up to two decimals." and
        "`total_community_benefit_usd` is the sum of `community_benefit_total_usd`
        over the issued decisions in the window, rounded half up to two decimals."
        PRD §3.9: "And `mean_comment_days` is 0.00 when no enhanced-track
        application falls in the window, and otherwise the sum, over the in-window
        enhanced-track applications, of each plan's `required_comment_days` plus its
        `granted_extension_days`, divided by the count of those applications,
        rounded half up to two decimals."

        Design: Corner/calculations/program_evaluation_zero_guards_on_empty_population
        """
        assert area_g["area_id"], "the empty-population run still needs one area"

        response = api.get_program_evaluation(ADMIN_HEADERS)

        report = validate_success(response)
        assert_fields(
            report,
            {
                "basis": BASIS_DECISION_DATE,
                "total_decided": 0,
                "issued_count": 0,
                "denied_count": 0,
            },
        )
        assert_ratio(report.get("denial_rate"), 0.0000, "denial_rate")
        assert_amounts(
            report,
            {
                "mean_residual_index": 0.00,
                "total_mitigation_credit_tpy": 0.00,
                "total_community_benefit_usd": 0.00,
                "mean_comment_days": 0.00,
            },
        )


class TestProgramEvaluationBasisVariants:
    """PRD §3.9 lets the two bases disagree over identical data."""

    def test_the_two_bases_report_differently_over_the_same_window(
        self, api, app_a_issued
    ):
        """October holds the decision but not the filing, so one basis sees nothing.

        PRD §3.9: "The `basis` parameter selects **which date** the reporting window
        filters on, and the two variants can report different metrics over identical
        data." and "`APPLICATION_DATE` filters on the application's own `created_at`
        date, so an application filed before the window but decided inside it is
        excluded under this variant while being included under the other." and "The
        window is closed on both ends — a date equal to `period_start` or to
        `period_end` is inside it — and the defaults are 1970-01-01 for
        `period_start` and 9999-12-31 for `period_end`."
        PRD §3.9: "The population is the applications whose `status` is `ISSUED` or
        `DENIED` whose facility's screening area carries a designation in the filter;
        the filter is the single supplied `designation` when one is given, and
        otherwise both `OVERBURDENED` and `SEVERELY_OVERBURDENED`."
        PRD §3.7: "`community_benefit_surcharge_usd` is the base multiplied by the
        surcharge rate multiplied by the designation multiplier, rounded half up to
        two decimals, and `community_benefit_total_usd` is the base plus that
        surcharge, rounded half up to two decimals."

        Design: Corner/calculations/program_evaluation_basis_variant_windows_diverge
        """
        state = app_a_issued
        assert_field(read_area(api, state["area_id"]), "designation", DESIGNATION_OVERBURDENED)

        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "required_comment_days": 70,
                "granted_extension_days": 0,
                "comment_end_date": "2026-10-09",
                "adequacy_status": ADEQUACY_COMPLIANT,
                "deficiency_codes": [],
            },
        )

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_ISSUED)
        assert_amounts(
            application,
            {
                "residual_impact_index": 51.14,
                "approved_net_emissions_tpy": 50.00,
                "total_mitigation_credit_tpy": 30.00,
            },
        )

        decision = find_decision(api, state["app_id"], state["decision_id"])
        assert_amounts(
            decision,
            {
                # A 95000.00 base takes the 0.05 rate, lifted by the 1.10 multiplier.
                "community_benefit_surcharge_usd": 5225.00,
                "community_benefit_total_usd": 100225.00,
            },
        )

        by_decision_date = validate_success(
            api.get_program_evaluation(
                ANALYST_HEADERS,
                params=program_evaluation_params(
                    basis=BASIS_DECISION_DATE,
                    period_start="2026-10-01",
                    period_end="2026-10-31",
                ),
            )
        )
        assert_fields(
            by_decision_date,
            {
                "basis": BASIS_DECISION_DATE,
                "total_decided": 1,
                "issued_count": 1,
                "denied_count": 0,
            },
        )
        assert_ratio(by_decision_date.get("denial_rate"), 0.0000, "denial_rate")
        assert_amounts(
            by_decision_date,
            {
                "mean_residual_index": 51.14,
                "total_mitigation_credit_tpy": 30.00,
                "total_community_benefit_usd": 100225.00,
                "mean_comment_days": 70.00,
            },
        )

        by_application_date = validate_success(
            api.get_program_evaluation(
                ANALYST_HEADERS,
                params=program_evaluation_params(
                    basis=BASIS_APPLICATION_DATE,
                    period_start="2026-10-01",
                    period_end="2026-10-31",
                ),
            )
        )
        assert_fields(
            by_application_date,
            {
                "basis": BASIS_APPLICATION_DATE,
                "total_decided": 0,
                "issued_count": 0,
            },
        )
        assert_ratio(by_application_date.get("denial_rate"), 0.0000, "denial_rate")
        assert_amounts(
            by_application_date,
            {
                "mean_residual_index": 0.00,
                "total_community_benefit_usd": 0.00,
                "mean_comment_days": 0.00,
            },
        )
