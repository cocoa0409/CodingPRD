"""Which rung answers first: state before floor, hold before status, media before territory."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

LOW_SEVERITY_DETECTION = {
    "detection_source": "MONITORING_FEED",
    "suspect_url": "https://pirate.example/low",
    "detected_channel": "ENTERTAINMENT",
    "detected_view_count": 400_000,
    "match_confidence": 0.500,
}

VIRAL_DETECTION = {
    "detection_source": "MONITORING_FEED",
    "suspect_url": "https://pirate.example/viral",
    "detected_channel": "ADVERTISING",
    "detected_view_count": 10_000_000,
    "match_confidence": 1.000,
}


def _one_low_severity_case():
    """A CLEAR living talent with a single case scoring below every threshold."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.open_case(scenario, LOW_SEVERITY_DETECTION)
    return scenario


def _escalate(scenario, headers):
    """Attempt an escalation without asserting the outcome."""
    return api_client.escalate_infringement_case(
        scenario["case"]["id"], factories.escalate_payload(), headers
    )


def test_escalating_too_early_reports_the_state_rung_not_the_severity_floor():
    """0.3550 is below the floor, yet the wrong status is what the caller hears.

    The PRD states: "The case must be `TAKEDOWN_ISSUED`, or escalation draws
    `ERR_INVALID_CASE_STATE`. Its `severity_score` must be at least 0.5000, or escalation
    is refused with `ERR_SEVERITY_BELOW_ESCALATION_FLOOR` — the sweep-opened case scoring
    0.6900 clears that floor while the 0.3550 case does not." The ladder settles which of
    the two is reported: "State-machine admissibility follows, in this internal order:
    `ERR_INVALID_TALENT_STATE`, `ERR_INVALID_ESTATE_AUTHORITY_STATE`,
    `ERR_INVALID_CONSENT_STATE`, `ERR_CONSENT_NOT_ACTIVE`, `ERR_INVALID_ASSET_STATE`,
    `ERR_INVALID_REPLICA_STATE`, `ERR_INVALID_PERFORMANCE_STATE`,
    `ERR_INVALID_LICENSE_STATE`, `ERR_INVALID_DISCLOSURE_STATE`, `ERR_INVALID_CASE_STATE`
    — all HTTP 409." The floor sits far below it: "Then the remaining business constraints:
    `ERR_EXCLUSIVITY_WINDOW_CONFLICT`, `ERR_REPLICA_OVERLAP_CAP_EXCEEDED`,
    `ERR_REVISION_LIMIT_REACHED`, `ERR_CONSENT_NOT_REVOCABLE`,
    `ERR_SEVERITY_BELOW_ESCALATION_FLOOR`." And the score itself is worked: "A confidence
    of 0.500 with four hundred thousand views against a `CLEAR` talent gives 0.3000 plus
    0.0100 plus 0.0450, which is 0.3550."

    Design: Corner/errors/case_state_rung_outranks_the_escalation_floor_rung
    """
    scenario = _one_low_severity_case()
    assert scenario["case"]["severity_score"] == 0.3550

    too_early = _escalate(scenario, scenario["admin_headers"])
    validate_error(too_early, "ERR_INVALID_CASE_STATE")
    assert too_early.status_code == 409

    issued = fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    assert issued["status"] == "TAKEDOWN_ISSUED"
    assert issued["triaged_by_user_id"] == scenario["compliance_user_id"]
    assert issued["takedown_issued_at"] == "2026-08-01T00:00:00Z"

    below_the_floor = _escalate(scenario, scenario["admin_headers"])
    validate_error(below_the_floor, "ERR_SEVERITY_BELOW_ESCALATION_FLOOR")
    assert below_the_floor.status_code == 409

    unescalated = fixtures.refresh_case(scenario)
    assert unescalated["status"] == "TAKEDOWN_ISSUED"
    assert unescalated["escalated_by_user_id"] is None
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")


