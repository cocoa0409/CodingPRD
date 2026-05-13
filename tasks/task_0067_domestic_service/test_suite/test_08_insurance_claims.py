"""Insurance claim opening side-effect from abnormal events (PRD §3.7).

NOTE on coverage: PRD §3.7 says an InsuranceClaim is opened automatically as
a side effect of an INJURY or PROPERTY_DAMAGE AbnormalEvent, but PRD §4
exposes only `GET /dsd/claims/{id}` — no claim-list endpoint — and PRD does
not commit to surfacing the new claim_id on the AbnormalEvent response.
Downstream tests that require operating on the claim (request-evidence, file,
mark-paid, archive) therefore have no PRD-mandated way to discover the
claim_id, so those tests live in test_11_difficulty_design.py under a
recipe that drives the claim via the audit-log discovery path made
unambiguous after `request-evidence` is called (which appends a
CLAIM_REPORTED audit row per PRD §3.7).
"""

import pytest

from test_helpers import (
    drive_order_to,
    report_abnormal,
    setup_order_in_state,
)


def test_injury_abnormal_event_sets_triggers_claim_true(api):
    """PRD §3.7: "When the category is INJURY or PROPERTY_DAMAGE, a derived
    triggers_claim flag is set to true and an InsuranceClaim is opened
    automatically as a side effect."

    Claim: AbnormalEvent created with category=INJURY has triggers_claim=True.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    event = report_abnormal(order["id"], category="INJURY")
    assert event["triggers_claim"] is True
    assert event["category"] == "INJURY"


def test_property_damage_abnormal_event_sets_triggers_claim_true(api):
    """PRD §3.7: "When the category is INJURY or PROPERTY_DAMAGE, a derived
    triggers_claim flag is set to true and an InsuranceClaim is opened
    automatically as a side effect."

    Claim: AbnormalEvent created with category=PROPERTY_DAMAGE has
    triggers_claim=True.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    event = report_abnormal(order["id"], category="PROPERTY_DAMAGE")
    assert event["triggers_claim"] is True
    assert event["category"] == "PROPERTY_DAMAGE"


def test_no_show_abnormal_event_does_not_trigger_claim(api):
    """PRD §3.7: "For NO_SHOW or OTHER categories, triggers_claim is false and
    no claim is opened."

    Claim: AbnormalEvent created with category=NO_SHOW has triggers_claim=False.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    event = report_abnormal(order["id"], category="NO_SHOW")
    assert event["triggers_claim"] is False
    assert event["category"] == "NO_SHOW"


def test_other_abnormal_event_does_not_trigger_claim(api):
    """PRD §3.7: "For NO_SHOW or OTHER categories, triggers_claim is false and
    no claim is opened."

    Claim: AbnormalEvent created with category=OTHER has triggers_claim=False.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    event = report_abnormal(order["id"], category="OTHER")
    assert event["triggers_claim"] is False
    assert event["category"] == "OTHER"


def test_abnormal_event_response_carries_required_fields(api):
    """PRD §3.7: "The report carries a reporter_role from the set PERSONNEL,
    CUSTOMER, or OPERATOR; a category of one of INJURY, PROPERTY_DAMAGE,
    NO_SHOW, or OTHER; and a free-text description."

    Claim: AbnormalEvent response carries reporter_role, category, and
    description.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    event = report_abnormal(
        order["id"], category="OTHER", description="Unit test report"
    )
    assert event["category"] == "OTHER"
    assert event["description"] == "Unit test report"
    assert event["reporter_role"] in ("PERSONNEL", "CUSTOMER", "OPERATOR")
