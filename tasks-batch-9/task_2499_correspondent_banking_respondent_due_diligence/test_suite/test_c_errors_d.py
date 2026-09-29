"""Corner queue - section errors, part D: approval ceilings, cross references and ownership."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    add_nested,
    add_verified_owner,
    all_assessed_overlays,
    assessed_questionnaire,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    post_observation,
    raise_alert,
    read_respondent,
    restricted_jurisdiction,
    score_respondent,
    setup_approved_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_approval_of_a_medium_rated_respondent_in_a_low_ceiling_jurisdiction(api):
    """The ceiling is a rank comparison against the home jurisdiction rather than a fixed
    rating, so an ordinary MEDIUM file fails only because its home country caps approvals at
    LOW - and it clears the licence and ownership gates that sit above it first.

    Design: Corner/errors/approval_of_a_medium_rated_respondent_in_a_low_ceiling_jurisdiction
    """
    turkey = new_jurisdiction(
        jurisdiction_code="TR", name="Turkey", basel_aml_index=6.0, corridor_risk_weight=1.3,
        fatf_listing="INCREASED_MONITORING", max_permitted_risk_rating="LOW",
    )
    assert turkey["jurisdiction_risk_points"] == 17.00
    restricted_jurisdiction(
        jurisdiction_code="RU", name="Russia", basel_aml_index=7.0, corridor_risk_weight=2.0
    )
    respondent = licensed_respondent(
        "TR", legal_name="Bosphorus Bank", swift_bic="BOSPTRIS",
        expected_monthly_volume_usd=150000000.00, expected_monthly_count=9000,
        nested_activity_permitted=True,
    )
    rid = respondent["id"]
    add_verified_owner(rid, "RU", owner_name="Emre Yildiz", ownership_pct=80.00, is_pep=True)
    assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL",
        self_ratings={domain: 4 for domain in CONTROL_DOMAIN_ORDER},
        overlays=all_assessed_overlays(4),
    )
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["inherent_risk_score"] == 47.00
    assert scored["control_score"] == 80.00
    assert scored["residual_risk_score"] == 31.14
    assert scored["risk_rating"] == "MEDIUM"
    assert scored["ownership_verified"] is True
    assert scored["dd_state"] == "PENDING_COMMITTEE"

    response = api.decide_committee(
        rid, {"action": "APPROVE", "decision_note": "Committee sign-off"}, COMMITTEE
    )
    validate_error(
        response, ApiErrorId.ERR_RATING_EXCEEDS_JURISDICTION_CEILING, expected_status=422
    )

    stored = read_respondent(rid)
    assert stored["dd_state"] == "PENDING_COMMITTEE"
    assert stored["approved_risk_rating"] == "UNRATED"
    assert stored["payment_posture"] == "BLOCKED"


def test_widening_the_posture_while_an_undisclosed_nested_row_is_outstanding(api):
    """The undisclosed-nesting gate guards the widening itself, not the endpoint, so the very
    same PATCH still succeeds when it leaves the posture alone.

    Design: Corner/errors/widening_the_posture_while_an_undisclosed_nested_row_is_outstanding
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    validate_success(api.amend_respondent(rid, {"payment_posture": "SCREEN_ONLY"}, RM))
    row = add_nested(
        rid, "DE", ANALYST, downstream_institution_name="Hinterbank GmbH",
        discovery_source="TRANSACTION_MONITORING",
    )
    assert row["state"] == "UNDISCLOSED_DETECTED"
    assert read_respondent(rid)["undisclosed_nested_count"] == 1

    refused = api.amend_respondent(rid, {"payment_posture": "OPEN"}, RM)
    validate_error(
        refused, ApiErrorId.ERR_UNDISCLOSED_NESTING_OUTSTANDING, expected_status=422
    )
    assert read_respondent(rid)["payment_posture"] == "SCREEN_ONLY"

    renamed = validate_success(
        api.amend_respondent(rid, {"legal_name": "Nordbank AG (renamed)"}, RM)
    )
    assert renamed["legal_name"] == "Nordbank AG (renamed)"
    assert renamed["payment_posture"] == "SCREEN_ONLY"


