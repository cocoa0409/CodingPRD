"""Composite setup builders and pytest fixtures.

The harness restarts the platform before every test, so nothing here may
assume pre-existing data: every builder walks the public endpoints of the
PRD to bring the platform to the posture a test needs, starting from the
logical clock and the registration of a plant.

Builders are plain functions so a test can vary any input; the pytest
fixtures at the foot of the module wrap the most frequently reused chains.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.constants import DEFAULT_LOGICAL_CLOCK
from test_helpers.factories import (
    approve_claim_payload,
    clearing_result_payload,
    create_capacity_obligation_payload,
    create_capacity_test_payload,
    create_dispatch_instruction_payload,
    create_market_bid_payload,
    create_safety_event_payload,
    create_soc_reservation_payload,
    create_storage_asset_payload,
    create_telemetry_sample_payload,
    create_warranty_claim_payload,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_asset_manager_headers,
    make_platform_admin_headers,
    make_safety_officer_headers,
    make_site_controller_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSET_MANAGER = TEST_USERS["asset_manager_headers"]
TRADER = TEST_USERS["market_trader_headers"]
MARKET_OPERATOR = TEST_USERS["market_operator_headers"]
CONTROL_ROOM = TEST_USERS["control_room_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]

# Warranty claim drafting, filing and adjudication are three separate hands.
CLAIM_FILER = make_asset_manager_headers("am_filer")
CLAIM_REVIEWER = make_asset_manager_headers("am_reviewer")
CLAIM_ADJUDICATOR = make_platform_admin_headers("provider_adjudicator")

# Safety events are opened by one officer and closed by another.
OPENING_OFFICER = make_safety_officer_headers("so_1")
CLOSING_OFFICER = make_safety_officer_headers("so_2")

# The delivery day every market chain below trades into.
RESERVATION_WINDOW_START = "2026-08-10T12:00:00Z"
RESERVATION_WINDOW_END = "2026-08-10T20:00:00Z"
DELIVERY_START = "2026-08-10T12:00:00Z"
DELIVERY_END = "2026-08-10T16:00:00Z"
SETPOINT_START = "2026-08-10T14:00:00Z"
SETPOINT_END = "2026-08-10T15:00:00Z"
DISPATCH_DAY_CLOCK = "2026-08-10T00:00:00Z"


# --------------------------------------------------------------- logical clock
def set_clock(instant=DEFAULT_LOGICAL_CLOCK):
    """Move the platform's logical clock to `instant`."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


# --------------------------------------------------------------- storage assets
def register_asset(**overrides):
    """Register one plant; it comes back OFFLINE and not yet market-available."""
    payload = create_storage_asset_payload(**overrides)
    return get_success_data(api_client.create_storage_asset(payload, ADMIN))


def commission_asset(asset_id):
    """Commission a registered plant, seeding its state-of-health figures."""
    return get_success_data(api_client.commission_storage_asset(asset_id, ADMIN))


def refresh_asset(asset_id):
    """Re-read a plant so a caller sees its current derived fields and version."""
    return get_success_data(api_client.get_storage_asset(asset_id, ASSET_MANAGER))


def provision_asset(**overrides):
    """Register and commission one plant, returning the commissioned record."""
    asset = register_asset(**overrides)
    return commission_asset(asset["id"])


def reference_plant():
    """The 100 MWh / 25 MW reference plant: 80 MWh stored, 70 MWh dispatchable."""
    return provision_asset()


def mid_life_plant():
    """A plant already 34,000 MWh into its 40,000 MWh throughput warranty."""
    return provision_asset(
        name="Mesa Verde BESS 2",
        initial_cumulative_throughput_mwh=34000.0,
    )


def lightly_cycled_plant():
    """A plant carrying 19.8 MWh of prior throughput, used for degradation work."""
    return provision_asset(
        name="Mesa Verde BESS 3",
        initial_cumulative_throughput_mwh=19.8,
    )


def short_warranty_plant():
    """A plant with a 200 MWh throughput warranty, 80 MWh of it already used."""
    return provision_asset(
        name="Mesa Verde BESS 4",
        initial_cumulative_throughput_mwh=80.0,
        warranty_throughput_limit_mwh=200.0,
    )


