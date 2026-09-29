"""One revoke call, five hops: replica, output, licence, retention and posture."""

from test_helpers import assertions, fixtures


def _live_licence_on_the_fifteenth_of_september():
    """The full chain live in the world, with the clock at 2026-09-15."""
    scenario = fixtures.campaign_live_license()
    fixtures.move_clock("2026-09-15T00:00:00Z", scenario["admin_headers"])
    return scenario


def test_revocation_quarantines_the_replica_and_withdraws_its_output():
    """Hops one to three: the grant ends, the replica is held, the output falls.

    The PRD states: "Because the grant has ended, hop two does two things: every
    biometric asset of this grant whose `status` is `STORED` or `PURGE_SCHEDULED`
    has its `retention_until` recomputed against the new effective end — and, for
    an asset already in `PURGE_SCHEDULED`, its `purge_due_at` recomputed with it —
    and every digital replica of this grant whose `status` is `BUILT` or
    `APPROVED_FOR_USE` moves to `QUARANTINED` with `quarantine_reason` of
    `CONSENT_REVOKED` and `held_from_status` set to the status it just left."

    Design: Difficulty/transitive_cascade/consent_revoke_five_hop_cascade_to_removal_obligation
    """
    scenario = _live_licence_on_the_fifteenth_of_september()

    fixtures.revoke_grant(scenario)

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "REVOKED"
    assert grant["effective_end_actual"] == "2026-09-15T00:00:00Z"

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "QUARANTINED"
    assert replica["quarantine_reason"] == "CONSENT_REVOKED"
    assert replica["held_from_status"] == "APPROVED_FOR_USE"

    performance = fixtures.refresh_performance(scenario)
    assert performance["review_status"] == "WITHDRAWN"
    assert performance["provisional_compensation_cents"] == 0


def test_revocation_raises_a_fourteen_day_removal_obligation_on_the_live_licence():
    """Hop four dates the obligation from the revocation, not from the window.

    The PRD states: "Because those performances are withdrawn, hop four moves every
    usage license on them whose `distribution_status` is `ISSUED` or `LIVE` to
    `REMOVAL_PENDING`, stamping `removal_reason` as `CONSENT_REVOKED` and computing
    a fresh `removal_deadline`; each affected replica's `open_license_count` is
    recomputed." The deadline itself follows the domicile profile: "In every case
    `removal_deadline` is computed as the current logical instant advanced by the
    domicile profile's `removal_window_days`: an obligation raised on 2 August 2027
    for a talent in a state allowing fourteen days gives a deadline of
    `2027-08-16T00:00:00Z`, and the same obligation for a talent in a state
    allowing twenty-one days gives `2027-08-23T00:00:00Z`."

    Design: Difficulty/transitive_cascade/consent_revoke_five_hop_cascade_to_removal_obligation
    """
    scenario = _live_licence_on_the_fifteenth_of_september()

    fixtures.revoke_grant(scenario)

    license_row = fixtures.refresh_license(scenario)
    assert license_row["distribution_status"] == "REMOVAL_PENDING"
    assert license_row["removal_reason"] == "CONSENT_REVOKED"
    assert license_row["removal_deadline"] == "2026-09-29T00:00:00Z"
    assert license_row["compliance_status"] == "VERIFIED"

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(talent, open_removal_obligation_count=1)
    assertions.assert_posture(talent, "RESTRICTED")


def test_revocation_pulls_the_retention_deadline_in_and_reverses_only_the_projection():
    """Hop five shortens custody to the contract, and the money nets to 770250.

    The PRD states: "If that grant is then revoked on 15 September 2026, the
    contractual deadline moves to 15 October 2026 while the statutory deadline
    stays where it was, so `retention_until` becomes `2026-10-15T00:00:00Z` and the
    contract binds." The delivery accrual is untouched, because only a live
    projection is wound back: "for each withdrawn performance carrying a live
    provisional accrual — a `provisional_compensation_cents` greater than zero — a
    `REVERSAL` entry is appended for the exact negation of that accrual, naming the
    live `PER_USE_PROVISIONAL` entry through `reverses_entry_id`, and
    `provisional_compensation_cents` is set to zero."

    Design: Difficulty/transitive_cascade/consent_revoke_five_hop_cascade_to_removal_obligation
    """
    scenario = _live_licence_on_the_fifteenth_of_september()
    assert fixtures.refresh_asset(scenario)["retention_until"] == "2027-08-01T00:00:00Z"

    fixtures.revoke_grant(scenario)

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "STORED"
    assert asset["retention_until"] == "2026-10-15T00:00:00Z"

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL", "REVERSAL"],
    )
    assertions.assert_ledger_entry(entries[3], "REVERSAL", -346_500)
    assertions.assert_exact_negation(entries[3], entries[1])
    assertions.assert_ledger_sums_to(entries, 770_250)

    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 770_250
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=770_250
    )
