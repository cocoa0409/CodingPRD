"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database,
using only endpoints the PRD declares. Setup calls use the lenient success
validator so that a broken precondition surfaces as a setup failure rather than
as a confusing assertion failure inside a test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    partner_org_payload, program_cycle_payload, project_request_payload,
    scope_definition_payload, deliverable_payload, volunteer_payload,
    skill_profile_payload, availability_window_payload, agreement_payload,
    time_log_payload, milestone_payload, handoff_payload,
    deliverable_scores_payload,
)
from .test_users import (
    make_program_manager_headers, make_scoping_specialist_headers,
    make_quality_reviewer_headers, make_volunteer_headers,
    make_partner_contact_headers, PM_USER_ID, SPEC_USER_ID, QR_USER_ID,
)

# ---------------------------------------------------------------------------
# Canonical timeline. The logical clock reads 2026-08-01T00:00:00Z at startup
# and only ever moves forward, so every literal below sits at or after that
# instant.
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
CYCLE_START = "2026-08-01T00:00:00Z"
CYCLE_END = "2026-12-01T00:00:00Z"
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-11-01T00:00:00Z"
WORK_DATE = "2026-08-12T00:00:00Z"
MILESTONE_DUE = "2026-08-20T00:00:00Z"
HOLD_CLOCK = "2026-08-19T00:00:00Z"

DEFAULT_DELIVERABLES = [
    {
        "title": "Findings memo",
        "sequence_no": 1,
        "weight_pct": 60.00,
        "hours_estimate": 24.00,
        "acceptance_criteria": "Board-ready memo with cited findings.",
    },
    {
        "title": "Remediation plan",
        "sequence_no": 2,
        "weight_pct": 40.00,
        "hours_estimate": 16.00,
        "acceptance_criteria": "Twelve-month remediation plan with owners.",
    },
]

STAGES = [
    "roster", "draft", "scoping", "scoped", "matching", "engaged",
    "agreement_drafted", "agreement_sent", "agreement_executed",
    "in_progress", "held", "submitted", "accepted", "handed_off",
]


# ---------------------------------------------------------------- primitives
def set_clock(to_iso8601: str, headers=None):
    """Move the logical clock forward to `to_iso8601`."""
    return get_success_data(
        api_client.set_clock(
            {"to_iso8601": to_iso8601}, headers or make_program_manager_headers()
        )
    )


def create_partner(pm_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_partner_org(
            partner_org_payload(**overrides),
            pm_headers or make_program_manager_headers(),
        )
    )


def create_cycle(pm_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_program_cycle(
            program_cycle_payload(**overrides),
            pm_headers or make_program_manager_headers(),
        )
    )


def create_volunteer(pm_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_volunteer(
            volunteer_payload(**overrides), pm_headers or make_program_manager_headers()
        )
    )


def create_skill_profile(volunteer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_skill_profile(
            volunteer_id,
            skill_profile_payload(**overrides),
            make_volunteer_headers(volunteer_id),
        )
    )


def vet_volunteer(volunteer_id: str, verify_skill_codes=None, pm_headers=None) -> dict:
    payload = {}
    if verify_skill_codes is not None:
        payload["verify_skill_codes"] = verify_skill_codes
    return get_success_data(
        api_client.vet_volunteer(
            volunteer_id, payload, pm_headers or make_program_manager_headers()
        )
    )


def create_window(volunteer_id: str, **overrides) -> dict:
    defaults = {"starts_at": WINDOW_START, "ends_at": WINDOW_END}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_availability_window(
            volunteer_id,
            availability_window_payload(**defaults),
            make_volunteer_headers(volunteer_id),
        )
    )


def create_vetted_volunteer(
    skill_code: str = "TAX_LAW",
    proficiency: int = 4,
    verify_skill: bool = True,
    years_experience: float = 10.0,
    window: bool = True,
    window_overrides=None,
    **volunteer_overrides,
) -> tuple:
    """Enrol a volunteer, declare one skill claim, vet, and (optionally) publish
    one availability window. Returns (volunteer, skill_profile, window|None)."""
    volunteer = create_volunteer(**volunteer_overrides)
    skill = create_skill_profile(
        volunteer["id"],
        skill_code=skill_code,
        proficiency=proficiency,
        years_experience=years_experience,
    )
    vet_volunteer(volunteer["id"], [skill_code] if verify_skill else [])
    win = None
    if window:
        win = create_window(volunteer["id"], **(window_overrides or {}))
    volunteer = get_success_data(
        api_client.get_volunteer(volunteer["id"], make_program_manager_headers())
    )
    return volunteer, skill, win


