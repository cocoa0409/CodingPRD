"""Role-based access control and ProviderRep scoping (PRD §2.1, §2.8, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_case_manager_headers,
    make_pharmacy_analyst_headers,
    make_plan_admin_headers,
    make_provider_rep_headers,
    setup_approved_scenario,
    submit_claim,
    create_drug_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoleExclusiveOperations:
    def test_roles_blocked_from_other_roles_exclusive_operations(self, api):
        """PRD §2.1: "Once the caller's context is established, each operation is
        restricted to designated roles per §4; an authenticated caller attempting an
        operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §2.8: "Every request is evaluated against an ordered pipeline, and an earlier
        failure masks later ones — the first failing stage determines the error returned."
        (role permission, stage 2, precedes existence, stage 5).

        Design: Corner/rbac/role_exclusive_denied_matrix
        """
        # Targets exist so the 403 (role stage) is what fires, never a 404.
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J7200", "drug_name": "RbacDrug"},
            member_id="MEM-R1",
        )
        claim = submit_claim(scenario, billed_units=10)
        auth_id = scenario["auth"]["id"]
        prov_id = scenario["provider"]["id"]

        # ProviderRep registering a drug (PlanAdmin-only per §4).
        resp = api.create_drug(
            create_drug_payload(j_code="J7201", drug_name="BadActor"),
            make_provider_rep_headers(prov_id),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

        # CaseManager suspending an authorization (MedicalPolicyOfficer-only per §4).
        resp = api.suspend_auth(auth_id, make_case_manager_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

        # PharmacyAnalyst paying a claim (PlanAdmin-only per §4).
        resp = api.pay_claim(claim["id"], make_pharmacy_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

        # PlanAdmin accepting a redirection (CaseManager-only per §4); the role check
        # fires before the existence check, so even a nonexistent id yields 403.
        resp = api.accept_redirection(
            NON_EXISTENT_UUID, {"accepted_site": "HOME"}, make_plan_admin_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestProviderScope:
    def test_provider_rep_scope_guard_and_silent_list_scoping(self, api):
        """PRD §2.1: "A `ProviderRep` addressing a resource that belongs to a different
        provider account is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.1: "List queries issued by a provider representative without an explicit
        foreign `provider_account_id` filter are not rejected; they are silently scoped
        to the caller's own account."

        Design: Corner/rbac/provider_scope_violation
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J7300", "drug_name": "ScopeDrug"},
            member_id="MEM-R2",
        )
        provider_b = scenario["provider"]
        claim_b = submit_claim(scenario, billed_units=10)
        assert claim_b["status"] == "APPROVED_FOR_PAYMENT"

        provider_a = get_success_data(
            api.create_provider_account({"name": "Provider A"}, make_plan_admin_headers())
        )
        rep_a = make_provider_rep_headers(provider_a["id"])

        # Reading another provider's claim by id -> 403 scope violation.
        resp = api.get_claim(claim_b["id"], rep_a)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SCOPE_VIOLATION, 403)

        # Listing with an explicit foreign provider_account_id filter -> 403.
        resp = api.list_claims(rep_a, params={"provider_account_id": provider_b["id"]})
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SCOPE_VIOLATION, 403)

        # Unfiltered list -> 200, silently scoped to the caller's own (empty) account.
        data, meta = validate_paginated(api.list_claims(rep_a))
        assert data == [], "auto-scoped list must hide other providers' claims"
        assert meta["total_count"] == 0

        # The same scope lens covers single provider-account reads (PRD §2.1).
        resp = api.get_provider_account(provider_b["id"], rep_a)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SCOPE_VIOLATION, 403)
        own = validate_success(api.get_provider_account(provider_a["id"], rep_a))
        assert own["id"] == provider_a["id"]
