"""Daily reconciliation shrink/variance, and optimistic concurrency (OCC)."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


class TestBeanUsageExpectedVsLedger:
    def _closed_recon(self, api, headers):
        shop = th.setup_latte_shop(api, headers=headers)
        member = th.new_member(api, headers=headers, email="usage@example.com", full_name="U")
        recon = th.open_reconciliation(api, shop["lot_id"], "2026-03-02", headers=headers)
        order = th.two_line_order(api, shop, member_id=member["id"], headers=headers)
        validate_success(api.pay_order(order["id"], headers))
        validate_success(api.fulfill_order(order["id"], headers))
        validate_success(api.log_waste(shop["lot_id"], {"grams": 20, "reason": "SPOILAGE"}, headers))
        th.submit_recon_count(api, recon["id"], counted_revenue_cents=1800,
                              counted_bean_on_hand_grams=900,
                              expected_version=recon["version"], headers=headers)
        return validate_success(api.close_reconciliation(recon["id"], headers))

    def test_ledger_usage_covers_sales_and_waste(self, api, manager_headers):
        """PRD 3.10: "the `ledger_usage_grams` is the `opening_bean_on_hand_grams`
        snapshot minus the lot's `on_hand_grams` at close — the chronological book
        value of every decrement since open, covering both sales draws and logged
        waste."
        PRD 3.10: "The `logged_waste_grams` is the lot's `waste_grams_total` at
        close minus the `opening_waste_grams` snapshot."

        Design: Difficulty/dual_variant_calc/bean_usage_expected_vs_ledger
        """
        recon = self._closed_recon(api, manager_headers)
        assert recon["ledger_usage_grams"] == 94, f"got {recon['ledger_usage_grams']}"
        assert recon["logged_waste_grams"] == 20, f"got {recon['logged_waste_grams']}"

    def test_expected_usage_excludes_waste_and_shrink(self, api, manager_headers):
        """PRD 3.10: "The `expected_usage_grams` is the `ledger_usage_grams` minus
        the `logged_waste_grams`, isolating the recipe- and sales-driven forward
        consumption."
        PRD 3.10: "The `shrink_grams` is the lot's `on_hand_grams` at close minus
        the `counted_bean_on_hand_grams`, the unexplained physical loss, which may
        be negative (found stock) or positive (lost stock)."

        Design: Difficulty/dual_variant_calc/bean_usage_expected_vs_ledger
        """
        recon = self._closed_recon(api, manager_headers)
        assert recon["expected_usage_grams"] == 74, f"got {recon['expected_usage_grams']}"
        assert recon["shrink_grams"] == 6, f"got {recon['shrink_grams']}"


def test_reconciliation_revenue_variance(api, manager_headers):
    """PRD 3.10: "The `expected_revenue_cents` is the sum of `total_cents` over
    every order that is both `PAID` and `FULFILLED` (voided or refunded orders are
    excluded), and the `revenue_variance_cents` is `counted_revenue_cents` minus
    `expected_revenue_cents` (which may be negative when the till is short or
    positive when it is over)."

    Design: Corner/calculations/reconciliation_revenue_variance_correct
    """
    member = th.member_with_lifetime(api, lifetime_points=1200, balance=0, headers=manager_headers)
    shop = th.setup_latte_shop(api, headers=manager_headers)
    order = th.two_line_order(api, shop, member_id=member["id"], headers=manager_headers)
    validate_success(api.pay_order(order["id"], manager_headers))
    validate_success(api.fulfill_order(order["id"], manager_headers))
    recon = th.open_reconciliation(api, shop["lot_id"], "2026-03-04", headers=manager_headers)
    th.submit_recon_count(api, recon["id"], counted_revenue_cents=1800,
                          counted_bean_on_hand_grams=900,
                          expected_version=recon["version"], headers=manager_headers)
    closed = validate_success(api.close_reconciliation(recon["id"], manager_headers))
    assert closed["expected_revenue_cents"] == 1764, f"got {closed['expected_revenue_cents']}"
    assert closed["revenue_variance_cents"] == 36, f"got {closed['revenue_variance_cents']}"


def test_close_without_count_rejected(api, manager_headers):
    """PRD 3.10: "A close is permitted only once a count has been submitted — that
    is, once `counted_revenue_cents` and `counted_bean_on_hand_grams` are set; a
    close attempted before then is rejected with `ERR_COUNT_NOT_SUBMITTED`."

    Design: Corner/state_machines/close_reconciliation_without_count_rejected
    """
    lot = th.new_bean_lot(api, origin="PERU", roast_level="LIGHT", received_grams=400,
                          par_grams=50, price_per_gram_cents=5, headers=manager_headers)
    recon = th.open_reconciliation(api, lot["id"], "2026-03-03", headers=manager_headers)
    resp = api.close_reconciliation(recon["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_COUNT_NOT_SUBMITTED.value)


def test_duplicate_business_date_rejected(api, manager_headers):
    """PRD 3.10: "The `business_date` must be unique across reconciliations; a
    duplicate is rejected with `ERR_DUPLICATE_BUSINESS_DATE`."

    Design: Corner/validations/duplicate_business_date_rejected
    """
    lot = th.new_bean_lot(api, origin="PERU", roast_level="LIGHT", received_grams=400,
                          par_grams=50, price_per_gram_cents=5, headers=manager_headers)
    th.open_reconciliation(api, lot["id"], "2026-03-06", headers=manager_headers)
    resp = api.create_reconciliation({"business_date": "2026-03-06", "bean_lot_id": lot["id"]},
                                     manager_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BUSINESS_DATE.value)


def test_reconciliation_submit_count_stale_version_rejected(api, manager_headers):
    """PRD 2.6: "Each accepted submission advances that `version`, so a submission
    whose `expected_reconciliation_version` no longer matches reflects an outdated
    draft and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/Cross-Cutting Complexity Layers/reconciliation_submit_count_stale_version_conflict
    """
    lot = th.new_bean_lot(api, origin="PERU", roast_level="LIGHT", received_grams=400,
                          par_grams=50, price_per_gram_cents=5, headers=manager_headers)
    recon = th.open_reconciliation(api, lot["id"], "2026-03-08", headers=manager_headers)
    stale_version = recon["version"]
    th.submit_recon_count(api, recon["id"], counted_revenue_cents=1000,
                          counted_bean_on_hand_grams=390,
                          expected_version=stale_version, headers=manager_headers)
    resp = api.submit_count(recon["id"], {"counted_revenue_cents": 1100,
                                          "counted_bean_on_hand_grams": 380,
                                          "expected_reconciliation_version": stale_version},
                            manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    assert resp.status_code == 412, f"got {resp.status_code}"


def test_subscription_create_stale_member_version_rejected(api, manager_headers):
    """PRD 2.6: "a request whose `expected_member_version` no longer matches
    reflects a view taken before another supersede; it is rejected with
    `ERR_STALE_VERSION` (HTTP 412) as a precondition failure, preventing the client
    from overwriting a subscription state it has not observed."

    Design: Corner/Cross-Cutting Complexity Layers/subscription_create_stale_member_version_conflict
    """
    member = th.new_member(api, headers=manager_headers, email="occsub@example.com", full_name="Occ")
    stale_version = member["version"]
    th.create_subscription(api, member["id"], stale_version, headers=manager_headers,
                           bean_origin="ETHIOPIA", frequency="MONTHLY", bags_per_cycle=2,
                           next_ship_at="2026-04-01T00:00:00Z")
    resp = api.create_subscription(
        {"member_id": member["id"], "bean_origin": "ETHIOPIA", "frequency": "WEEKLY",
         "bags_per_cycle": 1, "next_ship_at": "2026-04-08T00:00:00Z",
         "expected_member_version": stale_version}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    assert resp.status_code == 412, f"got {resp.status_code}"


def test_subscription_supersedes_prior_active(api, manager_headers):
    """PRD 3.8: "Creating it supersedes any prior `ACTIVE` subscription of the same
    member, transitioning that earlier subscription `ACTIVE -> SUPERSEDED` so that
    it stops billing and the new one becomes the member's active subscription; the
    member's `version` is incremented by one as part of this."

    Design: Corner/Cross-Cutting Complexity Layers/subscription_supersede_prior_active
    """
    member = th.new_member(api, headers=manager_headers, email="sup2@example.com", full_name="Sup2")
    sub1 = th.create_subscription(api, member["id"], member["version"], headers=manager_headers,
                                  bean_origin="ETHIOPIA", frequency="MONTHLY", bags_per_cycle=2,
                                  next_ship_at="2026-04-01T00:00:00Z")
    refreshed = validate_success(api.get_member(member["id"], manager_headers))
    sub2 = th.create_subscription(api, member["id"], refreshed["version"], headers=manager_headers,
                                  bean_origin="KENYA", frequency="WEEKLY", bags_per_cycle=1,
                                  next_ship_at="2026-04-08T00:00:00Z")
    fetched1 = validate_success(api.get_subscription(sub1["id"], manager_headers))
    fetched2 = validate_success(api.get_subscription(sub2["id"], manager_headers))
    assert fetched1["status"] == "SUPERSEDED", f"got {fetched1['status']}"
    assert fetched2["status"] == "ACTIVE", f"got {fetched2['status']}"
