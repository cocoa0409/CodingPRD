"""Buyback demands: price variants, exit cascade effects on votes, eligibility
and uniqueness guards (PRD §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    cast_consent_vote,
    create_buyback_demand_payload,
    create_draw,
    create_modification,
    demand_buyback,
    get_consent_vote,
    get_facility,
    get_modification_request,
    get_participant,
    get_success_data,
    make_agent_headers,
    make_participant_headers,
    set_clock,
    settle_buyback,
    settlement_for_participant,
    setup_committed_facility,
    setup_funded_facility,
    solicit_modification,
    validate_error,
    validate_success,
    wire_and_confirm_due,
)

AGENT = make_agent_headers()

STANDARD_COMMITMENTS = [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]


class TestBuybackPriceVariants:
    def test_buyback_price_standard_vs_penalty_variants(self):
        """PRD §3.9: "For `MISREPRESENTATION` and `DOCUMENTATION_DEFECT`, the
        standard variant, the price `repurchase_price_cents` is the outstanding
        share plus the accrued share. For `SERVICING_BREACH`, the penalty variant
        adds `penalty_cents` — the floor of the outstanding share times five
        hundred basis points divided by ten thousand — so the same position
        prices strictly higher; in the standard variant `penalty_cents` is zero."
        PRD §3.9: "The accrued share `accrued_share_cents` is the floor of the
        participant's `share_bps` times the facility's `accrued_interest_cents`
        divided by ten thousand, taken after accrual has been materialized to the
        settle date."

        Design: Difficulty/dual_variant_calc/buyback_price_standard_vs_penalty_variants
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        _, p2, p3 = setup["participants"]

        set_clock("2026-08-31T00:00:00Z")
        # Accrual materialized at settle: floor(5M * 1200 * 30 / 3.6M) == 50,000.
        bd2 = demand_buyback(facility["id"], p2["id"], "MISREPRESENTATION")
        settled2 = settle_buyback(bd2["id"])
        assert settled2["status"] == "SETTLED"
        assert settled2["outstanding_share_cents"] == 1_500_000
        assert settled2["accrued_share_cents"] == 15_000  # floor(3000 * 50000 / 10000)
        assert settled2["penalty_cents"] == 0
        assert settled2["repurchase_price_cents"] == 1_515_000

        # After P2's exit, shares rebase to 8572/1428 over the 7,000,000 base.
        bd3 = demand_buyback(facility["id"], p3["id"], "SERVICING_BREACH")
        settled3 = settle_buyback(bd3["id"])
        assert settled3["outstanding_share_cents"] == 500_000
        assert settled3["accrued_share_cents"] == 7_140  # floor(1428 * 50000 / 10000)
        assert settled3["penalty_cents"] == 25_000  # floor(500,000 * 500 / 10,000)
        assert settled3["repurchase_price_cents"] == 532_140

        assert get_participant(p2["id"])["status"] == "EXITED"
        assert get_participant(p3["id"])["status"] == "EXITED"
        assert get_facility(facility["id"])["committed_cents"] == 6_000_000

    def test_buyback_documentation_defect_uses_standard_variant(self):
        """PRD §3.9: "For `MISREPRESENTATION` and `DOCUMENTATION_DEFECT`, the
        standard variant, the price `repurchase_price_cents` is the outstanding
        share plus the accrued share."
        PRD §3.9: "For `SERVICING_BREACH`, the penalty variant adds
        `penalty_cents` — the floor of the outstanding share times five hundred
        basis points divided by ten thousand — so the same position prices
        strictly higher; in the standard variant `penalty_cents` is zero."

        Design: Difficulty/dual_variant_calc/buyback_price_standard_vs_penalty_variants
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        p2 = setup["participants"][1]

        set_clock("2026-08-31T00:00:00Z")
        demand = demand_buyback(facility["id"], p2["id"], "DOCUMENTATION_DEFECT")
        settled = settle_buyback(demand["id"])
        assert settled["penalty_cents"] == 0
        assert settled["outstanding_share_cents"] == 1_500_000
        assert settled["accrued_share_cents"] == 15_000
        assert settled["repurchase_price_cents"] == 1_515_000
        assert get_participant(p2["id"])["status"] == "EXITED"
        assert get_facility(facility["id"])["committed_cents"] == 7_000_000


class TestBuybackCascadeOnVotes:
    def test_buyback_settle_voids_consent_votes_and_rebases_tally(self):
        """PRD §3.9: "Hop 3 recomputes `share_bps` for the remaining participants
        and voids the exited participant's live votes on soliciting requests and
        declared cases, recomputing those tallies."
        PRD §3.6: "The adjusted base is the snapshot `voting_base_cents` minus
        the commitments of participants who have exited since solicitation."

        Design: Difficulty/transitive_cascade/buyback_settle_voids_votes_rebases_tally
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 1_000_000)
        facility = setup["facility"]
        p1, _, p3 = setup["participants"]

        mod = create_modification(
            facility["id"], setup["borrower"]["id"], "COVENANT_WAIVER",
            {"waiver_text": "T"},
        )
        solicit_modification(mod["id"])
        v1 = cast_consent_vote(mod["id"], p1["id"], "APPROVE")
        v3 = cast_consent_vote(mod["id"], p3["id"], "APPROVE")
        mid = get_modification_request(mod["id"])
        assert mid["approving_commitment_cents"] == 7_000_000

        # P3 exits via buyback (settled at the 2026-08-01 clock: zero accrued
        # days, so the price is exactly its outstanding share).
        demand = demand_buyback(facility["id"], p3["id"], "MISREPRESENTATION")
        settled = settle_buyback(demand["id"])
        assert settled["repurchase_price_cents"] == 100_000
        assert get_participant(p3["id"])["status"] == "EXITED"

        assert get_consent_vote(v3["id"])["status"] == "VOIDED"
        assert get_consent_vote(v1["id"])["status"] == "CAST"
        rebased = get_modification_request(mod["id"])
        # Adjusted base 10,000,000 - 1,000,000 = 9,000,000; P1 alone approves.
        assert rebased["approving_commitment_cents"] == 6_000_000
        assert rebased["approving_share_bps"] == 6666  # floor(10000 * 6 / 9)
        assert rebased["cast_share_bps"] == 6666
        assert get_facility(facility["id"])["committed_cents"] == 9_000_000


