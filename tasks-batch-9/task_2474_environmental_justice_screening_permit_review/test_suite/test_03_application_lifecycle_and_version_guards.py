"""Permit-application lifecycle states and the optimistic version guards.

The application is the spine of the workflow: its declared initial state, its
refusal of undeclared transitions, and the two `expected_application_version`
guards that hang off it are all proved here.
"""

from test_helpers import (
    APP_DRAFT,
    APP_ENHANCED_REVIEW,
    APP_SUBMITTED,
    APP_WITHDRAWN,
    ANALYST_HEADERS,
    ApiErrorId,
    BASE_COMMENT_DAYS,
    CONDITION_ADDITIONAL_CONTROL,
    CONDITION_MONITORING,
    DESIGNATION_UNDESIGNATED,
    DETERMINATION_ENHANCED_REQUIRED,
    MONITORING_CONTINUOUS,
    PERMIT_TYPE_MODIFICATION,
    PLAN_PLANNED,
    TRACK_ENHANCED,
    TRACK_UNDETERMINED,
    TRIGGER_FACILITY_TYPE,
    add_condition,
    assert_amount,
    assert_amounts,
    assert_created,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_page,
    assert_rejected,
    assessment_payload,
    condition_payload,
    find_condition,
    make_applicant_headers,
    permit_application_payload,
    read_application,
    read_area,
    resubmit_payload,
    validate_success,
    withdraw_payload,
)


class TestApplicationInitialState:
    """PRD §3.2 fixes every field a new application starts life with."""

    def test_new_application_lands_in_draft_with_zeroed_review_fields(
        self, api, area_g_facility
    ):
        """Nothing has been screened yet, so every review figure reads zero.

        PRD §3.2: "A new application lands in `status` `DRAFT` with `review_track`
        `UNDETERMINED`, `revision_round` 0, `screening_stale_flag` false,
        `pre_mitigation_index` 0.00, `total_mitigation_credit_tpy` 0.00,
        `residual_impact_index` 0.00 and `approved_net_emissions_tpy` 0.00."

        Design: Corner/state_machines/application_starts_in_draft_with_zeroed_review_fields
        """
        state = area_g_facility
        response = api.create_permit_application(
            permit_application_payload(
                facility_id=state["facility_id"],
                permit_type=PERMIT_TYPE_MODIFICATION,
                proposed_emissions_tpy=10.00,
                proposed_operating_hours_per_year=3000,
            ),
            make_applicant_headers(state["facility_id"]),
        )

        application = assert_created(response)
        assert_fields(
            application,
            {
                "status": APP_DRAFT,
                "review_track": TRACK_UNDETERMINED,
                "revision_round": 0,
                "screening_stale_flag": False,
                "version": 1,
            },
        )
        assert_amounts(
            application,
            {
                "pre_mitigation_index": 0.00,
                "total_mitigation_credit_tpy": 0.00,
                "residual_impact_index": 0.00,
                "approved_net_emissions_tpy": 0.00,
            },
        )


