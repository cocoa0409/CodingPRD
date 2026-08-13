"""Wrap-network registration, overlap rules, and resolution paths (PRD §3.4-§3.5)."""
from test_helpers import (
    ApiErrorId,
    add_claim_line,
    create_network_agreement,
    create_network_agreement_payload,
    create_test_claim,
    create_test_payer,
    price_claim,
    setup_active_contract,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CA, CM, RIA


def _claim_with_line(payer_id, claim_number, charge_cents=100000, **claim_kw):
    claim_kw.setdefault("service_category", "LAB")
    claim_kw.setdefault("admission_date", "2026-06-01")
    claim_kw.setdefault("discharge_date", "2026-06-01")
    claim_kw.setdefault("total_billed_charges_cents", charge_cents)
    claim = create_test_claim(payer_id, claim_number=claim_number, **claim_kw)
    return claim


class TestNetworkAgreementOverlap:
    def test_same_name_shared_boundary_rejected(self, api):
        """PRD §3.4: "Two agreements for the same payer under the same
        `network_name` may not share even a single calendar date while both
        are non-retired; the overlap check uses closed-interval semantics and
        rejects with `ERR_NETWORK_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/network_agreement_overlap_rejected_even_at_shared_boundary
        """
        payer = create_test_payer(name="Payer NO")
        create_network_agreement(payer["id"], network_name="WrapNet")
        # Shares only the single boundary date 2026-12-31 — still forbidden.
        resp = api.create_network_agreement(
            create_network_agreement_payload(
                payer["id"],
                network_name="WrapNet",
                wrap_rate_bp=5500,
                precedence_rank=2,
                effective_date="2026-12-31",
                expiration_date="2027-06-30",
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_NETWORK_AGREEMENT_OVERLAP.value)
        # Fully disjoint window under the same name: allowed.
        n2 = validate_success(
            api.create_network_agreement(
                create_network_agreement_payload(
                    payer["id"],
                    network_name="WrapNet",
                    wrap_rate_bp=5500,
                    precedence_rank=2,
                    effective_date="2027-01-01",
                    expiration_date="2027-12-31",
                ),
                CA,
            ),
            expected_status=201,
        )
        assert n2["status"] == "REGISTERED"

    def test_different_network_name_inside_window_allowed(self, api):
        """PRD §3.4: "Two agreements for the same payer under the same
        `network_name` may not share even a single calendar date while both
        are non-retired; the overlap check uses closed-interval semantics and
        rejects with `ERR_NETWORK_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/network_agreement_overlap_rejected_even_at_shared_boundary
        """
        payer = create_test_payer(name="Payer NO")
        create_network_agreement(payer["id"], network_name="WrapNet")
        # Different network_name inside the first agreement's window: allowed.
        n3 = validate_success(
            api.create_network_agreement(
                create_network_agreement_payload(
                    payer["id"],
                    network_name="OtherNet",
                    wrap_rate_bp=6000,
                    precedence_rank=1,
                    effective_date="2026-06-01",
                    expiration_date="2026-06-30",
                ),
                CA,
            ),
            expected_status=201,
        )
        assert n3["id"]
        # Same network_name with an interior overlap: rejected.
        resp = api.create_network_agreement(
            create_network_agreement_payload(
                payer["id"],
                network_name="WrapNet",
                wrap_rate_bp=6000,
                precedence_rank=3,
                effective_date="2026-06-01",
                expiration_date="2026-06-30",
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_NETWORK_AGREEMENT_OVERLAP.value)


class TestResolutionPaths:
    def test_flag_suspect_does_not_reprice_existing_claims(self, api):
        """PRD §3.4: "flagging deliberately does not reprice history — claims
        already priced `WRAP_CONFIRMED` under the agreement keep their numbers,
        and only future pricing runs see the new status." PRD §3.5: "if any
        agreement of the payer covers the anchor in `REGISTERED` or
        `FLAGGED_SUSPECT` status, the claim is flagged `SILENT_PPO_SUSPECT` and
        its expected amount is the full `total_billed_charges_cents`, because
        no discount is entitled."

        Design: Corner/state_machines/sm_flag_suspect_does_not_reprice_existing_claims
        """
        payer = create_test_payer(name="Payer FS")
        agreement = create_network_agreement(
            payer["id"], network_name="WrapNet", wrap_rate_bp=5000
        )
        validate_success(api.verify_network_agreement(agreement["id"], CM))
        claim1 = _claim_with_line(payer["id"], "CL-FS1")
        add_claim_line(claim1["id"], revenue_code="0300", charge_cents=100000)
        priced1 = price_claim(claim1["id"])
        assert priced1["network_flag"] == "WRAP_CONFIRMED"
        assert priced1["expected_reimbursement_cents"] == 50000

        claim2 = _claim_with_line(payer["id"], "CL-FS2")
        add_claim_line(claim2["id"], revenue_code="0300", charge_cents=100000)

        validate_success(api.flag_suspect_network_agreement(agreement["id"], RIA))

        after = validate_success(api.get_claim(claim1["id"], RIA))
        assert after["expected_reimbursement_cents"] == 50000
        assert after["network_flag"] == "WRAP_CONFIRMED"

        priced2 = price_claim(claim2["id"])
        assert priced2["network_flag"] == "SILENT_PPO_SUSPECT"
        assert priced2["expected_reimbursement_cents"] == 100000

    def test_wrap_pricing_rounds_per_line(self, api):
        """PRD §3.5: "On the wrap path, pricing is deliberately simpler: each
        line is priced at its `charge_cents` times the agreement's
        `wrap_rate_bp` divided by 10000, rounded half up per line, and the
        expected amount is the sum of the line amounts."

        Design: Corner/calculations/calc_wrap_pricing_rounds_per_line
        """
        payer = create_test_payer(name="Payer WR")
        agreement = create_network_agreement(
            payer["id"], network_name="RoundNet", wrap_rate_bp=6666
        )
        validate_success(api.verify_network_agreement(agreement["id"], CM))
        claim = _claim_with_line(payer["id"], "CL-WR1", charge_cents=3)
        for rev in ("0300", "0301", "0302"):
            add_claim_line(claim["id"], revenue_code=rev, charge_cents=1)
        priced = price_claim(claim["id"])
        # round_half_up(1 * 6666/10000) = 1 per line; 3 lines -> 3 (never the
        # sum-then-round result of round_half_up(1.9998) = 2, PRD §2.6).
        assert priced["network_flag"] == "WRAP_CONFIRMED"
        assert priced["expected_reimbursement_cents"] == 3

    def test_resolution_contract_beats_verified_wrap(self, api):
        """PRD §3.5: "Resolution proceeds in strict order, and a direct
        contract always beats every network agreement." and "a contract winner
        sets `priced_contract_id`, leaves `network_agreement_id` null, and
        keeps `network_flag` at `NONE`."

        Design: Corner/calculations/calc_resolution_contract_beats_verified_wrap
        """
        ctx = setup_active_contract()
        agreement = create_network_agreement(
            ctx["payer"]["id"], network_name="WrapX", wrap_rate_bp=5000
        )
        validate_success(api.verify_network_agreement(agreement["id"], CM))
        claim = create_test_claim(ctx["payer"]["id"], claim_number="CL-CW1")
        add_claim_line(claim["id"])
        priced = price_claim(claim["id"])
        assert priced["network_flag"] == "NONE"
        assert priced["priced_contract_id"] == ctx["contract"]["id"]
        assert priced["network_agreement_id"] is None
        # 2 per-diem nights x 100000 = 200000, not the 250000 wrap amount.
        assert priced["expected_reimbursement_cents"] == 200000

    def test_wrap_selection_higher_rate_wins(self, api):
        """PRD §3.5: "the payer's `VERIFIED` network agreements whose window
        contains the anchor compete, ranked by highest `wrap_rate_bp`, then
        lowest `precedence_rank`, then earliest `created_at`".

        Design: Corner/calculations/calc_wrap_selection_higher_rate_wins
        """
        payer = create_test_payer(name="Payer WS")
        na_a = create_network_agreement(
            payer["id"], network_name="WR-A", wrap_rate_bp=4000, precedence_rank=1
        )
        validate_success(api.verify_network_agreement(na_a["id"], CM))
        na_b = create_network_agreement(
            payer["id"], network_name="WR-B", wrap_rate_bp=6000, precedence_rank=2
        )
        validate_success(api.verify_network_agreement(na_b["id"], CM))
        claim = _claim_with_line(payer["id"], "CL-WS1")
        add_claim_line(claim["id"], revenue_code="0300", charge_cents=100000)
        priced = price_claim(claim["id"])
        assert priced["network_agreement_id"] == na_b["id"], (
            "Higher wrap_rate_bp (6000, rank 2) must beat 4000bp rank 1"
        )
        assert priced["expected_reimbursement_cents"] == 60000

    def test_suspect_agreement_pays_full_billed(self, api):
        """PRD §3.5: "if any agreement of the payer covers the anchor in
        `REGISTERED` or `FLAGGED_SUSPECT` status, the claim is flagged
        `SILENT_PPO_SUSPECT` and its expected amount is the full
        `total_billed_charges_cents`, because no discount is entitled."

        Design: Corner/calculations/calc_suspect_agreement_pays_full_billed
        """
        payer = create_test_payer(name="Payer SP")
        create_network_agreement(payer["id"], network_name="WrapS", wrap_rate_bp=5000)
        claim = _claim_with_line(payer["id"], "CL-SP1")
        add_claim_line(claim["id"], revenue_code="0300", charge_cents=100000)
        priced = price_claim(claim["id"])
        assert priced["network_flag"] == "SILENT_PPO_SUSPECT"
        assert priced["expected_reimbursement_cents"] == 100000
        assert priced["priced_contract_id"] is None

    def test_out_of_network_pays_full_billed(self, api):
        """PRD §3.5: "Fourth and finally, the claim is flagged
        `OUT_OF_NETWORK`, again with expected reimbursement equal to full
        billed charges."

        Design: Corner/calculations/calc_out_of_network_pays_full_billed
        """
        payer = create_test_payer(name="Payer ON")
        claim = _claim_with_line(payer["id"], "CL-ON1")
        add_claim_line(claim["id"], revenue_code="0300", charge_cents=100000)
        priced = price_claim(claim["id"])
        assert priced["network_flag"] == "OUT_OF_NETWORK"
        assert priced["expected_reimbursement_cents"] == 100000
