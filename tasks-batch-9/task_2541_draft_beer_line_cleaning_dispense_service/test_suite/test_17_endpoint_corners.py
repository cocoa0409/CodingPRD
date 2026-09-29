"""Corner cases in endpoint behaviour: the two rows a reschedule leaves behind, the compliance
gate on returning a line to service, the optional programme link on a contract, and a single-row
read whose answer changes because the clock moved."""

from test_helpers import (
    AUDITOR_HEADERS,
    ApiErrorId,
    BillingMode,
    ComplianceFlag,
    ComplianceResult,
    ContractStatus,
    DISPATCH_HEADERS,
    FundingStatus,
    FundedScope,
    LineStatus,
    RecordStatus,
    WorkStatus,
    AbandonReason,
    AccountStatus,
    assert_instant,
    assert_liters,
    assert_line_projection,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID


def test_one_reschedule_abandons_the_original_and_links_the_replacement_back_to_it(api):
    """PRD §3.3: "On success the original visit advances `SCHEDULED → ABANDONED` with
    `abandon_reason` set to `RESCHEDULED`, and a brand-new visit is minted in `SCHEDULED` carrying
    `rescheduled_from_visit_id` equal to the original visit's `id`, the same `account_id` and the
    same `visit_kind`, and a `technician_id` that defaults to the original's when the payload
    omitted it."

    Design: Corner/endpoints/corner_reschedule_abandons_the_original_and_mints_a_linked_replacement
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse", lines=())
    technician = fixtures.create_technician(api)
    original = fixtures.book_visit(api, venue["account"]["id"], technician["id"])

    # The payload names no technician, so the replacement must inherit the original's crew.
    replacement = get_success_data(
        api.reschedule_visit(
            original["id"],
            factories.reschedule_payload(
                scheduled_date="2026-08-07",
                scheduled_start_minute=600,
                scheduled_end_minute=720,
            ),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )

    assert replacement["id"] != original["id"]
    assert replacement["rescheduled_from_visit_id"] == original["id"]
    assert replacement["work_status"] == WorkStatus.SCHEDULED
    assert replacement["visit_kind"] == original["visit_kind"]
    assert replacement["account_id"] == venue["account"]["id"]
    assert replacement["technician_id"] == technician["id"]
    assert replacement["scheduled_date"] == "2026-08-07"
    assert replacement["scheduled_start_minute"] == 600
    assert replacement["scheduled_end_minute"] == 720

    abandoned = fixtures.read_visit(api, original["id"])
    assert abandoned["work_status"] == WorkStatus.ABANDONED
    assert abandoned["abandon_reason"] == AbandonReason.RESCHEDULED

    linked, meta = validate_paginated(
        api.list_service_visits(DISPATCH_HEADERS, rescheduled_from_visit_id=original["id"])
    )
    assert meta["total_count"] == 1
    assert linked[0]["id"] == replacement["id"]


def test_a_line_comes_back_only_once_the_failing_cycle_has_been_voided(api):
    """PRD §3.2: "A line whose newest posted cycle still grades `FAIL_CONCENTRATION`,
    `FAIL_CONTACT_TIME` or `FAIL_TEMPERATURE` is refused with `ERR_LINE_STILL_NON_COMPLIANT`."

    Design: Corner/endpoints/corner_return_to_service_is_blocked_until_the_failing_cycle_is_voided
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    line_id = ground["line"]["id"]
    account_id = ground["account"]["id"]

    # 92.0 F is under the caustic floor, so the cycle grades FAIL_TEMPERATURE.
    cycle = fixtures.log_cleaning_cycle(
        api, ground["visit"]["id"], line_id, ground["lot"]["id"], ground["technician"]["id"],
        chemical_type="CAUSTIC", contact_minutes=20, recirculation_temp_f=92.0,
        concentrate_liters_used=0.31,
    )
    assert cycle["compliance_result"] == ComplianceResult.FAIL_TEMPERATURE
    assert_line_projection(
        fixtures.read_line(api, line_id),
        status=LineStatus.OUT_OF_SERVICE,
        compliance_flag=ComplianceFlag.NON_COMPLIANT,
    )
    # One line out of four contracted leaves the account well below the suspension threshold.
    assert fixtures.read_account(api, account_id)["status"] == AccountStatus.ACTIVE

    validate_error(
        api.return_line_to_service(line_id, AUDITOR_HEADERS),
        ApiErrorId.LINE_STILL_NON_COMPLIANT,
        409,
    )

    voided = fixtures.void_cycle(api, cycle["id"], "Temperature probe was reading low.")
    assert voided["record_status"] == RecordStatus.VOIDED
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 20.0)

    restored = get_success_data(api.return_line_to_service(line_id, AUDITOR_HEADERS))

    assert restored["status"] == LineStatus.IN_SERVICE
    assert restored["compliance_flag"] == ComplianceFlag.COMPLIANT
    assert fixtures.read_account(api, account_id)["lines_out_of_service_count"] == 0
    # The void erased the only cycle the line ever had.
    assert restored["last_cleaned_at"] is None
    assert restored["next_due_at"] is None


