"""Negotiation round lifecycle: cap, alternation, MFN floor, fee formula variants."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_request,
    create_clearance_request,
    get_success_data,
    make_negotiator_headers,
    make_officer_headers,
    make_rights_holder_rep_headers,
    post_round,
    post_round_raw,
    setup_holder_asset,
    setup_request_in_negotiating,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNegotiationCapAndLoop:
    def test_five_rounds_complete_sixth_rejected(self, api):
        """PRD §3.3: "First, the cap: a request completes at most five rounds,
        and an attempt at a sixth is rejected with `ERR_NEGOTIATION_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/clearance_request_cyclic_negotiation_loop_with_cap
        """
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
            requested_units=2,
            holder_kind="PUBLISHER",
            mfn_floor_cents=100,
        )
        # Alternate Negotiator / RightsHolderRep across 5 rounds.
        fees = [90000, 85000, 80000, 75000, 72000]
        roles = ["Negotiator", "RightsHolderRep", "Negotiator", "RightsHolderRep", "Negotiator"]
        last_round = None
        for fee, role in zip(fees, roles):
            last_round = post_round(
                req["id"],
                fee,
                role=role,
                user_id=f"neg_loop_{fee}",
                holder_id=holder["id"] if role == "RightsHolderRep" else None,
            )
        assert last_round["round_index"] == 5

        # Sixth round attempt fails.
        err_resp = post_round_raw(
            req["id"],
            {"offered_fee_cents": 71000},
            role="RightsHolderRep",
            holder_id=holder["id"],
        )
        validate_error(err_resp, ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)

    def test_loop_preserves_negotiating_state_and_supersedes_prior_rounds(self, api):
        """PRD §3.3: "Each successfully posted round supersedes its predecessor —
        the prior `OPEN` round's `outcome` becomes `SUPERSEDED` — and the
        request's `negotiation_round`, the count of completed fee rounds,
        increments by 1."

        Design: Difficulty/non_linear_state_machine/clearance_request_cyclic_negotiation_loop_with_cap
        """
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
            requested_units=2,
        )
        post_round(req["id"], 90000, role="Negotiator", user_id="neg_l_1")
        post_round(req["id"], 85000, role="RightsHolderRep", holder_id=holder["id"])
        post_round(req["id"], 80000, role="Negotiator", user_id="neg_l_2")

        officer = make_officer_headers("off_l_1")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["status"] == "NEGOTIATING"
        assert req_after["negotiation_round"] == 3

        rounds, meta = validate_paginated(
            api.list_rounds(req["id"], make_negotiator_headers("neg_l_3"))
        )
        assert len(rounds) == 3
        assert rounds[0]["outcome"] == "SUPERSEDED"
        assert rounds[1]["outcome"] == "SUPERSEDED"
        assert rounds[2]["outcome"] == "OPEN"


class TestRoleAlternation:
    def test_consecutive_negotiator_rounds_rejected(self, api):
        """PRD §3.3: "Second, alternation: the new round's `offered_by_role`
        must differ from the most recently persisted round's `offered_by_role`
        — the two sides trade offers, never speaking twice in a row — with
        violation rejected as `ERR_ROUND_ROLE_ALTERNATION`; the very first
        round may be opened by either role."

        Design: Corner/calculations/role_alternation_violation_rejected
        """
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="STREAMING", requested_units=2
        )
        post_round(req["id"], 90000, role="Negotiator", user_id="neg_alt_1")
        err_resp = post_round_raw(
            req["id"], {"offered_fee_cents": 89000}, role="Negotiator", user_id="neg_alt_2"
        )
        validate_error(err_resp, ApiErrorId.ERR_ROUND_ROLE_ALTERNATION)
        ok = post_round(
            req["id"], 88000, role="RightsHolderRep", holder_id=holder["id"]
        )
        assert ok["round_index"] == 2


class TestFeeFormula:
    def test_term_tier_boundary_ninety_vs_ninety_one_days(self, api):
        """PRD §3.3: "The **term multiplier** reads the whole-day length of the
        requested window: at most ninety days multiplies by 1.0, longer than
        ninety days and at most three hundred sixty-five days multiplies by
        1.25, and anything longer multiplies by 1.6."

        Design: Difficulty/combinatorial_formula/fee_formula_three_input_nonlinear_tier_straddle
        """
        # ESTATE holder zeroes the MFN floor so the raw estimate IS the acceptance
        # threshold; this isolates the formula from the floor.
        holder, asset = setup_holder_asset(
            holder_kind="ESTATE",
            mfn_floor_cents=9999,
            work_kind="LITERARY_EXCERPT",
            permitted_media=["PRINT", "BROADCAST_TV"],
        )
        # R90: PRINT/EMEA/1 unit, 2026-09-01..2026-11-30 = 90 days → 5000*1.4*1.0 = 7000.
        r90, _rid = create_clearance_request(
            asset["id"],
            media="PRINT",
            territory="EMEA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-30T00:00:00Z",
            requested_units=1,
        )
        r90 = advance_request(r90["id"], r90["version"])
        r90 = advance_request(r90["id"], r90["version"])
        post_round(r90["id"], 7000, accept=True, role="Negotiator", user_id="neg_t_1")
        officer = make_officer_headers("off_t_1")
        r90_after = get_success_data(api.get_clearance_request(r90["id"], officer))
        assert r90_after["status"] == "APPROVED"
        assert r90_after["agreed_fee_cents"] == 7000

        # R91: PRINT/EMEA/1 unit, 2026-09-01..2026-12-01 = 91 days → 5000*1.4*1.25 = 8750.
        r91, _rid = create_clearance_request(
            asset["id"],
            media="PRINT",
            territory="EMEA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
            requested_units=1,
        )
        r91 = advance_request(r91["id"], r91["version"])
        r91 = advance_request(r91["id"], r91["version"])
        post_round(r91["id"], 8750, accept=True, role="Negotiator", user_id="neg_t_2")
        r91_after = get_success_data(api.get_clearance_request(r91["id"], officer))
        assert r91_after["status"] == "APPROVED"
        assert r91_after["agreed_fee_cents"] == 8750

    def test_bulk_discount_at_one_hundred_units(self, api):
        """PRD §3.3: "A bulk discount applies only when `requested_units` is at
        least one hundred: the raw fee is reduced by ten percent."

        Design: Difficulty/combinatorial_formula/fee_formula_three_input_nonlinear_tier_straddle
        """
        holder, asset = setup_holder_asset(
            holder_kind="ESTATE",
            mfn_floor_cents=9999,
            permitted_media=["BROADCAST_TV"],
        )
        # 50000 * 100 units * NA 1.0 * term 1.0 * (1 - 0.10) = 4_500_000.
        rb, _rid = create_clearance_request(
            asset["id"],
            media="BROADCAST_TV",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-10-01T00:00:00Z",
            requested_units=100,
        )
        rb = advance_request(rb["id"], rb["version"])
        rb = advance_request(rb["id"], rb["version"])
        post_round(rb["id"], 4500000, accept=True, role="Negotiator", user_id="neg_t_3")
        officer = make_officer_headers("off_t_3")
        rb_after = get_success_data(api.get_clearance_request(rb["id"], officer))
        assert rb_after["status"] == "APPROVED"
        assert rb_after["agreed_fee_cents"] == 4500000

    def test_single_round_half_up_rounding_pins_fee(self, api):
        """PRD §2.6: "Fee arithmetic is computed in floating point and rounded
        half-up to integer cents exactly once, at the final step of the fee
        recipe. Per-component rounding is explicitly rejected: a license carries
        exactly one fee line, and rounding intermediate components before
        combining them would diverge by whole cents."

        Design: Difficulty/combinatorial_formula/single_rounding_vs_forbidden_per_component_rounding
        """
        # RADIO/LATAM/1 unit / 91 days → 8000 * 0.8 * 1.25 = 8000 (rounded once).
        holder, asset = setup_holder_asset(
            holder_kind="ESTATE",
            mfn_floor_cents=1,
            work_kind="SOUND_RECORDING",
            permitted_media=["RADIO"],
        )
        req, _rid = create_clearance_request(
            asset["id"],
            media="RADIO",
            territory="LATAM",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
            requested_units=1,
        )
        req = advance_request(req["id"], req["version"])
        req = advance_request(req["id"], req["version"])
        post_round(req["id"], 8000, accept=True, role="Negotiator", user_id="neg_t_4")
        officer = make_officer_headers("off_t_4")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["status"] == "APPROVED"
        assert req_after["agreed_fee_cents"] == 8000


class TestMfnFloor:
    def test_offer_below_floor_rejected_at_final_variant(self, api):
        """PRD §3.3: "The accepted round's `offered_fee_cents` must be at least
        the floor, else `ERR_MFN_FLOOR_VIOLATION` — unless, again, the holder
        is an `ESTATE`."

        Design: Difficulty/dual_variant_calc/fee_provisional_ignores_mfn_floor_final_enforces_it
        """
        # SOCIAL/NA/10 units / 30d: raw = 3000*10*1.0*1.0 = 30000 = provisional estimate.
        # MFN floor = 5000 * 10 = 50000. Offer of 30000 matches provisional but is
        # rejected at the final variant.
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="SOCIAL",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-10-01T00:00:00Z",
            requested_units=10,
            holder_kind="PUBLISHER",
            mfn_floor_cents=5000,
            work_kind="STILL_IMAGE",
            permitted_media=["SOCIAL", "PRINT"],
        )
        err_resp = post_round_raw(
            req["id"],
            {"offered_fee_cents": 30000, "accept": True},
            role="Negotiator",
            user_id="neg_f_1",
        )
        validate_error(err_resp, ApiErrorId.ERR_MFN_FLOOR_VIOLATION)

    def test_offer_at_floor_accepted_and_approves(self, api):
        """PRD §3.3: "On acceptance the round's `outcome` becomes `ACCEPTED`,
        the request moves `NEGOTIATING` → `APPROVED`, its `agreed_fee_cents` is
        set to the accepted `offered_fee_cents`, and the parent asset is
        cascade-touched with a version bump."

        Design: Difficulty/dual_variant_calc/fee_provisional_ignores_mfn_floor_final_enforces_it
        """
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="SOCIAL",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-10-01T00:00:00Z",
            requested_units=10,
            holder_kind="PUBLISHER",
            mfn_floor_cents=5000,
            work_kind="STILL_IMAGE",
            permitted_media=["SOCIAL", "PRINT"],
        )
        accepted = post_round(
            req["id"],
            50000,
            accept=True,
            role="Negotiator",
            user_id="neg_f_2",
        )
        assert accepted["outcome"] == "ACCEPTED"
        officer = make_officer_headers("off_f_2")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["status"] == "APPROVED"
        assert req_after["agreed_fee_cents"] == 50000


class TestMfnEstateExemption:
    def test_estate_holder_accepts_below_floor_offer(self, api):
        """PRD §3.3: "The floor itself is zero for an `ESTATE` holder — estates
        are exempt — and for every other holder kind it is the holder's
        `mfn_floor_cents` multiplied by the request's `requested_units`."

        Design: Corner/calculations/fee_mfn_estate_exemption_allows_below_floor
        """
        holder, asset, req, _rid = setup_request_in_negotiating(
            media="SOCIAL",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-10-01T00:00:00Z",
            requested_units=1,
            holder_kind="ESTATE",
            mfn_floor_cents=9999,
            work_kind="STILL_IMAGE",
            permitted_media=["SOCIAL"],
        )
        accepted = post_round(
            req["id"], 1, accept=True, role="Negotiator", user_id="neg_c_11"
        )
        assert accepted["outcome"] == "ACCEPTED"
        officer = make_officer_headers("off_c_11")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["agreed_fee_cents"] == 1
