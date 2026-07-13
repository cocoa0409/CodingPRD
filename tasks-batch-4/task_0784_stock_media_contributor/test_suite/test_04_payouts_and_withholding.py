"""Payout requests: gross/net, per-line withholding, threshold, suspension, and OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_contributor_headers,
    onboard_active_contributor, get_contributor, get_contributor_version,
    add_earning_adjustment,
    setup_active_contributor_with_available_balance,
    setup_payout_ready_foreign, setup_suspended_contributor,
    assert_payout,
)

FINANCE = TEST_USERS["finance_headers"]


def _request_payout(api, contributor_id, version):
    ch = make_contributor_headers(contributor_id)
    return api.create_payout(contributor_id, {"expected_contributor_version": version}, ch)


def test_domestic_w9_payout_has_zero_withholding(api):
    """PRD §3.7: "a `W9` (domestic) filer withholds nothing, so the rate is 0.00 and the net
    equals the gross".

    Design: Corner/calculations/corner_withholding_domestic_w9_zero
    """
    cid, ver = setup_active_contributor_with_available_balance(api, adjustment_cents=10000)
    p = validate_success(_request_payout(api, cid, ver), 201)
    assert_payout(p)
    assert p["gross_amount_cents"] == 10000
    assert p["withholding_cents"] == 0
    assert p["net_amount_cents"] == 10000


def test_stale_contributor_version_rejects_second_payout(api):
    """PRD §2.6: "If they do not match — meaning some other operation (a prior payout, an earnings
    settlement, a reversal, or an adjustment) has advanced the contributor's `version` since the
    client last read it — the request is rejected with `ERR_STALE_CONTRIBUTOR_VERSION` (HTTP 412)
    before any balance arithmetic is performed".

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_contributor_version
    """
    c = onboard_active_contributor(api, tax_id="US-12")
    add_earning_adjustment(api, c["id"], 20000, reason="s")
    v0 = get_contributor_version(api, c["id"])
    first = validate_success(_request_payout(api, c["id"], v0), 201)
    assert first["status"] == "REQUESTED"
    validate_error(_request_payout(api, c["id"], v0), ApiErrorId.ERR_STALE_CONTRIBUTOR_VERSION.value)


def test_payout_gross_is_available_balance_snapshot(api):
    """PRD §3.7: "The payout's gross is a snapshot of the contributor's `available_balance_cents`
    at request time".

    Design: Difficulty/dual_variant_calc/payout_gross_vs_net
    """
    cid, ver = setup_payout_ready_foreign(api, treaty_rate_pct=None)  # 2x375 downloads + 10000 adj
    p = validate_success(_request_payout(api, cid, ver), 201)
    assert p["gross_amount_cents"] == 10750


def test_payout_net_is_gross_minus_withholding(api):
    """PRD §3.7: "`net_amount_cents` is `gross_amount_cents` minus `withholding_cents` — equal to
    the gross for a domestic contributor and strictly less than the gross for any foreign
    contributor with a nonzero rate."

    Design: Difficulty/dual_variant_calc/payout_gross_vs_net
    """
    cid, ver = setup_payout_ready_foreign(api, treaty_rate_pct=None)
    p = validate_success(_request_payout(api, cid, ver), 201)
    assert p["withholding_cents"] == 226
    assert p["net_amount_cents"] == 10524


def test_withholding_rounds_per_line_then_sums(api):
    """PRD §3.7: "The rate is applied **per contributing line, rounded to a whole cent per line,
    and only then summed** — for each of the contributor's downloads whose `earning_status` is
    `AVAILABLE`, the platform multiplies that download's `royalty_amount_cents` by the withholding
    rate and rounds the product to the nearest cent using round half up, and `withholding_cents`
    is the sum of those per-line rounded amounts."

    Design: Difficulty/combinatorial_formula/withholding_round_per_line_then_sum
    """
    cid, ver = setup_payout_ready_foreign(api, treaty_rate_pct=None)  # two 375 lines at 0.30
    p = validate_success(_request_payout(api, cid, ver), 201)
    # round(112.5)=113 per line, summed -> 226 (not round(750*0.30)=225).
    assert p["withholding_cents"] == 226


def test_adjustment_is_not_withheld_in_net(api):
    """PRD §3.7: "Any earning-adjustment credits that form part of the gross are **not** withheld;
    withholding is drawn only from download earning lines."

    Design: Difficulty/combinatorial_formula/withholding_round_per_line_then_sum
    """
    cid, ver = setup_payout_ready_foreign(api, treaty_rate_pct=None)  # gross 10750, only 750 withheld-eligible
    p = validate_success(_request_payout(api, cid, ver), 201)
    assert p["gross_amount_cents"] == 10750
    assert p["net_amount_cents"] == 10524, "only the two 375 download lines are withheld, not the 10000 adjustment"


def test_payout_at_exactly_threshold_succeeds(api):
    """PRD §3.7: "that gross must be at least the payout threshold of 10,000 cents ($100.00), and a
    request whose available balance falls short is rejected with `ERR_BELOW_PAYOUT_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/payout_threshold_exact_10000_vs_9999
    """
    cid, ver = setup_active_contributor_with_available_balance(api, adjustment_cents=10000)
    p = validate_success(_request_payout(api, cid, ver), 201)
    assert p["gross_amount_cents"] == 10000
    assert p["status"] == "REQUESTED"


def test_payout_one_cent_below_threshold_rejected(api):
    """PRD §3.7: "that gross must be at least the payout threshold of 10,000 cents ($100.00), and a
    request whose available balance falls short is rejected with `ERR_BELOW_PAYOUT_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/payout_threshold_exact_10000_vs_9999
    """
    cid, ver = setup_active_contributor_with_available_balance(api, adjustment_cents=9999)
    validate_error(_request_payout(api, cid, ver), ApiErrorId.ERR_BELOW_PAYOUT_THRESHOLD.value)


def test_suspended_contributor_payout_blocked_by_suspension(api):
    """PRD §3.7: "the suspension gate (a `SUSPENDED` contributor is rejected with
    `ERR_CONTRIBUTOR_SUSPENDED`), and the fiscal minimum."

    Design: Difficulty/priority_pair_validation_conflict/payout_suspended_beats_below_threshold
    """
    cid, ver = setup_suspended_contributor(api)  # available_balance 0, would also fail threshold
    validate_error(_request_payout(api, cid, ver), ApiErrorId.ERR_CONTRIBUTOR_SUSPENDED.value)


def test_suspension_precedes_threshold_check(api):
    """PRD §2.9: "suspension gating (`ERR_CONTRIBUTOR_SUSPENDED`, 403) ... and finally the two
    fiscal checks: the payout threshold (`ERR_BELOW_PAYOUT_THRESHOLD`, 422)".

    Design: Difficulty/priority_pair_validation_conflict/payout_suspended_beats_below_threshold
    """
    cid, ver = setup_suspended_contributor(api)
    contributor = get_contributor(api, cid)
    assert contributor["onboarding_status"] == "SUSPENDED"
    assert contributor["strike_count"] == 3
    assert contributor["available_balance_cents"] == 0
    # Balance 0 < 10000 would trip the threshold, yet suspension (higher priority) is what surfaces.
    validate_error(_request_payout(api, cid, ver), ApiErrorId.ERR_CONTRIBUTOR_SUSPENDED.value)
