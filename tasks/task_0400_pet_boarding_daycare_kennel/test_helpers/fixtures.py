"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
fixtures use get_success_data() (lenient) so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error deeper in.

Identity threading: the only entity-backed role is Owner. Operator setup runs as
FacilityManager (a strict superset of staff). When a fixture needs an
ownership-gated Owner call it threads the actual Owner.id through
make_owner_headers(owner_id).

A CAT reaches vaccination_status VALID with just RABIES + FVRCP, so the helpers
default to CAT to keep vaccine setup to two POSTs.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_owner_headers
from .factories import (
    create_facility_payload,
    create_owner_payload,
    create_pet_payload,
    create_vaccination_payload,
    review_payload,
    create_run_payload,
    create_reservation_payload,
    pay_deposit_payload,
    create_assignment_payload,
    create_addon_payload,
    create_package_payload,
    advance_clock_payload,
)

MGR = TEST_USERS["manager_headers"]


# ===========================================================================
# Tier 0: primitives
# ===========================================================================
def create_facility(**overrides):
    """Create a facility. Returns the facility dict (current_date == 2026-01-01)."""
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), MGR))


def create_owner(facility_id, **overrides):
    """Create an owner under a facility. Returns the owner dict."""
    return get_success_data(
        api_client.create_owner(facility_id, create_owner_payload(**overrides), MGR)
    )


def create_pet(owner_id, **overrides):
    """Create a pet under an owner. Returns the pet dict."""
    return get_success_data(
        api_client.create_pet(owner_id, create_pet_payload(**overrides), MGR)
    )


def create_run(facility_id, **overrides):
    """Create a run. Returns the run dict."""
    return get_success_data(
        api_client.create_run(facility_id, create_run_payload(**overrides), MGR)
    )


def create_package(owner_id, **overrides):
    """Create a package under an owner. Returns the package dict."""
    return get_success_data(
        api_client.create_package(owner_id, create_package_payload(**overrides), MGR)
    )


def advance_clock(facility_id, to_date):
    """Advance the business date. Returns the facility dict at the new date."""
    return get_success_data(
        api_client.advance_clock(facility_id, advance_clock_payload(to_date), MGR)
    )


def vaccinate_cat_valid(pet_id, expires_on="2027-06-01", administered_on="2025-06-01"):
    """Add RABIES + FVRCP so a CAT reaches vaccination_status VALID.

    Use a near-future expires_on to set up a later VALID->EXPIRED clock flip.
    """
    get_success_data(api_client.create_vaccination(
        pet_id, create_vaccination_payload(
            vaccine="RABIES", administered_on=administered_on, expires_on=expires_on), MGR))
    get_success_data(api_client.create_vaccination(
        pet_id, create_vaccination_payload(
            vaccine="FVRCP", administered_on=administered_on, expires_on=expires_on), MGR))


def review_pet(pet_id, decision):
    """Run a temperament review (CLEAR or FLAG). Returns the pet dict."""
    return get_success_data(api_client.review_pet(pet_id, review_payload(decision), MGR))


def create_assignment(reservation_id, run_id, expected_version):
    """Create a HELD assignment. Returns the assignment dict."""
    return get_success_data(api_client.create_assignment(
        reservation_id, create_assignment_payload(run_id, expected_version), MGR))


# ===========================================================================
# Tier 1: vaccinated + cleared CAT under a facility
# ===========================================================================
def setup_facility_owner_pet(
    deposit_policy="NONE",
    weight_kg=6,
    temperament="CALM",
    vaccinate=True,
    review="CLEAR",
    overbook_grace=None,
):
    """Create facility + owner + CAT pet; optionally vaccinate VALID and review.

    Returns (facility, owner, pet) with the pet dict re-fetched so its
    vaccination_status / temperament_clearance reflect the side effects.
    """
    fac_kwargs = {"deposit_policy": deposit_policy}
    if overbook_grace is not None:
        fac_kwargs["overbook_grace"] = overbook_grace
    facility = create_facility(**fac_kwargs)
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=weight_kg, temperament=temperament)
    if vaccinate:
        vaccinate_cat_valid(pet["id"])
    if review:
        review_pet(pet["id"], review)
    pet = get_success_data(api_client.get_pet(pet["id"], MGR))
    return facility, owner, pet


