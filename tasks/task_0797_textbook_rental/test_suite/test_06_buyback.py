"""The buyback flow: quote pricing, the ACCEPTED->PAID / ACCEPTED->REVISED fork, the
paid cascade, expiry boundary, lifecycle guards, and requote OCC."""
from test_helpers import (
    validate_success, validate_error,
    create_catalog_item_payload, create_customer_payload, create_buyback_quote_payload,
    inspect_buyback_payload, respond_revision_payload,
    TEST_USERS, make_customer_headers,
    create_catalog_item, create_customer, get_customer, get_buyback_quote,
    setup_accepted_buyback, setup_revised_buyback,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Dual-variant buyback_price: quoted vs assessed ───────────────────

def test_buyback_quoted_vs_assessed_divergence(api):
    """PRD 3.7: "the title's `buyback_base_cents` multiplied by the condition multiplier
    for the declared condition — 1.0 for `NEW`, 0.9 for `LIKE_NEW`, 0.75 for `GOOD`, and
    0.5 for `ACCEPTABLE` — rounded half up to whole cents."
    PRD 3.7: "When the assessed condition differs from the declared condition, the quote
    instead moves from `ACCEPTED` to `REVISED` and a `revised_price_cents` is computed by
    the same buyback-price rule but keyed on the assessed condition".

    Design: Difficulty/dual_variant_calc/buyback_quoted_vs_assessed_divergence
    """
    ctx = setup_revised_buyback(declared_condition="LIKE_NEW", assessed_condition="GOOD", email="bd1@x.com")
    quote = ctx["quote"]
    assert quote["status"] == "REVISED"
    assert quote["quoted_price_cents"] == 2700  # 3000 * 0.9


def test_buyback_revised_price_uses_assessed_condition(api):
    """PRD 3.7: "a `revised_price_cents` is computed by the same buyback-price rule but
    keyed on the assessed condition — generally a lower offer — while no credit or
    inventory is created yet."

    Design: Difficulty/dual_variant_calc/buyback_quoted_vs_assessed_divergence
    """
    ctx = setup_revised_buyback(declared_condition="LIKE_NEW", assessed_condition="GOOD", email="bd2@x.com")
    assert ctx["quote"]["revised_price_cents"] == 2250  # 3000 * 0.75


# ─── Depth-2 paid cascade: PAID creates unit + credits wallet ─────────

def test_buyback_paid_status_and_price(api):
    """PRD 3.7: "When the assessed condition equals the seller's `declared_condition`,
    the quote is paid: `status` moves from `ACCEPTED` to `PAID`, `paid_price_cents` is set
    to `quoted_price_cents`".

    Design: Difficulty/transitive_cascade/buyback_paid_cascade_depth2
    """
    ctx = setup_accepted_buyback(declared_condition="NEW", email="bp1@x.com")
    paid = validate_success(api.inspect_buyback_quote(
        ctx["quote"]["id"], inspect_buyback_payload("NEW"), WAREHOUSE), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_price_cents"] == 3000  # 3000 * 1.0


def test_buyback_paid_creates_unit_and_credits_wallet(api):
    """PRD 3.7: "a new `InventoryUnit` is created for the title with `condition_grade`
    equal to the assessed condition and `status` `AVAILABLE` (its identifier recorded in
    the quote's `inventory_unit_id`), and a `WalletTransaction` of `kind` `BUYBACK_CREDIT`
    is appended crediting the seller the positive `quoted_price_cents`."

    Design: Difficulty/transitive_cascade/buyback_paid_cascade_depth2
    """
    ctx = setup_accepted_buyback(declared_condition="NEW", email="bp2@x.com")
    paid = validate_success(api.inspect_buyback_quote(
        ctx["quote"]["id"], inspect_buyback_payload("NEW"), WAREHOUSE), 200)
    assert paid["inventory_unit_id"] is not None
    assert get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 3000


# ─── Accept rejected exactly at the expiry instant ────────────────────

def test_accept_rejected_at_expiry_instant(api):
    """PRD 3.7: "Accepting a quote requires it to be in `QUOTED` status, else
    `ERR_QUOTE_NOT_OPEN`, and requires the logical clock to be strictly before
    `quote_expires_at`; at or after that instant the quote is expired and acceptance is
    refused with `ERR_QUOTE_EXPIRED`."

    Design: Difficulty/boundary_precision_check/buyback_accept_rejected_exactly_at_expiry_instant
    """
    cat = create_catalog_item()
    cust = create_customer(email="ex1@x.com")
    headers = make_customer_headers(cust["id"])
    quote = validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "NEW", cust["version"]), headers), 201)
    # Advance the clock to exactly quote_expires_at; accept at that instant is expired.
    validate_success(api.set_clock({"to_iso8601": quote["quote_expires_at"]}, ADMIN), 200)
    res = api.accept_buyback_quote(quote["id"], headers)
    validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)


