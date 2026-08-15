"""Storage statements: the two accrual variants, rounding order, supersession,
the billing-run checkpoint, and job-level OCC (PRD §2.5, §2.6, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_job, get_job_version, create_statement, get_statement,
    set_clock, run_billing, setup_item_in_storage, release_placement,
)

PM = TEST_USERS["project_manager_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def _setup_divergence_scenario(claim_number, barcode, volume, rate, vault_code,
                               finalize=True):
    """GENERAL item placed 2026-08-10 (clock-set), PROVISIONAL statement for
    [2026-08-01, 2026-09-01) created 2026-08-15, placement released 2026-08-31;
    when finalize=True a billing run at 2026-09-01 finalizes the statement.
    Returns (ctx, statement, finalize-response-or-None).
    """
    ctx = setup_item_in_storage(
        job_overrides={"claim_number": claim_number},
        room_overrides={"name": "Lounge", "room_type": "LIVING"},
        item_overrides={"barcode": barcode, "description": "Sofa",
                        "item_category": "GENERAL", "declared_value_cents": 1000,
                        "volume_cu_ft": volume},
        vault_overrides={"code": vault_code, "climate_class": "CLIMATE_CONTROLLED",
                         "capacity_cu_ft": 10000,
                         "monthly_rate_cents_per_cu_ft": rate},
        placed_clock_iso="2026-08-10T09:00:00Z")
    set_clock("2026-08-15T09:00:00Z")
    stmt = create_statement(ctx["job"]["id"], "2026-08-01", "2026-09-01")
    set_clock("2026-08-31T10:00:00Z")
    release_placement(ctx["placement"]["id"])
    billing = None
    if finalize:
        set_clock("2026-09-01T00:00:00Z")
        billing = run_billing()
    return ctx, stmt, billing


class TestDualAccrualVariants:
    def test_provisional_variant_whole_month_accrual(self, api):
        """PRD §3.7: "Only placements currently `ACTIVE` whose `placed_on` falls
        before the statement's `period_end` participate. For each such placement,
        the charged span runs from the later of the placement's `placed_on` and the
        statement's `period_start` through `period_end`, and the charge is the
        placement's `monthly_rate_cents` snapshot multiplied by the number of
        distinct calendar months that span touches — any partial month counting as
        a full month, because the convention assumes continued occupancy."

        Design: Difficulty/dual_variant_calc/storage_accrual_provisional_vs_final_divergence
        """
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-DV1"},
            room_overrides={"name": "Lounge", "room_type": "LIVING"},
            item_overrides={"barcode": "BC-DV1", "description": "Sofa",
                            "item_category": "GENERAL", "declared_value_cents": 1000,
                            "volume_cu_ft": 40},
            vault_overrides={"code": "V-DV1", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 10000,
                             "monthly_rate_cents_per_cu_ft": 150},
            placed_clock_iso="2026-08-10T09:00:00Z")
        assert ctx["placement"]["monthly_rate_cents"] == 6000, (
            f"snapshot is volume 40 x rate 150, got {ctx['placement']['monthly_rate_cents']}")

        set_clock("2026-08-15T09:00:00Z")
        stmt = create_statement(ctx["job"]["id"], "2026-08-01", "2026-09-01")
        assert stmt["status"] == "PROVISIONAL"
        # Span [2026-08-10, 2026-09-01) touches one calendar month (August).
        assert stmt["provisional_total_cents"] == 6000, (
            f"whole-month convention: 1 month x 6000, got {stmt['provisional_total_cents']}")

    def test_final_variant_daily_proration_diverges(self, api):
        """PRD §3.7: "The final variant is a chronological daily proration over
        every placement — active or released — that occupied at least one day of
        the period." and "Because released placements participate and days rather
        than whole months are counted, the final figure generally differs from the
        provisional figure computed over identical placement data."
        PRD §3.7: "it finalizes every `PROVISIONAL` statement across all jobs whose
        `period_end` is on or before the logical clock's current date, computing
        each statement's `final_total_cents` under the final variant and moving it
        to `FINALIZED`."

        Design: Difficulty/dual_variant_calc/storage_accrual_provisional_vs_final_divergence
        """
        ctx, stmt, billing = _setup_divergence_scenario(
            "CLM-DV1", "BC-DV1", 40, 150, "V-DV1")

        final = get_statement(stmt["id"])
        assert final["status"] == "FINALIZED", (
            f"the billing run finalizes the elapsed statement, got {final['status']}")
        # daily = round_half_up(6000*12/365) = 197; occupied 2026-08-10..2026-08-30
        # = 21 days (released_on 08-31 excluded); 197 x 21 = 4137.
        assert final["final_total_cents"] == 4137, (
            f"daily 197 x 21 occupied days = 4137, got {final['final_total_cents']}")
        assert final["final_total_cents"] != 6000, (
            "the two variants must diverge on identical placement data")


class TestPinnedRoundingOrder:
    def _setup_rounding_case(self):
        """Vol 1 at 6001 cents/cu ft/mo (monthly snapshot 6001), placed at the
        default clock 2026-08-01, released 2026-08-04 -> 3 occupied days; statement
        [2026-08-01, 2026-09-01) finalized at 2026-09-01."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-CF1"},
            room_overrides={"name": "Study", "room_type": "OTHER"},
            item_overrides={"barcode": "BC-CF1", "description": "Lamp",
                            "item_category": "GENERAL", "declared_value_cents": 500,
                            "volume_cu_ft": 1},
            vault_overrides={"code": "V-CF1", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 1000,
                             "monthly_rate_cents_per_cu_ft": 6001})
        assert ctx["placement"]["monthly_rate_cents"] == 6001
        set_clock("2026-08-04T00:00:00Z")
        release_placement(ctx["placement"]["id"])
        stmt = create_statement(ctx["job"]["id"], "2026-08-01", "2026-09-01")
        set_clock("2026-09-01T00:00:00Z")
        run_billing()
        return ctx, stmt

    def test_daily_rate_rounded_before_multiplying_by_days(self, api):
        """PRD §2.5: "The storage daily-proration calculation pins a different and
        deliberate order: the daily rate for a placement is rounded half-up to
        whole cents first, once per placement, and only then multiplied by that
        placement's occupied-day count; unrounded per-placement values are never
        summed and rounded at the end."
        PRD §2.5: "a placement whose monthly snapshot rate is 6001 cents yields a
        daily rate of 197 cents after rounding (6001 times 12 divided by 365,
        rounded half-up), so three occupied days accrue 591 cents — not the 592
        cents that rounding the unrounded product at the end would produce."

        Design: Difficulty/combinatorial_formula/storage_daily_rate_rounding_order_pinned
        """
        _ctx, stmt = self._setup_rounding_case()
        final = get_statement(stmt["id"])
        assert final["final_total_cents"] == 591, (
            f"197/day x 3 days = 591 (not 592 from sum-then-round), "
            f"got {final['final_total_cents']}")

    def test_rounding_case_statement_finalized_and_provisional_excluded_release(self, api):
        """PRD §3.7: "it finalizes every `PROVISIONAL` statement across all jobs
        whose `period_end` is on or before the logical clock's current date,
        computing each statement's `final_total_cents` under the final variant and
        moving it to `FINALIZED`."
        PRD §3.7: "Only placements currently `ACTIVE` whose `placed_on` falls
        before the statement's `period_end` participate."

        Design: Difficulty/combinatorial_formula/storage_daily_rate_rounding_order_pinned
        """
        ctx, stmt = self._setup_rounding_case()
        # Statement was created after the release: the RELEASED placement is
        # outside the provisional input set, so the provisional accrual was 0.
        assert stmt["provisional_total_cents"] == 0, (
            f"provisional excludes the released placement, got {stmt['provisional_total_cents']}")
        final = get_statement(stmt["id"])
        assert final["status"] == "FINALIZED"
        assert final["final_total_cents"] is not None


