"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.
Every helper builds its preconditions from scratch via PRD endpoints only —
the harness restarts the server before every test, so nothing carries over.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REFERENCE_TARIFF
from .factories import (
    close_shift_payload,
    create_access_device_payload,
    create_charging_session_payload,
    create_credential_payload,
    create_event_booking_payload,
    create_ev_charger_payload,
    create_facility_payload,
    create_incident_payload,
    create_inspection_payload,
    create_maintenance_window_payload,
    create_monthly_agreement_payload,
    create_parker_account_payload,
    create_parking_session_payload,
    create_patrol_round_payload,
    create_rate_schedule_payload,
    create_repair_project_payload,
    create_shift_payload,
    report_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_gate_device_headers,
    make_monthly_parker_headers,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]  # X-User-ID "att-1"
AUD = TEST_USERS["revenue_auditor_headers"]  # X-User-ID "aud-1"
MS = TEST_USERS["maintenance_supervisor_headers"]
SEC = TEST_USERS["security_officer_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (FacilityManager-only capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, FM))


# ─── Tier 1/2: facility, tariff, gate ────────────────

def create_facility(name="Test Facility", total_spaces=200, monthly_capacity=50,
                    event_pool_spaces=40, levy_pct=None) -> dict:
    payload = create_facility_payload(
        name=name, total_spaces=total_spaces,
        monthly_capacity=monthly_capacity, event_pool_spaces=event_pool_spaces)
    if levy_pct is not None:
        payload["levy_pct"] = levy_pct
    return get_success_data(api_client.create_facility(payload, FM))


def create_draft_schedule(facility_id, label="Standard Tariff", cap_mode="CALENDAR_DAY",
                          effective_from="2026-08-01T00:00:00Z", **tariff_overrides) -> dict:
    tariff = dict(REFERENCE_TARIFF)
    tariff.update(tariff_overrides)
    payload = create_rate_schedule_payload(
        facility_id, label=label, cap_mode=cap_mode, effective_from=effective_from, **tariff)
    return get_success_data(api_client.create_rate_schedule(payload, FM))


def publish_schedule(rate_schedule_id, expected_facility_version) -> dict:
    return get_success_data(api_client.publish_rate_schedule(
        rate_schedule_id, expected_facility_version, FM))


def get_facility(facility_id) -> dict:
    return get_success_data(api_client.get_facility(facility_id, FM))


def setup_facility_with_published_rate(name="Tariff Facility", total_spaces=200,
                                       monthly_capacity=50, event_pool_spaces=40,
                                       levy_pct=None, cap_mode="CALENDAR_DAY",
                                       effective_from="2026-08-01T00:00:00Z",
                                       **tariff_overrides):
    """Facility + DRAFT schedule + publish. Returns (fresh facility, schedule)."""
    facility = create_facility(name, total_spaces, monthly_capacity,
                               event_pool_spaces, levy_pct)
    schedule = create_draft_schedule(facility["id"], cap_mode=cap_mode,
                                     effective_from=effective_from, **tariff_overrides)
    publish_schedule(schedule["id"], facility["version"])
    return get_facility(facility["id"]), schedule


def register_online_gate(facility_id, device_label="Entry Lane 1",
                         device_kind="ENTRY_GATE") -> dict:
    """Register a device and heartbeat it ONLINE as itself. Returns the device."""
    device = get_success_data(api_client.create_access_device(
        create_access_device_payload(facility_id, device_label=device_label,
                                     device_kind=device_kind), FM))
    return get_success_data(api_client.heartbeat_device(
        device["id"], make_gate_device_headers(device["id"])))


def setup_entry_ready_facility(name="Entry Facility", total_spaces=200,
                               monthly_capacity=50, event_pool_spaces=40,
                               levy_pct=None, cap_mode="CALENDAR_DAY",
                               **tariff_overrides):
    """Facility with a PUBLISHED reference tariff and one ONLINE entry gate.
    Returns (facility, schedule, gate)."""
    facility, schedule = setup_facility_with_published_rate(
        name=name, total_spaces=total_spaces, monthly_capacity=monthly_capacity,
        event_pool_spaces=event_pool_spaces, levy_pct=levy_pct, cap_mode=cap_mode,
        **tariff_overrides)
    gate = register_online_gate(facility["id"])
    return facility, schedule, gate


# ─── Tier 2: parkers, agreements, credentials ────────

def create_parker(full_name=None, email=None) -> dict:
    overrides = {}
    if full_name is not None:
        overrides["full_name"] = full_name
    if email is not None:
        overrides["email"] = email
    return get_success_data(api_client.create_parker_account(
        create_parker_account_payload(**overrides), ATT))


def submit_agreement(facility_id, parker_account_id, tier="STANDARD",
                     monthly_rate_cents=10000, ev_surcharge_cents=None) -> dict:
    overrides = {}
    if ev_surcharge_cents is not None:
        overrides["ev_surcharge_cents"] = ev_surcharge_cents
    return get_success_data(api_client.create_monthly_agreement(
        create_monthly_agreement_payload(
            facility_id, parker_account_id, tier=tier,
            monthly_rate_cents=monthly_rate_cents, **overrides), ATT))


def activate_agreement(agreement_id) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, ATT))