def test_the_programme_link_must_resolve_and_then_carries_the_venue_onto_programme_billing(api):
    """PRD §2.9: "References supplied in a request body are resolved the same way, after the shape
    check of the ladder and in the order the fields are listed for the endpoint, using the same code
    per target type: `account_id` yields `ERR_ACCOUNT_NOT_FOUND`, `line_id` yields
    `ERR_LINE_NOT_FOUND`, `technician_id` yields `ERR_TECHNICIAN_NOT_FOUND`, `chemical_lot_id`
    yields `ERR_CHEMICAL_LOT_NOT_FOUND`, `part_sku_id` yields `ERR_PART_NOT_FOUND`,
    `brewer_program_id` yields `ERR_PROGRAM_NOT_FOUND`, `visit_id` yields `ERR_VISIT_NOT_FOUND`, and
    `glycol_loop_id` yields `ERR_GLYCOL_LOOP_NOT_FOUND`."

    PRD §3.1: "`funding_status` is `NONE` when no `brewer_program_id` was supplied, `BREWER_FUNDED`
    when the named programme's status is `ACTIVE`, and `SELF_FUNDED` when the named programme is
    already exhausted or ended."

    Design: Corner/endpoints/corner_contract_program_link_requires_a_real_program_and_flips_billing_mode
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    account = fixtures.create_account(api, venue_name="Anchor Alehouse")
    program = fixtures.create_brewer_program(
        api, brewer_name="Northgate Brewing", funded_scope=FundedScope.FULL,
        co_pay_bps=2000, funding_cap_cents=100000,
    )
    assert program["status"] == "ACTIVE"
    assert account["version"] == 1

    validate_error(
        api.create_contract(
            factories.contract_payload(
                account["id"], account["version"], brewer_program_id=NON_EXISTENT_UUID
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.PROGRAM_NOT_FOUND,
        404,
    )

    # The refused draft moved nothing, so the same version token is still current.
    contract = fixtures.draft_contract(
        api, account["id"], account["version"], brewer_program_id=program["id"]
    )
    assert contract["status"] == ContractStatus.DRAFT
    assert contract["funding_status"] == FundingStatus.BREWER_FUNDED

    fixtures.activate_contract(api, contract["id"])
    reread = fixtures.read_account(api, account["id"])

    assert reread["billing_mode"] == BillingMode.PROGRAM_BILL
    # Drafting incremented the account once and activation incremented it again.
    assert reread["version"] == 3

    listed, meta = validate_paginated(
        api.list_contracts(DISPATCH_HEADERS, brewer_program_id=program["id"])
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == contract["id"]


def test_three_days_past_due_still_reads_compliant_and_four_days_does_not(api):
    """PRD §3.2: "The second is calendar-driven: a line is non-compliant once `days_overdue` is
    greater than the three-day grace allowance, so a line exactly three days past its due date is
    still `COMPLIANT` and one four days past it is not."

    Design: Corner/endpoints/corner_line_read_shows_three_days_overdue_compliant_and_four_non_compliant
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    line_id = ground["line"]["id"]
    fixtures.log_cleaning_cycle(
        api, ground["visit"]["id"], line_id, ground["lot"]["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    # No write touches the line from here on; only the clock moves.
    fixtures.set_clock(api, "2026-08-29T09:00:00Z")
    at_three = get_success_data(api.get_beer_line(line_id, AUDITOR_HEADERS))

    assert_instant(at_three["last_cleaned_at"], "2026-08-05T09:00:00Z", label="last_cleaned_at")
    assert_instant(at_three["next_due_at"], "2026-08-26T09:00:00Z", label="next_due_at")
    assert at_three["days_overdue"] == 3
    assert at_three["compliance_flag"] == ComplianceFlag.COMPLIANT

    fixtures.set_clock(api, "2026-08-30T09:00:00Z")
    at_four = get_success_data(api.get_beer_line(line_id, AUDITOR_HEADERS))

    assert at_four["days_overdue"] == 4
    assert at_four["compliance_flag"] == ComplianceFlag.NON_COMPLIANT
    # An overdue line is not taken out of service by the projection.
    assert at_four["status"] == LineStatus.IN_SERVICE

    _, meta = validate_paginated(
        api.list_beer_lines(
            AUDITOR_HEADERS,
            account_id=ground["account"]["id"],
            compliance_flag=ComplianceFlag.NON_COMPLIANT,
        )
    )
    assert meta["total_count"] == 1
