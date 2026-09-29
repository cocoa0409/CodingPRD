"""Every refusal names itself: per-entity not-founds and per-dimension state errors."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _one_talent_on_the_books():
    """A registered California profile and one living talent, so 404s are misses."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    return scenario


def _six_reads_of_nothing(headers):
    """One unknown-identifier read per entity family, each with the id it must report."""
    return (
        (
            lambda: api_client.get_estate_authority(NON_EXISTENT_UUID, headers),
            "ERR_ESTATE_AUTHORITY_NOT_FOUND",
        ),
        (
            lambda: api_client.get_generated_performance(NON_EXISTENT_UUID, headers),
            "ERR_GENERATED_PERFORMANCE_NOT_FOUND",
        ),
        (
            lambda: api_client.get_usage_license(NON_EXISTENT_UUID, headers),
            "ERR_USAGE_LICENSE_NOT_FOUND",
        ),
        (
            lambda: api_client.get_infringement_case(NON_EXISTENT_UUID, headers),
            "ERR_INFRINGEMENT_CASE_NOT_FOUND",
        ),
        (
            lambda: api_client.get_compensation_entry(NON_EXISTENT_UUID, headers),
            "ERR_COMPENSATION_ENTRY_NOT_FOUND",
        ),
        (
            lambda: api_client.get_talent(NON_EXISTENT_UUID, headers),
            "ERR_TALENT_NOT_FOUND",
        ),
    )


def test_each_unknown_identifier_answers_with_the_error_id_of_its_own_entity():
    """Six families, six distinct not-found identifiers, all of them 404.

    The PRD states:
    "Existence checks follow, in this internal order: `ERR_TALENT_NOT_FOUND` (a talent
    id from the path or body, as used by the talent read, the talent's
    estate-authority list and submission, the death record, and consent drafting);
    `ERR_ESTATE_AUTHORITY_NOT_FOUND` (estate-authority verification, and the
    `estate_authority_id` supplied on a consent draft); `ERR_CONSENT_GRANT_NOT_FOUND`
    (the grant read, countersign, suspension and revoke, plus the `consent_grant_id`
    supplied when registering a biometric asset or building a replica);
    `ERR_BIOMETRIC_ASSET_NOT_FOUND` (the asset read, the manual purge, and every
    member of `source_asset_ids` on a replica build); `ERR_DIGITAL_REPLICA_NOT_FOUND`
    (the replica read, approval for use, and the `digital_replica_id` on a performance
    submission); `ERR_GENERATED_PERFORMANCE_NOT_FOUND` (the performance read, review,
    resubmission, and the `generated_performance_id` on a license issuance);
    `ERR_USAGE_LICENSE_NOT_FOUND` (the license read, disclosure attestation,
    disclosure verification, go-live, removal confirmation, and the
    `matched_usage_license_id` optionally supplied when opening a case);
    `ERR_INFRINGEMENT_CASE_NOT_FOUND` (the case read, triage, escalation and closure);
    and `ERR_COMPENSATION_ENTRY_NOT_FOUND` (the ledger entry read). Each of these
    rungs governs wherever an identifier of that type is accepted, and all of them
    carry HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_distinct_per_entity
    """
    scenario = _one_talent_on_the_books()

    for read, expected_error_id in _six_reads_of_nothing(scenario["admin_headers"]):
        response = read()
        validate_error(response, expected_error_id)
        assert response.status_code == 404


def test_the_misses_are_per_row_and_wear_the_ordinary_error_envelope():
    """The talent that does exist still reads 200 beside the six refusals.

    The PRD states: "All error API responses (4xx status codes) follow this standard
    envelope format:" and the not-found rungs share one status: "Each of these rungs
    governs wherever an identifier of that type is accepted, and all of them carry
    HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_distinct_per_entity
    """
    scenario = _one_talent_on_the_books()
    headers = scenario["admin_headers"]

    response = api_client.get_talent(NON_EXISTENT_UUID, headers)
    validate_error(response, "ERR_TALENT_NOT_FOUND")
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].strip() != ""
    assert body["data"]["message"].strip() != ""

    present = validate_success(api_client.get_talent(scenario["talent"]["id"], headers), 200)
    assert present["id"] == scenario["talent"]["id"]
    assert present["life_status"] == "LIVING"


WYOMING_TALENT = {"legal_name": "Wyatt Boone", "domicile_state_code": "WY"}

