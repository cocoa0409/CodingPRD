"""Composite setup helpers — multi-step lifecycle builders (PRD §3).

Every fixture builds preconditions from scratch via PRD-declared endpoints.
Internal setup calls use get_success_data (lenient) so failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_alternator_model_payload,
    create_configuration_payload,
    create_crane_slot_payload,
    create_customer_payload,
    create_emissions_certificate_payload,
    create_engine_model_payload,
    create_factory_test_payload,
    create_order_payload,
    create_paralleling_scheme_payload,
    create_permit_case_payload,
    create_service_contract_payload,
    create_shipment_payload,
    create_sizing_study_payload,
    create_test_bay_payload,
)
from .test_users import TEST_USERS, make_customer_contact_headers, make_test_engineer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
FSM = TEST_USERS["field_service_manager_headers"]

# A standard three-step continuous load profile used by many sizing setups:
# running = 100 + 80 + 60 = 240; starting = 240 - 100 + 100*3.0 = 440
THREE_STEP_LOAD = [
    {"description": "A", "kva": 100, "duty": "CONTINUOUS"},
    {"description": "B", "kva": 80, "duty": "CONTINUOUS"},
    {"description": "C", "kva": 60, "duty": "CONTINUOUS"},
]


def setup_customer(**overrides) -> dict:
    payload = create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def setup_engine_model(**overrides) -> dict:
    payload = create_engine_model_payload(**overrides)
    return get_success_data(api_client.create_engine_model(payload, ADMIN))


def setup_alternator_model(**overrides) -> dict:
    payload = create_alternator_model_payload(**overrides)
    return get_success_data(api_client.create_alternator_model(payload, ADMIN))


def setup_order(customer_id, **overrides) -> dict:
    payload = create_order_payload(customer_id=customer_id, **overrides)
    return get_success_data(api_client.create_order(payload, SALES))


def setup_catalog(customer_overrides=None, engine_overrides=None, alternator_overrides=None):
    """Create customer + engine + alternator. Returns (customer, engine, alternator)."""
    customer = setup_customer(**(customer_overrides or {}))
    engine = setup_engine_model(**(engine_overrides or {}))
    alternator = setup_alternator_model(**(alternator_overrides or {}))
    return customer, engine, alternator


def create_study(order, engine_id, alternator_id, load_steps=None, **overrides) -> dict:
    """Create a DRAFT sizing study, threading the order's current version."""
    order_now = get_success_data(api_client.get_order(order["id"], SALES))
    payload = create_sizing_study_payload(
        order_id=order["id"],
        engine_model_id=engine_id,
        alternator_model_id=alternator_id,
        load_steps=load_steps if load_steps is not None else [
            {"description": "A", "kva": 100, "duty": "CONTINUOUS"}
        ],
        expected_order_version=order_now["version"],
        **overrides,
    )
    return get_success_data(api_client.create_sizing_study(payload, APP_ENG))


def create_submitted_study(order, engine_id, alternator_id, load_steps=None, **overrides) -> dict:
    """Create a study and submit it (SUBMITTED)."""
    study = create_study(order, engine_id, alternator_id, load_steps, **overrides)
    return get_success_data(api_client.submit_sizing_study(study["id"], APP_ENG))


def create_approved_study(order, engine_id, alternator_id, load_steps=None, **overrides) -> dict:
    """Create, submit, and approve a study. Returns the APPROVED study."""
    study = create_submitted_study(order, engine_id, alternator_id, load_steps, **overrides)
    return get_success_data(api_client.approve_sizing_study(study["id"], SALES))


def authorize_order(order_id, amount_cents=60000000, freight_charge_cents=1250000) -> dict:
    payload = {"amount_cents": amount_cents, "freight_charge_cents": freight_charge_cents}
    return get_success_data(api_client.authorize_order(order_id, payload, SALES))


def setup_authorized_order(customer_overrides=None, engine_overrides=None,
                           alternator_overrides=None, order_overrides=None,
                           amount_cents=60000000, freight_charge_cents=1250000,
                           load_steps=None, study_overrides=None):
    """Customer + catalog + order with APPROVED study and AUTHORIZED order.

    Returns dict with keys: customer, engine, alternator, order, study.
    """
    customer, engine, alternator = setup_catalog(
        customer_overrides, engine_overrides, alternator_overrides
    )
    order = setup_order(customer["id"], **(order_overrides or {}))
    study = create_approved_study(
        order, engine["id"], alternator["id"], load_steps, **(study_overrides or {})
    )
    order = authorize_order(order["id"], amount_cents, freight_charge_cents)
    return {
        "customer": customer,
        "engine": engine,
        "alternator": alternator,
        "order": order,
        "study": study,
    }


