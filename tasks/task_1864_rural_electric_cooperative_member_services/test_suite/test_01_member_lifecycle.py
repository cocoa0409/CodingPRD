"""Member lifecycle: creation defaults, invalid transitions, terminal lockdown,
invoice-gated suspension/reinstatement/termination (PRD §3.1)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_invoice_payload,
    create_member_payload,
    create_rate_schedule_payload,
    get_success_data,
    setup_cooperative,
    setup_finalized_invoice,
    setup_member,
    setup_published_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

REP = TEST_USERS["rep"]
ANALYST = TEST_USERS["rate_analyst"]
CLERK = TEST_USERS["billing_clerk"]


class TestMemberCreation:
    def test_create_member_success_and_defaults(self, api):
        """PRD §3.1: "A new member starts as an `APPLICANT`, and the roster of
        members can be listed with optional filters on `status` or `district_id`."
        PRD §2.4: "The `version` is an integer that starts low and increments on
        every mutation of the resource."

        Design: Corner/entities/create_member_success_and_defaults
        """
        setup_cooperative()
        data = validate_success(api.create_member(
            {"legal_name": "New M", "member_type": "RESIDENTIAL", "district_id": 1}, REP),
            expected_status=201)
        assert data["status"] == "APPLICANT"
        assert data["version"] == 1
        assert data["capital_credit_balance_cents"] == 0
        assert data["unclaimed_credit_cents"] == 0

    def test_create_member_missing_legal_name_returns_invalid_request(self, api):
        """PRD §2.8: "Independently of this ordering, a request body missing a
        required field or carrying a malformed value is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_member_missing_required_field_returns_invalid_request
        """
        setup_cooperative()
        resp = api.create_member({"member_type": "RESIDENTIAL", "district_id": 1}, REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_member_not_found_returns_404(self, api):
        """PRD §2.10: "the server returns `ERR_NOT_FOUND` (HTTP 404) for that
        identifier without examining anything further along the path."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        setup_cooperative()
        resp = api.get_member(NON_EXISTENT_UUID, REP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_member_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response always carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/member_list_pagination_envelope
        """
        setup_cooperative()
        for i, name in enumerate(("A", "B", "C"), start=1):
            get_success_data(api.create_member(
                create_member_payload(legal_name=name, district_id=i), REP), 201)
        data, meta = validate_paginated(api.list_members(REP, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_invalid_member_type_returns_invalid_request(self, api):
        """PRD §3.1: "a `member_type` of `RESIDENTIAL`, `COMMERCIAL`, or
        `IRRIGATION`" and §2.8: "a request body missing a required field or
        carrying a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enum_on_member_type_returns_invalid_request
        """
        setup_cooperative()
        resp = api.create_member(
            {"legal_name": "X", "member_type": "WHOLESALE", "district_id": 1}, REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMemberStateMachine:
    def test_terminate_from_applicant_returns_invalid_state(self, api):
        """PRD §3.1: "Termination is the terminal state. From `ACTIVE`, it
        requires that the member hold no invoice in `PROVISIONAL` status and no
        `FINALIZED` invoice still unpaid" — termination is defined only from
        ACTIVE or SUSPENDED, so an APPLICANT target is not in a legitimate
        from-state (`ERR_INVALID_STATE` per §2.8 rule five).

        Design: Corner/state_machines/terminate_from_applicant_returns_invalid_state
        """
        setup_cooperative()
        member = get_success_data(api.create_member(
            create_member_payload(legal_name="M"), REP), 201)
        resp = api.terminate_member(member["id"], REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_terminated_member_terminal_lockdown(self, api):
        """PRD §3.1: "Termination is the terminal state." Reinstatement is
        defined only as returning "a `SUSPENDED` member to `ACTIVE`", so a
        TERMINATED member rejects reinstate with ERR_INVALID_STATE.

        Design: Corner/state_machines/terminated_member_terminal_lockdown
        """
        setup_cooperative()
        member, _loc = setup_member(status="ACTIVE")
        member = get_success_data(api.terminate_member(member["id"], REP), 200)
        assert member["status"] == "TERMINATED"
        resp = api.reinstate_member(member["id"], REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_suspend_reinstate_cycle_returns_active(self, api):
        """PRD §3.1: "Reinstatement returns a `SUSPENDED` member to `ACTIVE`
        once every `FINALIZED` invoice across their locations has been `PAID`."

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        setup_cooperative()
        member, _loc = setup_member(status="ACTIVE")
        version_at_active = member["version"]
        member = get_success_data(api.suspend_member(member["id"], REP), 200)
        assert member["status"] == "SUSPENDED"
        member = get_success_data(api.reinstate_member(member["id"], REP), 200)
        assert member["status"] == "ACTIVE"
        assert member["version"] == version_at_active + 2

    def test_suspend_reinstate_cycle_repeated(self, api):
        """PRD §3.1: "Suspension is available against an `ACTIVE` member" and
        "Reinstatement returns a `SUSPENDED` member to `ACTIVE`" — the cycle can
        be exercised twice in a row.

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        setup_cooperative()
        member, _loc = setup_member(status="ACTIVE")
        for _ in range(2):
            member = get_success_data(api.suspend_member(member["id"], REP), 200)
            assert member["status"] == "SUSPENDED"
            member = get_success_data(api.reinstate_member(member["id"], REP), 200)
            assert member["status"] == "ACTIVE"

    def test_suspend_blocked_by_provisional_invoice(self, api):
        """PRD §3.1: "Suspension is available against an `ACTIVE` member, but
        only when no invoice for any of the member's locations is still in
        `PROVISIONAL` status; a lingering provisional bill blocks the move with
        `ERR_MEMBER_PROVISIONAL_INVOICE`."

        Design: Corner/state_machines/member_suspend_blocked_by_provisional_invoice
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        setup_published_schedule(rate_class="RESIDENTIAL")
        get_success_data(api.create_invoice(
            create_invoice_payload(service_location_id=location["id"]), CLERK), 201)
        resp = api.suspend_member(member["id"], REP)
        validate_error(resp, ApiErrorId.ERR_MEMBER_PROVISIONAL_INVOICE)

    def test_reinstate_blocked_by_unpaid_final_invoice(self, api):
        """PRD §3.1: "Reinstatement returns a `SUSPENDED` member to `ACTIVE`
        once every `FINALIZED` invoice across their locations has been `PAID` —
        an unpaid finalized bill blocks it with `ERR_MEMBER_PAST_DUE`."

        Design: Corner/errors/reinstate_blocked_by_unpaid_final_invoice
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        setup_published_schedule(rate_class="RESIDENTIAL")
        setup_finalized_invoice(
            location["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 0, 100)
        member = get_success_data(api.suspend_member(member["id"], REP), 200)
        assert member["status"] == "SUSPENDED"
        resp = api.reinstate_member(member["id"], REP)
        validate_error(resp, ApiErrorId.ERR_MEMBER_PAST_DUE)

    def test_terminate_blocked_by_unpaid_final_invoice(self, api):
        """PRD §3.1: "From `ACTIVE`, it requires that the member hold no invoice
        in `PROVISIONAL` status and no `FINALIZED` invoice still unpaid;
        otherwise the request fails with `ERR_MEMBER_UNPAID_FINAL`."

        Design: Corner/errors/terminate_blocked_by_unpaid_final_invoice
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        setup_published_schedule(rate_class="RESIDENTIAL")
        setup_finalized_invoice(
            location["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 0, 100)
        resp = api.terminate_member(member["id"], REP)
        validate_error(resp, ApiErrorId.ERR_MEMBER_UNPAID_FINAL)
