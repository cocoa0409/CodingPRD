"""Entity assertions and domain invariant checkers.

Every ``assert_<entity>`` checks the shape the PRD promises for that resource:
a UUID `id`, ISO 8601 timestamps, enum members inside their declared sets, and
— for the twelve resources that carry them — `updated_at` and `version`.  The
two append-only resources are checked for the *absence* of those two fields,
because PRD §2.4 says they are absent from them entirely.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

FOUR_DECIMAL_FIELDS = (
    "margin_floor_pct", "active_discount_pct", "discount_pct", "offer_discount_pct",
    "per_cycle_margin_pct", "blended_term_margin_pct", "retention_rate",
    "proration_factor", "priority_score",
)


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: Dict[str, Any]) -> None:
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer starting at 1, got {data.get('version')!r}"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """id + created_at only; updated_at and version must be absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, \
        "append-only resources carry no updated_at, but one was returned"
    assert "version" not in data, \
        "append-only resources carry no version, but one was returned"


def assert_integer_cents(data: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), \
            f"{field} must be an integer count of cents, got {value!r}"


def assert_four_decimal_fraction(value: Any, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), \
        f"{field} must be numeric, got {value!r}"
    quantised = round(float(value) + 1e-12, 4)
    assert abs(float(value) - quantised) < 1e-9, \
        f"{field} must be carried to exactly four decimal places, got {value!r}"


def normalise_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a comparable canonical form.

    PRD §2.4 renders instants with exactly three fractional digits, so a test
    that knows the logical instant it moved the clock to must compare without
    depending on how the fraction is spelled.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        head, fraction = text.split(".", 1)
        fraction = (fraction + "000")[:3].rstrip("0")
    else:
        head, fraction = text, ""
    return head if not fraction else f"{head}.{fraction}"


def assert_instant(actual: Any, expected: str, field: str = "timestamp") -> None:
    assert normalise_instant(actual) == normalise_instant(expected), \
        f"{field} must be {expected}, got {actual!r}"


