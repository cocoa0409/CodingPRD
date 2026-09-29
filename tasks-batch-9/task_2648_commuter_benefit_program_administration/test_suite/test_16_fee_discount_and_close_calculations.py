"""Administration-fee flooring, bulk invoice discounting, month-close rollover and
the fulfillment rollup of a late loss report.

The four concerns in this module all turn on a pinned constant or a pinned
rounding point:

* the payroll administration fee, which is floored at a declared monthly minimum
  rather than taken from the per-participant rate alone;
* the bulk discount tier boundary of a procurement invoice, exercised both below
  the boundary and across it, with the single rounding of the discount;
* the full-rollover branch of the month close, where both destination buckets are
  zero and therefore no ledger row may be appended;
* the fulfillment rollup after a line is reported lost once its batch has already
  reconciled.

Every expected figure below is computed by hand from the documented formula and
asserted as a literal integer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    PROGRAM_ADMIN,
    assert_account_conservation,
    assert_entry_types,
    assert_invoice_totals,
    assert_ledger_matches_account,
    assert_media_line,
    make_order_desk_headers,
    make_payroll_processor_headers,
)
from test_helpers import constants as C
from test_helpers import fixtures as fx


def test_01_admin_fee_floors_at_the_monthly_minimum_for_a_single_participant(api):
    """PRD 3.9: "`admin_fee_cents` is the larger of a 5000-cent monthly minimum —
    fifty dollars — and the participant count multiplied by 425 cents per
    participant."
    PRD 3.9: "computes `pre_waiver_charge_cents` as `total_pretax_cents` plus
    `total_posttax_cents` plus `admin_fee_cents`"
    PRD 3.9: "a pre-waiver charge below 50000 cents earns no waiver"
    PRD 3.9: "sets `employer_charge_cents` to `pre_waiver_charge_cents` minus
    `fee_waiver_cents`, and the tier is **never** re-derived from that final figure"
    PRD 3.9: "`total_pretax_cents` is the sum of `excluded_amount_cents` across the
    scope, and `total_posttax_cents` the sum of `posttax_effective_cents`"

    Design: Corner/calculations/payroll_admin_fee_floors_at_the_declared_minimum_constant
    """
    base = fx.make_funded_election(
        api,
        region_code=C.REGION_AUS,
        pretax_amount_cents=5000,
        employer_overrides={
            "legal_name": "Fee Floor Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        election_overrides={"posttax_amount_cents": 0},
    )
    assert base["window"]["status"] == "LOCKED", base["window"]["status"]
    assert base["election"]["funding_status"] == "FUNDED", (
        base["election"]["funding_status"]
    )

    payroll_headers = make_payroll_processor_headers("pay-1")
    payroll_file = fx.make_draft_payroll_file(
        api, base["employer"]["id"], period_month="2026-08", payroll_user_id="pay-1"
    )
    assert payroll_file["status"] == "DRAFT", payroll_file["status"]

    generated = validate_success(
        api.generate_payroll_file(payroll_file["id"], payroll_headers), 200
    )

    # Scope: the one FUNDED election of the 2026-08 window.
    # participant_count      = 1 distinct employee_id
    # total_pretax_cents     = excluded_amount_cents 5000
    # total_posttax_cents    = posttax_effective_cents 0
    # admin_fee_cents        = max(5000 minimum, 1 * 425) = 5000  (NOT 425)
    # pre_waiver_charge      = 5000 + 0 + 5000 = 10000
    # 10000 < 50000, so the waiver tier is 0 percent -> fee_waiver_cents = 0
    # employer_charge_cents  = 10000 - 0 = 10000
    assert generated["participant_count"] == 1, generated["participant_count"]
    assert generated["total_pretax_cents"] == 5000, generated["total_pretax_cents"]
    assert generated["total_posttax_cents"] == 0, generated["total_posttax_cents"]
    assert generated["admin_fee_cents"] == 5000, (
        "admin_fee_cents must be lifted to the 5000-cent minimum, not the 425-cent "
        f"per-participant figure, got {generated['admin_fee_cents']}"
    )
    assert generated["admin_fee_cents"] != C.ADMIN_FEE_PER_PARTICIPANT_CENTS, (
        "425 is what applying the per-participant rate without the minimum gives"
    )
    assert generated["pre_waiver_charge_cents"] == 10000, (
        generated["pre_waiver_charge_cents"]
    )
    assert generated["fee_waiver_cents"] == 0, generated["fee_waiver_cents"]
    assert generated["employer_charge_cents"] == 10000, (
        generated["employer_charge_cents"]
    )
    assert generated["status"] == "GENERATED", generated["status"]


def test_02_four_line_batch_stays_in_the_no_discount_tier(api):
    """PRD 3.5: "batches of 4 lines or fewer earn no discount at all, batches of 5
    through 9 lines earn 1.5 percent, and batches of 10 or more lines earn 3.0
    percent"
    PRD 3.5: "`discount_cents` is `subtotal_cents` multiplied by that percentage and
    divided by one hundred, rounded half up exactly once against the already-summed
    subtotal, and `total_cents` is `subtotal_cents` minus `discount_cents`."
    PRD 3.5: "`subtotal_cents` is the plain integer sum of their `line_total_cents`
    values"
    PRD 3.5: "The regional surcharge percentages are 7.5 percent for `US-CA-SFO`,
    6.25 percent for `US-NY-NYC`, 5.0 percent for `US-IL-CHI`, 4.0 percent for
    `US-WA-SEA` and 2.5 percent for `US-TX-AUS`."

    Design: Corner/calculations/five_line_batch_crosses_into_the_second_bulk_discount_tier
    """
    built = fx.make_batch_with_n_lines(
        api,
        line_count=4,
        region_code=C.REGION_AUS,
        unit_price_cents=1000,
        seal_user_id="desk-build",
        employer_overrides={"legal_name": "Bulk Tier Boundary Co"},
    )

    sealed = validate_success(
        api.seal_order_batch(
            built["batch"]["id"], make_order_desk_headers("desk-sealer")
        ),
        200,
    )

    # Each of the 4 lines: gross = 1000 * 1 = 1000; US-TX-AUS surcharge 2.5% of
    # 1000 = 25 exactly; line_total = 1000 + 25 = 1025.
    # subtotal_cents = 4 * 1025 = 4100
    # 4 lines is inside the "4 lines or fewer" tier, so discount_cents = 0
    # total_cents = 4100 - 0 = 4100
    assert_invoice_totals(
        sealed, line_count=4, subtotal_cents=4100, discount_cents=0, total_cents=4100
    )
    assert sealed["status"] == "SEALED", sealed["status"]
    for order in built["orders"]:
        priced = fx.read_media_order(api, order["id"])
        assert_media_line(
            priced,
            line_gross_cents=1000,
            line_surcharge_cents=25,
            line_total_cents=1025,
        )


def test_03_five_line_batch_crosses_into_the_one_and_a_half_percent_tier(api):
    """PRD 3.5: "batches of 4 lines or fewer earn no discount at all, batches of 5
    through 9 lines earn 1.5 percent, and batches of 10 or more lines earn 3.0
    percent"
    PRD 3.5: "`discount_cents` is `subtotal_cents` multiplied by that percentage and
    divided by one hundred, rounded half up exactly once against the already-summed
    subtotal, and `total_cents` is `subtotal_cents` minus `discount_cents`."
    PRD 3.5: "For each priced line, `line_gross_cents` is
    `unit_price_cents_snapshot` multiplied by `quantity`"
    PRD 3.5: "`line_surcharge_cents` is that gross amount multiplied by the batch
    region's handling surcharge percentage and divided by one hundred, **rounded
    half up to whole cents for that line alone**"
    PRD 3.5: "with `unit_price_cents_snapshot` copied from the catalogue product's
    current `unit_price_cents`"

    Design: Corner/calculations/five_line_batch_crosses_into_the_second_bulk_discount_tier
    """
    built = fx.make_batch_with_n_lines(
        api,
        line_count=5,
        region_code=C.REGION_AUS,
        unit_price_cents=1000,
        seal_user_id="desk-build",
        employer_overrides={"legal_name": "Bulk Tier Co"},
    )
    assert built["orders"][0]["unit_price_cents_snapshot"] == 1000, (
        built["orders"][0]["unit_price_cents_snapshot"]
    )

    sealed = validate_success(
        api.seal_order_batch(
            built["batch"]["id"], make_order_desk_headers("desk-sealer")
        ),
        200,
    )

    # Per line: gross = 1000 * 1 = 1000; US-TX-AUS surcharge 2.5% of 1000 = 25
    # exactly; line_total = 1025.  Rounding happens per line, then the totals sum.
    # subtotal_cents  = 5 * 1025 = 5125
    # 5 lines leaves the no-discount tier and takes 1.5%:
    # 5125 * 1.5 / 100 = 76.875 -> rounded half up exactly once = 77
    # total_cents     = 5125 - 77 = 5048
    assert_invoice_totals(
        sealed, line_count=5, subtotal_cents=5125, discount_cents=77, total_cents=5048
    )
    assert sealed["discount_cents"] != 0, (
        "five lines is past the four-line no-discount tier, so a zero discount is wrong"
    )
    assert sealed["discount_cents"] != 76, (
        "76.875 rounds half up to 77, never down to 76"
    )
    assert sealed["status"] == "SEALED", sealed["status"]
    for order in built["orders"]:
        priced = fx.read_media_order(api, order["id"])
        assert_media_line(
            priced,
            line_gross_cents=1000,
            line_surcharge_cents=25,
            line_total_cents=1025,
        )


def test_04_full_rollover_close_carries_the_whole_balance_and_writes_no_ledger_row(api):
    """PRD 3.8: "under `FULL_ROLLOVER` the entire unused balance carries forward"
    PRD 3.8: "the forfeiture amount is the unused balance minus the carried-forward
    amount"
    PRD 3.8: "nothing at all is refunded to the employer"
    PRD 3.8: "The two resulting deltas are then applied in a fixed order, with one
    ledger entry appended per non-zero delta."
    PRD 3.8: "after a standard close the account's `available_balance_cents` equals
    exactly the carried-forward amount"
    PRD 3.8: "Every election window of that employer whose `status` is `LOCKED` and
    whose `benefit_month` equals the supplied month moves `LOCKED → CLOSED`."
    PRD 3.8: "Nothing else is reset: `rollover_in_cents`, `contributed_cents`,
    `spent_cents` and `fee_charged_cents` are lifetime-cumulative buckets and a
    close never zeroes them."

    Design: Corner/calculations/full_rollover_close_carries_everything_and_appends_no_ledger_row
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        region_code=C.REGION_SEA,
        legal_name="Full Rollover Co",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
        rollover_policy="FULL_ROLLOVER",
        rollover_cap_cents=0,
    )
    employer = built["employer"]
    category = built["categories"][0]

    employee = fx.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="SEA-FR-1",
        work_region_code=C.REGION_SEA,
        hire_date="2026-02-01T00:00:00Z",
    )
    account = fx.make_benefit_account(
        api,
        employee["id"],
        category["id"],
        PROGRAM_ADMIN,
        opening_rollover_cents=12000,
    )
    # The opening balance is the account's single ledger row (ROLLOVER_IN 12000).
    assert account["available_balance_cents"] == 12000, (
        account["available_balance_cents"]
    )
    assert account["ledger_entry_count"] == 1, account["ledger_entry_count"]

    window = fx.make_open_window(api, employer["id"], PROGRAM_ADMIN)
    locked = validate_success(api.lock_election_window(window["id"], PROGRAM_ADMIN), 200)
    assert locked["status"] == "LOCKED", locked["status"]

    validate_success(
        api.month_close_employer(
            employer["id"], {"benefit_month": "2026-08"}, PROGRAM_ADMIN
        ),
        200,
    )

    # The employee is ACTIVE, so the standard close runs.  Unused amount is the
    # account's available_balance_cents of 12000; under FULL_ROLLOVER the whole
    # 12000 carries forward, so:
    #   forfeiture = 12000 - 12000 = 0   and   refund = 0
    # Both deltas are zero, so no ledger entry is appended at all and
    # ledger_entry_count stays at the single ROLLOVER_IN row.
    account_after = fx.read_account(api, account["id"])
    assert account_after["available_balance_cents"] == 12000, (
        "available_balance_cents must equal the carried-forward 12000, got "
        f"{account_after['available_balance_cents']}"
    )
    assert account_after["forfeited_cents"] == 0, account_after["forfeited_cents"]
    assert account_after["refunded_cents"] == 0, account_after["refunded_cents"]
    assert account_after["rollover_in_cents"] == 12000, (
        account_after["rollover_in_cents"]
    )
    assert account_after["ledger_entry_count"] == 1, (
        "no FORFEITURE and no REFUND row may be appended when both deltas are zero, "
        f"got ledger_entry_count {account_after['ledger_entry_count']}"
    )
    assert_account_conservation(account_after)

    entries = fx.read_ledger(api, account["id"])
    assert_entry_types(entries, ["ROLLOVER_IN"])
    assert_ledger_matches_account(account_after, entries)

    window_after = fx.read_window(api, window["id"])
    assert window_after["status"] == "CLOSED", window_after["status"]


