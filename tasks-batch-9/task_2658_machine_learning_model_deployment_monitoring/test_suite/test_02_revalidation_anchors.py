"""The two anchor instants of the periodic revalidation schedule."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assert_sweep_counters, assert_version_state
from test_helpers.api_client import ApiClient
from test_helpers.factories import (
    build_revalidation_disposition_payload,
)
from test_helpers.fixtures import (
    create_approved_dataset,
    create_approved_version,
    create_model,
    set_clock,
)
from test_helpers.test_users import ADMIN_1, APPROVER_1, APPROVER_2, MLE_1


def _approved_version_at_startup(api: ApiClient) -> dict:
    """One approved version, decided by u_appr_1 at the startup clock."""
    model = create_model(api, MLE_1, revalidation_interval_days=90)
    dataset = create_approved_dataset(api)
    return create_approved_version(
        api, model["id"], dataset["id"], MLE_1, APPROVER_1
    )


def _due_task(api: ApiClient, version_id: str) -> dict:
    rows = get_success_data(
        api.list_revalidation_tasks(
            APPROVER_1, {"model_version_id": version_id, "status": "DUE"}
        )
    )
    assert len(rows) == 1, f"expected exactly one DUE task, got {len(rows)}"
    return rows[0]


def test_approval_anchor_sets_the_first_due_date(api):
    """Approval anchors the first due date on approved_at.

    PRD 3.9: under the approval anchor "the next due date is the approval
    instant plus the entry's revalidation_interval_days whole days". The worked
    example approves at 2026-08-01T00:00:00Z with an interval of 90 days and
    lands on 2026-10-30T00:00:00Z, with the time-of-day component preserved.

    Design: Difficulty/dual_variant_calc/revalidation_due_date_approval_anchor_vs_pass_anchor
    """
    version = _approved_version_at_startup(api)

    assert version["approved_at"] == "2026-08-01T00:00:00Z"
    assert_version_state(
        version,
        approval_state="APPROVED",
        revalidation_due_at="2026-10-30T00:00:00Z",
    )


def test_sweep_copies_the_approval_anchored_due_date_onto_the_task(api):
    """The sweep copies the version's due date onto the task it creates.

    PRD 3.9: the sweep "creates one task per selected version with status DUE,
    due_at copied from the version's revalidation_due_at and swept_at stamped
    with the clock", and it selects approved versions whose due date is at or
    before the clock.

    Design: Difficulty/dual_variant_calc/revalidation_due_date_approval_anchor_vs_pass_anchor
    """
    version = _approved_version_at_startup(api)
    set_clock(api, "2026-11-01T00:00:00Z")

    sweep = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(sweep, created_count=1)

    task = _due_task(api, version["id"])
    assert task["due_at"] == "2026-10-30T00:00:00Z"
    assert task["swept_at"] == "2026-11-01T00:00:00Z"


def test_pass_anchor_shifts_the_whole_cadence_to_the_disposition_instant(api):
    """A late pass re-anchors the schedule on the disposition instant.

    PRD 3.9: under the pass anchor "the next due date is the clock at the
    moment of the passing disposition plus the interval in whole days — not the
    task's due_at, and not the version's original approved_at". Passing on
    2026-11-05T00:00:00Z therefore yields 2027-02-03T00:00:00Z rather than the
    cadence-preserving 2027-01-28T00:00:00Z.

    Design: Difficulty/dual_variant_calc/revalidation_due_date_approval_anchor_vs_pass_anchor
    """
    version = _approved_version_at_startup(api)
    set_clock(api, "2026-11-01T00:00:00Z")
    get_success_data(api.run_revalidation_sweep(ADMIN_1))
    task = _due_task(api, version["id"])

    get_success_data(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload("START_REVIEW"),
            APPROVER_2,
        )
    )
    set_clock(api, "2026-11-05T00:00:00Z")
    passed = get_success_data(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload(
                "PASS", findings="metrics stable, no action"
            ),
            APPROVER_2,
        )
    )

    assert passed["status"] == "PASSED"
    assert passed["decided_at"] == "2026-11-05T00:00:00Z"

    refreshed = get_success_data(api.get_model_version(version["id"], APPROVER_1))
    assert refreshed["revalidation_due_at"] == "2027-02-03T00:00:00Z"
    assert refreshed["revalidation_due_at"] != "2027-01-28T00:00:00Z"
    assert refreshed["approved_at"] == "2026-08-01T00:00:00Z"
