"""Composite setup helpers.

Every helper replays from an empty database using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup step failed" errors instead of confusing assertion failures.

Identity threading: ownership-gated calls (award accept/decline, letter
submit, report acknowledge, student-scoped application creates/submits) are
always made with make_student_headers / make_donor_headers built from the
real entity id, never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ADMIN_USER_ID,
    COORDINATOR_USER_ID,
    FAO_USER_ID,
)
from .factories import (
    create_application_payload,
    create_award_payload,
    create_cycle_payload,
    create_donor_payload,
    create_fund_payload,
    create_program_payload,
    create_renewal_payload,
    create_report_payload,
    create_score_payload,
    create_student_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_coordinator_headers,
    make_fao_headers,
    make_reviewer_headers,
    make_student_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: logical clock and ops run
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin). Returns the echoed reading."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers(ADMIN_USER_ID))
    return get_success_data(resp)


def run_daily():
    """Run the daily operations checkpoint. Returns the four counters."""
    resp = api_client.run_daily(make_admin_headers(ADMIN_USER_ID))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and reads
# ---------------------------------------------------------------------------

def create_student(**overrides):
    resp = api_client.create_student(create_student_payload(**overrides), COORD)
    return get_success_data(resp)


def create_donor(**overrides):
    resp = api_client.create_donor(create_donor_payload(**overrides), COORD)
    return get_success_data(resp)


def create_fund(**overrides):
    resp = api_client.create_fund(create_fund_payload(**overrides), COORD)
    return get_success_data(resp)


def get_fund(fund_id):
    return get_success_data(api_client.get_fund(fund_id, COORD))


def create_program(donor_id, fund_id, **overrides):
    resp = api_client.create_program(
        create_program_payload(donor_id, fund_id, **overrides), COORD
    )
    return get_success_data(resp)


def publish_program(program_id):
    return get_success_data(api_client.publish_program(program_id, COORD))


def create_open_program(donor_id, fund_id, **overrides):
    """Create a program and publish it (window opens at the default clock)."""
    program = create_program(donor_id, fund_id, **overrides)
    return publish_program(program["id"])


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, COORD))


def create_draft_application(student_id, program_id, as_student=False):
    """Create a DRAFT application. as_student=True exercises the student
    pathway with entity-backed ownership headers."""
    headers = make_student_headers(student_id) if as_student else COORD
    resp = api_client.create_application(
        create_application_payload(student_id, program_id), headers
    )
    return get_success_data(resp)


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, COORD))


def submit_application(application_id, student_id=None):
    """Submit as coordinator, or as the owning student when student_id given."""
    headers = make_student_headers(student_id) if student_id else COORD
    return get_success_data(api_client.submit_application(application_id, headers))


def list_applications(params=None):
    data, meta = validate_paginated(api_client.list_applications(COORD, params=params))
    return data, meta


def list_reminders(application_id, params=None):
    data, meta = validate_paginated(
        api_client.list_reminders(application_id, COORD, params=params)
    )
    return data, meta


def create_cycle(program_id, **overrides):
    resp = api_client.create_cycle(create_cycle_payload(program_id, **overrides), COORD)
    return get_success_data(resp)


def get_cycle(cycle_id):
    return get_success_data(api_client.get_cycle(cycle_id, COORD))


def submit_score_for(cycle_id, application_id, reviewer_id="rev_1",
                     academic=90, essay=90, need=90, conflict_of_interest=False):
    """Create + submit a score as one reviewer. Returns the SUBMITTED score."""
    headers = make_reviewer_headers(reviewer_id)
    payload = create_score_payload(
        cycle_id,
        application_id,
        academic_score=academic,
        essay_score=essay,
        need_score=need,
        conflict_of_interest=conflict_of_interest,
    )
    score = get_success_data(api_client.create_score(payload, headers))
    return get_success_data(api_client.submit_score(score["id"], headers))


def list_scores(params=None):
    data, meta = validate_paginated(api_client.list_scores(COORD, params=params))
    return data, meta


def get_award(award_id):
    return get_success_data(api_client.get_award(award_id, COORD))


def list_awards(params=None):
    data, meta = validate_paginated(api_client.list_awards(COORD, params=params))
    return data, meta


def create_offered_award(application_id, student_id, amount_cents):
    resp = api_client.create_award(
        create_award_payload(application_id, student_id, amount_cents=amount_cents),
        COORD,
    )
    return get_success_data(resp)


def accept_award(award_id, student_id):
    return get_success_data(
        api_client.accept_award(award_id, make_student_headers(student_id))
    )


def list_adjustments(params=None):
    data, meta = validate_paginated(api_client.list_adjustments(COORD, params=params))
    return data, meta


def list_disbursements(params=None):
    data, meta = validate_paginated(api_client.list_disbursements(COORD, params=params))
    return data, meta


def send_and_confirm(disbursement_id, sender_id=COORDINATOR_USER_ID,
                     confirmer_id=FAO_USER_ID):
    """Send as the coordinator and confirm as a DIFFERENT officer."""
    get_success_data(
        api_client.send_disbursement(
            disbursement_id, make_coordinator_headers(sender_id)
        )
    )
    return get_success_data(
        api_client.confirm_disbursement(
            disbursement_id, make_fao_headers(confirmer_id)
        )
    )


def list_letters(params=None):
    data, meta = validate_paginated(api_client.list_letters(COORD, params=params))
    return data, meta


def get_letter_for_award(award_id):
    """Return the award's single thank-you letter."""
    data, meta = list_letters({"award_id": award_id})
    assert meta["total_count"] >= 1, f"no thank-you letter found for award {award_id}"
    return data[0]


