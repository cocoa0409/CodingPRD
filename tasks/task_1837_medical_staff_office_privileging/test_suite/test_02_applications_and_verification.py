"""Application submission guards, verification workflow, waivers, and OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_verification_item,
    create_approved_member,
    create_application_payload,
    create_draft_application,
    create_member_record,
    create_submitted_application,
    file_npdb_report,
    get_success_data,
    parse_ts,
    receive_and_verify_item,
    receive_item,
    refresh_application,
    refresh_member,
    refresh_verification_item,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
    verify_item,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]


class TestSubmissionGuards:
    def test_submit_without_verification_items_rejected(self, api):
        """PRD §3.2: "The application must still be in `DRAFT`
        (`ERR_APPLICATION_NOT_IN_DRAFT`); at least one verification item must
        exist (`ERR_NO_VERIFICATION_ITEMS`)".

        Design: Corner/validations/submit_without_verification_items_rejected
        """
        member = create_member_record("Dr. NoVer", "NPDB-NV", "CARD")
        application = create_draft_application(member)

        resp = api.submit_application(application["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_VERIFICATION_ITEMS, 409)
        assert refresh_application(application["id"])["application_status"] == "DRAFT"

    def test_submit_from_submitted_is_invalid_state(self, api):
        """PRD §3.2: "The application must still be in `DRAFT`
        (`ERR_APPLICATION_NOT_IN_DRAFT`)".

        Design: Corner/state_machines/submit_from_submitted_is_invalid_state
        """
        ws = create_submitted_application("Dr. SS", "NPDB-SS",
                                          with_delineation=False)
        first = refresh_application(ws["application"]["id"])
        assert first["application_status"] == "SUBMITTED"

        resp = api.submit_application(ws["application"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_IN_DRAFT, 409)

        after = refresh_application(ws["application"]["id"])
        assert after["application_status"] == "SUBMITTED"
        assert after["submitted_at"] == first["submitted_at"], (
            "A rejected re-submission must not re-stamp submitted_at")


class TestVerificationWorkflow:
    def test_verification_item_discrepancy_cycle_allows_rereceipt(self, api):
        """PRD §3.2: "the same action also re-receives an item from `DISCREPANCY`
        after clarification, so the `RECEIVED` ↔ `DISCREPANCY` cycle is permitted
        — any other source state is rejected with `ERR_VERIFICATION_NOT_REQUESTED`."
        PRD §3.2: "while any item sits in `DISCREPANCY` the application is blocked
        from reaching `PSV_COMPLETE`."

        Design: Corner/state_machines/verification_item_discrepancy_cycle_allows_rereceipt
        """
        ws = create_submitted_application("Dr. Disc", "NPDB-DISC",
                                          item_kind="MEDICAL_SCHOOL",
                                          is_primary_source=True,
                                          with_delineation=False)
        item_id = ws["item"]["id"]

        receive_item(item_id)
        assert refresh_verification_item(item_id)["item_status"] == "RECEIVED"

        get_success_data(api.flag_verification_item_discrepancy(
            item_id, "school name mismatch vs diploma", COORD))
        flagged = refresh_verification_item(item_id)
        assert flagged["item_status"] == "DISCREPANCY"
        app_mid = refresh_application(ws["application"]["id"])
        assert app_mid["application_status"] == "PSV_IN_PROGRESS", (
            "A DISCREPANCY item blocks the application from PSV_COMPLETE")

        receive_item(item_id)
        assert refresh_verification_item(item_id)["item_status"] == "RECEIVED", (
            "mark-received re-receives an item from DISCREPANCY")

        verify_item(item_id)
        assert refresh_verification_item(item_id)["item_status"] == "VERIFIED"
        assert refresh_application(
            ws["application"]["id"])["application_status"] == "PSV_COMPLETE"

    def test_waived_items_excluded_from_required_count(self, api):
        """PRD §3.2: "Waived items are excluded from
        `verification_required_count`, which is recomputed on every waiver."
        PRD §3.2: "the moment that count reaches `verification_required_count`
        with no item remaining in `PENDING`, `REQUESTED`, `RECEIVED`, or
        `DISCREPANCY`, the application advances automatically from
        `PSV_IN_PROGRESS` to `PSV_COMPLETE`, ready for committee advancement."

        Design: Corner/calculations/waived_items_excluded_from_required_count
        """
        member = create_member_record("Dr. Waive", "NPDB-WV", "CARD")
        application = create_draft_application(member)
        primary_item = add_verification_item(application["id"], "MEDICAL_SCHOOL",
                                             True)
        reference_item = add_verification_item(application["id"], "REFERENCES",
                                               False)
        submit_application(application["id"])

        waived = get_success_data(api.waive_verification_item(
            reference_item["id"],
            "reference unresponsive after three documented attempts", CHAIR))
        assert waived["item_status"] == "WAIVED"

        receive_and_verify_item(primary_item["id"])

        app = refresh_application(application["id"])
        assert app["verification_required_count"] == 1, (
            "The waived REFERENCES item is excluded from the required count")
        assert app["verification_complete_count"] == 1
        assert app["application_status"] == "PSV_COMPLETE"

    def test_npdb_verify_gate_requires_filed_query(self, api):
        """PRD §3.2: "an item whose `item_kind` is `NPDB_QUERY` may be verified
        only when a filed NPDB report exists for the member whose `report_kind`
        matches the application — `QUERY_INITIAL` for an `INITIAL` application,
        `QUERY_REAPPOINTMENT` for a `REAPPOINTMENT` application — with
        `report_status` in `SUBMITTED` or `ACKNOWLEDGED`; without it, verification
        is rejected with `ERR_NPDB_QUERY_MISSING`."

        Design: Corner/validations/npdb_verify_gate_requires_filed_query
        """
        ws = create_submitted_application("Dr. NoQ", "NPDB-NQ",
                                          item_kind="NPDB_QUERY",
                                          is_primary_source=True,
                                          with_delineation=False)
        item_id = ws["item"]["id"]
        receive_item(item_id)

        resp = api.verify_verification_item(item_id, COORD)
        validate_error(resp, ApiErrorId.ERR_NPDB_QUERY_MISSING, 409)
        assert refresh_verification_item(item_id)["item_status"] == "RECEIVED"

    def test_advance_to_committee_with_unevaluated_delineation_rejected(self, api):
        """PRD §3.4: "every delineation riding on it must already sit in
        `CRITERIA_MET` or `CRITERIA_UNMET` — an unevaluated delineation blocks
        the move with `ERR_DELINEATIONS_UNEVALUATED`."

        Design: Corner/validations/advance_to_committee_with_unevaluated_delineation_rejected
        """
        ws = create_submitted_application("Dr. UnEv", "NPDB-UE")
        receive_and_verify_item(ws["item"]["id"])
        app = refresh_application(ws["application"]["id"])
        assert app["application_status"] == "PSV_COMPLETE"

        resp = api.advance_application_to_committee(app["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_DELINEATIONS_UNEVALUATED, 409)
        assert refresh_application(
            app["id"])["application_status"] == "PSV_COMPLETE"


class TestWaiverSafetyAndPriority:
    def _verified_primary_npdb_item(self):
        """NPDB_QUERY primary-source item driven to VERIFIED (a QUERY_INITIAL
        report is filed first to satisfy the NPDB query gate)."""
        ws = create_submitted_application("Dr. W", "NPDB-W1",
                                          item_kind="NPDB_QUERY",
                                          is_primary_source=True,
                                          with_delineation=False)
        item_id = ws["item"]["id"]
        receive_item(item_id)
        file_npdb_report(ws["member"]["id"], "QUERY_INITIAL")
        verify_item(item_id)
        return ws, item_id

    def test_waive_verified_primary_npdb_item_reports_state_error(self, api):
        """PRD §3.2: "An item in `REQUESTED` or `RECEIVED` may be waived — any
        other state is rejected with `ERR_VERIFICATION_NOT_WAIVABLE`".
        PRD §2.9: "Every request is validated against a fixed priority ladder,
        and a request that fails an earlier rung is never evaluated against a
        later one — the first failing rung determines the error returned."
        Waiving a VERIFIED primary-source NPDB item violates both state legality
        (rung 5) and the primary-source safety gate (rung 7); the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_waive
        """
        _ws, item_id = self._verified_primary_npdb_item()
        assert refresh_verification_item(item_id)["item_status"] == "VERIFIED"

        resp = api.waive_verification_item(
            item_id, "attempting to waive a verified primary source item", CHAIR)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_WAIVABLE, 409)
        assert refresh_verification_item(item_id)["item_status"] == "VERIFIED", (
            "A rejected waiver must leave the item untouched")

    def test_waive_requested_primary_npdb_item_hits_safety_gate(self, api):
        """PRD §3.2: "One safety gate is absolute: an item that is both
        primary-source (`is_primary_source` true) and of `item_kind` `NPDB_QUERY`
        cannot be waived at all, and the attempt is rejected with
        `ERR_PRIMARY_SOURCE_NOT_WAIVABLE` (403)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_waive
        """
        ws = create_submitted_application("Dr. W2", "NPDB-W2",
                                          item_kind="NPDB_QUERY",
                                          is_primary_source=True,
                                          with_delineation=False)
        item_id = ws["item"]["id"]
        assert refresh_verification_item(item_id)["item_status"] == "REQUESTED"

        resp = api.waive_verification_item(
            item_id, "waiving a primary source npdb query is forbidden", CHAIR)
        validate_error(resp, ApiErrorId.ERR_PRIMARY_SOURCE_NOT_WAIVABLE, 403)
        assert refresh_verification_item(item_id)["item_status"] == "REQUESTED"


class TestApplicationOcc:
    def test_occ_application_create_stale_member_version(self, api):
        """PRD §2.7: "If the member's current `version` has advanced beyond that
        value — because another writer has just submitted a superseding
        application, or because the member's term has been ratified forward —
        the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting
        the client from filing against a member snapshot it has not observed."
        PRD §3.1: "Creating the application increments the member's `version` by
        one — a supersede marker that makes any concurrent writer's stale member
        snapshot detectable."

        Design: Corner/cross_cutting_layers/occ_application_create_stale_member_version
        """
        member = create_member_record("Dr. OCC", "NPDB-OCC", "CARD")
        v0 = member["version"]

        first = validate_success(
            api.create_application(
                create_application_payload(member["id"], v0), COORD), 201)

        stale = api.create_application(
            create_application_payload(member["id"], v0), COORD)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh_version = refresh_member(member["id"])["version"]
        retry = validate_success(
            api.create_application(
                create_application_payload(
                    member["id"], fresh_version,
                    supersedes_application_id=first["id"]),
                COORD), 201)
        assert retry["id"] != first["id"]
        assert refresh_member(member["id"])["version"] == v0 + 2, (
            "Each successful application create increments member.version by one")


class TestTerminalApplication:
    def test_terminal_application_lockdown_withdraw_from_approved(self, api):
        """PRD §3.2: "a coordinator may withdraw an application from `DRAFT`,
        `SUBMITTED`, or `PSV_IN_PROGRESS` — attempting it from `COMMITTEE_REVIEW`
        or later is rejected with `ERR_APPLICATION_NOT_WITHDRAWABLE`."

        Design: Corner/state_machines/terminal_application_lockdown_withdraw_from_approved
        """
        ws = create_approved_member("Dr. Term", "NPDB-TERM")
        assert ws["application"]["application_status"] == "APPROVED"

        resp = api.withdraw_application(ws["application"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_WITHDRAWABLE, 409)
        assert refresh_application(
            ws["application"]["id"])["application_status"] == "APPROVED"


class TestReappointmentWindowBoundary:
    def _member_with_term(self):
        """Member ratified at the 2026-08-01 startup clock; the two-year term
        runs [2026-08-01, 2028-08-01)."""
        ws = create_approved_member("Dr. RW", "NPDB-RW1")
        assert ws["member"]["membership_status"] == "ACTIVE"
        return ws

    def test_reappointment_submit_at_window_opening_succeeds(self, api):
        """PRD §3.4: "A `REAPPOINTMENT` application may be submitted only inside
        the half-open window that opens exactly 180 days before the member's
        `current_term_end` and closes at `current_term_end`: submission at the
        opening instant is inside the window, while submission exactly at
        `current_term_end` is outside it — too late — and is rejected with
        `ERR_OUTSIDE_REAPPOINTMENT_WINDOW`."
        PRD §3.4: "the member's `current_term_start` is stamped with the
        ratification instant and `current_term_end` is recomputed by calendar
        arithmetic as exactly two years later, in UTC — the term is always two
        calendar years."

        2028-02-03 is exactly 180 days before the 2028-08-01 term end.

        Design: Difficulty/resource_temporal_overlap/reappointment_window_half_open_boundary
        """
        ws = self._member_with_term()
        set_clock("2028-02-03T00:00:00Z")

        member = refresh_member(ws["member"]["id"])
        assert parse_ts(member["current_term_end"]) == parse_ts(
            "2028-08-01T00:00:00Z")

        application = create_draft_application(
            member, application_kind="REAPPOINTMENT")
        add_verification_item(application["id"])
        submitted = submit_application(application["id"])
        assert submitted["application_status"] == "SUBMITTED", (
            "Submission at exactly term_end - 180 days is inside the window")

    def test_reappointment_submit_at_term_end_rejected(self, api):
        """PRD §3.4: "submission exactly at `current_term_end` is outside it —
        too late — and is rejected with `ERR_OUTSIDE_REAPPOINTMENT_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/reappointment_window_half_open_boundary
        """
        ws = self._member_with_term()
        set_clock("2028-08-01T00:00:00Z")

        member = refresh_member(ws["member"]["id"])
        application = create_draft_application(
            member, application_kind="REAPPOINTMENT")
        add_verification_item(application["id"])

        resp = api.submit_application(application["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_REAPPOINTMENT_WINDOW, 409)
