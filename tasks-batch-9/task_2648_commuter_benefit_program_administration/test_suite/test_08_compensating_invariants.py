"""Forward-plus-compensating cycles and the two quantities they must conserve.

Two different quantities in the commuter benefit program are conserved across a
forward action and its exact compensation, and both are asserted here in the
same shape: measure the invariant BEFORE the forward action, prove the forward
action moved it, then prove the compensating action put it back exactly.

* **Benefit dollars.** Funding an election credits its benefit account; the
  compensating funding reversal appends a third append-only ledger row and
  returns ``available_balance_cents`` to precisely its pre-funding value, while
  leaving ``contributed_cents`` intact and raising ``reversed_cents`` instead.
  The whole ledger row sequence — entry type, signed amount and running
  ``balance_after_cents`` — is asserted, not just the closing total.
* **Physical media units.** Superseding a pending media line and reissuing an
  undelivered one are two independent compensating cycles against the same
  election; after both, the net non-``CANCELLED`` unit count must still equal
  ``entitled_media_units`` exactly, and the sealed invoice must bill only the
  surviving line.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PROGRAM_ADMIN,
    assert_account_conservation,
    assert_invoice_totals,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    assert_media_line,
    factories as f,
    fixtures as fx,
    make_order_desk_headers,
)
from test_helpers import api_errors as _api_errors  # installs the status map
from test_helpers.constants import REGION_CHI, REGION_SEA

TRANSIT_CATEGORY = {
    "category_type": "TRANSIT_PASS",
    "monthly_exclusion_limit_cents": 30000,
}

# --- The Chicago money-conservation scenario ----------------------------------
OPENING_ROLLOVER_CENTS = 1500
ELECTED_PRETAX_CENTS = 30000
FUNDED_BALANCE_CENTS = OPENING_ROLLOVER_CENTS + ELECTED_PRETAX_CENTS  # 31500

# --- The Seattle media-unit-conservation scenario -----------------------------
UNIT_PRICE_CENTS = 3000
MEDIA_QUANTITY = 2
REPLACEMENT_FEE_CENTS = 500
SEATTLE_SURCHARGE_PCT = 4.0
LINE_GROSS_CENTS = UNIT_PRICE_CENTS * MEDIA_QUANTITY  # 6000
LINE_SURCHARGE_CENTS = 240  # 6000 * 4.0 / 100, rounded half up for this line
LINE_TOTAL_CENTS = LINE_GROSS_CENTS + LINE_SURCHARGE_CENTS  # 6240
MEDIA_ACCOUNT_ROLLOVER_CENTS = 2000

LIVE_MEDIA_STATUSES = (
    "PENDING",
    "SUBMITTED",
    "SHIPPED",
    "DELIVERED",
    "UNDELIVERED",
)


def _net_media_units(api, election_id):
    """The net media units on order: every non-CANCELLED row's quantity."""
    rows, _meta = validate_paginated(
        api.list_media_orders(
            make_order_desk_headers("desk-audit"),
            {"election_id": election_id, "limit": 100},
        )
    )
    return sum(row["quantity"] for row in rows if row["status"] in LIVE_MEDIA_STATUSES)


