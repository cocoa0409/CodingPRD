"""Trust remittances: CASH vs NET dual-variant, per-payment fee rounding, period
validity, out-of-trust guard, execution trust decrement, and OCC staleness."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_net_equals_gross_minus_fee,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]
TRUSTEE = TEST_USERS["trust_accountant_headers"]

_JUNE = ("2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")


# --- dual_variant_calc / dv_remittance_cash_vs_net (queue A, >=2 tests) ---

def _pool_posted_and_reversed(api):
    return fixtures.setup_remittance_pool(api, management_fee_pct=20.0, payments=[
        {"amount": 50000, "received_date": "2026-06-05T00:00:00Z"},
        {"amount": 30000, "received_date": "2026-06-20T00:00:00Z", "reverse": True},
    ])


def test_remittance_cash_counts_reversed_payment(api):
    """PRD §3.9: "Under `CASH`, the pool includes every payment that was ever posted in the
    window, even one later reversed — a cash estimate."
    PRD §3.9: "The `management_fee_cents` is computed per payment — each included payment's
    `amount_cents` multiplied by the association's `management_fee_pct` divided by 100,
    rounded half-up to whole cents — and then summed across payments."

    Design: Difficulty/dual_variant_calc/dv_remittance_cash_vs_net
    """
    pool = _pool_posted_and_reversed(api)
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="CASH")
    assert rem["gross_amount_cents"] == 80000
    assert rem["management_fee_cents"] == 16000
    assert rem["net_amount_cents"] == 64000
    assert_net_equals_gross_minus_fee(rem)


def test_remittance_net_excludes_reversed_payment(api):
    """PRD §3.9: "Under `NET`, only payments still in `POSTED` at compute time are included,
    excluding any currently reversed, which yields a lower gross whenever a period payment
    was reversed."

    Design: Difficulty/dual_variant_calc/dv_remittance_cash_vs_net
    """
    pool = _pool_posted_and_reversed(api)
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="NET")
    assert rem["gross_amount_cents"] == 50000
    assert rem["management_fee_cents"] == 10000
    assert rem["net_amount_cents"] == 40000


# --- combinatorial_formula / cf_remittance_fee_rounding_mode_b (queue A, >=2 tests) ---

def _pool_fee_rounding(api):
    return fixtures.setup_remittance_pool(api, management_fee_pct=8.25, payments=[
        {"amount": 12345, "received_date": "2026-06-10T00:00:00Z"},
        {"amount": 6789, "received_date": "2026-06-15T00:00:00Z"},
    ])


def test_remittance_fee_rounded_per_payment(api):
    """PRD §2.5: "the management fee is rounded half-up **per payment** before the per-payment
    results are summed. Rounding is never deferred to the aggregate."

    Design: Difficulty/combinatorial_formula/cf_remittance_fee_rounding_mode_b
    """
    pool = _pool_fee_rounding(api)
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="CASH")
    # round(1018.4625)+round(560.0925)=1018+560=1578, not round(1578.555)=1579
    assert rem["management_fee_cents"] == 1578, rem["management_fee_cents"]


def test_remittance_fee_gross_and_net(api):
    """PRD §3.9: "The `gross_amount_cents` is the sum of `amount_cents` across the included
    payments." and "The `net_amount_cents` is `gross_amount_cents` minus `management_fee_cents`."

    Design: Difficulty/combinatorial_formula/cf_remittance_fee_rounding_mode_b
    """
    pool = _pool_fee_rounding(api)
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="CASH")
    assert rem["gross_amount_cents"] == 19134
    assert rem["net_amount_cents"] == 17556
    assert_net_equals_gross_minus_fee(rem)


# --- Queue B ---

def test_remittance_period_end_before_start_rejected(api):
    """PRD §3.9: "The period end must not be earlier than the period start, else
    `ERR_PERIOD_INVALID`."

    Design: Corner/validations/remittance_period_end_before_start_rejected
    """
    assoc = fixtures.create_association(api, name="Quay HOA")
    resp = api.create_remittance({
        "association_id": assoc["id"], "period_start": "2026-06-30T00:00:00Z",
        "period_end": "2026-06-01T00:00:00Z", "basis": "CASH",
        "expected_association_version": assoc["version"],
    }, TRUSTEE)
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVALID.value)


def test_remittance_execution_over_trust_rejected(api):
    """PRD §3.9: "A `TrustAccountant` executes a `PENDING` remittance by moving it to
    `REMITTED`, but only when the association's `trust_balance_cents` is at least the
    remittance's `gross_amount_cents`; an out-of-trust remittance is refused with
    `ERR_INVALID_AMOUNT`."

    Design: Corner/validations/remittance_remit_exceeds_trust_rejected
    """
    pool = _pool_posted_and_reversed(api)  # trust 50000
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="CASH")  # gross 80000
    resp = api.transition_remittance(rem["id"], "REMITTED", TRUSTEE)
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_remittance_execution_decreases_trust(api):
    """PRD §3.9: "Executing decreases the association's `trust_balance_cents` by
    `gross_amount_cents`."

    Design: Corner/validations/remittance_remit_decreases_trust
    """
    pool = fixtures.setup_remittance_pool(api, management_fee_pct=20.0, payments=[
        {"amount": 50000, "received_date": "2026-06-05T00:00:00Z"},
    ])  # trust 50000
    rem = fixtures.create_remittance(api, pool["association"]["id"], _JUNE[0], _JUNE[1],
                                     pool["association_version"], basis="NET")
    assert rem["gross_amount_cents"] == 50000
    assert rem["net_amount_cents"] == 40000
    remitted = validate_success(api.transition_remittance(rem["id"], "REMITTED", TRUSTEE))
    assert remitted["status"] == "REMITTED"
    assoc = get_success_data(api.get_association(pool["association"]["id"], TRUSTEE))
    assert assoc["trust_balance_cents"] == 0


def test_remittance_create_stale_association_version_rejected(api):
    """PRD §2.6: "A remittance create must carry `expected_association_version`, the client's
    last observed `version` of the target `Association`. If it does not equal the
    association's current `version` — because another writer has changed the trust position,
    for example by posting a payment or remitting a prior remittance — the create is refused
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_remittance_create_stale_association_version
    """
    assoc = fixtures.create_association(api, name="Yarn HOA")
    v0 = assoc["version"]
    fixtures.create_remittance(api, assoc["id"], _JUNE[0], _JUNE[1], v0, basis="CASH")  # bumps to 2
    resp = api.create_remittance({
        "association_id": assoc["id"], "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-07-31T00:00:00Z", "basis": "CASH",
        "expected_association_version": v0,
    }, TRUSTEE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
