"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, using the lenient `get_success_data` validator so that a
broken precondition surfaces as a setup failure rather than as a confusing
assertion failure inside a test.

The logical clock reads 2026-08-01T00:00:00Z at startup (PRD §2.5), and the
database is empty at the start of every test, so helpers never assume any
pre-existing row.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_addendum_payload,
    create_employee_payload,
    create_jurisdiction_payload,
    create_legal_review_payload,
    create_legal_reviewer_payload,
    create_policy_document_payload,
    create_policy_version_payload,
    create_release_package_payload,
    create_translation_payload,
)
from .test_users import (
    make_admin_headers,
    make_author_headers,
    make_counsel_headers,
    make_employee_headers,
    make_localizer_headers,
    make_manager_headers,
)

CLOCK_START = "2026-08-01T00:00:00Z"

ADMIN = make_admin_headers()
AUTHOR = make_author_headers()
LOCALIZER = make_localizer_headers()


def _api():
    return api_client


# --- Tier 0: single-row creators -----------------------------------------


def new_jurisdiction(**overrides) -> dict:
    """Register one jurisdiction as HRComplianceAdmin."""
    return get_success_data(
        _api().create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN)
    )


def new_reviewer(jurisdiction_id, **overrides) -> dict:
    """Register one jurisdiction-licensed reviewer (default capacity 3)."""
    overrides.setdefault("concurrent_review_limit", 3)
    return get_success_data(
        _api().create_legal_reviewer(
            create_legal_reviewer_payload(jurisdiction_id, **overrides), ADMIN
        )
    )


def new_employee(jurisdiction_id, **overrides) -> dict:
    """Create one employee record."""
    return get_success_data(
        _api().create_employee(
            create_employee_payload(jurisdiction_id, **overrides), ADMIN
        )
    )


def new_document(**overrides) -> dict:
    """Create one policy document as PolicyAuthor."""
    return get_success_data(
        _api().create_policy_document(create_policy_document_payload(**overrides), AUTHOR)
    )


def mint_version(document, required_jurisdiction_ids, **overrides) -> dict:
    """Mint the next version of `document`, reading its current `version` as
    the expected-version token."""
    doc = get_success_data(_api().get_policy_document(document["id"], ADMIN))
    payload = create_policy_version_payload(
        required_jurisdiction_ids, doc["version"], **overrides
    )
    return get_success_data(
        _api().create_policy_version(document["id"], payload, AUTHOR)
    )


def add_addendum(policy_version_id, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        _api().create_addendum(
            policy_version_id,
            create_addendum_payload(jurisdiction_id, **overrides),
            AUTHOR,
        )
    )


def approve_addendum(addendum_id, reviewer_id) -> dict:
    return get_success_data(
        _api().approve_addendum(addendum_id, make_counsel_headers(reviewer_id))
    )


def request_review(
    policy_version_id, jurisdiction_id, reviewer_id, due_at="2026-08-20T00:00:00Z"
) -> dict:
    return get_success_data(
        _api().create_legal_review(
            policy_version_id,
            create_legal_review_payload(jurisdiction_id, reviewer_id, due_at),
            AUTHOR,
        )
    )


def set_clock(to_iso8601) -> dict:
    return get_success_data(_api().set_clock(to_iso8601, ADMIN))


def sweep() -> dict:
    return get_success_data(_api().escalation_sweep(ADMIN))


# --- Tier 1: state progression -------------------------------------------


def drive_version_to_in_legal_review(version, jurisdiction_reviewers, due_at="2026-08-20T00:00:00Z"):
    """Attach one addendum and one legal review per required jurisdiction,
    approve every addendum, then submit the version into legal review.

    `jurisdiction_reviewers` is a list of (jurisdiction_id, reviewer_id) pairs
    covering exactly the version's required_jurisdiction_ids.
    Returns (version, addenda_by_jurisdiction, reviews_by_jurisdiction).
    """
    addenda = {}
    reviews = {}
    for jurisdiction_id, reviewer_id in jurisdiction_reviewers:
        addendum = add_addendum(version["id"], jurisdiction_id)
        addenda[jurisdiction_id] = approve_addendum(addendum["id"], reviewer_id)
        reviews[jurisdiction_id] = request_review(
            version["id"], jurisdiction_id, reviewer_id, due_at
        )
    version = get_success_data(
        _api().submit_version_for_review(version["id"], AUTHOR)
    )
    return version, addenda, reviews


