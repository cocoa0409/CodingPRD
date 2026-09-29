"""The two-dimensional licence, terminal grants and repeat transitions."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _license_ledger(scenario):
    """Every ledger row raised against the scenario's licence."""
    return fixtures.ledger_entries(
        scenario, {"usage_license_id": scenario["license"]["id"]}
    )


def test_a_new_licence_starts_issued_and_pending_label_at_once():
    """Both dimensions are stamped on the same row, and the money with them.

    The PRD states: "Issuance stamps `distribution_status` as `ISSUED`, copies
    `licensee_user_id` from the performance so ownership survives independently of
    who called, and records the issuing user as `issued_by_user_id`. It also resolves
    the disclosure obligation from the talent's domicile profile:
    `disclosure_required` is taken from that profile's
    `disclosure_required_advertising` when `channel` is `ADVERTISING` and from
    `disclosure_required_entertainment` when `channel` is `ENTERTAINMENT`. When
    disclosure is required, `compliance_status` starts at `PENDING_LABEL`; when it is
    not required, `compliance_status` starts directly at `VERIFIED`, since there is
    nothing to label and nothing to check. `disclosure_placement`,
    `disclosure_label_text` and `disclosure_verified_by_user_id` all start null, as do
    `removal_deadline`, `removal_reason` and `removal_confirmed_at`." The money is the
    worked case: "The same base fee of 150000 cents on an `ADVERTISING` license
    delivering twelve million impressions across two territories composes to 150000
    multiplied by 1.90, 1.50 and 1.10, which is 470250" and "A final royalty of
    470250 cents on an `ADVERTISING` license where disclosure is required yields
    8229.375, which rounds up to a surcharge of 8230 and a total of 478480". The
    replica moves too: "Issuance finally increments the replica's `open_license_count`
    by one, recomputes the grant's `total_compensation_cents` and the talent's
    `lifetime_compensation_cents`, and advances the replica's and the talent's
    `version` by one each."

    Design: Corner/state_machines/usage_license_starts_in_issued_and_pending_label
    """
    scenario = fixtures.campaign_approved_performance()
    replica_version = fixtures.refresh_replica(scenario)["version"]

    fixtures.issue_license(scenario, fixtures.CAMPAIGN_LICENSE)
    issued = scenario["license"]

    assertions.assert_subset_equal(
        issued,
        {
            "distribution_status": "ISSUED",
            "compliance_status": "PENDING_LABEL",
            "disclosure_required": True,
            "licensee_user_id": scenario["licensee_user_id"],
            "issued_by_user_id": scenario["licensee_user_id"],
            "per_use_final_cents": 470_250,
            "compliance_surcharge_cents": 8_230,
            "license_total_cents": 478_480,
            "version": 1,
        },
    )
    assertions.assert_fields_null(
        issued,
        "disclosure_placement",
        "disclosure_label_text",
        "disclosure_verified_by_user_id",
        "removal_deadline",
        "removal_reason",
        "removal_confirmed_at",
    )

    replica = fixtures.refresh_replica(scenario)
    assert replica["open_license_count"] == 1
    assertions.assert_version_advanced_by(replica, replica_version)


def test_go_live_advances_only_the_distribution_dimension():
    """A verified label plus a clock inside the window moves ISSUED to LIVE.

    The PRD states: "Going live is the owning `LicenseeProducer`'s act and carries
    the `distribution_reference` — the URL or asset reference where the synthetic
    content is published, 1 to 300 characters and not blank. It moves
    `distribution_status` `ISSUED → LIVE` and stores that reference." The disclosure
    side is left where the officer left it: "`ACCEPT` moves `compliance_status`
    `LABELED → VERIFIED` and records the reviewing officer as
    `disclosure_verified_by_user_id`." No royalty is raised by the move, because the
    delivery accrual was raised at issuance: "The result is written to
    `per_use_final_cents` and posted as a `PER_USE_FINAL` ledger entry split three
    ways."

    Design: Corner/state_machines/go_live_moves_issued_license_to_live_once_disclosure_is_verified
    """
    scenario = fixtures.campaign_live_license()

    live = fixtures.refresh_license(scenario)
    assertions.assert_subset_equal(
        live,
        {
            "distribution_status": "LIVE",
            "distribution_reference": "spot-ref-001",
            "compliance_status": "VERIFIED",
            "disclosure_verified_by_user_id": scenario["compliance_user_id"],
        },
    )

    entries = _license_ledger(scenario)
    assertions.assert_entry_types(entries, ["PER_USE_FINAL"])
    assertions.assert_ledger_entry(entries[0], "PER_USE_FINAL", 470_250)


