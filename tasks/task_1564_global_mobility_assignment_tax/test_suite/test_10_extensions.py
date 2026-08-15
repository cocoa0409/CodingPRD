"""Extension requests: OCC-guarded create-with-supersede, the strictly-forward
and duration-cap input rules, the certificate coverage gate, and the
overrun-posture gate wired to the record-post cascade (PRD §2.7, §3.3, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_post_record,
    create_current_projection,
    create_extension_payload,
    create_pending_extension,
    get_assignment,
    get_assignment_version,
    setup_active_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BU = TEST_USERS["bu_approver_headers"]


def test_occ_stale_version_rejected_on_extension_create(api, admin_headers):
    """PRD §2.7: "Each of these requests must carry `expected_assignment_version`, a
    non-optional input holding the `version` of the target Assignment as the client
    last observed it."
    PRD §2.7: "If that value does not match the Assignment's current `version` —
    because an extension approval, a cost-projection creation, an extension-request
    creation, or a repatriation initiation has advanced it since the client's last
    read — the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412),
    preventing the client from acting on terms it has not observed."

    Design: Corner/validations/occ_stale_version_rejected_on_extension_create
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    version = get_assignment_version(asg_id)

    first = validate_success(api.create_extension(
        create_extension_payload(asg_id, "2027-10-31", version), ADMIN), 201)
    assert first["status"] == "PENDING"

    # The first create bumped the assignment version; replaying the captured
    # version is stale.
    res = api.create_extension(
        create_extension_payload(asg_id, "2027-11-30", version), ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION)

    fetched = validate_success(api.get_extension(first["id"], admin_headers), 200)
    assert fetched["status"] == "PENDING", "a rejected create must not supersede"


def test_extension_not_forward_and_max_duration_rejected(api, admin_headers):
    """PRD §3.7: "Within the date-window family, the strictly-forward rule precedes
    the duration cap: a `requested_new_end_date` that is not strictly after the
    assignment's current `planned_end_date` is rejected with
    `ERR_EXTENSION_NOT_FORWARD` (HTTP 422), and one that would push the assignment
    beyond `start_date` plus the program's `max_assignment_duration_days` is rejected
    with `ERR_MAX_DURATION_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/extension_not_forward_and_max_duration_rejected
    """
    ctx = setup_active_assignment(
        policy_overrides={"effective_from": "2026-01-01", "effective_to": "2033-01-01"})
    asg_id = ctx["assignment"]["id"]
    version = get_assignment_version(asg_id)

    # Equal to the current planned end: not strictly forward.
    res = api.create_extension(
        create_extension_payload(asg_id, "2027-08-31", version), ADMIN)
    validate_error(res, ApiErrorId.ERR_EXTENSION_NOT_FORWARD)

    # The failed create did not bump the version, so OCC still passes; the
    # strictly-forward rule passes here, and the duration cap fires.
    res = api.create_extension(
        create_extension_payload(asg_id, "2032-01-01", version), ADMIN)
    validate_error(res, ApiErrorId.ERR_MAX_DURATION_EXCEEDED)


def _setup_totalized_assignment_with_short_window():
    """Activated totalization-covered assignment ending 2027-06-30, with the
    certificate covering 2026-09-01..2027-08-31."""
    return setup_active_assignment(
        totalization=True,
        coc_valid_from="2026-09-01",
        coc_valid_until="2027-08-31",
        assignment_overrides={"planned_end_date": "2027-06-30"},
    )


def test_extension_approve_beyond_certificate_coverage_rejected(api, bu_approver_headers):
    """PRD §3.7: "Approval requires the same two state conditions and then evaluates
    two further gates in a fixed order: first the coverage gate — when
    `totalization_applies` is true, an `ISSUED` certificate whose `valid_until` falls
    on or after the `requested_new_end_date` must exist, otherwise the approval is
    rejected with `ERR_COC_COVERAGE_GAP`; then the posture gate — while the
    assignment's `cost_posture` is `OVERRUN`, approval is rejected with
    `ERR_COST_OVERRUN_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_certificate_coverage
    """
    ctx = _setup_totalized_assignment_with_short_window()
    asg_id = ctx["assignment"]["id"]

    # Forward of 2027-06-30 but past the certificate's 2027-08-31 coverage end.
    extension = create_pending_extension(asg_id, "2027-11-30")
    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_COC_COVERAGE_GAP)

    fetched = validate_success(api.get_extension(extension["id"], ADMIN), 200)
    assert fetched["status"] == "PENDING"


def test_extension_within_coverage_supersedes_and_approves(api, bu_approver_headers, admin_headers):
    """PRD §3.7: "Creation is create-with-supersede: any prior `PENDING` request for
    the same assignment becomes `SUPERSEDED`, the new request starts in `PENDING`, and
    the assignment's `version` increments by one."
    PRD §3.7: "An approved extension moves the request to `APPROVED`, records
    `decided_by_user_id`, sets the assignment's `planned_end_date` to the
    `requested_new_end_date`, refreshes the assignment's `updated_at`, and increments
    the assignment's `version` by one"

    Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_certificate_coverage
    """
    ctx = _setup_totalized_assignment_with_short_window()
    asg_id = ctx["assignment"]["id"]

    first = create_pending_extension(asg_id, "2027-11-30")
    validate_error(
        api.approve_extension(first["id"], bu_approver_headers),
        ApiErrorId.ERR_COC_COVERAGE_GAP,
    )

    # 2027-08-15 is strictly forward of the current 2027-06-30 end date and
    # inside the certificate coverage ending 2027-08-31.
    second = create_pending_extension(asg_id, "2027-08-15")
    stale_first = validate_success(api.get_extension(first["id"], admin_headers), 200)
    assert stale_first["status"] == "SUPERSEDED", (
        "the new create supersedes the prior PENDING request"
    )

    approved = validate_success(api.approve_extension(second["id"], bu_approver_headers), 200)
    assert approved["status"] == "APPROVED"
    assert get_assignment(asg_id)["planned_end_date"] == "2027-08-15"


def test_extension_approve_blocked_by_overrun_after_record_post(api, bu_approver_headers, admin_headers):
    """PRD §3.3: "The third hop re-runs the overrun posture check of §3.6, which may
    flip `cost_posture` from `NORMAL` to `OVERRUN`; while the posture is `OVERRUN`,
    extension approval is rejected with `ERR_COST_OVERRUN_BLOCKED` (§3.7)."

    Design: Difficulty/transitive_cascade/record_post_cascade_to_overrun_gate
    """
    ctx = setup_active_assignment(program_overrides={"cost_overrun_threshold_pct": 110})
    asg_id = ctx["assignment"]["id"]
    create_current_projection(asg_id)
    create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=1203188,
        per_diem_days=20, housing_receipts_cents=300000)
    assert get_assignment(asg_id)["cost_posture"] == "OVERRUN"

    extension = create_pending_extension(asg_id, "2027-10-31")
    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_COST_OVERRUN_BLOCKED)

    fetched = validate_success(api.get_extension(extension["id"], admin_headers), 200)
    assert fetched["status"] == "PENDING"
    assert get_assignment(asg_id)["planned_end_date"] == "2027-08-31"
