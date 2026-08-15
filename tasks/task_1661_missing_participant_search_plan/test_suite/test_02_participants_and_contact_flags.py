"""Participant census rules (required fields, computed balances, reverse
filtering) and the contact-flag / declare-missing / locate lifecycle."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equal,
    assert_participant,
    assert_search_case,
    create_case,
    declare_participant_missing,
    flag_participant,
    get_case,
    get_participant,
    get_search_case,
    issue_noit,
    locate_participant,
    record_search_attempt,
    setup_case_in_distribution,
    setup_exhausted_search,
    setup_missing_participant,
    submit_election,
    add_participant,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]


class TestParticipantCreation:
    def test_participant_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "Adding a participant requires the owning case's
        `termination_case_id` in the payload along with `full_name`, `ssn`
        (exactly nine digits — the credit-bureau search step relies on it),
        `mailing_address`, `account_balance_cents` (which may not be negative),
        and `vested_pct` between 0 and 100 inclusive."
        PRD §2.9: "Third, the request body shape is validated — required fields
        present, types correct, enum values in range, numeric constraints
        holding, no undeclared fields (`ERR_INVALID_REQUEST`), with the
        fiduciary narrative length check reported separately as
        `ERR_NARRATIVE_TOO_SHORT`."

        Design: Corner/entities/participant_missing_required_field_returns_invalid_request
        """
        case = create_case(plan_name="Req Co 401k", plan_number="101")
        resp = api.create_participant(
            {
                "termination_case_id": case["id"],
                "full_name": "No Ssn",
                "mailing_address": "1 N St",
                "account_balance_cents": 1000,
                "vested_pct": 100,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, _ = validate_paginated(
            api.list_participants(ADMIN, params={"termination_case_id": case["id"]})
        )
        assert data == [], "the rejected create must not persist a participant"

    def test_participant_computed_field_input_rejected(self, api):
        """PRD §2.9: "Third, the request body shape is validated — required
        fields present, types correct, enum values in range, numeric constraints
        holding, no undeclared fields (`ERR_INVALID_REQUEST`), with the
        fiduciary narrative length check reported separately as
        `ERR_NARRATIVE_TOO_SHORT`."
        PRD §2.4: "Fields marked as computed in this document are derived on
        read and never stored".

        Design: Corner/entities/participant_computed_field_input_ignored
        """
        case = create_case(plan_name="Computed Co 401k", plan_number="102")
        resp = api.create_participant(
            {
                "termination_case_id": case["id"],
                "full_name": "Sneaky Field",
                "ssn": "111110000",
                "mailing_address": "2 S St",
                "account_balance_cents": 1000,
                "vested_pct": 100,
                "vested_balance_cents": 1,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_participant_vested_balance_rounds_half_up(self, api):
        """PRD §3.1: "the system immediately derives `vested_balance_cents` as
        the account balance multiplied by the vesting percentage and divided by
        100, rounded half up to whole cents, and `net_distributable_cents` as
        `vested_balance_cents` minus `termination_expense_share_cents` (which
        starts at zero)."

        Design: Corner/entities/participant_vested_balance_computed_rounds_half_up
        """
        case = create_case(plan_name="Round Co 401k", plan_number="103")
        participant = add_participant(
            case["id"], 333335, vested_pct=60, full_name="Vest Math", ssn="111110001"
        )
        assert_participant(participant)
        # round_half_up(333335 * 60 / 100) = round_half_up(200001.0) = 200001
        assert participant["vested_balance_cents"] == 200001, (
            f"expected 200001, got {participant['vested_balance_cents']}"
        )
        assert participant["net_distributable_cents"] == 200001

    def test_get_participant_not_found_returns_404(self, api):
        """PRD §2.9: "Fourth, path resource identifiers are resolved
        left-to-right (`ERR_NOT_FOUND`), and body foreign-key references such as
        `termination_case_id` and `participant_id` are resolved
        (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Corner/entities/get_participant_not_found_returns_404
        """
        create_case(plan_name="Nf Co 401k", plan_number="105")
        resp = api.get_participant(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_participant_list_pagination_and_envelope(self, api):
        """PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.3: "List responses are sorted by `created_at` ascending."

        Design: Corner/entities/participant_list_pagination_and_envelope
        """
        case = create_case(plan_name="Page Co 401k", plan_number="106")
        add_participant(case["id"], 1000, full_name="Pg One", ssn="111110010")
        add_participant(case["id"], 2000, full_name="Pg Two", ssn="111110011")
        add_participant(case["id"], 3000, full_name="Pg Three", ssn="111110012")
        resp = api.list_participants(
            ADMIN, params={"termination_case_id": case["id"], "limit": 2, "offset": 1}
        )
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert meta["has_more"] is False, (
            "offset 1 + 2 rows covers the full 3-row set, so has_more is false"
        )
        assert data[0]["created_at"] <= data[1]["created_at"], (
            "list responses are sorted by created_at ascending"
        )

    def test_body_fk_not_found_returns_reference_error(self, api):
        """PRD §2.9: "Fourth, path resource identifiers are resolved
        left-to-right (`ERR_NOT_FOUND`), and body foreign-key references such as
        `termination_case_id` and `participant_id` are resolved
        (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Corner/validations/body_fk_not_found_returns_reference_error
        """
        create_case(plan_name="Fk Co 401k", plan_number="148")
        resp = api.create_participant(
            {
                "termination_case_id": NON_EXISTENT_UUID,
                "full_name": "Fk Ref",
                "ssn": "121110020",
                "mailing_address": "1 F St",
                "account_balance_cents": 1000,
                "vested_pct": 100,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestContactFlagsAndMissing:
    def test_declare_missing_flag_and_state_gates(self, api):
        """PRD §3.3: "A flag recorded from any other `locate_status` is rejected
        with `ERR_INVALID_FLAG_TRANSITION` (HTTP 409)."
        PRD §3.3: "a clear whose `flag_type` does not match the current flag is
        rejected with `ERR_INVALID_FLAG_TRANSITION`."
        PRD §3.3: "Declaration requires `locate_status` to be `FLAGGED_UNCASHED`
        or `FLAGGED_UNDELIVERABLE` — from anywhere else the call fails with
        `ERR_PARTICIPANT_NOT_FLAGGED` (HTTP 409), and because an open search
        case implies the participant is already `MISSING`, this gate also blocks
        re-declaration while a case is open."

        Design: Corner/state_machines/declare_missing_twice_flag_and_state_gates
        """
        case = create_case(plan_name="Twice Co 401k", plan_number="112")
        participant = add_participant(
            case["id"], 1000, full_name="Tw Ice", ssn="111110030"
        )
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")

        resp = api.clear_contact_flag(
            participant["id"], {"flag_type": "UNCASHED_CHECK"}, RECORDKEEPER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FLAG_TRANSITION)

        participant = declare_participant_missing(participant["id"])
        assert participant["locate_status"] == "MISSING"

        resp = api.flag_contact(
            participant["id"], {"flag_type": "UNDELIVERABLE_MAIL"}, RECORDKEEPER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FLAG_TRANSITION)

        resp = api.declare_missing(participant["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_FLAGGED)

    def test_declare_missing_after_exhaustion_rejected(self, api):
        """PRD §3.3: "One further gate looks backward: at most one
        `MissingSearchCase` ever exists for a participant, and if that case has
        been driven to `EXHAUSTED` the declaration is rejected with
        `ERR_SEARCH_CASE_EXHAUSTED_REDECLARE` (HTTP 409) — an exhausted
        participant's disposition must proceed, not restart."
        PRD §2.7: "When a search case is escalated from its final step to
        `EXHAUSTED`, the acting `PlanAdministrator`'s `X-User-ID` is recorded as
        the case's `exhausted_by_user_id`."

        Design: Corner/state_machines/declare_missing_after_exhaustion_returns_error
        """
        case = create_case(plan_name="Exhausted Co 401k", plan_number="113")
        participant = add_participant(
            case["id"], 1000, full_name="Ex Haust", ssn="111110031"
        )
        search_case = setup_exhausted_search(
            case["id"], participant["id"], document=False
        )
        assert search_case["status"] == "EXHAUSTED"
        assert search_case["exhausted_by_user_id"] == "admin-1"
        locate_participant(participant["id"], verified_address="8 Back Blvd")
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")
        resp = api.declare_missing(participant["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SEARCH_CASE_EXHAUSTED_REDECLARE)
        search_case = get_search_case(search_case["id"])
        assert search_case["status"] == "EXHAUSTED", (
            "the exhausted case must not be reopened by a re-declaration"
        )

    def test_locate_dimension_independent_of_distribution(self, api):
        """PRD §3.3: "Each participant carries two independent state dimensions
        on the same row: `locate_status` (the contact lifecycle: `UNVERIFIED`,
        `FLAGGED_UNCASHED`, `FLAGGED_UNDELIVERABLE`, `MISSING`, `LOCATED`) and
        `distribution_status` (the money lifecycle: `PENDING_ELECTION`,
        `ELECTION_SUBMITTED`, `ELECTION_ACCEPTED`, `PAID_OUT`,
        `AUTO_ROLLED_OVER`, `PBGC_TRANSFERRED`, `FORFEITED`, `RESTORED`). A
        transition on one dimension never changes the other unless a stated
        cascade says so."

        Design: Difficulty/non_linear_state_machine/participant_parallel_state_dimensions
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Parallel Co 401k", plan_number="040"
        )
        participant = plist[0]
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")
        participant = declare_participant_missing(participant["id"])
        assert participant["locate_status"] == "MISSING"
        assert participant["distribution_status"] == "PENDING_ELECTION", (
            "the locate dimension moved; the money dimension must be untouched"
        )
        participant = locate_participant(participant["id"], verified_address="5 New Ln")
        assert participant["locate_status"] == "LOCATED"
        assert participant["distribution_status"] == "PENDING_ELECTION"

    def test_distribution_dimension_independent_of_locate(self, api):
        """PRD §3.3: "A transition on one dimension never changes the other
        unless a stated cascade says so."
        PRD §3.6: "A successful submission creates the election in `SUBMITTED`,
        supersedes any prior `SUBMITTED` election of the same participant
        (`SUBMITTED → SUPERSEDED`), moves the participant's `distribution_status`
        to `ELECTION_SUBMITTED`, and increments the participant's `version` by
        one."

        Design: Difficulty/non_linear_state_machine/participant_parallel_state_dimensions
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Parallel Co 401k", plan_number="040"
        )
        participant = plist[0]
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")
        declare_participant_missing(participant["id"])
        locate_participant(participant["id"], verified_address="5 New Ln")
        election = submit_election(participant["id"], "DIRECT_ROLLOVER_IRA")
        assert election["status"] == "SUBMITTED"
        participant = get_participant(participant["id"])
        assert participant["distribution_status"] == "ELECTION_SUBMITTED"
        assert participant["locate_status"] == "LOCATED", (
            "the money dimension moved; the locate dimension must be untouched"
        )

    def test_declare_missing_response_shows_cascade(self, api):
        """PRD §3.3: "A successful declaration stamps `declared_missing_at` with
        the clock time and arms the search machinery: if no prior
        `MissingSearchCase` exists, one is created in `STEP1_COMMERCIAL_LOCATOR`
        with `opened_at` set to now; if the latest case is `RESOLVED`, it
        reopens to `STEP1_COMMERCIAL_LOCATOR` with its `resolved_at` cleared to
        null while `opened_at` is preserved from the original opening."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.8: "`missing_participant_count` counts participants whose
        `locate_status` is `MISSING`".

        Design: Corner/consistency_model/cascade_visible_in_same_response
        """
        case = create_case(plan_name="Immediate Co 401k", plan_number="190")
        participant = add_participant(
            case["id"], 1000, full_name="Im Mediate", ssn="121110070"
        )
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")
        resp = api.declare_missing(participant["id"], ADMIN)
        updated = validate_success(resp)
        assert updated["locate_status"] == "MISSING", (
            "the declare-missing response itself carries the new locate_status"
        )
        assert updated["active_search_case_id"], (
            "the same response carries the freshly opened search case id"
        )
        search_case = get_search_case(updated["active_search_case_id"])
        assert_search_case(search_case)
        assert search_case["status"] == "STEP1_COMMERCIAL_LOCATOR"
        assert_instant_equal(
            search_case["opened_at"], "2026-08-01T00:00:00Z", "opened_at"
        )
        assert search_case["attempt_count"] == 0
        case = get_case(case["id"])
        assert case["missing_participant_count"] == 1

    def test_fk_reverse_reachability_reads(self, api):
        """PRD §2.10: "List endpoints support filters matching the foreign keys
        declared in §4 — including `termination_case_id`, `participant_id`,
        `active_search_case_id`, `locate_status`, `distribution_status`,
        `notice_type`, `superseded_by_id`, `status`, and `entry_type` — each of
        which narrows the returned collection to rows whose corresponding field
        equals the supplied value, on top of the envelope pagination parameters
        `limit` and `offset`."

        Design: Corner/endpoints/fk_reverse_reachability_reads
        """
        case = create_case(plan_name="Reverse Co 401k", plan_number="161")
        notice = issue_noit(case["id"])
        participant = add_participant(
            case["id"], 1000, full_name="Re Verse", ssn="121110040"
        )
        participant, search_case = setup_missing_participant(
            participant["id"], flag_clock=None
        )
        record_search_attempt(
            search_case["id"], "COMMERCIAL_LOCATOR", "2026-08-01T00:00:00Z"
        )

        data, _ = validate_paginated(
            api.list_search_cases(ADMIN, params={"participant_id": participant["id"]})
        )
        assert [row["id"] for row in data] == [search_case["id"]]

        data, _ = validate_paginated(
            api.list_participants(
                ADMIN, params={"active_search_case_id": search_case["id"]}
            )
        )
        assert [row["id"] for row in data] == [participant["id"]]

        data, _ = validate_paginated(api.list_attempts(search_case["id"], ADMIN))
        assert len(data) == 1
        assert data[0]["method"] == "COMMERCIAL_LOCATOR"

        data, _ = validate_paginated(
            api.list_notices(ADMIN, params={"termination_case_id": case["id"]})
        )
        assert [row["id"] for row in data] == [notice["id"]]
