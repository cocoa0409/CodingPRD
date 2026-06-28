"""Shipment / reefer-unit lifecycle: transitions, preconditions, dispatch gates.

Translates difficulty instances (transitive_cascade accept, non_linear_state_machine
precooled branch) and corner state_machines / consistency_model instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures as fx,
    factories as F,
)


def test_new_shipment_starts_tendered(api):
    """PRD §3.2: "A freshly tendered shipment has `status` `TENDERED`, a null `reefer_unit_id`, a `precool_verified` flag of false, both fee totals at 0, and no assigned posture yet."

    Design: Corner/state_machines/new_shipment_starts_in_tendered
    """
    carrier = fx.create_carrier(legal_name="Init Carrier", op_id="carrier-c8")[0]
    resp = api.create_shipment(
        F.create_shipment_payload(carrier["id"], cargo_class="PHARMA"),
        fx.make_shipper_headers("shipper-c8"),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "TENDERED"
    assert data["precool_verified"] is False
    assert data["reefer_unit_id"] is None


def test_reject_an_already_rejected_shipment_returns_invalid_state(api):
    """PRD §3.3: "a carrier rejects a `TENDERED` shipment, moving it `TENDERED → REJECTED`. This is terminal and no unit was ever assigned, so nothing is released."
    PRD §2.6: "the target resource must currently be in a state from which the requested transition is allowed, failing with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/reject_an_already_rejected_shipment_returns_invalid_state
    """
    carrier, ch = fx.create_carrier(legal_name="Term Carrier", op_id="carrier-c7")
    shipment = fx.tender_shipment(carrier["id"], cargo_class="GENERAL", shipper_op="shipper-c7")
    validate_success(api.reject_shipment(shipment["id"], ch))
    resp = api.reject_shipment(shipment["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_precool_verify_before_readings_returns_precool_incomplete(api):
    """PRD §3.4: "it succeeds only when every compartment on the shipment has at least one `PRECOOL` sensor reading whose `temp_c` lies within that compartment's lane band — at or between `setpoint_min_c` and `setpoint_max_c` inclusive. If any compartment lacks such an in-band precool reading, verification is rejected with `ERR_PRECOOL_INCOMPLETE`."

    Design: Corner/state_machines/precool_verify_before_readings_returns_precool_incomplete
    """
    ctx = fx.setup_accepted(num_compartments=1, carrier_op="carrier-c9", shipper_op="shipper-c9")
    resp = api.precool_verify_shipment(ctx["shipment"]["id"], ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_PRECOOL_INCOMPLETE.value)


def test_accept_with_unit_too_small_returns_unit_too_small(api):
    """PRD §3.3: "its `compartment_count` must be greater than or equal to the number of compartments declared on the shipment — a unit with too few compartments is rejected with `ERR_UNIT_TOO_SMALL`."

    Design: Corner/state_machines/accept_with_unit_too_small_returns_unit_too_small
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=2, compartment_count=1, carrier_op="carrier-c12", shipper_op="shipper-c12"
    )
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(
        sid, F.accept_payload(ctx["unit"]["id"], sv), ctx["carrier_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_TOO_SMALL.value)


def test_duplicate_compartment_ordinal_rejected(api):
    """PRD §3.2: "The `ordinal` must be unique among the shipment's compartments and must fall within 1 through the reefer compartment count range; a duplicate or out-of-range ordinal is rejected with `ERR_DUPLICATE_ORDINAL`."

    Design: Corner/state_machines/duplicate_compartment_ordinal_rejected
    """
    carrier, ch = fx.create_carrier(legal_name="Dup Carrier", op_id="carrier-c13")
    lane = fx.create_lane()
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op="shipper-c13")
    fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op="shipper-c13")
    resp = api.create_compartment(
        shipment["id"], F.create_compartment_payload(lane["id"], 1),
        fx.make_shipper_headers("shipper-c13"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ORDINAL.value)


def test_dispatch_food_with_lapsed_sanitary_training_returns_lapsed(api):
    """PRD §3.6: "Second, if the shipment's `cargo_class` is `FOOD` or `PHARMA`, the carrier's `sanitary_training_current` must be true, else `ERR_SANITARY_TRAINING_LAPSED`."

    Design: Corner/state_machines/dispatch_food_with_lapsed_sanitary_training_returns_lapsed
    """
    # fsma true so the FSMA gate passes; sanitary false so the sanitary gate fires.
    ctx = _precooled_with_flags(api, fsma=True, sanitary=False, sanitation=True,
                                carrier_op="carrier-c10", shipper_op="shipper-c10")
    resp = api.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_SANITARY_TRAINING_LAPSED.value)


