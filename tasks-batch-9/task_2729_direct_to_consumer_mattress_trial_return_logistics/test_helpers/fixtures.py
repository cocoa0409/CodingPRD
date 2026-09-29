"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the API server before each test, so no
helper may assume a pre-existing row.

``get_success_data()`` (the lenient validator) is used throughout so that a
broken setup step reports "Setup step failed" rather than an opaque assertion.

Identity threading: PRD §2.1 makes ``Customer`` and ``RetailPartner``
entity-backed, so every ownership-gated call below is issued with
``make_customer_headers(customer["id"])`` or
``make_retail_partner_headers(partner["id"])`` rather than the shared header
constants.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    adjudicate_payload,
    approve_exchange_payload,
    attribution_claim_payload,
    clock_payload,
    comfort_exchange_payload,
    complete_appointment_payload,
    confirm_intake_payload,
    customer_payload,
    disposition_partner_payload,
    disposition_payload,
    inspect_payload,
    mattress_model_payload,
    pickup_appointment_payload,
    pickup_route_payload,
    promotion_bundle_payload,
    quality_claim_payload,
    refund_authorization_payload,
    retail_partner_payload,
    return_case_payload,
    review_attribution_payload,
    trial_abuse_signal_payload,
    trial_order_payload,
    void_refund_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_finance_controller_headers,
    make_retail_partner_headers,
    make_trial_support_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["trial_support_agent_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

# Two distinct operators per role, for the segregation-of-duties rules of PRD §2.11.
AUTHORIZER = make_finance_controller_headers("fin-authorizer-1")
RELEASER = make_finance_controller_headers("fin-releaser-1")
APPROVING_AGENT = make_trial_support_agent_headers("agent-approver-1")
SETTLING_CONTROLLER = make_finance_controller_headers("fin-settler-1")


# ---------------------------------------------------------------------------
# Clock (PRD §2.5)
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock to an exact instant."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_customer(customer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trial_order(order_id, headers or ADMIN))


def read_return_case(return_case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_return_case(return_case_id, headers or FINANCE))


def read_refund_summary(return_case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_refund_summary(return_case_id, headers or FINANCE))


def read_route(route_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_pickup_route(route_id, headers or LOGISTICS))


def read_appointment(appointment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_pickup_appointment(appointment_id, headers or LOGISTICS)
    )


def read_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_disposition_assignment(assignment_id, headers or LOGISTICS)
    )


def read_refund(refund_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_refund_authorization(refund_id, headers or FINANCE)
    )


def read_exchange(exchange_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_comfort_exchange(exchange_id, headers or AGENT))


def read_quality_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_quality_claim(claim_id, headers or AGENT))


def read_attribution_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_attribution_claim(claim_id, headers or FINANCE))


def list_abuse_signals(customer_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_customer_abuse_signals(customer_id, ADMIN, params=params)
    )


# ---------------------------------------------------------------------------
# Tier 1 — single rows of the catalogue (PRD §3.1)
# ---------------------------------------------------------------------------


def create_model(**overrides) -> dict:
    return get_success_data(
        api_client.create_mattress_model(mattress_model_payload(**overrides), ADMIN)
    )


def create_bundle(**overrides) -> dict:
    return get_success_data(
        api_client.create_promotion_bundle(promotion_bundle_payload(**overrides), ADMIN)
    )


def create_retail_partner_row(**overrides) -> dict:
    return get_success_data(
        api_client.create_retail_partner(retail_partner_payload(**overrides), ADMIN)
    )


def create_disposition_partner_row(**overrides) -> dict:
    return get_success_data(
        api_client.create_disposition_partner(
            disposition_partner_payload(**overrides), ADMIN
        )
    )


def create_customer_row(**overrides) -> dict:
    return get_success_data(api_client.create_customer(customer_payload(**overrides), ADMIN))


def create_charity(**overrides) -> dict:
    """An ACTIVE CHARITY partner that accepts grades A and B and refuses soiled units."""
    spec = {
        "name": "Second Sleep Charity",
        "partner_type": "CHARITY",
        "accepts_condition_grades": ["A", "B"],
        "soil_policy": "REJECT_SOILED",
        "priority_rank": 1,
    }
    spec.update(overrides)
    return create_disposition_partner_row(**spec)


def create_recycler(**overrides) -> dict:
    """An ACTIVE RECYCLER partner that accepts every grade and soiled units."""
    spec = {
        "name": "Foam Cycle",
        "partner_type": "RECYCLER",
        "accepts_condition_grades": ["A", "B", "C", "D"],
        "soil_policy": "ACCEPT_SOILED",
        "priority_rank": 2,
        "recycle_fee_cents_per_unit": 5000,
    }
    spec.update(overrides)
    return create_disposition_partner_row(**spec)


