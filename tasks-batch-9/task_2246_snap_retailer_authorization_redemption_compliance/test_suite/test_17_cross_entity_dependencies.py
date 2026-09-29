"""Operations blocked by state that lives on some other entity.

A sale needs both an authorized store and an activated deployment; an ownership
transfer is blocked by the previous owner's debt; an anomaly investigation needs
its triggering period to have actually scored at the top band.
"""
from test_helpers import (
    ADMIN,
    BASKET_SIMPLE,
    INV_PASS,
    ApiErrorId,
    activate_deployment,
    advance_clock,
    api_client,
    application_payload,
    assert_fields,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    close_period,
    create_owner,
    create_period,
    create_store,
    created,
    elect_cmp,
    file_reply,
    import_settlement,
    investigation_payload,
    issue_charge_letter,
    issue_determination,
    four_closed_periods,
    ok,
    open_case,
    owner_headers,
    pos_transaction_payload,
    refresh_application,
    refresh_owner,
    refresh_store,
    refresh_terminal,
    reserved_equipment,
    schedule_visit,
    start_visit,
    submit_findings,
    substantiated_ineligible_investigation,
    validate_error,
)


def _sale(context, equipment):
    return api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=BASKET_SIMPLE,
            snap_benefit_available_cents=1000,
            other_tender_offered_cents=0,
            household_ebt_card_last4="8821",
        ),
        context.clerk_h,
    )


def test_sale_on_a_merely_reserved_deployment_is_refused_though_the_store_is_fine():
    """An authorized store with an unimpeachable basket still cannot ring up a
    sale on a deployment that has not been activated.

    The specification requires the deployment itself to be transacting: activation
    is what makes "the store can transact", so a RESERVED commitment answers with
    its own error identifier while the store's own dimensions stay clean.

    Design: Difficulty/cross_entity_state_dependency/pos_sale_requires_authorized_store_and_active_deployment_together
    """
    context = authorized_store()
    equipment = reserved_equipment(context.store)

    response = _sale(context, equipment)

    validate_error(response, ApiErrorId.ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE.value, 409)
    assert refresh_store(context.store_id)["authorization_status"] == "AUTHORIZED"
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
    assert refresh_terminal(equipment.terminal_id)["status"] == "RESERVED"
    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )


def test_activating_the_same_deployment_turns_the_identical_request_into_a_sale():
    """Nothing changes but the deployment's state, and the request that was
    refused now clears.

    Activation moves the terminal from RESERVED to DEPLOYED and raises the store's
    `active_terminal_count`, and the specification settles a fully covered basket
    entirely in benefits: 758c of milk against 1,000c available.

    Design: Difficulty/cross_entity_state_dependency/pos_sale_requires_authorized_store_and_active_deployment_together
    """
    context = authorized_store()
    equipment = reserved_equipment(context.store)
    _sale(context, equipment)

    equipment.deployment = activate_deployment(equipment.deployment)

    assert refresh_terminal(equipment.terminal_id)["status"] == "DEPLOYED"
    assert refresh_store(context.store_id)["active_terminal_count"] == 1
    sale = created(_sale(context, equipment))
    assert_fields(
        sale, {"status": "AUTHORIZED", "ebt_tender_cents": 758}, "sale after activation"
    )
    assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id}), 1
    )


def _succession_pending_decision():
    """A first owner carrying 423,456c of penalty debt, and a second owner whose
    successor store is one approval away from authorization."""
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "CMP_IN_LIEU")

    owner2 = create_owner(
        legal_name="Second Street Foods Inc",
        ownership_type="CORPORATION",
        tax_id_last4="9032",
    )
    store2 = create_store(
        owner2,
        store_name="Rio Convenience (New Owner)",
        predecessor_store_id=context.store_id,
        hardship_designated=None,
    )
    application2 = created(
        api_client.create_application(
            application_payload(
                store2["id"],
                store2["version"],
                application_type="REAUTHORIZATION_OWNERSHIP_CHANGE",
                reported_inventory_lines=INV_PASS,
            ),
            owner_headers(owner2),
        )
    )
    ok(api_client.submit_application(application2["id"], owner_headers(owner2)))
    visit = schedule_visit(
        application2,
        context.inspector,
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T06:00:00Z",
    )
    advance_clock("2026-08-01T04:00:00Z")
    start_visit(visit, context.inspector)
    submit_findings(
        visit,
        context.inspector,
        observed_inventory_lines=INV_PASS,
        observed_staple_shelf_linear_feet=30,
    )
    return context, owner2, store2, application2


