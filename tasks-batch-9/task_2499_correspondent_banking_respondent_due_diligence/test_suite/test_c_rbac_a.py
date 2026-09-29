"""Corner queue - section rbac, part A: exclusive and shared operations."""
from test_helpers import (
    ANALYST_ID,
    ApiErrorId,
    OFFICER_ID,
    approve_plan,
    assert_instant_equals,
    calibrate,
    corridor,
    draft_plan,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    new_respondent,
    open_profile,
    progress_plan,
    read_payment,
    read_plan,
    read_refresh,
    read_respondent,
    respondent_version,
    schedule_refresh,
    score_respondent,
    submit_payment,
    submit_plan,
    setup_approved_respondent,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, COMMITTEE, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_respondent_approval_and_decline_belong_to_the_committee_alone(api):
    """Every other role is stopped at the role gate on a respondent that could never be
    approved on the merits, and the committee is stopped one rung lower - on the state - which
    is what proves the role check runs first.

    Design: Corner/rbac/respondent_approval_and_decline_belong_to_the_committee_alone
    """
    _de()
    respondent = new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert respondent["dd_state"] == "PROSPECT"
    version_before = respondent_version(rid)

    denied = [
        (ANALYST, {"action": "APPROVE"}),
        (RM, {"action": "APPROVE"}),
        (OFFICER, {"action": "APPROVE"}),
        (ADMIN, {"action": "APPROVE"}),
        (make_respondent_headers(rid), {"action": "DECLINE"}),
    ]
    for headers, payload in denied:
        validate_error(
            api.decide_committee(rid, payload, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )

    permitted = api.decide_committee(rid, {"action": "APPROVE"}, COMMITTEE)
    validate_error(permitted, ApiErrorId.ERR_INVALID_RESPONDENT_STATE, expected_status=409)

    stored = read_respondent(rid)
    assert stored["dd_state"] == "PROSPECT"
    assert stored["version"] == version_before


def test_shared_operations_accept_either_declared_role(api):
    """Three endpoints that name two roles each are driven once per role and succeed both
    times, so shared operations really are shared and no call answers 403.

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    germany = validate_success(
        api.create_jurisdiction_profile(
            {"jurisdiction_code": "DE", "name": "Germany", "basel_aml_index": 4.0,
             "corridor_risk_weight": 1.0},
            OFFICER,
        ),
        expected_status=201,
    )
    japan = validate_success(
        api.create_jurisdiction_profile(
            {"jurisdiction_code": "JP", "name": "Japan", "basel_aml_index": 3.0,
             "corridor_risk_weight": 1.0},
            ADMIN,
        ),
        expected_status=201,
    )
    assert germany["jurisdiction_code"] == "DE"
    assert japan["jurisdiction_code"] == "JP"

    licensing = {"license_status": "ACTIVE", "regulator_standing": "GOOD_STANDING",
                 "regulator_name": "BaFin"}
    for index, headers in enumerate((ANALYST, ADMIN)):
        prospect = new_respondent(
            "DE", legal_name=f"Prospekt Bank {index} AG", swift_bic=f"PRSPDEF{index}",
            expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        )
        verified = validate_success(
            api.verify_licensing(prospect["id"], licensing, headers)
        )
        assert verified["dd_state"] == "DD_IN_PROGRESS"

    for index, headers in enumerate((OFFICER, ANALYST)):
        bundle = setup_approved_respondent(
            "DE", legal_name=f"Approved Bank {index} AG", swift_bic=f"APRVDEF{index}",
            expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        )
        restricted = validate_success(
            api.restrict_respondent(
                bundle["respondent"]["id"],
                {"action": "RESTRICT", "restriction_reason": "OFFICER_ACTION",
                 "payment_posture": "BLOCKED"},
                headers,
            )
        )
        assert restricted["dd_state"] == "RESTRICTED"
        assert restricted["restriction_reason"] == "OFFICER_ACTION"
        assert restricted["payment_posture"] == "BLOCKED"


def test_the_logical_clock_and_the_refresh_sweep_are_platform_admin_only(api):
    """The two operator endpoints outside the domain workflow are refused to the compliance
    roles that drive refresh cycles by hand, and the admin's dry run then writes nothing at all.

    Design: Corner/rbac/the_logical_clock_and_the_refresh_sweep_are_platform_admin_only
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    cycle = schedule_refresh(rid, "2026-08-01T00:00:00Z", "2026-10-30T00:00:00Z")
    assert cycle["state"] == "SCHEDULED"

    for headers in (ANALYST, OFFICER):
        validate_error(
            api.run_sweep({"dry_run": False}, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
    validate_error(
        api.set_clock({"current_utc": "2026-09-02T00:00:00Z"}, ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    swept = validate_success(api.run_sweep({"dry_run": True}, ADMIN))
    assert swept == []

    stored = read_refresh(cycle["id"])
    assert stored["state"] == "SCHEDULED"
    assert stored["lapsed_at"] is None
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"


def test_screening_decisions_belong_to_the_sanctions_officer_alone(api):
    """The two roles that may submit payments and the analyst who calibrated the very threshold
    that held this one are all refused, so the denial cannot be read as lack of involvement.

    Design: Corner/rbac/screening_decisions_belong_to_the_sanctions_officer_alone
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    assert bundle["respondent"]["payment_posture"] == "OPEN"
    profile = open_profile(rid, [corridor("DE", 500000.00, 100)])
    calibrated = calibrate(profile["id"])
    assert calibrated["hold_threshold_usd"] == 82225.00

    instruction = submit_payment(
        rid, "DE", "DE", amount_usd=100000.00, purpose_code="TRADE_SETTLEMENT"
    )
    assert instruction["screening_state"] == "HELD_FOR_REVIEW"
    assert instruction["hold_reason"] == "AMOUNT_THRESHOLD"
    assert instruction["hold_threshold_applied"] == 82225.00

    denied = [
        (RM, {"action": "RELEASE", "decision_reason": "CLEARED_AFTER_REVIEW"}),
        (ANALYST, {"action": "RELEASE", "decision_reason": "CLEARED_AFTER_REVIEW"}),
        (ADMIN, {"action": "REJECT", "decision_reason": "SANCTIONS_MATCH"}),
        (make_respondent_headers(rid),
         {"action": "RELEASE", "decision_reason": "CLEARED_AFTER_REVIEW"}),
    ]
    for headers, payload in denied:
        validate_error(
            api.decide_screening(instruction["id"], payload, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )

    held = read_payment(instruction["id"])
    assert held["screening_state"] == "HELD_FOR_REVIEW"
    assert held["decided_by_user_id"] is None

    released = validate_success(
        api.decide_screening(
            instruction["id"],
            {"action": "RELEASE", "decision_reason": "CLEARED_AFTER_REVIEW"},
            OFFICER,
        )
    )
    assert released["screening_state"] == "RELEASED"
    assert released["decision_reason"] == "CLEARED_AFTER_REVIEW"
    assert released["decided_by_user_id"] == OFFICER_ID
    assert_instant_equals(released["decided_at"], "2026-08-01T00:00:00Z")


def test_risk_scoring_and_calibration_belong_to_the_compliance_analyst_alone(api):
    """The two analytical write capabilities are refused to every other role including the
    committee that will later decide on the score, and the refusals leave the respondent
    unrated and the profile provisional so the analyst's own run has something to change.

    Design: Corner/rbac/risk_scoring_and_calibration_belong_to_the_compliance_analyst_alone
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert respondent["risk_rating"] == "UNRATED"
    assert respondent["last_risk_assessed_at"] is None
    profile = open_profile(rid, [corridor("DE", 500000.00, 100)])
    assert profile["calibration_state"] == "PROVISIONAL"

    for headers in (RM, OFFICER, COMMITTEE, ADMIN):
        validate_error(
            api.assess_risk(rid, {"variant": "ONBOARDING_PROVISIONAL"}, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
    unrated = read_respondent(rid)
    assert unrated["risk_rating"] == "UNRATED"
    assert unrated["dd_state"] == "DD_IN_PROGRESS"
    assert unrated["last_risk_assessed_at"] is None
    assert unrated["assessed_by_user_id"] is None

    for headers in (OFFICER, ADMIN):
        validate_error(
            api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
    assert validate_success(
        api.get_monitoring_profile(profile["id"], ANALYST)
    )["calibration_state"] == "PROVISIONAL"

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["risk_rating"] == "LOW"
    assert scored["assessed_by_user_id"] == ANALYST_ID
    assert_instant_equals(scored["last_risk_assessed_at"], "2026-08-01T00:00:00Z")

    calibrated = calibrate(profile["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["calibrated_by_user_id"] == ANALYST_ID
    assert calibrated["aggregate_usd_threshold"] == 822250.00


def test_settlement_allocation_belongs_to_the_relationship_manager_alone(api):
    """The analyst who drafted this very plan and may serve its notice still cannot allocate
    against it, which separates the plan-progression grant from the settlement grant.

    Design: Corner/rbac/settlement_allocation_belongs_to_the_relationship_manager_alone
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    open_profile(rid, [corridor("DE", 500000.00, 100)])
    plan = draft_plan(
        rid, ANALYST, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=500000,
    )
    assert plan["drafted_by_user_id"] == ANALYST_ID
    assert submit_plan(plan["id"], ANALYST)["state"] == "PENDING_APPROVAL"
    approved = approve_plan(plan["id"])
    assert approved["state"] == "APPROVED"
    assert approved["notice_period_days"] == 105
    assert approved["wind_down_cap_usd"] == 1050000.00

    for headers in (ANALYST, COMMITTEE, ADMIN):
        validate_error(
            api.allocate_settlement(
                plan["id"], {"action": "ALLOCATE", "amount_cents": 100000}, headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
    untouched = read_plan(plan["id"])
    assert untouched["settled_cents"] == 0
    assert untouched["outstanding_obligation_cents"] == 500000
    assert untouched["allocation_round"] == 0
    assert untouched["allocation_lines"] == []

    served = progress_plan(plan["id"], "SERVE_NOTICE", headers=ANALYST)
    assert served["state"] == "NOTICE_SERVED"

    allocated = validate_success(
        api.allocate_settlement(plan["id"], {"action": "ALLOCATE", "amount_cents": 100000}, RM)
    )
    assert allocated["settled_cents"] == 100000
    assert allocated["outstanding_obligation_cents"] == 400000
    assert allocated["allocation_round"] == 1
    assert allocated["last_allocated_cents"] == 100000
    assert [(line["jurisdiction_code"], line["line_cents"]) for line in
            allocated["allocation_lines"]] == [("DE", 100000)]
