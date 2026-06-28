"""Vouchers (equity conservation, OCC, expiry, cancel) and collection/repair.

Translates Difficulty queue (A) instances `compensating_invariant /
voucher_issue_redeem_conserves_total_system_equity` and `non_linear_state_machine
/ asset_condition_cycle...`; and Corner queue (B) instances from `state_machines`,
`validations`, and `cross_cutting_complexity_layers` (voucher OCC).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_voucher,
    assert_location,
    assert_asset,
    assert_repair_job,
    make_pool_admin_headers,
    make_pool_operator_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Difficulty: voucher issue+redeem conserves total system equity
# --------------------------------------------------------------------------
def test_voucher_issue_debits_issuer_equity(api):
    """PRD §3.7: "the from_location_id's equity_balance is reduced by quantity,
    that location's version is incremented by one, and its equity_status is
    recomputed."

    Design: Difficulty/compensating_invariant/voucher_issue_redeem_conserves_total_system_equity
    """
    ctx = H.setup_voucher_outstanding(from_equity=10, quantity=4)
    la = validate_success(api.get_location(ctx["la"]["id"], OPERATOR))
    assert_location(la)
    assert la["equity_balance"] == 6, f"issuer should be 6, got {la['equity_balance']}"


def test_voucher_redeem_credits_redeemer_equity(api):
    """PRD §3.7: "On redemption the redeem location's equity_balance increases by
    quantity (the redeemer assumes the obligation) and its equity_status is
    recomputed. Issue and redeem form a conserving pair: the quantity debited from
    the issuing location on issue is the same quantity credited to the redeeming
    location on redeem, so total system equity is unchanged."

    Design: Difficulty/compensating_invariant/voucher_issue_redeem_conserves_total_system_equity
    """
    ctx = H.setup_voucher_outstanding(from_equity=10, quantity=4)
    redeemed = validate_success(
        api.redeem_voucher(
            ctx["voucher"]["id"], {"redeem_location_id": ctx["lb"]["id"]}, OPERATOR
        )
    )
    assert_voucher(redeemed)
    assert redeemed["status"] == "REDEEMED"
    la = validate_success(api.get_location(ctx["la"]["id"], OPERATOR))
    lb = validate_success(api.get_location(ctx["lb"]["id"], OPERATOR))
    assert la["equity_balance"] == 6, f"issuer should stay 6, got {la['equity_balance']}"
    assert lb["equity_balance"] == 4, f"redeemer should be 4, got {lb['equity_balance']}"


# --------------------------------------------------------------------------
# Corner: voucher OCC stale issue
# --------------------------------------------------------------------------
def test_occ_stale_location_version_on_voucher_issue_rejected(api):
    """PRD §2.9: "because the issue debits that location's equity and thus
    supersedes its prior equity view, a mismatch with the location's current
    version is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_location_version_on_voucher_issue_rejected
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    acct1 = H.create_account(legal_name="Acct1", role_type="MANUFACTURER")
    acct2 = H.create_account(legal_name="Acct2", role_type="RETAILER")
    stock = H.create_location(acct1["id"], name="Stock")
    la = H.create_location(acct1["id"], name="LA")
    H.issue_assets_into_location(asset_type["id"], stock["id"], la["id"], 5)
    stale_ver = H.location_version(la["id"])
    # First voucher issue bumps LA.version.
    H.issue_voucher(la["id"], acct2["id"], asset_type["id"], 1)
    resp = api.create_voucher(
        {
            "from_location_id": la["id"],
            "to_account_id": acct2["id"],
            "asset_type_id": asset_type["id"],
            "quantity": 1,
            "expected_from_location_version": stale_ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# --------------------------------------------------------------------------
# Corner: voucher redeem after expiry
# --------------------------------------------------------------------------
def test_voucher_redeem_after_expiry_returns_voucher_expired(api):
    """PRD §3.7: "the voucher must not be past expiry, meaning issued_at plus the
    policy's voucher_expiry_days must be strictly after the current logical clock
    (otherwise ERR_VOUCHER_EXPIRED)."

    Design: Corner/state_machines/voucher_redeem_after_expiry_returns_voucher_expired
    """
    policy = H.create_policy(voucher_expiry_days=90)
    asset_type = H.create_asset_type()
    acct1 = H.create_account(legal_name="Acct1", role_type="MANUFACTURER")
    acct2 = H.create_account(legal_name="Acct2", role_type="RETAILER")
    la = H.create_location(acct1["id"], name="LA")
    lb = H.create_location(acct2["id"], name="LB")
    H.set_clock("2026-06-01T00:00:00Z")
    voucher = H.issue_voucher(la["id"], acct2["id"], asset_type["id"], 2)
    H.set_clock("2026-10-01T00:00:00Z")  # past 90-day expiry
    resp = api.redeem_voucher(voucher["id"], {"redeem_location_id": lb["id"]}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_VOUCHER_EXPIRED.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: voucher redeem location not belonging to to_account
# --------------------------------------------------------------------------
def test_voucher_redeem_location_not_belonging_to_account_rejected(api):
    """PRD §3.7: "the supplied redeem_location_id must belong to the to_account_id
    and have status OPEN — a location that does not belong to that account is
    rejected with ERR_VOUCHER_REDEEM_LOCATION_INVALID".

    Design: Corner/validations/voucher_redeem_location_not_belonging_to_account_rejected
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    acct1 = H.create_account(legal_name="Acct1", role_type="MANUFACTURER")
    acct2 = H.create_account(legal_name="Acct2", role_type="RETAILER")
    acct3 = H.create_account(legal_name="Acct3", role_type="DISTRIBUTOR")
    la = H.create_location(acct1["id"], name="LA")
    l3 = H.create_location(acct3["id"], name="L3")
    H.set_clock("2026-06-01T00:00:00Z")
    voucher = H.issue_voucher(la["id"], acct2["id"], asset_type["id"], 1)
    # redeem_location belongs to acct3, not the voucher's to_account acct2.
    resp = api.redeem_voucher(voucher["id"], {"redeem_location_id": l3["id"]}, OPERATOR)
    validate_error(
        resp, ApiErrorId.ERR_VOUCHER_REDEEM_LOCATION_INVALID.value, expected_status=409
    )


# --------------------------------------------------------------------------
# Corner: voucher cancel restores issuer equity
# --------------------------------------------------------------------------
def test_voucher_cancel_restores_issuer_equity(api):
    """PRD §3.7: "A PoolAdmin may also cancel an outstanding voucher to CANCELLED,
    which likewise adds quantity back to the issuer's equity_balance and recomputes
    its equity_status."

    Design: Corner/state_machines/voucher_cancel_restores_issuer_equity
    """
    ctx = H.setup_voucher_outstanding(from_equity=5, quantity=3)
    # After issue, LA equity is 5 - 3 = 2.
    cancelled = validate_success(api.cancel_voucher(ctx["voucher"]["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    la = validate_success(api.get_location(ctx["la"]["id"], OPERATOR))
    assert la["equity_balance"] == 5, f"issuer should restore to 5, got {la['equity_balance']}"


# --------------------------------------------------------------------------
# Difficulty: asset cyclic condition AVAILABLE -> DAMAGED -> IN_REPAIR -> AVAILABLE
# --------------------------------------------------------------------------
def test_asset_condition_cycle_available_through_repair_back_to_available(api):
    """PRD §3.2: "A DAMAGED asset enters IN_REPAIR when a repair job opens over
    it, and from IN_REPAIR it either returns AVAILABLE on repair completion or goes
    to LOST on scrap." PRD §3.8: "Completing a repair advances it OPEN to
    COMPLETED, returning each asset IN_REPAIR to AVAILABLE at the source collection
    request's origin location (the repair depot) and incrementing that location's
    physical_balance."

    Design: Difficulty/non_linear_state_machine/asset_condition_cycle_available_through_repair_back_to_available
    """
    ctx = H.setup_repair_job_open(repair_cost_cents=1500, damaged=True)
    validate_success(api.complete_repair_job(ctx["repair_job"]["id"], OPERATOR))
    asset = validate_success(api.get_asset(ctx["asset"]["id"], OPERATOR))
    assert_asset(asset)
    assert asset["condition"] == "AVAILABLE", \
        f"asset should cycle back to AVAILABLE, got {asset['condition']}"
    assert asset["current_location_id"] == ctx["depot"]["id"], \
        "asset should return to the depot (collection origin) location"


def test_asset_condition_cycle_returns_to_start_state(api):
    """PRD §3.2: "An asset's condition moves through a cyclic state machine
    spanning AVAILABLE, ON_HIRE, IN_TRANSIT, DAMAGED, IN_REPAIR, and LOST. ...
    Reporting damage takes an asset to DAMAGED — from ON_HIRE or from AVAILABLE".

    Design: Difficulty/non_linear_state_machine/asset_condition_cycle_available_through_repair_back_to_available
    """
    ctx = H.setup_repair_job_open(repair_cost_cents=1500, damaged=True)
    # Before completion the asset is IN_REPAIR (it traversed AVAILABLE->DAMAGED->IN_REPAIR).
    mid = validate_success(api.get_asset(ctx["asset"]["id"], OPERATOR))
    assert mid["condition"] == "IN_REPAIR"
    validate_success(api.complete_repair_job(ctx["repair_job"]["id"], OPERATOR))
    back = validate_success(api.get_asset(ctx["asset"]["id"], OPERATOR))
    assert back["condition"] == "AVAILABLE"


# --------------------------------------------------------------------------
# Corner: repair scrap marks assets LOST
# --------------------------------------------------------------------------
def test_repair_scrap_marks_assets_lost(api):
    """PRD §3.8: "Scrapping a repair advances it OPEN to SCRAPPED, marking each
    asset IN_REPAIR to LOST for permanent removal from physical_balance."

    Design: Corner/state_machines/repair_scrap_marks_assets_lost
    """
    ctx = H.setup_repair_job_open(repair_cost_cents=1000, damaged=True)
    rj = validate_success(api.scrap_repair_job(ctx["repair_job"]["id"], OPERATOR))
    assert_repair_job(rj)
    assert rj["status"] == "SCRAPPED"
    asset = validate_success(api.get_asset(ctx["asset"]["id"], OPERATOR))
    assert asset["condition"] == "LOST"


# --------------------------------------------------------------------------
# Corner: repair job on non-damaged asset
# --------------------------------------------------------------------------
def test_repair_job_on_non_damaged_asset_returns_not_damaged(api):
    """PRD §3.8: "Each listed asset must be DAMAGED at job creation (otherwise
    ERR_ASSET_NOT_DAMAGED), and opening the job moves each asset DAMAGED to
    IN_REPAIR."

    Design: Corner/validations/repair_job_on_non_damaged_asset_returns_not_damaged
    """
    ctx = H.setup_repair_job_open(damaged=False)
    resp = api.create_repair_job(
        {
            "collection_request_id": ctx["collection"]["id"],
            "asset_ids": [ctx["asset"]["id"]],
            "repair_cost_cents": 100,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_DAMAGED.value, expected_status=409)
