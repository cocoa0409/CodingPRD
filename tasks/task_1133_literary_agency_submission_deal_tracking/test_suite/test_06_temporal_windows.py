"""Period-anchored temporal rules: the editor exclusivity half-open window,
the query-lapse cascade on period close, and the closed-books prefix gate."""
from test_helpers import (
    ApiErrorId,
    assign_query,
    assign_reader,
    close_books,
    close_period,
    create_agency,
    create_agent,
    create_author,
    create_editor,
    create_round,
    create_signed_agreement,
    create_accepted_manuscript,
    intake_query,
    make_agent_headers,
    open_round,
    queue_submission,
    request_manuscript,
    send_submission,
    setup_negotiating_deal,
    setup_signed_pipeline,
    create_royalty_statement_payload,
    get_manuscript,
    get_query,
    validate_error,
    validate_success,
)


def _second_signed_manuscript(ctx, genre="YA", word_count=85000, title="Book Two"):
    """Drive a second manuscript for the same agency/author to SIGNED."""
    pipe = create_accepted_manuscript(
        ctx["agency"]["id"], ctx["agent"]["id"], ctx["author"]["id"],
        genre=genre, word_count=word_count, title=title, eval_score=82,
    )
    agreement = create_signed_agreement(
        ctx["agency"]["id"], ctx["agent"]["id"], ctx["author"]["id"],
        pipe["manuscript"]["id"],
    )
    return pipe["manuscript"], agreement


def _setup_exclusivity_window():
    """s1 (round 1) SENT to edA at period 0; s2 (round 2, same editor) QUEUED."""
    ctx = setup_signed_pipeline(agency_name="Agency T1")
    agent_id = ctx["agent"]["id"]
    editor = create_editor(ctx["agency"]["id"], display_name="Ed A")

    round1 = create_round(ctx["manuscript"]["id"], agent_id)
    s1 = queue_submission(round1["id"], editor["id"], agent_id)
    open_round(round1, agent_id)
    send_submission(s1["id"], agent_id)

    manuscript2, _agr2 = _second_signed_manuscript(ctx)
    round2 = create_round(manuscript2["id"], agent_id)
    s2 = queue_submission(round2["id"], editor["id"], agent_id)
    open_round(round2, agent_id)
    return ctx, editor, s1, s2


class TestEditorExclusivityWindow:
    def test_editor_window_collision_inside_window(self, api):
        """PRD 3.5: "no other submission to the same editor — in any round, for any manuscript — may currently be in `SENT`, `UNDER_CONSIDERATION`, or `OFFER_EXTENDED` with a `sent_period_index` of p while the agency's current `period_index` is still less than p + 2."
        PRD 3.5: "The window is half-open: a send landing exactly at p + 2 is allowed, while one at p + 1 is rejected with `ERR_EDITOR_EXCLUSIVE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/editor_exclusivity_half_open_window
        """
        ctx, editor, _s1, s2 = _setup_exclusivity_window()
        agent_id = ctx["agent"]["id"]

        at_p = api.send_submission(s2["id"], make_agent_headers(agent_id))
        validate_error(at_p, ApiErrorId.ERR_EDITOR_EXCLUSIVE_WINDOW.value)

        close_period(ctx["agency"]["id"])
        at_p1 = api.send_submission(s2["id"], make_agent_headers(agent_id))
        validate_error(at_p1, ApiErrorId.ERR_EDITOR_EXCLUSIVE_WINDOW.value)

    def test_editor_window_adjacent_send_allowed(self, api):
        """PRD 3.5: "The window is half-open: a send landing exactly at p + 2 is allowed, while one at p + 1 is rejected with `ERR_EDITOR_EXCLUSIVE_WINDOW`. A successful send stamps `sent_period_index` with the current `period_index`."

        Design: Difficulty/resource_temporal_overlap/editor_exclusivity_half_open_window
        """
        ctx, editor, _s1, s2 = _setup_exclusivity_window()
        agent_id = ctx["agent"]["id"]

        close_period(ctx["agency"]["id"])
        close_period(ctx["agency"]["id"])
        resp = api.send_submission(s2["id"], make_agent_headers(agent_id))
        sent = validate_success(resp, 200)
        assert sent["status"] == "SENT"
        assert sent["sent_period_index"] == 2, (
            "the touching endpoint p + 2 must not collide with the half-open window"
        )


