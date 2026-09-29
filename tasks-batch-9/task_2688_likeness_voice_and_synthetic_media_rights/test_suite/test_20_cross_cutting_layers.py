"""Stale tokens, a repeated ops run, and a filtered page that moves under a write."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADVERTISING_GRANT = {"permitted_use_notes": "Ads"}

SOCIAL_DRAFT = {
    "permitted_media_types": ["SOCIAL"],
    "permitted_use_notes": "Socials",
}

VOICE_SAMPLE = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:aaa",
}

VOICE_BUILD = {"replica_kind": "VOICE", "build_ref": "build-001"}

SPOT_A = {
    "licensee_name": "Northlight",
    "intended_use_description": "Spot A",
    "projected_impressions": 500_000,
}

SPOT_B = {
    "licensee_name": "Northlight",
    "intended_use_description": "Spot B",
    "projected_impressions": 500_000,
    "scheduled_first_use_at": "2026-09-15T00:00:00Z",
}

FOUR_MONTH_WINDOW = {
    "distribution_start": "2026-08-01T00:00:00Z",
    "distribution_end": "2026-12-01T00:00:00Z",
    "actual_impressions": 500_000,
}


def _two_approved_spots_over_one_replica():
    """Two approved outputs on one replica, with both stale tokens captured."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    scenario["talent_version_at_creation"] = scenario["talent"]["version"]
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    scenario["replica_version_at_approval"] = scenario["replica"]["version"]
    fixtures.submit_performance(scenario, SPOT_A)
    fixtures.review_performance(scenario)
    fixtures.submit_performance(scenario, SPOT_B)
    fixtures.review_performance(scenario)
    return scenario


def _draft_a_social_grant(scenario, expected_talent_version):
    """Draft a second, non-exclusive grant echoing the supplied token."""
    payload = factories.consent_grant_payload(
        scenario["talent"]["id"], expected_talent_version, **SOCIAL_DRAFT
    )
    return api_client.create_consent_grant(payload, scenario["admin_headers"])


def _issue_over(scenario, performance, expected_replica_version):
    """Issue a licence over one output echoing the supplied replica token."""
    payload = factories.usage_license_payload(
        performance["id"], expected_replica_version, **FOUR_MONTH_WINDOW
    )
    return api_client.create_usage_license(payload, scenario["licensee_headers"])


def _grants_of(scenario):
    """Every grant standing against the scenario's talent."""
    data, meta = validate_paginated(
        api_client.list_consent_grants(
            scenario["admin_headers"], params={"talent_id": scenario["talent"]["id"]}
        )
    )
    return data, meta


def _licences(scenario):
    """Every licence in the world, with its pagination envelope."""
    return validate_paginated(api_client.list_usage_licenses(scenario["licensee_headers"]))


def test_the_creation_time_talent_token_is_refused_and_the_refreshed_one_lands():
    """The draft that echoes a long-superseded version is the only one turned away.

    The PRD explains why both gates exist: "Two writes in this system bind terms
    that depend on facts the caller read earlier, and in both cases a sequential
    retry would find nothing obviously wrong and would succeed while quietly using
    the wrong facts. Both are therefore guarded by optimistic concurrency control
    against the parent row's `version`." The first gate is stated exactly: "A `POST
    /consent-grants` request must carry `expected_talent_version` as a non-optional
    field, holding the client's last observed `version` of the `Talent` named by
    `talent_id`. If that value does not equal the talent's current `version`, the
    draft is rejected with `ERR_TALENT_VERSION_STALE` (HTTP 412)." A retry would
    otherwise have succeeded: "This matters because a second grant covering the
    same media type and territory is legitimate product behaviour — a non-exclusive
    grant may sit alongside an earlier one — so a drafter working from a stale view
    sees no blocking status field at all. Meanwhile an exclusivity change, a
    suspension or a death record recorded since that read silently rewrites the
    terms the drafter believed were in force." The refreshed token comes from the
    read: "No other endpoint accepts a version field, and none may be added.
    Reading a talent or a replica is how a client obtains the value it must echo
    back — both single-resource reads expose `version` for exactly this purpose."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
    """
    scenario = _two_approved_spots_over_one_replica()
    stale_token = scenario["talent_version_at_creation"]
    current = fixtures.read_talent(scenario)
    assert current["version"] > stale_token

    refused = _draft_a_social_grant(scenario, stale_token)
    validate_error(refused, "ERR_TALENT_VERSION_STALE")
    assert refused.status_code == 412
    _rows, meta = _grants_of(scenario)
    assert meta["total_count"] == 1

    accepted = validate_success(_draft_a_social_grant(scenario, current["version"]), 201)
    assert accepted["permitted_media_types"] == ["SOCIAL"]
    assert accepted["status"] == "PENDING_COUNTERSIGN"

    _rows, meta = _grants_of(scenario)
    assert meta["total_count"] == 2
    assert fixtures.read_talent(scenario)["version"] == current["version"] + 1


