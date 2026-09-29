"""Corner queue - section validations, part B: enums, numeric domains, pagination, concurrency."""
from test_helpers import (
    ApiErrorId,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    new_respondent,
    open_questionnaire,
    read_respondent,
    validate_error,
    validate_paginated,
    validate_success,
    verify_licensing,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, OFFICER


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


def test_unknown_enum_member_on_an_action_discriminator(api):
    """The role and the addressed row are both fine, so the request reaches the body checks and
    an action outside the discriminator's set is a body error rather than a state error.

    Design: Corner/validations/unknown_enum_member_on_an_action_discriminator
    """
    rid = _licensed()["id"]

    response = api.restrict_respondent(
        rid, {"action": "PAUSE", "restriction_reason": "OFFICER_ACTION"}, OFFICER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE, expected_status=400)

    assert read_respondent(rid)["dd_state"] == "DD_IN_PROGRESS"


def test_ownership_pct_lower_bound_is_exclusive_and_upper_bound_is_inclusive(api):
    """The declared domain is open below and closed above, so zero is refused while the exact
    ceiling - the largest stake one direct owner can hold - is accepted.

    Design: Corner/validations/ownership_pct_lower_bound_is_exclusive_and_upper_bound_is_inclusive
    """
    rid = _licensed()["id"]

    refused = api.create_beneficial_owner(
        rid,
        {"owner_name": "Zero Holder", "owner_type": "NATURAL_PERSON", "ownership_pct": 0.00,
         "country_of_residence": "DE"},
        ANALYST,
    )
    validate_error(refused, ApiErrorId.ERR_FIELD_OUT_OF_RANGE, expected_status=400)

    created = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Anna Weber", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 100.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )

    assert created["ownership_pct"] == 100.00
    assert created["effective_ownership_pct"] == 100.00
    assert created["chain_depth"] == 1
    assert created["verification_status"] == "PENDING"


def test_control_assessment_self_rating_outside_one_to_five(api):
    """The parent questionnaire is in a legal state and the role is the owning contact, so the
    numeric domain is the only thing left to fail, and the first-row transition never fires.

    Design: Corner/validations/control_assessment_self_rating_outside_one_to_five
    """
    rid = _licensed()["id"]
    questionnaire = open_questionnaire(rid)

    response = api.create_control_assessment(
        questionnaire["id"],
        {"control_domain": "GOVERNANCE", "self_rating": 6},
        make_respondent_headers(rid),
    )
    validate_error(response, ApiErrorId.ERR_FIELD_OUT_OF_RANGE, expected_status=400)

    assert validate_success(
        api.get_questionnaire(questionnaire["id"], ANALYST)
    )["state"] == "DRAFT"


def test_pagination_bounds_are_enforced_on_list_endpoints(api):
    """One past the declared maximum and one below the declared minimum are both refused, while
    the maximum itself succeeds, which is what proves the bound is inclusive.

    Design: Corner/validations/pagination_bounds_are_enforced_on_list_endpoints
    """
    over_limit = api.list_respondents(ANALYST, params={"limit": 101})
    validate_error(over_limit, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)

    negative_offset = api.list_respondents(ANALYST, params={"limit": 10, "offset": -1})
    validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)

    rows, meta = validate_paginated(
        api.list_respondents(ANALYST, params={"limit": 100, "offset": 0})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_unparseable_event_date_is_a_format_error(api):
    """A real calendar date written in the wrong notation fails the parse rung, which sits far
    above the temporal-admissibility rung that would otherwise have judged it.

    Design: Corner/validations/unparseable_event_date_is_a_format_error
    """
    rid = _licensed()["id"]

    response = api.create_adverse_media_event(
        rid,
        {"headline": "Regulatory probe reported", "category": "REGULATORY_ACTION",
         "severity_tier": "TIER_2", "source_reliability": "B", "event_date": "01-08-2026"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_FORMAT, expected_status=400)


def test_stale_respondent_version_beats_an_invalid_effective_interval(api):
    """The write is wrong twice over, and the concurrency rung is checked before every state
    and temporal rule, so the interval error never surfaces.

    Design: Corner/validations/stale_respondent_version_beats_an_invalid_effective_interval
    """
    _de()
    respondent = new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    stale_version = respondent["version"]
    verify_licensing(respondent["id"])
    assert read_respondent(respondent["id"])["version"] > stale_version

    response = api.create_monitoring_profile(
        respondent["id"],
        {"effective_from": "2026-12-31T00:00:00Z", "effective_to": "2026-07-01T00:00:00Z",
         "expected_corridors": [
             {"jurisdiction_code": "DE", "expected_monthly_usd": 400000.00,
              "expected_monthly_count": 80}],
         "expected_respondent_version": stale_version},
        ANALYST,
    )
    validate_error(
        response, ApiErrorId.ERR_STALE_RESPONDENT_VERSION, expected_status=412
    )

    _rows, meta = validate_paginated(
        api.list_monitoring_profiles(ANALYST, params={"respondent_bank_id": respondent["id"]})
    )
    assert meta["total_count"] == 0


def test_committee_approval_refused_from_the_wrong_respondent_state(api):
    """The respondent would fail several of the approval's business gates too, so the answer
    proves the declared-transition rung outranks all of them.

    Design: Corner/validations/committee_approval_refused_from_the_wrong_respondent_state
    """
    rid = _licensed()["id"]

    response = api.decide_committee(rid, {"action": "APPROVE"}, COMMITTEE)
    validate_error(response, ApiErrorId.ERR_INVALID_RESPONDENT_STATE, expected_status=409)

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "DD_IN_PROGRESS"
    assert respondent["approved_by_user_id"] is None
    assert respondent["approved_risk_rating"] == "UNRATED"
