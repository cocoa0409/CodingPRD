"""Prize awards: category-tabulated gate, placement selector, purse snapshot,
budget reservation and restore, segregation of duties, disburse withholding
variants, the tax-reportability boundary, and the contest tax summary.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_budget_invariant,
    assert_prize_award,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_prize_award_payload
from test_helpers.test_users import TEST_USERS, make_treasurer_headers

LEAD = TEST_USERS["contest_lead_headers"]
TR1 = TEST_USERS["treasurer_headers"]


def _tabulated_with_two_placed(prize_purse_cents=100000, prize_budget_cents=100000):
    """TABULATED category with e1 rank 1 (9,9,9) and e2 rank 2 (8,8,8)."""
    return fx.setup_tabulated_category(
        prize_purse_cents=prize_purse_cents,
        prize_budget_cents=prize_budget_cents,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )


# ---------------------------------------------------------------------------
# Cross-entity gate: PrizeAward -> Category TABULATED
# ---------------------------------------------------------------------------

def test_prize_create_requires_category_tabulated(api):
    """PRD §3.7: "Creating against a category not yet `TABULATED` is rejected with `ERR_CATEGORY_NOT_TABULATED`."
    PRD §3.7: "The entry being awarded is selected automatically: the `PLACED` entry of the category whose `placement_rank` equals the requested `rank`, with an empty result rejected as `ERR_PLACEMENT_NOT_FOUND`."
    PRD §3.7: "The award's `value_cents` is snapshotted at creation from the category's purse split — `prize_rank1_cents`, `prize_rank2_cents`, or `prize_rank3_cents` according to rank — so later edits to the purse never rewrite an existing award."

    Design: Difficulty/cross_entity_state_dependency/prize_create_requires_category_tabulated
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "prize_purse_cents": 100000,
          "entries": [{"title": "E1", "sheets": [(9, 9, 9)]}]}],
        prize_budget_cents=100000, lock=True, tabulate=False,
    )
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]

    resp_blocked = api.create_prize_award(
        create_prize_award_payload(category["id"], 1), TR1
    )
    validate_error(resp_blocked, ApiErrorId.ERR_CATEGORY_NOT_TABULATED)

    fx.tabulate_category(category["id"])
    resp_ok = api.create_prize_award(
        create_prize_award_payload(category["id"], 1), TR1
    )
    award = validate_success(resp_ok, 201)
    assert_prize_award(award)
    assert award["entry_id"] == entry["id"]
    assert award["value_cents"] == 50000
    assert award["status"] == "PENDING"


def test_prize_create_rejected_while_category_draft(api):
    """PRD §3.7: "Once a category is `TABULATED`, a `Treasurer` may create a `PrizeAward` for one of its ranks by supplying `category_id` and a `rank` between 1 and 3 inclusive. Creating against a category not yet `TABULATED` is rejected with `ERR_CATEGORY_NOT_TABULATED`."

    The same gate fires while the category is still DRAFT (contest in SETUP).

    Design: Difficulty/cross_entity_state_dependency/prize_create_requires_category_tabulated
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"], prize_purse_cents=100000)
    resp = api.create_prize_award(
        create_prize_award_payload(category["id"], 1), TR1
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_TABULATED)


def test_placement_not_found_for_missing_rank(api):
    """PRD §3.7: "The entry being awarded is selected automatically: the `PLACED` entry of the category whose `placement_rank` equals the requested `rank`, with an empty result rejected as `ERR_PLACEMENT_NOT_FOUND`."

    Only one entry was PLACED, so rank 3 has no winner.

    Design: Corner/validations/placement_not_found_for_missing_rank
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=100000, prize_budget_cents=100000,
        entry_sheets=[[(9, 9, 9)]],
    )
    category = scenario["categories"][0]
    resp = api.create_prize_award(
        create_prize_award_payload(category["id"], 3), TR1
    )
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_FOUND)


# ---------------------------------------------------------------------------
# Budget reservation, boundary, and conservation
# ---------------------------------------------------------------------------

