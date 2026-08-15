"""Composite setup helpers.

The interesting PRD claims require the system to be in a state that takes
5-15 API calls to reach (terminal + slots + arrived train + grounded container
+ pool + carrier + membership + appointment + check-in + reservation +
transaction). These helpers encapsulate those preambles so tests can focus on
assertions. All setup steps use get_success_data() so failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULTS,
    T_CHECKIN,
    T_GROUND,
    T_TRAIN_DEPARTURE,
    T_WINDOW_END,
    T_WINDOW_START,
)
from .factories import (
    apply_ledger_payload,
    check_in_payload,
    create_appointment_payload,
    create_carrier_payload,
    create_chassis_payload,
    create_container_payload,
    create_damage_payload,
    create_membership_payload,
    create_pool_payload,
    create_slot_payload,
    create_terminal_payload,
    create_train_payload,
    ground_container_payload,
    load_flip_credit_payload,
    reserve_chassis_payload,
)
from .test_users import TEST_USERS

TM = TEST_USERS["terminal_manager_headers"]
PA = TEST_USERS["pool_administrator_headers"]
YP = TEST_USERS["yard_planner_headers"]
RC = TEST_USERS["rail_coordinator_headers"]
GS = TEST_USERS["gate_supervisor_headers"]
GC = TEST_USERS["gate_clerk_headers"]
MP = TEST_USERS["maintenance_planner_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Primitive building blocks (single API call each, lenient validation)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Move the logical server clock (PRD §2.4). Returns current_utc."""
    return get_success_data(api_client.set_clock(to_iso8601, TM))


def create_terminal(**overrides):
    return get_success_data(
        api_client.create_terminal(create_terminal_payload(**overrides), TM))


def get_terminal(tid):
    return get_success_data(api_client.get_terminal(tid, TM))


def create_slot(tid, slot_code=DEFAULTS["SLOT_CODE"], row=DEFAULTS["SLOT_ROW"],
                tier_max=DEFAULTS["TIER_MAX"]):
    return get_success_data(api_client.create_slot(
        tid, create_slot_payload(slot_code=slot_code, row=row, tier_max=tier_max),
        YP))


def create_slots(tid, count, row="A", tier_max=DEFAULTS["TIER_MAX"]):
    """Create `count` slots A-01-1.. and return them in creation order."""
    return [create_slot(tid, slot_code=f"{row}-{i:02d}-1", row=row, tier_max=tier_max)
            for i in range(1, count + 1)]


def create_pool(tid, pool_code=DEFAULTS["POOL_CODE"]):
    return get_success_data(
        api_client.create_pool(tid, create_pool_payload(pool_code=pool_code), PA))


def get_pool(tid, pid):
    return get_success_data(api_client.get_pool(tid, pid, PA))


def create_chassis(tid, pid, chassis_number=DEFAULTS["CHASSIS_NUMBER"]):
    return get_success_data(api_client.create_chassis(
        tid, pid, create_chassis_payload(chassis_number=chassis_number), PA))


def get_chassis(tid, pid, cid):
    return get_success_data(api_client.get_chassis(tid, pid, cid, MP))


def create_carrier(scac_code=DEFAULTS["SCAC_CODE"],
                   carrier_name=DEFAULTS["CARRIER_NAME"],
                   billing_credit_limit_cents=DEFAULTS["CREDIT_LIMIT_CENTS"]):
    return get_success_data(api_client.create_carrier(
        create_carrier_payload(
            scac_code=scac_code, carrier_name=carrier_name,
            billing_credit_limit_cents=billing_credit_limit_cents),
        TM))


def get_carrier(carrier_id):
    return get_success_data(api_client.get_carrier(carrier_id, BC))


def enroll_carrier(tid, pid, carrier_id):
    """Create an ACTIVE ChassisMembership for the carrier on the pool."""
    return get_success_data(api_client.create_membership(
        tid, pid, create_membership_payload(carrier_id), PA))


def get_membership(tid, pid, mid):
    return get_success_data(api_client.get_membership(tid, pid, mid, PA))


def load_flip_credit(tid, pid, mid, credit_cents):
    return get_success_data(api_client.load_flip_credit(
        tid, pid, mid, load_flip_credit_payload(credit_cents), BC))