def create_active_agreement(facility_id, full_name=None, email=None, tier="STANDARD",
                            monthly_rate_cents=10000, ev_surcharge_cents=None):
    """Parker account + agreement walked to ACTIVE. Returns (parker, agreement)."""
    parker = create_parker(full_name, email)
    agreement = submit_agreement(facility_id, parker["id"], tier=tier,
                                 monthly_rate_cents=monthly_rate_cents,
                                 ev_surcharge_cents=ev_surcharge_cents)
    assert agreement["agreement_status"] == "APPROVED", (
        f"Setup expected APPROVED agreement, got {agreement['agreement_status']}")
    agreement = activate_agreement(agreement["id"])
    return parker, agreement


def issue_credential(agreement_id, credential_type="BADGE", deposit_cents=5000) -> dict:
    return get_success_data(api_client.create_credential(
        create_credential_payload(agreement_id, credential_type=credential_type,
                                  deposit_cents=deposit_cents), ATT))


def setup_agreement_with_credential(facility_id, credential_type="TRANSPONDER",
                                    deposit_cents=5000, monthly_rate_cents=10000):
    """ACTIVE agreement + ACTIVE credential. Returns (parker, agreement, credential)."""
    parker, agreement = create_active_agreement(
        facility_id, monthly_rate_cents=monthly_rate_cents)
    credential = issue_credential(agreement["id"], credential_type, deposit_cents)
    return parker, agreement, credential


# ─── Tier 2/3: shifts, sessions, settlements ─────────

def open_shift(facility_id, attendant_headers=None, opening_float_cents=10000) -> dict:
    headers = attendant_headers or ATT
    return get_success_data(api_client.create_shift(
        create_shift_payload(facility_id, opening_float_cents=opening_float_cents),
        headers))


def enter_vehicle(facility_id, gate, ticket_barcode, credential_id=None) -> dict:
    """Record a gate entry; the gate acts as itself (identity-bound call)."""
    payload = create_parking_session_payload(
        facility_id, gate["id"], ticket_barcode=ticket_barcode)
    if credential_id is not None:
        payload["credential_id"] = credential_id
    return get_success_data(api_client.create_parking_session(
        payload, make_gate_device_headers(gate["id"])))


def enter_vehicle_at(facility_id, gate, ticket_barcode, entry_at, credential_id=None) -> dict:
    """Set the logical clock, then record the entry so entry_at == entry instant."""
    set_clock(entry_at)
    return enter_vehicle(facility_id, gate, ticket_barcode, credential_id)


def quote_session_at(session_id, quote_at) -> dict:
    """Set the logical clock, then quote. Returns the quote payload."""
    set_clock(quote_at)
    return get_success_data(api_client.quote_session(session_id, ATT))


def pay_session_card(session_id) -> dict:
    return get_success_data(api_client.pay_session(
        session_id, {"tender_type": "CARD"}, ATT))


def pay_session_card_at(session_id, pay_at) -> dict:
    set_clock(pay_at)
    return pay_session_card(session_id)