def test_prize_budget_exceeded(api):
    """PRD §3.7: "First, the award reserves budget: `budget_reserved_cents` increases by `value_cents`, and if the new total would exceed the contest's `prize_budget_cents`, the request is rejected with `ERR_PRIZE_BUDGET_EXCEEDED` (HTTP 422)."

    Rank-1 value 50000 against a 40000 budget.

    Design: Corner/validations/prize_budget_exceeded_returns_422
    """
    scenario = _tabulated_with_two_placed(
        prize_purse_cents=100000, prize_budget_cents=40000
    )
    category = scenario["categories"][0]
    resp = api.create_prize_award(
        create_prize_award_payload(category["id"], 1), TR1
    )
    validate_error(resp, ApiErrorId.ERR_PRIZE_BUDGET_EXCEEDED)


def test_prize_budget_create_revoke_conservation(api):
    """PRD §3.1: "The invariant `prize_budget_cents == budget_reserved_cents + budget_available_cents` holds at all times."
    PRD §3.7: "Revocation is the exit in the other direction: a `ContestLead` may revoke an award in `PENDING` or `APPROVED`, moving it to `REVOKED` and restoring budget by subtracting `value_cents` from `budget_reserved_cents` so the budget invariant of §3.1 holds."

    create(50000) + approve + revoke leaves the budget exactly unchanged.

    Design: Difficulty/compensating_invariant/prize_budget_award_revoke_conservation
    """
    scenario = _tabulated_with_two_placed()
    contest = scenario["contest"]
    category = scenario["categories"][0]

    award = fx.create_award(category["id"], 1, creator_id="tr_1")
    assert award["value_cents"] == 50000

    mid = fx.get_contest(contest["id"])
    assert mid["budget_reserved_cents"] == 50000
    assert mid["budget_available_cents"] == 50000
    assert_budget_invariant(mid)

    fx.approve_award(award["id"], approver_id="tr_2")
    revoked = validate_success(api.revoke_prize_award(award["id"], LEAD))
    assert revoked["status"] == "REVOKED"

    after = fx.get_contest(contest["id"])
    assert after["budget_reserved_cents"] == 0
    assert after["budget_available_cents"] == 100000
    assert_budget_invariant(after)


def test_pending_award_revoke_restores_budget(api):
    """PRD §3.7: "Revocation is the exit in the other direction: a `ContestLead` may revoke an award in `PENDING` or `APPROVED`, moving it to `REVOKED` and restoring budget by subtracting `value_cents` from `budget_reserved_cents` so the budget invariant of §3.1 holds."
    PRD §3.1: "Alongside `prize_budget_cents`, every contest exposes two computed budget fields: `budget_reserved_cents`, the sum of `value_cents` over the contest's `PrizeAward` records whose status is `PENDING`, `APPROVED`, `DISBURSED`, or `TAX_REPORTED`; and `budget_available_cents`, the difference between `prize_budget_cents` and `budget_reserved_cents`."

    A PENDING award (never approved) revokes and restores budget.

    Design: Difficulty/compensating_invariant/prize_budget_award_revoke_conservation
    """
    scenario = _tabulated_with_two_placed()
    contest = scenario["contest"]
    category = scenario["categories"][0]

    award = fx.create_award(category["id"], 2, creator_id="tr_1")
    assert award["value_cents"] == 30000
    mid = fx.get_contest(contest["id"])
    assert mid["budget_reserved_cents"] == 30000
    assert mid["budget_available_cents"] == 70000

    revoked = validate_success(api.revoke_prize_award(award["id"], LEAD))
    assert revoked["status"] == "REVOKED"

    after = fx.get_contest(contest["id"])
    assert after["budget_reserved_cents"] == 0
    assert after["budget_available_cents"] == 100000
    assert_budget_invariant(after)


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------

