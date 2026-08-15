"""Fund establishment rules, gift lifecycle, and donor total compensation."""
from test_helpers import (
    ApiErrorId,
    activate_fund,
    api_client,
    assert_fund,
    assert_gift,
    create_donor,
    create_fund,
    create_gift,
    create_pool,
    finalize_open_quarter,
    get_success_data,
    make_board_member_headers,
    receive_gift,
    set_target_allocations,
    setup_zero_manager_pool,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_term_fund_requires_term_end_and_other_classes_forbid_it(api):
    """PRD §3.1: 'a term endowment must carry a `term_end_quarter_index` of at least
    1, while the other two classes must leave it null, and a malformed combination is
    rejected with `ERR_INVALID_REQUEST`.'

    Design: Corner/entities/term_fund_requires_term_end_and_other_classes_forbid_it
    """
    pool = create_pool(pool_name="Pool TC", inception_fiscal_year=2026)

    res1 = api.create_fund(
        {
            "pool_id": pool["id"],
            "fund_code": "FT1",
            "fund_name": "Bad Term",
            "endowment_class": "TERM_ENDOWMENT",
            "purpose_restriction": "UNRESTRICTED",
        },
        TEST_USERS["dev_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST, 400)

    res2 = api.create_fund(
        {
            "pool_id": pool["id"],
            "fund_code": "FT2",
            "fund_name": "Bad True",
            "endowment_class": "TRUE_ENDOWMENT",
            "term_end_quarter_index": 8,
            "purpose_restriction": "UNRESTRICTED",
        },
        TEST_USERS["dev_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST, 400)

    ok = validate_success(api.create_fund(
        {
            "pool_id": pool["id"],
            "fund_code": "FT3",
            "fund_name": "Good Term",
            "endowment_class": "TERM_ENDOWMENT",
            "term_end_quarter_index": 8,
            "purpose_restriction": "UNRESTRICTED",
        },
        TEST_USERS["dev_headers"],
    ), 201)
    assert_fund(ok)
    assert ok["fund_status"] == "DRAFT"


def test_activation_minimum_boundary_4999999_fails_5000000_passes(api):
    """PRD §3.1: 'The fund's `pledged_corpus_cents` — the sum of `amount_cents` over
    its `CORPUS` gifts in `PLEDGED`, `RECEIVED`, or `UNITIZED` status, i.e. every
    non-`CANCELLED`, non-`RETURNED` corpus gift — must reach the statutory minimum of
    5000000 cents ($50,000.00) before activation; because pledges count, a fund can
    activate on signed pledges before cash arrives, and an activation below the
    minimum is rejected with `ERR_MINIMUM_FUNDING_NOT_MET`.'

    Design: Corner/validations/activation_minimum_boundary_4999999_fails_5000000_passes
    """
    pool = create_pool(pool_name="Pool MN", inception_fiscal_year=2026)
    fund = create_fund(pool["id"], fund_code="FMIN", fund_name="Fund MN")
    donor = create_donor(donor_name="D MN")
    create_gift(fund["id"], donor["id"], "MN1", gift_type="CORPUS", amount_cents=4_999_999)

    res1 = api.activate_fund(fund["id"], TEST_USERS["dev_headers"])
    validate_error(res1, ApiErrorId.ERR_MINIMUM_FUNDING_NOT_MET, 422)

    create_gift(fund["id"], donor["id"], "MN2", gift_type="CORPUS", amount_cents=1)
    activated = validate_success(api.activate_fund(fund["id"], TEST_USERS["dev_headers"]), 200)
    assert activated["fund_status"] == "ACTIVE"
    assert activated["activated_quarter_index"] == 1


def test_donor_total_contributed_computed_on_receive_and_compensated_on_rescind(api):
    """PRD §3.2: 'Receipt also adds `amount_cents` to the donor's
    `total_contributed_cents`.'
    PRD §3.2: 'Rescinding a corpus gift subtracts `amount_cents` from the fund's
    `pledged_corpus_cents` (compensating the create) and subtracts `amount_cents`
    from the donor's `total_contributed_cents` (compensating the receive).'

    Design: Corner/entities/donor_total_contributed_computed_on_receive_and_compensated_on_rescind
    """
    pool = create_pool(pool_name="Pool DC", inception_fiscal_year=2026)
    fund = create_fund(pool["id"], fund_code="FDC", fund_name="Fund DC")
    donor = create_donor(donor_name="D DC", donor_type="ESTATE")
    gift = create_gift(fund["id"], donor["id"], "DC1", gift_type="CORPUS", amount_cents=5_000_000)
    activate_fund(fund["id"])

    received = validate_success(api.receive_gift(gift["id"], TEST_USERS["dev_headers"]), 200)
    assert received["gift_status"] == "RECEIVED"
    donor_after_receive = get_success_data(api.get_donor(donor["id"], TEST_USERS["dev_headers"]))
    assert donor_after_receive["total_contributed_cents"] == 5_000_000

    rescinded = validate_success(api.rescind_gift(gift["id"], TEST_USERS["dev_headers"]), 200)
    assert rescinded["gift_status"] == "RETURNED"
    donor_after = get_success_data(api.get_donor(donor["id"], TEST_USERS["dev_headers"]))
    assert donor_after["total_contributed_cents"] == 0
    fund_after = get_success_data(api.get_fund(fund["id"], TEST_USERS["dev_headers"]))
    assert fund_after["pledged_corpus_cents"] == 0


def test_gift_initial_state_and_receive_side_effects(api):
    """PRD §3.2: 'The gift is born `PLEDGED`.'
    PRD §3.2: 'Receipt stamps `received_quarter_index` with the open quarter
    (`current_quarter_index` + 1) — this stamp decides which quarter's `FINAL` price
    will unitize the gift — and computes an advisory
    `provisional_units_estimate_micro` as the gift's `amount_cents` multiplied by one
    billion and divided by the pool's `current_unit_price_millicents`, rounded half
    up.'

    Design: Corner/state_machines/gift_initial_state_and_receive_side_effects
    """
    ctx = setup_zero_manager_pool(pool_name="Pool GS")
    pool_id = ctx["pool"]["id"]
    # One finalized quarter (zero-manager pool, market value 0) at inception price.
    finalize_open_quarter(pool_id, 0)

    fund = create_fund(pool_id, fund_code="FGS", fund_name="Fund GS")
    donor = create_donor(donor_name="D GS")
    create_gift(fund["id"], donor["id"], "GS0", gift_type="CORPUS", amount_cents=5_000_000)
    created = create_gift(fund["id"], donor["id"], "GS1", gift_type="EXPENDABLE",
                          amount_cents=250_000)
    assert_gift(created)
    assert created["gift_status"] == "PLEDGED"
    activate_fund(fund["id"])

    received = validate_success(api.receive_gift(created["id"], TEST_USERS["dev_headers"]), 200)
    assert received["gift_status"] == "RECEIVED"
    assert received["received_quarter_index"] == 2
    assert received["provisional_units_estimate_micro"] == 2_500_000_000


def test_unitized_gift_rejects_receive_and_rescind_invalid_state(api):
    """PRD §3.2: 'Receiving a gift moves it from `PLEDGED` to `RECEIVED`'
    PRD §3.2: 'rescission after unitization is impossible because the transition only
    exists from `RECEIVED`.'
    PRD §2.8: '(6) lifecycle-state permission for the requested transition, failing
    as `ERR_INVALID_STATE_TRANSITION`'

    Design: Corner/state_machines/unitized_gift_rejects_receive_and_rescind_invalid_state
    """
    ctx = setup_zero_manager_pool(pool_name="Pool UG")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FUG", fund_name="Fund UG")
    donor = create_donor(donor_name="D UG")
    gift = create_gift(fund["id"], donor["id"], "UG1", gift_type="CORPUS",
                       amount_cents=5_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    finalize_open_quarter(pool_id, 0)

    unitized = get_success_data(api.get_gift(gift["id"], TEST_USERS["dev_headers"]))
    assert unitized["gift_status"] == "UNITIZED"

    res1 = api.receive_gift(gift["id"], TEST_USERS["dev_headers"])
    validate_error(res1, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    res2 = api.rescind_gift(gift["id"], TEST_USERS["dev_headers"])
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    after = get_success_data(api.get_gift(gift["id"], TEST_USERS["dev_headers"]))
    assert after["gift_status"] == "UNITIZED"
    assert after["units_purchased_micro"] == 50_000_000_000


def test_gift_received_after_finalize_catches_next_quarter_price(api):
    """PRD §3.2: 'The timing rule matters: a gift catches the price of the quarter it
    was received in. It must reach `RECEIVED` strictly before that quarter's finalize
    to ride its price; a gift received one request after the finalize catches the
    next quarter's price instead.'
    PRD §3.4: 'Each gift's `units_purchased_micro` is its `amount_cents` multiplied
    by one billion and divided by the `final_unit_price_millicents`, rounded half up
    per gift — never aggregated and then rounded.'

    Design: Corner/calculations/gift_received_after_finalize_catches_next_quarter_price
    """
    from test_helpers import setup_pool_world

    ctx = setup_pool_world(pool_name="Pool GT")
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    fund = create_fund(pool_id, fund_code="FGT", fund_name="Fund GT")
    donor = create_donor(donor_name="D GT")
    seed = create_gift(fund["id"], donor["id"], "GT1", gift_type="CORPUS",
                       amount_cents=10_000_000)
    activate_fund(fund["id"])
    receive_gift(seed["id"])
    gift_b = create_gift(fund["id"], donor["id"], "GT2", gift_type="EXPENDABLE",
                         amount_cents=5_000_000)
    receive_gift(gift_b["id"])

    # Q1 finalize: both gifts ride the Q1 price (inception 100000 millicents).
    finalize_open_quarter(pool_id, 10_000_000, reports=[{
        "manager_id": manager_id, "beginning_mv_cents": 0, "ending_mv_cents": 10_000_000,
        "flows": [{"day_offset": 0, "amount_cents": 15_000_000}],
    }])

    gift_b_after = get_success_data(api.get_gift(gift_b["id"], TEST_USERS["io_headers"]))
    assert gift_b_after["gift_status"] == "UNITIZED"
    assert gift_b_after["unitized_quarter_index"] == 1
    assert gift_b_after["units_purchased_micro"] == 50_000_000_000

    # Gift C received one request after the Q1 finalize catches Q2's price.
    gift_c = create_gift(fund["id"], donor["id"], "GT3", gift_type="EXPENDABLE",
                         amount_cents=5_000_000)
    receive_gift(gift_c["id"])
    gift_c_mid = get_success_data(api.get_gift(gift_c["id"], TEST_USERS["io_headers"]))
    assert gift_c_mid["gift_status"] == "RECEIVED"

    finalize_open_quarter(pool_id, 20_000_000, reports=[{
        "manager_id": manager_id, "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 20_000_000,
        "flows": [{"day_offset": 0, "amount_cents": 5_000_000}],
    }])

    gift_c_after = get_success_data(api.get_gift(gift_c["id"], TEST_USERS["io_headers"]))
    assert gift_c_after["gift_status"] == "UNITIZED"
    assert gift_c_after["unitized_quarter_index"] == 2
    # Q2 final price: round_half_up(20000000 * 1e9 / 150000000000) = 133333.
    assert gift_c_after["units_purchased_micro"] == 37_500_093_750


def test_fund_and_pool_termination_guards(api):
    """PRD §3.1: 'Terminating a fund is a `BoardMember` action from `ACTIVE` to
    `TERMINATED`, permitted only when the fund holds zero units (`units_held_micro`
    is 0), has no gift in `PLEDGED` or `RECEIVED`, has no distribution in
    `PROJECTED`, `PROPOSED`, `REVISION_REQUESTED`, or `APPROVED`, and has no payout
    in `SCHEDULED` or `DISBURSED`; any shortfall is rejected with
    `ERR_NOT_TERMINABLE`.'
    PRD §2.6: 'terminating a pool (a `BoardMember` action, allowed from either
    `ACTIVE` or `SUSPENDED` only when every fund of the pool has reached
    `TERMINATED`, failing which the request is rejected with `ERR_NOT_TERMINABLE`)'

    Design: Corner/validations/fund_and_pool_termination_guards
    """
    ctx = setup_zero_manager_pool(pool_name="Pool NT")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FNT", fund_name="Fund NT")
    donor = create_donor(donor_name="D NT")
    gift = create_gift(fund["id"], donor["id"], "NT1", gift_type="CORPUS",
                       amount_cents=5_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    finalize_open_quarter(pool_id, 0)

    res1 = api.terminate_fund(fund["id"], TEST_USERS["board_headers"])
    validate_error(res1, ApiErrorId.ERR_NOT_TERMINABLE, 422)

    res2 = api.terminate_pool(pool_id, TEST_USERS["board_headers"])
    validate_error(res2, ApiErrorId.ERR_NOT_TERMINABLE, 422)


def test_exception_on_healthy_fund_and_corpus_redemption_on_true_endowment_rejected(api):
    """PRD §3.6: 'The fund must be `ACTIVE` and actually underwater at request time;
    requesting an exception for a fund that is not underwater is rejected with
    `ERR_FUND_NOT_UNDERWATER`.'
    PRD §3.8: 'Corpus is inviolable for `TRUE_ENDOWMENT` funds and for
    `TERM_ENDOWMENT` funds whose `term_end_quarter_index` has not yet been reached;
    redemption on either is rejected with `ERR_CORPUS_INVIOLABLE`.'

    Design: Corner/validations/exception_on_healthy_fund_and_corpus_redemption_on_true_endowment_rejected
    """
    ctx = setup_zero_manager_pool(pool_name="Pool HF")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FHF", fund_name="Fund HF")
    donor = create_donor(donor_name="D HF")
    gift = create_gift(fund["id"], donor["id"], "HF1", gift_type="CORPUS",
                       amount_cents=5_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    finalize_open_quarter(pool_id, 0)

    # Market value 5000000 equals historic gift value 5000000: equality is not underwater.
    res1 = api.create_exception(
        {
            "fund_id": fund["id"],
            "fiscal_year": 2026,
            "requested_amount_cents": 100_000,
            "justification": "not needed",
        },
        TEST_USERS["dev_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_FUND_NOT_UNDERWATER, 422)

    res2 = api.redeem_corpus(fund["id"], {"amount_cents": 1000}, TEST_USERS["board_headers"])
    validate_error(res2, ApiErrorId.ERR_CORPUS_INVIOLABLE, 422)

    fund_after = get_success_data(api.get_fund(fund["id"], TEST_USERS["io_headers"]))
    assert fund_after["units_held_micro"] == 50_000_000_000
    assert fund_after["historic_gift_value_cents"] == 5_000_000
