"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test starts against an empty database). Uses get_success_data()
so setup failures surface as clear "Setup step failed" errors.

Identity threading (PRD §2.1): CAQH attestation is ownership-gated, so after
creating a Provider the attest call always uses make_provider_headers with the
actual provider id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_claim_payload,
    create_delegation_agreement_payload,
    create_enrollment_application_payload,
    create_payer_payload,
    create_practice_group_payload,
    create_provider_payload,
    create_roster_file_payload,
    roster_add_line,
)
from .test_users import (
    TEST_USERS,
    make_enrollment_specialist_headers,
    make_provider_headers,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]


# ─── Tier 0: single-resource creation ────────────────

def create_practice_group(**overrides) -> dict:
    res = api_client.create_practice_group(create_practice_group_payload(**overrides), OFFICER)
    return get_success_data(res)


def create_provider(group_id: str, **overrides) -> dict:
    """Create a provider in the group (EnrollmentSpecialist). CAQH profile is
    auto-created alongside (PRD §3.1)."""
    res = api_client.create_provider(group_id, create_provider_payload(**overrides), SPECIALIST)
    return get_success_data(res)


def get_caqh_profile(provider_id: str) -> dict:
    """Read the provider's single CAQH profile (array of length 1, PRD §3.1)."""
    res = api_client.get_provider_caqh_profile(provider_id, SPECIALIST)
    profiles = get_success_data(res)
    assert isinstance(profiles, list) and len(profiles) == 1, (
        f"Expected exactly one CAQH profile, got {profiles!r}"
    )
    return profiles[0]


def attest_provider(provider_id: str) -> dict:
    """Attest the provider's CAQH profile as the provider themselves."""
    profile = get_caqh_profile(provider_id)
    res = api_client.attest_caqh_profile(profile["id"], make_provider_headers(provider_id))
    return get_success_data(res)


def create_attested_provider(group_id: str, **overrides) -> tuple:
    """Create a provider and attest their CAQH profile. Returns (provider, profile)."""
    provider = create_provider(group_id, **overrides)
    profile = attest_provider(provider["id"])
    return provider, profile


def create_payer_config(**overrides) -> dict:
    res = api_client.create_payer(create_payer_payload(**overrides), OFFICER)
    return get_success_data(res)


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (ComplianceOfficer). Returns {current_utc}."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER)
    return get_success_data(res)


# ─── Tier 1: group + provider + payer scenarios ──────

def setup_group_provider_payer(attest: bool = True, payer_overrides: dict = None,
                               provider_overrides: dict = None) -> tuple:
    """Practice group + one provider (optionally attested) + one payer.
    Returns (group, provider, caqh_profile_or_None, payer)."""
    group = create_practice_group()
    provider = create_provider(group["id"], **(provider_overrides or {}))
    profile = attest_provider(provider["id"]) if attest else get_caqh_profile(provider["id"])
    payer = create_payer_config(**(payer_overrides or {}))
    return group, provider, profile, payer


# ─── Tier 2: application channel lifecycle ───────────

def create_draft_application(provider_id: str, payer_id: str, **overrides) -> dict:
    res = api_client.create_enrollment_application(
        create_enrollment_application_payload(provider_id, payer_id, **overrides),
        SPECIALIST,
    )
    return get_success_data(res)


def create_submitted_application(provider_id: str, payer_id: str, **overrides) -> dict:
    """DRAFT -> SUBMITTED. Returns the submitted application."""
    app = create_draft_application(provider_id, payer_id, **overrides)
    res = api_client.submit_application(app["id"], SPECIALIST)
    return get_success_data(res)


