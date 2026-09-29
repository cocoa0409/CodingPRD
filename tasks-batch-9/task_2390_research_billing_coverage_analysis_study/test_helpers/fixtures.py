"""Composite setup helpers for the Research Billing Coverage Analysis API.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — the database is empty at the start of every test.  Setup calls
go through ``get_success_data`` so a broken precondition reports itself as a
setup failure rather than as a confusing assertion failure inside a test.

The chain these helpers encapsulate is the spine of the product:

    clock -> register protocol -> settle the Medicare question -> open an
    analysis -> add items -> submit -> approve -> build the calendar
    (visits + charge routes) -> publish -> build and execute the budget ->
    open accrual -> register and consent a subject -> schedule and complete a
    visit (which drops charges) -> review charges -> raise, submit and remit a
    sponsor invoice -> open, respond to and resolve an audit finding -> file
    and implement an amendment -> run the aging epoch.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accrual_payload,
    aging_run_payload,
    budget_build_payload,
    charge_review_payload,
    consent_payload,
    create_amendment_payload,
    create_audit_finding_payload,
    create_calendar_visit_payload,
    create_charge_payload,
    create_coverage_analysis_payload,
    create_coverage_item_payload,
    create_sponsor_invoice_payload,
    create_study_calendar_payload,
    create_study_payload,
    create_study_subject_payload,
    create_subject_visit_payload,
    create_visit_charge_route_payload,
    qct_determination_payload,
    remittance_payload,
    resolve_finding_payload,
    respond_finding_payload,
    return_analysis_payload,
)
from .test_users import (
    ANALYST_ONE,
    COORDINATOR_ONE,
    LIAISON_ONE,
    LIAISON_TWO,
    MANAGER_ONE,
    MANAGER_TWO,
    REVIEWER_ONE,
    make_analyst_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
)

# ==========================================================================
# Grid, visit and route specifications
# ==========================================================================


def item_spec(
    item_code,
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=0,
    negotiated_unit_cents=0,
    expected_occurrences=1,
    medicare_coverage_basis=None,
    units_per_occurrence=None,
    description=None,
):
    """One row of a coverage analysis grid, as overrides for the item payload."""
    if medicare_coverage_basis is None:
        medicare_coverage_basis = (
            "STANDARD_OF_CARE" if classification == "ROUTINE_CARE" else "NOT_COVERED"
        )
    spec = {
        "item_code": item_code,
        "description": description or f"Protocol item {item_code}",
        "classification": classification,
        "medicare_coverage_basis": medicare_coverage_basis,
        "budget_category": budget_category,
        "charge_master_unit_cents": charge_master_unit_cents,
        "negotiated_unit_cents": negotiated_unit_cents,
        "expected_occurrences": expected_occurrences,
    }
    if units_per_occurrence is not None:
        spec["units_per_occurrence"] = units_per_occurrence
    return spec


def visit_spec(
    visit_name,
    sequence_index,
    target_day_offset,
    window_before_days=0,
    window_after_days=0,
):
    """One visit of a calendar generation, as overrides for the visit payload."""
    return {
        "visit_name": visit_name,
        "sequence_index": sequence_index,
        "target_day_offset": target_day_offset,
        "window_before_days": window_before_days,
        "window_after_days": window_after_days,
    }


def route_spec(visit_name, item_code, occurrences=None):
    """One visit charge route, naming its visit and item by their business keys."""
    spec = {"visit_name": visit_name, "item_code": item_code}
    if occurrences is not None:
        spec["occurrences"] = occurrences
    return spec


# A sponsor-borne per-patient item priced at 40,000 cents negotiated, the
# workhorse of the sponsor-invoicing scenarios.
SPONSOR_ITEM_J9999 = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)

# A routine-care item on the comprehensive metabolic panel, the workhorse of
# the payer-side scenarios.
ROUTINE_ITEM_80053 = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=1,
    medicare_coverage_basis="STANDARD_OF_CARE",
)

# A promotional item: zero-cost and never budgeted.
PROMOTIONAL_ITEM_A9270 = item_spec(
    "A9270",
    classification="PROMOTIONAL",
    budget_category="NOT_BUDGETED",
    charge_master_unit_cents=0,
    negotiated_unit_cents=0,
    expected_occurrences=1,
)


# ==========================================================================
# Tier 0: single-step primitives
# ==========================================================================


def set_clock(to_iso8601, user_id=MANAGER_ONE):
    """Move the server's logical clock to ``to_iso8601``."""
    return get_success_data(
        api_client.set_clock(to_iso8601, make_manager_headers(user_id))
    )


