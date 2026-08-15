"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls go through get_success_data so a
broken precondition surfaces as a clear "Setup failed" assertion.

Identity threading: CarrierManager is entity-backed by Carrier, so every
ownership-gated call is made with make_carrier_manager_headers(carrier["id"])
built from the real carrier id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    DEFAULT_CREDENTIAL_SETS,
    DEFAULT_SUB_END,
    DEFAULT_SUB_START,
    PERIOD_MONTH,
    PERIOD_YEAR,
)
from .factories import (
    create_carrier_payload,
    create_config_payload,
    create_credential_payload,
    create_dispute_payload,
    create_event_payload,
    create_override_payload,
    create_snapshot_payload,
    create_station_payload,
    create_subscription_payload,
    create_vehicle_payload,
)
from .test_users import TEST_USERS, make_carrier_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SPM = TEST_USERS["state_program_manager_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
FEED = TEST_USERS["safety_data_feed_headers"]
GATEWAY = TEST_USERS["telematics_gateway_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: clock + single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START_ISO):
    """Advance the logical clock (runs the materialization sweep)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_carrier(**overrides):
    """Onboard a carrier (ENROLLED, posture NOT_EVALUATED). Returns carrier."""
    return get_success_data(api_client.create_carrier(create_carrier_payload(**overrides),
                                                      ADMIN))


def get_carrier(carrier_id):
    return get_success_data(api_client.get_carrier(carrier_id, ADMIN))


def carrier_version(carrier_id):
    return get_carrier(carrier_id)["version"]


def post_snapshot(carrier_id, iss_score=30, safety_rating="SATISFACTORY",
                  source="FMCSA_FEED", effective_date="2026-08-01",
                  expected_carrier_version=None):
    """Post a safety-score snapshot. When expected_carrier_version is None the
    carrier is re-read first (the PRD's OCC flow: present the version last
    observed). Returns the snapshot."""
    if expected_carrier_version is None:
        expected_carrier_version = carrier_version(carrier_id)
    payload = create_snapshot_payload(
        carrier_id, expected_carrier_version,
        iss_score=iss_score, safety_rating=safety_rating, source=source,
        effective_date=effective_date)
    return get_success_data(api_client.create_snapshot(payload, FEED))


def transition_carrier(carrier_id, to_status, headers=None):
    return get_success_data(api_client.transition_carrier(
        carrier_id, to_status, headers or OFFICER))


def create_config(promote_to_participating=False, **fields):
    """Create a state program config (born PILOT). When
    promote_to_participating is True the config is immediately patched to
    PARTICIPATING and the fresh row returned."""
    cfg = get_success_data(api_client.create_config(create_config_payload(**fields),
                                                    SPM))
    if promote_to_participating:
        cfg = get_success_data(api_client.patch_config(
            cfg["id"],
            {"participation_status": "PARTICIPATING",
             "expected_state_program_config_version": cfg["version"]},
            SPM))
    return cfg


def patch_config(config_id, expected_version, **fields):
    payload = {"expected_state_program_config_version": expected_version}
    payload.update(fields)
    return get_success_data(api_client.patch_config(config_id, payload, SPM))


def create_station(config_id, **overrides):
    return get_success_data(api_client.create_station(
        create_station_payload(config_id, **overrides), SPM))


def create_vehicle_for(carrier_id, **overrides):
    """Register a vehicle as the owning CarrierManager."""
    headers = make_carrier_manager_headers(carrier_id)
    return get_success_data(api_client.create_vehicle(
        create_vehicle_payload(carrier_id, **overrides), headers))


def create_subscription_for(carrier_id, vehicle_id,
                            service_start_date=DEFAULT_SUB_START,
                            service_end_date=DEFAULT_SUB_END):
    headers = make_carrier_manager_headers(carrier_id)
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(
            carrier_id, vehicle_id,
            service_start_date=service_start_date,
            service_end_date=service_end_date),
        headers))


def create_credential_for(vehicle_id, carrier_id, device_type="TRANSPONDER",
                          device_serial=None):
    headers = make_carrier_manager_headers(carrier_id)
    overrides = {"device_type": device_type}
    if device_serial is not None:
        overrides["device_serial"] = device_serial
    return get_success_data(api_client.create_credential(
        create_credential_payload(vehicle_id, **overrides), headers))


def transition_credential(credential_id, to_status, carrier_id):
    headers = make_carrier_manager_headers(carrier_id)
    return get_success_data(api_client.transition_credential(
        credential_id, to_status, headers))


def activate_credential(credential_id, carrier_id):
    return transition_credential(credential_id, "ACTIVE", carrier_id)


def post_event(vehicle_id, station_id, approach_at, **fields):
    """Record a roadside approach through the telematics feed."""
    return get_success_data(api_client.create_event(
        create_event_payload(vehicle_id, station_id, approach_at, **fields),
        GATEWAY))


def open_dispute(bypass_event_id, carrier_id, claimed_credit_cents=1000,
                 reason="Wrongful pull-in"):
    headers = make_carrier_manager_headers(carrier_id)
    return get_success_data(api_client.create_dispute(
        create_dispute_payload(bypass_event_id,
                               claimed_credit_cents=claimed_credit_cents,
                               reason=reason),
        headers))


def request_override(carrier_id, start_date="2026-09-01", end_date="2026-10-01",
                     reason="Waiver request"):
    headers = make_carrier_manager_headers(carrier_id)
    return get_success_data(api_client.create_override(
        create_override_payload(carrier_id, carrier_version(carrier_id),
                                start_date=start_date, end_date=end_date,
                                reason=reason),
        headers))


def close_period(carrier_id, period_year=PERIOD_YEAR, period_month=PERIOD_MONTH):
    """Close a fully elapsed billing period; returns the created Invoice."""
    return get_success_data(api_client.close_billing_period(
        carrier_id, period_year, period_month, FINANCE))


# ---------------------------------------------------------------------------
# Tier 2: active carrier
# ---------------------------------------------------------------------------

def create_active_carrier(iss_score=30, safety_rating="SATISFACTORY",
                          effective_date="2026-08-01", **carrier_overrides):
    """Carrier onboarded, first snapshot posted, approved ENROLLED -> ACTIVE.

    Returns the fresh carrier row (post-approval).
    """
    carrier = create_carrier(**carrier_overrides)
    post_snapshot(carrier["id"], iss_score=iss_score, safety_rating=safety_rating,
                  effective_date=effective_date,
                  expected_carrier_version=carrier["version"])
    transition_carrier(carrier["id"], "ACTIVE")
    return get_carrier(carrier["id"])


# ---------------------------------------------------------------------------
# Tier 3: full bypass-capable scenario
# ---------------------------------------------------------------------------

def setup_bypass_ready(config_fields=None, promote_to_participating=True,
                       iss_score=30, safety_rating="SATISFACTORY",
                       station_type="FIXED_SCALE", supported_channel="BOTH",
                       service_start_date=DEFAULT_SUB_START,
                       service_end_date=DEFAULT_SUB_END,
                       device_type="TRANSPONDER",
                       vehicle_overrides=None,
                       clock=CLOCK_START_ISO,
                       activate=True):
    """Config + station + ACTIVE carrier + vehicle + subscription + credential.

    Returns a dict with every entity plus the ownership headers for the
    carrier manager. The default chain leaves the vehicle bypass-ready:
    PARTICIPATING config, OPERATIONAL FIXED_SCALE/BOTH station, ELIGIBLE
    ACTIVE carrier, IN_SERVICE vehicle, covering ACTIVE subscription, and an
    ACTIVE credential.
    """
    set_clock(clock)
    fields = {"requires_weight_clearance": True, "random_pull_in_rate_bps": 0,
              "bypass_rate_cap_bps": 10000,
              "credential_sets_required": list(DEFAULT_CREDENTIAL_SETS)}
    if config_fields:
        fields.update(config_fields)
    config = create_config(promote_to_participating=promote_to_participating,
                           **fields)
    station = create_station(config["id"], station_type=station_type,
                             supported_channel=supported_channel)
    carrier = create_active_carrier(iss_score=iss_score, safety_rating=safety_rating)
    cm = make_carrier_manager_headers(carrier["id"])
    vehicle = create_vehicle_for(carrier["id"], **(vehicle_overrides or {}))
    subscription = create_subscription_for(
        carrier["id"], vehicle["id"],
        service_start_date=service_start_date,
        service_end_date=service_end_date)
    credential = create_credential_for(vehicle["id"], carrier["id"],
                                       device_type=device_type)
    if activate:
        credential = activate_credential(credential["id"], carrier["id"])
    return {
        "config": config,
        "station": station,
        "carrier": get_carrier(carrier["id"]),
        "cm_headers": cm,
        "vehicle": vehicle,
        "subscription": subscription,
        "credential": credential,
    }


def setup_pull_in_event(approach_at="2026-08-05T10:00:00Z",
                        clock="2026-08-05T12:00:00Z",
                        measured_weight_lbs=90000, **fixture_kwargs):
    """Bypass-ready fixture plus one PULL_IN event (default: OVERWEIGHT via a
    90000-lb reading against the default 84000-lb clearance limit)."""
    fx = setup_bypass_ready(clock="2026-08-01T00:00:00Z", **fixture_kwargs)
    set_clock(clock)
    fields = {"credentials_presented": list(DEFAULT_CREDENTIAL_SETS)}
    if measured_weight_lbs is not None:
        fields["measured_weight_lbs"] = measured_weight_lbs
    event = post_event(fx["vehicle"]["id"], fx["station"]["id"], approach_at,
                       **fields)
    fx["event"] = event
    return fx


def setup_carrier_with_invoice(clock_after_close="2026-09-01T00:00:00Z",
                               **fixture_kwargs):
    """Bypass-ready fixture with the default August period closed: one
    full-month ACTIVE subscription, so the invoice carries a single TIER_1
    line for the full month. Returns fixture with 'invoice' attached."""
    fx = setup_bypass_ready(**fixture_kwargs)
    set_clock(clock_after_close)
    fx["invoice"] = close_period(fx["carrier"]["id"])
    return fx


def setup_carrier_past_due(**fixture_kwargs):
    """Fixture whose invoice has gone PAST_DUE (clock advanced past the
    invoice due date), so the carrier's subscriptions stand PAST_DUE."""
    fx = setup_carrier_with_invoice(**fixture_kwargs)
    set_clock("2026-09-16T00:00:00Z")
    fx["carrier"] = get_carrier(fx["carrier"]["id"])
    fx["invoice"] = get_success_data(
        api_client.get_invoice(fx["invoice"]["id"], FINANCE))
    return fx


# ---------------------------------------------------------------------------
# Tier 4: list helpers
# ---------------------------------------------------------------------------

def list_all(path_client_method, headers, **params):
    """Paginated list helper returning the full data list."""
    data, _meta = validate_paginated(path_client_method(headers, params=params))
    return data


def list_subscriptions_for(carrier_id=None, vehicle_id=None, headers=None):
    params = {}
    if carrier_id:
        params["carrier_id"] = carrier_id
    if vehicle_id:
        params["vehicle_id"] = vehicle_id
    return list_all(api_client.list_subscriptions, headers or FINANCE, **params)


def list_credentials_for(carrier_id=None, vehicle_id=None, headers=None):
    params = {}
    if carrier_id:
        params["carrier_id"] = carrier_id
    if vehicle_id:
        params["vehicle_id"] = vehicle_id
    return list_all(api_client.list_credentials, headers or FINANCE, **params)


def list_events_for(carrier_id=None, vehicle_id=None, station_id=None,
                    decision=None, headers=None, **extra):
    params = dict(extra)
    if carrier_id:
        params["carrier_id"] = carrier_id
    if vehicle_id:
        params["vehicle_id"] = vehicle_id
    if station_id:
        params["station_id"] = station_id
    if decision:
        params["decision"] = decision
    return list_all(api_client.list_events, headers or FINANCE, **params)


def list_invoices_for(carrier_id, headers=None):
    return list_all(api_client.list_invoices, headers or FINANCE,
                    **{"carrier_id": carrier_id})


def list_overrides_for(carrier_id, headers=None):
    return list_all(api_client.list_overrides, headers or OFFICER,
                    **{"carrier_id": carrier_id})


def list_vehicles_for(carrier_id, headers=None):
    return list_all(api_client.list_vehicles,
                    headers or make_carrier_manager_headers(carrier_id),
                    **{"carrier_id": carrier_id})