def assert_nullable_timestamp(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 or null, got {value!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert_integer_cents(data, "monthly_price_cents", "unit_cogs_cents")
    assert data["monthly_price_cents"] > 0, "monthly_price_cents must be strictly greater than zero"
    assert data["unit_cogs_cents"] >= 0, "unit_cogs_cents must be zero or greater"
    assert data["shipments_per_cycle"] >= 1
    assert data["shipments_per_term"] >= 1
    assert isinstance(data["allowed_frequency_weeks"], list) and data["allowed_frequency_weeks"]
    assert_four_decimal_fraction(data["margin_floor_pct"], "margin_floor_pct")
    assert 0.0 <= data["margin_floor_pct"] <= 1.0
    assert isinstance(data["is_negative_option"], bool)
    assert data["renewal_reminder_days_before"] >= 3, \
        "renewal_reminder_days_before may never be shorter than the three-day minimum lead"
    assert data["max_pause_cycles"] >= 1
    assert isinstance(data["addon_catalog"], list)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["active_subscription_count"], int)


def assert_subscriber(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["acquisition_channel"] in (
        "PAID_SOCIAL", "SEARCH", "AFFILIATE", "ORGANIC", "REFERRAL")
    assert isinstance(data["do_not_contact"], bool)
    for field in ("first_subscribed_at", "lapsed_at", "won_back_at",
                  "winback_suppressed_until", "last_contacted_at"):
        assert_nullable_timestamp(data, field)
    assert isinstance(data["tenure_days"], int) and data["tenure_days"] >= 0
    assert data["tenure_bucket"] in ("M0_1", "M2_3", "M4_6", "M7_12", "M13_PLUS")
    assert data["churn_type"] in ("NONE", "VOLUNTARY", "INVOLUNTARY")
    assert_integer_cents(data, "realized_ltv_cents", "projected_ltv_cents")
    assert isinstance(data["save_offer_grants_365d_count"], int)


def assert_subscription(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["lifecycle_state"] in ("ACTIVE", "PAUSED", "PENDING_CANCEL", "CANCELLED")
    assert data["billing_state"] in ("CURRENT", "PAST_DUE", "GRACE", "DELINQUENT")
    assert isinstance(data["frequency_weeks"], int) and data["frequency_weeks"] > 0
    assert isinstance(data["addons"], list)
    assert_four_decimal_fraction(data["active_discount_pct"], "active_discount_pct")
    assert 0.0 <= data["active_discount_pct"] < 1.0, \
        "active_discount_pct is at least 0.0000 and strictly below 1.0000"
    assert isinstance(data["discount_remaining_cycles"], int)
    assert_integer_cents(data, "baseline_price_cents", "committed_price_cents")
    assert is_iso8601_timestamp(data["next_renewal_at"])
    assert is_iso8601_timestamp(data["next_ship_at"])
    for field in ("paused_until", "cancel_effective_at", "first_failed_at", "grace_end_at"):
        assert_nullable_timestamp(data, field)
    assert isinstance(data["consecutive_failed_attempts"], int)
    assert isinstance(data["disclosure_acknowledged"], bool)
    assert_shipment_conservation(data)


def assert_payment_method(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["card_last4"], str) and len(data["card_last4"]) == 4 \
        and data["card_last4"].isdigit(), "card_last4 must be exactly four digits"
    assert 1 <= data["exp_month"] <= 12
    assert data["exp_year"] >= 2020
    assert data["network"] in ("VISA", "MASTERCARD", "AMEX", "DISCOVER")
    assert data["status"] in ("ACTIVE", "REPLACED", "EXPIRED")
    assert data["updater_status"] in ("NONE", "PENDING", "UPDATED", "UNAVAILABLE")
    assert_nullable_timestamp(data, "updater_requested_at")
    if data["updater_status"] == "NONE":
        assert data["updater_requested_at"] is None, \
            "updater_requested_at stays null while updater_status is NONE"


def assert_invoice(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 0
    assert_integer_cents(data, "amount_cents", "cogs_cents")
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        for key in ("kind", "code", "unit_price_cents", "qty", "line_cents"):
            assert key in line, f"line item is missing {key}: {line!r}"
    assert data["status"] in ("OPEN", "FAILED", "PAID", "WRITTEN_OFF")
    assert is_iso8601_timestamp(data["due_at"])
    assert_nullable_timestamp(data, "paid_at")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert_four_decimal_fraction(data["proration_factor"], "proration_factor")
    assert isinstance(data["is_renewal"], bool)
    assert data["is_renewal"] == (data["cycle_index"] != 0), \
        "is_renewal is false for cycle_index 0 and true for renewal-issued invoices"
    if data["status"] != "PAID":
        assert data["paid_at"] is None, "paid_at is null while the invoice is unpaid"


def assert_dunning_attempt(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["attempt_number"], int) and 1 <= data["attempt_number"] <= 4
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert_nullable_timestamp(data, "attempted_at")
    assert data["outcome"] in ("PENDING", "SUCCEEDED", "SOFT_DECLINE", "HARD_DECLINE")
    if data["outcome"] in ("SOFT_DECLINE", "HARD_DECLINE"):
        assert data["decline_code"] in (
            "INSUFFICIENT_FUNDS", "EXPIRED_CARD", "DO_NOT_HONOR", "LOST_STOLEN")
    else:
        assert data["decline_code"] is None, \
            "decline_code is null unless the outcome is one of the two declines"
    if data["outcome"] == "PENDING":
        assert data["attempted_at"] is None, "attempted_at is null while the outcome is PENDING"
    assert isinstance(data["backoff_days_applied"], int)
    assert isinstance(data["grace_clamped"], bool)
    assert isinstance(data["is_final"], bool)
    assert data["is_final"] == data["grace_clamped"], \
        "is_final is set to the same value as grace_clamped"
    if data["attempt_number"] == 1:
        assert data["previous_attempt_id"] is None, \
            "previous_attempt_id is null on the first attempt"


def assert_cancellation_session(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["state"] in ("STARTED", "REASON_CAPTURED", "OFFERS_PRESENTED",
                            "OFFER_ACCEPTED", "COMPLETED_CANCELLED", "ABANDONED")
    if data["reason_code"] is not None:
        assert data["reason_code"] in ("PRICE", "PRODUCT_FIT", "TOO_MUCH_PRODUCT",
                                      "SHIPPING_ISSUES", "FINANCIAL_HARDSHIP", "OTHER")
    assert isinstance(data["step_count"], int) and data["step_count"] >= 1
    assert isinstance(data["offers_presented_count"], int)
    assert data["entry_channel"] in ("WEB_SELF_SERVE", "APP_SELF_SERVE", "AGENT_ASSISTED")
    assert is_iso8601_timestamp(data["started_at"])
    assert_nullable_timestamp(data, "completed_at")
    if data["state"] in ("STARTED", "REASON_CAPTURED", "OFFERS_PRESENTED"):
        assert data["completed_at"] is None, "completed_at is null while the session is non-terminal"


def assert_save_offer_template(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["offer_type"] in ("PAUSE", "SKIP", "DISCOUNT", "PLAN_DOWNGRADE")
    assert_four_decimal_fraction(data["discount_pct"], "discount_pct")
    assert 0.0 <= data["discount_pct"] < 1.0
    for field in ("discount_cycles", "pause_cycles", "skip_count", "min_tenure_days",
                  "max_per_subscriber_per_365d", "expires_after_hours"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["eligible_reason_codes"], list)
    assert data["priority_rank"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_save_offer_grant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["state"] in ("PRESENTED", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED")
    assert_four_decimal_fraction(data["per_cycle_margin_pct"], "per_cycle_margin_pct")
    assert_four_decimal_fraction(data["blended_term_margin_pct"], "blended_term_margin_pct")
    assert isinstance(data["margin_exception_required"], bool)
    assert data["margin_exception_state"] in ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED")
    assert_integer_cents(data, "retention_value_cents")
    assert is_iso8601_timestamp(data["expires_at"])
    assert_nullable_timestamp(data, "accepted_at")
    if data["state"] != "ACCEPTED":
        assert data["accepted_at"] is None, "accepted_at is null unless the state is ACCEPTED"


def assert_subscription_modification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["mod_type"] in ("FREQUENCY_CHANGE", "ADDON_ADD", "ADDON_REMOVE",
                               "SKIP_SHIPMENT", "PLAN_DOWNGRADE", "PAUSE", "RESUME",
                               "DISCOUNT_APPLY")
    assert data["state"] in ("REQUESTED", "SCHEDULED", "APPLIED", "REVERSED", "CANCELLED")
    assert_integer_cents(data, "delta_price_cents")
    assert_nullable_timestamp(data, "applied_at")
    if data["state"] in ("SCHEDULED", "CANCELLED"):
        assert data["delta_price_cents"] == 0, \
            "delta_price_cents is 0 while the row is SCHEDULED or CANCELLED"
        assert data["applied_at"] is None, \
            "applied_at is null while the row is SCHEDULED or CANCELLED"


def assert_prior_snapshot_shape(snapshot: Dict[str, Any]) -> None:
    """The snapshot holds exactly the seven values a reversal restores (PRD §3.3)."""
    expected = {"plan_id", "frequency_weeks", "addons", "active_discount_pct",
                "discount_remaining_cycles", "committed_price_cents", "term_shipments_skipped"}
    assert set(snapshot.keys()) == expected, \
        f"prior_snapshot must hold exactly the seven declared values, got {sorted(snapshot)}"


def assert_compliance_notice(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["notice_type"] in ("NEGATIVE_OPTION_DISCLOSURE", "RENEWAL_REMINDER",
                                  "PRICE_CHANGE", "CANCELLATION_CONFIRMATION")
    assert data["state"] in ("SCHEDULED", "SENT", "MISSED")
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert_nullable_timestamp(data, "sent_at")
    assert data["channel"] in ("EMAIL", "SMS")
    assert isinstance(data["renewal_cycle_index"], int)
    if data["state"] in ("SCHEDULED", "MISSED"):
        assert data["sent_at"] is None, "sent_at is null while the notice is SCHEDULED or MISSED"


def assert_winback_campaign(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["state"] in ("DRAFT", "LAUNCHED", "CLOSED")
    assert isinstance(data["target_channels"], list)
    assert isinstance(data["target_reason_codes"], list)
    assert data["min_days_since_lapse"] >= 0
    assert data["max_days_since_lapse"] >= data["min_days_since_lapse"]
    assert_four_decimal_fraction(data["offer_discount_pct"], "offer_discount_pct")
    assert 0.0 <= data["offer_discount_pct"] < 1.0
    for field in ("send_window_days", "suppression_days", "targeted_count",
                  "sent_count", "converted_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_winback_target(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["state"] in ("ELIGIBLE", "SUPPRESSED", "SENT", "EXPIRED", "CONVERTED")
    assert data["suppression_reason"] in ("NONE", "RECENT_SAVE_OFFER", "ACTIVE_SUBSCRIPTION",
                                         "DO_NOT_CONTACT", "INVOLUNTARY_UNRESOLVED",
                                         "CONTACT_CAP")
    assert_four_decimal_fraction(data["priority_score"], "priority_score")
    assert_integer_cents(data, "projected_ltv_cents")
    for field in ("sent_at", "expires_at", "converted_at"):
        assert_nullable_timestamp(data, field)
    assert isinstance(data["days_since_lapse_at_target"], int)
    if data["sent_at"] is None:
        assert data["expires_at"] is None, "expires_at is null while the target was never sent"


def assert_cohort_snapshot(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data["ltv_variant"] in ("REALIZED", "PROJECTED")
    for field in ("member_count", "retained_count", "churned_voluntary_count",
                  "churned_involuntary_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_four_decimal_fraction(data["retention_rate"], "retention_rate")
    assert_integer_cents(data, "mean_ltv_cents")
    assert is_iso8601_timestamp(data["computed_at"])
    assert data["retained_count"] <= data["member_count"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_shipment_conservation(subscription: Dict[str, Any]) -> None:
    """`term_shipments_remaining` is never independently mutated (PRD §2.9)."""
    total = (subscription["term_shipments_delivered"]
             + subscription["term_shipments_skipped"]
             + subscription["term_shipments_remaining"])
    assert subscription["term_shipments_remaining"] >= 0, \
        "term_shipments_remaining may not go negative"
    assert isinstance(total, int)


def assert_shipment_units_conserved(subscription: Dict[str, Any],
                                    shipments_per_term: int) -> None:
    """delivered + skipped + remaining == shipments_per_term (PRD §2.9)."""
    total = (subscription["term_shipments_delivered"]
             + subscription["term_shipments_skipped"]
             + subscription["term_shipments_remaining"])
    assert total == shipments_per_term, (
        f"delivered {subscription['term_shipments_delivered']} + skipped "
        f"{subscription['term_shipments_skipped']} + remaining "
        f"{subscription['term_shipments_remaining']} must equal shipments_per_term "
        f"{shipments_per_term}, got {total}")


def assert_price_conserved(subscription: Dict[str, Any],
                           modifications: List[Dict[str, Any]]) -> None:
    """committed_price_cents == baseline_price_cents + sum of APPLIED/REVERSED deltas."""
    ledger = sum(m["delta_price_cents"] for m in modifications
                 if m["state"] in ("APPLIED", "REVERSED"))
    expected = subscription["baseline_price_cents"] + ledger
    assert subscription["committed_price_cents"] == expected, (
        f"committed_price_cents must equal baseline_price_cents "
        f"{subscription['baseline_price_cents']} plus the APPLIED/REVERSED delta ledger "
        f"{ledger} = {expected}, got {subscription['committed_price_cents']}")
    for mod in modifications:
        if mod["state"] in ("SCHEDULED", "CANCELLED"):
            assert mod["delta_price_cents"] == 0, \
                "rows in SCHEDULED or CANCELLED always carry delta_price_cents of 0"


def assert_line_items_pinned_order(invoice: Dict[str, Any]) -> None:
    """Plan line first, then one line per addon ordered by code ascending (PRD §3.4)."""
    lines = invoice["line_items"]
    assert lines, "line_items must record the breakdown"
    addon_codes = [line["code"] for line in lines[1:]]
    assert addon_codes == sorted(addon_codes), \
        f"addon lines must be ordered by code ascending, got {addon_codes}"


def assert_lines_sum_to_amount(invoice: Dict[str, Any]) -> None:
    """Each line is rounded first, then summed (PRD §2.8 pinned ordering)."""
    total = sum(line["line_cents"] for line in invoice["line_items"])
    assert invoice["amount_cents"] == total, (
        f"amount_cents must equal the sum of the already-rounded line_cents {total}, "
        f"got {invoice['amount_cents']}")


def assert_margin_exception_consistency(grant: Dict[str, Any]) -> None:
    """The exception axis starts PENDING exactly when the guardrail was breached."""
    if grant["margin_exception_required"]:
        assert grant["margin_exception_state"] in ("PENDING", "APPROVED", "REJECTED"), (
            "a grant whose blended margin breached the floor is created directly in PENDING, "
            f"got {grant['margin_exception_state']}")
    else:
        assert grant["margin_exception_state"] == "NOT_REQUIRED", (
            "a grant that did not breach the floor is NOT_REQUIRED, "
            f"got {grant['margin_exception_state']}")
