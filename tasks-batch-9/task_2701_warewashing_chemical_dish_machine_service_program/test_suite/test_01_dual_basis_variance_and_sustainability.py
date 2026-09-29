"""
Two-variant calculations: the variance-review basis and the sustainability basis.

Both pairs of tests hold every input byte-identical and change only the declared
basis, so the divergence they measure can come from nothing but the formula
variant the basis selects.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents,
    assert_four_dp,
    assert_instant_equals,
    assert_pct,
)
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS, AUDITOR_1_HEADERS
from test_helpers.types import (
    BASIS_AS_CALIBRATED,
    BASIS_NAMEPLATE,
    CERT_SANITATION,
    CLASS_OVERUSE,
    CLASS_WITHIN_TOLERANCE,
    REVIEW_DRAFT,
    SUSTAINABILITY_BASIS_RATED,
    SUSTAINABILITY_BASIS_TELEMETRY,
    VERDICT_ADJUSTED,
)

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-09-01T00:00:00Z"


def _consumption_scenario(api):
    """
    3000 racks over August on one DET-100 dispenser whose dose was 8.00 ml until
    an applied calibration on 2026-08-10 raised it to 9.20 ml. One 2-container
    delivery lands 40000 ml inside the window; inventory runs 5000 -> 17000, so
    actual draw-down is 28000 ml.
    """
    base = X.program_base(
        api, technician_overrides={"certification_level": CERT_SANITATION}
    )
    placement = X.installed_placement(api, base, asset_tag="AT-001")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-02T08:00:00Z")
    X.record_delivery(api, base, unit_count=2, delivered_at="2026-08-02T08:00:00Z")

    X.ingest_reading_at_clock(api, placement["id"], "2026-08-05T12:00:00Z", 1000)

    stage = X.visit_in_progress(
        api,
        base,
        placement["id"],
        arrival_instant="2026-08-10T09:00:00Z",
        scheduled_start_at="2026-08-10T09:00:00Z",
        scheduled_end_at="2026-08-10T10:00:00Z",
    )
    record = X.record_calibration(
        api,
        base,
        stage["visit_id"],
        dispenser["id"],
        measured_ppm=1380,
        measured_dose_ml_per_rack=8.00,
        adjusted_dose_ml_per_rack=9.20,
    )
    X.submit_visit(api, base, stage["visit_id"], repair_confirmed=True)
    X.verify_visit(api, stage["visit_id"])

    X.ingest_reading_at_clock(api, placement["id"], "2026-08-20T12:00:00Z", 3000)
    X.set_clock(api, WINDOW_END)

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "record": record,
        }
    )
    return base


def test_nameplate_basis_prices_every_rack_at_the_spec_dose(api):
    """
    NAMEPLATE ignores the dispenser's calibration history: all 3000 racks are
    priced at DET-100's 8.00 ml spec dose for 24000 ml expected, so the 28000 ml
    actually drawn reads as a 16.67 percent overrun.

    PRD §3.7: "Under the `NAMEPLATE` basis, every rack is priced at the
    product's `spec_dose_ml_per_rack`, ignoring the dispenser's calibration
    history altogether."

    Design: Difficulty/dual_variant_calc/variance_basis_nameplate_vs_as_calibrated_diverges
    """
    base = _consumption_scenario(api)

    response = api.create_usage_variance_review(
        F.usage_variance_review_payload(
            base["site_id"],
            base["detergent_id"],
            WINDOW_START,
            WINDOW_END,
            BASIS_NAMEPLATE,
            opening_inventory_ml=5000,
            ending_inventory_ml=17000,
        ),
        AUDITOR_1_HEADERS,
    )
    review = validate_success(response, 201)

    assert review["basis"] == BASIS_NAMEPLATE
    assert review["rack_count_in_period"] == 3000
    assert review["actual_consumption_ml"] == 28000
    assert review["expected_consumption_ml"] == 24000
    assert_pct(review["variance_pct"], 16.67)
    assert review["classification"] == CLASS_OVERUSE
    assert review["status"] == REVIEW_DRAFT


def test_as_calibrated_basis_prices_each_reading_at_the_live_dose(api):
    """
    AS_CALIBRATED splits the same window at the applied calibration: the 1000
    racks before it are priced at 8.00 ml and the 2000 after it at 9.20 ml for
    26400 ml expected — 2400 ml above NAMEPLATE over byte-identical telemetry,
    deliveries and inventory counts, which flips the classification to
    WITHIN_TOLERANCE.

    PRD §3.7: "Under the `AS_CALIBRATED` basis, each individual `DEVICE`
    reading inside the window has its `cycle_delta` priced at the dose that was
    actually in effect at that reading's `reading_at`, which is the
    `adjusted_dose_ml_per_rack` of the applied calibration record on that
    dispenser with the greatest verification instant at or before that moment,
    and, when no applied record precedes the reading, the dispenser's creation
    dose — the `calibrated_dose_ml_per_rack` as it stood at `dose_effective_at`."

    Design: Difficulty/dual_variant_calc/variance_basis_nameplate_vs_as_calibrated_diverges
    """
    base = _consumption_scenario(api)

    nameplate = validate_success(
        api.create_usage_variance_review(
            F.usage_variance_review_payload(
                base["site_id"],
                base["detergent_id"],
                WINDOW_START,
                WINDOW_END,
                BASIS_NAMEPLATE,
                opening_inventory_ml=5000,
                ending_inventory_ml=17000,
            ),
            AUDITOR_1_HEADERS,
        ),
        201,
    )
    as_calibrated = validate_success(
        api.create_usage_variance_review(
            F.usage_variance_review_payload(
                base["site_id"],
                base["detergent_id"],
                WINDOW_START,
                WINDOW_END,
                BASIS_AS_CALIBRATED,
                opening_inventory_ml=5000,
                ending_inventory_ml=17000,
            ),
            AUDITOR_1_HEADERS,
        ),
        201,
    )

    # Shared inputs really are shared.
    assert nameplate["rack_count_in_period"] == as_calibrated["rack_count_in_period"] == 3000
    assert nameplate["actual_consumption_ml"] == as_calibrated["actual_consumption_ml"] == 28000

    assert as_calibrated["expected_consumption_ml"] == 26400
    assert (
        as_calibrated["expected_consumption_ml"]
        - nameplate["expected_consumption_ml"]
        == 2400
    )
    assert_pct(as_calibrated["variance_pct"], 6.06)
    assert as_calibrated["classification"] == CLASS_WITHIN_TOLERANCE
    assert nameplate["classification"] == CLASS_OVERUSE

    # Two DRAFT reviews may cover the identical window; only publication claims one.
    assert nameplate["status"] == REVIEW_DRAFT
    assert as_calibrated["status"] == REVIEW_DRAFT

    # The applied ADJUSTED record is what made the two bases diverge.
    assert base["record"]["calibration_verdict"] == VERDICT_ADJUSTED
    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert dispenser["calibrated_dose_ml_per_rack"] == pytest.approx(9.20, abs=0.01)
    assert dispenser["prior_dose_ml_per_rack"] == pytest.approx(8.00, abs=0.01)
    assert_instant_equals(dispenser["dose_effective_at"], "2026-08-10T09:00:00Z", "dose_effective_at")


def _savings_scenario(api):
    """
    One DT-88 placement washing 3000 racks over August at a steady 20 psi, with
    one 2-container DET-100 delivery worth 19200 cents of chemical spend.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-002")

    X.set_clock(api, "2026-08-02T08:00:00Z")
    delivery = X.record_delivery(
        api, base, unit_count=2, delivered_at="2026-08-02T08:00:00Z"
    )
    assert_cents(delivery["amount_cents"], 19200)

    X.ingest_reading_at_clock(api, placement["id"], "2026-08-05T12:00:00Z", 1000)
    X.ingest_reading_at_clock(api, placement["id"], "2026-08-20T12:00:00Z", 3000)
    X.set_clock(api, WINDOW_END)

    base["placement_id"] = placement["id"]
    return base