def pay_session_cash(session_id, shift_id, attendant_headers=None) -> dict:
    headers = attendant_headers or ATT
    return get_success_data(api_client.pay_session(
        session_id, {"tender_type": "CASH", "shift_id": shift_id}, headers))


def setup_card_settled_session(name="Settled Facility", entry_at="2026-08-01T10:00:00Z",
                               pay_at="2026-08-01T11:00:00Z"):
    """Facility + tariff + gate + one session entered at entry_at and settled
    CARD at pay_at. Returns (facility, schedule, gate, session)."""
    facility, schedule, gate = setup_entry_ready_facility(name=name)
    session = enter_vehicle_at(facility["id"], gate, "SET-1", entry_at)
    session = pay_session_card_at(session["id"], pay_at)
    return facility, schedule, gate, session


def setup_shift_with_cash_settlement(name="Cash Facility", float_cents=10000,
                                     entry_at="2026-08-01T10:00:00Z",
                                     pay_at="2026-08-01T19:00:00Z"):
    """Facility + tariff + gate + OPEN shift (att-1) + one session settled CASH
    into that shift (9h stay -> 2400 capped with the reference tariff).
    Returns (facility, gate, shift, session)."""
    facility, schedule, gate = setup_entry_ready_facility(name=name)
    shift = open_shift(facility["id"], opening_float_cents=float_cents)
    session = enter_vehicle_at(facility["id"], gate, "CASH-1", entry_at)
    set_clock(pay_at)
    session = pay_session_cash(session["id"], shift["id"])
    return facility, gate, shift, session


def setup_closed_shift_with_recon(name="Recon Facility", float_cents=10000,
                                  entry_at="2026-08-01T10:00:00Z",
                                  pay_at="2026-08-01T19:00:00Z",
                                  counted_cash_cents=12400):
    """Cash-settled shift, closed by its attendant, reconciliation opened by
    aud-1 (DRAFT). Returns (facility, shift, session, reconciliation)."""
    facility, gate, shift, session = setup_shift_with_cash_settlement(
        name=name, float_cents=float_cents, entry_at=entry_at, pay_at=pay_at)
    closed = get_success_data(api_client.close_shift(
        shift["id"], close_shift_payload(counted_cash_cents), ATT))
    recon = get_success_data(api_client.create_reconciliation(
        {"shift_id": shift["id"]}, AUD))
    return facility, closed, session, recon


def setup_variance_review_recon(name="Variance Facility", float_cents=10000,
                                cash_fee_pay_at="2026-08-01T19:00:00Z",
                                counted_cash_cents=9400):
    """Full path to VARIANCE_REVIEW: counted 9400 vs expected 12400 -> -3000.
    Returns (facility, shift, reconciliation, incident_id of the auto incident)."""
    facility, shift, session, recon = setup_closed_shift_with_recon(
        name=name, float_cents=float_cents, pay_at=cash_fee_pay_at,
        counted_cash_cents=counted_cash_cents)
    submitted = get_success_data(api_client.submit_reconciliation(recon["id"], AUD))
    assert submitted["reconciliation_status"] == "VARIANCE_REVIEW", (
        f"Setup expected VARIANCE_REVIEW, got {submitted['reconciliation_status']}")
    incidents, _meta = _list_incidents(facility["id"], reconciliation_id=recon["id"])
    assert len(incidents) == 1, "Setup expected exactly one auto-created incident"
    return facility, shift, submitted, incidents[0]["id"]


def _list_incidents(facility_id, **params):
    from prd_bench_local_runner.testing import validate_paginated
    query = {"facility_id": facility_id}
    query.update(params)
    return validate_paginated(api_client.list_incidents(AUD, params=query))


# ─── Tier 2: inspections, repair projects ────────────

def create_inspection(facility_id, level_scope="L1",
                      scheduled_for="2026-08-02T09:00:00Z") -> dict:
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(facility_id, level_scope=level_scope,
                                  scheduled_for=scheduled_for), MS))


