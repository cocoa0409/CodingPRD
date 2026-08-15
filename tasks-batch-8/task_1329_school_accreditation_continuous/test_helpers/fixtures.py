"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database and the default logical clock
(2026-08-01T00:00:00Z, PRD §2.8), so these helpers build complete precondition
chains — system -> campuses -> standards -> term -> ratings -> advance ->
finalize -> visit pipeline -> decision — out of PRD-declared endpoints only.

Identity threading: Reviewer is entity-backed, so every identity-gated
reviewer call (draft finding, issue finding, issue report, verify) uses
make_reviewer_headers(reviewer["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_action_evidence_payload,
    create_assignment_payload,
    create_campus_payload,
    create_evidence_payload,
    create_fee_schedule_payload,
    create_finding_payload,
    create_goal_payload,
    create_indicator_payload,
    create_instrument_payload,
    create_interim_report_payload,
    create_invoice_payload,
    create_payment_payload,
    create_rating_payload,
    create_reviewer_payload,
    create_standard_payload,
    create_survey_window_payload,
    create_system_payload,
    create_term_payload,
    create_visit_payload,
)
from .test_users import TEST_USERS, make_reviewer_headers

OFFICER = TEST_USERS["officer_headers"]
COMMISSION = TEST_USERS["commission_headers"]
LEADER = TEST_USERS["leader_headers"]
BURSAR = TEST_USERS["bursar_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

DEFAULT_TERM_START = TEST_DEFAULTS["TERM_START"]
DEFAULT_VISIT_STARTS = "2026-11-02T00:00:00Z"
DEFAULT_VISIT_ENDS = "2026-11-04T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitive one-call helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.8). Returns the clock readback."""
    return get_success_data(api_client.set_clock(to_iso8601, OFFICER))


def create_system(name="Test County Schools", system_type="SINGLE_SCHOOL"):
    return get_success_data(api_client.create_system(
        create_system_payload(name=name, system_type=system_type), OFFICER))


def create_campus(system_id, name="Main Campus", enrollment=300):
    return get_success_data(api_client.create_campus(
        system_id, create_campus_payload(name=name, enrollment=enrollment), OFFICER))


def create_standard(code="L1", title="Leadership 1", domain="LEADERSHIP",
                    weight_pct=100, evidence_min_items=0):
    return get_success_data(api_client.create_standard(
        create_standard_payload(code=code, title=title, domain=domain,
                                weight_pct=weight_pct,
                                evidence_min_items=evidence_min_items), OFFICER))


def create_term(system_id, term_start=DEFAULT_TERM_START, term_length_years=5):
    return get_success_data(api_client.create_term(
        system_id, create_term_payload(term_start=term_start,
                                       term_length_years=term_length_years), OFFICER))


def get_term(term_id):
    return get_success_data(api_client.get_term(term_id, OFFICER))


def create_rating(term_id, campus_id, standard_id, rating, headers=None):
    """Create a SelfStudyRating with a freshly read OCC term version (PRD §2.6)."""
    term = get_term(term_id)
    payload = create_rating_payload(
        term_id=term_id, campus_id=campus_id, standard_id=standard_id,
        rating=rating, expected_term_version=term["version"])
    return get_success_data(api_client.create_rating(payload, headers or LEADER))


def submit_rating(rating_id, headers=None):
    return get_success_data(api_client.submit_rating(rating_id, headers or LEADER))


def finalize_rating(rating_id):
    return get_success_data(api_client.finalize_rating(rating_id, OFFICER))


def submit_and_finalize(rating_id):
    submit_rating(rating_id)
    return finalize_rating(rating_id)


def create_reviewer(full_name="Rita Reviewer", email="rita@accreditor.org",
                    conflict_system_ids=None):
    payload = create_reviewer_payload(full_name=full_name, email=email)
    if conflict_system_ids is not None:
        payload["conflict_system_ids"] = conflict_system_ids
    return get_success_data(api_client.create_reviewer(payload, OFFICER))


def create_fee_schedule(**overrides):
    return get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(**overrides), OFFICER))


