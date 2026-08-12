"""Insurance claims: verify error matrix, supersession, student-version OCC,
reverse reachability, and role exclusivity (PRD §2.1, §2.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_insurance_policy,
    assert_timestamp_prefix,
    create_insurance_policy_payload,
    make_policy,
    make_student,
    set_clock,
    validate_error,
    validate_success,
)


def test_policy_verify_error_matrix(api, billing_officer_headers):
    """PRD §3.2: "The policy must currently be `UNVERIFIED` — verifying anything
    else is rejected with `ERR_POLICY_NOT_UNVERIFIED`. The coverage window must
    still be live: a policy whose `coverage_end` has passed the current logical
    time is rejected with `ERR_POLICY_EXPIRED`. And for the `STUDENT_PLAN` payer
    type specifically, the covered student's `enrollment_status` must be
    `ENROLLED` at verify time — a student-plan policy for a student on leave or
    withdrawn is rejected with `ERR_POLICY_NOT_ELIGIBLE`."
    PRD §3.2: "A successful verify stamps `verified_at` with the current logical
    time and moves the policy `UNVERIFIED → VERIFIED`."

    Design: Corner/state_machines/policy_verify_error_matrix
    """
    set_clock("2026-05-01T00:00:00Z")

    student_a = make_student("S24", "Pol A")
    policy_a = make_policy(student_a, policy_number="PA-1")

    student_b = make_student("S25", "Pol B")
    policy_b = make_policy(
        student_b, policy_number="PB-1",
        coverage_start="2026-01-01T00:00:00Z", coverage_end="2026-04-01T00:00:00Z",
    )

    student_c = make_student("S26", "Pol C", enrollment_status="LEAVE")
    policy_c = make_policy(student_c, payer_type="STUDENT_PLAN", policy_number="PC-1")

    # Happy path: verify succeeds and stamps verified_at with the clock time.
    verified = validate_success(
        api.verify_insurance_policy(policy_a["id"], billing_officer_headers), 200
    )
    assert_insurance_policy(verified)
    assert verified["status"] == "VERIFIED"
    assert_timestamp_prefix(verified["verified_at"], "2026-05-01T00:00",
                            label="verified_at")

    # Double verify: no longer UNVERIFIED.
    res1 = api.verify_insurance_policy(policy_a["id"], billing_officer_headers)
    validate_error(res1, ApiErrorId.ERR_POLICY_NOT_UNVERIFIED, expected_status=409)

    # Coverage already lapsed (2026-04-01 < clock 2026-05-01).
    res2 = api.verify_insurance_policy(policy_b["id"], billing_officer_headers)
    validate_error(res2, ApiErrorId.ERR_POLICY_EXPIRED, expected_status=422)

    # STUDENT_PLAN requires an ENROLLED student at verify time.
    res3 = api.verify_insurance_policy(policy_c["id"], billing_officer_headers)
    validate_error(res3, ApiErrorId.ERR_POLICY_NOT_ELIGIBLE, expected_status=422)


def test_occ_stale_student_version_on_policy_create(api, billing_officer_headers):
    """PRD §2.8: "If the student's current `version` has advanced beyond what
    the caller observed — for example because another policy was created in the
    meantime, superseding the prior one and bumping the student's version — the
    create is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412)".
    PRD §3.2: "When a new policy is created for a student who already has one in
    `UNVERIFIED` or `VERIFIED` status, the older policy transitions
    automatically to `SUPERSEDED`."

    Design: Corner/cross_cutting_layers/occ_stale_student_version_on_policy_create
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S70", "Occ Stu")
    stale_version = student["version"]

    # First create succeeds and bumps the student's version.
    policy_a = validate_success(
        api.create_insurance_policy(
            create_insurance_policy_payload(
                student["id"], stale_version, policy_number="OC-1", copay_cents=100
            ),
            billing_officer_headers,
        ),
        201,
    )
    assert policy_a["status"] == "UNVERIFIED"

    student_after = validate_success(
        api.get_student(student["id"], billing_officer_headers), 200
    )
    assert student_after["version"] == stale_version + 1, (
        "creating a policy supersedes and mutates the student aggregate"
    )
    fresh_version = student_after["version"]

    # Replay with the stale observed version -> 412.
    res = api.create_insurance_policy(
        create_insurance_policy_payload(
            student["id"], stale_version, payer_type="STUDENT_PLAN",
            policy_number="OC-2",
        ),
        billing_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_STUDENT_VERSION, expected_status=412)

    # Retry with the fresh version succeeds and supersedes the first policy.
    policy_b = validate_success(
        api.create_insurance_policy(
            create_insurance_policy_payload(
                student["id"], fresh_version, payer_type="STUDENT_PLAN",
                policy_number="OC-2",
            ),
            billing_officer_headers,
        ),
        201,
    )
    assert policy_b["status"] == "UNVERIFIED"

    policies = validate_success(
        api.list_student_policies(student["id"], billing_officer_headers), 200
    )
    by_id = {p["id"]: p for p in policies}
    assert by_id[policy_a["id"]]["status"] == "SUPERSEDED"
    assert by_id[policy_b["id"]]["status"] == "UNVERIFIED"


def test_fk_reverse_reachability_student_policies(api, billing_officer_headers):
    """PRD §4: `GET /shc/students/{id}/insurance-policies` — "List a student's
    policies"; PRD §2.2: list responses return "an array of resource objects".

    Design: Corner/endpoints/fk_reverse_reachability_student_policies
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S51", "Reverse FK")
    policy = make_policy(student, policy_number="RF-1")

    policies = validate_success(
        api.list_student_policies(student["id"], billing_officer_headers), 200
    )
    assert isinstance(policies, list) and len(policies) == 1, (
        f"expected exactly one policy for the student, got {policies}"
    )
    assert policies[0]["id"] == policy["id"]
    assert policies[0]["student_id"] == student["id"]


def test_frontdesk_cannot_verify_policy_forbidden(api, front_desk_headers):
    """PRD §2.1: "an authenticated caller whose role is not on the endpoint's
    authorized list is rejected with `ERR_FORBIDDEN`." PRD §4: verifying a
    policy is authorized for `BillingOfficer` only.

    Design: Corner/rbac/frontdesk_cannot_verify_policy_forbidden
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S63", "Verify Deny")
    policy = make_policy(student, policy_number="VD-1")

    res = api.verify_insurance_policy(policy["id"], front_desk_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