def register_study(user_id=MANAGER_ONE, **overrides):
    """Register a protocol in the research billing office."""
    return get_success_data(
        api_client.create_study(
            create_study_payload(**overrides), make_manager_headers(user_id)
        )
    )


def read_study(study_id, user_id=MANAGER_ONE):
    return get_success_data(
        api_client.get_study(study_id, make_manager_headers(user_id))
    )


def study_version(study_id, user_id=MANAGER_ONE):
    """The study's current ``version``, for the §2.6 optimistic-concurrency guards."""
    return read_study(study_id, user_id)["version"]


def determine_qct(study_id, basis="DEEMED_IND_IDE", user_id=REVIEWER_ONE, **overrides):
    """Record the Medicare qualifying-clinical-trial determination."""
    return get_success_data(
        api_client.record_qct_determination(
            study_id,
            qct_determination_payload(basis=basis, **overrides),
            make_reviewer_headers(user_id),
        )
    )


def open_analysis(study_id, expected_version=None, user_id=ANALYST_ONE, **overrides):
    """Open a coverage analysis revision against a study."""
    if expected_version is None:
        expected_version = study_version(study_id)
    return get_success_data(
        api_client.create_coverage_analysis(
            create_coverage_analysis_payload(study_id, expected_version, **overrides),
            make_analyst_headers(user_id),
        )
    )


def read_analysis(analysis_id, user_id=ANALYST_ONE):
    return get_success_data(
        api_client.get_coverage_analysis(analysis_id, make_analyst_headers(user_id))
    )


def analysis_version(analysis_id, user_id=ANALYST_ONE):
    """The analysis' current ``version``, for the §2.6 item-add guard."""
    return read_analysis(analysis_id, user_id)["version"]


def add_item(analysis_id, expected_version=None, user_id=ANALYST_ONE, **overrides):
    """Add one immutable item to a draft or returned analysis."""
    if expected_version is None:
        expected_version = analysis_version(analysis_id)
    return get_success_data(
        api_client.create_coverage_item(
            create_coverage_item_payload(analysis_id, expected_version, **overrides),
            make_analyst_headers(user_id),
        )
    )


def add_items(analysis_id, specs, user_id=ANALYST_ONE):
    """Add a whole grid, re-reading the analysis version before each add.

    Returns ``(items, item_by_code)``; items are in the order they were added,
    which is also the order the analysis returns them.
    """
    items = []
    for spec in specs:
        items.append(add_item(analysis_id, user_id=user_id, **spec))
    return items, {item["item_code"]: item for item in items}


def submit_analysis(analysis_id, user_id=ANALYST_ONE):
    """Send a draft analysis to compliance review."""
    return get_success_data(
        api_client.submit_coverage_analysis(analysis_id, make_analyst_headers(user_id))
    )


def return_analysis(analysis_id, user_id=REVIEWER_ONE, **overrides):
    """Return an analysis under review to the analyst."""
    return get_success_data(
        api_client.return_coverage_analysis(
            analysis_id,
            return_analysis_payload(**overrides),
            make_reviewer_headers(user_id),
        )
    )


def approve_analysis(analysis_id, user_id=REVIEWER_ONE):
    """Approve an analysis under review.  The approver must not be the preparer."""
    return get_success_data(
        api_client.approve_coverage_analysis(
            analysis_id, make_reviewer_headers(user_id)
        )
    )


def build_budget(
    study_id,
    source_analysis_id,
    expected_version=None,
    basis="COVERAGE_DRIVEN",
    indirect_rate_pct=20.0,
    user_id=MANAGER_ONE,
    **overrides,
):
    """Build the sponsor budget from an approved coverage analysis."""
    if expected_version is None:
        expected_version = study_version(study_id)
    payload = budget_build_payload(
        source_analysis_id,
        expected_version,
        basis=basis,
        indirect_rate_pct=indirect_rate_pct,
        **overrides,
    )
    return get_success_data(
        api_client.build_budget(study_id, payload, make_manager_headers(user_id))
    )


def execute_budget(study_id, user_id=MANAGER_TWO):
    """Execute the built budget.  The executor must not be the builder."""
    return get_success_data(
        api_client.execute_budget(study_id, make_manager_headers(user_id))
    )


