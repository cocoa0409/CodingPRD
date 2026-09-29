"""Composite setup helpers — the multi-step preambles the PRD workflows need.

Every helper drives the public API only, and uses ``get_success_data`` so a
broken preamble surfaces as an explicit "Setup step failed" instead of a
confusing downstream assertion.  Nothing is carried between tests: the server
is relaunched with an empty database before each one, so every fixture rebuilds
its world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_ACTIVATION,
    CLOCK_REFERENCE,
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_DIESEL_POSTING_DATE,
    DEFAULT_DIESEL_PRICE,
    DEFAULT_GAUGE_STATION,
    DEFAULT_READING_AT,
    DEFAULT_STAGE_FEET,
    DEPARTED_AT,
    STANDARD_DISCHARGES,
    TEST_DEFAULTS,
    TOW_ARRIVED_AT,
)
from .factories import (
    complete_cleaning_order_payload,
    create_barge_assignment_payload,
    create_barge_payload,
    create_cargo_claim_payload,
    create_cleaning_order_payload,
    create_commodity_payload,
    create_compatibility_rule_payload,
    create_fleeting_assignment_payload,
    create_fleeting_berth_payload,
    create_freight_contract_payload,
    create_fuel_index_posting_payload,
    create_lock_payload,
    create_lock_reservation_payload,
    create_river_stage_reading_payload,
    create_shipper_payload,
    create_tariff_filing_payload,
    create_tow_payload,
    next_hull_number,
)
from .test_users import (
    ADJUSTER_APPROVER_USER_ID,
    ADJUSTER_ASSESSOR_USER_ID,
    ANALYST_USER_ID,
    RATE_AUTHORITY_USER_ID,
    make_claims_adjuster_headers,
    make_contract_manager_headers,
    make_harbor_agent_headers,
    make_lock_master_headers,
    make_rate_authority_headers,
    make_tariff_analyst_headers,
    make_towboat_dispatcher_headers,
    make_waterway_admin_headers,
)

ADMIN = make_waterway_admin_headers()
ANALYST = make_tariff_analyst_headers()
RATE = make_rate_authority_headers()
DISPATCH = make_towboat_dispatcher_headers()
HARBOR = make_harbor_agent_headers()
BILLER = make_contract_manager_headers()
ADJUSTER = make_claims_adjuster_headers()


# ---------------------------------------------------------------------------
# Tier 1 — atomic creation / transition wrappers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_shipper(**overrides):
    return get_success_data(
        api_client.create_shipper(create_shipper_payload(**overrides), BILLER))


def create_commodity(**overrides):
    return get_success_data(
        api_client.create_commodity(create_commodity_payload(**overrides), ADMIN))


def create_compatibility_rule(prior_group, next_group, **overrides):
    return get_success_data(api_client.create_compatibility_rule(
        create_compatibility_rule_payload(prior_group, next_group, **overrides), ADMIN))


def create_fuel_posting(**overrides):
    return get_success_data(api_client.create_fuel_index_posting(
        create_fuel_index_posting_payload(**overrides), ANALYST))


def create_river_reading(**overrides):
    return get_success_data(api_client.create_river_stage_reading(
        create_river_stage_reading_payload(**overrides), ADMIN))


def create_barge(**overrides):
    return get_success_data(
        api_client.create_barge(create_barge_payload(**overrides), ADMIN))


def create_fleeting_berth(**overrides):
    return get_success_data(api_client.create_fleeting_berth(
        create_fleeting_berth_payload(**overrides), ADMIN))


def create_lock(**overrides):
    return get_success_data(
        api_client.create_lock(create_lock_payload(**overrides), ADMIN))


def create_tow(**overrides):
    return get_success_data(
        api_client.create_tow(create_tow_payload(**overrides), DISPATCH))


def draft_tariff(analyst_user_id=ANALYST_USER_ID, **overrides):
    return get_success_data(api_client.create_tariff_filing(
        create_tariff_filing_payload(**overrides),
        make_tariff_analyst_headers(analyst_user_id)))


def file_tariff(tariff_filing_id, analyst_user_id=ANALYST_USER_ID):
    return get_success_data(api_client.file_tariff_filing(
        tariff_filing_id, make_tariff_analyst_headers(analyst_user_id)))


def effectuate_tariff(tariff_filing_id, rate_user_id=RATE_AUTHORITY_USER_ID):
    return get_success_data(api_client.effectuate_tariff_filing(
        tariff_filing_id, make_rate_authority_headers(rate_user_id)))


def create_effective_tariff(**overrides):
    """Draft -> FILED (analyst-1) -> EFFECTIVE (rate-1)."""
    filing = draft_tariff(**overrides)
    file_tariff(filing["id"])
    return effectuate_tariff(filing["id"])


def create_contract(shipper_id, commodity_id, **overrides):
    return get_success_data(api_client.create_freight_contract(
        create_freight_contract_payload(shipper_id, commodity_id, **overrides), BILLER))


def book_contract(contract_id):
    return get_success_data(api_client.book_freight_contract(contract_id, BILLER))


def activate_contract(contract_id):
    return get_success_data(api_client.activate_freight_contract(contract_id, BILLER))


def create_active_contract(shipper_id, commodity_id, **overrides):
    contract = create_contract(shipper_id, commodity_id, **overrides)
    book_contract(contract["id"])
    return activate_contract(contract["id"])


def add_assignment(tow_id, barge_id, contract_id, loaded_tons=None, cut_position=1,
                   **overrides):
    return get_success_data(api_client.create_barge_assignment(
        tow_id,
        create_barge_assignment_payload(
            barge_id, contract_id, loaded_tons=loaded_tons,
            cut_position=cut_position, **overrides),
        DISPATCH))


def seal_tow(tow_id):
    return get_success_data(api_client.seal_tow(tow_id, DISPATCH))


def depart_tow(tow_id, departed_at=DEPARTED_AT):
    return get_success_data(
        api_client.depart_tow(tow_id, {"departed_at": departed_at}, DISPATCH))


def arrive_tow(tow_id, arrived_at=TOW_ARRIVED_AT):
    return get_success_data(
        api_client.arrive_tow(tow_id, {"arrived_at": arrived_at}, DISPATCH))


def break_up_tow(tow_id):
    return get_success_data(api_client.break_up_tow(tow_id, DISPATCH))


def adjust_load(tow_id, expected_tow_version=None):
    if expected_tow_version is None:
        expected_tow_version = read_tow(tow_id)["version"]
    return get_success_data(api_client.adjust_tow_load(
        tow_id, {"expected_tow_version": expected_tow_version}, DISPATCH))


def drop_assignment(assignment_id):
    return get_success_data(api_client.drop_barge_assignment(assignment_id, DISPATCH))


def record_barge_arrival(assignment_id, arrived_at):
    return get_success_data(api_client.record_barge_arrival(
        assignment_id, {"arrived_at": arrived_at}, DISPATCH))


def start_unload(assignment_id, unload_started_at):
    return get_success_data(api_client.start_unload(
        assignment_id, {"unload_started_at": unload_started_at}, DISPATCH))


def finish_unload(assignment_id, unload_finished_at, discharged_tons):
    return get_success_data(api_client.finish_unload(
        assignment_id,
        {"unload_finished_at": unload_finished_at, "discharged_tons": discharged_tons},
        DISPATCH))


def discharge_assignment(assignment_id, timetable):
    """Tender, start and finish one barge from a discharge timetable dict."""
    record_barge_arrival(assignment_id, timetable["arrived_at"])
    start_unload(assignment_id, timetable["unload_started_at"])
    return finish_unload(
        assignment_id, timetable["unload_finished_at"], timetable["discharged_tons"])


def create_fleeting_assignment(barge_id, berth_id, **overrides):
    return get_success_data(api_client.create_fleeting_assignment(
        create_fleeting_assignment_payload(barge_id, berth_id, **overrides), HARBOR))


def release_fleeting_assignment(assignment_id, released_at):
    return get_success_data(api_client.release_fleeting_assignment(
        assignment_id, {"released_at": released_at}, HARBOR))


def cancel_fleeting_assignment(assignment_id):
    return get_success_data(
        api_client.cancel_fleeting_assignment(assignment_id, HARBOR))


def create_cleaning_order(barge_id, commodity_id, **overrides):
    return get_success_data(api_client.create_cleaning_order(
        barge_id, create_cleaning_order_payload(commodity_id, **overrides), HARBOR))


def start_cleaning_order(order_id):
    return get_success_data(api_client.start_cleaning_order(order_id, HARBOR))


def complete_cleaning_order(order_id, performed_level="WASH",
                            certificate_number="CERT-1", inspection_passed=True):
    return get_success_data(api_client.complete_cleaning_order(
        order_id,
        complete_cleaning_order_payload(
            performed_level, certificate_number, inspection_passed),
        HARBOR))


def request_lock_slot(lock_id, tow_id, requested_start_at, expected_tow_version=None,
                      **overrides):
    if expected_tow_version is None:
        expected_tow_version = read_tow(tow_id)["version"]
    return get_success_data(api_client.create_lock_reservation(
        create_lock_reservation_payload(
            lock_id, tow_id, requested_start_at, expected_tow_version, **overrides),
        DISPATCH))


def grant_lock_slot(reservation_id, lock_id):
    return get_success_data(api_client.grant_lock_reservation(
        reservation_id, make_lock_master_headers(lock_id)))


def enter_chamber(reservation_id, actual_start_at):
    return get_success_data(api_client.enter_chamber(
        reservation_id, {"actual_start_at": actual_start_at}, DISPATCH))


def clear_chamber(reservation_id, actual_end_at):
    return get_success_data(api_client.clear_chamber(
        reservation_id, {"actual_end_at": actual_end_at}, DISPATCH))


def set_lock_status(lock_id, status, headers=None):
    return get_success_data(api_client.set_lock_status(
        lock_id, {"status": status}, headers or make_lock_master_headers(lock_id)))


def issue_invoice(contract_id, shipper_id, expected_shipper_version=None):
    """Read the shipper's live version, then issue the bill against it."""
    if expected_shipper_version is None:
        expected_shipper_version = read_shipper(shipper_id)["version"]
    return get_success_data(api_client.issue_invoice(
        contract_id, {"expected_shipper_version": expected_shipper_version}, BILLER))