def create_report(donor_id, **overrides):
    resp = api_client.create_report(create_report_payload(donor_id, **overrides), COORD)
    return get_success_data(resp)


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, COORD))


# ---------------------------------------------------------------------------
# Tier 2: committee flow — one application driven to a finalize outcome
# ---------------------------------------------------------------------------

def drive_to_selected(student_id, program_id, cycle_overrides=None, scores=None):
    """Create + submit one application, then run a full committee cycle on it:
    cycle -> open-scoring -> score(s) submitted -> open-deliberation ->
    finalize. With the default single 90/90/90 score and selection_quota 1
    the application lands SELECTED.

    scores: list of dicts with keys reviewer_id/academic/essay/need.
    Returns {"application": <refreshed>, "cycle": <cycle>}.
    """
    application = create_draft_application(student_id, program_id)
    submit_application(application["id"])
    cycle = create_cycle(program_id, **(cycle_overrides or {}))
    get_success_data(api_client.open_scoring(cycle["id"], COORD))
    for spec in (scores or [{"reviewer_id": "rev_1"}]):
        submit_score_for(
            cycle["id"],
            application["id"],
            reviewer_id=spec.get("reviewer_id", "rev_1"),
            academic=spec.get("academic", 90),
            essay=spec.get("essay", 90),
            need=spec.get("need", 90),
        )
    get_success_data(api_client.open_deliberation(cycle["id"], COORD))
    get_success_data(api_client.finalize_cycle(cycle["id"], COORD))
    return {"application": get_application(application["id"]), "cycle": cycle}


# ---------------------------------------------------------------------------
# Tier 3: full-pipeline fixtures
# ---------------------------------------------------------------------------

