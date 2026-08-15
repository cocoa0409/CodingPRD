"""Interim estimate variants, reserve accrual, publish supersession, report OCC."""
from test_helpers import (
    ACTUARY, ApiErrorId, CLOCK_INTERIM, CLOCK_RECONCILE, CLOCK_WINDOW_PAST,
    INTERIM_RESERVE_ACCRUAL_CENTS, QUALITY, build_pipeline,
    create_interim_report_payload, finalize_settlement, get_year,
    make_interim_report, make_settlement, mark_year_settled, set_clock,
    setup_org, single_member_journey, validate_error, validate_success,
    year_version,
)


def _two_member_measuring(org, *, contract_overrides, claims, quality_lock=False):
    return build_pipeline(
        org, stage="MEASURING",
        claim_specs=claims,
        quality_specs=[("HBA1C", 350, 1000), ("MAMMO", 50, 1000)],
        quality_lock=quality_lock,
        contract_overrides=contract_overrides,
    )


def test_interim_estimate_annualization_authoritative(api):
    """PRD §3.9: "The **annualization** variant, stored on `est_actual_annualization_cents`, is the YTD total multiplied by 12 and divided by `months_elapsed`, rounded half-up. The **completion-factor** variant, stored on `est_actual_completion_cents`, is the YTD total multiplied by 1000 and divided by a per-month completion factor in milli, rounded half-up; the completion factors by month are: 150 for month 1, 320 for month 2, 480 for month 3, 620 for month 4, 740 for month 5, 850 for month 6, 910 for month 7, 950 for month 8, 970 for month 9, 985 for month 10, and 995 for month 11."
    PRD §3.9: "The contract's `estimate_method` selects which of the two variants is authoritative: `ANNUALIZATION` selects the annualization variant, `COMPLETION_FACTOR` selects the completion-factor variant."

    Design: Difficulty/dual_variant_calc/interim_estimate_annualization_vs_completion_factor_divergence
    """
    org = setup_org()
    pipe = _two_member_measuring(
        org,
        contract_overrides={
            "estimate_method": "ANNUALIZATION", "savings_cap_bp": 5000, "contract_ref": "C-A",
        },
        claims=[{"member": 0, "ref": "CL-A1", "service_date": "2026-02-10",
                 "amount": 200000, "pay_clock": "2026-03-01T00:00:00Z"}],
    )
    report = make_interim_report(pipe["year"]["id"], months_elapsed=6)
    # ytd = 200000: annualization round(200000*12/6) = 400000;
    # completion round(200000*1000/850) = 235294.
    assert report["est_actual_annualization_cents"] == 400000
    assert report["est_actual_completion_cents"] == 235294
    # ANNUALIZATION authoritative: gross 1,400,000; rate 7777 >= MSR 200;
    # shared min(700000, cap 900000) = 700000; interim composite 30 -> mult 5000;
    # est_net = 350000 + round(10000*0.5) = 355000; reserve = round(355000*6/12).
    assert report["est_net_payable_cents"] == 355000
    assert report["reserve_accrual_cents"] == 177500


def test_interim_estimate_completion_factor_diverges(api):
    """PRD §3.9: "The contract's `estimate_method` selects which of the two variants is authoritative: `ANNUALIZATION` selects the annualization variant, `COMPLETION_FACTOR` selects the completion-factor variant. Identical YTD data yields different estimates under the two variants."
    PRD §3.9: "The reserve accrual, stored on `reserve_accrual_cents`, is the round-half-up of the positive part of the estimated net payable multiplied by `months_elapsed` and divided by 12. If the estimated net payable is zero or negative, the reserve accrual is zero."

    Design: Difficulty/dual_variant_calc/interim_estimate_annualization_vs_completion_factor_divergence
    """
    org = setup_org()
    claims = [{"member": 0, "ref": "CL-1", "service_date": "2026-02-10",
               "amount": 200000, "pay_clock": "2026-03-01T00:00:00Z"}]
    pipe_a = _two_member_measuring(
        org,
        contract_overrides={
            "estimate_method": "ANNUALIZATION", "savings_cap_bp": 5000, "contract_ref": "C-A",
        },
        claims=claims,
    )
    pipe_b = _two_member_measuring(
        org,
        contract_overrides={
            "estimate_method": "COMPLETION_FACTOR", "savings_cap_bp": 800, "contract_ref": "C-B",
        },
        claims=[dict(c, ref="CL-1") for c in claims],
    )
    report_a = make_interim_report(pipe_a["year"]["id"], months_elapsed=6)
    report_b = make_interim_report(pipe_b["year"]["id"], months_elapsed=6)

    # Both variants are computed side by side on both reports.
    assert report_b["est_actual_annualization_cents"] == 400000
    assert report_b["est_actual_completion_cents"] == 235294
    # COMPLETION_FACTOR authoritative: est_actual 235294; gross 1,564,706;
    # rate 8692 >= 200; uncapped round(1564706*0.5) = 782353 but the cap
    # round(1800000*800/10000) = 144000 binds; est_net = round(144000*0.5)
    # + round(10000*0.5) = 72000 + 5000 = 77000; reserve round(77000*6/12).
    assert report_b["est_net_payable_cents"] == 77000
    assert report_b["reserve_accrual_cents"] == 38500
    assert report_a["est_net_payable_cents"] == 355000
    assert report_a["est_net_payable_cents"] != report_b["est_net_payable_cents"], (
        "identical YTD data must diverge under the two estimate methods"
    )


