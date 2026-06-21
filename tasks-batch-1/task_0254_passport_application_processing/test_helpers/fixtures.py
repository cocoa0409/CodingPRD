"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the application to be deep in its lifecycle —
submitted, paid, in verification, adjudicating, or terminal — which takes 5-15
API calls to reach. These helpers encapsulate those chains so each test focuses
on its single assertion.

All setup calls go through get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" error, not a confusing
assertion deep inside a test.

Identity threading: every role here is entity-backed. After creating an Applicant
/ AcceptanceAgent / Adjudicator, ownership- and SoD-gated calls use the real
entity id via make_*_headers(), never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ADULT_NEW_BOOK_TOTAL, DEFAULT_CLEANUP_BUFFER_MINUTES
from .factories import (
    create_acceptance_agent_payload,
    create_acceptance_facility_payload,
    create_adjudicator_payload,
    create_appointment_payload,
    create_applicant_payload,
    create_application_payload,
    create_document_payload,
    create_photo_payload,
    create_urgent_travel_counter_payload,
    pay_payload,
    submit_payload,
    unique_email,
    verify_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjudicator_headers,
    make_agent_headers,
    make_applicant_headers,
)

ADJ = TEST_USERS["adjudicator_headers"]  # admin-style seeds (create facility/agent/etc.)


