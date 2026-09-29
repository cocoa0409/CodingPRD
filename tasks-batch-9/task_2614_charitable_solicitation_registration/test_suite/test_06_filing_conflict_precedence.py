"""When two rules are broken at once, the lower rung number answers.

Several of these scenarios violate two independent rules simultaneously. The
response must name the earlier rung of the validation ladder, even where the
later one is the more alarming defect and even where both carry the same status.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    api_client,
    attach_required_documents,
    create_financial_statement,
    create_fundraiser,
    create_organization,
    decide_action,
    draft_contract,
    file_contract,
    move_clock_to,
    open_filing,
    read_contract,
    read_organization,
    read_registration,
    register_fundraiser_in_state,
    remediate_action,
    run_sweep,
    seed_california_profile,
    make_fundraiser_agent_headers,
    seed_state_profile,
    setup_registered_filing,
    state_registration_payload,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)

FLORIDA_PROFILE = {
    "renewal_due_rule": "FYE_PLUS_6M",
    "assurance_basis": "GROSS_REVENUE",
    "review_threshold_cents": 20_000_000,
    "audit_threshold_cents": 200_000_000,
}


def _first_action_for(registration_id: str):
    response = api_client.list_enforcement_actions(
        COMPLIANCE, params={"registration_id": registration_id}
    )
    actions, _meta = validate_paginated(response)
    assert actions, f"Expected an enforcement action on filing {registration_id}"
    return actions[0]


class TestHaltedPostureOutranksAssuranceShortfall:
    """A cease order in the domicile state answers before the fiscal defect."""

    def _halted_charity_with_a_defective_florida_packet(self):
        ctx = setup_registered_filing()
        seed_state_profile("FL", **FLORIDA_PROFILE)
        unassured = create_financial_statement(
            ctx["organization"], fiscal_year=2025, assurance_level="NONE"
        )
        florida = open_filing(
            ctx["organization"]["id"],
            unassured["id"],
            "FL",
            fiscal_year=2025,
            coverage_start="2024-07-01T00:00:00Z",
            coverage_end="2025-07-01T00:00:00Z",
        )
        attach_required_documents(florida["id"], ctx["preparer"]["id"], "REVIEW")

        move_clock_to("2026-11-15T00:00:00Z")
        run_sweep("CA")
        action = _first_action_for(ctx["registration"]["id"])
        validate_success(remediate_action(action["id"], "Renewal packet in preparation."))
        validate_success(decide_action(action["id"], "ESCALATE"))

        ctx["florida_registration"] = florida
        ctx["enforcement_action"] = action
        return ctx

    def test_a_halted_charity_cannot_submit_even_a_packet_with_a_fiscal_defect(self):
        """PRD §2.11 rung 14: "The organization's `solicitation_posture` is not
        `HALTED` → `ERR_SOLICITATION_HALTED` (409). Applies to registration
        creation, filing submission, and promotion creation." PRD §2.11 also fixes
        the precedence: "Checks are evaluated in a fixed ascending order and the
        first failure wins; no later check can mask an earlier one, and no earlier
        check is skipped because a later one would also fail."

        Design: Difficulty/priority_pair_validation_conflict/halted_posture_p14_beats_assurance_insufficient_p34_on_submit
        """
        ctx = self._halted_charity_with_a_defective_florida_packet()
        florida_id = ctx["florida_registration"]["id"]

        response = submit_filing(
            florida_id,
            ctx["certifier"]["id"],
            certification_note="Certified for Florida.",
        )

        validate_error(response, ApiErrorId.ERR_SOLICITATION_HALTED.value)
        florida = read_registration(florida_id)
        assert florida["status"] == "DRAFT", (
            f"The rejected packet stays in draft, got {florida['status']}"
        )
        assert florida["required_financial_attestation"] == "REVIEW", (
            "Florida measures gross revenue and demands a review, got "
            f"{florida['required_financial_attestation']}"
        )
        assert florida["submitted_at"] is None, (
            f"Nothing was submitted, got {florida['submitted_at']}"
        )
        assert (
            read_organization(ctx["organization"]["id"])["solicitation_posture"]
            == "HALTED"
        ), "The domicile cease order halts solicitation everywhere"

    def test_once_the_halt_is_lifted_the_same_packet_reports_its_assurance_shortfall(
        self,
    ):
        """PRD §2.11 rung 34: "The supporting statement's assurance level covers the
        requirement → `ERR_ASSURANCE_LEVEL_INSUFFICIENT` (422). Applies to filing
        submission." PRD §3.4 states the scale: "the statement's `assurance_level`
        must be at or above `required_financial_attestation` on the ordered scale
        where `NONE` is weakest, `REVIEW` sits above it and `AUDIT` is strongest".

        Design: Difficulty/priority_pair_validation_conflict/halted_posture_p14_beats_assurance_insufficient_p34_on_submit
        """
        ctx = self._halted_charity_with_a_defective_florida_packet()
        # PRD §3.9: remediation "is available from `OPEN` and from `ESCALATED` — an
        # escalated cease-solicitation order can be remediated repeatedly" — and a
        # `CURE` decision "is available only from `REMEDIATION_SUBMITTED`", so the
        # escalated order must re-enter remediation before it can be cured.
        validate_success(
            remediate_action(
                ctx["enforcement_action"]["id"], "Renewal packet now complete."
            )
        )
        validate_success(decide_action(ctx["enforcement_action"]["id"], "CURE"))
        assert (
            read_organization(ctx["organization"]["id"])["solicitation_posture"]
            == "CLEAR"
        ), "The cure lifts the halt so the later rung can be reached"

        response = submit_filing(
            ctx["florida_registration"]["id"], ctx["certifier"]["id"]
        )

        validate_error(response, ApiErrorId.ERR_ASSURANCE_LEVEL_INSUFFICIENT.value)
        assert read_registration(ctx["florida_registration"]["id"])["status"] == "DRAFT", (
            "The fiscal defect is real, so the packet still cannot be submitted"
        )


class TestContractStateOutranksFundraiserRegistration:
    """A voided contract reports its own status before the firm's credentials."""

    def _voided_contract(self):
        seed_california_profile(
            fundraiser_contract_filing_days=10, fundraiser_bond_minimum_cents=2_500_000
        )
        organization = create_organization()
        fundraiser = create_fundraiser(
            legal_name="Northline Donor Services",
            fundraiser_type="PROFESSIONAL_SOLICITOR",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        registration = register_fundraiser_in_state(
            fundraiser["id"],
            "CA",
            bond_on_file_cents=2_500_000,
            expires_at="2026-09-30T00:00:00Z",
        )
        contract = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA"],
            contract_start="2026-08-01T00:00:00Z",
            contract_end="2027-08-01T00:00:00Z",
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )
        contract = validate_success(file_contract(contract["id"], fundraiser["id"]))

        move_clock_to("2026-10-01T00:00:00Z")
        run_sweep("CA")
        return organization, fundraiser, registration, contract

    def test_refiling_a_voided_contract_reports_the_contract_state_not_the_lapsed_firm(
        self,
    ):
        """PRD §2.11 rung 11: "The contract's `status` is `DRAFT` for a filing
        operation → `ERR_INVALID_CONTRACT_STATE` (409). Applies to contract
        filing." PRD §3.9 explains how it got there: "every fundraising contract of
        the same firm whose `status` is `FILED` or `LATE_FILED` and whose
        `state_codes` contains the lapsed state is driven to `VOIDED`".

        Design: Difficulty/priority_pair_validation_conflict/contract_state_p11_beats_fundraiser_registration_p19_on_file
        """
        _organization, fundraiser, _registration, contract = self._voided_contract()

        response = api_client.file_fundraising_contract(
            contract["id"], {}, make_fundraiser_agent_headers(fundraiser["id"])
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CONTRACT_STATE.value)

        stored = read_contract(contract["id"])
        assert stored["status"] == "VOIDED", (
            f"The lapse cascade voided the contract, got {stored['status']}"
        )
        assert stored["filing_due_date"] == "2026-08-11T00:00:00.000Z", (
            "The contract start plus California's ten filing days, got "
            f"{stored['filing_due_date']}"
        )
        assert stored["late_filing_surcharge_cents"] == 0, (
            "The original filing was timely, got "
            f"{stored['late_filing_surcharge_cents']}"
        )

        registrations, _meta = validate_paginated(
            api_client.list_fundraiser_registrations(
                fundraiser["id"], make_fundraiser_agent_headers(fundraiser["id"])
            )
        )
        assert registrations[0]["status"] == "LAPSED", (
            f"The credential expired at the sweep, got {registrations[0]['status']}"
        )

    def test_a_fresh_draft_contract_reports_the_lapsed_credential_instead(self):
        """PRD §2.11 rung 19: "Every state on the contract or promotion has an active
        fundraiser registration for the firm → `ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE`
        (422). Applies to contract filing and promotion filing." PRD §3.6 phrases the
        same condition: "Every state in `state_codes` must have an `ACTIVE`
        registration for this firm, or it reports
        `ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_p11_beats_fundraiser_registration_p19_on_file
        """
        organization, fundraiser, _registration, _voided = self._voided_contract()

        replacement = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA"],
            contract_start="2026-10-01T00:00:00Z",
            contract_end="2027-10-01T00:00:00Z",
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )
        assert replacement["status"] == "DRAFT", (
            f"The replacement clears the state rung, got {replacement['status']}"
        )

        response = api_client.file_fundraising_contract(
            replacement["id"], {}, make_fundraiser_agent_headers(fundraiser["id"])
        )

        validate_error(
            response, ApiErrorId.ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE.value
        )
        assert read_contract(replacement["id"])["status"] == "DRAFT", (
            "An unfilable contract stays in draft"
        )


