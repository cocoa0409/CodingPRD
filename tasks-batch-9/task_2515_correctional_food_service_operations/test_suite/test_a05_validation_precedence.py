"""Requests engineered to fail two rules at once, to pin the reported code.

The rejection ladder is part of the contract, so each fixture below violates two
gates simultaneously and then, after the earlier violation is cleared, replays the
same request to prove the later gate was live all along.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Terminal state beats the clinical-indication requirement
# ---------------------------------------------------------------------------


def _two_medical_orders_one_revoked(api: ApiClient) -> dict:
    """Two therapeutic orders on one inmate, neither carrying a clinical
    indication, over disjoint half-open windows. The first is revoked."""
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-PP1"},
        facility_overrides={
            "facility_code": "FAC-PP1",
            "sharps_authorized_count": 12,
        },
    )
    inmate = fixtures.create_inmate(api, ctx["facility"]["id"])
    order_a = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="DIABETIC_2000",
                clinical_indication=factories.OMIT,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    revoked = validate_success(
        api.revoke_diet_order(
            order_a["id"],
            {"revocation_reason": "Provider withdrew the order"},
            users.DIETITIAN,
        )
    )
    inmate = validate_success(api.get_inmate(inmate["id"], users.OFFICER))
    order_b = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="DIABETIC_2000",
                clinical_indication=factories.OMIT,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    ctx["inmate"] = inmate
    ctx["order_a"] = revoked
    ctx["order_b"] = order_b
    return ctx


def test_verifying_a_revoked_order_reports_terminal_state_not_the_missing_indication(
    api: ApiClient,
) -> None:
    """Both gates are violated at once and the earlier ladder rung wins.

    The PRD states: "a request that fails two checks always reports the earlier
    one", places at rung 16 the check that "The target resource is not already
    sitting in a terminal state for the machine being driven, else
    `ERR_ALREADY_TERMINAL` (HTTP 409)" whose terminal states include "a diet order
    in `EXPIRED` or `REVOKED`", and places the clinical-indication requirement
    "Beyond step 18". The revoked order therefore reports the terminal state even
    though its `clinical_indication` is blank.

    Design: Difficulty/priority_pair_validation_conflict/revoked_medical_order_verify_returns_already_terminal_not_clinical_indication_required
    """
    ctx = _two_medical_orders_one_revoked(api)

    validate_error(
        api.verify_diet_order(ctx["order_a"]["id"], users.MEDICAL),
        ApiErrorId.ERR_ALREADY_TERMINAL.value,
        409,
    )

    order_a = fixtures.read_diet_order(api, ctx["order_a"]["id"])
    assert order_a["status"] == "REVOKED"
    assert order_a["verified_by_user_id"] is None
    assert order_a["verified_at"] is None
    assert order_a["verification_expires_at"] is None


def test_a_live_order_with_the_same_defect_reports_the_missing_indication(
    api: ApiClient,
) -> None:
    """With the terminal-state rung cleared, the later gate fires on an identically
    shaped order.

    The PRD states: "A `MEDICAL` order must carry a non-empty `clinical_indication`
    by the time it is verified; a blank one is `ERR_CLINICAL_INDICATION_REQUIRED`
    with HTTP 422." The second order is still in `PENDING_VERIFICATION`, so the
    ladder reaches that gate and stops there.

    Design: Difficulty/priority_pair_validation_conflict/revoked_medical_order_verify_returns_already_terminal_not_clinical_indication_required
    """
    ctx = _two_medical_orders_one_revoked(api)

    validate_error(
        api.verify_diet_order(ctx["order_b"]["id"], users.MEDICAL),
        ApiErrorId.ERR_CLINICAL_INDICATION_REQUIRED.value,
        422,
    )

    order_b = fixtures.read_diet_order(api, ctx["order_b"]["id"])
    assert order_b["status"] == "PENDING_VERIFICATION"
    assert order_b["verified_by_user_id"] is None

    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assert inmate["active_diet_order_count"] == 0


# ---------------------------------------------------------------------------
# Kitchen posture beats the tray budget
# ---------------------------------------------------------------------------


def _locked_down_kitchen_with_a_locked_forecast(api: ApiClient) -> dict:
    """A facility in LOCKDOWN because a knife is unaccounted for, holding a locked
    forecast whose whole tray budget is 22."""
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-PP2"},
        facility_overrides={
            "facility_code": "FAC-PP2",
            "sharps_authorized_count": 12,
        },
    )
    assert ctx["forecast"]["total_forecast_trays"] == 22
    facility_id = ctx["facility"]["id"]

    enrolment = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-PP2-W01", sharps_eligible=True
    )
    worker = validate_success(
        api.assign_inmate_worker(
            enrolment["worker"]["id"],
            factories.assign_payload("COOK_CHILL"),
            users.FOOD_SUPERVISOR,
        )
    )
    issuance = fixtures.issued_tool(
        api,
        facility_id,
        worker["id"],
        tool_class="SHARP_KNIFE",
        tool_serial="KN-001",
        shadow_board_slot=1,
    )
    validate_success(
        api.declare_tool_unaccounted(
            issuance["id"], factories.declare_unaccounted_payload(), users.OFFICER
        )
    )
    facility = fixtures.read_facility(api, facility_id)
    assert facility["kitchen_posture"] == "LOCKDOWN"

    ctx["facility"] = facility
    ctx["issuance"] = issuance
    return ctx


def _oversized_batch_payload(api: ApiClient, ctx: dict) -> dict:
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    return factories.production_batch_payload(
        facility["id"],
        ctx["forecast"]["id"],
        facility["version"],
        planned_trays=999,
    )


def test_the_posture_gate_is_reported_before_the_tray_budget(api: ApiClient) -> None:
    """A batch that is both unsafe and unaffordable reports the safety gate.

    The PRD orders the gates beyond the numbered ladder as "the kitchen posture gate
    (`ERR_KITCHEN_POSTURE_BLOCKED`); the open-sharps gate on tool issue ... the tray
    budget (`ERR_TRAY_BUDGET_EXCEEDED`); and finally the cost ceiling", and requires
    of a batch creation that "The facility's `kitchen_posture` must read `OPEN`,
    otherwise `ERR_KITCHEN_POSTURE_BLOCKED`." No partial write may survive the
    rejection.

    Design: Difficulty/priority_pair_validation_conflict/locked_down_kitchen_beats_tray_budget_on_production_batch_create
    """
    ctx = _locked_down_kitchen_with_a_locked_forecast(api)

    validate_error(
        api.create_production_batch(
            _oversized_batch_payload(api, ctx), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_KITCHEN_POSTURE_BLOCKED.value,
        409,
    )

    batches, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"facility_id": ctx["facility"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected create must leave no batch behind"
    assert batches == []


def test_recovering_the_knife_exposes_the_tray_budget_violation(api: ApiClient) -> None:
    """Once the posture returns to OPEN the same oversized batch reports the fiscal
    gate instead, proving that gate was live all along.

    The PRD states: "The sum of `planned_trays` across every batch tied to the same
    forecast whose `production_stage` is not `DISCARDED`, counting the batch now
    being created, may not exceed that forecast's `total_forecast_trays`. Exceeding
    it reports `ERR_TRAY_BUDGET_EXCEEDED`." It also states that recovering the tool
    "additionally sets `recovered` to true" and "recomputes `kitchen_posture` — which
    returns to `OPEN` only when `open_sharps_discrepancy_count` is 0 and no other
    restricting condition holds".

    Design: Difficulty/priority_pair_validation_conflict/locked_down_kitchen_beats_tray_budget_on_production_batch_create
    """
    ctx = _locked_down_kitchen_with_a_locked_forecast(api)

    validate_error(
        api.create_production_batch(
            _oversized_batch_payload(api, ctx), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_KITCHEN_POSTURE_BLOCKED.value,
        409,
    )

    returned = validate_success(
        api.return_tool_issuance(
            ctx["issuance"]["id"], factories.tool_return_payload(1), users.OFFICER
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["recovered"] is True

    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["kitchen_posture"] == "OPEN"
    assert facility["open_sharps_discrepancy_count"] == 0
    assertions.assert_sharps_conservation(facility)

    validate_error(
        api.create_production_batch(
            _oversized_batch_payload(api, ctx), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_TRAY_BUDGET_EXCEEDED.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"facility_id": ctx["facility"]["id"]}
        )
    )
    assert meta["total_count"] == 0
