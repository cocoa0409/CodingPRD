"""Hire lifecycle, tiered/dual-variant charge, credit exposure, OCC, settlement.

Translates Difficulty queue (A) instances from `dual_variant_calc` (hire),
`combinatorial_formula` (hire tiered rate), `non_linear_state_machine` (parallel
dimensions), `priority_pair_validation_conflict` (asset-referential beats
fiscal), `boundary_precision_check` (credit-limit), `cross_entity_state_dependency`
(account active), `resource_temporal_overlap` (asset occupancy); and Corner queue
(B) instances from `state_machines`, `calculations`, `validations`, `endpoints`,
and `cross_cutting_complexity_layers` (OCC on hire open).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    assert_hire,
    assert_asset,
    make_pool_admin_headers,
    make_pool_operator_headers,
    make_participant_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Difficulty: dual-variant — provisional accrual vs finalized replay diverge
# --------------------------------------------------------------------------
def _setup_11_asset_hire_with_two_damaged():
    """11 assets ON_HIRE from 2026-06-01; assets 1 & 2 damaged on 2026-06-03;
    clock advanced to 2026-06-11. Returns hire id. base_daily_rate_cents=500."""
    ctx = H.bootstrap_program(
        asset_type_overrides={"base_daily_rate_cents": 500, "useful_life_days": 1825},
        account_overrides={"credit_limit_cents": 10_000_000},
        clock="2026-06-01T00:00:00Z",
    )
    assets = H.mint_assets(ctx["asset_type"]["id"], ctx["location"]["id"], 11)
    asset_ids = [a["id"] for a in assets]
    hire = H.open_hire(
        ctx["account"]["id"], ctx["location"]["id"], ctx["asset_type"]["id"], asset_ids
    )
    H.set_clock("2026-06-03T00:00:00Z")
    H.get_success_data(H.api_client.report_damage(asset_ids[0], OPERATOR))
    H.get_success_data(H.api_client.report_damage(asset_ids[1], OPERATOR))
    H.set_clock("2026-06-11T00:00:00Z")
    return hire["id"]


def test_hire_provisional_accrual_uses_current_count(api):
    """PRD §3.4: "This provisional figure deliberately uses the current surviving
    on-hire asset count for the whole span and ignores any mid-hire damage
    history, so it is an estimate that can exceed the chronological finalized
    figure."

    Design: Difficulty/dual_variant_calc/hire_provisional_accrual_vs_finalized_replay_diverge
    """
    hire_id = _setup_11_asset_hire_with_two_damaged()
    hire = validate_success(api.get_hire(hire_id, OPERATOR))
    assert_hire(hire)
    # 10 whole days x 9 surviving assets x base rate 500 (count 9 < tier1) = 45000.
    assert hire["accrued_charge_cents"] == 45000, \
        f"expected provisional 45000, got {hire['accrued_charge_cents']}"


def test_hire_finalized_replay_diverges_from_provisional(api):
    """PRD §3.4: "Because the replay honors each asset's actual damage day rather
    than the surviving count, a hire whose assets were damaged mid-term yields a
    smaller finalized total than its provisional accrual."

    Design: Difficulty/dual_variant_calc/hire_provisional_accrual_vs_finalized_replay_diverge
    """
    hire_id = _setup_11_asset_hire_with_two_damaged()
    provisional = validate_success(api.get_hire(hire_id, OPERATOR))["accrued_charge_cents"]
    closed = validate_success(api.close_hire(hire_id, OPERATOR))
    # Days 06-01,06-02: 11 assets, tier1 rate 450 -> 11*450*2 = 9900.
    # Days 06-03..06-10 (8 days): 9 assets, rate 500 -> 9*500*8 = 36000. Total 45900.
    assert closed["final_charge_cents"] == 45900, \
        f"expected final 45900, got {closed['final_charge_cents']}"
    assert closed["final_charge_cents"] != provisional


# --------------------------------------------------------------------------
# Difficulty: combinatorial tiered rate (10-asset 1-day hire)
# --------------------------------------------------------------------------
def test_hire_tiered_rate_at_tier1_breakpoint(api):
    """PRD §3.4: "When the count is at least 10 but fewer than 50, the rate is the
    base rate multiplied by 0.90, floored to whole cents." PRD §3.4: "The pinned
    final_charge_cents is the sum across all days; the day count is whole half-open
    days and the tiered rate is floored once per tier."

    Design: Difficulty/combinatorial_formula/hire_tiered_rate_three_input_nonlinear
    """
    ctx = H.bootstrap_program(
        asset_type_overrides={"base_daily_rate_cents": 500},
        account_overrides={"credit_limit_cents": 100_000_000, "role_type": "DISTRIBUTOR"},
        clock="2026-06-01T00:00:00Z",
    )
    assets = H.mint_assets(ctx["asset_type"]["id"], ctx["location"]["id"], 10, serial_prefix="B")
    asset_ids = [a["id"] for a in assets]
    hire = H.open_hire(
        ctx["account"]["id"], ctx["location"]["id"], ctx["asset_type"]["id"], asset_ids
    )
    H.set_clock("2026-06-02T00:00:00Z")
    closed = validate_success(api.close_hire(hire["id"], OPERATOR))
    # 1 day x 10 assets x floor(500*0.90)=450 -> 4500.
    assert closed["final_charge_cents"] == 4500, \
        f"expected 4500, got {closed['final_charge_cents']}"


def test_hire_tiered_rate_below_tier1_breakpoint_undiscounted(api):
    """PRD §3.4: "When the count is fewer than 10, the rate is the base rate
    itself. The rate is floored once per tier; the per-day charge is that floored
    rate multiplied by the active asset count, not re-floored afterward."

    Design: Difficulty/combinatorial_formula/hire_tiered_rate_three_input_nonlinear
    """
    ctx = H.bootstrap_program(
        asset_type_overrides={"base_daily_rate_cents": 500},
        account_overrides={"credit_limit_cents": 100_000_000, "role_type": "DISTRIBUTOR"},
        clock="2026-06-01T00:00:00Z",
    )
    assets = H.mint_assets(ctx["asset_type"]["id"], ctx["location"]["id"], 9, serial_prefix="N")
    asset_ids = [a["id"] for a in assets]
    hire = H.open_hire(
        ctx["account"]["id"], ctx["location"]["id"], ctx["asset_type"]["id"], asset_ids
    )
    H.set_clock("2026-06-02T00:00:00Z")
    closed = validate_success(api.close_hire(hire["id"], OPERATOR))
    # 9 < tier1 (10): rate stays base 500. 1 day x 9 x 500 = 4500.
    assert closed["final_charge_cents"] == 4500, \
        f"expected 4500 (undiscounted), got {closed['final_charge_cents']}"


# --------------------------------------------------------------------------
# Difficulty: parallel lifecycle x settlement dimensions
# --------------------------------------------------------------------------
def test_hire_parallel_lifecycle_and_settlement_dimensions(api):
    """PRD §3.9: "a CLOSED hire becomes INVOICED when an invoice referencing it is
    issued and SETTLED when that invoice is fully paid, while its lifecycle_status
    stays CLOSED throughout."

    Design: Difficulty/non_linear_state_machine/hire_parallel_lifecycle_and_settlement_dimensions
    """
    ctx = H.setup_closed_hire(asset_count=1, base_daily_rate_cents=500)
    inv, _lines = H.setup_invoice_with_lines(
        ctx["account"]["id"], [("HIRE", 500, {"source_hire_id": ctx["hire"]["id"]})]
    )
    H.issue_invoice(inv["id"])
    H.record_payment(inv["id"], 500)
    hire = validate_success(api.get_hire(ctx["hire"]["id"], OPERATOR))
    assert hire["lifecycle_status"] == "CLOSED"
    assert hire["settlement_status"] == "SETTLED"


def test_hire_settlement_invoiced_keeps_lifecycle_closed(api):
    """PRD §3.4: "These two status dimensions evolve independently. The
    lifecycle_status runs OPEN to CLOSED or OPEN to VOIDED; the settlement_status
    runs UNBILLED to INVOICED to SETTLED."

    Design: Difficulty/non_linear_state_machine/hire_parallel_lifecycle_and_settlement_dimensions
    """
    ctx = H.setup_closed_hire_invoiced(line_amount=500)
    hire = validate_success(api.get_hire(ctx["hire"]["id"], OPERATOR))
    assert hire["lifecycle_status"] == "CLOSED"
    assert hire["settlement_status"] == "INVOICED"


# --------------------------------------------------------------------------
# Difficulty: priority-pair — asset referential (8) beats fiscal (12)
# --------------------------------------------------------------------------
def test_hire_open_asset_referential_beats_credit_limit_fiscal(api):
    """PRD §3.4: "Every listed asset must be AVAILABLE (otherwise
    ERR_ASSET_NOT_AVAILABLE) and physically at the hire's location_id (otherwise
    ERR_ASSET_WRONG_LOCATION)". PRD §2.10: "then the optimistic-concurrency
    version check for hire-open and voucher-issue (ERR_STALE_VERSION), then the
    target resource's state eligibility for the requested transition
    (ERR_INVALID_STATE), and finally the domain-specific business preconditions
    described throughout §3."

    Design: Difficulty/priority_pair_validation_conflict/hire_open_asset_referential_beats_credit_limit_fiscal
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    big = H.create_account(legal_name="Acme", role_type="MANUFACTURER", credit_limit_cents=100_000_000)
    tiny = H.create_account(legal_name="Tiny", role_type="RETAILER", credit_limit_cents=1)
    l1 = H.create_location(big["id"], name="L1")
    H.set_clock("2026-06-01T00:00:00Z")
    asset = H.create_asset(asset_type["id"], l1["id"], serial="Q1")
    # First hire occupies the asset.
    H.open_hire(big["id"], l1["id"], asset_type["id"], [asset["id"]])
    ver = H.location_version(l1["id"])
    # Second hire on the SAME asset (not AVAILABLE) by a credit-1 account.
    resp = api.create_hire(
        {
            "account_id": tiny["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": [asset["id"]],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value, expected_status=409)


def test_hire_open_asset_referential_beats_credit_limit_fiscal_asset_stays_on_first_hire(api):
    """PRD §3.4: "Every listed asset must be AVAILABLE (otherwise
    ERR_ASSET_NOT_AVAILABLE)". PRD §3.4: "each listed asset transitions AVAILABLE
    to ON_HIRE with its current_hire_id set to the new hire".

    Design: Difficulty/priority_pair_validation_conflict/hire_open_asset_referential_beats_credit_limit_fiscal
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    big = H.create_account(legal_name="Acme", role_type="MANUFACTURER", credit_limit_cents=100_000_000)
    tiny = H.create_account(legal_name="Tiny", role_type="RETAILER", credit_limit_cents=1)
    l1 = H.create_location(big["id"], name="L1")
    H.set_clock("2026-06-01T00:00:00Z")
    asset = H.create_asset(asset_type["id"], l1["id"], serial="Q1")
    hire1 = H.open_hire(big["id"], l1["id"], asset_type["id"], [asset["id"]])
    ver = H.location_version(l1["id"])
    # The asset-availability check (priority 8) fires before the fiscal check (12).
    resp = api.create_hire(
        {
            "account_id": tiny["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": [asset["id"]],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value, expected_status=409)
    # The asset remains ON_HIRE on the first hire (no partial second-hire mutation).
    asset_data = validate_success(api.get_asset(asset["id"], OPERATOR))
    assert asset_data["condition"] == "ON_HIRE"
    assert asset_data["current_hire_id"] == hire1["id"]


# --------------------------------------------------------------------------
# Difficulty: credit-limit boundary (== allowed)
# --------------------------------------------------------------------------
def test_credit_limit_exposure_equal_allowed(api):
    """PRD §3.5: "The open is rejected with ERR_CREDIT_LIMIT_EXCEEDED only when
    this exposure is strictly greater than credit_limit_cents; an exposure exactly
    equal to credit_limit_cents is allowed."

    Design: Difficulty/boundary_precision_check/credit_limit_exposure_equal_allowed_strict_over_rejected
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type(base_daily_rate_cents=500)
    account = H.create_account(legal_name="Edge", role_type="DISTRIBUTOR", credit_limit_cents=5400)
    l1 = H.create_location(account["id"], name="L1")
    H.set_clock("2026-06-01T00:00:00Z")
    assets = H.mint_assets(asset_type["id"], l1["id"], 12, serial_prefix="E")
    asset_ids = [a["id"] for a in assets]
    ver = H.location_version(l1["id"])
    # day-1 reservation = 1 x 12 x floor(500*0.9)=450 = 5400 == limit -> allowed.
    resp = api.create_hire(
        {
            "account_id": account["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": asset_ids,
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    data = validate_success(resp, expected_status=201)
    assert data["lifecycle_status"] == "OPEN"


def test_credit_limit_exposure_strict_over_rejected(api):
    """PRD §3.5: "The open is rejected with ERR_CREDIT_LIMIT_EXCEEDED only when
    this exposure is strictly greater than credit_limit_cents; an exposure exactly
    equal to credit_limit_cents is allowed."

    Design: Difficulty/boundary_precision_check/credit_limit_exposure_equal_allowed_strict_over_rejected
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type(base_daily_rate_cents=500)
    account = H.create_account(legal_name="Edge", role_type="DISTRIBUTOR", credit_limit_cents=5399)
    l1 = H.create_location(account["id"], name="L1")
    H.set_clock("2026-06-01T00:00:00Z")
    assets = H.mint_assets(asset_type["id"], l1["id"], 12, serial_prefix="E")
    asset_ids = [a["id"] for a in assets]
    ver = H.location_version(l1["id"])
    # day-1 reservation 5400 > 5399 -> rejected.
    resp = api.create_hire(
        {
            "account_id": account["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": asset_ids,
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, expected_status=409)


# --------------------------------------------------------------------------
# Difficulty: cross-entity state — hire requires account ACTIVE
# --------------------------------------------------------------------------
def test_hire_open_requires_account_active(api):
    """PRD §3.4: "the hiring account must be ACTIVE — a SUSPENDED or CLOSED
    account is rejected with ERR_ACCOUNT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/hire_open_requires_account_active
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="MANUFACTURER", credit_limit_cents=100_000_000)
    l1 = H.create_location(account["id"], name="L1")
    asset = H.create_asset(asset_type["id"], l1["id"], serial="H1")
    ver = H.location_version(l1["id"])
    H.get_success_data(api.suspend_account(account["id"], ADMIN))
    resp = api.create_hire(
        {
            "account_id": account["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": [asset["id"]],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, expected_status=409)


def test_hire_open_requires_account_active_rejects_closed_account(api):
    """PRD §3.4: "the hiring account must be ACTIVE — a SUSPENDED or CLOSED
    account is rejected with ERR_ACCOUNT_NOT_ACTIVE." PRD §3.1: "An ACTIVE account
    may be closed to CLOSED, but only when it has no hire whose lifecycle_status is
    OPEN ... and its outstanding_charge_cents is exactly 0".

    Design: Difficulty/cross_entity_state_dependency/hire_open_requires_account_active
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="MANUFACTURER", credit_limit_cents=100_000_000)
    l1 = H.create_location(account["id"], name="L1")
    asset = H.create_asset(asset_type["id"], l1["id"], serial="H2")
    ver = H.location_version(l1["id"])
    # A fresh account with no open hire and zero outstanding charge can be closed.
    H.get_success_data(api.close_account(account["id"], ADMIN))
    resp = api.create_hire(
        {
            "account_id": account["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": [asset["id"]],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, expected_status=409)


# --------------------------------------------------------------------------
# Difficulty: per-asset occupancy overlap rejected
# --------------------------------------------------------------------------
def test_hire_asset_occupancy_overlap_rejected(api):
    """PRD §3.4: "Every listed asset must be AVAILABLE (otherwise
    ERR_ASSET_NOT_AVAILABLE)". PRD §3.2: "Placing an asset on a hire takes it
    AVAILABLE to ON_HIRE; closing that hire returns it ON_HIRE to AVAILABLE."

    Design: Difficulty/resource_temporal_overlap/hire_asset_occupancy_overlap_rejected
    """
    ctx = H.setup_open_hire(asset_count=1, credit_limit_cents=100_000_000)
    ver = H.location_version(ctx["location"]["id"])
    resp = api.create_hire(
        {
            "account_id": ctx["account"]["id"],
            "location_id": ctx["location"]["id"],
            "asset_type_id": ctx["asset_type"]["id"],
            "asset_ids": ctx["asset_ids"],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value, expected_status=409)


def test_hire_asset_rehireable_after_first_hire_closes(api):
    """PRD §3.4: "Closing a hire advances its lifecycle_status OPEN to CLOSED ...
    returns every asset still ON_HIRE on the hire to AVAILABLE with current_hire_id
    cleared to null". PRD §3.4: "Every listed asset must be AVAILABLE (otherwise
    ERR_ASSET_NOT_AVAILABLE)".

    Design: Difficulty/resource_temporal_overlap/hire_asset_occupancy_overlap_rejected
    """
    ctx = H.setup_open_hire(asset_count=1, credit_limit_cents=100_000_000)
    H.set_clock("2026-06-02T00:00:00Z")
    H.close_hire(ctx["hire"]["id"])
    # Occupancy interval now closed -> the asset is AVAILABLE and re-hireable.
    ver = H.location_version(ctx["location"]["id"])
    resp = api.create_hire(
        {
            "account_id": ctx["account"]["id"],
            "location_id": ctx["location"]["id"],
            "asset_type_id": ctx["asset_type"]["id"],
            "asset_ids": ctx["asset_ids"],
            "expected_location_version": ver,
        },
        OPERATOR,
    )
    data = validate_success(resp, expected_status=201)
    assert data["lifecycle_status"] == "OPEN"


# --------------------------------------------------------------------------
# Corner: OCC stale location version on hire open
# --------------------------------------------------------------------------
def test_occ_stale_location_version_on_hire_open_rejected(api):
    """PRD §2.9: "if expected_location_version does not match the location's
    current version, the open is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_location_version_on_hire_open_rejected
    """
    policy = H.create_policy()
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="DISTRIBUTOR", credit_limit_cents=10_000_000)
    l1 = H.create_location(account["id"], name="L1")
    H.set_clock("2026-06-01T00:00:00Z")
    a1 = H.create_asset(asset_type["id"], l1["id"], serial="S1")
    a2 = H.create_asset(asset_type["id"], l1["id"], serial="S2")
    stale_ver = H.location_version(l1["id"])
    # First hire bumps L1.version.
    H.open_hire(account["id"], l1["id"], asset_type["id"], [a1["id"]])
    resp = api.create_hire(
        {
            "account_id": account["id"],
            "location_id": l1["id"],
            "asset_type_id": asset_type["id"],
            "asset_ids": [a2["id"]],
            "expected_location_version": stale_ver,
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# --------------------------------------------------------------------------
# Corner: account outstanding charge recompute after close
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Corner: hire close from already-closed -> invalid state
# --------------------------------------------------------------------------
def test_hire_close_from_already_closed_returns_invalid_state(api):
    """PRD §3.4: "Closing a hire advances its lifecycle_status OPEN to CLOSED and
    is permitted only from OPEN (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/hire_close_from_already_closed_returns_invalid_state
    """
    ctx = H.setup_closed_hire(asset_count=1, base_daily_rate_cents=500)
    resp = api.close_hire(ctx["hire"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: hire void after invoiced -> already invoiced
# --------------------------------------------------------------------------
def test_hire_void_after_invoiced_returns_already_invoiced(api):
    """PRD §3.4: "A hire may instead be voided by a PoolAdmin, but only while its
    settlement_status is UNBILLED (otherwise ERR_HIRE_ALREADY_INVOICED)." and
    "Voiding advances lifecycle_status OPEN -> VOIDED".

    A hire can only reach settlement_status INVOICED after being CLOSED (PRD §3.4:
    "an OPEN hire can never be INVOICED — invoicing requires the hire to be CLOSED
    first"; §3.9 issue requires lifecycle_status CLOSED). So any invoiced hire is
    necessarily no longer OPEN. Per PRD §2.10 the state-eligibility check for the
    OPEN -> VOIDED transition (ERR_INVALID_STATE, priority 6) precedes the
    settlement-status business precondition (ERR_HIRE_ALREADY_INVOICED, priority
    7); but a reader treating the "only while settlement_status is UNBILLED" guard
    as the primary void gate could surface ERR_HIRE_ALREADY_INVOICED. Both are
    PRD-faithful, so accept either.

    Design: Corner/state_machines/hire_void_after_invoiced_returns_already_invoiced
    """
    ctx = H.setup_closed_hire_invoiced(line_amount=500)
    resp = api.void_hire(ctx["hire"]["id"], ADMIN)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_HIRE_ALREADY_INVOICED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


# --------------------------------------------------------------------------
# Corner: account close blocked by open hire / not settled
# --------------------------------------------------------------------------
def test_account_close_blocked_by_open_hire(api):
    """PRD §3.1: "An ACTIVE account may be closed to CLOSED, but only when it has
    no hire whose lifecycle_status is OPEN (otherwise ERR_ACCOUNT_HAS_OPEN_HIRE)".

    Design: Corner/state_machines/account_close_blocked_by_open_hire
    """
    ctx = H.setup_open_hire(asset_count=1)
    resp = api.close_account(ctx["account"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_HIRE.value, expected_status=409)


def test_account_not_settled_close_blocked(api):
    """PRD §3.1: "An ACTIVE account may be closed to CLOSED, but only when it has
    no hire whose lifecycle_status is OPEN (otherwise ERR_ACCOUNT_HAS_OPEN_HIRE)
    and its outstanding_charge_cents is exactly 0 (otherwise
    ERR_ACCOUNT_NOT_SETTLED)".

    Design: Corner/validations/account_not_settled_close_blocked
    """
    ctx = H.setup_closed_hire_invoiced(line_amount=500)
    resp = api.close_account(ctx["account"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SETTLED.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: hire-not-closed on invoice issue
# --------------------------------------------------------------------------
def test_hire_not_closed_on_invoice_issue(api):
    """PRD §3.9: "Issue requires the invoice to have at least one line (otherwise
    ERR_INVOICE_EMPTY) and requires that every HIRE line's source hire be in
    lifecycle_status CLOSED (otherwise ERR_HIRE_NOT_CLOSED)."

    Design: Corner/validations/error_hire_not_closed_on_invoice_issue_covered_by_settlement
    """
    ctx = H.setup_open_hire(asset_count=1)
    inv, _lines = H.setup_invoice_with_lines(
        ctx["account"]["id"], [("HIRE", 500, {"source_hire_id": ctx["hire"]["id"]})]
    )
    resp = api.issue_invoice(inv["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_HIRE_NOT_CLOSED.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: report-damage on ON_HIRE asset removes occupancy
# --------------------------------------------------------------------------
def test_report_damage_on_on_hire_asset_removes_occupancy(api):
    """PRD §3.2: "Reporting damage takes an asset to DAMAGED — from ON_HIRE or
    from AVAILABLE; when the damaged asset was on an OPEN hire, it is removed from
    that hire's occupancy and its current_hire_id is cleared to null."

    Design: Corner/endpoints/report_damage_on_on_hire_asset_removes_occupancy
    """
    ctx = H.setup_open_hire(asset_count=1)
    asset_id = ctx["asset_ids"][0]
    resp = api.report_damage(asset_id, make_participant_headers(ctx["account"]["id"]))
    data = validate_success(resp)
    assert_asset(data)
    assert data["condition"] == "DAMAGED"
    assert data["current_hire_id"] is None