class TestCoverageOverlapOutranksDuplicateFiling:
    """Two rules, one status code: only the error identifier tells them apart."""

    def test_an_overlapping_renewal_in_a_used_fiscal_year_reports_the_temporal_rule(
        self,
    ):
        """PRD §2.11 rung 22: "Coverage intervals do not overlap →
        `ERR_COVERAGE_PERIOD_OVERLAP` (409). Applies to registration creation and
        review." Rung 27 sits below it: "No non-terminal registration already exists
        for the same organization, state and fiscal year →
        `ERR_DUPLICATE_STATE_REGISTRATION` (409). Applies to registration creation."

        Design: Difficulty/priority_pair_validation_conflict/coverage_overlap_p22_beats_duplicate_registration_p27_on_create
        """
        ctx = setup_registered_filing()

        response = api_client.create_state_registration(
            state_registration_payload(
                ctx["organization"]["id"],
                ctx["financial_statement"]["id"],
                "CA",
                "RENEWAL",
                coverage_start="2026-06-01T00:00:00Z",
                coverage_end="2027-06-01T00:00:00Z",
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value)
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "The incumbent filing is untouched by the rejected create"
        )
        assert (
            read_organization(ctx["organization"]["id"])["registered_state_count"] == 1
        ), "No second registration was opened"

    def test_a_non_overlapping_reuse_of_the_same_fiscal_year_reports_the_duplicate_rule(
        self,
    ):
        """PRD §3.3: "at most one non-terminal filing may exist per organization,
        state and fiscal year: if another filing for the same triple exists in any
        status other than `EXPIRED` or `WITHDRAWN`, the create is rejected with
        `ERR_DUPLICATE_STATE_REGISTRATION`."

        Design: Difficulty/priority_pair_validation_conflict/coverage_overlap_p22_beats_duplicate_registration_p27_on_create
        """
        ctx = setup_registered_filing()

        response = api_client.create_state_registration(
            state_registration_payload(
                ctx["organization"]["id"],
                ctx["financial_statement"]["id"],
                "CA",
                "RENEWAL",
                coverage_start="2026-07-01T00:00:00Z",
                coverage_end="2027-07-01T00:00:00Z",
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_STATE_REGISTRATION.value)
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "The incumbent filing is untouched by the rejected create"
        )


