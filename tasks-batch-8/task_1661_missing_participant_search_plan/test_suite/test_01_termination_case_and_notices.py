"""Termination case lifecycle: creation defaults, the notice program (NOIT /
INTERESTED_PARTY windows, supersede links, OCC), effectuation gates and the
vesting fan-out, resolution posture, and response-envelope / auth shapes."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fund_conservation,
    assert_participant,
    assert_termination_case,
    assert_version_incremented,
    create_case,
    effectuate_termination,
    get_case,
    get_participant,
    issue_noit,
    issue_notice,
    set_clock,
    setup_case_in_distribution,
    validate_error,
    validate_paginated,
    validate_success,
    add_participant,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCaseCreationDefaults:
    def test_case_creation_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "an optional `restoration_policy` of `NOMINAL` or
        `EARNINGS_ADJUSTED` which defaults to `NOMINAL` when omitted. The new
        case starts in `DRAFT` status with all counters and ledger fields at
        zero."
        PRD §3.1: "its issuance pins the case's computed `default_treatment_date`
        to the non-superseded `DISTRIBUTION` notice's `action_effective_date`
        plus 30 days — null until such a notice exists, and recomputed on
        supersede."
        PRD §2.8: "so a case with no participants is never "all resolved"".

        Design: Corner/entities/case_creation_applies_defaults_and_system_fields
        """
        case = create_case(plan_name="Defaults Co 401k", plan_number="100")
        assert_termination_case(case)
        assert case["restoration_policy"] == "NOMINAL", (
            f"omitted restoration_policy must default to NOMINAL, got {case['restoration_policy']}"
        )
        assert case["status"] == "DRAFT"
        assert case["total_participant_count"] == 0
        assert case["resolved_participant_count"] == 0
        assert case["missing_participant_count"] == 0
        assert case["all_participants_resolved"] is False
        assert case["blackout_active"] is False
        assert case["default_treatment_date"] is None
        for field in (
            "total_plan_assets_cents",
            "sponsor_contribution_cents",
            "paid_out_cents",
            "pbgc_transferred_cents",
            "forfeited_cents",
            "expense_paid_cents",
            "remaining_undistributed_cents",
        ):
            assert case[field] == 0, f"{field} must start at zero, got {case[field]}"


