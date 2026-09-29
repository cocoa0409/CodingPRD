"""Gates that read a different entity than the one being moved.

A contract cannot be filed until the firm's credentials are in order in every
one of its states, and a promotion cannot be activated while a cease order is
live in a state the promotion never mentions.
"""

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    activate_promotion,
    api_client,
    approve_filing,
    attach_required_documents,
    create_financial_statement,
    create_fundraiser,
    create_officer_pair,
    create_organization,
    decide_action,
    draft_contract,
    file_contract,
    make_fundraiser_agent_headers,
    move_clock_to,
    open_filing,
    read_contract,
    read_organization,
    read_promotion,
    read_registration,
    register_fundraiser_in_state,
    remediate_action,
    run_sweep,
    seed_california_profile,
    seed_state_profile,
    setup_filed_promotion,
    submit_filing,
    vacate_action,
    validate_error,
    validate_paginated,
    validate_success,
)

DECEMBER_WINDOW = {
    "promo_start": "2026-12-01T00:00:00Z",
    "promo_end": "2026-12-31T00:00:00Z",
}


def _first_action_for(registration_id: str):
    actions, _meta = validate_paginated(
        api_client.list_enforcement_actions(
            COMPLIANCE, params={"registration_id": registration_id}
        )
    )
    assert actions, f"Expected an enforcement action on filing {registration_id}"
    return actions[0]


class TestContractRequiresCredentialsInEveryState:
    """The gate is per element of the contract's state array."""

    def _two_state_contract(self):
        seed_california_profile(
            fundraiser_contract_filing_days=10, fundraiser_bond_minimum_cents=2_500_000
        )
        seed_state_profile(
            "FL",
            renewal_due_rule="FYE_PLUS_6M",
            assurance_basis="GROSS_REVENUE",
            fundraiser_contract_filing_days=15,
            fundraiser_bond_minimum_cents=2_500_000,
        )
        organization = create_organization(domicile_state_code="CA")
        fundraiser = create_fundraiser(
            legal_name="Northline Donor Services",
            fundraiser_type="PROFESSIONAL_SOLICITOR",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        register_fundraiser_in_state(
            fundraiser["id"],
            "CA",
            bond_on_file_cents=2_500_000,
            expires_at="2027-12-31T00:00:00Z",
        )
        contract = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA", "FL"],
            contract_start="2026-08-01T00:00:00Z",
            contract_end="2027-08-01T00:00:00Z",
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )
        return fundraiser, contract

    def test_one_missing_state_credential_blocks_a_two_state_contract(self):
        """PRD §3.6: "Every state in `state_codes` must have an `ACTIVE` registration
        for this firm, or it reports `ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE`." The
        deadline comes from the strictest state: "`filing_due_date` is
        `contract_start` plus the **smallest** `fundraiser_contract_filing_days`
        among the states listed in `state_codes`, counted in whole days."

        Design: Difficulty/cross_entity_state_dependency/contract_file_requires_active_registration_in_every_contract_state
        """
        fundraiser, contract = self._two_state_contract()

        assert contract["filing_due_date"] == "2026-08-11T00:00:00.000Z", (
            "Ten days is smaller than fifteen, so California's window governs, got "
            f"{contract['filing_due_date']}"
        )

        response = api_client.file_fundraising_contract(
            contract["id"], {}, make_fundraiser_agent_headers(fundraiser["id"])
        )

        validate_error(
            response, ApiErrorId.ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE.value
        )
        stored = read_contract(contract["id"])
        assert stored["status"] == "DRAFT", (
            f"The contract is not filed, got {stored['status']}"
        )
        assert stored["filed_at"] is None, (
            f"Nothing was stamped, got {stored['filed_at']}"
        )

    def test_registering_the_second_state_lets_the_identical_call_succeed(self):
        """PRD §3.6: "A clock at or before `filing_due_date` drives `DRAFT` →
        `FILED`, stamps `filed_at` with the current logical clock, and sets
        `late_filing_surcharge_cents` to 0." A new state registration "is born
        `ACTIVE` and immediately refreshes the firm's `registry_status`."

        Design: Difficulty/cross_entity_state_dependency/contract_file_requires_active_registration_in_every_contract_state
        """
        fundraiser, contract = self._two_state_contract()
        api_client.file_fundraising_contract(
            contract["id"], {}, make_fundraiser_agent_headers(fundraiser["id"])
        )

        florida = register_fundraiser_in_state(
            fundraiser["id"],
            "FL",
            bond_on_file_cents=2_500_000,
            expires_at="2027-12-31T00:00:00Z",
        )
        filed = validate_success(file_contract(contract["id"], fundraiser["id"]))

        assert florida["status"] == "ACTIVE", (
            f"The Florida credential is live, got {florida['status']}"
        )
        assert filed["status"] == "FILED", (
            f"The identical call now succeeds, got {filed['status']}"
        )
        assert filed["filed_at"] == "2026-08-01T00:00:00.000Z", (
            f"The filing is stamped at the logical clock, got {filed['filed_at']}"
        )
        assert filed["late_filing_surcharge_cents"] == 0, (
            "The filing is inside its window, got "
            f"{filed['late_filing_surcharge_cents']}"
        )


