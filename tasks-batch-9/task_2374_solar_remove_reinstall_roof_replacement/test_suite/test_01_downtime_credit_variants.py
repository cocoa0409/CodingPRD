"""Two-variant calculations: the downtime credit and the module warranty verdict.

Both families exercise the same input set through two different published rule
sets and prove the two rule sets disagree.
"""

import pytest

from test_helpers import (
    add_bin,
    add_circuit,
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


def _setup_downtime_reconciliation() -> dict:
    """LEASE project taken to COMMISSIONED with one weather-aborted outage date.

    baseline_daily_kwh 41.75, downtime_days_estimated 9, de-energized
    2026-08-03T09:00:00Z, re-energized 2026-08-09T15:00:00Z, and exactly one
    WEATHER_ABORTED roofing window covering the single date 2026-08-05.
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

    file_warranty_notice(project_id, notice_reference="MN-2026-0417")
    collect_all_consents(project, parties)

    circuit = add_circuit(project_id, circuit_label="S1", module_count=1, dc_kw=0.41)
    unit = add_unit(
        project_id, circuit["id"], crew_id, serial_number="SN-0001", rated_watts=410
    )
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=4, climate_controlled=True
    )

    set_clock("2026-08-03T09:00:00Z")
    deenergize_circuit(
        circuit["id"],
        crew_id,
        True,
        isolation_note="AC disconnect open, DC taped and tagged",
    )
    at_deenergized = refresh_project(project_id)

    remove_unit(unit["id"], crew_id)
    store_unit(unit["id"], storage_bin["id"], crew_id)
    grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")

    window = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-05T13:00:00Z",
        end_utc="2026-08-05T21:00:00Z",
        weather_risk_score=60,
    )
    drive_window(
        window["id"],
        "WEATHER_ABORT",
        abort_reason="Monsoon cell over site, tear-off unsafe",
    )

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
        waiver_reason="Two fasteners re-seated during tear-off, no upgrade scope required",
    )

    set_clock("2026-08-09T15:00:00Z")
    reinstall_unit(unit["id"], crew_id)
    reenergize_circuit(circuit["id"], crew_id)

    return {
        "project_id": project_id,
        "at_deenergized": at_deenergized,
        "commissioned": refresh_project(project_id),
    }


def _setup_opposite_warranty_verdicts() -> dict:
    """Two identical panels whose warranty_variant is pinned two hours apart.

    Panel u1 comes off while warranty_notice_status is still PENDING; the notice
    is then filed and panel u2 comes off on the same calendar date. Both sit 20
    whole UTC days in the same climate-controlled bin and both grade SERVICEABLE.
    Returns the two reinstalled units and the rolled-up project.
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

    collect_all_consents(project, parties)

    circuit = add_circuit(project_id, circuit_label="S1", module_count=2, dc_kw=0.82)
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=4, climate_controlled=True
    )
    unit_1 = add_unit(
        project_id, circuit["id"], crew_id, serial_number="SN-0001", rated_watts=410
    )
    unit_2 = add_unit(
        project_id, circuit["id"], crew_id, serial_number="SN-0002", rated_watts=410
    )

    set_clock("2026-08-03T09:00:00Z")
    deenergize_circuit(circuit["id"], crew_id, True)

    # u1 leaves the roof while the notice is still PENDING -> INSTALLER_LENIENT.
    removed_1 = remove_unit(unit_1["id"], crew_id)
    file_warranty_notice(project_id, notice_reference="MN-2026-0417")
    # u2 leaves the roof two hours later, notice now FILED -> MANUFACTURER_STRICT.
    set_clock("2026-08-03T11:00:00Z")
    removed_2 = remove_unit(unit_2["id"], crew_id)

    store_unit(unit_1["id"], storage_bin["id"], crew_id)
    store_unit(unit_2["id"], storage_bin["id"], crew_id)
    grade_unit(unit_1["id"], crew_id, "SERVICEABLE", "RETAIN")
    grade_unit(unit_2["id"], crew_id, "SERVICEABLE", "RETAIN")

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

    set_clock("2026-08-23T10:00:00Z")
    reinstalled_1 = reinstall_unit(unit_1["id"], crew_id)
    reinstalled_2 = reinstall_unit(unit_2["id"], crew_id)

    return {
        "project_id": project_id,
        "removed_1": removed_1,
        "removed_2": removed_2,
        "unit_1": reinstalled_1,
        "unit_2": reinstalled_2,
        "project": refresh_project(project_id),
    }