def mark_paid(contract_id, paid_amount_cents):
    return get_success_data(api_client.mark_contract_paid(
        contract_id, {"paid_amount_cents": paid_amount_cents}, BILLER))


def file_claim(contract_id, assignment_id, headers=None, **overrides):
    return get_success_data(api_client.create_cargo_claim(
        create_cargo_claim_payload(contract_id, assignment_id, **overrides),
        headers or make_claims_adjuster_headers(ADJUSTER_ASSESSOR_USER_ID)))


def begin_claim_review(claim_id, user_id=ADJUSTER_ASSESSOR_USER_ID):
    return get_success_data(api_client.begin_claim_review(
        claim_id, make_claims_adjuster_headers(user_id)))


def assess_claim(claim_id, user_id=ADJUSTER_ASSESSOR_USER_ID):
    return get_success_data(api_client.assess_cargo_claim(
        claim_id, make_claims_adjuster_headers(user_id)))


def approve_claim(claim_id, user_id=ADJUSTER_APPROVER_USER_ID):
    return get_success_data(api_client.approve_cargo_claim(
        claim_id, make_claims_adjuster_headers(user_id)))


def deny_claim(claim_id, denial_reason="Not supported.",
               user_id=ADJUSTER_APPROVER_USER_ID):
    return get_success_data(api_client.deny_cargo_claim(
        claim_id, {"denial_reason": denial_reason},
        make_claims_adjuster_headers(user_id)))