def _chicago_funded_election(api):
    """A FUNDED 30000-cent election over an account seeded with 1500 cents.

    Returns the employer, the account as it stood before the lock, the account
    as it stands after the funding cascade, and the election.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[dict(TRANSIT_CATEGORY)],
        legal_name="Chicago Reversal Co",
        region_code=REGION_CHI,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    enrolled = fx.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": OPENING_ROLLOVER_CENTS},
        external_ref="CHI-REV-1",
        work_region_code=REGION_CHI,
        hire_date="2026-02-01T00:00:00Z",
    )
    employee = enrolled["employee"]
    opening_account = enrolled["account"]
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    election = fx.make_election(
        api,
        employee["id"],
        window["id"],
        category["id"],
        opening_account["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=ELECTED_PRETAX_CENTS,
        posttax_amount_cents=0,
    )
    pre_lock_employer = fx.read_employer(api, employer["id"])
    locked_window = validate_success(
        api.lock_election_window(window["id"], PROGRAM_ADMIN)
    )
    return {
        "employer": employer,
        "pre_lock_employer": pre_lock_employer,
        "category": category,
        "employee": employee,
        "opening_account": opening_account,
        "window": locked_window,
        "election": fx.read_election(api, election["id"]),
        "funded_account": fx.read_account(api, opening_account["id"]),
    }


def _seattle_media_election(api):
    """A PENDING Seattle election entitled to 2 smart-card units, with one
    PENDING media line (quantity 2) already filed into an OPEN batch.

    The window is never locked, so the election stays PENDING throughout and the
    only money that ever moves is the replacement fee.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[dict(TRANSIT_CATEGORY)],
        legal_name="Seattle Unit Conservation Co",
        region_code=REGION_SEA,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    media = fx.make_transit_media(
        api,
        "desk-catalog",
        sku="SEA-UNIT",
        media_type="SMART_CARD_LOAD",
        region_code=REGION_SEA,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=UNIT_PRICE_CENTS,
        replacement_fee_cents=REPLACEMENT_FEE_CENTS,
        requires_physical_fulfillment=True,
    )
    enrolled = fx.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": MEDIA_ACCOUNT_ROLLOVER_CENTS},
        external_ref="SEA-UC-1",
        work_region_code=REGION_SEA,
        hire_date="2026-02-01T00:00:00Z",
    )
    employee = enrolled["employee"]
    account = enrolled["account"]
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    election = fx.make_election(
        api,
        employee["id"],
        window["id"],
        category["id"],
        account["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=6000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=MEDIA_QUANTITY,
    )
    batch = fx.make_open_batch(api, window["id"], REGION_SEA, "desk-sealer")
    order_a = fx.make_media_order(
        api,
        election["id"],
        media["id"],
        batch["id"],
        "desk-sealer",
        quantity=MEDIA_QUANTITY,
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-31T00:00:00Z",
    )
    return {
        "employer": employer,
        "category": category,
        "employee": employee,
        "account": account,
        "media": media,
        "window": window,
        "election": election,
        "batch": batch,
        "order_a": order_a,
    }


def _supersede_media_line(api, setup):
    """File a second line for the same election and product, superseding the
    first one on the same (election_id, transit_media_id) pair."""
    version = fx.current_election_version(api, setup["election"]["id"])
    return validate_success(
        api.create_media_order(
            f.media_order_payload(
                setup["election"]["id"],
                setup["media"]["id"],
                setup["batch"]["id"],
                version,
                quantity=MEDIA_QUANTITY,
                coverage_start_at="2026-08-01T00:00:00Z",
                coverage_end_at="2026-08-31T00:00:00Z",
            ),
            make_order_desk_headers("desk-sealer"),
        ),
        expected_status=201,
    )


# =============================================================================
# Conserved quantity 1: benefit dollars across funding and its reversal
# =============================================================================
def test_01_funding_reversal_returns_available_balance_to_its_pre_funding_value(api):
    """PRD §3.3: "Because reversal is an exact compensation, funding an election and then reversing it must leave the account's `available_balance_cents` back at precisely the value it held before the funding, with the conservation identities of §2.9 holding at every step."
    PRD §2.9: "First, `available_balance_cents` equals `rollover_in_cents` plus `contributed_cents`, minus `spent_cents`, minus `forfeited_cents`, minus `refunded_cents`, minus `reversed_cents`, minus `fee_charged_cents`."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_money_conservation_and_ledger_sum
    """
    setup = _chicago_funded_election(api)

    # BEFORE the forward action: only the carried-in balance is on the account.
    opening = setup["opening_account"]
    assert opening["available_balance_cents"] == OPENING_ROLLOVER_CENTS, (
        f"seeded account must open at {OPENING_ROLLOVER_CENTS}, "
        f"got {opening['available_balance_cents']}"
    )
    assert opening["rollover_in_cents"] == OPENING_ROLLOVER_CENTS
    assert opening["contributed_cents"] == 0
    assert opening["reversed_cents"] == 0
    assert opening["ledger_entry_count"] == 1, (
        "a non-zero opening balance writes exactly one ROLLOVER_IN row"
    )
    assert_account_conservation(opening)

    # The forward action moved the invariant.
    funded = setup["funded_account"]
    assert setup["election"]["funding_status"] == "FUNDED"
    assert funded["available_balance_cents"] == FUNDED_BALANCE_CENTS, (
        f"funding must credit the elected total, got {funded['available_balance_cents']}"
    )
    assert funded["contributed_cents"] == ELECTED_PRETAX_CENTS
    assert funded["ledger_entry_count"] == 2
    assert_account_conservation(funded)

    # The compensating action restores it exactly.
    reversed_election = validate_success(
        api.reverse_election_funding(
            setup["election"]["id"],
            {"reason": "EMPLOYER_FUNDING_RECALL"},
            PROGRAM_ADMIN,
        )
    )
    assert reversed_election["funding_status"] == "REVERSED", (
        f"funding_status must be REVERSED, got {reversed_election['funding_status']}"
    )

    restored = fx.read_account(api, setup["opening_account"]["id"])
    assert restored["available_balance_cents"] == OPENING_ROLLOVER_CENTS, (
        "reversal must return available_balance_cents to its pre-funding value "
        f"{OPENING_ROLLOVER_CENTS}, got {restored['available_balance_cents']}"
    )
    assert_account_conservation(restored)


def test_02_funding_reversal_appends_a_third_ledger_row_instead_of_unwinding_contributions(api):
    """PRD §3.3: "The election moves `FUNDED → REVERSED`, and one ledger entry with `entry_type` `FUNDING_REVERSAL` is appended to the election's benefit account carrying a negative `amount_cents` equal to the election's `total_amount_cents`, with `source_entity` `Election` and `source_id` the election's identifier."
    PRD §3.3: "The account's `reversed_cents` increases by that same `total_amount_cents`, `available_balance_cents` is recomputed, `ledger_entry_count` is incremented, and `BenefitAccount.version` advances by 1."
    PRD §2.9: "A third, order-sensitive identity governs the log itself: each entry's `balance_after_cents` equals the running signed total of all entries for that account up to and including itself, taken in ascending `created_at` order."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_money_conservation_and_ledger_sum
    """
    setup = _chicago_funded_election(api)
    account_id = setup["opening_account"]["id"]
    election = setup["election"]

    before_rows = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        before_rows,
        [
            ("ROLLOVER_IN", OPENING_ROLLOVER_CENTS, OPENING_ROLLOVER_CENTS),
            ("CONTRIBUTION", ELECTED_PRETAX_CENTS, FUNDED_BALANCE_CENTS),
        ],
    )

    validate_success(
        api.reverse_election_funding(
            election["id"], {"reason": "EMPLOYER_FUNDING_RECALL"}, PROGRAM_ADMIN
        )
    )

    rows = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        rows,
        [
            ("ROLLOVER_IN", OPENING_ROLLOVER_CENTS, OPENING_ROLLOVER_CENTS),
            ("CONTRIBUTION", ELECTED_PRETAX_CENTS, FUNDED_BALANCE_CENTS),
            ("FUNDING_REVERSAL", -ELECTED_PRETAX_CENTS, OPENING_ROLLOVER_CENTS),
        ],
    )
    compensating = rows[-1]
    assert compensating["source_entity"] == "Election"
    assert compensating["source_id"] == election["id"]
    assert compensating["benefit_account_id"] == account_id

    account = fx.read_account(api, account_id)
    assert account["contributed_cents"] == ELECTED_PRETAX_CENTS, (
        "the compensation is additive: contributed_cents is never rolled back, "
        f"got {account['contributed_cents']}"
    )
    assert account["reversed_cents"] == ELECTED_PRETAX_CENTS, (
        f"reversed_cents must carry the reversal, got {account['reversed_cents']}"
    )
    assert account["rollover_in_cents"] == OPENING_ROLLOVER_CENTS
    assert account["spent_cents"] == 0
    assert account["forfeited_cents"] == 0
    assert account["refunded_cents"] == 0
    assert account["fee_charged_cents"] == 0
    assert account["available_balance_cents"] == OPENING_ROLLOVER_CENTS
    assert account["ledger_entry_count"] == 3
    assert_account_conservation(account)
    assert_ledger_matches_account(account, rows)