def test_the_closed_case_reports_the_state_rung_again_to_a_second_administrator():
    """Voluntary removal ends the case, and no administrator reopens the legal path.

    The PRD states: "From `TAKEDOWN_ISSUED`, an `outcome` of `REMOVED` moves the case
    `TAKEDOWN_ISSUED → RESOLVED_REMOVED` with `closure_outcome` recorded as
    `VOLUNTARY_REMOVAL`; no holds were ever applied on that branch, so nothing is
    released." Escalation is then shut for good: "The case must be `TAKEDOWN_ISSUED`, or
    escalation draws `ERR_INVALID_CASE_STATE`." The closer is recorded: "`closed_by_user_id`
    records the closer, and the case's and talent's `version` each advance by one."

    Design: Corner/errors/case_state_rung_outranks_the_escalation_floor_rung
    """
    scenario = _one_low_severity_case()
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    validate_error(
        _escalate(scenario, scenario["admin_headers"]),
        "ERR_SEVERITY_BELOW_ESCALATION_FLOOR",
    )

    closed = fixtures.close_case(scenario, "REMOVED")
    assert closed["status"] == "RESOLVED_REMOVED"
    assert closed["closure_outcome"] == "VOLUNTARY_REMOVAL"
    assert closed["closed_by_user_id"] == scenario["admin_user_id"]
    assert closed["legal_hold_applied_count"] == 0

    after_the_fact = _escalate(scenario, scenario["second_admin_headers"])
    validate_error(after_the_fact, "ERR_INVALID_CASE_STATE")

    terminal = fixtures.refresh_case(scenario)
    assert terminal["status"] == "RESOLVED_REMOVED"
    assert terminal["escalated_by_user_id"] is None


FACE_SCAN = {
    "asset_kind": "FACE_SCAN",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:bbb",
}