# ---------------------------------------------------------------------------
# Read helpers — always re-read, never trust a stale local copy
# ---------------------------------------------------------------------------
def read_shipper(shipper_id):
    return get_success_data(api_client.get_shipper(shipper_id, BILLER))


def read_tariff(tariff_filing_id):
    return get_success_data(api_client.get_tariff_filing(tariff_filing_id, ANALYST))


def read_barge(barge_id):
    return get_success_data(api_client.get_barge(barge_id, ADMIN))


def read_cleaning_order(order_id):
    return get_success_data(api_client.get_cleaning_order(order_id, HARBOR))


def read_berth(berth_id):
    return get_success_data(api_client.get_fleeting_berth(berth_id, HARBOR))


def read_fleeting_assignment(assignment_id):
    return get_success_data(api_client.get_fleeting_assignment(assignment_id, HARBOR))


def read_lock(lock_id):
    return get_success_data(api_client.get_lock(lock_id, ADMIN))


def read_reservation(reservation_id):
    return get_success_data(api_client.get_lock_reservation(reservation_id, DISPATCH))


def read_tow(tow_id):
    return get_success_data(api_client.get_tow(tow_id, DISPATCH))


def read_assignment(assignment_id):
    return get_success_data(api_client.get_barge_assignment(assignment_id, DISPATCH))


