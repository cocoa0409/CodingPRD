"""Percentage-rent charges: the two independent status axes, issuance of a
draft charge and the payment rules on the collection axis.
"""
from test_helpers import (
    AUDITOR, LEASE_ADMIN, TEST_DEFAULTS, ApiErrorId, assert_charge,
    charges_for_year, close_period, first_charge_of_type, ledger_entries,
    make_tenant_headers, read_charge, read_lease_year, reconcile,
    setup_year_with_accepted_reports, setup_year_with_periodic_charge,
    validate_error, validate_success,
)


def test_two_payments_settle_the_collection_axis_without_touching_billing(api):
    """PRD §3.8: "An accepted payment increases `paid_cents` by the amount
    paid, and the collection axis advances accordingly: a payment smaller than
    the whole outstanding balance moves `UNPAID → PARTIAL`, a payment exactly
    settling the remaining balance on a partly paid charge moves `PARTIAL →
    PAID`, and a payment exactly equal to the full `amount_cents` on an
    untouched charge moves `UNPAID → PAID` in one step. Throughout,
    `billing_status` is untouched — the two axes advance independently."

    Design: Difficulty/non_linear_state_machine/charge_billing_and_collection_axes_advance_independently
    """
    scene = setup_year_with_periodic_charge(suite_code="601")
    charge_id = scene["charge"]["id"]
    tenant_headers = make_tenant_headers(scene["tenant"]["id"])

    validate_success(
        api.pay_charge(charge_id, {"amount_cents": 500_000}, tenant_headers))
    final = validate_success(
        api.pay_charge(charge_id, {"amount_cents": 700_000}, tenant_headers))

    assert_charge(final)
    assert final["amount_cents"] == 1_200_000
    assert final["paid_cents"] == 1_200_000
    assert final["collection_status"] == "PAID"
    assert final["billing_status"] == "ISSUED", (
        "paying a charge never moves the billing axis")


def test_partial_payment_leaves_the_year_billed_total_unchanged(api):
    """PRD §3.8: "A percentage-rent charge tracks two things that have nothing
    to do with each other — whether the landlord has billed it, and whether the
    tenant has paid it — so it carries two status fields that advance
    independently. `billing_status` is the billing axis and takes `DRAFT`,
    `ISSUED` or the terminal `VOID`. `collection_status` is the collection axis
    and takes `UNPAID`, `PARTIAL`, and the terminal values `PAID` and
    `WRITTEN_OFF`."
    PRD §3.8: "Payments touch only the collection axis and may be applied by a
    `LeaseAdministrator` or by the lease's own `TenantUser`, supplying an
    `amount_cents`."

    Design: Difficulty/non_linear_state_machine/charge_billing_and_collection_axes_advance_independently
    """
    scene = setup_year_with_periodic_charge(suite_code="601")
    charge_id = scene["charge"]["id"]

    partly_paid = validate_success(
        api.pay_charge(charge_id, {"amount_cents": 500_000},
                       make_tenant_headers(scene["tenant"]["id"])))

    assert partly_paid["collection_status"] == "PARTIAL"
    assert partly_paid["paid_cents"] == 500_000
    assert partly_paid["billing_status"] == "ISSUED"

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_billed_cents"] == 1_200_000, (
        "collection movements never change what has been billed")


def test_payment_larger_than_the_outstanding_balance_is_refused(api):
    """PRD §3.8: "The payment must be strictly greater than zero and must not
    exceed the outstanding balance, which is the charge's `amount_cents` less
    its `paid_cents`; a payment that is zero, negative, or larger than the
    outstanding balance is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_above_outstanding_balance_returns_422
    """
    scene = setup_year_with_periodic_charge(suite_code="6501")
    charge_id = scene["charge"]["id"]

    validate_error(
        api.pay_charge(charge_id, {"amount_cents": 1_200_001}, LEASE_ADMIN),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)

    charge_now = read_charge(charge_id)
    assert charge_now["paid_cents"] == 0
    assert charge_now["collection_status"] == "UNPAID"
    assert charge_now["billing_status"] == "ISSUED"


def test_lease_administrator_may_pay_a_charge_in_full(api):
    """PRD §3.8: "Payments touch only the collection axis and may be applied by
    a `LeaseAdministrator` or by the lease's own `TenantUser`, supplying an
    `amount_cents`."
    PRD §3.8: "An accepted payment increases `paid_cents` by the amount paid,
    and the collection axis advances accordingly: a payment smaller than the
    whole outstanding balance moves `UNPAID → PARTIAL`, a payment exactly
    settling the remaining balance on a partly paid charge moves `PARTIAL →
    PAID`, and a payment exactly equal to the full `amount_cents` on an
    untouched charge moves `UNPAID → PAID` in one step."

    Design: Corner/rbac/lease_administrator_shares_the_payment_endpoint_with_tenant_user
    """
    scene = setup_year_with_periodic_charge(suite_code="8401")

    data = validate_success(
        api.pay_charge(scene["charge"]["id"], {"amount_cents": 1_200_000},
                       LEASE_ADMIN))

    assert data["paid_cents"] == 1_200_000
    assert data["collection_status"] == "PAID"
    assert data["billing_status"] == "ISSUED"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_billed_cents"] == 1_200_000


def test_issuing_a_draft_credit_charge_moves_the_billing_axis_and_the_ledger(api):
    """PRD §3.10: "When it is less than zero, it creates a charge with
    `charge_type` of `CREDIT`, `billing_status` of `DRAFT`,
    `collection_status` of `UNPAID`, `amount_cents` equal to the (negative)
    delta and `sales_report_id` null."
    PRD §3.8: "Issuing a draft charge is a `LeaseAdministrator` action moving
    the billing axis `DRAFT → ISSUED`. It requires the charge to be `DRAFT` and
    the owning reporting year to be anything other than `CLOSED`. It stamps
    `issued_at`, increases the year's `cumulative_billed_cents` by
    `amount_cents`, and appends a ledger entry carrying `amount_cents` as its
    `delta_billed_cents` — of type `TRUE_UP_ISSUED` when the amount is positive
    and `CREDIT_ISSUED` when it is negative. The collection axis is untouched
    by issuance: a draft charge already sits at `UNPAID`, and it stays there."

    Design: Corner/endpoints/issue_draft_credit_charge_moves_billing_axis_and_ledger
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="7101", billing_mode="PERIOD_STANDALONE",
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"])
    close_period(scene["lease_year"]["id"])
    reconciled = reconcile(scene["lease_year"]["id"])
    assert reconciled["true_up_delta_cents"] == -1_600_000, (
        "the annual recompute owes nothing while 1,600,000 was billed "
        "per-period")
    credit = first_charge_of_type(scene["lease_year"]["id"], "CREDIT")
    assert credit["billing_status"] == "DRAFT"
    assert credit["amount_cents"] == -1_600_000
    assert credit["sales_report_id"] is None

    issued = validate_success(api.issue_charge(credit["id"], LEASE_ADMIN))

    assert issued["billing_status"] == "ISSUED"
    assert issued["collection_status"] == "UNPAID"
    assert issued["charge_type"] == "CREDIT"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_billed_cents"] == 0

    entries = ledger_entries(scene["lease_year"]["id"], headers=AUDITOR)
    assert len(entries) == 3
    assert entries[-1]["entry_type"] == "CREDIT_ISSUED"
    assert entries[-1]["delta_billed_cents"] == -1_600_000
    assert charges_for_year(scene["lease_year"]["id"],
                           billing_status="ISSUED") != []