# ---------------------------------------------------------------- reservations
def hold_reservation(
    asset_id,
    purpose="ENERGY_ARBITRAGE",
    reserved_mwh=40.0,
    window_start=RESERVATION_WINDOW_START,
    window_end=RESERVATION_WINDOW_END,
    headers=TRADER,
    expected_asset_version=None,
):
    """Reserve energy against a plant, reading its current version first."""
    if expected_asset_version is None:
        expected_asset_version = refresh_asset(asset_id)["version"]
    payload = create_soc_reservation_payload(
        asset_id,
        expected_asset_version,
        purpose=purpose,
        reserved_mwh=reserved_mwh,
        window_start=window_start,
        window_end=window_end,
    )
    return get_success_data(api_client.create_soc_reservation(payload, headers))


def release_reservation(reservation_id, headers=TRADER):
    return get_success_data(
        api_client.release_soc_reservation(reservation_id, headers)
    )


def refresh_reservation(reservation_id, headers=TRADER):
    return get_success_data(api_client.get_soc_reservation(reservation_id, headers))


# ----------------------------------------------------------------- market bids
def draft_bid(
    asset_id,
    reservation_id,
    market_type="DAY_AHEAD",
    product="ENERGY",
    direction="DISCHARGE",
    delivery_start=DELIVERY_START,
    delivery_end=DELIVERY_END,
    offer_mw=20.0,
    headers=TRADER,
    **overrides,
):
    """Draft one offer against a held reservation, pricing it on creation."""
    payload = create_market_bid_payload(
        asset_id,
        reservation_id,
        market_type=market_type,
        product=product,
        direction=direction,
        delivery_start=delivery_start,
        delivery_end=delivery_end,
        offer_mw=offer_mw,
        **overrides,
    )
    return get_success_data(api_client.create_market_bid(payload, headers))


def submit_bid(bid_id, headers=TRADER):
    return get_success_data(api_client.submit_market_bid(bid_id, headers))


def clear_bid(bid_id, cleared_price_usd_per_mwh=45.00, cleared_mw=20.0):
    """Post a CLEARED outcome from the market operator's desk."""
    payload = clearing_result_payload(
        "CLEARED",
        cleared_price_usd_per_mwh=cleared_price_usd_per_mwh,
        cleared_mw=cleared_mw,
    )
    return get_success_data(
        api_client.post_clearing_result(bid_id, payload, MARKET_OPERATOR)
    )


def unclear_bid(bid_id):
    """Post an UNCLEARED outcome, which carries no price and no cleared power."""
    return get_success_data(
        api_client.post_clearing_result(
            bid_id, clearing_result_payload("UNCLEARED"), MARKET_OPERATOR
        )
    )


def refresh_bid(bid_id, headers=TRADER):
    return get_success_data(api_client.get_market_bid(bid_id, headers))


def submitted_bid(asset_id, reservation_id, **kwargs):
    """Draft an offer and submit it into the market."""
    bid = draft_bid(asset_id, reservation_id, **kwargs)
    return submit_bid(bid["id"])


def cleared_bid(
    asset_id,
    reservation_id,
    cleared_price_usd_per_mwh=45.00,
    cleared_mw=20.0,
    **kwargs,
):
    """Draft, submit and clear one offer in a single call."""
    bid = submitted_bid(asset_id, reservation_id, **kwargs)
    return clear_bid(
        bid["id"],
        cleared_price_usd_per_mwh=cleared_price_usd_per_mwh,
        cleared_mw=cleared_mw,
    )


# ------------------------------------------------------- dispatch instructions
def issue_dispatch(
    bid_id,
    asset_id,
    instructed_mw=20.0,
    setpoint_start=SETPOINT_START,
    setpoint_end=SETPOINT_END,
):
    """Issue one instruction against a cleared offer; it lands PENDING."""
    payload = create_dispatch_instruction_payload(
        bid_id,
        asset_id,
        instructed_mw=instructed_mw,
        setpoint_start=setpoint_start,
        setpoint_end=setpoint_end,
    )
    return get_success_data(
        api_client.create_dispatch_instruction(payload, MARKET_OPERATOR)
    )


