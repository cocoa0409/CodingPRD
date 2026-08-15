"""Design review cycle: tiered fees, revision loop, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_review,
    create_active_engagement,
    create_assembly,
    create_design_review,
    drive_review_through_cycle,
    get_engagement,
    make_field_technician_headers,
    make_reviewer_headers,
    start_review,
    validate_error,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestDesignReviewFeeTieredBranching:
    """Two revision cycles, three barriers, 18 drawings -> fee 812000."""

    def _setup_review_with_two_cycles(self):
        eng = create_active_engagement(name="E3")
        asm = create_assembly(eng["id"], tag="W3", assembly_type="MASONRY",
                              design_u_factor=1.2,
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"],
                                   barrier_scope=["AIR", "WATER", "THERMAL"],
                                   drawing_count=18)
        start_review(eng["id"], rev["id"], "rev-user-1")
        drive_review_through_cycle(eng["id"], rev["id"], "rev-user-1")
        drive_review_through_cycle(eng["id"], rev["id"], "rev-user-1")
        return eng, rev

    def test_review_fee_combines_tier_barrier_and_revision_surcharges(self):
        """PRD §3.2: "The design review fee is a tiered price evaluated in a
        pinned order: base tier first, then barrier surcharge, then revision
        surcharge, all in integer cents. The base depends on `drawing_count`:
        a round reviewing at most 5 drawings bills a flat 250000 cents; a round
        reviewing more than 5 but at most 15 drawings bills 250000 cents plus
        30000 cents for each drawing beyond the fifth; a round reviewing more
        than 15 drawings bills 250000 cents plus 300000 cents (the full second
        tier) plus 20000 cents for each drawing beyond the fifteenth. The
        barrier surcharge adds 40000 cents for each barrier layer in
        `barrier_scope` beyond the first. The revision surcharge is ten percent
        of the base for each completed revision round — `revision_round`
        multiplied by ten percent of the base — rounded half-up to whole
        cents."
        PRD §3.2: "Approval flips the assembly's `review_status` to `APPROVED`,
        computes the round's `review_fee_cents` as described below, adds that
        fee to the engagement's `recognized_fees_cents` under the provisional
        accrual of §2.7, and re-derives the engagement posture."

        Design: Difficulty/combinatorial_formula/design_review_fee_tiered_branching
        """
        eng, rev = self._setup_review_with_two_cycles()
        # Approval at revision_round 2 must come from a different reviewer.
        resp = api_client.approve_review(eng["id"], rev["id"],
                                         make_reviewer_headers("rev-user-2"))
        data = validate_success(resp, 200)
        # base = 250000 + 300000 + 3*20000 = 610000; barrier = 2*40000 = 80000;
        # revision = round_half_up(2 * 0.10 * 610000) = 122000.
        assert data["review_fee_cents"] == 812000
        assert data["revision_round"] == 2
        assert data["status"] == "APPROVED"
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 812000

    def test_review_fee_tier_boundary_five_vs_six_drawings(self):
        """PRD §3.2: "a round reviewing at most 5 drawings bills a flat 250000
        cents; a round reviewing more than 5 but at most 15 drawings bills
        250000 cents plus 30000 cents for each drawing beyond the fifth".

        Design: Difficulty/combinatorial_formula/design_review_fee_tiered_branching
        """
        eng = create_active_engagement(name="E3B")
        fees = {}
        for tag, drawings in (("W3B-5", 5), ("W3B-6", 6)):
            asm = create_assembly(eng["id"], tag=tag, assembly_type="MASONRY",
                                  design_u_factor=1.2,
                                  required_airtightness_lps_m2=2.0)
            rev = create_design_review(eng["id"], asm["id"],
                                       barrier_scope=["AIR"],
                                       drawing_count=drawings)
            start_review(eng["id"], rev["id"], "rev-user-1")
            data = approve_review(eng["id"], rev["id"], "rev-user-1")
            fees[drawings] = data["review_fee_cents"]
        assert fees[5] == 250000
        assert fees[6] == 280000


class TestDesignReviewCyclicRevisionLoop:

    def _setup_review_at_round_one_under_review(self):
        """One full cycle: review is UNDER_REVIEW again, revision_round == 1,
        and rev-user-1 is the round's recorded comment issuer."""
        eng = create_active_engagement(name="E5")
        asm = create_assembly(eng["id"], tag="W5", assembly_type="ROOFING",
                              design_u_factor=0.9,
                              required_airtightness_lps_m2=2.5)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["WATER"],
                                   drawing_count=3)
        start_review(eng["id"], rev["id"], "rev-user-1")
        drive_review_through_cycle(eng["id"], rev["id"], "rev-user-1")
        return eng, rev

    def test_cycle_approve_by_round_comment_issuer_rejected(self):
        """PRD §3.2: "if the round has been revised at least once (that is,
        `revision_round` is 1 or more), the approving reviewer's `X-User-ID`
        must differ from the `reviewer_id` who issued the current round's
        comments — the reviewer who issued comments on a round may never
        approve that same round, and a violation is rejected with
        `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403)."
        PRD §3.2: "A `Consultant` then answers with a revision, moving the
        round from `COMMENTS_ISSUED` to `REVISED` and incrementing
        `revision_round` by 1."

        Design: Difficulty/non_linear_state_machine/design_review_cyclic_revision_loop
        """
        eng, rev = self._setup_review_at_round_one_under_review()
        resp = api_client.approve_review(eng["id"], rev["id"],
                                         make_reviewer_headers("rev-user-1"))
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
        after = validate_success(
            api_client.get_design_review(eng["id"], rev["id"], C), 200)
        assert after["revision_round"] == 1
        assert after["status"] == "UNDER_REVIEW"
        assert after["reviewer_id"] == "rev-user-1"

    def test_revision_round_increments_once_per_cycle(self):
        """PRD §3.2: "A `Reviewer` may start the next look, which cycles the
        round from `REVISED` back to `UNDER_REVIEW`; the `reviewer_id` recorded
        on the prior round is deliberately retained through this re-entry,
        because it anchors the segregation-of-duties check at approval time."
        PRD §3.2: "A `Consultant` then answers with a revision, moving the
        round from `COMMENTS_ISSUED` to `REVISED` and incrementing
        `revision_round` by 1."

        Design: Difficulty/non_linear_state_machine/design_review_cyclic_revision_loop
        """
        eng, rev = self._setup_review_at_round_one_under_review()
        drive_review_through_cycle(eng["id"], rev["id"], "rev-user-1")
        data = validate_success(
            api_client.get_design_review(eng["id"], rev["id"], C), 200)
        assert data["revision_round"] == 2
        assert data["status"] == "UNDER_REVIEW"
        assert data["reviewer_id"] == "rev-user-1"
        # A different reviewer may approve the re-reviewed round.
        approved = approve_review(eng["id"], rev["id"], "rev-user-2")
        assert approved["status"] == "APPROVED"


