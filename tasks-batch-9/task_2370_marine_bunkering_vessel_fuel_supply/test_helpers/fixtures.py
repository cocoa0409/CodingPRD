"""Composite state builders.

Every test starts against an empty database, so any precondition beyond a bare
creation has to be built from scratch through the API. These builders do that:
each one drives the real endpoints with the correct role identity and returns the
resources it created, so a test can jump straight to the state it is about.

The builders share a mutable ``ctx`` dictionary whose keys are the domain nouns
(``port``, ``grade``, ``quotes``, ``customer``, ``asset``, ``nomination``,
``order``, ``bdn``, ``invoice``, ``claim``, ``analysis``, ``spill``). A builder
reads what it needs from ``ctx``, performs its step, writes the fresh
representation back and returns ``ctx``, so the tiers chain: asking for a
``build_issued_invoice`` builds everything underneath it. Each tier is also
tolerant of a ``ctx`` that is already past that step, so the chains compose
without repeating work.

Low-level single-step helpers (``clear_order``, ``raise_claim``, ``report_spill``
and friends) are exported too, for tests that need to stop between two steps or
drive a second entity by hand.

Setup calls use ``get_success_data`` so a broken precondition surfaces as a setup
failure rather than as a misleading assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    auto_schedule_payload,
    claim_decision_payload,
    clear_payload,
    complete_pumping_payload,
    compliance_review_payload,
    confirm_containment_payload,
    create_bdn_payload,
    create_customer_payload,
    create_delivery_asset_payload,
    create_delivery_order_payload,
    create_fuel_grade_payload,
    create_index_quote_payload,
    create_invoice_payload,
    create_lab_analysis_payload,
    create_nomination_payload,
    create_port_payload,
    create_quality_claim_payload,
    create_spill_incident_payload,
    credit_review_payload,
    joint_survey_payload,
    quantity_decision_payload,
    set_clock_payload,
)
from .test_users import (
    COMPLIANCE_USER_ID,
    CREDIT_USER_ID,
    LAB_USER_ID,
    OPS_USER_ID,
    SURVEYOR_USER_ID,
    TEST_USERS,
    make_barge_master_headers,
    make_compliance_officer_headers,
    make_credit_controller_headers,
    make_customer_rep_headers,
    make_lab_technician_headers,
    make_ops_coordinator_headers,
    make_surveyor_headers,
)

OPS = TEST_USERS["ops_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
CREDIT = TEST_USERS["credit_controller_headers"]
LAB = TEST_USERS["lab_technician_headers"]

# ─── Canonical instants used across the suite ─────────

CLOCK_BEFORE_WINDOW = "2026-08-05T00:00:00Z"
CLOCK_IN_SLOT = "2026-08-10T06:30:00Z"
CLOCK_AFTER_PUMPING = "2026-08-10T14:30:00Z"

WINDOW_START = "2026-08-10T06:00:00Z"
WINDOW_END = "2026-08-11T06:00:00Z"
SLOT_START = "2026-08-10T06:00:00Z"
SLOT_END = "2026-08-10T12:00:00Z"
PRICING_DATE = "2026-08-10T12:00:00Z"

# The two canonical quotes: one posted before the window, one on the delivery day.
EARLY_QUOTE = {"quote_date": "2026-08-03T00:00:00Z", "price_usd_per_mt": 705.00}
LATE_QUOTE = {"quote_date": "2026-08-10T00:00:00Z", "price_usd_per_mt": 745.50}
DEFAULT_QUOTES = [EARLY_QUOTE, LATE_QUOTE]


# ─── Clock ────────────────────────────────────────────

def set_logical_clock(instant):
    """Move the logical clock; the call returns no resource payload."""
    get_success_data(api_client.set_clock(set_clock_payload(instant), OPS))


# ─── Single-resource creations ────────────────────────

def add_port(**overrides):
    return get_success_data(api_client.create_port(create_port_payload(**overrides), OPS))


def add_fuel_grade(**overrides):
    return get_success_data(
        api_client.create_fuel_grade(create_fuel_grade_payload(**overrides), OPS)
    )


def add_index_quote(grade_id, **overrides):
    return get_success_data(
        api_client.create_index_quote(
            create_index_quote_payload(grade_id, **overrides), CREDIT
        )
    )


def add_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CREDIT)
    )


def add_asset(home_port_id, **overrides):
    return get_success_data(
        api_client.create_delivery_asset(
            create_delivery_asset_payload(home_port_id, **overrides), OPS
        )
    )


def add_nomination(ctx, **overrides):
    """Intake a nomination against the context's customer, port and grade."""
    payload = create_nomination_payload(
        ctx["customer"]["id"], ctx["port"]["id"], ctx["grade"]["id"], **overrides
    )
    ctx["nomination"] = get_success_data(api_client.create_nomination(payload, OPS))
    return ctx["nomination"]


