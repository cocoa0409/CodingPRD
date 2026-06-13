"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every individual test, so each fixture
builds its preconditions from scratch against an empty database, using only
PRD-declared endpoints. Fixtures use get_success_data() (lenient validator) so a
setup failure surfaces as a clear "Setup failed" rather than a confusing assertion.

Identity threading: when a fixture books an appointment as the Donor role, it uses
make_donor_headers(donor_id) so the ownership check sees the real donor id. Most
setup here books as IntakeNurse (also authorized), which is not ownership-gated.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_center_payload,
    advance_clock_payload,
    create_donor_payload,
    create_deferral_payload,
    create_slot_payload,
    create_appointment_payload,
    create_donation_payload,
    create_health_screening_payload,
    create_test_result_payload,
    create_blood_unit_payload,
    create_adverse_reaction_payload,
    create_inventory_bucket_payload,
)
from .test_users import TEST_USERS, make_donor_headers

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]
LAB = TEST_USERS["lab_technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]

DEFAULT_CLOCK = "2025-01-01T00:00:00.000Z"


# ─── Tier 1: Foundational state ───────────────────────────────────────────────
def create_center(clock=DEFAULT_CLOCK, **overrides):
    """Create a center and advance its clock to `clock` (None to leave at epoch).
    Returns the center dict (post-advance if a clock was given)."""
    center = get_success_data(api_client.create_center(create_center_payload(**overrides), ADMIN))
    if clock is not None:
        center = get_success_data(
            api_client.advance_clock(center["id"], advance_clock_payload(clock), ADMIN)
        )
    return center


def create_donor(center_id, **overrides):
    """Register a donor against the center. Returns the donor dict."""
    return get_success_data(
        api_client.create_donor(create_donor_payload(center_id, **overrides), NURSE)
    )


def create_slot(center_id, **overrides):
    """Create an appointment slot. Returns the slot dict (carries version)."""
    return get_success_data(
        api_client.create_slot(create_slot_payload(center_id, **overrides), ADMIN)
    )


def book_appointment(donor_id, slot, as_donor=False, **overrides):
    """Book the donor into `slot` using the slot's current version. Returns the
    appointment dict. When as_donor is True, books with make_donor_headers(donor_id)
    so the ownership check passes; otherwise books as IntakeNurse."""
    headers = make_donor_headers(donor_id) if as_donor else NURSE
    payload = create_appointment_payload(donor_id, slot["id"], slot["version"], **overrides)
    return get_success_data(api_client.create_appointment(payload, headers))


def record_screening(appointment_id, **overrides):
    """Record a (by default passing) health screening for the appointment."""
    return get_success_data(
        api_client.create_health_screening(
            create_health_screening_payload(appointment_id, **overrides), NURSE
        )
    )


# ─── Tier 2: Appointment lifecycle ────────────────────────────────────────────
def setup_checked_in_appointment(center_clock=DEFAULT_CLOCK, donation_type="WHOLE",
                                 slot_overrides=None, donor_overrides=None):
    """center -> donor -> slot(donation_type) -> book -> check-in.

    Returns (center, donor, slot, appointment) with the appointment CHECKED_IN.
    No screening is recorded yet, so this is the base for screening/collection tests.
    """
    slot_overrides = slot_overrides or {}
    donor_overrides = donor_overrides or {}
    center = create_center(clock=center_clock)
    donor = create_donor(center["id"], **donor_overrides)
    slot = create_slot(center["id"], donation_type=donation_type, **slot_overrides)
    appt = book_appointment(donor["id"], slot)
    appt = get_success_data(api_client.check_in_appointment(appt["id"], NURSE))
    return center, donor, slot, appt


def setup_scheduled_appointment(center_clock=DEFAULT_CLOCK, donation_type="WHOLE",
                                slot_overrides=None, donor_overrides=None):
    """center -> donor -> slot -> book (status SCHEDULED, no check-in).

    Returns (center, donor, slot, appointment).
    """
    slot_overrides = slot_overrides or {}
    donor_overrides = donor_overrides or {}
    center = create_center(clock=center_clock)
    donor = create_donor(center["id"], **donor_overrides)
    slot = create_slot(center["id"], donation_type=donation_type, **slot_overrides)
    appt = book_appointment(donor["id"], slot)
    return center, donor, slot, appt


# ─── Tier 3: Collection / donation lifecycle ──────────────────────────────────
def setup_collected_donation(center_clock=DEFAULT_CLOCK, donation_type="WHOLE",
                             volume_ml=450, screening_overrides=None,
                             slot_overrides=None, donor_overrides=None):
    """Full chain to a COLLECTED donation:
    center -> donor -> slot -> book -> check-in -> PASS screening -> record collection.

    Returns (center, donor, slot, appointment, donation).
    """
    screening_overrides = screening_overrides or {}
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock=center_clock, donation_type=donation_type,
        slot_overrides=slot_overrides, donor_overrides=donor_overrides,
    )
    record_screening(appt["id"], **screening_overrides)
    donation = get_success_data(
        api_client.create_donation(appt["id"], create_donation_payload(volume_ml=volume_ml), NURSE)
    )
    return center, donor, slot, appt, donation


