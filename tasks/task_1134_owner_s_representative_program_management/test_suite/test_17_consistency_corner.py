"""Queue B — consistency_model section corner tests."""
from test_helpers import (
    api_client, get_success_data,
    create_active_program, create_drawdown,
    pm_headers,
)


def test_immediate_visibility_after_drawdown_create(api):
    """PRD §3.5: "Creation immediately moves the pool (reserved up, available
    down by the amount), recomputes posture, and refreshes every DRAFT
    OwnerReport for the program."

    Design: Corner/consistency_model/immediate_visibility_after_drawdown_create
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-IMM",
    )
    pid = prog["id"]
    dd = create_drawdown(pid, 400_000, purpose="p")
    assert dd["status"] == "RESERVED"
    # Read-after-write reflects the pool move immediately
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_reserved_cents"] == 400_000
    assert p["contingency_available_cents"] == 600_000
