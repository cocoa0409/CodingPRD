"""Side letters / MFN uniqueness, valuation-mark conflicts and supersession,
investment realization, NAV, the WRITE-OFF cascade, OCC concurrency, and the
state-precedence cancel case. Covers the remaining difficulty- and corner-queue
instances across marks, validations, endpoints, and cross-cutting layers.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_capital_call_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# State precedence: cancel an already-cancelled call
# ---------------------------------------------------------------------------

def test_cancel_already_cancelled_call_is_invalid_state(api):
    """PRD §2.8: "For any operation that drives a state machine, the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_capital_call_cancel
    """
    fund = fx.create_fund(name="PriOne Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP N", tax_id_last4="9008")
    fx.create_accepted_commitment(fund["id"], lp["id"], 6_000_000)
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    validate_success(api.cancel_capital_call(call["id"], FM), 200)  # now CANCELLED
    validate_error(api.cancel_capital_call(call["id"], FM), "ERR_INVALID_STATE", 409)


def test_cancel_settled_call_is_invalid_state(api):
    """PRD §2.8: "the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_capital_call_cancel
    """
    fund = fx.create_fund(name="PriOne Settled Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP N2", tax_id_last4="9028")
    fx.create_accepted_commitment(fund["id"], lp["id"], 6_000_000)
    call = fx.issue_and_fund_call(fund["id"], 1_000_000)  # drives call to SETTLED
    assert validate_success(api.get_capital_call(call["id"], FM), 200)["status"] == "SETTLED"
    validate_error(api.cancel_capital_call(call["id"], FM), "ERR_INVALID_STATE", 409)


# ---------------------------------------------------------------------------
# Side letters / MFN uniqueness
# ---------------------------------------------------------------------------

def test_mfn_rank_uniqueness_rejected(api):
    """PRD §3.7: "The `mfn_rank` must be unique on the fund among side letters that are `PROPOSED` or `EXECUTED`; a collision is rejected with `ERR_MFN_RANK_TAKEN` (HTTP 409)."

    Design: Corner/validations/mfn_rank_uniqueness_rejected
    """
    fund = fx.create_fund(name="MFN Fund", target_size_cents=5_000_000)
    lp1 = fx.create_lp(legal_name="LP MR1", tax_id_last4="3030")
    lp2 = fx.create_lp(legal_name="LP MR2", tax_id_last4="3131")
    validate_success(api.create_side_letter(
        {"fund_id": fund["id"], "lp_id": lp1["id"], "mfn_rank": 1}, CO), 201)
    validate_error(api.create_side_letter(
        {"fund_id": fund["id"], "lp_id": lp2["id"], "mfn_rank": 1}, CO),
        "ERR_MFN_RANK_TAKEN", 409)


# ---------------------------------------------------------------------------
# Valuation marks — supersession and date conflict
# ---------------------------------------------------------------------------

def test_finalize_mark_supersedes_prior_final(api):
    """PRD §3.4: "Finalization cascades: any prior mark on the same investment still in `FINAL` status is moved to `SUPERSEDED`, and the investment's `current_mark_cents` is recomputed from the newly final mark."

    Design: Corner/state_machines/finalize_mark_supersedes_prior_final
    """
    fund = fx.create_fund(name="Supersede Fund", target_size_cents=5_000_000)
    inv, _ = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                  company_name="Lambda", sector="Edu")
    mark1 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-03-31T00:00:00Z",
         "fair_value_cents": 3_500_000, "methodology": "LAST_ROUND"}, FA), 201)
    api.finalize_valuation_mark(mark1["id"], FA)
    mark2 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
         "fair_value_cents": 4_200_000, "methodology": "DCF"}, FA), 201)
    finalized = validate_success(api.finalize_valuation_mark(mark2["id"], FA), 200)
    assert finalized["status"] == "FINAL"
    assert validate_success(api.get_valuation_mark(mark1["id"], FM), 200)["status"] == "SUPERSEDED"
    assert validate_success(api.get_investment(inv["id"], FM), 200)["current_mark_cents"] == 4_200_000


def test_valuation_mark_equal_date_conflict(api):
    """PRD §3.4: "Before a mark may be finalized, its `as_of_date` must be strictly later than the `as_of_date` of the investment's current `FINAL` mark; an equal or earlier date collides and is rejected with `ERR_MARK_DATE_CONFLICT` (HTTP 409), which prevents a back-dated mark from superseding a newer one."

    Design: Difficulty/resource_temporal_overlap/valuation_mark_strictly_later_date_conflict
    """
    fund = fx.create_fund(name="MarkConflict Fund", target_size_cents=5_000_000)
    inv, _ = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                  company_name="Eta", sector="Media")
    mark1 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
         "fair_value_cents": 3_500_000, "methodology": "LAST_ROUND"}, FA), 201)
    api.finalize_valuation_mark(mark1["id"], FA)
    mark2 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
         "fair_value_cents": 4_000_000, "methodology": "DCF"}, FA), 201)
    validate_error(api.finalize_valuation_mark(mark2["id"], FA),
                   "ERR_MARK_DATE_CONFLICT", 409)


def test_valuation_mark_earlier_date_conflict(api):
    """PRD §3.4: "Before a mark may be finalized, its `as_of_date` must be strictly later than the `as_of_date` of the investment's current `FINAL` mark; an equal or earlier date collides and is rejected with `ERR_MARK_DATE_CONFLICT` (HTTP 409), which prevents a back-dated mark from superseding a newer one."

    Design: Difficulty/resource_temporal_overlap/valuation_mark_strictly_later_date_conflict
    """
    fund = fx.create_fund(name="MarkEarlier Fund", target_size_cents=5_000_000)
    inv, _ = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                  company_name="Eta3", sector="Media")
    mark1 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
         "fair_value_cents": 3_500_000, "methodology": "LAST_ROUND"}, FA), 201)
    api.finalize_valuation_mark(mark1["id"], FA)
    mark2 = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-03-31T00:00:00Z",
         "fair_value_cents": 4_000_000, "methodology": "DCF"}, FA), 201)
    validate_error(api.finalize_valuation_mark(mark2["id"], FA),
                   "ERR_MARK_DATE_CONFLICT", 409)


# ---------------------------------------------------------------------------
# WRITE_OFF cascade
# ---------------------------------------------------------------------------

def test_writeoff_mark_cascades_to_investment_and_company(api):
    """PRD §3.4: "If the finalized mark's `methodology` is `WRITE_OFF`, the cascade reaches further — the owning `Investment` moves to `IMPAIRED` and the owning `PortfolioCompany` moves to `WRITTEN_OFF`."

    Design: Difficulty/transitive_cascade/writeoff_mark_cascades_to_investment_and_company
    """
    fund = fx.create_fund(name="WriteOff Fund", target_size_cents=5_000_000)
    inv, pc = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                   ownership_pct_bps=1200, company_name="Delta", sector="Bio")
    mark = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
         "fair_value_cents": 0, "methodology": "WRITE_OFF"}, FA), 201)
    finalized = validate_success(api.finalize_valuation_mark(mark["id"], FA), 200)
    assert finalized["status"] == "FINAL"
    assert validate_success(api.get_investment(inv["id"], FM), 200)["status"] == "IMPAIRED"
    assert validate_success(api.get_investment(inv["id"], FM), 200)["current_mark_cents"] == 0
    assert validate_success(api.get_portfolio_company(pc["id"], FM), 200)["status"] == "WRITTEN_OFF"


def test_writeoff_cascade_sets_current_mark_to_zero(api):
    """PRD §3.4: "the investment's `current_mark_cents` is recomputed from the newly final mark."

    Design: Difficulty/transitive_cascade/writeoff_mark_cascades_to_investment_and_company
    """
    fund = fx.create_fund(name="WriteOff2 Fund", target_size_cents=5_000_000)
    inv, pc = fx.create_investment(fund["id"], cost_basis_cents=2_500_000,
                                   ownership_pct_bps=1000, company_name="Delta2", sector="Bio")
    mark = validate_success(api.create_valuation_mark(
        {"investment_id": inv["id"], "as_of_date": "2024-09-30T00:00:00Z",
         "fair_value_cents": 0, "methodology": "WRITE_OFF"}, FA), 201)
    validate_success(api.finalize_valuation_mark(mark["id"], FA), 200)
    refreshed = validate_success(api.get_investment(inv["id"], FM), 200)
    assert refreshed["current_mark_cents"] == 0
    assert refreshed["status"] == "IMPAIRED"


# ---------------------------------------------------------------------------
# Realize investment + NAV
# ---------------------------------------------------------------------------

def test_realize_investment_sets_proceeds_and_exits_company(api):
    """PRD §3.4: "Realizing an investment is the `FundManager`'s act of crystallizing an exit. It moves the investment from `ACTIVE` to `REALIZED`, records the supplied `realized_proceeds_cents`, and moves the owning company from `HELD` to `EXITED`."

    Design: Corner/endpoints/realize_investment_action_sets_proceeds
    """
    fund = fx.create_fund(name="Realize Fund", target_size_cents=5_000_000)
    inv, pc = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                   company_name="Omicron", sector="Robotics")
    realized = validate_success(
        api.realize_investment(inv["id"], {"realized_proceeds_cents": 5_000_000}, FM), 200)
    assert realized["status"] == "REALIZED"
    assert realized["realized_proceeds_cents"] == 5_000_000
    assert validate_success(api.get_portfolio_company(pc["id"], FM), 200)["status"] == "EXITED"


def test_fund_nav_from_final_mark(api):
    """PRD §3.1: "The fund NAV is the sum of `current_mark_cents` across the fund's investments whose `status` is `ACTIVE` or `IMPAIRED`."

    Design: Corner/endpoints/fund_nav_computed_read
    """
    fund = fx.create_fund(name="NAV Fund", target_size_cents=5_000_000)
    inv, _ = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                  company_name="Xi", sector="Climate")
    fx.create_final_mark(inv["id"], "2024-06-30T00:00:00Z", 4_000_000, methodology="DCF")
    nav = validate_success(api.get_fund_nav(fund["id"], FM), 200)
    assert nav["fund_nav_cents"] == 4_000_000


# ---------------------------------------------------------------------------
# OCC on fund version
# ---------------------------------------------------------------------------

def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.7: "When a `FundManager` issues a capital call, the request must carry `expected_fund_version` matching the target fund's current `version`."
    PRD §3.3: "On issuance the call is assigned the next monotonic `call_number` for that fund (1, 2, 3, and so on), enters `ISSUED` status, and the fund's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    fund = fx.create_fund(name="OCC OK Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP OK", tax_id_last4="4141")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    v1 = fx.fund_version(fund["id"])
    payload = create_capital_call_payload(fund["id"], v1, called_amount_cents=1_000_000)
    validate_success(api.create_capital_call(payload, FM), 201)
    assert validate_success(api.get_fund(fund["id"], FM), 200)["version"] == v1 + 1


def test_occ_stale_version_rejected(api):
    """PRD §2.7: "If the fund's `version` has advanced since the client last read it — because another call was issued, a commitment was accepted, or a distribution was declared, each of which bumps the fund — the issuance is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), forcing the client to refresh before it mis-sequences the call."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected
    """
    fund = fx.create_fund(name="OCC Stale Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP SV", tax_id_last4="4242")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    v1 = fx.fund_version(fund["id"])
    # First call bumps the fund version; v1 is now stale.
    validate_success(
        api.create_capital_call(
            create_capital_call_payload(fund["id"], v1, called_amount_cents=1_000_000), FM), 201)
    stale = create_capital_call_payload(fund["id"], v1, called_amount_cents=500_000)
    validate_error(api.create_capital_call(stale, FM), "ERR_STALE_FUND_VERSION", 412)