def create_calendar(study_id, source_analysis_id, user_id=ANALYST_ONE):
    """Start a new EHR study-calendar generation from an approved analysis."""
    return get_success_data(
        api_client.create_study_calendar(
            create_study_calendar_payload(study_id, source_analysis_id),
            make_analyst_headers(user_id),
        )
    )


def add_visit(calendar_id, user_id=ANALYST_ONE, **overrides):
    """Add a visit to a draft calendar."""
    return get_success_data(
        api_client.create_calendar_visit(
            create_calendar_visit_payload(calendar_id, **overrides),
            make_analyst_headers(user_id),
        )
    )


def add_route(calendar_visit_id, coverage_item_id, user_id=ANALYST_ONE, **overrides):
    """Link a coverage item to a calendar visit."""
    return get_success_data(
        api_client.create_visit_charge_route(
            create_visit_charge_route_payload(
                calendar_visit_id, coverage_item_id, **overrides
            ),
            make_analyst_headers(user_id),
        )
    )


def publish_calendar(calendar_id, user_id=REVIEWER_ONE):
    """Publish a draft calendar into the EHR and retire earlier generations."""
    return get_success_data(
        api_client.publish_study_calendar(calendar_id, make_reviewer_headers(user_id))
    )


def read_calendar(calendar_id, user_id=ANALYST_ONE):
    return get_success_data(
        api_client.get_study_calendar(calendar_id, make_analyst_headers(user_id))
    )


def open_accrual(study_id, user_id=MANAGER_ONE):
    """Open the protocol to accrual."""
    return get_success_data(
        api_client.set_accrual(
            study_id,
            accrual_payload(target_status="OPEN_TO_ACCRUAL"),
            make_manager_headers(user_id),
        )
    )


def close_accrual(study_id, user_id=MANAGER_ONE):
    """Close the protocol to accrual, cascading subjects and scheduled visits."""
    return get_success_data(
        api_client.set_accrual(
            study_id,
            accrual_payload(target_status="CLOSED_TO_ACCRUAL"),
            make_manager_headers(user_id),
        )
    )


def register_subject(study_id, subject_number="S-001", user_id=COORDINATOR_ONE):
    """Register a screening subject on a protocol open to accrual."""
    return get_success_data(
        api_client.create_study_subject(
            create_study_subject_payload(study_id, subject_number=subject_number),
            make_coordinator_headers(user_id),
        )
    )


def consent_subject(subject_id, consent_date="2026-09-01", user_id=COORDINATOR_ONE):
    """Record informed consent, pinning the study's published calendar generation."""
    return get_success_data(
        api_client.consent_study_subject(
            subject_id,
            consent_payload(consent_date=consent_date),
            make_coordinator_headers(user_id),
        )
    )


def schedule_visit(
    study_subject_id, calendar_visit_id, actual_service_date, user_id=COORDINATOR_ONE
):
    """Schedule a calendar visit for a consented subject."""
    return get_success_data(
        api_client.create_subject_visit(
            create_subject_visit_payload(
                study_subject_id, calendar_visit_id, actual_service_date
            ),
            make_coordinator_headers(user_id),
        )
    )


def complete_visit(subject_visit_id, user_id=COORDINATOR_ONE):
    """Record that the visit occurred, dropping one charge per visit charge route."""
    return get_success_data(
        api_client.complete_subject_visit(
            subject_visit_id, make_coordinator_headers(user_id)
        )
    )


def post_charge(study_id, user_id=COORDINATOR_ONE, **overrides):
    """Post a charge from the EHR charge interface."""
    return get_success_data(
        api_client.create_charge(
            create_charge_payload(study_id, **overrides),
            make_coordinator_headers(user_id),
        )
    )


def read_charge(charge_id, user_id=MANAGER_ONE):
    return get_success_data(
        api_client.get_charge(charge_id, make_manager_headers(user_id))
    )


def review_charge(charge_id, decision, user_id=REVIEWER_ONE, **overrides):
    """Route an unrouted charge, hold it for the sponsor, or write it off."""
    return get_success_data(
        api_client.review_charge(
            charge_id,
            charge_review_payload(decision, **overrides),
            make_reviewer_headers(user_id),
        )
    )