def setup_selector_world(
    candidates,
    *,
    clock: str = None,
    partner_budget: float = 12000000.00,
    cycle_slots: int = 10,
    cycle_starts_at: str = CYCLE_START,
    cycle_ends_at: str = CYCLE_END,
    skill_code: str = "LEGAL_CONTRACTS",
    min_proficiency: int = 3,
    urgency: str = "ROUTINE",
    requested_hours: float = 40.00,
    estimated_hours: float = 40.00,
    complexity_factor: float = 1.00,
    confidentiality_tier: str = "STANDARD",
    ip_disposition: str = "ASSIGN_TO_PARTNER",
    deliverables=None,
    title: str = "Selector request",
    approve: bool = True,
) -> dict:
    """Build a cycle, a partner, an arbitrary candidate roster and one request whose
    revision is approved, stopping short of running the selector.

    Each entry of `candidates` is a dict of keyword arguments understood by
    `create_vetted_volunteer` — for example
    `{"seniority": "ASSOCIATE", "proficiency": 5, "verify_skill": True,
      "window_overrides": {"hours_offered": 24.00}}`.
    """
    pm = make_program_manager_headers()
    spec = make_scoping_specialist_headers()
    w: dict = {"pm_headers": pm, "spec_headers": spec, "spec_user_id": SPEC_USER_ID}
    w["cycle"] = create_cycle(
        pm,
        starts_at=cycle_starts_at,
        ends_at=cycle_ends_at,
        capacity_slot_total=cycle_slots,
    )
    w["partner"] = create_partner(pm, annual_budget_usd=partner_budget)
    w["partner_headers"] = make_partner_contact_headers(w["partner"]["id"])
    if clock:
        set_clock(clock, pm)

    w["candidates"] = []
    for spec_row in candidates:
        row = dict(spec_row)
        row.setdefault("skill_code", skill_code)
        volunteer, skill, win = create_vetted_volunteer(**row)
        w["candidates"].append(
            {
                "volunteer": volunteer,
                "skill_profile": skill,
                "window": win,
                "volunteer_headers": make_volunteer_headers(volunteer["id"]),
            }
        )

    w["request"] = get_success_data(
        api_client.create_project_request(
            project_request_payload(
                w["partner"]["id"],
                w["cycle"]["id"],
                title=title,
                required_skill_code=skill_code,
                min_proficiency=min_proficiency,
                requested_hours=requested_hours,
                urgency=urgency,
            ),
            w["partner_headers"],
        )
    )
    w["request"] = get_success_data(
        api_client.submit_for_scoping(w["request"]["id"], w["partner_headers"])
    )
    w["scope"] = get_success_data(
        api_client.create_scope_definition(
            w["request"]["id"],
            scope_definition_payload(
                w["request"]["version"],
                estimated_hours=estimated_hours,
                complexity_factor=complexity_factor,
                confidentiality_tier=confidentiality_tier,
                ip_disposition=ip_disposition,
            ),
            spec,
        )
    )
    dspecs = DEFAULT_DELIVERABLES if deliverables is None else deliverables
    w["deliverables"] = [
        get_success_data(
            api_client.create_deliverable(
                w["scope"]["id"], deliverable_payload(**d), spec
            )
        )
        for d in dspecs
    ]
    if approve:
        w["scope"] = get_success_data(
            api_client.approve_scope_definition(w["scope"]["id"], w["partner_headers"])
        )
        w["request"] = get_success_data(
            api_client.get_project_request(w["request"]["id"], pm)
        )
    return w


