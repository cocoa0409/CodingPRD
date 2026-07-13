"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every individual test. Setup
calls use get_success_data() so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    facility_payload, cell_payload, hauler_account_payload, manifest_payload,
    special_waste_approval_payload, decide_payload, ticket_payload, weigh_out_payload,
    inspect_payload, post_payload, gas_reading_payload, invoice_payload, payment_payload,
)
from .test_users import (
    make_facility_admin_headers, make_gate_operator_headers,
    make_environmental_officer_headers, make_billing_clerk_headers, make_hauler_headers,
)

# Distinct default gate-operator identities so segregation-of-duties (inspector != poster)
# holds by default.
INSPECT_USER = "op_insp"
POST_USER = "op_post"


# --------------------------------------------------------------------------- #
# Granular step helpers (each mirrors one setup_api_call)                      #
# --------------------------------------------------------------------------- #

def create_facility(total_airspace_cubic_yards=1000, name="F1", admin_id="adm1"):
    resp = api_client.create_facility(
        facility_payload(name=name, total_airspace_cubic_yards=total_airspace_cubic_yards),
        make_facility_admin_headers(admin_id),
    )
    return get_success_data(resp)


def create_cell(facility_id, capacity_cubic_yards=1000, name="C1", admin_id="adm1"):
    resp = api_client.create_cell(
        facility_id, cell_payload(name=name, capacity_cubic_yards=capacity_cubic_yards),
        make_facility_admin_headers(admin_id),
    )
    return get_success_data(resp)


def create_hauler(credit_limit_cents=100_000_000, name="H1", admin_id="adm1"):
    resp = api_client.create_hauler_account(
        hauler_account_payload(name=name, credit_limit_cents=credit_limit_cents),
        make_facility_admin_headers(admin_id),
    )
    return get_success_data(resp)


def create_manifest(hauler_id, declared_material="MSW", declared_weight_tons=7.0):
    resp = api_client.create_manifest(
        manifest_payload(hauler_id, declared_material=declared_material,
                         declared_weight_tons=declared_weight_tons),
        make_hauler_headers(hauler_id),
    )
    return get_success_data(resp)


def submit_manifest(manifest_id, hauler_id):
    return api_client.submit_manifest(manifest_id, make_hauler_headers(hauler_id))


def open_special_waste_approval(manifest_id, waste_type="ASBESTOS", profile_ref="PRF-1", eo_id="eo1"):
    resp = api_client.create_special_waste_approval(
        manifest_id, special_waste_approval_payload(waste_type=waste_type, profile_ref=profile_ref),
        make_environmental_officer_headers(eo_id),
    )
    return get_success_data(resp)


def decide_special_waste_approval(approval_id, decision, eo_id="eo1", decision_note=None):
    payload = decide_payload(decision) if decision_note is None else decide_payload(decision, decision_note=decision_note)
    resp = api_client.decide_special_waste_approval(
        approval_id, payload, make_environmental_officer_headers(eo_id),
    )
    return get_success_data(resp)


def create_gas_reading(facility_id, methane_ppm, reading_at="2026-03-01T08:00:00Z", eo_id="eo1"):
    resp = api_client.create_gas_reading(
        facility_id, gas_reading_payload(methane_ppm, reading_at),
        make_environmental_officer_headers(eo_id),
    )
    return get_success_data(resp)


def create_ticket(facility_id, hauler_id, material="MSW", gross_weight_tons=10.0,
                  manifest_id=None, op_id=INSPECT_USER):
    extra = {}
    if manifest_id is not None:
        extra["manifest_id"] = manifest_id
    resp = api_client.create_ticket(
        ticket_payload(facility_id, hauler_id, material=material,
                       gross_weight_tons=gross_weight_tons, **extra),
        make_gate_operator_headers(op_id),
    )
    return get_success_data(resp)


def weigh_out(ticket_id, tare_weight_tons, op_id=INSPECT_USER):
    resp = api_client.weigh_out_ticket(
        ticket_id, weigh_out_payload(tare_weight_tons), make_gate_operator_headers(op_id),
    )
    return get_success_data(resp)


def inspect(ticket_id, result="PASS", reject_reason=None, op_id=INSPECT_USER):
    resp = api_client.inspect_ticket(
        ticket_id, inspect_payload(result, reject_reason), make_gate_operator_headers(op_id),
    )
    return get_success_data(resp)


def get_facility(facility_id, user_id=POST_USER, role="GateOperator"):
    resp = api_client.get_facility(facility_id, make_gate_operator_headers(user_id))
    return get_success_data(resp)


def facility_version(facility_id, user_id=POST_USER):
    return get_facility(facility_id, user_id)["version"]


def post_ticket(ticket_id, facility_id, op_id=POST_USER, expected_version=None):
    if expected_version is None:
        expected_version = facility_version(facility_id, op_id)
    resp = api_client.post_ticket(
        ticket_id, post_payload(expected_version), make_gate_operator_headers(op_id),
    )
    return get_success_data(resp)


def create_invoice(hauler_id, clerk_id="bc1"):
    resp = api_client.create_invoice(invoice_payload(hauler_id), make_billing_clerk_headers(clerk_id))
    return get_success_data(resp)