class TestNoitProgram:
    def test_noit_date_mismatch_rejected(self, api):
        """PRD §3.1: "the `action_effective_date` must equal the case's
        `proposed_termination_date`, failing which the issuance is rejected with
        `ERR_NOIT_DATE_MISMATCH` (HTTP 422)".

        Design: Corner/validations/noit_date_mismatch_returns_error
        """
        case = create_case(plan_name="Mismatch Date Co 401k", plan_number="140")
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-20T00:00:00Z",
                "expected_termination_case_version": case["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOIT_DATE_MISMATCH)
        assert get_case(case["id"])["status"] == "DRAFT"

    def test_noit_sixty_day_lower_bound_accepted(self, api):
        """PRD §3.1: "the issuance clock time must fall within the window from
        90 days before the proposed termination date through 60 days before it,
        inclusive by whole calendar days — an issuance outside that window is
        rejected with `ERR_NOIT_TIMING_WINDOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/noit_sixty_day_boundary
        """
        case = create_case(plan_name="Sixty OK Co 401k", plan_number="071")
        set_clock("2026-08-16T00:00:00Z")  # exactly 60 days before 2026-10-15
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": case["version"],
            },
            ADMIN,
        )
        validate_success(resp, 201)
        assert get_case(case["id"])["status"] == "NOTICE_OF_INTENT_ISSUED", (
            "a NOIT issued exactly 60 days before termination is inside the "
            "inclusive window and must be accepted"
        )

    def test_noit_fifty_nine_days_rejected(self, api):
        """PRD §3.1: "the issuance clock time must fall within the window from
        90 days before the proposed termination date through 60 days before it,
        inclusive by whole calendar days — an issuance outside that window is
        rejected with `ERR_NOIT_TIMING_WINDOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/noit_sixty_day_boundary
        """
        case = create_case(plan_name="Fiftynine Co 401k", plan_number="072")
        set_clock("2026-08-17T00:00:00Z")  # 59 days before 2026-10-15
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": case["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOIT_TIMING_WINDOW)
        assert get_case(case["id"])["status"] == "DRAFT"

    def test_noit_ninety_day_boundary(self, api):
        """PRD §3.1: "the issuance clock time must fall within the window from
        90 days before the proposed termination date through 60 days before it,
        inclusive by whole calendar days — an issuance outside that window is
        rejected with `ERR_NOIT_TIMING_WINDOW` (HTTP 422)."

        Design: Corner/validations/noit_ninety_day_boundary
        """
        case_ok = create_case(plan_name="Ninety Co 401k", plan_number="141")
        case_bad = create_case(plan_name="Ninetyone Co 401k", plan_number="142")
        set_clock("2026-07-17T00:00:00Z")  # exactly 90 days before 2026-10-15
        resp = api.create_notice(
            {
                "termination_case_id": case_ok["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": case_ok["version"],
            },
            ADMIN,
        )
        validate_success(resp, 201)
        assert get_case(case_ok["id"])["status"] == "NOTICE_OF_INTENT_ISSUED"
        set_clock("2026-07-16T00:00:00Z")  # 91 days before: outside the window
        resp = api.create_notice(
            {
                "termination_case_id": case_bad["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": case_bad["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOIT_TIMING_WINDOW)
        assert get_case(case_bad["id"])["status"] == "DRAFT"

    def test_interested_party_window_boundaries(self, api):
        """PRD §3.7: "The intended filing date must be covered by a
        non-superseded `INTERESTED_PARTY` notice whose `action_effective_date`
        equals it and whose issuance fell in the window from 24 days before the
        filing date through 10 days before it, inclusive by whole calendar days;
        an interested-party notice issued outside that window, and a create or
        file without a live covering notice in it, are rejected with
        `ERR_INTERESTED_PARTY_WINDOW` (HTTP 422)."

        Design: Corner/validations/interested_party_window_boundaries
        """
        case_ok = create_case(plan_name="Ip Ten Co 401k", plan_number="143")
        case_bad = create_case(plan_name="Ip Five Co 401k", plan_number="144")
        set_clock("2026-08-20T00:00:00Z")  # 10 days before the filing date
        resp = api.create_notice(
            {
                "termination_case_id": case_ok["id"],
                "notice_type": "INTERESTED_PARTY",
                "action_effective_date": "2026-08-30T00:00:00Z",
                "expected_termination_case_version": case_ok["version"],
            },
            ADMIN,
        )
        validate_success(resp, 201)
        set_clock("2026-08-25T00:00:00Z")  # 5 days before the filing date
        resp = api.create_notice(
            {
                "termination_case_id": case_bad["id"],
                "notice_type": "INTERESTED_PARTY",
                "action_effective_date": "2026-08-30T00:00:00Z",
                "expected_termination_case_version": case_bad["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INTERESTED_PARTY_WINDOW)

    def test_notice_reissue_supersedes_prior(self, api):
        """PRD §3.1: "Every issuance records the clock time as `issued_at` and
        supersedes the prior live notice of the same `notice_type` on the same
        case by writing the new notice's id into the superseded notice's
        `superseded_by_id` (which is null while a notice is the live one)."
        PRD §3.1: "A first NOIT transitions the case `DRAFT →
        NOTICE_OF_INTENT_ISSUED`; a reissued NOIT keeps the case in
        `NOTICE_OF_INTENT_ISSUED` while superseding the previous NOIT under the
        same date and timing checks."

        Design: Corner/entities/notice_supersede_self_reference_links
        """
        case = create_case(plan_name="Supersede Co 401k", plan_number="108")
        notice1 = issue_notice(case["id"], "NOIT", "2026-10-15T00:00:00Z")
        notice2 = issue_notice(case["id"], "NOIT", "2026-10-15T00:00:00Z")
        reread1 = validate_success(api.get_notice(notice1["id"], ADMIN))
        reread2 = validate_success(api.get_notice(notice2["id"], ADMIN))
        assert reread1["superseded_by_id"] == notice2["id"], (
            "the reissue must link the prior notice to its successor"
        )
        assert reread2["superseded_by_id"] is None, (
            "the live notice carries a null superseded_by_id"
        )
        data, meta = validate_paginated(
            api.list_notices(ADMIN, params={"superseded_by_id": notice2["id"]})
        )
        assert [row["id"] for row in data] == [notice1["id"]], (
            "filtering notices by superseded_by_id must return exactly the "
            "superseded predecessor"
        )
        assert get_case(case["id"])["status"] == "NOTICE_OF_INTENT_ISSUED"

    def test_occ_stale_case_version_notice_rejected(self, api):
        """PRD §2.6: "Issuing a participant notice requires the request body to
        carry `expected_termination_case_version`, holding the `version` of the
        `TerminationCase` as the client last observed it. If another writer has
        advanced the case's `version` since that read — for example by reissuing
        a notice, which legitimately supersedes the live notice of the same type
        — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing
        the writer to re-read before superseding."

        Design: Corner/complexity_layers/occ_stale_case_version_notice_rejected
        """
        case = create_case(plan_name="Occ Case Co 401k", plan_number="182")
        stale_version = case["version"]
        notice1 = issue_notice(case["id"], "NOIT", "2026-10-15T00:00:00Z")
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": stale_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh_version = get_case(case["id"])["version"]
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "NOIT",
                "action_effective_date": "2026-10-15T00:00:00Z",
                "expected_termination_case_version": fresh_version,
            },
            ADMIN,
        )
        notice2 = validate_success(resp, 201)
        reread1 = validate_success(api.get_notice(notice1["id"], ADMIN))
        assert reread1["superseded_by_id"] == notice2["id"], (
            "the fresh-version reissue supersedes the live NOIT"
        )


class TestEffectuation:
    def test_effectuate_state_and_timing_gates(self, api):
        """PRD §3.2: "The case must be `NOTICE_OF_INTENT_ISSUED` (otherwise
        `ERR_CASE_INVALID_STATE`) and the current clock must be at or after the
        `proposed_termination_date`, failing which the call is rejected with
        `ERR_TERMINATION_DATE_NOT_REACHED` (HTTP 409)."

        Design: Corner/state_machines/effectuate_state_and_timing_gates
        """
        case_a = create_case(plan_name="Gate A Co 401k", plan_number="110")
        resp = api.effectuate_termination(case_a["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        assert get_case(case_a["id"])["status"] == "DRAFT"

        case_b = create_case(plan_name="Gate B Co 401k", plan_number="111")
        issue_noit(case_b["id"])
        set_clock("2026-10-14T00:00:00Z")  # one day before the termination date
        resp = api.effectuate_termination(case_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TERMINATION_DATE_NOT_REACHED)
        assert get_case(case_b["id"])["status"] == "NOTICE_OF_INTENT_ISSUED"

    def test_vesting_cascade_on_effectuate(self, api):
        """PRD §3.2: "Effectuation is a fan-out event: every participant's
        `vested_pct` is forced to 100, each participant's `vested_balance_cents`
        and `net_distributable_cents` are recomputed, and each participant's
        `version` increments. Simultaneously the case snapshots its ledger:
        `total_plan_assets_cents` becomes the sum of `account_balance_cents`
        over all participants, and `remaining_undistributed_cents` initializes
        to the same total."

        Design: Corner/calculations/vesting_cascade_on_effectuate
        """
        case = create_case(plan_name="Vest Co 401k", plan_number="133")
        participant = add_participant(
            case["id"], 1000000, vested_pct=60, full_name="Ve St", ssn="121110006"
        )
        assert participant["vested_balance_cents"] == 600000
        version_before = participant["version"]
        issue_noit(case["id"])
        effectuate_termination(case["id"])
        participant = get_participant(participant["id"])
        assert participant["vested_pct"] == 100, "termination forces full vesting"
        assert participant["vested_balance_cents"] == 1000000
        assert participant["net_distributable_cents"] == 1000000
        assert_version_incremented(participant["version"], version_before)
        case = get_case(case["id"])
        assert case["total_plan_assets_cents"] == 1000000
        assert case["remaining_undistributed_cents"] == 1000000
        assert_fund_conservation(case)

    def test_participant_created_after_effectuate_is_fully_vested(self, api):
        """PRD §3.1: "When the case is already `TERMINATION_EFFECTIVE` at the
        time of the add, the participant is stored with `vested_pct` forced to
        100 regardless of the supplied value."

        Design: Corner/entities/participant_created_after_effectuate_is_fully_vested
        """
        case = create_case(plan_name="Late Vest Co 401k", plan_number="104")
        issue_noit(case["id"])
        effectuate_termination(case["id"])
        participant = add_participant(
            case["id"], 500000, vested_pct=60, full_name="Late Joiner", ssn="111110002"
        )
        assert_participant(participant)
        assert participant["vested_pct"] == 100, (
            f"participants added after effectuation are stored fully vested, "
            f"got {participant['vested_pct']}"
        )
        assert participant["vested_balance_cents"] == 500000
        assert participant["net_distributable_cents"] == 500000


class TestZeroParticipantPosture:
    def test_zero_participant_posture_fields(self, api):
        """PRD §2.8: "The boolean `all_participants_resolved` is true exactly
        when `total_participant_count` is greater than zero and
        `resolved_participant_count` equals `total_participant_count` — so a
        case with no participants is never "all resolved"."

        Design: Difficulty/boundary_precision_check/zero_participant_posture_boundary
        """
        case, participants = setup_case_in_distribution(
            participants=[], plan_name="Empty Co 401k", plan_number="073"
        )
        assert participants == []
        assert case["status"] == "DISTRIBUTION_IN_PROGRESS"
        assert case["total_participant_count"] == 0
        assert case["resolved_participant_count"] == 0
        assert case["all_participants_resolved"] is False, (
            "the empty census never satisfies the all-resolved posture"
        )

    def test_zero_participant_advance_rejected(self, api):
        """PRD §3.2: "advancing the case `DISTRIBUTION_IN_PROGRESS →
        FINAL_RECONCILIATION` requires `all_participants_resolved` to be true,
        failing which the call is rejected with
        `ERR_PARTICIPANTS_NOT_ALL_RESOLVED` (HTTP 409) — and note that the empty
        census never satisfies this, since `all_participants_resolved` demands a
        positive `total_participant_count`."

        Design: Difficulty/boundary_precision_check/zero_participant_posture_boundary
        """
        case, _ = setup_case_in_distribution(
            participants=[], plan_name="Empty Co 401k", plan_number="073"
        )
        resp = api.advance_to_reconciliation(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANTS_NOT_ALL_RESOLVED)
        assert get_case(case["id"])["status"] == "DISTRIBUTION_IN_PROGRESS"


class TestEnvelopeAndAuth:
    def test_error_envelope_shape_on_violation(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/error_envelope_shape_on_violation
        """
        case = create_case(plan_name="Envelope Co 401k", plan_number="160")
        resp = api.get_participant(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["message"].strip(), "error message must be non-empty"
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, f"error meta must carry exactly the two request fields, got {body['meta']}"
        assert body["meta"]["api_request_id"].startswith("req_")

        resp = api.get_termination_case(case["id"], ADMIN)
        data = validate_success(resp)
        body = resp.json()
        assert body["response_type"] == "object"
        assert data["id"] == case["id"]
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        case = create_case(plan_name="Auth Co 401k", plan_number="156")
        resp = api.get_termination_case(case["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        resp = api.get_termination_case(
            case["id"], headers={"X-User-ID": "admin-1"}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