class TestPromotionActivationRequiresAClearPosture:
    """Activation demands a fully clear posture, not merely a posture that is
    not halted."""

    def _restricted_charity_with_a_filed_florida_promotion(self):
        seed_california_profile()
        seed_california_profile(state_code="FL", coventure_filing_required=True)
        organization = create_organization(domicile_state_code="FL")
        statement = create_financial_statement(organization)
        certifier, preparer = create_officer_pair(organization["id"])
        registration = open_filing(organization["id"], statement["id"], "CA")
        attach_required_documents(
            registration["id"],
            preparer["id"],
            registration["required_financial_attestation"],
        )
        validate_success(submit_filing(registration["id"], certifier["id"]))
        registration = validate_success(approve_filing(registration["id"]))

        promotion = setup_filed_promotion(
            organization["id"], ["FL"], DECEMBER_WINDOW
        )["promotion"]

        move_clock_to("2026-11-15T00:00:00Z")
        run_sweep("CA")
        action = _first_action_for(registration["id"])
        validate_success(remediate_action(action["id"], "Renewal packet in preparation."))
        validate_success(decide_action(action["id"], "ESCALATE"))
        move_clock_to("2026-12-05T00:00:00Z")

        return {
            "organization": organization,
            "registration": registration,
            "promotion": promotion,
            "enforcement_action": action,
        }

    def test_a_cease_order_in_another_state_restricts_activation_without_halting_it(
        self,
    ):
        """PRD §2.11 rung 15: "The organization's `solicitation_posture` is exactly
        `CLEAR` → `ERR_SOLICITATION_RESTRICTED` (409). Applies to promotion
        activation." PRD §3.7: activation "demands `solicitation_posture` of exactly
        `CLEAR`, so a charity under a single non-domicile cease order — posture
        `RESTRICTED` — cannot start a new promotion, and the attempt reports
        `ERR_SOLICITATION_RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/promotion_activate_requires_clear_posture_from_another_states_filing
        """
        ctx = self._restricted_charity_with_a_filed_florida_promotion()

        organization = read_organization(ctx["organization"]["id"])
        assert organization["solicitation_posture"] == "RESTRICTED", (
            "A cease order outside the domicile state restricts rather than halts, "
            f"got {organization['solicitation_posture']}"
        )
        assert read_promotion(ctx["promotion"]["id"])["status"] == "FILED", (
            "The Florida promotion is untouched by a California cease order"
        )

        response = activate_promotion(ctx["promotion"]["id"])
        validate_error(response, ApiErrorId.ERR_SOLICITATION_RESTRICTED.value)
        assert read_promotion(ctx["promotion"]["id"])["status"] == "FILED", (
            "The refused activation leaves the promotion filed"
        )

    def test_vacating_the_order_clears_the_posture_and_the_promotion_activates(self):
        """PRD §3.9: "The variant from `ESCALATED` does more, because escalation had
        ceased a filing: it also restores that filing `CEASED` → `REGISTERED` and
        recomputes `ceased_state_codes`, `solicitation_posture` and
        `registered_state_count` in addition."

        Design: Difficulty/cross_entity_state_dependency/promotion_activate_requires_clear_posture_from_another_states_filing
        """
        ctx = self._restricted_charity_with_a_filed_florida_promotion()

        vacated = validate_success(
            vacate_action(
                ctx["enforcement_action"]["id"],
                "Notice issued against the wrong fiscal year.",
            )
        )
        assert vacated["status"] == "VACATED", (
            f"The order is withdrawn, got {vacated['status']}"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "The ceased filing is restored by the vacatur"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["ceased_state_codes"] == [], (
            f"No state is under a cease order, got {organization['ceased_state_codes']}"
        )
        assert organization["solicitation_posture"] == "CLEAR", (
            f"The posture is fully clear again, got {organization['solicitation_posture']}"
        )
        assert organization["penalty_outstanding_cents"] == 0, (
            "The vacated penalty leaves the ledger, got "
            f"{organization['penalty_outstanding_cents']}"
        )
        assert organization["registered_state_count"] == 1, (
            f"The restored filing is counted, got {organization['registered_state_count']}"
        )

        activated = validate_success(activate_promotion(ctx["promotion"]["id"]))
        assert activated["status"] == "ACTIVE", (
            f"The promotion may finally start, got {activated['status']}"
        )