def read_contract(contract_id):
    return get_success_data(api_client.get_freight_contract(contract_id, BILLER))


def read_claim(claim_id):
    return get_success_data(api_client.get_cargo_claim(claim_id, ADJUSTER))


def read_breakdown(contract_id, variant=None):
    params = None if variant is None else {"variant": variant}
    return get_success_data(
        api_client.get_charge_breakdown(contract_id, BILLER, params=params))


# ---------------------------------------------------------------------------
# Tier 2 — reference-data preamble
# ---------------------------------------------------------------------------
def setup_grain_reference(
    stage_feet=DEFAULT_STAGE_FEET,
    gauge_station=DEFAULT_GAUGE_STATION,
    reading_at=DEFAULT_READING_AT,
    with_stage_reading=True,
    diesel_price=DEFAULT_DIESEL_PRICE,
    posting_date=DEFAULT_DIESEL_POSTING_DATE,
    with_fuel_posting=True,
    credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
    shipper_name="Delta Grain Co",
    effective_from="2026-08-01T00:00:00Z",
    effective_to="2026-12-31T23:59:59Z",
    with_tariff=True,
    reference_clock=CLOCK_REFERENCE,
    activation_clock=CLOCK_ACTIVATION,
):
    """Lay down the shared reference layer for a GRAIN movement.

    Clock is moved to the reference epoch, a CORN commodity is registered, a
    GRAIN tariff is filed by analyst-1 and effectuated by rate-1, a diesel price
    is posted, a gauge reading is recorded and a shipper account is opened.  The
    clock is left at the activation epoch.  Pass ``reference_clock=None`` and
    ``activation_clock=None`` to leave the logical clock untouched.
    """
    if reference_clock is not None:
        set_clock(reference_clock)
    commodity = create_commodity(code="CORN", commodity_group="GRAIN")
    tariff = None
    if with_tariff:
        tariff = create_effective_tariff(
            commodity_group="GRAIN",
            effective_from=effective_from,
            effective_to=effective_to)
    if with_fuel_posting:
        create_fuel_posting(
            posting_date=posting_date, diesel_price_cents_per_gallon=diesel_price)
    if with_stage_reading:
        create_river_reading(
            gauge_station=gauge_station, reading_at=reading_at, stage_feet=stage_feet)
    shipper = create_shipper(
        name=shipper_name, credit_limit_cents=credit_limit_cents)
    if activation_clock is not None:
        set_clock(activation_clock)
    return {
        "commodity": commodity,
        "commodity_id": commodity["id"],
        "tariff": tariff,
        "shipper": shipper,
        "shipper_id": shipper["id"],
        "gauge_station": gauge_station,
    }


# ---------------------------------------------------------------------------
# Tier 3 — full voyage lifecycle
# ---------------------------------------------------------------------------
MOVEMENT_STAGES = ("BUILDING", "SEALED", "UNDERWAY", "ARRIVED", "DISCHARGED")


def setup_grain_movement(
    loads=(1700,),
    capacities=None,
    stage="BUILDING",
    contracted_tons=None,
    reference=None,
    ref_kwargs=None,
    contract_kwargs=None,
    tow_kwargs=None,
    barge_kwargs=None,
    discharges=None,
    departed_at=DEPARTED_AT,
    tow_arrived_at=TOW_ARRIVED_AT,
):
    """Build a single-contract grain movement and drive it to ``stage``.

    ``loads`` is one entry per cut, in ascending cut_position order.  The
    returned dict carries the freshly-read tow, contract and assignments plus
    every reference row the movement was built on.
    """
    assert stage in MOVEMENT_STAGES, f"unknown movement stage {stage!r}"
    ref = reference or setup_grain_reference(**(ref_kwargs or {}))
    caps = capacities or [TEST_DEFAULTS["CAPACITY_TONS"]] * len(loads)
    barge_kwargs = barge_kwargs or {}

    barges = [
        create_barge(hull_number=next_hull_number(), capacity_tons=cap, **barge_kwargs)
        for cap in caps
    ]
    contract = create_active_contract(
        ref["shipper_id"], ref["commodity_id"],
        contracted_tons=contracted_tons if contracted_tons is not None else sum(loads),
        **(contract_kwargs or {}))
    tow_payload = dict(controlling_gauge_station=ref["gauge_station"])
    tow_payload.update(tow_kwargs or {})
    tow = create_tow(**tow_payload)

    assignments = []
    for index, (barge, tons) in enumerate(zip(barges, loads), start=1):
        assignments.append(
            add_assignment(tow["id"], barge["id"], contract["id"],
                           loaded_tons=tons, cut_position=index))

    if stage in ("SEALED", "UNDERWAY", "ARRIVED", "DISCHARGED"):
        seal_tow(tow["id"])
    if stage in ("UNDERWAY", "ARRIVED", "DISCHARGED"):
        depart_tow(tow["id"], departed_at)
    if stage in ("ARRIVED", "DISCHARGED"):
        arrive_tow(tow["id"], tow_arrived_at)
    if stage == "DISCHARGED":
        timetables = discharges or STANDARD_DISCHARGES
        for assignment, timetable in zip(assignments, timetables):
            discharge_assignment(assignment["id"], timetable)

    return {
        "reference": ref,
        "commodity": ref["commodity"],
        "commodity_id": ref["commodity_id"],
        "tariff": ref["tariff"],
        "shipper": read_shipper(ref["shipper_id"]),
        "shipper_id": ref["shipper_id"],
        "barges": [read_barge(b["id"]) for b in barges],
        "contract": read_contract(contract["id"]),
        "contract_id": contract["id"],
        "tow": read_tow(tow["id"]),
        "tow_id": tow["id"],
        "assignments": [read_assignment(a["id"]) for a in assignments],
    }