# ------------------------------------------------------------------- world
def setup_world(
    stage: str = "engaged",
    *,
    partner_budget: float = 12000000.00,
    cycle_slots: int = 10,
    cycle_starts_at: str = CYCLE_START,
    cycle_ends_at: str = CYCLE_END,
    volunteer_seniority: str = "SENIOR",
    volunteer_rate: float = 150.00,
    skill_code: str = "TAX_LAW",
    proficiency: int = 4,
    verify_skill: bool = True,
    window_starts_at: str = WINDOW_START,
    window_ends_at: str = WINDOW_END,
    window_kind: str = "HARD",
    window_hours: float = 300.00,
    urgency: str = "ROUTINE",
    min_proficiency: int = 3,
    requested_hours: float = 40.00,
    estimated_hours: float = 40.00,
    complexity_factor: float = 1.00,
    confidentiality_tier: str = "STANDARD",
    ip_disposition: str = "ASSIGN_TO_PARTNER",
    deliverables=None,
    title: str = "Annual audit readiness",
    agreement_ip_disposition=None,
    agreement_confidentiality_tier=None,
    indemnity_cap_usd: float = 10000.00,
    time_logs=None,
    milestone_due_at: str = MILESTONE_DUE,
    hold_clock: str = HOLD_CLOCK,
    reported_cumulative_hours: float = 40.00,
    review_scores=None,
    handoff_artifact_count: int = 3,
    destruction_certificate_ref=None,
    spec_user_id: str = SPEC_USER_ID,
    reviewer_user_id: str = QR_USER_ID,
    pm_user_id: str = PM_USER_ID,
    request_overrides=None,
) -> dict:
    """Walk the program from an empty database up to `stage`.

    Returns a dict of the created rows and the role headers needed to act on
    them. Identity-backed roles are always threaded with the acting entity's own
    id: `partner_headers` carries the PartnerOrg id and `volunteer_headers`
    carries the Volunteer id.
    """
    assert stage in STAGES, f"unknown stage {stage!r}"
    stage_index = STAGES.index(stage)
    pm = make_program_manager_headers(pm_user_id)
    spec = make_scoping_specialist_headers(spec_user_id)
    qr = make_quality_reviewer_headers(reviewer_user_id)

    w: dict = {
        "pm_headers": pm,
        "spec_headers": spec,
        "reviewer_headers": qr,
        "pm_user_id": pm_user_id,
        "spec_user_id": spec_user_id,
        "reviewer_user_id": reviewer_user_id,
    }

    w["cycle"] = create_cycle(
        pm,
        starts_at=cycle_starts_at,
        ends_at=cycle_ends_at,
        capacity_slot_total=cycle_slots,
    )
    w["partner"] = create_partner(pm, annual_budget_usd=partner_budget)
    w["partner_headers"] = make_partner_contact_headers(w["partner"]["id"])

    volunteer, skill, win = create_vetted_volunteer(
        skill_code=skill_code,
        proficiency=proficiency,
        verify_skill=verify_skill,
        window_overrides={
            "starts_at": window_starts_at,
            "ends_at": window_ends_at,
            "window_kind": window_kind,
            "hours_offered": window_hours,
        },
        seniority=volunteer_seniority,
        professional_rate_usd_per_hour=volunteer_rate,
    )
    w["volunteer"] = volunteer
    w["skill_profile"] = skill
    w["window"] = win
    w["volunteer_headers"] = make_volunteer_headers(volunteer["id"])

    if stage_index < STAGES.index("draft"):
        return w

    req_kwargs = {
        "title": title,
        "required_skill_code": skill_code,
        "min_proficiency": min_proficiency,
        "requested_hours": requested_hours,
        "urgency": urgency,
    }
    req_kwargs.update(request_overrides or {})
    w["request"] = get_success_data(
        api_client.create_project_request(
            project_request_payload(w["partner"]["id"], w["cycle"]["id"], **req_kwargs),
            w["partner_headers"],
        )
    )

    if stage_index < STAGES.index("scoping"):
        return w

    w["request"] = get_success_data(
        api_client.submit_for_scoping(w["request"]["id"], w["partner_headers"])
    )

    w["scope"] = get_success_data(
        api_client.create_scope_definition(
            w["request"]["id"],
            scope_definition_payload(
                w["request"]["version"],
                estimated_hours=estimated_hours,
                complexity_factor=complexity_factor,
                confidentiality_tier=confidentiality_tier,
                ip_disposition=ip_disposition,
            ),
            spec,
        )
    )
    specs = DEFAULT_DELIVERABLES if deliverables is None else deliverables
    w["deliverables"] = [
        get_success_data(
            api_client.create_deliverable(
                w["scope"]["id"], deliverable_payload(**d), spec
            )
        )
        for d in specs
    ]

    if stage_index < STAGES.index("scoped"):
        return w

    w["scope"] = get_success_data(
        api_client.approve_scope_definition(w["scope"]["id"], w["partner_headers"])
    )
    w["request"] = get_success_data(
        api_client.get_project_request(w["request"]["id"], pm)
    )

    if stage_index < STAGES.index("matching"):
        return w

    w["offer"] = get_success_data(
        api_client.match_project_request(w["request"]["id"], spec)
    )

    if stage_index < STAGES.index("engaged"):
        return w

    w["engagement"] = get_success_data(
        api_client.accept_match_offer(w["offer"]["id"], w["volunteer_headers"])
    )

    if stage_index < STAGES.index("agreement_drafted"):
        return w

    w["agreement"] = get_success_data(
        api_client.create_agreement(
            w["engagement"]["id"],
            agreement_payload(
                w["engagement"]["version"],
                ip_disposition=(
                    agreement_ip_disposition
                    if agreement_ip_disposition is not None
                    else ip_disposition
                ),
                confidentiality_tier=(
                    agreement_confidentiality_tier
                    if agreement_confidentiality_tier is not None
                    else confidentiality_tier
                ),
                indemnity_cap_usd=indemnity_cap_usd,
            ),
            pm,
        )
    )

    if stage_index < STAGES.index("agreement_sent"):
        return w

    w["agreement"] = get_success_data(
        api_client.send_agreement(w["agreement"]["id"], pm)
    )

    if stage_index < STAGES.index("agreement_executed"):
        return w

    get_success_data(
        api_client.execute_agreement(w["agreement"]["id"], w["volunteer_headers"])
    )
    w["agreement"] = get_success_data(
        api_client.execute_agreement(w["agreement"]["id"], w["partner_headers"])
    )

    if stage_index < STAGES.index("in_progress"):
        return w

    w["engagement"] = get_success_data(
        api_client.start_engagement(w["engagement"]["id"], w["volunteer_headers"])
    )

    if stage_index < STAGES.index("held"):
        return w

    w["milestone"] = get_success_data(
        api_client.create_milestone(
            w["engagement"]["id"], milestone_payload(due_at=milestone_due_at), pm
        )
    )
    log_specs = time_logs if time_logs is not None else [
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
    ]
    w["time_logs"] = [
        get_success_data(
            api_client.create_time_log(
                w["engagement"]["id"], time_log_payload(**spec_row), w["volunteer_headers"]
            )
        )
        for spec_row in log_specs
    ]
    if hold_clock:
        set_clock(hold_clock, pm)
    w["milestone"] = get_success_data(
        api_client.hold_milestone(
            w["milestone"]["id"],
            {"reported_cumulative_hours": reported_cumulative_hours},
            pm,
        )
    )

    if stage_index < STAGES.index("submitted"):
        return w

    w["engagement"] = get_success_data(
        api_client.submit_engagement(w["engagement"]["id"], w["volunteer_headers"])
    )

    if stage_index < STAGES.index("accepted"):
        return w

    w["review"] = get_success_data(
        api_client.create_quality_review(w["engagement"]["id"], qr)
    )
    scores = review_scores or {d["id"]: 5 for d in w["deliverables"]}
    w["review"] = get_success_data(
        api_client.score_quality_review(
            w["review"]["id"], deliverable_scores_payload(scores), qr
        )
    )
    w["review"] = get_success_data(
        api_client.decide_quality_review(w["review"]["id"], qr, {})
    )
    w["engagement"] = get_success_data(
        api_client.get_engagement(w["engagement"]["id"], pm)
    )

    if stage_index < STAGES.index("handed_off"):
        return w

    ho = handoff_payload(handoff_artifact_count=handoff_artifact_count)
    if destruction_certificate_ref is not None:
        ho["destruction_certificate_ref"] = destruction_certificate_ref
    w["engagement"] = get_success_data(
        api_client.handoff_engagement(w["engagement"]["id"], ho, pm)
    )
    return w


