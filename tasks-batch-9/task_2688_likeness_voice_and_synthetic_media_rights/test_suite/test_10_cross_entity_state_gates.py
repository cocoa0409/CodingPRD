"""Gates that read another entity's status: the same call fails, then succeeds."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

COMPLIANCE_HOLD = {"suspension_reason": "COMPLIANCE_HOLD"}


def _built_replica_under_a_suspended_grant():
    """A replica left in BUILT while its governing grant is put on hold."""
    scenario = fixtures.campaign_built_replica()
    fixtures.suspend_grant(scenario, overrides=COMPLIANCE_HOLD)
    return scenario


def _approve_the_replica(scenario):
    """Send the talent-side approval without asserting the outcome."""
    return api_client.approve_replica_for_use(
        scenario["replica"]["id"],
        factories.approve_replica_payload(),
        scenario["talent_rep_headers"],
    )


def test_a_suspended_grant_blocks_an_approval_the_replica_itself_still_allows():
    """Nothing about the replica changed, yet the approval is refused.

    The PRD states: "The replica must be `BUILT`, or the request draws
    `ERR_INVALID_REPLICA_STATE`; the governing grant must be `ACTIVE`, or
    `ERR_CONSENT_NOT_ACTIVE`; the talent's posture must not be `FROZEN`, or
    `ERR_TALENT_RIGHTS_FROZEN`; and a talent whose `life_status` is `DECEASED` must
    have a `VERIFIED` estate authority, or `ERR_ESTATE_AUTHORITY_UNVERIFIED`." The
    hold leaves the replica alone: "A compliance suspension deliberately does
    **not** quarantine anything: replicas built under the grant keep their status,
    in pointed contrast with the death-record cascade, which does quarantine them."
    The talent's posture follows the grant: "a talent with one `SUSPENDED` grant is
    `RESTRICTED`".

    Design: Difficulty/cross_entity_state_dependency/replica_approval_gated_on_consent_grant_status
    """
    scenario = _built_replica_under_a_suspended_grant()
    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "SUSPENDED"
    assert grant["suspension_reason"] == "COMPLIANCE_HOLD"
    held_version = fixtures.refresh_replica(scenario)["version"]

    validate_error(_approve_the_replica(scenario), "ERR_CONSENT_NOT_ACTIVE")

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "BUILT"
    assertions.assert_versioned(replica, held_version)
    assertions.assert_fields_null(replica, "quarantine_reason", "held_from_status")
    assertions.assert_posture(fixtures.read_talent(scenario), "RESTRICTED")


def test_reinstating_the_grant_lets_the_identical_approval_through():
    """The gate reads the grant, so clearing the hold clears the refusal.

    The PRD states: "`REINSTATE` requires the grant to be `SUSPENDED` and moves it
    `SUSPENDED → ACTIVE`, clearing `suspension_reason` to null." The approval then
    lands as written: "On success the replica moves `BUILT → APPROVED_FOR_USE`,
    `approved_at` records the logical instant, `approved_by_user_id` records the
    approver, and `version` advances by one." None of this is a money event — the
    only entry on the grant is the one countersigning posted: "One entry of type
    `INITIAL_CREATION` is appended for the rounded amount, and only when the union
    floor strictly exceeds that amount is a second entry of type `UNION_TOPUP`
    appended for the difference."

    Design: Difficulty/cross_entity_state_dependency/replica_approval_gated_on_consent_grant_status
    """
    scenario = _built_replica_under_a_suspended_grant()
    validate_error(_approve_the_replica(scenario), "ERR_CONSENT_NOT_ACTIVE")

    reinstated = fixtures.reinstate_grant(scenario)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")

    approved = validate_success(_approve_the_replica(scenario), 200)
    assert approved["status"] == "APPROVED_FOR_USE"
    assert approved["approved_by_user_id"] == scenario["talent"]["id"]

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000)


def _purge_the_source_asset(scenario):
    """Ask for the manual destruction without asserting the outcome."""
    return api_client.purge_biometric_asset(
        scenario["asset"]["id"], factories.purge_payload(), scenario["admin_headers"]
    )


def test_an_approved_replica_blocks_the_purge_of_the_sample_it_was_trained_on():
    """The asset is purgeable by its own status, and refused all the same.

    The PRD states: "And an asset still listed in the `source_asset_ids` of any
    replica whose `status` is `BUILT` or `APPROVED_FOR_USE` is refused with
    `ERR_ASSET_BOUND_TO_ACTIVE_REPLICA`, because purging it would orphan a live
    replica's provenance." Its own status would otherwise admit the request: "It is
    admissible from `STORED` and from `PURGE_SCHEDULED`, and moves the asset to
    `PURGED` with `payload_digest` cleared to null, `purged_at` stamped and
    `purge_due_at` left exactly as it was."

    Design: Difficulty/cross_entity_state_dependency/asset_purge_gated_on_bound_replica_status
    """
    scenario = fixtures.campaign_approved_replica()
    assert fixtures.refresh_replica(scenario)["status"] == "APPROVED_FOR_USE"

    validate_error(_purge_the_source_asset(scenario), "ERR_ASSET_BOUND_TO_ACTIVE_REPLICA")

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "STORED"
    assert asset["payload_digest"] == "sha256:aaa"
    assertions.assert_fields_null(asset, "purged_at")


def test_quarantining_that_replica_unblocks_the_identical_purge():
    """The revoke cascade impounds the replica but never destroys the sample.

    The PRD states: "every digital replica of this grant whose `status` is `BUILT`
    or `APPROVED_FOR_USE` moves to `QUARANTINED` with `quarantine_reason` of
    `CONSENT_REVOKED` and `held_from_status` set to the status it just left." The
    sample's deadline moves instead: "`retention_until` is whichever of the two
    comes first, and when the two coincide that shared instant is the answer." The
    once-refused purge then completes: "moves the asset to `PURGED` with
    `payload_digest` cleared to null, `purged_at` stamped and `purge_due_at` left
    exactly as it was" — and "the asset's `version` advances by one on every one of
    these moves."

    Design: Difficulty/cross_entity_state_dependency/asset_purge_gated_on_bound_replica_status
    """
    scenario = fixtures.campaign_approved_replica()
    validate_error(_purge_the_source_asset(scenario), "ERR_ASSET_BOUND_TO_ACTIVE_REPLICA")

    fixtures.revoke_grant(scenario)

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "QUARANTINED"
    assert replica["quarantine_reason"] == "CONSENT_REVOKED"

    stored = fixtures.refresh_asset(scenario)
    assert stored["status"] == "STORED"
    assert stored["retention_until"] == "2026-08-31T00:00:00Z"

    purged = validate_success(_purge_the_source_asset(scenario), 200)
    assert purged["status"] == "PURGED"
    assert purged["payload_digest"] is None
    assert purged["purged_at"] == "2026-08-01T00:00:00Z"
    assertions.assert_version_advanced_by(purged, stored["version"])

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000)


ESTATE_CLAIM = {
    "executor_name": "R. Reyes",
    "court_document_ref": "CA-PROB-2026-118",
    "registration_number": "CA-REG-55123",
}


def _submitted_output_of_a_talent_who_just_died():
    """A SUBMITTED output whose talent died, the estate claim still unverified."""
    scenario = fixtures.campaign_submitted_performance()
    fixtures.record_death(scenario, {"date_of_death": "2026-08-01T00:00:00Z"})
    fixtures.submit_estate_authority(scenario, ESTATE_CLAIM)
    return scenario


def _approve_the_performance(scenario, headers):
    """Record the APPROVE decision from whichever side is named."""
    return api_client.review_generated_performance(
        scenario["performance"]["id"],
        factories.review_payload("APPROVE", review_note="estate has no objection"),
        headers,
    )


def test_the_death_record_suspends_the_grant_and_the_review_stalls_on_it():
    """The output never moved; the talent's death closed the grant under it.

    The PRD states: "Because of that, the second hop moves every consent grant of
    this talent whose `status` is `ACTIVE` and whose `grantor_kind` is `TALENT` from
    `ACTIVE` to `SUSPENDED`, stamping `suspension_reason` as `DEATH_PENDING_ESTATE`
    — the living person who executed those grants can no longer stand behind them.
    Because those grants are now suspended, the third hop moves every digital
    replica whose governing grant is in that set and whose `status` is `BUILT` or
    `APPROVED_FOR_USE` to `QUARANTINED`, recording `quarantine_reason` as
    `ESTATE_PENDING` and `held_from_status` as whatever status the replica held
    immediately before the hop." The review reads the grant: "The performance must
    be `SUBMITTED`, or the decision draws `ERR_INVALID_PERFORMANCE_STATE`; the grant
    must be `ACTIVE`; the posture must not be `FROZEN`; and a deceased talent must
    have a `VERIFIED` estate authority." The inactive grant is reported ahead of the
    missing paperwork: "State-machine admissibility follows, in this internal order:
    `ERR_INVALID_TALENT_STATE`, `ERR_INVALID_ESTATE_AUTHORITY_STATE`,
    `ERR_INVALID_CONSENT_STATE`, `ERR_CONSENT_NOT_ACTIVE`, `ERR_INVALID_ASSET_STATE`,
    `ERR_INVALID_REPLICA_STATE`, `ERR_INVALID_PERFORMANCE_STATE`,
    `ERR_INVALID_LICENSE_STATE`, `ERR_INVALID_DISCLOSURE_STATE`,
    `ERR_INVALID_CASE_STATE` — all HTTP 409. Then the posture gates in order:
    `ERR_TALENT_RIGHTS_FROZEN`, then `ERR_TALENT_RIGHTS_RESTRICTED`, then the
    deceased-talent gate `ERR_ESTATE_AUTHORITY_UNVERIFIED`, which requires that a
    talent whose `life_status` is `DECEASED` have at least one `VERIFIED` estate
    authority before any consent, approval or license activity proceeds (that gate
    applies to consent drafting, countersign, replica approval and performance
    review)."

    Design: Difficulty/cross_entity_state_dependency/performance_review_gated_on_talent_life_status_and_estate_verification
    """
    scenario = _submitted_output_of_a_talent_who_just_died()

    talent = fixtures.read_talent(scenario)
    assert talent["life_status"] == "DECEASED"
    assert talent["postmortem_rights_until"] == "2096-08-01T00:00:00Z"
    assertions.assert_posture(talent, "RESTRICTED")

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "SUSPENDED"
    assert grant["suspension_reason"] == "DEATH_PENDING_ESTATE"

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "QUARANTINED"
    assert replica["quarantine_reason"] == "ESTATE_PENDING"
    assert replica["held_from_status"] == "APPROVED_FOR_USE"

    response = _approve_the_performance(scenario, scenario["talent_rep_headers"])
    validate_error(response, "ERR_CONSENT_NOT_ACTIVE")

    performance = fixtures.refresh_performance(scenario)
    assert performance["review_status"] == "SUBMITTED"
    assert performance["provisional_compensation_cents"] == 346_500


def test_verification_by_a_second_administrator_releases_what_the_death_suspended():
    """One verify call restores the grant, the replica and the posture at once.

    The PRD states: "On success the claim's `status` becomes `VERIFIED`,
    `verified_by_user_id` records the verifier and `verified_at` records the logical
    instant. The talent's `postmortem_registration_number` is then copied from this
    authority's `registration_number`, so a state that demands registration can be
    satisfied from the estate paperwork. Verification also releases what the death
    record suspended: every consent grant of this talent sitting in `SUSPENDED` with
    `suspension_reason` of `DEATH_PENDING_ESTATE` returns to `ACTIVE` with its reason
    cleared, and every digital replica quarantined with `quarantine_reason` of
    `ESTATE_PENDING` returns to exactly its `held_from_status`, with both
    `quarantine_reason` and `held_from_status` cleared, rows processed in
    `created_at` ascending order." With the hold gone the posture follows the grant:
    "A talent with no cases, one `ACTIVE` grant and no open removal obligations is
    `CLEAR`".

    Design: Difficulty/cross_entity_state_dependency/performance_review_gated_on_talent_life_status_and_estate_verification
    """
    scenario = _submitted_output_of_a_talent_who_just_died()
    submitted_by = scenario["estate_authority"]["submitted_by_user_id"]

    fixtures.verify_estate_authority(scenario, scenario["second_admin_headers"])

    authority = scenario["estate_authority"]
    assert authority["status"] == "VERIFIED"
    assert authority["verified_by_user_id"] == scenario["second_admin_user_id"]
    assert authority["verified_by_user_id"] != submitted_by

    talent = fixtures.read_talent(scenario)
    assert talent["postmortem_registration_number"] == "CA-REG-55123"
    assertions.assert_posture(talent, "CLEAR")

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "ACTIVE"
    assert grant["suspension_reason"] is None

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "APPROVED_FOR_USE"
    assertions.assert_fields_null(replica, "quarantine_reason", "held_from_status")


def test_the_estate_representative_then_approves_and_the_accrual_never_moved():
    """The verified estate holds the approval right the dead talent held.

    The PRD states: "A `TalentRepresentative` whose identifier equals the talent
    behind the performance, or an `EstateRepresentative` holding that talent's
    `VERIFIED` estate authority, records a `decision` of `APPROVE`,
    `REQUEST_REVISION` or `REJECT`, with an optional `review_note` stored alongside
    it and, for an outright rejection, a `rejection_reason`." The money is left
    exactly where submission put it: "`APPROVE` moves the performance `SUBMITTED →
    APPROVED`, records `reviewed_by_user_id`, and **retains** the provisional
    accrual — it is reversed only by rejection, withdrawal or resubmission."

    Design: Difficulty/cross_entity_state_dependency/performance_review_gated_on_talent_life_status_and_estate_verification
    """
    scenario = _submitted_output_of_a_talent_who_just_died()
    fixtures.verify_estate_authority(scenario, scenario["second_admin_headers"])

    approved = validate_success(
        _approve_the_performance(scenario, scenario["estate_rep_headers"]), 200
    )
    assert approved["review_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == scenario["estate_authority"]["id"]
    assert approved["provisional_compensation_cents"] == 346_500

    entries = fixtures.ledger_entries(
        scenario,
        {"generated_performance_id": scenario["performance"]["id"], "limit": 100},
    )
    assertions.assert_entry_types(entries, ["PER_USE_PROVISIONAL"])
    assertions.assert_ledger_entry(entries[0], "PER_USE_PROVISIONAL", 346_500)
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 646_500
