"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
scheme registration, actor onboarding, application acceptance, audit
assignment/start/report/decision, certificate issuance, NC lifecycle —
out of PRD-declared endpoints only.

Identity threading (PRD §2.1): ClientAdmin calls carry X-User-ID equal to the
owning Client.id, Auditor calls carry the assigned Auditor.id, and
DecisionMaker calls carry the acting DecisionMaker.id. SchemeAdmin is opaque,
so the shared scheme_admin_headers constant is used everywhere for it.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUDIT1_START_AT,
    AUDIT2_START_AT,
    DEFAULT_SCOPE,
    WITNESS_PASS_DATE,
)
from .factories import (
    create_application_payload,
    create_assign_payload,
    create_auditor_payload,
    create_cap_payload,
    create_cap_review_payload,
    create_client_payload,
    create_decision_maker_payload,
    create_decision_payload,
    create_nonconformity_payload,
    create_reschedule_payload,
    create_review_payload,
    create_scheme_payload,
    create_scope_change_payload,
    create_submit_report_payload,
    create_suspend_payload,
    create_witness_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_client_admin_headers,
    make_decision_maker_headers,
)

ADMIN = TEST_USERS["scheme_admin_headers"]


class Chain(SimpleNamespace):
    """Attribute-access bag of entities accumulated along a lifecycle chain.

    Populated progressively: scheme, client, auditor, dm, app, audit, then
    (depending on depth) certificate, listing, audit2, ...
    """


# ---------------------------------------------------------------------------
# Tier 0: clock + single-entity creators (each returns the created resource)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (SchemeAdmin-only, PRD §2.6)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def make_scheme(**overrides):
    """Register a certification scheme with its rule constants (PRD §3.1)."""
    resp = api_client.create_scheme(create_scheme_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_client(name="Acme Baking Co", **overrides):
    resp = api_client.create_client(create_client_payload(name=name, **overrides),
                                    ADMIN)
    return get_success_data(resp)


def make_auditor(name="Audrey Auditor", competencies=None, conflicts=None,
                 witness=True, witnessed_on=WITNESS_PASS_DATE,
                 witness_result="PASS"):
    """Register an auditor; when `witness` is true, also record a witness
    audit so calibration_status flips per PRD §3.2. Returns the fresh record."""
    payload = create_auditor_payload(name=name)
    if competencies is not None:
        payload["competency_categories"] = competencies
    if conflicts is not None:
        payload["conflicted_client_ids"] = conflicts
    auditor = get_success_data(api_client.create_auditor(payload, ADMIN))
    if witness:
        get_success_data(api_client.create_witness_audit(
            auditor["id"],
            create_witness_audit_payload(witnessed_on=witnessed_on,
                                         result=witness_result),
            ADMIN))
    return get_auditor(auditor["id"])


def make_decision_maker(name="Dana Decider", linked_auditor_id=None):
    payload = create_decision_maker_payload(name=name)
    if linked_auditor_id is not None:
        payload["linked_auditor_id"] = linked_auditor_id
    return get_success_data(api_client.create_decision_maker(payload, ADMIN))


# ---------------------------------------------------------------------------
# Role-header threading helpers (entity-backed identities, PRD §2.1)
# ---------------------------------------------------------------------------

def client_headers(client) -> dict:
    return make_client_admin_headers(client["id"])


def auditor_headers(auditor) -> dict:
    return make_auditor_headers(auditor["id"])


def dm_headers(dm) -> dict:
    return make_decision_maker_headers(dm["id"])


# ---------------------------------------------------------------------------
# Tier 0: plain reads (as SchemeAdmin, which may read everything, PRD §4)
# ---------------------------------------------------------------------------

def get_scheme(scheme_id):
    return get_success_data(api_client.get_scheme(scheme_id, ADMIN))


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, ADMIN))


def get_auditor(auditor_id):
    return get_success_data(api_client.get_auditor(auditor_id, ADMIN))


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, ADMIN))


def get_audit(audit_id):
    return get_success_data(api_client.get_audit(audit_id, ADMIN))


def get_nc(nc_id):
    return get_success_data(api_client.get_nonconformity(nc_id, ADMIN))


