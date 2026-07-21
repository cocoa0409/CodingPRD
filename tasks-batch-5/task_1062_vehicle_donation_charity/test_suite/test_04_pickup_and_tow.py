"""Getting the car into custody: tow windows, vendors and attempts."""
from test_helpers import (
    ApiErrorId,
    assert_follow_up_task,
    assert_pickup_order,
    cancel_as_donor,
    create_pickup_order_payload,
    new_charity,
    new_donor,
    new_vendor,
    read_donation,
    read_pickup,
    read_vendor,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    book_pickup,
    donation_tasks,
    donation_version,
    read_donor,
    set_clock,
    setup_accepted_with_vendor,
    setup_pickup_blocked_donation,
)


class TestPickupFailureCascade:
    def test_third_failed_tow_blocks_the_donation(self, api, intake_agent_headers):
        """PRD §3.5: "The order moves `SCHEDULED → FAILED`, the reason is stored, the
        vendor's `booked_slots_count` falls by one, and the donation's `pickup_attempts`
        rises by one. When that increment brings the count to three or beyond, the
        donation moves `ACCEPTED → PICKUP_BLOCKED`, and that blockage in turn opens a
        follow-up obligation of type `PICKUP_ESCALATION`, `OPEN`, assigned to
        `ProgramAdmin`, and due fifteen days after the current logical clock."

        Design: Difficulty/transitive_cascade/pickup_failure_cascades_to_pickup_block_and_escalation_task
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor(declared_condition="POOR")
        donation_id = bundle["donation"]["id"]

        first = book_pickup(
            donation_id,
            bundle["vendor"]["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=bundle["donation"]["version"],
        )
        validate_success(
            api.fail_pickup(
                first["id"], {"failure_reason": "vehicle not at address"}, intake_agent_headers
            ),
            200,
        )
        after_first = read_donation(donation_id)
        assert after_first["pickup_attempts"] == 1
        assert after_first["status"] == "ACCEPTED"

        second = book_pickup(
            donation_id,
            bundle["vendor"]["id"],
            start="2026-07-07T09:00:00Z",
            end="2026-07-07T11:00:00Z",
        )
        validate_success(
            api.fail_pickup(
                second["id"], {"failure_reason": "keys unavailable"}, intake_agent_headers
            ),
            200,
        )
        after_second = read_donation(donation_id)
        assert after_second["pickup_attempts"] == 2
        assert after_second["status"] == "ACCEPTED"

        third = book_pickup(
            donation_id,
            bundle["vendor"]["id"],
            start="2026-07-08T09:00:00Z",
            end="2026-07-08T11:00:00Z",
        )
        validate_success(
            api.fail_pickup(
                third["id"], {"failure_reason": "donor not reachable"}, intake_agent_headers
            ),
            200,
        )

        blocked = read_donation(donation_id)
        assert blocked["pickup_attempts"] == 3
        assert blocked["status"] == "PICKUP_BLOCKED"
        assert blocked["payout_status"] == "PENDING", "the money axis never moved"
        assert read_pickup(third["id"])["attempt_number"] == 3
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 0

    def test_pickup_block_opens_exactly_one_escalation_task(self, api):
        """PRD §3.10: "Follow-up obligations arise in four ways, all of them consequences
        of other work: a drafted receipt raises a `RECEIPT_DELIVERY` task due in thirty
        days; a donation blocked after three failed tows raises a `PICKUP_ESCALATION` task
        due in fifteen days; an abandoned title raises a `TITLE_STALE` task due in fifteen
        days; and an auto-opened remittance batch raises a `REMITTANCE_PENDING` task due
        in fifteen days."
        PRD §3.5: "When that increment brings the count to three or beyond, the donation
        moves `ACCEPTED → PICKUP_BLOCKED`, and that blockage in turn opens a follow-up
        obligation of type `PICKUP_ESCALATION`, `OPEN`, assigned to `ProgramAdmin`, and
        due fifteen days after the current logical clock."

        Design: Difficulty/transitive_cascade/pickup_failure_cascades_to_pickup_block_and_escalation_task
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_pickup_blocked_donation()

        tasks = donation_tasks(bundle["donation"]["id"])
        assert len(tasks) == 1
        task = tasks[0]
        assert_follow_up_task(task)
        assert task["task_type"] == "PICKUP_ESCALATION"
        assert task["status"] == "OPEN"
        assert task["assigned_role"] == "ProgramAdmin"
        assert task["due_utc"].startswith("2026-07-20T00:00:00")
        assert bundle["donation"]["status"] == "PICKUP_BLOCKED"


