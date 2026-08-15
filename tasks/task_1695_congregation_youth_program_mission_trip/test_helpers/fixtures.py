"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API (each
test runs against a freshly restarted server with an empty database). Setup
calls use the lenient get_success_data() validator so a setup failure reports
as "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_chaperone_assignment_payload,
    create_chaperone_payload,
    create_consent_form_payload,
    create_donation_payload,
    create_itinerary_item_payload,
    create_lodging_reservation_payload,
    create_participant_payload,
    create_payment_payload,
    create_program_payload,
    create_registration_payload,
    create_scholarship_application_payload,
    create_trip_payload,
)
from .test_users import (
    make_chaperone_headers,
    make_director_headers,
    make_guardian_headers,
    make_leader_headers,
    make_reviewer_headers,
    make_treasurer_headers,
)

REQUIRED_FORM_TYPES = ("PARENTAL_CONSENT", "MEDICAL_RELEASE",
                       "CONDUCT_AGREEMENT")


# ---------------------------------------------------------------------------
# Tier 1: single creates and small transitions
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a program (starts OPEN). Returns the Program."""
    resp = api_client.create_program(create_program_payload(**overrides),
                                     make_director_headers())
    return get_success_data(resp)


def create_trip(program_id, **overrides):
    """Create a trip in DRAFT. Returns the Trip."""
    resp = api_client.create_trip(create_trip_payload(program_id, **overrides),
                                  make_director_headers())
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock (runs the delinquency and expiry sweeps)."""
    resp = api_client.set_clock(to_iso8601, make_director_headers())
    get_success_data(resp)


def open_trip_registration(trip_id):
    """DRAFT -> REGISTRATION_OPEN. Returns the updated Trip."""
    resp = api_client.open_registration(trip_id, make_director_headers())
    return get_success_data(resp)


def create_participant(program_id, guardian_user_id="guardian-1", **overrides):
    """Create a participant owned by the given guardian handle."""
    resp = api_client.create_participant(
        create_participant_payload(program_id, **overrides),
        make_guardian_headers(guardian_user_id))
    return get_success_data(resp)


def create_registration(trip_id, participant_id, guardian_user_id="guardian-1",
                        **overrides):
    """Create a registration (DRAFT / PENDING_DEPOSIT). Returns the Registration."""
    resp = api_client.create_registration(
        create_registration_payload(trip_id, participant_id, **overrides),
        make_guardian_headers(guardian_user_id))
    return get_success_data(resp)


def add_consent_form(registration_id, form_type, guardian_user_id="guardian-1",
                     **overrides):
    """Submit one consent form (starts SUBMITTED). Returns the ConsentForm."""
    resp = api_client.create_consent_form(
        registration_id, create_consent_form_payload(form_type, **overrides),
        make_guardian_headers(guardian_user_id))
    return get_success_data(resp)


def review_consent_form(form_id, decision, reason=None, reviewer="director-1"):
    """VERIFY or REJECT a SUBMITTED form as a non-guardian director."""
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    resp = api_client.review_consent_form(form_id, payload,
                                          make_director_headers(reviewer))
    return get_success_data(resp)


def submit_registration(registration_id, guardian_user_id="guardian-1"):
    """DRAFT -> SUBMITTED by the owning guardian."""
    resp = api_client.submit_registration(
        registration_id, make_guardian_headers(guardian_user_id))
    return get_success_data(resp)


def review_registration(registration_id, decision, reason=None,
                        reviewer="director-1"):
    """APPROVE or REJECT a SUBMITTED registration as a non-guardian director."""
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    resp = api_client.review_registration(registration_id, payload,
                                          make_director_headers(reviewer))
    return get_success_data(resp)


def post_payment(registration_id, amount_cents, method="CASH",
                 user_id="treasurer-1"):
    """Post a payment as the treasurer. Returns the Payment."""
    resp = api_client.create_payment(
        registration_id,
        create_payment_payload(amount_cents=amount_cents, method=method),
        make_treasurer_headers(user_id))
    return get_success_data(resp)


def get_registration(registration_id):
    resp = api_client.get_registration(registration_id,
                                       make_director_headers())
    return get_success_data(resp)