# ===========================================================================
# Tier 2: a reservation with a HELD assignment, ready (or nearly) to confirm
# ===========================================================================
def setup_held_reservation(
    service_type="OVERNIGHT",
    start_date="2026-02-01",
    end_date="2026-02-04",
    deposit_policy="NONE",
    weight_kg=6,
    temperament="CALM",
    vaccinate=True,
    review="CLEAR",
    run_kind=None,
    run_size_class="LARGE",
    daycare_capacity=5,
    package_id=None,
    reservation_overrides=None,
):
    """Facility + owner + pet + run + reservation + one HELD assignment.

    Picks the run kind from service_type by default. Returns a dict with keys:
    facility, owner, pet, run, reservation, assignment. The reservation dict is
    the freshly-created one (REQUESTED).
    """
    if run_kind is None:
        run_kind = "OVERNIGHT_SUITE" if service_type == "OVERNIGHT" else "DAYCARE_PEN"

    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy=deposit_policy, weight_kg=weight_kg, temperament=temperament,
        vaccinate=vaccinate, review=review,
    )
    run_kwargs = {"label": "Run-1", "kind": run_kind, "size_class": run_size_class}
    if run_kind == "DAYCARE_PEN":
        run_kwargs["daycare_capacity"] = daycare_capacity
    run = create_run(facility["id"], **run_kwargs)

    res_payload = {}
    if package_id is not None:
        res_payload["package_id"] = package_id
    if reservation_overrides:
        res_payload.update(reservation_overrides)
    reservation = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], service_type, start_date, end_date, **res_payload),
        MGR,
    ))
    assignment = create_assignment(reservation["id"], run["id"], reservation["version"])
    return {
        "facility": facility,
        "owner": owner,
        "pet": pet,
        "run": run,
        "reservation": reservation,
        "assignment": assignment,
    }


# ===========================================================================
# Tier 3: confirmed reservation (full preconditions paid + cascaded)
# ===========================================================================
def setup_confirmed_reservation(
    service_type="OVERNIGHT",
    start_date="2026-02-01",
    end_date="2026-02-04",
    deposit_policy="NONE",
    weight_kg=6,
    temperament="CALM",
    pay_cash=None,
    package_id=None,
    daycare_capacity=5,
    run_size_class="LARGE",
):
    """Walk a reservation all the way to CONFIRMED.

    If deposit_policy != NONE, pass pay_cash to cover the latched deposit before
    confirm. Returns the same dict shape as setup_held_reservation plus the
    confirmed reservation under key "reservation".
    """
    ctx = setup_held_reservation(
        service_type=service_type, start_date=start_date, end_date=end_date,
        deposit_policy=deposit_policy, weight_kg=weight_kg, temperament=temperament,
        package_id=package_id, daycare_capacity=daycare_capacity,
        run_size_class=run_size_class,
    )
    res_id = ctx["reservation"]["id"]
    if pay_cash is not None:
        get_success_data(api_client.pay_deposit(res_id, pay_deposit_payload(pay_cash), MGR))
    ctx["reservation"] = get_success_data(api_client.confirm_reservation(res_id, MGR))
    return ctx


# ===========================================================================
# Tier 4: package-funded daycare reservation, confirmed (credit consumed)
# ===========================================================================
def setup_package_funded_confirmed(
    tier="DAYCARE_10",
    cycle_start_date="2026-01-01",
    auto_renew=False,
    start_date="2026-01-10",
    daycare_capacity=5,
):
    """DAYCARE reservation funded by an ACTIVE package, confirmed (one credit used).

    Returns a dict with keys: facility, owner, pet, run, package, reservation,
    assignment. The package dict is re-fetched post-confirm so credits_remaining
    reflects the consumed credit.
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE")
    package = create_package(
        owner["id"], tier=tier, cycle_start_date=cycle_start_date, auto_renew=auto_renew)
    run = create_run(
        facility["id"], label="Pen-1", kind="DAYCARE_PEN",
        size_class="LARGE", daycare_capacity=daycare_capacity)
    reservation = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(
            pet["id"], "DAYCARE", start_date, start_date, package_id=package["id"]),
        MGR,
    ))
    assignment = create_assignment(reservation["id"], run["id"], reservation["version"])
    reservation = get_success_data(api_client.confirm_reservation(reservation["id"], MGR))
    package = get_success_data(api_client.get_package(package["id"], MGR))
    return {
        "facility": facility,
        "owner": owner,
        "pet": pet,
        "run": run,
        "package": package,
        "reservation": reservation,
        "assignment": assignment,
    }


# ===========================================================================
# Tier 5: an expired package (clock advanced past its 30-day cycle)
# ===========================================================================
def setup_expired_package(auto_renew=False, cycle_start_date="2026-01-01", to_date="2026-02-15"):
    """Buy an ACTIVE package, then advance the clock past its cycle to EXPIRE it.

    Returns (facility, owner, package) with the package re-fetched (EXPIRED).
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    package = create_package(
        owner["id"], cycle_start_date=cycle_start_date, auto_renew=auto_renew)
    advance_clock(facility["id"], to_date)
    package = get_success_data(api_client.get_package(package["id"], MGR))
    return facility, owner, package