def test_the_pre_issuance_replica_token_is_refused_and_the_refreshed_one_lands():
    """The first issuance moves the replica, so the same token fails the second.

    The PRD states the second gate: "A `POST /usage-licenses` request must carry
    `expected_replica_version` as a non-optional field, holding the client's last
    observed `version` of the `DigitalReplica` behind the performance being
    licensed. If that value does not equal the replica's current `version`,
    issuance is rejected with `ERR_REPLICA_VERSION_STALE` (HTTP 412)." A retry
    would have found nothing amiss: "Issuing a second license over the same replica
    and an overlapping territory is legitimate up to the declared overlap cap, so a
    sequential retry would still find the replica `APPROVED_FOR_USE` and would
    itself succeed; only the advanced `version` reveals that the replica's
    approval, its source assets or its open license count moved under the
    licensee's feet." The first issuance is what moved it: "Issuance finally
    increments the replica's `open_license_count` by one, recomputes the grant's
    `total_compensation_cents` and the talent's `lifetime_compensation_cents`, and
    advances the replica's and the talent's `version` by one each." And the cap is
    not what refused the second: "At most two usage licenses whose
    `distribution_status` is `ISSUED` or `LIVE` may hold closed inclusive
    distribution windows that overlap on the same `digital_replica_id` while
    sharing at least one territory code."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
    """
    scenario = _two_approved_spots_over_one_replica()
    spot_a, spot_b = scenario["performances"][0], scenario["performances"][1]
    stale_token = scenario["replica_version_at_approval"]

    first = validate_success(_issue_over(scenario, spot_a, stale_token), 201)
    assert first["distribution_status"] == "ISSUED"

    refused = _issue_over(scenario, spot_b, stale_token)
    validate_error(refused, "ERR_REPLICA_VERSION_STALE")
    assert refused.status_code == 412

    replica = fixtures.refresh_replica(scenario)
    assert replica["version"] == stale_token + 1
    assert replica["open_license_count"] == 1
    assert replica["status"] == "APPROVED_FOR_USE"

    second = validate_success(_issue_over(scenario, spot_b, replica["version"]), 201)
    assert second["distribution_status"] == "ISSUED"
    assert second["generated_performance_id"] == spot_b["id"]
    assert fixtures.refresh_replica(scenario)["open_license_count"] == 2


def test_the_refused_issuance_left_no_licence_row_and_no_ledger_row():
    """Nothing of the rejected write survives anywhere in the record.

    The PRD ties the money to the accepted issuance alone: "The result is written
    to `per_use_final_cents` and posted as a `PER_USE_FINAL` ledger entry split
    three ways." The ledger is the only place such rows can be found: "The
    compensation ledger is readable throughout: a single entry can be read by its
    identifier, and the collection read — filterable by talent, grant, performance,
    license, reversed entry and entry type — is the only channel through which
    entries appended deep inside a cascade, particularly reversals, can be
    discovered at all."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
    """
    scenario = _two_approved_spots_over_one_replica()
    spot_a, spot_b = scenario["performances"][0], scenario["performances"][1]
    stale_token = scenario["replica_version_at_approval"]

    validate_success(_issue_over(scenario, spot_a, stale_token), 201)
    validate_error(_issue_over(scenario, spot_b, stale_token), "ERR_REPLICA_VERSION_STALE")

    _rows, meta = _licences(scenario)
    assert meta["total_count"] == 1

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_FINAL",
        ],
    )