def _issued_licence_with_a_verified_label():
    """An ISSUED licence whose PRE_ROLL label the officer has accepted."""
    scenario = fixtures.campaign_issued_license()
    fixtures.attest_disclosure(
        scenario,
        {
            "disclosure_placement": "PRE_ROLL",
            "disclosure_label_text": "Voice generated with a licensed digital replica",
        },
    )
    fixtures.verify_disclosure(scenario, "ACCEPT")
    return scenario


def _go_live(scenario, headers=None):
    """Attempt to publish, outcome unasserted."""
    return api_client.go_live(
        scenario["license"]["id"],
        factories.go_live_payload(distribution_reference="spot-ref-001"),
        headers or scenario["licensee_headers"],
    )


def test_a_clock_one_day_short_of_the_window_refuses_the_go_live():
    """Only the instant is wrong, and the licence does not budge for it.

    The PRD states: "Four conditions guard it: the license must be `ISSUED`, or
    `ERR_INVALID_LICENSE_STATE`; `compliance_status` must be `VERIFIED`, or
    `ERR_DISCLOSURE_NOT_VERIFIED`; the current logical instant must lie inside the
    closed window from `distribution_start` through `distribution_end` inclusive, or
    `ERR_OUTSIDE_DISTRIBUTION_WINDOW`; and the governing grant must still be
    `ACTIVE`, or `ERR_CONSENT_NOT_ACTIVE`." Ownership is answered before any of them:
    "Ownership and duty separation follow, in this order:
    `ERR_NOT_TALENT_REPRESENTATIVE`, then `ERR_NOT_ESTATE_REPRESENTATIVE` (both
    applying to countersign, revoke, replica approval and performance review), then
    `ERR_NOT_LICENSEE_OWNER` (applying to resubmission, license issuance, disclosure
    attestation, go-live and removal confirmation), then `ERR_SEGREGATION_OF_DUTIES`
    (applying to estate-authority verification and case escalation)."

    Design: Corner/state_machines/go_live_before_distribution_window_is_refused
    """
    scenario = _issued_licence_with_a_verified_label()
    fixtures.move_clock("2026-08-31T00:00:00Z", scenario["admin_headers"])

    validate_error(_go_live(scenario), "ERR_OUTSIDE_DISTRIBUTION_WINDOW")

    refused = fixtures.refresh_license(scenario)
    assert refused["distribution_status"] == "ISSUED"
    assert refused["distribution_reference"] is None

    fixtures.move_clock("2026-09-01T00:00:00Z", scenario["admin_headers"])
    published = validate_success(_go_live(scenario), 200)
    assert published["distribution_status"] == "LIVE"

    validate_error(
        _go_live(scenario, scenario["other_licensee_headers"]),
        "ERR_NOT_LICENSEE_OWNER",
    )