class TestBuybackGuards:
    def test_buyback_not_funded_rejected(self):
        """PRD §3.9: "A demander that is not `FUNDED` fails with
        `ERR_BUYBACK_NOT_FUNDED`".

        Design: Corner/validations/buyback_not_funded_rejected
        """
        # Facility reaches FUNDING (an allowed posture) via a draw, but the
        # participant never confirms its wire, so it stays COMMITTED.
        setup = setup_committed_facility([("NP", 5_000_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]
        create_draw(facility["id"], 1_000_000)
        assert get_facility(facility["id"])["status"] == "FUNDING"
        assert get_participant(participant["id"])["status"] == "COMMITTED"

        resp = api_client.create_buyback_demand(
            create_buyback_demand_payload(facility["id"], breach_type="MISREPRESENTATION"),
            make_participant_headers(participant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYBACK_NOT_FUNDED, expected_status=409)

    def test_buyback_duplicate_pending_rejected(self):
        """PRD §3.9: "a participant may hold only one open demand per facility —
        `DEMANDED`, `ACKNOWLEDGED`, or `DISPUTED` — a second failing
        `ERR_BUYBACK_ALREADY_PENDING`."

        Design: Corner/validations/buyback_duplicate_pending_rejected
        """
        setup = setup_funded_facility(
            [("DP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        participant = setup["participants"][0]
        demand_buyback(facility["id"], participant["id"], "MISREPRESENTATION")

        resp = api_client.create_buyback_demand(
            create_buyback_demand_payload(facility["id"], breach_type="SERVICING_BREACH"),
            make_participant_headers(participant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYBACK_ALREADY_PENDING, expected_status=409)

    def test_buyback_settle_from_demanded_rejected(self):
        """PRD §3.9: "Settlement moves `ACKNOWLEDGED` → `SETTLED`".
        PRD §2.9: "6. Target-state legality: the target resource's own state
        permits the transition; terminal states reject everything — otherwise
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/buyback_settle_from_demanded_rejected
        """
        setup = setup_funded_facility(
            [("DP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        participant = setup["participants"][0]
        demand = demand_buyback(facility["id"], participant["id"], "DOCUMENTATION_DEFECT")

        resp = api_client.settle_buyback_demand(demand["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        refreshed = get_success_data(api_client.get_buyback_demand(demand["id"], AGENT))
        assert refreshed["status"] == "DEMANDED"
