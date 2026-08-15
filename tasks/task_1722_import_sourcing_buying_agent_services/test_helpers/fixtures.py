"""Composite setup helpers.

Multi-step arrangement builders used by the test suite. Every helper builds
its preconditions from scratch through the public API (the server restarts
before every test, so nothing persists between tests). Setup calls go through
get_success_data so a setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_DELIVERY_MONTH,
    DEFAULT_DOC_EXPIRES_AT,
    DEFAULT_INSPECTION_DATE,
    DEFAULT_VALID_UNTIL,
    GRADE_A_AUDIT,
    REQUIRED_DOCS,
    TEST_DEFAULTS,
)
from .factories import (
    accept_quotation_payload,
    amend_po_payload,
    create_agent_payload,
    create_audit_payload,
    create_buyer_payload,
    create_compliance_document_payload,
    create_factory_payload,
    create_inspection_payload,
    create_inspector_payload,
    create_milestone_payload,
    create_quality_claim_payload,
    create_quotation_payload,
    create_sample_payload,
    create_shipment_payload,
    create_sourcing_request_payload,
    handover_payload,
    record_result_payload,
    resubmit_sample_payload,
    review_sample_payload,
    submit_milestone_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_manager_headers,
    make_factory_rep_headers,
    make_inspector_headers,
    make_sourcing_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _setup_failed(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code}: {resp.text}"
    )


def _ok(resp, step):
    if resp.status_code // 100 != 2:
        _setup_failed(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_buyer(name="Buyer One", country_code="US") -> dict:
    resp = api_client.create_buyer(create_buyer_payload(name=name, country_code=country_code), ADMIN)
    return _ok(resp, "create_buyer")


def create_agent(name="Agent One", agency_name="AgencyCo") -> dict:
    resp = api_client.create_agent(create_agent_payload(name=name, agency_name=agency_name), ADMIN)
    return _ok(resp, "create_agent")


def create_inspector(name="Inspector One", region="CN-South") -> dict:
    resp = api_client.create_inspector(create_inspector_payload(name=name, region=region), ADMIN)
    return _ok(resp, "create_inspector")


def create_factory(agent_id, name="Factory One", country_code="CN",
                   monthly_capacity_units=TEST_DEFAULTS["MONTHLY_CAPACITY_UNITS"]) -> dict:
    resp = api_client.create_factory(
        create_factory_payload(
            name=name, country_code=country_code,
            monthly_capacity_units=monthly_capacity_units,
        ),
        make_sourcing_agent_headers(agent_id),
    )
    return _ok(resp, "create_factory")


def create_audit(factory_id, agent_id, **overrides) -> dict:
    resp = api_client.create_audit(
        factory_id, create_audit_payload(**overrides), make_sourcing_agent_headers(agent_id)
    )
    return _ok(resp, "create_audit")


def approve_audit(audit_id) -> dict:
    return _ok(api_client.approve_audit(audit_id, COMPLIANCE), "approve_audit")


def reject_audit(audit_id) -> dict:
    return _ok(api_client.reject_audit(audit_id, COMPLIANCE), "reject_audit")


def make_graded_factory(agent_id, audit_overrides=None, **factory_kwargs) -> dict:
    """Factory plus an APPROVED ONSITE audit (default inputs score 92 -> A)."""
    factory = create_factory(agent_id, **factory_kwargs)
    audit = create_audit(factory["id"], agent_id, **(audit_overrides or {}))
    approve_audit(audit["id"])
    return api_client.get_factory(factory["id"], ADMIN).json()["data"]


def make_grade_a_factory(agent_id, **factory_kwargs) -> dict:
    return make_graded_factory(agent_id, audit_overrides=None, **factory_kwargs)


# ---------------------------------------------------------------------------
# Tier 1b: compliance documents
# ---------------------------------------------------------------------------

def upload_and_verify_doc(factory_id, agent_id, doc_type,
                          expires_at=DEFAULT_DOC_EXPIRES_AT,
                          issued_date="2026-01-01") -> dict:
    doc = _ok(
        api_client.create_compliance_document(
            factory_id,
            create_compliance_document_payload(
                doc_type=doc_type, issued_date=issued_date, expires_at=expires_at
            ),
            make_sourcing_agent_headers(agent_id),
        ),
        "create_compliance_document",
    )
    return _ok(
        api_client.verify_compliance_document(doc["id"], COMPLIANCE),
        "verify_compliance_document",
    )


def setup_compliance_docs(factory_id, agent_id, category,
                          expires_at=DEFAULT_DOC_EXPIRES_AT) -> list:
    """Upload + verify every doc type the category requires (PRD posture rule)."""
    return [
        upload_and_verify_doc(factory_id, agent_id, dt, expires_at=expires_at)
        for dt in REQUIRED_DOCS[category]
    ]


# ---------------------------------------------------------------------------
# Tier 2: engagement hierarchy (buyer -> SR -> quotation -> PO)
# ---------------------------------------------------------------------------

def create_sourcing_request(buyer_id, agent_id, **overrides) -> dict:
    resp = api_client.create_sourcing_request(
        create_sourcing_request_payload(assigned_agent_id=agent_id, **overrides),
        make_buyer_manager_headers(buyer_id),
    )
    return _ok(resp, "create_sourcing_request")


def create_sample(sr_id, agent_id, notes="v0") -> dict:
    resp = api_client.create_sample(
        sr_id, create_sample_payload(notes=notes), make_sourcing_agent_headers(agent_id)
    )
    return _ok(resp, "create_sample")


def create_quotation(sr_id, factory_id, **overrides) -> dict:
    resp = api_client.create_quotation(
        sr_id, create_quotation_payload(**overrides), make_factory_rep_headers(factory_id)
    )
    return _ok(resp, "create_quotation")


def get_quotation(quotation_id) -> dict:
    return _ok(api_client.get_quotation(quotation_id, ADMIN), "get_quotation")


def get_purchase_order(po_id) -> dict:
    return _ok(api_client.get_purchase_order(po_id, ADMIN), "get_purchase_order")


def get_factory(factory_id) -> dict:
    return _ok(api_client.get_factory(factory_id, ADMIN), "get_factory")


def get_buyer(buyer_id) -> dict:
    return _ok(api_client.get_buyer(buyer_id, ADMIN), "get_buyer")


def accept_quotation(buyer_id, quotation, ordered_qty,
                     delivery_month=DEFAULT_DELIVERY_MONTH,
                     freight_cents=None, insurance_cents=None) -> dict:
    """Accept a quotation, echoing its current version (OCC)."""
    version = quotation["version"] if isinstance(quotation, dict) else get_quotation(quotation)["version"]
    qid = quotation["id"] if isinstance(quotation, dict) else quotation
    extra = {}
    if freight_cents is not None:
        extra["freight_cents"] = freight_cents
    if insurance_cents is not None:
        extra["insurance_cents"] = insurance_cents
    resp = api_client.accept_quotation(
        qid,
        accept_quotation_payload(ordered_qty, version, delivery_month=delivery_month, **extra),
        make_buyer_manager_headers(buyer_id),
    )
    return _ok(resp, "accept_quotation")


def setup_po_scenario(category="APPAREL", unit_price_cents=TEST_DEFAULTS["UNIT_PRICE_CENTS"],
                      moq=TEST_DEFAULTS["MOQ"], ordered_qty=TEST_DEFAULTS["ORDERED_QTY"],
                      delivery_month=DEFAULT_DELIVERY_MONTH,
                      monthly_capacity_units=TEST_DEFAULTS["MONTHLY_CAPACITY_UNITS"],
                      commission_mode="FOB", with_docs=True,
                      docs_expires_at=DEFAULT_DOC_EXPIRES_AT,
                      with_second_agent=False, with_inspector=False,
                      buyer_name="Buyer One", agent_name="Agent One",
                      factory_name="Factory One", factory_country="CN",
                      sr_quantity=None, sr_title="Goods",
                      freight_cents=None, insurance_cents=None) -> dict:
    """Full happy-path chain through an ACTIVE purchase order.

    Returns a context dict: buyer, agent, agent2?, inspector?, factory, sr,
    quotation, po.
    """
    buyer = create_buyer(buyer_name)
    agent = create_agent(agent_name)
    ctx = {"buyer": buyer, "agent": agent}
    if with_second_agent:
        ctx["agent2"] = create_agent("Agent Two")
    if with_inspector:
        ctx["inspector"] = create_inspector()
    factory = make_grade_a_factory(
        agent["id"], name=factory_name, country_code=factory_country,
        monthly_capacity_units=monthly_capacity_units,
    )
    ctx["factory"] = factory
    if with_docs:
        ctx["docs"] = setup_compliance_docs(
            factory["id"], agent["id"], category, expires_at=docs_expires_at
        )
    sr = create_sourcing_request(
        buyer["id"], agent["id"],
        title=sr_title, product_category=category,
        target_price_cents=unit_price_cents,
        quantity=sr_quantity if sr_quantity is not None else ordered_qty,
        commission_mode=commission_mode,
    )
    ctx["sr"] = sr
    quotation = create_quotation(sr["id"], factory["id"],
                                 unit_price_cents=unit_price_cents, moq=moq)
    ctx["quotation"] = quotation
    po = accept_quotation(buyer["id"], quotation, ordered_qty,
                          delivery_month=delivery_month,
                          freight_cents=freight_cents,
                          insurance_cents=insurance_cents)
    ctx["po"] = po
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: production lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_milestone(po_id, agent_id, name="FULL", weight_pct=100) -> dict:
    resp = api_client.create_milestone(
        po_id, create_milestone_payload(name=name, weight_pct=weight_pct),
        make_sourcing_agent_headers(agent_id),
    )
    return _ok(resp, "create_milestone")


def submit_milestone(milestone_id, factory_id, evidence_note="done") -> dict:
    resp = api_client.submit_milestone(
        milestone_id, submit_milestone_payload(evidence_note=evidence_note),
        make_factory_rep_headers(factory_id),
    )
    return _ok(resp, "submit_milestone")


def verify_milestone(milestone_id, agent_id) -> dict:
    return _ok(api_client.verify_milestone(milestone_id, make_sourcing_agent_headers(agent_id)),
               "verify_milestone")


def reject_milestone(milestone_id, agent_id) -> dict:
    return _ok(api_client.reject_milestone(milestone_id, make_sourcing_agent_headers(agent_id)),
               "reject_milestone")


def advance_to_production_complete(ctx) -> dict:
    """Create the FULL(100) plan, submit and verify it. Returns the milestone."""
    po = ctx["po"]
    milestone = create_milestone(po["id"], ctx["agent"]["id"], name="FULL", weight_pct=100)
    submit_milestone(milestone["id"], ctx["factory"]["id"])
    verify_milestone(milestone["id"], ctx["agent"]["id"])
    ctx["milestone"] = milestone
    return milestone


def book_inspection(po_id, agent_id, inspector_id, inspection_type="PSI",
                    scheduled_date=DEFAULT_INSPECTION_DATE, duration_days=1,
                    lot_size=TEST_DEFAULTS["ORDERED_QTY"]) -> dict:
    resp = api_client.create_inspection(
        po_id,
        create_inspection_payload(
            inspector_id=inspector_id, inspection_type=inspection_type,
            scheduled_date=scheduled_date, duration_days=duration_days, lot_size=lot_size,
        ),
        make_sourcing_agent_headers(agent_id),
    )
    return _ok(resp, "create_inspection")


def record_result(inspection_id, inspector_id, defects_critical=0,
                  defects_major=0, defects_minor=0) -> dict:
    resp = api_client.record_inspection_result(
        inspection_id,
        record_result_payload(defects_critical, defects_major, defects_minor),
        make_inspector_headers(inspector_id),
    )
    return _ok(resp, "record_inspection_result")


def book_and_pass_psi(ctx, lot_size=None, scheduled_date=DEFAULT_INSPECTION_DATE,
                      inspector=None, duration_days=1) -> dict:
    """Book a PSI and record a clean (all-zero) result. Returns the inspection."""
    inspector = inspector or ctx.get("inspector") or create_inspector()
    ctx["inspector"] = inspector
    inspection = book_inspection(
        ctx["po"]["id"], ctx["agent"]["id"], inspector["id"],
        inspection_type="PSI", scheduled_date=scheduled_date,
        duration_days=duration_days,
        lot_size=lot_size if lot_size is not None else ctx["po"]["ordered_qty"],
    )
    return record_result(inspection["id"], inspector["id"], 0, 0, 0)


# ---------------------------------------------------------------------------
# Tier 4/5: shipment, close, and claims
# ---------------------------------------------------------------------------

def book_shipment(po_id, agent_id, shipped_qty, vessel_ref="V1") -> dict:
    resp = api_client.create_shipment(
        po_id, create_shipment_payload(shipped_qty=shipped_qty, vessel_ref=vessel_ref),
        make_sourcing_agent_headers(agent_id),
    )
    return _ok(resp, "create_shipment")


def handover_documents(shipment_id, factory_id, doc_refs=None) -> dict:
    resp = api_client.handover_shipment_documents(
        shipment_id, handover_payload(doc_refs=doc_refs or ["BL-1"]),
        make_factory_rep_headers(factory_id),
    )
    return _ok(resp, "handover_shipment_documents")


def confirm_receipt(shipment_id, buyer_id) -> dict:
    return _ok(api_client.confirm_shipment_receipt(
        shipment_id, make_buyer_manager_headers(buyer_id)), "confirm_shipment_receipt")


def ship_and_close(ctx, vessel_ref="V1") -> dict:
    """Ship the PO's full open quantity, hand over docs, confirm receipt.

    After confirmation the PO is CLOSED (open_qty 0, single live shipment
    DELIVERED). Returns the shipment; refreshes ctx["po"] to the closed PO.
    """
    po = get_purchase_order(ctx["po"]["id"])
    shipment = book_shipment(po["id"], ctx["agent"]["id"], po["open_qty"], vessel_ref)
    handover_documents(shipment["id"], ctx["factory"]["id"])
    confirm_receipt(shipment["id"], ctx["buyer"]["id"])
    ctx["shipment"] = shipment
    ctx["po"] = get_purchase_order(po["id"])
    return shipment


def setup_closed_po(category="APPAREL", unit_price_cents=TEST_DEFAULTS["UNIT_PRICE_CENTS"],
                    ordered_qty=TEST_DEFAULTS["ORDERED_QTY"],
                    delivery_month=DEFAULT_DELIVERY_MONTH,
                    monthly_capacity_units=TEST_DEFAULTS["MONTHLY_CAPACITY_UNITS"],
                    commission_mode="FOB",
                    docs_expires_at=DEFAULT_DOC_EXPIRES_AT,
                    with_second_agent=True,
                    inspection_date=DEFAULT_INSPECTION_DATE,
                    freight_cents=None, insurance_cents=None) -> dict:
    """Full lifecycle: buyer/agent(+adjudicator)/inspector/factory -> PO CLOSED."""
    ctx = setup_po_scenario(
        category=category, unit_price_cents=unit_price_cents, ordered_qty=ordered_qty,
        delivery_month=delivery_month, monthly_capacity_units=monthly_capacity_units,
        commission_mode=commission_mode, with_docs=True,
        docs_expires_at=docs_expires_at, with_second_agent=with_second_agent,
        with_inspector=True, freight_cents=freight_cents, insurance_cents=insurance_cents,
    )
    advance_to_production_complete(ctx)
    book_and_pass_psi(ctx, scheduled_date=inspection_date)
    ship_and_close(ctx)
    return ctx


def file_claim(po_id, buyer_id, items) -> dict:
    resp = api_client.create_quality_claim(
        po_id, create_quality_claim_payload(items=items),
        make_buyer_manager_headers(buyer_id),
    )
    return _ok(resp, "create_quality_claim")


def approve_claim(claim_id, adjudicator_agent_id) -> dict:
    return _ok(api_client.approve_quality_claim(
        claim_id, make_sourcing_agent_headers(adjudicator_agent_id)), "approve_quality_claim")


def get_quality_claim(claim_id) -> dict:
    return _ok(api_client.get_quality_claim(claim_id, ADMIN), "get_quality_claim")


def get_shipment(shipment_id) -> dict:
    return _ok(api_client.get_shipment(shipment_id, ADMIN), "get_shipment")


def get_inspection(inspection_id) -> dict:
    return _ok(api_client.get_inspection(inspection_id, ADMIN), "get_inspection")


def get_sample(sample_id) -> dict:
    return _ok(api_client.get_sample(sample_id, ADMIN), "get_sample")


def get_milestone(milestone_id) -> dict:
    return _ok(api_client.get_milestone(milestone_id, ADMIN), "get_milestone")


def get_compliance_document(doc_id) -> dict:
    return _ok(api_client.get_compliance_document(doc_id, ADMIN), "get_compliance_document")


def get_sourcing_request(sr_id) -> dict:
    return _ok(api_client.get_sourcing_request(sr_id, ADMIN), "get_sourcing_request")


def get_agent(agent_id) -> dict:
    return _ok(api_client.get_agent(agent_id, ADMIN), "get_agent")


def review_sample(sample_id, buyer_id, decision, comments=None) -> dict:
    payload = review_sample_payload(decision=decision)
    if comments is not None:
        payload["comments"] = comments
    resp = api_client.review_sample(sample_id, payload, make_buyer_manager_headers(buyer_id))
    return _ok(resp, "review_sample")


def resubmit_sample(sample_id, agent_id, notes="resubmission") -> dict:
    resp = api_client.resubmit_sample(
        sample_id, resubmit_sample_payload(notes=notes), make_sourcing_agent_headers(agent_id)
    )
    return _ok(resp, "resubmit_sample")


def counter_quotation(quotation_id, headers, unit_price_cents, version) -> dict:
    resp = api_client.counter_quotation(
        quotation_id,
        {"unit_price_cents": unit_price_cents, "expected_quotation_version": version},
        headers,
    )
    return _ok(resp, "counter_quotation")


def amend_po(po_id, agent_id, expected_po_version, **changes) -> dict:
    resp = api_client.amend_purchase_order(
        po_id, amend_po_payload(expected_po_version, **changes),
        make_sourcing_agent_headers(agent_id),
    )
    return _ok(resp, "amend_purchase_order")


def set_clock(to_iso8601) -> dict:
    return _ok(api_client.set_clock(to_iso8601, ADMIN), "set_clock")
