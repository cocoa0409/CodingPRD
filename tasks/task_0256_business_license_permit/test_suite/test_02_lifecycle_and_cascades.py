"""License/application lifecycle shapes and the terminal cascades.

Covers difficulty rules non_linear_state_machine and transitive_cascade, the
business-risk dual-variant instance, plus corner endpoint/cross-cutting
instances that share these multi-step setups.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_endorsement_payload,
    create_transfer_payload, complete_transfer_payload,
    TEST_USERS,
    setup_issued_license, setup_delinquent_license,
    get_license_fee_assessments, assessments_of_kind, settle_all_license_fees,
    set_clock,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
ISSUER = make_licensing_officer_headers("officer-issuer")


def test_license_delinquent_then_renew_cycle(api):
    """PRD §3.6: "A license may be renewed by its `Applicant` from either
    `ACTIVE` (an in-cycle renewal, `ACTIVE → ACTIVE`) or `DELINQUENT` (a recovery
    renewal, `DELINQUENT → ACTIVE`)."
    PRD §3.6: "Every renewal advances `expires_on` by the category's
    `term_months` anchored to the current `expires_on`, increments
    `renewal_count` by one, and settles the license's outstanding `RENEWAL_FEE`
    and `DELINQUENCY_PENALTY` assessments."

    Design: Difficulty/non_linear_state_machine/license_delinquent_renew_active_cycle
    """
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-08-02T00:00:00Z")
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    assert lic["status"] == "DELINQUENT"
    # Settle outstanding RENEWAL_FEE + DELINQUENCY_PENALTY, then renew within window.
    settle_all_license_fees(lic["id"], biz_h)
    renewed = validate_success(api.renew_license(lic["id"], biz_h), 200)
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1, renewed["renewal_count"]


def test_application_zoning_branch_clear_vs_variance(api):
    """PRD §3.3: "When the `requested_zone_code` is one of the category's
    `allowed_zones`, the application clears: it advances `SUBMITTED →
    ZONING_CLEARED` and its `zoning_status` is set to `CLEARED`."
    PRD §3.3: "If the category's `requires_zoning_check` is true, the application
    takes the variance branch, advancing `SUBMITTED → VARIANCE_REQUIRED` with its
    `zoning_status` set to `VARIANCE_REQUIRED`".

    Design: Difficulty/non_linear_state_machine/application_branch_zoning_clear_vs_variance
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="FORK_CAT", risk_tier="HIGH", activity_base_risk=30,
            required_inspection_count=0, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz_a = get_success_data(api.create_business(
        create_business_payload(legal_name="Fork Biz A", owner_name="FA",
                                zone_code="C1"), APPLICANT))
    biz_b = get_success_data(api.create_business(
        create_business_payload(legal_name="Fork Biz B", owner_name="FB",
                                zone_code="Z9"), APPLICANT))
    app_a = get_success_data(api.create_application(
        create_application_payload(biz_a["id"], cat["id"],
                                   declared_employee_count=1, requested_zone_code="C1"),
        make_applicant_headers(biz_a["id"])))
    get_success_data(api.submit_application(app_a["id"], make_applicant_headers(biz_a["id"])))
    app_b = get_success_data(api.create_application(
        create_application_payload(biz_b["id"], cat["id"],
                                   declared_employee_count=1, requested_zone_code="Z9"),
        make_applicant_headers(biz_b["id"])))
    get_success_data(api.submit_application(app_b["id"], make_applicant_headers(biz_b["id"])))

    res_a = validate_success(api.zoning_check_application(app_a["id"], OFFICER), 200)
    res_b = validate_success(api.zoning_check_application(app_b["id"], OFFICER), 200)
    assert res_a["status"] == "ZONING_CLEARED", res_a["status"]
    assert res_b["status"] == "VARIANCE_REQUIRED", res_b["status"]


