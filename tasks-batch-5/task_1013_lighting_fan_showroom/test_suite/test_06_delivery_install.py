"""Delivery + install lifecycle: cascade, delivery-readiness guard, installer overlap (PRD §2.7, §2.10, §3.7)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_installer, create_truck, create_delivery_job, deliver_job,
    create_referral, schedule_referral, setup_confirmed_retail_order,
    create_fixture, create_order, add_line, quote, confirm,
)

SM = TEST_USERS["sm_headers"]


# --------------------------- transitive cascade: order cancel -> void -> withdraw --------
def _cascade_setup(api):
    inst = create_installer(api, name="Ivan", service_area="NORTH")
    truck = create_truck(api, name="T1")
    order, line, fx = setup_confirmed_retail_order(api, base_price_cents=8000)
    dj = create_delivery_job(api, order["id"], truck["id"], "2026-07-10T10:00:00Z", "2026-07-10T12:00:00Z")
    ref = create_referral(api, order["id"], inst["id"], dj["id"])
    return order, inst, dj, ref


def test_order_cancel_voids_scheduled_delivery_job(api):
    """PRD §2.7: "the cancellation additionally releases the order's committed trade credit
    back to the account, transitions every non-terminal `SpecialOrder` belonging to that
    order to `CANCELLED`, and voids every `SCHEDULED` `DeliveryJob` belonging to that order
    by moving it to `VOIDED`."

    Design: Difficulty/transitive_cascade/order_cancel_voids_delivery_withdraws_install_frees_installer
    """
    order, inst, dj, ref = _cascade_setup(api)
    cancelled = validate_success(api.cancel_order(order["id"], SM), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    job = validate_success(api.get_delivery_job(dj["id"], SM), 200)
    assert job["status"] == "VOIDED"


def test_order_cancel_withdraws_referral_and_frees_installer(api):
    """PRD §2.7: "Voiding a delivery job in turn withdraws every install referral tied to
    that job that is still in `REFERRED` or `SCHEDULED`, moving each to `WITHDRAWN` and
    decrementing the relevant installer's active-referral tally."

    Design: Difficulty/transitive_cascade/order_cancel_voids_delivery_withdraws_install_frees_installer
    """
    order, inst, dj, ref = _cascade_setup(api)
    api.cancel_order(order["id"], SM)
    referral = validate_success(api.get_install_referral(ref["id"], SM), 200)
    assert referral["status"] == "WITHDRAWN"
    installer = validate_success(api.get_installer(inst["id"], SM), 200)
    assert installer["active_referral_count"] == 0


# --------------------------- cross-entity: schedule requires delivered job ---------------
def _referral_undelivered(api, sku="F-7B"):
    inst = create_installer(api, name="I7", service_area="S")
    truck = create_truck(api, name="T7")
    order, line, fx = setup_confirmed_retail_order(api, base_price_cents=5000)
    dj = create_delivery_job(api, order["id"], truck["id"], "2026-07-11T08:00:00Z", "2026-07-11T09:00:00Z")
    ref = create_referral(api, order["id"], inst["id"], dj["id"])
    return ref


def test_install_schedule_requires_delivered_job(api):
    """PRD §3.7: "Scheduling a referral requires it to be `REFERRED`, requires the linked
    delivery job identified by `delivery_job_id` to have reached `DELIVERED` (otherwise
    `ERR_DELIVERY_NOT_READY`), and requires the proposed appointment window not to overlap
    any other `SCHEDULED` referral for the same installer (otherwise `ERR_INSTALLER_UNAVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/install_schedule_requires_delivery_delivered
    """
    ref = _referral_undelivered(api)
    resp = api.schedule_install_referral(
        ref["id"], {"appointment_start": "2026-07-11T10:00:00Z", "appointment_end": "2026-07-11T11:00:00Z"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_READY.value)


def test_install_schedule_rejected_leaves_referral_referred(api):
    """PRD §3.7: "Scheduling a referral requires it to be `REFERRED`, requires the linked
    delivery job identified by `delivery_job_id` to have reached `DELIVERED` (otherwise
    `ERR_DELIVERY_NOT_READY`), and requires the proposed appointment window not to overlap
    any other `SCHEDULED` referral for the same installer (otherwise `ERR_INSTALLER_UNAVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/install_schedule_requires_delivery_delivered
    """
    ref = _referral_undelivered(api, sku="F-7C")
    api.schedule_install_referral(
        ref["id"], {"appointment_start": "2026-07-11T10:00:00Z", "appointment_end": "2026-07-11T11:00:00Z"}, SM
    )
    data = validate_success(api.get_install_referral(ref["id"], SM), 200)
    assert data["status"] == "REFERRED"


# --------------------------- resource temporal overlap: half-open windows ----------------
def _three_delivered_referrals(api):
    inst = create_installer(api, name="I8", service_area="S", daily_capacity=10)
    order, line, fx = setup_confirmed_retail_order(api, base_price_cents=5000)
    refs = []
    for i, tname in enumerate(("T8a", "T8b", "T8c")):
        truck = create_truck(api, name=tname)
        dj = create_delivery_job(api, order["id"], truck["id"],
                                 "2026-07-12T06:00:00Z", "2026-07-12T07:00:00Z")
        deliver_job(api, dj["id"])
        refs.append(create_referral(api, order["id"], inst["id"], dj["id"]))
    # R1 scheduled [10:00,12:00)
    schedule_referral(api, refs[0]["id"], "2026-07-12T10:00:00Z", "2026-07-12T12:00:00Z")
    return refs


def test_installer_overlapping_appointment_rejected(api):
    """PRD §2.10: "Install appointment windows are half-open intervals `[appointment_start,
    appointment_end)`: two appointments for the same installer may not overlap, though exact
    adjacency where one ends at the instant the next begins is permitted; a scheduling attempt
    that overlaps an existing `SCHEDULED` referral for the same installer is rejected with
    `ERR_INSTALLER_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/installer_appointment_half_open_overlap
    """
    refs = _three_delivered_referrals(api)
    resp = api.schedule_install_referral(
        refs[1]["id"], {"appointment_start": "2026-07-12T11:00:00Z", "appointment_end": "2026-07-12T13:00:00Z"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_INSTALLER_UNAVAILABLE.value)


def test_installer_adjacent_appointment_accepted(api):
    """PRD §2.10: "Install appointment windows are half-open intervals `[appointment_start,
    appointment_end)`: two appointments for the same installer may not overlap, though exact
    adjacency where one ends at the instant the next begins is permitted; a scheduling attempt
    that overlaps an existing `SCHEDULED` referral for the same installer is rejected with
    `ERR_INSTALLER_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/installer_appointment_half_open_overlap
    """
    refs = _three_delivered_referrals(api)
    # R3 [12:00,14:00): start equals R1's end -> adjacency allowed.
    data = validate_success(api.schedule_install_referral(
        refs[2]["id"], {"appointment_start": "2026-07-12T12:00:00Z", "appointment_end": "2026-07-12T14:00:00Z"}, SM
    ), 200)
    assert data["status"] == "SCHEDULED"


# --------------------------- priority pair: referential beats temporal -------------------
def _referential_vs_temporal_setup(api):
    inst = create_installer(api, name="I", service_area="S")
    tA = create_truck(api, name="TA")
    tB = create_truck(api, name="TB")
    # Order1: delivered job J1; referral R1 scheduled [10:00,12:00).
    o1, l1, fx = setup_confirmed_retail_order(api, base_price_cents=5000)
    j1 = create_delivery_job(api, o1["id"], tA["id"], "2026-07-10T08:00:00Z", "2026-07-10T09:00:00Z")
    deliver_job(api, j1["id"])
    r1 = create_referral(api, o1["id"], inst["id"], j1["id"])
    schedule_referral(api, r1["id"], "2026-07-10T10:00:00Z", "2026-07-10T12:00:00Z")
    # Order2: SCHEDULED (undelivered) job J2; referral R2 linked to J2.
    o2, l2, fx2 = setup_confirmed_retail_order(api, base_price_cents=5000, category="SCONCE")
    j2 = create_delivery_job(api, o2["id"], tB["id"], "2026-07-10T08:00:00Z", "2026-07-10T09:00:00Z")
    r2 = create_referral(api, o2["id"], inst["id"], j2["id"])
    return r2


def test_schedule_reports_delivery_not_ready_over_installer_conflict(api):
    """PRD §2.8: "Within that business tier the ordering is: the special-order confirmation
    guard and the delivery-creation order-state guard (`ERR_ORDER_NOT_CONFIRMED`); the
    install-schedule delivery-readiness guard (`ERR_DELIVERY_NOT_READY`); the installer overlap
    guard (`ERR_INSTALLER_UNAVAILABLE`); the truck buffer guard (`ERR_TRUCK_WINDOW_CONFLICT`)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    r2 = _referential_vs_temporal_setup(api)
    # Appointment [11:00,13:00) overlaps R1 AND J2 is undelivered; readiness guard wins.
    resp = api.schedule_install_referral(
        r2["id"], {"appointment_start": "2026-07-10T11:00:00Z", "appointment_end": "2026-07-10T13:00:00Z"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_READY.value)


def test_schedule_referential_conflict_leaves_referral_referred(api):
    """PRD §2.8: "the install-schedule delivery-readiness guard (`ERR_DELIVERY_NOT_READY`);
    the installer overlap guard (`ERR_INSTALLER_UNAVAILABLE`)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    r2 = _referential_vs_temporal_setup(api)
    api.schedule_install_referral(
        r2["id"], {"appointment_start": "2026-07-10T11:00:00Z", "appointment_end": "2026-07-10T13:00:00Z"}, SM
    )
    data = validate_success(api.get_install_referral(r2["id"], SM), 200)
    assert data["status"] == "REFERRED"


# --------------------------- corner: delivery create guards -------------------------------
def test_delivery_job_create_requires_confirmed_order(api):
    """PRD §3.7: "Creating a delivery job also requires the parent order to have advanced to
    `CONFIRMED` or `COMPLETED`; otherwise it is rejected with `ERR_ORDER_NOT_CONFIRMED`."

    Design: Corner/validations/delivery_create_order_not_confirmed_returns_error
    """
    truck = create_truck(api, name="TQ")
    fx = create_fixture(api, sku_base="F-DQ", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="DQ")
    add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])  # order QUOTED, not confirmed
    resp = api.create_delivery_job(
        {"order_id": order["id"], "delivery_truck_id": truck["id"],
         "window_start": "2026-07-15T10:00:00Z", "window_end": "2026-07-15T12:00:00Z"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONFIRMED.value)


def test_delivery_job_window_end_before_start_returns_validation(api):
    """PRD §3.7: "The window must be well-formed — a `window_end` at or before `window_start`
    is rejected with `ERR_VALIDATION`".

    Design: Corner/validations/delivery_job_window_end_before_start_returns_validation
    """
    truck = create_truck(api, name="TW")
    order, line, fx = setup_confirmed_retail_order(api, base_price_cents=5000)
    resp = api.create_delivery_job(
        {"order_id": order["id"], "delivery_truck_id": truck["id"],
         "window_start": "2026-07-14T12:00:00Z", "window_end": "2026-07-14T10:00:00Z"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