def create_train(tid, scheduled_departure_utc=T_TRAIN_DEPARTURE,
                 train_symbol=DEFAULTS["TRAIN_SYMBOL"]):
    return get_success_data(api_client.create_train(
        tid, create_train_payload(
            train_symbol=train_symbol,
            scheduled_departure_utc=scheduled_departure_utc),
        RC))


def create_arrived_train(tid, scheduled_departure_utc=T_TRAIN_DEPARTURE,
                         train_symbol=DEFAULTS["TRAIN_SYMBOL"]):
    train = create_train(tid, scheduled_departure_utc, train_symbol)
    return get_success_data(api_client.mark_train_arrived(tid, train["id"], RC))


def get_train(tid, trid):
    return get_success_data(api_client.get_train(tid, trid, RC))


def register_container(tid, planned_train_id,
                       container_number=DEFAULTS["CONTAINER_NUMBER"]):
    return get_success_data(api_client.create_container(
        tid, create_container_payload(
            planned_train_id, container_number=container_number), RC))


def get_container(tid, cid):
    return get_success_data(api_client.get_container(tid, cid, YP))


def ground_container(tid, container_id):
    """Ground a container, threading the terminal's current OCC version."""
    version = get_terminal(tid)["version"]
    return get_success_data(api_client.ground_container(
        tid, container_id, ground_container_payload(version), YP))


def get_slot(tid, sid):
    return get_success_data(api_client.get_slot(tid, sid, YP))


def book_appointment(tid, carrier_id, container_id, direction,
                     window_start_utc=T_WINDOW_START, window_end_utc=T_WINDOW_END):
    return get_success_data(api_client.create_appointment(
        tid, create_appointment_payload(
            carrier_id, container_id, direction, window_start_utc, window_end_utc),
        GS))


def get_appointment(tid, aid):
    return get_success_data(api_client.get_appointment(tid, aid, GC))


def check_in(tid, appointment_id, driver_id=DEFAULTS["DRIVER_ID"]):
    return get_success_data(api_client.check_in_appointment(
        tid, appointment_id, check_in_payload(driver_id), GC))


def reserve_chassis(tid, pid, chassis_id, appointment_id):
    """Reserve a chassis, threading the pool's current OCC version."""
    version = get_pool(tid, pid)["version"]
    return get_success_data(api_client.reserve_chassis(
        tid, pid, chassis_id,
        reserve_chassis_payload(appointment_id, version), GS))


def open_transaction(tid, appointment_id, driver_id=DEFAULTS["DRIVER_ID"],
                     gate_lane=DEFAULTS["GATE_LANE"], chassis_id=None):
    payload = {"appointment_id": appointment_id, "driver_id": driver_id,
               "gate_lane": gate_lane}
    if chassis_id is not None:
        payload["chassis_id"] = chassis_id
    return get_success_data(api_client.create_transaction(tid, payload, GC))


def get_transaction(tid, txid):
    return get_success_data(api_client.get_transaction(tid, txid, GC))


def complete_transaction(tid, txid):
    return get_success_data(api_client.complete_transaction(tid, txid, GC))


def reject_transaction(tid, txid):
    return get_success_data(api_client.reject_transaction(tid, txid, GC))


def open_damage(tid, gate_transaction_id, damage_kind, severity,
                repair_cost_cents, chassis_id=None, container_id=None,
                as_headers=None):
    return get_success_data(api_client.create_damage(
        tid, create_damage_payload(
            gate_transaction_id, damage_kind, severity, repair_cost_cents,
            chassis_id=chassis_id, container_id=container_id),
        as_headers or GC))


def list_ledger_entries(tid, **filters):
    params = {k: v for k, v in filters.items() if v is not None}
    params.setdefault("limit", 100)
    return get_success_data(api_client.list_ledger_entries(tid, BC, params=params))


def get_ledger_entry(tid, lid):
    return get_success_data(api_client.get_ledger_entry(tid, lid, BC))


def apply_ledger_payment(tid, lid, apply_cents, carrier_id):
    """Apply a payment, threading the carrier's current OCC version."""
    version = get_carrier(carrier_id)["version"]
    return get_success_data(api_client.apply_ledger_payment(
        tid, lid, apply_ledger_payload(apply_cents, version), BC))