class TestClosePeriodLapseCascade:
    def _setup_stale_requested_query(self):
        """Query requested at period 0; linked manuscript stays READER_ASSIGNED."""
        agency = create_agency(name="Agency LP")
        agent = create_agent(agency["id"])
        author = create_author(agency["id"])
        query = intake_query(agent["id"], author["id"], genre="YA", word_count=80000)
        assign_query(query["id"], agent["id"])
        manuscript = request_manuscript(query["id"], agent["id"], title="Stale Book")
        assign_reader(manuscript["id"], agent["id"])
        return agency, agent, query, manuscript

    def test_lapse_triggers_only_when_period_passes(self, api):
        """PRD 3.2: "When the period closes and period N becomes the completed period, every letter still in `REQUESTED` whose `requested_period_index` is at or before N minus one lapses to `LAPSED` — but only while its linked manuscript is still early in its own pipeline, namely `SUBMITTED` or `READER_ASSIGNED`."

        Design: Difficulty/transitive_cascade/close_period_lapse_cascade_three_links
        """
        agency, agent, query, _manuscript = self._setup_stale_requested_query()

        after1 = close_period(agency["id"])
        assert after1["period_index"] == 1
        letter1 = get_query(query["id"])
        assert letter1["status"] == "REQUESTED", (
            "closing period 0 completes N=0; requested_period_index 0 <= -1 is false, no lapse"
        )

        after2 = close_period(agency["id"])
        assert after2["period_index"] == 2
        letter2 = get_query(query["id"])
        assert letter2["status"] == "LAPSED", (
            "closing period 1 completes N=1; requested_period_index 0 <= 0 triggers the sweep"
        )

    def test_lapse_cascade_declines_linked_manuscript(self, api):
        """PRD 3.2: "The lapse then propagates: each lapsed letter's linked manuscript declines to `DECLINED`, a decline caused by the lapse rather than by the period close directly."

        Design: Difficulty/transitive_cascade/close_period_lapse_cascade_three_links
        """
        agency, agent, query, manuscript = self._setup_stale_requested_query()
        close_period(agency["id"])
        close_period(agency["id"])

        letter = get_query(query["id"])
        assert letter["status"] == "LAPSED"
        manuscript_now = get_manuscript(manuscript["id"])
        assert manuscript_now["status"] == "DECLINED", (
            "the manuscript's decline is caused by the query's lapse, not by close-period"
        )


class TestBooksClosedPrefix:
    def _setup_books_closed_through_one(self):
        """NEGOTIATING deal at period 0; agency advanced to period 2 and books
        closed (books_closed_through_period_index == 1)."""
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency T2")
        close_period(ctx["agency"]["id"])
        close_period(ctx["agency"]["id"])
        closed = close_books(ctx["agency"]["id"])
        assert closed["books_closed_through_period_index"] == 1
        return ctx

    def test_statement_touching_closed_prefix_rejected(self, api, royalties_accountant_headers):
        """PRD 3.8: "Two period gates apply at intake: a `period_index` beyond the agency's current `period_index` is a future statement and fails with `ERR_FUTURE_STATEMENT`, while a `period_index` at or before `books_closed_through_period_index` falls inside closed books and fails with `ERR_BOOKS_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/books_closed_prefix_boundary_touch_rejected
        """
        ctx = self._setup_books_closed_through_one()
        resp = api.create_royalty_statement(
            create_royalty_statement_payload(
                ctx["deal"]["id"], period_index=1,
                units=(100, 0, 0), receipts=(100000, 0, 0),
                publisher_reported_royalty_cents=10000,
            ),
            royalties_accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKS_CLOSED.value)

    def test_statement_adjacent_above_closed_prefix_allowed(self, api, royalties_accountant_headers):
        """PRD 3.8: "Two period gates apply at intake: a `period_index` beyond the agency's current `period_index` is a future statement and fails with `ERR_FUTURE_STATEMENT`, while a `period_index` at or before `books_closed_through_period_index` falls inside closed books and fails with `ERR_BOOKS_CLOSED`."
        PRD 2.6: "statements may only be intaken for a period strictly after `books_closed_through_period_index` and no later than the current `period_index`"

        Design: Difficulty/resource_temporal_overlap/books_closed_prefix_boundary_touch_rejected
        """
        ctx = self._setup_books_closed_through_one()
        resp = api.create_royalty_statement(
            create_royalty_statement_payload(
                ctx["deal"]["id"], period_index=2,
                units=(100, 0, 0), receipts=(100000, 0, 0),
                publisher_reported_royalty_cents=10000,
            ),
            royalties_accountant_headers,
        )
        statement = validate_success(resp, 201)
        assert statement["status"] == "RECEIVED", (
            "the adjacent period above the closed prefix must be accepted"
        )