class TestUndeclaredApplicationTransitions:
    """PRD §3.2 and §3.9 name the only originating states for each trigger."""

    def test_submitting_an_already_submitted_application_is_rejected(
        self, api, area_g_facility
    ):
        """`SUBMITTED` is not a from-state for submit, so the second call fails.

        PRD §3.2: "The applicant then **submits** the application, moving it
        `DRAFT → SUBMITTED`; only the owning representative may do so, only from
        `DRAFT`, and the transition increments the application's `version` by 1."
        and "Any other originating state yields `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/submit_on_already_submitted_application_rejected
        """
        state = area_g_facility
        applicant = make_applicant_headers(state["facility_id"])
        application = assert_created(
            api.create_permit_application(
                permit_application_payload(
                    facility_id=state["facility_id"],
                    permit_type=PERMIT_TYPE_MODIFICATION,
                    proposed_emissions_tpy=10.00,
                    proposed_operating_hours_per_year=3000,
                ),
                applicant,
            )
        )
        first = validate_success(api.submit_application(application["id"], applicant))
        assert_field(first, "status", APP_SUBMITTED)
        assert_field(first, "version", 2)

        second = api.submit_application(application["id"], applicant)

        assert_rejected(second, ApiErrorId.INVALID_APPLICATION_STATE)

        stored = read_application(api, application["id"])
        assert_field(stored, "status", APP_SUBMITTED)
        assert_field(stored, "version", 2)

    def test_withdrawn_application_is_terminal_and_rejects_resubmit(
        self, api, area_g_facility
    ):
        """A withdrawn file cannot be resurrected by a resubmission.

        PRD §3.9: "Only the owning representative may resubmit, and only from
        `RETURNED_FOR_REVISION`."
        PRD §2.10: "The target resource is in a state from which the requested
        transition is declared — otherwise the per-family state code:
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_ASSESSMENT_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_MEETING_STATE`,
        `ERR_INVALID_CONDITION_STATE`, `ERR_INVALID_DECISION_STATE`,
        `ERR_INVALID_COMPLAINT_STATE`, `ERR_INVALID_INSPECTION_STATE`, or
        `ERR_AREA_NOT_STALE` when recertification is asked of an area whose
        `data_status` is already `CURRENT`."

        Design: Corner/state_machines/withdrawn_application_is_terminal_and_rejects_resubmit
        """
        state = area_g_facility
        applicant = make_applicant_headers(state["facility_id"])
        application = assert_created(
            api.create_permit_application(
                permit_application_payload(
                    facility_id=state["facility_id"],
                    permit_type=PERMIT_TYPE_MODIFICATION,
                    proposed_emissions_tpy=10.00,
                    proposed_operating_hours_per_year=3000,
                ),
                applicant,
            )
        )
        withdrawn = validate_success(
            api.withdraw_application(
                application["id"],
                applicant,
                payload=withdraw_payload(reason="Project cancelled by the owner"),
            )
        )
        assert_field(withdrawn, "status", APP_WITHDRAWN)

        response = api.resubmit_application(
            application["id"],
            applicant,
            payload=resubmit_payload(proposed_emissions_tpy=12.00),
        )

        assert_rejected(response, ApiErrorId.INVALID_APPLICATION_STATE)

        stored = read_application(api, application["id"])
        assert_field(stored, "status", APP_WITHDRAWN)
        assert_field(stored, "revision_round", 0)
        assert_amount(
            stored.get("proposed_emissions_tpy"), 10.00, "proposed_emissions_tpy"
        )


