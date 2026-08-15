"""Attribution runs, rollup math, risk-model pinning, and run-level OCC."""
from test_helpers import (
    ApiErrorId, add_record, build_pipeline, compute_run, create_risk_score_payload,
    get_year, lock_year_attribution, make_draft_run, make_locked_run, make_risk_score,
    setup_org, lock_run, validate_error, validate_success,
)
from test_helpers import (
    ATTRIBUTION, CLOCK_START, create_attribution_run_payload, get_success_data,
    set_clock, year_version,
)


def test_risk_model_prospective_variant_drives_benchmark(api):
    """PRD §3.6: "The same weighted-mean formula is in fact evaluated twice — once over `FINAL` scores with `model_used` `PROSPECTIVE` and once over `FINAL` scores with `model_used` `CONCURRENT` — and the contract's pinned `risk_model` selects which variant drives `benchmark_cost_cents`."
    PRD §3.6: "The year's `risk_adjustment_factor_milli` is the floor of the weighted mean — the sum over the population of each record's `member_months` multiplied by its authoritative `score_milli`, divided by the sum of `member_months`, with floor division to an integer milli."

    Design: Difficulty/dual_variant_calc/risk_model_prospective_vs_concurrent_divergence
    """
    org = setup_org()
    pipe = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        contract_overrides={"risk_model": "PROSPECTIVE", "contract_ref": "C-P"},
        risk_scores=[
            {"member": 0, "model": "PROSPECTIVE", "score": 1250},
            {"member": 1, "model": "PROSPECTIVE", "score": 800},
        ],
    )
    year = pipe["year"]
    # floor((12*1250 + 6*800) / 18) = floor(1100.0) = 1100
    assert year["risk_adjustment_factor_milli"] == 1100
    # round(100000*12*1250/1000) + round(100000*6*800/1000) = 1500000 + 480000
    assert year["benchmark_cost_cents"] == 1980000
    assert year["total_member_months"] == 18


def test_risk_model_concurrent_variant_diverges(api):
    """PRD §3.6: "The same weighted-mean formula is in fact evaluated twice — once over `FINAL` scores with `model_used` `PROSPECTIVE` and once over `FINAL` scores with `model_used` `CONCURRENT` — and the contract's pinned `risk_model` selects which variant drives `benchmark_cost_cents`. The other variant is observational only and is used in reporting and in renewal analysis. Identical populations can yield different benchmarks under the two variants because the underlying score sets differ."
    PRD §3.6: "The year's `benchmark_cost_cents` is the sum over the population of a per-record term: the contract's `benchmark_pmpm_cents` multiplied by the record's `member_months` multiplied by the record's authoritative `score_milli`, divided by 1000, rounded half-up to a whole cent per record, and only then summed."

    Design: Difficulty/dual_variant_calc/risk_model_prospective_vs_concurrent_divergence
    """
    org = setup_org()
    pipe_p = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        contract_overrides={"risk_model": "PROSPECTIVE", "contract_ref": "C-P"},
        risk_scores=[
            {"member": 0, "model": "PROSPECTIVE", "score": 1250},
            {"member": 1, "model": "PROSPECTIVE", "score": 800},
        ],
    )
    pipe_c = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        contract_overrides={"risk_model": "CONCURRENT", "contract_ref": "C-C"},
        risk_scores=[
            {"member": 0, "model": "CONCURRENT", "score": 1100},
            {"member": 1, "model": "CONCURRENT", "score": 900},
        ],
    )
    yp, yc = pipe_p["year"], pipe_c["year"]
    # CONCURRENT: floor((12*1100 + 6*900) / 18) = floor(1033.33) = 1033
    assert yc["risk_adjustment_factor_milli"] == 1033
    # per-record: round(100000*12*1100/1000) + round(100000*6*900/1000)
    #           = 1320000 + 540000 = 1860000
    assert yc["benchmark_cost_cents"] == 1860000
    assert yp["benchmark_cost_cents"] == 1980000
    assert yp["benchmark_cost_cents"] != yc["benchmark_cost_cents"], (
        "identical population and score rows must diverge under the two pinned models"
    )


