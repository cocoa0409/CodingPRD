"""Buy plans (tiered landed cost, budget, OCC, double-commit) and commission
statements (provisional vs final, posture gate, segregation of duties)."""
from test_helpers import (
    ApiErrorId,
    assert_buy_plan,
    assert_commission_statement,
    create_approved_adoption,
    create_faculty,
    create_publisher_with_agreement,
    create_section,
    create_term,
    create_title,
    get_buy_plan_for_adoption,
    get_success_data,
    make_faculty_headers,
    make_finance_headers,
    make_manager_headers,
    open_section,
    open_term_adoption,
    reset_clock,
    drive_term_to_sales_open,
    run_census,
    set_clock,
    CLOCK_AT_CENSUS,
    CLOCK_PAST_ADD_DROP,
    place_order,
    get_first_order_line,
    setup_sales_open_with_approved_adoption,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def _two_plan_scenario(api):
    """Two APPROVED adoptions of the same title (60 + 50 new units), each
    with a DRAFT buy plan whose quantities are pinned by PATCH. Returns
    (plan1, plan2)."""
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000004", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    sec1 = create_section(term["id"], faculty["id"], course_code="CS101")
    sec2 = create_section(term["id"], faculty["id"], course_code="CS102")
    open_term_adoption(term["id"])
    opened1 = open_section(sec1["id"])
    opened2 = open_section(sec2["id"])
    ado1 = create_approved_adoption(
        sec1["id"], title["id"], faculty["id"], opened1["version"],
        qty_new=60, posted_price_cents=10000,
    )
    ado2 = create_approved_adoption(
        sec2["id"], title["id"], faculty["id"], opened2["version"],
        qty_new=50, posted_price_cents=10000,
    )
    bp1 = get_buy_plan_for_adoption(ado1["id"])
    bp2 = get_buy_plan_for_adoption(ado2["id"])
    bp1 = validate_success(
        api.patch_buy_plan(
            bp1["id"],
            {"qty_new": 60, "qty_used": 0, "qty_rental": 0, "qty_digital": 0},
            MANAGER,
        )
    )
    bp2 = validate_success(
        api.patch_buy_plan(
            bp2["id"],
            {"qty_new": 50, "qty_used": 0, "qty_rental": 0, "qty_digital": 0},
            MANAGER,
        )
    )
    return bp1, bp2


def test_buyplan_tier_projection_evaluation_order(api):
    """PRD §3.5: "First, gross units are the sum of the plan's `qty_new`,
    `qty_used`, `qty_rental`, and `qty_digital`. Second, projected units add to
    gross units the same four-quantity sum over every other buy plan in
    `COMMITTED` or `RECEIVED` in the same term whose adoption's title shares
    this plan's publisher. Third, a tier bonus of 0.02 applies when projected
    units are at least 100; otherwise the bonus is 0. Fourth,
    `discount_pct_applied` is the active agreement's `discount_pct` plus the
    tier bonus. Fifth, the unit new cost is the title's `list_price_cents`
    multiplied by one minus `discount_pct_applied`, rounded half-up to integer
    cents. Sixth, `landed_cost_cents` is `qty_new` multiplied by that unit new
    cost. The flag `tier_bonus_applied` records whether the bonus was granted."

    Design: Difficulty/combinatorial_formula/buyplan_tier_projection_evaluation_order
    """
    bp1, bp2 = _two_plan_scenario(api)

    committed1 = validate_success(
        api.commit_buy_plan(
            bp1["id"], {"expected_buy_plan_version": bp1["version"]}, MANAGER
        )
    )
    assert_buy_plan(committed1)
    # Projected 60 < 100: no bonus; 60 * round(10000 * 0.90) = 540000.
    assert committed1["tier_bonus_applied"] is False
    assert committed1["landed_cost_cents"] == 540000

    committed2 = validate_success(
        api.commit_buy_plan(
            bp2["id"], {"expected_buy_plan_version": bp2["version"]}, MANAGER
        )
    )
    # Projected 50 + 60 = 110 >= 100: bonus applies; 50 * round(10000 * 0.88).
    assert committed2["tier_bonus_applied"] is True
    assert committed2["discount_pct_applied"] == 0.12
    assert committed2["landed_cost_cents"] == 440000


def test_buyplan_tier_bonus_no_retroactive_repricing(api):
    """PRD §3.5: "Note the deliberate asymmetry: the tier is selected on
    projected volume including this plan, but the bonus applies only to this
    plan's cost — there is no retroactive repricing of earlier plans."

    Design: Difficulty/combinatorial_formula/buyplan_tier_projection_evaluation_order
    """
    bp1, bp2 = _two_plan_scenario(api)
    validate_success(
        api.commit_buy_plan(
            bp1["id"], {"expected_buy_plan_version": bp1["version"]}, MANAGER
        )
    )
    validate_success(
        api.commit_buy_plan(
            bp2["id"], {"expected_buy_plan_version": bp2["version"]}, MANAGER
        )
    )
    # Re-reading plan 1 after plan 2 crossed the tier: unchanged.
    reread = get_success_data(api.get_buy_plan(bp1["id"], MANAGER))
    assert reread["tier_bonus_applied"] is False
    assert reread["discount_pct_applied"] == 0.10
    assert reread["landed_cost_cents"] == 540000


def test_buyplan_commit_twice_rejected(api):
    """PRD §3.5: "A `BookstoreManager` commits a `DRAFT` plan, which requires
    the source adoption to be `APPROVED` (`ERR_ADOPTION_NOT_APPROVED`
    otherwise)".
    PRD §2.8: "State: the target resource is in a valid from-state for the
    requested transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/buyplan_commit_twice_rejected
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001005", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    ado = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, posted_price_cents=10000,
    )
    plan = get_buy_plan_for_adoption(ado["id"])

    committed = validate_success(
        api.commit_buy_plan(
            plan["id"], {"expected_buy_plan_version": plan["version"]}, MANAGER
        )
    )
    assert committed["status"] == "COMMITTED"
    assert committed["landed_cost_cents"] == 90000

    # Second commit from COMMITTED with the current version: state guard,
    # not OCC.
    fresh = get_success_data(api.get_buy_plan(plan["id"], MANAGER))
    resp = api.commit_buy_plan(
        plan["id"], {"expected_buy_plan_version": fresh["version"]}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_buyplan_commit_stale_version_rejected(api):
    """PRD §2.7: "Committing a buy plan requires `expected_buy_plan_version`
    matching the plan's current `version`. The tier projection and budget
    arithmetic the client relied on were computed from the plan's quantities; a
    stale read invalidates that arithmetic."

    Design: Corner/cross_cutting_layers/occ_buyplan_commit_stale_version_rejected
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001020", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    ado = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, posted_price_cents=10000,
    )
    plan = get_buy_plan_for_adoption(ado["id"])
    # An intervening PATCH advances the plan version past the captured one.
    validate_success(api.patch_buy_plan(plan["id"], {"qty_new": 12}, MANAGER))

    resp = api.commit_buy_plan(
        plan["id"], {"expected_buy_plan_version": plan["version"]}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api.get_buy_plan(plan["id"], MANAGER))
    assert current["status"] == "DRAFT"
    assert current["committed_by_user_id"] is None


