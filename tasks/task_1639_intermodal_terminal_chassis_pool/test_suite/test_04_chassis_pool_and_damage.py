"""Chassis lifecycle, reservation preconditions, roadability axis, and damage
workflows (PRD §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_chassis,
    assert_chassis_pool,
    assert_damage_inspection,
    assert_ledger_entry,
    check_in,
    create_chassis,
    create_pool,
    create_terminal,
    get_chassis,
    get_container,
    get_membership,
    get_pool,
    is_iso8601_timestamp,
    list_ledger_entries,
    open_damage,
    open_transaction,
    reserve_chassis,
    setup_booked_out_appointment,
    setup_checked_in_out_appointment,
    setup_pending_out_transaction,
    TEST_USERS,
    validate_error,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
PA = TEST_USERS["pool_administrator_headers"]
GS = TEST_USERS["gate_supervisor_headers"]
MP = TEST_USERS["maintenance_planner_headers"]


class TestChassisCreation:
    def test_chassis_created_available_and_roadable(self, api):
        """PRD §3.1: "Adding a chassis to a pool requires only its
        `chassis_number` (unique within the pool); the new unit arrives
        `AVAILABLE` and `ROADABLE`, its `last_inspection_at` unset, and the
        pool's `total_chassis_count` and `available_chassis_count` each rise by
        one."

        Design: Corner/entities/chassis_creation_defaults_roadable
        """
        terminal = create_terminal()
        tid = terminal["id"]
        pool = create_pool(tid)

        chassis = create_chassis(tid, pool["id"])
        assert_chassis(chassis)
        assert chassis["status"] == "AVAILABLE"
        assert chassis["roadability_status"] == "ROADABLE"
        assert chassis.get("last_inspection_at") is None

        pool_after = get_pool(tid, pool["id"])
        assert pool_after["total_chassis_count"] == 1
        assert pool_after["available_chassis_count"] == 1

    def test_chassis_initial_state_available(self, api):
        """PRD §3.1: "the new unit arrives `AVAILABLE` and `ROADABLE`, its
        `last_inspection_at` unset, and the pool's `total_chassis_count` and
        `available_chassis_count` each rise by one."

        Design: Corner/state_machines/chassis_initial_state_available
        """
        terminal = create_terminal()
        tid = terminal["id"]
        pool = create_pool(tid)

        chassis = create_chassis(tid, pool["id"], chassis_number="CH-777")
        assert chassis["status"] == "AVAILABLE", (
            "A newly added chassis starts in AVAILABLE")


class TestChassisReservation:
    def test_reserve_requires_checked_in_appointment(self, api):
        """PRD §3.4: "Reservation requires three preconditions, and their order
        matters per §2.11: the chassis must be `ROADABLE` (else
        `ERR_CHASSIS_UNROADABLE`), its status must be `AVAILABLE` (else
        `ERR_INVALID_STATE`), and the named appointment must be `CHECKED_IN`
        with direction `OUT` (else `ERR_NO_CHECKED_IN_APPOINTMENT`, HTTP 409)."

        The appointment here is BOOKED but never checked in.

        Design: Difficulty/cross_entity_state_dependency/chassis_reserve_depends_on_appointment_checked_in
        """
        ctx = setup_booked_out_appointment()
        tid = ctx["terminal"]["id"]
        assert ctx["appointment"]["status"] == "BOOKED"
        version = get_pool(tid, ctx["pool"]["id"])["version"]

        resp = api.reserve_chassis(
            tid, ctx["pool"]["id"], ctx["chassis"]["id"],
            {"appointment_id": ctx["appointment"]["id"],
             "expected_pool_version": version},
            GS,
        )
        validate_error(resp, ApiErrorId.ERR_NO_CHECKED_IN_APPOINTMENT)
        chassis = get_chassis(tid, ctx["pool"]["id"], ctx["chassis"]["id"])
        assert chassis["status"] == "AVAILABLE"

    def test_reserve_succeeds_after_checkin(self, api):
        """PRD §3.4: "On success the chassis becomes `RESERVED`, the pool's
        `reserved_chassis_count` rises by one and `available_chassis_count`
        falls by one, and the pool's `version` increments."
        PRD §2.9: "A successful reservation itself increments the pool's
        `version` by one."

        Design: Difficulty/cross_entity_state_dependency/chassis_reserve_depends_on_appointment_checked_in
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        pool_before = get_pool(tid, ctx["pool"]["id"])
        assert (pool_before["available_chassis_count"],
                pool_before["reserved_chassis_count"]) == (1, 0)

        chassis = reserve_chassis(
            tid, ctx["pool"]["id"], ctx["chassis"]["id"],
            ctx["appointment"]["id"])
        assert chassis["status"] == "RESERVED"

        pool_after = get_pool(tid, ctx["pool"]["id"])
        assert_chassis_pool(pool_after)
        assert pool_after["reserved_chassis_count"] == 1
        assert pool_after["available_chassis_count"] == 0
        assert pool_after["version"] == pool_before["version"] + 1, (
            "A successful reservation increments the pool's version by exactly one")

    def test_reserve_on_retired_chassis_rejected(self, api):
        """PRD §3.4: "Reservation requires three preconditions, and their order
        matters per §2.11: the chassis must be `ROADABLE` (else
        `ERR_CHASSIS_UNROADABLE`), its status must be `AVAILABLE` (else
        `ERR_INVALID_STATE`), and the named appointment must be `CHECKED_IN`
        with direction `OUT` (else `ERR_NO_CHECKED_IN_APPOINTMENT`, HTTP 409)."

        The chassis is RETIRED (a terminal state) and the named appointment is
        a real CHECKED_IN OUT appointment, isolating the state failure.

        Design: Corner/state_machines/chassis_invalid_transition_from_retired_returns_invalid_state
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]
        validate_success(api.retire_chassis(tid, pid, chid, TM), 200)
        assert get_chassis(tid, pid, chid)["status"] == "RETIRED"

        version = get_pool(tid, pid)["version"]
        resp = api.reserve_chassis(
            tid, pid, chid,
            {"appointment_id": ctx["appointment"]["id"],
             "expected_pool_version": version},
            GS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReserveValidationOrdering:
    def test_state_failure_masks_roadability_failure(self, api):
        """PRD §2.11: "Every request passes through a fixed validation
        sequence, and the order is observable: an earlier failure masks every
        later one." with "5. State-machine legality — the target resource is in
        a state from which the requested transition is defined, else
        `ERR_INVALID_STATE`." preceding "6. Roadability — a chassis being
        reserved, out-gated, or exited from maintenance is `ROADABLE`, else
        `ERR_CHASSIS_UNROADABLE`."

        The chassis is both MAINTENANCE and UNROADABLE; the state failure must
        be reported.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_reserve
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]
        tx = open_transaction(tid, ctx["appointment"]["id"])  # no chassis attached
        open_damage(tid, tx["id"], "BRAKE", "SAFETY_CRITICAL", 250000,
                    chassis_id=chid, as_headers=MP)
        assert get_chassis(tid, pid, chid)["roadability_status"] == "UNROADABLE"
        validate_success(api.enter_maintenance(tid, pid, chid, MP), 200)
        assert get_chassis(tid, pid, chid)["status"] == "MAINTENANCE"

        version = get_pool(tid, pid)["version"]
        resp = api.reserve_chassis(
            tid, pid, chid,
            {"appointment_id": ctx["appointment"]["id"],
             "expected_pool_version": version},
            GS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_unroadable_available_chassis_reserve_rejected(self, api):
        """PRD §3.4: "the chassis must be `ROADABLE` (else
        `ERR_CHASSIS_UNROADABLE`)".

        The chassis is AVAILABLE (state check passes) but UNROADABLE, so the
        roadability failure surfaces on its own.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_reserve
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]
        tx = open_transaction(tid, ctx["appointment"]["id"])  # no chassis attached
        open_damage(tid, tx["id"], "BRAKE", "SAFETY_CRITICAL", 250000,
                    chassis_id=chid, as_headers=MP)
        chassis = get_chassis(tid, pid, chid)
        assert chassis["status"] == "AVAILABLE"
        assert chassis["roadability_status"] == "UNROADABLE"

        version = get_pool(tid, pid)["version"]
        resp = api.reserve_chassis(
            tid, pid, chid,
            {"appointment_id": ctx["appointment"]["id"],
             "expected_pool_version": version},
            GS,
        )
        validate_error(resp, ApiErrorId.ERR_CHASSIS_UNROADABLE)


class TestDamageRoadabilityCascade:
    def test_major_damage_on_reserved_chassis_releases_reservation(self, api):
        """PRD §3.7: "Opening a `MAJOR` or `SAFETY_CRITICAL` inspection against
        a chassis immediately forces that chassis `UNROADABLE` — this
        roadability flip applies regardless of the chassis's current status,
        short of retirement. If the chassis happened to be `RESERVED` at that
        moment, the reservation is voided as a side effect: the chassis drops
        back to `AVAILABLE` and the pool's reserved and available counts
        adjust."

        Design: Difficulty/non_linear_state_machine/chassis_roadability_parallel_dimension
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]
        assert ctx["chassis"]["status"] == "RESERVED"

        damage = open_damage(tid, ctx["transaction"]["id"], "BRAKE", "MAJOR",
                             120000, chassis_id=chid)
        assert_damage_inspection(damage)
        assert damage["status"] == "OPEN"

        chassis = get_chassis(tid, pid, chid)
        assert chassis["roadability_status"] == "UNROADABLE"
        assert chassis["status"] == "AVAILABLE", (
            "The reservation is voided as a side effect of the roadability flip")
        pool = get_pool(tid, pid)
        assert pool["reserved_chassis_count"] == 0
        assert pool["available_chassis_count"] == 1

    def test_minor_damage_leaves_roadability_and_status_untouched(self, api):
        """PRD §3.7: "Opening a `MAJOR` or `SAFETY_CRITICAL` inspection against
        a chassis immediately forces that chassis `UNROADABLE`". A `MINOR`
        inspection is outside that enumeration, so neither axis moves.

        Design: Difficulty/non_linear_state_machine/chassis_roadability_parallel_dimension
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]

        damage = open_damage(tid, ctx["transaction"]["id"], "TIRE", "MINOR",
                             5000, chassis_id=chid)
        assert damage["severity"] == "MINOR"

        chassis = get_chassis(tid, pid, chid)
        assert chassis["roadability_status"] == "ROADABLE", (
            "A MINOR finding does not force UNROADABLE")
        assert chassis["status"] == "RESERVED", (
            "A MINOR finding does not void the reservation")
        pool = get_pool(tid, pid)
        assert pool["reserved_chassis_count"] == 1
        assert pool["available_chassis_count"] == 0

    def test_safety_critical_damage_cascades_unroadable_and_release(self, api):
        """PRD §3.7: "Opening a `MAJOR` or `SAFETY_CRITICAL` inspection against
        a chassis immediately forces that chassis `UNROADABLE` — this
        roadability flip applies regardless of the chassis's current status,
        short of retirement. If the chassis happened to be `RESERVED` at that
        moment, the reservation is voided as a side effect: the chassis drops
        back to `AVAILABLE` and the pool's reserved and available counts
        adjust."

        Depth check: the creation event (link 1) flips roadability (link 2),
        which releases the reservation (link 3); the appointment and the
        pending transaction are untouched by the cascade.

        Design: Difficulty/transitive_cascade/damage_open_cascade_depth2
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]

        open_damage(tid, ctx["transaction"]["id"], "FRAME", "SAFETY_CRITICAL",
                    250000, chassis_id=chid, as_headers=MP)

        chassis = get_chassis(tid, pid, chid)
        assert chassis["roadability_status"] == "UNROADABLE"
        assert chassis["status"] == "AVAILABLE"
        pool = get_pool(tid, pid)
        assert pool["available_chassis_count"] == 1
        assert pool["reserved_chassis_count"] == 0

    def test_repair_restores_roadability_and_bills_damage(self, api):
        """PRD §3.7: "Marking repaired bills the damage: a `DAMAGE_REPAIR`
        ledger entry for the inspection's `repair_cost_cents` is created
        against the carrier of the linked gate transaction. Marking repaired
        also re-evaluates roadability: if the inspection referenced a chassis
        and no other `OPEN` inspection of `MAJOR` or `SAFETY_CRITICAL` severity
        remains on that chassis, the chassis returns to `ROADABLE` and its
        `last_inspection_at` is stamped with the current logical clock."

        Design: Difficulty/transitive_cascade/damage_open_cascade_depth2
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        chid = ctx["chassis"]["id"]
        tx = open_transaction(tid, ctx["appointment"]["id"])  # chassis stays AVAILABLE
        damage = open_damage(tid, tx["id"], "FRAME", "SAFETY_CRITICAL", 250000,
                             chassis_id=chid, as_headers=MP)
        assert get_chassis(tid, pid, chid)["roadability_status"] == "UNROADABLE"

        validate_success(api.schedule_damage_repair(tid, damage["id"], MP), 200)
        repaired = validate_success(
            api.mark_damage_repaired(tid, damage["id"], MP), 200)
        assert repaired["status"] == "REPAIRED"

        chassis = get_chassis(tid, pid, chid)
        assert chassis["roadability_status"] == "ROADABLE", (
            "No other OPEN major/safety damage remains: roadability is restored")
        assert chassis["status"] == "AVAILABLE"
        assert is_iso8601_timestamp(chassis["last_inspection_at"]), (
            "last_inspection_at is stamped with the current logical clock")

        repairs = list_ledger_entries(tid, entry_kind="DAMAGE_REPAIR",
                                      carrier_id=ctx["carrier"]["id"])
        assert len(repairs) == 1, "Exactly one DAMAGE_REPAIR entry is created"
        assert_ledger_entry(repairs[0])
        assert repairs[0]["amount_cents"] == 250000
        assert repairs[0]["status"] == "OPEN"

    def test_waive_open_damage(self, api):
        """PRD §3.7: "A `TerminalManager` may instead waive an inspection from
        either `OPEN` or `REPAIR_SCHEDULED`; waiver runs the same roadability
        recomputation as repair — restoring `ROADABLE` when no other qualifying
        open damage remains — but creates no billing entry."

        Design: Corner/state_machines/damage_waive_from_open
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        damage = open_damage(tid, ctx["transaction"]["id"], "TIRE", "MINOR",
                             5000, chassis_id=ctx["chassis"]["id"])

        waived = validate_success(api.waive_damage(tid, damage["id"], TM), 200)
        assert waived["status"] == "WAIVED"
        chassis = get_chassis(tid, ctx["pool"]["id"], ctx["chassis"]["id"])
        assert chassis["roadability_status"] == "ROADABLE"


class TestVoidBlockedByDamage:
    def test_void_container_with_open_damage_rejected(self, api):
        """PRD §3.3: "A `TerminalManager` may void a container that is
        `ON_GROUND`, provided no `OPEN` damage inspection references it
        (otherwise `ERR_OPEN_DAMAGE_EXISTS`)."

        Design: Corner/validations/container_void_blocked_by_open_damage
        """
        ctx = setup_checked_in_out_appointment()
        tid = ctx["terminal"]["id"]
        tx = open_transaction(tid, ctx["appointment"]["id"])  # no chassis attached
        open_damage(tid, tx["id"], "CONTAINER_DENT", "MINOR", 5000,
                    container_id=ctx["container"]["id"])

        resp = api.void_container(tid, ctx["container"]["id"], TM)
        validate_error(resp, ApiErrorId.ERR_OPEN_DAMAGE_EXISTS)
        assert get_container(tid, ctx["container"]["id"])["status"] == "ON_GROUND"
