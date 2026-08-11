"""Classification: class bracket overlap, selector empty set, capacity
boundary, half-open weight boundaries, and placed_count conservation
(PRD §3.3, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_show_class,
    build_show_state,
    classify_entry,
    create_class,
    create_fair,
    get_class,
    get_entry,
    validate_error,
    validate_success,
    weigh_entry,
)

ADMIN = TEST_USERS["admin"]


class TestClassBrackets:
    def test_class_range_overlap_rejected_touching_allowed(self, api):
        """PRD §3.3: "Two classes of the same fair and species may not have
        overlapping brackets under half-open semantics — touching boundaries,
        where one class's maximum equals the next class's minimum, are allowed
        — and `class_code` must be unique within the fair and species; either
        violation is rejected with `ERR_CLASS_RANGE_OVERLAP` (HTTP 409)."

        Design: Corner/validations/class_range_overlap_rejected_touching_allowed
        """
        fair = create_fair(name="Fair V4")
        create_class(
            fair["id"], species="MARKET_LAMB", class_code="LAMB-A",
            weight_min_lbs=90, weight_max_lbs=100,
        )
        overlap = api_client.create_class(
            {
                "fair_id": fair["id"], "species": "MARKET_LAMB",
                "class_code": "LAMB-B", "weight_min_lbs": 95,
                "weight_max_lbs": 105, "capacity": 5,
            },
            ADMIN,
        )
        validate_error(overlap, ApiErrorId.ERR_CLASS_RANGE_OVERLAP)

        touching = api_client.create_class(
            {
                "fair_id": fair["id"], "species": "MARKET_LAMB",
                "class_code": "LAMB-C", "weight_min_lbs": 100,
                "weight_max_lbs": 120, "capacity": 5,
            },
            ADMIN,
        )
        created = validate_success(touching, 201)
        assert_show_class(created)
        assert created["status"] == "OPEN"
        assert created["placed_count"] == 0


class TestClassifySelector:
    def test_no_class_for_weight_returns_error(self, api):
        """PRD §3.3: "Without an explicit target, the selector considers every
        `OPEN` class of the entry's fair and species whose bracket contains the
        official weight — lower bound inclusive, upper bound exclusive — and
        whose `placed_count` is still below `capacity`; among the eligible
        classes it picks the one with the lowest `weight_min_lbs`, breaking
        ties by earliest `created_at` and never by `id`, and an empty eligible
        set is rejected with `ERR_NO_CLASS_FOR_WEIGHT` (HTTP 422)."

        Design: Corner/validations/no_class_for_weight_returns_error
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair V7"},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 2000}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            advance_to="WEIGH_IN",
        )
        entry_id = ctx["entries"][0]["id"]
        resp = api_client.classify_entry(entry_id, TEST_USERS["show_clerk"])
        validate_error(resp, ApiErrorId.ERR_NO_CLASS_FOR_WEIGHT)
        entry = get_entry(entry_id)
        assert entry["status"] == "WEIGHED"
        assert entry["class_id"] is None

    def test_class_capacity_boundary_full_at_capacity(self, api):
        """PRD §3.3: "When the request names an explicit `class_id`, failures
        map specifically: a target that is not `OPEN` yields
        `ERR_CLASS_NOT_OPEN` (HTTP 409), a target already at capacity yields
        `ERR_CLASS_CAPACITY_FULL` (HTTP 409), and a weight outside the bracket
        or a species mismatch yields `ERR_NO_CLASS_FOR_WEIGHT` — in that
        order."

        Design: Corner/calculations/class_capacity_boundary_full_at_capacity
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair K4"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 95},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 96},
            ],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 1}],
            advance_to="WEIGH_IN",
        )
        class_id = ctx["classes"][0]["id"]
        first = classify_entry(ctx["entries"][0]["id"], class_id)
        assert first["status"] == "CLASSIFIED"
        assert get_class(class_id)["placed_count"] == 1, (
            "first classify fills the class to capacity 1"
        )

        resp = api_client.classify_entry(
            ctx["entries"][1]["id"], TEST_USERS["show_clerk"], class_id=class_id
        )
        validate_error(resp, ApiErrorId.ERR_CLASS_CAPACITY_FULL)
        assert get_entry(ctx["entries"][1]["id"])["status"] == "WEIGHED"

    def test_class_weight_min_inclusive_max_exclusive(self, api):
        """PRD §3.3: "Without an explicit target, the selector considers every
        `OPEN` class of the entry's fair and species whose bracket contains the
        official weight — lower bound inclusive, upper bound exclusive — and
        whose `placed_count` is still below `capacity`; among the eligible
        classes it picks the one with the lowest `weight_min_lbs`, breaking
        ties by earliest `created_at` and never by `id`, and an empty eligible
        set is rejected with `ERR_NO_CLASS_FOR_WEIGHT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/class_weight_min_inclusive_max_exclusive
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R6B"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 100.0},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 95.0},
            ],
            classes=[
                {"species": "MARKET_LAMB", "class_code": "LAMB-LT",
                 "weight_min_lbs": 90, "weight_max_lbs": 100, "capacity": 5},
                {"species": "MARKET_LAMB", "class_code": "LAMB-HV",
                 "weight_min_lbs": 100, "weight_max_lbs": 120, "capacity": 5},
            ],
            advance_to="WEIGH_IN",
        )
        class_lt = ctx["classes"][0]["id"]
        class_hv = ctx["classes"][1]["id"]

        placed_100 = classify_entry(ctx["entries"][0]["id"])
        assert placed_100["class_id"] == class_hv, (
            "100.0 is inside [100,120) (min inclusive) and outside [90,100) "
            "(max exclusive)"
        )
        placed_95 = classify_entry(ctx["entries"][1]["id"])
        assert placed_95["class_id"] == class_lt

    def test_class_weight_at_top_bound_finds_no_class(self, api):
        """PRD §3.3: "Without an explicit target, the selector considers every
        `OPEN` class of the entry's fair and species whose bracket contains the
        official weight — lower bound inclusive, upper bound exclusive — and
        whose `placed_count` is still below `capacity`; among the eligible
        classes it picks the one with the lowest `weight_min_lbs`, breaking
        ties by earliest `created_at` and never by `id`, and an empty eligible
        set is rejected with `ERR_NO_CLASS_FOR_WEIGHT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/class_weight_min_inclusive_max_exclusive
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R6B-top"},
            entries=[{"species": "MARKET_LAMB", "tag_number": "L-009",
                      "weight_lbs": 120.0}],
            classes=[
                {"species": "MARKET_LAMB", "class_code": "LAMB-LT",
                 "weight_min_lbs": 90, "weight_max_lbs": 100, "capacity": 5},
                {"species": "MARKET_LAMB", "class_code": "LAMB-HV",
                 "weight_min_lbs": 100, "weight_max_lbs": 120, "capacity": 5},
            ],
            advance_to="WEIGH_IN",
        )
        resp = api_client.classify_entry(
            ctx["entries"][0]["id"], TEST_USERS["show_clerk"]
        )
        validate_error(resp, ApiErrorId.ERR_NO_CLASS_FOR_WEIGHT)
        assert get_entry(ctx["entries"][0]["id"])["class_id"] is None