def test_03_funding_reversal_unwinds_the_employer_pretax_commitment(api):
    """PRD §3.4: "The employer's `total_pretax_committed_cents` is recomputed as the sum of `excluded_amount_cents` over every election whose window belongs to this employer and whose `funding_status` is exactly `FUNDED`."
    PRD §3.4: "The same commitment recomputation runs after an amendment to an already-`FUNDED` election and after a funding reversal."

    Design: Difficulty/compensating_invariant/funding_reversal_restores_money_conservation_and_ledger_sum
    """
    setup = _chicago_funded_election(api)

    assert setup["pre_lock_employer"]["total_pretax_committed_cents"] == 0, (
        "a PENDING election commits nothing, got "
        f"{setup['pre_lock_employer']['total_pretax_committed_cents']}"
    )

    funded_employer = fx.read_employer(api, setup["employer"]["id"])
    assert funded_employer["total_pretax_committed_cents"] == ELECTED_PRETAX_CENTS, (
        "the funded election must be committed, got "
        f"{funded_employer['total_pretax_committed_cents']}"
    )
    assert funded_employer["program_status"] == "ACTIVE", (
        "30000 committed is far below the 5000000 program cap, so no suspension"
    )

    validate_success(
        api.reverse_election_funding(
            setup["election"]["id"],
            {"reason": "EMPLOYER_FUNDING_RECALL"},
            PROGRAM_ADMIN,
        )
    )

    unwound = fx.read_employer(api, setup["employer"]["id"])
    assert unwound["total_pretax_committed_cents"] == 0, (
        "a REVERSED election is no longer exactly FUNDED, so the commitment "
        f"returns to 0, got {unwound['total_pretax_committed_cents']}"
    )
    assert unwound["program_status"] == "ACTIVE"


