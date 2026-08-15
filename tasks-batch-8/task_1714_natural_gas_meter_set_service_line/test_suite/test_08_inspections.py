"""Inspection scheduling: half-open windows, certification gates, fail/reinspect loop."""
from test_helpers import (
    ApiErrorId,
    create_inspection_payload,
    create_inspector_payload,
    get_success_data,
    make_inspector_headers,
    setup_draft_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInspectorWindowSemantics:
    def test_back_to_back_adjacency_allowed(self, api, coordinator_headers, admin_headers):
        """PRD §3.4: "Because the intervals are half-open, back-to-back adjacency — one window's end exactly equal to the next window's start — is allowed."

        Design: Difficulty/resource_temporal_overlap/inspector_windows_half_open_adjacency
        """
        ctx = setup_draft_app()
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        first = get_success_data(
            api.create_inspection(
                create_inspection_payload(ctx["app"]["id"], inspector["id"]),
                coordinator_headers,
            )
        )
        assert first["status"] == "SCHEDULED"

        # [660, 720) starts exactly when [540, 660) ends.
        adjacent = get_success_data(
            api.create_inspection(
                create_inspection_payload(
                    ctx["app"]["id"], inspector["id"], start_minute=660, end_minute=720
                ),
                coordinator_headers,
            )
        )
        assert adjacent["status"] == "SCHEDULED", (
            "start == existing end is legal under half-open interval semantics"
        )

    def test_overlapping_window_conflicts(self, api, coordinator_headers, admin_headers):
        """PRD §3.4: "a new inspection conflicts when its start falls before an existing inspection's end while its end falls after that inspection's start, and the conflict is rejected with `ERR_INSPECTOR_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspector_windows_half_open_adjacency
        """
        ctx = setup_draft_app()
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        get_success_data(
            api.create_inspection(
                create_inspection_payload(ctx["app"]["id"], inspector["id"]),
                coordinator_headers,
            )
        )

        # [650, 700): 650 < 660 and 700 > 540 — overlaps [540, 660).
        resp = api.create_inspection(
            create_inspection_payload(
                ctx["app"]["id"], inspector["id"], start_minute=650, end_minute=700
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT, expected_status=409)


class TestInspectionLifecycle:
    def test_fail_reschedule_pass_cycle(self, api, coordinator_headers, admin_headers):
        """PRD §3.4: "A pass moves the inspection to the terminal `COMPLETED_PASS`; a fail moves it to `COMPLETED_FAIL`, which is deliberately non-terminal so the fail-reschedule-reinspect loop can cycle."
        PRD §3.4: "The coordinator may reschedule a failed inspection — or one the clock swept from `SCHEDULED` to `EXPIRED` — back to `SCHEDULED` with a fresh `inspection_date`, `start_minute`, and `end_minute`, re-running the same creation-time checks: date not in the past, certification coverage, and window conflict."

        Design: Corner/state_machines/inspection_fail_reschedule_cycle
        """
        ctx = setup_draft_app()
        inspector = get_success_data(
            api.create_inspector(
                create_inspector_payload(full_name="Insp Lee",
                                         certifications=["FINAL_SAFETY"]),
                admin_headers,
            )
        )
        inspection = get_success_data(
            api.create_inspection(
                create_inspection_payload(
                    ctx["app"]["id"], inspector["id"],
                    inspection_type="FINAL_SAFETY", end_minute=600,
                ),
                coordinator_headers,
            )
        )
        inspector_headers = make_inspector_headers(inspector["id"])
        failed = get_success_data(
            api.record_inspection_result(
                inspection["id"], {"result": "FAIL", "notes": "venting defect"},
                inspector_headers,
            )
        )
        assert failed["status"] == "COMPLETED_FAIL"

        resp = api.reschedule_inspection(
            inspection["id"],
            {"inspection_date": "2026-08-13", "start_minute": 600, "end_minute": 660},
            coordinator_headers,
        )
        rescheduled = validate_success(resp)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["inspection_date"] == "2026-08-13"
        assert rescheduled["start_minute"] == 600 and rescheduled["end_minute"] == 660

        passed = get_success_data(
            api.record_inspection_result(
                inspection["id"], {"result": "PASS", "notes": "rework verified"},
                inspector_headers,
            )
        )
        assert passed["status"] == "COMPLETED_PASS"


class TestInspectionCreationRules:
    def test_past_inspection_date_rejected(self, api, coordinator_headers, admin_headers):
        """PRD §3.4: "an `inspection_date` that must not lie in the past (`ERR_DATE_IN_PAST`)"

        Design: Corner/errors/inspection_past_date_rejected
        """
        ctx = setup_draft_app()  # clock pinned to 2026-08-01
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        resp = api.create_inspection(
            create_inspection_payload(
                ctx["app"]["id"], inspector["id"], inspection_date="2026-07-30"
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_IN_PAST, expected_status=422)

        resp = api.list_inspections(
            coordinator_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0

    def test_uncertified_inspector_rejected(self, api, coordinator_headers, admin_headers):
        """PRD §3.4: "the inspector's `certifications` — a subset of `PRESSURE_TEST`, `ROAD_CUT`, and `FINAL_SAFETY` — must contain the member matching the inspection type, else `ERR_INSPECTOR_NOT_CERTIFIED` (HTTP 422)."

        Design: Corner/errors/uncertified_inspector_rejected
        """
        ctx = setup_draft_app()
        inspector = get_success_data(
            api.create_inspector(
                create_inspector_payload(full_name="Insp Lee", certifications=["ROAD_CUT"]),
                admin_headers,
            )
        )
        resp = api.create_inspection(
            create_inspection_payload(
                ctx["app"]["id"], inspector["id"], inspection_type="FINAL_SAFETY"
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED, expected_status=422)

        resp = api.list_inspections(
            coordinator_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestInspectionOwnership:
    def test_wrong_inspector_cannot_record_result(self, api, coordinator_headers,
                                                  admin_headers):
        """PRD §3.4: "Results are personal. Only the inspector named on the inspection may record its outcome — anyone else's attempt meets `ERR_FORBIDDEN_OWNER`"
        PRD §2.1: "recording an inspection result compares the inspection's `inspector_id` to `X-User-ID`, again rejecting a mismatch with `ERR_FORBIDDEN_OWNER`."

        Design: Corner/rbac/wrong_inspector_cannot_record_result
        """
        ctx = setup_draft_app()
        insp_a = get_success_data(
            api.create_inspector(create_inspector_payload(full_name="Insp A"), admin_headers)
        )
        insp_b = get_success_data(
            api.create_inspector(create_inspector_payload(full_name="Insp B"), admin_headers)
        )
        inspection = get_success_data(
            api.create_inspection(
                create_inspection_payload(ctx["app"]["id"], insp_a["id"]),
                coordinator_headers,
            )
        )

        resp = api.record_inspection_result(
            inspection["id"], {"result": "PASS"}, make_inspector_headers(insp_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER, expected_status=403)

        after = get_success_data(api.get_inspection(inspection["id"], coordinator_headers))
        assert after["status"] == "SCHEDULED"
