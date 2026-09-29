"""Composite state builders.

The harness restarts the API server before every individual test, so every test
starts from an empty database. Nothing here assumes pre-existing rows: each
builder constructs the state it needs from scratch, through the endpoints of PRD
section 4 only, and returns the rows the API minted so a test can thread the
real identifiers into the calls it is exercising.

For the three entity-backed roles of PRD 2.1 the builders always derive headers
from the identifier of the row that was created — a `Customer` caller acts under
its own `Customer.id`, a `PartnerManager` under its `DeliveryPartner.id` and a
`Courier` under its `Courier.id` — because ownership is enforced by comparing
`X-User-ID` to a foreign key on the addressed resource.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    CAPTURE_PHOTO_HANDOFF,
    CAPTURE_PHOTO_ID,
    CAPTURE_SIGNATURE,
    CASE_DECISION_SUBSTANTIATED,
    CLEARANCE_DECISION_CLEAR,
    DRY_STATUS_WET,
    RESTRICTION_ALCOHOL,
    REVIEW_DECISION_ACCEPT,
    SEVERITY_MAJOR,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_A_HEADERS,
    make_courier_headers,
    make_customer_headers,
    make_partner_manager_headers,
)

# ---------------------------------------------------------------------------
# Reference instants used by the composite builders
# ---------------------------------------------------------------------------
CLOCK_AUGUST_20_NOON = "2026-08-20T12:00:00Z"
DELIVERY_AUGUST_20_EVENING = "2026-08-20T18:00:00Z"


# ===========================================================================
# Tier 1: one call each
# ===========================================================================
def set_clock(api, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock, which also runs the epoch sweep of PRD 2.5."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN_HEADERS))


def create_jurisdiction(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(f.jurisdiction_payload(**overrides), ADMIN_HEADERS)
    )


def create_policy(api, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_restriction_policy(
            f.restriction_policy_payload(jurisdiction_id, **overrides), ADMIN_HEADERS
        )
    )


def create_product(api, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_product(payload, ADMIN_HEADERS))


def create_customer(api, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer(f.customer_payload(jurisdiction_id, **overrides), ADMIN_HEADERS)
    )


def attest_customer(api, customer_id: str, attested_dob: str = f.ADULT_DOB, **overrides: Any):
    """The customer's own act (PRD 3.2), so it runs under that customer's headers."""
    return get_success_data(
        api.record_age_attestation(
            customer_id,
            f.attestation_payload(attested_dob, **overrides),
            make_customer_headers(customer_id),
        )
    )


def read_customer(api, customer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_customer(customer_id, ADMIN_HEADERS))


def add_identity_check(api, customer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Runs a pre-verification, reading the customer's current `version` first."""
    current = read_customer(api, customer_id)
    payload = f.identity_check_payload(current["version"], **overrides)
    return get_success_data(api.create_identity_check(customer_id, payload, ADMIN_HEADERS))


def create_partner(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_partner(f.delivery_partner_payload(**overrides), ADMIN_HEADERS)
    )


def create_courier(api, delivery_partner_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_courier(
            f.courier_payload(delivery_partner_id, **overrides),
            make_partner_manager_headers(delivery_partner_id),
        )
    )


def issue_certification(
    api, courier: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_courier_certification(
            f.courier_certification_payload(courier["id"], **overrides),
            make_partner_manager_headers(courier["delivery_partner_id"]),
        )
    )


def create_order(
    api,
    customer_id: str,
    delivery_jurisdiction_id: str,
    delivery_partner_id: str,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_order(
            f.order_payload(
                customer_id,
                delivery_jurisdiction_id,
                delivery_partner_id,
                scheduled_delivery_at,
                delivery_fee_cents,
                **overrides,
            ),
            make_customer_headers(customer_id),
        )
    )


def add_line(api, order: Dict[str, Any], product_id: str, quantity: int = 1) -> Dict[str, Any]:
    return get_success_data(
        api.create_order_line(
            order["id"],
            f.order_line_payload(product_id, quantity),
            make_customer_headers(order["customer_id"]),
        )
    )


def submit_order(api, order: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.submit_order(order["id"], make_customer_headers(order["customer_id"]))
    )


def dispatch_order(api, order: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.dispatch_order(
            order["id"], make_partner_manager_headers(order["delivery_partner_id"])
        )
    )


def clear_order(api, order_id: str, decision: str = CLEARANCE_DECISION_CLEAR) -> Dict[str, Any]:
    return get_success_data(
        api.record_clearance(order_id, f.clearance_payload(decision), OFFICER_A_HEADERS)
    )


