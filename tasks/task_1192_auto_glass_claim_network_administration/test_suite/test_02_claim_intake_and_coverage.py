"""Claim intake, provisional responsibility, coverage verification, supplements."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    assert_claim,
    create_claim_payload,
    make_policyholder_headers,
    make_regulation, make_policyholder, make_policy,
    make_claim, verify_claim, get_claim,
    setup_network, setup_claim_verified,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestClaimIntake:
    def test_claim_intake_sets_policyholder_from_header(self, api):
        """PRD §3.2: "The filing policyholder's identity is captured from the
        caller: the claim's `policyholder_id` is set from `X-User-ID`."

        Design: Corner/entities/claim_intake_sets_policyholder_from_header
        """
        net = setup_network(with_shop=False, with_part=False)
        resp = api.create_claim(
            create_claim_payload(net["policy"]["id"],
                                 estimated_repair_cost_cents=80000),
            make_policyholder_headers(net["policyholder"]["id"]))
        data = validate_success(resp, 201)
        assert_claim(data)
        assert data["policyholder_id"] == net["policyholder"]["id"]

    def test_claim_initial_state_submitted(self, api):
        """PRD §3.2: "Otherwise the claim begins life in `SUBMITTED`."

        Design: Corner/state_machines/claim_initial_state_submitted
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        assert claim["status"] == "SUBMITTED"
        assert claim["version"] == 1


class TestDeductibleDetermination:
    def test_deductible_state_cap_applied(self, api):
        """PRD §3.2: "The effective deductible starts as the policy's
        `deductible_cents` and is reduced to the state cap whenever the state
        sets one — that is, the effective deductible is the smaller of
        `deductible_cents` and `max_deductible_cents` whenever the latter is not
        null."

        Design: Corner/calculations/deductible_state_cap_applied
        """
        net = setup_network(state_code="SC", zero_deductible_windshield=True,
                            max_deductible_cents=25000, tax_bp=600,
                            deductible_cents=100000,
                            with_shop=False, with_part=False)
        resp = api.create_claim(
            create_claim_payload(net["policy"]["id"], incident_state_code="SC",
                                 service_zip_code="29201",
                                 part_category="SIDE_GLASS",
                                 estimated_repair_cost_cents=40000),
            make_policyholder_headers(net["policyholder"]["id"]))
        claim = validate_success(resp, 201)
        # min(min(100000, 25000 cap), 40000 estimate) = 25000
        assert claim["provisional_customer_responsibility_cents"] == 25000
        verified = verify_claim(claim["id"])
        # SIDE_GLASS never triggers the zero-deductible rule; the cap wins.
        assert verified["deductible_applied_cents"] == 25000

    def test_zero_deductible_only_for_windshield(self, api):
        """PRD §3.2: "The zero-deductible rule applies when all three conditions
        hold: the regulation's `zero_deductible_windshield` is true, the claim's
        `part_category` is `WINDSHIELD`, and the policy's `coverage_type` is
        `COMPREHENSIVE`."

        Design: Corner/calculations/zero_deductible_only_for_windshield
        """
        net = setup_network(state_code="FL", zero_deductible_windshield=True,
                            tax_bp=0, deductible_cents=30000,
                            with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           part_category="REAR_GLASS",
                           estimated_repair_cost_cents=50000)
        # REAR_GLASS: rule does not fire, provisional = min(30000, 50000).
        assert claim["provisional_customer_responsibility_cents"] == 30000
        verified = verify_claim(claim["id"])
        assert verified["deductible_applied_cents"] == 30000


