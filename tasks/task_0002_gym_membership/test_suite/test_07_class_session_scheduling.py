"""Class session scheduling: equipment, trainer overlap, maintenance (PRD §3.5)."""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    assert_class_session,
    create_class_session_payload,
    create_equipment_pool,
    discover_or_create_store,
    iso_utc,
    register_trainer,
    schedule_class_session,
    setup_equipment_pool_saturated,
    validate_error,
    validate_success,
)


class TestScheduleHappyPath:

    def test_basic_session_created_in_scheduled(self, api):
        """PRD §3.5: "The new session begins in status SCHEDULED, and
        reserved_seat_count is initialised to zero."

        Claim: a freshly scheduled session has status=SCHEDULED, reserved_seat_count=0.
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"])
        session = schedule_class_session(
            store, trainer, class_type="YOGA", capacity=10, starts_in_hours=48
        )
        assert_class_session(session)
        assert session["status"] == "SCHEDULED"
        assert session["reserved_seat_count"] == 0
        assert session["minimum_tier"] == "BASIC"  # PRD §3.5 default


class TestEquipmentCapacity:

    def test_equipment_pool_overflow_rejected(self, api):
        """PRD §3.5: "the sum of equipment_units_required across all SCHEDULED or
        LOCKED class sessions whose [starts_at, ends_at) half-open window overlaps
        the requested session's window must remain at or below the pool's
        total_units... A violation of either clause is rejected with
        ERR_EQUIPMENT_UNAVAILABLE."

        Claim: scheduling a session that pushes overlapping units above total_units
        → ERR_EQUIPMENT_UNAVAILABLE.
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        # Sliding-window overflow: new session overlaps the saturated window by 30 min.
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_start = datetime.fromisoformat(scen["starts_at"].replace("Z", "+00:00"))
        overlap_start = iso_utc(existing_start + timedelta(minutes=30))
        overlap_end = iso_utc(existing_start + timedelta(minutes=90))
        payload = create_class_session_payload(
            class_type="SPIN",
            trainer_id=new_trainer["id"],
            starts_at=overlap_start,
            ends_at=overlap_end,
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=1,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")

    def test_zero_units_required_bypasses_equipment_check(self, api):
        """PRD §3.5: "equipment_units_required defaults to zero." and PRD §3.5's
        capacity invariant says "the sum of equipment_units_required across all
        SCHEDULED or LOCKED class sessions whose [starts_at, ends_at) half-open
        window overlaps the requested session's window must remain at or below
        the pool's total_units" — when the candidate's units required is zero,
        even a fully-saturated pool can host it (the constraint is satisfied).

        Claim: scheduling with equipment_units_required=0 against a saturated pool
        succeeds (201).
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_start = datetime.fromisoformat(scen["starts_at"].replace("Z", "+00:00"))
        payload = create_class_session_payload(
            class_type="YOGA",
            trainer_id=new_trainer["id"],
            starts_at=iso_utc(existing_start),
            ends_at=iso_utc(existing_start + timedelta(minutes=60)),
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=0,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        data = validate_success(res, 201)
        assert_class_session(data)

    def test_maintenance_window_blocks_overlap(self, api):
        """PRD §3.5: "the requested window must not overlap the pool's
        [maintenance_window_start, maintenance_window_end) half-open maintenance
        window even partially. A violation of either clause is rejected with
        ERR_EQUIPMENT_UNAVAILABLE."

        Claim: a session whose window partially overlaps the pool's maintenance
        window → ERR_EQUIPMENT_UNAVAILABLE.
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"])
        now = datetime.now(timezone.utc)
        maint_start = iso_utc(now + timedelta(hours=48))
        maint_end = iso_utc(now + timedelta(hours=50))
        pool = create_equipment_pool(
            store,
            equipment_type="SPIN_BIKE",
            total_units=5,
            maintenance_window_start=maint_start,
            maintenance_window_end=maint_end,
        )
        # Session overlaps maintenance by 30 min.
        sess_start = iso_utc(now + timedelta(hours=49, minutes=30))
        sess_end = iso_utc(now + timedelta(hours=50, minutes=30))
        payload = create_class_session_payload(
            class_type="SPIN",
            trainer_id=trainer["id"],
            starts_at=sess_start,
            ends_at=sess_end,
            capacity=5,
            equipment_pool_id=pool["id"],
            equipment_units_required=1,
        )
        res = api.create_class_session(
            store["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")