# =============================================================================
# Conserved quantity 2: physical media units across supersede and reissue
# =============================================================================
def test_04_superseding_a_pending_media_line_conserves_entitled_media_units(api):
    """PRD §2.10: "The net media units actually on order for that election is the sum of `quantity` over the election's media order rows whose `status` is `PENDING`, `SUBMITTED`, `SHIPPED`, `DELIVERED` or `UNDELIVERED`; rows whose `status` is `CANCELLED` are the only exclusion, and that includes every row cancelled because a later create superseded it."
    PRD §3.5: "Like elections, media lines supersede rather than stack: when a `PENDING` line already exists for the same `election_id` and `transit_media_id` pair, that older line is moved to `CANCELLED`, the new row's `superseded_media_order_id` is set to the older line's identifier, and `MediaOrder.version` advances by 1 on the cancelled row."

    Design: Difficulty/compensating_invariant/media_supersede_and_reissue_conserve_entitled_media_units
    """
    setup = _seattle_media_election(api)
    election_id = setup["election"]["id"]

    assert setup["election"]["entitled_media_units"] == MEDIA_QUANTITY, (
        f"media_quantity 2 must land as entitled_media_units, "
        f"got {setup['election']['entitled_media_units']}"
    )
    assert setup["order_a"]["status"] == "PENDING"
    assert setup["order_a"]["superseded_media_order_id"] is None
    assert _net_media_units(api, election_id) == MEDIA_QUANTITY, (
        "before the cycle the single live line already covers the entitlement"
    )

    order_b = _supersede_media_line(api, setup)
    assert order_b["superseded_media_order_id"] == setup["order_a"]["id"], (
        "the new line must name the line it displaced, got "
        f"{order_b['superseded_media_order_id']}"
    )
    assert order_b["quantity"] == MEDIA_QUANTITY
    assert order_b["status"] == "PENDING"

    order_a = fx.read_media_order(api, setup["order_a"]["id"])
    assert order_a["status"] == "CANCELLED", (
        f"the superseded line must be CANCELLED, got {order_a['status']}"
    )

    rows, meta = validate_paginated(
        api.list_media_orders(
            make_order_desk_headers("desk-audit"),
            {"election_id": election_id, "limit": 100},
        )
    )
    assert meta["total_count"] == 2, (
        f"both the cancelled and the surviving row persist, got {meta['total_count']}"
    )
    assert sorted(row["status"] for row in rows) == ["CANCELLED", "PENDING"]
    assert _net_media_units(api, election_id) == MEDIA_QUANTITY, (
        "a supersede cycle may not mint extra media units: the net must still be "
        f"{MEDIA_QUANTITY}, got {_net_media_units(api, election_id)}"
    )

    election = fx.read_election(api, election_id)
    assert election["entitled_media_units"] == MEDIA_QUANTITY
    assert election["fulfillment_status"] == "ORDERED"


