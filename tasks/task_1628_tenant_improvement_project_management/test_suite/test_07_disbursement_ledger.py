"""Allowance ledger: consumption variants, tiered retainage, escrow release."""
from test_helpers import (
    ApiErrorId,
    create_approved_draw,
    create_draw_record,
    create_submitted_draw,
    get_success_data,
    make_contractor_rep_headers,
    make_landlord_approver_headers,
    set_logical_clock,
    setup_project_in_construction,
    validate_error,
    validate_success,
)

MID = "2026-08-15T00:00:00Z"


def _construction_with_clock(api):
    sc = setup_project_in_construction()
    set_logical_clock(MID)
    return sc


class TestAllowanceConsumptionVariants:
    def test_allowance_consumption_provisional_vs_final_on_tiproject(
        self, api, landlord_pm_headers
    ):
        """PRD 3.6: "The final variant, `allowance_consumed_cents`, sums
        `approved_amount_cents` across the project's draws in `APPROVED` or
        `PAID` and nothing else; the provisional variant,
        `provisional_allowance_consumed_cents`, adds on the full
        `requested_amount_cents` of draws still waiting in `SUBMITTED` or
        `ON_HOLD`, so the provisional figure is always at least the final one
        while review is pending". PRD 3.6: "`allowance_remaining_cents` is
        `allowance_total_cents` minus `allowance_consumed_cents`."

        Design: Difficulty/dual_variant_calc/allowance_consumption_provisional_vs_final_on_tiproject
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        draw1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        # Early tier: cum_before 0 < half of 50000000 -> 10% withholding.
        assert draw1["retainage_held_cents"] == 1_000_000
        assert draw1["net_payment_cents"] == 9_000_000

        draw2 = create_submitted_draw(sc["project"]["id"], ctr, 12_000_000)["draw"]
        assert draw2["status"] == "SUBMITTED"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 10_000_000, (
            "the final variant counts only the APPROVED draw"
        )
        assert project["provisional_allowance_consumed_cents"] == 22_000_000, (
            "the provisional variant adds the SUBMITTED draw's full requested amount"
        )
        assert project["allowance_remaining_cents"] == 40_000_000

    def test_provisional_variant_refreshes_when_draw_leaves_submitted(
        self, api, landlord_pm_headers
    ):
        """PRD 3.6: "Both variants refresh whenever a draw enters or leaves
        `SUBMITTED`, `ON_HOLD`, `APPROVED`, `PAID`, `REJECTED`, or `VOIDED`,
        and when a work letter is executed." PRD 3.6: "Rejection moves
        `SUBMITTED` → `REJECTED`, refreshing the provisional consumption and
        the posture."

        Design: Difficulty/dual_variant_calc/allowance_consumption_provisional_vs_final_on_tiproject
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        draw2 = create_submitted_draw(sc["project"]["id"], ctr, 12_000_000)["draw"]

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["provisional_allowance_consumed_cents"] == 22_000_000

        rejected = get_success_data(
            api.reject_draw(draw2["id"], make_landlord_approver_headers("approver-1"))
        )
        assert rejected["status"] == "REJECTED"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 10_000_000
        assert project["provisional_allowance_consumed_cents"] == 10_000_000, (
            "leaving SUBMITTED for REJECTED removes the draw from the provisional variant"
        )
        assert project["allowance_remaining_cents"] == 40_000_000


class TestRetainageTieredBoundary:
    def test_retainage_tiered_threshold_boundary(self, api, landlord_pm_headers):
        """PRD 3.6: "the server sums `approved_amount_cents` over the project's
        other draws in `APPROVED` or `PAID`, and if that prior cumulative total
        is below half of `allowance_total_cents` the early rate of ten percent
        applies, while a cumulative total equal to or above that half-way
        threshold drops the rate to five percent; the draw's
        `retainage_held_cents` is its `approved_amount_cents` times the
        applicable rate, rounded half up to a whole cent, and its
        `net_payment_cents` is the approved amount minus that withholding."

        Design: Difficulty/combinatorial_formula/retainage_tiered_threshold_boundary
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        d1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d1["retainage_held_cents"] == 1_000_000  # cum_before 0 < 25000000 -> 10%
        d2 = create_approved_draw(sc["project"]["id"], ctr, 15_000_000)
        assert d2["retainage_held_cents"] == 1_500_000  # cum_before 10000000 < 25000000 -> 10%

        # cum_before is now exactly 25000000 == half of the allowance.
        d3 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d3["retainage_held_cents"] == 500_000, (
            f"at exactly the half-way threshold the late 5% tier applies, got "
            f"{d3['retainage_held_cents']}"
        )
        assert d3["net_payment_cents"] == 9_500_000

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["retainage_held_cents"] == 3_000_000
        assert project["allowance_consumed_cents"] == 35_000_000

    def test_retainage_early_tier_just_below_threshold(self, api, landlord_pm_headers):
        """PRD 3.6: "if that prior cumulative total is below half of
        `allowance_total_cents` the early rate of ten percent applies, while a
        cumulative total equal to or above that half-way threshold drops the
        rate to five percent".

        Design: Difficulty/combinatorial_formula/retainage_tiered_threshold_boundary
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        d1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d1["retainage_held_cents"] == 1_000_000
        # cum_before 10000000 < 25000000 -> 10%; round_half_up(1499999.9) = 1500000.
        d2 = create_approved_draw(sc["project"]["id"], ctr, 14_999_999)
        assert d2["retainage_held_cents"] == 1_500_000

        # cum_before 24999999 is still BELOW the 25000000 threshold -> 10%.
        d3 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d3["retainage_held_cents"] == 1_000_000, (
            f"one cent below the threshold the early 10% tier still applies, got "
            f"{d3['retainage_held_cents']}"
        )
        assert d3["net_payment_cents"] == 9_000_000


