"""Custom baling service orders: cutting-state gate, equipment buffer,
billing tiers and floor, moisture safety, and the grower-suspend cascade.

Covers PRD §3.9 (baling service orders) and §3.1 (grower suspension).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    complete_baling_order,
    create_baling_order,
    create_field,
    create_grower,
    create_cutting,
    open_cutting_window,
    schedule_baling_order,
    setup_in_progress_baling_order,
    setup_scheduled_cutting,
    start_baling_order,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# cross_entity_state_dependency / bso_schedule_gated_on_cutting_state
# ===========================================================================

class TestBsoScheduleGatedOnCuttingState:
    def test_schedule_rejected_while_cutting_scheduled(self, api):
        """PRD §3.9: "Two conditions guard scheduling: the referenced cutting
        must be `WINDOW_OPEN` or `CUT` (again `ERR_BSO_WRONG_STATE`), since
        baling hay that is not yet in or past its window is pointless".

        With no weather reports the cutting is still SCHEDULED, so the
        schedule attempt is rejected.

        Design: Difficulty/cross_entity_state_dependency/bso_schedule_gated_on_cutting_state
        """
        grower, _field, cutting = setup_scheduled_cutting()
        bso = create_baling_order(grower["id"], cutting["id"])
        resp = api_client.schedule_baling_service_order(
            bso["id"],
            {"scheduled_date": "2026-08-05", "equipment_unit": "BALER-7"},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_BSO_WRONG_STATE)

    def test_schedule_succeeds_once_window_opens(self, api):
        """PRD §3.1: "If all three days have reports and each is both dry and
        drying-capable, a `SCHEDULED` cutting flips to `WINDOW_OPEN`." PRD
        §3.9: "Scheduling stamps `scheduled_date` and `equipment_unit` and
        moves the order to `SCHEDULED`."

        The identical schedule call succeeds once the cutting's window opens.

        Design: Difficulty/cross_entity_state_dependency/bso_schedule_gated_on_cutting_state
        """
        grower, _field, cutting = setup_scheduled_cutting()
        bso = create_baling_order(grower["id"], cutting["id"])
        open_cutting_window(cutting["id"], grower_id=grower["id"])
        scheduled = validate_success(api_client.schedule_baling_service_order(
            bso["id"],
            {"scheduled_date": "2026-08-05", "equipment_unit": "BALER-7"},
            OPS,
        ))
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["scheduled_date"] == "2026-08-05"
        assert scheduled["equipment_unit"] == "BALER-7"


# ===========================================================================
# resource_temporal_overlap / equipment_buffer_day_gap
# ===========================================================================

class TestEquipmentBufferDayGap:
    def _two_open_orders(self):
        """One grower, two fields, two WINDOW_OPEN cuttings, two REQUESTED
        baling orders."""
        grower = create_grower(name="Grower Fifteen")
        field_a = create_field(grower["id"], name="East 1")
        field_b = create_field(grower["id"], name="East 2")
        cutting_a = create_cutting(field_a["id"], grower["id"])
        cutting_b = create_cutting(field_b["id"], grower["id"])
        open_cutting_window(cutting_a["id"], grower_id=grower["id"])
        bso_a = create_baling_order(grower["id"], cutting_a["id"])
        bso_b = create_baling_order(grower["id"], cutting_b["id"])
        return bso_a, bso_b

    def test_one_day_gap_conflicts(self, api):
        """PRD §3.9: "the equipment buffer requires that no other order on the
        same `equipment_unit` in `SCHEDULED` or `IN_PROGRESS` status have a
        scheduled date within less than two days of this one — the absolute
        difference between the two dates must be at least two days,
        guaranteeing one idle day between jobs — otherwise
        `ERR_EQUIPMENT_BUFFER_CONFLICT`."

        BALER-7 taken on 2026-08-03 rejects a second job on 2026-08-04 (one
        day apart).

        Design: Difficulty/resource_temporal_overlap/equipment_buffer_day_gap
        """
        bso_a, bso_b = self._two_open_orders()
        scheduled = schedule_baling_order(
            bso_a["id"], scheduled_date="2026-08-03", equipment_unit="BALER-7",
        )
        assert scheduled["status"] == "SCHEDULED"
        resp = api_client.schedule_baling_service_order(
            bso_b["id"],
            {"scheduled_date": "2026-08-04", "equipment_unit": "BALER-7"},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_BUFFER_CONFLICT)

    def test_two_day_gap_allowed(self, api):
        """PRD §3.9: "the absolute difference between the two dates must be at
        least two days, guaranteeing one idle day between jobs — otherwise
        `ERR_EQUIPMENT_BUFFER_CONFLICT`."

        Two days after the 2026-08-03 job (i.e. 2026-08-05) leaves exactly
        one idle day and schedules cleanly.

        Design: Difficulty/resource_temporal_overlap/equipment_buffer_day_gap
        """
        bso_a, bso_b = self._two_open_orders()
        schedule_baling_order(
            bso_a["id"], scheduled_date="2026-08-03", equipment_unit="BALER-7",
        )
        scheduled = validate_success(api_client.schedule_baling_service_order(
            bso_b["id"],
            {"scheduled_date": "2026-08-05", "equipment_unit": "BALER-7"},
            OPS,
        ))
        assert scheduled["status"] == "SCHEDULED"


# ===========================================================================
# Corner/calculations / baling_billing_marginal_tiers_and_floor
# ===========================================================================

def test_baling_billing_marginal_tiers_and_floor(api):
    """PRD §3.9: "The subtotal prices each bale at its marginal rate: the
    first 500 bales at 1200 cents apiece, bales 501 through 1000 at 1050
    cents apiece, and every bale beyond 1000 at 900 cents apiece." PRD §3.9:
    "The invoice is then the subtotal plus any surcharge, but never less than
    the minimum charge of 600000 cents; the minimum is applied last, after
    the surcharge". PRD §3.9: invoicing "computes the bill, sets
    `invoice_cents`, adds that amount to the grower's
    `outstanding_balance_cents`".

    501 dry bales bill 500 x 1200 + 1 x 1050 = 601050 (marginal tiers, not an
    average rate); 400 dry bales compute 480000 but the floor bills 600000.
    The grower's outstanding balance accumulates both invoices.

    Design: Corner/calculations/baling_billing_marginal_tiers_and_floor
    """
    grower = create_grower(name="Grower N")
    field1 = create_field(grower["id"], name="Field N1", forage_type="GRASS")
    field2 = create_field(grower["id"], name="Field N2", forage_type="GRASS")
    c1 = create_cutting(field1["id"], grower["id"])
    c2 = create_cutting(field2["id"], grower["id"])
    open_cutting_window(c1["id"], grower_id=grower["id"])
    bso_a = create_baling_order(grower["id"], c1["id"])
    bso_b = create_baling_order(grower["id"], c2["id"])
    schedule_baling_order(bso_a["id"], scheduled_date="2026-08-03",
                          equipment_unit="BALER-1")
    schedule_baling_order(bso_b["id"], scheduled_date="2026-08-03",
                          equipment_unit="BALER-2")
    start_baling_order(bso_a["id"])
    start_baling_order(bso_b["id"])
    complete_baling_order(bso_a["id"], actual_bale_count=501,
                          baled_moisture_pct=15.0)
    complete_baling_order(bso_b["id"], actual_bale_count=400,
                          baled_moisture_pct=15.0)
    inv_a = validate_success(api_client.invoice_baling_service_order(bso_a["id"], OPS))
    inv_b = validate_success(api_client.invoice_baling_service_order(bso_b["id"], OPS))
    assert inv_a["invoice_cents"] == 601050
    assert inv_b["invoice_cents"] == 600000
    grower_read = validate_success(api_client.get_grower(grower["id"], ADMIN))
    assert grower_read["outstanding_balance_cents"] == 1201050


# ===========================================================================
# Corner/validations / moisture_unsafe_blocks_complete
# ===========================================================================

def test_moisture_unsafe_blocks_complete(api):
    """PRD §3.9: "Completing an `IN_PROGRESS` order records the
    `actual_bale_count` and the `baled_moisture_pct`, subject to a hard
    safety gate: bale moisture above 20.0 is unsafe, and completion with such
    a reading is rejected outright with `ERR_MOISTURE_UNSAFE`; a reading of
    exactly 20.0 or below completes normally."

    Completing at 20.5% moisture is rejected and the order stays IN_PROGRESS.

    Design: Corner/validations/moisture_unsafe_blocks_complete
    """
    ctx = setup_in_progress_baling_order(
        equipment_unit="BALER-3", field_overrides={"forage_type": "GRASS"},
    )
    resp = api_client.complete_baling_service_order(
        ctx["bso"]["id"],
        {"actual_bale_count": 300, "baled_moisture_pct": 20.5},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_MOISTURE_UNSAFE)
    read = validate_success(
        api_client.get_baling_service_order(ctx["bso"]["id"], ADMIN)
    )
    assert read["status"] == "IN_PROGRESS"


# ===========================================================================
# Corner/state_machines / bso_invoice_before_complete_rejected
# ===========================================================================

def test_bso_invoice_before_complete_rejected(api):
    """PRD §3.9: "`BrokerOps` invoices a `COMPLETED` order, which computes
    the bill, sets `invoice_cents`, adds that amount to the grower's
    `outstanding_balance_cents`, and moves the order to terminal
    `INVOICED`." PRD §2.6: "State-machine guards, including the
    optimistic-concurrency stale-version check: the from-state must match
    the attempted transition". Baling-order from-state mismatches draw
    `ERR_BSO_WRONG_STATE` (PRD §3.9: "from any other state,
    `ERR_BSO_WRONG_STATE`").

    A REQUESTED order has never been completed, so invoicing it is rejected
    and the order stays REQUESTED.

    Design: Corner/state_machines/bso_invoice_before_complete_rejected
    """
    grower, _field, cutting = setup_scheduled_cutting(
        field_overrides={"forage_type": "GRASS"},
    )
    bso = create_baling_order(grower["id"], cutting["id"])
    resp = api_client.invoice_baling_service_order(bso["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_BSO_WRONG_STATE)
    read = validate_success(api_client.get_baling_service_order(bso["id"], ADMIN))
    assert read["status"] == "REQUESTED"


# ===========================================================================
# Corner/state_machines / grower_suspend_cancels_open_bsos
# ===========================================================================

def test_grower_suspend_cancels_open_bsos(api):
    """PRD §3.1: "suspension carries a conditional cascade: every baling
    service order belonging to that grower still in `REQUESTED` or
    `SCHEDULED` status is cancelled outright."

    The REQUESTED order is cancelled by the cascade; the IN_PROGRESS order is
    untouched.

    Design: Corner/state_machines/grower_suspend_cancels_open_bsos
    """
    grower, _field, cutting = setup_scheduled_cutting()
    open_cutting_window(cutting["id"], grower_id=grower["id"])
    bso_a = create_baling_order(grower["id"], cutting["id"])
    bso_b = create_baling_order(grower["id"], cutting["id"])
    schedule_baling_order(bso_b["id"], scheduled_date="2026-08-03",
                          equipment_unit="BALER-9")
    start_baling_order(bso_b["id"])

    suspended = validate_success(api_client.suspend_grower(grower["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    read_a = validate_success(api_client.get_baling_service_order(bso_a["id"], ADMIN))
    read_b = validate_success(api_client.get_baling_service_order(bso_b["id"], ADMIN))
    assert read_a["status"] == "CANCELLED"
    assert read_b["status"] == "IN_PROGRESS"
