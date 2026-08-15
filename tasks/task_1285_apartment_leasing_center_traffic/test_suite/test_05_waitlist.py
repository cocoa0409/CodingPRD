"""Waitlist: join gate, queue-head promotion and its capacity gate, decline
requeue, offer expiry sweep, conversion via application, and immediate reads."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    create_agent,
    create_application,
    create_floorplan,
    create_property,
    create_waitlist_entry,
    decline_waitlist_entry,
    get_waitlist_entry,
    make_leasing_agent_headers,
    promote_waitlist_entry,
    set_clock,
    setup_offered_waitlist,
    setup_occupied_floorplan,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestWaitlistJoin:
    def test_waitlist_join_when_units_available_rejected(self, api):
        """PRD §3.4: "Joining the waitlist takes `floorplan_id`, `contact_name`, and
        `contact_email`, and is permitted only while the floorplan's
        `available_units` is zero; joining while at least one unit is available is
        rejected with `ERR_FLOORPLAN_AVAILABLE`."

        Design: Corner/validations/waitlist_join_when_units_available_rejected
        """
        prop = create_property(name="Waitlist Willows", code="WW1")
        agent = create_agent(prop["id"], full_name="WwA", email="wwa@x.com")
        f_avail = create_floorplan(prop["id"], name="Open 1BR", total_units=1)
        f_zero = create_floorplan(prop["id"], name="Future 1BR", total_units=0)

        resp = api.create_waitlist_entry(
            {"floorplan_id": f_avail["id"], "contact_name": "Early",
             "contact_email": "early@x.com"},
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_FLOORPLAN_AVAILABLE)

        entry = create_waitlist_entry(f_zero["id"], agent["id"],
                                      contact_name="Future", contact_email="fut@x.com")
        assert entry["status"] == "WAITING"
        assert entry["position"] == 1


class TestPromotion:
    def test_promote_without_units_returns_no_units_to_offer(self, api):
        """PRD §3.4: "The entry being promoted must be `WAITING`
        (`ERR_WAITLIST_INVALID_STATE` otherwise), and promotion requires effective
        availability — the floorplan's `available_units` minus the number of its
        entries currently `OFFERED` — of at least one, otherwise
        `ERR_NO_UNITS_TO_OFFER`."

        Design: Corner/validations/promote_without_units_returns_no_units_to_offer
        """
        occ = setup_occupied_floorplan()  # 1 unit held by an EXECUTED lease
        site = occ["site"]
        entry = create_waitlist_entry(site["floorplan"]["id"], site["agent"]["id"],
                                      contact_name="E1", contact_email="ne1@x.com")
        assert entry["position"] == 1  # sole entry is the queue head

        resp = api.promote_waitlist_entry(
            entry["id"], make_leasing_agent_headers(site["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_UNITS_TO_OFFER)
        assert get_waitlist_entry(entry["id"])["status"] == "WAITING"

    def test_promote_returns_fully_mutated_entity_immediately(self, api):
        """PRD §3.4: "A promoted entry becomes `OFFERED`, and its `offer_expires_at`
        is set to the current logical time plus a seventy-two-hour offer window."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/promote_returns_fully_mutated_entity_immediately
        """
        arrangement = setup_offered_waitlist(num_entries=1, execute_lease=False)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry = arrangement["entries"][0]
        # The lease cancellation auto-promoted the sole entry; decline it so a
        # manual promotion can be observed through the response body itself.
        decline_waitlist_entry(entry["id"], agent_id)
        assert get_waitlist_entry(entry["id"])["status"] == "WAITING"

        resp = api.promote_waitlist_entry(entry["id"],
                                          make_leasing_agent_headers(agent_id))
        promoted = validate_success(resp)
        assert promoted["status"] == "OFFERED"
        # Default logical clock 2026-08-01T00:00:00Z plus the 72-hour offer window.
        assert_same_instant(promoted["offer_expires_at"], "2026-08-04T00:00:00Z",
                            label="offer_expires_at")
        reread = get_waitlist_entry(entry["id"])
        assert reread["status"] == promoted["status"]
        assert_same_instant(reread["offer_expires_at"], "2026-08-04T00:00:00Z",
                            label="offer_expires_at reread")


class TestDeclineAndTerminalStates:
    def test_decline_cancelled_entry_returns_invalid_state(self, api):
        """PRD §3.4: "Or the entry is cancelled: cancellation is permitted from
        `WAITING` or `OFFERED` (anything else is `ERR_WAITLIST_INVALID_STATE`),
        lands the entry in the terminal `CANCELLED` state, and clears
        `offer_expires_at` when cancelling an `OFFERED` entry."
        PRD §3.4: "Positions are never reused: entries that reach `CONVERTED` or
        `CANCELLED` keep their historical positions."
        PRD §2.10: "Fourth, state checks: the per-entity invalid-state family
        (`ERR_INQUIRY_INVALID_STATE`, `ERR_TOUR_INVALID_STATE`,
        `ERR_WAITLIST_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`,
        `ERR_LEASE_INVALID_STATE`, `ERR_MOVEIN_INVALID_STATE`,
        `ERR_PRICING_OFFER_INVALID_STATE`), the pipeline-gating errors
        (`ERR_INQUIRY_NOT_ACTIVE`, `ERR_APPLICATION_NOT_LEASABLE`,
        `ERR_LEASE_NOT_EXECUTED`), a repeat first response (`ERR_ALREADY_RESPONDED`),
        and the stale-version rejection (`ERR_STALE_VERSION`)."

        Design: Corner/state_machines/decline_cancelled_entry_returns_invalid_state
        """
        site = setup_site(floorplan_overrides={"name": "Future 1BR",
                                               "total_units": 0})
        agent_id = site["agent"]["id"]
        entry = create_waitlist_entry(site["floorplan"]["id"], agent_id,
                                      contact_name="Lock", contact_email="lock@x.com")
        cancelled = validate_success(api.cancel_waitlist_entry(
            entry["id"], make_leasing_agent_headers(agent_id)))
        assert cancelled["status"] == "CANCELLED"

        resp = api.decline_waitlist_entry(entry["id"],
                                          make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_WAITLIST_INVALID_STATE)
        after = get_waitlist_entry(entry["id"])
        assert after["status"] == "CANCELLED"
        assert after["position"] == 1, "a terminal entry keeps its historical position"


class TestOfferExpirySweep:
    def test_waitlist_offer_expiry_requeues_entry(self, api):
        """PRD §3.4: "The offer lapses: once the logical clock reaches
        `offer_expires_at`, the entry is lazily swept back to `WAITING` on its next
        access, with the same requeue-to-back and cleared expiry."
        PRD §3.4: "A new entry starts `WAITING`, and its `position` is computed as
        one more than the highest `position` among the floorplan's other entries in
        `WAITING` or `OFFERED` — the entry being created is excluded from that
        maximum — or 1 when no such entries exist."

        Design: Corner/calculations/waitlist_offer_expiry_requeues_entry
        """
        arrangement = setup_offered_waitlist(num_entries=1)
        entry = arrangement["entries"][0]
        offered = get_waitlist_entry(entry["id"])
        assert offered["status"] == "OFFERED"
        assert_same_instant(offered["offer_expires_at"], "2026-08-04T00:00:00Z",
                            label="offer_expires_at")

        # At exactly offer_expires_at the next read sweeps the entry back.
        set_clock("2026-08-04T00:00:00Z")
        swept = get_waitlist_entry(entry["id"])
        assert swept["status"] == "WAITING"
        assert swept["offer_expires_at"] is None
        assert swept["position"] == 1, \
            "the requeue excludes the entry itself; the sole entry returns to 1"


class TestWaitlistConversion:
    def test_waitlist_converted_entry_converts_on_application_create(self, api):
        """PRD §3.4: "The prospect accepts implicitly by applying: when an
        application is created naming the entry, the entry must be `OFFERED` and
        unexpired (`ERR_WAITLIST_INVALID_STATE` otherwise), and it becomes
        `CONVERTED` with its `linked_application_id` set to the new application's
        id."
        PRD §3.5: "A new application starts in `SCREENING`."

        Design: Corner/endpoints/waitlist_converted_entry_converts_on_application_create
        """
        arrangement = setup_offered_waitlist(num_entries=1)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry = arrangement["entries"][0]

        application = create_application(site["floorplan"]["id"], agent_id,
                                         waitlist_entry_id=entry["id"],
                                         applicant_name="E One",
                                         applicant_email="ce1@x.com")
        assert application["status"] == "SCREENING"
        converted = get_waitlist_entry(entry["id"])
        assert converted["status"] == "CONVERTED"
        assert converted["linked_application_id"] == application["id"]

        # CONVERTED is terminal: a second application against the same entry fails.
        resp = api.create_application(
            {"waitlist_entry_id": entry["id"], "floorplan_id": site["floorplan"]["id"],
             "applicant_name": "E Again", "applicant_email": "ce1b@x.com",
             "annual_income_cents": 9000000, "credit_score": 750},
            make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_WAITLIST_INVALID_STATE)


class TestDeclineRequeueCycle:
    def test_waitlist_offer_decline_requeues_to_back_of_queue(self, api):
        """PRD §3.4: "The prospect declines: the entry returns from `OFFERED` to
        `WAITING`, its `offer_expires_at` is cleared to null, and its `position` is
        recomputed to the back of the queue — one more than the highest position
        among the floorplan's other `WAITING` or `OFFERED` entries."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_requeues_to_back
        """
        arrangement = setup_offered_waitlist(num_entries=2)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry1, entry2 = arrangement["entries"]
        # The cancellation auto-promoted the head (position 1).
        assert get_waitlist_entry(entry1["id"])["status"] == "OFFERED"
        assert get_waitlist_entry(entry2["id"])["position"] == 2

        declined = decline_waitlist_entry(entry1["id"], agent_id)
        assert declined["status"] == "WAITING"
        assert declined["offer_expires_at"] is None
        assert declined["position"] == 3, \
            "requeue lands behind the previously waiting entry at position 2"

    def test_waitlist_decline_then_promote_new_queue_head(self, api):
        """PRD §3.4: "The queue head is the `WAITING` entry for the floorplan with
        the smallest `position`, ties broken by the earliest `created_at`; when no
        `WAITING` entry exists there is no head, auto-promotion is a no-op, and a
        targeted promotion of a non-head entry is rejected with
        `ERR_NOT_QUEUE_HEAD`."
        PRD §3.4: "A promoted entry becomes `OFFERED`, and its `offer_expires_at` is
        set to the current logical time plus a seventy-two-hour offer window."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_requeues_to_back
        """
        arrangement = setup_offered_waitlist(num_entries=2)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry1, entry2 = arrangement["entries"]
        decline_waitlist_entry(entry1["id"], agent_id)  # entry1 requeues to position 3

        # Entry2 (position 2) is now the head and promotes cleanly at the default
        # clock: offer_expires_at = 2026-08-01T00:00:00Z + 72h.
        promoted = promote_waitlist_entry(entry2["id"], agent_id)
        assert promoted["status"] == "OFFERED"
        assert_same_instant(promoted["offer_expires_at"], "2026-08-04T00:00:00Z",
                            label="offer_expires_at")
        # The declined entry now sits strictly behind the promoted one.
        assert get_waitlist_entry(entry1["id"])["position"] > \
            get_waitlist_entry(entry2["id"])["position"]


class TestQueueCardinalityInvariant:
    def test_waitlist_promote_decline_conserves_queue_cardinality(self, api):
        """PRD §3.4: "The prospect declines: the entry returns from `OFFERED` to
        `WAITING`, its `offer_expires_at` is cleared to null, and its `position` is
        recomputed to the back of the queue — one more than the highest position
        among the floorplan's other `WAITING` or `OFFERED` entries."

        Design: Difficulty/compensating_invariant/waitlist_promote_decline_conserves_queue_cardinality
        """
        arrangement = setup_offered_waitlist(num_entries=3)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry1 = arrangement["entries"][0]
        # Head was auto-promoted by the lease cancellation; declining it is the
        # compensating transition of the promote/decline pair.
        decline_waitlist_entry(entry1["id"], agent_id)

        data, _ = validate_paginated(api.list_waitlist_entries(
            PM, params={"floorplan_id": site["floorplan"]["id"]}))
        live = [e for e in data if e["status"] in ("WAITING", "OFFERED")]
        assert len(live) == 3, "promote + decline leaves queue cardinality unchanged"
        declined = get_waitlist_entry(entry1["id"])
        assert declined["status"] == "WAITING"
        assert declined["position"] == 4, \
            "the declined entry requeues strictly behind positions 2 and 3"

    def test_waitlist_non_head_promotion_rejected(self, api):
        """PRD §3.4: "The queue head is the `WAITING` entry for the floorplan with
        the smallest `position`, ties broken by the earliest `created_at`; when no
        `WAITING` entry exists there is no head, auto-promotion is a no-op, and a
        targeted promotion of a non-head entry is rejected with
        `ERR_NOT_QUEUE_HEAD`."

        Design: Difficulty/compensating_invariant/waitlist_promote_decline_conserves_queue_cardinality
        """
        arrangement = setup_offered_waitlist(num_entries=3)
        site = arrangement["site"]
        agent_id = site["agent"]["id"]
        entry1, entry2, entry3 = arrangement["entries"]
        decline_waitlist_entry(entry1["id"], agent_id)  # head: entry2 (position 2)

        resp = api.promote_waitlist_entry(entry3["id"],
                                          make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_NOT_QUEUE_HEAD)
        assert get_waitlist_entry(entry3["id"])["status"] == "WAITING"

        # The true head still promotes after the failed non-head attempt.
        promoted = promote_waitlist_entry(entry2["id"], agent_id)
        assert promoted["status"] == "OFFERED"
