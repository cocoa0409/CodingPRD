"""Applicant registration and application filing/submission rules (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_application,
    create_applicant_payload,
    create_application_payload,
    get_application,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_applicant,
    make_application,
    make_cycle,
    make_open_world,
    make_parent_headers,
    make_section,
    open_cycle,
    parse_instant,
    pin_clock,
    set_clock,
    setup_decision_world,
    setup_scored_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestApplicantRegistration:
    def test_applicant_legacy_parent_defaults_false(self, api, director_headers):
        """PRD §3.2: "Registration records the `family_id` of the owning family
        account, the child's `first_name` and `last_name`, a `date_of_birth` as
        an ISO 8601 date in `YYYY-MM-DD` form, and an optional `legacy_parent`
        flag — defaulting to false — that marks a parent as an alumnus for
        legacy preference."

        Design: Corner/entities/applicant_legacy_parent_defaults_false
        """
        pin_clock()
        resp = api.create_applicant(create_applicant_payload("fam-a"),
                                    make_parent_headers("fam-a"))
        data = validate_success(resp, 201)
        assert data["legacy_parent"] is False
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int)

    def test_create_applicant_with_id_field_rejected(self, api, director_headers):
        """PRD §2.7: "The body is well-formed, contains all required fields,
        and carries no unknown fields; failure is `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
        unique per resource."

        Design: Corner/entities/create_applicant_with_id_field_rejected
        """
        pin_clock()
        payload = create_applicant_payload("fam-a")
        payload["id"] = "00000000-0000-4000-8000-0000000000aa"
        resp = api.create_applicant(payload, make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestApplicationCreation:
    def test_application_initial_state_draft(self, api, director_headers):
        """PRD §3.2: "A new application starts in `DRAFT`."
        PRD §3.2: "A successful submission stamps `submitted_at` with the
        logical clock, a value that later feeds ranking tie-breaks; until
        submitted, `submitted_at` is null."

        Design: Corner/state_machines/application_initial_state_draft
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        resp = api.create_application(
            create_application_payload(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"]),
            make_parent_headers("fam-a"),
        )
        data = validate_success(resp, 201)
        assert_application(data)
        assert data["status"] == "DRAFT"
        assert data["submitted_at"] is None
        assert data["composite_score"] is None
        assert data["promoted_from_waitlist"] is False
        assert isinstance(data["version"], int)

    def test_create_application_invalid_round_enum_rejected(
            self, api, director_headers):
        """PRD §2.7: "Enum membership, integer ranges, datetime ordering,
        kind-specific field presence on evaluations, cycle deadline ordering,
        and the revise-award amount band; failure is `ERR_VALIDATION`
        (HTTP 422)."
        PRD §3.2: "the `round` — `EARLY` or `REGULAR`."

        Design: Corner/entities/create_application_invalid_round_enum_rejected
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        resp = api.create_application(
            create_application_payload(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], round="ROLLING"),
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 422)

    def test_get_nonexistent_application_not_found(self, api, director_headers):
        """PRD §2.7: "Path resource existence. Identifiers in the URL path are
        validated left to right; the first missing resource yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_application_not_found
        """
        pin_clock()
        resp = api.get_application("00000000-0000-4000-8000-0000000000ff",
                                   director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_create_application_with_unknown_section_not_found(
            self, api, director_headers):
        """PRD §2.7: "Referenced resources named in the body — `applicant_id`,
        `cycle_id`, `grade_section_id`, `application_id`, `test_session_id`,
        `student_id` — must exist; failure is `ERR_REFERENCE_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/validations/create_application_with_unknown_section_not_found
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        resp = api.create_application(
            create_application_payload(
                applicant["id"], world["cycle"]["id"],
                "00000000-0000-4000-8000-0000000000ee",
            ),
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, 404)

    def test_create_application_in_draft_cycle_rejected(
            self, api, director_headers):
        """PRD §3.2: "Creation is gated: the cycle must be `OPEN` (anything
        else is `ERR_CYCLE_NOT_OPEN`)".

        Design: Corner/validations/create_application_in_draft_cycle_rejected
        """
        cycle = make_cycle()
        section = make_section(cycle["id"])
        applicant = make_applicant("fam-a")
        resp = api.create_application(
            create_application_payload(applicant["id"], cycle["id"],
                                       section["id"]),
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN, 409)

    def test_grade_cycle_mismatch_rejected(self, api, director_headers):
        """PRD §3.2: "the chosen section must belong to the given cycle
        (`ERR_GRADE_CYCLE_MISMATCH` when it belongs to another)".

        Design: Corner/validations/grade_cycle_mismatch_rejected
        """
        cycle_a = make_cycle(
            academic_year="2026-2027",
            early_deadline_at="2026-09-01T00:00:00Z",
            regular_deadline_at="2026-11-15T00:00:00Z",
            aid_budget_total_cents=0,
        )
        section_a = make_section(cycle_a["id"], tuition_cents=2_900_000)
        cycle_b = make_cycle()
        make_section(cycle_b["id"])
        open_cycle(cycle_a["id"])
        open_cycle(cycle_b["id"])
        applicant = make_applicant("fam-a")
        # Both references exist; the section belongs to cycle A, not B.
        resp = api.create_application(
            create_application_payload(applicant["id"], cycle_b["id"],
                                       section_a["id"]),
            make_parent_headers("fam-a"),
        )
        validate_error(resp, ApiErrorId.ERR_GRADE_CYCLE_MISMATCH, 409)

    def test_duplicate_live_application_rejected_then_allowed_after_terminal(
            self, api, director_headers):
        """PRD §3.2: "an applicant may hold only one live application per cycle
        — a second application for the same applicant and cycle while the
        first is in any non-terminal state is rejected with
        `ERR_DUPLICATE_APPLICATION`."
        PRD §3.6: "From `DRAFT`, withdrawal moves the application to
        `WITHDRAWN` with no further effects."

        Design: Corner/validations/duplicate_live_application_rejected_then_allowed_after_terminal
        """
        ctx = setup_submitted_application("fam-a")
        payload = create_application_payload(
            ctx["applicant"]["id"], ctx["cycle"]["id"], ctx["section"]["id"],
            round="REGULAR",
        )
        resp = api.create_application(payload, make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)
        # WITHDRAWN is terminal, so the uniqueness set is empty again.
        resp = api.withdraw_application(ctx["application"]["id"],
                                        make_parent_headers("fam-a"))
        validate_success(resp, 200)
        resp = api.create_application(payload, make_parent_headers("fam-a"))
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"


