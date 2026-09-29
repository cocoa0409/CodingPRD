"""Refurbishment between leases: quoting, segregation of duties and the custody loop."""
import pytest

from test_helpers import (
    DALLAS_DAMAGE,
    RURAL_DAMAGE,
    ApiErrorId,
    approve_refurbishment,
    assert_refurbishment_order,
    complete_refurbishment,
    finalize_assessment,
    get_branch,
    get_refurbishment_order,
    get_unit,
    make_branch_ops_headers,
    make_fleet_admin_headers,
    make_leasing_agent_headers,
    quote_refurbishment,
    reject_refurbishment,
    setup_dallas_finalized_assessment,
    setup_dallas_submitted_assessment,
    setup_rural_quoted_refurbishment,
    setup_rural_refurbishing_unit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_lease_payload,
    create_refurbishment_order_payload,
)

RURAL_SITE = "9 County Road 12, Rural TX"


# ─── The unit closes its refurbishment cycle ─────────────────────────────────

def test_unit_returns_to_in_fleet_after_a_full_refurbishment_cycle(api):
    """PRD §3.3: "The unit's `status` traces a closed loop rather than a one-way
    lifecycle: `IN_FLEET → RESERVED → IN_TRANSIT → ON_LEASE → RETURNED →
    REFURBISHING → IN_FLEET`."
    PRD §3.9: "The unit moves `REFURBISHING → IN_FLEET`; its `condition_grade`
    is rewritten to the order's `target_condition_grade`; its `refurb_cycles` is
    incremented by one; its `accumulated_damage_cents` is increased by the
    `chargeable_cents` of the assessment behind the order, which is how a
    building's lifetime damage burden is tracked across tenancies; its
    `latest_quote_estimate_cents` is reset to 0; and its `version` is
    incremented."
    PRD §3.3: "A fifth system-managed field, `installed_config_id`, records
    which floorplan configuration is physically installed in the unit; it is
    null until a delivery-and-install job completes, at which point it is
    written with that lease's configuration — and it is never cleared
    afterwards, so a unit back in the yard still reports the last floorplan it
    wore."

    Design: Difficulty/non_linear_state_machine/unit_status_closes_the_refurbishment_cycle
    """
    ctx = setup_dallas_finalized_assessment()
    assert get_unit(ctx["unit"]["id"])["status"] == "RETURNED"

    order = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        scope="STANDARD", labor_hours=12.5, parts_cost_cents=143_700,
        target_condition_grade="B")
    approve_refurbishment(order["id"])
    completed = complete_refurbishment(order["id"], ctx["branch"]["id"], 465_900)

    assert completed["status"] == "COMPLETED", (
        f"Expected COMPLETED, got {completed['status']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"the loop must close back at IN_FLEET, got {unit['status']}")
    assert unit["condition_grade"] == "B", (
        f"the grade must be rewritten to the order's target, got "
        f"{unit['condition_grade']}")
    assert unit["refurb_cycles"] == 1, (
        f"Expected refurb_cycles 1, got {unit['refurb_cycles']}")
    assert unit["accumulated_damage_cents"] == DALLAS_DAMAGE["CHARGEABLE_CENTS"], (
        f"the finalized chargeback must be absorbed, expected 358250, got "
        f"{unit['accumulated_damage_cents']}")
    assert unit["latest_quote_estimate_cents"] == 0, (
        f"no quote is open any more, got {unit['latest_quote_estimate_cents']}")
    assert unit["installed_config_id"] == ctx["config"]["id"], (
        f"the last floorplan worn is never cleared, got "
        f"{unit['installed_config_id']}")


def test_refurbishment_completion_recomputes_the_branch_counters(api):
    """PRD §3.9: "The order's `estimated_cost_cents` is the sum of three
    separately rounded lines."
    PRD §3.9: "The recovery line takes sixty percent of the assessment's
    `chargeable_cents` and rounds half up — the shop expects to recover most,
    but not all, of what the lessee was charged."
    PRD §3.9: "Because the unit re-entered `IN_FLEET`, the branch's
    `units_available` rises by one, and because that count changed,
    `utilization_pct` is recomputed."


    PRD §3.9: "The labour line takes the estimated `labor_hours`, multiplies by
    the servicing branch's `labor_rate_cents_per_hour` and by a scope factor of
    0.45 for `COSMETIC`, 1.00 for `STANDARD`, or 1.85 for `FULL`, and rounds
    half up to a whole cent. The parts line multiplies the estimated
    `parts_cost_cents` by the same scope factor and rounds half up. The recovery
    line takes sixty percent of the assessment's `chargeable_cents` and rounds
    half up — the shop expects to recover most, but not all, of what the lessee
    was charged."

    Design: Difficulty/non_linear_state_machine/unit_status_closes_the_refurbishment_cycle
    """
    ctx = setup_dallas_finalized_assessment()

    order = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        scope="STANDARD", labor_hours=12.5, parts_cost_cents=143_700,
        target_condition_grade="B")
    assert_refurbishment_order(order)
    assert order["estimated_cost_cents"] == 473_650, (
        f"Expected 115000 labour + 143700 parts + 214950 recovery = 473650, got "
        f"{order['estimated_cost_cents']}")

    approve_refurbishment(order["id"])
    complete_refurbishment(order["id"], ctx["branch"]["id"], 465_900)

    branch = get_branch(ctx["branch"]["id"])
    assert branch["units_in_yard"] == 1, (
        f"the refurbished unit is back on the yard, got {branch['units_in_yard']}")
    assert branch["units_available"] == 1, (
        f"units_available must rise by one on re-entry to IN_FLEET, got "
        f"{branch['units_available']}")
    assert float(branch["utilization_pct"]) == pytest.approx(0.00, abs=0.005), (
        f"the branch's only assigned unit is leasable again, so utilization is "
        f"0.00; got {branch['utilization_pct']}")


