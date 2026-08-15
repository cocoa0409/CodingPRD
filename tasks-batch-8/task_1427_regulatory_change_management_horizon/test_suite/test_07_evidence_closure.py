"""Evidence packages, sealing cascade, and change closure."""
from test_helpers import (
    ApiErrorId,
    create_artifact_payload,
    get_change,
    get_plan,
    make_business_owner_headers,
    make_manager_headers,
    parse_iso,
    setup_completed_plan_with_package,
    setup_plan,
    validate_error,
    validate_success,
    MANAGER_1,
    api_client,
)


class TestPackageLifecycle:
    def test_second_package_for_plan_rejected(self, api, manager_1_headers):
        """PRD §3.8: "at most one package may exist per plan
        (`ERR_PACKAGE_ALREADY_EXISTS`)".

        Design: Corner/endpoints/ep_second_package_for_plan_rejected
        """
        pipe = setup_completed_plan_with_package(citation="EP-3")
        owner_headers = make_business_owner_headers(pipe["owner"]["id"])
        resp = api.create_evidence_package(
            {"implementation_plan_id": pipe["plan"]["id"]}, owner_headers
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_ALREADY_EXISTS)
        first = validate_success(api.get_evidence_package(pipe["package"]["id"], manager_1_headers))
        assert first["status"] == "ASSEMBLING"

    def test_package_requires_completed_plan(self, api):
        """PRD §3.8: "Once a plan stands `COMPLETED`, its owner opens a package
        for it by naming the `implementation_plan_id`; a plan that has not
        reached `COMPLETED` is rejected with `ERR_PLAN_NOT_COMPLETED`".

        Design: Corner/errors/err_plan_not_completed_blocks_package
        """
        pipe = setup_plan(target_status="IN_EXECUTION", citation="PC-1", criticality="CRITICAL")
        resp = api.create_evidence_package(
            {"implementation_plan_id": pipe["plan"]["id"]},
            make_business_owner_headers(pipe["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_COMPLETED)


class TestArtifactConservation:
    def test_attach_remove_conserves_count(self, api):
        """PRD §3.8: "The package enters as `ASSEMBLING` with an empty `artifacts`
        list and an `artifact_count` of zero."
        PRD §3.8: "While the package is assembling, the owner attaches artifacts
        one at a time, each described by an `artifact_type` and a `uri`; the
        server mints an `artifact_id` for each item and stamps its `attached_at`
        with the logical clock, and a successful attachment answers 201. An
        artifact can be removed again by its `artifactId` while the package is
        still assembling — naming an unknown artifact identifier yields
        `ERR_NOT_FOUND`."

        Design: Difficulty/compensating_invariant/ci_artifact_attach_remove_conserves_count
        """
        pipe = setup_completed_plan_with_package(citation="CI-B")
        package, owner = pipe["package"], pipe["owner"]
        owner_headers = make_business_owner_headers(owner["id"])
        assert package["artifact_count"] == 0

        attached = validate_success(
            api.attach_artifact(package["id"], create_artifact_payload(), owner_headers), 201
        )
        assert attached["artifact_count"] == 1
        artifact_id = attached["artifacts"][0]["artifact_id"]
        assert artifact_id, "Server-minted artifact_id must be present"

        removed = validate_success(api.remove_artifact(package["id"], artifact_id, owner_headers), 200)
        assert removed["artifact_count"] == 0, "Attach/remove conserves the count exactly"
        assert removed["artifacts"] == []

    def test_seal_with_conserved_zero_count_rejected(self, api, manager_1_headers):
        """PRD §3.8: "Sealing is a `ComplianceManager` action with two
        preconditions: the package must still stand `ASSEMBLING`
        (`ERR_PACKAGE_SEALED` otherwise), and it must hold at least one artifact
        (`ERR_NO_ARTIFACTS`)."

        Design: Difficulty/compensating_invariant/ci_artifact_attach_remove_conserves_count
        """
        pipe = setup_completed_plan_with_package(citation="CI-B2")
        package, owner = pipe["package"], pipe["owner"]
        owner_headers = make_business_owner_headers(owner["id"])
        attached = validate_success(
            api.attach_artifact(package["id"], create_artifact_payload(), owner_headers), 201
        )
        api.remove_artifact(package["id"], attached["artifacts"][0]["artifact_id"], owner_headers)
        resp = api.seal_evidence_package(package["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ARTIFACTS)
        data = validate_success(api.get_evidence_package(package["id"], manager_1_headers))
        assert data["status"] == "ASSEMBLING"


class TestSealedImmutability:
    def test_sealed_package_immutable(self, api, manager_1_headers):
        """PRD §3.8: "Both attachment and removal are rejected with
        `ERR_PACKAGE_SEALED` once the package has left `ASSEMBLING`".
        PRD §3.8: "the package must still stand `ASSEMBLING` (`ERR_PACKAGE_SEALED`
        otherwise)".

        Design: Corner/state_machines/sm_sealed_package_immutable
        """
        pipe = setup_completed_plan_with_package(citation="SM-8", attach_artifact=True)
        package, owner = pipe["package"], pipe["owner"]
        seal = api.seal_evidence_package(package["id"], manager_1_headers)
        assert seal.status_code == 200, f"Setup failed: {seal.text}"

        resp = api.seal_evidence_package(package["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_SEALED)
        resp = api.attach_artifact(
            package["id"], create_artifact_payload(artifact_type="OTHER", uri="s3://ev/late.pdf"),
            make_business_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_SEALED)
        data = validate_success(api.get_evidence_package(package["id"], manager_1_headers))
        assert data["artifact_count"] == 1


class TestSealClosureCascade:
    def test_seal_verifies_plan(self, api, manager_1_headers):
        """PRD §3.8: "Sealing stamps `sealed_at` with the clock, renders the
        package immutable, and fires the two-link closure cascade. First, the
        plan behind the package moves from `COMPLETED` to `VERIFIED` with its
        `verification_evidence_id` pointing at the sealed package."

        Design: Difficulty/transitive_cascade/tc_seal_verified_closure_chain
        """
        pipe = setup_completed_plan_with_package(citation="TC-2", attach_artifact=True)
        package = pipe["package"]
        resp = api.seal_evidence_package(package["id"], manager_1_headers)
        sealed = validate_success(resp, 200)
        assert sealed["status"] == "SEALED"
        assert parse_iso(sealed["sealed_at"]) == parse_iso("2026-08-01T00:00:00Z")
        plan = get_plan(pipe["plan"]["id"])
        assert plan["execution_status"] == "VERIFIED"
        assert plan["verification_evidence_id"] == package["id"]

    def test_seal_closes_change_when_all_plans_verified(self, api, manager_1_headers):
        """PRD §3.8: "Second, closure is re-evaluated for the plan's regulatory
        change: when every `ACTIVE` obligation introduced by that change has at
        least one implementation plan, and none of those obligations' plans
        remains in `DRAFT`, `SUBMITTED`, `REJECTED`, `APPROVED`, `IN_EXECUTION`,
        or `COMPLETED` — that is, every one of their plans has reached `VERIFIED`
        — the change itself moves from `TRIAGED_APPLICABLE` to its terminal
        `CLOSED` state."

        Design: Difficulty/transitive_cascade/tc_seal_verified_closure_chain
        """
        pipe = setup_completed_plan_with_package(citation="TC-2C", attach_artifact=True)
        assert get_change(pipe["change"]["id"])["status"] == "TRIAGED_APPLICABLE"
        seal = api.seal_evidence_package(pipe["package"]["id"], manager_1_headers)
        assert seal.status_code == 200, f"Setup failed: {seal.text}"
        change = get_change(pipe["change"]["id"])
        assert change["status"] == "CLOSED", "Bubble-up closure: the single obligation's only plan is VERIFIED"
