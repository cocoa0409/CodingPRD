"""Non-linear state machine cycles: resolution reject-redraft, minutes
review-rejection loop, and package seal-unseal cycle."""
from test_helpers import (
    add_director,
    add_document,
    cast_ballot,
    close_vote_as_chair,
    create_meeting_resolution,
    create_package,
    get_success_data,
    open_vote_as_chair,
    set_clock,
    setup_adjourned_meeting_with_minutes,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    setup_vote_open_resolution,
    table_resolution,
    validate_success,
    make_chair_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestResolutionRejectRedraftCycle:
    """Difficulty instance: resolution_reject_redraft_cycle.

    Round 1: VOTE_OPEN -> REJECTED with 1 FOR / 2 AGAINST. Redraft voids the
    ballots and zeroes tallies. Round 2: 3 FOR -> ADOPTED.
    """

    def _setup_round1_rejected(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp RC")
        d1, d2, d3 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d["id"] for d in directors])
        r = create_meeting_resolution(corp["id"], m["id"], title="Cycle R", text="v1 text")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        v1 = cast_ballot(r["id"], d1["id"], "FOR")
        cast_ballot(r["id"], d2["id"], "AGAINST")
        cast_ballot(r["id"], d3["id"], "AGAINST")
        close_vote_as_chair(r["id"], d1["id"])
        return corp, directors, m, r, v1

    def test_redraft_voids_round1_ballots_and_resets_tallies(self, api):
        """PRD §3.6: "the secretary may redraft it back to `DRAFT`, voiding any
        remaining `ACTIVE` ballots, resetting all four tallies to zero, and
        clearing its consent fields."

        Design: Difficulty/non_linear_state_machine/resolution_reject_redraft_cycle
        """
        _corp, _directors, _m, r, v1 = self._setup_round1_rejected(api)
        resp = api.redraft_resolution(r["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DRAFT"
        assert data["for_count"] == 0 and data["against_count"] == 0
        v1_after = get_success_data(api.get_vote_record(v1["id"], SECRETARY))
        assert v1_after["status"] == "VOIDED"

    def test_full_cycle_lands_adopted(self, api):
        """PRD §3.6: "the secretary may redraft it back to `DRAFT`" — after
        redraft, the resolution may re-table, re-open, and close into ADOPTED.

        Design: Difficulty/non_linear_state_machine/resolution_reject_redraft_cycle
        """
        _corp, directors, _m, r, _v1 = self._setup_round1_rejected(api)
        d1, d2, d3 = directors
        api.redraft_resolution(r["id"], SECRETARY)
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        cast_ballot(r["id"], d1["id"], "FOR")
        cast_ballot(r["id"], d2["id"], "FOR")
        cast_ballot(r["id"], d3["id"], "FOR")
        close_vote_as_chair(r["id"], d1["id"])
        final = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert final["status"] == "ADOPTED"
        assert final["for_count"] == 3
        assert final["against_count"] == 0


class TestMinutesReviewRejectionLoop:
    """Difficulty instance: minutes_review_rejection_loop."""

    def _setup_minutes_draft(self, api):
        corp, bylaws, directors = setup_corporation_with_directors(
            2, name="Corp M", minute_retention_years=5
        )
        d1 = directors[0]
        m, mn = setup_adjourned_meeting_with_minutes(
            corp["id"],
            d1["id"],
            [d1["id"], directors[1]["id"]],
            convene_clock="2026-06-20T11:00:00Z",
        )
        return corp, d1, m, mn

    def test_reject_redraft_circulate_loop_increments_review_round(self, api):
        """PRD §3.9: "each circulation stores the supplied `content` and
        increments `review_round`." / "the circulate-review loop may run as
        many rounds as needed, `review_round` climbing each time."

        Design: Difficulty/non_linear_state_machine/minutes_review_rejection_loop
        """
        _corp, d1, _m, mn = self._setup_minutes_draft(api)
        api.circulate_minutes(mn["id"], {"content": "draft v1"}, SECRETARY)
        api.reject_minutes(mn["id"], {"reason": "typo in attendees"}, make_chair_headers(d1["id"]))
        api.redraft_minutes(mn["id"], {"content": "draft v2 corrected"}, SECRETARY)
        api.circulate_minutes(mn["id"], {"content": "draft v2 corrected"}, SECRETARY)
        after = get_success_data(api.get_minutes(mn["id"], SECRETARY))
        assert after["review_round"] == 2, f"expected 2 circulations, got {after['review_round']}"
        assert after["status"] == "CIRCULATED_FOR_REVIEW"

    def test_approve_enter_book_assigns_seq_and_hash(self, api):
        """PRD §3.9: "The secretary enters an `APPROVED` minutes, which moves
        it to `ENTERED_IN_BOOK` and stamps two evidentiary fields: `book_seq_no`,
        one greater than the highest `book_seq_no` already entered for that
        corporation — zero when the book is empty — so the sequence is
        gap-free, and `content_hash`, the lowercase SHA-256 hexadecimal of the
        `content`." / "computes `retention_until` as `approved_at` advanced by
        the `minute_retention_years` of the corporation's currently adopted
        bylaws".

        Design: Difficulty/non_linear_state_machine/minutes_review_rejection_loop
        """
        _corp, d1, _m, mn = self._setup_minutes_draft(api)
        api.circulate_minutes(mn["id"], {"content": "draft v1"}, SECRETARY)
        api.reject_minutes(mn["id"], {"reason": "typo"}, make_chair_headers(d1["id"]))
        api.redraft_minutes(mn["id"], {"content": "draft v2 corrected"}, SECRETARY)
        api.circulate_minutes(mn["id"], {"content": "draft v2 corrected"}, SECRETARY)
        api.approve_minutes(mn["id"], make_chair_headers(d1["id"]))
        resp = api.enter_book_minutes(mn["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ENTERED_IN_BOOK"
        assert data["book_seq_no"] == 1
        assert data["retention_until"].startswith("2031-06-20T11:00:00"), (
            f"expected retention_until = approved_at + 5 years, got {data['retention_until']}"
        )
        # SHA-256 of "draft v2 corrected"
        expected_hash = "34c66333240fcd2100d8b552e0bd9f2889acf2e762865afb0601ae651a4a2a84"
        assert data["content_hash"] == expected_hash, (
            f"expected sha256 of 'draft v2 corrected', got {data['content_hash']}"
        )


class TestPackageSealUnsealCycle:
    """Difficulty instance: package_seal_unseal_cycle."""

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp P")
        d1 = directors[0]
        from test_helpers import schedule_noticed_meeting

        m = schedule_noticed_meeting(corp["id"], d1["id"])
        p = create_package(m["id"])
        add_document(p["id"], "Agenda", "s3://a", "GENERAL")
        api.seal_board_package(p["id"], SECRETARY)
        api.unseal_board_package(p["id"], SECRETARY)
        add_document(p["id"], "Financials", "s3://f", "CONFIDENTIAL")
        api.seal_board_package(p["id"], SECRETARY)
        return corp, d1, m, p

    def test_seal_count_accumulates_across_unseal(self, api):
        """PRD §3.5: "a seal stamps `sealed_at` from the clock and increments
        `seal_count`. A sealed package can be reopened for corrections —
        `SEALED` → `ASSEMBLING` — and sealed again later." Unsealing does not
        reset the seal counter.

        Design: Difficulty/non_linear_state_machine/package_seal_unseal_cycle
        """
        _corp, _d1, _m, p = self._setup(api)
        after = get_success_data(api.get_board_package(p["id"], SECRETARY))
        assert after["seal_count"] == 2, f"expected 2 seals, got {after['seal_count']}"
        assert after["document_count"] == 2
        assert after["status"] == "SEALED"

    def test_distribute_within_lead_window(self, api):
        """PRD §3.5: "Distribution releases a `SEALED` package, but only within
        the bylaws lead window: the current clock must be no later than the
        meeting's `scheduled_start` minus the `package_lead_days` of the
        governing bylaws". PRD §3.5: "Distribution stamps `distributed_at` and
        moves the package to the terminal `DISTRIBUTED` state".

        Design: Difficulty/non_linear_state_machine/package_seal_unseal_cycle
        """
        _corp, _d1, _m, p = self._setup(api)
        # package_lead_days=5, scheduled_start 2026-06-20T10:00Z -> deadline 2026-06-15T10:00Z.
        set_clock("2026-06-14T10:00:00Z")
        resp = api.distribute_board_package(p["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DISTRIBUTED"
        assert data["distributed_at"].startswith("2026-06-14T10:00:00")
