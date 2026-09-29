"""Requests that break two rules at once, and which refusal the ladder reports."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

ESCALATION_DETECTION = {
    "detection_source": "MONITORING_FEED",
    "suspect_url": "https://pirate.example/clip-1",
    "detected_channel": "ADVERTISING",
    "detected_state_code": "CA",
    "detected_view_count": 8_000_000,
    "match_confidence": 0.900,
}

CUT_RATE_DRAFT = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US"],
    "permitted_use_notes": "Second campaign at a cut rate",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_until": "2027-03-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 60_000,
}


def _frozen_talent_holding_one_grant():
    """An escalated case has frozen a talent who already holds one active grant."""
    scenario = fixtures.campaign_stored_asset()
    fixtures.open_case(scenario, ESCALATION_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)
    return scenario


def _draft_the_cut_rate_grant(scenario):
    """Send the below-floor draft with the talent's current version echoed back."""
    talent = fixtures.read_talent(scenario)
    payload = factories.consent_grant_payload(
        talent["id"], talent["version"], **CUT_RATE_DRAFT
    )
    return api_client.create_consent_grant(payload, scenario["admin_headers"])


def _grant_count(scenario):
    response = api_client.list_consent_grants(
        scenario["admin_headers"],
        params={"talent_id": scenario["talent"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return len(data)


def test_frozen_posture_is_reported_ahead_of_the_below_floor_fee():
    """One draft breaks both rules; the posture gate answers first.

    The PRD states: "A talent whose posture is `FROZEN` cannot be the subject of a
    new grant." The money defect is deliberately reported last: "Last of all sits
    the fiscal rung `ERR_COMPENSATION_BELOW_STATUTORY_FLOOR`, ranked bottom on
    purpose: a frozen talent, a scope breach or a defective term is always reported
    ahead of a money defect on the same draft."

    Design: Difficulty/priority_pair_validation_conflict/frozen_talent_outranks_below_floor_per_use_fee_on_consent_create
    """
    scenario = _frozen_talent_holding_one_grant()
    assertions.assert_posture(fixtures.read_talent(scenario), "FROZEN")

    validate_error(_draft_the_cut_rate_grant(scenario), "ERR_TALENT_RIGHTS_FROZEN")

    assert _grant_count(scenario) == 1


def test_the_same_draft_exposes_the_floor_once_the_posture_clears():
    """With the case closed the identical payload fails on the money instead.

    The PRD states: "When the grant carries a union affiliation, the governing
    union row is selected as described in §2.7 using the grant's `effective_from`
    as the reference date and the grant's governing media type, and
    `per_use_base_fee_cents` must be at least half of that row's
    `minimum_per_use_cents`." A per-use fee of 60000 against a floor row of 150000
    is below that half, so the draft was defective all along.

    Design: Difficulty/priority_pair_validation_conflict/frozen_talent_outranks_below_floor_per_use_fee_on_consent_create
    """
    scenario = _frozen_talent_holding_one_grant()
    _draft_the_cut_rate_grant(scenario)

    fixtures.close_case(scenario, "SETTLED", headers=scenario["second_admin_headers"])

    talent = fixtures.read_talent(scenario)
    assertions.assert_posture(talent, "CLEAR")
    assert fixtures.refresh_asset(scenario)["status"] == "STORED"

    validate_error(
        _draft_the_cut_rate_grant(scenario), "ERR_COMPENSATION_BELOW_STATUTORY_FLOOR"
    )

    assert _grant_count(scenario) == 1
    entries = fixtures.talent_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000)


CROSS_GRANT_DETECTION = dict(
    ESCALATION_DETECTION, suspect_url="https://pirate.example/clip-2"
)


def _two_grants_with_the_only_sample_impounded():
    """Grant A owns the sample; grant B is a sibling; litigation holds the sample."""
    scenario = fixtures.campaign_stored_asset(
        grant_overrides={"permitted_use_notes": "Grant A - voice"},
        asset_overrides=dict(fixtures.CAMPAIGN_ASSET, capture_ref="cap-A1"),
    )
    scenario["grant_a"] = fixtures.refresh_grant(scenario)
    fixtures.draft_consent_grant(
        scenario,
        dict(fixtures.CAMPAIGN_GRANT, permitted_use_notes="Grant B - separate campaign"),
    )
    fixtures.countersign_grant(scenario)
    scenario["grant_b"] = fixtures.refresh_grant(scenario)
    fixtures.open_case(scenario, CROSS_GRANT_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)
    return scenario


def _build_under_grant_b(scenario):
    """Try to train a replica under grant B from grant A's impounded sample."""
    payload = factories.digital_replica_payload(
        scenario["talent"]["id"],
        scenario["grant_b"]["id"],
        [scenario["asset"]["id"]],
        replica_kind="VOICE",
        build_ref="build-x1",
    )
    return api_client.create_digital_replica(payload, scenario["admin_headers"])


def _replica_count(scenario):
    response = api_client.list_digital_replicas(
        scenario["admin_headers"],
        params={"talent_id": scenario["talent"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return len(data)


def test_impounded_source_is_reported_ahead_of_the_wrong_grant():
    """The safety refusal outranks the referential one on the same payload.

    The PRD states: "If any member is an asset in `LEGAL_HOLD`, the build is
    refused with `ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD` — training a replica on
    material impounded for litigation is the gravest failure this office can
    commit, so that refusal outranks every scope and referential check on the same
    request, and a payload that mixes impounded material together with material
    from the wrong grant is reported as the safety failure." The frozen posture
    cannot shadow the pair, because "Notably, the talent's `FROZEN` posture is
    **not** a gate on building a replica: the legal-hold state of the specific
    source assets is the operative safety signal here, and the posture gate is
    deliberately absent from this one operation."

    Design: Difficulty/priority_pair_validation_conflict/legal_hold_source_asset_outranks_cross_grant_asset_mismatch
    """
    scenario = _two_grants_with_the_only_sample_impounded()
    assert fixtures.refresh_asset(scenario)["status"] == "LEGAL_HOLD"

    validate_error(
        _build_under_grant_b(scenario), "ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD"
    )

    assert _replica_count(scenario) == 0


def test_releasing_the_hold_uncovers_the_cross_grant_mismatch():
    """The identical body now fails on provenance rather than on impoundment.

    The PRD states: "Next, if any member belongs to a different `consent_grant_id`
    or a different `talent_id` than the replica being built, the build is refused
    with `ERR_ASSET_CONSENT_MISMATCH`, because material captured under one grant
    may not be reused under another."

    Design: Difficulty/priority_pair_validation_conflict/legal_hold_source_asset_outranks_cross_grant_asset_mismatch
    """
    scenario = _two_grants_with_the_only_sample_impounded()
    _build_under_grant_b(scenario)

    fixtures.close_case(scenario, "SETTLED", headers=scenario["second_admin_headers"])

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "STORED"
    assert asset["held_from_status"] is None

    validate_error(_build_under_grant_b(scenario), "ERR_ASSET_CONSENT_MISMATCH")

    assert _replica_count(scenario) == 0


US_LICENCE = {
    "channel": "ADVERTISING",
    "territory_codes": ["US"],
    "actual_impressions": 12_000_000,
}

OUTPUTS = (
    {"intended_use_description": "Autumn radio spot",
     "scheduled_first_use_at": "2026-09-01T00:00:00Z"},
    {"intended_use_description": "Winter radio spot",
     "scheduled_first_use_at": "2026-11-01T00:00:00Z"},
    {"intended_use_description": "Spring radio spot",
     "scheduled_first_use_at": "2026-12-01T00:00:00Z"},
)


def _three_outputs_with_two_overlapping_us_licences():
    """Two ISSUED US windows already overlap on the one replica."""
    scenario = fixtures.campaign_approved_replica()
    approved = []
    for overrides in OUTPUTS:
        fixtures.submit_performance(
            scenario, dict(fixtures.CAMPAIGN_PERFORMANCE, **overrides)
        )
        fixtures.review_performance(scenario, "APPROVE", {"review_note": "ok"})
        approved.append(fixtures.refresh_performance(scenario))
    scenario["p1"], scenario["p2"], scenario["p3"] = approved

    fixtures.issue_license(
        scenario,
        dict(
            US_LICENCE,
            distribution_start="2026-09-01T00:00:00Z",
            distribution_end="2026-12-01T00:00:00Z",
        ),
        performance=scenario["p1"],
    )
    fixtures.issue_license(
        scenario,
        dict(
            US_LICENCE,
            distribution_start="2026-11-01T00:00:00Z",
            distribution_end="2027-01-01T00:00:00Z",
        ),
        performance=scenario["p2"],
    )
    return scenario


def _issue_third_licence(scenario, distribution_end, expected_replica_version=None):
    """Ask for a third US window on the same replica, ending where told."""
    if expected_replica_version is None:
        expected_replica_version = fixtures.refresh_replica(scenario)["version"]
    payload = factories.usage_license_payload(
        scenario["p3"]["id"],
        expected_replica_version,
        channel="ADVERTISING",
        territory_codes=["US"],
        distribution_start="2026-11-15T00:00:00Z",
        distribution_end=distribution_end,
        actual_impressions=12_000_000,
    )
    return api_client.create_usage_license(payload, scenario["licensee_headers"])


def _licence_count_on_third_output(scenario):
    response = api_client.list_usage_licenses(
        scenario["admin_headers"],
        params={"generated_performance_id": scenario["p3"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return len(data)


def test_a_window_past_the_consent_term_is_reported_ahead_of_the_overlap_cap():
    """The end date sits a month past the grant, so the term rule answers.

    The PRD states: "The requested window from `distribution_start` through
    `distribution_end` must lie entirely inside the grant's half-open term from
    `effective_from` to `effective_until`, or issuance is refused with
    `ERR_WINDOW_EXCEEDS_CONSENT_TERM` — a license may not authorise distribution
    past the day consent lapses."

    Design: Difficulty/priority_pair_validation_conflict/window_exceeding_consent_term_outranks_replica_overlap_cap
    """
    scenario = _three_outputs_with_two_overlapping_us_licences()

    validate_error(
        _issue_third_licence(scenario, "2027-09-01T00:00:00Z"),
        "ERR_WINDOW_EXCEEDS_CONSENT_TERM",
    )

    assert _licence_count_on_third_output(scenario) == 0


def test_pulling_the_end_date_inside_the_term_uncovers_the_overlap_cap():
    """Inside the term the same request is the third overlapping US window.

    The PRD states: "At most two usage licenses whose `distribution_status` is
    `ISSUED` or `LIVE` may hold closed inclusive distribution windows that overlap
    on the same `digital_replica_id` while sharing at least one territory code."
    And: "A third such license is refused with `ERR_REPLICA_OVERLAP_CAP_EXCEEDED`."
    Neither rejected attempt may advance the replica the request gated on.

    Design: Difficulty/priority_pair_validation_conflict/window_exceeding_consent_term_outranks_replica_overlap_cap
    """
    scenario = _three_outputs_with_two_overlapping_us_licences()
    replica_version = fixtures.refresh_replica(scenario)["version"]

    _issue_third_licence(scenario, "2027-09-01T00:00:00Z", replica_version)
    validate_error(
        _issue_third_licence(scenario, "2027-06-01T00:00:00Z", replica_version),
        "ERR_REPLICA_OVERLAP_CAP_EXCEEDED",
    )

    assert _licence_count_on_third_output(scenario) == 0
    assertions.assert_versioned(fixtures.refresh_replica(scenario), replica_version)

    entries = fixtures.ledger_entries(
        scenario,
        {"generated_performance_id": scenario["p3"]["id"], "limit": 100},
    )
    assertions.assert_entry_types(entries, ["PER_USE_PROVISIONAL"])
    assertions.assert_ledger_entry(entries[0], "PER_USE_PROVISIONAL", 346_500)