def report_inspection(inspection_id, load_bearing_rating=5, waterproofing_rating=5,
                      surface_rating=5, closed_space_count=None) -> dict:
    """Start fieldwork, then file the report. Returns REPORTED inspection."""
    get_success_data(api_client.start_inspection(inspection_id, MS))
    payload = report_inspection_payload(load_bearing_rating, waterproofing_rating,
                                        surface_rating)
    if closed_space_count is not None:
        payload["closed_space_count"] = closed_space_count
    return get_success_data(api_client.report_inspection(inspection_id, payload, MS))


def setup_reported_inspection(facility_id, level_scope="L1", load_bearing_rating=5,
                              waterproofing_rating=5, surface_rating=5,
                              closed_space_count=None) -> dict:
    inspection = create_inspection(facility_id, level_scope=level_scope)
    return report_inspection(inspection["id"], load_bearing_rating, waterproofing_rating,
                             surface_rating, closed_space_count)


def setup_critical_reported_facility(name="Critical Facility", level_scope="L1",
                                     closed_space_count=0, total_spaces=200,
                                     monthly_capacity=50):
    """Facility whose inspection on level_scope has been REPORTED CRITICAL
    (load-bearing 2 override), flipping posture to RESTRICTED.
    Returns (facility, inspection)."""
    facility = create_facility(name, total_spaces=total_spaces,
                               monthly_capacity=monthly_capacity)
    inspection = setup_reported_inspection(
        facility["id"], level_scope=level_scope, load_bearing_rating=2,
        waterproofing_rating=5, surface_rating=5, closed_space_count=closed_space_count)
    return get_facility(facility["id"]), inspection


def create_repair_project(facility_id, title="Repair", level_scope="L1",
                          estimated_cost_cents=1000, inspection_id=None,
                          closed_space_count=0) -> dict:
    overrides = {"closed_space_count": closed_space_count}
    if inspection_id is not None:
        overrides["inspection_id"] = inspection_id
    return get_success_data(api_client.create_repair_project(
        create_repair_project_payload(
            facility_id, title=title, level_scope=level_scope,
            estimated_cost_cents=estimated_cost_cents, **overrides), MS))


# ─── Tier 2: EV chargers and charging sessions ───────

def create_ev_charger(facility_id, charger_label="EV-01", max_kw=7) -> dict:
    """Propose a charger (stands PROPOSED)."""
    return get_success_data(api_client.create_ev_charger(
        create_ev_charger_payload(facility_id, charger_label=charger_label,
                                  max_kw=max_kw), MS))


def commission_ev_charger(facility_id, charger_label="EV-01", max_kw=7) -> dict:
    """Charger walked PROPOSED -> PERMITTED -> INSTALLED -> COMMISSIONED."""
    charger = create_ev_charger(facility_id, charger_label=charger_label, max_kw=max_kw)
    get_success_data(api_client.permit_ev_charger(charger["id"], MS))
    get_success_data(api_client.install_ev_charger(charger["id"], MS))
    return get_success_data(api_client.commission_ev_charger(charger["id"], MS))


# ─── Tier 2: events ──────────────────────────────────

def create_event_booking(facility_id, event_name="Event", start_at="2026-08-20T18:00:00Z",
                         end_at="2026-08-20T23:00:00Z", presale_allocation=0,
                         min_staff=0, deposit_cents=None, cancellation_policy=None) -> dict:
    overrides = {}
    if deposit_cents is not None:
        overrides["deposit_cents"] = deposit_cents
    if cancellation_policy is not None:
        overrides["cancellation_policy"] = cancellation_policy
    return get_success_data(api_client.create_event_booking(
        create_event_booking_payload(
            facility_id, event_name=event_name, start_at=start_at, end_at=end_at,
            presale_allocation=presale_allocation, min_staff=min_staff, **overrides), FM))


def confirm_event_booking(event_booking_id, roster=None) -> dict:
    return get_success_data(api_client.confirm_event_booking(
        event_booking_id, roster or [], FM))


# ─── Tier 5: close-of-business ───────────────────────

def run_close_of_business(facility_id) -> dict:
    """Run the daily close. Returns the summary payload."""
    return get_success_data(api_client.close_of_business(facility_id, FM))
