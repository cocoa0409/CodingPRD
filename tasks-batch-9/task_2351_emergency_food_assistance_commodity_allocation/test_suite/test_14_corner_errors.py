"""Every declared refusal is reachable, distinct, and leaves the program untouched."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    CycleStatus,
    Disposition,
    FormulaVariant,
    HoldScope,
    LotStatus,
    NON_EXISTENT_UUID,
    OrderStatus,
    RecallClass,
    RecallStatus,
    TransferStatus,
    assert_lot_ledger,
    factories as f,
    fixtures as fx,
    make_agency_coordinator_headers,
    make_second_state_admin_headers,
    validate_error,
)

RICE_CODE = "BULK_RICE"
CHICKEN_CODE = "FROZEN_CHICKEN"
SECOND_ADMIN = make_second_state_admin_headers()


def test_01_every_path_identifier_has_its_own_not_found_code(api):
    """PRD §2.6: "For a path such as `/efap/agencies/{agency_id}/agreement-renewals`, the
    agency is resolved before the request body is inspected at all; an unknown `agency_id`
    yields `ERR_AGENCY_NOT_FOUND` (HTTP 404) regardless of whatever else is wrong with the
    payload." PRD §2.6: "The same discipline governs every other identifier, and each maps
    to its own dedicated not-found code, all of them HTTP 404: `service_area_id` to
    `ERR_SERVICE_AREA_NOT_FOUND`, `commodity_id` to `ERR_COMMODITY_NOT_FOUND`,
    `warehouse_id` to `ERR_WAREHOUSE_NOT_FOUND`, `inventory_lot_id` to
    `ERR_INVENTORY_LOT_NOT_FOUND`, `cycle_id` to `ERR_CYCLE_NOT_FOUND`,
    `agency_allocation_id` to `ERR_ALLOCATION_NOT_FOUND`, `order_id` to
    `ERR_ORDER_NOT_FOUND`, `order_line_id` to `ERR_ORDER_LINE_NOT_FOUND`, `appointment_id`
    to `ERR_APPOINTMENT_NOT_FOUND`, `transfer_id` to `ERR_TRANSFER_NOT_FOUND`, `recall_id`
    to `ERR_RECALL_NOT_FOUND`, `recall_action_id` to `ERR_RECALL_ACTION_NOT_FOUND`, and
    `distribution_id` to `ERR_DISTRIBUTION_NOT_FOUND`."

    Design: Corner/errors/every_declared_not_found_code_is_triggerable_by_an_unknown_id
    """
    unknown = NON_EXISTENT_UUID
    probes = [
        (api.get_service_area(unknown, headers=fx.ADMIN), ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND),
        (
            api.create_civil_rights_training(
                unknown, f.civil_rights_training_payload(), headers=fx.REVIEWER
            ),
            ApiErrorId.ERR_AGENCY_NOT_FOUND,
        ),
        (api.get_commodity(unknown, headers=fx.ADMIN), ApiErrorId.ERR_COMMODITY_NOT_FOUND),
        (api.get_warehouse(unknown, headers=fx.ADMIN), ApiErrorId.ERR_WAREHOUSE_NOT_FOUND),
        (
            api.get_inventory_lot(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND,
        ),
        (api.get_allocation_cycle(unknown, headers=fx.ADMIN), ApiErrorId.ERR_CYCLE_NOT_FOUND),
        (
            api.get_agency_allocation(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_ALLOCATION_NOT_FOUND,
        ),
        (api.get_commodity_order(unknown, headers=fx.ADMIN), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_order_line(unknown, headers=fx.ADMIN), ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
        (
            api.get_delivery_appointment(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_APPOINTMENT_NOT_FOUND,
        ),
        (
            api.get_inventory_transfer(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_TRANSFER_NOT_FOUND,
        ),
        (api.get_recall(unknown, headers=fx.ADMIN), ApiErrorId.ERR_RECALL_NOT_FOUND),
        (
            api.get_recall_action(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_RECALL_ACTION_NOT_FOUND,
        ),
        (
            api.get_household_distribution(unknown, headers=fx.ADMIN),
            ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND,
        ),
    ]

    observed = [validate_error(response, expected, 404)["error_id"] for response, expected in probes]

    assert len(observed) == 14, f"expected fourteen probes but ran {len(observed)}"
    assert len(set(observed)) == 14, (
        f"the fourteen not-found codes must be pairwise distinct but got {observed}"
    )


def _declined_transfer_voided_record_and_empty_order(api):
    """A DECLINED transfer, a VOIDED distribution and a DRAFT order with no lines."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    declined = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    fx.decline_transfer(api, declined["id"], agency["id"], decline_reason="NO_DRY_SPACE")
    accepted = fx.propose_transfer(api, lot["id"], agency["id"], 10)
    fx.accept_transfer(api, accepted["id"], agency["id"])
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    record = fx.record_distribution(
        api,
        agency["id"],
        cycle["id"],
        rice["id"],
        household_size=3,
        declared_monthly_income_cents=100000,
        participates_in_snap=False,
        self_declaration_signed=True,
        cases_distributed=2,
        distribution_date="2026-08-06",
    )
    fx.void_distribution(api, record["id"], agency["id"])
    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "lot": lot,
        "declined": declined,
        "record": record,
        "order": order,
    }


