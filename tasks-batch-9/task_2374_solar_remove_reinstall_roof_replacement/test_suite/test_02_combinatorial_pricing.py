"""Multi-input formulas whose published result depends on how the terms combine.

Three families: the four-step deck-upgrade price with its cap/floor nest, the
per-calendar-day rounding of the final downtime credit, and the pinned snapshot
ordering inside the replacement-match classification.
"""

import pytest

from test_helpers import (
    add_circuit,
    add_bin,
    add_finding,
    add_unit,
    add_window,
    assert_credit_ledger_identity,
    collect_all_consents,
    create_core_parties,
    create_project,
    deenergize_circuit,
    drive_finding,
    drive_window,
    file_warranty_notice,
    grade_unit,
    raise_sourcing_order,
    reenergize_circuit,
    refresh_project,
    reinstall_unit,
    remove_unit,
    set_clock,
    settle_credit,
    store_unit,
)

# --------------------------------------------------------------------------
# Composite setups (private to this module)
# --------------------------------------------------------------------------


def _setup_two_scoped_findings() -> dict:
    """HOST_OWNED project with two FLASHING_FAILURE findings, both scoped.

    Finding A straddles all three area tiers (420 sqft, 36 attachments, HIGH).
    Finding B has an attachment leg that alone out-ranks the cap (10 sqft, 600
    attachments, LOW). The generous budget keeps the budget gate out of the way.
    """
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=9_000_000,
    )
    project_id = project["id"]
    roofer_id = parties["roofer"]["id"]

    finding_a = add_finding(
        project_id,
        roofer_id,
        finding_type="FLASHING_FAILURE",
        severity="HIGH",
        affected_area_sqft=420,
        attachment_count_affected=36,
    )
    finding_b = add_finding(
        project_id,
        roofer_id,
        finding_type="FLASHING_FAILURE",
        severity="LOW",
        affected_area_sqft=10,
        attachment_count_affected=600,
    )

    scoped_a = drive_finding(finding_a["id"], roofer_id, "SCOPE")
    scoped_b = drive_finding(finding_b["id"], roofer_id, "SCOPE")

    return {
        "project_id": project_id,
        "roofer_id": roofer_id,
        "scoped_a": scoped_a,
        "scoped_b": scoped_b,
        "project": refresh_project(project_id),
    }


def _setup_three_halved_outage_dates() -> dict:
    """LEASE project commissioned over 7 outage dates, three of them halved.

    De-energized 2026-08-03T09:00:00Z, re-energized 2026-08-09T15:00:00Z. After
    commissioning, three single-date roofing windows on 2026-08-04, 2026-08-05
    and 2026-08-06 are WEATHER_ABORTED.
    """
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=9,
        upgrade_budget_cents=5_000_000,
    )
    project_id = project["id"]
    crew_id = parties["crew"]["id"]
    roofer_id = parties["roofer"]["id"]

    file_warranty_notice(project_id, notice_reference="MN-2026-0418")
    collect_all_consents(project, parties)

    circuit = add_circuit(project_id, circuit_label="S1", module_count=1, dc_kw=0.41)
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=4, climate_controlled=True
    )
    unit = add_unit(
        project_id, circuit["id"], crew_id, serial_number="SN-0001", rated_watts=410
    )

    set_clock("2026-08-03T09:00:00Z")
    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(unit["id"], crew_id)
    store_unit(unit["id"], storage_bin["id"], crew_id)
    grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")

    finding = add_finding(
        project_id,
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=20,
        attachment_count_affected=2,
    )
    drive_finding(
        finding["id"],
        roofer_id,
        "WAIVE",
        waiver_reason="Fasteners re-seated, no upgrade scope required",
    )

    set_clock("2026-08-09T15:00:00Z")
    reinstall_unit(unit["id"], crew_id)
    reenergize_circuit(circuit["id"], crew_id)

    for day, reason in (
        ("2026-08-04", "Rain out day 1"),
        ("2026-08-05", "Rain out day 2"),
        ("2026-08-06", "Rain out day 3"),
    ):
        window = add_window(
            project_id,
            roofer_id,
            trade="ROOFING",
            start_utc=f"{day}T13:00:00Z",
            end_utc=f"{day}T21:00:00Z",
        )
        drive_window(window["id"], "WEATHER_ABORT", abort_reason=reason)

    return {
        "project_id": project_id,
        "commissioned": refresh_project(project_id),
    }


