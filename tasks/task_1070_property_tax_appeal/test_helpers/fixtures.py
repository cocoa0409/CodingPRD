"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Setup calls use the
lenient get_success_data() validator so a setup break surfaces clearly.

Identity threading: Analyst and Client are entity-backed roles. Every ownership-gated or
actor-recording call uses make_analyst_headers(analyst_id) / make_client_headers(client_id)
with the actual entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS, make_analyst_headers, make_client_headers, make_billing_headers,
)
from . import factories as F

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
BILLING = TEST_USERS["billing_headers"]


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, FIRM_ADMIN))


# --------------------------------------------------------------------------- #
# granular entity builders
# --------------------------------------------------------------------------- #
def new_analyst(api, **overrides):
    return get_success_data(api.create_analyst(F.create_analyst_payload(**overrides), FIRM_ADMIN))


def new_client(api, **overrides):
    return get_success_data(api.create_client(F.create_client_payload(**overrides), FIRM_ADMIN))


def new_jurisdiction(api, **overrides):
    return get_success_data(api.create_jurisdiction(F.create_jurisdiction_payload(**overrides), FIRM_ADMIN))


def new_fee_agreement(api, client_id, accept=False, **overrides):
    fa = get_success_data(api.create_fee_agreement(F.create_fee_agreement_payload(client_id, **overrides), FIRM_ADMIN))
    if accept:
        fa = get_success_data(api.accept_fee_agreement(fa["id"], make_client_headers(client_id)))
    return fa


def new_parcel(api, analyst_id, client_id, jurisdiction_id, **overrides):
    return get_success_data(api.create_parcel(
        F.create_parcel_payload(client_id, jurisdiction_id, **overrides),
        make_analyst_headers(analyst_id)))


def new_assessment(api, analyst_id, parcel_id, **overrides):
    return get_success_data(api.create_assessment(
        F.create_assessment_payload(parcel_id, **overrides), make_analyst_headers(analyst_id)))


def new_appeal(api, analyst_id, assessment_id, fee_agreement_id,
               valuation_method="SALES_COMPARISON", **overrides):
    return get_success_data(api.create_appeal(
        F.create_appeal_payload(assessment_id, analyst_id, fee_agreement_id, valuation_method, **overrides),
        make_analyst_headers(analyst_id)))


def add_evidence(api, analyst_id, appeal_id, **overrides):
    return get_success_data(api.create_evidence(
        appeal_id, F.create_evidence_payload(**overrides), make_analyst_headers(analyst_id)))


def do_file_appeal(api, analyst_id, appeal_id):
    return get_success_data(api.file_appeal(appeal_id, make_analyst_headers(analyst_id)))


def appeal_version(api, analyst_id, appeal_id):
    return get_success_data(api.get_appeal(appeal_id, make_analyst_headers(analyst_id)))["version"]


def add_offer(api, analyst_id, appeal_id, offer_value_cents, expected_version=None,
              proposed_by="FIRM", expires_at="2026-12-31T00:00:00Z", **overrides):
    if expected_version is None:
        expected_version = appeal_version(api, analyst_id, appeal_id)
    return get_success_data(api.create_settlement_offer(
        appeal_id,
        F.create_settlement_offer_payload(offer_value_cents, expected_version, proposed_by, expires_at, **overrides),
        make_analyst_headers(analyst_id)))


def schedule_hearing(api, analyst_id, appeal_id, representative_id,
                     scheduled_start, scheduled_end, docket_room="R1", **overrides):
    return get_success_data(api.schedule_hearing(
        appeal_id,
        F.create_hearing_payload(representative_id, scheduled_start, scheduled_end, docket_room, **overrides),
        make_analyst_headers(analyst_id)))


def hold_hearing(api, representative_id, hearing_id, outcome_note=None):
    payload = {} if outcome_note is None else {"outcome_note": outcome_note}
    return get_success_data(api.hold_hearing(hearing_id, payload, make_analyst_headers(representative_id)))


def do_record_decision(api, analyst_id, appeal_id, decision_value_cents):
    return get_success_data(api.record_decision(
        appeal_id, {"decision_value_cents": decision_value_cents}, make_analyst_headers(analyst_id)))


def invoice_for_appeal(api, appeal_id):
    """Return the (single) invoice created for an appeal, via the Billing invoice list."""
    data = get_success_data(api.list_invoices(BILLING, params={"appeal_id": appeal_id}))
    assert data, f"expected an invoice for appeal {appeal_id}"
    return data[0]


def do_issue_invoice(api, invoice_id):
    return get_success_data(api.issue_invoice(invoice_id, BILLING))


