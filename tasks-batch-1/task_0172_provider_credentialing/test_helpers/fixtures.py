"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before each
test. Fixtures use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

All roles are opaque; the deterministic clock, segregation-of-duties anchor
(initiated_by_user_id), and chair tie-break (chair_user_id) depend on the exact
X-User-ID strings, so the builders thread explicit user_id values throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_system_admin_headers,
    make_specialist_headers,
    make_medical_director_headers,
    make_peer_reviewer_headers,
    make_enrollment_coordinator_headers,
    make_compliance_officer_headers,
)
from . import factories as f

# Canonical operator identities used across fixtures.
ADMIN = "admin-1"
SPEC = "spec-1"
MD = "md-1"
REV2 = "rev-2"
REV3 = "rev-3"
ENR = "enr-1"
COMP = "comp-1"

LICENSE_ISSUED = "2025-01-01T00:00:00.000Z"
LICENSE_FAR_EXPIRY = "2030-01-01T00:00:00.000Z"


# -------------------------------------------------------------------------
# Tier 0: atomic helpers
# -------------------------------------------------------------------------
def create_org(name="CVO", **overrides):
    """Create a credentialing org. Returns the org dict (current_utc at default)."""
    resp = api_client.create_org(f.create_org_payload(name=name, **overrides),
                                 make_system_admin_headers(ADMIN))
    return get_success_data(resp)


def set_clock(org_id, to_iso8601):
    """Advance the deterministic clock (SystemAdmin only). Returns the org dict."""
    resp = api_client.set_clock(f.set_clock_payload(to_iso8601),
                                make_system_admin_headers(ADMIN))
    return get_success_data(resp)


def create_provider(org_id, npi="1234567890", caqh_id="CAQH-A",
                    spec_user_id=SPEC, full_name="Dr A", **overrides):
    resp = api_client.create_provider(
        f.create_provider_payload(org_id, npi=npi, caqh_id=caqh_id,
                                  full_name=full_name, **overrides),
        make_specialist_headers(spec_user_id))
    return get_success_data(resp)


def add_license(provider_id, identifier="LIC-1", issued_date=LICENSE_ISSUED,
                expiration_date=LICENSE_FAR_EXPIRY, item_type="STATE_LICENSE",
                spec_user_id=SPEC):
    resp = api_client.create_credential_item(
        provider_id,
        f.create_credential_item_payload(
            item_type=item_type, identifier=identifier,
            issued_date=issued_date, expiration_date=expiration_date),
        make_specialist_headers(spec_user_id))
    return get_success_data(resp)


def create_payer(org_id, name="Plan X", retroactive_allowed=False,
                 panel_capacity=5, enr_user_id=ENR, **overrides):
    resp = api_client.create_payer(
        f.create_payer_payload(org_id, name=name,
                               retroactive_allowed=retroactive_allowed,
                               panel_capacity=panel_capacity, **overrides),
        make_enrollment_coordinator_headers(enr_user_id))
    return get_success_data(resp)


def create_sanctions_source(org_id, source_code="OIG_LEIE", severity_weight=3,
                            comp_user_id=COMP):
    resp = api_client.create_sanctions_source(
        f.create_sanctions_source_payload(org_id, source_code=source_code,
                                          severity_weight=severity_weight),
        make_compliance_officer_headers(comp_user_id))
    return get_success_data(resp)


def create_reviewer(org_id, user_id, full_name=None, vote_weight=None,
                    admin_user_id=ADMIN):
    extra = {}
    if vote_weight is not None:
        extra["vote_weight"] = vote_weight
    if full_name is None:
        full_name = f"Reviewer {user_id}"
    resp = api_client.create_peer_reviewer(
        f.create_peer_reviewer_payload(org_id, user_id, full_name=full_name, **extra),
        make_system_admin_headers(admin_user_id))
    return get_success_data(resp)