def _a_stored_sample_and_a_viral_detection():
    """One stored face scan under an active grant, and a case scoring 0.8950."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, FACE_SCAN)
    fixtures.open_case(scenario, VIRAL_DETECTION)
    return scenario


def _purge(scenario):
    """Attempt the manual purge without asserting the outcome."""
    return api_client.purge_biometric_asset(
        scenario["asset"]["id"],
        factories.purge_payload(purge_note="destroy the scan"),
        scenario["admin_headers"],
    )


def _an_escalated_case_over_that_sample():
    """The same facts carried through mandatory takedown into legal escalation."""
    scenario = _a_stored_sample_and_a_viral_detection()
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)
    return scenario


def test_a_case_at_that_severity_cannot_be_dismissed_at_all():
    """0.8950 leaves one permitted decision, and the refusal moves nothing.

    The PRD states: "A case whose `severity_score` is at or above 0.7500 may not be
    dismissed at all — the only permitted decision is `ISSUE_TAKEDOWN` — and the attempt is
    refused with `ERR_TAKEDOWN_MANDATORY`." The score is composed as the PRD composes it:
    "Confidence dominates it: the score is `match_confidence` weighted at 0.60, plus a
    saturating reach term weighted at 0.25, plus a posture term weighted at 0.15, with the
    sum rounded half up to four decimal places. The reach term is `detected_view_count`
    divided by ten million, capped at 1.0, so anything at or above ten million views
    contributes the full reach weight."

    Design: Corner/errors/impounded_asset_refuses_purge_until_the_case_closes
    """
    scenario = _a_stored_sample_and_a_viral_detection()
    assert scenario["case"]["severity_score"] == 0.8950

    refused = api_client.triage_infringement_case(
        scenario["case"]["id"],
        factories.triage_payload("DISMISS"),
        scenario["compliance_headers"],
    )
    validate_error(refused, "ERR_TAKEDOWN_MANDATORY")

    unmoved = fixtures.refresh_case(scenario)
    assert unmoved["status"] == "DETECTED"
    assert unmoved["closure_outcome"] is None


def test_the_impounded_sample_refuses_the_purge_with_the_hold_not_the_status():
    """The asset-state rung stands aside so the informative refusal is heard.

    The PRD states: "An asset in `LEGAL_HOLD` is refused with `ERR_ASSET_UNDER_LEGAL_HOLD`,
    because impounded material may not be destroyed — the state check deliberately admits
    that status so this more informative refusal is the one the caller sees." The ladder
    spells the deference out: "When a manual purge targets a biometric asset whose `status`
    is `LEGAL_HOLD`, the asset-state rung deliberately admits that status and lets the
    safety rung report `ERR_ASSET_UNDER_LEGAL_HOLD` instead of `ERR_INVALID_ASSET_STATE`,
    so the requester learns the material is impounded rather than merely in an unexpected
    state; the asset-state rung itself refuses only an already-`PURGED` asset." The
    impoundment is the escalation's second hop: "Because litigation is now live, hop two
    impounds evidence: every biometric asset of this case's talent whose `status` is
    `STORED` or `PURGE_SCHEDULED` moves to `LEGAL_HOLD`, recording `held_from_status` as
    exactly the status it left so the release can resume the same schedule, and leaving
    `purge_due_at` untouched; `legal_hold_applied_count` is set to the number of assets
    moved."

    Design: Corner/errors/impounded_asset_refuses_purge_until_the_case_closes
    """
    scenario = _an_escalated_case_over_that_sample()

    assert scenario["case"]["status"] == "LEGAL_ESCALATED"
    assert scenario["case"]["legal_hold_applied_count"] == 1

    held = fixtures.refresh_asset(scenario)
    assert held["status"] == "LEGAL_HOLD"
    assert held["held_from_status"] == "STORED"
    assertions.assert_posture(fixtures.read_talent(scenario), "FROZEN")

    refused = _purge(scenario)
    validate_error(refused, "ERR_ASSET_UNDER_LEGAL_HOLD")
    assert refused.status_code == 409

    intact = fixtures.refresh_asset(scenario)
    assert intact["purged_at"] is None
    assert intact["payload_digest"] == FACE_SCAN["payload_digest"]


def test_closing_the_settlement_releases_the_hold_and_the_same_purge_succeeds():
    """The refusal was the hold and nothing else: the identical call then lands.

    The PRD states: "Both escalated closures release what the escalation impounded, but
    only when no other infringement case of this same talent remains in `LEGAL_ESCALATED`:
    every biometric asset in `LEGAL_HOLD` returns to exactly its `held_from_status` —
    `LEGAL_HOLD → STORED` for one held from storage, `LEGAL_HOLD → PURGE_SCHEDULED` for one
    held mid-schedule — and every digital replica quarantined with `quarantine_reason` of
    `SOURCE_LEGAL_HOLD` returns to exactly its `held_from_status`, with `held_from_status`
    and `quarantine_reason` cleared on both." The counters part company: "`legal_hold_applied_count`
    is left as the historical record of what the case once impounded, while the talent's
    `legal_hold_asset_count` falls back to its pre-escalation value and `rights_posture` is
    recomputed — typically to `RESTRICTED` while removal obligations remain open, and to
    `CLEAR` only when none do." The released sample is then destructible: "It is admissible
    from `STORED` and from `PURGE_SCHEDULED`, and moves the asset to `PURGED` with
    `payload_digest` cleared to null, `purged_at` stamped and `purge_due_at` left exactly as
    it was."

    Design: Corner/errors/impounded_asset_refuses_purge_until_the_case_closes
    """
    scenario = _an_escalated_case_over_that_sample()
    retention_before_the_hold = scenario["asset"]["retention_until"]
    validate_error(_purge(scenario), "ERR_ASSET_UNDER_LEGAL_HOLD")

    settled = fixtures.close_case(
        scenario, "SETTLED", headers=scenario["second_admin_headers"]
    )
    assert settled["status"] == "CLOSED_SETTLED"
    assert settled["legal_hold_applied_count"] == 1

    released = fixtures.refresh_asset(scenario)
    assert released["status"] == "STORED"
    assert released["held_from_status"] is None
    assert released["retention_until"] == retention_before_the_hold

    talent = fixtures.read_talent(scenario)
    assertions.assert_posture(talent, "CLEAR")
    assertions.assert_talent_counters(talent, legal_hold_asset_count=0)

    purged = validate_success(_purge(scenario), 200)
    assert purged["status"] == "PURGED"
    assert purged["purged_at"] == "2026-08-01T00:00:00Z"
    assert purged["payload_digest"] is None


VOICE_SAMPLE = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:aaa",
}

VOICE_BUILD = {"replica_kind": "VOICE", "build_ref": "build-001"}

US_SPOT = {
    "licensee_name": "Northlight",
    "media_type": "ADVERTISING",
    "territory_codes": ["US"],
    "intended_use_description": "US spot",
    "projected_impressions": 500_000,
}

AUGUST_TO_DECEMBER = {
    "distribution_start": "2026-08-01T00:00:00Z",
    "distribution_end": "2026-12-01T00:00:00Z",
    "actual_impressions": 500_000,
}


def _an_approved_replica_cleared_only_for_us_advertising():
    """A grant permitting ADVERTISING in the United States, and nothing else."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, {"permitted_use_notes": "US ads only"})
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    return scenario