# ------------------------------------------------------- convenience wrappers
def setup_roster(**kwargs) -> dict:
    """Cycle + partner + vetted volunteer with one availability window."""
    return setup_world("roster", **kwargs)


def setup_draft_request(**kwargs) -> dict:
    return setup_world("draft", **kwargs)


def setup_scoping_request(**kwargs) -> dict:
    """Request in SCOPING with one DRAFT revision and its deliverable set."""
    return setup_world("scoping", **kwargs)


def setup_scoped_request(**kwargs) -> dict:
    """Request in SCOPED with an APPROVED revision."""
    return setup_world("scoped", **kwargs)


def setup_offer(**kwargs) -> dict:
    """Request in MATCHING with one OFFERED match offer."""
    return setup_world("matching", **kwargs)


def setup_engagement(**kwargs) -> dict:
    """Accepted offer: engagement in NOT_STARTED / UNVALUED."""
    return setup_world("engaged", **kwargs)


def setup_drafted_agreement(**kwargs) -> dict:
    return setup_world("agreement_drafted", **kwargs)


def setup_sent_agreement(**kwargs) -> dict:
    return setup_world("agreement_sent", **kwargs)


def setup_executed_agreement(**kwargs) -> dict:
    return setup_world("agreement_executed", **kwargs)


