"""CarDwell demurrage: free-time boundary, tiered rates, ownership multiplier,
provisional vs final variants, and dwell lifecycle errors (PRD §2.3, §3.5).
"""
from test_helpers import (
    SERVICE,
    ApiErrorId,
    assert_car_dwell,
    create_car_dwell_payload,
    get_car_dwell,
    make_active_agreement,
    make_car_dwell,
    release_car_dwell,
    set_clock,
    validate_error,
    validate_paginated,
)

PLACED = "2026-08-01T00:00:00Z"


class TestProvisionalVsFinal:
    def test_provisional_demurrage_recomputed_against_logical_clock(self, api):
        """PRD §3.5: "While a dwell is `SPOTTED`, every read of it — single or
        list — recomputes its provisional charge against the logical clock;
        `dwell_minutes` at that point is the elapsed time from `placed_at` to
        the logical-clock now, expressed in whole minutes."
        PRD §3.5: "Otherwise the chargeable minutes are divided by the 1,440
        minutes of a day and rounded up, so any partial day bills a full day."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_release
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX1001")
        assert dwell["accrued_demurrage_cents"] == 0
        set_clock("2026-08-05T00:00:00Z")
        # 5760 total minutes - 2880 free minutes = 2880 chargeable -> 2 days.
        read = get_car_dwell(dwell["id"])
        assert read["status"] == "SPOTTED"
        assert read["dwell_minutes"] == 5760
        assert read["accrued_demurrage_cents"] == 15000  # 2 * 7500

    def test_release_computes_final_and_freezes_accrual(self, api):
        """PRD §3.5: "Release — performed by a `RailroadServiceManager` with a
        `released_at` strictly later than `placed_at` (else
        `ERR_INVALID_RELEASE_TIME`), and only from `SPOTTED` (else
        `ERR_DWELL_INVALID_STATE`) — computes this final variant, sets
        `dwell_minutes`, `chargeable_days`, and `final_demurrage_cents`,
        freezes `accrued_demurrage_cents`, and moves the dwell to `RELEASED`,
        after which reads return the frozen values."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_release
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX1001")
        set_clock("2026-08-05T00:00:00Z")
        provisional = get_car_dwell(dwell["id"])
        assert provisional["accrued_demurrage_cents"] == 15000
        # Release at 2026-08-07: 8640 total - 2880 free = 5760 -> 4 days.
        released = release_car_dwell(dwell["id"], "2026-08-07T00:00:00Z")
        assert released["status"] == "RELEASED"
        assert released["dwell_minutes"] == 8640
        assert released["chargeable_days"] == 4
        # 2 * 7500 + 2 * 15000
        assert released["final_demurrage_cents"] == 45000
        # The provisional field froze at its clock-based value, not the final.
        assert released["accrued_demurrage_cents"] == 15000
        reread = get_car_dwell(dwell["id"])
        assert reread["final_demurrage_cents"] == 45000
        assert reread["accrued_demurrage_cents"] == 15000


class TestTieredOwnershipInteraction:
    def test_railroad_car_eight_day_dwell_tiered_charge(self, api):
        """PRD §3.5: "The first two chargeable days bill at
        `demurrage_base_rate_cents` each, and every day beyond the second bills
        at `demurrage_escalated_rate_cents`."

        Design: Difficulty/combinatorial_formula/demurrage_tiered_ownership_interaction
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(
            agreement["id"], car_mark="RBOX2001", car_ownership="RAILROAD"
        )
        # 8 days total = 11520 min; 11520 - 2880 free = 8640 -> 6 days.
        released = release_car_dwell(dwell["id"], "2026-08-09T00:00:00Z")
        assert released["chargeable_days"] == 6
        # 2 * 7500 + 4 * 15000
        assert released["final_demurrage_cents"] == 75000

    def test_private_car_free_time_doubles(self, api):
        """PRD §3.5: "The free allowance is the agreement's `free_time_hours`
        converted to minutes, and it doubles for `PRIVATE` cars."
        PRD §3.5: "The first two chargeable days bill at
        `demurrage_base_rate_cents` each, and every day beyond the second bills
        at `demurrage_escalated_rate_cents`."

        Design: Difficulty/combinatorial_formula/demurrage_tiered_ownership_interaction
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(
            agreement["id"], car_mark="PVTX2002", car_ownership="PRIVATE"
        )
        # Free allowance doubles to 96 h = 5760 min; 11520 - 5760 = 5760 -> 4 days.
        released = release_car_dwell(dwell["id"], "2026-08-09T00:00:00Z")
        assert released["chargeable_days"] == 4
        # 2 * 7500 + 2 * 15000
        assert released["final_demurrage_cents"] == 45000


class TestFreeTimeBoundary:
    def test_release_exactly_at_free_time_bills_zero(self, api):
        """PRD §3.5: "Chargeable minutes are the total minutes minus the free
        minutes; if that difference is zero or negative — a car released
        exactly at the end of its free time included — no days are charged and
        the amount is zero."

        Design: Difficulty/boundary_precision_check/demurrage_free_time_exact_boundary
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX7001")
        # Exactly 48 h after placement: 2880 total - 2880 free = 0.
        released = release_car_dwell(dwell["id"], "2026-08-03T00:00:00Z")
        assert released["chargeable_days"] == 0
        assert released["final_demurrage_cents"] == 0

    def test_release_one_minute_past_free_time_bills_full_day(self, api):
        """PRD §3.5: "Otherwise the chargeable minutes are divided by the 1,440
        minutes of a day and rounded up, so any partial day bills a full day."

        Design: Difficulty/boundary_precision_check/demurrage_free_time_exact_boundary
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX7002")
        # 2881 total minutes: 1 chargeable minute -> ceil -> 1 full day.
        released = release_car_dwell(dwell["id"], "2026-08-03T00:01:00Z")
        assert released["chargeable_days"] == 1
        assert released["final_demurrage_cents"] == 7500