def run_ops(tid):
    return get_success_data(api_client.run_ops(tid, TM))


# ---------------------------------------------------------------------------
# Tier 1-2: terminal + yard + train + container hierarchies
# ---------------------------------------------------------------------------

def setup_terminal_with_slots(yard_slot_count=20, num_slots=1, **terminal_overrides):
    """Terminal plus `num_slots` EMPTY yard slots. Returns (terminal, slots)."""
    terminal = create_terminal(yard_slot_count=yard_slot_count, **terminal_overrides)
    slots = create_slots(terminal["id"], num_slots)
    return terminal, slots


def setup_grounded_container(*, gate_free_hours=48, ground_clock=T_GROUND,
                             yard_slot_count=20, num_slots=1,
                             train_departure=T_TRAIN_DEPARTURE,
                             container_number=DEFAULTS["CONTAINER_NUMBER"],
                             **terminal_overrides):
    """Terminal + slot(s) + ARRIVED train + one grounded (ON_GROUND) container.

    Returns dict(terminal, slots, train, container).
    """
    terminal, slots = setup_terminal_with_slots(
        yard_slot_count=yard_slot_count, num_slots=num_slots,
        gate_free_hours=gate_free_hours, **terminal_overrides)
    tid = terminal["id"]
    train = create_arrived_train(tid, scheduled_departure_utc=train_departure)
    container = register_container(tid, train["id"], container_number)
    set_clock(ground_clock)
    container = ground_container(tid, container["id"])
    return {"terminal": get_terminal(tid), "slots": slots, "train": train,
            "container": container}


def setup_congested_terminal():
    """Terminal in CONGESTED posture: yard_slot_count=10 (congestion threshold
    floor(10 * 0.15) = 1) with nine of ten slots occupied, leaving
    yard_slots_free == 1 <= threshold while still > 0.

    Also stands up a pool, carrier with ACTIVE membership, and a tenth
    container still INBOUND_TRAIN for booking attempts.
    Returns dict(terminal, train, pool, carrier, membership, spare_container).
    """
    terminal, slots = setup_terminal_with_slots(yard_slot_count=10, num_slots=10)
    tid = terminal["id"]
    train = create_arrived_train(tid)
    set_clock(T_GROUND)
    for i in range(9):
        container = register_container(tid, train["id"], f"C00000000{i + 1:02d}")
        ground_container(tid, container["id"])
    spare = register_container(tid, train["id"], "C0000000010")
    pool = create_pool(tid)
    carrier = create_carrier()
    membership = enroll_carrier(tid, pool["id"], carrier["id"])
    terminal = get_terminal(tid)
    assert terminal["posture"] == "CONGESTED", (
        f"Setup failed: expected CONGESTED posture, got {terminal['posture']} "
        f"(free={terminal['yard_slots_free']})")
    return {"terminal": terminal, "slots": slots, "train": train, "pool": pool,
            "carrier": carrier, "membership": membership, "spare_container": spare}


def setup_full_terminal(yard_slot_count=1):
    """Terminal in CLOSED posture: every yard slot consumed by a grounded
    container (yard_slots_free == 0). One extra container remains
    INBOUND_TRAIN for probing ground attempts.
    Returns dict(terminal, slots, train, grounded, spare_container)."""
    terminal, slots = setup_terminal_with_slots(
        yard_slot_count=yard_slot_count, num_slots=yard_slot_count)
    tid = terminal["id"]
    train = create_arrived_train(tid)
    set_clock(T_GROUND)
    grounded = []
    for i in range(yard_slot_count):
        container = register_container(tid, train["id"], f"C{i + 1:010d}")
        grounded.append(ground_container(tid, container["id"]))
    spare = register_container(tid, train["id"], "C0000000099")
    terminal = get_terminal(tid)
    assert terminal["posture"] == "CLOSED", (
        f"Setup failed: expected CLOSED posture, got {terminal['posture']} "
        f"(free={terminal['yard_slots_free']})")
    return {"terminal": terminal, "slots": slots, "train": train,
            "grounded": grounded, "spare_container": spare}


# ---------------------------------------------------------------------------
# Tier 3: gate pipeline — appointment, check-in, reservation, transaction
# ---------------------------------------------------------------------------

