"""
Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so each helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup failed" messages rather than confusing assertions.

Identity threading: Reviewer and SubcontractorRep are entity-backed (PRD §2.1),
so ownership-gated calls always pass the acting entity's id through
make_reviewer_headers / make_subcontractor_rep_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_installation_activity_payload,
    create_lli_advance_payload,
    create_owner_report_payload,
    create_price_payload,
    create_project_payload,
    create_reviewer_payload,
    create_revision_payload,
    create_rfi_answer_payload,
    create_rfi_payload,
    create_spec_section_payload,
    create_subcontractor_payload,
)
from .test_users import (
    TEST_USERS,
    make_reviewer_headers,
    make_subcontractor_rep_headers,
)

PA = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]
OR = TEST_USERS["owner_rep_headers"]


# ─── Tier 0: clock ──────────────────────────────────────────────────


def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Position the logical clock (PRD §2.11)."""
    return get_success_data(api_client.set_clock(to_iso8601, PA))


# ─── Tier 1: single resources ───────────────────────────────────────


def create_project(project_name="Test Project", **overrides) -> dict:
    return get_success_data(
        api_client.create_project(create_project_payload(project_name, **overrides), PA)
    )


def get_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, PE))


def current_project_version(project_id) -> int:
    return get_project(project_id)["version"]


def activate_project(project_id) -> dict:
    return get_success_data(api_client.activate_project(project_id, PM))


def create_active_project(project_name="Test Project", **overrides) -> dict:
    """Create + activate a project. Returns the project as ACTIVE."""
    project = create_project(project_name, **overrides)
    return activate_project(project["id"])


def add_subcontractor(project_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_subcontractor(
            project_id, create_subcontractor_payload(**overrides), PE
        )
    )


def add_reviewer(project_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_reviewer(project_id, create_reviewer_payload(**overrides), PM)
    )


def add_spec_section(project_id, section_number="051200", **overrides) -> dict:
    return get_success_data(
        api_client.create_spec_section(
            project_id, create_spec_section_payload(section_number, **overrides), PE
        )
    )


def activate_spec_section(section_id) -> dict:
    return get_success_data(api_client.activate_spec_section(section_id, PE))


# ─── Tier 2: submittal register ─────────────────────────────────────


def project_submittals(project_id) -> list:
    return get_success_data(api_client.list_project_submittals(project_id, PE))


def submittals_of_section(project_id, section_number) -> list:
    """Submittals generated from one section, identified by the PRD-pinned
    item_number format '<section_number>-<NN>' (PRD §3.1)."""
    prefix = f"{section_number}-"
    return [
        s
        for s in project_submittals(project_id)
        if str(s.get("item_number", "")).startswith(prefix)
    ]


def get_submittal(submittal_id) -> dict:
    return get_success_data(api_client.get_submittal(submittal_id, PE))


def current_submittal_version(submittal_id) -> int:
    return get_submittal(submittal_id)["version"]


def lli_of_submittal(submittal_id):
    """The long-lead item of a submittal, or None (array of zero or one, PRD §3.4)."""
    items = get_success_data(api_client.get_submittal_long_lead_item(submittal_id, PE))
    assert isinstance(items, list) and len(items) <= 1, (
        f"Expected an array of zero or one long-lead item, got {items!r}"
    )
    return items[0] if items else None


