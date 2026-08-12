"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints: the
harness restarts the server before each test, so nothing is ever carried over.
Setup calls use the lenient validator so a broken precondition surfaces as
"Setup step failed" rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    appointment_payload,
    client_payload,
    climate_reading_payload,
    consignment_agreement_payload,
    credit_adjustment_payload,
    instrument_payload,
    location_payload,
    move_job_payload,
    parts_allocation_payload,
    parts_lot_payload,
    quote_payload,
    route_day_payload,
    service_order_payload,
    technician_payload,
    warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_shop_manager_headers,
    make_showroom_agent_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
COORDINATOR = TEST_USERS["move_coordinator_headers"]
AGENT = TEST_USERS["showroom_agent_headers"]

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0 — single-call primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_daily_sweep() -> dict:
    return get_success_data(api_client.run_daily_sweep(ADMIN))


def new_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(client_payload(**overrides), MANAGER))


def new_location(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(location_payload(client_id, **overrides), MANAGER)
    )


def new_instrument(client_id: str, location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_instrument(
            instrument_payload(client_id, location_id, **overrides), MANAGER
        )
    )


def new_technician(**overrides) -> dict:
    return get_success_data(
        api_client.create_technician(technician_payload(**overrides), ADMIN)
    )


def fund_client(client_id: str, amount_cents: int, memo: str = "opening funds") -> dict:
    return get_success_data(
        api_client.create_credit_adjustment(
            client_id, credit_adjustment_payload(amount_cents, memo), MANAGER
        )
    )


def assess_pitch(instrument_id: str, measured_deviation_cents: float,
                 reference_pitch_hz: float = 440.0) -> dict:
    return get_success_data(
        api_client.create_pitch_assessment(
            instrument_id,
            {
                "reference_pitch_hz": reference_pitch_hz,
                "measured_deviation_cents": measured_deviation_cents,
            },
            MANAGER,
        )
    )


def set_condition(instrument_id: str, to_condition_status: str,
                  note: str = "assessed") -> dict:
    return get_success_data(
        api_client.create_condition_transition(
            instrument_id,
            {"to_condition_status": to_condition_status, "note": note},
            MANAGER,
        )
    )


def set_custody(instrument_id: str, to_custody_status: str,
                authorizing_move_job_id=None) -> dict:
    payload = {"to_custody_status": to_custody_status}
    if authorizing_move_job_id is not None:
        payload["authorizing_move_job_id"] = authorizing_move_job_id
    return get_success_data(
        api_client.create_custody_transition(instrument_id, payload, COORDINATOR)
    )


def read_instrument(instrument_id: str) -> dict:
    return get_success_data(api_client.get_instrument(instrument_id, MANAGER))


def instrument_version(instrument_id: str) -> int:
    return read_instrument(instrument_id)["version"]


def read_route_day(route_day_id: str) -> dict:
    return get_success_data(api_client.get_route_day(route_day_id, MANAGER))


def route_day_version(route_day_id: str) -> int:
    return read_route_day(route_day_id)["version"]


def read_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, MANAGER))


def read_service_order(service_order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(service_order_id, MANAGER))


def read_milestones(service_order_id: str) -> list:
    return get_success_data(
        api_client.list_service_order_milestones(service_order_id, MANAGER)
    )


def read_warranty(warranty_id: str) -> dict:
    return get_success_data(api_client.get_warranty(warranty_id, MANAGER))


def read_parts_lot(parts_lot_id: str) -> dict:
    return get_success_data(api_client.get_parts_lot(parts_lot_id, MANAGER))


def read_ledger(client_id: str, **filters) -> list:
    params = {"client_id": client_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_ledger_entries(MANAGER, params=params))


def warranty_for_instrument(instrument_id: str) -> dict:
    rows = get_success_data(
        api_client.list_warranties(MANAGER, params={"instrument_id": instrument_id})
    )
    assert rows, f"Setup step failed: no warranty exists for instrument {instrument_id}"
    return rows[0]


def add_climate_reading(location_id: str, recorded_at_utc: str,
                        relative_humidity_pct: float, **overrides) -> dict:
    return get_success_data(
        api_client.create_climate_reading(
            climate_reading_payload(
                location_id, recorded_at_utc, relative_humidity_pct, **overrides
            ),
            MANAGER,
        )
    )


