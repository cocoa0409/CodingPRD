"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls go
through the lenient `get_success_data` validator so a broken precondition
surfaces as a setup failure rather than a confusing assertion.

Naming: the "primitives" section wraps one endpoint each; the sections after it
compose those primitives into the states the interesting rules need.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADMIN_ROOT,
    CO_ALPHA,
    CO_BRAVO,
    FO_ONE,
    WORKING_TUESDAY_10AM,
)
from .factories import (
    apply_substitution_payload,
    create_auto_reorder_schedule_payload,
    create_customer_payload,
    create_doctor_lookup_prescription_payload,
    create_insurance_plan_payload,
    create_lens_equivalence_payload,
    create_order_payload,
    create_prescriber_payload,
    create_prescription_payload,
    create_product_payload,
    create_reimbursement_claim_payload,
    create_reorder_hold_payload,
    create_return_request_payload,
    create_self_report_prescription_payload,
    file_prescriber_dispute_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    CO_ALPHA_HEADERS,
    CO_BRAVO_HEADERS,
    FO_HEADERS,
    make_compliance_headers,
    make_customer_headers,
    make_fulfillment_headers,
    make_prescriber_headers,
)

# ==========================================================================
# Primitives — one endpoint each
# ==========================================================================


def set_clock(current_utc: str) -> dict:
    """Pin the logical clock. Every deadline and window comparison reads it."""
    return get_success_data(api_client.set_logical_clock(current_utc, ADMIN_HEADERS))


def read_clock() -> dict:
    return get_success_data(api_client.read_logical_clock(ADMIN_HEADERS))


def new_insurance_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_plan(
            create_insurance_plan_payload(**overrides), ADMIN_HEADERS
        )
    )


def retire_insurance_plan(plan_id: str) -> dict:
    return get_success_data(api_client.retire_insurance_plan(plan_id, ADMIN_HEADERS))


def new_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN_HEADERS)
    )


def deactivate_product(product_id: str) -> dict:
    return get_success_data(api_client.deactivate_product(product_id, ADMIN_HEADERS))


def new_lens_equivalence(from_product_id: str, to_product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lens_equivalence(
            from_product_id,
            create_lens_equivalence_payload(to_product_id, **overrides),
            ADMIN_HEADERS,
        )
    )


def new_prescriber(**overrides) -> dict:
    return get_success_data(
        api_client.create_prescriber(
            create_prescriber_payload(**overrides), ADMIN_HEADERS
        )
    )


def suspend_prescriber(prescriber_id: str) -> dict:
    return get_success_data(api_client.suspend_prescriber(prescriber_id, ADMIN_HEADERS))


def new_customer(insurance_plan_id=None, **overrides) -> dict:
    payload = create_customer_payload(**overrides)
    if insurance_plan_id is not None:
        payload["insurance_plan_id"] = insurance_plan_id
    return get_success_data(api_client.create_customer(payload, ADMIN_HEADERS))


def get_ledger(customer_id: str) -> dict:
    """Reconciled ledger read, performed by the owning customer."""
    return get_success_data(
        api_client.get_customer_ledger(customer_id, make_customer_headers(customer_id))
    )