def setup_in_progress_engagement(**kwargs) -> dict:
    """Engagement in IN_PROGRESS behind an EXECUTED agreement."""
    return setup_world("in_progress", **kwargs)


def setup_held_milestone_engagement(**kwargs) -> dict:
    """Engagement still IN_PROGRESS with one HELD milestone and approved logs."""
    return setup_world("held", **kwargs)


def setup_submitted_engagement(**kwargs) -> dict:
    """Engagement in SUBMITTED with one HELD milestone and approved logs."""
    return setup_world("submitted", **kwargs)


def setup_accepted_engagement(**kwargs) -> dict:
    """Engagement in ACCEPTED after a PASS review decision."""
    return setup_world("accepted", **kwargs)


def setup_handed_off_engagement(**kwargs) -> dict:
    """Engagement in HANDED_OFF with the request CLOSED."""
    return setup_world("handed_off", **kwargs)


# ---------------------------------------------------------- targeted helpers
def add_second_volunteer(
    w: dict,
    skill_code: str = "TAX_LAW",
    proficiency: int = 4,
    verify_skill: bool = True,
    window_overrides=None,
    **volunteer_overrides,
) -> dict:
    """Add another vetted volunteer with an availability window to an existing
    world. Returns a dict with volunteer, skill_profile, window and headers."""
    volunteer, skill, win = create_vetted_volunteer(
        skill_code=skill_code,
        proficiency=proficiency,
        verify_skill=verify_skill,
        window_overrides=window_overrides
        or {
            "starts_at": WINDOW_START,
            "ends_at": WINDOW_END,
            "window_kind": "HARD",
            "hours_offered": 300.00,
        },
        **volunteer_overrides,
    )
    return {
        "volunteer": volunteer,
        "skill_profile": skill,
        "window": win,
        "volunteer_headers": make_volunteer_headers(volunteer["id"]),
    }


def add_scoped_request(
    w: dict,
    *,
    skill_code: str = "TAX_LAW",
    min_proficiency: int = 3,
    urgency: str = "ROUTINE",
    estimated_hours: float = 40.00,
    complexity_factor: float = 1.00,
    confidentiality_tier: str = "STANDARD",
    ip_disposition: str = "ASSIGN_TO_PARTNER",
    deliverables=None,
    title: str = "Second engagement",
    partner=None,
    partner_headers=None,
) -> dict:
    """Add a second SCOPED request (with an APPROVED revision) to an existing
    world's partner and cycle. Returns {request, scope, deliverables}."""
    partner = partner or w["partner"]
    partner_headers = partner_headers or make_partner_contact_headers(partner["id"])
    spec = w["spec_headers"]
    request = get_success_data(
        api_client.create_project_request(
            project_request_payload(
                partner["id"],
                w["cycle"]["id"],
                title=title,
                required_skill_code=skill_code,
                min_proficiency=min_proficiency,
                urgency=urgency,
            ),
            partner_headers,
        )
    )
    request = get_success_data(
        api_client.submit_for_scoping(request["id"], partner_headers)
    )
    scope = get_success_data(
        api_client.create_scope_definition(
            request["id"],
            scope_definition_payload(
                request["version"],
                estimated_hours=estimated_hours,
                complexity_factor=complexity_factor,
                confidentiality_tier=confidentiality_tier,
                ip_disposition=ip_disposition,
            ),
            spec,
        )
    )
    dspecs = DEFAULT_DELIVERABLES if deliverables is None else deliverables
    dels = [
        get_success_data(
            api_client.create_deliverable(scope["id"], deliverable_payload(**d), spec)
        )
        for d in dspecs
    ]
    scope = get_success_data(
        api_client.approve_scope_definition(scope["id"], partner_headers)
    )
    request = get_success_data(api_client.get_project_request(request["id"], w["pm_headers"]))
    return {"request": request, "scope": scope, "deliverables": dels}


def add_draft_revision(w: dict, **overrides) -> dict:
    """Draft another scope revision on the world's request, re-reading the
    request's current version first so the stale-version guard passes."""
    request = get_success_data(
        api_client.get_project_request(w["request"]["id"], w["pm_headers"])
    )
    return get_success_data(
        api_client.create_scope_definition(
            request["id"],
            scope_definition_payload(request["version"], **overrides),
            w["spec_headers"],
        )
    )