class TestProvisionalInputSet:
    def test_provisional_excludes_released_placements(self, api):
        """PRD §3.7: "Only placements currently `ACTIVE` whose `placed_on` falls
        before the statement's `period_end` participate."

        Design: Corner/calculations/provisional_excludes_released_placements
        """
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-CA3"},
            room_overrides={"name": "Den"},
            item_overrides={"barcode": "BC-CA3", "description": "Rug",
                            "item_category": "GENERAL", "declared_value_cents": 1500,
                            "volume_cu_ft": 10},
            vault_overrides={"code": "V-CA3", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 1000,
                             "monthly_rate_cents_per_cu_ft": 150})
        # Placed at the default clock 2026-08-01; released 2026-08-10.
        set_clock("2026-08-10T00:00:00Z")
        release_placement(ctx["placement"]["id"])

        stmt = create_statement(ctx["job"]["id"], "2026-08-01", "2026-09-01")
        assert stmt["provisional_total_cents"] == 0, (
            "the RELEASED placement is excluded from the forward-looking input set, "
            f"got {stmt['provisional_total_cents']}")


class TestSupersede:
    def test_statement_supersede_voids_prior(self, api):
        """PRD §3.7: "The non-voided statements of one job must have disjoint
        periods, and a job holds at most one `PROVISIONAL` statement at a time —
        unless the creation names that provisional statement in
        `supersedes_statement_id`, in which case the named statement is voided as
        the new one succeeds."
        PRD §3.7: "Statements are listed globally, filterable by `job_id` and/or
        `supersedes_statement_id`, and read individually."

        Design: Corner/state_machines/statement_supersede_voids_prior
        """
        job = create_job(claim_number="CLM-SM7", property_address="58 Beech St")
        s1 = create_statement(job["id"], "2026-08-01", "2026-09-01")
        assert s1["status"] == "PROVISIONAL"

        s2 = create_statement(job["id"], "2026-08-01", "2026-09-01",
                              supersedes_statement_id=s1["id"])
        assert s2["status"] == "PROVISIONAL", (
            f"the superseding statement becomes the sole PROVISIONAL, got {s2['status']}")
        assert s2["id"] != s1["id"]

        s1_after = get_statement(s1["id"])
        assert s1_after["status"] == "VOIDED", (
            f"the named statement is voided as the new one succeeds, got {s1_after['status']}")

        lineage = get_success_data(api.list_storage_statements(
            CLERK, params={"supersedes_statement_id": s1["id"]}))
        assert [s["id"] for s in lineage] == [s2["id"]], (
            f"exactly S2 names S1 as superseded, got {[s['id'] for s in lineage]}")


