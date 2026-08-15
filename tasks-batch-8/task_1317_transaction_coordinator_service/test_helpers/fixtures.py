"""Composite setup helpers. Every helper builds preconditions from scratch using only
PRD-declared endpoints (the runner restarts the server before every test, so each test
starts against an empty database).

Identity threading: after creating a Coordinator, every Coordinator-role call in the
chain uses make_coordinator_headers(coordinator["id"]); likewise Agent-role calls use
make_agent_headers(agent["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_coordinator_payload,
    create_agent_payload,
    create_template_payload,
    create_subscription_payload,
    create_file_payload,
    create_purchase_file_payload,
    create_document_payload,
    create_amendment_payload,
)
from .test_users import TEST_USERS, make_coordinator_headers, make_agent_headers

# -----------------------------------------------------------------------------
# Canonical scenario content (names/dates shared across test files)
# -----------------------------------------------------------------------------

STANDARD_MILESTONE_DEFS = [
    {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
    {"name": "Inspection Period", "offset_days": 7, "mandatory": True},
    {"name": "Financing Approval", "offset_days": 21, "mandatory": False},
]
SIMPLE_MILESTONE_DEFS = [{"name": "Listing Paperwork", "offset_days": 5, "mandatory": False}]
EFFECTIVE_DATE = "2026-08-03"
CLOSING_DATE = "2026-08-31"
LIST_PRICE_CENTS = 45000000


# -----------------------------------------------------------------------------
# Tier 1: base actors
# -----------------------------------------------------------------------------

def make_coordinator(name="Casey Coord"):
    """Register a coordinator. Returns (coordinator, coordinator_headers)."""
    payload = create_coordinator_payload(full_name=name)
    resp = api_client.create_coordinator(payload, TEST_USERS["admin_headers"])
    coord = get_success_data(resp)
    return coord, make_coordinator_headers(coord["id"])


def make_agent(coord_headers, name="Seller Sam", brokerage="Berkshire"):
    """Add an agent to the acting coordinator's roster. Returns (agent, agent_headers)."""
    resp = api_client.create_agent(
        create_agent_payload(full_name=name, brokerage=brokerage), coord_headers
    )
    agent = get_success_data(resp)
    return agent, make_agent_headers(agent["id"])


def make_template(state_code="TX", contract_type="LISTING_ONLY",
                  milestone_defs=None, required_doc_types=None, publish=True):
    """Create (and by default publish) a checklist template. Returns template dict."""
    payload = create_template_payload(
        state_code=state_code,
        contract_type=contract_type,
        milestone_defs=milestone_defs if milestone_defs is not None else list(SIMPLE_MILESTONE_DEFS),
        required_doc_types=required_doc_types if required_doc_types is not None else [],
    )
    resp = api_client.create_template(payload, TEST_USERS["admin_headers"])
    tmpl = get_success_data(resp)
    if publish:
        resp = api_client.publish_template(tmpl["id"], TEST_USERS["admin_headers"])
        tmpl = get_success_data(resp)
    return tmpl


def make_subscription(coord_headers, monthly_fee_cents=29900, included_files_quota=1,
                      overage_fee_cents=34900):
    """Open a subscription for the acting coordinator. Returns subscription dict."""
    resp = api_client.create_subscription(
        create_subscription_payload(
            monthly_fee_cents=monthly_fee_cents,
            included_files_quota=included_files_quota,
            overage_fee_cents=overage_fee_cents,
        ),
        coord_headers,
    )
    return get_success_data(resp)


# -----------------------------------------------------------------------------
# Tier 1.5: file creation
# -----------------------------------------------------------------------------

