"""Calculation correctness, variant selection, business validations, and
immediate-consistency reads.

Queue B (Corner) — sections: calculations, validations, consistency_model.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_funeral_home, create_gpl_item, create_plot,
    create_case, create_disclosed_case, add_line, select_line, create_contract,
    setup_arranged_case, post_principal, post_earnings, submit_for_funding,
    current_contract_version,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]


# ==========================================================================
# calculations
# ==========================================================================
def test_at_need_funded_amount_sums_two_principal_deposits(api):
    """PRD §3.4: "For an AT_NEED_DIRECT contract it is the chronological sum of
    the amounts of every posted principal deposit ... this variant counts only
    realized posted principal payments, with no earnings and no projection."

    Two SELECTED lines (SERVICE 200000 + taxable MERCHANDISE 162000) lock the
    contract amount at 362000; deposits 200000 then 162000 sum to 362000,
    projection 0.

    Design: Corner/calculations/at_need_chronological_funded_amount_two_deposits
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, preneed_trustable=True, unit_price_cents=200000)
    casket = create_gpl_item(home["id"], code="CASKET", name="Casket",
                             category="MERCHANDISE", taxable=True, preneed_trustable=True,
                             unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    casket_line = add_line(case["id"], casket["id"])
    select_line(case["id"], casket_line["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 200000)
    post_principal(contract["id"], 162000)

    data = validate_success(api.get_contract(contract["id"], TRUST))
    assert data["funded_amount_cents"] == 362000
    assert data["projected_earnings_cents"] == 0
    assert data["contract_amount_cents"] == 362000


def test_at_need_reserve_snapshots_live_price(api):
    """PRD §3.8: "its locked_price_cents is snapshotted from current_price_cents
    as a price lock".
    PRD §3.8: "For an AT_NEED case the charge is the plot's live
    current_price_cents".

    Reserving an 80000 plot for an AT_NEED case locks locked_price_cents at 80000.

    Design: Corner/calculations/plot_charge_at_need_locks_live_price_at_reservation
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-90", current_price_cents=80000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")

    reserved = validate_success(api.reserve_plot(
        plot["id"], {"case_id": case["id"], "expected_plot_version": plot["version"]}, CLERK))
    assert reserved["locked_price_cents"] == 80000
    assert reserved["status"] == "RESERVED"


# ==========================================================================
# validations
# ==========================================================================
def test_add_statement_line_before_disclosure_rejected(api):
    """PRD §3.2: "No statement line may be added and no GFS may be issued unless
    disclosure_acknowledged is true; an attempt to add a line or issue the
    statement before disclosure has been acknowledged is rejected with
    ERR_DISCLOSURE_REQUIRED (HTTP 409)."

    Design: Corner/validations/add_statement_line_before_disclosure_returns_disclosure_required
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=False, unit_price_cents=100000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")  # INTAKE, not disclosed

    resp = api.add_statement_line(case["id"], {"gpl_item_id": svc["id"], "quantity": 1}, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED.value)


def test_mark_funded_preneed_principal_short_returns_trust_underfunded(api):
    """PRD §3.6: "for a PRENEED_TRUST contract, trust_principal_cents must be at
    least trust_required_cents, and an underfunded preneed trust is rejected with
    ERR_TRUST_UNDERFUNDED (HTTP 409)."

    trust_required 90000; principal 88000 < 90000, but EARNINGS 30000 lift
    funded_amount to 120640 >= contract_amount 100000 — funding sufficiency passes
    while the trust gate fails.

    Design: Corner/validations/mark_funded_preneed_principal_short_returns_trust_underfunded
    """
    home = create_funeral_home(name="Trust Home", sales_tax_pct=0.0,
                               state_trust_pct=0.90, trust_admin_retention_cents=0)
    tr = create_gpl_item(home["id"], code="SVC-TR", name="Trustable service",
                         category="SERVICE", taxable=False, non_declinable=True,
                         preneed_trustable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], tr["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 88000)
    post_earnings(contract["id"], 30000)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v}, TRUST)
    validate_error(resp, ApiErrorId.ERR_TRUST_UNDERFUNDED.value)

    after = validate_success(api.get_contract(contract["id"], TRUST))
    assert after["trust_required_cents"] == 90000
    assert after["trust_principal_cents"] == 88000
    assert after["credited_earnings_cents"] == 30000
    assert after["funded_amount_cents"] == 120640
    assert after["status"] == "PENDING_FUNDING"


def test_mark_funded_preneed_fully_funded_succeeds(api):
    """PRD §3.6: "The contract must be sufficiently funded: funded_amount_cents
    must be at least contract_amount_cents ... Additionally, for a PRENEED_TRUST
    contract, trust_principal_cents must be at least trust_required_cents".

    Principal 100000 >= required 90000 and funded 103000 >= contract_amount
    100000, so both gates pass and the contract becomes FUNDED.

    Design: Corner/validations/mark_funded_preneed_fully_funded_succeeds
    """
    home = create_funeral_home(name="Trust Home 2", sales_tax_pct=0.0,
                               state_trust_pct=0.90, trust_admin_retention_cents=0)
    tr = create_gpl_item(home["id"], code="SVC-TR", name="Trustable service",
                         category="SERVICE", taxable=False, non_declinable=True,
                         preneed_trustable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], tr["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 100000)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    funded = validate_success(api.mark_funded(
        contract["id"], {"expected_contract_version": c_v}, TRUST))
    assert funded["trust_required_cents"] == 90000
    assert funded["trust_principal_cents"] == 100000
    assert funded["funded_amount_cents"] == 103000
    assert funded["status"] == "FUNDED"


def test_mark_funded_at_need_shortfall_returns_funding_shortfall(api):
    """PRD §3.6: "funded_amount_cents must be at least contract_amount_cents, and
    a shortfall is rejected with ERR_FUNDING_SHORTFALL (HTTP 409)."

    funded 99999 < contract_amount 100000.

    Design: Corner/validations/mark_funded_at_need_shortfall_returns_funding_shortfall
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    post_principal(contract["id"], 99999)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v}, TRUST)
    validate_error(resp, ApiErrorId.ERR_FUNDING_SHORTFALL.value)

    after = validate_success(api.get_contract(contract["id"], TRUST))
    assert after["status"] == "PENDING_FUNDING"


def test_remove_non_declinable_line_rejected(api):
    """PRD §3.3: "A line drawn from a non-declinable item is created already
    SELECTED and can never be removed ... Attempting to remove a non-declinable
    line is rejected with ERR_NON_DECLINABLE_LINE (HTTP 409)."

    Design: Corner/validations/remove_non_declinable_line_returns_non_declinable_line
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic services",
                          category="SERVICE", non_declinable=True, unit_price_cents=200000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    nd_line = add_line(case["id"], svc["id"])

    resp = api.remove_statement_line(case["id"], nd_line["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_NON_DECLINABLE_LINE.value)

    after = validate_success(api.get_statement_line(nd_line["id"], ARRANGER))
    assert after["line_status"] == "SELECTED"


# ==========================================================================
# consistency_model
# ==========================================================================
def test_provisional_total_visible_immediately_after_line_add(api):
    """PRD §3.3: "Adding, selecting, or removing a line recomputes the case's
    provisional statement total."
    PRD §3.3: "if the line is taxable, its tax is that subtotal multiplied by the
    home's sales_tax_pct, rounded half up to a whole cent".

    A taxable 150000 line, once SELECTED, immediately shows provisional
    150000 + round_half_up(150000*0.08)=12000 = 162000 on the next GET.

    Design: Corner/consistency_model/derived_total_visible_immediately_after_line_add
    """
    home = create_funeral_home()
    casket = create_gpl_item(home["id"], code="CASKET", name="Casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    line = add_line(case["id"], casket["id"])
    select_line(case["id"], line["id"])

    data = validate_success(api.get_case(case["id"], ARRANGER))
    assert data["statement_total_provisional_cents"] == 162000
