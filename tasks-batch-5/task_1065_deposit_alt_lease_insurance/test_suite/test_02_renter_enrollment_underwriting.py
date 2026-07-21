"""Renter enrollment creation gates, underwriting risk scoring, and the state-compliance /
property-active / lease-overlap validation stack (PRD §2.7, §3.2)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    create_landlord, create_renter, create_property, create_state_compliance_rule,
    activate_property, terminate_property, setup_active_property,
    create_renter_enrollment, submit_underwriting,
    create_renter_enrollment_payload, make_renter_headers, make_underwriting_agent_headers,
)


def test_renter_referenced_by_id_not_found_on_enrollment_create(api):
    """PRD §2.5: "a body field such as `landlord_id`, `property_id`, `renter_id`, `policy_id`,
    `claim_id`, `subrogation_case_id`, or `state_code` must likewise resolve before any state or
    business-rule check runs." "an unresolvable ... a renter yields `ERR_RENTER_NOT_FOUND` ...
    all at HTTP 404."

    Design: Corner/entities/renter_referenced_by_id_not_found_on_enrollment_create
    """
    landlord, prop, rule = setup_active_property()
    real_renter = create_renter()  # used only to authenticate the call
    payload = create_renter_enrollment_payload(prop["id"], NON_EXISTENT_UUID)
    res = api.create_renter_enrollment(payload, make_renter_headers(real_renter["id"]))
    validate_error(res, ApiErrorId.ERR_RENTER_NOT_FOUND, expected_status=404)


def test_renter_enrollment_get_not_found(api, underwriting_agent_headers):
    """PRD §2.5: "an unresolvable ... a renter enrollment yields
    `ERR_RENTER_ENROLLMENT_NOT_FOUND` ... all at HTTP 404."

    Design: Corner/entities/renter_enrollment_get_not_found
    """
    res = api.get_renter_enrollment(NON_EXISTENT_UUID, underwriting_agent_headers)
    validate_error(res, ApiErrorId.ERR_RENTER_ENROLLMENT_NOT_FOUND, expected_status=404)


def test_renter_enrollment_missing_required_field_rejected(api):
    """PRD §3.2: "the renter submits an enrollment against a specific unit: `property_id`,
    `renter_id`, a `payment_plan` of either `MONTHLY` or `ANNUAL_UPFRONT`, a
    `requested_coverage_limit_cents` (must be positive), `self_reported_annual_income_cents`
    (zero or greater), optionally `verified_annual_income_cents` and `employment_verified`
    (defaulting to false) when employer-side verification has already run, a
    `credit_proxy_score` between 300 and 850 inclusive, an optional `prior_eviction_count`
    (defaulting to 0, never negative), and the `lease_start_date`/`lease_end_date` pair..."

    Design: Corner/entities/renter_enrollment_missing_required_field_rejected
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    del payload["credit_proxy_score"]
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_renter_enrollment_blocked_by_pending_review_property(api):
    """PRD §3.2: "Three gates run before the application is even accepted, beyond the
    state-compliance checks in §2.7: the target property's `program_status` must be `ACTIVE`, or
    the request is rejected with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409)..."

    Design: Difficulty/cross_entity_state_dependency/renter_enrollment_blocked_by_pending_review_property
    """
    landlord = create_landlord()
    prop = create_property(landlord, state_code="CA")
    create_state_compliance_rule("CA")
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE, expected_status=409)
    after = validate_success(api.get_property(prop["id"], make_underwriting_agent_headers()), 200)
    assert after["program_status"] == "PENDING_REVIEW"


def test_renter_enrollment_blocked_by_terminated_property(api):
    """PRD §3.2: "the target property's `program_status` must be `ACTIVE`, or the request is
    rejected with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/renter_enrollment_blocked_by_pending_review_property
    """
    landlord, prop, rule = setup_active_property()
    prop = terminate_property(prop["id"])
    assert prop["program_status"] == "TERMINATED"
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE, expected_status=409)


def test_state_enrollment_prohibited_beats_property_not_active(api):
    """PRD §2.7: "Filing a new renter enrollment against a property whose state has no
    configured rule is rejected with `ERR_STATE_NOT_CONFIGURED` (HTTP 422); filing against a
    property whose state's rule has `enrollment_allowed` set to false is rejected with
    `ERR_STATE_ENROLLMENT_PROHIBITED` (HTTP 422). Both of these state-compliance checks apply
    specifically to new-enrollment creation and are evaluated before the property-active and
    lease-overlap checks described in §3.1 and §3.2."

    Design: Difficulty/priority_pair_validation_conflict/renter_enrollment_safety_beats_referential_on_unconfigured_and_unactivated_property
    """
    landlord = create_landlord()
    prop = create_property(landlord, state_code="NY")
    create_state_compliance_rule("NY", enrollment_allowed=False)
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_STATE_ENROLLMENT_PROHIBITED, expected_status=422)
    after = validate_success(api.get_property(prop["id"], make_underwriting_agent_headers()), 200)
    assert after["program_status"] == "PENDING_REVIEW"