def setup_invoiced_movement(**kwargs):
    """A discharged movement whose bill has been issued against the live
    shipper version.  Returns the movement dict with refreshed rows."""
    kwargs.setdefault("stage", "DISCHARGED")
    movement = setup_grain_movement(**kwargs)
    issue_invoice(movement["contract_id"], movement["shipper_id"])
    movement["contract"] = read_contract(movement["contract_id"])
    movement["shipper"] = read_shipper(movement["shipper_id"])
    return movement


def setup_claim_under_review(claim_kwargs=None, claim_clock="2026-08-22T00:00:00Z",
                             invoiced=False, **kwargs):
    """A discharged (optionally invoiced) movement carrying a cargo claim that
    has been taken into review by adjuster adj-1."""
    movement = setup_invoiced_movement(**kwargs) if invoiced \
        else setup_grain_movement(stage="DISCHARGED", **kwargs)
    if claim_clock is not None:
        set_clock(claim_clock)
    claim = file_claim(
        movement["contract_id"], movement["assignments"][0]["id"],
        **(claim_kwargs or {}))
    begin_claim_review(claim["id"])
    movement["claim"] = read_claim(claim["id"])
    movement["claim_id"] = claim["id"]
    return movement


def setup_assessed_claim(claim_kwargs=None, invoiced=True, **kwargs):
    """A movement whose claim has been assessed by adj-1, so both settlement
    variants are stored and approval is one call away."""
    movement = setup_claim_under_review(
        claim_kwargs=claim_kwargs, invoiced=invoiced, **kwargs)
    assess_claim(movement["claim_id"])
    movement["claim"] = read_claim(movement["claim_id"])
    return movement


# ---------------------------------------------------------------------------
# Tier 4 — lock scheduling preambles
# ---------------------------------------------------------------------------
def setup_underway_tow_at_lock(requested_start_at="2026-08-14T14:00:00Z",
                               lock_kwargs=None, **kwargs):
    """A departed one-barge movement holding a GRANTED slot at a chamber, with
    the tow already inside that chamber."""
    lock = create_lock(**(lock_kwargs or {}))
    movement = setup_grain_movement(stage="UNDERWAY", **kwargs)
    reservation = request_lock_slot(lock["id"], movement["tow_id"], requested_start_at)
    grant_lock_slot(reservation["id"], lock["id"])
    movement["lock"] = read_lock(lock["id"])
    movement["lock_id"] = lock["id"]
    movement["reservation"] = read_reservation(reservation["id"])
    movement["reservation_id"] = reservation["id"]
    return movement


def setup_empty_tows(count=1, **tow_kwargs):
    """N tows still in BUILDING with no assignments — enough for chamber-window
    arithmetic, which is sized from ``barge_count``."""
    names = ["M/V Alpha", "M/V Bravo", "M/V Charlie", "M/V Delta", "M/V Echo"]
    tows = []
    for index in range(count):
        payload = dict(towboat_name=names[index % len(names)])
        payload.update(tow_kwargs)
        tows.append(create_tow(**payload))
    return tows