class TestBillingRunCheckpoint:
    def test_billing_run_finalizes_only_elapsed_statements(self, api):
        """PRD §3.7: "Executed by a `BillingClerk`, it finalizes every
        `PROVISIONAL` statement across all jobs whose `period_end` is on or before
        the logical clock's current date, computing each statement's
        `final_total_cents` under the final variant and moving it to `FINALIZED`.
        The run reports the `finalized_count` and the `finalized_statement_ids`."

        Design: Corner/cross_cutting_layers/billing_run_finalizes_only_elapsed_statements
        """
        job = create_job(claim_number="CLM-LA3", property_address="96 Birch St")
        s1 = create_statement(job["id"], "2026-08-01", "2026-09-01")

        set_clock("2026-09-01T00:00:00Z")
        first = run_billing()
        assert first["finalized_count"] == 1, (
            f"period_end == clock date is inclusive, got {first['finalized_count']}")
        assert s1["id"] in first["finalized_statement_ids"]

        s1_after = get_statement(s1["id"])
        assert s1_after["status"] == "FINALIZED"
        assert s1_after["final_total_cents"] == 0, (
            f"no placements occupied the period, got {s1_after['final_total_cents']}")

        s2 = create_statement(job["id"], "2026-09-01", "2026-10-01")
        second = run_billing()
        assert second["finalized_count"] == 0, (
            f"S2's period_end 2026-10-01 is after the clock, got {second['finalized_count']}")
        assert get_statement(s2["id"])["status"] == "PROVISIONAL"


class TestImmediateAccrualAndOCC:
    def test_statement_create_response_shows_computed_accrual(self, api):
        """PRD §3.7: "A statement is born `PROVISIONAL`, and while provisional its
        `provisional_total_cents` is computed — and recomputed on every placement
        activation or release touching the job — under the provisional variant of
        the storage accrual: a forward-looking, whole-month convention."

        Design: Corner/consistency_model/statement_create_response_shows_computed_accrual
        """
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-CM1"},
            room_overrides={"name": "Den"},
            item_overrides={"barcode": "BC-CM1", "description": "Cabinet",
                            "item_category": "GENERAL", "declared_value_cents": 4000,
                            "volume_cu_ft": 10},
            vault_overrides={"code": "V-CM1", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 1000,
                             "monthly_rate_cents_per_cu_ft": 150})
        # Placed at the default clock; monthly snapshot 10 x 150 = 1500; the span
        # [2026-08-01, 2026-09-01) touches one calendar month (August).
        res = api.create_storage_statement(ctx["job"]["id"], {
            "period_start": "2026-08-01", "period_end": "2026-09-01",
            "expected_job_version": get_job_version(ctx["job"]["id"])}, CLERK)
        stmt = validate_success(res, 201)
        assert stmt["status"] == "PROVISIONAL"
        assert stmt["provisional_total_cents"] == 1500, (
            f"the creation response carries the computed accrual inline, "
            f"got {stmt['provisional_total_cents']}")

    def test_occ_stale_job_version_returns_412(self, api):
        """PRD §2.6: "A storage statement creation request must carry
        `expected_job_version`, the client's last observed `version` of the parent
        pack-out job. If another writer has advanced the job's `version` since the
        client last read it, the creation is rejected with `ERR_STALE_JOB_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_job_version_returns_412
        """
        job = create_job(claim_number="CLM-LA2", property_address="94 Elm St")
        stale_version = job["version"]
        s1 = validate_success(api.create_storage_statement(job["id"], {
            "period_start": "2026-08-01", "period_end": "2026-09-01",
            "expected_job_version": stale_version}, CLERK), 201)

        res = api.create_storage_statement(job["id"], {
            "period_start": "2026-08-01", "period_end": "2026-09-01",
            "supersedes_statement_id": s1["id"],
            "expected_job_version": stale_version}, CLERK)
        validate_error(res, ApiErrorId.ERR_STALE_JOB_VERSION, expected_status=412)

        assert get_statement(s1["id"])["status"] == "PROVISIONAL", (
            "the rejected supersede must leave S1 untouched")