def create_configuration(order_id, sizing_study_id, **overrides) -> dict:
    payload = create_configuration_payload(
        order_id=order_id, sizing_study_id=sizing_study_id, **overrides
    )
    return get_success_data(api_client.create_configuration(payload, APP_ENG))


def setup_locked_configuration(**kwargs):
    """Authorized order + APPROVED study + LOCKED configuration.

    Returns dict with keys: customer, engine, alternator, order, study, configuration.
    Extra kwargs: configuration_overrides, plus setup_authorized_order kwargs.
    """
    config_overrides = kwargs.pop("configuration_overrides", {})
    ctx = setup_authorized_order(**kwargs)
    config = create_configuration(ctx["order"]["id"], ctx["study"]["id"], **config_overrides)
    config = get_success_data(api_client.lock_configuration(config["id"], APP_ENG))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    ctx["order"] = order
    ctx["configuration"] = config
    return ctx


def setup_submitted_permit(**kwargs):
    """Locked configuration + SUBMITTED permit. Adds keys: permit."""
    ctx = setup_locked_configuration(**kwargs)
    permit = get_success_data(api_client.create_permit_case(
        create_permit_case_payload(
            order_id=ctx["order"]["id"],
            configuration_id=ctx["configuration"]["id"],
        ),
        COMPLIANCE,
    ))
    permit = get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    ctx["permit"] = permit
    return ctx


def setup_approved_permit(**kwargs):
    """Submitted permit approved by the AHJ. Adds keys: permit."""
    ctx = setup_submitted_permit(**kwargs)
    permit = get_success_data(api_client.approve_permit_ahj(ctx["permit"]["id"], ADMIN))
    ctx["permit"] = permit
    return ctx


def create_certificate(order_id, configuration_id, **overrides) -> dict:
    payload = create_emissions_certificate_payload(
        order_id=order_id, configuration_id=configuration_id, **overrides
    )
    return get_success_data(api_client.create_emissions_certificate(payload, COMPLIANCE))


def setup_issued_certificate(**kwargs):
    """Locked config + APPROVED permit + ISSUED certificate -> order build TESTING.

    Adds keys: permit, certificate.
    """
    ctx = setup_approved_permit(**kwargs)
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    cert = get_success_data(
        api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE)
    )
    cert = get_success_data(api_client.issue_emissions_certificate(cert["id"], ADMIN))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    ctx["order"] = order
    ctx["certificate"] = cert
    return ctx


def setup_test_bay(**overrides) -> dict:
    payload = create_test_bay_payload(**overrides)
    return get_success_data(api_client.create_test_bay(payload, ADMIN))


def create_factory_test(order_id, configuration_id, bay_id, **overrides) -> dict:
    payload = create_factory_test_payload(
        order_id=order_id, configuration_id=configuration_id, bay_id=bay_id, **overrides
    )
    return get_success_data(api_client.create_factory_test(payload, make_test_engineer_headers("eng-scheduler")))


def setup_testing_order(**kwargs):
    """Full chain to build_status TESTING with a test bay ready.

    Keys: customer, engine, alternator, order, study, configuration, permit,
    certificate, bay.
    """
    bay_overrides = kwargs.pop("bay_overrides", {})
    ctx = setup_issued_certificate(**kwargs)
    bay = setup_test_bay(**bay_overrides)
    ctx["bay"] = bay
    return ctx


def record_passing_test(test_id, recorder_id="eng-recorder-1", readings=None) -> dict:
    """Start + record a passing test. Returns the recorded (PASSED) test."""
    get_success_data(api_client.start_factory_test(test_id, make_test_engineer_headers(recorder_id)))
    payload = {"readings": readings or [{"kw": 100, "hours": 1.0, "power_factor": 0.90}]}
    return get_success_data(
        api_client.record_factory_test(test_id, payload, make_test_engineer_headers(recorder_id))
    )