def test_attribution_exclude_reinstate_member_months_conserved(api, attribution_analyst_headers):
    """PRD §3.5: "Exclusion triggers a two-link cascade: first, the year's `total_member_months` and `benchmark_cost_cents` are recomputed without this record; second, the year's settlement, if it is in `PROVISIONAL` or `FINALIZED`, has its `needs_recompute` set to `true` — this is the serialization point between attribution edits and downstream settlement."
    PRD §3.5: "Reinstatement restores the record and recomputes the year rollups with the record back in scope; the compensating invariant is that an exclude followed by a reinstate leaves `total_member_months` identical to its pre-exclude value."

    Design: Difficulty/compensating_invariant/attribution_exclude_reinstate_member_months_conserved
    """
    org = setup_org()
    pipe = build_pipeline(org, stage="ATTRIBUTION_LOCKED")
    year_id = pipe["year"]["id"]
    rec_m1 = pipe["records"][0]

    assert pipe["year"]["total_member_months"] == 18
    assert pipe["year"]["benchmark_cost_cents"] == 1800000

    excluded = api.exclude_attribution_record(rec_m1["id"], attribution_analyst_headers)
    assert validate_success(excluded)["record_status"] == "EXCLUDED"
    year = get_year(year_id)
    assert year["total_member_months"] == 6, "excluding M1 (12 mm) leaves only M2's 6"
    assert year["benchmark_cost_cents"] == 600000

    restored = api.reinstate_attribution_record(rec_m1["id"], attribution_analyst_headers)
    assert validate_success(restored)["record_status"] == "CONFIRMED"
    year = get_year(year_id)
    assert year["total_member_months"] == 18, "exclude+reinstate conserves member-months"
    assert year["benchmark_cost_cents"] == 1800000


def test_attribution_exclude_half_year_member_then_reinstate(api, attribution_analyst_headers):
    """PRD §3.5: "Exclusion triggers a two-link cascade: first, the year's `total_member_months` and `benchmark_cost_cents` are recomputed without this record; second, the year's settlement, if it is in `PROVISIONAL` or `FINALIZED`, has its `needs_recompute` set to `true` — this is the serialization point between attribution edits and downstream settlement."
    PRD §3.5: "Reinstatement restores the record and recomputes the year rollups with the record back in scope; the compensating invariant is that an exclude followed by a reinstate leaves `total_member_months` identical to its pre-exclude value."

    Design: Difficulty/compensating_invariant/attribution_exclude_reinstate_member_months_conserved
    """
    org = setup_org()
    pipe = build_pipeline(org, stage="ATTRIBUTION_LOCKED")
    year_id = pipe["year"]["id"]
    rec_m2 = pipe["records"][1]

    validate_success(api.exclude_attribution_record(rec_m2["id"], attribution_analyst_headers))
    year = get_year(year_id)
    assert year["total_member_months"] == 12, "excluding M2 (6 mm) leaves only M1's 12"
    assert year["benchmark_cost_cents"] == 1200000

    validate_success(api.reinstate_attribution_record(rec_m2["id"], attribution_analyst_headers))
    year = get_year(year_id)
    assert year["total_member_months"] == 18
    assert year["benchmark_cost_cents"] == 1800000


def test_year_lock_attribution_without_locked_run_rejected(api, payer_admin_headers):
    """PRD §3.4: "From `ATTRIBUTION_OPEN` the admin locks attribution (`ATTRIBUTION_OPEN → ATTRIBUTION_LOCKED`); this requires exactly one `AttributionRun` of the year to be in `LOCKED` status (`ERR_NO_LOCKED_ATTRIBUTION_RUN` if there is none; the run lock itself enforces at-most-one)."

    Design: Corner/state_machines/year_lock_attribution_without_locked_run_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="OPEN")
    year_id = pipe["year"]["id"]
    run = make_draft_run(year_id)
    add_record(run["id"], org["members"][0]["id"], org["practices"][0]["id"])
    compute_run(run["id"])

    resp = api.lock_attribution(year_id, payer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKED_ATTRIBUTION_RUN)
    year = get_year(year_id)
    assert year["year_status"] == "ATTRIBUTION_OPEN"
    assert year["locked_run_id"] is None


def test_attribution_run_second_lock_rejected(api, attribution_analyst_headers):
    """PRD §3.5: "Locking requires the year to be in `ATTRIBUTION_OPEN` (`ERR_YEAR_NOT_OPEN`) and requires that no other run of the same year is currently in `LOCKED` (`ERR_RUN_ALREADY_LOCKED`)."
    PRD §3.5: "A `LOCKED` run is not superseded by run creation; only the reopen-attribution cascade of §3.4 moves a `LOCKED` run to `SUPERSEDED`."

    Design: Corner/state_machines/attribution_run_second_lock_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="RUN_LOCKED")
    year_id = pipe["year"]["id"]
    run_a = pipe["run"]
    assert run_a["run_status"] == "LOCKED"

    run_b = make_draft_run(year_id, run_label="R-2")
    # Creating run B must not supersede the LOCKED run A.
    reread_a = validate_success(api.get_attribution_run(run_a["id"], attribution_analyst_headers))
    assert reread_a["run_status"] == "LOCKED"

    compute_run(run_b["id"])
    resp = api.lock_attribution_run(run_b["id"], attribution_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_RUN_ALREADY_LOCKED)
    reread_a = validate_success(api.get_attribution_run(run_a["id"], attribution_analyst_headers))
    assert reread_a["run_status"] == "LOCKED"


