"""Access grants and physical key inventory: request validation, issuance,
overdue/return/lost settlement, and the key conservation invariant."""

from test_helpers import (
    FACILITIES_MANAGER,
    SCHEDULER,
    ApiErrorId,
    assert_access_grant,
    assert_room_key_invariant,
    create_grant,
    daily_close,
    get_event,
    get_invoice,
    get_org,
    get_room,
    issue_grant,
    org_headers,
    set_clock,
    setup_confirmed_event,
    setup_org_room,
    create_event,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_grant_create_with_invalid_grant_type_rejected(api):
    """PRD §3.7: "supplying the `event_id` and a `grant_type` of `PHYSICAL_KEY`
    or `CARD_ACCESS`."
    PRD §2.9: "Request shape: required fields, enum membership, and types
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/access_grant_create_invalid_enum_rejected
    """
    scn = setup_org_room(room_overrides={"capacity": 10})
    event = create_event(scn.org, scn.room["id"], expected_attendance=5)
    response = api.create_access_grant(
        {"event_id": event["id"], "grant_type": "MAGIC_KEY"}, FACILITIES_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api.list_access_grants(SCHEDULER))
    assert meta["total_count"] == 0, "no grant persisted"


def test_grant_overdue_then_late_return_forfeits_half_onto_final_invoice(api):
    """PRD §3.7: "Grants left outstanding past their deadline are marked
    `OVERDUE` by the daily-close once the clock passes the `return_deadline`."
    PRD §3.7: "A return on or before the `return_deadline` forfeits nothing; a
    late return forfeits half of the deposit, rounded half-up to whole cents."
    PRD §3.7: "the forfeited portion is recorded as the grant's
    `deposit_forfeit_cents` and lands in the event invoice's
    `deposit_charge_cents` with totals recomputed even on a finalized invoice"
    PRD §3.4: "Its invoice is finalized with the room charged at 100%, the
    fulfilled service charges, and a flat 5000-cent `no_show_fee_cents`, with no
    insurance surcharge applied."

    Design: Corner/state_machines/grant_goes_overdue_and_late_return_forfeits_half
    """
    scn = setup_confirmed_event(
        room_overrides={"capacity": 10, "key_count": 1},
        event_overrides={
            "expected_attendance": 5,
            "start_at": "2026-09-16T14:00:00Z",
            "end_at": "2026-09-16T16:00:00Z",
        },
    )
    grant = create_grant(scn.event["id"], grant_type="PHYSICAL_KEY")
    issued = issue_grant(grant["id"])
    assert issued["status"] == "ISSUED"
    assert issued["deposit_cents"] == 7500

    # Past the return deadline (end 16:00 + 24h = 2026-09-17T16:00).
    set_clock("2026-09-18T00:00:00Z")
    counters = daily_close()
    assert counters["grants_overdue"] == 1
    assert counters["no_shows_marked"] == 1, "never checked in -> NO_SHOW too"

    invoice_mid = get_invoice(scn.invoice["id"])
    assert invoice_mid["status"] == "FINALIZED"
    assert invoice_mid["total_cents"] == 15000, "room 10000 + no-show fee 5000"
    assert invoice_mid["deposit_charge_cents"] == 0

    returned = validate_success(
        api.return_access_grant(grant["id"], FACILITIES_MANAGER), 200
    )
    assert returned["status"] == "RETURNED"
    assert returned["deposit_forfeit_cents"] == 3750, "round_half_up(7500 * 0.5)"

    invoice_end = get_invoice(scn.invoice["id"])
    assert invoice_end["deposit_charge_cents"] == 3750
    assert invoice_end["total_cents"] == 18750, "forfeit recomputes a FINALIZED invoice"

    assert get_org(scn.org["id"])["deposit_held_cents"] == 0
    assert get_room(scn.room["id"])["keys_issued"] == 0


def test_cancel_confirmed_event_blocked_until_issued_grant_returned(api):
    """PRD §3.4: "A `CONFIRMED` event holding any access grant in `ISSUED` or
    `OVERDUE` refuses cancellation with `ERR_ACCESS_GRANTS_OUTSTANDING` until
    those grants are returned or marked lost."
    PRD §3.4: "Notice of at least 72 hours is free"

    Design: Corner/validations/cancel_confirmed_with_issued_grant_blocked_until_returned
    """
    scn = setup_confirmed_event(
        room_overrides={
            "capacity": 30,
            "key_count": 1,
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
        event_overrides={
            "expected_attendance": 5,
            "start_at": "2026-09-16T14:00:00Z",
            "end_at": "2026-09-16T15:00:00Z",
        },
    )
    grant = create_grant(scn.event["id"], grant_type="PHYSICAL_KEY")
    issue_grant(grant["id"])

    blocked = api.cancel_event(scn.event["id"], org_headers(scn.org))
    validate_error(blocked, ApiErrorId.ERR_ACCESS_GRANTS_OUTSTANDING)
    assert get_event(scn.event["id"])["status"] == "CONFIRMED"

    returned = validate_success(
        api.return_access_grant(grant["id"], FACILITIES_MANAGER), 200
    )
    assert returned["status"] == "RETURNED"
    assert returned["deposit_forfeit_cents"] == 0, "on-time return forfeits nothing"

    cancelled = validate_success(api.cancel_event(scn.event["id"], org_headers(scn.org)), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0, "notice far beyond 72h"
    assert get_invoice(scn.invoice["id"])["status"] == "VOIDED"


class TestKeyInventoryConservation:
    def _setup(self, api):
        scn = setup_confirmed_event(
            org_overrides={"name": "Dept Music", "contact_email": "music@univ.edu"},
            room_overrides={
                "name": "MUS-1", "building_code": "MUS", "capacity": 30,
                "key_count": 2,
            },
            event_overrides={
                "title": "Recital",
                "expected_attendance": 20,
                "start_at": "2026-09-16T14:00:00Z",
                "end_at": "2026-09-16T16:00:00Z",
            },
        )
        scn.g1 = create_grant(scn.event["id"], grant_type="PHYSICAL_KEY")
        scn.g2 = create_grant(scn.event["id"], grant_type="PHYSICAL_KEY")
        scn.g3 = create_grant(scn.event["id"], grant_type="PHYSICAL_KEY")
        return scn

    def test_lowest_free_slot_assignment_and_full_inventory_rejection(self, api):
        """PRD §3.7: "for a physical key the grant draws the lowest-numbered
        free `key_slot` between 1 and the room's `key_count` while the room's
        `keys_issued` increments by one."
        PRD §3.7: "A physical-key issuance is refused with
        `ERR_NO_KEYS_AVAILABLE` once `keys_issued` has reached `key_count`."

        Design: Difficulty/compensating_invariant/key_inventory_conservation_across_issue_return_lost
        """
        scn = self._setup(api)
        g1 = issue_grant(scn.g1["id"])
        g2 = issue_grant(scn.g2["id"])
        assert g1["key_slot"] == 1
        assert g2["key_slot"] == 2
        assert g1["deposit_cents"] == 7500
        assert_access_grant(g1)

        full = api.issue_access_grant(scn.g3["id"], FACILITIES_MANAGER)
        validate_error(full, ApiErrorId.ERR_NO_KEYS_AVAILABLE)

        room = get_room(scn.room["id"])
        assert room["keys_issued"] == 2
        assert room["key_count"] == 2
        assert get_org(scn.org["id"])["deposit_held_cents"] == 15000

    def test_return_frees_slot_and_lost_retires_it_conserving_inventory(self, api):
        """PRD §3.2: "the sum of `key_count` and `keys_lost_total` is invariant
        over the room's life, shrinking and growing in lockstep as slots are
        retired."
        PRD §3.7: "Marking a grant lost — again from `ISSUED` or `OVERDUE` —
        forfeits the entire deposit, recorded as `deposit_forfeit_cents`,
        releases the held deposit, and adds the forfeit to the event invoice."
        PRD §3.7: "A lost physical key permanently shrinks the room's inventory:
        `key_count` decrements by one, `keys_issued` decrements by one,
        `keys_lost_total` increments by one, and the retired `key_slot` is never
        reused"

        Design: Difficulty/compensating_invariant/key_inventory_conservation_across_issue_return_lost
        """
        scn = self._setup(api)
        issue_grant(scn.g1["id"])
        issue_grant(scn.g2["id"])

        returned = validate_success(
            api.return_access_grant(scn.g1["id"], FACILITIES_MANAGER), 200
        )
        assert returned["deposit_forfeit_cents"] == 0, "on-time return"

        # Slot 1 was freed by the return and is reused by the pending grant.
        g3 = issue_grant(scn.g3["id"])
        assert g3["key_slot"] == 1

        lost = validate_success(
            api.mark_lost_access_grant(scn.g2["id"], FACILITIES_MANAGER), 200
        )
        assert lost["status"] == "LOST"
        assert lost["deposit_forfeit_cents"] == 7500, "100% forfeit on lost"

        room = get_room(scn.room["id"])
        assert room["key_count"] == 1
        assert room["keys_issued"] == 1, "only G3 outstanding"
        assert room["keys_lost_total"] == 1
        assert_room_key_invariant(room, 2)

        org = get_org(scn.org["id"])
        assert org["deposit_held_cents"] == 7500, "only G3's deposit remains held"

        invoice = get_invoice(scn.invoice["id"])
        assert invoice["deposit_charge_cents"] == 7500
        assert invoice["total_cents"] == 17500, "room 10000 + forfeit 7500"