def test_countersigning_twice_pays_the_creation_fee_only_once():
    """The second signature is a state error, not a second payment.

    The PRD states: "A grant not in `PENDING_COUNTERSIGN` draws
    `ERR_INVALID_CONSENT_STATE`; a talent whose posture is `FROZEN` draws
    `ERR_TALENT_RIGHTS_FROZEN`; a deceased talent with no `VERIFIED` estate authority
    draws `ERR_ESTATE_AUTHORITY_UNVERIFIED`; a state that requires registration where
    the talent has none draws `ERR_POSTMORTEM_REGISTRATION_MISSING`; and a missing
    union row draws `ERR_UNION_SCHEDULE_MISSING`." The payment belongs to the one
    successful signature: "One entry of type `INITIAL_CREATION` is appended for the
    rounded amount, and only when the union floor strictly exceeds that amount is a
    second entry of type `UNION_TOPUP` appended for the difference."

    Design: Corner/state_machines/second_countersign_of_the_same_grant_is_refused
    """
    scenario = fixtures.campaign_active_grant()
    active = fixtures.refresh_grant(scenario)

    validate_error(
        api_client.countersign_consent_grant(
            active["id"], {}, scenario["talent_rep_headers"]
        ),
        "ERR_INVALID_CONSENT_STATE",
    )

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    unchanged = fixtures.refresh_grant(scenario)
    assert unchanged["total_compensation_cents"] == 300_000
    assertions.assert_versioned(unchanged, active["version"])
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )


def _approve_again(scenario, headers=None):
    """Send approve-for-use at an already approved replica."""
    return api_client.approve_replica_for_use(
        scenario["replica"]["id"],
        factories.approve_replica_payload(approval_note="second approval"),
        headers or scenario["talent_rep_headers"],
    )


def test_approving_an_approved_replica_leaves_the_first_approver_of_record():
    """APPROVED_FOR_USE is not in the from-set, and the ownership rung outranks it.

    The PRD states: "The replica must be `BUILT`, or the request draws
    `ERR_INVALID_REPLICA_STATE`; the governing grant must be `ACTIVE`, or
    `ERR_CONSENT_NOT_ACTIVE`; the talent's posture must not be `FROZEN`, or
    `ERR_TALENT_RIGHTS_FROZEN`; and a talent whose `life_status` is `DECEASED` must
    have a `VERIFIED` estate authority, or `ERR_ESTATE_AUTHORITY_UNVERIFIED`." The
    first decision is the recorded one: "On success the replica moves `BUILT →
    APPROVED_FOR_USE`, `approved_at` records the logical instant,
    `approved_by_user_id` records the approver, and `version` advances by one." A
    stranger is turned away earlier still: "Ownership and duty separation follow, in
    this order: `ERR_NOT_TALENT_REPRESENTATIVE`, then
    `ERR_NOT_ESTATE_REPRESENTATIVE` (both applying to countersign, revoke, replica
    approval and performance review)".

    Design: Corner/state_machines/approve_for_use_on_an_already_approved_replica_is_refused
    """
    scenario = fixtures.campaign_approved_replica()
    approved = fixtures.refresh_replica(scenario)

    validate_error(_approve_again(scenario), "ERR_INVALID_REPLICA_STATE")

    still = fixtures.refresh_replica(scenario)
    assertions.assert_subset_equal(
        still,
        {
            "status": "APPROVED_FOR_USE",
            "approved_by_user_id": approved["approved_by_user_id"],
            "approved_at": approved["approved_at"],
            "version": approved["version"],
        },
    )

    stranger = fixtures.make_talent_representative_headers(
        "00000000-0000-4000-8000-00000000abcd"
    )
    validate_error(
        _approve_again(scenario, stranger), "ERR_NOT_TALENT_REPRESENTATIVE"
    )


