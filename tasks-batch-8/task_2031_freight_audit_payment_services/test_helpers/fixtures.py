"""Composite setup helpers for multi-step test prerequisites.

The server is relaunched before every test, so each helper builds its entire
precondition chain from an empty database using only PRD-declared endpoints.
All setup calls go through get_success_data() so a setup failure surfaces as
a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: CarrierRep and ClientViewer are entity-backed roles, so
carrier-scoped calls use make_carrier_rep_headers(carrier["id"]) and
client-scoped reads use make_client_viewer_headers(client["id"]). Payment-run
composition and release use distinct operator ids to respect segregation of
duties (PRD §3.8).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, INVOICE_DATE, RUN_DATE, SHIP_DATE
from .factories import (
    create_carrier_payload,
    create_client_payload,
    create_fx_rate_payload,
    create_gl_account_payload,
    create_invoice_payload,
    create_payment_run_payload,
    create_rate_contract_payload,
    create_recovery_claim_payload,
    create_shipment_payload,
    ltl_lane_us_ca,
    parcel_lane_de_us,
)
from .test_users import (
    FIN_OPERATOR_1,
    TEST_USERS,
    TREASURY_OPERATOR_1,
    make_carrier_rep_headers,
    make_finance_controller_headers,
    make_treasury_approver_headers,
)

ADMIN = TEST_USERS["fap_admin_headers"]
ANALYST = TEST_USERS["audit_analyst_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]  # op-fin-1
TREASURY = TEST_USERS["treasury_approver_headers"]  # op-treasury-1


# ─── Logical clock ────────────────────────────────────


def set_clock(to_iso8601: str = CLOCK_START):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Client / carrier / contract building blocks ──────


def create_client(**overrides):
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN), 201)


def activate_client(client_id: str):
    return get_success_data(api_client.activate_client(client_id, ADMIN))


def create_active_client(**overrides):
    client = create_client(**overrides)
    activate_client(client["id"])
    return get_success_data(api_client.get_client(client["id"], ADMIN))


def create_carrier(client_id: str, **overrides):
    return get_success_data(
        api_client.create_carrier(client_id, create_carrier_payload(**overrides), ADMIN), 201
    )


def approve_carrier(carrier_id: str):
    return get_success_data(api_client.approve_carrier_onboard(carrier_id, ADMIN))


def create_active_carrier(client_id: str, **overrides):
    carrier = create_carrier(client_id, **overrides)
    approve_carrier(carrier["id"])
    return get_success_data(api_client.get_carrier(carrier["id"], ADMIN))


def create_contract(carrier_id: str, lanes=None, **overrides):
    return get_success_data(
        api_client.create_rate_contract(
            carrier_id, create_rate_contract_payload(lanes=lanes, **overrides), ADMIN
        ),
        201,
    )


def activate_contract(contract_id: str, expected_version: int):
    return get_success_data(
        api_client.activate_rate_contract(
            contract_id, {"expected_rate_contract_version": expected_version}, ADMIN
        )
    )


def create_active_contract(carrier_id: str, lanes=None, **overrides):
    contract = create_contract(carrier_id, lanes=lanes, **overrides)
    return activate_contract(contract["id"], contract["version"])


def setup_standard_chain(
    client_overrides=None,
    carrier_overrides=None,
    lanes=None,
    with_contract: bool = True,
    contract_overrides=None,
):
    """ACTIVE client + ACTIVE carrier (+ ACTIVE canonical LTL contract).

    Returns dict(client, carrier, contract) — contract is None when
    with_contract=False.
    """
    set_clock()
    client = create_active_client(**(client_overrides or {}))
    carrier = create_active_carrier(client["id"], **(carrier_overrides or {}))
    contract = None
    if with_contract:
        contract = create_active_contract(
            carrier["id"], lanes=lanes, **(contract_overrides or {})
        )
    return {"client": client, "carrier": carrier, "contract": contract}


# ─── Shipments and invoices ───────────────────────────


def create_shipment(client_id: str, carrier_id: str, **overrides):
    return get_success_data(
        api_client.create_shipment(
            client_id, create_shipment_payload(carrier_id, **overrides), ANALYST
        ),
        201,
    )


def create_invoice(client_id: str, carrier_id: str, **overrides):
    return get_success_data(
        api_client.create_invoice(
            client_id, create_invoice_payload(carrier_id, **overrides), ANALYST
        ),
        201,
    )


def capture_invoice(invoice_id: str):
    return get_success_data(api_client.capture_invoice(invoice_id, ANALYST))


def rate_invoice(invoice_id: str, policy=None):
    payload = {} if policy is None else {"policy": policy}
    return get_success_data(api_client.rate_invoice(invoice_id, payload, ANALYST))


def finalize_invoice(invoice_id: str):
    return get_success_data(api_client.finalize_invoice_audit(invoice_id, ANALYST))


def rerate_invoice(invoice_id: str, policy=None):
    payload = {} if policy is None else {"policy": policy}
    return get_success_data(api_client.rerate_invoice(invoice_id, payload, ANALYST))


def audit_invoice_to_cleared(invoice_id: str, policy=None):
    """capture -> rate -> finalize_audit. Returns the CLEARED invoice."""
    capture_invoice(invoice_id)
    rate_invoice(invoice_id, policy=policy)
    return finalize_invoice(invoice_id)


def build_cleared_invoice(
    chain,
    invoice_number="INV-0001",
    shipment_overrides=None,
    invoice_overrides=None,
):
    """Canonical 500 kg LTL shipment + invoice billed at the canonical rated
    total (87500), audited to CLEARED. Returns the finalized invoice."""
    shipment = create_shipment(
        chain["client"]["id"], chain["carrier"]["id"], **(shipment_overrides or {})
    )
    overrides = {"invoice_number": invoice_number, "shipment_id": shipment["id"]}
    overrides.update(invoice_overrides or {})
    invoice = create_invoice(chain["client"]["id"], chain["carrier"]["id"], **overrides)
    return audit_invoice_to_cleared(invoice["id"])


def get_invoice(invoice_id: str):
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def list_invoice_lines(invoice_id: str):
    return get_success_data(api_client.list_lines_of_invoice(invoice_id, ADMIN))


def find_line(invoice_id: str, charge_code: str):
    """Return the line of the invoice carrying the given charge code.

    Lines are looked up by charge code rather than list position so the
    lookup does not depend on list ordering."""
    for line in list_invoice_lines(invoice_id):
        if line["charge_code"] == charge_code:
            return line
    raise AssertionError(f"Setup failed: no {charge_code} line on invoice {invoice_id}")


def list_invoice_exceptions(invoice_id: str):
    return get_success_data(api_client.list_invoice_exceptions(invoice_id, ANALYST))


def first_exception(invoice_id: str):
    exceptions = list_invoice_exceptions(invoice_id)
    assert len(exceptions) == 1, f"Setup failed: expected 1 exception, got {len(exceptions)}"
    return exceptions[0]


# ─── Exception scenarios ──────────────────────────────


def build_rate_mismatch_exception(chain):
    """Invoice billed 91000 against a rated total of 87500: variance 3500
    exceeds the client's 500-minor tolerance, so finalization routes to
    EXCEPTION with a RATE_MISMATCH exception (disputed 3500, queue CARRIER).

    Returns (invoice, exception)."""
    shipment = create_shipment(chain["client"]["id"], chain["carrier"]["id"])
    invoice = create_invoice(
        chain["client"]["id"],
        chain["carrier"]["id"],
        invoice_number="INV-0004",
        shipment_id=shipment["id"],
        billed_total_minor=91000,
        lines=[
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 78000},
            {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7800},
            {"charge_code": "LIFTGATE", "billed_amount_minor": 5200},
        ],
    )
    capture_invoice(invoice["id"])
    rate_invoice(invoice["id"])
    finalize_invoice(invoice["id"])
    exception = first_exception(invoice["id"])
    assert exception["code"] == "RATE_MISMATCH", "Setup failed: expected RATE_MISMATCH"
    return invoice, exception


def notify_and_respond(exception_id: str, carrier_id: str):
    """OPEN -> CARRIER_NOTIFIED -> CARRIER_RESPONDED (carrier-scoped)."""
    get_success_data(api_client.notify_exception_carrier(exception_id, ANALYST))
    return get_success_data(
        api_client.respond_exception_carrier(
            exception_id, {}, make_carrier_rep_headers(carrier_id)
        )
    )


# ─── GL accounts and FX rates ─────────────────────────


def create_gl_account(client_id: str, **overrides):
    return get_success_data(
        api_client.create_gl_account(client_id, create_gl_account_payload(**overrides), FINANCE),
        201,
    )


def create_fx_rate(client_id: str, **overrides):
    return get_success_data(
        api_client.create_fx_rate(client_id, create_fx_rate_payload(**overrides), FINANCE),
        201,
    )


# ─── Payment runs ─────────────────────────────────────


def create_payment_run(client_id: str, user_id: str = FIN_OPERATOR_1, **overrides):
    return get_success_data(
        api_client.create_payment_run(
            client_id,
            create_payment_run_payload(**overrides),
            make_finance_controller_headers(user_id),
        ),
        201,
    )


def get_payment_run(run_id: str):
    return get_success_data(api_client.get_payment_run(run_id, ADMIN))


def add_run_item(run_id: str, invoice_id: str, user_id: str = FIN_OPERATOR_1):
    """Add one item, reading the run's current version first (OCC, PRD §2.9)."""
    run = get_payment_run(run_id)
    return get_success_data(
        api_client.add_payment_run_item(
            run_id,
            {"expected_payment_run_version": run["version"], "invoice_id": invoice_id},
            make_finance_controller_headers(user_id),
        ),
        201,
    )


