"""Minutes lifecycle: retention purge at strict-greater boundary, audit
reconstruction with purged gaps, and per-resolution rounding."""
from test_helpers import (
    add_director,
    add_directors,
    cast_ballot,
    close_vote_as_chair,
    convene_meeting,
    create_meeting_resolution,
    get_minutes_for_meeting,
    get_success_data,
    open_vote_as_chair,
    record_attendance,
    schedule_noticed_meeting,
    set_clock,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    setup_minutes_in_book,
    table_resolution,
    validate_error,
    validate_success,
    make_chair_headers,
    SECRETARY,
    AUDITOR,
)
from test_helpers import api_client


class TestMinutesPurgedOnlyStrictlyAfterRetention:
    """Corner instance: minutes_purged_only_strictly_after_retention.

    minute_retention_years=1, approved at 2026-06-20T11:00Z -> retention_until
    2027-06-20T11:00Z. Checkpoint at exactly retention keeps it; at +1s purges.
    """

    def _setup_minutes_in_book(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(
            1, name="Corp C3", minute_retention_years=1
        )
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        set_clock("2026-06-20T11:00:00Z")
        convene_meeting(m["id"], d1["id"])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        mn = get_minutes_for_meeting(m["id"])
        api.circulate_minutes(mn["id"], {"content": "body of minutes"}, SECRETARY)
        api.approve_minutes(mn["id"], make_chair_headers(d1["id"]))
        api.enter_book_minutes(mn["id"], SECRETARY)
        return corp, d1, m, mn

    def test_equality_with_retention_until_retains(self, api):
        """PRD §3.9: "every minutes record `ENTERED_IN_BOOK` whose
        `retention_until` lies strictly before the current clock moves to the
        terminal `PURGED` state — a clock exactly equal to the retention
        instant retains the record."

        Design: Corner/calculations/minutes_purged_only_strictly_after_retention
        """
        corp, _d1, _m, mn = self._setup_minutes_in_book(api)
        set_clock("2027-06-20T11:00:00Z")
        resp = api.run_checkpoint(corp["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        purged = data.get("purged_minutes_ids", [])
        assert mn["id"] not in purged, f"equality with retention_until must retain, got {purged}"
        after = get_success_data(api.get_minutes(mn["id"], SECRETARY))
        assert after["status"] == "ENTERED_IN_BOOK"

    def test_one_second_after_retention_purges(self, api):
        """PRD §3.9: "Purging clears `content` to the empty string but keeps
        `content_hash`, so the book remains tamper-evident even after its
        pages are gone."

        Design: Corner/calculations/minutes_purged_only_strictly_after_retention
        """
        corp, _d1, _m, mn = self._setup_minutes_in_book(api)
        set_clock("2027-06-20T11:00:01Z")
        resp = api.run_checkpoint(corp["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert mn["id"] in data.get("purged_minutes_ids", []), (
            f"expected {mn['id']} in purged roster, got {data.get('purged_minutes_ids')}"
        )
        after = get_success_data(api.get_minutes(mn["id"], SECRETARY))
        assert after["status"] == "PURGED"
        assert after["content"] == ""
        assert after["content_hash"], "content_hash must be retained after purge"


class TestReconstructionFailsOnPurgedGap:
    """Corner instance: reconstruction_fails_on_purged_gap."""

    def _setup_purged_minutes(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(
            1, name="Corp C4", minute_retention_years=1
        )
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        set_clock("2026-06-20T11:00:00Z")
        convene_meeting(m["id"], d1["id"])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        mn = get_minutes_for_meeting(m["id"])
        api.circulate_minutes(mn["id"], {"content": "body"}, SECRETARY)
        api.approve_minutes(mn["id"], make_chair_headers(d1["id"]))
        api.enter_book_minutes(mn["id"], SECRETARY)
        set_clock("2027-06-21T11:00:00Z")
        api.run_checkpoint(corp["id"], SECRETARY)
        return corp, m, mn

    def test_reconstruction_fails_when_scope_contains_purged_minutes(self, api):
        """PRD §3.9: "The gap check runs first: if any meeting inside the
        window has its minutes in `PURGED` status, the request collapses to
        `FAILED`, setting `failure_reason` and leaving `reconstruction_log`
        null."

        Design: Corner/calculations/reconstruction_fails_on_purged_gap
        """
        corp, _m, _mn = self._setup_purged_minutes(api)
        ar_resp = api.create_audit_request(
            {
                "corporation_id": corp["id"],
                "requested_by_label": "Aud",
                "scope_start": "2026-01-01T00:00:00Z",
                "scope_end": "2026-12-31T23:59:59Z",
            },
            AUDITOR,
        )
        ar = get_success_data(ar_resp)
        resp = api.reconstruct_audit_request(ar["id"], AUDITOR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FAILED"
        assert data["failure_reason"], "failure_reason must be set on purged gap"
        assert data.get("reconstruction_log") is None
        assert data.get("reconstruction_digest") is None

    def test_reconstruction_without_purged_minutes_completes(self, api):
        """PRD §3.9: "Otherwise the request settles into the terminal
        `COMPLETED` state."

        Design: Corner/calculations/reconstruction_fails_on_purged_gap
        """
        # Setup minutes but do NOT purge them.
        corp, _bylaws, directors = setup_corporation_with_directors(
            1, name="Corp C4b", minute_retention_years=1
        )
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        set_clock("2026-06-20T11:00:00Z")
        convene_meeting(m["id"], d1["id"])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        mn = get_minutes_for_meeting(m["id"])
        api.circulate_minutes(mn["id"], {"content": "body"}, SECRETARY)
        api.approve_minutes(mn["id"], make_chair_headers(d1["id"]))
        api.enter_book_minutes(mn["id"], SECRETARY)
        ar_resp = api.create_audit_request(
            {
                "corporation_id": corp["id"],
                "requested_by_label": "Aud",
                "scope_start": "2026-01-01T00:00:00Z",
                "scope_end": "2026-12-31T23:59:59Z",
            },
            AUDITOR,
        )
        ar = get_success_data(ar_resp)
        resp = api.reconstruct_audit_request(ar["id"], AUDITOR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"


class TestGovernanceApprovalRatePerResolutionRounding:
    """Difficulty instance: governance_approval_rate_per_resolution_rounding.

    Three resolutions, eligible pool 3 for each:
      R1 2 FOR / 1 AGAINST (ADOPTED) -> 100*2/3 = 66.666.. -> round 66.7
      R2 2 FOR / 1 AGAINST (ADOPTED) -> 66.7
      R3 0 FOR / 3 AGAINST (REJECTED) -> 0.0
    Mean of (66.7, 66.7, 0.0) = 44.4666.. -> round 44.5.
    Pooled alternative (4/9 -> 44.4) is explicitly not used.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp G")
        d1, d2, d3 = directors
        # Meeting of 180 minutes, all 3 present, quorum = max(1, ceil(60*3/100)) = 2.
        from test_helpers import schedule_noticed_meeting

        m = schedule_noticed_meeting(
            corp["id"], d1["id"], meeting_type="ANNUAL", duration_minutes=180
        )
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        record_attendance(m["id"], d2["id"], "IN_PERSON")
        record_attendance(m["id"], d3["id"], "REMOTE")
        set_clock("2026-06-20T10:00:00Z")
        convene_meeting(m["id"], d1["id"])

        resolutions = []
        for title in ("R1", "R2", "R3"):
            r = create_meeting_resolution(corp["id"], m["id"], title=title, text=f"{title} text")
            resolutions.append(r)

        # R1: 2 FOR, 1 AGAINST -> ADOPTED
        table_resolution(resolutions[0]["id"])
        open_vote_as_chair(resolutions[0]["id"], d1["id"])
        cast_ballot(resolutions[0]["id"], d1["id"], "FOR")
        cast_ballot(resolutions[0]["id"], d2["id"], "FOR")
        cast_ballot(resolutions[0]["id"], d3["id"], "AGAINST")
        close_vote_as_chair(resolutions[0]["id"], d1["id"])

        # R2: 2 FOR, 1 AGAINST -> ADOPTED
        table_resolution(resolutions[1]["id"])
        open_vote_as_chair(resolutions[1]["id"], d1["id"])
        cast_ballot(resolutions[1]["id"], d1["id"], "FOR")
        cast_ballot(resolutions[1]["id"], d2["id"], "FOR")
        cast_ballot(resolutions[1]["id"], d3["id"], "AGAINST")
        close_vote_as_chair(resolutions[1]["id"], d1["id"])

        # R3: 0 FOR, 3 AGAINST -> REJECTED
        table_resolution(resolutions[2]["id"])
        open_vote_as_chair(resolutions[2]["id"], d1["id"])
        cast_ballot(resolutions[2]["id"], d1["id"], "AGAINST")
        cast_ballot(resolutions[2]["id"], d2["id"], "AGAINST")
        cast_ballot(resolutions[2]["id"], d3["id"], "AGAINST")
        close_vote_as_chair(resolutions[2]["id"], d1["id"])

        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        return corp, m, resolutions

    def test_per_resolution_rounding_then_mean(self, api):
        """PRD §3.9: "Each remaining resolution contributes the percentage of
        its `for_count` over its pool, rounded half up to one decimal place —
        the rounding happens per resolution, before any averaging. The
        reported rate is the arithmetic mean of those per-resolution
        percentages, itself rounded half up to one decimal place. A pooled
        alternative — summing all FOR tallies over the summed eligible pools
        — is deliberately not used."

        Design: Difficulty/combinatorial_formula/governance_approval_rate_per_resolution_rounding
        """
        corp, _m, _rs = self._setup(api)
        ar_resp = api.create_audit_request(
            {
                "corporation_id": corp["id"],
                "requested_by_label": "Ext Audit LLP",
                "scope_start": "2026-01-01T00:00:00Z",
                "scope_end": "2026-12-31T23:59:59Z",
            },
            AUDITOR,
        )
        ar = get_success_data(ar_resp)
        resp = api.reconstruct_audit_request(ar["id"], AUDITOR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"
        assert data["governance_approval_rate_pct"] == 44.5, (
            f"expected 44.5 (per-resolution round then mean), got {data['governance_approval_rate_pct']}"
        )

    def test_entry_count_includes_meeting_and_closed_resolutions(self, api):
        """PRD §3.9: "The sources are the corporation's meetings by their
        `created_at`, its resolutions in `ADOPTED` or `REJECTED` by their
        `closed_at`, and its approved minutes by their `approved_at` — each
        admitted when its relevant timestamp falls inside the inclusive scope
        window."

        Design: Difficulty/combinatorial_formula/governance_approval_rate_per_resolution_rounding
        """
        corp, _m, _rs = self._setup(api)
        ar_resp = api.create_audit_request(
            {
                "corporation_id": corp["id"],
                "requested_by_label": "Ext Audit LLP",
                "scope_start": "2026-01-01T00:00:00Z",
                "scope_end": "2026-12-31T23:59:59Z",
            },
            AUDITOR,
        )
        ar = get_success_data(ar_resp)
        resp = api.reconstruct_audit_request(ar["id"], AUDITOR)
        data = validate_success(resp, expected_status=200)
        # 1 meeting + 3 closed resolutions; minutes unapproved so excluded.
        assert data["entry_count"] == 4, f"expected 4 entries, got {data['entry_count']}"
