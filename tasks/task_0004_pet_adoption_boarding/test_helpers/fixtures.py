"""Composite setup helpers for Pet Adoption & Boarding tests.

Every fixture uses get_success_data() internally so setup failures produce
clear errors instead of confusing assertion failures in tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_shelter_payload,
    create_animal_payload,
    create_vaccination_record_payload,
    create_adopter_payload,
    create_adoption_application_payload,
    create_home_visit_payload,
    complete_home_visit_payload,
    create_boarding_reservation_payload,
    pay_invoice_payload,
    create_compliance_hold_payload,
    resolve_hold_payload,
    create_fee_schedule_payload,
    create_settlement_batch_payload,
    reject_application_payload,
    blacklist_adopter_payload,
    future_date,
    past_date,
    iso_now_offset,
)

_manager = TEST_USERS["manager_headers"]
_manager2 = TEST_USERS["manager_headers_2"]
_case_worker = TEST_USERS["case_worker_headers"]
_case_worker2 = TEST_USERS["case_worker_headers_2"]
_vet = TEST_USERS["vet_headers"]


# Vaccine sets per species (PRD 3.2 — adoption-time required set)
_ADOPTION_VACCINES = {
    "DOG": ["RABIES", "DHPP"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}
# Boarding adds BORDETELLA to DOG (PRD 3.2, 3.5)
_BOARDING_VACCINES = {
    "DOG": ["RABIES", "DHPP", "BORDETELLA"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1: State Progression — single entity brought to a target state
# ═══════════════════════════════════════════════════════════════════════════

def create_shelter(**overrides):
    """Create a new OPEN shelter. Returns the Shelter dict."""
    payload = create_shelter_payload(**overrides)
    return get_success_data(api_client.create_shelter(payload, _manager))


def create_suspended_shelter(**overrides):
    shelter = create_shelter(**overrides)
    return get_success_data(api_client.suspend_shelter(shelter["id"], _manager))


def create_animal_intake(shelter_id=None, **overrides):
    """Create an animal in INTAKE status. Returns animal."""
    if shelter_id is None:
        shelter = create_shelter()
        shelter_id = shelter["id"]
    payload = create_animal_payload(shelter_id, **overrides)
    return get_success_data(api_client.create_animal(payload, _case_worker))


def add_vaccinations_for_adoption(animal_id, species="DOG"):
    """Add all required vaccination records (adoption variant) for an animal."""
    vaccines = _ADOPTION_VACCINES.get(species, [])
    records = []
    for vaccine in vaccines:
        payload = create_vaccination_record_payload(
            animal_id, vaccine_name=vaccine, expiry_days_from_now=365
        )
        rec = get_success_data(api_client.create_vaccination_record(payload, _vet))
        records.append(rec)
    return records


def add_vaccinations_for_boarding(animal_id, species="DOG"):
    """Add all required vaccination records (boarding variant) for an animal."""
    vaccines = _BOARDING_VACCINES.get(species, [])
    records = []
    for vaccine in vaccines:
        payload = create_vaccination_record_payload(
            animal_id, vaccine_name=vaccine, expiry_days_from_now=365
        )
        rec = get_success_data(api_client.create_vaccination_record(payload, _vet))
        records.append(rec)
    return records


def create_available_animal(shelter_id=None, species="DOG", **overrides):
    """Create an animal with full vaccinations and make it AVAILABLE. Returns animal."""
    if shelter_id is None:
        shelter = create_shelter()
        shelter_id = shelter["id"]
    animal = create_animal_intake(shelter_id=shelter_id, species=species, **overrides)
    add_vaccinations_for_adoption(animal["id"], species=species)
    animal = get_success_data(api_client.make_animal_available(animal["id"], _case_worker))
    assert animal["status"] == "AVAILABLE", f"Expected AVAILABLE, got {animal['status']}"
    return animal


def create_boarding_ready_animal(shelter_id=None, species="DOG", **overrides):
    """Animal made AVAILABLE with boarding-compliance vaccines (DOG includes BORDETELLA)."""
    if shelter_id is None:
        shelter = create_shelter()
        shelter_id = shelter["id"]
    animal = create_animal_intake(shelter_id=shelter_id, species=species, **overrides)
    add_vaccinations_for_boarding(animal["id"], species=species)
    animal = get_success_data(api_client.make_animal_available(animal["id"], _case_worker))
    return animal


def create_adopter(shelter_id=None, **overrides):
    """Create an ACTIVE adopter."""
    if shelter_id is None:
        shelter = create_shelter()
        shelter_id = shelter["id"]
    payload = create_adopter_payload(shelter_id, **overrides)
    return get_success_data(api_client.create_adopter(payload, _case_worker))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2: Entity Hierarchy — parent + child setups
# ═══════════════════════════════════════════════════════════════════════════

def setup_shelter_with_available_animal(species="DOG", animal_overrides=None, **shelter_overrides):
    """Return (shelter, animal) where animal is AVAILABLE and vaccination-compliant."""
    shelter = create_shelter(**shelter_overrides)
    animal = create_available_animal(
        shelter_id=shelter["id"], species=species, **(animal_overrides or {})
    )
    return shelter, animal


def setup_shelter_with_adopter(adopter_overrides=None, **shelter_overrides):
    """Return (shelter, adopter)."""
    shelter = create_shelter(**shelter_overrides)
    adopter = create_adopter(shelter_id=shelter["id"], **(adopter_overrides or {}))
    return shelter, adopter


def setup_basic_adoption_scenario(species="DOG", weight_kg=15.0, animal_overrides=None, adopter_overrides=None):
    """Return (shelter, animal, adopter) ready for an adoption application.

    Animal is AVAILABLE; adopter is ACTIVE. species and weight_kg control
    whether the derived requires_home_visit is true.
    """
    shelter = create_shelter()
    ao = dict(animal_overrides or {})
    ao.setdefault("weight_kg", weight_kg)
    animal = create_available_animal(shelter_id=shelter["id"], species=species, **ao)
    adopter = create_adopter(shelter_id=shelter["id"], **(adopter_overrides or {}))
    return shelter, animal, adopter


def setup_fee_schedule(shelter_id, adoption_base_cents=10000,
                      boarding_daily_cents=2000, special_needs_cents=500,
                      loyalty_pct=10, species="ALL"):
    """Create a baseline FeeSchedule (ALL species) for the given shelter.

    Creates:
      - ADOPTION_BASE row for species (default ALL)
      - BOARDING_DAILY row for species (default ALL)
      - SPECIAL_NEEDS_SURCHARGE row for species (default ALL)
      - LOYALTY_DISCOUNT_PCT row for ALL
    """
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="ADOPTION_BASE",
                                     species=species, amount_cents=adoption_base_cents),
        _manager,
    ))
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="BOARDING_DAILY",
                                     species=species, amount_cents=boarding_daily_cents),
        _manager,
    ))
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="SPECIAL_NEEDS_SURCHARGE",
                                     species=species, amount_cents=special_needs_cents),
        _manager,
    ))
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="LOYALTY_DISCOUNT_PCT",
                                     species="ALL", amount_cents=loyalty_pct),
        _manager,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3: Full Lifecycle Shortcuts — adoption application pipeline
# ═══════════════════════════════════════════════════════════════════════════

def create_submitted_application(shelter=None, animal=None, adopter=None, species="DOG", weight_kg=15.0):
    """Create an adoption application in SUBMITTED state.

    Returns (shelter, animal, adopter, application).
    """
    if shelter is None or animal is None or adopter is None:
        shelter, animal, adopter = setup_basic_adoption_scenario(
            species=species, weight_kg=weight_kg
        )
    app = get_success_data(api_client.create_adoption_application(
        create_adoption_application_payload(animal["id"], adopter["id"]),
        _case_worker,
    ))
    return shelter, animal, adopter, app


def start_review(application_id, reviewer_headers=None):
    """Transition application SUBMITTED -> UNDER_REVIEW. Returns updated app."""
    headers = reviewer_headers or _case_worker
    return get_success_data(api_client.start_review_application(application_id, headers))


def create_application_under_review(species="CAT", weight_kg=5.0, reviewer_headers=None):
    """Application in UNDER_REVIEW state (by default requires_home_visit=False).

    CAT + weight<25 implies requires_home_visit=False by default.
    Returns (shelter, animal, adopter, app, reviewer_headers).
    """
    shelter, animal, adopter, app = create_submitted_application(
        species=species, weight_kg=weight_kg
    )
    reviewer = reviewer_headers or _case_worker
    app = start_review(app["id"], reviewer_headers=reviewer)
    return shelter, animal, adopter, app, reviewer


def create_reviewed_application(species="CAT", weight_kg=5.0, reviewer_headers=None):
    """Application in REVIEWED state (no home visit required).

    Returns (shelter, animal, adopter, app, reviewer_headers).
    """
    shelter, animal, adopter, app, reviewer = create_application_under_review(
        species=species, weight_kg=weight_kg, reviewer_headers=reviewer_headers
    )
    app = get_success_data(api_client.complete_review(app["id"], reviewer))
    assert app["status"] == "REVIEWED", f"Expected REVIEWED, got {app['status']}"
    return shelter, animal, adopter, app, reviewer


def create_approved_application(
    species="CAT", weight_kg=5.0,
    reviewer_headers=None, approver_headers=None,
    include_fee_schedule=True,
):
    """Application in APPROVED state with a FeeInvoice created.

    Returns (shelter, animal, adopter, app, invoice, reviewer, approver).
    """
    reviewer = reviewer_headers or _case_worker
    approver = approver_headers or _manager
    shelter, animal, adopter, app, _r = create_reviewed_application(
        species=species, weight_kg=weight_kg, reviewer_headers=reviewer
    )
    if include_fee_schedule:
        setup_fee_schedule(shelter["id"])
    app = get_success_data(api_client.approve_application(app["id"], approver))
    assert app["status"] == "APPROVED", f"Expected APPROVED, got {app['status']}"
    invoice_id = app["fee_invoice_id"]
    invoice = get_success_data(api_client.get_fee_invoice(invoice_id, approver))
    return shelter, animal, adopter, app, invoice, reviewer, approver


def pay_invoice_in_full(invoice_id, payer_headers=None):
    """Pay the full remaining balance on an invoice. Returns paid invoice."""
    payer = payer_headers or _case_worker
    invoice = get_success_data(api_client.get_fee_invoice(invoice_id, payer))
    balance = invoice["balance_due_cents"]
    if balance == 0:
        return invoice
    return get_success_data(
        api_client.pay_fee_invoice(invoice_id, pay_invoice_payload(balance), payer)
    )


def create_completed_application(species="CAT", weight_kg=5.0):
    """Full adoption life-cycle: application COMPLETED, animal ADOPTED.

    Returns (shelter, animal, adopter, app, invoice).
    """
    shelter, animal, adopter, app, invoice, reviewer, approver = \
        create_approved_application(species=species, weight_kg=weight_kg)
    pay_invoice_in_full(invoice["id"])
    app = get_success_data(api_client.complete_application(app["id"], reviewer))
    invoice = get_success_data(api_client.get_fee_invoice(invoice["id"], reviewer))
    return shelter, animal, adopter, app, invoice


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3b: Home-visit sub-workflow
# ═══════════════════════════════════════════════════════════════════════════

def create_application_home_visit_required(reviewer_headers=None):
    """Application in HOME_VISIT_REQUIRED state.

    Uses a DOG (species triggers requires_home_visit=true).
    Returns (shelter, animal, adopter, app, reviewer_headers).
    """
    reviewer = reviewer_headers or _case_worker
    shelter, animal, adopter, app = create_submitted_application(
        species="DOG", weight_kg=15.0
    )
    app = start_review(app["id"], reviewer_headers=reviewer)
    app = get_success_data(api_client.require_home_visit(app["id"], reviewer))
    assert app["status"] == "HOME_VISIT_REQUIRED", f"Expected HOME_VISIT_REQUIRED, got {app['status']}"
    return shelter, animal, adopter, app, reviewer


def create_home_visit_scheduled(reviewer_headers=None):
    """Schedule a HomeVisit; application in HOME_VISIT_SCHEDULED, visit in SCHEDULED.

    Returns (shelter, animal, adopter, app, home_visit, reviewer_headers).
    """
    reviewer = reviewer_headers or _case_worker
    shelter, animal, adopter, app, _r = create_application_home_visit_required(
        reviewer_headers=reviewer
    )
    payload = create_home_visit_payload(app["id"], scheduled_days_from_now=3)
    hv = get_success_data(api_client.create_home_visit(payload, reviewer))
    app = get_success_data(api_client.get_adoption_application(app["id"], reviewer))
    return shelter, animal, adopter, app, hv, reviewer


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3c: Boarding lifecycle shortcuts
# ═══════════════════════════════════════════════════════════════════════════

def create_boarding_requested(species="DOG", duration_days=3, check_in_days_from_now=0,
                               check_in_already_past=False, **overrides):
    """Create a REQUESTED boarding reservation.

    Returns (shelter, animal, reservation).
    """
    shelter = create_shelter(**overrides.pop("shelter_overrides", {}))
    setup_fee_schedule(shelter["id"])
    animal = create_boarding_ready_animal(shelter_id=shelter["id"], species=species)
    payload = create_boarding_reservation_payload(
        shelter["id"], animal["id"],
        check_in_days_from_now=check_in_days_from_now,
        duration_days=duration_days,
        check_in_already_past=check_in_already_past,
    )
    res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
    return shelter, animal, res


def confirm_reservation(reservation_id, manager_headers=None):
    """Confirm a REQUESTED boarding reservation."""
    mgr = manager_headers or _manager
    return get_success_data(api_client.confirm_boarding_reservation(reservation_id, mgr))


def create_boarding_confirmed(species="DOG", duration_days=3,
                               check_in_already_past=False, **overrides):
    """Boarding reservation in CONFIRMED state with invoice + match created.

    By default check_in_date is set to 'now + 1 minute' so the reservation is
    confirmable. Passing ``check_in_already_past=True`` instead uses
    today-midnight as check_in_date, letting subsequent /check-in calls
    succeed immediately (no real wall-clock wait needed).
    Returns (shelter, animal, reservation, invoice, match).
    """
    shelter, animal, res = create_boarding_requested(
        species=species, duration_days=duration_days, check_in_days_from_now=0,
        check_in_already_past=check_in_already_past,
        **overrides,
    )
    res = confirm_reservation(res["id"])
    assert res["status"] == "CONFIRMED", f"Expected CONFIRMED, got {res['status']}"
    invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
    match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
    return shelter, animal, res, invoice, match


def create_boarding_checked_in(species="DOG", duration_days=3):
    """Boarding reservation in CHECKED_IN state. animal is BOARDING.

    Returns (shelter, animal, reservation, invoice, match).
    """
    import time
    shelter, animal, res, invoice, match = create_boarding_confirmed(
        species=species, duration_days=duration_days
    )
    # Small wait so current_time > check_in_date (which was ~1 min in future).
    # We use iso_now_offset minutes=1 for check_in_date in the factory so we need to
    # ensure the reservation's check_in_date is in the past. To avoid actually waiting,
    # recreate with an immediately valid check_in_date.
    # Actually the factory above uses minutes=1 — so we need to wait ~62 seconds.
    # To keep tests fast, skip waiting and only use this fixture when waits are OK.
    time.sleep(65)
    res = get_success_data(api_client.check_in_boarding_reservation(res["id"], _case_worker))
    assert res["status"] == "CHECKED_IN"
    return shelter, animal, res, invoice, match


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4: Accumulation / Threshold targeting
# ═══════════════════════════════════════════════════════════════════════════

def fill_boarding_capacity_to(shelter_id, target_count):
    """Fill the shelter to exactly `target_count` CONFIRMED reservations.

    Each reservation gets its own boarding-ready animal. Useful for capacity tests.
    Returns list of (animal, reservation) tuples.
    """
    out = []
    for _ in range(target_count):
        animal = create_boarding_ready_animal(shelter_id=shelter_id, species="DOG")
        payload = create_boarding_reservation_payload(
            shelter_id, animal["id"], check_in_days_from_now=1, duration_days=2
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        assert res["status"] == "CONFIRMED"
        out.append((animal, res))
    return out


def create_active_hold(animal_id, severity="HIGH", hold_type="HEALTH_CONCERN",
                       reason="Test", creator_headers=None):
    """Create an ACTIVE ComplianceHold. Defaults to HIGH severity."""
    creator = creator_headers or _vet
    payload = create_compliance_hold_payload(
        animal_id, hold_type=hold_type, severity=severity, reason=reason
    )
    return get_success_data(api_client.create_compliance_hold(payload, creator))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5: Settlement / Terminal state
# ═══════════════════════════════════════════════════════════════════════════

def create_paid_adoption_invoice(species="CAT", weight_kg=5.0):
    """Create a PAID adoption FeeInvoice.

    Returns (shelter, animal, adopter, app, invoice).
    """
    shelter, animal, adopter, app, invoice, reviewer, approver = \
        create_approved_application(species=species, weight_kg=weight_kg)
    invoice = pay_invoice_in_full(invoice["id"])
    assert invoice["status"] == "PAID", f"Expected PAID, got {invoice['status']}"
    return shelter, animal, adopter, app, invoice


def create_settlement_batch_for_shelter(shelter_id, period_start_days_ago=30,
                                         period_end_days_from_now=1):
    """Create a DRAFT SettlementBatch for a shelter's paid invoices."""
    payload = create_settlement_batch_payload(
        shelter_id,
        period_start_days_ago=period_start_days_ago,
        period_end_days_from_now=period_end_days_from_now,
    )
    return get_success_data(api_client.create_settlement_batch(payload, _manager))