def test_rated_basis_credits_the_nameplate_water_per_rack(api):
    """
    RATED prices each rack at DT-88's nameplate 0.74 L, so 3000 racks against a
    1.20 L baseline save 1380.00 L, worth 662 cents, and the six pinned cost
    steps land on a 45262-cent net programme cost.

    PRD §3.9: "Under the `RATED` basis, each placement's effective water per
    rack is simply its machine model's `rated_water_l_per_rack`, so savings
    depend only on rack counts."

    Design: Difficulty/dual_variant_calc/sustainability_basis_rated_vs_telemetry_measured_diverges
    """
    base = _savings_scenario(api)

    report = validate_success(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(WINDOW_START, WINDOW_END, SUSTAINABILITY_BASIS_RATED),
        )
    )

    assert report["rack_count"] == 3000
    assert report["water_saved_l"] == pytest.approx(1380.00, abs=0.01)
    assert report["energy_saved_kwh"] == pytest.approx(630.00, abs=0.01)
    assert_cents(report["water_savings_cents"], 662)
    assert_cents(report["energy_savings_cents"], 8820)
    assert_cents(report["gross_savings_cents"], 9482)
    assert_cents(report["chemical_spend_cents"], 19200)
    assert_cents(report["gross_program_cost_cents"], 44200)
    assert report["service_fee_rate"] == pytest.approx(0.08, abs=1e-9)
    assert_cents(report["service_fee_cents"], 1536)
    assert_cents(report["sustainability_credit_cents"], 474)
    assert_cents(report["net_program_cost_cents"], 45262)
    assert_pct(report["goal_attainment_pct"], 0.28)


