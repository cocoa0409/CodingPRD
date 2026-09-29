"""Opposite interval semantics: consent terms half-open, distribution closed."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

EPISODIC_UNION_ROW = {
    "union_code": "SAG_AFTRA",
    "media_type": "EPISODIC",
    "effective_from": "2026-07-01T00:00:00Z",
    "minimum_initial_cents": 200_000,
    "minimum_per_use_cents": 100_000,
}

EXCLUSIVE_AUTUMN_TERM = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US", "MX"],
    "permitted_use_notes": "Exclusive autumn window",
    "exclusivity": "EXCLUSIVE",
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_until": "2027-02-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}

ADJACENT_SUCCESSOR = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US", "MX"],
    "permitted_use_notes": "Adjacent successor term",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2027-02-01T00:00:00Z",
    "effective_until": "2027-08-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}

ONE_DAY_TOO_EARLY = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US"],
    "permitted_use_notes": "One day too early",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2027-01-31T00:00:00Z",
    "effective_until": "2027-06-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}

DIFFERENT_MEDIUM = {
    "permitted_media_types": ["EPISODIC"],
    "territory_codes": ["US", "MX"],
    "permitted_use_notes": "Overlapping in time but a different medium",
    "exclusivity": "EXCLUSIVE",
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_until": "2026-12-01T00:00:00Z",
    "initial_creation_fee_cents": 200_000,
    "per_use_base_fee_cents": 100_000,
}

DISJOINT_TERRITORY = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["JP"],
    "permitted_use_notes": "Overlapping in time but a disjoint territory",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_until": "2026-12-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}


def _talent_under_an_exclusive_autumn_term():
    """One ACTIVE EXCLUSIVE grant over ADVERTISING in US and MX until February."""
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.register_union_minimum(scenario, EPISODIC_UNION_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    fixtures.draft_consent_grant(scenario, EXCLUSIVE_AUTUMN_TERM)
    fixtures.countersign_grant(scenario)
    return scenario


def _draft(scenario, overrides):
    """Draft one more grant on the fresh talent version, outcome unasserted."""
    talent = fixtures.read_talent(scenario)
    payload = factories.consent_grant_payload(
        talent["id"], talent["version"], **overrides
    )
    return api_client.create_consent_grant(payload, scenario["admin_headers"])


def _grant_count(scenario):
    """How many grants the talent actually holds."""
    response = api_client.list_consent_grants(
        scenario["admin_headers"],
        params={"talent_id": scenario["talent"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return len(data)


def test_a_term_starting_where_the_exclusive_term_ends_is_adjacent_not_overlapping():
    """February the first is legal; January the thirty-first is one day too many.

    The PRD states: "Two grants conflict when their half-open terms overlap and
    they share at least one member of `permitted_media_types` and at least one
    member of `territory_codes`. An `EXCLUSIVE` draft may not conflict with any such
    grant, and a `NON_EXCLUSIVE` draft may not conflict with an existing `EXCLUSIVE`
    one. Two `NON_EXCLUSIVE` grants may overlap freely. Adjacency is not overlap:
    one term ending exactly where the next begins is permitted, because the first
    term excludes its own end instant. A conflict is refused with
    `ERR_EXCLUSIVITY_WINDOW_CONFLICT`." The rule is stated on that half-open shape:
    "A consent term is half-open: it runs from `effective_from` inclusive to
    `effective_until` exclusive."

    Design: Difficulty/resource_temporal_overlap/exclusive_consent_term_half_open_adjacency_permitted
    """
    scenario = _talent_under_an_exclusive_autumn_term()

    successor = validate_success(_draft(scenario, ADJACENT_SUCCESSOR), 201)
    assert successor["status"] == "PENDING_COUNTERSIGN"
    assert successor["effective_from"] == "2027-02-01T00:00:00Z"

    validate_error(_draft(scenario, ONE_DAY_TOO_EARLY), "ERR_EXCLUSIVITY_WINDOW_CONFLICT")

    assert _grant_count(scenario) == 2


def test_the_conflict_needs_time_and_media_and_territory_to_intersect_at_once():
    """Overlapping in time is harmless when the medium or the map is disjoint.

    The PRD states: "Take the draft's half-open term from `effective_from` to
    `effective_until` and compare it with the term of every other grant of the same
    talent that is not in a terminal status — that is, every grant that is not
    `REVOKED` and not `EXPIRED`. Two grants conflict when their half-open terms
    overlap and they share at least one member of `permitted_media_types` and at
    least one member of `territory_codes`."

    Design: Difficulty/resource_temporal_overlap/exclusive_consent_term_half_open_adjacency_permitted
    """
    scenario = _talent_under_an_exclusive_autumn_term()

    episodic = validate_success(_draft(scenario, DIFFERENT_MEDIUM), 201)
    assert episodic["permitted_media_types"] == ["EPISODIC"]
    assert episodic["exclusivity"] == "EXCLUSIVE"

    elsewhere = validate_success(_draft(scenario, DISJOINT_TERRITORY), 201)
    assert elsewhere["territory_codes"] == ["JP"]

    assert _grant_count(scenario) == 3


def test_only_the_countersigned_exclusive_term_moved_any_money():
    """The exclusivity factor lifts 300000 to 405000 and a draft posts nothing.

    The PRD states: "The **exclusivity factor** is 1.35 for an `EXCLUSIVE` grant and
    1.00 for a `NON_EXCLUSIVE` one. The negotiated `initial_creation_fee_cents` is
    multiplied by the breadth factor, then by the duration factor, then by the
    exclusivity factor, and the fully composed product is rounded half up to a whole
    number of cents exactly once — never factor by factor." The floor does not bind:
    "`initial_compensation_cents` is then whichever is greater, the rounded amount or
    the floor, and `union_topup_cents` is the amount by which the floor exceeds the
    rounded amount, or zero when it does not exceed it." A drafted successor is not a
    payment: "Drafting stamps `status` as `PENDING_COUNTERSIGN`, records the drafting
    administrator as `drafted_by_user_id`, leaves `suspension_reason`,
    `countersigned_at` and `effective_end_actual` null, and initialises
    `initial_compensation_cents`, `union_topup_cents` and `total_compensation_cents`
    to zero."

    Design: Difficulty/resource_temporal_overlap/exclusive_consent_term_half_open_adjacency_permitted
    """
    scenario = _talent_under_an_exclusive_autumn_term()
    successor = validate_success(_draft(scenario, ADJACENT_SUCCESSOR), 201)
    assert successor["total_compensation_cents"] == 0

    exclusive = fixtures.refresh_grant(scenario)
    assert exclusive["initial_compensation_cents"] == 405_000
    assert exclusive["union_topup_cents"] == 0
    assert exclusive["total_compensation_cents"] == 405_000

    entries = fixtures.talent_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(
        entries[0], "INITIAL_CREATION", 405_000, 303_750, 81_000, 20_250
    )
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=405_000
    )


US_ONLY = {"channel": "ADVERTISING", "territory_codes": ["US"], "actual_impressions": 12_000_000}

THREE_OUTPUTS = (
    {"intended_use_description": "Autumn radio spot"},
    {"intended_use_description": "Winter radio spot"},
    {"intended_use_description": "Spring radio spot"},
)


def _two_us_windows_the_second_running_into_december():
    """Two ISSUED US windows on one replica: Sep-Dec and Nov-Feb."""
    scenario = fixtures.campaign_approved_replica()
    approved = []
    for overrides in THREE_OUTPUTS:
        fixtures.submit_performance(
            scenario, dict(fixtures.CAMPAIGN_PERFORMANCE, **overrides)
        )
        fixtures.review_performance(scenario, "APPROVE", {"review_note": "ok"})
        approved.append(fixtures.refresh_performance(scenario))
    scenario["p1"], scenario["p2"], scenario["p3"] = approved

    fixtures.issue_license(
        scenario,
        dict(
            US_ONLY,
            distribution_start="2026-09-01T00:00:00Z",
            distribution_end="2026-12-01T00:00:00Z",
        ),
        performance=scenario["p1"],
    )
    scenario["l1"] = scenario["license"]
    fixtures.issue_license(
        scenario,
        dict(
            US_ONLY,
            distribution_start="2026-11-01T00:00:00Z",
            distribution_end="2027-02-01T00:00:00Z",
        ),
        performance=scenario["p2"],
    )
    scenario["l2"] = scenario["license"]
    scenario["replica_version"] = fixtures.refresh_replica(scenario)["version"]
    return scenario


def _issue_third_window(scenario, distribution_start):
    """Ask for a third US window starting where told, outcome unasserted."""
    payload = factories.usage_license_payload(
        scenario["p3"]["id"],
        scenario["replica_version"],
        channel="ADVERTISING",
        territory_codes=["US"],
        distribution_start=distribution_start,
        distribution_end="2027-03-01T00:00:00Z",
        actual_impressions=12_000_000,
    )
    return api_client.create_usage_license(payload, scenario["licensee_headers"])


def _licences_on_the_third_output(scenario):
    """Every licence standing against the third approved output."""
    response = api_client.list_usage_licenses(
        scenario["admin_headers"],
        params={"generated_performance_id": scenario["p3"]["id"], "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return data


def test_a_window_beginning_on_the_day_another_ends_is_the_third_overlap():
    """Touching the first window's last day makes the cap bite.

    The PRD states: "At most two usage licenses whose `distribution_status` is
    `ISSUED` or `LIVE` may hold closed inclusive distribution windows that overlap
    on the same `digital_replica_id` while sharing at least one territory code.
    Touching windows count as overlapping — one window ending exactly on the day the
    next begins is an overlap for this purpose, unlike consent terms, where adjacency
    is permitted. A third such license is refused with
    `ERR_REPLICA_OVERLAP_CAP_EXCEEDED`." The windows are read closed on both sides:
    "A distribution window is closed: it runs from `distribution_start` through
    `distribution_end`, both inclusive."

    Design: Difficulty/resource_temporal_overlap/license_distribution_windows_closed_inclusive_touch_counts_toward_cap
    """
    scenario = _two_us_windows_the_second_running_into_december()

    validate_error(
        _issue_third_window(scenario, "2026-12-01T00:00:00Z"),
        "ERR_REPLICA_OVERLAP_CAP_EXCEEDED",
    )

    assert _licences_on_the_third_output(scenario) == []
    assert fixtures.refresh_replica(scenario)["version"] == scenario["replica_version"]
    for held in ("l1", "l2"):
        surviving = fixtures.refresh_license(scenario, scenario[held])
        assert surviving["distribution_status"] == "ISSUED"
        assert surviving["compliance_status"] == "PENDING_LABEL"


def test_one_day_clear_of_that_window_leaves_only_two_overlapping():
    """Starting on the second of December issues, and prices itself alone.

    The PRD states: "The **final per-use royalty** is computed at issuance by the
    same formula the provisional accrual used, with two substitutions: reach is the
    license's `actual_impressions` rather than the performance's projection, and the
    territory count is the size of the license's `territory_codes`, which may be a
    strict subset of the performance's declared territories or a different selection
    within the grant's scope." The licensee's total follows: "`compliance_surcharge_cents`
    is the subtotal multiplied by that rate and rounded **up** to the next whole cent
    — not half up, as every royalty is. `license_total_cents` is the subtotal plus
    that surcharge."

    Design: Difficulty/resource_temporal_overlap/license_distribution_windows_closed_inclusive_touch_counts_toward_cap
    """
    scenario = _two_us_windows_the_second_running_into_december()
    validate_error(
        _issue_third_window(scenario, "2026-12-01T00:00:00Z"),
        "ERR_REPLICA_OVERLAP_CAP_EXCEEDED",
    )

    issued = validate_success(
        _issue_third_window(scenario, "2026-12-02T00:00:00Z"), 201
    )

    assert issued["distribution_status"] == "ISSUED"
    assert issued["per_use_final_cents"] == 427_500
    assert issued["compliance_surcharge_cents"] == 7_482
    assert issued["license_total_cents"] == 434_982
    assert len(_licences_on_the_third_output(scenario)) == 1
