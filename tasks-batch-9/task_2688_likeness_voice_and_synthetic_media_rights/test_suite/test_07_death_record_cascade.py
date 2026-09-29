"""Recording a death: three hops down to a restricted posture, and no money."""

from test_helpers import assertions, fixtures

FACE_ASSET = {
    "asset_kind": "FACE_SCAN",
    "capture_ref": "cap-002",
    "storage_class": "COLD_ARCHIVE",
    "payload_digest": "sha256:bbb",
}

FACE_REPLICA = {"replica_kind": "FACE", "build_ref": "build-002"}


def _approved_face_replica():
    """A living talent's face replica cleared for use, nothing generated yet."""
    return fixtures.campaign_approved_replica(
        asset_overrides=FACE_ASSET, replica_overrides=FACE_REPLICA
    )


def test_death_suspends_the_talent_granted_consent_and_quarantines_its_replica():
    """The consent is suspended pending the estate, not revoked outright.

    The PRD states: "Because of that, the second hop moves every consent grant of
    this talent whose `status` is `ACTIVE` and whose `grantor_kind` is `TALENT`
    from `ACTIVE` to `SUSPENDED`, stamping `suspension_reason` as
    `DEATH_PENDING_ESTATE` — the living person who executed those grants can no
    longer stand behind them." And: "Because those grants are now suspended, the
    third hop moves every digital replica whose governing grant is in that set and
    whose `status` is `BUILT` or `APPROVED_FOR_USE` to `QUARANTINED`, recording
    `quarantine_reason` as `ESTATE_PENDING` and `held_from_status` as whatever
    status the replica held immediately before the hop."

    Design: Difficulty/transitive_cascade/death_record_three_hop_cascade_to_restricted_posture
    """
    scenario = _approved_face_replica()

    fixtures.record_death(scenario, {"date_of_death": "2026-08-01T00:00:00Z"})

    talent = fixtures.read_talent(scenario)
    assert talent["life_status"] == "DECEASED"
    assert talent["postmortem_rights_until"] == "2096-08-01T00:00:00Z"
    assertions.assert_posture(talent, "RESTRICTED")

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "SUSPENDED"
    assert grant["status"] != "REVOKED"
    assert grant["suspension_reason"] == "DEATH_PENDING_ESTATE"
    assert grant["effective_end_actual"] is None

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "QUARANTINED"
    assert replica["quarantine_reason"] == "ESTATE_PENDING"
    assert replica["held_from_status"] == "APPROVED_FOR_USE"


def test_death_moves_neither_the_ledger_nor_the_custody_deadline():
    """The cascade posts nothing and leaves the sample's deadline where it was.

    The PRD states: "Grants executed by an estate rather than by the living talent
    are left alone, and no biometric asset is disturbed by a death record." The
    deadline is safe because the term did not move: "A suspension recomputation
    changes nothing, since suspending a grant does not move its effective end."

    Design: Difficulty/transitive_cascade/death_record_three_hop_cascade_to_restricted_posture
    """
    scenario = _approved_face_replica()

    fixtures.record_death(scenario, {"date_of_death": "2026-08-01T00:00:00Z"})

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000)
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 300_000
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "STORED"
    assert asset["retention_until"] == "2027-08-01T00:00:00Z"
    assertions.assert_fields_null(asset, "purge_due_at", "purged_at", "held_from_status")