# ---------------------------------------------------------------------------
# Tier 2 — customer, order and the delivery cascade (PRD §3.3)
# ---------------------------------------------------------------------------


def setup_delivered_order(
    model=None,
    model_overrides=None,
    customer=None,
    customer_overrides=None,
    order_overrides=None,
    delivered_at=TEST_DEFAULTS["DELIVERY_CLOCK"],
    dispatch=True,
    deliver=True,
) -> dict:
    """Catalogue row, customer and one trial order carried as far as delivery.

    ``delivered_at`` moves the logical clock before the deliver call, so
    ``delivered_at``, ``break_in_ends_at`` and ``trial_ends_at`` are all pinned.
    """
    model = model or create_model(**(model_overrides or {}))
    customer = customer or create_customer_row(**(customer_overrides or {}))
    customer_headers = make_customer_headers(customer["id"])

    payload = trial_order_payload(customer["id"], model["id"])
    payload["gross_price_cents"] = model["list_price_cents"]
    payload.update(order_overrides or {})
    order = get_success_data(api_client.create_trial_order(payload, AGENT))

    if delivered_at:
        set_clock(delivered_at)
    if dispatch:
        order = get_success_data(api_client.dispatch_trial_order(order["id"], {}, LOGISTICS))
    if deliver:
        order = get_success_data(api_client.deliver_trial_order(order["id"], {}, LOGISTICS))

    return {
        "model": model,
        "customer": customer,
        "customer_headers": customer_headers,
        "order": order,
    }


def add_order_for_customer(
    customer: dict,
    model: dict,
    order_overrides=None,
    delivered_at=None,
    dispatch=True,
    deliver=True,
) -> dict:
    """A second (or third) order for an existing customer, optionally delivered."""
    payload = trial_order_payload(customer["id"], model["id"])
    payload["gross_price_cents"] = model["list_price_cents"]
    payload.update(order_overrides or {})
    order = get_success_data(api_client.create_trial_order(payload, AGENT))
    if delivered_at:
        set_clock(delivered_at)
    if dispatch:
        order = get_success_data(api_client.dispatch_trial_order(order["id"], {}, LOGISTICS))
    if deliver:
        order = get_success_data(api_client.deliver_trial_order(order["id"], {}, LOGISTICS))
    return order


def preload_abuse_signals(customer_id: str, signals) -> list:
    """Record backdated abuse signals for a customer (PRD §3.2).

    ``signals`` is a sequence of ``(signal_type, recorded_at)`` pairs; a
    ``recorded_at`` of ``None`` lets the server stamp the current clock.
    """
    created = []
    for signal_type, recorded_at in signals:
        payload = trial_abuse_signal_payload(customer_id, signal_type)
        if recorded_at is not None:
            payload["recorded_at"] = recorded_at
        created.append(
            get_success_data(api_client.create_trial_abuse_signal(payload, ADMIN))
        )
    return created


# ---------------------------------------------------------------------------
# Tier 3 — the return lifecycle (PRD §3.6 through §3.9)
# ---------------------------------------------------------------------------


def open_return_case(order_id: str, customer_headers: dict, reason_code="COMFORT",
                     requested_at=None) -> dict:
    if requested_at:
        set_clock(requested_at)
    return get_success_data(
        api_client.create_return_case(
            return_case_payload(order_id, reason_code), customer_headers
        )
    )


def setup_published_route(**overrides) -> dict:
    """A PickupRoute carried from DRAFT to PUBLISHED (PRD §3.7)."""
    route = get_success_data(
        api_client.create_pickup_route(pickup_route_payload(**overrides), LOGISTICS)
    )
    route = get_success_data(api_client.publish_pickup_route(route["id"], {}, LOGISTICS))
    return route


def book_appointment(route_id: str, return_case_id: str, slot_start_at=None,
                     slot_end_at=None, expected_version=None) -> dict:
    """Book a slot, reading the route's current version when none is supplied."""
    if expected_version is None:
        expected_version = read_route(route_id)["version"]
    payload = pickup_appointment_payload(route_id, return_case_id, expected_version)
    if slot_start_at:
        payload["slot_start_at"] = slot_start_at
    if slot_end_at:
        payload["slot_end_at"] = slot_end_at
    return get_success_data(
        api_client.create_pickup_appointment(payload, LOGISTICS), expected_status=201
    )


def complete_appointment(appointment_id: str, outcome="COMPLETED", at=None) -> dict:
    if at:
        set_clock(at)
    return get_success_data(
        api_client.complete_pickup_appointment(
            appointment_id, complete_appointment_payload(outcome), LOGISTICS
        )
    )


