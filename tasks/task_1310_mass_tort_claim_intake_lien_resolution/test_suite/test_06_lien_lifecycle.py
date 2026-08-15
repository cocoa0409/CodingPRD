"""Lien lifecycle: provisional demands, holder window, negotiated vs silent
resolution, waiver, dispute cycle, and finalization gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_lien,
    create_program, create_tier_assigned_claim, create_claim_in_liens_pending,
    add_lien, add_lien_in_state, get_claim_version,
    create_published_matrix, create_claimant, create_injury_verified_claim,
    assign_tier_with_fresh_version,
    make_claimant_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
LIEN_HEADERS = TEST_USERS["lien_analyst_headers"]


class TestProvisionalDemandRates:
    def test_medicaid_provisional_and_due_date(self, api, lien_analyst_headers):
        """PRD §3.5: "`MEDICAID` is fifty percent; `VA_TRICARE` is seventy percent; `PRIVATE_INSURER` is seventy-five percent."
        PRD §3.5: "That window is fixed at thirty days: notification stamps `holder_response_due_at` as the program's `current_utc` plus thirty days, read from the program logical clock."

        Design: Corner/state_machines/lien_notify_computes_provisional_and_due_date
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICAID", holder_name="State DHHS",
                                            asserted_amount_cents=200_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        resp = api.notify_lien(pid, cid, lid, lien_analyst_headers)
        data = validate_success(resp)
        assert_lien(data)
        assert data["state"] == "NOTIFIED"
        assert data["provisional_demand_cents"] == 100_000, (
            f"MEDICAID provisional = 200000 * 0.50 = 100000, got {data['provisional_demand_cents']}"
        )
        assert data["holder_response_due_at"] == "2026-08-31T00:00:00Z", (
            f"due date = default clock 2026-08-01 + 30 days, got {data['holder_response_due_at']}"
        )

    def test_medicare_provisional_uses_sixty_percent(self, api, lien_analyst_headers):
        """PRD §3.5: "A `MEDICARE` lien's `provisional_demand_cents` is sixty percent of the asserted amount; `MEDICAID` is fifty percent; `VA_TRICARE` is seventy percent; `PRIVATE_INSURER` is seventy-five percent."

        Design: Corner/calculations/provisional_medicare_uses_060_rate
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=250_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        resp = api.notify_lien(pid, cid, lid, lien_analyst_headers)
        data = validate_success(resp)
        assert data["provisional_demand_cents"] == 150_000, (
            f"MEDICARE provisional = 250000 * 0.60 = 150000, got {data['provisional_demand_cents']}"
        )

    def test_provisional_demand_differs_by_holder_type(self, api, lien_analyst_headers):
        """PRD §3.5: "Notification triggers the provisional-demand calculation: a discount is applied to `asserted_amount_cents` according to holder type, each multiplication rounded half up to integer cents."

        Design: Corner/state_machines/lien_notify_computes_provisional_and_due_date
        """
        # VA_TRICARE at 0.70 on the same asserted amount yields a different
        # provisional than MEDICAID at 0.50 — the rate is holder-type driven.
        ctx = create_claim_in_liens_pending(lien_type="VA_TRICARE", holder_name="VA",
                                            asserted_amount_cents=200_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        resp = api.notify_lien(pid, cid, lid, lien_analyst_headers)
        data = validate_success(resp)
        assert data["provisional_demand_cents"] == 140_000, (
            f"VA_TRICARE provisional = 200000 * 0.70 = 140000, got {data['provisional_demand_cents']}"
        )


class TestProvisionalVsFinalDualVariant:
    def test_medicare_provisional_discounted_final_silent_full_asserted(self, api, lien_analyst_headers, program_admin_headers):
        """PRD §3.5: "On this path the server sets `final_demand_cents` equal to the full `asserted_amount_cents` — the discount evaporates with the deadline — and the client cannot override the figure on this path."

        Design: Difficulty/dual_variant_calc/lien_demand_provisional_vs_final_medicare
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=100_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        notified = validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        assert notified["provisional_demand_cents"] == 60_000
        # Advance the program clock past the 30-day holder window.
        validate_success(api.set_clock(pid, {"to_iso8601": "2026-09-15T00:00:00Z"}, program_admin_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resolved = validate_success(api.resolve_lien(pid, cid, lid, {"expected_claim_version": version},
                                                     lien_analyst_headers))
        assert resolved["state"] == "RESOLVED"
        assert resolved["final_demand_cents"] == 100_000, (
            f"silent path final == asserted (no 40% discount), got {resolved['final_demand_cents']}"
        )
        assert notified["provisional_demand_cents"] != resolved["final_demand_cents"], (
            "provisional variant (60000) must differ from silent-path final variant (100000) for identical lien data"
        )

    def test_silent_path_recompute_claim_totals(self, api, lien_analyst_headers, program_admin_headers):
        """PRD §3.5: "Either resolution path recomputes the claim's `total_lien_cents` as the sum of `final_demand_cents` across the claim's liens in `RESOLVED` state and recomputes `net_award_cents`, and both advance the claim's `version` by 1."

        Design: Difficulty/dual_variant_calc/lien_demand_provisional_vs_final_medicare
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=100_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.set_clock(pid, {"to_iso8601": "2026-09-15T00:00:00Z"}, program_admin_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        validate_success(api.resolve_lien(pid, cid, lid, {"expected_claim_version": version},
                                          lien_analyst_headers))
        claim = validate_success(api.get_claim(pid, cid, program_admin_headers))
        assert claim["total_lien_cents"] == 100_000
        assert claim["net_award_cents"] == claim["gross_award_cents"] - 100_000 - claim["attorney_fee_cents"]


class TestMedicalProviderHardshipBranch:
    def _program_with_provider_lien(self, base_award_cents, program_code, full_name, ssn_last4):
        program = create_program(program_code=program_code)
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=base_award_cents)
        claimant = create_claimant(pid, full_name=full_name, ssn_last4=ssn_last4)
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        assign_tier_with_fresh_version(pid, claim["id"], matrix["id"])
        lien = add_lien(pid, claim["id"], lien_type="MEDICAL_PROVIDER", holder_name="Clinic",
                        asserted_amount_cents=1_000_000)
        return pid, claim["id"], lien["id"]

    def test_below_hardship_floor_uses_forty_percent(self, api, lien_analyst_headers):
        """PRD §3.5: "A `MEDICAL_PROVIDER` lien receives a hardship-dependent discount: if the claim's `gross_award_cents` is below the hardship floor of five million cents (that is, $50,000), the provisional demand is forty percent of the asserted amount; otherwise it is eighty percent."

        Design: Difficulty/combinatorial_formula/provisional_lien_demand_tiered_branch_mode_a
        """
        pid, cid, lid = self._program_with_provider_lien(4_000_000, "MT-LOW", "Carol", "1111")
        resp = api.notify_lien(pid, cid, lid, lien_analyst_headers)
        data = validate_success(resp)
        assert data["provisional_demand_cents"] == 400_000, (
            f"gross 4000000 < 5000000 floor -> 0.40 branch: 1000000*0.40=400000, got {data['provisional_demand_cents']}"
        )

    def test_at_or_above_hardship_floor_uses_eighty_percent(self, api, lien_analyst_headers):
        """PRD §3.5: "A `MEDICAL_PROVIDER` lien receives a hardship-dependent discount: if the claim's `gross_award_cents` is below the hardship floor of five million cents (that is, $50,000), the provisional demand is forty percent of the asserted amount; otherwise it is eighty percent."

        Design: Difficulty/combinatorial_formula/provisional_lien_demand_tiered_branch_mode_a
        """
        pid, cid, lid = self._program_with_provider_lien(6_000_000, "MT-HIGH", "Dave", "2222")
        resp = api.notify_lien(pid, cid, lid, lien_analyst_headers)
        data = validate_success(resp)
        assert data["provisional_demand_cents"] == 800_000, (
            f"gross 6000000 >= 5000000 floor -> 0.80 branch: 1000000*0.80=800000, got {data['provisional_demand_cents']}"
        )


class TestLienResolveBoundaries:
    def test_final_equal_to_asserted_allowed(self, api, lien_analyst_headers):
        """PRD §3.5: "The analyst supplies `final_demand_cents`, which must be at least zero and no more than `asserted_amount_cents` — an amount above the asserted figure is rejected as `ERR_FINAL_EXCEEDS_ASSERTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/final_equals_asserted_boundary_lien_resolve
        """
        ctx = create_claim_in_liens_pending(lien_type="PRIVATE_INSURER", holder_name="InsCo",
                                            asserted_amount_cents=100_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resp = api.resolve_lien(pid, cid, lid,
                                {"expected_claim_version": version, "final_demand_cents": 100_000},
                                lien_analyst_headers)
        data = validate_success(resp)
        assert data["state"] == "RESOLVED"
        assert data["final_demand_cents"] == 100_000, (
            f"final == asserted is the inclusive boundary; got {data['final_demand_cents']}"
        )

    def test_final_one_cent_above_asserted_rejected(self, api, lien_analyst_headers):
        """PRD §3.5: "The analyst supplies `final_demand_cents`, which must be at least zero and no more than `asserted_amount_cents` — an amount above the asserted figure is rejected as `ERR_FINAL_EXCEEDS_ASSERTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/final_equals_asserted_boundary_lien_resolve
        """
        ctx = create_claim_in_liens_pending(lien_type="PRIVATE_INSURER", holder_name="InsCo",
                                            asserted_amount_cents=100_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resp = api.resolve_lien(pid, cid, lid,
                                {"expected_claim_version": version, "final_demand_cents": 100_001},
                                lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_FINAL_EXCEEDS_ASSERTED)

    def test_final_above_asserted_rejected(self, api, lien_analyst_headers):
        """PRD §3.5: "The analyst supplies `final_demand_cents`, which must be at least zero and no more than `asserted_amount_cents` — an amount above the asserted figure is rejected as `ERR_FINAL_EXCEEDS_ASSERTED` (HTTP 422)."

        Design: Corner/validations/final_exceeds_asserted_returns_error
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resp = api.resolve_lien(pid, cid, lid,
                                {"expected_claim_version": version, "final_demand_cents": 60_000},
                                lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_FINAL_EXCEEDS_ASSERTED)


class TestHolderWindow:
    def test_silent_resolve_before_window_close_rejected(self, api, lien_analyst_headers):
        """PRD §3.5: "the program's `current_utc` must be strictly later than `holder_response_due_at`, otherwise the attempt is rejected as `ERR_HOLDER_WINDOW_OPEN` (HTTP 422)."

        Design: Corner/validations/holder_window_open_blocks_silent_resolve
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resp = api.resolve_lien(pid, cid, lid, {"expected_claim_version": version}, lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_HOLDER_WINDOW_OPEN)


class TestLienDisputeCycle:
    def test_dispute_then_begin_negotiation_closes_cycle(self, api, lien_analyst_headers):
        """PRD §3.5: "The claimant, acting through `ClaimantRole`, may dispute a lien that is `IN_NEGOTIATION`, moving it to `DISPUTED`; a `LienAnalyst` can then begin negotiation again to bring it back."

        Design: Difficulty/non_linear_state_machine/lien_dispute_cycle_on_lien
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        disputed = validate_success(
            api.dispute_lien(pid, cid, lid, make_claimant_headers(ctx["claimant"]["id"]))
        )
        assert disputed["state"] == "DISPUTED", f"Expected DISPUTED, got {disputed['state']}"
        back = validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        assert back["state"] == "IN_NEGOTIATION", (
            f"begin-negotiation from DISPUTED must return to IN_NEGOTIATION, got {back['state']}"
        )

    def test_dispute_from_notified_rejected(self, api, lien_analyst_headers):
        """PRD §3.5: "The claimant, acting through `ClaimantRole`, may dispute a lien that is `IN_NEGOTIATION`, moving it to `DISPUTED`; a `LienAnalyst` can then begin negotiation again to bring it back."
        PRD §3.5: "Any of these lien operations attempted against a lien in the wrong `state` is rejected as `ERR_LIEN_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/lien_dispute_cycle_on_lien
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        resp = api.dispute_lien(pid, cid, lid, make_claimant_headers(ctx["claimant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LIEN_INVALID_STATE)


class TestFinalizeLiensGates:
    def test_unresolved_lien_blocks_finalize(self, api, lien_analyst_headers):
        """PRD §3.5: "Finalization is blocked, with `ERR_UNRESOLVED_LIENS_EXIST` (HTTP 409), while any lien remains in `IDENTIFIED`, `NOTIFIED`, `IN_NEGOTIATION`, or `DISPUTED`; and it is blocked, with `ERR_OPEN_APPEAL_BLOCKS_FINALIZE` (HTTP 409), while the claim's `active_appeal_id` is non-null."

        Design: Corner/validations/unresolved_liens_block_finalize
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        resp = api.finalize_liens(pid, cid, lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LIENS_EXIST)


class TestResolveLienOcc:
    def test_stale_version_on_lien_resolve_rejected(self, api, lien_analyst_headers):
        """PRD §2.6: "Likewise, a lien-resolution request must carry `expected_claim_version` matching the owning claim's current `version`; a mismatch — for example because an appeal was filed or liens were finalized since the client last read the claim — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_resolve_lien_stale
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        v_stale = get_claim_version(pid, cid, lien_analyst_headers)
        # A subsequent lien identification is a claim-level event; regardless, we
        # resolve with a version one behind the captured one, which is stale.
        add_lien(pid, cid, lien_type="MEDICAID", holder_name="DHHS", asserted_amount_cents=999)
        resp = api.resolve_lien(pid, cid, lid,
                                {"expected_claim_version": v_stale - 1, "final_demand_cents": 40_000},
                                lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_version_on_lien_resolve_accepted(self, api, lien_analyst_headers):
        """PRD §2.6: "Likewise, a lien-resolution request must carry `expected_claim_version` matching the owning claim's current `version`; a mismatch — for example because an appeal was filed or liens were finalized since the client last read the claim — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_resolve_lien_stale
        """
        ctx = create_claim_in_liens_pending(lien_type="MEDICARE", holder_name="CMS",
                                            asserted_amount_cents=50_000)
        pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
        validate_success(api.notify_lien(pid, cid, lid, lien_analyst_headers))
        validate_success(api.begin_lien_negotiation(pid, cid, lid, lien_analyst_headers))
        version = get_claim_version(pid, cid, lien_analyst_headers)
        resp = api.resolve_lien(pid, cid, lid,
                                {"expected_claim_version": version, "final_demand_cents": 40_000},
                                lien_analyst_headers)
        data = validate_success(resp)
        assert data["state"] == "RESOLVED"
        assert data["final_demand_cents"] == 40_000
