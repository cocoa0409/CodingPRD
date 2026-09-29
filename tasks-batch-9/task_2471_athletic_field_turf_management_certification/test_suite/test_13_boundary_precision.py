"""Values sitting exactly on a documented threshold, and their neighbours."""

from test_helpers import (
    ApiErrorId,
    assert_capital_conserved,
    assert_two_decimals,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestGmaxMeanOnTheMandatoryLimit:
    def test_a_mean_of_exactly_two_hundred_is_advisory_and_not_a_failure(
        self, client, roster
    ):
        """One tenth of a gram separates a restriction from an unsafe closure.

        "The verdict is then read off two thresholds, both of which are inclusive
        on the lower side of the band they close: a mean of 165.0 g or less is a
        `PASS`, a mean above 165.0 g but no more than 200.0 g is an `ADVISORY`, and
        a mean strictly above 200.0 g is a `FAIL`."

        "A mean of exactly 165.0 is therefore a `PASS` and a mean of exactly 200.0
        is an `ADVISORY`."

        "An advisory order pushes the field `OPEN → RESTRICTED`, which permits
        `PRACTICE` and `COMMUNITY` bookings to continue while barring `GAME` and
        `TOURNAMENT` — an attempt at either of the barred classes is refused with
        `ERR_FIELD_RESTRICTED_FOR_ACTIVITY`."

        "The age component is 100.00 minus the ratio of `age_years` to
        `expected_life_years` expressed as a percentage, likewise floored at 0.00
        and rounded half up to two decimals, so a surface exactly at its nominal
        life scores 0.00 on age and one past it is floored rather than negative."

        Design: Difficulty/boundary_precision_check/gmax_mean_exactly_at_mandatory_limit_is_advisory_not_fail
        """
        field = fixtures.register_grass_practice_3(client, roster)
        assessment, order = fixtures.advise_field_restricted(
            client, roster, field["id"], [199.9, 200.0, 200.1]
        )

        # 599.9 spread either side of the limit averages back onto it exactly.
        assert round(float(assessment["gmax_mean_value"]), 1) == 200.0
        assert assessment["result"] == "ADVISORY"
        assert assessment["result"] != "FAIL"

        assert order["severity"] == "ADVISORY"
        assert order["status"] == "OPEN"
        assert order["source_assessment_id"] == assessment["id"]

        after = fixtures.read_field(client, roster, field["id"])
        assert after["open_advisory_remediation_count"] == 1
        assert after["open_mandatory_remediation_count"] == 0
        assert after["play_status"] == "RESTRICTED"
        assert after["play_status"] != "CLOSED_UNSAFE"
        assert round(float(after["latest_gmax_mean_value"]), 1) == 200.0

        # Wear 100.00 x 0.50 + age 91.67 x 0.20 + a safety component of exactly
        # 0.00, because the mean sits on the mandatory limit itself.
        assert_two_decimals(
            after["condition_index_agronomic"], 68.33, "Field.condition_index_agronomic"
        )
        assert_two_decimals(after["age_years"], 1.00, "Field.age_years")

        # A tenth of a gram higher, on an untouched field, reads the other band.
        neighbour = fixtures.register_grass_main_1(client, roster)
        failing, failing_order = fixtures.fail_field_unsafe(
            client, roster, neighbour["id"], [200.0, 200.1, 200.2]
        )
        assert round(float(failing["gmax_mean_value"]), 1) == 200.1
        assert failing["result"] == "FAIL"
        assert failing_order["severity"] == "MANDATORY"
        neighbour_after = fixtures.read_field(client, roster, neighbour["id"])
        assert neighbour_after["play_status"] == "CLOSED_UNSAFE"
        assert neighbour_after["open_mandatory_remediation_count"] == 1

    def test_the_two_neighbouring_means_refuse_bookings_in_different_words(
        self, client, roster
    ):
        """The boundary decides which of two non-interchangeable errors is returned.

        "A `RESTRICTED` field accepts only `PRACTICE` and `COMMUNITY`."

        "A `CLOSED_ADMIN`, `CLOSED_UNSAFE` or `RETIRED` field accepts no activity at
        all."

        "Two distinct errors express these refusals and they are not
        interchangeable: a posture of `CLOSED_ADMIN`, `CLOSED_UNSAFE` or `RETIRED`
        yields `ERR_FIELD_NOT_PLAYABLE` (HTTP 422), whereas an `OPEN` or
        `RESTRICTED` field that simply will not take the requested intensity yields
        `ERR_FIELD_RESTRICTED_FOR_ACTIVITY` (HTTP 422)."

        "A mean of exactly 165.0 is therefore a `PASS` and a mean of exactly 200.0
        is an `ADVISORY`."

        Design: Difficulty/boundary_precision_check/gmax_mean_exactly_at_mandatory_limit_is_advisory_not_fail
        """
        restricted = fixtures.register_grass_practice_3(client, roster)
        fixtures.advise_field_restricted(
            client, roster, restricted["id"], [199.9, 200.0, 200.1]
        )
        assert (
            fixtures.read_field(client, roster, restricted["id"])["play_status"]
            == "RESTRICTED"
        )

        # The advisory band still allows the gentler activity classes through.
        practice = fixtures.request_booking(
            client,
            roster,
            restricted["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T10:00:00Z",
            window_end_utc="2026-08-05T12:00:00Z",
            expected_participant_count=30,
        )
        assert practice["status"] == "SCHEDULED"
        assert fixtures.confirm_booking(client, roster, practice["id"])[
            "status"
        ] == "CONFIRMED"

        intensity_error = validate_error(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=restricted["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="GAME",
                    window_start_utc="2026-08-07T19:00:00Z",
                    window_end_utc="2026-08-07T21:00:00Z",
                    expected_participant_count=60,
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.FIELD_RESTRICTED_FOR_ACTIVITY,
            422,
        )
        assert intensity_error["error_id"] != ApiErrorId.FIELD_NOT_PLAYABLE

        # One tenth of a gram past the limit and even a practice is refused, in
        # the other vocabulary.
        closed = fixtures.register_grass_main_1(client, roster)
        fixtures.fail_field_unsafe(client, roster, closed["id"], [200.0, 200.1, 200.2])
        assert (
            fixtures.read_field(client, roster, closed["id"])["play_status"]
            == "CLOSED_UNSAFE"
        )
        posture_error = validate_error(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=closed["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="PRACTICE",
                    window_start_utc="2026-08-05T10:00:00Z",
                    window_end_utc="2026-08-05T12:00:00Z",
                    expected_participant_count=30,
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.FIELD_NOT_PLAYABLE,
            422,
        )
        assert posture_error["error_id"] != ApiErrorId.FIELD_RESTRICTED_FOR_ACTIVITY


class TestBudgetLockOnTheThreshold:
    def _identical_plan(self, client, roster, field_id, budget_id, install_year):
        """Price the same replacement twice over: 4900000 uplifted by 0.07."""
        field = fixtures.read_field(client, roster, field_id)
        plan = fixtures.draft_plan(
            client,
            roster,
            field_id,
            budget_id,
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=install_year,
        )
        fixtures.submit_plan(client, roster, plan["id"])
        return plan

    def test_a_commitment_equal_to_the_threshold_locks_but_one_cent_short_does_not(
        self, client, full_roster
    ):
        """Two budgets one cent apart, one identical commitment, two postures.

        "On creation, `committed_amount_cents` is 0, `available_amount_cents` equals
        `total_authorized_amount_cents`, `status` is `OPEN`, and
        `lock_threshold_amount_cents` is set to ninety percent of the authorisation
        — the total multiplied by 0.90 and rounded half up to a whole number of
        cents."

        "That threshold is what stops the department from spending the last tenth of
        a year's capital without a fresh look: the budget's `status` is `LOCKED`
        whenever `committed_amount_cents` is at or above `lock_threshold_amount_cents`
        and `OPEN` whenever it is below, and because the comparison is inclusive, a
        commitment exactly equal to the threshold locks the budget."

        "`available_amount_cents` is always `total_authorized_amount_cents` minus
        `committed_amount_cents`."

        Design: Difficulty/boundary_precision_check/budget_locks_when_commitment_exactly_equals_lock_threshold
        """
        on_threshold_field = fixtures.register_synthetic_stadium_1(client, full_roster)
        one_cent_richer_field = fixtures.register_synthetic_stadium_1(
            client, full_roster, name="Synthetic Stadium 2"
        )

        # 5825556 x 0.90 is 5243000.4 and 5825557 x 0.90 is 5243001.3.
        on_threshold = fixtures.authorize_budget(
            client, full_roster, fiscal_year=2027, total_authorized_amount_cents=5825556
        )
        one_cent_richer = fixtures.authorize_budget(
            client, full_roster, fiscal_year=2028, total_authorized_amount_cents=5825557
        )
        assert on_threshold["lock_threshold_amount_cents"] == 5243000
        assert one_cent_richer["lock_threshold_amount_cents"] == 5243001
        assert on_threshold["status"] == "OPEN"
        assert one_cent_richer["status"] == "OPEN"

        first = self._identical_plan(
            client, full_roster, on_threshold_field["id"], on_threshold["id"], 2028
        )
        second = self._identical_plan(
            client, full_roster, one_cent_richer_field["id"], one_cent_richer["id"], 2029
        )
        assert first["plan_funding_amount_cents"] == 5243000
        assert second["plan_funding_amount_cents"] == 5243000

        approved_first = fixtures.decide_plan(
            client, full_roster, first["id"], decision="APPROVE"
        )
        approved_second = fixtures.decide_plan(
            client, full_roster, second["id"], decision="APPROVE"
        )
        assert approved_first["funding_status"] == "APPROVED"
        assert approved_second["funding_status"] == "APPROVED"

        locked = fixtures.read_budget(client, full_roster, on_threshold["id"])
        assert locked["committed_amount_cents"] == 5243000
        assert locked["committed_amount_cents"] == locked["lock_threshold_amount_cents"]
        assert locked["status"] == "LOCKED", "an inclusive comparison locks on equality"
        assert locked["available_amount_cents"] == 582556
        assert_capital_conserved(locked)

        still_open = fixtures.read_budget(client, full_roster, one_cent_richer["id"])
        assert still_open["committed_amount_cents"] == 5243000
        assert (
            still_open["committed_amount_cents"]
            < still_open["lock_threshold_amount_cents"]
        )
        assert still_open["status"] == "OPEN", "one cent short of the threshold is below it"
        assert still_open["available_amount_cents"] == 582557
        assert_capital_conserved(still_open)

    def test_the_same_cent_decides_whether_a_sibling_plan_is_deferred(
        self, client, full_roster
    ):
        """The lock comparison is the only thing standing between DRAFT and DEFERRED.

        "Hop four is the consequence of that lock — **every other** plan on the same
        `capital_budget_id` whose `funding_status` is `DRAFT` moves `DRAFT →
        DEFERRED`, visited in order of `replacement_priority_score` descending and
        then `created_at` ascending — and a deferred plan can no longer be submitted
        until its budget reopens."

        "The plan must be in `DRAFT`, or the submission is refused with
        `ERR_PLAN_NOT_DRAFT`, and its budget must be `OPEN`, or it is refused with
        `ERR_BUDGET_LOCKED`."

        "That threshold is what stops the department from spending the last tenth of
        a year's capital without a fresh look: the budget's `status` is `LOCKED`
        whenever `committed_amount_cents` is at or above `lock_threshold_amount_cents`
        and `OPEN` whenever it is below, and because the comparison is inclusive, a
        commitment exactly equal to the threshold locks the budget."

        Design: Difficulty/boundary_precision_check/budget_locks_when_commitment_exactly_equals_lock_threshold
        """
        synthetic = fixtures.register_synthetic_stadium_1(client, full_roster)
        grass = fixtures.register_grass_practice_3(client, full_roster)
        # One cent more authority than the locking case, and therefore one cent
        # more threshold: 5243001 rather than 5243000.
        budget = fixtures.authorize_budget(
            client, full_roster, fiscal_year=2028, total_authorized_amount_cents=5825557
        )
        assert budget["lock_threshold_amount_cents"] == 5243001

        main = self._identical_plan(
            client, full_roster, synthetic["id"], budget["id"], 2029
        )
        sibling = fixtures.draft_plan(
            client,
            full_roster,
            grass["id"],
            budget["id"],
            grass["version"],
            target_surface_type="NATURAL_GRASS",
            area_sq_ft=60000,
            priority_basis="REMAINING_LIFE",
            planned_install_year=2029,
        )
        assert sibling["funding_status"] == "DRAFT"

        approved = fixtures.decide_plan(
            client, full_roster, main["id"], decision="APPROVE"
        )
        assert approved["funding_status"] == "APPROVED"

        after_budget = fixtures.read_budget(client, full_roster, budget["id"])
        assert after_budget["committed_amount_cents"] == 5243000
        assert after_budget["status"] == "OPEN"

        # The lock never fired, so the deferral cascade never ran either.
        untouched = fixtures.read_plan(client, full_roster, sibling["id"])
        assert untouched["funding_status"] == "DRAFT"
        assert untouched["funding_status"] != "DEFERRED"
        assert untouched["plan_funding_amount_cents"] == 1452000

        # Both submission preconditions are met, so the sibling still moves.
        resubmitted = validate_success(
            client.submit_replacement_plan(
                sibling["id"],
                factories.make_plan_submit_payload(full_roster.id_of("director")),
                full_roster.director_headers,
            ),
            200,
        )
        assert resubmitted["funding_status"] == "SUBMITTED"
