"""Floor placement, category zones, space conservation, and neighbor requests."""
from test_helpers import (
    CLOCK_JURY_REVIEW,
    STANDARD_SCORES,
    TEST_USERS,
    ApiErrorId,
    accept_offer,
    advance_phase,
    assert_neighbor_request,
    assert_placement,
    create_application,
    create_neighbor_request,
    create_placement,
    decide,
    get_application,
    get_space_unit,
    list_space_units,
    make_exhibitor_headers,
    post_scores,
    register_exhibitor,
    release_placement,
    set_clock,
    setup_accepted_with_placements,
    setup_contracted_application,
    setup_decided_application,
    setup_open_convention,
    setup_submitted_application,
    submit_and_verify_permit,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_application,
)

ARTIST_TABLE_SPEC = {
    "space_code": "T-01",
    "block": "T",
    "unit_number": 1,
    "hall": "ARTIST_ALLEY_HALL",
    "kind": "ARTIST_TABLE",
    "base_price_cents": 30000,
}

ARTIST_TABLE_SPEC_2 = {
    "space_code": "T-02",
    "block": "T",
    "unit_number": 2,
    "hall": "ARTIST_ALLEY_HALL",
    "kind": "ARTIST_TABLE",
    "base_price_cents": 30000,
}

TWO_BOOTH_SPACES = [
    {
        "space_code": "A-101",
        "block": "A",
        "unit_number": 101,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    },
    {
        "space_code": "A-102",
        "block": "A",
        "unit_number": 102,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    },
]

ARTIST_QUOTA_ONLY = [
    {"category": "ARTIST_ALLEY", "max_accepted": 2, "max_waitlisted": 2}
]


class TestPlacementConfirm:
    def test_placement_confirm_executes_full_side_effect_set(self, api, director_headers):
        """PRD §3.6: "Confirmation moves the placement `TENTATIVE` →
        `CONFIRMED`, the unit `RESERVED` → `ASSIGNED`, and the application
        `CONTRACTED` → `PLACED` — an already `PLACED` application stays
        `PLACED`."
        PRD §3.7: "the application's `included_badges` is the sum of those
        allotments over its `ASSIGNED` units, recomputed at every placement
        confirmation. `RESERVED` units contribute nothing."

        Design: Corner/state_machines/placement_confirm_executes_full_side_effect_set
        """
        bundle = setup_contracted_application()  # CONTRACTED, TENTATIVE on A-101
        placement = validate_success(
            api.confirm_placement(
                bundle["placement"]["id"], TEST_USERS["director_headers"]
            )
        )
        assert_placement(placement)
        assert placement["status"] == "CONFIRMED"

        space = get_space_unit(bundle["spaces"]["A-101"]["id"])
        assert space["status"] == "ASSIGNED"
        assert space["current_application_id"] == bundle["application"]["id"]

        app = get_application(bundle["application"]["id"])
        assert app["status"] == "PLACED"
        assert app["included_badges"] == 4  # BOOTH_10X10 allotment

    def test_badge_allocation_sums_across_kinds(self, api):
        """PRD §3.7: "Each `ASSIGNED` unit contributes a per-kind allotment —
        four badges for a `BOOTH_10X10`, six for a `BOOTH_10X20`, six for a
        `CORNER_BOOTH`, eight for an `ENDCAP`, twelve for a `FEATURED_ISLAND`,
        two for an `ARTIST_TABLE`, and two for a `NONPROFIT_TABLE` — and the
        application's `included_badges` is the sum of those allotments over its
        `ASSIGNED` units, recomputed at every placement confirmation."
        PRD §3.7: "`RESERVED` units contribute nothing."

        Design: Corner/calculations/badge_allocation_sums_across_kinds
        """
        bundle = setup_contracted_application(
            space_specs=[
                TWO_BOOTH_SPACES[0],
                {
                    "space_code": "A-102",
                    "block": "A",
                    "unit_number": 102,
                    "hall": "MAIN",
                    "kind": "BOOTH_10X20",
                    "base_price_cents": 180000,
                },
            ],
            kinds=("BOOTH_10X10", "BOOTH_10X20"),
            space_count=2,
            placement_space_codes=["A-101", "A-102"],
            deposit_cents=59500,  # (100000+180000) * 0.85 * 0.25
            dock_doors=[{"door_code": "D1"}],
        )
        app_id = bundle["application"]["id"]
        # Invoice check: subtotal 280000 -> 5% multi-space + 10% early-bird,
        # single rounding: 280000 * 0.85 = 238000; deposit 59500.
        assert bundle["application"]["final_invoice_cents"] == 238000

        # RESERVED units contribute nothing yet — confirm placements one by one.
        first = bundle["placements"][0]
        validate_success(
            api.confirm_placement(first["id"], TEST_USERS["director_headers"])
        )
        assert get_application(app_id)["included_badges"] == 4

        second = bundle["placements"][1]
        validate_success(
            api.confirm_placement(second["id"], TEST_USERS["director_headers"])
        )
        app = get_application(app_id)
        assert app["included_badges"] == 10  # 4 + 6
        assert app["status"] == "PLACED"


