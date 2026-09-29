"""Cascades: one call, three causally chained levels.

Escalating a cease order reaches an entity the request never names, and a
restatement reaches back into a packet the regulator is already holding.
"""

from test_helpers import (
    create_financial_statement,
    decide_action,
    list_financial_statements,
    read_organization,
    read_promotion,
    read_registration,
    remediate_action,
    setup_delinquent_filing,
    setup_filed_promotion,
    setup_registered_filing,
    setup_submitted_filing,
    validate_success,
)

DECEMBER_WINDOW = {
    "promo_start": "2026-12-01T00:00:00Z",
    "promo_end": "2026-12-31T00:00:00Z",
}


def _statement_by_id(organization_id: str, statement_id: str):
    for statement in list_financial_statements(organization_id):
        if statement["id"] == statement_id:
            return statement
    raise AssertionError(f"Statement {statement_id} is missing from the roster")


class TestEscalationCascade:
    """Ceasing a filing halts cause marketing the escalation never mentions."""

    def _escalated_charity(self):
        ctx = setup_delinquent_filing(sweep_at="2026-11-15T00:00:00Z")
        promo_ctx = setup_filed_promotion(
            ctx["organization"]["id"], ["CA"], DECEMBER_WINDOW
        )
        ctx["promotion"] = promo_ctx["promotion"]
        validate_success(
            remediate_action(
                ctx["enforcement_action"]["id"], "Renewal packet in preparation."
            )
        )
        ctx["escalated"] = validate_success(
            decide_action(ctx["enforcement_action"]["id"], "ESCALATE")
        )
        return ctx

    def test_escalation_ceases_the_filing_and_halts_solicitation_in_the_domicile_state(
        self,
    ):
        """PRD §3.9: "The first link ceases the filing: a linked filing in
        `DELINQUENT` moves `DELINQUENT` → `CEASED` and increments its `version`.
        The second link, caused by the first, adds that filing's `state_code` to
        the organization's `ceased_state_codes`, recomputes `solicitation_posture`
        from the §2.8 rules, and increments `Organization.version` by one."

        Design: Difficulty/transitive_cascade/escalation_cascade_e1_e2_e3_halts_filed_coventure_promotion
        """
        ctx = self._escalated_charity()

        assert ctx["escalated"]["status"] == "ESCALATED", (
            f"The action escalated, got {ctx['escalated']['status']}"
        )
        assert ctx["escalated"]["action_type"] == "CEASE_SOLICITATION_ORDER", (
            "Escalation rewrites the action type, got "
            f"{ctx['escalated']['action_type']}"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "CEASED", (
            "The linked filing is ceased by the first link of the cascade"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["ceased_state_codes"] == ["CA"], (
            f"California is now a ceased state, got {organization['ceased_state_codes']}"
        )
        assert organization["solicitation_posture"] == "HALTED", (
            "A cease order in the domicile state halts solicitation everywhere, got "
            f"{organization['solicitation_posture']}"
        )

    def test_escalation_halts_a_filed_promotion_the_call_never_names(self):
        """PRD §3.9: "The third link, caused by the second and firing only where the
        posture actually became `RESTRICTED` or `HALTED`, halts cause marketing:
        every co-venture promotion of that organization in `FILED` or in `ACTIVE`
        whose `state_codes` contains the ceased state moves to `HALTED`."

        Design: Difficulty/transitive_cascade/escalation_cascade_e1_e2_e3_halts_filed_coventure_promotion
        """
        ctx = self._escalated_charity()

        promotion = read_promotion(ctx["promotion"]["id"])
        assert promotion["status"] == "HALTED", (
            "A filed California promotion is halted by the ceased filing, got "
            f"{promotion['status']}"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["penalty_outstanding_cents"] == 2_004, (
            "The escalated action still sits on the ledger, got "
            f"{organization['penalty_outstanding_cents']}"
        )
        assert organization["registered_state_count"] == 0, (
            "A ceased filing is no longer a registration, got "
            f"{organization['registered_state_count']}"
        )


class TestRestatementCascade:
    """A restatement repoints live filings and can send one back as deficient."""

    def _restated_charity(self, setup):
        ctx = setup()
        ctx["restatement"] = create_financial_statement(
            ctx["organization"], assurance_level="NONE"
        )
        return ctx

    def test_a_restatement_supersedes_the_prior_statement_and_repoints_the_live_filing(
        self,
    ):
        """PRD §3.2: "Filing a second statement for a `fiscal_year` that already
        has a current one is a **restatement**, and it is a three-link cascade
        rather than a simple insert. The prior statement moves `CURRENT` →
        `SUPERSEDED`. Every registration pointing at the superseded statement
        through `financial_statement_id` whose `status` is `DRAFT`, `SUBMITTED` or
        `DEFICIENT` is repointed to the new statement's identifier, has its
        `required_financial_attestation` re-derived against the new numbers, and
        has its `version` incremented."

        Design: Difficulty/transitive_cascade/restatement_cascade_r1_r2_r3_deficients_submitted_filing
        """
        ctx = self._restated_charity(setup_submitted_filing)
        organization_id = ctx["organization"]["id"]

        original = _statement_by_id(
            organization_id, ctx["financial_statement"]["id"]
        )
        assert original["statement_status"] == "SUPERSEDED", (
            f"The prior statement is superseded, got {original['statement_status']}"
        )
        assert ctx["restatement"]["statement_status"] == "CURRENT", (
            "The restatement is authoritative, got "
            f"{ctx['restatement']['statement_status']}"
        )

        registration = read_registration(ctx["registration"]["id"])
        assert registration["financial_statement_id"] == ctx["restatement"]["id"], (
            "The submitted filing now stands on the restatement, got "
            f"{registration['financial_statement_id']}"
        )
        assert registration["required_financial_attestation"] == "REVIEW", (
            "The restated revenue still crosses the review threshold, got "
            f"{registration['required_financial_attestation']}"
        )

    def test_a_weaker_assurance_level_pushes_the_submitted_filing_back_as_deficient(
        self,
    ):
        """PRD §3.2: "where such a repointed registration was sitting in
        `SUBMITTED`, and its freshly re-derived attestation requirement now
        outranks the new statement's `assurance_level` on the ordered scale in
        which `NONE` is weakest, `REVIEW` sits above it and `AUDIT` is strongest,
        that registration is pushed back `SUBMITTED` → `DEFICIENT` with
        `deficiency_reasons` set to a single-element list holding
        `ASSURANCE_LEVEL_INSUFFICIENT` and `deficiency_round_count` incremented by
        one."

        Design: Difficulty/transitive_cascade/restatement_cascade_r1_r2_r3_deficients_submitted_filing
        """
        ctx = self._restated_charity(setup_submitted_filing)

        registration = read_registration(ctx["registration"]["id"])
        assert registration["status"] == "DEFICIENT", (
            "An unassured restatement cannot support a review-level filing, got "
            f"{registration['status']}"
        )
        assert registration["deficiency_reasons"] == ["ASSURANCE_LEVEL_INSUFFICIENT"], (
            f"The single reason is recorded, got {registration['deficiency_reasons']}"
        )
        assert registration["deficiency_round_count"] == 1, (
            f"The cascade counts as a round, got {registration['deficiency_round_count']}"
        )
        assert (
            read_organization(ctx["organization"]["id"])["registered_state_count"] == 0
        ), "Nothing was ever registered, so nothing is counted"

    def test_a_restatement_does_not_reopen_a_filing_the_state_already_accepted(self):
        """PRD §3.2: "Registrations already in `REGISTERED`, `EXPIRED`,
        `DELINQUENT`, `CEASED` or `WITHDRAWN` are untouched by all three links: a
        restatement does not reopen a filing the state has already accepted."

        Design: Difficulty/transitive_cascade/restatement_cascade_r1_r2_r3_deficients_submitted_filing
        """
        ctx = self._restated_charity(setup_registered_filing)

        registration = read_registration(ctx["registration"]["id"])
        assert registration["status"] == "REGISTERED", (
            f"An accepted filing is left alone, got {registration['status']}"
        )
        assert registration["financial_statement_id"] == ctx["financial_statement"]["id"], (
            "The accepted filing still stands on the statement it was approved "
            f"on, got {registration['financial_statement_id']}"
        )
        assert registration["deficiency_round_count"] == 0, (
            f"No revision round was opened, got {registration['deficiency_round_count']}"
        )
        original = _statement_by_id(
            ctx["organization"]["id"], ctx["financial_statement"]["id"]
        )
        assert original["statement_status"] == "SUPERSEDED", (
            "The statement itself is still superseded by the restatement, got "
            f"{original['statement_status']}"
        )