def read_summary(study_id, user_id=MANAGER_ONE):
    """The billing office's per-study segregation dashboard."""
    return get_success_data(
        api_client.get_charge_review_summary(study_id, make_manager_headers(user_id))
    )


def raise_invoice(
    study_id,
    expected_version=None,
    period_end_date="2026-12-31",
    user_id=MANAGER_ONE,
    **overrides,
):
    """Raise a draft sponsor invoice and select its lines under the waterfall."""
    if expected_version is None:
        expected_version = study_version(study_id)
    return get_success_data(
        api_client.create_sponsor_invoice(
            create_sponsor_invoice_payload(
                study_id,
                expected_version,
                period_end_date=period_end_date,
                **overrides,
            ),
            make_manager_headers(user_id),
        )
    )


def submit_invoice(invoice_id, user_id=MANAGER_ONE):
    """Submit a draft invoice to the sponsor, or re-submit a disputed one."""
    return get_success_data(
        api_client.submit_sponsor_invoice(invoice_id, make_manager_headers(user_id))
    )


def remit(invoice_id, outcome, user_id=MANAGER_ONE, **overrides):
    """Record the sponsor's response."""
    return get_success_data(
        api_client.record_remittance(
            invoice_id,
            remittance_payload(outcome, **overrides),
            make_manager_headers(user_id),
        )
    )


def open_finding(study_id, user_id=LIAISON_ONE, **overrides):
    """Open an audit finding against a study or one of its charges."""
    return get_success_data(
        api_client.create_audit_finding(
            create_audit_finding_payload(study_id, **overrides),
            make_liaison_headers(user_id),
        )
    )


def respond_finding(finding_id, user_id=LIAISON_TWO, **overrides):
    """File the billing office's response.  The responder must not be the opener."""
    return get_success_data(
        api_client.respond_audit_finding(
            finding_id,
            respond_finding_payload(**overrides),
            make_liaison_headers(user_id),
        )
    )


def resolve_finding(finding_id, disposition, user_id=LIAISON_TWO, **overrides):
    """Close a responded finding."""
    return get_success_data(
        api_client.resolve_audit_finding(
            finding_id,
            resolve_finding_payload(disposition, **overrides),
            make_liaison_headers(user_id),
        )
    )


def file_amendment(
    study_id, scope="ITEM_CHANGE", effective_date="2026-08-01", user_id=MANAGER_ONE
):
    """File a protocol amendment."""
    return get_success_data(
        api_client.create_amendment(
            create_amendment_payload(
                study_id, scope=scope, effective_date=effective_date
            ),
            make_manager_headers(user_id),
        )
    )


def implement_amendment(amendment_id, user_id=MANAGER_ONE):
    """Implement an effective amendment, firing the five-link cascade."""
    return get_success_data(
        api_client.implement_amendment(amendment_id, make_manager_headers(user_id))
    )


def run_aging(study_id, user_id=MANAGER_ONE):
    """Advance the unbilled-charge aging epoch for one study."""
    return get_success_data(
        api_client.run_aging(aging_run_payload(study_id), make_manager_headers(user_id))
    )


# ==========================================================================
# Tier 1-2: study with a coverage analysis grid
# ==========================================================================


def setup_study_with_draft_grid(
    item_specs=None,
    clock=None,
    qct_basis=None,
    qct_registry_number=None,
    study_overrides=None,
    analyst=ANALYST_ONE,
    reviewer=REVIEWER_ONE,
):
    """Protocol registered, Medicare question optionally settled, one DRAFT
    analysis carrying ``item_specs``.

    Returns a context dict with ``study``, ``analysis``, ``items`` and
    ``item_by_code``.  ``study`` is re-read at the end so its ``version`` and
    ledger reflect every cascade that has fired.
    """
    if clock is not None:
        set_clock(clock)
    study = register_study(**(study_overrides or {}))
    if qct_basis is not None:
        extra = {}
        if qct_registry_number is not None:
            extra["registry_number"] = qct_registry_number
        study = determine_qct(study["id"], basis=qct_basis, user_id=reviewer, **extra)
    analysis = open_analysis(study["id"], user_id=analyst)
    items, item_by_code = add_items(analysis["id"], item_specs or [], user_id=analyst)
    return {
        "study": read_study(study["id"]),
        "analysis": read_analysis(analysis["id"]),
        "items": items,
        "item_by_code": item_by_code,
    }


