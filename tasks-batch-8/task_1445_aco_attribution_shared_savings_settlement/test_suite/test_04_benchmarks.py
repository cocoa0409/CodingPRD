"""Benchmark computation: posture gate, OCC, variant duality, risk adjustment."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    add_participant,
    adjudicate,
    assert_benchmark,
    build_period_scenario,
    compute_benchmark,
    create_benchmark_payload,
    create_period,
    current_period_version,
    ingest_claim,
    lock_period,
    open_period,
    run_alignment,
    validate_error,
    validate_success,
)


def _two_beneficiary_locked_period(tax_id):
    """BR (1960, dual+disabled) and BP (1990) each with one adjudicated PART_B
    visit; retrospective run; period locked (records FINAL)."""
    return build_period_scenario(
        tax_id=tax_id,
        beneficiaries=(
            {"medicare_id": "MBI-BV-R", "birth_year": 1960,
             "dual_eligible": True, "disabled": True},
            {"medicare_id": "MBI-BV-P", "birth_year": 1990},
        ),
        claims=(
            {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
             "amount": 20000, "claim_type": "PART_B"},
            {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
             "amount": 20000, "claim_type": "PART_B"},
        ),
        benchmark_variant=None,
        quality_scores=None,
    )


class TestBenchmarkPostureAndOcc:
    def test_benchmark_before_lock_rejected(self, api, admin_headers):
        """PRD §3.4: "Benchmark computation requires the period to be
        `ASSIGNMENT_LOCKED` — a period in any lesser posture rejects the request
        with `ERR_PERIOD_NOT_LOCKED` (HTTP 409)".

        Design: Corner/errors/benchmark_before_lock_rejected
        """
        period = create_period(tax_id="ACO-Z1")
        open_period(period["id"])
        res = api.create_benchmark(
            period["id"],
            create_benchmark_payload(current_period_version(period["id"]), variant="FINAL"),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_LOCKED, expected_status=409)

    def test_stale_version_on_benchmark_create(self, api, admin_headers):
        """PRD §2.6: "If that value does not equal the period's current `version`
        — for example because another writer has since opened or locked the
        period, or has completed a run, benchmark, or settlement of their own —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_version_on_benchmark_create
        """
        period = create_period(tax_id="ACO-X1")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-X1", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        run_alignment(period["id"])
        lock_period(period["id"])
        stale_version = current_period_version(period["id"])
        compute_benchmark(period["id"], variant="PROVISIONAL")  # advances version
        res = api.create_benchmark(
            period["id"],
            create_benchmark_payload(stale_version, variant="FINAL"),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestBenchmarkVariantDuality:
    def test_provisional_benchmark_uses_1030_factor(self, api, admin_headers):
        """PRD §3.4: "The update factor is variant-dependent and is recorded on
        the benchmark as `update_factor_used`: 1.030 for a `PROVISIONAL` variant,
        1.021 for a `FINAL` variant." and "`total_benchmark_cents` is the product
        of `risk_score_sum`, the 100000-cent per-member-per-month base, twelve
        months, and the update factor, rounded half-up once at the very end to
        integer cents."

        Design: Difficulty/dual_variant_calc/benchmark_provisional_vs_final_factor
        """
        ctx = _two_beneficiary_locked_period("ACO-BV")
        benchmark = compute_benchmark(ctx["period"]["id"], variant="PROVISIONAL")
        assert_benchmark(benchmark)
        assert benchmark["update_factor_used"] == pytest.approx(1.03)
        assert benchmark["beneficiary_months"] == 24
        # risk_score_sum 1.40 + 1.00 = 2.40; 2.40 x 100000 x 12 x 1.030
        assert benchmark["risk_score_sum"] == pytest.approx(2.40)
        assert benchmark["total_benchmark_cents"] == 2966400

    def test_final_benchmark_uses_1021_factor_and_differs(self, api, admin_headers):
        """PRD §3.4: "Because both the included population and the update factor
        differ, identical attribution data yields different totals under the two
        variants."

        Design: Difficulty/dual_variant_calc/benchmark_provisional_vs_final_factor
        """
        ctx = _two_beneficiary_locked_period("ACO-BV2")
        provisional = compute_benchmark(ctx["period"]["id"], variant="PROVISIONAL")
        final = compute_benchmark(ctx["period"]["id"], variant="FINAL")
        assert final["update_factor_used"] == pytest.approx(1.021)
        assert final["total_benchmark_cents"] == 2940480
        assert provisional["total_benchmark_cents"] - final["total_benchmark_cents"] == 25920


class TestBenchmarkSupersede:
    def test_benchmark_recreate_supersedes_prior_active(self, api, admin_headers):
        """PRD §3.4: "Each variant keeps at most one `ACTIVE` benchmark per
        period: computing a new benchmark of a variant supersedes the prior
        `ACTIVE` benchmark of that same variant, moving it to `SUPERSEDED`."

        Design: Corner/state_machines/benchmark_recreate_supersedes_prior_active
        """
        period = create_period(tax_id="ACO-S5")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-S5", 1960, dual_eligible=True, disabled=True)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        run_alignment(period["id"])
        lock_period(period["id"])
        first = compute_benchmark(period["id"], variant="PROVISIONAL")
        second = compute_benchmark(period["id"], variant="PROVISIONAL")
        assert second["status"] == "ACTIVE"
        first_after = validate_success(api.get_benchmark(first["id"], admin_headers), 200)
        assert first_after["status"] == "SUPERSEDED"


class TestRiskScoreComponents:
    def test_risk_score_component_sum_with_aged_esrd(self, api, admin_headers):
        """PRD §3.4: "Each attributed beneficiary earns a risk score assembled
        from a base of 1.00, plus 0.25 when `dual_eligible`, plus 0.40 when
        `esrd`, plus 0.15 when `disabled`, plus 0.05 when the beneficiary's age
        at period start — performance start year minus `birth_year` — is at
        least 75."

        Design: Corner/calculations/risk_score_component_sum_with_aged_esrd
        """
        ctx = build_period_scenario(
            tax_id="ACO-C1",
            beneficiaries=(
                {"medicare_id": "MBI-C1", "birth_year": 1950,
                 "dual_eligible": True, "disabled": True, "esrd": True},
            ),
            benchmark_variant=None,
            quality_scores=None,
        )
        benchmark = compute_benchmark(ctx["period"]["id"], variant="FINAL")
        assert benchmark["risk_score_sum"] == pytest.approx(1.85)
        assert benchmark["beneficiary_months"] == 12
        # 1.85 x 100000 x 12 x 1.021, rounded half-up once at the end
        assert benchmark["total_benchmark_cents"] == 2266620
