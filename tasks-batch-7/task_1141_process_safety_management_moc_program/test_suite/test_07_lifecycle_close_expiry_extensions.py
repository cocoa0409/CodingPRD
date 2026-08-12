"""Life in service: closure gates, temporary expiry sweep, extension control."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_extension_request_payload,
    create_standard_actors,
    drive_moc_to_closed,
    drive_moc_to_in_service,
    get_moc,
    get_unit,
    list_extension_requests,
    list_unit_action_items,
    make_requester_headers,
    moc_version,
    new_manual_item,
    set_clock,
    setup_in_service_scenario,
    setup_unit_with_study,
    validate_error,
    validate_success,
    verify_item,
    work_item_to_submitted,
)

MANAGER = TEST_USERS["manager_headers"]


def _revert_item_of(unit_id):
    items = list_unit_action_items(unit_id)
    reverts = [i for i in items if i["source_type"] == "REVERT"]
    assert len(reverts) == 1, f"Expected exactly one REVERT item, got {len(reverts)}"
    return reverts[0]


class TestTerminalLockdown:
    def test_moc_terminal_lockdown_authorize_after_close_rejected(self, api):
        """PRD §3.6: "A `PsmManager` may close a `PERMANENT` or
        `REPLACEMENT_IN_KIND` MOC from `IN_SERVICE`, provided no open-class action
        item with `source_type` `MOC_CONDITION` remains sourced to it
        (`ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE`); closure stamps `closed_at` and
        lands in `CLOSED`."
        PRD §3.5: "Startup authorization itself is a `PsmManager` act on a MOC in
        `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE`)" — CLOSED is
        terminal, so authorize after close is a state error.

        Design: Corner/state_machines/moc_terminal_lockdown_authorize_after_close_rejected
        """
        unit, study = setup_unit_with_study()
        actors = create_standard_actors()
        moc = drive_moc_to_closed(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                  actors["app"]["id"], actors["lead"]["id"],
                                  change_class="PERMANENT")
        assert moc["status"] == "CLOSED"
        assert moc["closed_at"] == "2026-05-01T00:00:00Z"

        resp = api.authorize_startup(moc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOC_INVALID_STATE.value)
        assert get_moc(moc["id"])["status"] == "CLOSED"


class TestTemporaryExpiry:
    def test_temp_moc_revert_verify_closes_moc(self, api):
        """PRD §3.6: "When that revert item is later verified closed, the MOC
        bubbles up from `EXPIRED_REVERT_REQUIRED` to `CLOSED` with `closed_at`
        stamped — no separate MOC-level call is needed."

        Design: Corner/state_machines/temp_moc_revert_verify_closes_moc
        """
        unit, study, actors, moc = setup_in_service_scenario(
            change_class="TEMPORARY", severity=1, likelihood=1,
            temporary_start_date="2026-05-01", temporary_duration_days=5)
        set_clock("2026-05-07T00:00:00Z")
        assert get_moc(moc["id"])["status"] == "EXPIRED_REVERT_REQUIRED"
        revert = _revert_item_of(unit["id"])

        work_item_to_submitted(revert["id"], actors["req"]["id"], file_ref="s3://ev/revert.pdf")
        verified = verify_item(revert["id"])
        assert verified["source_type"] == "REVERT"
        assert verified["status"] == "VERIFIED_CLOSED"

        closed = get_moc(moc["id"])
        assert closed["status"] == "CLOSED", "verifying the REVERT item must close the expired MOC"
        assert closed["closed_at"] == "2026-05-07T00:00:00Z"
        assert get_unit(unit["id"])["open_action_count"] == 0

    def test_clock_expiry_spawns_revert_item(self, api):
        """PRD §3.6: "When the logical clock advances strictly beyond a temporary
        in-service MOC's `temporary_end_date` — a MOC whose end date is exactly
        today is not yet expired — the sweep moves it from `IN_SERVICE` to
        `EXPIRED_REVERT_REQUIRED`, spawns a revert action item with `source_type`
        `REVERT` sourced to the MOC, priority `P1`, assigned to the MOC's
        `requester_id`, due thirty days after the clock date, and the unit's
        `open_action_count` and index are updated accordingly."

        Design: Difficulty/transitive_cascade/clock_expiry_revert_cascade
        """
        unit, study, actors, moc = setup_in_service_scenario(
            change_class="TEMPORARY", severity=1, likelihood=1,
            temporary_start_date="2026-05-01", temporary_duration_days=5)
        new_manual_item(unit["id"], actors["req"]["id"], priority="P1", due_in_days=1, title="m1")
        new_manual_item(unit["id"], actors["req"]["id"], priority="P1", due_in_days=1, title="m2")
        set_clock("2026-05-03T00:00:00Z")

        set_clock("2026-05-07T00:00:00Z")  # strictly past end 2026-05-06
        expired = get_moc(moc["id"])
        assert expired["status"] == "EXPIRED_REVERT_REQUIRED"
        assert expired["temporary_end_date"] == "2026-05-06T00:00:00Z"

        revert = _revert_item_of(unit["id"])
        assert revert["priority"] == "P1"
        assert revert["assignee_id"] == actors["req"]["id"]
        assert revert["source_id"] == moc["id"]
        assert revert["status"] == "OPEN"
        assert revert["due_date"] == "2026-06-06T00:00:00Z", (
            f"revert item is due thirty days after the sweep clock, got {revert['due_date']}"
        )
        assert get_unit(unit["id"])["open_action_count"] == 3

    def test_expired_revert_overdue_lifts_posture(self, api):
        """PRD §3.6 (the spawned revert item is "due thirty days after the clock
        date") plus PRD §2.10: "fifteen points per overdue open action item" and
        "an index of at least 40 but below 70 is `RESTRICTED`" — once the revert
        item itself falls overdue, three overdue P1 items lift the index to 45.

        Design: Difficulty/transitive_cascade/clock_expiry_revert_cascade
        """
        unit, study, actors, moc = setup_in_service_scenario(
            change_class="TEMPORARY", severity=1, likelihood=1,
            temporary_start_date="2026-05-01", temporary_duration_days=5)
        new_manual_item(unit["id"], actors["req"]["id"], priority="P1", due_in_days=1, title="m1")
        new_manual_item(unit["id"], actors["req"]["id"], priority="P1", due_in_days=1, title="m2")
        set_clock("2026-05-03T00:00:00Z")
        set_clock("2026-05-07T00:00:00Z")

        set_clock("2026-06-07T00:00:00Z")  # revert item (due 2026-06-06) now overdue
        unit_after = get_unit(unit["id"])
        assert unit_after["overdue_action_count"] == 3
        assert unit_after["process_safety_index"] == 45, (
            f"3 overdue P1 items must yield 45, got {unit_after['process_safety_index']}"
        )
        assert unit_after["psm_posture"] == "RESTRICTED"
        assert get_moc(moc["id"])["status"] == "EXPIRED_REVERT_REQUIRED"


class TestExtensionCaps:
    def _temp_moc_in_service(self, **unit_overrides):
        unit, study = setup_unit_with_study(**unit_overrides)
        actors = create_standard_actors()
        moc = drive_moc_to_in_service(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                      actors["app"]["id"], actors["lead"]["id"],
                                      change_class="TEMPORARY", severity=1, likelihood=1,
                                      temporary_start_date="2026-05-01",
                                      temporary_duration_days=180)
        return unit, actors, moc

    def test_extension_count_boundary_allows_second(self, api):
        """PRD §3.6: "Approval adds `requested_days` to
        `total_approved_extension_days`, pushes `temporary_end_date` out by the
        same number of days, increments `extension_count` by one" — with the
        default `max_extensions` of 2 (PRD §3.1), the second extension still
        succeeds: end 2026-10-28 → +60 → 2026-12-27 → +60 → 2027-02-25.

        Design: Difficulty/boundary_precision_check/extension_count_cap_boundary
        """
        unit, actors, moc = self._temp_moc_in_service()
        req_id = actors["req"]["id"]

        e1 = validate_success(api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=60),
            make_requester_headers(req_id)), 201)
        validate_success(api.approve_extension(e1["id"], MANAGER), 200)
        after_first = get_moc(moc["id"])
        assert after_first["temporary_end_date"] == "2026-12-27T00:00:00Z"
        assert after_first["extension_count"] == 1
        assert after_first["total_approved_extension_days"] == 60

        e2 = validate_success(api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=60),
            make_requester_headers(req_id)), 201)
        validate_success(api.approve_extension(e2["id"], MANAGER), 200)
        after_second = get_moc(moc["id"])
        assert after_second["temporary_end_date"] == "2027-02-25T00:00:00Z"
        assert after_second["extension_count"] == 2, "the 2nd extension succeeds — cap is inclusive"
        assert after_second["total_approved_extension_days"] == 120

    def test_extension_count_cap_rejects_third(self, api):
        """PRD §3.6: "Three caps guard creation and are evaluated in a pinned
        order: first the count — if the MOC's `extension_count` has already
        reached the unit's `max_extensions`, the rejection is
        `ERR_MAX_EXTENSIONS_REACHED`" — the third request (30 days, which would
        pass both day caps: candidate 2027-03-27 within the 2027-04-26 lifetime
        cap) is rejected on count alone.

        Design: Difficulty/boundary_precision_check/extension_count_cap_boundary
        """
        unit, actors, moc = self._temp_moc_in_service()
        req_id = actors["req"]["id"]
        for days in (60, 60):
            ext = validate_success(api.create_extension_request(
                moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=days),
                make_requester_headers(req_id)), 201)
            validate_success(api.approve_extension(ext["id"], MANAGER), 200)

        resp = api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=30),
            make_requester_headers(req_id))
        validate_error(resp, ApiErrorId.ERR_MAX_EXTENSIONS_REACHED.value)
        assert get_moc(moc["id"])["extension_count"] == 2

    def test_extension_denial_leaves_dates_unchanged(self, api):
        """PRD §3.6: "Denial lands in `DENIED` and changes none of the MOC's dates
        or counts — the extension budget is left exactly as it was, a deliberate
        compensating invariant."

        Design: Corner/calculations/extension_denial_leaves_dates_unchanged
        """
        unit, actors, moc = self._temp_moc_in_service()
        req_id = actors["req"]["id"]
        ext = validate_success(api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=60),
            make_requester_headers(req_id)), 201)

        denied = validate_success(api.deny_extension(ext["id"], MANAGER), 200)
        assert denied["status"] == "DENIED"
        after = get_moc(moc["id"])
        assert after["temporary_end_date"] == "2026-10-28T00:00:00Z"
        assert after["extension_count"] == 0
        assert after["total_approved_extension_days"] == 0

    def test_extension_day_cap_and_total_cap_violations(self, api):
        """PRD §3.6: "second the per-extension size — `requested_days` (at least
        1) must not exceed the unit's `extension_max_days`, else
        `ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS`; third the lifetime cap — the
        candidate end date (the current `temporary_end_date` plus
        `requested_days`) must not fall beyond `temporary_start_date` plus the
        unit's `total_temp_cap_days`, else `ERR_TEMP_TOTAL_CAP_EXCEEDED`."
        Case 1: 91 > the 90-day default per-extension cap. Case 2: on a 200-day
        lifetime cap unit, a 30-day request whose candidate end 2026-11-27 falls
        beyond 2026-05-01 + 200 = 2026-11-17.

        Design: Corner/validations/extension_day_cap_and_total_cap_violations
        """
        unit1, actors, moc1 = self._temp_moc_in_service()
        req_id = actors["req"]["id"]
        resp1 = api.create_extension_request(
            moc1["id"], create_extension_request_payload(moc_version(moc1["id"]), requested_days=91),
            make_requester_headers(req_id))
        validate_error(resp1, ApiErrorId.ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS.value)

        unit2, actors2, moc2 = self._temp_moc_in_service(total_temp_cap_days=200)
        req2 = actors2["req"]["id"]
        resp2 = api.create_extension_request(
            moc2["id"], create_extension_request_payload(moc_version(moc2["id"]), requested_days=30),
            make_requester_headers(req2))
        validate_error(resp2, ApiErrorId.ERR_TEMP_TOTAL_CAP_EXCEEDED.value)
        after = get_moc(moc2["id"])
        assert after["extension_count"] == 0
        assert after["temporary_end_date"] == "2026-10-28T00:00:00Z"

    def test_extension_on_permanent_moc_rejected(self, api):
        """PRD §3.6: "Extensions are a temporary-only construct — requesting one
        on a non-`TEMPORARY` MOC is rejected with `ERR_MOC_NOT_TEMPORARY`" — even
        though the PERMANENT MOC here stands IN_SERVICE.

        Design: Corner/validations/extension_on_permanent_moc_rejected
        """
        unit, study, actors, moc = setup_in_service_scenario(change_class="PERMANENT")
        req_id = actors["req"]["id"]
        resp = api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=30),
            make_requester_headers(req_id))
        validate_error(resp, ApiErrorId.ERR_MOC_NOT_TEMPORARY.value)
        assert resp.status_code == 422
        assert list_extension_requests(moc["id"]) == []

    def test_occ_extension_supersede_and_stale_version(self, api):
        """PRD §3.6: "Creation supersedes any existing `PENDING` extension on the
        same MOC, moving the older one to `VOID`, and increments the MOC's
        `version`; the new request lands in `PENDING` with `decided_by` unset."
        PRD §2.7: "If the supplied value does not match the MOC's current
        `version`, the request is rejected with `ERR_STALE_MOC_VERSION` (HTTP
        412)". No approval happened, so the dates never move.

        Design: Corner/cross_cutting_complexity_layers/occ_extension_supersede_and_stale_version
        """
        unit, actors, moc = self._temp_moc_in_service()
        req_id = actors["req"]["id"]

        e1 = validate_success(api.create_extension_request(
            moc["id"], create_extension_request_payload(moc_version(moc["id"]), requested_days=30),
            make_requester_headers(req_id)), 201)
        stale_version = moc_version(moc["id"])
        e2 = validate_success(api.create_extension_request(
            moc["id"], create_extension_request_payload(stale_version, requested_days=45),
            make_requester_headers(req_id)), 201)

        extensions = {e["id"]: e for e in list_extension_requests(moc["id"])}
        assert extensions[e1["id"]]["status"] == "VOID", "fresh create supersedes the pending sibling"
        assert extensions[e2["id"]]["status"] == "PENDING"

        resp = api.create_extension_request(
            moc["id"], create_extension_request_payload(stale_version, requested_days=10),
            make_requester_headers(req_id))
        validate_error(resp, ApiErrorId.ERR_STALE_MOC_VERSION.value)
        assert resp.status_code == 412
        assert get_moc(moc["id"])["temporary_end_date"] == "2026-10-28T00:00:00Z"


class TestCloseGate:
    def test_close_moc_blocked_by_open_condition_items(self, api):
        """PRD §3.4: "The approval payload may carry an optional `conditions`
        array: each element spawns a new action item in `OPEN` status with
        `source_type` `MOC_CONDITION` sourced to this MOC".
        PRD §3.5: startup is blocked only when "open-class action item of priority
        `P1`" remains — an open P2 condition does not block authorization.
        PRD §3.6: "A `PsmManager` may close a `PERMANENT` or
        `REPLACEMENT_IN_KIND` MOC from `IN_SERVICE`, provided no open-class action
        item with `source_type` `MOC_CONDITION` remains sourced to it
        (`ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE`)".

        Design: Corner/validations/close_moc_blocked_by_open_condition_items
        """
        unit, study = setup_unit_with_study()
        actors = create_standard_actors()
        moc = drive_moc_to_in_service(
            unit["id"], actors["req"]["id"], actors["rev"]["id"], actors["app"]["id"],
            actors["lead"]["id"], change_class="PERMANENT", severity=1, likelihood=1,
            conditions=[{"title": "Install placard", "priority": "P2",
                         "assignee_id": actors["req"]["id"]}])
        assert moc["status"] == "IN_SERVICE", (
            "authorize-startup must succeed despite the open P2 condition (P1-only gate)"
        )
        items = list_unit_action_items(unit["id"])
        assert len(items) == 1 and items[0]["source_type"] == "MOC_CONDITION"
        condition_item = items[0]

        blocked = api.close_moc(moc["id"], MANAGER)
        validate_error(blocked, ApiErrorId.ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE.value)

        work_item_to_submitted(condition_item["id"], actors["req"]["id"],
                               file_ref="s3://ev/placard.jpg")
        verify_item(condition_item["id"])
        closed = validate_success(api.close_moc(moc["id"], MANAGER), 200)
        assert closed["status"] == "CLOSED"
