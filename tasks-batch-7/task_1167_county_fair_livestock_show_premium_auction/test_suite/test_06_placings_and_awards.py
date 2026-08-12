"""Placing submission rules, premium award computation, purse conservation,
and the affidavit-revoke disqualification cascade (PRD §3.4, §3.5, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    award_for_entry,
    build_show_state,
    get_class,
    get_entry,
    get_fair,
    get_ring_slot,
    list_placings,
    make_judge_headers,
    placing_for_entry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin"]
TREASURER = TEST_USERS["treasurer"]
INSPECTOR = TEST_USERS["health_inspector"]


class TestPlacingSubmissionRules:
    def test_placings_rank_gap_rejected_and_atomic(self, api):
        """PRD §3.4: "then rank contiguity — the ranks must be exactly the
        contiguous set 1 through N with no duplicates or gaps, else
        `ERR_RANK_SEQUENCE_INVALID` (HTTP 422)".
        PRD §3.4: "Either every line is valid and the whole set is recorded, or
        nothing is."

        Design: Corner/validations/placings_rank_gap_rejected_and_atomic
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair V11"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 100},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 101},
            ],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0},
            judges=[{"qualified_species": ["MARKET_LAMB"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            advance_to="SHOWING",
        )
        slot = ctx["slots"][0]
        judge_id = ctx["judges"][0]["id"]
        e1, e2 = ctx["entries"][0]["id"], ctx["entries"][1]["id"]

        resp = api_client.submit_placings(
            slot["id"],
            [
                {"entry_id": e1, "rank": 1, "award": "NONE"},
                {"entry_id": e2, "rank": 3, "award": "NONE"},
            ],
            make_judge_headers(judge_id),
        )
        validate_error(resp, ApiErrorId.ERR_RANK_SEQUENCE_INVALID)
        assert list_placings() == [], "atomic rejection persists nothing"
        assert get_ring_slot(slot["id"])["status"] == "IN_PROGRESS"
        assert get_class(ctx["classes"][0]["id"])["status"] == "OPEN"
        assert get_entry(e1)["status"] == "CLASSIFIED"
        assert get_entry(e2)["status"] == "CLASSIFIED"

    def test_placings_foreign_entry_rejected(self, api):
        """PRD §3.4: "and finally per-line membership — each line's entry must
        belong to the slot's class and be `CLASSIFIED`, else
        `ERR_ENTRY_NOT_IN_CLASS` (HTTP 422)."

        Design: Corner/validations/placings_foreign_entry_rejected
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair V12"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 95},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 105},
            ],
            classes=[
                {"species": "MARKET_LAMB", "class_code": "LAMB-A",
                 "weight_min_lbs": 90, "weight_max_lbs": 100, "capacity": 5},
                {"species": "MARKET_LAMB", "class_code": "LAMB-B",
                 "weight_min_lbs": 100, "weight_max_lbs": 120, "capacity": 5},
            ],
            entry_class_map={0: 0, 1: 1},
            judges=[{"qualified_species": ["MARKET_LAMB"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            advance_to="SHOWING",
        )
        slot = ctx["slots"][0]
        judge_id = ctx["judges"][0]["id"]
        e1, e2 = ctx["entries"][0]["id"], ctx["entries"][1]["id"]

        resp = api_client.submit_placings(
            slot["id"],
            [
                {"entry_id": e1, "rank": 1, "award": "NONE"},
                {"entry_id": e2, "rank": 2, "award": "NONE"},
            ],
            make_judge_headers(judge_id),
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_IN_CLASS)
        assert list_placings() == []

    def test_second_grand_champion_same_species_rejected(self, api):
        """PRD §3.4: "then champion uniqueness — at most one `GRAND_CHAMPION`
        and one `RESERVE_CHAMPION` per species per fair, else
        `ERR_CHAMPION_ALREADY_AWARDED` (HTTP 409)".

        Design: Corner/validations/second_grand_champion_same_species_rejected
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair V13"},
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200},
                {"species": "MARKET_STEER", "tag_number": "S-002",
                 "weight_lbs": 1300},
            ],
            classes=[
                {"species": "MARKET_STEER", "class_code": "STEER-A",
                 "weight_min_lbs": 1000, "weight_max_lbs": 1250,
                 "capacity": 5},
                {"species": "MARKET_STEER", "class_code": "STEER-B",
                 "weight_min_lbs": 1250, "weight_max_lbs": 1500,
                 "capacity": 5},
            ],
            entry_class_map={0: 0, 1: 1},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[
                {"class_index": 0, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T09:00:00Z",
                 "ends_at": "2026-07-10T10:00:00Z"},
                {"class_index": 1, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T10:15:00Z",
                 "ends_at": "2026-07-10T11:00:00Z"},
            ],
            placings=[{
                "slot_index": 0,
                "lines": [{"entry_index": 0, "rank": 1,
                           "award": "GRAND_CHAMPION"}],
            }],
            advance_to="SHOWING",
        )
        slot_b = ctx["slots"][1]
        judge_id = ctx["judges"][0]["id"]
        assert get_class(ctx["classes"][0]["id"])["status"] == "FINALIZED"

        resp = api_client.submit_placings(
            slot_b["id"],
            [{"entry_id": ctx["entries"][1]["id"], "rank": 1,
              "award": "GRAND_CHAMPION"}],
            make_judge_headers(judge_id),
        )
        validate_error(resp, ApiErrorId.ERR_CHAMPION_ALREADY_AWARDED)
        assert get_ring_slot(slot_b["id"])["status"] == "IN_PROGRESS"
        assert get_class(ctx["classes"][1]["id"])["status"] == "OPEN"


