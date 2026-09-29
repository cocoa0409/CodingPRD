"""The two optimistic-concurrency guards seen from both sides, and the sweep at
the tolerated end of the delinquency threshold."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    agreement_payload,
    api_client,
    assert_instant_equals,
    assign_room,
    confirm_traveler,
    create_plan,
    enrol_traveler,
    expected_installment_amounts,
    hold_filler_service,
    open_departure,
    open_sales,
    pay,
    program_with_departure,
    read_departure,
    read_plan,
    read_traveler,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    HOLY_LAND_T1_INVOICE_CENTS,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
FINANCE = TEST_USERS["finance_controller"]


def test_a_version_read_before_the_re_rooming_no_longer_buys_a_plan(api):
    """PRD §2.7: "Creating an installment plan for a traveler — `POST
    /pilgrims/{pilgrimId}/payment-plans` — requires `expected_pilgrim_version`,
    carrying the `version` of the target `Pilgrim` that the client last observed.
    If that value does not equal the traveler's current `version`, the request is
    rejected with `ERR_STALE_PILGRIM_VERSION` (HTTP 412). This is what stops a
    client from rescheduling against a traveler ledger it no longer understands —
    for instance building a plan on an invoice total that a later air deviation or
    a group-size repricing has already replaced." Rooming is one of the writes
    that moves it, per §3.5: "A successful assignment writes
    `room_type_assigned`, `room_label`, `ground_floor` and `dietary_codes`, writes
    `roommate_pilgrim_id` on **both** travelers so the pairing is mutual, sets
    `single_supplement_applied_cents` to the departure's
    `provisional_single_supplement_cents` when `room_type_assigned` is `SINGLE`
    and clears it to 0 otherwise, recomputes the invoice, and increments the
    traveler's `version`." PRD §3.7: "With no plan the money dimension is judged
    directly against the invoice: `payment_status` becomes `PAID_IN_FULL` when
    `cash_applied_cents` has reached `invoice_total_cents`, otherwise
    `DEPOSIT_PAID` when it has reached the departure's `provisional_deposit_cents`,
    and otherwise `UNPAID`."

    Design: Corner/cross_cutting_complexity_layers/stale_pilgrim_version_on_payment_plan_create_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Traveler A",
        date_of_birth="1975-01-10",
        room_type_requested="DOUBLE",
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-230")
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    observed = read_traveler(traveler["id"], FINANCE)
    stale_version = observed["version"]
    # A second rooming call moves the traveler one version on.
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-232")

    response = api_client.create_payment_plan(
        traveler["id"],
        {
            "plan_type": "MONTHLY_3",
            "first_due_date": "2026-08-15",
            "expected_pilgrim_version": stale_version,
        },
        FINANCE,
    )
    validate_error(response, ApiErrorId.STALE_PILGRIM_VERSION.value)

    live = read_traveler(traveler["id"])
    assert live["invoice_total_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    assert live["payment_status"] == "DEPOSIT_PAID"
    # Nothing was scheduled, so the traveler still has no ledger.
    _rows, meta = validate_paginated(
        api_client.list_payment_plans(FINANCE, {"pilgrim_id": traveler["id"]})
    )
    assert meta["total_count"] == 0


def test_the_freshly_read_version_buys_a_plan_that_drains_the_credit(api):
    """PRD §2.7: "Creating an installment plan for a traveler — `POST
    /pilgrims/{pilgrimId}/payment-plans` — requires `expected_pilgrim_version`,
    carrying the `version` of the target `Pilgrim` that the client last observed.
    If that value does not equal the traveler's current `version`, the request is
    rejected with `ERR_STALE_PILGRIM_VERSION` (HTTP 412)." PRD §3.7: "The plan
    derives `installment_count` as 1 for `SINGLE_BALANCE`, 3 for `MONTHLY_3` and 6
    for `MONTHLY_6`, captures `total_scheduled_cents` from the traveler's current
    `invoice_total_cents`, and builds the `installments` array. The base amount is
    `total_scheduled_cents` divided by the installment count using integer floor
    division, and the remainder is `total_scheduled_cents` less the base amount
    multiplied by the count." And: "The new plan's schedule is built from the
    traveler's **current** `invoice_total_cents` — the prior plan's payments do not
    reduce it, because that money has just been returned to credit — and then the
    whole of `credit_balance_cents` is drained into the new installments by the
    same waterfall, earliest due date first. The traveler's `payment_status`
    becomes `PLAN_ACTIVE`, except that when the drained credit already covers the
    whole schedule the plan completes and `payment_status` becomes `PAID_IN_FULL`
    in the same request." The drain follows the receipt waterfall: "For each
    installment in turn, the shortfall is its `amount_due_cents` less its
    `amount_paid_cents`, the amount taken is the lesser of that shortfall and the
    cash still unallocated, `amount_paid_cents` increases by the amount taken, the
    remaining cash decreases by it, and the installment's `status` becomes `PAID`
    when `amount_paid_cents` now equals `amount_due_cents` and `PARTIALLY_PAID`
    otherwise."

    Design: Corner/cross_cutting_complexity_layers/payment_plan_create_with_the_current_version_succeeds
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Traveler A",
        date_of_birth="1975-01-10",
        room_type_requested="DOUBLE",
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-231")
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    # Read taken after the last write, so the version quoted is the live one.
    observed = read_traveler(traveler["id"], FINANCE)
    assert observed["credit_balance_cents"] == 50_000

    created = validate_success(
        api_client.create_payment_plan(
            traveler["id"],
            {
                "plan_type": "MONTHLY_3",
                "first_due_date": "2026-08-15",
                "expected_pilgrim_version": observed["version"],
            },
            FINANCE,
        ),
        201,
    )

    assert created["installment_count"] == 3
    assert created["total_scheduled_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    amounts = expected_installment_amounts(HOLY_LAND_T1_INVOICE_CENTS, 3)
    assert amounts == [192_390, 192_389, 192_389]
    assert [item["amount_due_cents"] for item in created["installments"]] == amounts
    installments = read_plan(created["id"])["installments"]
    # The 50,000 sitting in credit lands on the earliest due date.
    assert installments[0]["amount_paid_cents"] == 50_000
    assert installments[0]["status"] == "PARTIALLY_PAID"
    assert installments[1]["amount_paid_cents"] == 0
    assert installments[1]["status"] == "SCHEDULED"
    assert read_plan(created["id"])["status"] == "ACTIVE"

    live = read_traveler(traveler["id"])
    assert live["credit_balance_cents"] == 0
    assert live["payment_status"] == "PLAN_ACTIVE"


def test_the_version_that_opening_sales_moved_on_no_longer_buys_an_agreement(api):
    """PRD §2.7: "Creating a group leader agreement — `POST
    /group-leader-agreements` — requires `expected_departure_version`, carrying
    the `version` of the target `Departure` that the client last observed. If that
    value does not equal the departure's current `version`, the request is
    rejected with `ERR_STALE_DEPARTURE_VERSION` (HTTP 412). Because a new
    agreement for the same departure and the same leader identifier legitimately
    supersedes the prior one, the stale-version check is the only deterministic
    guard against renegotiating terms on an outdated view of the departure." PRD
    §3.1: "Opening sales clears `final_tier_code` back to unset and
    `final_per_pax_price_cents` back to 0, re-derives the provisional snapshot,
    re-reads the risk posture, and increments the departure's `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_departure_version_on_agreement_create_rejected
    """
    program, departure = program_with_departure()
    stale_version = departure["version"]
    hold_filler_service(program, departure)
    opened = open_sales(departure["id"])
    assert opened["status"] == "OPEN_FOR_SALE"

    response = api_client.create_agreement(
        agreement_payload(
            departure["id"],
            stale_version,
            leader_name="Fr. Alonso Reyes",
            leader_user_id="u-leader-alonso",
            free_travel_threshold=6,
            commission_mode="PER_PAX_CASH",
            commission_rate_cents_per_pax=6000,
            accrual_basis="RECRUITED",
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.STALE_DEPARTURE_VERSION.value)

    assert read_departure(departure["id"])["status"] == "OPEN_FOR_SALE"
    _rows, meta = validate_paginated(
        api_client.list_agreements(PLANNER, {"departure_id": departure["id"]})
    )
    assert meta["total_count"] == 0


def test_a_single_overdue_installment_is_marked_but_tolerated(api):
    """PRD §3.7: "Hop one: every installment whose `status` is `SCHEDULED` or
    `PARTIALLY_PAID` and whose `due_date` is strictly before the logical clock's
    date moves to `PAST_DUE`, and each plan's `past_due_count` is refreshed. Hop
    two: a plan whose refreshed `past_due_count` has reached 2 or more moves to
    `DEFAULTED` and its traveler's `payment_status` becomes `IN_DEFAULT` — one
    missed installment is tolerated, two is not. Hop three: a defaulted traveler
    has their `ticketed_name` cleared, which decrements `seats_assigned` on the
    departure's blocks, and a defaulted traveler in `CONFIRMED` reverts to
    `DEPOSITED`, which in turn re-runs the departure's provisional tier
    calculation and the recruiting agreement's snapshot accrual. The sweep always
    increments the departure's `sweep_run_count` and stamps `last_sweep_at` with
    the logical clock, even when it defaults nobody; and when the clock has
    reached the `departure_date`, the same call carries a `SALES_CLOSED` departure
    on to `OPERATED`."

    Design: Corner/cross_cutting_complexity_layers/one_past_due_installment_stays_below_the_default_threshold
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    traveler = enrol_traveler(
        departure_id,
        full_name="Traveler A",
        date_of_birth="1975-01-10",
        room_type_requested="DOUBLE",
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-233")
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    confirm_traveler(traveler["id"])
    plan = create_plan(traveler["id"], "MONTHLY_3", "2026-08-15")
    # One day past the first due date, and no further installment is due yet.
    set_clock("2026-08-16T00:00:00Z")

    validate_success(api_client.run_payment_sweep(departure_id, FINANCE))

    swept = read_plan(plan["id"])
    assert swept["past_due_count"] == 1
    assert swept["status"] == "ACTIVE"
    assert swept["installments"][0]["status"] == "PAST_DUE"
    assert swept["installments"][1]["status"] == "SCHEDULED"
    assert swept["installments"][2]["status"] == "SCHEDULED"
    assert read_traveler(traveler["id"])["booking_status"] == "CONFIRMED"
    live = read_departure(departure_id)
    assert live["sweep_run_count"] == 1
    assert_instant_equals(live["last_sweep_at"], "2026-08-16T00:00:00Z")
