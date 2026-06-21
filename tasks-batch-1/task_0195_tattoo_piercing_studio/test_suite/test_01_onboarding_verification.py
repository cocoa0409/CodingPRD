"""Client onboarding and age/identity verification.

Covers client self-registration defaults, the verification state machine
(submit / approve / reject branches), and the age-gate boundary at exactly 18.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_client_headers, anonymous_no_auth,
    create_client, set_clock,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]
ANON = {"Content-Type": "application/json"}


def test_create_client_defaults_unverified_null_age(api):
    """PRD §3.2: "A newly registered client begins with an `id_status` of
    `UNVERIFIED`. The `id_document_type` is null until a verification is
    submitted, and `verified_age_years` is null until verification is approved."

    Design: Corner/entities/client_id_status_system_default_unverified
    """
    data = validate_success(
        api.create_client(
            factories.create_client_payload(full_name="Fresh", date_of_birth="1990-01-01"),
            ANON,
        ),
        expected_status=201,
    )
    assert data["id_status"] == "UNVERIFIED", f"expected UNVERIFIED, got {data['id_status']}"
    assert data["verified_age_years"] is None, "verified_age_years must be null on a fresh client"


def test_create_client_missing_date_of_birth_rejected(api):
    """PRD §2.9: "A malformed body, a missing required field, or a value that is
    not a member of its declared enumeration is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_client_missing_required_field_rejected
    """
    resp = api.create_client({"full_name": "No DOB", "email": "nodob@example.com"}, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_verification_reject_branch_sets_rejected_null_age(api):
    """PRD §3.2: "On the rejection branch, the manager moves the client from
    `PENDING_REVIEW` to `REJECTED` — again permitted only from `PENDING_REVIEW`
    — optionally recording a `reason`, and `verified_age_years` is left null."

    Design: Corner/state_machines/verification_reject_branch_sets_rejected
    """
    client = create_client(date_of_birth="1990-01-01")
    cid = client["id"]
    ch = make_client_headers(cid)
    get_success_data(api.submit_id_verification(cid, factories.id_verification_payload(), ch))
    data = validate_success(
        api.reject_id_verification(cid, MANAGER, {"reason": "blurry scan"}),
        expected_status=200,
    )
    assert data["id_status"] == "REJECTED", f"expected REJECTED, got {data['id_status']}"
    assert data["verified_age_years"] is None, "rejected client keeps verified_age_years null"


def test_age_gate_exactly_eighteen_passes(api):
    """PRD §3.2: "Approval is the point at which the age gate is enforced: the
    client's whole-year age, computed from `date_of_birth` as of the approval
    date, must be at least the minimum booking age of 18 years."
    PRD §3.2: "On a successful approval, `verified_age_years` is set to that
    whole-year age."

    Design: Difficulty/boundary_precision_check/age_gate_exactly_eighteen_passes
    """
    set_clock("2026-06-01T12:00:00Z")
    client = create_client(date_of_birth="2008-06-01")  # exactly 18 on 2026-06-01
    cid = client["id"]
    ch = make_client_headers(cid)
    get_success_data(
        api.submit_id_verification(cid, factories.id_verification_payload(id_document_type="STATE_ID"), ch)
    )
    data = validate_success(api.approve_id_verification(cid, MANAGER), expected_status=200)
    assert data["id_status"] == "VERIFIED", f"expected VERIFIED at exactly 18, got {data['id_status']}"
    assert data["verified_age_years"] == 18, f"expected verified_age_years 18, got {data['verified_age_years']}"


def test_underage_approval_rejected(api):
    """PRD §3.2: "If the client is younger than 18 whole years at the approval
    date, approval is rejected with `ERR_UNDERAGE`."

    Design: Difficulty/boundary_precision_check/age_gate_exactly_eighteen_passes
    """
    set_clock("2026-06-01T12:00:00Z")
    # One day short of 18 on the approval date.
    client = create_client(date_of_birth="2008-06-02")
    cid = client["id"]
    ch = make_client_headers(cid)
    get_success_data(api.submit_id_verification(cid, factories.id_verification_payload(), ch))
    resp = api.approve_id_verification(cid, MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNDERAGE.value, expected_status=422)