def new_prescription(customer_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prescription(
            create_prescription_payload(customer_id, product_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def new_doctor_lookup_prescription(
    customer_id: str, product_id: str, prescriber_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_prescription(
            create_doctor_lookup_prescription_payload(
                customer_id, product_id, prescriber_id, **overrides
            ),
            make_customer_headers(customer_id),
        )
    )


def new_self_report_prescription(customer_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prescription(
            create_self_report_prescription_payload(
                customer_id, product_id, **overrides
            ),
            make_customer_headers(customer_id),
        )
    )


def submit_prescription(prescription_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.submit_prescription(
            prescription_id, make_customer_headers(customer_id)
        )
    )


def read_prescription(prescription_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_prescription(prescription_id, headers or ADMIN_HEADERS)
    )


def invalidate_prescription(prescription_id: str, reason="manual review", actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.invalidate_prescription(
            prescription_id, {"reason": reason}, make_compliance_headers(actor)
        )
    )


def send_verification_request(prescription_id: str, prescriber_id: str, actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.send_verification_request(
            prescription_id,
            {"prescriber_id": prescriber_id},
            make_compliance_headers(actor),
        )
    )


def respond_to_verification_request(
    request_id: str, prescriber_id: str, response_type: str, **extra
) -> dict:
    payload = {"response_type": response_type}
    payload.update(extra)
    return get_success_data(
        api_client.respond_to_verification_request(
            request_id, payload, make_prescriber_headers(prescriber_id)
        )
    )


def run_verification_sweep(actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.run_verification_sweep(make_compliance_headers(actor))
    )


def new_order(
    customer_id: str,
    prescription_id: str,
    ordered_product_id: str,
    boxes_od: int = 1,
    boxes_os: int = 1,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(
                customer_id,
                prescription_id,
                ordered_product_id,
                boxes_od,
                boxes_os,
                **overrides,
            ),
            make_customer_headers(customer_id),
        )
    )


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_order(order_id, headers or ADMIN_HEADERS))


def ship_order(order_id: str, actor=FO_ONE) -> dict:
    return get_success_data(
        api_client.ship_order(order_id, make_fulfillment_headers(actor))
    )


def deliver_order(order_id: str, actor=FO_ONE) -> dict:
    return get_success_data(
        api_client.deliver_order(order_id, make_fulfillment_headers(actor))
    )


def cancel_order(order_id: str, customer_id: str, reason="CUSTOMER_REQUEST") -> dict:
    return get_success_data(
        api_client.cancel_order(
            order_id,
            {"cancellation_reason": reason},
            make_customer_headers(customer_id),
        )
    )


def apply_substitution(
    order_id: str, substitute_product_id: str, expected_order_version: int, **overrides
) -> dict:
    return get_success_data(
        api_client.apply_substitution(
            order_id,
            apply_substitution_payload(
                substitute_product_id, expected_order_version, **overrides
            ),
            FO_HEADERS,
        )
    )


def new_reorder_hold(customer_id: str, prescription_id: str, actor=CO_ALPHA, **overrides) -> dict:
    return get_success_data(
        api_client.create_reorder_hold(
            create_reorder_hold_payload(customer_id, prescription_id, **overrides),
            make_compliance_headers(actor),
        )
    )


def release_reorder_hold(hold_id: str, actor=CO_BRAVO, note="released") -> dict:
    return get_success_data(
        api_client.release_reorder_hold(
            hold_id, {"note": note}, make_compliance_headers(actor)
        )
    )


def escalate_reorder_hold(hold_id: str, actor=CO_BRAVO, escalated_reason="escalated") -> dict:
    return get_success_data(
        api_client.escalate_reorder_hold(
            hold_id,
            {"escalated_reason": escalated_reason},
            make_compliance_headers(actor),
        )
    )


def open_holds_for_customer(customer_id: str) -> list:
    data = get_success_data(
        api_client.list_reorder_holds(
            CO_ALPHA_HEADERS, params={"customer_id": customer_id, "status": "OPEN"}
        )
    )
    return data


def new_auto_reorder_schedule(
    customer_id: str, prescription_id: str, product_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_auto_reorder_schedule(
            create_auto_reorder_schedule_payload(
                customer_id, prescription_id, product_id, **overrides
            ),
            make_customer_headers(customer_id),
        )
    )


def pause_schedule(schedule_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.pause_auto_reorder_schedule(
            schedule_id, make_customer_headers(customer_id)
        )
    )


def resume_schedule(schedule_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.resume_auto_reorder_schedule(
            schedule_id, make_customer_headers(customer_id)
        )
    )


def cancel_schedule(schedule_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.cancel_auto_reorder_schedule(
            schedule_id, make_customer_headers(customer_id)
        )
    )


def run_auto_reorder(actor=FO_ONE) -> dict:
    return get_success_data(
        api_client.run_auto_reorder(make_fulfillment_headers(actor))
    )


def new_return_request(order_id: str, customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_return_request(
            create_return_request_payload(order_id, customer_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def approve_return_request(return_id: str, actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.approve_return_request(return_id, make_compliance_headers(actor))
    )


def settle_return_request(return_id: str, actor=CO_BRAVO) -> dict:
    return get_success_data(
        api_client.settle_return_request(return_id, make_compliance_headers(actor))
    )


def new_reimbursement_claim(order_id: str, customer_id: str, insurance_plan_id: str) -> dict:
    return get_success_data(
        api_client.create_reimbursement_claim(
            create_reimbursement_claim_payload(order_id, customer_id, insurance_plan_id),
            make_customer_headers(customer_id),
        )
    )


def generate_reimbursement_claim(claim_id: str, actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.generate_reimbursement_claim(claim_id, make_compliance_headers(actor))
    )


def submit_reimbursement_claim(claim_id: str, actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.submit_reimbursement_claim(claim_id, make_compliance_headers(actor))
    )


def void_reimbursement_claim(claim_id: str, voided_reason="CUSTOMER_REQUEST", actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.void_reimbursement_claim(
            claim_id, {"voided_reason": voided_reason}, make_compliance_headers(actor)
        )
    )


def prescription_version(prescription_id: str, prescriber_id: str) -> int:
    """Read the live Prescription version as the prescriber, for the optimistic
    concurrency token a dispute must carry."""
    data = get_success_data(
        api_client.get_prescription(
            prescription_id, make_prescriber_headers(prescriber_id)
        )
    )
    return data["version"]


def order_version(order_id: str) -> int:
    """Read the live Order version, for the substitution concurrency token."""
    return get_success_data(api_client.get_order(order_id, FO_HEADERS))["version"]


def file_prescriber_dispute(
    prescription_id: str, prescriber_id: str, expected_version=None, **overrides
) -> dict:
    if expected_version is None:
        expected_version = prescription_version(prescription_id, prescriber_id)
    return get_success_data(
        api_client.file_prescriber_dispute(
            file_prescriber_dispute_payload(
                prescription_id, prescriber_id, expected_version, **overrides
            ),
            make_prescriber_headers(prescriber_id),
        )
    )


def resolve_prescriber_dispute(dispute_id: str, resolution: str, actor=CO_ALPHA) -> dict:
    return get_success_data(
        api_client.resolve_prescriber_dispute(
            dispute_id, {"resolution": resolution}, make_compliance_headers(actor)
        )
    )


def compliance_events(prescription_id: str, limit: int = 100) -> list:
    """The whole append-only trail for one prescription, ordered by
    `occurred_at` ascending. The trail declares only `limit` and `offset`, so it
    is read in full and filtered in the caller."""
    return get_success_data(
        api_client.list_compliance_events_for_prescription(
            prescription_id, CO_ALPHA_HEADERS, params={"limit": limit}
        )
    )


def count_compliance_events(prescription_id: str, event_type: str) -> int:
    """How many events of one type the prescription's trail carries."""
    return sum(
        1
        for event in compliance_events(prescription_id)
        if event["event_type"] == event_type
    )


# ==========================================================================
# Tier 1 / 2 — reference data plus a prescription in a chosen lifecycle state
# ==========================================================================


def setup_reference_data(
    clock=WORKING_TUESDAY_10AM,
    with_plan=False,
    plan_overrides=None,
    product_overrides=None,
    customer_overrides=None,
    with_prescriber=False,
    prescriber_overrides=None,
) -> dict:
    """Clock + product + customer, optionally a plan and a prescriber.

    Returns a scenario dict whose keys are reused by every richer helper:
    `product`, `customer`, `customer_headers`, and optionally `plan` and
    `prescriber`.
    """
    if clock is not None:
        set_clock(clock)
    scenario = {}
    if with_plan:
        scenario["plan"] = new_insurance_plan(**(plan_overrides or {}))
    scenario["product"] = new_product(**(product_overrides or {}))
    if with_prescriber:
        scenario["prescriber"] = new_prescriber(**(prescriber_overrides or {}))
    plan_id = scenario["plan"]["id"] if with_plan else None
    scenario["customer"] = new_customer(
        insurance_plan_id=plan_id, **(customer_overrides or {})
    )
    scenario["customer_headers"] = make_customer_headers(scenario["customer"]["id"])
    return scenario


def setup_verified_prescription(
    clock=WORKING_TUESDAY_10AM,
    with_plan=False,
    plan_overrides=None,
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
) -> dict:
    """An UPLOAD prescription submitted straight through to VERIFIED_ACTIVE.

    Adds `prescription` to the scenario dict from `setup_reference_data`.
    """
    scenario = setup_reference_data(
        clock=clock,
        with_plan=with_plan,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
    )
    rx = new_prescription(
        scenario["customer"]["id"],
        scenario["product"]["id"],
        **(prescription_overrides or {}),
    )
    scenario["prescription"] = submit_prescription(rx["id"], scenario["customer"]["id"])
    return scenario


def setup_draft_prescription(
    clock=WORKING_TUESDAY_10AM,
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
) -> dict:
    """An UPLOAD prescription left in DRAFT, ready for a submit trigger."""
    scenario = setup_reference_data(
        clock=clock,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
    )
    scenario["prescription"] = new_prescription(
        scenario["customer"]["id"],
        scenario["product"]["id"],
        **(prescription_overrides or {}),
    )
    return scenario


def setup_pending_verification_prescription(
    clock=WORKING_TUESDAY_10AM,
    directory_verified=True,
    contact_channel="PORTAL",
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
    submit=True,
) -> dict:
    """A DOCTOR_LOOKUP prescription naming a directory-verified prescriber,
    submitted into PENDING_VERIFICATION. Adds `prescriber` and `prescription`.
    """
    scenario = setup_reference_data(
        clock=clock,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
        with_prescriber=True,
        prescriber_overrides={
            "directory_verified": directory_verified,
            "contact_channel": contact_channel,
        },
    )
    rx = new_doctor_lookup_prescription(
        scenario["customer"]["id"],
        scenario["product"]["id"],
        scenario["prescriber"]["id"],
        **(prescription_overrides or {}),
    )
    scenario["prescription"] = (
        submit_prescription(rx["id"], scenario["customer"]["id"]) if submit else rx
    )
    return scenario


def setup_verified_prescription_with_prescriber(
    clock=WORKING_TUESDAY_10AM,
    with_plan=False,
    plan_overrides=None,
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
) -> dict:
    """An UPLOAD prescription that names a prescriber, so the prescriber can file
    a dispute against a prescription that is already VERIFIED_ACTIVE."""
    scenario = setup_reference_data(
        clock=clock,
        with_plan=with_plan,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
        with_prescriber=True,
    )
    overrides = dict(prescription_overrides or {})
    overrides["prescriber_id"] = scenario["prescriber"]["id"]
    rx = new_prescription(
        scenario["customer"]["id"], scenario["product"]["id"], **overrides
    )
    scenario["prescription"] = submit_prescription(rx["id"], scenario["customer"]["id"])
    return scenario


def setup_verified_prescription_via_confirmed_round(
    clock=WORKING_TUESDAY_10AM,
    with_plan=False,
    plan_overrides=None,
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
) -> dict:
    """A DOCTOR_LOOKUP prescription promoted to VERIFIED_ACTIVE by a CONFIRMED
    prescriber response, so the prescription names a prescriber who can then
    file a dispute against it.

    Adds `prescriber`, `verification_request` and the VERIFIED_ACTIVE
    `prescription`.
    """
    scenario = setup_reference_data(
        clock=clock,
        with_plan=with_plan,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
        with_prescriber=True,
    )
    rx = new_doctor_lookup_prescription(
        scenario["customer"]["id"],
        scenario["product"]["id"],
        scenario["prescriber"]["id"],
        **(prescription_overrides or {}),
    )
    submit_prescription(rx["id"], scenario["customer"]["id"])
    scenario["verification_request"] = send_verification_request(
        rx["id"], scenario["prescriber"]["id"]
    )
    respond_to_verification_request(
        scenario["verification_request"]["id"],
        scenario["prescriber"]["id"],
        "CONFIRMED",
    )
    scenario["prescription"] = read_prescription(rx["id"])
    return scenario


def setup_verification_round(
    clock=WORKING_TUESDAY_10AM,
    directory_verified=True,
    contact_channel="PORTAL",
    capture_mode="DOCTOR_LOOKUP",
    prescription_overrides=None,
    product_overrides=None,
    actor=CO_ALPHA,
) -> dict:
    """A prescription in PENDING_VERIFICATION with one outstanding SENT round.

    Adds `verification_request` to the scenario dict.
    """
    if capture_mode == "DOCTOR_LOOKUP":
        scenario = setup_pending_verification_prescription(
            clock=clock,
            directory_verified=directory_verified,
            contact_channel=contact_channel,
            product_overrides=product_overrides,
            prescription_overrides=prescription_overrides,
        )
    else:
        scenario = setup_reference_data(
            clock=clock,
            product_overrides=product_overrides,
            with_prescriber=True,
            prescriber_overrides={
                "directory_verified": directory_verified,
                "contact_channel": contact_channel,
            },
        )
        rx = new_self_report_prescription(
            scenario["customer"]["id"],
            scenario["product"]["id"],
            **(prescription_overrides or {}),
        )
        scenario["prescription"] = submit_prescription(
            rx["id"], scenario["customer"]["id"]
        )
    scenario["verification_request"] = send_verification_request(
        scenario["prescription"]["id"], scenario["prescriber"]["id"], actor=actor
    )
    return scenario


# ==========================================================================
# Tier 3 — orders through the fulfillment lifecycle
# ==========================================================================


def setup_order_on_verified_prescription(
    boxes_od=1,
    boxes_os=1,
    clock=WORKING_TUESDAY_10AM,
    with_plan=False,
    plan_overrides=None,
    product_overrides=None,
    customer_overrides=None,
    prescription_overrides=None,
    order_overrides=None,
) -> dict:
    """A PENDING, RX_CLEARED order on a VERIFIED_ACTIVE prescription."""
    scenario = setup_verified_prescription(
        clock=clock,
        with_plan=with_plan,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
        customer_overrides=customer_overrides,
        prescription_overrides=prescription_overrides,
    )
    scenario["order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        boxes_od,
        boxes_os,
        **(order_overrides or {}),
    )
    return scenario


def setup_shipped_order(**kwargs) -> dict:
    """An order walked to SHIPPED."""
    scenario = setup_order_on_verified_prescription(**kwargs)
    scenario["order"] = ship_order(scenario["order"]["id"])
    return scenario


def setup_delivered_order(**kwargs) -> dict:
    """An order walked to DELIVERED, which anchors the claim window."""
    scenario = setup_shipped_order(**kwargs)
    scenario["order"] = deliver_order(scenario["order"]["id"])
    return scenario


def setup_delivered_order_with_draft_claim(
    boxes_od=1,
    boxes_os=1,
    clock=WORKING_TUESDAY_10AM,
    plan_overrides=None,
    product_overrides=None,
    prescription_overrides=None,
    order_overrides=None,
) -> dict:
    """A plan-covered delivered order carrying one DRAFT reimbursement claim."""
    scenario = setup_delivered_order(
        boxes_od=boxes_od,
        boxes_os=boxes_os,
        clock=clock,
        with_plan=True,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
        prescription_overrides=prescription_overrides,
        order_overrides=order_overrides,
    )
    scenario["claim"] = new_reimbursement_claim(
        scenario["order"]["id"], scenario["customer"]["id"], scenario["plan"]["id"]
    )
    return scenario


def setup_generated_claim(actor=CO_ALPHA, **kwargs) -> dict:
    """A claim taken through generation, so plan-year allowance is consumed."""
    scenario = setup_delivered_order_with_draft_claim(**kwargs)
    scenario["claim"] = generate_reimbursement_claim(scenario["claim"]["id"], actor=actor)
    return scenario


def setup_approved_return(
    reason="PRESCRIPTION_CHANGE",
    return_overrides=None,
    approver=CO_ALPHA,
    with_claim=False,
    **kwargs,
) -> dict:
    """A delivered order with one APPROVED return request awaiting settlement."""
    if with_claim:
        scenario = setup_delivered_order_with_draft_claim(**kwargs)
    else:
        scenario = setup_delivered_order(**kwargs)
    overrides = dict(return_overrides or {})
    overrides["reason"] = reason
    scenario["return_request"] = new_return_request(
        scenario["order"]["id"], scenario["customer"]["id"], **overrides
    )
    scenario["return_request"] = approve_return_request(
        scenario["return_request"]["id"], actor=approver
    )
    return scenario


# ==========================================================================
# Tier 4 — threshold and boundary targeting
# ==========================================================================


def setup_order_at_subtotal(subtotal_cents: int, unit_price_cents: int, **kwargs) -> dict:
    """Place an order whose subtotal lands exactly on `subtotal_cents`.

    Used for the free-shipping threshold, where the boxes count is derived from
    the unit price so the subtotal can be pinned to the exact value under test.
    """
    assert subtotal_cents % unit_price_cents == 0, (
        "subtotal_cents must be a whole multiple of unit_price_cents"
    )
    boxes = subtotal_cents // unit_price_cents
    product_overrides = dict(kwargs.pop("product_overrides", None) or {})
    product_overrides["unit_price_cents"] = unit_price_cents
    return setup_order_on_verified_prescription(
        boxes_od=boxes,
        boxes_os=0,
        product_overrides=product_overrides,
        **kwargs,
    )


def setup_substitution_candidates(
    substitutes,
    clock=WORKING_TUESDAY_10AM,
    boxes_od=1,
    boxes_os=1,
    product_overrides=None,
    prescription_overrides=None,
    equivalence_overrides=None,
) -> dict:
    """A PENDING order plus a set of substitute products already mapped to the
    ordered product by a lens equivalence.

    `substitutes` is a list of product-payload override dicts. The returned
    scenario adds `substitutes` (list of product dicts) and `equivalences`
    (list of equivalence dicts) in the same order.
    """
    scenario = setup_order_on_verified_prescription(
        boxes_od=boxes_od,
        boxes_os=boxes_os,
        clock=clock,
        product_overrides=product_overrides,
        prescription_overrides=prescription_overrides,
    )
    scenario["substitutes"] = []
    scenario["equivalences"] = []
    for index, spec in enumerate(substitutes):
        spec = dict(spec)
        equivalence_spec = dict(equivalence_overrides or {})
        equivalence_spec.update(spec.pop("equivalence", {}) or {})
        substitute = new_product(**spec)
        scenario["substitutes"].append(substitute)
        scenario["equivalences"].append(
            new_lens_equivalence(
                scenario["product"]["id"], substitute["id"], **equivalence_spec
            )
        )
        del index
    return scenario


def setup_allowance_partly_consumed(
    first_boxes=(1, 1),
    plan_overrides=None,
    product_overrides=None,
    clock=WORKING_TUESDAY_10AM,
) -> dict:
    """A plan-covered customer whose first delivered order already has a
    GENERATED claim, so the plan-year allowance is partly spent before the
    order under test is placed."""
    scenario = setup_generated_claim(
        boxes_od=first_boxes[0],
        boxes_os=first_boxes[1],
        clock=clock,
        plan_overrides=plan_overrides,
        product_overrides=product_overrides,
    )
    scenario["first_order"] = scenario["order"]
    scenario["first_claim"] = scenario["claim"]
    return scenario


def setup_second_delivered_order(scenario: dict, boxes_od=1, boxes_os=1) -> dict:
    """Add a second delivered order (and DRAFT claim) to an existing scenario,
    reusing its customer, prescription, product and plan."""
    order = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        boxes_od,
        boxes_os,
    )
    ship_order(order["id"])
    scenario["order"] = deliver_order(order["id"])
    if "plan" in scenario:
        scenario["claim"] = new_reimbursement_claim(
            scenario["order"]["id"], scenario["customer"]["id"], scenario["plan"]["id"]
        )
    return scenario


# ==========================================================================
# Tier 5 — terminal states reached through the deferred sweeps and cascades
# ==========================================================================


def setup_expired_prescription_via_sweep(
    expiry_date="2026-09-10",
    clock_before="2026-09-08T10:00:00Z",
    clock_after="2026-09-10T09:00:00Z",
    with_order=False,
    with_schedule=False,
    boxes_od=1,
    boxes_os=1,
    product_overrides=None,
) -> dict:
    """A VERIFIED_ACTIVE prescription driven to EXPIRED by the sweep, which also
    opens a system PRESCRIPTION_EXPIRED hold.

    Adds `sweep` (the sweep response) and `hold` (the OPEN hold the sweep
    opened), plus `order` and `schedule` when requested.
    """
    scenario = setup_verified_prescription(
        clock=clock_before,
        product_overrides=product_overrides,
        prescription_overrides={"expiry_date": expiry_date},
    )
    if with_order:
        scenario["order"] = new_order(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_od,
            boxes_os,
        )
    if with_schedule:
        scenario["schedule"] = new_auto_reorder_schedule(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["product"]["id"],
        )
    set_clock(clock_after)
    scenario["sweep"] = run_verification_sweep()
    holds = open_holds_for_customer(scenario["customer"]["id"])
    scenario["hold"] = holds[0] if holds else None
    return scenario


def setup_open_hold_with_open_dispute(
    clock=WORKING_TUESDAY_10AM,
    hold_opener=CO_ALPHA,
    dispute_reason="NOT_MY_PATIENT",
) -> dict:
    """A prescription carrying both a manually opened hold and an OPEN
    prescriber dispute, so a release attempt has two independent blockers."""
    scenario = setup_verified_prescription_with_prescriber(clock=clock)
    scenario["hold"] = new_reorder_hold(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        actor=hold_opener,
    )
    scenario["dispute"] = file_prescriber_dispute(
        scenario["prescription"]["id"],
        scenario["prescriber"]["id"],
        dispute_reason=dispute_reason,
    )
    return scenario


def setup_dispute_upheld_cascade(
    clock=WORKING_TUESDAY_10AM,
    pending_boxes=(1, 1),
    delivered_boxes=(1, 1),
    with_claim_on_delivered=True,
    plan_overrides=None,
) -> dict:
    """A plan-covered customer with one PENDING order, one DELIVERED order whose
    claim is GENERATED, and an OPEN dispute ready to be upheld.

    Adds `pending_order`, `delivered_order`, `claim` and `dispute`.
    """
    scenario = setup_verified_prescription_with_prescriber(
        clock=clock, with_plan=True, plan_overrides=plan_overrides
    )
    delivered = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        delivered_boxes[0],
        delivered_boxes[1],
    )
    ship_order(delivered["id"])
    scenario["delivered_order"] = deliver_order(delivered["id"])
    if with_claim_on_delivered:
        claim = new_reimbursement_claim(
            scenario["delivered_order"]["id"],
            scenario["customer"]["id"],
            scenario["plan"]["id"],
        )
        scenario["claim"] = generate_reimbursement_claim(claim["id"])
    scenario["pending_order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        pending_boxes[0],
        pending_boxes[1],
    )
    scenario["dispute"] = file_prescriber_dispute(
        scenario["prescription"]["id"], scenario["prescriber"]["id"]
    )
    return scenario


def setup_correction_pending_prescription(
    clock=WORKING_TUESDAY_10AM,
    corrected_od_sphere=-2.50,
    corrected_os_sphere=-4.00,
) -> dict:
    """A prescription pushed into CORRECTION_PENDING by a CORRECTED response to
    its first verification round."""
    scenario = setup_verification_round(clock=clock)
    scenario["verification_request"] = respond_to_verification_request(
        scenario["verification_request"]["id"],
        scenario["prescriber"]["id"],
        "CORRECTED",
        corrected_od_sphere=corrected_od_sphere,
        corrected_os_sphere=corrected_os_sphere,
    )
    return scenario


def setup_active_schedule(
    clock=WORKING_TUESDAY_10AM,
    schedule_overrides=None,
    product_overrides=None,
    prescription_overrides=None,
) -> dict:
    """An ACTIVE auto-reorder schedule on a VERIFIED_ACTIVE prescription."""
    scenario = setup_verified_prescription(
        clock=clock,
        product_overrides=product_overrides,
        prescription_overrides=prescription_overrides,
    )
    scenario["schedule"] = new_auto_reorder_schedule(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        **(schedule_overrides or {}),
    )
    return scenario


def setup_order_blocked_by_open_hold(
    clock=WORKING_TUESDAY_10AM, hold_opener=CO_ALPHA, boxes_od=1, boxes_os=1
) -> dict:
    """A cleared PENDING order whose customer has one OPEN hold, so fulfillment
    is blocked until the hold leaves OPEN."""
    scenario = setup_order_on_verified_prescription(
        boxes_od=boxes_od, boxes_os=boxes_os, clock=clock
    )
    scenario["hold"] = new_reorder_hold(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        actor=hold_opener,
    )
    return scenario


def setup_retired_plan_claim(clock=WORKING_TUESDAY_10AM, boxes_od=1, boxes_os=1) -> dict:
    """A DRAFT claim whose plan was retired after the claim was opened."""
    scenario = setup_delivered_order_with_draft_claim(
        boxes_od=boxes_od, boxes_os=boxes_os, clock=clock
    )
    scenario["plan"] = retire_insurance_plan(scenario["plan"]["id"])
    return scenario


__all__ = [name for name in dir() if not name.startswith("_")]