def get_certificate(certificate_id):
    return get_success_data(api_client.get_certificate(certificate_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: application lifecycle (DRAFT -> SUBMITTED -> ACCEPTED/REJECTED)
# ---------------------------------------------------------------------------

def make_application(client, scheme, categories=None, site_name="Site A",
                     scope_text="production of baked goods"):
    """DRAFT application owned by `client` (client_id binds from X-User-ID)."""
    payload = create_application_payload(
        scheme["id"], site_name=site_name, scope_text=scope_text,
        product_categories=[dict(e) for e in (categories or DEFAULT_SCOPE)])
    return get_success_data(
        api_client.create_application(payload, client_headers(client)))


def submit_application(app, client):
    return get_success_data(
        api_client.submit_application(app["id"], client_headers(client)))


def review_application(app, outcome, rejection_reason=None):
    payload = create_review_payload(outcome)
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.review_application(app["id"], payload,
                                                          ADMIN))


def accept_application(app):
    return review_application(app, "ACCEPTED")


def reject_application(app, reason="scope not certifiable"):
    return review_application(app, "REJECTED", rejection_reason=reason)


def application_audits(application_id):
    """Audits of an application in sequence_number ascending order (PRD §3.3)."""
    return get_success_data(api_client.list_application_audits(application_id,
                                                               ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: audit lifecycle (assign -> start -> report -> decide)
# ---------------------------------------------------------------------------

def assign_audit(audit_id, auditor_id):
    return get_success_data(api_client.assign_auditor(
        audit_id, create_assign_payload(auditor_id), ADMIN))


def reschedule_audit(audit_id, window_start, window_end):
    return get_success_data(api_client.reschedule_audit(
        audit_id, create_reschedule_payload(window_start, window_end), ADMIN))


def start_audit(audit_id, auditor_id, at=AUDIT1_START_AT):
    """Advance the clock to `at` (inside the window) and start the audit."""
    set_clock(at)
    return get_success_data(api_client.start_audit(
        audit_id, auditor_headers({"id": auditor_id})))


def make_nonconformity(audit_id, auditor_id, grade="MINOR",
                       clause_ref="SQF 2.6.1", description="minor finding"):
    return get_success_data(api_client.create_nonconformity(
        audit_id,
        create_nonconformity_payload(grade=grade, clause_ref=clause_ref,
                                     description=description),
        auditor_headers({"id": auditor_id})))


def list_nonconformities(audit_id):
    return get_success_data(api_client.list_nonconformities(audit_id, ADMIN))


def submit_report(audit_id, auditor_id, actual_days=1):
    return get_success_data(api_client.submit_report(
        audit_id, create_submit_report_payload(actual_days),
        auditor_headers({"id": auditor_id})))


def decide_audit(audit_id, decision_maker_id, outcome="GRANT"):
    return get_success_data(api_client.decide_audit(
        audit_id, create_decision_payload(outcome),
        dm_headers({"id": decision_maker_id})))


def audit_certificate(audit_id):
    """The certificate an audit issued, as an array of zero or one (PRD §3.6)."""
    return get_success_data(api_client.get_audit_certificate(audit_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: nonconformity CAP cycle
# ---------------------------------------------------------------------------

def submit_cap(nc_id, client_id, cap_text="corrective action plan"):
    return get_success_data(api_client.submit_cap(
        nc_id, create_cap_payload(cap_text),
        make_client_admin_headers(client_id)))


def review_cap(nc_id, auditor_id, outcome="ACCEPT", notes=None):
    payload = create_cap_review_payload(outcome)
    if notes is not None:
        payload["review_notes"] = notes
    return get_success_data(api_client.review_cap(
        nc_id, payload, make_auditor_headers(auditor_id)))


def close_nc(nc_id, client_id, auditor_id):
    """OPEN -> UNDER_REVIEW -> CLOSED."""
    submit_cap(nc_id, client_id)
    return review_cap(nc_id, auditor_id, "ACCEPT")


def reject_nc(nc_id, client_id, auditor_id, cap_text="revised plan"):
    """OPEN -> UNDER_REVIEW -> OPEN, rejection_count + 1."""
    submit_cap(nc_id, client_id, cap_text)
    return review_cap(nc_id, auditor_id, "REJECT")


# ---------------------------------------------------------------------------
# Tier 2: certificates, scope changes, appeals, directory
# ---------------------------------------------------------------------------

def suspend_certificate(certificate_id, decision_maker_id,
                        reason="manual regulatory hold", at=None):
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.suspend_certificate(
        certificate_id, create_suspend_payload(reason),
        dm_headers({"id": decision_maker_id})))


def reinstate_certificate(certificate_id, decision_maker_id):
    return get_success_data(api_client.reinstate_certificate(
        certificate_id, dm_headers({"id": decision_maker_id})))


def withdraw_certificate(certificate_id, decision_maker_id):
    return get_success_data(api_client.withdraw_certificate(
        certificate_id, dm_headers({"id": decision_maker_id})))


def certificate_listing(certificate_id):
    """The certificate's single directory listing (exactly one per
    certificate, PRD §2.10)."""
    data = get_success_data(api_client.get_certificate_listing(certificate_id,
                                                               ADMIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one listing for certificate {certificate_id}, "
        f"got {data!r}"
    )
    return data[0]


def certificate_scope_changes(certificate_id):
    return get_success_data(api_client.list_scope_changes(certificate_id, ADMIN))


def certificate_appeals(certificate_id):
    return get_success_data(api_client.list_certificate_appeals(certificate_id,
                                                                ADMIN))


def create_scope_change(certificate_id, client_id, requested_categories,
                        reason, expected_certificate_version):
    return get_success_data(api_client.create_scope_change(
        certificate_id,
        create_scope_change_payload(requested_categories, reason,
                                    expected_certificate_version),
        make_client_admin_headers(client_id)))


def decide_scope_change(scope_change_id, decision_maker_id, outcome):
    return get_success_data(api_client.decide_scope_change(
        scope_change_id, {"outcome": outcome},
        dm_headers({"id": decision_maker_id})))


def file_appeal(certificate_id, client_id, grounds="appeal grounds"):
    return get_success_data(api_client.create_appeal(
        {"certificate_id": certificate_id, "grounds": grounds},
        make_client_admin_headers(client_id)))


def decide_appeal(appeal_id, decision_maker_id, outcome):
    return get_success_data(api_client.decide_appeal(
        appeal_id, {"outcome": outcome}, dm_headers({"id": decision_maker_id})))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle chains
# ---------------------------------------------------------------------------

def setup_accepted_chain(scheme_overrides=None, categories=None,
                         client_name="Acme Baking Co", auditor_name="Audrey Auditor",
                         auditor_overrides=None, witness=True,
                         witnessed_on=WITNESS_PASS_DATE, dm_name="Dana Decider"):
    """Scheme + client + auditor (+PASS witness) + decision maker + an
    application walked DRAFT -> SUBMITTED -> ACCEPTED, with audit seq1
    auto-created in SCHEDULED (PRD §3.3)."""
    chain = Chain()
    chain.scheme = make_scheme(**(scheme_overrides or {}))
    chain.client = make_client(name=client_name)
    chain.auditor = make_auditor(name=auditor_name, witness=witness,
                                 witnessed_on=witnessed_on,
                                 **(auditor_overrides or {}))
    chain.dm = make_decision_maker(name=dm_name)
    chain.app = make_application(chain.client, chain.scheme,
                                 categories=categories)
    chain.app = submit_application(chain.app, chain.client)
    chain.app = accept_application(chain.app)
    chain.audit = application_audits(chain.app["id"])[0]
    return chain


def setup_assigned_chain(**kwargs):
    """Accepted chain + auditor assigned to audit seq1 (PRD §3.4)."""
    chain = setup_accepted_chain(**kwargs)
    chain.audit = assign_audit(chain.audit["id"], chain.auditor["id"])
    return chain


def setup_started_chain(at=AUDIT1_START_AT, **kwargs):
    """Assigned chain + audit seq1 started inside its window (PRD §3.5)."""
    chain = setup_assigned_chain(**kwargs)
    chain.audit = start_audit(chain.audit["id"], chain.auditor["id"], at=at)
    return chain


def setup_reported_chain(actual_days=1, at=AUDIT1_START_AT, **kwargs):
    """Started chain + report submitted (REPORT_SUBMITTED, PRD §3.5).

    chain.audit carries the frozen reported_score and audit_fee.
    """
    chain = setup_started_chain(at=at, **kwargs)
    chain.audit = submit_report(chain.audit["id"], chain.auditor["id"],
                                actual_days=actual_days)
    return chain


def setup_granted_chain(actual_days=1, at=AUDIT1_START_AT, **kwargs):
    """Reported chain + GRANT decision on the INITIAL audit: certificate
    issued ACTIVE, directory listing LISTED, next audit scheduled (PRD §3.6).
    """
    chain = setup_reported_chain(actual_days=actual_days, at=at, **kwargs)
    chain.audit = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
    certs = audit_certificate(chain.audit["id"])
    assert len(certs) == 1, "Setup failed: GRANT on INITIAL issued no certificate"
    chain.certificate = certs[0]
    chain.listing = certificate_listing(chain.certificate["id"])
    return chain


def start_second_audit(chain, at=AUDIT2_START_AT):
    """Assign the chain auditor to the auto-created audit seq2 and start it
    inside its window. Sets chain.audit2 and returns it."""
    audits = application_audits(chain.app["id"])
    assert len(audits) >= 2, "Setup failed: no successor audit was scheduled"
    audit2 = audits[1]
    assign_audit(audit2["id"], chain.auditor["id"])
    chain.audit2 = start_audit(audit2["id"], chain.auditor["id"], at=at)
    return chain.audit2
