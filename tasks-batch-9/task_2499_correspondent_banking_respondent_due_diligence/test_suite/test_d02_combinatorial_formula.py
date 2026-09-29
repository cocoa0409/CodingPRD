"""Difficulty queue - rule combinatorial_formula.

Three formulae whose answer depends on how the pieces are combined: the inherent
score's four capped components, the calibration's per-corridor rounding before the
aggregate buffer, and the refresh date's pinned five-step evaluation.
"""
from test_helpers import (
    add_control_rows,
    add_nested,
    add_owner,
    add_verified_owner,
    assert_instant_equals,
    calibrate,
    committee_decision,
    confirmed_media,
    corridor,
    licensed_respondent,
    log_media,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    read_nested,
    read_respondent,
    score_respondent,
    set_clock,
    submit_questionnaire,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ANALYST, OFFICER, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]


def _flat_questionnaire(respondent_id, rating, version="V1"):
    questionnaire = open_questionnaire(respondent_id, version=version)
    add_control_rows(questionnaire["id"], respondent_id, {d: rating for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], respondent_id)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    return questionnaire


def _capped_respondent():
    """R1: home PK at the jurisdiction points cap, ownership raw 32 and nested raw 23."""
    pk_profile = new_jurisdiction(
        name="Pakistan", sanctions_status="RESTRICTED", fatf_listing="CALL_FOR_ACTION",
        secrecy_flag=True, basel_aml_index=10.0, corridor_risk_weight=1.0,
    )
    pk = pk_profile["jurisdiction_code"]
    pa = new_jurisdiction(name="Panama", sanctions_status="RESTRICTED", basel_aml_index=5.0)[
        "jurisdiction_code"
    ]
    de = new_jurisdiction(name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]

    # R2 already carries one depth-1 live row, so R1's edge into R2 computes depth 2.
    r2 = licensed_respondent(de, legal_name="Downstream Respondent AG")
    add_nested(r2["id"], de, downstream_institution_name="R2 Downstream One",
               discovery_source="QUESTIONNAIRE")

    r1 = licensed_respondent(
        pk, legal_name="Karachi Trade Bank", expected_monthly_volume_usd=1000000.00,
        expected_monthly_count=250, nested_activity_permitted=True,
    )
    rid = r1["id"]
    add_verified_owner(rid, pk, owner_name="Pep Holder", ownership_pct=40.00, is_pep=True)
    add_verified_owner(
        rid, pa, owner_name="State Holder", owner_type="STATE", ownership_pct=20.00
    )

    deep = add_nested(
        rid, de, downstream_institution_name="Deep Downstream",
        discovery_source="TRANSACTION_MONITORING", downstream_respondent_bank_id=r2["id"],
    )
    add_nested(rid, de, downstream_institution_name="Shallow One",
               discovery_source="TRANSACTION_MONITORING")
    add_nested(rid, de, downstream_institution_name="Shallow Two",
               discovery_source="ADVERSE_MEDIA")

    _flat_questionnaire(rid, 3)
    return pk_profile, rid, deep


def test_inherent_score_clips_three_components_at_once(api):
    """The jurisdiction (43 raw), ownership (32 raw) and nested (23 raw) components all
    clip in the same run, giving 40.00 + 24.0 + 20.0 + 8 = 92.00 with the 100.00 score
    cap inert, and a residual of 71.30 that lands on PROHIBITED.

    Design: Difficulty/combinatorial_formula/inherent_risk_three_component_caps_bind_on_inclusive_volume_tier_edge
    """
    pk_profile, rid, deep = _capped_respondent()

    assert pk_profile["jurisdiction_risk_points"] == 40.00  # min(40.00, 8+12+3+10.0*2.0)

    scored = validate_success(
        api.assess_risk(rid, {"variant": "ONBOARDING_PROVISIONAL"}, ANALYST)
    )

    assert scored["control_score"] == 60.00
    assert scored["control_credit"] == 0.2250
    assert scored["inherent_risk_score"] == 92.00
    assert scored["residual_risk_score"] == 71.30  # round(round(92.00*0.7750, 2), 2)
    assert scored["risk_rating"] == "PROHIBITED"
    # ownership_verified is false at 60.00%, so the lifecycle hop does not fire.
    assert scored["ownership_verified"] is False
    assert scored["dd_state"] == "DD_IN_PROGRESS"