ONE_SPOT = {
    "licensee_name": "Northlight",
    "intended_use_description": "Spot",
    "projected_impressions": 500_000,
    "scheduled_first_use_at": "2026-08-05T00:00:00Z",
}

AUGUST_INTO_SEPTEMBER = {
    "distribution_start": "2026-08-01T00:00:00Z",
    "distribution_end": "2026-09-01T00:00:00Z",
    "actual_impressions": 500_000,
}

FIRST_FLIGHT = {"distribution_reference": "flight-1"}


def _a_live_licence_whose_window_closed_yesterday():
    """One LIVE licence, its window ending 1 September, read at 2 September."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    fixtures.submit_performance(scenario, ONE_SPOT)
    fixtures.review_performance(scenario)
    fixtures.issue_license(scenario, AUGUST_INTO_SEPTEMBER)
    fixtures.attest_disclosure(scenario)
    fixtures.verify_disclosure(scenario)
    fixtures.go_live(scenario, FIRST_FLIGHT)
    fixtures.move_clock("2026-09-02T00:00:00Z", scenario["admin_headers"])
    return scenario


def _cases_of(scenario):
    """Every case standing against the scenario's talent, with its envelope."""
    return validate_paginated(
        api_client.list_infringement_cases(
            scenario["admin_headers"], params={"talent_id": scenario["talent"]["id"]}
        )
    )


def test_the_first_run_raises_the_obligation_and_the_second_run_reports_nothing():
    """A second sweep at the same instant, under a different office, moves no row.

    The PRD states: "Running it twice at the same logical instant changes nothing
    on the second pass — every phase's precondition is already false for the rows
    the first pass moved." The phase that fires is the second: "Phase two opens
    removal obligations on expired licenses: every license whose
    `distribution_status` is `ISSUED` or `LIVE` and whose `distribution_end` is
    strictly earlier than the current logical instant moves to `REMOVAL_PENDING`
    with `removal_reason` of `TERM_EXPIRED` and a fresh `removal_deadline`." The
    deadline is dated from the run: "In every case `removal_deadline` is computed
    as the current logical instant advanced by the domicile profile's
    `removal_window_days`: an obligation raised on 2 August 2027 for a talent in a
    state allowing fourteen days gives a deadline of `2027-08-16T00:00:00Z`, and
    the same obligation for a talent in a state allowing twenty-one days gives
    `2027-08-23T00:00:00Z`." Either office may invoke the run: "The sweep is the
    office's periodic ops run, invoked by a `RightsAdministrator` or a
    `ComplianceOfficer` and evaluated entirely against the current logical clock."

    Design: Corner/cross_cutting_complexity_layers/rerunning_a_sweep_at_the_same_instant_changes_nothing
    """
    scenario = _a_live_licence_whose_window_closed_yesterday()
    assert scenario["license"]["distribution_status"] == "LIVE"

    first_run = fixtures.run_sweep(scenario, scenario["admin_headers"])
    assertions.assert_sweep_counts(
        first_run, expired_license_count=1, removal_pending_count=1
    )

    license_row = fixtures.refresh_license(scenario)
    assert license_row["distribution_status"] == "REMOVAL_PENDING"
    assert license_row["removal_reason"] == "TERM_EXPIRED"
    assert license_row["removal_deadline"] == "2026-09-16T00:00:00Z"

    second_run = fixtures.run_sweep(scenario, scenario["compliance_headers"])
    assertions.assert_sweep_changed_nothing(second_run)


def test_the_second_run_neither_restamped_the_deadline_nor_double_counted_it():
    """One obligation, one version bump, one restricted posture after both runs.

    The PRD counts the obligation once: "The talent's
    `open_removal_obligation_count` increases by one and its `rights_posture` is
    recomputed, and both the license's and the talent's `version` advance by one."
    A talent carrying an open obligation is not clear: "Otherwise, if the talent's
    `open_removal_obligation_count` is greater than zero, or if any consent grant of
    this talent has status `SUSPENDED`, the posture is `RESTRICTED`." Every
    mutation is visible in the row's counter: "Most
    resources additionally carry `updated_at`, of the same format, refreshed on
    every mutation, and `version`, an integer that starts at 1 on creation and
    increases by exactly one on every mutation of that row — including mutations
    the row suffers as a side effect of an operation aimed at some other resource."

    Design: Corner/cross_cutting_complexity_layers/rerunning_a_sweep_at_the_same_instant_changes_nothing
    """
    scenario = _a_live_licence_whose_window_closed_yesterday()
    before = dict(scenario["license"])

    fixtures.run_sweep(scenario, scenario["admin_headers"])
    after_first = fixtures.refresh_license(scenario)
    assertions.assert_version_advanced_by(after_first, before["version"], 1)

    fixtures.run_sweep(scenario, scenario["compliance_headers"])
    after_second = fixtures.refresh_license(scenario)
    assert after_second["version"] == after_first["version"]
    assert after_second["removal_deadline"] == after_first["removal_deadline"]
    assert after_second["removal_confirmed_at"] is None

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(talent, open_removal_obligation_count=1)
    assertions.assert_posture(talent, "RESTRICTED")