def test_composite_weighted_rounding_visible_in_interim_estimate(api):
    """PRD §3.10: "Otherwise the composite, stored on `quality_composite_points`, is the round-half-up of the numerator multiplied by 100 and divided by nine times the denominator, yielding an integer in 0..100."
    PRD §3.10: "If the composite is greater than or equal to the `quality_gate_floor_points` but below excellence, the multiplier is 5000 plus the round-half-up of the composite-minus-floor, multiplied by 5000, divided by the excellence-minus-floor gap."

    Design: Corner/calculations/composite_weighted_rounding_visible_in_interim_estimate
    """
    org = setup_org()
    pipe = build_pipeline(
        org, stage="MEASURING",
        claim_specs=[{"member": 0, "ref": "CL-1", "service_date": "2026-02-10",
                      "amount": 200000, "pay_clock": "2026-03-01T00:00:00Z"}],
        quality_specs=[("HBA1C", 350, 1000), ("MAMMO", 150, 1000)],
        quality_lock=False,
    )
    report = make_interim_report(pipe["year"]["id"], months_elapsed=6)
    # Interim composite: HBA1C 3 pts (w9000) + MAMMO 1 pt (w1000), both
    # VALIDATED: round_half_up(28000*100/(9*10000)) = 31 -> sliding multiplier
    # 5000 + round(1*5000/50) = 5100. Shared = min(700000, cap 180000) = 180000.
    # est_net = round(180000*0.51) + round(10000*0.51) = 91800 + 5100.
    assert report["est_net_payable_cents"] == 96900
    assert report["reserve_accrual_cents"] == 48450


