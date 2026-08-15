"""Composite setup helpers.

Each helper replays a multi-step PRD workflow from an empty database and
returns the created resources as plain dicts. Setup calls use
get_success_data() so a failed precondition surfaces as a clear
"Setup failed" message instead of a confusing assertion error.

Ownership rule: any call restricted to the owning BackgroundActor
(accept/decline/dispute/withdraw) is made with make_actor_headers(actor["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_actor_payload,
    create_booking_payload,
    create_bump_payload,
    create_casting_call_payload,
    create_holding_area_payload,
    create_payroll_batch_payload,
    create_production_payload,
    create_ratio_waiver_payload,
    create_standby_entry_payload,
    create_time_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_actor_headers,
    make_associate_headers,
    make_director_headers,
    make_payroll_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
UNION_REP = TEST_USERS["union_rep_headers"]

SHOOT_DATE = TEST_DEFAULTS["SHOOT_DATE"]              # "2026-08-10"
CALL_TIME = TEST_DEFAULTS["GENERAL_CALL_TIME"]        # "2026-08-10T07:00:00Z"
PRE_SHOOT_CLOCK = TEST_DEFAULTS["PRE_SHOOT_CLOCK"]    # "2026-08-10T06:55:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource builders and state transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (AgencyAdmin). Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_production(active=True, **overrides):
    """Create a Production; activate it when active=True. Returns Production."""
    prod = get_success_data(
        api_client.create_production(create_production_payload(**overrides), ADMIN)
    )
    if active:
        prod = get_success_data(api_client.activate_production(prod["id"], ADMIN))
    return prod


def create_actor(union_status="NONUNION", verify=True, **overrides):
    """Register a BackgroundActor; verify to ELIGIBLE when verify=True."""
    actor = get_success_data(
        api_client.create_actor(
            create_actor_payload(union_status=union_status, **overrides), ADMIN
        )
    )
    if verify:
        actor = get_success_data(api_client.verify_actor(actor["id"], ADMIN))
    return actor


def create_casting_call(production_id, publish=False, **overrides):
    """Create a CastingCall (DRAFT); publish when publish=True."""
    call = get_success_data(
        api_client.create_casting_call(
            create_casting_call_payload(production_id, **overrides), DIRECTOR
        )
    )
    if publish:
        call = get_success_data(api_client.publish_casting_call(call["id"], DIRECTOR))
    return call


def publish_call(call_id):
    return get_success_data(api_client.publish_casting_call(call_id, DIRECTOR))


def lock_call(call_id):
    return get_success_data(api_client.lock_casting_call(call_id, DIRECTOR))


def start_shooting(call_id, pre_shoot_clock=PRE_SHOOT_CLOCK):
    """Set the clock onto the shoot date, then start shooting. Returns the call."""
    set_clock(pre_shoot_clock)
    return get_success_data(api_client.start_shooting(call_id, ASSOCIATE))


def create_booking(call_id, actor_id, call_time=None):
    """Create a booking (OFFERED). Consumes one slot."""
    payload = create_booking_payload(call_id, actor_id)
    if call_time is not None:
        payload["call_time"] = call_time
    return get_success_data(api_client.create_booking(payload, ASSOCIATE))


def accept_booking(booking_id, actor_id):
    """Owner-actor accept: OFFERED -> CONFIRMED."""
    return get_success_data(
        api_client.accept_booking(booking_id, make_actor_headers(actor_id))
    )


def decline_booking(booking_id, actor_id):
    return get_success_data(
        api_client.decline_booking(booking_id, make_actor_headers(actor_id))
    )


def confirm_booking(call_id, actor_id, call_time=None):
    """Create + accept. Returns the CONFIRMED booking."""
    booking = create_booking(call_id, actor_id, call_time=call_time)
    return accept_booking(booking["id"], actor_id)


def create_standby_entry(call_id, actor_id):
    return get_success_data(
        api_client.create_standby_entry(
            create_standby_entry_payload(call_id, actor_id), ASSOCIATE
        )
    )


def create_holding_area(call_id, capacity=1, **overrides):
    return get_success_data(
        api_client.create_holding_area(
            create_holding_area_payload(call_id, capacity=capacity, **overrides),
            ASSOCIATE,
        )
    )


def create_ratio_waiver(call_id, union_slot_reduction=1, requester="dir-1", **overrides):
    return get_success_data(
        api_client.create_ratio_waiver(
            create_ratio_waiver_payload(
                call_id, union_slot_reduction=union_slot_reduction, **overrides
            ),
            make_director_headers(requester),
        )
    )


def check_in_booking(booking_id, at=None, holding_area_id=None):
    """Optionally set the logical clock, then check in (CONFIRMED -> CHECKED_IN)."""
    if at is not None:
        set_clock(at)
    payload = {}
    if holding_area_id is not None:
        payload["holding_area_id"] = holding_area_id
    return get_success_data(api_client.check_in_booking(booking_id, payload, ASSOCIATE))


def add_time_event(booking_id, event_type, occurred_at, corrects_event_id=None):
    payload = create_time_event_payload(booking_id, event_type, occurred_at)
    if corrects_event_id is not None:
        payload["corrects_event_id"] = corrects_event_id
    return get_success_data(api_client.create_time_event(payload, ASSOCIATE))


def wrap_out_booking(booking_id, at=None):
    """Optionally set the logical clock, then wrap out (CHECKED_IN -> WRAPPED)."""
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.wrap_out_booking(booking_id, ASSOCIATE))


def get_voucher_for_booking(booking_id):
    """Exactly one voucher exists per booking (PRD §3.4). Returns it."""
    data = get_success_data(
        api_client.list_vouchers(ASSOCIATE, params={"booking_id": booking_id})
    )
    assert len(data) == 1, f"Expected exactly 1 voucher for booking, got {len(data)}"
    return data[0]


def issue_voucher(voucher_id, issuer="assoc-1"):
    return get_success_data(
        api_client.issue_voucher(voucher_id, make_associate_headers(issuer))
    )


def create_bump(voucher_id, amount_cents=2500, requester="assoc-1", **overrides):
    return get_success_data(
        api_client.create_bump_adjustment(
            create_bump_payload(voucher_id, amount_cents=amount_cents, **overrides),
            make_associate_headers(requester),
        )
    )


def create_batch(production_id, creator="pc-1", **overrides):
    return get_success_data(
        api_client.create_payroll_batch(
            create_payroll_batch_payload(production_id, **overrides),
            make_payroll_headers(creator),
        )
    )


def add_batch_item(batch_id, voucher_id, expected_batch_version, operator="pc-1"):
    return get_success_data(
        api_client.add_batch_item(
            batch_id,
            {
                "voucher_id": voucher_id,
                "expected_batch_version": expected_batch_version,
            },
            make_payroll_headers(operator),
        )
    )


def submit_batch(batch_id, operator="pc-1"):
    return get_success_data(api_client.submit_batch(batch_id, make_payroll_headers(operator)))


def get_case_for_call(call_id):
    data = get_success_data(
        api_client.list_replacement_cases(ASSOCIATE, params={"casting_call_id": call_id})
    )
    assert len(data) >= 1, f"Expected a replacement case for the call, got {len(data)}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2/3: day-flow composites (PUBLISHED -> CONFIRMED -> SHOOTING -> WRAPPED)
# ---------------------------------------------------------------------------

def setup_published_call(union_slots=0, nonunion_slots=1, **call_overrides):
    """Production ACTIVE + CastingCall PUBLISHED. Returns (production, call)."""
    prod = create_production(active=True)
    call = create_casting_call(
        prod["id"],
        publish=True,
        union_slots=union_slots,
        nonunion_slots=nonunion_slots,
        **call_overrides,
    )
    return prod, call


def setup_confirmed_booking(
    union_status="NONUNION", union_slots=0, nonunion_slots=1, **call_overrides
):
    """Production ACTIVE, actor ELIGIBLE, call PUBLISHED, booking CONFIRMED.
    Returns (production, call, actor, booking)."""
    prod, call = setup_published_call(union_slots, nonunion_slots, **call_overrides)
    actor = create_actor(union_status)
    booking = confirm_booking(call["id"], actor["id"])
    return prod, call, actor, booking


def setup_shooting_booking(
    union_status="NONUNION",
    union_slots=0,
    nonunion_slots=1,
    check_in=False,
    check_in_at=CALL_TIME,
    **call_overrides,
):
    """Full pre-day flow through SHOOTING: production ACTIVE, actor ELIGIBLE,
    call PUBLISHED -> booking CONFIRMED -> call LOCKED -> clock on shoot date ->
    SHOOTING; optionally checks the booking in at check_in_at.
    Returns (production, call, actor, booking)."""
    prod, call, actor, booking = setup_confirmed_booking(
        union_status, union_slots, nonunion_slots, **call_overrides
    )
    lock_call(call["id"])
    start_shooting(call["id"])
    if check_in:
        booking = check_in_booking(booking["id"], at=check_in_at)
    return prod, call, actor, booking


def setup_wrapped_day(
    union_status="NONUNION",
    union_slots=0,
    nonunion_slots=1,
    check_in_at=CALL_TIME,
    meals=(),
    wrap_at="2026-08-10T16:00:00Z",
    **call_overrides,
):
    """Complete workday: booking CHECKED_IN, meal events appended, WRAPPED,
    DRAFT voucher auto-created. `meals` is a list of (meal_out, meal_in) pairs.
    Returns (production, call, actor, booking, voucher)."""
    prod, call, actor, booking = setup_shooting_booking(
        union_status, union_slots, nonunion_slots, check_in=True,
        check_in_at=check_in_at, **call_overrides,
    )
    for meal_out, meal_in in meals:
        add_time_event(booking["id"], "MEAL_OUT", meal_out)
        add_time_event(booking["id"], "MEAL_IN", meal_in)
    booking = wrap_out_booking(booking["id"], at=wrap_at)
    voucher = get_voucher_for_booking(booking["id"])
    return prod, call, actor, booking, voucher


def setup_issued_voucher(issuer="assoc-1", **kwargs):
    """setup_wrapped_day + issue. Returns (production, call, actor, booking, voucher)."""
    prod, call, actor, booking, voucher = setup_wrapped_day(**kwargs)
    voucher = issue_voucher(voucher["id"], issuer=issuer)
    return prod, call, actor, booking, voucher


def setup_open_batch_with_voucher(operator="pc-1", **kwargs):
    """Issued voucher + OPEN batch + voucher added.
    Returns (production, call, actor, booking, voucher, batch)."""
    prod, call, actor, booking, voucher = setup_issued_voucher(**kwargs)
    batch = create_batch(prod["id"], creator=operator)
    batch = add_batch_item(
        batch["id"], voucher["id"], expected_batch_version=batch["version"],
        operator=operator,
    )
    return prod, call, actor, booking, voucher, batch


def setup_submitted_batch(operator="pc-1", **kwargs):
    """OPEN batch with the issued voucher, submitted.
    Returns (production, call, actor, booking, voucher, batch)."""
    prod, call, actor, booking, voucher, batch = setup_open_batch_with_voucher(
        operator=operator, **kwargs
    )
    batch = submit_batch(batch["id"], operator=operator)
    return prod, call, actor, booking, voucher, batch


def setup_no_show_case(
    standby_union_statuses=(),
    union_slots=1,
    nonunion_slots=0,
    no_show_clock="2026-08-10T08:05:00Z",
    **call_overrides,
):
    """Shoot-day vacancy: CONFIRMED booking marked NO_SHOW on a SHOOTING call,
    which opens a ReplacementCase (OPEN). Standby entries are registered while
    the call is PUBLISHED, in the order given.
    Returns (production, call, original_actor, booking, case, standby_actors,
    standby_entries)."""
    prod = create_production(active=True)
    call = create_casting_call(
        prod["id"],
        publish=True,
        union_slots=union_slots,
        nonunion_slots=nonunion_slots,
        **call_overrides,
    )
    standby_actors = [create_actor(us) for us in standby_union_statuses]
    standby_entries = [
        create_standby_entry(call["id"], a["id"]) for a in standby_actors
    ]
    actor0 = create_actor("SAG_AFTRA" if union_slots > 0 else "NONUNION")
    booking = confirm_booking(call["id"], actor0["id"])
    lock_call(call["id"])
    start_shooting(call["id"])
    set_clock(no_show_clock)
    booking = get_success_data(api_client.mark_no_show(booking["id"], ASSOCIATE))
    case = get_case_for_call(call["id"])
    return prod, call, actor0, booking, case, standby_actors, standby_entries
