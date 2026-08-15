"""Tank wash certificate lifecycle, wash-bay buffering, and prior-load rules."""
import pytest

from test_helpers import (
    SO_1,
    TEST_USERS,
    check_in,
    close_delivery,
    close_meter,
    confirm_placards,
    create_certified_cert,
    create_driver,
    create_product,
    create_rack,
    create_rule,
    create_shipment_payload,
    create_spill_plan_payload,
    create_trailer,
    create_wash_bay,
    create_wash_certificate_payload,
    make_customer_rep_headers,
    make_driver_headers,
    make_safety_officer_headers,
    plan_shipment,
    plan_shipment_payload,
    record_weights,
    set_clock,
    setup_draft_shipment,
    start_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
WASH_OP = TEST_USERS["wash_operator_headers"]


def test_certify_twice_rejected(api):
    """PRD 3.2: "certifying a `SCHEDULED` certificate (any other state draws
    `ERR_CERT_INVALID_STATE`) moves it to `CERTIFIED`".

    Design: Corner/state_machines/certify_twice_rejected
    """
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])
    res = api.certify_wash_certificate(cert["id"], WASH_OP)
    validate_error(res, "ERR_CERT_INVALID_STATE", expected_status=409)


def test_plan_requires_certified_wash_cert(api):
    """PRD 3.3: "When the requirement is `NONE`, attaching a certificate is optional —
    but an attached certificate must still be `CERTIFIED` (else
    `ERR_CERT_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/plan_requires_certified_wash_cert
    """
    scenario = setup_draft_shipment()
    bay = create_wash_bay(supported_wash_levels=["FLUSH"])
    cert = validate_success(api.create_wash_certificate(
        create_wash_certificate_payload(scenario["trl"]["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T06:00:00Z",
                                        window_end="2026-08-02T07:00:00Z"),
        WASH_OP), 201)  # SCHEDULED, never certified

    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        wash_cert_id=cert["id"]), DISP)
    validate_error(res, "ERR_CERT_INVALID_STATE", expected_status=409)

    ship = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert ship["status"] == "DRAFT"


def test_plan_with_certified_cert_holds_it(api):
    """PRD 3.3: "A successful plan has three side effects beyond the state change: the
    trailer transitions `AVAILABLE → ASSIGNED`, the attached certificate (if any)
    transitions `CERTIFIED → HELD`, and the customer's `exposure_cents` is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/plan_requires_certified_wash_cert
    """
    set_clock("2026-08-01T08:00:00Z")
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])

    planned = plan_shipment(scenario, set_the_clock=False, wash_cert_id=cert["id"])
    assert planned["status"] == "PLANNED"

    cert_after = validate_success(api.get_wash_certificate(cert["id"], DISP), 200)
    assert cert_after["status"] == "HELD"


def test_cert_expired_rejected(api):
    """PRD 3.2: "attempting to attach an expired certificate at plan time fails
    instead with `ERR_WASH_CERT_EXPIRED` and leaves the certificate untouched."
    (FLUSH validity 48h per PRD 3.2; certified at 2026-08-01T08:00 expires
    2026-08-03T08:00; planning at 2026-08-03T09:00 attaches an expired cert.)

    Design: Corner/validations/cert_expired_rejected
    """
    set_clock("2026-08-01T08:00:00Z")
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(
        scenario["trl"]["id"], wash_level="FLUSH",
        window_start="2026-08-01T06:00:00Z", window_end="2026-08-01T07:00:00Z")
    set_clock("2026-08-03T09:00:00Z")

    res = api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"],
        rack_window_start="2026-08-04T10:00:00Z", rack_window_end="2026-08-04T12:00:00Z",
        wash_cert_id=cert["id"]), DISP)
    validate_error(res, "ERR_WASH_CERT_EXPIRED", expected_status=422)


def test_lazy_cert_expiry_on_read(api):
    """PRD 2.5: "A TankWashCertificate whose `expires_at` lies in the past transitions
    `CERTIFIED → EXPIRED` the next time it is read". (FLUSH certified at
    2026-08-01T08:00 expires at 2026-08-03T08:00.)

    Design: Corner/complexity_layers/lazy_cert_expiry_on_read
    """
    set_clock("2026-08-01T08:00:00Z")
    trl = create_trailer()
    cert, _bay = create_certified_cert(trl["id"], wash_level="FLUSH")

    before = validate_success(api.get_wash_certificate(cert["id"], WASH_OP), 200)
    assert before["status"] == "CERTIFIED"

    set_clock("2026-08-03T08:00:01Z")
    after = validate_success(api.get_wash_certificate(cert["id"], WASH_OP), 200)
    assert after["status"] == "EXPIRED"


