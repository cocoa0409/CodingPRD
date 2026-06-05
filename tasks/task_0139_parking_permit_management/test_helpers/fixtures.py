"""Composite setup helpers for Parking & Permit Management tests.

Each fixture builds preconditions from scratch using only PRD-declared endpoints
(the per-test-server harness starts every test against an empty database). Setup
calls use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing downstream assertion.

Identity threading: Motorist and Merchant are entity_backed. After creating one,
ownership-gated calls use make_motorist_headers(motorist["id"]) /
make_merchant_headers(merchant["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_motorist_headers,
    make_merchant_headers,
)
from . import factories as F

ADMIN = TEST_USERS["facility_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ---------------------------------------------------------------------------
# Clock control (PRD §3.3 administrative test-driving capability)
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Fix the server's notion of current UTC. FacilityAdmin-only."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: primitive single-entity creators (return the data dict)
# ---------------------------------------------------------------------------
def create_garage(**overrides) -> dict:
    return get_success_data(api_client.create_garage(F.create_garage_payload(**overrides), ADMIN))


def create_rate_plan(**overrides) -> dict:
    return get_success_data(api_client.create_rate_plan(F.create_rate_plan_payload(**overrides), ADMIN))


def create_zone(garage_id, rate_plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_zone(F.create_zone_payload(garage_id, rate_plan_id, **overrides), ADMIN)
    )


def create_space(zone_id, **overrides) -> dict:
    return get_success_data(api_client.create_space(F.create_space_payload(zone_id, **overrides), ADMIN))


def create_motorist(email, **overrides) -> dict:
    return get_success_data(api_client.create_motorist(F.create_motorist_payload(email, **overrides), ADMIN))


def create_merchant(garage_id, **overrides) -> dict:
    return get_success_data(api_client.create_merchant(F.create_merchant_payload(garage_id, **overrides), ADMIN))


def create_plate_read(garage_id, plate, zone_id, read_at_utc, **overrides) -> dict:
    return get_success_data(
        api_client.create_plate_read(
            F.create_plate_read_payload(garage_id, plate, zone_id, read_at_utc, **overrides), OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: facility setup (garage + rate plan + one zone [+ spaces])
# ---------------------------------------------------------------------------
def setup_garage_with_zone(zone_type="MIXED", permit_capacity=5, num_spaces=0,
                           garage_overrides=None, rate_overrides=None, zone_overrides=None):
    """Active facility: garage + rate plan + one zone, plus `num_spaces` spaces.

    Returns dict with garage, rate_plan, zone, spaces (list).
    """
    garage = create_garage(**(garage_overrides or {}))
    rate_plan = create_rate_plan(**(rate_overrides or {}))
    zone = create_zone(
        garage["id"], rate_plan["id"], zone_type=zone_type,
        permit_capacity=permit_capacity, **(zone_overrides or {})
    )
    spaces = [create_space(zone["id"], label=f"S{i+1}") for i in range(num_spaces)]
    return {"garage": garage, "rate_plan": rate_plan, "zone": zone, "spaces": spaces}


def setup_transient_facility(num_spaces=1, **rate_overrides):
    """Garage + TRANSIENT zone (permit_capacity 0) + `num_spaces` spaces.

    Returns dict with garage, rate_plan, zone, spaces.
    """
    return setup_garage_with_zone(
        zone_type="TRANSIENT", permit_capacity=0, num_spaces=num_spaces,
        rate_overrides=rate_overrides or None,
    )


# ---------------------------------------------------------------------------
# Tier 3: permit lifecycle shortcuts
# ---------------------------------------------------------------------------
def request_permit(zone_id, motorist_id, plate) -> dict:
    """Motorist requests a permit (REQUESTED). Ownership-gated -> entity-backed headers."""
    return get_success_data(
        api_client.create_permit(
            F.create_permit_payload(zone_id, motorist_id, plate), make_motorist_headers(motorist_id)
        )
    )


def activate_permit(permit_id, expected_zone_version) -> dict:
    """FacilityAdmin activates a REQUESTED permit with the OCC zone version token."""
    return get_success_data(
        api_client.activate_permit(permit_id, {"expected_zone_version": expected_zone_version}, ADMIN)
    )


def setup_active_permit(zone_type="MIXED", permit_capacity=5, plate="ACT111",
                        email="active@x.com", rate_overrides=None):
    """Garage + zone + motorist + ACTIVE permit.

    Returns dict: garage, rate_plan, zone (re-read post-activation), motorist, permit.
    """
    facility = setup_garage_with_zone(
        zone_type=zone_type, permit_capacity=permit_capacity, rate_overrides=rate_overrides
    )
    zone = facility["zone"]
    motorist = create_motorist(email, default_plate=plate)
    permit = request_permit(zone["id"], motorist["id"], plate)
    permit = activate_permit(permit["id"], zone["version"])
    zone = get_success_data(api_client.get_zone(zone["id"], ADMIN))
    return {
        "garage": facility["garage"], "rate_plan": facility["rate_plan"],
        "zone": zone, "motorist": motorist, "permit": permit,
    }


def add_waitlist_entry(zone_id, motorist_id, plate) -> dict:
    """Motorist joins a zone waitlist (WAITING). Ownership-gated."""
    return get_success_data(
        api_client.add_waitlist_entry(
            zone_id, F.create_waitlist_entry_payload(motorist_id, plate), make_motorist_headers(motorist_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: access-session lifecycle
# ---------------------------------------------------------------------------
def open_session(garage_id, plate, entry_at_utc, permit_id=None) -> dict:
    """FacilityAdmin opens an access session at the gate."""
    overrides = {"permit_id": permit_id} if permit_id is not None else {}
    return get_success_data(
        api_client.create_session(
            F.create_session_payload(garage_id, plate, entry_at_utc, **overrides), ADMIN
        )
    )


def close_session(session_id, exit_at_utc, validation_id=None) -> dict:
    """FacilityAdmin exits (closes) an OPEN session, computing charges."""
    overrides = {"validation_id": validation_id} if validation_id is not None else {}
    return get_success_data(
        api_client.exit_session(session_id, F.exit_session_payload(exit_at_utc, **overrides), ADMIN)
    )


def setup_open_transient_session(plate="SES111", entry_at_utc="2026-06-01T10:00:00Z",
                                 num_spaces=1, **rate_overrides):
    """Transient facility with one OPEN session occupying a stall.

    Sets the clock to entry_at_utc first. Returns dict: garage, rate_plan, zone,
    spaces, session.
    """
    facility = setup_transient_facility(num_spaces=num_spaces, **rate_overrides)
    set_clock(entry_at_utc)
    session = open_session(facility["garage"]["id"], plate, entry_at_utc)
    return {**facility, "session": session}


# ---------------------------------------------------------------------------
# Tier 5: merchant validations
# ---------------------------------------------------------------------------
def issue_validation(garage_id, merchant_id, discount_kind, discount_value,
                     expires_at_utc="2026-06-02T00:00:00Z") -> dict:
    """Merchant issues a validation. Ownership-gated -> entity-backed headers."""
    return get_success_data(
        api_client.create_validation(
            F.create_validation_payload(garage_id, merchant_id, discount_kind,
                                        discount_value, expires_at_utc),
            make_merchant_headers(merchant_id),
        )
    )


def setup_transient_session_with_validation(discount_kind, discount_value,
                                            merchant_budget=10000,
                                            plate="VAL111",
                                            entry_at_utc="2026-06-01T10:00:00Z",
                                            expires_at_utc="2026-06-02T00:00:00Z",
                                            **rate_overrides):
    """Transient facility + merchant + an ISSUED validation + one OPEN session.

    Returns dict: garage, rate_plan, zone, spaces, merchant, validation, session.
    """
    facility = setup_transient_facility(num_spaces=1, **rate_overrides)
    garage = facility["garage"]
    merchant = create_merchant(garage["id"], validation_budget_cents=merchant_budget)
    validation = issue_validation(garage["id"], merchant["id"], discount_kind,
                                  discount_value, expires_at_utc=expires_at_utc)
    set_clock(entry_at_utc)
    session = open_session(garage["id"], plate, entry_at_utc)
    return {**facility, "merchant": merchant, "validation": validation, "session": session}


# ---------------------------------------------------------------------------
# Tier 6: enforcement / citations / appeals
# ---------------------------------------------------------------------------
def issue_citation(garage_id, plate, plate_read_id, base_fine_cents=5000,
                   violation_code="NO_PERMIT") -> dict:
    """EnforcementOfficer issues a citation from a plate read."""
    return get_success_data(
        api_client.create_citation(
            F.create_citation_payload(garage_id, plate, plate_read_id,
                                      violation_code=violation_code,
                                      base_fine_cents=base_fine_cents),
            OFFICER,
        )
    )


def setup_issued_citation(plate="CIT111", base_fine_cents=5000, email="cit@x.com",
                          register_motorist=True, read_at_utc="2026-06-01T08:00:00Z"):
    """Garage + TRANSIENT zone + (optional motorist) + plate read + one ISSUED citation.

    Returns dict: garage, rate_plan, zone, motorist (or None), plate_read, citation.
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    motorist = create_motorist(email, default_plate=plate) if register_motorist else None
    plate_read = create_plate_read(garage["id"], plate, zone["id"], read_at_utc)
    citation = issue_citation(garage["id"], plate, plate_read["id"], base_fine_cents=base_fine_cents)
    return {
        "garage": garage, "rate_plan": facility["rate_plan"], "zone": zone,
        "motorist": motorist, "plate_read": plate_read, "citation": citation,
    }