def test_05_late_loss_report_lifts_the_election_but_leaves_the_reconciled_batch_alone(api):
    """PRD 3.6: "a line whose `status` is `DELIVERED` moves `DELIVERED →
    UNDELIVERED`; both paths carry the identical payload and produce the identical
    effects"
    PRD 3.6: "The payload supplies `reason`, one of `NEVER_ARRIVED`, `LOST`,
    `STOLEN` or `DAMAGED`, which is stored on the row as `undelivered_reason`."
    PRD 3.6: "if any candidate order has `status` `UNDELIVERED`, the result is
    `REPLACEMENT_PENDING`"
    PRD 3.6: "In both cases the parent election's `fulfillment_status` is re-derived
    to `REPLACEMENT_PENDING`"
    PRD 3.5: "the batch moves `RELEASED → RECONCILED` and its `version` advances by
    1. `RECONCILED` is terminal."
    PRD 3.6: "the reissue increments the line's `replacement_count` by 1"

    Design: Corner/calculations/undelivered_after_reconciled_batch_propagates_to_election_but_stops_at_terminal_batch
    """
    chain = fx.make_procurement_chain(
        api,
        region_code=C.REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=6000,
        unit_price_cents=6000,
        seal_user_id="desk-a",
        release_user_id="desk-b",
        stop_after="delivered",
        employer_overrides={
            "legal_name": "Late Loss Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        account_overrides={"opening_rollover_cents": 2000},
        media_overrides={"sku": "AUS-LL"},
    )
    # The single line was delivered, so the whole chain has already settled: the
    # order is DELIVERED, the election reads DELIVERED and the batch reconciled.
    assert chain["order"]["status"] == "DELIVERED", chain["order"]["status"]
    assert chain["batch"]["status"] == "RECONCILED", chain["batch"]["status"]
    election_before = fx.read_election(api, chain["election"]["id"])
    assert election_before["fulfillment_status"] == "DELIVERED", (
        election_before["fulfillment_status"]
    )

    reported = validate_success(
        api.report_media_order_undelivered(
            chain["order"]["id"], {"reason": "LOST"}, make_order_desk_headers("desk-a")
        ),
        200,
    )

    assert reported["status"] == "UNDELIVERED", reported["status"]
    assert reported["undelivered_reason"] == "LOST", reported["undelivered_reason"]
    # No reissue has happened, so the replacement counter and the fee are untouched.
    assert reported["replacement_count"] == 0, reported["replacement_count"]

    # The rollup propagates up exactly one level: the only candidate order is
    # UNDELIVERED, so the election lands in REPLACEMENT_PENDING.  Its money axis is
    # independent and stays PENDING.
    election_after = fx.read_election(api, chain["election"]["id"])
    assert election_after["fulfillment_status"] == "REPLACEMENT_PENDING", (
        election_after["fulfillment_status"]
    )
    assert election_after["funding_status"] == "PENDING", (
        election_after["funding_status"]
    )

    # Propagation then stops: RECONCILED is terminal, so the batch is not dragged
    # back to RELEASED.
    batch_after = fx.read_batch(api, chain["batch"]["id"])
    assert batch_after["status"] == "RECONCILED", (
        "a terminal RECONCILED batch must not move when a delivered line is later "
        f"reported lost, got {batch_after['status']}"
    )

    account_after = fx.read_account(api, chain["account"]["id"])
    assert account_after["fee_charged_cents"] == 0, (
        "reporting media undelivered charges no replacement fee, got "
        f"{account_after['fee_charged_cents']}"
    )
    assert_account_conservation(account_after)
