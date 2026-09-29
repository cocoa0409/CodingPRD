"""Derived numbers with more than one input: retention, posture, reach and floors."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
)

CA_365_PROFILE = {"biometric_retention_max_days": 365, "deletion_grace_days": 30}

NY_180_PROFILE = {
    "state_code": "NY",
    "postmortem_rights_years": 40,
    "postmortem_requires_registration": False,
    "biometric_retention_max_days": 180,
    "deletion_grace_days": 15,
    "removal_window_days": 7,
    "disclosure_required_entertainment": False,
    "min_disclosure_rank_advertising": 4,
    "min_disclosure_rank_entertainment": 1,
}

LONG_TERM_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    territory_codes=["US"],
    permitted_use_notes="Long campaign",
)

SHORT_TERM_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    territory_codes=["US"],
    permitted_use_notes="Short campaign",
    effective_until="2026-10-01T00:00:00Z",
)

NY_TALENT = {
    "legal_name": "Noor Haddad",
    "domicile_state_code": "NY",
    "union_code": "SAG_AFTRA",
}


def _sample_under(scenario, capture_ref, digest):
    """Capture one voice sample under the scenario's current grant."""
    fixtures.register_biometric_asset(
        scenario,
        dict(fixtures.CAMPAIGN_ASSET, capture_ref=capture_ref, payload_digest=digest),
    )
    return scenario["asset"]


def _three_samples_captured_on_the_first_of_august():
    """One sample per arm of the min(): long CA term, short CA term, long NY term."""
    home = fixtures.register_state_law_profile(overrides=CA_365_PROFILE)
    fixtures.register_state_law_profile(home, NY_180_PROFILE)
    fixtures.register_union_minimum(home, fixtures.SAG_ADVERTISING_ROW)

    fixtures.create_talent(home, fixtures.CAMPAIGN_TALENT)
    fixtures.draft_consent_grant(home, LONG_TERM_GRANT)
    fixtures.countersign_grant(home)
    statutory = _sample_under(home, "cap-long-ca", "sha256:a01")

    fixtures.draft_consent_grant(home, SHORT_TERM_GRANT)
    fixtures.countersign_grant(home)
    contractual = _sample_under(home, "cap-short-ca", "sha256:a02")

    away = fixtures.new_scenario()
    fixtures.create_talent(away, NY_TALENT)
    fixtures.draft_consent_grant(away, LONG_TERM_GRANT)
    fixtures.countersign_grant(away)
    shorter_statute = _sample_under(away, "cap-long-ny", "sha256:a03")

    return statutory, contractual, shorter_statute


def test_each_of_the_two_retention_arms_wins_on_the_sample_built_to_suit_it():
    """The statute binds the long term, the contract binds the short one.

    The PRD states: "The statutory deadline is the asset's `created_at` advanced
    by the domicile profile's `biometric_retention_max_days`. The contractual
    deadline is the end of the consent term — `effective_end_actual` when the
    grant has ended, otherwise `effective_until` — advanced by that profile's
    `deletion_grace_days`. `retention_until` is whichever of the two comes first,
    and when the two coincide that shared instant is the answer." Two of the three
    answers are worked outright: "An asset created on 1 August 2026 under a profile
    allowing 365 statutory days and 30 grace days, on a grant whose
    `effective_until` is 1 August 2027, has a statutory deadline of 1 August 2027
    and a contractual deadline of 31 August 2027, so `retention_until` is
    `2027-08-01T00:00:00Z` and the statute binds." And: "For a talent in a state
    allowing only 180 statutory days and 15 grace days, the same asset and term
    give a statutory deadline of 28 January 2027 against a contractual deadline of
    16 August 2027, so `retention_until` is `2027-01-28T00:00:00Z`." The profile
    consulted is the talent's own: "Profiles are matched to work by state code, not
    by foreign key: a talent's `domicile_state_code` selects the profile whose
    `state_code` equals it, and an infringement case's `detected_state_code` selects
    the profile for the state where a suspected use was observed."

    Design: Corner/calculations/retention_deadline_takes_the_earlier_of_statute_and_consent_end_plus_grace
    """
    statutory, contractual, shorter_statute = _three_samples_captured_on_the_first_of_august()

    assert statutory["retention_until"] == "2027-08-01T00:00:00Z"
    assert contractual["retention_until"] == "2026-10-31T00:00:00Z"
    assert shorter_statute["retention_until"] == "2027-01-28T00:00:00Z"

    for asset in (statutory, contractual, shorter_statute):
        assert asset["status"] == "STORED"
        assertions.assert_fields_null(asset, "purged_at")


