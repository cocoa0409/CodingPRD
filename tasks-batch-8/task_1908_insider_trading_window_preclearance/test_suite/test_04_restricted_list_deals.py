"""Restricted list maintenance, deal activation/close cascades, entry conservation."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_officer,
    assert_same_instant,
    activate_deal,
    close_deal,
    create_current_person,
    create_deal,
    create_manual_restricted_entry,
    create_officer,
    create_person,
    create_submitted_request,
    get_success_data,
    ingest_confirmation,
    list_active_entries_for_ticker,
    set_logical_clock,
    validate_error,
    validate_success,
)


class TestManualRestrictedEntries:
    def test_manual_restricted_entry_created_with_defaults(self, api):
        """PRD §3.3: "An officer adds a ticker with a `security_ticker` and an
        optional free-text `note`, producing an `ACTIVE` entry whose `source` is
        `MANUAL`."

        Design: Corner/entities/restricted_entry_manual_create_defaults
        """
        officer = create_officer("officer_c1@x.com")
        resp = api.create_restricted_list_entry(
            {"security_ticker": "DELTA"}, as_officer(officer)
        )
        data = validate_success(resp, expected_status=201)
        assert data["source"] == "MANUAL"
        assert data["status"] == "ACTIVE"
        assert data["deal_id"] is None

    def test_duplicate_manual_restricted_entry_rejected(self, api):
        """PRD §3.3: "Manual creation is the one place a duplicate is blocked: if any
        entry for that ticker is already `ACTIVE` — regardless of its source —
        creation is rejected with `ERR_DUPLICATE_RESTRICTED_ENTRY` (409)."

        Design: Corner/errors/manual_duplicate_restricted_entry_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_e2@x.com")
        create_manual_restricted_entry(officer, "ACME", note="first")
        resp = api.create_restricted_list_entry(
            {"security_ticker": "ACME", "note": "second"}, as_officer(officer)
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESTRICTED_ENTRY)
        active = list_active_entries_for_ticker(officer, "ACME")
        assert len(active) == 1, f"expected exactly 1 ACTIVE entry, got {len(active)}"

    def test_confirmation_on_restricted_ticker_flagged_restricted_list(self, api):
        """PRD §3.7: "If an `ACTIVE` blackout window applicable to the ticker covers
        the `trade_date`, `flagged_reason` is `BLACKOUT_TRADE`; otherwise, if an
        `ACTIVE` restricted-list entry matches the ticker, `flagged_reason` is
        `RESTRICTED_LIST`; otherwise it is `NO_PRECLEARANCE`."

        Design: Corner/errors/flagged_confirmation_reason_restricted_list
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_e4@x.com")
        subject = create_person("Subject E4", "subject_e4@x.com")
        create_manual_restricted_entry(officer, "ACME")

        conf = ingest_confirmation(
            officer, subject, ticker="ACME", side="BUY", quantity=10, price=10.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-C-E4",
        )
        assert conf["status"] == "FLAGGED"
        assert conf["flagged_reason"] == "RESTRICTED_LIST"


class TestDealActivationCascade:
    def test_deal_activation_creates_entry_and_event_window(self, api):
        """PRD §3.3: "Moving a deal from `INTAKE` to `ACTIVE` stamps `activated_at`,
        increments the deal's `version`, and then, in the same transaction: first, a
        `RestrictedListEntry` is always created for the deal's ticker with `source`
        `DEAL_INTAKE`, a `deal_id` back-reference, and `status` `ACTIVE` — this happens
        even when a `MANUAL` entry for the same ticker is already active, because
        multiple active entries per ticker are permitted across different sources;
        second, if the deal carries an `event_blackout_start`, an `EVENT_DRIVEN`
        blackout window is created over that interval for the deal's ticker with the
        same `deal_id` back-reference, subject to the merge rule of §3.2".

        Design: Difficulty/transitive_cascade/deal_activate_to_entry_to_auto_deny
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer8@x.com")
        deal = create_deal(
            officer, "PROJECTFALCON", "ACME",
            event_blackout_start="2026-08-03T00:00:00Z",
            event_blackout_end="2026-08-07T00:00:00Z",
        )
        activated = activate_deal(officer, deal["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["activated_at"] is not None

        entries = get_success_data(
            api.list_deal_restricted_list_entries(deal["id"], as_officer(officer))
        )
        assert len(entries) == 1, f"expected exactly 1 deal-sourced entry, got {len(entries)}"
        assert entries[0]["source"] == "DEAL_INTAKE"
        assert entries[0]["status"] == "ACTIVE"
        assert entries[0]["security_ticker"] == "ACME"

        windows = get_success_data(
            api.list_blackout_windows(as_officer(officer), params={"deal_id": deal["id"]})
        )
        assert len(windows) == 1
        win = windows[0]
        assert win["kind"] == "EVENT_DRIVEN"
        assert win["status"] == "SCHEDULED"
        assert win["deal_id"] == deal["id"]
        assert_same_instant(win["start_at"], "2026-08-03T00:00:00Z", "window start_at")
        assert_same_instant(win["end_at"], "2026-08-07T00:00:00Z", "window end_at")

    def test_deal_activation_auto_denies_pending_requests(self, api):
        """PRD §3.3: "third, every preclearance request on that ticker sitting in
        `SUBMITTED` or `UNDER_REVIEW` is automatically denied, with `denial_reason`
        set to `RESTRICTED_LIST`."

        Design: Difficulty/transitive_cascade/deal_activate_to_entry_to_auto_deny
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer8b@x.com")
        insider = create_current_person("Insider G", "insider_g@x.com")
        req = create_submitted_request(
            insider, ticker="ACME", side="BUY", quantity=50,
            proposed_trade_date="2026-08-05T00:00:00Z",
        )
        deal = create_deal(
            officer, "PROJECTFALCON2", "ACME",
            event_blackout_start="2026-08-03T00:00:00Z",
            event_blackout_end="2026-08-07T00:00:00Z",
        )
        activate_deal(officer, deal["id"])

        fresh = get_success_data(api.get_preclearance_request(req["id"], admin_headers()))
        assert fresh["status"] == "DENIED"
        assert fresh["denial_reason"] == "RESTRICTED_LIST"


class TestDealCloseAbandoned:
    def test_abandoned_deal_cancels_window_and_removes_entry(self, api):
        """PRD §3.3: "Closing as `ABANDONED` moves the deal to `ABANDONED`: the same
        restricted-entry removal applies, but every deal-sourced window in either
        `SCHEDULED` or `ACTIVE` is cancelled — an abandoned deal lifts nothing."
        PRD §3.3: "deal-sourced restricted entries that are still `ACTIVE` are removed
        with `removed_reason` `DEAL_CLOSED`".

        Design: Corner/state_machines/deal_close_abandoned_cancels_scheduled_window
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_s5@x.com")
        deal = create_deal(
            officer, "PROJECTGAMMA", "GAMMA", deal_type="DIVESTITURE",
            event_blackout_start="2026-08-10T00:00:00Z",
            event_blackout_end="2026-08-14T00:00:00Z",
        )
        activate_deal(officer, deal["id"])
        entries = get_success_data(
            api.list_deal_restricted_list_entries(deal["id"], as_officer(officer))
        )
        windows = get_success_data(
            api.list_blackout_windows(as_officer(officer), params={"deal_id": deal["id"]})
        )
        entry_id, win_id = entries[0]["id"], windows[0]["id"]

        closed = close_deal(officer, deal["id"], "ABANDONED")
        assert closed["status"] == "ABANDONED"

        entry_data = get_success_data(
            api.list_deal_restricted_list_entries(deal["id"], as_officer(officer))
        )[0]
        assert entry_data["status"] == "REMOVED"
        assert entry_data["removed_reason"] == "DEAL_CLOSED"
        win = get_success_data(api.get_blackout_window(win_id, as_officer(officer)))
        assert win["status"] == "CANCELLED"


class TestRestrictedEntryConservation:
    def test_deal_activation_adds_entry_alongside_manual(self, api):
        """PRD §3.3: "a `RestrictedListEntry` is always created for the deal's ticker
        with `source` `DEAL_INTAKE`, a `deal_id` back-reference, and `status` `ACTIVE`
        — this happens even when a `MANUAL` entry for the same ticker is already
        active, because multiple active entries per ticker are permitted across
        different sources".

        Design: Difficulty/compensating_invariant/restricted_entry_count_conserved_through_deal_cycle
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer17@x.com")
        create_manual_restricted_entry(officer, "ACME", note="standing restriction")
        deal = create_deal(officer, "PROJECTORCA", "ACME", deal_type="ACQUISITION")

        before = list_active_entries_for_ticker(officer, "ACME")
        assert len(before) == 1
        activate_deal(officer, deal["id"])
        after = list_active_entries_for_ticker(officer, "ACME")
        assert len(after) == 2, f"MANUAL + DEAL_INTAKE entries expected, got {len(after)}"
        sources = sorted(e["source"] for e in after)
        assert sources == ["DEAL_INTAKE", "MANUAL"]

    def test_deal_close_removes_only_deal_sourced_entry(self, api):
        """PRD §3.3: "Closing as `COMPLETED` moves the deal from `ACTIVE` to `CLOSED`:
        deal-sourced restricted entries that are still `ACTIVE` are removed with
        `removed_reason` `DEAL_CLOSED`".

        Design: Difficulty/compensating_invariant/restricted_entry_count_conserved_through_deal_cycle
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer17b@x.com")
        manual = create_manual_restricted_entry(officer, "ACME", note="standing restriction")
        deal = create_deal(officer, "PROJECTORCA2", "ACME", deal_type="ACQUISITION")
        activate_deal(officer, deal["id"])
        assert len(list_active_entries_for_ticker(officer, "ACME")) == 2

        close_deal(officer, deal["id"], "COMPLETED")
        remaining = list_active_entries_for_ticker(officer, "ACME")
        assert len(remaining) == 1
        assert remaining[0]["id"] == manual["id"]
        assert remaining[0]["status"] == "ACTIVE"

        deal_entries = get_success_data(
            api.list_deal_restricted_list_entries(deal["id"], as_officer(officer))
        )
        assert deal_entries[0]["status"] == "REMOVED"
        assert deal_entries[0]["removed_reason"] == "DEAL_CLOSED"