def setup_register_world(
    project_name="Register Project",
    section_number="051200",
    lead_time_days=20,
    review_days=10,
    default_need_date="2026-10-30",
    required_submittal_kinds=("SHOP_DRAWINGS",),
    reviewers=({"display_name": "Arch One", "discipline": "ARCH"},),
    with_subcontractor=True,
    project_overrides=None,
):
    """ACTIVE project + responsible subcontractor + reviewers + activated section.

    Returns dict(project, subcontractor, reviewers, section, submittals).
    Submittals are ordered by the section's kind array order (creation order).
    """
    project = create_active_project(project_name, **(project_overrides or {}))
    subcontractor = (
        add_subcontractor(project["id"], company_name="SteelFab", trade="structural steel")
        if with_subcontractor
        else None
    )
    created_reviewers = [add_reviewer(project["id"], **r) for r in reviewers]
    section_kwargs = {
        "lead_time_days": lead_time_days,
        "review_days": review_days,
        "default_need_date": default_need_date,
        "required_submittal_kinds": list(required_submittal_kinds),
    }
    if subcontractor is not None:
        section_kwargs["responsible_subcontractor_id"] = subcontractor["id"]
    section = add_spec_section(project["id"], section_number, **section_kwargs)
    activate_spec_section(section["id"])
    submittals = submittals_of_section(project["id"], section_number)
    assert len(submittals) == len(required_submittal_kinds), (
        f"Register generation produced {len(submittals)} submittals, "
        f"expected {len(required_submittal_kinds)}"
    )
    return {
        "project": project,
        "subcontractor": subcontractor,
        "reviewers": created_reviewers,
        "section": section,
        "submittals": submittals,
    }


def setup_long_lead_world(clock_to=None, **kwargs) -> dict:
    """Register world whose section is long-lead (lead >= threshold): the sole
    submittal carries a linked LongLeadItem and expediting MONITORING (PRD §3.1)."""
    kwargs.setdefault("lead_time_days", 35)
    world = setup_register_world(**kwargs)
    if clock_to is not None:
        set_clock(clock_to)
        # Regenerate nothing: the world was built at the default clock; callers
        # that need generation-time lateness pass clock_to BEFORE building via
        # setup_long_lead_world_at_clock instead.
    world["lli"] = lli_of_submittal(world["submittals"][0]["id"])
    return world


def setup_long_lead_world_at_clock(clock_to, **kwargs) -> dict:
    """Long-lead world where the clock is positioned BEFORE register generation,
    so the item's days_late/escalation/score reflect that clock (PRD §3.1)."""
    project_overrides = kwargs.pop("project_overrides", None)
    section_number = kwargs.pop("section_number", "051200")
    lead_time_days = kwargs.pop("lead_time_days", 35)
    review_days = kwargs.pop("review_days", 10)
    default_need_date = kwargs.pop("default_need_date", "2026-10-30")
    required_submittal_kinds = kwargs.pop("required_submittal_kinds", ("SHOP_DRAWINGS",))

    project = create_active_project("LongLead Project", **(project_overrides or {}))
    subcontractor = add_subcontractor(
        project["id"], company_name="SteelFab", trade="structural steel"
    )
    reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
    section = add_spec_section(
        project["id"],
        section_number,
        lead_time_days=lead_time_days,
        review_days=review_days,
        default_need_date=default_need_date,
        responsible_subcontractor_id=subcontractor["id"],
        required_submittal_kinds=list(required_submittal_kinds),
    )
    set_clock(clock_to)
    activate_spec_section(section["id"])
    submittals = submittals_of_section(project["id"], section_number)
    return {
        "project": project,
        "subcontractor": subcontractor,
        "reviewers": [reviewer],
        "reviewer": reviewer,
        "section": section,
        "submittals": submittals,
        "submittal": submittals[0],
        "lli": lli_of_submittal(submittals[0]["id"]),
    }


# ─── Tier 3: review cycle ───────────────────────────────────────────


def submit_revision(submittal_id, subcontractor_id, document_ref="doc://rev") -> dict:
    """Submit a revision as the responsible subcontractor at the current version."""
    version = current_submittal_version(submittal_id)
    return get_success_data(
        api_client.create_revision(
            submittal_id,
            create_revision_payload(document_ref, version),
            make_subcontractor_rep_headers(subcontractor_id),
        )
    )


def route_revision(revision_id, reviewer_id=None) -> dict:
    payload = {} if reviewer_id is None else {"reviewer_id": reviewer_id}
    return get_success_data(api_client.route_revision(revision_id, payload, PE))


def return_revision(revision_id, reviewer_id, action_code="A", comments=None) -> dict:
    payload = {"action_code": action_code}
    if comments is not None:
        payload["comments"] = comments
    return get_success_data(
        api_client.return_revision(revision_id, payload, make_reviewer_headers(reviewer_id))
    )


