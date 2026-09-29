"""Initial states, backward edges, terminal lockdown and cross-entity side effects.

Each case pins one edge of one machine: where a child row starts, which
transitions are defined, what a refused transition must leave untouched, and which
neighbouring row a successful transition is obliged to move.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_compliance_sweep_tally,
    assert_lease_disposition,
    assert_markdown_stage,
    assert_sales_day,
    assert_settlement,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_sales_day,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    open_lease_disposition,
    open_settlement,
    pin_clock,
    read_engagement,
    read_store,
    revoke_license,
    run_compliance_sweep,
    setup_approved_engagement,
    setup_planned_store,
    setup_selling_store,
    submit_engagement,
    submit_expense_item,
    validate_error,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
KESTREL_LEASE = {
    "landlord_name": "Kestrel Realty", "surrender_deadline_date": "2026-12-01",
    "daily_holdover_rate_cents": 25000, "rent_arrears_cents": 400000,
    "cam_arrears_cents": 150000, "restoration_cost_cents": 600000,
    "fixture_reserve_price_cents": 500000, "surrender_credit_cents": 0,
}
FIRST_STAGE = {
    "stage_index": 1, "discount_pct": 0.2, "sell_through_target_pct": 0.25,
    "window_start_date": "2026-09-16", "window_end_date": "2026-10-01",
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_license(license_id):
    return validate_success(
        api_client.get_gob_license(license_id, make_compliance_headers())
    )


def _read_settlement(settlement_id):
    return validate_success(
        api_client.get_settlement(settlement_id, make_consultant_headers())
    )


class TestDeclaredInitialStates:
    def test_four_child_machines_each_open_on_their_own_initial_state(self):
        """A stage, a lease, a selling day and an expense, all freshly created.

        The PRD says: "A newly authored stage begins at `stage_status` of `ARMED` with
        `escalation_applied_pct` at exactly 0.0000, `closed_reason` and
        `checkpoint_sell_through_pct` unset, and `activated_at` unset."

        Design: Corner/state_machines/child_rows_start_in_their_declared_initial_states
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2001", "address_line": "S-2001 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2001"},
        )
        stage = add_markdown_stage(scenario["store"]["id"], **FIRST_STAGE)
        assert_markdown_stage(stage)
        assert stage["stage_status"] == "ARMED"
        assert stage["closed_reason"] is None
        assert stage["escalation_applied_pct"] == pytest.approx(0.0000, abs=0.00001)
        assert stage["activated_at"] is None
        assert stage["version"] == 1

    def test_a_lease_disposition_opens_in_draft_at_round_zero(self):
        """No offer has been sent, so the negotiation counter is still zero.

        The PRD says: "The disposition opens at `disposition_status` of `DRAFT` with
        `negotiation_round` at 0 and every negotiated, computed, and allocation field
        unset."

        Design: Corner/state_machines/child_rows_start_in_their_declared_initial_states
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2001", "address_line": "S-2001 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2001"},
        )
        lease = open_lease_disposition(scenario["store"]["id"], **KESTREL_LEASE)
        assert_lease_disposition(lease)
        assert lease["disposition_status"] == "DRAFT"
        assert lease["negotiation_round"] == 0
        # "every negotiated, computed, and allocation field unset" -- the PRD
        # spends the word "0" where it means zero (§3.7 opens an employee with
        # "`served_days` and `earned_bonus_cents` both 0, and `notice_given_date`
        # ... unset"), so a negotiated field opens null rather than at zero.
        assert lease["agreed_surrender_payment_cents"] is None
        assert lease["offered_surrender_payment_cents"] is None
        assert lease["landlord_counter_amount_cents"] is None
        assert lease["version"] == 1

    def test_a_filed_selling_day_waits_in_review_outside_the_realized_money(self):
        """PENDING_REVIEW money has not reached the ledger.

        The PRD says: "The filed day is stored at `day_status` of `PENDING_REVIEW` with
        `net_sales_cents` computed as the two net-sales figures added together, the
        filing identity captured in `submitted_by_user_id`, and `posted_at`,
        `reviewed_by_user_id`, and `allocation_note` all unset."

        Design: Corner/state_machines/child_rows_start_in_their_declared_initial_states
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2001", "address_line": "S-2001 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2001"},
        )
        day = file_sales_day(
            scenario["store"]["id"], business_date="2026-09-15",
            original_net_sales_cents=120000, augmentation_net_sales_cents=0,
            original_units_sold=40, augmentation_units_sold=0,
        )
        assert_sales_day(day)
        assert day["day_status"] == "PENDING_REVIEW"
        assert day["version"] == 1
        assert read_store(scenario["store"]["id"])[
            "realized_gross_recovery_cents"
        ] == 0

    def test_a_submitted_expense_has_no_shares_and_no_place_in_the_aggregate(self):
        """SUBMITTED sits outside the engagement's three expense aggregates.

        The PRD says: "Voiding a `SUBMITTED` item is aggregate-neutral, because a
        submitted item was never inside the three engagement aggregates to begin with;
        voiding an `APPROVED` item is a compensating action that removes it from all
        three, restoring them to exactly their pre-approval values."

        Design: Corner/state_machines/child_rows_start_in_their_declared_initial_states
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2001", "address_line": "S-2001 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2001"},
        )
        item = submit_expense_item(
            scenario["engagement"]["id"], store_id=scenario["store"]["id"],
            expense_category="ADVERTISING", amount_cents=90000,
            incurred_date="2026-09-15",
        )
        assert item["expense_status"] == "SUBMITTED"
        assert item["liquidator_share_cents"] == 0
        assert item["retailer_share_cents"] == 0
        assert item["version"] == 1
        assert read_engagement(scenario["engagement"]["id"])[
            "expense_total_cents"
        ] == 0


class TestEngagementBackwardEdgeAndIdempotency:
    def test_return_for_revision_restores_draft_and_fires_no_store_cascade(self):
        """The only backward edge of the engagement machine leaves the store PLANNED.

        The PRD says: "A `RETURN_FOR_REVISION` decision sends the engagement back
        `PENDING_RETAILER_APPROVAL → DRAFT` and touches no store whatsoever; the
        consultant revises and resubmits, and this revision loop may repeat without
        limit."

        Design: Corner/state_machines/engagement_return_for_revision_loops_back_to_draft_and_leaves_stores_planned
        """
        scenario = setup_planned_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2002", "address_line": "S-2002 Liquidation Row",
            },
        )
        submit_engagement(scenario["engagement"]["id"])
        returned = approve_engagement(
            scenario["engagement"]["id"], decision="RETURN_FOR_REVISION"
        )
        assert returned["engagement_status"] == "DRAFT"
        assert returned["version"] == 3
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "PLANNED"
        assert store["selling_start_date"] is None
        assert store["version"] == 1

    def test_the_engagement_can_be_submitted_again_after_the_return(self):
        """Resubmission recomputes the opening arithmetic and advances the version.

        The PRD says: "On success the submitting identity is recorded in
        `submitted_by_user_id` — and re-recorded on every subsequent submission, because
        this step may repeat — and the agreement's opening arithmetic is laid down:
        `original_cost_value_cents` is re-summed from the cost value of every
        original-merchandise lot across every store of the engagement,
        `guaranty_amount_cents` is re-derived as that original cost value multiplied by
        `guaranty_pct` and rounded half up to whole cents for a `GUARANTEED` or `HYBRID`
        agreement and set to exactly 0 for a `FEE_BASED` one, and
        `projected_gross_recovery_cents` and `projected_shortfall_cents` are recomputed
        as described in §3.2."

        Design: Corner/state_machines/engagement_return_for_revision_loops_back_to_draft_and_leaves_stores_planned
        """
        scenario = setup_planned_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2002", "address_line": "S-2002 Liquidation Row",
            },
        )
        submit_engagement(scenario["engagement"]["id"])
        approve_engagement(
            scenario["engagement"]["id"], decision="RETURN_FOR_REVISION"
        )
        resubmitted = submit_engagement(scenario["engagement"]["id"])
        assert resubmitted["engagement_status"] == "PENDING_RETAILER_APPROVAL"
        assert resubmitted["version"] == 4
        assert resubmitted["original_cost_value_cents"] == 2000000

    def test_a_second_submit_for_approval_is_refused_and_bumps_nothing(self):
        """Submitting twice is not idempotent — the second call is a state error.

        The PRD says: "Three preconditions hold: the engagement must currently be
        `DRAFT`, it must have at least one store, and every one of its stores must hold
        at least one inventory lot of original retailer merchandise; a submission that
        fails any of the three is refused with `ERR_ENGAGEMENT_STATE_INVALID`, and one
        that fails the economics coherence check is refused with
        `ERR_ECONOMICS_CONFIG_INVALID`."

        Design: Corner/state_machines/second_submit_for_approval_returns_engagement_state_invalid
        """
        scenario = setup_planned_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2003", "address_line": "S-2003 Liquidation Row",
            },
        )
        submit_engagement(scenario["engagement"]["id"])
        response = api_client.submit_engagement_for_approval(
            scenario["engagement"]["id"], make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID.value, 409)
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["engagement_status"] == "PENDING_RETAILER_APPROVAL"
        assert engagement["version"] == 2


class TestInvalidTransitions:
    def test_closing_a_license_pending_store_reports_the_store_state_error(self):
        """The engagement gate is satisfied, so the store's own machine refuses.

        The PRD says: "The `LiquidationConsultant` closes a store from `SELLING` or
        from `SUSPENDED`; a store in any other status draws `ERR_STORE_STATE_INVALID`."

        Design: Corner/state_machines/close_selling_on_a_license_pending_store_returns_store_state_invalid
        """
        scenario = setup_approved_engagement(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2004", "address_line": "S-2004 Liquidation Row",
            },
        )
        assert scenario["store"]["store_status"] == "LICENSE_PENDING"
        response = api_client.close_selling(
            scenario["store"]["id"], make_consultant_headers()
        )
        error = validate_error(
            response, ApiErrorId.ERR_STORE_STATE_INVALID.value, 409
        )
        assert error["error_id"] != ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID.value
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "LICENSE_PENDING"
        assert store["selling_end_date"] is None
        assert store["version"] == 2
        assert read_engagement(scenario["engagement"]["id"])[
            "engagement_status"
        ] == "ACTIVE"

    def test_accepting_a_draft_worksheet_is_refused_and_writes_no_money(self):
        """The retailer has nothing to answer until the consultant proposes.

        The PRD says: "Proposing the worksheet is what computes the split. It is
        defined from `DRAFT` and from `DISPUTED`, both taking the worksheet to
        `PROPOSED`; any other status draws `ERR_SETTLEMENT_STATE_INVALID`."

        Design: Corner/state_machines/settlement_response_on_a_draft_worksheet_returns_settlement_state_invalid
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2010", "address_line": "S-2010 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2010"},
        )
        settlement = open_settlement(scenario["engagement"]["id"], "PROVISIONAL")
        response = api_client.respond_to_settlement(
            settlement["id"], {"response": "ACCEPT"}, make_controller_headers()
        )
        validate_error(response, ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value, 409)
        read_back = _read_settlement(settlement["id"])
        assert_settlement(read_back)
        assert read_back["settlement_status"] == "DRAFT"
        assert read_back["version"] == 1
        assert read_back["computed_at"] is None
        assert read_back["proposed_by_user_id"] is None
        # "A new worksheet opens at `settlement_status` of `DRAFT` with every
        # split figure unset" -- the refused ACCEPT must leave them unset, which
        # is null and not zero.
        for field in (
            "gross_recovery_cents", "liquidator_fee_cents",
            "retailer_proceeds_cents", "liquidator_proceeds_cents",
        ):
            assert read_back[field] is None, field