def make_file(coord_headers, seller_agent_id, buyer_agent_id=None, billing_model="PER_FILE",
              state_code="TX", contract_type="LISTING_ONLY",
              closing_date=CLOSING_DATE, effective_date=EFFECTIVE_DATE,
              inspection_offset_days=7, appraisal_offset_days=14,
              financing_offset_days=None, list_price_cents=LIST_PRICE_CENTS,
              property_address="1 Main St", subscription=None):
    """Create a DRAFT file. For SUBSCRIPTION billing pass the subscription dict; the
    current subscription version is re-read for the OCC field."""
    if contract_type == "PURCHASE_SALE":
        payload = create_purchase_file_payload(
            property_address=property_address,
            effective_date=effective_date,
            closing_date=closing_date,
            list_price_cents=list_price_cents,
            seller_agent_id=seller_agent_id,
            buyer_agent_id=buyer_agent_id,
            inspection_offset_days=inspection_offset_days,
            appraisal_offset_days=appraisal_offset_days,
            financing_offset_days=financing_offset_days if financing_offset_days is not None else 21,
        )
        if financing_offset_days is None:
            payload.pop("financing_offset_days", None)
    else:
        payload = create_file_payload(
            property_address=property_address,
            effective_date=effective_date,
            closing_date=closing_date,
            list_price_cents=list_price_cents,
            seller_agent_id=seller_agent_id,
            inspection_offset_days=inspection_offset_days,
            appraisal_offset_days=appraisal_offset_days,
        )
    payload["billing_model"] = billing_model
    payload["state_code"] = state_code
    if buyer_agent_id is not None:
        payload["buyer_agent_id"] = buyer_agent_id
    if billing_model == "SUBSCRIPTION":
        sub = get_success_data(api_client.get_subscription(subscription["id"], coord_headers))
        payload["subscription_id"] = subscription["id"]
        payload["expected_subscription_version"] = sub["version"]
    resp = api_client.create_file(payload, coord_headers)
    return get_success_data(resp)


def activate_file(coord_headers, file_id):
    return get_success_data(api_client.activate_file(file_id, coord_headers))


# -----------------------------------------------------------------------------
# Tier 2: composed scenarios
# -----------------------------------------------------------------------------

def make_coordinator_with_seller(seller_name="Seller Sam"):
    """Coordinator + one seller agent. Returns (coord, coord_h, seller, seller_h)."""
    coord, coord_h = make_coordinator()
    seller, seller_h = make_agent(coord_h, seller_name)
    return coord, coord_h, seller, seller_h


def make_coordinator_with_buyer_seller():
    """Coordinator + buyer and seller agents.
    Returns (coord, coord_h, buyer, buyer_h, seller, seller_h)."""
    coord, coord_h = make_coordinator()
    buyer, buyer_h = make_agent(coord_h, "Buyer Beth")
    seller, seller_h = make_agent(coord_h, "Seller Sam")
    return coord, coord_h, buyer, buyer_h, seller, seller_h


def make_active_listing_file(closing_date=CLOSING_DATE, state_code="TX",
                             template_overrides=None, file_overrides=None,
                             coordinator_name="Casey Coord"):
    """ACTIVE PER_FILE LISTING_ONLY file against a freshly published template.
    Returns dict with keys: coord, coord_h, seller, seller_h, tmpl, file."""
    coord, coord_h = make_coordinator(coordinator_name)
    seller, seller_h = make_agent(coord_h)
    t_over = dict(template_overrides or {})
    tmpl = make_template(
        state_code=state_code,
        contract_type="LISTING_ONLY",
        milestone_defs=t_over.pop("milestone_defs", list(SIMPLE_MILESTONE_DEFS)),
        required_doc_types=t_over.pop("required_doc_types", []),
    )
    f_over = dict(file_overrides or {})
    f = make_file(
        coord_h,
        seller["id"],
        billing_model="PER_FILE",
        state_code=state_code,
        contract_type="LISTING_ONLY",
        closing_date=closing_date,
        **f_over,
    )
    f = activate_file(coord_h, f["id"])
    return {"coord": coord, "coord_h": coord_h, "seller": seller,
            "seller_h": seller_h, "tmpl": tmpl, "file": f}


