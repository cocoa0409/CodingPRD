"""Curative requirements: flag cascade, waiver safety, segregation of duties (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    approve_report,
    assert_curative_requirement,
    create_curative,
    create_document,
    drive_report_under_review,
    get_order,
    get_success_data,
    make_abstracter_headers,
    make_examiner_headers,
    make_ops_headers,
    satisfy_curative,
    setup_order_with_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFlagCascade:
    def _setup_lien_order(self, api):
        ctx = setup_order_with_assignment(
            "client_732", "abs_732", search_type="LIEN_JUDGMENT_TAX"
        )
        doc = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_732",
            instrument_type="LIEN",
            grantor_name="B Jones",
            grantee_name="IRS",
            instrument_number="INST-732-A",
            recording_date="2019-04-15",
        )
        ctx["document"] = doc
        return ctx

    def test_flag_raises_system_curative_with_document_link_and_severity(self, api):
        """PRD §3.4: "Flagging a document moves it from `REPORTED` to
        `FLAGGED_FOR_CURATIVE` and, as a cascade, raises a `CurativeRequirement` on
        the order with `record_document_id` pointing at the flagged document,
        `raised_by_examiner_ref` left null (the system raised it), `description`
        set to the supplied `reason`, and `severity` of `CRITICAL` when the
        instrument is a `LIEN`, `JUDGMENT`, or `TAX_LIEN` and `STANDARD` otherwise;
        the order's `open_curative_count` increments by one."

        Design: Difficulty/transitive_cascade/flag_document_cascade_raises_curative_and_bumps_order_count
        """
        ctx = self._setup_lien_order(api)
        flagged = api.flag_record_document(
            ctx["document"]["id"],
            {"reason": "open federal tax lien of record"},
            make_abstracter_headers("abs_732"),
        )
        doc = validate_success(flagged, 200)
        assert doc["status"] == "FLAGGED_FOR_CURATIVE"

        curatives, meta = validate_paginated(
            api.list_curative_requirements(
                make_ops_headers(), params={"order_id": ctx["order"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "exactly one requirement must be raised by the flag"
        curative = curatives[0]
        assert_curative_requirement(curative)
        assert curative["record_document_id"] == ctx["document"]["id"]
        assert curative["severity"] == "CRITICAL", "LIEN maps to CRITICAL severity"
        assert curative["raised_by_examiner_ref"] is None, "system-raised carries a null raiser"
        assert curative["status"] == "OPEN"
        assert curative["description"] == "open federal tax lien of record"

    def test_flag_increments_order_open_curative_count(self, api):
        """PRD §3.4: "Flagging a document moves it from `REPORTED` to
        `FLAGGED_FOR_CURATIVE` and, as a cascade, raises a `CurativeRequirement` on
        the order with `record_document_id` pointing at the flagged document,
        `raised_by_examiner_ref` left null (the system raised it), `description`
        set to the supplied `reason`, and `severity` of `CRITICAL` when the
        instrument is a `LIEN`, `JUDGMENT`, or `TAX_LIEN` and `STANDARD` otherwise;
        the order's `open_curative_count` increments by one."

        Design: Difficulty/transitive_cascade/flag_document_cascade_raises_curative_and_bumps_order_count
        """
        ctx = self._setup_lien_order(api)
        assert get_order(ctx["order"]["id"])["open_curative_count"] == 0

        flagged = api.flag_record_document(
            ctx["document"]["id"],
            {"reason": "open federal tax lien of record"},
            make_abstracter_headers("abs_732"),
        )
        validate_success(flagged, 200)

        order = get_order(ctx["order"]["id"])
        assert order["open_curative_count"] == 1, (
            f"the curative creation must bump the order counter, got {order['open_curative_count']}"
        )


class TestWaiverSafety:
    def _setup_flagged_critical(self, api, client_ref, abstracter_ref):
        ctx = setup_order_with_assignment(
            client_ref, abstracter_ref, search_type="LIEN_JUDGMENT_TAX"
        )
        doc = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            abstracter_ref,
            instrument_type="LIEN",
            grantor_name="B",
            grantee_name="IRS",
            instrument_number="INST-FLAG-1",
            recording_date="2018-01-01",
        )
        flagged = api.flag_record_document(
            doc["id"], {"reason": "open tax lien"}, make_abstracter_headers(abstracter_ref)
        )
        validate_success(flagged, 200)
        curatives, _ = validate_paginated(
            api.list_curative_requirements(
                make_ops_headers(), params={"order_id": ctx["order"]["id"]}
            )
        )
        ctx["document"] = doc
        ctx["curative"] = curatives[0]
        return ctx

    def test_critical_curative_waive_rejected(self, api):
        """PRD §3.8: "a requirement whose `severity` is `CRITICAL` cannot be waived
        at all (`ERR_CRITICAL_NOT_WAIVABLE`, HTTP 422), and segregation of duties
        forbids the waiving examiner from being the same examiner who raised it, so
        a waiver is refused with `ERR_SOD_WAIVER_FORBIDDEN` (HTTP 403) whenever
        `raised_by_examiner_ref` is non-null and equals the caller's `X-User-ID` —
        a system-raised requirement, whose raiser is null, may be waived by any
        examiner."

        Design: Corner/validations/critical_curative_waive_rejected
        """
        ctx = self._setup_flagged_critical(api, "client_833", "abs_833")
        assert ctx["curative"]["severity"] == "CRITICAL", "setup sanity"
        assert ctx["curative"]["raised_by_examiner_ref"] is None, (
            "system-raised raiser is null, so segregation cannot mask the severity rule"
        )

        resp = api.waive_curative_requirement(
            ctx["curative"]["id"],
            {"resolution_note": "waive attempt on critical"},
            make_examiner_headers("ex_833"),
        )
        validate_error(resp, ApiErrorId.ERR_CRITICAL_NOT_WAIVABLE)

    def test_waive_on_closed_curative_surfaces_state_error(self, api):
        """PRD §3.8: "waiver carries two safety checks, evaluated after the generic
        guards: a requirement whose `severity` is `CRITICAL` cannot be waived at
        all (`ERR_CRITICAL_NOT_WAIVABLE`, HTTP 422)"
        PRD §2.10: "then the terminal-order guard, then generic state-transition
        legality (409), and only then the domain business rules — waiver safety,
        temporal windows, overlap and buffer conflicts, uniqueness, OCC staleness —
        each at its declared position. When several rules could reject the same
        request, the one earliest in this order is the error the client receives;
        for example, an attempt to post a fee against a retrieval that is already
        `INVOICED` on an already-delivered order surfaces `ERR_ALREADY_INVOICED`,
        never `ERR_ORDER_TERMINAL`."

        Design: Difficulty/priority_pair_validation_conflict/waive_satisfied_critical_curative_state_error_beats_safety_error
        """
        ctx = self._setup_flagged_critical(api, "client_741", "abs_741")
        satisfy_curative(
            ctx["curative"]["id"], "lien released per recorded release INST-741-R", "abs_741"
        )

        resp = api.waive_curative_requirement(
            ctx["curative"]["id"],
            {"resolution_note": "waive attempt on closed critical item"},
            make_examiner_headers("ex_741"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            f"state category (409) must beat waiver safety (422), got {resp.status_code}"
        )

    def test_rejected_waive_leaves_satisfied_curative_untouched(self, api):
        """PRD §3.8: "The assigned abstracter satisfies a requirement by supplying
        a `resolution_note`, moving it from `OPEN` to `SATISFIED` and decrementing
        `open_curative_count`."

        Design: Difficulty/priority_pair_validation_conflict/waive_satisfied_critical_curative_state_error_beats_safety_error
        """
        ctx = self._setup_flagged_critical(api, "client_741", "abs_741")
        satisfy_curative(
            ctx["curative"]["id"], "lien released per recorded release INST-741-R", "abs_741"
        )
        resp = api.waive_curative_requirement(
            ctx["curative"]["id"],
            {"resolution_note": "waive attempt on closed critical item"},
            make_examiner_headers("ex_741"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(
            api.get_curative_requirement(ctx["curative"]["id"], make_ops_headers())
        )
        assert after["status"] == "SATISFIED", "rejected waive fires no side effects"
        assert after["resolution_note"] == "lien released per recorded release INST-741-R"

    def test_sod_waiver_by_raising_examiner_forbidden(self, api):
        """PRD §3.8: "a requirement whose `severity` is `CRITICAL` cannot be waived
        at all (`ERR_CRITICAL_NOT_WAIVABLE`, HTTP 422), and segregation of duties
        forbids the waiving examiner from being the same examiner who raised it, so
        a waiver is refused with `ERR_SOD_WAIVER_FORBIDDEN` (HTTP 403) whenever
        `raised_by_examiner_ref` is non-null and equals the caller's `X-User-ID` —
        a system-raised requirement, whose raiser is null, may be waived by any
        examiner."

        Design: Corner/validations/sod_waiver_by_raising_examiner_forbidden
        """
        ctx = drive_report_under_review("client_832", "abs_832", "ex_832")
        curative = create_curative(
            ctx["order"]["id"],
            "ex_832",
            description="Confirm no unrecorded easements",
            severity="STANDARD",
        )
        assert curative["raised_by_examiner_ref"] == "ex_832"

        self_waive = api.waive_curative_requirement(
            curative["id"],
            {"resolution_note": "self-waiver attempt"},
            make_examiner_headers("ex_832"),
        )
        validate_error(self_waive, ApiErrorId.ERR_SOD_WAIVER_FORBIDDEN)

        other_waive = api.waive_curative_requirement(
            curative["id"],
            {"resolution_note": "reviewed by second examiner; acceptable risk"},
            make_examiner_headers("ex_832b"),
        )
        waived = validate_success(other_waive, 200)
        assert waived["status"] == "WAIVED"

        order = get_order(ctx["order"]["id"])
        assert order["open_curative_count"] == 0, "waiver decrements the open count"


class TestApprovalGateAndCounters:
    def test_approve_with_open_curative_requirement_rejected(self, api):
        """PRD §3.7: "Approval — moving the report from `UNDER_REVIEW` to
        `APPROVED` — requires that the caller be the booked `reviewer_examiner_ref`
        (else `ERR_FORBIDDEN`) and that no curative requirement on the order
        remains `OPEN` (else `ERR_OPEN_CURATIVE_REQUIREMENTS`, HTTP 409); approval
        moves the order from `REPORT_UNDER_REVIEW` to `READY_FOR_DELIVERY` and
        increments the order's `version`."

        Design: Difficulty/cross_entity_state_dependency/report_approve_blocked_by_open_curative_requirement
        """
        ctx = drive_report_under_review("client_761", "abs_761", "ex_761")
        create_curative(
            ctx["order"]["id"],
            "ex_761",
            description="Obtain missing marital status affidavit",
            severity="STANDARD",
        )

        resp = api.approve_abstract_report(ctx["report"]["id"], make_examiner_headers("ex_761"))
        validate_error(resp, ApiErrorId.ERR_OPEN_CURATIVE_REQUIREMENTS)

        report = get_success_data(
            api.get_abstract_report(ctx["report"]["id"], make_ops_headers())
        )
        assert report["status"] == "UNDER_REVIEW", "rejected approval leaves the report in review"

    def test_approve_succeeds_after_curative_satisfied(self, api):
        """PRD §3.7: "approval moves the order from `REPORT_UNDER_REVIEW` to
        `READY_FOR_DELIVERY` and increments the order's `version`."
        PRD §3.8: "The assigned abstracter satisfies a requirement by supplying a
        `resolution_note`, moving it from `OPEN` to `SATISFIED` and decrementing
        `open_curative_count`."

        Design: Difficulty/cross_entity_state_dependency/report_approve_blocked_by_open_curative_requirement
        """
        ctx = drive_report_under_review("client_761", "abs_761", "ex_761")
        curative = create_curative(
            ctx["order"]["id"],
            "ex_761",
            description="Obtain missing marital status affidavit",
            severity="STANDARD",
        )
        blocked = api.approve_abstract_report(ctx["report"]["id"], make_examiner_headers("ex_761"))
        validate_error(blocked, ApiErrorId.ERR_OPEN_CURATIVE_REQUIREMENTS)

        satisfy_curative(curative["id"], "affidavit obtained and recorded", "abs_761")
        order = get_order(ctx["order"]["id"])
        assert order["open_curative_count"] == 0

        approved = approve_report(ctx["report"]["id"], "ex_761")
        assert approved["status"] == "APPROVED"
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "READY_FOR_DELIVERY"

    def test_derived_counters_reconcile_immediately(self, api):
        """PRD §3.8: "every requirement opens in `OPEN` status with
        `resolution_note` null, and each opening increments the order's
        `open_curative_count` by one — a read-only tally of how many requirements
        remain open."
        PRD §3.8: "The assigned abstracter satisfies a requirement by supplying a
        `resolution_note`, moving it from `OPEN` to `SATISFIED` and decrementing
        `open_curative_count`."

        Design: Corner/cross_cutting_layers/derived_counters_reconcile_immediately
        """
        ctx = setup_order_with_assignment("client_874", "abs_874")
        curative = create_curative(
            ctx["order"]["id"],
            "ex_874",
            description="Obtain release of expired mechanic lien",
            severity="LOW",
        )
        order_after_raise = get_order(ctx["order"]["id"])
        assert order_after_raise["open_curative_count"] == 1, (
            "the raise is visible on the immediately following read"
        )

        satisfy_curative(curative["id"], "release recorded", "abs_874")
        order_after_satisfy = get_order(ctx["order"]["id"])
        assert order_after_satisfy["open_curative_count"] == 0, (
            "satisfy reconciles the counter in the same request"
        )
