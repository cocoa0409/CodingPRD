"""Salvage batches and certified tonnage: weigh cascade, dual tonnage ledgers,
quarantine compensation cycle (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_in_progress_job,
    create_category,
    create_manifested_batch,
    create_report,
    get_success_data,
    set_clock,
    setup_job_with_weighed_batch,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_hazmat_technician_headers

COORD = TEST_USERS["crew_coordinator_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / job_tonnage_estimated_vs_certified
# ---------------------------------------------------------------------------

class TestJobTonnageEstimatedVsCertified:
    def test_batch_weigh_computes_diverted_weight(self, api):
        """PRD §3.6: "First, the batch lands in `WEIGHED`, its `diverted_weight_lbs`
        is computed as the scale weight minus the contamination weight, `weighed_at`
        is stamped from the logical clock, and `report_period` is derived as the
        year-and-month (`YYYY-MM`) of that timestamp, staying empty until the batch
        is weighed."

        Design: Difficulty/dual_variant_calc/job_tonnage_estimated_vs_certified
        """
        ctx = create_in_progress_job(start="2026-06-10T08:00:00Z", end="2026-06-10T16:00:00Z",
                                     title="Job A", quoted_fee_cents=200000)
        category = create_category(code="LUMBER", display_name="Lumber",
                                   pricing_model="PER_SQFT", base_rate_cents=200)
        batch = create_manifested_batch(ctx["job"]["id"], category["id"],
                                        estimated_weight_lbs=500)
        batch = validate_success(api.weigh_batch(
            batch["id"], {"scale_weight_lbs": 480, "contamination_weight_lbs": 30}, COORD))
        assert batch["status"] == "WEIGHED"
        assert batch["diverted_weight_lbs"] == 450, (
            f"diverted = 480 - 30 = 450, got {batch['diverted_weight_lbs']}")

    def test_job_tonnage_estimated_and_certified_diverge(self, api):
        """PRD §3.6: "The estimated figure, `estimated_diverted_weight_lbs`, sums
        `estimated_weight_lbs` over the job's batches in `MANIFESTED`, `WEIGHED`,
        `QUARANTINED`, or `SORTED` — every batch except those `DISPOSED_HAZARD`. The
        certified figure, `certified_diverted_weight_lbs`, sums `diverted_weight_lbs`
        over the job's batches in `WEIGHED` or `SORTED` whose category counts toward
        diversion (`divertible`); the same job and the same batches therefore yield
        different numbers whenever estimates differ from scale weights or
        contamination exists."

        Design: Difficulty/dual_variant_calc/job_tonnage_estimated_vs_certified
        """
        ctx = create_in_progress_job(start="2026-06-10T08:00:00Z", end="2026-06-10T16:00:00Z",
                                     title="Job A", quoted_fee_cents=200000)
        category = create_category(code="LUMBER", display_name="Lumber",
                                   pricing_model="PER_SQFT", base_rate_cents=200)
        batch = create_manifested_batch(ctx["job"]["id"], category["id"],
                                        estimated_weight_lbs=500)
        validate_success(api.weigh_batch(
            batch["id"], {"scale_weight_lbs": 480, "contamination_weight_lbs": 30}, COORD))
        job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
        assert job["estimated_diverted_weight_lbs"] == 500, (
            f"estimated variant sums manifest estimates: {job['estimated_diverted_weight_lbs']}")
        assert job["certified_diverted_weight_lbs"] == 450, (
            f"certified variant sums scale-minus-contamination: {job['certified_diverted_weight_lbs']}")


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / weigh_cascade_batch_job_report
# ---------------------------------------------------------------------------

class TestWeighCascadeBatchJobReport:
    def test_weigh_cascade_batch_and_job(self, api):
        """PRD §3.6: "Second, the job's certified diverted tonnage rises by the
        batch's diverted pounds. Third, the `OPEN` diversion report for that period
        recomputes its running totals."

        Design: Difficulty/transitive_cascade/weigh_cascade_batch_job_report
        """
        set_clock("2026-06-01T09:00:00Z")
        create_report("2026-06")
        ctx = create_in_progress_job(start="2026-06-12T08:00:00Z", end="2026-06-12T16:00:00Z",
                                     title="Job B", quoted_fee_cents=180000)
        category = create_category(code="LUMBER3", display_name="Lumber 3",
                                   pricing_model="PER_SQFT", base_rate_cents=200)
        batch = create_manifested_batch(ctx["job"]["id"], category["id"],
                                        estimated_weight_lbs=500)
        batch = validate_success(api.weigh_batch(
            batch["id"], {"scale_weight_lbs": 480, "contamination_weight_lbs": 30}, COORD))
        assert batch["status"] == "WEIGHED"
        assert batch["diverted_weight_lbs"] == 450
        assert batch["report_period"] == "2026-06", (
            f"report_period stamped from the logical clock: {batch['report_period']}")

        job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
        assert job["certified_diverted_weight_lbs"] == 450, (
            "hop 2: job certified tonnage rises by the batch's diverted pounds")

    def test_weigh_cascade_reaches_open_period_report(self, api):
        """PRD §3.9: "The frozen `sold_lbs` is the batch stream's certified diverted
        pounds — the reuse-store convention credits certified salvage tonnage to the
        retail stream until individual items prove otherwise — plus the walk-in
        weight of items sold in the period in `divertible` categories"
        PRD §3.9: "The `total_diverted_lbs` is the sum of the sold, donated, and
        recycled figures."

        Design: Difficulty/transitive_cascade/weigh_cascade_batch_job_report
        """
        set_clock("2026-06-01T09:00:00Z")
        report = create_report("2026-06")
        ctx = create_in_progress_job(start="2026-06-12T08:00:00Z", end="2026-06-12T16:00:00Z",
                                     title="Job B", quoted_fee_cents=180000)
        category = create_category(code="LUMBER3", display_name="Lumber 3",
                                   pricing_model="PER_SQFT", base_rate_cents=200)
        batch = create_manifested_batch(ctx["job"]["id"], category["id"],
                                        estimated_weight_lbs=500)
        validate_success(api.weigh_batch(
            batch["id"], {"scale_weight_lbs": 480, "contamination_weight_lbs": 30}, COORD))

        report = get_success_data(api.get_diversion_report(report["id"], ADMIN))
        assert report["total_diverted_lbs"] == 450, (
            f"hop 3: OPEN report running total includes the batch: {report['total_diverted_lbs']}")
        assert report["sold_lbs"] == 450, (
            f"batch stream credited to the retail share: {report['sold_lbs']}")


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / certified_tonnage_quarantine_cycle_invariant
# ---------------------------------------------------------------------------

class TestCertifiedTonnageQuarantineCycleInvariant:
    def test_quarantine_debits_certified_tonnage(self, api):
        """PRD §3.6: "When a post-hoc hazard is discovered — including the
        job-level cascade of §3.4 — a `HazmatTechnician`, `StoreManager`, or
        `WarehouseAdmin` quarantines it, moving it from `WEIGHED` to `QUARANTINED`
        (same state gate, `ERR_BATCH_NOT_WEIGHED`, with optional `notes` recorded):
        the job's certified tonnage is debited back by the batch's diverted pounds,
        and the open period report recomputes excluding the batch."

        Design: Difficulty/compensating_invariant/certified_tonnage_quarantine_cycle_invariant
        """
        ctx = setup_job_with_weighed_batch(
            scale_weight_lbs=480, contamination_weight_lbs=30, estimated_weight_lbs=500,
            start="2026-06-18T08:00:00Z", end="2026-06-18T16:00:00Z",
            code="BEAMS", display_name="Beams", pricing_model="PER_LINEAR_FT",
            base_rate_cents=400,
        )
        assert ctx["job"]["certified_diverted_weight_lbs"] == 450

        batch = validate_success(api.quarantine_batch(
            ctx["batch"]["id"], {"notes": "suspect mastic"},
            make_hazmat_technician_headers(ctx["tech"]["id"])))
        assert batch["status"] == "QUARANTINED"
        job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
        assert job["certified_diverted_weight_lbs"] == 0, (
            f"quarantine debits the diverted pounds: {job['certified_diverted_weight_lbs']}")

    def test_remediated_resolve_recredits_certified_tonnage(self, api):
        """PRD §3.6: "Resolving with an `outcome` of `REMEDIATED` returns the batch
        to `WEIGHED`; if the resolution supplies a `new_scale_weight_lbs`, the
        batch's `scale_weight_lbs` is replaced and `diverted_weight_lbs` recomputed
        from it, the job's certified tonnage is re-credited by the diverted pounds,
        and the open report recomputes including the batch — this
        weigh–quarantine–reweigh cycle is unbounded."

        Design: Difficulty/compensating_invariant/certified_tonnage_quarantine_cycle_invariant
        """
        ctx = setup_job_with_weighed_batch(
            scale_weight_lbs=480, contamination_weight_lbs=30, estimated_weight_lbs=500,
            start="2026-06-18T08:00:00Z", end="2026-06-18T16:00:00Z",
            code="BEAMS", display_name="Beams", pricing_model="PER_LINEAR_FT",
            base_rate_cents=400,
        )
        validate_success(api.quarantine_batch(
            ctx["batch"]["id"], {"notes": "suspect mastic"},
            make_hazmat_technician_headers(ctx["tech"]["id"])))
        job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
        assert job["certified_diverted_weight_lbs"] == 0

        batch = validate_success(api.resolve_quarantine(
            ctx["batch"]["id"], {"outcome": "REMEDIATED"},
            make_hazmat_technician_headers(ctx["tech"]["id"])))
        assert batch["status"] == "WEIGHED"
        assert batch["diverted_weight_lbs"] == 450
        job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
        assert job["certified_diverted_weight_lbs"] == 450, (
            "weigh +450, quarantine -450, REMEDIATED resolve +450: cycle conserves tonnage")
