"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so a broken setup step raises a clear
"Setup step failed" error rather than a confusing downstream assertion failure.

Identity threading: every HousingNavigator-owned call (referral create/accept/decline/enroll)
uses make_navigator_headers(navigator_id) so X-User-ID equals the acting navigator's id,
as the PRD's ownership model requires.

Every helper builds its preconditions from scratch — the server database is empty at the
start of each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_assessment_payload, create_consent_payload,
    create_screening_payload, create_shelter_payload, create_bed_payload,
    create_bed_reservation_payload, create_waitlist_entry_payload,
    create_prioritization_entry_payload, create_housing_navigator_payload,
    create_referral_payload, create_exit_record_payload,
)
from .test_users import TEST_USERS, make_navigator_headers

INTAKE = TEST_USERS["intake_headers"]
SHELTER = TEST_USERS["shelter_manager_headers"]
NAV = TEST_USERS["navigator_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


# ─── Base primitives ──────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock. Returns the response body's data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def new_client(full_name="Test Client", dob="1990-01-01", **overrides) -> dict:
    return get_success_data(
        api_client.create_client(create_client_payload(full_name, dob, **overrides), INTAKE))


def new_assessment(client_id, self_report_points=9, **overrides) -> dict:
    return get_success_data(api_client.create_assessment(
        create_assessment_payload(client_id, self_report_points, **overrides), INTAKE))


def complete_assessment(assessment_id) -> dict:
    return get_success_data(api_client.complete_assessment(assessment_id, INTAKE))


def new_active_client(self_report_points=9, **client_overrides):
    """Client + DRAFT assessment + complete -> client is ACTIVE with a vulnerability_score.
    Returns (client_after_completion, assessment)."""
    client = new_client(**client_overrides)
    asm = new_assessment(client["id"], self_report_points)
    complete_assessment(asm["id"])
    client_after = get_success_data(api_client.get_client(client["id"], INTAKE))
    return client_after, asm


def new_consent(client_id, **overrides) -> dict:
    """PENDING consent."""
    return get_success_data(
        api_client.create_consent(create_consent_payload(client_id, **overrides), INTAKE))


def new_active_consent(client_id, **overrides) -> dict:
    """PENDING consent then activate -> ACTIVE consent."""
    consent = new_consent(client_id, **overrides)
    return get_success_data(api_client.activate_consent(consent["id"], INTAKE))


def new_screening(client_id, has_safe_alternative=False, **overrides) -> dict:
    return get_success_data(api_client.create_screening(
        create_screening_payload(client_id, has_safe_alternative, **overrides), INTAKE))


def new_shelter(name="Test Shelter", project_type="ES") -> dict:
    return get_success_data(
        api_client.create_shelter(create_shelter_payload(name, project_type), SHELTER))


def add_bed(shelter_id, label="B1") -> dict:
    return get_success_data(
        api_client.create_bed(create_bed_payload(shelter_id, label), SHELTER))


def shelter_version(shelter_id) -> int:
    return get_success_data(api_client.get_shelter(shelter_id, SHELTER))["version"]


def get_shelter(shelter_id) -> dict:
    return get_success_data(api_client.get_shelter(shelter_id, SHELTER))


def new_shelter_with_beds(labels=("B1",), name="Test Shelter", project_type="ES"):
    """Shelter plus one bed per label. Returns (shelter, [beds])."""
    shelter = new_shelter(name, project_type)
    beds = [add_bed(shelter["id"], label) for label in labels]
    return shelter, beds


def new_reservation(client_id, shelter_id, entry_date, expected_exit_date,
                    expected_shelter_version=None) -> dict:
    """Create a RESERVED bed reservation. Fetches the current shelter version when one
    is not supplied so the OCC precondition passes."""
    if expected_shelter_version is None:
        expected_shelter_version = shelter_version(shelter_id)
    return get_success_data(api_client.create_bed_reservation(
        create_bed_reservation_payload(client_id, shelter_id, entry_date,
                                       expected_exit_date, expected_shelter_version), SHELTER))


def new_waitlist_entry(shelter_id, client_id, entry_date, expected_exit_date) -> dict:
    return get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(shelter_id, client_id, entry_date, expected_exit_date),
        SHELTER))


def new_pool_entry(client_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.create_prioritization_entry(
        create_prioritization_entry_payload(client_id), headers))


def new_navigator(max_caseload=2, name="Test Navigator") -> dict:
    return get_success_data(api_client.create_housing_navigator(
        create_housing_navigator_payload(name, max_caseload), ADMIN))


