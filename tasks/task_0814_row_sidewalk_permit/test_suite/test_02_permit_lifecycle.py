"""Permit lifecycle: drafting, the review revision loop, expiration, and
role/ownership gating on lifecycle actions."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER_1 = TEST_USERS["reviewer_headers"]
REVIEWER_2 = TEST_USERS["reviewer_2_headers"]


def test_new_permit_starts_in_draft(api):
    """PRD §3.2: "A new permit begins in `DRAFT`."
    PRD §2.4: "a `version` integer that begins at 1 and increments by one on
    every mutation."

    Design: Corner/state_machines/permit_initial_state_is_draft
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    permit = fixtures.create_draft_permit(api, app["id"], seg["id"])
    assert permit["status"] == "DRAFT"
    assert permit["version"] == 1


def test_submit_from_approved_returns_invalid_state(api):
    """PRD §3.2: "Submitting a permit that is in neither `DRAFT` nor
    `RETURNED_FOR_REVISION` is rejected with `ERR_INVALID_PERMIT_STATE`, and a
    submit by anyone other than the owning applicant is an authorization failure."

    Design: Corner/state_machines/submit_from_approved_returns_invalid_state
    """
    ctx = fixtures.setup_approved_permit(api)
    headers = make_applicant_headers(ctx["app_id"])
    resp = api.submit_permit(ctx["permit_id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE.value)


def test_submit_from_expired_terminal_is_locked(api):
    """PRD §3.2: "Submitting a permit that is in neither `DRAFT` nor
    `RETURNED_FOR_REVISION` is rejected with `ERR_INVALID_PERMIT_STATE`, and a
    submit by anyone other than the owning applicant is an authorization failure."

    Design: Corner/state_machines/expired_permit_submit_terminal_lockdown
    """
    ctx = fixtures.setup_issued_permit(api)  # valid_until 2026-04-11
    fixtures.set_clock(api, "2026-04-12T00:00:00Z")
    expired = get_success_data(api.expire_permit(ctx["permit_id"], ADMIN))
    assert expired["status"] == "EXPIRED"

    headers = make_applicant_headers(ctx["app_id"])
    resp = api.submit_permit(ctx["permit_id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE.value)


def test_reviewer_returns_permit_to_revision(api):
    """PRD §3.2: "When the `outcome` returns the permit for rework, it transitions
    to `RETURNED_FOR_REVISION` and the supplied `review_notes` are stored."

    Design: Difficulty/non_linear_state_machine/permit_review_revision_cycle
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    headers = make_applicant_headers(app["id"])
    permit = fixtures.create_draft_permit(api, app["id"], seg["id"])
    get_success_data(api.submit_permit(permit["id"], headers))
    returned = get_success_data(
        api.decide_permit(
            permit["id"], {"outcome": "RETURNED", "review_notes": "add dimensions"}, REVIEWER_1
        )
    )
    assert returned["status"] == "RETURNED_FOR_REVISION"


def test_returned_permit_resubmit_reenters_review(api):
    """PRD §3.2: "the same submit action also carries a permit from
    `RETURNED_FOR_REVISION` back to `UNDER_REVIEW`, forming the revision loop."

    Design: Difficulty/non_linear_state_machine/permit_review_revision_cycle
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    headers = make_applicant_headers(app["id"])
    permit = fixtures.create_draft_permit(api, app["id"], seg["id"])
    get_success_data(api.submit_permit(permit["id"], headers))
    get_success_data(
        api.decide_permit(
            permit["id"], {"outcome": "RETURNED", "review_notes": "add dimensions"}, REVIEWER_1
        )
    )
    resubmitted = get_success_data(api.submit_permit(permit["id"], headers))
    assert resubmitted["status"] == "UNDER_REVIEW"


def test_expire_before_valid_until_rejected(api):
    """PRD §3.9: "An expiration attempted while the clock date is on or before
    `valid_until` is rejected with `ERR_NOT_YET_EXPIRED`; attempting to expire a
    permit that is not `ISSUED` is rejected with `ERR_INVALID_PERMIT_STATE`."

    Design: Corner/validations/not_yet_expired_violation_to_error
    """
    ctx = fixtures.setup_issued_permit(api)  # valid_until 2026-04-11, clock at 2026-03-01 default
    resp = api.expire_permit(ctx["permit_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_YET_EXPIRED.value)


def test_applicant_cannot_issue_permit(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation — or an `Applicant` attempts to act on a
    permit it does not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/rbac_applicant_cannot_issue_permit
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    permit = fixtures.create_draft_permit(api, app["id"], seg["id"])
    headers = make_applicant_headers(app["id"])
    resp = api.issue_permit(permit["id"], headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_non_owner_applicant_cannot_submit(api):
    """PRD §2.1: "Ownership checks on any resource that references an applicant
    compare the governing permit's `applicant_id` to `X-User-ID`; a mismatch is
    an authorization failure."

    Design: Corner/rbac/rbac_non_owner_applicant_cannot_submit
    """
    app_a = fixtures.create_applicant(api, company_name="Acme", license_number="L1")
    app_b = fixtures.create_applicant(
        api, company_name="Beta", license_number="L2", contact_email="b@x.com"
    )
    seg = fixtures.create_segment(api)
    permit = fixtures.create_draft_permit(api, app_a["id"], seg["id"])
    resp = api.submit_permit(permit["id"], make_applicant_headers(app_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
