"""Visit recording, overlap and frequency guards, and verification gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_visit,
    create_visit_payload,
    get_success_data,
    provider_headers,
    record_hourly_visits,
    record_visit,
    standard_world,
    submit_claim,
    validate_error,
    validate_success,
    verify_visit,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


def test_visit_created_in_recorded_initial_state(api):
    """PRD §3.5: "The system derives `duration_minutes` as the interval length
    in minutes and computes a provisional `fraud_score` as described in §3.6."
    PRD §3.5: "Verification by a `ClaimsReviewer` moves `RECORDED → VERIFIED`
    and is permitted only while the visit is `RECORDED`"

    Design: Corner/state_machines/visit_created_in_recorded_initial_state
    """
    world = standard_world()
    resp = api.create_visit(
        create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                             check_in_at="2026-05-02T08:00:00Z", check_out_at="2026-05-02T09:30:00Z"),
        provider_headers(world),
    )
    visit = validate_success(resp, expected_status=201)
    assert_visit(visit)
    assert visit["status"] == "RECORDED"
    assert visit["duration_minutes"] == 90, f"08:00-09:30 must derive 90 minutes, got {visit['duration_minutes']}"
    assert visit["fraud_score"] == 0, f"a lone GEO_FENCE visit has no signals, got {visit['fraud_score']}"


class TestVisitHalfOpenOverlap:
    def test_adjacent_visit_allowed(self, api):
        """PRD §3.5: "The interval is half-open — it includes `check_in_at`
        and excludes `check_out_at`" and "merely adjacent visits, where one
        visit's `check_out_at` equals the next visit's `check_in_at`, are
        allowed, while a genuine intersection is refused with
        `ERR_VISIT_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/visit_half_open_overlap
        """
        world = standard_world()
        record_visit(world, "2026-05-02T09:00:00Z", "2026-05-02T10:00:00Z")
        resp = api.create_visit(
            create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                                 check_in_at="2026-05-02T10:00:00Z", check_out_at="2026-05-02T11:00:00Z"),
            provider_headers(world),
        )
        visit = validate_success(resp, expected_status=201)
        assert visit["status"] == "RECORDED", "adjacency is allowed under half-open intervals"

    def test_intersecting_visit_rejected(self, api):
        """PRD §3.5: "the new interval may not intersect any of the member's
        other visits still in `RECORDED` or `VERIFIED`; merely adjacent visits,
        where one visit's `check_out_at` equals the next visit's `check_in_at`,
        are allowed, while a genuine intersection is refused with
        `ERR_VISIT_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/visit_half_open_overlap
        """
        world = standard_world()
        record_visit(world, "2026-05-02T09:00:00Z", "2026-05-02T10:00:00Z")
        resp = api.create_visit(
            create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                                 check_in_at="2026-05-02T09:30:00Z", check_out_at="2026-05-02T10:30:00Z"),
            provider_headers(world),
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_TIME_OVERLAP)


def test_visit_create_rejects_inverted_range(api):
    """PRD §3.5: "The interval is half-open — it includes `check_in_at` and
    excludes `check_out_at` — and `check_out_at` must be strictly later than
    `check_in_at` (`ERR_INVALID_DATE_RANGE`)."

    Design: Corner/validations/visit_create_rejects_inverted_range
    """
    world = standard_world()
    resp = api.create_visit(
        create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                             check_in_at="2026-05-02T09:00:00Z", check_out_at="2026-05-02T09:00:00Z"),
        provider_headers(world),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_visit_frequency_cap_ninth_rejected(api):
    """PRD §3.5: "Under a cap of 8, the eighth visit inside the window
    succeeds and the ninth is refused with `ERR_FREQUENCY_CAP_EXCEEDED`."
    PRD §3.5: "the window's lower bound is strict, so a visit exactly thirty
    days old is excluded"

    Design: Corner/calculations/visit_frequency_cap_ninth_rejected
    """
    world = standard_world()
    record_hourly_visits(world, 8)  # 2026-05-02 08:00 through 16:00

    ninth = api.create_visit(
        create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                             check_in_at="2026-05-02T16:00:00Z", check_out_at="2026-05-02T17:00:00Z"),
        provider_headers(world),
    )
    validate_error(ninth, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED)

    # 2026-05-02T08:00 is strictly outside (2026-06-02T08:00 - 30d, 2026-06-02T08:00].
    later = api.create_visit(
        create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                             check_in_at="2026-06-02T08:00:00Z", check_out_at="2026-06-02T09:00:00Z"),
        provider_headers(world),
    )
    validate_success(later, expected_status=201)


def test_visit_outside_contract_window_rejected(api):
    """PRD §3.5: "First, `check_in_at` must fall inside the provider's
    contract window, closed on both ends (`ERR_SERVICE_OUTSIDE_CONTRACT`)."

    Design: Corner/validations/visit_outside_contract_window_rejected
    """
    world = standard_world()  # contract ends 2026-12-31
    resp = api.create_visit(
        create_visit_payload(world["enrollment"]["id"], world["member"]["id"],
                             check_in_at="2027-01-05T08:00:00Z", check_out_at="2027-01-05T09:00:00Z"),
        provider_headers(world),
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_OUTSIDE_CONTRACT)


class TestVisitVerifyRequiresProviderActive:
    def test_verify_blocked_while_provider_suspended(self, api):
        """PRD §3.5: "Verification by a `ClaimsReviewer` moves `RECORDED →
        VERIFIED` and is permitted only while the visit is `RECORDED`, only
        while the recording provider is `ACTIVE` — a cross-entity dependency
        from visit to provider, failing with `ERR_PROVIDER_NOT_ACTIVE`
        otherwise"

        Design: Difficulty/cross_entity_state_dependency/visit_verify_requires_provider_active
        """
        world = standard_world()
        visit = record_visit(world, "2026-05-02T08:00:00Z", "2026-05-02T09:00:00Z")
        validate_success(api.suspend_provider(world["provider"]["id"], ADMIN))
        resp = api.verify_visit(visit["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_ACTIVE)

    def test_visit_remains_recorded_after_blocked_verify(self, api, admin_headers):
        """PRD §3.5: "only while the recording provider is `ACTIVE` — a
        cross-entity dependency from visit to provider, failing with
        `ERR_PROVIDER_NOT_ACTIVE` otherwise"

        Design: Difficulty/cross_entity_state_dependency/visit_verify_requires_provider_active
        """
        world = standard_world()
        visit = record_visit(world, "2026-05-02T08:00:00Z", "2026-05-02T09:00:00Z")
        validate_success(api.suspend_provider(world["provider"]["id"], ADMIN))
        validate_error(api.verify_visit(visit["id"], REVIEWER), ApiErrorId.ERR_PROVIDER_NOT_ACTIVE)
        after = get_success_data(api.get_visit(visit["id"], admin_headers))
        assert after["status"] == "RECORDED", f"blocked verify must not move the visit, got {after['status']}"


def test_void_visit_referenced_by_open_claim_rejected(api, admin_headers):
    """PRD §3.5: "A verified visit may be voided — `VERIFIED → VOIDED` — only
    while no claim in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `APPROVED`
    references it; otherwise the void is refused with `ERR_VISIT_IN_USE`."

    Design: Corner/validations/void_visit_referenced_by_open_claim_rejected
    """
    world = standard_world()
    visit = record_visit(world, "2026-05-02T08:00:00Z", "2026-05-02T09:00:00Z")
    verify_visit(visit["id"])
    submit_claim(world, 1000, "R-V", visit_ids=[visit["id"]])

    resp = api.void_visit(visit["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_VISIT_IN_USE)
    after = get_success_data(api.get_visit(visit["id"], admin_headers))
    assert after["status"] == "VERIFIED", f"blocked void must leave the visit VERIFIED, got {after['status']}"