def accept_dispatch(dispatch_id):
    return get_success_data(
        api_client.accept_dispatch_instruction(dispatch_id, CONTROL_ROOM)
    )


def execute_dispatch(dispatch_id, asset_id):
    return get_success_data(
        api_client.execute_dispatch_instruction(
            dispatch_id, make_site_controller_headers(asset_id)
        )
    )


def complete_dispatch(dispatch_id, asset_id):
    return get_success_data(
        api_client.complete_dispatch_instruction(
            dispatch_id, make_site_controller_headers(asset_id)
        )
    )


def fail_dispatch(dispatch_id, failure_reason="DELIVERY_VOIDED", headers=CONTROL_ROOM):
    return get_success_data(
        api_client.fail_dispatch_instruction(
            dispatch_id, headers, {"failure_reason": failure_reason}
        )
    )


def settle_score(dispatch_id):
    return get_success_data(
        api_client.settle_dispatch_score(dispatch_id, MARKET_OPERATOR)
    )


def refresh_dispatch(dispatch_id, headers=MARKET_OPERATOR):
    return get_success_data(
        api_client.get_dispatch_instruction(dispatch_id, headers)
    )


def executing_dispatch(bid_id, asset_id, **kwargs):
    """Issue, accept and begin executing one instruction."""
    dispatch = issue_dispatch(bid_id, asset_id, **kwargs)
    accept_dispatch(dispatch["id"])
    return execute_dispatch(dispatch["id"], asset_id)


# ---------------------------------------------------------------- telemetry
def append_sample(
    dispatch_id,
    asset_id,
    sample_index,
    sampled_at,
    measured_mw=20.0,
    measured_mvar=0.0,
    soc_mwh_reading=75.0,
    max_cell_temp_c=30.0,
):
    """Append one quarter-hour sample to an executing instruction's stream."""
    payload = create_telemetry_sample_payload(
        dispatch_id,
        sample_index,
        sampled_at,
        measured_mw=measured_mw,
        measured_mvar=measured_mvar,
        soc_mwh_reading=soc_mwh_reading,
        max_cell_temp_c=max_cell_temp_c,
    )
    return get_success_data(
        api_client.create_telemetry_sample(
            payload, make_site_controller_headers(asset_id)
        )
    )


def append_samples(dispatch_id, asset_id, samples):
    """Append a run of samples given as (sampled_at, measured_mw, soc_reading) triples."""
    created = []
    for index, sample in enumerate(samples, start=1):
        sampled_at, measured_mw, soc_reading = sample
        created.append(
            append_sample(
                dispatch_id,
                asset_id,
                index,
                sampled_at,
                measured_mw=measured_mw,
                soc_mwh_reading=soc_reading,
            )
        )
    return created


# The four-sample delivery run of a 20 MW instruction over one hour: the
# quarter-hour readings average exactly 19.8 MWh of delivered energy.
NOMINAL_DELIVERY_SAMPLES = [
    ("2026-08-10T14:15:00Z", 19.6, 75.1),
    ("2026-08-10T14:30:00Z", 20.4, 70.0),
    ("2026-08-10T14:45:00Z", 19.2, 65.2),
    ("2026-08-10T15:00:00Z", 20.0, 60.2),
]


# -------------------------------------------------------------- safety events
def open_safety_event(
    asset_id,
    event_type="THERMAL_ANOMALY",
    severity="WARNING",
    detected_max_cell_temp_c=66.0,
    headers=OPENING_OFFICER,
):
    """Open one safety event, which recomputes the plant's safety posture."""
    payload = create_safety_event_payload(
        asset_id,
        event_type=event_type,
        severity=severity,
        detected_max_cell_temp_c=detected_max_cell_temp_c,
    )
    return get_success_data(api_client.create_safety_event(payload, headers))