class TestPlacedCountInvariant:
    def test_placement_count_conserved_across_reweigh_reclassify(self, api):
        """PRD §3.3: "Recording a fresh ticket for a `CLASSIFIED` entry is a
        reweigh: the prior `ACTIVE` ticket is voided with `void_reason`
        `SUPERSEDED`, the entry's `class_id` is cleared to null, the prior
        class's `placed_count` is decremented by one, the entry falls back
        `CLASSIFIED` → `WEIGHED`, and the official weight is recomputed."
        PRD §3.3: "A successful classification moves the entry `WEIGHED` →
        `CLASSIFIED`, sets its `class_id`, and increments the target class's
        `placed_count` by one."

        Design: Difficulty/compensating_invariant/placement_count_conserved_across_reweigh_reclassify
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R9B"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 95.0},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 110.0},
            ],
            classes=[
                {"species": "MARKET_LAMB", "class_code": "LAMB-LT",
                 "weight_min_lbs": 90, "weight_max_lbs": 100, "capacity": 5},
                {"species": "MARKET_LAMB", "class_code": "LAMB-HV",
                 "weight_min_lbs": 100, "weight_max_lbs": 120, "capacity": 5},
            ],
            entry_class_map={0: 0, 1: 1},
            advance_to="WEIGH_IN",
        )
        class_lt, class_hv = ctx["classes"][0]["id"], ctx["classes"][1]["id"]
        assert get_class(class_lt)["placed_count"] == 1
        assert get_class(class_hv)["placed_count"] == 1

        # Reweigh entry 110 -> 98.0: un-classifies it out of LAMB-HV.
        weigh_entry(ctx["entries"][1]["id"], 98.0,
                    weighed_at="2026-07-01T11:00:00Z")
        assert get_class(class_lt)["placed_count"] == 1
        assert get_class(class_hv)["placed_count"] == 0, (
            "reweigh decrements the vacated class"
        )

        classify_entry(ctx["entries"][1]["id"], class_lt)
        assert get_class(class_lt)["placed_count"] == 2
        assert get_class(class_hv)["placed_count"] == 0

    def test_placed_count_decremented_on_disqualify_from_classified(self, api):
        """PRD §3.8: "if the entry was `CLASSIFIED` or `SHOWN`, its `class_id`
        is cleared, the class's `placed_count` is decremented by one, and a
        `FINALIZED` class reopens to `OPEN`."

        Design: Difficulty/compensating_invariant/placement_count_conserved_across_reweigh_reclassify
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R9B-dq"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 95.0},
                {"species": "MARKET_LAMB", "tag_number": "L-002",
                 "weight_lbs": 96.0},
            ],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0},
            advance_to="WEIGH_IN",
        )
        class_id = ctx["classes"][0]["id"]
        assert get_class(class_id)["placed_count"] == 2

        resp = api_client.disqualify_entry(
            ctx["entries"][1]["id"], "papers mismatch", ADMIN
        )
        disqualified = validate_success(resp, 200)
        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["class_id"] is None
        assert get_class(class_id)["placed_count"] == 1, (
            "disqualify decrements placed_count for the surviving entry only"
        )
        assert get_entry(ctx["entries"][0]["id"])["status"] == "CLASSIFIED"