def setup_labeled_unit(center_clock=DEFAULT_CLOCK, donation_type="WHOLE", volume_ml=450,
                       component="RBC", din="DIN-LBL-001", donor_overrides=None):
    """COLLECTED donation with one QUARANTINED labeled blood unit.

    Returns (center, donor, slot, appointment, donation, unit).
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock=center_clock, donation_type=donation_type, volume_ml=volume_ml,
        donor_overrides=donor_overrides,
    )
    unit = get_success_data(
        api_client.create_blood_unit(
            create_blood_unit_payload(donation["id"], component=component, din=din), LAB
        )
    )
    return center, donor, slot, appt, donation, unit


def setup_available_unit(center_clock=DEFAULT_CLOCK, component="RBC", din="DIN-AVL-001",
                         volume_ml=450, donor_overrides=None):
    """A released, AVAILABLE blood unit: label a unit, then record a NEGATIVE test
    so the donation goes RELEASABLE and the unit transitions to AVAILABLE.

    Returns (center, donor, slot, appointment, donation, unit) where unit is AVAILABLE.
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        center_clock=center_clock, donation_type="WHOLE", volume_ml=volume_ml,
        component=component, din=din, donor_overrides=donor_overrides,
    )
    get_success_data(
        api_client.create_test_result(donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB)
    )
    unit = get_success_data(api_client.get_blood_unit(unit["id"], INV))
    return center, donor, slot, appt, donation, unit


def setup_bucket_for_available_unit(blood_type="O_POS", component="RBC", din="DIN-BKT-001"):
    """An AVAILABLE unit (O_POS/RBC by default) plus an InventoryBucket initialized
    over that (blood_type, component) at the center.

    Returns (center, donor, unit, bucket).
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        component=component, din=din, donor_overrides={"blood_type": blood_type},
    )
    bucket = get_success_data(
        api_client.create_inventory_bucket(
            create_inventory_bucket_payload(center["id"], blood_type=blood_type, component=component), INV
        )
    )
    return center, donor, unit, bucket


# ─── Tier 4: Threshold / interval targeting ───────────────────────────────────
def setup_donor_with_prior_collection(donation_type="WHOLE", first_clock=DEFAULT_CLOCK,
                                      volume_ml=450, donor_overrides=None):
    """A donor who has completed one collection of `donation_type` at first_clock,
    with a fresh second slot booked but NOT yet checked in. Used for inter-donation
    interval boundary tests: advance the clock, then check in the second appointment.

    Returns (center, donor, first_donation, second_slot, second_appt).
    The caller advances the clock and creates the second slot's window as needed via
    second_slot_overrides.
    """
    donor_overrides = donor_overrides or {}
    center, donor, slot1, appt1, donation1 = setup_collected_donation(
        center_clock=first_clock, donation_type=donation_type, volume_ml=volume_ml,
        donor_overrides=donor_overrides,
    )
    return center, donor, donation1


def book_second_appointment_at(center, donor, donation_type, slot_window_start,
                               slot_window_end, advance_to):
    """Create a fresh slot for `donation_type` spanning the given window, book the donor
    into it, then advance the center clock to `advance_to`. Returns the SCHEDULED
    appointment. Booking happens before the clock advance so the slot exists; the
    second appointment is the donor's only open appointment.
    """
    slot2 = create_slot(
        center["id"], donation_type=donation_type,
        starts_at=slot_window_start, ends_at=slot_window_end, capacity=5,
    )
    appt2 = book_appointment(donor["id"], slot2)
    get_success_data(api_client.advance_clock(center["id"], advance_clock_payload(advance_to), ADMIN))
    return slot2, appt2


def record_prior_plasma_collection(center, donor, clock, slot_window_start, slot_window_end,
                                   volume_ml):
    """Advance the clock to `clock`, create a PLASMA slot, book + check in + PASS screening
    + record a PLASMA collection of `volume_ml`. Used to accumulate rolling-window plasma
    volume. Returns the donation dict.
    """
    get_success_data(api_client.advance_clock(center["id"], advance_clock_payload(clock), ADMIN))
    slot = create_slot(
        center["id"], donation_type="PLASMA",
        starts_at=slot_window_start, ends_at=slot_window_end, capacity=9,
    )
    appt = book_appointment(donor["id"], slot)
    appt = get_success_data(api_client.check_in_appointment(appt["id"], NURSE))
    record_screening(appt["id"], hemoglobin_g_dl=13.5, weight_kg=donor["weight_kg"])
    return get_success_data(
        api_client.create_donation(appt["id"], create_donation_payload(volume_ml=volume_ml), NURSE)
    )


def setup_plasma_appointment_ready_to_collect(center_clock, weight_kg, slot_window_start,
                                              slot_window_end):
    """A donor checked-in for a PLASMA collection with a PASS screening already recorded,
    ready for the collection POST under test. Returns (center, donor, appointment).
    """
    center = create_center(clock=center_clock)
    donor = create_donor(center["id"], weight_kg=weight_kg)
    slot = create_slot(
        center["id"], donation_type="PLASMA",
        starts_at=slot_window_start, ends_at=slot_window_end, capacity=9,
    )
    appt = book_appointment(donor["id"], slot)
    appt = get_success_data(api_client.check_in_appointment(appt["id"], NURSE))
    record_screening(appt["id"], hemoglobin_g_dl=13.5, weight_kg=weight_kg)
    return center, donor, appt


# ─── Tier 5: Deferral helpers ─────────────────────────────────────────────────
def raise_deferral(donor_id, **overrides):
    """Manually raise a deferral against the donor (as IntakeNurse). Returns deferral."""
    return get_success_data(
        api_client.create_deferral(create_deferral_payload(donor_id, **overrides), NURSE)
    )


def log_adverse_reaction(donation_id, **overrides):
    """Log an adverse reaction against a donation (as IntakeNurse). Returns the reaction."""
    return get_success_data(
        api_client.create_adverse_reaction(
            create_adverse_reaction_payload(donation_id, **overrides), NURSE
        )
    )