def test_nested_rollup_feeds_the_capped_component_and_depth_two_bonus(api):
    """The transitive edge computes depth 2, three UNDISCLOSED_DETECTED rows weigh 5
    each, and the resulting rollup is what drives the nested component's 5*3 + 8 = 23
    into its 20.0 cap.

    Design: Difficulty/combinatorial_formula/inherent_risk_three_component_caps_bind_on_inclusive_volume_tier_edge
    """
    pk_profile, rid, deep = _capped_respondent()

    edge = read_nested(deep["id"])
    assert edge["depth"] == 2
    assert edge["state"] == "UNDISCLOSED_DETECTED"

    respondent = read_respondent(rid)
    assert respondent["max_nested_depth"] == 2
    assert respondent["undisclosed_nested_count"] == 3
    assert respondent["disclosed_nested_count"] == 0
    assert respondent["nested_exposure_units"] == 20  # 5*2 + 5*1 + 5*1
    assert respondent["verified_ownership_pct"] == 60.00
    assert respondent["ownership_verified"] is False


def _bare_scored_respondent(code, volume):
    respondent = licensed_respondent(
        code, legal_name="Volume Edge Bank", expected_monthly_volume_usd=volume,
    )
    _flat_questionnaire(respondent["id"], 3)
    return score_respondent(respondent["id"], "ONBOARDING_PROVISIONAL")


def test_activity_tier_edge_is_inclusive_at_exactly_one_million(api):
    """Exactly 1000000.00 of declared monthly volume scores 6 activity points while
    999999.99 scores 2, so two otherwise identical respondents differ by exactly the
    four points the inclusive lower edge is worth.

    Design: Difficulty/combinatorial_formula/inherent_risk_three_component_caps_bind_on_inclusive_volume_tier_edge
    """
    code = new_jurisdiction(name="Neutral", basel_aml_index=0.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]

    on_edge = _bare_scored_respondent(code, 1000000.00)
    below_edge = _bare_scored_respondent(code, 999999.99)

    # 0 jurisdiction + 6 for verified_ownership_pct below 75.00 + 0 nested + activity.
    assert on_edge["inherent_risk_score"] == 12.00
    assert below_edge["inherent_risk_score"] == 8.00


def _three_corridor_profile():
    de = new_jurisdiction(name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]
    sg = new_jurisdiction(name="Singapore", basel_aml_index=1.0, corridor_risk_weight=0.70)[
        "jurisdiction_code"
    ]
    nl = new_jurisdiction(name="Netherlands", basel_aml_index=2.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]
    respondent = licensed_respondent(
        de, legal_name="Rounding Order Bank", expected_monthly_volume_usd=4500000.00
    )
    rid = respondent["id"]
    _flat_questionnaire(rid, 4)
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["risk_rating"] == "LOW"  # rating factor 1.30

    profile = open_profile(
        rid,
        [
            corridor(de, 757911.74, 140),
            corridor(sg, 164867.73, 90),
            corridor(nl, 713984.50, 64),
        ],
        tolerance_pct=0.15,
        effective_from="2026-03-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    return (de, sg, nl), rid, profile


def test_calibration_rounds_each_corridor_before_the_aggregate_buffer(api):
    """Rounding each corridor to 2 decimals first sums to 2552595.25 and buffers to
    2807854.78; buffering the unrounded 2552595.245014... sum would answer 2807854.77.

    Design: Difficulty/combinatorial_formula/calibration_rounds_each_corridor_before_the_aggregate_buffer
    """
    (de, sg, nl), rid, profile = _three_corridor_profile()

    calibrated = validate_success(
        api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, ANALYST)
    )

    assert calibrated["calibration_state"] == "CALIBRATED"
    by_code = {c["jurisdiction_code"]: c for c in calibrated["corridor_thresholds"]}
    assert by_code[de]["usd_threshold"] == 1133078.05  # raw 1133078.0513
    assert by_code[sg]["usd_threshold"] == 352110.37  # raw 352110.36621...
    assert by_code[nl]["usd_threshold"] == 1067406.83  # raw 1067406.8275, half up
    assert calibrated["aggregate_usd_threshold"] == 2807854.78
    assert calibrated["hold_threshold_usd"] == 280785.48
    assert calibrated["calibrated_by_user_id"] == "user-analyst-01"


def test_calibration_count_thresholds_take_the_ceiling_not_the_nearest(api):
    """The count figure always rounds up: 209.30 becomes 210, 192.214... becomes 193
    and 95.68 becomes 96, and the corridor order of the payload is preserved.

    Design: Difficulty/combinatorial_formula/calibration_rounds_each_corridor_before_the_aggregate_buffer
    """
    (de, sg, nl), rid, profile = _three_corridor_profile()

    calibrated = validate_success(
        api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, ANALYST)
    )

    assert [c["jurisdiction_code"] for c in calibrated["corridor_thresholds"]] == [de, sg, nl]
    counts = [c["count_threshold"] for c in calibrated["corridor_thresholds"]]
    assert counts == [210, 193, 96]