SEVERE_DETECTION = {
    "suspect_url": "https://pirate.example/clip",
    "detected_view_count": 10_000_000,
    "match_confidence": 1.000,
}


def test_only_the_escalated_leg_of_the_case_walk_freezes_the_talent():
    """A severe case freezes nothing until it reaches legal, and thaws on closure.

    The PRD states: "If any infringement case of this talent has status
    `LEGAL_ESCALATED`, the posture is `FROZEN`. Otherwise, if the talent's
    `open_removal_obligation_count` is greater than zero, or if any consent grant of
    this talent has status `SUSPENDED`, the posture is `RESTRICTED`. Otherwise the
    posture is `CLEAR`." Closure takes the case back out of that input set:
    "Terminal case statuses — `DISMISSED_LICENSED`, `DISMISSED_NO_ACTION`,
    `RESOLVED_REMOVED`, `CLOSED_SETTLED` and `CLOSED_LITIGATED` — contribute
    nothing, and neither do the terminal grant statuses `REVOKED` and `EXPIRED`."
    The second counter is reported but does not vote: "The second counter does not
    enter the posture formula; it exists so that an operator can see at a glance how
    much material is impounded." The score itself is stored once and never revised:
    "Two computations run at the moment the case is persisted."

    Design: Corner/calculations/only_legal_escalated_cases_enter_the_posture_input_set
    """
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    fixtures.open_case(scenario, SEVERE_DETECTION)

    assert scenario["case"]["severity_score"] == 0.8950
    assert scenario["case"]["status"] == "DETECTED"
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")

    issued = fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    assert issued["status"] == "TAKEDOWN_ISSUED"
    assert issued["takedown_issued_at"] == "2026-08-01T00:00:00Z"
    assert issued["triaged_by_user_id"] == scenario["compliance_user_id"]
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")

    escalated = fixtures.escalate_case(scenario)
    assert escalated["status"] == "LEGAL_ESCALATED"
    assert escalated["escalated_by_user_id"] == scenario["second_admin_user_id"]
    assert escalated["legal_hold_applied_count"] == 0

    frozen = fixtures.read_talent(scenario)
    assertions.assert_posture(frozen, "FROZEN")
    assertions.assert_talent_counters(
        frozen, legal_hold_asset_count=0, open_removal_obligation_count=0
    )

    closed = fixtures.close_case(
        scenario, "SETTLED", headers=scenario["second_admin_headers"]
    )
    assert closed["status"] == "CLOSED_SETTLED"
    assert closed["closure_outcome"] == "SETTLED"

    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")
    assert fixtures.refresh_case(scenario)["severity_score"] == 0.8950


SINGLE_TERRITORY_SPOT = dict(
    fixtures.CAMPAIGN_PERFORMANCE,
    territory_codes=["US"],
    projected_impressions=500_000,
)


def _approved_replica_for(scenario, capture_ref, build_ref):
    """Take one talent from an ACTIVE grant to an APPROVED_FOR_USE replica."""
    fixtures.draft_consent_grant(scenario, LONG_TERM_GRANT)
    fixtures.countersign_grant(scenario)
    _sample_under(scenario, capture_ref, "sha256:a01")
    fixtures.build_replica(scenario, dict(fixtures.CAMPAIGN_REPLICA, build_ref=build_ref))
    fixtures.approve_replica(scenario)
    return scenario