def get_reviewer(reviewer_id) -> dict:
    return get_success_data(api_client.get_reviewer(reviewer_id, PE))


def setup_approved_submittal(
    need_date="2026-09-01",
    lead_time_days=5,
    review_days=5,
    action_code="A",
    section_number="033000",
    project_overrides=None,
) -> dict:
    """Register world + one revision submitted, routed, and returned with an
    approving action code: the submittal stands APPROVED (PRD §3.2)."""
    world = setup_register_world(
        section_number=section_number,
        lead_time_days=lead_time_days,
        review_days=review_days,
        default_need_date=need_date,
        required_submittal_kinds=("PRODUCT_DATA",),
        project_overrides=project_overrides,
    )
    submittal = world["submittals"][0]
    subcontractor = world["subcontractor"]
    reviewer = world["reviewers"][0]
    revision = submit_revision(submittal["id"], subcontractor["id"], "doc://rev0")
    route_revision(revision["id"], reviewer["id"])
    revision = return_revision(revision["id"], reviewer["id"], action_code)
    world.update(
        {
            "submittal": get_submittal(submittal["id"]),
            "revision": revision,
            "reviewer": reviewer,
        }
    )
    return world


def setup_released_submittal(**kwargs) -> dict:
    """Approved submittal released for construction (PRD §3.3): QUEUED
    DistributionRecords exist for the affected-subcontractor set."""
    world = setup_approved_submittal(**kwargs)
    submittal = get_success_data(
        api_client.release_submittal_for_construction(world["submittal"]["id"], PE)
    )
    world["submittal"] = submittal
    world["distribution_records"] = distribution_records_for_source(
        world["project"]["id"], submittal["id"]
    )
    return world


# ─── Tier 3b: RFI flow ──────────────────────────────────────────────


def create_rfi(project_id, expected_project_version=None, **overrides) -> dict:
    if expected_project_version is None:
        expected_project_version = current_project_version(project_id)
    overrides.setdefault("subject", "RFI subject")
    overrides.setdefault("question_text", "RFI question?")
    return get_success_data(
        api_client.create_rfi(
            project_id,
            create_rfi_payload(
                overrides.pop("subject"),
                overrides.pop("question_text"),
                expected_project_version,
                **overrides,
            ),
            PE,
        )
    )


def route_rfi(rfi_id, reviewer_id=None) -> dict:
    payload = {} if reviewer_id is None else {"reviewer_id": reviewer_id}
    return get_success_data(api_client.route_rfi(rfi_id, payload, PE))


def answer_rfi(rfi_id, reviewer_id, **overrides) -> dict:
    return get_success_data(
        api_client.answer_rfi(
            rfi_id, create_rfi_answer_payload(**overrides), make_reviewer_headers(reviewer_id)
        )
    )


def create_answered_rfi(
    project_id,
    reviewer_id,
    spec_section_id=None,
    submittal_id=None,
    subject="RFI subject",
    answer_overrides=None,
) -> dict:
    """Create + route + answer an RFI (no impacts by default). Returns the RFI."""
    kwargs = {}
    if spec_section_id is not None:
        kwargs["spec_section_id"] = spec_section_id
    if submittal_id is not None:
        kwargs["submittal_id"] = submittal_id
    rfi = create_rfi(project_id, subject=subject, **kwargs)
    route_rfi(rfi["id"], reviewer_id)
    answer_kwargs = {"answer_text": "answered"}
    answer_kwargs.update(answer_overrides or {})
    answer_rfi(rfi["id"], reviewer_id, **answer_kwargs)
    return get_success_data(api_client.get_rfi(rfi["id"], PE))


# ─── Tier 3c: impact assessments & the contingency ledger ───────────


def assessment_for_rfi(project_id, rfi_id) -> dict:
    """The ImpactAssessment auto-created by an RFI's cost-flagged answer;
    it carries the source RFI's id as its rfi_id (PRD §3.6)."""
    assessments = get_success_data(
        api_client.list_project_impact_assessments(project_id, PE)
    )
    matches = [a for a in assessments if a.get("rfi_id") == rfi_id]
    assert len(matches) == 1, (
        f"Expected exactly one assessment for RFI {rfi_id}, found {len(matches)}"
    )
    return matches[0]


