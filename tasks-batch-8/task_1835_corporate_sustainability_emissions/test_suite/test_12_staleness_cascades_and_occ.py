"""The three-link staleness cascade (inventory -> targets -> questionnaires)
from approval, voiding, retirement, and void-retirement triggers, plus the
optimistic-concurrency guard on inventory recalculation."""
from test_helpers import (
    MANAGER, ApiErrorId, activate_target, answer_section, approve_record,
    create_approved_record, cycle_version, get_inventory_for_cycle,
    get_questionnaire, get_target, make_collecting_cycle,
    make_fully_answered_cdp, make_factor, make_instrument, make_site,
    make_target, recalc_inventory, recalc_inventory_payload, retire_instrument,
    review_record, submit_record, transition_payload, validate_error,
    validate_success,
)

CASCADE_QUOTE = (
    "In the heavier tier — activity record approval and voiding, engagement "
    "acceptance, instrument retirement and void-retirement, and both "
    "cycle-reopen edges — a three-link cascade fires: the inventory drops to "
    "`STALE` (link 1); every `ACTIVE` emission target watching the cycle "
    "flips its `trajectory_status` to `NOT_EVALUATED`, because the verdict "
    "depended on the now-stale totals (link 2); and each questionnaire "
    "response of the cycle in `DRAFT`, `IN_REVIEW`, or `APPROVED` with an "
    "answered EMISSIONS section has `emissions_section_stale` set to true, "
    "warning that its disclosed figures may no longer match (link 3)."
)


def _assert_cascade_fired(cycle_id, target_id, questionnaire_id):
    assert get_inventory_for_cycle(cycle_id)["status"] == "STALE", "link 1: inventory STALE"
    assert get_target(target_id)["trajectory_status"] == "NOT_EVALUATED", (
        "link 2: watching target NOT_EVALUATED"
    )
    assert get_questionnaire(questionnaire_id)["emissions_section_stale"] is True, (
        "link 3: questionnaire emissions section stale"
    )


def _fuel_lab():
    """Collecting cycle + fully answered CDP questionnaire + ACTIVE SCOPE1_2_3
    target (base 1000, 2025 -> 2030); no locked 2025 cycle exists."""
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    questionnaire = make_fully_answered_cdp(cycle["id"])
    target = activate_target(make_target()["id"])
    return site, factor, cycle, questionnaire, target


def test_approval_fires_three_link_cascade(api, manager_headers):
    """PRD §2.6: "In the heavier tier — activity record approval and voiding,
    engagement acceptance, instrument retirement and void-retirement, and
    both cycle-reopen edges — a three-link cascade fires: the inventory drops
    to `STALE` (link 1); every `ACTIVE` emission target watching the cycle
    flips its `trajectory_status` to `NOT_EVALUATED`, because the verdict
    depended on the now-stale totals (link 2); and each questionnaire
    response of the cycle in `DRAFT`, `IN_REVIEW`, or `APPROVED` with an
    answered EMISSIONS section has `emissions_section_stale` set to true,
    warning that its disclosed figures may no longer match (link 3)."

    Design: Difficulty/transitive_cascade/approval_cascade_inventory_target_questionnaire
    """
    site, factor, cycle, questionnaire, target = _fuel_lab()
    recalc_inventory(cycle["id"])
    assert get_target(target["id"])["trajectory_status"] == "ON_TRACK", (
        "zero-record recalc: actual reduction 100.0% >= required 10.0% - 2.0"
    )
    assert get_questionnaire(questionnaire["id"])["emissions_section_stale"] is False

    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=100)
    review_record(record["id"])
    approve_record(record["id"])

    _assert_cascade_fired(cycle["id"], target["id"], questionnaire["id"])


def test_void_fires_three_link_cascade(api, manager_headers):
    """PRD §3.3: "A `SustainabilityManager` may later void an approved record
    — `APPROVED` to the terminal `VOIDED` — which is the compensating
    reversal of approval: the record leaves the approved set, the same
    three-link cascade fires, `readiness_pct` is recomputed, and again both
    versions advance."

    Design: Difficulty/transitive_cascade/approval_cascade_inventory_target_questionnaire
    """
    site, factor, cycle, questionnaire, target = _fuel_lab()
    record = create_approved_record(cycle["id"], site["id"], factor["id"], quantity=100)
    # Settle the system: recalc re-evaluates the target; re-answering clears
    # the flag set by the approval cascade.
    recalc_inventory(cycle["id"])
    assert get_target(target["id"])["trajectory_status"] == "ON_TRACK"
    answer_section(questionnaire["id"], "EMISSIONS", "revised emissions text")
    assert get_questionnaire(questionnaire["id"])["emissions_section_stale"] is False

    voided = validate_success(
        api.transition_activity_record(record["id"], transition_payload("VOIDED"), MANAGER)
    )
    assert voided["status"] == "VOIDED"
    _assert_cascade_fired(cycle["id"], target["id"], questionnaire["id"])


