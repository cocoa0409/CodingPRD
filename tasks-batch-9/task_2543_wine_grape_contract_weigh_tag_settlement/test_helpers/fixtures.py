"""Composite setup helpers.

Every helper builds its state from scratch through the documented endpoints — the
database is empty at the start of each test. Setup calls use the lenient
`get_success_data` so a broken precondition surfaces as a setup failure rather
than as a confusing assertion inside a test body.

The producer role's `X-User-ID` is the acting producer's `id`, so every
ownership-gated call threads `make_grower_headers(grower["id"])`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPOINTMENT_WINDOW_END,
    APPOINTMENT_WINDOW_START,
    CLOCK_INITIAL,
    PICK_CALL_ISSUED_AT,
    SAMPLING_RECORDED_AT,
    SAMPLING_WINDOW_END,
    SAMPLING_WINDOW_START,
    TARGET_PICK_AT,
    TEST_DEFAULTS,
    TRUCK_ARRIVAL_AT,
)
from .factories import (
    create_allocation_payload,
    create_delivery_appointment_payload,
    create_grading_payload,
    create_grape_contract_payload,
    create_grower_payload,
    create_lane_payload,
    create_pick_call_payload,
    create_quality_spec_payload,
    create_sampling_crew_payload,
    create_sampling_visit_payload,
    create_vineyard_block_payload,
    create_weigh_tag_payload,
    record_sampling_visit_payload,
    single_installment_plan,
    tare_payload,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_coordinator_headers,
    make_grower_headers,
    make_lab_tech_headers,
    make_manager_headers,
    make_scale_operator_headers,
)

MANAGER = TEST_USERS["manager_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SCALE_OPERATOR = TEST_USERS["scale_operator_headers"]
LAB_TECH = TEST_USERS["lab_tech_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --- The logical harvest clock -------------------------------------------------


def read_clock(headers=None) -> str:
    data = get_success_data(api_client.get_clock(headers or MANAGER))
    return data["current_utc"]


def move_clock(instant: str, headers=None) -> str:
    """Move the logical clock, firing every time-driven transition."""
    data = get_success_data(api_client.set_clock({"current_utc": instant}, headers or MANAGER))
    return data["current_utc"]


def reset_clock(headers=None) -> str:
    return move_clock(CLOCK_INITIAL, headers)


# --- Reference book -----------------------------------------------------------


def create_grower(**overrides) -> dict:
    return get_success_data(api_client.create_grower(create_grower_payload(**overrides), MANAGER))


def suspend_grower(grower_id: str, reason: str = None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.suspend_grower(grower_id, MANAGER, payload))


def reinstate_grower(grower_id: str) -> dict:
    return get_success_data(api_client.reinstate_grower(grower_id, MANAGER))


def read_grower(grower_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_grower(grower_id, headers or MANAGER))


def create_block(grower_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vineyard_block(create_vineyard_block_payload(grower_id, **overrides), MANAGER)
    )


def read_block(block_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_vineyard_block(block_id, headers or MANAGER))


def create_quality_spec(**overrides) -> dict:
    return get_success_data(api_client.create_quality_spec(create_quality_spec_payload(**overrides), MANAGER))


# --- Contract negotiation -----------------------------------------------------


def create_contract(grower_id: str, quality_spec_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_grape_contract(
            create_grape_contract_payload(grower_id, quality_spec_id, **overrides), MANAGER
        )
    )


def offer_contract(contract_id: str, base_price_per_ton_cents: int = None) -> dict:
    payload = {} if base_price_per_ton_cents is None else {"base_price_per_ton_cents": base_price_per_ton_cents}
    return get_success_data(api_client.offer_contract(contract_id, MANAGER, payload))


def counter_contract(contract_id: str, grower_id: str, counter_base_price_per_ton_cents: int) -> dict:
    return get_success_data(
        api_client.counter_contract(
            contract_id,
            {"counter_base_price_per_ton_cents": counter_base_price_per_ton_cents},
            make_grower_headers(grower_id),
        )
    )


def accept_contract(contract_id: str, grower_id: str) -> dict:
    return get_success_data(api_client.accept_contract(contract_id, make_grower_headers(grower_id)))


def read_contract(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_grape_contract(contract_id, headers or MANAGER))


def create_allocation(contract_id: str, block_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_allocation(create_allocation_payload(contract_id, block_id, **overrides), MANAGER)
    )


def read_allocation(allocation_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, headers or MANAGER))


def close_settlement(contract_id: str) -> dict:
    return get_success_data(api_client.close_settlement(contract_id, MANAGER))


def read_settlement_summary(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_settlement_summary(contract_id, headers or MANAGER))


# --- Crush pad, crews and sampling -------------------------------------------


def create_lane(**overrides) -> dict:
    return get_success_data(api_client.create_lane(create_lane_payload(**overrides), MANAGER))


def read_lane(lane_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_lane(lane_id, headers or MANAGER))


def create_crew(**overrides) -> dict:
    return get_success_data(api_client.create_sampling_crew(create_sampling_crew_payload(**overrides), COORDINATOR))


def read_crew(crew_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sampling_crew(crew_id, headers or COORDINATOR))


def book_sampling_visit(
    contract_id: str,
    block_id: str,
    crew_id: str,
    window_start: str = SAMPLING_WINDOW_START,
    window_end: str = SAMPLING_WINDOW_END,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_sampling_visit(
            create_sampling_visit_payload(contract_id, block_id, crew_id, window_start, window_end, **overrides),
            COORDINATOR,
        )
    )


def record_sampling_visit(visit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_sampling_visit(visit_id, record_sampling_visit_payload(**overrides), COORDINATOR)
    )


def read_sampling_visit(visit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sampling_visit(visit_id, headers or COORDINATOR))


# --- Pick calls and appointments ---------------------------------------------


def issue_pick_call(contract_id: str, block_id: str, target_pick_at: str = TARGET_PICK_AT, estimated_tons: float = 45.000, **overrides) -> dict:
    return get_success_data(
        api_client.create_pick_call(
            create_pick_call_payload(contract_id, block_id, target_pick_at, estimated_tons, **overrides),
            COORDINATOR,
        )
    )


def acknowledge_pick_call(pick_call_id: str, grower_id: str) -> dict:
    return get_success_data(api_client.acknowledge_pick_call(pick_call_id, make_grower_headers(grower_id)))


def revise_pick_call(pick_call_id: str, revised_target_pick_at: str, revised_estimated_tons: float = None) -> dict:
    payload = {"revised_target_pick_at": revised_target_pick_at}
    if revised_estimated_tons is not None:
        payload["revised_estimated_tons"] = revised_estimated_tons
    return get_success_data(api_client.revise_pick_call(pick_call_id, payload, COORDINATOR))


def read_pick_call(pick_call_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_pick_call(pick_call_id, headers or COORDINATOR))


def book_appointment(
    pick_call_id: str,
    lane_id: str,
    window_start: str = APPOINTMENT_WINDOW_START,
    window_end: str = APPOINTMENT_WINDOW_END,
    planned_tons: float = 22.000,
    headers=None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                pick_call_id, lane_id, window_start, window_end, planned_tons, **overrides
            ),
            headers or COORDINATOR,
        )
    )


def cancel_appointment(appointment_id: str, reason: str = None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.cancel_delivery_appointment(appointment_id, COORDINATOR, payload))


def read_appointment(appointment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_appointment(appointment_id, headers or COORDINATOR))


# --- Scale house and lab ------------------------------------------------------


def appointment_version(appointment_id: str) -> int:
    return int(read_appointment(appointment_id, SCALE_OPERATOR)["version"])


def weigh_tag_version(tag_id: str) -> int:
    return int(read_weigh_tag(tag_id, LAB_TECH)["version"])


def capture_gross(
    appointment_id: str,
    block_id: str,
    gross_weight_lbs: int,
    expected_appointment_version: int = None,
    headers=None,
) -> dict:
    version = (
        appointment_version(appointment_id)
        if expected_appointment_version is None
        else expected_appointment_version
    )
    return get_success_data(
        api_client.create_weigh_tag(
            create_weigh_tag_payload(appointment_id, block_id, gross_weight_lbs, version),
            headers or SCALE_OPERATOR,
        )
    )


def capture_tare(tag_id: str, tare_weight_lbs: int, headers=None) -> dict:
    return get_success_data(
        api_client.tare_weigh_tag(tag_id, tare_payload(tare_weight_lbs), headers or SCALE_OPERATOR)
    )


def read_weigh_tag(tag_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_weigh_tag(tag_id, headers or SCALE_OPERATOR))


def record_grading(
    tag_id: str,
    brix: float = 24.0,
    ta_gl: float = 6.5,
    ph: float = 3.55,
    rot_pct: float = 2.0,
    mog_pct: float = 1.0,
    expected_weigh_tag_version: int = None,
    headers=None,
) -> dict:
    version = weigh_tag_version(tag_id) if expected_weigh_tag_version is None else expected_weigh_tag_version
    payload = create_grading_payload(
        version, brix=brix, ta_gl=ta_gl, ph=ph, rot_pct=rot_pct, mog_pct=mog_pct
    )
    return get_success_data(api_client.create_grading(tag_id, payload, headers or LAB_TECH))


def dispute_grading(tag_id: str, grower_id: str, reason: str = None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(
        api_client.create_grade_dispute(tag_id, make_grower_headers(grower_id), payload)
    )


def read_grading(grade_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_quality_grade(grade_id, headers or LAB_TECH))


def list_gradings(**filters) -> list:
    return get_success_data(api_client.list_quality_grades(LAB_TECH, params=filters or None))


def list_settlement_lines(**filters) -> list:
    return get_success_data(api_client.list_settlement_lines(MANAGER, params=filters or None))


def list_installments(**filters) -> list:
    return get_success_data(api_client.list_installments(CLERK, params=filters or None))


def read_installment(installment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_installment(installment_id, headers or CLERK))


def pay_installment(installment_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.create_payment(installment_id, {"amount_cents": amount_cents}, CLERK))


# --- Unit conversion helper ---------------------------------------------------


def tons_to_lbs(net_tons: float) -> int:
    """Whole pounds that convert back to `net_tons` at 2000 lbs per ton."""
    return int(round(float(net_tons) * 2000))


# --- Tier 1: reference book ----------------------------------------------------


def setup_reference_book(grower_overrides=None, block_overrides=None, spec_overrides=None) -> dict:
    """One producer, one quality specification and one vineyard block."""
    grower = create_grower(**(grower_overrides or {}))
    spec = create_quality_spec(**(spec_overrides or {}))
    block = create_block(grower["id"], **(block_overrides or {}))
    return {
        "grower": grower,
        "spec": spec,
        "block": block,
        "grower_headers": make_grower_headers(grower["id"]),
    }


# --- Tier 2: contract lifecycle ------------------------------------------------


def setup_drafted_contract(contract_overrides=None, **book_overrides) -> dict:
    """Reference book plus a DRAFT contract with one allocated block."""
    ctx = setup_reference_book(**book_overrides)
    contract = create_contract(ctx["grower"]["id"], ctx["spec"]["id"], **(contract_overrides or {}))
    allocation = create_allocation(contract["id"], ctx["block"]["id"])
    ctx["contract"] = contract
    ctx["allocation"] = allocation
    return ctx


def setup_offered_contract(contract_overrides=None, **book_overrides) -> dict:
    ctx = setup_drafted_contract(contract_overrides, **book_overrides)
    ctx["contract"] = offer_contract(ctx["contract"]["id"])
    return ctx


def setup_active_contract(contract_overrides=None, **book_overrides) -> dict:
    """Walk DRAFT to ACTIVE: allocate a block, offer, then accept as the producer.

    Returns the context dict with the accepted contract, whose tonnage caps,
    renewal window and installment rows have all been derived.
    """
    ctx = setup_offered_contract(contract_overrides, **book_overrides)
    ctx["contract"] = accept_contract(ctx["contract"]["id"], ctx["grower"]["id"])
    ctx["allocation"] = read_allocation(ctx["allocation"]["id"])
    return ctx


# --- Tier 3: harvest chain -----------------------------------------------------


def setup_pick_ready_block(
    ctx: dict,
    measured_brix: float = 24.5,
    measured_rot_pct: float = 1.0,
    sampled_at: str = SAMPLING_RECORDED_AT,
    crew_overrides=None,
) -> dict:
    """Book and record a sampling visit so the block is demonstrably pick-ready."""
    crew = ctx.get("crew") or create_crew(region_code=ctx["grower"]["region_code"], **(crew_overrides or {}))
    visit = book_sampling_visit(ctx["contract"]["id"], ctx["block"]["id"], crew["id"])
    move_clock(sampled_at)
    visit = record_sampling_visit(visit["id"], measured_brix=measured_brix, measured_rot_pct=measured_rot_pct)
    ctx["crew"] = crew
    ctx["visit"] = visit
    return ctx


def setup_issued_pick_call(
    ctx: dict,
    issued_at: str = PICK_CALL_ISSUED_AT,
    target_pick_at: str = TARGET_PICK_AT,
    estimated_tons: float = 45.000,
) -> dict:
    """Contract ACTIVE + pick-ready block, then issue the call from `issued_at`."""
    if "visit" not in ctx:
        setup_pick_ready_block(ctx)
    move_clock(issued_at)
    ctx["pick_call"] = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], target_pick_at, estimated_tons
    )
    return ctx


def setup_acknowledged_pick_call(
    ctx: dict,
    issued_at: str = PICK_CALL_ISSUED_AT,
    target_pick_at: str = TARGET_PICK_AT,
    estimated_tons: float = 45.000,
) -> dict:
    if "pick_call" not in ctx:
        setup_issued_pick_call(ctx, issued_at, target_pick_at, estimated_tons)
    ctx["pick_call"] = acknowledge_pick_call(ctx["pick_call"]["id"], ctx["grower"]["id"])
    return ctx


def setup_crush_pad(ctx: dict, lane_overrides=None) -> dict:
    """Open one receiving lane."""
    ctx["lane"] = create_lane(**(lane_overrides or {}))
    return ctx


def setup_harvest_ready(
    contract_overrides=None,
    lane_overrides=None,
    estimated_tons: float = 45.000,
    target_pick_at: str = TARGET_PICK_AT,
    **book_overrides,
) -> dict:
    """The full preamble: ACTIVE contract, allocated pick-ready block, one open
    lane and one ACKNOWLEDGED pick call. Nothing has been booked yet."""
    ctx = setup_active_contract(contract_overrides, **book_overrides)
    setup_crush_pad(ctx, lane_overrides)
    setup_acknowledged_pick_call(ctx, target_pick_at=target_pick_at, estimated_tons=estimated_tons)
    return ctx


def setup_scheduled_appointment(
    ctx: dict,
    window_start: str = APPOINTMENT_WINDOW_START,
    window_end: str = APPOINTMENT_WINDOW_END,
    planned_tons: float = 22.000,
    headers=None,
) -> dict:
    """Reserve one crush-pad slot against the acknowledged call."""
    appointment = book_appointment(
        ctx["pick_call"]["id"], ctx["lane"]["id"], window_start, window_end, planned_tons, headers
    )
    ctx.setdefault("appointments", []).append(appointment)
    ctx["appointment"] = appointment
    return ctx


# --- Tier 4: loads on the pad --------------------------------------------------


def deliver_gross_load(
    ctx: dict,
    net_tons: float,
    appointment: dict = None,
    arrival_at: str = TRUCK_ARRIVAL_AT,
    tare_weight_lbs: int = 10000,
    block_id: str = None,
    headers=None,
) -> dict:
    """Move the clock into the arrival envelope and capture the inbound pass."""
    appointment = appointment or ctx["appointment"]
    move_clock(arrival_at)
    tag = capture_gross(
        appointment["id"],
        block_id or ctx["block"]["id"],
        tare_weight_lbs + tons_to_lbs(net_tons),
        headers=headers,
    )
    ctx.setdefault("tags", []).append(tag)
    ctx["tag"] = tag
    ctx.setdefault("tares", {})[tag["id"]] = tare_weight_lbs
    return tag


def deliver_net_load(
    ctx: dict,
    net_tons: float,
    appointment: dict = None,
    arrival_at: str = TRUCK_ARRIVAL_AT,
    tare_weight_lbs: int = 10000,
    block_id: str = None,
) -> dict:
    """Capture gross then tare, leaving the load NET_FINAL and still PENDING."""
    tag = deliver_gross_load(ctx, net_tons, appointment, arrival_at, tare_weight_lbs, block_id)
    tag = capture_tare(tag["id"], tare_weight_lbs)
    ctx["tags"][-1] = tag
    ctx["tag"] = tag
    return tag


def grade_load(
    ctx: dict,
    tag: dict = None,
    brix: float = 24.0,
    ta_gl: float = 6.5,
    ph: float = 3.55,
    rot_pct: float = 2.0,
    mog_pct: float = 1.0,
) -> dict:
    tag = tag or ctx["tag"]
    grading = record_grading(tag["id"], brix=brix, ta_gl=ta_gl, ph=ph, rot_pct=rot_pct, mog_pct=mog_pct)
    ctx.setdefault("gradings", []).append(grading)
    ctx["grading"] = grading
    return grading


def deliver_and_grade_load(
    ctx: dict,
    net_tons: float,
    brix: float = 24.0,
    ta_gl: float = 6.5,
    ph: float = 3.55,
    rot_pct: float = 2.0,
    mog_pct: float = 1.0,
    appointment: dict = None,
    arrival_at: str = TRUCK_ARRIVAL_AT,
    tare_weight_lbs: int = 10000,
    block_id: str = None,
) -> tuple:
    """Gross, tare and grade one load. Returns (tag, grading)."""
    tag = deliver_net_load(ctx, net_tons, appointment, arrival_at, tare_weight_lbs, block_id)
    grading = grade_load(ctx, tag, brix, ta_gl, ph, rot_pct, mog_pct)
    return read_weigh_tag(tag["id"]), grading


# --- Tier 5: settlement and payment -------------------------------------------


def setup_settled_contract(
    contract_overrides=None,
    loads=((22.000, 24.0), (18.000, 24.0)),
    close_at: str = None,
    **book_overrides,
) -> dict:
    """Deliver and grade a list of (net_tons, brix) loads, then close the vintage.

    Every load lands on its own crush-pad slot so the lane's buffered exclusivity
    rule is respected; the loads are graded in the order given.
    """
    ctx = setup_harvest_ready(
        contract_overrides=contract_overrides,
        lane_overrides={"daily_capacity_tons": 200.000, "max_load_tons": 40.000},
        estimated_tons=sum(load[0] for load in loads) + 1.000,
        **book_overrides,
    )
    windows = [
        ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z", "2026-08-25T14:30:00Z"),
        ("2026-08-25T16:30:00Z", "2026-08-25T18:30:00Z", "2026-08-25T17:00:00Z"),
        ("2026-08-25T19:00:00Z", "2026-08-25T21:00:00Z", "2026-08-25T19:30:00Z"),
        ("2026-08-26T09:00:00Z", "2026-08-26T11:00:00Z", "2026-08-26T09:30:00Z"),
    ]
    for index, (net_tons, brix) in enumerate(loads):
        window_start, window_end, arrival_at = windows[index]
        setup_scheduled_appointment(ctx, window_start, window_end, planned_tons=net_tons)
        deliver_and_grade_load(ctx, net_tons, brix=brix, arrival_at=arrival_at)
    if close_at:
        move_clock(close_at)
    ctx["contract"] = close_settlement(ctx["contract"]["id"])
    ctx["installments"] = list_installments(contract_id=ctx["contract"]["id"])
    return ctx


# --- Named composite scenarios -------------------------------------------------


def setup_single_load_on_pad(
    contract_overrides=None,
    net_tons: float = 22.000,
    tare_weight_lbs: int = 17240,
    estimated_tons: float = None,
    planned_tons: float = None,
    lane_overrides=None,
    sampled_at: str = SAMPLING_RECORDED_AT,
    issued_at: str = PICK_CALL_ISSUED_AT,
    target_pick_at: str = TARGET_PICK_AT,
    arrival_at: str = TRUCK_ARRIVAL_AT,
    window_start: str = APPOINTMENT_WINDOW_START,
    window_end: str = APPOINTMENT_WINDOW_END,
    **book_overrides,
) -> dict:
    """One producer, block, specification, lane and crew; an ACTIVE contract with
    the block allocated; a recorded pick-ready sampling visit; an acknowledged
    pick call; one booked slot; and one load already at NET_FINAL and PENDING.

    This is the shared preamble for every load-level pricing scenario.
    """
    ctx = setup_active_contract(contract_overrides, **book_overrides)
    setup_crush_pad(ctx, lane_overrides)
    setup_pick_ready_block(ctx, sampled_at=sampled_at)
    setup_issued_pick_call(
        ctx,
        issued_at=issued_at,
        target_pick_at=target_pick_at,
        estimated_tons=estimated_tons if estimated_tons is not None else net_tons + 23.000,
    )
    ctx["pick_call"] = acknowledge_pick_call(ctx["pick_call"]["id"], ctx["grower"]["id"])
    setup_scheduled_appointment(
        ctx,
        window_start,
        window_end,
        planned_tons if planned_tons is not None else net_tons,
    )
    deliver_net_load(ctx, net_tons, arrival_at=arrival_at, tare_weight_lbs=tare_weight_lbs)
    return ctx


def setup_settlement_basis_pair(base_price_per_ton_cents: int = 450000) -> dict:
    """Two ACTIVE TONNAGE contracts on one producer and one block, identical in
    every commercial term except `settlement_basis` (LOAD_BY_LOAD versus
    WEIGHTED_BLEND).  Each is fed the same two loads — 22.000 net tons graded at
    Brix 28.0 and 18.000 net tons graded at Brix 21.5 — and neither is closed yet.

    Returns the context with keys `contract_a`, `contract_b`, `tags_a`, `tags_b`.
    """
    move_clock("2026-08-20T08:00:00Z")
    book = setup_reference_book()
    grower, spec, block = book["grower"], book["spec"], book["block"]
    lane = create_lane(lane_code="L1", daily_capacity_tons=80.000)
    crew = create_crew(region_code=grower["region_code"])

    contracts = {}
    for key, basis in (("a", "LOAD_BY_LOAD"), ("b", "WEIGHTED_BLEND")):
        contract = create_contract(
            grower["id"],
            spec["id"],
            contract_basis="TONNAGE",
            committed_tons=40.000,
            base_price_per_ton_cents=base_price_per_ton_cents,
            over_delivery_policy="ACCEPT_AT_SPOT",
            settlement_basis=basis,
            term_start_vintage=2026,
            term_end_vintage=2028,
            installment_plan=single_installment_plan(),
        )
        create_allocation(contract["id"], block["id"])
        offer_contract(contract["id"])
        contracts[key] = accept_contract(contract["id"], grower["id"])

    ctx = {
        "grower": grower,
        "spec": spec,
        "block": block,
        "lane": lane,
        "crew": crew,
        "contract_a": contracts["a"],
        "contract_b": contracts["b"],
        "grower_headers": make_grower_headers(grower["id"]),
    }

    schedule = {
        "a": {
            "target_pick_at": "2026-08-25T14:00:00Z",
            "slots": [
                ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z", "2026-08-25T14:30:00Z", 22.000, 28.0),
                ("2026-08-25T17:00:00Z", "2026-08-25T19:00:00Z", "2026-08-25T17:30:00Z", 18.000, 21.5),
            ],
            "visit_window": ("2026-08-20T14:00:00Z", "2026-08-20T16:00:00Z"),
        },
        "b": {
            "target_pick_at": "2026-08-27T14:00:00Z",
            "slots": [
                ("2026-08-27T14:00:00Z", "2026-08-27T16:00:00Z", "2026-08-27T14:30:00Z", 22.000, 28.0),
                ("2026-08-27T17:00:00Z", "2026-08-27T19:00:00Z", "2026-08-27T17:30:00Z", 18.000, 21.5),
            ],
            "visit_window": ("2026-08-20T17:00:00Z", "2026-08-20T19:00:00Z"),
        },
    }

    # Both harvests are sampled, called and booked while the clock is still at
    # 2026-08-20T08:00:00Z.  The notice gate measures `target_pick_at` against the
    # logical clock at issuance, so advancing the clock into contract A's arrival
    # windows before contract B's call is issued would leave B short of the
    # 48-hour `min_pick_notice_hours` floor.
    for key in ("a", "b"):
        plan = schedule[key]
        contract = contracts[key]
        visit = book_sampling_visit(
            contract["id"], block["id"], crew["id"], plan["visit_window"][0], plan["visit_window"][1]
        )
        record_sampling_visit(visit["id"], measured_brix=24.5, measured_rot_pct=1.0)
        pick_call = issue_pick_call(contract["id"], block["id"], plan["target_pick_at"], 45.000)
        acknowledge_pick_call(pick_call["id"], grower["id"])
        plan["pick_call"] = pick_call
        plan["appointments"] = [
            book_appointment(pick_call["id"], lane["id"], slot[0], slot[1], slot[3])
            for slot in plan["slots"]
        ]

    for key in ("a", "b"):
        plan = schedule[key]
        tags = []
        for appointment, slot in zip(plan["appointments"], plan["slots"]):
            move_clock(slot[2])
            tare = 17240 if slot[3] == 22.000 else 17000
            tag = capture_gross(
                appointment["id"], block["id"], tare + tons_to_lbs(slot[3])
            )
            capture_tare(tag["id"], tare)
            record_grading(tag["id"], brix=slot[4], ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)
            tags.append(read_weigh_tag(tag["id"]))
        ctx[f"pick_call_{key}"] = read_pick_call(plan["pick_call"]["id"])
        ctx[f"appointments_{key}"] = plan["appointments"]
        ctx[f"tags_{key}"] = tags
    return ctx


def setup_prior_vintage_expiry_then_current_rejection() -> dict:
    """A producer carrying one 2025 expired pick call and one 2026 load already at
    NET_FINAL awaiting a rot-driven quality rejection.

    The 2025 call is issued and left unacknowledged, so advancing the clock past
    its acknowledgement deadline expires it; the clock then moves into the 2026
    vintage before the load is presented.  Returns the context with the load in
    `tag`, ready to be graded by the caller.
    """
    move_clock("2025-08-20T08:00:00Z")
    book = setup_reference_book()
    grower, spec, block = book["grower"], book["spec"], book["block"]
    lane = create_lane(lane_code="L1", daily_capacity_tons=80.000)
    crew = create_crew(region_code=grower["region_code"])
    contract = create_contract(
        grower["id"],
        spec["id"],
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_SPOT",
        term_start_vintage=2025,
        term_end_vintage=2028,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], block["id"])
    offer_contract(contract["id"])
    contract = accept_contract(contract["id"], grower["id"])

    visit_2025 = book_sampling_visit(
        contract["id"], block["id"], crew["id"], "2025-08-20T09:00:00Z", "2025-08-20T11:00:00Z"
    )
    record_sampling_visit(visit_2025["id"], measured_brix=24.5, measured_rot_pct=1.0)
    pick_2025 = issue_pick_call(contract["id"], block["id"], "2025-08-25T14:00:00Z", 20.000)

    # The acknowledgement deadline is 24 hours after issuance and nobody answers.
    move_clock("2025-08-21T09:00:00Z")
    move_clock("2026-08-20T08:00:00Z")

    visit_2026 = book_sampling_visit(
        contract["id"], block["id"], crew["id"], "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"
    )
    record_sampling_visit(visit_2026["id"], measured_brix=24.5, measured_rot_pct=1.0)
    pick_2026 = issue_pick_call(contract["id"], block["id"], "2026-08-25T14:00:00Z", 45.000)
    acknowledge_pick_call(pick_2026["id"], grower["id"])
    appointment = book_appointment(
        pick_2026["id"], lane["id"], "2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z", 22.000
    )
    move_clock("2026-08-25T14:30:00Z")
    tag = capture_gross(appointment["id"], block["id"], 61240)
    tag = capture_tare(tag["id"], 17240)
    return {
        "grower": grower,
        "spec": spec,
        "block": block,
        "lane": lane,
        "crew": crew,
        "contract": contract,
        "pick_call_2025": pick_2025,
        "pick_call": pick_2026,
        "appointment": appointment,
        "tag": tag,
        "tags": [tag],
        "grower_headers": make_grower_headers(grower["id"]),
    }


def setup_cap_cascade_pad() -> dict:
    """A 40.000-ton contract one load short of its soft cap, with a third slot still
    reserved on the lane.

    Three slots are booked on one lane for 2026-08-25 — 22.000, 18.000 and 25.000 tons
    — the first load is weighed, tared and graded at Brix 28.0, and the second load is
    weighed and tared but deliberately left ungraded.  Grading it takes the contract to
    exactly `committed_tons`.  Returns the context with `tag1`, `tag2`, `appointments`
    and the still-acknowledged `pick_call`.
    """
    move_clock("2026-08-20T08:00:00Z")
    book = setup_reference_book()
    grower, spec, block = book["grower"], book["spec"], book["block"]
    lane = create_lane(
        lane_code="L1", daily_capacity_tons=80.000, turnaround_buffer_minutes=30, max_load_tons=40.0
    )
    crew = create_crew(region_code=grower["region_code"], max_concurrent_visits=2)
    contract = create_contract(
        grower["id"],
        spec["id"],
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        committed_tons=40.000,
        over_delivery_policy="ACCEPT_AT_SPOT",
        spot_price_pct=70.0,
        over_delivery_tolerance_pct=10.0,
        provisional_payment_pct=60.0,
        pick_call_ack_window_hours=24,
        term_start_vintage=2026,
        term_end_vintage=2028,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], block["id"])
    offer_contract(contract["id"])
    contract = accept_contract(contract["id"], grower["id"])

    visit = book_sampling_visit(
        contract["id"], block["id"], crew["id"], "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"
    )
    record_sampling_visit(visit["id"], measured_brix=24.5, measured_ph=3.45, measured_rot_pct=1.0)
    pick_call = issue_pick_call(contract["id"], block["id"], "2026-08-25T14:00:00Z", 45.000)
    acknowledge_pick_call(pick_call["id"], grower["id"])

    slots = (
        ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z", 22.000),
        ("2026-08-25T17:00:00Z", "2026-08-25T19:00:00Z", 18.000),
        ("2026-08-25T20:00:00Z", "2026-08-25T22:00:00Z", 25.000),
    )
    appointments = [
        book_appointment(pick_call["id"], lane["id"], start, end, tons) for start, end, tons in slots
    ]

    move_clock("2026-08-25T14:30:00Z")
    tag1 = capture_gross(appointments[0]["id"], block["id"], 61240)
    capture_tare(tag1["id"], 17240)
    record_grading(tag1["id"], brix=28.0, ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)

    move_clock("2026-08-25T17:30:00Z")
    tag2 = capture_gross(appointments[1]["id"], block["id"], 53000)
    tag2 = capture_tare(tag2["id"], 17000)

    return {
        "grower": grower,
        "spec": spec,
        "block": block,
        "lane": lane,
        "crew": crew,
        "contract": contract,
        "visit": visit,
        "pick_call": pick_call,
        "appointments": appointments,
        "tag1": read_weigh_tag(tag1["id"]),
        "tag2": tag2,
        "grower_headers": make_grower_headers(grower["id"]),
    }