def test_state_enrollment_prohibited_on_active_property_isolated(api):
    """PRD §2.7: "filing against a property whose state's rule has `enrollment_allowed` set to
    false is rejected with `ERR_STATE_ENROLLMENT_PROHIBITED` (HTTP 422)." This check applies
    regardless of whether the referential (property-active) check would independently pass.

    Design: Difficulty/priority_pair_validation_conflict/renter_enrollment_safety_beats_referential_on_unconfigured_and_unactivated_property
    """
    landlord, prop, rule = setup_active_property(state_code="NY", rule_overrides={"enrollment_allowed": False})
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_STATE_ENROLLMENT_PROHIBITED, expected_status=422)


def test_state_not_configured_blocks_enrollment_creation(api):
    """PRD §2.7: "Filing a new renter enrollment against a property whose state has no
    configured rule is rejected with `ERR_STATE_NOT_CONFIGURED` (HTTP 422)."

    Design: Corner/validations/state_not_configured_blocks_enrollment_creation
    """
    landlord = create_landlord()
    prop = create_property(landlord, state_code="TX")
    prop = activate_property(prop["id"])
    renter = create_renter()
    payload = create_renter_enrollment_payload(prop["id"], renter["id"])
    res = api.create_renter_enrollment(payload, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_STATE_NOT_CONFIGURED, expected_status=422)


