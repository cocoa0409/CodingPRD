"""Make-procedure step sign-off sequencing, completion gates, the completion
cascade (batch + whey + vat + intake), and vat CIP recovery."""
import pytest

from test_helpers import (
    ApiErrorId,
    CM_ALICE,
    assert_cheese_batch,
    batch_id_for_make,
    make_cheesemaker_headers,
    make_completed_batch,
    validate_error,
    validate_success,
    whey_stream_for_make,
)
from test_helpers.test_users import TEST_USERS

RECEIVER = TEST_USERS["milk_receiver_headers"]
PLANNER = TEST_USERS["make_planner_headers"]
CHEESEMAKER = TEST_USERS["cheesemaker_headers"]


class TestStepSignOff:
    def test_make_sheet_signoff_out_of_order_rejected(self, api):
        """PRD §3.4: "The sign-off for a given `stepNo` is accepted only when
        `make_steps_completed` is exactly `stepNo` minus one — steps are
        numbered from one, so the first sign-off requires zero completed steps
        — and any other arrival order fails with `ERR_STEP_OUT_OF_ORDER`."

        Design: Corner/state_machines/make_sheet_signoff_out_of_order_rejected
        """
        ctx = make_completed_batch(complete=False, steps_to_sign=1)
        resp = api.sign_off_step(
            ctx["make"]["id"], 3, make_cheesemaker_headers("cm_bob")
        )
        validate_error(resp, ApiErrorId.ERR_STEP_OUT_OF_ORDER, 409)
        make_now = validate_success(api.get_make_sheet(ctx["make"]["id"], PLANNER))
        assert make_now["make_steps_completed"] == 1, (
            "an out-of-order sign-off must not advance the step counter"
        )

    def test_make_sheet_consecutive_same_operator_signoff_rejected(self, api):
        """PRD §3.4: "Segregation of duties applies within the procedure: the
        same cheesemaker may not sign two consecutive steps, so a signer whose
        `X-User-ID` matches the previous step's entry in `step_signer_ids` is
        rejected with `ERR_STEP_SOLE_OPERATOR`."

        Design: Corner/state_machines/make_sheet_consecutive_same_operator_signoff_rejected
        """
        ctx = make_completed_batch(complete=False, steps_to_sign=1)
        resp = api.sign_off_step(
            ctx["make"]["id"], 2, make_cheesemaker_headers(CM_ALICE)
        )
        validate_error(resp, ApiErrorId.ERR_STEP_SOLE_OPERATOR, 422)


class TestCompletionGate:
    def test_yield_impossible_over_100pct(self, api):
        """PRD §3.4: "The green weight must be positive — zero or negative
        fails `ERR_INVALID_REQUEST` — and must not exceed `liters_committed`,
        since that would imply a yield above one hundred percent, failing
        `ERR_YIELD_IMPOSSIBLE`; a green weight exactly equal to the committed
        liters passes."

        Design: Corner/validations/yield_impossible_over_100pct
        """
        ctx = make_completed_batch(complete=False)
        resp = api.complete_make_sheet(
            ctx["make"]["id"],
            {"green_weight_kg": 5001.0, "wheels_produced": 4},
            make_cheesemaker_headers(CM_ALICE),
        )
        validate_error(resp, ApiErrorId.ERR_YIELD_IMPOSSIBLE, 422)
        make_now = validate_success(api.get_make_sheet(ctx["make"]["id"], PLANNER))
        assert make_now["status"] == "CURD_READY", (
            "a rejected completion leaves the make CURD_READY"
        )


