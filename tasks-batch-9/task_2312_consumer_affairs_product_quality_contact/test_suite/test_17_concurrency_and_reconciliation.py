"""Version pins and derived counters: the two writes that refuse a superseded
view of their parent, and one live counter watched through every event that is
supposed to move it."""

from test_helpers import (
    ApiErrorId,
    add_complaint,
    add_contact,
    add_kit,
    append_custody,
    assert_goodwill_math,
    assert_two_decimal_value,
    custody_event_payload,
    lab_accept_kit,
    receive_kit,
    remedy_payload,
    seed_base_world,
    seed_shipped_kit,
    seed_triaged_complaint,
    ship_kit,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

SOFT_FOREIGN_MATTER = dict(complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT")


class TestComplaintVersionPin:
    def test_a_remedy_written_against_a_moved_complaint_is_refused(self, api):
        """Two intervening writes invalidate the pin; the re-read version works once.

        PRD: "If `expected_complaint_version` no longer matches, the create is
        rejected with `ERR_STALE_COMPLAINT_VERSION` (HTTP 412) and no `Remedy`
        record is written."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_complaint_version_rejects_the_remedy_write
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "EMAIL", "raw_message": "Stale pack."},
            complaint_type="QUALITY",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        stale_version = world["complaints"]["cp1"]["version"]
        agent = world.headers("ag1")
        lead = world.headers("ql1")

        validate_success(
            api.quality_hold_complaint(complaint_id, {"reason": "Brief look."}, lead)
        )
        released = validate_success(
            api.release_complaint_hold(complaint_id, {"reason": "Cleared."}, lead)
        )
        fresh_version = released["version"]
        assert fresh_version == stale_version + 2

        superseded = api.create_remedy(
            remedy_payload(complaint_id, stale_version, requested_value_cents=1500),
            agent,
        )
        validate_error(superseded, ApiErrorId.STALE_COMPLAINT_VERSION, 412)
        _rows, nothing = validate_paginated(api.list_remedies(agent))
        assert nothing["total_count"] == 0

        accepted = validate_success(
            api.create_remedy(
                remedy_payload(
                    complaint_id, fresh_version, requested_value_cents=1500
                ),
                agent,
            ),
            201,
        )
        assert_goodwill_math(accepted, 1500, 0.10, 150, 1650, "TIER_1")

        _rows, one = validate_paginated(api.list_remedies(agent))
        assert one["total_count"] == 1


class TestCustodyVersionPin:
    def test_each_accepted_append_forces_the_next_one_to_re_read(self, api):
        """Reusing the shipping version after one append is refused, then works re-read.

        PRD: "An append whose `expected_sample_kit_version` does not match is
        rejected with `ERR_STALE_SAMPLE_KIT_VERSION` (HTTP 412) and the chain is
        left untouched."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_sample_kit_version_rejects_the_custody_append
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "PHONE", "raw_message": "Soft matter."},
            **SOFT_FOREIGN_MATTER,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        shipped = seed_shipped_kit(
            api, world, complaint_id, kit_code="K-D01", seal_id_issued="SEAL-D01"
        )
        kit_id = shipped["id"]
        agent = world.headers("ag1")
        # Dispatch already wrote KIT_ISSUED at sequence_no 1.
        assert shipped["custody_event_count"] == 1
        pinned_version = shipped["version"]

        sealed = append_custody(
            api,
            world,
            kit_id,
            "CONSUMER_SEALED",
            "2026-08-01T02:00:00Z",
            actor_label="Rin Sato",
            seal_id_observed="SEAL-D01",
            version=pinned_version,
        )
        assert sealed["sequence_no"] == 2

        superseded = api.append_custody_event(
            kit_id,
            custody_event_payload(
                "CARRIER_PICKUP",
                "2026-08-01T06:00:00Z",
                pinned_version,
                actor_label="Courier",
            ),
            agent,
        )
        validate_error(superseded, ApiErrorId.STALE_SAMPLE_KIT_VERSION, 412)

        untouched = validate_success(api.get_sample_kit(kit_id, agent))
        assert untouched["status"] == "SHIPPED"
        assert untouched["custody_event_count"] == 2
        assert untouched["version"] != pinned_version

        picked_up = append_custody(
            api,
            world,
            kit_id,
            "CARRIER_PICKUP",
            "2026-08-01T06:00:00Z",
            actor_label="Courier",
            version=untouched["version"],
        )
        assert picked_up["sequence_no"] == 3

        in_transit = validate_success(api.get_sample_kit(kit_id, agent))
        assert in_transit["status"] == "IN_TRANSIT_INBOUND"
        assert in_transit["custody_event_count"] == 3
        assert in_transit["chain_integrity_status"] == "PENDING"

        _events, chain = validate_paginated(api.list_custody_events(kit_id, agent))
        assert chain["total_count"] == 3


class TestOpenKitCountReconciliation:
    def test_the_live_kit_counter_moves_on_every_entry_and_both_exits(self, api):
        """Two requests take it to 2; a cancellation and a completion bring it to 0.

        PRD: "Requesting the kit moves the complaint `TRIAGED → AWAITING_SAMPLE`
        and raises the consumer's `open_kit_count` by one."

        PRD: "A `CareSupervisor` may cancel an unreturned kit, optionally with a
        `reason`, from either `REQUESTED` or `SHIPPED`; the kit becomes
        `CANCELLED`, which is terminal, the parent complaint moves
        `AWAITING_SAMPLE → IN_RESOLUTION`, and the consumer's `open_kit_count`
        falls by one."

        Design: Corner/cross_cutting_complexity_layers/corner_open_kit_count_reconciles_across_the_kit_lifecycle
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        add_contact(
            api,
            world,
            "ct1",
            channel="PHONE",
            raw_message="Two packs with soft matter.",
        )
        for key in ("cpa", "cpb"):
            add_complaint(api, world, key, **SOFT_FOREIGN_MATTER)
            world["complaints"][key] = triage(
                api, world, world["complaints"][key]["id"], reviewer_note="Retrieve."
            )
        first_complaint = world["complaints"]["cpa"]["id"]
        second_complaint = world["complaints"]["cpb"]["id"]
        consumer_id = world["consumer"]["id"]
        agent = world.headers("ag1")
        supervisor = world.headers("sup1")

        def open_kits() -> int:
            return validate_success(api.get_consumer(consumer_id, agent))[
                "open_kit_count"
            ]

        assert open_kits() == 0

        first_kit = add_kit(
            api, world, first_complaint, "ka", kit_code="K-E01",
            seal_id_issued="SEAL-E01",
        )
        assert first_kit["status"] == "REQUESTED"
        assert open_kits() == 1

        # A live count, not a one-kit-per-consumer flag.
        second_kit = add_kit(
            api, world, second_complaint, "kb", kit_code="K-E02",
            seal_id_issued="SEAL-E02",
        )
        assert second_kit["status"] == "REQUESTED"
        assert open_kits() == 2

        cancelled = validate_success(
            api.cancel_sample_kit(
                first_kit["id"], {"reason": "Consumer discarded the item."}, supervisor
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert open_kits() == 1
        abandoned = validate_success(api.get_complaint(first_complaint, agent))
        assert abandoned["handling_status"] == "IN_RESOLUTION"

        kit_id = second_kit["id"]
        ship_kit(api, world, kit_id)
        append_custody(
            api, world, kit_id, "CONSUMER_SEALED", "2026-08-01T02:00:00Z",
            actor_label="Rin Sato", seal_id_observed="SEAL-E02",
        )
        append_custody(
            api, world, kit_id, "CARRIER_PICKUP", "2026-08-01T06:00:00Z",
            actor_label="Courier",
        )
        append_custody(
            api, world, kit_id, "LAB_RECEIVED", "2026-08-05T06:00:00Z",
            actor="ql1", actor_label="Lab desk", seal_id_observed="SEAL-E02",
        )
        receive_kit(api, world, kit_id)
        append_custody(
            api, world, kit_id, "LAB_OPENED", "2026-08-05T07:00:00Z",
            actor="ql1", actor_label="Analyst",
        )
        accepted = lab_accept_kit(api, world, kit_id, lab_note="Usable.")
        assert accepted["status"] == "LAB_ACCEPTED"
        assert accepted["chain_integrity_status"] == "INTACT"
        assert accepted["disposition"] == "USABLE"
        assert_two_decimal_value(accepted["transit_hours"], 96.00)
        resolved = validate_success(api.get_complaint(second_complaint, agent))
        assert resolved["handling_status"] == "IN_RESOLUTION"

        # Two entries, one abandonment and one completion, reconciled exactly.
        assert open_kits() == 0