def test_lease_interval_overlap_on_same_property_rejected(api):
    """PRD §3.2: "the requested `[lease_start_date, lease_end_date)` window — treated as a
    half-open interval, so a lease ending exactly when another begins does not count as
    overlapping — must not overlap any existing non-terminal policy's lease window on the same
    property, or the request is rejected with `ERR_LEASE_TERM_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/policy_lease_interval_overlap_on_same_property
    """
    landlord, prop, rule = setup_active_property()
    renter1 = create_renter()
    renter2 = create_renter()
    enrollment1 = create_renter_enrollment(prop["id"], renter1,
                              lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2027-07-01T00:00:00Z")
    submit_underwriting(enrollment1["id"], renter1["id"])  # auto-approves -> creates the Policy the overlap check compares against
    payload = create_renter_enrollment_payload(
        prop["id"], renter2["id"],
        lease_start_date="2026-12-01T00:00:00Z", lease_end_date="2027-12-01T00:00:00Z",
    )
    res = api.create_renter_enrollment(payload, make_renter_headers(renter2["id"]))
    validate_error(res, ApiErrorId.ERR_LEASE_TERM_OVERLAP, expected_status=409)


def test_lease_interval_starting_exactly_when_prior_ends_does_not_overlap(api):
    """PRD §3.2: "the requested `[lease_start_date, lease_end_date)` window — treated as a
    half-open interval, so a lease ending exactly when another begins does not count as
    overlapping..."

    Design: Difficulty/resource_temporal_overlap/policy_lease_interval_overlap_on_same_property
    """
    landlord, prop, rule = setup_active_property()
    renter1 = create_renter()
    renter2 = create_renter()
    enrollment1 = create_renter_enrollment(prop["id"], renter1,
                              lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2027-07-01T00:00:00Z")
    submit_underwriting(enrollment1["id"], renter1["id"])  # auto-approves -> Policy; adjacent window must NOT overlap it
    payload = create_renter_enrollment_payload(
        prop["id"], renter2["id"],
        lease_start_date="2027-07-01T00:00:00Z", lease_end_date="2028-07-01T00:00:00Z",
    )
    res = api.create_renter_enrollment(payload, make_renter_headers(renter2["id"]))
    enrollment2 = validate_success(res, 201)
    assert enrollment2["status"] == "PENDING_UNDERWRITING"


def test_risk_score_self_reported_vs_verified_diverge_tier(api):
    """PRD §3.2: "This score is computed twice under two variants that can legitimately
    diverge: the self-reported variant always runs, using `self_reported_annual_income_cents`,
    and is written to `risk_score_self_reported`; the verified variant runs only when
    `employment_verified` is true and `verified_annual_income_cents` has been supplied, using
    that verified figure instead, and is written to `risk_score_verified`." "Whichever of the two
    is "official" for gating purposes is `risk_score_verified` when it exists, falling back to
    `risk_score_self_reported` otherwise; the resulting `risk_tier` field on the enrollment
    reflects whichever score is official."

    Design: Difficulty/dual_variant_calc/underwriting_risk_score_self_reported_vs_verified_diverge_tier
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment = create_renter_enrollment(
        prop["id"], renter,
        requested_coverage_limit_cents=300000,
        self_reported_annual_income_cents=7200000,
        verified_annual_income_cents=4800000,
        employment_verified=True,
        credit_proxy_score=750,
        prior_eviction_count=0,
    )
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    assert enrollment["risk_score_self_reported"] == 7
    assert enrollment["risk_score_verified"] == 21
    assert enrollment["risk_tier"] == "MEDIUM"
    assert enrollment["status"] == "APPROVED"


def test_risk_score_verified_stays_null_when_employment_not_verified(api):
    """PRD §3.2: "the verified variant runs only when `employment_verified` is true and
    `verified_annual_income_cents` has been supplied, using that verified figure instead, and is
    written to `risk_score_verified`."

    Design: Difficulty/dual_variant_calc/underwriting_risk_score_self_reported_vs_verified_diverge_tier
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment = create_renter_enrollment(
        prop["id"], renter,
        requested_coverage_limit_cents=300000,
        self_reported_annual_income_cents=7200000,
        verified_annual_income_cents=4800000,
        employment_verified=False,
        credit_proxy_score=750,
        prior_eviction_count=0,
    )
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    assert enrollment["risk_score_self_reported"] == 7
    assert enrollment["risk_score_verified"] is None
    assert enrollment["risk_tier"] == "LOW"


def test_risk_score_exactly_at_auto_approve_threshold_is_inclusive(api):
    """PRD §3.2: "Submission then forks on that official score. An official score of 35 (the
    auto-approve threshold) or below routes straight to `APPROVED`, provided the monthly fee that
    would result...does not exceed the property's state fee ceiling..."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_auto_approve_threshold_is_inclusive
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment = create_renter_enrollment(
        prop["id"], renter,
        requested_coverage_limit_cents=200000,
        self_reported_annual_income_cents=900000,
        credit_proxy_score=850,
        prior_eviction_count=0,
    )
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    assert enrollment["risk_score_self_reported"] == 35
    assert enrollment["status"] == "APPROVED"


def test_risk_score_one_above_auto_approve_threshold_routes_manual_review(api):
    """PRD §3.2: "An official score above 35 routes instead to `MANUAL_REVIEW`, with no fee
    check at submission time."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_auto_approve_threshold_is_inclusive
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment = create_renter_enrollment(
        prop["id"], renter,
        requested_coverage_limit_cents=200000,
        self_reported_annual_income_cents=800000,
        credit_proxy_score=850,
        prior_eviction_count=0,
    )
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    assert enrollment["risk_score_self_reported"] == 36
    assert enrollment["status"] == "MANUAL_REVIEW"


def test_fee_exceeds_state_cap_blocks_auto_approval(api):
    """PRD §3.2: "provided the monthly fee that would result (computed exactly as described in
    §3.3, before any state-cap clamping) does not exceed the property's state fee ceiling — if it
    does, the submission is rejected with `ERR_FEE_EXCEEDS_STATE_CAP` (HTTP 422) rather than
    silently capping the fee."

    Design: Corner/validations/fee_exceeds_state_cap_blocks_auto_approval
    """
    landlord, prop, rule = setup_active_property(
        monthly_rent_cents=50000, rule_overrides={"max_monthly_fee_pct_of_rent": 0.10}
    )
    renter = create_renter()
    enrollment = create_renter_enrollment(
        prop["id"], renter,
        requested_coverage_limit_cents=1000000,
        self_reported_annual_income_cents=7200000,
        credit_proxy_score=750,
        prior_eviction_count=0,
    )
    res = api.submit_underwriting(enrollment["id"], make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_FEE_EXCEEDS_STATE_CAP, expected_status=422)
    after = validate_success(api.get_renter_enrollment(enrollment["id"], make_renter_headers(renter["id"])), 200)
    assert after["status"] == "PENDING_UNDERWRITING"


def test_decide_before_submit_underwriting_ever_ran_invalid_state(api):
    """PRD §3.2: "From `MANUAL_REVIEW`, an `UnderwritingAgent` issues a `decide` action of either
    `APPROVE`...or `DECLINE`..." PRD §2.5: "...then the state or transition-eligibility check for
    the target resource (`ERR_INVALID_STATE`)..."

    Design: Corner/state_machines/renter_enrollment_decide_from_pending_underwriting_invalid
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment = create_renter_enrollment(prop["id"], renter)
    assert enrollment["status"] == "PENDING_UNDERWRITING"
    res = api.decide_renter_enrollment(enrollment["id"], {"action": "APPROVE"}, make_underwriting_agent_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_renter_enrollment(enrollment["id"], make_renter_headers(renter["id"])), 200)
    assert after["status"] == "PENDING_UNDERWRITING"
