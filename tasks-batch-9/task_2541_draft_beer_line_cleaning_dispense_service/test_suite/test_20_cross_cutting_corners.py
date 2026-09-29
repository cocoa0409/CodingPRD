"""Corner cases where a global layer meets a workflow: the two version guards refusing a token the
caller's own earlier write invalidated, an aggregate threshold crossed by the second failure, and
the immediacy of every projection one write touches."""

from test_helpers import (
    AUDITOR_HEADERS,
    AbandonReason,
    AccountStatus,
    ActionTaken,
    ApiErrorId,
    BalanceRecordStatus,
    ChemicalType,
    ComplianceFlag,
    ComplianceResult,
    ComponentType,
    ConditionGrade,
    ContractStatus,
    DISPATCH_HEADERS,
    LineStatus,
    LotStatus,
    SuspendedReason,
    WorkStatus,
    assert_instant,
    assert_liters,
    assert_pct,
    assert_psi,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

_SECOND_LINE = {
    "line_number": 2,
    "run_length_feet": 24,
    "vertical_rise_feet": 3,
    "inner_diameter_inches": 0.25,
    "beer_style_group": "LAGER",
    "average_daily_throughput_liters": 9.0,
}


def test_a_second_contract_quoting_the_pre_activation_account_version_is_stale(api):
    """PRD §2.7: "If that value does not equal the account's current `version`, the create is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/corner_contract_create_carrying_the_pre_activation_account_version_is_stale
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    account = fixtures.create_account(api, venue_name="Anchor Alehouse")
    opening_version = account["version"]
    assert opening_version == 1

    first = fixtures.draft_contract(api, account["id"], opening_version)
    # Drafting increments the account once.
    assert fixtures.read_account(api, account["id"])["version"] == 2
    fixtures.activate_contract(api, first["id"])
    # Activation increments it again.
    current_version = fixtures.read_account(api, account["id"])["version"]
    assert current_version == 3

    stale_terms = factories.contract_payload(
        account["id"], opening_version, cleaning_frequency_days=28,
        contracted_line_count=6, per_line_rate_cents=4400,
    )
    validate_error(
        api.create_contract(stale_terms, DISPATCH_HEADERS),
        ApiErrorId.STALE_ACCOUNT_VERSION,
        412,
    )

    second = fixtures.draft_contract(
        api, account["id"], current_version, cleaning_frequency_days=28,
        contracted_line_count=6, per_line_rate_cents=4400,
    )
    assert second["status"] == ContractStatus.DRAFT
    # A four-weekly interval carries a quarter more soil.
    assert second["frequency_multiplier"] == 1.25

    fixtures.activate_contract(api, second["id"])

    assert fixtures.read_contract(api, first["id"])["status"] == ContractStatus.EXPIRED
    assert fixtures.read_contract(api, second["id"])["status"] == ContractStatus.ACTIVE


def test_a_replayed_balance_proposal_is_stale_by_construction(api):
    """PRD §2.7: "Note the self-reinforcing consequence: because creating a proposal itself
    increments the line's `version`, a second create that reuses the version read before the first
    create is stale by construction."

    Design: Corner/cross_cutting_layers/corner_second_balance_proposal_carrying_the_pre_proposal_line_version_is_stale
    """
    ground = fixtures.setup_started_visit(api, venue_name="Anchor Alehouse", lot_specs=())
    visit_id = ground["visit"]["id"]
    line_id = ground["line"]["id"]
    read_version = ground["line"]["version"]
    assert read_version == 1

    first = fixtures.propose_balance(
        api, visit_id, line_id, read_version, ground["technician"]["id"],
        measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=59.2,
    )

    validate_error(
        api.create_balance_record(
            factories.balance_record_payload(
                visit_id, line_id, read_version,
                measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=59.2,
            ),
            ground["tech_headers"],
        ),
        ApiErrorId.STALE_LINE_VERSION,
        412,
    )

    fresh_version = fixtures.read_line(api, line_id)["version"]
    assert fresh_version == 2

    second = fixtures.propose_balance(
        api, visit_id, line_id, fresh_version, ground["technician"]["id"],
        measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=59.2,
    )
    assert second["status"] == BalanceRecordStatus.PROPOSED

    reread = fixtures.read_line(api, line_id)
    assert reread["version"] == 3
    # Nothing was applied, only proposed.
    assert reread["applied_psi"] is None

    _, meta = validate_paginated(api.list_balance_records(AUDITOR_HEADERS, line_id=line_id))
    assert meta["total_count"] == 2
    assert_psi(first["required_applied_psi"], 13.60)
    assert_pct(second["required_co2_pct"], 59.2)


def test_one_failed_component_holds_the_venue_open_and_the_second_suspends_it(api):
    """PRD §3.4: "Hop two recomputes the owning account's `lines_out_of_service_count` and applies
    the compliance threshold: when twice that count is greater than or equal to the active contract's
    `contracted_line_count`, the account advances `ACTIVE → SUSPENDED` with `suspended_reason` set to
    `LINE_COMPLIANCE_THRESHOLD`."

    PRD §3.6: "When a component is graded `FAILED` and the technician did **not** replace it, the
    line advances `IN_SERVICE → OUT_OF_SERVICE` — a venue cannot keep pouring through a failed
    faucet."

    Design: Corner/cross_cutting_layers/corner_one_line_out_of_three_holds_but_two_trips_the_doubling_threshold
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        contracted_line_count=3,
        lines=(fixtures.DEFAULT_LINE, _SECOND_LINE),
        lot_specs=(),
    )
    account_id = ground["account"]["id"]
    visit_id = ground["visit"]["id"]
    line_one, line_two = ground["lines"]

    first = fixtures.log_inspection(
        api, visit_id, line_one["id"], ground["technician"]["id"],
        component_type=ComponentType.FAUCET, condition_grade=ConditionGrade.FAILED,
        action_taken=ActionTaken.NONE,
    )
    # A failed component left unreplaced carries no part charge.
    assert first["part_charge_cents"] == 0
    assert fixtures.read_line(api, line_one["id"])["status"] == LineStatus.OUT_OF_SERVICE

    # Twice one is two, still below the three lines the contract covers.
    holding = fixtures.read_account(api, account_id)
    assert holding["status"] == AccountStatus.ACTIVE
    assert holding["lines_out_of_service_count"] == 1

    fixtures.log_inspection(
        api, visit_id, line_two["id"], ground["technician"]["id"],
        component_type=ComponentType.COUPLER, condition_grade=ConditionGrade.FAILED,
        action_taken=ActionTaken.NONE,
    )
    assert fixtures.read_line(api, line_two["id"])["status"] == LineStatus.OUT_OF_SERVICE

    suspended = fixtures.read_account(api, account_id)
    assert suspended["status"] == AccountStatus.SUSPENDED
    assert suspended["lines_out_of_service_count"] == 2
    assert suspended["suspended_reason"] == SuspendedReason.LINE_COMPLIANCE_THRESHOLD
    assert fixtures.read_contract(api, ground["contract"]["id"])["status"] == ContractStatus.SUSPENDED

    # Only SCHEDULED visits are abandoned by the suspension.
    reread = fixtures.read_visit(api, visit_id)
    assert reread["work_status"] == WorkStatus.IN_PROGRESS
    assert reread["abandon_reason"] == AbandonReason.NONE