def test_dispatch_with_undocumented_sanitation_returns_undocumented(api):
    """PRD §3.6: "Third, the assigned reefer unit's `last_sanitation_at` must be set (a washout must have been documented), else `ERR_SANITATION_UNDOCUMENTED`."

    Design: Corner/state_machines/dispatch_with_undocumented_sanitation_returns_undocumented
    """
    ctx = _precooled_with_flags(api, fsma=True, sanitary=True, sanitation=False,
                                carrier_op="carrier-c11", shipper_op="shipper-c11")
    resp = api.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_SANITATION_UNDOCUMENTED.value)


def test_dispatch_blocked_when_carrier_not_fsma_registered(api):
    """PRD §3.6: "First, if any compartment's lane is regulated (its `regulated` flag is true), the owning carrier's `fsma_registered` must be true, else the dispatch is rejected with `ERR_FSMA_NOT_REGISTERED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_depends_on_carrier_fsma_registration
    """
    # Carrier fsma=false but sanitary=true and unit sanitation documented: only the
    # FSMA gate (a field on the Carrier entity) blocks the PRECOOLED -> IN_TRANSIT move.
    ctx = _precooled_with_flags(api, fsma=False, sanitary=True, sanitation=True,
                                carrier_op="carrier-op-13", shipper_op="shipper-op-13")
    resp = api.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_FSMA_NOT_REGISTERED.value)


def test_dispatch_fsma_block_leaves_shipment_precooled(api):
    """PRD §3.6: "A carrier dispatches a shipment only from `PRECOOLED`, and only when `precool_verified` is true."
    PRD §3.6: "if any compartment's lane is regulated ... the owning carrier's `fsma_registered` must be true, else the dispatch is rejected with `ERR_FSMA_NOT_REGISTERED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_depends_on_carrier_fsma_registration
    """
    ctx = _precooled_with_flags(api, fsma=False, sanitary=True, sanitation=True,
                                carrier_op="carrier-op-13b", shipper_op="shipper-op-13b")
    validate_error(api.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]),
                   ApiErrorId.ERR_FSMA_NOT_REGISTERED.value)
    after = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert after["status"] == "PRECOOLED", "blocked dispatch must leave the shipment in PRECOOLED"


def test_accept_cascade_assigns_unit_and_bumps_version(api):
    """PRD §3.3: "On a successful accept the shipment moves `TENDERED → ACCEPTED`, its `reefer_unit_id` is set to the named unit, that unit moves `AVAILABLE → ASSIGNED`, and the shipment's `version` increments by 1."

    Design: Difficulty/transitive_cascade/accept_cascade_assigns_unit_and_bumps_version
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, compartment_count=2, carrier_op="carrier-op-8", shipper_op="shipper-op-8",
        asset_tag="RU-8",
    )
    sid = ctx["shipment"]["id"]
    accepted_version = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(
        sid, F.accept_payload(ctx["unit"]["id"], accepted_version), ctx["carrier_headers"]
    )
    data = validate_success(resp)
    assert data["reefer_unit_id"] == ctx["unit"]["id"]
    assert data["status"] == "ACCEPTED"
    assert data["version"] == accepted_version + 1, \
        f"version must increment by 1 from {accepted_version}, got {data['version']}"
    unit = validate_success(api.get_reefer_unit(ctx["unit"]["id"], ctx["carrier_headers"]))
    assert unit["status"] == "ASSIGNED", \
        "unit must cascade AVAILABLE -> ASSIGNED from the shipment accept (no direct unit call)"


def test_accept_cascade_reefer_unit_assigned_state(api):
    """PRD §3.1: "It is drawn from the available pool when a shipment is accepted (`AVAILABLE → ASSIGNED`)".

    Design: Difficulty/transitive_cascade/accept_cascade_assigns_unit_and_bumps_version
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, carrier_op="carrier-op-8b", shipper_op="shipper-op-8b", asset_tag="RU-8b",
    )
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    validate_success(api.accept_shipment(sid, F.accept_payload(ctx["unit"]["id"], sv),
                                         ctx["carrier_headers"]))
    unit = validate_success(api.get_reefer_unit(ctx["unit"]["id"], ctx["carrier_headers"]))
    assert unit["status"] == "ASSIGNED"