def test_neither_run_opened_a_case_while_the_removal_window_is_still_open():
    """Phase three has nothing to punish yet, so no case exists after two runs.

    The PRD states: "Phase three punishes overdue removals. Every license whose
    `distribution_status` is `REMOVAL_PENDING`, whose `removal_deadline` is
    strictly earlier than the current logical instant, and whose
    `removal_confirmed_at` is still null has its `compliance_status` set to
    `NON_COMPLIANT` while its `distribution_status` stays exactly at
    `REMOVAL_PENDING` — this is the phase that demonstrates the two dimensions are
    genuinely independent." Only that phase opens a case on its own: "Each such
    license also causes a fresh infringement case to be opened automatically, with
    `detection_source` of `SWEEP`, a `match_confidence` of 1.000, `suspect_url`
    copied from the license's `distribution_reference`, `detected_state_code` taken
    from the talent's `domicile_state_code`, `detected_channel` taken from the
    license's `channel`, and `matched_usage_license_id` naming that license."

    Design: Corner/cross_cutting_complexity_layers/rerunning_a_sweep_at_the_same_instant_changes_nothing
    """
    scenario = _a_live_licence_whose_window_closed_yesterday()

    fixtures.run_sweep(scenario, scenario["admin_headers"])
    fixtures.run_sweep(scenario, scenario["compliance_headers"])

    _rows, meta = _cases_of(scenario)
    assert meta["total_count"] == 0
    assert fixtures.refresh_license(scenario)["compliance_status"] == "VERIFIED"


TWO_MEDIA_GRANT = {
    "permitted_media_types": ["ADVERTISING", "SOCIAL"],
    "permitted_use_notes": "Ads",
}

SIX_SPOTS = (
    ("Spot 1", "ADVERTISING", "2026-09-01T00:00:00Z"),
    ("Spot 2", "ADVERTISING", "2026-09-02T00:00:00Z"),
    ("Spot 3", "SOCIAL", "2026-09-03T00:00:00Z"),
    ("Spot 4", "SOCIAL", "2026-09-04T00:00:00Z"),
    ("Spot 5", "ADVERTISING", "2026-09-05T00:00:00Z"),
    ("Spot 6", "ADVERTISING", "2026-09-06T00:00:00Z"),
)


def _six_outputs_submitted_in_a_known_order():
    """Six outputs on one replica, two of them social, created Spot 1 to Spot 6."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, TWO_MEDIA_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    for description, media_type, first_use in SIX_SPOTS:
        fixtures.submit_performance(
            scenario,
            {
                "licensee_name": "Northlight",
                "intended_use_description": description,
                "media_type": media_type,
                "projected_impressions": 100_000,
                "scheduled_first_use_at": first_use,
            },
        )
    return scenario


def _page_of_outputs(scenario, **params):
    """One page of the output list, as descriptions plus the page envelope."""
    data, meta = validate_paginated(
        api_client.list_generated_performances(scenario["admin_headers"], params=params)
    )
    return [row["intended_use_description"] for row in data], meta


def _reject(scenario, performance):
    """Reject one output on brand grounds from the talent's side."""
    return validate_success(
        api_client.review_generated_performance(
            performance["id"],
            factories.review_payload("REJECT", rejection_reason="OFF_BRAND"),
            scenario["talent_rep_headers"],
        ),
        200,
    )


