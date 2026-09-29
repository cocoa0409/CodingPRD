"""Setup helpers.

The harness restarts the API server before every test, so each test begins
against an empty store.  Everything a test needs must therefore be built from
scratch through the public endpoints — which is exactly what these helpers do.

Two layers:

* granular steps (``create_port``, ``approve_operator``, ``book`` …), each one
  request, each returning the created or updated resource; and
* composites (``setup_selling_departure``, ``setup_ticketed_booking`` …) that
  assemble the canonical world in the order the API requires: port, meeting
  point, operator, safety audit, vetting approval, excursion, publication, port
  call, tender waves, sales opening, departure, tender assignment.

Creates are asserted at 201 and actions at 200, so a broken setup fails loudly
at the step that broke rather than in the assertion under test.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .constants import DEFAULT_CLOCK, INSTANTS
from .test_users import (
    AUDITOR_USER_ID,
    TEST_USERS,
    make_guest_headers,
    make_vetting_officer_headers,
)

DESK = TEST_USERS["desk_headers"]
MANAGER = TEST_USERS["manager_headers"]
VETTING_OFFICER = TEST_USERS["vetting_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
PORT_AGENT = TEST_USERS["port_agent_headers"]
RISK_OFFICER = TEST_USERS["risk_officer_headers"]
SECOND_RISK_OFFICER = TEST_USERS["second_risk_officer_headers"]
FINANCE = TEST_USERS["finance_headers"]


class World(dict):
    """Dict with attribute access, so composites read as ``world.departure``."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _created(resp) -> dict:
    validate_success(resp, 201)
    return get_success_data(resp)


def _acted(resp) -> dict:
    validate_success(resp, 200)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

def set_clock(api, current_utc: str) -> None:
    """Move the logical clock every temporal rule reads."""
    validate_success(api.set_clock(current_utc), 200)


# --------------------------------------------------------------------------
# Ports and meeting points
# --------------------------------------------------------------------------

def create_port(api, headers=MANAGER, **overrides) -> dict:
    return _created(api.create_port(factories.create_port_payload(**overrides), headers))


def create_tender_port(api, headers=MANAGER, **overrides) -> dict:
    return _created(
        api.create_port(factories.create_tender_port_payload(**overrides), headers)
    )


def create_meeting_point(api, port_id, headers=MANAGER, **overrides) -> dict:
    return _created(
        api.create_meeting_point(
            port_id, factories.create_meeting_point_payload(**overrides), headers
        )
    )


# --------------------------------------------------------------------------
# Operators, audits and vetting
# --------------------------------------------------------------------------

def create_operator(api, port_id, headers=VETTING_OFFICER, **overrides) -> dict:
    return _created(
        api.create_operator(factories.create_operator_payload(port_id, **overrides),
                            headers)
    )


def record_safety_audit(api, operator_id, headers=None, auditor_user_id=None,
                        **overrides) -> dict:
    """Record an audit.  The recorded auditor matters: whoever conducted the
    newest audit may not be the officer who approves that operator."""
    if headers is None:
        headers = (
            make_vetting_officer_headers(auditor_user_id)
            if auditor_user_id
            else make_vetting_officer_headers(AUDITOR_USER_ID)
        )
    return _created(
        api.create_safety_audit(
            operator_id, factories.create_safety_audit_payload(**overrides), headers
        )
    )