def test_interim_publish_superseded_rejected(api, actuary_analyst_headers):
    """PRD §3.9: "A new report's `report_status` is created as `DRAFT`, the report is assigned a `report_seq` one higher than the previous report of the year (starting at 1), and its creation supersedes any prior `DRAFT` report of the same year (that report moves `DRAFT → SUPERSEDED`)."
    PRD §3.9: "Publication (`DRAFT → PUBLISHED`) is permitted only while the year is in `MEASURING` or `RECONCILING` (`ERR_YEAR_NOT_MEASURING`)."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Corner/state_machines/interim_publish_superseded_rejected
    """
    pipe = single_member_journey(stage="MEASURING", quality_lock=False)
    year_id = pipe["year"]["id"]

    report1 = make_interim_report(year_id, months_elapsed=6)
    report2 = make_interim_report(year_id, months_elapsed=6)
    assert report2["report_seq"] == 2

    stale_publish = api.publish_interim_report(report1["id"], actuary_analyst_headers)
    validate_error(stale_publish, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    published = api.publish_interim_report(report2["id"], actuary_analyst_headers)
    assert validate_success(published)["report_status"] == "PUBLISHED"
    reread1 = validate_success(api.get_interim_report(report1["id"], actuary_analyst_headers))
    assert reread1["report_status"] == "SUPERSEDED"


def test_interim_variant_input_filtering_changes_estimate(api, quality_analyst_headers):
    """PRD §3.9: "The quality gate multiplier is applied using the **interim** variant of the composite, which includes results in `VALIDATED` as well as `LOCKED`."
    PRD §3.10: "The official variant uses only `LOCKED` results; the interim variant used by §3.9 includes both `VALIDATED` and `LOCKED` results, so identical measure data can yield a different composite under the two variants whenever a result is validated but not yet locked."
    PRD §3.10: "If the denominator is zero — no locked results, or all weights somehow zero — the composite is zero."

    Design: Corner/complexity_layers/interim_variant_input_filtering_changes_estimate
    """
    org = setup_org()
    pipe = build_pipeline(
        org, stage="MEASURING",
        claim_specs=[{"member": 0, "ref": "CL-1", "service_date": "2026-02-10",
                      "amount": 200000, "pay_clock": "2026-03-01T00:00:00Z"}],
        quality_specs=[("HBA1C", 350, 1000)],
        quality_lock=False,
    )
    year_id = pipe["year"]["id"]
    result = pipe["quality"][0]

    report_a = make_interim_report(year_id, months_elapsed=6)
    # HBA1C VALIDATED is inside the interim input set: composite 33 (single
    # result in set) -> multiplier 5300; shared = min(700000, 180000) = 180000;
    # est_net = round(180000*0.53) + round(10000*0.53) = 95400 + 5300.
    assert report_a["est_net_payable_cents"] == 100700
    assert report_a["reserve_accrual_cents"] == 50350

    validate_success(
        api.return_quality_result_for_correction(result["id"], quality_analyst_headers)
    )
    report_b = make_interim_report(year_id, months_elapsed=6)
    # Back in REPORTED the result leaves the interim input set: composite 0 ->
    # multiplier 0 -> no estimated net, no reserve, from identical claims.
    assert report_b["est_net_payable_cents"] == 0
    assert report_b["reserve_accrual_cents"] == 0

    reread_a = validate_success(api.get_interim_report(report_a["id"], ACTUARY))
    assert reread_a["report_status"] == "SUPERSEDED"


def test_reserve_accrual_released_on_mark_settled(api):
    """PRD §3.9: "Publishing supersedes any other `PUBLISHED` report of the year (that report moves `PUBLISHED → SUPERSEDED`), posts the new report's `reserve_accrual_cents` onto the year's `accrued_reserve_cents`, and stamps `published_on` with the logical clock date."
    PRD §3.4: "The other exit is taken by a `SettlementOfficer` who marks the year settled (`RECONCILING → SETTLED`); this requires a settlement in `FINALIZED`, `AUTHORIZED`, or `DISTRIBUTED` (`ERR_SETTLEMENT_NOT_FINAL` otherwise) and requires the logical clock date to be strictly greater than the settlement's `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_OPEN` otherwise). Marking settled releases the reserve: `accrued_reserve_cents` is set to 0."

    Design: Corner/calculations/reserve_accrual_released_on_mark_settled
    """
    pipe = single_member_journey(
        stage="FINALIZED",
        claim_amounts=[("2026-02-10", 400000), ("2026-03-20", 100000)],
        interim_months=6,
    )
    year_id = pipe["year"]["id"]
    year = get_year(year_id)
    assert year["accrued_reserve_cents"] == INTERIM_RESERVE_ACCRUAL_CENTS, (
        "publishing posts the reserve accrual onto the year"
    )

    settled = mark_year_settled(year_id)
    assert settled["year_status"] == "SETTLED"
    assert settled["accrued_reserve_cents"] == 0, (
        "mark-settled releases the reserve against the finalized settlement"
    )


def test_occ_interim_report_stale_version_rejected(api, actuary_analyst_headers):
    """PRD §2.7: "If the parent's current `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Creating an interim report against a `PerformanceYear` requires `expected_performance_year_version` matching that year's current `version`. The guarded endpoint is the interim-report create."
    PRD §3.9: "A new report's `report_status` is created as `DRAFT`, the report is assigned a `report_seq` one higher than the previous report of the year (starting at 1), and its creation supersedes any prior `DRAFT` report of the same year (that report moves `DRAFT → SUPERSEDED`)."

    Design: Corner/complexity_layers/occ_interim_report_stale_version_rejected
    """
    pipe = single_member_journey(stage="MEASURING", quality_lock=False)
    year_id = pipe["year"]["id"]
    set_clock(CLOCK_INTERIM)

    observed = year_version(year_id)
    first = api.create_interim_report(
        create_interim_report_payload(year_id, observed, months_elapsed=7), ACTUARY
    )
    report1 = validate_success(first, 201)
    assert report1["report_seq"] == 1

    stale = api.create_interim_report(
        create_interim_report_payload(year_id, observed, months_elapsed=7), ACTUARY
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = year_version(year_id)
    second = api.create_interim_report(
        create_interim_report_payload(year_id, fresh, months_elapsed=7), ACTUARY
    )
    report2 = validate_success(second, 201)
    assert report2["report_seq"] == 2

    reread = validate_success(api.get_interim_report(report1["id"], actuary_analyst_headers))
    assert reread["report_status"] == "SUPERSEDED"
