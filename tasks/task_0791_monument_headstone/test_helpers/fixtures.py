"""Composite setup helpers for the Monument & Headstone API.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because the harness restarts the server (empty DB, logical clock reset to
2026-03-01T00:00:00Z) before every test. Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion later.

Identity threading: every ownership-gated Customer write uses
make_customer_headers(customer["id"]) with the real Customer.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_cemetery_payload, create_customer_payload, create_workshop_payload,
    create_crew_payload, create_order_payload, create_design_proof_payload,
    create_payment_payload, create_fabrication_job_payload, create_permit_payload,
    create_installation_payload, create_restoration_payload, assess_restoration_payload,
)


# --- role header shortcuts ---
def _admin():
    return TEST_USERS["admin_headers"]


def _designer():
    return TEST_USERS["designer_headers"]


def _shop():
    return TEST_USERS["shop_manager_headers"]


def _fieldops():
    return TEST_USERS["field_ops_headers"]


# --- primitive builders ---
def set_clock(iso: str):
    get_success_data(api_client.set_clock({"to_iso8601": iso}, _admin()))


def make_cemetery(**over) -> dict:
    return get_success_data(api_client.create_cemetery(create_cemetery_payload(**over), _admin()))


def make_customer(**over) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**over), _admin()))


def make_workshop(name="Shop A") -> dict:
    return get_success_data(api_client.create_workshop(create_workshop_payload(name=name), _admin()))


def make_crew(name="Crew 1") -> dict:
    return get_success_data(api_client.create_crew(create_crew_payload(name=name), _admin()))


def make_order(customer: dict, cemetery: dict, **over) -> dict:
    payload = create_order_payload(customer["id"], cemetery["id"], **over)
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer["id"]))
    )


def fetch_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, _admin()))


def make_proof(order: dict, expected_version=None, **over) -> dict:
    ev = expected_version if expected_version is not None else order["version"]
    payload = create_design_proof_payload(order["id"], ev, **over)
    return get_success_data(api_client.create_design_proof(payload, _designer()))


def submit_proof(proof: dict) -> dict:
    return get_success_data(api_client.submit_design_proof(proof["id"], _designer()))


def request_changes(proof: dict, customer: dict) -> dict:
    return get_success_data(
        api_client.request_changes_design_proof(proof["id"], make_customer_headers(customer["id"]))
    )


def approve_proof(proof: dict, customer: dict) -> dict:
    return get_success_data(
        api_client.approve_design_proof(proof["id"], make_customer_headers(customer["id"]))
    )


def pay(order: dict, customer: dict, payment_type: str, amount_cents: int) -> dict:
    payload = create_payment_payload(order["id"], payment_type, amount_cents)
    return get_success_data(
        api_client.create_payment(payload, make_customer_headers(customer["id"]))
    )


# =============================================================================
# Composite setups
# =============================================================================

def setup_drafting_order(cemetery_over=None, order_over=None) -> dict:
    """Cemetery + Customer + a DRAFTING / UNPAID MonumentOrder."""
    cem = make_cemetery(**(cemetery_over or {}))
    cust = make_customer()
    order = make_order(cust, cem, **(order_over or {}))
    return {
        "cemetery": cem,
        "customer": cust,
        "customer_headers": make_customer_headers(cust["id"]),
        "order": order,
    }


def setup_order_and_workshop(cemetery_over=None, order_over=None) -> dict:
    """A DRAFTING order plus a Workshop (no proof)."""
    ctx = setup_drafting_order(cemetery_over, order_over)
    ctx["workshop"] = make_workshop()
    return ctx


def setup_deposit_paid_order(deposit_cents=33880, cemetery_over=None, order_over=None) -> dict:
    """DRAFTING order with the deposit paid (payment_status DEPOSIT_PAID), no proof."""
    ctx = setup_drafting_order(cemetery_over, order_over)
    ctx["deposit_payment"] = pay(ctx["order"], ctx["customer"], "DEPOSIT", deposit_cents)
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_draft_proof(proof_lines=None, cemetery_over=None, order_over=None) -> dict:
    """DRAFTING order carrying a proof still in DRAFT (never submitted); UNPAID."""
    ctx = setup_drafting_order(cemetery_over, order_over)
    over = {} if proof_lines is None else {"line_char_counts": proof_lines}
    ctx["proof"] = make_proof(ctx["order"], **over)
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_submitted_proof(proof_lines=None, cemetery_over=None, order_over=None) -> dict:
    """DRAFTING order carrying a SUBMITTED proof; UNPAID (deposit not paid)."""
    ctx = setup_draft_proof(proof_lines, cemetery_over, order_over)
    ctx["proof"] = submit_proof(ctx["proof"])
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_changes_requested_proof(proof_lines=None, cemetery_over=None, order_over=None) -> dict:
    """Proof taken DRAFT -> SUBMITTED (round 1) -> CHANGES_REQUESTED by the customer."""
    ctx = setup_submitted_proof(proof_lines, cemetery_over, order_over)
    request_changes(ctx["proof"], ctx["customer"])
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_deposit_paid_submitted_proof(
    deposit_cents=33880, proof_lines=None, cemetery_over=None, order_over=None
) -> dict:
    """SUBMITTED proof with the deposit paid — the state right before approval."""
    ctx = setup_submitted_proof(proof_lines, cemetery_over, order_over)
    ctx["deposit_payment"] = pay(ctx["order"], ctx["customer"], "DEPOSIT", deposit_cents)
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_approved_proof(
    deposit_cents=33880, proof_lines=None, cemetery_over=None, order_over=None
) -> dict:
    """Order still DRAFTING with an APPROVED current proof and the deposit paid.

    After approval merchandise/contract are re-priced from the proof's line counts.
    """
    ctx = setup_deposit_paid_submitted_proof(deposit_cents, proof_lines, cemetery_over, order_over)
    approve_proof(ctx["proof"], ctx["customer"])
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_in_fabrication(
    deposit_cents=33880, proof_lines=None, fab_start="2026-03-05T09:00:00Z",
    fab_end="2026-03-05T12:00:00Z", cemetery_over=None, order_over=None,
) -> dict:
    """Order at IN_FABRICATION with one SCHEDULED FabricationJob on a workshop."""
    ctx = setup_approved_proof(deposit_cents, proof_lines, cemetery_over, order_over)
    ctx["workshop"] = make_workshop()
    fab = get_success_data(api_client.create_fabrication_job(
        create_fabrication_job_payload(ctx["order"]["id"], ctx["workshop"]["id"], fab_start, fab_end),
        _shop(),
    ))
    ctx["fabrication_job"] = fab
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_ready_to_install(
    deposit_cents=33880, proof_lines=None, fab_clock="2026-03-10T00:00:00Z",
    fab_start="2026-03-05T09:00:00Z", fab_end="2026-03-05T12:00:00Z",
    pay_balance=False, balance_cents=53371, cemetery_over=None, order_over=None,
) -> dict:
    """Order at READY_TO_INSTALL: proof approved, deposit paid, fabrication completed.

    completed_at is stamped from the logical clock (set to ``fab_clock``). Set
    ``pay_balance=True`` to also drive payment_status to PAID_IN_FULL.
    """
    ctx = setup_approved_proof(deposit_cents, proof_lines, cemetery_over, order_over)
    ctx["workshop"] = make_workshop()
    set_clock(fab_clock)
    fab = get_success_data(api_client.create_fabrication_job(
        create_fabrication_job_payload(ctx["order"]["id"], ctx["workshop"]["id"], fab_start, fab_end),
        _shop(),
    ))
    fab = get_success_data(api_client.complete_fabrication_job(fab["id"], _shop()))
    ctx["fabrication_job"] = fab
    if pay_balance:
        ctx["balance_payment"] = pay(ctx["order"], ctx["customer"], "BALANCE", balance_cents)
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_pending_permit(
    permit_number="P-100", placement_date="2026-03-20T00:00:00Z",
    pay_balance=False, **ready_kwargs,
) -> dict:
    """READY_TO_INSTALL order + a Crew + a PENDING (not-yet-issued) permit."""
    ctx = setup_ready_to_install(pay_balance=pay_balance, **ready_kwargs)
    ctx["crew"] = make_crew()
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(ctx["order"]["id"], ctx["cemetery"]["id"],
                              permit_number=permit_number, placement_date=placement_date),
        _fieldops(),
    ))
    ctx["permit"] = permit
    return ctx


def setup_issued_permit(
    permit_number="P-100", placement_date="2026-03-20T00:00:00Z",
    pay_balance=False, **ready_kwargs,
) -> dict:
    """READY_TO_INSTALL order + Crew + an ISSUED permit."""
    ctx = setup_pending_permit(permit_number, placement_date, pay_balance, **ready_kwargs)
    ctx["permit"] = get_success_data(api_client.issue_permit(ctx["permit"]["id"], _fieldops()))
    return ctx


def setup_scheduled_installation(
    inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T11:00:00Z",
    permit_number="P-100", placement_date="2026-03-20T00:00:00Z",
    pay_balance=False, **ready_kwargs,
) -> dict:
    """ISSUED permit + a SCHEDULED Installation on a crew."""
    ctx = setup_issued_permit(permit_number, placement_date, pay_balance, **ready_kwargs)
    inst = get_success_data(api_client.create_installation(
        create_installation_payload(ctx["order"]["id"], ctx["crew"]["id"], inst_start, inst_end),
        _fieldops(),
    ))
    ctx["installation"] = inst
    ctx["order"] = fetch_order(ctx["order"]["id"])
    return ctx


def setup_order_with_issued_permit_simple(
    permit_number="P-200", placement_date="2026-03-20T00:00:00Z",
    cemetery_over=None, order_over=None,
) -> dict:
    """A DRAFTING order with an ISSUED permit (permit opened + issued directly)."""
    ctx = setup_drafting_order(cemetery_over, order_over)
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(ctx["order"]["id"], ctx["cemetery"]["id"],
                              permit_number=permit_number, placement_date=placement_date),
        _fieldops(),
    ))
    ctx["permit"] = get_success_data(api_client.issue_permit(permit["id"], _fieldops()))
    return ctx


def setup_requested_restoration(
    service_type="REPAIR", reported_area_cm2=1000, cemetery_over=None, order_over=None,
) -> dict:
    """Order + Workshop + a RestorationJob in REQUESTED with a quoted cost."""
    ctx = setup_order_and_workshop(cemetery_over, order_over)
    rest = get_success_data(api_client.create_restoration(
        create_restoration_payload(ctx["order"]["id"], service_type, reported_area_cm2),
        make_customer_headers(ctx["customer"]["id"]),
    ))
    ctx["restoration"] = rest
    return ctx


def setup_assessed_restoration(
    service_type="CLEANING", reported_area_cm2=400, measured_area_cm2=400, condition="NORMAL",
    a_start="2026-03-10T09:00:00Z", a_end="2026-03-10T10:00:00Z",
    cemetery_over=None, order_over=None,
) -> dict:
    """Order + Workshop + a RestorationJob already ASSESSED (booking the workshop)."""
    ctx = setup_requested_restoration(service_type, reported_area_cm2, cemetery_over, order_over)
    rest = get_success_data(api_client.assess_restoration(
        ctx["restoration"]["id"],
        assess_restoration_payload(ctx["workshop"]["id"], measured_area_cm2, condition, a_start, a_end),
        _shop(),
    ))
    ctx["restoration"] = rest
    return ctx


def setup_workshop_with_assessed_restoration_and_pending(
    a_start="2026-03-10T09:00:00Z", a_end="2026-03-10T12:00:00Z",
    second_reported=600, cemetery_over=None, order_over=None,
) -> dict:
    """One ASSESSED restoration booking a workshop slot, plus a second REQUESTED job."""
    ctx = setup_requested_restoration("REPAIR", 500, cemetery_over, order_over)
    ctx["restoration_assessed"] = get_success_data(api_client.assess_restoration(
        ctx["restoration"]["id"],
        assess_restoration_payload(ctx["workshop"]["id"], 500, "NORMAL", a_start, a_end),
        _shop(),
    ))
    ctx["restoration_pending"] = get_success_data(api_client.create_restoration(
        create_restoration_payload(ctx["order"]["id"], "REPAIR", second_reported),
        make_customer_headers(ctx["customer"]["id"]),
    ))
    return ctx


def setup_one_proof_order(proof_lines=None, cemetery_over=None, order_over=None) -> dict:
    """Order + one created proof; returns the ORIGINAL observed order version (``ov``).

    The order's live version has already advanced past ``ov`` by the proof creation.
    """
    cem = make_cemetery(**(cemetery_over or {}))
    cust = make_customer()
    order = make_order(cust, cem, **(order_over or {}))
    ov = order["version"]
    over = {} if proof_lines is None else {"line_char_counts": proof_lines}
    proof = make_proof(order, expected_version=ov, **over)
    return {
        "cemetery": cem,
        "customer": cust,
        "customer_headers": make_customer_headers(cust["id"]),
        "order": fetch_order(order["id"]),
        "proof": proof,
        "observed_version": ov,
    }