# -------------------------------------------------------------------------
# Tier 1: provider lifecycle progressions
# -------------------------------------------------------------------------
def setup_provider_submitted(org_id=None, npi="1234567890", caqh_id="CAQH-A",
                             license_expiration=LICENSE_FAR_EXPIRY,
                             license_identifier="LIC-1", spec_user_id=SPEC):
    """Org + provider with one STATE_LICENSE, application SUBMITTED.

    Returns (org_id, provider, license_item).
    """
    if org_id is None:
        org_id = create_org()["id"]
    provider = create_provider(org_id, npi=npi, caqh_id=caqh_id, spec_user_id=spec_user_id)
    item = add_license(provider["id"], identifier=license_identifier,
                       expiration_date=license_expiration, spec_user_id=spec_user_id)
    get_success_data(api_client.submit_application(provider["id"],
                                                   make_specialist_headers(spec_user_id)))
    return org_id, provider, item


def setup_provider_in_verification(org_id=None, npi="1234567890", caqh_id="CAQH-A",
                                   license_expiration=LICENSE_FAR_EXPIRY,
                                   license_identifier="LIC-1", spec_user_id=SPEC):
    """Provider IN_VERIFICATION; its license is PENDING_PSV.

    Returns (org_id, provider, license_item).
    """
    org_id, provider, item = setup_provider_submitted(
        org_id=org_id, npi=npi, caqh_id=caqh_id, license_expiration=license_expiration,
        license_identifier=license_identifier, spec_user_id=spec_user_id)
    get_success_data(api_client.begin_verification(provider["id"],
                                                   make_specialist_headers(spec_user_id)))
    return org_id, provider, item


def setup_provider_ready_for_review(org_id=None, npi="1234567890", caqh_id="CAQH-A",
                                    license_expiration=LICENSE_FAR_EXPIRY,
                                    license_identifier="LIC-1", spec_user_id=SPEC):
    """Provider READY_FOR_REVIEW: one license VERIFIED, verification finalized.

    Returns (org_id, provider, license_item).
    """
    org_id, provider, item = setup_provider_in_verification(
        org_id=org_id, npi=npi, caqh_id=caqh_id, license_expiration=license_expiration,
        license_identifier=license_identifier, spec_user_id=spec_user_id)
    vr = get_success_data(api_client.create_verification_request(
        item["id"], f.create_verification_request_payload(),
        make_specialist_headers(spec_user_id)))
    get_success_data(api_client.complete_verification_request(
        vr["id"], f.complete_verification_payload("PASS"),
        make_specialist_headers(spec_user_id)))
    get_success_data(api_client.finalize_verification(
        provider["id"], make_specialist_headers(spec_user_id)))
    return org_id, provider, item


# -------------------------------------------------------------------------
# Tier 2 / 3: peer-review committee + clearing a provider
# -------------------------------------------------------------------------
def register_three_reviewers(org_id, chair_user_id=MD, rev2_user_id=REV2,
                             rev3_user_id=REV3):
    """Register chair + two reviewers (all default vote_weight 1).

    Returns (chair, rev2, rev3).
    """
    chair = create_reviewer(org_id, chair_user_id, full_name="Chair MD")
    rev2 = create_reviewer(org_id, rev2_user_id, full_name="Rev 2")
    rev3 = create_reviewer(org_id, rev3_user_id, full_name="Rev 3")
    return chair, rev2, rev3


