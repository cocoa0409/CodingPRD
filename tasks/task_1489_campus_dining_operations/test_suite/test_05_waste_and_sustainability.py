"""Waste-log pipeline: state gates, segregation of duties, the verify/reject
cycle, posted-mass conservation, and the sustainability alert threshold."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_posted_waste_log,
    drive_period_to_closed,
    drive_period_to_reconciled,
    get_period,
    get_waste_log,
    make_hall_manager_headers,
    make_kitchen_lead_headers,
    post_waste_log,
    record_waste_log,
    reject_waste_log,
    setup_hall_cycle_recipe,
    validate_error,
    verify_waste_log,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]


def _reconciled_period_with_swipes(api, hall_name, service_date, board_count):
    hall, recipe, cycle = setup_hall_cycle_recipe(hall_name=hall_name)
    period = drive_period_to_reconciled(
        hall["id"], cycle["id"], recipe["id"], service_date,
        events=[("BOARD_SWIPE", 0, board_count)])
    return hall, period


class TestWasteStateGates:
    def test_post_before_verify_rejected(self, api):
        """PRD §3.4: "Posting (`VERIFIED` → `POSTED`) is the monetizable step: it
        requires the parent period to be `RECONCILED`, else `ERR_INVALID_STATE`,
        and it recomputes the period's sustainability aggregates."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/waste_post_before_verify_rejected
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall SM2",
                                                       "2026-08-25", 20)
        log = record_waste_log(period["id"], category="SPOILAGE",
                               disposition="COMPOST", weight_kg=3.0,
                               recorder_id="kl-2")
        resp = api.post_waste_log(log["id"], HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_waste_log(log["id"])["status"] == "RECORDED"
        assert get_period(period["id"])["posted_waste_kg"] == pytest.approx(0.0)

    def test_close_blocked_while_waste_pending(self, api):
        """PRD §3.3: "Closing (`RECONCILED` → `CLOSED`) is performed by a
        `DiningAdmin` and is refused with `ERR_PENDING_WASTE_LOGS` while any
        waste log for the period still sits in `RECORDED` or `VERIFIED` status —
        the waste pipeline of §3.4 must fully settle first."

        Design: Corner/state_machines/period_close_with_pending_waste_blocked
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall SM8",
                                                       "2026-08-27", 5)
        record_waste_log(period["id"], category="PRE_CONSUMER",
                         disposition="LANDFILL", weight_kg=1.0, recorder_id="kl-3")
        resp = api.close_meal_period(period["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PENDING_WASTE_LOGS)
        assert get_period(period["id"])["status"] == "RECONCILED"

    def test_record_after_period_close_window_closed(self, api):
        """PRD §3.4: "Recording is accepted only while the parent period is
        `IN_SERVICE` or `RECONCILED`; once the period is `CLOSED` (or was
        `CANCELLED`), the window has shut and recording is refused with
        `ERR_WASTE_WINDOW_CLOSED`."

        Design: Corner/errors/waste_record_after_period_close_window_closed
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall E3")
        period = drive_period_to_closed(
            hall["id"], cycle["id"], recipe["id"], "2026-09-02",
            events=[("BOARD_SWIPE", 0, 5)])
        resp = api.create_waste_log(
            period["id"],
            {"category": "PRE_CONSUMER", "disposition": "LANDFILL",
             "weight_kg": 1.0},
            make_kitchen_lead_headers("kl-4"))
        validate_error(resp, ApiErrorId.ERR_WASTE_WINDOW_CLOSED)


class TestSegregationOfDuties:
    def test_recorder_cannot_verify_own_log(self, api):
        """PRD §3.4: "Verification (`RECORDED` → `VERIFIED`) is a `HallManager`
        duty with a hard segregation-of-duties rule: the verifier's `X-User-ID`
        must differ from the log's `recorded_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` — even though `HallManager` is otherwise the
        correct role."

        Design: Corner/errors/waste_self_verify_segregation_of_duties
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall E2",
                                                       "2026-09-01", 5)
        log = record_waste_log(period["id"], category="SPOILAGE",
                               disposition="LANDFILL", weight_kg=2.0,
                               recorder_id="dual-1")
        assert log["recorded_by_user_id"] == "dual-1"
        resp = api.verify_waste_log(log["id"],
                                    make_hall_manager_headers("dual-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_waste_log(log["id"])
        assert after["status"] == "RECORDED"
        assert after["verified_by_user_id"] is None


class TestVerifyRejectCycle:
    def test_verify_reject_cycle_statuses(self, api):
        """PRD §3.4: "A failed verification cycles the log back (`VERIFIED` →
        `RECORDED`) via rejection, clearing `verified_by_user_id` to null and
        accepting an optional `reason`; because only `POSTED` rows feed the
        period aggregates and rejection never changes the posted set, rejection
        deliberately performs no recomputation."

        Design: Difficulty/non_linear_state_machine/waste_log_verify_reject_cycle
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall W",
                                                       "2026-08-10", 1)
        log = record_waste_log(period["id"], category="PRE_CONSUMER",
                               disposition="LANDFILL", weight_kg=10.0,
                               recorder_id="kl-1")
        statuses = [log["status"]]
        verified = verify_waste_log(log["id"], verifier_id="hm-1")
        statuses.append(verified["status"])
        rejected = reject_waste_log(log["id"])
        statuses.append(rejected["status"])
        re_verified = verify_waste_log(log["id"], verifier_id="hm-1")
        statuses.append(re_verified["status"])
        posted = post_waste_log(log["id"])
        statuses.append(posted["status"])
        assert statuses == ["RECORDED", "VERIFIED", "RECORDED", "VERIFIED",
                            "POSTED"], (
            "the reject edge reopens the log; the cycle is legal, not a "
            "terminal lockdown")

    def test_reject_clears_verifier_and_post_hits_aggregates_once(self, api):
        """PRD §3.4: "A failed verification cycles the log back (`VERIFIED` →
        `RECORDED`) via rejection, clearing `verified_by_user_id` to null and
        accepting an optional `reason`; because only `POSTED` rows feed the
        period aggregates and rejection never changes the posted set, rejection
        deliberately performs no recomputation."

        Design: Difficulty/non_linear_state_machine/waste_log_verify_reject_cycle
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall W",
                                                       "2026-08-10", 1)
        log = record_waste_log(period["id"], category="PRE_CONSUMER",
                               disposition="LANDFILL", weight_kg=10.0,
                               recorder_id="kl-1")
        verify_waste_log(log["id"], verifier_id="hm-1")
        rejected = reject_waste_log(log["id"])
        assert rejected["verified_by_user_id"] is None
        verify_waste_log(log["id"], verifier_id="hm-1")
        post_waste_log(log["id"])
        period_after = get_period(period["id"])
        assert period_after["posted_waste_kg"] == pytest.approx(10.0), (
            "the verify/reject cycle never touched the POSTED set; the single "
            "post moves exactly 10.0 kg")


class TestSustainabilityAlertThreshold:
    def _setup(self, api):
        """RECONCILED period with 100 covers and one POSTED 15.0 kg LANDFILL log
        plus a second VERIFIED 0.02 kg LANDFILL log."""
        _hall, period = _reconciled_period_with_swipes(api, "Hall SA",
                                                       "2026-08-12", 100)
        create_posted_waste_log(period["id"], category="POST_CONSUMER",
                                disposition="LANDFILL", weight_kg=15.0,
                                recorder_id="kl-1", verifier_id="hm-1")
        w2 = record_waste_log(period["id"], category="POST_CONSUMER",
                              disposition="LANDFILL", weight_kg=0.02,
                              recorder_id="kl-1")
        verify_waste_log(w2["id"], verifier_id="hm-1")
        return period, w2

    def test_exactly_at_threshold_does_not_alert(self, api):
        """PRD §3.4: "The `sustainability_alert` flag is then re-evaluated
        against the 0.15 kilograms-per-cover threshold: it is set true when
        `actual_covers` is greater than 0 and the landfill kilograms per actual
        cover is strictly greater than 0.15 — a ratio of exactly 0.15 does not
        raise the alert — and it is false whenever `actual_covers` is 0."

        Design: Difficulty/transitive_cascade/waste_post_threshold_alert_cascade
        """
        period, _w2 = self._setup(api)
        after = get_period(period["id"])
        assert after["posted_waste_kg"] == pytest.approx(15.0)
        assert after["sustainability_alert"] is False, (
            "15.0/100 == 0.15 exactly; the strictly-greater threshold is not "
            "crossed")

    def test_one_cent_above_threshold_flips_alert(self, api):
        """PRD §3.4: "The `sustainability_alert` flag is then re-evaluated
        against the 0.15 kilograms-per-cover threshold: it is set true when
        `actual_covers` is greater than 0 and the landfill kilograms per actual
        cover is strictly greater than 0.15 — a ratio of exactly 0.15 does not
        raise the alert — and it is false whenever `actual_covers` is 0."

        Design: Difficulty/transitive_cascade/waste_post_threshold_alert_cascade
        """
        period, w2 = self._setup(api)
        post_waste_log(w2["id"])
        after = get_period(period["id"])
        assert after["posted_waste_kg"] == pytest.approx(15.02)
        assert after["landfill_waste_kg"] == pytest.approx(15.02)
        assert after["sustainability_alert"] is True, (
            "15.02/100 = 0.1502 > 0.15 — the aggregate recompute flips the flag")
        assert after["diversion_rate"] == pytest.approx(0.0), (
            "all posted mass is LANDFILL")


class TestPostedMassConservation:
    def test_verify_reject_cycle_leaves_posted_mass_at_zero(self, api):
        """PRD §3.4: "A failed verification cycles the log back (`VERIFIED` →
        `RECORDED`) via rejection, clearing `verified_by_user_id` to null and
        accepting an optional `reason`; because only `POSTED` rows feed the
        period aggregates and rejection never changes the posted set, rejection
        deliberately performs no recomputation."

        Design: Difficulty/compensating_invariant/waste_posted_mass_conservation
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall INV3",
                                                       "2026-08-18", 10)
        log = record_waste_log(period["id"], category="PRE_CONSUMER",
                               disposition="COMPOST", weight_kg=10.0,
                               recorder_id="kl-9")
        verify_waste_log(log["id"], verifier_id="hm-9")
        reject_waste_log(log["id"])
        mid = get_period(period["id"])
        assert mid["posted_waste_kg"] == pytest.approx(0.0), (
            "intermediate verifications add nothing to the POSTED set")

    def test_single_post_counts_mass_exactly_once(self, api):
        """PRD §3.4: "The period's `posted_waste_kg` becomes the sum of
        `weight_kg` over all its `POSTED` logs, and `landfill_waste_kg` the same
        sum restricted to logs whose disposition is `LANDFILL`; both are carried
        at 2 decimal places. The `diversion_rate` is the composted-plus-donated
        kilograms divided by the total posted kilograms, carried to 4 decimal
        places, and is null when no waste is posted at all."

        Design: Difficulty/compensating_invariant/waste_posted_mass_conservation
        """
        _hall, period = _reconciled_period_with_swipes(api, "Hall INV3",
                                                       "2026-08-18", 10)
        log = record_waste_log(period["id"], category="PRE_CONSUMER",
                               disposition="COMPOST", weight_kg=10.0,
                               recorder_id="kl-9")
        verify_waste_log(log["id"], verifier_id="hm-9")
        reject_waste_log(log["id"])
        verify_waste_log(log["id"], verifier_id="hm-9")
        post_waste_log(log["id"])
        after = get_period(period["id"])
        assert after["posted_waste_kg"] == pytest.approx(10.0), (
            "single counting, no duplication from the cycle")
        assert after["diversion_rate"] == pytest.approx(1.0), (
            "all 10.0 kg COMPOST")
        assert after["sustainability_alert"] is False, (
            "landfill 0/10 = 0 <= 0.15")
