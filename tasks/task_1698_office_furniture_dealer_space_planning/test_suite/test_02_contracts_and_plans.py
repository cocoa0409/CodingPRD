"""Pricing contracts and space plans: activation, SoD, amendment, revision."""
from test_helpers import (
    ApiErrorId,
    create_pricing_contract_payload,
    fixtures as fx,
    make_contracts_officer_headers,
    validate_error,
    validate_success,
    AE,
    ADMIN,
    APPROVER,
    CO,
    DESIGNER,
    REP,
    USER_CONTRACTS_OFFICER_2,
)

CO2 = make_contracts_officer_headers(USER_CONTRACTS_OFFICER_2)


class TestContractActivation:
    def test_contract_double_activate_rejected(self, api):
        """PRD section 3.3: "On activation the server records
        `activated_by_user_id`, the contract moves from `DRAFT` to `ACTIVE`" —
        no activation transition exists from `ACTIVE`.
        PRD section 2.8: "(4) the target resource being in a state from which
        the requested transition exists", else ERR_INVALID_STATE (HTTP 409 per
        the section 5 catalogue).

        Design: Corner/state_machines/contract_double_activate_rejected
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        fx.activate_contract(ctx.contract["id"])
        resp = api.activate_contract(ctx.contract["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_sod_contract_activate_by_creator_rejected(self, api):
        """PRD section 3.3: "the activator must differ from the creator recorded
        in `created_by_user_id` (a match is rejected with `ERR_SOD_VIOLATION`,
        enforcing segregation of duties)".

        Design: Corner/validations/sod_contract_activate_by_creator_rejected
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        # The creator's user id presented under the ContractsOfficer role.
        resp = api.activate_contract(
            ctx.contract["id"], make_contracts_officer_headers(ctx.contract["created_by_user_id"])
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        ok = api.activate_contract(ctx.contract["id"], CO)
        assert validate_success(ok)["status"] == "ACTIVE"

    def test_pricing_violation_tier_over_55_rejected(self, api):
        """PRD section 3.3: "every tier's `discount_pct` and the
        `default_discount_pct` must each be at most the maximum permitted
        discount of 55 percent (any excess is rejected with
        `ERR_CONTRACT_PRICING_VIOLATION`)".

        Design: Corner/validations/pricing_violation_tier_over_55_rejected
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        contract = fx.create_contract(
            ctx.customer["id"],
            {
                "pricing_tiers": [
                    {"category": "SEATING", "min_qty": 1, "discount_pct": 60}
                ]
            },
        )
        resp = api.activate_contract(contract["id"], CO)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_PRICING_VIOLATION)


class TestContractAmendment:
    def test_amend_creates_successor_and_activation_supersedes(self, api):
        """PRD section 3.3: "A successful amendment increments the amended
        contract's `version` by one and creates a successor contract in `DRAFT`
        whose `supersedes_contract_id` names the amended contract and whose
        unspecified fields are copied from it; the amended contract itself
        remains `ACTIVE` until that successor activates." and "when the contract
        names a `supersedes_contract_id` whose predecessor is currently `ACTIVE`
        — that predecessor automatically transitions to `SUPERSEDED`."

        Design: Corner/endpoints/amend_creates_successor_and_activation_supersedes
        """
        ctx = fx.setup_catalog(approve_plan=False)
        k_v = ctx.contract["version"]
        successor = validate_success(
            api.amend_contract(
                ctx.contract["id"],
                {"expected_contract_version": k_v, "default_discount_pct": 35},
                CO,
            ),
            201,
        )
        assert successor["status"] == "DRAFT"
        assert successor["supersedes_contract_id"] == ctx.contract["id"]
        assert successor["default_discount_pct"] == 35
        original = validate_success(api.get_pricing_contract(ctx.contract["id"], CO))
        assert original["status"] == "ACTIVE"
        validate_success(api.activate_contract(successor["id"], CO2))
        original_after = validate_success(api.get_pricing_contract(ctx.contract["id"], CO))
        assert original_after["status"] == "SUPERSEDED"

    def test_occ_contract_amend_stale_rejected(self, api):
        """PRD section 2.6: "A request to create an amendment (a successor draft
        contract) against an existing `PricingContract` must carry
        `expected_contract_version` equal to the contract's current `version`.
        If another writer has advanced the contract's `version` since the client
        last read it, the amendment is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/complexity_layers/occ_contract_amend_stale_rejected
        """
        ctx = fx.setup_catalog(approve_plan=False)
        k_v = ctx.contract["version"]
        first = validate_success(
            api.amend_contract(
                ctx.contract["id"],
                {"expected_contract_version": k_v, "default_discount_pct": 35},
                CO,
            ),
            201,
        )
        assert first["id"]
        resp = api.amend_contract(
            ctx.contract["id"],
            {"expected_contract_version": k_v, "default_discount_pct": 32},
            CO,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_contract_expiry_sweep_on_clock_set(self, api):
        """PRD section 2.7: "Setting the clock via the admin-only test-driving
        capability advances it to a supplied `to_iso8601` instant and triggers
        two automatic sweeps: any `PricingContract` in `ACTIVE` whose
        `effective_to` date is earlier than the new current UTC date transitions
        to `EXPIRED`".

        Design: Corner/endpoints/contract_expiry_sweep_on_clock_set
        """
        ctx = fx.setup_catalog(
            approve_plan=False,
            contract_overrides={"pricing_tiers": [], "effective_to": "2026-08-10"},
        )
        assert ctx.contract["status"] == "ACTIVE"
        fx.set_clock("2026-08-11T00:00:00Z")
        after = validate_success(api.get_pricing_contract(ctx.contract["id"], CO))
        assert after["status"] == "EXPIRED"


class TestSpacePlanLifecycle:
    def test_plan_approve_supersedes_predecessor(self, api):
        """PRD section 3.3: "If the approved plan names a `supersedes_plan_id`
        whose predecessor is currently `APPROVED`, the predecessor automatically
        transitions to `SUPERSEDED`."

        Design: Corner/state_machines/plan_approve_supersedes_predecessor
        """
        ctx_deal = fx.create_dealership()
        customer = fx.create_customer(ctx_deal["id"])
        plan_a, _t = fx.create_approved_plan(
            customer["id"], {"name": "HQ v1"}, {"code": "WS-A"}
        )
        plan_b, _t2 = fx.create_approved_plan(
            customer["id"],
            {"name": "HQ v2", "supersedes_plan_id": plan_a["id"]},
            {"code": "WS-A"},
        )
        assert plan_b["status"] == "APPROVED"
        plan_a_after = validate_success(api.get_space_plan(plan_a["id"], DESIGNER))
        assert plan_a_after["status"] == "SUPERSEDED"

    def test_typical_patch_rejected_when_plan_approved(self, api):
        """PRD section 3.3: "Typicals may be added while the plan is `DRAFT` or
        `IN_REVISION`, and an existing typical's `quantity` or
        `target_budget_cents_per_instance` may be edited in those same states" —
        an edit against an `APPROVED` plan targets a state from which the
        transition does not exist (PRD section 2.8 rule 4), rejected with
        ERR_INVALID_STATE (HTTP 409 per the section 5 catalogue).

        Design: Corner/entities/typical_patch_rejected_when_plan_approved
        """
        ctx_deal = fx.create_dealership()
        customer = fx.create_customer(ctx_deal["id"])
        plan, typical = fx.create_approved_plan(customer["id"])
        assert plan["status"] == "APPROVED"
        resp = api.patch_typical(typical["id"], {"quantity": 6}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSpacePlanRevisionCycle:
    def test_spaceplan_revision_cycle_revise_opens_revision(self, api):
        """PRD section 3.3: "A `Designer` may send an `APPROVED` plan back into
        `IN_REVISION` to start a new cycle: the `revision_no` increments by one,
        `approved_version` is cleared to null, and typicals become editable
        again."

        Design: Difficulty/non_linear_state_machine/spaceplan_revision_cycle
        """
        ctx_deal = fx.create_dealership()
        customer = fx.create_customer(ctx_deal["id"])
        plan, _typical = fx.create_approved_plan(customer["id"])
        assert plan["approved_version"] == plan["version"]
        revised = validate_success(api.revise_plan(plan["id"], DESIGNER))
        assert revised["status"] == "IN_REVISION"
        assert revised["revision_no"] == plan["revision_no"] + 1
        assert revised.get("approved_version") is None

    def test_spaceplan_revision_cycle_repins_approved_version(self, api):
        """PRD section 3.3: "The plan then cycles back through submit and
        approval." and "approving a `SUBMITTED` plan moves it to `APPROVED` and
        pins `approved_version` to the plan's current `version`, which becomes
        the version-pinning anchor for later order submit and acknowledgment."
        PRD section 3.3: "every such edit recomputes the plan's `budget_cents`
        and increments the plan's `version`."

        Design: Difficulty/non_linear_state_machine/spaceplan_revision_cycle
        """
        ctx_deal = fx.create_dealership()
        customer = fx.create_customer(ctx_deal["id"])
        plan, typical = fx.create_approved_plan(customer["id"])
        first_pin = plan["approved_version"]
        validate_success(api.revise_plan(plan["id"], DESIGNER))
        validate_success(api.patch_typical(typical["id"], {"quantity": 12}, DESIGNER))
        validate_success(api.submit_plan(plan["id"], DESIGNER))
        reapproved = validate_success(api.approve_plan(plan["id"], APPROVER))
        assert reapproved["status"] == "APPROVED"
        assert reapproved["approved_version"] == reapproved["version"]
        assert reapproved["approved_version"] != first_pin


class TestVersionPinningAtAcknowledge:
    def test_version_pin_ack_blocked_after_plan_revision(self, api):
        """PRD section 3.4: "the `pinned_plan_version` must equal the plan's
        `approved_version` with the plan still `APPROVED`, else
        `ERR_PLAN_SUPERSEDED`." Revising the plan clears `approved_version` to
        null (PRD section 3.3), so the pin can no longer match.

        Design: Corner/complexity_layers/version_pin_ack_blocked_after_plan_revision
        """
        ctx = fx.setup_submitted_order()
        validate_success(api.revise_plan(ctx.plan["id"], DESIGNER))
        resp = api.acknowledge_order(ctx.order["id"], REP)
        validate_error(resp, ApiErrorId.ERR_PLAN_SUPERSEDED)

    def test_version_pin_ack_blocked_after_contract_amend(self, api):
        """PRD section 3.4: "the `pinned_contract_version` must equal the
        contract's current `version` and the contract must still be `ACTIVE`,
        else `ERR_CONTRACT_NOT_EFFECTIVE`". Activating the amendment successor
        moves the pinned contract to `SUPERSEDED` (PRD section 3.3).

        Design: Corner/complexity_layers/version_pin_ack_blocked_after_contract_amend
        """
        ctx = fx.setup_submitted_order()
        successor = validate_success(
            api.amend_contract(
                ctx.contract["id"],
                {
                    "expected_contract_version": ctx.contract["version"],
                    "default_discount_pct": 35,
                },
                CO,
            ),
            201,
        )
        validate_success(api.activate_contract(successor["id"], CO2))
        resp = api.acknowledge_order(ctx.order["id"], REP)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EFFECTIVE)