def refresh_safety_event(event_id, headers=SAFETY_OFFICER):
    return get_success_data(api_client.get_safety_event(event_id, headers))


def discharge_suppression(event_id, suppression_agent_kg=250.0, headers=OPENING_OFFICER):
    return get_success_data(
        api_client.discharge_suppression(
            event_id, {"suppression_agent_kg": suppression_agent_kg}, headers
        )
    )


def close_event(event_id, headers=CLOSING_OFFICER, **payload):
    return get_success_data(
        api_client.close_safety_event(event_id, headers, payload or None)
    )


CRITICAL_CLOSURE = {
    "emergency_response_ack_at": "2026-08-01T02:00:00Z",
    "emergency_ack_agencies": ["Mesa County Fire", "ISO Control Centre"],
    "responder_cleared": True,
}


def elevate_asset(asset_id):
    """Drive a plant to ELEVATED safety state with a WARNING thermal anomaly."""
    return open_safety_event(
        asset_id,
        event_type="THERMAL_ANOMALY",
        severity="WARNING",
        detected_max_cell_temp_c=66.0,
    )


def alarm_asset(asset_id):
    """Drive a plant to ALARM with a CRITICAL smoke detection."""
    return open_safety_event(
        asset_id,
        event_type="SMOKE_DETECTED",
        severity="CRITICAL",
        detected_max_cell_temp_c=70.0,
    )


def lockout_asset(asset_id):
    """Drive a plant into LOCKOUT with a manual thermal-runaway declaration."""
    return open_safety_event(
        asset_id,
        event_type="THERMAL_RUNAWAY",
        severity="CRITICAL",
        detected_max_cell_temp_c=82.0,
    )


# --------------------------------------------------------- capacity obligations
def enrol_obligation(asset_id, headers=ASSET_MANAGER, **overrides):
    """Enrol a plant in a capacity programme."""
    payload = create_capacity_obligation_payload(asset_id, **overrides)
    return get_success_data(api_client.create_capacity_obligation(payload, headers))


def record_unavailability(
    obligation_id, hours, reason="FORCED_OUTAGE", headers=CONTROL_ROOM
):
    payload = {"unavailable_hours_delta": hours}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.record_unavailability(obligation_id, payload, headers)
    )


def assess_obligation(obligation_id, mode="PRELIMINARY"):
    return get_success_data(
        api_client.assess_capacity_obligation(
            obligation_id, {"mode": mode}, MARKET_OPERATOR
        )
    )


def refresh_obligation(obligation_id, headers=ASSET_MANAGER):
    return get_success_data(
        api_client.get_capacity_obligation(obligation_id, headers)
    )


# ------------------------------------------------------------- revision loop
def revise_bid(bid_id, headers=TRADER, **fields):
    """Re-price an uncleared offer, consuming one revision allowance."""
    return get_success_data(api_client.revise_market_bid(bid_id, fields, headers))


def run_revision_cycle(bid_id, **fields):
    """Walk one full negotiation loop: submit, come back uncleared, re-price.

    The offer must be `DRAFT` on entry and is `DRAFT` again on exit with its
    revision allowance one lower.
    """
    submit_bid(bid_id)
    unclear_bid(bid_id)
    return revise_bid(bid_id, **fields)


def withdraw_bid(bid_id, headers=TRADER):
    return get_success_data(api_client.withdraw_market_bid(bid_id, headers))


# -------------------------------------------------------------- capacity tests
def schedule_test(asset_id, scheduled_date="2026-08-01T00:00:00Z", headers=ASSET_MANAGER, **overrides):
    payload = create_capacity_test_payload(
        asset_id, scheduled_date=scheduled_date, **overrides
    )
    return get_success_data(api_client.create_capacity_test(payload, headers))


def start_test(test_id, asset_id):
    return get_success_data(
        api_client.start_capacity_test(test_id, make_site_controller_headers(asset_id))
    )


def finish_test(test_id, asset_id, measured_capacity_mwh=90.0):
    return get_success_data(
        api_client.complete_capacity_test(
            test_id,
            {"measured_capacity_mwh": measured_capacity_mwh},
            make_site_controller_headers(asset_id),
        )
    )