def _setup_sourcing_order_on_notified_project() -> dict:
    """LEASE project with the notice FILED and one DAMAGED, RETAINED panel.

    The offered part keeps the manufacturer of record but changes the model code
    and offers 426 W against 410 W of record, and carries no waiver_ref.
    """
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=40.0,
        downtime_days_estimated=5,
        upgrade_budget_cents=5_000_000,
    )
    project_id = project["id"]
    crew_id = parties["crew"]["id"]

    file_warranty_notice(project_id, notice_reference="MN-2026-0419")
    collect_all_consents(project, parties)

    circuit = add_circuit(project_id, circuit_label="S1", module_count=1, dc_kw=0.41)
    unit = add_unit(
        project_id,
        circuit["id"],
        crew_id,
        manufacturer="Meridian Solar",
        model_code="MS-410",
        serial_number="SN-0001",
        rated_watts=410,
    )

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(unit["id"], crew_id)
    grade_unit(
        unit["id"],
        crew_id,
        "DAMAGED",
        "RETAIN",
        damage_note="Backsheet crack found during tear-off",
    )

    order = raise_sourcing_order(
        project_id,
        unit["id"],
        requested_model_code="MS-410",
        offered_manufacturer="Meridian Solar",
        offered_model_code="MS-425",
        offered_rated_watts=426,
        unit_cost_cents=31_500,
    )

    return {
        "project_id": project_id,
        "order": order,
        "project": refresh_project(project_id),
    }


# --------------------------------------------------------------------------
# Deck upgrade price: tiers x flashing surcharge x severity, then cap/floor
# --------------------------------------------------------------------------
class TestDeckUpgradePriceCombination:
    def test_tier_straddle_flashing_surcharge_and_severity_multiplier_compose(self):
        """420 sqft pays all three tiers, flashing lifts attachments, HIGH scales both.

        "Each tier contributes only the area that actually falls inside it, so a
        250-square-foot finding pays the first tier on 100 square feet and the
        second tier on 150."

        "Each affected attachment or flashing costs 4,200 cents, and that whole
        attachment subtotal is multiplied by 1.25 when the `finding_type` is
        `FLASHING_FAILURE`, and by 1.00 for every other finding type."

        "The published multipliers are 1.00 for `LOW`, 1.15 for `MEDIUM`, 1.40 for
        `HIGH` and 1.75 for `CRITICAL`."

        Design: Difficulty/combinatorial_formula/deck_upgrade_cost_mode_a_tier_straddle_flashing_surcharge_and_floor_beating_cap
        """
        ctx = _setup_two_scoped_findings()
        scoped_a = ctx["scoped_a"]

        assert scoped_a["upgrade_cost_cents"] == 723520, (
            "area 100x950 + 200x780 + 120x640 = 327800, attachments 36x4200x1.25 = "
            "189000, and HIGH scales the 516800 sum by 1.40 to 723520 cents, got "
            f"{scoped_a['upgrade_cost_cents']}"
        )
        assert scoped_a["status"] == "UPGRADE_SCOPED", (
            f"SCOPE takes an OPEN finding to UPGRADE_SCOPED, got {scoped_a['status']}"
        )
        assert scoped_a["scoped_by_party_id"] == ctx["roofer_id"], (
            "scoped_by_party_id must record the acting roofer, got "
            f"{scoped_a['scoped_by_party_id']}"
        )

    def test_attachment_floor_out_ranks_the_cap(self):
        """The cap/floor nest is not a plain clamp: the floor may exceed the cap.

        "The interaction is deliberate: when the attachment subtotal alone exceeds
        the cap, the floor wins and the result legitimately exceeds 2,500,000
        cents."

        Design: Difficulty/combinatorial_formula/deck_upgrade_cost_mode_a_tier_straddle_flashing_surcharge_and_floor_beating_cap
        """
        ctx = _setup_two_scoped_findings()
        scoped_b = ctx["scoped_b"]

        assert scoped_b["upgrade_cost_cents"] == 3150000, (
            "the 600x4200x1.25 = 3150000-cent attachment floor beats the capped "
            f"2500000 raw amount, got {scoped_b['upgrade_cost_cents']}"
        )
        assert scoped_b["upgrade_cost_cents"] > 2500000, (
            "the published result must legitimately exceed the 2,500,000-cent cap, "
            f"got {scoped_b['upgrade_cost_cents']}"
        )

    def test_project_rolls_up_both_scoped_costs_and_stays_restricted(self):
        """The project total sums the scoped findings; the HIGH finding restricts.

        "The project's `scoped_upgrade_cost_cents` — the sum of
        `upgrade_cost_cents` over the project's findings whose `status` is
        `UPGRADE_SCOPED` or `UPGRADE_COMPLETED` — plus the newly computed cost for
        this finding must not exceed `upgrade_budget_cents`; when it would, the
        scope is refused with `ERR_UPGRADE_BUDGET_EXCEEDED` (HTTP 402)."

        "If the project is not `FROZEN`, the posture is `RESTRICTED` when at least
        one of these four conditions holds: the project has a deck finding whose
        `severity` is `HIGH` and whose `status` is either `OPEN` or
        `UPGRADE_SCOPED`; the project has a permit application whose `status` is
        either `DRAFT` or `SUBMITTED` and whose jurisdiction has
        `repermit_required_for_reinstall` set to true; some inspection booked under
        any permit application of the project has `status` `FAILED` or
        `CORRECTION_REQUIRED`; or the project's `weather_abort_count` has reached
        two or more."

        Design: Difficulty/combinatorial_formula/deck_upgrade_cost_mode_a_tier_straddle_flashing_surcharge_and_floor_beating_cap
        """
        ctx = _setup_two_scoped_findings()
        project = ctx["project"]

        assert project["scoped_upgrade_cost_cents"] == 3873520, (
            "723520 + 3150000 = 3873520 cents of scoped upgrade, got "
            f"{project['scoped_upgrade_cost_cents']}"
        )
        assert project["posture"] == "RESTRICTED", (
            "an UPGRADE_SCOPED HIGH finding restricts but does not freeze, got "
            f"{project['posture']}"
        )