def test_every_figure_one_cycle_touches_is_readable_on_the_next_request(api):
    """PRD §2.10: "When an operation's side effects reach into other records, those records are
    updated inside the same request, before the response is built, and the response reflects the
    post-cascade world."

    Design: Corner/consistency_model/corner_every_derived_field_touched_by_one_cycle_is_readable_immediately
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    line_id = ground["line"]["id"]
    lot_id = ground["lot"]["id"]

    cycle = fixtures.log_cleaning_cycle(
        api, ground["visit"]["id"], line_id, lot_id, ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    # The create response already carries every derived figure in the dosing chain.
    assert_liters(cycle["line_volume_liters"], 2.214)
    assert cycle["total_solution_liters"] == 7
    assert_liters(cycle["prescribed_concentrate_liters"], 0.31)
    assert_pct(cycle["effective_active_pct"], 1.993)
    assert cycle["required_contact_minutes"] == 20
    assert cycle["compliance_result"] == ComplianceResult.PASS

    # No clock move and no second write happen before these reads.
    line = fixtures.read_line(api, line_id)
    assert_instant(line["last_cleaned_at"], "2026-08-05T09:00:00Z", label="last_cleaned_at")
    assert_instant(line["next_due_at"], "2026-08-26T09:00:00Z", label="next_due_at")
    assert line["days_overdue"] == 0
    assert line["compliance_flag"] == ComplianceFlag.COMPLIANT
    assert line["last_chemical_type"] == ChemicalType.CAUSTIC

    lot = fixtures.read_lot(api, lot_id)
    assert_liters(lot["liters_remaining"], 19.690)
    assert lot["status"] == LotStatus.AVAILABLE

    listed, meta = validate_paginated(
        api.list_cleaning_cycles(
            AUDITOR_HEADERS, line_id=line_id, compliance_result=ComplianceResult.PASS
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == cycle["id"]