class TestScreenCascadeVisibility:
    """PRD §3.2 makes the screen's whole fan-out visible to the caller at once."""

    def test_screen_response_exposes_its_own_cascade_immediately(
        self, api, area_k_submitted_application
    ):
        """One screen call returns the determination and leaves the plan in place.

        PRD §3.2: "The screen writes an **ApplicabilityDetermination** recording
        `permit_application_id`, the fired `trigger_codes`, the `result`, an
        `area_designation_snapshot` of the area's designation and an
        `ej_screen_score_snapshot` of its statewide score at determination time,
        the application's `revision_round` at determination time,
        `determined_by_user_id` set to the screening analyst's `X-User-ID`, and
        `application_version_after`." and "If at least one trigger fires, `result`
        is `ENHANCED_REQUIRED`, `review_track` becomes `ENHANCED`, the application
        moves `SUBMITTED → ENHANCED_REVIEW`, and the divergent side effect kicks
        in: a participation plan is created in `PLANNED` with its required comment
        days computed, unless the application already has a participation plan
        whose status is anything other than `CANCELLED`, in which case that
        existing plan's required comment days are recomputed instead."

        Design: Corner/consistency_model/screen_response_exposes_its_own_cascade_immediately
        """
        state = area_k_submitted_application
        response = api.screen_application(state["app_id"], ANALYST_HEADERS)

        determination = assert_created(response)
        assert_fields(
            determination,
            {
                "permit_application_id": state["app_id"],
                "result": DETERMINATION_ENHANCED_REQUIRED,
                "trigger_codes": [TRIGGER_FACILITY_TYPE],
                "area_designation_snapshot": DESIGNATION_UNDESIGNATED,
                # The application is on its first pass, so `revision_round` is 0.
                "revision_round": 0,
                "determined_by_user_id": "analyst-1",
                "application_version_after": 3,
            },
        )
        assert_amount(
            determination.get("ej_screen_score_snapshot"),
            0.00,
            "ej_screen_score_snapshot",
        )

        application = read_application(api, state["app_id"])
        assert_fields(
            application,
            {
                "status": APP_ENHANCED_REVIEW,
                "review_track": TRACK_ENHANCED,
                "version": 3,
            },
        )

        plans = assert_page(
            api.list_application_plans(state["app_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(plans[0], "status", PLAN_PLANNED)
        assert_field(plans[0], "required_comment_days", BASE_COMMENT_DAYS)
        # A `PLANNED` plan is not yet a running comment period.
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 0)


class TestApplicationVersionGuards:
    """PRD §2.7 requires the caller to prove it read the application's version."""

    def test_stale_application_version_on_assessment_create_is_rejected(
        self, api, area_k_screened
    ):
        """The pre-screen version cannot author an assessment after the screen.

        PRD §2.7: "Creating a cumulative impact assessment (`POST
        /ej/cumulative-impact-assessments`) requires
        `expected_application_version`, carrying the client's last observed
        `version` of the target `PermitApplication`." and "A mismatch against the
        application's current `version` is rejected with
        `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_on_assessment_create_rejected
        """
        state = area_k_screened
        assert state["v_submit"] == 2, "submit should take the application to version 2"
        assert state["v_screen"] == 3, "the screen should take it on to version 3"

        response = api.create_assessment(
            assessment_payload(
                permit_application_id=state["app_id"],
                expected_application_version=state["v_submit"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.STALE_APPLICATION_VERSION)

        assert_field(read_application(api, state["app_id"]), "version", 3)
        assert_empty_listing(
            api.list_application_assessments(state["app_id"], ANALYST_HEADERS)
        )

    def test_stale_application_version_on_condition_create_is_rejected(
        self, api, area_k_screened
    ):
        """The first condition bumped the version, so replaying it is refused.

        PRD §2.7: "Attaching a permit condition (`POST /ej/permit-conditions`)
        likewise requires `expected_application_version` and is rejected with
        `ERR_STALE_APPLICATION_VERSION` (HTTP 412) on mismatch." and "Every
        condition rewrites `total_mitigation_credit_tpy` and
        `residual_impact_index`, so an author working from a stale mitigation
        picture would size a control requirement against a residual index that no
        longer exists."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_on_condition_create_rejected
        """
        state = area_k_screened
        version_at_screen = state["v_screen"]
        first = add_condition(
            api,
            state,
            CONDITION_ADDITIONAL_CONTROL,
            reduction_tpy=5.00,
            enforceable=True,
        )
        version_after_first = first["application_version_after"]

        response = api.create_permit_condition(
            condition_payload(
                permit_application_id=state["app_id"],
                condition_type=CONDITION_MONITORING,
                reduction_tpy=10.00,
                enforceable=True,
                expected_application_version=version_at_screen,
                monitoring_frequency=MONITORING_CONTINUOUS,
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.STALE_APPLICATION_VERSION)

        stored_condition = find_condition(api, state["app_id"], first["id"])
        assert_amount(stored_condition.get("credit_tpy"), 5.00, "credit_tpy")

        application = read_application(api, state["app_id"])
        assert_amount(
            application.get("total_mitigation_credit_tpy"),
            5.00,
            "total_mitigation_credit_tpy",
        )
        assert_field(application, "version", version_after_first)
        assert_page(
            api.list_application_conditions(state["app_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