class TestVerifyCoverage:
    def test_verify_coverage_from_non_submitted_rejected(self, api):
        """PRD §3.2: "Verification requires the claim to be `SUBMITTED` (else
        `ERR_CLAIM_NOT_SUBMITTED`, HTTP 409)..."

        Design: Corner/state_machines/verify_coverage_from_non_submitted_rejected
        """
        ctx = setup_claim_verified(with_shop=False, with_part=False)
        resp = api.verify_coverage(ctx["claim"]["id"], {}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
        assert get_claim(ctx["claim"]["id"])["status"] == "COVERAGE_VERIFIED"

    def test_rbac_policyholder_cannot_verify_coverage(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_policyholder_cannot_verify_coverage
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        resp = api.verify_coverage(
            claim["id"], {}, make_policyholder_headers(net["policyholder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_claim(claim["id"])["status"] == "SUBMITTED"


class TestClaimTerminalDenial:
    def test_claim_terminal_denied_lockdown(self, api):
        """PRD §3.2: "The filing policyholder remains free to cancel their own
        claim while it is `SUBMITTED`, `COVERAGE_VERIFIED`, or `WORK_AUTHORIZED`
        — any other state is rejected with `ERR_CLAIM_NOT_CANCELLABLE`..."
        PRD §3.2: "Verification requires the claim to be `SUBMITTED` (else
        `ERR_CLAIM_NOT_SUBMITTED`, HTTP 409)..."

        Design: Corner/state_machines/claim_terminal_denied_lockdown
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        resp = api.deny_claim(claim["id"], {"denial_reason": "not covered"}, ADJUSTER)
        assert validate_success(resp, 200)["status"] == "DENIED"
        cancel = api.cancel_claim(
            claim["id"], {}, make_policyholder_headers(net["policyholder"]["id"]))
        validate_error(cancel, ApiErrorId.ERR_CLAIM_NOT_CANCELLABLE)
        verify = api.verify_coverage(claim["id"], {}, ADJUSTER)
        validate_error(verify, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
        assert get_claim(claim["id"])["status"] == "DENIED"


class TestClaimOwnership:
    def test_ownership_mismatch_policyholder_cancels_others_claim(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        Policyholder compare the resource's foreign-key field — for example a
        claim's `policyholder_id` — to `X-User-ID`, and a mismatch is rejected
        with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/ownership_mismatch_policyholder_cancels_others_claim
        """
        make_regulation("FL")
        pa = make_policyholder(full_name="Owner A", email="oa@x.com")
        pb = make_policyholder(full_name="Owner B", email="ob@x.com")
        pol_a = make_policy(pa["id"])
        claim = make_claim(pa, pol_a, estimated_repair_cost_cents=80000)
        resp = api.cancel_claim(claim["id"], {}, make_policyholder_headers(pb["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP_MISMATCH)
        assert get_claim(claim["id"])["status"] == "SUBMITTED"


class TestVersionIncrement:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` (integer): A system-managed integer that
        increments by one with every modification to the resource, including
        server-initiated cascade mutations."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        net = setup_network(state_code="AZ", tax_bp=560, with_shop=False,
                            with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           incident_state_code="AZ", service_zip_code="85001",
                           estimated_repair_cost_cents=80000)
        assert claim["version"] == 1
        v2 = verify_claim(claim["id"])
        assert v2["version"] == 2
        resp = api.supplement_claim(
            claim["id"],
            {"additional_damage_description": "more",
             "revised_estimated_repair_cost_cents": 90000},
            make_policyholder_headers(net["policyholder"]["id"]))
        v3 = validate_success(resp, 200)
        assert v3["version"] == 3
        v4 = verify_claim(claim["id"])
        assert v4["version"] == 4
        assert v4["updated_at"] >= v3["updated_at"] >= v2["updated_at"]


class TestImmediateConsistency:
    def test_immediate_visibility_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_visibility_in_same_response
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        resp = api.verify_coverage(claim["id"], {}, ADJUSTER)
        data = validate_success(resp, 200)
        assert data["status"] == "COVERAGE_VERIFIED"
        assert data["deductible_applied_cents"] == 50000
        reread = get_claim(claim["id"])
        assert reread["status"] == "COVERAGE_VERIFIED"
        assert reread["deductible_applied_cents"] == 50000


# ---------------------------------------------------------------------------
# Difficulty: supplement re-verify cycle
# ---------------------------------------------------------------------------

class TestClaimSupplementReverifyCycle:
    def _setup_verified(self):
        net = setup_network(state_code="AZ", tax_bp=560, with_shop=False,
                            with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           incident_state_code="AZ", service_zip_code="85001",
                           estimated_repair_cost_cents=40000)
        verified = verify_claim(claim["id"])
        assert verified["deductible_applied_cents"] == 50000
        return net, claim

    def _supplement(self, net, claim):
        from test_helpers import api_client
        return api_client.supplement_claim(
            claim["id"],
            {"additional_damage_description": "more damage found",
             "revised_estimated_repair_cost_cents": 90000},
            make_policyholder_headers(net["policyholder"]["id"]))

    def test_supplement_reopens_and_resets_deductible_basis(self, api):
        """PRD §3.2: "The supplement moves the claim `COVERAGE_VERIFIED` →
        `SUBMITTED`: the intake estimate is replaced by the revised figure, the
        provisional customer responsibility is recomputed from it, and the stored
        `deductible_applied_cents` is reset to null until the adjuster verifies
        coverage again."

        Design: Difficulty/non_linear_state_machine/claim_supplement_reverify_cycle
        """
        net, claim = self._setup_verified()
        resp = self._supplement(net, claim)
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED"
        assert data["estimated_repair_cost_cents"] == 90000
        assert data["provisional_customer_responsibility_cents"] == 50000
        assert data["deductible_applied_cents"] is None

    def test_reverify_after_supplement_restores_final_basis(self, api):
        """PRD §3.2: "This revision loop re-opens a verified claim for
        re-verification as many times as needed."
        PRD §3.2: "On success the claim moves `SUBMITTED` → `COVERAGE_VERIFIED`;
        the final deductible basis is stored in `deductible_applied_cents` as
        zero under the zero-deductible rule and as the effective deductible
        otherwise..."

        Design: Difficulty/non_linear_state_machine/claim_supplement_reverify_cycle
        """
        net, claim = self._setup_verified()
        validate_success(self._supplement(net, claim), 200)
        reverified = verify_claim(claim["id"])
        assert reverified["status"] == "COVERAGE_VERIFIED"
        assert reverified["deductible_applied_cents"] == 50000
        # create 1, verify 2, supplement 3, verify 4
        assert reverified["version"] == 4


# ---------------------------------------------------------------------------
# Difficulty: claim verify depends on policy state
# ---------------------------------------------------------------------------

class TestClaimVerifyDependsOnPolicyState:
    def _setup(self):
        make_regulation("FL")
        ph = make_policyholder(full_name="Xdep One", email="xd1@x.com")
        pol_act = make_policy(ph["id"], policy_number="PN-XD-A")
        pol_liab = make_policy(ph["id"], policy_number="PN-XD-L",
                               coverage_type="LIABILITY")
        claim_ok = make_claim(ph, pol_act, estimated_repair_cost_cents=80000)
        claim_liab = make_claim(ph, pol_liab, estimated_repair_cost_cents=80000)
        return claim_ok, claim_liab

    def test_liability_policy_claim_rejected(self, api):
        """PRD §3.2: "Verification requires ... the policy's `coverage_type` to
        be `COMPREHENSIVE` (else `ERR_COVERAGE_TYPE_INELIGIBLE`, HTTP 422)..."

        Design: Difficulty/cross_entity_state_dependency/claim_verify_depends_on_policy_state
        """
        _ok, claim_liab = self._setup()
        resp = api.verify_coverage(claim_liab["id"], {}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_TYPE_INELIGIBLE)
        assert get_claim(claim_liab["id"])["status"] == "SUBMITTED"

    def test_comprehensive_active_policy_claim_verifies(self, api):
        """PRD §3.2: "On success the claim moves `SUBMITTED` →
        `COVERAGE_VERIFIED`; the final deductible basis is stored in
        `deductible_applied_cents`..."

        Design: Difficulty/cross_entity_state_dependency/claim_verify_depends_on_policy_state
        """
        claim_ok, _liab = self._setup()
        verified = verify_claim(claim_ok["id"])
        assert verified["status"] == "COVERAGE_VERIFIED"
        assert verified["deductible_applied_cents"] == 50000