def test_wash_bay_buffer_gap_required(api):
    """PRD 3.2: "a new booking is rejected with `ERR_WASH_BAY_WINDOW_CONFLICT` (409)
    whenever another booking on the same bay in `SCHEDULED` or `CERTIFIED` status
    satisfies both of these conditions — the new window starts before the existing
    window's end plus the bay's `cleanup_buffer_minutes`, and the existing window
    starts before the new window's end plus that same buffer." (Existing 09:00-10:00
    with a 30-minute buffer: a 10:00 start collides with the buffer; 10:30 fits.)

    Design: Difficulty/resource_temporal_overlap/wash_bay_buffer_gap_required
    """
    trl1 = create_trailer(unit_number="T-101")
    trl2 = create_trailer(unit_number="T-102")
    trl3 = create_trailer(unit_number="T-103")
    bay = create_wash_bay(supported_wash_levels=["FLUSH"], cleanup_buffer_minutes=30)
    first = validate_success(api.create_wash_certificate(
        create_wash_certificate_payload(trl1["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T09:00:00Z",
                                        window_end="2026-08-02T10:00:00Z"),
        WASH_OP), 201)
    assert first["status"] == "SCHEDULED"

    res = api.create_wash_certificate(
        create_wash_certificate_payload(trl2["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T10:00:00Z",
                                        window_end="2026-08-02T11:00:00Z"),
        WASH_OP)
    validate_error(res, "ERR_WASH_BAY_WINDOW_CONFLICT", expected_status=409)

    third = validate_success(api.create_wash_certificate(
        create_wash_certificate_payload(trl3["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T10:30:00Z",
                                        window_end="2026-08-02T11:30:00Z"),
        WASH_OP), 201)
    assert third["status"] == "SCHEDULED"


def test_wash_bay_straddling_booking_rejected(api):
    """PRD 3.2: "a new booking is rejected with `ERR_WASH_BAY_WINDOW_CONFLICT` (409)
    whenever another booking on the same bay in `SCHEDULED` or `CERTIFIED` status
    satisfies both of these conditions — the new window starts before the existing
    window's end plus the bay's `cleanup_buffer_minutes`, and the existing window
    starts before the new window's end plus that same buffer." (09:30-10:30 straddles
    the 09:00-10:00 booking outright.)

    Design: Difficulty/resource_temporal_overlap/wash_bay_buffer_gap_required
    """
    trl1 = create_trailer(unit_number="T-101")
    trl2 = create_trailer(unit_number="T-102")
    bay = create_wash_bay(supported_wash_levels=["FLUSH"], cleanup_buffer_minutes=30)
    validate_success(api.create_wash_certificate(
        create_wash_certificate_payload(trl1["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T09:00:00Z",
                                        window_end="2026-08-02T10:00:00Z"),
        WASH_OP), 201)

    res = api.create_wash_certificate(
        create_wash_certificate_payload(trl2["id"], bay["id"], wash_level="FLUSH",
                                        window_start="2026-08-02T09:30:00Z",
                                        window_end="2026-08-02T10:30:00Z"),
        WASH_OP)
    validate_error(res, "ERR_WASH_BAY_WINDOW_CONFLICT", expected_status=409)


def test_cert_hold_release_round_trip(api):
    """PRD 2.9: "Unwinding operations are symmetrical compensating releases:
    unplanning or cancelling a planned shipment returns the trailer to `AVAILABLE`,
    returns the held certificate to `CERTIFIED` unchanged, clears the assignment
    fields, and recomputes exposure."

    Design: Difficulty/compensating_invariant/cert_hold_release_round_trip
    """
    set_clock("2026-08-01T08:00:00Z")
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])

    planned = plan_shipment(scenario, set_the_clock=False, wash_cert_id=cert["id"])
    assert planned["status"] == "PLANNED"
    mid = validate_success(api.get_wash_certificate(cert["id"], DISP), 200)
    assert mid["status"] == "HELD"

    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    end = validate_success(api.get_wash_certificate(cert["id"], DISP), 200)
    assert end["status"] == "CERTIFIED"
    assert end["consumed_by_shipment_id"] is None

    held, meta = validate_paginated(api.list_wash_certificates(DISP, params={"status": "HELD"}))
    assert meta["total_count"] == 0


def test_unplan_releases_cert_and_trailer(api):
    """PRD 3.3: "Unplanning a `PLANNED` shipment (any other state draws
    `ERR_SHIPMENT_INVALID_STATE`) returns it to `DRAFT`, releases the trailer
    `ASSIGNED → AVAILABLE`, returns the held certificate `HELD → CERTIFIED`, clears
    the assignment fields, and recomputes exposure."

    Design: Difficulty/compensating_invariant/cert_hold_release_round_trip
    """
    set_clock("2026-08-01T08:00:00Z")
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])
    plan_shipment(scenario, set_the_clock=False, wash_cert_id=cert["id"])

    unplanned = validate_success(api.unplan_shipment(scenario["ship"]["id"], DISP), 200)
    assert unplanned["status"] == "DRAFT"
    assert unplanned["trailer_id"] is None
    assert unplanned["wash_cert_id"] is None

    cert_after = validate_success(api.get_wash_certificate(cert["id"], DISP), 200)
    assert cert_after["status"] == "CERTIFIED"
    trailer_after = validate_success(api.get_trailer(scenario["trl"]["id"], DISP), 200)
    assert trailer_after["status"] == "AVAILABLE"