def test_sod_creator_cannot_approve_own_award(api):
    """PRD §3.7: "Approval by a `Treasurer` moves it to `APPROVED` and writes the approver's `X-User-ID` into `approved_by_user_id`, but segregation of duties forbids the maker from checking their own work: if the caller's `X-User-ID` equals the award's `created_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/sod_creator_cannot_approve_own_award
    """
    scenario = _tabulated_with_two_placed()
    category = scenario["categories"][0]
    award = fx.create_award(category["id"], 1, creator_id="tr_1")

    resp_self = api.approve_prize_award(award["id"], make_treasurer_headers("tr_1"))
    validate_error(resp_self, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert fx.get_prize_award(award["id"])["status"] == "PENDING"

    approved = fx.approve_award(award["id"], approver_id="tr_2")
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "tr_2"


# ---------------------------------------------------------------------------
# Disburse withholding variants
# ---------------------------------------------------------------------------

def test_payout_with_w9_vs_backup_withholding(api):
    """PRD §3.7: "When `tax_form_received` is true, `withheld_cents` is set to 0 and `net_payout_cents` equals the full `value_cents`. When `tax_form_received` is false, backup withholding applies: `withheld_cents` is the `value_cents` multiplied by 0.24, rounded half-up to integer cents, and `net_payout_cents` is the `value_cents` minus `withheld_cents`."

    Purse 100000 -> rank1 50000 (W-9: 0 / 50000), rank2 30000
    (backup: 7200 / 22800).

    Design: Difficulty/dual_variant_calc/prize_payout_with_w9_vs_backup_withholding
    """
    scenario = _tabulated_with_two_placed()
    category = scenario["categories"][0]

    aw1 = fx.create_award(category["id"], 1, creator_id="tr_1")
    assert aw1["value_cents"] == 50000
    assert aw1["tax_reportable"] is False
    fx.approve_award(aw1["id"], approver_id="tr_2")
    disbursed1 = fx.disburse_award(aw1["id"], tax_form_received=True)
    assert disbursed1["status"] == "DISBURSED"
    assert disbursed1["withheld_cents"] == 0
    assert disbursed1["net_payout_cents"] == 50000
    assert disbursed1["tax_form_received"] is True

    aw2 = fx.create_award(category["id"], 2, creator_id="tr_1")
    assert aw2["value_cents"] == 30000
    fx.approve_award(aw2["id"], approver_id="tr_2")
    disbursed2 = fx.disburse_award(aw2["id"], tax_form_received=False)
    assert disbursed2["status"] == "DISBURSED"
    assert disbursed2["withheld_cents"] == 7200
    assert disbursed2["net_payout_cents"] == 22800


def test_payout_withholding_rounds_half_up(api):
    """PRD §3.7: "When `tax_form_received` is false, backup withholding applies: `withheld_cents` is the `value_cents` multiplied by 0.24, rounded half-up to integer cents, and `net_payout_cents` is the `value_cents` minus `withheld_cents`."
    PRD §2.5: "Wherever a division or rate multiplication would produce a fraction of a cent (the purse split, backup withholding), the result is rounded to integer cents using the round-half-up method."

    Purse 66666 -> rank1 value 33333; withholding 7999.92 rounds to 8000,
    net 25333.

    Design: Difficulty/dual_variant_calc/prize_payout_with_w9_vs_backup_withholding
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=66666, prize_budget_cents=100000,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )
    category = scenario["categories"][0]
    aw1 = fx.create_award(category["id"], 1, creator_id="tr_1")
    assert aw1["value_cents"] == 33333
    fx.approve_award(aw1["id"], approver_id="tr_2")
    disbursed = fx.disburse_award(aw1["id"], tax_form_received=False)
    assert disbursed["withheld_cents"] == 8000
    assert disbursed["net_payout_cents"] == 25333


# ---------------------------------------------------------------------------
# Tax-reportability boundary (inclusive 60000)
# ---------------------------------------------------------------------------

def test_prize_exactly_60000_is_tax_reportable(api):
    """PRD §3.7: "Second, tax flagging: `tax_reportable` is computed as whether `value_cents` is greater than or equal to 60000 cents — the boundary is inclusive, so a prize of exactly 60000 is reportable."

    Purse 120000 -> rank1 exactly 60000 (reportable), rank2 36000 (not).

    Design: Difficulty/boundary_precision_check/prize_exactly_600_dollars_taxable
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=120000, prize_budget_cents=200000,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )
    category = scenario["categories"][0]

    aw1 = fx.create_award(category["id"], 1, creator_id="tr_1")
    assert aw1["value_cents"] == 60000
    assert aw1["tax_reportable"] is True

    aw2 = fx.create_award(category["id"], 2, creator_id="tr_1")
    assert aw2["value_cents"] == 36000
    assert aw2["tax_reportable"] is False