def submit_appeal(citation_id, motorist_id, reason="reason") -> dict:
    """Motorist submits an appeal against a citation. Ownership-gated by motorist_id."""
    return get_success_data(
        api_client.create_appeal(
            F.create_appeal_payload(citation_id, motorist_id, reason), make_motorist_headers(motorist_id)
        )
    )


def decide_appeal(appeal_id, decision) -> dict:
    """EnforcementOfficer decides an appeal (UPHELD or DISMISSED)."""
    return get_success_data(api_client.decide_appeal(appeal_id, {"decision": decision}, OFFICER))


def setup_submitted_appeal(plate="APL111", base_fine_cents=5000, email="apl@x.com",
                           read_at_utc="2026-06-01T08:00:00Z"):
    """Issued citation owned by a registered motorist + a SUBMITTED appeal on it.

    Returns dict: garage, zone, motorist, plate_read, citation, appeal.
    """
    ctx = setup_issued_citation(plate=plate, base_fine_cents=base_fine_cents,
                                email=email, register_motorist=True, read_at_utc=read_at_utc)
    appeal = submit_appeal(ctx["citation"]["id"], ctx["motorist"]["id"])
    return {**ctx, "appeal": appeal}


def issue_n_citations_same_plate(garage_id, zone_id, plate, count, base_fine_cents=5000,
                                 base_read_iso_hour=8):
    """Issue `count` citations for the same plate (each from its own plate read).

    Returns the list of issued citation dicts in chronological order. Used to set
    up repeat-offender escalation tiers (prior_count accumulates).
    """
    citations = []
    for i in range(count):
        read_at = f"2026-06-01T{base_read_iso_hour + i:02d}:00:00Z"
        pr = create_plate_read(garage_id, plate, zone_id, read_at)
        citations.append(issue_citation(garage_id, plate, pr["id"], base_fine_cents=base_fine_cents))
    return citations