def create_annual_invoice(system_id, billing_year=2026):
    return get_success_data(api_client.create_invoice(
        system_id, create_invoice_payload(billing_year=billing_year,
                                          invoice_type="ANNUAL_FEE"), BURSAR))


def post_payment(invoice_id, amount_cents, paid_at="2026-08-02T00:00:00Z"):
    """Post a payment with a freshly read OCC invoice version (PRD §2.6).
    Returns the raw Response so callers can validate success or error."""
    invoice = get_success_data(api_client.get_invoice(invoice_id, BURSAR))
    payload = create_payment_payload(
        amount_cents, invoice["version"], paid_at=paid_at)
    return api_client.create_payment(invoice_id, payload, BURSAR)


def create_indicator(goal_id, measured_at="2027-01-15T00:00:00Z", value=65,
                     note=None, headers=None):
    """Post a ProgressIndicator with a freshly read OCC goal version (PRD §2.6)."""
    goal = get_success_data(api_client.get_goal(goal_id, OFFICER))
    payload = create_indicator_payload(goal["version"], measured_at=measured_at,
                                       value=value)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_indicator(goal_id, payload,
                                                        headers or LEADER))


# ---------------------------------------------------------------------------
# Tier 1/2: self-study term context (system + campuses + standards + term +
# full rating coverage, advanced to SELF_STUDY — PRD §3.2 advance gate)
# ---------------------------------------------------------------------------

def setup_self_study_term(system_name="Test County Schools",
                          system_type="SINGLE_SCHOOL",
                          campuses=None,
                          standards=None,
                          rating_values=None,
                          term_start=DEFAULT_TERM_START,
                          term_length_years=5,
                          initial_clock=DEFAULT_CLOCK,
                          advance=True):
    """Build a term ready for (or already in) SELF_STUDY.

    campuses: list of (name, enrollment); default one campus of 300.
    standards: list of (code, title, domain, weight_pct, evidence_min_items);
               default one standard L1 weight 100 min_items 0.
    rating_values: {(campus_idx, standard_idx): rating}; default 3 everywhere.
                   The full campus x standard coverage matrix is always created,
                   which the PREPARATION -> SELF_STUDY advance requires.

    Returns a context dict: system, campuses, standards, term, ratings.
    """
    if initial_clock:
        set_clock(initial_clock)
    standards = standards if standards is not None else [
        ("L1", "Leadership 1", "LEADERSHIP", 100, 0)]
    campuses = campuses if campuses is not None else [("Main Campus", 300)]

    system = create_system(name=system_name, system_type=system_type)
    campus_objs = [create_campus(system["id"], name=n, enrollment=e)
                   for n, e in campuses]
    standard_objs = [create_standard(code=c, title=t, domain=d, weight_pct=w,
                                     evidence_min_items=m)
                     for c, t, d, w, m in standards]
    term = create_term(system["id"], term_start=term_start,
                       term_length_years=term_length_years)

    ratings = {}
    for ci, campus in enumerate(campus_objs):
        for si, standard in enumerate(standard_objs):
            value = (rating_values or {}).get((ci, si), 3)
            ratings[(ci, si)] = create_rating(term["id"], campus["id"],
                                              standard["id"], value)

    if advance:
        term = get_success_data(api_client.advance_term(term["id"], OFFICER))

    return {
        "system": system,
        "campuses": campus_objs,
        "standards": standard_objs,
        "term": term,
        "ratings": ratings,
    }


def finalize_all_ratings(ctx):
    """Submit + finalize every rating in the context (PRD §3.3)."""
    for key in sorted(ctx["ratings"].keys()):
        submit_and_finalize(ctx["ratings"][key]["id"])
    return ctx