def inspect_return(return_case_id: str, condition_grade="A", soil_flag=False,
                   accessory_returned=False) -> dict:
    return get_success_data(
        api_client.inspect_return_case(
            return_case_id,
            inspect_payload(condition_grade, soil_flag, accessory_returned),
            LOGISTICS,
        )
    )


def disposition_return(return_case_id: str, disposition="DONATION",
                       intake_date=TEST_DEFAULTS["INTAKE_DATE"]) -> dict:
    return get_success_data(
        api_client.disposition_return_case(
            return_case_id, disposition_payload(disposition, intake_date), LOGISTICS
        )
    )


def confirm_assignment_intake(assignment_id: str, outcome="DELIVERED") -> dict:
    return get_success_data(
        api_client.confirm_intake(
            assignment_id, confirm_intake_payload(outcome), LOGISTICS
        )
    )


def authorize_refund(return_case_id: str, headers=AUTHORIZER, expected_version=None,
                     supersedes_refund_id=None) -> dict:
    if expected_version is None:
        expected_version = read_return_case(return_case_id)["version"]
    payload = refund_authorization_payload(return_case_id, expected_version)
    if supersedes_refund_id is not None:
        payload["supersedes_refund_id"] = supersedes_refund_id
    return get_success_data(
        api_client.create_refund_authorization(payload, headers), expected_status=201
    )


def release_refund(refund_id: str, headers=RELEASER) -> dict:
    return get_success_data(api_client.release_refund(refund_id, {}, headers))


def void_refund(refund_id: str, headers=RELEASER, void_reason=None) -> dict:
    payload = void_refund_payload() if void_reason is None else void_refund_payload(void_reason)
    return get_success_data(api_client.void_refund(refund_id, payload, headers))


_STAGES = (
    "REQUESTED",
    "PICKUP_SCHEDULED",
    "PICKED_UP",
    "INSPECTED",
    "DISPOSITIONED",
    "INTAKE_CONFIRMED",
    "AUTHORIZED",
    "RELEASED",
)


def _stage_reached(stage: str, target: str) -> bool:
    return _STAGES.index(target) >= _STAGES.index(stage)