class TestDesignReviewStateGates:

    def test_design_review_reject_from_submitted_invalid(self):
        """PRD §3.2: "starting a round that is not in `SUBMITTED` (or, on the
        re-entry path described below, not in `REVISED`) is rejected with
        `ERR_REVIEW_NOT_ACTIONABLE` (HTTP 409)."
        PRD §3.2: "Approval by a `Reviewer` moves the round from `UNDER_REVIEW`
        to `APPROVED` and is guarded by three conditions: the round must be
        `UNDER_REVIEW`..."
        PRD §2.11: "The target entity's own state preconditions for the invoked
        transition — the family of not-actionable errors such as
        `ERR_REVIEW_NOT_ACTIONABLE`..."

        Design: Corner/state_machines/design_review_reject_from_submitted_invalid
        """
        eng = create_active_engagement(name="ER")
        asm = create_assembly(eng["id"], tag="AR", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["AIR"],
                                   drawing_count=2)
        resp = api_client.approve_review(eng["id"], rev["id"],
                                         make_reviewer_headers("rev-user-1"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ACTIONABLE)
        data = validate_success(
            api_client.get_design_review(eng["id"], rev["id"], C), 200)
        assert data["status"] == "SUBMITTED"


class TestDesignReviewRbac:

    def test_field_technician_cannot_begin_review(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: the start-review endpoint row lists `Reviewer` as its only
        authorized role.

        Design: Corner/rbac/field_technician_cannot_begin_review
        """
        eng = create_active_engagement(name="EFT")
        asm = create_assembly(eng["id"], tag="AFT", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["AIR"],
                                   drawing_count=1)
        resp = api_client.start_review(
            eng["id"], rev["id"],
            make_field_technician_headers("tech-user-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        data = validate_success(
            api_client.get_design_review(eng["id"], rev["id"], C), 200)
        assert data["status"] == "SUBMITTED"

    def test_reviewer_cannot_create_assembly(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: the create-assembly endpoint row lists `Consultant` as its only
        authorized role.

        Design: Corner/rbac/reviewer_cannot_create_assembly
        """
        eng = create_active_engagement(name="ERB")
        resp = api_client.create_assembly(
            eng["id"],
            {"tag": "RB", "assembly_type": "MASONRY", "design_u_factor": 1.0,
             "required_airtightness_lps_m2": 2.0},
            make_reviewer_headers("rev-user-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestAssemblyRegistration:

    def test_assembly_duplicate_tag_rejected(self):
        """PRD §3.1: "The `tag` must be unique within the engagement under
        case-sensitive comparison; a duplicate registration is rejected with
        `ERR_DUPLICATE_ASSEMBLY_TAG` (HTTP 409)."

        Design: Corner/entities/assembly_duplicate_tag_rejected
        """
        eng = create_active_engagement(name="E")
        eng2 = create_active_engagement(name="E2")
        create_assembly(eng["id"], tag="W1", assembly_type="MASONRY",
                        design_u_factor=1.0, required_airtightness_lps_m2=2.0)
        resp = api_client.create_assembly(
            eng["id"],
            {"tag": "W1", "assembly_type": "ROOFING", "design_u_factor": 0.9,
             "required_airtightness_lps_m2": 2.5},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSEMBLY_TAG)
        # The same tag on a different engagement is allowed.
        resp = api_client.create_assembly(
            eng2["id"],
            {"tag": "W1", "assembly_type": "ROOFING", "design_u_factor": 0.9,
             "required_airtightness_lps_m2": 2.5},
            C,
        )
        data = validate_success(resp, 201)
        assert data["tag"] == "W1"