def test_the_output_list_pages_in_creation_order_and_derives_has_more_from_the_total():
    """A full last page still reports no more, and a page past the end is empty.

    The PRD fixes the order: "Unless a specific collection says otherwise, lists
    are ordered by `created_at` ascending." It fixes the window too: "`limit`
    controls page size: it defaults to 10, may not be smaller than 1, and may not be
    larger than 100." And it fixes what the envelope means: "Every list response
    reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where
    `total_count` counts the rows matching the filters before the page window is
    applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/cross_cutting_complexity_layers/filtering_sorting_and_paging_compose_on_the_performance_list
    """
    scenario = _six_outputs_submitted_in_a_known_order()

    head, meta = _page_of_outputs(scenario, limit=2, offset=0)
    assert head == ["Spot 1", "Spot 2"]
    assertions.assert_pagination(meta, 2, 0, 6, True)

    tail, meta = _page_of_outputs(scenario, limit=2, offset=4)
    assert tail == ["Spot 5", "Spot 6"]
    assertions.assert_pagination(meta, 2, 4, 6, False)

    past_the_end, meta = _page_of_outputs(scenario, limit=2, offset=6)
    assert past_the_end == []
    assertions.assert_pagination(meta, 2, 6, 6, False)


def test_two_filters_intersect_and_the_total_counts_only_the_filtered_population():
    """Social outputs still awaiting review are two of the six on the table.

    The PRD states: "Collections also accept equality filters, and each filter
    narrows the result set before pagination." The two used here are both declared:
    "Generated performances filter on `digital_replica_id`, `licensee_user_id`,
    `review_status` and `media_type`." What the total counts is the narrowed
    population: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` counts the rows matching the
    filters before the page window is applied and `has_more` is true when rows
    remain beyond the current window."

    Design: Corner/cross_cutting_complexity_layers/filtering_sorting_and_paging_compose_on_the_performance_list
    """
    scenario = _six_outputs_submitted_in_a_known_order()

    rows, meta = _page_of_outputs(
        scenario, review_status="SUBMITTED", media_type="SOCIAL", limit=2, offset=0
    )

    assert rows == ["Spot 3", "Spot 4"]
    assertions.assert_pagination(meta, 2, 0, 2, False)


def test_a_rejected_output_leaves_one_filtered_population_and_joins_another():
    """The same query returns a different page once the row's status moves.

    The PRD states: "`REJECT` moves it `SUBMITTED → REJECTED`, stamping
    `rejection_reason` from the payload — the reasons in the vocabulary are
    `OFF_BRAND`, `OUT_OF_SCOPE`, `QUALITY`, `REVIEW_WINDOW_LAPSED` and
    `REVISION_LIMIT_REACHED` — appending a `REVERSAL` entry that exactly negates the
    live `PER_USE_PROVISIONAL` entry, including the exact negation of its three
    share columns, and setting `provisional_compensation_cents` to zero." The
    filtered view follows that move: "Collections also accept equality filters, and
    each filter narrows the result set before pagination." The row is not gone from
    the table, only from that population: "Every list response reports `limit`,
    `offset`, `total_count` and `has_more` inside `meta`, where `total_count` counts
    the rows matching the filters before the page window is applied and `has_more`
    is true when rows remain beyond the current window."

    Design: Corner/cross_cutting_complexity_layers/filtering_sorting_and_paging_compose_on_the_performance_list
    """
    scenario = _six_outputs_submitted_in_a_known_order()
    third_spot = scenario["performances"][2]
    assert third_spot["intended_use_description"] == "Spot 3"

    rejected = _reject(scenario, third_spot)
    assert rejected["review_status"] == "REJECTED"
    assert rejected["provisional_compensation_cents"] == 0

    remaining, meta = _page_of_outputs(
        scenario, review_status="SUBMITTED", media_type="SOCIAL", limit=2, offset=0
    )
    assert remaining == ["Spot 4"]
    assertions.assert_pagination(meta, 2, 0, 1, False)

    moved, meta = _page_of_outputs(scenario, review_status="REJECTED", limit=10, offset=0)
    assert moved == ["Spot 3"]
    assertions.assert_pagination(meta, 10, 0, 1, False)

    everything, meta = _page_of_outputs(scenario, limit=10, offset=0)
    assert len(everything) == 6
    assert meta["total_count"] == 6