def new_parts_lot(part_type: str = "HAMMER_SET", initial_qty: int = 4,
                  **overrides) -> dict:
    return get_success_data(
        api_client.create_parts_lot(
            parts_lot_payload(part_type, initial_qty, **overrides), MANAGER
        )
    )


def reserve_parts(service_order_id: str, parts_lot_id: str, requested_qty: int,
                  expected_parts_lot_version: int) -> dict:
    return get_success_data(
        api_client.create_parts_allocation(
            service_order_id,
            parts_allocation_payload(
                parts_lot_id, requested_qty, expected_parts_lot_version
            ),
            MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — quote and order lifecycle steps
# ---------------------------------------------------------------------------
def draft_quote(instrument_id: str, service_type: str, **overrides) -> dict:
    """Draft a quote, always quoting the instrument's freshly read version."""
    version = overrides.pop("expected_instrument_version", None)
    if version is None:
        version = instrument_version(instrument_id)
    return get_success_data(
        api_client.create_quote(
            quote_payload(instrument_id, service_type, version, **overrides), MANAGER
        )
    )


def issue_quote(quote_id: str) -> dict:
    return get_success_data(api_client.issue_quote(quote_id, MANAGER))


def approve_quote(quote_id: str, client_id: str) -> dict:
    return get_success_data(
        api_client.approve_quote(quote_id, make_client_headers(client_id))
    )


def new_service_order(quote_id: str, technician_id=None) -> dict:
    payload = service_order_payload(quote_id)
    if technician_id is not None:
        payload["assigned_technician_id"] = technician_id
    return get_success_data(api_client.create_service_order(payload, MANAGER))


def start_service_order(service_order_id: str) -> dict:
    return get_success_data(api_client.start_service_order(service_order_id, MANAGER))


def release_milestone(milestone_id: str, operator_user_id: str) -> dict:
    return get_success_data(
        api_client.release_milestone(
            milestone_id, make_shop_manager_headers(operator_user_id)
        )
    )


def accept_milestone(milestone_id: str, client_id: str) -> dict:
    return get_success_data(
        api_client.accept_milestone(milestone_id, make_client_headers(client_id))
    )


def complete_service_order(service_order_id: str) -> dict:
    return get_success_data(api_client.complete_service_order(service_order_id, MANAGER))


def new_route_day(technician_id: str, service_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_route_day(
            route_day_payload(technician_id, service_date, **overrides), MANAGER
        )
    )


def book_appointment(instrument_id: str, route_day_id: str, location_id: str,
                     scheduled_start_utc: str, service_type: str = "TUNE",
                     **overrides) -> dict:
    version = overrides.pop("expected_route_day_version", None)
    if version is None:
        version = route_day_version(route_day_id)
    return get_success_data(
        api_client.create_appointment(
            appointment_payload(
                instrument_id, route_day_id, location_id, scheduled_start_utc,
                service_type, version, **overrides,
            ),
            MANAGER,
        )
    )


def route_day_transition(route_day_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.create_route_day_status_transition(
            route_day_id, {"to_status": to_status}, MANAGER
        )
    )


def new_move_job(instrument_id: str, origin_location_id: str,
                 destination_location_id: str, distance_miles: float,
                 scheduled_window_start_utc: str, scheduled_window_end_utc: str,
                 **overrides) -> dict:
    return get_success_data(
        api_client.create_move_job(
            move_job_payload(
                instrument_id, origin_location_id, destination_location_id,
                distance_miles, scheduled_window_start_utc, scheduled_window_end_utc,
                **overrides,
            ),
            COORDINATOR,
        )
    )


def move_job_transition(move_job_id: str, to_status: str, reason=None) -> dict:
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.create_move_job_status_transition(move_job_id, payload, COORDINATOR)
    )


def file_warranty_claim(warranty_id: str, client_id: str,
                        expected_warranty_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            warranty_claim_payload(
                warranty_id, expected_warranty_version, **overrides
            ),
            make_client_headers(client_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------
def setup_client_with_instrument(client_type=None, zone_code="ZONE_A",
                                 instrument_class="UPRIGHT", usage_tier="HOME",
                                 climate_controlled=None, stair_flights=None,
                                 deviation=None, funding=None,
                                 target_pitch_hz=None, address_key=None) -> dict:
    """One client, one address, one instrument — the base of nearly every scenario."""
    client_over = {"home_zone_code": zone_code}
    if client_type is not None:
        client_over["client_type"] = client_type
    client = new_client(**client_over)

    location_over = {"zone_code": zone_code}
    if climate_controlled is not None:
        location_over["climate_controlled"] = climate_controlled
    if stair_flights is not None:
        location_over["stair_flights"] = stair_flights
    if address_key is not None:
        location_over["address_key"] = address_key
    location = new_location(client["id"], **location_over)

    instrument_over = {"instrument_class": instrument_class, "usage_tier": usage_tier}
    if target_pitch_hz is not None:
        instrument_over["target_pitch_hz"] = target_pitch_hz
    instrument = new_instrument(client["id"], location["id"], **instrument_over)

    if funding is not None:
        fund_client(client["id"], funding)
    if deviation is not None:
        assess_pitch(instrument["id"], deviation)
        instrument = read_instrument(instrument["id"])

    return {"client": client, "location": location, "instrument": instrument}


def move_instrument_to_shop(instrument_id: str) -> dict:
    """Walk the custody axis AT_CLIENT_SITE -> IN_TRANSIT -> IN_SHOP."""
    set_custody(instrument_id, "IN_TRANSIT")
    return set_custody(instrument_id, "IN_SHOP")


# ---------------------------------------------------------------------------
# Tier 3 — full quote-to-order lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_order(service_type="VOICE", instrument_class="UPRIGHT", client_type=None,
                zone_code="ZONE_A", deviation=1.0, condition="SERVICEABLE",
                funding=None, certification_level="JOURNEYMAN",
                climate_controlled=None, in_shop=False, start=False,
                usage_tier="STUDIO") -> dict:
    """Client + address + instrument + technician + approved quote + service order.

    `condition` names the condition_status the instrument is driven to before the
    quote is drafted (None leaves it at NEEDS_ASSESSMENT).  `start` additionally
    starts the order, which readies every milestone.
    """
    base = setup_client_with_instrument(
        client_type=client_type, zone_code=zone_code,
        instrument_class=instrument_class, usage_tier=usage_tier,
        climate_controlled=climate_controlled, deviation=deviation, funding=funding,
    )
    client, location, instrument = base["client"], base["location"], base["instrument"]

    technician = new_technician(
        certification_level=certification_level, zone_codes=[zone_code]
    )

    if condition is not None:
        set_condition(instrument["id"], condition)
    if in_shop:
        move_instrument_to_shop(instrument["id"])

    quote = draft_quote(instrument["id"], service_type)
    issue_quote(quote["id"])
    approve_quote(quote["id"], client["id"])
    order = new_service_order(quote["id"], technician["id"])

    result = {
        "client": client,
        "location": location,
        "instrument": read_instrument(instrument["id"]),
        "technician": technician,
        "quote": get_success_data(api_client.get_quote(quote["id"], MANAGER)),
        "order": order,
    }
    if start:
        result["order"] = start_service_order(order["id"])
    result["milestones"] = read_milestones(order["id"])
    return result


def setup_voice_order_in_progress(funding=200000) -> dict:
    """A 42000-cent VOICE order IN_PROGRESS with two 21000-cent READY milestones."""
    return setup_order(
        service_type="VOICE", instrument_class="UPRIGHT", funding=funding,
        condition="SERVICEABLE", certification_level="JOURNEYMAN", start=True,
    )


def setup_rebuild_order_pending(client_type=None, instrument_class="UPRIGHT",
                                deviation=48.0, funding=None, in_shop=False) -> dict:
    """An approved REBUILD quote realised as a PENDING service order."""
    return setup_order(
        service_type="REBUILD", instrument_class=instrument_class,
        client_type=client_type, deviation=deviation, condition="REBUILD_REQUIRED",
        funding=funding, certification_level="MASTER", in_shop=in_shop,
        usage_tier="HOME", start=False,
    )


def setup_completed_tune_order(funding=100000, climate_controlled=None) -> dict:
    """A 19500-cent TUNE order carried through to COMPLETED, minting a warranty."""
    ctx = setup_order(
        service_type="TUNE", instrument_class="UPRIGHT", deviation=2.0,
        condition=None, funding=funding, certification_level="APPRENTICE",
        climate_controlled=climate_controlled, usage_tier="HOME", start=True,
    )
    milestone = ctx["milestones"][0]
    release_milestone(milestone["id"], "mgr-release-op")
    accept_milestone(milestone["id"], ctx["client"]["id"])
    ctx["order"] = complete_service_order(ctx["order"]["id"])
    ctx["milestones"] = read_milestones(ctx["order"]["id"])
    ctx["warranty"] = warranty_for_instrument(ctx["instrument"]["id"])
    ctx["releaser_user_id"] = "mgr-release-op"
    return ctx


def setup_submitted_warranty_claim(clock="2026-06-20T00:00:00Z",
                                   funding=100000) -> dict:
    """A completed TUNE order, the clock advanced, and one SUBMITTED claim."""
    ctx = setup_completed_tune_order(funding=funding)
    set_clock(clock)
    warranty = read_warranty(ctx["warranty"]["id"])
    ctx["claim"] = file_warranty_claim(
        warranty["id"], ctx["client"]["id"], warranty["version"]
    )
    ctx["warranty"] = read_warranty(warranty["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — showroom and consignment
# ---------------------------------------------------------------------------
def setup_listed_consignment(reserve_price_cents=900000,
                             creator_user_id="agent-create-1") -> dict:
    """An instrument IN_SHOP, consigned, activated and listed to the showroom floor."""
    base = setup_client_with_instrument()
    client, instrument = base["client"], base["instrument"]
    buyer = new_client()
    move_instrument_to_shop(instrument["id"])

    creator = make_showroom_agent_headers(creator_user_id)
    agreement = get_success_data(
        api_client.create_consignment_agreement(
            consignment_agreement_payload(
                instrument["id"], client["id"], reserve_price_cents,
                instrument_version(instrument["id"]),
            ),
            creator,
        )
    )
    get_success_data(
        api_client.activate_consignment_agreement(agreement["id"], creator)
    )
    agreement = get_success_data(
        api_client.list_showroom_consignment_agreement(agreement["id"], creator)
    )
    return {
        "client": client,
        "buyer": buyer,
        "location": base["location"],
        "instrument": read_instrument(instrument["id"]),
        "agreement": agreement,
        "creator_user_id": creator_user_id,
    }


# ---------------------------------------------------------------------------
# Tier 5 — route days and stops
# ---------------------------------------------------------------------------
def setup_route_day_scenario(service_date="2026-05-04", zone_code="ZONE_A",
                             certification_level="APPRENTICE", capacity_minutes=None,
                             deviation=2.0, instrument_class="UPRIGHT",
                             client_zone=None) -> dict:
    """One assessed instrument, one technician and one OPEN route day."""
    base = setup_client_with_instrument(
        zone_code=zone_code, instrument_class=instrument_class, deviation=deviation,
    )
    if client_zone is not None:
        base["client"] = get_success_data(
            api_client.update_client(
                base["client"]["id"], {"home_zone_code": client_zone}, MANAGER
            )
        )
    technician = new_technician(
        certification_level=certification_level, zone_codes=[zone_code]
    )
    overrides = {}
    if capacity_minutes is not None:
        overrides["capacity_minutes"] = capacity_minutes
    route_day = new_route_day(technician["id"], service_date, **overrides)
    return {
        "client": base["client"],
        "location": base["location"],
        "instrument": base["instrument"],
        "technician": technician,
        "route_day": route_day,
    }


def setup_instrument_with_dispatched_move_job(instrument_class="UPRIGHT") -> dict:
    """One instrument at a residence, a move-certified crew lead, and a DISPATCHED job
    carrying the instrument to the shop's receiving bay."""
    base = setup_client_with_instrument(
        instrument_class=instrument_class, deviation=3.0, address_key="residence-key"
    )
    client, home, instrument = base["client"], base["location"], base["instrument"]
    shop = new_location(
        client["id"], label="Receiving Bay", address_key="shop-yard-key",
        distance_miles_from_shop=0.0, climate_controlled=True,
    )
    set_condition(instrument["id"], "SERVICEABLE")
    technician = new_technician(move_certified=True, zone_codes=["ZONE_A"])
    job = new_move_job(
        instrument["id"], home["id"], shop["id"], 9.0,
        "2026-05-06T09:00:00Z", "2026-05-06T12:00:00Z",
        move_technician_id=technician["id"],
    )
    move_job_transition(job["id"], "SCHEDULED")
    job = move_job_transition(job["id"], "DISPATCHED")
    return {
        "client": client,
        "home_location": home,
        "shop_location": shop,
        "instrument": read_instrument(instrument["id"]),
        "technician": technician,
        "move_job": job,
    }


def setup_voice_order_on_hold_after_no_show(funding=200000) -> dict:
    """A VOICE order driven to ON_HOLD by a no-show on its linked stop."""
    ctx = setup_voice_order_in_progress(funding=funding)
    set_clock("2026-05-03T14:00:00Z")
    route_day = new_route_day(ctx["technician"]["id"], "2026-05-04")
    appointment = book_appointment(
        ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
        "2026-05-04T09:00:00Z", "VOICE", service_order_id=ctx["order"]["id"],
    )
    route_day_transition(route_day["id"], "LOCKED")
    route_day_transition(route_day["id"], "DISPATCHED")
    appointment = get_success_data(
        api_client.no_show_appointment(
            appointment["id"], make_technician_headers(ctx["technician"]["id"])
        )
    )
    ctx["route_day"] = read_route_day(route_day["id"])
    ctx["appointment"] = appointment
    ctx["order"] = read_service_order(ctx["order"]["id"])
    ctx["milestones"] = read_milestones(ctx["order"]["id"])
    return ctx


def setup_approved_quote_without_order(service_type="VOICE",
                                       certification_level="APPRENTICE",
                                       condition="SERVICEABLE", deviation=2.0,
                                       instrument_class="UPRIGHT") -> dict:
    """An APPROVED quote plus a technician, stopping short of the service order."""
    base = setup_client_with_instrument(
        instrument_class=instrument_class, deviation=deviation
    )
    technician = new_technician(
        certification_level=certification_level, zone_codes=["ZONE_A"]
    )
    if condition is not None:
        set_condition(base["instrument"]["id"], condition)
    quote = draft_quote(base["instrument"]["id"], service_type)
    issue_quote(quote["id"])
    approve_quote(quote["id"], base["client"]["id"])
    base["technician"] = technician
    base["quote"] = quote
    return base


def setup_two_day_cancellation_scenario() -> dict:
    """One instrument holding a stop exactly 72 hours out and one 71.983 hours out."""
    base = setup_client_with_instrument(deviation=1.0)
    client, location, instrument = base["client"], base["location"], base["instrument"]
    technician = new_technician(
        certification_level="APPRENTICE", zone_codes=["ZONE_A"]
    )
    near_day = new_route_day(technician["id"], "2026-05-03")
    exact_day = new_route_day(technician["id"], "2026-05-04")
    near_stop = book_appointment(
        instrument["id"], near_day["id"], location["id"],
        "2026-05-03T23:59:00Z", "TUNE",
    )
    exact_stop = book_appointment(
        instrument["id"], exact_day["id"], location["id"],
        "2026-05-04T00:00:00Z", "TUNE",
    )
    return {
        "client": client,
        "location": location,
        "instrument": instrument,
        "technician": technician,
        "near_day": near_day,
        "exact_day": exact_day,
        "near_stop": near_stop,
        "exact_stop": exact_stop,
    }


def setup_partially_dispatchable_route_day() -> dict:
    """A LOCKED route day carrying a TUNE stop then a REGULATE stop, whose technician
    has since been downgraded to APPRENTICE."""
    set_clock("2026-05-03T14:00:00Z")
    client = new_client(home_zone_code="ZONE_A")
    site_a = new_location(client["id"], label="Site A", address_key="dispatch-site-a")
    site_b = new_location(client["id"], label="Site B", address_key="dispatch-site-b")
    instrument_a = new_instrument(client["id"], site_a["id"], usage_tier="HOME")
    instrument_b = new_instrument(client["id"], site_b["id"], usage_tier="STUDIO")
    assess_pitch(instrument_a["id"], 2.0)
    assess_pitch(instrument_b["id"], 2.0)
    set_condition(instrument_b["id"], "SERVICEABLE")

    technician = new_technician(
        certification_level="JOURNEYMAN", zone_codes=["ZONE_A"]
    )
    route_day = new_route_day(technician["id"], "2026-05-04")
    tune_stop = book_appointment(
        instrument_a["id"], route_day["id"], site_a["id"],
        "2026-05-04T09:00:00Z", "TUNE",
    )
    regulate_stop = book_appointment(
        instrument_b["id"], route_day["id"], site_b["id"],
        "2026-05-04T10:25:00Z", "REGULATE",
    )
    get_success_data(
        api_client.update_technician(
            technician["id"], {"certification_level": "APPRENTICE"}, ADMIN
        )
    )
    route_day_transition(route_day["id"], "LOCKED")
    return {
        "client": client,
        "technician": technician,
        "route_day": read_route_day(route_day["id"]),
        "tune_stop": tune_stop,
        "regulate_stop": regulate_stop,
    }


def setup_completed_rebuild_order(funding=2000000, deviation=70.0,
                                  releaser_user_id="mgr-rebuild-release") -> dict:
    """A REBUILD order carried to COMPLETED with the instrument standing IN_SHOP."""
    ctx = setup_order(
        service_type="REBUILD", instrument_class="UPRIGHT", deviation=deviation,
        condition="REBUILD_REQUIRED", funding=funding, certification_level="MASTER",
        in_shop=True, usage_tier="HOME", start=True,
    )
    for milestone in sorted(ctx["milestones"], key=lambda m: m["sequence_index"]):
        release_milestone(milestone["id"], releaser_user_id)
        accept_milestone(milestone["id"], ctx["client"]["id"])
    ctx["order"] = complete_service_order(ctx["order"]["id"])
    ctx["milestones"] = read_milestones(ctx["order"]["id"])
    ctx["instrument"] = read_instrument(ctx["instrument"]["id"])
    ctx["warranty"] = warranty_for_instrument(ctx["instrument"]["id"])
    ctx["releaser_user_id"] = releaser_user_id
    return ctx


def setup_listed_consignment_with_rebuild_advance(reserve_price_cents=1800000,
                                                  creator_user_id="agent-advance-1") -> dict:
    """A restored instrument listed on the showroom floor, carrying a recoverable
    restoration advance from its COMPLETED REBUILD order."""
    ctx = setup_completed_rebuild_order()
    buyer = new_client()
    creator = make_showroom_agent_headers(creator_user_id)
    agreement = get_success_data(
        api_client.create_consignment_agreement(
            consignment_agreement_payload(
                ctx["instrument"]["id"], ctx["client"]["id"], reserve_price_cents,
                instrument_version(ctx["instrument"]["id"]),
            ),
            creator,
        )
    )
    get_success_data(api_client.activate_consignment_agreement(agreement["id"], creator))
    agreement = get_success_data(
        api_client.list_showroom_consignment_agreement(agreement["id"], creator)
    )
    ctx["buyer"] = buyer
    ctx["agreement"] = agreement
    ctx["creator_user_id"] = creator_user_id
    return ctx


def setup_rebuild_quote_over_voice_order(funding=200000) -> dict:
    """An in-flight VOICE order on an instrument that also carries an ISSUED REBUILD
    quote — the state Cascade B fires from."""
    ctx = setup_voice_order_in_progress(funding=funding)
    rebuild_quote = draft_quote(ctx["instrument"]["id"], "REBUILD")
    issue_quote(rebuild_quote["id"])
    ctx["rebuild_quote"] = rebuild_quote
    ctx["voice_quote"] = ctx["quote"]
    return ctx