def setup_study_with_analysis_under_review(item_specs=None, **kwargs):
    """As above, then submitted to compliance so the analysis is UNDER_REVIEW."""
    ctx = setup_study_with_draft_grid(
        item_specs or [SPONSOR_ITEM_J9999], **kwargs
    )
    analyst = kwargs.get("analyst", ANALYST_ONE)
    submit_analysis(ctx["analysis"]["id"], user_id=analyst)
    ctx["analysis"] = read_analysis(ctx["analysis"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_study_with_approved_analysis(item_specs=None, approver=REVIEWER_ONE, **kwargs):
    """The full coverage chain: registered -> determined -> grid -> submitted ->
    APPROVED, leaving the study at COVERAGE_APPROVED.

    ``qct_basis`` defaults to ``DEEMED_IND_IDE`` because approval of a grid
    carrying a conditional routine-care item requires a determination, and the
    default grid is safe either way.
    """
    kwargs.setdefault("qct_basis", "DEEMED_IND_IDE")
    kwargs.setdefault("qct_registry_number", "NCT10000000")
    ctx = setup_study_with_analysis_under_review(item_specs, **kwargs)
    approve_analysis(ctx["analysis"]["id"], user_id=approver)
    ctx["analysis"] = read_analysis(ctx["analysis"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_study_with_built_budget(
    item_specs=None,
    basis="COVERAGE_DRIVEN",
    indirect_rate_pct=20.0,
    builder=MANAGER_ONE,
    **kwargs,
):
    """Approved analysis, then the sponsor budget built from it."""
    ctx = setup_study_with_approved_analysis(item_specs, **kwargs)
    build_budget(
        ctx["study"]["id"],
        ctx["analysis"]["id"],
        basis=basis,
        indirect_rate_pct=indirect_rate_pct,
        user_id=builder,
    )
    ctx["study"] = read_study(ctx["study"]["id"])
    ctx["budget_builder"] = builder
    return ctx


def setup_study_with_executed_budget(
    item_specs=None, builder=MANAGER_ONE, executor=MANAGER_TWO, **kwargs
):
    """Built budget, then executed by a different manager."""
    ctx = setup_study_with_built_budget(item_specs, builder=builder, **kwargs)
    execute_budget(ctx["study"]["id"], user_id=executor)
    ctx["study"] = read_study(ctx["study"]["id"])
    ctx["budget_executor"] = executor
    return ctx


# ==========================================================================
# Tier 3: calendar generations
# ==========================================================================


def build_calendar_generation(
    ctx, visit_specs, route_specs=None, publish=False, analyst=ANALYST_ONE
):
    """Add one calendar generation to an existing context.

    ``visit_specs`` come from :func:`visit_spec`; ``route_specs`` from
    :func:`route_spec`, naming their visit by ``visit_name`` and their item by
    ``item_code``.  The generation is published when ``publish`` is true.

    Adds ``calendar``, ``visits``, ``visit_by_name`` and ``routes`` to the
    context and returns it.
    """
    calendar = create_calendar(
        ctx["study"]["id"], ctx["analysis"]["id"], user_id=analyst
    )
    visits = []
    visit_by_name = {}
    for spec in visit_specs:
        visit = add_visit(calendar["id"], user_id=analyst, **spec)
        visits.append(visit)
        visit_by_name[visit["visit_name"]] = visit
    routes = []
    for spec in route_specs or []:
        spec = dict(spec)
        visit_name = spec.pop("visit_name")
        item_code = spec.pop("item_code")
        routes.append(
            add_route(
                visit_by_name[visit_name]["id"],
                ctx["item_by_code"][item_code]["id"],
                user_id=analyst,
                **spec,
            )
        )
    if publish:
        publish_calendar(calendar["id"])
    ctx["calendar"] = read_calendar(calendar["id"])
    ctx["visits"] = visits
    ctx["visit_by_name"] = visit_by_name
    ctx["routes"] = routes
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_published_calendar(
    item_specs=None, visit_specs=None, route_specs=None, **kwargs
):
    """Approved analysis plus one PUBLISHED calendar generation.

    The default generation is a single day-zero visit routing the default
    sponsor item, which is exactly what a publication needs: at least one
    visit and nothing left unrouted.
    """
    if item_specs is None:
        item_specs = [SPONSOR_ITEM_J9999]
    if visit_specs is None:
        visit_specs = [visit_spec("Screening", 1, 0, 0, 3)]
    if route_specs is None:
        route_specs = [route_spec("Screening", item_specs[0]["item_code"])]
    ctx = setup_study_with_approved_analysis(item_specs, **kwargs)
    return build_calendar_generation(
        ctx, visit_specs, route_specs, publish=True, analyst=kwargs.get("analyst", ANALYST_ONE)
    )


def setup_open_to_accrual(
    item_specs=None,
    visit_specs=None,
    route_specs=None,
    basis="COVERAGE_DRIVEN",
    indirect_rate_pct=20.0,
    builder=MANAGER_ONE,
    executor=MANAGER_TWO,
    **kwargs,
):
    """Everything upstream of accrual: approved analysis, published calendar,
    budget built and executed, protocol OPEN_TO_ACCRUAL.

    A qualifying determination plus a registry number is set up by default
    because opening a qualifying trial to accrual demands one.
    """
    ctx = setup_published_calendar(item_specs, visit_specs, route_specs, **kwargs)
    build_budget(
        ctx["study"]["id"],
        ctx["analysis"]["id"],
        basis=basis,
        indirect_rate_pct=indirect_rate_pct,
        user_id=builder,
    )
    execute_budget(ctx["study"]["id"], user_id=executor)
    open_accrual(ctx["study"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    ctx["budget_builder"] = builder
    ctx["budget_executor"] = executor
    return ctx


# ==========================================================================
# Tier 4: accrual, visits and the charges they drop
# ==========================================================================


def setup_consented_subject(
    ctx, subject_number="S-001", consent_date="2026-09-01", coordinator=COORDINATOR_ONE
):
    """Register and consent one subject on an open protocol.

    Consent pins the study's single PUBLISHED calendar onto the subject.
    Returns the consented subject; the context gains ``subject``.
    """
    subject = register_subject(
        ctx["study"]["id"], subject_number=subject_number, user_id=coordinator
    )
    subject = consent_subject(
        subject["id"], consent_date=consent_date, user_id=coordinator
    )
    ctx["subject"] = subject
    return subject


def setup_scheduled_visit(
    ctx,
    visit_name=None,
    actual_service_date="2026-09-02",
    subject=None,
    coordinator=COORDINATOR_ONE,
):
    """Schedule one occurrence of a calendar visit for a consented subject."""
    subject = subject or ctx["subject"]
    if visit_name is None:
        visit_name = ctx["visits"][0]["visit_name"]
    subject_visit = schedule_visit(
        subject["id"],
        ctx["visit_by_name"][visit_name]["id"],
        actual_service_date,
        user_id=coordinator,
    )
    ctx["subject_visit"] = subject_visit
    return subject_visit


def setup_visit_generated_charges(
    item_specs=None,
    visit_specs=None,
    route_specs=None,
    consent_date="2026-09-01",
    actual_service_date="2026-09-02",
    clock=None,
    **kwargs,
):
    """The whole spine through to a completed visit that has dropped charges.

    Returns the context with ``subject``, ``subject_visit`` (completed) and
    ``charges`` — the study's charges, oldest-created first.
    """
    ctx = setup_open_to_accrual(item_specs, visit_specs, route_specs, clock=clock, **kwargs)
    setup_consented_subject(ctx, consent_date=consent_date)
    setup_scheduled_visit(ctx, actual_service_date=actual_service_date)
    complete_visit(ctx["subject_visit"]["id"])
    ctx["subject_visit"] = get_success_data(
        api_client.get_subject_visit(
            ctx["subject_visit"]["id"], make_coordinator_headers(COORDINATOR_ONE)
        )
    )
    ctx["subject"] = get_success_data(
        api_client.get_study_subject(
            ctx["subject"]["id"], make_coordinator_headers(COORDINATOR_ONE)
        )
    )
    ctx["charges"] = list_study_charges(ctx["study"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def list_study_charges(study_id, user_id=MANAGER_ONE, **params):
    """The study's charges, in creation order."""
    query = {"study_id": study_id}
    query.update(params)
    body = api_client.list_charges(make_manager_headers(user_id), params=query)
    return get_success_data(body)


# ==========================================================================
# Tier 4: charges positioned for review and invoicing
# ==========================================================================


def setup_charge_awaiting_review(
    item_specs=None,
    charge_code="80053",
    service_date="2026-08-01",
    amount_cents=9000,
    clock=None,
    **kwargs,
):
    """Approved analysis covering ``charge_code``, plus one interface-posted
    charge sitting UNROUTED and UNBILLED, ready for a review decision.

    The context gains ``charge``.
    """
    if item_specs is None:
        item_specs = [ROUTINE_ITEM_80053]
    ctx = setup_study_with_approved_analysis(item_specs, clock=clock, **kwargs)
    ctx["charge"] = post_charge(
        ctx["study"]["id"],
        charge_code=charge_code,
        service_date=service_date,
        amount_cents=amount_cents,
    )
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_payer_billed_charge(**kwargs):
    """A charge cleared to the payer: ROUTED_PAYER and BILLED_PAYER.

    Clearing to the payer requires the posture to be OPEN, so the default
    determination is a qualifying one.
    """
    ctx = setup_charge_awaiting_review(**kwargs)
    review_charge(ctx["charge"]["id"], "CLEAR_TO_PAYER")
    ctx["charge"] = read_charge(ctx["charge"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_sponsor_unbilled_charge(
    charge_code="J9999", amount_cents=40000, item_specs=None, **kwargs
):
    """A charge held for the sponsor: ROUTED_SPONSOR and UNBILLED — the only
    pair a sponsor invoice will pick up.
    """
    if item_specs is None:
        item_specs = [SPONSOR_ITEM_J9999]
    ctx = setup_charge_awaiting_review(
        item_specs=item_specs,
        charge_code=charge_code,
        amount_cents=amount_cents,
        **kwargs,
    )
    review_charge(ctx["charge"]["id"], "HOLD_FOR_SPONSOR")
    ctx["charge"] = read_charge(ctx["charge"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_sponsor_unbilled_charges(
    charge_specs, item_specs=None, clock=None, **kwargs
):
    """Several sponsor-held charges on one study, for the invoice waterfall.

    ``charge_specs`` is a list of dicts of overrides for the charge payload;
    each is posted and then held for the sponsor in the order given.  The
    context gains ``charges`` in that order.
    """
    if item_specs is None:
        item_specs = [SPONSOR_ITEM_J9999]
    ctx = setup_study_with_approved_analysis(item_specs, clock=clock, **kwargs)
    charges = []
    for spec in charge_specs:
        charge = post_charge(ctx["study"]["id"], **spec)
        review_charge(charge["id"], "HOLD_FOR_SPONSOR")
        charges.append(read_charge(charge["id"]))
    ctx["charges"] = charges
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_priced_study_with_sponsor_charges(
    charge_specs,
    item_specs=None,
    indirect_rate_pct=32.0,
    basis="COVERAGE_DRIVEN",
    builder=MANAGER_ONE,
    clock=None,
    **kwargs,
):
    """Sponsor-held charges on a study whose ``effective_indirect_rate_pct``
    has been settled by a budget build — the invoice line selector needs that
    rate to compute each line's indirect.
    """
    if item_specs is None:
        item_specs = [SPONSOR_ITEM_J9999]
    ctx = setup_study_with_approved_analysis(item_specs, clock=clock, **kwargs)
    build_budget(
        ctx["study"]["id"],
        ctx["analysis"]["id"],
        basis=basis,
        indirect_rate_pct=indirect_rate_pct,
        user_id=builder,
    )
    charges = []
    for spec in charge_specs:
        charge = post_charge(ctx["study"]["id"], **spec)
        review_charge(charge["id"], "HOLD_FOR_SPONSOR")
        charges.append(read_charge(charge["id"]))
    ctx["charges"] = charges
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_draft_invoice(charge_specs, period_end_date="2026-12-31", **kwargs):
    """A DRAFT sponsor invoice with its lines already selected."""
    ctx = setup_priced_study_with_sponsor_charges(charge_specs, **kwargs)
    ctx["invoice"] = raise_invoice(
        ctx["study"]["id"], period_end_date=period_end_date
    )
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_submitted_invoice(charge_specs, **kwargs):
    """A SUBMITTED sponsor invoice; its charges have moved to INVOICED_SPONSOR."""
    ctx = setup_draft_invoice(charge_specs, **kwargs)
    ctx["invoice"] = submit_invoice(ctx["invoice"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


# ==========================================================================
# Tier 5: audit findings, amendments and the aging epoch
# ==========================================================================


def setup_open_finding(ctx=None, opener=LIAISON_ONE, **overrides):
    """Open an audit finding, which drives the posture straight to ALL_BLOCKED."""
    if ctx is None:
        ctx = setup_study_with_approved_analysis()
    ctx["finding"] = open_finding(ctx["study"]["id"], user_id=opener, **overrides)
    ctx["finding_opener"] = opener
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_responded_finding(
    ctx=None, opener=LIAISON_ONE, responder=LIAISON_TWO, **overrides
):
    """A finding taken OPEN -> RESPONDED by a different liaison, ready to resolve."""
    ctx = setup_open_finding(ctx, opener=opener, **overrides)
    ctx["finding"] = respond_finding(ctx["finding"]["id"], user_id=responder)
    ctx["finding_responder"] = responder
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_refundable_finding(
    clock=None,
    charge_code="80053",
    service_date="2026-08-01",
    amount_cents=9000,
    opener=LIAISON_ONE,
    responder=LIAISON_TWO,
    **kwargs,
):
    """A payer-billed charge with a RESPONDED finding naming it — the exact
    precondition a REFUND_AND_REROUTE resolution demands.
    """
    ctx = setup_payer_billed_charge(
        clock=clock,
        charge_code=charge_code,
        service_date=service_date,
        amount_cents=amount_cents,
        **kwargs,
    )
    ctx = setup_responded_finding(
        ctx,
        opener=opener,
        responder=responder,
        charge_id=ctx["charge"]["id"],
        finding_type="IMPROPER_PAYER_BILL",
        claimed_amount_cents=amount_cents,
    )
    ctx["charge"] = read_charge(ctx["charge"]["id"])
    return ctx


def setup_submitted_amendment(
    ctx=None, scope="ITEM_CHANGE", effective_date="2026-08-01", **kwargs
):
    """A SUBMITTED amendment on a study whose lifecycle permits implementation."""
    if ctx is None:
        ctx = setup_study_with_approved_analysis(**kwargs)
    ctx["amendment"] = file_amendment(
        ctx["study"]["id"], scope=scope, effective_date=effective_date
    )
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_rebuild_blocked_study(
    item_specs=None,
    visit_specs=None,
    route_specs=None,
    clock=None,
    effective_date="2026-08-01",
    scope="ITEM_AND_SCHEDULE_CHANGE",
    budget=False,
    indirect_rate_pct=32.0,
    builder=MANAGER_ONE,
    executor=MANAGER_TWO,
    implement_at=None,
    **kwargs,
):
    """A study driven into the rebuild-induced ALL_BLOCKED posture: a published
    calendar moved to REBUILD_REQUIRED by an implemented amendment.

    When ``budget`` is true the sponsor budget is built and executed before the
    amendment lands, so the implementation also supersedes an executed budget.
    """
    ctx = setup_published_calendar(item_specs, visit_specs, route_specs, clock=clock, **kwargs)
    if budget:
        build_budget(
            ctx["study"]["id"],
            ctx["analysis"]["id"],
            indirect_rate_pct=indirect_rate_pct,
            user_id=builder,
        )
        execute_budget(ctx["study"]["id"], user_id=executor)
        ctx["budget_builder"] = builder
        ctx["budget_executor"] = executor
    ctx = setup_submitted_amendment(ctx, scope=scope, effective_date=effective_date)
    if implement_at is not None:
        set_clock(implement_at)
    ctx["amendment"] = implement_amendment(ctx["amendment"]["id"])
    ctx["calendar"] = read_calendar(ctx["calendar"]["id"])
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def setup_aged_sponsor_charge(
    unbilled_at="2026-08-10T00:00:00Z",
    run_at=None,
    charge_code="J9999",
    amount_cents=40000,
    service_date=None,
    **kwargs,
):
    """A sponsor-held charge whose ``unbilled_since`` is pinned at
    ``unbilled_at``, with the clock optionally advanced to ``run_at``.

    ``service_date`` defaults to the calendar date of ``unbilled_at`` so the
    approval that covers the charge still counts as effective on that date.

    The aging epoch is not run here — the caller decides when the epoch moves,
    because unbilled age is deliberately stale between runs.
    """
    if service_date is None:
        service_date = unbilled_at[:10]
    ctx = setup_sponsor_unbilled_charge(
        clock=unbilled_at,
        charge_code=charge_code,
        amount_cents=amount_cents,
        service_date=service_date,
        **kwargs,
    )
    if run_at is not None:
        set_clock(run_at)
    return ctx