# --------------------------------------------------------------------------
# The two downtime-credit variants
# --------------------------------------------------------------------------
class TestDowntimeCreditVariants:
    def test_provisional_variant_prices_only_the_estimated_days(self):
        """The forward-looking variant reads three project fields and rounds once.

        "It is the `baseline_daily_kwh` multiplied by `downtime_days_estimated`,
        multiplied by 14 cents, multiplied by the ownership factor, with a
        **single** rounding half up to whole cents applied to that entire product
        at the end."

        Design: Difficulty/dual_variant_calc/downtime_credit_provisional_forward_looking_vs_final_chronological_reconciliation
        """
        ctx = _setup_downtime_reconciliation()
        at_deenergized = ctx["at_deenergized"]

        assert at_deenergized["phase"] == "DEENERGIZED", (
            "isolating the only circuit must advance AUTHORIZED -> DEENERGIZED, "
            f"got phase {at_deenergized['phase']}"
        )
        assert at_deenergized["provisional_credit_cents"] == 5261, (
            "41.75 kWh x 9 estimated days x 14 cents x LEASE factor 1.00 rounds "
            f"half up to 5261 cents, got {at_deenergized['provisional_credit_cents']}"
        )
        assert at_deenergized["credit_authorized_cents"] == 5261, (
            "reserving the provisional credit adds it to the authorized account, "
            f"got {at_deenergized['credit_authorized_cents']}"
        )
        assert at_deenergized["credit_reserved_cents"] == 5261, (
            "reserving the provisional credit adds it to the reserved account, "
            f"got {at_deenergized['credit_reserved_cents']}"
        )
        assert_credit_ledger_identity(at_deenergized)

    def test_final_variant_replays_the_actual_dates_and_diverges(self):
        """The chronological variant halves the weather-aborted date and rounds daily.

        "That day's cents are the `baseline_daily_kwh` multiplied by 14 cents,
        multiplied by the ownership factor, multiplied by that day's factor,
        **rounded half up to whole cents for that day**."

        Design: Difficulty/dual_variant_calc/downtime_credit_provisional_forward_looking_vs_final_chronological_reconciliation
        """
        ctx = _setup_downtime_reconciliation()
        project_id = ctx["project_id"]

        assert ctx["commissioned"]["phase"] == "COMMISSIONED", (
            "re-energizing the only circuit must advance REINSTALL -> COMMISSIONED, "
            f"got phase {ctx['commissioned']['phase']}"
        )

        settle_credit(
            project_id,
            settlement_note="Lease downtime credit trued up against actual outage dates",
        )
        project = refresh_project(project_id)

        assert project["downtime_days_actual"] == 7, (
            "2026-08-03 .. 2026-08-09 inclusive is 7 distinct UTC dates, got "
            f"{project['downtime_days_actual']}"
        )
        assert project["final_credit_cents"] == 3802, (
            "six full days at 585 cents plus the weather-aborted 2026-08-05 at 292 "
            f"cents is 3802 cents, got {project['final_credit_cents']}"
        )
        assert project["provisional_credit_cents"] == 5261, (
            "the provisional figure must survive settlement unchanged, got "
            f"{project['provisional_credit_cents']}"
        )
        assert project["final_credit_cents"] != project["provisional_credit_cents"], (
            "the two variants must disagree on this project: final="
            f"{project['final_credit_cents']} provisional="
            f"{project['provisional_credit_cents']}"
        )

    def test_settlement_books_the_divergence_as_released_credit(self):
        """Settlement moves the reserved balance out and releases the difference.

        "On success the computed figure is written to `final_credit_cents`; the
        difference between `final_credit_cents` and `credit_reserved_cents` is
        taken, and when that difference is positive it is added to
        `credit_authorized_cents` (a negative or zero difference leaves the
        authorized total alone); `credit_settled_cents` is set to
        `final_credit_cents`; `credit_reserved_cents` is set to zero;
        `credit_released_cents` is set to `credit_authorized_cents` minus
        `credit_settled_cents`; and the project's `phase` moves `COMMISSIONED →
        CLOSED`."

        Design: Difficulty/dual_variant_calc/downtime_credit_provisional_forward_looking_vs_final_chronological_reconciliation
        """
        ctx = _setup_downtime_reconciliation()
        project_id = ctx["project_id"]

        settle_credit(
            project_id,
            settlement_note="Lease downtime credit trued up against actual outage dates",
        )
        project = refresh_project(project_id)

        assert project["credit_authorized_cents"] == 5261, (
            "the final figure came out lower than the reservation, so the authorized "
            f"total stays at 5261, got {project['credit_authorized_cents']}"
        )
        assert project["credit_settled_cents"] == 3802, (
            "credit_settled_cents must equal final_credit_cents, got "
            f"{project['credit_settled_cents']}"
        )
        assert project["credit_reserved_cents"] == 0, (
            "settlement zeroes the reserved account, got "
            f"{project['credit_reserved_cents']}"
        )
        assert project["credit_released_cents"] == 1459, (
            "5261 authorized minus 3802 settled leaves 1459 released, got "
            f"{project['credit_released_cents']}"
        )
        assert project["phase"] == "CLOSED", (
            f"settlement must close the project, got phase {project['phase']}"
        )
        assert_credit_ledger_identity(project)


