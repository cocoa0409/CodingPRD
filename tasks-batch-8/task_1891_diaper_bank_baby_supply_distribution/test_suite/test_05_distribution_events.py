"""Distribution event scheduling, lifecycle transitions, and the lock/unlock revert."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_distribution_event,
    create_agency,
    create_event,
    create_household,
    create_issuance_payload,
    get_event,
    get_inventory,
    get_run,
    get_run_lines,
    lock_event,
    open_event,
    record_issuance,
    setup_event_with_issuance,
    size_entry,
    supply_line,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]


class TestSiteScheduling:
    def test_back_to_back_events_allowed(self, api):
        """PRD §3.5: "Scheduling enforces one site's single-booking rule: the new event's half-open window, inclusive of `starts_at` and exclusive of `ends_at`, must not intersect the window of any existing event at the same `site_name` whose status is `SCHEDULED`, `OPEN`, or `LOCKED`; a conflict is rejected with `ERR_SITE_SCHEDULE_CONFLICT`, while two events that merely touch — one's `ends_at` equal to the other's `starts_at` — are allowed."

        Design: Difficulty/resource_temporal_overlap/site_event_half_open_interval_adjacency
        """
        agency = create_agency(name="Agency J", agency_code="AG-J",
                               contact_email="j@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        first = create_event(agency["id"], site_name="Dock",
                             starts_at="2026-08-10T09:00:00Z",
                             ends_at="2026-08-10T12:00:00Z")
        assert_distribution_event(first)

        # Adjacency is not overlap: the second window starts exactly when the
        # first ends, and half-open intervals treat that as non-intersecting.
        second = validate_success(
            api.create_distribution_event(
                {"host_agency_id": agency["id"], "site_name": "Dock",
                 "starts_at": "2026-08-10T12:00:00Z",
                 "ends_at": "2026-08-10T15:00:00Z"},
                ADMIN,
            ),
            201,
        )
        assert second["status"] == "SCHEDULED"
        assert second["id"] != first["id"]

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.5: "Scheduling enforces one site's single-booking rule: the new event's half-open window, inclusive of `starts_at` and exclusive of `ends_at`, must not intersect the window of any existing event at the same `site_name` whose status is `SCHEDULED`, `OPEN`, or `LOCKED`; a conflict is rejected with `ERR_SITE_SCHEDULE_CONFLICT`, while two events that merely touch — one's `ends_at` equal to the other's `starts_at` — are allowed."

        Design: Difficulty/resource_temporal_overlap/site_event_half_open_interval_adjacency
        """
        agency = create_agency(name="Agency J", agency_code="AG-J",
                               contact_email="j@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        create_event(agency["id"], site_name="Dock",
                     starts_at="2026-08-10T09:00:00Z",
                     ends_at="2026-08-10T12:00:00Z")
        create_event(agency["id"], site_name="Dock",
                     starts_at="2026-08-10T12:00:00Z",
                     ends_at="2026-08-10T15:00:00Z")

        # 11:59 < 12:00, so [11:59, 13:00) intersects the first event's window.
        resp = api.create_distribution_event(
            {"host_agency_id": agency["id"], "site_name": "Dock",
             "starts_at": "2026-08-10T11:59:00Z",
             "ends_at": "2026-08-10T13:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_SCHEDULE_CONFLICT)


class TestEventOpening:
    def test_event_open_requires_active_agency(self, api):
        """PRD §3.5: "Opening an event — `SCHEDULED` → `OPEN` — requires that the event is still `SCHEDULED` (otherwise `ERR_INVALID_EVENT_STATE`), that its host agency is `ACTIVE` (otherwise `ERR_AGENCY_NOT_ACTIVE`), and that the logical clock has not reached the event's `ends_at` (opening at or after the end is rejected with `ERR_EVENT_ALREADY_ENDED`)."

        Design: Difficulty/cross_entity_state_dependency/event_open_requires_active_agency
        """
        agency = create_agency(name="Agency I", agency_code="AG-I",
                               contact_email="i@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        event = create_event(agency["id"], site_name="X-Site")
        validate_success(api.suspend_agency(agency["id"], ADMIN), 200)

        resp = api.open_distribution_event(event["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_ACTIVE)

    def test_rejected_open_leaves_event_scheduled(self, api):
        """PRD §3.5: "Opening an event — `SCHEDULED` → `OPEN` — requires that the event is still `SCHEDULED` (otherwise `ERR_INVALID_EVENT_STATE`), that its host agency is `ACTIVE` (otherwise `ERR_AGENCY_NOT_ACTIVE`), and that the logical clock has not reached the event's `ends_at` (opening at or after the end is rejected with `ERR_EVENT_ALREADY_ENDED`)."
        PRD §3.1: "`SUSPENDED` is terminal, and a suspended agency's practical consequence reaches beyond allocations: an event hosted by a non-`ACTIVE` agency cannot be opened (§3.5)."

        Design: Difficulty/cross_entity_state_dependency/event_open_requires_active_agency
        """
        agency = create_agency(name="Agency I", agency_code="AG-I",
                               contact_email="i@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        event = create_event(agency["id"], site_name="X-Site")
        validate_success(api.suspend_agency(agency["id"], ADMIN), 200)

        resp = api.open_distribution_event(event["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_ACTIVE)

        event_after = get_event(event["id"])
        assert event_after["status"] == "SCHEDULED", (
            "A rejected open performs no partial transition"
        )


class TestLockUnlockRevert:
    def test_unlock_reverts_locked_event_to_open(self, api):
        """PRD §3.5: "Locking — `OPEN` → `LOCKED` — freezes recording ahead of completion; unlocking — `LOCKED` → `OPEN` — is the legal revert branch, and the lock/unlock pair may repeat."
        PRD §3.5: "While `OPEN`, issuances may be recorded."

        Design: Difficulty/non_linear_state_machine/event_lock_unlock_revert_branch
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_2", stock_units=200, issue_quantity=100, record=False,
        )
        event = scenario["event"]
        assert event["status"] == "OPEN"

        locked = validate_success(api.lock_distribution_event(event["id"], ADMIN), 200)
        assert locked["status"] == "LOCKED"

        unlocked = validate_success(api.unlock_distribution_event(event["id"], ADMIN), 200)
        assert unlocked["status"] == "OPEN", "Unlock is the legal revert branch"

        # Recording is possible again after the revert.
        issuance = record_issuance(
            event["id"], scenario["household"]["id"],
            [supply_line("SIZE_2", 100)],
        )
        assert issuance["status"] == "RECORDED"
        assert issuance["total_units"] == 100

    def test_reverted_event_completes_and_credits_line(self, api):
        """PRD §3.5: "In the second hop, each fulfilled issuance line debits the inventory twice — `on_hand_units` decreases by the quantity and `reserved_units` decreases by the same quantity, because the reservation is being consumed rather than released, leaving `available_units` unchanged by fulfillment itself — and the allocation line selected by the clock's current calendar month, the run's `PUBLISHED` status, the event's host agency, and the line's size is credited, its `fulfilled_units` increasing by the quantity and its status recomputed per §3.4."
        PRD §3.4: "a line whose `fulfilled_units` lands between zero and `allocated_units` moves `ALLOCATED` → `PARTIALLY_FULFILLED`"

        Design: Difficulty/non_linear_state_machine/event_lock_unlock_revert_branch
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_2", stock_units=200, issue_quantity=100, record=False,
        )
        event = scenario["event"]
        validate_success(api.lock_distribution_event(event["id"], ADMIN), 200)
        validate_success(api.unlock_distribution_event(event["id"], ADMIN), 200)
        record_issuance(event["id"], scenario["household"]["id"],
                        [supply_line("SIZE_2", 100)])
        validate_success(api.lock_distribution_event(event["id"], ADMIN), 200)

        completed = validate_success(api.complete_distribution_event(event["id"], ADMIN), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["issued_total_units"] == 100

        lines = get_run_lines(scenario["run"]["id"])
        assert lines[0]["fulfilled_units"] == 100
        assert lines[0]["status"] == "PARTIALLY_FULFILLED", (
            "100 fulfilled of 200 allocated lands between zero and the allocation"
        )
        assert get_run(scenario["run"]["id"])["status"] == "PUBLISHED", (
            "The run stays PUBLISHED while a line remains unfulfilled"
        )

        entry = size_entry(get_inventory(), "SIZE_2")
        assert entry["on_hand_units"] == 100
        assert entry["reserved_units"] == 100, (
            "Fulfillment consumes the reservation instead of releasing it"
        )


class TestEventCancellation:
    def test_event_cancel_after_complete_lockdown(self, api):
        """PRD §3.5: "An event may be cancelled from `SCHEDULED` or from `OPEN`; a `LOCKED` event cannot be cancelled directly — it must be unlocked first — and cancellation from `LOCKED` or any action on a terminal event is rejected with `ERR_INVALID_EVENT_STATE`."
        PRD §3.5: "`COMPLETED` is terminal."

        Design: Corner/state_machines/event_cancel_after_complete_lockdown
        """
        agency = create_agency(name="Agency T", agency_code="AG-T",
                               contact_email="t@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        event = create_event(agency["id"], site_name="T-Site")
        open_event(event["id"])
        lock_event(event["id"])
        completed = validate_success(
            api.complete_distribution_event(event["id"], ADMIN), 200)
        assert completed["status"] == "COMPLETED"

        resp = api.cancel_distribution_event(event["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE)

        event_after = get_event(event["id"])
        assert event_after["status"] == "COMPLETED"
        assert event_after["issued_total_units"] == 0, (
            "No issuances existed, so the fulfilled-total sum is zero"
        )

    def test_event_cancel_auto_voids_recorded_issuances(self, api):
        """PRD §3.5: "Cancelling an `OPEN` event voids its work: every `RECORDED` issuance transitions to `VOIDED` with no inventory effect, because stock moves only on fulfillment."

        Design: Corner/state_machines/event_cancel_auto_voids_recorded_issuances
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_2", stock_units=100, issue_quantity=40, record=True,
        )
        event = scenario["event"]
        issuance = scenario["issuance"]
        assert issuance["status"] == "RECORDED"

        cancelled = validate_success(api.cancel_distribution_event(event["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"

        issuances = validate_success(
            api.list_event_issuances(event["id"], ADMIN), 200)
        assert issuances[0]["status"] == "VOIDED", (
            "Cancelling an OPEN event auto-voids its RECORDED issuances"
        )

        household = validate_success(
            api.get_household(scenario["household"]["id"], PRIVACY), 200)
        assert household["consumed_this_month_units"] == 0, (
            "VOIDED issuances are excluded from monthly consumption"
        )

        entry = size_entry(get_inventory(), "SIZE_2")
        assert entry["on_hand_units"] == 100, "Stock moves only at fulfillment"
        assert entry["reserved_units"] == 100, (
            "The published run's reservation is untouched by an event cancellation"
        )


class TestIssuanceEventGate:
    def test_issuance_on_locked_event_rejected(self, api):
        """PRD §3.5: "The gates fire in the pipeline order of §2.6: the event must be `OPEN` (otherwise `ERR_EVENT_NOT_OPEN`); if the household is flagged `privacy_restricted`, only a `PrivacyOfficer` may record for it (otherwise `ERR_PRIVACY_RESTRICTED`); the household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_NOT_ELIGIBLE`); and each household may receive at most one issuance per event (a second attempt yields `ERR_DUPLICATE_HOUSEHOLD_ISSUANCE`)."

        Design: Corner/validations/issuance_on_locked_event_rejected
        """
        agency = create_agency(name="Agency L", agency_code="AG-L",
                               contact_email="l@x.org", children_served_monthly=100,
                               storage_capacity_units=10000)
        event = create_event(agency["id"], site_name="L-Site")
        open_event(event["id"])
        lock_event(event["id"])
        household = create_household(children_sizes=["SIZE_1"], consent_on_file=True)

        resp = api.record_issuance(
            event["id"],
            create_issuance_payload(household["id"],
                                    lines=[supply_line("SIZE_1", 10)]),
            PRIVACY,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPEN)
