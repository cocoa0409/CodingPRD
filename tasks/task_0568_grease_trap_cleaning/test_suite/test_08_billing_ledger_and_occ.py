"""Compensating invariants (invoice-void conserves balance, manifest-void conserves gallons)
and optimistic-concurrency on invoice creation — difficulty + corner queues."""
from test_helpers import (
    validate_success, validate_error,
    create_invoice_payload,
    TEST_USERS, get_success_data,
)
from test_helpers.fixtures import (
    new_customer, new_active_contract, new_draft_invoice, customer_version,
    setup_issued_invoice, setup_inprogress_grease_work_order, file_manifest,
)
from test_helpers.api_client import api_client

BILLING = TEST_USERS["billing_clerk_headers"]


# ─────────────── Difficulty: invoice void conserves outstanding balance ───────────────
def test_issue_then_void_returns_balance_to_zero(api):
    """PRD §2.9: "voiding an issued invoice subtracts its `total_amount_cents`, exactly
    reversing the debit that issuing applied. The system guarantees that for any single
    invoice, an issue followed by a void leaves `outstanding_balance_cents` unchanged."

    Design: Difficulty/compensating_invariant/invoice_void_conserves_outstanding_balance
    """
    ctx = setup_issued_invoice(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0)
    after_issue = validate_success(api.get_customer(ctx["cust_id"], BILLING), 200)
    assert after_issue["outstanding_balance_cents"] == 12500, "issue debits the balance"
    validate_success(api.void_invoice(ctx["inv_id"], BILLING), 200)
    after_void = validate_success(api.get_customer(ctx["cust_id"], BILLING), 200)
    assert after_void["outstanding_balance_cents"] == 0, \
        "void must exactly reverse the issue debit back to 0"


def test_void_moves_invoice_to_void_terminal_state(api):
    """PRD §3.7: "an `ISSUED` invoice may be voided, moving it `ISSUED → VOID` (terminal) and
    subtracting `total_amount_cents` from `outstanding_balance_cents` to exactly reverse the
    issue debit, again incrementing the customer's `version`."

    Design: Difficulty/compensating_invariant/invoice_void_conserves_outstanding_balance
    """
    ctx = setup_issued_invoice(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0)
    v_before = validate_success(api.get_customer(ctx["cust_id"], BILLING), 200)["version"]
    voided = validate_success(api.void_invoice(ctx["inv_id"], BILLING), 200)
    assert voided["status"] == "VOID", "void moves the invoice to the terminal VOID state"
    v_after = validate_success(api.get_customer(ctx["cust_id"], BILLING), 200)["version"]
    assert v_after == v_before + 1, "voiding increments the customer's version by 1"


# ─────────────── Difficulty: manifest void conserves lifetime gallons ───────────────
def _grease_equipment_with_recorded_800():
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 1000,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    man = file_manifest(ctx["wo_id"], ctx["tech_id"], disposal_facility_permit="FAC-6",
                        volume_gallons=800)
    return ctx, man


def test_manifest_void_restores_lifetime_gallons(api):
    """PRD §3.4: "voiding moves its `status` to `VOIDED` and, as a compensating action,
    subtracts its `volume_gallons` back out of the equipment's `lifetime_pumped_gallons`,
    conserving that lifetime total across a record-then-void pair."

    Design: Difficulty/compensating_invariant/manifest_void_conserves_pumped_gallons
    """
    ctx, man = _grease_equipment_with_recorded_800()
    before = validate_success(api.get_equipment(ctx["eq_id"], ctx["tech_headers"]), 200)
    assert before["lifetime_pumped_gallons"] == 800, "the recorded manifest added 800"
    validate_success(api.void_manifest(man["id"], ctx["tech_headers"]), 200)
    after = validate_success(api.get_equipment(ctx["eq_id"], ctx["tech_headers"]), 200)
    assert after["lifetime_pumped_gallons"] == 0, "void must subtract the 800 back out"


def test_manifest_void_sets_voided_status(api):
    """PRD §3.4: "A `RECORDED` manifest may be voided by the owning technician or by a
    `ComplianceOfficer`; voiding moves its `status` to `VOIDED`".

    Design: Difficulty/compensating_invariant/manifest_void_conserves_pumped_gallons
    """
    ctx, man = _grease_equipment_with_recorded_800()
    voided = validate_success(api.void_manifest(man["id"], ctx["tech_headers"]), 200)
    assert voided["status"] == "VOIDED", "voiding sets the manifest status to VOIDED"


# ─────────────── Corner: OCC on invoice creation ───────────────
def test_invoice_create_increments_customer_version(api):
    """PRD §3.7: "A new invoice is created in `DRAFT`, computes a `provisional_total_cents`,
    increments the customer's `version` by 1, and auto-voids any prior `DRAFT` invoice for
    the same customer and period."

    Design: Corner/cross_cutting_complexity_layers/occ_success_increments_customer_version
    """
    cust = new_customer(credit_limit_cents=1000000)
    new_active_contract(cust["id"], base_rate_cents=5000, tax_rate_bps=0)
    before = customer_version(cust["id"])
    assert before == 1, "a new customer starts at version 1"
    inv = new_draft_invoice(cust["id"])
    assert inv["status"] == "DRAFT"
    after = customer_version(cust["id"])
    assert after == 2, "invoice creation increments the customer's version from 1 to 2"


def test_invoice_create_with_stale_version_rejected(api):
    """PRD §2.7: "If it is present but does not equal the customer's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_returns_412
    """
    cust = new_customer(credit_limit_cents=1000000)
    contract = new_active_contract(cust["id"], base_rate_cents=5000, tax_rate_bps=0)
    stale_version = customer_version(cust["id"])  # v1, captured before any invoice create
    # First create bumps the customer version to 2, leaving stale_version out of date.
    get_success_data(api.create_invoice(
        create_invoice_payload(cust["id"], stale_version, contract_id=contract["id"]), BILLING))
    res = api.create_invoice(
        create_invoice_payload(cust["id"], stale_version, contract_id=contract["id"],
                               period_start="2026-06-01T00:00:00Z",
                               period_end="2026-07-01T00:00:00Z"),
        BILLING)
    validate_error(res, "ERR_STALE_VERSION")
