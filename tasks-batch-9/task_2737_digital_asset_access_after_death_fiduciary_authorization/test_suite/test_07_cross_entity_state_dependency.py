"""
Cross-entity state dependencies of the Digital Estate Fiduciary Access API.

Each test here shows one operation whose outcome is decided by the state of a
record it does not itself name: a provider's suspension posture deciding whether
an already-submitted election may be executed, and a death certificate's
verification status deciding whether a fully drafted request package may be
submitted.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import (
    ERR_DEATH_CERTIFICATE_NOT_VERIFIED,
    ERR_PLATFORM_SUSPENDED,
)
from test_helpers.assertions import assert_fields, assert_not_null_fields, assert_null_fields
from test_helpers.constants import (
    ACCESS_UNVERIFIED,
    DISPOSITION_ELECTED,
    DISPOSITION_EXECUTED,
    DOC_PENDING,
    DOC_VERIFIED,
    EL_ACTION_EXECUTE,
    ELECTION_EXECUTED,
    ELECTION_SUBMITTED,
    PHASE_AUTHORIZED,
    PHASE_DISCLOSURE,
    PHASE_INTAKE,
    PHASE_WIND_DOWN,
    PLATFORM_STATUS_PARTICIPATING,
    PLATFORM_STATUS_SUSPENDED,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    REQ_ACTION_SUBMIT,
)
from test_helpers.test_users import make_platform_compliance_headers


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant, tolerating any fractional-second width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _memorialize_election_ready_to_execute(api):
    """A SUBMITTED MEMORIALIZE election over one disclosed cloud-storage account."""
    fixtures.set_clock(api)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-S")
    asset = fixtures.add_asset(
        api, ctx, platform["id"], account_handle="vault-memorial", quoted_value_cents=75000
    )
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    election = fixtures.submitted_election(api, ctx, asset["id"])
    return platform, ctx, asset, election


def test_execute_is_refused_while_the_provider_is_suspended(api):
    """
    A countersign-free MEMORIALIZE election sitting in SUBMITTED cannot be
    executed while its provider's status is SUSPENDED, even though the election
    never references that field, and the refusal leaves the election, the
    account and the estate's counters exactly where they were.

    PRD: "The provider must not be `SUSPENDED` and must still support the elected disposition."

    Design: Difficulty/cross_entity_state_dependency/election_execute_depends_on_platform_status_in_another_aggregate
    """
    platform, ctx, asset, election = _memorialize_election_ready_to_execute(api)
    fixtures.patch_platform(api, platform["id"], status=PLATFORM_STATUS_SUSPENDED)

    response = api.transition_disposition_election(
        election["id"],
        f.election_transition_payload(
            EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-S1"
        ),
        make_platform_compliance_headers(platform["id"]),
    )
    validate_error(response, ERR_PLATFORM_SUSPENDED)

    election_after = fixtures.read_election(api, ctx, election["id"])
    assert_fields(election_after, status=ELECTION_SUBMITTED)
    assert_null_fields(election_after, "executed_at", "platform_confirmation_reference")

    asset_after = fixtures.read_asset(api, ctx, asset["id"])
    assert_fields(asset_after, disposition_status=DISPOSITION_ELECTED)
    assert_null_fields(asset_after, "disposed_at")

    estate = fixtures.read_estate(api, ctx)
    assert_fields(
        estate,
        assets_disposed_count=0,
        assets_pending_disposition_count=1,
        administration_phase=PHASE_DISCLOSURE,
    )


def test_execute_succeeds_once_the_provider_is_restored_to_participating(api):
    """
    The identical EXECUTE call that a suspended provider refused goes through
    once the provider is patched back to PARTICIPATING: the account is
    memorialized, its disposal is stamped and the estate reaches WIND_DOWN.

    PRD: "A `MEMORIALIZE` execution sets the account's `disposition_status` to `EXECUTED` and stamps its `disposed_at`."

    Design: Difficulty/cross_entity_state_dependency/election_execute_depends_on_platform_status_in_another_aggregate
    """
    platform, ctx, asset, election = _memorialize_election_ready_to_execute(api)
    compliance = make_platform_compliance_headers(platform["id"])

    fixtures.patch_platform(api, platform["id"], status=PLATFORM_STATUS_SUSPENDED)
    blocked = api.transition_disposition_election(
        election["id"],
        f.election_transition_payload(
            EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-S1"
        ),
        compliance,
    )
    validate_error(blocked, ERR_PLATFORM_SUSPENDED)

    fixtures.patch_platform(api, platform["id"], status=PLATFORM_STATUS_PARTICIPATING)
    cleared = api.transition_disposition_election(
        election["id"],
        f.election_transition_payload(
            EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-S2"
        ),
        compliance,
    )
    executed = validate_success(cleared, 200)
    assert_fields(
        executed, status=ELECTION_EXECUTED, platform_confirmation_reference="CV-MEM-S2"
    )
    assert_not_null_fields(executed, "executed_at")

    asset_after = fixtures.read_asset(api, ctx, asset["id"])
    assert_fields(asset_after, disposition_status=DISPOSITION_EXECUTED)
    assert_not_null_fields(asset_after, "disposed_at")

    estate = fixtures.read_estate(api, ctx)
    assert_fields(
        estate,
        assets_disposed_count=1,
        assets_pending_disposition_count=0,
        administration_phase=PHASE_WIND_DOWN,
    )


def _package_awaiting_certificate_verification(api):
    """A complete DRAFT package whose death certificate is still PENDING."""
    fixtures.set_clock(api)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-T", verify_death_certificate=False)
    asset = fixtures.add_asset(
        api, ctx, platform["id"], account_handle="vault-pending", quoted_value_cents=30000
    )
    request = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])
    return platform, ctx, asset, request


def test_submit_is_refused_while_the_cited_death_certificate_is_pending(api):
    """
    The package is complete and the letters it cites are verified and issued, yet
    submission is refused because the cited death certificate — a record on
    another aggregate — has never been verified. Nothing moves: the package stays
    in DRAFT with no review window and the estate stays in INTAKE.

    PRD: "The cited death certificate must be in `VERIFIED` status, or the submission is rejected with `ERR_DEATH_CERTIFICATE_NOT_VERIFIED`; a pending or revoked certificate cannot support a submission."

    Design: Difficulty/cross_entity_state_dependency/request_submit_depends_on_death_certificate_verification_state
    """
    platform, ctx, asset, request = _package_awaiting_certificate_verification(api)

    certificate = fixtures.read_document(api, ctx, ctx.death_certificate_id)
    assert_fields(certificate, verification_status=DOC_PENDING)
    assert_fields(fixtures.read_estate(api, ctx), administration_phase=PHASE_INTAKE)

    response = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
    )
    validate_error(response, ERR_DEATH_CERTIFICATE_NOT_VERIFIED)

    request_after = fixtures.read_request(api, ctx, request["id"])
    assert_fields(request_after, status=REQUEST_DRAFT)
    assert_null_fields(request_after, "review_window_start", "review_window_end")
    assert_fields(fixtures.read_estate(api, ctx), administration_phase=PHASE_INTAKE)
    assert_fields(
        fixtures.read_asset(api, ctx, asset["id"]), access_status=ACCESS_UNVERIFIED
    )


def test_submit_succeeds_after_the_registrar_verifies_the_certificate(api):
    """
    Verifying the death certificate carries the estate out of INTAKE and clears
    the way for the identical submission, which opens a fourteen-day half-open
    review window from the current clock position while disclosing nothing.

    PRD: "On submission the server sets `review_window_start` to the current logical-clock instant and `review_window_end` to that instant advanced by the provider's `review_window_days` days, and the window is **half-open**: the start instant is inside the window and the end instant is outside it."

    Design: Difficulty/cross_entity_state_dependency/request_submit_depends_on_death_certificate_verification_state
    """
    platform, ctx, asset, request = _package_awaiting_certificate_verification(api)

    blocked = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
    )
    validate_error(blocked, ERR_DEATH_CERTIFICATE_NOT_VERIFIED)

    verified = fixtures.verify_document(api, ctx.death_certificate_id)
    assert_fields(verified, verification_status=DOC_VERIFIED)
    assert _instant(verified["verified_at"]) == _instant("2026-08-01T00:00:00Z"), (
        f"verified_at should be stamped with the logical clock, got {verified['verified_at']!r}"
    )
    assert_fields(fixtures.read_estate(api, ctx), administration_phase=PHASE_AUTHORIZED)

    cleared = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
    )
    submitted = validate_success(cleared, 200)
    assert_fields(submitted, status=REQUEST_SUBMITTED)
    assert _instant(submitted["review_window_start"]) == _instant("2026-08-01T00:00:00Z"), (
        f"review_window_start should open at the clock, got {submitted['review_window_start']!r}"
    )
    assert _instant(submitted["review_window_end"]) == _instant("2026-08-15T00:00:00Z"), (
        f"review_window_end should be 14 days later, got {submitted['review_window_end']!r}"
    )
    assert_fields(
        fixtures.read_asset(api, ctx, asset["id"]), access_status=ACCESS_UNVERIFIED
    )
