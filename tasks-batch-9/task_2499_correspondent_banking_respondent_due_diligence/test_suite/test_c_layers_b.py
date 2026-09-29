"""Corner queue - section cross_cutting_complexity_layers, part B: the operator sweep."""
from test_helpers import (
    assert_instant_equals,
    dispatch_request,
    new_jurisdiction,
    raise_request,
    read_refresh,
    read_request,
    read_respondent,
    schedule_refresh,
    set_clock,
    setup_approved_respondent,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _sent_request(respondent_id):
    request = raise_request(
        respondent_id, request_topic="ACTIVITY_EXPLANATION", severity="MEDIUM"
    )
    return dispatch_request(request["id"])


def test_the_refresh_sweep_applies_every_due_transition_in_one_pinned_run(api):
    """One operator call fans out across three respondents and two child workflows, the dry run
    names exactly the same audience while writing nothing, and the respondent whose window has
    not closed is left alone, which shows the sweep is selective rather than global.

    Design: Corner/cross_cutting_complexity_layers/the_refresh_sweep_applies_every_due_transition_in_one_pinned_run
    """
    _de()
    respondents = []
    for index, name in enumerate(("A Bank AG", "B Bank AG", "C Bank AG")):
        bundle = setup_approved_respondent(
            "DE", legal_name=name, swift_bic=f"BNK{index}DEFF",
            expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        )
        respondents.append(bundle["respondent"]["id"])
    rid_a, rid_b, rid_c = respondents

    cycle_a = schedule_refresh(rid_a, "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z")
    request_a = _sent_request(rid_a)
    request_b = _sent_request(rid_b)
    cycle_c = schedule_refresh(rid_c, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

    for request in (request_a, request_b):
        assert request["state"] == "SENT"
        assert request["sla_hours"] == 168
        assert_instant_equals(request["dispatched_at"], "2026-08-01T00:00:00Z")
        assert_instant_equals(request["due_at"], "2026-08-08T00:00:00Z")
    assert cycle_a["state"] == "SCHEDULED"
    assert cycle_c["state"] == "SCHEDULED"

    set_clock("2026-08-12T00:00:00Z")

    dry = validate_success(api.run_sweep({"dry_run": True}, ADMIN))
    dry_ids = [row["id"] for row in dry]
    assert rid_a in dry_ids
    assert rid_b in dry_ids
    assert rid_c not in dry_ids

    assert read_refresh(cycle_a["id"])["state"] == "SCHEDULED"
    assert read_refresh(cycle_a["id"])["lapsed_at"] is None
    assert read_request(request_a["id"])["state"] == "SENT"
    assert read_request(request_b["id"])["state"] == "SENT"
    for rid in respondents:
        assert read_respondent(rid)["unresponsive_strikes"] == 0

    wet = validate_success(api.run_sweep({"dry_run": False}, ADMIN))
    assert [row["id"] for row in wet] == dry_ids

    lapsed = read_refresh(cycle_a["id"])
    assert lapsed["state"] == "LAPSED"
    assert_instant_equals(lapsed["lapsed_at"], "2026-08-12T00:00:00Z")
    assert read_respondent(rid_a)["dd_state"] == "REFRESH_OVERDUE"

    for request_id in (request_a["id"], request_b["id"]):
        escalated = read_request(request_id)
        assert escalated["state"] == "ESCALATED"
        assert escalated["escalation_level"] == 3
    assert read_respondent(rid_a)["unresponsive_strikes"] == 1
    assert read_respondent(rid_b)["unresponsive_strikes"] == 1

    assert read_respondent(rid_c)["dd_state"] == "REFRESH_DUE"
    assert read_refresh(cycle_c["id"])["state"] == "SCHEDULED"