def approve_all_reviews(reviews, jurisdiction_reviewers):
    """Start and APPROVE every review, as its own assigned reviewer."""
    reviewer_of = dict(jurisdiction_reviewers)
    out = {}
    for jurisdiction_id, review in reviews.items():
        headers = make_counsel_headers(reviewer_of[jurisdiction_id])
        get_success_data(_api().start_legal_review(review["id"], headers))
        out[jurisdiction_id] = get_success_data(
            _api().decide_legal_review(review["id"], {"verdict": "APPROVE"}, headers)
        )
    return out


def drive_version_to_approved(version, jurisdiction_reviewers, due_at="2026-08-20T00:00:00Z"):
    """DRAFT -> IN_LEGAL_REVIEW -> APPROVED. Returns (version, addenda, reviews)."""
    version, addenda, reviews = drive_version_to_in_legal_review(
        version, jurisdiction_reviewers, due_at
    )
    reviews = approve_all_reviews(reviews, jurisdiction_reviewers)
    version = get_success_data(_api().approve_policy_version(version["id"], ADMIN))
    return version, addenda, reviews


def publish_translation(policy_version_id, language_code="en", section_scores=None) -> dict:
    """Open a localization track, submit accessibility scores and publish it.

    The default scores put a11y_index at 96.00, which clears both the AA
    publication gate and the accessible-employee delivery floor.
    """
    version = get_success_data(_api().get_policy_version(policy_version_id, ADMIN))
    if section_scores is None:
        section_scores = [0.96] * version["section_count"]
    track = get_success_data(
        _api().create_translation(
            policy_version_id, create_translation_payload(language_code), LOCALIZER
        )
    )
    get_success_data(_api().start_translation(track["id"], LOCALIZER))
    get_success_data(
        _api().submit_a11y(track["id"], {"section_scores": section_scores}, LOCALIZER)
    )
    return get_success_data(_api().publish_translation(track["id"], LOCALIZER))


def track_at_a11y_review(policy_version_id, language_code="en", section_scores=None) -> dict:
    """Open a localization track and park it at A11Y_REVIEW (not published)."""
    version = get_success_data(_api().get_policy_version(policy_version_id, ADMIN))
    if section_scores is None:
        section_scores = [0.96] * version["section_count"]
    track = get_success_data(
        _api().create_translation(
            policy_version_id, create_translation_payload(language_code), LOCALIZER
        )
    )
    get_success_data(_api().start_translation(track["id"], LOCALIZER))
    return get_success_data(
        _api().submit_a11y(track["id"], {"section_scores": section_scores}, LOCALIZER)
    )


def new_package(scope_jurisdiction_ids, effective_date, **overrides) -> dict:
    return get_success_data(
        _api().create_release_package(
            create_release_package_payload(
                scope_jurisdiction_ids, effective_date, **overrides
            ),
            ADMIN,
        )
    )


def add_item(release_package_id, policy_version_id) -> dict:
    return get_success_data(
        _api().add_release_item(
            release_package_id, {"policy_version_id": policy_version_id}, ADMIN
        )
    )


def schedule_package(release_package_id) -> dict:
    return get_success_data(_api().schedule_release_package(release_package_id, ADMIN))


def release_package(release_package_id) -> dict:
    """Release using a freshly read expected_release_package_version token."""
    pkg = get_success_data(_api().get_release_package(release_package_id, ADMIN))
    return get_success_data(
        _api().release_release_package(
            release_package_id,
            {"expected_release_package_version": pkg["version"]},
            ADMIN,
        )
    )


# --- Tier 2: entity hierarchy --------------------------------------------


