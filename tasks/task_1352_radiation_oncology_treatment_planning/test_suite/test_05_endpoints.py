"""Endpoint-level claims: not-found, pagination envelope, error envelope,
logical-clock default, successor listing."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS,
    create_patient_payload, create_plan_payload, create_dose_constraint_payload,
    setup_patient, setup_machine, setup_course, setup_treatment_ready_linac,
    setup_on_treatment, book_session, deliver_session,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestNotFound:
    def test_get_patient_not_found_returns_404(self):
        """PRD §2.5 (priority 3): "Every identifier in the URL path is validated
        left-to-right, and the first identifier that does not resolve to an
        existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/endpoints/get_patient_not_found_returns_404
        """
        resp = api_client.get_patient("00000000-0000-4000-8000-00000000dead", SCHED)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestPagination:
    def test_list_pagination_envelope(self):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 ... `offset` sets the number of items skipped and
        defaults to 0. ... The `meta` object of a list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        With 12 patients the first page returns 10 rows (has_more true) and
        offset 10 returns 2 rows (has_more false).

        Design: Corner/endpoints/list_pagination_envelope
        """
        for i in range(1, 13):
            get_success_data(api_client.create_patient(
                create_patient_payload(mrn=f"MRN-PG-{i:02d}", full_name=f"Page {i}"), SCHED))
        page1, meta1 = validate_paginated(api_client.list_patients(SCHED))
        assert len(page1) == 10, "default limit 10"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api_client.list_patients(SCHED, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_response_envelope_shape(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a `data`
        object carrying "`error_id`" plus "a human-readable explanation of the
        error" in `message`.

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api_client.get_machine("00000000-0000-4000-8000-00000000dead", ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert isinstance(err.get("message"), str) and err["message"], \
            "error envelope must carry a non-empty message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, \
            "error meta contains only request id and timestamp"


class TestLogicalClock:
    def test_clock_default_governs_machine_down_cascade(self):
        """PRD §2.8: "at startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time."
        PRD §3.8: "every fraction session on that machine still `SCHEDULED` with
        a `start_time` at or after the current logical time is cancelled with
        `cancellation_reason` `MACHINE_DOWN`" and per affected course "the
        system creates an interruption of its own: `reason` `MACHINE_DOWN` ...
        status `OPEN`".
        A session on 2026-08-03 is future relative to the startup default, so
        setting the LINAC DOWN cancels it and opens one interruption.

        Design: Corner/endpoints/clock_default_governs_machine_down_cascade
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-EP-CLK", total_dose=2000, fractions=10)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                            "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        get_success_data(api_client.set_machine_status(ctx["linac"]["id"], {"status": "DOWN"}, ADMIN))
        sessions = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], SCHED))[0]
        target = [s for s in sessions if s["id"] == sess["id"]][0]
        assert target["status"] == "CANCELLED"
        assert target["cancellation_reason"] == "MACHINE_DOWN"
        interruptions = validate_paginated(
            api_client.list_interruptions(ctx["course"]["id"], SCHED))[0]
        assert len(interruptions) == 1
        itr = interruptions[0]
        assert itr["reason"] == "MACHINE_DOWN"
        assert itr["missed_count"] == 1
        assert itr["status"] == "OPEN"


class TestPlanSuccessors:
    def test_plan_successors_list_after_adaptation(self):
        """PRD §3.4: "Plans form a supersession chain: clients can list the
        plans whose `supersedes_plan_id` points at a given plan (its
        successors)". After one adaptation replan, the original plan's successor
        list holds exactly the adaptation plan; the adaptation plan's list is
        empty.

        Design: Corner/endpoints/plan_successors_list_after_adaptation
        """
        ctx = setup_on_treatment(num_delivered=1, total_dose=2000, fractions=10,
                                 mrn="MRN-EP-SUC")
        plan_a = ctx["plan"]
        adapt = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.0}, ONC_A))
        plan_b = get_success_data(api_client.create_plan(
            ctx["course"]["id"],
            create_plan_payload(contour_set_id=ctx["contour"]["id"],
                                target_total_dose_cGy=1800, planned_fractions=9,
                                supersedes_plan_id=plan_a["id"],
                                expected_course_version=adapt["version"]),
            DOS_A))
        succ_a = validate_success(api_client.list_plan_successors(plan_a["id"], DOS_A))
        assert isinstance(succ_a, list) and len(succ_a) == 1
        assert succ_a[0]["id"] == plan_b["id"]
        succ_b = validate_success(api_client.list_plan_successors(plan_b["id"], DOS_A))
        assert succ_b == []
