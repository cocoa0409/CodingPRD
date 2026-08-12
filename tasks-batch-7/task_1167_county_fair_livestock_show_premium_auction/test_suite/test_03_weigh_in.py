"""Weigh-in: posture gate, OCC stale versions, official-weight resolution,
manual void rules, and the reweigh un-classify cycle (PRD §2.5, §2.9, §3.3).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_fair_to,
    advance_posture,
    api_client,
    assert_weigh_ticket,
    classify_entry,
    create_class,
    create_exhibitor,
    create_fair,
    create_verified_entry,
    create_weigh_ticket_payload,
    get_class,
    get_entry,
    validate_error,
    validate_success,
    weigh_entry,
)

ADMIN = TEST_USERS["admin"]
WEIGHMASTER = TEST_USERS["weigh_master"]


def _verified_entry_in_weigh_in(name="Fair T03", tag="S-001",
                                species="MARKET_STEER"):
    """Fair walked to WEIGH_IN with one VERIFIED entry, not yet weighed."""
    fair = create_fair(name=name)
    advance_posture(fair["id"], "ENTRIES_OPEN")
    exhibitor = create_exhibitor(fair["id"])
    entry = create_verified_entry(
        fair["id"], exhibitor, species=species, tag_number=tag
    )
    advance_fair_to(fair["id"], "WEIGH_IN")
    return fair, exhibitor, get_entry(entry["id"])


class TestWeighInPostureGate:
    def test_weigh_in_posture_forbidden_during_entries_open(self, api):
        """PRD §2.5: "Entry creation is allowed only in `ENTRIES_OPEN`; entry
        verification is allowed in `ENTRIES_OPEN` or `ENTRIES_LOCKED`; weigh-in
        and classification require `WEIGH_IN`; starting a ring slot and
        submitting placings require `SHOWING`; auction-lot operations require
        `AUCTION`; and invoice issue, invoice payments, premium approval, and
        premium payment all require `SETTLEMENT`. An operation attempted under
        the wrong posture is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409)."

        Design: Corner/validations/weigh_in_posture_forbidden_during_entries_open
        """
        fair = create_fair(name="Fair V6")
        advance_posture(fair["id"], "ENTRIES_OPEN")
        exhibitor = create_exhibitor(fair["id"])
        entry = create_verified_entry(fair["id"], exhibitor, tag_number="S-001")
        current = get_entry(entry["id"])
        resp = api_client.create_weigh_ticket(
            create_weigh_ticket_payload(entry["id"], current["version"]),
            WEIGHMASTER,
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)


class TestWeighTicketOcc:
    def test_occ_weigh_ticket_stale_version_returns_412(self, api):
        """PRD §2.9: "Creating a weigh ticket (`POST /v1/weigh-tickets` — the
        write behind every new ticket, whether a first weigh-in or a reweigh)
        requires `expected_entry_version` carrying the caller's last observed
        `version` of the parent animal entry; recording a ticket advances the
        entry's `version`, so a client holding a stale value — for example one
        that read the entry before an earlier ticket was recorded — is rejected
        deterministically with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_weigh_ticket_stale_version_returns_412
        """
        _fair, _exh, entry = _verified_entry_in_weigh_in("Fair X1")
        stale_version = entry["version"]

        first = weigh_entry(entry["id"], 1200)
        assert_weigh_ticket(first)

        resp = api_client.create_weigh_ticket(
            create_weigh_ticket_payload(
                entry["id"], stale_version, weight_lbs=1205,
                weighed_at="2026-07-01T10:05:00Z",
            ),
            WEIGHMASTER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_entry(entry["id"])["official_weight_lbs"] == 1200, (
            "the loser's write must not be applied"
        )


class TestOfficialWeightResolution:
    def test_official_weight_supersede_and_void_recompute(self, api):
        """PRD §3.3: "Among the entry's weigh tickets in `ACTIVE` status —
        `VOIDED` tickets are excluded — the winner is the ticket with the
        greatest `created_at`; if two tickets share the same `created_at`
        millisecond, the larger `weighed_at` wins; if still tied, the larger
        `weight_lbs` wins."
        PRD §3.3: "After a manual void the official weight is recomputed from
        the remaining `ACTIVE` tickets, and if none remain the entry falls back
        `WEIGHED` → `VERIFIED`."

        Design: Corner/calculations/official_weight_supersede_and_void_recompute
        """
        _fair, _exh, entry = _verified_entry_in_weigh_in("Fair K2")
        weigh_entry(entry["id"], 100, weighed_at="2026-07-01T10:00:00Z")
        after_first = get_entry(entry["id"])
        assert after_first["official_weight_lbs"] == 100
        assert after_first["status"] == "WEIGHED"

        ticket_2 = weigh_entry(entry["id"], 105,
                               weighed_at="2026-07-01T11:00:00Z")
        after_second = get_entry(entry["id"])
        assert after_second["official_weight_lbs"] == 105, (
            "the latest ACTIVE ticket wins"
        )

        voided = validate_success(
            api_client.void_weigh_ticket(
                ticket_2["id"], WEIGHMASTER, reason="scale miscalibration"
            ),
            200,
        )
        assert voided["status"] == "VOIDED"
        after_void = get_entry(entry["id"])
        assert after_void["official_weight_lbs"] is None
        assert after_void["status"] == "VERIFIED", (
            "with no ACTIVE ticket remaining the entry falls back to VERIFIED"
        )

    def test_weigh_ticket_void_rejected_once_entry_classified(self, api):
        """PRD §3.3: "A `WeighMaster` may also void a ticket manually with an
        optional `reason`, but only while the entry is `WEIGHED` — voiding
        against a `CLASSIFIED`-or-later entry is rejected with
        `ERR_INVALID_STATE`, because such an entry is corrected by recording a
        new ticket instead."

        Design: Corner/state_machines/weigh_ticket_void_rejected_once_entry_classified
        """
        _fair, _exh, entry = _verified_entry_in_weigh_in("Fair S6")
        ticket_1 = weigh_entry(entry["id"], 1200)
        show_class = create_class(_fair["id"], species="MARKET_STEER",
                                  class_code="STEER-A")
        classify_entry(entry["id"], show_class["id"])

        resp = api_client.void_weigh_ticket(
            ticket_1["id"], WEIGHMASTER, reason="scale drift"
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        ticket = validate_success(
            api_client.get_weigh_ticket(ticket_1["id"], ADMIN), 200
        )
        assert ticket["status"] == "ACTIVE"


class TestReweighCycle:
    def test_entry_reweigh_cycle_unclassifies_and_reclassifies(self, api):
        """PRD §3.3: "Recording a fresh ticket for a `CLASSIFIED` entry is a
        reweigh: the prior `ACTIVE` ticket is voided with `void_reason`
        `SUPERSEDED`, the entry's `class_id` is cleared to null, the prior
        class's `placed_count` is decremented by one, the entry falls back
        `CLASSIFIED` → `WEIGHED`, and the official weight is recomputed."

        Design: Difficulty/non_linear_state_machine/entry_reweigh_cycle_unclassifies_and_reclassifies
        """
        fair, _exh, entry = _verified_entry_in_weigh_in("Fair R3A")
        weigh_entry(entry["id"], 1200)
        show_class = create_class(fair["id"], species="MARKET_STEER",
                                  class_code="STEER-A")
        classified = classify_entry(entry["id"], show_class["id"])
        assert classified["status"] == "CLASSIFIED"
        assert get_class(show_class["id"])["placed_count"] == 1

        weigh_entry(entry["id"], 1210, weighed_at="2026-07-01T11:00:00Z")
        mid = get_entry(entry["id"])
        assert mid["status"] == "WEIGHED"
        assert mid["class_id"] is None
        assert mid["official_weight_lbs"] == 1210
        assert get_class(show_class["id"])["placed_count"] == 0, (
            "un-classify decrements the prior class"
        )

        reclassified = classify_entry(entry["id"], show_class["id"])
        assert reclassified["status"] == "CLASSIFIED"
        assert get_class(show_class["id"])["placed_count"] == 1

    def test_entry_reweigh_supersedes_ticket_and_bumps_version_once(self, api):
        """PRD §3.3: "Recording a fresh ticket for a `CLASSIFIED` entry is a
        reweigh: the prior `ACTIVE` ticket is voided with `void_reason`
        `SUPERSEDED`, the entry's `class_id` is cleared to null, the prior
        class's `placed_count` is decremented by one, the entry falls back
        `CLASSIFIED` → `WEIGHED`, and the official weight is recomputed."
        PRD §3.3: "Every ticket creation increments the entry's `version` by
        one."

        Design: Difficulty/non_linear_state_machine/entry_reweigh_cycle_unclassifies_and_reclassifies
        """
        fair, _exh, entry = _verified_entry_in_weigh_in("Fair R3A-v")
        ticket_1 = weigh_entry(entry["id"], 1200)
        show_class = create_class(fair["id"], species="MARKET_STEER",
                                  class_code="STEER-A")
        classify_entry(entry["id"], show_class["id"])
        version_before = get_entry(entry["id"])["version"]

        weigh_entry(entry["id"], 1210, weighed_at="2026-07-01T11:00:00Z")
        after = get_entry(entry["id"])
        assert after["version"] == version_before + 1, (
            "one ticket creation advances the entry version by exactly one"
        )
        old_ticket = validate_success(
            api_client.get_weigh_ticket(ticket_1["id"], ADMIN), 200
        )
        assert old_ticket["status"] == "VOIDED"
        assert old_ticket["void_reason"] == "SUPERSEDED"
