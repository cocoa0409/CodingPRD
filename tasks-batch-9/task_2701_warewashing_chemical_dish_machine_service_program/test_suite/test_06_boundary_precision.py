"""
Boundaries probed from both sides: the concentration-drift bands and the
technician workload cap.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_NO_ELIGIBLE_TECHNICIAN
from test_helpers.assertions import (
    assert_calibration_record,
    assert_pct,
    assert_workload,
)
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS, PLATFORM_ADMIN_HEADERS
from test_helpers.types import (
    CERT_L2,
    EFFICACY_NOT_APPLICABLE,
    TECH_AVAILABLE,
    TICKET_DISPATCHED,
    TICKET_QUEUED,
    VERDICT_ADJUSTED,
    VERDICT_FAIL,
    VERDICT_PASS,
    VISIT_IN_PROGRESS,
)


def _visit_ready_for_titration(api):
    """
    An IN_PROGRESS visit on a placement whose DET-100 dispenser targets 1200 ppm
    with the default 10.00 tolerance. The visit is never submitted, so nothing is
    ever applied and every assertion is about creation-time values.
    """
    base = X.program_base(api)
    assert base["detergent"]["concentration_tolerance_pct"] == pytest.approx(
        10.00, abs=0.001
    )

    placement = X.installed_placement(api, base, asset_tag="AT-901")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    ticket = X.file_ticket(api, base, placement["id"])
    dispatched = X.dispatch_ticket(api, ticket["id"])
    assert dispatched["assigned_technician_id"] == base["technician_id"]

    visit = X.book_visit(api, base, ticket["id"])
    X.set_clock(api, "2026-08-01T10:00:00Z")
    arrived = X.arrive_visit(api, base, visit["id"])
    assert arrived["visit_status"] == VISIT_IN_PROGRESS

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "visit_id": visit["id"],
        }
    )
    return base


@pytest.mark.parametrize(
    "measured_ppm,adjusted,expected_drift,expected_verdict",
    [
        (1080, None, -10.00, VERDICT_PASS),
        (1079, 8.80, -10.08, VERDICT_ADJUSTED),
        (1206, None, 0.50, VERDICT_PASS),
        (1500, 6.40, 25.00, VERDICT_ADJUSTED),
        (1501, 6.40, 25.08, VERDICT_FAIL),
    ],
)
def test_drift_bands_are_inclusive_on_the_passing_side(
    api, measured_ppm, adjusted, expected_drift, expected_verdict
):
    """
    Against a 1200 ppm target: 1080 ppm is exactly -10.00 and stays PASS, 1079
    ppm rounds to -10.08 and becomes ADJUSTED, 1206 ppm is exactly 0.50 and stays
    PASS, 1500 ppm is exactly 25.00 and stays ADJUSTED, and 1501 ppm rounds to
    25.08 and becomes FAIL. Equality never crosses a band.

    PRD §3.6: "Both boundaries are inclusive on the *passing* side: an absolute
    drift exactly equal to the product's tolerance is `PASS`, not `ADJUSTED`, and
    an absolute drift of exactly 25.00 is `ADJUSTED`, not `FAIL`."

    Design: Difficulty/boundary_precision_check/drift_pct_tolerance_and_hard_fail_boundaries_are_inclusive_on_the_passing_side
    """
    base = _visit_ready_for_titration(api)

    record = X.record_calibration(
        api,
        base,
        base["visit_id"],
        base["dispenser_id"],
        measured_ppm=measured_ppm,
        measured_dose_ml_per_rack=8.00,
        adjusted_dose_ml_per_rack=adjusted,
    )

    assert_calibration_record(record)
    assert_pct(record["drift_pct"], expected_drift)
    assert record["calibration_verdict"] == expected_verdict
    # A DETERGENT dispenser computes no sanitizer efficacy verdict.
    assert record["efficacy_result"] == EFFICACY_NOT_APPLICABLE
    assert "contact_seconds" not in record or record["contact_seconds"] is None
    assert record["applied"] is False


def test_five_titrations_stamp_their_own_verdicts_and_apply_nothing(api):
    """
    All five probes filed inside one visit leave the dispenser's live dose at
    8.00 with every record still unapplied, because nothing is applied until the
    visit is verified, and the visit's own evidence counter reaches five.

    PRD §3.6: "Recording any calibration record increments the visit's
    `calibration_record_count` by one and the dispenser's `version` by one —
    which is why an engineer taking two consecutive measurements on the same
    dispenser must re-read the dispenser between them to obtain a fresh
    `expected_dispenser_version`."

    Design: Difficulty/boundary_precision_check/drift_pct_tolerance_and_hard_fail_boundaries_are_inclusive_on_the_passing_side
    """
    base = _visit_ready_for_titration(api)

    probes = [
        (1080, None, -10.00, VERDICT_PASS),
        (1079, 8.80, -10.08, VERDICT_ADJUSTED),
        (1206, None, 0.50, VERDICT_PASS),
        (1500, 6.40, 25.00, VERDICT_ADJUSTED),
        (1501, 6.40, 25.08, VERDICT_FAIL),
    ]
    for measured_ppm, adjusted, expected_drift, expected_verdict in probes:
        record = X.record_calibration(
            api,
            base,
            base["visit_id"],
            base["dispenser_id"],
            measured_ppm=measured_ppm,
            measured_dose_ml_per_rack=8.00,
            adjusted_dose_ml_per_rack=adjusted,
        )
        assert_pct(record["drift_pct"], expected_drift)
        assert record["calibration_verdict"] == expected_verdict
        assert record["applied"] is False

    visit = get_success_data(
        api.get_service_visit(base["visit_id"], base["technician_headers"])
    )
    assert visit["calibration_record_count"] == 5

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert dispenser["calibrated_dose_ml_per_rack"] == pytest.approx(8.00, abs=0.01)
    assert dispenser["last_calibrated_at"] is None
    assert dispenser["last_drift_pct"] is None


def _four_queued_tickets_one_technician(api):
    """
    Four INSTALLED machines in one kitchen, each with its own QUEUED RACK_QUALITY
    report, against exactly one AVAILABLE NW L2 engineer.
    """
    base = X.program_base(
        api,
        technician_overrides={
            "certification_level": CERT_L2,
            "status": TECH_AVAILABLE,
        },
    )
    tickets = []
    for index in range(4):
        placement = X.installed_placement(api, base, asset_tag=f"AT-A0{index + 1}")
        tickets.append(X.file_ticket(api, base, placement["id"]))

    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(technician, 0)

    base["tickets"] = tickets
    return base


def test_third_dispatch_is_accepted_at_a_workload_of_two(api):
    """
    Eligibility needs the counter strictly below three, so the third dispatch is
    evaluated at two and succeeds, taking the engineer to exactly three.

    PRD §3.5: "and their `open_ticket_count` is strictly fewer than three, so an
    engineer already carrying three open jobs is full."

    Design: Difficulty/boundary_precision_check/technician_workload_cap_boundary_empties_the_dispatch_pool
    """
    base = _four_queued_tickets_one_technician(api)

    for index in range(2):
        dispatched = X.dispatch_ticket(api, base["tickets"][index]["id"])
        assert dispatched["assigned_technician_id"] == base["technician_id"]

    before_third = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(before_third, 2)

    third = X.dispatch_ticket(api, base["tickets"][2]["id"])
    assert third["assigned_technician_id"] == base["technician_id"]
    assert third["status"] == TICKET_DISPATCHED

    at_cap = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(at_cap, 3)


def test_fourth_dispatch_empties_the_pool_and_mutates_nothing(api):
    """
    At a workload of exactly three the only candidate is filtered out, the fourth
    dispatch fails with an empty candidate set, and not one field moves.

    PRD §3.5: "When the candidate set comes out empty the request fails with
    `ERR_NO_ELIGIBLE_TECHNICIAN` and **nothing at all is mutated** — the ticket
    remains `QUEUED`, `assigned_technician_id` remains null and
    `escalation_level` is untouched."

    Design: Difficulty/boundary_precision_check/technician_workload_cap_boundary_empties_the_dispatch_pool
    """
    base = _four_queued_tickets_one_technician(api)

    for index in range(3):
        X.dispatch_ticket(api, base["tickets"][index]["id"])

    validate_error(
        api.dispatch_service_ticket(
            base["tickets"][3]["id"], PLATFORM_ADMIN_HEADERS, F.dispatch_payload()
        ),
        ERR_NO_ELIGIBLE_TECHNICIAN,
        409,
    )

    fourth = get_success_data(
        api.get_service_ticket(base["tickets"][3]["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert fourth["status"] == TICKET_QUEUED
    assert fourth["assigned_technician_id"] is None
    assert fourth["escalation_level"] == 0

    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(technician, 3)
    assert technician["quality_flag_count"] == 0

    for index in range(3):
        ticket = get_success_data(
            api.get_service_ticket(
                base["tickets"][index]["id"], ACCOUNT_MANAGER_HEADERS
            )
        )
        assert ticket["status"] == TICKET_DISPATCHED
