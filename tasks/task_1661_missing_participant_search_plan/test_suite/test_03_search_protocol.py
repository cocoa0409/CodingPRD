"""The four-step missing-participant search protocol: attempt recording rules,
escalation gates, the certified-mail timing rules, reopen cycling, and the
logical clock's fixed startup value."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fiduciary_log_entry,
    assert_instant_equal,
    assert_search_attempt,
    create_case,
    create_search_protocol_summary,
    declare_participant_missing,
    escalate_search,
    get_participant,
    get_search_case,
    record_search_attempt,
    set_clock,
    setup_missing_participant,
    add_participant,
    validate_error,
    TEST_USERS,
    make_participant_headers,
)

ADMIN = TEST_USERS["admin_headers"]
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]
FIDUCIARY = TEST_USERS["fiduciary_headers"]


def _open_search_case(api, plan_name="Search Co 401k", plan_number="900",
                      flag_clock=None):
    """Case + participant flagged and declared missing; returns (case, participant, search_case)."""
    case = create_case(plan_name=plan_name, plan_number=plan_number)
    participant = add_participant(
        case["id"], 1000, full_name="Sea Rch", ssn="999000001"
    )
    participant, search_case = setup_missing_participant(
        participant["id"], flag_clock=flag_clock
    )
    return case, participant, search_case


class TestEscalationGates:
    def test_escalate_without_attempt_rejected(self, api):
        """PRD §3.4: "Every escalation is performed by a `PlanAdministrator` and
        is gated the same way: the case must be in the expected step
        (escalating a `RESOLVED` or `EXHAUSTED` case is rejected with
        `ERR_SEARCH_CASE_NOT_ESCAPABLE`, HTTP 409), and at least one recorded
        `SearchAttempt` on the case must exist whose `method` matches the
        current step and whose `outcome` is `NO_RESULT` — without it, the
        escalation fails with `ERR_NO_ATTEMPT_ON_CURRENT_STEP` (HTTP 409)."

        Design: Corner/state_machines/escalate_without_attempt_returns_no_attempt_error
        """
        _, _, search_case = _open_search_case(api, "NoAttempt Co 401k", "114")
        resp = api.escalate_search_case(search_case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ATTEMPT_ON_CURRENT_STEP)
        assert get_search_case(search_case["id"])["status"] == "STEP1_COMMERCIAL_LOCATOR"

    def test_escalate_before_certified_window_closes(self, api):
        """PRD §3.4: "And the final escalation `STEP4_CERTIFIED_MAIL →
        EXHAUSTED` additionally requires that the current clock has reached the
        latest certified-mail attempt's `attempted_at` plus 15 days (latest by
        `attempted_at`, ties broken by latest `created_at`); escalating earlier
        is rejected with `ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN` (HTTP 409)."

        Design: Corner/state_machines/escalate_before_certified_window_closes_returns_error
        """
        _, _, search_case = _open_search_case(
            api, "Window Co 401k", "115", flag_clock="2026-11-01T00:00:00Z"
        )
        sc_id = search_case["id"]
        set_clock("2026-11-01T00:00:00Z")
        record_search_attempt(sc_id, "COMMERCIAL_LOCATOR", "2026-11-01T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-02T00:00:00Z")
        record_search_attempt(sc_id, "PUBLIC_RECORDS", "2026-11-02T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-03T00:00:00Z")
        record_search_attempt(sc_id, "CREDIT_BUREAU", "2026-11-03T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-04T00:00:00Z")
        record_search_attempt(sc_id, "CERTIFIED_MAIL", "2026-11-04T00:00:00Z")

        set_clock("2026-11-14T00:00:00Z")  # certified attempt + 10 days
        resp = api.escalate_search_case(sc_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN)
        assert get_search_case(sc_id)["status"] == "STEP4_CERTIFIED_MAIL"

        set_clock("2026-11-19T00:00:00Z")  # exactly attempt + 15 days
        search_case = escalate_search(sc_id)
        assert search_case["status"] == "EXHAUSTED", (
            "the 15-day response window is inclusive: at exactly +15 days the "
            "escalation succeeds"
        )
        assert_instant_equal(
            search_case["exhausted_at"], "2026-11-19T00:00:00Z", "exhausted_at"
        )

    def test_search_method_mismatch_rejected(self, api):
        """PRD §3.4: "The attempt's `method` is one of `COMMERCIAL_LOCATOR`,
        `PUBLIC_RECORDS`, `CREDIT_BUREAU`, or `CERTIFIED_MAIL` and must equal
        the case's current step; a mismatched method is rejected with
        `ERR_SEARCH_METHOD_MISMATCH` (HTTP 422)."

        Design: Corner/state_machines/search_method_mismatch_returns_error
        """
        _, _, search_case = _open_search_case(api, "Mismatch Co 401k", "116")
        resp = api.record_attempt(
            search_case["id"],
            {
                "method": "CREDIT_BUREAU",
                "vendor_name": "CBX",
                "attempted_at": "2026-08-01T00:00:00Z",
                "outcome": "NO_RESULT",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SEARCH_METHOD_MISMATCH)
        assert get_search_case(search_case["id"])["attempt_count"] == 0

    def test_attempt_and_escalate_on_resolved_case_rejected(self, api):
        """PRD §3.4: "Recording an attempt also requires the case to be in a
        step state — attempts on a `RESOLVED` or `EXHAUSTED` case fail with
        `ERR_SEARCH_CASE_NOT_OPEN` (HTTP 409)".
        PRD §3.4: "the case must be in the expected step (escalating a
        `RESOLVED` or `EXHAUSTED` case is rejected with
        `ERR_SEARCH_CASE_NOT_ESCAPABLE`, HTTP 409)".

        Design: Corner/state_machines/attempt_and_escalate_on_resolved_case_rejected
        """
        _, _, search_case = _open_search_case(api, "Resolved Co 401k", "117")
        record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z",
            outcome="LOCATED",
        )
        assert get_search_case(search_case["id"])["status"] == "RESOLVED"

        resp = api.record_attempt(
            search_case["id"],
            {
                "method": "COMMERCIAL_LOCATOR",
                "vendor_name": "Loc8",
                "attempted_at": "2026-08-01T00:00:00Z",
                "outcome": "NO_RESULT",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SEARCH_CASE_NOT_OPEN)
        resp = api.escalate_search_case(search_case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SEARCH_CASE_NOT_ESCAPABLE)
        search_case = get_search_case(search_case["id"])
        assert search_case["status"] == "RESOLVED"
        assert search_case["attempt_count"] == 1

    def test_attempt_timestamp_in_future_rejected(self, api):
        """PRD §3.4: "Attempts are chronological: `attempted_at` must be at or
        after the case's `opened_at`, at or before the current clock, and at or
        after every prior attempt's `attempted_at` on the same case, else
        `ERR_ATTEMPT_TIMESTAMP_INVALID` (HTTP 422)."

        Design: Corner/state_machines/attempt_timestamp_in_future_returns_error
        """
        _, _, search_case = _open_search_case(api, "Future Co 401k", "118")
        resp = api.record_attempt(
            search_case["id"],
            {
                "method": "COMMERCIAL_LOCATOR",
                "vendor_name": "Loc8",
                "attempted_at": "2026-08-02T00:00:00Z",  # one day past the clock
                "outcome": "NO_RESULT",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_TIMESTAMP_INVALID)
        assert get_search_case(search_case["id"])["attempt_count"] == 0


class TestClockDefault:
    def test_clock_default_is_fixed_at_startup(self, api):
        """PRD §2.4: "Before any explicit set, the clock reads exactly
        2026-08-01T00:00:00Z."
        PRD §3.4: "Attempts are chronological: `attempted_at` must be at or
        after the case's `opened_at`, at or before the current clock, and at or
        after every prior attempt's `attempted_at` on the same case, else
        `ERR_ATTEMPT_TIMESTAMP_INVALID` (HTTP 422)."

        Design: Corner/complexity_layers/clock_default_is_fixed_at_startup
        """
        _, _, search_case = _open_search_case(api, "Clock Co 401k", "180")
        resp = api.record_attempt(
            search_case["id"],
            {
                "method": "COMMERCIAL_LOCATOR",
                "vendor_name": "Loc8",
                "attempted_at": "2026-08-01T00:00:01Z",  # one second past startup
                "outcome": "NO_RESULT",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_TIMESTAMP_INVALID)
        attempt = record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z"
        )
        assert_search_attempt(attempt)
        assert get_search_case(search_case["id"])["attempt_count"] == 1


class TestAppendOnlyLogs:
    def test_append_only_events_have_no_version(self, api):
        """PRD §2.4: "Two resources are append-only logs and deliberately carry
        only `id` and `created_at`: `SearchAttempt` and `FiduciaryLogEntry` have
        neither `updated_at` nor `version`."
        PRD §3.8: "The server stamps each entry with the author's
        `author_user_id` and `author_role` taken from the request headers."

        Design: Corner/entities/append_only_events_have_no_version
        """
        case, _, search_case = _open_search_case(api, "Immutable Co 401k", "107")
        attempt = record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z"
        )
        assert_search_attempt(attempt)  # asserts no updated_at / version keys

        entry = create_search_protocol_summary(case["id"], search_case["id"])
        assert_fiduciary_log_entry(entry)  # asserts no updated_at / version keys
        assert entry["author_user_id"] == "admin-1"
        assert entry["author_role"] == "PlanAdministrator"


class TestSearchRbac:
    def test_independent_fiduciary_cannot_record_attempt(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/search-cases/{id}/attempts` | Record a search
        attempt; method must match the current step; outcome LOCATED resolves
        the case and the participant | PlanAdministrator |"

        Design: Corner/rbac/independent_fiduciary_cannot_record_search_attempt
        """
        _, _, search_case = _open_search_case(api, "Rbac Four Co 401k", "173")
        resp = api.record_attempt(
            search_case["id"],
            {
                "method": "COMMERCIAL_LOCATOR",
                "vendor_name": "Loc8",
                "attempted_at": "2026-08-01T00:00:00Z",
                "outcome": "NO_RESULT",
            },
            FIDUCIARY,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_search_case(search_case["id"])["attempt_count"] == 0


class TestSearchCaseReopenCycle:
    def test_located_attempt_resolves_case(self, api):
        """PRD §3.4: "When an attempt comes back `LOCATED`, the case moves from
        whichever step it occupied to `RESOLVED` with `resolved_at` stamped and
        the participant's `active_search_case_id` cleared — the same effects as
        a direct locate."

        Design: Difficulty/non_linear_state_machine/search_case_reopen_cycle
        """
        _, participant, search_case = _open_search_case(api, "Cycle Co 401k", "041")
        record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z",
            outcome="LOCATED",
        )
        search_case = get_search_case(search_case["id"])
        assert search_case["status"] == "RESOLVED"
        assert search_case["resolved_at"] is not None
        participant = get_participant(participant["id"])
        assert participant["locate_status"] == "LOCATED"
        assert participant["active_search_case_id"] is None, (
            "resolution clears the participant's active search case"
        )

    def test_redeclaration_reopens_same_search_case(self, api):
        """PRD §3.4: "A later re-declaration of the same participant reopens the
        `RESOLVED` case to `STEP1_COMMERCIAL_LOCATOR`, clears `resolved_at` to
        null, and restarts the protocol from step one."
        PRD §3.3: "if the latest case is `RESOLVED`, it reopens to
        `STEP1_COMMERCIAL_LOCATOR` with its `resolved_at` cleared to null while
        `opened_at` is preserved from the original opening."

        Design: Difficulty/non_linear_state_machine/search_case_reopen_cycle
        """
        _, participant, search_case = _open_search_case(api, "Cycle Co 401k", "041")
        record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z",
            outcome="LOCATED",
        )
        # Re-flag from LOCATED (allowed) and re-declare missing.
        api.flag_contact(
            participant["id"], {"flag_type": "UNDELIVERABLE_MAIL"}, RECORDKEEPER
        )
        participant = declare_participant_missing(participant["id"])
        assert participant["locate_status"] == "MISSING"
        assert participant["active_search_case_id"] == search_case["id"], (
            "the reopen reuses the same search case row — no new row is created"
        )
        reopened = get_search_case(search_case["id"])
        assert reopened["status"] == "STEP1_COMMERCIAL_LOCATOR"
        assert reopened["resolved_at"] is None
        assert_instant_equal(
            reopened["opened_at"], "2026-08-01T00:00:00Z",
            "opened_at preserved from the original opening",
        )
        assert reopened["attempt_count"] == 1, "attempt history survives the reopen"


class TestCertifiedMailTrailingBuffer:
    def _step4_case_with_certified_attempt(self, api):
        _, _, search_case = _open_search_case(
            api, "Buffer Co 401k", "091", flag_clock="2026-11-01T00:00:00Z"
        )
        sc_id = search_case["id"]
        set_clock("2026-11-01T00:00:00Z")
        record_search_attempt(sc_id, "COMMERCIAL_LOCATOR", "2026-11-01T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-02T00:00:00Z")
        record_search_attempt(sc_id, "PUBLIC_RECORDS", "2026-11-02T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-03T00:00:00Z")
        record_search_attempt(sc_id, "CREDIT_BUREAU", "2026-11-03T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-04T00:00:00Z")
        record_search_attempt(sc_id, "CERTIFIED_MAIL", "2026-11-04T00:00:00Z")
        return sc_id

    def test_certified_mail_attempt_inside_buffer_rejected(self, api):
        """PRD §3.4: "A `CERTIFIED_MAIL` attempt may not fall inside the 15-day
        trailing buffer of a previous `CERTIFIED_MAIL` attempt on the same case
        — an `attempted_at` earlier than the prior certified-mail attempt's
        `attempted_at` plus 15 days is rejected with
        `ERR_CERTIFIED_MAIL_WINDOW_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/certified_mail_trailing_buffer
        """
        sc_id = self._step4_case_with_certified_attempt(api)
        set_clock("2026-11-10T00:00:00Z")  # prior certified attempt + 6 days
        resp = api.record_attempt(
            sc_id,
            {
                "method": "CERTIFIED_MAIL",
                "vendor_name": "USPS",
                "attempted_at": "2026-11-10T00:00:00Z",
                "outcome": "NO_RESULT",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFIED_MAIL_WINDOW_ACTIVE)
        search_case = get_search_case(sc_id)
        assert search_case["attempt_count"] == 4, (
            "the rejected attempt leaves no row behind"
        )
        assert search_case["status"] == "STEP4_CERTIFIED_MAIL"

    def test_certified_mail_attempt_at_buffer_end_allowed(self, api):
        """PRD §3.4: "A `CERTIFIED_MAIL` attempt may not fall inside the 15-day
        trailing buffer of a previous `CERTIFIED_MAIL` attempt on the same case
        — an `attempted_at` earlier than the prior certified-mail attempt's
        `attempted_at` plus 15 days is rejected with
        `ERR_CERTIFIED_MAIL_WINDOW_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/certified_mail_trailing_buffer
        """
        sc_id = self._step4_case_with_certified_attempt(api)
        set_clock("2026-11-19T00:00:00Z")  # exactly prior attempt + 15 days
        attempt = record_search_attempt(
            sc_id, "CERTIFIED_MAIL", "2026-11-19T00:00:00Z", vendor_name="USPS"
        )
        assert_search_attempt(attempt)
        search_case = get_search_case(sc_id)
        assert search_case["attempt_count"] == 5
        assert search_case["status"] == "STEP4_CERTIFIED_MAIL", (
            "attempts do not advance the protocol step"
        )


class TestRoleBeatsExistence:
    def test_role_auth_beats_existence_on_attempt(self, api):
        """PRD §2.9: "Every write request passes through a fixed sequence of
        rejection layers, and the layering is observable: an earlier failure
        masks later ones. First, the two auth headers are checked (missing or
        unrecognised headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
        Second, role authorization is checked (`ERR_FORBIDDEN_ROLE`, or
        `ERR_PARTICIPANT_OWNERSHIP_VIOLATION` for a `Participant` submitting an
        election for someone else). Third, the request body shape is validated
        — required fields present, types correct, enum values in range, numeric
        constraints holding, no undeclared fields (`ERR_INVALID_REQUEST`), with
        the fiduciary narrative length check reported separately as
        `ERR_NARRATIVE_TOO_SHORT`. Fourth, path resource identifiers are
        resolved left-to-right (`ERR_NOT_FOUND`), and body foreign-key
        references such as `termination_case_id` and `participant_id` are
        resolved (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Difficulty/priority_pair_validation_conflict/role_auth_beats_existence
        """
        create_case(plan_name="AuthOrder Co 401k", plan_number="062")
        resp = api.record_attempt(
            NON_EXISTENT_UUID,
            {
                "method": "COMMERCIAL_LOCATOR",
                "vendor_name": "Loc8",
                "attempted_at": "2026-08-01T00:00:00Z",
                "outcome": "NO_RESULT",
            },
            make_participant_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_role_auth_beats_existence_on_escalate(self, api):
        """PRD §2.9: "Second, role authorization is checked
        (`ERR_FORBIDDEN_ROLE`, or `ERR_PARTICIPANT_OWNERSHIP_VIOLATION` for a
        `Participant` submitting an election for someone else). Third, the
        request body shape is validated — required fields present, types
        correct, enum values in range, numeric constraints holding, no
        undeclared fields (`ERR_INVALID_REQUEST`), with the fiduciary narrative
        length check reported separately as `ERR_NARRATIVE_TOO_SHORT`. Fourth,
        path resource identifiers are resolved left-to-right (`ERR_NOT_FOUND`),
        and body foreign-key references such as `termination_case_id` and
        `participant_id` are resolved (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Difficulty/priority_pair_validation_conflict/role_auth_beats_existence
        """
        create_case(plan_name="AuthOrder Co 401k", plan_number="062")
        resp = api.escalate_search_case(
            NON_EXISTENT_UUID, make_participant_headers(NON_EXISTENT_UUID)
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
