"""The seat ledger under assignment, re-seating and revocation, plus the
closed-interval-with-cooldown rule that governs sibling entitlement windows.
"""

from test_helpers import (
    ApiErrorId,
    EntitlementStatus,
    SeatStatus,
    assert_entitlement,
    assert_seat_assignment,
    assert_seat_counts,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSeatConservation:
    """Assignment, re-seating and revocation all keep the ledger balanced."""

    def test_each_assignment_moves_one_seat_from_available_to_assigned(self, api):
        """Two assignments against three seats read 1/2 and then 2/1.

        PRD 3.5: "Seat conservation is an invariant that must hold after every
        seat mutation without exception: `seats_total` always equals
        `seats_assigned` plus `seats_available`", where "`seats_assigned` is the
        count of seat rows on that entitlement whose status is `ACTIVE`".

        Design: Difficulty/compensating_invariant/seat_conservation_across_assign_revoke_and_reseat
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=3
        )
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="second",
            full_name="Vic Wrench",
            identity_document_ref="DL-88456",
        )

        fixtures.add_seat(api, ctx, key="main")
        assert_entitlement(ctx["entitlement"])
        assert_seat_counts(ctx["entitlement"], 1, 2)

        fixtures.add_seat(api, ctx, key="second")
        assert_seat_counts(ctx["entitlement"], 2, 1)

    def test_reseating_the_same_technician_supersedes_and_is_seat_neutral(self, api):
        """The prior row goes SUPERSEDED and the counters do not move.

        PRD 3.5: "Because one active row simply replaces another, the
        entitlement's `seats_assigned` is unchanged by a re-seat", and seat
        conservation still holds — "across a re-seat, both are unchanged".

        Design: Difficulty/compensating_invariant/seat_conservation_across_assign_revoke_and_reseat
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=3
        )
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="second",
            full_name="Vic Wrench",
            identity_document_ref="DL-88456",
        )
        fixtures.add_seat(api, ctx, key="main")
        fixtures.add_seat(api, ctx, key="second")
        first_seat_id = ctx["seats"]["second"]["id"]

        fixtures.add_seat(api, ctx, key="second")
        replacement = ctx["seats"]["second"]
        superseded = validate_success(
            api.get_seat_assignment(first_seat_id, ctx["manager_headers"])
        )

        assert_seat_assignment(replacement)
        assert replacement["id"] != first_seat_id
        assert replacement["status"] == SeatStatus.ACTIVE
        assert superseded["status"] == SeatStatus.SUPERSEDED
        assert_seat_counts(ctx["entitlement"], 2, 1)

    def test_revocation_exactly_compensates_the_forward_assignment(self, api):
        """The reason is stored verbatim and the counters return to 1/2.

        PRD 3.5: "The supplied `reason` is written verbatim to
        `revocation_reason`, the entitlement's `seats_assigned` is decremented by
        1 with `seats_available` recomputed", and "Across a forward assignment
        followed by its compensating revocation, both derived numbers return to
        exactly the values they had before the assignment".

        Design: Difficulty/compensating_invariant/seat_conservation_across_assign_revoke_and_reseat
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=3
        )
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="second",
            full_name="Vic Wrench",
            identity_document_ref="DL-88456",
        )
        fixtures.add_seat(api, ctx, key="main")
        fixtures.add_seat(api, ctx, key="second")

        revoked = validate_success(
            api.revoke_seat_assignment(
                ctx["seats"]["main"]["id"],
                factories.reason_payload("moved to another branch"),
                ctx["manager_headers"],
            )
        )
        entitlement = fixtures.refresh_entitlement(api, ctx)

        assert_seat_assignment(revoked)
        assert revoked["status"] == SeatStatus.REVOKED
        assert revoked["revocation_reason"] == "moved to another branch"
        assert_seat_counts(entitlement, 1, 2)

        rows, meta = validate_paginated(
            api.list_seat_assignments(
                ctx["manager_headers"],
                {"entitlement_id": entitlement["id"], "status": SeatStatus.ACTIVE},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [ctx["seats"]["second"]["id"]]


class TestEntitlementWindowCooldown:
    """Sibling windows are closed intervals separated by a 24-hour cooldown."""

    def test_a_gap_of_exactly_24_hours_conflicts(self, api):
        """A window opening exactly one day after the incumbent closes is refused.

        PRD 2.9: "windows that overlap conflict, windows that merely touch at an
        instant conflict, a gap of exactly 24 hours conflicts, and only a gap
        strictly wider than 24 hours is accepted." PRD 3.3 names the outcome:
        "the purchase is refused with `ERR_ENTITLEMENT_WINDOW_CONFLICT` (HTTP
        409) if any sibling entitlement on the same shop and the same license, in
        status `PENDING` or `ACTIVE`, satisfies both of these".

        Design: Difficulty/resource_temporal_overlap/entitlement_window_closed_interval_plus_24h_cooldown_rejects_exact_gap
        """
        ctx = fixtures.build_entitled_shop(api, funding_cents=300000)
        assert ctx["shop"]["data_credit_balance_cents"] == 215001

        response = api.create_entitlement(
            factories.entitlement_payload(
                ctx["shop"]["id"],
                ctx["license"]["id"],
                window_start="2026-09-02T00:00:00Z",
                window_end="2026-10-01T00:00:00Z",
            ),
            ctx["manager_headers"],
        )

        validate_error(response, ApiErrorId.ENTITLEMENT_WINDOW_CONFLICT, 409)
        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 215001

    def test_a_gap_one_second_wider_than_24_hours_is_accepted(self, api):
        """One second past the cooldown the second purchase goes through.

        PRD 2.9: "only a gap strictly wider than 24 hours is accepted", where the
        cooldown is measured against the incumbent window, and PRD 3.3 charges the
        accepted purchase in the usual way, stamping `charged_cents` and debiting
        the balance.

        Design: Difficulty/resource_temporal_overlap/entitlement_window_closed_interval_plus_24h_cooldown_rejects_exact_gap
        """
        ctx = fixtures.build_entitled_shop(api, funding_cents=300000)

        second = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"],
                    ctx["license"]["id"],
                    window_start="2026-09-02T00:00:01Z",
                    window_end="2026-10-01T00:00:00Z",
                ),
                ctx["manager_headers"],
            ),
            201,
        )
        shop = fixtures.refresh_shop(api, ctx)

        assert_entitlement(second)
        assert second["status"] == EntitlementStatus.PENDING
        assert second["charged_cents"] == 84999
        assert shop["data_credit_balance_cents"] == 130002

        _rows, meta = validate_paginated(
            api.list_entitlements(
                ctx["manager_headers"],
                {"shop_id": ctx["shop"]["id"], "license_id": ctx["license"]["id"]},
            )
        )
        assert meta["total_count"] == 2