def current_engagement_version(w: dict) -> int:
    return get_success_data(
        api_client.get_engagement(w["engagement"]["id"], w["pm_headers"])
    )["version"]


def read_engagement(w: dict) -> dict:
    return get_success_data(
        api_client.get_engagement(w["engagement"]["id"], w["pm_headers"])
    )


def read_cycle(w: dict) -> dict:
    return get_success_data(
        api_client.get_program_cycle(w["cycle"]["id"], w["pm_headers"])
    )


def read_window(w: dict, window_id=None, volunteer_id=None) -> dict:
    volunteer_id = volunteer_id or w["volunteer"]["id"]
    window_id = window_id or w["window"]["id"]
    rows, _ = _paginated(
        api_client.list_availability_windows(volunteer_id, w["pm_headers"])
    )
    for row in rows:
        if row["id"] == window_id:
            return row
    raise AssertionError(f"Setup failed: window {window_id} not found")


def read_volunteer(w: dict, volunteer_id=None) -> dict:
    return get_success_data(
        api_client.get_volunteer(
            volunteer_id or w["volunteer"]["id"], w["pm_headers"]
        )
    )


def read_partner(w: dict, partner_id=None) -> dict:
    return get_success_data(
        api_client.get_partner_org(partner_id or w["partner"]["id"], w["pm_headers"])
    )


def read_request(w: dict, request_id=None) -> dict:
    return get_success_data(
        api_client.get_project_request(
            request_id or w["request"]["id"], w["pm_headers"]
        )
    )


def read_scope(w: dict, scope_id=None) -> dict:
    return get_success_data(
        api_client.get_scope_definition(scope_id or w["scope"]["id"], w["pm_headers"])
    )


def read_agreement(w: dict, agreement_id=None) -> dict:
    rows, _ = _paginated(
        api_client.list_agreements(w["engagement"]["id"], w["pm_headers"])
    )
    target = agreement_id or w["agreement"]["id"]
    for row in rows:
        if row["id"] == target:
            return row
    raise AssertionError(f"Setup failed: agreement {target} not found")


def read_offer(w: dict, offer_id=None) -> dict:
    return get_success_data(
        api_client.get_match_offer(offer_id or w["offer"]["id"], w["pm_headers"])
    )


def read_milestone(w: dict, milestone_id=None) -> dict:
    return get_success_data(
        api_client.get_milestone(milestone_id or w["milestone"]["id"], w["pm_headers"])
    )


def read_deliverables(w: dict, scope_id=None) -> list:
    rows, _ = _paginated(
        api_client.list_deliverables(scope_id or w["scope"]["id"], w["pm_headers"])
    )
    return rows


def read_valuation_records(w: dict) -> list:
    rows, _ = _paginated(
        api_client.list_valuation_records(w["engagement"]["id"], w["pm_headers"])
    )
    return rows


def read_time_logs(w: dict) -> list:
    rows, _ = _paginated(
        api_client.list_time_logs(w["engagement"]["id"], w["pm_headers"])
    )
    return rows


def read_milestones(w: dict) -> list:
    rows, _ = _paginated(
        api_client.list_milestones(w["engagement"]["id"], w["pm_headers"])
    )
    return rows


def read_scope_changes(w: dict) -> list:
    rows, _ = _paginated(
        api_client.list_scope_change_requests(w["engagement"]["id"], w["pm_headers"])
    )
    return rows


def _paginated(response):
    """Read a list endpoint's rows without asserting envelope details (setup use)."""
    body = response.json()
    assert response.status_code < 300, (
        f"Setup failed: list call returned {response.status_code}: {body}"
    )
    return body.get("data", []), body.get("meta", {})


def post_valuation(w: dict, method: str = "INDEPENDENT_SECTOR"):
    """Post a valuation record after re-reading the engagement version."""
    version = current_engagement_version(w)
    return api_client.create_valuation(
        w["engagement"]["id"],
        {"expected_engagement_version": version, "method": method},
        w["pm_headers"],
    )


def drive_review_to_outcome(w: dict, scores: dict, reviewer_headers=None):
    """Open a review round on a SUBMITTED engagement and score it. Returns the
    SCORED review row."""
    qr = reviewer_headers or w["reviewer_headers"]
    review = get_success_data(
        api_client.create_quality_review(w["engagement"]["id"], qr)
    )
    review = get_success_data(
        api_client.score_quality_review(
            review["id"], deliverable_scores_payload(scores), qr
        )
    )
    w["review"] = review
    return review
