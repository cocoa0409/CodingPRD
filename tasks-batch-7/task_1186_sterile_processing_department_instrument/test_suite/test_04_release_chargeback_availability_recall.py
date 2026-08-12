"""Load release economics (chargeback rounding, shelf-life tiers), the
availability projection's dual variants, the RUNNING fork's divergent side
effects, and the BI-positive recall cascade.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
AUDIT = TEST_USERS["quality_auditor_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]


class TestChargebackPerTrayRoundingOrder:
    """The pinned per-tray rounding order on a prevacuum load (two tests, one
    design instance)."""

    def test_chargeback_rounds_per_tray_then_sums(self, api):
        """PRD §3.5: "each tray's fee rounded half up to whole cents *first*
        and the per-tray fees summed *afterward*. The order is pinned: three
        trays on a prevacuum sterilizer bill 3,714 cents (three times the
        individually rounded 1,237.5-cent line), whereas summing raw fees and
        rounding once would wrongly produce 3,713 cents."

        Design: Difficulty/combinatorial_formula/load_chargeback_per_tray_rounding_order
        """
        s = fx.setup_prevac_three_tray_load(api)
        load = validate_success(api.get_sterilization_load(s.load["id"], ADMIN))
        assert load["total_chargeback_cents"] == 3714, (
            "3 x round_half_up(1000 x 1.2375) = 3 x 1238 = 3714; "
            "the forbidden sum-then-round order would give 3713"
        )

    def test_released_load_marks_member_trays_sterile(self, api):
        """PRD §3.5: "On release the load moves `COMPLETED → RELEASED` and
        `released_at` is stamped. Every member tray moves `IN_LOAD → STERILE`:
        its `sterility_expires_at` is assigned per the shelf-life tiers of
        §2.10, its `cycles_completed` increments by 1, and its
        `current_load_id` clears."

        Design: Difficulty/combinatorial_formula/load_chargeback_per_tray_rounding_order
        """
        s = fx.setup_prevac_three_tray_load(api)
        assert s.load["status"] == "RELEASED"
        for tray in s.trays:
            assert tray["status"] == "STERILE"
            assert tray["cycles_completed"] == 1
            assert tray["current_load_id"] is None
            assert_instant_equals(
                tray["sterility_expires_at"], "2026-05-31T03:00:00Z",
                "WRAPPED tier: released_at 2026-05-01T03:00:00Z + 720h",
            )


def test_chargeback_h2o2_two_trays_value(api):
    """PRD §3.5: "a base fee of 1,000 cents per member tray, multiplied by the
    sterilizer's method factor — 1.0 for `STEAM_GRAVITY`, 1.2375 for
    `STEAM_PREVAC`, 1.7625 for `LOW_TEMP_H2O2` — with each tray's fee rounded
    half up to whole cents *first* and the per-tray fees summed *afterward*."

    Design: Corner/calculations/chargeback_h2o2_two_trays_value
    """
    tpl = fx.create_template(api)
    ta = fx.create_technician(api, name="Tech A", certification_level=3,
                              certified_methods=["LOW_TEMP_H2O2"])
    ts = fx.create_technician(api, name="Sup S", certification_level=3,
                              certified_methods=["LOW_TEMP_H2O2"])
    sh = fx.create_sterilizer(api, name="SH", method="LOW_TEMP_H2O2",
                              chamber_capacity=2, cycle_minutes=90,
                              required_certification_level=1)
    trays, load = fx.create_sterile_trays(api, tpl["id"], sh["id"], ta["id"],
                                          ts["id"], ["H1", "H2"])
    assert load["total_chargeback_cents"] == 3526, (
        "2 x round_half_up(1000 x 1.7625) = 2 x 1763 = 3526; "
        "the naive order would give 3525"
    )


def test_sterility_shelf_tier_rigid_container(api):
    """PRD §2.10: "A `WRAPPED` tray receives 720 hours (thirty days) of shelf
    life; a `RIGID_CONTAINER` tray receives 2,160 hours (ninety days).
    Concretely, each member tray's `sterility_expires_at` is set to the load's
    `released_at` plus the tier hours for its packaging."

    Design: Corner/calculations/sterility_shelf_tier_rigid_container
    """
    tpl = fx.create_template(api, code="RIG-01", name="Rigid Set",
                             packaging_type="RIGID_CONTAINER")
    ta = fx.create_technician(api, name="Tech A", certification_level=2)
    ts = fx.create_technician(api, name="Sup S", certification_level=3)
    sg = fx.create_sterilizer(api)
    trays, load = fx.create_sterile_trays(api, tpl["id"], sg["id"], ta["id"],
                                          ts["id"], ["RG"])
    assert trays[0]["status"] == "STERILE"
    assert_instant_equals(trays[0]["sterility_expires_at"], "2026-07-30T03:00:00Z",
                          "released 2026-05-01T03:00:00Z + 2160h RIGID_CONTAINER tier")


class TestAvailabilityConfirmedVsPipeline:
    """Dual-variant availability projection over one template and window (two
    tests, one design instance)."""

    def test_confirmed_counts_only_currently_sterile(self, api):
        """PRD §3.1: "`confirmed_available_count` — the conservative variant:
        trays of this template currently `STERILE` whose
        `sterility_expires_at` is later than W. Only physically sterile stock
        counts."

        Design: Difficulty/dual_variant_calc/tray_availability_confirmed_vs_pipeline
        """
        s = fx.setup_availability_projection_scenario(api)
        data = validate_success(
            api.get_template_availability(s.tpl["id"], "2026-05-01T08:00:00Z", ADMIN)
        )
        assert data["confirmed_available_count"] == 2, (
            "only t1 and t2 are STERILE with expiry 2026-05-31T03:00:00Z > W"
        )

    def test_pipeline_adds_projected_in_load_trays(self, api):
        """PRD §3.1: "`pipeline_available_count` — the optimistic variant:
        everything in the confirmed count, plus trays of this template
        currently `IN_LOAD` whose load is `LOADING`, `RUNNING`, or `COMPLETED`
        and whose *projected release instant* falls at or before W (the
        boundary is inclusive)." "Identical inputs therefore yield a strictly
        larger pipeline count whenever qualifying in-pipeline trays exist."

        Design: Difficulty/dual_variant_calc/tray_availability_confirmed_vs_pipeline
        """
        s = fx.setup_availability_projection_scenario(api)
        data = validate_success(
            api.get_template_availability(s.tpl["id"], "2026-05-01T08:00:00Z", ADMIN)
        )
        assert data["pipeline_available_count"] == 4, (
            "t3,t4 on the RUNNING load project to 2026-05-01T08:00:00Z <= W "
            "(inclusive); t5 on the LOADING load projects to "
            "2026-05-02T08:00:00Z > W and is excluded"
        )
        assert data["pipeline_available_count"] != data["confirmed_available_count"]


class TestLoadBranchingDivergentSideEffects:
    """The RUNNING fork: COMPLETED vs FAILED_CYCLE leave observably different
    worlds (two tests, one design instance)."""

    def test_completed_branch_creates_bi_and_releases(self, api):
        """PRD §3.4: "Completing the cycle requires the load `RUNNING` (else
        `ERR_LOAD_NOT_RUNNING`) and moves it to `COMPLETED`: `completed_at` is
        stamped, the sterilizer returns to `IDLE`, and exactly one biological
        indicator is auto-created for the load". PRD §3.5: "On release the
        load moves `COMPLETED → RELEASED`".

        Design: Difficulty/non_linear_state_machine/load_branching_divergent_side_effects
        """
        s = fx.setup_load_branching_scenario(api)
        la = validate_success(api.get_sterilization_load(s.la["id"], ADMIN))
        assert la["status"] == "RELEASED"
        assert la["total_chargeback_cents"] == 1000, (
            "one GRAVITY tray: round_half_up(1000 x 1.0) = 1000"
        )
        ta = validate_success(api.get_tray(s.ta["id"], ADMIN))
        assert ta["status"] == "STERILE"
        assert_instant_equals(ta["sterility_expires_at"], "2026-05-31T03:00:00Z",
                              "WRAPPED tier from the 2026-05-01T03:00:00Z release")

    def test_failed_cycle_branch_demotes_and_debits(self, api):
        """PRD §3.4: "Recording a cycle-parameter failure requires `RUNNING`
        (else `ERR_LOAD_NOT_RUNNING`), moves the load to `FAILED_CYCLE`, frees
        the sterilizer to `IDLE`, returns every member tray to `ASSEMBLED`
        with `current_load_id` cleared, and attributes an 8-point competency
        demerit to the load's `operator_id`."

        Design: Difficulty/non_linear_state_machine/load_branching_divergent_side_effects
        """
        s = fx.setup_load_branching_scenario(api)
        h = make_technician_headers(s.tech_a["id"])
        failed = validate_success(api.fail_load_cycle(s.lf["id"], h))
        assert failed["status"] == "FAILED_CYCLE"

        tf = validate_success(api.get_tray(s.tf["id"], ADMIN))
        assert tf["status"] == "ASSEMBLED"
        assert tf["current_load_id"] is None

        bis, meta = validate_paginated(
            api.list_biological_indicators(ADMIN, params={"load_id": s.lf["id"]})
        )
        assert meta["total_count"] == 0, "no BI is auto-created on the failure branch"

        tech = validate_success(api.get_technician(s.tech_a["id"], ADMIN))
        assert tech["competency_score"] == 92, "one -8 cycle-failure demerit"

        ster = validate_success(api.get_sterilizer(s.ster["id"], ADMIN))
        assert ster["status"] == "IDLE"


class TestBiPositiveRecallCascadeDepth4:
    """BI POSITIVE on a RELEASED load: a four-link cascade (two tests, one
    design instance)."""

    def _trigger(self, api, s):
        return api.record_bi_result(s.bi2["id"], {"result": "POSITIVE"}, AUDIT)

    def test_links_1_and_2_load_recalled_tray_quarantined(self, api):
        """PRD §3.5: "or automatically by the system when a `POSITIVE` BI
        result lands on a `RELEASED` load, in which case `recall_reason` is
        recorded as the literal `BI_POSITIVE`. Either way the load moves
        `RELEASED → RECALLED` with `recall_reason` set and `recalled_at`
        stamped. The recall cascade then fires: every member tray currently
        `STERILE` moves to `QUARANTINED` with `quarantine_reason` copied from
        the load's `recall_reason` and `sterility_expires_at` cleared to
        null".

        Design: Difficulty/transitive_cascade/bi_positive_recall_cascade_depth4
        """
        s = fx.setup_recall_cascade_scenario(api)
        validate_success(self._trigger(api, s))
        lq = validate_success(api.get_sterilization_load(s.lq["id"], ADMIN))
        assert lq["status"] == "RECALLED"
        assert lq["recall_reason"] == "BI_POSITIVE"
        assert_instant_equals(lq["recalled_at"], "2026-05-01T06:00:00Z",
                              "recalled_at stamps the logical clock")
        tq = validate_success(api.get_tray(s.tq["id"], ADMIN))
        assert tq["status"] == "QUARANTINED"
        assert tq["quarantine_reason"] == "BI_POSITIVE"
        assert tq["sterility_expires_at"] is None

    def test_links_3_and_4_reservation_cancelled_case_at_risk(self, api):
        """PRD §3.5: "every reservation still `RESERVED` on those trays moves
        to `CANCELLED`; and each case stripped of a reservation this way, if
        it was `TRAYS_RESERVED`, falls to `AT_RISK`."

        Design: Difficulty/transitive_cascade/bi_positive_recall_cascade_depth4
        """
        s = fx.setup_recall_cascade_scenario(api)
        validate_success(self._trigger(api, s))
        rq = validate_success(api.get_tray_reservation(s.rq["id"], ADMIN))
        assert rq["status"] == "CANCELLED"
        cq = validate_success(api.get_or_case(s.cq["id"], ADMIN))
        assert cq["status"] == "AT_RISK"
