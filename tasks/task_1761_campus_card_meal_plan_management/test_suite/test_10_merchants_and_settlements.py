"""The off-campus merchant program: onboarding, transactions, the settlement
sweep, carryover, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_merchant,
    create_active_merchant,
    create_holder,
    create_merchant,
    create_settlement_draft,
    create_term,
    file_dispute,
    get_success_data,
    make_bursar_headers,
    make_cardholder_headers,
    make_merchantuser_headers,
    post_merchant_transaction,
    resolve_dispute,
    set_clock,
    setup_funded_campus_cash,
    setup_merchant_with_transactions,
    setup_submitted_settlement,
    submit_settlement_as_merchant,
    validate_error,
    validate_paginated,
    validate_success,
)

BURSAR = TEST_USERS["bursar_headers"]
POS = TEST_USERS["pos_headers"]


class TestMerchantTransactions:
    def test_transaction_against_inactive_merchant_rejected(self, api):
        """PRD §3.5: "A merchant posting additionally requires the merchant to be
        `ACTIVE` (`ERR_MERCHANT_NOT_ACTIVE`)."
        PRD §3.9: "A suspended merchant accepts no new transactions."

        Design: Corner/validations/transaction_against_inactive_merchant_rejected
        """
        set_clock("2026-08-25T09:00:00Z")
        merchant = create_merchant(merchant_code="M-INA", commission_bps=100,
                                   category="OTHER")
        holder, card, account = setup_funded_campus_cash(
            amount_cents=3000, university_id="U92011", full_name="Uma Ina",
            email="uma2@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")

        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 500, "idempotency_key": "uma2-t",
             "merchant_id": merchant["id"]},
            make_merchantuser_headers(merchant["id"]))
        validate_error(resp, ApiErrorId.ERR_MERCHANT_NOT_ACTIVE)
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 3000

    def test_merchantuser_cannot_post_for_other_merchant(self, api):
        """PRD §3.5: "a `MerchantUser` for an off-campus purchase (who must pass a
        `merchant_id` equal to their own merchant id — anything else is
        `ERR_NOT_RESOURCE_OWNER`)"

        Design: Corner/rbac/merchantuser_cannot_post_for_other_merchant
        """
        set_clock("2026-09-05T12:00:00Z")
        own = create_active_merchant(merchant_code="M-OWN", commission_bps=100)
        other = create_active_merchant(merchant_code="M-OTH", commission_bps=100)
        holder, card, account = setup_funded_campus_cash(
            amount_cents=3000, university_id="U94006", full_name="Uli Merch",
            email="uli@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")

        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 400, "idempotency_key": "uli-t",
             "merchant_id": other["id"]}, make_merchantuser_headers(own["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        transactions, _ = validate_paginated(
            api.list_transactions(BURSAR, {"card_id": card["id"]}))
        assert transactions == []

    def test_pos_terminal_cannot_supply_merchant_id(self, api):
        """PRD §3.5: "posted either by a `PointOfSale` terminal for on-campus
        dining (which must omit `merchant_id`)"
        PRD §2.10: "**Body well-formedness** — required fields present, types
        correct, enum values in range, `amount_cents` positive (exactly zero for
        a meal swipe), end after start, dates parseable, and `rejection_reason` or
        `denial_reason` present where the action requires one, else
        `ERR_VALIDATION` (400)."

        Design: Corner/rbac/pos_terminal_cannot_supply_merchant_id
        """
        set_clock("2026-08-25T09:00:00Z")
        merchant = create_active_merchant(merchant_code="M-POS",
                                          commission_bps=100)
        holder, card, account = setup_funded_campus_cash(
            amount_cents=3000, university_id="U94007", full_name="Vic Pos",
            email="vicp@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")

        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 400, "idempotency_key": "vicp-t",
             "merchant_id": merchant["id"]}, POS)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_transaction_list_filtered_by_merchant(self, api):
        """PRD §3.5: "Transactions can be listed with filters on `card_id`,
        `account_id`, `enrollment_id`, `merchant_id`, `settled_in_settlement_id`,
        and `status`; a `CardHolder` sees only their own transactions and a
        `MerchantUser` only their own merchant's."
        PRD §2.1: "ownership checks on any resource that references a `Merchant`
        compare the resource's merchant linkage field to `X-User-ID`, and list
        filters naming another merchant's id are equally rejected with
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/endpoints/transaction_list_filtered_by_merchant
        """
        set_clock("2026-09-05T12:00:00Z")
        mx = create_active_merchant(merchant_code="M-FX", commission_bps=100)
        my = create_active_merchant(merchant_code="M-FY", commission_bps=100)
        holder, card, account = setup_funded_campus_cash(
            amount_cents=5000, university_id="U93004", full_name="Fi Filter",
            email="fi@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")
        post_merchant_transaction(card["id"], mx["id"], 400, key="fi-x")
        post_merchant_transaction(card["id"], my["id"], 400, key="fi-y")

        filtered, meta = validate_paginated(
            api.list_transactions(BURSAR, {"merchant_id": mx["id"]}))
        assert len(filtered) == 1
        assert filtered[0]["merchant_id"] == mx["id"]

        other = api.list_transactions(make_merchantuser_headers(mx["id"]),
                                      {"merchant_id": my["id"]})
        validate_error(other, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestSettlementCreation:
    def test_settlement_period_outside_term_rejected(self, api):
        """PRD §3.9: "both ends must lie within the term's
        `start_date`-to-`end_date` span (`ERR_PERIOD_OUTSIDE_TERM`)"

        Design: Corner/validations/settlement_period_outside_term_rejected
        """
        set_clock("2026-10-05T09:00:00Z")
        term = create_term(term_code="T-POT")
        merchant = create_active_merchant(merchant_code="M-POT",
                                          commission_bps=100, category="OTHER")
        resp = api.create_settlement(
            merchant["id"],
            {"term_id": term["id"], "period_start": "2026-12-01T00:00:00Z",
             "period_end": "2026-12-20T23:59:59Z"},
            make_merchantuser_headers(merchant["id"]))
        validate_error(resp, ApiErrorId.ERR_PERIOD_OUTSIDE_TERM)

    def test_settlement_touching_day_conflicts(self, api):
        """PRD §3.9: "the period must not share any day with an existing
        non-`REJECTED` settlement of the same merchant — because both intervals
        are closed, touching endpoints conflict and are rejected with
        `ERR_SETTLEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/settlement_closed_closed_touch_overlap
        """
        merchant_id, term_id = _setup_existing_september_settlement(api)
        touching = api.create_settlement(
            merchant_id,
            {"term_id": term_id, "period_start": "2026-09-30T00:00:00Z",
             "period_end": "2026-10-31T23:59:59Z"},
            make_merchantuser_headers(merchant_id))
        validate_error(touching, ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP)

    def test_settlement_starting_next_day_after_period_allowed(self, api):
        """PRD §3.9: "the period must not share any day with an existing
        non-`REJECTED` settlement of the same merchant — because both intervals
        are closed, touching endpoints conflict and are rejected with
        `ERR_SETTLEMENT_PERIOD_OVERLAP`." — a period that shares no day with the
        existing one (2026-10-01 onward) conflicts with nothing.

        Design: Difficulty/resource_temporal_overlap/settlement_closed_closed_touch_overlap
        """
        merchant_id, term_id = _setup_existing_september_settlement(api)
        ok = api.create_settlement(
            merchant_id,
            {"term_id": term_id, "period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-10-31T23:59:59Z"},
            make_merchantuser_headers(merchant_id))
        created = validate_success(ok, 201)
        assert created["status"] == "DRAFT"


class TestSettlementSweep:
    def test_commission_modes_diverge_per_transaction(self, api):
        """PRD §3.9: "under `PER_TRANSACTION`, each transaction's commission — its
        amount multiplied by `commission_bps` and divided by 10000 — is rounded
        half-up to whole cents **first**, and those rounded values are then summed"

        Design: Difficulty/dual_variant_calc/settlement_commission_mode_variants_diverge
        """
        ids = _setup_two_merchants_with_transactions(api)
        sa = _create_and_submit(api, ids["ma_id"], ids["term_id"])
        # PER_TRANSACTION: 3 x round_half_up(999*275/10000) = 3 x 27 = 81
        assert sa["gross_cents"] == 2997
        assert sa["transaction_count"] == 3
        assert sa["commission_cents"] == 81
        assert sa["net_cents"] == 2916

    def test_commission_modes_diverge_aggregate(self, api):
        """PRD §3.9: "under `AGGREGATE`, the amounts are summed first and the
        commission is computed on the gross and rounded half-up exactly once. The
        two modes disagree whenever per-transaction fractions would sum across a
        half-cent boundary."

        Design: Difficulty/dual_variant_calc/settlement_commission_mode_variants_diverge
        """
        ids = _setup_two_merchants_with_transactions(api)
        sa = _create_and_submit(api, ids["ma_id"], ids["term_id"])
        sb = _create_and_submit(api, ids["mb_id"], ids["term_id"])
        # AGGREGATE: round_half_up(2997*275/10000) = 82
        assert sb["gross_cents"] == 2997
        assert sb["commission_cents"] == 82
        assert sb["net_cents"] == 2915
        assert sb["commission_cents"] != sa["commission_cents"]

    def test_settlement_per_transaction_rounding_order(self, api):
        """PRD §3.9: "under `PER_TRANSACTION`, each transaction's commission — its
        amount multiplied by `commission_bps` and divided by 10000 — is rounded
        half-up to whole cents **first**, and those rounded values are then summed"

        Design: Difficulty/combinatorial_formula/settlement_per_transaction_rounding_order
        """
        (term, merchant, holder, card, account, txs) = \
            setup_merchant_with_transactions([199, 199, 199])
        settlement = create_settlement_draft(merchant["id"], term["id"])
        submitted = submit_settlement_as_merchant(settlement["id"],
                                                  merchant["id"])
        # Round-first: 3 x round_half_up(199*275/10000) = 3 x 5 = 15.
        # The forbidden sum-then-round order would yield 16.
        assert submitted["commission_cents"] == 15

    def test_settlement_per_transaction_rounding_gross_and_net(self, api):
        """PRD §3.9: "`gross_cents` is the sum of the swept amounts;
        `transaction_count` is their number; `net_cents` is `gross_cents` minus
        `commission_cents`."

        Design: Difficulty/combinatorial_formula/settlement_per_transaction_rounding_order
        """
        (term, merchant, holder, card, account, txs) = \
            setup_merchant_with_transactions([199, 199, 199])
        settlement = create_settlement_draft(merchant["id"], term["id"])
        submitted = submit_settlement_as_merchant(settlement["id"],
                                                  merchant["id"])
        assert submitted["gross_cents"] == 597
        assert submitted["transaction_count"] == 3
        assert submitted["net_cents"] == 582


class TestSettlementRejectionCycle:
    def test_settlement_rejection_resubmission_cycle(self, api):
        """PRD §3.9: "Rejection requires a `rejection_reason` (`ERR_VALIDATION`
        otherwise) and unlinks every swept transaction — their
        `settled_in_settlement_id` returns to null — making them eligible for a
        future sweep."

        Design: Difficulty/non_linear_state_machine/settlement_rejection_resubmission_cycle
        """
        ids = _setup_cycle_scenario(api)
        rejected = validate_success(
            api.reject_settlement(ids["s_id"], {"rejection_reason":
                                                "missing receipt"},
                                  make_bursar_headers("bursar-1")), 200)
        assert rejected["status"] == "REJECTED"
        tx_now = get_success_data(api.get_transaction(ids["tx1_id"], BURSAR))
        assert tx_now["settled_in_settlement_id"] is None
        assert ids["s_gross1"] == 999
        assert ids["s_comm1"] == 27

    def test_settlement_resubmission_reruns_fresh_sweep(self, api):
        """PRD §3.9: "Resubmission after rejection runs a fresh sweep that
        replaces the prior computed values, clears the `rejection_reason`, and
        updates `submitted_by`."

        Design: Difficulty/non_linear_state_machine/settlement_rejection_resubmission_cycle
        """
        ids = _setup_cycle_scenario(api)
        validate_success(
            api.reject_settlement(ids["s_id"], {"rejection_reason":
                                                "missing receipt"},
                                  make_bursar_headers("bursar-1")), 200)
        set_clock("2026-09-10T12:00:00Z")
        post_merchant_transaction(ids["card_id"], ids["m_id"], 500, key="cyc-2")

        resubmitted = submit_settlement_as_merchant(ids["s_id"], ids["m_id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["gross_cents"] == 1499      # 999 + 500
        assert resubmitted["commission_cents"] == 41   # 27 + round(500*275/10000)=14
        assert resubmitted["net_cents"] == 1458
        assert resubmitted["transaction_count"] == 2


class TestDisputeCarryover:
    def test_dispute_carryover_exclusion_from_first_sweep(self, api):
        """PRD §3.9: "Transactions `UNDER_DISPUTE` at submit time are excluded."
        PRD §3.9: "The sweep set is the merchant's card transactions whose
        `created_at` falls within the closed-closed period (compared at timestamp
        precision), whose `status` is `POSTED`, and whose
        `settled_in_settlement_id` is still null"

        Design: Difficulty/compensating_invariant/dispute_carryover_gross_conservation
        """
        ids = _setup_carryover_scenario(api)
        assert ids["s1_gross"] == 1998       # disputed 999 excluded
        assert ids["s1_count"] == 2

    def test_dispute_carryover_gross_conservation(self, api):
        """PRD §3.9: "A transaction excluded from a sweep because it was
        `UNDER_DISPUTE` becomes sweep-eligible again when its dispute resolves for
        the merchant or is withdrawn — restored to its `pre_dispute_status` — and
        it then enters the merchant's **next** submitted settlement as a carried
        transaction, overriding the period filter, with
        `carried_from_settlement_id` recording the settlement that excluded it."

        Design: Difficulty/compensating_invariant/dispute_carryover_gross_conservation
        """
        ids = _setup_carryover_scenario(api)
        resolve_dispute(ids["d_id"], "FOR_MERCHANT", "service rendered",
                        analyst="fraud-1")
        tx3_now = get_success_data(api.get_transaction(ids["tx3_id"], BURSAR))
        assert tx3_now["status"] == "POSTED"

        set_clock("2026-10-10T12:00:00Z")
        post_merchant_transaction(ids["card_id"], ids["m_id"], 500, key="cry-4")
        s2 = create_settlement_draft(ids["m_id"], ids["term_id"],
                                     period_start="2026-10-01T00:00:00Z",
                                     period_end="2026-10-31T23:59:59Z")
        s2_submitted = submit_settlement_as_merchant(s2["id"], ids["m_id"])
        assert s2_submitted["gross_cents"] == 1499      # carried 999 + new 500
        assert s2_submitted["commission_cents"] == 41   # 27 + 14
        assert s2_submitted["transaction_count"] == 2
        assert s2_submitted["carried_from_settlement_id"] == ids["s1_id"]
        # Invariant: 1998 + 1499 == 3497 == 999 x 3 + 500.
        assert ids["s1_gross"] + s2_submitted["gross_cents"] == 3497


class TestSettlementAdjudication:
    def test_merchantuser_cannot_approve_settlement(self, api):
        """PRD §4: settlement approval's authorized role list contains only
        BursarOffice. PRD §2.1: "If the headers are well-formed but the named role
        is not in the calling endpoint's authorized role list, the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/merchantuser_cannot_approve_settlement
        """
        (term, merchant, holder, card, account, txs, submitted) = \
            setup_submitted_settlement(amounts=(999,), commission_bps=100)
        resp = api.approve_settlement(
            submitted["id"], make_merchantuser_headers(merchant["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        still = get_success_data(api.get_settlement(submitted["id"], BURSAR))
        assert still["status"] == "SUBMITTED"

    def test_settlement_sod_submitter_approver_payer_chain(self, api):
        """PRD §3.9: "Approval requires the approver's `X-User-ID` to differ from
        the `submitted_by` (`ERR_SOD_APPROVER_IS_SUBMITTER`), records
        `approved_by`, and moves every linked transaction to `SETTLED`."
        PRD §3.9: "Payment of an `APPROVED` settlement requires the payer to
        differ from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`) and records
        `paid_by`, completing the cycle at `PAID`."

        Design: Corner/rbac/settlement_sod_submitter_approver_payer_chain
        """
        set_clock("2026-10-05T09:00:00Z")
        term = create_term(term_code="T-SOD")
        merchant = create_active_merchant(merchant_code="M-SOD",
                                          commission_bps=100, category="OTHER")
        settlement = create_settlement_draft(
            merchant["id"], term["id"],
            headers=make_bursar_headers("bursar-9"))
        get_success_data(api.submit_settlement(settlement["id"],
                                               make_bursar_headers("bursar-9")))

        bad_approve = api.approve_settlement(settlement["id"],
                                             make_bursar_headers("bursar-9"))
        validate_error(bad_approve, ApiErrorId.ERR_SOD_APPROVER_IS_SUBMITTER)

        approved = validate_success(
            api.approve_settlement(settlement["id"],
                                   make_bursar_headers("bursar-8")), 200)
        assert approved["status"] == "APPROVED"

        bad_pay = api.pay_settlement(settlement["id"],
                                     make_bursar_headers("bursar-8"))
        validate_error(bad_pay, ApiErrorId.ERR_SOD_PAYER_IS_APPROVER)

        paid = validate_success(api.pay_settlement(
            settlement["id"], make_bursar_headers("bursar-7")), 200)
        assert paid["status"] == "PAID"

    def test_settled_locked_transaction_not_disputable(self, api):
        """PRD §3.6: "only against a transaction that is not `REVERSED` and not
        locked into a settlement in `APPROVED` or `PAID` (`ERR_TX_NOT_DISPUTABLE`)"
        PRD §3.9: approval "moves every linked transaction to `SETTLED`."

        Design: Corner/validations/settled_locked_transaction_not_disputable
        """
        (term, merchant, holder, card, account, txs, submitted) = \
            setup_submitted_settlement(amounts=(999,))
        validate_success(api.approve_settlement(
            submitted["id"], make_bursar_headers("bursar-1")), 200)
        tx = txs[0]
        tx_now = get_success_data(api.get_transaction(tx["id"], BURSAR))
        assert tx_now["status"] == "SETTLED"

        resp = api.create_dispute(tx["id"], {"reason_code": "UNAUTHORIZED_USE"},
                                  make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_TX_NOT_DISPUTABLE)
        still = get_success_data(api.get_transaction(tx["id"], BURSAR))
        assert still["status"] == "SETTLED"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _create_and_submit(api, merchant_id, term_id):
    settlement = create_settlement_draft(merchant_id, term_id)
    return submit_settlement_as_merchant(settlement["id"], merchant_id)


def _setup_two_merchants_with_transactions(api):
    """Two ACTIVE merchants (PER_TRANSACTION and AGGREGATE, 275 bps); a funded
    verified card; three 999-cent transactions at each merchant."""
    set_clock("2026-09-05T12:00:00Z")
    term = create_term(term_code="SETT26")
    ma = create_active_merchant(merchant_code="M-A",
                                commission_mode="PER_TRANSACTION")
    mb = create_active_merchant(merchant_code="M-B", commission_mode="AGGREGATE")
    holder, card, account = setup_funded_campus_cash(
        amount_cents=10000, university_id="U2001", full_name="Bob Resident",
        email="bob@x.edu", holder_type="STUDENT_RESIDENT",
        housing_status="ON_CAMPUS")
    for i in range(1, 4):
        post_merchant_transaction(card["id"], ma["id"], 999, key=f"t-a{i}")
        post_merchant_transaction(card["id"], mb["id"], 999, key=f"t-b{i}")
    return {"term_id": term["id"], "ma_id": ma["id"], "mb_id": mb["id"]}


def _setup_existing_september_settlement(api):
    """ACTIVE merchant M-OVL with a settlement over
    [2026-09-01T00:00:00Z, 2026-09-30T23:59:59Z] (DRAFT occupies the span)."""
    set_clock("2026-10-05T09:00:00Z")
    term = create_term(term_code="SETT26D")
    merchant = create_active_merchant(merchant_code="M-OVL", category="GROCERY")
    create_settlement_draft(merchant["id"], term["id"])
    return merchant["id"], term["id"]


def _setup_cycle_scenario(api):
    """One 999-cent merchant transaction swept into a SUBMITTED settlement."""
    set_clock("2026-09-05T12:00:00Z")
    term = create_term(term_code="SETT26C")
    merchant = create_active_merchant(merchant_code="M-CYC", category="BOOKSTORE")
    holder, card, account = setup_funded_campus_cash(
        amount_cents=10000, university_id="U4002", full_name="Gus Commuter",
        email="gus@x.edu", holder_type="STUDENT_COMMUTER",
        housing_status="COMMUTER")
    tx = post_merchant_transaction(card["id"], merchant["id"], 999, key="cyc-1")
    settlement = create_settlement_draft(merchant["id"], term["id"])
    submitted = submit_settlement_as_merchant(settlement["id"], merchant["id"])
    return {"term_id": term["id"], "m_id": merchant["id"], "card_id": card["id"],
            "tx1_id": tx["id"], "s_id": settlement["id"],
            "s_gross1": submitted["gross_cents"],
            "s_comm1": submitted["commission_cents"]}


def _setup_carryover_scenario(api):
    """Three 999-cent merchant transactions; tx3 disputed; the September
    settlement submitted with tx3 excluded."""
    set_clock("2026-09-05T12:00:00Z")
    term = create_term(term_code="SETT26E")
    merchant = create_active_merchant(merchant_code="M-CRY")
    holder, card, account = setup_funded_campus_cash(
        amount_cents=10000, university_id="U10002", full_name="Tess Resident",
        email="tess@x.edu", holder_type="STUDENT_RESIDENT",
        housing_status="ON_CAMPUS")
    post_merchant_transaction(card["id"], merchant["id"], 999, key="cry-1")
    post_merchant_transaction(card["id"], merchant["id"], 999, key="cry-2")
    tx3 = post_merchant_transaction(card["id"], merchant["id"], 999, key="cry-3")
    dispute = file_dispute(tx3["id"], holder["id"], "SERVICE_NOT_RECEIVED")
    s1 = create_settlement_draft(merchant["id"], term["id"])
    s1_submitted = submit_settlement_as_merchant(s1["id"], merchant["id"])
    return {"term_id": term["id"], "m_id": merchant["id"], "card_id": card["id"],
            "tx3_id": tx3["id"], "d_id": dispute["id"], "s1_id": s1["id"],
            "s1_gross": s1_submitted["gross_cents"],
            "s1_count": s1_submitted["transaction_count"]}
