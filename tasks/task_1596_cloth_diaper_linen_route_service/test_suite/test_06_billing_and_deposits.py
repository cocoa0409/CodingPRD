"""Weekly invoice composition, billing-cycle guards, delinquency timing, and
deposit-sufficiency on lost-item charges (PRD 3.8, 3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    create_case,
    generate_invoice,
    generate_invoice_payload,
    invoice_event,
    read_customer,
    setup_active_subscription,
    setup_completed_stop_with_intake,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import BILLING


class TestInvoiceGeneration:
    def test_invoice_generate_response_money_fields(self, api):
        """PRD 3.9: "`base_fee_cents` is the plan's `weekly_fee_cents` for the week."
        PRD 3.9: "`total_cents` is the base fee plus overage minus pause credit — a
        sum of already-rounded integer-cent lines, per §2.6 — floored at zero."

        Design: Corner/endpoints/invoice_generate_response_money_fields
        """
        ctx = setup_active_subscription()
        invoice = generate_invoice(ctx["subscription"]["id"])
        assert_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        assert invoice["base_fee_cents"] == 3900
        assert invoice["overage_cents"] == 0, "no qualifying intakes in a quiet week"
        assert invoice["pause_credit_cents"] == 0, "no pauses intersect the period"
        assert invoice["total_cents"] == 3900

    def test_invoice_period_overlap_returns_cycle_closed(self, api):
        """PRD 3.9: "the period must be exactly seven days and must not overlap the
        half-open period of any non-`VOID` invoice of the same subscription, else
        `ERR_BILLING_CYCLE_CLOSED`."

        Design: Corner/validations/invoice_period_overlap_returns_cycle_closed
        """
        ctx = setup_active_subscription()
        generate_invoice(ctx["subscription"]["id"], "2026-08-03", "2026-08-10")

        response = _client.generate_invoice(
            generate_invoice_payload(ctx["subscription"]["id"], "2026-08-05", "2026-08-12"),
            BILLING,
        )
        validate_error(response, ApiErrorId.ERR_BILLING_CYCLE_CLOSED.value)

    def test_mark_past_due_too_early_returns_not_past_due(self, api):
        """PRD 3.9: "marking past due requires the current logical time to be at
        least 14 days after `issued_at` (`ERR_INVOICE_NOT_PAST_DUE` before then),
        moves `ISSUED` → `PAST_DUE`, and cascades the subscription's `billing_status`
        from `CURRENT` to `PAST_DUE`."

        Design: Corner/validations/mark_past_due_too_early_returns_not_past_due
        """
        from test_helpers.fixtures import set_clock

        ctx = setup_active_subscription()
        invoice = generate_invoice(ctx["subscription"]["id"])
        invoice_event(invoice["id"], "ISSUE")  # issued_at = 2026-08-01T00:00:00Z
        set_clock("2026-08-10T00:00:00Z")  # only 9 days later

        response = _client.invoice_event(invoice["id"], {"event_type": "MARK_PAST_DUE"}, BILLING)
        validate_error(response, ApiErrorId.ERR_INVOICE_NOT_PAST_DUE.value)

        after = validate_success(_client.get_invoice(invoice["id"], BILLING))
        assert after["status"] == "ISSUED", "a rejected MARK_PAST_DUE leaves the invoice ISSUED"


class TestOverageCap:
    def test_overage_cap_clamps_billing(self, api):
        """PRD 3.9: "`overage_cents` draws on the subscription's intakes in
        `RECONCILED` or `RESOLVED` whose stop's route date falls inside the half-open
        period: each qualifying intake contributes its `verified_count` minus the
        `weekly_quota`, floored at zero and capped at `overage_cap_items`, and the
        summed items multiply by `overage_rate_cents`."

        Design: Corner/calculations/overage_cap_clamps_billing
        """
        # verified 150 (clean 150, scale 15000 -> variance 0, RECONCILED).
        ctx = setup_completed_stop_with_intake(clean_items=150, scale_weight_g=15000)
        intake = ctx["intake"]
        assert intake["status"] == "RECONCILED"
        assert intake["verified_count"] == 150

        invoice = generate_invoice(ctx["subscription"]["id"])
        assert invoice["overage_cents"] == 200, (
            f"min(150 - 80, 20) x 10 = 200, got {invoice['overage_cents']}"
        )
        assert invoice["total_cents"] == 4100, (
            f"3900 base + 200 overage = 4100, got {invoice['total_cents']}"
        )


class TestDepositSufficiency:
    def test_deposit_insufficient_on_oversized_charge(self, api):
        """PRD 3.8: "The charge then posts to the deposit ledger — provided
        `deposit_held_cents` covers it, else `ERR_DEPOSIT_INSUFFICIENT`:
        `charge_cents` is recorded on the case, the held balance drops by the charge,
        and `deposit_applied_cents` rises by the charge, moving the case `OPEN` →
        `CHARGED`."

        Design: Corner/validations/deposit_insufficient_on_oversized_charge
        """
        ctx = setup_active_subscription()
        case = create_case(
            ctx["subscription"]["id"], ctx["pool"]["id"],
            case_type="LOST", item_count=100, first_issued_date="2026-06-01",
        )

        response = _client.case_event(case["id"], {"event_type": "CHARGE"}, BILLING)
        validate_error(response, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)

        after = validate_success(_client.get_case(case["id"], BILLING))
        assert after["status"] == "OPEN", "a failed charge leaves the case OPEN"
        customer = read_customer(ctx["customer"]["id"])
        assert customer["deposit_held_cents"] == 18000, (
            "the ledger is untouched when the deposit cannot cover the charge"
        )