# ---------------------------------------------------------------------------
# Tier 7: event pricing
# ---------------------------------------------------------------------------
def create_event_window(garage_id, window_start_utc, window_end_utc,
                        flat_surcharge_cents=1000, multiplier=None, name="Event") -> dict:
    """Create a DRAFT event-pricing window (multiplier optional -> server default 1.0)."""
    overrides = {}
    if multiplier is not None:
        overrides["multiplier"] = multiplier
    return get_success_data(
        api_client.create_event_pricing(
            F.create_event_pricing_payload(garage_id, window_start_utc, window_end_utc,
                                           flat_surcharge_cents=flat_surcharge_cents,
                                           name=name, **overrides),
            ADMIN,
        )
    )


def publish_event_window(ep_id) -> dict:
    """Publish a DRAFT window so it begins pricing sessions."""
    return get_success_data(api_client.publish_event_pricing(ep_id, ADMIN))


def setup_published_event_session(window_start_utc, window_end_utc, multiplier,
                                  flat_surcharge_cents, entry_at_utc, plate="EVT111",
                                  **rate_overrides):
    """Transient facility + a PUBLISHED event window + one OPEN session at entry_at_utc.

    Returns dict: garage, rate_plan, zone, spaces, event, session.
    """
    facility = setup_transient_facility(num_spaces=1, **rate_overrides)
    garage = facility["garage"]
    event = create_event_window(garage["id"], window_start_utc, window_end_utc,
                                flat_surcharge_cents=flat_surcharge_cents, multiplier=multiplier)
    publish_event_window(event["id"])
    set_clock(entry_at_utc)
    session = open_session(garage["id"], plate, entry_at_utc)
    return {**facility, "event": event, "session": session}


# ---------------------------------------------------------------------------
# Convenience getters (re-read current state after side effects)
# ---------------------------------------------------------------------------
def get_zone(zone_id) -> dict:
    return get_success_data(api_client.get_zone(zone_id, ADMIN))


def get_garage(garage_id) -> dict:
    return get_success_data(api_client.get_garage(garage_id, ADMIN))


def get_space(space_id) -> dict:
    return get_success_data(api_client.get_space(space_id, ADMIN))


def get_motorist(motorist_id) -> dict:
    return get_success_data(api_client.get_motorist(motorist_id, ADMIN))


def get_merchant(merchant_id) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, ADMIN))


def get_permit(permit_id) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def get_citation(citation_id) -> dict:
    return get_success_data(api_client.get_citation(citation_id, ADMIN))


def get_validation(validation_id) -> dict:
    return get_success_data(api_client.get_validation(validation_id, ADMIN))


def get_waitlist_entry(entry_id) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, ADMIN))


def get_session(session_id) -> dict:
    return get_success_data(api_client.get_session(session_id, ADMIN))
