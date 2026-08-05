"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures raise
clear "setup failed" errors rather than confusing assertion failures.

The Attacher role is entity-backed: whenever an ownership-gated call is made on
behalf of an attacher, the attacher's own id is threaded through as X-User-ID
via make_attacher_headers(attacher["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_pole_owner_payload,
    create_crew_payload,
    create_pole_payload,
    create_attacher_payload,
    create_application_payload,
    create_survey_payload,
    create_finding_payload,
    create_annual_rental_invoice_payload,
    create_dispute_payload,
)
from .test_users import (
    TEST_USERS,
    make_engineer_headers,
    make_permit_officer_headers,
    make_attacher_headers,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]

DEFAULT_SURVEYOR = "eng-1"
DEFAULT_OFFICER = "po-1"


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock to an ISO instant (JointUseCoordinator only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, COORD))


# ─── Tier 1: Individual entity creation ───────────────────────────────────
def setup_owner(**overrides) -> dict:
    return get_success_data(
        api_client.create_pole_owner(create_pole_owner_payload(**overrides), COORD)
    )


def setup_crew(owner_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_crew(create_crew_payload(owner_id, **overrides), COORD)
    )


def setup_pole(owner_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pole(create_pole_payload(owner_id, **overrides), COORD)
    )


_ATTACHER_SEQ = [0]


def setup_attacher(**overrides) -> dict:
    # An attacher's cin is globally unique (PRD §2.5); auto-generate unique
    # defaults so multiple scenarios in one test do not collide on cin.
    if "cin" not in overrides:
        _ATTACHER_SEQ[0] += 1
        n = _ATTACHER_SEQ[0]
        overrides.setdefault("cin", f"CIN-AUTO-{n}")
        overrides.setdefault("company_name", f"Attacher-{n}")
        overrides.setdefault("contact_email", f"attacher{n}@x.com")
    return get_success_data(
        api_client.create_attacher(create_attacher_payload(**overrides), COORD)
    )


# ─── Tier 2: Base scenario (owner + crew + pole + attacher) ────────────────
def setup_base(owner_overrides=None, pole_overrides=None, attacher_overrides=None,
               with_crew=True) -> dict:
    """Owner + (optional) crew + pole + attacher. Returns a context dict."""
    owner = setup_owner(**(owner_overrides or {}))
    crew = setup_crew(owner["id"]) if with_crew else None
    pole = setup_pole(owner["id"], **(pole_overrides or {}))
    attacher = setup_attacher(**(attacher_overrides or {}))
    return {"owner": owner, "crew": crew, "pole": pole, "attacher": attacher}


# ─── Tier 3: Application lifecycle shortcuts ───────────────────────────────
def submit_application(pole_id: str, attacher_id: str, **overrides) -> dict:
    """Submit an application on behalf of the owning attacher (SUBMITTED)."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(pole_id, attacher_id, **overrides),
            make_attacher_headers(attacher_id),
        )
    )


def submit_survey(app_id: str, crew_id: str, surveyor_user_id: str = DEFAULT_SURVEYOR,
                  **survey_overrides) -> dict:
    """Engineer submits the make-ready survey (SUBMITTED -> SURVEYED)."""
    return get_success_data(
        api_client.survey_application(
            app_id,
            create_survey_payload(crew_id, **survey_overrides),
            make_engineer_headers(surveyor_user_id),
        )
    )


def issue_estimate(app_id: str, surveyor_user_id: str = DEFAULT_SURVEYOR) -> dict:
    """Engineer issues the estimate at the application's current version."""
    app = get_success_data(api_client.get_application(app_id, make_engineer_headers(surveyor_user_id)))
    return get_success_data(
        api_client.estimate_application(
            app_id,
            {"expected_application_version": app["version"]},
            make_engineer_headers(surveyor_user_id),
        )
    )


def accept_estimate(app_id: str, attacher_id: str) -> dict:
    return get_success_data(
        api_client.estimate_decision_application(
            app_id, {"decision": "ACCEPT"}, make_attacher_headers(attacher_id)
        )
    )


def grant_permit(app_id: str, officer_user_id: str = DEFAULT_OFFICER,
                 actual_labor_hours=4) -> dict:
    return get_success_data(
        api_client.permit_application(
            app_id,
            {"decision": "GRANTED", "actual_labor_hours": actual_labor_hours},
            make_permit_officer_headers(officer_user_id),
        )
    )


def deny_permit(app_id: str, officer_user_id: str = DEFAULT_OFFICER) -> dict:
    return get_success_data(
        api_client.permit_application(
            app_id, {"decision": "DENIED"}, make_permit_officer_headers(officer_user_id)
        )
    )


# --- Composite application-state builders ---------------------------------
# The COMPLEX/8h/2-existing survey drives the canonical estimate fee 210450.
COMPLEX_SURVEY = {
    "estimated_labor_hours": 8,
    "make_ready_required": True,
    "existing_attacher_count": 2,
    "complexity_class": "COMPLEX",
}


