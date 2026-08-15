"""Docket sweep: clock-gated lapse and the lapse cascade (PRD §3.9, §2.4)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_client,
    create_contact,
    create_family,
    create_pending_application,
    create_granted_application,
    create_docket_entry_payload,
    create_office_action_payload,
    list_obligations,
    get_application,
    request_authorization,
    set_clock,
)

ANY = TEST_USERS["any_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestSweepClockGating:
    def test_sweep_before_deadline_lapses_nothing(self):
        """PRD §3.9: "Against the current logical clock it lapses every docket
        entry in `PENDING` or `IN_PROGRESS` whose `current_due_date` is before
        today"; PRD §2.4: "the word "today" means the calendar date, in UTC, of
        the logical clock at the moment the rule is evaluated."

        Design: Corner/cross_cutting_complexity_layers/sweep_noop_before_deadline_then_lapses
        """
        set_clock("2026-08-01T00:00:00Z")
        create_us_rule()
        client = create_client("SwpCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-S1")
        validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="bar",
                                                   base_due_date="2026-08-03"), CLERK), 201)
        set_clock("2026-08-02T00:00:00Z")
        # Due 2026-08-03 is not before 2026-08-02: nothing lapses.
        data = validate_success(api_client.run_docket_sweep(ADMIN), 201)
        assert data["entries_lapsed"] == 0
        assert data["applications_lapsed"] == 0

    def test_sweep_after_deadline_lapses_entry_and_statutory_cascades(self):
        """PRD §3.9: "A lapsed `STATUTORY` entry pulls its parent application
        from `PENDING` to `LAPSED`."

        Design: Corner/cross_cutting_complexity_layers/sweep_noop_before_deadline_then_lapses
        """
        set_clock("2026-08-01T00:00:00Z")
        create_us_rule()
        client = create_client("SwpCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-S1")
        entry = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="bar",
                                                   base_due_date="2026-08-03"), CLERK), 201)
        set_clock("2026-08-04T00:00:00Z")
        data = validate_success(api_client.run_docket_sweep(ADMIN), 201)
        assert data["entries_lapsed"] == 1
        assert data["applications_lapsed"] == 1
        assert validate_success(api_client.get_docket_entry(entry["id"], ANY), 200)["status"] == "LAPSED"
        assert get_application(app["id"])["status"] == "LAPSED"


class TestSweepLapseCascade:
    def _cascade_world(self):
        set_clock("2026-08-01T00:00:00Z")
        create_us_rule()
        client = create_client("CasCo")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=1000000)
        # A1 PENDING with a STATUTORY entry due 2026-08-03 and a RECORDATION
        # entry due 2026-12-01 (later in sweep order).
        a1 = create_pending_application(family["id"], application_number="US-C1")
        en_stat = validate_success(api_client.create_docket_entry(
            a1["id"], create_docket_entry_payload(entry_type="STATUTORY", title="bar",
                                                  base_due_date="2026-08-03"), CLERK), 201)
        en_rec = validate_success(api_client.create_docket_entry(
            a1["id"], create_docket_entry_payload(entry_type="RECORDATION", title="rec",
                                                  base_due_date="2026-12-01"), CLERK), 201)
        # A2 GRANTED with a y3 obligation (due 2028-09-01, window end
        # 2029-03-01) carrying a REQUESTED authorization.
        a2 = create_granted_application(family["id"], application_number="US-C2")
        obligation = list_obligations(a2["id"])[0]
        au, _ = request_authorization(obligation["id"], 10000)
        set_clock("2029-03-02T00:00:00Z")
        return {"a1": a1, "a2": a2, "en_stat": en_stat, "en_rec": en_rec,
                "obligation": obligation, "authorization": au}

    def test_sweep_reports_pinned_counts(self):
        """PRD §3.9: "The run reports `entries_lapsed`, `obligations_lapsed`,
        `applications_lapsed`, and `obligations_superseded_authorizations`" and
        "Cascade mutations take effect immediately, so an entry already
        cancelled by an application-lapse cascade before its turn arrives is
        skipped and counted as cancelled, not lapsed."

        Design: Corner/cross_cutting_complexity_layers/sweep_lapse_cascade_cancels_entries_and_obligations
        """
        ctx = self._cascade_world()
        data = validate_success(api_client.run_docket_sweep(ADMIN), 201)
        # Only the STATUTORY entry lapses; the later RECORDATION entry is
        # cancelled by the application-lapse cascade before its turn.
        assert data["entries_lapsed"] == 1
        # The y3 obligation is past its surcharge window end (2029-03-01).
        assert data["obligations_lapsed"] == 1
        # A1 lapses via its statutory entry; A2 lapses via its obligation.
        assert data["applications_lapsed"] == 2
        assert data["obligations_superseded_authorizations"] == 1

    def test_sweep_cascade_end_states(self):
        """PRD §3.9: "The sweep also lapses every annuity obligation in
        `SCHEDULED` or `PENDING_AUTHORIZATION` whose `surcharge_window_end` is
        before today — the latter superseding its `REQUESTED` authorization —
        and any `GRANTED` application that had an obligation lapse in this run
        becomes `LAPSED`, firing the full application-lapse cascade."

        Design: Corner/cross_cutting_complexity_layers/sweep_lapse_cascade_cancels_entries_and_obligations
        """
        ctx = self._cascade_world()
        validate_success(api_client.run_docket_sweep(ADMIN), 201)
        assert validate_success(api_client.get_docket_entry(ctx["en_stat"]["id"], ANY), 200)["status"] == "LAPSED"
        assert validate_success(api_client.get_docket_entry(ctx["en_rec"]["id"], ANY), 200)["status"] == "CANCELLED"
        assert validate_success(api_client.get_annuity_obligation(ctx["obligation"]["id"], ANY), 200)["status"] == "LAPSED"
        assert validate_success(api_client.get_authorization(ctx["authorization"]["id"], ANY), 200)["status"] == "SUPERSEDED"
        assert get_application(ctx["a2"]["id"])["status"] == "LAPSED"


class TestAuditWindowHalfOpenAdjacency:
    def _audit_world(self):
        create_us_rule()
        client = create_client("AudCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-A")
        a1 = validate_success(api_client.create_audit(
            app["id"],
            {"window_start": "2026-08-01", "window_end": "2026-08-10", "register_entries": []},
            CLERK), 201)
        assert a1["status"] == "OPEN"
        return app

    def test_adjacent_window_allowed(self):
        """PRD §3.9: "pure adjacency — the new `window_start` equalling an
        existing window's `window_end` — touches no shared date and is
        allowed."

        Design: Difficulty/resource_temporal_overlap/audit_windows_half_open_adjacency
        """
        app = self._audit_world()
        data = validate_success(api_client.create_audit(
            app["id"],
            {"window_start": "2026-08-10", "window_end": "2026-08-12", "register_entries": []},
            CLERK), 201)
        assert data["status"] == "OPEN"

    def test_intersecting_window_rejected(self):
        """PRD §3.9: "A new audit's window must not intersect the window of any
        non-terminal audit on the same application; intersection is rejected
        with `ERR_AUDIT_WINDOW_OVERLAP`, while pure adjacency — the new
        `window_start` equalling an existing window's `window_end` — touches no
        shared date and is allowed."

        Design: Difficulty/resource_temporal_overlap/audit_windows_half_open_adjacency
        """
        app = self._audit_world()
        validate_error(api_client.create_audit(
            app["id"],
            {"window_start": "2026-08-09", "window_end": "2026-08-11", "register_entries": []},
            CLERK), ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)


class TestAuditVarianceClassification:
    def test_three_variance_kinds_in_pinned_order(self):
        """PRD §3.9: "A register row with no exactly matching internal row
        produces a `DATE_MISMATCH` variance when an internal row of the same
        `entry_type` but a different due date exists — choosing the internal
        row with the smallest absolute difference in due dates and breaking
        remaining ties by the earliest entry `created_at` — carrying both
        `internal_due_date` and `register_due_date`; otherwise it produces a
        `MISSING_INTERNAL` variance carrying the `register_due_date`. After
        that matching pass, an internal row left without a register match
        produces a `MISSING_REGISTER` variance carrying the
        `internal_due_date`. The resulting `variances` list is sorted by entry
        type ascending and then by due date ascending, taking the internal due
        date when present and the register due date otherwise."

        Design: Corner/calculations/audit_variance_classification_and_order
        """
        create_us_rule()
        client = create_client("VarCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-V")
        # OA-response entry: internal due 2026-08-20 (mail 2026-05-20 + 3 months).
        validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(mail_date="2026-05-20"), CLERK), 201)
        # Manual RECORDATION entry due 2026-08-10.
        validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="RECORDATION", title="Rec",
                                                   base_due_date="2026-08-10"), CLERK), 201)
        audit = validate_success(api_client.create_audit(
            app["id"],
            {
                "window_start": "2026-08-01",
                "window_end": "2026-09-01",
                "register_entries": [
                    {"entry_type": "OFFICE_ACTION_RESPONSE", "due_date": "2026-08-25"},
                    {"entry_type": "STATUTORY", "due_date": "2026-08-15"},
                ],
            },
            CLERK), 201)
        assert audit["status"] == "VARIANCE_FOUND"
        kinds = [v["kind"] for v in audit["variances"]]
        # Sorted by entry_type ascending: OFFICE_ACTION_RESPONSE < RECORDATION < STATUTORY.
        assert kinds == ["DATE_MISMATCH", "MISSING_REGISTER", "MISSING_INTERNAL"]
        mismatch = audit["variances"][0]
        assert mismatch["internal_due_date"] == "2026-08-20"
        assert mismatch["register_due_date"] == "2026-08-25"
