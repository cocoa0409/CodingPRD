"""Second-angle coverage for the deeper PRD rules.

Each deeper rule is asserted by at least two tests; the primary assertions live
in test_01..test_04, and these complementary tests pin a distinct, independently
PRD-derived facet of the same rule (e.g. the side-effect ledger entry behind a
fee, the positive control behind a precedence rejection, the assessment created
behind a penalty).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_inspection_payload,
    record_inspection_payload, create_endorsement_payload,
    create_transfer_payload, complete_transfer_payload,
    TEST_USERS,
    setup_issued_license, setup_zoning_cleared_application, setup_submitted_application,
    setup_delinquent_license, setup_active_license_with_transfer,
    setup_approved_transfer,
    get_license_fee_assessments, get_application_fee_assessments,
    assessments_of_kind, fee_sum, settle_all_license_fees, set_clock,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
ISSUER = make_licensing_officer_headers("officer-issuer")


# ─── dual_variant_calc ─────────────────────────────────────────────────────
def test_issuance_fee_creates_issuance_fee_assessment(api):
    """PRD §3.5: "The system opens an `ISSUANCE_FEE` assessment against the new
    license for the final fee, unsettled."

    Design: Difficulty/dual_variant_calc/license_fee_estimate_vs_final_diverge
    """
    ctx = setup_issued_license(
        category_overrides={
            "code": "FOOD_SERVICE2", "risk_tier": "HIGH", "activity_base_risk": 40,
            "required_inspection_count": 2, "requires_zoning_check": True,
            "term_months": 12, "allowed_zones": ["C1", "C2"]},
        application_overrides={"declared_employee_count": 12, "requested_zone_code": "C1"},
        passed_inspections=[
            {"inspector_user_id": "insp-1", "verified_employee_count": 15},
            {"inspector_user_id": "insp-1", "verified_employee_count": 15}],
    )
    ledger = get_license_fee_assessments(ctx["license"]["id"])
    issuance = assessments_of_kind(ledger, "ISSUANCE_FEE")
    assert len(issuance) == 1, issuance
    assert issuance[0]["amount"] == 825.00, issuance[0]
    assert issuance[0]["settled"] is False, issuance[0]


def test_provisional_risk_score_at_approval_is_base_only(api):
    """PRD §3.4: "This provisional variant scores the business before any
    inspection findings are aggregated: it starts from the activity's
    `activity_base_risk`, treats the open-violation count as zero (so the
    violation contribution is nothing at this stage), adds a delinquency weight
    only if the business is currently `DELINQUENT` and a prior-revocation weight
    only if its `prior_revocation_flag` is set, then clamps to 0 through 100."

    Design: Difficulty/dual_variant_calc/business_risk_provisional_vs_audited_diverge
    """
    # GOOD business, base 40, no failed-item aggregation at approval -> provisional 40.
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="PROV_HIGH", risk_tier="HIGH", activity_base_risk=40,
            required_inspection_count=1, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Prov Co", owner_name="PR",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "insp-p"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 1, 5), INSPECTOR))
    get_success_data(api.approve_application(app["id"], OFFICER))

    biz_after = get_success_data(api.get_business(biz["id"], OFFICER))
    assert biz_after["compliance_risk_score"] == 40, biz_after["compliance_risk_score"]


# ─── combinatorial_formula ─────────────────────────────────────────────────
def test_issuance_fee_variance_flag_persists_into_final_fee(api):
    """PRD §3.3: "an application carrying the variance surcharge keeps that 150.00
    in every later fee that re-reads the variance flag."
    PRD §3.5: "plus the 150.00 zoning variance surcharge when the application's
    `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise".

    Design: Difficulty/combinatorial_formula/issuance_fee_nonlinear_multi_input
    """
    # Same MEDIUM/variance/1-inspection setup; assert the application stays
    # VARIANCE_REQUIRED through issuance so the 150 surcharge is in final_fee 505.
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="RETAIL_MED2", risk_tier="MEDIUM", activity_base_risk=20,
            required_inspection_count=1, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Var Shop2", owner_name="V2",
                                zone_code="I2"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=4, requested_zone_code="I2"), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "insp-v"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 6, 0), INSPECTOR))
    get_success_data(api.approve_application(app["id"], OFFICER))
    lic = validate_success(api.issue_application(app["id"], ISSUER), 201)

    app_after = get_success_data(api.get_application(app["id"], OFFICER))
    assert app_after["zoning_status"] == "VARIANCE_REQUIRED", app_after["zoning_status"]
    assert lic["final_fee"] == 505.00, lic["final_fee"]


def test_variance_recompute_raises_application_fee_assessment(api):
    """PRD §3.3: "on this branch the system recomputes `estimated_fee` to include
    the 150.00 zoning variance surcharge and correspondingly raises the open
    `APPLICATION_FEE` assessment's `amount` to match the new estimate."

    Design: Difficulty/combinatorial_formula/variance_surcharge_recompute_order_pinned
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="BAR_HIGH2", risk_tier="HIGH", activity_base_risk=35,
            required_inspection_count=0, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Late Bar2", owner_name="L2",
                                zone_code="I9"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=12, requested_zone_code="I9"), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))

    ledger = get_application_fee_assessments(app["id"])
    app_fees = assessments_of_kind(ledger, "APPLICATION_FEE")
    assert any(a["amount"] == 810.00 for a in app_fees), app_fees


# ─── non_linear_state_machine ──────────────────────────────────────────────
def test_in_cycle_renewal_active_to_active_advances_expiry(api):
    """PRD §3.6: "An in-cycle renewal from `ACTIVE` creates and immediately
    settles a `RENEWAL_FEE` and carries no penalty."
    PRD §3.6: "Every renewal advances `expires_on` by the category's `term_months`
    anchored to the current `expires_on`, increments `renewal_count` by one".

    Design: Difficulty/non_linear_state_machine/license_delinquent_renew_active_cycle
    """
    # ACTIVE -> ACTIVE renewal inside the window (no delinquency), distinct from
    # the DELINQUENT->ACTIVE leg asserted in test_02.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "CYCLE_MED2", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    set_clock("2027-05-15T00:00:00Z")  # within 60-day window before 2027-06-01
    renewed = validate_success(api.renew_license(lic["id"], biz_h), 200)
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1, renewed["renewal_count"]
    assert renewed["expires_on"].startswith("2028-06-01"), renewed["expires_on"]


def test_variance_branch_recomputes_fee_clear_branch_does_not(api):
    """PRD §3.3: "Both the cleared branch and the variance branch are legitimate
    paths toward approval; they differ only in the surcharge already baked into the
    assessment."
    PRD §3.3: "it advances `SUBMITTED → ZONING_CLEARED` and its `zoning_status` is
    set to `CLEARED`."

    Design: Difficulty/non_linear_state_machine/application_branch_zoning_clear_vs_variance
    """
    # Clear branch leaves estimated_fee unchanged (no 150 surcharge).
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="FORK_CAT2", risk_tier="HIGH", activity_base_risk=30,
            required_inspection_count=0, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Clear Co", owner_name="CL",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=1, requested_zone_code="C1"), biz_h))
    submitted = get_success_data(api.submit_application(app["id"], biz_h))  # 600 + 5 = 605
    cleared = validate_success(api.zoning_check_application(app["id"], OFFICER), 200)
    assert cleared["status"] == "ZONING_CLEARED"
    assert cleared["estimated_fee"] == submitted["estimated_fee"] == 605.00, cleared


# ─── transitive_cascade ────────────────────────────────────────────────────
def test_revoke_voids_active_endorsement_specifically(api):
    """PRD §3.7: "First, every endorsement of the license currently in `ACTIVE` or
    `SUSPENDED` is driven to `VOIDED`."

    Design: Difficulty/transitive_cascade/revoke_cascade_endorsement_transfer_business_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "REVK_MED2", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    end = get_success_data(api.create_endorsement(
        create_endorsement_payload(lic["id"], kind="HAZMAT_HANDLING",
                                   condition_text="Storage limit"), OFFICER))
    set_clock("2027-09-10T00:00:00Z")
    get_success_data(api.assess_delinquency(lic["id"], OFFICER))
    get_success_data(api.revoke_license(lic["id"], OFFICER))

    end_after = get_success_data(api.get_endorsement(end["id"], OFFICER))
    assert end_after["status"] == "VOIDED", end_after["status"]


def test_delinquency_sets_business_delinquent_standing(api):
    """PRD §3.6: "It then sets the holding `Business`'s `standing` to `DELINQUENT`
    and recomputes its `compliance_risk_score` under the audited variant."

    Design: Difficulty/transitive_cascade/delinquency_cascade_business_standing_riskscore_depth2
    """
    ctx = setup_delinquent_license(risk_tier="LOW",
                                   category_overrides={"activity_base_risk": 10},
                                   overdue_clock="2027-07-15T00:00:00Z")
    biz_after = get_success_data(api.get_business(ctx["business"]["id"], OFFICER))
    assert biz_after["standing"] == "DELINQUENT", biz_after["standing"]
    # LOW base 10 + delinquency 20 = 30.
    assert biz_after["compliance_risk_score"] == 30, biz_after["compliance_risk_score"]


# ─── priority_pair_validation_conflict ─────────────────────────────────────
def test_issue_with_distinct_officer_succeeds(api):
    """PRD §3.5: "the issuing officer's `X-User-ID` must differ from every
    `inspector_user_id` recorded on any inspection of this application: an officer
    who inspected the premises may not also issue its license."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_inspection_prereq_on_issue
    """
    # Same setup but issuer id differs from inspector -> issuance succeeds (the
    # positive control that the segregation check, not some other gate, was the
    # blocker in the negative test).
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="SOD_OK", risk_tier="LOW", activity_base_risk=10,
            required_inspection_count=1, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="SOD OK Co", owner_name="SK",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "inspector-only"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 1, 0), INSPECTOR))
    get_success_data(api.approve_application(app["id"], OFFICER))

    lic = validate_success(
        api.issue_application(app["id"], make_licensing_officer_headers("a-different-officer")), 201)
    assert lic["status"] == "ACTIVE"


def test_surrender_active_no_fees_succeeds_when_state_valid(api):
    """PRD §3.7: "Surrender is the voluntary terminus, performed by an `Applicant`
    on an `ACTIVE` license, advancing it `ACTIVE → SURRENDERED`. It is gated
    fiscally: a license may be surrendered only when it has no outstanding
    unsettled `FeeAssessment`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_surrender
    """
    # Positive control distinguishing the state gate from the fiscal gate: an
    # ACTIVE license whose only assessment is settled surrenders cleanly, proving
    # the DELINQUENT rejection in test_03 was the state tier, not the fiscal tier.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "SURR_OK", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    settle_all_license_fees(lic["id"], biz_h)
    surrendered = validate_success(api.surrender_license(lic["id"], biz_h), 200)
    assert surrendered["status"] == "SURRENDERED", surrendered["status"]


# ─── boundary_precision_check ──────────────────────────────────────────────
def test_delinquency_day31_tier_a_penalty(api):
    """PRD §3.6: "If it is greater than 30 but at most 60 days, the rate is 10
    percent. ... The penalty is that rate multiplied by the base renewal fee for
    the license's risk tier — 200.00 for `LOW`, 480.00 for `MEDIUM`, 900.00 for
    `HIGH` — rounded to two decimal places using round-half-up."

    Design: Difficulty/boundary_precision_check/delinquency_grace_boundary_day30_vs_day31
    """
    # X+1 side of the grace boundary: 31 days overdue -> tier A 10% of 480 = 48.00.
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-07-02T00:00:00Z")  # 31 days
    lic = ctx["license"]
    ledger = get_license_fee_assessments(lic["id"])
    penalties = assessments_of_kind(ledger, "DELINQUENCY_PENALTY")
    assert len(penalties) == 1 and penalties[0]["amount"] == 48.00, penalties


def test_inspection_prereq_met_allows_approval(api):
    """PRD §3.4: "the count of this application's inspections whose `result` is
    `PASSED` must be at least the category's `required_inspection_count`."

    Design: Difficulty/boundary_precision_check/inspection_prereq_empty_set_zero_count_boundary
    """
    # X side of the count boundary: exactly required_inspection_count=1 PASSED ->
    # approval succeeds (complement to the zero-count rejection in test_03).
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="PREREQ_OK", risk_tier="LOW", activity_base_risk=10,
            required_inspection_count=1, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Prereq OK", owner_name="PO",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "insp-ok"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 1, 0), INSPECTOR))
    approved = validate_success(api.approve_application(app["id"], OFFICER), 200)
    assert approved["status"] == "APPROVED", approved["status"]


# ─── cross_entity_state_dependency ─────────────────────────────────────────
def test_transfer_approve_requires_target_business_good_standing(api):
    """PRD §3.9: "A `LicensingOfficer` approves a requested transfer (`REQUESTED →
    APPROVED`), which additionally requires that the license be `ACTIVE` and that
    the business named by `to_business_id` be in `GOOD` standing — a receiving
    business not in good standing causes `ERR_BUSINESS_NOT_IN_GOOD_STANDING` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_business_good_standing
    """
    # Same Application/Business standing gate, exercised on the transfer-approve
    # path where the receiving business is not GOOD.
    set_clock("2026-06-01T00:00:00Z")
    # Seller license (kept ACTIVE).
    seller_ctx = setup_issued_license(category_overrides={
        "code": "XSELL_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    seller = seller_ctx["business"]
    seller_lic = seller_ctx["license"]
    seller_h = seller_ctx["biz_headers"]
    # Buyer business driven DELINQUENT via its own license.
    buyer_ctx = setup_issued_license(category_overrides={
        "code": "XBUY_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    buyer = buyer_ctx["business"]
    set_clock("2027-07-15T00:00:00Z")
    get_success_data(api.assess_delinquency(buyer_ctx["license"]["id"], OFFICER))
    set_clock("2026-06-02T00:00:00Z")  # back to a time the seller license is ACTIVE

    tr = get_success_data(api.create_transfer(
        create_transfer_payload(seller_lic["id"], seller["id"], buyer["id"]), seller_h))
    res = api.approve_transfer(tr["id"], OFFICER)
    validate_error(res, "ERR_BUSINESS_NOT_IN_GOOD_STANDING", expected_status=409)


def test_transfer_request_blocked_when_license_not_active(api):
    """PRD §3.9: "A transfer may only target a license that is `ACTIVE`; at
    request, approval, and completion, a license that is `DELINQUENT`, `REVOKED`,
    or `SURRENDERED` causes rejection with `ERR_LICENSE_NOT_TRANSFERABLE` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_license_active
    """
    # Same OwnershipTransfer<-License dependency, exercised at the request edge.
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-07-15T00:00:00Z")
    lic = ctx["license"]
    seller = ctx["business"]
    seller_h = ctx["biz_headers"]
    buyer = get_success_data(api.create_business(
        create_business_payload(legal_name="Buyer X", owner_name="BX",
                                zone_code="C1"), APPLICANT))
    res = api.create_transfer(
        create_transfer_payload(lic["id"], seller["id"], buyer["id"]), seller_h)
    validate_error(res, "ERR_LICENSE_NOT_TRANSFERABLE", expected_status=409)


# ─── resource_temporal_overlap ─────────────────────────────────────────────
def test_renewal_window_open_at_lower_bound_succeeds(api):
    """PRD §3.6: "Renewal is only permitted once the renewal window has opened —
    that is, when the current clock instant is at or after the license's
    `expires_on` minus the renewal window of 60 days."

    Design: Difficulty/resource_temporal_overlap/renewal_window_half_open_lower_bound
    """
    # X side of the half-open bound: exactly expires_on - 60 days = 2027-04-02,
    # the window is OPEN, so renewal succeeds (complement to the day-61 rejection).
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "WIN_MED2", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    set_clock("2027-04-02T00:00:00Z")  # expires 2027-06-01 minus 60 days
    renewed = validate_success(api.renew_license(lic["id"], biz_h), 200)
    assert renewed["status"] == "ACTIVE", renewed["status"]
    assert renewed["renewal_count"] == 1, renewed["renewal_count"]


def test_revocation_succeeds_past_threshold(api):
    """PRD §3.7: "revocation is only permitted once `days_overdue` exceeds the
    revocation threshold of 90 days".
    PRD §3.7: "Revocation is the punitive terminus, performed by a
    `LicensingOfficer` on a `DELINQUENT` license, advancing it `DELINQUENT →
    REVOKED`."

    Design: Difficulty/resource_temporal_overlap/revocation_threshold_closed_upper_interval
    """
    # X+1 side: 101 days overdue (2027-09-10) -> over threshold, revoke succeeds.
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-09-10T00:00:00Z")
    lic = ctx["license"]
    revoked = validate_success(api.revoke_license(lic["id"], OFFICER), 200)
    assert revoked["status"] == "REVOKED", revoked["status"]


# ─── compensating_invariant ────────────────────────────────────────────────
def test_withdraw_reverses_application_fee_net_zero(api):
    """PRD §3.2: "If at the moment of withdrawal an unsettled `APPLICATION_FEE`
    assessment exists, the system appends a `REVERSAL` assessment for the negative
    of the estimated fee so the applicant owes nothing for an application they
    walked away from."

    Design: Difficulty/compensating_invariant/reject_reverses_application_fee_net_zero
    """
    # Same net-zero ledger conservation, reached via the withdraw path instead of
    # reject — both append a REVERSAL of -estimated_fee.
    ctx = setup_submitted_application(
        category_overrides={
            "code": "WDR_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
            "required_inspection_count": 0, "requires_zoning_check": False,
            "term_months": 12, "allowed_zones": ["C1"]},
        application_overrides={"declared_employee_count": 4, "requested_zone_code": "C1"},
    )
    app = ctx["application"]
    biz_h = ctx["biz_headers"]
    withdrawn = validate_success(api.withdraw_application(app["id"], biz_h), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    ledger = get_application_fee_assessments(app["id"])
    assert fee_sum(ledger) == 0.00, fee_sum(ledger)
    reversals = assessments_of_kind(ledger, "REVERSAL")
    assert len(reversals) == 1 and reversals[0]["amount"] == -270.00, reversals


def test_completed_transfer_charges_positive_fee(api):
    """PRD §3.9: "On completion the license's `business_id` is reassigned to
    `to_business_id` (only the holding business moves; the owner-of-record name is
    not copied), the system computes the `transfer_fee` and opens a `TRANSFER_FEE`
    assessment against the license for it, and both the license's `version` and the
    transfer's `version` advance."

    Design: Difficulty/compensating_invariant/transfer_cancel_zeroes_transfer_fee_quantity
    """
    # The conserved transfer_fee quantity is positive only on COMPLETE; this is the
    # forward action the cancel test pins back to zero. HIGH -> 500.00.
    ctx = setup_approved_transfer(risk_tier="HIGH")
    completed = validate_success(api.complete_transfer(
        ctx["transfer"]["id"],
        complete_transfer_payload(ctx["license_version"]), OFFICER), 200)
    assert completed["transfer_fee"] == 500.00, completed["transfer_fee"]
    ledger = get_license_fee_assessments(ctx["license"]["id"])
    tf = assessments_of_kind(ledger, "TRANSFER_FEE")
    assert len(tf) == 1 and tf[0]["amount"] == 500.00, tf
