"""Damage claims: report-time schema and ownership gates, the provisional and
assessed fee schedule variants, and the assess/reopen/settle lifecycle."""
from test_helpers import (
    EM,
    TA,
    ApiErrorId,
    assert_damage_claim,
    create_claim,
    create_player,
    get_claim,
    get_gear,
    setup_assessed_gear_claim,
    setup_issued_kit,
    setup_player_with_issued_gear,
    validate_error,
    validate_success,
)


class TestClaimCreation:
    def test_claim_provisional_fee_and_initial_state(self, api):
        """PRD §3.7: "A fresh claim is `REPORTED` and immediately carries a
        `provisional_fee_cents` estimate computed with the replacement variant
        below."
        PRD §3.7: "The replacement variant — used for every provisional
        estimate at report time and for `LOST` claims at assessment — forces
        both factors to 1.0"

        Design: Corner/entities/claim_provisional_fee_and_initial_state
        """
        player, gear = setup_player_with_issued_gear(
            asset_tag="HLM-901", acquired_on="2025-01-01",
            player_name="Init One")
        claim = validate_success(api.create_damage_claim(
            {
                "player_id": player["id"],
                "claim_type": "DAMAGED",
                "base_value_cents": 40000,
                "gear_item_id": gear["id"],
            },
            EM,
        ), 201)
        assert_damage_claim(claim)
        assert claim["status"] == "REPORTED"
        assert claim["provisional_fee_cents"] == 40000, (
            "The provisional estimate always uses the replacement variant")
        assert claim["assessed_fee_cents"] is None
        assert claim["final_fee_cents"] is None

    def test_claim_subject_neither_fk_returns_400(self, api):
        """PRD §3.7: "exactly one subject: a `kit_assignment_id` or a
        `gear_item_id` — supplying both or neither fails schema validation
        with `ERR_INVALID_CLAIM_SUBJECT`."

        Design: Corner/validations/claim_subject_neither_fk_returns_400
        """
        player = create_player(full_name="Sub One")
        resp = api.create_damage_claim(
            {
                "player_id": player["id"],
                "claim_type": "LOST",
                "base_value_cents": 10000,
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_SUBJECT)
        assert resp.status_code == 400

    def test_claim_player_mismatch_rejected(self, api):
        """PRD §3.7: "must belong to the named player — the kit through its
        `player_id`, the gear through its `current_holder_id` — otherwise
        `ERR_CLAIM_PLAYER_MISMATCH`."

        Design: Corner/validations/claim_player_mismatch_rejected
        """
        ws = setup_issued_kit(jersey_number=61, player_name="Own One")
        p2 = create_player(full_name="Own Two", position_group="DEFENSE")

        resp = api.create_damage_claim(
            {
                "player_id": p2["id"],
                "claim_type": "LOST",
                "base_value_cents": 12000,
                "kit_assignment_id": ws["kit"]["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_PLAYER_MISMATCH)
        assert resp.status_code == 409, (
            "A kit issued to one player cannot be claimed under another")


class TestClaimStateMachine:
    def test_claim_settle_from_reported_rejected(self, api):
        """PRD §3.7: "From `ASSESSED`, three resolutions exist, all rejected
        with `ERR_CLAIM_NOT_ASSESSED` from any other state."

        Design: Corner/state_machines/claim_settle_from_reported_rejected
        """
        player, gear = setup_player_with_issued_gear(
            asset_tag="HLM-903", player_name="Pre One")
        claim = create_claim(player["id"], claim_type="DAMAGED",
                             base_value_cents=10000, gear_item_id=gear["id"])
        assert claim["status"] == "REPORTED"

        resp = api.settle_damage_claim(claim["id"], EM)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ASSESSED)
        assert get_claim(claim["id"])["status"] == "REPORTED", (
            "The rejected settle leaves the claim REPORTED")

    def test_claim_assess_twice_rejected(self, api):
        """PRD §3.7: "Assessment is performed by an `EquipmentManager` on a
        `REPORTED` claim (`ERR_CLAIM_NOT_REPORTED` otherwise) and records the
        assessed `condition_grade` supplied in the payload."
        PRD §3.7: "the factor is 1.0 when the age is at most 365 days, 0.7
        when the age falls between 366 and 730 days inclusive, and 0.4 beyond
        730 days."

        Design: Corner/state_machines/claim_assess_twice_rejected
        """
        _player, _gear, claim = setup_assessed_gear_claim(
            claim_type="DAMAGED", base_value_cents=10000, grade="B",
            asset_tag="HLM-905", acquired_on="2025-01-01")
        assert claim["assessed_fee_cents"] == 5600, (
            "Depreciated: 10000 x 0.80 grade-B x 0.70 age (577 days)")

        resp = api.assess_damage_claim(claim["id"], {"condition_grade": "C"}, EM)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REPORTED)
        after = get_claim(claim["id"])
        assert after["status"] == "ASSESSED"
        assert after["assessed_fee_cents"] == 5600, (
            "The rejected reassessment leaves the first assessment intact")
        assert after["condition_grade"] == "B"

    def test_damage_claim_assess_reopen_cycle(self, api):
        """PRD §3.7: "A `TeamAdmin` may also reopen the claim, moving it back
        to `REPORTED` with `assessed_fee_cents` and `condition_grade` reset to
        null, ready for a fresh assessment."
        PRD §3.7: "An `EquipmentManager` settles the claim: `final_fee_cents`
        takes the assessed fee, the claim lands in `SETTLED`, and the subject
        mutates per type — a lost kit's assignment moves to `LOST` (number
        freed, `closed_at` stamped, no restock), lost gear moves to `RETIRED`
        with its holder cleared, a damaged kit's assignment moves to
        `RETURNED` with the full pool-restock cascade of §3.4 (which may clear
        `reorder_blocked`), and damaged gear returns to `IN_STOCK` wearing the
        assessed `condition_grade`."
        PRD §3.7: "The depreciated variant multiplies the base value by a
        condition factor — grade `A` contributes 1.00, `B` 0.80, `C` 0.60, `F`
        0.25"

        Design: Difficulty/non_linear_state_machine/damage_claim_assess_reopen_cycle
        """
        player, gear = setup_player_with_issued_gear(
            asset_tag="HLM-301", size_spec="HELMET-XL", acquired_on="2024-01-01",
            player_name="Loop One")
        claim = create_claim(player["id"], claim_type="DAMAGED",
                             base_value_cents=30000, gear_item_id=gear["id"])

        first = validate_success(api.assess_damage_claim(
            claim["id"], {"condition_grade": "B"}, EM))
        assert first["status"] == "ASSESSED"
        assert first["assessed_fee_cents"] == 9600, (
            "First pass: 30000 x 0.80 grade-B x 0.40 age (943 days)")

        reopened = validate_success(api.reopen_damage_claim(claim["id"], TA))
        assert reopened["status"] == "REPORTED"
        assert reopened["assessed_fee_cents"] is None
        assert reopened["condition_grade"] is None, (
            "Reopen clears the assessed fields for a fresh assessment")

        second = validate_success(api.assess_damage_claim(
            claim["id"], {"condition_grade": "C"}, EM))
        assert second["assessed_fee_cents"] == 7200, (
            "Second pass: 30000 x 0.60 grade-C x 0.40 age")

        settled = validate_success(api.settle_damage_claim(claim["id"], EM))
        assert settled["status"] == "SETTLED"
        assert settled["final_fee_cents"] == 7200

        gear_after = get_gear(gear["id"])
        assert gear_after["status"] == "IN_STOCK"
        assert gear_after["condition_grade"] == "C", (
            "Damaged gear returns to stock wearing the assessed grade")


class TestDamageFeeSchedule:
    def test_damage_fee_replacement_vs_depreciated_divergence(self, api):
        """PRD §3.7: "The replacement variant — used for every provisional
        estimate at report time and for `LOST` claims at assessment — forces
        both factors to 1.0, so with identical inputs it yields a fee greater
        than or equal to the depreciated variant whenever the grade is below
        `A` or the age exceeds 365 days."
        PRD §3.7: "The `assessed_fee_cents` is then computed with the variant
        selected by `claim_type`: replacement for `LOST`, depreciated — using
        the assessed grade — for `DAMAGED`."

        Design: Difficulty/dual_variant_calc/damage_fee_replacement_vs_depreciated_divergence
        """
        p1, h1 = setup_player_with_issued_gear(
            asset_tag="HLM-001", acquired_on="2024-01-01", player_name="P One")
        p2, h2 = setup_player_with_issued_gear(
            asset_tag="HLM-002", acquired_on="2024-01-01", player_name="P Two")
        lost = create_claim(p1["id"], claim_type="LOST", base_value_cents=40000,
                            gear_item_id=h1["id"])
        damaged = create_claim(p2["id"], claim_type="DAMAGED",
                               base_value_cents=40000, gear_item_id=h2["id"])
        assert lost["provisional_fee_cents"] == 40000
        assert damaged["provisional_fee_cents"] == 40000, (
            "Provisional estimates are always the replacement variant")

        lost_assessed = validate_success(api.assess_damage_claim(
            lost["id"], {"condition_grade": "B"}, EM))
        damaged_assessed = validate_success(api.assess_damage_claim(
            damaged["id"], {"condition_grade": "B"}, EM))

        assert lost_assessed["status"] == "ASSESSED"
        assert damaged_assessed["status"] == "ASSESSED"
        assert lost_assessed["assessed_fee_cents"] == 40000, (
            "REPLACEMENT: both factors forced to 1.0 -> min(50000, "
            "max(5000, 40000))")
        assert damaged_assessed["assessed_fee_cents"] == 12800, (
            "DEPRECIATED: 40000 x 0.80 grade-B x 0.40 age (943 days) = 12800 — "
            "same inputs, different policy-selected variant, different money")

    def test_damage_fee_tiered_min_max_boundary(self, api):
        """PRD §3.7: "The product is truncated toward zero to a whole cent,
        then raised to a floor of 5,000 cents where it falls short and capped
        at a ceiling of 50,000 cents."
        PRD §3.7: "Evaluation always proceeds in that fixed order: factor
        lookup, multiplication, deductible floor, cap."

        Design: Difficulty/combinatorial_formula/damage_fee_tiered_min_max_boundary
        """
        pf, hf = setup_player_with_issued_gear(
            asset_tag="HLM-101", size_spec="HELMET-M", acquired_on="2024-01-01",
            player_name="F One")
        pc, hc = setup_player_with_issued_gear(
            asset_tag="HLM-102", size_spec="HELMET-M", acquired_on="2024-01-01",
            player_name="C One")
        floor_claim = create_claim(pf["id"], claim_type="DAMAGED",
                                   base_value_cents=6000, gear_item_id=hf["id"])
        cap_claim = create_claim(pc["id"], claim_type="LOST",
                                 base_value_cents=80000, gear_item_id=hc["id"])

        floor_assessed = validate_success(api.assess_damage_claim(
            floor_claim["id"], {"condition_grade": "F"}, EM))
        assert floor_assessed["assessed_fee_cents"] == 5000, (
            "Raw 6000 x 0.25 grade-F x 0.40 age = 600 clamps UP to the "
            "5,000-cent deductible floor")

        cap_assessed = validate_success(api.assess_damage_claim(
            cap_claim["id"], {"condition_grade": "A"}, EM))
        assert cap_assessed["assessed_fee_cents"] == 50000, (
            "Raw 80000 (replacement variant) clamps DOWN to the 50,000-cent "
            "fee ceiling")