def test_accept_succeeds_strictly_before_expiry(api):
    """PRD 3.7: "requires the logical clock to be strictly before `quote_expires_at`".
    PRD 3.7: "Acceptance moves `status` from `QUOTED` to `ACCEPTED` with no ledger change
    yet."

    Design: Difficulty/boundary_precision_check/buyback_accept_rejected_exactly_at_expiry_instant
    """
    cat = create_catalog_item()
    cust = create_customer(email="ex2@x.com")
    headers = make_customer_headers(cust["id"])
    quote = validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "NEW", cust["version"]), headers), 201)
    # Default clock (2026-03-01) is strictly before quote_expires_at.
    accepted = validate_success(api.accept_buyback_quote(quote["id"], headers), 200)
    assert accepted["status"] == "ACCEPTED"


# ─── Corner: buyback lifecycle guards ─────────────────────────────────

def test_accept_non_quoted_buyback_returns_409(api):
    """PRD 3.7: "Accepting a quote requires it to be in `QUOTED` status, else
    `ERR_QUOTE_NOT_OPEN`".

    Design: Corner/state_machines/accept_non_quoted_buyback_returns_409
    """
    ctx = setup_accepted_buyback(declared_condition="GOOD", email="anq@x.com")  # already ACCEPTED
    res = api.accept_buyback_quote(ctx["quote"]["id"], ctx["headers"])
    validate_error(res, "ERR_QUOTE_NOT_OPEN", expected_status=409)


def test_inspect_buyback_not_accepted_returns_409(api):
    """PRD 3.7: "A `WarehouseAgent` then inspects the received copy against an accepted
    quote, which requires the quote to be in `ACCEPTED` status, else
    `ERR_QUOTE_NOT_ACCEPTED`."

    Design: Corner/state_machines/inspect_buyback_not_accepted_returns_409
    """
    cat = create_catalog_item()
    cust = create_customer(email="iba@x.com")
    headers = make_customer_headers(cust["id"])
    quote = validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "GOOD", cust["version"]), headers), 201)  # QUOTED
    res = api.inspect_buyback_quote(quote["id"], inspect_buyback_payload("GOOD"), WAREHOUSE)
    validate_error(res, "ERR_QUOTE_NOT_ACCEPTED", expected_status=409)


def test_respond_revision_not_revised_returns_409(api):
    """PRD 3.7: "Responding requires the quote to be in `REVISED` status, else
    `ERR_QUOTE_NOT_REVISED`, and carries an `action` of either `ACCEPT` or `DECLINE`."

    Design: Corner/state_machines/respond_revision_not_revised_returns_409
    """
    ctx = setup_accepted_buyback(declared_condition="GOOD", email="rrn@x.com")  # ACCEPTED, never revised
    res = api.respond_revision_buyback_quote(
        ctx["quote"]["id"], respond_revision_payload("ACCEPT"), ctx["headers"])
    validate_error(res, "ERR_QUOTE_NOT_REVISED", expected_status=409)


def test_buyback_revised_decline_terminal_no_credit(api):
    """PRD 3.7: "Declining the revision moves `status` from `REVISED` to `DECLINED`: the
    copy is conceptually returned to the seller, no credit is paid, and no `InventoryUnit`
    is created."

    Design: Corner/state_machines/buyback_revised_decline_terminal_no_credit
    """
    ctx = setup_revised_buyback(declared_condition="NEW", assessed_condition="GOOD", email="brd@x.com")
    declined = validate_success(api.respond_revision_buyback_quote(
        ctx["quote"]["id"], respond_revision_payload("DECLINE"), ctx["headers"]), 200)
    assert declined["status"] == "DECLINED"
    assert declined["inventory_unit_id"] is None
    assert get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 0


# ─── Corner: requote optimistic concurrency (OCC) ─────────────────────

def test_buyback_requote_stale_customer_version_returns_412(api):
    """PRD 2.7: "If `expected_customer_version` does not equal the stored
    `Customer.version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 2.7: "requesting a quote supersedes any prior open quote for the same title and
    advances the seller's `Customer.version`".

    Design: Corner/cross_cutting_complexity_layers/buyback_requote_stale_customer_version_returns_412
    """
    cat = create_catalog_item()
    cust = create_customer(email="occ1@x.com")
    headers = make_customer_headers(cust["id"])
    v0 = cust["version"]
    validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "GOOD", v0), headers), 201)  # bumps Customer.version
    res = api.create_buyback_quote(create_buyback_quote_payload(cat["id"], "LIKE_NEW", v0), headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_buyback_requote_fresh_version_supersedes_prior(api):
    """PRD 3.7: "requesting a new quote for a `(customer_id, catalog_item_id)` pair
    supersedes any prior quote still in `QUOTED` status for that same pair by moving it to
    `SUPERSEDED`, and the create advances the seller's `Customer.version` by one."

    Design: Corner/cross_cutting_complexity_layers/buyback_requote_fresh_version_supersedes_prior
    """
    cat = create_catalog_item()
    cust = create_customer(email="occ2@x.com")
    headers = make_customer_headers(cust["id"])
    q1 = validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "GOOD", cust["version"]), headers), 201)
    v1 = get_customer(cust["id"])["version"]  # re-read the advanced version
    q2 = validate_success(api.create_buyback_quote(
        create_buyback_quote_payload(cat["id"], "LIKE_NEW", v1), headers), 201)
    assert get_buyback_quote(q1["id"])["status"] == "SUPERSEDED"
    assert get_buyback_quote(q2["id"])["status"] == "QUOTED"
