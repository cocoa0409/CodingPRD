"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the server (empty DB) before every test, so every helper
builds its preconditions from scratch using only PRD-declared endpoints. All
helpers use ``get_success_data`` (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion mismatches.

Identity threading: the Applicant is entity-backed, so ownership-gated calls
use ``make_applicant_headers(applicant["id"])`` — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_support_structure_payload,
    create_row_segment_payload,
    create_application_payload,
    create_node_payload,
    completeness_review_payload,
    design_review_payload,
    aesthetic_review_payload,
    inspection_payload,
    payment_payload,
    decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_row_reviewer_headers,
    make_aesthetic_reviewer_headers,
    make_approver_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_SUBMIT_CLOCK = "2026-06-01T00:00:00Z"
DEFAULT_DECISION_CLOCK = "2026-07-15T00:00:00Z"
DEFAULT_ACTIVATION_CLOCK = "2026-08-20T00:00:00Z"
DEFAULT_CONSTRUCTION_DATE = "2026-06-15T00:00:00Z"


# ─── Atomic seeding helpers ───────────────────────────────────────────────
def set_clock(iso: str):
    return get_success_data(api_client.set_clock(iso, ADMIN))


def register_applicant(company_name="Acme Wireless", contact_email="ops@acme.example",
                       sign=True) -> dict:
    applicant = get_success_data(
        api_client.create_applicant(
            create_applicant_payload(company_name=company_name, contact_email=contact_email),
            ADMIN,
        )
    )
    if sign:
        applicant = get_success_data(
            api_client.sign_master_agreement(
                applicant["id"], make_applicant_headers(applicant["id"])
            )
        )
    return applicant


def create_structure(max_collocations=2, structure_type="EXISTING_UTILITY",
                     in_design_district="NONE", location_desc=None) -> dict:
    payload = create_support_structure_payload(
        structure_type=structure_type, max_collocations=max_collocations,
        in_design_district=in_design_district,
    )
    if location_desc is not None:
        payload["location_desc"] = location_desc
    return get_success_data(api_client.create_support_structure(payload, ADMIN))


def create_segment(name="Main St", corridor_code="C-1", in_historic_district=False,
                   last_paved_at=None, moratorium_months=None) -> dict:
    payload = create_row_segment_payload(
        name=name, corridor_code=corridor_code, in_historic_district=in_historic_district,
    )
    if last_paved_at is not None:
        payload["last_paved_at"] = last_paved_at
    if moratorium_months is not None:
        payload["moratorium_months"] = moratorium_months
    return get_success_data(api_client.create_row_segment(payload, ADMIN))


def open_application(applicant_id, project_name=None) -> dict:
    payload = create_application_payload()
    if project_name is not None:
        payload["project_name"] = project_name
    return get_success_data(
        api_client.create_application(payload, make_applicant_headers(applicant_id))
    )


def add_node(app_id, applicant_id, support_structure_id, row_segment_id,
             facility_type="COLLOCATION",
             proposed_construction_date=DEFAULT_CONSTRUCTION_DATE) -> dict:
    return get_success_data(
        api_client.add_node(
            app_id,
            create_node_payload(
                support_structure_id, row_segment_id,
                facility_type=facility_type,
                proposed_construction_date=proposed_construction_date,
            ),
            make_applicant_headers(applicant_id),
        )
    )


def submit(app_id, applicant_id) -> dict:
    return get_success_data(
        api_client.submit_application(app_id, make_applicant_headers(applicant_id))
    )


def record_completeness(app_id, complete=True, reviewer_id="rowrev-1", deficiencies=None) -> dict:
    payload = completeness_review_payload(complete=complete)
    if deficiencies is not None:
        payload["deficiencies"] = deficiencies
    return get_success_data(
        api_client.completeness_review(app_id, payload, make_row_reviewer_headers(reviewer_id))
    )


def cure(app_id, applicant_id) -> dict:
    return get_success_data(
        api_client.cure_application(app_id, make_applicant_headers(applicant_id))
    )


def structure_version(ss_id, reader_id="rowrev-1") -> int:
    data = get_success_data(
        api_client.get_support_structure(ss_id, make_row_reviewer_headers(reader_id))
    )
    return data["version"]


def fetch_structure(ss_id) -> dict:
    return get_success_data(api_client.get_support_structure(ss_id, ADMIN))


def fetch_node(node_id) -> dict:
    return get_success_data(api_client.get_node(node_id, ADMIN))


def fetch_application(app_id) -> dict:
    return get_success_data(api_client.get_application(app_id, ADMIN))


def record_design_review(node_id, ss_id, outcome="PASS", reviewer_id="rowrev-1",
                         expected_version=None) -> dict:
    if expected_version is None:
        expected_version = structure_version(ss_id, reader_id=reviewer_id)
    return get_success_data(
        api_client.design_review(
            node_id,
            design_review_payload(expected_version, outcome=outcome),
            make_row_reviewer_headers(reviewer_id),
        )
    )


def record_aesthetic_review(node_id, outcome="PASS", reviewer_id="aesrev-1") -> dict:
    return get_success_data(
        api_client.aesthetic_review(
            node_id, aesthetic_review_payload(outcome=outcome),
            make_aesthetic_reviewer_headers(reviewer_id),
        )
    )


def decide(app_id, approver_id="approver-1") -> dict:
    return get_success_data(
        api_client.decide_application(app_id, decision_payload(), make_approver_headers(approver_id))
    )


def fetch_invoice(app_id, applicant_id) -> dict:
    data = get_success_data(
        api_client.get_application_fee_invoice(app_id, make_applicant_headers(applicant_id))
    )
    return data[0]


def pay_full(app_id, applicant_id) -> dict:
    """Read the current invoice and pay its full outstanding balance."""
    invoice = fetch_invoice(app_id, applicant_id)
    outstanding = invoice["outstanding_amount_cents"]
    return get_success_data(
        api_client.create_payment(
            invoice["id"],
            payment_payload(outstanding, invoice["version"]),
            make_applicant_headers(applicant_id),
        )
    )


def record_inspection(node_id, outcome="PASS", inspector_id="insp-1") -> dict:
    return get_success_data(
        api_client.create_inspection(
            node_id, inspection_payload(outcome=outcome), make_inspector_headers(inspector_id)
        )
    )


def activate(node_id, inspector_id="insp-1") -> dict:
    return get_success_data(
        api_client.activate_node(node_id, make_inspector_headers(inspector_id))
    )


def first_rental(node_id) -> dict:
    data = get_success_data(api_client.list_node_rentals(node_id, ADMIN))
    return data[0]


# ─── Composite scenarios ──────────────────────────────────────────────────
def setup_under_review_single(structure_kwargs=None, segment_kwargs=None,
                              facility_type="COLLOCATION",
                              construction_date=DEFAULT_CONSTRUCTION_DATE,
                              submit_clock=DEFAULT_SUBMIT_CLOCK) -> dict:
    """Registered+signed applicant, one structure, one segment, a single-node
    application submitted then moved to UNDER_REVIEW (completeness=true).
    Returns a context dict."""
    structure_kwargs = structure_kwargs or {}
    segment_kwargs = segment_kwargs or {}
    applicant = register_applicant()
    structure = create_structure(**structure_kwargs)
    segment = create_segment(**segment_kwargs)
    set_clock(submit_clock)
    app = open_application(applicant["id"], project_name="P")
    node = add_node(
        app["id"], applicant["id"], structure["id"], segment["id"],
        facility_type=facility_type, proposed_construction_date=construction_date,
    )
    submit(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    return {
        "applicant": applicant,
        "structure": structure,
        "segment": segment,
        "app": app,
        "node": node,
    }


def setup_granted_single_collocation(submit_clock=DEFAULT_SUBMIT_CLOCK,
                                     decision_clock=DEFAULT_DECISION_CLOCK,
                                     pay=True, inspect=False,
                                     inspection_outcome="PASS") -> dict:
    """Single COLLOCATION node driven to GRANTED (design PASS + decision).
    Optionally pays the final invoice and records an inspection. Returns a
    context dict including the granted application and permitted node."""
    ctx = setup_under_review_single(submit_clock=submit_clock)
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    set_clock(decision_clock)
    decide(ctx["app"]["id"])
    if pay:
        pay_full(ctx["app"]["id"], ctx["applicant"]["id"])
    if inspect:
        record_inspection(ctx["node"]["id"], outcome=inspection_outcome)
    ctx["invoice"] = fetch_invoice(ctx["app"]["id"], ctx["applicant"]["id"])
    ctx["node"] = fetch_node(ctx["node"]["id"])
    return ctx


def setup_activated_single_collocation(submit_clock=DEFAULT_SUBMIT_CLOCK,
                                       decision_clock=DEFAULT_DECISION_CLOCK,
                                       activation_clock=DEFAULT_ACTIVATION_CLOCK) -> dict:
    """Single COLLOCATION node driven all the way to ACTIVATED with an ACTIVE
    rental. Returns a context dict; ``rental`` is the activated rental."""
    ctx = setup_granted_single_collocation(
        submit_clock=submit_clock, decision_clock=decision_clock,
        pay=True, inspect=True, inspection_outcome="PASS",
    )
    set_clock(activation_clock)
    activate(ctx["node"]["id"])
    ctx["node"] = fetch_node(ctx["node"]["id"])
    ctx["structure"] = fetch_structure(ctx["structure"]["id"])
    ctx["rental"] = first_rental(ctx["node"]["id"])
    return ctx


def setup_submitted_single(structure_kwargs=None, segment_kwargs=None,
                           facility_type="COLLOCATION",
                           construction_date=DEFAULT_CONSTRUCTION_DATE,
                           submit_clock=DEFAULT_SUBMIT_CLOCK) -> dict:
    """Single-node application left in SUBMITTED (no completeness review yet)."""
    structure_kwargs = structure_kwargs or {}
    segment_kwargs = segment_kwargs or {}
    applicant = register_applicant()
    structure = create_structure(**structure_kwargs)
    segment = create_segment(**segment_kwargs)
    set_clock(submit_clock)
    app = open_application(applicant["id"], project_name="P")
    node = add_node(
        app["id"], applicant["id"], structure["id"], segment["id"],
        facility_type=facility_type, proposed_construction_date=construction_date,
    )
    submit(app["id"], applicant["id"])
    return {
        "applicant": applicant,
        "structure": structure,
        "segment": segment,
        "app": app,
        "node": node,
    }


def setup_denied_single_collocation(submit_clock=DEFAULT_SUBMIT_CLOCK,
                                    decision_clock=DEFAULT_DECISION_CLOCK,
                                    pay=False) -> dict:
    """Single COLLOCATION node design-FAILed then decided to DENIED."""
    ctx = setup_under_review_single(submit_clock=submit_clock)
    if pay:
        pay_full(ctx["app"]["id"], ctx["applicant"]["id"])
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="FAIL")
    set_clock(decision_clock)
    decide(ctx["app"]["id"])
    ctx["invoice"] = fetch_invoice(ctx["app"]["id"], ctx["applicant"]["id"])
    ctx["node"] = fetch_node(ctx["node"]["id"])
    return ctx
