"""Submission rounds and editor-facing tracking: open gates, send gates,
close gates, terminal lockdown, and round-open optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    accept_manuscript,
    assign_query,
    assign_reader,
    create_agency,
    create_agent,
    create_author,
    create_client_agreement_payload,
    create_editor,
    create_offer_payload,
    create_round,
    evaluate_manuscript,
    get_submission,
    intake_query,
    make_agent_headers,
    open_round,
    queue_submission,
    record_offer,
    request_manuscript,
    send_submission,
    setup_signed_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


def _signed(name):
    return setup_signed_pipeline(agency_name=name)


class TestRoundOpenGates:
    def test_open_empty_round_rejected(self, api):
        """PRD 3.5: "Beyond concurrency, three business gates apply: a `SIGNED` client agreement must exist for the manuscript (`ERR_AGREEMENT_NOT_SIGNED`); no other round for the same manuscript may already be `OPEN` (`ERR_ROUND_ALREADY_OPEN`); and the round must hold at least one `QUEUED` submission (`ERR_EMPTY_ROUND`)."

        Design: Difficulty/boundary_precision_check/submission_round_open_empty_vs_single_queue
        """
        ctx = _signed("Agency B2")
        agent_id = ctx["agent"]["id"]
        empty_round = create_round(ctx["manuscript"]["id"], agent_id)

        resp = api.open_submission_round(
            empty_round["id"],
            {"expected_submission_round_version": empty_round["version"]},
            make_agent_headers(agent_id),
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_ROUND.value)

        current = api.get_submission_round(empty_round["id"], make_agent_headers(agent_id))
        assert validate_success(current, 200)["status"] == "DRAFT"

    def test_open_single_queue_round_succeeds(self, api):
        """PRD 3.5: "the round must hold at least one `QUEUED` submission (`ERR_EMPTY_ROUND`). A successful open increments the round's `version` by one."

        Design: Difficulty/boundary_precision_check/submission_round_open_empty_vs_single_queue
        """
        ctx = _signed("Agency B2")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        queue_submission(round_data["id"], editor["id"], agent_id)

        opened = open_round(round_data, agent_id)
        assert opened["status"] == "OPEN", "exactly one QUEUED submission is sufficient"
        assert opened["version"] == round_data["version"] + 1

    def test_occ_round_open_stale_version_returns_412(self, api):
        """PRD 2.10: "If the round's current `version` differs — because any mutation, including a previous successful open, has advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state check runs."
        PRD 3.5: "A successful open increments the round's `version` by one."

        Design: Corner/cross_cutting_layers/occ_round_open_stale_version_returns_412
        """
        ctx = _signed("Agency OC1")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        queue_submission(round_data["id"], editor["id"], agent_id)
        stale_version = round_data["version"]

        opened = open_round(round_data, agent_id)
        assert opened["status"] == "OPEN"
        assert opened["version"] == stale_version + 1

        replay = api.open_submission_round(
            round_data["id"],
            {"expected_submission_round_version": stale_version},
            make_agent_headers(agent_id),
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)

    def test_round_open_without_signed_agreement_rejected(self, api):
        """PRD 3.5: "Beyond concurrency, three business gates apply: a `SIGNED` client agreement must exist for the manuscript (`ERR_AGREEMENT_NOT_SIGNED`); no other round for the same manuscript may already be `OPEN` (`ERR_ROUND_ALREADY_OPEN`); and the round must hold at least one `QUEUED` submission (`ERR_EMPTY_ROUND`)."

        Design: Corner/validations/round_open_without_signed_agreement_rejected
        """
        agency = create_agency(name="Agency AN")
        agent = create_agent(agency["id"])
        author = create_author(agency["id"])
        editor = create_editor(agency["id"])
        query = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
        assign_query(query["id"], agent["id"])
        manuscript = request_manuscript(query["id"], agent["id"], title="T")
        assign_reader(manuscript["id"], agent["id"])
        evaluate_manuscript(manuscript["id"], agent["id"], eval_score=80)
        accept_manuscript(manuscript["id"], agent["id"])
        agreement = validate_success(
            api.create_client_agreement(
                create_client_agreement_payload(author["id"], manuscript["id"], agent["id"]),
                make_agent_headers(agent["id"]),
            ),
            201,
        )
        validate_success(api.offer_agreement(agreement["id"], make_agent_headers(agent["id"])), 200)

        round_data = create_round(manuscript["id"], agent["id"])
        queue_submission(round_data["id"], editor["id"], agent["id"])
        resp = api.open_submission_round(
            round_data["id"],
            {"expected_submission_round_version": round_data["version"]},
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED.value)

        current = api.get_submission_round(round_data["id"], make_agent_headers(agent["id"]))
        assert validate_success(current, 200)["status"] == "DRAFT"

    def test_second_open_round_same_manuscript_rejected(self, api):
        """PRD 3.5: "no other round for the same manuscript may already be `OPEN` (`ERR_ROUND_ALREADY_OPEN`)"

        Design: Corner/validations/second_open_round_same_manuscript_rejected
        """
        ctx = _signed("Agency RO")
        agent_id = ctx["agent"]["id"]
        ed_a = create_editor(ctx["agency"]["id"], display_name="Ed A")
        ed_b = create_editor(ctx["agency"]["id"], display_name="Ed B", imprint="Imprint B")

        round1 = create_round(ctx["manuscript"]["id"], agent_id)
        queue_submission(round1["id"], ed_a["id"], agent_id)
        open_round(round1, agent_id)

        round2 = create_round(ctx["manuscript"]["id"], agent_id)
        queue_submission(round2["id"], ed_b["id"], agent_id)
        resp = api.open_submission_round(
            round2["id"],
            {"expected_submission_round_version": round2["version"]},
            make_agent_headers(agent_id),
        )
        validate_error(resp, ApiErrorId.ERR_ROUND_ALREADY_OPEN.value)

        current = api.get_submission_round(round2["id"], make_agent_headers(agent_id))
        assert validate_success(current, 200)["status"] == "DRAFT"


class TestSubmissionCreateAndSendGates:
    def test_duplicate_submission_same_editor_same_round_rejected(self, api):
        """PRD 3.5: "the round must not already contain a submission to the same editor (`ERR_DUPLICATE_SUBMISSION`)"

        Design: Corner/validations/duplicate_submission_same_editor_same_round_rejected
        """
        ctx = _signed("Agency DS")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        queue_submission(round_data["id"], editor["id"], agent_id)

        resp = api.create_submission(
            {"submission_round_id": round_data["id"], "editor_id": editor["id"]},
            make_agent_headers(agent_id),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBMISSION.value)

        listed, _meta = validate_paginated(
            api.list_submissions(make_agent_headers(agent_id),
                                 params={"submission_round_id": round_data["id"]})
        )
        assert len(listed) == 1

    def test_round_capacity_exceeded_at_max_editors(self, api):
        """PRD 3.5: "the round's live population — submissions in `QUEUED`, `SENT`, `UNDER_CONSIDERATION`, or `OFFER_EXTENDED` — must still be below `max_editors`, else `ERR_ROUND_CAPACITY_EXCEEDED`."

        Design: Corner/validations/round_capacity_exceeded_at_max_editors
        """
        ctx = _signed("Agency RC")
        agent_id = ctx["agent"]["id"]
        ed_a = create_editor(ctx["agency"]["id"], display_name="Ed A")
        ed_b = create_editor(ctx["agency"]["id"], display_name="Ed B", imprint="Imprint B")
        round_data = create_round(ctx["manuscript"]["id"], agent_id, max_editors=1)
        queue_submission(round_data["id"], ed_a["id"], agent_id)

        resp = api.create_submission(
            {"submission_round_id": round_data["id"], "editor_id": ed_b["id"]},
            make_agent_headers(agent_id),
        )
        validate_error(resp, ApiErrorId.ERR_ROUND_CAPACITY_EXCEEDED.value)

    def test_send_blocked_while_round_draft(self, api):
        """PRD 3.5: "Marking a submission sent (`QUEUED` → `SENT`) requires the parent round to be `OPEN` (`ERR_ROUND_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/submission_send_requires_round_open
        """
        ctx = _signed("Agency X1")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)

        resp = api.send_submission(submission["id"], make_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_ROUND_NOT_OPEN.value)

        current = get_submission(submission["id"])
        assert current["status"] == "QUEUED"

    def test_send_succeeds_after_round_open(self, api):
        """PRD 3.5: "Marking a submission sent (`QUEUED` → `SENT`) requires the parent round to be `OPEN` (`ERR_ROUND_NOT_OPEN`)"
        PRD 3.5: "A successful send stamps `sent_period_index` with the current `period_index`."

        Design: Difficulty/cross_entity_state_dependency/submission_send_requires_round_open
        """
        ctx = _signed("Agency X1")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)
        open_round(round_data, agent_id)

        sent = send_submission(submission["id"], agent_id)
        assert sent["status"] == "SENT"
        assert sent["sent_period_index"] == 0

    def test_send_to_inactive_editor_rejected(self, api, agency_admin_headers):
        """PRD 3.5: "Marking a submission sent (`QUEUED` → `SENT`) requires the parent round to be `OPEN` (`ERR_ROUND_NOT_OPEN`), requires the editor to be `ACTIVE` (`ERR_EDITOR_INACTIVE`)"

        Design: Corner/validations/send_to_inactive_editor_rejected
        """
        ctx = _signed("Agency EI")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)
        open_round(round_data, agent_id)

        validate_success(api.deactivate_editor(editor["id"], agency_admin_headers), 200)
        resp = api.send_submission(submission["id"], make_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_EDITOR_INACTIVE.value)

        current = get_submission(submission["id"])
        assert current["status"] == "QUEUED"


class TestRoundCloseAndTerminalStates:
    def test_close_round_with_under_consideration_submission_rejected(self, api):
        """PRD 3.5: "Closing the round (`OPEN` → `CLOSED`) refuses to strand live work: it is blocked while any submission in the round is `UNDER_CONSIDERATION` or `OFFER_EXTENDED` (`ERR_ROUND_HAS_LIVE_SUBMISSIONS`)"
        PRD 3.5: "A successful close sweeps every `QUEUED` and `SENT` submission in the round to `WITHDRAWN`, releasing any editor exclusivity window those submissions held."

        Design: Corner/validations/close_round_with_under_consideration_submission_rejected
        """
        ctx = _signed("Agency CL")
        agent_id = ctx["agent"]["id"]
        ed_a = create_editor(ctx["agency"]["id"], display_name="Ed A")
        ed_b = create_editor(ctx["agency"]["id"], display_name="Ed B", imprint="Imprint B")
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        s1 = queue_submission(round_data["id"], ed_a["id"], agent_id)
        s2 = queue_submission(round_data["id"], ed_b["id"], agent_id)
        open_round(round_data, agent_id)
        send_submission(s1["id"], agent_id)
        validate_success(
            api.mark_under_consideration(s1["id"], make_agent_headers(agent_id)), 200
        )

        blocked = api.close_submission_round(round_data["id"], make_agent_headers(agent_id))
        validate_error(blocked, ApiErrorId.ERR_ROUND_HAS_LIVE_SUBMISSIONS.value)

        validate_success(api.pass_submission(s1["id"], make_agent_headers(agent_id)), 200)
        closed = validate_success(
            api.close_submission_round(round_data["id"], make_agent_headers(agent_id)), 200
        )
        assert closed["status"] == "CLOSED"

        s2_now = get_submission(s2["id"])
        assert s2_now["status"] == "WITHDRAWN", "close must sweep QUEUED submissions to WITHDRAWN"

    def test_close_round_with_live_offer_rejected(self, api):
        """PRD 3.6: "Either party can kill the offer from either `RECEIVED` or `UNDER_NEGOTIATION`: the agency's decline lands it in `DECLINED`, and the editor's withdrawal lands it in `WITHDRAWN_BY_EDITOR`; both cascade the parent submission to `PASSED`."
        PRD 3.5: "it is blocked while any submission in the round is `UNDER_CONSIDERATION` or `OFFER_EXTENDED` (`ERR_ROUND_HAS_LIVE_SUBMISSIONS`) and while any offer on the round's submissions is `RECEIVED` or `UNDER_NEGOTIATION` (`ERR_ROUND_HAS_LIVE_OFFERS`)."

        Design: Corner/validations/close_round_with_live_offer_rejected
        """
        ctx = _signed("Agency LO")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)
        open_round(round_data, agent_id)
        send_submission(submission["id"], agent_id)
        offer = record_offer(submission["id"], agent_id, advance_cents=300000)
        assert offer["status"] == "RECEIVED"

        validate_success(api.decline_offer(offer["id"], make_agent_headers(agent_id)), 200)
        s1_now = get_submission(submission["id"])
        assert s1_now["status"] == "PASSED", "offer decline must cascade the submission to PASSED"

        closed = validate_success(
            api.close_submission_round(round_data["id"], make_agent_headers(agent_id)), 200
        )
        assert closed["status"] == "CLOSED"

    def test_withdraw_submission_with_live_offer_rejected(self, api):
        """PRD 3.5: "A submission in `OFFER_EXTENDED` may only be withdrawn manually once its offer has reached `DECLINED`, `WITHDRAWN_BY_EDITOR`, or `SUPERSEDED`; attempting it earlier fails with `ERR_OFFER_STILL_LIVE`."

        Design: Corner/validations/withdraw_submission_with_live_offer_rejected
        """
        ctx = _signed("Agency WL")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)
        open_round(round_data, agent_id)
        send_submission(submission["id"], agent_id)
        offer = record_offer(submission["id"], agent_id, advance_cents=300000)
        assert offer["status"] == "RECEIVED"

        resp = api.withdraw_submission(submission["id"], make_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_OFFER_STILL_LIVE.value)

        current = get_submission(submission["id"])
        assert current["status"] == "OFFER_EXTENDED"

    def test_offer_create_on_queued_submission_invalid_state(self, api):
        """PRD 3.6: "The submission must be in `SENT` or `UNDER_CONSIDERATION` (any other state fails with `ERR_INVALID_STATE`)"

        Design: Corner/validations/offer_create_on_queued_submission_invalid_state
        """
        ctx = _signed("Agency OQ")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)

        resp = api.create_offer(
            create_offer_payload(submission["id"], advance_cents=300000),
            make_agent_headers(agent_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminal_lockdown_pass_on_passed_submission(self, api):
        """PRD 3.5: "`PASSED` and `WITHDRAWN` are terminal for a submission; `CLOSED` is terminal for a round."
        PRD 2.9: "State admissibility — the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/terminal_lockdown_pass_on_passed_submission
        """
        ctx = _signed("Agency TL")
        agent_id = ctx["agent"]["id"]
        editor = create_editor(ctx["agency"]["id"])
        round_data = create_round(ctx["manuscript"]["id"], agent_id)
        submission = queue_submission(round_data["id"], editor["id"], agent_id)
        open_round(round_data, agent_id)
        send_submission(submission["id"], agent_id)
        validate_success(api.pass_submission(submission["id"], make_agent_headers(agent_id)), 200)

        again = api.pass_submission(submission["id"], make_agent_headers(agent_id))
        validate_error(again, ApiErrorId.ERR_INVALID_STATE.value)

        withdrawn = api.withdraw_submission(submission["id"], make_agent_headers(agent_id))
        validate_error(withdrawn, ApiErrorId.ERR_INVALID_STATE.value)

        current = get_submission(submission["id"])
        assert current["status"] == "PASSED"