def test_precooled_shipment_can_be_cancelled_releasing_unit(api):
    """PRD §3.3: "A shipper may cancel a shipment after it has been accepted but before it dispatches — that is, while it is in `ACCEPTED` or in `PRECOOLED`."
    PRD §3.3: "From either of those two states the shipment moves to `CANCELLED`; in both cases the reefer unit that was reserved transitions `ASSIGNED → AVAILABLE` and the shipment's `reefer_unit_id` is cleared back to null, returning the unit to the pool."

    Design: Difficulty/non_linear_state_machine/shipment_precooled_branches_to_in_transit_or_cancelled
    """
    ctx = fx.setup_precooled(num_compartments=1, carrier_op="carrier-op-6", shipper_op="shipper-op-6")
    sid = ctx["shipment"]["id"]
    resp = api.cancel_shipment(sid, fx.make_shipper_headers("shipper-op-6"))
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["reefer_unit_id"] is None, "reefer_unit_id must be cleared to null on cancel"
    unit = validate_success(api.get_reefer_unit(ctx["unit"]["id"], ctx["carrier_headers"]))
    assert unit["status"] == "AVAILABLE", "unit must return to AVAILABLE, not stay IN_TRANSIT"


def test_precooled_shipment_can_dispatch_to_in_transit(api):
    """PRD §3.6: "When all three gates pass, the shipment moves `PRECOOLED → IN_TRANSIT`, the reefer unit moves `ASSIGNED → IN_TRANSIT`, and the moment of dispatch anchors the telemetry timeline so that `offset_min = 0` corresponds to the `IN_TRANSIT` start."

    Design: Difficulty/non_linear_state_machine/shipment_precooled_branches_to_in_transit_or_cancelled
    """
    ctx = fx.setup_precooled(num_compartments=1, carrier_op="carrier-op-6b", shipper_op="shipper-op-6b")
    sid = ctx["shipment"]["id"]
    data = validate_success(api.dispatch_shipment(sid, ctx["carrier_headers"]))
    assert data["status"] == "IN_TRANSIT"
    unit = validate_success(api.get_reefer_unit(ctx["unit"]["id"], ctx["carrier_headers"]))
    assert unit["status"] == "IN_TRANSIT"


def test_accept_changes_visible_in_same_response(api):
    """PRD §3.3: "On a successful accept the shipment moves `TENDERED → ACCEPTED`, its `reefer_unit_id` is set to the named unit".

    Design: Corner/consistency_model/accept_changes_visible_in_same_response
    """
    ctx = fx.setup_tendered_with_compartments(
        num_compartments=1, carrier_op="carrier-c28", shipper_op="shipper-c28", asset_tag="RU-C28",
    )
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(sid, F.accept_payload(ctx["unit"]["id"], sv), ctx["carrier_headers"])
    data = validate_success(resp)
    assert data["reefer_unit_id"] == ctx["unit"]["id"]
    assert data["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Local helper: PRECOOLED shipment with precise carrier compliance flags.
# ---------------------------------------------------------------------------
def _precooled_with_flags(api, fsma, sanitary, sanitation, carrier_op, shipper_op):
    """Build a PRECOOLED FOOD/FROZEN shipment with explicit carrier compliance flags
    and unit sanitation, stopping just before dispatch."""
    from test_helpers import get_success_data
    carrier, ch = fx.create_carrier(legal_name="Gate Carrier", fsma_registered=fsma,
                                    sanitary_training_current=sanitary, op_id=carrier_op)
    lane = fx.create_lane()
    sanit_at = "2026-02-28T00:00:00Z" if sanitation else None
    unit = fx.create_unit(ch, carrier["id"], asset_tag=f"RU-{carrier_op}",
                          compartment_count=1, last_sanitation_at=sanit_at)
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op=shipper_op)
    comp = fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op=shipper_op)
    fx.accept(shipment["id"], unit["id"], ch)
    get_success_data(api.create_reading(comp["id"], F.create_reading_payload("PRECOOL", 0, temp_c=-20), ch))
    get_success_data(api.precool_verify_shipment(shipment["id"], ch))
    return {"carrier": carrier, "carrier_headers": ch, "unit": unit,
            "shipment": shipment, "compartments": [comp]}
