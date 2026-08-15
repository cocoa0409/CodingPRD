"""Offline batch channel: replay idempotency, overbook allowance, sync voids."""
from test_helpers import (
    TEST_USERS,
    admit_online_session,
    get_window,
    offline_payment_record,
    offline_session_record,
    set_clock,
    setup_operating_day,
    sign_waiver,
    upload_batch,
    validate_paginated,
)

MANAGER = TEST_USERS["farm_manager_headers"]
KIOSK = TEST_USERS["kiosk_device_headers"]


class TestBatchReplay:
    def test_offline_batch_replay_is_idempotent(self, api):
        """PRD §3.9: "The first upload decides the batch's fate permanently:
        replaying the same pair returns the stored batch with an identical
        `results` array and applies nothing a second time."

        Design: Corner/cross_cutting_layers/offline_batch_replay_is_idempotent
        """
        world = setup_operating_day(waiver_names=("Ann", "Bob"))
        records = [
            offline_session_record(
                1, "S1", window_id=world["window_id"],
                waiver_id=world["waiver_id"],
                pricing_policy_id=world["policy_id"], party_size=2,
                container_count=1, parking_spaces=1),
            offline_payment_record(2, "P1", session_ref="S1", amount_cents=1500),
        ]
        first = upload_batch("DEV1", "B1", records)
        assert first["status"] == "APPLIED"
        assert first["applied_count"] == 2

        replay = upload_batch("DEV1", "B1", records)
        assert replay["id"] == first["id"], "replay returns the stored batch"
        assert replay["applied_count"] == 2
        assert replay["results"] == first["results"]

        sessions, meta = validate_paginated(api.list_visit_sessions(
            MANAGER, params={"window_id": world["window_id"]}))
        assert meta["total_count"] == 1, "no double-apply"
        assert sessions[0]["total_paid_cents"] == 1500, (
            "the payment applied exactly once")


class TestOfflineOverbookAllowance:
    def test_offline_overbook_allowance_then_conflict(self, api):
        """PRD §3.9: "the session must fit within the offline capacity
        allowance — the window's `picking_capacity_slots` plus an allowance of
        10 extra slots — and the `offline_ref` must never have been seen on any
        session; each of those four failures creates the session directly in
        `VOIDED` with `sync_outcome` `SYNC_CONFLICT`."
        PRD §3.9: "A batch whose records all applied is `APPLIED`; any conflict
        makes it `PARTIALLY_APPLIED`."

        Design: Corner/cross_cutting_layers/offline_overbook_allowance_then_conflict
        """
        names30 = [f"P{i}" for i in range(1, 31)]
        world = setup_operating_day(waiver_names=names30)
        wv_7 = sign_waiver(world["season_id"],
                           [f"Q{i}" for i in range(1, 8)],
                           signer_name="Few", signer_email="few@x.com")
        admit_online_session(world, party_size=30)  # window exactly full

        batch1 = upload_batch("DEV1", "BO1", [offline_session_record(
            1, "S-OB1", window_id=world["window_id"], waiver_id=wv_7["id"],
            pricing_policy_id=world["policy_id"], party_size=4)])
        assert batch1["status"] == "APPLIED", "party 4 fits within 30 + 10"
        assert get_window(world["window_id"])["booked_slots"] == 34

        batch2 = upload_batch("DEV1", "BO2", [offline_session_record(
            1, "S-OB2", window_id=world["window_id"], waiver_id=wv_7["id"],
            pricing_policy_id=world["policy_id"], party_size=7)])
        assert batch2["status"] == "PARTIALLY_APPLIED"
        assert batch2["applied_count"] == 0
        assert batch2["conflict_count"] == 1, "34 + 7 = 41 > 40"

        voided, _ = validate_paginated(api.list_visit_sessions(
            MANAGER, params={"window_id": world["window_id"],
                             "visit_status": "VOIDED"}))
        assert voided[0]["sync_outcome"] == "SYNC_CONFLICT"
        assert get_window(world["window_id"])["booked_slots"] == 34, (
            "VOIDED sessions leave the capacity input set")


class TestOfflineWeatherVoid:
    def test_offline_session_against_weather_cancelled_window_voided(self, api):
        """PRD §3.9: "the window must not be `CANCELLED` with `cancel_reason`
        `WEATHER`, the waiver must be valid at apply time (signed,
        version-current, and covering the party per the trio of §2.7), the
        session must fit within the offline capacity allowance"
        PRD §3.9: "a session that landed `VOIDED` marks the payment `FAILED`
        and the record conflicts; otherwise the payment settles to `SETTLED`
        and the record applies."

        Design: Corner/cross_cutting_layers/offline_session_against_weather_cancelled_window_voided
        """
        world = setup_operating_day()
        set_clock("2026-08-04T11:00:00Z")
        api.close_weather(world["day_id"], MANAGER)  # zero on-site sessions

        batch = upload_batch("DEV1", "BW1", [
            offline_session_record(
                1, "S-W", window_id=world["window_id"],
                waiver_id=world["waiver_id"],
                pricing_policy_id=world["policy_id"], party_size=1),
            offline_payment_record(2, "P-W", session_ref="S-W", amount_cents=650),
        ])
        assert batch["status"] == "PARTIALLY_APPLIED"
        assert batch["applied_count"] == 0
        assert batch["conflict_count"] == 2

        sessions, _ = validate_paginated(api.list_visit_sessions(
            MANAGER, params={"window_id": world["window_id"]}))
        assert sessions[0]["visit_status"] == "VOIDED"
        assert sessions[0]["sync_outcome"] == "SYNC_CONFLICT"

        payments, _ = validate_paginated(api.list_payments(
            MANAGER, params={"session_id": sessions[0]["id"]}))
        assert payments[0]["status"] == "FAILED", (
            "a voided session collects nothing")

        window = get_window(world["window_id"])
        assert window["status"] == "CANCELLED"
        assert window["cancel_reason"] == "WEATHER"