def _one_output_in_each_state():
    """Two outputs submitted at the same instant by talents in two states."""
    home = fixtures.register_state_law_profile()
    fixtures.register_state_law_profile(home, NY_180_PROFILE)
    fixtures.register_union_minimum(home, fixtures.SAG_ADVERTISING_ROW)

    fixtures.create_talent(home, fixtures.CAMPAIGN_TALENT)
    _approved_replica_for(home, "cap-ca", "build-ca")

    away = fixtures.new_scenario()
    fixtures.create_talent(away, NY_TALENT)
    _approved_replica_for(away, "cap-ny", "build-ny")

    fixtures.submit_performance(
        home, dict(SINGLE_TERRITORY_SPOT, intended_use_description="CA spot")
    )
    fixtures.submit_performance(
        away, dict(SINGLE_TERRITORY_SPOT, intended_use_description="NY spot")
    )
    return home["performance"], away["performance"]


def test_the_review_window_is_seven_days_in_both_states():
    """Two states disagree on every other duration; the review window is fixed.

    The PRD states: "A new submission is `SUBMITTED` with `revision_round` at zero,
    `reviewed_by_user_id`, `rejection_reason` and `review_note` all null, and a
    `review_deadline` set to the current logical instant advanced by the seven-day
    review window." The instant it is measured from is the clock, not the schedule
    the licensee proposes: "Before any caller moves it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`; that is the fixed startup default, and the
    server never falls back to real time." The accrual is measured from the
    performance's own declarations: "reach is the performance's own
    `projected_impressions` and the territory count is the size of the performance's
    `territory_codes`." Five hundred thousand impressions sit in the lowest reach
    tier, because the reach factor "is 1.00 when reach is at most one million, 1.40
    when reach is above one million and at most ten million, and 1.90 above ten
    million", and one territory leaves the territory factor where it starts, since it
    "starts at 1.00 and adds 0.10 for each territory beyond the first — one territory
    gives 1.00, two give 1.10, ten give 1.90."

    Design: Corner/calculations/review_deadline_is_minted_from_the_review_window_constant
    """
    californian, new_yorker = _one_output_in_each_state()

    for performance in (californian, new_yorker):
        assert performance["review_deadline"] == "2026-08-08T00:00:00Z"
        assert performance["review_status"] == "SUBMITTED"
        assert performance["revision_round"] == 0
        assertions.assert_fields_null(performance, "reviewed_by_user_id")
        assert performance["provisional_compensation_cents"] == 225_000
        assert performance["scheduled_first_use_at"] == "2026-09-01T00:00:00Z"


TIER_PROBES = (
    ("tier1 upper bound", 1_000_000, 247_500),
    ("tier2 lower bound", 1_000_001, 346_500),
    ("tier2 upper bound", 10_000_000, 346_500),
    ("tier3 lower bound", 10_000_001, 470_250),
)


def test_both_reach_tiers_include_their_own_upper_bound():
    """One impression either side of each boundary, on otherwise identical outputs.

    The PRD states that the reach factor "is 1.00 when reach is at most one million,
    1.40 when reach is above one million and at most ten million, and 1.90 above ten
    million." Each tier prices the whole volume: "The grant's
    `per_use_base_fee_cents` is multiplied by the reach factor, then by the media
    multiplier, then by the territory factor, and the composed product is rounded
    half up to a whole number of cents exactly once." Two territories put the
    territory factor at 1.10, since it "starts at 1.00 and adds 0.10 for each
    territory beyond the first — one territory gives 1.00, two give 1.10, ten give
    1.90", and each accrual is posted as it is earned: "The result is written to
    `provisional_compensation_cents` and posted as a `PER_USE_PROVISIONAL` ledger
    entry split three ways; the grant's `total_compensation_cents` and the talent's
    `lifetime_compensation_cents` are recomputed, and the talent's `version` advances
    by one."

    Design: Corner/calculations/reach_multiplier_tiers_switch_exactly_at_their_upper_bounds
    """
    scenario = fixtures.campaign_approved_replica()

    for description, projection, expected in TIER_PROBES:
        fixtures.submit_performance(
            scenario,
            dict(
                fixtures.CAMPAIGN_PERFORMANCE,
                intended_use_description=description,
                projected_impressions=projection,
            ),
        )
        assert scenario["performance"]["provisional_compensation_cents"] == expected

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
        ],
    )
    assert sum(entry["amount_cents"] for entry in entries[1:]) == 1_410_750
    assertions.assert_ledger_sums_to(entries, 1_710_750)
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 1_710_750