def lock_run(run_id: str, user_id: str = FIN_OPERATOR_1):
    return get_success_data(
        api_client.lock_payment_run(run_id, make_finance_controller_headers(user_id))
    )


def unlock_run(run_id: str, user_id: str = FIN_OPERATOR_1):
    return get_success_data(
        api_client.unlock_payment_run(run_id, make_finance_controller_headers(user_id))
    )


def release_run(run_id: str, user_id: str = TREASURY_OPERATOR_1):
    return get_success_data(
        api_client.release_payment_run(run_id, make_treasury_approver_headers(user_id))
    )


def settle_run(run_id: str, user_id: str = TREASURY_OPERATOR_1):
    return get_success_data(
        api_client.settle_payment_run(run_id, make_treasury_approver_headers(user_id))
    )


def list_run_items(run_id: str):
    return get_success_data(api_client.list_payment_run_items(run_id, FINANCE))


def list_run_advices(run_id: str):
    return get_success_data(api_client.list_run_remittance_advices(run_id, ADMIN))


def build_locked_run(client_id: str, invoice_ids, user_id: str = FIN_OPERATOR_1):
    """DRAFT run + one item per invoice + lock. Returns the LOCKED run."""
    run = create_payment_run(client_id, user_id=user_id)
    for invoice_id in invoice_ids:
        add_run_item(run["id"], invoice_id, user_id=user_id)
    return lock_run(run["id"], user_id=user_id)