def create_surveyed_application(owner_overrides=None, pole_overrides=None,
                                attacher_overrides=None, app_overrides=None,
                                survey_overrides=None,
                                surveyor_user_id: str = DEFAULT_SURVEYOR) -> dict:
    """Base scenario + application walked to SURVEYED. Returns the context dict
    augmented with 'app'."""
    ctx = setup_base(owner_overrides, pole_overrides, attacher_overrides)
    app = submit_application(ctx["pole"]["id"], ctx["attacher"]["id"], **(app_overrides or {}))
    submit_survey(app["id"], ctx["crew"]["id"], surveyor_user_id, **(survey_overrides or {}))
    ctx["app"] = get_success_data(api_client.get_application(app["id"], COORD))
    ctx["surveyor_user_id"] = surveyor_user_id
    return ctx


def create_estimate_issued_application(**kwargs) -> dict:
    """Context with the application in ESTIMATE_ISSUED."""
    ctx = create_surveyed_application(**kwargs)
    issue_estimate(ctx["app"]["id"], ctx["surveyor_user_id"])
    ctx["app"] = get_success_data(api_client.get_application(ctx["app"]["id"], COORD))
    return ctx


def create_accepted_application(**kwargs) -> dict:
    """Context with the application in ESTIMATE_ACCEPTED (reservation + MAKE_READY
    invoice ISSUED)."""
    ctx = create_estimate_issued_application(**kwargs)
    accept_estimate(ctx["app"]["id"], ctx["attacher"]["id"])
    ctx["app"] = get_success_data(api_client.get_application(ctx["app"]["id"], COORD))
    return ctx


def create_granted_application(actual_labor_hours=4, officer_user_id: str = DEFAULT_OFFICER,
                               **kwargs) -> dict:
    """Context with the application in PERMIT_GRANTED plus its ACTIVE Attachment."""
    ctx = create_accepted_application(**kwargs)
    grant_permit(ctx["app"]["id"], officer_user_id, actual_labor_hours)
    ctx["app"] = get_success_data(api_client.get_application(ctx["app"]["id"], COORD))
    ctx["attachment"] = get_attachment_for_application(ctx["app"]["id"])
    return ctx


def get_attachment_for_application(app_id: str) -> dict:
    data, _ = _list(api_client.list_attachments(COORD, params={"application_id": app_id}))
    return data[0] if data else None


def get_make_ready_invoice_for_application(app_id: str) -> dict:
    data, _ = _list(api_client.list_invoices(COORD, params={"application_id": app_id}))
    # MAKE_READY invoice for this application (first-year ANNUAL_RENTAL also carries
    # the application_id; filter to MAKE_READY).
    mk = [i for i in data if i.get("invoice_type") == "MAKE_READY"]
    return mk[0] if mk else (data[0] if data else None)


def _list(resp):
    """Extract (data_list, meta) from a list response envelope leniently."""
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 4: Findings & their auto-issued invoices ─────────────────────────
def create_finding(pole_id: str, attacher_id: str, **overrides) -> dict:
    """FieldAuditor logs an unauthorized-attachment finding (FLAGGED); an
    UNAUTHORIZED invoice is auto-issued."""
    return get_success_data(
        api_client.create_finding(
            create_finding_payload(pole_id, attacher_id, **overrides), AUDITOR
        )
    )


def legalize_finding(finding_id: str) -> dict:
    return get_success_data(
        api_client.resolve_finding(finding_id, {"resolution": "LEGALIZE"}, COORD)
    )


def create_legalized_attachment(pole_id: str, attacher_id: str, space_inches: int,
                                position_inches: int) -> dict:
    """Create a finding then legalize it, producing an ACTIVE authorized=false
    Attachment of the given space. Returns the finding after legalization."""
    finding = create_finding(
        pole_id, attacher_id,
        discovered_space_inches=space_inches,
        discovered_position_inches=position_inches,
        good_faith=True,
        estimated_install_years_ago=1,
    )
    return legalize_finding(finding["id"])


# ─── Tier 5: Disputes ──────────────────────────────────────────────────────
def open_dispute_on_finding(attacher_id: str, finding_id: str, reason="not ours") -> dict:
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(attacher_id, finding_id=finding_id, reason=reason),
            make_attacher_headers(attacher_id),
        )
    )


def open_dispute_on_invoice(attacher_id: str, invoice_id: str, reason="overcharged") -> dict:
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(attacher_id, invoice_id=invoice_id, reason=reason),
            make_attacher_headers(attacher_id),
        )
    )


def dispute_to_under_review(dispute_id: str) -> dict:
    """Coordinator opens review: OPEN -> UNDER_REVIEW."""
    return get_success_data(
        api_client.transition_dispute(dispute_id, {"to_state": "UNDER_REVIEW"}, COORD)
    )


def dispute_request_info(dispute_id: str) -> dict:
    """Coordinator requests info: UNDER_REVIEW -> INFO_REQUESTED."""
    return get_success_data(
        api_client.transition_dispute(dispute_id, {"to_state": "INFO_REQUESTED"}, COORD)
    )


def dispute_respond(dispute_id: str, attacher_id: str) -> dict:
    """Attacher responds: INFO_REQUESTED -> UNDER_REVIEW (round_count += 1)."""
    return get_success_data(
        api_client.transition_dispute(
            dispute_id, {"to_state": "UNDER_REVIEW"}, make_attacher_headers(attacher_id)
        )
    )