# ─── The quote is gated on the assessment's state ────────────────────────────

def test_refurbishment_quote_is_refused_while_the_assessment_is_submitted(api):
    """PRD §3.9: "The assessment named must have reached `FINALIZED`, or the
    quote is refused with `ERR_ASSESSMENT_NOT_FINALIZED`, and it must be an
    assessment of the very unit being refurbished, or the quote is refused with
    `ERR_ENTITY_LINK_MISMATCH`."
    PRD §3.9: "Finalization moves the assessment `SUBMITTED → FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/refurbishment_quote_gated_on_damage_assessment_state
    """
    ctx = setup_dallas_submitted_assessment()
    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "RETURNED"
    assert ctx["assessment"]["status"] == "SUBMITTED"

    response = api.create_refurbishment_order(
        create_refurbishment_order_payload(
            unit["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
            unit["version"], scope="STANDARD", labor_hours=12.5,
            parts_cost_cents=143_700, target_condition_grade="B"),
        make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value)

    _, meta = validate_paginated(api.list_refurbishment_orders(
        make_fleet_admin_headers(), params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 0, (
        f"the refused quote must not persist, got {meta['total_count']}")
    assert get_unit(unit["id"])["latest_quote_estimate_cents"] == 0


def test_refurbishment_quote_is_accepted_once_the_assessment_is_finalized(api):
    """PRD §3.9: "The assessment named must have reached `FINALIZED`, or the
    quote is refused with `ERR_ASSESSMENT_NOT_FINALIZED`, and it must be an
    assessment of the very unit being refurbished, or the quote is refused with
    `ERR_ENTITY_LINK_MISMATCH`."
    PRD §3.9: "Any refurbishment order already sitting at `QUOTED` on that unit
    moves `QUOTED → SUPERSEDED`; the unit's `latest_quote_estimate_cents` is set
    to the **new** order's `estimated_cost_cents`; and the unit's `version` is
    incremented by one."
    PRD §3.9: "The unit's `status` is deliberately not changed: the building
    stays `RETURNED` until someone with spending authority approves the work."

    Design: Difficulty/cross_entity_state_dependency/refurbishment_quote_gated_on_damage_assessment_state
    """
    ctx = setup_dallas_submitted_assessment()
    before = get_unit(ctx["unit"]["id"])
    validate_error(
        api.create_refurbishment_order(
            create_refurbishment_order_payload(
                before["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
                before["version"], scope="STANDARD", labor_hours=12.5,
                parts_cost_cents=143_700, target_condition_grade="B"),
            make_branch_ops_headers(ctx["branch"]["id"])),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value)

    finalized = finalize_assessment(ctx["assessment"]["id"], "C")
    assert finalized["chargeable_cents"] == DALLAS_DAMAGE["CHARGEABLE_CENTS"]

    after = get_unit(ctx["unit"]["id"])
    order = validate_success(api.create_refurbishment_order(
        create_refurbishment_order_payload(
            after["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
            after["version"], scope="STANDARD", labor_hours=12.5,
            parts_cost_cents=143_700, target_condition_grade="B"),
        make_branch_ops_headers(ctx["branch"]["id"])), 201)

    assert order["status"] == "QUOTED", (
        f"Expected QUOTED, got {order['status']}")
    assert order["estimated_cost_cents"] == 473_650, (
        f"only a finalized assessment contributes the 214950 recovery leg; "
        f"expected 473650, got {order['estimated_cost_cents']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["latest_quote_estimate_cents"] == 473_650, (
        f"the newest open quote must be published on the unit, got "
        f"{unit['latest_quote_estimate_cents']}")
    assert unit["status"] == "RETURNED", (
        f"quoting never moves the unit, got {unit['status']}")

    _, meta = validate_paginated(api.list_refurbishment_orders(
        make_fleet_admin_headers(), params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 1, (
        f"only the accepted quote persisted, got {meta['total_count']}")


# ─── Corner coverage ─────────────────────────────────────────────────────────

def test_rejecting_refurbishment_returns_the_unit_to_the_fleet_unchanged(api):
    """PRD §3.9: "The order moves `QUOTED → REJECTED`, the reason is stored, the
    unit goes straight `RETURNED → IN_FLEET` and becomes leasable again as-is,
    the unit's `latest_quote_estimate_cents` is reset to 0, the unit's `version`
    is incremented, and the branch's `units_available` and `utilization_pct` are
    recomputed."
    PRD §3.9: "Nothing else moves: there is no grade change, no increment to
    `refurb_cycles`, and no damage absorbed into `accumulated_damage_cents`."
    PRD §3.9: "The labour line takes the estimated `labor_hours`, multiplies by
    the servicing branch's `labor_rate_cents_per_hour` and by a scope factor of
    0.45 for `COSMETIC`, 1.00 for `STANDARD`, or 1.85 for `FULL`, and rounds
    half up to a whole cent."

    Design: Corner/state_machines/reject_refurbishment_returns_unit_to_fleet_without_grade_change
    """
    ctx = setup_rural_quoted_refurbishment()
    assert ctx["assessment"]["chargeable_cents"] == RURAL_DAMAGE["CHARGEABLE_CENTS"]
    assert ctx["order"]["estimated_cost_cents"] == 194_124, (
        f"Expected 51750 labour + 64674 parts + 77700 recovery = 194124, got "
        f"{ctx['order']['estimated_cost_cents']}")

    rejected = reject_refurbishment(ctx["order"]["id"], "Unit is leasable as-is")
    assert rejected["status"] == "REJECTED", (
        f"Expected REJECTED, got {rejected['status']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"declining sends the unit straight back to the fleet, got "
        f"{unit['status']}")
    assert unit["condition_grade"] == "A", (
        f"there is no grade change on a decline, got {unit['condition_grade']}")
    assert unit["refurb_cycles"] == 0, (
        f"a declined order is not a cycle, got {unit['refurb_cycles']}")
    assert unit["accumulated_damage_cents"] == 0, (
        f"no damage is absorbed on a decline, got "
        f"{unit['accumulated_damage_cents']}")
    assert unit["latest_quote_estimate_cents"] == 0, (
        f"the open quote is retired, got {unit['latest_quote_estimate_cents']}")

    branch = get_branch(ctx["branch"]["id"])
    assert branch["units_available"] == 1, (
        f"the unit is leasable again, got {branch['units_available']}")
    assert float(branch["utilization_pct"]) == pytest.approx(0.00, abs=0.005), (
        f"Expected utilization 0.00, got {branch['utilization_pct']}")


def test_booking_a_refurbishing_unit_is_refused(api):
    """PRD §3.4: "And the unit must not be in the shop: a unit whose status is
    `REFURBISHING` has no committed return date and is rejected with
    `ERR_UNIT_NOT_AVAILABLE`, while a unit in any other status is bookable
    forward and is judged instead by the occupancy calendar below."
    PRD §3.9: "On approval the order moves `QUOTED → APPROVED`, the approver's
    identifier is stored as `approved_by_user_id`, the unit moves
    `RETURNED → REFURBISHING`, and the unit's `version` is incremented."

    Design: Corner/errors/booking_a_refurbishing_unit_returns_unit_not_available
    """
    ctx = setup_rural_refurbishing_unit()

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "REFURBISHING", (
        f"Expected the approved order to put the unit in the shop, got "
        f"{unit['status']}")
    order = get_refurbishment_order(ctx["order"]["id"])
    assert order["status"] == "APPROVED"
    assert order["approved_by_user_id"] == "admin-ops-2", (
        f"the approver's identifier must be stored, got "
        f"{order['approved_by_user_id']}")

    # A start date years clear of every existing interval still fails, because
    # the shop status is decided before the calendar.
    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], unit["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address="44 Far Road, Rural TX",
                             start_date="2028-01-01", term_months=6),
        make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 1, (
        f"the refused quote must not persist, got {meta['total_count']}")


def test_the_assessor_cannot_approve_the_refurbishment_they_authored(api):
    """PRD §3.9: "Approval requires the order to be `QUOTED` — approving or
    declining an order that has already left `QUOTED`, such as rejecting one
    that is already `APPROVED`, is refused with `ERR_INVALID_STATE` — the
    underlying assessment to be `FINALIZED`, failing which the approval is
    refused with `ERR_ASSESSMENT_NOT_FINALIZED`, and the unit to be `RETURNED`;
    it further requires that the approving administrator's `X-User-ID` differs
    from the `assessor_user_id` recorded on that assessment, and an operator who
    tries to authorize spend against damage they themselves documented is
    refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "On approval the order moves `QUOTED → APPROVED`, the approver's
    identifier is stored as `approved_by_user_id`, the unit moves
    `RETURNED → REFURBISHING`, and the unit's `version` is incremented."

    Design: Corner/rbac/assessor_cannot_approve_the_refurbishment_they_authored
    """
    ctx = setup_rural_quoted_refurbishment()
    assert ctx["assessment"]["assessor_user_id"] == "inspector-9", (
        f"the inspector's handle must be recorded, got "
        f"{ctx['assessment']['assessor_user_id']}")

    same_operator = api.approve_refurbishment_order(
        ctx["order"]["id"], make_fleet_admin_headers("inspector-9"))
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    assert get_refurbishment_order(ctx["order"]["id"])["status"] == "QUOTED", (
        "the refused approval must leave the order QUOTED")
    assert get_unit(ctx["unit"]["id"])["status"] == "RETURNED", (
        "the refused approval must leave the unit RETURNED")

    approved = validate_success(api.approve_refurbishment_order(
        ctx["order"]["id"], make_fleet_admin_headers("admin-ops-2")))
    assert approved["status"] == "APPROVED", (
        f"a different administrator may authorize the spend, got "
        f"{approved['status']}")
    assert approved["approved_by_user_id"] == "admin-ops-2", (
        f"Expected the approver's identifier stored, got "
        f"{approved['approved_by_user_id']}")
    assert get_unit(ctx["unit"]["id"])["status"] == "REFURBISHING", (
        "approval takes the unit RETURNED -> REFURBISHING")
