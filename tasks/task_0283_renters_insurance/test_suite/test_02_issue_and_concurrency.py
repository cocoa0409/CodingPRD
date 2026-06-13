"""Issuing a policy: preconditions, OCC on policy edits, billing setup, RBAC."""
from test_helpers import (
    add_full_coverage,
    create_policyholder,
    create_quoted_policy,
    get_first_invoice,
    issue_policy,
    make_policyholder_headers,
    setup_active_policy,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


def _pp_only(api, policy_id, version):
    return validate_success(
        api.add_coverage_line(
            policy_id,
            {"coverage_type": "PERSONAL_PROPERTY", "limit_cents": 3000000,
             "expected_policy_version": version},
            UW,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Queue B: issue preconditions / state-machine guards
# ---------------------------------------------------------------------------
def test_issue_without_all_three_coverages_rejected(api):
    """PRD §3.3: "The policy must carry exactly one coverage line of each of
    the three coverage types `PERSONAL_PROPERTY`, `LIABILITY`, and
    `LOSS_OF_USE`; a policy missing any of them is rejected with
    ERR_COVERAGE_INCOMPLETE."

    Design: Corner/state_machines/issue_without_all_three_coverages_returns_coverage_incomplete
    """
    ph = create_policyholder(email="s2@x.com")
    policy = create_quoted_policy(ph["id"])
    _pp_only(api, policy["id"], policy["version"])
    validate_error(api.issue_policy(policy["id"], UW), "ERR_COVERAGE_INCOMPLETE", 422)


def test_issue_already_active_policy_rejected(api):
    """PRD §3.8: "any transition requested from a state where it is not defined
    is rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "Issuing a policy advances it from `QUOTED` to `ACTIVE`".

    Design: Corner/state_machines/issue_already_active_policy_returns_invalid_state
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="s1@x.com")
    validate_error(api.issue_policy(policy["id"], UW), "ERR_INVALID_STATE", 409)


def test_duplicate_coverage_type_rejected(api):
    """PRD §3.2: "Each coverage type may appear at most once per policy, so a
    second line of a type already present is rejected with
    ERR_DUPLICATE_COVERAGE_TYPE."

    Design: Corner/state_machines/duplicate_coverage_type_rejected
    """
    ph = create_policyholder(email="s3@x.com")
    policy = create_quoted_policy(ph["id"])
    first = _pp_only(api, policy["id"], policy["version"])
    # read fresh version after the first add bumped it
    v1 = api.get_policy(policy["id"], UW).json()["data"]["version"]
    assert first  # first add succeeded
    resp = api.add_coverage_line(
        policy["id"],
        {"coverage_type": "PERSONAL_PROPERTY", "limit_cents": 5000000,
         "expected_policy_version": v1},
        UW,
    )
    validate_error(resp, "ERR_DUPLICATE_COVERAGE_TYPE", 409)


def test_issue_invalid_term_effective_after_expiry_rejected(api):
    """PRD §3.3: "The `effective_date` must be strictly earlier than the
    `expiry_date`, failing which the issue is rejected with ERR_INVALID_TERM."

    Design: Corner/state_machines/issue_invalid_term_effective_after_expiry_returns_invalid_term
    """
    ph = create_policyholder(email="s4@x.com")
    policy = create_quoted_policy(
        ph["id"], effective_date="2027-01-01T00:00:00Z",
        expiry_date="2026-01-01T00:00:00Z",
    )
    add_full_coverage(policy["id"])
    validate_error(api.issue_policy(policy["id"], UW), "ERR_INVALID_TERM", 422)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap — half-open policy term overlap
# ---------------------------------------------------------------------------
def test_policy_term_half_open_overlap_rejected_on_issue(api):
    """PRD §3.3: "the new term must not overlap the term of any other `ACTIVE`
    or `LAPSED` policy held by the same `policyholder_id`; because the term
    interval is half-open over `[effective_date, expiry_date)`, two terms that
    merely touch at a shared boundary instant do not overlap, but any genuine
    overlap is rejected with ERR_TERM_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_rejected_on_issue
    """
    ph = create_policyholder(email="to1@x.com")
    # First policy, issued, term [2026-01-01, 2027-01-01)
    p1 = create_quoted_policy(ph["id"], insured_address="25 DD St")
    add_full_coverage(p1["id"])
    issue_policy(p1["id"])
    # Second policy, term [2026-06-01, 2027-06-01) genuinely overlaps
    p2 = create_quoted_policy(
        ph["id"], insured_address="26 EE St",
        effective_date="2026-06-01T00:00:00Z", expiry_date="2027-06-01T00:00:00Z",
    )
    add_full_coverage(p2["id"])
    validate_error(api.issue_policy(p2["id"], UW), "ERR_TERM_OVERLAP", 409)


def test_policy_term_touching_boundary_does_not_overlap(api):
    """PRD §3.3: "because the term interval is half-open over
    `[effective_date, expiry_date)`, two terms that merely touch at a shared
    boundary instant do not overlap, but any genuine overlap is rejected with
    ERR_TERM_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_rejected_on_issue
    """
    ph = create_policyholder(email="to1b@x.com")
    p1 = create_quoted_policy(ph["id"], insured_address="25 DD St")
    add_full_coverage(p1["id"])
    issue_policy(p1["id"])
    # term starts exactly at the prior expiry instant -> no overlap, issues fine
    p2 = create_quoted_policy(
        ph["id"], insured_address="26b EE St",
        effective_date="2027-01-01T00:00:00Z", expiry_date="2028-01-01T00:00:00Z",
    )
    add_full_coverage(p2["id"])
    issued = validate_success(api.issue_policy(p2["id"], UW), 200)
    assert issued["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue B: OCC on policy edits (cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
def test_occ_stale_policy_version_on_coverage_line_add(api):
    """PRD §2.7: "That add likewise must carry `expected_policy_version`
    matching the policy's current `version`; a writer still holding the prior
    version has a stale view of which coverage types already exist and is
    rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_coverage_line_add
    """
    ph = create_policyholder(email="occ1@x.com")
    policy = create_quoted_policy(ph["id"])
    v0 = policy["version"]
    first = validate_success(
        api.add_coverage_line(
            policy["id"],
            {"coverage_type": "PERSONAL_PROPERTY", "limit_cents": 3000000,
             "expected_policy_version": v0},
            UW,
        ),
        201,
    )
    assert first
    # second add still carrying the pre-first version is stale
    resp = api.add_coverage_line(
        policy["id"],
        {"coverage_type": "LIABILITY", "limit_cents": 10000000,
         "expected_policy_version": v0},
        UW,
    )
    validate_error(resp, "ERR_STALE_POLICY_VERSION", 412)


def test_occ_correct_version_on_scheduled_item_add_succeeds_and_bumps(api):
    """PRD §2.7: "A scheduled-item add must carry `expected_policy_version`
    equal to the target policy's current `version`."
    PRD §3.2: "scheduling an item is OCC-guarded on `expected_policy_version`
    (see §2.7), re-runs the premium calculation to refresh `annual_premium_cents`,
    and increments the policy's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_scheduled_item_add_succeeds_then_bumps
    """
    ph = create_policyholder(email="occ2@x.com")
    policy = create_quoted_policy(ph["id"])
    v0 = policy["version"]
    si = validate_success(
        api.add_scheduled_item(
            policy["id"],
            {"description": "necklace", "appraised_value_cents": 400000,
             "expected_policy_version": v0},
            UW,
        ),
        201,
    )
    assert si["status"] == "ACTIVE"
    after = validate_success(api.get_policy(policy["id"], UW), 200)
    assert after["version"] == v0 + 1, (after["version"], v0)


# ---------------------------------------------------------------------------
# Queue B: monthly installment surcharge
# ---------------------------------------------------------------------------
def test_monthly_billing_installment_surcharge_on_invoice_only(api):
    """PRD §3.3: "for a `MONTHLY` policy it is one installment, computed as the
    annual premium multiplied by 1.05 and divided by 12, rounded half up to a
    whole cent — the 1.05 factor being the five-percent installment surcharge."
    PRD §3.2: "Note that `billing_mode` does not alter `annual_premium_cents`
    at all; it changes only the amount of the invoice created at issue".

    Design: Corner/calculations/monthly_billing_installment_surcharge_applied_to_invoice_only
    """
    _ph, policy, _lines, invoice = setup_active_policy(
        billing_mode="MONTHLY", email="cc2@x.com"
    )
    assert policy["annual_premium_cents"] == 33350, policy["annual_premium_cents"]
    assert invoice["amount_cents"] == 2918, invoice["amount_cents"]


# ---------------------------------------------------------------------------
# Queue B: RBAC
# ---------------------------------------------------------------------------
def test_policyholder_cannot_issue_policy(api):
    """PRD §2.1: "The `Underwriter` is a carrier operator who creates
    policyholders, bundles, and policies, manages coverage lines and scheduled
    items, issues, cancels, and reinstates policies".
    PRD §2.1: "When an authenticated role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/policyholder_cannot_issue_policy
    """
    ph = create_policyholder(email="rb1@x.com")
    policy = create_quoted_policy(ph["id"])
    add_full_coverage(policy["id"])
    resp = api.issue_policy(policy["id"], make_policyholder_headers(ph["id"]))
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed
    value, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request("GET", "/policies", headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)
