"""Optimistic concurrency on accept, validation-priority conflicts, and conserved
quantities (reefer pool).

Translates difficulty instances (priority_pair_validation_conflict, compensating_invariant
reefer pool) and corner cross_cutting_complexity_layers (OCC) instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    fixtures as fx,
    factories as F,
)


def test_occ_stale_shipment_version_on_accept_rejected(api):
    """PRD §2.7: "The accept request must carry a non-optional `expected_shipment_version` field holding the `version` of the shipment that the carrier last observed. If that value does not equal the shipment's current `version`, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Adding or removing a compartment increments the shipment's `version".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shipment_version_on_accept
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, compartment_count=2, carrier_op="carrier-c26", shipper_op="shipper-c26",
        asset_tag="RU-C26",
    )
    sid = ctx["shipment"]["id"]
    stale_version = fx.current_version(sid, ctx["carrier_headers"])
    # Shipper adds a second compartment, bumping the version past the captured value.
    fx.add_compartment(sid, ctx["lane"]["id"], ordinal=2, shipper_op="shipper-c26")
    resp = api.accept_shipment(
        sid, F.accept_payload(ctx["unit"]["id"], stale_version), ctx["carrier_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_version_on_accept_succeeds_and_bumps_version(api):
    """PRD §3.3: "On a successful accept the shipment moves `TENDERED → ACCEPTED ... and the shipment's `version` increments by 1."
    PRD §2.7: "If that value does not equal the shipment's current `version`, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_accept_succeeds
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, carrier_op="carrier-c27", shipper_op="shipper-c27", asset_tag="RU-C27",
    )
    sid = ctx["shipment"]["id"]
    current = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(sid, F.accept_payload(ctx["unit"]["id"], current), ctx["carrier_headers"])
    data = validate_success(resp)
    assert data["status"] == "ACCEPTED"
    assert data["version"] == current + 1, \
        f"accept must bump version from {current} to {current + 1}, got {data['version']}"


def test_state_check_beats_safety_gate_on_dispatch(api):
    """PRD §2.6: "Fifth is state legality: the target resource must currently be in a state from which the requested transition is allowed, failing with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.6: "After those five framework checks, the domain-specific business rules apply (the dispatch safety gates, ... )".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch_wrong_state_and_no_fsma
    """
    # ACCEPTED (not PRECOOLED) shipment whose carrier is also not FSMA-registered: the
    # state check (priority 5) wins over the FSMA safety gate (priority 6).
    carrier, ch = fx.create_carrier(legal_name="NoFsma Carrier", fsma_registered=False,
                                    sanitary_training_current=False, op_id="carrier-op-9b")
    lane = fx.create_lane()
    unit = fx.create_unit(ch, carrier["id"], asset_tag="RU-9b", compartment_count=1)
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op="shipper-op-9b")
    fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op="shipper-op-9b")
    fx.accept(shipment["id"], unit["id"], ch)
    # Shipment is ACCEPTED (precool not verified); dispatch must fail the state check.
    resp = api.dispatch_shipment(shipment["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_safety_gate_from_tendered(api):
    """PRD §2.6: "Fifth is state legality: the target resource must currently be in a state from which the requested transition is allowed, failing with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "A carrier dispatches a shipment only from `PRECOOLED`, and only when `precool_verified` is true."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch_wrong_state_and_no_fsma
    """
    # TENDERED (not even ACCEPTED) shipment, carrier not FSMA-registered: the state
    # check still pre-empts the FSMA safety gate.
    carrier, ch = fx.create_carrier(legal_name="NoFsma2 Carrier", fsma_registered=False,
                                    sanitary_training_current=False, op_id="carrier-op-9c")
    lane = fx.create_lane()
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op="shipper-op-9c")
    fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op="shipper-op-9c")
    resp = api.dispatch_shipment(shipment["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_fk_check_beats_constraint_gate_on_accept(api):
    """PRD §2.6: "Fourth is body-level referential integrity — foreign keys in the body must resolve, failing with `ERR_FK_NOT_FOUND`."
    PRD §2.5: "When a create or accept request names a related resource by id — a `carrier_id`, a `reefer_unit_id`, ... and that id does not resolve to an existing resource of the correct type, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_accept_bad_unit_fk_and_too_small
    """
    # 2-compartment shipment accepted with a non-existent reefer_unit_id: the FK check
    # (priority 4) wins before any ERR_UNIT_TOO_SMALL constraint (priority 10).
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=2, compartment_count=2, carrier_op="carrier-op-10", shipper_op="shipper-op-10",
        asset_tag="RU-10",
    )
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(sid, F.accept_payload(NON_EXISTENT_UUID, sv), ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_fk_check_beats_constraint_independent_of_sizing(api):
    """PRD §2.5: "When a create or accept request names a related resource by id ... and that id does not resolve to an existing resource of the correct type, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 422)."
    PRD §2.6: "Fourth is body-level referential integrity — foreign keys in the body must resolve, failing with `ERR_FK_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_accept_bad_unit_fk_and_too_small
    """
    # A 1-compartment shipment (no sizing problem) accepted with a bogus reefer_unit_id
    # still fails the FK check — the referential gate runs regardless of the unit-sizing
    # constraint that would never even apply here.
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, carrier_op="carrier-op-10b", shipper_op="shipper-op-10b",
        asset_tag="RU-10b",
    )
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(sid, F.accept_payload(NON_EXISTENT_UUID, sv), ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_reefer_pool_conserved_after_accept_then_cancel(api):
    """PRD §3.3: "in both cases the reefer unit that was reserved transitions `ASSIGNED → AVAILABLE` and the shipment's `reefer_unit_id` is cleared back to null, returning the unit to the pool."

    Design: Difficulty/compensating_invariant/reefer_pool_conservation_accept_then_cancel
    """
    ctx = fx.setup_accepted(num_compartments=1, carrier_op="carrier-op-17", shipper_op="shipper-op-17")
    sid = ctx["shipment"]["id"]
    validate_success(api.cancel_shipment(sid, fx.make_shipper_headers("shipper-op-17")))
    # Conserved quantity: count of AVAILABLE units for the carrier returns to 1.
    avail, meta = validate_paginated(
        api.list_reefer_units(ctx["carrier_headers"],
                              params={"carrier_id": ctx["carrier"]["id"], "status": "AVAILABLE"})
    )
    avail_ids = {u["id"] for u in avail}
    assert ctx["unit"]["id"] in avail_ids, "released unit must be back in the AVAILABLE pool"
    assert len(avail_ids) == 1, "AVAILABLE-unit count must equal the pre-accept value (1)"
    unit = validate_success(api.get_reefer_unit(ctx["unit"]["id"], ctx["carrier_headers"]))
    assert unit["status"] == "AVAILABLE"


def test_cancel_clears_shipment_reefer_unit_link(api):
    """PRD §3.3: "in both cases the reefer unit that was reserved transitions `ASSIGNED → AVAILABLE` and the shipment's `reefer_unit_id` is cleared back to null, returning the unit to the pool."

    Design: Difficulty/compensating_invariant/reefer_pool_conservation_accept_then_cancel
    """
    # The compensating cancel must also clear the forward accept's reefer_unit_id link
    # on the shipment — the two sides of the conserved reservation are released together.
    ctx = fx.setup_accepted(num_compartments=1, carrier_op="carrier-op-17b", shipper_op="shipper-op-17b")
    sid = ctx["shipment"]["id"]
    accepted = validate_success(api.get_shipment(sid, ctx["carrier_headers"]))
    assert accepted["reefer_unit_id"] == ctx["unit"]["id"], "accept must set the link first"
    cancelled = validate_success(api.cancel_shipment(sid, fx.make_shipper_headers("shipper-op-17b")))
    assert cancelled["reefer_unit_id"] is None, "cancel must clear reefer_unit_id back to null"