def test_telemetry_measured_basis_inflates_water_by_the_pressure_factor(api):
    """
    TELEMETRY_MEASURED multiplies the same nameplate litres by
    round_half_up(20 / 15, 4) = 1.3333, so the same 3000 racks save only
    640.074 L and 307 cents; energy is untouched, the credit shrinks to 456 and
    the net programme cost rises by 18 cents. Neither read mutates anything.

    PRD §3.9: "Under `TELEMETRY_MEASURED`, that nameplate figure is inflated by
    an observed pressure factor: average the `rinse_pressure_psi` of the
    placement's `DEVICE` readings inside the window, divide by the model's
    `min_rinse_pressure_psi`, and round half up to four decimal places; when the
    placement has no `DEVICE` reading inside the window at all, the factor is
    exactly 1.0000."

    Design: Difficulty/dual_variant_calc/sustainability_basis_rated_vs_telemetry_measured_diverges
    """
    base = _savings_scenario(api)
    site_version_before = X.site_version(api, base["site_id"])

    rated = validate_success(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(WINDOW_START, WINDOW_END, SUSTAINABILITY_BASIS_RATED),
        )
    )
    measured = validate_success(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(WINDOW_START, WINDOW_END, SUSTAINABILITY_BASIS_TELEMETRY),
        )
    )

    assert measured["rack_count"] == rated["rack_count"] == 3000
    assert measured["water_saved_l"] == pytest.approx(640.074, abs=0.001)
    assert_four_dp(round(measured["water_saved_l"], 4))
    assert_cents(measured["water_savings_cents"], 307)
    # The pressure factor touches water only.
    assert_cents(measured["energy_savings_cents"], 8820)
    assert_cents(measured["gross_savings_cents"], 9127)
    assert_cents(measured["sustainability_credit_cents"], 456)
    assert_cents(measured["net_program_cost_cents"], 45280)
    assert_pct(measured["goal_attainment_pct"], 0.13)

    assert rated["water_saved_l"] - measured["water_saved_l"] == pytest.approx(
        739.926, abs=0.001
    )
    assert (
        measured["net_program_cost_cents"] - rated["net_program_cost_cents"] == 18
    )

    # "They persist nothing, mutate no state and increment no version."
    assert X.site_version(api, base["site_id"]) == site_version_before