def make_active_purchase_file(closing_date=CLOSING_DATE, state_code="TX",
                              required_doc_types=None, financing_offset_days=21,
                              milestone_defs=None, effective_date=EFFECTIVE_DATE):
    """ACTIVE PER_FILE PURCHASE_SALE file. Returns dict with keys:
    coord, coord_h, buyer, buyer_h, seller, seller_h, tmpl, file."""
    coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
    tmpl = make_template(
        state_code=state_code,
        contract_type="PURCHASE_SALE",
        milestone_defs=milestone_defs if milestone_defs is not None else list(STANDARD_MILESTONE_DEFS),
        required_doc_types=required_doc_types if required_doc_types is not None else ["EXECUTED_CONTRACT"],
    )
    f = make_file(
        coord_h,
        seller["id"],
        buyer_agent_id=buyer["id"],
        billing_model="PER_FILE",
        state_code=state_code,
        contract_type="PURCHASE_SALE",
        closing_date=closing_date,
        effective_date=effective_date,
        financing_offset_days=financing_offset_days,
    )
    f = activate_file(coord_h, f["id"])
    return {"coord": coord, "coord_h": coord_h, "buyer": buyer, "buyer_h": buyer_h,
            "seller": seller, "seller_h": seller_h, "tmpl": tmpl, "file": f}


# -----------------------------------------------------------------------------
# Tier 2.5: child lookups and progressions
# -----------------------------------------------------------------------------

def get_file_version(coord_h, file_id):
    return get_success_data(api_client.get_file(file_id, coord_h))["version"]


# List-filter discipline: the PRD names query filters only for reminders
# (deadline_id, status) and signature requests (amendment_id, agent_id, status,
# round_number). All other lookups list unfiltered and select client-side on
# PRD-named response fields; in the single-file scenarios below the whole list
# belongs to the file under test.


def list_milestones_for_file(coord_h, file_id, **extra_params):
    """All milestones (single-file scenarios: the whole list is the file's)."""
    return get_success_data(api_client.list_milestones(coord_h, params={"limit": 100}))


def get_milestone_by_name(coord_h, file_id, name):
    rows = [m for m in list_milestones_for_file(coord_h, file_id) if m["name"] == name]
    assert len(rows) == 1, f"expected exactly one milestone named {name!r}, got {len(rows)}"
    return rows[0]


def get_deadline_by_kind(coord_h, file_id, kind):
    rows = [d for d in get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
            if d["kind"] == kind]
    assert len(rows) == 1, f"expected exactly one {kind} deadline, got {len(rows)}"
    return rows[0]


