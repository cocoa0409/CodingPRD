"""Optimistic concurrency control on the three guarded writes, and existence
precedence over body validation (PRD §2.8, §2.9, §2.10)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    make_dispatcher_headers,
    make_fleet_admin_headers,
    make_payroll_clerk_headers,
    setup_planned_trip,
    setup_settlement_after_invoice,
    validate_error,
    validate_success,
)

FLEET_ADMIN = make_fleet_admin_headers()
DISPATCHER = make_dispatcher_headers()
PAYROLL_1 = make_payroll_clerk_headers("payroll-1")

NON_EXISTENT_LOAD = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_stale_driver_patch_rejected(api):
    """PRD §2.8: "Updating a Driver's pay or home-terminal configuration
    requires the request to carry `expected_driver_version`, holding the Driver
    `version` the client last observed. If the driver's current `version` has
    moved past that value, the update is rejected with `ERR_STALE_VERSION`
    (HTTP 412), so a client never overwrites a pay configuration it has not
    seen."

    Design: Corner/validations/occ_stale_driver_patch_rejected
    """
    driver = create_driver(cdl_number="CDL-V3")
    assert driver["version"] == 1
    patched = validate_success(api_client.patch_driver(
        driver["id"], {"home_terminal": "FTW", "expected_driver_version": 1},
        FLEET_ADMIN))
    assert patched["version"] == 2
    resp = api_client.patch_driver(
        driver["id"], {"home_terminal": "HOU", "expected_driver_version": 1},
        FLEET_ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_existence_failure_precedes_body_validation(api):
    """PRD §2.10: "Existence failures therefore always precede body, state,
    concurrency, and business-rule failures on the same request, per the
    pipeline order in §2.9."
    (Unknown load id + invalid enum member in the body -> the 404 wins.)

    Design: Corner/validations/existence_beats_body_format
    """
    resp = api_client.create_load_accessorial(
        NON_EXISTENT_LOAD, {"type": "BOGUS", "quantity": 5}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_FOUND)


def test_trip_replan_recomputes_pay_and_guards_version(api):
    """PRD §3.3: "The replan is OCC-guarded by `expected_trip_version` as
    described in §2.8, re-runs the full safety-and-temporal screen — the safety
    floor, the four feasibility clauses, the home-time ceiling, and the overlap
    rule — against the revised inputs, recomputes `provisional_pay_cents`, and
    increments the trip's `version`."
    PRD §2.8: "Because cascaded touches also advance a trip's `version`, any
    intervening write — including one the client did not itself perform —
    causes the replan to be rejected with `ERR_STALE_VERSION` (HTTP 412)."
    ((900 + 200) * 62 = 68200 after replanning deadhead 120 -> 200.)

    Design: Corner/cross_cutting_complexity_layers/trip_patch_replan_occ_recompute
    """
    ctx = setup_planned_trip(cdl_number="CDL-X2", unit_number="T-X2")
    trip = ctx["trip"]
    assert trip["provisional_pay_cents"] == 63240
    assert trip["version"] == 1
    replanned = validate_success(api_client.patch_trip(
        trip["id"], {"planned_deadhead_miles": 200, "expected_trip_version": 1},
        DISPATCHER))
    assert replanned["version"] == 2
    assert replanned["provisional_pay_cents"] == 68200
    resp = api_client.patch_trip(
        trip["id"], {"planned_deadhead_miles": 300, "expected_trip_version": 1},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_settlement_recalculate_adjustment_and_stale_guard(api):
    """PRD §3.9: "While the settlement remains `DRAFT`, a `PayrollClerk` may
    recalculate it, recomputing every component from current data and replacing
    `manual_adjustment_cents` with a supplied value — which may be negative —
    that defaults to 0 when omitted."
    PRD §2.8: "Recalculating a `DRAFT` Settlement requires
    `expected_settlement_version`, holding the Settlement `version` the client
    last observed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),
    so a manual adjustment is never applied on top of an unobserved
    recalculation."
    (Adjustment 5000: subtotal 66600 + 5000 = 71600; top-up recomputes to
    120000 - 71600 = 48400; gross stays 120000.)

    Design: Corner/cross_cutting_complexity_layers/settlement_recalculate_occ_and_adjustment_absorbed
    """
    ctx = setup_settlement_after_invoice(cdl_number="CDL-X3", unit_number="T-X3")
    stl = ctx["settlement"]
    assert stl["guarantee_top_up_cents"] == 53400
    assert stl["version"] == 1
    sid = stl["id"]
    recalced = validate_success(api_client.recalculate_settlement(
        sid, {"manual_adjustment_cents": 5000, "expected_settlement_version": 1},
        PAYROLL_1))
    assert recalced["manual_adjustment_cents"] == 5000
    assert recalced["guarantee_top_up_cents"] == 48400
    assert recalced["gross_pay_cents"] == 120000
    assert recalced["version"] == 2
    resp = api_client.recalculate_settlement(
        sid, {"manual_adjustment_cents": 7000, "expected_settlement_version": 1},
        PAYROLL_1)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