def test_a_revoked_grant_takes_neither_a_second_revoke_nor_a_suspension():
    """Both attempts are state errors, and the revocation instant stands.

    The PRD states: "It is admissible from `PENDING_COUNTERSIGN`, `ACTIVE` or
    `SUSPENDED` and refused from a terminal status with `ERR_INVALID_CONSENT_STATE`."
    A suspension is refused on the same ground: "A suspension request against a grant
    in any other status — a terminal grant, or an attempt to reinstate one that is
    already `ACTIVE` — draws `ERR_INVALID_CONSENT_STATE`." The terminal grant no
    longer colours the talent: "Terminal case statuses — `DISMISSED_LICENSED`,
    `DISMISSED_NO_ACTION`, `RESOLVED_REMOVED`, `CLOSED_SETTLED` and
    `CLOSED_LITIGATED` — contribute nothing, and neither do the terminal grant
    statuses `REVOKED` and `EXPIRED`."

    Design: Corner/state_machines/revoked_grant_is_terminal_and_refuses_further_transitions
    """
    scenario = fixtures.campaign_active_grant()
    fixtures.revoke_grant(scenario)
    revoked = fixtures.refresh_grant(scenario)
    assert revoked["status"] == "REVOKED"
    assert revoked["effective_end_actual"] == "2026-08-01T00:00:00Z"

    validate_error(
        api_client.revoke_consent_grant(
            revoked["id"],
            factories.revoke_payload(revocation_note="second revocation"),
            scenario["talent_rep_headers"],
        ),
        "ERR_INVALID_CONSENT_STATE",
    )
    validate_error(
        api_client.change_consent_grant_suspension(
            revoked["id"],
            factories.suspension_payload("SUSPEND", suspension_reason="COMPLIANCE_HOLD"),
            scenario["admin_headers"],
        ),
        "ERR_INVALID_CONSENT_STATE",
    )

    after = fixtures.refresh_grant(scenario)
    assert after["status"] == "REVOKED"
    assert after["effective_end_actual"] == "2026-08-01T00:00:00Z"
    assertions.assert_posture(fixtures.read_talent(scenario), "CLEAR")


def test_the_disclosure_dimension_cycles_while_distribution_stands_still():
    """Label, rejection, relabel and acceptance all leave ISSUED untouched.

    The PRD states: "A usage license carries two status dimensions on one row, and
    they advance independently. `distribution_status` tracks where the content stands
    in the world and moves through `ISSUED`, `LIVE`, `REMOVAL_PENDING` and the
    terminal `REMOVAL_CONFIRMED`. `compliance_status` tracks the synthetic-content
    disclosure and moves through `PENDING_LABEL`, `LABELED`, `VERIFIED` and
    `NON_COMPLIANT`." Re-attestation is the cycle: "Attestation is admissible when
    `compliance_status` is `PENDING_LABEL` or `NON_COMPLIANT` — re-attestation after a
    rejection is the cycle in this dimension — and is refused with
    `ERR_INVALID_DISCLOSURE_STATE` when the license is already `LABELED` or
    `VERIFIED`." A rejection keeps the evidence: "`REJECT` moves it `LABELED →
    NON_COMPLIANT` and leaves `disclosure_verified_by_user_id` null, while
    `disclosure_placement` and `disclosure_label_text` are retained for the audit
    trail rather than cleared, so a reviewer can see what was claimed."

    Design: Corner/state_machines/disclosure_dimension_moves_without_disturbing_distribution_dimension
    """
    scenario = fixtures.campaign_issued_license()

    labeled = fixtures.attest_disclosure(
        scenario,
        {"disclosure_placement": "PRE_ROLL", "disclosure_label_text": "AI voice"},
    )
    assert labeled["compliance_status"] == "LABELED"
    assert labeled["distribution_status"] == "ISSUED"

    rejected = fixtures.verify_disclosure(scenario, "REJECT")
    assert rejected["compliance_status"] == "NON_COMPLIANT"
    assert rejected["distribution_status"] == "ISSUED"
    assert rejected["disclosure_verified_by_user_id"] is None
    assert rejected["disclosure_placement"] == "PRE_ROLL"

    reread = fixtures.refresh_license(scenario)
    assert reread["compliance_status"] == "NON_COMPLIANT"
    assert reread["distribution_status"] == "ISSUED"

    relabeled = fixtures.attest_disclosure(
        scenario,
        {
            "disclosure_placement": "PRE_ROLL",
            "disclosure_label_text": "Voice generated with a licensed digital replica",
        },
    )
    assert relabeled["compliance_status"] == "LABELED"
    assert relabeled["distribution_status"] == "ISSUED"

    verified = fixtures.verify_disclosure(scenario, "ACCEPT")
    assert verified["compliance_status"] == "VERIFIED"
    assert verified["distribution_status"] == "ISSUED"
    assert verified["disclosure_verified_by_user_id"] == scenario["compliance_user_id"]


