"""Make-good loops: preemption-to-reschedule rebirth, and obligation
conservation across the reschedule and issue-credit resolution paths
(PRD §3.6, §3.7, §3.8)."""
from test_helpers import (
    BA,
    TD,
    api_client,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    get_success_data,
    import_as_run_ok,
    list_discrepancies,
    make_billing_admin_headers,
    setup_bookable_station,
    validate_success,
)

SAT_LOG_DATE = "2026-05-02"  # a Saturday


# ---------------------------------------------------------------------------
# Spot make-good cycle: preempted, then reborn via reschedule
# ---------------------------------------------------------------------------

def _setup_preempted_spot_env():
    """SAT clock hour 15 (1 unit / 120s) and hour 16 (2 units / 120s);
    AFTERNOON_DRIVE card 5000/1000 SAT; book share 3.0; PREEMPTIBLE order P
    with p1 at hour 15; FIXED order F preempts it."""
    env = setup_bookable_station(
        weekday="SAT", daypart="AFTERNOON_DRIVE", hour=15,
        capacity_units=1, capacity_seconds=120,
        extra_slots=[{
            "slot_type": "SPOT_BREAK", "hour": 16,
            "capacity_units": 2, "capacity_seconds": 120,
        }],
        base_rate_cents=5000, min_rate_cents=1000,
        share_value=3.0, book_period=("2026-04-01", "2026-06-30"),
    )
    order_p = create_active_order(
        env["station"]["id"], rate_tier="PREEMPTIBLE",
        daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 1}],
    )
    order_f = create_active_order(
        env["station"]["id"], rate_tier="FIXED",
        daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date=SAT_LOG_DATE)
    p1 = book_spot_ok(order_p["id"], log["id"], daypart="AFTERNOON_DRIVE", hour=15)
    book_spot_ok(
        order_f["id"], log["id"], daypart="AFTERNOON_DRIVE", hour=15,
        allow_preemption=True,
    )
    env.update({"order_p": order_p, "order_f": order_f, "log": log, "p1": p1})
    return env


def test_preemption_moves_spot_to_make_good_pending(api):
    """PRD §3.6: "Each victim transitions to `MAKE_GOOD_PENDING` with
    `make_good_reason` `PREEMPTED`". PRD §3.2 pricing: share 3.0 yields x1.00,
    SAT yields x0.85, so the victim booked at round_half_up(5000 x 1.00 x
    0.85) = 4250.

    Design: Difficulty/non_linear_state_machine/spot_make_good_cycle_preempt_then_reschedule
    """
    env = _setup_preempted_spot_env()
    assert env["p1"]["unit_rate_cents"] == 4250, "victim booked at 4250 before preemption"

    p1 = get_success_data(api_client.get_spot(env["p1"]["id"], TD))
    assert p1["status"] == "MAKE_GOOD_PENDING"
    assert p1["make_good_reason"] == "PREEMPTED"


def test_make_good_reschedule_rebirths_successor(api):
    """PRD §3.7: "Rescheduling a spot takes `target_log_id`, `target_daypart`,
    `target_hour`, and `duration_sec`, creates a successor Spot in `SCHEDULED`
    with `makeup_of_spot_id` set to the original's id, computes a fresh
    `unit_rate_cents`, posts a new DEBIT for TRADE orders, and explicitly does
    not count the successor against `daypart_targets`."

    Design: Difficulty/non_linear_state_machine/spot_make_good_cycle_preempt_then_reschedule
    """
    env = _setup_preempted_spot_env()
    successor = get_success_data(
        api_client.reschedule_spot(
            env["p1"]["id"],
            {
                "target_log_id": env["log"]["id"],
                "target_daypart": "AFTERNOON_DRIVE",
                "target_hour": 16,
                "duration_sec": 60,
            },
            TD,
        )
    )
    assert successor["status"] == "SCHEDULED", "successor reborn into SCHEDULED"
    assert successor["makeup_of_spot_id"] == env["p1"]["id"]
    assert successor["unit_rate_cents"] == 4250, (
        "fresh pricing: daypart capacity 3 units, occupied 1 (the preempting spot) "
        "-> u = 1/3 < 0.70 -> x1.00; 5000 x 1.00 x 0.85"
    )

    p1 = get_success_data(api_client.get_spot(env["p1"]["id"], TD))
    assert p1["status"] == "RESOLVED", "make-good loop closed"


# ---------------------------------------------------------------------------
# Obligation conservation across both resolution paths
# ---------------------------------------------------------------------------