def test_buyplan_commit_over_budget_rejected(api):
    """PRD §3.5: "Commitment also enforces the term budget: the sum of
    `landed_cost_cents` over all `COMMITTED` and `RECEIVED` plans in the term,
    plus this plan's `landed_cost_cents`, must not exceed the term's
    `buy_budget_cents`; a commit that would breach the cap is rejected with
    `ERR_TERM_BUDGET_EXCEEDED`."

    Design: Corner/endpoints/buyplan_commit_over_budget_rejected
    """
    reset_clock()
    term = create_term({"buy_budget_cents": 500000})
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001014", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    ado = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=60, posted_price_cents=10000,
    )
    plan = get_buy_plan_for_adoption(ado["id"])

    resp = api.commit_buy_plan(
        plan["id"], {"expected_buy_plan_version": plan["version"]}, MANAGER
    )
    # 60 * round(10000 * 0.90) = 540000 > 500000.
    validate_error(resp, ApiErrorId.ERR_TERM_BUDGET_EXCEEDED)
    current = get_success_data(api.get_buy_plan(plan["id"], MANAGER))
    assert current["status"] == "DRAFT"
    assert current["committed_by_user_id"] is None


def test_commission_provisional_vs_final_reconciliation(api):
    """PRD §3.10: "Creation computes a `PROVISIONAL` snapshot, recorded in
    `calculation_variant`."
    PRD §3.10: "A successful issue recomputes the commission with the `FINAL`
    variant — folding in all returns processed between creation and issue —
    locks the numbers, stamps `issued_by_user_id`, and increments the
    statement's `version`."
    PRD §3.10: "Title net is gross minus returns, and the title's commission is
    the net multiplied by the active agreement's `commission_pct`, rounded
    half-up to integer cents."

    Design: Corner/calculations/commission_provisional_vs_final_reconciliation
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "has_used": False,
                         "has_rental": False, "has_digital": False},
        awarded_aid_cents=0,
        isbn="9780000001007",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1}],
    )
    line = get_first_order_line(order["id"])

    set_clock(CLOCK_AT_CENSUS)
    run_census(base["term"]["id"])

    stmt = validate_success(
        api.create_commission_statement(
            {"publisher_id": base["publisher"]["id"],
             "term_id": base["term"]["id"]},
            make_finance_headers("fin-1"),
        ),
        expected_status=201,
    )
    assert_commission_statement(stmt)
    assert stmt["calculation_variant"] == "PROVISIONAL"
    assert stmt["gross_sales_cents"] == 10000
    assert stmt["returns_cents"] == 0
    assert stmt["commission_cents"] == 800

    # Post-deadline manager-override return of the line: 8000 refund,
    # processed after the provisional snapshot.
    set_clock(CLOCK_PAST_ADD_DROP)
    validate_success(
        api.return_order_line(order["id"], line["id"], {"override": True}, MANAGER)
    )

    issued = validate_success(
        api.issue_commission_statement(stmt["id"], make_finance_headers("fin-1"))
    )
    assert issued["status"] == "ISSUED"
    assert issued["calculation_variant"] == "FINAL"
    assert issued["returns_cents"] == 8000
    assert issued["net_sales_cents"] == 2000
    assert issued["commission_cents"] == 160
    assert issued["issued_by_user_id"] == "fin-1"


def test_commission_issue_requires_term_posture_clear(api):
    """PRD §3.10: "First, the term's `compliance_posture` must be `CLEAR`;
    issuing into a `RESTRICTED` term — one with non-compliant sections at
    adoption close — is rejected with `ERR_TERM_NOT_COMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/commission_issue_requires_term_posture_clear
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000011", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    # DRAFT adoption that will be swept to EXPIRED at adoption close, making
    # the section NON_COMPLIANT and the term RESTRICTED.
    from test_helpers import create_adoption
    create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    drive_term_to_sales_open(term["id"])
    set_clock(CLOCK_AT_CENSUS)
    run_census(term["id"])

    term_now = get_success_data(api.get_term(term["id"], MANAGER))
    assert term_now["compliance_posture"] == "RESTRICTED"

    stmt = validate_success(
        api.create_commission_statement(
            {"publisher_id": pub["id"], "term_id": term["id"]},
            make_finance_headers("fin-1"),
        ),
        expected_status=201,
    )
    resp = api.issue_commission_statement(stmt["id"], make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_COMPLIANT)
    current = get_success_data(
        api.get_commission_statement(stmt["id"], make_finance_headers("fin-1"))
    )
    assert current["status"] == "DRAFT"


def test_commission_issue_blocked_until_posture_clears(api):
    """PRD §3.10: "First, the term's `compliance_posture` must be `CLEAR`;
    issuing into a `RESTRICTED` term — one with non-compliant sections at
    adoption close — is rejected with `ERR_TERM_NOT_COMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/commission_issue_requires_term_posture_clear
    """
    reset_clock()
    # Restricted term: one DRAFT adoption expires at close.
    term_r = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000035", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    sec_r = create_section(term_r["id"], faculty["id"], course_code="CS101")
    open_term_adoption(term_r["id"])
    opened_r = open_section(sec_r["id"])
    from test_helpers import create_adoption
    create_adoption(
        sec_r["id"], title["id"], faculty["id"], opened_r["version"],
        qty_new=5, posted_price_cents=10000,
    )
    drive_term_to_sales_open(term_r["id"])
    set_clock(CLOCK_AT_CENSUS)
    run_census(term_r["id"])
    stmt_r = validate_success(
        api.create_commission_statement(
            {"publisher_id": pub["id"], "term_id": term_r["id"]},
            make_finance_headers("fin-1"),
        ),
        expected_status=201,
    )
    resp = api.issue_commission_statement(stmt_r["id"], make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_COMPLIANT)

    # A clean term (no sections, posture CLEAR) issues without the gate firing.
    term_c = create_term({"code": "2027-FALL"})
    open_term_adoption(term_c["id"])
    drive_term_to_sales_open(term_c["id"])
    set_clock(CLOCK_AT_CENSUS)
    run_census(term_c["id"])
    term_c_now = get_success_data(api.get_term(term_c["id"], MANAGER))
    assert term_c_now["compliance_posture"] == "CLEAR"
    stmt_c = validate_success(
        api.create_commission_statement(
            {"publisher_id": pub["id"], "term_id": term_c["id"]},
            make_finance_headers("fin-1"),
        ),
        expected_status=201,
    )
    issued = validate_success(
        api.issue_commission_statement(stmt_c["id"], make_finance_headers("fin-1"))
    )
    assert issued["status"] == "ISSUED"


def test_sod_commission_issue_by_committer_rejected(api):
    """PRD §3.10: "Second, segregation of duties: the issuing `FinanceAdmin`'s
    `X-User-ID` must differ from the `committed_by_user_id` of every buy plan
    in `COMMITTED` or `RECEIVED` for this publisher in this term; a match means
    the same operator committed purchasing and is now certifying the commission
    on it, and the issue is rejected with `ERR_SOD_COMMISSION_CONFLICT` (HTTP
    403)."

    Design: Corner/roles/sod_commission_issue_by_committer_rejected
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001018", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    ado = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, posted_price_cents=10000,
    )
    plan = get_buy_plan_for_adoption(ado["id"])
    committed = validate_success(
        api.commit_buy_plan(
            plan["id"], {"expected_buy_plan_version": plan["version"]},
            make_manager_headers("mgr-1"),
        )
    )
    assert committed["committed_by_user_id"] == "mgr-1"

    drive_term_to_sales_open(term["id"])
    set_clock(CLOCK_AT_CENSUS)
    run_census(term["id"])

    stmt = validate_success(
        api.create_commission_statement(
            {"publisher_id": pub["id"], "term_id": term["id"]},
            make_finance_headers("fin-1"),
        ),
        expected_status=201,
    )
    # The issuer id equals the recorded committer id: segregation conflict.
    resp = api.issue_commission_statement(stmt["id"], make_finance_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_COMMISSION_CONFLICT)

    # A different operator id issues cleanly.
    issued = validate_success(
        api.issue_commission_statement(stmt["id"], make_finance_headers("fin-9"))
    )
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == "fin-9"
