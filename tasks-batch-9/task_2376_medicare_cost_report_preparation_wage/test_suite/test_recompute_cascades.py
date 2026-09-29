"""The multi-link recompute cascades: a completed stepdown reaching the
settlement flag, and an incorporated audit exception staling the allocation."""

from test_helpers import (
    assert_money_equals,
    assert_ratio_equals,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    read_cost_center,
    read_cost_report,
    respond_to_audit_adjustment,
    resolve_audit_adjustment,
    run_stepdown,
    setup_proposed_audit_adjustment,
    setup_tentative_settlement,
)


def test_completed_run_reaches_the_uncompensated_care_figures(api):
    """A second stepdown run rewrites the cost centers, the report ratio and
    then the uncompensated care data set that hangs off that ratio.

    PRD 2.7: "Link three, driven by the new `cost_to_charge_ratio`, recomputes the report's `UccDataSet` — its snapshot `cost_to_charge_ratio`, its `uncompensated_care_cost_cents` and its `ucc_payment_cents` — and clears that data set's `recompute_required` back to false."

    Design: Difficulty/transitive_cascade/stepdown_completion_cascades_through_ucc_to_settlement_flag
    """
    scenario = setup_tentative_settlement(api)

    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")

    ancillary = read_cost_center(api, scenario, scenario["cc_ancillary"])
    assert_money_equals(ancillary["allocated_in_cents"], 45047620, "allocated_in_cents")
    assert_money_equals(
        ancillary["allocated_total_cost_cents"], 165047620, "allocated_total_cost_cents"
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 449047620, "total_allowable_cost_cents"
    )
    assert_ratio_equals(report["cost_to_charge_ratio"], 1.122619, "cost_to_charge_ratio")
    assert report["allocation_status"] == "CURRENT"

    ucc = validate_success(
        api.get_ucc_data_set(scenario["ucc_data_set_id"], scenario["analyst"])
    )
    assert_ratio_equals(ucc["cost_to_charge_ratio"], 1.122619, "ucc cost_to_charge_ratio")
    assert_money_equals(
        ucc["uncompensated_care_cost_cents"], 51404760, "uncompensated_care_cost_cents"
    )
    assert_money_equals(ucc["ucc_payment_cents"], 10280952, "ucc_payment_cents")
    assert ucc["recompute_required"] is False
    assert ucc["dsh_patient_percentage"] == 0.1500
    assert ucc["dsh_eligible"] is True


def test_settlement_snapshot_is_flagged_rather_than_rewritten(api):
    """The cascade only raises recompute_required on the issued settlement; its
    basis and its payable amount keep the figures captured at issuance.

    PRD 2.7: "Link four, driven by that data set recompute, sets `recompute_required` to true on every `Settlement` of the report whose `status` is `ISSUED` and whose `basis_allowable_cost_cents` no longer equals the newly computed `total_allowable_cost_cents`."

    Design: Difficulty/transitive_cascade/stepdown_completion_cascades_through_ucc_to_settlement_flag
    """
    scenario = setup_tentative_settlement(api)
    single_run_id = scenario["single_run"]["id"]
    before = validate_success(
        api.get_settlement(scenario["tentative_settlement_id"], scenario["auditor"])
    )
    assert before["recompute_required"] is False

    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")

    after = validate_success(
        api.get_settlement(scenario["tentative_settlement_id"], scenario["auditor"])
    )
    assert after["recompute_required"] is True
    assert after["status"] == "ISSUED"
    assert_money_equals(
        after["basis_allowable_cost_cents"], 448666667, "basis_allowable_cost_cents"
    )
    assert_money_equals(
        after["amount_due_provider_cents"], 119600000, "amount_due_provider_cents"
    )

    superseded = validate_success(api.get_stepdown_run(single_run_id, scenario["analyst"]))
    assert superseded["status"] == "STALE"
    assert superseded["stale_reason"] == "SUPERSEDED_BY_NEWER_RUN"


def test_incorporated_exception_mints_an_audit_sourced_workpaper_entry(api):
    """Incorporating an accepted exception synthesizes one AUDIT workpaper entry
    and moves only the target center's adjustment column.

    PRD 3.8: "Link one creates a workpaper entry of type `ADJUSTMENT` with `source` `AUDIT`, its `source_audit_adjustment_id` pointing back at the adjustment and a single leg placing the proposed amount on the adjustment's target cost center."

    Design: Difficulty/transitive_cascade/audit_adjustment_incorporation_cascades_to_stale_allocation
    """
    scenario = setup_proposed_audit_adjustment(api)
    respond_to_audit_adjustment(
        api, scenario, "ACCEPT", "Provider concurs with exception AE-14"
    )

    adjustment = resolve_audit_adjustment(api, scenario, "INCORPORATE")
    assert adjustment["status"] == "INCORPORATED"
    assert adjustment["proposed_by_user_id"] == "mac-auditor-1"
    assert adjustment["resolved_by_user_id"] == "mac-auditor-2"

    entries, meta = validate_paginated(
        api.list_audit_adjustment_workpaper_entries(
            scenario["adjustment_id"], scenario["auditor"]
        )
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["entry_type"] == "ADJUSTMENT"
    assert entry["source"] == "AUDIT"
    assert entry["status"] == "ACTIVE"
    assert entry["source_audit_adjustment_id"] == scenario["adjustment_id"]
    assert len(entry["legs"]) == 1
    assert entry["legs"][0]["cost_center_id"] == scenario["cc_ancillary"]
    assert_money_equals(entry["legs"][0]["amount_cents"], -5000000, "leg amount")

    ancillary = read_cost_center(api, scenario, scenario["cc_ancillary"])
    assert_money_equals(
        ancillary["adjustment_amount_cents"], -5000000, "adjustment_amount_cents"
    )
    assert_money_equals(
        ancillary["post_adjustment_cost_cents"], 115000000, "post_adjustment_cost_cents"
    )
    assert_money_equals(ancillary["direct_cost_cents"], 120000000, "direct_cost_cents")
    assert_money_equals(
        ancillary["reclassified_amount_cents"], 0, "reclassified_amount_cents"
    )


def test_audit_incorporation_stales_the_allocation_and_flags_the_settlement(api):
    """The synthesized entry demotes the completed run, stales the report and
    raises the settlement flag, without moving allowable cost.

    PRD 2.7: "Whenever any input to that allocation changes, the run is demoted to `STALE`, its `stale_reason` records why, and `allocation_status` becomes `STALE` unless a newer `COMPLETED` run already exists."

    Design: Difficulty/transitive_cascade/audit_adjustment_incorporation_cascades_to_stale_allocation
    """
    scenario = setup_proposed_audit_adjustment(api)
    single_run_id = scenario["single_run"]["id"]
    respond_to_audit_adjustment(
        api, scenario, "ACCEPT", "Provider concurs with exception AE-14"
    )

    resolve_audit_adjustment(api, scenario, "INCORPORATE")

    run = validate_success(api.get_stepdown_run(single_run_id, scenario["analyst"]))
    assert run["status"] == "STALE"
    assert run["stale_reason"] == "WORKPAPER_ENTRY_CHANGED"

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "STALE"
    assert_money_equals(
        report["total_allowable_cost_cents"], 448666667, "total_allowable_cost_cents"
    )

    settlement = validate_success(
        api.get_settlement(scenario["tentative_settlement_id"], scenario["auditor"])
    )
    assert settlement["recompute_required"] is True
