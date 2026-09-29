"""Corner queue - section validations, part C: state gates, uniqueness, intervals, temporal."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    dispatch_request,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    raise_request,
    read_plan,
    read_request,
    read_respondent,
    restricted_jurisdiction,
    sanctioned_jurisdiction,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, RM, RM_ID
from test_helpers.test_users import RM_ID_2


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _licensed():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_dispatching_an_already_sent_information_request_is_rejected(api):
    """Replaying the dispatch is an idempotency corner rather than a legal no-op, and the first
    dispatch's whole service-level triple has to survive the refusal.

    Design: Corner/validations/dispatching_an_already_sent_information_request_is_rejected
    """
    rid = _licensed()["id"]
    request = raise_request(rid, request_topic="ACTIVITY_EXPLANATION", severity="MEDIUM")
    dispatch_request(request["id"])

    response = api.dispatch_request(request["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_RFI_STATE, expected_status=409)

    stored = read_request(request["id"])
    assert stored["state"] == "SENT"
    assert stored["sla_hours"] == 168
    assert_instant_equals(stored["due_at"], "2026-08-08T00:00:00Z")


def test_an_exiting_respondent_refuses_writes_outside_the_exit_workflow(api):
    """Once the exit has begun, an otherwise perfectly legal respondent write is refused on
    relationship-closure grounds, which is a different rung and a different error from a
    plain state violation.

    Design: Corner/validations/an_exiting_respondent_refuses_writes_outside_the_exit_workflow
    """
    rid = _licensed()["id"]
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000,
    )
    assert read_respondent(rid)["dd_state"] == "EXITING"

    response = api.verify_licensing(
        rid,
        {"license_status": "CONDITIONAL", "regulator_standing": "GOOD_STANDING",
         "regulator_name": "BaFin"},
        ANALYST,
    )
    validate_error(
        response, ApiErrorId.ERR_RESPONDENT_RELATIONSHIP_CLOSED, expected_status=403
    )

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "EXITING"
    assert respondent["license_status"] == "ACTIVE"
    assert read_plan(plan["id"])["state"] == "DRAFT"


def test_duplicate_swift_bic_across_respondents_is_rejected(api):
    """The identifier is unique across the whole collection, so an otherwise entirely different
    bank reusing it is refused - and the payload must be valid for that error to be reachable.

    Design: Corner/validations/duplicate_swift_bic_across_respondents_is_rejected
    """
    _licensed()

    response = api.create_respondent(
        {"legal_name": "Nordbank Zweigstelle AG", "swift_bic": "NORDDEFF",
         "home_jurisdiction_code": "DE", "relationship_manager_user_id": RM_ID_2,
         "expected_monthly_volume_usd": 100000.00, "expected_monthly_count": 20},
        RM,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE, expected_status=409)

    _rows, meta = validate_paginated(api.list_respondents(RM))
    assert meta["total_count"] == 1


def test_adjacent_monitoring_intervals_count_as_an_overlap(api):
    """The second interval starts at the exact instant the first one ends, and because these
    intervals are closed on both sides that single shared instant is a conflict.

    Design: Corner/validations/adjacent_monitoring_intervals_count_as_an_overlap
    """
    rid = _licensed()["id"]
    first = open_profile(
        rid,
        [{"jurisdiction_code": "DE", "expected_monthly_usd": 400000.00,
          "expected_monthly_count": 80}],
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-09-30T00:00:00Z",
    )

    response = api.create_monitoring_profile(
        rid,
        {"effective_from": "2026-09-30T00:00:00Z", "effective_to": "2026-12-31T23:59:59Z",
         "expected_corridors": [
             {"jurisdiction_code": "DE", "expected_monthly_usd": 400000.00,
              "expected_monthly_count": 80}],
         "expected_respondent_version": read_respondent(rid)["version"]},
        ANALYST,
    )
    validate_error(
        response, ApiErrorId.ERR_MONITORING_INTERVAL_OVERLAP, expected_status=409
    )

    rows, meta = validate_paginated(
        api.list_monitoring_profiles(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_sanctioned_home_jurisdiction_blocks_creation_while_restricted_does_not(api):
    """The rule keys on the strongest sanctions value alone, so the paired create under a merely
    restricted jurisdiction has to succeed for the refusal to mean anything.

    Design: Corner/validations/sanctioned_home_jurisdiction_blocks_creation_while_restricted_does_not
    """
    sanctioned_jurisdiction(
        jurisdiction_code="SY", name="Syria", basel_aml_index=8.0, corridor_risk_weight=2.0
    )
    restricted_jurisdiction(
        jurisdiction_code="RU", name="Russia", basel_aml_index=6.0, corridor_risk_weight=1.5
    )

    refused = api.create_respondent(
        {"legal_name": "Damascus Commercial Bank", "swift_bic": "DAMCSYDA",
         "home_jurisdiction_code": "SY", "relationship_manager_user_id": RM_ID,
         "expected_monthly_volume_usd": 100000.00, "expected_monthly_count": 20},
        RM,
    )
    validate_error(
        refused, ApiErrorId.ERR_HOME_JURISDICTION_SANCTIONED, expected_status=422
    )

    created = validate_success(
        api.create_respondent(
            {"legal_name": "Volga Bank", "swift_bic": "VOLGRUMM",
             "home_jurisdiction_code": "RU", "relationship_manager_user_id": RM_ID,
             "expected_monthly_volume_usd": 100000.00, "expected_monthly_count": 20},
            RM,
        ),
        expected_status=201,
    )

    assert created["dd_state"] == "PROSPECT"
    assert created["payment_posture"] == "BLOCKED"
    _rows, meta = validate_paginated(api.list_respondents(RM))
    assert meta["total_count"] == 1


def test_adverse_media_event_date_equal_to_the_clock_is_admissible(api):
    """Only a strictly later instant is inadmissible, so the clock's own instant is logged
    while the day after is refused, and neither call moves the uplift.

    Design: Corner/validations/adverse_media_event_date_equal_to_the_clock_is_admissible
    """
    rid = _licensed()["id"]

    logged = validate_success(
        api.create_adverse_media_event(
            rid,
            {"headline": "Same-day regulatory notice", "category": "REGULATORY_ACTION",
             "severity_tier": "TIER_2", "source_reliability": "B",
             "event_date": "2026-08-01T00:00:00Z"},
            ANALYST,
        ),
        expected_status=201,
    )
    assert logged["adjudication_state"] == "NEW"
    assert logged["uplift_points"] == 0.00

    refused = api.create_adverse_media_event(
        rid,
        {"headline": "Tomorrow's news", "category": "REGULATORY_ACTION",
         "severity_tier": "TIER_2", "source_reliability": "B",
         "event_date": "2026-08-02T00:00:00Z"},
        ANALYST,
    )
    validate_error(refused, ApiErrorId.ERR_EVENT_DATE_IN_FUTURE, expected_status=422)

    assert read_respondent(rid)["adverse_media_uplift"] == 0.00