def _electricity_lab():
    """Collecting cycle + grid 0.4 / residual 0.5 factors for CA + fully
    answered CDP questionnaire + ACTIVE SCOPE1_2 target + one APPROVED
    ELECTRICITY record of 100 MWh."""
    site = make_site(name="Alpha", grid_region_code="CA")
    grid = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    make_factor(
        scope_category="SCOPE2_RESIDUAL_MIX", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.5,
    )
    cycle = make_collecting_cycle()
    questionnaire = make_fully_answered_cdp(cycle["id"])
    target = activate_target(make_target(scope_coverage="SCOPE1_2")["id"])
    create_approved_record(
        cycle["id"], site["id"], grid["id"], activity_type="ELECTRICITY",
        quantity=100, unit="MWh",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    return site, cycle, questionnaire, target


def test_retirement_fires_three_link_cascade(api, manager_headers):
    """PRD §3.6: "Retirement records the linkage in `retired_for_cycle_id`
    and `retired_for_site_id`, fires the full three-link cascade of §2.6, and
    advances both the instrument's and the cycle's versions."

    Design: Difficulty/transitive_cascade/retirement_cascade_inventory_target_questionnaire
    """
    site, cycle, questionnaire, target = _electricity_lab()
    # Settle: recalc (market 50.0 -> actual 95.0% >= 8.0% -> ON_TRACK) and
    # clear the flag the approval cascade set.
    recalc_inventory(cycle["id"])
    assert get_target(target["id"])["trajectory_status"] == "ON_TRACK"
    answer_section(questionnaire["id"], "EMISSIONS", "revised emissions text")
    assert get_questionnaire(questionnaire["id"])["emissions_section_stale"] is False

    instrument = make_instrument(serial_number="S-200", technology="WIND",
                                 vintage_year=2026, quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])

    _assert_cascade_fired(cycle["id"], target["id"], questionnaire["id"])


def test_void_retirement_fires_three_link_cascade(api, manager_headers):
    """PRD §3.6: "While the formerly linked cycle is still collecting, a
    manager may reverse a retirement: void-retirement moves the instrument
    from `RETIRED` back to `PROCURED`, clears both `retired_for_cycle_id` and
    `retired_for_site_id` to null, fires the compensating three-link cascade
    against that cycle, and advances both versions."

    Design: Difficulty/transitive_cascade/retirement_cascade_inventory_target_questionnaire
    """
    site, cycle, questionnaire, target = _electricity_lab()
    instrument = make_instrument(serial_number="S-201", technology="WIND",
                                 vintage_year=2026, quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])
    # Settle after the retirement cascade.
    recalc_inventory(cycle["id"])
    assert get_target(target["id"])["trajectory_status"] == "ON_TRACK"
    answer_section(questionnaire["id"], "EMISSIONS", "revised emissions text")
    assert get_questionnaire(questionnaire["id"])["emissions_section_stale"] is False

    validate_success(api.void_retirement(instrument["id"], MANAGER))
    _assert_cascade_fired(cycle["id"], target["id"], questionnaire["id"])


def test_recalculate_with_stale_cycle_version_returns_412(api, manager_headers):
    """PRD §2.8: "The inventory-recalculation write requires
    `expected_cycle_version`, carrying the client's last observed `version`
    of the reporting cycle; if the cycle's current `version` has advanced
    past the supplied value — because another writer approved a record,
    retired an instrument, or otherwise bumped it since the client last read
    the cycle — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), so
    the client cannot recompute against an input set it has not observed."

    Design: Corner/cross_cutting_layers/recalculate_with_stale_cycle_version_returns_412
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    stale_version = cycle_version(cycle["id"])
    # The approval cascade advances the cycle version past the observed one.
    create_approved_record(cycle["id"], site["id"], factor["id"], quantity=10)

    stale = api.recalculate_inventory(
        cycle["id"], recalc_inventory_payload(stale_version), manager_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = validate_success(
        api.recalculate_inventory(
            cycle["id"], recalc_inventory_payload(cycle_version(cycle["id"])),
            manager_headers,
        )
    )
    assert fresh["status"] == "CURRENT"