def setup_approved_version(
    jurisdiction=None,
    document=None,
    version=None,
    due_at="2026-08-20T00:00:00Z",
    publish_translation_track=True,
    section_scores=None,
    language_code="en",
):
    """One jurisdiction + one reviewer + one document + one APPROVED version,
    optionally with a PUBLISHED localization track in `language_code`.

    Returns a dict with keys: jurisdiction, reviewer, document, version,
    addenda, reviews, translation.
    """
    j = new_jurisdiction(**(jurisdiction or {}))
    r = new_reviewer(j["id"])
    d = new_document(**(document or {}))
    v = mint_version(d, [j["id"]], **(version or {}))
    v, addenda, reviews = drive_version_to_approved(v, [(j["id"], r["id"])], due_at)
    track = None
    if publish_translation_track:
        track = publish_translation(v["id"], language_code, section_scores)
    return {
        "jurisdiction": j,
        "reviewer": r,
        "document": d,
        "version": v,
        "addenda": addenda,
        "reviews": reviews,
        "translation": track,
    }


def add_approved_version_to_document(
    document, jurisdiction_id, reviewer_id, version=None,
    due_at="2026-09-30T00:00:00Z", publish_translation_track=True,
    section_scores=None, language_code="en",
):
    """Mint a successor version on an existing document and drive it to
    APPROVED (plus a PUBLISHED rendition).  Returns the version row."""
    v = mint_version(document, [jurisdiction_id], **(version or {}))
    v, _addenda, _reviews = drive_version_to_approved(
        v, [(jurisdiction_id, reviewer_id)], due_at
    )
    if publish_translation_track:
        publish_translation(v["id"], language_code, section_scores)
    return v


def released_package_for(
    version_ids, scope_jurisdiction_ids, effective_date, clock_to=None, name=None
):
    """Create -> item(s) -> schedule -> advance clock -> release."""
    overrides = {"name": name} if name else {}
    pkg = new_package(scope_jurisdiction_ids, effective_date, **overrides)
    for version_id in version_ids:
        add_item(pkg["id"], version_id)
    schedule_package(pkg["id"])
    set_clock(clock_to or effective_date)
    return release_package(pkg["id"])


def assignments_of(release_package_id=None, employee_id=None, **extra):
    params = {"limit": 100}
    if release_package_id:
        params["release_package_id"] = release_package_id
    if employee_id:
        params["employee_id"] = employee_id
    params.update(extra)
    return get_success_data(_api().list_assignments(ADMIN, params=params))


def sole_assignment(release_package_id, employee_id):
    rows = assignments_of(release_package_id, employee_id)
    assert len(rows) == 1, (
        f"Setup failed: expected exactly 1 assignment for employee {employee_id} "
        f"in package {release_package_id}, got {len(rows)}"
    )
    return rows[0]


# --- Tier 3: full lifecycle shortcuts ------------------------------------


def setup_released_scenario(
    jurisdiction=None,
    document=None,
    version=None,
    employee=None,
    with_manager=False,
    extra_employees=0,
    effective_date="2026-08-15T00:00:00Z",
    deliver=True,
    section_scores=None,
    language_code="en",
    package_name=None,
):
    """The canonical end-to-end preamble.

    Jurisdiction -> reviewer -> (optional manager) employee (+ extras) ->
    document -> APPROVED version -> PUBLISHED rendition -> package with one
    item -> schedule -> advance clock to `effective_date` -> release, then
    optionally deliver the subject employee's assignment.

    Returns a dict with keys: jurisdiction, reviewer, document, version,
    translation, manager, employee, extras, package, assignment.
    """
    base = setup_approved_version(
        jurisdiction=jurisdiction,
        document=document,
        version=version,
        publish_translation_track=True,
        section_scores=section_scores,
        language_code=language_code,
    )
    j = base["jurisdiction"]

    manager = new_employee(j["id"]) if with_manager else None
    emp_overrides = dict(employee or {})
    if manager is not None:
        emp_overrides.setdefault("manager_id", manager["id"])
    subject = new_employee(j["id"], **emp_overrides)
    extras = [new_employee(j["id"]) for _ in range(extra_employees)]

    pkg = released_package_for(
        [base["version"]["id"]], [j["id"]], effective_date, name=package_name
    )
    base["version"] = get_success_data(
        _api().get_policy_version(base["version"]["id"], ADMIN)
    )

    assignment = None
    if subject["employment_status"] != "TERMINATED":
        assignment = sole_assignment(pkg["id"], subject["id"])
        if deliver:
            assignment = get_success_data(
                _api().deliver_assignment(assignment["id"], ADMIN)
            )

    base.update(
        {
            "manager": manager,
            "employee": subject,
            "extras": extras,
            "package": pkg,
            "assignment": assignment,
        }
    )
    return base


