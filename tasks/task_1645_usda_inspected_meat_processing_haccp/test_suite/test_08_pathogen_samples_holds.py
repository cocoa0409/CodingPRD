"""Pathogen sampling, positive-result hold cascade, hold release workflow."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_finished_lot_payload,
    pathogen_sample_payload,
    release_hold_payload,
    report_result_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures

QA = TEST_USERS["qa_manager_headers"]
PROD = TEST_USERS["production_manager_headers"]


class TestPositiveResultHoldCascade:
    def test_positive_result_holds_lot_quarantines_finished_lot_restricts_day(self, api):
        """PRD §2.8: "Link 1: a lab result of `POSITIVE` moves the sampled carcass lot to `HELD` — or directly to `CONDEMNED` when the lot was already `HELD` and the positive sample is a confirmation retest."
        PRD §2.8: "Link 2: the lot's transition to `HELD` or `CONDEMNED` moves every finished lot sourced from it and still in `PRODUCED` status to `QUARANTINED`."
        PRD §2.8: "Link 3: each such quarantine recomputes the owning production day's posture to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/positive_pathogen_result_hold_quarantine_cascade
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-G", units_produced=50,
        )
        sample = fixtures.collect_sample(lot["id"])
        assert sample["result"] == "PENDING"

        reported = fixtures.report_sample(sample["id"], "POSITIVE")
        assert reported["result"] == "POSITIVE"
        assert reported.get("reported_at"), "report stamps reported_at"

        lot_after = validate_success(api.get_lot(lot["id"], QA), 200)
        assert lot_after["status"] == "HELD", "cascade link 1: lot -> HELD"

        fl_after = validate_success(api.get_finished_lot(fl["id"], QA), 200)
        assert fl_after["status"] == "QUARANTINED", (
            "cascade link 2: PRODUCED finished lot -> QUARANTINED"
        )

        day_after = validate_success(
            api.get_production_day(env["day"]["id"], QA), 200
        )
        assert day_after["posture"] == "RESTRICTED", (
            "cascade link 3: day posture recomputed to RESTRICTED"
        )

    def test_shipped_finished_lot_is_not_quarantined(self, api):
        """PRD §2.8: "Link 2: the lot's transition to `HELD` or `CONDEMNED` moves every finished lot sourced from it and still in `PRODUCED` status to `QUARANTINED`."

        Design: Difficulty/transitive_cascade/positive_pathogen_result_hold_quarantine_cascade
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-G2"
        )
        label = fixtures.create_approved_label(env["plant"]["id"])
        fl_shipped = fixtures.pack_finished_lot(
            env["day"]["id"], lot["id"], label["id"], units_produced=10,
        )
        fl_kept = fixtures.pack_finished_lot(
            env["day"]["id"], lot["id"], label["id"], units_produced=10,
        )
        fixtures.get_success_data(api.ship_finished_lot(fl_shipped["id"], PROD))

        sample = fixtures.collect_sample(lot["id"])
        fixtures.report_sample(sample["id"], "POSITIVE")

        shipped_after = validate_success(
            api.get_finished_lot(fl_shipped["id"], QA), 200
        )
        assert shipped_after["status"] == "SHIPPED", (
            "only lots still in PRODUCED quarantine; SHIPPED lots are untouched"
        )
        kept_after = validate_success(api.get_finished_lot(fl_kept["id"], QA), 200)
        assert kept_after["status"] == "QUARANTINED"

        lot_after = validate_success(api.get_lot(lot["id"], QA), 200)
        assert lot_after["status"] == "HELD"
        day_after = validate_success(
            api.get_production_day(env["day"]["id"], QA), 200
        )
        assert day_after["posture"] == "RESTRICTED"


class TestSampleReporting:
    def test_sample_report_twice_returns_already_reported(self, api):
        """PRD §3.6: "A `LabAnalyst` reports the outcome by supplying the `result` as `NEGATIVE` or `POSITIVE`; only a still-`PENDING` sample may be reported, otherwise `ERR_SAMPLE_ALREADY_REPORTED`."
        PRD §3.6: "The new sample records the collector as `collected_by`, starts with `result` `PENDING`, and computes `is_confirmation`: true when an earlier-created `POSITIVE` sample already exists for the same lot."

        Design: Corner/state_machines/sample_report_twice_returns_already_reported
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-03")
        lot = fixtures.receive_lot(env["day"]["id"])
        resp = api.pass_ante_mortem(
            lot["id"], fixtures.make_inspector_headers(fixtures.INSPECTOR_1)
        )
        validate_success(resp, 200)
        validate_success(
            api.harvest_lot(lot["id"], {"hot_carcass_weight_lbs": 1030.0}, PROD), 200
        )

        sample = fixtures.collect_sample(
            lot["id"], organism="GENERIC_ECOLI", sample_type="CARCASS_SWAB"
        )
        assert sample["result"] == "PENDING", "newly collected sample is PENDING"

        first = fixtures.report_sample(sample["id"], "NEGATIVE")
        assert first["result"] == "NEGATIVE"

        again = api.report_sample_result(
            sample["id"], report_result_payload(result="POSITIVE"),
            fixtures.make_lab_analyst_headers(fixtures.LAB_ANALYST_1),
        )
        validate_error(again, ApiErrorId.ERR_SAMPLE_ALREADY_REPORTED)
        assert again.status_code == 409

        after = validate_success(api.get_pathogen_sample(sample["id"], QA), 200)
        assert after["result"] == "NEGATIVE"