def test_cert_revoke_cascades_shipment_and_trailer(api):
    """PRD 3.2: "Revoking a `HELD` one cascades in two hops: first, the shipment
    holding it — the `PLANNED` shipment whose `wash_cert_id` references this
    certificate — reverts `PLANNED → DRAFT` with `wash_cert_id`, `trailer_id`,
    `driver_id`, `rack_id`, `rack_window_start`, and `rack_window_end` all cleared;
    second, because that revert releases the trailer, the trailer transitions
    `ASSIGNED → AVAILABLE`."

    Design: Difficulty/transitive_cascade/cert_revoke_cascades_shipment_and_trailer
    """
    set_clock("2026-08-01T08:00:00Z")
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])
    plan_shipment(scenario, set_the_clock=False, wash_cert_id=cert["id"])

    revoked = validate_success(
        api.revoke_wash_certificate(cert["id"], make_safety_officer_headers(SO_1)), 200)
    assert revoked["status"] == "VOIDED"  # hop 1

    ship = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert ship["status"] == "DRAFT"  # hop 2
    assert ship["wash_cert_id"] is None
    assert ship["trailer_id"] is None

    trailer = validate_success(api.get_trailer(scenario["trl"]["id"], ADMIN), 200)
    assert trailer["status"] == "AVAILABLE"  # hop 3


def test_revoke_certified_cert_without_holding_shipment(api):
    """PRD 3.2: "Revoking a `CERTIFIED` certificate simply removes it from the pool."
    (No holding shipment, so no cascade; the trailer stays AVAILABLE.)

    Design: Difficulty/transitive_cascade/cert_revoke_cascades_shipment_and_trailer
    """
    scenario = setup_draft_shipment()
    cert, _bay = create_certified_cert(scenario["trl"]["id"])

    revoked = validate_success(
        api.revoke_wash_certificate(cert["id"], make_safety_officer_headers(SO_1)), 200)
    assert revoked["status"] == "VOIDED"

    trailer = validate_success(api.get_trailer(scenario["trl"]["id"], ADMIN), 200)
    assert trailer["status"] == "AVAILABLE"


def _run_petroleum_load_on_trailer(api):
    """Full lifecycle of one PETROLEUM load on a shared trailer; returns the scenario
    dict (shipment DELIVERED, trailer AVAILABLE with last_product_group PETROLEUM)."""
    scenario = setup_draft_shipment()
    scenario["rack"] = create_rack(rack_code="R-MULTI",
                                   authorized_groups=["PETROLEUM", "CAUSTIC", "ACID",
                                                      "VEG_OIL", "FOOD_GRADE"])
    # re-plan onto the multi-group rack (setup's default rack is PETROLEUM-only)
    set_clock("2026-08-02T10:30:00Z")
    validate_success(api.plan_shipment(scenario["ship"]["id"], plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"]), DISP), 200)
    check_in(scenario)
    close_meter(scenario, meter_end_gal=1000, observed_temp_F=60)
    record_weights(scenario)
    confirm_placards(scenario)
    rep = make_customer_rep_headers(scenario["cust"]["id"])
    plan = validate_success(api.create_spill_plan(
        create_spill_plan_payload(scenario["cust"]["id"], scenario["prod"]["id"]), rep), 201)
    validate_success(api.submit_spill_plan(plan["id"], rep), 200)
    validate_success(api.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1)), 200)
    validate_success(api.depart_shipment(scenario["ship"]["id"], DISP), 200)
    start_delivery(scenario)
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)
    return scenario