def _submit_out_of_scope(scenario, media_type, territories, description):
    """Submit a performance outside the grant's scope without asserting the outcome."""
    return api_client.create_generated_performance(
        factories.generated_performance_payload(
            scenario["replica"]["id"],
            licensee_name="Northlight",
            media_type=media_type,
            territory_codes=territories,
            intended_use_description=description,
            projected_impressions=500_000,
        ),
        scenario["licensee_headers"],
    )


def _performances_of_the_replica(scenario):
    """Every performance standing against the scenario's replica."""
    return validate_paginated(
        api_client.list_generated_performances(
            scenario["admin_headers"],
            params={"digital_replica_id": scenario["replica"]["id"], "limit": 100},
        )
    )


def test_a_payload_wrong_on_both_scope_fields_reports_the_media_type():
    """Media type is checked first, so one stray territory never masks it.

    The PRD states: "The declared `media_type` must be a member of the grant's
    `permitted_media_types`, or `ERR_MEDIA_TYPE_OUT_OF_SCOPE`; every declared territory
    must be a member of the grant's `territory_codes`, or `ERR_TERRITORY_OUT_OF_SCOPE`."
    Their order is pinned by the ladder: "Safety rules come next, in order:
    `ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD`, `ERR_ASSET_UNDER_LEGAL_HOLD`,
    `ERR_ASSET_BOUND_TO_ACTIVE_REPLICA`, `ERR_POSTMORTEM_REGISTRATION_MISSING`,
    `ERR_POSTMORTEM_RIGHTS_EXPIRED`, `ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT`,
    `ERR_DISCLOSURE_NOT_VERIFIED`, `ERR_TAKEDOWN_MANDATORY`. Then referential scope:
    `ERR_MEDIA_TYPE_OUT_OF_SCOPE`, `ERR_TERRITORY_OUT_OF_SCOPE`,
    `ERR_ASSET_CONSENT_MISMATCH`, `ERR_NO_SOURCE_ASSETS`."
    The clean submission lands where the PRD says it does: "A new submission is `SUBMITTED`
    with `revision_round` at zero, `reviewed_by_user_id`, `rejection_reason` and
    `review_note` all null, and a `review_deadline` set to the current logical instant
    advanced by the seven-day review window."

    Design: Corner/errors/scope_errors_order_media_type_before_territory
    """
    scenario = _an_approved_replica_cleared_only_for_us_advertising()

    wrong_media = _submit_out_of_scope(scenario, "EPISODIC", ["US"], "TV episode cameo")
    validate_error(wrong_media, "ERR_MEDIA_TYPE_OUT_OF_SCOPE")
    assert wrong_media.status_code == 422

    wrong_territory = _submit_out_of_scope(
        scenario, "ADVERTISING", ["US", "GB"], "Global spot"
    )
    validate_error(wrong_territory, "ERR_TERRITORY_OUT_OF_SCOPE")
    assert wrong_territory.status_code == 422

    validate_error(
        _submit_out_of_scope(scenario, "EPISODIC", ["GB"], "Both wrong"),
        "ERR_MEDIA_TYPE_OUT_OF_SCOPE",
    )

    fixtures.submit_performance(scenario, US_SPOT)
    assert scenario["performance"]["review_status"] == "SUBMITTED"
    assert scenario["performance"]["revision_round"] == 0

    rows, meta = _performances_of_the_replica(scenario)
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [scenario["performance"]["id"]]


