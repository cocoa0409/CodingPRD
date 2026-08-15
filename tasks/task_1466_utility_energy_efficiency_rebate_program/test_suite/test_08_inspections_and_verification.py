"""Inspections and verification: scheduling gates, completion ordering and
cascades, verification entry paths, measured-input validation, and the
deemed-versus-measured savings variants."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    assert_inspection,
    attach_savings_claim,
    create_draft_application,
    submit_application,
    build_application_requiring_inspection,
    build_post_inspection_application,
    build_submitted_application,
    complete_inspection,
    create_active_ally,
    create_inspection_schedule_payload,
    create_open_program,
    get_application,
    get_inspection,
    get_line_item,
    get_program_year,
    get_savings_claim,
    get_trade_ally,
    validate_error,
    validate_paginated,
    validate_success,
    verify_application,
)

LARGE_CLAIM_MEASURE = {"base_rate_cents": 5_000, "deemed_kwh_per_unit": 10_001}


def _open_program_with_large_claim_measure():
    """Open program whose only measure triggers the large-claim inspection
    override (deemed_kwh_per_unit 10001 >= 10000) for quantity 1."""
    return create_open_program(measure_specs=[dict(LARGE_CLAIM_MEASURE)])


class TestInspectionScheduling:
    def test_schedule_pre_inspection_when_not_required_returns_error(
        self, api, admin_headers
    ):
        """PRD §3.5: "Scheduling requires the application to be in `SUBMITTED` —
        the state check runs first — and `inspection_required` to be true;
        attempting it on an unflagged application yields
        `ERR_INSPECTION_NOT_REQUIRED` (HTTP 409)."

        Design: Corner/validations/schedule_pre_inspection_when_not_required_returns_error
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_submitted_application(py, ally, measures[0])
        assert app["inspection_required"] is False

        res = api.schedule_pre_inspection(
            app["id"], create_inspection_schedule_payload(), admin_headers
        )
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_REQUIRED, expected_status=409)

    def test_inspection_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "`ERR_INSPECTION_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`,
        `ERR_SAVINGS_CLAIM_NOT_FOUND`, or `ERR_ADJUSTMENT_NOT_FOUND` (all HTTP
        404)."

        Design: Corner/entities/inspection_not_found_returns_404
        """
        res = api.get_inspection(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_FOUND, expected_status=404)

    def test_inspections_filtered_by_application(self, api, admin_headers):
        """PRD §3.5: "Inspection listings filter by `application_id`,
        `inspection_kind`, and `outcome`."

        Design: Corner/endpoints/get_inspections_filtered_by_application
        """
        py, measures = _open_program_with_large_claim_measure()
        ally = create_active_ally()
        app, _line, insp = build_application_requiring_inspection(
            py, ally, measures[0]
        )

        data, meta = validate_paginated(
            api.list_inspections(admin_headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert_inspection(data[0])
        assert data[0]["application_id"] == app["id"]
        assert data[0]["inspection_kind"] == "PRE"
        assert data[0]["outcome"] == "PENDING"


class TestInspectionCompletion:
    def test_failed_without_reason_returns_error(self, api, admin_headers, inspector_headers):
        """PRD §3.5: "a `FAILED` outcome must carry a non-empty `fail_reason`,
        which stays null on a pass. The completion checks run in a fixed order:
        the program-open gate, then the parent application's state must permit
        the completion — `PRE_INSPECTION` for a pre-installation inspection,
        `POST_INSPECTION` for a post-installation one (`ERR_INVALID_STATE`) —
        then the fail-reason requirement (`ERR_FAIL_REASON_REQUIRED`, HTTP 422),
        and only then the guard against double completion
        (`ERR_INSPECTION_ALREADY_COMPLETED`, HTTP 409)."

        Design: Corner/validations/inspection_failed_without_reason_returns_error
        """
        py, measures = _open_program_with_large_claim_measure()
        ally = create_active_ally()
        _app, _line, insp = build_application_requiring_inspection(
            py, ally, measures[0]
        )

        res = api.complete_inspection(insp["id"], {"outcome": "FAILED"}, inspector_headers)
        validate_error(res, ApiErrorId.ERR_FAIL_REASON_REQUIRED, expected_status=422)

    def test_complete_twice_returns_already_completed(
        self, api, admin_headers, inspector_headers
    ):
        """PRD §3.5: "A passed post-installation inspection leaves the
        application in `POST_INSPECTION`."
        PRD §3.5: "and only then the guard against double completion
        (`ERR_INSPECTION_ALREADY_COMPLETED`, HTTP 409)."

        Design: Corner/state_machines/inspection_complete_twice_returns_already_completed
        """
        # Use a POST-kind inspection: after it passes, the parent application
        # remains in POST_INSPECTION, so the parent-state check still permits
        # the completion attempt and the double-completion guard is reached.
        py, measures = _open_program_with_large_claim_measure()
        ally = create_active_ally()
        app, _line, _pre = build_post_inspection_application(py, ally, measures[0])
        assert app["status"] == "POST_INSPECTION"

        post = validate_success(
            api.schedule_post_inspection(
                app["id"], create_inspection_schedule_payload(), admin_headers
            ),
            201,
        )
        assert post["inspection_kind"] == "POST"
        assert post["outcome"] == "PENDING"

        completed = complete_inspection(post, "PASSED")
        assert completed["outcome"] == "PASSED"
        assert get_application(app["id"])["status"] == "POST_INSPECTION"

        res = api.complete_inspection(post["id"], {"outcome": "PASSED"}, inspector_headers)
        validate_error(
            res, ApiErrorId.ERR_INSPECTION_ALREADY_COMPLETED, expected_status=409
        )


class TestFailedInspectionCascade:
    def _five_submitted_apps(self, api):
        """Five same-day submissions; the fifth is inspection-required via
        index sampling. Returns (py, ally, measure, apps)."""
        py, measures = create_open_program()
        ally = create_active_ally()
        apps = [
            build_submitted_application(py, ally, measures[0])[0]
            for _ in range(5)
        ]
        return py, ally, measures[0], apps

    def test_failed_pre_inspection_rejects_application_and_releases_budget(
        self, api, admin_headers
    ):
        """PRD §3.5: "A failed inspection of either kind moves the parent
        application to `REJECTED`, releases its `incentive_total_cents` from the
        program year's `committed_cents`, and increments the program year's
        `version` alongside the application's and the inspection's."

        Design: Difficulty/transitive_cascade/inspection_failed_cascade_depth3
        """
        py, ally, measure, apps = self._five_submitted_apps(api)
        app5 = apps[4]
        assert app5["inspection_required"] is True
        py_mid = get_program_year(py["id"])
        assert py_mid["committed_cents"] == 50_000

        insp = validate_success(
            api.schedule_pre_inspection(
                app5["id"], create_inspection_schedule_payload(), admin_headers
            ),
            201,
        )
        completed = complete_inspection(
            insp, "FAILED", fail_reason="Measure not installed as claimed"
        )
        assert completed["outcome"] == "FAILED"
        assert completed["completed_on"] is not None

        app5_after = get_application(app5["id"])
        assert app5_after["status"] == "REJECTED"

        py_after = get_program_year(py["id"])
        assert py_after["committed_cents"] == 40_000

    def test_failed_pre_inspection_recomputes_ally_performance(
        self, api, admin_headers
    ):
        """PRD §3.2: "Whenever an inspection is completed — pass or fail, pre-
        or post-installation — the installing ally's `performance_score` is
        recomputed across every completed inspection belonging to that ally's
        applications, in any program year: one hundred times the number of
        `PASSED` inspections divided by the number of completed inspections
        (those `PASSED` or `FAILED`), rounded half-up to a whole number."
        PRD §3.2: "`PREFERRED` at ninety or above, `STANDARD` at seventy or
        above, and `PROBATION` below seventy."

        Design: Difficulty/transitive_cascade/inspection_failed_cascade_depth3
        """
        py, ally, measure, apps = self._five_submitted_apps(api)
        app5 = apps[4]
        insp = validate_success(
            api.schedule_pre_inspection(
                app5["id"], create_inspection_schedule_payload(), admin_headers
            ),
            201,
        )
        complete_inspection(insp, "FAILED", fail_reason="Measure not installed as claimed")

        ally_after = get_trade_ally(ally["id"])
        # 0 PASSED of 1 completed -> score 0 -> PROBATION.
        assert ally_after["performance_score"] == 0
        assert ally_after["standing_tier"] == "PROBATION"


class TestVerificationGates:
    def test_verify_when_inspection_required_returns_error(
        self, api, admin_headers, inspector_headers
    ):
        """PRD §3.5: "From `SUBMITTED`, direct verification additionally
        requires `inspection_required` to be false; otherwise the refusal is
        `ERR_INSPECTION_REQUIRED_OUTSTANDING` (HTTP 409)."

        Design: Corner/validations/verify_when_inspection_required_but_not_completed_returns_error
        """
        py, measures = _open_program_with_large_claim_measure()
        ally = create_active_ally()
        app, _line = build_submitted_application(py, ally, measures[0])
        assert app["inspection_required"] is True

        res = api.verify_application(app["id"], inspector_headers)
        validate_error(
            res, ApiErrorId.ERR_INSPECTION_REQUIRED_OUTSTANDING, expected_status=409
        )
        assert get_application(app["id"])["status"] == "SUBMITTED"

    def test_verify_from_post_inspection_without_post_passed_returns_error(
        self, api, admin_headers, inspector_headers
    ):
        """PRD §3.5: "From `POST_INSPECTION`, verification additionally requires
        a passed post-installation inspection on the application; otherwise the
        refusal is `ERR_POST_INSPECTION_NOT_PASSED` (HTTP 409)."

        Design: Corner/validations/verify_from_post_inspection_without_post_passed_returns_error
        """
        py, measures = _open_program_with_large_claim_measure()
        ally = create_active_ally()
        app, _line, _pre = build_post_inspection_application(py, ally, measures[0])
        assert app["status"] == "POST_INSPECTION"

        res = api.verify_application(app["id"], inspector_headers)
        validate_error(
            res, ApiErrorId.ERR_POST_INSPECTION_NOT_PASSED, expected_status=409
        )
        assert get_application(app["id"])["status"] == "POST_INSPECTION"

    def test_measured_claim_with_post_not_below_pre_returns_invalid(
        self, api, admin_headers, inspector_headers
    ):
        """PRD §3.5: "for every line whose savings claim is `MEASURED`, both
        `pre_annual_kwh` and `post_annual_kwh` must be present, with the
        post-retrofit figure strictly below the pre-retrofit figure, or
        verification is refused with `ERR_INVALID_MEASURED_INPUT` (HTTP 422)."

        Design: Corner/validations/measured_claim_with_post_greater_than_pre_returns_invalid
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_submitted_application(
            py, ally, measures[0], claim=("MEASURED", 5_000, 8_000)
        )

        res = api.verify_application(app["id"], inspector_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_MEASURED_INPUT, expected_status=422)
        assert get_application(app["id"])["status"] == "SUBMITTED"


