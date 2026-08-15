"""Composite setup helpers for the cruise-port terminal workflows.

Every test starts against an empty database (the runner restarts the server
per test), so these helpers build complete precondition chains from scratch.
They use the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_ETA,
    DEFAULT_ETD,
    DEFAULT_SERVICE_WINDOW_END,
    DEFAULT_SERVICE_WINDOW_START,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    create_baggage_item_payload,
    create_berth_assignment_payload,
    create_berth_payload,
    create_manifest_entry_payload,
    create_port_call_payload,
    create_screening_lane_payload,
    create_service_order_payload,
    create_terminal_payload,
    create_transport_slot_payload,
    create_vessel_payload,
    create_weather_advisory_payload,
    delay_port_call_payload,
    open_lane_payload,
    post_adjustment_payload,
    settle_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_harbormaster_headers,
    make_operator_headers,
    make_vessel_agent_headers,
)

ADMIN = TEST_USERS["admin_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CUSTOMS = TEST_USERS["customs_headers"]
BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Terminal / berth / vessel registry
# ---------------------------------------------------------------------------

def create_terminal(name="T1", max_apron_slots=4, taxi_dispatch_capacity_per_window=2):
    resp = api_client.create_terminal(
        create_terminal_payload(
            name=name,
            max_apron_slots=max_apron_slots,
            taxi_dispatch_capacity_per_window=taxi_dispatch_capacity_per_window,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_berth(terminal_id, berth_code="B1", length_ft=1200, max_draft_ft=40.0):
    resp = api_client.create_berth(
        create_berth_payload(terminal_id, berth_code=berth_code,
                             length_ft=length_ft, max_draft_ft=max_draft_ft),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_vessel(terminal_id, name="MV A", loa_ft=950, draft_ft=30.0,
                  pax_capacity=4000, crew_count=900):
    resp = api_client.create_vessel(
        create_vessel_payload(terminal_id, name=name, loa_ft=loa_ft,
                              draft_ft=draft_ft, pax_capacity=pax_capacity,
                              crew_count=crew_count),
        ADMIN,
    )
    return get_success_data(resp, 201)


def get_terminal(terminal_id):
    return get_success_data(api_client.get_terminal(terminal_id, ADMIN))


def get_port_call(port_call_id):
    return get_success_data(api_client.get_port_call(port_call_id, HARBORMASTER))


# ---------------------------------------------------------------------------
# Port calls
# ---------------------------------------------------------------------------

def create_port_call(terminal_id, vessel_id, voyage_ref="V1",
                     scheduled_eta=DEFAULT_ETA, scheduled_etd=DEFAULT_ETD,
                     booked_embark_pax=10, booked_debark_pax=10, as_admin=False):
    payload = create_port_call_payload(
        terminal_id, vessel_id, voyage_ref=voyage_ref,
        scheduled_eta=scheduled_eta, scheduled_etd=scheduled_etd,
        booked_embark_pax=booked_embark_pax, booked_debark_pax=booked_debark_pax,
    )
    headers = ADMIN if as_admin else make_vessel_agent_headers(vessel_id)
    resp = api_client.create_port_call(payload, headers)
    return get_success_data(resp, 201)


def delay_port_call(port_call_id, vessel_id, revised_eta="2026-08-11T08:00:00Z",
                    revised_etd="2026-08-11T20:00:00Z", reason="weather"):
    resp = api_client.delay_port_call(
        port_call_id,
        delay_port_call_payload(revised_eta=revised_eta, revised_etd=revised_etd,
                                reason=reason),
        make_vessel_agent_headers(vessel_id),
    )
    return get_success_data(resp)


def confirm_revised_port_call(port_call_id):
    return get_success_data(api_client.confirm_revised_port_call(port_call_id, HARBORMASTER))


def arrive_port_call(port_call_id, actual_eta=DEFAULT_ETA):
    resp = api_client.arrive_port_call(port_call_id, {"actual_eta": actual_eta}, HARBORMASTER)
    return get_success_data(resp)


def begin_turnaround(port_call_id):
    return get_success_data(api_client.begin_turnaround(port_call_id, OPERATOR))


def depart_port_call(port_call_id, actual_etd=DEFAULT_ETD):
    resp = api_client.depart_port_call(port_call_id, {"actual_etd": actual_etd}, HARBORMASTER)
    return get_success_data(resp)


def close_port_call(port_call_id):
    return get_success_data(api_client.close_port_call(port_call_id, BILLING))


# ---------------------------------------------------------------------------
# Berth assignments
# ---------------------------------------------------------------------------

def add_berth_assignment(port_call_id, berth_id, window_start=DEFAULT_WINDOW_START,
                         window_end=DEFAULT_WINDOW_END, expected_port_call_version=None):
    """Create a TENTATIVE assignment. When expected_port_call_version is not
    given, the call's current version is read first (OCC field)."""
    if expected_port_call_version is None:
        expected_port_call_version = get_port_call(port_call_id)["version"]
    resp = api_client.create_berth_assignment(
        port_call_id,
        create_berth_assignment_payload(
            berth_id, expected_port_call_version,
            window_start=window_start, window_end=window_end,
        ),
        HARBORMASTER,
    )
    return get_success_data(resp, 201)