class TestSubmission:
    def test_submit_after_round_deadline_rejected(self, api, director_headers):
        """PRD §3.2: "the logical clock must be at or before the round's
        deadline — `early_deadline_at` for `EARLY`, `regular_deadline_at` for
        `REGULAR` — with a late submission rejected as
        `ERR_ROUND_DEADLINE_PASSED`."

        Design: Corner/validations/submit_after_round_deadline_rejected
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        application = make_application(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], "fam-a", "EARLY")
        set_clock("2026-11-02T00:00:00Z")  # one day past the EARLY deadline
        resp = api.submit_application(application["id"],
                                      make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_ROUND_DEADLINE_PASSED, 422)
        assert get_application(application["id"])["status"] == "DRAFT"

    def test_submit_when_evaluation_complete_rejected(self, api,
                                                      director_headers):
        """PRD §3.2: "The application must currently be `DRAFT`
        (`ERR_APPLICATION_NOT_DRAFT` otherwise)".

        Design: Corner/state_machines/submit_when_evaluation_complete_rejected
        """
        ctx = setup_scored_application("fam-a")  # 80/90 -> EVALUATION_COMPLETE
        assert ctx["application"]["status"] == "EVALUATION_COMPLETE"
        resp = api.submit_application(ctx["application"]["id"],
                                      make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT, 409)
        assert (get_application(ctx["application"]["id"])["status"]
                == "EVALUATION_COMPLETE")

    def test_immediate_read_after_mutation(self, api, director_headers):
        """PRD §2.9: "Consistency is immediate: every mutation is atomic within
        its request, and derived counters are recomputed inside the same
        request that invalidates them — no background jobs, no eventual
        reconciliation."
        PRD §3.2: "A successful submission stamps `submitted_at` with the
        logical clock".
        PRD §2.5: "`version` (integer): a system-managed counter that
        increments by one on every mutation of the resource".

        Design: Corner/consistency_model/immediate_read_after_mutation
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        application = make_application(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], "fam-a", "EARLY")
        created_version = application["version"]
        resp = api.submit_application(application["id"],
                                      make_parent_headers("fam-a"))
        validate_success(resp, 200)
        read_back = validate_success(
            api.get_application(application["id"], make_parent_headers("fam-a"))
        )
        assert read_back["status"] == "SUBMITTED"
        # The submit ran at the 2026-08-01T00:00:00Z boot clock (PRD §2.4).
        assert parse_instant(read_back["submitted_at"]) == parse_instant(
            "2026-08-01T00:00:00Z"
        )
        assert read_back["version"] == created_version + 1