# ─── Reads that refresh the context ───────────────────

def _store(ctx, key, resource, requested_id):
    if ctx is not None and requested_id in (None, ctx.get(key, {}).get("id")):
        ctx[key] = resource
    return resource


def read_port(ctx=None, port_id=None):
    port = get_success_data(api_client.get_port(port_id or ctx["port"]["id"], OPS))
    return _store(ctx, "port", port, port_id)


def read_fuel_grade(ctx=None, grade_id=None):
    grade = get_success_data(api_client.get_fuel_grade(grade_id or ctx["grade"]["id"], OPS))
    return _store(ctx, "grade", grade, grade_id)


def read_customer(ctx=None, customer_id=None):
    customer = get_success_data(
        api_client.get_customer(customer_id or ctx["customer"]["id"], CREDIT)
    )
    return _store(ctx, "customer", customer, customer_id)


def read_credit_exposure(ctx=None, customer_id=None):
    """The computed read that rewrites all five exposure fields before returning."""
    return get_success_data(
        api_client.get_credit_exposure(customer_id or ctx["customer"]["id"], CREDIT)
    )


def read_asset(ctx=None, asset_id=None):
    asset = get_success_data(
        api_client.get_delivery_asset(asset_id or ctx["asset"]["id"], OPS)
    )
    return _store(ctx, "asset", asset, asset_id)


def read_nomination(ctx=None, nomination_id=None):
    nomination = get_success_data(
        api_client.get_nomination(nomination_id or ctx["nomination"]["id"], OPS)
    )
    return _store(ctx, "nomination", nomination, nomination_id)


def read_order(ctx=None, order_id=None):
    order = get_success_data(
        api_client.get_delivery_order(order_id or ctx["order"]["id"], OPS)
    )
    return _store(ctx, "order", order, order_id)


def read_bdn(ctx=None, bdn_id=None):
    bdn = get_success_data(
        api_client.get_bunker_delivery_note(bdn_id or ctx["bdn"]["id"], OPS)
    )
    return _store(ctx, "bdn", bdn, bdn_id)


def read_claim(ctx=None, claim_id=None):
    claim = get_success_data(
        api_client.get_quality_claim(claim_id or ctx["claim"]["id"], SURVEYOR)
    )
    return _store(ctx, "claim", claim, claim_id)


def read_lab_analysis(ctx=None, analysis_id=None):
    analysis = get_success_data(
        api_client.get_lab_analysis(analysis_id or ctx["analysis"]["id"], LAB)
    )
    return _store(ctx, "analysis", analysis, analysis_id)


def read_invoice(ctx=None, invoice_id=None):
    invoice = get_success_data(
        api_client.get_invoice(invoice_id or ctx["invoice"]["id"], CREDIT)
    )
    return _store(ctx, "invoice", invoice, invoice_id)


def read_spill(ctx=None, incident_id=None):
    incident = get_success_data(
        api_client.get_spill_incident(incident_id or ctx["spill"]["id"], COMPLIANCE)
    )
    return _store(ctx, "spill", incident, incident_id)


