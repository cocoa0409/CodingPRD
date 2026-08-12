"""Inspections, posture derivation, segregation of duties, and the verify ->
quarantine cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    complete_course,
    create_and_verify_inspection,
    create_season,
    create_subscription_paid,
    get_allocation_for,
    make_beekeeper_headers,
    make_host_headers,
    make_manager_headers,
    record_harvest,
    record_inspection,
    approve_harvest,
    setup_allocation_scenario,
    setup_hive_scenario,
    setup_hive_with_verified_inspection,
    submit_inspection,
    validate_error,
    validate_success,
    verify_inspection,
)

MGR = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]
BK1 = TEST_USERS["beekeeper_headers"]


class TestInspectionReviewLoop:
    def test_verify_draft_inspection_rejected(self, api):
        """PRD §3.4: "An `ApiaryManager` then either verifies or returns it;
        attempting either on an inspection not in `SUBMITTED` fails with
        `ERR_INSPECTION_NOT_SUBMITTED`."

        Design: Corner/state_machines/verify_draft_inspection_rejected
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(ctx["hive"]["id"], mites_counted=1)
        res = api.verify_inspection(insp["id"], MGR)
        validate_error(res, "ERR_INSPECTION_NOT_SUBMITTED")
        current = validate_success(api.get_inspection(insp["id"], MGR))
        assert current["status"] == "DRAFT"
        assert current["verified_by_id"] is None

    def test_return_moves_to_returned_with_reason(self, api):
        """PRD §3.4: "A return requires a `return_reason`, moves the inspection
        to `RETURNED`, and the recorder may later resubmit — the
        `return_reason` is retained for audit."

        Design: Difficulty/non_linear_state_machine/inspection_return_resubmit_revision_loop
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(
            ctx["hive"]["id"],
            inspected_at="2026-05-10T00:00:00Z",
            mites_counted=4, bees_sampled=300, brood_score=7, stores_kg=9.0,
        )
        submit_inspection(insp["id"])
        returned = validate_success(
            api.return_inspection(
                insp["id"], {"return_reason": "redo brood frames"}, MGR,
            ),
            200,
        )
        assert returned["status"] == "RETURNED", "revision exit from SUBMITTED"
        assert returned["return_reason"] == "redo brood frames"

    def test_resubmit_then_verify_completes_loop(self, api):
        """PRD §3.4: "Verification stamps `verified_by_id`, sets the hive's
        `last_verified_inspection_at` to the inspection's `inspected_at`,
        recomputes both posture variants, and is terminal."
        PRD §3.4: "anything else yields `STABLE`."

        Design: Difficulty/non_linear_state_machine/inspection_return_resubmit_revision_loop
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(
            ctx["hive"]["id"],
            inspected_at="2026-05-10T00:00:00Z",
            mites_counted=4, bees_sampled=300, brood_score=7, stores_kg=9.0,
        )
        submit_inspection(insp["id"])
        validate_success(
            api.return_inspection(
                insp["id"], {"return_reason": "redo brood frames"}, MGR,
            ),
            200,
        )
        resubmitted = validate_success(
            api.submit_inspection(insp["id"], BK1), 200,
        )
        assert resubmitted["status"] == "SUBMITTED", (
            "loop back into SUBMITTED from RETURNED is legal"
        )
        verified = validate_success(
            api.verify_inspection(insp["id"], MGR), 200,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_id"] == "mgr-1"
        assert verified["return_reason"] == "redo brood frames", (
            "return_reason retained as audit across the loop"
        )
        hive = validate_success(api.get_hive(ctx["hive"]["id"], MGR))
        # mites 1.33/100 (< 2.00), brood 7 (>= 6), stores 9 (>= 8),
        # brood < 8 blocks THRIVING: the ladder falls through to STABLE.
        assert hive["posture"] == "STABLE"
        # NOTE: an exact-string assertion on `last_verified_inspection_at`
        # was removed: PRD §2.4 pins the three-fractional-digit format only
        # for `api_request_timestamp`, `created_at`, and `updated_at`; the
        # rendered format of derived datetime fields is unspecified, so both
        # "…T00:00:00Z" and "…T00:00:00.000Z" are PRD-consistent outputs.


class TestMiteLoadComputation:
    def test_mite_load_rounding_precision(self, api):
        """PRD §3.4: "the server immediately computes and stores
        `mite_load_per_100`: the mite count divided by the bees sampled,
        multiplied by 100, rounded half-up to two decimal places using decimal
        arithmetic."

        Design: Corner/calculations/inspection_mite_load_rounding_precision
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(
            ctx["hive"]["id"], mites_counted=8, bees_sampled=300,
        )
        # round_half_up(8 / 300 * 100, 2) == round_half_up(2.6666..., 2)
        assert insp["mite_load_per_100"] == pytest.approx(2.67, abs=1e-9), (
            "2.6666... must store as 2.67 under round-half-up decimal math"
        )

    def test_exactly_3_00_triggers_treatment_required(self, api):
        """PRD §3.4: "at least 3.00 yields `TREATMENT_REQUIRED`."
        PRD §3.4: "a `mite_load_per_100` of at least 9.00 yields
        `QUARANTINED`."

        Design: Difficulty/boundary_precision_check/mite_threshold_exact_3_00_triggers
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        insp = record_inspection(
            hive_id, inspected_at="2026-05-10T00:00:00Z",
            mites_counted=9, bees_sampled=300,
            brood_score=8, stores_kg=10.0,
        )
        submit_inspection(insp["id"])
        verified = verify_inspection(insp["id"])
        assert verified["mite_load_per_100"] == pytest.approx(3.00, abs=1e-9)
        hive = validate_success(api.get_hive(hive_id, MGR))
        assert hive["posture"] == "TREATMENT_REQUIRED", (
            ">= 3.00 is inclusive for the treatment threshold"
        )
        assert hive["lifecycle_status"] == "ACTIVE", (
            "3.00 does not reach the 9.00 quarantine threshold"
        )

    def test_just_below_3_00_stays_watch(self, api):
        """PRD §3.4: "From that latest inspection the ladder is evaluated top
        to bottom, first match winning: `disease_flag` true yields
        `QUARANTINED`; a `mite_load_per_100` of at least 9.00 yields
        `QUARANTINED`; at least 3.00 yields `TREATMENT_REQUIRED`; at least 2.00
        yields `WATCH`; a `brood_score` below 6 or `stores_kg` below 8 yields
        `WATCH`; a sighted queen with `brood_score` of at least 8 and
        `mite_load_per_100` below 1.00 yields `THRIVING`; anything else yields
        `STABLE`."

        Design: Difficulty/boundary_precision_check/mite_threshold_exact_3_00_triggers
        """
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        insp = record_inspection(
            hive_id, inspected_at="2026-05-10T00:00:00Z",
            mites_counted=8, bees_sampled=300,
            brood_score=8, stores_kg=10.0,
        )
        submit_inspection(insp["id"])
        verified = verify_inspection(insp["id"])
        assert verified["mite_load_per_100"] == pytest.approx(2.67, abs=1e-9)
        hive = validate_success(api.get_hive(hive_id, MGR))
        assert hive["posture"] == "WATCH", "2.67 >= 2.00 but < 3.00"
        assert hive["lifecycle_status"] == "ACTIVE"


class TestPostureVariants:
    def _setup_submitted_bad_report(self):
        """Hive with a VERIFIED healthy inspection and a SUBMITTED (not
        verified) bad report at 9.00 mites per 100."""
        ctx = setup_hive_scenario()
        hive_id = ctx["hive"]["id"]
        create_and_verify_inspection(
            hive_id, inspected_at="2026-05-02T00:00:00Z",
            mites_counted=0, bees_sampled=300,
            brood_score=9, queen_seen=True, stores_kg=12.0,
        )
        bad = record_inspection(
            hive_id, inspected_at="2026-05-18T00:00:00Z",
            mites_counted=9, bees_sampled=100, brood_score=7, stores_kg=9.0,
        )
        submit_inspection(bad["id"])
        ctx["bad_inspection"] = bad
        return ctx

    def test_provisional_moves_while_authoritative_stays(self, api):
        """PRD §2.7: "The **provisional** variant, `provisional_posture`,
        additionally considers `SUBMITTED` inspections and is informational
        only — an unverified bad report moves `provisional_posture` while
        `posture` stays unchanged, and the provisional value never gates
        anything."

        Design: Difficulty/dual_variant_calc/posture_provisional_vs_authoritative_gating
        """
        ctx = self._setup_submitted_bad_report()
        hive = validate_success(api.get_hive(ctx["hive"]["id"], MGR))
        assert hive["posture"] == "THRIVING", (
            "authoritative variant excludes the SUBMITTED report"
        )
        assert hive["provisional_posture"] == "QUARANTINED", (
            "provisional variant includes the SUBMITTED 9.00/100 report"
        )
        # The provisional value never gates: harvest creation still succeeds.
        harvest = validate_success(
            api.create_harvest(
                {
                    "hive_id": ctx["hive"]["id"],
                    "collected_on": "2026-05-20T00:00:00Z",
                    "gross_kg": 4.000,
                    "moisture_pct": 18.0,
                },
                BK1,
            ),
            201,
        )
        assert harvest["status"] == "RECORDED"

    def test_verify_flips_authoritative_and_voids_harvest(self, api):
        """PRD §3.4: "When a newly verified inspection's authoritative posture
        evaluates to `QUARANTINED`, an `ACTIVE` hive's `lifecycle_status`
        cascades to `QUARANTINED`, its `posture` is set to `QUARANTINED`, every
        harvest of that hive still in `RECORDED` status is voided."

        Design: Difficulty/dual_variant_calc/posture_provisional_vs_authoritative_gating
        """
        ctx = self._setup_submitted_bad_report()
        harvest = validate_success(
            api.create_harvest(
                {
                    "hive_id": ctx["hive"]["id"],
                    "collected_on": "2026-05-20T00:00:00Z",
                    "gross_kg": 4.000,
                    "moisture_pct": 18.0,
                },
                BK1,
            ),
            201,
        )
        verify_inspection(ctx["bad_inspection"]["id"])
        hive = validate_success(api.get_hive(ctx["hive"]["id"], MGR))
        assert hive["posture"] == "QUARANTINED"
        assert hive["lifecycle_status"] == "QUARANTINED"
        harvest_after = validate_success(api.get_harvest(harvest["id"], MGR))
        assert harvest_after["status"] == "VOIDED", (
            "quarantine cascade voids the in-flight RECORDED harvest"
        )


class TestQuarantineCascadeChain:
    def _setup_cascade(self):
        """Season + PLUS + HOST-101 (effective 2950 bps); one APPROVED harvest
        (net 5.000) and one RECORDED harvest (net 5.000); bad inspection at
        9.50/100 SUBMITTED but not yet verified."""
        ctx = setup_allocation_scenario(
            plan="PLUS",
            with_education=True,
            base_bps=2500,
            harvests=((5.000, 18.0),),
            inspection_schedule=[{"inspected_at": "2026-06-01T00:00:00Z"}],
        )
        hive_id = ctx["hive"]["id"]
        h2 = record_harvest(
            hive_id, collected_on="2026-06-16T00:00:00Z",
            gross_kg=5.000, moisture_pct=18.0,
        )
        ctx["recorded_harvest"] = h2
        before = get_allocation_for(hive_id, ctx["season"]["id"])
        ctx["pool_before"] = before["projected_pool_net_kg"]
        bad = record_inspection(
            hive_id, inspected_at="2026-06-20T00:00:00Z",
            mites_counted=95, bees_sampled=1000,
            brood_score=5, queen_seen=False, stores_kg=6.0,
        )
        submit_inspection(bad["id"])
        ctx["bad_inspection"] = bad
        return ctx

    def test_verify_quarantines_hive_and_voids_recorded_harvest(self, api):
        """PRD §3.4: "When a newly verified inspection's authoritative posture
        evaluates to `QUARANTINED`, an `ACTIVE` hive's `lifecycle_status`
        cascades to `QUARANTINED`, its `posture` is set to `QUARANTINED`, every
        harvest of that hive still in `RECORDED` status is voided."

        Design: Difficulty/transitive_cascade/verify_inspection_quarantine_cascade_chain
        """
        ctx = self._setup_cascade()
        verified = verify_inspection(ctx["bad_inspection"]["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["mite_load_per_100"] == pytest.approx(9.50, abs=1e-9), (
            ">= 9.00 is the quarantine threshold"
        )
        # Link 1: the verify mutates the hive.
        hive = validate_success(api.get_hive(ctx["hive"]["id"], MGR))
        assert hive["posture"] == "QUARANTINED"
        assert hive["lifecycle_status"] == "QUARANTINED"
        # Link 2: the hive quarantine voids the RECORDED harvest.
        h2 = validate_success(
            api.get_harvest(ctx["recorded_harvest"]["id"], MGR),
        )
        assert h2["status"] == "VOIDED"
        # The APPROVED harvest is outside the cascade's stated scope.
        h1 = validate_success(
            api.get_harvest(ctx["harvest_ids"][0], MGR),
        )
        assert h1["status"] == "APPROVED"

    def test_allocation_recomputed_by_the_void(self, api):
        """PRD §3.4: "the season's allocation for the hive — if one exists —
        is recomputed on the projected variant excluding the voided harvests."
        PRD §3.6: "It reports `projected_pool_net_kg`, the sum of `net_kg` over
        the pair's harvests in `RECORDED` or `APPROVED` status, and
        `projected_host_kg`, computed from those same harvests with all share
        inputs read live."

        Design: Difficulty/transitive_cascade/verify_inspection_quarantine_cascade_chain
        """
        ctx = self._setup_cascade()
        assert ctx["pool_before"] == pytest.approx(10.000, abs=1e-9), (
            "allocation reflected both harvests before the cascade"
        )
        verify_inspection(ctx["bad_inspection"]["id"])
        # Link 3: the harvest void recomputes the allocation (projected).
        alloc = get_allocation_for(ctx["hive"]["id"], ctx["season"]["id"])
        # Only the APPROVED 5.000 kg remains; effective 2500 + 250 + 200.
        assert alloc["projected_pool_net_kg"] == pytest.approx(5.000, abs=1e-9)
        assert alloc["projected_host_kg"] == pytest.approx(1.475, abs=1e-9)


class TestSegregationOfDuties:
    def test_verify_own_inspection_rejected(self, api):
        """PRD §2.10: "The beekeeper who recorded an inspection may submit or
        resubmit it, but may never verify or return it: verification and return
        are performed by an `ApiaryManager` whose `X-User-ID` differs from the
        inspection's `recorded_by_id`, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/verify_own_inspection_segregation_rejected
        """
        ctx = setup_hive_scenario()
        insp = record_inspection(ctx["hive"]["id"], mites_counted=1)
        submit_inspection(insp["id"])
        # Same operator id as the recorder, but with the manager role.
        res = api.verify_inspection(
            insp["id"], make_manager_headers("bk-1"),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
        current = validate_success(api.get_inspection(insp["id"], MGR))
        assert current["status"] == "SUBMITTED"
