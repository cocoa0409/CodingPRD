"""Composite setup helpers for the SMA Model Delivery API.

The harness restarts the server before every individual test, so every fixture
here builds its preconditions from scratch through PRD-declared endpoints only.
Setup calls use the lenient `get_success_data()` validator so a broken
precondition surfaces as a clear "Setup failed" message rather than a confusing
assertion deep inside a test.

Identity threading: `SponsorOperator` is entity-backed, so every sponsor-scoped
call made here uses `make_sponsor_operator_headers(sponsor["id"])`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_block_payload,
    create_distribution_payload,
    create_fee_invoice_payload,
    create_harvest_proposal_payload,
    create_model_payload,
    create_model_version_payload,
    create_restriction_payload,
    create_security_payload,
    create_sponsor_payload,
    deposit_payload,
    drift_evaluation_payload,
    execute_block_payload,
    performance_observation_payload,
    reject_harvest_payload,
    reject_model_version_payload,
    reprice_security_payload,
    set_clock_payload,
    sleeve,
    sleeves_payload,
    transfer_in_payload,
    void_invoice_payload,
)
from .test_users import (
    COMPLIANCE_USER_ID,
    MANAGER_USER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_portfolio_manager_headers,
    make_sponsor_operator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["portfolio_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_officer_headers"]

# The three instruments and the 25,000,000c account shape reused by most of the
# multi-step scenarios in this suite.
STANDARD_SECURITIES = [
    ("ALFA", "Alfa Industrials", 10_000),
    ("BETA", "Beta Materials", 5_000),
    ("CETA", "Ceta Utilities", 2_500),
]
STANDARD_SLEEVES = [("ALFA", 5000), ("BETA", 3000), ("CETA", 2000)]
STANDARD_POSITIONS = [
    ("ALFA", 1250, 12_500_000),
    ("BETA", 1500, 7_500_000),
    ("CETA", 1000, 2_500_000),
]
STANDARD_CASH_CENTS = 2_500_000


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. Returns the echoed { current_utc }."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: registry rows
# ---------------------------------------------------------------------------
def create_security(ticker="ALFA", last_price_cents=10_000, name=None, **overrides):
    """Register one instrument. Returns the Security."""
    payload = create_security_payload(
        ticker=ticker,
        name=name or f"{ticker.title()} Industrials",
        last_price_cents=last_price_cents,
        **overrides,
    )
    return get_success_data(api_client.create_security(payload, ADMIN))


def create_securities(specs=None) -> dict:
    """Register several instruments. `specs` entries are (ticker, name, price)
    or (ticker, price) tuples, or full payload dicts. Returns {ticker: Security}."""
    specs = STANDARD_SECURITIES if specs is None else specs
    out = {}
    for spec in specs:
        if isinstance(spec, dict):
            security = get_success_data(
                api_client.create_security(create_security_payload(**spec), ADMIN)
            )
        elif len(spec) == 3:
            ticker, name, price = spec
            security = create_security(ticker=ticker, name=name, last_price_cents=price)
        else:
            ticker, price = spec
            security = create_security(ticker=ticker, last_price_cents=price)
        out[security["ticker"]] = security
    return out


def reprice_security(security_id, last_price_cents):
    """Re-mark an instrument. Returns the updated Security."""
    return get_success_data(
        api_client.reprice_security(
            security_id, reprice_security_payload(last_price_cents), ADMIN
        )
    )


def create_sponsor(platform_code="NRTH", name=None, **overrides):
    """Register a sponsor platform. Returns the Sponsor (its id is the
    X-User-ID its operators must present)."""
    payload = create_sponsor_payload(
        platform_code=platform_code, name=name or "Northline Wealth", **overrides
    )
    return get_success_data(api_client.create_sponsor(payload, ADMIN))


def create_model(strategy_code="CORE", **overrides):
    """Register a model strategy. Returns the Model."""
    payload = create_model_payload(strategy_code=strategy_code, **overrides)
    return get_success_data(api_client.create_model(payload, MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: model-version lifecycle
# ---------------------------------------------------------------------------
def _resolve_sleeves(sleeve_specs, securities):
    """Turn [(ticker, weight)] / [(ticker, weight, cap)] into sleeve objects."""
    resolved = []
    for spec in sleeve_specs:
        if isinstance(spec, dict):
            resolved.append(spec)
            continue
        if len(spec) == 3:
            ticker, weight, cap = spec
        else:
            (ticker, weight), cap = spec, None
        resolved.append(sleeve(securities[ticker]["id"], weight, cap))
    return resolved


def create_draft_version(model_id, sleeve_specs=None, securities=None):
    """Open a DRAFT version and, when sleeves are supplied, install them."""
    version = get_success_data(
        api_client.create_model_version(create_model_version_payload(model_id), MANAGER)
    )
    if sleeve_specs:
        version = set_sleeves(version["id"], sleeve_specs, securities)
    return version


def set_sleeves(model_version_id, sleeve_specs, securities=None):
    """Replace a DRAFT version's sleeve array wholesale."""
    sleeves = (
        sleeve_specs
        if securities is None
        else _resolve_sleeves(sleeve_specs, securities)
    )
    return get_success_data(
        api_client.replace_sleeves(model_version_id, sleeves_payload(sleeves), MANAGER)
    )