def acknowledge(assignment, employee_id, method="ESIGN", language_code="en",
                signature_text="Typed Full Name"):
    """Record an acknowledgment as the assignment's own assignee."""
    return get_success_data(
        _api().create_acknowledgment(
            {
                "assignment_id": assignment["id"],
                "method": method,
                "language_code": language_code,
                "signature_text": signature_text,
            },
            make_employee_headers(employee_id),
        )
    )


def setup_open_escalation_case(clock_to="2026-09-03T00:00:00Z", **scenario_kwargs):
    """A delivered, unacknowledged assignment driven overdue, then swept so an
    escalation case is OPEN.  Returns the scenario dict plus `case`."""
    scenario_kwargs.setdefault("with_manager", True)
    scenario = setup_released_scenario(**scenario_kwargs)
    set_clock(clock_to)
    sweep()
    cases = get_success_data(
        _api().list_escalations(
            ADMIN,
            params={"assignment_id": scenario["assignment"]["id"], "limit": 100},
        )
    )
    assert len(cases) == 1, (
        f"Setup failed: expected exactly 1 escalation case, got {len(cases)}"
    )
    scenario["case"] = cases[0]
    return scenario


def setup_escalated_hr_case(clock_to="2026-09-03T00:00:00Z", **scenario_kwargs):
    """Drive an escalation case OPEN -> NOTIFIED -> ESCALATED_HR (tier 3)."""
    scenario = setup_open_escalation_case(clock_to=clock_to, **scenario_kwargs)
    case_id = scenario["case"]["id"]
    get_success_data(_api().notify_escalation(case_id, ADMIN))
    scenario["case"] = get_success_data(_api().escalate_hr(case_id, ADMIN))
    return scenario


# --- Tier 4: exception lifecycle -----------------------------------------


def create_exception(policy_version_id, employee_id, **overrides):
    """File a policy exception, reading the employee's current `version` as the
    expected-version token."""
    from .factories import create_policy_exception_payload

    employee = get_success_data(_api().get_employee(employee_id, ADMIN))
    payload = create_policy_exception_payload(
        policy_version_id, employee["version"], **overrides
    )
    return get_success_data(
        _api().create_policy_exception(payload, make_employee_headers(employee_id))
    )


def setup_submitted_exception(
    reason_code="MEDICAL",
    requested_days=90,
    justification="Recovering from surgery; cannot complete e-sign flow yet.",
    second_reviewer=True,
    **scenario_kwargs,
):
    """A delivered PENDING assignment whose assignee has filed an exception.

    A second, untouched reviewer in the same jurisdiction is registered so the
    legal stage can be satisfied without a reviewer conflict.
    Returns the scenario dict plus `exception` and `reviewer_2`.
    """
    scenario_kwargs.setdefault("with_manager", True)
    scenario = setup_released_scenario(**scenario_kwargs)
    scenario["reviewer_2"] = (
        new_reviewer(scenario["jurisdiction"]["id"]) if second_reviewer else None
    )
    scenario["exception"] = create_exception(
        scenario["version"]["id"],
        scenario["employee"]["id"],
        reason_code=reason_code,
        requested_days=requested_days,
        justification=justification,
    )
    return scenario


def setup_manager_approved_exception(**kwargs):
    """Carry a submitted exception through its first-stage manager approval."""
    scenario = setup_submitted_exception(**kwargs)
    scenario["exception"] = get_success_data(
        _api().manager_decision(
            scenario["exception"]["id"],
            {"decision": "APPROVE"},
            make_manager_headers(scenario["manager"]["id"]),
        )
    )
    return scenario


def setup_granted_exception(**kwargs):
    """Carry an exception all the way to GRANTED via the second reviewer, so the
    linked assignment is EXEMPT and open_ack_count has been decremented."""
    scenario = setup_manager_approved_exception(**kwargs)
    scenario["exception"] = get_success_data(
        _api().legal_decision(
            scenario["exception"]["id"],
            {"decision": "APPROVE"},
            make_counsel_headers(scenario["reviewer_2"]["id"]),
        )
    )
    return scenario