# ─── Tier 1: reference data ───────────────────────────

def build_reference_data(clock=CLOCK_BEFORE_WINDOW, port=None, grade=None,
                         customer=None, asset=None, quotes=DEFAULT_QUOTES):
    """An Emission Control Area port, one distillate grade with two posted
    quotes, one buyer with a large credit limit and one certified barge.

    Pass ``quotes=[]`` to leave the grade unpriced, or a list of override dicts to
    control the price history the bunker adjustment factor reads.
    """
    ctx = {}
    if clock is not None:
        set_logical_clock(clock)
    ctx["port"] = add_port(**(port or {}))
    ctx["grade"] = add_fuel_grade(**(grade or {}))
    ctx["quotes"] = [add_index_quote(ctx["grade"]["id"], **spec) for spec in quotes]
    ctx["customer"] = add_customer(**(customer or {}))
    ctx["asset"] = add_asset(ctx["port"]["id"], **(asset or {}))
    return ctx


def add_second_port(ctx, **overrides):
    """A second port — Antwerp with a concurrency capacity of one by default."""
    defaults = {"port_code": "BEANR", "name": "Antwerp", "concurrent_ops_capacity": 1}
    defaults.update(overrides)
    ctx["second_port"] = add_port(**defaults)
    return ctx["second_port"]


def add_second_grade(ctx, **overrides):
    """A second grade in the residual segregation family."""
    defaults = {
        "grade_code": "HSFO-380",
        "max_sulfur_pct": 3.500,
        "eca_permitted": False,
        "index_code": "HSFO-ARA",
        "base_barging_rate_usd_per_mt": 7.50,
        "min_barging_fee_usd": 1500.00,
        "cross_contamination_group": "RESIDUAL",
    }
    defaults.update(overrides)
    ctx["second_grade"] = add_fuel_grade(**defaults)
    return ctx["second_grade"]


def add_second_asset(ctx, **overrides):
    """A second barge at the same home port, Bunker Bravo by default."""
    defaults = {"name": "Bunker Bravo"}
    defaults.update(overrides)
    ctx["second_asset"] = add_asset(ctx["port"]["id"], **defaults)
    return ctx["second_asset"]


# ─── Tier 2: nomination progression ───────────────────

def submit_compliance_decision(ctx, decision, reviewer=COMPLIANCE_USER_ID,
                               nomination_id=None):
    nomination = get_success_data(
        api_client.compliance_review(
            nomination_id or ctx["nomination"]["id"],
            compliance_review_payload(decision),
            make_compliance_officer_headers(reviewer),
        )
    )
    return _store(ctx, "nomination", nomination, nomination_id)


def confirm_stem(ctx, nomination_id=None):
    nomination = get_success_data(
        api_client.confirm_nomination(nomination_id or ctx["nomination"]["id"], OPS)
    )
    return _store(ctx, "nomination", nomination, nomination_id)


def build_draft_nomination(ctx=None, nomination=None, **reference_overrides):
    """A nomination fresh from intake: DRAFT fulfilment, PENDING_REVIEW compliance."""
    if ctx is None:
        ctx = build_reference_data(**reference_overrides)
    if "nomination" not in ctx:
        add_nomination(ctx, **(nomination or {}))
    return ctx


def build_approved_nomination(ctx=None, nomination=None, reviewer=COMPLIANCE_USER_ID,
                             **reference_overrides):
    """Compliance APPROVED while fulfilment is still DRAFT."""
    ctx = build_draft_nomination(ctx, nomination=nomination, **reference_overrides)
    if ctx["nomination"]["compliance_status"] != "APPROVED":
        submit_compliance_decision(ctx, "APPROVE", reviewer=reviewer)
    return ctx


