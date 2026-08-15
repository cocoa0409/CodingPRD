"""Project commercial rollups (volume-discounted fee), exploration
authorizations (cap boundary, OCC, ownership), and plan-creation OCC."""
import pytest

from test_helpers import (
    LM,
    PM,
    SE,
    ApiErrorId,
    api_client,
    approve_authorization,
    create_authorization,
    create_boring_plan_payload,
    create_client,
    create_lab_order,
    create_project,
    get_project,
    get_success_data,
    make_client_rep_headers,
    setup_fieldwork_project,
    setup_lab_received_sample,
    transition_authorization,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Volume-discount tier on the pre-discount gross (difficulty, two tests)
# ---------------------------------------------------------------------------

class TestProjectFeeDiscountTierOnPrediscountGross:
    """The 5% discount tier keys on the PRE-discount gross: a project at
    exactly 500,000 cents gross qualifies and lands below the tier."""

    def _project_with_orders(self, api, base_fee_cents, orders):
        """FIELDWORK project with the given base fee and a lab-received
        sample, then the given (test_type, priority) orders created."""
        ctx = setup_lab_received_sample(base_fee_cents=base_fee_cents)
        for test_type, priority in orders:
            create_lab_order(ctx["project"]["id"], ctx["sample"]["id"],
                             test_type=test_type, priority=priority)
        return ctx

    def test_gross_exactly_at_tier_receives_discount_and_lands_below(self, api):
        """PRD section 3.6: "The `total_fee_cents` recomputes whenever the
        base fee changes or the testing invoice is recomputed, in a pinned
        order: first take the project's `testing_invoice_cents`; add it to
        `base_fee_cents` for the gross; when that gross is at least 500,000
        cents, the discount is five percent of the testing invoice rounded
        half-up to whole cents, and when the gross is below the tier the
        discount is zero; `total_fee_cents` is the gross minus the discount.
        The tier test keys on the pre-discount gross, so a project whose
        gross is exactly 500,000 cents — say a 300,000-cent base fee and a
        200,000-cent testing invoice — receives the 10,000-cent discount and
        lands at 490,000 cents, below the tier it qualified on."

        Design: Difficulty/combinatorial_formula/project_fee_discount_tier_on_prediscount_gross
        """
        ctx = self._project_with_orders(api, 300000, [
            ("DIRECT_SHEAR", "STANDARD"), ("DIRECT_SHEAR", "STANDARD"),
            ("SIEVE_ANALYSIS", "STANDARD"), ("SIEVE_ANALYSIS", "STANDARD"),
            ("PROCTOR", "STANDARD"), ("UNCONFINED_COMPRESSION", "STANDARD"),
        ])
        project = get_success_data(api.get_project(ctx["project"]["id"], PM))
        # 55000*2 + 18500*2 + 21000 + 32000 = 200000 exactly.
        assert project["testing_invoice_cents"] == 200000
        # gross 300000 + 200000 = 500000 >= tier -> discount 10000.
        assert project["total_fee_cents"] == 490000

    def test_gross_below_tier_gets_no_discount(self, api):
        """PRD section 3.6: "when that gross is at least 500,000 cents, the
        discount is five percent of the testing invoice rounded half-up to
        whole cents, and when the gross is below the tier the discount is
        zero; `total_fee_cents` is the gross minus the discount. The tier
        test keys on the pre-discount gross".

        Design: Difficulty/combinatorial_formula/project_fee_discount_tier_on_prediscount_gross
        """
        ctx = self._project_with_orders(api, 300000, [
            ("DIRECT_SHEAR", "STANDARD"),
        ])
        project = get_success_data(api.get_project(ctx["project"]["id"], PM))
        assert project["testing_invoice_cents"] == 55000
        # gross 355000 < 500000 -> no discount.
        assert project["total_fee_cents"] == 355000


# ---------------------------------------------------------------------------
# Authorization approve/revoke compensation (difficulty, two tests)
# ---------------------------------------------------------------------------

class TestAuthorizationApproveRevokeRestoresCommittedBudget:
    """additional_committed_cents is conserved: approve commits, revoke
    compensates."""

    def test_approve_then_revoke_restores_zero(self, api):
        """PRD section 3.3: "Approval adds `authorized_amount_cents` to
        `additional_committed_cents` and increments the Project's `version`
        by 1. The `ClientRep` may instead revoke an approval (`APPROVED` →
        `REVOKED`) under the same ownership and OCC guards, but only while
        `consumed_boring_count` is still zero (`ERR_INVALID_STATE`
        otherwise); revocation subtracts the amount from
        `additional_committed_cents` as compensation and likewise increments
        the Project's `version`."

        Design: Difficulty/compensating_invariant/authorization_approve_revoke_restores_committed_budget
        """
        ctx = setup_fieldwork_project()
        project_id = ctx["project"]["id"]
        assert get_project(project_id)["additional_committed_cents"] == 0

        auth = create_authorization(project_id, authorized_amount_cents=200000,
                                    extra_boring_count=2)
        approve_authorization(auth["id"], ctx["client"]["id"], project_id)
        after_approve = get_project(project_id)
        assert after_approve["additional_committed_cents"] == 200000

        transition_authorization(auth["id"], "REVOKED", ctx["client"]["id"],
                                 after_approve["version"])
        after_revoke = get_project(project_id)
        assert after_revoke["additional_committed_cents"] == 0, (
            "Revocation must subtract the amount as compensation"
        )

    def test_committed_equals_sum_over_approved_authorizations(self, api):
        """PRD section 3.3: "The project's `additional_committed_cents`
        therefore always equals the sum of `authorized_amount_cents` over
        authorizations in `APPROVED`, plus those in `EXHAUSTED`, which keep
        their amounts committed."

        Design: Difficulty/compensating_invariant/authorization_approve_revoke_restores_committed_budget
        """
        ctx = setup_fieldwork_project()
        project_id = ctx["project"]["id"]
        client_id = ctx["client"]["id"]

        auth1 = create_authorization(project_id, authorized_amount_cents=100000,
                                     extra_boring_count=1)
        approve_authorization(auth1["id"], client_id, project_id)
        auth2 = create_authorization(project_id, authorized_amount_cents=100000,
                                     extra_boring_count=1)
        approve_authorization(auth2["id"], client_id, project_id)
        assert get_project(project_id)["additional_committed_cents"] == 200000

        current = get_project(project_id)
        transition_authorization(auth1["id"], "REVOKED", client_id,
                                 current["version"])
        assert get_project(project_id)["additional_committed_cents"] == 100000, (
            "Only the still-APPROVED authorization's amount remains committed"
        )


# ---------------------------------------------------------------------------
# OCC on plan creation and authorization transitions (corner instances)
# ---------------------------------------------------------------------------

def test_occ_stale_project_version_on_plan_create_returns_412(api):
    """PRD section 2.7: "Creating a boring-plan revision —
    `POST /geo/projects/{id}/boring-plans` — requires
    `expected_project_version` matching the target Project's current
    `version`. A mismatch is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412)" and "Plan creation itself increments the parent Project's
    `version` by 1."

    Design: Corner/validations/occ_stale_project_version_on_plan_create_returns_412
    """
    client = create_client()
    project = create_project(client["id"])
    stale_version = project["version"]

    first = api.create_boring_plan(
        project["id"], create_boring_plan_payload(stale_version), SE)
    validate_success(first, 201)

    # Replaying the pre-first-create version is stale: the first create
    # already bumped the project's version.
    resp = api.create_boring_plan(
        project["id"],
        create_boring_plan_payload(stale_version, planned_boring_count=2,
                                   planned_total_footage_ft=60),
        SE)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
    assert resp.status_code == 412


def test_occ_stale_project_version_on_authorization_approve_returns_412(api):
    """PRD section 2.7: "Approving or revoking an exploration authorization —
    `POST /geo/exploration-authorizations/{id}/transition` — requires
    `expected_project_version` matching the Project's current `version`; a
    mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The
    transition mutates the project's committed-authorization total, so a
    stale view of that total must not drive the cap check."

    Design: Corner/validations/occ_stale_project_version_on_authorization_approve_returns_412
    """
    ctx = setup_fieldwork_project()
    project_id = ctx["project"]["id"]
    auth = create_authorization(project_id, authorized_amount_cents=100000,
                                extra_boring_count=1)
    current_version = get_project(project_id)["version"]

    resp = api.transition_exploration_authorization(
        auth["id"],
        {"to": "APPROVED", "expected_project_version": current_version - 1},
        make_client_rep_headers(ctx["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
    assert resp.status_code == 412

    after = get_success_data(api.get_exploration_authorization(auth["id"], PM))
    assert after["status"] == "PROPOSED", "A stale approval has no side effects"
    assert get_project(project_id)["additional_committed_cents"] == 0


def test_authorization_cap_inclusive_boundary(api):
    """PRD section 3.3: "the project's `additional_committed_cents` plus the
    new `authorized_amount_cents` must not exceed
    `additional_auth_cap_cents`, an inclusive boundary — a total exactly
    equal to the cap passes, one cent over fails with
    `ERR_AUTH_CAP_EXCEEDED` (HTTP 422)".

    Design: Corner/validations/authorization_cap_inclusive_boundary
    """
    ctx = setup_fieldwork_project()
    project_id = ctx["project"]["id"]
    client_id = ctx["client"]["id"]

    auth1 = create_authorization(project_id, authorized_amount_cents=300000,
                                 extra_boring_count=2)
    approve_authorization(auth1["id"], client_id, project_id)
    auth2 = create_authorization(project_id, authorized_amount_cents=200000,
                                 extra_boring_count=1)
    approved2 = approve_authorization(auth2["id"], client_id, project_id)
    assert approved2["status"] == "APPROVED", (
        "300000 + 200000 == 500000 cap: the inclusive boundary admits equality"
    )
    assert get_project(project_id)["additional_committed_cents"] == 500000

    auth3 = create_authorization(project_id, authorized_amount_cents=1,
                                 extra_boring_count=1)
    current_version = get_project(project_id)["version"]
    resp = api.transition_exploration_authorization(
        auth3["id"],
        {"to": "APPROVED", "expected_project_version": current_version},
        make_client_rep_headers(client_id))
    validate_error(resp, ApiErrorId.ERR_AUTH_CAP_EXCEEDED)
    assert resp.status_code == 422


def test_clientrep_cannot_approve_other_clients_authorization(api):
    """PRD section 3.3: "The owning `ClientRep` approves it (`PROPOSED` →
    `APPROVED`): the caller's `X-User-ID` must equal the project's
    `client_id` (`ERR_FORBIDDEN_ROLE` otherwise)".
    PRD section 2.1: "When `X-User-Role` is `ClientRep`, `X-User-ID` is the
    `id` of the acting `Client`; ownership checks on any resource that
    references a `Client` — directly, or through a Project's `client_id` —
    compare that foreign key to `X-User-ID`."

    Design: Corner/rbac/clientrep_cannot_approve_other_clients_authorization
    """
    ctx = setup_fieldwork_project()
    other_client = create_client(name="Beta LLC", contact_email="b@x.com")
    project_id = ctx["project"]["id"]
    auth = create_authorization(project_id, authorized_amount_cents=100000,
                                extra_boring_count=1)
    current_version = get_project(project_id)["version"]

    resp = api.transition_exploration_authorization(
        auth["id"],
        {"to": "APPROVED", "expected_project_version": current_version},
        make_client_rep_headers(other_client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403