def walk_term_to_review(ctx):
    """SELF_STUDY -> REVIEW: finalize every rating, then advance (PRD §3.2)."""
    finalize_all_ratings(ctx)
    ctx["term"] = get_success_data(api_client.advance_term(ctx["term"]["id"], OFFICER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: visit pipeline (PRD §3.6)
# ---------------------------------------------------------------------------

def add_reported_visit(ctx, starts_on=DEFAULT_VISIT_STARTS,
                       ends_on=DEFAULT_VISIT_ENDS, severity="COMMENDATION",
                       follow_up_months=None, narrative="Strong governance.",
                       campus_idx=0, reviewer_name="Rita Reviewer",
                       reviewer_email="rita@accreditor.org", standard_idx=0):
    """While the term is in REVIEW: register a reviewer, request a visit, assign
    the reviewer as CHAIR, confirm, drive the clock through starts_on/ends_on so
    the visit reaches REPORT_DRAFT, then draft + issue a finding and issue the
    visit report as the lead reviewer. Returns (visit, reviewer, finding)."""
    reviewer = create_reviewer(full_name=reviewer_name, email=reviewer_email)
    reviewer_headers = make_reviewer_headers(reviewer["id"])
    visit_payload = create_visit_payload(
        reviewer["id"],
        campus_id=ctx["campuses"][campus_idx]["id"],
        starts_on=starts_on, ends_on=ends_on)
    visit = get_success_data(api_client.create_visit(
        ctx["term"]["id"], visit_payload, OFFICER))
    get_success_data(api_client.create_visit_assignment(
        visit["id"], create_assignment_payload(reviewer["id"], role_on_team="CHAIR"),
        OFFICER))
    get_success_data(api_client.confirm_visit(visit["id"], OFFICER))
    # Clock-driven: CONFIRMED -> IN_FIELD at starts_on, then -> REPORT_DRAFT at ends_on.
    set_clock(starts_on)
    set_clock(ends_on)
    finding_payload = create_finding_payload(
        ctx["standards"][standard_idx]["id"], severity=severity, narrative=narrative)
    if follow_up_months is not None:
        finding_payload["follow_up_months"] = follow_up_months
    finding = get_success_data(api_client.create_finding(
        visit["id"], finding_payload, reviewer_headers))
    get_success_data(api_client.issue_finding(finding["id"], reviewer_headers))
    visit = get_success_data(api_client.issue_visit_report(visit["id"], reviewer_headers))
    ctx["visit"] = visit
    ctx["reviewer"] = reviewer
    ctx["finding"] = finding
    return visit, reviewer, finding


def walk_term_to_term_active(ctx, outcome="ACCREDITED", **visit_kwargs):
    """Full pipeline: finalize ratings, advance to REVIEW, run a reported visit,
    advance to DECISION, and post the commission decision (PRD §3.2)."""
    walk_term_to_review(ctx)
    add_reported_visit(ctx, **visit_kwargs)
    ctx["term"] = get_success_data(api_client.advance_term(ctx["term"]["id"], OFFICER))
    ctx["term"] = get_success_data(api_client.decide_term(
        ctx["term"]["id"], {"outcome": outcome}, COMMISSION))
    ctx["system"] = get_success_data(api_client.get_system(ctx["system"]["id"], OFFICER))
    return ctx


def setup_term_active(system_name="Goal County Schools", outcome="ACCREDITED",
                      **kwargs):
    """Complete context with the term in TERM_ACTIVE (decision rendered)."""
    ctx = setup_self_study_term(system_name=system_name, **kwargs)
    walk_term_to_term_active(ctx, outcome=outcome)
    return ctx


def get_action_items_for_finding(finding_id):
    data = get_success_data(api_client.list_finding_action_items(finding_id, OFFICER))
    assert isinstance(data, list) and len(data) >= 1, \
        "expected at least one action item created from the finding"
    return data


def setup_open_action_item(term_start="2025-09-01T00:00:00Z",
                           starts_on="2026-08-29T00:00:00Z",
                           ends_on="2026-08-31T00:00:00Z",
                           follow_up_months=6,
                           narrative="Adopt a formal policy review cycle."):
    """Full pipeline ending in TERM_ACTIVE (ACCREDITED_WITH_STIPULATIONS) with
    one OPEN RequiredActionItem created from a REQUIRED_ACTION finding.
    Returns (ctx, action_item)."""
    ctx = setup_self_study_term(system_name="Action Item Schools",
                                term_start=term_start)
    walk_term_to_term_active(
        ctx, outcome="ACCREDITED_WITH_STIPULATIONS",
        starts_on=starts_on, ends_on=ends_on, severity="REQUIRED_ACTION",
        follow_up_months=follow_up_months, narrative=narrative)
    items = get_action_items_for_finding(ctx["finding"]["id"])
    return ctx, items[0]


# ---------------------------------------------------------------------------
# Tier 3: survey windows (PRD §3.4)
# ---------------------------------------------------------------------------

def setup_open_survey_window(min_participation_pct=50, eligible_count=4,
                             stakeholder_group="STAFF", title="Staff Survey",
                             opens_at="2026-10-01T00:00:00Z",
                             closes_at="2026-11-01T00:00:00Z",
                             clock_inside="2026-10-15T00:00:00Z"):
    """Term in SELF_STUDY plus a survey window; the clock is moved inside the
    window so it stands OPEN. Returns (ctx, instrument, window)."""
    ctx = setup_self_study_term(system_name="Survey County",
                                system_type="DISTRICT",
                                campuses=[("North Campus", 500)])
    instrument = get_success_data(api_client.create_survey_instrument(
        create_instrument_payload(stakeholder_group=stakeholder_group, title=title,
                                  min_participation_pct=min_participation_pct),
        OFFICER))
    window = get_success_data(api_client.create_survey_window(
        ctx["term"]["id"],
        create_survey_window_payload(ctx["campuses"][0]["id"], instrument["id"],
                                     opens_at=opens_at, closes_at=closes_at,
                                     eligible_count=eligible_count),
        OFFICER))
    if clock_inside:
        set_clock(clock_inside)
    return ctx, instrument, window


def submit_responses(window_id, tokens):
    """Submit anonymous survey responses for each token (PRD §3.4)."""
    for token in tokens:
        get_success_data(api_client.submit_survey_response(
            window_id, {"respondent_token": token}, ANONYMOUS))


# ---------------------------------------------------------------------------
# Tier 3/5: improvement goals and interim reports (PRD §3.5, §3.7)
# ---------------------------------------------------------------------------

def create_goal_under_term(term_id, standard_id, campus_id=None, title="Raise proficiency",
                           baseline_value=50, target_value=80, direction="INCREASE"):
    payload = create_goal_payload(standard_id, title=title,
                                  baseline_value=baseline_value,
                                  target_value=target_value, direction=direction)
    if campus_id is not None:
        payload["campus_id"] = campus_id
    return get_success_data(api_client.create_goal(term_id, payload, LEADER))


def setup_adopted_goal(baseline_value=50, target_value=80, direction="INCREASE"):
    """Term in TERM_ACTIVE with one goal already ADOPTED. Returns (ctx, goal)."""
    ctx = setup_self_study_term(system_name="Goal County Schools")
    goal = create_goal_under_term(ctx["term"]["id"], ctx["standards"][0]["id"],
                                  campus_id=ctx["campuses"][0]["id"],
                                  baseline_value=baseline_value,
                                  target_value=target_value, direction=direction)
    walk_term_to_term_active(ctx)
    goal = get_success_data(api_client.adopt_goal(goal["id"], OFFICER))
    return ctx, goal


def setup_accepted_interim_report(report_year=1, narrative="Year one progress."):
    """Term walked TERM_ACTIVE -> INTERIM_MONITORING via one ACCEPTED report.
    Returns (ctx, report)."""
    ctx = setup_term_active(system_name="Monitoring County Schools")
    report = get_success_data(api_client.create_interim_report(
        ctx["term"]["id"],
        create_interim_report_payload(report_year=report_year, narrative=narrative),
        LEADER))
    get_success_data(api_client.submit_interim_report(report["id"], LEADER))
    report = get_success_data(api_client.accept_interim_report(report["id"], OFFICER))
    ctx["term"] = get_success_data(api_client.advance_term(ctx["term"]["id"], OFFICER))
    return ctx, report