class TestPlacementGuards:
    def test_placement_category_zone_violation(self, api, director_headers):
        """PRD §3.6: "The offered unit must be `AVAILABLE`
        (`ERR_SPACE_NOT_AVAILABLE`), its `kind` must appear among the
        application's `requested_space_kinds` (`ERR_SPACE_KIND_MISMATCH`), and
        the combination of the application's `category`, the unit's `kind`, and
        the unit's `hall` must satisfy the convention's category-zone map —
        each category is confined to defined zones of the floor, and an
        out-of-zone offer is rejected with `ERR_CATEGORY_ZONE_VIOLATION`."

        Design: Corner/validations/placement_category_zone_violation
        """
        # The application requests BOOTH_10X10 so the kind gate passes; only
        # the category-zone gate can fail: an ARTIST_ALLEY application has no
        # zone covering a MAIN-hall booth (the category is confined to the
        # artist zone), so the out-of-zone offer is rejected.
        bundle = setup_decided_application(
            decision="ACCEPTED",
            category="ARTIST_ALLEY",
            kinds=("BOOTH_10X10",),
            estimated_daily_sales_cents=10000,
            space_specs=[
                {
                    "space_code": "A-101",
                    "block": "A",
                    "unit_number": 101,
                    "hall": "MAIN",
                    "kind": "BOOTH_10X10",
                    "base_price_cents": 100000,
                },
                ARTIST_TABLE_SPEC,
            ],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        advance_phase(bundle["convention"]["id"])  # JURY_REVIEW -> PLACEMENT
        resp = api.create_placement(
            {
                "application_id": bundle["application"]["id"],
                "space_unit_id": bundle["spaces"]["A-101"]["id"],
            },
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_ZONE_VIOLATION)
        assert get_space_unit(bundle["spaces"]["A-101"]["id"])["status"] == "AVAILABLE"

    def test_placement_kind_not_requested_rejected(self, api, director_headers):
        """PRD §3.6: "The offered unit must be `AVAILABLE`
        (`ERR_SPACE_NOT_AVAILABLE`), its `kind` must appear among the
        application's `requested_space_kinds` (`ERR_SPACE_KIND_MISMATCH`), and
        the combination of the application's `category`, the unit's `kind`, and
        the unit's `hall` must satisfy the convention's category-zone map —
        each category is confined to defined zones of the floor, and an
        out-of-zone offer is rejected with `ERR_CATEGORY_ZONE_VIOLATION`."

        Design: Corner/validations/placement_kind_not_requested_rejected
        """
        bundle = setup_decided_application(
            decision="ACCEPTED",
            space_specs=[
                TWO_BOOTH_SPACES[0],
                {
                    "space_code": "A-102",
                    "block": "A",
                    "unit_number": 102,
                    "hall": "MAIN",
                    "kind": "BOOTH_10X20",
                    "base_price_cents": 180000,
                },
            ],
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        advance_phase(bundle["convention"]["id"])  # JURY_REVIEW -> PLACEMENT
        # Same hall/zone, but the application requested only BOOTH_10X10.
        resp = api.create_placement(
            {
                "application_id": bundle["application"]["id"],
                "space_unit_id": bundle["spaces"]["A-102"]["id"],
            },
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SPACE_KIND_MISMATCH)
        assert get_space_unit(bundle["spaces"]["A-102"]["id"])["status"] == "AVAILABLE"

    def test_placement_on_reserved_space_rejected(self, api, director_headers):
        """PRD §3.6: "The offered unit must be `AVAILABLE`
        (`ERR_SPACE_NOT_AVAILABLE`), its `kind` must appear among the
        application's `requested_space_kinds` (`ERR_SPACE_KIND_MISMATCH`), and
        the combination of the application's `category`, the unit's `kind`, and
        the unit's `hall` must satisfy the convention's category-zone map —
        each category is confined to defined zones of the floor, and an
        out-of-zone offer is rejected with `ERR_CATEGORY_ZONE_VIOLATION`."

        Design: Corner/validations/placement_on_reserved_space_rejected
        """
        bundle = setup_accepted_with_placements(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        space_id = bundle["spaces"]["A-101"]["id"]
        assert get_space_unit(space_id)["status"] == "RESERVED"
        resp = api.create_placement(
            {"application_id": app_id, "space_unit_id": space_id},
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SPACE_NOT_AVAILABLE)
        placements, _meta = validate_paginated(
            api.list_placements(director_headers, params={"application_id": app_id})
        )
        assert len([p for p in placements if p["status"] == "TENTATIVE"]) == 1


class TestSpaceConservation:
    def test_space_status_conservation_across_offer_and_release(self, api):
        """PRD §3.6: "A successful offer creates the placement `TENTATIVE` and
        moves the unit `AVAILABLE` → `RESERVED` with its
        `current_application_id` set to the application."
        PRD §3.6: "A `TENTATIVE` placement may instead be released, returning
        the placement to `RELEASED` and the unit to `AVAILABLE`"

        Design: Difficulty/compensating_invariant/space_unit_status_conservation_under_offer_release
        """
        bundle = setup_decided_application(
            decision="ACCEPTED", space_specs=TWO_BOOTH_SPACES
        )
        conv_id = bundle["convention"]["id"]
        advance_phase(conv_id)  # JURY_REVIEW -> PLACEMENT

        def status_counts():
            counts = {"AVAILABLE": 0, "RESERVED": 0, "ASSIGNED": 0}
            for unit in list_space_units(params={"convention_id": conv_id}):
                counts[unit["status"]] += 1
            return counts

        before = status_counts()
        assert before == {"AVAILABLE": 2, "RESERVED": 0, "ASSIGNED": 0}

        placement = create_placement(
            bundle["application"]["id"], bundle["spaces"]["A-101"]["id"]
        )
        between = status_counts()
        assert between == {"AVAILABLE": 1, "RESERVED": 1, "ASSIGNED": 0}

        release_placement(placement["id"])
        after = status_counts()
        # The compensating pair nets to zero drift: the sum across statuses
        # always equals the number of created units.
        assert after == before

    def test_released_space_returns_available_with_holder_cleared(self, api):
        """PRD §3.6: "A `TENTATIVE` placement may instead be released, returning
        the placement to `RELEASED` and the unit to `AVAILABLE`"
        PRD §3.1: "Each unit also carries a system-maintained
        `current_application_id` pointing at the application currently holding
        it — null while the unit is `AVAILABLE`."

        Design: Difficulty/compensating_invariant/space_unit_status_conservation_under_offer_release
        """
        bundle = setup_decided_application(
            decision="ACCEPTED", space_specs=TWO_BOOTH_SPACES
        )
        conv_id = bundle["convention"]["id"]
        advance_phase(conv_id)
        placement = create_placement(
            bundle["application"]["id"], bundle["spaces"]["A-101"]["id"]
        )
        release_placement(placement["id"])

        space = get_space_unit(bundle["spaces"]["A-101"]["id"])
        assert space["status"] == "AVAILABLE"
        assert space["current_application_id"] is None

        released = validate_success(
            api.list_placements(
                TEST_USERS["director_headers"],
                params={"application_id": bundle["application"]["id"]},
            )
        )
        assert [p["status"] for p in released] == ["RELEASED"]


class TestNeighborRequests:
    def test_neighbor_request_moot_when_target_withdraws(self, api, director_headers):
        """PRD §3.6: "And whenever either party's application reaches
        `WITHDRAWN`, `JURIED_REJECTED`, `DECLINED`, or `CANCELLED`, every
        still-`PENDING` request between them becomes `MOOT`."
        PRD §3.3: "Withdrawal is the exhibitor's exit from any pre-contract
        state: from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_REVISION`, or
        `JURIED_WAITLISTED` the application moves to `WITHDRAWN`, and every
        `PENDING` neighbor request involving that exhibitor becomes `MOOT`."

        Design: Corner/state_machines/neighbor_request_moot_when_target_withdraws
        """
        bundle = setup_open_convention(
            space_specs=[ARTIST_TABLE_SPEC],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Artist Amy", category="ARTIST_ALLEY")
        ex_b = register_exhibitor(legal_name="Artist Ben", category="ARTIST_ALLEY")
        app_a = create_application(
            conv_id,
            ex_a["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        app_b = create_application(
            conv_id,
            ex_b["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        submit_application(app_a["id"], ex_a["id"])
        submit_application(app_b["id"], ex_b["id"])
        request = create_neighbor_request(conv_id, ex_a["id"], ex_b["id"], "ADJACENT_TO")
        assert_neighbor_request(request)
        assert request["status"] == "PENDING"

        # The target withdraws; the request is MOOTed by the system cascade.
        withdraw_application(app_b["id"], ex_b["id"])
        updated = validate_success(
            api.get_neighbor_request(request["id"], director_headers)
        )
        assert updated["status"] == "MOOT"

    def test_neighbor_request_honored_on_adjacent_confirm(self, api, director_headers):
        """PRD §3.6: "During each placement-confirm sweep, a `PENDING` request
        is evaluated once both the requester and the target hold at least one
        `CONFIRMED` placement in the convention after that confirm."
        PRD §3.6: "An `ADJACENT_TO` request is `HONORED` when at least one
        requester space is adjacent to at least one target space — same `block`,
        `unit_number` differing by exactly one — and an `AWAY_FROM` request is
        `HONORED` when no requester space is adjacent to any target space."

        Design: Corner/state_machines/neighbor_request_honored_on_adjacent_confirm
        """
        bundle = setup_open_convention(
            space_specs=[ARTIST_TABLE_SPEC, ARTIST_TABLE_SPEC_2],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Artist Amy", category="ARTIST_ALLEY")
        ex_b = register_exhibitor(legal_name="Artist Ben", category="ARTIST_ALLEY")
        app_a = create_application(
            conv_id,
            ex_a["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        app_b = create_application(
            conv_id,
            ex_b["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        submit_application(app_a["id"], ex_a["id"])
        submit_application(app_b["id"], ex_b["id"])
        request = create_neighbor_request(conv_id, ex_a["id"], ex_b["id"], "ADJACENT_TO")

        set_clock(CLOCK_JURY_REVIEW)
        advance_phase(conv_id)  # -> JURY_REVIEW
        post_scores(app_a["id"], STANDARD_SCORES)
        post_scores(app_b["id"], STANDARD_SCORES)
        decide(app_a["id"], "ACCEPTED")
        decide(app_b["id"], "ACCEPTED")
        advance_phase(conv_id)  # -> PLACEMENT
        placement_a = create_placement(app_a["id"], bundle["spaces"]["T-01"]["id"])
        placement_b = create_placement(app_b["id"], bundle["spaces"]["T-02"]["id"])
        submit_and_verify_permit(app_a["id"], ex_a["id"])
        submit_and_verify_permit(app_b["id"], ex_b["id"])
        # ARTIST_TABLE 30000 with early-bird 10%: invoice 27000, deposit 6750.
        accept_offer(app_a["id"], ex_a["id"], 6750)
        accept_offer(app_b["id"], ex_b["id"], 6750)

        validate_success(
            api.confirm_placement(placement_a["id"], director_headers)
        )
        mid = validate_success(api.get_neighbor_request(request["id"], director_headers))
        assert mid["status"] == "PENDING", (
            "target not yet placed: request must stay PENDING"
        )

        validate_success(
            api.confirm_placement(placement_b["id"], director_headers)
        )
        end = validate_success(api.get_neighbor_request(request["id"], director_headers))
        # T-01 and T-02: same block T, |1 - 2| == 1 -> adjacent.
        assert end["status"] == "HONORED"

    def test_neighbor_request_self_target_rejected(self, api):
        """PRD §3.6: "Targeting oneself is rejected with
        `ERR_NEIGHBOR_SELF_TARGET`; the target — like the requester — must hold
        a live application in the convention
        (`ERR_NEIGHBOR_TARGET_NOT_APPLIED`); and a duplicate `PENDING` request
        for the same requester, target, and kind is rejected with
        `ERR_DUPLICATE_NEIGHBOR_REQUEST`."

        Design: Corner/validations/neighbor_request_self_target_rejected
        """
        bundle = setup_submitted_application(
            category="ARTIST_ALLEY",
            kinds=("ARTIST_TABLE",),
            estimated_daily_sales_cents=10000,
            space_specs=[ARTIST_TABLE_SPEC],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        ex_id = bundle["exhibitor"]["id"]
        resp = api.create_neighbor_request(
            {
                "convention_id": bundle["convention"]["id"],
                "target_exhibitor_id": ex_id,
                "kind": "ADJACENT_TO",
            },
            make_exhibitor_headers(ex_id),
        )
        validate_error(resp, ApiErrorId.ERR_NEIGHBOR_SELF_TARGET)

    def test_neighbor_request_duplicate_pair_rejected(self, api):
        """PRD §3.6: "Targeting oneself is rejected with
        `ERR_NEIGHBOR_SELF_TARGET`; the target — like the requester — must hold
        a live application in the convention
        (`ERR_NEIGHBOR_TARGET_NOT_APPLIED`); and a duplicate `PENDING` request
        for the same requester, target, and kind is rejected with
        `ERR_DUPLICATE_NEIGHBOR_REQUEST`."

        Design: Corner/validations/neighbor_request_duplicate_pair_rejected
        """
        bundle = setup_open_convention(
            space_specs=[ARTIST_TABLE_SPEC],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Artist Amy", category="ARTIST_ALLEY")
        ex_b = register_exhibitor(legal_name="Artist Ben", category="ARTIST_ALLEY")
        app_a = create_application(
            conv_id,
            ex_a["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        app_b = create_application(
            conv_id,
            ex_b["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        submit_application(app_a["id"], ex_a["id"])
        submit_application(app_b["id"], ex_b["id"])
        create_neighbor_request(conv_id, ex_a["id"], ex_b["id"], "ADJACENT_TO")
        resp = api.create_neighbor_request(
            {
                "convention_id": conv_id,
                "target_exhibitor_id": ex_b["id"],
                "kind": "ADJACENT_TO",
            },
            make_exhibitor_headers(ex_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NEIGHBOR_REQUEST)

    def test_neighbor_request_target_without_application_rejected(self, api):
        """PRD §3.6: "Targeting oneself is rejected with
        `ERR_NEIGHBOR_SELF_TARGET`; the target — like the requester — must hold
        a live application in the convention
        (`ERR_NEIGHBOR_TARGET_NOT_APPLIED`); and a duplicate `PENDING` request
        for the same requester, target, and kind is rejected with
        `ERR_DUPLICATE_NEIGHBOR_REQUEST`."

        Design: Corner/validations/neighbor_request_target_without_application_rejected
        """
        bundle = setup_open_convention(
            space_specs=[ARTIST_TABLE_SPEC],
            category_quotas=ARTIST_QUOTA_ONLY,
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Artist Amy", category="ARTIST_ALLEY")
        ex_b = register_exhibitor(
            legal_name="Artist Ben", category="ARTIST_ALLEY"
        )  # registered but never applies
        app_a = create_application(
            conv_id,
            ex_a["id"],
            category="ARTIST_ALLEY",
            requested_space_kinds=["ARTIST_TABLE"],
            estimated_daily_sales_cents=10000,
        )
        submit_application(app_a["id"], ex_a["id"])
        resp = api.create_neighbor_request(
            {
                "convention_id": conv_id,
                "target_exhibitor_id": ex_b["id"],
                "kind": "AWAY_FROM",
            },
            make_exhibitor_headers(ex_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NEIGHBOR_TARGET_NOT_APPLIED)