def create_payment(invoice_id, amount_cents, method="ACH", clerk_id="bc1"):
    resp = api_client.create_payment(
        invoice_id, payment_payload(amount_cents, method), make_billing_clerk_headers(clerk_id),
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Composite fixtures                                                           #
# --------------------------------------------------------------------------- #

def setup_ticket_in_state(target_state, *, total_airspace=1000, cell_capacity=1000,
                          with_cell=True, credit_limit=100_000_000, material="MSW",
                          gross=10.0, tare=2.0, manifest_id=None, inspect_user=INSPECT_USER):
    """Build facility (+optional cell) + hauler + ticket, walked to target_state.

    target_state in {CREATED, WEIGHED, INSPECTED}. Returns a dict:
    {facility, cell, hauler, ticket}. `ticket` is the freshest server view.
    """
    facility = create_facility(total_airspace)
    cell = create_cell(facility["id"], cell_capacity) if with_cell else None
    hauler = create_hauler(credit_limit)
    ticket = create_ticket(facility["id"], hauler["id"], material=material,
                           gross_weight_tons=gross, manifest_id=manifest_id, op_id=inspect_user)
    if target_state == "CREATED":
        return {"facility": facility, "cell": cell, "hauler": hauler, "ticket": ticket}
    ticket = weigh_out(ticket["id"], tare, op_id=inspect_user)
    if target_state == "WEIGHED":
        return {"facility": facility, "cell": cell, "hauler": hauler, "ticket": ticket}
    ticket = inspect(ticket["id"], "PASS", op_id=inspect_user)
    if target_state == "INSPECTED":
        return {"facility": facility, "cell": cell, "hauler": hauler, "ticket": ticket}
    raise ValueError(f"unsupported target_state {target_state}")


def setup_posted_ticket(*, total_airspace=1000, cell_capacity=1000, credit_limit=100_000_000,
                        material="CONSTRUCTION_DEBRIS", gross=1.5, tare=1.0,
                        inspect_user=INSPECT_USER, post_user=POST_USER):
    """Facility + cell + hauler + one POSTED ticket. Returns dict with the posted ticket
    refetched, plus the facility version captured just before the post."""
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=total_airspace,
                                cell_capacity=cell_capacity, credit_limit=credit_limit,
                                material=material, gross=gross, tare=tare, inspect_user=inspect_user)
    pre_version = facility_version(ctx["facility"]["id"], post_user)
    ctx["pre_post_facility_version"] = pre_version
    ctx["ticket"] = post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"],
                                op_id=post_user, expected_version=pre_version)
    return ctx


def setup_suspended_hauler_with_invoice():
    """Two posted CONSTRUCTION_DEBRIS tickets (fee 2600 each) drive a credit_limit-5200 hauler
    to SUSPENDED, then a settlement invoice is issued (total 5656). Returns dict:
    {facility, cell, hauler, tickets, invoice}."""
    facility = create_facility(1000)
    cell = create_cell(facility["id"], 1000)
    hauler = create_hauler(5200)
    tickets = []
    for _ in range(2):
        tk = create_ticket(facility["id"], hauler["id"], material="CONSTRUCTION_DEBRIS",
                           gross_weight_tons=1.5, op_id=INSPECT_USER)
        weigh_out(tk["id"], 1.0, op_id=INSPECT_USER)
        inspect(tk["id"], "PASS", op_id=INSPECT_USER)
        tk = post_ticket(tk["id"], facility["id"], op_id=POST_USER)
        tickets.append(tk)
    invoice = create_invoice(hauler["id"])
    return {"facility": facility, "cell": cell, "hauler": hauler,
            "tickets": tickets, "invoice": invoice}


def setup_two_inspected_tickets_same_facility():
    """Facility (airspace 500, one large cell) + two INSPECTED CONSTRUCTION_DEBRIS tickets,
    with the facility version captured before any post. Returns dict:
    {facility, cell, hauler, t1, t2, pre_version}."""
    facility = create_facility(500)
    cell = create_cell(facility["id"], 100)
    hauler = create_hauler(100_000_000)
    tickets = []
    for _ in range(2):
        tk = create_ticket(facility["id"], hauler["id"], material="CONSTRUCTION_DEBRIS",
                           gross_weight_tons=1.5, op_id=INSPECT_USER)
        weigh_out(tk["id"], 1.0, op_id=INSPECT_USER)
        tk = inspect(tk["id"], "PASS", op_id=INSPECT_USER)
        tickets.append(tk)
    pre_version = facility_version(facility["id"], POST_USER)
    return {"facility": facility, "cell": cell, "hauler": hauler,
            "t1": tickets[0], "t2": tickets[1], "pre_version": pre_version}


def setup_special_waste_manifest(*, declared_material="ASBESTOS", declared_weight_tons=3.0,
                                 waste_type="ASBESTOS", profile_ref="PRF-1"):
    """Hauler + special-waste manifest + one PENDING approval. Returns dict:
    {hauler, manifest, approval}."""
    hauler = create_hauler(100_000_000)
    manifest = create_manifest(hauler["id"], declared_material=declared_material,
                               declared_weight_tons=declared_weight_tons)
    approval = open_special_waste_approval(manifest["id"], waste_type=waste_type,
                                           profile_ref=profile_ref)
    return {"hauler": hauler, "manifest": manifest, "approval": approval}