def _setup_two_missed_spots_env():
    """Three spots booked at hour 6; the import airs only the first, so two
    obligations (MISSED) with two discrepancies result. The log is then
    reopened to LOCKED so make-good resolution is posture-legal."""
    env = setup_bookable_station(
        weekday="MON", daypart="MORNING_DRIVE", hour=6,
        capacity_units=10, capacity_seconds=600,
        extra_slots=[{
            "slot_type": "SPOT_BREAK", "hour": 7,
            "capacity_units": 10, "capacity_seconds": 600,
        }],
        base_rate_cents=1000, min_rate_cents=100,
    )
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 3}]
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    s1, s2, s3 = (book_spot_ok(order["id"], log["id"]) for _ in range(3))
    import_as_run_ok(log["id"], aired_spot_ids=[s1["id"]])
    env.update({"order": order, "log": log, "s1": s1, "s2": s2, "s3": s3})
    return env


def _reopen_to_locked(log_id):
    get_success_data(api_client.begin_reconciliation(log_id, TD))
    reopened = get_success_data(api_client.reopen_log(log_id, TD))
    assert reopened["posture"] == "LOCKED"


def test_make_good_obligations_created_one_per_miss(api):
    """PRD §3.7: "The system enforces a make-good conservation invariant after
    every spot and live-read transition: the count of spots in
    `MAKE_GOOD_PENDING` plus the count `RESOLVED` always equals the count of
    `make_good_reason` `PREEMPTED` plus the count `MISSED` — every preemption
    or miss creates exactly one obligation and every obligation closes exactly
    once."

    Design: Difficulty/compensating_invariant/make_good_obligations_conserve_across_resolution_paths
    """
    env = _setup_two_missed_spots_env()
    s2 = get_success_data(api_client.get_spot(env["s2"]["id"], TD))
    s3 = get_success_data(api_client.get_spot(env["s3"]["id"], TD))
    for spot in (s2, s3):
        assert spot["status"] == "MAKE_GOOD_PENDING"
        assert spot["make_good_reason"] == "MISSED"
    # Invariant after import: 2 pending + 0 resolved == 2 missed + 0 preempted.
    pending = sum(1 for s in (s2, s3) if s["status"] == "MAKE_GOOD_PENDING")
    assert pending == 2

    discrepancies = list_discrepancies(log_id=env["log"]["id"])
    assert len(discrepancies) == 2
    assert all(d["discrepancy_kind"] == "MISSED_SPOT" for d in discrepancies)
    assert all(d["status"] == "UNRESOLVED" for d in discrepancies)


def test_make_good_obligations_conserve_across_resolution_paths(api):
    """PRD §3.7: "In both cases, the linked `MISSED_SPOT` or `MISSED_READ`
    Discrepancy auto-transitions `UNRESOLVED → RESOLVED`." and "**Issue-credit**
    — by a `BillingAdmin`, optionally carrying a `note` — closes the obligation
    with no successor". On quotas, PRD §3.7: "and explicitly does not count the
    successor against `daypart_targets`".

    Design: Difficulty/compensating_invariant/make_good_obligations_conserve_across_resolution_paths
    """
    env = _setup_two_missed_spots_env()
    log_id = env["log"]["id"]
    _reopen_to_locked(log_id)

    # Path 1: reschedule s2 -> successor at hour 7.
    successor = get_success_data(
        api_client.reschedule_spot(
            env["s2"]["id"],
            {
                "target_log_id": log_id,
                "target_daypart": "MORNING_DRIVE",
                "target_hour": 7,
                "duration_sec": 60,
            },
            TD,
        )
    )
    assert successor["makeup_of_spot_id"] == env["s2"]["id"]
    assert successor["status"] == "SCHEDULED"

    # Path 2: issue-credit s3 (no successor).
    credited = get_success_data(
        api_client.issue_spot_credit(
            env["s3"]["id"], {"note": "credit instead of make-good"},
            make_billing_admin_headers("ba-1"),
        )
    )
    assert credited["status"] == "RESOLVED"

    s2 = get_success_data(api_client.get_spot(env["s2"]["id"], TD))
    assert s2["status"] == "RESOLVED"

    # Final invariant: 0 pending + 2 resolved == 2 missed + 0 preempted.
    states = [
        get_success_data(api_client.get_spot(sid, TD))
        for sid in (env["s2"]["id"], env["s3"]["id"])
    ]
    pending = sum(1 for s in states if s["status"] == "MAKE_GOOD_PENDING")
    resolved = sum(1 for s in states if s["status"] == "RESOLVED")
    missed = sum(1 for s in states if s["make_good_reason"] == "MISSED")
    assert (pending, resolved) == (0, 2)
    assert pending + resolved == missed, "obligations conserved exactly"

    log = get_success_data(api_client.get_log(log_id, TD))
    assert log["unresolved_discrepancy_count"] == 0, (
        "both discrepancies auto-resolved by the obligation cascade"
    )

    order = get_success_data(api_client.get_order(env["order"]["id"], TD))
    # Only s1 (AIRED) counts; the successor is exempt from daypart_targets.
    assert order["units_scheduled"] == 1, "successor spot does not consume daypart_targets"
