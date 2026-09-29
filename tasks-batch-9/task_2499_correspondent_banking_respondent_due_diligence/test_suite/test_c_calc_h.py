"""Corner queue - section calculations, part H: notice period, wind-down cap, settlement."""
from test_helpers import (
    allocate,
    approve_plan,
    corridor,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    read_plan,
    read_respondent,
    submit_plan,
)
from test_helpers.fixtures import RM, RM_ID


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _respondent():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )["id"]


def test_notice_period_days_adds_the_obligation_extension_to_a_commercial_exit(api):
    """The longest base plus the obligation extension, with neither the prohibited reduction
    nor the sanctions override in play, and drafting alone moves the respondent to exiting.

    Design: Corner/calculations/notice_period_days_adds_the_obligation_extension_to_a_commercial_exit
    """
    rid = _respondent()

    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000,
    )

    assert plan["state"] == "DRAFT"
    assert plan["notice_period_days"] == 105
    assert plan["drafted_by_user_id"] == RM_ID
    assert plan["outstanding_obligation_cents"] == 1000
    assert plan["settled_cents"] == 0
    assert plan["allocation_round"] == 0
    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "EXITING"
    assert respondent["payment_posture"] == "WIND_DOWN_ONLY"


def test_wind_down_cap_forward_projected_uses_the_declared_monthly_volume(api):
    """The notice period converts to a fractional number of months and the whole product is
    rounded once, and the forward basis reads the declared volume with no activity on file.

    Design: Corner/calculations/wind_down_cap_forward_projected_uses_the_declared_monthly_volume
    """
    rid = _respondent()
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000,
    )
    submit_plan(plan["id"])

    approved = approve_plan(plan["id"])

    assert approved["state"] == "APPROVED"
    assert approved["notice_period_days"] == 105
    assert approved["wind_down_cap_usd"] == 1050000.00
    assert approved["wind_down_released_usd"] == 0.00
    assert approved["wind_down_end_at"] is None


def _allocatable_plan():
    """APPROVED plan over three equal corridors, so allocation ties break on jurisdiction code."""
    _de()
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    new_jurisdiction(
        jurisdiction_code="IT", name="Italy", basel_aml_index=4.5, corridor_risk_weight=1.1
    )
    rid = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )["id"]
    open_profile(
        rid,
        [corridor("FR", 100000.00, 20), corridor("IT", 100000.00, 20),
         corridor("DE", 100000.00, 20)],
    )
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000,
    )
    submit_plan(plan["id"])
    approve_plan(plan["id"])
    return plan


def test_settlement_allocation_puts_the_whole_residue_on_the_first_line(api):
    """Equal corridors force the code tie-break, and an amount that does not divide evenly
    proves the residue lands entirely on the first line rather than being spread.

    Design: Corner/calculations/settlement_allocation_puts_the_whole_residue_on_the_first_line
    """
    plan = _allocatable_plan()

    allocated = allocate(plan["id"], 100)

    lines = allocated["allocation_lines"]
    assert [line["jurisdiction_code"] for line in lines] == ["DE", "FR", "IT"]
    assert [line["line_cents"] for line in lines] == [34, 33, 33]
    assert allocated["settled_cents"] == 100
    assert allocated["outstanding_obligation_cents"] == 900
    assert allocated["settled_cents"] + allocated["outstanding_obligation_cents"] == 1000
    assert allocated["allocation_round"] == 1
    assert allocated["last_allocated_cents"] == 100


def test_settlement_allocation_reverse_restores_the_counters_exactly(api):
    """Reversing the exact last allocated amount is its precise inverse, and dropping back to
    round zero is what clears the lines and the reversal amount together.

    Design: Corner/calculations/settlement_allocation_reverse_restores_the_counters_exactly
    """
    plan = _allocatable_plan()
    allocate(plan["id"], 100)

    reversed_plan = allocate(plan["id"], 100, action="REVERSE")

    assert reversed_plan["settled_cents"] == 0
    assert reversed_plan["outstanding_obligation_cents"] == 1000
    assert reversed_plan["allocation_round"] == 0
    assert reversed_plan["allocation_lines"] == []
    assert reversed_plan["last_allocated_cents"] == 0
    assert read_plan(plan["id"])["allocation_lines"] == []