def list_reminders_for_deadline(coord_h, deadline_id, status=None):
    params = {"deadline_id": deadline_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(api_client.list_reminders(coord_h, params=params))


def get_file_invoice(coord_h, file_id):
    rows = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
    assert len(rows) == 1, f"expected exactly one invoice for the file, got {len(rows)}"
    return rows[0]


def get_file_closing_verification(coord_h, file_id):
    rows = get_success_data(api_client.list_closing_verifications(coord_h, params={"limit": 10}))
    assert len(rows) == 1, f"expected exactly one closing verification, got {len(rows)}"
    return rows[0]


def list_all_amendments(coord_h):
    return get_success_data(api_client.list_amendments(coord_h, params={"limit": 100}))


def list_all_communications(coord_h):
    return get_success_data(api_client.list_communications(coord_h, params={"limit": 100}))


def get_signature_request_for_agent(coord_h, amendment_id, agent_id, round_number=None):
    params = {"amendment_id": amendment_id, "agent_id": agent_id, "limit": 100}
    if round_number is not None:
        params["round_number"] = round_number
    rows = get_success_data(api_client.list_signature_requests(coord_h, params=params))
    assert len(rows) == 1, f"expected exactly one signature request, got {len(rows)}"
    return rows[0]


def complete_milestone(coord_h, milestone_id):
    """PENDING -> IN_PROGRESS -> COMPLETED. Returns the completed milestone."""
    api_client.start_milestone(milestone_id, coord_h)
    resp = api_client.complete_milestone(milestone_id, coord_h)
    return get_success_data(resp)


def complete_all_mandatory_milestones(coord_h, file_id):
    for ms in list_milestones_for_file(coord_h, file_id):
        if ms["mandatory"] and ms["status"] in ("PENDING", "IN_PROGRESS"):
            complete_milestone(coord_h, ms["id"])


def accept_document(coord_h, agent_h, file_id, doc_type):
    """Create + submit + accept one document. Returns the ACCEPTED document."""
    doc = get_success_data(
        api_client.create_document(create_document_payload(file_id=file_id, doc_type=doc_type), coord_h)
    )
    api_client.submit_document(doc["id"], agent_h)
    return get_success_data(api_client.accept_document(doc["id"], coord_h))


def run_audit(coord_h, file_id):
    return get_success_data(api_client.run_compliance_audit(file_id, coord_h))


def make_draft_amendment(coord_h, file_id, effective_from="2026-08-10",
                         effective_to="2026-08-15", **extra):
    """Create a DRAFT amendment with the file's current version as the OCC value."""
    payload = create_amendment_payload(
        file_id=file_id,
        expected_file_version=get_file_version(coord_h, file_id),
        effective_from=effective_from,
        effective_to=effective_to,
        **extra,
    )
    return get_success_data(api_client.create_amendment(payload, coord_h))


def make_routed_amendment(coord_h, file_id, effective_from="2026-08-10",
                          effective_to="2026-08-15", **extra):
    am = make_draft_amendment(coord_h, file_id, effective_from, effective_to, **extra)
    return get_success_data(api_client.route_amendment(am["id"], coord_h))


def make_fully_signed_amendment(coord_h, file_id, buyer_h=None, seller_h=None,
                                buyer_id=None, seller_id=None, **amendment_overrides):
    """Create -> route -> sign with every signer. Returns the FULLY_SIGNED amendment."""
    am = make_routed_amendment(coord_h, file_id, **amendment_overrides)
    if buyer_h and buyer_id:
        sig = get_signature_request_for_agent(coord_h, am["id"], buyer_id)
        api_client.sign_signature_request(sig["id"], buyer_h)
    if seller_h and seller_id:
        sig = get_signature_request_for_agent(coord_h, am["id"], seller_id)
        api_client.sign_signature_request(sig["id"], seller_h)
    return get_success_data(api_client.get_amendment(am["id"], coord_h))


# -----------------------------------------------------------------------------
# Tier 3/5: file lifecycle through close and archive
# -----------------------------------------------------------------------------

def request_close(coord_h, file_id):
    return get_success_data(api_client.request_close_file(file_id, coord_h))


def clear_to_close(coord_h, cv_id, lender_needed):
    """Drive a ClosingVerification to overall_status CLEAR_TO_CLOSE."""
    api_client.confirm_title(cv_id, TEST_USERS["title_rep_headers"])
    if lender_needed:
        api_client.confirm_lender(cv_id, TEST_USERS["lender_rep_headers"])
    return get_success_data(api_client.get_closing_verification(cv_id, coord_h))


def make_closed_listing_file():
    """CO LISTING_ONLY cash file closed end-to-end (empty audit set, optional milestone
    waived, title-only verification). Returns the scenario dict augmented with cv and
    invoice."""
    scen = make_active_listing_file(state_code="CO")
    coord_h, f = scen["coord_h"], scen["file"]
    run_audit(coord_h, f["id"])
    ms = get_milestone_by_name(coord_h, f["id"], "Listing Paperwork")
    api_client.waive_milestone(ms["id"], coord_h)
    scen["file"] = request_close(coord_h, f["id"])
    cv = get_file_closing_verification(coord_h, f["id"])
    scen["cv"] = clear_to_close(coord_h, cv["id"], lender_needed=False)
    scen["file"] = get_success_data(api_client.close_file(f["id"], coord_h))
    scen["invoice"] = get_file_invoice(coord_h, f["id"])
    return scen
