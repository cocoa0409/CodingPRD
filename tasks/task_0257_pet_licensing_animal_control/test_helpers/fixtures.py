"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
fixture builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test.

Identity threading: after creating an Owner, any ownership-gated call (submit,
attach-vaccination, renew, pay-penalty, mark-deceased, appeal) uses
make_owner_headers(owner["id"]) — never the shared TEST_USERS["owner_headers"]
constant — so the §2.1 ownership check sees a live Owner.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_pet_payload,
    create_vaccination_record_payload,
    create_kennel_payload,
    create_license_payload,
    create_dangerous_dog_case_payload,
    create_lost_found_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_owner_headers,
    make_clerk_headers,
    make_officer_headers,
)

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]

# A far-future RABIES expiry used whenever the proof must simply be valid.
FAR_FUTURE_EXPIRES = "2030-06-01T00:00:00Z"
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


# ───────────────────────── clock ─────────────────────────
def set_clock(to_iso8601=DEFAULT_CLOCK, headers=None):
    """Pin the logical clock to an absolute instant (PRD §2.10)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or CLERK))


def advance_clock(to_iso8601, headers=None):
    """Advance the clock and fire auto-transitions (PRD §2.10, §3.5)."""
    return get_success_data(api_client.advance_clock(to_iso8601, headers or CLERK))


# ─────────────────── primitive entity setup ───────────────────
def create_owner(**overrides):
    """Register an Owner (PRD §3.1). Returns the Owner dict."""
    return get_success_data(
        api_client.create_owner(create_owner_payload(**overrides), CLERK)
    )


def create_pet(owner_id, **overrides):
    """Create a Pet owned by owner_id (PRD §3.1)."""
    return get_success_data(
        api_client.create_pet(
            create_pet_payload(owner_id, **overrides), make_owner_headers(owner_id)
        )
    )


def create_rabies_record(owner_id, pet_id, expires_on=FAR_FUTURE_EXPIRES, **overrides):
    """Record an unexpired RABIES vaccination proof for a pet (PRD §3.1)."""
    return get_success_data(
        api_client.create_vaccination_record(
            create_vaccination_record_payload(
                pet_id, expires_on=expires_on, **overrides
            ),
            make_owner_headers(owner_id),
        )
    )


def create_kennel(owner_id, slot_capacity=5, **overrides):
    """Create a Kennel for an owner (PRD §3.2)."""
    return get_success_data(
        api_client.create_kennel(
            create_kennel_payload(owner_id, slot_capacity=slot_capacity, **overrides),
            make_owner_headers(owner_id),
        )
    )


def create_draft_license(owner_id, pet_id, **overrides):
    """Create a license application in DRAFT (PRD §3.2)."""
    return get_success_data(
        api_client.create_license(
            create_license_payload(owner_id, pet_id, **overrides),
            make_owner_headers(owner_id),
        )
    )


# ─────────────────── owner + pet + proof bundle ───────────────────
def setup_owner_pet(owner_overrides=None, pet_overrides=None, with_rabies=True):
    """Owner + one Pet (+ optional RABIES proof). Returns (owner, pet, vr_or_None).

    The RABIES proof is far-future-unexpired so the license workflow can complete.
    """
    owner = create_owner(**(owner_overrides or {}))
    pet = create_pet(owner["id"], **(pet_overrides or {}))
    vr = create_rabies_record(owner["id"], pet["id"]) if with_rabies else None
    return owner, pet, vr


# ─────────────────── license lifecycle walkers ───────────────────
def drive_license_to_under_review(owner_id, license_id, vaccination_record_id):
    """DRAFT→SUBMITTED→UNDER_REVIEW→NEEDS_VACCINATION_PROOF→UNDER_REVIEW with a
    RABIES proof attached (PRD §3.2–§3.3). Returns the license dict.

    The submit step is performed only when the license is still in DRAFT: a
    caller may have already submitted it (e.g. to assert the provisional fee),
    and re-submitting a non-DRAFT license is correctly ERR_INVALID_STATE per
    PRD §3.2, so this helper must not blindly re-submit.
    """
    oh = make_owner_headers(owner_id)
    current = get_success_data(api_client.get_license(license_id, CLERK))
    if current["status"] == "DRAFT":
        get_success_data(api_client.submit_license(license_id, oh))
    get_success_data(api_client.start_review_license(license_id, CLERK))
    get_success_data(api_client.request_vaccination_proof(license_id, CLERK))
    return get_success_data(
        api_client.attach_vaccination(
            license_id, {"vaccination_record_id": vaccination_record_id}, oh
        )
    )


def drive_license_to_approved(owner_id, license_id, vaccination_record_id):
    """...→APPROVED (PRD §3.3). Stamps final_fee_cents. Returns license dict."""
    drive_license_to_under_review(owner_id, license_id, vaccination_record_id)
    return get_success_data(api_client.approve_license(license_id, CLERK))


def drive_license_to_active(owner_id, license_id, vaccination_record_id):
    """...→ACTIVE via issue-tag (PRD §3.4). Returns the ACTIVE license dict."""
    drive_license_to_approved(owner_id, license_id, vaccination_record_id)
    return get_success_data(api_client.issue_tag(license_id, CLERK))


def setup_active_individual_license(
    owner=None, pet=None, vr=None, owner_overrides=None,
    pet_overrides=None, term_years=1,
):
    """Owner + pet + RABIES proof + an ACTIVE INDIVIDUAL license.

    Returns (owner, pet, vr, license). Any of owner/pet/vr may be supplied to
    reuse existing entities (e.g. a second license for the same pet).
    """
    if owner is None:
        owner = create_owner(**(owner_overrides or {}))
    if pet is None:
        pet = create_pet(owner["id"], **(pet_overrides or {}))
    if vr is None:
        vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=term_years
    )
    lic = drive_license_to_active(owner["id"], lic["id"], vr["id"])
    return owner, pet, vr, lic


def setup_approved_individual_license(
    owner_overrides=None, pet_overrides=None, term_years=1
):
    """Owner + pet + RABIES proof + an APPROVED (not yet issued) INDIVIDUAL license.

    Returns (owner, pet, vr, license).
    """
    owner = create_owner(**(owner_overrides or {}))
    pet = create_pet(owner["id"], **(pet_overrides or {}))
    vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=term_years
    )
    lic = drive_license_to_approved(owner["id"], lic["id"], vr["id"])
    return owner, pet, vr, lic


def setup_active_kennel_license(owner, kennel, vr=None, pet_overrides=None):
    """Add one ACTIVE KENNEL license (its own new pet + RABIES proof) to a kennel.

    Returns (pet, vr, license). Used to advance Kennel.occupied_slots one at a time.
    """
    pet = create_pet(owner["id"], **(pet_overrides or {}))
    if vr is None:
        vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="KENNEL", term_years=1,
        kennel_id=kennel["id"],
    )
    lic = drive_license_to_active(owner["id"], lic["id"], vr["id"])
    return pet, vr, lic


def setup_kennel_with_active_licenses(slot_capacity, occupied, owner_overrides=None):
    """Owner + Kennel(slot_capacity) carrying `occupied` ACTIVE KENNEL licenses.

    Returns (owner, kennel, [licenses]). Each active license consumes one slot, so
    the kennel's occupied_slots equals `occupied`.
    """
    owner = create_owner(**(owner_overrides or {}))
    kennel = create_kennel(owner["id"], slot_capacity=slot_capacity)
    licenses = []
    for i in range(occupied):
        _, _, lic = setup_active_kennel_license(
            owner, kennel, pet_overrides={"name": f"K{i + 1}", "is_altered": False}
        )
        licenses.append(lic)
    return owner, kennel, licenses


def setup_expired_individual_license(
    owner=None, pet=None, vr=None, term_years=1,
    issued_clock=DEFAULT_CLOCK, expiry_clock="2027-02-10T00:00:00Z",
    pet_overrides=None,
):
    """Owner + pet + an INDIVIDUAL license driven to ACTIVE at issued_clock then
    aged past the grace window to EXPIRED at expiry_clock (PRD §3.5).

    The default clocks (issued 2026-01-01 term 1yr → expires 2027-01-01,
    grace-end 2027-01-31; advanced to 2027-02-10 → days_late=10 → penalty 2000 on
    a 4000 final fee). Returns (owner, pet, vr, license_after_expiry).
    """
    if owner is None:
        owner = create_owner()
    if pet is None:
        pet = create_pet(owner["id"], **(pet_overrides or {"is_altered": False}))
    if vr is None:
        vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=term_years
    )
    drive_license_to_active(owner["id"], lic["id"], vr["id"])
    advance_clock(expiry_clock)
    lic = get_success_data(api_client.get_license(lic["id"], CLERK))
    return owner, pet, vr, lic


# ─────────────────── dangerous-dog setup ───────────────────
def setup_designated_case(owner_id, pet_id, severity="BITE"):
    """Open a dangerous-dog case for a pet and drive it to DESIGNATED (PRD §3.7).

    Returns the DESIGNATED case dict. Sets Pet.is_dangerous=true and cascades the
    surcharge onto the pet's ACTIVE/GRACE licenses.
    """
    case = get_success_data(
        api_client.create_dangerous_dog_case(
            create_dangerous_dog_case_payload(pet_id, severity=severity), OFFICER
        )
    )
    get_success_data(api_client.investigate_case(case["id"], OFFICER))
    return get_success_data(api_client.designate_case(case["id"], OFFICER))


def setup_appealed_case(owner_id, pet_id, severity="BITE"):
    """Drive a dangerous-dog case to DESIGNATED then APPEALED (PRD §3.7).

    The appeal is owner-initiated, so it uses make_owner_headers(owner_id).
    Returns the APPEALED case dict.
    """
    case = setup_designated_case(owner_id, pet_id, severity=severity)
    return get_success_data(
        api_client.appeal_case(case["id"], make_owner_headers(owner_id))
    )


# ─────────────────── lost/found setup ───────────────────
def create_report(report_type, species, **overrides):
    """File a lost/found report as the officer (PRD §3.8)."""
    return get_success_data(
        api_client.create_lost_found_report(
            create_lost_found_report_payload(report_type, species, **overrides), OFFICER
        )
    )


def setup_matched_pair(
    species="DOG", zip_seen="55555",
    lost_reported_at="2026-03-01T07:00:00Z",
    found_reported_at="2026-03-01T08:00:00Z",
):
    """A LOST and a FOUND report sharing species+zip, matched into a mutual pair
    (PRD §3.8). Returns (lost_report, found_report) both in MATCHED.
    """
    found = create_report(
        "FOUND", species, zip_seen=zip_seen, reported_at=found_reported_at
    )
    lost = create_report(
        "LOST", species, zip_seen=zip_seen, reported_at=lost_reported_at
    )
    get_success_data(api_client.match_report(lost["id"], OFFICER))
    found = get_success_data(api_client.get_lost_found_report(found["id"], OFFICER))
    lost = get_success_data(api_client.get_lost_found_report(lost["id"], OFFICER))
    return lost, found