def build_confirmed_nomination(ctx=None, nomination=None, reviewer=COMPLIANCE_USER_ID,
                              **reference_overrides):
    """Compliance APPROVED and fulfilment CONFIRMED — ready for a slot."""
    ctx = build_approved_nomination(
        ctx, nomination=nomination, reviewer=reviewer, **reference_overrides
    )
    if ctx["nomination"]["fulfillment_status"] == "DRAFT":
        confirm_stem(ctx)
    return ctx


# ─── Tier 3: delivery orders ──────────────────────────

def schedule_order(ctx, asset_id=None, nomination_id=None, store_as="order", **overrides):
    """Hand-schedule an order, threading the nomination's current version."""
    nomination = (
        read_nomination(nomination_id=nomination_id) if nomination_id
        else ctx["nomination"]
    )
    payload = create_delivery_order_payload(
        nomination["id"],
        asset_id or ctx["asset"]["id"],
        nomination["version"],
        **overrides,
    )
    order = get_success_data(api_client.create_delivery_order(payload, OPS))
    ctx[store_as] = order
    read_nomination(ctx, nomination_id=nomination_id)
    return order


def auto_schedule(ctx, requested_slot_start=SLOT_START, nomination_id=None,
                  store_as="order"):
    """Delegate asset selection and slot derivation to the server."""
    nomination = (
        read_nomination(nomination_id=nomination_id) if nomination_id
        else ctx["nomination"]
    )
    order = get_success_data(
        api_client.auto_schedule_nomination(
            nomination["id"],
            auto_schedule_payload(requested_slot_start, nomination["version"]),
            OPS,
        )
    )
    ctx[store_as] = order
    read_nomination(ctx, nomination_id=nomination_id)
    return order


def build_scheduled_order(ctx=None, order=None, **kwargs):
    """A SCHEDULED order on a SCHEDULED nomination, measurement NOT_STARTED."""
    ctx = build_confirmed_nomination(ctx, **kwargs)
    if "order" not in ctx:
        schedule_order(ctx, **(order or {}))
    return ctx


def clear_order(ctx, order_id=None, clock=CLOCK_IN_SLOT,
                port_clearance_ref="PA-RTM-0001"):
    if clock is not None:
        set_logical_clock(clock)
    order = get_success_data(
        api_client.clear_delivery_order(
            order_id or ctx["order"]["id"], clear_payload(port_clearance_ref), OPS
        )
    )
    return _store(ctx, "order", order, order_id)


def build_cleared_order(ctx=None, clearance_clock=CLOCK_IN_SLOT, **kwargs):
    """Port clearance recorded: logistics CLEARED with cleared_at stamped."""
    ctx = build_scheduled_order(ctx, **kwargs)
    if ctx["order"]["logistics_status"] == "SCHEDULED":
        clear_order(ctx, clock=clearance_clock)
    return ctx


def _asset_id_for(ctx, order_id):
    if order_id is None or order_id == ctx.get("order", {}).get("id"):
        return ctx["order"]["asset_id"]
    return read_order(order_id=order_id)["asset_id"]


def start_pumping(ctx, order_id=None):
    headers = make_barge_master_headers(_asset_id_for(ctx, order_id))
    order = get_success_data(
        api_client.start_pumping(order_id or ctx["order"]["id"], headers)
    )
    return _store(ctx, "order", order, order_id)


def build_pumping_order(ctx=None, **kwargs):
    """The transfer has begun: logistics PUMPING and last_grade_id written."""
    ctx = build_cleared_order(ctx, **kwargs)
    if ctx["order"]["logistics_status"] == "CLEARED":
        start_pumping(ctx)
    return ctx


def complete_pumping(ctx, order_id=None, clock=CLOCK_AFTER_PUMPING, figures=None):
    if clock is not None:
        set_logical_clock(clock)
    headers = make_barge_master_headers(_asset_id_for(ctx, order_id))
    order = get_success_data(
        api_client.complete_pumping(
            order_id or ctx["order"]["id"],
            complete_pumping_payload(**(figures or {})),
            headers,
        )
    )
    return _store(ctx, "order", order, order_id)