def setup_booked_out_appointment(*, flip_credit_cents=0,
                                 gate_free_hours=48,
                                 per_diem_rate_cents=15000,
                                 storage_rate_cents=8000,
                                 flip_fee_cents=5000,
                                 rail_cutoff_minutes=60,
                                 yard_slot_count=20,
                                 train_departure=T_TRAIN_DEPARTURE,
                                 ground_clock=T_GROUND,
                                 window_start=T_WINDOW_START,
                                 window_end=T_WINDOW_END,
                                 booking_clock=T_CHECKIN,
                                 driver_id=DEFAULTS["DRIVER_ID"]):
    """Full chain up to a BOOKED OUT appointment (driver not yet checked in).

    Terminal + slot + pool + chassis (AVAILABLE/ROADABLE) + carrier + ACTIVE
    membership (optionally pre-loaded with flip-fee credit) + ARRIVED train +
    grounded container + booked OUT appointment.

    Returns dict with every resource created along the way.
    """
    terminal = create_terminal(
        gate_free_hours=gate_free_hours, per_diem_rate_cents=per_diem_rate_cents,
        storage_rate_cents=storage_rate_cents, flip_fee_cents=flip_fee_cents,
        rail_cutoff_minutes_before_departure=rail_cutoff_minutes,
        yard_slot_count=yard_slot_count)
    tid = terminal["id"]
    slot = create_slot(tid)
    pool = create_pool(tid)
    chassis = create_chassis(tid, pool["id"])
    carrier = create_carrier()
    membership = enroll_carrier(tid, pool["id"], carrier["id"])
    if flip_credit_cents:
        load_flip_credit(tid, pool["id"], membership["id"], flip_credit_cents)
        membership = get_membership(tid, pool["id"], membership["id"])
    train = create_arrived_train(tid, scheduled_departure_utc=train_departure)
    container = register_container(tid, train["id"])
    set_clock(ground_clock)
    container = ground_container(tid, container["id"])
    set_clock(booking_clock)
    appointment = book_appointment(tid, carrier["id"], container["id"], "OUT",
                                   window_start, window_end)
    return {"terminal": get_terminal(tid), "slot": slot, "pool": pool,
            "chassis": chassis, "carrier": carrier, "membership": membership,
            "train": train, "container": container, "appointment": appointment,
            "driver_id": driver_id}


def setup_checked_in_out_appointment(checkin_clock=T_CHECKIN, **kwargs):
    """setup_booked_out_appointment + driver check-in at `checkin_clock`."""
    ctx = setup_booked_out_appointment(**kwargs)
    tid = ctx["terminal"]["id"]
    set_clock(checkin_clock)
    ctx["appointment"] = check_in(tid, ctx["appointment"]["id"], ctx["driver_id"])
    return ctx


def setup_pending_out_transaction(**kwargs):
    """setup_checked_in_out_appointment + chassis RESERVED + transaction PENDING
    carrying that chassis. Accepts the same keyword overrides."""
    ctx = setup_checked_in_out_appointment(**kwargs)
    tid = ctx["terminal"]["id"]
    ctx["chassis"] = reserve_chassis(
        tid, ctx["pool"]["id"], ctx["chassis"]["id"], ctx["appointment"]["id"])
    ctx["transaction"] = open_transaction(
        tid, ctx["appointment"]["id"], driver_id=ctx["driver_id"],
        chassis_id=ctx["chassis"]["id"])
    return ctx


def setup_completed_out_gate(complete_clock=None, **kwargs):
    """Full out-gate move: pending transaction completed at `complete_clock`
    (defaults to the check-in clock). Returns the context with the COMPLETED
    transaction plus refreshed appointment/chassis/container."""
    ctx = setup_pending_out_transaction(**kwargs)
    tid = ctx["terminal"]["id"]
    if complete_clock is not None:
        set_clock(complete_clock)
    ctx["transaction"] = complete_transaction(tid, ctx["transaction"]["id"])
    ctx["appointment"] = get_appointment(tid, ctx["appointment"]["id"])
    ctx["chassis"] = get_chassis(tid, ctx["pool"]["id"], ctx["chassis"]["id"])
    ctx["container"] = get_container(tid, ctx["container"]["id"])
    ctx["terminal"] = get_terminal(tid)
    ctx["pool"] = get_pool(tid, ctx["pool"]["id"])
    return ctx
