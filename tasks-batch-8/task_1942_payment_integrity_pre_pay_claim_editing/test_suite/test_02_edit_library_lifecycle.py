"""Edit version lifecycle: birth state, state-gated actions, terminal
lockdown, suspension screening effect, retirement guard, and the
suspend/reactivate and submit/reject cycles."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_and_decide,
    create_active_edit,
    create_edit_rule,
    create_edit_version,
    get_success_data,
    get_version,
    list_claim_hits,
    list_claim_tasks,
    screen_one_line_claim,
    setup_provider_with_active_edit,
    submit_version,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_edit_version_starts_in_draft(api):
    """PRD §3.2: "A new version is born in `DRAFT`; the server assigns its
    `version_number` sequentially within the rule starting at 1 in creation
    order, and records the authoring librarian in `created_by_user_id`."

    Design: Corner/state_machines/edit_version_starts_in_draft
    """
    rule = create_edit_rule(edit_code="INIT-01", category="POLICY",
                            librarian_id="librarian-1")
    version = validate_success(api.create_edit_version(
        rule["id"],
        {"severity": "MONITOR", "applies_to_claim_types": ["PROFESSIONAL"],
         "logic_expression": "watch",
         "effective_from": "2026-01-01T00:00:00Z"},
        {"X-User-ID": "librarian-7", "X-User-Role": "EditLibrarian",
         "Content-Type": "application/json"}), expected_status=201)
    assert version["status"] == "DRAFT"
    assert version["version_number"] == 1
    assert version["created_by_user_id"] == "librarian-7"


def test_approve_from_draft_rejected(api):
    """PRD §3.2: "approval and rejection require `PENDING_APPROVAL`"
    PRD §3.2: "Any edit-version action attempted from a status that does not
    permit it is rejected with `ERR_EDIT_VERSION_NOT_APPROVABLE` (HTTP 409)."

    Design: Corner/state_machines/approve_from_draft_rejected
    """
    rule = create_edit_rule(edit_code="INV-01", category="POLICY")
    version = create_edit_version(rule["id"])
    resp = api.approve_edit_version(
        version["id"], {"expected_edit_rule_version": rule["version"]},
        APPROVER)
    validate_error(resp, ApiErrorId.ERR_EDIT_VERSION_NOT_APPROVABLE,
                   expected_status=409)
    assert get_version(version["id"])["status"] == "DRAFT"


def test_retired_version_terminal_lockdown(api):
    """PRD §3.2: "`RETIRED` is terminal and accepts no further action."
    PRD §3.2: "Any edit-version action attempted from a status that does not
    permit it is rejected with `ERR_EDIT_VERSION_NOT_APPROVABLE` (HTTP 409)."

    Design: Corner/state_machines/retired_version_terminal_lockdown
    """
    rule, version = create_active_edit(edit_code="TERM-01", category="POLICY")
    retired = validate_success(
        api.retire_edit_version(version["id"], APPROVER))
    assert retired["status"] == "RETIRED"

    for action in (
        lambda: api.suspend_edit_version(version["id"], {}, APPROVER),
        lambda: api.reactivate_edit_version(version["id"], APPROVER),
        lambda: api.retire_edit_version(version["id"], APPROVER),
    ):
        validate_error(action(), ApiErrorId.ERR_EDIT_VERSION_NOT_APPROVABLE,
                       expected_status=409)
    assert get_version(version["id"])["status"] == "RETIRED"


def test_suspended_edit_does_not_fire(api):
    """PRD §3.4: "One edit hit is created per eligible `ACTIVE` edit version
    per claim line"
    PRD §3.4: "When the run produced none of those, the claim goes straight to
    `READY_TO_PAY`"

    Design: Corner/state_machines/suspended_edit_does_not_fire
    """
    provider, rule, version = setup_provider_with_active_edit(
        npi="NPI-SM6", edit_code="SUSP-01")
    get_success_data(api.suspend_edit_version(version["id"], {}, APPROVER))
    assert get_version(version["id"])["status"] == "SUSPENDED"

    claim = screen_one_line_claim(provider["id"], billed=30000,
                                  claim_number="SU1", member_id="M-SU1")
    assert claim["status"] == "READY_TO_PAY"
    assert claim["allowed_amount_cents"] == 30000
    assert claim["denied_amount_cents"] == 0
    hits = list_claim_hits(claim["id"])
    assert hits == [], "a SUSPENDED version must not fire any hit"


def test_retire_version_with_fired_hits_rejected(api):
    """PRD §3.2: "it is refused with `ERR_EDIT_VERSION_IN_USE` (HTTP 409)
    while any hit pinned to the version remains `FIRED`, because retiring a
    version with live pended work would orphan the review queue."
    PRD §3.2: "Retirement moves an `ACTIVE` or `SUSPENDED` version to
    `RETIRED`"

    Design: Corner/state_machines/retire_version_with_fired_hits_rejected
    """
    provider, rule, version = setup_provider_with_active_edit(
        npi="NPI-SM7", edit_code="RET-01")
    claim = screen_one_line_claim(provider["id"], billed=30000,
                                  claim_number="RT1", member_id="M-RT1")
    assert claim["status"] == "PENDED"

    resp = api.retire_edit_version(version["id"], APPROVER)
    validate_error(resp, ApiErrorId.ERR_EDIT_VERSION_IN_USE,
                   expected_status=409)

    task = list_claim_tasks(claim["id"])[0]
    assign_and_decide(task["id"], reviewer_id="rev-1", outcome="UPHOLD")
    retired = validate_success(api.retire_edit_version(version["id"], APPROVER))
    assert retired["status"] == "RETIRED"


def test_edit_version_suspend_reactivate_cycle(api):
    """PRD §3.2: "An `EditApprover` may suspend an `ACTIVE` version manually,
    attaching an optional `note`."
    PRD §3.2: "Reactivation returns a `SUSPENDED` version to `ACTIVE`, but
    only while its `fp_rate` is below 0.25"

    Design: Difficulty/non_linear_state_machine/edit_version_suspend_reactivate_cycle
    """
    rule, version = create_active_edit(edit_code="CYC-01", category="POLICY")
    assert version["status"] == "ACTIVE"

    suspended = validate_success(
        api.suspend_edit_version(version["id"], {}, APPROVER))
    assert suspended["status"] == "SUSPENDED"

    reactivated = validate_success(
        api.reactivate_edit_version(version["id"], APPROVER))
    assert reactivated["status"] == "ACTIVE", (
        "fp_rate 0 < 0.25, so the SUSPENDED -> ACTIVE leg must succeed"
    )
    assert get_version(version["id"])["status"] == "ACTIVE"


def test_edit_version_reject_returns_to_draft_cycle(api):
    """PRD §3.2: "Submission moves a version from `DRAFT` to
    `PENDING_APPROVAL`."
    PRD §3.2: "Rejection returns a `PENDING_APPROVAL` version to `DRAFT` and
    accepts an optional `rejection_reason`."

    Design: Difficulty/non_linear_state_machine/edit_version_suspend_reactivate_cycle
    """
    rule = create_edit_rule(edit_code="CYC-02", category="POLICY")
    version = create_edit_version(rule["id"])
    submitted = submit_version(version["id"])
    assert submitted["status"] == "PENDING_APPROVAL"
    rejected = validate_success(api.reject_edit_version(
        version["id"], {"rejection_reason": "needs work"}, APPROVER))
    assert rejected["status"] == "DRAFT", (
        "DRAFT -> PENDING_APPROVAL -> DRAFT cycle must close on the same row"
    )
    assert get_version(version["id"])["status"] == "DRAFT"