class TestDeemedVsMeasuredSavings:
    def _program_with_400kwh_measure(self):
        return create_open_program(
            measure_specs=[{"base_rate_cents": 10_000, "deemed_kwh_per_unit": 400}]
        )

    def test_measured_claim_overrides_deemed_value(self, api, admin_headers):
        """PRD §3.5: "A `MEASURED` line instead takes the metered delta — its
        `measured_kwh` is the claim's `pre_annual_kwh` minus its
        `post_annual_kwh`, and the line's `final_kwh` equals that
        `measured_kwh`"
        PRD §3.5: "The application's `final_kwh` is the sum across its lines and
        is locked once the application reaches `VERIFIED`."

        Design: Difficulty/dual_variant_calc/savings_claim_deemed_vs_measured_on_line_item
        """
        py, measures = self._program_with_400kwh_measure()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        line = add_line_item(app, measures[0], quantity=5, ally=ally)
        claim = attach_savings_claim(
            line, ally, "MEASURED", pre_annual_kwh=12_500, post_annual_kwh=9_800
        )
        app = submit_application(app, ally)
        # Deemed at submission: 400 * 5.
        assert app["claimed_kwh"] == 2_000

        app = verify_application(app)
        assert app["status"] == "VERIFIED"
        # Measured delta: 12500 - 9800 = 2700 — diverges from the deemed 2000.
        assert app["final_kwh"] == 2_700
        assert app["final_kwh"] != app["claimed_kwh"]

        line_after = get_line_item(line["id"])
        assert line_after["measured_kwh"] == 2_700
        assert line_after["final_kwh"] == 2_700

    def test_measured_claim_persists_computed_kwh(self, api, admin_headers):
        """PRD §3.5: "Each claim's `computed_kwh` is persisted equal to its
        line's finalized value: for `DEEMED`, the line's `claimed_kwh`; for
        `MEASURED`, the pre-minus-post delta."

        Design: Difficulty/dual_variant_calc/savings_claim_deemed_vs_measured_on_line_item
        """
        py, measures = self._program_with_400kwh_measure()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        line = add_line_item(app, measures[0], quantity=5, ally=ally)
        claim = attach_savings_claim(
            line, ally, "MEASURED", pre_annual_kwh=12_500, post_annual_kwh=9_800
        )
        app = submit_application(app, ally)
        verify_application(app)

        claim_after = get_savings_claim(claim["id"])
        assert claim_after["computed_kwh"] == 2_700

    def test_deemed_claim_keeps_submission_value(self, api, admin_headers):
        """PRD §3.5: "A line with no savings claim, or a `DEEMED` claim, keeps
        its submission-pinned value: its `final_kwh` equals its `claimed_kwh`."
        PRD §3.5: "while `measured_kwh` remains unset (null) on deemed lines."
        PRD §3.5: "Each claim's `computed_kwh` is persisted equal to its line's
        finalized value: for `DEEMED`, the line's `claimed_kwh`; for `MEASURED`,
        the pre-minus-post delta."

        Design: Difficulty/dual_variant_calc/savings_claim_deemed_vs_measured_on_line_item
        """
        py, measures = self._program_with_400kwh_measure()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        line = add_line_item(app, measures[0], quantity=5, ally=ally)
        claim = attach_savings_claim(line, ally, "DEEMED")
        app = submit_application(app, ally)
        assert app["claimed_kwh"] == 2_000

        app = verify_application(app)
        assert app["final_kwh"] == 2_000

        line_after = get_line_item(line["id"])
        assert line_after["final_kwh"] == 2_000
        assert line_after["measured_kwh"] is None

        claim_after = get_savings_claim(claim["id"])
        assert claim_after["computed_kwh"] == 2_000