def test_05_undelivered_then_reissue_conserves_media_units_on_the_same_row(api):
    """PRD §2.10: "After any completed forward-plus-compensating media cycle — reporting a line undelivered and then reissuing it, or creating a line and then superseding it with a newer one — that net must equal `entitled_media_units` exactly."
    PRD §3.6: "Alongside the fee, the reissue increments the line's `replacement_count` by 1 and adds the fee to its `replacement_fee_charged_cents`, moves the line `UNDELIVERED → SUBMITTED` on the **same row with the same `quantity`**, and clears `tracking_ref` back to null so the next shipment can record a fresh one."
    PRD §3.6: "Reusing the same row with the same `quantity` is what preserves the media unit conservation of §2.10: a full cycle of report-undelivered followed by reissue mints no additional media units."

    Design: Difficulty/compensating_invariant/media_supersede_and_reissue_conserve_entitled_media_units
    """
    setup = _seattle_media_election(api)
    election_id = setup["election"]["id"]
    account_id = setup["account"]["id"]
    sealer = make_order_desk_headers("desk-sealer")

    order_b = _supersede_media_line(api, setup)
    assert _net_media_units(api, election_id) == MEDIA_QUANTITY

    validate_success(api.seal_order_batch(setup["batch"]["id"], sealer))
    validate_success(
        api.release_order_batch(
            setup["batch"]["id"], make_order_desk_headers("desk-releaser")
        )
    )
    shipped = validate_success(
        api.ship_media_order(order_b["id"], {"tracking_ref": "TRK-SEA-UC-1"}, sealer)
    )
    assert shipped["status"] == "SHIPPED"
    assert shipped["tracking_ref"] == "TRK-SEA-UC-1"
    assert _net_media_units(api, election_id) == MEDIA_QUANTITY

    # The forward action: the pass never arrived.
    undelivered = validate_success(
        api.report_media_order_undelivered(
            order_b["id"], {"reason": "NEVER_ARRIVED"}, sealer
        )
    )
    assert undelivered["status"] == "UNDELIVERED"
    assert undelivered["undelivered_reason"] == "NEVER_ARRIVED"
    assert _net_media_units(api, election_id) == MEDIA_QUANTITY, (
        "an UNDELIVERED row still counts toward the net on-order units"
    )

    # The compensating action: reissue the very same row.
    reissued = validate_success(
        api.reissue_media_order(
            order_b["id"], {"waive_replacement_fee": False}, sealer
        )
    )
    assert reissued["id"] == order_b["id"], "reissue must reuse the same row"
    assert reissued["status"] == "SUBMITTED", (
        f"reissue moves UNDELIVERED -> SUBMITTED, got {reissued['status']}"
    )
    assert reissued["quantity"] == MEDIA_QUANTITY, (
        f"the reissued row keeps its quantity, got {reissued['quantity']}"
    )
    assert reissued["replacement_count"] == 1
    assert reissued["tracking_ref"] is None, (
        f"reissue clears tracking_ref, got {reissued['tracking_ref']!r}"
    )
    assert reissued["replacement_fee_charged_cents"] == REPLACEMENT_FEE_CENTS

    assert _net_media_units(api, election_id) == MEDIA_QUANTITY, (
        "after both the supersede cycle and the undelivered-then-reissue cycle "
        f"the net must be exactly {MEDIA_QUANTITY} units, got "
        f"{_net_media_units(api, election_id)}"
    )
    election = fx.read_election(api, election_id)
    assert election["entitled_media_units"] == MEDIA_QUANTITY
    assert election["fulfillment_status"] == "ORDERED", (
        "no line is UNDELIVERED and none is yet SHIPPED again, so the election "
        f"returns to ORDERED, got {election['fulfillment_status']}"
    )
    assert election["funding_status"] == "PENDING", (
        "the window was never locked, so the money side never moved"
    )

    account = fx.read_account(api, account_id)
    assert account["fee_charged_cents"] == REPLACEMENT_FEE_CENTS
    assert account["available_balance_cents"] == (
        MEDIA_ACCOUNT_ROLLOVER_CENTS - REPLACEMENT_FEE_CENTS
    )
    assert account["ledger_entry_count"] == 2
    assert_account_conservation(account)
    rows = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        rows,
        [
            (
                "ROLLOVER_IN",
                MEDIA_ACCOUNT_ROLLOVER_CENTS,
                MEDIA_ACCOUNT_ROLLOVER_CENTS,
            ),
            (
                "REPLACEMENT_FEE",
                -REPLACEMENT_FEE_CENTS,
                MEDIA_ACCOUNT_ROLLOVER_CENTS - REPLACEMENT_FEE_CENTS,
            ),
        ],
    )
    assert rows[-1]["source_entity"] == "MediaOrder"
    assert rows[-1]["source_id"] == order_b["id"]
    assert_ledger_matches_account(account, rows)


