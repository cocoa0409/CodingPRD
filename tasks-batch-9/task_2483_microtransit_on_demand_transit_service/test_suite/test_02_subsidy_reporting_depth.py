"""Depth coverage of subsidy reporting (PRD §3.9) and the figures it reads.

Every scenario is composed from scratch through the public endpoints, because the
server is relaunched with an empty database before each individual test. The
logical clock reads 2026-08-01T00:00:00Z at start-up, so each builder walks it to
the 2026-08-03 service day explicitly before touching anything time-dependent.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import subsidy_report_payload
from test_helpers.fixtures import (
    accept_assignment,
    board_assignment,
    close_block,
    complete_assignment,
    create_active_zone,
    create_approved_stop,
    create_block,
    create_driver,
    create_report,
    create_rider,
    create_trip,
    create_vehicle,
    dispatch_trip,
    open_block,
    refresh_block,
    refresh_report,
    refresh_trip,
    refresh_zone,
    set_clock,
    submit_report,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    AUDITOR_ID,
    FINANCE_ANALYST_2_HEADERS,
    FINANCE_ANALYST_2_ID,
    FINANCE_ANALYST_HEADERS,
    FINANCE_ANALYST_ID,
)

# Reporting periods used below. Both are inclusive on each end (PRD §3.9).
PERIOD_AUGUST = {"period_start_date": "2026-08-01", "period_end_date": "2026-08-31"}
PERIOD_SERVICE_DAY = {"period_start_date": "2026-08-03", "period_end_date": "2026-08-03"}


# ─── Raw-response helpers for the calls under test ─────────────────────────


def _open_report(zone_id, variant, period):
    """Open a report and return the raw response so the 201 can be validated."""
    return api_client.create_subsidy_report(
        subsidy_report_payload(zone_id, variant=variant, **period),
        FINANCE_ANALYST_HEADERS,
    )


def _submit(report_id, headers=FINANCE_ANALYST_HEADERS):
    return api_client.submit_subsidy_report(report_id, headers)


def _certify(report_id, note=None, headers=AUDITOR_HEADERS):
    payload = {} if note is None else {"note": note}
    return api_client.certify_subsidy_report(report_id, headers, payload)


def _amend(report_id, headers=FINANCE_ANALYST_HEADERS):
    return api_client.amend_subsidy_report(report_id, headers)


# ─── Scenario builders ─────────────────────────────────────────────────────


def _build_divergent_variant_scope():
    """One CLOSED block with 1.50 actual hours against 4.00 scheduled, one block
    left OPEN with 3.00 scheduled hours, one COMPLETED trip charged 325 cents and
    one trip stalled in ASSIGNED / QUOTED with no ledger rows at all."""
    set_clock("2026-08-03T06:00:00Z")
    zone = create_active_zone()
    stop_0 = create_approved_stop(zone["id"], "S0", 0)
    stop_4 = create_approved_stop(zone["id"], "S4", 4)
    stop_6 = create_approved_stop(zone["id"], "S6", 6)
    stop_10 = create_approved_stop(zone["id"], "S10", 10)
    vehicle_1 = create_vehicle(zone["id"], "V1")
    vehicle_2 = create_vehicle(zone["id"], "V2", wav_positions=0)
    driver_1 = create_driver(zone["id"], "D1")
    driver_2 = create_driver(zone["id"], "D2", wav_certified=False)
    rider_1 = create_rider(zone["id"], "R1")
    rider_2 = create_rider(zone["id"], "R2")
    block_1 = create_block(zone["id"], vehicle_1["id"], driver_1["id"])
    block_2 = create_block(
        zone["id"], vehicle_2["id"], driver_2["id"], end_utc="2026-08-03T09:00:00Z"
    )
    block_1 = open_block(block_1["id"])
    block_2 = open_block(block_2["id"])

    trip_1 = create_trip(zone["id"], rider_1["id"], stop_0["id"], stop_4["id"])
    offer_1 = dispatch_trip(trip_1["id"], block_1["id"])
    trip_2 = create_trip(zone["id"], rider_2["id"], stop_6["id"], stop_10["id"])
    offer_2 = dispatch_trip(trip_2["id"], block_2["id"])

    set_clock("2026-08-03T07:00:00Z")
    accept_assignment(offer_1["id"], driver_1["id"])
    board_assignment(offer_1["id"], driver_1["id"])
    accept_assignment(offer_2["id"], driver_2["id"])
    set_clock("2026-08-03T07:12:00Z")
    complete_assignment(offer_1["id"], driver_1["id"])
    set_clock("2026-08-03T07:30:00Z")
    block_1 = close_block(block_1["id"])
    return {
        "zone": zone,
        "block_1": block_1,
        "block_2": refresh_block(block_2["id"]),
        "trip_1": refresh_trip(trip_1["id"]),
        "trip_2": refresh_trip(trip_2["id"]),
    }


def _file_both_variants(zone_id):
    """Reproduce the two filings: a PROVISIONAL and a FINAL report over the same
    inclusive period, which the variant-scoped overlap rule permits."""
    provisional = validate_success(
        _open_report(zone_id, "PROVISIONAL", PERIOD_AUGUST), 201
    )
    provisional = validate_success(_submit(provisional["id"]))
    final = validate_success(_open_report(zone_id, "FINAL", PERIOD_AUGUST), 201)
    final = validate_success(_submit(final["id"]))
    return provisional, final


def _build_rounding_order_state():
    """Two in-period blocks of 2.01 and 1.01 scheduled revenue hours — both of
    whose exact per-block costs end in .40 — plus one completed 325-cent trip."""
    set_clock("2026-08-03T06:00:00Z")
    zone = create_active_zone()
    stop_0 = create_approved_stop(zone["id"], "S0", 0)
    stop_4 = create_approved_stop(zone["id"], "S4", 4)
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    rider = create_rider(zone["id"], "R1")
    block_a = create_block(
        zone["id"], vehicle["id"], driver["id"], end_utc="2026-08-03T08:00:36Z"
    )
    block_b = create_block(
        zone["id"],
        vehicle["id"],
        driver["id"],
        start_utc="2026-08-03T09:00:00Z",
        end_utc="2026-08-03T10:00:36Z",
    )
    block_a = open_block(block_a["id"])

    trip = create_trip(zone["id"], rider["id"], stop_0["id"], stop_4["id"])
    offer = dispatch_trip(trip["id"], block_a["id"])
    set_clock("2026-08-03T07:00:00Z")
    accept_assignment(offer["id"], driver["id"])
    board_assignment(offer["id"], driver["id"])
    set_clock("2026-08-03T07:12:00Z")
    complete_assignment(offer["id"], driver["id"])
    return {
        "zone": zone,
        "block_a": refresh_block(block_a["id"]),
        "block_b": refresh_block(block_b["id"]),
        "trip": refresh_trip(trip["id"]),
    }


def _build_certified_report_over_empty_day():
    """A zone with one CLOSED two-hour block and no trips at all, whose FINAL
    report has been filed by fa-1 and certified by aud-1."""
    set_clock("2026-08-03T06:00:00Z")
    zone = create_active_zone()
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    block = open_block(
        create_block(zone["id"], vehicle["id"], driver["id"])["id"]
    )
    set_clock("2026-08-03T08:00:00Z")
    block = close_block(block["id"])

    report = create_report(zone["id"], variant="FINAL", **PERIOD_AUGUST)
    report = submit_report(report["id"])
    report = validate_success(_certify(report["id"], note="first pass accepted"))
    return {"zone": zone, "block": block, "report": report}


def _build_deficient_equivalence_state():
    """Two completed trips — a non-accessible one that waited 4 minutes and a
    wheelchair-accessible one that waited 10 — leave the zone DEFICIENT, while a
    third accepted-but-unboarded trip stands ready to move the ratio, and the
    block stays OPEN throughout so the finalisation gate is also violated."""
    set_clock("2026-08-03T06:00:00Z")
    zone = create_active_zone()
    stop_0 = create_approved_stop(zone["id"], "S0", 0)
    stop_4 = create_approved_stop(zone["id"], "S4", 4)
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    rider_nonwav = create_rider(zone["id"], "RN")
    rider_wav = create_rider(zone["id"], "RW", mobility_device="WHEELCHAIR")
    rider_nonwav_2 = create_rider(zone["id"], "RN2")
    block = open_block(
        create_block(zone["id"], vehicle["id"], driver["id"])["id"]
    )

    trip_nonwav = create_trip(
        zone["id"], rider_nonwav["id"], stop_0["id"], stop_4["id"]
    )
    offer_nonwav = dispatch_trip(trip_nonwav["id"], block["id"])
    trip_wav = create_trip(zone["id"], rider_wav["id"], stop_0["id"], stop_4["id"])
    offer_wav = dispatch_trip(trip_wav["id"], block["id"])
    trip_nonwav_2 = create_trip(
        zone["id"],
        rider_nonwav_2["id"],
        stop_0["id"],
        stop_4["id"],
        requested_pickup_utc="2026-08-03T07:30:00Z",
    )
    offer_nonwav_2 = dispatch_trip(trip_nonwav_2["id"], block["id"])

    accept_assignment(offer_nonwav["id"], driver["id"])
    accept_assignment(offer_wav["id"], driver["id"])
    accept_assignment(offer_nonwav_2["id"], driver["id"])

    set_clock("2026-08-03T07:04:00Z")
    board_assignment(offer_nonwav["id"], driver["id"])
    set_clock("2026-08-03T07:10:00Z")
    board_assignment(offer_wav["id"], driver["id"])
    set_clock("2026-08-03T07:16:00Z")
    complete_assignment(offer_nonwav["id"], driver["id"])
    set_clock("2026-08-03T07:22:00Z")
    complete_assignment(offer_wav["id"], driver["id"])

    report = create_report(zone["id"], variant="FINAL", **PERIOD_SERVICE_DAY)
    report = submit_report(report["id"])
    return {
        "zone": zone,
        "block": block,
        "driver": driver,
        "offer_nonwav_2": offer_nonwav_2,
        "trip_nonwav_2": trip_nonwav_2,
        "report": report,
    }


def _build_zero_trip_closed_block_state():
    """One block open for 7218 seconds — 2.005 hours exactly — and no rider,
    stop, trip or assignment anywhere, plus a DRAFT FINAL report over the day."""
    set_clock("2026-08-03T05:00:00Z")
    zone = create_active_zone()
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    block = create_block(zone["id"], vehicle["id"], driver["id"])
    set_clock("2026-08-03T06:00:00Z")
    block = open_block(block["id"])
    set_clock("2026-08-03T08:00:18Z")
    block = close_block(block["id"])
    report = create_report(zone["id"], variant="FINAL", **PERIOD_SERVICE_DAY)
    return {"zone": zone, "block": block, "report": report}


def _build_submitted_while_block_open():
    """A FINAL report filed while its only in-period block is still OPEN, so the
    CLOSED-only block scope was empty at submission but one completed trip had
    already contributed 325 cents of fare revenue."""
    set_clock("2026-08-03T06:00:00Z")
    zone = create_active_zone()
    stop_0 = create_approved_stop(zone["id"], "S0", 0)
    stop_4 = create_approved_stop(zone["id"], "S4", 4)
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    rider = create_rider(zone["id"], "R1")
    block = open_block(
        create_block(zone["id"], vehicle["id"], driver["id"])["id"]
    )

    trip = create_trip(zone["id"], rider["id"], stop_0["id"], stop_4["id"])
    offer = dispatch_trip(trip["id"], block["id"])
    accept_assignment(offer["id"], driver["id"])
    set_clock("2026-08-03T07:00:00Z")
    board_assignment(offer["id"], driver["id"])
    set_clock("2026-08-03T07:12:00Z")
    complete_assignment(offer["id"], driver["id"])

    report = create_report(zone["id"], variant="FINAL", **PERIOD_SERVICE_DAY)
    report = submit_report(report["id"])
    return {
        "zone": zone,
        "block": block,
        "trip": refresh_trip(trip["id"]),
        "report": report,
    }


# ─── The two variants disagree about scope and about which hours to read ────


class TestVariantScopeDivergence:
    def test_provisional_variant_costs_scheduled_hours_of_open_and_closed_blocks(self):
        """A PROVISIONAL filing costs every in-period block on its scheduled hours and counts assigned trips.

        PRD: "Under the `PROVISIONAL` variant — filed while the period is still running — the block scope is the in-period blocks whose `state` is `SCHEDULED`, `OPEN` or `CLOSED`, and each such block contributes its `scheduled_revenue_hours`."

        Design: Difficulty/dual_variant_calc/subsidy_per_trip_provisional_vs_final_scope_and_hours_diverge
        """
        state = _build_divergent_variant_scope()
        provisional, _final = _file_both_variants(state["zone"]["id"])

        # 4.00 h and 3.00 h of scheduled service are what PROVISIONAL reads.
        assert state["block_1"]["scheduled_revenue_hours"] == pytest.approx(
            4.00, abs=0.01
        )
        assert state["block_2"]["scheduled_revenue_hours"] == pytest.approx(
            3.00, abs=0.01
        )
        assertions.assert_block_state(state["block_1"], "CLOSED")
        assertions.assert_block_state(state["block_2"], "OPEN")

        # The COMPLETED trip and the merely ASSIGNED one are both in trip scope.
        assertions.assert_trip_state(state["trip_1"], "COMPLETED", "CHARGED")
        assertions.assert_trip_state(state["trip_2"], "ASSIGNED", "QUOTED")

        assertions.assert_report_state(provisional, "SUBMITTED")
        assertions.assert_fields(
            provisional,
            variant="PROVISIONAL",
            total_operating_cost_cents=64680,  # 36960 + 27720
            total_trips=2,
            total_fare_revenue_cents=325,
            subsidy_per_trip_cents=32178,  # 64355 / 2 = 32177.5, half up
        )

    def test_final_variant_costs_actual_hours_of_closed_blocks_only(self):
        """A FINAL filing over the same days costs only the CLOSED block on its actual hours and counts only completed trips.

        PRD: "Under the `FINAL` variant — filed once every block in the period is finalised — the block scope is the in-period blocks whose `state` is `CLOSED` and nothing else, and each such block contributes its `actual_revenue_hours`."

        Design: Difficulty/dual_variant_calc/subsidy_per_trip_provisional_vs_final_scope_and_hours_diverge
        """
        state = _build_divergent_variant_scope()
        provisional, final = _file_both_variants(state["zone"]["id"])

        # The CLOSED block ran 06:00Z-07:30Z; the OPEN block earned nothing.
        assert state["block_1"]["actual_revenue_hours"] == pytest.approx(1.50, abs=0.01)
        assert state["block_2"]["actual_revenue_hours"] == pytest.approx(0.00, abs=0.01)

        assertions.assert_report_state(final, "SUBMITTED")
        assertions.assert_fields(
            final,
            variant="FINAL",
            total_operating_cost_cents=13860,  # round_half_up(1.50 * 8250 * 1.12)
            total_trips=1,
            total_fare_revenue_cents=325,
            subsidy_per_trip_cents=13535,  # (13860 - 325) / 1
        )
        # Same zone, same inclusive period, two independently scoped filings.
        assert final["id"] != provisional["id"]


# ─── Operating cost rounds once per block, before the sum ───────────────────


class TestPerBlockOperatingCostRounding:
    def test_operating_cost_rounds_each_block_to_whole_cents_before_summing(self):
        """Two blocks whose exact costs end in .40 cents each round down first, so the total is 27904.

        PRD: "Each vehicle block in scope is costed individually: take that block's revenue hours, multiply by 8250 cents — the operating cost of one revenue hour, that is 82.50 dollars — then multiply by 1.12 to add the twelve percent administrative overhead the agency allows, and round the product half up to whole cents."

        Design: Difficulty/combinatorial_formula/operating_cost_rounds_per_block_before_summing
        """
        state = _build_rounding_order_state()
        report = validate_success(
            _open_report(state["zone"]["id"], "PROVISIONAL", PERIOD_AUGUST), 201
        )
        report = validate_success(_submit(report["id"]))

        # 7236 s and 3636 s of scheduled window, in hours to 2 decimal places.
        assert state["block_a"]["scheduled_revenue_hours"] == pytest.approx(
            2.01, abs=0.01
        )
        assert state["block_b"]["scheduled_revenue_hours"] == pytest.approx(
            1.01, abs=0.01
        )
        assertions.assert_block_state(state["block_a"], "OPEN")
        assertions.assert_block_state(state["block_b"], "SCHEDULED")

        # 18572.40c -> 18572 and 9332.40c -> 9332, summed after rounding.
        assertions.assert_report_state(report, "SUBMITTED")
        assert report["total_operating_cost_cents"] == 27904

    def test_deferred_rounding_total_and_subsidy_per_trip_are_both_excluded(self):
        """Rounding the summed exact costs once would report 27905, which the specification forbids.

        PRD: "Summing the unrounded per-block costs and rounding once at the end produces a different total and is not what this specification requires."

        Design: Difficulty/combinatorial_formula/operating_cost_rounds_per_block_before_summing
        """
        state = _build_rounding_order_state()
        report = validate_success(
            _open_report(state["zone"]["id"], "PROVISIONAL", PERIOD_AUGUST), 201
        )
        report = validate_success(_submit(report["id"]))

        # 27904.80c summed-then-rounded is the wrong answer by exactly one cent.
        assert report["total_operating_cost_cents"] != 27905
        assertions.assert_trip_state(state["trip"], "COMPLETED", "CHARGED")
        assertions.assert_fields(
            report,
            total_trips=1,
            total_fare_revenue_cents=325,
            subsidy_per_trip_cents=27579,  # (27904 - 325) / 1
        )


# ─── The report workflow cycles rather than terminating ────────────────────


class TestAmendmentCycle:
    def test_amend_clears_both_attributions_and_refiling_records_the_new_analyst(self):
        """Amending a certified report bumps the amendment count and clears both attribution fields, and the refiling stamps the second analyst.

        PRD: "A `FinanceAnalyst` may reopen a certified report with a `CERTIFIED → AMENDED` move, which increases `amendment_count` by 1, clears `certified_by_user_id` to null, clears `submitted_by_user_id` to null and advances `version` by 1."

        Design: Difficulty/non_linear_state_machine/subsidy_report_certify_amend_resubmit_recertify_cycle
        """
        state = _build_certified_report_over_empty_day()
        certified = state["report"]
        assertions.assert_report_state(certified, "CERTIFIED")

        amended = validate_success(_amend(certified["id"]))
        assertions.assert_report_state(amended, "AMENDED")
        assertions.assert_fields(
            amended,
            amendment_count=1,
            certified_by_user_id=None,
            submitted_by_user_id=None,
        )
        assertions.assert_version_advanced(certified, amended)

        refiled = validate_success(_submit(amended["id"], FINANCE_ANALYST_2_HEADERS))
        assertions.assert_report_state(refiled, "SUBMITTED")
        assertions.assert_fields(
            refiled,
            submitted_by_user_id=FINANCE_ANALYST_2_ID,
            certified_by_user_id=None,
            rejection_reason=None,
            amendment_count=1,
        )

    def test_recertification_after_amendment_restamps_the_auditor_and_keeps_totals(self):
        """The certify-amend-refile-recertify cycle returns the report to CERTIFIED with the amendment counted and the totals unchanged.

        PRD: "From `AMENDED` the report must be refiled and recertified, which is why the report workflow has no terminal state at all: the cycle `CERTIFIED → AMENDED → SUBMITTED → CERTIFIED` can run as many times as the period needs restating, with `amendment_count` recording how often it has."

        Design: Difficulty/non_linear_state_machine/subsidy_report_certify_amend_resubmit_recertify_cycle
        """
        state = _build_certified_report_over_empty_day()
        report_id = state["report"]["id"]

        validate_success(_amend(report_id))
        validate_success(_submit(report_id, FINANCE_ANALYST_2_HEADERS))
        recertified = validate_success(
            _certify(report_id, note="amended figures accepted")
        )

        assertions.assert_report_state(recertified, "CERTIFIED")
        assertions.assert_fields(
            recertified,
            amendment_count=1,
            certified_by_user_id=AUDITOR_ID,
            submitted_by_user_id=FINANCE_ANALYST_2_ID,
            total_operating_cost_cents=18480,  # round_half_up(2.00 * 8250 * 1.12)
            total_trips=0,
            total_fare_revenue_cents=0,
            subsidy_per_trip_cents=0,
        )
        assert state["block"]["actual_revenue_hours"] == pytest.approx(2.00, abs=0.01)
        assert refresh_report(report_id)["state"] == "CERTIFIED"


# ─── Equivalent service outranks block finalisation on certify ─────────────


class TestCertifyRejectionPrecedence:
    def test_deficient_equivalence_is_reported_before_unfinalised_blocks(self):
        """With both certify preconditions violated at once, the equivalence verdict is the failure the auditor sees.

        PRD: "Similarly, certifying a subsidy report reports `ERR_SEGREGATION_OF_DUTIES` before `ERR_EQUIVALENCE_DEFICIENT`, and `ERR_EQUIVALENCE_DEFICIENT` before `ERR_BLOCKS_NOT_FINALIZED`."

        Design: Difficulty/priority_pair_validation_conflict/equivalence_deficient_priority_30_outranks_blocks_not_finalized_priority_58
        """
        state = _build_deficient_equivalence_state()
        zone = refresh_zone(state["zone"]["id"])

        # Waits of 10 (accessible) against 4 (ambulatory) -> ratio 2.500.
        assert zone["wav_avg_wait_minutes"] == pytest.approx(10.00, abs=0.01)
        assert zone["nonwav_avg_wait_minutes"] == pytest.approx(4.00, abs=0.01)
        assert zone["wav_equivalence_ratio"] == pytest.approx(2.500, abs=0.01)
        assert zone["equivalence_verdict"] == "DEFICIENT"
        # The block is still OPEN, so the finalisation gate is violated too.
        assertions.assert_block_state(
            refresh_block(state["block"]["id"]), "OPEN"
        )

        validate_error(
            _certify(state["report"]["id"], note="first attempt"),
            ApiErrorId.ERR_EQUIVALENCE_DEFICIENT.value,
        )

        unchanged = refresh_report(state["report"]["id"])
        assertions.assert_report_state(unchanged, "SUBMITTED")
        assertions.assert_fields(
            unchanged,
            certified_by_user_id=None,
            submitted_by_user_id=FINANCE_ANALYST_ID,
        )

    def test_clearing_equivalence_at_the_inclusive_ratio_surfaces_the_block_gate(self):
        """A third completed trip drags the ratio to exactly 1.250, which is compliant, so the identical certify now fails on the OPEN block instead.

        PRD: "The threshold is inclusive, so a zone where wheelchair-accessible riders wait exactly a quarter longer than ambulatory riders is still compliant, and one where they wait any more than that is not."

        Design: Difficulty/priority_pair_validation_conflict/equivalence_deficient_priority_30_outranks_blocks_not_finalized_priority_58
        """
        state = _build_deficient_equivalence_state()
        report_id = state["report"]["id"]
        driver_id = state["driver"]["id"]

        validate_error(
            _certify(report_id, note="first attempt"),
            ApiErrorId.ERR_EQUIVALENCE_DEFICIENT.value,
        )

        set_clock("2026-08-03T07:42:00Z")
        board_assignment(state["offer_nonwav_2"]["id"], driver_id)
        set_clock("2026-08-03T07:54:00Z")
        complete_assignment(state["offer_nonwav_2"]["id"], driver_id)

        third = refresh_trip(state["trip_nonwav_2"]["id"])
        assertions.assert_fields(third, wait_minutes=12, ride_minutes=12)

        zone = refresh_zone(state["zone"]["id"])
        assert zone["nonwav_avg_wait_minutes"] == pytest.approx(8.00, abs=0.01)
        assert zone["wav_equivalence_ratio"] == pytest.approx(1.250, abs=0.01)
        assert zone["equivalence_verdict"] == "COMPLIANT"
        assert zone["avg_wait_minutes"] == pytest.approx(8.67, abs=0.01)
        assert zone["avg_ride_minutes"] == pytest.approx(12.00, abs=0.01)
        assert zone["completed_trip_count"] == 3

        validate_error(
            _certify(report_id, note="second attempt"),
            ApiErrorId.ERR_BLOCKS_NOT_FINALIZED.value,
        )

        still_submitted = refresh_report(report_id)
        assertions.assert_report_state(still_submitted, "SUBMITTED")
        assertions.assert_fields(
            still_submitted,
            certified_by_user_id=None,
            submitted_by_user_id=FINANCE_ANALYST_ID,
        )
        assertions.assert_block_state(refresh_block(state["block"]["id"]), "OPEN")


# ─── Boundaries: half-up revenue hours and the zero-trip denominator ───────


class TestRevenueHourAndDenominatorBoundaries:
    def test_actual_revenue_hours_round_half_up_and_drive_the_operating_cost(self):
        """A block open for exactly 2.005 hours settles at 2.01 actual revenue hours, which costs 18572 cents.

        PRD: "On success `state` becomes `CLOSED`, `closed_at` is stamped with the current logical clock reading, and `actual_revenue_hours` is recomputed as the difference between `closed_at` and `opened_at` expressed in hours to 2 decimal places rounded half up."

        Design: Difficulty/boundary_precision_check/zero_trip_denominator_and_half_up_revenue_hours_boundary
        """
        state = _build_zero_trip_closed_block_state()
        report = validate_success(_submit(state["report"]["id"]))

        block = state["block"]
        assertions.assert_block_state(block, "CLOSED")
        assertions.assert_instant_equals(block["closed_at"], "2026-08-03T08:00:18Z")
        assert block["scheduled_revenue_hours"] == pytest.approx(4.00, abs=0.01)
        assert block["actual_revenue_hours"] == pytest.approx(2.01, abs=0.01)
        assert block["boardings_count"] == 0

        # 2.01 * 8250 * 1.12 = 18572.40c; truncating the hours to 2.00 gives 18480.
        assertions.assert_report_state(report, "SUBMITTED")
        assert report["total_operating_cost_cents"] == 18572

    def test_zero_trip_denominator_reports_zero_subsidy_per_trip(self):
        """A period with a costed block but no completed trip reports a subsidy per trip of 0 rather than dividing by zero.

        PRD: "`subsidy_per_trip_cents` is then `total_operating_cost_cents` minus `total_fare_revenue_cents`, divided by `total_trips`, rounded half up to whole cents — and when `total_trips` is 0 it reads 0 rather than being undefined."

        Design: Difficulty/boundary_precision_check/zero_trip_denominator_and_half_up_revenue_hours_boundary
        """
        state = _build_zero_trip_closed_block_state()
        report = validate_success(_submit(state["report"]["id"]))

        assertions.assert_fields(
            report,
            total_trips=0,
            total_fare_revenue_cents=0,
            subsidy_per_trip_cents=0,
        )
        assert report["total_operating_cost_cents"] == 18572

        zone = refresh_zone(state["zone"]["id"])
        assert zone["boardings_per_revenue_hour"] == pytest.approx(0.00, abs=0.01)
        assert zone["avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
        assert zone["avg_ride_minutes"] == pytest.approx(0.00, abs=0.01)
        assert zone["wav_equivalence_ratio"] == pytest.approx(0.000, abs=0.01)
        assert zone["equivalence_verdict"] == "COMPLIANT"


# ─── Certification reads block state; submission freezes the totals ────────


class TestFinalisationGateAndFrozenTotals:
    def test_certify_is_refused_while_an_in_period_block_is_still_open(self):
        """Certification is refused while the period's only block is OPEN, and closing it settles 1.20 actual hours.

        PRD: "Third, **finalisation**: every vehicle block of the report's zone whose `start_utc` falls on a UTC calendar date inside the inclusive reporting period must be in `CLOSED` or `CANCELLED`, and a block still `SCHEDULED` or `OPEN` is rejected with `ERR_BLOCKS_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/certification_gated_on_block_finalization_with_totals_frozen_at_submit
        """
        state = _build_submitted_while_block_open()
        report_id = state["report"]["id"]

        assertions.assert_block_state(refresh_block(state["block"]["id"]), "OPEN")
        validate_error(
            _certify(report_id, note="pre-close attempt"),
            ApiErrorId.ERR_BLOCKS_NOT_FINALIZED.value,
        )

        after_failure = refresh_report(report_id)
        assertions.assert_report_state(after_failure, "SUBMITTED")
        assertions.assert_null_fields(after_failure, "certified_by_user_id")

        closed = close_block(state["block"]["id"])
        assertions.assert_block_state(closed, "CLOSED")
        assert closed["actual_revenue_hours"] == pytest.approx(1.20, abs=0.01)
        assert closed["boardings_count"] == 1

        zone = refresh_zone(state["zone"]["id"])
        assert zone["boardings_per_revenue_hour"] == pytest.approx(0.83, abs=0.01)

    def test_certification_keeps_the_totals_the_submission_froze(self):
        """Certifying after the close succeeds and leaves the totals exactly as the submission computed them, negative subsidy included.

        PRD: "Recomputation on every submission is what makes a provisional report meaningful; the numbers a report carries are always the numbers as of its most recent filing."

        Design: Difficulty/cross_entity_state_dependency/certification_gated_on_block_finalization_with_totals_frozen_at_submit
        """
        state = _build_submitted_while_block_open()
        report_id = state["report"]["id"]

        validate_error(
            _certify(report_id, note="pre-close attempt"),
            ApiErrorId.ERR_BLOCKS_NOT_FINALIZED.value,
        )
        close_block(state["block"]["id"])
        certified = validate_success(_certify(report_id, note="post-close attempt"))

        assertions.assert_report_state(certified, "CERTIFIED")
        assertions.assert_fields(
            certified,
            certified_by_user_id=AUDITOR_ID,
            submitted_by_user_id=FINANCE_ANALYST_ID,
            amendment_count=0,
            total_trips=1,
            total_fare_revenue_cents=325,
            total_operating_cost_cents=0,  # the block was OPEN when this was filed
            subsidy_per_trip_cents=-325,
        )
        assertions.assert_trip_state(state["trip"], "COMPLETED", "CHARGED")
