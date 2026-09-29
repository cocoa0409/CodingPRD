"""Races on the §2.9 precedence ladder, plus the authentication, role and
ownership gates that occupy its top four rungs.

Every scenario below is a request that would fail two declared checks at once.
The ladder in §2.9 fixes which single error comes back, so each race asserts the
winning identifier, asserts the losing identifier was not the one returned, and
then re-reads the domain to show that nothing was written or moved.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK,
    TEST_USERS,
    advance_show,
    booth_version,
    build_user_headers,
    create_exhibitor,
    create_jurisdiction,
    create_labor_call_payload,
    create_service_order_payload,
    create_venue,
    create_venue_payload,
    get_change_order,
    get_labor_call,
    make_exhibitor_headers,
    raise_change_order,
    service_order_line,
    set_clock,
    setup_order_ground,
    setup_requested_labor_call,
    setup_show_ground,
    submit_change_order,
    validate_error,
    validate_paginated,
)

OPS = TEST_USERS["show_operations_headers"]

# A jurisdiction that forbids exhibitor self-install, caps a crew at six workers
# and demands a thirty minute turnaround between calls.
STRICT_RIGGING_JURISDICTION = {
    "trade": "RIGGING",
    "straight_time_rate_cents_per_hour": 14000,
    "min_call_hours": 4,
    "crew_max_size": 6,
    "exhibitor_self_install_allowed": False,
    "turnaround_buffer_minutes": 30,
}

# One cleaning line: 2 units at 75000 cents under the ADVANCE multiplier of 1.00
# prices the order at 154080 cents, far beyond a 100 cent credit limit.
CLEANING_LINES = [service_order_line(1, "CLN-VAC", 2, 75000, 0)]


def _closed_show_with_hairline_credit_limit():
    """A show walked all the way to CLOSED, held by an exhibitor whose credit
    limit is 100 cents, so a single cleaning order breaches both gates at once."""
    return setup_show_ground(show_status="CLOSED", credit_limit_cents=100)


def _order_on_the_closed_show(api, ground):
    """Raise the doomed cleaning order as the booth's own exhibitor, pinning the
    booth version re-read after the show transitions so the rung 12 stale-version
    check cannot fire ahead of the checks being raced."""
    payload = create_service_order_payload(
        ground["booth"]["id"],
        booth_version(ground["booth"]["id"]),
        service_type="CLEANING",
        lines=CLEANING_LINES,
    )
    return api.create_service_order(
        payload, make_exhibitor_headers(ground["exhibitor"]["id"]))


class TestClosedShowOutranksTheFiscalGate:
    """A CLOSED show and a blown credit limit on one service order request."""

    def test_closed_show_is_reported_instead_of_the_credit_limit_breach(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §2.9: "The show reached from the target is in a status that admits the operation — otherwise `ERR_SHOW_NOT_ACCEPTING` (409)."
        PRD §2.9: "Projected credit exposure is within the exhibitor's limit — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (402)."
        PRD §3.5: "The show reached from the booth must be in `OPEN_FOR_ORDERS`, `ADVANCE_CLOSED`, `MOVE_IN` or `ON_SITE`, or the request is refused with `ERR_SHOW_NOT_ACCEPTING`."
        PRD §3.5: "That figure must not exceed the exhibitor's `credit_limit_cents`; equality is permitted, and only a strictly greater figure is refused, with `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402."

        Design: Difficulty/priority_pair_validation_conflict/closed_show_state_beats_credit_limit_fiscal
        """
        ground = _closed_show_with_hairline_credit_limit()

        response = _order_on_the_closed_show(api, ground)

        error = validate_error(response, ApiErrorId.ERR_SHOW_NOT_ACCEPTING,
                               expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
            "The show-status rung is judged before the projected-exposure rung, so a "
            "154080 cent order against a 100 cent limit on a CLOSED show must still "
            f"report ERR_SHOW_NOT_ACCEPTING, got {error['error_id']}")

    def test_closed_show_outranks_the_frozen_booth_and_writes_no_order(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §2.9: "A check is only reached when every check above it has passed."
        PRD §2.9: "The booth reached from the target is not `FROZEN` — otherwise `ERR_BOOTH_FROZEN` (409)."
        PRD §2.10: "The booth's show has `status` `CLOSED` — posture `FROZEN`, reason `SHOW_CLOSED`."
        PRD §2.10: "Everything a `RESTRICTED` booth blocks, a `FROZEN` booth also blocks, and where both would apply the `FROZEN` rejection is the one returned, because it sits higher on the ladder."

        Design: Difficulty/priority_pair_validation_conflict/closed_show_state_beats_credit_limit_fiscal
        """
        ground = _closed_show_with_hairline_credit_limit()

        response = _order_on_the_closed_show(api, ground)

        error = validate_error(response, ApiErrorId.ERR_SHOW_NOT_ACCEPTING,
                               expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_BOOTH_FROZEN.value, (
            "The CLOSED show freezes the booth, but the show-status rung sits above "
            f"the frozen-booth rung, got {error['error_id']}")

        rows, meta = validate_paginated(
            api.list_service_orders(OPS, params={"booth_id": ground["booth"]["id"]}))
        assert meta["total_count"] == 0, (
            "A refused order writes nothing, so the booth must carry no service "
            f"orders, got total_count {meta['total_count']}")
        assert rows == [], f"Expected no service order rows on the booth, got {rows}"


def _labor_ground_with_foreign_jurisdiction():
    """The show sits at venue A; the RIGGING craft that forbids self-install is
    declared at venue B, so one labor call can fail both checks together."""
    ground = setup_show_ground(show_status="ON_SITE")
    other_venue = create_venue(name="Lakeside Expo Hall", city="Milwaukee")
    ground["foreign_venue"] = other_venue
    ground["foreign_jurisdiction"] = create_jurisdiction(
        other_venue["id"], **STRICT_RIGGING_JURISDICTION)
    return ground


def _self_install_call_under_foreign_jurisdiction(api, ground):
    payload = create_labor_call_payload(
        ground["booth"]["id"],
        ground["foreign_jurisdiction"]["id"],
        crew_size=2,
        self_install_requested=True,
    )
    return api.create_labor_call(
        payload, make_exhibitor_headers(ground["exhibitor"]["id"]))


class TestUnionSelfInstallOutranksTheVenueReferentialCheck:
    """Self-install forbidden by the craft, and the craft belongs to another hall."""

    def test_self_install_refusal_is_reported_instead_of_the_venue_mismatch(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §2.9: "Self-install is permitted by the named jurisdiction — otherwise `ERR_UNION_JURISDICTION_REQUIRED` (422)."
        PRD §2.9: "The jurisdiction belongs to the venue hosting the booth's show — otherwise `ERR_JURISDICTION_VENUE_MISMATCH` (422)."
        PRD §3.7: "Self-install is only honoured where the union permits it: when `self_install_requested` is true and the named jurisdiction's `exhibitor_self_install_allowed` is false, the request is refused with `ERR_UNION_JURISDICTION_REQUIRED`."
        PRD §3.7: "The craft must belong to the right building: the named jurisdiction's `venue_id` must equal the `venue_id` of the show reached from the booth, or the request is refused with `ERR_JURISDICTION_VENUE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/union_safety_beats_jurisdiction_venue_referential
        """
        ground = _labor_ground_with_foreign_jurisdiction()

        response = _self_install_call_under_foreign_jurisdiction(api, ground)

        error = validate_error(response, ApiErrorId.ERR_UNION_JURISDICTION_REQUIRED,
                               expected_status=422)
        assert error["error_id"] != ApiErrorId.ERR_JURISDICTION_VENUE_MISMATCH.value, (
            "The self-install rung is judged before the jurisdiction-venue rung, so a "
            "call naming another hall's craft with self_install_requested true must "
            f"still report ERR_UNION_JURISDICTION_REQUIRED, got {error['error_id']}")

    def test_refused_self_install_request_leaves_no_labor_call_on_the_booth(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §3.7: "Self-install is only honoured where the union permits it: when `self_install_requested` is true and the named jurisdiction's `exhibitor_self_install_allowed` is false, the request is refused with `ERR_UNION_JURISDICTION_REQUIRED`."
        PRD §3.7: "Five checks guard the request, in the precedence order §2.9 fixes."

        Design: Difficulty/priority_pair_validation_conflict/union_safety_beats_jurisdiction_venue_referential
        """
        ground = _labor_ground_with_foreign_jurisdiction()

        response = _self_install_call_under_foreign_jurisdiction(api, ground)
        validate_error(response, ApiErrorId.ERR_UNION_JURISDICTION_REQUIRED,
                       expected_status=422)

        rows, meta = validate_paginated(
            api.list_labor_calls(OPS, params={"booth_id": ground["booth"]["id"]}))
        assert meta["total_count"] == 0, (
            "A refused labor call writes no row, so the booth must carry no calls, "
            f"got total_count {meta['total_count']}")
        assert rows == [], f"Expected no labor call rows on the booth, got {rows}"


def _booth_with_a_live_afternoon_call():
    """A REQUESTED crew already occupies 13:00 to 17:00 on the booth under a
    craft whose turnaround buffer is thirty minutes and whose crew cap is six."""
    return setup_requested_labor_call(
        show_status="ON_SITE",
        call_overrides={"crew_size": 4},
        jurisdiction_overrides=STRICT_RIGGING_JURISDICTION,
    )


def _oversized_overlapping_call(api, ground):
    """16:00 to 19:00 lands inside the buffered shadow of the live call, and nine
    workers exceed the jurisdiction's cap of six."""
    payload = create_labor_call_payload(
        ground["booth"]["id"],
        ground["jurisdiction"]["id"],
        scheduled_start="2026-09-21T16:00:00Z",
        scheduled_end="2026-09-21T19:00:00Z",
        crew_size=9,
    )
    return api.create_labor_call(payload, OPS)


class TestBufferedOverlapOutranksTheCrewSizeCap:
    """One labor call that both collides with a live crew and asks for too many."""

    def test_buffered_overlap_is_reported_instead_of_the_crew_size_limit(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §2.9: "Buffered crew overlap — otherwise `ERR_LABOR_CALL_OVERLAP` (409)."
        PRD §2.9: "Crew size within the jurisdiction's bounds — otherwise `ERR_CREW_SIZE_LIMIT` (422)."
        PRD §3.7: "The crew resource must be free, accounting for the jurisdiction's mandatory turnaround: considering the same `jurisdiction_id` and `booth_id` pair, and every existing call on that pair whose `status` is `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly before the existing call's `scheduled_end` extended forward by `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls strictly before the new `scheduled_end` extended forward by the same buffer."
        PRD §3.7: "And the crew must be a legal size: `crew_size` must be at least 1 and no greater than the jurisdiction's `crew_max_size`, or the request is refused with `ERR_CREW_SIZE_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/labor_overlap_temporal_beats_crew_size_constraint
        """
        ground = _booth_with_a_live_afternoon_call()

        response = _oversized_overlapping_call(api, ground)

        error = validate_error(response, ApiErrorId.ERR_LABOR_CALL_OVERLAP,
                               expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_CREW_SIZE_LIMIT.value, (
            "The buffered-overlap rung is judged before the crew-size rung, so a nine "
            "worker call landing inside the thirty minute turnaround must still report "
            f"ERR_LABOR_CALL_OVERLAP, got {error['error_id']}")

    def test_rejected_overlap_leaves_the_live_call_requested_and_alone(self, api):
        """PRD §2.9: "A check is only reached when every check above it has passed."
        PRD §3.7: "The call is born `REQUESTED` with `actual_start`, `actual_end`, `billed_hours`, `st_hours`, `ot_hours`, `dt_hours` and `labor_charge_cents` all null."
        PRD §3.7: "The crew resource must be free, accounting for the jurisdiction's mandatory turnaround: considering the same `jurisdiction_id` and `booth_id` pair, and every existing call on that pair whose `status` is `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly before the existing call's `scheduled_end` extended forward by `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls strictly before the new `scheduled_end` extended forward by the same buffer."

        Design: Difficulty/priority_pair_validation_conflict/labor_overlap_temporal_beats_crew_size_constraint
        """
        ground = _booth_with_a_live_afternoon_call()
        first_call_id = ground["labor_call"]["id"]

        response = _oversized_overlapping_call(api, ground)
        validate_error(response, ApiErrorId.ERR_LABOR_CALL_OVERLAP, expected_status=409)

        first_call = get_labor_call(first_call_id)
        assert first_call["status"] == "REQUESTED", (
            "The rejected second call must not disturb the call it collided with, "
            f"expected REQUESTED, got {first_call['status']}")

        rows, meta = validate_paginated(
            api.list_labor_calls(OPS, params={"booth_id": ground["booth"]["id"]}))
        assert meta["total_count"] == 1, (
            "Only the original call may exist on the booth, got total_count "
            f"{meta['total_count']}")
        assert [row["id"] for row in rows] == [first_call_id], (
            f"Expected only labor call {first_call_id} on the booth, got {rows}")


def _submitted_change_order_raised_by_ops_one():
    """A change order created by ops-1 and moved only as far as SUBMITTED, so an
    APPROVE by ops-1 fails both the segregation rung and the from-state rung."""
    ground = setup_order_ground(show_status="OPEN_FOR_ORDERS",
                                lines=[service_order_line(1)])
    show_id = ground["show"]["id"]
    for status in ("ADVANCE_CLOSED", "MOVE_IN", "ON_SITE"):
        advance_show(show_id, status)
    change_order = raise_change_order(
        ground["booth"]["id"], "SERVICE_ORDER", ground["order"]["id"],
        actor_headers=OPS, delta_kind="QTY_INCREASE", delta_qty=1,
        reason="One more drop")
    ground["change_order"] = submit_change_order(change_order["id"], OPS)
    return ground


class TestSegregationOfDutiesOutranksTheFromStateCheck:
    """The creating operator approving its own change order, out of state too."""

    def test_segregation_of_duties_is_reported_instead_of_the_state_transition(self, api):
        """PRD §2.9: "When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder."
        PRD §2.9: "Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §2.9: "The target sits in a from-state the requested transition declares — otherwise `ERR_INVALID_STATE_TRANSITION` (409)."
        PRD §2.1: "Three decisions may not be taken by the operator who originated the thing being decided: approving or rejecting a change order (the acting `X-User-ID` must differ from that change order's `created_by_user_id`), adjudicating a damage claim (must differ from `filed_by_user_id`), and voiding an invoice (must differ from `issued_by_user_id`)."
        PRD §2.1: "A violation of any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "A change order resting in `UNDER_REVIEW` awaits exactly one of three outcomes, and no other status accepts a decision."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_auth_beats_invalid_state
        """
        ground = _submitted_change_order_raised_by_ops_one()

        response = api.review_change_order(
            ground["change_order"]["id"], {"decision": "APPROVE"}, OPS)

        error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                               expected_status=403)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, (
            "The segregation rung is judged before the from-state rung, so ops-1 "
            "approving its own SUBMITTED change order must still report "
            f"ERR_SEGREGATION_OF_DUTIES, got {error['error_id']}")

    def test_refused_self_approval_leaves_the_change_order_submitted_and_unreviewed(self, api):
        """PRD §2.9: "A check is only reached when every check above it has passed."
        PRD §3.8: "The change order is born `DRAFT`, with `created_by_user_id` taken from the acting `X-User-ID`, `reviewed_by_user_id` null and `price_delta_cents` null."
        PRD §3.8: "A `decision` of `APPROVE` moves `UNDER_REVIEW → APPROVED`, requires the acting `X-User-ID` to differ from the change order's `created_by_user_id`, and records that operator as `reviewed_by_user_id`; the booth then recomputes posture and lands on `RESTRICTED` with `posture_reason` `CHANGE_ORDER_APPROVED` unless a freezing clause outranks it."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_auth_beats_invalid_state
        """
        ground = _submitted_change_order_raised_by_ops_one()
        change_order_id = ground["change_order"]["id"]

        response = api.review_change_order(
            change_order_id, {"decision": "APPROVE"}, OPS)
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        change_order = get_change_order(change_order_id)
        assert change_order["status"] == "SUBMITTED", (
            "A refused review moves nothing, so the change order must still be "
            f"SUBMITTED, got {change_order['status']}")
        assert change_order["reviewed_by_user_id"] is None, (
            "No reviewer identity may be recorded by a refused approval, got "
            f"{change_order['reviewed_by_user_id']}")


class TestAuthenticationRoleAndOwnershipGates:
    """The top four rungs: headers present, role recognised, role authorised,
    and the entity-backed identity owning what it writes against."""

    def test_exhibitor_may_not_register_a_venue(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to invoke it (see §4)."
        PRD §2.1: "When an authenticated operator's role is not on that endpoint's list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/venues` | Register a venue with its straight-time band, forklift limit and hanging-sign policy | `ShowOperations` |"

        Design: Corner/rbac/exhibitor_cannot_create_venue
        """
        set_clock(BASE_CLOCK)
        exhibitor = create_exhibitor()

        response = api.create_venue(
            create_venue_payload(name="Pirate Hall", city="Chicago"),
            make_exhibitor_headers(exhibitor["id"]))

        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_exhibitor_may_not_order_against_another_exhibitors_booth(self, api):
        """PRD §2.1: "When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting `Exhibitor` row; ownership checks on any resource that references an exhibitor compare that resource's `exhibitor_id` — reached directly on the resource, or indirectly through the booth, order, crate, asset, design, claim or invoice named by the request — to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.1: "Passing the role check is not the same as passing the ownership check, and the two are evaluated in that order."
        PRD §2.9: "Ownership: an acting `Exhibitor`'s `X-User-ID` equals the `exhibitor_id` reachable from the target resource, and an acting `WarehouseAgent`'s `X-User-ID` equals the `warehouse_id` the request targets — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."
        PRD §4: "| POST | `/service-orders` | Order a show service against a booth; tiers, prices and credit-checks the order in one call | `Exhibitor`, `ShowOperations` |"

        Design: Corner/rbac/exhibitor_cannot_order_against_another_exhibitors_booth
        """
        ground = setup_show_ground()
        intruder = create_exhibitor(company_name="Borealis Robotics",
                                    contact_email="ap@borealis.test")

        payload = create_service_order_payload(
            ground["booth"]["id"], booth_version(ground["booth"]["id"]),
            lines=[service_order_line(1)])
        response = api.create_service_order(
            payload, make_exhibitor_headers(intruder["id"]))

        error = validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER,
                               expected_status=403)
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
            "Exhibitor is an authorised role on POST /service-orders, so the refusal "
            f"must be the ownership one, got {error['error_id']}")

        rows, meta = validate_paginated(
            api.list_service_orders(OPS, params={"booth_id": ground["booth"]["id"]}))
        assert meta["total_count"] == 0, (
            "The intruder's refused order must leave the booth with no service "
            f"orders, got total_count {meta['total_count']}")
        assert rows == [], f"Expected no service order rows on the booth, got {rows}"

    @pytest.mark.parametrize("headers", [
        pytest.param({"Content-Type": "application/json"},
                     id="neither_user_id_nor_role"),
        pytest.param(build_user_headers("ops-1", "DockForeman"),
                     id="role_outside_the_declared_six"),
    ])
    def test_absent_or_unrecognised_role_headers_are_unauthenticated(self, api, headers):
        """PRD §2.1: "Every request, without exception, must carry two headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity that operator is acting in."
        PRD §2.1: "If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The same 401 and the same `ERR_UNAUTHENTICATED` identifier are returned when `X-User-Role` carries a value that is not one of the six roles the system recognises."
        PRD §2.1: "Those six roles are `Exhibitor`, `ShowOperations`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster` and `FinanceController`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        set_clock(BASE_CLOCK)
        venue = create_venue()

        response = api.get_venue(venue["id"], headers)

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