def submit_version(model_version_id, submitter=MANAGER_USER_ID):
    return get_success_data(
        api_client.submit_model_version(
            model_version_id, make_portfolio_manager_headers(submitter)
        )
    )


def approve_version(model_version_id, reviewer=COMPLIANCE_USER_ID):
    return get_success_data(
        api_client.approve_model_version(
            model_version_id, make_compliance_officer_headers(reviewer)
        )
    )


def reject_version(model_version_id, rejection_note, reviewer=COMPLIANCE_USER_ID):
    return get_success_data(
        api_client.reject_model_version(
            model_version_id,
            reject_model_version_payload(rejection_note),
            make_compliance_officer_headers(reviewer),
        )
    )


def publish_version(model_version_id, publisher=MANAGER_USER_ID):
    return get_success_data(
        api_client.publish_model_version(
            model_version_id, make_portfolio_manager_headers(publisher)
        )
    )


def create_approved_version(
    model_id, sleeve_specs, securities, submitter=MANAGER_USER_ID,
    reviewer=COMPLIANCE_USER_ID,
):
    """DRAFT -> sleeves -> PENDING_APPROVAL -> APPROVED. Returns the version."""
    version = create_draft_version(model_id, sleeve_specs, securities)
    submit_version(version["id"], submitter)
    return approve_version(version["id"], reviewer)


def create_published_version(
    model_id, sleeve_specs, securities, submitter=MANAGER_USER_ID,
    reviewer=COMPLIANCE_USER_ID,
):
    """DRAFT -> sleeves -> submit -> approve -> PUBLISHED. Returns the version."""
    version = create_approved_version(
        model_id, sleeve_specs, securities, submitter, reviewer
    )
    return publish_version(version["id"], submitter)