# --------------------------------------------------------------------------
# Final credit: round per calendar day, then sum
# --------------------------------------------------------------------------
class TestFinalCreditPerDayRounding:
    def test_weather_aborted_dates_halve_their_day_factor(self):
        """Only WEATHER_ABORTED windows halve the dates their interval covers.

        "For each date in turn, determine a day factor: it is 0.5 when there exists
        a work window on this project whose `status` is `WEATHER_ABORTED` and whose
        interval covers that date — meaning the date of the window's `start_utc` is
        at or before the date in question and the date in question is at or before
        the date of the window's `end_utc` — and 1.0 otherwise."

        Design: Difficulty/combinatorial_formula/final_credit_mode_b_rounds_per_calendar_day_before_summing
        """
        ctx = _setup_three_halved_outage_dates()
        project = ctx["commissioned"]

        assert project["phase"] == "COMMISSIONED", (
            "the project must be COMMISSIONED before settlement, got phase "
            f"{project['phase']}"
        )
        assert project["weather_abort_count"] == 3, (
            f"three windows were aborted, got {project['weather_abort_count']}"
        )
        assert project["downtime_days_actual"] == 7, (
            "2026-08-03 .. 2026-08-09 inclusive is 7 distinct UTC dates, got "
            f"{project['downtime_days_actual']}"
        )

    def test_rounding_per_day_before_summing_is_observable(self):
        """Four whole days at 585 plus three halved days at 292 makes 3216, not 3215.

        "The rounding order is pinned: rounding once per calendar day *before*
        summing is correct, and summing the unrounded day amounts and rounding once
        at the end is wrong."

        Design: Difficulty/combinatorial_formula/final_credit_mode_b_rounds_per_calendar_day_before_summing
        """
        ctx = _setup_three_halved_outage_dates()
        project_id = ctx["project_id"]

        settle_credit(project_id)
        project = refresh_project(project_id)

        assert project["final_credit_cents"] == 3216, (
            "4 x round_half_up(584.5) + 3 x round_half_up(292.25) = 4x585 + 3x292 = "
            f"3216 cents, got {project['final_credit_cents']}"
        )
        assert project["final_credit_cents"] != 3215, (
            "3215 is the figure produced by summing the unrounded day amounts and "
            "rounding once at the end, which the specification calls wrong"
        )

    def test_settlement_releases_the_unspent_reservation(self):
        """A lower final figure leaves the authorized total alone and releases the rest.

        "On success the computed figure is written to `final_credit_cents`; the
        difference between `final_credit_cents` and `credit_reserved_cents` is
        taken, and when that difference is positive it is added to
        `credit_authorized_cents` (a negative or zero difference leaves the
        authorized total alone); `credit_settled_cents` is set to
        `final_credit_cents`; `credit_reserved_cents` is set to zero;
        `credit_released_cents` is set to `credit_authorized_cents` minus
        `credit_settled_cents`; and the project's `phase` moves `COMMISSIONED →
        CLOSED`."

        Design: Difficulty/combinatorial_formula/final_credit_mode_b_rounds_per_calendar_day_before_summing
        """
        ctx = _setup_three_halved_outage_dates()
        project_id = ctx["project_id"]

        settle_credit(project_id)
        project = refresh_project(project_id)

        assert project["credit_authorized_cents"] == 5261, (
            "the provisional reservation of 5261 cents is not topped up by a lower "
            f"final figure, got {project['credit_authorized_cents']}"
        )
        assert project["credit_settled_cents"] == 3216, (
            f"credit_settled_cents must equal final_credit_cents, got "
            f"{project['credit_settled_cents']}"
        )
        assert project["credit_released_cents"] == 2045, (
            "5261 authorized minus 3216 settled leaves 2045 released, got "
            f"{project['credit_released_cents']}"
        )
        assert project["phase"] == "CLOSED", (
            f"settlement must close the project, got phase {project['phase']}"
        )
        assert_credit_ledger_identity(project)


