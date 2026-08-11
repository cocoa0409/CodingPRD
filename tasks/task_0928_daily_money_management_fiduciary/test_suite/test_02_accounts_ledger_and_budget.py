"""Accounts under management, the immutable ledger, and the monthly budget."""

from test_helpers import (
    ApiErrorId,
    account_adjustment_payload,
    api_client,
    assert_budget_category,
    assert_budget_invariants,
    assert_client_account,
    assert_ledger_entry,
    budget_override_payload,
    create_account,
    create_active_client,
    list_ledger_entries,
    payment_request,
    post_adjustment,
    read_account,
    read_bond,
    read_budget_category,
    read_payment,
    register_bond,
    release_payment,
    schedule_payment,
    set_clock,
    settle_payment,
    setup_billpay_world,
    TEST_USERS,
    create_budget_category,
    grant_override,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]
SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]


def test_a_deposit_writes_an_immutable_ledger_entry_with_no_version_field():
    """PRD §2.5: "Three entities are deliberately excluded: a `LedgerEntry`, a
    `FamilyReport` and an `AuditEntry` are immutable once written and therefore
    carry only `id` and `created_at` — they have no `updated_at` field and no
    `version` field at all, and no endpoint updates or deletes them."
    PRD §3.2: "A `DEPOSIT` appends a `DEPOSIT` ledger entry of positive
    `amount_cents` dated the supplied `value_date`, which raises
    `cleared_balance_cents`"

    Design: Corner/entities/corner_ledger_entry_is_immutable_with_no_version_field
    """
    set_clock("2026-06-01T09:00:00Z")
    register_bond()
    client = create_active_client(intake_reference="INT-C006")
    account = create_account(client["id"], opening_balance_cents=5000000)

    post_adjustment(
        account["id"],
        "DEPOSIT",
        250000,
        "2026-06-01",
        memo="Social Security direct deposit.",
    )

    entries = list_ledger_entries(account["id"])
    assert len(entries) == 1, f"Expected exactly one ledger entry, got {entries}"
    entry = entries[0]
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "DEPOSIT"
    assert entry["amount_cents"] == 250000
    assert entry["frozen"] is False
    assert "version" not in entry
    assert "updated_at" not in entry

    after = read_account(account["id"])
    assert after["cleared_balance_cents"] == 5250000
    assert after["available_balance_cents"] == 5250000


def test_releasing_more_hold_than_is_outstanding_is_refused():
    """PRD §3.2: "`pending_holds_cents` is the running total of withdrawal
    holds placed minus holds released, and it is floored at zero: a release
    that would drive it negative is refused with `ERR_VALIDATION` rather than
    clamped."

    Design: Corner/calculations/corner_hold_release_below_zero_is_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    register_bond()
    client = create_active_client(intake_reference="INT-C020")
    account = create_account(client["id"], opening_balance_cents=5000000)
    post_adjustment(account["id"], "WITHDRAWAL_HOLD", 120000, "2026-06-01")

    response = api_client.post_account_adjustment(
        account["id"],
        account_adjustment_payload("HOLD_RELEASE", 150000, "2026-06-01"),
        SPECIALIST,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    after = read_account(account["id"])
    assert_client_account(after)
    assert after["pending_holds_cents"] == 120000
    assert after["available_balance_cents"] == 4880000


def test_an_override_reason_shorter_than_twenty_characters_is_refused():
    """PRD §3.2: "The reason must be at least 20 characters long — a bare "over
    budget" is refused with `ERR_VALIDATION` — and `added_cents` must be
    greater than zero."

    Design: Corner/validations/corner_override_reason_shorter_than_minimum_is_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-C035")
    line = create_budget_category(
        client["id"], category_name="UTILITIES", budget_month="2026-06", allocation_cents=100000
    )

    response = api_client.grant_budget_override(
        line["id"], budget_override_payload(50000, "Too short"), MANAGER
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    after = read_budget_category(line["id"])
    assert after["override_granted_cents"] == 0
    assert after["override_count"] == 0


def test_a_budget_override_lifts_the_ceiling_that_had_refused_the_payment():
    """PRD §2.9 rung 36: "**Budget line capacity.** The line's
    `committed_cents` plus this payment's `amount_cents` is at or below
    `allocation_cents` plus `override_granted_cents`; landing exactly on the
    allocation is permitted. Otherwise `ERR_BUDGET_EXCEEDED` (409)."
    PRD §3.2: "The grant raises `override_granted_cents` by `added_cents`,
    increments `override_count` by one, records the text in
    `last_override_reason`, and recomputes the line's derived figures."

    Design: Corner/validations/corner_budget_exceeded_then_permitted_once_an_override_is_granted
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=100000)

    refused = payment_request(world, amount_cents=120000, channel="ACH")
    validate_error(refused, ApiErrorId.ERR_BUDGET_EXCEEDED.value, 409)

    granted = grant_override(
        world["budget_category"]["id"],
        50000,
        "Winter heating surcharge approved by the family conference.",
    )
    assert granted["override_granted_cents"] == 50000
    assert granted["override_count"] == 1

    accepted = payment_request(world, amount_cents=120000, channel="ACH")
    validate_success(accepted, 201)

    line = read_budget_category(world["budget_category"]["id"])
    assert_budget_category(line)
    assert line["committed_cents"] == 120000
    assert line["remaining_cents"] == 30000
    assert line["variance_full_cents"] == 30000
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 120500


def test_variance_direction_reads_over_from_the_period_to_date_figure():
    """PRD §3.2: "`variance_direction` is keyed to the **period-to-date**
    figure, never to the full-period one: it reads `UNDER` when
    `variance_ptd_cents` is greater than zero, `EXACT` when it is exactly zero,
    and `OVER` when it is negative."
    PRD §3.2: "The prorated allocation is `allocation_cents` plus
    `override_granted_cents`, multiplied by the elapsed-day count, divided by
    the month's day count, and rounded half up to a whole number of cents.
    `variance_ptd_cents` is then that prorated allocation minus
    `settled_cents`."

    Design: Corner/calculations/corner_variance_direction_reads_over_when_settled_spend_beats_prorated_allocation
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=300000)
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])

    set_clock("2026-06-02T09:00:00Z")
    settle_payment(payment["id"])

    line = read_budget_category(world["budget_category"]["id"])
    assert_budget_invariants(line)
    assert line["settled_cents"] == 80000
    assert line["committed_cents"] == 80000
    assert line["variance_full_cents"] == 220000
    assert line["variance_ptd_cents"] == -60000
    assert line["variance_direction"] == "OVER"

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 0
    assert bond["exposure_settled_inclusive_cents"] == 80000
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 4919500


