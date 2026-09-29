"""Cross-cutting layers: optimistic concurrency on both guarded parents, the
statutory penalty ceiling, and cascades that must land entirely or not at all.
"""
from test_helpers import (
    ADMIN,
    AUG_01,
    AUG_10,
    AUG_11,
    AUG_20,
    AUG_21,
    SEP_20,
    ApiErrorId,
    active_equipment,
    advance_clock,
    api_client,
    application_payload,
    assert_depot_conservation,
    assert_fields,
    assert_instant,
    assert_ledger_conservation,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    charged_case,
    close_period,
    create_deployment,
    create_owner,
    create_period,
    create_terminal,
    elect_cmp,
    enforce_case,
    file_reply,
    finalize_case,
    four_closed_periods,
    import_settlement,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    open_case,
    open_investigation,
    owner_headers,
    refresh_case,
    refresh_depot,
    refresh_deployment,
    refresh_owner,
    refresh_period,
    refresh_store,
    refresh_terminal,
    store_patch_payload,
    store_payload,
    substantiated_trafficking_investigation,
    validate_error,
    validate_success,
    INV_PASS,
)

CAP_PERIODS = (
    (5, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    (6, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    (7, "2026-07-01T00:00:00Z", AUG_01),
)


def test_stale_store_version_is_refused_and_the_refreshed_version_succeeds():
    """A profile edit bumps the store, so an application filed against the pre-edit
    snapshot is 412 and so is a second edit quoting the same spent token, while the
    refreshed token succeeds -- and the successful filing bumps the store again.

    The rule names both writes and both directions: "Every store profile edit and
    every application creation increments `Store.version`, so a caller that read the
    store and then saw the profile edited must re-read before filing. If
    `expected_store_version` does not equal the store's current `version`, the
    request is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412). The same field and
    the same rejection apply to a store profile edit, which likewise names
    `expected_store_version` and likewise refuses a stale value with
    `ERR_STALE_STORE_VERSION` (HTTP 412)." The successful edit's own bump is
    specified too: "A successful edit recomputes `staple_sales_bps` and
    `criterion_b_pass` from the new sales figures and advances the store's `version`
    by one, which is exactly what invalidates any application snapshot a client was
    holding."

    Design: Corner/cross_cutting_complexity_layers/stale_store_version_is_refused_and_the_refreshed_version_succeeds
    """
    owner = create_owner()
    owner_h = owner_headers(owner)
    store = validate_success(
        api_client.create_store(
            store_payload(owner["id"], store_name="Occ Corner Market"), owner_h
        ),
        201,
    )
    version_1 = store["version"]

    patched = validate_success(
        api_client.update_store(
            store["id"], store_patch_payload(version_1, staple_shelf_linear_feet=36), owner_h
        )
    )
    version_2 = patched["version"]
    assert version_2 == version_1 + 1, patched
    assert patched["staple_shelf_linear_feet"] == 36, patched

    stale_application = api_client.create_application(
        application_payload(store["id"], version_1, reported_inventory_lines=INV_PASS),
        owner_h,
    )
    validate_error(stale_application, ApiErrorId.ERR_STALE_STORE_VERSION.value, 412)
    assert_no_rows(api_client.list_applications(ADMIN, {"store_id": store["id"]}))

    stale_patch = api_client.update_store(
        store["id"], store_patch_payload(version_1, staple_shelf_linear_feet=40), owner_h
    )
    validate_error(stale_patch, ApiErrorId.ERR_STALE_STORE_VERSION.value, 412)
    assert refresh_store(store["id"])["staple_shelf_linear_feet"] == 36

    application = validate_success(
        api_client.create_application(
            application_payload(store["id"], version_2, reported_inventory_lines=INV_PASS),
            owner_h,
        ),
        201,
    )
    assert application["status"] == "DRAFT", application
    assert refresh_store(store["id"])["version"] == version_2 + 1
    assert_row_count(api_client.list_applications(ADMIN, {"store_id": store["id"]}), 1)


def test_stale_sanction_case_version_blocks_the_cmp_election():
    """An otherwise flawless election -- hardship store, CHARGE_ISSUED case, window
    wide open -- quoting the pre-charge case version is 412, so the version token is
    checked before the state, window and hardship gates, and no election row is left
    behind.

    The election's token is mandatory and its refusal is its own: "Filing a
    civil-money-penalty election requires `expected_sanction_case_version` as a
    non-optional field in the request body, carrying the client's last observed
    `version` of the target `SanctionCase`." "If `expected_sanction_case_version`
    does not equal the case's current `version`, the election is rejected with
    `ERR_STALE_SANCTION_CASE_VERSION` (HTTP 412) rather than silently re-quoted
    against a case the client has not observed." Its place in the ladder is fixed:
    "8. **Optimistic concurrency.** The supplied expected-version value must equal
    the parent's current `version`, yielding `ERR_STALE_STORE_VERSION` or
    `ERR_STALE_SANCTION_CASE_VERSION` (412)." The store carries four closed
    monitoring periods so the follow-up election, quoted "against the election-time
    history", has a basis pool to quote from.

    Design: Corner/cross_cutting_complexity_layers/stale_sanction_case_version_blocks_the_cmp_election
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    case = charged_case(context)

    stale = api_client.create_cmp_election(
        case["id"],
        {"expected_sanction_case_version": case["version"] - 1},
        context.owner_h,
    )
    stale_body = validate_error(
        stale, ApiErrorId.ERR_STALE_SANCTION_CASE_VERSION.value, 412
    )
    for wrong in (
        ApiErrorId.ERR_CMP_ELECTION_WINDOW_CLOSED,
        ApiErrorId.ERR_INVALID_STATE,
        ApiErrorId.ERR_CMP_NOT_AVAILABLE,
    ):
        assert stale_body["error_id"] != wrong.value, stale_body
    assert_no_rows(api_client.list_cmp_elections(case["id"], ADMIN))

    election = elect_cmp(case, context.owner)
    assert election["status"] == "ELECTED", election
    assert_row_count(api_client.list_cmp_elections(case["id"], ADMIN), 1)
    assert refresh_case(case["id"])["status"] == "CHARGE_ISSUED"


def test_civil_money_penalty_is_capped_and_reports_cmp_capped():
    """Three closed periods of 8,000,000c give a monthly penalty of 800,000c, which
    the ten trafficking months would take to 8,000,000c, so the stored amount clamps
    to 6,900,000c with the cap reported -- and the ledger, the case balance and the
    owner rollup all carry the capped figure.

    The arithmetic and the ceiling are one sentence each: "From the basis,
    `avg_monthly_redemption_cents` is the sum of `redemption_total_cents` over the
    basis periods divided by the number of basis periods, rounded half up to whole
    cents. `monthly_penalty_cents` is ten percent of that average -- the average
    multiplied by 1,000 basis points, divided by 10,000 -- rounded half up to whole
    cents. The month multiplier is 10 months flat for a `TRAFFICKING` case, and
    otherwise the `disqualification_months` the previous paragraph derived.
    `cmp_amount_cents` is the monthly penalty multiplied by the month multiplier,
    capped at the statutory maximum of $69,000.00, and `cmp_capped` is true exactly
    when the uncapped product would have exceeded that maximum." The basis is chosen
    by seasoning: "When the span is **fewer than 365 days** ... the variant is
    `PEAK_3_PERIOD_AVERAGE` and the basis is the 3 periods with the highest
    `redemption_total_cents`".

    Design: Corner/cross_cutting_complexity_layers/civil_money_penalty_is_capped_and_reports_cmp_capped
    """
    context = authorized_store()
    period_ids = []
    for period_index, period_start, period_end in CAP_PERIODS:
        period = create_period(
            context.store_id,
            period_index=period_index,
            period_start=period_start,
            period_end=period_end,
        )
        import_settlement(
            period["id"],
            imported_total_cents=8000000,
            imported_transaction_count=80,
            imported_large_transaction_cents=0,
            imported_even_dollar_transaction_count=0,
        )
        closed = close_period(period["id"])
        assert_fields(
            closed,
            {"status": "CLOSED", "anomaly_score": 45, "flag_level": "FLAG_L1"},
            f"closed period {period_index}",
        )
        period_ids.append(period["id"])

    investigation = substantiated_trafficking_investigation(context.store_id)
    case = open_case(investigation["id"], "TRAFFICKING")
    charged = issue_charge_letter(case["id"])
    elect_cmp(charged, context.owner)
    file_reply(case["id"], context.owner)

    determined = issue_determination(case["id"], "CMP_IN_LIEU")
    assert_fields(
        determined,
        {
            "status": "DETERMINED",
            "sanction_type": "CMP_IN_LIEU",
            "cmp_basis_variant": "PEAK_3_PERIOD_AVERAGE",
            "avg_monthly_redemption_cents": 8000000,
            "monthly_penalty_cents": 800000,
            "cmp_amount_cents": 6900000,
            "cmp_capped": True,
            "cmp_outstanding_cents": 6900000,
        },
        "capped trafficking penalty",
    )
    assert sorted(determined["cmp_basis_period_ids"]) == sorted(period_ids), determined

    entries = ledger_entries(case["id"])
    assert len(entries) == 1, entries
    assert_fields(
        entries[0],
        {
            "entry_type": "CMP_ASSESSED",
            "amount_cents": 6900000,
            "reason_code": "DETERMINATION",
            "balance_after_cents": 6900000,
        },
        "assessment row",
    )
    assert_ledger_conservation(entries, refresh_case(case["id"]))
    assert_fields(
        refresh_owner(context.owner_id),
        {
            "cmp_outstanding_cents": 6900000,
            "sanction_flag": "HAS_ACTIVE_CMP_DEBT",
            "status": "ACTIVE",
        },
        "owner rollup under the capped penalty",
    )
    for period_id in period_ids:
        assert refresh_period(period_id)["flag_level"] == "FLAG_L1"


def test_refused_enforcement_performs_no_partial_cascade():
    """The premature enforcement of an already final permanent disqualification
    lands none of its four levels -- deployment, terminal, depot and store are all
    untouched -- and the same request at the effective date moves every level at
    once.

    Enforcement is gated on the date the finalization fixed: "Finalization of a
    disqualification fixes `effective_date` at thirty days after
    `final_decision_at`." and "enforcement may proceed when the clock is at or after
    `effective_date`". Only the successful call cascades: "A successful enforcement
    moves the case to `ENFORCED`, its second terminal status, and sets `enforced_at`
    from the logical clock. It then cascades four hops outward." Its second hop is
    the hardware: "every one of the store's `ACTIVE` terminal commitments moves to
    `RECALL_PENDING` with `close_reason_code` set to `AUTHORIZATION_LOST`, and the
    store's `active_terminal_count` is decremented for each. Third, each unit behind
    those commitments moves from `DEPLOYED` to `PENDING_RETURN` and every affected
    depot's counters are recomputed." Finalization has already moved the
    authorization dimension -- "for a `PERMANENT_DISQUALIFICATION` or
    `TEMPORARY_DISQUALIFICATION` its `authorization_status` moves from `AUTHORIZED`
    to `SUSPENDED`" -- so the refused enforcement must leave the store on
    `SUSPENDED`, reaching the terminal `DISQUALIFIED` only on the successful call.

    Design: Corner/cross_cutting_complexity_layers/refused_enforcement_performs_no_partial_cascade
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    investigation = substantiated_trafficking_investigation(context.store_id)
    case = open_case(investigation["id"], "TRAFFICKING")
    issue_charge_letter(case["id"])
    advance_clock(AUG_11)
    issue_determination(case["id"], "PERMANENT_DISQUALIFICATION")
    advance_clock(AUG_21)
    finalized = finalize_case(case["id"])
    assert_instant(finalized["effective_date"], SEP_20, "effective_date")

    early = api_client.enforce_sanction_case(case["id"], ADMIN)
    validate_error(early, ApiErrorId.ERR_ENFORCEMENT_NOT_DUE.value, 409)

    assert_fields(
        refresh_deployment(equipment.deployment_id),
        {"status": "ACTIVE", "close_reason_code": None},
        "deployment after the refused enforcement",
    )
    assert refresh_terminal(equipment.terminal_id)["status"] == "DEPLOYED"
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {
            "units_deployed": 1,
            "units_pending_return": 0,
            "units_reserved": 0,
            "units_in_stock": 4,
        },
    )
    assert_fields(
        refresh_store(context.store_id),
        {
            "authorization_status": "SUSPENDED",
            "active_terminal_count": 1,
            "sanction_status": "SANCTION_FINAL",
        },
        "store after the refused enforcement",
    )
    refused_case = refresh_case(case["id"])
    assert refused_case["status"] == "SANCTION_FINAL", refused_case
    assert refused_case["enforced_at"] is None, refused_case
    assert_fields(
        refresh_owner(context.owner_id),
        {
            "permanent_disqualification_count": 1,
            "sanction_flag": "PERMANENTLY_DISQUALIFIED",
            "status": "ACTIVE",
        },
        "owner after the refused enforcement",
    )

    advance_clock(SEP_20)
    enforced = enforce_case(case["id"])
    assert enforced["status"] == "ENFORCED", enforced
    assert_fields(
        refresh_deployment(equipment.deployment_id),
        {"status": "RECALL_PENDING", "close_reason_code": "AUTHORIZATION_LOST"},
        "deployment after enforcement",
    )
    assert refresh_terminal(equipment.terminal_id)["status"] == "PENDING_RETURN"
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_deployed": 0, "units_pending_return": 1},
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "DISQUALIFIED", "active_terminal_count": 0},
        "store after enforcement",
    )