REJECTED_TAKE = {"intended_use_description": "rejected take"}
APPROVED_TAKE = {"intended_use_description": "approved take"}


def _one_rejected_and_one_licensed_output():
    """p1 rejected and already reversed; p2 approved and licensed."""
    scenario = fixtures.campaign_approved_replica()

    fixtures.submit_performance(
        scenario, dict(fixtures.CAMPAIGN_PERFORMANCE, **REJECTED_TAKE)
    )
    fixtures.review_performance(
        scenario,
        "REJECT",
        {"review_note": "off brand", "rejection_reason": "OFF_BRAND"},
    )
    scenario["p1"] = fixtures.refresh_performance(scenario)

    fixtures.submit_performance(
        scenario, dict(fixtures.CAMPAIGN_PERFORMANCE, **APPROVED_TAKE)
    )
    fixtures.review_performance(scenario, "APPROVE", {"review_note": "ok"})
    scenario["p2"] = fixtures.refresh_performance(scenario)

    fixtures.issue_license(
        scenario, fixtures.CAMPAIGN_LICENSE, performance=scenario["p2"]
    )
    return scenario


def test_the_revocation_cascade_leaves_the_already_reversed_output_alone():
    """One new reversal, not two: the rejected take is already settled.

    The PRD states: "Because those replicas are quarantined, hop three moves every
    generated performance under them whose `review_status` is `SUBMITTED`,
    `REVISION_REQUESTED` or `APPROVED` to `WITHDRAWN`; for each withdrawn performance
    carrying a live provisional accrual — a `provisional_compensation_cents` greater
    than zero — a `REVERSAL` entry is appended for the exact negation of that accrual,
    naming the live `PER_USE_PROVISIONAL` entry through `reverses_entry_id`, and
    `provisional_compensation_cents` is set to zero." A hop's input set is what the
    hop before it actually moved: "First, hops execute in the stated order, and each
    hop's input set is the set of rows the previous hop actually changed — a hop that
    changes nothing stops the chain beneath it." The licence follows: "Because those
    performances are withdrawn, hop four moves every usage license on them whose
    `distribution_status` is `ISSUED` or `LIVE` to `REMOVAL_PENDING`, stamping
    `removal_reason` as `CONSENT_REVOKED` and computing a fresh `removal_deadline`;
    each affected replica's `open_license_count` is recomputed."

    Design: Corner/state_machines/revocation_cascade_skips_children_already_in_terminal_states
    """
    scenario = _one_rejected_and_one_licensed_output()

    before = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        before,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "REVERSAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_FINAL",
        ],
    )
    assertions.assert_ledger_sums_to(before, 1_116_750)

    fixtures.revoke_grant(scenario)

    after = fixtures.grant_ledger(scenario)
    assert len(after) == len(before) + 1
    assertions.assert_ledger_entry(after[-1], "REVERSAL", -346_500)
    assertions.assert_ledger_sums_to(after, 770_250)
    assert after[-1]["generated_performance_id"] == scenario["p2"]["id"]

    assert fixtures.refresh_performance(scenario, scenario["p1"])["review_status"] == "REJECTED"
    assert fixtures.refresh_performance(scenario, scenario["p2"])["review_status"] == "WITHDRAWN"

    license_row = fixtures.refresh_license(scenario)
    assertions.assert_subset_equal(
        license_row,
        {
            "distribution_status": "REMOVAL_PENDING",
            "removal_reason": "CONSENT_REVOKED",
            "removal_deadline": "2026-08-15T00:00:00Z",
        },
    )

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(talent, open_removal_obligation_count=1)
    assertions.assert_posture(talent, "RESTRICTED")