def test_ownership_change_approval_is_blocked_by_the_predecessor_owners_debt():
    """The successor's own application is perfect, yet approval is refused because
    the previous owner still owes a civil money penalty.

    The specification blocks the transfer while money is outstanding: the previous
    owner "carries the `HAS_ACTIVE_CMP_DEBT` flag until the balance reaches zero",
    and the transfer-integrity rule refuses the reauthorization until then. The
    blocking state sits two entities away, on a different owner entirely.

    Design: Difficulty/cross_entity_state_dependency/reauthorization_approval_blocked_by_predecessor_owner_cmp_debt
    """
    context, owner2, _store2, application2 = _succession_pending_decision()

    response = api_client.decide_application(
        application2["id"], {"outcome": "APPROVED"}, ADMIN
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_CMP_OUTSTANDING.value, 409)
    assert_fields(
        refresh_owner(context.owner_id),
        {"cmp_outstanding_cents": 423456, "sanction_flag": "HAS_ACTIVE_CMP_DEBT"},
        "predecessor owner",
    )
    assert_fields(
        refresh_owner(owner2["id"]),
        {"cmp_outstanding_cents": 0, "sanction_flag": "CLEAR"},
        "successor owner",
    )


def test_blocked_succession_leaves_the_successor_application_under_review():
    """The refusal decides nothing: the application stays UNDER_REVIEW with a
    passing verification, and the successor store is never authorized.

    The specification keeps the eligibility verdict and the decision separate, so
    `verified_criterion_pass` remains true -- the successor's own eligibility was
    never in doubt -- while the store keeps no FNS number and still points at its
    predecessor.

    Design: Difficulty/cross_entity_state_dependency/reauthorization_approval_blocked_by_predecessor_owner_cmp_debt
    """
    context, _owner2, store2, application2 = _succession_pending_decision()

    api_client.decide_application(application2["id"], {"outcome": "APPROVED"}, ADMIN)

    assert_fields(
        refresh_application(application2["id"]),
        {
            "status": "UNDER_REVIEW",
            "decided_at": None,
            "verified_criterion_pass": True,
        },
        "successor application",
    )
    assert_fields(
        refresh_store(store2["id"]),
        {
            "authorization_status": "NOT_AUTHORIZED",
            "fns_number": None,
            "predecessor_store_id": context.store_id,
        },
        "successor store",
    )


def _unflagged_closed_period():
    context = authorized_store()
    period = create_period(
        context.store_id,
        period_index=1,
        period_start="2026-06-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    import_settlement(
        period["id"],
        imported_total_cents=1234567,
        imported_transaction_count=40,
        imported_large_transaction_cents=0,
        imported_even_dollar_transaction_count=0,
    )
    return context, close_period(period["id"])


def test_anomaly_investigation_needs_a_period_that_actually_scored_flag_l3():
    """A closed period that scored zero cannot justify opening an
    anomaly-flag-three investigation, even though it exists and belongs to the
    store.

    The gate is on a computed field of the parent rather than on its status: an
    investigation opened for the top anomaly band must name a period whose
    `flag_level` really is `FLAG_L3`, and this one closed at `FLAG_L0` with a
    score of 0 against its 1,250,000c size expectation.

    Design: Difficulty/cross_entity_state_dependency/anomaly_investigation_requires_trigger_period_actually_at_flag_l3
    """
    context, period = _unflagged_closed_period()
    assert_fields(
        period,
        {
            "status": "CLOSED",
            "anomaly_score": 0,
            "flag_level": "FLAG_L0",
            "size_expectation_cents": 1250000,
        },
        "unflagged period",
    )

    response = api_client.create_investigation(
        investigation_payload(
            context.store_id,
            opened_reason="ANOMALY_FLAG_L3",
            trigger_period_id=period["id"],
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_TRIGGER_PERIOD_NOT_FLAGGED.value, 422)


def test_refused_anomaly_investigation_leaves_the_store_completely_clean():
    """The rejected request writes no investigation and does not touch the store's
    sanction dimension or its flag level.

    An investigation is what moves `sanction_status` to UNDER_INVESTIGATION, so a
    refused opening must leave it at NONE, and the store's derived flag level
    stays at the band its only closed period actually reached.

    Design: Difficulty/cross_entity_state_dependency/anomaly_investigation_requires_trigger_period_actually_at_flag_l3
    """
    context, period = _unflagged_closed_period()

    api_client.create_investigation(
        investigation_payload(
            context.store_id,
            opened_reason="ANOMALY_FLAG_L3",
            trigger_period_id=period["id"],
        ),
        ADMIN,
    )

    assert_no_rows(
        api_client.list_investigations(ADMIN, {"store_id": context.store_id})
    )
    assert_fields(
        refresh_store(context.store_id),
        {"sanction_status": "NONE", "redemption_flag_level": "FLAG_L0"},
        "untouched store",
    )