def test_revoke_cascade_depth3(api):
    """PRD §3.7: "Revocation triggers a three-level cascade. First, every
    endorsement of the license currently in `ACTIVE` or `SUSPENDED` is driven to
    `VOIDED`. Second, every ownership transfer of the license currently in
    `REQUESTED` or `APPROVED` is cancelled, and that cancellation itself sets the
    transfer's `transfer_fee` to zero. Third, the holding business is set to
    `REVOKED` standing, its `prior_revocation_flag` is set to true, and its
    `compliance_risk_score` is recomputed under the audited variant."

    Design: Difficulty/transitive_cascade/revoke_cascade_endorsement_transfer_business_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "REVK_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    seller = ctx["business"]
    seller_h = ctx["biz_headers"]
    buyer = get_success_data(api.create_business(
        create_business_payload(legal_name="Buyer Co", owner_name="BC",
                                zone_code="C1"), APPLICANT))
    end = get_success_data(api.create_endorsement(
        create_endorsement_payload(lic["id"], kind="LATE_HOURS",
                                   condition_text="Close by 02:00"), OFFICER))
    tr = get_success_data(api.create_transfer(
        create_transfer_payload(lic["id"], seller["id"], buyer["id"]), seller_h))
    set_clock("2027-09-10T00:00:00Z")
    get_success_data(api.assess_delinquency(lic["id"], OFFICER))

    revoked = validate_success(api.revoke_license(lic["id"], OFFICER), 200)
    assert revoked["status"] == "REVOKED"

    end_after = get_success_data(api.get_endorsement(end["id"], OFFICER))
    assert end_after["status"] == "VOIDED", end_after["status"]
    tr_after = get_success_data(api.get_transfer(tr["id"], OFFICER))
    assert tr_after["status"] == "CANCELLED", tr_after["status"]
    assert tr_after["transfer_fee"] == 0, tr_after["transfer_fee"]
    biz_after = get_success_data(api.get_business(seller["id"], OFFICER))
    assert biz_after["standing"] == "REVOKED", biz_after["standing"]
    assert biz_after["prior_revocation_flag"] is True, biz_after["prior_revocation_flag"]


def test_delinquency_cascade_business_standing_riskscore(api):
    """PRD §3.6: "It then sets the holding `Business`'s `standing` to
    `DELINQUENT` and recomputes its `compliance_risk_score` under the audited
    variant."
    PRD §3.6: "The score is the activity's `activity_base_risk`, plus the
    violation contribution — 5 per open violation, but that violation
    contribution is capped at 30 so additional violations beyond the cap add
    nothing — plus 20 if the business's `standing` is `DELINQUENT`, plus 10 if
    its `prior_revocation_flag` is set, with the final sum clamped to the
    inclusive range 0 through 100."

    Design: Difficulty/transitive_cascade/delinquency_cascade_business_standing_riskscore_depth2
    """
    # LOW activity_base_risk=10, no failed items -> audited = 10 + 0 + 20 (delinquency) = 30.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "DELQ_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz = ctx["business"]
    set_clock("2027-07-15T00:00:00Z")
    delinq = validate_success(api.assess_delinquency(lic["id"], OFFICER), 200)
    assert delinq["status"] == "DELINQUENT"

    biz_after = get_success_data(api.get_business(biz["id"], OFFICER))
    assert biz_after["standing"] == "DELINQUENT", biz_after["standing"]
    assert biz_after["compliance_risk_score"] == 30, biz_after["compliance_risk_score"]


def test_business_risk_provisional_vs_audited_diverge(api):
    """PRD §3.4: "This provisional variant scores the business before any
    inspection findings are aggregated: it starts from the activity's
    `activity_base_risk`, treats the open-violation count as zero (so the
    violation contribution is nothing at this stage), adds a delinquency weight
    only if the business is currently `DELINQUENT` and a prior-revocation weight
    only if its `prior_revocation_flag` is set, then clamps to 0 through 100."
    PRD §3.6: "Where the provisional variant treats the open-violation count as
    zero, the audited variant sets the open-violation count to the sum of
    `failed_item_count` across this business's inspections. The score is the
    activity's `activity_base_risk`, plus the violation contribution — 5 per open
    violation, but that violation contribution is capped at 30 so additional
    violations beyond the cap add nothing — plus 20 if the business's `standing`
    is `DELINQUENT`, plus 10 if its `prior_revocation_flag` is set, with the
    final sum clamped to the inclusive range 0 through 100."

    Design: Difficulty/dual_variant_calc/business_risk_provisional_vs_audited_diverge
    """
    # HIGH base 40, 1 inspection failed_item_count=3.
    # Provisional at approval: 40 + 0 + 0 = 40. Audited at delinquency:
    # 40 + min(5*3,30)=15 + 20 (delinquency) = 75.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(
        category_overrides={
            "code": "HAZ_PLANT", "risk_tier": "HIGH", "activity_base_risk": 40,
            "required_inspection_count": 1, "requires_zoning_check": True,
            "term_months": 12, "allowed_zones": ["C1"]},
        application_overrides={"declared_employee_count": 4, "requested_zone_code": "C1"},
        passed_inspections=[{"inspector_user_id": "insp-9",
                             "verified_employee_count": 4, "failed_item_count": 3}],
    )
    lic = ctx["license"]
    biz = ctx["business"]
    set_clock("2027-08-02T00:00:00Z")
    delinq = validate_success(api.assess_delinquency(lic["id"], OFFICER), 200)
    assert delinq["status"] == "DELINQUENT"

    biz_after = get_success_data(api.get_business(biz["id"], OFFICER))
    assert biz_after["compliance_risk_score"] == 75, biz_after["compliance_risk_score"]
    assert biz_after["standing"] == "DELINQUENT", biz_after["standing"]


def test_renewal_settles_outstanding_and_advances_expiry(api):
    """PRD §3.6: "Every renewal advances `expires_on` by the category's
    `term_months` anchored to the current `expires_on`, increments
    `renewal_count` by one, and settles the license's outstanding `RENEWAL_FEE`
    and `DELINQUENCY_PENALTY` assessments."

    Design: Corner/cross_cutting_complexity_layers/renewal_settles_outstanding_assessments_reconciled
    """
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-08-02T00:00:00Z")
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    renewed = validate_success(api.renew_license(lic["id"], biz_h), 200)
    assert renewed["status"] == "ACTIVE"
    # expires_on advanced 12 months from 2027-06-01 -> 2028-06-01.
    assert renewed["expires_on"].startswith("2028-06-01"), renewed["expires_on"]

    ledger = get_license_fee_assessments(lic["id"])
    relevant = [a for a in ledger if a["kind"] in ("RENEWAL_FEE", "DELINQUENCY_PENALTY")]
    assert relevant, "expected RENEWAL_FEE/DELINQUENCY_PENALTY on the ledger"
    assert all(a["settled"] is True for a in relevant), relevant


def test_endorsement_suspend_reinstate_round_trip(api):
    """PRD §3.8: "A `LicensingOfficer` may suspend an `ACTIVE` endorsement
    (`ACTIVE → SUSPENDED`), which requires that the parent license be in `ACTIVE`
    or `DELINQUENT`; may reinstate a `SUSPENDED` endorsement (`SUSPENDED →
    ACTIVE`), which requires that the parent license be `ACTIVE`".
    PRD §3.8: "Each of these transitions advances the endorsement's `version`."

    Design: Corner/endpoints/endorsement_suspend_then_reinstate_round_trip
    """
    ctx = setup_issued_license(category_overrides={
        "code": "END_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    end = get_success_data(api.create_endorsement(
        create_endorsement_payload(lic["id"], kind="OUTDOOR_SEATING",
                                   condition_text="Patio only"), OFFICER))
    assert end["version"] == 1, end["version"]
    get_success_data(api.suspend_endorsement(end["id"], OFFICER))
    reinstated = validate_success(api.reinstate_endorsement(end["id"], OFFICER), 200)
    assert reinstated["status"] == "ACTIVE", reinstated["status"]
    assert reinstated["version"] == 3, reinstated["version"]
