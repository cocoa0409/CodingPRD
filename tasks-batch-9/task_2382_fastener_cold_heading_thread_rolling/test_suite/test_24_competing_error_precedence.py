"""Competing refusals on a single fastener-plant request.

Some requests break two of the plant's rules at once — a lot frozen on quality hold
whose furnace charge is also too heavy, or a certificate signed by the very inspector
who destroyed the sample pieces on a lot whose risk score is above the certifiable
ceiling. The PRD evaluates its rules in a strict ascending ladder and the first rule
violated decides the response, so this module pins which refusal the caller actually
sees, and proves with single-failure controls that the losing rule was live all along.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    factories,
    fixtures,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

HEAT_TREAT_HEADERS = TEST_USERS["heat_treat_headers"]
MANAGER_HEADERS = TEST_USERS["manager_headers"]

# The two-operation route the competing-refusal lots run, from PRD §3.5.
TWO_OP_ROUTE = [
    {"op_type": "THREAD_ROLL", "sequence_no": 1, "pieces_out": 9750, "machine_code": "TR-1"},
    {"op_type": "POINT", "sequence_no": 2, "pieces_out": 9740, "machine_code": "PT-1"},
]

TWO_OP_SPEC_OVERRIDES = {
    "required_secondary_ops": ["THREAD_ROLL", "POINT"],
    "blank_mass_g": 20.0,
    "packaging_mode": "BY_WEIGHT",
    "nominal_pack_count": 500,
    "pieces_per_kg": 62.5,
}

# 9740 available pieces x 20.0 g / 1000 = 194.800 kg of charge (PRD §3.5).
EXPECTED_CHARGE_MASS_KG = 194.800

HEAT_TREAT_BOOKING_WINDOW = {
    "window_start_at": "2026-09-01T18:00:00Z",
    "window_end_at": "2026-09-01T23:00:00Z",
}


# ---------------------------------------------------------------------------
# Instance setups
# ---------------------------------------------------------------------------
def _secondary_done_lot(max_charge_mass_kg: float) -> Dict[str, Any]:
    """A SECONDARY_DONE lot holding 9740 pieces, plus a furnace of the given capacity."""
    return fixtures.setup_secondary_done_lot(
        planned_pieces=10000,
        headed_count=9800,
        heading_scrap_count=150,
        ops=[dict(op) for op in TWO_OP_ROUTE],
        spec_overrides=dict(TWO_OP_SPEC_OVERRIDES),
        furnace_overrides={
            "furnace_code": "FCE-SMALL",
            "max_charge_mass_kg": max_charge_mass_kg,
        },
        lot_overrides={"lot_code": "L-2601"},
    )


def _book_heat_treat_run(lot_id: str, furnace_id: str):
    """Book the canonical 18:00-23:00 furnace window for the lot."""
    return api_client.create_heat_treat_run(
        factories.create_heat_treat_run_payload(
            lot_id, furnace_id, **HEAT_TREAT_BOOKING_WINDOW
        ),
        HEAT_TREAT_HEADERS,
    )


def _runs_booked_for(lot_id: str) -> int:
    items, meta = validate_paginated(
        api_client.list_heat_treat_runs(
            HEAT_TREAT_HEADERS, params={"production_lot_id": lot_id}
        )
    )
    assert len(items) == meta["total_count"], (
        f"Expected the page to hold every run of lot {lot_id}, "
        f"got {len(items)} rows against total_count {meta['total_count']}"
    )
    return meta["total_count"]


def _drafted_certificate_over_the_ceiling() -> Dict[str, Any]:
    """A DRAFT certificate on a lot whose risk_score_final is 65.00.

    Die set DIE-1S-778 is rated for exactly the lot's inflated demand, so
    tool_utilization_pct lands on 100.00; the coupon's decarburization sits exactly on
    the part's 0.150 mm ceiling; and the relief bake starts exactly 4.000 hours after
    plating. The destructive test is performed by ``user-7``.
    """
    return fixtures.setup_drafted_certificate(
        cert_serial="CERT-0030",
        drafter_headers=MANAGER_HEADERS,
        spec_overrides=dict(TWO_OP_SPEC_OVERRIDES),
        tool_overrides={"tool_code": "DIE-1S-778", "rated_life_pieces": 5985},
        press_code="PRESS-6",
        lot_overrides={"lot_code": "L-2630"},
        planned_pieces=5700,
        headed_count=5900,
        heading_scrap_count=85,
        ops=[
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": 5850,
                "machine_code": "TR-1",
            },
            {
                "op_type": "POINT",
                "sequence_no": 2,
                "pieces_out": 5840,
                "machine_code": "PT-1",
            },
        ],
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.150,
        bake_started_at="2026-09-02T06:00:00Z",
        inspector_user_id="user-7",
        min_measured_core_hardness_hv=330.0,
    )


def _assert_certificate_untouched(cert_id: str, expected_version: int) -> None:
    cert = fixtures.read_certificate(cert_id)
    assert cert["status"] == "DRAFT", (
        f"Expected DRAFT, got {cert['status']} after a refused issue attempt"
    )
    assert cert["signed_by_user_id"] is None, (
        f"Expected signed_by_user_id to stay empty, got {cert['signed_by_user_id']}"
    )
    assert cert["issued_at"] is None, (
        f"Expected issued_at to stay empty, got {cert['issued_at']}"
    )
    assert cert["version"] == expected_version, (
        f"Expected version {expected_version}, got {cert['version']} "
        "after a refused issue attempt"
    )


# ---------------------------------------------------------------------------
# Hold freeze (tier 9) against furnace charge capacity (tier 17)
# ---------------------------------------------------------------------------
class TestHoldOutranksFurnaceCapacity:
    """A booking that is both frozen by a hold and too heavy for the furnace."""

    def test_hold_freeze_wins_over_the_oversized_charge(self):
        """A held lot whose 194.800 kg charge also busts a 100.0 kg furnace reports the hold.

        PRD: "The first rule violated decides the response, and no later rule runs."

        PRD: "The production lot in scope must not have `disposition` of `HOLD` — otherwise `ERR_LOT_ON_HOLD` (409)."

        PRD: "The run's `charge_mass_kg` is derived, not supplied: it is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places, and it may not exceed the furnace's `max_charge_mass_kg` — the comparison is inclusive, so a charge exactly at capacity is accepted, and anything heavier is refused with `ERR_FURNACE_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/lot_hold_state_error_precedes_furnace_capacity_error
        """
        env = _secondary_done_lot(max_charge_mass_kg=100.0)
        lot_id = env["lot"]["id"]
        assert env["lot"]["available_count"] == 9740, (
            f"Expected 9740 available pieces, got {env['lot']['available_count']}"
        )

        fixtures.place_hold(lot_id, reason="SURFACE_FINISH_REVIEW")

        response = _book_heat_treat_run(lot_id, env["furnace"]["id"])
        validate_error(response, ApiErrorId.ERR_LOT_ON_HOLD.value, 409)

        assert _runs_booked_for(lot_id) == 0, (
            "A refused booking must leave no heat treatment run on the lot"
        )
        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "SECONDARY_DONE", (
            f"Expected SECONDARY_DONE, got {lot['process_state']} after the refusal"
        )
        assert lot["disposition"] == "HOLD", (
            f"Expected the lot to stay on HOLD, got {lot['disposition']}"
        )

    def test_releasing_the_hold_exposes_the_capacity_refusal_underneath(self):
        """Once the hold is cleared the very same booking is refused for furnace capacity.

        PRD: "A successful release takes the lot `HOLD → IN_PROCESS`, resets `hold_source` to `NONE`, and increments the `version` by 1."

        PRD: "The run's `charge_mass_kg` is derived, not supplied: it is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places, and it may not exceed the furnace's `max_charge_mass_kg` — the comparison is inclusive, so a charge exactly at capacity is accepted, and anything heavier is refused with `ERR_FURNACE_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/lot_hold_state_error_precedes_furnace_capacity_error
        """
        env = _secondary_done_lot(max_charge_mass_kg=100.0)
        lot_id = env["lot"]["id"]
        furnace_id = env["furnace"]["id"]

        fixtures.place_hold(lot_id, reason="SURFACE_FINISH_REVIEW")
        validate_error(
            _book_heat_treat_run(lot_id, furnace_id),
            ApiErrorId.ERR_LOT_ON_HOLD.value,
            409,
        )

        released = fixtures.release_hold(lot_id, note="FINISH_ACCEPTED")
        assert released["disposition"] == "IN_PROCESS", (
            f"Expected IN_PROCESS after the release, got {released['disposition']}"
        )
        assert released["hold_source"] == "NONE", (
            f"Expected hold_source NONE after the release, got {released['hold_source']}"
        )

        response = _book_heat_treat_run(lot_id, furnace_id)
        validate_error(response, ApiErrorId.ERR_FURNACE_CAPACITY_EXCEEDED.value, 422)

        assert _runs_booked_for(lot_id) == 0, (
            "Neither refused booking may leave a heat treatment run behind"
        )
        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "SECONDARY_DONE", (
            f"Expected SECONDARY_DONE, got {lot['process_state']} after both refusals"
        )
        assert lot["disposition"] == "IN_PROCESS", (
            f"Expected IN_PROCESS, got {lot['disposition']} after both refusals"
        )

    def test_hold_alone_blocks_a_booking_a_bigger_furnace_would_accept(self):
        """With a 400.0 kg furnace the charge fits, so the hold is the only obstacle.

        PRD: "The production lot in scope must not have `disposition` of `HOLD` — otherwise `ERR_LOT_ON_HOLD` (409)."

        PRD: "This rule guards the same twenty-two operations as tier 8 minus two: releasing a hold is exempt (it is the operation that clears the hold) and placing a hold is exempt (it has its own precondition)."

        Design: Difficulty/priority_pair_validation_conflict/lot_hold_state_error_precedes_furnace_capacity_error
        """
        env = _secondary_done_lot(max_charge_mass_kg=400.0)
        lot_id = env["lot"]["id"]
        furnace_id = env["furnace"]["id"]

        fixtures.place_hold(lot_id, reason="SURFACE_FINISH_REVIEW")
        validate_error(
            _book_heat_treat_run(lot_id, furnace_id),
            ApiErrorId.ERR_LOT_ON_HOLD.value,
            409,
        )
        assert _runs_booked_for(lot_id) == 0, (
            "The held booking must leave no heat treatment run on the lot"
        )

        fixtures.release_hold(lot_id, note="FINISH_ACCEPTED")
        run = validate_success(_book_heat_treat_run(lot_id, furnace_id), 201)
        assert run["charge_mass_kg"] == pytest.approx(EXPECTED_CHARGE_MASS_KG, abs=0.001), (
            f"Expected a derived charge of {EXPECTED_CHARGE_MASS_KG} kg, "
            f"got {run['charge_mass_kg']}"
        )
        assert run["status"] == "PLANNED", (
            f"Expected a booked run to start PLANNED, got {run['status']}"
        )
        assert _runs_booked_for(lot_id) == 1, (
            "Exactly one heat treatment run must exist once the hold is released"
        )


# ---------------------------------------------------------------------------
# Segregation of duties (tier 12) against the risk ceiling (tier 16)
# ---------------------------------------------------------------------------
class TestSegregationOfDutiesOutranksRiskCeiling:
    """An issue attempt that is both self-signed and over the certifiable risk ceiling."""

    def test_segregation_of_duties_wins_over_the_risk_ceiling(self):
        """The inspector who destroyed the sample is refused for duties, not for risk.

        PRD: "The first rule violated decides the response, and no later rule runs."

        PRD: "Later, when a certificate citing that test is issued or reissued, the system compares the acting `X-User-ID` against the stored `performed_by_user_id` of the cited test; if they are equal, the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD: "And the lot's `risk_score_final` may be at most 55.00; the bound is inclusive, so exactly 55.00 is certifiable, while a higher score is refused with `ERR_RISK_SCORE_TOO_HIGH`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_precedes_risk_ceiling_error_at_issue
        """
        env = _drafted_certificate_over_the_ceiling()
        lot = env["lot"]
        test = env["lot_test"]
        cert = env["certificate"]

        assert lot["tool_utilization_pct"] == pytest.approx(100.00, abs=0.001), (
            f"Expected tool_utilization_pct 100.00, got {lot['tool_utilization_pct']}"
        )
        assert lot["risk_score_pre_test"] == pytest.approx(65.00, abs=0.001), (
            f"Expected risk_score_pre_test 65.00, got {lot['risk_score_pre_test']}"
        )
        assert lot["risk_score_final"] == pytest.approx(65.00, abs=0.001), (
            f"Expected risk_score_final 65.00, got {lot['risk_score_final']}"
        )
        assert test["performed_by_user_id"] == "user-7", (
            f"Expected the test to record user-7, got {test['performed_by_user_id']}"
        )

        response = api_client.issue_certification_document(
            cert["id"], make_manager_headers("user-7")
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        _assert_certificate_untouched(cert["id"], cert["version"])
        refreshed = fixtures.read_lot(lot["id"])
        assert refreshed["process_state"] == "TESTED", (
            f"Expected the lot to stay TESTED, got {refreshed['process_state']}"
        )

    def test_the_frozen_sampling_plan_behind_the_sixty_five_point_score(self):
        """A pre-test score of 65.00 freezes TIGHTENED inspection: 115 pieces, zero tolerated.

        PRD: "Severity is `TIGHTENED` when either of two things is true: the lot's `risk_score_pre_test` is at least 40.0, or a rejected test already exists anywhere in the plant on a production lot sharing both the same `part_spec_id` and the same `traceability_heat_id` as this lot."

        PRD: "Under **tightened inspection**, `sample_size` is the greater of 13 and 1.5 multiplied by the square root of `available_count`, raised upward to the next whole piece, and `acceptance_number` is 0 unconditionally — the very same measured failure count that accepts a lot under normal inspection rejects it under tightened inspection, and the sampling floor of 13 pieces is itself out of reach for a nearly exhausted lot."

        PRD: "`risk_score_final` adds test evidence to the frozen pre-test value: it is `risk_score_pre_test` plus 12.5 points for each failure counted in `total_failures`, capped at 100, and rounded half up to two decimal places."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_precedes_risk_ceiling_error_at_issue
        """
        env = _drafted_certificate_over_the_ceiling()
        test = env["lot_test"]
        lot = env["lot"]

        assert test["severity"] == "TIGHTENED", (
            f"Expected TIGHTENED severity at a pre-test score of 65.00, "
            f"got {test['severity']}"
        )
        assert test["sample_size"] == 115, (
            f"Expected a tightened sample of 115 pieces from 5840 available, "
            f"got {test['sample_size']}"
        )
        assert test["acceptance_number"] == 0, (
            f"Expected acceptance_number 0 under tightened inspection, "
            f"got {test['acceptance_number']}"
        )
        assert test["result"] == "ACCEPT", (
            f"Expected ACCEPT with zero failures, got {test['result']}"
        )
        assert lot["inspection_severity"] == "TIGHTENED", (
            f"Expected the lot to freeze TIGHTENED, got {lot['inspection_severity']}"
        )
        assert lot["risk_score_final"] == pytest.approx(65.00, abs=0.001), (
            f"Expected risk_score_final to stay at 65.00 with zero failures, "
            f"got {lot['risk_score_final']}"
        )

    def test_a_second_manager_then_meets_the_risk_ceiling_refusal(self):
        """A manager who did not perform the test clears duties and hits the 55.00 ceiling.

        PRD: "And the lot's `risk_score_final` may be at most 55.00; the bound is inclusive, so exactly 55.00 is certifiable, while a higher score is refused with `ERR_RISK_SCORE_TOO_HIGH`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_precedes_risk_ceiling_error_at_issue
        """
        env = _drafted_certificate_over_the_ceiling()
        cert = env["certificate"]

        validate_error(
            api_client.issue_certification_document(
                cert["id"], make_manager_headers("user-7")
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        response = api_client.issue_certification_document(
            cert["id"], make_manager_headers("qm-1")
        )
        validate_error(response, ApiErrorId.ERR_RISK_SCORE_TOO_HIGH.value, 422)

        _assert_certificate_untouched(cert["id"], cert["version"])
        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "TESTED", (
            f"Expected the lot to stay TESTED, got {lot['process_state']}"
        )
        assert lot["risk_score_final"] == pytest.approx(65.00, abs=0.001), (
            f"Expected risk_score_final 65.00, got {lot['risk_score_final']}"
        )

    def test_segregation_of_duties_alone_refuses_a_certifiable_lot(self):
        """A lot comfortably under the risk ceiling is still refused when the signer tested it.

        PRD: "Signing is exclusively a `QualityManager` act, and it is where segregation of duties bites: the acting `X-User-ID` must differ from the `performed_by_user_id` of the cited test, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_precedes_risk_ceiling_error_at_issue
        """
        env = fixtures.setup_drafted_certificate(
            drafter_headers=MANAGER_HEADERS,
            inspector_user_id="user-7",
        )
        lot = env["lot"]
        cert = env["certificate"]

        assert lot["risk_score_final"] <= 55.00, (
            f"This control needs a certifiable score, got {lot['risk_score_final']}"
        )
        assert env["lot_test"]["performed_by_user_id"] == "user-7", (
            f"Expected the test to record user-7, "
            f"got {env['lot_test']['performed_by_user_id']}"
        )

        response = api_client.issue_certification_document(
            cert["id"], make_manager_headers("user-7")
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        _assert_certificate_untouched(cert["id"], cert["version"])
        refreshed = fixtures.read_lot(lot["id"])
        assert refreshed["process_state"] == "TESTED", (
            f"Expected the lot to stay TESTED, got {refreshed['process_state']}"
        )

        issued = fixtures.issue_certificate(cert["id"], manager_user_id="qm-1")
        assert issued["status"] == "ISSUED", (
            f"A different manager must be able to sign the same certificate, "
            f"got {issued['status']}"
        )
        assert issued["signed_by_user_id"] == "qm-1", (
            f"Expected signed_by_user_id qm-1, got {issued['signed_by_user_id']}"
        )
