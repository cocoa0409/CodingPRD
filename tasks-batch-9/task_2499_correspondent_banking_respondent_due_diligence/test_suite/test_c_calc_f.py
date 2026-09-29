"""Corner queue - section calculations, part F: RFI service levels and the strike ledger."""
from test_helpers import (
    adjudicate_request,
    assert_instant_equals,
    dispatch_request,
    licensed_respondent,
    maintain_request,
    new_jurisdiction,
    raise_request,
    read_request,
    read_respondent,
    respond_request,
    set_clock,
)
from test_helpers.fixtures import ANALYST_ID


def _respondent():
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )["id"]


def test_rfi_response_sla_base_hours_for_a_high_severity_request(api):
    """Neither compression applies to an unrated respondent with a clean ledger, so the base
    window survives intact and the whole service-level triple is written only at dispatch.

    Design: Corner/calculations/rfi_response_sla_base_hours_for_a_high_severity_request
    """
    rid = _respondent()
    request = raise_request(rid, request_topic="OWNERSHIP_EVIDENCE", severity="HIGH")
    assert request["sla_hours"] is None
    assert request["due_at"] is None

    dispatched = dispatch_request(request["id"])

    assert dispatched["state"] == "SENT"
    assert dispatched["sla_hours"] == 72
    assert_instant_equals(dispatched["dispatched_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(dispatched["due_at"], "2026-08-04T00:00:00Z")
    assert dispatched["escalation_level"] == 1
    assert dispatched["reminder_count"] == 0
    assert dispatched["insufficiency_rounds"] == 0
    assert dispatched["retro_credited"] is False


def test_rfi_response_sla_strike_compression_lands_on_the_twelve_hour_floor(api):
    """Halving the shortest base lands exactly on the floor, so the floor cannot be lifting
    the value; the two earlier requests keep the window they were dispatched with.

    Design: Corner/calculations/rfi_response_sla_strike_compression_lands_on_the_twelve_hour_floor
    """
    rid = _respondent()
    first = raise_request(rid, request_topic="OWNERSHIP_EVIDENCE", severity="CRITICAL")
    second = raise_request(rid, request_topic="LICENSING_EVIDENCE", severity="CRITICAL")
    third = raise_request(rid, request_topic="NESTED_DISCLOSURE", severity="CRITICAL")
    dispatch_request(first["id"])
    dispatch_request(second["id"])
    set_clock("2026-08-03T00:00:00Z")
    maintain_request(first["id"], "MARK_OVERDUE")
    maintain_request(second["id"], "MARK_OVERDUE")

    dispatched = dispatch_request(third["id"])

    assert read_respondent(rid)["unresponsive_strikes"] == 2
    assert dispatched["sla_hours"] == 12
    assert_instant_equals(dispatched["due_at"], "2026-08-03T12:00:00Z")
    assert read_request(first["id"])["sla_hours"] == 24
    assert read_request(second["id"])["sla_hours"] == 24
    assert read_respondent(rid)["dd_state"] == "DD_IN_PROGRESS"


def test_unresponsive_strike_ledger_third_strike_restricts_the_respondent(api):
    """The third strike reaches the ledger's inclusive restriction threshold, so the
    restriction is driven by the ledger itself and the already-blocked posture is left alone.

    Design: Corner/calculations/unresponsive_strike_ledger_third_strike_restricts_the_respondent
    """
    rid = _respondent()
    requests = [
        raise_request(rid, request_topic=topic, severity="CRITICAL")
        for topic in ("OWNERSHIP_EVIDENCE", "LICENSING_EVIDENCE", "NESTED_DISCLOSURE")
    ]
    for request in requests:
        dispatch_request(request["id"])
    set_clock("2026-08-02T00:00:00Z")
    maintain_request(requests[0]["id"], "MARK_OVERDUE")
    maintain_request(requests[1]["id"], "MARK_OVERDUE")

    marked = maintain_request(requests[2]["id"], "MARK_OVERDUE")

    assert marked["state"] == "OVERDUE"
    respondent = read_respondent(rid)
    assert respondent["unresponsive_strikes"] == 3
    assert respondent["dd_state"] == "RESTRICTED"
    assert respondent["restriction_reason"] == "UNRESPONSIVE_STRIKES"
    assert respondent["payment_posture"] == "BLOCKED"


def test_unresponsive_strike_ledger_retro_credit_is_floored_at_zero(api):
    """The reminder count on the answered request exceeds the single strike it earned, so the
    credit clamps at zero instead of turning negative, and the credit flag is still stamped.

    Design: Corner/calculations/unresponsive_strike_ledger_retro_credit_is_floored_at_zero
    """
    rid = _respondent()
    request = raise_request(rid, request_topic="OWNERSHIP_EVIDENCE", severity="CRITICAL")
    dispatch_request(request["id"])
    set_clock("2026-08-03T00:00:00Z")
    maintain_request(request["id"], "MARK_OVERDUE")
    maintain_request(request["id"], "REMIND")
    maintain_request(request["id"], "REMIND")
    assert read_respondent(rid)["unresponsive_strikes"] == 1
    respond_request(request["id"], rid)

    accepted = adjudicate_request(request["id"], "ACCEPT", retro_credit=True)

    assert accepted["state"] == "ACCEPTED"
    assert accepted["reminder_count"] == 3
    assert accepted["retro_credited"] is True
    assert accepted["adjudicated_by_user_id"] == ANALYST_ID
    assert read_respondent(rid)["unresponsive_strikes"] == 0