# --------------------------------------------------------------------------
# The two warranty rule sets
# --------------------------------------------------------------------------
class TestWarrantyVariantVerdicts:
    def test_removal_pins_the_variant_from_the_notice_status_at_that_instant(self):
        """The variant is decided by the notice status when the unit comes off.

        "Removal also **pins the warranty rule set** that will judge this unit
        later: `warranty_variant` becomes `MANUFACTURER_STRICT` when the project's
        `warranty_notice_status` is `FILED` at that instant, and
        `INSTALLER_LENIENT` otherwise."

        Design: Difficulty/dual_variant_calc/unit_warranty_manufacturer_strict_vs_installer_lenient_opposite_verdicts
        """
        ctx = _setup_opposite_warranty_verdicts()

        assert ctx["removed_1"]["warranty_variant"] == "INSTALLER_LENIENT", (
            "u1 was removed while the notice was still PENDING, so the lenient "
            f"variant must be pinned, got {ctx['removed_1']['warranty_variant']}"
        )
        assert ctx["removed_2"]["warranty_variant"] == "MANUFACTURER_STRICT", (
            "u2 was removed after the notice was FILED, so the strict variant must "
            f"be pinned, got {ctx['removed_2']['warranty_variant']}"
        )
        assert ctx["unit_1"]["warranty_variant"] == "INSTALLER_LENIENT", (
            "the pinned variant must survive storage and reinstall, got "
            f"{ctx['unit_1']['warranty_variant']}"
        )
        assert ctx["unit_2"]["warranty_variant"] == "MANUFACTURER_STRICT", (
            "the pinned variant must survive storage and reinstall, got "
            f"{ctx['unit_2']['warranty_variant']}"
        )

    def test_identical_inputs_reach_opposite_verdicts(self):
        """20 days in a climate-controlled bin passes strict and fails lenient.

        "The two variants therefore return opposite verdicts on identical inputs —
        a `REPLACED` unit stored 20 days in a climate-controlled bin is preserved
        under the strict variant and not preserved under the lenient one."

        Design: Difficulty/dual_variant_calc/unit_warranty_manufacturer_strict_vs_installer_lenient_opposite_verdicts
        """
        ctx = _setup_opposite_warranty_verdicts()
        unit_1, unit_2 = ctx["unit_1"], ctx["unit_2"]

        assert unit_1["off_roof_days"] == 20, (
            f"2026-08-03 to 2026-08-23 is 20 whole UTC days, got {unit_1['off_roof_days']}"
        )
        assert unit_2["off_roof_days"] == 20, (
            f"2026-08-03 to 2026-08-23 is 20 whole UTC days, got {unit_2['off_roof_days']}"
        )
        assert unit_1["condition_grade"] == "SERVICEABLE", unit_1["condition_grade"]
        assert unit_2["condition_grade"] == "SERVICEABLE", unit_2["condition_grade"]

        assert unit_1["warranty_preserved"] is False, (
            "the lenient variant has a hard 14-day ceiling and no climate-control "
            f"escape hatch, got warranty_preserved={unit_1['warranty_preserved']}"
        )
        assert unit_2["warranty_preserved"] is True, (
            "the strict variant tolerates 20 days when storage beyond a fortnight "
            f"was climate controlled, got warranty_preserved={unit_2['warranty_preserved']}"
        )

    @pytest.mark.parametrize(
        "unit_key,expected_points",
        [("unit_1", 25), ("unit_2", 0)],
    )
    def test_risk_points_follow_the_variant_that_judged_the_unit(
        self, unit_key, expected_points
    ):
        """A failed lenient verdict is penalised harder than a passing strict one.

        "When `warranty_preserved` comes out true, the unit's
        `warranty_risk_points` is 0."

        "When it comes out false, `warranty_risk_points` is 10 under
        `MANUFACTURER_STRICT` and 25 under `INSTALLER_LENIENT` — the lenient
        variant carries the heavier penalty precisely because no notice was on
        file."

        Design: Difficulty/dual_variant_calc/unit_warranty_manufacturer_strict_vs_installer_lenient_opposite_verdicts
        """
        ctx = _setup_opposite_warranty_verdicts()
        unit = ctx[unit_key]

        assert unit["warranty_risk_points"] == expected_points, (
            f"{unit_key} carries variant {unit['warranty_variant']} with "
            f"warranty_preserved={unit['warranty_preserved']}, so "
            f"warranty_risk_points must be {expected_points}, got "
            f"{unit['warranty_risk_points']}"
        )

    def test_project_rollup_is_the_logical_and_of_the_reinstalled_units(self):
        """One unpreserved reinstalled unit drags the project flag false.

        "The project's `stored_unit_count`, `reinstalled_unit_count` and roll-up
        `warranty_preserved` are recomputed; the project-level flag is the logical
        AND of `warranty_preserved` across every unit of the project whose
        `handling_status` is `REINSTALLED`, taken in `created_at` ascending order,
        and it is true when that set is empty."

        Design: Difficulty/dual_variant_calc/unit_warranty_manufacturer_strict_vs_installer_lenient_opposite_verdicts
        """
        ctx = _setup_opposite_warranty_verdicts()
        project = ctx["project"]

        assert project["reinstalled_unit_count"] == 2, (
            "both panels went back on the roof, got "
            f"{project['reinstalled_unit_count']}"
        )
        assert project["warranty_preserved"] is False, (
            "the lenient panel is not preserved, so the AND over reinstalled units "
            f"must be false, got {project['warranty_preserved']}"
        )
