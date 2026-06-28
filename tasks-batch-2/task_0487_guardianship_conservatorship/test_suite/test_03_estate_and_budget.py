"""Inventory funding of the restricted account, and the budget approval gate.

Difficulty: inventory-approve depends on an OPEN restricted account existing.
Corner: inventory funds the account, budget supersession, OCC budget-approve.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_account_balance_invariant,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty: inventory approve depends on an OPEN restricted account
# ===========================================================================
def test_inventory_approve_rejected_without_open_account(api):
    """PRD 3.4: "A judge then approves a FILED inventory, moving it to APPROVED;
    approval requires an OPEN restricted account to exist on the case (else
    ERR_NO_RESTRICTED_ACCOUNT)."

    Design: Difficulty/cross_entity_state_dependency/cesd_inventory_approve_requires_open_account
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP")
    inv = get_success_data(
        api.create_inventory(
            F.create_inventory_payload(ctx["case_id"], liquid_assets_cents=4_000_000),
            fx.make_fiduciary_headers(ctx["fiduciary_id"]),
        )
    )
    api.file_inventory(inv["id"], fx.make_fiduciary_headers(ctx["fiduciary_id"]))
    validate_error(
        api.approve_inventory(inv["id"], fx.JUDGE),
        ApiErrorId.ERR_NO_RESTRICTED_ACCOUNT,
    )


def test_inventory_approve_succeeds_after_account_opened(api):
    """PRD 3.4: "On approval, the inventory's liquid_assets_cents is credited into
    the account's principal_balance_cents, and the available balance is recomputed
    accordingly."

    Design: Difficulty/cross_entity_state_dependency/cesd_inventory_approve_requires_open_account
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP")
    inv = get_success_data(
        api.create_inventory(
            F.create_inventory_payload(ctx["case_id"], liquid_assets_cents=4_000_000),
            fx.make_fiduciary_headers(ctx["fiduciary_id"]),
        )
    )
    api.file_inventory(inv["id"], fx.make_fiduciary_headers(ctx["fiduciary_id"]))
    account = fx.open_restricted_account(ctx["case_id"], ctx["fiduciary_id"])
    approved = validate_success(api.approve_inventory(inv["id"], fx.JUDGE))
    assert approved["status"] == "APPROVED"
    acct = get_success_data(api.get_restricted_account(account["id"], fx.JUDGE))
    assert acct["principal_balance_cents"] == 4_000_000


# ===========================================================================
# Corner: inventory approve funds the account (ledger sync)
# ===========================================================================
def test_inventory_approve_funds_account(api):
    """PRD 3.4: "On approval, the inventory's liquid_assets_cents is credited into
    the account's principal_balance_cents, and the available balance is recomputed
    accordingly."

    Design: Corner/state_machines/ledger_sync_inventory_approve_funds_account
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP")
    account = fx.open_restricted_account(ctx["case_id"], ctx["fiduciary_id"])
    fx.fund_account_via_inventory(ctx["case_id"], ctx["fiduciary_id"], 3_000_000)
    acct = get_success_data(api.get_restricted_account(account["id"], fx.JUDGE))
    assert acct["principal_balance_cents"] == 3_000_000
    assert acct["available_balance_cents"] == 3_000_000
    assert_account_balance_invariant(acct)


def test_inventory_file_rejected_when_case_not_active(api):
    """PRD 3.4: "The fiduciary files the inventory, moving it from DRAFT to FILED,
    which requires the inventory to be in DRAFT (else ERR_INVALID_STATE) and the
    case to be ACTIVE (else ERR_CASE_NOT_ACTIVE)."

    Design: Corner/errors/error_case_not_active_inventory_file_in_draft_case
    """
    person = fx.create_person(liquid_estate_cents=8_000_000)
    case = fx.create_case(person["id"], case_type="CONSERVATORSHIP")
    # Inventory drafted by an arbitrary fiduciary id; the case is still DRAFT.
    inv = get_success_data(
        api.create_inventory(
            F.create_inventory_payload(case["id"], liquid_assets_cents=1_000_000),
            fx.make_fiduciary_headers("any-fid"),
        )
    )
    validate_error(
        api.file_inventory(inv["id"], fx.make_fiduciary_headers("any-fid")),
        ApiErrorId.ERR_CASE_NOT_ACTIVE,
    )


# ===========================================================================
# Budget approval gate + OCC
# ===========================================================================
def test_budget_approve_supersedes_prior_same_year(api):
    """PRD 3.5: "A successful approval moves the budget to APPROVED, supersedes any
    other APPROVED budget on the same case for the same period_year to SUPERSEDED
    (only one approved budget governs a given year), and increments the case's
    version by one."

    Design: Corner/state_machines/budget_approve_supersedes_prior_same_year
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    b1 = fx.create_approved_budget(ctx["case_id"], fid, period_year=2026, care_cap_cents=1_000_000)

    # Second 2026 budget submitted then approved.
    b2 = get_success_data(
        api.create_budget(
            F.create_budget_payload(ctx["case_id"], period_year=2026, care_cap_cents=2_000_000),
            fx.make_fiduciary_headers(fid),
        )
    )
    api.submit_budget(b2["id"], fx.make_fiduciary_headers(fid))
    cv = fx.current_case_version(ctx["case_id"])
    b2_approved = validate_success(
        api.approve_budget(b2["id"], F.approve_budget_payload(cv), fx.JUDGE)
    )
    assert b2_approved["status"] == "APPROVED"
    b1_after = get_success_data(api.get_budget(b1["id"], fx.JUDGE))
    assert b1_after["status"] == "SUPERSEDED"


def test_budget_approve_correct_version_increments_case_version(api):
    """PRD 2.8: "Both of these write operations, when they succeed, increment the
    case's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_budget_approve_correct_version_succeeds
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    budget = get_success_data(
        api.create_budget(
            F.create_budget_payload(ctx["case_id"], period_year=2026, care_cap_cents=1_000_000),
            fx.make_fiduciary_headers(fid),
        )
    )
    api.submit_budget(budget["id"], fx.make_fiduciary_headers(fid))
    cv_before = fx.current_case_version(ctx["case_id"])
    approved = validate_success(
        api.approve_budget(budget["id"], F.approve_budget_payload(cv_before), fx.JUDGE)
    )
    assert approved["status"] == "APPROVED"
    cv_after = fx.current_case_version(ctx["case_id"])
    assert cv_after == cv_before + 1
