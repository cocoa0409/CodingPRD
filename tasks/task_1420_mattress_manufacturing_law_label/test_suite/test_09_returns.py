"""Returns: comfort window, receive/inspect, and the three resolutions (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_return_request,
    assert_unit,
    create_return_payload,
    setup_delivered_order,
    setup_inspected_return,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]


def test_comfort_exchange_window_inclusive_then_closed(api):
    """PRD §3.9: "A comfort-exchange return is also bound to the 100-night
    comfort window: a `COMFORT_EXCHANGE` request made when the logical clock
    has passed the unit's `delivered_at` plus 100 days is rejected with
    `ERR_OUTSIDE_COMFORT_WINDOW` (409)."

    Design: Corner/validations/comfort_window_boundary_inclusive
    """
    ctx = setup_delivered_order(quantity=2, foam_mass_required_kg=20)
    retailer_headers = make_retailer_headers(ctx["retailer"]["id"])
    u1, u2 = ctx["units"][0]["id"], ctx["units"][1]["id"]

    # Delivered at 2026-08-02T00:00:00Z; exactly +100 days has not yet passed
    # the window end, so the request is accepted.
    get_success_data(api.set_clock("2026-11-10T00:00:00Z", PM))
    opened = validate_success(api.create_return(
        create_return_payload(
            unit_id=u1, retailer_id=ctx["retailer"]["id"], reason="COMFORT_EXCHANGE",
        ),
        retailer_headers,
    ), expected_status=201)
    assert_return_request(opened)
    assert opened["status"] == "REQUESTED"

    # One second past the window end the same request is rejected.
    get_success_data(api.set_clock("2026-11-10T00:00:01Z", PM))
    late = api.create_return(
        create_return_payload(
            unit_id=u2, retailer_id=ctx["retailer"]["id"], reason="COMFORT_EXCHANGE",
        ),
        retailer_headers,
    )
    validate_error(late, ApiErrorId.ERR_OUTSIDE_COMFORT_WINDOW)


def test_return_exchange_resolution_creates_replacement_unit(api):
    """PRD §3.9: "`EXCHANGE` is valid only when the return's `reason` is
    `COMFORT_EXCHANGE` — an exchange resolution on a `DEFECT` return is
    rejected with `ERR_RESOLUTION_REASON_MISMATCH` (409)."
    PRD §3.9: "It manufactures a replacement unit against the same order,
    model, and batch, born `MANUFACTURED` and recorded as the return's
    `replacement_unit_id`, while the original unit moves `RETURNED` →
    `RECOVERED` — core recovery keeps it in the plant — and the return closes
    as `RESOLVED_EXCHANGE`."

    Design: Corner/state_machines/return_exchange_creates_replacement_unit
    """
    ctx = setup_inspected_return(reason="COMFORT_EXCHANGE", measured_sag_inches=0.8)
    unit_id = ctx["units"][0]["id"]

    resolved = validate_success(api.resolve_return(
        ctx["return"]["id"], {"resolution": "EXCHANGE"}, PM
    ))
    assert resolved["status"] == "RESOLVED_EXCHANGE"
    replacement_id = resolved["replacement_unit_id"]
    assert replacement_id, "EXCHANGE resolution must record replacement_unit_id"

    original = get_success_data(api.get_unit(unit_id, PM))
    assert original["status"] == "RECOVERED"

    replacement = get_success_data(api.get_unit(replacement_id, PM))
    assert_unit(replacement)
    assert replacement["status"] == "MANUFACTURED"
    assert replacement["order_id"] == ctx["order"]["id"]
    assert replacement["foam_batch_id"] == ctx["batch"]["id"]
    assert replacement["model_id"] == ctx["model"]["id"]


def test_return_recycle_resolution_scraps_unit_and_creates_intake(api):
    """PRD §3.9: "`RECYCLE` requires the unit's retailer to have
    `recycling_enrolled` true (`ERR_RECYCLING_NOT_ENROLLED`); the original
    unit moves `RETURNED` → `SCRAPPED`, which in turn creates a
    `RecyclingIntake` for the unit's retailer with `unit_id` set to the unit
    and `declared_weight_kg` equal to the sum of the model BOM's
    `quantity_per_unit` over the `FOAM_CORE`, `MEMORY_LAYER`, `TICKING`, and
    `FOUNDATION` lines, and the provisional credit that intake posts lands on
    the ledger with source `EXCHANGE_RECOVERY`."
    PRD §3.9: "The provisional credit is computed immediately:
    `declared_weight_kg` multiplied by a flat 20 cents per kilogram, rounded
    half up to integer cents, stored as `provisional_credit_cents`, and posted
    to the retailer's ledger as a `CreditAdjustment` with source
    `RECYCLING_PROVISIONAL` and `source_id` set to the intake."

    Design: Corner/state_machines/recycle_resolution_creates_intake_cascade
    """
    # One FOAM_CORE line with quantity_per_unit 2.0 -> declared weight 2.0 kg.
    ctx = setup_inspected_return(reason="DEFECT", measured_sag_inches=2.1)
    unit_id = ctx["units"][0]["id"]
    retailer_id = ctx["retailer"]["id"]

    resolved = validate_success(api.resolve_return(
        ctx["return"]["id"], {"resolution": "RECYCLE"}, PM
    ))
    assert resolved["status"] == "RESOLVED_RECYCLED"

    unit = get_success_data(api.get_unit(unit_id, PM))
    assert unit["status"] == "SCRAPPED"

    intakes, _meta = validate_paginated(
        api.list_recycling_intakes(PM, params={"unit_id": unit_id})
    )
    assert len(intakes) == 1
    intake = intakes[0]
    assert intake["unit_id"] == unit_id
    assert intake["retailer_id"] == retailer_id
    assert intake["declared_weight_kg"] == 2.0
    # 2.0 kg x 20 cents/kg = 40 cents, posted to the retailer ledger.
    assert intake["provisional_credit_cents"] == 40

    retailer = get_success_data(api.get_retailer(retailer_id, PM))
    assert retailer["credit_balance_cents"] == 40


def test_exchange_resolution_on_defect_return_rejected(api):
    """PRD §3.9: "`EXCHANGE` is valid only when the return's `reason` is
    `COMFORT_EXCHANGE` — an exchange resolution on a `DEFECT` return is
    rejected with `ERR_RESOLUTION_REASON_MISMATCH` (409)."
    PRD §3.9: "`REJECT` ships the unit back to the retailer — the unit moves
    `RETURNED` → `DELIVERED` — and the return closes as `REJECTED`."

    Design: Corner/validations/resolution_exchange_on_defect_return_rejected
    """
    ctx = setup_inspected_return(reason="DEFECT", measured_sag_inches=2.1)
    unit_id = ctx["units"][0]["id"]

    mismatch = api.resolve_return(ctx["return"]["id"], {"resolution": "EXCHANGE"}, PM)
    validate_error(mismatch, ApiErrorId.ERR_RESOLUTION_REASON_MISMATCH)

    rejected = validate_success(api.resolve_return(
        ctx["return"]["id"], {"resolution": "REJECT"}, PM
    ))
    assert rejected["status"] == "REJECTED"
    assert rejected["replacement_unit_id"] is None

    unit = get_success_data(api.get_unit(unit_id, PM))
    assert unit["status"] == "DELIVERED"
