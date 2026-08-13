"""Meeting lifecycle transitions, gating, adjourn/reconvene cycle, and the
terminal filing path (PRD §3.2, §3.7, §3.8)."""
from datetime import datetime

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_draft_meeting, add_account, add_proposal, lock_record_date,
    generate_distributions,
    setup_locked_meeting, setup_materials_distributed, setup_voting_open,
    setup_meeting_in_progress, setup_meeting_held,
    add_broker_search, respond_broker_search,
    create_certification_draft, current_meeting_version,
    make_inspector_headers, make_shareholder_headers,
    MEETING_DATETIME,
)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestLifecycleGates:
    def test_open_voting_from_draft_returns_invalid_meeting_state(self, api, proxy_admin_headers):
        """PRD §3.7: "Opening requires the meeting to be in
        `MATERIALS_DISTRIBUTED`".
        PRD §2.6: "4. **State.** Whether the target resource's lifecycle
        state permits the operation (`ERR_INVALID_MEETING_STATE` and its
        resource-specific counterparts)."

        Design: Corner/state_machines/open_voting_from_draft_returns_invalid_meeting_state
        """
        meeting = create_draft_meeting()
        resp = api.open_voting(meeting["id"], proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_MEETING_STATE, 409)
        current = validate_success(api.get_meeting(meeting["id"], proxy_admin_headers), 200)
        assert current["status"] == "DRAFT", "rejected open-voting must not transition the meeting"

    def test_double_lock_record_date_returns_invalid_meeting_state(self, api, proxy_admin_headers):
        """PRD §3.2: "The `ProxyAdministrator` performs the lock, which requires
        the meeting to be in `DRAFT`".

        Design: Corner/state_machines/double_lock_record_date_returns_invalid_meeting_state
        """
        meeting = create_draft_meeting()
        add_account(meeting["id"], "A-1001")
        lock_record_date(meeting["id"])
        resp = api.lock_record_date(meeting["id"], proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_MEETING_STATE, 409)
        current = validate_success(api.get_meeting(meeting["id"], proxy_admin_headers), 200)
        assert current["status"] == "RECORD_DATE_LOCKED", "meeting must remain RECORD_DATE_LOCKED"

    def test_convene_before_meeting_datetime_returns_not_yet_started(self, api, proxy_admin_headers):
        """PRD §3.7: "convening moves the meeting `VOTING_OPEN →
        MEETING_IN_PROGRESS` — but only once the logical clock has reached the
        `meeting_datetime`; convening early is rejected with
        `ERR_MEETING_NOT_YET_STARTED`."
        PRD §2.4: "At server startup the logical clock is set to exactly
        `2026-08-01T00:00:00Z`".

        Design: Corner/validations/convene_before_meeting_datetime_returns_not_yet_started
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        # Logical clock is untouched: still the 2026-08-01 startup default,
        # which precedes the 2026-09-15 meeting datetime.
        resp = api.convene(m_id, proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_YET_STARTED, 422)
        current = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert current["status"] == "VOTING_OPEN", "meeting must remain VOTING_OPEN"

    def test_conclude_from_adjourned_returns_invalid_meeting_state(self, api, proxy_admin_headers):
        """PRD §3.7: "A successful conclusion moves the meeting
        `MEETING_IN_PROGRESS → MEETING_HELD`" — conclusion is defined only from
        the in-progress state.
        PRD §2.6: "4. **State.** Whether the target resource's lifecycle
        state permits the operation (`ERR_INVALID_MEETING_STATE` and its
        resource-specific counterparts)."

        Design: Corner/state_machines/conclude_from_adjourned_returns_invalid_meeting_state
        """
        ctx = setup_meeting_in_progress(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        resp = api.adjourn(m_id, proxy_admin_headers)
        validate_success(resp, 200)
        resp = api.conclude(m_id, proxy_admin_headers, {})
        validate_error(resp, ApiErrorId.ERR_INVALID_MEETING_STATE, 409)
        current = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert current["status"] == "ADJOURNED", "meeting must remain ADJOURNED"

    def test_conclude_below_quorum_returns_quorum_not_met(self, api, proxy_admin_headers):
        """PRD §3.7: "the `FINAL` quorum variant — walk-ins included — must be
        met at that moment, or the conclusion is rejected with
        `ERR_QUORUM_NOT_MET` and the meeting stays in progress."

        Design: Corner/validations/conclude_below_quorum_returns_quorum_not_met
        """
        ctx = setup_meeting_in_progress(
            account_specs=[{"shares_held": 4000}],
            vote_specs=[{"account": 0, "choice": "FOR"}],
        )
        m_id = ctx["meeting"]["id"]
        # 4000 / 10000 = 4000bp < 5000bp threshold.
        resp = api.conclude(m_id, proxy_admin_headers, {})
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET, 422)
        current = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert current["status"] == "MEETING_IN_PROGRESS", (
            "rejected conclusion leaves the meeting in progress"
        )

    def test_open_voting_with_pending_broker_search_returns_incomplete(self, api, proxy_admin_headers):
        """PRD §3.2: "The broker search must be fully resolved before voting can
        open: every record of the meeting still in `REQUESTED` blocks the
        opening of voting with `ERR_BROKER_SEARCH_INCOMPLETE`."

        Design: Corner/validations/open_voting_with_pending_broker_search_returns_incomplete
        """
        ctx = setup_locked_meeting()
        m_id = ctx["meeting"]["id"]
        add_proposal(m_id, 1)
        search = add_broker_search(m_id, "BRK-1")
        generate_distributions(m_id)
        blocked = api.open_voting(m_id, proxy_admin_headers)
        validate_error(blocked, ApiErrorId.ERR_BROKER_SEARCH_INCOMPLETE, 422)
        respond_broker_search(search["id"], 2500)
        opened = api.open_voting(m_id, proxy_admin_headers)
        data = validate_success(opened, 200)
        assert data["status"] == "VOTING_OPEN", (
            "once every search is RESPONDED the identical call succeeds"
        )

    def test_open_voting_without_active_proposal_returns_no_active_proposal(self, api, proxy_admin_headers):
        """PRD §3.7: "Opening requires the meeting to be in
        `MATERIALS_DISTRIBUTED`, requires at least one proposal to be `ACTIVE`
        (`ERR_NO_ACTIVE_PROPOSAL`)".

        Design: Corner/validations/open_voting_without_active_proposal_returns_no_active_proposal
        """
        ctx = setup_materials_distributed()
        m_id = ctx["meeting"]["id"]
        proposal = ctx["proposals"][0]
        validate_success(api.withdraw_proposal(proposal["id"], proxy_admin_headers), 200)
        resp = api.open_voting(m_id, proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PROPOSAL, 422)
        current = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert current["status"] == "MATERIALS_DISTRIBUTED", (
            "rejected open-voting must not transition the meeting"
        )


class TestBrokerSearchLifecycle:
    def test_duplicate_broker_code_within_meeting_returns_conflict(self, api, transfer_agent_headers):
        """PRD §3.2: "A broker search record is created with the meeting's
        `meeting_id`, a `broker_code` unique within the meeting
        (`ERR_DUPLICATE_BROKER_CODE` on collision), and the `broker_name`".

        Design: Corner/validations/duplicate_broker_code_within_meeting_returns_conflict
        """
        ctx = setup_locked_meeting()
        m_id = ctx["meeting"]["id"]
        add_broker_search(m_id, "BRK-1")
        resp = api.create_broker_search(
            {"meeting_id": m_id, "broker_code": "BRK-1", "broker_name": "Same Code Broker"},
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BROKER_CODE, 409)

    def test_broker_respond_twice_returns_already_responded(self, api, broker_headers, proxy_admin_headers):
        """PRD §3.2: "The `Broker` answers the request by reporting its omnibus
        `shares_reported`, which must be zero or greater; the response stores
        the figure on the record and transitions it from `REQUESTED` to
        `RESPONDED`. A record that has already been answered rejects a second
        response with `ERR_BROKER_SEARCH_ALREADY_RESPONDED`."

        Design: Corner/state_machines/broker_respond_twice_returns_already_responded
        """
        ctx = setup_locked_meeting()
        m_id = ctx["meeting"]["id"]
        search = add_broker_search(m_id, "BRK-1")
        first = api.respond_broker_search(search["id"], {"shares_reported": 2500}, broker_headers)
        data = validate_success(first, 200)
        assert data["status"] == "RESPONDED"
        resp = api.respond_broker_search(search["id"], {"shares_reported": 9999}, broker_headers)
        validate_error(resp, ApiErrorId.ERR_BROKER_SEARCH_ALREADY_RESPONDED, 409)
        current = validate_success(api.get_broker_search(search["id"], proxy_admin_headers), 200)
        assert current["status"] == "RESPONDED"
        assert current["shares_reported"] == 2500, "the first reported figure is retained"


class TestAdjournReconveneCycle:
    """The meeting machine is cyclic: MEETING_IN_PROGRESS <-> ADJOURNED, with
    vote intake suspended only while adjourned."""

    def test_vote_rejected_while_adjourned(self, api, proxy_admin_headers):
        """PRD §3.7: "Adjourning moves the meeting from `MEETING_IN_PROGRESS`
        to `ADJOURNED` and suspends voting — vote and revoke calls during an
        adjournment fail with `ERR_VOTING_NOT_OPEN`".

        Design: Difficulty/non_linear_state_machine/meeting_adjourn_reconvene_cycle_suspends_voting
        """
        ctx = setup_meeting_in_progress()  # no votes yet
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        adjourned = api.adjourn(m_id, proxy_admin_headers)
        data = validate_success(adjourned, 200)
        assert data["status"] == "ADJOURNED"
        resp = api.create_vote_instruction(
            {
                "meeting_id": m_id,
                "proposal_id": proposal["id"],
                "account_id": account["id"],
                "channel": "INTERNET",
                "choice": "FOR",
                "control_number": account["control_number"],
            },
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN, 409)

    def test_reconvene_reenters_in_progress_and_vote_succeeds(self, api, proxy_admin_headers):
        """PRD §3.7: "reconvening moves the meeting from `ADJOURNED` back to
        `MEETING_IN_PROGRESS`, resuming vote intake."
        PRD §3.4: "A successfully cast instruction starts in `VALIDATED`."

        Design: Difficulty/non_linear_state_machine/meeting_adjourn_reconvene_cycle_suspends_voting
        """
        ctx = setup_meeting_in_progress()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        validate_success(api.adjourn(m_id, proxy_admin_headers), 200)
        reconvened = api.reconvene(m_id, proxy_admin_headers)
        data = validate_success(reconvened, 200)
        assert data["status"] == "MEETING_IN_PROGRESS", (
            f"cycle must re-enter MEETING_IN_PROGRESS, got {data['status']}"
        )
        resp = api.create_vote_instruction(
            {
                "meeting_id": m_id,
                "proposal_id": proposal["id"],
                "account_id": account["id"],
                "channel": "INTERNET",
                "choice": "FOR",
                "control_number": account["control_number"],
            },
            make_shareholder_headers(account["id"]),
        )
        vote = validate_success(resp, 201)
        assert vote["status"] == "VALIDATED", "identical vote succeeds after reconvene"


class TestTerminalLifecycle:
    def test_full_lifecycle_to_filed_meeting_locks_terminal_state(self, api, proxy_admin_headers):
        """PRD §3.8: "A successful signing moves the certification `DRAFT →
        SIGNED`, resolves every `ACTIVE` proposal to `PASSED` or `FAILED`
        according to its `CERTIFIED` tabulation outcome, advances the meeting
        `MEETING_HELD → RESULTS_CERTIFIED`, and increments the meeting's
        `version`."
        PRD §3.8: "From `RESULTS_CERTIFIED`, the administrator files the
        results, supplying the `filing_reference`; the system stamps `filed_at`
        from the logical clock, records the reference, moves the meeting to the
        terminal `FILED_8K` state, and increments its `version`."

        Design: Corner/state_machines/full_lifecycle_to_filed_meeting_locks_terminal_state
        """
        ctx = setup_meeting_held(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        proposal = ctx["proposals"][0]
        cert = create_certification_draft(m_id, creator_user_id="insp-1")
        version = current_meeting_version(m_id)
        signed = api.sign_certification(
            cert["id"], {"expected_meeting_version": version}, make_inspector_headers("insp-2")
        )
        cert_data = validate_success(signed, 200)
        assert cert_data["status"] == "SIGNED"
        prop = validate_success(api.get_proposal(proposal["id"], proxy_admin_headers), 200)
        assert prop["status"] == "PASSED", "CERTIFIED outcome of a unanimous FOR vote is PASSED"
        meeting = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert meeting["status"] == "RESULTS_CERTIFIED"

        filed = api.file_8k(m_id, {"filing_reference": "8-K-2026-0001"}, proxy_admin_headers)
        filed_data = validate_success(filed, 200)
        assert filed_data["status"] == "FILED_8K"
        assert filed_data["filing_reference"] == "8-K-2026-0001"
        assert _parse_ts(filed_data["filed_at"]) == _parse_ts(MEETING_DATETIME), (
            "filed_at is stamped from the logical clock (advanced to the meeting datetime)"
        )
        # Terminal lockdown: any further lifecycle transition fails.
        resp = api.adjourn(m_id, proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_MEETING_STATE, 409)