def test_committed_money_drives_the_full_period_variance():
    """PRD §3.2: "**The full-period variance**, `variance_full_cents`, is
    `allocation_cents` plus `override_granted_cents` minus `committed_cents` —
    the whole month's allocation measured against money that has merely been
    committed."
    PRD §3.2: "`committed_cents` is the sum of `amount_cents` — principal only,
    service fee excluded — over the line's payments whose `settlement_status`
    is `SCHEDULED`, `IN_FLIGHT` or `SETTLED`; cancelled, stopped and returned
    payments are excluded from it entirely."

    Design: Difficulty/dual_variant_calc/budget_variance_full_vs_period_to_date_diverge
    """
    world = setup_billpay_world(clock_iso="2026-06-10T09:00:00Z", allocation_cents=300000)

    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    assert payment["projected_settlement_date"] == "2026-06-12"
    line = read_budget_category(world["budget_category"]["id"])
    assert line["committed_cents"] == 80000
    assert line["settled_cents"] == 0
    assert line["remaining_cents"] == 220000
    assert line["variance_full_cents"] == 220000


def test_settled_money_against_a_prorated_allocation_drives_the_period_to_date_variance():
    """PRD §3.2: "**The period-to-date variance**, `variance_ptd_cents`,
    prorates instead."
    PRD §3.2: "The prorated allocation is `allocation_cents` plus
    `override_granted_cents`, multiplied by the elapsed-day count, divided by
    the month's day count, and rounded half up to a whole number of cents.
    `variance_ptd_cents` is then that prorated allocation minus
    `settled_cents`."

    Design: Difficulty/dual_variant_calc/budget_variance_full_vs_period_to_date_diverge
    """
    world = setup_billpay_world(clock_iso="2026-06-10T09:00:00Z", allocation_cents=300000)

    schedule_payment(world, amount_cents=80000, channel="ACH")

    line = read_budget_category(world["budget_category"]["id"])
    assert_budget_category(line)
    # 300000 * 10 elapsed days / 30 days in June = 100000, less 0 settled cents.
    assert line["variance_ptd_cents"] == 100000
    assert line["variance_direction"] == "UNDER"
    assert line["variance_full_cents"] != line["variance_ptd_cents"], (
        "the two variance variants must disagree while money is committed but unsettled"
    )


def test_account_version_advances_on_creation_deposit_and_payment_schedule():
    """PRD §2.5: "| Place an account under management | The new
    `ClientAccount` is created at `version` 1. |"
    PRD §2.5: "| Post a deposit, place a hold, release a hold | `ClientAccount`
    +1."
    PRD §2.5: "| Schedule a payment | The new `Payment` is created at `version`
    1; `ClientAccount` +1."

    Design: Corner/cross_cutting_complexity_layers/corner_account_version_increments_on_every_mutation
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    assert world["account"]["version"] == 1

    deposited = post_adjustment(
        world["account"]["id"], "DEPOSIT", 250000, "2026-06-01", memo="Pension deposit."
    )
    assert deposited["version"] == 2

    schedule_payment(world, amount_cents=80000, channel="ACH")

    final = read_account(world["account"]["id"])
    assert final["version"] == 3
    assert final["cleared_balance_cents"] == 5250000
    assert final["available_balance_cents"] == 5169500