# --- Tier 5: retention / evidence ----------------------------------------


def setup_acknowledged_assignment(extra_employees=1, **scenario_kwargs):
    """A delivered assignment that has been acknowledged by ESIGN.

    One spare employee is created by default so the owning package still has an
    open assignment and therefore stays RELEASED rather than closing.
    Returns the scenario dict plus `acknowledgment`.
    """
    scenario = setup_released_scenario(extra_employees=extra_employees, **scenario_kwargs)
    scenario["acknowledgment"] = acknowledge(
        scenario["assignment"], scenario["employee"]["id"]
    )
    return scenario


def retention_rows_for(employee_id):
    return get_success_data(
        _api().list_retention_records(
            ADMIN, params={"employee_id": employee_id, "limit": 100}
        )
    )


def acknowledgments_for(employee_id, status=None):
    params = {"employee_id": employee_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(_api().list_acknowledgments(ADMIN, params=params))


# --- Refresh helpers ------------------------------------------------------


def refresh_employee(employee_id):
    return get_success_data(_api().get_employee(employee_id, ADMIN))


def refresh_reviewer(reviewer_id):
    return get_success_data(_api().get_legal_reviewer(reviewer_id, ADMIN))


def refresh_version(policy_version_id):
    return get_success_data(_api().get_policy_version(policy_version_id, ADMIN))


def refresh_document(policy_document_id):
    return get_success_data(_api().get_policy_document(policy_document_id, ADMIN))


def refresh_addendum(addendum_id):
    return get_success_data(_api().get_addendum(addendum_id, ADMIN))


def refresh_review(legal_review_id):
    return get_success_data(_api().get_legal_review(legal_review_id, ADMIN))


def refresh_translation(translation_id):
    return get_success_data(_api().get_translation(translation_id, ADMIN))


def refresh_package(release_package_id):
    return get_success_data(_api().get_release_package(release_package_id, ADMIN))


def refresh_assignment(assignment_id):
    return get_success_data(_api().get_assignment(assignment_id, ADMIN))


def refresh_case(escalation_case_id):
    return get_success_data(_api().get_escalation(escalation_case_id, ADMIN))


def refresh_exception(policy_exception_id):
    return get_success_data(_api().get_policy_exception(policy_exception_id, ADMIN))


def refresh_acknowledgment(acknowledgment_id):
    return get_success_data(_api().get_acknowledgment(acknowledgment_id, ADMIN))


# --- Thin single-call wrappers used directly by tests ---------------------


def submit_for_review(policy_version_id):
    return get_success_data(_api().submit_version_for_review(policy_version_id, AUTHOR))


def approve_version(policy_version_id):
    return get_success_data(_api().approve_policy_version(policy_version_id, ADMIN))


def reopen_version(policy_version_id):
    return get_success_data(_api().reopen_policy_version(policy_version_id, AUTHOR))


def withdraw_version(policy_version_id):
    return get_success_data(_api().withdraw_policy_version(policy_version_id, ADMIN))


def deliver(assignment_id):
    return get_success_data(_api().deliver_assignment(assignment_id, ADMIN))


def patch_employee(employee_id, **fields):
    return get_success_data(_api().patch_employee(employee_id, fields, ADMIN))


def start_review_as(review_id, reviewer_id):
    return get_success_data(
        _api().start_legal_review(review_id, make_counsel_headers(reviewer_id))
    )


def decide_review_as(review_id, reviewer_id, verdict, comment=None):
    payload = {"verdict": verdict}
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(
        _api().decide_legal_review(review_id, payload, make_counsel_headers(reviewer_id))
    )


def manager_decide(policy_exception_id, manager_employee_id, decision, note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        _api().manager_decision(
            policy_exception_id, payload, make_manager_headers(manager_employee_id)
        )
    )


def legal_decide(policy_exception_id, reviewer_id, decision, note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        _api().legal_decision(
            policy_exception_id, payload, make_counsel_headers(reviewer_id)
        )
    )