SEPTEMBER_UNION_ROW = {
    "union_code": "SAG_AFTRA",
    "media_type": "ADVERTISING",
    "effective_from": "2026-09-01T00:00:00Z",
    "minimum_initial_cents": 500_000,
    "minimum_per_use_cents": 250_000,
}

AUGUST_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    territory_codes=["US"],
    permitted_use_notes="August campaign",
    initial_creation_fee_cents=250_000,
)

SEPTEMBER_GRANT = dict(
    AUGUST_GRANT,
    permitted_use_notes="September campaign",
    effective_from="2026-09-01T00:00:00Z",
    effective_until="2027-09-01T00:00:00Z",
)


def test_the_floor_comes_from_the_row_in_force_not_the_row_filed_first():
    """Rows filed newest-first still apply oldest-first, and the floor changes.

    The PRD states: "Among those candidates, only rows whose `effective_from` is at
    or before the reference date qualify, and the qualifying row with the greatest
    `effective_from` wins; should two qualifying rows share that same
    `effective_from`, the one with the earlier `created_at` wins. The reference date
    is the grant's `effective_from` for the initial creation payment and for per-use
    pricing alike." A later floor is a new row rather than an edit: "A
    `UnionMinimumSchedule` row is a statement of one union's floor as of one
    effective date and is never edited — a change in the floor is a new row with a
    later `effective_from`." The August answer is worked outright: "The same scope at
    a negotiated 250000 gives `initial_compensation_cents` of 300000 and
    `union_topup_cents` of 50000." The two ledger movements follow the same rule:
    "One entry of type `INITIAL_CREATION` is appended for the rounded amount, and
    only when the union floor strictly exceeds that amount is a second entry of type
    `UNION_TOPUP` appended for the difference."

    Design: Corner/calculations/union_schedule_selection_is_chronological_not_insertion_ordered
    """
    scenario = fixtures.register_state_law_profile()
    fixtures.register_union_minimum(scenario, SEPTEMBER_UNION_ROW)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)

    fixtures.draft_consent_grant(scenario, AUGUST_GRANT)
    fixtures.countersign_grant(scenario)
    august = fixtures.refresh_grant(scenario)

    assert august["initial_compensation_cents"] == 300_000
    assert august["union_topup_cents"] == 50_000
    assert august["total_compensation_cents"] == 300_000

    entries = fixtures.grant_ledger(scenario, august)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION", "UNION_TOPUP"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 250_000)
    assertions.assert_ledger_entry(entries[1], "UNION_TOPUP", 50_000)

    fixtures.move_clock("2026-09-01T00:00:00Z", scenario["admin_headers"])
    fixtures.draft_consent_grant(scenario, SEPTEMBER_GRANT)
    fixtures.countersign_grant(scenario)
    september = fixtures.refresh_grant(scenario)

    assert september["initial_compensation_cents"] == 500_000
    assert september["union_topup_cents"] == 250_000
    assert september["total_compensation_cents"] == 500_000

    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=800_000
    )


CONFIDENT_DETECTION = {
    "suspect_url": "https://pirate.example/a",
    "detected_view_count": 8_000_000,
    "match_confidence": 0.900,
}

