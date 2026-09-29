"""Who may act, whose version wins, and what a single write leaves visible everywhere."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    AppointmentStatus,
    CancelReason,
    DrawPosture,
    EligibilityPosture,
    LotStatus,
    MonitorFlag,
    MonitorPolicy,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    OrderStatus,
    RecallClass,
    RecallStatus,
    SECOND_STATE_ADMIN_ID,
    STATE_ADMIN_ID,
    TrainingStatus,
    TransferStatus,
    CycleStatus,
    Disposition,
    FormulaVariant,
    HoldScope,
    assert_instant,
    assert_lot_assignments,
    assert_lot_ledger,
    assert_pounds,
    assert_ratio,
    assert_version_incremented,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_agency_coordinator_headers,
    make_headers,
    make_second_state_admin_headers,
    make_warehouse_operator_headers,
    validate_error,
    validate_success,
)

RICE_CODE = "BULK_RICE"
SECOND_ADMIN = make_second_state_admin_headers()


def _one_agency_and_one_warehouse(api):
    """A registered agency and a warehouse, so every role has a real identity to present."""
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
    warehouse = fx.create_warehouse(api, name="WH North")
    return {"area": area, "agency": agency, "warehouse": warehouse}


def test_01_a_header_less_write_is_401_and_an_unlisted_role_is_403(api):
    """PRD §2.1: "If either header is missing or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." PRD §2.1: "If `X-User-Role` carries a value that is
    not one of the four recognised roles, or names a role that the addressed operation does
    not authorise, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/missing_headers_are_unauthenticated_and_the_wrong_role_is_unauthorized
    """
    env = _one_agency_and_one_warehouse(api)

    validate_error(
        api.create_commodity(
            f.commodity_payload(code="NOHDR", name="No Header Rice"), headers=NO_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_commodity(
            f.commodity_payload(code="WRONGROLE", name="Wrong Role Rice"),
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    codes = {row["code"] for row in fx.list_rows(api.list_commodities(headers=fx.ADMIN))}
    assert "NOHDR" not in codes, (
        f"the unauthenticated create must write nothing but the catalogue holds {sorted(codes)}"
    )
    assert "WRONGROLE" not in codes, (
        f"the unauthorized create must write nothing but the catalogue holds {sorted(codes)}"
    )


def test_02_authorisation_precedes_existence_and_only_the_clock_read_is_exempt(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    user, and `X-User-Role`, declaring the capacity in which that user is acting." PRD
    §2.1: "The single exception is the logical-clock read described in §2.4, which may be
    called without headers." PRD §2.4: "Any caller may read the clock back, and that read
    is the one operation in the API that does not require authentication headers; it
    answers with the same `current_utc` field."

    Design: Corner/rbac/missing_headers_are_unauthenticated_and_the_wrong_role_is_unauthorized
    """
    env = _one_agency_and_one_warehouse(api)

    validate_error(
        api.create_civil_rights_training(
            env["agency"]["id"],
            f.civil_rights_training_payload(),
            headers=make_warehouse_operator_headers(env["warehouse"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_civil_rights_training(
            env["agency"]["id"],
            f.civil_rights_training_payload(),
            headers=make_headers("aud-1", "Auditor"),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.get_service_area(
            NON_EXISTENT_UUID, headers=make_agency_coordinator_headers(env["agency"]["id"])
        ),
        ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND,
        404,
    )

    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["training_status"] == TrainingStatus.REQUIRED, (
        f"neither refused write may record a session but training_status reads "
        f"{agency['training_status']}"
    )
    clock = get_success_data(api.get_clock(headers=NO_HEADERS))
    assert_instant(clock["current_utc"], "2026-08-01T00:00:00Z", "current_utc")


def _two_agencies_two_warehouses_and_a_scheduled_delivery(api):
    """Alpha owns a scheduled ten-case delivery at WH North; Beta and WH South own nothing."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    alpha = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    beta = fx.create_agency(
        api,
        area["id"],
        name="Agency Beta",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, alpha["id"])
    fx.make_agency_eligible(api, beta["id"])
    rice = fx.create_bulk_rice(api)
    north = fx.create_warehouse(api, name="WH North")
    south = fx.create_warehouse(api, name="WH South")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        north["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
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

    order = fx.create_order(api, cycle["id"], alpha["id"], north["id"])
    fx.add_line(api, order["id"], alpha["id"], rice["id"], 10)
    fx.submit_order(api, order["id"], alpha["id"])
    fx.approve_order(api, order["id"])
    appointment = fx.book_appointment(api, order["id"])
    return {
        "alpha": alpha,
        "beta": beta,
        "rice": rice,
        "north": north,
        "south": south,
        "lot": lot,
        "cycle": cycle,
        "order": order,
        "appointment": appointment,
    }


def test_03_a_coordinator_holding_the_right_role_cannot_touch_another_agencys_rows(api):
    """PRD §2.2: "When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the
    acting `Agency`; ownership checks on any resource that references an `Agency` compare
    the resource's foreign-key field to `X-User-ID`." PRD §2.2: "Concretely, a
    coordinator's writes are refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) unless
    `X-User-ID` equals the `agency_id` of the order being created, lined, submitted or
    cancelled, the `to_agency_id` of the transfer being accepted or declined, the
    `agency_id` of the recall action being acknowledged or dispositioned, and the
    `agency_id` of the household distribution being recorded or voided."

    Design: Corner/rbac/a_coordinator_cannot_touch_another_agencys_rows_and_an_operator_cannot_confirm_another_warehouse
    """
    env = _two_agencies_two_warehouses_and_a_scheduled_delivery(api)
    intruder = make_agency_coordinator_headers(env["beta"]["id"])

    validate_error(
        api.add_order_line(
            env["order"]["id"], f.order_line_payload(env["rice"]["id"], 1), headers=intruder
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.create_household_distribution(
            f.household_distribution_payload(
                env["alpha"]["id"],
                env["cycle"]["id"],
                env["rice"]["id"],
                household_size=2,
                declared_monthly_income_cents=100000,
                participates_in_snap=False,
                self_declaration_signed=True,
                cases_distributed=1,
                distribution_date="2026-08-06",
            ),
            headers=intruder,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    order = fx.read_order(api, env["order"]["id"])
    assert order["line_count"] == 1, (
        f"the intruder's line may not be added but line_count is {order['line_count']}"
    )
    alpha = fx.read_agency(api, env["alpha"]["id"])
    assert alpha["agency_cases_on_hand"] == 0, (
        f"nothing has been delivered yet so agency_cases_on_hand must be 0 but reads "
        f"{alpha['agency_cases_on_hand']}"
    )


def test_04_only_the_dock_owning_operator_may_confirm_the_delivery(api):
    """PRD §2.2: "When `X-User-Role` is `StateWarehouseOperator`, `X-User-ID` is the `id` of
    the acting `Warehouse`; ownership checks on any resource that references a `Warehouse`
    compare the resource's foreign-key field to `X-User-ID`." PRD §3.7: "**Confirming
    delivery** is reserved to the `StateWarehouseOperator` who owns the dock: `X-User-ID`
    must equal the appointment's `warehouse_id`, otherwise `ERR_NOT_RESOURCE_OWNER`." PRD
    §3.7: "The appointment moves `SCHEDULED → DELIVERED`, capturing `delivered_pounds` from
    the order's `total_pounds` and recording the confirming operator in
    `confirmed_by_user_id`."

    Design: Corner/rbac/a_coordinator_cannot_touch_another_agencys_rows_and_an_operator_cannot_confirm_another_warehouse
    """
    env = _two_agencies_two_warehouses_and_a_scheduled_delivery(api)
    fx.set_clock(api, "2026-08-10T10:00:00Z")

    validate_error(
        api.confirm_delivery(
            env["appointment"]["id"],
            headers=make_warehouse_operator_headers(env["south"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    blocked = fx.read_appointment(api, env["appointment"]["id"])
    assert blocked["status"] == AppointmentStatus.SCHEDULED, (
        f"the refused confirmation must leave the appointment SCHEDULED but got "
        f"{blocked['status']}"
    )

    confirmed = fx.confirm_delivery(api, env["appointment"]["id"], env["north"]["id"])

    assert confirmed["status"] == AppointmentStatus.DELIVERED, (
        f"the owning operator's confirmation expected DELIVERED but got {confirmed['status']}"
    )
    assert confirmed["confirmed_by_user_id"] == env["north"]["id"], (
        f"confirmed_by_user_id expected {env['north']['id']} but got "
        f"{confirmed['confirmed_by_user_id']}"
    )
    alpha = fx.read_agency(api, env["alpha"]["id"])
    assert alpha["agency_cases_on_hand"] == 10, (
        f"the delivery credits Alpha with ten cases but agency_cases_on_hand reads "
        f"{alpha['agency_cases_on_hand']}"
    )
    beta = fx.read_agency(api, env["beta"]["id"])
    assert beta["agency_cases_on_hand"] == 0, (
        f"Beta received nothing but agency_cases_on_hand reads "
        f"{beta['agency_cases_on_hand']}"
    )


def _returned_recall_awaiting_closure(api):
    """A CLASS_II recall in MONITORING whose only action returned all twenty cases."""
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
        recall_class=RecallClass.CLASS_II,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Packaging defect reported on the federal lot.",
    )
    fx.dispatch_notices(api, recall["id"])
    action = fx.recall_actions_of(api, recall["id"])[0]
    fx.acknowledge_action(api, action["id"], agency["id"])
    fx.report_disposition(
        api,
        action["id"],
        agency["id"],
        disposition=Disposition.RETURNED_TO_STATE,
        cases_accounted=20,
    )
    return {"agency": agency, "lot": lot, "recall": recall}


def test_05_the_admin_who_raised_the_recall_may_not_close_it(api):
    """PRD §3.8: "**Closing a recall** is the final act, and it may not be performed by the
    `StateAdmin` recorded in `initiated_by_user_id` — that same admin attempting closure is
    refused with `ERR_SEGREGATION_OF_DUTIES`." PRD §2.2: "Both opaque identifiers are
    nonetheless compared against each other across time, which is what makes segregation of
    duties work: the recorded `last_returned_by_user_id` is compared with the `X-User-ID`
    presented at approval, and the recorded `initiated_by_user_id` is compared with the
    `X-User-ID` presented at recall closure."

    Design: Corner/rbac/the_recall_initiator_cannot_close_its_own_recall_but_a_second_admin_can
    """
    env = _returned_recall_awaiting_closure(api)

    response = api.close_recall(env["recall"]["id"], headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["status"] == RecallStatus.MONITORING, (
        f"the refused closure must leave the recall MONITORING but got {recall['status']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.HOLD, (
        f"the lot stays held until a lawful closure but it reads {lot['status']}"
    )


def test_06_a_second_admin_closes_the_recall_and_releases_the_returned_lot(api):
    """PRD §3.8: "If no disposition was `DESTROYED`, the recall releases: each held lot
    moves `HOLD → AVAILABLE` with `hold_recall_id` cleared back to null, every delivery
    appointment that this lot's hold had put into `BLOCKED` moves `BLOCKED → SCHEDULED`, and
    every order in `HELD` whose `lot_assignments` reference the lot moves `HELD → APPROVED`
    — and where its appointment came back to `SCHEDULED`, the order continues on to
    `SCHEDULED` in the same cascade." PRD §3.8: "Under `RETURNED_TO_STATE` the cases
    physically travel back: the agency's `agency_cases_on_hand` falls by `cases_accounted`
    and the source lot's `cases_on_hand` rises by the same amount, keeping the program case
    total of §2.9 conserved."

    Design: Corner/rbac/the_recall_initiator_cannot_close_its_own_recall_but_a_second_admin_can
    """
    env = _returned_recall_awaiting_closure(api)

    closed = get_success_data(api.close_recall(env["recall"]["id"], headers=SECOND_ADMIN))

    assert closed["status"] == RecallStatus.CLOSED, (
        f"the second admin's closure expected CLOSED but got {closed['status']}"
    )
    assert closed["initiated_by_user_id"] == STATE_ADMIN_ID, (
        f"initiated_by_user_id expected {STATE_ADMIN_ID} but got "
        f"{closed['initiated_by_user_id']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"a release path closure returns the lot to AVAILABLE but it reads {lot['status']}"
    )
    assert lot["hold_recall_id"] is None, (
        f"hold_recall_id expected null but got {lot['hold_recall_id']}"
    )
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=0, cases_shipped_to_date=20)
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 0, (
        f"the returned cases left the agency so agency_cases_on_hand must be 0 but reads "
        f"{agency['agency_cases_on_hand']}"
    )


def _versions_captured_before_the_writes_that_bump_them(api):
    """One draft order and one proposal, with the pre-write versions of both guarded rows."""
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

    allocation_v1 = fx.read_allocation(api, cycle["id"], agency["id"])["version"]
    lot_v1 = fx.read_lot(api, lot["id"])["version"]
    first_order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    first_transfer = fx.propose_transfer(api, lot["id"], agency["id"], 5)
    return {
        "agency": agency,
        "warehouse": warehouse,
        "lot": lot,
        "cycle": cycle,
        "allocation_v1": allocation_v1,
        "lot_v1": lot_v1,
        "first_order": first_order,
        "first_transfer": first_transfer,
    }


def test_07_a_replayed_entitlement_version_is_refused_and_the_refetched_one_supersedes(api):
    """PRD §2.8: "If that value does not equal the allocation's current `version`, the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.5: "Creation is
    *superseding*: any existing order of the same agency in the same cycle that is still in
    `DRAFT` is cancelled with `cancel_reason` set to `SUPERSEDED`, so an agency never
    accumulates competing drafts." PRD §3.5: "Creation increments the parent entitlement's
    `version` by one — which is exactly why a client issuing a second create must re-read
    the entitlement first."

    Design: Corner/cross-cutting complexity layers/stale_expected_versions_are_refused_on_both_declared_occ_rules
    """
    env = _versions_captured_before_the_writes_that_bump_them(api)
    coordinator = make_agency_coordinator_headers(env["agency"]["id"])
    payload = f.commodity_order_payload(
        env["cycle"]["id"],
        env["agency"]["id"],
        env["warehouse"]["id"],
        env["allocation_v1"],
    )

    validate_error(
        api.create_commodity_order(payload, headers=coordinator),
        ApiErrorId.ERR_STALE_VERSION,
        412,
    )

    _rows, meta = fx.list_rows_and_meta(
        api.list_commodity_orders(headers=fx.ADMIN, params={"cycle_id": env["cycle"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused create must write no second order but total_count is "
        f"{meta['total_count']}"
    )
    allocation_v2 = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])["version"]
    assert_version_incremented(allocation_v2, env["allocation_v1"])

    retry = validate_success(
        api.create_commodity_order(
            f.commodity_order_payload(
                env["cycle"]["id"],
                env["agency"]["id"],
                env["warehouse"]["id"],
                allocation_v2,
            ),
            headers=coordinator,
        ),
        201,
    )
    assert retry["status"] == OrderStatus.DRAFT, (
        f"the retry with the refetched version expected DRAFT but got {retry['status']}"
    )
    superseded = fx.read_order(api, env["first_order"]["id"])
    assert superseded["status"] == OrderStatus.CANCELLED, (
        f"the earlier draft expected CANCELLED but got {superseded['status']}"
    )
    assert superseded["cancel_reason"] == CancelReason.SUPERSEDED, (
        f"cancel_reason expected SUPERSEDED but got {superseded['cancel_reason']}"
    )


def test_08_a_replayed_lot_version_is_refused_and_the_refetched_one_proposes(api):
    """PRD §2.8: "If that value does not equal the lot's current `version`, the proposal is
    rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.3: "On success the transfer is
    written in `status` `PROPOSED` with `transferred_value_cents` computed as `cases`
    multiplied by the `entitlement_value_cents_per_case` of the source lot's commodity, the
    lot's `cases_committed` grows by `cases` with `cases_on_hand` deliberately untouched,
    and the lot's `version` is incremented."

    Design: Corner/cross-cutting complexity layers/stale_expected_versions_are_refused_on_both_declared_occ_rules
    """
    env = _versions_captured_before_the_writes_that_bump_them(api)

    validate_error(
        api.create_inventory_transfer(
            f.inventory_transfer_payload(
                env["lot"]["id"], env["agency"]["id"], 5, env["lot_v1"]
            ),
            headers=fx.ADMIN,
        ),
        ApiErrorId.ERR_STALE_VERSION,
        412,
    )

    stale_view = fx.read_lot(api, env["lot"]["id"])
    assert stale_view["cases_committed"] == 5, (
        f"only the setup proposal may hold a commitment but cases_committed is "
        f"{stale_view['cases_committed']}"
    )
    assert_version_incremented(stale_view["version"], env["lot_v1"])

    retry = validate_success(
        api.create_inventory_transfer(
            f.inventory_transfer_payload(
                env["lot"]["id"], env["agency"]["id"], 5, stale_view["version"]
            ),
            headers=fx.ADMIN,
        ),
        201,
    )
    assert retry["status"] == TransferStatus.PROPOSED, (
        f"the retry with the refetched version expected PROPOSED but got {retry['status']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=10, cases_shipped_to_date=0)
    first = fx.read_transfer(api, env["first_transfer"]["id"])
    assert first["status"] == TransferStatus.PROPOSED, (
        f"the setup proposal expected PROPOSED but got {first['status']}"
    )
    assert first["cases"] == 5, f"cases expected 5 but got {first['cases']}"


def test_09_the_parent_count_follows_every_posture_move_including_a_sweeps(api):
    """PRD §3.1: "Alongside these inputs the area maintains `eligible_agency_count`, which
    starts at 0 and thereafter tracks how many agencies in that area currently hold an
    `ELIGIBLE` posture." PRD §3.2: "Immediately after any posture write, the
    `eligible_agency_count` of that agency's service area is recomputed as the number of
    agencies in that area whose posture is `ELIGIBLE`." PRD §3.2: "A training in `CURRENT`
    moves to `LAPSED` once the current instant reaches `training_expires_at`." PRD §3.2:
    "`LAPSED → CURRENT` is re-training after expiry. It requires `completed_at` at or before
    the current instant, refreshes both timestamps, and recomputes the posture — an agency
    whose agreement is still `ACTIVE` moves from `PROBATION` back to `ELIGIBLE` in the same
    write."

    Design: Corner/cross-cutting complexity layers/service_area_eligible_agency_count_reconciles_across_create_lapse_and_retraining
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    assert area["eligible_agency_count"] == 0, (
        f"a fresh area starts at 0 but eligible_agency_count is {area['eligible_agency_count']}"
    )
    version_at_creation = area["version"]
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.record_training(api, agency["id"], completed_at="2026-07-01T00:00:00Z")
    assert fx.read_service_area(api, area["id"])["eligible_agency_count"] == 0, (
        "training alone leaves the posture INELIGIBLE so the count must still be 0"
    )

    fx.renew_agreement(
        api,
        agency["id"],
        agreement_start_date="2026-07-01",
        agreement_end_date="2028-06-30",
    )
    assert fx.read_agency(api, agency["id"])["eligibility_posture"] == EligibilityPosture.ELIGIBLE
    assert fx.read_service_area(api, area["id"])["eligible_agency_count"] == 1, (
        "the agreement makes Alpha ELIGIBLE so the count must be 1"
    )

    fx.set_clock(api, "2027-07-02T00:00:00Z")
    fx.run_compliance_sweep(api)
    lapsed = fx.read_agency(api, agency["id"])
    assert lapsed["training_status"] == TrainingStatus.LAPSED, (
        f"training_status expected LAPSED but got {lapsed['training_status']}"
    )
    assert lapsed["agreement_status"] == AgreementStatus.ACTIVE, (
        f"the term still runs so agreement_status expected ACTIVE but got "
        f"{lapsed['agreement_status']}"
    )
    assert lapsed["eligibility_posture"] == EligibilityPosture.PROBATION, (
        f"eligibility_posture expected PROBATION but got {lapsed['eligibility_posture']}"
    )
    assert fx.read_service_area(api, area["id"])["eligible_agency_count"] == 0, (
        "the sweep must rewrite the parent's count without any call addressing the area"
    )

    fx.record_training(api, agency["id"], completed_at="2027-07-02T00:00:00Z")
    restored = fx.read_agency(api, agency["id"])
    assert restored["training_status"] == TrainingStatus.CURRENT, (
        f"training_status expected CURRENT but got {restored['training_status']}"
    )
    assert_instant(
        restored["training_expires_at"], "2028-07-01T00:00:00Z", "training_expires_at"
    )
    assert restored["eligibility_posture"] == EligibilityPosture.ELIGIBLE, (
        f"eligibility_posture expected ELIGIBLE but got {restored['eligibility_posture']}"
    )
    final_area = fx.read_service_area(api, area["id"])
    assert final_area["eligible_agency_count"] == 1, (
        f"eligible_agency_count expected 1 but got {final_area['eligible_agency_count']}"
    )
    assert final_area["poverty_population"] == 40000, (
        f"no count rewrite may disturb poverty_population but it reads "
        f"{final_area['poverty_population']}"
    )
    assert_version_incremented(final_area["version"], version_at_creation, min_increment=3)


def _three_lots_in_three_states_at_one_warehouse(api):
    """A posted excess lot, a never-posted receipt and a recall-held lot in one warehouse."""
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
    warehouse = fx.create_warehouse_with_policy(
        api, MonitorPolicy.TURNOVER_BASED, name="WH North"
    )
    excess = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="EXCESS-600",
        cases_received=600,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    raw = fx.create_inventory_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="RAW-100",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    held = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="HELD-100",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    recall = fx.raise_recall(
        api,
        held["id"],
        recall_class=RecallClass.CLASS_III,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Mislabelled pallet placard on the federal lot.",
    )
    return {
        "warehouse": warehouse,
        "excess": excess,
        "raw": raw,
        "held": held,
        "recall": recall,
    }


def test_10_a_monitor_run_scores_only_the_available_lot(api):
    """PRD §3.3: "Only lots in `AVAILABLE` or `WATCH` are scored." PRD §3.3: "Lots in
    `RECEIVED`, `HOLD`, `DISPOSED`, or `DEPLETED` are skipped entirely and keep whatever
    `monitor_flag` they already had." PRD §3.3: "The `monitor_flag` is then decided with
    **excess taking strict precedence over staleness**: if the lot's `cases_on_hand` exceeds
    its commodity's `excess_case_ceiling`, the flag is `EXCESS` and the index plays no part
    in that decision; otherwise, if the rounded `slow_moving_index` is at least 0.60, the
    flag is `SLOW_MOVING`; otherwise the flag is `NONE`." PRD §3.3: "Every scored lot has
    `monitor_flag`, `slow_moving_index`, and `last_monitored_at` written and its `version`
    incremented by one."

    Design: Corner/cross-cutting complexity layers/a_monitor_run_scores_only_available_and_watch_lots_and_skips_received_and_held_ones
    """
    env = _three_lots_in_three_states_at_one_warehouse(api)

    fx.run_monitor(api, env["warehouse"]["id"])

    scored = fx.read_lot(api, env["excess"]["id"])
    assert scored["monitor_flag"] == MonitorFlag.EXCESS, (
        f"600 cases against a 500-case ceiling expected EXCESS but got "
        f"{scored['monitor_flag']}"
    )
    assert_ratio(scored["slow_moving_index"], 0.7, "slow_moving_index")
    assert scored["status"] == LotStatus.WATCH, (
        f"a flagged AVAILABLE lot moves to WATCH but it reads {scored['status']}"
    )
    assert_instant(scored["last_monitored_at"], "2026-08-01T00:00:00Z", "last_monitored_at")

    skipped_receipt = fx.read_lot(api, env["raw"]["id"])
    assert skipped_receipt["status"] == LotStatus.RECEIVED, (
        f"the never-posted receipt expected RECEIVED but got {skipped_receipt['status']}"
    )
    assert skipped_receipt["monitor_flag"] == MonitorFlag.NONE, (
        f"monitor_flag expected NONE but got {skipped_receipt['monitor_flag']}"
    )
    assert_ratio(skipped_receipt["slow_moving_index"], 0.0, "slow_moving_index")
    assert skipped_receipt["last_monitored_at"] is None, (
        f"last_monitored_at expected null but got {skipped_receipt['last_monitored_at']}"
    )

    skipped_hold = fx.read_lot(api, env["held"]["id"])
    assert skipped_hold["status"] == LotStatus.HOLD, (
        f"the recalled lot expected HOLD but got {skipped_hold['status']}"
    )
    assert skipped_hold["hold_recall_id"] == env["recall"]["id"], (
        f"hold_recall_id expected {env['recall']['id']} but got "
        f"{skipped_hold['hold_recall_id']}"
    )
    assert skipped_hold["monitor_flag"] == MonitorFlag.NONE, (
        f"monitor_flag expected NONE but got {skipped_hold['monitor_flag']}"
    )
    assert skipped_hold["last_monitored_at"] is None, (
        f"last_monitored_at expected null but got {skipped_hold['last_monitored_at']}"
    )


def test_11_a_second_run_at_the_same_instant_rescores_without_a_second_transition(api):
    """PRD §3.3: "A lot in `AVAILABLE` that scores `EXCESS` or `SLOW_MOVING` moves
    `AVAILABLE → WATCH`." PRD §3.3: "A lot already in the status its flag implies simply has
    its `slow_moving_index` and `last_monitored_at` refreshed."

    Design: Corner/cross-cutting complexity layers/a_monitor_run_scores_only_available_and_watch_lots_and_skips_received_and_held_ones
    """
    env = _three_lots_in_three_states_at_one_warehouse(api)

    fx.run_monitor(api, env["warehouse"]["id"])
    fx.run_monitor(api, env["warehouse"]["id"])

    rescored = fx.read_lot(api, env["excess"]["id"])
    assert rescored["status"] == LotStatus.WATCH, (
        f"the second run must not move the lot again but it reads {rescored['status']}"
    )
    assert rescored["monitor_flag"] == MonitorFlag.EXCESS, (
        f"monitor_flag expected EXCESS but got {rescored['monitor_flag']}"
    )
    assert_ratio(rescored["slow_moving_index"], 0.7, "slow_moving_index")
    assert_instant(rescored["last_monitored_at"], "2026-08-01T00:00:00Z", "last_monitored_at")
    assert fx.read_lot(api, env["raw"]["id"])["last_monitored_at"] is None, (
        "a skipped lot stays unscored however often the run repeats"
    )


def _submitted_order_awaiting_the_second_reviewer(api):
    """A ten-case submitted order over a hundred-case lot in an open cycle."""
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

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    line = fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
    fx.submit_order(api, order["id"], agency["id"])
    return {
        "agency": agency,
        "lot": lot,
        "cycle": cycle,
        "order": order,
        "line": line,
    }


def test_12_the_approval_response_already_carries_the_totals_it_recomputed(api):
    """PRD §3.6: "Once conversion and reservation succeed, the order's
    `total_cases_approved` is written as the sum of the lines' `cases_approved`, and that
    figure must not exceed the entitlement's `cases_remaining`, otherwise
    `ERR_ALLOCATION_EXCEEDED`." PRD §3.6: "On success `approved_at` is stamped from the
    logical clock, `approved_by_user_id` records the reviewer's `X-User-ID`, each reserved
    lot's `cases_committed` carries its new reservation, the entitlement's `cases_committed`
    grows by `total_cases_approved` with `cases_remaining` recomputed and its `status` moved
    to `PARTIALLY_DRAWN`, the cycle's `draw_posture` is recomputed, and the order's
    `version` is incremented." PRD §2.11: "A cycle's `draw_posture` is recomputed from the
    aggregate state of its entitlement rows whenever any of those rows' `cases_committed` or
    `cases_delivered` changes: it reads `NOT_STARTED` while every entitlement of the cycle is
    still `ENTITLED`, `FULLY_DRAWN` only when every entitlement of the cycle is
    `FULLY_DRAWN`, and `PARTIAL` in every other case."

    Design: Corner/consistency model/every_declared_cascade_is_visible_in_the_writing_response_and_on_immediate_reread
    """
    env = _submitted_order_awaiting_the_second_reviewer(api)

    approved = get_success_data(api.approve_order(env["order"]["id"], headers=fx.SECOND_REVIEWER))

    assert approved["status"] == OrderStatus.APPROVED, (
        f"the approval body itself must read APPROVED but got {approved['status']}"
    )
    assert approved["total_cases_approved"] == 10, (
        f"total_cases_approved expected 10 in the writing response but got "
        f"{approved['total_cases_approved']}"
    )
    assert_pounds(approved["total_pounds"], 200.00, "total_pounds")
    assert approved["total_pallets"] == 1, (
        f"total_pallets expected 1 but got {approved['total_pallets']}"
    )

    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=10, cases_shipped_to_date=0)
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_delivered"] == 0, (
        f"cases_delivered expected 0 but got {allocation['cases_delivered']}"
    )
    assert allocation["cases_remaining"] == 990, (
        f"cases_remaining expected 990 but got {allocation['cases_remaining']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["draw_posture"] == DrawPosture.PARTIAL, (
        f"one partially drawn entitlement leaves the cycle PARTIAL but it reads "
        f"{cycle['draw_posture']}"
    )
    assert cycle["total_allocated_cases"] == 1000, (
        f"the approval may not disturb total_allocated_cases but it reads "
        f"{cycle['total_allocated_cases']}"
    )
    assert cycle["status"] == CycleStatus.OPEN, (
        f"the cycle stays OPEN through an approval but it reads {cycle['status']}"
    )


def test_13_the_reservation_is_readable_at_the_same_instant_and_stays_put(api):
    """PRD §3.6: "Each amount taken is appended to the line's `lot_assignments` in fill
    order as a pairing of the `lot_id` drawn from and the `cases` taken, and is added to that
    lot's `cases_committed`." PRD §2.4: "Whenever this document says "the current instant", it means the
    value of that logical clock at the moment the request is processed."

    Design: Corner/consistency model/every_declared_cascade_is_visible_in_the_writing_response_and_on_immediate_reread
    """
    env = _submitted_order_awaiting_the_second_reviewer(api)
    fx.approve_order(api, env["order"]["id"])

    first_read = fx.read_order_lines(api, env["order"]["id"])[0]
    assert first_read["cases_approved"] == 10, (
        f"cases_approved expected 10 but got {first_read['cases_approved']}"
    )
    assert_lot_assignments(first_read, [(env["lot"]["id"], 10)])

    second_read = fx.read_order_lines(api, env["order"]["id"])[0]
    assert second_read["cases_approved"] == first_read["cases_approved"], (
        "a repeated read at the same logical instant must return the same cases_approved"
    )
    assert_lot_assignments(second_read, [(env["lot"]["id"], 10)])
    assert second_read["version"] == first_read["version"], (
        f"nothing settles between two reads at one instant but the version moved from "
        f"{first_read['version']} to {second_read['version']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=10, cases_shipped_to_date=0)
    assert_instant(
        fx.read_clock(api)["current_utc"], "2026-08-06T00:00:00Z", "current_utc"
    )