def test_06_sealed_invoice_bills_only_the_surviving_media_line(api):
    """PRD §3.5: "Exactly those `PENDING` lines are priced; lines already cancelled by a supersede create are excluded, and no line can be added after the seal because the batch has left `OPEN`."
    PRD §3.5: "For each priced line, `line_gross_cents` is `unit_price_cents_snapshot` multiplied by `quantity`;"
    PRD §3.5: "The regional surcharge percentages are 7.5 percent for `US-CA-SFO`, 6.25 percent for `US-NY-NYC`, 5.0 percent for `US-IL-CHI`, 4.0 percent for `US-WA-SEA` and 2.5 percent for `US-TX-AUS`."

    Design: Difficulty/compensating_invariant/media_supersede_and_reissue_conserve_entitled_media_units
    """
    setup = _seattle_media_election(api)
    election_id = setup["election"]["id"]
    sealer = make_order_desk_headers("desk-sealer")

    order_b = _supersede_media_line(api, setup)

    sealed = validate_success(api.seal_order_batch(setup["batch"]["id"], sealer))
    assert sealed["status"] == "SEALED"
    assert_invoice_totals(
        sealed,
        line_count=1,
        subtotal_cents=LINE_TOTAL_CENTS,
        discount_cents=0,
        total_cents=LINE_TOTAL_CENTS,
    )

    priced = fx.read_media_order(api, order_b["id"])
    assert priced["unit_price_cents_snapshot"] == UNIT_PRICE_CENTS
    assert_media_line(
        priced,
        line_gross_cents=LINE_GROSS_CENTS,
        line_surcharge_cents=LINE_SURCHARGE_CENTS,
        line_total_cents=LINE_TOTAL_CENTS,
    )

    cancelled = fx.read_media_order(api, setup["order_a"]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert_media_line(
        cancelled, line_gross_cents=0, line_surcharge_cents=0, line_total_cents=0
    )

    assert _net_media_units(api, election_id) == MEDIA_QUANTITY, (
        "sealing bills one line, and the conserved unit count is still "
        f"{MEDIA_QUANTITY}"
    )
