"""Programs: creation side effects, OCC, policy-period overlap, fronting
dependencies, collateral valuation, and collateral/admitted-assets invariants."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_program,
    create_fronting,
    create_program,
    get_captive,
    get_captive_version,
    setup_capitalized_captive,
    setup_fronting_collateral_posted,
    setup_fronting_terms_agreed,
    setup_quoted_program,
    validate_error,
    validate_success,
)


class TestProgramCreation:

    def test_program_creation_side_effects(self, api, underwriter_headers, captive_manager_headers):
        """PRD §3.3: "A successful create lands the program in `DRAFT` status with
        `coverage_status` set to `UNBOUND`, and increments the captive's `version`
        by 1."
        PRD §2.4: "Both of these writes also increment the captive's `version` by 1
        on success."

        Design: Corner/endpoints/program_creation_side_effects
        """
        captive = setup_capitalized_captive()
        version_before = get_captive_version(captive["id"])
        program = create_program(captive["id"])
        assert_program(program)
        assert program["program_status"] == "DRAFT"
        assert program["coverage_status"] == "UNBOUND"
        assert program["premium_allocated_cents"] == 0
        assert program["claims_incurred_cents"] == 0
        assert program["claims_paid_cents"] == 0
        captive_after = get_captive(captive["id"])
        assert captive_after["version"] == version_before + 1, (
            f"Captive version must increment by 1 on program creation: "
            f"{version_before} -> {captive_after['version']}"
        )

    def test_occ_stale_version_on_program_create(self, api, underwriter_headers):
        """PRD §2.4: "Creating a new `InsuranceProgram` requires the request body
        to carry `expected_captive_version` — a non-optional integer equal to the
        captive's current `version` as last observed by the client. If the
        captive's actual `version` has advanced since (for example because another
        writer just triggered a solvency recalculation), the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_program_create
        """
        captive = setup_capitalized_captive()
        stale_version = get_captive_version(captive["id"])
        first = create_program(captive["id"], expected_captive_version=stale_version,
                               program_name="OCC Prog 1")
        assert first["program_status"] == "DRAFT"
        # The first creation advanced the captive's version; replaying the stale
        # version on a second create must be rejected.
        resp = api.create_program(
            captive["id"],
            {
                "program_name": "OCC Prog 2",
                "line_of_business": "WORKERS_COMP",
                "policy_period_start": "2026-06-01T00:00:00Z",
                "policy_period_end": "2027-05-31T23:59:59Z",
                "aggregate_limit_cents": 1000000,
                "per_occurrence_limit_cents": 250000,
                "attachment_point_cents": 10000,
                "premium_budget_cents": 200000,
                "expected_captive_version": stale_version,
            },
            underwriter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_error_program_not_found(self, api, underwriter_headers):
        """PRD §2.4: "then that the program identified by `programId` exists under
        that captive (else `ERR_PROGRAM_NOT_FOUND`)".

        Design: Corner/errors/error_program_not_found
        """
        captive = setup_capitalized_captive()
        resp = api.get_program(captive["id"], NON_EXISTENT_UUID, underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


class TestPolicyPeriodOverlap:

    def test_policy_period_overlap_same_line_of_business_rejected(self, api, underwriter_headers):
        """PRD §3.3: "the requested period must not overlap any existing program
        for the same `line_of_business` under the same captive (else
        `ERR_POLICY_PERIOD_OVERLAP`, HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/policy_period_overlap_same_line_of_business
        """
        captive = setup_capitalized_captive()
        create_program(captive["id"], program_name="GL Prog O1",
                       line_of_business="GENERAL_LIABILITY",
                       policy_period_start="2026-06-01T00:00:00Z",
                       policy_period_end="2027-05-31T23:59:59Z")
        resp = api.create_program(
            captive["id"],
            {
                "program_name": "GL Prog O2",
                "line_of_business": "GENERAL_LIABILITY",
                "policy_period_start": "2026-12-01T00:00:00Z",
                "policy_period_end": "2027-11-30T23:59:59Z",
                "aggregate_limit_cents": 1000000,
                "per_occurrence_limit_cents": 250000,
                "attachment_point_cents": 10000,
                "premium_budget_cents": 200000,
                "expected_captive_version": get_captive_version(captive["id"]),
            },
            underwriter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_PERIOD_OVERLAP)

    def test_policy_period_overlap_different_line_allowed(self, api, underwriter_headers):
        """PRD §3.3: "the requested period must not overlap any existing program
        for the same `line_of_business` under the same captive (else
        `ERR_POLICY_PERIOD_OVERLAP`, HTTP 409)" — the overlap check is scoped to
        the same line of business, so an overlapping period for a different line
        is accepted.

        Design: Difficulty/resource_temporal_overlap/policy_period_overlap_same_line_of_business
        """
        captive = setup_capitalized_captive()
        create_program(captive["id"], program_name="GL Prog O1",
                       line_of_business="GENERAL_LIABILITY",
                       policy_period_start="2026-06-01T00:00:00Z",
                       policy_period_end="2027-05-31T23:59:59Z")
        second = create_program(
            captive["id"],
            program_name="WC Prog O2",
            line_of_business="WORKERS_COMP",
            policy_period_start="2026-12-01T00:00:00Z",
            policy_period_end="2027-11-30T23:59:59Z",
        )
        assert_program(second)
        assert second["program_status"] == "DRAFT"
        assert second["line_of_business"] == "WORKERS_COMP"


class TestProgramBindFrontingDependency:

    def test_bind_rejected_when_fronting_not_ready(self, api, underwriter_headers):
        """PRD §3.3: "binding requires the program to be `QUOTED` (else
        `ERR_PROGRAM_NOT_QUOTED`) and, when `fronting_required` is true, requires
        the associated `FrontingArrangement` to be in `COLLATERAL_POSTED` or any
        later state (else `ERR_FRONTING_NOT_READY`)."

        Design: Difficulty/cross_entity_state_dependency/program_bind_requires_fronting_collateral_posted
        """
        captive = setup_capitalized_captive()
        program = setup_quoted_program(captive["id"], fronting_required=True)
        # Create a fronting arrangement that stays in NEGOTIATING.
        fronting = create_fronting(captive["id"], program["id"])
        assert fronting["status"] == "NEGOTIATING"
        resp = api.bind_program(captive["id"], program["id"], underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_FRONTING_NOT_READY)

    def test_bind_succeeds_once_collateral_posted(self, api, underwriter_headers):
        """PRD §3.3: "Binding by an `Underwriter` moves the program `QUOTED →
        BOUND` and flips `coverage_status` to `BOUND`; binding requires the
        program to be `QUOTED` (else `ERR_PROGRAM_NOT_QUOTED`) and, when
        `fronting_required` is true, requires the associated `FrontingArrangement`
        to be in `COLLATERAL_POSTED` or any later state (else
        `ERR_FRONTING_NOT_READY`)."
        PRD §3.4: "Posting collateral against the arrangement by a `CaptiveManager`
        transitions the arrangement `TERMS_AGREED → COLLATERAL_POSTED`."

        Design: Difficulty/cross_entity_state_dependency/program_bind_requires_fronting_collateral_posted
        """
        captive = setup_capitalized_captive()
        program = setup_quoted_program(captive["id"], fronting_required=True)
        fronting, collateral = setup_fronting_collateral_posted(captive["id"], program["id"])
        assert fronting["status"] == "COLLATERAL_POSTED"
        bound = validate_success(api.bind_program(captive["id"], program["id"], underwriter_headers))
        assert bound["program_status"] == "BOUND"
        assert bound["coverage_status"] == "BOUND"


class TestCollateralValuation:

    def test_collateral_per_posting_rounding_first_posting(self, api, captive_manager_headers):
        """PRD §3.4: "its `haircut_pct` and `effective_value_cents` are computed
        from the haircut schedule (§2.8, with the conservative multiplier for
        micro-captives): `effective_value_cents` is `amount_cents` multiplied by
        one minus the haircut, rounded to integer cents half-up."
        PRD §2.8: "every non-cash collateral haircut is multiplied by one and a
        half (so a `LETTER_OF_CREDIT` carries a 10% haircut instead of 5%, ...)"
        — the standard letter-of-credit haircut is therefore 5%, and this captive
        elects `STANDARD_831A`, so 33333 * (1 - 0.05) = 31666.35 rounds half-up to
        31666 integer cents.

        Design: Difficulty/combinatorial_formula/collateral_valuation_nested_rounding_order
        """
        captive = setup_capitalized_captive(tax_classification="STANDARD_831A")
        program = setup_quoted_program(captive["id"], fronting_required=True)
        fronting = setup_fronting_terms_agreed(captive["id"], program["id"])
        resp = api.create_collateral(
            captive["id"], program["id"], fronting["id"],
            {
                "collateral_type": "LETTER_OF_CREDIT",
                "amount_cents": 33333,
                "posted_date": "2026-05-01T00:00:00Z",
                "expiry_date": "2027-05-01T00:00:00Z",
                "issuing_institution": "Bank A",
            },
            captive_manager_headers,
        )
        collateral = validate_success(resp, expected_status=201)
        assert collateral["haircut_pct"] == pytest.approx(0.05), (
            f"Standard LOC haircut must be 0.05, got {collateral['haircut_pct']}"
        )
        assert collateral["effective_value_cents"] == 31666, (
            f"33333 * 0.95 = 31666.35 rounds half-up to 31666, "
            f"got {collateral['effective_value_cents']}"
        )

    def test_collateral_per_posting_rounding_sum(self, api, captive_manager_headers):
        """PRD §3.4: "`effective_value_cents` is `amount_cents` multiplied by one
        minus the haircut, rounded to integer cents half-up" — rounding happens
        per posting, so two postings of 33333 cents at the standard 5% LOC haircut
        yield 31666 each and a combined 63332 (per-posting rounding), not the
        63333 that aggregate-then-round would produce.

        Design: Difficulty/combinatorial_formula/collateral_valuation_nested_rounding_order
        """
        captive = setup_capitalized_captive(tax_classification="STANDARD_831A")
        program = setup_quoted_program(captive["id"], fronting_required=True)
        fronting = setup_fronting_terms_agreed(captive["id"], program["id"])
        effective_values = []
        for bank in ("Bank A", "Bank B"):
            resp = api.create_collateral(
                captive["id"], program["id"], fronting["id"],
                {
                    "collateral_type": "LETTER_OF_CREDIT",
                    "amount_cents": 33333,
                    "posted_date": "2026-05-01T00:00:00Z",
                    "expiry_date": "2027-05-01T00:00:00Z",
                    "issuing_institution": bank,
                },
                captive_manager_headers,
            )
            collateral = validate_success(resp, expected_status=201)
            effective_values.append(collateral["effective_value_cents"])
        assert effective_values == [31666, 31666], (
            f"Each posting rounds independently to 31666, got {effective_values}"
        )
        assert sum(effective_values) == 63332, (
            f"Per-posting rounding then sum gives 63332, got {sum(effective_values)}"
        )


class TestCollateralVerifyAdmittedAssets:

    def test_collateral_verify_marks_verified_and_computes_effective_value(
        self, api, captive_manager_headers
    ):
        """PRD §3.4: "A `CaptiveManager` then verifies the posting, which flips
        `verification_status` to `VERIFIED` and updates the parent arrangement's
        `collateral_posted_cents` and `collateral_shortfall_cents`."
        PRD §2.8: "(so a `LETTER_OF_CREDIT` carries a 10% haircut instead of 5%,
        ...)" — under `STANDARD_831A` the standard 5% LOC haircut applies, so a
        100000-cent posting carries an effective value of 95000 cents.

        Design: Difficulty/compensating_invariant/collateral_post_verify_preserves_total_admitted_assets
        """
        captive = setup_capitalized_captive(tax_classification="STANDARD_831A")
        program = setup_quoted_program(captive["id"], fronting_required=True)
        fronting = setup_fronting_terms_agreed(captive["id"], program["id"])
        collateral = validate_success(
            api.create_collateral(
                captive["id"], program["id"], fronting["id"],
                {
                    "collateral_type": "LETTER_OF_CREDIT",
                    "amount_cents": 100000,
                    "posted_date": "2026-05-01T00:00:00Z",
                    "expiry_date": "2027-06-01T00:00:00Z",
                    "issuing_institution": "Bank R",
                },
                captive_manager_headers,
            ),
            expected_status=201,
        )
        assert collateral["verification_status"] == "PENDING_VERIFICATION"
        assert collateral["effective_value_cents"] == 95000
        verified = validate_success(
            api.verify_collateral(captive["id"], program["id"], fronting["id"],
                                  collateral["id"], captive_manager_headers)
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["effective_value_cents"] == 95000

    def test_collateral_verify_increases_admitted_assets_by_effective_value(
        self, api, captive_manager_headers
    ):
        """PRD §2.8: "The `admitted_assets` total is computed as the sum of the
        `effective_value_cents` of every `CollateralPosting` whose
        `verification_status` is `VERIFIED`, plus the sum of the
        `allocated_amount_cents` of every `PremiumAllocation` whose `status` is
        `PROVISIONAL`, `AUDITED`, or `FINALIZED`, minus the sum of the
        `paid_amount_cents` of every `Claim` whose `claim_status` is `SETTLED`."
        Verifying a 100000-cent letter of credit (standard 5% haircut) therefore
        raises admitted assets by exactly its 95000-cent effective value.

        Design: Difficulty/compensating_invariant/collateral_post_verify_preserves_total_admitted_assets
        """
        captive = setup_capitalized_captive(tax_classification="STANDARD_831A")
        program = setup_quoted_program(captive["id"], fronting_required=True)
        fronting = setup_fronting_terms_agreed(captive["id"], program["id"])
        admitted_before = get_captive(captive["id"])["admitted_assets"]
        collateral = validate_success(
            api.create_collateral(
                captive["id"], program["id"], fronting["id"],
                {
                    "collateral_type": "LETTER_OF_CREDIT",
                    "amount_cents": 100000,
                    "posted_date": "2026-05-01T00:00:00Z",
                    "expiry_date": "2027-06-01T00:00:00Z",
                    "issuing_institution": "Bank R",
                },
                captive_manager_headers,
            ),
            expected_status=201,
        )
        # PENDING_VERIFICATION collateral contributes nothing to admitted assets.
        admitted_pending = get_captive(captive["id"])["admitted_assets"]
        assert admitted_pending == admitted_before, (
            f"Unverified collateral must not move admitted_assets: "
            f"{admitted_before} -> {admitted_pending}"
        )
        validate_success(
            api.verify_collateral(captive["id"], program["id"], fronting["id"],
                                  collateral["id"], captive_manager_headers)
        )
        admitted_after = get_captive(captive["id"])["admitted_assets"]
        assert admitted_after - admitted_before == 95000, (
            f"admitted_assets must increase by the 95000-cent effective value: "
            f"{admitted_before} -> {admitted_after}"
        )