def test_alert_and_rfi_links_may_not_cross_respondents(api):
    """Both body-supplied references are checked against the respondent in the path, so an
    identifier that resolves perfectly well is still refused - and with 422 rather than 404.

    Design: Corner/errors/alert_and_rfi_links_may_not_cross_respondents
    """
    _de()
    bank_a = licensed_respondent(
        "DE", legal_name="A Bank AG", swift_bic="ABNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    bank_b = licensed_respondent(
        "DE", legal_name="B Bank AG", swift_bic="BBNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    profile_b = open_profile(bank_b["id"], [corridor("DE", 400000.00, 80)])
    assert profile_b["calibration_state"] == "PROVISIONAL"
    observation_b = post_observation(
        profile_b["id"], "2026-07", "DE", aggregate_usd=5000000.00, txn_count=900
    )
    assert observation_b["alerts_created_count"] == 0
    alert_b = raise_alert(bank_b["id"], "VOLUME_BREACH", "MEDIUM", OFFICER)

    cross_alert = api.create_monitoring_alert(
        bank_a["id"],
        {"alert_type": "VOLUME_BREACH", "severity": "MEDIUM",
         "activity_observation_id": observation_b["id"]},
        OFFICER,
    )
    validate_error(cross_alert, ApiErrorId.ERR_CROSS_RESPONDENT_REFERENCE, expected_status=422)

    cross_request = api.create_information_request(
        bank_a["id"],
        {"request_topic": "ACTIVITY_EXPLANATION", "severity": "MEDIUM",
         "monitoring_alert_id": alert_b["id"]},
        ANALYST,
    )
    validate_error(cross_request, ApiErrorId.ERR_CROSS_RESPONDENT_REFERENCE, expected_status=422)

    _alerts, alert_meta = validate_paginated(
        api.list_monitoring_alerts(ANALYST, params={"respondent_bank_id": bank_a["id"]})
    )
    assert alert_meta["total_count"] == 0
    _requests, request_meta = validate_paginated(
        api.list_information_requests(ANALYST, params={"respondent_bank_id": bank_a["id"]})
    )
    assert request_meta["total_count"] == 0


def _chain_level(api, respondent_id, name, parent_id=None):
    payload = {
        "owner_name": name, "owner_type": "LEGAL_ENTITY", "ownership_pct": 50.00,
        "country_of_residence": "DE",
    }
    if parent_id is not None:
        payload["parent_owner_id"] = parent_id
    return validate_success(
        api.create_beneficial_owner(respondent_id, payload, ANALYST), expected_status=201
    )


def test_an_ownership_chain_deeper_than_four_levels_is_rejected(api):
    """Four levels is the structural maximum, so the fifth is refused outright rather than
    clamped, and the four legal rows keep their look-through percentages.

    Design: Corner/errors/an_ownership_chain_deeper_than_four_levels_is_rejected
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    levels = []
    parent = None
    for index in range(4):
        parent = _chain_level(
            api, rid, f"Level {index + 1} Holding GmbH",
            parent["id"] if parent is not None else None,
        )
        levels.append(parent)
    assert [level["chain_depth"] for level in levels] == [1, 2, 3, 4]
    assert [level["effective_ownership_pct"] for level in levels] == [50.00, 25.00, 12.50, 6.25]

    response = api.create_beneficial_owner(
        rid,
        {"owner_name": "Level Five Holding GmbH", "owner_type": "LEGAL_ENTITY",
         "ownership_pct": 50.00, "country_of_residence": "DE",
         "parent_owner_id": levels[3]["id"]},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_DEPTH_EXCEEDED, expected_status=422)

    _rows, meta = validate_paginated(
        api.list_beneficial_owners(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 4


def test_sibling_ownership_percentages_may_not_exceed_one_hundred(api):
    """The ceiling applies per sibling group, so the identical stake that overflows the direct
    owners is accepted one level down, and a group landing exactly on 100.00 is permitted.

    Design: Corner/errors/sibling_ownership_percentages_may_not_exceed_one_hundred
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    first = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Erste Holding GmbH", "owner_type": "LEGAL_ENTITY",
             "ownership_pct": 60.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )

    overflowing = api.create_beneficial_owner(
        rid,
        {"owner_name": "Zweite Holding GmbH", "owner_type": "LEGAL_ENTITY",
         "ownership_pct": 45.00, "country_of_residence": "DE"},
        ANALYST,
    )
    validate_error(overflowing, ApiErrorId.ERR_OWNERSHIP_PCT_EXCEEDS_100, expected_status=422)

    nested = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Zweite Holding GmbH", "owner_type": "LEGAL_ENTITY",
             "ownership_pct": 45.00, "country_of_residence": "DE",
             "parent_owner_id": first["id"]},
            ANALYST,
        ),
        expected_status=201,
    )
    assert nested["chain_depth"] == 2
    assert nested["effective_ownership_pct"] == 27.00

    exact = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Dritte Holding GmbH", "owner_type": "LEGAL_ENTITY",
             "ownership_pct": 40.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )
    assert exact["chain_depth"] == 1
    assert exact["effective_ownership_pct"] == 40.00

    _rows, meta = validate_paginated(
        api.list_beneficial_owners(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 3


def test_an_observation_month_after_the_clock_month_is_rejected(api):
    """The comparison is on the clock's calendar month rather than on an instant, so the month
    that has barely started is admissible while the next one is refused.

    Design: Corner/errors/an_observation_month_after_the_clock_month_is_rejected
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    profile = open_profile(respondent["id"], [corridor("DE", 400000.00, 80)])
    assert profile["calibration_state"] == "PROVISIONAL"

    future = api.create_observation(
        profile["id"],
        {"period_month": "2026-09", "corridor_jurisdiction_code": "DE",
         "aggregate_usd": 100000.00, "txn_count": 20},
        ANALYST,
    )
    validate_error(future, ApiErrorId.ERR_OBSERVATION_PERIOD_IN_FUTURE, expected_status=422)

    current = validate_success(
        api.create_observation(
            profile["id"],
            {"period_month": "2026-08", "corridor_jurisdiction_code": "DE",
             "aggregate_usd": 100000.00, "txn_count": 20},
            ANALYST,
        ),
        expected_status=201,
    )
    assert current["period_month"] == "2026-08"
    assert current["alerts_created_count"] == 0

    _rows, meta = validate_paginated(
        api.list_activity_observations(
            ANALYST, params={"monitoring_profile_id": profile["id"]}
        )
    )
    assert meta["total_count"] == 1