SECOND_TALENT = {"legal_name": "Bo Lindqvist", "union_code": "SAG_AFTRA"}


def _one_clear_and_one_restricted_talent():
    """Two talents identical but for a suspended grant on the second."""
    clear = fixtures.register_state_law_profile()
    fixtures.register_union_minimum(clear, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(clear, fixtures.CAMPAIGN_TALENT)

    restricted = fixtures.new_scenario()
    fixtures.create_talent(restricted, SECOND_TALENT)
    fixtures.draft_consent_grant(restricted, LONG_TERM_GRANT)
    fixtures.countersign_grant(restricted)
    fixtures.suspend_grant(restricted, overrides={"suspension_reason": "COMPLIANCE_HOLD"})

    assertions.assert_posture(fixtures.read_talent(clear), "CLEAR")
    assertions.assert_posture(fixtures.read_talent(restricted), "RESTRICTED")
    return clear, restricted


def test_the_posture_term_and_the_reach_cap_are_each_visible_on_their_own():
    """Same detection, two postures: 0.0450 apart; and the reach term stops at 0.25.

    The PRD states: "the score is `match_confidence` weighted at 0.60, plus a
    saturating reach term weighted at 0.25, plus a posture term weighted at 0.15,
    with the sum rounded half up to four decimal places." The reach term has a
    ceiling: "The reach term is `detected_view_count` divided by ten million, capped
    at 1.0, so anything at or above ten million views contributes the full reach
    weight." The third term is read from the talent as it stands when the detection
    arrives, and it "maps `FROZEN` to 1.0, `RESTRICTED` to 0.6 and `CLEAR` to 0.3."
    The second talent is restricted rather than frozen because "if
    any consent grant of this talent has status `SUSPENDED`, the posture is
    `RESTRICTED`", and the terms are separable because "Because the three weights sum
    to exactly 1.00, the score always lies between 0 and 1." A score above the bar
    cannot be waved away: "A case whose `severity_score` is at or above 0.7500 may
    not be dismissed at all — the only permitted decision is `ISSUE_TAKEDOWN` — and
    the attempt is refused with `ERR_TAKEDOWN_MANDATORY`." Each case is born
    untriaged: "A new case is `DETECTED` with `legal_hold_applied_count` at zero and
    `triaged_by_user_id`, `escalated_by_user_id`, `closed_by_user_id`,
    `takedown_issued_at` and `closure_outcome` all null."

    Design: Corner/calculations/severity_weights_isolate_the_posture_term_and_saturate_the_reach_term
    """
    clear, restricted = _one_clear_and_one_restricted_talent()

    fixtures.open_case(clear, CONFIDENT_DETECTION)
    against_clear = clear["case"]
    fixtures.open_case(
        restricted, dict(CONFIDENT_DETECTION, suspect_url="https://pirate.example/b")
    )
    against_restricted = restricted["case"]
    fixtures.open_case(
        clear,
        dict(
            CONFIDENT_DETECTION,
            suspect_url="https://pirate.example/c",
            detected_view_count=20_000_000,
        ),
    )
    saturated = clear["case"]

    assert against_clear["severity_score"] == 0.7850
    assert against_restricted["severity_score"] == 0.8300
    assert round(against_restricted["severity_score"] - against_clear["severity_score"], 4) == 0.0450
    assert saturated["severity_score"] == 0.8350

    for case in (against_clear, against_restricted, saturated):
        assert case["status"] == "DETECTED"
        assertions.assert_fields_null(case, "triaged_by_user_id")

    refused = api_client.triage_infringement_case(
        against_clear["id"],
        factories.triage_payload("DISMISS"),
        clear["compliance_headers"],
    )
    validate_error(refused, "ERR_TAKEDOWN_MANDATORY")
    assert fixtures.refresh_case(clear, against_clear)["status"] == "DETECTED"