def setup_return_lifecycle(
    stage="AUTHORIZED",
    model_overrides=None,
    bundle_overrides=None,
    customer_overrides=None,
    order_overrides=None,
    partner_specs=None,
    delivered_at=TEST_DEFAULTS["DELIVERY_CLOCK"],
    requested_at=TEST_DEFAULTS["RETURN_REQUEST_CLOCK"],
    reason_code="COMFORT",
    route_overrides=None,
    slot_start_at=TEST_DEFAULTS["SLOT_START_AT"],
    slot_end_at=TEST_DEFAULTS["SLOT_END_AT"],
    pickup_at=TEST_DEFAULTS["PICKUP_CLOCK"],
    condition_grade="A",
    soil_flag=False,
    accessory_returned=False,
    disposition="DONATION",
    intake_date=TEST_DEFAULTS["INTAKE_DATE"],
    intake_outcome="DELIVERED",
    authorizer_headers=AUTHORIZER,
    releaser_headers=RELEASER,
) -> dict:
    """Drive one order through the whole return chain up to ``stage``.

    The default shape is the recipe reused by most of the money rules: a QUEEN
    model at 120000 cents delivered 2026-08-01, returned 2026-09-10, collected
    2026-09-15 (45 nights of use), inspected grade A and unsoiled, donated with
    intake on 2026-09-16 and authorized by ``fin-authorizer-1``.
    """
    assert stage in _STAGES, f"unknown lifecycle stage {stage!r}"

    bundle = create_bundle(**bundle_overrides) if bundle_overrides is not None else None
    partners = [create_disposition_partner_row(**spec) for spec in (partner_specs or [])]
    if not partners and partner_specs is None:
        partners = [create_charity()]

    order_extras = dict(order_overrides or {})
    if bundle is not None:
        order_extras.setdefault("bundle_id", bundle["id"])

    scenario = setup_delivered_order(
        model_overrides=model_overrides,
        customer_overrides=customer_overrides,
        order_overrides=order_extras,
        delivered_at=delivered_at,
    )
    scenario["bundle"] = bundle
    scenario["partners"] = partners

    return_case = open_return_case(
        scenario["order"]["id"],
        scenario["customer_headers"],
        reason_code=reason_code,
        requested_at=requested_at,
    )
    scenario["return_case"] = return_case
    if not _stage_reached("PICKUP_SCHEDULED", stage):
        return scenario

    route = setup_published_route(**(route_overrides or {}))
    scenario["route"] = route
    appointment = book_appointment(
        route["id"], return_case["id"], slot_start_at, slot_end_at
    )
    scenario["appointment"] = appointment
    if not _stage_reached("PICKED_UP", stage):
        return scenario

    scenario["appointment"] = complete_appointment(
        appointment["id"], "COMPLETED", at=pickup_at
    )
    if not _stage_reached("INSPECTED", stage):
        return scenario

    scenario["return_case"] = inspect_return(
        return_case["id"], condition_grade, soil_flag, accessory_returned
    )
    if not _stage_reached("DISPOSITIONED", stage):
        return scenario

    assignment = disposition_return(return_case["id"], disposition, intake_date)
    scenario["assignment"] = assignment
    scenario["return_case"] = read_return_case(return_case["id"])
    if not _stage_reached("INTAKE_CONFIRMED", stage):
        return scenario

    scenario["assignment"] = confirm_assignment_intake(assignment["id"], intake_outcome)
    if not _stage_reached("AUTHORIZED", stage):
        return scenario

    refund = authorize_refund(return_case["id"], headers=authorizer_headers)
    scenario["refund"] = refund
    scenario["return_case"] = read_return_case(return_case["id"])
    if not _stage_reached("RELEASED", stage):
        return scenario

    scenario["refund"] = release_refund(refund["id"], headers=releaser_headers)
    scenario["return_case"] = read_return_case(return_case["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — quality claims and comfort exchanges (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


def file_quality_claim(order_id: str, claim_type: str, photo_evidence_count: int,
                       headers=None, **extras) -> dict:
    payload = quality_claim_payload(order_id, claim_type, photo_evidence_count, **extras)
    return get_success_data(
        api_client.create_quality_claim(payload, headers or AGENT), expected_status=201
    )


def adjudicate_claim(claim_id: str, resolution: str, headers=APPROVING_AGENT) -> dict:
    return get_success_data(
        api_client.adjudicate_quality_claim(claim_id, adjudicate_payload(resolution), headers)
    )


def request_evidence(claim_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.request_claim_evidence(claim_id, {}, headers or AGENT)
    )


def request_comfort_exchange(original_order_id: str, target_model_id: str,
                             headers=None) -> dict:
    return get_success_data(
        api_client.create_comfort_exchange(
            comfort_exchange_payload(original_order_id, target_model_id),
            headers or AGENT,
        ),
        expected_status=201,
    )


def approve_comfort_exchange(exchange_id: str, order_id: str, headers=None) -> dict:
    expected_version = read_order(order_id)["version"]
    return get_success_data(
        api_client.approve_comfort_exchange(
            exchange_id, approve_exchange_payload(expected_version), headers or AGENT
        )
    )


def setup_order_in_trial_active(model_overrides=None, customer_overrides=None,
                                order_overrides=None,
                                delivered_at=TEST_DEFAULTS["DELIVERY_CLOCK"],
                                active_at="2026-09-01T00:00:00Z") -> dict:
    """A delivered order whose break-in window has already elapsed (PRD §3.3)."""
    scenario = setup_delivered_order(
        model_overrides=model_overrides,
        customer_overrides=customer_overrides,
        order_overrides=order_overrides,
        delivered_at=delivered_at,
    )
    set_clock(active_at)
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 5 — retail partner attribution (PRD §3.10)
# ---------------------------------------------------------------------------


def setup_partner_channel_order(partner_overrides=None, model_overrides=None,
                                customer_overrides=None, order_overrides=None,
                                delivered_at=TEST_DEFAULTS["DELIVERY_CLOCK"]) -> dict:
    """A RETAIL_PARTNER-channel order delivered and attributable to its partner."""
    partner = create_retail_partner_row(**(partner_overrides or {}))
    extras = dict(order_overrides or {})
    extras.setdefault("channel", "RETAIL_PARTNER")
    extras.setdefault("retail_partner_id", partner["id"])
    scenario = setup_delivered_order(
        model_overrides=model_overrides,
        customer_overrides=customer_overrides,
        order_overrides=extras,
        delivered_at=delivered_at,
    )
    scenario["partner"] = partner
    scenario["partner_headers"] = make_retail_partner_headers(partner["id"])
    return scenario


def file_attribution_claim(partner: dict, order_id: str, claim_type: str,
                           evidence_url_count=2, headers=None, **extras) -> dict:
    payload = attribution_claim_payload(
        partner["id"], order_id, claim_type, evidence_url_count, **extras
    )
    return get_success_data(
        api_client.create_attribution_claim(
            payload, headers or make_retail_partner_headers(partner["id"])
        ),
        expected_status=201,
    )


def accept_attribution_for_review(claim_id: str, headers=FINANCE) -> dict:
    return get_success_data(
        api_client.review_attribution_claim(
            claim_id, review_attribution_payload("ACCEPT_FOR_REVIEW"), headers
        )
    )