def test_02_terminal_transfers_and_voided_records_refuse_a_second_decision(api):
    """PRD §3.3: "The receiving agency's `AgencyCoordinator` decides the outcome, and
    either decision is refused with `ERR_INVALID_TRANSFER_STATE` if the transfer is
    already `ACCEPTED` or `DECLINED` — both are terminal." PRD §3.9: "The record must be in
    `RECORDED`, otherwise `ERR_INVALID_DISTRIBUTION_STATE`, and its cycle must not be
    `RECONCILED`, otherwise `ERR_INVALID_CYCLE_STATE`."

    Design: Corner/errors/transfer_distribution_and_empty_order_state_errors_are_each_triggerable
    """
    env = _declined_transfer_voided_record_and_empty_order(api)
    coordinator = make_agency_coordinator_headers(env["agency"]["id"])

    validate_error(
        api.accept_inventory_transfer(env["declined"]["id"], headers=coordinator),
        ApiErrorId.ERR_INVALID_TRANSFER_STATE,
        409,
    )
    validate_error(
        api.void_household_distribution(
            env["record"]["id"], f.void_reason_payload("SECOND_ATTEMPT"), headers=coordinator
        ),
        ApiErrorId.ERR_INVALID_DISTRIBUTION_STATE,
        409,
    )

    transfer = fx.read_transfer(api, env["declined"]["id"])
    assert transfer["status"] == TransferStatus.DECLINED, (
        f"the transfer must stay DECLINED but got {transfer['status']}"
    )
    assert transfer["decline_reason"] == "NO_DRY_SPACE", (
        f"decline_reason expected NO_DRY_SPACE but got {transfer['decline_reason']}"
    )
    record = fx.read_distribution(api, env["record"]["id"])
    assert record["void_reason"] == "DATA_ENTRY_ERROR", (
        f"the refused second void may not overwrite void_reason but it reads "
        f"{record['void_reason']}"
    )


