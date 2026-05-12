"""Evidence collection, chain-of-custody integrity, and the
rebuttal-cycle state machine.

PRD §3.5.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    DEFAULT_NOW,
    add_minutes,
    advance_clock,
    api_client,
    append_custody,
    assert_evidence,
    assert_rebuttal,
    collect_evidence,
    create_custody_event_payload,
    create_evidence_payload,
    create_rebuttal_payload,
    setup_submitted_evidence,
    setup_three_lawyers_and_active_case,
    validate_error,
    validate_success,
)


T0 = DEFAULT_NOW


# ---------------------------------------------------------------------------
# Evidence creation: initial custody event auto-appended
# ---------------------------------------------------------------------------
def test_evidence_creation_appends_initial_custody_event(api):
    """PRD §3.5: 'On creation, the system auto-appends an initial
    CustodyEvent whose action is COLLECTED, whose actor_lawyer_id is the
    supplied collected_by_lawyer_id, and whose occurred_at equals
    collected_at.'
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(T0)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=T0,
        actor_headers=bundle["partner_headers"],
    )
    assert_evidence(e)
    assert e["status"] == "COLLECTED"
    assert e["submitted_at"] is None
    assert e["rebuttal_count"] == 0


# ---------------------------------------------------------------------------
# Custody chain: strictly increasing occurred_at
# ---------------------------------------------------------------------------
def test_custody_event_equal_occurred_at_rejected(api):
    """PRD §3.5: 'The custody chain integrity rule is strict: every new
    event's occurred_at must be strictly greater than the most recent
    event's occurred_at for the same evidence — equality is forbidden,
    not merely uncommon. A violation surfaces ERR_CUSTODY_CHAIN_BROKEN.'
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(T0)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=T0,
        actor_headers=bundle["partner_headers"],
    )
    # Same occurred_at as the auto-appended COLLECTED event ⇒ rejected.
    payload = create_custody_event_payload(
        actor_lawyer_id=bundle["partner"]["id"],
        action="EXAMINED",
        occurred_at=T0,
    )
    res = api.append_custody_event(
        e["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_CUSTODY_CHAIN_BROKEN", expected_status=409)


def test_custody_event_earlier_occurred_at_rejected(api):
    """PRD §3.5: 'every new event's occurred_at must be strictly greater
    than the most recent event's occurred_at for the same evidence —
    equality is forbidden, not merely uncommon. A violation surfaces
    ERR_CUSTODY_CHAIN_BROKEN.'
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(T0)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=T0,
        actor_headers=bundle["partner_headers"],
    )
    payload = create_custody_event_payload(
        actor_lawyer_id=bundle["partner"]["id"],
        action="EXAMINED",
        occurred_at=add_minutes(T0, -5),
    )
    res = api.append_custody_event(
        e["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_CUSTODY_CHAIN_BROKEN", expected_status=409)


# ---------------------------------------------------------------------------
# Submission preconditions
# ---------------------------------------------------------------------------
def test_submit_after_returned_rejected(api):
    """PRD §3.5: 'the custody chain to be unbroken (every prior
    CustodyEvent.occurred_at strictly increasing and the most recent
    action not equal to RETURNED)'

    Claim: latest custody action == RETURNED ⇒ submit rejected with
    ERR_CUSTODY_CHAIN_BROKEN.
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(T0)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=T0,
        actor_headers=bundle["partner_headers"],
    )
    append_custody(
        evidence_id=e["id"], actor_lawyer_id=bundle["junior"]["id"],
        action="TRANSFERRED", occurred_at=add_minutes(T0, 5),
        actor_headers=bundle["partner_headers"],
    )
    append_custody(
        evidence_id=e["id"], actor_lawyer_id=bundle["junior"]["id"],
        action="RETURNED", occurred_at=add_minutes(T0, 10),
        actor_headers=bundle["partner_headers"],
    )
    res = api.submit_evidence(e["id"], bundle["partner_headers"])
    validate_error(res, "ERR_CUSTODY_CHAIN_BROKEN", expected_status=409)


def test_submission_appends_custody_event_and_sets_status(api):
    """PRD §3.5: 'On successful submission, the system stamps submitted_at,
    appends an additional CustodyEvent whose action is SUBMITTED and whose
    actor is the acting lawyer, and the evidence transitions from
    COLLECTED to SUBMITTED.'
    """
    bundle = setup_submitted_evidence()
    e = bundle["evidence"]
    assert e["status"] == "SUBMITTED"
    assert e["submitted_at"] is not None


# ---------------------------------------------------------------------------
# Rebuttal cycles
# ---------------------------------------------------------------------------
def test_first_rebuttal_transitions_evidence_to_rebutted(api):
    """PRD §3.5: 'The first rebuttal against a SUBMITTED evidence
    increments the evidence's rebuttal_count and transitions the evidence
    from SUBMITTED to REBUTTED.'
    """
    bundle = setup_submitted_evidence()
    rebuttal = validate_success(
        api.file_rebuttal(
            bundle["evidence"]["id"],
            create_rebuttal_payload(
                filed_by_lawyer_id=bundle["junior"]["id"]
            ),
            bundle["junior_headers"],
        ),
        201,
    )
    assert_rebuttal(rebuttal)
    assert rebuttal["status"] == "OPEN"
    after = validate_success(
        api.get_evidence(bundle["evidence"]["id"],
                         bundle["partner_headers"]), 200,
    )
    assert after["status"] == "REBUTTED"
    assert after["rebuttal_count"] == 1


def test_dismiss_rebuttal_returns_to_submitted(api):
    """PRD §3.5: 'A partner or senior may dismiss a rebuttal, marking it
    DISMISSED; once every rebuttal on a REBUTTED evidence has resolved
    into either UPHELD or DISMISSED, the evidence falls back from
    REBUTTED to SUBMITTED.'
    """
    bundle = setup_submitted_evidence()
    r = validate_success(
        api.file_rebuttal(
            bundle["evidence"]["id"],
            create_rebuttal_payload(
                filed_by_lawyer_id=bundle["junior"]["id"]
            ),
            bundle["junior_headers"],
        ),
        201,
    )
    validate_success(
        api.dismiss_rebuttal(r["id"], bundle["senior_headers"]), 200,
    )
    after = validate_success(
        api.get_evidence(bundle["evidence"]["id"],
                         bundle["partner_headers"]), 200,
    )
    assert after["status"] == "SUBMITTED"


def test_uphold_latest_rebuttal_excludes_evidence(api):
    """PRD §3.5: 'A partner may uphold a rebuttal, marking it UPHELD; if
    the upheld rebuttal is the latest still-open rebuttal against an
    evidence in SUBMITTED or REBUTTED, the evidence transitions to
    EXCLUDED.'
    """
    bundle = setup_submitted_evidence()
    r = validate_success(
        api.file_rebuttal(
            bundle["evidence"]["id"],
            create_rebuttal_payload(
                filed_by_lawyer_id=bundle["junior"]["id"]
            ),
            bundle["junior_headers"],
        ),
        201,
    )
    validate_success(
        api.uphold_rebuttal(r["id"], bundle["partner_headers"]), 200,
    )
    after = validate_success(
        api.get_evidence(bundle["evidence"]["id"],
                         bundle["partner_headers"]), 200,
    )
    assert after["status"] == "EXCLUDED"


# ---------------------------------------------------------------------------
# Direct partner-only exclude path
# ---------------------------------------------------------------------------
def test_partner_can_exclude_collected_evidence(api):
    """PRD §3.5: 'A partner also retains a direct exclusion path: from
    COLLECTED, a partner may exclude an evidence (typically before it
    ever reaches court), moving it to EXCLUDED.'
    """
    bundle = setup_three_lawyers_and_active_case()
    advance_clock(T0)
    e = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=T0,
        actor_headers=bundle["partner_headers"],
    )
    excluded = validate_success(
        api.exclude_evidence(e["id"], bundle["partner_headers"]), 200,
    )
    assert excluded["status"] == "EXCLUDED"


# ---------------------------------------------------------------------------
# Posture impact (PRD §2.8 / §3.5)
# ---------------------------------------------------------------------------
def test_rebuttal_drives_case_posture_to_restricted(api):
    """PRD §2.8: 'if the case has any Evidence row whose status is
    REBUTTED, the posture is RESTRICTED ...'
    """
    bundle = setup_submitted_evidence()
    case_id = bundle["case"]["id"]
    # Pre-rebuttal: posture should be OPEN.
    pre = validate_success(api.get_case(case_id, bundle["partner_headers"]), 200)
    assert pre["posture"] == "OPEN"
    validate_success(
        api.file_rebuttal(
            bundle["evidence"]["id"],
            create_rebuttal_payload(
                filed_by_lawyer_id=bundle["junior"]["id"]
            ),
            bundle["junior_headers"],
        ),
        201,
    )
    after = validate_success(api.get_case(case_id, bundle["partner_headers"]), 200)
    assert after["posture"] == "RESTRICTED"
