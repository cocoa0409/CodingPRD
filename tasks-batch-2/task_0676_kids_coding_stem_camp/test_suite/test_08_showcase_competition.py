"""Showcase judging lifecycle: rank assignment ordering, post-results precondition,
and cancellation cascade.

Covers corner state-machine instances post_results_assigns_rank_score_desc_created_at_tiebreak
and post_results_with_unscored_accepted_returns_error, plus the cross-cutting
showcase_cancel_withdraws_entries_cascade instance.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    setup_catalogue, create_guardian, create_member,
    submit_entry, accept_entry, score_entry, set_clock,
    TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


def _open_showcase(center_id, program_id, capacity=5):
    created = get_success_data(api_client.create_showcase(
        {"center_id": center_id, "program_id": program_id, "min_belt_rank": 1,
         "capacity": capacity, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    return get_success_data(api_client.open_showcase(created["id"], ADMIN))


# ─── Corner / state_machines / post_results_assigns_rank_score_desc_created_at_tiebreak ─
def test_post_results_ranks_score_desc_then_created_at_asc(api):
    """PRD §3.8: "Posting results assigns each scored entry a final placement `rank`,
    ordered by `score` descending and then by `created_at` ascending, numbering 1 through N"

    Design: Corner/state_machines/post_results_assigns_rank_score_desc_created_at_tiebreak
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    m3 = create_member(guardian["id"], program["id"])
    showcase = _open_showcase(center["id"], program["id"])
    e1 = submit_entry(guardian["id"], showcase["id"], m1["id"])  # created first
    accept_entry(e1["id"], showcase["id"])
    e2 = submit_entry(guardian["id"], showcase["id"], m2["id"])  # created second
    accept_entry(e2["id"], showcase["id"])
    e3 = submit_entry(guardian["id"], showcase["id"], m3["id"])  # created third
    accept_entry(e3["id"], showcase["id"])
    set_clock("2026-05-10T12:00:01Z")
    api.close_showcase_entries(showcase["id"], ADMIN)
    score_entry(e1["id"], 90)
    score_entry(e2["id"], 90)
    score_entry(e3["id"], 95)
    api.post_showcase_results(showcase["id"], ADMIN)
    after_e1 = get_success_data(api.get_showcase_entry(e1["id"], ADMIN))
    after_e2 = get_success_data(api.get_showcase_entry(e2["id"], ADMIN))
    after_e3 = get_success_data(api.get_showcase_entry(e3["id"], ADMIN))
    assert after_e3["rank"] == 1  # score 95 highest
    assert after_e1["rank"] == 2  # score 90, created earlier
    assert after_e2["rank"] == 3  # score 90, created later


def test_post_results_completes_showcase(api):
    """PRD §3.8: "Posting results transitions the showcase `JUDGING → COMPLETED`; it is
    permitted only from `JUDGING` and only when every accepted entry has reached `SCORED`"

    Design: Corner/state_machines/post_results_assigns_rank_score_desc_created_at_tiebreak
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    showcase = _open_showcase(center["id"], program["id"])
    e1 = submit_entry(guardian["id"], showcase["id"], m1["id"])
    accept_entry(e1["id"], showcase["id"])
    set_clock("2026-05-10T12:00:01Z")
    api.close_showcase_entries(showcase["id"], ADMIN)
    score_entry(e1["id"], 88)
    completed = get_success_data(api.post_showcase_results(showcase["id"], ADMIN))
    assert completed["status"] == "COMPLETED"


# ─── Corner / state_machines / post_results_with_unscored_accepted_returns_error ─
def test_post_results_with_unscored_accepted_rejected(api):
    """PRD §3.8: "if any accepted entry remains un-scored it is rejected with
    `ERR_UNSCORED_ENTRIES_REMAIN`, HTTP 409"

    Design: Corner/state_machines/post_results_with_unscored_accepted_returns_error
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    showcase = _open_showcase(center["id"], program["id"])
    e1 = submit_entry(guardian["id"], showcase["id"], m1["id"])
    accept_entry(e1["id"], showcase["id"])
    set_clock("2026-05-10T12:00:01Z")
    api.close_showcase_entries(showcase["id"], ADMIN)
    # Entry remains ACCEPTED (unscored).
    res = api.post_showcase_results(showcase["id"], ADMIN)
    validate_error(res, "ERR_UNSCORED_ENTRIES_REMAIN")


# ─── Corner / cross_cutting_complexity_layers / showcase_cancel_withdraws_entries_cascade ─
def test_showcase_cancel_withdraws_accepted_entry(api):
    """PRD §3.8: "cancellation drives every non-terminal entry — those in `SUBMITTED`,
    `ACCEPTED`, or `SCORED` — to `WITHDRAWN`, sets the `accepted_entry_count` to 0, and
    increments the showcase's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/showcase_cancel_withdraws_entries_cascade
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    showcase = _open_showcase(center["id"], program["id"])
    e1 = submit_entry(guardian["id"], showcase["id"], m1["id"])
    accept_entry(e1["id"], showcase["id"])  # accepted_entry_count -> 1
    api.cancel_showcase(showcase["id"], ADMIN)
    entry_after = get_success_data(api.get_showcase_entry(e1["id"], ADMIN))
    showcase_after = get_success_data(api.get_showcase(showcase["id"], ADMIN))
    assert entry_after["status"] == "WITHDRAWN"
    assert showcase_after["accepted_entry_count"] == 0