def setup_file_under_review(org_id=None, npi="1234567890", caqh_id="CAQH-A",
                            license_expiration=LICENSE_FAR_EXPIRY,
                            license_identifier="LIC-1", spec_user_id=SPEC,
                            chair_user_id=MD, reviewers=None):
    """Provider READY_FOR_REVIEW + 3 registered reviewers + a file UNDER_REVIEW.

    Pass `reviewers=(chair, rev2, rev3)` to reuse an existing committee (e.g.
    when multiple providers in the same org share one panel); otherwise three
    fresh reviewers are registered.

    Returns dict with keys: org_id, provider, item, chair, rev2, rev3, file.
    """
    org_id, provider, item = setup_provider_ready_for_review(
        org_id=org_id, npi=npi, caqh_id=caqh_id, license_expiration=license_expiration,
        license_identifier=license_identifier, spec_user_id=spec_user_id)
    if reviewers is None:
        chair, rev2, rev3 = register_three_reviewers(org_id, chair_user_id=chair_user_id)
    else:
        chair, rev2, rev3 = reviewers
    file = get_success_data(api_client.create_credentialing_file(
        provider["id"], make_specialist_headers(spec_user_id)))
    get_success_data(api_client.open_review(
        file["id"], make_medical_director_headers(chair_user_id)))
    return {"org_id": org_id, "provider": provider, "item": item,
            "chair": chair, "rev2": rev2, "rev3": rev3, "file": file}


def cast_three_yes_votes(file_id, chair, rev2, rev3, chair_user_id=MD,
                         rev2_user_id=REV2, rev3_user_id=REV3):
    """Cast YES from rev2, rev3, and chair on the file."""
    get_success_data(api_client.cast_vote(
        file_id, f.cast_vote_payload(rev2["id"], "YES"),
        make_peer_reviewer_headers(rev2_user_id)))
    get_success_data(api_client.cast_vote(
        file_id, f.cast_vote_payload(rev3["id"], "YES"),
        make_peer_reviewer_headers(rev3_user_id)))
    get_success_data(api_client.cast_vote(
        file_id, f.cast_vote_payload(chair["id"], "YES"),
        make_medical_director_headers(chair_user_id)))


def finalize_file(file_id, decision="APPROVE", chair_user_id=MD, decision_reason=None):
    """GET the file for its current version, then finalize with that version.

    Returns the finalized file dict.
    """
    file = get_success_data(api_client.get_credentialing_file(
        file_id, make_medical_director_headers(chair_user_id)))
    extra = {}
    if decision_reason is not None:
        extra["decision_reason"] = decision_reason
    resp = api_client.finalize_file(
        file_id, f.finalize_payload(decision, file["version"], **extra),
        make_medical_director_headers(chair_user_id))
    return get_success_data(resp)


def setup_cleared_provider(org_id=None, clock="2026-03-01T00:00:00.000Z",
                           npi="1234567890", caqh_id="CAQH-A",
                           license_expiration=LICENSE_FAR_EXPIRY,
                           license_identifier="LIC-1",
                           spec_user_id=SPEC, chair_user_id=MD, reviewers=None):
    """Full lifecycle to a CLEARED provider.

    Sets the clock to `clock` (so credentialing_completed_date is deterministic;
    pass clock=None to leave the clock untouched, e.g. when a caller already set
    it), builds a provider READY_FOR_REVIEW with one verified license, registers a
    3-member committee (or reuses `reviewers`), opens review, casts 3 YES votes,
    and finalizes APPROVE.

    Returns dict: org_id, provider, item, chair, rev2, rev3, file.
    The provider is now CLEARED / recred_state CURRENT.
    """
    if org_id is None:
        org_id = create_org()["id"]
    if clock is not None:
        set_clock(org_id, clock)
    ctx = setup_file_under_review(org_id=org_id, npi=npi, caqh_id=caqh_id,
                                  license_expiration=license_expiration,
                                  license_identifier=license_identifier,
                                  spec_user_id=spec_user_id, chair_user_id=chair_user_id,
                                  reviewers=reviewers)
    cast_three_yes_votes(ctx["file"]["id"], ctx["chair"], ctx["rev2"], ctx["rev3"],
                         chair_user_id=chair_user_id)
    finalize_file(ctx["file"]["id"], "APPROVE", chair_user_id=chair_user_id)
    return ctx


