"""Treatments, the withdrawal embargo, and harvest recording rules."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_verify_inspection,
    create_completed_treatment,
    create_harvest_payload,
    create_treatment_payload,
    make_manager_headers,
    record_harvest,
    rollover_season,
    setup_allocation_scenario,
    setup_hive_scenario,
    setup_hive_with_verified_inspection,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]
BK1 = TEST_USERS["beekeeper_headers"]


class TestTreatmentLifecycle:
    def test_complete_before_start_rejected(self, api):
        """PRD §3.5: "A beekeeper starts it when work begins (the hive must be
        `ACTIVE` or `QUARANTINED`), stamping `started_at` and moving it
        `IN_PROGRESS`, and later completes it, stamping `completed_at` and
        reaching the terminal `COMPLETED` state."
        PRD §2.12 step 6: "the target resource's current state permits the
        transition, and the OCC `expected_*_version` match is evaluated at this
        step; failures surface as `ERR_INVALID_STATE`, `ERR_HIVE_NOT_OPERABLE`,
        `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INSPECTION_NOT_SUBMITTED`,
        `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_INVOICE_NOT_PAYABLE`,
        `ERR_INVOICE_NOT_VOIDABLE`, `ERR_SWARM_NOT_ACTIONABLE`,
        `ERR_REMOVAL_NOT_ACTIONABLE`, `ERR_ALLOCATION_NOT_DISTRIBUTABLE`,
        `ERR_SEASON_NOT_CLOSABLE`, `ERR_ENROLLMENT_NOT_COMPLETABLE`, or
        `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/treatment_complete_before_start_rejected
        """
        ctx = setup_hive_scenario()
        treatment = validate_success(
            api.create_treatment(
                create_treatment_payload(
                    ctx["hive"]["id"], product="OXALIC_ACID",
                    start_date="2026-05-05T00:00:00Z",
                    end_date="2026-05-08T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        assert treatment["status"] == "SCHEDULED"
        res = api.complete_treatment(treatment["id"], BK1)
        validate_error(res, "ERR_INVALID_STATE")
        current = validate_success(api.get_treatment(treatment["id"], MGR))
        assert current["status"] == "SCHEDULED"
        assert current["completed_at"] is None


class TestTreatmentWindows:
    def test_adjacent_windows_allowed(self, api):
        """PRD §3.5: "The window is half-open — it covers the start date and
        every day up to but not including the end date — `end_date` must fall
        after `start_date`, and the new window must not overlap any existing
        treatment window on the same hive under half-open semantics, else
        `ERR_TREATMENT_WINDOW_OVERLAP`."
        PRD §3.5: "On creation the server derives `withdrawal_end_date` as
        `end_date` plus 14 days, and the treatment starts `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/treatment_window_half_open_adjacency
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        t1 = validate_success(
            api.create_treatment(
                create_treatment_payload(
                    hive_id, product="APIVAR",
                    start_date="2026-05-01T00:00:00Z",
                    end_date="2026-05-10T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        # t2 starts exactly when t1 ends: adjacency is not overlap.
        t2 = validate_success(
            api.create_treatment(
                create_treatment_payload(
                    hive_id, product="FORMIC_ACID",
                    start_date="2026-05-10T00:00:00Z",
                    end_date="2026-05-20T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        assert t1["status"] == "SCHEDULED" and t2["status"] == "SCHEDULED"
        # Verify the date portion matches end_date + 14 days. The exact
        # fractional-second rendering is unspecified in PRD (only
        # api_request_timestamp / created_at / updated_at are pinned to three
        # fractional digits), so we compare instants, not strings.
        from datetime import datetime, timezone, timedelta
        def _parse(s):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        expected = _parse("2026-05-10T00:00:00Z") + timedelta(days=14)
        assert _parse(t1["withdrawal_end_date"]) == expected, (
            "withdrawal_end_date := end_date + 14 days at creation"
        )

    def test_intersecting_window_rejected(self, api):
        """PRD §3.5: "the new window must not overlap any existing treatment
        window on the same hive under half-open semantics, else
        `ERR_TREATMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/treatment_window_half_open_adjacency
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        for product, start, end in (
            ("APIVAR", "2026-05-01T00:00:00Z", "2026-05-10T00:00:00Z"),
            ("FORMIC_ACID", "2026-05-10T00:00:00Z", "2026-05-20T00:00:00Z"),
        ):
            validate_success(
                api.create_treatment(
                    create_treatment_payload(
                        hive_id, product=product,
                        start_date=start, end_date=end,
                    ),
                    MGR,
                ),
                201,
            )
        # [05-09, 05-11) intersects both existing windows.
        res = api.create_treatment(
            create_treatment_payload(
                hive_id, product="OXALIC_ACID",
                start_date="2026-05-09T00:00:00Z",
                end_date="2026-05-11T00:00:00Z",
            ),
            MGR,
        )
        validate_error(res, "ERR_TREATMENT_WINDOW_OVERLAP")


class TestHarvestRecording:
    def test_net_kg_computed_at_creation(self, api):
        """PRD §3.5: "The server computes `net_kg` immediately: moisture
        strictly above 18.6 percent is penalized while exactly 18.6 is not, the
        excess percentage points are divided by 100 and multiplied by both
        `gross_kg` and a penalty factor of 2.0 to give the moisture penalty in
        kilograms, and `net_kg` is `gross_kg` minus that penalty, rounded
        half-up to three decimal places in decimal arithmetic. The harvest is
        born `RECORDED`."

        Design: Corner/entities/harvest_net_kg_computed_at_creation
        """
        ctx = setup_hive_with_verified_inspection(
            inspection_overrides={"inspected_at": "2026-06-01T00:00:00Z"},
        )
        harvest = record_harvest(
            ctx["hive"]["id"], collected_on="2026-06-15T00:00:00Z",
            gross_kg=10.000, moisture_pct=19.6,
        )
        # 10.000 - 10.000 * (1.0 / 100) * 2.0 == 9.800
        assert harvest["net_kg"] == pytest.approx(9.800, abs=1e-9)
        assert harvest["status"] == "RECORDED", "harvest initial state"

    def test_moisture_exactly_18_6_no_penalty(self, api):
        """PRD §3.5: "moisture strictly above 18.6 percent is penalized while
        exactly 18.6 is not."

        Design: Difficulty/boundary_precision_check/moisture_exact_18_6_no_penalty
        """
        ctx = setup_hive_with_verified_inspection(
            inspection_overrides={"inspected_at": "2026-06-01T00:00:00Z"},
        )
        harvest = record_harvest(
            ctx["hive"]["id"], collected_on="2026-06-15T00:00:00Z",
            gross_kg=10.000, moisture_pct=18.6,
        )
        assert harvest["net_kg"] == pytest.approx(10.000, abs=1e-9), (
            "max(0, 18.6 - 18.6) == 0: the strictly-greater branch is off"
        )

    def test_moisture_18_7_penalized(self, api):
        """PRD §3.5: "moisture strictly above 18.6 percent is penalized while
        exactly 18.6 is not, the excess percentage points are divided by 100
        and multiplied by both `gross_kg` and a penalty factor of 2.0 to give
        the moisture penalty in kilograms, and `net_kg` is `gross_kg` minus
        that penalty, rounded half-up to three decimal places in decimal
        arithmetic."

        Design: Difficulty/boundary_precision_check/moisture_exact_18_6_no_penalty
        """
        ctx = setup_hive_with_verified_inspection(
            inspection_overrides={"inspected_at": "2026-06-01T00:00:00Z"},
        )
        harvest = record_harvest(
            ctx["hive"]["id"], collected_on="2026-06-16T00:00:00Z",
            gross_kg=10.000, moisture_pct=18.7,
        )
        # 10.000 - 10.000 * (0.1 / 100) * 2.0 == 10.000 - 0.020 == 9.980
        assert harvest["net_kg"] == pytest.approx(9.980, abs=1e-9)

    def test_freshness_window_inclusive_at_30_days(self, api):
        """PRD §3.5: "Recording requires an operable hive, freshness of field
        knowledge — some `VERIFIED` inspection of the hive whose `inspected_at`
        lies in the closed window from 30 days before `collected_on` through
        `collected_on`, failing which `ERR_INSPECTION_STALE`."

        Design: Corner/validations/harvest_freshness_30d_boundary
        """
        ctx = setup_hive_with_verified_inspection(
            inspection_overrides={"inspected_at": "2026-05-01T00:00:00Z"},
        )
        hive_id = ctx["hive"]["id"]
        # 2026-05-31 is exactly 30 days after the inspection: inside the
        # closed window.
        ok = validate_success(
            api.create_harvest(
                create_harvest_payload(
                    hive_id, collected_on="2026-05-31T00:00:00Z",
                    gross_kg=3.000, moisture_pct=18.0,
                ),
                BK1,
            ),
            201,
        )
        assert ok["status"] == "RECORDED"
        # 2026-06-01 is 31 days after: outside the closed window.
        res = api.create_harvest(
            create_harvest_payload(
                hive_id, collected_on="2026-06-01T00:00:00Z",
                gross_kg=3.000, moisture_pct=18.0,
            ),
            BK1,
        )
        validate_error(res, "ERR_INSPECTION_STALE")


class TestHarvestSafetyGates:
    def test_harvest_on_quarantined_hive_rejected(self, api):
        """PRD §3.4: "Quarantine freezes income: harvesting or splitting a
        quarantined hive is rejected with `ERR_HIVE_QUARANTINED`."
        PRD §3.4: "`disease_flag` true yields `QUARANTINED`."

        Design: Corner/errors/harvest_on_quarantined_hive_rejected
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        create_and_verify_inspection(
            hive_id, inspected_at="2026-05-02T00:00:00Z",
            mites_counted=0, bees_sampled=300,
            brood_score=9, queen_seen=True, stores_kg=12.0,
        )
        create_and_verify_inspection(
            hive_id, inspected_at="2026-05-18T00:00:00Z",
            mites_counted=2, bees_sampled=300, disease_flag=True,
            brood_score=4, queen_seen=False, stores_kg=5.0,
        )
        hive = validate_success(api.get_hive(hive_id, MGR))
        assert hive["lifecycle_status"] == "QUARANTINED", (
            "disease_flag verification quarantined the hive"
        )
        res = api.create_harvest(
            create_harvest_payload(
                hive_id, collected_on="2026-05-19T00:00:00Z",
                gross_kg=2.000, moisture_pct=18.0,
            ),
            BK1,
        )
        validate_error(res, "ERR_HIVE_QUARANTINED")

    def test_harvest_in_withdrawal_window_rejected(self, api):
        """PRD §3.5: "a harvest may not be recorded if its `collected_on`
        falls inside the embargo window — from the treatment's `start_date` up
        to but not including `withdrawal_end_date` — of any `IN_PROGRESS` or
        `COMPLETED` treatment on the hive; the rejection is
        `ERR_WITHDRAWAL_WINDOW_ACTIVE`."

        Design: Corner/errors/harvest_in_withdrawal_window_rejected
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        create_completed_treatment(
            hive_id, product="FORMIC_ACID",
            start_date="2026-05-02T00:00:00Z", end_date="2026-05-10T00:00:00Z",
        )  # embargo [2026-05-02, 2026-05-24)
        create_and_verify_inspection(
            hive_id, inspected_at="2026-05-15T00:00:00Z",
            mites_counted=5, bees_sampled=300,
            brood_score=7, queen_seen=True, stores_kg=9.0,
        )
        res = api.create_harvest(
            create_harvest_payload(
                hive_id, collected_on="2026-05-20T00:00:00Z",
                gross_kg=2.000, moisture_pct=18.0,
            ),
            BK1,
        )
        validate_error(res, "ERR_WITHDRAWAL_WINDOW_ACTIVE")

    def test_approve_own_harvest_segregation_rejected(self, api):
        """PRD §2.10: "The same wall stands between harvest recording and
        harvest approval: the approving manager's `X-User-ID` must differ from
        the harvest's `recorded_by_id`, with `ERR_SEGREGATION_OF_DUTIES` on a
        match."

        Design: Corner/errors/approve_own_harvest_segregation_rejected
        """
        ctx = setup_hive_with_verified_inspection(
            inspection_overrides={"inspected_at": "2026-06-01T00:00:00Z"},
        )
        harvest = record_harvest(
            ctx["hive"]["id"], collected_on="2026-06-15T00:00:00Z",
            gross_kg=4.000, moisture_pct=18.0,
        )
        res = api.approve_harvest(
            harvest["id"], make_manager_headers("bk-1"),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
        current = validate_success(api.get_harvest(harvest["id"], MGR))
        assert current["status"] == "RECORDED"
        assert current["approved_by_id"] is None


class TestHarvestValidationOrdering:
    def _setup_dead_hive_in_withdrawal(self):
        """Hive with a COMPLETED treatment ([2026-05-02, 2026-05-10),
        withdrawal to 2026-05-24), then marked DEAD at 2026-05-15."""
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        create_completed_treatment(
            hive_id, product="APIVAR",
            start_date="2026-05-02T00:00:00Z", end_date="2026-05-10T00:00:00Z",
        )
        api_client.set_clock("2026-05-15T00:00:00Z", OPS)
        validate_success(api_client.mark_hive_dead(hive_id, MGR), 200)
        return ctx

    def test_state_error_beats_withdrawal_safety(self, api):
        """PRD §2.12: "Every request passes through a fixed pipeline of checks,
        evaluated in this order, and the first failure determines the error
        returned"
        PRD §2.12 step 6: "the target resource's current state permits the
        transition, and the OCC `expected_*_version` match is evaluated at this
        step; failures surface as `ERR_INVALID_STATE`, `ERR_HIVE_NOT_OPERABLE`,
        `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INSPECTION_NOT_SUBMITTED`,
        `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_INVOICE_NOT_PAYABLE`,
        `ERR_INVOICE_NOT_VOIDABLE`, `ERR_SWARM_NOT_ACTIONABLE`,
        `ERR_REMOVAL_NOT_ACTIONABLE`, `ERR_ALLOCATION_NOT_DISTRIBUTABLE`,
        `ERR_SEASON_NOT_CLOSABLE`, `ERR_ENROLLMENT_NOT_COMPLETABLE`, or
        `ERR_STALE_VERSION` (412)."
        PRD §2.12 step 7: "waiver currency where required (agreement signing,
        hive installation, removal requests, enrollment), segregation of
        duties, hive not quarantined for harvest or split, no treatment
        withdrawal window covering `collected_on`; surfaced as
        `ERR_WAIVER_CURRENT_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`,
        `ERR_HIVE_QUARANTINED`, or `ERR_WITHDRAWAL_WINDOW_ACTIVE`."
        PRD §3.3: "a `DEAD` or `REMOVED` hive accepts no splits, inspections,
        harvests, or treatments (`ERR_HIVE_NOT_OPERABLE`)."

        Design: Difficulty/priority_pair_validation_conflict/harvest_state_error_beats_withdrawal_safety
        """
        ctx = self._setup_dead_hive_in_withdrawal()
        # 2026-05-20 lies inside the withdrawal window [05-02, 05-24), so the
        # safety rule also fails; the state error must surface first.
        res = api.create_harvest(
            create_harvest_payload(
                ctx["hive"]["id"], collected_on="2026-05-20T00:00:00Z",
                gross_kg=2.000, moisture_pct=18.0,
            ),
            BK1,
        )
        validate_error(res, "ERR_HIVE_NOT_OPERABLE")

    def test_withdrawal_fires_alone_when_hive_operable(self, api):
        """PRD §3.5: "a harvest may not be recorded if its `collected_on`
        falls inside the embargo window — from the treatment's `start_date` up
        to but not including `withdrawal_end_date` — of any `IN_PROGRESS` or
        `COMPLETED` treatment on the hive; the rejection is
        `ERR_WITHDRAWAL_WINDOW_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/harvest_state_error_beats_withdrawal_safety
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        create_completed_treatment(
            hive_id, product="APIVAR",
            start_date="2026-05-02T00:00:00Z", end_date="2026-05-10T00:00:00Z",
        )
        # The hive stays ACTIVE with a fresh verified inspection: only the
        # withdrawal rule can fail on this harvest attempt.
        create_and_verify_inspection(
            hive_id, inspected_at="2026-05-15T00:00:00Z",
            mites_counted=0, bees_sampled=300,
            brood_score=9, queen_seen=True, stores_kg=12.0,
        )
        res = api.create_harvest(
            create_harvest_payload(
                hive_id, collected_on="2026-05-20T00:00:00Z",
                gross_kg=2.000, moisture_pct=18.0,
            ),
            BK1,
        )
        validate_error(res, "ERR_WITHDRAWAL_WINDOW_ACTIVE")


class TestHarvestFinalizationLockdown:
    def test_void_after_finalization_rejected(self, api):
        """PRD §3.5: "A manager may also void a harvest in `RECORDED` or
        `APPROVED` status — again only while the allocation is not `FINALIZED`
        or `DISTRIBUTED`."
        PRD §3.5: "a late approval attempt against a settled allocation fails
        with `ERR_ALLOCATION_NOT_DISTRIBUTABLE`."

        Design: Corner/state_machines/harvest_void_after_finalization_rejected
        """
        ctx = setup_allocation_scenario(harvests=((4.000, 18.0),))
        rollover_season(ctx["season"]["id"], at="2026-10-20T00:00:00Z")
        harvest_id = ctx["harvest_ids"][0]
        res = api.void_harvest(harvest_id, MGR)
        validate_error(res, "ERR_ALLOCATION_NOT_DISTRIBUTABLE")
        harvest = validate_success(api.get_harvest(harvest_id, MGR))
        assert harvest["status"] == "APPROVED", "no drift after rejection"