DETECTED_IN_WYOMING = {
    "detection_source": "MANUAL_REPORT",
    "suspect_url": "https://pirate.example/wy",
    "detected_state_code": "WY",
    "detected_view_count": 5_000,
    "match_confidence": 0.600,
}

DETECTED_AT_HOME = dict(
    DETECTED_IN_WYOMING,
    suspect_url="https://pirate.example/ca",
    detected_state_code="CA",
)


def _talents_on_the_books(scenario):
    """Every talent record the office holds."""
    data, meta = validate_paginated(
        api_client.list_talents(scenario["admin_headers"], params={"limit": 100})
    )
    return data, meta


def _open_case(scenario, overrides):
    """Open one case without asserting the outcome."""
    return api_client.create_infringement_case(
        factories.infringement_case_payload(scenario["talent"]["id"], **overrides),
        scenario["compliance_headers"],
    )


def test_an_unregistered_state_blocks_both_the_domicile_and_the_use_state_paths():
    """Wyoming is unknown to the office, so neither the talent nor the case lands.

    The PRD states: "Profiles are matched to work by state code, not by foreign key: a
    talent's `domicile_state_code` selects the profile whose `state_code` equals it, and
    an infringement case's `detected_state_code` selects the profile for the state where
    a suspected use was observed. Whenever an operation needs a profile that does not
    exist, it fails with `ERR_STATE_LAW_PROFILE_MISSING` (HTTP 422). That applies to
    creating a talent, recording a death, drafting a consent grant, registering a
    biometric asset, issuing a usage license, attesting a disclosure, and opening an
    infringement case — for a case, both the talent's domicile profile and the detected
    state's profile must exist." The case rung is stated again where cases are opened:
    "Both the talent's domicile profile and the detected state's profile must exist, or
    the case cannot be opened."

    Design: Corner/errors/missing_state_law_profile_blocks_talent_and_case_creation
    """
    scenario = _one_talent_on_the_books()

    refused_talent = api_client.create_talent(
        factories.talent_payload(**WYOMING_TALENT), scenario["admin_headers"]
    )
    validate_error(refused_talent, "ERR_STATE_LAW_PROFILE_MISSING")
    assert refused_talent.status_code == 422

    talents, meta = _talents_on_the_books(scenario)
    assert meta["total_count"] == 1
    assert [row["id"] for row in talents] == [scenario["talent"]["id"]]

    validate_error(
        _open_case(scenario, DETECTED_IN_WYOMING), "ERR_STATE_LAW_PROFILE_MISSING"
    )
    _cases, case_meta = validate_paginated(
        api_client.list_infringement_cases(scenario["compliance_headers"])
    )
    assert case_meta["total_count"] == 0


def test_the_same_detection_inside_the_registered_state_opens_and_scores():
    """0.600 confidence on five thousand views against a CLEAR talent is 0.4051.

    The PRD states: "Confidence dominates it: the score is `match_confidence` weighted
    at 0.60, plus a saturating reach term weighted at 0.25, plus a posture term weighted
    at 0.15, with the sum rounded half up to four decimal places. The reach term is
    `detected_view_count` divided by ten million, capped at 1.0, so anything at or above
    ten million views contributes the full reach weight." The living talent's answer on
    the second computation is fixed too: "`enforceable_under_use_state` is true when the
    talent is `LIVING`, and for a `DECEASED` talent is true only when
    `use_state_rights_until` is non-null and at or after the current logical instant." And
    the opening posture is fixed: "A new case is `DETECTED` with `legal_hold_applied_count`
    at zero and `triaged_by_user_id`, `escalated_by_user_id`, `closed_by_user_id`,
    `takedown_issued_at` and `closure_outcome` all null."

    Design: Corner/errors/missing_state_law_profile_blocks_talent_and_case_creation
    """
    scenario = _one_talent_on_the_books()

    case = validate_success(_open_case(scenario, DETECTED_AT_HOME), 201)

    assert case["severity_score"] == 0.4051
    assert case["enforceable_under_use_state"] is True
    assert case["use_state_rights_until"] is None
    assert case["status"] == "DETECTED"
    assert case["legal_hold_applied_count"] == 0
    assertions.assert_fields_null(
        case, "triaged_by_user_id", "escalated_by_user_id", "closed_by_user_id"
    )


VOICE_SAMPLE = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:aaa",
}