# --------------------------------------------------------------------------- #
# composite scenario builders
# --------------------------------------------------------------------------- #
# The default 3-comp set used by the dual-variant valuation recipes:
#   SALES_COMPARISON  median(adjusted sale) = 30000000
#   ASSESSMENT_EQUITY median(comp_assessed / 0.90) = 29000000
DUAL_VARIANT_COMPS = [
    {"comp_address": "c-a", "sale_price_cents": 30000000, "comp_assessed_value_cents": 27900000, "adjustment_pct": 0.00},
    {"comp_address": "c-b", "sale_price_cents": 32000000, "comp_assessed_value_cents": 25200000, "adjustment_pct": -0.05},
    {"comp_address": "c-c", "sale_price_cents": 28000000, "comp_assessed_value_cents": 26100000, "adjustment_pct": 0.05},
]

# single comp used when only "some included evidence" is needed
SINGLE_COMP = [{"comp_address": "c-1", "sale_price_cents": 27000000,
                "comp_assessed_value_cents": 27000000, "adjustment_pct": 0.00}]


def setup_base(api, accept_fee=False, two_analysts=False,
               jurisdiction_overrides=None, assessment_overrides=None,
               valuation_method="SALES_COMPARISON"):
    """Create analyst(+optional second), client, jurisdiction, fee agreement, parcel, assessment.
    Returns a dict of the created entities and their ids."""
    analyst = new_analyst(api)
    ctx = {"analyst": analyst, "analyst_id": analyst["id"]}
    if two_analysts:
        analyst2 = new_analyst(api)
        ctx["analyst2"] = analyst2
        ctx["analyst2_id"] = analyst2["id"]
    client = new_client(api)
    jurisdiction = new_jurisdiction(api, **(jurisdiction_overrides or {}))
    fee = new_fee_agreement(api, client["id"], accept=accept_fee)
    parcel = new_parcel(api, analyst["id"], client["id"], jurisdiction["id"])
    assessment = new_assessment(api, analyst["id"], parcel["id"], **(assessment_overrides or {}))
    ctx.update({
        "client": client, "client_id": client["id"],
        "jurisdiction": jurisdiction, "jurisdiction_id": jurisdiction["id"],
        "fee_agreement": fee, "fee_agreement_id": fee["id"],
        "parcel": parcel, "parcel_id": parcel["id"],
        "assessment": assessment, "assessment_id": assessment["id"],
        "valuation_method": valuation_method,
    })
    return ctx


def setup_filed_appeal(api, valuation_method="SALES_COMPARISON", comps=None,
                       accept_fee=False, two_analysts=False,
                       jurisdiction_overrides=None, assessment_overrides=None):
    """Base + appeal created + evidence attached + appeal FILED. Returns ctx with 'appeal' (post-file)."""
    ctx = setup_base(api, accept_fee=accept_fee, two_analysts=two_analysts,
                     jurisdiction_overrides=jurisdiction_overrides,
                     assessment_overrides=assessment_overrides,
                     valuation_method=valuation_method)
    appeal = new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"], valuation_method)
    ctx["appeal_id"] = appeal["id"]
    for comp in (comps if comps is not None else SINGLE_COMP):
        add_evidence(api, ctx["analyst_id"], appeal["id"], **comp)
    ctx["appeal"] = do_file_appeal(api, ctx["analyst_id"], appeal["id"])
    return ctx


def setup_decided_appeal(api, decision_value_cents, comps=None, accept_fee=True,
                         valuation_method="SALES_COMPARISON", assessment_overrides=None):
    """Filed appeal -> schedule hearing (rep = analyst2) -> hold -> record decision.
    Returns ctx with 'appeal' (DECIDED) and 'invoice' (the DRAFT invoice)."""
    ctx = setup_filed_appeal(api, valuation_method=valuation_method, comps=comps,
                             accept_fee=accept_fee, two_analysts=True,
                             assessment_overrides=assessment_overrides)
    hearing = schedule_hearing(api, ctx["analyst_id"], ctx["appeal_id"], ctx["analyst2_id"],
                               "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")
    ctx["hearing"] = hearing
    hold_hearing(api, ctx["analyst2_id"], hearing["id"])
    ctx["appeal"] = do_record_decision(api, ctx["analyst_id"], ctx["appeal_id"], decision_value_cents)
    ctx["invoice"] = invoice_for_appeal(api, ctx["appeal_id"])
    return ctx


def setup_issued_invoice(api, decision_value_cents, comps=None,
                         valuation_method="SALES_COMPARISON", assessment_overrides=None):
    """Decided appeal with a positive-savings invoice issued. Returns ctx with issued 'invoice'."""
    ctx = setup_decided_appeal(api, decision_value_cents, comps=comps, accept_fee=True,
                               valuation_method=valuation_method, assessment_overrides=assessment_overrides)
    ctx["invoice"] = do_issue_invoice(api, ctx["invoice"]["id"])
    return ctx