def confirm_assignment(assignment_id):
    return get_success_data(api_client.confirm_berth_assignment(assignment_id, HARBORMASTER))


def create_confirmed_assignment(port_call_id, berth_id,
                                window_start=DEFAULT_WINDOW_START,
                                window_end=DEFAULT_WINDOW_END):
    assignment = add_berth_assignment(port_call_id, berth_id,
                                      window_start=window_start, window_end=window_end)
    return confirm_assignment(assignment["id"])


def get_berth_assignment(assignment_id):
    return get_success_data(api_client.get_berth_assignment(assignment_id, HARBORMASTER))


# ---------------------------------------------------------------------------
# Screening lanes
# ---------------------------------------------------------------------------

def create_screening_lane(terminal_id, lane_code="L1"):
    resp = api_client.create_screening_lane(
        create_screening_lane_payload(terminal_id, lane_code=lane_code), ADMIN)
    return get_success_data(resp, 201)


def open_lane(lane_id, officers_assigned=2):
    return get_success_data(
        api_client.open_screening_lane(lane_id, open_lane_payload(officers_assigned), OPERATOR))


def create_open_lane(terminal_id, lane_code="L1", officers_assigned=2):
    lane = create_screening_lane(terminal_id, lane_code=lane_code)
    return open_lane(lane["id"], officers_assigned=officers_assigned)


# ---------------------------------------------------------------------------
# Manifest entries
# ---------------------------------------------------------------------------

def add_manifest_entry(port_call_id, vessel_id, passenger_ref, direction="EMBARK",
                       cabin_class="STANDARD"):
    resp = api_client.create_manifest_entry(
        port_call_id,
        create_manifest_entry_payload(passenger_ref, direction=direction,
                                      cabin_class=cabin_class),
        make_vessel_agent_headers(vessel_id),
    )
    return get_success_data(resp, 201)


def get_manifest_entry(entry_id):
    return get_success_data(api_client.get_manifest_entry(entry_id, OPERATOR))


def check_in_entry(entry_id):
    return get_success_data(api_client.check_in_manifest_entry(entry_id, OPERATOR))


def screen_entry(entry_id):
    return get_success_data(api_client.screen_manifest_entry(entry_id, OPERATOR))


def board_entry(entry_id):
    return get_success_data(api_client.board_manifest_entry(entry_id, OPERATOR))


def offload_entry(entry_id):
    return get_success_data(api_client.offload_manifest_entry(entry_id, OPERATOR))


def disembark_entry(entry_id):
    return get_success_data(api_client.disembark_manifest_entry(entry_id, OPERATOR))


def customs_hold_entry(entry_id):
    return get_success_data(api_client.customs_hold_manifest_entry(entry_id, CUSTOMS))


def customs_release_entry(entry_id):
    return get_success_data(api_client.customs_release_manifest_entry(entry_id, CUSTOMS))