def build_settled_invoice(chain, **invoice_kwargs):
    """Cleared invoice fully settled through a payment run (paid in full —
    gross 87500 earns no discount tier). Returns (invoice, run)."""
    invoice = build_cleared_invoice(chain, **invoice_kwargs)
    run = build_locked_run(chain["client"]["id"], [invoice["id"]])
    release_run(run["id"])
    settle_run(run["id"])
    return get_invoice(invoice["id"]), get_payment_run(run["id"])


# ─── Recovery claims ──────────────────────────────────


def create_recovery_claim(invoice_id: str, **overrides):
    return get_success_data(
        api_client.create_recovery_claim(
            invoice_id, create_recovery_claim_payload(**overrides), ANALYST
        ),
        201,
    )


# ─── EUR / FX scenario ────────────────────────────────


def setup_eur_fx_chain(fx_rates=(("2026-08-01", 1_100_000),)):
    """ACTIVE USD client + ACTIVE EUR carrier + ACTIVE EUR PARCEL contract.

    fx_rates is an iterable of (effective_date, rate_ppm) EUR->USD rows.
    Returns dict(client, carrier, contract)."""
    set_clock()
    client = create_active_client()
    carrier = create_active_carrier(
        client["id"],
        scac_code="EUCA",
        legal_name="Euro Carrier",
        country="DE",
        billing_currency="EUR",
        payment_terms_days=30,
        remit_email="remit@euca.example",
    )
    contract = create_active_contract(
        carrier["id"], lanes=[parcel_lane_de_us()], name="C3", currency="EUR"
    )
    for effective_date, rate_ppm in fx_rates:
        create_fx_rate(client["id"], effective_date=effective_date, rate_ppm=rate_ppm)
    return {"client": client, "carrier": carrier, "contract": contract}


def build_eur_invoice(chain, lines, invoice_number="INV-0300", **overrides):
    """EUR PARCEL invoice over a 1 kg DE->US shipment."""
    shipment = create_shipment(
        chain["client"]["id"],
        chain["carrier"]["id"],
        pro_number="PRO-3001",
        origin_country="DE",
        dest_country="US",
        mode="PARCEL",
        actual_weight_kg=1,
        accessorials_rendered=["DETENTION", "STORAGE"],
    )
    return create_invoice(
        chain["client"]["id"],
        chain["carrier"]["id"],
        invoice_number=invoice_number,
        shipment_id=shipment["id"],
        invoice_date=INVOICE_DATE,
        currency="EUR",
        billed_total_minor=sum(line["billed_amount_minor"] for line in lines),
        lines=lines,
        **overrides,
    )
