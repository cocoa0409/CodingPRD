"""Invariants that survive an operation because two effects cancel exactly.

A superseding verification raises one census counter and lowers another in the
same operation, leaving the special-diet census where it started. A tool
declaration and its recovery return move the sharps counters in opposite
directions, and the conservation identity has to hold at every instant in between.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Superseding verification: increment and decrement cancel
# ---------------------------------------------------------------------------


def _halal_order_and_its_replacement(api: ApiClient) -> dict:
    """A verified HALAL accommodation plus a pending vegetarian order raised to
    supersede it over the identical window."""
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-CI1"},
        facility_overrides={
            "facility_code": "FAC-CI1",
            "sharps_authorized_count": 12,
        },
    )
    inmate = fixtures.create_inmate(
        api, ctx["facility"]["id"], religious_affiliation="MUSLIM"
    )
    order_a = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="HALAL",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    order_a = validate_success(api.verify_diet_order(order_a["id"], users.CHAPLAIN))

    inmate = validate_success(api.get_inmate(inmate["id"], users.OFFICER))
    order_b = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="VEGETARIAN_RELIGIOUS",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
                supersedes_diet_order_id=order_a["id"],
            ),
            users.DIETITIAN,
        ),
        201,
    )
    ctx["inmate"] = inmate
    ctx["order_a"] = order_a
    ctx["order_b"] = order_b
    return ctx


def test_a_superseding_verification_leaves_both_census_counters_where_they_were(
    api: ApiClient,
) -> None:
    """The replacement becomes active and the incumbent is revoked in one operation,
    so neither counter moves even though both orders did.

    The PRD states: "When the verified order carries a `supersedes_diet_order_id`, one
    further cascade hop runs in the same operation: the incumbent order transitions
    `ACTIVE` → `REVOKED` with its own `version` incremented by 1. Because the
    incumbent has left `ACTIVE`, a second hop then decrements
    `Inmate.active_diet_order_count` by 1 and `Facility.active_special_diet_count` by
    1. The increment and the decrement cancel exactly, so both counters read the same
    value after a superseding verification as they did before it — this is the
    compensating invariant that keeps an inmate's active order count pinned at no more
    than 1."

    Design: Difficulty/compensating_invariant/supersede_verify_leaves_special_diet_census_unchanged
    """
    ctx = _halal_order_and_its_replacement(api)

    assert ctx["order_b"]["status"] == "PENDING_VERIFICATION"
    assert ctx["order_b"]["supersedes_diet_order_id"] == ctx["order_a"]["id"]

    inmate_before = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    facility_before = fixtures.read_facility(api, ctx["facility"]["id"])
    assert inmate_before["active_diet_order_count"] == 1
    assert facility_before["active_special_diet_count"] == 1

    verified_b = validate_success(
        api.verify_diet_order(ctx["order_b"]["id"], users.CHAPLAIN)
    )
    assert verified_b["status"] == "ACTIVE"
    assertions.assert_version_bumped_by(ctx["order_b"], verified_b)

    revoked_a = fixtures.read_diet_order(api, ctx["order_a"]["id"])
    assert revoked_a["status"] == "REVOKED"
    assert revoked_a["version"] > ctx["order_a"]["version"]

    inmate_after = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    facility_after = fixtures.read_facility(api, ctx["facility"]["id"])
    assert inmate_after["active_diet_order_count"] == 1
    assert facility_after["active_special_diet_count"] == 1


def test_a_verification_with_no_supersede_raises_the_census_by_exactly_one(
    api: ApiClient,
) -> None:
    """The compensating pair is what pins the census: an ordinary verification on a
    second family moves both counters up.

    The PRD states: "A verification with no supersede simply raises both counters by
    exactly 1." It also defines the counters as counts over source rows —
    "`Inmate.active_diet_order_count` is the number of diet orders for that inmate
    whose `status` is `ACTIVE`" and "`Facility.active_special_diet_count` is the number
    of `ACTIVE` diet orders whose inmate sits at that facility *and* is still
    `IN_CUSTODY`", with orders in "`PENDING_VERIFICATION`, `SUSPENDED`, `EXPIRED` or
    `REVOKED`" excluded from both.

    Design: Difficulty/compensating_invariant/supersede_verify_leaves_special_diet_census_unchanged
    """
    ctx = _halal_order_and_its_replacement(api)
    validate_success(api.verify_diet_order(ctx["order_b"]["id"], users.CHAPLAIN))

    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    order_c = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="GLUTEN_FREE",
                clinical_indication="Biopsy-confirmed coeliac disease",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    verified_c = validate_success(api.verify_diet_order(order_c["id"], users.MEDICAL))
    assert verified_c["status"] == "ACTIVE"

    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert inmate["active_diet_order_count"] == 2
    assert facility["active_special_diet_count"] == 2

    orders, meta = validate_paginated(
        api.list_diet_orders(users.DIETITIAN, {"inmate_id": ctx["inmate"]["id"]})
    )
    assert meta["total_count"] == 3
    statuses = sorted(order["status"] for order in orders)
    assert statuses == ["ACTIVE", "ACTIVE", "REVOKED"]


# ---------------------------------------------------------------------------
# Sharps conservation identity across a loss and its recovery
# ---------------------------------------------------------------------------


def _kitchen_with_a_sanitation_worker(api: ApiClient) -> dict:
    """A facility authorised for twelve sharps with one worker on the sanitation
    detail, which no lockdown cascade touches."""
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-CI2"},
        facility_overrides={
            "facility_code": "FAC-CI2",
            "sharps_authorized_count": 12,
        },
    )
    enrolment = fixtures.enrolled_worker(
        api, ctx["facility"]["id"], booking_number="BK-CI2-W01", sharps_eligible=True
    )
    worker = validate_success(
        api.assign_inmate_worker(
            enrolment["worker"]["id"],
            factories.assign_payload("SANITATION"),
            users.FOOD_SUPERVISOR,
        )
    )
    ctx["worker"] = worker
    return ctx


def _summary(api: ApiClient, facility_id: str) -> dict:
    summary = validate_success(api.get_sharps_summary(facility_id, users.OFFICER))
    assertions.assert_sharps_summary_conservation(summary)
    return summary


def test_the_conservation_identity_holds_at_every_step_of_a_loss_and_recovery(
    api: ApiClient,
) -> None:
    """On board plus issued plus unaccounted equals authorised after each of four
    writes, while the non-sharp tool stays outside every sharps counter.

    The PRD states: "**Tool issuance** is the sharps-control ledger, and it is
    governed by a conservation identity that must hold at every instant: for each
    facility, `sharps_on_board_count` plus `sharps_issued_count` plus
    `sharps_unaccounted_count` equals `sharps_authorized_count`. Only the three sharp
    classes participate in the sharps counters — `SHARP_KNIFE`, `MEAT_SAW` and
    `SCISSORS` — while a `NON_SHARP` tool is tracked as an issuance but is excluded
    from every sharps counter." It adds that `sharps_on_board_count` "falls by 1 on
    each issue, rises by 1 on each return including a recovery return out of
    `UNACCOUNTED`", and that a recovery return "additionally sets `recovered` to true".

    Design: Difficulty/compensating_invariant/sharps_conservation_identity_holds_across_unaccounted_and_recovery
    """
    ctx = _kitchen_with_a_sanitation_worker(api)
    facility_id = ctx["facility"]["id"]

    at_rest = _summary(api, facility_id)
    assert at_rest["sharps_authorized_count"] == 12
    assert at_rest["sharps_on_board_count"] == 12
    assert at_rest["sharps_issued_count"] == 0
    assert at_rest["sharps_unaccounted_count"] == 0

    scoop = fixtures.issued_tool(
        api,
        facility_id,
        ctx["worker"]["id"],
        tool_class="NON_SHARP",
        tool_serial="SCOOP-001",
        shadow_board_slot=7,
    )
    after_scoop = _summary(api, facility_id)
    assert after_scoop["sharps_on_board_count"] == 12
    assert after_scoop["sharps_issued_count"] == 0
    assert after_scoop["sharps_unaccounted_count"] == 0

    knife = fixtures.issued_tool(
        api,
        facility_id,
        ctx["worker"]["id"],
        tool_class="SHARP_KNIFE",
        tool_serial="KN-001",
        shadow_board_slot=1,
    )
    after_knife = _summary(api, facility_id)
    assert after_knife["sharps_on_board_count"] == 11
    assert after_knife["sharps_issued_count"] == 1
    assert after_knife["sharps_unaccounted_count"] == 0

    validate_success(
        api.declare_tool_unaccounted(
            knife["id"], factories.declare_unaccounted_payload(), users.OFFICER
        )
    )
    after_loss = _summary(api, facility_id)
    assert after_loss["sharps_on_board_count"] == 11
    assert after_loss["sharps_issued_count"] == 0
    assert after_loss["sharps_unaccounted_count"] == 1
    assert after_loss["open_sharps_discrepancy_count"] == 1
    assert after_loss["kitchen_posture"] == "LOCKDOWN"

    recovered = validate_success(
        api.return_tool_issuance(
            knife["id"], factories.tool_return_payload(1), users.OFFICER
        )
    )
    assert recovered["status"] == "RETURNED"
    assert recovered["recovered"] is True
    assertions.assert_instant(recovered["returned_at"], "2026-08-01T00:00:00Z")
    assert recovered["return_certified_by_user_id"] == users.user_id_of(users.OFFICER)

    after_recovery = _summary(api, facility_id)
    assert after_recovery["sharps_on_board_count"] == 12
    assert after_recovery["sharps_issued_count"] == 0
    assert after_recovery["sharps_unaccounted_count"] == 0
    assert after_recovery["open_sharps_discrepancy_count"] == 0
    assert after_recovery["kitchen_posture"] == "OPEN"

    still_out = fixtures.read_tool(api, scoop["id"])
    assert still_out["status"] == "ISSUED"
    assert still_out["recovered"] is False


def test_a_physical_audit_after_the_recovery_finds_no_shortfall(
    api: ApiClient,
) -> None:
    """The recovered knife is back on the board, so a count of twelve reconciles
    exactly and the audit records a zero shortfall.

    The PRD states: "The audit then overwrites `sharps_on_board_count` with
    `counted_on_board` wholesale, sets `sharps_audit_shortfall` to
    `sharps_authorized_count` minus the sum of `counted_on_board`,
    `sharps_issued_count` and `sharps_unaccounted_count`, stamps
    `last_sharps_audit_at` from the logical clock, recomputes `kitchen_posture` and
    increments `version` by 1." It also states that "Rows in `RETURNED` contribute to
    neither counter, whatever the `recovered` flag says", and that
    "`open_sharps_discrepancy_count` is `sharps_unaccounted_count` plus
    `sharps_audit_shortfall`".

    Design: Difficulty/compensating_invariant/sharps_conservation_identity_holds_across_unaccounted_and_recovery
    """
    ctx = _kitchen_with_a_sanitation_worker(api)
    facility_id = ctx["facility"]["id"]

    fixtures.issued_tool(
        api,
        facility_id,
        ctx["worker"]["id"],
        tool_class="NON_SHARP",
        tool_serial="SCOOP-001",
        shadow_board_slot=7,
    )
    knife = fixtures.issued_tool(
        api,
        facility_id,
        ctx["worker"]["id"],
        tool_class="SHARP_KNIFE",
        tool_serial="KN-001",
        shadow_board_slot=1,
    )
    validate_success(
        api.declare_tool_unaccounted(
            knife["id"], factories.declare_unaccounted_payload(), users.OFFICER
        )
    )
    validate_success(
        api.return_tool_issuance(
            knife["id"], factories.tool_return_payload(1), users.OFFICER
        )
    )

    before = fixtures.read_facility(api, facility_id)
    audited = validate_success(
        api.sharps_audit(facility_id, factories.sharps_audit_payload(12), users.OFFICER)
    )
    assertions.assert_facility(audited)
    assert audited["sharps_on_board_count"] == 12
    assert audited["sharps_audit_shortfall"] == 0
    assert audited["open_sharps_discrepancy_count"] == 0
    assertions.assert_instant(audited["last_sharps_audit_at"], "2026-08-01T00:00:00Z")
    assert audited["kitchen_posture"] == "OPEN"
    assertions.assert_version_bumped_by(before, audited)
    assertions.assert_sharps_conservation(audited)

    issuances, meta = validate_paginated(
        api.list_facility_tool_issuances(facility_id, users.OFFICER)
    )
    assert meta["total_count"] == 2
    statuses = {issuance["tool_serial"]: issuance["status"] for issuance in issuances}
    assert statuses == {"SCOOP-001": "ISSUED", "KN-001": "RETURNED"}

    worker = fixtures.read_worker(api, ctx["worker"]["id"])
    assert worker["assignment_status"] == "ASSIGNED"
    assert worker["work_area"] == "SANITATION"