def price_assessment(assessment_id, sub_quote_cents, user_id="op-pe-1") -> dict:
    from .test_users import make_project_engineer_headers

    return get_success_data(
        api_client.price_impact_assessment(
            assessment_id,
            create_price_payload(sub_quote_cents),
            make_project_engineer_headers(user_id),
        )
    )


def accept_assessment(assessment_id, user_id="op-pm-1") -> dict:
    from .test_users import make_project_manager_headers

    return get_success_data(
        api_client.accept_impact_assessment(
            assessment_id, make_project_manager_headers(user_id)
        )
    )


def waive_assessment(assessment_id, user_id="op-pm-1") -> dict:
    from .test_users import make_project_manager_headers

    return get_success_data(
        api_client.waive_impact_assessment(
            assessment_id, make_project_manager_headers(user_id)
        )
    )


def setup_estimated_assessment(
    initial_contingency_cents=2_000_000,
    estimated_cost_cents=100_000,
    schedule_impact_days=None,
    submittal_id=None,
    project_name="Impact Project",
) -> dict:
    """ACTIVE project + ARCH reviewer + cost-flagged answered RFI.

    Returns dict(project, reviewer, rfi, assessment) with the assessment in
    ESTIMATED (PRD §3.6). schedule_impact_days additionally declares a
    schedule impact on the answer.
    """
    project = create_active_project(
        project_name, initial_contingency_cents=initial_contingency_cents
    )
    reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
    rfi_kwargs = {}
    if submittal_id is not None:
        rfi_kwargs["submittal_id"] = submittal_id
    rfi = create_rfi(project["id"], subject="Cost impact question", **rfi_kwargs)
    route_rfi(rfi["id"], reviewer["id"])
    answer_kwargs = {
        "answer_text": "premium work required",
        "cost_impact_flag": True,
        "estimated_cost_cents": estimated_cost_cents,
    }
    if schedule_impact_days is not None:
        answer_kwargs["schedule_impact_flag"] = True
        answer_kwargs["estimated_schedule_days"] = schedule_impact_days
    answer_rfi(rfi["id"], reviewer["id"], **answer_kwargs)
    assessment = assessment_for_rfi(project["id"], rfi["id"])
    return {
        "project": project,
        "reviewer": reviewer,
        "rfi": rfi,
        "assessment": assessment,
    }


# ─── Tier 3d: distribution ──────────────────────────────────────────


def distribute_rfi(rfi_id) -> list:
    """Distribute an answered RFI; returns the created DistributionRecords."""
    return get_success_data(api_client.distribute_rfi(rfi_id, PE))


def distribution_records_for_source(project_id, source_id) -> list:
    records = get_success_data(
        api_client.list_project_distribution_records(project_id, PE)
    )
    return [r for r in records if r.get("source_id") == source_id]


def send_record(record_id) -> dict:
    return get_success_data(api_client.send_distribution_record(record_id, PE))


def get_record(record_id) -> dict:
    return get_success_data(api_client.get_distribution_record(record_id, PE))


def get_subcontractor(subcontractor_id) -> dict:
    return get_success_data(api_client.get_subcontractor(subcontractor_id, PE))


def setup_distributed_rfi(clock_to="2026-08-03T09:00:00Z", project_overrides=None) -> dict:
    """ACTIVE project + responsible subcontractor + reviewer + section; one RFI
    linked to the section, answered and distributed (PRD §3.5). Records remain
    QUEUED. Returns dict(project, subcontractor, reviewer, section, rfi, records).
    """
    project = create_active_project("Distribution Project", **(project_overrides or {}))
    subcontractor = add_subcontractor(
        project["id"], company_name="MechCo", trade="mechanical"
    )
    reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
    section = add_spec_section(
        project["id"], "230000", responsible_subcontractor_id=subcontractor["id"]
    )
    if clock_to is not None:
        set_clock(clock_to)
    rfi = create_answered_rfi(project["id"], reviewer["id"], spec_section_id=section["id"])
    records = distribute_rfi(rfi["id"])
    return {
        "project": project,
        "subcontractor": subcontractor,
        "reviewer": reviewer,
        "section": section,
        "rfi": rfi,
        "records": records,
    }