def test_the_licence_territory_narrows_against_the_performance_as_well():
    """A territory the parent output never claimed cannot be licensed either.

    The PRD states: "`territory_codes` is a list of 1 to 20 distinct two-letter uppercase
    territory codes, and every performance and every license territory must later be a
    member of it." The refusal is the same rung the submission uses: "Safety rules come
    next, in order: `ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD`, `ERR_ASSET_UNDER_LEGAL_HOLD`,
    `ERR_ASSET_BOUND_TO_ACTIVE_REPLICA`, `ERR_POSTMORTEM_REGISTRATION_MISSING`,
    `ERR_POSTMORTEM_RIGHTS_EXPIRED`, `ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT`,
    `ERR_DISCLOSURE_NOT_VERIFIED`, `ERR_TAKEDOWN_MANDATORY`. Then referential scope:
    `ERR_MEDIA_TYPE_OUT_OF_SCOPE`, `ERR_TERRITORY_OUT_OF_SCOPE`,
    `ERR_ASSET_CONSENT_MISMATCH`, `ERR_NO_SOURCE_ASSETS`."

    Design: Corner/errors/scope_errors_order_media_type_before_territory
    """
    scenario = _an_approved_replica_cleared_only_for_us_advertising()
    replica_version = scenario["replica"]["version"]
    fixtures.submit_performance(scenario, US_SPOT)
    fixtures.review_performance(scenario, "APPROVE")

    refused = api_client.create_usage_license(
        factories.usage_license_payload(
            scenario["performance"]["id"],
            replica_version,
            territory_codes=["GB"],
            **AUGUST_TO_DECEMBER,
        ),
        scenario["licensee_headers"],
    )
    validate_error(refused, "ERR_TERRITORY_OUT_OF_SCOPE")
    assert refused.status_code == 422

    _rows, meta = validate_paginated(
        api_client.list_usage_licenses(scenario["admin_headers"])
    )
    assert meta["total_count"] == 0


ADVERTISING_GRANT = {"permitted_use_notes": "Ads"}

SOCIAL_GRANT = {"permitted_media_types": ["SOCIAL"], "permitted_use_notes": "Socials"}