def walk_entry_to_checked_in(port_call_id, vessel_id, passenger_ref,
                             cabin_class="STANDARD"):
    entry = add_manifest_entry(port_call_id, vessel_id, passenger_ref,
                               direction="EMBARK", cabin_class=cabin_class)
    return check_in_entry(entry["id"])


def walk_entry_to_embarked(port_call_id, vessel_id, passenger_ref,
                           cabin_class="STANDARD"):
    """BOOKED -> CHECKED_IN -> SCREENED -> EMBARKED. Requires the call to be
    TURNAROUND with the customs case CLEARED and an open staffed lane."""
    entry = walk_entry_to_checked_in(port_call_id, vessel_id, passenger_ref,
                                     cabin_class=cabin_class)
    screen_entry(entry["id"])
    return board_entry(entry["id"])


# ---------------------------------------------------------------------------
# Baggage items
# ---------------------------------------------------------------------------

def check_bag(manifest_entry_id, tag_code="TAG1"):
    resp = api_client.create_baggage_item(
        create_baggage_item_payload(manifest_entry_id, tag_code=tag_code), OPERATOR)
    return get_success_data(resp, 201)


def get_bag(bag_id):
    return get_success_data(api_client.get_baggage_item(bag_id, OPERATOR))


def stage_bag(bag_id):
    return get_success_data(api_client.stage_baggage_item(bag_id, OPERATOR))


def load_bag(bag_id):
    return get_success_data(api_client.load_baggage_item(bag_id, OPERATOR))


# ---------------------------------------------------------------------------
# Customs cases
# ---------------------------------------------------------------------------

def create_customs_case(port_call_id):
    return get_success_data(api_client.create_customs_case(port_call_id, CUSTOMS), 201)


def file_customs_case(case_id):
    return get_success_data(api_client.file_customs_case(case_id, CUSTOMS))


def clear_customs_case(case_id):
    return get_success_data(api_client.clear_customs_case(case_id, CUSTOMS))


def get_customs_case(case_id):
    return get_success_data(api_client.get_customs_case(case_id, CUSTOMS))


# ---------------------------------------------------------------------------
# Service orders
# ---------------------------------------------------------------------------

def create_service_order(port_call_id, vessel_id, kind="PROVISIONING", units=5,
                         window_start=DEFAULT_SERVICE_WINDOW_START,
                         window_end=DEFAULT_SERVICE_WINDOW_END):
    resp = api_client.create_service_order(
        port_call_id,
        create_service_order_payload(kind=kind, units=units,
                                     window_start=window_start, window_end=window_end),
        make_vessel_agent_headers(vessel_id),
    )
    return get_success_data(resp, 201)


def get_service_order(order_id):
    return get_success_data(api_client.get_service_order(order_id, HARBORMASTER))


def approve_service_order(order_id, role="TerminalOperator", user_id="op-1"):
    headers = (make_operator_headers(user_id) if role == "TerminalOperator"
               else make_harbormaster_headers(user_id))
    return get_success_data(api_client.approve_service_order(order_id, headers))


def start_service_order(order_id):
    return get_success_data(api_client.start_service_order(order_id, OPERATOR))


def complete_service_order(order_id, actual_units):
    return get_success_data(
        api_client.complete_service_order(order_id, {"actual_units": actual_units}, OPERATOR))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def create_provisional_invoice(port_call_id):
    return get_success_data(api_client.create_provisional_invoice(port_call_id, BILLING), 201)


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, BILLING))


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def settle_invoice(invoice_id, payment_cents):
    return get_success_data(
        api_client.settle_invoice(invoice_id, settle_invoice_payload(payment_cents), BILLING))


def dispute_invoice(invoice_id, vessel_id, reason="dispute"):
    return get_success_data(
        api_client.dispute_invoice(invoice_id, {"reason": reason},
                                   make_vessel_agent_headers(vessel_id)))


def post_adjustment(invoice_id, amount_cents, reason, expected_invoice_version):
    return get_success_data(
        api_client.post_invoice_adjustment(
            invoice_id,
            post_adjustment_payload(amount_cents, reason, expected_invoice_version),
            BILLING))