def open_attempt(
    api,
    order: Dict[str, Any],
    courier: Dict[str, Any],
    started_at: str = DELIVERY_AUGUST_20_EVENING,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_attempt(
            f.delivery_attempt_payload(order["id"], courier["id"], started_at),
            make_courier_headers(courier["id"]),
        )
    )


def record_id_check(
    api, attempt: Dict[str, Any], courier_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_id_check(
            attempt["id"], f.id_check_payload(**overrides), make_courier_headers(courier_id)
        )
    )


def add_capture(
    api, attempt: Dict[str, Any], courier_id: str, kind: str, content_hash: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_capture(
            attempt["id"],
            f.capture_payload(kind=kind, content_hash=content_hash, **overrides),
            make_courier_headers(courier_id),
        )
    )


def add_mandatory_captures(
    api, attempt: Dict[str, Any], courier_id: str, include_photo_id: bool = True
) -> List[Dict[str, Any]]:
    """The signature and handoff photo every handover needs, plus the scan photo."""
    captures = [
        add_capture(api, attempt, courier_id, CAPTURE_SIGNATURE, f.SIGNATURE_HASH),
        add_capture(api, attempt, courier_id, CAPTURE_PHOTO_HANDOFF, f.PHOTO_HANDOFF_HASH),
    ]
    if include_photo_id:
        captures.append(
            add_capture(api, attempt, courier_id, CAPTURE_PHOTO_ID, f.PHOTO_ID_HASH)
        )
    return captures


def record_handover(api, attempt: Dict[str, Any], courier_id: str, **overrides: Any):
    return get_success_data(
        api.record_handover(
            attempt["id"], f.handover_payload(**overrides), make_courier_headers(courier_id)
        )
    )


def record_refusal(
    api, attempt: Dict[str, Any], courier_id: str, refusal_reason: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_refusal(
            attempt["id"],
            f.refusal_payload(refusal_reason, **overrides),
            make_courier_headers(courier_id),
        )
    )


def settle_return(api, order_id: str, restock_confirmed: bool = True) -> Dict[str, Any]:
    return get_success_data(
        api.create_return_settlement(
            order_id, f.return_settlement_payload(restock_confirmed), ADMIN_HEADERS
        )
    )


def schedule_shopper_test(
    api, courier_id: str, order_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_secret_shopper_test(
            f.secret_shopper_test_payload(courier_id, order_id, **overrides), AUDITOR_HEADERS
        )
    )


def record_shopper_outcome(
    api, test_id: str, observed_outcome: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_shopper_outcome(
            test_id, f.shopper_outcome_payload(observed_outcome, **overrides), AUDITOR_HEADERS
        )
    )


def read_order(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, ADMIN_HEADERS))


def read_partner(api, partner_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_partner(partner_id, ADMIN_HEADERS))


def read_courier(api, courier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_courier(courier_id, ADMIN_HEADERS))


def read_attempt(api, attempt_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_attempt(attempt_id, ADMIN_HEADERS))


def read_case(api, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_violation_case(case_id, ADMIN_HEADERS))


def read_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_corrective_action_plan(plan_id, ADMIN_HEADERS))


def read_certification(api, certification_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_courier_certification(certification_id, ADMIN_HEADERS))


# ===========================================================================
# Case and plan chains (PRD 3.9)
# ===========================================================================
def open_manual_case(
    api,
    delivery_partner_id: str,
    delivery_attempt_id: Optional[str] = None,
    secret_shopper_test_id: Optional[str] = None,
    severity: str = SEVERITY_MAJOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_violation_case(
            f.violation_case_payload(
                delivery_partner_id,
                delivery_attempt_id=delivery_attempt_id,
                secret_shopper_test_id=secret_shopper_test_id,
                severity=severity,
                **overrides,
            ),
            OFFICER_A_HEADERS,
        )
    )


def investigate_case(api, case_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.investigate_case(case_id, headers or OFFICER_A_HEADERS))