# --------------------------------------------------------------------------
# Sourcing tolerance: the step-two snapshot precedes the step-five reset
# --------------------------------------------------------------------------
class TestSourcingToleranceSnapshotOrder:
    def test_watt_delta_is_signed_and_two_decimal(self):
        """426 W against 410 W of record is a +3.90 percent delta.

        "Step one computes `watt_delta_pct` as the offered watts minus the unit's
        `rated_watts` of record, divided by that same `rated_watts` of record,
        multiplied by 100, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/sourcing_tolerance_mode_c_reads_warranty_snapshot_before_the_same_field_is_reset
        """
        ctx = _setup_sourcing_order_on_notified_project()
        order = ctx["order"]

        assert order["watt_delta_pct"] == pytest.approx(3.90, abs=0.01), (
            "(426 - 410) / 410 x 100 rounds half up to 3.90, got "
            f"{order['watt_delta_pct']}"
        )

    def test_tolerance_reads_the_filed_snapshot_and_classifies_compatible(self):
        """The FILED bonus applies because step two snapshots before step five.

        "Step two computes `tolerance_pct` from a snapshot of the project taken
        **before** step five mutates it."

        "When the snapshot of the project's `warranty_notice_status` is `FILED`, a
        further 1.00 percent is added, because a notified manufacturer tolerates
        more variation."

        "Otherwise it is `COMPATIBLE` when the `offered_manufacturer` still equals
        the unit's `manufacturer` of record and the absolute value of
        `watt_delta_pct` is less than or equal to `tolerance_pct` — a delta exactly
        equal to the tolerance is `COMPATIBLE`."

        Design: Difficulty/combinatorial_formula/sourcing_tolerance_mode_c_reads_warranty_snapshot_before_the_same_field_is_reset
        """
        ctx = _setup_sourcing_order_on_notified_project()
        order = ctx["order"]

        assert order["tolerance_pct"] == pytest.approx(4.00, abs=0.01), (
            "base 3.00 plus the 1.00 FILED-notice bonus is 4.00 percent, got "
            f"{order['tolerance_pct']}"
        )
        assert order["match_class"] == "COMPATIBLE", (
            "same manufacturer, different model code and a 3.90 delta inside the "
            f"4.00 tolerance is COMPATIBLE, got {order['match_class']}"
        )
        assert order["status"] == "PENDING_REVIEW", (
            "a COMPATIBLE match on a LEASE project awaits the system owner, got "
            f"{order['status']}"
        )

    def test_step_five_resets_the_notice_status_but_keeps_the_reference(self):
        """The same request that read FILED then writes the status back to PENDING.

        "When the resulting `match_class` is anything other than `EXACT` and the
        project's `warranty_notice_status` is `FILED`, that status is reset to
        `PENDING`, because the manufacturer must be re-notified that the model of
        record changed."

        Design: Difficulty/combinatorial_formula/sourcing_tolerance_mode_c_reads_warranty_snapshot_before_the_same_field_is_reset
        """
        ctx = _setup_sourcing_order_on_notified_project()
        project = ctx["project"]

        assert project["warranty_notice_status"] == "PENDING", (
            "a non-exact sourcing order must reset a FILED notice status, got "
            f"{project['warranty_notice_status']}"
        )
        assert project["warranty_notice_reference"] == "MN-2026-0419", (
            "the recorded manufacturer case reference is not cleared by the reset, "
            f"got {project['warranty_notice_reference']}"
        )