def get_final_invoice_for_call(port_call_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_invoices(BILLING, params={"port_call_id": port_call_id,
                                                     "kind": "FINAL"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly one FINAL invoice, got {meta}"
    return data[0]


# ---------------------------------------------------------------------------
# Transport slots
# ---------------------------------------------------------------------------

def create_transport_slot(terminal_id, port_call_id, vehicle_class="TAXI", party_size=2):
    resp = api_client.create_transport_slot(
        create_transport_slot_payload(terminal_id, port_call_id,
                                      vehicle_class=vehicle_class, party_size=party_size),
        OPERATOR)
    return get_success_data(resp, 201)


def get_transport_slot(slot_id):
    return get_success_data(api_client.get_transport_slot(slot_id, OPERATOR))


# ---------------------------------------------------------------------------
# Weather advisories
# ---------------------------------------------------------------------------

def create_weather_advisory(terminal_id, severity="WARNING",
                            window_start="2026-08-01T00:00:00Z",
                            window_end="2026-09-01T00:00:00Z"):
    resp = api_client.create_weather_advisory(
        create_weather_advisory_payload(terminal_id, severity=severity,
                                        window_start=window_start,
                                        window_end=window_end),
        ADMIN)
    return get_success_data(resp, 201)


def get_weather_advisory(advisory_id):
    return get_success_data(api_client.get_weather_advisory(advisory_id, ADMIN))


# ---------------------------------------------------------------------------
# Composite scenario fixtures
# ---------------------------------------------------------------------------

def setup_base(name="T1", max_apron_slots=4, taxi_dispatch_capacity_per_window=2,
               berth_code="B1", berth_length_ft=1200, berth_max_draft_ft=40.0,
               vessel_name="MV A", loa_ft=950, draft_ft=30.0,
               pax_capacity=4000, crew_count=900):
    """Terminal + one berth + one vessel. Returns a context dict."""
    terminal = create_terminal(name=name, max_apron_slots=max_apron_slots,
                               taxi_dispatch_capacity_per_window=taxi_dispatch_capacity_per_window)
    berth = create_berth(terminal["id"], berth_code=berth_code,
                         length_ft=berth_length_ft, max_draft_ft=berth_max_draft_ft)
    vessel = create_vessel(terminal["id"], name=vessel_name, loa_ft=loa_ft,
                           draft_ft=draft_ft, pax_capacity=pax_capacity,
                           crew_count=crew_count)
    return {"terminal": terminal, "berth": berth, "vessel": vessel}


def setup_scheduled_call(voyage_ref="V1", scheduled_eta=DEFAULT_ETA,
                         scheduled_etd=DEFAULT_ETD, booked_embark_pax=10,
                         booked_debark_pax=10, **base_kwargs):
    """Base scenario + one SCHEDULED port call owned by the vessel's agent."""
    ctx = setup_base(**base_kwargs)
    ctx["port_call"] = create_port_call(
        ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref=voyage_ref,
        scheduled_eta=scheduled_eta, scheduled_etd=scheduled_etd,
        booked_embark_pax=booked_embark_pax, booked_debark_pax=booked_debark_pax)
    return ctx


def setup_confirmed_call(window_start=DEFAULT_WINDOW_START,
                         window_end=DEFAULT_WINDOW_END, **kwargs):
    """SCHEDULED call holding a CONFIRMED berth assignment."""
    ctx = setup_scheduled_call(**kwargs)
    ctx["assignment"] = create_confirmed_assignment(
        ctx["port_call"]["id"], ctx["berth"]["id"],
        window_start=window_start, window_end=window_end)
    return ctx


def setup_arrived_call(actual_eta=DEFAULT_ETA, window_start=DEFAULT_WINDOW_START,
                       window_end=DEFAULT_WINDOW_END, **kwargs):
    """Call ARRIVED; its CONFIRMED assignment flipped to ACTIVE."""
    ctx = setup_confirmed_call(window_start=window_start, window_end=window_end, **kwargs)
    ctx["port_call"] = arrive_port_call(ctx["port_call"]["id"], actual_eta=actual_eta)
    ctx["assignment"] = get_berth_assignment(ctx["assignment"]["id"])
    return ctx


def setup_turnaround_call(customs="cleared", officers=2, actual_eta=DEFAULT_ETA,
                          **kwargs):
    """Full setup to TURNAROUND: arrived call + open staffed lane + customs
    case filed (and cleared when customs='cleared')."""
    ctx = setup_arrived_call(actual_eta=actual_eta, **kwargs)
    ctx["lane"] = create_open_lane(ctx["terminal"]["id"], officers_assigned=officers)
    ctx["customs_case"] = create_customs_case(ctx["port_call"]["id"])
    file_customs_case(ctx["customs_case"]["id"])
    ctx["port_call"] = begin_turnaround(ctx["port_call"]["id"])
    if customs == "cleared":
        ctx["customs_case"] = clear_customs_case(ctx["customs_case"]["id"])
    else:
        ctx["customs_case"] = get_customs_case(ctx["customs_case"]["id"])
    return ctx


def setup_departed_call(actual_etd=DEFAULT_ETD, **kwargs):
    """TURNAROUND call with customs CLEARED, departed (assignment RELEASED)."""
    ctx = setup_turnaround_call(customs="cleared", **kwargs)
    ctx["port_call"] = depart_port_call(ctx["port_call"]["id"], actual_etd=actual_etd)
    return ctx


def setup_closed_call(actual_etd=DEFAULT_ETD, **kwargs):
    """Full lifecycle through CLOSED; the FINAL DRAFT invoice is generated."""
    ctx = setup_departed_call(actual_etd=actual_etd, **kwargs)
    ctx["port_call"] = close_port_call(ctx["port_call"]["id"])
    ctx["final_invoice"] = get_final_invoice_for_call(ctx["port_call"]["id"])
    return ctx


def setup_turnaround_with_entries(entries, customs="cleared", officers=2,
                                  vessel_name="MV A", booked_embark_pax=100,
                                  booked_debark_pax=100, voyage_ref="V1",
                                  **base_kwargs):
    """Walk a call to TURNAROUND with manifest entries pre-added and progressed.

    entries: list of dicts with keys
        ref          passenger_ref (unique within the call)
        direction    "EMBARK" or "DEBARK"
        cabin_class  optional, default "STANDARD"
        progress     optional target state:
                     EMBARK: None | "checked_in" | "screened" | "embarked"
                     DEBARK: None | "disembarked" | "held" | "cleared"

    Build order: entries are added while the call is SCHEDULED (EMBARK entries
    are checked in at the same time when their progress asks for it); the berth
    assignment is confirmed; the customs case is created and filed; a staffed
    lane is opened; the call arrives; DEBARK entries are disembarked / held /
    released; EMBARK entries are screened; the turnaround begins; the case is
    cleared when customs == "cleared"; EMBARK entries marked "embarked" are
    boarded last.

    Returns a context dict with ctx["entries"] mapping ref -> latest entry.
    """
    ctx = setup_base(vessel_name=vessel_name, **base_kwargs)
    term_id = ctx["terminal"]["id"]
    ves_id = ctx["vessel"]["id"]
    pc = create_port_call(term_id, ves_id, voyage_ref=voyage_ref,
                          booked_embark_pax=booked_embark_pax,
                          booked_debark_pax=booked_debark_pax)
    ctx["port_call"] = pc

    ctx["entries"] = {}
    for spec in entries:
        entry = add_manifest_entry(pc["id"], ves_id, spec["ref"],
                                   direction=spec["direction"],
                                   cabin_class=spec.get("cabin_class", "STANDARD"))
        ctx["entries"][spec["ref"]] = entry
        if spec["direction"] == "EMBARK" and spec.get("progress") in (
                "checked_in", "screened", "embarked"):
            ctx["entries"][spec["ref"]] = check_in_entry(entry["id"])

    ctx["assignment"] = create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
    cc = create_customs_case(pc["id"])
    file_customs_case(cc["id"])
    ctx["customs_case"] = cc
    ctx["lane"] = create_open_lane(term_id, officers_assigned=officers)
    ctx["port_call"] = arrive_port_call(pc["id"])

    for spec in entries:
        progress = spec.get("progress")
        if spec["direction"] == "DEBARK" and progress in (
                "disembarked", "held", "cleared"):
            entry_id = ctx["entries"][spec["ref"]]["id"]
            ctx["entries"][spec["ref"]] = disembark_entry(entry_id)
            if progress == "held":
                ctx["entries"][spec["ref"]] = customs_hold_entry(entry_id)
            elif progress == "cleared":
                ctx["entries"][spec["ref"]] = customs_release_entry(entry_id)
        if spec["direction"] == "EMBARK" and spec.get("progress") in (
                "screened", "embarked"):
            entry_id = ctx["entries"][spec["ref"]]["id"]
            ctx["entries"][spec["ref"]] = screen_entry(entry_id)

    ctx["port_call"] = begin_turnaround(pc["id"])
    if customs == "cleared":
        ctx["customs_case"] = clear_customs_case(cc["id"])

    for spec in entries:
        if spec["direction"] == "EMBARK" and spec.get("progress") == "embarked":
            entry_id = ctx["entries"][spec["ref"]]["id"]
            ctx["entries"][spec["ref"]] = board_entry(entry_id)

    return ctx


def setup_executed_turnaround(actual_etd="2026-08-10T20:20:00Z",
                              service_kind="PROVISIONING", service_units=10,
                              actual_units=10):
    """The full operating day used by the final-invoice billing scenarios:
    two taxable EMBARK entries boarded, one CREW entry boarded (tax-exempt),
    one DEBARK entry disembarked and customs-cleared, and one service order
    completed at actual units — then departed at actual_etd.

    A second berth keeps the terminal posture OPERATIONAL so the terminal
    operator can approve the order without the conditional-role gate.
    """
    ctx = setup_base(vessel_name="MV E")
    create_berth(ctx["terminal"]["id"], berth_code="B2", length_ft=1100,
                 max_draft_ft=38.0)
    term_id = ctx["terminal"]["id"]
    ves_id = ctx["vessel"]["id"]
    pc = create_port_call(term_id, ves_id, voyage_ref="V1",
                          booked_embark_pax=100, booked_debark_pax=100)
    ctx["port_call"] = pc
    ctx["assignment"] = create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
    cc = create_customs_case(pc["id"])
    file_customs_case(cc["id"])
    ctx["customs_case"] = cc
    ctx["lane"] = create_open_lane(term_id, officers_assigned=2)

    e1 = add_manifest_entry(pc["id"], ves_id, "P1", direction="EMBARK",
                            cabin_class="STANDARD")
    e2 = add_manifest_entry(pc["id"], ves_id, "P2", direction="EMBARK",
                            cabin_class="PREMIUM")
    e3 = add_manifest_entry(pc["id"], ves_id, "P3", direction="EMBARK",
                            cabin_class="CREW")
    e4 = add_manifest_entry(pc["id"], ves_id, "P4", direction="DEBARK",
                            cabin_class="STANDARD")
    for entry in (e1, e2, e3):
        check_in_entry(entry["id"])

    ctx["port_call"] = arrive_port_call(pc["id"])
    ctx["port_call"] = begin_turnaround(pc["id"])
    ctx["customs_case"] = clear_customs_case(cc["id"])

    for entry in (e1, e2, e3):
        screen_entry(entry["id"])
        board_entry(entry["id"])
    ctx["embarked"] = [e1["id"], e2["id"], e3["id"]]

    disembark_entry(e4["id"])
    ctx["debarked"] = customs_release_entry(e4["id"])

    so = create_service_order(pc["id"], ves_id, kind=service_kind,
                              units=service_units)
    approve_service_order(so["id"], role="TerminalOperator", user_id="op-1")
    start_service_order(so["id"])
    ctx["service_order"] = complete_service_order(so["id"], actual_units=actual_units)

    ctx["port_call"] = depart_port_call(pc["id"], actual_etd=actual_etd)
    return ctx