class TestSubmitStateBeatsDeadline:
    """Difficulty instance: the state gate precedes the temporal gate in the
    validation pipeline, so a re-submit of a submitted application reports the
    state error even when the deadline has also passed."""

    def test_resubmit_after_deadline_reports_state_error(
            self, api, director_headers):
        """PRD §2.7: "Every request is evaluated against a fixed pipeline of
        validation layers, and the first failing layer wins — later layers are
        never consulted once a rejection is issued."
        PRD §2.7: "10. **Target state preconditions.**" / "11. **Temporal
        gates.**" — the state layer runs before the temporal layer.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_precondition_beats_deadline
        """
        ctx = setup_submitted_application("fam-a")  # submitted at boot clock
        set_clock("2026-12-01T00:00:00Z")  # past the 2026-11-01 EARLY deadline
        resp = api.submit_application(ctx["application"]["id"],
                                      make_parent_headers("fam-a"))
        # Both gates are violated; the state error must win (409, not 422).
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT, 409)
        assert get_application(ctx["application"]["id"])["status"] == "SUBMITTED"

    def test_resubmit_before_deadline_also_reports_state_error(
            self, api, director_headers):
        """PRD §3.2: "The application must currently be `DRAFT`
        (`ERR_APPLICATION_NOT_DRAFT` otherwise)" — with the clock still inside
        the round window the state gate is the only one that can fire.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_precondition_beats_deadline
        """
        ctx = setup_submitted_application("fam-a")
        resp = api.submit_application(ctx["application"]["id"],
                                      make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT, 409)
        assert get_application(ctx["application"]["id"])["status"] == "SUBMITTED"


class TestTerminalLockdown:
    def test_withdraw_denied_application_terminal_rejected(
            self, api, director_headers):
        """PRD §3.2: "An application's `status` walks a wide state space:
        `DRAFT`, `SUBMITTED`, `EVALUATION_COMPLETE`, `OFFERED`,
        `CONTRACT_ISSUED`, `WAITLISTED`, `ENROLLED`, and the terminal states
        `DENIED`, `DECLINED`, `WITHDRAWN`, `EXPIRED`, and `MELTED`."
        PRD §3.3: "one in a terminal state with `ERR_APPLICATION_TERMINAL`" —
        the terminal-state gate code for operations on finished applications.

        Design: Corner/state_machines/withdraw_denied_application_terminal_rejected
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-h", "test": 100, "interview": 100},
                {"family": "fam-m", "test": 80, "interview": 90},
                {"family": "fam-l", "test": 60, "interview": 60},
            ],
            capacity=1,
        )
        denied = ctx["candidates"][2]["application"]
        assert denied["status"] == "DENIED"
        resp = api.withdraw_application(denied["id"],
                                        make_parent_headers("fam-l"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_TERMINAL, 409)
        assert get_application(denied["id"])["status"] == "DENIED"


class TestListing:
    def test_list_applicants_pagination_and_envelope(self, api, officer_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults
        to 0."
        PRD §2.3: "Paginated list responses carry four fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/list_applicants_pagination_and_envelope
        """
        for index in range(11):
            make_applicant("fam-p", as_officer=True,
                           first_name=f"K{index + 1:02d}",
                           date_of_birth=f"2013-01-{index + 1:02d}")
        data, meta = validate_paginated(api.list_applicants(officer_headers))
        assert len(data) == 10
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 11 and meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_applicants(officer_headers, params={"limit": 10,
                                                         "offset": 10})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 11 and meta2["has_more"] is False
