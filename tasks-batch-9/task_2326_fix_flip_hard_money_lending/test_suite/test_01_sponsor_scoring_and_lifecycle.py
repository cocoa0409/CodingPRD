"""Sponsor registration, experience scoring, tier banding and lifecycle."""

import pytest

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    BorrowerStatus,
    EntityType,
    ExperienceTier,
    GuaranteeStatus,
    PropertyStatus,
    RehabLineItemStatus,
    api_client,
    assert_borrower_score,
    assert_same_record,
    assert_system_fields,
    factories,
    fixtures,
    validate_error,
    validate_success,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
)

# A sponsor whose intake score lands exactly on the TIER_B lower edge:
# 4/5 experience = 32.00, (696-600)/200 credit = 12.00, 1_800_000 over ten
# percent of 30_000_000 liquidity = 12.00, 6/10 career = 9.00 -> 65.00.
EDGE_SPONSOR = {
    "flips_last_24mo": 4,
    "flips_lifetime": 6,
    "credit_score": 696,
    "liquidity_cents": 1_800_000,
    "prior_default_count": 0,
    "declared_target_loan_cents": 30_000_000,
}


class TestExperienceScoreVariants:
    def test_recertification_uses_the_lifetime_decay_variant(self):
        """Recertifying the TIER_B edge sponsor rescores it with decayed lifetime flips.

        Intake credits only the rolling window, so four recent flips against a
        target of five gives 32.00 of the experience term and a 65.00 total.
        Recertification credits older flips at one half, so units become
        4 + 0.5 * (6 - 4) = 5, the experience term saturates at 40.00 and the
        recertified total is 73.00. The PRD states: "On recertification the
        **lifetime-decay** variant applies: experience units are
        `flips_last_24mo` plus half of the difference between `flips_lifetime`
        and `flips_last_24mo`, so older flips are credited at a decay weight of
        one half and the same sponsor scores differently on recertification than
        at intake."

        Design: Difficulty/dual_variant_calc/borrower_score_intake_rolling_vs_recert_lifetime_decay
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.register_borrower(**EDGE_SPONSOR)
        assert_borrower_score(
            borrower,
            intake_experience_score=65.00,
            effective_experience_score=65.00,
            experience_tier=ExperienceTier.TIER_B.value,
        )
        assert borrower["recertified_experience_score"] is None
        assert borrower["recertified_at"] is None

        fixtures.execute_guarantee(borrower["id"])
        fixtures.approve_sponsor(borrower["id"])

        recertified = validate_success(
            api_client.borrower_status_action(
                borrower["id"], factories.recertify_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        assert_borrower_score(
            recertified,
            intake_experience_score=65.00,
            recertified_experience_score=73.00,
            effective_experience_score=73.00,
            experience_tier=ExperienceTier.TIER_B.value,
        )
        assert recertified["status"] == BorrowerStatus.APPROVED_SPONSOR.value
        assert recertified["recertified_at"] is not None
        assert recertified["recertified_at"].startswith("2026-08-10T09:00:00"), (
            "recertified_at must be the logical-clock instant"
        )

    def test_the_two_variants_can_straddle_two_tiers_for_one_sponsor(self):
        """A sponsor with no recent flips but ten lifetime flips jumps TIER_C to TIER_A.

        Intake counts only `flips_last_24mo`, which is zero here, so the
        experience term contributes nothing and the intake total is
        0 + 20 + 20 + 15 = 55.00, banding TIER_C. The decay variant credits half
        of the ten lifetime flips as five units, saturating the experience term
        at 40.00 for a recertified 95.00 and TIER_A. The PRD states: "The field
        `effective_experience_score` reports `recertified_experience_score` when
        `recertified_at` is non-null and `intake_experience_score` otherwise,
        and `experience_tier` is always banded from
        `effective_experience_score`."

        Design: Difficulty/dual_variant_calc/borrower_score_intake_rolling_vs_recert_lifetime_decay
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.register_borrower(
            flips_last_24mo=0,
            flips_lifetime=10,
            credit_score=760,
            liquidity_cents=30_000_000,
            declared_target_loan_cents=30_000_000,
        )
        assert_borrower_score(
            borrower,
            intake_experience_score=55.00,
            effective_experience_score=55.00,
            experience_tier=ExperienceTier.TIER_C.value,
        )

        fixtures.execute_guarantee(borrower["id"])
        fixtures.approve_sponsor(borrower["id"])
        recertified = validate_success(
            api_client.borrower_status_action(
                borrower["id"], factories.recertify_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        assert_borrower_score(
            recertified,
            intake_experience_score=55.00,
            recertified_experience_score=95.00,
            effective_experience_score=95.00,
            experience_tier=ExperienceTier.TIER_A.value,
        )


class TestTierBandBoundary:
    def test_a_score_of_exactly_sixty_five_bands_tier_b(self):
        """A 696 FICO puts the total on 65.00 exactly and the band is inclusive.

        The credit term is (696 - 600) / 200 = 0.48 of 25 points = 12.00, which
        with 32.00 of experience, 12.00 of liquidity and 9.00 of career lands the
        clamped total on exactly 65.00. The PRD states: "`TIER_A` at 80.00 or
        above, `TIER_B` at 65.00 or above, `TIER_C` at 45.00 or above, and
        `TIER_D` below 45.00. The bands are inclusive at their lower edge, so a
        score of exactly 65.00 is `TIER_B` and not `TIER_C`."

        Design: Difficulty/boundary_precision_check/experience_tier_boundary_exactly_65_00_versus_64_88
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.register_borrower(**EDGE_SPONSOR)
        assert_borrower_score(
            borrower,
            intake_experience_score=65.00,
            effective_experience_score=65.00,
            experience_tier=ExperienceTier.TIER_B.value,
        )
        assert borrower["status"] == BorrowerStatus.PROSPECT.value
        assert borrower["guarantee_status"] == GuaranteeStatus.PENDING.value
        assert borrower["recertified_at"] is None

    def test_one_fico_point_below_the_edge_rounds_to_64_88_and_bands_tier_c(self):
        """A 695 FICO scores 64.875 unrounded, which rounds half up to 64.88.

        Dropping one FICO point takes the credit term to
        (695 - 600) / 200 = 0.475 of 25 = 11.875, so the raw total is 64.875 and
        the reported figure is 64.88 — twelve hundredths below the TIER_B edge
        and therefore TIER_C. The PRD states: "The raw total is then clamped to
        the range 0 through 100 and rounded half up to two decimal places. Only
        the clamped total is rounded; the four terms are carried at full
        precision until then."

        Design: Difficulty/boundary_precision_check/experience_tier_boundary_exactly_65_00_versus_64_88
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        edge = fixtures.register_borrower(**EDGE_SPONSOR)
        below = fixtures.register_borrower(
            **{**EDGE_SPONSOR, "credit_score": 695}, legal_entity_name="Larkspur LLC"
        )
        assert_borrower_score(
            below,
            intake_experience_score=64.88,
            effective_experience_score=64.88,
            experience_tier=ExperienceTier.TIER_C.value,
        )
        delta = round(
            edge["intake_experience_score"] - below["intake_experience_score"], 2
        )
        assert delta == pytest.approx(0.12, abs=1e-9), (
            f"the two sponsors must differ by exactly 0.12, got {delta}"
        )


class TestBorrowerRowShape:
    def test_registration_returns_the_scored_row_with_its_tier(self):
        """Creating a sponsor returns the whole row, score and tier included.

        A brand-new sponsor is not merely stored: the score is computed on the
        way in and returned with the created row. The PRD states: "A newly
        registered sponsor begins with `status` of `PROSPECT` and
        `guarantee_status` of `PENDING`; `guarantee_effective_date` and
        `suspension_reason` are null."

        Design: Corner/entities/borrower_creation_returns_the_full_row_with_computed_score_and_tier
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        response = api_client.create_borrower(
            factories.borrower_payload(), LOAN_OFFICER
        )
        borrower = validate_success(response, 201)

        assert_system_fields(borrower, expected_version=1)
        assert borrower["legal_entity_name"] == "Ridgeline Rehab LLC"
        assert borrower["entity_type"] == EntityType.LLC.value
        assert borrower["guarantor_name"] == "D. Ruiz"
        assert borrower["flips_last_24mo"] == 6
        assert borrower["flips_lifetime"] == 8
        assert borrower["credit_score"] == 760
        assert borrower["liquidity_cents"] == 30_000_000
        assert borrower["prior_default_count"] == 0
        assert borrower["declared_target_loan_cents"] == 30_000_000
        assert borrower["status"] == BorrowerStatus.PROSPECT.value
        assert borrower["guarantee_status"] == GuaranteeStatus.PENDING.value
        assert borrower["guarantee_effective_date"] is None
        assert borrower["suspension_reason"] is None
        # 40 experience + 20 credit + 20 liquidity + 12 career = 92.00.
        assert_borrower_score(
            borrower,
            intake_experience_score=92.00,
            effective_experience_score=92.00,
            experience_tier=ExperienceTier.TIER_A.value,
        )

    def test_reading_a_sponsor_returns_the_stored_row_unchanged(self):
        """A read never mutates: two reads match the create response exactly.

        A `GET` is not a lifecycle action, so no derived field is re-based and no
        version is consumed. The PRD states: "A recomputation of a derived field
        counts as a mutation." — a plain read performs none, so `version` stays
        on 1 and `updated_at` never moves.

        Design: Corner/entities/get_borrower_returns_the_stored_row_unchanged
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        created = fixtures.register_borrower()

        first = validate_success(
            api_client.get_borrower(created["id"], LOAN_OFFICER), 200
        )
        second = validate_success(
            api_client.get_borrower(created["id"], LOAN_OFFICER), 200
        )

        assert_same_record(created, first)
        assert_same_record(first, second)
        assert first["version"] == 1, "a read must not consume a version"


class TestDeclaredInitialStates:
    def test_every_new_row_starts_in_its_declared_initial_state(self):
        """Sponsor, property, application and scope line each open where declared.

        Four different machines are minted here and each lands on its own
        declared entry state with its counters at zero. The PRD states: "A new
        line starts at `PROPOSED` with `revision_round` at 0, `released_cents`
        at 0, `released_percent` at 0, and `approved_cost_cents` and
        `reviewer_note` both null."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")

        borrower = fixtures.register_borrower()
        assert borrower["status"] == BorrowerStatus.PROSPECT.value
        assert borrower["guarantee_status"] == GuaranteeStatus.PENDING.value

        subject = fixtures.register_property()
        assert subject["status"] == PropertyStatus.UNDER_CONTRACT.value
        assert subject["valuation_revision_count"] == 0

        contractor = fixtures.register_contractor()
        application = fixtures.open_application(borrower["id"], subject["id"])
        assert application["status"] == ApplicationStatus.DRAFT.value
        assert application["approved_rehab_total_cents"] == 0
        assert application["sizing_stale"] is False
        assert application["decline_reason"] is None
        for nullable in (
            "cap_purchase_advance_cents",
            "cap_ltc_cents",
            "cap_ltarv_cents",
            "max_total_loan_cents",
            "sized_initial_funding_cents",
            "sized_interest_reserve_cents",
            "sized_committed_amount_cents",
            "approved_loan_amount_cents",
            "alloc_initial_funding_cents",
            "alloc_interest_reserve_cents",
            "alloc_rehab_holdback_cents",
        ):
            assert application[nullable] is None, f"{nullable} must open null"

        line = fixtures.add_scope_line(
            application["id"], fixtures.THREE_LINE_SCOPE[0], contractor["id"]
        )
        assert line["status"] == RehabLineItemStatus.PROPOSED.value
        assert line["revision_round"] == 0
        assert line["released_cents"] == 0
        assert line["released_percent"] == pytest.approx(0.0)
        assert line["approved_cost_cents"] is None
        assert line["reviewer_note"] is None


class TestSponsorLifecycle:
    def test_guarantee_then_approval_advances_the_sponsor(self):
        """Executing the guarantee unlocks the approval that advances the sponsor.

        The guarantee write is what flips `guarantee_status`, and only then can
        the committee advance the status axis. The PRD states: "Recording
        execution takes a `guarantor_name`, a `signature_ref` identifying the
        signed instrument, and an `effective_date`; it sets `guarantee_status` to
        `EXECUTED` and stores `guarantee_effective_date` from the supplied
        `effective_date`."

        Design: Corner/state_machines/guarantee_execution_then_sponsor_approval_advances_the_borrower
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.register_borrower()

        executed = validate_success(
            api_client.record_guarantee(
                borrower["id"], factories.guarantee_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert executed["guarantee_status"] == GuaranteeStatus.EXECUTED.value
        assert executed["guarantee_effective_date"] == "2026-08-10"
        assert executed["status"] == BorrowerStatus.PROSPECT.value, (
            "the guarantee write must not advance the status axis by itself"
        )

        approved = validate_success(
            api_client.borrower_status_action(
                borrower["id"], factories.approve_sponsor_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        assert approved["status"] == BorrowerStatus.APPROVED_SPONSOR.value
        assert approved["guarantee_status"] == GuaranteeStatus.EXECUTED.value
        assert approved["suspension_reason"] is None

    def test_a_second_approval_is_refused_on_state(self):
        """The approval edge leaves `PROSPECT` only, so a repeat is a state error.

        Re-approving an already-approved sponsor has no source state to leave.
        The PRD states: "Approving a sponsor advances `PROSPECT →
        APPROVED_SPONSOR` and requires three things" — and the target entity's
        own state is checked at rung 9 of the precedence ladder, reported as
        `ERR_BORROWER_STATE_INVALID`.

        Design: Corner/state_machines/a_second_sponsor_approval_is_rejected_rather_than_absorbed
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.build_approved_sponsor()
        assert borrower["status"] == BorrowerStatus.APPROVED_SPONSOR.value
        version_after_first = borrower["version"]

        response = api_client.borrower_status_action(
            borrower["id"], factories.approve_sponsor_payload(), CREDIT_COMMITTEE
        )
        validate_error(response, ApiErrorId.BORROWER_STATE_INVALID.value)

        unchanged = validate_success(
            api_client.get_borrower(borrower["id"], LOAN_OFFICER), 200
        )
        assert unchanged["status"] == BorrowerStatus.APPROVED_SPONSOR.value
        assert unchanged["version"] == version_after_first, (
            "a rejected approval must not consume a version"
        )


class TestSponsorEligibilityGates:
    def test_approval_and_sizing_each_enforce_their_own_sponsor_gate(self):
        """The three approval gates fire, and sizing re-checks sponsor standing.

        An unexecuted guarantee, a sole proprietorship and a TIER_D sponsor each
        block approval with their own code, and an application whose sponsor was
        never approved cannot be sized. The PRD states: "A first sizing requires
        the sponsor to be `APPROVED_SPONSOR` (otherwise
        `ERR_BORROWER_NOT_ELIGIBLE`), at least one scope line in `APPROVED`, and
        no scope line still sitting in `PROPOSED` or `REVISION_REQUESTED`".

        Design: Corner/validations/sponsor_eligibility_is_checked_at_approval_and_at_application
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")

        pending = fixtures.register_borrower(legal_entity_name="Pending Guarantee LLC")
        validate_error(
            api_client.borrower_status_action(
                pending["id"], factories.approve_sponsor_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.GUARANTEE_NOT_EXECUTED.value,
        )

        sole_prop = fixtures.register_borrower(
            legal_entity_name="Ruiz Sole Trader",
            entity_type=EntityType.SOLE_PROP.value,
        )
        fixtures.execute_guarantee(sole_prop["id"])
        validate_error(
            api_client.borrower_status_action(
                sole_prop["id"], factories.approve_sponsor_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.ENTITY_TYPE_NOT_ELIGIBLE.value,
        )

        # 0 experience + 2.50 credit + 0 liquidity + 0 career = 2.50 -> TIER_D.
        thin = fixtures.register_borrower(
            legal_entity_name="Thin File LLC",
            flips_last_24mo=0,
            flips_lifetime=0,
            credit_score=620,
            liquidity_cents=0,
        )
        assert thin["experience_tier"] == ExperienceTier.TIER_D.value
        fixtures.execute_guarantee(thin["id"])
        validate_error(
            api_client.borrower_status_action(
                thin["id"], factories.approve_sponsor_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.BORROWER_NOT_ELIGIBLE.value,
        )

        # A sole proprietorship cannot even open an application.
        subject = fixtures.register_property()
        validate_error(
            api_client.create_application(
                factories.application_payload(sole_prop["id"], subject["id"]),
                LOAN_OFFICER,
            ),
            ApiErrorId.ENTITY_TYPE_NOT_ELIGIBLE.value,
        )

        # And an application whose sponsor is still PROSPECT cannot be sized.
        contractor = fixtures.register_contractor()
        application = fixtures.open_application(pending["id"], subject["id"])
        # Two equal-cost lines, so each approval clears the concentration cap that
        # is measured across the application's live lines at review time.
        line = fixtures.add_scope_line(
            application["id"], fixtures.THREE_LINE_SCOPE[0], contractor["id"]
        )
        sibling = fixtures.add_scope_line(
            application["id"],
            fixtures.ScopeSpec("KITCHEN", 4_000_000, 0, "Cabinets and counters"),
            contractor["id"],
        )
        fixtures.approve_scope_line(line["id"])
        fixtures.approve_scope_line(sibling["id"])
        validate_error(
            api_client.size_application(
                application["id"], factories.size_payload(), LOAN_OFFICER
            ),
            ApiErrorId.BORROWER_NOT_ELIGIBLE.value,
        )

        # Executing the guarantee and approving the sponsor unblocks the sizing.
        fixtures.execute_guarantee(pending["id"])
        fixtures.approve_sponsor(pending["id"])
        sized = validate_success(
            api_client.size_application(
                application["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert sized["status"] == ApplicationStatus.SIZED.value