class TestFinalDrawEscrowRelease:
    def test_retainage_escrow_conservation_final_draw_release(self, api, landlord_pm_headers):
        """PRD 3.6: "A draw marked `is_final_draw` withholds nothing at
        approval — its retainage is zero by definition." PRD 3.6: "Paying the
        final draw releases everything still held: the project's entire
        `retainage_held_cents` balance is added into
        `retainage_released_cents`, the held balance is zeroed, and the final
        payout is the draw's `net_payment_cents` plus that released retainage."

        Design: Difficulty/compensating_invariant/retainage_escrow_conservation_final_draw_release
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        create_approved_draw(sc["project"]["id"], ctr, 10_000_000)  # holds 1000000
        create_approved_draw(sc["project"]["id"], ctr, 15_000_000)  # holds 1500000
        create_approved_draw(sc["project"]["id"], ctr, 10_000_000)  # holds 500000 (late tier)

        final = create_approved_draw(
            sc["project"]["id"],
            ctr,
            5_000_000,
            waiver_type="UNCONDITIONAL_FINAL",
            is_final_draw=True,
        )
        assert final["retainage_held_cents"] == 0, "the final draw withholds nothing"
        assert final["net_payment_cents"] == 5_000_000

        paid = validate_success(api.pay_draw(final["id"], landlord_pm_headers), 200)
        assert paid["status"] == "PAID"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["retainage_held_cents"] == 0, "the held balance is zeroed on final pay"
        assert project["retainage_released_cents"] == 3_000_000, (
            f"the full escrow (1000000+1500000+500000) is released, got "
            f"{project['retainage_released_cents']}"
        )
        assert project["allowance_consumed_cents"] == 40_000_000

    def test_ordinary_draw_payment_does_not_release_escrow(self, api, landlord_pm_headers):
        """PRD 3.6: "For an ordinary draw the paid-out amount is simply its
        `net_payment_cents`. Paying the final draw releases everything still
        held: the project's entire `retainage_held_cents` balance is added into
        `retainage_released_cents`, the held balance is zeroed".

        Design: Difficulty/compensating_invariant/retainage_escrow_conservation_final_draw_release
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        d1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        create_approved_draw(sc["project"]["id"], ctr, 15_000_000)

        paid = validate_success(api.pay_draw(d1["id"], landlord_pm_headers), 200)
        assert paid["status"] == "PAID"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["retainage_held_cents"] == 2_500_000, (
            "paying a non-final draw leaves the escrow untouched"
        )
        assert project["retainage_released_cents"] == 0


class TestAllowancePoolConservation:
    def test_allowance_pool_conservation_across_approve_and_void(self, api, landlord_pm_headers):
        """PRD 3.6: "voiding an `APPROVED` draw is the approver's compensation
        path — the draw's `approved_amount_cents` comes back out of
        `allowance_consumed_cents`, its withholding comes back out of the
        project's `retainage_held_cents`, the remaining allowance is
        recomputed". PRD 3.6: "`allowance_remaining_cents` is
        `allowance_total_cents` minus `allowance_consumed_cents`."

        Design: Difficulty/compensating_invariant/allowance_pool_conservation_across_approve_and_void
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        d1 = create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        assert d1["retainage_held_cents"] == 1_000_000

        voided = get_success_data(
            api.void_draw(d1["id"], make_landlord_approver_headers("approver-9"))
        )
        assert voided["status"] == "VOIDED"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 0, "approve-then-void fully compensates"
        assert project["allowance_remaining_cents"] == 50_000_000
        assert project["retainage_held_cents"] == 0, "the withholding is backed out too"
        assert (
            project["allowance_consumed_cents"] + project["allowance_remaining_cents"]
            == project["allowance_total_cents"]
        )

        d2 = create_approved_draw(sc["project"]["id"], ctr, 15_000_000)
        assert d2["status"] == "APPROVED"
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 15_000_000
        assert project["allowance_remaining_cents"] == 35_000_000
        assert (
            project["allowance_consumed_cents"] + project["allowance_remaining_cents"]
            == 50_000_000
        ), "the pool split stays conserved after subsequent activity"

    def test_draft_draw_void_is_side_effect_free(self, api, landlord_pm_headers):
        """PRD 3.6: "Voiding has two flavors: the contractor may void a `DRAFT`
        draw outright, while voiding an `APPROVED` draw is the approver's
        compensation path — the draw's `approved_amount_cents` comes back out
        of `allowance_consumed_cents`".

        Design: Difficulty/compensating_invariant/allowance_pool_conservation_across_approve_and_void
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        create_approved_draw(sc["project"]["id"], ctr, 10_000_000)
        draft = create_draw_record(sc["project"]["id"], ctr, 7_000_000)
        assert draft["status"] == "DRAFT"

        voided = get_success_data(
            api.void_draw(draft["id"], make_contractor_rep_headers(ctr))
        )
        assert voided["status"] == "VOIDED"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 10_000_000, (
            "a DRAFT draw never entered the ledger; voiding it changes nothing"
        )
        assert project["allowance_remaining_cents"] == 40_000_000
        assert project["retainage_held_cents"] == 1_000_000


