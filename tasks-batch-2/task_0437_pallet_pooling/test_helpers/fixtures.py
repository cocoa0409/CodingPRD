"""Composite setup helpers for the pallet-pooling API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty DB) before every test.
Helpers use get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_pool_admin_headers,
    make_pool_operator_headers,
    make_participant_headers,
)
from . import factories as f

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Advance the server logical clock (PoolAdmin only)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# --------------------------------------------------------------------------
# Bootstrap primitives
# --------------------------------------------------------------------------
def create_policy(**overrides) -> dict:
    return get_success_data(
        api_client.create_pool_policy(f.create_pool_policy_payload(**overrides), ADMIN)
    )


def create_asset_type(**overrides) -> dict:
    return get_success_data(
        api_client.create_asset_type(f.create_asset_type_payload(**overrides), ADMIN)
    )


def create_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_account(f.create_account_payload(**overrides), ADMIN)
    )


def create_location(account_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(
            f.create_location_payload(account_id, **overrides), ADMIN
        )
    )


def create_asset(asset_type_id, location_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(
            f.create_asset_payload(asset_type_id, location_id, **overrides), OPERATOR
        )
    )


def get_location(location_id) -> dict:
    return get_success_data(api_client.get_location(location_id, OPERATOR))


def location_version(location_id) -> int:
    return get_location(location_id)["version"]


# --------------------------------------------------------------------------
# Tier 1/2: program bootstrap (policy + asset type + account + location)
# --------------------------------------------------------------------------
def bootstrap_program(
    policy_overrides=None,
    asset_type_overrides=None,
    account_overrides=None,
    location_overrides=None,
    clock=None,
):
    """Create policy, asset type, account, and one location.

    Returns dict with keys: policy, asset_type, account, location.
    If `clock` is given it is set AFTER creation (so created_at uses startup
    default), matching the design recipes that set the clock mid-setup.
    """
    policy = create_policy(**(policy_overrides or {}))
    asset_type = create_asset_type(**(asset_type_overrides or {}))
    account = create_account(**(account_overrides or {}))
    location = create_location(account["id"], **(location_overrides or {}))
    if clock is not None:
        set_clock(clock)
    return {
        "policy": policy,
        "asset_type": asset_type,
        "account": account,
        "location": location,
    }


def mint_assets(asset_type_id, location_id, count, serial_prefix="S", in_service_at="2026-01-01T00:00:00Z"):
    """Mint `count` AVAILABLE assets at a location. Returns list of asset dicts."""
    assets = []
    for i in range(1, count + 1):
        assets.append(
            create_asset(
                asset_type_id,
                location_id,
                serial=f"{serial_prefix}{i}",
                in_service_at=in_service_at,
            )
        )
    return assets


# --------------------------------------------------------------------------
# Tier 2: equity setup via ISSUANCE (stock -> destination location)
# --------------------------------------------------------------------------
def issue_assets_into_location(
    asset_type_id, stock_location_id, dest_location_id, count,
    serial_prefix="I", in_service_at="2026-01-01T00:00:00Z", actor=None,
):
    """Mint `count` assets at stock, then ISSUANCE-dispatch-receive them into
    dest_location. Afterwards dest physical_balance and equity_balance both
    rise by `count`. Returns (asset_ids, transfer_order).
    """
    actor = actor or OPERATOR
    assets = mint_assets(
        asset_type_id, stock_location_id, count,
        serial_prefix=serial_prefix, in_service_at=in_service_at,
    )
    asset_ids = [a["id"] for a in assets]
    to = get_success_data(
        api_client.create_transfer_order(
            f.create_transfer_order_payload(
                stock_location_id, dest_location_id, "ISSUANCE", asset_ids
            ),
            actor,
        )
    )
    get_success_data(api_client.dispatch_transfer_order(to["id"], actor))
    to = get_success_data(api_client.receive_transfer_order(to["id"], actor))
    return asset_ids, to


def setup_location_with_equity(equity, asset_type_overrides=None, account_overrides=None):
    """Build a location whose equity_balance == physical_balance == `equity`
    via an ISSUANCE from a stock location under the same account.

    Returns dict: policy, asset_type, account, stock, location, asset_ids.
    """
    policy = create_policy()
    asset_type = create_asset_type(**(asset_type_overrides or {}))
    account = create_account(**(account_overrides or {}))
    stock = create_location(account["id"], name="Stock")
    location = create_location(account["id"], name="L1")
    asset_ids, _ = issue_assets_into_location(
        asset_type["id"], stock["id"], location["id"], equity
    )
    return {
        "policy": policy,
        "asset_type": asset_type,
        "account": account,
        "stock": stock,
        "location": location,
        "asset_ids": asset_ids,
    }


# --------------------------------------------------------------------------
# Tier 3: hire lifecycle shortcuts
# --------------------------------------------------------------------------
def open_hire(account_id, location_id, asset_type_id, asset_ids, actor=None):
    """Open a hire reading the current location version for OCC. Returns hire."""
    actor = actor or OPERATOR
    ver = location_version(location_id)
    return get_success_data(
        api_client.create_hire(
            f.create_hire_payload(
                account_id, location_id, asset_type_id, asset_ids, ver
            ),
            actor,
        )
    )


def close_hire(hire_id, actor=None):
    actor = actor or OPERATOR
    return get_success_data(api_client.close_hire(hire_id, actor))


def setup_open_hire(asset_count=1, base_daily_rate_cents=500, credit_limit_cents=10_000_000,
                    on_hire_clock="2026-06-01T00:00:00Z", account_overrides=None):
    """Bootstrap a program, mint `asset_count` assets, set clock, and open a hire.

    Returns dict: policy, asset_type, account, location, asset_ids, hire.
    """
    acct_over = {"credit_limit_cents": credit_limit_cents}
    acct_over.update(account_overrides or {})
    ctx = bootstrap_program(
        asset_type_overrides={"base_daily_rate_cents": base_daily_rate_cents},
        account_overrides=acct_over,
        clock=on_hire_clock,
    )
    assets = mint_assets(ctx["asset_type"]["id"], ctx["location"]["id"], asset_count)
    asset_ids = [a["id"] for a in assets]
    hire = open_hire(
        ctx["account"]["id"], ctx["location"]["id"], ctx["asset_type"]["id"], asset_ids
    )
    ctx["asset_ids"] = asset_ids
    ctx["hire"] = hire
    return ctx


def setup_closed_hire(asset_count=1, base_daily_rate_cents=500,
                      on_hire_clock="2026-06-01T00:00:00Z",
                      off_hire_clock="2026-06-02T00:00:00Z",
                      account_overrides=None):
    """Open then close a hire. Returns dict with closed `hire` and context."""
    ctx = setup_open_hire(
        asset_count=asset_count, base_daily_rate_cents=base_daily_rate_cents,
        on_hire_clock=on_hire_clock, account_overrides=account_overrides,
    )
    set_clock(off_hire_clock)
    ctx["hire"] = close_hire(ctx["hire"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 4: audit reconciliation
# --------------------------------------------------------------------------
def create_audit(location_id, window_start, window_end, counted_physical, **overrides):
    return get_success_data(
        api_client.create_audit(
            f.create_audit_payload(
                location_id, window_start, window_end, counted_physical, **overrides
            ),
            OPERATOR,
        )
    )


def finalize_audit(audit_id):
    return get_success_data(api_client.finalize_audit(audit_id, OPERATOR))


def setup_audit_ready(equity, counted_physical, loss_basis="REPLACEMENT",
                      asset_type_overrides=None,
                      window_start="2026-06-01T00:00:00Z",
                      window_end="2026-06-30T00:00:00Z"):
    """Build a location with `equity` (via ISSUANCE) plus a DRAFT audit over it.

    Returns dict: policy, asset_type, account, stock, location, asset_ids, audit.
    """
    ctx = setup_location_with_equity(equity, asset_type_overrides=asset_type_overrides)
    ctx["audit"] = create_audit(
        ctx["location"]["id"], window_start, window_end, counted_physical,
        loss_basis=loss_basis,
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3/4: voucher issue
# --------------------------------------------------------------------------
def issue_voucher(from_location_id, to_account_id, asset_type_id, quantity, actor=None):
    """Issue a voucher, reading the current from_location version for OCC."""
    actor = actor or OPERATOR
    ver = location_version(from_location_id)
    return get_success_data(
        api_client.create_voucher(
            f.create_voucher_payload(
                from_location_id, to_account_id, asset_type_id, quantity, ver
            ),
            actor,
        )
    )


def setup_voucher_outstanding(from_equity, quantity, voucher_expiry_days=90,
                              issue_clock="2026-06-01T00:00:00Z"):
    """Two accounts; LA (acct1) loaded to `from_equity` via ISSUANCE; LB under
    acct2; an OUTSTANDING voucher of `quantity` issued from LA to acct2.

    Returns dict: policy, asset_type, acct1, acct2, stock, la, lb, voucher.
    """
    policy = create_policy(voucher_expiry_days=voucher_expiry_days)
    asset_type = create_asset_type()
    acct1 = create_account(legal_name="Acct1", role_type="MANUFACTURER")
    acct2 = create_account(legal_name="Acct2", role_type="RETAILER")
    stock = create_location(acct1["id"], name="Stock")
    la = create_location(acct1["id"], name="LA")
    lb = create_location(acct2["id"], name="LB")
    issue_assets_into_location(asset_type["id"], stock["id"], la["id"], from_equity)
    set_clock(issue_clock)
    voucher = issue_voucher(la["id"], acct2["id"], asset_type["id"], quantity)
    return {
        "policy": policy,
        "asset_type": asset_type,
        "acct1": acct1,
        "acct2": acct2,
        "stock": stock,
        "la": la,
        "lb": lb,
        "voucher": voucher,
    }


# --------------------------------------------------------------------------
# Tier 3: collection + repair
# --------------------------------------------------------------------------
def create_collection_request(location_id, asset_ids):
    return get_success_data(
        api_client.create_collection_request(
            f.create_collection_request_payload(location_id, asset_ids), OPERATOR
        )
    )


def collect_request(cr_id):
    return get_success_data(api_client.collect_collection_request(cr_id, OPERATOR))


def create_repair_job(collection_request_id, asset_ids, repair_cost_cents):
    return get_success_data(
        api_client.create_repair_job(
            f.create_repair_job_payload(
                collection_request_id, asset_ids, repair_cost_cents
            ),
            OPERATOR,
        )
    )


def setup_repair_job_open(repair_cost_cents=1500, damaged=True):
    """Mint one asset at a depot, (optionally) damage it, collect it, and open a
    repair job over it.

    Returns dict: policy, asset_type, account, depot, asset, collection, repair_job.
    When damaged=False the asset stays AVAILABLE through collection (used to test
    repair-on-non-damaged rejection) and `repair_job` is omitted.
    """
    ctx = bootstrap_program()
    depot = create_location(ctx["account"]["id"], name="Depot")
    asset = create_asset(ctx["asset_type"]["id"], depot["id"], serial="R1")
    if damaged:
        get_success_data(api_client.report_damage(asset["id"], OPERATOR))
    cr = create_collection_request(depot["id"], [asset["id"]])
    collect_request(cr["id"])
    result = {
        "policy": ctx["policy"],
        "asset_type": ctx["asset_type"],
        "account": ctx["account"],
        "depot": depot,
        "asset": asset,
        "collection": cr,
    }
    if damaged:
        result["repair_job"] = create_repair_job(
            cr["id"], [asset["id"]], repair_cost_cents
        )
    return result


# --------------------------------------------------------------------------
# Tier 5: invoice / billing
# --------------------------------------------------------------------------
def create_invoice(account_id):
    return get_success_data(
        api_client.create_invoice(f.create_invoice_payload(account_id), OPERATOR)
    )


def add_invoice_line(invoice_id, kind, amount_cents, **overrides):
    return get_success_data(
        api_client.add_invoice_line(
            invoice_id, f.create_invoice_line_payload(kind, amount_cents, **overrides),
            OPERATOR,
        )
    )


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_invoice(invoice_id, OPERATOR))


def record_payment(invoice_id, amount_cents):
    return get_success_data(
        api_client.record_payment(invoice_id, {"amount_cents": amount_cents}, OPERATOR)
    )


def setup_invoice_with_lines(account_id, lines):
    """Create a DRAFT invoice and attach `lines` (list of (kind, amount_cents)
    or (kind, amount_cents, extra_dict)). Returns (invoice, [line, ...])."""
    inv = create_invoice(account_id)
    created = []
    for entry in lines:
        if len(entry) == 3:
            kind, amount, extra = entry
        else:
            kind, amount = entry
            extra = {}
        created.append(add_invoice_line(inv["id"], kind, amount, **extra))
    return inv, created


def setup_closed_hire_invoiced(line_amount=500):
    """Closed hire (1 asset, 1 day) referenced by a HIRE line on an ISSUED
    invoice (settlement_status -> INVOICED).

    Returns dict: account, hire, invoice, line plus base context.
    """
    ctx = setup_closed_hire()
    inv, lines = setup_invoice_with_lines(
        ctx["account"]["id"],
        [("HIRE", line_amount, {"source_hire_id": ctx["hire"]["id"]})],
    )
    inv = issue_invoice(inv["id"])
    ctx["invoice"] = inv
    ctx["line"] = lines[0]
    return ctx
