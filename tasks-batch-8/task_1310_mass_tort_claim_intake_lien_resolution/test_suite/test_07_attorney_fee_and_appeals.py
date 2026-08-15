"""Attorney-fee nested rounding, appeal branching, re-tier cascades, and the
active-appeal pointer invariant."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_tier_assigned_claim,
    create_claim_with_two_published_tiers, create_claim_with_open_appeal,
    create_claim_with_appeal_under_review,
    file_appeal, add_lien_in_state, get_claim_version,
    appeal_rationale_payload, create_appeal_payload,
    make_claimant_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
LIEN_HEADERS = TEST_USERS["lien_analyst_headers"]


def _resolve_two_small_liens(ctx, finals=(101, 103)):
    """Resolve two PRIVATE_INSURER liens at the given negotiated finals."""
    pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
    liens = []
    for i, final in enumerate(finals):
        holder = f"InsCo {chr(ord('A') + i)}"
        lien = add_lien_in_state(pid, cid, "RESOLVED", resolve_final_demand_cents=final,
                                 lien_type="PRIVATE_INSURER", holder_name=holder,
                                 asserted_amount_cents=final)
        liens.append(lien)
    return liens


class TestAttorneyFeeNestedRounding:
    def test_resolve_sums_total_lien_across_resolved_liens(self, api, program_admin_headers):
        """PRD §3.5: "Either resolution path recomputes the claim's `total_lien_cents` as the sum of `final_demand_cents` across the claim's liens in `RESOLVED` state and recomputes `net_award_cents`, and both advance the claim's `version` by 1."

        Design: Difficulty/dual_variant_calc/attorney_fee_per_line_vs_sum_then_round
        """
        ctx = create_tier_assigned_claim(base_award_cents=1_000, represented_by_counsel=True,
                                         severities=(80, 70), severity_min=50, severity_max=100)
        _resolve_two_small_liens(ctx, finals=(101, 103))
        claim = validate_success(api.get_claim(ctx["program"]["id"], ctx["claim"]["id"],
                                               program_admin_headers))
        assert claim["total_lien_cents"] == 204, (
            f"total_lien_cents = 101 + 103 = 204, got {claim['total_lien_cents']}"
        )


class TestAttorneyFeeRoundingOrderModeB:
    def test_net_award_floored_at_zero(self, api, program_admin_headers):
        """PRD §3.7: "The **net award** is `gross_award_cents` minus `total_lien_cents` minus `attorney_fee_cents`, floored at zero. It is recomputed at tier assignment, at every lien resolution or waiver, at lien finalization, and at every appeal outcome that re-tiers the claim."

        Design: Difficulty/combinatorial_formula/attorney_fee_nested_rounding_mode_b
        """
        # gross = 1000, single lien resolved at the full 1000. The lien takes the
        # entire gross, so raw net (gross - liens - fee) is negative under any
        # non-negative fee and the floor must clamp it to zero.
        ctx = create_tier_assigned_claim(base_award_cents=1_000, represented_by_counsel=True,
                                         severities=(80, 70), severity_min=50, severity_max=100)
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        add_lien_in_state(pid, cid, "RESOLVED", resolve_final_demand_cents=1_000,
                          lien_type="PRIVATE_INSURER", holder_name="InsCo Full",
                          asserted_amount_cents=1_000)
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["net_award_cents"] == 0, (
            f"net = 1000 - 1000 - fee must floor at zero, got {claim['net_award_cents']}"
        )


class TestAttorneyFeeNoCounsel:
    def test_fee_zero_without_counsel(self, api, program_admin_headers):
        """PRD §3.7: "When the claimant's `represented_by_counsel` is false, `attorney_fee_cents` is zero."

        Design: Corner/calculations/attorney_fee_zero_when_no_counsel
        """
        ctx = create_tier_assigned_claim(base_award_cents=5_000_000, represented_by_counsel=False,
                                         severities=(70, 65))
        claim = validate_success(api.get_claim(ctx["program"]["id"], ctx["claim"]["id"],
                                               program_admin_headers))
        assert claim["attorney_fee_cents"] == 0


class TestAppealBranching:
    def test_appeal_progress_fork_to_upheld_retiers(self, api, program_admin_headers):
        """PRD §3.6: "Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null."

        Design: Difficulty/non_linear_state_machine/appeal_branching_with_revert_on_appeal
        """
        ctx = create_claim_with_appeal_under_review()
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        reviewed = validate_success(api.get_appeal(pid, cid, aid, program_admin_headers))
        assert reviewed["state"] == "UNDER_REVIEW"
        upheld = validate_success(
            api.uphold_appeal(pid, cid, aid, appeal_rationale_payload(
                resolution_rationale="New evidence accepted; re-tier applied."), program_admin_headers)
        )
        assert upheld["state"] == "UPHELD"
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["gross_award_cents"] == 8_000_000, (
            f"re-tier to requested matrix row must set gross to 8000000, got {claim['gross_award_cents']}"
        )

    def test_appeal_withdraw_revert_from_filed(self, api, program_admin_headers):
        """PRD §3.6: "The claimant may also withdraw an appeal, but only while it is still `FILED`; withdrawal moves it to `WITHDRAWN`, clears `active_appeal_id`, and advances the claim's `version`."

        Design: Difficulty/non_linear_state_machine/appeal_branching_with_revert_on_appeal
        """
        ctx = create_claim_with_open_appeal()
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        withdrawn = validate_success(
            api.withdraw_appeal(pid, cid, aid, make_claimant_headers(ctx["claimant"]["id"]))
        )
        assert withdrawn["state"] == "WITHDRAWN"
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["active_appeal_id"] is None


class TestAppealUpholdCascadeDepth3:
    def test_uphold_recomputes_gross_fee_net_chain(self, api, program_admin_headers):
        """PRD §3.6: "Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null."

        Design: Difficulty/transitive_cascade/appeal_uphold_cascade_depth3
        """
        ctx = create_claim_with_appeal_under_review(represented_by_counsel=False)
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        assert ctx["claim"]["gross_award_cents"] == 3_000_000
        validate_success(api.uphold_appeal(pid, cid, aid, appeal_rationale_payload(
            resolution_rationale="Re-tier to high matrix row justified"), program_admin_headers))
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["gross_award_cents"] == 8_000_000, "link 1: gross recomputed"
        assert claim["attorney_fee_cents"] == 0, "link 2: no counsel -> fee stays 0"
        assert claim["net_award_cents"] == 8_000_000, "link 3: net = gross - liens(0) - fee(0)"
        assert claim["active_appeal_id"] is None

    def test_uphold_clears_active_appeal_and_advances_version(self, api, program_admin_headers):
        """PRD §3.6: "Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null. Denying the appeal moves it to `DENIED` and clears `active_appeal_id` without touching the award figures. Either outcome advances the claim's `version` by 1."

        Design: Difficulty/transitive_cascade/appeal_uphold_cascade_depth3
        """
        ctx = create_claim_with_appeal_under_review(represented_by_counsel=False)
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        version_before = get_claim_version(pid, cid)
        upheld = validate_success(api.uphold_appeal(
            pid, cid, aid,
            appeal_rationale_payload(resolution_rationale="Re-tier to high matrix row justified"),
            program_admin_headers,
        ))
        assert upheld["state"] == "UPHELD"
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["active_appeal_id"] is None
        assert claim["version"] == version_before + 1, (
            f"appeal outcome must advance claim version by 1: {version_before} -> {claim['version']}"
        )

    def test_uphold_with_counsel_recomputes_fee_from_new_gross(self, api, program_admin_headers):
        """PRD §3.6: "Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null."

        Design: Corner/cross_cutting_layers/cascading_side_effects_appeal_uphold_ripples_to_net_award
        """
        ctx = create_claim_with_appeal_under_review(represented_by_counsel=True)
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        # Before: gross 3000000, fee = round(3000000*0.4) = 1200000, net = 1800000.
        assert ctx["claim"]["attorney_fee_cents"] == 1_200_000
        assert ctx["claim"]["net_award_cents"] == 1_800_000
        validate_success(api.uphold_appeal(pid, cid, aid, appeal_rationale_payload(
            resolution_rationale="Re-tier applied to higher matrix"), program_admin_headers))
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["gross_award_cents"] == 8_000_000
        assert claim["attorney_fee_cents"] == 3_200_000, (
            f"fee = round(8000000*0.4) = 3200000, got {claim['attorney_fee_cents']}"
        )
        assert claim["net_award_cents"] == 4_800_000


class TestActiveAppealInvariant:
    def test_file_sets_and_withdraw_clears_active_appeal(self, api, program_admin_headers):
        """PRD §3.6: "A successful filing creates the appeal in `FILED` state, writes its id into the claim's `active_appeal_id`, and advances the claim's `version` by 1."
        PRD §3.6: "The claimant may also withdraw an appeal, but only while it is still `FILED`; withdrawal moves it to `WITHDRAWN`, clears `active_appeal_id`, and advances the claim's `version`."

        Design: Difficulty/compensating_invariant/appeal_uphold_then_withdraw_conserves_active_appeal_count
        """
        ctx = create_claim_with_two_published_tiers()
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        assert ctx["claim"]["active_appeal_id"] is None
        appeal = file_appeal(pid, cid, ctx["claimant"]["id"],
                             ctx["matrix_low"]["id"], ctx["matrix_high"]["id"])
        claim_after_file = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim_after_file["active_appeal_id"] == appeal["id"]
        validate_success(api.withdraw_appeal(pid, cid, appeal["id"],
                                             make_claimant_headers(ctx["claimant"]["id"])))
        claim_after_withdraw = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim_after_withdraw["active_appeal_id"] is None, (
            "withdrawal is the compensating action that restores active_appeal_id to null"
        )

    def test_uphold_clears_active_appeal(self, api, program_admin_headers):
        """PRD §3.6: "Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null."

        Design: Difficulty/compensating_invariant/appeal_uphold_then_withdraw_conserves_active_appeal_count
        """
        ctx = create_claim_with_appeal_under_review()
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        validate_success(api.uphold_appeal(pid, cid, aid, appeal_rationale_payload(
            resolution_rationale="Re-tier applied after review."), program_admin_headers))
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["active_appeal_id"] is None


class TestAppealGates:
    def test_second_appeal_while_open_rejected(self, api):
        """PRD §3.6: "Filing is rejected with `ERR_CLAIM_INVALID_STATE` when the claim is not `TIER_ASSIGNED`, and with `ERR_APPEAL_ALREADY_OPEN` (HTTP 409) when `active_appeal_id` is already non-null."

        Design: Corner/errors/err_appeal_already_open_triggerable
        """
        ctx = create_claim_with_open_appeal()
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        resp = api.create_appeal(
            pid, cid,
            create_appeal_payload(ctx["matrix_low"]["id"], ctx["matrix_high"]["id"],
                                  grounds="Second appeal attempt grounds"),
            make_claimant_headers(ctx["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_OPEN)

    def test_finalize_liens_blocked_by_open_appeal(self, api, lien_analyst_headers):
        """PRD §3.5: "Finalization is blocked, with `ERR_UNRESOLVED_LIENS_EXIST` (HTTP 409), while any lien remains in `IDENTIFIED`, `NOTIFIED`, `IN_NEGOTIATION`, or `DISPUTED`; and it is blocked, with `ERR_OPEN_APPEAL_BLOCKS_FINALIZE` (HTTP 409), while the claim's `active_appeal_id` is non-null."

        Design: Difficulty/cross_entity_state_dependency/finalize_liens_depends_on_appeal
        """
        ctx = create_claim_with_open_appeal()
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        # All liens resolved, but the appeal is still open.
        add_lien_in_state(pid, cid, "RESOLVED", resolve_final_demand_cents=40_000,
                          lien_type="MEDICARE", holder_name="CMS", asserted_amount_cents=50_000)
        resp = api.finalize_liens(pid, cid, lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_APPEAL_BLOCKS_FINALIZE)

    def test_finalize_liens_succeeds_after_appeal_withdrawn(self, api, lien_analyst_headers):
        """PRD §3.5: "When every lien on the claim has reached `RESOLVED` or `WAIVED`, the `LienAnalyst` finalizes liens, moving the claim from `LIENS_PENDING` to `LIENS_RESOLVED` and setting `lien_posture` to `ALL_RESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/finalize_liens_depends_on_appeal
        """
        ctx = create_claim_with_open_appeal()
        pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
        add_lien_in_state(pid, cid, "RESOLVED", resolve_final_demand_cents=40_000,
                          lien_type="MEDICARE", holder_name="CMS", asserted_amount_cents=50_000)
        # Clearing the appeal removes the cross-entity gate.
        validate_success(api.withdraw_appeal(pid, cid, aid, make_claimant_headers(ctx["claimant"]["id"])))
        claim = validate_success(api.finalize_liens(pid, cid, lien_analyst_headers))
        assert claim["status"] == "LIENS_RESOLVED"
        assert claim["lien_posture"] == "ALL_RESOLVED"
