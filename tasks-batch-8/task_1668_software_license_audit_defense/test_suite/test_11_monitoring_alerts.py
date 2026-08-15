"""Monitoring alerts: suppression capture, worsen-and-reopen on the same row,
expiry threshold boundaries, and lifecycle errors (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_alert,
    confirm_deployment,
    create_deployment,
    create_entitlement,
    create_product,
    create_vendor,
    get_license_position,
    list_product_alerts,
    set_clock,
    setup_product_with_gap,
    validate_error,
    validate_success,
)


def _setup_open_over_deployment_alert():
    """Product entitled 10 with 12 CONFIRMED deployed: gap 2, ratio 1.2 -> MATERIAL,
    so one OVER_DEPLOYMENT alert is OPEN at WARNING."""
    ctx = setup_product_with_gap(entitled=10, deployed=12)
    alerts = list_product_alerts(ctx["product"]["id"])
    assert len(alerts) == 1, "exactly one alert row exists for the product"
    alert = alerts[0]
    assert alert["alert_type"] == "OVER_DEPLOYMENT"
    assert alert["status"] == "OPEN"
    assert alert["severity"] == "WARNING", "MATERIAL gap severity maps to WARNING"
    assert alert["triggered_value"] == 2
    assert alert["threshold_value"] == 0
    ctx["alert"] = alert
    return ctx


class TestSuppressWorsenReopen:
    def test_alert_suppression_captures_triggered_value(self, api,
                                                        sam_manager_headers):
        """PRD §3.9: "A `SAMManager` may suppress an `OPEN` alert by recording a
        mandatory `suppression_reason`; suppression captures the current
        `triggered_value` into `suppressed_value`, which remains null unless the
        alert is `SUPPRESSED`."
        PRD §3.9: "Alert creation is an upsert: at most one alert per product and
        `alert_type` exists in `OPEN` or `SUPPRESSED` status at any time, stamped
        with its `severity`, `triggered_value`, and `threshold_value` when the
        triggering recompute or clock sweep creates it."

        Design: Difficulty/compensating_invariant/alert_suppress_worsen_reopen_conserves_cardinality
        """
        ctx = _setup_open_over_deployment_alert()
        alert = ctx["alert"]
        assert alert["suppressed_value"] is None, \
            "suppressed_value stays null while the alert is OPEN"

        suppressed = validate_success(
            api.suppress_alert(
                alert["id"],
                {"suppression_reason": "True-up purchase order already submitted"},
                sam_manager_headers), 200)
        assert_alert(suppressed)
        assert suppressed["id"] == alert["id"]
        assert suppressed["status"] == "SUPPRESSED"
        assert suppressed["suppressed_value"] == 2, \
            "suppression captures the current triggered_value"

    def test_worsened_gap_reopens_same_alert_row(self, api, sam_manager_headers):
        """PRD §3.9: "Suppression is not silence forever: each later re-evaluation
        compares the fresh `triggered_value` against `suppressed_value`, and when
        the value has worsened strictly beyond it — a larger gap for
        `OVER_DEPLOYMENT`, or fewer days to expiry for `ENTITLEMENT_EXPIRING` — the
        same alert row re-opens to `OPEN` with its `id` unchanged and
        `suppressed_value` cleared."
        PRD §3.9: "Alert creation is an upsert: at most one alert per product and
        `alert_type` exists in `OPEN` or `SUPPRESSED` status at any time"

        Design: Difficulty/compensating_invariant/alert_suppress_worsen_reopen_conserves_cardinality
        """
        ctx = _setup_open_over_deployment_alert()
        alert = ctx["alert"]
        validate_success(
            api.suppress_alert(alert["id"], {"suppression_reason": "order placed"},
                               sam_manager_headers), 200)

        # Worsen the gap from 2 to 7 (12 + 5 deployed against 10 entitled).
        extra = create_deployment(ctx["product"]["id"], measured_quantity=5,
                                  measured_on="2026-07-16T00:00:00Z")
        confirm_deployment(extra["id"])

        alerts = list_product_alerts(ctx["product"]["id"])
        assert len(alerts) == 1, \
            "the same row re-opens; no duplicate alert is inserted"
        reopened = alerts[0]
        assert reopened["id"] == alert["id"]
        assert reopened["status"] == "OPEN"
        assert reopened["triggered_value"] == 7, "gap worsened 2 -> 7, beyond 2"
        assert reopened["suppressed_value"] is None, "re-open clears suppressed_value"
        assert reopened["severity"] == "CRITICAL", \
            "ratio 17/10 = 1.7 >= 1.25 makes the gap CRITICAL"


class TestSuppressErrors:
    def test_alert_suppress_twice_rejected(self, api, sam_manager_headers):
        """PRD §3.9: "Suppressing an alert that is not `OPEN` is rejected with
        `ERR_ALERT_INVALID_STATE`."

        Design: Corner/state_machines/alert_suppress_twice_rejected
        """
        ctx = _setup_open_over_deployment_alert()
        alert = ctx["alert"]
        validate_success(
            api.suppress_alert(alert["id"], {"suppression_reason": "order placed"},
                               sam_manager_headers), 200)

        resp = api.suppress_alert(alert["id"],
                                  {"suppression_reason": "second attempt"},
                                  sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ALERT_INVALID_STATE)

    def test_alert_not_found_on_suppress(self, api, sam_manager_headers):
        """PRD §3.9: "Alerts are listed per product with optional `status` and
        `alert_type` filters, and unknown alert identifiers surface as
        `ERR_ALERT_NOT_FOUND`."

        Design: Corner/errors/alert_not_found_on_suppress
        """
        resp = api.suppress_alert(NON_EXISTENT_UUID,
                                  {"suppression_reason": "no such alert"},
                                  sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ALERT_NOT_FOUND)


class TestEntitlementExpiringBoundary:
    def test_expiry_alert_fires_at_exactly_30_days(self, api, sam_manager_headers):
        """PRD §3.9: "`ENTITLEMENT_EXPIRING` fires when some `ACTIVE` entitlement
        of the product will reach its `effective_to` within the next 30 days,
        measured in whole days as the floor of the difference between
        `effective_to` and the current clock: a record with exactly 30 days
        remaining does trigger the alert, 31 days does not, and the day of expiry
        itself still counts. Its `triggered_value` carries the smallest
        days-to-expiry among the matching records, its `threshold_value` is 30, and
        its `severity` is always `WARNING`."
        PRD §2.4: "Setting the clock triggers the entitlement status sweep (every
        `SCHEDULED` record whose `effective_from` has been reached becomes `ACTIVE`,
        and every `ACTIVE` record whose `effective_to` has been reached or passed
        becomes `EXPIRED`), the `ENTITLEMENT_EXPIRING` alert sweep, position
        recomputation for affected products, and recomputation of the audit case
        rollups that depend on them."

        Design: Corner/calculations/expiry_alert_fires_at_exactly_30_days
        """
        vendor = create_vendor()
        product_1 = create_product(vendor["id"], name="Prod 1")
        product_2 = create_product(vendor["id"], name="Prod 2")
        # At the 2026-08-01 logical clock: 2026-08-31 is exactly 30 days out;
        # 2026-09-01 is 31 days out.
        create_entitlement(product_1["id"], purchase_order_number="PO-1",
                           quantity=10, effective_to="2026-08-31T00:00:00Z")
        create_entitlement(product_2["id"], purchase_order_number="PO-2",
                           quantity=10, effective_to="2026-09-01T00:00:00Z")

        set_clock("2026-08-01T00:00:00Z")

        alerts_1 = list_product_alerts(product_1["id"])
        assert len(alerts_1) == 1, "exactly 30 days remaining triggers the alert"
        alert = alerts_1[0]
        assert_alert(alert)
        assert alert["alert_type"] == "ENTITLEMENT_EXPIRING"
        assert alert["status"] == "OPEN"
        assert alert["triggered_value"] == 30
        assert alert["threshold_value"] == 30
        assert alert["severity"] == "WARNING"

        alerts_2 = list_product_alerts(product_2["id"])
        assert alerts_2 == [], "31 days out does not trigger the alert"
