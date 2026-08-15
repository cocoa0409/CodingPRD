"""Composite setup helpers for the livestock-hauling scenarios.

Every test starts against an empty database (the runner restarts the server
per test), so each helper builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data so a failure surfaces
as a clear "Setup step failed" rather than a confusing assertion error.

All helpers return a simple dict namespace of the created records/ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_brand_inspection_payload,
    create_driver_payload,
    create_duty_event_payload,
    create_health_paper_payload,
    create_incident_payload,
    create_load_payload,
    create_shipper_payload,
    create_trailer_payload,
    create_washout_payload,
    create_weight_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_headers,
    make_driver_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CO1 = make_compliance_headers("co-1")
CO2 = make_compliance_headers("co-2")
CONSIGNEE = TEST_USERS["consignee_headers"]
WASHOUT = TEST_USERS["washout_headers"]


def set_clock(to_iso8601: str):
    """Advance the logical clock (CarrierAdmin-only capability, PRD §2.5)."""
    get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_shipper(**overrides) -> dict:
    return get_success_data(api.create_shipper(create_shipper_payload(**overrides),
                                               ADMIN))


def create_driver(**overrides) -> dict:
    return get_success_data(api.create_driver(create_driver_payload(**overrides),
                                              ADMIN))


def create_trailer(num_compartments: int = 1, **overrides) -> dict:
    """Create a trailer. Returns {"trailer": ..., "compartments": [...]}.

    Compartments are ordered by compartment_index ascending (PRD §3.2), so
    compartments[i] corresponds to the (i+1)-th entry of the supplied array.
    """
    if "compartments" not in overrides:
        overrides["compartments"] = [
            {"compartment_index": i + 1, "max_head_count": 40,
             "max_weight_lb": 45000}
            for i in range(num_compartments)
        ]
    trailer = get_success_data(
        api.create_trailer(create_trailer_payload(**overrides), ADMIN))
    comps, _meta = _list_compartments(trailer["id"])
    return {"trailer": trailer, "compartments": comps}


def _list_compartments(trailer_id: str) -> tuple:
    resp = api.list_compartments(trailer_id, ADMIN)
    body = resp.json()
    assert resp.status_code == 200, f"Setup step failed listing compartments: {resp.text}"
    return body["data"], body["meta"]


def wash_trailer(trailer_id: str, washed_at: str = "2026-08-01T00:30:00Z",
                 method: str = "HIGH_PRESSURE") -> dict:
    return get_success_data(
        api.create_washout(trailer_id,
                           create_washout_payload(washed_at=washed_at,
                                                  method=method),
                           WASHOUT))


def create_load(shipper_id: str, **overrides) -> dict:
    return get_success_data(api.create_load(create_load_payload(
        shipper_id=shipper_id, **overrides), DISP))


def get_load(load_id: str) -> dict:
    return get_success_data(api.get_load(load_id, ADMIN))


def get_driver(driver_id: str) -> dict:
    return get_success_data(api.get_driver(driver_id, ADMIN))


def get_trailer(trailer_id: str) -> dict:
    return get_success_data(api.get_trailer(trailer_id, ADMIN))


def get_settlement_of_load(load_id: str) -> dict:
    """The load's settlement sub-resource is an array of zero or one (PRD §3.6)."""
    data = get_success_data(api.get_load_settlement(load_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one settlement row for the departed load, got {data!r}")
    return data[0]


def allocate_all(load: dict, compartment_ids: list, head_per_alloc: int = None,
                 avg_weight_lb: float = None) -> list:
    """Allocate the load's full declared totals across the given compartments,
    refreshing expected_load_version between calls (each allocation increments
    the load version by 1, PRD §3.3). Returns the created allocations."""
    n = len(compartment_ids)
    head_total = load["declared_head_count"]
    weight_total = load["declared_weight_lb"]
    per_head = head_total // n
    allocations = []
    for i, comp_id in enumerate(compartment_ids):
        head = per_head if i < n - 1 else head_total - per_head * (n - 1)
        if head_per_alloc is not None:
            head = head_per_alloc
        if avg_weight_lb is not None:
            avg = avg_weight_lb
        else:
            # choose an average so the summed rounded weights equal declared
            remaining_weight = weight_total - sum(a["weight_lb"] for a in allocations)
            avg = remaining_weight / head
        current = get_load(load["id"])
        payload = {
            "trailer_compartment_id": comp_id,
            "head_count": head,
            "avg_weight_lb": avg,
            "expected_load_version": current["version"],
        }
        allocations.append(
            get_success_data(api.create_allocation(load["id"], payload, DISP)))
    return allocations


def plan_load(load_id: str):
    get_success_data(api.finalize_plan(load_id, DISP))


def attach_and_verify_paperwork(load: dict, verified_by=None,
                                brand_inspected_at: str = "2026-08-01T06:30:00Z"):
    """Attach + verify a health paper and a brand inspection (SoD: the
    verifier differs from the uploader), then advance the load to
    PAPERWORK_VERIFIED. Caller must have set the clock so that the brand
    inspection's inspected_at (default 2026-08-01T06:30) is not in the future
    and sits within 96h of planned_departure_at."""
    verifier = verified_by or CO2
    hp = get_success_data(api.create_health_paper(
        load["id"], create_health_paper_payload(
            species=load["species"],
            head_count_listed=load["declared_head_count"]), CO1))
    get_success_data(api.verify_health_paper(hp["id"], verifier))
    bi = get_success_data(api.create_brand_inspection(
        load["id"], create_brand_inspection_payload(
            inspected_at=brand_inspected_at,
            head_count_inspected=load["declared_head_count"]), CO1))
    get_success_data(api.verify_brand_inspection(bi["id"], verifier))
    get_success_data(api.verify_paperwork(load["id"], verifier))
    return {"health_paper_id": hp["id"], "brand_inspection_id": bi["id"]}


def assign_driver(load_id: str, driver_id: str) -> dict:
    """Assign with OCC: re-read the driver to obtain the current version."""
    driver = get_driver(driver_id)
    return get_success_data(api.assign_driver(
        load_id,
        {"driver_id": driver_id, "expected_driver_version": driver["version"]},
        DISP))


def setup_planned_load(head_count: int = 40, weight_lb: int = 40000,
                       num_compartments: int = 1, **load_overrides) -> dict:
    """Shipper + trailer + DRAFT load fully allocated and finalized (PLANNED)."""
    shipper = create_shipper()
    tt = create_trailer(num_compartments=num_compartments)
    load = create_load(shipper["id"], declared_head_count=head_count,
                       declared_weight_lb=weight_lb, **load_overrides)
    comp_ids = [c["id"] for c in tt["compartments"]]
    allocate_all(load, comp_ids)
    plan_load(load["id"])
    return {
        "shipper": shipper,
        "trailer": tt["trailer"],
        "compartments": tt["compartments"],
        "load": get_load(load["id"]),
    }


def setup_verified_load(head_count: int = 40, weight_lb: int = 40000,
                        num_compartments: int = 1,
                        start_clock: str = "2026-08-01T01:00:00Z",
                        brand_inspected_at: str = "2026-08-01T06:30:00Z",
                        paperwork_clock: str = "2026-08-01T07:00:00Z",
                        **load_overrides) -> dict:
    """A planned load whose paperwork is verified (PAPERWORK_VERIFIED).

    Sets the clock to start_clock, builds the plan, verifies the health
    paper, moves the clock to paperwork_clock for the brand inspection
    (inspected at brand_inspected_at), and leaves the clock there. Callers
    building trips on a later clock must pass start_clock /
    brand_inspected_at / paperwork_clock values that keep the logical clock
    moving forward."""
    set_clock(start_clock)
    ctx = setup_planned_load(head_count, weight_lb, num_compartments,
                             **load_overrides)
    load = ctx["load"]
    hp = get_success_data(api.create_health_paper(
        load["id"], create_health_paper_payload(
            species=load["species"],
            head_count_listed=load["declared_head_count"]), CO1))
    get_success_data(api.verify_health_paper(hp["id"], CO2))
    set_clock(paperwork_clock)
    bi = get_success_data(api.create_brand_inspection(
        load["id"], create_brand_inspection_payload(
            inspected_at=brand_inspected_at,
            head_count_inspected=load["declared_head_count"]), CO1))
    get_success_data(api.verify_brand_inspection(bi["id"], CO2))
    get_success_data(api.verify_paperwork(load["id"], CO2))
    ctx["load"] = get_load(load["id"])
    ctx["health_paper_id"] = hp["id"]
    ctx["brand_inspection_id"] = bi["id"]
    return ctx


def setup_assigned_load(head_count: int = 40, weight_lb: int = 40000,
                        num_compartments: int = 1, driver: dict = None,
                        wash: bool = True, wash_at: str = None,
                        **load_overrides) -> dict:
    """PAPERWORK_VERIFIED load with a driver assigned (ASSIGNED).

    Washes the trailer (required before a first departure, PRD §3.2) unless
    wash=False; wash_at overrides the wash timestamp (must be <= the current
    clock and fresh enough for the planned departure)."""
    driver = driver or create_driver()
    ctx = setup_verified_load(head_count, weight_lb, num_compartments,
                              **load_overrides)
    if wash:
        wash_trailer(ctx["trailer"]["id"],
                     washed_at=wash_at or "2026-08-01T00:30:00Z")
    assign_driver(ctx["load"]["id"], driver["id"])
    ctx["driver"] = get_driver(driver["id"])
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


def setup_in_transit_load(depart_at: str = "2026-08-02T08:00:00Z",
                          origin_temperature_f: int = 70,
                          **kwargs) -> dict:
    """An ASSIGNED load driven to IN_TRANSIT: departs at depart_at.

    System duty events are appended on the driver's log (PRD §3.5)."""
    ctx = setup_assigned_load(**kwargs)
    set_clock(depart_at)
    driver_id = ctx["driver"]["id"]
    get_success_data(api.depart(
        ctx["load"]["id"], {"origin_temperature_f": origin_temperature_f},
        make_driver_headers(driver_id)))
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


def setup_arrived_load(arrive_at: str = "2026-08-02T16:00:00Z", **kwargs) -> dict:
    """An in-transit load brought to ARRIVED (system DRIVING_OFF appended)."""
    ctx = setup_in_transit_load(**kwargs)
    set_clock(arrive_at)
    get_success_data(api.arrive(ctx["load"]["id"],
                                make_driver_headers(ctx["driver"]["id"])))
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


def record_delivery_ticket(load_id: str, net_lb: int, tare_lb: int = 6000,
                           weighed_at: str = "2026-08-02T15:30:00Z",
                           ticket_type: str = "DELIVERY") -> dict:
    return get_success_data(api.create_weight_ticket(
        load_id,
        create_weight_ticket_payload(ticket_type=ticket_type,
                                     gross_lb=net_lb + tare_lb,
                                     tare_lb=tare_lb, weighed_at=weighed_at),
        CONSIGNEE))


def setup_delivered_load(net_lb: int = None, deliver_at: str = "2026-08-02T16:30:00Z",
                         weighed_at: str = "2026-08-02T15:30:00Z",
                         **kwargs) -> dict:
    """Full trip through DELIVERED; settlement is PENDING with the final
    amounts computed from the latest DELIVERY ticket (net_lb defaults to the
    declared weight, i.e. an on-weight delivery with no shrink penalty).

    weighed_at is the delivery ticket's timestamp: it must not be later than
    the clock at recording time (the arrive_at of the trip) or the ticket is
    rejected with ERR_EVENT_IN_FUTURE (PRD scale-ticket rule)."""
    ctx = setup_arrived_load(**kwargs)
    net = net_lb if net_lb is not None else ctx["load"]["declared_weight_lb"]
    record_delivery_ticket(ctx["load"]["id"], net, weighed_at=weighed_at)
    set_clock(deliver_at)
    get_success_data(api.deliver(ctx["load"]["id"], CONSIGNEE))
    ctx["load"] = get_load(ctx["load"]["id"])
    ctx["settlement"] = get_settlement_of_load(ctx["load"]["id"])
    return ctx


def report_incident(load_id: str, driver_id: str, **overrides) -> dict:
    """The assigned driver reports a welfare incident on their own load."""
    return get_success_data(api.create_incident(
        create_incident_payload(load_id=load_id, **overrides),
        make_driver_headers(driver_id)))


def start_review(incident_id: str):
    get_success_data(api.start_incident_review(incident_id, CO2))


def close_incident(incident_id: str, fine_waived=None) -> dict:
    payload = {} if fine_waived is None else {"fine_waived": fine_waived}
    return get_success_data(api.close_incident(incident_id, payload, CO2))


def append_duty_event(driver_id: str, event_type: str, occurred_at: str) -> dict:
    return get_success_data(api.create_duty_event(
        driver_id,
        create_duty_event_payload(event_type=event_type, occurred_at=occurred_at),
        ADMIN))


def dispute(settlement_id: str, disputed_weight_lb: int) -> dict:
    return get_success_data(api.dispute_settlement(
        settlement_id, {"disputed_weight_lb": disputed_weight_lb}, CONSIGNEE))


def counter(settlement_id: str, counter_weight_lb: int) -> dict:
    """Counter with OCC: re-read the settlement for its current version."""
    settlement = get_success_data(api.get_settlement(settlement_id, ADMIN))
    return get_success_data(api.counter_settlement(
        settlement_id,
        {"counter_weight_lb": counter_weight_lb,
         "expected_settlement_version": settlement["version"]},
        DISP))
