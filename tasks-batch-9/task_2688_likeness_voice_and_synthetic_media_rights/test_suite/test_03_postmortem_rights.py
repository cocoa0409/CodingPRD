"""Post-mortem rights resolved twice: under the domicile's law and the use state's."""

from test_helpers import api_client, assertions, factories, fixtures, validate_error

CA_SEVENTY_YEAR_PROFILE = {
    "state_code": "CA",
    "postmortem_rights_years": 70,
    "postmortem_requires_registration": True,
    "biometric_retention_max_days": 365,
}

TX_NO_POSTMORTEM_PROFILE = {
    "state_code": "TX",
    "postmortem_rights_years": 0,
    "postmortem_requires_registration": False,
    "biometric_retention_max_days": 90,
    "deletion_grace_days": 10,
    "removal_window_days": 21,
    "disclosure_required_advertising": False,
    "disclosure_required_entertainment": False,
    "min_disclosure_rank_advertising": 1,
    "min_disclosure_rank_entertainment": 1,
}

TEXAS_DETECTION = {
    "detection_source": "MONITORING_FEED",
    "suspect_url": "https://example.tx/clip-99",
    "detected_channel": "ADVERTISING",
    "detected_state_code": "TX",
    "detected_view_count": 400_000,
    "match_confidence": 0.5,
}


def _deceased_talent_detected_in_texas():
    """A CA talent who died in 2020, with one use detected in a zero-year state."""
    scenario = fixtures.register_state_law_profile(overrides=CA_SEVENTY_YEAR_PROFILE)
    fixtures.register_state_law_profile(scenario, TX_NO_POSTMORTEM_PROFILE)
    fixtures.create_talent(
        scenario, {"legal_name": "Marguerite Vale", "union_code": "SAG_AFTRA"}
    )
    fixtures.record_death(scenario, {"date_of_death": "2020-03-15T00:00:00Z"})
    fixtures.open_case(scenario, TEXAS_DETECTION)
    return scenario


def test_domicile_term_lives_while_the_use_state_recognises_nothing():
    """The same death instant resolves to 2090 at home and to null in Texas.

    The PRD states: "A talent who died on 15 March 2020 domiciled in a state
    recognising seventy years therefore has `postmortem_rights_until` of
    `2090-03-15T00:00:00Z`." It also states: "A talent who died in 2020 domiciled
    in a state recognising seventy years has live domicile rights, yet a use
    detected in a state recognising none produces a null `use_state_rights_until`
    and an `enforceable_under_use_state` of false — the domicile answer says the
    right lives, the use-state answer says there is nothing to enforce there."

    Design: Difficulty/dual_variant_calc/postmortem_expiry_domicile_versus_use_state_divergence
    """
    scenario = _deceased_talent_detected_in_texas()

    talent = fixtures.read_talent(scenario)
    assert talent["life_status"] == "DECEASED"
    assert talent["postmortem_rights_until"] == "2090-03-15T00:00:00Z"

    case = fixtures.refresh_case(scenario)
    assert case["use_state_rights_until"] is None
    assert case["enforceable_under_use_state"] is False
    assert case["severity_score"] == 0.3550


def test_takedown_is_refused_where_the_use_state_grants_no_right():
    """A live domicile term cannot carry a takedown into a state with none.

    The PRD states: "Conversely, `ISSUE_TAKEDOWN` requires
    `enforceable_under_use_state` to be true, and a deceased talent whose rights
    have lapsed in the detected state cannot support one — the attempt is refused
    with `ERR_POSTMORTEM_RIGHTS_EXPIRED`." The refused case keeps the status it
    was opened in: "A new case is `DETECTED` with `legal_hold_applied_count` at
    zero and `triaged_by_user_id`, `escalated_by_user_id`, `closed_by_user_id`,
    `takedown_issued_at` and `closure_outcome` all null."

    Design: Difficulty/dual_variant_calc/postmortem_expiry_domicile_versus_use_state_divergence
    """
    scenario = _deceased_talent_detected_in_texas()
    opened_version = scenario["case"]["version"]

    response = api_client.triage_infringement_case(
        scenario["case"]["id"],
        factories.triage_payload("ISSUE_TAKEDOWN"),
        scenario["compliance_headers"],
    )
    validate_error(response, "ERR_POSTMORTEM_RIGHTS_EXPIRED")

    case = fixtures.refresh_case(scenario)
    assert case["status"] == "DETECTED"
    assertions.assert_fields_null(case, "takedown_issued_at", "triaged_by_user_id")
    assertions.assert_versioned(case, opened_version)