class TestTerminalStateLockdown:
    def test_a_second_revocation_is_refused_and_cannot_inflate_the_strikes(self):
        """REVOKED has no outgoing edge, and a refusal must not count as a strike.

        The PRD says: "A compliance officer revokes an `APPROVED` licence with a
        mandatory `revoked_reason`; a licence in any other status draws
        `ERR_LICENSE_STATE_INVALID`."

        Design: Corner/state_machines/revoked_license_is_terminal_so_a_second_revocation_is_refused
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2005", "address_line": "S-2005 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2005"},
        )
        license_id = scenario["license"]["id"]
        revoke_license(license_id, revoked_reason="signage violation")
        response = api_client.revoke_gob_license(
            license_id, {"revoked_reason": "signage violation"},
            make_compliance_headers(),
        )
        validate_error(response, ApiErrorId.ERR_LICENSE_STATE_INVALID.value, 409)
        license_row = _read_license(license_id)
        assert license_row["license_status"] == "REVOKED"
        assert license_row["version"] == 3
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["compliance_strike_count"] == 1
        assert engagement["compliance_posture"] == "RESTRICTED"
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "SUSPENDED"
        assert store["suspension_reason"] == "LICENSE_REVOKED"


class TestSideEffectExecution:
    def test_licence_approval_dates_the_sale_from_the_licence_period_start(self):
        """The store starts selling on 2026-09-20, not on the agreement's 2026-09-15.

        The PRD says: "An approval moves the licence `APPLIED → APPROVED` and, across
        the entity boundary, lifts a store waiting in `LICENSE_PENDING` into `SELLING`
        with its `selling_start_date` set to the licence's `period_start_date`; the
        store's `version` increments alongside the licence's."

        Design: Corner/state_machines/license_approval_moves_the_pending_store_to_selling_on_the_period_start_date
        """
        scenario = setup_approved_engagement(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2006", "address_line": "S-2006 Liquidation Row",
            },
        )
        license_row = apply_for_license(
            scenario["store"]["id"], license_number="NY-GOB-2006",
            period_start_date="2026-09-20", period_end_date="2026-10-19",
            advertising_claim_codes=["EVERYTHING_MUST_GO"],
        )
        decided = decide_license(license_row["id"])
        assert decided["license_status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "co-2"
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "SELLING"
        assert store["selling_start_date"] == "2026-09-20"
        assert store["version"] == 3
        assert read_engagement(scenario["engagement"]["id"])[
            "compliance_strike_count"
        ] == 0

    def test_the_sweep_is_the_only_route_to_an_expired_licence(self):
        """A period that ended 2026-10-14 expires only when the sweep observes it.

        The PRD says: "Every `APPROVED` licence of the engagement whose
        `period_end_date` falls strictly before the current logical clock date moves
        `APPROVED → EXPIRED`; each such expiry suspends its still-`SELLING` store with
        `suspension_reason` of `LICENSE_EXPIRED`, closes that store's `ACTIVE` stage
        with `closed_reason` of `LICENSE_LOST` and no escalation, and increments the
        engagement's `compliance_strike_count` by 1 with the posture re-derived."

        Design: Corner/state_machines/compliance_sweep_expires_the_lapsed_license_and_suspends_its_store
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2007", "address_line": "S-2007 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2007"},
        )
        pin_clock("2026-10-20T00:00:00Z")
        tally = run_compliance_sweep(scenario["engagement"]["id"])
        assert_compliance_sweep_tally(tally)
        assert tally["expired_license_count"] == 1
        assert tally["suspended_store_count"] == 1
        assert tally["closed_stage_count"] == 0
        assert tally["compliance_strike_count"] == 1
        assert tally["compliance_posture"] == "RESTRICTED"
        assert _read_license(scenario["license"]["id"])[
            "license_status"
        ] == "EXPIRED"
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "SUSPENDED"
        assert store["suspension_reason"] == "LICENSE_EXPIRED"

    def test_a_second_sweep_at_the_same_clock_finds_nothing_left_to_expire(self):
        """The sweep is a one-shot observation, not a repeatable strike generator.

        The PRD says: "The sweep answers with a tally rather than a resource:
        `expired_license_count`, `closed_stage_count`, `suspended_store_count`, and the
        engagement's resulting `compliance_strike_count` and `compliance_posture`."

        Design: Corner/state_machines/compliance_sweep_expires_the_lapsed_license_and_suspends_its_store
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2007", "address_line": "S-2007 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2007"},
        )
        pin_clock("2026-10-20T00:00:00Z")
        run_compliance_sweep(scenario["engagement"]["id"])
        second = run_compliance_sweep(scenario["engagement"]["id"])
        assert second["expired_license_count"] == 0
        assert second["compliance_strike_count"] == 1

    def test_a_discretionary_suspension_closes_the_stage_without_a_strike(self):
        """Only an actual licence loss moves the strike counter.

        The PRD says: "What it deliberately does not do is record a compliance strike:
        only an actual licence loss moves `compliance_strike_count`."

        Design: Corner/state_machines/manual_suspend_closes_the_active_stage_without_adding_a_compliance_strike
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={
                "store_code": "S-2009", "address_line": "S-2009 Liquidation Row",
            },
            license_overrides={"license_number": "NY-GOB-2009"},
        )
        store_id = scenario["store"]["id"]
        stage = add_markdown_stage(store_id, **FIRST_STAGE)
        activate_markdown_stage(stage["id"])
        before = read_store(store_id)
        assert before["planned_avg_discount_pct"] == pytest.approx(
            0.2000, abs=0.00001
        )
        assert before["projected_gross_recovery_cents"] == 3400000
        assert before["projected_recovery_ratio"] == pytest.approx(
            1.7000, abs=0.00001
        )
        suspended = validate_success(
            api_client.suspend_store(store_id, make_compliance_headers())
        )
        assert suspended["store_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "COMPLIANCE_HOLD"
        closed = _read_stage(stage["id"])
        assert closed["stage_status"] == "CLOSED"
        assert closed["closed_reason"] == "LICENSE_LOST"
        after = read_store(store_id)
        assert after["planned_avg_discount_pct"] == pytest.approx(
            0.0000, abs=0.00001
        )
        assert after["projected_gross_recovery_cents"] == 4250000
        assert after["projected_recovery_ratio"] == pytest.approx(
            2.1250, abs=0.00001
        )
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["compliance_strike_count"] == 0
        assert engagement["compliance_posture"] == "OPEN"


class TestPreconditionEnforcement:
    def test_wind_down_is_refused_while_a_single_store_is_still_selling(self):
        """The gate is universally quantified: one open store blocks the whole
        engagement.

        The PRD says: "The consultant moves the engagement `ACTIVE → WIND_DOWN`, but
        only once every store of the engagement has reached `CLOSED` or `SURRENDERED`;
        while any store is still `PLANNED`, `LICENSE_PENDING`, `SELLING`, or
        `SUSPENDED` the request is refused with `ERR_STORES_NOT_CLOSED`."

        Design: Corner/state_machines/wind_down_rejects_while_one_store_is_open_then_succeeds_once_both_are_closed
        """
        scenario = _two_licensed_stores_one_of_them_closed()
        validate_error(
            scenario["refusal"], ApiErrorId.ERR_STORES_NOT_CLOSED.value, 409
        )
        assert read_store(scenario["store_a"]["id"])["store_status"] == "CLOSED"
        assert read_store(scenario["store_b"]["id"])["store_status"] == "SELLING"
        assert read_engagement(scenario["engagement"]["id"])[
            "engagement_status"
        ] == "ACTIVE"

    def test_the_identical_wind_down_succeeds_once_the_second_store_closes(self):
        """Both stores date their close from the logical clock.

        The PRD says: "Hop one takes the store to `CLOSED`, sets `selling_end_date` to
        the current logical-clock date, and freezes `realized_sell_through_pct`."

        Design: Corner/state_machines/wind_down_rejects_while_one_store_is_open_then_succeeds_once_both_are_closed
        """
        scenario = _two_licensed_stores_one_of_them_closed()
        close_store(scenario["store_b"]["id"])
        wound_down = validate_success(
            api_client.wind_down_engagement(
                scenario["engagement"]["id"], make_consultant_headers()
            )
        )
        assert wound_down["engagement_status"] == "WIND_DOWN"
        for key in ("store_a", "store_b"):
            assert read_store(scenario[key]["id"])[
                "selling_end_date"
            ] == "2026-09-15"


def _two_licensed_stores_one_of_them_closed():
    """Two NY stores selling under their own licences, with the first one shut.

    The engagement therefore satisfies the wind-down gate for one store and fails it
    for the other, which is the whole point of the pair.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement()
    store_a = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-2008A", address_line="S-2008A Liquidation Row",
    )
    add_inventory_lot(store_a["id"])
    store_b = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-2008B", address_line="S-2008B Liquidation Row",
    )
    add_inventory_lot(store_b["id"])
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    for store, number in ((store_a, "NY-GOB-2008A"), (store_b, "NY-GOB-2008B")):
        license_row = apply_for_license(store["id"], license_number=number)
        decide_license(license_row["id"])
    close_store(store_a["id"])
    return {
        "engagement": engagement,
        "store_a": store_a,
        "store_b": store_b,
        "refusal": api_client.wind_down_engagement(
            engagement["id"], make_consultant_headers()
        ),
    }
