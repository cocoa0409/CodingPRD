"""Global rule ordering when one request breaks several rules at once.

A station log against a unit in the wrong build state must answer with the build
state even when the acting technician is also uncertified, and an approval of a
warranty claim must answer with part fitment even when the shelf is also empty.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    PLANT_MANAGER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
    make_technician_headers,
)

DRUM_START = "2026-08-01T08:00:00Z"
DRUM_END = "2026-08-01T09:00:00Z"


class TestStationLogBuildStateOutranksTechnicianCertification:
    """The build-state rule is numbered 26 and the certification rule 36."""

    def test_01_planned_unit_and_uncertified_technician_reports_build_state(self, api):
        """A drum log on a unit never released to the floor, filed by a technician
        with no certification at all, reports the build-state failure only.

        PRD: "The rule set is therefore **strictly and globally ordered**: when a request violates more than one rule, the response carries the error of the highest-ranked violated rule and no other, and the request is rejected before any state change or derived recomputation occurs."
        Design: Difficulty/priority_pair_validation_conflict/build_state_beats_technician_cert_on_station_log
        """
        model = fx.make_model(api)
        station = fx.make_station(api)
        technician = fx.make_technician(api)
        build = fx.make_build_order(api, model["id"])

        payload = f.station_log_payload(
            station["id"], "DRUM_FAB", DRUM_START, DRUM_END, "PASS"
        )
        response = api.create_station_log(
            build["id"], payload, make_technician_headers(technician["id"])
        )
        validate_error(response, E.ERR_BUILD_STATE_INVALID, expected_status=409)

        after = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        assert after["build_state"] == "PLANNED"
        assert after["station_pass_count"] == 0
        assert after["labor_minutes_total"] == 0

        rows, _ = validate_paginated(
            api.list_station_logs(PLANT_MANAGER, build_order_id=build["id"])
        )
        assert rows == []

        technician_after = validate_success(
            api.get_technician(technician["id"], TRAINING_ADMIN), expected_status=200
        )
        assert technician_after["cert_state"] == "UNCERTIFIED"

    def test_02_correct_build_state_lets_the_certification_rule_fire(self, api):
        """With the unit legitimately on the floor, the very same uncertified
        technician now trips the certification rule instead.

        PRD: "The technician the operation depends on has `cert_state` of `ACTIVE`, has `cert_expires_on` strictly after the current logical-clock instant, and holds the scope the operation demands: the referenced station's `station_type` for a station log, `QA_SIGNOFF` for a final inspection, and the claimed part's `requires_cert_scope` for the claim's `reported_by_technician_id` whenever that scope is not `NONE`."
        Design: Difficulty/priority_pair_validation_conflict/build_state_beats_technician_cert_on_station_log
        """
        env = fx.make_certified_model(api)
        station = fx.make_station(api)
        technician = fx.make_technician(api)
        build = fx.make_build_order(api, env["model"]["id"])
        fx.release_build(api, build["id"])

        payload = f.station_log_payload(
            station["id"], "DRUM_FAB", DRUM_START, DRUM_END, "PASS"
        )
        response = api.create_station_log(
            build["id"], payload, make_technician_headers(technician["id"])
        )
        validate_error(response, E.ERR_TECHNICIAN_NOT_CERTIFIED, expected_status=422)

        after = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        assert after["build_state"] == "ON_FLOOR"
        assert after["station_pass_count"] == 0
        assert after["labor_minutes_total"] == 0


class TestAdjudicationFitmentOutranksPartStock:
    """The fitment rule is numbered 38 and the stock rule 56."""

    def test_01_unfitted_and_unstocked_part_reports_part_not_fitted(self, api):
        """Approving a claim for a vended-only bearing on a 60 lb on-premises unit
        with an empty shelf reports the fitment failure, not the shortage.

        PRD: "The rule set is therefore **strictly and globally ordered**: when a request violates more than one rule, the response carries the error of the highest-ranked violated rule and no other, and the request is rejected before any state change or derived recomputation occurs."
        Design: Difficulty/priority_pair_validation_conflict/part_fitment_beats_stock_shortage_on_adjudicate
        """
        env = fx.make_warranty_environment(
            api,
            on_hand_qty=0,
            part_overrides={
                "part_number": "BRG-9910",
                "fits_product_lines": ["VENDED"],
                "fits_min_capacity_lb": 20,
                "fits_max_capacity_lb": 40,
            },
        )
        claim = fx.make_submitted_claim(api, env, diagnostics_code="DX-BRG-11")
        part_version = fx.read_part_version(api, env["part"]["id"])

        response = api.adjudicate_warranty_claim(
            claim["id"],
            f.adjudicate_payload(part_version, "APPROVE"),
            WARRANTY_ANALYST,
        )
        validate_error(response, E.ERR_PART_NOT_FITTED, expected_status=422)

        claim_after = validate_success(
            api.get_warranty_claim(claim["id"], WARRANTY_ANALYST), expected_status=200
        )
        assert claim_after["claim_state"] == "SUBMITTED"
        assert claim_after["coverage_variant"] == "NONE"
        a.assert_cents(claim_after["covered_amount_cents"], 0)

        part_after = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert part_after["on_hand_qty"] == 0
        assert part_after["reserved_qty"] == 0
        assert part_after["stock_state"] == "BACKORDERED"
        assert part_after["version"] == part_version

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        a.assert_cents(distributor["warranty_credit_cents"], 0)
        assert distributor["open_claim_count"] == 1

    def test_02_fitted_part_with_an_empty_shelf_reports_insufficient_stock(self, api):
        """When only the shelf is empty and the bearing does fit the unit, the
        stock rule is the one that answers.

        PRD: "The claimed part has `on_hand_qty` of at least 1 at approval time — otherwise `ERR_INSUFFICIENT_PART_STOCK`, HTTP 409, on claim adjudication."
        Design: Difficulty/priority_pair_validation_conflict/part_fitment_beats_stock_shortage_on_adjudicate
        """
        env = fx.make_warranty_environment(api, on_hand_qty=0)
        claim = fx.make_submitted_claim(api, env)
        part_version = fx.read_part_version(api, env["part"]["id"])

        response = api.adjudicate_warranty_claim(
            claim["id"],
            f.adjudicate_payload(part_version, "APPROVE"),
            WARRANTY_ANALYST,
        )
        validate_error(response, E.ERR_INSUFFICIENT_PART_STOCK, expected_status=409)

        claim_after = validate_success(
            api.get_warranty_claim(claim["id"], WARRANTY_ANALYST), expected_status=200
        )
        assert claim_after["claim_state"] == "SUBMITTED"
        a.assert_cents(claim_after["covered_amount_cents"], 0)