def new_referral(client_id, prioritization_entry_id, navigator_id,
                 psh_project_name="Maple PSH") -> dict:
    return get_success_data(api_client.create_referral(
        create_referral_payload(client_id, prioritization_entry_id, navigator_id,
                                psh_project_name),
        make_navigator_headers(navigator_id)))


def new_exit_record(client_id, destination, reservation_id=None, referral_id=None,
                    headers=SHELTER) -> dict:
    return get_success_data(api_client.create_exit_record(
        create_exit_record_payload(client_id, destination, reservation_id, referral_id),
        headers))


# ─── Tier: consent-gated shelter stay ─────────────────────────────────────────
def setup_reserved_client(entry_date="2026-03-05", expected_exit_date="2026-03-20",
                          shelter_name="Stay ES", active_consent=True,
                          self_report_points=None):
    """Client (optionally with an ACTIVE consent) holding one RESERVED reservation in a
    single-bed shelter. Returns dict(client, consent, shelter, bed, reservation)."""
    client = new_client()
    consent = new_active_consent(client["id"]) if active_consent else new_consent(client["id"])
    if self_report_points is not None:
        asm = new_assessment(client["id"], self_report_points)
        complete_assessment(asm["id"])
    shelter, beds = new_shelter_with_beds(("B1",), name=shelter_name)
    reservation = new_reservation(client["id"], shelter["id"], entry_date, expected_exit_date)
    return {"client": client, "consent": consent, "shelter": shelter,
            "bed": beds[0], "reservation": reservation}


def setup_checked_in_stay(entry_date="2026-03-05", expected_exit_date="2026-03-20",
                          shelter_name="Stay ES"):
    """Client with ACTIVE consent, CHECKED_IN in a single-bed shelter.
    Returns dict(client, consent, shelter, bed, reservation)."""
    ctx = setup_reserved_client(entry_date, expected_exit_date, shelter_name, active_consent=True)
    ctx["reservation"] = get_success_data(
        api_client.check_in_reservation(ctx["reservation"]["id"], SHELTER))
    return ctx


def setup_completed_shelter_stay(entry_date="2026-03-05", checkout_iso="2026-03-10T00:00:00Z",
                                 start_iso="2026-03-05T00:00:00Z",
                                 expected_exit_date="2026-03-20", shelter_name="Stay ES"):
    """Full shelter stay: set clock, check in, advance clock, check out. The reservation is
    CHECKED_OUT with exit_date at the checkout clock. Returns dict(client, shelter, bed,
    reservation)."""
    set_clock(start_iso)
    ctx = setup_checked_in_stay(entry_date, expected_exit_date, shelter_name)
    set_clock(checkout_iso)
    ctx["reservation"] = get_success_data(
        api_client.check_out_reservation(ctx["reservation"]["id"], SHELTER))
    return ctx


# ─── Tier: prioritization pool + referrals ────────────────────────────────────
def setup_active_pooled_client(self_report_points=9, pool_headers=ADMIN, **client_overrides):
    """ACTIVE client with completed assessment + ACTIVE consent + ACTIVE pool entry.
    Returns dict(client, assessment, consent, pool_entry)."""
    client, asm = new_active_client(self_report_points, **client_overrides)
    consent = new_active_consent(client["id"])
    pe = new_pool_entry(client["id"], pool_headers)
    return {"client": client, "assessment": asm, "consent": consent, "pool_entry": pe}


def setup_pending_referral(self_report_points=9, max_caseload=2, **client_overrides):
    """ACTIVE pooled client + navigator + a PENDING referral (pool entry MATCHED).
    Returns dict(client, pool_entry, navigator, referral)."""
    ctx = setup_active_pooled_client(self_report_points, **client_overrides)
    nav = new_navigator(max_caseload)
    ref = new_referral(ctx["client"]["id"], ctx["pool_entry"]["id"], nav["id"])
    return {"client": ctx["client"], "pool_entry": ctx["pool_entry"],
            "navigator": nav, "referral": ref, "consent": ctx["consent"],
            "assessment": ctx["assessment"]}


def setup_accepted_referral(self_report_points=9, max_caseload=2, **client_overrides):
    """A referral driven through to ACCEPTED (navigator caseload = 1).
    Returns dict(client, pool_entry, navigator, referral)."""
    ctx = setup_pending_referral(self_report_points, max_caseload, **client_overrides)
    ctx["referral"] = get_success_data(api_client.accept_referral(
        ctx["referral"]["id"], make_navigator_headers(ctx["navigator"]["id"])))
    return ctx