def test_subthreshold_award_can_never_be_tax_reported(api):
    """PRD §3.7: "A `DISBURSED` award may be marked `TAX_REPORTED` once its 1099 has been filed. Two preconditions guard that step: the award's `tax_reportable` must be true (sub-threshold prizes are never reported, and the attempt is rejected with `ERR_INVALID_STATE`), and `tax_form_received` must be true — a 1099 cannot be filed without a W-9, and the attempt is rejected with `ERR_TAX_FORM_REQUIRED`."

    A disbursed sub-threshold award (36000, W-9 on file) still cannot be
    marked TAX_REPORTED because the tax_reportable flag is false.

    Design: Difficulty/boundary_precision_check/prize_exactly_600_dollars_taxable
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=120000, prize_budget_cents=200000,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )
    category = scenario["categories"][0]
    aw2 = fx.create_award(category["id"], 2, creator_id="tr_1")
    fx.approve_award(aw2["id"], approver_id="tr_2")
    disbursed = fx.disburse_award(aw2["id"], tax_form_received=True)
    assert disbursed["tax_reportable"] is False
    assert disbursed["tax_form_received"] is True

    resp = api.mark_tax_reported(aw2["id"], make_treasurer_headers("tr_2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_prize_award(aw2["id"])["status"] == "DISBURSED"


# ---------------------------------------------------------------------------
# Tax reporting gate and summary
# ---------------------------------------------------------------------------

def test_tax_report_requires_w9(api):
    """PRD §3.7: "A `DISBURSED` award may be marked `TAX_REPORTED` once its 1099 has been filed. Two preconditions guard that step: the award's `tax_reportable` must be true (sub-threshold prizes are never reported, and the attempt is rejected with `ERR_INVALID_STATE`), and `tax_form_received` must be true — a 1099 cannot be filed without a W-9, and the attempt is rejected with `ERR_TAX_FORM_REQUIRED`."

    A reportable 60000 award disbursed under backup withholding
    (withheld 14400) can never be marked TAX_REPORTED.

    Design: Corner/validations/tax_report_without_w9_returns_409
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=120000, prize_budget_cents=200000,
        entry_sheets=[[(9, 9, 9)]],
    )
    category = scenario["categories"][0]
    award = fx.create_award(category["id"], 1, creator_id="tr_1")
    fx.approve_award(award["id"], approver_id="tr_2")
    disbursed = fx.disburse_award(award["id"], tax_form_received=False)
    assert disbursed["withheld_cents"] == 14400

    resp = api.mark_tax_reported(award["id"], make_treasurer_headers("tr_2"))
    validate_error(resp, ApiErrorId.ERR_TAX_FORM_REQUIRED)
    assert fx.get_prize_award(award["id"])["status"] == "DISBURSED"


def test_tax_summary_input_set_and_totals(api):
    """PRD §3.7: "It aggregates only the contest's awards in `DISBURSED` or `TAX_REPORTED` — `PENDING`, `APPROVED`, and `REVOKED` are excluded because that money has not left (or will never leave) the building — and reports `total_prize_value_cents` as the sum of `value_cents`, `total_withheld_cents` as the sum of the per-award `withheld_cents` exactly as rounded at disburse time with no re-rounding at aggregation, `reportable_award_count` as the number of included awards whose `tax_reportable` is true, and `disbursed_award_count` as the number of awards in the input set."

    Purse 120000 -> aw1 60000 (W-9, TAX_REPORTED), aw2 36000 (backup 8640,
    PENDING at first read).

    Design: Corner/calculations/tax_summary_input_set_and_totals
    """
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=120000, prize_budget_cents=200000,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )
    contest = scenario["contest"]
    category = scenario["categories"][0]
    aw1 = fx.create_award(category["id"], 1, creator_id="tr_1")
    aw2 = fx.create_award(category["id"], 2, creator_id="tr_1")

    fx.approve_award(aw1["id"], approver_id="tr_2")
    fx.disburse_award(aw1["id"], tax_form_received=True)
    reported = validate_success(
        api.mark_tax_reported(aw1["id"], make_treasurer_headers("tr_2"))
    )
    assert reported["status"] == "TAX_REPORTED"

    # aw2 is still PENDING: invisible to the summary.
    summary1 = validate_success(api.get_tax_summary(contest["id"], TR1))
    assert summary1["total_prize_value_cents"] == 60000
    assert summary1["total_withheld_cents"] == 0
    assert summary1["reportable_award_count"] == 1
    assert summary1["disbursed_award_count"] == 1

    fx.approve_award(aw2["id"], approver_id="tr_2")
    disbursed2 = fx.disburse_award(aw2["id"], tax_form_received=False)
    assert disbursed2["withheld_cents"] == 8640

    summary2 = validate_success(api.get_tax_summary(contest["id"], TR1))
    assert summary2["total_prize_value_cents"] == 96000
    assert summary2["total_withheld_cents"] == 8640
    assert summary2["disbursed_award_count"] == 2