def setup_accepted_test(**kwargs):
    """Order at READY_TO_SHIP: test recorded PASS and accepted (SoD respected).

    Adds keys: bay, test.
    """
    ctx = setup_testing_order(**kwargs)
    test = create_factory_test(ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"])
    recorder = "eng-recorder-1"
    acceptor = "eng-acceptor-1"
    test = record_passing_test(test["id"], recorder)
    test = get_success_data(
        api_client.accept_factory_test(test["id"], make_test_engineer_headers(acceptor))
    )
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    ctx["order"] = order
    ctx["test"] = test
    ctx["recorder_id"] = recorder
    ctx["acceptor_id"] = acceptor
    return ctx


def setup_crane_slot(**overrides) -> dict:
    payload = create_crane_slot_payload(**overrides)
    return get_success_data(api_client.create_crane_slot(payload, ADMIN))


def book_shipment(order_id, crane_slot, **overrides) -> dict:
    slot_now = get_success_data(api_client.get_crane_slot(crane_slot["id"], LOGISTICS))
    payload = create_shipment_payload(
        order_id=order_id,
        crane_slot_id=crane_slot["id"],
        expected_crane_slot_version=slot_now["version"],
        **overrides,
    )
    return get_success_data(api_client.create_shipment(payload, LOGISTICS))


def setup_booked_shipment(**kwargs):
    """Order READY_TO_SHIP with a BOOKED shipment on a fresh crane slot.

    Adds keys: crane_slot, shipment.
    """
    slot_overrides = kwargs.pop("slot_overrides", {})
    shipment_overrides = kwargs.pop("shipment_overrides", {})
    ctx = setup_accepted_test(**kwargs)
    slot = setup_crane_slot(**slot_overrides)
    shipment = book_shipment(ctx["order"]["id"], slot, **shipment_overrides)
    ctx["crane_slot"] = slot
    ctx["shipment"] = shipment
    return ctx


def setup_delivered_order(**kwargs):
    """Full chain through shipment DELIVERED (order build DELIVERED, commercial INVOICED).

    The crane slot's service_date defaults to the logical clock date so dispatch
    is immediately possible. Adds keys: crane_slot, shipment.
    """
    kwargs.setdefault("slot_overrides", {})
    kwargs["slot_overrides"].setdefault("service_date", "2026-08-01")
    ctx = setup_booked_shipment(**kwargs)
    shipment = get_success_data(api_client.dispatch_shipment(ctx["shipment"]["id"], LOGISTICS))
    shipment = get_success_data(api_client.deliver_shipment(shipment["id"], LOGISTICS))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    ctx["shipment"] = shipment
    ctx["order"] = order
    return ctx


def create_commissioning_event(order_id, shipment_id, **overrides) -> dict:
    from .factories import create_commissioning_event_payload
    payload = create_commissioning_event_payload(
        order_id=order_id, shipment_id=shipment_id, **overrides
    )
    return get_success_data(api_client.create_commissioning_event(payload, FSM))


def setup_completed_commissioning(**kwargs):
    """Delivered order + commissioning event COMPLETED (not yet accepted).

    Adds keys: crane_slot, shipment, event.
    """
    event_overrides = kwargs.pop("event_overrides", {})
    engineer_id = kwargs.pop("engineer_id", "field-eng-1")
    training_hours = kwargs.pop("training_hours", 3.0)
    ctx = setup_delivered_order(**kwargs)
    event = create_commissioning_event(
        ctx["order"]["id"], ctx["shipment"]["id"], **event_overrides
    )
    event = get_success_data(api_client.assign_commissioning_event(
        event["id"], {"engineer_id": engineer_id}, FSM
    ))
    event = get_success_data(api_client.start_commissioning_event(event["id"], FSM))
    event = get_success_data(api_client.complete_commissioning_event(
        event["id"], {"training_hours": training_hours, "checklist_completed": True}, FSM
    ))
    ctx["event"] = event
    return ctx


def setup_commissioned_order(**kwargs):
    """Full lifecycle through COMMISSIONED (commercial CLOSED).

    Adds keys: crane_slot, shipment, event.
    """
    ctx = setup_completed_commissioning(**kwargs)
    contact = make_customer_contact_headers(ctx["customer"]["id"])
    event = get_success_data(api_client.accept_commissioning_event(ctx["event"]["id"], contact))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    ctx["event"] = event
    ctx["order"] = order
    return ctx


def create_service_contract(order_id, **overrides) -> dict:
    payload = create_service_contract_payload(order_id=order_id, **overrides)
    return get_success_data(api_client.create_service_contract(payload, SALES))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def reset_clock():
    """Return the logical clock to its startup default (PRD §2.4)."""
    return set_clock(DEFAULT_CLOCK_ISO)


def setup_scheme_with_positions(order_id, max_units=2, num_positions=1, sync_mode="ISOLATED"):
    scheme = get_success_data(api_client.create_paralleling_scheme(
        create_paralleling_scheme_payload(order_id=order_id, sync_mode=sync_mode, max_units=max_units),
        APP_ENG,
    ))
    for _ in range(num_positions):
        scheme = get_success_data(
            api_client.add_scheme_position(scheme["id"], {"kw_rating": 500}, APP_ENG)
        )
    return scheme