def test_03_an_order_with_no_lines_cannot_be_submitted_and_the_ledger_holds(api):
    """PRD §3.5: "The order must carry at least one line, otherwise `ERR_EMPTY_ORDER`."
    PRD §3.3: "Declining a transfer moves it `PROPOSED → DECLINED`. It requires the same
    ownership check, takes a `decline_reason`, and compensates the proposal exactly: the
    lot's `cases_committed` falls by `cases` while `cases_on_hand` is never touched,
    restoring the lot to its pre-proposal figures." PRD §3.9: "The void compensates
    exactly: the entitlement's `distributed_pounds` falls by the record's
    `pounds_distributed`, its `distribution_record_count` falls by one, and its
    `record_compliance_pct` is recomputed over the remaining `RECORDED` rows, while the
    agency's `agency_cases_on_hand` rises by `cases_distributed`."

    Design: Corner/errors/transfer_distribution_and_empty_order_state_errors_are_each_triggerable
    """
    env = _declined_transfer_voided_record_and_empty_order(api)

    response = api.submit_order(
        env["order"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EMPTY_ORDER, 422)
    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.DRAFT, (
        f"the refused submit must leave the order DRAFT but got {order['status']}"
    )
    assert order["line_count"] == 0, (
        f"line_count expected 0 but got {order['line_count']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 10, (
        f"the void must credit the two cases back exactly once but on hand reads "
        f"{agency['agency_cases_on_hand']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=90, cases_committed=0, cases_shipped_to_date=10)


def _paperwork_and_unfundable_floors(api):
    """An untrained agency, two agreed agencies, and a HOLD_HARMLESS pool of 100 cases."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=100000
    )
    xray = fx.create_agency(
        api,
        area["id"],
        name="Agency Xray",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=60000,
        prior_period_allocated_cases=200,
    )
    agreed = []
    for name in ("Agency Yankee", "Agency Zulu"):
        agency = fx.create_agency(
            api,
            area["id"],
            name=name,
            cold_storage_pallet_capacity=10,
            prior_period_pounds_distributed=60000,
            prior_period_allocated_cases=200,
        )
        fx.make_agency_eligible(api, agency["id"])
        agreed.append(agency)
    yankee, zulu = agreed

    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27HH",
        formula_variant=FormulaVariant.HOLD_HARMLESS,
        allocatable_cases=100,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    return {"xray": xray, "yankee": yankee, "zulu": zulu, "cycle": cycle}


def test_04_renewals_need_current_training_and_a_term_that_starts_after_the_old_one(api):
    """PRD §3.2: "Recording a renewal is permitted only while `training_status` is
    `CURRENT`; attempting it while training is `REQUIRED` or `LAPSED` is refused with
    `ERR_TRAINING_NOT_CURRENT`." PRD §3.2: "`ACTIVE → ACTIVE` is early renewal of a term
    that has not yet lapsed. Beyond training currency, it requires the payload's
    `agreement_start_date` to be strictly after the agency's *current*
    `agreement_end_date`, otherwise `ERR_AGREEMENT_NOT_RENEWABLE`. It replaces the term
    with the payload dates and increases `renewal_count` by one."

    Design: Corner/errors/compliance_and_feasibility_errors_are_each_triggerable
    """
    env = _paperwork_and_unfundable_floors(api)

    validate_error(
        api.create_agreement_renewal(
            env["xray"]["id"],
            f.agreement_renewal_payload("2026-08-01", "2027-07-31"),
            headers=fx.REVIEWER,
        ),
        ApiErrorId.ERR_TRAINING_NOT_CURRENT,
        422,
    )
    validate_error(
        api.create_agreement_renewal(
            env["yankee"]["id"],
            f.agreement_renewal_payload("2027-01-01", "2027-12-31"),
            headers=fx.REVIEWER,
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_RENEWABLE,
        409,
    )

    xray = fx.read_agency(api, env["xray"]["id"])
    assert xray["agreement_status"] == AgreementStatus.PENDING, (
        f"the untrained agency must stay PENDING but got {xray['agreement_status']}"
    )
    assert xray["renewal_count"] == 0, (
        f"renewal_count expected 0 but got {xray['renewal_count']}"
    )
    yankee = fx.read_agency(api, env["yankee"]["id"])
    assert yankee["agreement_end_date"] == "2027-06-30", (
        f"the refused renewal may not replace the term but agreement_end_date reads "
        f"{yankee['agreement_end_date']}"
    )
    assert yankee["renewal_count"] == 1, (
        f"renewal_count expected 1 but got {yankee['renewal_count']}"
    )


def test_05_unfundable_floors_refuse_the_run_and_write_nothing(api):
    """PRD §3.4: "If the total shortfall exceeds the total excess the allocation cannot be
    funded and the run is refused with `ERR_ALLOCATION_INFEASIBLE`." PRD §3.4: "Under
    `HOLD_HARMLESS`, each agency's `floor_cases` is 90 percent of its
    `prior_period_allocated_cases` with the fractional part discarded, and no agency may
    finish below that floor." PRD §2.11: "The rule is that every cascade named in §3 is
    part of the same transaction as its trigger: either the whole chain lands or nothing
    does."

    Design: Corner/errors/compliance_and_feasibility_errors_are_each_triggerable
    """
    env = _paperwork_and_unfundable_floors(api)

    response = api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_ALLOCATION_INFEASIBLE, 422)
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["status"] == CycleStatus.DRAFT, (
        f"the refused run must leave the cycle DRAFT but got {cycle['status']}"
    )
    assert cycle["total_allocated_cases"] == 0, (
        f"total_allocated_cases expected 0 but got {cycle['total_allocated_cases']}"
    )
    assert cycle["eligible_agency_count"] == 0, (
        f"eligible_agency_count expected 0 but got {cycle['eligible_agency_count']}"
    )
    assert cycle["allocation_locked_at"] is None, (
        f"allocation_locked_at expected null but got {cycle['allocation_locked_at']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_cycle_allocations(env["cycle"]["id"], headers=fx.ADMIN)
    )
    assert meta["total_count"] == 0, (
        f"a failed compute writes nothing but total_count is {meta['total_count']}"
    )


def _class_one_recall_short_of_its_exposure(api):
    """A CLASS_I recall in MONITORING whose only action destroyed 15 of 20 exposed cases."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    fx.accept_transfer(api, transfer["id"], agency["id"])
    recall = fx.raise_recall(
        api,
        lot["id"],
        recall_class=RecallClass.CLASS_I,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Listeria positive on the federal lot.",
    )
    fx.dispatch_notices(api, recall["id"])
    action = fx.recall_actions_of(api, recall["id"])[0]
    fx.acknowledge_action(api, action["id"], agency["id"])
    fx.report_disposition(
        api,
        action["id"],
        agency["id"],
        disposition=Disposition.DESTROYED,
        cases_accounted=15,
    )
    return {"agency": agency, "lot": lot, "recall": recall, "action": action}


def test_06_a_lot_carries_one_open_recall_and_an_agency_one_action(api):
    """PRD §3.8: "At most one recall in `INITIATED`, `NOTIFYING`, or `MONITORING` may name
    a given source lot at a time, a second attempt answering `ERR_RECALL_ALREADY_OPEN`."
    PRD §3.8: "A `StateAdmin` names an additional `agency_id`; the recall must be in
    `MONITORING`, otherwise `ERR_INVALID_RECALL_STATE`, and no existing action of that
    recall may already name that agency, otherwise `ERR_DUPLICATE_RECALL_ACTION`."

    Design: Corner/errors/recall_uniqueness_expansion_and_accounting_errors_are_each_triggerable
    """
    env = _class_one_recall_short_of_its_exposure(api)

    validate_error(
        api.create_recall(
            f.recall_payload(
                env["lot"]["id"],
                recall_class=RecallClass.CLASS_II,
                hold_scope=HoldScope.LOT_ONLY,
                reason="Duplicate report on the same federal lot.",
            ),
            headers=fx.ADMIN,
        ),
        ApiErrorId.ERR_RECALL_ALREADY_OPEN,
        409,
    )
    validate_error(
        api.expand_recall(
            env["recall"]["id"], {"agency_id": env["agency"]["id"]}, headers=fx.ADMIN
        ),
        ApiErrorId.ERR_DUPLICATE_RECALL_ACTION,
        409,
    )

    _rows, meta = fx.list_rows_and_meta(
        api.list_recalls(headers=fx.ADMIN, params={"source_lot_id": env["lot"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the lot may carry one recall but total_count is {meta['total_count']}"
    )
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["action_count"] == 1, (
        f"action_count expected 1 but got {recall['action_count']}"
    )
    assert recall["status"] == RecallStatus.MONITORING, (
        f"the failed expansion must leave the recall MONITORING but got {recall['status']}"
    )


def test_07_a_class_one_recall_will_not_close_over_unaccounted_cases(api):
    """PRD §3.8: "Closure of a `CLASS_I` recall carries one extra bar: every dispositioned
    action must have reported a `cases_accounted` figure equal to its `exposed_cases`, and
    any shortfall refuses the closure with `ERR_RECALL_CASES_UNACCOUNTED`." PRD §3.8:
    "Each covered lot moves `AVAILABLE → HOLD` or `WATCH → HOLD` — a lot moved from
    `WATCH` keeps its existing `monitor_flag`, since the hold says nothing about staleness
    — has its `hold_recall_id` set to the recall's `id`, contributes one to the recall's
    `held_lot_count`, and has its `version` incremented."

    Design: Corner/errors/recall_uniqueness_expansion_and_accounting_errors_are_each_triggerable
    """
    env = _class_one_recall_short_of_its_exposure(api)

    response = api.close_recall(env["recall"]["id"], headers=SECOND_ADMIN)

    validate_error(response, ApiErrorId.ERR_RECALL_CASES_UNACCOUNTED, 409)
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["status"] == RecallStatus.MONITORING, (
        f"the refused closure must leave the recall MONITORING but got {recall['status']}"
    )
    assert recall["accounted_cases"] == 15, (
        f"accounted_cases expected 15 but got {recall['accounted_cases']}"
    )
    assert recall["dispositioned_count"] == 1, (
        f"dispositioned_count expected 1 but got {recall['dispositioned_count']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.HOLD, (
        f"an unaccounted recall never releases its lots but the lot reads {lot['status']}"
    )
    assert lot["hold_recall_id"] == env["recall"]["id"], (
        f"hold_recall_id expected {env['recall']['id']} but got {lot['hold_recall_id']}"
    )


def _dry_warehouse_and_a_short_ranking(api):
    """A frozen-incapable warehouse, one posted and one unposted lot, and a 150-case line."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(
        api,
        name="WH Dry",
        dry_pallet_capacity=100,
        cold_pallet_capacity=0,
        frozen_pallet_capacity=0,
    )
    posted = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-POSTED",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    unposted = fx.create_inventory_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-UNPOSTED",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2027-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27M",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE, CHICKEN_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    first = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    line = fx.add_line(api, first["id"], agency["id"], rice["id"], 150)
    fx.submit_order(api, first["id"], agency["id"])
    second = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "chicken": chicken,
        "rice": rice,
        "posted": posted,
        "unposted": unposted,
        "first": first,
        "line": line,
        "second": second,
    }


def test_08_a_frozen_line_and_an_oversized_transfer_are_both_refused(api):
    """PRD §3.5: "The receiving warehouse must have a non-zero capacity pool for the
    line's storage class — a `DRY` line needs `dry_pallet_capacity` above zero, a `COLD`
    line needs `cold_pallet_capacity` above zero, a `FROZEN` line needs
    `frozen_pallet_capacity` above zero — and a `FROZEN` line additionally requires the
    ordering agency's own `cold_storage_pallet_capacity` to be above zero." PRD §3.5: "Any
    of these failing answers `ERR_STORAGE_CLASS_UNSUPPORTED`." PRD §3.3: "The proposed
    `cases` may not exceed the lot's available cases as defined in §2.9 — that is,
    `cases_on_hand` minus `cases_committed` at proposal time — otherwise
    `ERR_LOT_CASES_UNAVAILABLE`."

    Design: Corner/errors/inventory_and_cold_chain_errors_are_each_triggerable
    """
    env = _dry_warehouse_and_a_short_ranking(api)
    posted_before = fx.read_lot(api, env["posted"]["id"])

    validate_error(
        api.add_order_line(
            env["second"]["id"],
            f.order_line_payload(env["chicken"]["id"], 5),
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        ),
        ApiErrorId.ERR_STORAGE_CLASS_UNSUPPORTED,
        422,
    )
    validate_error(
        api.create_inventory_transfer(
            f.inventory_transfer_payload(
                env["posted"]["id"], env["agency"]["id"], 200, posted_before["version"]
            ),
            headers=fx.ADMIN,
        ),
        ApiErrorId.ERR_LOT_CASES_UNAVAILABLE,
        409,
    )

    order = fx.read_order(api, env["second"]["id"])
    assert order["line_count"] == 0, (
        f"the refused line may not be counted but line_count is {order['line_count']}"
    )
    posted = fx.read_lot(api, env["posted"]["id"])
    assert posted["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {posted['cases_committed']}"
    )
    assert posted["version"] == posted_before["version"], (
        f"the refused proposal must not bump the version from {posted_before['version']} "
        f"but the lot reads {posted['version']}"
    )


def test_09_a_short_ranking_and_an_empty_agency_shelf_are_both_refused(api):
    """PRD §3.6: "If the ranked candidate list is exhausted while a line still needs
    cases, the **entire approval fails** with `ERR_INSUFFICIENT_INVENTORY`: no line is
    partially reserved, no lot's `cases_committed` changes, and the order remains in
    `SUBMITTED`." PRD §3.6: "Lots in `RECEIVED`, `HOLD`, `DISPOSED`, or `DEPLETED` are
    invisible to the selector." PRD §3.9: "The `cases_distributed` figure must not exceed
    the agency's `agency_cases_on_hand`, otherwise `ERR_AGENCY_INVENTORY_INSUFFICIENT`; on
    success that counter falls by `cases_distributed`."

    Design: Corner/errors/inventory_and_cold_chain_errors_are_each_triggerable
    """
    env = _dry_warehouse_and_a_short_ranking(api)

    validate_error(
        api.approve_order(env["first"]["id"], headers=fx.SECOND_REVIEWER),
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY,
        409,
    )
    validate_error(
        api.create_household_distribution(
            f.household_distribution_payload(
                env["agency"]["id"],
                env["cycle"]["id"],
                env["rice"]["id"],
                household_size=3,
                declared_monthly_income_cents=100000,
                participates_in_snap=False,
                self_declaration_signed=True,
                cases_distributed=5,
                distribution_date="2026-08-06",
            ),
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        ),
        ApiErrorId.ERR_AGENCY_INVENTORY_INSUFFICIENT,
        422,
    )

    order = fx.read_order(api, env["first"]["id"])
    assert order["status"] == OrderStatus.SUBMITTED, (
        f"the refused approval must leave the order SUBMITTED but got {order['status']}"
    )
    assert order["total_cases_approved"] == 0, (
        f"total_cases_approved expected 0 but got {order['total_cases_approved']}"
    )
    posted = fx.read_lot(api, env["posted"]["id"])
    assert posted["cases_committed"] == 0, (
        f"no partial reservation was allowed but cases_committed is "
        f"{posted['cases_committed']}"
    )
    line = fx.read_order_lines(api, env["first"]["id"])[0]
    assert line["lot_assignments"] == [], (
        f"lot_assignments expected empty but got {line['lot_assignments']}"
    )
    unposted = fx.read_lot(api, env["unposted"]["id"])
    assert unposted["status"] == LotStatus.RECEIVED, (
        f"the unposted receipt expected RECEIVED but got {unposted['status']}"
    )
    assert unposted["cases_on_hand"] == 0, (
        f"cases_on_hand expected 0 but got {unposted['cases_on_hand']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 0, (
        f"agency_cases_on_hand expected 0 but got {agency['agency_cases_on_hand']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["distribution_record_count"] == 0, (
        f"distribution_record_count expected 0 but got "
        f"{allocation['distribution_record_count']}"
    )
