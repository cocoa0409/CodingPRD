"""Composite setup helpers.

The interesting claims in the PRD require the system to be in a specific
posture (published event, approved unit, vetted participant, paid order,
contracted vendor, ...) that takes many API calls to reach. These helpers
encapsulate those multi-step preambles so tests focus on assertions.

All helpers use the lenient get_success_data() validator so a setup failure
surfaces as a clear "Setup failed" message rather than an assertion error.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_participant_headers,
    make_safety_officer_headers,
    make_spectator_headers,
    make_unit_commander_headers,
    make_vendor_headers,
    role_only_headers,
)

ORG = TEST_USERS["organizer_headers"]
AO = TEST_USERS["authenticity_officer_headers"]
SO1 = TEST_USERS["safety_officer_headers"]


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 1: event + posture progression
# ---------------------------------------------------------------------------

def create_event(**overrides) -> dict:
    """Create a canonical event in PLANNING. Returns the event."""
    resp = api_client.create_event(factories.create_event_payload(**overrides), ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: could not create event"
    return data


def get_event(event_id) -> dict:
    resp = api_client.get_event(event_id, ORG)
    data = get_success_data(resp)
    assert data, f"Setup failed: could not read event {event_id}"
    return data


def set_clock(to_iso8601: str) -> None:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ORG)
    assert get_success_data(resp) is not None, f"Setup failed: set_clock {to_iso8601}"


def add_signed_agreement(event_id, agreement_type, signer_name=None, **overrides) -> dict:
    """Create + sign an agreement, threading the OCC expected_event_version."""
    current = get_event(event_id)
    payload = factories.create_agreement_payload(
        agreement_type=agreement_type,
        expected_event_version=current["version"],
        **overrides,
    )
    if agreement_type == "INSURANCE_LIABILITY":
        payload.setdefault("coverage_amount_cents", 2000000)
        payload.setdefault("document_ref", "DOC-INS-1")
    resp = api_client.create_agreement(event_id, payload, ORG)
    agreement = get_success_data(resp)
    assert agreement, f"Setup failed: could not create {agreement_type} agreement"
    sign = factories.sign_agreement_payload(
        signer_name=signer_name or ("Insurer Irene" if agreement_type == "INSURANCE_LIABILITY" else "Landowner Lee")
    )
    resp = api_client.sign_agreement(agreement["id"], sign, ORG)
    signed = get_success_data(resp)
    assert signed, f"Setup failed: could not sign {agreement_type} agreement"
    return signed


def open_registration(event_id) -> dict:
    resp = api_client.open_registration(event_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: open-registration"
    return data


def publish_event(event_id) -> dict:
    resp = api_client.publish_event(event_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: publish"
    return data


def open_gates(event_id) -> dict:
    resp = api_client.open_gates(event_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: open-gates"
    return data


def complete_event(event_id) -> dict:
    resp = api_client.complete_event(event_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: complete"
    return data


def setup_registration_open_event(**overrides) -> dict:
    """Event in REGISTRATION_OPEN (no agreements required)."""
    event = create_event(**overrides)
    return open_registration(event["id"])


def setup_published_event(**overrides) -> dict:
    """Event in PUBLISHED with signed landowner + insurance agreements
    covering the event window and sufficient liability coverage."""
    event = create_event(**overrides)
    add_signed_agreement(event["id"], "LANDOWNER_USE")
    add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
    open_registration(event["id"])
    return publish_event(event["id"])


def setup_open_event(**overrides) -> dict:
    """Event in EVENT_OPEN (published, gates open, no alerts)."""
    event = setup_published_event(**overrides)
    return open_gates(event["id"])


def setup_completed_event(**overrides) -> dict:
    """Event walked all the way to COMPLETED."""
    event = setup_open_event(**overrides)
    return complete_event(event["id"])


# ---------------------------------------------------------------------------
# Tier 2: units and participants
# ---------------------------------------------------------------------------

def create_unit(event_id, **overrides) -> dict:
    """Register a unit as a UnitCommander (identity bootstrap at creation)."""
    resp = api_client.create_unit(
        factories.create_unit_payload(event_id, **overrides),
        make_unit_commander_headers(_uid("uc")),
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not create unit"
    return data


def vet_unit(unit_id, decision="APPROVE", notes="ok") -> dict:
    resp = api_client.vet_unit(unit_id, factories.vet_unit_payload(decision=decision, notes=notes), ORG)
    data = get_success_data(resp)
    assert data, f"Setup failed: vet unit {decision}"
    return data


def setup_approved_unit(event_id, **overrides) -> dict:
    unit = create_unit(event_id, **overrides)
    return vet_unit(unit["id"], "APPROVE")


def create_participant(event_id, unit_id=None, **overrides) -> dict:
    """Register a participant. When unit_id is given the call is made by the
    unit's commander (ownership-gated on the unit id); otherwise an
    EventOrganizer registers an independent reenactor."""
    if unit_id is not None:
        overrides.setdefault("unit_id", unit_id)
        headers = make_unit_commander_headers(unit_id)
    else:
        headers = ORG
    resp = api_client.create_participant(
        factories.create_participant_payload(event_id, **overrides), headers
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not create participant"
    return data


def submit_participant(participant_id, unit_id=None) -> dict:
    headers = make_unit_commander_headers(unit_id) if unit_id else make_participant_headers(participant_id)
    resp = api_client.submit_participant(participant_id, headers)
    data = get_success_data(resp)
    assert data, "Setup failed: submit participant"
    return data


def vet_participant(participant_id, decision="APPROVE", notes="ok") -> dict:
    resp = api_client.vet_participant(
        participant_id, factories.vet_participant_payload(decision=decision, notes=notes), AO
    )
    data = get_success_data(resp)
    assert data, f"Setup failed: vet participant {decision}"
    return data


def setup_vetted_participant(event_id, unit_id=None, **overrides) -> dict:
    """Participant walked DRAFT -> SUBMITTED -> VETTED."""
    participant = create_participant(event_id, unit_id=unit_id, **overrides)
    submit_participant(participant["id"], unit_id=unit_id)
    return vet_participant(participant["id"], "APPROVE")


def check_in_participant(participant_id, headers=None) -> dict:
    resp = api_client.check_in_participant(participant_id, headers or ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: participant check-in"
    return data


# ---------------------------------------------------------------------------
# Tier 3: equipment and inspections
# ---------------------------------------------------------------------------

def declare_equipment(participant_id, unit_id=None, **overrides) -> dict:
    headers = make_unit_commander_headers(unit_id) if unit_id else ORG
    resp = api_client.create_equipment_item(
        factories.create_equipment_item_payload(participant_id, **overrides), headers
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not declare equipment"
    return data


def schedule_inspection(item_id, officer="so-1", **overrides) -> dict:
    resp = api_client.schedule_inspection(
        item_id,
        factories.schedule_inspection_payload(**overrides),
        make_safety_officer_headers(officer),
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not schedule inspection"
    return data


def record_inspection(inspection_id, officer="so-1", **overrides) -> dict:
    resp = api_client.record_inspection(
        inspection_id,
        factories.record_inspection_payload(**overrides),
        make_safety_officer_headers(officer),
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not record inspection"
    return data


def setup_failed_equipment(event_id, unit_id=None, item_type="EDGED", officer="so-1"):
    """Participant with one equipment item whose inspection was RECORDED_FAIL.
    Returns (participant, item, inspection)."""
    participant = create_participant(event_id, unit_id=unit_id)
    item = declare_equipment(participant["id"], unit_id=unit_id, item_type=item_type)
    inspection = schedule_inspection(item["id"], officer=officer)
    record_inspection(inspection["id"], officer=officer,
                      outcome="FAIL", failure_reason="unsafe condition")
    return participant, item, inspection


# ---------------------------------------------------------------------------
# Tier 4: site areas, allocations, program slots
# ---------------------------------------------------------------------------

def create_site_area(event_id, area_kind="DEMO", capacity_units=4, area_name=None, **overrides) -> dict:
    names = {"DEMO": "Demo Field", "PARKING": "Lot B", "CAMP": "Camp North",
             "SUTLER": "Sutler Row", "SPECTATOR": "Spectator Hill"}
    payload = factories.create_site_area_payload(
        area_name=area_name or names.get(area_kind, "Area"),
        area_kind=area_kind,
        capacity_units=capacity_units,
        **overrides,
    )
    resp = api_client.create_site_area(event_id, payload, ORG)
    data = get_success_data(resp)
    assert data, f"Setup failed: could not create {area_kind} area"
    return data


def create_program_slot(event_id, site_area_id, **overrides) -> dict:
    resp = api_client.create_program_slot(
        event_id, factories.create_program_slot_payload(site_area_id, **overrides), ORG
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not create program slot"
    return data


def confirm_program_slot(slot_id) -> dict:
    resp = api_client.confirm_program_slot(slot_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: could not confirm program slot"
    return data


def create_allocation(area_id, **overrides) -> dict:
    resp = api_client.create_allocation(area_id, factories.create_allocation_payload(**overrides), ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: could not create allocation"
    return data


# ---------------------------------------------------------------------------
# Tier 5: ticket orders and parking
# ---------------------------------------------------------------------------

def create_ticket_order(event_id, buyer="spec-1", **overrides) -> dict:
    resp = api_client.create_ticket_order(
        event_id,
        factories.create_ticket_order_payload(**overrides),
        make_spectator_headers(buyer),
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not create ticket order"
    return data


def pay_ticket_order(order_id, buyer="spec-1", **overrides) -> dict:
    resp = api_client.pay_ticket_order(
        order_id, factories.pay_ticket_order_payload(**overrides), make_spectator_headers(buyer)
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not pay ticket order"
    return data


def setup_paid_order(event_id, buyer="spec-1", **order_overrides) -> dict:
    order = create_ticket_order(event_id, buyer=buyer, **order_overrides)
    return pay_ticket_order(order["id"], buyer=buyer)


def issue_parking_pass(order_id, buyer="spec-1", **overrides) -> dict:
    resp = api_client.issue_parking_pass(
        order_id, factories.issue_parking_pass_payload(**overrides), make_spectator_headers(buyer)
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not issue parking pass"
    return data


# ---------------------------------------------------------------------------
# Tier 6: vendors (sutler row)
# ---------------------------------------------------------------------------

def create_vendor(event_id, **overrides) -> dict:
    """Apply as a Vendor-role caller without X-User-ID so the created
    vendor's own id becomes the ownership self-anchor (PRD section 2.1)."""
    resp = api_client.create_vendor(
        event_id, factories.create_vendor_payload(**overrides), role_only_headers("Vendor")
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not create vendor"
    return data


def approve_vendor(vendor_id) -> dict:
    resp = api_client.approve_vendor(vendor_id, ORG)
    data = get_success_data(resp)
    assert data, "Setup failed: could not approve vendor"
    return data


def contract_vendor(vendor_id, **overrides) -> dict:
    """Contract as the vendor itself; X-User-ID equals the self-anchor id."""
    resp = api_client.contract_vendor(
        vendor_id, factories.contract_vendor_payload(**overrides),
        make_vendor_headers(vendor_id),
    )
    data = get_success_data(resp)
    assert data, "Setup failed: could not contract vendor"
    return data


def setup_approved_vendor(event_id, **overrides) -> dict:
    vendor = create_vendor(event_id, **overrides)
    return approve_vendor(vendor["id"])


def setup_contracted_vendor(event_id, payment_cents=48600, **overrides) -> dict:
    vendor = setup_approved_vendor(event_id, **overrides)
    return contract_vendor(vendor["id"], fee_payment_cents=payment_cents)


# ---------------------------------------------------------------------------
# Tier 7: contingency alerts
# ---------------------------------------------------------------------------

def raise_alert(event_id, severity="RED_FLAG", alert_kind="FIRE", message="alert", officer="so-1") -> dict:
    resp = api_client.create_contingency_alert(
        event_id,
        factories.create_contingency_alert_payload(
            alert_kind=alert_kind, severity=severity, message=message
        ),
        make_safety_officer_headers(officer),
    )
    data = get_success_data(resp)
    assert data, f"Setup failed: could not raise {severity} alert"
    return data