class TestHoldReleaseCycle:
    def test_hold_release_cycle_with_confirmation_retest(self, api):
        """PRD §3.6: "The new sample records the collector as `collected_by`, starts with `result` `PENDING`, and computes `is_confirmation`: true when an earlier-created `POSITIVE` sample already exists for the same lot."
        PRD §3.6: "A successful release moves the lot to `RELEASED` — from which fabrication may begin or resume — and recomputes the day's posture."

        Design: Corner/state_machines/lot_hold_release_cycle_with_confirmation_retest
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-13"
        )
        s1 = fixtures.collect_sample(lot["id"])
        assert s1["is_confirmation"] is False, "no earlier POSITIVE exists yet"
        fixtures.report_sample(s1["id"], "POSITIVE")

        held = validate_success(api.get_lot(lot["id"], QA), 200)
        assert held["status"] == "HELD"

        # The confirmation retest is collected while the lot is HELD.
        s2 = fixtures.collect_sample(lot["id"])
        assert s2["is_confirmation"] is True, (
            "an earlier-created POSITIVE sample marks the retest"
        )
        fixtures.report_sample(s2["id"], "NEGATIVE")

        released = validate_success(
            api.release_hold(
                lot["id"],
                release_hold_payload(
                    disposition_note="Confirmation retest negative; lot released "
                                     "for fabrication"
                ),
                QA,
            ),
            200,
        )
        assert released["status"] == "RELEASED"

        refab = validate_success(api.fabricate_lot(lot["id"], PROD), 200)
        assert refab["status"] == "FABRICATING", (
            "fabrication may resume from RELEASED — the cycle is closed"
        )

    def test_release_hold_without_retest_returns_positive_unresolved(self, api):
        """PRD §3.6: "The lot must be `HELD` (`ERR_LOT_INVALID_STATE`), and the release requires proof the positive was resolved: a `NEGATIVE` sample of the lot whose `created_at` is later than the latest `POSITIVE` sample's `created_at` must exist, otherwise the release is rejected with `ERR_POSITIVE_PATHOGEN_UNRESOLVED`."

        Design: Corner/state_machines/release_hold_without_retest_returns_positive_unresolved
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-14")
        lot = fixtures.receive_lot(env["day"]["id"])
        fixtures.walk_lot_to_chilled(lot["id"])
        s1 = fixtures.collect_sample(
            lot["id"], organism="ECOLI_O157H7", sample_type="CARCASS_SWAB"
        )
        fixtures.report_sample(s1["id"], "POSITIVE")

        held = validate_success(api.get_lot(lot["id"], QA), 200)
        assert held["status"] == "HELD"

        resp = api.release_hold(
            lot["id"], release_hold_payload(disposition_note="Premature release "
                                            "attempt"), QA,
        )
        validate_error(resp, ApiErrorId.ERR_POSITIVE_PATHOGEN_UNRESOLVED)
        assert resp.status_code == 422

        after = validate_success(api.get_lot(lot["id"], QA), 200)
        assert after["status"] == "HELD"


class TestFinishedLotCreatePathogenGate:
    def test_create_with_pending_sample_returns_positive_unresolved(self, api):
        """PRD §3.8: "The gates run in a fixed order: the state family comes first — the owning day must be `OPEN` (`ERR_DAY_NOT_OPEN`) — followed by the business checks: the label must be `APPROVED` (`ERR_LABEL_INVALID_STATE`); no pathogen sample of the source lot may be `PENDING` or `POSITIVE` (`ERR_POSITIVE_PATHOGEN_UNRESOLVED`); the label must be the latest-approved application for its plant and `product_name`, meaning no other `APPROVED` label for the same product name exists whose approval executed later (`ERR_LABEL_VERSION_STALE`); and the cooler gate of §3.1 must admit the new weight (`ERR_COOLER_CAPACITY_EXCEEDED`)."

        Design: Corner/endpoints/finished_lot_create_with_pending_sample_returns_positive_unresolved
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-39"
        )
        label = fixtures.create_approved_label(env["plant"]["id"])
        sample = fixtures.collect_sample(
            lot["id"], organism="ECOLI_O157H7", sample_type="GROUND_PRODUCT"
        )
        assert sample["result"] == "PENDING"

        payload = create_finished_lot_payload(
            source_lot_id=lot["id"], label_approval_id=label["id"],
            units_produced=10, unit_weight_lbs=5.0, shelf_life_days=10,
        )
        blocked = api.create_finished_lot(env["day"]["id"], payload, PROD)
        validate_error(blocked, ApiErrorId.ERR_POSITIVE_PATHOGEN_UNRESOLVED)
        assert blocked.status_code == 422

        fixtures.report_sample(sample["id"], "NEGATIVE")
        created = validate_success(
            api.create_finished_lot(env["day"]["id"], payload, PROD), 201
        )
        assert created["status"] == "PRODUCED", (
            "once the sample reports NEGATIVE the conditional gate clears"
        )
