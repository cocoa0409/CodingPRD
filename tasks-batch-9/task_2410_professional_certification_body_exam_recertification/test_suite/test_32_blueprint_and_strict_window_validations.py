"""The strict accrual window's left edge, and the two rules that sit below the schema."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

STRICT_PROGRAM = {"ceu_credit_accrual_basis": "STRICT_CYCLE"}

WEIGHTS_SHORT_OF_A_HUNDRED = [
    {"domain_code": "D1", "weight_pct": 60, "min_operational_items": 1},
    {"domain_code": "D2", "weight_pct": 30, "min_operational_items": 1},
]
WEIGHTS_ON_A_REPEATED_DOMAIN = [
    {"domain_code": "D1", "weight_pct": 50, "min_operational_items": 1},
    {"domain_code": "D1", "weight_pct": 50, "min_operational_items": 1},
]

PRETEST_BATCH = {
    "is_pretest": True,
    "response_count": 40,
    "correct_count": 24,
    "upper_n": 10,
    "upper_correct": 9,
    "lower_n": 10,
    "lower_correct": 3,
}


def _strict_cycle(api):
    """An ACTIVE credential whose cycle pinned STRICT_CYCLE at creation."""
    state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
    cycle = fx.read_cycle(api, state.cycle_id)
    assert cycle["accrual_basis_snapshot"] == "STRICT_CYCLE"
    assert float(cycle["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)
    assert str(cycle["starts_on"]).startswith("2026-08-10")
    return state


def _claim(api, state, activity_date, provider, contact_hours=12.0):
    return api.claim_ceu_activity(
        state.cycle_id,
        f.claim_ceu_payload(activity_date=activity_date, provider=provider,
                            contact_hours=contact_hours),
        state.owner_headers)


def _a_programme_with_one_draft_item(api):
    """The only programme in the database, plus an item that never left DRAFT."""
    program = fx.active_program(api)
    item = fx.draft_item(api, program["id"], cognitive_level="RECALL",
                         stem="CPX draft item")
    assert item["status"] == "DRAFT"
    return program, item


class TestStrictCycleLookbackWindow:
    """The strict window opens on `starts_on` itself and not a day earlier."""

    def test_a_date_ninety_days_before_the_cycle_is_outside_the_strict_window(self, api):
        """Under STRICT_CYCLE the 2026-05-12 claim that a carryover cycle would have
        admitted is refused on the window, and no activity row survives the attempt.

        PRD §3.11: "Under `STRICT_CYCLE`, the accrual window runs from the cycle's `starts_on`
        to its `ends_on` with both ends inclusive, and any carried-in credit is forfeited —
        the carry-in contribution is 0.00 regardless of what `carryover_credits_in` holds."

        PRD §3.11: "An activity dated exactly on `starts_on` or exactly on `ends_on` is
        inside the window under both variants; an activity dated 90 days before `starts_on`
        counts under `CARRYOVER_ALLOWED` and is rejected at submission time with
        `ERR_ACTIVITY_OUTSIDE_CYCLE` under `STRICT_CYCLE`."

        Design: Corner/validations/strict_cycle_refuses_the_lookback_date_that_carryover_allowed_accepts
        """
        state = _strict_cycle(api)

        refused = _claim(api, state, "2026-05-12T00:00:00Z", "Spring Institute")

        validate_error(refused, ApiErrorId.ERR_ACTIVITY_OUTSIDE_CYCLE.value, 422)
        assert fx.read_activities_of(api, state.cycle_id) == []
        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["status"] == "OPEN"

    def test_the_opening_day_itself_is_inside_the_window_and_satisfies_the_cycle(self, api):
        """A claim dated exactly on `starts_on` is admitted, awards twelve credits at
        submission, and once approved carries the cycle and its holder's mirror to SATISFIED.

        PRD §3.11: "A new claim has its `cycle_id` set to the cycle it was claimed against,
        `status` `SUBMITTED`, `counted` false, `credits_counted` 0.00, `reviewer_user_id` and
        `audit_verifier_user_id` null, and `review_note` null until a reviewer supplies one.
        Its `credits_awarded` is recorded immediately as the `contact_hours` multiplied by the
        category's credit multiplier, rounded half up to two decimals."

        PRD §3.11: "An `APPROVE` requires the activity to be `SUBMITTED`, moves it
        `SUBMITTED → APPROVED`, and sets `counted` to true."

        PRD §3.11: "Fourth, the cycle's `credits_applied` becomes the sum of
        `credits_counted` across the eligible set plus the carry-in contribution, rounded half
        up to two decimals."

        Design: Corner/validations/strict_cycle_refuses_the_lookback_date_that_carryover_allowed_accepts
        """
        state = _strict_cycle(api)
        _claim(api, state, "2026-05-12T00:00:00Z", "Spring Institute")

        claimed = validate_success(
            _claim(api, state, "2026-08-10T00:00:00Z", "Opening Day Seminar"), 201)
        assert float(claimed["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert claimed["status"] == "SUBMITTED"
        assert claimed["counted"] is False
        ax.assert_ceu_activity(claimed)

        approved = validate_success(api.review_ceu_activity(
            claimed["id"], f.review_ceu_payload("APPROVE"), fx.ELIGIBILITY_REVIEWER_3), 200)
        assert float(approved["credits_counted"]) == pytest.approx(12.00, abs=0.01)
        assert approved["counted"] is True

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"

        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert certificant["status"] == "ACTIVE"


class TestBlueprintWeightsAndStatsEligibility:
    """Two schema-valid bodies are still refused, each by the rule that owns it."""

    def test_weights_totalling_ninety_are_refused_on_the_blueprint_not_on_the_schema(
            self, api):
        """Every required field is present and correctly typed, so the answer is the
        blueprint rule's 400 rather than the schema layer's.

        PRD §3.1: "The `weight_pct` values are integers and must sum to exactly 100, and no
        `domain_code` may repeat inside the array — a violation of either constraint is
        `ERR_BLUEPRINT_WEIGHTS_INVALID`."

        PRD §2.7: "8. **Blueprint weights.** The `weight_pct` values across `domain_specs` sum
        to exactly 100 and every `domain_code` in the array is distinct → otherwise
        `ERR_BLUEPRINT_WEIGHTS_INVALID` (400). Checked both when a program is created and
        again when it is activated."

        Design: Corner/validations/blueprint_weight_sum_and_stats_eligibility_rejects_a_ninety_point_split_and_a_draft_item
        """
        program, _item = _a_programme_with_one_draft_item(api)

        refused = api.create_program(
            f.create_program_payload(name="Certified Practitioner W", credential_code="CPW",
                                     domain_specs=WEIGHTS_SHORT_OF_A_HUNDRED),
            fx.PROGRAM_ADMIN)

        error = validate_error(refused, ApiErrorId.ERR_BLUEPRINT_WEIGHTS_INVALID.value, 400)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        rows, meta = validate_paginated(api.list_programs(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [program["id"]]

    def test_a_repeated_domain_code_is_refused_even_though_its_weights_total_a_hundred(
            self, api):
        """Fifty plus fifty satisfies the sum and still fails, because the uniqueness half of
        the same rule is independent, and neither rejected programme was stored.

        PRD §3.1: "That blueprint holds between 1 and 8 rows; each row names a `domain_code`,
        a `weight_pct`, and a `min_operational_items` count of at least zero."

        PRD §3.1: "The `weight_pct` values are integers and must sum to exactly 100, and no
        `domain_code` may repeat inside the array — a violation of either constraint is
        `ERR_BLUEPRINT_WEIGHTS_INVALID`."

        Design: Corner/validations/blueprint_weight_sum_and_stats_eligibility_rejects_a_ninety_point_split_and_a_draft_item
        """
        program, _item = _a_programme_with_one_draft_item(api)
        api.create_program(
            f.create_program_payload(name="Certified Practitioner W", credential_code="CPW",
                                     domain_specs=WEIGHTS_SHORT_OF_A_HUNDRED),
            fx.PROGRAM_ADMIN)

        refused = api.create_program(
            f.create_program_payload(name="Certified Practitioner V", credential_code="CPV",
                                     domain_specs=WEIGHTS_ON_A_REPEATED_DOMAIN),
            fx.PROGRAM_ADMIN)

        error = validate_error(refused, ApiErrorId.ERR_BLUEPRINT_WEIGHTS_INVALID.value, 400)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        _rows, meta = validate_paginated(api.list_programs(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 1
        assert fx.read_program(api, program["id"])["credential_code"] == "CPX"

    def test_a_batch_aimed_at_a_draft_item_is_refused_and_moves_no_accumulator(self, api):
        """The counts are internally consistent, so the objection is the item's maturity, and
        the refusal leaves all twelve accumulators and both statistics untouched.

        PRD §3.3: "Ingestion is permitted only while the item's `status` is `APPROVED`,
        `PRETEST`, `OPERATIONAL`, or `FLAGGED`; a `DRAFT`, `IN_REVIEW`,
        `REVISION_REQUESTED`, `REJECTED`, or `RETIRED` item is refused with
        `ERR_ITEM_NOT_ELIGIBLE_FOR_STATS`."

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list is empty,
        its `review_round` starts at 1, all twelve of its response accumulators start at 0,
        and its `stat_basis_applied` starts at `INSUFFICIENT_DATA` with both `p_value` and
        `discrimination_index` null."

        PRD §3.1: "`operational_item_count` is the number of the program's items whose
        `status` is `OPERATIONAL`"

        Design: Corner/validations/blueprint_weight_sum_and_stats_eligibility_rejects_a_ninety_point_split_and_a_draft_item
        """
        program, item = _a_programme_with_one_draft_item(api)
        assert fx.read_program(api, program["id"])["blueprint_posture"] == "DEFICIENT"

        refused = api.ingest_response_batch(item["id"], PRETEST_BATCH, fx.PSYCHOMETRICIAN)

        validate_error(refused, ApiErrorId.ERR_ITEM_NOT_ELIGIBLE_FOR_STATS.value, 422)
        stored = fx.read_item(api, item["id"])
        assert stored["status"] == "DRAFT"
        assert stored["pretest_response_count"] == 0
        assert stored["operational_response_count"] == 0
        assert stored["p_value"] is None
        assert stored["discrimination_index"] is None
        assert stored["stat_basis_applied"] == "INSUFFICIENT_DATA"
        assert stored["flag_reason"] is None

        settled = fx.read_program(api, program["id"])
        assert settled["operational_item_count"] == 0
        assert settled["blueprint_posture"] == "DEFICIENT"
        ax.assert_blueprint_posture_agrees_with_counts(settled)
