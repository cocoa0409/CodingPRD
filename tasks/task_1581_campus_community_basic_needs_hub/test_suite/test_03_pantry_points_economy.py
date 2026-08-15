"""Weekly points economy: settled/reserved bases, allotment boundaries,
supersession recomputation, pinned line pricing, immediate consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    checkin_visit_with_line,
    create_active_client,
    create_coordinator,
    create_item,
    create_pantry_staff,
    get_success_data,
    set_clock,
    setup_pantry_scenario,
    validate_error,
    validate_success,
)


class TestSettledVsReservedBasis:
    def test_open_visit_reserved_basis_exceeds_settled_basis(self, api):
        """PRD §3.3: "`pantry_points_spent_settled` sums `points_spent` over
        the client's `COMPLETED` visits whose `week_start` equals the current
        window — an open checked-in visit does not reduce the displayed
        settled figure. `pantry_points_spent_reserved` adds the open visit's
        `provisional_points` on top of the settled figure — identical data
        therefore yields a larger reserved figure while a visit is open ..."

        Design: Difficulty/dual_variant_calc/points_balance_settled_vs_reserved_basis
        """
        sc = setup_pantry_scenario(
            client_alias="moss",
            item_name="Rice 1lb",
            item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                            "reorder_threshold": 0, "per_visit_limit": 5},
        )
        visit, line = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 2
        )
        mid = validate_success(
            api.get_client(sc["client"]["id"], sc["pantry_headers"]), 200
        )
        assert mid["pantry_points_spent_settled"] == 0, (
            "no COMPLETED visit yet — settled basis is 0"
        )
        assert mid["pantry_points_spent_reserved"] == 20, (
            "reserved basis adds the open visit's 20 provisional points"
        )
        # The check-in response is a pre-line-add snapshot; re-read the visit.
        visit_mid = validate_success(
            api.get_pantry_visit(visit["id"], sc["pantry_headers"]), 200
        )
        assert visit_mid["provisional_points"] == 20
        assert visit_mid["points_spent"] == 0

    def test_checkout_converges_settled_and_reserved_bases(self, api):
        """PRD §3.3: "On success the visit moves to `COMPLETED`: `points_spent`
        is finalized to the provisional total and `provisional_points` is
        cleared to 0 ... and the client's spent totals are recomputed."
        PRD §3.3: "`pantry_points_spent_reserved` adds the open visit's
        `provisional_points` on top of the settled figure".

        Design: Difficulty/dual_variant_calc/points_balance_settled_vs_reserved_basis
        """
        sc = setup_pantry_scenario(
            client_alias="moss",
            item_name="Rice 1lb",
            item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                            "reorder_threshold": 0, "per_visit_limit": 5},
        )
        visit, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 2
        )
        completed = validate_success(api.checkout_visit(visit["id"], sc["pantry_headers"]), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["points_spent"] == 20
        assert completed["provisional_points"] == 0

        end = validate_success(
            api.get_client(sc["client"]["id"], sc["pantry_headers"]), 200
        )
        assert end["pantry_points_spent_settled"] == 20
        assert end["pantry_points_spent_reserved"] == 20, (
            "no open visit remains — the two bases converge"
        )


class TestCheckoutAllotmentBoundary:
    def _setup_at_monday(self):
        """Client hh=1 (allotment 30); item cost 10 stock 10 limit 5; clock at
        Monday 2026-08-03T10:00:00Z; visit A holds 3 units (30 points)."""
        sc = setup_pantry_scenario(
            client_alias="reed",
            item_name="Pasta",
            item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                            "reorder_threshold": 0, "per_visit_limit": 5},
        )
        set_clock("2026-08-03T10:00:00Z")
        visit_a, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 3
        )
        return sc, visit_a

    def test_checkout_exactly_at_allotment_passes(self, api):
        """PRD §3.3: "the reserved-basis points test must pass — the client's
        `pantry_points_spent_settled` for the current week window plus this
        visit's `provisional_points` must not exceed the client's
        `pantry_points_allotment`, where exactly reaching the allotment passes
        and any excess is rejected with `ERR_POINTS_BALANCE_EXCEEDED`"
        PRD §3.2: "a base of 30 points, plus 10 points for each household
        member beyond the first (per `household_size_effective`), capped at
        60 points."

        Design: Difficulty/boundary_precision_check/checkout_at_exact_points_allotment_passes_one_point_over_fails
        """
        sc, visit_a = self._setup_at_monday()
        completed = validate_success(
            api.checkout_visit(visit_a["id"], sc["pantry_headers"]), 200
        )
        assert completed["status"] == "COMPLETED"
        assert completed["points_spent"] == 30, (
            "settled 0 + provisional 30 == allotment 30 — the boundary value passes"
        )

    def test_checkout_one_point_over_allotment_fails(self, api):
        """PRD §3.3: "the reserved-basis points test must pass — the client's
        `pantry_points_spent_settled` for the current week window plus this
        visit's `provisional_points` must not exceed the client's
        `pantry_points_allotment`, where exactly reaching the allotment passes
        and any excess is rejected with `ERR_POINTS_BALANCE_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/checkout_at_exact_points_allotment_passes_one_point_over_fails
        """
        sc, visit_a = self._setup_at_monday()
        validate_success(api.checkout_visit(visit_a["id"], sc["pantry_headers"]), 200)

        visit_b, _ = checkin_visit_with_line(
            sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
        )
        res = api.checkout_visit(visit_b["id"], sc["pantry_headers"])
        validate_error(res, ApiErrorId.ERR_POINTS_BALANCE_EXCEEDED, expected_status=422)

        visit_b_after = validate_success(
            api.get_pantry_visit(visit_b["id"], sc["pantry_headers"]), 200
        )
        assert visit_b_after["status"] == "CHECKED_IN", (
            "failed checkout applies no stock or points movement"
        )
        items = validate_success(api.list_pantry_items(sc["pantry_headers"]), 200)
        assert items[0]["quantity_on_hand"] == 7, (
            "only visit A's 3 units decremented the stock"
        )


def test_allotment_shrinks_midweek_after_superseding_verification(api):
    """PRD §3.2: "Any other `VERIFIED` assessment of the same client is
    automatically superseded to `SUPERSEDED`, so at most one verified
    assessment exists per client at any time. The client's derived fields are
    then recomputed from the newly verified assessment: ... the
    `pantry_points_allotment` is recomputed per the weekly-budget rule ..."
    PRD §3.3: "any excess is rejected with `ERR_POINTS_BALANCE_EXCEEDED`."

    Design: Corner/calculations/pantry_allotment_shrinks_midweek_after_superseding_verification
    """
    _, coord = create_coordinator()
    _, pantry = create_pantry_staff()
    client, first, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=4, monthly_income_cents=300000,
            housing_status="COST_BURDENED", dependents_under_18=3,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=2, consent_confidential=True,
        ),
        client_overrides={"alias_name": "shrink"},
    )
    item = create_item("Milk", category="PERISHABLE", point_cost=10,
                       quantity_on_hand=10, reorder_threshold=0, per_visit_limit=5)
    set_clock("2026-08-03T10:00:00Z")
    visit_a, _ = checkin_visit_with_line(pantry, client["id"], item["id"], 5)
    validate_success(api.checkout_visit(visit_a["id"], pantry), 200)

    # A second assessment with household_size 1 supersedes the first mid-week.
    second = get_success_data(
        api.create_assessment(
            client["id"],
            dict(household_size=1, monthly_income_cents=100000,
                 housing_status="STABLE", dependents_under_18=0,
                 receives_snap=False, receives_childcare_subsidy=False,
                 food_insecurity_score=1, consent_confidential=True),
            coord,
        )
    )
    validate_success(api.submit_assessment(client["id"], second["id"], coord), 200)
    current = validate_success(api.get_client(client["id"], coord), 200)
    validate_success(
        api.verify_assessment(
            client["id"], second["id"],
            {"expected_client_version": current["version"]}, coord,
        ),
        200,
    )

    after = validate_success(api.get_client(client["id"], pantry), 200)
    assert after["pantry_points_allotment"] == 30, "allotment recomputed to hh=1"
    assert after["pantry_points_spent_settled"] == 50, "history is not rewritten"

    first_after = validate_success(api.get_assessment(first["id"], coord), 200)
    second_after = validate_success(api.get_assessment(second["id"], coord), 200)
    assert first_after["status"] == "SUPERSEDED"
    assert second_after["status"] == "VERIFIED"

    visit_b, _ = checkin_visit_with_line(pantry, client["id"], item["id"], 1)
    res = api.checkout_visit(visit_b["id"], pantry)
    validate_error(res, ApiErrorId.ERR_POINTS_BALANCE_EXCEEDED, expected_status=422)
    visit_b_after = validate_success(api.get_pantry_visit(visit_b["id"], pantry), 200)
    assert visit_b_after["status"] == "CHECKED_IN", (
        "settled 50 + provisional 10 > allotment 30 — checkout rejected, visit stays open"
    )


def test_checkout_write_visible_in_response_and_next_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.3: "On success the visit moves to `COMPLETED`: `points_spent` is
    finalized to the provisional total and `provisional_points` is cleared to
    0; each line decrements its item's `quantity_on_hand` by the line quantity
    ... and the client's spent totals are recomputed."

    Design: Corner/consistency_model/writes_visible_in_same_request_and_next_read
    """
    sc = setup_pantry_scenario(
        client_alias="ic",
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=100000,
            housing_status="STABLE", dependents_under_18=1,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=1, consent_confidential=True,
        ),
        item_name="IC",
        item_overrides={"point_cost": 20, "quantity_on_hand": 3,
                        "reorder_threshold": 0, "per_visit_limit": 2},
    )
    visit, _ = checkin_visit_with_line(
        sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
    )
    completed = validate_success(api.checkout_visit(visit["id"], sc["pantry_headers"]), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["points_spent"] == 20

    client_after = validate_success(
        api.get_client(sc["client"]["id"], sc["pantry_headers"]), 200
    )
    assert client_after["pantry_points_spent_settled"] == 20
    assert client_after["pantry_points_spent_reserved"] == 20

    items = validate_success(api.list_pantry_items(sc["pantry_headers"]), 200)
    assert items[0]["quantity_on_hand"] == 2


def test_line_item_points_pinned_at_add_time(api):
    """PRD §3.3: "Each recorded line pins its `points_charged` as the line's
    `quantity` multiplied by the item's `point_cost` at that moment, and the
    visit's `provisional_points` grows by the same amount."
    PRD §3.3: "a `point_cost` change never retro-edits the pinned
    `points_charged` of line items already recorded."

    Design: Corner/entities/line_item_points_pinned_at_add_time
    """
    sc = setup_pantry_scenario(
        client_alias="p",
        item_name="Tuna",
        item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                        "reorder_threshold": 0, "per_visit_limit": 5},
    )
    visit, line = checkin_visit_with_line(
        sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 2
    )
    assert line["points_charged"] == 20, "2 units x 10 points pinned at add time"

    validate_success(
        api.patch_pantry_item(
            sc["item"]["id"],
            {"point_cost": 15, "expected_item_version": sc["item"]["version"]},
            TEST_USERS["hub_admin_headers"],
        ),
        200,
    )

    lines = validate_success(
        api.list_visit_line_items(sc["pantry_headers"], params={"visit_id": visit["id"]}),
        200,
    )
    assert lines[0]["points_charged"] == 20, (
        "later price changes never retro-edit pinned lines"
    )
    visit_after = validate_success(
        api.get_pantry_visit(visit["id"], sc["pantry_headers"]), 200
    )
    assert visit_after["provisional_points"] == 20