class TestCoverageHalfOpenAdjacency:
    """Consecutive coverage years abut; a one-day retreat overlaps."""

    def test_a_renewal_starting_exactly_on_the_prior_coverage_end_is_accepted(self):
        """PRD §3.3: "The interval is treated as half-open — `coverage_start` is
        inside it and `coverage_end` is outside it — and it is compared against the
        coverage intervals of every other filing for the same organization and state
        whose `status` is `SUBMITTED`, `REGISTERED`, `DELINQUENT` or `CEASED`. Any
        genuine overlap reports `ERR_COVERAGE_PERIOD_OVERLAP`, while two intervals
        that merely abut, where the new `coverage_start` is exactly the existing
        `coverage_end`, are accepted as consecutive coverage years rather than a
        conflict."

        Design: Difficulty/resource_temporal_overlap/registration_coverage_half_open_adjacency_allowed_overlap_rejected
        """
        ctx = setup_registered_filing()

        response = api_client.create_state_registration(
            state_registration_payload(
                ctx["organization"]["id"],
                ctx["financial_statement"]["id"],
                "CA",
                "RENEWAL",
                fiscal_year=2027,
                coverage_start="2026-07-01T00:00:00Z",
                coverage_end="2027-07-01T00:00:00Z",
                supersedes_registration_id=ctx["registration"]["id"],
            ),
            COMPLIANCE,
        )

        renewal = validate_success(response, 201)
        assert renewal["status"] == "DRAFT", (
            f"The accepted renewal opens in draft, got {renewal['status']}"
        )
        assert renewal["coverage_start"] == "2026-07-01T00:00:00.000Z", (
            f"The abutting start is stored verbatim, got {renewal['coverage_start']}"
        )
        assert renewal["supersedes_registration_id"] == ctx["registration"]["id"], (
            "The renewal names the filing it replaces, got "
            f"{renewal['supersedes_registration_id']}"
        )

    def test_a_renewal_starting_one_day_earlier_genuinely_overlaps(self):
        """PRD §3.3: "Any genuine overlap reports `ERR_COVERAGE_PERIOD_OVERLAP`".
        The comparison is scoped to siblings of the same charity and state and the
        interval bound is exclusive at `coverage_end`: "`coverage_end` must in all
        cases be strictly after `coverage_start`."

        Design: Difficulty/resource_temporal_overlap/registration_coverage_half_open_adjacency_allowed_overlap_rejected
        """
        ctx = setup_registered_filing()

        response = api_client.create_state_registration(
            state_registration_payload(
                ctx["organization"]["id"],
                ctx["financial_statement"]["id"],
                "CA",
                "RENEWAL",
                fiscal_year=2029,
                coverage_start="2026-06-30T00:00:00Z",
                coverage_end="2027-06-30T00:00:00Z",
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value)
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "The incumbent filing is untouched by the rejected create"
        )
        assert (
            read_organization(ctx["organization"]["id"])["registered_state_count"] == 1
        ), "No second registration was opened"