def setup_finalized_cycle(student_specs=None, student_overrides=None,
                          program_overrides=None,
                          cycle_overrides=None, score_specs=None,
                          fund_overrides=None, donor_overrides=None):
    """N students each apply to one OPEN program; all submit; one cycle
    scores them; deliberation locks; finalize ranks.

    student_specs: list of per-student payload overrides (default: one).
    student_overrides: single-student shorthand — a dict applied as the one
    student's payload overrides when student_specs is not given.
    score_specs: list of dicts {app_index, reviewer_id, academic, essay,
    need} (default: one 90/90/90 score per application by rev_1).
    Returns ctx: students, applications, program, fund, donor, cycle, scores.
    """
    if student_specs is None:
        student_specs = [dict(student_overrides or {})]
    donor = create_donor(**(donor_overrides or {}))
    fund = create_fund(**(fund_overrides or {}))
    program = create_open_program(donor["id"], fund["id"], **(program_overrides or {}))

    students, applications = [], []
    for spec in student_specs:
        student = create_student(**spec)
        students.append(student)
        app = create_draft_application(student["id"], program["id"])
        submit_application(app["id"])
        applications.append(app)

    cycle = create_cycle(program["id"], **(cycle_overrides or {}))
    get_success_data(api_client.open_scoring(cycle["id"], COORD))

    if score_specs is None:
        score_specs = [
            {"app_index": i, "reviewer_id": "rev_1"}
            for i in range(len(applications))
        ]
    scores = []
    for spec in score_specs:
        scores.append(submit_score_for(
            cycle["id"],
            applications[spec["app_index"]]["id"],
            reviewer_id=spec.get("reviewer_id", "rev_1"),
            academic=spec.get("academic", 90),
            essay=spec.get("essay", 90),
            need=spec.get("need", 90),
        ))

    get_success_data(api_client.open_deliberation(cycle["id"], COORD))
    get_success_data(api_client.finalize_cycle(cycle["id"], COORD))

    return {
        "students": students,
        "applications": [get_application(a["id"]) for a in applications],
        "program": program,
        "fund": fund,
        "donor": donor,
        "cycle": get_cycle(cycle["id"]),
        "scores": scores,
    }


def setup_offered_award(amount_cents=500000, **flow_kwargs):
    """Finalized single-application cycle + an OFFERED award on it.

    PRD §3.6 caps an offer at the program's award_amount_cents, so when the
    caller does not set the cap explicitly the program is built with a cap
    that covers the requested award amount.
    """
    program_overrides = dict(flow_kwargs.pop("program_overrides", None) or {})
    program_overrides.setdefault("award_amount_cents", max(500000, amount_cents))
    flow_kwargs["program_overrides"] = program_overrides
    ctx = setup_finalized_cycle(**flow_kwargs)
    award = create_offered_award(
        ctx["applications"][0]["id"], ctx["students"][0]["id"], amount_cents
    )
    ctx["award"] = award
    return ctx


def setup_accepted_award(amount_cents=500000, term_count=None, **flow_kwargs):
    """Offered award accepted by the student; optionally a split plan is
    generated (disbursements key, ordered by term_seq)."""
    ctx = setup_offered_award(amount_cents=amount_cents, **flow_kwargs)
    ctx["award"] = accept_award(ctx["award"]["id"], ctx["students"][0]["id"])
    if term_count is not None:
        data = get_success_data(api_client.schedule_split(
            ctx["award"]["id"], {"term_count": term_count}, COORD
        ))
        ctx["disbursements"] = sorted(data, key=lambda d: d["term_seq"])
    return ctx


def setup_fully_disbursed_award(amount_cents=500000, term_count=1,
                                sender_id=COORDINATOR_USER_ID,
                                confirmer_id=FAO_USER_ID, **flow_kwargs):
    """Accepted award with the whole split confirmed -> FULLY_DISBURSED.

    Each term's send is date-gated, so the clock is advanced to the term's
    scheduled_date before sending terms after the first.
    """
    ctx = setup_accepted_award(
        amount_cents=amount_cents, term_count=term_count, **flow_kwargs
    )
    for disb in ctx["disbursements"]:
        set_clock(f"{disb['scheduled_date']}T00:00:00Z")
        send_and_confirm(disb["id"], sender_id=sender_id, confirmer_id=confirmer_id)
    ctx["award"] = get_award(ctx["award"]["id"])
    return ctx


def setup_pending_renewal(program_overrides=None, eval_overrides=None,
                          **flow_kwargs):
    """FULLY_DISBURSED award on a renewable program + one PENDING evaluation."""
    renewable = {
        "renewable": True,
        "renewal_min_gpa_hundredths": 250,
        "renewal_min_credits": 12,
        "max_renewals": 2,
    }
    renewable.update(program_overrides or {})
    ctx = setup_fully_disbursed_award(program_overrides=renewable, **flow_kwargs)
    evaluation = get_success_data(api_client.create_renewal_evaluation(
        create_renewal_payload(ctx["award"]["id"], **(eval_overrides or {})),
        COORD,
    ))
    ctx["evaluation"] = evaluation
    return ctx