class TestVendorStanding:
    def test_reservation_against_a_suspended_vendor_is_refused(
        self, api, intake_agent_headers, program_admin_headers
    ):
        """PRD §3.1: "Vendors begin `ACTIVE` with `booked_slots_count` at 0, and may be
        moved to `SUSPENDED`, after which no new reservation and no completion may be
        booked against them — reported as `ERR_VENDOR_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/pickup_order_creation_blocked_by_suspended_tow_vendor
        """
        set_clock("2026-07-05T00:00:00Z")
        suspended = new_vendor(name="Sidelined Towing", hourly_rate_cents=11_000)
        validate_success(api.suspend_tow_vendor(suspended["id"], program_admin_headers), 200)
        bundle = setup_accepted_with_vendor(
            vendor=new_vendor(name="Active Towing", hourly_rate_cents=13_000),
            declared_condition="FAIR",
        )

        response = api.create_pickup_order(
            create_pickup_order_payload(
                bundle["donation"]["id"], suspended["id"], bundle["donation"]["version"]
            ),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_VENDOR_SUSPENDED.value)
        refreshed = read_vendor(suspended["id"])
        assert refreshed["status"] == "SUSPENDED"
        assert refreshed["booked_slots_count"] == 0

    def test_the_identical_window_is_accepted_by_an_active_vendor(self, api, intake_agent_headers):
        """PRD §3.5: "A reservation that survives all of that is created in `status` of
        `SCHEDULED`, raises the vendor's `booked_slots_count` by one, and records
        `attempt_number` as one more than the donation's `pickup_attempts` at that moment."

        Design: Difficulty/cross_entity_state_dependency/pickup_order_creation_blocked_by_suspended_tow_vendor
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor(declared_condition="FAIR")

        order = validate_success(
            api.create_pickup_order(
                create_pickup_order_payload(
                    bundle["donation"]["id"],
                    bundle["vendor"]["id"],
                    bundle["donation"]["version"],
                ),
                intake_agent_headers,
            ),
            201,
        )

        assert_pickup_order(order)
        assert order["status"] == "SCHEDULED"
        assert order["attempt_number"] == 1
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 1
        assert read_donation(bundle["donation"]["id"])["pickup_attempts"] == 0


class TestVendorWindowSeparation:
    def test_window_inside_the_ninety_minute_buffer_collides(self, api, intake_agent_headers):
        """PRD §3.5: "Concretely, a proposed window collides with an existing scheduled
        window on that vendor when the proposed start falls strictly before the existing
        end extended by ninety minutes **and** the existing start falls strictly before
        the proposed end extended by ninety minutes; a collision is refused with
        `ERR_VENDOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vendor_window_conflict_at_exact_ninety_minute_buffer_edge
        """
        set_clock("2026-07-05T00:00:00Z")
        charity = new_charity()
        donor = new_donor()
        vendor = new_vendor()
        first_bundle = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        book_pickup(
            first_bundle["donation"]["id"],
            vendor["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=first_bundle["donation"]["version"],
        )
        second_bundle = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)

        response = api.create_pickup_order(
            create_pickup_order_payload(
                second_bundle["donation"]["id"],
                vendor["id"],
                second_bundle["donation"]["version"],
                scheduled_start_utc="2026-07-06T12:29:00Z",
                scheduled_end_utc="2026-07-06T14:00:00Z",
            ),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_VENDOR_WINDOW_CONFLICT.value)
        assert read_vendor(vendor["id"])["booked_slots_count"] == 1

    def test_window_exactly_ninety_minutes_after_the_existing_end_is_accepted(
        self, api, intake_agent_headers
    ):
        """PRD §3.5: "Windows are half-open, covering their start instant but not their
        end instant, and a new window beginning exactly ninety minutes after an existing
        window's end is therefore accepted."
        PRD §3.5: "Vendors need turnaround time between jobs, so reserved windows on the
        same vendor must stand ninety minutes apart."

        Design: Difficulty/resource_temporal_overlap/vendor_window_conflict_at_exact_ninety_minute_buffer_edge
        """
        set_clock("2026-07-05T00:00:00Z")
        charity = new_charity()
        donor = new_donor()
        vendor = new_vendor()
        first_bundle = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        book_pickup(
            first_bundle["donation"]["id"],
            vendor["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=first_bundle["donation"]["version"],
        )
        second_bundle = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)

        order = validate_success(
            api.create_pickup_order(
                create_pickup_order_payload(
                    second_bundle["donation"]["id"],
                    vendor["id"],
                    second_bundle["donation"]["version"],
                    scheduled_start_utc="2026-07-06T12:30:00Z",
                    scheduled_end_utc="2026-07-06T14:00:00Z",
                ),
                intake_agent_headers,
            ),
            201,
        )

        assert order["status"] == "SCHEDULED"
        assert read_vendor(vendor["id"])["booked_slots_count"] == 2
        rows, _ = validate_paginated(
            api.list_pickup_orders(intake_agent_headers, params={"tow_vendor_id": vendor["id"]})
        )
        assert len(rows) == 2
        assert all(row["status"] == "SCHEDULED" for row in rows)


class TestVendorSlotConservation:
    def test_each_reservation_raises_the_vendor_slot_count(self, api):
        """PRD §2.9: "`TowVendor.booked_slots_count` is the number of that vendor's pickup
        orders whose `status` is `SCHEDULED`: it rises by one whenever an order is created
        and falls by one whenever an order leaves `SCHEDULED` by completion, failure, or
        cancellation."

        Design: Difficulty/compensating_invariant/pickup_create_then_cancel_restores_vendor_slot_count
        """
        set_clock("2026-07-05T00:00:00Z")
        charity = new_charity()
        donor = new_donor()
        vendor = new_vendor(name="Counting Towing")
        first = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        second = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)

        book_pickup(
            first["donation"]["id"],
            vendor["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=first["donation"]["version"],
        )
        assert read_vendor(vendor["id"])["booked_slots_count"] == 1

        book_pickup(
            second["donation"]["id"],
            vendor["id"],
            start="2026-07-08T09:00:00Z",
            end="2026-07-08T11:00:00Z",
            expected_version=second["donation"]["version"],
        )
        assert read_vendor(vendor["id"])["booked_slots_count"] == 2

    def test_cancelling_both_reservations_restores_the_count_without_counting_attempts(
        self, api, intake_agent_headers
    ):
        """PRD §3.5: "The order moves `SCHEDULED → CANCELLED` and the vendor's
        `booked_slots_count` falls by one — but, unlike a failure, the donation's
        `pickup_attempts` is left untouched. A release is not an attempt."

        Design: Difficulty/compensating_invariant/pickup_create_then_cancel_restores_vendor_slot_count
        """
        set_clock("2026-07-05T00:00:00Z")
        charity = new_charity()
        donor = new_donor()
        vendor = new_vendor(name="Counting Towing")
        first = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        second = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        first_order = book_pickup(
            first["donation"]["id"],
            vendor["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=first["donation"]["version"],
        )
        second_order = book_pickup(
            second["donation"]["id"],
            vendor["id"],
            start="2026-07-08T09:00:00Z",
            end="2026-07-08T11:00:00Z",
            expected_version=second["donation"]["version"],
        )

        validate_success(
            api.cancel_pickup(
                first_order["id"], {"reason": "donor rescheduled"}, intake_agent_headers
            ),
            200,
        )
        assert read_vendor(vendor["id"])["booked_slots_count"] == 1

        validate_success(
            api.cancel_pickup(
                second_order["id"], {"reason": "vendor truck breakdown"}, intake_agent_headers
            ),
            200,
        )
        assert read_vendor(vendor["id"])["booked_slots_count"] == 0

        rows, meta = validate_paginated(
            api.list_pickup_orders(
                intake_agent_headers,
                params={"tow_vendor_id": vendor["id"], "status": "SCHEDULED"},
            )
        )
        assert rows == [] and meta["total_count"] == 0
        assert read_pickup(first_order["id"])["status"] == "CANCELLED"
        assert read_pickup(second_order["id"])["status"] == "CANCELLED"
        for bundle in (first, second):
            donation = read_donation(bundle["donation"]["id"])
            assert donation["pickup_attempts"] == 0
            assert donation["status"] == "ACCEPTED"


class TestWindowValidation:
    def test_window_ending_before_it_starts_is_refused(self, api, intake_agent_headers):
        """PRD §3.5: "The window must be coherent — the end strictly after the start,
        otherwise `ERR_PICKUP_WINDOW_INVALID` — and it may not be backdated: a start
        strictly before the current logical clock is refused with `ERR_PICKUP_IN_PAST`,
        while a start exactly at the current clock is accepted."

        Design: Corner/validations/corner_pickup_window_with_end_before_start_returns_window_invalid
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor()

        response = api.create_pickup_order(
            create_pickup_order_payload(
                bundle["donation"]["id"],
                bundle["vendor"]["id"],
                bundle["donation"]["version"],
                scheduled_start_utc="2026-07-06T11:00:00Z",
                scheduled_end_utc="2026-07-06T09:00:00Z",
            ),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_PICKUP_WINDOW_INVALID.value)
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 0
        rows, _ = validate_paginated(
            api.list_pickup_orders(
                intake_agent_headers, params={"donation_id": bundle["donation"]["id"]}
            )
        )
        assert rows == []

    def test_backdated_window_is_refused_while_a_window_at_the_clock_is_accepted(
        self, api, intake_agent_headers
    ):
        """PRD §3.5: "The window must be coherent — the end strictly after the start,
        otherwise `ERR_PICKUP_WINDOW_INVALID` — and it may not be backdated: a start
        strictly before the current logical clock is refused with `ERR_PICKUP_IN_PAST`,
        while a start exactly at the current clock is accepted."

        Design: Corner/validations/corner_pickup_window_starting_before_the_clock_returns_pickup_in_past
        """
        set_clock("2026-07-05T12:00:00Z")
        bundle = setup_accepted_with_vendor(vendor=new_vendor(name="Past Towing"))

        backdated = api.create_pickup_order(
            create_pickup_order_payload(
                bundle["donation"]["id"],
                bundle["vendor"]["id"],
                bundle["donation"]["version"],
                scheduled_start_utc="2026-07-05T11:59:00Z",
                scheduled_end_utc="2026-07-05T14:00:00Z",
            ),
            intake_agent_headers,
        )
        validate_error(backdated, ApiErrorId.ERR_PICKUP_IN_PAST.value)

        at_the_clock = validate_success(
            api.create_pickup_order(
                create_pickup_order_payload(
                    bundle["donation"]["id"],
                    bundle["vendor"]["id"],
                    bundle["donation"]["version"],
                    scheduled_start_utc="2026-07-05T12:00:00Z",
                    scheduled_end_utc="2026-07-05T14:00:00Z",
                ),
                intake_agent_headers,
            ),
            201,
        )
        assert at_the_clock["status"] == "SCHEDULED"
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 1

    def test_vendor_capacity_caps_the_number_of_scheduled_orders(self, api, intake_agent_headers):
        """PRD §3.5: "Beyond separation, the vendor's overall load is capped: if adding
        this reservation would push the vendor's count of `SCHEDULED` orders above its
        `daily_capacity_slots`, the request is refused with
        `ERR_VENDOR_CAPACITY_EXCEEDED`."

        Design: Corner/validations/corner_vendor_capacity_is_an_aggregate_validation
        """
        set_clock("2026-07-05T00:00:00Z")
        charity = new_charity()
        donor = new_donor()
        vendor = new_vendor(name="One Slot Towing", daily_capacity_slots=1)
        first = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
        book_pickup(
            first["donation"]["id"],
            vendor["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=first["donation"]["version"],
        )
        second = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)

        response = api.create_pickup_order(
            create_pickup_order_payload(
                second["donation"]["id"],
                vendor["id"],
                second["donation"]["version"],
                scheduled_start_utc="2026-07-09T09:00:00Z",
                scheduled_end_utc="2026-07-09T11:00:00Z",
            ),
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED.value)
        assert read_vendor(vendor["id"])["booked_slots_count"] == 1
        rows, _ = validate_paginated(
            api.list_pickup_orders(intake_agent_headers, params={"tow_vendor_id": vendor["id"]})
        )
        assert len(rows) == 1

    def test_attempt_budget_blocks_a_fourth_reservation_until_the_pickup_is_reset(
        self, api, intake_agent_headers, program_admin_headers
    ):
        """PRD §3.5: "And the program will not chase a car forever — a donation whose
        `pickup_attempts` has already reached three admits no further reservation, refused
        with `ERR_PICKUP_ATTEMPTS_EXCEEDED`."
        PRD §3.5: "A program administrator resets the pickup with a `reason`, moving the
        donation `PICKUP_BLOCKED → ACCEPTED`, resetting `pickup_attempts` to 0, and
        marking every `PICKUP_ESCALATION` follow-up on that donation that is still `OPEN`
        or `ESCALATED` as `DONE` with a `resolution_note` of exactly `pickup reset`."

        Design: Corner/validations/corner_new_pickup_order_after_three_failures_is_conditionally_blocked
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_pickup_blocked_donation()
        donation_id = bundle["donation"]["id"]
        vendor_id = bundle["vendor"]["id"]

        refused = api.create_pickup_order(
            create_pickup_order_payload(
                donation_id,
                vendor_id,
                donation_version(donation_id),
                scheduled_start_utc="2026-07-09T09:00:00Z",
                scheduled_end_utc="2026-07-09T11:00:00Z",
            ),
            intake_agent_headers,
        )
        validate_error(refused, ApiErrorId.ERR_PICKUP_ATTEMPTS_EXCEEDED.value)

        reset = validate_success(
            api.reset_pickup(
                donation_id, {"reason": "donor confirmed new address"}, program_admin_headers
            ),
            200,
        )
        assert reset["status"] == "ACCEPTED"
        assert reset["pickup_attempts"] == 0
        escalations = [
            task
            for task in donation_tasks(donation_id)
            if task["task_type"] == "PICKUP_ESCALATION"
        ]
        assert escalations and all(task["status"] == "DONE" for task in escalations)
        assert all(task["resolution_note"] == "pickup reset" for task in escalations)

        accepted = validate_success(
            api.create_pickup_order(
                create_pickup_order_payload(
                    donation_id,
                    vendor_id,
                    reset["version"],
                    scheduled_start_utc="2026-07-09T09:00:00Z",
                    scheduled_end_utc="2026-07-09T11:00:00Z",
                ),
                intake_agent_headers,
            ),
            201,
        )
        assert accepted["attempt_number"] == 1
        assert read_vendor(vendor_id)["booked_slots_count"] == 1


class TestPickupCascadesAndConcurrency:
    def test_cancelling_the_donation_releases_its_scheduled_tow(self, api):
        """PRD §3.2: "Cancellation lowers the donor's `donation_count` by one and releases
        logistics: every pickup order for that donation still sitting in `SCHEDULED` is
        cancelled, and each such cancellation lowers that vendor's `booked_slots_count` by
        one."

        Design: Corner/state_machines/corner_donation_cancel_cascades_down_to_scheduled_pickup_orders
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor(vendor=new_vendor(name="Cascade Towing"))
        order = book_pickup(
            bundle["donation"]["id"],
            bundle["vendor"]["id"],
            expected_version=bundle["donation"]["version"],
        )

        cancelled = validate_success(
            cancel_as_donor(bundle["donation"]["id"], bundle["donor"]["id"]), 200
        )

        assert cancelled["status"] == "CANCELLED"
        assert read_pickup(order["id"])["status"] == "CANCELLED"
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 0
        assert cancelled["pickup_attempts"] == 0
        assert read_donor(bundle["donor"]["id"])["donation_count"] == 0

    def test_completing_a_cascade_cancelled_order_is_refused(self, api, intake_agent_headers):
        """PRD §3.5: "Any of these three against an order that is not `SCHEDULED` is
        refused with `ERR_INVALID_PICKUP_STATE`."
        PRD §3.5: "**Completion.** An agent records a successful tow together with the
        billed `actual_tow_cost_cents`."

        Design: Corner/state_machines/corner_pickup_complete_is_guarded_by_donation_status
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor(vendor=new_vendor(name="Guard Towing"))
        order = book_pickup(
            bundle["donation"]["id"],
            bundle["vendor"]["id"],
            expected_version=bundle["donation"]["version"],
        )
        validate_success(cancel_as_donor(bundle["donation"]["id"], bundle["donor"]["id"]), 200)

        response = api.complete_pickup(
            order["id"], {"actual_tow_cost_cents": 15_000}, intake_agent_headers
        )

        validate_error(response, ApiErrorId.ERR_INVALID_PICKUP_STATE.value)
        after = read_pickup(order["id"])
        assert after["status"] == "CANCELLED"
        assert after["actual_tow_cost_cents"] == 0, "no tow cost was ever recorded"
        assert read_donation(bundle["donation"]["id"])["status"] == "CANCELLED"
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 0

    def test_stale_donation_version_blocks_a_second_reservation(self, api, intake_agent_headers):
        """PRD §2.7: "Creating a pickup order requires `expected_donation_version`,
        carrying the client's last observed `version` of the donation being towed. If it
        does not equal the donation's current `version`, the create is rejected with
        `ERR_STALE_DONATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/corner_occ_stale_donation_version_on_pickup_order_create
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_accepted_with_vendor(vendor=new_vendor(name="OCC Towing"))
        donation_id = bundle["donation"]["id"]
        stale_version = bundle["donation"]["version"]
        book_pickup(
            donation_id,
            bundle["vendor"]["id"],
            start="2026-07-06T09:00:00Z",
            end="2026-07-06T11:00:00Z",
            expected_version=stale_version,
        )

        refused = api.create_pickup_order(
            create_pickup_order_payload(
                donation_id,
                bundle["vendor"]["id"],
                stale_version,
                scheduled_start_utc="2026-07-09T09:00:00Z",
                scheduled_end_utc="2026-07-09T11:00:00Z",
            ),
            intake_agent_headers,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_DONATION_VERSION.value)
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 1
        version_after_refusal = donation_version(donation_id)

        accepted = validate_success(
            api.create_pickup_order(
                create_pickup_order_payload(
                    donation_id,
                    bundle["vendor"]["id"],
                    version_after_refusal,
                    scheduled_start_utc="2026-07-09T09:00:00Z",
                    scheduled_end_utc="2026-07-09T11:00:00Z",
                ),
                intake_agent_headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"
        assert read_vendor(bundle["vendor"]["id"])["booked_slots_count"] == 2
        assert donation_version(donation_id) == version_after_refusal + 1
