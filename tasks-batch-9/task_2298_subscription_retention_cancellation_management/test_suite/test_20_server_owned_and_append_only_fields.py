"""Fields the server owns: computed prices, minted invoices and append-only records.

A client-supplied committed price is ignored, the signup invoice exists only as a side
effect with every field minted server-side, and the two append-only resources carry
neither `version` nor `updated_at`.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_append_only_fields,
    assert_cohort_snapshot,
    assert_dunning_attempt,
    assert_instant,
    assert_invoice,
    create_attempt,
    create_cohort_snapshot_payload,
    create_subscription_payload,
    new_core_plan,
    new_payment_method,
    new_subscriber,
    set_clock,
    setup_active_subscription,
    signup_invoice,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


class TestComputedFields:

    def test_a_client_supplied_committed_price_is_ignored_and_recomputed(self):
        """The server prices 4999 plus two MUGs at 7597 whatever the body claims.

        PRD §3.3: "It is the plan component plus the addon components, each rounded
        separately: the plan component is `monthly_price_cents` multiplied by
        `shipments_per_cycle` multiplied by one minus `active_discount_pct`, rounded half
        up to whole cents; each addon component is that addon's `unit_price_cents`
        multiplied by its `qty` multiplied by one minus `active_discount_pct`, rounded
        half up to whole cents; the results are then added."

        Design: Corner/entities/committed_price_is_computed_from_plan_and_addons_client_value_input_ignored
        """
        set_clock("2026-01-10")
        plan = new_core_plan()
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        card = new_payment_method(subscriber["id"])

        payload = create_subscription_payload(
            subscriber["id"], plan["id"], card["id"],
            addons=[{"code": "MUG", "qty": 2}], committed_price_cents=99)
        subscription = validate_success(api_client.create_subscription(payload, ADMIN), 201)

        assert subscription["committed_price_cents"] == 7597
        assert subscription["baseline_price_cents"] == 7597
        assert len(subscription["addons"]) == 1
        assert subscription["addons"][0]["code"] == "MUG"
        assert subscription["addons"][0]["qty"] == 2
        assert subscription["addons"][0]["unit_price_cents"] == 1299
        assert subscription["addons"][0]["unit_cogs_cents"] == 520


class TestSystemMintedInvoice:

    def test_the_signup_invoice_has_no_create_endpoint_and_every_field_minted(self):
        """Cycle zero, not a renewal, open, due at the signup instant, never attempted.

        PRD §3.4: "`due_at` is the clock instant of invoice creation; `paid_at` is the
        `attempted_at` of the successful charge attempt and is null while the invoice is
        unpaid; `attempt_count` counts the charge attempts recorded against this invoice
        and starts at 0."

        Design: Corner/entities/signup_invoice_system_fields_are_server_minted
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "SEARCH"},
            addons=[{"code": "MUG", "qty": 1}])

        invoice = signup_invoice(world["subscription"]["id"])
        assert_invoice(invoice)
        assert invoice["cycle_index"] == 0
        assert invoice["is_renewal"] is False
        assert invoice["status"] == "OPEN"
        assert_instant(invoice["due_at"], "2026-01-10T00:00:00Z", "due_at")
        assert invoice["paid_at"] is None
        assert invoice["attempt_count"] == 0
        assert invoice["proration_factor"] == pytest.approx(1.0000, abs=5e-5)
        assert invoice["payment_method_id"] == world["payment_method"]["id"]


class TestAppendOnlyRecords:

    def test_a_dunning_attempt_carries_no_version_and_no_updated_at(self):
        """The first attempt is a record of an event: id and created_at only.

        PRD §2.2: "Two resources are append-only records of something that already
        happened and therefore carry **only** `id` and `created_at` — both `updated_at`
        and `version` are absent from them entirely: `DunningAttempt`, which records one
        charge attempt against one invoice, and `RetentionCohortSnapshot`, which is an
        immutable analytical artifact with no update or delete operation of any kind."

        Design: Corner/entities/dunning_attempt_is_immutable_with_no_version_and_no_write_endpoint
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        attempt = create_attempt(world["invoice"]["id"])

        stored = validate_success(api_client.get_dunning_attempt(attempt["id"], BILLING), 200)
        assert_append_only_fields(stored)
        assert_dunning_attempt(stored)
        assert stored["attempt_number"] == 1
        assert stored["previous_attempt_id"] is None
        assert stored["outcome"] == "PENDING"
        assert stored["attempted_at"] is None
        assert stored["backoff_days_applied"] == 0
        assert stored["grace_clamped"] is False
        assert stored["is_final"] is False

    def test_a_snapshot_of_an_empty_cohort_is_a_persisted_zero_artifact(self):
        """No members means retention_rate 0.0000 and mean_ltv_cents 0, not a division error.

        PRD §3.9: "`retention_rate` is `retained_count` divided by `member_count`, rounded
        half up to four decimal places, and exactly `0.0000` when `member_count` is 0.
        `mean_ltv_cents` is the sum across members of the selected variant — each member's
        `realized_ltv_cents` when `ltv_variant` is `REALIZED`, otherwise their
        `projected_ltv_cents` — divided by `member_count` and rounded half up to whole
        cents, and exactly 0 when `member_count` is 0."

        Design: Corner/entities/cohort_snapshot_of_empty_cohort_is_an_immutable_zero_artifact
        """
        set_clock("2026-02-01")
        snapshot = validate_success(api_client.create_cohort_snapshot(
            create_cohort_snapshot_payload("2026-01", ltv_variant="REALIZED"), RETENTION), 201)

        assert_cohort_snapshot(snapshot)
        assert snapshot["member_count"] == 0
        assert snapshot["retained_count"] == 0
        assert snapshot["churned_voluntary_count"] == 0
        assert snapshot["churned_involuntary_count"] == 0
        assert snapshot["retention_rate"] == pytest.approx(0.0000, abs=5e-5)
        assert snapshot["mean_ltv_cents"] == 0
        assert_instant(snapshot["computed_at"], "2026-02-01T00:00:00Z", "computed_at")
