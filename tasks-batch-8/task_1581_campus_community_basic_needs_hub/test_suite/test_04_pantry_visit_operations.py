"""Pantry visit operations: the 168h frequency window, checkout/void
conservation, operational error codes, and the verified-assessment gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    checkin_visit_with_line,
    checkout,
    create_item,
    create_line_item_payload,
    run_sweeps,
    set_clock,
    setup_pantry_scenario,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["hub_admin_headers"]


class TestVisitFrequencyWindow:
    def _setup_two_completed_visits(self):
        """v1 COMPLETED at 2026-08-03T10:00:00Z, v2 COMPLETED at
        2026-08-04T10:00:00Z (10 points each; allotment 30)."""
        sc = setup_pantry_scenario(
            client_alias="sage",
            item_name="Beans",
            item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                            "reorder_threshold": 0, "per_visit_limit": 5},
        )
        set_clock("2026-08-03T10:00:00Z")
        v1, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
        )
        checkout(sc["pantry_headers"], v1["id"])
        set_clock("2026-08-04T10:00:00Z")
        v2, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
        )
        checkout(sc["pantry_headers"], v2["id"])
        return sc

    def test_third_visit_inside_168h_rejected(self, api):
        """PRD §3.3: "The rolling-window rule counts the client's visits in
        `CHECKED_IN` or `COMPLETED` status whose `visit_date` falls strictly
        inside the trailing 168 hours — a visit exactly 168 hours old does not
        count, and `VOIDED` visits never count — and rejects the check-in with
        `ERR_VISIT_LIMIT_EXCEEDED` when that count has already reached 2; the
        second visit inside the window is admitted, the third rejected."

        Design: Difficulty/boundary_precision_check/visit_frequency_third_visit_rejected_then_allowed_at_exact_168h
        """
        sc = self._setup_two_completed_visits()
        set_clock("2026-08-05T10:00:00Z")
        res = api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"])
        validate_error(res, ApiErrorId.ERR_VISIT_LIMIT_EXCEEDED, expected_status=409)

    def test_visit_exactly_168h_old_falls_outside_window(self, api):
        """PRD §3.3: "The rolling-window rule counts the client's visits in
        `CHECKED_IN` or `COMPLETED` status whose `visit_date` falls strictly
        inside the trailing 168 hours — a visit exactly 168 hours old does not
        count ..."
        PRD §3.3: "A new visit starts `CHECKED_IN` with `visit_date` set to
        the logical now, `week_start` set to the Monday 00:00:00.000Z of the
        containing logical week ..."

        Design: Difficulty/boundary_precision_check/visit_frequency_third_visit_rejected_then_allowed_at_exact_168h
        """
        sc = self._setup_two_completed_visits()
        # At 2026-08-10T10:00:00Z, v1 (2026-08-03T10:00:00Z) is precisely 168h
        # old and fails the strict window test; only v2 still counts.
        set_clock("2026-08-10T10:00:00Z")
        v3 = validate_success(
            api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"]), 201
        )
        assert v3["status"] == "CHECKED_IN"
        assert v3["week_start"] == "2026-08-10T00:00:00.000Z", (
            "v3 lands in the ISO week starting Monday 2026-08-10"
        )


class TestCheckoutVoidConservation:
    def _setup_completed_visit(self):
        """Item Oil cost 10, stock 5, reorder_threshold 3, limit 5; clock
        2026-08-03T10:00:00Z; visit v1 completed with 2 units (20 points)."""
        sc = setup_pantry_scenario(
            client_alias="hazel",
            item_name="Oil",
            item_overrides={"point_cost": 10, "quantity_on_hand": 5,
                            "reorder_threshold": 3, "per_visit_limit": 5},
        )
        set_clock("2026-08-03T10:00:00Z")
        v1, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 2
        )
        checkout(sc["pantry_headers"], v1["id"])
        return sc, v1

    def test_void_restores_stock_and_clears_restock_flag(self, api):
        """PRD §3.3: "every such decrement recomputes that item's
        `restock_flag`, setting it when stock falls to or below the reorder
        threshold".
        PRD §3.3: "Voiding a `COMPLETED` visit restores each line's
        `quantity_on_hand` by the line quantity — each restore recomputing the
        item's `restock_flag`, clearing it when stock climbs back above the
        reorder threshold — ... resets the visit's `points_spent` to 0 ..."

        Design: Difficulty/compensating_invariant/checkout_then_void_restores_stock_points_and_frequency_slot
        """
        sc, v1 = self._setup_completed_visit()
        items_mid = validate_success(api.list_pantry_items(sc["pantry_headers"]), 200)
        assert items_mid[0]["quantity_on_hand"] == 3
        assert items_mid[0]["restock_flag"] is True, "3 <= threshold 3 (inclusive)"

        voided = validate_success(api.void_visit(v1["id"], sc["pantry_headers"]), 200)
        assert voided["status"] == "VOIDED"
        assert voided["points_spent"] == 0

        items_end = validate_success(api.list_pantry_items(sc["pantry_headers"]), 200)
        assert items_end[0]["quantity_on_hand"] == 5, "units conserved across the void"
        assert items_end[0]["restock_flag"] is False

    def test_void_frees_points_and_frequency_slot(self, api):
        """PRD §3.3: "Voiding a `COMPLETED` visit ... recomputes the client's
        settled points downward, resets the visit's `points_spent` to 0, and
        frees the frequency slot, since `VOIDED` visits do not count toward
        the rolling 168-hour limit."

        Design: Difficulty/compensating_invariant/checkout_then_void_restores_stock_points_and_frequency_slot
        """
        sc, v1 = self._setup_completed_visit()
        validate_success(api.void_visit(v1["id"], sc["pantry_headers"]), 200)

        client_after = validate_success(
            api.get_client(sc["client"]["id"], sc["pantry_headers"]), 200
        )
        assert client_after["pantry_points_spent_settled"] == 0, (
            "points conserved: settled returns to 0 after the compensating void"
        )
        v2 = validate_success(
            api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"]), 201
        )
        assert v2["status"] == "CHECKED_IN", (
            "the voided visit holds no 168h frequency slot"
        )


def test_pantry_operational_errors_batch(api):
    """PRD §3.3: "it must hold at least one line item (else
    `ERR_EMPTY_CHECKOUT`)".
    PRD §3.3: "the cumulative units of that item across the visit — including
    earlier lines — must not exceed the item's `per_visit_limit` (else
    `ERR_ITEM_LIMIT_EXCEEDED`)".
    PRD §3.3: "The one-open-visit rule rejects a check-in with
    `ERR_VISIT_ALREADY_OPEN` when the client already has a `CHECKED_IN`
    visit."
    PRD §3.3: "the referenced item must be `ACTIVE` with `quantity_on_hand`
    covering the requested quantity (else `ERR_ITEM_NOT_AVAILABLE`)".

    Design: Corner/errors/pantry_operational_errors_batch
    """
    sc = setup_pantry_scenario(
        client_alias="op",
        assessment_overrides=dict(
            household_size=3, monthly_income_cents=150000,
            housing_status="STABLE", dependents_under_18=2,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=2, consent_confidential=True,
        ),
        item_name="Soap",
        item_overrides={"category": "HYGIENE", "point_cost": 5,
                        "quantity_on_hand": 2, "reorder_threshold": 0,
                        "per_visit_limit": 1},
    )
    pantry = sc["pantry_headers"]
    diapers = create_item(
        "Diapers", category="BABY_CARE", point_cost=5, quantity_on_hand=0,
        reorder_threshold=0, per_visit_limit=5,
    )
    v1 = validate_success(api.check_in_pantry_visit(sc["client"]["id"], pantry), 201)

    res = api.checkout_visit(v1["id"], pantry)
    validate_error(res, ApiErrorId.ERR_EMPTY_CHECKOUT, expected_status=422)

    validate_success(
        api.add_line_item(v1["id"], create_line_item_payload(sc["item"]["id"], 1), pantry),
        201,
    )
    res = api.add_line_item(v1["id"], create_line_item_payload(sc["item"]["id"], 1), pantry)
    validate_error(res, ApiErrorId.ERR_ITEM_LIMIT_EXCEEDED, expected_status=422)

    res = api.check_in_pantry_visit(sc["client"]["id"], pantry)
    validate_error(res, ApiErrorId.ERR_VISIT_ALREADY_OPEN, expected_status=409)

    completed = validate_success(api.checkout_visit(v1["id"], pantry), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["points_spent"] == 5

    v2 = validate_success(api.check_in_pantry_visit(sc["client"]["id"], pantry), 201)
    res = api.add_line_item(v2["id"], create_line_item_payload(diapers["id"], 1), pantry)
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_AVAILABLE, expected_status=409)

    items = validate_success(api.list_pantry_items(pantry, params={"status": "ACTIVE"}), 200)
    soap = [i for i in items if i["item_name"] == "Soap"][0]
    assert soap["quantity_on_hand"] == 1


def test_line_item_add_on_completed_visit_returns_not_open(api):
    """PRD §3.3: "Line adds are admitted only on a `CHECKED_IN` visit (else
    `ERR_VISIT_NOT_OPEN`)".

    Design: Corner/errors/line_item_add_on_completed_visit_returns_not_open
    """
    sc = setup_pantry_scenario(
        client_alias="no",
        item_name="NO",
        item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                        "reorder_threshold": 0, "per_visit_limit": 3},
    )
    v, _ = checkin_visit_with_line(
        sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
    )
    checkout(sc["pantry_headers"], v["id"])

    res = api.add_line_item(
        v["id"], create_line_item_payload(sc["item"]["id"], 1), sc["pantry_headers"]
    )
    validate_error(res, ApiErrorId.ERR_VISIT_NOT_OPEN, expected_status=409)

    lines = validate_success(
        api.list_visit_line_items(sc["pantry_headers"], params={"visit_id": v["id"]}),
        200,
    )
    assert len(lines) == 1, "the pinned line set is unchanged"
    visit_after = validate_success(api.get_pantry_visit(v["id"], sc["pantry_headers"]), 200)
    assert visit_after["points_spent"] == 10


class TestCheckinRequiresVerifiedAssessment:
    def _setup_expired_assessment(self):
        """Client verified at the 2026-08-01T00:00:00Z startup clock, then the
        clock advances to exactly expires_at (2027-08-01T00:00:00Z) and the
        sweep runs."""
        sc = setup_pantry_scenario(
            client_alias="lake",
            item_name="LakeItem",
            item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                            "reorder_threshold": 0, "per_visit_limit": 5},
        )
        verified = validate_success(
            api_client.get_assessment(sc["assessment"]["id"], sc["coord_headers"]), 200
        )
        assert verified["expires_at"] == "2027-08-01T00:00:00.000Z"
        set_clock("2027-08-01T00:00:00Z")
        return sc

    def test_expired_assessment_blocks_pantry_checkin(self, api):
        """PRD §3.2: "sets `expires_at` exactly 365 days after verification —
        ... the assessment expires as soon as the logical clock reaches or
        passes `expires_at`."
        PRD §3.3: "Check-in requires the client to be `ACTIVE` (else
        `ERR_CLIENT_NOT_ACTIVE`) and to hold a verified assessment (else
        `ERR_ASSESSMENT_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_after_verified_assessment_expires
        """
        sc = self._setup_expired_assessment()
        sweep = run_sweeps()
        assert sweep["assessments_expired"] == 1, (
            "the boundary is reached at exactly expires_at"
        )

        res = api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"])
        validate_error(res, ApiErrorId.ERR_ASSESSMENT_REQUIRED, expected_status=409)

        client_after = validate_success(
            api.get_client(sc["client"]["id"], sc["pantry_headers"]), 200
        )
        assert client_after["status"] == "ACTIVE", (
            "assessment expiry does not suspend the client"
        )

    def test_assessment_expiry_unwinds_client_derived_fields(self, api):
        """PRD §3.2: "when no other verified assessment remains for the
        client, the client's derived fields unwind — `household_size_effective`
        returns to null, `pantry_points_allotment` to 0, and `risk_tier` to
        null."

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_after_verified_assessment_expires
        """
        sc = self._setup_expired_assessment()
        run_sweeps()
        client_after = validate_success(
            api.get_client(sc["client"]["id"], sc["coord_headers"]), 200
        )
        assert client_after["household_size_effective"] is None
        assert client_after["pantry_points_allotment"] == 0
        assert client_after["risk_tier"] is None