def get_model_version(model_version_id):
    return get_success_data(api_client.get_model_version(model_version_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: platform env — securities + sponsor + model + PUBLISHED version
# ---------------------------------------------------------------------------
def setup_platform(
    securities=None,
    sleeves=None,
    model_overrides=None,
    sponsor_overrides=None,
    submitter=MANAGER_USER_ID,
    reviewer=COMPLIANCE_USER_ID,
    publish=True,
):
    """Instruments + sponsor + model + one model version.

    Returns a dict with keys: securities ({ticker: Security}), sponsor, model,
    model_version, sponsor_headers.
    """
    secs = create_securities(securities)
    sponsor = create_sponsor(**(sponsor_overrides or {}))
    model = create_model(**(model_overrides or {}))
    sleeve_specs = sleeves if sleeves is not None else [("ALFA", 10000)]
    if publish:
        version = create_published_version(
            model["id"], sleeve_specs, secs, submitter, reviewer
        )
    else:
        version = create_draft_version(model["id"], sleeve_specs, secs)
    return {
        "securities": secs,
        "sponsor": sponsor,
        "sponsor_headers": make_sponsor_operator_headers(sponsor["id"]),
        "model": model,
        "model_version": version,
    }


# ---------------------------------------------------------------------------
# Tier 3: accounts
# ---------------------------------------------------------------------------
def open_account(env, account_number="ACC-001", sponsor=None, **overrides):
    """Open an SMA account on the env's sponsor and model."""
    sponsor = sponsor or env["sponsor"]
    payload = create_account_payload(
        sponsor["id"], env["model"]["id"], account_number=account_number, **overrides
    )
    return get_success_data(
        api_client.create_account(payload, make_sponsor_operator_headers(sponsor["id"]))
    )


def deposit(account_id, sponsor_id, amount_cents):
    return get_success_data(
        api_client.deposit_cash(
            account_id,
            deposit_payload(amount_cents),
            make_sponsor_operator_headers(sponsor_id),
        )
    )


def transfer_in(account_id, sponsor_id, security_id, shares, cost_basis_cents, origin=None):
    """Book an existing position in kind. Returns the created TaxLot."""
    extra = {} if origin is None else {"origin": origin}
    return get_success_data(
        api_client.transfer_in(
            account_id,
            transfer_in_payload(security_id, shares, cost_basis_cents, **extra),
            make_sponsor_operator_headers(sponsor_id),
        )
    )


def fund_account(env, account, cash_cents=0, positions=None):
    """Credit cash and book in-kind positions. `positions` entries are
    (ticker, shares, cost_basis_cents) or (ticker, shares, basis, origin).
    Returns the refreshed Account."""
    sponsor_id = env["sponsor"]["id"]
    if cash_cents:
        deposit(account["id"], sponsor_id, cash_cents)
    for spec in positions or []:
        ticker, shares, basis = spec[0], spec[1], spec[2]
        origin = spec[3] if len(spec) > 3 else None
        transfer_in(
            account["id"],
            sponsor_id,
            env["securities"][ticker]["id"],
            shares,
            basis,
            origin,
        )
    return get_account(account["id"])


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


def setup_funded_account(
    securities=None,
    sleeves=None,
    model_overrides=None,
    sponsor_overrides=None,
    account_overrides=None,
    account_number="ACC-001",
    cash_cents=0,
    positions=None,
):
    """Platform env plus one funded account. Returns the env with `account`."""
    env = setup_platform(
        securities=securities,
        sleeves=sleeves,
        model_overrides=model_overrides,
        sponsor_overrides=sponsor_overrides,
    )
    account = open_account(env, account_number, **(account_overrides or {}))
    env["account"] = fund_account(env, account, cash_cents, positions)
    return env


def setup_standard_account(
    drift_threshold_bps=1000,
    account_overrides=None,
    sponsor_overrides=None,
    sleeves=None,
    positions=None,
    cash_cents=STANDARD_CASH_CENTS,
    model_overrides=None,
):
    """The canonical 25,000,000c account: ALFA 1250 / BETA 1500 / CETA 1000 plus
    2,500,000c cash, tracking a PUBLISHED ALFA 5000 / BETA 3000 / CETA 2000
    version. Returns the env with `account`."""
    merged_model = {"drift_threshold_bps": drift_threshold_bps}
    merged_model.update(model_overrides or {})
    overrides = {"cash_reserve_bps": 100}
    overrides.update(account_overrides or {})
    return setup_funded_account(
        securities=STANDARD_SECURITIES,
        sleeves=STANDARD_SLEEVES if sleeves is None else sleeves,
        model_overrides=merged_model,
        sponsor_overrides=sponsor_overrides,
        account_overrides=overrides,
        cash_cents=cash_cents,
        positions=STANDARD_POSITIONS if positions is None else positions,
    )


def suspend_account(account_id):
    return get_success_data(api_client.suspend_account(account_id, COMPLIANCE))


def reinstate_account(account_id):
    return get_success_data(api_client.reinstate_account(account_id, COMPLIANCE))


def create_restriction(account_id, security_id, restriction_type, max_position_bps=None):
    extra = {} if max_position_bps is None else {"max_position_bps": max_position_bps}
    return get_success_data(
        api_client.create_restriction(
            create_restriction_payload(
                account_id, security_id, restriction_type, **extra
            ),
            COMPLIANCE,
        )
    )


def lift_restriction(restriction_id):
    return get_success_data(api_client.lift_restriction(restriction_id, COMPLIANCE))


def evaluate_drift(account_id, sponsor_id, basis=None):
    """Run a drift evaluation. Returns the refreshed Account."""
    return get_success_data(
        api_client.evaluate_drift(
            account_id,
            drift_evaluation_payload(basis),
            make_sponsor_operator_headers(sponsor_id),
        )
    )


def rebalance(account_id, sponsor_id):
    """Generate rebalance orders. Returns the rebalance result object."""
    return get_success_data(
        api_client.rebalance_account(account_id, make_sponsor_operator_headers(sponsor_id))
    )


def run_implementation(account_id, sponsor_id):
    """Adopt the pending version. Returns the implementation result object."""
    return get_success_data(
        api_client.run_implementation(
            account_id, make_sponsor_operator_headers(sponsor_id)
        )
    )


def record_performance(
    account_id, sponsor_id, period_end, gross_return_bps, ending_value_cents
):
    return get_success_data(
        api_client.record_performance(
            account_id,
            performance_observation_payload(
                period_end, gross_return_bps, ending_value_cents
            ),
            make_sponsor_operator_headers(sponsor_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: distributions and the notification fan-out
# ---------------------------------------------------------------------------
def create_distribution(
    sponsor_id,
    model_version_id,
    expected_model_version_version=None,
    effective_from="2026-01-01T00:00:00Z",
    effective_until=None,
):
    """Distribute a PUBLISHED version onto a sponsor platform (PENDING)."""
    if expected_model_version_version is None:
        expected_model_version_version = get_model_version(model_version_id)["version"]
    extra = {} if effective_until is None else {"effective_until": effective_until}
    return get_success_data(
        api_client.create_distribution(
            create_distribution_payload(
                sponsor_id,
                model_version_id,
                expected_model_version_version,
                effective_from,
                **extra,
            ),
            MANAGER,
        )
    )


def activate_distribution(distribution_id, sponsor_id):
    return get_success_data(
        api_client.activate_distribution(
            distribution_id, make_sponsor_operator_headers(sponsor_id)
        )
    )


def create_active_distribution(
    sponsor_id, model_version_id, effective_from="2026-01-01T00:00:00Z",
    effective_until=None,
):
    """Create then activate a distribution. Returns the ACTIVE distribution."""
    dist = create_distribution(
        sponsor_id, model_version_id, None, effective_from, effective_until
    )
    return activate_distribution(dist["id"], sponsor_id)


def publish_successor_version(env, sleeve_specs=None, submitter=MANAGER_USER_ID,
                              reviewer=COMPLIANCE_USER_ID):
    """Author, approve and publish a second version of the env's model. This is
    what drives the publication fan-out onto the env's accounts. Returns the new
    version."""
    specs = sleeve_specs if sleeve_specs is not None else [("ALFA", 10000)]
    version = create_approved_version(
        env["model"]["id"], specs, env["securities"], submitter, reviewer
    )
    return publish_version(version["id"], submitter)


def setup_account_pending_implementation(
    securities=None,
    sleeves=None,
    successor_sleeves=None,
    model_overrides=None,
    sponsor_overrides=None,
    account_overrides=None,
    cash_cents=0,
    positions=None,
    activate_successor_distribution=True,
):
    """Drive an account into PENDING_IMPLEMENTATION through the publication
    fan-out: v1 published and actively distributed, account opened on it, then
    v2 published so the account is notified. When
    `activate_successor_distribution` is true an ACTIVE distribution of v2 is
    left in place so the implementation can run.

    Returns the env with keys `account`, `distribution_v1`, `model_version_v2`
    and (when activated) `distribution_v2`.
    """
    env = setup_funded_account(
        securities=securities,
        sleeves=sleeves,
        model_overrides=model_overrides,
        sponsor_overrides=sponsor_overrides,
        account_overrides=account_overrides,
        cash_cents=cash_cents,
        positions=positions,
    )
    env["distribution_v1"] = create_active_distribution(
        env["sponsor"]["id"], env["model_version"]["id"]
    )
    v2 = publish_successor_version(env, successor_sleeves)
    env["model_version_v2"] = v2
    if activate_successor_distribution:
        env["distribution_v2"] = create_active_distribution(
            env["sponsor"]["id"], v2["id"]
        )
    env["account"] = get_account(env["account"]["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 4: orders, blocks and the allocation chain
# ---------------------------------------------------------------------------
def list_trade_orders(**filters):
    """List trade orders (ordered created_at ASC then sequence_number ASC)."""
    data, _meta = _paginated(api_client.list_trade_orders(ADMIN, params=filters or None))
    return data


def list_tax_lots(**filters):
    data, _meta = _paginated(api_client.list_tax_lots(ADMIN, params=filters or None))
    return data


def _paginated(response):
    body = get_success_data(response)
    meta = response.json()["meta"]
    return body, meta


def get_trade_order(trade_order_id):
    return get_success_data(api_client.get_trade_order(trade_order_id, ADMIN))


def get_tax_lot(tax_lot_id):
    return get_success_data(api_client.get_tax_lot(tax_lot_id, ADMIN))


def get_block(block_id):
    return get_success_data(api_client.get_block(block_id, ADMIN))


def cancel_order(trade_order_id, sponsor_id):
    return get_success_data(
        api_client.cancel_trade_order(
            trade_order_id, make_sponsor_operator_headers(sponsor_id)
        )
    )


def create_block(trade_order_ids, sponsor_id):
    return get_success_data(
        api_client.create_block(
            create_block_payload(trade_order_ids),
            make_sponsor_operator_headers(sponsor_id),
        )
    )


def execute_block(block_id, filled_shares, avg_fill_price_cents):
    return get_success_data(
        api_client.execute_block(
            block_id, execute_block_payload(filled_shares, avg_fill_price_cents), ADMIN
        )
    )


def allocate_block(block_id):
    return get_success_data(api_client.allocate_block(block_id, ADMIN))


def unwind_block(block_id):
    return get_success_data(api_client.unwind_block(block_id, ADMIN))


def setup_drifted_account_with_orders(
    drift_threshold_bps=1000,
    account_overrides=None,
    sponsor_overrides=None,
    sleeves=None,
    positions=None,
    cash_cents=STANDARD_CASH_CENTS,
    restrictions=None,
    securities=None,
    model_overrides=None,
):
    """Canonical account driven to DRIFTED with a full set of PROPOSED rebalance
    orders. `restrictions` entries are (ticker, restriction_type) or
    (ticker, restriction_type, max_position_bps).

    Returns the env with `account`, `restrictions`, `rebalance_result` and
    `orders` (the PROPOSED rebalance orders, ticker-ascending generation order).
    """
    env = setup_funded_account(
        securities=STANDARD_SECURITIES if securities is None else securities,
        sleeves=STANDARD_SLEEVES if sleeves is None else sleeves,
        model_overrides=dict({"drift_threshold_bps": drift_threshold_bps},
                             **(model_overrides or {})),
        sponsor_overrides=sponsor_overrides,
        account_overrides=dict({"cash_reserve_bps": 100}, **(account_overrides or {})),
        cash_cents=cash_cents,
        positions=STANDARD_POSITIONS if positions is None else positions,
    )
    created = []
    for spec in restrictions or []:
        ticker, restriction_type = spec[0], spec[1]
        cap = spec[2] if len(spec) > 2 else None
        created.append(
            create_restriction(
                env["account"]["id"], env["securities"][ticker]["id"],
                restriction_type, cap,
            )
        )
    env["restrictions"] = created
    env["account"] = evaluate_drift(env["account"]["id"], env["sponsor"]["id"])
    env["rebalance_result"] = rebalance(env["account"]["id"], env["sponsor"]["id"])
    env["orders"] = [
        get_trade_order(oid) for oid in env["rebalance_result"]["trade_order_ids"]
    ]
    env["account"] = get_account(env["account"]["id"])
    return env


def setup_open_block(order_ids=None, env=None):
    """Assemble the given PROPOSED orders into an OPEN block."""
    ids = order_ids or [o["id"] for o in env["orders"]]
    return create_block(ids, env["sponsor"]["id"])


def setup_filled_block(env, order_ids=None, filled_shares=None, avg_fill_price_cents=None):
    """Assemble a block and record a street fill on it. Returns the FILLED block."""
    block = setup_open_block(order_ids, env)
    fill = block["requested_shares"] if filled_shares is None else filled_shares
    price = (
        avg_fill_price_cents
        if avg_fill_price_cents is not None
        else env["securities"][
            next(
                ticker
                for ticker, sec in env["securities"].items()
                if sec["id"] == block["security_id"]
            )
        ]["last_price_cents"]
    )
    return execute_block(block["id"], fill, price)


# ---------------------------------------------------------------------------
# Tier 4: harvesting
# ---------------------------------------------------------------------------
def create_harvest_proposal(
    account_id, security_id, shares, expected_account_version=None,
    replacement_security_id=None,
):
    if expected_account_version is None:
        expected_account_version = get_account(account_id)["version"]
    extra = (
        {}
        if replacement_security_id is None
        else {"replacement_security_id": replacement_security_id}
    )
    return get_success_data(
        api_client.create_harvest_proposal(
            create_harvest_proposal_payload(
                account_id, security_id, shares, expected_account_version, **extra
            ),
            MANAGER,
        )
    )


def approve_harvest(harvest_proposal_id):
    return get_success_data(
        api_client.approve_harvest_proposal(harvest_proposal_id, COMPLIANCE)
    )


def reject_harvest(harvest_proposal_id, rejection_note):
    return get_success_data(
        api_client.reject_harvest_proposal(
            harvest_proposal_id, reject_harvest_payload(rejection_note), COMPLIANCE
        )
    )


def execute_harvest(harvest_proposal_id):
    return get_success_data(
        api_client.execute_harvest_proposal(harvest_proposal_id, MANAGER)
    )


def setup_harvest_ready_account(
    positions=None,
    harvest_budget_cents=100_000_000,
    securities=None,
    sleeves=None,
    cash_cents=0,
    model_overrides=None,
    sponsor_overrides=None,
    account_overrides=None,
):
    """Account with `tax_overlay_enabled` true, a generous harvest budget and
    the given in-kind lots already booked. Returns the env with `account`."""
    overrides = {
        "tax_overlay_enabled": True,
        "harvest_budget_cents": harvest_budget_cents,
    }
    overrides.update(account_overrides or {})
    return setup_funded_account(
        securities=securities,
        sleeves=sleeves,
        model_overrides=model_overrides,
        sponsor_overrides=sponsor_overrides,
        account_overrides=overrides,
        cash_cents=cash_cents,
        positions=positions,
    )


# ---------------------------------------------------------------------------
# Tier 5: fee invoices, delinquency and the write-off chain
# ---------------------------------------------------------------------------
def create_invoice(account_id, **overrides):
    return get_success_data(
        api_client.create_fee_invoice(
            create_fee_invoice_payload(account_id, **overrides), BILLING
        )
    )


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_fee_invoice(invoice_id, BILLING))


def pay_invoice(invoice_id):
    return get_success_data(api_client.pay_fee_invoice(invoice_id, BILLING))


def void_invoice(invoice_id, void_reason="Billed in error"):
    return get_success_data(
        api_client.void_fee_invoice(invoice_id, void_invoice_payload(void_reason), BILLING)
    )


def mark_invoice_delinquent(invoice_id):
    return get_success_data(
        api_client.mark_fee_invoice_delinquent(invoice_id, BILLING)
    )


def write_off_invoice(invoice_id):
    return get_success_data(api_client.write_off_fee_invoice(invoice_id, BILLING))


def setup_issued_invoice(account_id, **overrides):
    """Compute and issue one invoice. Returns the ISSUED FeeInvoice."""
    invoice = create_invoice(account_id, **overrides)
    return issue_invoice(invoice["id"])


def setup_delinquent_invoice(account_id, clock_after_term=None, **overrides):
    """Issue an invoice and, once the 30-day payment term has run out on the
    logical clock, declare it delinquent. Returns the ISSUED invoice whose
    account is now DELINQUENT."""
    invoice = setup_issued_invoice(account_id, **overrides)
    if clock_after_term:
        set_clock(clock_after_term)
    mark_invoice_delinquent(invoice["id"])
    return get_success_data(api_client.get_fee_invoice(invoice["id"], BILLING))


def setup_written_off_account(account_id, clock_after_term=None, **overrides):
    """Drive the account's billing dimension to WRITTEN_OFF through the
    delinquency path. Returns (invoice, account)."""
    invoice = setup_delinquent_invoice(account_id, clock_after_term, **overrides)
    invoice = write_off_invoice(invoice["id"])
    return invoice, get_account(account_id)
