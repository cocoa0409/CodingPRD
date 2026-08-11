"""Provider lifecycle: suspend/reinstate cycle, contract OCC, RBAC, cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_provider_payload,
    get_success_data,
    make_provider_operator_headers,
    put_contract_payload,
    record_visit,
    standard_world,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]


class TestProviderSuspendReinstateCycle:
    def test_provider_suspend_reinstate_returns_to_active(self, api):
        """PRD §3.3: "the network lifecycle then runs `PENDING_ONBOARD →
        ACTIVE`, `ACTIVE → SUSPENDED`, `SUSPENDED → ACTIVE`, and `ACTIVE` or
        `SUSPENDED → TERMINATED`."

        Design: Difficulty/non_linear_state_machine/provider_suspend_reinstate_cycle
        """
        provider = get_success_data(api.create_provider(create_provider_payload(name="CycGym"), ADMIN))
        get_success_data(api.activate_provider(provider["id"], ADMIN))
        suspended = validate_success(api.suspend_provider(provider["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_provider(provider["id"], ADMIN))
        assert reinstated["status"] == "ACTIVE", (
            f"ACTIVE -> SUSPENDED -> ACTIVE loop must end ACTIVE, got {reinstated['status']}"
        )

    def test_provider_suspend_reinstate_version_progression(self, api):
        """PRD §2.4: "`version` (integer): a system-managed counter that
        increments with every mutation, including system-driven mutations such
        as cascade steps and automatic state transitions."

        Design: Difficulty/non_linear_state_machine/provider_suspend_reinstate_cycle
        """
        provider = get_success_data(api.create_provider(create_provider_payload(name="CycGym"), ADMIN))
        assert provider["version"] == 1
        activated = get_success_data(api.activate_provider(provider["id"], ADMIN))
        assert activated["version"] == 2
        suspended = get_success_data(api.suspend_provider(provider["id"], ADMIN))
        assert suspended["version"] == 3
        reinstated = get_success_data(api.reinstate_provider(provider["id"], ADMIN))
        assert reinstated["version"] == 4, (
            f"create/activate/suspend/reinstate must yield version 4, got {reinstated['version']}"
        )


def test_provider_contract_stale_version_rejected(api):
    """PRD §2.7: "Re-papering a provider's contract via
    `PUT /api/providers/{id}/contract` requires `expected_provider_version`,
    the caller's last observed `version` of the provider."
    PRD §2.7: "In both cases, if the supplied expectation does not match the
    resource's current `version` — because a previously accepted amendment has
    already advanced it — the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no replacement occurs."

    Design: Corner/cross_cutting_complexity_layers/provider_contract_stale_version_rejected
    """
    provider = get_success_data(api.create_provider(create_provider_payload(name="OccGym"), ADMIN))
    stale_version = provider["version"]

    first = api.put_provider_contract(provider["id"], put_contract_payload(stale_version), ADMIN)
    updated = validate_success(first)
    assert updated["version"] == stale_version + 1

    second = api.put_provider_contract(
        provider["id"],
        put_contract_payload(stale_version, contract_end="2026-03-31T23:59:59Z", visit_rate_cents=1700),
        ADMIN,
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)


def test_provider_operator_cannot_activate_provider(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/provider_operator_cannot_activate_provider
    """
    provider = get_success_data(api.create_provider(create_provider_payload(name="SelfGym"), ADMIN))
    resp = api.activate_provider(provider["id"], make_provider_operator_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = get_success_data(api.get_provider(provider["id"], ADMIN))
    assert after["status"] == "PENDING_ONBOARD"


def test_provider_terminate_cascades_visits_and_claims(api, admin_headers):
    """PRD §3.3: "Every visit recorded by that provider and still `RECORDED`
    flips to `REJECTED`; each such rejection forces any claim in `SUBMITTED`
    or `NEEDS_INFO` at that provider to `REJECTED`; and each auto-rejected
    claim releases its enrollment reservation."

    Design: Corner/state_machines/provider_terminate_cascades_visits_and_claims
    """
    world = standard_world()
    visit = record_visit(world, "2026-05-02T08:00:00Z", "2026-05-02T09:00:00Z")
    claim = submit_claim(world, 1000, "R-DP", as_provider=True)

    validate_success(api.terminate_provider(world["provider"]["id"], ADMIN))

    visit_after = get_success_data(api.get_visit(visit["id"], admin_headers))
    assert visit_after["status"] == "REJECTED", f"RECORDED visit must be rejected, got {visit_after['status']}"
    claim_after = get_success_data(api.get_claim(claim["id"], admin_headers))
    assert claim_after["review_status"] == "REJECTED", (
        f"SUBMITTED claim at the provider must be rejected, got {claim_after['review_status']}"
    )
    allowance = get_success_data(api.get_enrollment_allowance(world["enrollment"]["id"], admin_headers))
    assert allowance["reserved_cents"] == 0, (
        f"auto-rejected claim must release its reservation, reserved={allowance['reserved_cents']}"
    )