def find_record(provider_id: str = None, payer_id: str = None,
                source_application_id: str = None, status: str = None) -> dict:
    """Fetch the single enrollment record matching the given filters."""
    params = {}
    if provider_id is not None:
        params["provider_id"] = provider_id
    if payer_id is not None:
        params["payer_id"] = payer_id
    if source_application_id is not None:
        params["source_application_id"] = source_application_id
    if status is not None:
        params["status"] = status
    records = get_success_data(api_client.list_enrollment_records(SPECIALIST, params=params))
    assert isinstance(records, list) and len(records) == 1, (
        f"Expected exactly one enrollment record for {params}, got {records!r}"
    )
    return records[0]


def create_approved_application(provider_id: str, payer_id: str,
                                approve_at: str = None, **overrides) -> tuple:
    """Create -> submit -> (optionally advance clock) -> approve.
    Returns (approved_application, created_enrollment_record)."""
    app = create_submitted_application(provider_id, payer_id, **overrides)
    if approve_at is not None:
        set_clock(approve_at)
    approved = get_success_data(api_client.approve_application(app["id"], PAYER_REP))
    record = find_record(source_application_id=app["id"])
    return approved, record


# ─── Tier 3: delegated credentialing channel ─────────

def create_active_agreement(group_id: str, payer_id: str, **overrides) -> dict:
    """Create a delegation agreement (born ACTIVE). Callers needing the OCC
    version should read agreement["version"] from the returned dict, or re-GET
    the agreement after any intervening roster submission."""
    res = api_client.create_delegation_agreement(
        create_delegation_agreement_payload(group_id, payer_id, **overrides),
        OFFICER,
    )
    return get_success_data(res)


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_delegation_agreement(agreement_id, OFFICER))


def submit_roster_file(agreement_id: str, expected_agreement_version: int, lines: list,
                       submitter_user_id: str = None) -> dict:
    """Submit a roster file as an EnrollmentSpecialist. Pass submitter_user_id
    to control the recorded submitted_by_user_id (segregation-of-duties)."""
    headers = (
        make_enrollment_specialist_headers(submitter_user_id)
        if submitter_user_id is not None
        else SPECIALIST
    )
    res = api_client.create_roster_file(
        create_roster_file_payload(agreement_id, expected_agreement_version, lines),
        headers,
    )
    return get_success_data(res)


def get_roster_lines(roster_file_id: str) -> list:
    return get_success_data(api_client.list_roster_lines(roster_file_id, SPECIALIST))


def get_roster_line(roster_file_id: str, index: int = 0) -> dict:
    lines = get_roster_lines(roster_file_id)
    assert len(lines) > index, f"Roster file {roster_file_id} has no line {index}"
    return lines[index]


def confirm_line(roster_file_id: str, line_id: str, confirmed_effective_date: str) -> dict:
    res = api_client.confirm_roster_line(
        roster_file_id, line_id,
        {"confirmed_effective_date": confirmed_effective_date},
        PAYER_REP,
    )
    return get_success_data(res)


def create_record_via_roster_add(agreement: dict, provider_id: str,
                                 expected_date: str = "2026-08-01",
                                 confirmed_date: str = None,
                                 payer_id: str = None) -> tuple:
    """Submit a single-line ADD roster and confirm it (clean match by default).
    Returns (roster_file, line, created_record)."""
    roster = submit_roster_file(
        agreement["id"], agreement["version"],
        [roster_add_line(provider_id, expected_effective_date=expected_date)],
    )
    line = get_roster_line(roster["id"], 0)
    confirm_line(roster["id"], line["id"], confirmed_date or expected_date)
    record = find_record(provider_id=provider_id, payer_id=payer_id)
    return roster, line, record


# ─── Tier 4: claims ──────────────────────────────────

def create_claim(provider_id: str, payer_id: str, **overrides) -> dict:
    res = api_client.create_claim(
        create_claim_payload(provider_id, payer_id, **overrides),
        SPECIALIST,
    )
    return get_success_data(res)


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, OFFICER))


def get_provider_balance(provider_id: str) -> int:
    provider = get_success_data(api_client.get_provider(provider_id, OFFICER))
    return provider["recoupment_balance_cents"]