def refresh_test(test_id, headers=ASSET_MANAGER):
    return get_success_data(api_client.get_capacity_test(test_id, headers))


def completed_test(
    asset_id,
    scheduled_date="2026-08-01T00:00:00Z",
    measured_capacity_mwh=90.0,
    **overrides,
):
    """Schedule, start and complete one capacity test, running the degradation model."""
    test = schedule_test(asset_id, scheduled_date=scheduled_date, **overrides)
    start_test(test["id"], asset_id)
    return finish_test(test["id"], asset_id, measured_capacity_mwh=measured_capacity_mwh)


# ------------------------------------------------------------ warranty claims
def file_claim(asset_id, capacity_test_id, headers=CLAIM_FILER, **overrides):
    payload = create_warranty_claim_payload(asset_id, capacity_test_id, **overrides)
    return get_success_data(api_client.create_warranty_claim(payload, headers))


def submit_claim(claim_id, headers=CLAIM_REVIEWER):
    return get_success_data(api_client.submit_warranty_claim(claim_id, headers))


def approve_claim(
    claim_id,
    remedy_install_date="2026-09-01T00:00:00Z",
    remedy_outage_days=3,
    headers=CLAIM_ADJUDICATOR,
):
    payload = approve_claim_payload(
        remedy_install_date=remedy_install_date,
        remedy_outage_days=remedy_outage_days,
    )
    return get_success_data(
        api_client.adjudicate_warranty_claim(claim_id, payload, headers)
    )


def deny_claim(claim_id, denial_reason="NO_SHORTFALL", headers=CLAIM_ADJUDICATOR):
    return get_success_data(
        api_client.adjudicate_warranty_claim(
            claim_id, {"decision": "DENY", "denial_reason": denial_reason}, headers
        )
    )


def install_remedy(claim_id, headers=CLAIM_FILER):
    return get_success_data(api_client.install_warranty_remedy(claim_id, headers))


def refresh_claim(claim_id, headers=ASSET_MANAGER):
    return get_success_data(api_client.get_warranty_claim(claim_id, headers))


def approved_claim(
    asset_id,
    capacity_test_id,
    remedy_install_date="2026-09-01T00:00:00Z",
    remedy_outage_days=3,
):
    """File, submit and approve a claim citing a triggered capacity test."""
    claim = file_claim(asset_id, capacity_test_id)
    submit_claim(claim["id"])
    return approve_claim(
        claim["id"],
        remedy_install_date=remedy_install_date,
        remedy_outage_days=remedy_outage_days,
    )


# ------------------------------------------------------- composite market chains
def market_position(
    reserved_mwh=40.0,
    purpose="ENERGY_ARBITRAGE",
    window_start=RESERVATION_WINDOW_START,
    window_end=RESERVATION_WINDOW_END,
    **asset_overrides,
):
    """A commissioned plant with one held reservation behind it."""
    asset = provision_asset(**asset_overrides)
    reservation = hold_reservation(
        asset["id"],
        purpose=purpose,
        reserved_mwh=reserved_mwh,
        window_start=window_start,
        window_end=window_end,
    )
    return {"asset": asset, "reservation": reservation}


def cleared_position(
    cleared_price_usd_per_mwh=45.00,
    cleared_mw=20.0,
    offer_mw=20.0,
    reserved_mwh=40.0,
    **asset_overrides,
):
    """A commissioned plant whose offer has cleared the day-ahead market."""
    position = market_position(reserved_mwh=reserved_mwh, **asset_overrides)
    bid = cleared_bid(
        position["asset"]["id"],
        position["reservation"]["id"],
        cleared_price_usd_per_mwh=cleared_price_usd_per_mwh,
        cleared_mw=cleared_mw,
        offer_mw=offer_mw,
    )
    position["bid"] = bid
    return position


def executing_position(instructed_mw=20.0, **kwargs):
    """A cleared offer with one instruction accepted and executing at the site."""
    position = cleared_position(**kwargs)
    dispatch = executing_dispatch(
        position["bid"]["id"], position["asset"]["id"], instructed_mw=instructed_mw
    )
    position["dispatch"] = dispatch
    return position