def test_wash_rank_hierarchy_satisfied(api):
    """PRD 3.3: "Wash levels are totally ordered by rank: `NONE` ranks 0, `FLUSH` 1,
    `DETERGENT_WASH` 2, and `CHEMICAL_KOSHER` 3" and "its wash level ranks at least as
    high as the requirement (else `ERR_WASH_LEVEL_INSUFFICIENT`)". (Rule
    PETROLEUM->CAUSTIC requires FLUSH; a DETERGENT_WASH certificate satisfies it.)

    Design: Corner/calculations/wash_rank_hierarchy_satisfied
    """
    base = _run_petroleum_load_on_trailer(api)
    caustic = create_product(
        name="Caustic Soda", compatibility_group="CAUSTIC", hazmat_class="CLASS_8_CORROSIVE",
        density_lb_per_gal=9.0, temp_coeff_per_degF=0.0004, placard_code="UN1824")
    create_rule(prior_group="PETROLEUM", next_group="CAUSTIC", required_wash_level="FLUSH")
    cert, _bay = create_certified_cert(base["trl"]["id"], wash_level="DETERGENT_WASH",
                                       window_start="2026-08-02T14:00:00Z",
                                       window_end="2026-08-02T15:00:00Z")
    s2 = validate_success(api.create_shipment(
        create_shipment_payload(base["cust"]["id"], caustic["id"]), DISP), 201)

    planned = validate_success(api.plan_shipment(s2["id"], plan_shipment_payload(
        base["trl"]["id"], base["drv"]["id"], base["rack"]["id"],
        rack_window_start="2026-08-03T10:00:00Z", rack_window_end="2026-08-03T12:00:00Z",
        wash_cert_id=cert["id"]), DISP), 200)
    assert planned["status"] == "PLANNED"

    cert_after = validate_success(api.get_wash_certificate(cert["id"], DISP), 200)
    assert cert_after["status"] == "HELD"


def test_wash_failure_modes(api):
    """PRD 3.3: "if no such rule exists the plan fails with
    `ERR_COMPATIBILITY_RULE_MISSING`, and if the rule is marked `forbidden` it fails
    with `ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN`" and "its wash level ranks at least
    as high as the requirement (else `ERR_WASH_LEVEL_INSUFFICIENT`)". (After a
    PETROLEUM load: ACID rule requires DETERGENT_WASH but only a FLUSH cert is
    attached; VEG_OIL has no rule; FOOD_GRADE is forbidden.)

    Design: Corner/validations/wash_failure_modes
    """
    base = _run_petroleum_load_on_trailer(api)
    acid = create_product(
        name="Hydrochloric Acid", compatibility_group="ACID", hazmat_class="CLASS_8_CORROSIVE",
        density_lb_per_gal=9.5, temp_coeff_per_degF=0.0003, placard_code="UN1789")
    veg = create_product(
        name="Soybean Oil", compatibility_group="VEG_OIL", hazmat_class="NONE",
        packing_group="NONE", density_lb_per_gal=7.7, temp_coeff_per_degF=0.0004,
        placard_code="NONE")
    food = create_product(
        name="Glucose Syrup", compatibility_group="FOOD_GRADE", hazmat_class="NONE",
        packing_group="NONE", density_lb_per_gal=11.0, temp_coeff_per_degF=0.0003,
        placard_code="NONE")
    create_rule(prior_group="PETROLEUM", next_group="ACID", required_wash_level="DETERGENT_WASH")
    create_rule(prior_group="PETROLEUM", next_group="FOOD_GRADE",
                required_wash_level="CHEMICAL_KOSHER", forbidden=True)
    cert, _bay = create_certified_cert(base["trl"]["id"], wash_level="FLUSH",
                                       window_start="2026-08-02T14:00:00Z",
                                       window_end="2026-08-02T15:00:00Z")
    s_acid = validate_success(api.create_shipment(
        create_shipment_payload(base["cust"]["id"], acid["id"]), DISP), 201)
    s_veg = validate_success(api.create_shipment(
        create_shipment_payload(base["cust"]["id"], veg["id"]), DISP), 201)
    s_food = validate_success(api.create_shipment(
        create_shipment_payload(base["cust"]["id"], food["id"]), DISP), 201)

    window = {"rack_window_start": "2026-08-03T10:00:00Z",
              "rack_window_end": "2026-08-03T12:00:00Z"}
    res1 = api.plan_shipment(s_acid["id"], plan_shipment_payload(
        base["trl"]["id"], base["drv"]["id"], base["rack"]["id"],
        wash_cert_id=cert["id"], **window), DISP)
    validate_error(res1, "ERR_WASH_LEVEL_INSUFFICIENT", expected_status=422)

    res2 = api.plan_shipment(s_veg["id"], plan_shipment_payload(
        base["trl"]["id"], base["drv"]["id"], base["rack"]["id"], **window), DISP)
    validate_error(res2, "ERR_COMPATIBILITY_RULE_MISSING", expected_status=422)

    res3 = api.plan_shipment(s_food["id"], plan_shipment_payload(
        base["trl"]["id"], base["drv"]["id"], base["rack"]["id"], **window), DISP)
    validate_error(res3, "ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN", expected_status=422)