class TestCompletionCascade:
    def test_make_complete_creates_batch_whey_and_dirties_vat(self, api):
        """PRD §3.4: "Completing the make fans out into a cascade. A cheese
        batch is created in `GREEN` with `current_grade` `UNGRADED` and
        `release_decision` `PENDING`, carrying the make's `variety`, its
        `make_sheet_id`, the recorded `green_weight_kg` and `wheels_produced`,
        both yield figures of §3.5, `wheels_placed` at zero, and `min_age_days`
        pinned by variety: sixty days for `CHEDDAR`, zero for `COLBY`, thirty
        for `BRICK`, twenty-one for `MUENSTER`. A whey stream is created
        alongside it with `total_whey_kg` fixed at that moment. The vat moves
        `IN_MAKE` → `CLEANING` with `cip_clean` set to `false`, closing the vat
        to new bookings until cleaning completes."

        Design: Difficulty/transitive_cascade/make_complete_cascades_to_batch_whey_vat_and_intake
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        make_now = validate_success(api.get_make_sheet(ctx["make"]["id"], PLANNER))
        assert make_now["status"] == "COMPLETED"
        batch = validate_success(api.get_cheese_batch(ctx["batch_id"], CHEESEMAKER))
        assert_cheese_batch(batch)
        assert batch["status"] == "GREEN", f"batch must be born GREEN, got {batch['status']}"
        assert batch["current_grade"] == "UNGRADED"
        assert batch["release_decision"] == "PENDING"
        assert batch["wheels_placed"] == 0
        assert batch["min_age_days"] == 60, (
            f"CHEDDAR pins a 60-day minimum age, got {batch['min_age_days']}"
        )
        whey = ctx["whey"]
        assert whey["total_whey_kg"] == pytest.approx(9020.0), (
            f"whey total must be liters minus green weight, got {whey['total_whey_kg']}"
        )
        vat_now = validate_success(api.get_vat(ctx["vat"]["id"], CHEESEMAKER))
        assert vat_now["status"] == "CLEANING" and vat_now["cip_clean"] is False

    def test_make_complete_consumes_intake_to_terminal(self, api):
        """PRD §3.2: "The moment `consumed_liters` exactly equals
        `volume_liters` after a commit, the intake transitions automatically
        from `ACCEPTED` to terminal `CONSUMED`."
        PRD §3.4: "The intake's `consumed_liters` rises by `liters_committed`
        — milk is committed at start, not at schedule time — and if that brings
        `consumed_liters` exactly to `volume_liters`, the intake becomes
        `CONSUMED`."

        Design: Difficulty/transitive_cascade/make_complete_cascades_to_batch_whey_vat_and_intake
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        intake_now = validate_success(api.get_milk_intake(ctx["intake"]["id"], RECEIVER))
        assert intake_now["status"] == "CONSUMED", (
            f"intake committed to its full volume must be CONSUMED, got {intake_now['status']}"
        )
        assert intake_now["consumed_liters"] == pytest.approx(10000.0)

    def test_immediate_consistency_cascade_visible_in_same_read(self, api):
        """PRD §2.5: "When one request touches several resources — completing
        a make creates a cheese batch and a whey stream, dirties the vat, and
        may consume the milk intake — each touched resource is updated
        independently and atomically with the request."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_read
        """
        ctx = make_completed_batch(
            volume_liters=5000.0, liters_committed=5000.0,
            green_weight_kg=500.0, wheels_produced=4,
        )
        intake_now = validate_success(api.get_milk_intake(ctx["intake"]["id"], RECEIVER))
        assert intake_now["status"] == "CONSUMED", (
            "the intake cascade must be visible in the immediately following read"
        )
        vat_now = validate_success(api.get_vat(ctx["vat"]["id"], CHEESEMAKER))
        assert vat_now["status"] == "CLEANING", (
            "the vat cascade must be visible in the immediately following read"
        )


class TestVatCip:
    def test_vat_cip_returns_to_idle_and_clean(self, api):
        """PRD §3.4: "A `Cheesemaker` later completes CIP on a `CLEANING` vat —
        any other vat state fails with `ERR_INVALID_STATE` — which returns the
        vat to `IDLE` and restores `cip_clean` to `true`."

        Design: Corner/endpoints/vat_cip_returns_to_idle_and_clean
        """
        ctx = make_completed_batch()
        data = validate_success(api.cip_vat(ctx["vat"]["id"], CHEESEMAKER))
        assert data["status"] == "IDLE", f"CIP returns the vat to IDLE, got {data['status']}"
        assert data["cip_clean"] is True, "CIP restores cip_clean to true"