def _an_active_grant_over_one_non_union_talent():
    """The default California chain as far as a countersigned grant."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario)
    fixtures.countersign_grant(scenario)
    return scenario


def _one_sample_bound_to_no_replica():
    """That grant plus a single stored voice sample no replica was ever built from."""
    scenario = _an_active_grant_over_one_non_union_talent()
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    return scenario


def test_the_second_purge_is_an_asset_state_error_that_rewrites_no_stamp():
    """Destruction happens once; the repeat is refused and changes nothing.

    The PRD states: "On the manual path a `RightsAdministrator` destroys the sample ahead
    of schedule, supplying a `purge_note`. It is admissible from `STORED` and from
    `PURGE_SCHEDULED`, and moves the asset to `PURGED` with `payload_digest` cleared to
    null, `purged_at` stamped and `purge_due_at` left exactly as it was. An asset already
    `PURGED` is refused with `ERR_INVALID_ASSET_STATE`." The terminal status admits no
    second move: "`PURGED` is terminal; the asset's `version` advances by one on every one
    of these moves."

    Design: Corner/errors/repeat_death_record_and_repeat_purge_are_state_errors
    """
    scenario = _one_sample_bound_to_no_replica()
    purged = fixtures.purge_asset(scenario)
    assert purged["status"] == "PURGED"
    assert purged["purged_at"] == "2026-08-01T00:00:00Z"
    assert purged["payload_digest"] is None

    repeat = api_client.purge_biometric_asset(
        scenario["asset"]["id"],
        factories.purge_payload(purge_note="second attempt"),
        scenario["admin_headers"],
    )
    validate_error(repeat, "ERR_INVALID_ASSET_STATE")
    assert repeat.status_code == 409

    unchanged = fixtures.refresh_asset(scenario)
    assert unchanged["purged_at"] == "2026-08-01T00:00:00Z"
    assert unchanged["payload_digest"] is None
    assertions.assert_versioned(unchanged, purged["version"])


def test_the_second_death_record_is_a_talent_state_error_and_moves_no_date():
    """Death is recorded once; an earlier date afterwards may not overwrite it.

    The first record's own arithmetic is fixed: "Otherwise `postmortem_rights_until` is
    the date of death advanced by that number of whole years, landing on the same month
    and day, stored as an instant at `00:00:00Z`." The grant follows: "Because of that,
    the second hop moves every consent grant of this talent whose `status` is `ACTIVE`
    and whose `grantor_kind` is `TALENT` from `ACTIVE` to `SUSPENDED`, stamping
    `suspension_reason` as `DEATH_PENDING_ESTATE` — the living person who executed those
    grants can no longer stand behind them." So does the posture: "Because at least one
    grant is now suspended, the fourth hop recomputes the talent's `rights_posture`,
    which becomes `RESTRICTED` unless a `LEGAL_ESCALATED` case already forces `FROZEN`."
    The repeat is then refused outright: "The record is refused with
    `ERR_INVALID_TALENT_STATE` if the talent is already `DECEASED`, and with
    `ERR_STATE_LAW_PROFILE_MISSING` if no law profile exists for the talent's
    `domicile_state_code` — the domicile is frozen at death precisely because the answer
    to \"how long do the rights last\" must stop moving."

    Design: Corner/errors/repeat_death_record_and_repeat_purge_are_state_errors
    """
    scenario = _an_active_grant_over_one_non_union_talent()

    fixtures.record_death(scenario)
    deceased = fixtures.read_talent(scenario)
    assert deceased["life_status"] == "DECEASED"
    assert deceased["date_of_death"] == "2026-08-01T00:00:00Z"
    assert deceased["postmortem_rights_until"] == "2096-08-01T00:00:00Z"

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "SUSPENDED"
    assert grant["suspension_reason"] == "DEATH_PENDING_ESTATE"
    assertions.assert_posture(deceased, "RESTRICTED")

    repeat = api_client.record_death(
        scenario["talent"]["id"],
        factories.death_record_payload(date_of_death="2026-07-01T00:00:00Z"),
        scenario["admin_headers"],
    )
    validate_error(repeat, "ERR_INVALID_TALENT_STATE")
    assert repeat.status_code == 409

    unchanged = fixtures.read_talent(scenario)
    assert unchanged["date_of_death"] == "2026-08-01T00:00:00Z"
    assert unchanged["postmortem_rights_until"] == "2096-08-01T00:00:00Z"
    assertions.assert_versioned(unchanged, deceased["version"])


HALF_MILLION_SPOT = {
    "projected_impressions": 500_000,
    "intended_use_description": "Spring spot",
}

LICENCE_OPEN_FROM_AUGUST = {
    "distribution_start": "2026-08-01T00:00:00Z",
    "distribution_end": "2026-12-01T00:00:00Z",
    "actual_impressions": 500_000,
}

VOICE_BUILD = {"replica_kind": "VOICE", "build_ref": "build-001"}


def _an_issued_licence_awaiting_its_label():
    """The California advertising chain through to an ISSUED, unlabelled licence."""
    scenario = _one_sample_bound_to_no_replica()
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    fixtures.submit_performance(scenario, HALF_MILLION_SPOT)
    fixtures.review_performance(scenario, "APPROVE")
    fixtures.issue_license(scenario, LICENCE_OPEN_FROM_AUGUST)
    return scenario


def _confirm_removal(scenario):
    """Send a removal confirmation without asserting the outcome."""
    return api_client.confirm_removal(
        scenario["license"]["id"],
        factories.confirm_removal_payload(),
        scenario["licensee_headers"],
    )


def _go_live(scenario):
    """Send a go-live without asserting the outcome."""
    return api_client.go_live(
        scenario["license"]["id"],
        factories.go_live_payload(distribution_reference="flight-1"),
        scenario["licensee_headers"],
    )


def _attest(scenario, placement, text):
    """Attest a disclosure label without asserting the outcome."""
    return api_client.attest_disclosure(
        scenario["license"]["id"],
        factories.disclosure_payload(
            disclosure_placement=placement, disclosure_label_text=text
        ),
        scenario["licensee_headers"],
    )


def _review(scenario, decision, **overrides):
    """Record a review decision without asserting the outcome."""
    return api_client.review_generated_performance(
        scenario["performance"]["id"],
        factories.review_payload(decision, **overrides),
        fixtures.grantor_headers(scenario),
    )


def _resubmit(scenario, description):
    """Resubmit a performance without asserting the outcome."""
    return api_client.resubmit_generated_performance(
        scenario["performance"]["id"],
        factories.resubmit_payload(
            intended_use_description=description, projected_impressions=500_000
        ),
        scenario["licensee_headers"],
    )


def test_the_two_licence_dimensions_refuse_under_two_different_error_ids():
    """One row, one distribution rung, one compliance rung, two distinct ids.

    The PRD states: "The license must be `REMOVAL_PENDING`, or the request draws
    `ERR_INVALID_LICENSE_STATE`, and the caller must be the recorded licensee." Going live
    then fails on the other dimension: "Four conditions guard it: the license must be
    `ISSUED`, or `ERR_INVALID_LICENSE_STATE`; `compliance_status` must be `VERIFIED`, or
    `ERR_DISCLOSURE_NOT_VERIFIED`; the current logical instant must lie inside the closed
    window from `distribution_start` through `distribution_end` inclusive, or
    `ERR_OUTSIDE_DISTRIBUTION_WINDOW`; and the governing grant must still be `ACTIVE`, or
    `ERR_CONSENT_NOT_ACTIVE`."

    Design: Corner/errors/license_disclosure_and_performance_state_errors_are_three_distinct_ids
    """
    scenario = _an_issued_licence_awaiting_its_label()
    assert scenario["license"]["distribution_status"] == "ISSUED"
    assert scenario["license"]["compliance_status"] == "PENDING_LABEL"

    refused_removal = _confirm_removal(scenario)
    validate_error(refused_removal, "ERR_INVALID_LICENSE_STATE")
    assert refused_removal.status_code == 409

    validate_error(_go_live(scenario), "ERR_DISCLOSURE_NOT_VERIFIED")

    still_issued = fixtures.refresh_license(scenario)
    assert still_issued["distribution_status"] == "ISSUED"
    assert still_issued["distribution_reference"] is None


def test_a_verified_disclosure_may_not_be_attested_a_second_time():
    """The compliance dimension closes after acceptance and keeps what it stored.

    The PRD states: "Attestation is admissible when `compliance_status` is `PENDING_LABEL`
    or `NON_COMPLIANT` — re-attestation after a rejection is the cycle in this dimension —
    and is refused with `ERR_INVALID_DISCLOSURE_STATE` when the license is already
    `LABELED` or `VERIFIED`." The accepted pair moves it: "A successful attestation moves
    `compliance_status` from `PENDING_LABEL → LABELED` or from `NON_COMPLIANT → LABELED`,
    stores both attested fields, resets `disclosure_verified_by_user_id` to null, and
    advances the license's `version` by one." And: "`ACCEPT` moves `compliance_status`
    `LABELED → VERIFIED` and records the reviewing officer as
    `disclosure_verified_by_user_id`."

    Design: Corner/errors/license_disclosure_and_performance_state_errors_are_three_distinct_ids
    """
    scenario = _an_issued_licence_awaiting_its_label()

    labelled = validate_success(_attest(scenario, "PRE_ROLL", "Synthetic performance"), 200)
    assert labelled["compliance_status"] == "LABELED"
    assert labelled["disclosure_placement"] == "PRE_ROLL"
    assert labelled["disclosure_verified_by_user_id"] is None

    verified = fixtures.verify_disclosure(scenario, "ACCEPT")
    assert verified["compliance_status"] == "VERIFIED"
    assert verified["disclosure_verified_by_user_id"] == scenario["compliance_user_id"]

    repeat = _attest(scenario, "PERSISTENT_BUG", "Second attestation")
    validate_error(repeat, "ERR_INVALID_DISCLOSURE_STATE")
    assert repeat.status_code == 409

    unchanged = fixtures.refresh_license(scenario)
    assert unchanged["disclosure_placement"] == "PRE_ROLL"
    assert unchanged["compliance_status"] == "VERIFIED"


def test_the_parent_performance_reports_its_own_state_error_for_both_verbs():
    """Review and resubmit both refuse an APPROVED output, under one shared id.

    The PRD states: "The performance must be `SUBMITTED`, or the decision draws
    `ERR_INVALID_PERFORMANCE_STATE`; the grant must be `ACTIVE`; the posture must not be
    `FROZEN`; and a deceased talent must have a `VERIFIED` estate authority." Resubmission
    is gated on a different status entirely: "The performance must be
    `REVISION_REQUESTED`, or the request draws `ERR_INVALID_PERFORMANCE_STATE`, and the
    governing grant must still be `ACTIVE`."

    Design: Corner/errors/license_disclosure_and_performance_state_errors_are_three_distinct_ids
    """
    scenario = _an_issued_licence_awaiting_its_label()
    approved = fixtures.refresh_performance(scenario)

    validate_error(
        _review(scenario, "REJECT", rejection_reason="OFF_BRAND"),
        "ERR_INVALID_PERFORMANCE_STATE",
    )
    validate_error(_resubmit(scenario, "Second cut"), "ERR_INVALID_PERFORMANCE_STATE")

    unchanged = fixtures.refresh_performance(scenario)
    assert unchanged["review_status"] == "APPROVED"
    assert unchanged["rejection_reason"] is None
    assertions.assert_versioned(unchanged, approved["version"])


def test_only_the_label_and_its_acceptance_advanced_the_licence_version():
    """Five refusals write nothing; the two accepted calls move it exactly twice.

    The PRD states: "Either way the license's `version` advances by one." That is the
    second of the two accepted moves, the first being the attestation itself: "A
    successful attestation moves `compliance_status` from `PENDING_LABEL → LABELED` or
    from `NON_COMPLIANT → LABELED`, stores both attested fields, resets
    `disclosure_verified_by_user_id` to null, and advances the license's `version` by
    one."

    Design: Corner/errors/license_disclosure_and_performance_state_errors_are_three_distinct_ids
    """
    scenario = _an_issued_licence_awaiting_its_label()
    baseline = scenario["license"]["version"]

    validate_error(_confirm_removal(scenario), "ERR_INVALID_LICENSE_STATE")
    validate_error(_go_live(scenario), "ERR_DISCLOSURE_NOT_VERIFIED")
    validate_success(_attest(scenario, "PRE_ROLL", "Synthetic performance"), 200)
    fixtures.verify_disclosure(scenario, "ACCEPT")
    validate_error(
        _attest(scenario, "PERSISTENT_BUG", "Second attestation"),
        "ERR_INVALID_DISCLOSURE_STATE",
    )
    validate_error(
        _review(scenario, "REJECT", rejection_reason="OFF_BRAND"),
        "ERR_INVALID_PERFORMANCE_STATE",
    )
    validate_error(_resubmit(scenario, "Second cut"), "ERR_INVALID_PERFORMANCE_STATE")

    final = fixtures.refresh_license(scenario)
    assert final["distribution_status"] == "ISSUED"
    assert final["compliance_status"] == "VERIFIED"
    assertions.assert_version_advanced_by(final, baseline, 2)


def _three_revision_rounds_already_granted():
    """A submitted output that has been through all three revisions the cap allows."""
    scenario = _one_sample_bound_to_no_replica()
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    fixtures.submit_performance(
        scenario, {"projected_impressions": 500_000, "intended_use_description": "Cut 1"}
    )
    for cut in ("Cut 2", "Cut 3", "Cut 4"):
        fixtures.review_performance(scenario, "REQUEST_REVISION")
        fixtures.resubmit_performance(
            scenario,
            {"projected_impressions": 500_000, "intended_use_description": cut},
        )
    return scenario


def test_the_fourth_revision_request_rejects_at_the_cap_and_reverses_the_accrual():
    """Three rounds granted, then the request converts into a rejection.

    The PRD states: "`REQUEST_REVISION` moves it `SUBMITTED → REVISION_REQUESTED` and
    records `reviewed_by_user_id`, provided `revision_round` is still below the cap of
    three rounds." Each granted round is spent by the resubmission: "On success the
    performance moves `REVISION_REQUESTED → SUBMITTED`, `revision_round` increases by one,
    the two supplied fields replace their predecessors, `reviewed_by_user_id` is cleared to
    null, and `review_deadline` is set afresh to the current logical instant advanced by
    seven days." The fourth request does not loop: "A `REQUEST_REVISION` arriving when
    `revision_round` has already reached three does not loop: it rejects the performance
    instead, with `rejection_reason` of `REVISION_LIMIT_REACHED` and the same reversal."
    That reversal is the rejection's own: "`REJECT` moves it `SUBMITTED → REJECTED`,
    stamping `rejection_reason` from the payload — the reasons in the vocabulary are
    `OFF_BRAND`, `OUT_OF_SCOPE`, `QUALITY`, `REVIEW_WINDOW_LAPSED` and
    `REVISION_LIMIT_REACHED` — appending a `REVERSAL` entry that exactly negates the live
    `PER_USE_PROVISIONAL` entry, including the exact negation of its three share columns,
    and setting `provisional_compensation_cents` to zero."

    Design: Corner/errors/resubmit_after_the_cap_driven_rejection_reports_the_revision_limit
    """
    scenario = _three_revision_rounds_already_granted()
    at_the_cap = fixtures.refresh_performance(scenario)
    assert at_the_cap["revision_round"] == 3
    assert at_the_cap["review_status"] == "SUBMITTED"

    rejected = validate_success(_review(scenario, "REQUEST_REVISION"), 200)

    assert rejected["review_status"] == "REJECTED"
    assert rejected["rejection_reason"] == "REVISION_LIMIT_REACHED"
    assert rejected["provisional_compensation_cents"] == 0

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
        ],
    )
    assertions.assert_exact_negation(entries[-1], entries[-2])


def test_the_resubmit_after_that_rejection_names_the_limit_not_the_state():
    """The shut door explains itself: the cap, not the generic wrong-status refusal.

    The PRD states: "Two exhaustion cases are refused with `ERR_REVISION_LIMIT_REACHED`
    instead: a performance still in `REVISION_REQUESTED` whose `revision_round` has reached
    three, and a performance already `REJECTED` with `rejection_reason` of
    `REVISION_LIMIT_REACHED` — the second is the reachable form, since the fourth revision
    request rejects rather than loops." The rejected row is finished with: "And if the
    replica behind the performance is quarantined by a cascade, the performance moves from
    `SUBMITTED`, `REVISION_REQUESTED` or `APPROVED` to `WITHDRAWN`, again with any live
    provisional accrual reversed and `provisional_compensation_cents` zeroed. Both
    `REJECTED` and `WITHDRAWN` are terminal."

    Design: Corner/errors/resubmit_after_the_cap_driven_rejection_reports_the_revision_limit
    """
    scenario = _three_revision_rounds_already_granted()
    rejected = validate_success(_review(scenario, "REQUEST_REVISION"), 200)

    refused = _resubmit(scenario, "Cut 5")
    validate_error(refused, "ERR_REVISION_LIMIT_REACHED")
    assert refused.status_code == 409

    unchanged = fixtures.refresh_performance(scenario)
    assert unchanged["revision_round"] == 3
    assert unchanged["review_status"] == "REJECTED"
    assert unchanged["intended_use_description"] == "Cut 4"
    assertions.assert_versioned(unchanged, rejected["version"])