def get_trip(trip_id):
    resp = api_client.get_trip(trip_id, make_director_headers())
    return get_success_data(resp)


def get_program(program_id):
    resp = api_client.get_program(program_id, make_director_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — program/trip open, participants, registrations
# ---------------------------------------------------------------------------

def setup_program_with_open_trip(program_overrides=None, **trip_overrides):
    """Program + trip opened for registration. Returns (program, trip)."""
    program = create_program(**(program_overrides or {}))
    trip = create_trip(program["id"], **trip_overrides)
    trip = open_trip_registration(trip["id"])
    return program, trip


def add_three_required_forms(registration_id, guardian_user_id="guardian-1",
                             verify=True):
    """Submit the three required form types; optionally VERIFY each.

    Returns dict {form_type: ConsentForm}.
    """
    forms = {}
    for form_type in REQUIRED_FORM_TYPES:
        form = add_consent_form(registration_id, form_type, guardian_user_id)
        if verify:
            form = review_consent_form(form["id"], "VERIFY")
        forms[form_type] = form
    return forms


def create_submitted_registration(trip_id, guardian_user_id="guardian-1",
                                  participant_overrides=None,
                                  registration_overrides=None):
    """Participant + registration + three VERIFIED required forms + SUBMITTED.

    Returns (participant, registration, forms).
    """
    trip = get_trip(trip_id)
    participant = create_participant(
        trip["program_id"], guardian_user_id, **(participant_overrides or {}))
    registration = create_registration(
        trip_id, participant["id"], guardian_user_id,
        **(registration_overrides or {}))
    forms = add_three_required_forms(registration["id"], guardian_user_id,
                                     verify=True)
    registration = submit_registration(registration["id"], guardian_user_id)
    return participant, registration, forms


def create_approved_registration(trip_id, guardian_user_id="guardian-1",
                                 participant_overrides=None,
                                 registration_overrides=None):
    """Participant + registration walked to APPROVED.

    Returns (participant, registration, forms).
    """
    participant, registration, forms = create_submitted_registration(
        trip_id, guardian_user_id, participant_overrides,
        registration_overrides)
    registration = review_registration(registration["id"], "APPROVE")
    return participant, registration, forms


def create_confirmed_registration(trip_id, guardian_user_id="guardian-1",
                                  payment_amount_cents=None,
                                  payment_method="CASH",
                                  participant_overrides=None,
                                  registration_overrides=None):
    """Participant + registration walked to CONFIRMED (deposit covered).

    Returns (participant, registration, forms, payment).
    """
    trip = get_trip(trip_id)
    if payment_amount_cents is None:
        payment_amount_cents = trip["deposit_cents"]
    participant, registration, forms = create_approved_registration(
        trip_id, guardian_user_id, participant_overrides,
        registration_overrides)
    payment = post_payment(registration["id"], payment_amount_cents,
                           method=payment_method)
    resp = api_client.confirm_registration(registration["id"],
                                           make_director_headers())
    registration = get_success_data(resp)
    return participant, registration, forms, payment


# ---------------------------------------------------------------------------
# Tier 2b: fundraising accounts and donations
# ---------------------------------------------------------------------------

def get_account_for_registration(registration_id, reader="treasurer-1"):
    """Return the registration's one-to-one fundraising account.

    The PRD specifies the resource, not the read shape; accept either a
    singleton list or a bare object and return the account dict.
    """
    resp = api_client.get_registration_fundraising_account(
        registration_id, make_treasurer_headers(reader))
    data = get_success_data(resp)
    if isinstance(data, list):
        assert len(data) == 1, (
            f"expected exactly one fundraising account, got {len(data)}")
        return data[0]
    assert isinstance(data, dict) and data.get("id"), (
        f"expected the one-to-one fundraising account, got {data!r}")
    return data


def add_donation(account_id, amount_cents, channel="CASH", donor_name="Donor D",
                 user_id="treasurer-1"):
    """Record a donation (RECEIVED) as the treasurer. Returns the Donation."""
    resp = api_client.create_donation(
        account_id,
        create_donation_payload(donor_name=donor_name,
                                amount_cents=amount_cents, channel=channel),
        make_treasurer_headers(user_id))
    return get_success_data(resp)


def get_account(account_id, reader="treasurer-1"):
    resp = api_client.get_fundraising_account(account_id,
                                              make_treasurer_headers(reader))
    return get_success_data(resp)


def apply_account_credit(account_id, user_id="treasurer-1"):
    resp = api_client.apply_credit(account_id, make_treasurer_headers(user_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2c: scholarships
# ---------------------------------------------------------------------------

def create_application(registration_id, requested_cents=100000,
                       guardian_user_id="guardian-1"):
    """Apply for aid (starts UNDER_REVIEW). Returns the application."""
    resp = api_client.create_scholarship_application(
        create_scholarship_application_payload(registration_id,
                                               requested_cents=requested_cents),
        make_guardian_headers(guardian_user_id))
    return get_success_data(resp)


def decide_application(application_id, decision, reason=None,
                       reviewer="reviewer-1"):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    resp = api_client.decide_scholarship_application(
        application_id, payload, make_reviewer_headers(reviewer))
    return get_success_data(resp)


def get_application(application_id, reader="reviewer-1"):
    resp = api_client.get_scholarship_application(
        application_id, make_reviewer_headers(reader))
    return get_success_data(resp)


def create_approved_application(registration_id, requested_cents=100000,
                                guardian_user_id="guardian-1",
                                reviewer="reviewer-1"):
    """Create + APPROVE an application. Returns the approved application."""
    app = create_application(registration_id, requested_cents,
                             guardian_user_id)
    return decide_application(app["id"], "APPROVE", reviewer=reviewer)


# ---------------------------------------------------------------------------
# Tier 2d: chaperones, background checks, assignments
# ---------------------------------------------------------------------------

def create_chaperone(program_id, **overrides):
    resp = api_client.create_chaperone(
        create_chaperone_payload(program_id, **overrides),
        make_director_headers())
    return get_success_data(resp)


def initiate_background_check(chaperone_id, vendor_reference=None):
    payload = {}
    if vendor_reference is not None:
        payload["vendor_reference"] = vendor_reference
    resp = api_client.create_background_check(chaperone_id,
                                              make_director_headers(),
                                              payload)
    return get_success_data(resp)


def advance_check(check_id, to_status, vendor_reference=None):
    payload = {"to_status": to_status}
    if vendor_reference is not None:
        payload["vendor_reference"] = vendor_reference
    resp = api_client.advance_background_check(check_id, payload,
                                               make_director_headers())
    return get_success_data(resp)


def create_cleared_chaperone(program_id, **chaperone_overrides):
    """Chaperone with a background check advanced to CLEARED.

    Returns (chaperone, check).
    """
    chaperone = create_chaperone(program_id, **chaperone_overrides)
    check = initiate_background_check(chaperone["id"])
    advance_check(check["id"], "SCREENING")
    check = advance_check(check["id"], "CLEARED")
    return chaperone, check


def propose_assignment(trip_id, chaperone_id, role="LEAD",
                       proposer="director-1"):
    resp = api_client.create_chaperone_assignment(
        create_chaperone_assignment_payload(trip_id, chaperone_id, role=role),
        make_director_headers(proposer))
    return get_success_data(resp)


def respond_assignment(assignment_id, chaperone_id, decision):
    """The assigned chaperone responds; X-User-ID is the Chaperone record id."""
    resp = api_client.respond_chaperone_assignment(
        assignment_id, {"decision": decision},
        make_chaperone_headers(chaperone_id))
    return get_success_data(resp)


def add_cleared_chaperone_to_trip(trip_id, program_id, role="LEAD",
                                  **chaperone_overrides):
    """Cleared chaperone proposed on the trip and ACCEPTed (CONFIRMED).

    Returns (chaperone, check, assignment).
    """
    chaperone, check = create_cleared_chaperone(program_id,
                                                **chaperone_overrides)
    assignment = propose_assignment(trip_id, chaperone["id"], role=role)
    assignment = respond_assignment(assignment["id"], chaperone["id"],
                                    "ACCEPT")
    return chaperone, check, assignment


# ---------------------------------------------------------------------------
# Tier 2e: itinerary and lodging
# ---------------------------------------------------------------------------

def add_itinerary_item(trip_id, leader="leader-1", **overrides):
    resp = api_client.create_itinerary_item(
        trip_id, create_itinerary_item_payload(**overrides),
        make_leader_headers(leader))
    return get_success_data(resp)


def add_lodging(trip_id, leader="leader-1", **overrides):
    resp = api_client.create_lodging_reservation(
        trip_id, create_lodging_reservation_payload(**overrides),
        make_leader_headers(leader))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_lock_ready_trip(num_confirmed=1, program_overrides=None,
                          trip_overrides=None, room_capacity=30,
                          lodging_cost_cents=0, insurance_tier="NONE",
                          chaperone_role="LEAD", payment_method="CASH",
                          payment_amount_cents=None,
                          with_chaperone=True, with_lodging=True):
    """Trip with everything the roster lock needs, still REGISTRATION_CLOSED.

    Builds: program, trip, one CONFIRMED cleared chaperone, one lodging
    reservation, `num_confirmed` CONFIRMED registrations (deposit paid), and
    closes registration.

    Returns dict with program, trip, chaperone, assignment, lodging, and a
    list of per-registration bundles (participant, registration, payment).
    """
    program = create_program(**(program_overrides or {}))
    trip_kwargs = {"destination_type": "IN_STATE",
                   "base_cost_cents": 80000, "deposit_cents": 50000,
                   "capacity_youth": 10, "chaperone_ratio": 5,
                   "start_date": "2027-06-15", "end_date": "2027-06-16",
                   "emergency_protocol_text": ""}
    trip_kwargs.update(trip_overrides or {})
    trip = create_trip(program["id"], **trip_kwargs)
    lodging = None
    if with_lodging:
        lodging = add_lodging(trip["id"], room_capacity=room_capacity,
                              cost_cents=lodging_cost_cents,
                              check_in_date=trip_kwargs["start_date"],
                              check_out_date=trip_kwargs["end_date"])
    open_trip_registration(trip["id"])
    chaperone, check, assignment = None, None, None
    if with_chaperone:
        chaperone, check, assignment = add_cleared_chaperone_to_trip(
            trip["id"], program["id"], role=chaperone_role)
    bundles = []
    for i in range(num_confirmed):
        guardian = f"guardian-{i + 1}"
        participant, registration, forms, payment = \
            create_confirmed_registration(
                trip["id"], guardian_user_id=guardian,
                payment_amount_cents=payment_amount_cents,
                payment_method=payment_method,
                participant_overrides={"family_key": f"fam-{i + 1}"},
                registration_overrides={"insurance_tier": insurance_tier})
        bundles.append({"participant": participant,
                        "registration": registration,
                        "forms": forms, "payment": payment})
    resp = api_client.close_registration(trip["id"], make_director_headers())
    trip = get_success_data(resp)
    return {"program": program, "trip": trip, "chaperone": chaperone,
            "check": check, "assignment": assignment, "lodging": lodging,
            "bundles": bundles}


def lock_trip_roster(trip_id):
    """REGISTRATION_CLOSED -> ROSTER_LOCKED. Returns the locked Trip."""
    resp = api_client.lock_roster(trip_id, make_director_headers())
    return get_success_data(resp)


def start_trip_in_progress(trip_id, clock_iso):
    """Advance the clock to the trip start instant, then start the trip."""
    set_clock(clock_iso)
    resp = api_client.start_trip(trip_id, make_director_headers())
    return get_success_data(resp)


def setup_in_progress_trip_with_confirmed(num_confirmed=1, **kwargs):
    """Lock-ready trip driven all the way to IN_PROGRESS.

    Returns the setup_lock_ready_trip dict plus the refreshed trip.
    """
    bundle = setup_lock_ready_trip(num_confirmed=num_confirmed, **kwargs)
    trip = lock_trip_roster(bundle["trip"]["id"])
    start_instant = f"{bundle['trip']['start_date']}T00:00:00Z"
    trip = start_trip_in_progress(trip["id"], start_instant)
    bundle["trip"] = trip
    return bundle