def test_run_lock_does_not_mutate_year_until_lock_attribution(api, payer_admin_headers):
    """PRD §3.4: "The side effect is significant: the year records the run as its `locked_run_id`, then recomputes `total_member_months`, `risk_adjustment_factor_milli`, and `benchmark_cost_cents` per the attribution rollup described in §3.6."
    PRD §3.5: "The analyst then locks the run (`COMPUTED → LOCKED`). Locking requires the year to be in `ATTRIBUTION_OPEN` (`ERR_YEAR_NOT_OPEN`) and requires that no other run of the same year is currently in `LOCKED` (`ERR_RUN_ALREADY_LOCKED`)."

    Design: Corner/endpoints/run_lock_does_not_mutate_year_until_lock_attribution
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="RUN_LOCKED")
    year_id = pipe["year"]["id"]

    year = get_year(year_id)
    assert year["year_status"] == "ATTRIBUTION_OPEN"
    assert year["locked_run_id"] is None
    assert year["total_member_months"] == 0, "run lock alone must not populate rollups"

    locked = api.lock_attribution(year_id, payer_admin_headers)
    year = validate_success(locked)
    assert year["year_status"] == "ATTRIBUTION_LOCKED"
    assert year["locked_run_id"] == pipe["run"]["id"]
    assert year["total_member_months"] == 12
    assert year["benchmark_cost_cents"] == 1200000


def test_raf_floor_and_default_score_fallback(api):
    """PRD §3.6: "For each record, the member's authoritative risk score is the `FINAL` `RiskScore` whose `model_used` equals the contract's pinned `risk_model`; if no such score exists, the default of 1000 milli is used."
    PRD §3.6: "The year's `risk_adjustment_factor_milli` is the floor of the weighted mean — the sum over the population of each record's `member_months` multiplied by its authoritative `score_milli`, divided by the sum of `member_months`, with floor division to an integer milli."

    Design: Corner/calculations/raf_floor_and_default_score_fallback
    """
    org = setup_org()
    pipe = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        risk_scores=[
            {"member": 0, "model": "PROSPECTIVE", "score": 1250, "finalize": True},
            {"member": 1, "model": "PROSPECTIVE", "score": 9999, "finalize": False},
        ],
    )
    year = pipe["year"]
    # M2's PRELIMINARY 9999 is ignored; default 1000 applies.
    # floor((12*1250 + 6*1000) / 18) = floor(21000/18) = floor(1166.67) = 1166
    assert year["risk_adjustment_factor_milli"] == 1166
    # round(100000*12*1250/1000) + round(100000*6*1000/1000) = 1500000 + 600000
    assert year["benchmark_cost_cents"] == 2100000


def test_occ_attribution_run_stale_version_rejected(api, attribution_analyst_headers):
    """PRD §2.7: "If the parent's current `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Creating an attribution run against a `PerformanceYear` requires `expected_performance_year_version` matching that year's current `version`. The guarded endpoint is the attribution-run create nested under the year."
    PRD §3.5: "Creating a new run supersedes the previous run: any prior run of the same year in `DRAFT` is moved to `SUPERSEDED` (a `DRAFT → SUPERSEDED` transition), and any prior run in `COMPUTED` is moved to `SUPERSEDED` (a `COMPUTED → SUPERSEDED` transition); records of a superseded run remain queryable but never again drive rollups."

    Design: Corner/complexity_layers/occ_attribution_run_stale_version_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="OPEN")
    year_id = pipe["year"]["id"]

    observed = year_version(year_id)
    first = api.create_attribution_run(
        year_id, create_attribution_run_payload(observed, run_label="R-1"), attribution_analyst_headers
    )
    run1 = validate_success(first, 201)
    assert run1["run_seq"] == 1

    stale = api.create_attribution_run(
        year_id, create_attribution_run_payload(observed, run_label="R-2"), attribution_analyst_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = year_version(year_id)
    second = api.create_attribution_run(
        year_id, create_attribution_run_payload(fresh, run_label="R-2"), attribution_analyst_headers
    )
    run2 = validate_success(second, 201)
    assert run2["run_seq"] == 2, "run_seq is one more than the highest existing run_seq"

    reread = validate_success(api.get_attribution_run(run1["id"], attribution_analyst_headers))
    assert reread["run_status"] == "SUPERSEDED"


def test_risk_model_mismatch_rejected(api, actuary_analyst_headers):
    """PRD §2.11: "Any subsequent attempt to ingest a `RiskScore` whose `model_used` differs from the pinned `risk_model` is rejected with `ERR_RISK_MODEL_MISMATCH`."
    PRD §2.11: "When a contract transitions from `DRAFT` to `ACTIVE`, its `risk_model` becomes immutable: there is no endpoint that modifies it."

    Design: Corner/errors/risk_model_mismatch_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="SETUP")
    resp = api.create_risk_score(
        create_risk_score_payload(
            org["members"][0]["id"], pipe["year"]["id"],
            model_used="CONCURRENT", score_milli=1100,
        ),
        actuary_analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RISK_MODEL_MISMATCH)
