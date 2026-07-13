"""Device activation guards, out-of-service restoration, and the
device-operability precondition on starting an inspection."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Corner: validations / activate_before_fee_paid
# --------------------------------------------------------------------------
def test_activate_before_fee_paid_returns_registration_fee_unpaid(api):
    """PRD §3.3: "the device's `REGISTRATION` fee invoice must already be `PAID`,
    or the request is rejected with `ERR_REGISTRATION_FEE_UNPAID` (HTTP 402)."

    Design: Corner/validations/activate_before_fee_paid_returns_registration_fee_unpaid
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    resp = api.activate_device(ctx["device"]["id"], th.REG)
    th.validate_error(resp, ApiErrorId.ERR_REGISTRATION_FEE_UNPAID.value)


# --------------------------------------------------------------------------
# Corner: state_machines / activate_twice_returns_not_registered
# --------------------------------------------------------------------------
def test_activate_twice_returns_not_registered(api):
    """PRD §3.3: "Activation has two guards: the device must currently be
    REGISTERED, or the request is rejected with ERR_DEVICE_NOT_REGISTERED".

    Design: Corner/state_machines/activate_twice_returns_not_registered
    """
    ctx = th.setup_active_device(api, category="PASSENGER_ELEVATOR")
    resp = api.activate_device(ctx["device"]["id"], th.REG)
    th.validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_REGISTERED.value)


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / inspection_start_requires_device_operable
# --------------------------------------------------------------------------
def test_start_blocked_when_device_out_of_service(api):
    """PRD §3.5: "Because an inspector cannot work on a device that is out of
    service or gone, the device must not be OUT_OF_SERVICE or DECOMMISSIONED;
    either state rejects the start with ERR_DEVICE_NOT_OPERABLE."

    Design: Difficulty/cross_entity_state_dependency/inspection_start_requires_device_operable
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], inspector["id"])
    th.create_oos_order(api, device["id"], reason="NONPAYMENT", start=0, end=10)
    resp = api.start_inspection(ins["id"], th.make_licensed_inspector_headers(inspector["id"]))
    th.validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_OPERABLE.value)


def test_start_allowed_when_device_operable(api):
    """PRD §3.5: "Because an inspector cannot work on a device that is out of
    service or gone, the device must not be `OUT_OF_SERVICE` or `DECOMMISSIONED`;
    either state rejects the start with `ERR_DEVICE_NOT_OPERABLE`." An operable
    device therefore permits the start.

    Design: Difficulty/cross_entity_state_dependency/inspection_start_requires_device_operable
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], inspector["id"])
    resp = api.start_inspection(ins["id"], th.make_licensed_inspector_headers(inspector["id"]))
    started = th.validate_success(resp)
    assert started["status"] == "IN_PROGRESS"


# --------------------------------------------------------------------------
# Corner: state_machines / oos_lift_restores_device_active
# --------------------------------------------------------------------------
def test_oos_lift_restores_device_active(api):
    """PRD §2.8: "When an active order is later lifted, active_oos_count is
    decremented by 1; if that decrement brings active_oos_count to 0, the device
    returns from OUT_OF_SERVICE to ACTIVE".

    Design: Corner/state_machines/oos_lift_restores_device_active
    """
    ctx = th.setup_active_device(api, category="PASSENGER_ELEVATOR")
    order = th.create_oos_order(api, ctx["device"]["id"], reason="NONPAYMENT", start=0, end=5)
    lifted = th.lift_oos_order(api, order["id"])
    assert lifted["status"] == "LIFTED"
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["status"] == "ACTIVE"
    assert dev["active_oos_count"] == 0


# --------------------------------------------------------------------------
# Corner: state_machines / lift_inactive_order_returns_not_active
# --------------------------------------------------------------------------
def test_lift_inactive_order_returns_not_active(api):
    """PRD §3.8: "The order must be `ACTIVE`, or the request is rejected with
    `ERR_OOS_ORDER_NOT_ACTIVE`."

    Design: Corner/state_machines/lift_inactive_order_returns_not_active
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    order = th.create_oos_order(api, ctx["device"]["id"], reason="NONPAYMENT", start=0, end=5)
    th.lift_oos_order(api, order["id"])
    resp = api.lift_oos_order(order["id"], th.SAFETY)
    th.validate_error(resp, ApiErrorId.ERR_OOS_ORDER_NOT_ACTIVE.value)