def build_delivered_order(ctx=None, figures=None, pumping_clock=CLOCK_AFTER_PUMPING,
                          **kwargs):
    """Transfer closed: logistics DELIVERED with the three figures recorded.

    For a `SUPPLIER_FIGURES` buyer the measurement dimension is already AGREED
    when this returns; for a `JOINT_SURVEY_MANDATORY` buyer it stops at
    FIGURES_RECORDED awaiting an independent figure.
    """
    ctx = build_pumping_order(ctx, **kwargs)
    if ctx["order"]["logistics_status"] == "PUMPING":
        complete_pumping(ctx, clock=pumping_clock, figures=figures)
    return ctx


def file_joint_survey(ctx, surveyed_mt, order_id=None):
    order = get_success_data(
        api_client.file_joint_survey(
            order_id or ctx["order"]["id"], joint_survey_payload(surveyed_mt), SURVEYOR
        )
    )
    return _store(ctx, "order", order, order_id)


def submit_quantity_decision(ctx, decision, order_id=None, headers=None):
    """AGREE is the surveyor's call; DISPUTE is the buyer representative's."""
    if headers is None:
        headers = (
            SURVEYOR if decision == "AGREE"
            else make_customer_rep_headers(ctx["customer"]["id"])
        )
    order = get_success_data(
        api_client.submit_quantity_decision(
            order_id or ctx["order"]["id"], quantity_decision_payload(decision), headers
        )
    )
    return _store(ctx, "order", order, order_id)


def build_joint_survey_context(**kwargs):
    """Reference data whose buyer contracts on JOINT_SURVEY_MANDATORY."""
    kwargs.setdefault("customer", {"settlement_basis": "JOINT_SURVEY_MANDATORY"})
    return build_reference_data(**kwargs)


def build_agreed_order(ctx=None, surveyed_mt=1191.850, **kwargs):
    """A delivered order whose measurement dimension is AGREED, whichever branch
    the buyer's settlement basis dictates."""
    ctx = build_delivered_order(ctx, **kwargs)
    if ctx["order"]["measurement_status"] == "FIGURES_RECORDED":
        file_joint_survey(ctx, surveyed_mt)
        submit_quantity_decision(ctx, "AGREE")
    return ctx


def cancel_order(ctx, order_id=None):
    order = get_success_data(
        api_client.cancel_delivery_order(order_id or ctx["order"]["id"], OPS)
    )
    return _store(ctx, "order", order, order_id)


# ─── Tier 4: notes and samples ────────────────────────

def issue_bdn(ctx, order_id=None, issuer=OPS_USER_ID, **overrides):
    payload = create_bdn_payload(order_id or ctx["order"]["id"], **overrides)
    ctx["bdn"] = get_success_data(
        api_client.create_bunker_delivery_note(
            payload, make_ops_coordinator_headers(issuer)
        )
    )
    return ctx["bdn"]


def build_issued_bdn(ctx=None, bdn=None, **kwargs):
    """A MARPOL note in ISSUED status with its retained sample RETAINED."""
    ctx = build_agreed_order(ctx, **kwargs)
    if "bdn" not in ctx:
        issue_bdn(ctx, **(bdn or {}))
    return ctx


def release_sample(ctx, bdn_id=None):
    bdn = get_success_data(api_client.release_sample(bdn_id or ctx["bdn"]["id"], OPS))
    return _store(ctx, "bdn", bdn, bdn_id)


def build_released_sample(ctx=None, **kwargs):
    """The retained sample has gone to the laboratory: custody RELEASED_TO_LAB."""
    ctx = build_issued_bdn(ctx, **kwargs)
    if ctx["bdn"]["sample_custody_status"] != "RELEASED_TO_LAB":
        release_sample(ctx)
    return ctx


# ─── Tier 5: invoicing ────────────────────────────────