def setup_sent_distributions(count, clock_to="2026-08-03T09:00:00Z") -> dict:
    """`count` RFIs, each answered, distributed to the section's responsible
    subcontractor, and sent at `clock_to` (PRD §3.3/§3.5)."""
    world = setup_distributed_rfi(clock_to=clock_to)
    records = list(world["records"])
    for record in records:
        send_record(record["id"])
    rfis = [world["rfi"]]
    for i in range(1, count):
        rfi = create_answered_rfi(
            world["project"]["id"],
            world["reviewer"]["id"],
            spec_section_id=world["section"]["id"],
            subject=f"RFI {i + 1}",
        )
        for record in distribute_rfi(rfi["id"]):
            send_record(record["id"])
            records.append(record)
        rfis.append(rfi)
    world["rfis"] = rfis
    world["records"] = [get_record(r["id"]) for r in records]
    return world


# ─── Tier 3e: installation activities ───────────────────────────────


def create_activity(
    project_id, submittal_id, subcontractor_id, start_date, end_date, description=None
) -> dict:
    return get_success_data(
        api_client.create_installation_activity(
            project_id,
            create_installation_activity_payload(
                submittal_id, subcontractor_id, start_date, end_date, description
            ),
            PE,
        )
    )


def get_activity(activity_id) -> dict:
    return get_success_data(api_client.get_installation_activity(activity_id, PE))


# ─── Tier 3f: owner reports ─────────────────────────────────────────


def create_owner_report(project_id, period_start, period_end, expected_project_version=None) -> dict:
    if expected_project_version is None:
        expected_project_version = current_project_version(project_id)
    return get_success_data(
        api_client.create_owner_report(
            project_id,
            create_owner_report_payload(period_start, period_end, expected_project_version),
            PE,
        )
    )


def publish_owner_report(report_id) -> dict:
    return get_success_data(api_client.publish_owner_report(report_id, PE))


def report_metrics(report_id, view=None) -> dict:
    params = {} if view is None else {"view": view}
    return get_success_data(api_client.get_owner_report_metrics(report_id, PE, params=params))


# ─── Tier 3g: escalation events (append-only log) ───────────────────


def escalation_events(event_type=None, source_id=None) -> list:
    """All escalation events (fresh database per test), filtered in code."""
    events = get_success_data(api_client.list_escalation_events(PE))
    if event_type is not None:
        events = [e for e in events if e.get("event_type") == event_type]
    if source_id is not None:
        events = [e for e in events if e.get("source_id") == source_id]
    return events


# ─── Tier 4: threshold targeting ────────────────────────────────────


def setup_reviewer_capacity_world(num_submittals=4, r1_capacity=3, with_r2=True) -> dict:
    """Register world with one submittal per register kind, one revision
    submitted on each, and ARCH reviewers R1 (created first) and R2.

    Returns dict(world fields..., revisions)."""
    kinds = ["PRODUCT_DATA", "SHOP_DRAWINGS", "SAMPLES", "MOCKUP"][:num_submittals]
    reviewers = [{"display_name": "Arch One", "discipline": "ARCH", "review_capacity": r1_capacity}]
    if with_r2:
        reviewers.append({"display_name": "Arch Two", "discipline": "ARCH", "review_capacity": 3})
    world = setup_register_world(
        project_name="Capacity Project",
        lead_time_days=20,
        review_days=10,
        default_need_date="2026-10-30",
        required_submittal_kinds=tuple(kinds),
        reviewers=reviewers,
    )
    revisions = [
        submit_revision(s["id"], world["subcontractor"]["id"], f"doc://r{i}")
        for i, s in enumerate(world["submittals"])
    ]
    world["revisions"] = revisions
    world["reviewer"] = world["reviewers"][0]
    return world
