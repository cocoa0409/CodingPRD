"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds its
preconditions from scratch (the server starts against an empty database before
each test). Setup calls use get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .test_users import TEST_USERS
from . import factories as f

INTAKE = TEST_USERS["intake_headers"]
CLASSIFICATION = TEST_USERS["classification_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
HEALTH = TEST_USERS["health_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / 2: base entity creation
# ---------------------------------------------------------------------------
def create_inmate(api, sex="MALE", **overrides):
    resp = api.create_inmate(f.create_inmate_payload(sex=sex, **overrides), INTAKE)
    return get_success_data(resp)


def create_booking(api, inmate_id, **overrides):
    resp = api.create_booking(f.create_booking_payload(inmate_id, **overrides), INTAKE)
    return get_success_data(resp)


def create_inmate_and_booking(api, sex="MALE", booking_overrides=None):
    """Register an inmate and open a BOOKED custody episode. Returns (inmate, booking)."""
    inmate = create_inmate(api, sex=sex)
    booking = create_booking(api, inmate["id"], **(booking_overrides or {}))
    return inmate, booking


def classify_initial(api, booking_id, expected_booking_version):
    resp = api.create_classification(
        booking_id,
        f.create_classification_payload("INITIAL", expected_booking_version),
        CLASSIFICATION,
    )
    return get_success_data(resp)


def create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR",
                              prior_bookings_count=0, sentence_days=100,
                              sentence_start_date="2026-05-01"):
    """Inmate + BOOKED booking + INITIAL classification -> CLASSIFIED.
    Returns (inmate, booking_after_classify) where booking is re-read post-classification."""
    inmate = create_inmate(api, sex=sex)
    booking = create_booking(
        api, inmate["id"], charge_severity=charge_severity,
        prior_bookings_count=prior_bookings_count, sentence_days=sentence_days,
        sentence_start_date=sentence_start_date,
    )
    classify_initial(api, booking["id"], booking["version"])
    booking = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    return inmate, booking


# ---------------------------------------------------------------------------
# Housing
# ---------------------------------------------------------------------------
def create_housing_unit(api, security_level="MIN", gender="MALE", capacity=4, name="Pod-Test"):
    resp = api.create_housing_unit(
        f.create_housing_unit_payload(name=name, security_level=security_level,
                                      gender=gender, capacity=capacity),
        CLASSIFICATION,
    )
    return get_success_data(resp)


def add_bed(api, unit_id, bed_label="B1"):
    resp = api.create_bed(unit_id, f.create_bed_payload(bed_label=bed_label), CLASSIFICATION)
    return get_success_data(resp)


def create_unit_with_beds(api, security_level="MIN", gender="MALE", capacity=4, bed_labels=("B1",)):
    """Returns (unit, [bed, ...])."""
    unit = create_housing_unit(api, security_level=security_level, gender=gender, capacity=capacity)
    beds = [add_bed(api, unit["id"], bed_label=label) for label in bed_labels]
    return unit, beds


def house_booking(api, booking_id, bed_id, start_datetime="2026-05-02T10:00:00Z", end_datetime=None):
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(booking_id, bed_id, start_datetime, end_datetime),
        CLASSIFICATION,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Commissary
# ---------------------------------------------------------------------------
def get_account_for_booking(api, booking_id):
    resp = api.get_commissary_account(booking_id, INTAKE)
    data = get_success_data(resp)
    # FK-reverse GET returns an array of 0-1 accounts.
    return data[0] if isinstance(data, list) else data


def setup_account_with_deposit(api, amount_cents=1000, sex="MALE"):
    """Inmate + BOOKED booking + auto account + deposit. Returns (booking, account_after_deposit)."""
    inmate = create_inmate(api, sex=sex)
    booking = create_booking(api, inmate["id"], sentence_days=40)
    account = get_account_for_booking(api, booking["id"])
    account = get_success_data(api.deposit(account["id"], f.deposit_payload(amount_cents), INTAKE))
    return booking, account


def place_order(api, account_id, lines, expected_version):
    resp = api.create_order(account_id, f.create_order_payload(lines, expected_version), INTAKE)
    return get_success_data(resp)


def three_taxable_lines():
    """Three taxable lines qty1 @105c -> per-line round 113 x3 + 25 fee = 364 (PRD §3.4)."""
    return [
        f.order_line("soap", 1, 105, True),
        f.order_line("pen", 1, 105, True),
        f.order_line("gum", 1, 105, True),
    ]


def setup_fulfilled_order(api, deposit_cents=1000):
    """Inmate + booking + account deposited + a FULFILLED 364c order.
    Returns (account_id, order)."""
    booking, account = setup_account_with_deposit(api, deposit_cents)
    order = place_order(api, account["id"], three_taxable_lines(), account["version"])
    order = get_success_data(api.fulfill_order(order["id"], INTAKE))
    return account["id"], order


# ---------------------------------------------------------------------------
# Visitation
# ---------------------------------------------------------------------------
def register_visitor(api, inmate_id, relationship="FAMILY", visitor_name="Test Visitor"):
    resp = api.register_visitor(
        inmate_id, f.register_visitor_payload(relationship=relationship, visitor_name=visitor_name),
        SCHEDULER,
    )
    return get_success_data(resp)


def setup_approved_visitor(api, sex="MALE"):
    """Inmate + booking + APPROVED visitor. Returns (inmate, booking, visitor)."""
    inmate = create_inmate(api, sex=sex)
    booking = create_booking(api, inmate["id"], sentence_days=40)
    visitor = register_visitor(api, inmate["id"], relationship="ATTORNEY")
    visitor = get_success_data(api.approve_visitor(visitor["id"], SCHEDULER))
    return inmate, booking, visitor


def request_visit(api, booking_id, visitor_id, start_datetime, end_datetime):
    resp = api.create_visit(
        f.create_visit_payload(booking_id, visitor_id, start_datetime, end_datetime), SCHEDULER
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------
def report_infraction(api, booking_id, infraction_type="CONTRABAND", good_time_forfeit_days=3,
                      reporter_user_id="officer-intake-1"):
    """Report an infraction under an explicit reporter X-User-ID (for SoD setups)."""
    headers = build_user_headers(reporter_user_id, "IntakeOfficer")
    resp = api.create_infraction(
        booking_id, f.create_infraction_payload(infraction_type, good_time_forfeit_days), headers
    )
    return get_success_data(resp)


def uphold_infraction(api, infraction_id, upholder_user_id="supervisor-1"):
    headers = build_user_headers(upholder_user_id, "Supervisor")
    resp = api.uphold_infraction(infraction_id, headers)
    return get_success_data(resp)


def setup_classified_with_reported_infraction(api, forfeit_days=6, sentence_days=100,
                                              charge_severity="MISDEMEANOR", prior_bookings_count=0):
    """Inmate + MIN classified booking + one REPORTED infraction (reporter officer-intake-1).
    Returns (booking, infraction)."""
    inmate = create_inmate(api, sex="MALE")
    booking = create_booking(api, inmate["id"], charge_severity=charge_severity,
                             prior_bookings_count=prior_bookings_count, sentence_days=sentence_days)
    classify_initial(api, booking["id"], booking["version"])
    infraction = report_infraction(api, booking["id"], "DISOBEDIENCE", forfeit_days,
                                   reporter_user_id="officer-intake-1")
    return booking, infraction


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
def add_property(api, booking_id, description="silver watch", category="ELECTRONICS"):
    resp = api.create_property(
        booking_id, f.create_property_payload(description, category), INTAKE
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Court
# ---------------------------------------------------------------------------
def schedule_court_event(api, booking_id, event_datetime="2026-06-01T09:00:00Z",
                         event_type="ARRAIGNMENT", transport_required=True):
    resp = api.create_court_event(
        booking_id,
        f.create_court_event_payload(event_datetime, event_type, transport_required=transport_required),
        SCHEDULER,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
def file_request(api, booking_id, request_type="MEDICAL", description="sick call"):
    resp = api.create_request(
        booking_id, f.create_request_payload(request_type, description), HEALTH
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601):
    resp = api.set_clock({"to_iso8601": to_iso8601}, SUPERVISOR)
    return get_success_data(resp)