def raise_invoice(ctx, order_id=None, **overrides):
    payload = create_invoice_payload(order_id or ctx["order"]["id"], **overrides)
    ctx["invoice"] = get_success_data(api_client.create_invoice(payload, CREDIT))
    return ctx["invoice"]


def build_provisional_invoice(ctx=None, invoice=None, **kwargs):
    """A PROVISIONAL invoice with all four components and the adjustment factor
    already derived."""
    ctx = build_issued_bdn(ctx, **kwargs)
    if "invoice" not in ctx:
        raise_invoice(ctx, **(invoice or {}))
    return ctx


def issue_invoice(ctx, invoice_id=None):
    invoice = get_success_data(
        api_client.issue_invoice(invoice_id or ctx["invoice"]["id"], CREDIT)
    )
    return _store(ctx, "invoice", invoice, invoice_id)


def build_issued_invoice(ctx=None, **kwargs):
    """An ISSUED invoice: the receivable is on the buyer's books, the standing has
    been re-derived and the nomination has closed."""
    ctx = build_provisional_invoice(ctx, **kwargs)
    if ctx["invoice"]["status"] == "PROVISIONAL":
        issue_invoice(ctx)
        read_customer(ctx)
        read_nomination(ctx)
    return ctx


def void_invoice(ctx, invoice_id=None):
    invoice = get_success_data(
        api_client.void_invoice(invoice_id or ctx["invoice"]["id"], CREDIT)
    )
    return _store(ctx, "invoice", invoice, invoice_id)


# ─── Tier 6: claims, analyses and remediation ─────────

def raise_claim(ctx, bdn_id=None, **overrides):
    payload = create_quality_claim_payload(bdn_id or ctx["bdn"]["id"], **overrides)
    ctx["claim"] = get_success_data(
        api_client.create_quality_claim(
            payload, make_customer_rep_headers(ctx["customer"]["id"])
        )
    )
    return ctx["claim"]


def build_submitted_claim(ctx=None, claim=None, **kwargs):
    """A claim in SUBMITTED with analysis_round 0 and credit 0.00, standing on an
    issued invoice and a released sample."""
    ctx = build_issued_invoice(ctx, **kwargs)
    if ctx["bdn"]["sample_custody_status"] != "RELEASED_TO_LAB":
        release_sample(ctx)
    if "claim" not in ctx:
        raise_claim(ctx, **(claim or {}))
    return ctx


def file_lab_analysis(ctx, claim_id=None, analyst=LAB_USER_ID, **overrides):
    claim = read_claim(ctx, claim_id=claim_id)
    payload = create_lab_analysis_payload(claim["id"], claim["version"], **overrides)
    ctx["analysis"] = get_success_data(
        api_client.create_lab_analysis(payload, make_lab_technician_headers(analyst))
    )
    read_claim(ctx, claim_id=claim_id)
    return ctx["analysis"]


def build_analysed_claim(ctx=None, measured_sulfur_pct=0.135, **kwargs):
    """A claim in UNDER_ANALYSIS with a first-round analysis filed and judged."""
    ctx = build_submitted_claim(ctx, **kwargs)
    if "analysis" not in ctx:
        file_lab_analysis(ctx, measured_sulfur_pct=measured_sulfur_pct)
    return ctx


def submit_claim_decision(ctx, decision, claim_id=None, surveyor=SURVEYOR_USER_ID,
                          **overrides):
    claim = get_success_data(
        api_client.claim_decision(
            claim_id or ctx["claim"]["id"],
            claim_decision_payload(decision, **overrides),
            make_surveyor_headers(surveyor),
        )
    )
    return _store(ctx, "claim", claim, claim_id)


def build_proposed_claim(ctx=None, measured_sulfur_pct=0.135,
                         remediation_type="PRICE_ALLOWANCE", **kwargs):
    """A claim in REMEDIATION_PROPOSED with credit_usd computed."""
    ctx = build_analysed_claim(ctx, measured_sulfur_pct=measured_sulfur_pct, **kwargs)
    if ctx["claim"]["status"] == "UNDER_ANALYSIS":
        submit_claim_decision(ctx, "PROPOSE", remediation_type=remediation_type)
    return ctx


