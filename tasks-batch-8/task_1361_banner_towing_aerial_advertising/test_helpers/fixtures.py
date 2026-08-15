"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. OCC version fields are always read fresh via GET
immediately before the guarded write, mirroring PRD §2.10's
"caller proves it has observed the current state" contract.

Identity threading: Client and Pilot are entity-backed roles, so every
ownership-gated call is made with make_client_headers(client["id"]) /
make_pilot_headers(pilot_id) — never with the shared placeholder constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_aircraft_payload,
    create_airspace_approval_payload,
    create_banner_payload,
    create_banner_revision_payload,
    create_base_payload,
    create_campaign_payload,
    create_client_payload,
    create_flight_log_payload,
    create_flight_slot_payload,
    create_invoice_payload,
    create_pilot_payload,
    create_route_payload,
    create_seasonal_capacity_payload,
    create_tfr_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_pilot_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
GROUND = TEST_USERS["ground_crew_lead_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]

NO_GO_WEATHER = {"ceiling_ft": 500, "visibility_sm": 2.0, "wind_kts": 5}
GO_WEATHER = {"ceiling_ft": 5000, "visibility_sm": 10.0, "wind_kts": 5}
MARGINAL_WEATHER = {"ceiling_ft": 1200, "visibility_sm": 4.0, "wind_kts": 10}


def _fail(step, resp):
    raise AssertionError(f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 1 — stand-up primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=TEST_DEFAULTS["CLOCK_START"]):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


def create_base(code="KMYB", name="Myrtle Beach"):
    resp = api_client.create_base(create_base_payload(code=code, name=name), ADMIN)
    return _ok("create_base", resp)


def create_aircraft(base_id, tail_number="N100AA", model="CITABRIA",
                    max_tow_weight_lbs=TEST_DEFAULTS["MAX_TOW_WEIGHT_LBS"],
                    hourly_rate_cents=TEST_DEFAULTS["HOURLY_RATE_CENTS"]):
    resp = api_client.create_aircraft(
        base_id,
        create_aircraft_payload(
            tail_number=tail_number, model=model,
            max_tow_weight_lbs=max_tow_weight_lbs,
            hourly_rate_cents=hourly_rate_cents,
        ),
        ADMIN,
    )
    return _ok("create_aircraft", resp)


def create_pilot(base_id, full_name="Pilot One", certificate_number="CERT-1",
                 tow_endorsement_level="STANDARD"):
    resp = api_client.create_pilot(
        base_id,
        create_pilot_payload(
            full_name=full_name, certificate_number=certificate_number,
            tow_endorsement_level=tow_endorsement_level,
        ),
        ADMIN,
    )
    return _ok("create_pilot", resp)


def create_route(base_id, code="BEACH-N-01", kind="BEACH",
                 min_banner_length_ft=TEST_DEFAULTS["MIN_BANNER_LENGTH_FT"],
                 length_nm=TEST_DEFAULTS["ROUTE_LENGTH_NM"]):
    resp = api_client.create_route(
        create_route_payload(code=code, kind=kind, base_id=base_id,
                             length_nm=length_nm,
                             min_banner_length_ft=min_banner_length_ft),
        ADMIN,
    )
    return _ok("create_route", resp)


def create_client(legal_name="Acme Advertising", billing_email="acme@example.com"):
    resp = api_client.create_client(
        create_client_payload(legal_name=legal_name, billing_email=billing_email),
        ADMIN,
    )
    return _ok("create_client", resp)


def create_campaign(client_id, name="Summer Campaign"):
    resp = api_client.create_campaign(client_id, create_campaign_payload(name=name),
                                      make_client_headers(client_id))
    return _ok("create_campaign", resp)


# ---------------------------------------------------------------------------
# Tier 2 — banner fabrication chain, approvals, capacity
# ---------------------------------------------------------------------------

def propose_and_activate_revision(banner_id, client_id, text="EAT AT JOES",
                                  artwork_hash="art-hash-1"):
    """Propose a BannerRevision and approve it (auto-activates per PRD §3.3).
    Returns the ACTIVE revision."""
    headers = make_client_headers(client_id)
    resp = api_client.propose_banner_revision(
        banner_id,
        create_banner_revision_payload(proposed_text=text,
                                       proposed_artwork_hash=artwork_hash),
        headers,
    )
    revision = _ok("propose_banner_revision", resp)
    resp = api_client.approve_banner_revision(revision["id"], headers)
    return _ok("approve_banner_revision", resp)


def fabricate_banner(banner_id):
    """Banner DRAFT -> IN_FABRICATION with a fresh OCC read (PRD §2.10)."""
    current = _ok("get_banner(pre-fabricate)",
                  api_client.get_banner(banner_id, ADMIN))
    resp = api_client.fabricate_banner(
        banner_id, {"expected_banner_version": current["version"]}, GROUND)
    return _ok("fabricate_banner", resp)


def mark_banner_ready(banner_id):
    resp = api_client.mark_banner_ready(banner_id, GROUND)
    return _ok("mark_banner_ready", resp)


def create_ready_banner(campaign_id, client_id, length_ft=TEST_DEFAULTS["BANNER_LENGTH_FT"],
                        weight_lbs=TEST_DEFAULTS["BANNER_WEIGHT_LBS"],
                        text="EAT AT JOES"):
    """Banner + approved revision + fabrication + mark_ready.
    Returns (banner_READY, active_revision)."""
    resp = api_client.create_banner(
        campaign_id,
        create_banner_payload(text_message=text, banner_length_ft=length_ft,
                              banner_weight_lbs=weight_lbs),
        make_client_headers(client_id),
    )
    banner = _ok("create_banner", resp)
    revision = propose_and_activate_revision(banner["id"], client_id, text=text)
    fabricate_banner(banner["id"])
    banner = mark_banner_ready(banner["id"])
    return banner, revision


def create_draft_banner(campaign_id, client_id,
                        length_ft=TEST_DEFAULTS["BANNER_LENGTH_FT"],
                        weight_lbs=TEST_DEFAULTS["BANNER_WEIGHT_LBS"]):
    """Banner left in DRAFT (no revision, no fabrication)."""
    resp = api_client.create_banner(
        campaign_id,
        create_banner_payload(banner_length_ft=length_ft,
                              banner_weight_lbs=weight_lbs),
        make_client_headers(client_id),
    )
    return _ok("create_banner", resp)


def create_granted_approval(route_id, date_local="2026-08-13",
                            window_start="2026-08-13T14:00:00Z",
                            window_end="2026-08-13T18:00:00Z",
                            stadium_tfr_waiver=None):
    payload = create_airspace_approval_payload(
        date_local=date_local, window_start_utc=window_start,
        window_end_utc=window_end,
    )
    if stadium_tfr_waiver is not None:
        payload["stadium_tfr_waiver"] = stadium_tfr_waiver
    resp = api_client.create_airspace_approval(route_id, payload, DISPATCHER)
    approval = _ok("create_airspace_approval", resp)
    resp = api_client.grant_airspace_approval(approval["id"], COMPLIANCE)
    return _ok("grant_airspace_approval", resp)


def create_pending_approval(route_id, date_local="2026-08-13",
                            window_start="2026-08-13T14:00:00Z",
                            window_end="2026-08-13T18:00:00Z"):
    resp = api_client.create_airspace_approval(
        route_id,
        create_airspace_approval_payload(date_local=date_local,
                                         window_start_utc=window_start,
                                         window_end_utc=window_end),
        DISPATCHER,
    )
    return _ok("create_airspace_approval", resp)


def create_tfr(route_id, starts="2026-08-13T15:00:00Z", ends="2026-08-13T18:00:00Z",
               reason="GAME"):
    resp = api_client.create_tfr_restriction(
        create_tfr_payload(route_id=route_id, starts_utc=starts, ends_utc=ends,
                           reason=reason),
        COMPLIANCE,
    )
    return _ok("create_tfr_restriction", resp)


def create_capacity(base_id, month=TEST_DEFAULTS["MONTH"],
                    quota=TEST_DEFAULTS["QUOTA_HOURS"]):
    resp = api_client.create_seasonal_capacity(
        base_id,
        create_seasonal_capacity_payload(month_yyyy_mm=month,
                                         aircraft_hour_quota=quota),
        ADMIN,
    )
    return _ok("create_seasonal_capacity", resp)


def get_capacity(capacity_id):
    return _ok("get_seasonal_capacity",
               api_client.get_seasonal_capacity(capacity_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3 — booking, scheduling, flight day
# ---------------------------------------------------------------------------

def book_slot(campaign_id, client_id, route_id, approval_id, banner_id,
              capacity_id, date_local="2026-08-13",
              planned_start="2026-08-13T15:00:00Z", planned_duration_hours=1,
              supersedes_slot_id=None):
    """Create + book a FlightSlot with a fresh OCC read of the SeasonalCapacity
    (PRD §2.10). Returns the BOOKED slot."""
    capacity = get_capacity(capacity_id)
    payload = create_flight_slot_payload(
        route_id=route_id, airspace_approval_id=approval_id, banner_id=banner_id,
        date_local=date_local, planned_start_utc=planned_start,
        planned_duration_hours=planned_duration_hours,
        expected_seasonal_capacity_version=capacity["version"],
    )
    if supersedes_slot_id is not None:
        payload["supersedes_slot_id"] = supersedes_slot_id
    resp = api_client.create_flight_slot(campaign_id, payload,
                                         make_client_headers(client_id))
    return _ok("create_flight_slot", resp)


def book_campaign(campaign_id, client_id):
    """Campaign DRAFT -> BOOKED with a fresh OCC read (PRD §2.10)."""
    current = _ok("get_campaign(pre-book)",
                  api_client.get_campaign(campaign_id, ADMIN))
    resp = api_client.book_campaign(
        campaign_id, {"expected_campaign_version": current["version"]},
        make_client_headers(client_id))
    return _ok("book_campaign", resp)


def schedule_slot(slot_id):
    resp = api_client.schedule_flight_slot(slot_id, DISPATCHER)
    return _ok("schedule_flight_slot", resp)


def get_slot(slot_id):
    return _ok("get_flight_slot", api_client.get_flight_slot(slot_id, ADMIN))


def post_weather(slot_id, ceiling_ft=500, visibility_sm=2.0, wind_kts=5,
                 as_headers=None):
    resp = api_client.record_weather_assessment(
        slot_id,
        {"ceiling_ft": ceiling_ft, "visibility_sm": visibility_sm,
         "wind_kts": wind_kts},
        as_headers or DISPATCHER,
    )
    return _ok("record_weather_assessment", resp)


def file_flight_log(slot_id, hobbs_out=100.0, hobbs_in=101.0,
                    pickup_outcome="CLEAN", pickup_technique="GROUND_PICKUP",
                    tow_field_notes=""):
    """File the FlightLog as the slot's assigned pilot (PRD §3.6 ownership)."""
    slot = get_slot(slot_id)
    pilot_id = slot["assigned_pilot_id"]
    resp = api_client.file_flight_log(
        slot_id,
        create_flight_log_payload(
            hobbs_out=hobbs_out, hobbs_in=hobbs_in,
            pickup_technique=pickup_technique, pickup_outcome=pickup_outcome,
            tow_field_notes=tow_field_notes,
        ),
        make_pilot_headers(pilot_id),
    )
    return _ok("file_flight_log", resp)


def fly_slot(slot_id, hobbs_out=100.0, hobbs_in=101.0, pickup_outcome="CLEAN"):
    """Schedule + file the flight log; returns the FlightLog."""
    schedule_slot(slot_id)
    return file_flight_log(slot_id, hobbs_out=hobbs_out, hobbs_in=hobbs_in,
                           pickup_outcome=pickup_outcome)


def weather_cancel_slot(slot_id, new_start):
    """Drive a SCHEDULED slot to CANCELLED_WEATHER: NO_GO -> WEATHER_HOLD,
    reschedule, second NO_GO (PRD §3.6 two-strike rule)."""
    schedule_slot(slot_id)
    post_weather(slot_id, **NO_GO_WEATHER)
    resp = api_client.reschedule_after_hold(
        slot_id, {"planned_start_utc": new_start}, DISPATCHER)
    _ok("reschedule_after_hold", resp)
    post_weather(slot_id, **NO_GO_WEATHER)
    return get_slot(slot_id)


# ---------------------------------------------------------------------------
# Tier 4 — full scenario assembly
# ---------------------------------------------------------------------------

def setup_operation(base_code="KMYB", route_kind="BEACH", pilot_endorsement="STANDARD",
                    hourly_rate_cents=TEST_DEFAULTS["HOURLY_RATE_CENTS"],
                    quota=TEST_DEFAULTS["QUOTA_HOURS"], month=TEST_DEFAULTS["MONTH"],
                    date_local="2026-08-13", window_start="2026-08-13T14:00:00Z",
                    window_end="2026-08-13T18:00:00Z", stadium_tfr_waiver=None,
                    banner_length_ft=TEST_DEFAULTS["BANNER_LENGTH_FT"],
                    banner_weight_lbs=TEST_DEFAULTS["BANNER_WEIGHT_LBS"],
                    with_ready_banner=True, clock=TEST_DEFAULTS["CLOCK_START"]):
    """The workhorse: clock + base + aircraft + pilot + route + client +
    campaign + (READY banner) + GRANTED approval + SeasonalCapacity.

    Returns a dict with every created entity. Single aircraft and single
    pilot at the base make the PRD §3.5 selectors deterministic.
    """
    if clock is not None:
        set_clock(clock)
    base = create_base(code=base_code)
    aircraft = create_aircraft(base["id"], hourly_rate_cents=hourly_rate_cents)
    pilot = create_pilot(base["id"], tow_endorsement_level=pilot_endorsement)
    route = create_route(base["id"], kind=route_kind)
    client = create_client()
    campaign = create_campaign(client["id"])
    banner = revision = None
    if with_ready_banner:
        banner, revision = create_ready_banner(
            campaign["id"], client["id"],
            length_ft=banner_length_ft, weight_lbs=banner_weight_lbs)
    approval = create_granted_approval(
        route["id"], date_local=date_local, window_start=window_start,
        window_end=window_end, stadium_tfr_waiver=stadium_tfr_waiver)
    capacity = create_capacity(base["id"], month=month, quota=quota)
    return {
        "base": base, "aircraft": aircraft, "pilot": pilot, "route": route,
        "client": client, "campaign": campaign, "banner": banner,
        "revision": revision, "approval": approval, "capacity": capacity,
    }


def book_slot_in(scenario, planned_start="2026-08-13T15:00:00Z",
                 planned_duration_hours=1, supersedes_slot_id=None):
    """Book a slot inside a scenario dict from setup_operation."""
    return book_slot(
        scenario["campaign"]["id"], scenario["client"]["id"],
        scenario["route"]["id"], scenario["approval"]["id"],
        scenario["banner"]["id"], scenario["capacity"]["id"],
        date_local=scenario["approval"]["date_local"],
        planned_start=planned_start,
        planned_duration_hours=planned_duration_hours,
        supersedes_slot_id=supersedes_slot_id,
    )


def list_campaign_credits(campaign_id):
    data = _ok("list_make_good_credits",
               api_client.list_make_good_credits(campaign_id, ADMIN))
    return data


def issue_invoice(campaign_id, period=TEST_DEFAULTS["MONTH"]):
    resp = api_client.issue_invoice(campaign_id, create_invoice_payload(
        period_yyyy_mm=period), FINANCE)
    return _ok("issue_invoice", resp)