def setup_active_enrollment(org_id=None, clock="2026-03-01T00:00:00.000Z",
                            npi="1234567890", caqh_id="CAQH-A",
                            license_expiration=LICENSE_FAR_EXPIRY,
                            license_identifier="LIC-1",
                            retroactive_allowed=False, panel_capacity=5,
                            payer_name="Plan X", spec_user_id=SPEC, reviewers=None):
    """Full lifecycle to a CLEARED provider with one ACTIVE payer enrollment.

    Returns dict: org_id, provider, item, payer, enrollment (ACTIVE),
    chair, rev2, rev3, file.
    """
    ctx = setup_cleared_provider(org_id=org_id, clock=clock, npi=npi, caqh_id=caqh_id,
                                 license_expiration=license_expiration,
                                 license_identifier=license_identifier,
                                 spec_user_id=spec_user_id, reviewers=reviewers)
    payer = create_payer(ctx["org_id"], name=payer_name,
                         retroactive_allowed=retroactive_allowed,
                         panel_capacity=panel_capacity)
    enrollment = get_success_data(api_client.create_payer_enrollment(
        ctx["provider"]["id"], f.create_enrollment_payload(payer["id"]),
        make_enrollment_coordinator_headers(ENR)))
    get_success_data(api_client.submit_enrollment(
        enrollment["id"], make_enrollment_coordinator_headers(ENR)))
    enrollment = get_success_data(api_client.activate_enrollment(
        enrollment["id"], make_enrollment_coordinator_headers(ENR)))
    return {"org_id": ctx["org_id"], "provider": ctx["provider"], "item": ctx["item"],
            "payer": payer, "enrollment": enrollment, "chair": ctx["chair"],
            "rev2": ctx["rev2"], "rev3": ctx["rev3"], "file": ctx["file"]}


def setup_submitted_enrollment_for_cleared(org_id=None,
                                           clock="2026-03-01T00:00:00.000Z",
                                           retroactive_allowed=False,
                                           panel_capacity=5, payer_name="Plan X"):
    """CLEARED provider + a payer + an enrollment in SUBMITTED state.

    Returns dict: org_id, provider, payer, enrollment (SUBMITTED), chair/rev2/rev3.
    """
    ctx = setup_cleared_provider(org_id=org_id, clock=clock)
    payer = create_payer(ctx["org_id"], name=payer_name,
                         retroactive_allowed=retroactive_allowed,
                         panel_capacity=panel_capacity)
    enrollment = get_success_data(api_client.create_payer_enrollment(
        ctx["provider"]["id"], f.create_enrollment_payload(payer["id"]),
        make_enrollment_coordinator_headers(ENR)))
    enrollment = get_success_data(api_client.submit_enrollment(
        enrollment["id"], make_enrollment_coordinator_headers(ENR)))
    return {"org_id": ctx["org_id"], "provider": ctx["provider"], "payer": payer,
            "enrollment": enrollment, "chair": ctx["chair"],
            "rev2": ctx["rev2"], "rev3": ctx["rev3"]}


# -------------------------------------------------------------------------
# Tier 4: sanctions
# -------------------------------------------------------------------------
def setup_open_hit_screening(org_id=None, severity_weight=3, source_code="OIG_LEIE",
                             spec_user_id=SPEC):
    """Provider (DRAFT, license added, not submitted) + an OPEN HIT screening.

    Returns dict: org_id, provider, source, screening.
    """
    if org_id is None:
        org_id = create_org()["id"]
    source = create_sanctions_source(org_id, source_code=source_code,
                                     severity_weight=severity_weight)
    provider = create_provider(org_id, spec_user_id=spec_user_id)
    add_license(provider["id"], spec_user_id=spec_user_id)
    screening = get_success_data(api_client.create_sanctions_screening(
        provider["id"], f.create_sanctions_screening_payload(source["id"], "HIT"),
        make_compliance_officer_headers(COMP)))
    return {"org_id": org_id, "provider": provider, "source": source,
            "screening": screening}