def _two_healthy_grants_with_the_chain_on_the_first():
    """One talent, two non-exclusive grants, an approved output under the first."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    advertising_grant = scenario["grant"]
    fixtures.draft_consent_grant(scenario, SOCIAL_GRANT)
    fixtures.countersign_grant(scenario)
    social_grant = scenario["grant"]
    scenario["grant"] = advertising_grant
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    fixtures.submit_performance(scenario, US_SPOT)
    fixtures.review_performance(scenario, "APPROVE")
    return scenario, advertising_grant, social_grant


def _issue_licence(scenario, expected_replica_version):
    """Attempt the licence issuance without asserting the outcome."""
    return api_client.create_usage_license(
        factories.usage_license_payload(
            scenario["performance"]["id"], expected_replica_version, **AUGUST_TO_DECEMBER
        ),
        scenario["licensee_headers"],
    )


def test_suspending_an_unrelated_grant_restricts_the_whole_talent():
    """The exploited grant is untouched, yet the licence is refused all the same.

    The PRD states: "`SUSPEND` requires the grant to be `ACTIVE` and moves it `ACTIVE →
    SUSPENDED`, stamping `suspension_reason` with the supplied reason, which defaults to
    `COMPLIANCE_HOLD` — the only two reasons in the vocabulary are `DEATH_PENDING_ESTATE`
    and `COMPLIANCE_HOLD`. The talent's `rights_posture` is recomputed and becomes
    `RESTRICTED` unless a `LEGAL_ESCALATED` case already forces `FROZEN`." The posture is a
    property of the talent, not of one grant: "Otherwise, if the talent's
    `open_removal_obligation_count` is greater than zero, or if any consent grant of this
    talent has status `SUSPENDED`, the posture is `RESTRICTED`." And that posture bites at
    issuance: "The talent's posture must be neither `FROZEN` nor `RESTRICTED`, drawing
    `ERR_TALENT_RIGHTS_FROZEN` or `ERR_TALENT_RIGHTS_RESTRICTED` respectively."

    Design: Corner/errors/restricted_posture_blocks_license_issuance_until_reinstatement
    """
    scenario, advertising_grant, social_grant = _two_healthy_grants_with_the_chain_on_the_first()
    replica_version = fixtures.refresh_replica(scenario)["version"]

    suspended = fixtures.suspend_grant(
        scenario, grant=social_grant, overrides={"suspension_reason": "COMPLIANCE_HOLD"}
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "COMPLIANCE_HOLD"
    assert fixtures.refresh_grant(scenario, advertising_grant)["status"] == "ACTIVE"

    talent = fixtures.read_talent(scenario)
    assertions.assert_posture(talent, "RESTRICTED")
    assertions.assert_talent_counters(talent, open_removal_obligation_count=0)

    refused = _issue_licence(scenario, replica_version)
    validate_error(refused, "ERR_TALENT_RIGHTS_RESTRICTED")
    assert refused.status_code == 409

    _rows, meta = validate_paginated(
        api_client.list_usage_licenses(scenario["admin_headers"])
    )
    assert meta["total_count"] == 0


def test_reinstatement_clears_the_posture_and_the_identical_call_is_accepted():
    """The same payload, the same echoed replica version, and now a licence.

    The PRD states: "`REINSTATE` requires the grant to be `SUSPENDED` and moves it
    `SUSPENDED → ACTIVE`, clearing `suspension_reason` to null." With nothing left
    suspended the posture falls back: "A talent with no cases, one `ACTIVE` grant and no
    open removal obligations is `CLEAR`; a talent with one `SUSPENDED` grant is
    `RESTRICTED`; a talent with one `LEGAL_ESCALATED` case and two open removal obligations
    is `FROZEN`, because the escalation clause is evaluated first; and when that escalated
    case is closed as `CLOSED_SETTLED` while two removal obligations are still open, the
    posture becomes `RESTRICTED` rather than `CLEAR`." The refusal was
    the posture rung alone, because the version gate reads the replica: "The two
    optimistic-concurrency rungs come after ownership and before any state check:
    `ERR_TALENT_VERSION_STALE` on consent drafting, then `ERR_REPLICA_VERSION_STALE` on
    license issuance."

    Design: Corner/errors/restricted_posture_blocks_license_issuance_until_reinstatement
    """
    scenario, _advertising_grant, social_grant = _two_healthy_grants_with_the_chain_on_the_first()
    replica_version = fixtures.refresh_replica(scenario)["version"]
    fixtures.suspend_grant(scenario, grant=social_grant)
    validate_error(_issue_licence(scenario, replica_version), "ERR_TALENT_RIGHTS_RESTRICTED")

    reinstated = fixtures.reinstate_grant(scenario, grant=social_grant)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")

    licensed = validate_success(_issue_licence(scenario, replica_version), 201)
    assert licensed["distribution_status"] == "ISSUED"
    assert licensed["territory_codes"] == ["US"]


def _an_estate_standing_in_for_a_dead_performer(scenario, name, executor, ref, registration):
    """Kill the performer and verify one estate claim, with or without a number."""
    fixtures.create_talent(scenario, {"legal_name": name})
    fixtures.record_death(scenario)
    fixtures.submit_estate_authority(
        scenario,
        {
            "executor_name": executor,
            "court_document_ref": ref,
            "registration_number": registration,
        },
    )
    fixtures.verify_estate_authority(scenario)
    return scenario


def _two_estates_differing_only_in_their_registration():
    """Two deceased California performers, one estate registered and one not."""
    unregistered = fixtures.register_state_law_profile()
    _an_estate_standing_in_for_a_dead_performer(
        unregistered, "Unregistered Estate", "Dana Cole", "PROB-A-1", None
    )
    registered = fixtures.new_scenario()
    _an_estate_standing_in_for_a_dead_performer(
        registered, "Registered Estate", "Sam Ruiz", "PROB-B-1", "CA-REG-88"
    )
    return unregistered, registered


def _draft_an_estate_grant(scenario):
    """Draft a post-mortem grant executed by the estate, outcome unasserted."""
    talent = fixtures.read_talent(scenario)
    return api_client.create_consent_grant(
        factories.consent_grant_payload(
            talent["id"],
            talent["version"],
            grantor_kind="ESTATE",
            estate_authority_id=scenario["estate_authority"]["id"],
            permitted_media_types=["FEATURE_FILM"],
            permitted_use_notes="Archive film use",
        ),
        scenario["second_admin_headers"],
    )


def _grants_of(scenario):
    """Every grant standing against one talent."""
    return validate_paginated(
        api_client.list_consent_grants(
            scenario["admin_headers"],
            params={"talent_id": scenario["talent"]["id"], "limit": 100},
        )
    )


def test_the_unregistered_estate_cannot_grant_consent_in_a_registering_state():
    """Verification copied nothing, so the safety rung refuses the draft outright.

    The PRD states: "`postmortem_requires_registration` is a boolean: when true,
    post-mortem rights are unenforceable in that state until the estate supplies a
    registration number." The check reads the value verification copies: "The talent's
    `postmortem_registration_number` is then copied from this authority's
    `registration_number`, so a state that demands registration can be satisfied from the
    estate paperwork." And the draft rung is explicit: "For a deceased talent whose domicile
    profile sets `postmortem_requires_registration` to true, the talent's
    `postmortem_registration_number` must be non-null, or the draft is refused with
    `ERR_POSTMORTEM_REGISTRATION_MISSING`; and the domicile-law post-mortem term must still
    be live — `postmortem_rights_until` must be non-null and at or after the current logical
    instant — or the draft is refused with `ERR_POSTMORTEM_RIGHTS_EXPIRED`." It is not the
    unverified-estate refusal, because that one asks a different question: "A talent whose
    `life_status` is `DECEASED` must already have a `VERIFIED` estate authority, or the draft
    is refused with `ERR_ESTATE_AUTHORITY_UNVERIFIED`."

    Design: Corner/errors/estate_grant_needs_the_registration_number_the_state_demands
    """
    unregistered, _registered = _two_estates_differing_only_in_their_registration()

    talent = fixtures.read_talent(unregistered)
    assert talent["life_status"] == "DECEASED"
    assert talent["postmortem_rights_until"] == "2096-08-01T00:00:00Z"
    assert talent["postmortem_registration_number"] is None
    assert unregistered["estate_authority"]["status"] == "VERIFIED"

    refused = _draft_an_estate_grant(unregistered)
    validate_error(refused, "ERR_POSTMORTEM_REGISTRATION_MISSING")
    assert refused.status_code == 422

    _rows, meta = _grants_of(unregistered)
    assert meta["total_count"] == 0


def test_the_registered_estate_executes_the_same_draft_successfully():
    """The registration number is the only difference, and it decides the outcome.

    The PRD states: "The draft names the talent through `talent_id` and declares
    `grantor_kind` — `TALENT` when the living performer will execute the grant, `ESTATE`
    when a verified estate will. When `grantor_kind` is `ESTATE`, `estate_authority_id`
    must name the estate authority that will execute it; when `grantor_kind` is `TALENT`,
    `estate_authority_id` must be null." The successful draft opens where every draft
    opens: "Drafting stamps `status` as `PENDING_COUNTERSIGN`, records the drafting
    administrator as `drafted_by_user_id`, leaves `suspension_reason`, `countersigned_at`
    and `effective_end_actual` null, and initialises `initial_compensation_cents`,
    `union_topup_cents` and `total_compensation_cents` to zero."

    Design: Corner/errors/estate_grant_needs_the_registration_number_the_state_demands
    """
    _unregistered, registered = _two_estates_differing_only_in_their_registration()

    talent = fixtures.read_talent(registered)
    assert talent["postmortem_registration_number"] == "CA-REG-88"

    granted = validate_success(_draft_an_estate_grant(registered), 201)
    assert granted["status"] == "PENDING_COUNTERSIGN"
    assert granted["grantor_kind"] == "ESTATE"
    assert granted["estate_authority_id"] == registered["estate_authority"]["id"]
    assert granted["drafted_by_user_id"] == registered["second_admin_user_id"]
    assert granted["total_compensation_cents"] == 0

    _rows, meta = _grants_of(registered)
    assert meta["total_count"] == 1
