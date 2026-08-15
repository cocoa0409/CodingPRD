"""Clinical policy versioning, create-with-supersede, and the optimistic
concurrency guard on the drug policy lineage (PRD §2.7, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_clinical_policy_payload,
    create_drug,
    create_policy,
    create_provider,
    get_auth,
    get_drug_version,
    make_provider_rep_headers,
    setup_drug_with_policy,
    submit_auth,
    TEST_USERS,
    validate_error,
    validate_success,
)

MPO = TEST_USERS["mpo_headers"]


class TestPolicyOcc:
    def test_policy_create_with_stale_drug_version_rejected(self, api):
        """PRD §2.7: "If the presented value does not equal the drug's current `version`,
        the request is rejected with `ERR_STALE_DRUG_VERSION` (HTTP 412), and this check
        is evaluated before any business rule on the request."
        PRD §3.2: "Whenever a version becomes `ACTIVE`, whether atomically at creation or
        through later activation, the prior `ACTIVE` version for the same drug flips to
        `SUPERSEDED` in the same commit."

        Design: Corner/validations/occ_stale_version_rejected
        """
        drug = create_drug(j_code="J6200", drug_name="OccDrug")
        stale_version = drug["version"]

        # First create succeeds while the presented version is current.
        pol1 = create_policy(
            drug["id"], stale_version, covered_diagnoses=["C50"], status="ACTIVE"
        )
        assert pol1["status"] == "ACTIVE"
        assert pol1["version_no"] == 1, "per-drug version_no starts at 1 (PRD §3.2)"
        assert get_drug_version(drug["id"]) == stale_version + 1

        # Reusing the now-stale captured version is rejected with 412.
        resp = api.create_clinical_policy(
            create_clinical_policy_payload(
                drug["id"], stale_version, covered_diagnoses=["C51"]
            ),
            MPO,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DRUG_VERSION, 412)

        # Re-reading the drug and presenting the fresh version succeeds; the create
        # supersedes the prior ACTIVE policy and bumps the drug version again.
        pol2 = create_policy(
            drug["id"], get_drug_version(drug["id"]), covered_diagnoses=["C51"]
        )
        assert pol2["status"] == "ACTIVE"
        assert pol2["version_no"] == 2
        superseded = validate_success(api.get_clinical_policy(pol1["id"], MPO))
        assert superseded["status"] == "SUPERSEDED"
        assert get_drug_version(drug["id"]) == stale_version + 2

    def test_activate_active_policy_rejected(self, api, mpo_headers):
        """PRD §3.2: "Activation is refused unless the policy is `DRAFT`, failing with
        `ERR_POLICY_NOT_DRAFT`; per the pipeline of §2.8, the `expected_drug_version`
        check runs before that business rule and before every other business rule on the
        request."

        Design: Corner/state_machines/policy_activate_active_rejected
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J4500", "drug_name": "PolDrug"}, with_rate=False
        )
        drug_id = backbone["drug"]["id"]
        policy = backbone["policy"]
        assert policy["status"] == "ACTIVE"
        version_before = get_drug_version(drug_id)

        # OCC passes (fresh version), so the state gate is what fires.
        resp = api.activate_clinical_policy(
            policy["id"], {"expected_drug_version": version_before}, mpo_headers
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_DRAFT, 409)

        still = validate_success(api.get_clinical_policy(policy["id"], mpo_headers))
        assert still["status"] == "ACTIVE"
        assert get_drug_version(drug_id) == version_before, (
            "a failed activation must not bump the drug version"
        )


class TestApprovalPolicyGate:
    def test_approval_blocked_when_policy_only_draft(self, api):
        """PRD §3.4: "An `ACTIVE` clinical policy must exist for the drug, otherwise
        `ERR_NO_ACTIVE_POLICY`."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_clinical_policy_state
        """
        drug = create_drug(j_code="J3300", drug_name="GateDrugB")
        draft = create_policy(drug["id"], drug["version"], status="DRAFT")
        assert draft["status"] == "DRAFT"
        provider = create_provider(name="Gate Provider B")
        auth = submit_auth(
            drug["id"], provider["id"], "MEM-14", requested_dose_mg=100
        )

        resp = api.approve_auth(auth["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY, 409)
        assert get_auth(auth["id"])["status"] == "SUBMITTED"

    def test_approval_after_activation_pins_policy_version(self, api):
        """PRD §3.4: "The governing policy's identity is pinned onto the authorization as
        `policy_id` and `policy_version_no` — both null until approval".
        PRD §3.2: "Each new version receives the next per-drug sequential `version_no`,
        starting at 1".

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_clinical_policy_state
        """
        drug = create_drug(j_code="J3301", drug_name="GateDrugB2")
        draft = create_policy(drug["id"], drug["version"], status="DRAFT")
        provider = create_provider(name="Gate Provider B2")
        auth = submit_auth(
            drug["id"], provider["id"], "MEM-14B", requested_dose_mg=100
        )

        activated = validate_success(
            api.activate_clinical_policy(
                draft["id"], {"expected_drug_version": get_drug_version(drug["id"])}, MPO
            )
        )
        assert activated["status"] == "ACTIVE"

        approved = validate_success(
            api.approve_auth(auth["id"], {"max_administrations": 4}, MPO)
        )
        assert approved["status"] == "APPROVED"
        assert approved["policy_id"] == draft["id"]
        assert approved["policy_version_no"] == 1, "pinned version_no of the first policy"
        assert approved["administrations_used"] == 0