def vetting_action(api, operator_id, action, headers=VETTING_OFFICER,
                   note=None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return _acted(api.vetting_action(operator_id, payload, headers))


def create_approved_operator(api, port_id, audit_overrides=None,
                             operator_overrides=None, headers=VETTING_OFFICER,
                             auditor_user_id=AUDITOR_USER_ID) -> dict:
    """Register an operator, record one audit and walk DRAFT → SUBMITTED →
    APPROVED.  The audit is recorded by a different officer than the approver."""
    operator = create_operator(api, port_id, headers=headers,
                               **(operator_overrides or {}))
    record_safety_audit(api, operator["id"], auditor_user_id=auditor_user_id,
                        **(audit_overrides or {}))
    vetting_action(api, operator["id"], "SUBMIT", headers=headers)
    return vetting_action(api, operator["id"], "APPROVE", headers=headers)


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

def create_excursion(api, port_id, operator_id, headers=MANAGER, **overrides) -> dict:
    return _created(
        api.create_excursion(
            factories.create_excursion_payload(port_id, operator_id, **overrides),
            headers,
        )
    )


def catalog_action(api, excursion_id, action, headers=MANAGER, note=None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return _acted(api.catalog_action(excursion_id, payload, headers))


def publish_excursion(api, excursion_id, headers=MANAGER) -> dict:
    """DRAFT → PENDING_REVIEW → PUBLISHED."""
    catalog_action(api, excursion_id, "SUBMIT_REVIEW", headers=headers)
    return catalog_action(api, excursion_id, "PUBLISH", headers=headers)


def create_published_excursion(api, port_id, operator_id, headers=MANAGER,
                               **overrides) -> dict:
    excursion = create_excursion(api, port_id, operator_id, headers=headers,
                                 **overrides)
    return publish_excursion(api, excursion["id"], headers=headers)


# --------------------------------------------------------------------------
# Port calls, delays and tender waves
# --------------------------------------------------------------------------

def create_port_call(api, port_id, headers=PORT_AGENT, **overrides) -> dict:
    return _created(
        api.create_port_call(factories.create_port_call_payload(port_id, **overrides),
                             headers)
    )


def port_call_transition(api, port_call_id, action, headers=PORT_AGENT,
                         note=None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return _acted(api.port_call_transition(port_call_id, payload, headers))


def open_port_call_sales(api, port_call_id, headers=PORT_AGENT) -> dict:
    return port_call_transition(api, port_call_id, "OPEN_SALES", headers=headers)


def arrive_port_call(api, port_call_id, headers=PORT_AGENT) -> dict:
    """PLANNED/OPEN_FOR_SALE → IN_PORT, the state check-in and dispatch need."""
    return port_call_transition(api, port_call_id, "ARRIVE", headers=headers)


def record_delay(api, port_call_id, additional_delay_minutes, headers=PORT_AGENT,
                 reason_code=None) -> dict:
    payload = {"additional_delay_minutes": additional_delay_minutes}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return _acted(api.record_delay(port_call_id, payload, headers))


def create_tender_wave(api, port_call_id, headers=PORT_AGENT, **overrides) -> dict:
    return _created(
        api.create_tender_wave(
            port_call_id, factories.create_tender_wave_payload(**overrides), headers
        )
    )


# --------------------------------------------------------------------------
# Departures
# --------------------------------------------------------------------------

def create_departure(api, excursion_id, port_call_id, meeting_point_id,
                     headers=MANAGER, **overrides) -> dict:
    return _created(
        api.create_departure(
            factories.create_departure_payload(
                excursion_id, port_call_id, meeting_point_id, **overrides
            ),
            headers,
        )
    )


def assign_tender_wave(api, departure_id, headers=PORT_AGENT) -> dict:
    """The server picks the wave by policy; the caller supplies no choice."""
    return _acted(api.assign_tender_wave(departure_id, {}, headers))


def rebalance_allocation(api, departure_id, expected_departure_version,
                         precruise_allocation, onboard_allocation,
                         total_capacity=None, headers=MANAGER) -> dict:
    payload = {
        "expected_departure_version": expected_departure_version,
        "precruise_allocation": precruise_allocation,
        "onboard_allocation": onboard_allocation,
    }
    if total_capacity is not None:
        payload["total_capacity"] = total_capacity
    return _acted(api.rebalance_allocation(departure_id, payload, headers))


def reschedule_meeting(api, departure_id, meeting_time_utc,
                       dispatch_dwell_minutes=None, headers=MANAGER) -> dict:
    payload = {"meeting_time_utc": meeting_time_utc}
    if dispatch_dwell_minutes is not None:
        payload["dispatch_dwell_minutes"] = dispatch_dwell_minutes
    return _acted(api.reschedule_meeting(departure_id, payload, headers))


def cancel_departure(api, departure_id, cause, offer_alternative=None, note=None,
                     headers=MANAGER) -> dict:
    payload = {"cause": cause}
    if offer_alternative is not None:
        payload["offer_alternative"] = offer_alternative
    if note is not None:
        payload["note"] = note
    return _acted(api.cancel_departure(departure_id, payload, headers))


def dispatch_departure(api, departure_id, headers=PORT_AGENT) -> dict:
    return _acted(api.departure_operation(departure_id, {"action": "DISPATCH"}, headers))


def complete_departure(api, departure_id, actual_return_utc,
                       headers=PORT_AGENT) -> dict:
    return _acted(
        api.departure_operation(
            departure_id,
            {"action": "COMPLETE", "actual_return_utc": actual_return_utc},
            headers,
        )
    )


def get_departure(api, departure_id, headers=MANAGER) -> dict:
    return _acted(api.get_departure(departure_id, headers))


def get_departure_version(api, departure_id, headers=MANAGER) -> int:
    """Read the departure's current version, which every booking create and
    every allocation rebalance must echo back."""
    return get_departure(api, departure_id, headers)["version"]


def get_operator(api, operator_id, headers=VETTING_OFFICER) -> dict:
    return _acted(api.get_operator(operator_id, headers))


def get_operator_version(api, operator_id, headers=FINANCE) -> int:
    """Read the operator's current version, which a statement create must echo."""
    return get_operator(api, operator_id, headers)["version"]


# --------------------------------------------------------------------------
# Guests and bookings
# --------------------------------------------------------------------------

def create_guest(api, headers=DESK, **overrides) -> dict:
    return _created(api.create_guest(factories.create_guest_payload(**overrides), headers))


def create_booking(api, departure_id, guest_id, expected_departure_version=None,
                   headers=DESK, **overrides) -> dict:
    if expected_departure_version is None:
        expected_departure_version = get_departure_version(api, departure_id)
    return _created(
        api.create_booking(
            factories.create_booking_payload(
                departure_id, guest_id, expected_departure_version, **overrides
            ),
            headers,
        )
    )


def fulfillment_action(api, booking_id, action, headers=DESK, note=None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return _acted(api.fulfillment_action(booking_id, payload, headers))


def ticket_booking(api, booking_id, headers=DESK) -> dict:
    """BOOKED → TICKETED, which is also the charge event."""
    return fulfillment_action(api, booking_id, "TICKET", headers=headers)


def check_in_booking(api, booking_id, headers=DESK) -> dict:
    return fulfillment_action(api, booking_id, "CHECK_IN", headers=headers)


def mark_no_show(api, booking_id, headers=DESK) -> dict:
    return fulfillment_action(api, booking_id, "MARK_NO_SHOW", headers=headers)


def cancel_booking(api, booking_id, headers=DESK, reason_code=None) -> dict:
    payload = {}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return _acted(api.cancel_booking(booking_id, payload, headers))


def cancel_booking_as_guest(api, booking_id, guest_id, reason_code=None) -> dict:
    """A Guest caller must be the booking's own guest, so the acting identity is
    the guest row's id."""
    return cancel_booking(api, booking_id, headers=make_guest_headers(guest_id),
                          reason_code=reason_code)


def get_booking(api, booking_id, headers=DESK) -> dict:
    return _acted(api.get_booking(booking_id, headers))


def list_ledger_entries(api, headers=FINANCE, params=None):
    resp = api.list_ledger_entries(headers, params=params)
    validate_success(resp, 200)
    return resp.json()["data"]


def ledger_entries_for_booking(api, booking_id, headers=FINANCE):
    """The booking's money history, in the created_at ASC order the PRD fixes."""
    return list_ledger_entries(api, headers=headers,
                               params={"booking_id": booking_id, "limit": 100})


# --------------------------------------------------------------------------
# Incidents and claims
# --------------------------------------------------------------------------

def file_incident(api, booking_id, headers=DESK, **overrides) -> dict:
    return _created(
        api.file_incident(booking_id, factories.create_incident_payload(**overrides),
                          headers)
    )


def open_claim(api, incident_id, headers=RISK_OFFICER, **overrides) -> dict:
    return _created(
        api.open_claim(incident_id, factories.create_claim_payload(**overrides), headers)
    )


def close_incident(api, incident_id, headers=RISK_OFFICER,
                   resolution_note=None) -> dict:
    payload = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return _acted(api.close_incident(incident_id, payload, headers))


def claim_action(api, claim_id, action, headers=SECOND_RISK_OFFICER, note=None,
                 **extra) -> dict:
    """Adjudication is barred to the officer who opened the claim, so the default
    actor here is a different officer than ``open_claim`` uses."""
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    payload.update(extra)
    return _acted(api.claim_action(claim_id, payload, headers))


def adjudicate_upheld(api, claim_id, liability_share_bps, settlement_amount_cents,
                      headers=SECOND_RISK_OFFICER) -> dict:
    return claim_action(
        api, claim_id, "ADJUDICATE_UPHELD", headers=headers,
        liability_share_bps=liability_share_bps,
        settlement_amount_cents=settlement_amount_cents,
    )


def adjudicate_denied(api, claim_id, headers=SECOND_RISK_OFFICER) -> dict:
    return claim_action(api, claim_id, "ADJUDICATE_DENIED", headers=headers)


# --------------------------------------------------------------------------
# Commission statements
# --------------------------------------------------------------------------

def create_statement(api, operator_id, port_call_id, basis="PROVISIONAL",
                     expected_operator_version=None, headers=FINANCE,
                     **overrides) -> dict:
    if expected_operator_version is None:
        expected_operator_version = get_operator_version(api, operator_id,
                                                         headers=headers)
    return _created(
        api.create_commission_statement(
            factories.create_statement_payload(
                operator_id, port_call_id, expected_operator_version, basis,
                **overrides
            ),
            headers,
        )
    )


def statement_transition(api, statement_id, action, headers=FINANCE, note=None,
                         **extra) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    payload.update(extra)
    return _acted(api.statement_transition(statement_id, payload, headers))


# --------------------------------------------------------------------------
# Composites
# --------------------------------------------------------------------------

def setup_port_world(api, clock=DEFAULT_CLOCK, tender=False, port=None,
                     meeting_point=None) -> World:
    """A port with one meeting point, and the clock parked at a known instant."""
    if clock is not None:
        set_clock(api, clock)
    port_row = (
        create_tender_port(api, **(port or {}))
        if tender
        else create_port(api, **(port or {}))
    )
    defaults = {} if not tender else {"name": "Pier Apron A", "zone": "PIER_APRON"}
    defaults.update(meeting_point or {})
    return World(
        port=port_row,
        meeting_point=create_meeting_point(api, port_row["id"], **defaults),
    )


def setup_catalog_world(api, clock=DEFAULT_CLOCK, tender=False, port=None,
                        meeting_point=None, operator=None, audit=None,
                        excursion=None, publish=True) -> World:
    """A port, a meeting point, an APPROVED operator and one excursion — published
    unless the caller wants it left in DRAFT."""
    world = setup_port_world(api, clock=clock, tender=tender, port=port,
                             meeting_point=meeting_point)
    world.operator = create_approved_operator(
        api, world.port["id"], audit_overrides=audit, operator_overrides=operator
    )
    excursion_overrides = {"is_line_operated": True} if tender else {}
    excursion_overrides.update(excursion or {})
    world.excursion = create_excursion(
        api, world.port["id"], world.operator["id"], **excursion_overrides
    )
    if publish:
        world.excursion = publish_excursion(api, world.excursion["id"])
    return world


def setup_selling_departure(api, clock=DEFAULT_CLOCK, tender=False, port=None,
                            meeting_point=None, operator=None, audit=None,
                            excursion=None, publish=True, port_call=None,
                            tender_waves=None, open_sales=True, departure=None,
                            assign_wave=None) -> World:
    """The canonical world: a published excursion on an OPEN_FOR_SALE port call
    with one departure that therefore lands straight in SELLING.

    At a TENDER port one EXCURSION_PRIORITY wave is published by default and the
    departure is assigned to it, since an unassigned group carries a 20-minute
    projection penalty.
    """
    world = setup_catalog_world(api, clock=clock, tender=tender, port=port,
                               meeting_point=meeting_point, operator=operator,
                               audit=audit, excursion=excursion, publish=publish)
    world.port_call = create_port_call(api, world.port["id"], **(port_call or {}))

    if tender_waves is None:
        tender_waves = [{}] if tender else []
    world.tender_waves = [
        create_tender_wave(api, world.port_call["id"], **overrides)
        for overrides in tender_waves
    ]

    if open_sales:
        world.port_call = open_port_call_sales(api, world.port_call["id"])

    world.departure = create_departure(
        api, world.excursion["id"], world.port_call["id"], world.meeting_point["id"],
        **(departure or {}),
    )

    if assign_wave is None:
        assign_wave = bool(world.tender_waves)
    if assign_wave:
        world.departure = assign_tender_wave(api, world.departure["id"])
    return world


def create_guest_and_booking(api, world, guest=None, booking=None,
                             headers=DESK) -> tuple:
    """Register a guest on the world's voyage and book them onto its departure."""
    guest_overrides = {"voyage_code": world.port_call["voyage_code"]}
    guest_overrides.update(guest or {})
    guest_row = create_guest(api, **guest_overrides)
    booking_row = create_booking(
        api, world.departure["id"], guest_row["id"], headers=headers,
        **(booking or {}),
    )
    return guest_row, booking_row


def setup_booked_booking(api, clock=DEFAULT_CLOCK, guest=None, booking=None,
                         **world_kwargs) -> World:
    """A SELLING departure carrying one BOOKED / AUTHORIZED booking."""
    world = setup_selling_departure(api, clock=clock, **world_kwargs)
    world.guest, world.booking = create_guest_and_booking(
        api, world, guest=guest, booking=booking
    )
    return world


def setup_ticketed_booking(api, clock=DEFAULT_CLOCK, guest=None, booking=None,
                           **world_kwargs) -> World:
    """A booking taken to TICKETED / CHARGED, the state the money rules key on."""
    world = setup_booked_booking(api, clock=clock, guest=guest, booking=booking,
                                 **world_kwargs)
    world.booking = ticket_booking(api, world.booking["id"])
    return world


def setup_checked_in_booking(api, clock=DEFAULT_CLOCK,
                             checkin_clock=INSTANTS["CHECKIN_CLOCK"],
                             guest=None, booking=None, **world_kwargs) -> World:
    """A TICKETED booking checked in.

    Order matters: the booking is taken and ticketed at the early clock, then the
    clock is moved to ``checkin_clock`` — arrival may only be marked once the
    clock has reached the call's effective arrival, and check-in only inside the
    inclusive window from 45 minutes before the meeting time to 10 minutes after
    it — and only then is the call brought IN_PORT and the guest checked in.  The
    default ``checkin_clock`` sits inside the window for the canonical 09:00Z
    meeting time.
    """
    world = setup_ticketed_booking(api, clock=clock, guest=guest, booking=booking,
                                   **world_kwargs)
    if checkin_clock is not None:
        set_clock(api, checkin_clock)
    world.port_call = arrive_port_call(api, world.port_call["id"])
    world.booking = check_in_booking(api, world.booking["id"])
    return world


def setup_operating_departure(api, clock=DEFAULT_CLOCK,
                              checkin_clock=INSTANTS["CHECKIN_CLOCK"],
                              guest=None, booking=None, **world_kwargs) -> World:
    """A departure dispatched into OPERATING with one CHECKED_IN booking."""
    world = setup_checked_in_booking(api, clock=clock, checkin_clock=checkin_clock,
                                     guest=guest, booking=booking, **world_kwargs)
    world.departure = dispatch_departure(api, world.departure["id"])
    return world


def setup_completed_departure(api, actual_return_utc, clock=DEFAULT_CLOCK,
                              checkin_clock=INSTANTS["CHECKIN_CLOCK"],
                              return_clock=None, guest=None,
                              booking=None, **world_kwargs) -> World:
    """A COMPLETED departure.  ``actual_return_utc`` must be at or after the
    meeting time and at or before the logical clock, so the clock is moved to
    ``return_clock`` (defaulting to the return instant) first."""
    world = setup_operating_departure(api, clock=clock, checkin_clock=checkin_clock,
                                      guest=guest, booking=booking, **world_kwargs)
    set_clock(api, return_clock or actual_return_utc)
    world.departure = complete_departure(api, world.departure["id"], actual_return_utc)
    world.booking = get_booking(api, world.booking["id"])
    return world


def setup_incident(api, clock=DEFAULT_CLOCK,
                   checkin_clock=INSTANTS["CHECKIN_CLOCK"], incident=None,
                   guest=None, booking=None, **world_kwargs) -> World:
    """A CHECKED_IN booking carrying one FILED incident — only bookings that
    reached the shore may carry one."""
    world = setup_checked_in_booking(api, clock=clock, checkin_clock=checkin_clock,
                                     guest=guest, booking=booking, **world_kwargs)
    world.incident = file_incident(api, world.booking["id"], **(incident or {}))
    return world


def setup_claim(api, clock=DEFAULT_CLOCK,
                checkin_clock=INSTANTS["CHECKIN_CLOCK"], incident=None,
                claim=None, guest=None, booking=None, **world_kwargs) -> World:
    """A SUBMITTED claim on a filed incident, opened by the first risk officer."""
    world = setup_incident(api, clock=clock, checkin_clock=checkin_clock,
                           incident=incident, guest=guest, booking=booking,
                           **world_kwargs)
    world.claim = open_claim(api, world.incident["id"], **(claim or {}))
    return world


def setup_claim_under_review(api, **kwargs) -> World:
    """A claim moved SUBMITTED → UNDER_OPERATOR_REVIEW, the state adjudication and
    dispute both start from."""
    world = setup_claim(api, **kwargs)
    world.claim = claim_action(api, world.claim["id"], "SEND_TO_OPERATOR",
                              headers=RISK_OFFICER)
    return world
