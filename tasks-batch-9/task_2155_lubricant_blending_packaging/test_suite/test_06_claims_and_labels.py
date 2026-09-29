"""Approval claims, the label estate they gate, and the blocking cascade."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    confirm_order,
    create_active_claim,
    create_active_config,
    create_active_recipe,
    create_active_spec,
    create_config,
    create_customer,
    create_recipe,
    find_order_line,
    make_effective,
    open_order,
    read_claim,
    read_config,
    read_order,
    read_recipe,
    read_spec,
    set_clock,
    setup_active_formulation,
    setup_claim_blocked_configuration,
    setup_cleared_change_request,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]


class TestApprovalClaimCycle:
    def test_suspending_an_active_claim_flags_it_for_recertification(self, api):
        """PRD 3.6: "An approval moves the claim `SUBMITTED → ACTIVE`, stores the
        `licence_number`, clears `requires_recertification` back to false, and computes
        `valid_until` as the logical clock's current instant plus 730 calendar days."
        PRD 3.6: "`SUSPEND` moves an active claim `ACTIVE → SUSPENDED`, sets
        `requires_recertification` to true and records the supplied text into
        `suspension_reason`; the same `ACTIVE → SUSPENDED` hop is driven by the system as link 2
        of cascade A."

        Design: Difficulty/non_linear_state_machine/approval_claim_active_suspended_submitted_active_cycle
        """
        world = setup_active_formulation(with_lots=False)
        claim = create_active_claim(world["spec"]["id"], licence_number="API-1234")

        assert claim["status"] == "ACTIVE"
        assert claim["licence_number"] == "API-1234"
        assert claim["requires_recertification"] is False
        assert claim["valid_until"] == "2028-08-01T06:00:00.000Z"

        suspended = validate_success(
            api.approval_claim_lifecycle(
                claim["id"], {"action": "SUSPEND", "reason": "OEM audit finding"}, COMPLIANCE
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["requires_recertification"] is True

    def test_re_approval_returns_the_claim_to_active_and_restamps_its_licence(self, api):
        """PRD 3.6: "Submission is the act of sending the claim to the body, and it is reachable
        from two originating states: `DRAFT → SUBMITTED` for a first approval, and
        `SUSPENDED → SUBMITTED` for a re-approval after a specification change."
        PRD 3.6: "Both paths write `pinned_spec_revision` from the specification's current
        `revision`; on the re-approval path this re-pins the claim to the new revision, which is
        what closes the `ACTIVE → SUSPENDED → SUBMITTED → ACTIVE` cycle."
        PRD 3.6: "An approval moves the claim `SUBMITTED → ACTIVE`, stores the `licence_number`,
        clears `requires_recertification` back to false, and computes `valid_until` as the
        logical clock's current instant plus 730 calendar days."

        Design: Difficulty/non_linear_state_machine/approval_claim_active_suspended_submitted_active_cycle
        """
        world = setup_active_formulation(with_lots=False)
        claim = create_active_claim(world["spec"]["id"], licence_number="API-1234")
        validate_success(
            api.approval_claim_lifecycle(
                claim["id"], {"action": "SUSPEND", "reason": "OEM audit finding"}, COMPLIANCE
            )
        )

        resubmitted = validate_success(api.submit_approval_claim(claim["id"], COMPLIANCE))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["pinned_spec_revision"] == 1

        reapproved = validate_success(
            api.decide_approval_claim(
                claim["id"], {"decision": "APPROVE", "licence_number": "API-5678"}, COMPLIANCE
            )
        )
        assert reapproved["status"] == "ACTIVE"
        assert reapproved["licence_number"] == "API-5678"
        assert reapproved["requires_recertification"] is False
        assert reapproved["valid_until"] == "2028-08-01T06:00:00.000Z"

    def test_duplicate_claim_triple_is_refused_while_the_first_is_in_play(self, api):
        """PRD 3.6: "The combination of specification, `claim_body` and `claim_code` may be held
        by only one claim at a time that is still in play: if an existing claim on the same
        triple sits in `DRAFT`, `SUBMITTED`, `ACTIVE` or `SUSPENDED`, the create is refused with
        `ERR_DUPLICATE_CLAIM`."
        PRD 3.6: "Claims in `REJECTED` or `WITHDRAWN` do not block a new one."

        Design: Corner/validations/duplicate_approval_claim_triple_rejected
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        validate_success(
            api.create_approval_claim(
                {"product_spec_id": spec["id"], "claim_body": "API", "claim_code": "API SP"},
                COMPLIANCE,
            ),
            201,
        )

        response = api.create_approval_claim(
            {"product_spec_id": spec["id"], "claim_body": "API", "claim_code": "API SP"},
            COMPLIANCE,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)

        _, meta = validate_paginated(
            api.list_approval_claims(COMPLIANCE, {"product_spec_id": spec["id"]})
        )
        assert meta["total_count"] == 1

    def test_submission_requires_a_current_active_formulation(self, api):
        """PRD 3.6: "Both paths require the specification to be `ACTIVE`, or
        `ERR_SPEC_NOT_ACTIVE` applies, and both require the specification to carry at least one
        recipe that is `ACTIVE` **and** whose `spec_revision_pinned` equals the specification's
        current `revision` — a claim cannot be substantiated without a formulation that is
        actually current — or the submission is refused with `ERR_NO_ELIGIBLE_RECIPE`."
        PRD 3.6: "The claim opens in `DRAFT` with `pinned_spec_revision` null, `licence_number`
        null, `valid_until` null, `requires_recertification` false and `suspension_reason`
        null."

        Design: Corner/validations/claim_submit_without_active_recipe_returns_no_eligible_recipe
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        draft_recipe = create_recipe(spec["id"])
        claim = validate_success(
            api.create_approval_claim(
                {"product_spec_id": spec["id"], "claim_body": "ILSAC", "claim_code": "GF-6A"},
                COMPLIANCE,
            ),
            201,
        )

        refused = api.submit_approval_claim(claim["id"], COMPLIANCE)
        validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_RECIPE.value, 409)

        blocked = read_claim(claim["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["pinned_spec_revision"] is None

        validate_success(api.activate_blend_recipe(draft_recipe["id"], PM))
        submitted = validate_success(api.submit_approval_claim(claim["id"], COMPLIANCE))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["pinned_spec_revision"] == 1

    def test_claim_repins_to_the_new_revision_after_a_governed_change(self, api):
        """PRD 3.6: "Both paths write `pinned_spec_revision` from the specification's current
        `revision`; on the re-approval path this re-pins the claim to the new revision, which is
        what closes the `ACTIVE → SUSPENDED → SUBMITTED → ACTIVE` cycle."
        PRD 3.1: "Every approval claim on the specification whose status is `ACTIVE` and whose
        `pinned_spec_revision` is now behind the specification's `revision` moves
        `ACTIVE → SUSPENDED`, which in turn blocks the package configurations printing its claim
        code and puts their open order lines and confirmed orders on hold, as described in §3.6
        and §3.8."
        PRD 3.1: "Independently, every recipe on the specification whose status is `ACTIVE` and
        whose `spec_revision_pinned` is now behind the specification's `revision` moves
        `ACTIVE → RETIRED`."
        PRD 3.2: "The recipe is created in `DRAFT` and copies the specification's current
        `revision` into `spec_revision_pinned` at that moment."

        Design: Corner/cross_cutting_complexity_layers/claim_repins_to_the_new_spec_revision_on_resubmit
        """
        world = setup_active_formulation(with_lots=False)
        claim = create_active_claim(world["spec"]["id"], licence_number="API-1234")
        assert claim["pinned_spec_revision"] == 1

        request = setup_cleared_change_request(world["spec"]["id"])
        make_effective(request["id"])

        suspended = read_claim(claim["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["pinned_spec_revision"] == 1
        assert suspended["requires_recertification"] is True
        assert read_recipe(world["recipe"]["id"])["status"] == "RETIRED"

        fresh_recipe = create_active_recipe(world["spec"]["id"])
        assert fresh_recipe["spec_revision_pinned"] == 2
        assert fresh_recipe["status"] == "ACTIVE"

        resubmitted = validate_success(api.submit_approval_claim(claim["id"], COMPLIANCE))
        assert resubmitted["pinned_spec_revision"] == 2

        reapproved = validate_success(
            api.decide_approval_claim(
                claim["id"], {"decision": "APPROVE", "licence_number": "API-5678"}, COMPLIANCE
            )
        )
        assert reapproved["status"] == "ACTIVE"
        assert reapproved["requires_recertification"] is False


class TestLabelConfigurationGates:
    def test_configuration_activation_requires_every_printed_claim_to_be_active(self, api):
        """PRD 3.6: "Activation moves the configuration `DRAFT → ACTIVE` while the specification
        is `ACTIVE`, and every entry in `claim_codes` must match an approval claim on the same
        `product_spec_id` whose status is `ACTIVE`; otherwise the activation is refused with
        `ERR_CLAIM_NOT_ACTIVE`."
        PRD 3.6: "A `claim_codes` array lists the approval claim codes printed on the label and
        defaults to empty, which means the label carries no approval claim at all."

        Design: Corner/validations/claim_not_active_blocks_configuration_activation
        """
        world = setup_active_formulation(with_lots=False)
        claim = validate_success(
            api.create_approval_claim(
                {"product_spec_id": world["spec"]["id"], "claim_body": "API",
                 "claim_code": "API SP"},
                COMPLIANCE,
            ),
            201,
        )
        config = create_config(world["spec"]["id"], claim_codes=["API SP"])

        refused = api.activate_package_configuration(config["id"], PM)
        validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_ACTIVE.value, 422)
        assert read_config(config["id"])["status"] == "DRAFT"

        validate_success(api.submit_approval_claim(claim["id"], COMPLIANCE))
        approved = validate_success(
            api.decide_approval_claim(
                claim["id"], {"decision": "APPROVE", "licence_number": "API-1234"}, COMPLIANCE
            )
        )
        assert approved["status"] == "ACTIVE"

        activated = validate_success(api.activate_package_configuration(config["id"], PM))
        assert activated["status"] == "ACTIVE"

    def test_re_approving_the_claim_lifts_the_configuration_out_of_claim_blocked(self, api):
        """PRD 3.6: "It also repairs the label estate: every package configuration sitting in
        `CLAIM_BLOCKED` whose printed claim codes are now **all** carried by `ACTIVE` claims on
        the same specification moves `CLAIM_BLOCKED → ACTIVE`, advancing its own `version`."
        PRD 3.6: "A configuration that has been blocked returns to service only through the
        claim-repair path described above, moving `CLAIM_BLOCKED → ACTIVE` once every one of its
        printed claim codes is again matched by an `ACTIVE` claim on the same specification."
        PRD 3.6: "Whenever a claim leaves `ACTIVE` — by suspension, whether operator-driven or
        cascade-driven, or by withdrawal directly from `ACTIVE` — every package configuration
        whose `claim_codes` array contains that claim's `claim_code` and whose status is
        `ACTIVE` moves `ACTIVE → CLAIM_BLOCKED`."

        Design: Corner/state_machines/claim_approval_restores_claim_blocked_configuration
        """
        world = setup_claim_blocked_configuration()
        assert world["config"]["status"] == "CLAIM_BLOCKED"
        assert world["claim"]["status"] == "SUSPENDED"

        validate_success(api.submit_approval_claim(world["claim"]["id"], COMPLIANCE))
        reapproved = validate_success(
            api.decide_approval_claim(
                world["claim"]["id"],
                {"decision": "APPROVE", "licence_number": "API-5678"},
                COMPLIANCE,
            )
        )
        assert reapproved["status"] == "ACTIVE"
        assert reapproved["requires_recertification"] is False

        assert read_config(world["config"]["id"])["status"] == "ACTIVE"

    def test_activating_a_blocked_configuration_is_decided_on_its_own_state(self, api):
        """PRD 2.6: "Every check in the system occupies a fixed rung, and the rungs are evaluated
        in strictly ascending order; the **first** check that fails decides the response and no
        later check is consulted."
        PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."
        PRD 2.6: "30. Claim set integrity — every printed claim code on the configuration
        matches an `ACTIVE` claim on the same specification; otherwise `ERR_CLAIM_NOT_ACTIVE`
        (422). Guards package-configuration activation."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_claim_not_active_on_configuration_activate
        """
        world = setup_claim_blocked_configuration()

        response = api.activate_package_configuration(world["config"]["id"], PM)
        error = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_CLAIM_NOT_ACTIVE.value

    def test_refused_reactivation_leaves_the_label_estate_untouched(self, api):
        """PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."
        PRD 3.6: "Whenever a claim leaves `ACTIVE` — by suspension, whether operator-driven or
        cascade-driven, or by withdrawal directly from `ACTIVE` — every package configuration
        whose `claim_codes` array contains that claim's `claim_code` and whose status is
        `ACTIVE` moves `ACTIVE → CLAIM_BLOCKED`."
        PRD 3.6: "A configuration that has been blocked returns to service only through the
        claim-repair path described above, moving `CLAIM_BLOCKED → ACTIVE` once every one of its
        printed claim codes is again matched by an `ACTIVE` claim on the same specification."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_claim_not_active_on_configuration_activate
        """
        world = setup_claim_blocked_configuration()

        response = api.activate_package_configuration(world["config"]["id"], PM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        assert read_config(world["config"]["id"])["status"] == "CLAIM_BLOCKED"
        assert read_claim(world["claim"]["id"])["status"] == "SUSPENDED"


class TestCascadeVisibility:
    def test_suspending_a_claim_blocks_the_label_and_holds_the_order_immediately(self, api):
        """PRD 2.9: "Where one operation mutates more than one entity, the secondary effects are
        as binding as the primary one."
        PRD 3.6: "Whenever a claim leaves `ACTIVE` — by suspension, whether operator-driven or
        cascade-driven, or by withdrawal directly from `ACTIVE` — every package configuration
        whose `claim_codes` array contains that claim's `claim_code` and whose status is
        `ACTIVE` moves `ACTIVE → CLAIM_BLOCKED`."
        PRD 3.8: "Line-level holds are always system-driven: an `OPEN` line moves
        `OPEN → HOLD` exactly when the configuration it references has become `CLAIM_BLOCKED` or
        `SUPERSEDED`."
        PRD 3.8: "The same `CONFIRMED → HOLD` hop is driven by the system as link 4 of cascade
        A, with `hold_reason` set to `CLAIM_BLOCKED_LINE`, whenever an order line on a confirmed
        order is put on hold because the configuration it quotes stopped being `ACTIVE`."

        Design: Corner/consistency_model/cascade_results_are_visible_in_the_triggering_response
        """
        set_clock(CLOCK_BASE)
        customer = create_customer(takeback_agreement_status="ACTIVE")
        spec = create_active_spec()
        create_active_recipe(spec["id"])
        claim = create_active_claim(spec["id"], licence_number="API-1234")
        config = create_active_config(
            spec["id"],
            package_type="PAIL_20L",
            label_brand="Bravo Blue",
            fill_volume_l=20.0,
            private_label=True,
            customer_id=customer["id"],
            claim_codes=["API SP"],
        )
        order = open_order(customer["id"])
        line = add_order_line(order["id"], config["id"], 37)
        confirm_order(order["id"])

        suspended = validate_success(
            api.approval_claim_lifecycle(
                claim["id"], {"action": "SUSPEND", "reason": "OEM audit finding"}, COMPLIANCE
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["requires_recertification"] is True

        assert read_config(config["id"])["status"] == "CLAIM_BLOCKED"
        assert find_order_line(order["id"], line["id"])["status"] == "HOLD"

        held_order = read_order(order["id"])
        assert held_order["status"] == "HOLD"
        assert held_order["hold_reason"] == "CLAIM_BLOCKED_LINE"
