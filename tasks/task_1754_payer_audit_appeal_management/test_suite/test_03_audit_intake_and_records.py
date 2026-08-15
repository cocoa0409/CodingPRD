"""Audit intake, claim-line guards, the records deadline (inclusive boundary,
missed-deadline auto-denial cascade, late submission revert), OCC on records
submissions, version increments, and the append-only event trail."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_claim_line,
    advance_clock,
    assert_case_event,
    begin_payer_review,
    create_audit_case,
    create_audit_case_payload,
    create_claim_line_payload,
    create_issue_code,
    create_payer,
    denied_outcome,
    get_case,
    get_line,
    is_valid_uuid,
    paid_outcome,
    post_determination,
    records_submission_payload,
    setup_case_past_records_deadline,
    setup_overlap_scenario,
    submit_records,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

HIM = TEST_USERS["him_headers"]
READER = TEST_USERS["reader_headers"]


class TestCaseCreation:
    def test_case_created_with_computed_records_deadline(self, api):
        """PRD §3.2: "A successfully intaked case starts in `RECEIVED` with
        `late_submission` false, all monetary totals at zero, and a computed
        `records_due_at` equal to `received_at` plus the payer's
        `records_submission_days` days — an inclusive deadline per §2.8."

        Design: Corner/entities/audit_case_created_with_computed_deadline
        """
        payer = create_payer(name="P1", records_submission_days=30)
        case = validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"], "RAC_COMPLEX",
                                      "2026-08-01T00:00:00Z"), HIM), 201)
        assert case["records_due_at"] == "2026-08-31T00:00:00Z"
        assert case["status"] == "RECEIVED"
        assert case["late_submission"] is False
        assert case["total_billed_cents"] == 0
        assert case["total_denied_active_cents"] == 0
        assert case["total_upheld_cents"] == 0

    def test_get_missing_case_returns_not_found(self, api, reader_headers):
        """PRD §2.9: "Existence — every path identifier and every foreign-key
        reference in the body must resolve, checked left to right, else
        `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_missing_case_returns_not_found
        """
        resp = api.get_audit_case(NON_EXISTENT_UUID, reader_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClaimLineGuards:
    def test_empty_service_interval_rejected(self, api, him_headers):
        """PRD §3.2: "The service interval is half-open — the start date
        inclusive, the end date exclusive — and the end must be strictly after
        the start; the billed amount must be positive. Malformed intervals or
        non-positive amounts fail with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/claim_line_invalid_interval_rejected
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        resp = api.add_claim_line(
            case["id"],
            create_claim_line_payload("L-1", "PA-1", "2026-01-10T00:00:00Z",
                                      "2026-01-10T00:00:00Z", 1000),
            him_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_overlapping_interval_in_other_open_case_rejected(self, api,
                                                              him_headers):
        """PRD §3.2: "Adding a line is rejected with
        `ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT` (HTTP 409) when another claim line
        already exists that belongs to a different case of the same payer,
        whose case is not `CLOSED`, which carries the same `claim_number`, and
        whose service interval overlaps the new one."

        Design: Difficulty/resource_temporal_overlap/claim_interval_overlap_half_open
        """
        scn = setup_overlap_scenario()
        resp = api.add_claim_line(
            scn["c2"]["id"],
            create_claim_line_payload("CLM-9", "PA-1", "2026-01-05T00:00:00Z",
                                      "2026-01-12T00:00:00Z", 50000),
            him_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT)

    def test_adjacent_interval_and_other_payer_accepted(self, api, him_headers):
        """PRD §3.2: "Under the half-open convention, overlap means the new
        start falls before the existing end and the existing start falls before
        the new end; pure adjacency — a new interval beginning exactly where an
        existing one ends — is not overlap and is permitted."
        PRD §3.2: "another claim line already exists that belongs to a
        different case of the same payer"

        Design: Difficulty/resource_temporal_overlap/claim_interval_overlap_half_open
        """
        scn = setup_overlap_scenario()
        adjacent = validate_success(api.add_claim_line(
            scn["c2"]["id"],
            create_claim_line_payload("CLM-9", "PA-1", "2026-01-10T00:00:00Z",
                                      "2026-01-20T00:00:00Z", 50000),
            him_headers), 201)
        assert is_valid_uuid(adjacent["id"]), (
            "Adjacency at the exclusive end is not overlap")
        cross = validate_success(api.add_claim_line(
            scn["c3"]["id"],
            create_claim_line_payload("CLM-9", "PA-1", "2026-01-05T00:00:00Z",
                                      "2026-01-12T00:00:00Z", 50000),
            him_headers), 201)
        assert is_valid_uuid(cross["id"]), (
            "The overlap guard is scoped to the same payer")


class TestCaseListing:
    def _three_cases(self):
        payer = create_payer(name="P1")
        for i, audit_type in enumerate(
                ("RAC_COMPLEX", "RAC_AUTOMATED", "TARGETED_PROBE"), start=1):
            create_audit_case(payer["id"], audit_type,
                              f"2026-08-0{i}T00:00:00Z")
        return payer

    def test_pagination_defaults_and_pages(self, api, reader_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return: when omitted it defaults to 10, its accepted minimum
        is 1, and its accepted maximum is 100. The `offset` parameter specifies
        how many items to skip from the beginning of the result set and
        defaults to 0."
        PRD §2.3: "List responses carry the following pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_and_defaults
        """
        self._three_cases()
        page1, meta1 = validate_paginated(
            api.list_audit_cases(reader_headers, params={"limit": 2,
                                                         "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_audit_cases(reader_headers, params={"limit": 2,
                                                         "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3 and meta2["has_more"] is False

    def test_filters_by_payer_and_status(self, api, reader_headers):
        """PRD §3.2: "The case register supports listing with optional
        `payer_id`, `status`, and `audit_type` filters."

        Design: Corner/endpoints/list_filters_status_and_payer
        """
        pa = create_payer(name="PA", payer_type="RAC")
        pb = create_payer(name="PB", payer_type="COMMERCIAL")
        ca1 = create_audit_case(pa["id"], "RAC_COMPLEX")
        ca2 = create_audit_case(pa["id"], "RAC_AUTOMATED")
        line = add_claim_line(ca2["id"], billed_amount_cents=100000)
        submit_records(ca2["id"])
        begin_payer_review(ca2["id"], pa["id"])
        post_determination(ca2["id"], pa["id"], [paid_outcome(line["id"])])
        cb1 = create_audit_case(pb["id"], "COMMERCIAL_POSTPAY")

        data, meta = validate_paginated(api.list_audit_cases(
            reader_headers, params={"payer_id": pa["id"],
                                    "status": "DETERMINATION_ISSUED"}))
        assert meta["total_count"] == 1 and data[0]["id"] == ca2["id"]
        data, meta = validate_paginated(api.list_audit_cases(
            reader_headers, params={"payer_id": pa["id"],
                                    "status": "RECEIVED"}))
        assert meta["total_count"] == 1 and data[0]["id"] == ca1["id"]
        data, meta = validate_paginated(api.list_audit_cases(
            reader_headers, params={"payer_id": pb["id"]}))
        assert meta["total_count"] == 1 and data[0]["id"] == cb1["id"]


class TestRecordsDeadlineBoundary:
    def test_submission_at_exact_deadline_is_on_time(self, api):
        """PRD §2.8: "An action lands on time when the logical clock reads at
        or before the deadline instant: a submission whose logical timestamp
        equals `records_due_at` exactly is on time, and one second past it is
        late."

        Design: Difficulty/boundary_precision_check/records_deadline_inclusive_equality
        """
        payer = create_payer(name="P1", records_submission_days=30)
        case = create_audit_case(payer["id"], "RAC_COMPLEX",
                                 "2026-08-01T00:00:00Z")
        advance_clock("2026-08-31T00:00:00Z")
        submitted = submit_records(case["id"], "M-A")
        assert submitted["records_due_at"] == "2026-08-31T00:00:00Z"
        assert submitted["status"] == "RECORDS_SUBMITTED"
        assert submitted["late_submission"] is False, (
            "Equality with records_due_at is on time")

    def test_submission_one_second_past_deadline_is_late(self, api):
        """PRD §2.8: "a submission whose logical timestamp equals
        `records_due_at` exactly is on time, and one second past it is late."
        PRD §3.2: "A late submission from `MISSED_DEADLINE` is accepted. It
        stamps `records_submitted_at` with the current logical time and sets
        `late_submission` true — a sticky flag that never returns to false."

        Design: Difficulty/boundary_precision_check/records_deadline_inclusive_equality
        """
        payer = create_payer(name="P1", records_submission_days=30)
        case = create_audit_case(payer["id"], "RAC_COMPLEX",
                                 "2026-08-01T00:00:00Z")
        advance_clock("2026-08-31T00:00:01Z")
        swept = get_case(case["id"])
        assert swept["status"] == "MISSED_DEADLINE", (
            "One second past the deadline the sweep has already fired")
        submitted = submit_records(case["id"], "M-B")
        assert submitted["status"] == "RECORDS_SUBMITTED"
        assert submitted["late_submission"] is True


class TestMissedDeadlineCascade:
    def test_sweep_auto_denies_every_under_audit_line(self, api):
        """PRD §3.2: "The missed-deadline sweep fires on any clock advance that
        pushes the logical time past `records_due_at` while the case is still
        `RECEIVED`. The case moves `RECEIVED → MISSED_DEADLINE`, and every
        claim line still `UNDER_AUDIT` is auto-denied: it moves to `DENIED`
        with `denied_amount_cents` set to its full `billed_amount_cents`,
        `denial_category` set to `TECHNICAL`, `issue_code_id` left null, and
        `auto_denied` set true."

        Design: Difficulty/transitive_cascade/missed_deadline_auto_denial_cascade
        """
        scn = setup_case_past_records_deadline((100000, 200000))
        case = scn["case"]
        assert case["status"] == "MISSED_DEADLINE"
        assert case["total_denied_active_cents"] == 300000, (
            "Both auto-denied lines bubble up into the case totals")
        line = get_line(scn["lines"][0]["id"])
        assert line["status"] == "DENIED"
        assert line["denied_amount_cents"] == 100000
        assert line["denial_category"] == "TECHNICAL"
        assert line["issue_code_id"] is None
        assert line["auto_denied"] is True

    def test_late_submission_reverts_auto_denied_lines(self, api):
        """PRD §3.2: "Every claim line whose `auto_denied` is true reverts
        `DENIED → UNDER_AUDIT`, with `denied_amount_cents` reset to zero,
        `denial_category` cleared to null, and `auto_denied` reset to false;
        lines denied by an actual payer determination are untouched."
        PRD §3.2: "sets `late_submission` true — a sticky flag that never
        returns to false."

        Design: Difficulty/transitive_cascade/missed_deadline_auto_denial_cascade
        """
        scn = setup_case_past_records_deadline((100000, 200000))
        submitted = submit_records(scn["case"]["id"], "M-late")
        assert submitted["status"] == "RECORDS_SUBMITTED"
        assert submitted["late_submission"] is True
        line = get_line(scn["lines"][0]["id"])
        assert line["status"] == "UNDER_AUDIT"
        assert line["denied_amount_cents"] == 0
        assert line["auto_denied"] is False
        assert get_case(scn["case"]["id"])["total_denied_active_cents"] == 0


class TestRecordsSubmissionOcc:
    def test_stale_expected_version_rejected_then_fresh_succeeds(self, api,
                                                                 him_headers):
        """PRD §2.7: "If the case's version has advanced since that observation
        — because another submission, amendment, or automatic transition landed
        in between — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.2: "A manifest amendment from `RECORDS_SUBMITTED` is permitted
        any number of times."

        Design: Corner/cross_cutting/occ_records_submission_stale_version
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        assert case["version"] == 1
        first = validate_success(api.submit_records(
            case["id"], records_submission_payload("M-1", 1), HIM), 200)
        assert first["status"] == "RECORDS_SUBMITTED"
        assert first["version"] == 2
        stale = api.submit_records(
            case["id"], records_submission_payload("M-2", 1), him_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        third = validate_success(api.submit_records(
            case["id"], records_submission_payload("M-2", 2), HIM), 200)
        assert third["version"] == 3, (
            "Amendment with the fresh version succeeds — the state permits it")


class TestCaseVersionIncrements:
    def test_version_increments_on_every_mutation_including_cascades(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one with every modification of the resource, including
        mutations driven by cascading side effects."
        PRD §3.2: "Every line addition recomputes the case's monetary totals"

        Design: Corner/cross_cutting/version_increments_on_every_mutation
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        assert case["version"] == 1
        add_claim_line(case["id"], billed_amount_cents=100000)
        after_line = get_case(case["id"])
        assert after_line["version"] == 2, (
            "The claim-line cascade recomputes case totals and bumps version")
        assert after_line["total_billed_cents"] == 100000
        submitted = submit_records(case["id"])
        assert submitted["version"] == 3


class TestCaseEventTrail:
    def test_event_entries_carry_no_version_or_updated_at(self, api,
                                                          reader_headers):
        """PRD §2.5: "An `AuditCaseEvent` is append-only: it carries `id` and
        `created_at`, and both `updated_at` and `version` are absent, because
        events are never modified after being written."

        Design: Corner/entities/event_log_entries_immutable
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        events, meta = validate_paginated(
            api.list_case_events(case["id"], reader_headers))
        assert meta["total_count"] >= 1
        first = events[0]
        assert_case_event(first)
        assert first["event_type"] == "CASE_CREATED"
        assert first["actor_role"] == "HIMCoordinator"
        for entry in events:
            assert "version" not in entry and "updated_at" not in entry

    def test_lifecycle_events_recorded_in_order(self, api, reader_headers):
        """PRD §2.11: "The trail for a case is readable through the case's
        events listing in chronological order."
        PRD §2.11: "an `event_type` drawn from `CASE_CREATED`,
        `RECORDS_SUBMITTED`, `REVIEW_BEGAN`, `DETERMINATION_ISSUED` ... the
        `actor_role` and `actor_user_id` that caused it"

        Design: Corner/endpoints/events_audit_trail_ordered
        """
        payer = create_payer(name="P1")
        issue = create_issue_code("AUTH", "TECHNICAL", "Missing auth")
        case = create_audit_case(payer["id"])
        line = add_claim_line(case["id"], billed_amount_cents=100000)
        submit_records(case["id"])
        begin_payer_review(case["id"], payer["id"])
        post_determination(case["id"], payer["id"],
                           [denied_outcome(line["id"], 100000, issue["id"])])
        events, meta = validate_paginated(
            api.list_case_events(case["id"], reader_headers))
        event_types = [e["event_type"] for e in events]
        assert event_types == ["CASE_CREATED", "RECORDS_SUBMITTED",
                               "REVIEW_BEGAN", "DETERMINATION_ISSUED"]
        for entry in events[2:]:
            assert entry["actor_role"] == "PayerAgent"
            assert entry["actor_user_id"] == payer["id"]