class TestDrawCreationDefaults:
    def test_disbursement_computed_fields_ignore_client_input(self, api, landlord_pm_headers):
        """PRD 2.4: "Beyond the common properties, several child collections
        assign a sequential number per parent: a work letter's `version_no`, a
        plan submission's `revision_no`, a change order's `co_number`, a draw's
        `draw_number`, and an invoice's `invoice_number` each start at 1 within
        their project and are assigned in `created_at` order." PRD 3.6:
        "Submission moves `DRAFT` → `SUBMITTED` through the ordered gates of
        §2.7".

        Design: Corner/entities/disbursement_computed_fields_ignore_client_input
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]

        d1 = validate_success(
            api.create_draw(
                sc["project"]["id"],
                {
                    "period_end_date": "2026-08-14T00:00:00Z",
                    "requested_amount_cents": 500_000,
                    "expected_ti_project_version": get_success_data(
                        api.get_project(sc["project"]["id"], landlord_pm_headers)
                    )["version"],
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert d1["draw_number"] == 1, "the first draw of a project is numbered 1"
        assert d1["status"] == "DRAFT", "a draw begins as a draft awaiting submission"

        d2 = validate_success(
            api.create_draw(
                sc["project"]["id"],
                {
                    "period_end_date": "2026-08-14T00:00:00Z",
                    "requested_amount_cents": 600_000,
                    "expected_ti_project_version": get_success_data(
                        api.get_project(sc["project"]["id"], landlord_pm_headers)
                    )["version"],
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert d2["draw_number"] == 2, "numbers advance sequentially in created_at order"


class TestDrawApprovalLadder:
    def test_draw_approve_without_verified_waiver_rejected(self, api, landlord_pm_headers):
        """PRD 3.6: "at least one waiver on the draw must be `VERIFIED`, else
        `ERR_LIEN_WAIVER_MISSING` (HTTP 422)".

        Design: Corner/validations/draw_approve_without_verified_waiver_rejected
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        # Waiver attached but left PENDING.
        submitted = create_submitted_draw(
            sc["project"]["id"], ctr, 1_000_000, waiver_action="pending"
        )
        draw = submitted["draw"]
        assert submitted["waiver"]["status"] == "PENDING"

        resp = api.approve_draw(
            draw["id"],
            {"approved_amount_cents": 1_000_000},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_WAIVER_MISSING)
        after = get_success_data(api.get_draw(draw["id"], landlord_pm_headers))
        assert after["status"] == "SUBMITTED"

    def test_draw_approve_waiver_amount_mismatch_rejected(self, api, landlord_pm_headers):
        """PRD 3.6: "that verified waiver's `amount_cents` must equal the
        draw's `requested_amount_cents`, else
        `ERR_LIEN_WAIVER_AMOUNT_MISMATCH`".

        Design: Corner/validations/draw_approve_waiver_amount_mismatch_rejected
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        submitted = create_submitted_draw(
            sc["project"]["id"], ctr, 1_000_000, waiver_amount_cents=999_999
        )
        assert submitted["waiver"]["status"] == "VERIFIED"

        resp = api.approve_draw(
            submitted["draw"]["id"],
            {"approved_amount_cents": 1_000_000},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_WAIVER_AMOUNT_MISMATCH)

    def test_draw_approve_exceeding_requested_rejected(self, api, landlord_pm_headers):
        """PRD 3.6: "the approved amount may not exceed
        `requested_amount_cents`, else `ERR_APPROVAL_EXCEEDS_REQUEST` (HTTP
        422)".

        Design: Corner/validations/draw_approve_exceeding_requested_rejected
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        submitted = create_submitted_draw(sc["project"]["id"], ctr, 1_000_000)

        resp = api.approve_draw(
            submitted["draw"]["id"],
            {"approved_amount_cents": 1_000_001},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_APPROVAL_EXCEEDS_REQUEST)