def delivered_position(samples=None, instructed_mw=20.0, **kwargs):
    """A delivery run carried through to completion, so a provisional score exists."""
    position = executing_position(instructed_mw=instructed_mw, **kwargs)
    append_samples(
        position["dispatch"]["id"],
        position["asset"]["id"],
        samples if samples is not None else NOMINAL_DELIVERY_SAMPLES,
    )
    position["dispatch"] = complete_dispatch(
        position["dispatch"]["id"], position["asset"]["id"]
    )
    return position


def triggered_test_position(scheduled_date="2026-08-01T00:00:00Z"):
    """A lightly cycled plant whose first capacity test triggered the warranty."""
    asset = lightly_cycled_plant()
    test = completed_test(
        asset["id"], scheduled_date=scheduled_date, measured_capacity_mwh=90.0
    )
    return {"asset": asset, "test": test}


# ------------------------------------------------------------- pytest fixtures
@pytest.fixture
def client():
    """The API client every test speaks to."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def asset_manager_headers():
    return ASSET_MANAGER


@pytest.fixture
def trader_headers():
    return TRADER


@pytest.fixture
def market_operator_headers():
    return MARKET_OPERATOR


@pytest.fixture
def control_room_headers():
    return CONTROL_ROOM


@pytest.fixture
def safety_officer_headers():
    return OPENING_OFFICER


@pytest.fixture
def closing_officer_headers():
    return CLOSING_OFFICER


@pytest.fixture
def logical_clock():
    """The platform clock parked on the reference trading date."""
    return set_clock(DEFAULT_LOGICAL_CLOCK)


@pytest.fixture
def dispatch_day_clock():
    """The platform clock parked on the delivery day every dispatch chain uses."""
    return set_clock(DISPATCH_DAY_CLOCK)


@pytest.fixture
def registered_asset(logical_clock):
    """One plant registered but not yet commissioned, so still offline."""
    return register_asset()


@pytest.fixture
def commissioned_asset(logical_clock):
    """The reference plant, commissioned and market-available."""
    return reference_plant()


@pytest.fixture
def held_reservation(commissioned_asset):
    """40 MWh of the reference plant held for energy arbitrage."""
    return hold_reservation(commissioned_asset["id"])


@pytest.fixture
def drafted_bid(commissioned_asset, held_reservation):
    """A drafted day-ahead energy offer priced against the reference plant."""
    return draft_bid(commissioned_asset["id"], held_reservation["id"])


@pytest.fixture
def cleared_market_position(dispatch_day_clock):
    """A plant whose 20 MW day-ahead offer cleared at 45.00 dollars."""
    return cleared_position()


@pytest.fixture
def pending_instruction(cleared_market_position):
    """One instruction issued against a cleared offer, awaiting the control room."""
    return issue_dispatch(
        cleared_market_position["bid"]["id"],
        cleared_market_position["asset"]["id"],
    )


@pytest.fixture
def executing_instruction(dispatch_day_clock):
    """A delivery under way at the site, ready to receive telemetry."""
    return executing_position()


@pytest.fixture
def provisional_delivery(dispatch_day_clock):
    """A completed delivery carrying a provisional performance score."""
    return delivered_position()


@pytest.fixture
def enrolled_obligation(commissioned_asset):
    """The reference plant enrolled in a capacity programme."""
    return enrol_obligation(commissioned_asset["id"])


@pytest.fixture
def triggered_capacity_test(logical_clock):
    """A completed capacity test whose shortfall triggered the warranty."""
    return triggered_test_position()


@pytest.fixture
def approved_warranty_claim(triggered_capacity_test):
    """An approved claim with a three-day augmentation outage from 1 September."""
    claim = approved_claim(
        triggered_capacity_test["asset"]["id"],
        triggered_capacity_test["test"]["id"],
    )
    return {
        "asset": triggered_capacity_test["asset"],
        "test": triggered_capacity_test["test"],
        "claim": claim,
    }
