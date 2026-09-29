"""Condition reports, the weighted grade, refurbishment QA and catalogue publication."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_condition_report,
    assert_refurbishment_order,
    catalog_ready_batch,
    catalog_ready_lot,
    create_condition_report_payload,
    create_refurbishment_order_payload,
    intake_decision_payload,
    lot_assignment_payload,
    make_consignor_headers,
    new_auction,
    new_consignment,
    new_consignor,
    new_lot,
    new_yard,
    refurbishment_transition_payload,
    rescore_condition_report_payload,
    reset_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import INSPECTOR, OPERATOR, SECOND_INSPECTOR


def _accepted_consignment_with_lot(hour_meter_reading: int = 6_200):
    """Walk consignor -> consignment -> lot -> submit -> accept, ready for a report."""
    reset_clock()
    consignor = new_consignor()
    consignor_headers = make_consignor_headers(consignor["id"])
    consignment = new_consignment(consignor)
    lot = new_lot(
        consignment,
        consignor,
        serial_number="CAT-D8T-0001",
        hour_meter_reading=hour_meter_reading,
    )
    validate_success(api_client.submit_consignment(consignment["id"], consignor_headers))
    validate_success(
        api_client.decide_consignment_intake(
            consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
        )
    )
    return consignor, consignment, lot


class TestWeightedGradeRounding:
    def test_each_weighted_component_is_rounded_before_the_four_are_added(self):
        """83.5/77.5/64.5/58.5 grades as 74.16, the per-component total, and not as 74.15,
        the figure a single rounding of the summed products would produce.

        PRD 2.6: "The same holds for the four weighted components of a condition grade,
        which are each rounded before they are added."
        PRD 3.2: "Multiply `structural_score` by 0.35 and round the product half up to two
        decimals; multiply `powertrain_score` by 0.30 and round half up to two decimals;
        multiply `hydraulics_score` by 0.20 and round half up to two decimals; multiply
        `tires_score` by 0.15 and round half up to two decimals."
        PRD 3.2: "Summing the unrounded products and rounding once at the end gives a
        different number and is not the specified behaviour."
        PRD 3.2: "A `grade_score` of at least 85 bands as `A`; failing that, at least 70
        bands as `B`".

        Design: Difficulty/combinatorial_formula/condition_grade_rounds_per_component_before_summing
        """
        _, _, lot = _accepted_consignment_with_lot(hour_meter_reading=6_200)

        report = validate_success(
            api_client.create_condition_report(
                lot["id"],
                create_condition_report_payload(
                    structural_score=83.5,
                    powertrain_score=77.5,
                    hydraulics_score=64.5,
                    tires_score=58.5,
                    observed_hour_meter_reading=6_386,
                    hour_meter_verified=True,
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )

        assert_condition_report(report)
        assert report["grade_score"] == pytest.approx(74.16, abs=0.001)
        assert report["grade_score"] != pytest.approx(74.15, abs=0.001)
        assert report["grade_band"] == "B"
        assert report["hour_meter_variance_pct"] == pytest.approx(0.0300, abs=0.00001)
        assert report["status"] == "DRAFT"

        stored_lot = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert stored_lot["lifecycle_status"] == "INSPECTED"
        assert stored_lot["title_status"] == "TITLE_PENDING"

    def test_a_rescore_reruns_the_same_per_component_rounding(self):
        """Correcting the draft to 96.5/82.5/78.5/54.5 restamps 82.41, again the total of
        four separately rounded components rather than 82.40.

        PRD 3.2: "An `IntakeInspector` may resubmit any of `structural_score`,
        `powertrain_score`, `hydraulics_score`, `tires_score` or `hour_meter_verified` on a
        report whose `status` is still `DRAFT`; the whole grade calculation is re-run and
        `grade_score` and `grade_band` are restamped from the revised inputs, and the
        report's `version` increments by 1."
        PRD 3.2: "Add those four already-rounded components together; the sum needs no
        further rounding because each term already carries two decimals."

        Design: Difficulty/combinatorial_formula/condition_grade_rounds_per_component_before_summing
        """
        _, _, lot = _accepted_consignment_with_lot(hour_meter_reading=6_200)
        report = validate_success(
            api_client.create_condition_report(
                lot["id"],
                create_condition_report_payload(
                    structural_score=83.5,
                    powertrain_score=77.5,
                    hydraulics_score=64.5,
                    tires_score=58.5,
                    observed_hour_meter_reading=6_386,
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert report["version"] == 1

        rescored = validate_success(
            api_client.rescore_condition_report(
                report["id"],
                rescore_condition_report_payload(
                    structural_score=96.5,
                    powertrain_score=82.5,
                    hydraulics_score=78.5,
                    tires_score=54.5,
                ),
                INSPECTOR,
            )
        )

        assert rescored["grade_score"] == pytest.approx(82.41, abs=0.001)
        assert rescored["grade_score"] != pytest.approx(82.40, abs=0.001)
        assert rescored["grade_band"] == "B"
        assert rescored["version"] == 2
        assert rescored["status"] == "DRAFT"
        assert rescored["hour_meter_variance_pct"] == pytest.approx(0.0300, abs=0.00001)


class TestUnverifiedHourMeter:
    def test_an_unverified_meter_costs_fifteen_points_and_caps_the_published_band(self):
        """Four scores of 95.0 grade as 95.00 before the penalty, 80.00 after it, and the
        band that would read B is published as C.

        PRD 3.2: "If `hour_meter_verified` is false, subtract a flat penalty of 15 points
        from that sum and take the larger of the result and 0.00; if `hour_meter_verified`
        is true, the sum stands as computed."
        PRD 3.2: "One override sits on top: when `hour_meter_verified` is false, a band that
        would otherwise have come out `A` or `B` is published as `C` instead."
        PRD 3.2: "take the absolute difference between `observed_hour_meter_reading` and the
        lot's declared `hour_meter_reading`, divide it by the larger of the lot's declared
        `hour_meter_reading` and 1, and round the quotient half up to four decimal places."

        Design: Corner/validations/unverified_hour_meter_blocks_assignment_until_the_disclaimer_is_accepted
        """
        stage = catalog_ready_lot(
            lot_overrides={"serial_number": "CAT-D8T-0001", "hour_meter_reading": 6_200},
            report_overrides={
                "structural_score": 95.0,
                "powertrain_score": 95.0,
                "hydraulics_score": 95.0,
                "tires_score": 95.0,
                "observed_hour_meter_reading": 4_100,
                "hour_meter_verified": False,
            },
        )

        report = stage["report"]
        assert_condition_report(report)
        assert report["hour_meter_verified"] is False
        assert report["grade_score"] == pytest.approx(80.00, abs=0.001)
        assert report["grade_band"] == "C"
        assert report["hour_meter_variance_pct"] == pytest.approx(0.3387, abs=0.00001)

    def test_only_the_lot_carrying_the_disclaimer_reaches_the_catalogue(self):
        """Two equally unverified machines part ways at assignment: the bare lot is refused
        and the one whose seller accepted the hours-not-warranted disclaimer is assigned.

        PRD 3.4: "Either the report's `hour_meter_verified` must be true or the lot's
        `sold_as_hours_unverified` must be true, failing which the refusal is
        `ERR_HOUR_METER_UNVERIFIED` — an unverifiable meter reaches the catalogue only
        behind the seller's hours-not-warranted disclaimer."
        PRD 3.1: "While a lot is still in `INTAKE` or `INSPECTED`, its consignor may revise
        the catalogue-relevant data by supplying any of `reserve_price_cents`,
        `sold_as_hours_unverified` or `weight_kg`; the edit bumps the lot's `version`."

        Design: Corner/validations/unverified_hour_meter_blocks_assignment_until_the_disclaimer_is_accepted
        """
        stage = catalog_ready_batch(
            [
                {"serial_number": "CAT-D8T-0001"},
                {"serial_number": "CAT-D8T-0002"},
            ],
            report_overrides={
                "structural_score": 95.0,
                "powertrain_score": 95.0,
                "hydraulics_score": 95.0,
                "tires_score": 95.0,
                "observed_hour_meter_reading": 4_100,
                "hour_meter_verified": False,
            },
            publish_count=0,
        )
        bare_lot, disclaimed_lot = stage["lots"]
        consignor_headers = stage["consignor_headers"]

        patched = validate_success(
            api_client.update_lot(
                disclaimed_lot["id"], {"sold_as_hours_unverified": True}, consignor_headers
            )
        )
        assert patched["sold_as_hours_unverified"] is True
        assert patched["version"] == disclaimed_lot["version"] + 1

        for report in stage["reports"]:
            validate_success(api_client.publish_condition_report(report["id"], INSPECTOR))
        auction = new_auction(stage["yard"])

        refused = api_client.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(bare_lot["id"]), OPERATOR
        )
        validate_error(
            refused, ApiErrorId.ERR_HOUR_METER_UNVERIFIED, expected_status=422
        )

        validate_success(
            api_client.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(disclaimed_lot["id"]), OPERATOR
            ),
            expected_status=201,
        )

        held = validate_success(api_client.get_lot(bare_lot["id"], OPERATOR))
        assert held["lifecycle_status"] == "CATALOG_READY"
        assert held["auction_id"] is None
        catalogued = validate_success(api_client.get_lot(disclaimed_lot["id"], OPERATOR))
        assert catalogued["lifecycle_status"] == "ASSIGNED"
        assert catalogued["auction_id"] == auction["id"]


class TestRefurbishmentQaCycle:
    def test_a_rework_decision_and_a_restart_close_the_loop_and_count_the_lap(self):
        """QA_REWORK then START walks QA_REVIEW to REWORK to IN_PROGRESS, keeps the recorded
        actual cost, and leaves the lot itself where inspection put it.

        PRD 3.2: "`QA_REWORK` moves it `QA_REVIEW → REWORK`, requires a `qa_note` in the
        request, records that note, and increments `rework_round` by 1".
        PRD 3.2: "From `REWORK`, another `START` returns the order to `IN_PROGRESS`, closing
        the `QA_REVIEW → REWORK → IN_PROGRESS → QA_REVIEW` loop for at most two laps."
        PRD 3.2: "`SUBMIT_QA` moves it `IN_PROGRESS → QA_REVIEW` and requires
        `actual_cost_cents` in the request, which overwrites the field on the order and
        becomes the basis of the seller recharge at settlement."

        Design: Corner/state_machines/refurbishment_rework_lap_returns_the_order_to_in_progress
        """
        stage = catalog_ready_batch(
            [{"serial_number": "CAT-D8T-0001"}], publish_count=0
        )
        lot = stage["lots"][0]

        order = validate_success(
            api_client.create_refurbishment_order(
                create_refurbishment_order_payload(lot["id"]), INSPECTOR
            ),
            expected_status=201,
        )
        assert_refurbishment_order(order)
        assert order["status"] == "DRAFT"
        assert order["rework_round"] == 0

        validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("START"), INSPECTOR
            )
        )
        validate_success(
            api_client.transition_refurbishment_order(
                order["id"],
                refurbishment_transition_payload("SUBMIT_QA", actual_cost_cents=420_000),
                INSPECTOR,
            )
        )

        reworked = validate_success(
            api_client.transition_refurbishment_order(
                order["id"],
                refurbishment_transition_payload(
                    "QA_REWORK", qa_note="seal weeping under load test"
                ),
                SECOND_INSPECTOR,
            )
        )
        assert reworked["status"] == "REWORK"
        assert reworked["rework_round"] == 1
        assert reworked["actual_cost_cents"] == 420_000

        restarted = validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("START"), INSPECTOR
            )
        )
        assert restarted["status"] == "IN_PROGRESS"
        assert restarted["rework_round"] == 1
        assert restarted["actual_cost_cents"] == 420_000

        stored_lot = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert stored_lot["lifecycle_status"] == "INSPECTED"

    def test_a_third_rework_decision_is_refused_at_the_declared_lap_limit(self):
        """Two laps are allowed; the third QA_REWORK is refused and changes nothing.

        PRD 3.2: "it is only available while `rework_round` is still below 2, so a third
        rework decision is refused with `ERR_MAX_REWORK_ROUNDS_EXCEEDED` rather than being
        silently capped."

        Design: Corner/state_machines/third_refurbishment_rework_lap_is_rejected_at_max_rework_rounds
        """
        stage = catalog_ready_batch(
            [{"serial_number": "CAT-D8T-0001"}], publish_count=0
        )
        lot = stage["lots"][0]
        order = validate_success(
            api_client.create_refurbishment_order(
                create_refurbishment_order_payload(lot["id"]), INSPECTOR
            ),
            expected_status=201,
        )

        def transition(action, **payload):
            return validate_success(
                api_client.transition_refurbishment_order(
                    order["id"], refurbishment_transition_payload(action, **payload), INSPECTOR
                )
            )

        transition("START")
        transition("SUBMIT_QA", actual_cost_cents=420_000)
        first_lap = transition("QA_REWORK", qa_note="lap one")
        assert first_lap["rework_round"] == 1
        transition("START")
        transition("SUBMIT_QA", actual_cost_cents=480_000)
        second_lap = transition("QA_REWORK", qa_note="lap two")
        assert second_lap["rework_round"] == 2
        transition("START")
        awaiting_qa = transition("SUBMIT_QA", actual_cost_cents=480_000)
        assert awaiting_qa["status"] == "QA_REVIEW"

        response = api_client.transition_refurbishment_order(
            order["id"],
            refurbishment_transition_payload("QA_REWORK", qa_note="lap three"),
            INSPECTOR,
        )

        validate_error(
            response, ApiErrorId.ERR_MAX_REWORK_ROUNDS_EXCEEDED, expected_status=422
        )

        stored = validate_success(api_client.get_refurbishment_order(order["id"], INSPECTOR))
        assert stored["status"] == "QA_REVIEW"
        assert stored["rework_round"] == 2
        assert stored["actual_cost_cents"] == 480_000

    def test_the_inspector_who_wrote_the_report_cannot_sign_off_the_work(self):
        """The author's QA_PASS is refused on separation of duties while a second inspector's
        identical call completes the order.

        PRD 3.2: "`QA_PASS` moves it `QA_REVIEW → COMPLETED`, which is terminal; it requires
        that `actual_cost_cents` is not null and that the acting `X-User-ID` differs from the
        `inspector_user_id` recorded on the lot's condition report, and it stamps
        `qa_signed_off_by_user_id` with the acting `X-User-ID`."
        PRD 3.2: "Passing QA on work whose inspection you authored yourself is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/RBAC/the_reporting_inspector_cannot_qa_pass_their_own_refurbishment
        """
        stage = catalog_ready_batch(
            [{"serial_number": "CAT-D8T-0001"}], publish_count=0
        )
        lot = stage["lots"][0]
        report = stage["reports"][0]
        assert report["inspector_user_id"] == "inspector-1"

        order = validate_success(
            api_client.create_refurbishment_order(
                create_refurbishment_order_payload(lot["id"]), INSPECTOR
            ),
            expected_status=201,
        )
        validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("START"), INSPECTOR
            )
        )
        validate_success(
            api_client.transition_refurbishment_order(
                order["id"],
                refurbishment_transition_payload("SUBMIT_QA", actual_cost_cents=300_000),
                INSPECTOR,
            )
        )

        refused = api_client.transition_refurbishment_order(
            order["id"], refurbishment_transition_payload("QA_PASS"), INSPECTOR
        )
        validate_error(
            refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403
        )
        held = validate_success(api_client.get_refurbishment_order(order["id"], INSPECTOR))
        assert held["status"] == "QA_REVIEW"

        completed = validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("QA_PASS"), SECOND_INSPECTOR
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["rework_round"] == 0
        assert completed["qa_signed_off_by_user_id"] == "inspector-2"


class TestCataloguePublication:
    def test_publication_waits_for_every_refurbishment_order_to_complete(self):
        """An order still in DRAFT blocks the publish; completing it lets the identical call
        through and moves both the report and the lot.

        PRD 3.2: "It requires the lot to be in `INSPECTED`, the report to still be in
        `DRAFT`, the parent consignment to be in `INTAKE_ACCEPTED`, and every refurbishment
        order of the lot to have reached `COMPLETED` — a condition that is vacuously
        satisfied when the lot has no orders at all, and that is otherwise refused with
        `ERR_REFURBISHMENT_INCOMPLETE`."
        PRD 3.2: "Publishing a report moves its own `status` `DRAFT → PUBLISHED` and moves
        the lot `INSPECTED → CATALOG_READY`."

        Design: Corner/state_machines/publishing_a_report_with_an_open_refurbishment_order_is_rejected
        """
        stage = catalog_ready_batch(
            [{"serial_number": "CAT-D8T-0001"}], publish_count=0
        )
        lot = stage["lots"][0]
        report = stage["reports"][0]
        order = validate_success(
            api_client.create_refurbishment_order(
                create_refurbishment_order_payload(lot["id"]), INSPECTOR
            ),
            expected_status=201,
        )
        assert order["status"] == "DRAFT"

        blocked = api_client.publish_condition_report(report["id"], INSPECTOR)
        validate_error(
            blocked, ApiErrorId.ERR_REFURBISHMENT_INCOMPLETE, expected_status=409
        )
        assert (
            validate_success(api_client.get_condition_report(report["id"], OPERATOR))["status"]
            == "DRAFT"
        )
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["lifecycle_status"]
            == "INSPECTED"
        )

        validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("START"), INSPECTOR
            )
        )
        validate_success(
            api_client.transition_refurbishment_order(
                order["id"],
                refurbishment_transition_payload("SUBMIT_QA", actual_cost_cents=150_000),
                INSPECTOR,
            )
        )
        completed = validate_success(
            api_client.transition_refurbishment_order(
                order["id"], refurbishment_transition_payload("QA_PASS"), SECOND_INSPECTOR
            )
        )
        assert completed["status"] == "COMPLETED"

        published = validate_success(
            api_client.publish_condition_report(report["id"], INSPECTOR)
        )
        assert published["status"] == "PUBLISHED"
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["lifecycle_status"]
            == "CATALOG_READY"
        )

    def test_republishing_a_published_report_does_not_re_fire_the_side_effect(self):
        """The second publish is an invalid state and leaves the lot's version untouched.

        PRD 3.2: "It requires the lot to be in `INSPECTED`, the report to still be in
        `DRAFT`, the parent consignment to be in `INTAKE_ACCEPTED`, and every refurbishment
        order of the lot to have reached `COMPLETED`".
        PRD 2.8: "The target is in a state from which the requested transition is declared
        — otherwise `ERR_INVALID_STATE` (409). This is the generic guard; every
        terminal-state lockdown and every replayed one-shot action lands here."
        PRD 3.2: "The lot's `version` and the report's `version` each increment by 1."

        Design: Corner/state_machines/second_publish_of_the_same_report_returns_409_invalid_state
        """
        stage = catalog_ready_lot(lot_overrides={"serial_number": "CAT-D8T-0001"})
        lot = stage["lot"]
        report = stage["report"]
        assert report["status"] == "PUBLISHED"
        assert lot["lifecycle_status"] == "CATALOG_READY"

        response = api_client.publish_condition_report(report["id"], INSPECTOR)

        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        stored_report = validate_success(
            api_client.get_condition_report(report["id"], OPERATOR)
        )
        assert stored_report["status"] == "PUBLISHED"
        stored_lot = validate_success(api_client.get_lot(lot["id"], OPERATOR))
        assert stored_lot["lifecycle_status"] == "CATALOG_READY"
        assert stored_lot["version"] == lot["version"]

    def test_the_batch_only_catalogues_once_its_last_lot_is_published(self):
        """With two machines on one accepted batch, the first publish leaves the consignment
        where it was and the second flips it.

        PRD 3.2: "When the published lot was the last one needed — that is, when every
        non-`WITHDRAWN` lot of the consignment is now `CATALOG_READY`, and at least one of
        them actually is `CATALOG_READY` rather than the batch consisting only of withdrawn
        units — the parent consignment moves `INTAKE_ACCEPTED → CATALOGED` on its own, with
        its `version` incremented by 1."

        Design: Corner/state_machines/consignment_bubbles_up_to_cataloged_when_the_last_lot_publishes
        """
        stage = catalog_ready_batch(
            [
                {"serial_number": "CAT-D8T-0001"},
                {"serial_number": "CAT-D8T-0002"},
            ],
            publish_count=0,
        )
        consignment_id = stage["consignment"]["id"]
        first_report, second_report = stage["reports"]
        first_lot, second_lot = stage["lots"]

        validate_success(api_client.publish_condition_report(first_report["id"], INSPECTOR))
        after_first = validate_success(
            api_client.get_consignment(consignment_id, OPERATOR)
        )
        assert after_first["status"] == "INTAKE_ACCEPTED"

        validate_success(api_client.publish_condition_report(second_report["id"], INSPECTOR))
        after_second = validate_success(
            api_client.get_consignment(consignment_id, OPERATOR)
        )
        assert after_second["status"] == "CATALOGED"
        assert after_second["version"] == after_first["version"] + 1

        for lot in (first_lot, second_lot):
            stored = validate_success(api_client.get_lot(lot["id"], OPERATOR))
            assert stored["lifecycle_status"] == "CATALOG_READY"
