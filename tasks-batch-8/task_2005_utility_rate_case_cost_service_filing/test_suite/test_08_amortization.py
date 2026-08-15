"""Amortization schedule generation, strict posting order, LIFO reversal, and
principal-coverage conservation (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_amortization_coverage_invariant,
    get_asset,
    setup_decided_with_tariffs_and_asset,
    setup_rates_implemented_with_asset,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

UF = TEST_USERS["utility_filer_alice"]


def _pending_entries(api, asset_id):
    data, _meta = validate_paginated(api.list_amortization_entries(
        UF, params={"regulatory_asset_id": asset_id, "status": "PENDING"}))
    return sorted(data, key=lambda e: e["period_index"])


def _all_entries(api, asset_id):
    """Every generated entry of the asset, in cascade generation order — the
    coverage invariant must see PENDING, POSTED, and REVERSED rows alike."""
    data, _meta = validate_paginated(api.list_amortization_entries(
        UF, params={"regulatory_asset_id": asset_id}))
    return sorted(data, key=lambda e: e["period_index"])


# ─── Difficulty: combinatorial_formula / amortization rounding ───────────────

def test_amortization_components_floor_plus_tail(api):
    """PRD §3.6: "At creation the server computes `monthly_base_cents` as the
    floor of `principal_cents` divided by `amortization_months`, and
    `final_month_cents` as `principal_cents` minus `monthly_base_cents`
    multiplied by one less than `amortization_months`" and "The rounding
    remainder is absorbed entirely by the last installment — the schedule floors
    each base installment and pushes the remainder to the tail, rather than
    rounding each installment independently."

    Design: Difficulty/combinatorial_formula/amortization_remainder_to_last_installment
    """
    s = setup_decided_with_tariffs_and_asset()
    asset = get_asset(s.ra1["id"])
    assert asset["monthly_base_cents"] == 2500000, "floor(10,000,001 / 4)"
    assert asset["final_month_cents"] == 2500001, "10,000,001 - 2,500,000*3"
    assert asset["status"] == "APPROVED_FOR_AMORTIZATION"


def test_amortization_entries_carry_remainder_in_last_period(api):
    """PRD §3.6: "Each generated entry has `amount_cents` equal to
    `monthly_base_cents` for every `period_index` less than `amortization_months`,
    and equal to `final_month_cents` for the final `period_index`" and "The
    invariant is that the sum of all generated `amount_cents` equals
    `principal_cents` exactly."
    PRD §2.3: "Rows minted in a single cascade share one `created_at` timestamp;
    their relative order is the cascade's generation order, pinned per collection:
    for AmortizationEntry the order is `period_index` ascending"

    Design: Difficulty/combinatorial_formula/amortization_remainder_to_last_installment
    """
    s = setup_decided_with_tariffs_and_asset()
    entries, meta = validate_paginated(api.list_amortization_entries(
        UF, params={"regulatory_asset_id": s.ra1["id"]}))
    assert meta["total_count"] == 4
    assert [e["period_index"] for e in entries] == [1, 2, 3, 4], (
        "cascade generation order pinned ascending"
    )
    assert [e["amount_cents"] for e in entries] == [2500000, 2500000, 2500000, 2500001]
    assert all(e["status"] == "PENDING" for e in entries)
    assert sum(e["amount_cents"] for e in entries) == 10000001, (
        "remainder absorbed by the tail, principal conserved exactly"
    )


# ─── Corner: posting preconditions ───────────────────────────────────────────

def test_post_before_asset_amortizing_rejected(api):
    """PRD §3.6: "Posting requires the entry in `PENDING`
    (`ERR_INVALID_AMORT_ENTRY_STATE`), the owning asset in `AMORTIZING`
    (`ERR_INVALID_ASSET_STATE`), and the entry's `period_index` equal to the
    minimum `period_index` among the asset's `PENDING` entries — posting out of
    order is `ERR_AMORTIZATION_OUT_OF_ORDER`."

    Design: Corner/state_machines/post_before_asset_amortizing_rejected
    """
    # DECIDED interlude: RA1 approved at issue-order (entries generated) but
    # implement-rates has NOT run, so the asset is not AMORTIZING yet.
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=False, classes="res", with_asset=True)
    am1 = _pending_entries(api, s.ra1["id"])[0]
    res = api.post_amortization_entry(am1["id"], UF)
    validate_error(res, ApiErrorId.ERR_INVALID_ASSET_STATE, expected_status=409)
    entry = validate_success(api.get_amortization_entry(am1["id"], UF), 200)
    assert entry["status"] == "PENDING"
    assert get_asset(s.ra1["id"])["amortized_to_date_cents"] == 0


def test_amort_entry_double_post_rejected(api):
    """PRD §3.6: "Posting requires the entry in `PENDING`
    (`ERR_INVALID_AMORT_ENTRY_STATE`)" and "A successful post stamps `posted_at`,
    moves the entry to `POSTED`, adds the entry's `amount_cents` to the asset's
    `amortized_to_date_cents`"

    Design: Corner/state_machines/amort_entry_double_post_rejected
    """
    s = setup_rates_implemented_with_asset()
    am1 = _pending_entries(api, s.ra1["id"])[0]
    posted = validate_success(api.post_amortization_entry(am1["id"], UF), 200)
    assert posted["status"] == "POSTED"
    res = api.post_amortization_entry(am1["id"], UF)
    validate_error(res, ApiErrorId.ERR_INVALID_AMORT_ENTRY_STATE, expected_status=409)
    assert get_asset(s.ra1["id"])["amortized_to_date_cents"] == 2500000, (
        "posted exactly once — no double-count"
    )


def test_amortization_out_of_order_posting_rejected(api):
    """PRD §3.6: "the entry's `period_index` equal to the minimum `period_index`
    among the asset's `PENDING` entries — posting out of order is
    `ERR_AMORTIZATION_OUT_OF_ORDER`."

    Design: Corner/calculations/amortization_out_of_order_posting_rejected
    """
    s = setup_rates_implemented_with_asset()
    pending = _pending_entries(api, s.ra1["id"])
    am1, am2 = pending[0], pending[1]
    res = api.post_amortization_entry(am2["id"], UF)
    validate_error(res, ApiErrorId.ERR_AMORTIZATION_OUT_OF_ORDER, expected_status=422)
    posted = validate_success(api.post_amortization_entry(am1["id"], UF), 200)
    assert posted["status"] == "POSTED"
    assert get_asset(s.ra1["id"])["amortized_to_date_cents"] == 2500000


def test_amortization_reversal_lifo_enforced(api):
    """PRD §3.6: "Reversal is LIFO: the entry must be in `POSTED`, the asset in
    `AMORTIZING` or `FULLY_AMORTIZED`, and the entry's `period_index` equal to the
    maximum `period_index` among the asset's `POSTED` entries — otherwise
    `ERR_REVERSAL_NOT_LATEST`."

    Design: Corner/calculations/amortization_reversal_lifo_enforced
    """
    s = setup_rates_implemented_with_asset()
    pending = _pending_entries(api, s.ra1["id"])
    am1, am2 = pending[0], pending[1]
    validate_success(api.post_amortization_entry(am1["id"], UF), 200)
    validate_success(api.post_amortization_entry(am2["id"], UF), 200)
    res = api.reverse_amortization_entry(am1["id"], UF)
    validate_error(res, ApiErrorId.ERR_REVERSAL_NOT_LATEST, expected_status=422)
    reversed2 = validate_success(api.reverse_amortization_entry(am2["id"], UF), 200)
    assert reversed2["status"] == "REVERSED"
    assert get_asset(s.ra1["id"])["amortized_to_date_cents"] == 2500000, (
        "only period 1 remains posted"
    )


def test_amortization_full_schedule_completes_asset(api):
    """PRD §3.6: "A successful post stamps `posted_at`, moves the entry to
    `POSTED`, adds the entry's `amount_cents` to the asset's
    `amortized_to_date_cents`, and if no `PENDING` entries remain the asset
    bubbles up to `FULLY_AMORTIZED`." and "The invariant is that the sum of all
    generated `amount_cents` equals `principal_cents` exactly."

    Design: Corner/calculations/amortization_full_schedule_completes_asset
    """
    s = setup_rates_implemented_with_asset()
    pending = _pending_entries(api, s.ra1["id"])
    last = None
    for entry in pending:
        last = validate_success(api.post_amortization_entry(entry["id"], UF), 200)
    assert last["status"] == "POSTED"
    assert last["amount_cents"] == 2500001, "final installment carries the remainder"
    asset = get_asset(s.ra1["id"])
    assert asset["status"] == "FULLY_AMORTIZED", "bubble-up on last PENDING posting"
    assert asset["amortized_to_date_cents"] == 10000001, "principal exactly, no drift"


# ─── Difficulty: compensating_invariant / principal coverage ─────────────────

def test_post_moves_amount_into_amortized_to_date(api):
    """PRD §3.6: "A successful post stamps `posted_at`, moves the entry to
    `POSTED`, adds the entry's `amount_cents` to the asset's
    `amortized_to_date_cents`, and if no `PENDING` entries remain the asset
    bubbles up to `FULLY_AMORTIZED`."

    Design: Difficulty/compensating_invariant/amortization_post_reverse_conserves_principal_coverage
    """
    s = setup_rates_implemented_with_asset()
    am1 = _pending_entries(api, s.ra1["id"])[0]
    assert am1["period_index"] == 1 and am1["amount_cents"] == 2500000
    posted = validate_success(api.post_amortization_entry(am1["id"], UF), 200)
    assert posted["status"] == "POSTED"
    asset = get_asset(s.ra1["id"])
    assert asset["amortized_to_date_cents"] == 2500000
    assert asset["status"] == "AMORTIZING", "one post of four never completes"
    assert_amortization_coverage_invariant(asset, _all_entries(api, s.ra1["id"]))


def test_reverse_restores_coverage_with_zero_drift(api):
    """PRD §3.6: "A successful reversal moves the entry to `REVERSED`, subtracts
    its `amount_cents` from `amortized_to_date_cents`, and if the asset was
    `FULLY_AMORTIZED` returns it to `AMORTIZING`."

    Design: Difficulty/compensating_invariant/amortization_post_reverse_conserves_principal_coverage
    """
    s = setup_rates_implemented_with_asset()
    am1 = _pending_entries(api, s.ra1["id"])[0]
    validate_success(api.post_amortization_entry(am1["id"], UF), 200)
    reversed1 = validate_success(api.reverse_amortization_entry(am1["id"], UF), 200)
    assert reversed1["status"] == "REVERSED"
    asset = get_asset(s.ra1["id"])
    assert asset["amortized_to_date_cents"] == 0, "post+reverse leaves zero drift"
    assert asset["status"] == "AMORTIZING"
    assert_amortization_coverage_invariant(asset, _all_entries(api, s.ra1["id"]))
