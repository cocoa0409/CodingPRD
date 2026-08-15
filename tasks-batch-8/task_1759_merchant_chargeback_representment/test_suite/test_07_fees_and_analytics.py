"""Fee pass-through money movement, segregation of duties, partial wins, and
win-rate analytics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assemble_packet,
    create_fee_assessment_payload,
    create_merchant,
    create_rule,
    get_merchant,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    ingest_sales_batch,
    list_fees,
    make_finance_ops_headers,
    make_merchant_user_headers,
    notify,
    set_clock,
    setup_submitted_case,
    submit_packet,
    upload_evidence,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]


def _setup_merchant_with_clearing(api, sales=10, amount=10000):
    """Merchant with `sales` x `amount` clearing at reserve rate 0."""
    m = create_merchant(api, legal_name="Fee M", reserve_rate_bps=0)
    if sales > 1:
        ingest_sales_batch(api, m["id"], "S", sales, amount, "2026-07-10T00:00:00Z")
    else:
        ingest_sale(api, m["id"], "T-1", amount, "2026-07-10T00:00:00Z")
    return m


def test_fee_settle_debits_clearing(api):
    """PRD §3.8: "Settlement collects the fee from the merchant's clearing:
    `clearing_balance_cents` decreases by the fee's `amount_cents`,
    `settled_at` is stamped, and the fee becomes `SETTLED`."

    Design: Corner/rbac/fee_settle_debits_clearing
    """
    m = _setup_merchant_with_clearing(api)  # 100000 clearing
    fee = get_success_data(
        api.create_fee_assessment(
            create_fee_assessment_payload(merchant_id=m["id"], amount_cents=7500),
            make_finance_ops_headers("fin-1"),
        )
    )

    settled = validate_success(
        api.settle_fee_assessment(fee["id"], make_finance_ops_headers("fin-1"))
    )
    assert settled["status"] == "SETTLED"
    assert settled.get("settled_at") is not None
    # 100000 - 7500: the settlement stands as a clearing debit.
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 92500


def test_fee_waive_after_settle_terminal_rejected(api):
    """PRD §3.8: "Two terminal resolutions exist, both `FinanceOps` actions and
    both requiring the fee to still be `ASSESSED` — acting on a fee in any
    other state fails with `ERR_INVALID_FEE_STATE`."

    Design: Corner/state_machines/fee_waive_terminal_rejected
    """
    m = _setup_merchant_with_clearing(api)
    fee = get_success_data(
        api.create_fee_assessment(
            create_fee_assessment_payload(merchant_id=m["id"], amount_cents=7500),
            make_finance_ops_headers("fin-1"),
        )
    )
    get_success_data(api.settle_fee_assessment(fee["id"], make_finance_ops_headers("fin-1")))

    # A different waver avoids the segregation question entirely; the state
    # gate is what answers.
    resp = api.waive_fee_assessment(fee["id"], make_finance_ops_headers("fin-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_FEE_STATE)
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 92500


def test_segregation_of_duties_fee_waive(api):
    """PRD §3.8: "whenever the fee's `assessed_by_user_id` is a real user
    rather than the literal `system`, the waiving user's `X-User-ID` must
    differ from it — a `FinanceOps` operator cannot waive a fee they assessed
    themselves, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). System-assessed fees are exempt from the segregation check and
    may be waived by any `FinanceOps` operator."

    Design: Corner/rbac/segregation_of_duties_fee_waive
    """
    create_rule(api)
    m = create_merchant(api, legal_name="SoD M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-SD1", 5000)

    manual_fee = get_success_data(
        api.create_fee_assessment(
            create_fee_assessment_payload(merchant_id=m["id"], amount_cents=50000),
            make_finance_ops_headers("fin-1"),
        )
    )
    assert manual_fee["assessed_by_user_id"] == "fin-1"

    self_waive = api.waive_fee_assessment(
        manual_fee["id"], make_finance_ops_headers("fin-1")
    )
    validate_error(self_waive, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    other_waive = api.waive_fee_assessment(
        manual_fee["id"], make_finance_ops_headers("fin-2")
    )
    waived = validate_success(other_waive)
    assert waived["status"] == "WAIVED"
    assert waived["waived_by_user_id"] == "fin-2"
    assert waived.get("waived_at") is not None

    # The system-assessed CHARGEBACK_FEE is exempt from the segregation check.
    sys_fees = list_fees(api, chargeback_id=cb["id"])
    assert len(sys_fees) == 1
    assert sys_fees[0]["assessed_by_user_id"] == "system"
    sys_waive = api.waive_fee_assessment(
        sys_fees[0]["id"], make_finance_ops_headers("fin-1")
    )
    assert validate_success(sys_waive)["status"] == "WAIVED"


def test_partial_win_requires_amount_and_recredits_partial(api):
    """PRD §3.7: "An `outcome` of `PARTIAL_WON` requires a `won_amount_cents`
    strictly greater than zero and strictly less than the chargeback's
    `amount_cents` — a missing or out-of-range value fails with
    `ERR_INVALID_REQUEST` — records that amount, and stamps `decided_at`."
    PRD §3.7: "`recredited_cents` records the returned amount — the full
    `amount_cents` on a `WON`, the recorded `won_amount_cents` on a
    `PARTIAL_WON` — and the merchant's `clearing_balance_cents` increases by
    `recredited_cents` as the re-credit lands."

    Design: Corner/calculations/partial_win_recredit_and_missing_amount_rejected
    """
    bundle = setup_submitted_case(
        api,
        received_at="2026-07-15T00:00:00Z",
        merchant_overrides={"reserve_rate_bps": 0},
    )
    rep_id = bundle["representment"]["id"]
    cb_id = bundle["chargeback"]["id"]
    m_id = bundle["merchant"]["id"]

    missing = api.post_network_outcome(rep_id, {"outcome": "PARTIAL_WON"}, OPS)
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    decided = validate_success(
        api.post_network_outcome(
            rep_id, {"outcome": "PARTIAL_WON", "won_amount_cents": 6000}, OPS
        )
    )
    assert decided["status"] == "PARTIAL_WON"
    assert decided["won_amount_cents"] == 6000
    assert decided.get("decided_at") is not None

    cb = get_success_data(api.get_chargeback(cb_id, OPS))
    assert cb["case_status"] == "DECIDED_WON"
    assert cb["recredited_cents"] == 6000
    # Sale +10000, receipt debit -10000, partial re-credit +6000.
    assert get_merchant(api, m_id)["clearing_balance_cents"] == 6000


def _setup_win_rate_cases(api):
    """Four cases: WON, PARTIAL_WON 6000/10000, LOST, and one ASSEMBLED packet
    never submitted (excluded from the decided set)."""
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="WinRate M", reserve_rate_bps=0)
    refs = []
    for i in (1, 2, 3, 4):
        ingest_sale(api, m["id"], f"T-{i}", 10000, "2026-07-10T00:00:00Z")
        refs.append(f"T-{i}")
    set_clock(api, "2026-07-15T00:00:00Z")
    reps = {}
    for i, ref in enumerate(refs, start=1):
        cb = ingest_chargeback(api, m["id"], ref, f"NC-WR{i}", 10000)
        notify(api, cb["id"])
        ev = upload_evidence(api, cb["id"], m["id"], "RECEIPT", f"s3://ev/{i}.pdf")
        reps[i] = (cb, assemble_packet(api, cb["id"], m["id"], [ev["id"]]))
    headers = make_merchant_user_headers(m["id"])
    for i in (1, 2, 3):
        submit_packet(api, reps[i][1]["id"], m["id"])
    return m, reps


def test_win_rate_partial_weighting_and_filter(api):
    """PRD §3.9: "It computes over decided representments only — those in
    `WON`, `PARTIAL_WON`, or `LOST`, joined to their chargebacks and filtered
    by the optional `merchant_id`, `reason_code`, and `network` parameters,
    while `ASSEMBLED`, `SUBMITTED`, `RETURNED_FOR_CURE`, and `SUPERSEDED`
    packets are excluded". "The win rate counts a partial win as half a win: it
    is ten thousand times the sum of full wins plus half the partial wins,
    divided by the number of decided representments, rounded half-up to an
    integer basis point."

    Design: Corner/calculations/win_rate_partial_weighting_and_filter
    """
    m, reps = _setup_win_rate_cases(api)
    get_success_data(api.post_network_outcome(reps[1][1]["id"], {"outcome": "WON"}, OPS))
    get_success_data(
        api.post_network_outcome(
            reps[2][1]["id"], {"outcome": "PARTIAL_WON", "won_amount_cents": 6000}, OPS
        )
    )
    get_success_data(api.post_network_outcome(reps[3][1]["id"], {"outcome": "LOST"}, OPS))
    # reps[4] stays ASSEMBLED — never decided, hence excluded.

    data = validate_success(api.get_win_rate(OPS, params={"merchant_id": m["id"]}))
    assert data["decided_count"] == 3
    assert data["won_count"] == 1
    assert data["partial_win_count"] == 1
    assert data["lost_count"] == 1
    # round_half_up(10000 x (1 + 0.5) / 3) = 5000.
    assert data["win_rate_bps"] == 5000

    filtered = validate_success(
        api.get_win_rate(OPS, params={"merchant_id": m["id"], "reason_code": "10.4"})
    )
    assert filtered["win_rate_bps"] == 5000


def test_win_rate_empty_decided_set_null(api):
    """PRD §3.9: "When the filtered set contains no decided representments,
    `win_rate_bps` is null."

    Design: Corner/calculations/win_rate_empty_decided_set_null
    """
    m = create_merchant(api, legal_name="NoWR M", reserve_rate_bps=0)
    data = validate_success(
        api.get_win_rate(TEST_USERS["risk_officer_headers"], params={"merchant_id": m["id"]})
    )
    assert data["decided_count"] == 0
    assert data["win_rate_bps"] is None