def decide_case(
    api,
    case_id: str,
    decision: str = CASE_DECISION_SUBSTANTIATED,
    assessed_severity: Optional[str] = SEVERITY_MAJOR,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.case_decision_payload(
        decision,
        assessed_severity if decision == CASE_DECISION_SUBSTANTIATED else None,
    )
    return get_success_data(
        api.decide_case(case_id, payload, headers or OFFICER_A_HEADERS)
    )


def build_substantiated_case(
    api,
    delivery_partner_id: str,
    delivery_attempt_id: Optional[str] = None,
    secret_shopper_test_id: Optional[str] = None,
    severity: str = SEVERITY_MAJOR,
    assessed_severity: Optional[str] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Manual case walked OPEN -> UNDER_INVESTIGATION -> SUBSTANTIATED."""
    headers = officer_headers or OFFICER_A_HEADERS
    case = open_manual_case(
        api,
        delivery_partner_id,
        delivery_attempt_id=delivery_attempt_id,
        secret_shopper_test_id=secret_shopper_test_id,
        severity=severity,
    )
    investigate_case(api, case["id"], headers)
    return decide_case(
        api,
        case["id"],
        CASE_DECISION_SUBSTANTIATED,
        assessed_severity or severity,
        headers,
    )


def file_plan(
    api, case: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Files a corrective action plan, reading the case's current `version` first."""
    current = read_case(api, case["id"])
    return get_success_data(
        api.create_corrective_action_plan(
            case["id"],
            f.corrective_action_plan_payload(current["version"], **overrides),
            make_partner_manager_headers(current["delivery_partner_id"]),
        )
    )


def review_plan(
    api,
    plan_id: str,
    decision: str = REVIEW_DECISION_ACCEPT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_corrective_action_plan(
            plan_id, f.plan_review_payload(decision), headers or OFFICER_A_HEADERS
        )
    )


def resubmit_plan(
    api, plan: Dict[str, Any], delivery_partner_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_corrective_action_plan(
            plan["id"],
            f.plan_resubmit_payload(**overrides),
            make_partner_manager_headers(delivery_partner_id),
        )
    )


def verify_plan(
    api, plan_id: str, verification_outcome: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.verify_corrective_action_plan(
            plan_id, f.plan_verify_payload(verification_outcome), headers or OFFICER_A_HEADERS
        )
    )


# ===========================================================================
# Tier 4: whole-world skeletons
# ===========================================================================
def build_unrestricted_world(
    api,
    clock: str = CLOCK_AUGUST_20_NOON,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    quantity: int = 4,
    delivery_fee_cents: int = 600,
) -> Dict[str, Any]:
    """A world whose only product is classified `NONE`.

    Such an order takes the unrestricted shortcut of PRD 3.3: it needs no
    attestation, no pre-verification and no policy, so the world stops short of
    publishing one.
    """
    set_clock(api, clock)
    jurisdiction = create_jurisdiction(
        api, code="US-NY", name="New York State", dry_status=DRY_STATUS_WET, utc_offset_minutes=-240
    )
    grocery = create_product(api, f.grocery_product_payload())
    customer = create_customer(api, jurisdiction["id"])
    partner = create_partner(api, license_reference="NY-DEL-0001")
    courier = create_courier(api, partner["id"])
    certification = issue_certification(api, courier)
    order = create_order(
        api,
        customer["id"],
        jurisdiction["id"],
        partner["id"],
        scheduled_delivery_at,
        delivery_fee_cents,
    )
    line = add_line(api, order, grocery["id"], quantity)
    return {
        "jurisdiction": jurisdiction,
        "grocery": grocery,
        "customer": customer,
        "partner": partner,
        "courier": courier,
        "certification": certification,
        "order": order,
        "line": line,
        "clock": clock,
        "scheduled_delivery_at": scheduled_delivery_at,
        "customer_headers": make_customer_headers(customer["id"]),
        "partner_headers": make_partner_manager_headers(partner["id"]),
        "courier_headers": make_courier_headers(courier["id"]),
    }


def build_restricted_world(
    api,
    clock: str = CLOCK_AUGUST_20_NOON,
    dry_status: str = DRY_STATUS_WET,
    utc_offset_minutes: int = -240,
    jurisdiction_code: str = "US-NY",
    attested_dob: str = f.ADULT_DOB,
    policy_overrides: Optional[Dict[str, Any]] = None,
    with_identity_check: bool = True,
    identity_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A world in which one `ALCOHOL` policy governs and the purchaser is cleared.

    The purchaser attests an adult date of birth and carries one `VALID`
    identity pre-verification whose confidence bands as `MATCH`, so an order in
    this world routes to `PREVERIFIED` once the rest of the battery passes.
    """
    set_clock(api, clock)
    jurisdiction = create_jurisdiction(
        api,
        code=jurisdiction_code,
        name="New York State",
        dry_status=dry_status,
        utc_offset_minutes=utc_offset_minutes,
    )
    policy = create_policy(api, jurisdiction["id"], **(policy_overrides or {}))
    wine = create_product(api, f.wine_product_payload())
    customer = create_customer(api, jurisdiction["id"])
    attest_customer(api, customer["id"], attested_dob)
    identity_check = None
    if with_identity_check:
        identity_check = add_identity_check(
            api,
            customer["id"],
            provided_dob=attested_dob,
            source_dob=attested_dob,
            **(identity_overrides or {}),
        )
    partner = create_partner(api, license_reference="NY-DEL-0001")
    courier = create_courier(api, partner["id"])
    certification = issue_certification(api, courier)
    return {
        "jurisdiction": jurisdiction,
        "policy": policy,
        "wine": wine,
        "customer": read_customer(api, customer["id"]),
        "identity_check": identity_check,
        "partner": partner,
        "courier": courier,
        "certification": certification,
        "clock": clock,
        "attested_dob": attested_dob,
        "customer_headers": make_customer_headers(customer["id"]),
        "partner_headers": make_partner_manager_headers(partner["id"]),
        "courier_headers": make_courier_headers(courier["id"]),
    }


def add_restricted_order(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
    product: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Opens an order in a restricted world and puts one restricted line on it."""
    order = create_order(
        api,
        world["customer"]["id"],
        world["jurisdiction"]["id"],
        world["partner"]["id"],
        scheduled_delivery_at,
        delivery_fee_cents,
    )
    line = add_line(api, order, (product or world["wine"])["id"], quantity)
    return {"order": order, "line": line}


def build_submitted_restricted_order(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
) -> Dict[str, Any]:
    """A restricted order carried through the order-time battery of PRD 3.3."""
    built = add_restricted_order(
        api, world, quantity, scheduled_delivery_at, delivery_fee_cents
    )
    submitted = submit_order(api, built["order"])
    return {"order": submitted, "line": built["line"]}


def build_dispatched_restricted_order(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
) -> Dict[str, Any]:
    """A submitted restricted order the partner has accepted for carriage."""
    built = build_submitted_restricted_order(
        api, world, quantity, scheduled_delivery_at, delivery_fee_cents
    )
    dispatched = dispatch_order(api, built["order"])
    return {"order": dispatched, "line": built["line"]}


def build_open_attempt(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    started_at: str = DELIVERY_AUGUST_20_EVENING,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
) -> Dict[str, Any]:
    """A dispatched restricted order with the courier standing at the door."""
    built = build_dispatched_restricted_order(
        api, world, quantity, scheduled_delivery_at, delivery_fee_cents
    )
    attempt = open_attempt(api, built["order"], world["courier"], started_at)
    return {"order": built["order"], "line": built["line"], "attempt": attempt}


def build_id_verified_attempt(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    started_at: str = DELIVERY_AUGUST_20_EVENING,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
    **id_check_overrides: Any,
) -> Dict[str, Any]:
    """An attempt whose door-side check passed the document sub-order and the age fork."""
    built = build_open_attempt(
        api, world, quantity, started_at, scheduled_delivery_at, delivery_fee_cents
    )
    verified = record_id_check(
        api,
        built["attempt"],
        world["courier"]["id"],
        scanned_dob=world["attested_dob"],
        **id_check_overrides,
    )
    built["attempt"] = verified
    return built


def build_delivered_order(
    api,
    world: Dict[str, Any],
    quantity: int = 2,
    started_at: str = DELIVERY_AUGUST_20_EVENING,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
) -> Dict[str, Any]:
    """A restricted order carried all the way to `DELIVERED` through a handover."""
    built = build_id_verified_attempt(
        api, world, quantity, started_at, scheduled_delivery_at, delivery_fee_cents
    )
    add_mandatory_captures(api, built["attempt"], world["courier"]["id"])
    record_handover(api, built["attempt"], world["courier"]["id"])
    built["order"] = read_order(api, built["order"]["id"])
    built["attempt"] = read_attempt(api, built["attempt"]["id"])
    return built


def build_returning_order(
    api,
    world: Dict[str, Any],
    refusal_reason: str,
    quantity: int = 3,
    started_at: str = DELIVERY_AUGUST_20_EVENING,
    scheduled_delivery_at: str = DELIVERY_AUGUST_20_EVENING,
    delivery_fee_cents: int = 600,
    from_id_verified: bool = True,
) -> Dict[str, Any]:
    """A restricted order refused at the door and therefore `RETURN_IN_TRANSIT`."""
    if from_id_verified:
        built = build_id_verified_attempt(
            api, world, quantity, started_at, scheduled_delivery_at, delivery_fee_cents
        )
    else:
        built = build_open_attempt(
            api, world, quantity, started_at, scheduled_delivery_at, delivery_fee_cents
        )
    refused = record_refusal(api, built["attempt"], world["courier"]["id"], refusal_reason)
    built["attempt"] = refused
    built["order"] = read_order(api, built["order"]["id"])
    return built


def build_accepted_plan(
    api,
    case: Dict[str, Any],
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A plan filed against a substantiated case and accepted on first review."""
    plan = file_plan(api, case)
    return review_plan(api, plan["id"], REVIEW_DECISION_ACCEPT, reviewer_headers)
