"""Cascade outreach: invitation cost, the SENT/DECLINED cycle, acceptance cascade,
outreach-budget ledger, and send preconditions.

Translates queue-A difficulty instances (declined-then-resent cycle, accept cascade,
send-requires-actionable, outreach-budget conservation) and queue-B corner instances
(phone/degree-2 cost, expire-before-deadline, over-budget send).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_counselor_headers,
    create_invitation_payload,
    setup_sent_invitation, setup_proband_disclosed_actionable,
    setup_risk_assessed_case, create_invitation,
    create_family, create_counselor, create_case, add_member,
)


# --------------------------------------------------------------------------- #
# Difficulty: cascade_invitation_declined_then_resent_cycle
# --------------------------------------------------------------------------- #
def _declined_then_resent():
    ctx = setup_sent_invitation(contact_method="EMAIL", degree=1)
    hdr = make_counselor_headers(ctx["counselor_id"])
    get_success_data(api_decline(ctx))
    resent = validate_success(api_send(ctx), 200)
    ctx["resent"] = resent
    ctx["hdr"] = hdr
    return ctx


def api_decline(ctx):
    from test_helpers import api_client
    return api_client.decline_invitation(ctx["invitation_id"],
                                         make_counselor_headers(ctx["counselor_id"]))


def api_send(ctx):
    from test_helpers import api_client
    return api_client.send_invitation(ctx["invitation_id"],
                                      make_counselor_headers(ctx["counselor_id"]))


def test_declined_invitation_can_be_resent(api):
    """PRD 3.7: "Sending an invitation — the transition into SENT, allowed from either
    DRAFT or DECLINED (else ERR_INVITATION_INVALID_STATE)". PRD 3.7: "Because DECLINED
    can be sent again, outreach is cyclic: a declined invitation re-enters SENT under
    the same preconditions and re-reserves its cost."

    Design: Difficulty/non_linear_state_machine/cascade_invitation_declined_then_resent_cycle
    """
    ctx = _declined_then_resent()
    assert ctx["resent"]["status"] == "SENT"


def test_resend_re_reserves_cost(api):
    """PRD 3.7: "a base of 500 cents for LETTER, 100 cents for EMAIL, or 800 cents for
    PHONE, plus a degree surcharge of 0 cents for a first-degree relative". PRD 3.7: "A
    send reserves the cost — adding estimated_cost_cents to outreach_reserved_cents and
    recomputing availability".

    Design: Difficulty/non_linear_state_machine/cascade_invitation_declined_then_resent_cycle
    """
    ctx = _declined_then_resent()
    assert ctx["resent"]["estimated_cost_cents"] == 100
    fam = validate_success(api.get_family(ctx["family_id"], ctx["hdr"]), 200)
    assert fam["outreach_reserved_cents"] == 100


# --------------------------------------------------------------------------- #
# Difficulty: accept_invitation_cascades_to_relative_case_and_family_counters_depth2
# --------------------------------------------------------------------------- #
def _accepted_invitation():
    ctx = setup_sent_invitation(contact_method="EMAIL", degree=1)
    hdr = make_counselor_headers(ctx["counselor_id"])
    accepted = validate_success(
        api_accept(ctx, {"patient_dob": "1978-01-01", "covered_sessions": 2}), 200)
    ctx["accepted"] = accepted
    ctx["hdr"] = hdr
    return ctx


def api_accept(ctx, payload):
    from test_helpers import api_client
    return api_client.accept_invitation(ctx["invitation_id"],
                                        make_counselor_headers(ctx["counselor_id"]),
                                        payload)


def test_accept_creates_relative_case(api):
    """PRD 3.7: "Accepting a sent invitation is the productive terminus: it converts the
    reservation to spend ... and then manufactures a new counseling case for the
    relative. The relative's case is created in the same family, its
    originating_invitation_id set to the accepted invitation".

    Design: Difficulty/transitive_cascade/accept_invitation_cascades_to_relative_case_and_family_counters_depth2
    """
    ctx = _accepted_invitation()
    assert ctx["accepted"]["status"] == "ACCEPTED"
    cases, meta = validate_paginated(
        api.list_cases(ctx["hdr"], params={"originating_invitation_id": ctx["invitation_id"]}))
    assert meta["total_count"] == 1
    assert cases[0]["originating_invitation_id"] == ctx["invitation_id"]


def test_accept_updates_family_cascade_counters(api):
    """PRD 3.7: "Creating that case recomputes the family's cascade_cases_count and
    cascade_uptake_pct." PRD 2.7: "cascade_uptake_pct is cascade_cases_count divided by
    cascade_invitations_sent_count". PRD 3.7: "it converts the reservation to spend —
    subtracting estimated_cost_cents from outreach_reserved_cents and adding it to
    outreach_spent_cents".

    Design: Difficulty/transitive_cascade/accept_invitation_cascades_to_relative_case_and_family_counters_depth2
    """
    ctx = _accepted_invitation()
    fam = validate_success(api.get_family(ctx["family_id"], ctx["hdr"]), 200)
    assert fam["cascade_cases_count"] == 1
    assert fam["cascade_uptake_pct"] == pytest.approx(1.0, abs=1e-6)
    assert fam["outreach_spent_cents"] == 100


# --------------------------------------------------------------------------- #
# Difficulty: cascade_send_requires_actionable_disclosed_result
# --------------------------------------------------------------------------- #
def _drafted_invite_without_disclosure():
    ctx = setup_risk_assessed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": False,
                  "age_of_onset": None}],
        budget=100000, covered_sessions=2)
    inv = create_invitation(ctx["family_id"], ctx["case_id"], ctx["members"][0]["id"],
                            ctx["counselor_id"], relationship="SIBLING", degree=1,
                            contact_method="PHONE")
    ctx["invitation"] = inv
    ctx["invitation_id"] = inv["id"]
    return ctx


def test_send_without_actionable_result_rejected(api):
    """PRD 3.7: "the proband case must have a DISCLOSED test result that is actionable
    (else ERR_RESULT_NOT_ACTIONABLE)".

    Design: Difficulty/cross_entity_state_dependency/cascade_send_requires_actionable_disclosed_result
    """
    ctx = _drafted_invite_without_disclosure()
    res = api.send_invitation(ctx["invitation_id"], make_counselor_headers(ctx["counselor_id"]))
    validate_error(res, "ERR_RESULT_NOT_ACTIONABLE", expected_status=409)


def test_send_without_actionable_result_leaves_invitation_draft(api):
    """PRD 3.7: "the proband case must have a DISCLOSED test result that is actionable
    (else ERR_RESULT_NOT_ACTIONABLE)". PRD 3.7: "A send reserves the cost — adding
    estimated_cost_cents to outreach_reserved_cents and recomputing availability".

    Design: Difficulty/cross_entity_state_dependency/cascade_send_requires_actionable_disclosed_result
    """
    ctx = _drafted_invite_without_disclosure()
    hdr = make_counselor_headers(ctx["counselor_id"])
    api.send_invitation(ctx["invitation_id"], hdr)
    inv = validate_success(api.get_invitation(ctx["invitation_id"], hdr), 200)
    assert inv["status"] == "DRAFT"
    fam = validate_success(api.get_family(ctx["family_id"], hdr), 200)
    assert fam["outreach_reserved_cents"] == 0


# --------------------------------------------------------------------------- #
# Difficulty: outreach_budget_conserved_on_send_then_decline
# --------------------------------------------------------------------------- #
def test_decline_releases_reservation(api):
    """PRD 3.7: "Declining a sent invitation moves it to DECLINED and releases the
    reservation, subtracting estimated_cost_cents from outreach_reserved_cents and
    recomputing availability."

    Design: Difficulty/compensating_invariant/outreach_budget_conserved_on_send_then_decline
    """
    ctx = setup_sent_invitation(contact_method="EMAIL", degree=1)
    hdr = make_counselor_headers(ctx["counselor_id"])
    declined = validate_success(api.decline_invitation(ctx["invitation_id"], hdr), 200)
    assert declined["status"] == "DECLINED"
    fam = validate_success(api.get_family(ctx["family_id"], hdr), 200)
    assert fam["outreach_reserved_cents"] == 0
    assert fam["outreach_spent_cents"] == 0


def test_outreach_ledger_conserved_after_send_then_decline(api):
    """PRD 2.7: "The invariant outreach_budget_cents equals outreach_available_cents plus
    outreach_reserved_cents plus outreach_spent_cents holds at every instant".

    Design: Difficulty/compensating_invariant/outreach_budget_conserved_on_send_then_decline
    """
    ctx = setup_sent_invitation(contact_method="EMAIL", degree=1)
    hdr = make_counselor_headers(ctx["counselor_id"])
    validate_success(api.decline_invitation(ctx["invitation_id"], hdr), 200)
    fam = validate_success(api.get_family(ctx["family_id"], hdr), 200)
    assert fam["outreach_available_cents"] == 100000
    assert fam["outreach_budget_cents"] == 100000
    assert fam["outreach_budget_cents"] == (
        fam["outreach_available_cents"] + fam["outreach_reserved_cents"]
        + fam["outreach_spent_cents"])


# --------------------------------------------------------------------------- #
# Corner: cascade_cost_phone_degree2_is_1000
# --------------------------------------------------------------------------- #
def test_cascade_cost_phone_degree2(api):
    """PRD 3.7: "On creation the invitation is DRAFT and its estimated_cost_cents is
    computed from the outreach price sheet: a base of 500 cents for LETTER, 100 cents
    for EMAIL, or 800 cents for PHONE, plus a degree surcharge of 0 cents for a
    first-degree relative, 200 cents for a second-degree relative, or 400 cents for a
    third-degree relative."

    Design: Corner/calculations/cascade_cost_phone_degree2_is_1000
    """
    fam = create_family(name="Kindred P")
    gc = create_counselor()
    case = create_case(fam["id"], gc["id"], covered_sessions=1)
    member = add_member(case["id"], gc["id"], relationship="AUNT_UNCLE", degree=2,
                        affected=False, age_of_onset=None)
    res = api.create_invitation(
        create_invitation_payload(fam["id"], case["id"], member["id"],
                                  relative_name="Rel P", relationship="AUNT_UNCLE",
                                  degree=2, contact_method="PHONE"),
        make_counselor_headers(gc["id"]))
    inv = validate_success(res, 201)
    assert inv["estimated_cost_cents"] == 1000
    assert inv["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Corner: expire_invitation_before_deadline_rejected
# --------------------------------------------------------------------------- #
def test_expire_before_deadline_rejected(api):
    """PRD 3.7: "Expiring a sent invitation is permitted only once the logical clock has
    reached or passed expires_at (else ERR_INVITATION_NOT_EXPIRABLE)". PRD 2.12: "At
    startup the clock reads exactly 2026-05-01T00:00:00Z, and before any set call it
    stays at that default and never falls back to real time."

    Design: Corner/state_machines/expire_invitation_before_deadline_rejected
    """
    ctx = setup_sent_invitation(contact_method="LETTER", degree=1,
                                expires_at="2026-07-01T00:00:00Z")
    hdr = make_counselor_headers(ctx["counselor_id"])
    res = api.expire_invitation(ctx["invitation_id"], hdr)
    validate_error(res, "ERR_INVITATION_NOT_EXPIRABLE", expected_status=409)
    inv = validate_success(api.get_invitation(ctx["invitation_id"], hdr), 200)
    assert inv["status"] == "SENT"


# --------------------------------------------------------------------------- #
# Corner: cascade_send_over_budget_rejected
# --------------------------------------------------------------------------- #
def test_send_over_budget_rejected(api):
    """PRD 3.7: "the family's outreach_available_cents must be at least this invitation's
    estimated_cost_cents (else ERR_OUTREACH_BUDGET_EXCEEDED)".

    Design: Corner/validations/cascade_send_over_budget_rejected
    """
    ctx = setup_proband_disclosed_actionable(budget=500)
    inv = create_invitation(ctx["family_id"], ctx["case_id"], ctx["at_risk_member_id"],
                            ctx["counselor_id"], relationship="SIBLING", degree=1,
                            contact_method="PHONE")  # cost 800 > budget 500
    hdr = make_counselor_headers(ctx["counselor_id"])
    res = api.send_invitation(inv["id"], hdr)
    validate_error(res, "ERR_OUTREACH_BUDGET_EXCEEDED", expected_status=402)
    fetched = validate_success(api.get_invitation(inv["id"], hdr), 200)
    assert fetched["status"] == "DRAFT"
