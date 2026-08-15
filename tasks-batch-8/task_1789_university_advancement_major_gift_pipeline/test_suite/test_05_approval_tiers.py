"""Approval tier multi-input branching: type multiplier, trusted-capacity shift,
organization exemption, and tier-role mapping."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_rated_assigned_prospect, create_submitted_proposal,
    create_approved_proposal, get_proposal,
)

DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]


class TestApprovalTierMultiInputBranching:
    """Queue A: combinatorial_formula / approval_tier_multi_input_branching."""

    def test_band_a_individual_shifts_principal_down_to_major(self, api):
        """PRD §3.4: "A trusted-capacity shift then applies: when the prospect's
        `prospect_type` is `INDIVIDUAL` and the pinned capacity band is `A`, the
        tier shifts one step down — `PRINCIPAL` becomes `MAJOR`, `MAJOR` becomes
        `STANDARD`, and `STANDARD` stays `STANDARD` — reflecting the office's
        confidence in its best-understood donors; `ORGANIZATION` prospects never
        shift."

        Design: Difficulty/combinatorial_formula/approval_tier_multi_input_branching
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=2000000000,  # band A after VERIFIED x1.0
            prospect_type="INDIVIDUAL", move_to="CULTIVATION",
            max_prospect_count=5, max_open_ask_cents=10000000000,
            engagement_score=90, philanthropy_score=90, recency_score=90,
        )
        assert p["capacity_band"] == "A"
        prop = create_submitted_proposal(p["id"], f["id"], 150000000, designation_purpose="Endowment")
        assert prop["approval_tier"] == "MAJOR"  # PRINCIPAL shifted one step down
        assert prop["pinned_capacity_band"] == "A"

    def test_band_a_organization_does_not_shift(self, api):
        """PRD §3.4: "A trusted-capacity shift then applies: when the prospect's
        `prospect_type` is `INDIVIDUAL` and the pinned capacity band is `A`, the
        tier shifts one step down — `PRINCIPAL` becomes `MAJOR`, `MAJOR` becomes
        `STANDARD`, and `STANDARD` stays `STANDARD` — reflecting the office's
        confidence in its best-understood donors; `ORGANIZATION` prospects never
        shift."

        Design: Difficulty/combinatorial_formula/approval_tier_multi_input_branching
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=2000000000,
            prospect_type="ORGANIZATION", move_to="CULTIVATION",
            max_prospect_count=5, max_open_ask_cents=10000000000,
            engagement_score=90, philanthropy_score=90, recency_score=90,
        )
        assert p["capacity_band"] == "A"
        prop = create_submitted_proposal(p["id"], f["id"], 150000000, designation_purpose="Endowment")
        assert prop["approval_tier"] == "PRINCIPAL"  # shift blocked for organizations

    def test_planned_gift_counts_at_half_face_for_tiering(self, api):
        """PRD §3.4: "The proposal's `effective_ask_cents` is the
        `ask_amount_cents` multiplied by the type multiplier — 1.0 for
        `OUTRIGHT`, 1.0 for `PLEDGE`, and 0.5 for `PLANNED` — rounded half up to
        a whole cent; planned gifts therefore count at half their face value for
        tiering."

        Design: Difficulty/combinatorial_formula/approval_tier_multi_input_branching
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=200000000,  # band B
            prospect_type="INDIVIDUAL", move_to="CULTIVATION",
            max_prospect_count=5, max_open_ask_cents=10000000000,
            engagement_score=50, philanthropy_score=50, recency_score=50,
        )
        assert p["capacity_band"] == "B"
        prop = create_submitted_proposal(
            p["id"], f["id"], 120000000, proposal_type="PLANNED",
            designation_purpose="Bequest",
        )
        assert prop["effective_ask_cents"] == 60000000  # round_half_up(120000000 * 0.5)
        assert prop["approval_tier"] == "MAJOR"  # 25000000 <= 60000000 < 100000000


class TestTierRoleMapping:
    def test_tier_role_violation_rejected(self, api):
        """PRD §3.4: "A reviewer — `AdvancementDirector` or `VPAdvancement`,
        matching the tier's requirement or the request fails with
        `ERR_TIER_APPROVAL_ROLE_VIOLATION` — acts on a proposal in
        `UNDER_REVIEW` (otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`)."
        PRD §3.4: "a `STANDARD` proposal needs exactly one `AdvancementDirector`
        approval, a `MAJOR` proposal exactly one `VPAdvancement` approval, and a
        `PRINCIPAL` proposal a quorum of two distinct `VPAdvancement` approvals."

        Design: Corner/validations/tier_role_violation_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(
            assessed_capacity_cents=200000000, move_to="CULTIVATION",
            max_open_ask_cents=1000000000,
        )
        prop = create_submitted_proposal(p["id"], f["id"], 30000000)
        assert prop["approval_tier"] == "MAJOR"  # 25000000 <= 30000000 < 100000000

        resp = api.review_proposal(prop["id"], {"decision": "APPROVE"}, DIR)
        validate_error(resp, ApiErrorId.ERR_TIER_APPROVAL_ROLE_VIOLATION)

        d = validate_success(api.review_proposal(prop["id"], {"decision": "APPROVE"}, VP))
        assert d["status"] == "APPROVED"