def test_opening_an_investigation_releases_reserved_deployments_but_spares_active_ones():
    """Opening the investigation releases the RESERVED deployment and returns its
    unit to stock -- not to pending-return -- while the ACTIVE deployment on the same
    store is untouched, so exactly one of two children moves and the depot's five
    units still reconcile.

    The cascade is conditional on the child's state: "Every `RESERVED` terminal
    commitment of the store is driven to `RELEASED`, with the units returned to
    `IN_STOCK` and the depot counters recomputed -- speculative hardware is not
    extended to a store under investigation." The store dimension that moves is only
    one of the two: "The store's `sanction_status` moves to `UNDER_INVESTIGATION`,
    which is permitted from `NONE` and also from `SANCTION_REVERSED`". And the
    counters are per-status counts: "`units_in_stock` is the residual".

    Design: Corner/cross_cutting_complexity_layers/opening_an_investigation_releases_reserved_deployments_but_spares_active_ones
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    second_terminal = create_terminal(
        equipment.depot, serial_number="EBT-0002", model="EBT_ONLY_DIAL"
    )
    reserved = create_deployment(
        context.store,
        second_terminal,
        deploy_start=AUG_10,
        deploy_end=AUG_20,
    )
    assert reserved["status"] == "RESERVED", reserved

    investigation = open_investigation(context.store_id, opened_reason="TIP")
    assert investigation["status"] == "OPEN", investigation

    released = refresh_deployment(reserved["id"])
    assert released["status"] == "RELEASED", released
    assert_instant(released["closed_at"], AUG_01, "released closed_at")
    assert refresh_terminal(second_terminal["id"])["status"] == "IN_STOCK"

    assert refresh_deployment(equipment.deployment_id)["status"] == "ACTIVE"
    assert refresh_terminal(equipment.terminal_id)["status"] == "DEPLOYED"

    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {
            "units_in_stock": 4,
            "units_reserved": 0,
            "units_deployed": 1,
            "units_pending_return": 0,
            "units_retired": 0,
        },
    )
    assert_fields(
        refresh_store(context.store_id),
        {
            "active_terminal_count": 1,
            "sanction_status": "UNDER_INVESTIGATION",
            "authorization_status": "AUTHORIZED",
        },
        "store after the investigation opened",
    )


def test_active_terminal_count_survives_the_recall_path_without_double_counting():
    """The two-step teardown decrements the store's active terminal count exactly
    once: the recall takes it from 2 to 1, the subsequent return of that same unit
    does not decrement again, and returning the still-active unit takes it to 0 with
    every unit back in stock.

    Each hop re-derives the counters: "`active_terminal_count` is the number of that
    store's `ACTIVE` terminal commitments" and "`units_in_stock` is the residual".
    The recall and the return are separate hops with separate unit statuses: a recall
    drives the unit to `PENDING_RETURN` and "Records physical return of an active or
    recalled terminal to the depot". Both closed statuses are terminal, so a repeat
    is a state error: "9. **State machine.** The entity's current status must permit
    the requested transition -- otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/cross_cutting_complexity_layers/active_terminal_count_survives_the_recall_path_without_double_counting
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    second_terminal = create_terminal(
        equipment.depot, serial_number="EBT-0002", model="EBT_ONLY_DIAL"
    )
    second = create_deployment(context.store, second_terminal)
    validate_success(api_client.activate_deployment(second["id"], ADMIN))

    assert refresh_store(context.store_id)["active_terminal_count"] == 2
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_deployed": 2, "units_in_stock": 3},
    )

    recalled = validate_success(api_client.recall_deployment(second["id"], ADMIN))
    assert recalled["status"] == "RECALL_PENDING", recalled
    assert refresh_terminal(second_terminal["id"])["status"] == "PENDING_RETURN"
    assert refresh_store(context.store_id)["active_terminal_count"] == 1
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_deployed": 1, "units_pending_return": 1, "units_in_stock": 3},
    )

    returned = validate_success(api_client.return_deployment(second["id"], ADMIN))
    assert returned["status"] == "RETURNED", returned
    assert_instant(returned["closed_at"], AUG_01, "returned closed_at")
    assert refresh_terminal(second_terminal["id"])["status"] == "IN_STOCK"
    assert refresh_store(context.store_id)["active_terminal_count"] == 1
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_deployed": 1, "units_pending_return": 0, "units_in_stock": 4},
    )

    last = validate_success(api_client.return_deployment(equipment.deployment_id, ADMIN))
    assert last["status"] == "RETURNED", last
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_deployed": 0, "units_pending_return": 0, "units_in_stock": 5},
    )

    for deployment_id in (second["id"], equipment.deployment_id):
        repeat = api_client.return_deployment(deployment_id, ADMIN)
        validate_error(repeat, ApiErrorId.ERR_INVALID_STATE.value, 409)
