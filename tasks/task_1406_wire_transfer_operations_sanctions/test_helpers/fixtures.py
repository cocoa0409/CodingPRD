"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly started server). Setup calls use
the lenient get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Canonical actor identities (PRD §2.1 opaque identifiers):
  op-1   WireOperator        ap-1 / ap-2  WireApprover pair
  ss-1   SanctionsScreener   co-1         ComplianceOfficer
  fa-1   FraudAnalyst        rs-1         RepairSpecialist
  inv-1  WireInvestigator    benebank-1   BeneficiaryBank
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    assess_fee_payload,
    confirm_fraud_hold_payload,
    create_account_payload,
    create_beneficiary_payload,
    create_business_date_payload,
    create_customer_payload,
    create_investigation_payload,
    create_recall_payload,
    create_wire_payload,
    hit_disposition_payload,
    place_fraud_hold_payload,
    post_charge_payload,
    record_callback_payload,
    respond_recall_payload,
    simulate_hit_payload,
    submit_wire_payload,
    tracer_payload,
)
from .test_users import (
    TEST_USERS,
    make_beneficiary_bank_headers,
    make_fraud_analyst_headers,
    make_repair_specialist_headers,
    make_sanctions_screener_headers,
    make_wire_approver_headers,
    make_wire_investigator_headers,
    make_wire_operator_headers,
)

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]
APPROVER_1 = TEST_USERS["wire_approver_headers"]
APPROVER_2 = TEST_USERS["wire_approver_2_headers"]
SCREENER = TEST_USERS["sanctions_screener_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
FRAUD_ANALYST = TEST_USERS["fraud_analyst_headers"]
REPAIR_SPECIALIST = TEST_USERS["repair_specialist_headers"]
INVESTIGATOR = TEST_USERS["wire_investigator_headers"]
BENEFICIARY_BANK = TEST_USERS["beneficiary_bank_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Time helpers (logical clock instants, PRD §2.5)
# ---------------------------------------------------------------------------

def parse_instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def format_instant(dt: datetime) -> str:
    """Render an aware UTC datetime as an ISO 8601 'Z' timestamp."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_hours(iso: str, hours: float) -> str:
    return format_instant(parse_instant(iso) + timedelta(hours=hours))


def set_clock(to_iso8601: str):
    """Advance the logical clock (WireOpsAdmin-only). Returns current_utc."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: onboarding entities (PRD §3.1) and the ops-day calendar (§2.5)
# ---------------------------------------------------------------------------

def create_customer(headers=None, **overrides):
    """Register a customer. Returns the created customer."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), headers or ADMIN))


def create_account(customer_id, headers=None, **overrides):
    """Open an account for a customer. Returns the created account."""
    return get_success_data(
        api_client.create_account(
            create_account_payload(customer_id, **overrides), headers or ADMIN))


def create_beneficiary(customer_id, headers=None, **overrides):
    """Register a beneficiary for a customer. Returns the created beneficiary."""
    return get_success_data(
        api_client.create_beneficiary(
            create_beneficiary_payload(customer_id, **overrides), headers or OPERATOR))


def create_business_date(business_date, headers=None):
    """Open a business date (ops day). Returns the created BusinessDate."""
    return get_success_data(api_client.create_business_date(
        create_business_date_payload(business_date), headers or ADMIN))


def get_account(account_id, headers=None):
    return get_success_data(api_client.get_account(account_id, headers or OPERATOR))


def get_customer(customer_id, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def setup_wire_room(business_date=None, customer_overrides=None,
                    account_overrides=None, beneficiary_overrides=None):
    """Customer + account + beneficiary (+ optional OPEN business date).

    Returns a dict with keys customer, account, beneficiary, business_date
    (None when business_date is not given).
    """
    customer = create_customer(**(customer_overrides or {}))
    account = create_account(customer["id"], **(account_overrides or {}))
    beneficiary = create_beneficiary(customer["id"], **(beneficiary_overrides or {}))
    bd = create_business_date(business_date) if business_date else None
    return {
        "customer": customer,
        "account": account,
        "beneficiary": beneficiary,
        "business_date": bd,
    }


# ---------------------------------------------------------------------------
# Tier 2: wire lifecycle (PRD §3.2-§3.5)
# ---------------------------------------------------------------------------

def create_wire(account_id, beneficiary_id, amount_cents=100000,
                operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"], **overrides):
    """Initiate a wire as the given operator identity. Returns the wire."""
    return get_success_data(api_client.create_wire(
        create_wire_payload(account_id, beneficiary_id,
                            amount_cents=amount_cents, **overrides),
        make_wire_operator_headers(operator_user_id)))


def get_wire(wire_id, headers=None):
    return get_success_data(api_client.get_wire(wire_id, headers or OPERATOR))


def wire_version(wire_id, headers=None) -> int:
    """Current optimistic-concurrency version of the wire (PRD §2.7)."""
    return get_wire(wire_id, headers)["version"]


def submit_wire(wire_id, business_date,
                operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                waive_callback=None):
    """Submit an INITIATED / callback-cleared wire. Returns the wire."""
    payload = submit_wire_payload(business_date)
    if waive_callback is not None:
        payload["waive_callback"] = waive_callback
    return get_success_data(api_client.submit_wire(
        wire_id, payload, make_wire_operator_headers(operator_user_id)))


def approve_wire(wire_id, approver_user_id):
    """Record one approval with a fresh expected_wire_version (PRD §2.7)."""
    version = wire_version(wire_id)
    return get_success_data(api_client.approve_wire(
        wire_id, {"expected_wire_version": version},
        make_wire_approver_headers(approver_user_id)))


def dual_approve_wire(wire_id,
                      first=TEST_DEFAULTS["APPROVER_1_USER_ID"],
                      second=TEST_DEFAULTS["APPROVER_2_USER_ID"]):
    """Record the FIRST and SECOND approvals. Returns the APPROVED wire."""
    approve_wire(wire_id, first)
    return approve_wire(wire_id, second)


def release_wire(wire_id, operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"]):
    """Release an APPROVED/CLEAR/unheld wire. Returns the EXECUTED wire."""
    version = wire_version(wire_id)
    return get_success_data(api_client.release_wire(
        wire_id, {"expected_wire_version": version},
        make_wire_operator_headers(operator_user_id)))


def repair_wire(wire_id, specialist_user_id=TEST_DEFAULTS["REPAIR_SPECIALIST_USER_ID"],
                **field_overrides):
    """Repair a PENDING_APPROVAL wire with a fresh version. Returns the wire."""
    version = wire_version(wire_id)
    payload = {"expected_wire_version": version}
    payload.update(field_overrides)
    return get_success_data(api_client.repair_wire(
        wire_id, payload, make_repair_specialist_headers(specialist_user_id)))


def resubmit_wire(wire_id, specialist_user_id=TEST_DEFAULTS["REPAIR_SPECIALIST_USER_ID"]):
    """Return a REPAIR wire to PENDING_APPROVAL. Returns the wire."""
    return get_success_data(api_client.resubmit_wire(
        wire_id, make_repair_specialist_headers(specialist_user_id)))


def cancel_wire(wire_id, operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"]):
    return get_success_data(api_client.cancel_wire(
        wire_id, make_wire_operator_headers(operator_user_id)))


def reject_wire(wire_id, approver_user_id=TEST_DEFAULTS["APPROVER_1_USER_ID"],
                reason="not approved"):
    return get_success_data(api_client.reject_wire(
        wire_id, {"reason": reason}, make_wire_approver_headers(approver_user_id)))


def list_wire_sanctions_hits(wire_id, headers=None):
    return get_success_data(api_client.list_wire_sanctions_hits(
        wire_id, headers or SCREENER))


def list_wire_fees(wire_id, headers=None):
    return get_success_data(api_client.list_wire_fees(wire_id, headers or OPERATOR))


def list_wire_charges(wire_id, headers=None):
    return get_success_data(api_client.list_wire_charges(wire_id, headers or OPERATOR))


def list_wire_callbacks(wire_id, headers=None):
    return get_success_data(api_client.list_wire_callbacks(wire_id, headers or OPERATOR))


def list_wire_fraud_holds(wire_id, headers=None):
    return get_success_data(api_client.list_wire_fraud_holds(
        wire_id, headers or FRAUD_ANALYST))


def list_wire_approvals(wire_id, headers=None):
    return get_success_data(api_client.list_wire_approvals(wire_id, headers or OPERATOR))


def release_open_hits(wire_id,
                      screener_user_id=TEST_DEFAULTS["SCREENER_USER_ID"]):
    """Release every OPEN sanctions hit on the wire as false positive.

    A submit whose risk score reaches the review threshold creates a synthetic
    OPEN hit (PRD §3.3); fixtures that need a CLEAR wire disposition it here.
    Returns the list of released hits.
    """
    released = []
    for hit in list_wire_sanctions_hits(wire_id):
        if hit["status"] == "OPEN":
            released.append(get_success_data(api_client.release_sanctions_hit(
                hit["id"], hit_disposition_payload("false positive"),
                make_sanctions_screener_headers(screener_user_id))))
    return released


def create_submitted_wire(account_id, beneficiary_id, business_date,
                          amount_cents=100000,
                          operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                          clear_hits=True, **overrides):
    """Wire walked INITIATED -> PENDING_APPROVAL (screening run, reservation
    active). When the screening review threshold was crossed, the synthetic
    OPEN hit is dispositioned so the wire lands CLEAR unless clear_hits=False.
    Returns the wire."""
    wire = create_wire(account_id, beneficiary_id, amount_cents,
                       operator_user_id=operator_user_id, **overrides)
    wire = submit_wire(wire["id"], business_date,
                       operator_user_id=operator_user_id)
    if clear_hits:
        release_open_hits(wire["id"])
        wire = get_wire(wire["id"])
    return wire


def create_approved_wire(account_id, beneficiary_id, business_date,
                         amount_cents=100000,
                         operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                         clear_hits=True, **overrides):
    """Wire walked to APPROVED (dual approval by two distinct non-initiator
    approvers). Returns the wire."""
    wire = create_submitted_wire(
        account_id, beneficiary_id, business_date, amount_cents,
        operator_user_id=operator_user_id, clear_hits=clear_hits, **overrides)
    return dual_approve_wire(wire["id"])


def create_executed_wire(account_id, beneficiary_id, business_date,
                         amount_cents=100000,
                         operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                         charges=None, clear_hits=True, **overrides):
    """Wire walked all the way to EXECUTED.

    charges: optional list of post_charge_payload overrides posted while the
    wire is APPROVED (the window in which every charge source is postable).
    Returns the EXECUTED wire.
    """
    wire = create_approved_wire(
        account_id, beneficiary_id, business_date, amount_cents,
        operator_user_id=operator_user_id, clear_hits=clear_hits, **overrides)
    for charge_overrides in (charges or []):
        get_success_data(api_client.post_charge(
            wire["id"], post_charge_payload(**charge_overrides), OPERATOR))
    return release_wire(wire["id"], operator_user_id=operator_user_id)


def create_callback_pending_wire(account_id, beneficiary_id,
                                 amount_cents=150000000,
                                 operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                                 **overrides):
    """Wire at/above the callback threshold: CALLBACK_PENDING with one OPEN
    CallbackVerification case. Returns (wire, case)."""
    wire = create_wire(account_id, beneficiary_id, amount_cents,
                       operator_user_id=operator_user_id, **overrides)
    cases = list_wire_callbacks(wire["id"])
    assert len(cases) == 1, f"expected one OPEN callback case, got {len(cases)}"
    return wire, cases[0]


def record_callback(case_id, outcome="CONFIRMED",
                    operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                    **overrides):
    return get_success_data(api_client.record_callback(
        case_id, record_callback_payload(outcome, **overrides),
        make_wire_operator_headers(operator_user_id)))


# ---------------------------------------------------------------------------
# Tier 3: sanctions (PRD §3.6) and fraud holds (PRD §3.8)
# ---------------------------------------------------------------------------

def simulate_hit(wire_id, screener_user_id=TEST_DEFAULTS["SCREENER_USER_ID"],
                 **overrides):
    """Attach a deterministic party-match hit to a wire. Returns the hit."""
    return get_success_data(api_client.simulate_screening_hit(
        simulate_hit_payload(wire_id, **overrides),
        make_sanctions_screener_headers(screener_user_id)))


def place_fraud_hold(wire_id, analyst_user_id=TEST_DEFAULTS["FRAUD_ANALYST_USER_ID"],
                     **overrides):
    """Place a fraud hold on an APPROVED unheld wire. Returns the hold."""
    return get_success_data(api_client.place_fraud_hold(
        wire_id, place_fraud_hold_payload(**overrides),
        make_fraud_analyst_headers(analyst_user_id)))


def confirm_fraud_hold(hold_id, confirmation="LEGITIMATE",
                       analyst_user_id=TEST_DEFAULTS["FRAUD_ANALYST_USER_ID"]):
    return get_success_data(api_client.confirm_fraud_hold(
        hold_id, confirm_fraud_hold_payload(confirmation),
        make_fraud_analyst_headers(analyst_user_id)))


# ---------------------------------------------------------------------------
# Tier 4: recalls (PRD §3.9)
# ---------------------------------------------------------------------------

def create_recall(wire_id, operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"],
                  **overrides):
    return get_success_data(api_client.create_recall(
        create_recall_payload(wire_id, **overrides),
        make_wire_operator_headers(operator_user_id)))


def send_recall(recall_id, operator_user_id=TEST_DEFAULTS["OPERATOR_USER_ID"]):
    return get_success_data(api_client.send_recall(
        recall_id, make_wire_operator_headers(operator_user_id)))


def respond_recall(recall_id, response="FUNDS_RETURNED",
                   bank_user_id=TEST_DEFAULTS["BENEFICIARY_BANK_USER_ID"]):
    return get_success_data(api_client.respond_recall(
        recall_id, respond_recall_payload(response),
        make_beneficiary_bank_headers(bank_user_id)))


def create_sent_recall(wire_id, **overrides):
    """Recall walked REQUESTED -> SENT_TO_BENEFICIARY_BANK. Returns the recall."""
    recall = create_recall(wire_id, **overrides)
    return send_recall(recall["id"])


# ---------------------------------------------------------------------------
# Tier 5: fees and investigations (PRD §3.7, §3.10)
# ---------------------------------------------------------------------------

def assess_fee(wire_id, kind="PROVISIONAL", headers=None):
    return get_success_data(api_client.assess_fee(
        wire_id, assess_fee_payload(kind), headers or OPERATOR))


def post_charge(wire_id, headers=None, **overrides):
    return get_success_data(api_client.post_charge(
        wire_id, post_charge_payload(**overrides), headers or OPERATOR))


def create_investigation(wire_id,
                         investigator_user_id=TEST_DEFAULTS["INVESTIGATOR_USER_ID"],
                         **overrides):
    return get_success_data(api_client.create_investigation(
        create_investigation_payload(wire_id, **overrides),
        make_wire_investigator_headers(investigator_user_id)))


def dispatch_tracer(investigation_id,
                    investigator_user_id=TEST_DEFAULTS["INVESTIGATOR_USER_ID"],
                    body="tracer message"):
    return get_success_data(api_client.dispatch_tracer(
        investigation_id, tracer_payload(body),
        make_wire_investigator_headers(investigator_user_id)))


def respond_investigation(investigation_id,
                          investigator_user_id=TEST_DEFAULTS["INVESTIGATOR_USER_ID"],
                          body="counterparty reply"):
    return get_success_data(api_client.respond_investigation(
        investigation_id, tracer_payload(body),
        make_wire_investigator_headers(investigator_user_id)))