class TestTierBoundary:
    def test_tier_boundary_day_two_vs_day_three(self, api):
        """PRD §3.5: "The first two chargeable days bill at
        `demurrage_base_rate_cents` each, and every day beyond the second bills
        at `demurrage_escalated_rate_cents`."

        Design: Corner/calculations/demurrage_tier_boundary_day2_vs_day3
        """
        agreement = make_active_agreement()
        d2 = make_car_dwell(agreement["id"], car_mark="RBOX9401")
        d3 = make_car_dwell(agreement["id"], car_mark="RBOX9402")
        # 4 days total: 5760 - 2880 = 2880 chargeable -> exactly 2 days.
        two_day = release_car_dwell(d2["id"], "2026-08-05T00:00:00Z")
        assert two_day["chargeable_days"] == 2
        assert two_day["final_demurrage_cents"] == 15000  # 2 * 7500
        # 5 days total: 7200 - 2880 = 4320 chargeable -> 3 days; the third
        # day bills at the escalated rate.
        three_day = release_car_dwell(d3["id"], "2026-08-06T00:00:00Z")
        assert three_day["chargeable_days"] == 3
        assert three_day["final_demurrage_cents"] == 30000  # 2*7500 + 1*15000


class TestDwellValidationAndLifecycle:
    def test_invalid_car_ownership_rejected(self, api):
        """PRD §3.5: "a `car_ownership` of `RAILROAD` or `PRIVATE`"
        PRD §2.10: "fifth, request body shape and field-level validity —
        required fields present, enum members valid, dates well-ordered,
        percentages within range (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/car_dwell_invalid_ownership_enum_rejected
        """
        agreement = make_active_agreement()
        res = api.create_car_dwell(
            create_car_dwell_payload(
                agreement["id"], car_mark="RBOX9001", car_ownership="ELECTRIC"
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_duplicate_spotted_car_rejected(self, api):
        """PRD §3.5: "At most one `SPOTTED` dwell may exist for a given
        agreement and car mark; a duplicate is rejected with
        `ERR_CAR_ALREADY_SPOTTED`."

        Design: Corner/validations/duplicate_spotted_car_rejected
        """
        agreement = make_active_agreement()
        make_car_dwell(agreement["id"], car_mark="RBOX9501")
        res = api.create_car_dwell(
            create_car_dwell_payload(
                agreement["id"],
                car_mark="RBOX9501",
                placed_at="2026-08-02T00:00:00Z",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_CAR_ALREADY_SPOTTED, 409)

    def test_release_before_placement_rejected(self, api):
        """PRD §3.5: "Release — performed by a `RailroadServiceManager` with a
        `released_at` strictly later than `placed_at` (else
        `ERR_INVALID_RELEASE_TIME`), and only from `SPOTTED` (else
        `ERR_DWELL_INVALID_STATE`)"

        Design: Corner/validations/release_before_placement_returns_invalid_release_time
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX9601")
        # released_at == placed_at is not strictly later.
        res = api.release_car_dwell(dwell["id"], {"released_at": PLACED}, SERVICE)
        validate_error(res, ApiErrorId.ERR_INVALID_RELEASE_TIME, 400)
        assert get_car_dwell(dwell["id"])["status"] == "SPOTTED"

    def test_release_already_released_dwell_rejected(self, api):
        """PRD §3.5: "Release — performed by a `RailroadServiceManager` with a
        `released_at` strictly later than `placed_at` (else
        `ERR_INVALID_RELEASE_TIME`), and only from `SPOTTED` (else
        `ERR_DWELL_INVALID_STATE`) — computes this final variant, sets
        `dwell_minutes`, `chargeable_days`, and `final_demurrage_cents`,
        freezes `accrued_demurrage_cents`, and moves the dwell to `RELEASED`,
        after which reads return the frozen values."

        Design: Corner/state_machines/release_already_released_dwell_returns_invalid_state
        """
        agreement = make_active_agreement()
        dwell = make_car_dwell(agreement["id"], car_mark="RBOX9201")
        first = release_car_dwell(dwell["id"], "2026-08-03T00:01:00Z")
        assert first["final_demurrage_cents"] == 7500
        res = api.release_car_dwell(
            dwell["id"], {"released_at": "2026-08-09T00:00:00Z"}, SERVICE
        )
        validate_error(res, ApiErrorId.ERR_DWELL_INVALID_STATE, 409)
        after = get_car_dwell(dwell["id"])
        assert after["status"] == "RELEASED"
        assert after["final_demurrage_cents"] == 7500, (
            "the rejected second release must not move the frozen final charge"
        )


class TestDwellListing:
    def test_car_dwell_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/car_dwell_list_pagination_interaction
        """
        agreement = make_active_agreement()
        make_car_dwell(agreement["id"], car_mark="RBOX9101")
        make_car_dwell(agreement["id"], car_mark="RBOX9102")
        page1, meta1 = validate_paginated(
            api.list_car_dwells(
                SERVICE,
                params={"agreement_id": agreement["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_car_dwells(
                SERVICE,
                params={"agreement_id": agreement["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        marks = {page1[0]["car_mark"], page2[0]["car_mark"]}
        assert marks == {"RBOX9101", "RBOX9102"}
        assert_car_dwell(page1[0])
        assert_car_dwell(page2[0])