class TestStateFairQualification:
    def test_state_fair_qualification_rank_threshold_inclusive(self, api):
        """PRD §3.4: "Each entry's `state_fair_qualified` is recomputed: it is
        set when the placing's `award` is anything other than `NONE`, or when
        the `rank` is at or under the species threshold in the fair's
        `state_qualify_rank` — the boundary is inclusive, so a rank exactly
        equal to the threshold qualifies."

        Design: Corner/calculations/state_fair_qualification_rank_threshold_inclusive
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair K1"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 100},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 101},
                {"species": "MARKET_LAMB", "tag_number": "L-003",
                 "weight_lbs": 102},
            ],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0, 2: 0},
            judges=[{"qualified_species": ["MARKET_LAMB"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{
                "slot_index": 0,
                "lines": [
                    {"entry_index": 0, "rank": 1, "award": "NONE"},
                    {"entry_index": 1, "rank": 2, "award": "NONE"},
                    {"entry_index": 2, "rank": 3, "award": "NONE"},
                ],
            }],
            advance_to="SHOWING",
        )
        # state_qualify_rank[MARKET_LAMB] == 2 (fixture default).
        assert get_entry(ctx["entries"][0]["id"])["state_fair_qualified"] is True
        assert get_entry(ctx["entries"][1]["id"])["state_fair_qualified"] is True, (
            "rank exactly at the inclusive threshold qualifies"
        )
        assert get_entry(ctx["entries"][2]["id"])["state_fair_qualified"] is False, (
            "rank 3 exceeds the threshold of 2"
        )


class TestPremiumAmountAndPool:
    def test_premium_tiered_conditional_bonus_and_cap(self, api):
        """PRD §3.5: "A large-class bonus applies when the class's
        `placed_count`, counted after the placing batch lands, is at least the
        fair's `large_class_min_entries`: the bonus is the base multiplied by
        `large_class_bonus_rate`, rounded half-up to whole cents, and is zero
        otherwise. The provisional award, `provisional_amount_cents`, is the
        base plus the bonus, capped at `premium_cap_cents` — the cap applies
        after the bonus, so the stored amount is the smaller of the two."

        Design: Difficulty/combinatorial_formula/premium_tiered_conditional_bonus_and_cap
        """
        ctx = build_show_state(
            fair_overrides={
                "name": "Fair R2A", "large_class_min_entries": 2,
                "large_class_bonus_rate": 0.10, "premium_cap_cents": 60000,
            },
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200, "exhibitor_index": 0},
                {"species": "MARKET_STEER", "tag_number": "S-002",
                 "weight_lbs": 1250, "exhibitor_index": 1},
            ],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{
                "slot_index": 0,
                "lines": [
                    {"entry_index": 0, "rank": 1, "award": "GRAND_CHAMPION"},
                    {"entry_index": 1, "rank": 2, "award": "NONE"},
                ],
            }],
            advance_to="SHOWING",
        )
        award_a = award_for_entry(ctx["entries"][0]["id"])
        award_b = award_for_entry(ctx["entries"][1]["id"])
        # class placed_count 2 >= large_class_min_entries 2 -> bonus applies.
        assert award_a["provisional_amount_cents"] == 55000, (
            "base 50000 + round_half_up(50000*0.10)=5000, under cap 60000"
        )
        assert award_b["provisional_amount_cents"] == 11000, (
            "base 10000 + 1000 bonus"
        )
        fair = get_fair(ctx["fair"]["id"])
        assert fair["available_premium_pool_cents"] == 34000, (
            "100000 budget - 55000 - 11000"
        )

    def test_premium_cap_applies_after_bonus(self, api):
        """PRD §3.5: "The provisional award, `provisional_amount_cents`, is the
        base plus the bonus, capped at `premium_cap_cents` — the cap applies
        after the bonus, so the stored amount is the smaller of the two."

        Design: Difficulty/combinatorial_formula/premium_tiered_conditional_bonus_and_cap
        """
        ctx = build_show_state(
            fair_overrides={
                "name": "Fair R2A-cap", "large_class_min_entries": 2,
                "large_class_bonus_rate": 0.10, "premium_cap_cents": 52000,
            },
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200},
                {"species": "MARKET_STEER", "tag_number": "S-002",
                 "weight_lbs": 1250},
            ],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{
                "slot_index": 0,
                "lines": [
                    {"entry_index": 0, "rank": 1, "award": "GRAND_CHAMPION"},
                    {"entry_index": 1, "rank": 2, "award": "NONE"},
                ],
            }],
            advance_to="SHOWING",
        )
        award_a = award_for_entry(ctx["entries"][0]["id"])
        assert award_a["provisional_amount_cents"] == 52000, (
            "min(50000 + 5000 bonus, cap 52000)"
        )
        award_b = award_for_entry(ctx["entries"][1]["id"])
        assert award_b["provisional_amount_cents"] == 11000

    def test_premium_pool_conserved_across_accrue_and_void(self, api):
        """PRD §3.5: "At every moment, `available_premium_pool_cents` equals
        `premium_budget_cents` minus the sum of `provisional_amount_cents`
        across all of the fair's awards in `ACCRUED`, `APPROVED`, or `PAID`
        status; `FORFEITED` awards are excluded because their reservation has
        returned to the pool."
        PRD §3.4: "Voiding moves the placing `RECORDED` → `VOIDED` with
        `void_reason` set, forfeits its premium award with the reservation
        released back to the pool, drops the entry back `SHOWN` → `CLASSIFIED`,
        recomputes `state_fair_qualified` to false, and reopens the class
        `FINALIZED` → `OPEN`."

        Design: Difficulty/compensating_invariant/premium_pool_conserved_across_accrue_and_void
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R9A"},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 1200}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            advance_to="SHOWING",
        )
        fair_id = ctx["fair"]["id"]
        assert get_fair(fair_id)["available_premium_pool_cents"] == 88000, (
            "100000 - 12000 accrued reservation"
        )

        placing = placing_for_entry(ctx["entries"][0]["id"])
        judge_id = ctx["judges"][0]["id"]
        voided = validate_success(
            api_client.void_placing(placing["id"], "misheard tag",
                                    make_judge_headers(judge_id)),
            200,
        )
        assert voided["status"] == "VOIDED"
        assert get_fair(fair_id)["available_premium_pool_cents"] == 100000, (
            "voiding the placing returns the reservation to the pool"
        )
        assert award_for_entry(ctx["entries"][0]["id"])["status"] == "FORFEITED"

    def test_premium_pool_conserved_across_accrue_and_manual_forfeit(self, api):
        """PRD §3.5: "A `Treasurer` may also forfeit an award — from `ACCRUED`
        or from `APPROVED` alike — by supplying a `reason`; forfeiture moves
        the award to `FORFEITED` and releases `provisional_amount_cents` back
        into `available_premium_pool_cents`."

        Design: Difficulty/compensating_invariant/premium_pool_conserved_across_accrue_and_void
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R9A-forfeit"},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 1200}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            advance_to="SHOWING",
        )
        fair_id = ctx["fair"]["id"]
        assert get_fair(fair_id)["available_premium_pool_cents"] == 88000

        award = award_for_entry(ctx["entries"][0]["id"])
        forfeited = validate_success(
            api_client.forfeit_premium_award(award["id"], "ineligible",
                                             TREASURER),
            200,
        )
        assert forfeited["status"] == "FORFEITED"
        assert get_fair(fair_id)["available_premium_pool_cents"] == 100000


class TestAffidavitRevokeCascade:
    def _shown_entry_with_affidavit(self, name):
        return build_show_state(
            fair_overrides={"name": name},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 1200}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            affidavit_entries=[0],
            advance_to="SHOWING",
        )

    def test_affidavit_revoke_cascade_disqualify_void_forfeit_release(self, api):
        """PRD §3.8: "revocation is blocked while the entry is `SOLD`,
        `CLEARED`, `REJECTED`, or `DISQUALIFIED` (else `ERR_INVALID_STATE`),
        and a successful revocation moves the affidavit to `REVOKED` and
        disqualifies the entry through the same cascade."
        PRD §3.8: "The cascade compensates everything the entry touched: the
        entry becomes `DISQUALIFIED`; its `RECORDED` placings become `VOIDED`;
        its `ACCRUED` or `APPROVED` awards become `FORFEITED` with
        `provisional_amount_cents` released back to the pool; its `QUEUED` or
        `PASSED` lots become `NO_SALE`; its `REQUESTED` or `APPROVED`
        disposition orders become `REJECTED` with `reject_reason` set;
        `state_fair_qualified` is cleared to false; and if the entry was
        `CLASSIFIED` or `SHOWN`, its `class_id` is cleared, the class's
        `placed_count` is decremented by one, and a `FINALIZED` class reopens
        to `OPEN`."

        Design: Difficulty/transitive_cascade/affidavit_revoke_cascade_disqualify_void_forfeit_release
        """
        ctx = self._shown_entry_with_affidavit("Fair R4A")
        fair_id = ctx["fair"]["id"]
        entry_id = ctx["entries"][0]["id"]
        assert get_fair(fair_id)["available_premium_pool_cents"] == 88000

        affidavit = ctx["affidavits"][0]
        revoked = validate_success(
            api_client.revoke_affidavit(affidavit["id"], "drug test positive",
                                        INSPECTOR),
            200,
        )
        assert revoked["status"] == "REVOKED"

        assert get_entry(entry_id)["status"] == "DISQUALIFIED"
        assert placing_for_entry(entry_id)["status"] == "VOIDED"
        assert award_for_entry(entry_id)["status"] == "FORFEITED"
        assert get_fair(fair_id)["available_premium_pool_cents"] == 100000, (
            "the forfeiture releases the 12000 reservation back to the pool"
        )

    def test_affidavit_revoke_reopens_class_and_clears_entry_placement(self, api):
        """PRD §3.8: "if the entry was `CLASSIFIED` or `SHOWN`, its `class_id`
        is cleared, the class's `placed_count` is decremented by one, and a
        `FINALIZED` class reopens to `OPEN`."
        PRD §3.8: "The cascade compensates everything the entry touched: the
        entry becomes `DISQUALIFIED`; its `RECORDED` placings become `VOIDED`;
        its `ACCRUED` or `APPROVED` awards become `FORFEITED` with
        `provisional_amount_cents` released back to the pool; its `QUEUED` or
        `PASSED` lots become `NO_SALE`; its `REQUESTED` or `APPROVED`
        disposition orders become `REJECTED` with `reject_reason` set;
        `state_fair_qualified` is cleared to false; and if the entry was
        `CLASSIFIED` or `SHOWN`, its `class_id` is cleared, the class's
        `placed_count` is decremented by one, and a `FINALIZED` class reopens
        to `OPEN`."

        Design: Difficulty/transitive_cascade/affidavit_revoke_cascade_disqualify_void_forfeit_release
        """
        ctx = self._shown_entry_with_affidavit("Fair R4A-cls")
        entry_id = ctx["entries"][0]["id"]
        class_id = ctx["classes"][0]["id"]
        # rank 1 <= state_qualify_rank 2 -> qualified before the revoke.
        assert get_entry(entry_id)["state_fair_qualified"] is True
        assert get_class(class_id)["status"] == "FINALIZED"

        validate_success(
            api_client.revoke_affidavit(
                ctx["affidavits"][0]["id"], "drug test positive", INSPECTOR
            ),
            200,
        )
        entry = get_entry(entry_id)
        assert entry["status"] == "DISQUALIFIED"
        assert entry["class_id"] is None
        assert entry["state_fair_qualified"] is False
        show_class = get_class(class_id)
        assert show_class["status"] == "OPEN", "FINALIZED class reopens"
        assert show_class["placed_count"] == 0
