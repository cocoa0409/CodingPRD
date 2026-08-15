"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the server before each test) using only PRD-declared
endpoints, and validates setup calls with the lenient get_success_data so
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    assign_payload,
    clock_payload,
    create_appeal_payload,
    create_attachment_payload,
    create_denial_payload,
    create_payer_payload,
    create_policy_payload,
    create_remittance_code_payload,
    create_scorecard_payload,
    create_task_payload,
    create_write_off_payload,
    implement_fix_payload,
    outcome_payload,
    triage_payload,
)
from .test_users import TEST_USERS, director_headers, manager_headers, specialist_headers, upstream_owner_headers

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["manager_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
UPSTREAM = TEST_USERS["upstream_owner_headers"]


# ---------------------------------------------------------------- clock ---

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (director-only). Returns the clock response data."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), DIRECTOR))


# ------------------------------------------------------------ catalogs ---

def make_payer(**overrides) -> dict:
    """Create a payer. Returns the payer resource."""
    return get_success_data(api_client.create_payer(create_payer_payload(**overrides), DIRECTOR))


def make_policy(payer_id, level_number=1, **overrides) -> dict:
    """Create a payer appeal policy for (payer_id, level_number)."""
    return get_success_data(
        api_client.create_payer_appeal_policy(
            create_policy_payload(payer_id, level_number, **overrides), DIRECTOR
        )
    )


def make_remittance_code(**overrides) -> dict:
    """Register a remittance code (default CO-16 / CODING / CODING / appealable)."""
    return get_success_data(
        api_client.create_remittance_code(create_remittance_code_payload(**overrides), DIRECTOR)
    )


def setup_catalog(levels=(1,), payer_overrides=None, code_overrides=None,
                  policy_overrides_by_level=None):
    """Payer + one appeal policy per requested level + one remittance code.

    Returns dict(payer, policies, code) where policies maps level_number -> policy.
    Pass levels=() to create a payer with no policies (default-fallback scenarios).
    """
    payer = make_payer(**(payer_overrides or {}))
    policies = {}
    for level in levels:
        overrides = (policy_overrides_by_level or {}).get(level, {})
        policies[level] = make_policy(payer["id"], level, **overrides)
    code = make_remittance_code(**(code_overrides or {}))
    return {"payer": payer, "policies": policies, "code": code}


# ------------------------------------------------------------- denials ---

def make_denial(payer_id, remittance_code_id, **overrides) -> dict:
    """Intake a denial (specialist). Returns the denial in RECEIVED."""
    return get_success_data(
        api_client.create_denial_case(
            create_denial_payload(payer_id, remittance_code_id, **overrides), SPECIALIST
        )
    )


def triage_denial(denial_id, preventable_flag=False, root_cause_department=None) -> dict:
    """Triage a RECEIVED denial. Returns the denial in TRIAGED."""
    payload = triage_payload(preventable_flag)
    if root_cause_department is not None:
        payload["root_cause_department"] = root_cause_department
    return get_success_data(api_client.triage_denial(denial_id, payload, SPECIALIST))


def assign_denial(denial_id, expected_version, specialist_id="spec-1") -> dict:
    """Assign a TRIAGED/QUEUED denial under the OCC guard. Returns the denial."""
    return get_success_data(
        api_client.assign_denial(
            denial_id, assign_payload(specialist_id, expected_version), MANAGER
        )
    )


def make_queued_denial(payer_id, remittance_code_id, specialist_id="spec-1", **overrides) -> dict:
    """Intake + triage + assign. Returns the denial in QUEUED (version captured live)."""
    denial = make_denial(payer_id, remittance_code_id, **overrides)
    triaged = triage_denial(denial["id"], preventable_flag=overrides.get("preventable_flag", False))
    return assign_denial(denial["id"], triaged["version"], specialist_id=specialist_id)


# ------------------------------------------------------------- appeals ---

def make_appeal(denial_id) -> dict:
    """Open the next appeal level for a denial. Returns the appeal in DRAFT."""
    return get_success_data(
        api_client.create_appeal(create_appeal_payload(denial_id), SPECIALIST)
    )


def attach_document(appeal_id, document_type="CLINICAL_NOTES", file_reference=None) -> dict:
    """Attach a clinical document to a DRAFT/LETTER_GENERATED appeal."""
    overrides = {}
    if file_reference is not None:
        overrides["file_reference"] = file_reference
    return get_success_data(
        api_client.create_appeal_attachment(
            create_attachment_payload(appeal_id, document_type, **overrides), SPECIALIST
        )
    )


def make_lettered_appeal(denial_id, attachment_types=("CLINICAL_NOTES",)) -> dict:
    """Create appeal + attach the given document types + generate letter.

    Returns the appeal in LETTER_GENERATED.
    """
    appeal = make_appeal(denial_id)
    for doc_type in attachment_types:
        attach_document(appeal["id"], doc_type, file_reference=f"doc-{appeal['id'][:8]}-{doc_type.lower()}")
    return get_success_data(api_client.generate_letter(appeal["id"], SPECIALIST))


def make_submitted_appeal(denial_id, attachment_types=("CLINICAL_NOTES",)) -> dict:
    """Lettered appeal + submit. Returns the appeal in SUBMITTED."""
    appeal = make_lettered_appeal(denial_id, attachment_types)
    return get_success_data(api_client.submit_appeal(appeal["id"], SPECIALIST))


def record_outcome(appeal_id, outcome, recovered_amount_cents) -> dict:
    """Record the payer's decision on a SUBMITTED appeal. Returns the appeal."""
    return get_success_data(
        api_client.record_outcome(
            appeal_id, outcome_payload(outcome, recovered_amount_cents), SPECIALIST
        )
    )


def setup_denial_with_submitted_appeal(payer_id, code_id, claim_number,
                                       denied_amount_cents=250000,
                                       billed_amount_cents=None,
                                       attachment_types=("CLINICAL_NOTES",)):
    """Queued denial + SUBMITTED level-1 appeal. Returns (denial_id, appeal)."""
    kwargs = {"claim_number": claim_number, "denied_amount_cents": denied_amount_cents}
    if billed_amount_cents is not None:
        kwargs["billed_amount_cents"] = billed_amount_cents
    denial = make_queued_denial(payer_id, code_id, **kwargs)
    appeal = make_submitted_appeal(denial["id"], attachment_types)
    return denial["id"], appeal


# --------------------------------------------------------- write-offs ---

def make_write_off(denial_id, requested_amount_cents, reason_code="SMALL_BALANCE",
                   requester_user_id="spec-1") -> dict:
    """Create a write-off request as the given specialist user id."""
    return get_success_data(
        api_client.create_write_off_request(
            create_write_off_payload(denial_id, requested_amount_cents, reason_code=reason_code),
            specialist_headers(requester_user_id),
        )
    )


def approve_write_off(request_id, approver_headers=None) -> dict:
    """Approve a pending request (default: a manager distinct from spec-1)."""
    headers = approver_headers or manager_headers("mgr-1")
    return get_success_data(api_client.approve_write_off(request_id, headers))


# -------------------------------------------------------- root-cause ---

def get_auto_task_for_denial(denial_id) -> dict:
    """Fetch the auto-created root-cause task attached to a preventable denial."""
    data = get_success_data(
        api_client.list_root_cause_tasks(MANAGER, params={"denial_case_id": denial_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one auto task for denial {denial_id}, got {data}"
    )
    return data[0]


def make_verified_task(payer_id, code_id, claim_number, denied_amount_cents=100000,
                       implementer_user_id="uo-1", verifier_user_id="mgr-1",
                       verify_clock=None):
    """Preventable denial -> auto task -> acknowledge -> implement -> verify.

    Returns dict(denial, task) with the task in VERIFIED. When verify_clock is
    given, the logical clock is advanced to that instant before verification.
    """
    denial = make_denial(payer_id, code_id, claim_number=claim_number,
                         billed_amount_cents=denied_amount_cents + 20000,
                         denied_amount_cents=denied_amount_cents)
    triage_denial(denial["id"], preventable_flag=True)
    task = get_auto_task_for_denial(denial["id"])
    get_success_data(api_client.acknowledge_task(task["id"], upstream_owner_headers(implementer_user_id)))
    get_success_data(api_client.implement_fix(
        task["id"], implement_fix_payload(), upstream_owner_headers(implementer_user_id)
    ))
    if verify_clock is not None:
        set_clock(verify_clock)
    verified = get_success_data(api_client.verify_task(task["id"], manager_headers(verifier_user_id)))
    return {"denial": denial, "task": verified}


# --------------------------------------------------------- scorecards ---

def make_scorecard(department="CODING", period_start_date="2026-08-01",
                   period_end_date="2026-12-31") -> dict:
    """Open a department scorecard. Returns the scorecard in OPEN."""
    return get_success_data(
        api_client.create_department_scorecard(
            create_scorecard_payload(
                department,
                period_start_date=period_start_date,
                period_end_date=period_end_date,
            ),
            DIRECTOR,
        )
    )


def get_scorecard(scorecard_id) -> dict:
    return get_success_data(api_client.get_department_scorecard(scorecard_id, MANAGER))


def get_denial(denial_id) -> dict:
    return get_success_data(api_client.get_denial_case(denial_id, MANAGER))


def get_task(task_id) -> dict:
    return get_success_data(api_client.get_root_cause_task(task_id, MANAGER))


def get_payer(payer_id) -> dict:
    return get_success_data(api_client.get_payer(payer_id, MANAGER))


__all__ = [name for name in dir() if not name.startswith("_")]
