"""Composite setup helpers: multi-step API sequences built on PRD endpoints.

Every helper builds preconditions from scratch (the server restarts before each
test) and uses get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .factories import (
    applicability_run_payload,
    create_activity_payload,
    create_consumer_payload,
    create_contract_payload,
    create_data_element_payload,
    create_data_system_payload,
    create_notice_payload,
    create_purpose_payload,
    create_retention_policy_payload,
    create_rights_request_payload,
    create_state_law_rule_payload,
    create_transfer_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_consumer_headers

PA = TEST_USERS["privacy_admin_headers"]
DS = TEST_USERS["data_steward_headers"]
BO1 = TEST_USERS["business_owner_headers"]          # X-User-ID bo-1
BO2 = TEST_USERS["business_owner_2_headers"]        # X-User-ID bo-2
LC1 = TEST_USERS["legal_counsel_headers"]           # X-User-ID lc-1
LC2 = TEST_USERS["legal_counsel_2_headers"]         # X-User-ID lc-2
LC9 = TEST_USERS["legal_counsel_9_headers"]         # X-User-ID lc-9
VM = TEST_USERS["vendor_manager_headers"]

# Full clause set required by a HIGH-risk vendor (PRD §3.3).
HIGH_CLAUSES = ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT", "SUBPROCESSOR_CONSENT", "AUDIT_RIGHTS"]
# Clause set required by a STANDARD-risk vendor (PRD §3.3).
STANDARD_CLAUSES = ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT"]


# ---------------------------------------------------------------------------
# Tier 1/2: single-entity and small composite setups
# ---------------------------------------------------------------------------

def create_element(element_key="email", category="BASIC_CONTACT", classification="INTERNAL"):
    """Create one ACTIVE data element. Returns the element dict."""
    resp = api.create_data_element(
        create_data_element_payload(
            element_key=element_key, category=category, classification=classification
        ),
        DS,
    )
    return get_success_data(resp)


def create_retention_policy(policy_code="RP-1YR", duration_days=365, disposal_action="DELETE"):
    """Create one retention policy. Returns the policy dict."""
    resp = api.create_retention_policy(
        create_retention_policy_payload(
            policy_code=policy_code, duration_days=duration_days, disposal_action=disposal_action
        ),
        PA,
    )
    return get_success_data(resp)


def create_data_system(system_key="sys-a", hosting_region="US", stores_categories=None):
    """Create one ACTIVE data system. Returns the system dict."""
    resp = api.create_data_system(
        create_data_system_payload(
            system_key=system_key,
            hosting_region=hosting_region,
            stores_categories=["FINANCIAL"] if stores_categories is None else stores_categories,
        ),
        PA,
    )
    return get_success_data(resp)


def create_published_notice(scope="WEBSITE", title="v1",
                            effective_from="2026-01-01T00:00:00Z",
                            effective_to="2027-01-01T00:00:00Z"):
    """Create a notice and publish it. Returns the published notice dict."""
    resp = api.create_notice(
        create_notice_payload(
            scope=scope, title=title, effective_from=effective_from, effective_to=effective_to
        ),
        PA,
    )
    notice = get_success_data(resp)
    return get_success_data(api.publish_notice(notice["id"], PA))


def create_consumer(email="tx@x.com", full_name="TX One", state_code="TX"):
    """Register one consumer. Returns the consumer dict."""
    resp = api.create_consumer(
        create_consumer_payload(email=email, full_name=full_name, state_code=state_code),
        PA,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: vendor + contract lifecycle
# ---------------------------------------------------------------------------

def create_approved_vendor(vendor_name="DataPro", processes_categories=None, home_region="US"):
    """Vendor carried through ONBOARDING -> ASSESSMENT -> APPROVED with one
    EXECUTED contract carrying exactly the clause set its risk tier requires.
    Returns (vendor, contract)."""
    categories = ["FINANCIAL"] if processes_categories is None else processes_categories
    vendor = get_success_data(api.create_vendor(
        create_vendor_payload(
            vendor_name=vendor_name, home_region=home_region, processes_categories=categories
        ),
        VM,
    ))
    tier = vendor["risk_tier"]
    clauses = {
        "LOW": ["DPA"],
        "STANDARD": list(STANDARD_CLAUSES),
        "HIGH": list(HIGH_CLAUSES),
    }[tier]
    submitted = get_success_data(api.submit_vendor_assessment(vendor["id"], VM))
    contract = get_success_data(api.create_contract(
        vendor["id"],
        create_contract_payload(
            provided_clauses=clauses, expected_vendor_version=submitted["version"]
        ),
        VM,
    ))
    get_success_data(api.verify_contract(contract["id"], LC1))
    get_success_data(api.execute_contract(contract["id"], VM))
    approved = get_success_data(api.approve_vendor(vendor["id"], PA))
    return approved, contract


# ---------------------------------------------------------------------------
# Tier 2/3: activity + purpose lifecycle
# ---------------------------------------------------------------------------

def create_active_activity(element_overrides=None, vendor_id=None, activity_overrides=None,
                           purpose_overrides=None, notice_scope="WEBSITE"):
    """Activity carried to ACTIVE with one DOCUMENTED purpose (non-CONSENT basis
    by default). Returns (activity, purpose)."""
    element_overrides = element_overrides or {}
    activity_overrides = activity_overrides or {}
    purpose_overrides = purpose_overrides or {}
    element = create_element(**element_overrides)
    policy = create_retention_policy()
    payload = create_activity_payload(
        notice_scope=notice_scope, data_element_ids=[element["id"]], **activity_overrides
    )
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    activity = get_success_data(api.create_activity(payload, DS))
    ppayload = {"retention_policy_id": policy["id"]}
    ppayload.update(purpose_overrides)
    purpose = get_success_data(api.create_purpose(
        activity["id"], create_purpose_payload(**ppayload), DS
    ))
    activity = get_success_data(api.activate_activity(activity["id"], DS))
    return activity, purpose


# ---------------------------------------------------------------------------
# Tier 3: assessment lifecycle
# ---------------------------------------------------------------------------

def create_activity_with_manual_assessment(activity_overrides=None, submitter_headers=None):
    """Low-risk activity plus a manually triggered PIA submitted by a
    BusinessOwner (IN_REVIEW). Returns (activity, assessment)."""
    element = create_element()
    overrides = {"data_element_ids": [element["id"]]}
    overrides.update(activity_overrides or {})
    activity = get_success_data(api.create_activity(create_activity_payload(**overrides), DS))
    assessment = get_success_data(api.create_assessment(activity["id"], DS))
    assessment = get_success_data(
        api.submit_assessment(assessment["id"], submitter_headers or BO1)
    )
    return activity, assessment


# ---------------------------------------------------------------------------
# Tier 3: transfer landscape (approved vendor + contract, ACTIVE activity,
# ACTIVE system) and approved transfer
# ---------------------------------------------------------------------------

def setup_transfer_landscape(source_region="US"):
    """Full transfer-ready landscape: APPROVED vendor with EXECUTED contract,
    ACTIVE data system in the given hosting region, ACTIVE activity with a
    DOCUMENTED CONTRACT purpose. Returns dict of the pieces."""
    vendor, contract = create_approved_vendor()
    system = create_data_system(hosting_region=source_region)
    activity, purpose = create_active_activity(vendor_id=vendor["id"])
    return {"vendor": vendor, "contract": contract, "system": system,
            "activity": activity, "purpose": purpose}


def setup_approved_transfer(source_region="US", dest_region="EU", mechanism="SCC_2021",
                            effective_from="2026-03-01T00:00:00Z",
                            effective_to="2026-09-01T00:00:00Z"):
    """Landscape plus one APPROVED transfer. Returns dict with a 'transfer' key."""
    landscape = setup_transfer_landscape(source_region=source_region)
    transfer = get_success_data(api.create_transfer(
        create_transfer_payload(
            source_system_id=landscape["system"]["id"],
            vendor_id=landscape["vendor"]["id"],
            vendor_contract_id=landscape["contract"]["id"],
            activity_id=landscape["activity"]["id"],
            dest_region=dest_region,
            mechanism=mechanism,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        PA,
    ))
    get_success_data(api.assess_transfer(transfer["id"], LC1))
    transfer = get_success_data(api.approve_transfer(transfer["id"], LC1))
    landscape["transfer"] = transfer
    return landscape


# ---------------------------------------------------------------------------
# Tier 5: notice supersession landscape (active activity whose CONSENT purpose
# is pinned to a published notice, plus an APPROVED transfer on that activity)
# ---------------------------------------------------------------------------

def setup_notice_supersede_landscape():
    """Published notice n1 (WEBSITE), ACTIVE activity with a CONSENT purpose
    pinned to n1, and one APPROVED transfer. Returns dict of the pieces."""
    vendor, contract = create_approved_vendor()
    system = create_data_system(system_key="sys-crm")
    element = create_element()
    policy = create_retention_policy()
    n1 = create_published_notice(scope="WEBSITE", title="v1")
    activity = get_success_data(api.create_activity(
        create_activity_payload(
            activity_name="CRM processing", business_unit="Sales",
            notice_scope="WEBSITE", data_element_ids=[element["id"]],
            vendor_id=vendor["id"],
        ),
        DS,
    ))
    purpose = get_success_data(api.create_purpose(
        activity["id"],
        create_purpose_payload(
            purpose_type="MARKETING", legal_basis="CONSENT",
            retention_policy_id=policy["id"],
        ),
        DS,
    ))
    activity = get_success_data(api.activate_activity(activity["id"], DS))
    transfer = get_success_data(api.create_transfer(
        create_transfer_payload(
            source_system_id=system["id"], vendor_id=vendor["id"],
            vendor_contract_id=contract["id"], activity_id=activity["id"],
            dest_region="EU", mechanism="SCC_2021",
            effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z",
        ),
        PA,
    ))
    get_success_data(api.assess_transfer(transfer["id"], LC1))
    transfer = get_success_data(api.approve_transfer(transfer["id"], LC1))
    return {"vendor": vendor, "contract": contract, "system": system, "element": element,
            "policy": policy, "n1": n1, "activity": activity, "purpose": purpose,
            "transfer": transfer}


def publish_superseding_notice(n1_id, scope="WEBSITE", title="v2",
                               effective_from="2026-08-01T00:00:00Z",
                               effective_to="2028-01-01T00:00:00Z"):
    """Create and publish a notice that supersedes n1. Returns the new notice."""
    resp = api.create_notice(
        create_notice_payload(
            scope=scope, title=title, effective_from=effective_from,
            effective_to=effective_to, supersedes_notice_id=n1_id,
        ),
        PA,
    )
    n2 = get_success_data(resp)
    return get_success_data(api.publish_notice(n2["id"], PA))


# ---------------------------------------------------------------------------
# Tier 3: rights request lifecycle
# ---------------------------------------------------------------------------

def create_consumer_and_request(email="tx@x.com", state_code="TX",
                                request_type="ACCESS",
                                requested_categories=None):
    """Register a consumer and file one rights request as that consumer
    (ownership: X-User-ID is the consumer's id). Returns (consumer, request)."""
    consumer = create_consumer(email=email, state_code=state_code)
    request = get_success_data(api.create_rights_request(
        consumer["id"],
        create_rights_request_payload(
            request_type=request_type,
            requested_categories=requested_categories or ["BASIC_CONTACT"],
        ),
        make_consumer_headers(consumer["id"]),
    ))
    return consumer, request


def create_verified_request_with_systems(systems=None, email="tx@x.com",
                                         request_type="ACCESS",
                                         requested_categories=None):
    """Systems + consumer + verified + routed request.

    `systems` is a list of dicts with system_key / hosting_region /
    stores_categories. Returns dict with consumer, request, tasks, systems.
    """
    created_systems = []
    for spec in (systems or []):
        created_systems.append(create_data_system(**spec))
    consumer, request = create_consumer_and_request(
        email=email, request_type=request_type, requested_categories=requested_categories
    )
    request = get_success_data(api.verify_rights_request(request["id"], DS))
    request = get_success_data(api.route_rights_request(request["id"], DS))
    tasks, _meta = validate_paginated(api.list_request_tasks(request["id"], DS))
    return {"consumer": consumer, "request": request, "tasks": tasks, "systems": created_systems}


# ---------------------------------------------------------------------------
# Tier 4: state-law applicability
# ---------------------------------------------------------------------------

def create_state_law_rule(state_code, resident_records_threshold,
                          revenue_share_threshold_pct=100.0,
                          request_deadline_days=45, extension_days=30,
                          law_name=None):
    """Create one state law rule. Returns the rule dict."""
    resp = api.create_state_law_rule(
        create_state_law_rule_payload(
            state_code=state_code,
            law_name=law_name or f"{state_code} Act",
            resident_records_threshold=resident_records_threshold,
            revenue_share_threshold_pct=revenue_share_threshold_pct,
            request_deadline_days=request_deadline_days,
            extension_days=extension_days,
        ),
        PA,
    )
    return get_success_data(resp)


def run_applicability(state_revenues, total_revenue_cents=1000):
    """Trigger one threshold-monitoring run. Returns the run summary dict."""
    resp = api.run_applicability_evaluations(
        applicability_run_payload(
            state_revenues=state_revenues, total_revenue_cents=total_revenue_cents
        ),
        PA,
    )
    return get_success_data(resp)


def list_evaluations_for_rule(rule_id):
    """All evaluation rows for one rule. Returns (data_list, meta)."""
    return validate_paginated(
        api.list_applicability_evaluations(PA, params={"state_law_rule_id": rule_id})
    )