def request_retest(ctx, claim_id=None):
    claim = get_success_data(
        api_client.request_retest(
            claim_id or ctx["claim"]["id"],
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
    )
    return _store(ctx, "claim", claim, claim_id)


def accept_remediation(ctx, claim_id=None, acceptor=CREDIT_USER_ID):
    claim = get_success_data(
        api_client.accept_remediation(
            claim_id or ctx["claim"]["id"], make_credit_controller_headers(acceptor)
        )
    )
    return _store(ctx, "claim", claim, claim_id)


def build_accepted_claim(ctx=None, **kwargs):
    """A claim in REMEDIATION_ACCEPTED whose credit has been booked onto the
    issued invoice and cascaded into the buyer's balance."""
    ctx = build_proposed_claim(ctx, **kwargs)
    if ctx["claim"]["status"] == "REMEDIATION_PROPOSED":
        accept_remediation(ctx)
        read_invoice(ctx)
        read_customer(ctx)
    return ctx


# ─── Spill incidents ──────────────────────────────────

def report_spill(ctx, order_id=None, **overrides):
    headers = make_barge_master_headers(_asset_id_for(ctx, order_id))
    payload = create_spill_incident_payload(order_id or ctx["order"]["id"], **overrides)
    ctx["spill"] = get_success_data(api_client.create_spill_incident(payload, headers))
    return ctx["spill"]


def build_open_spill(ctx=None, spill=None, **kwargs):
    """A reported incident, its own order suspended and the asset's score
    recomputed to absorb the penalty points."""
    ctx = build_cleared_order(ctx, **kwargs)
    if "spill" not in ctx:
        report_spill(ctx, **(spill or {}))
        read_order(ctx)
        read_asset(ctx)
    return ctx


def build_quarantined_asset(ctx=None, **kwargs):
    """A major spill — 250.00 litres with no boom in the water — has quarantined
    the context's asset and left the incident OPEN."""
    kwargs.setdefault("spill", {"volume_liters": 250.00, "boom_deployed": False})
    return build_open_spill(ctx, **kwargs)


def confirm_containment(ctx, incident_id=None, response_ref="RESP-RTM-0001"):
    incident = get_success_data(
        api_client.confirm_containment(
            incident_id or ctx["spill"]["id"],
            confirm_containment_payload(response_ref),
            COMPLIANCE,
        )
    )
    return _store(ctx, "spill", incident, incident_id)


def close_spill(ctx, incident_id=None):
    incident = get_success_data(
        api_client.close_spill_incident(incident_id or ctx["spill"]["id"], COMPLIANCE)
    )
    return _store(ctx, "spill", incident, incident_id)


def build_closed_spill(ctx=None, **kwargs):
    """Containment confirmed and the incident CLOSED, so a quarantine may lift."""
    ctx = build_open_spill(ctx, **kwargs)
    if ctx["spill"]["status"] == "OPEN":
        confirm_containment(ctx)
        close_spill(ctx)
    return ctx


def return_asset_to_service(ctx, asset_id=None):
    asset = get_success_data(
        api_client.return_asset_to_service(asset_id or ctx["asset"]["id"], COMPLIANCE)
    )
    return _store(ctx, "asset", asset, asset_id)


# ─── Credit shaping ───────────────────────────────────

def apply_credit_review(ctx, customer_id=None, **payload):
    customer = get_success_data(
        api_client.credit_review(
            customer_id or ctx["customer"]["id"], credit_review_payload(**payload), CREDIT
        )
    )
    return _store(ctx, "customer", customer, customer_id)


def force_credit_hold(ctx, credit_limit_usd=None):
    """Shrink the credit limit to the settled receivable so utilisation reaches
    1.0000 and the buyer's standing re-derives to HOLD."""
    if credit_limit_usd is None:
        credit_limit_usd = round(read_customer(ctx)["outstanding_balance_usd"], 2)
    return apply_credit_review(ctx, credit_limit_usd=credit_limit_usd)


# ─── Multi-entity contexts ────────────────────────────

def build_two_asset_context(second_asset=None, **kwargs):
    """Reference data plus a second barge, for asset-selection, slot-conflict and
    quarantine-cascade work."""
    ctx = build_reference_data(**kwargs)
    add_second_asset(ctx, **(second_asset or {}))
    return ctx


def add_confirmed_nomination(ctx, store_as="second_nomination", reviewer=COMPLIANCE_USER_ID,
                             **overrides):
    """Take in, approve and confirm one more stem on the same buyer, port and
    grade, leaving ``ctx["nomination"]`` pointing at the original."""
    first = ctx.get("nomination")
    add_nomination(ctx, **overrides)
    submit_compliance_decision(ctx, "APPROVE", reviewer=reviewer)
    confirm_stem(ctx)
    ctx[store_as] = ctx["nomination"]
    if first is not None:
        ctx["nomination"] = read_nomination(nomination_id=first["id"])
    return ctx[store_as]


def build_two_confirmed_nominations(**kwargs):
    """Two confirmed stems on the same buyer, port and grade, so two slots can
    compete for the same asset or the same port."""
    ctx = build_confirmed_nomination(**kwargs)
    add_confirmed_nomination(ctx)
    return ctx


__all__ = [
    "OPS",
    "COMPLIANCE",
    "SURVEYOR",
    "CREDIT",
    "LAB",
    "CLOCK_BEFORE_WINDOW",
    "CLOCK_IN_SLOT",
    "CLOCK_AFTER_PUMPING",
    "WINDOW_START",
    "WINDOW_END",
    "SLOT_START",
    "SLOT_END",
    "PRICING_DATE",
    "EARLY_QUOTE",
    "LATE_QUOTE",
    "DEFAULT_QUOTES",
    "set_logical_clock",
    "add_port",
    "add_fuel_grade",
    "add_index_quote",
    "add_customer",
    "add_asset",
    "add_nomination",
    "add_second_port",
    "add_second_grade",
    "add_second_asset",
    "add_confirmed_nomination",
    "read_port",
    "read_fuel_grade",
    "read_customer",
    "read_credit_exposure",
    "read_asset",
    "read_nomination",
    "read_order",
    "read_bdn",
    "read_claim",
    "read_lab_analysis",
    "read_invoice",
    "read_spill",
    "build_reference_data",
    "build_joint_survey_context",
    "build_two_asset_context",
    "build_two_confirmed_nominations",
    "build_draft_nomination",
    "build_approved_nomination",
    "build_confirmed_nomination",
    "submit_compliance_decision",
    "confirm_stem",
    "schedule_order",
    "auto_schedule",
    "build_scheduled_order",
    "clear_order",
    "build_cleared_order",
    "start_pumping",
    "build_pumping_order",
    "complete_pumping",
    "build_delivered_order",
    "file_joint_survey",
    "submit_quantity_decision",
    "build_agreed_order",
    "cancel_order",
    "issue_bdn",
    "build_issued_bdn",
    "release_sample",
    "build_released_sample",
    "raise_invoice",
    "build_provisional_invoice",
    "issue_invoice",
    "build_issued_invoice",
    "void_invoice",
    "raise_claim",
    "build_submitted_claim",
    "file_lab_analysis",
    "build_analysed_claim",
    "submit_claim_decision",
    "build_proposed_claim",
    "request_retest",
    "accept_remediation",
    "build_accepted_claim",
    "report_spill",
    "build_open_spill",
    "build_quarantined_asset",
    "confirm_containment",
    "close_spill",
    "build_closed_spill",
    "return_asset_to_service",
    "apply_credit_review",
    "force_credit_hold",
]