def _high_rated_approved_respondent():
    """Approved at the default clock with approved_risk_rating HIGH."""
    pk = new_jurisdiction(
        name="Pakistan", sanctions_status="RESTRICTED", fatf_listing="CALL_FOR_ACTION",
        secrecy_flag=True, basel_aml_index=8.0, corridor_risk_weight=1.0,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        pk, legal_name="Circular Cadence Bank", expected_monthly_volume_usd=4500000.00,
        nested_activity_permitted=False,
    )
    rid = respondent["id"]
    owner = add_owner(rid, pk, owner_name="Pep Majority", ownership_pct=80.00, is_pep=True)
    verify_owner(owner["id"])
    _flat_questionnaire(rid, 2)
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["inherent_risk_score"] == 59.00  # 39.00 + (10 + min(12, 4)) + 0 + 6
    assert scored["control_score"] == 40.00
    assert scored["control_credit"] == 0.1125
    assert scored["residual_risk_score"] == 52.36
    assert scored["risk_rating"] == "HIGH"
    committee_decision(rid, "APPROVE")
    return pk, rid


def test_tier_one_confirmation_pulls_the_date_to_triage_plus_thirty_days(api):
    """Steps one and two run off the frozen approved_risk_rating HIGH, so the base
    window end stays 2027-08-01 and the live rating stays HIGH; the TIER_1 override
    then replaces the accelerated candidate with triaged_at plus 30 days.

    Design: Difficulty/combinatorial_formula/refresh_due_date_pinned_five_step_order_beats_fixed_point_iteration
    """
    pk, rid = _high_rated_approved_respondent()
    approved = read_respondent(rid)
    assert approved["approved_risk_rating"] == "HIGH"
    assert_instant_equals(approved["last_approved_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(approved["refresh_due_date"], "2027-08-01T00:00:00Z")

    set_clock("2027-06-01T00:00:00Z")
    first = confirmed_media(
        rid, headline="Regulator sanctions the bank", category="REGULATORY_ACTION",
        severity_tier="TIER_1", source_reliability="A", event_date="2026-11-10T00:00:00Z",
    )

    assert first["uplift_points"] == 12.00  # round(12.0*1.00, 2)
    respondent = read_respondent(rid)
    assert respondent["adverse_media_uplift"] == 12.00
    assert respondent["residual_risk_score"] == 64.36  # 52.36 + 12.00
    assert respondent["risk_rating"] == "HIGH"
    assert respondent["approved_risk_rating"] == "HIGH"
    # accelerated candidate is 2027-08-01; triaged_at 2027-06-01 plus 30 days is earlier.
    assert_instant_equals(respondent["refresh_due_date"], "2027-07-01T00:00:00Z")


def test_refresh_due_date_follows_the_pinned_five_step_order(api):
    """A second confirmation lifts the uplift to 19.00 and the live rating to
    PROHIBITED, whose cadence of 0 months collapses the accelerated candidate onto
    last_approved_at and leaves only the 30-day floor: 2026-08-31. Feeding the live
    PROHIBITED back into steps one and two would answer 2027-08-01 instead.

    Design: Difficulty/combinatorial_formula/refresh_due_date_pinned_five_step_order_beats_fixed_point_iteration
    """
    pk, rid = _high_rated_approved_respondent()
    set_clock("2027-06-01T00:00:00Z")
    confirmed_media(
        rid, headline="Regulator sanctions the bank", category="REGULATORY_ACTION",
        severity_tier="TIER_1", source_reliability="A", event_date="2026-11-10T00:00:00Z",
    )
    second = log_media(
        rid, headline="Civil litigation filed abroad", category="LITIGATION",
        severity_tier="TIER_2", source_reliability="A", event_date="2027-01-20T00:00:00Z",
    )

    triaged = validate_success(api.triage_media(second["id"], {"action": "CONFIRM"}, OFFICER))
    assert triaged["uplift_points"] == 7.00  # round(7.0*1.00, 2)
    assert triaged["adjudication_state"] == "CONFIRMED"

    respondent = read_respondent(rid)
    assert respondent["inherent_risk_score"] == 59.00
    assert respondent["adverse_media_uplift"] == 19.00  # 12.00 then 19.00, re-rounded
    assert respondent["residual_risk_score"] == 71.36  # round(52.36 + 19.00, 2)
    assert respondent["risk_rating"] == "PROHIBITED"
    assert respondent["approved_risk_rating"] == "HIGH"  # frozen, never refreshed here
    assert_instant_equals(respondent["refresh_due_date"], "2026-08-31T00:00:00Z")
    assert respondent["dd_state"] == "RESTRICTED"
    assert respondent["restriction_reason"] == "ADVERSE_MEDIA"
