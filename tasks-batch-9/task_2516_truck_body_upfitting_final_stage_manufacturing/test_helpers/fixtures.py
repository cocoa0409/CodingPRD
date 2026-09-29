"""Composite state builders.

Every builder drives the public API only — there is no direct database access
and no mocking. Each one returns the created records so a test can pin exact
identifiers and versions.

The harness restarts the server before every test, so each of these builders
starts from an empty store and must seed everything it needs.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import UpfitApiClient
from .constants import (
    BODY_DUMP_12FT,
    BODY_SERVICE_11FT,
    CLOCK_ORIGIN,
    CM_F450,
    CM_F550,
    CUSTOMER_METRO,
    EQ_CRANE_6000,
    EQ_DUMP_HOIST_10T,
    EQ_LIFTGATE_2500,
    EQ_PTO_PUMP_AUX,
    WORK_BAY_1,
    vin_f450,
    vin_f550,
)

# ==========================================================================
# Tier 1 — single-record primitives
# ==========================================================================


def pin_clock(api: UpfitApiClient, instant: str = CLOCK_ORIGIN) -> None:
    """Pin the logical clock of §2.4 as the first call of every scenario."""
    get_success_data(api.set_clock(instant, users.ADMIN))


def new_chassis_model(api: UpfitApiClient, spec: Dict[str, Any] = None, **overrides) -> dict:
    payload = dict(spec or CM_F550)
    payload.update(overrides)
    return get_success_data(api.create_chassis_model(payload, users.ADMIN), 201)


def new_body_spec(api: UpfitApiClient, spec: Dict[str, Any] = None, **overrides) -> dict:
    payload = dict(spec or BODY_SERVICE_11FT)
    payload.update(overrides)
    return get_success_data(api.create_body_spec(payload, users.ADMIN), 201)


def new_equipment_spec(api: UpfitApiClient, spec: Dict[str, Any] = None, **overrides) -> dict:
    payload = dict(spec or EQ_CRANE_6000)
    payload.update(overrides)
    return get_success_data(api.create_equipment_spec(payload, users.ADMIN), 201)


def new_work_bay(api: UpfitApiClient, spec: Dict[str, Any] = None, **overrides) -> dict:
    payload = dict(spec or WORK_BAY_1)
    payload.update(overrides)
    return get_success_data(api.create_work_bay(payload, users.ADMIN), 201)


def new_customer(api: UpfitApiClient, **overrides) -> dict:
    payload = dict(CUSTOMER_METRO)
    payload.update(overrides)
    return get_success_data(api.create_customer(payload, users.ADMIN), 201)


def new_configuration(
    api: UpfitApiClient,
    chassis_model_id: str,
    body_spec_id: str,
    *,
    publish: bool = True,
    **overrides,
) -> dict:
    payload = f.build_configuration_payload(chassis_model_id, body_spec_id, **overrides)
    record = get_success_data(api.create_build_configuration(payload, users.ENGINEER), 201)
    if publish:
        record = get_success_data(
            api.publish_build_configuration(record["id"], users.ENGINEER)
        )
    return record


def new_order(api: UpfitApiClient, build_configuration_id: str, **overrides) -> dict:
    payload = f.upfit_order_payload(build_configuration_id, **overrides)
    return get_success_data(api.create_upfit_order(payload, users.SCHEDULER), 201)


def new_chassis(
    api: UpfitApiClient,
    chassis_model_id: str,
    *,
    vin: Optional[str] = None,
    availability_date: str = "2026-08-05",
    ownership: Optional[str] = None,
) -> dict:
    payload = f.chassis_payload(
        chassis_model_id, vin=vin or vin_f550(1), availability_date=availability_date
    )
    if ownership is not None:
        payload["ownership"] = ownership
    return get_success_data(api.receive_chassis(payload, users.ADMIN), 201)


def inspect_chassis(api: UpfitApiClient, chassis_id: str, front_lb: int, rear_lb: int) -> dict:
    return get_success_data(
        api.inspect_chassis(
            chassis_id, f.inspection_payload(front_lb, rear_lb), users.TECHNICIAN
        )
    )


def received_and_inspected_chassis(
    api: UpfitApiClient,
    chassis_model_id: str,
    *,
    vin: Optional[str] = None,
    availability_date: str = "2026-08-05",
    ownership: Optional[str] = None,
    measured: Tuple[int, int] = (4905, 2755),
) -> dict:
    chassis = new_chassis(
        api,
        chassis_model_id,
        vin=vin,
        availability_date=availability_date,
        ownership=ownership,
    )
    return inspect_chassis(api, chassis["id"], measured[0], measured[1])


# ==========================================================================
# Tier 2 — read helpers and small transition wrappers
# ==========================================================================


def read_order(api: UpfitApiClient, order_id: str, headers=None) -> dict:
    return get_success_data(api.get_upfit_order(order_id, headers or users.SCHEDULER))


def read_chassis(api: UpfitApiClient, chassis_id: str, headers=None) -> dict:
    return get_success_data(api.get_chassis(chassis_id, headers or users.ADMIN))


def read_installation(api: UpfitApiClient, installation_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_equipment_installation(installation_id, headers or users.TECHNICIAN)
    )


def read_interface(api: UpfitApiClient, interface_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_electrical_interface(interface_id, headers or users.OFFICER)
    )


def read_slot(api: UpfitApiClient, slot_id: str, headers=None) -> dict:
    return get_success_data(api.get_build_slot(slot_id, headers or users.SCHEDULER))


def read_certification(api: UpfitApiClient, certification_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_weight_certification(certification_id, headers or users.OFFICER)
    )


def read_label(api: UpfitApiClient, label_id: str, headers=None) -> dict:
    return get_success_data(api.get_compliance_label(label_id, headers or users.OFFICER))


def read_claim(api: UpfitApiClient, claim_id: str, headers=None) -> dict:
    return get_success_data(api.get_warranty_claim(claim_id, headers or users.WARRANTY_ADMIN))


def order_version(api: UpfitApiClient, order_id: str) -> int:
    return read_order(api, order_id)["version"]


def chassis_version(api: UpfitApiClient, chassis_id: str) -> int:
    return read_chassis(api, chassis_id)["version"]


def projection(api: UpfitApiClient, order_id: str, basis: str, headers=None) -> dict:
    return get_success_data(
        api.weight_projection(order_id, headers or users.ENGINEER, {"basis": basis})
    )


def submit_engineering(api: UpfitApiClient, order_id: str, headers=None) -> dict:
    return get_success_data(api.submit_engineering(order_id, headers or users.ENGINEER))


def allocate(api: UpfitApiClient, order_id: str, chassis_id: str, headers=None) -> dict:
    version = chassis_version(api, chassis_id)
    return get_success_data(
        api.allocate_chassis(
            order_id,
            f.allocate_chassis_payload(chassis_id, version),
            headers or users.SCHEDULER,
        )
    )


def release(api: UpfitApiClient, order_id: str, headers=None) -> dict:
    return get_success_data(api.release_order(order_id, headers or users.SCHEDULER))


def plan_equipment(
    api: UpfitApiClient,
    order_id: str,
    equipment_spec_id: str,
    mount_cg_from_front_axle_in: int,
    hydraulic_circuit: str,
    headers=None,
) -> dict:
    payload = f.equipment_installation_payload(
        order_id,
        equipment_spec_id,
        mount_cg_from_front_axle_in=mount_cg_from_front_axle_in,
        hydraulic_circuit=hydraulic_circuit,
    )
    return get_success_data(
        api.create_equipment_installation(payload, headers or users.ENGINEER), 201
    )


def install_equipment(
    api: UpfitApiClient, installation_id: str, actual_weight_lb: int, headers=None
) -> dict:
    return get_success_data(
        api.install_equipment(
            installation_id, {"actual_weight_lb": actual_weight_lb}, headers or users.TECHNICIAN
        )
    )


def propose_interface(
    api: UpfitApiClient,
    order_id: str,
    interface_method: str,
    circuit_amp_draw: int,
    signal_source: str,
    *,
    waiver: Optional[bool] = None,
    headers=None,
) -> dict:
    payload = f.electrical_interface_payload(
        order_id,
        interface_method=interface_method,
        circuit_amp_draw=circuit_amp_draw,
        signal_source=signal_source,
    )
    if waiver is not None:
        payload["customer_warranty_waiver_ack"] = waiver
    return get_success_data(
        api.create_electrical_interface(payload, headers or users.ENGINEER), 201
    )


def approve_interface(api: UpfitApiClient, interface_id: str, headers=None) -> dict:
    return get_success_data(api.approve_interface(interface_id, headers or users.OFFICER))


def new_slot(
    api: UpfitApiClient,
    order_id: str,
    work_bay_id: str,
    start_date: str,
    end_date: str,
    *,
    slot_type: str = "BODY_MOUNT",
    queue_if_full: Optional[bool] = None,
    headers=None,
) -> dict:
    payload = f.build_slot_payload(
        order_id, work_bay_id, start_date, end_date, slot_type=slot_type
    )
    if queue_if_full is not None:
        payload["queue_if_full"] = queue_if_full
    return get_success_data(api.create_build_slot(payload, headers or users.SCHEDULER), 201)


def start_slot(api: UpfitApiClient, slot_id: str, headers=None) -> dict:
    return get_success_data(api.start_build_slot(slot_id, headers or users.TECHNICIAN))


def close_slot(api: UpfitApiClient, slot_id: str, headers=None) -> dict:
    return get_success_data(api.close_build_slot(slot_id, headers or users.TECHNICIAN))


def install_body(api: UpfitApiClient, order_id: str, actual_weight_lb: int, headers=None) -> dict:
    return get_success_data(
        api.body_install(
            order_id, {"body_actual_weight_lb": actual_weight_lb}, headers or users.TECHNICIAN
        )
    )


def draft_certification(
    api: UpfitApiClient, order_id: str, basis: str, *, expected_version: Optional[int] = None,
    headers=None,
) -> dict:
    version = expected_version if expected_version is not None else order_version(api, order_id)
    payload = f.weight_certification_payload(order_id, basis, version)
    return get_success_data(
        api.create_weight_certification(payload, headers or users.ENGINEER), 201
    )


def approve_certification(api: UpfitApiClient, certification_id: str, headers=None) -> dict:
    return get_success_data(
        api.approve_weight_certification(certification_id, headers or users.OFFICER)
    )


def issue_label(
    api: UpfitApiClient,
    order_id: str,
    certification_id: str,
    *,
    supersedes_label_id: Optional[str] = None,
    headers=None,
) -> dict:
    payload = f.compliance_label_payload(order_id, certification_id)
    if supersedes_label_id is not None:
        payload["supersedes_label_id"] = supersedes_label_id
    return get_success_data(
        api.create_compliance_label(payload, headers or users.OFFICER_ALT), 201
    )


def deliver(api: UpfitApiClient, order_id: str, headers=None) -> dict:
    return get_success_data(api.deliver_order(order_id, headers or users.SCHEDULER))


def open_claim(
    api: UpfitApiClient,
    order_id: str,
    failure_system: str,
    claim_cost_cents: int,
    *,
    claim_number: str = "WC-5001",
    headers=None,
) -> dict:
    payload = f.warranty_claim_payload(
        order_id, failure_system, claim_cost_cents, claim_number=claim_number
    )
    return get_success_data(
        api.create_warranty_claim(payload, headers or users.WARRANTY_ADMIN), 201
    )


def inspect_claim(api: UpfitApiClient, claim_id: str, taint_confirmed: bool, headers=None) -> dict:
    return get_success_data(
        api.inspect_warranty_claim(
            claim_id, {"taint_confirmed": taint_confirmed}, headers or users.WARRANTY_ADMIN
        )
    )


def adjudicate_claim(
    api: UpfitApiClient, claim_id: str, *, override: Optional[bool] = None, headers=None
) -> dict:
    payload = {} if override is None else {"override_liability_cap": override}
    return get_success_data(
        api.adjudicate_warranty_claim(claim_id, headers or users.WARRANTY_ADMIN, payload)
    )


# ==========================================================================
# Tier 3 — reference catalog worlds
# ==========================================================================


def catalog_service(api: UpfitApiClient, *, with_equipment: bool = True) -> SimpleNamespace:
    """F550 book entry plus the eleven-foot service body, clock pinned."""
    pin_clock(api)
    ns = SimpleNamespace()
    ns.cm = new_chassis_model(api, CM_F550)
    ns.body = new_body_spec(api, BODY_SERVICE_11FT)
    if with_equipment:
        ns.crane = new_equipment_spec(api, EQ_CRANE_6000)
        ns.liftgate = new_equipment_spec(api, EQ_LIFTGATE_2500)
    return ns


def catalog_dump(api: UpfitApiClient, *, with_equipment: bool = True) -> SimpleNamespace:
    """F450 book entry plus the twelve-foot dump body and its hoist."""
    pin_clock(api)
    ns = SimpleNamespace()
    ns.cm = new_chassis_model(api, CM_F450)
    ns.body = new_body_spec(api, BODY_DUMP_12FT)
    if with_equipment:
        ns.hoist = new_equipment_spec(api, EQ_DUMP_HOIST_10T)
        ns.pump = new_equipment_spec(api, EQ_PTO_PUMP_AUX)
    return ns


# ==========================================================================
# Tier 4 — an order standing on a chassis, ready to be advanced
# ==========================================================================


def service_order_world(
    api: UpfitApiClient,
    *,
    offset: int = 120,
    tier: str = "CUSTOM",
    order_type: str = "POOL_STOCK",
    order_number: str = "UO-5001",
    config_code: str = "CFG-SERVICE-A",
    standard_equipment_spec_ids: Optional[Sequence[str]] = None,
    required_payload_lb: Optional[int] = None,
    requested_in_service_date: Optional[str] = None,
    warranty_liability_cap_cents: Optional[int] = None,
    availability_date: str = "2026-08-05",
    measured: Tuple[int, int] = (4905, 2755),
    vin: Optional[str] = None,
    with_bay: bool = True,
    with_equipment: bool = True,
    with_customer: bool = False,
) -> SimpleNamespace:
    """F550 + SERVICE-11FT: a DRAFT order and an INSPECTED unit on the yard.

    With the default mount offset of 120 inches the AS_DESIGNED basis reads
    5009 / 4591 / 9600 with a payload capacity of 9900 pounds, and the
    AS_MEASURED basis on a 2160-pound mounted body reads 5099 / 4721 / 9820
    with a payload capacity of 9680 pounds.
    """
    ns = catalog_service(api, with_equipment=with_equipment)
    if with_bay:
        ns.bay = new_work_bay(api, WORK_BAY_1)
    ns.customer = new_customer(api) if (with_customer or order_type == "CUSTOMER_SPECIFIC") else None
    ns.config = new_configuration(
        api,
        ns.cm["id"],
        ns.body["id"],
        config_code=config_code,
        standardization_tier=tier,
        standard_equipment_spec_ids=list(standard_equipment_spec_ids or []),
    )
    order_kwargs: Dict[str, Any] = {
        "order_number": order_number,
        "order_type": order_type,
        "body_mount_offset_from_front_axle_in": offset,
    }
    if ns.customer is not None and order_type == "CUSTOMER_SPECIFIC":
        order_kwargs["customer_id"] = ns.customer["id"]
    if required_payload_lb is not None:
        order_kwargs["required_payload_lb"] = required_payload_lb
    if requested_in_service_date is not None:
        order_kwargs["requested_in_service_date"] = requested_in_service_date
    if warranty_liability_cap_cents is not None:
        order_kwargs["warranty_liability_cap_cents"] = warranty_liability_cap_cents
    ns.order = new_order(api, ns.config["id"], **order_kwargs)
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin or vin_f550(1),
        availability_date=availability_date,
        measured=measured,
    )
    return ns


def dump_order_world(
    api: UpfitApiClient,
    *,
    offset: int = 96,
    hoist_mount_cg: int = 130,
    tier: str = "CUSTOM",
    order_type: str = "POOL_STOCK",
    order_number: str = "UO-5001",
    config_code: str = "CFG-DUMP-A",
    standard_equipment_spec_ids: Optional[Sequence[str]] = None,
    required_payload_lb: Optional[int] = None,
    requested_in_service_date: Optional[str] = None,
    availability_date: str = "2026-08-05",
    measured: Tuple[int, int] = (4905, 2755),
    vin: Optional[str] = None,
    with_bay: bool = True,
    plan_hoist: bool = True,
) -> SimpleNamespace:
    """F450 + DUMP-12FT with the hoist planned at 130 inches.

    With the default 96-inch mount offset the AS_DESIGNED basis reads
    4467 / 6383 / 10850 and the payload capacity comes out at 2999 pounds,
    because the cargo centroid sits behind the rear axle and the front-axle
    ceiling therefore drops out of the minimum entirely.
    """
    ns = catalog_dump(api)
    if with_bay:
        ns.bay = new_work_bay(api, WORK_BAY_1)
    ns.config = new_configuration(
        api,
        ns.cm["id"],
        ns.body["id"],
        config_code=config_code,
        standardization_tier=tier,
        standard_equipment_spec_ids=list(standard_equipment_spec_ids or []),
    )
    order_kwargs: Dict[str, Any] = {
        "order_number": order_number,
        "order_type": order_type,
        "body_mount_offset_from_front_axle_in": offset,
    }
    if required_payload_lb is not None:
        order_kwargs["required_payload_lb"] = required_payload_lb
    if requested_in_service_date is not None:
        order_kwargs["requested_in_service_date"] = requested_in_service_date
    ns.order = new_order(api, ns.config["id"], **order_kwargs)
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin or vin_f450(1),
        availability_date=availability_date,
        measured=measured,
    )
    if plan_hoist:
        ns.hoist_install = plan_equipment(
            api, ns.order["id"], ns.hoist["id"], hoist_mount_cg, "PRIMARY"
        )
    return ns


# ==========================================================================
# Tier 5 — staged advancement of an existing world
# ==========================================================================


def advance_to_released(api: UpfitApiClient, ns: SimpleNamespace) -> SimpleNamespace:
    """Submit engineering as eng-1, bind the unit, then release as ps-1."""
    submit_engineering(api, ns.order["id"])
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = release(api, ns.order["id"])
    ns.chassis = read_chassis(api, ns.chassis["id"])
    return ns


def advance_to_in_build(
    api: UpfitApiClient,
    ns: SimpleNamespace,
    *,
    start_date: str = "2026-09-01",
    end_date: str = "2026-09-10",
    slot_type: str = "BODY_MOUNT",
) -> SimpleNamespace:
    """Book one bay window and start work in it."""
    ns.slot = new_slot(
        api, ns.order["id"], ns.bay["id"], start_date, end_date, slot_type=slot_type
    )
    ns.slot = start_slot(api, ns.slot["id"])
    ns.order = read_order(api, ns.order["id"])
    ns.chassis = read_chassis(api, ns.chassis["id"])
    return ns


def advance_to_build_complete(
    api: UpfitApiClient, ns: SimpleNamespace, *, body_weight_lb: int = 2160
) -> SimpleNamespace:
    """Bolt the body down and close the only open window."""
    ns.order = install_body(api, ns.order["id"], body_weight_lb)
    ns.slot = close_slot(api, ns.slot["id"])
    ns.order = read_order(api, ns.order["id"])
    return ns


def advance_to_labeled(api: UpfitApiClient, ns: SimpleNamespace) -> SimpleNamespace:
    """Design certification, measured certification, then the label.

    The drafter is eng-1 and the approver co-1, so the label must be issued by
    co-2 to satisfy the segregation of duties on label issuance.
    """
    ns.cert_designed = draft_certification(api, ns.order["id"], "AS_DESIGNED")
    ns.cert_designed = approve_certification(api, ns.cert_designed["id"])
    ns.cert_measured = draft_certification(api, ns.order["id"], "AS_MEASURED")
    ns.cert_measured = approve_certification(api, ns.cert_measured["id"])
    ns.label = issue_label(api, ns.order["id"], ns.cert_measured["id"])
    ns.order = read_order(api, ns.order["id"])
    return ns


def advance_to_delivered(api: UpfitApiClient, ns: SimpleNamespace) -> SimpleNamespace:
    ns.order = deliver(api, ns.order["id"])
    ns.chassis = read_chassis(api, ns.chassis["id"])
    return ns


def delivered_service_order(
    api: UpfitApiClient,
    *,
    interfaces: Sequence[Tuple[str, int, str]] = (),
    approve_interfaces: bool = True,
    warranty_liability_cap_cents: Optional[int] = None,
    order_type: str = "POOL_STOCK",
    with_customer: bool = False,
) -> SimpleNamespace:
    """The whole lifecycle of an F550 service build, ending at DELIVERED.

    No equipment is ever planned, so the measured basis counts the body alone
    and the label that goes on the truck is an ``ALTERER`` label carried by the
    ``UPFITTER``. Each entry in ``interfaces`` is proposed by eng-1 before
    release and approved by co-1, which is how a non-INTACT chassis warranty
    posture is established before a claim is opened.
    """
    ns = service_order_world(
        api,
        order_type=order_type,
        with_customer=with_customer,
        with_equipment=False,
        warranty_liability_cap_cents=warranty_liability_cap_cents,
    )
    ns.interfaces: List[dict] = []
    for method, amps, signal in interfaces:
        record = propose_interface(api, ns.order["id"], method, amps, signal)
        if approve_interfaces:
            record = approve_interface(api, record["id"])
        ns.interfaces.append(record)
    advance_to_released(api, ns)
    advance_to_in_build(api, ns)
    advance_to_build_complete(api, ns)
    advance_to_labeled(api, ns)
    advance_to_delivered(api, ns)
    return ns


# ==========================================================================
# Tier 2 addendum — the remaining single-call transitions
# ==========================================================================


def commission_equipment(api: UpfitApiClient, installation_id: str, headers=None) -> dict:
    return get_success_data(
        api.commission_equipment(installation_id, headers or users.TECHNICIAN)
    )


def decommission_equipment(
    api: UpfitApiClient, installation_id: str, reason: str, headers=None
) -> dict:
    return get_success_data(
        api.decommission_equipment(
            installation_id, {"reason": reason}, headers or users.TECHNICIAN
        )
    )


def remove_equipment(
    api: UpfitApiClient, installation_id: str, reason: str, headers=None
) -> dict:
    return get_success_data(
        api.remove_equipment(installation_id, {"reason": reason}, headers or users.TECHNICIAN)
    )


def quarantine_chassis(api: UpfitApiClient, chassis_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.quarantine_chassis(
            chassis_id, {"quarantine_reason": reason}, headers or users.ADMIN
        )
    )


def return_chassis(api: UpfitApiClient, chassis_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.return_chassis(chassis_id, {"reason": reason}, headers or users.ADMIN)
    )


def cancel_order(api: UpfitApiClient, order_id: str, reason: str, headers=None) -> dict:
    # PRD 3.3: "Cancellation is a `PlantAdmin` capability" — the default caller
    # must therefore be the plant administrator, not the scheduler.
    return get_success_data(
        api.cancel_order(order_id, {"reason": reason}, headers or users.ADMIN)
    )


def cancel_slot(api: UpfitApiClient, slot_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.cancel_build_slot(slot_id, {"reason": reason}, headers or users.SCHEDULER)
    )


def reject_interface(api: UpfitApiClient, interface_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.reject_interface(interface_id, {"reason": reason}, headers or users.OFFICER)
    )


def request_rework(api: UpfitApiClient, order_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.request_rework(order_id, {"reason": reason}, headers or users.OFFICER)
    )


def patch_body_mount(api: UpfitApiClient, order_id: str, offset_in: int, headers=None) -> dict:
    return get_success_data(
        api.patch_body_mount(
            order_id,
            {"body_mount_offset_from_front_axle_in": offset_in},
            headers or users.ENGINEER,
        )
    )


def deprecate_configuration(api: UpfitApiClient, configuration_id: str, headers=None) -> dict:
    return get_success_data(
        api.deprecate_build_configuration(configuration_id, headers or users.ENGINEER)
    )


def read_configuration(api: UpfitApiClient, configuration_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_build_configuration(configuration_id, headers or users.ENGINEER)
    )


def set_bay_status(api: UpfitApiClient, work_bay_id: str, status: str, headers=None) -> dict:
    return get_success_data(
        api.set_work_bay_status(work_bay_id, {"status": status}, headers or users.ADMIN)
    )


def dispute_claim(api: UpfitApiClient, claim_id: str, reason: str, headers=None) -> dict:
    return get_success_data(
        api.dispute_warranty_claim(claim_id, {"reason": reason}, headers or users.WARRANTY_ADMIN)
    )


def pay_claim(api: UpfitApiClient, claim_id: str, headers=None) -> dict:
    return get_success_data(
        api.pay_warranty_claim(claim_id, headers or users.WARRANTY_ADMIN)
    )
