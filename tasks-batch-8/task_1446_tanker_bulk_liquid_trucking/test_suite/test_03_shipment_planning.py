"""Shipment creation, planning validation chain, and pipeline-ordering claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    close_meter,
    create_active_agreement,
    create_driver,
    create_product,
    create_rack,
    create_shipment_payload,
    create_trailer,
    create_wash_bay,
    create_wash_certificate_payload,
    make_customer_rep_headers,
    plan_shipment,
    plan_shipment_payload,
    setup_draft_shipment,
    setup_planned_shipment,
    setup_reconciled_shipment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
WASH_OP = TEST_USERS["wash_operator_headers"]


def test_shipment_created_in_draft(api):
    """PRD 3.3: "The new shipment is `DRAFT`: `trailer_id`, `driver_id`, `rack_id`,
    and `wash_cert_id` are null, no `rack_window_start` or `rack_window_end` is
    reserved, `weights_verified_at` and `reconciled_at` are null,
    `placards_confirmed` is false".

    Design: Corner/state_machines/shipment_created_in_draft
    """
    scenario = setup_draft_shipment()
    ship = scenario["ship"]
    assert ship["status"] == "DRAFT"
    assert ship["trailer_id"] is None
    assert ship["wash_cert_id"] is None
    assert ship["weights_verified_at"] is None


def test_double_cancel_rejected(api):
    """PRD 3.3: "Either source state attempted from elsewhere draws
    `ERR_SHIPMENT_INVALID_STATE`." (cancel is defined only from DRAFT or PLANNED,
    so an already-CANCELLED shipment rejects a second cancel).

    Design: Corner/state_machines/double_cancel_rejected
    """
    scenario = setup_draft_shipment()
    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    res = api.cancel_shipment(scenario["ship"]["id"], DISP)
    validate_error(res, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)


def test_cancel_reconciled_shipment_rejected(api):
    """PRD 3.3: "Either source state attempted from elsewhere draws
    `ERR_SHIPMENT_INVALID_STATE`." (RECONCILED is neither DRAFT nor PLANNED, so
    cancel is rejected and the shipment remains RECONCILED.)

    Design: Corner/state_machines/cancel_reconciled_shipment_rejected
    """
    scenario = setup_reconciled_shipment(route_miles=500)
    res = api.cancel_shipment(scenario["ship"]["id"], DISP)
    validate_error(res, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)

    after = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert after["status"] == "RECONCILED"
    # 1000 gal * 100c = 100000; + 4% surcharge 4000; + rack fee 15000; no shortage.
    assert after["final_total_cents"] == 119000


def test_suspended_customer_cannot_order(api):
    """PRD 3.3: "The referenced customer must be `ACTIVE` or creation fails with
    `ERR_CUSTOMER_NOT_ACTIVE`."

    Design: Corner/errors/suspended_customer_cannot_order
    """
    scenario = setup_draft_shipment()
    validate_success(api.suspend_customer(scenario["cust"]["id"], ADMIN), 200)
    res = api.create_shipment(
        create_shipment_payload(scenario["cust"]["id"], scenario["prod"]["id"]), DISP)
    validate_error(res, "ERR_CUSTOMER_NOT_ACTIVE", expected_status=409)


def test_inactive_driver_cannot_be_planned(api):
    """PRD 3.3: "The driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`)".

    Design: Corner/errors/inactive_driver_cannot_be_planned
    """
    scenario = setup_draft_shipment()
    validate_success(api.deactivate_driver(scenario["drv"]["id"], ADMIN), 200)
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_DRIVER_NOT_ACTIVE", expected_status=409)


def test_capacity_exceeded_rejected(api):
    """PRD 3.3: "the `ordered_gallons` must not exceed the trailer's
    `capacity_gallons` (`ERR_CAPACITY_EXCEEDED`)".

    Design: Corner/validations/capacity_exceeded_rejected
    """
    scenario = setup_draft_shipment(ordered_gallons=9000)  # capacity 8000
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=422)


def test_trailer_unavailable_rejected(api):
    """PRD 3.3: "The trailer must be `AVAILABLE` (`ERR_TRAILER_NOT_AVAILABLE`)".

    Design: Corner/errors/trailer_unavailable_rejected
    """
    scenario = setup_draft_shipment()
    plan_shipment(scenario)  # trailer now ASSIGNED to the first shipment
    second = validate_success(
        api.create_shipment(
            create_shipment_payload(scenario["cust"]["id"], scenario["prod"]["id"]), DISP), 201)
    res = api.plan_shipment(second["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        rack_window_start="2026-08-03T10:00:00Z", rack_window_end="2026-08-03T12:00:00Z"), DISP)
    validate_error(res, "ERR_TRAILER_NOT_AVAILABLE", expected_status=409)


def test_dedication_mismatch_rejected(api):
    """PRD 3.3: "if the trailer's `dedicated_customer_id` is set to a customer other
    than the shipment's, the plan is rejected with `ERR_TRAILER_DEDICATION_MISMATCH`".

    Design: Corner/validations/dedication_mismatch_rejected
    """
    dedicated = create_active_agreement()
    other_cust = validate_success(
        api.create_customer({"name": "Other Co", "credit_limit_cents": 1000000000}, ADMIN), 201)
    prod = create_product()
    drv = create_driver()
    rack = create_rack()
    ship = validate_success(
        api.create_shipment(create_shipment_payload(other_cust["id"], prod["id"]), DISP), 201)
    res = api.plan_shipment(ship["id"], plan_shipment_payload(
        dedicated["trl"]["id"], drv["id"], rack["id"]), DISP)
    validate_error(res, "ERR_TRAILER_DEDICATION_MISMATCH", expected_status=422)


def test_credit_limit_exceeded_solo(api):
    """PRD 3.3: "The customer's current `exposure_cents` plus a plan-time estimate for
    the new shipment must not exceed the customer's `credit_limit_cents`, with equality
    allowed; a breach is `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

    Design: Corner/validations/credit_limit_exceeded_solo
    """
    scenario = setup_draft_shipment(ordered_gallons=100, credit_limit_cents=1000)
    # estimate = 100*100 + 400 + 15000 = 25400 > 1000
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)


def test_rack_window_outside_hours_rejected(api):
    """PRD 3.3: "The reserved window must lie within the rack's operating hours on a
    single UTC calendar day — beginning no earlier than `open_hour` and ending no later
    than `close_hour` — or the plan is rejected with
    `ERR_WINDOW_OUTSIDE_OPERATING_HOURS`." (Rack runs 6-22; 21:00-23:00 ends past close.)

    Design: Corner/validations/rack_window_outside_hours_rejected
    """
    scenario = setup_draft_shipment()
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        rack_window_start="2026-08-02T21:00:00Z", rack_window_end="2026-08-02T23:00:00Z"), DISP)
    validate_error(res, "ERR_WINDOW_OUTSIDE_OPERATING_HOURS", expected_status=422)


def test_rack_not_authorized_for_product(api):
    """PRD 3.3: "The referential gate then requires the product's
    `compatibility_group` to appear in the rack's `authorized_groups`, else
    `ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT`."

    Design: Corner/validations/rack_not_authorized_for_product
    """
    scenario = setup_draft_shipment(
        product_overrides={
            "name": "Hydrochloric Acid", "compatibility_group": "ACID",
            "hazmat_class": "CLASS_8_CORROSIVE", "density_lb_per_gal": 9.5,
            "temp_coeff_per_degF": 0.0003, "placard_code": "UN1789",
        })
    # rack authorizes only PETROLEUM; trailer has no prior load, so no wash rule applies
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT", expected_status=422)


def test_existence_beats_state_on_plan(api):
    """PRD 2.8: "a failure at any step short-circuits all later steps, so the error a
    caller receives always comes from the earliest failing category", with existence at
    step 3 ("path identifiers are validated left-to-right, then identifiers referenced
    in the request body") and state gates at step 6.

    Design: Corner/validations/existence_beats_state_on_plan
    """
    scenario = setup_draft_shipment()
    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        NON_EXISTENT_UUID, scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_TRAILER_NOT_FOUND", expected_status=404)


def test_state_beats_safety_on_plan_cancelled(api):
    """PRD 2.8: "a failure at any step short-circuits all later steps, so the error a
    caller receives always comes from the earliest failing category", with state gates
    at step 6 and business safety (driver endorsements) at step 7.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_plan_cancelled
    """
    scenario = setup_draft_shipment(
        driver_overrides={"full_name": "No Hazmat", "cdl_number": "CDL-2",
                          "hazmat_endorsement": False})
    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)


def test_plan_cancelled_shipment_with_clean_driver_also_rejected(api):
    """PRD 3.3: "The shipment must currently be `DRAFT` (`ERR_SHIPMENT_INVALID_STATE`
    otherwise)" — the state gate rejects planning a CANCELLED shipment even when no
    other violation exists.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_plan_cancelled
    """
    scenario = setup_draft_shipment()
    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)


def test_safety_beats_fiscal_on_plan(api):
    """PRD 2.8 step 11: "Because this gate runs last, a plan request that would fail
    both a safety check and the credit check is always rejected for the safety
    failure." (Driver lacks the hazmat endorsement required for a CLASS_3 product;
    credit limit of 1 cent would also be exceeded.)

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_plan
    """
    scenario = setup_draft_shipment(
        ordered_gallons=100,
        credit_limit_cents=1,
        driver_overrides={"full_name": "No Hazmat", "cdl_number": "CDL-2",
                          "hazmat_endorsement": False})
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_DRIVER_ENDORSEMENT_MISSING", expected_status=422)


def test_missing_hazmat_endorsement_rejected_within_credit_limit(api):
    """PRD 3.3: "must hold the hazmat endorsement whenever the product's
    `hazmat_class` is anything other than `NONE` — a missing endorsement is
    `ERR_DRIVER_ENDORSEMENT_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_plan
    """
    scenario = setup_draft_shipment(
        driver_overrides={"full_name": "No Hazmat", "cdl_number": "CDL-2",
                          "hazmat_endorsement": False})
    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP)
    validate_error(res, "ERR_DRIVER_ENDORSEMENT_MISSING", expected_status=422)


def test_rack_windows_half_open_adjacency(api):
    """PRD 3.3: "The window must also not overlap any other shipment on the same rack
    in `PLANNED`, `LOADING`, or `LOADED` status, using half-open interval semantics
    with zero buffer". (A [12:00,14:00) window after a PLANNED [10:00,12:00) does not
    overlap under half-open semantics and is accepted.)

    Design: Difficulty/resource_temporal_overlap/rack_windows_half_open_adjacency
    """
    scenario = setup_draft_shipment()
    plan_shipment(scenario)  # s1 PLANNED on rack R-1 with [10:00, 12:00)
    trl2 = create_trailer(unit_number="T-102")
    s2 = validate_success(api.create_shipment(
        create_shipment_payload(scenario["cust"]["id"], scenario["prod"]["id"]), DISP), 201)

    planned = validate_success(api.plan_shipment(s2["id"], plan_shipment_payload(
        trl2["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        rack_window_start="2026-08-02T12:00:00Z", rack_window_end="2026-08-02T14:00:00Z"),
        DISP), 200)
    assert planned["status"] == "PLANNED"


def test_rack_windows_straddling_rejected(api):
    """PRD 3.3: "The window must also not overlap any other shipment on the same rack
    in `PLANNED`, `LOADING`, or `LOADED` status, using half-open interval semantics
    with zero buffer: an overlap is `ERR_RACK_WINDOW_CONFLICT` (409)." ([11:30,13:00)
    straddles the PLANNED [10:00,12:00).)

    Design: Difficulty/resource_temporal_overlap/rack_windows_half_open_adjacency
    """
    scenario = setup_draft_shipment()
    plan_shipment(scenario)  # s1 PLANNED on rack R-1 with [10:00, 12:00)
    trl3 = create_trailer(unit_number="T-103")
    s3 = validate_success(api.create_shipment(
        create_shipment_payload(scenario["cust"]["id"], scenario["prod"]["id"]), DISP), 201)

    res = api.plan_shipment(s3["id"], plan_shipment_payload(
        trl3["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        rack_window_start="2026-08-02T11:30:00Z", rack_window_end="2026-08-02T13:00:00Z"), DISP)
    validate_error(res, "ERR_RACK_WINDOW_CONFLICT", expected_status=409)


def test_endorsement_expiry_boundary(api):
    """PRD 3.1: "an `endorsement_expires_on` date in ISO `YYYY-MM-DD` form —
    endorsements remain valid through that date inclusive, and a date before the
    current logical date means expired." At the startup clock 2026-08-01, a driver
    expiring 2026-07-01 is expired (ERR_DRIVER_ENDORSEMENT_EXPIRED) while one expiring
    2026-08-01 plans successfully.

    Design: Corner/validations/endorsement_expiry_boundary
    """
    cust = validate_success(
        api.create_customer({"name": "Acme Chem", "credit_limit_cents": 1000000000}, ADMIN), 201)
    prod = create_product()
    trl = create_trailer()
    drv_old = create_driver(cdl_number="CDL-9", full_name="Old Endorsement",
                            endorsement_expires_on="2026-07-01")
    drv_today = create_driver(cdl_number="CDL-10", full_name="Expires Today",
                              endorsement_expires_on="2026-08-01")
    rack = create_rack()
    s1 = validate_success(
        api.create_shipment(create_shipment_payload(cust["id"], prod["id"]), DISP), 201)
    s2 = validate_success(
        api.create_shipment(create_shipment_payload(cust["id"], prod["id"]), DISP), 201)

    # startup clock is exactly 2026-08-01 (PRD 2.5); no clock set needed.
    res = api.plan_shipment(s1["id"], plan_shipment_payload(
        trl["id"], drv_old["id"], rack["id"]), DISP)
    validate_error(res, "ERR_DRIVER_ENDORSEMENT_EXPIRED", expected_status=422)

    ok = validate_success(api.plan_shipment(s2["id"], plan_shipment_payload(
        trl["id"], drv_today["id"], rack["id"]), DISP), 200)
    assert ok["status"] == "PLANNED"