# ─── Clock control ────────────────────────────────────
def set_clock(iso8601: str):
    """Set the system clock; returns the new current_utc payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADJ))


# ─── Tier 0: bare participant / infrastructure creation ───
def create_applicant(**overrides):
    """Create an Applicant. Returns the applicant dict."""
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides),
                                    TEST_USERS["applicant_headers"])
    )


def create_facility(**overrides):
    return get_success_data(
        api_client.create_acceptance_facility(create_acceptance_facility_payload(**overrides), ADJ)
    )


def create_agent(facility_id, **overrides):
    return get_success_data(
        api_client.create_acceptance_agent(create_acceptance_agent_payload(facility_id, **overrides), ADJ)
    )


def create_adjudicator(**overrides):
    return get_success_data(
        api_client.create_adjudicator(create_adjudicator_payload(**overrides), ADJ)
    )


def create_counter(**overrides):
    return get_success_data(
        api_client.create_urgent_travel_counter(create_urgent_travel_counter_payload(**overrides), ADJ)
    )


def create_application(applicant_id, **overrides):
    """Create a DRAFT application owned by applicant_id."""
    return get_success_data(
        api_client.create_application(create_application_payload(applicant_id, **overrides),
                                      make_applicant_headers(applicant_id))
    )


def add_photo(application_id, applicant_id, **overrides):
    return get_success_data(
        api_client.create_photo(application_id, create_photo_payload(**overrides),
                                make_applicant_headers(applicant_id))
    )


def add_document(application_id, applicant_id, doc_category="IDENTITY",
                 doc_kind="DRIVERS_LICENSE", **overrides):
    return get_success_data(
        api_client.create_document(application_id,
                                   create_document_payload(doc_category, doc_kind, **overrides),
                                   make_applicant_headers(applicant_id))
    )


def get_fee_for_application(application_id, applicant_id):
    """Return the single FeeAssessment dict for an application (must exist)."""
    data, _ = _list(api_client.list_fee_assessments(
        make_applicant_headers(applicant_id), params={"application_id": application_id}))
    assert data, f"no fee assessment found for application {application_id}"
    return data[0]


def _list(response):
    """Return (data, meta) from a 2xx list response; raise a clear error otherwise."""
    if not (200 <= response.status_code < 300):
        raise AssertionError(f"Setup list failed HTTP {response.status_code}: {response.text}")
    payload = response.json()
    return payload["data"], payload["meta"]


# ─── Tier 1: DRAFT application fully prepared for submit ───
def draft_ready_to_submit(application_type="NEW", product_type="BOOK",
                          applicant_overrides=None, application_overrides=None,
                          doc_specs=None, photo_overrides=None):
    """
    Create an applicant + DRAFT application + a PASS photo + the supporting
    documents in doc_specs. Returns a dict with applicant, application (fresh
    read so version is current), and the created document dicts.

    doc_specs defaults to the NEW/RENEWAL identity+citizenship pair; pass a list
    of (doc_category, doc_kind, {overrides}) tuples to customize.
    """
    applicant = create_applicant(**(applicant_overrides or {}))
    application = create_application(applicant["id"], application_type=application_type,
                                     product_type=product_type, **(application_overrides or {}))
    add_photo(application["id"], applicant["id"], **(photo_overrides or {}))

    if doc_specs is None:
        doc_specs = [("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": 100}),
                     ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": 100})]
    docs = {}
    for category, kind, ov in doc_specs:
        doc = add_document(application["id"], applicant["id"], doc_category=category,
                           doc_kind=kind, **ov)
        docs.setdefault(category, []).append(doc)

    fresh = get_success_data(
        api_client.get_application(application["id"], make_applicant_headers(applicant["id"])))
    return {"applicant": applicant, "application": fresh, "docs": docs}


# ─── Tier 2: submitted (fee created, UNPAID) ───
def submitted_application(**kwargs):
    """Drive a draft through DRAFT->SUBMITTED. Returns the Tier-1 dict plus the
    submitted application read and its UNPAID fee assessment."""
    ctx = draft_ready_to_submit(**kwargs)
    app_id = ctx["application"]["id"]
    appl_id = ctx["applicant"]["id"]
    submitted = get_success_data(
        api_client.submit_application(app_id, submit_payload(ctx["application"]["version"]),
                                      make_applicant_headers(appl_id)))
    fee = get_fee_for_application(app_id, appl_id)
    ctx["application"] = submitted
    ctx["fee"] = fee
    return ctx


# ─── Tier 3: paid ───
def paid_application(**kwargs):
    """Submitted + fee PAID at exactly total_due_cents. Returns the context dict
    with the refreshed application and the PAID fee."""
    ctx = submitted_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    fee = ctx["fee"]
    paid_fee = get_success_data(
        api_client.pay_fee_assessment(fee["id"], pay_payload(fee["total_due_cents"]),
                                      make_applicant_headers(appl_id)))
    ctx["fee"] = paid_fee
    ctx["application"] = get_success_data(
        api_client.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)))
    return ctx


# ─── Tier 4: in verification (agent assigned) ───
def in_verification_application(agent=None, **kwargs):
    """Paid + begin-verification by a fresh AcceptanceAgent. Returns the context
    dict with 'agent' added and the refreshed application in IN_VERIFICATION."""
    ctx = paid_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    if agent is None:
        facility = create_facility()
        agent = create_agent(facility["id"])
        ctx["facility"] = facility
    ctx["agent"] = agent
    started = get_success_data(
        api_client.begin_verification(ctx["application"]["id"], make_agent_headers(agent["id"])))
    ctx["application"] = started
    return ctx


def accept_document(document_id, agent_id):
    return get_success_data(
        api_client.verify_document(document_id, verify_payload("ACCEPT"), make_agent_headers(agent_id)))


def accept_documents_clearing_holds(application_id, applicant_id, agent_id, document_ids,
                                    adjudicator_id):
    """Accept a sequence of documents on an IN_VERIFICATION application, clearing
    the review hold between accepts.

    Per PRD §3.6 the FINAL risk gate fires "on every change to a supporting
    document's verification status": accepting one document while its sibling is
    still PENDING (factor quality 0) can push the FINAL risk strictly above 50 and
    transition the application to REVIEW_HOLD. Because "Verification is permitted
    only when ... the parent application is IN_VERIFICATION", the next accept would
    be rejected. PRD §3.6 also grants the adjudicator a clear-hold capability that
    "reverts the application from REVIEW_HOLD back to IN_VERIFICATION". This helper
    walks that faithful path: after each accept, if the application is sitting in
    REVIEW_HOLD and more documents remain, the adjudicator clears the hold so the
    agent can continue verifying.
    """
    for idx, doc_id in enumerate(document_ids):
        accept_document(doc_id, agent_id)
        if idx == len(document_ids) - 1:
            break
        app = get_success_data(
            api_client.get_application(application_id, make_applicant_headers(applicant_id)))
        if app["status"] == "REVIEW_HOLD":
            get_success_data(
                api_client.clear_hold(application_id, make_adjudicator_headers(adjudicator_id)))


# ─── Tier 5: adjudicating (all required docs accepted) ───
def adjudicating_application(adjudicator=None, doc_qualities=None, **kwargs):
    """
    Drive a NEW BOOK application to ADJUDICATING: in-verification, then accept
    both IDENTITY and CITIZENSHIP documents (the required set). A distinct
    Adjudicator is created so SoD passes downstream. Returns the context dict
    with 'agent', 'adjudicator', and the refreshed application.

    doc_qualities lets callers control declared_quality of the two docs so the
    final risk score can be steered (used by the review-hold cascade test).
    """
    if doc_qualities is not None:
        q_id, q_cit = doc_qualities
        kwargs.setdefault("doc_specs", [
            ("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": q_id}),
            ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": q_cit}),
        ])
    ctx = in_verification_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]

    id_doc = ctx["docs"]["IDENTITY"][0]
    cit_doc = ctx["docs"]["CITIZENSHIP"][0]
    accept_document(id_doc["id"], agent_id)
    accept_document(cit_doc["id"], agent_id)

    if adjudicator is None:
        adjudicator = create_adjudicator()
    ctx["adjudicator"] = adjudicator
    ctx["application"] = get_success_data(
        api_client.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)))
    return ctx


# ─── Tier 6: appointment helpers ───
def book_facility_appointment(application_id, applicant_id, facility_id,
                              start_utc, end_utc, expected_version):
    return get_success_data(
        api_client.create_appointment(create_appointment_payload(
            application_id, "ACCEPTANCE_FACILITY", expected_version, start_utc, end_utc,
            facility_id=facility_id), make_applicant_headers(applicant_id)))


def book_counter_appointment(application_id, applicant_id, counter_id,
                             start_utc, end_utc, expected_version):
    return get_success_data(
        api_client.create_appointment(create_appointment_payload(
            application_id, "URGENT_TRAVEL_COUNTER", expected_version, start_utc, end_utc,
            counter_id=counter_id), make_applicant_headers(applicant_id)))


def current_version(application_id, applicant_id):
    app = get_success_data(
        api_client.get_application(application_id, make_applicant_headers(applicant_id)))
    return app["version"]


# ─── Tier 7: approved / issued ───
def approved_application(**kwargs):
    """Adjudicating -> APPROVED by the distinct adjudicator (SoD-clean)."""
    ctx = adjudicating_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    adj_id = ctx["adjudicator"]["id"]
    from .factories import adjudicate_payload
    get_success_data(
        api_client.adjudicate(ctx["application"]["id"], adjudicate_payload("APPROVE"),
                              make_adjudicator_headers(adj_id)))
    ctx["application"] = get_success_data(
        api_client.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)))
    return ctx


def issued_application(**kwargs):
    """Approved -> ISSUED."""
    ctx = approved_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    adj_id = ctx["adjudicator"]["id"]
    get_success_data(
        api_client.issue_application(ctx["application"]["id"], make_adjudicator_headers(adj_id)))
    ctx["application"] = get_success_data(
        api_client.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)))
    return ctx


# ─── Name-change flow (RENEWAL) ───
def name_change_evidence_verified(**kwargs):
    """
    RENEWAL BOOK application with name_change_requested=true, driven through to
    IN_VERIFICATION with all required documents ACCEPTED so name_change_status is
    EVIDENCE_VERIFIED while the main status remains IN_VERIFICATION. A distinct
    adjudicator is created for the subsequent decide call. Returns the context
    dict.

    The application carries the full required document set (IDENTITY,
    CITIZENSHIP, NAME_CHANGE_EVIDENCE) at quality 100. The IDENTITY and
    CITIZENSHIP documents are accepted first: with both accepted the FINAL risk is
    0 (PRD §3.6: 100 - (0.40*100 + 0.35*100 + 0.25*100) = 0), well below the
    review-hold threshold, and the auto-advance does not fire because the
    NAME_CHANGE_EVIDENCE document is still PENDING (not all required categories are
    yet accepted). The NAME_CHANGE_EVIDENCE document is accepted last: that
    acceptance cascades name_change_status PENDING_EVIDENCE -> EVIDENCE_VERIFIED,
    and although every required document is now ACCEPTED the application does NOT
    auto-advance to ADJUDICATING because PRD §3.6 requires the name-change
    dimension to be NONE or APPROVED for that advance — EVIDENCE_VERIFIED holds it
    in IN_VERIFICATION. The final FINAL risk (0) keeps it out of REVIEW_HOLD.
    """
    kwargs.setdefault("application_type", "RENEWAL")
    kwargs.setdefault("application_overrides", {"name_change_requested": True, "prior_name": "Prior Name"})
    kwargs.setdefault("doc_specs", [
        ("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": 100}),
        ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": 100}),
        ("NAME_CHANGE_EVIDENCE", "MARRIAGE_CERTIFICATE", {"declared_quality": 100}),
    ])
    ctx = in_verification_application(**kwargs)
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]
    # Accept IDENTITY and CITIZENSHIP first (risk drops to 0, no auto-advance yet
    # because NAME_CHANGE_EVIDENCE is still PENDING), then the evidence document
    # last so the name-change cascade fires and holds the main status.
    accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent_id)
    accept_document(ctx["docs"]["CITIZENSHIP"][0]["id"], agent_id)
    nc_doc = ctx["docs"]["NAME_CHANGE_EVIDENCE"][0]
    accept_document(nc_doc["id"], agent_id)
    ctx["adjudicator"] = create_adjudicator()
    ctx["nc_doc"] = nc_doc
    ctx["application"] = get_success_data(
        api_client.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)))
    return ctx
