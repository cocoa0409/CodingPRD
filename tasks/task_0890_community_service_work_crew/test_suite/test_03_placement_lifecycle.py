"""Placement proposal, waiver, and activation preconditions — cross-entity state
dependencies and the state-vs-safety validation precedence.

Covers Difficulty queue: cross_entity_state_dependency (placement->site) and
priority_pair_validation_conflict (terminal-placement activate). Covers Corner queue:
several placement-activation validations.
"""
from test_helpers import (
    validate_success, validate_error,
    create_placement_payload,
    make_supervisor_headers,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ============================ Difficulty: placement -> site dependency
def test_activate_placement_on_prospective_site_rejected(api):
    """PRD §3.3: "The host site must currently be `ACCEPTING`, or `ERR_SITE_NOT_ACCEPTING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cesd_placement_activate_requires_site_accepting
    """
    fx.set_clock()
    site = fx.new_site()
    sup = fx.new_supervisor(site["id"])
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-13")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    fx.sign_waiver(plc["id"], part["id"])
    assert site["status"] == "PROSPECTIVE"
    res = api.activate_placement(plc["id"], COORD)
    validate_error(res, "ERR_SITE_NOT_ACCEPTING", 409)
    after = validate_success(api.get_placement(plc["id"], COORD), 200)
    assert after["status"] == "PROPOSED"


def test_activate_placement_on_paused_site_rejected(api):
    """PRD §3.3: "The host site must currently be `ACCEPTING`, or `ERR_SITE_NOT_ACCEPTING` (HTTP 409)."
    PRD §3.1: "Pausing a site moves it from `ACCEPTING` to `PAUSED`; while paused, new placements to the
    site are blocked".

    Design: Difficulty/cross_entity_state_dependency/cesd_placement_activate_requires_site_accepting
    """
    base = fx.accepting_site_with_supervisor()
    paused = validate_success(api.pause_site(base["site"]["id"], COORD), 200)
    assert paused["status"] == "PAUSED"
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-13B")
    plc = fx.new_placement(ref["id"], base["site"]["id"], base["supervisor"]["id"])
    fx.sign_waiver(plc["id"], part["id"])
    res = api.activate_placement(plc["id"], COORD)
    validate_error(res, "ERR_SITE_NOT_ACCEPTING", 409)


# ============================ Difficulty: terminal-state beats waiver guard
def test_activate_terminated_placement_returns_invalid_state(api):
    """PRD §2.9: "the generic state check that a resource admits the requested transition, else
    `ERR_INVALID_STATE`; and then the specific state and business guards
    (referral-not-active, placement-not-active, waiver, site-accepting, insurance,
    self-approval, session buffers, capacity, hours limits) described in §3."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_activate_terminal_placement_and_unsigned_waiver_state_wins
    """
    fx.set_clock()
    site = fx.new_site()
    sup = fx.new_supervisor(site["id"])
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-9")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    validate_success(api.terminate_placement(plc["id"], COORD, {"reason": "cancelled"}), 200)
    # Waiver never signed, but the state check (priority 7) pre-empts the waiver guard.
    res = api.activate_placement(plc["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_activate_terminated_placement_leaves_status_terminated(api):
    """PRD §3.3: "Placement terminal states are `COMPLETED` and `TERMINATED`."
    PRD §2.9: "the generic state check that a resource admits the requested transition, else
    `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_activate_terminal_placement_and_unsigned_waiver_state_wins
    """
    fx.set_clock()
    site = fx.new_site()
    sup = fx.new_supervisor(site["id"])
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-9B")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    validate_success(api.terminate_placement(plc["id"], COORD), 200)
    api.activate_placement(plc["id"], COORD)  # rejected
    after = validate_success(api.get_placement(plc["id"], COORD), 200)
    assert after["status"] == "TERMINATED"


# ============================ Difficulty: check-in requires placement ACTIVE
def test_checkin_on_proposed_placement_rejected(api):
    """PRD §3.5: "Checking in advances a session from `SCHEDULED` to `CHECKED_IN`, but only while the
    placement is `ACTIVE`; if the placement is not active the check-in is refused with
    `ERR_PLACEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cesd_checkin_requires_placement_active
    """
    fx.set_clock()
    site = fx.new_site()
    sup = fx.new_supervisor(site["id"])
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-14")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    ws = fx.new_session(plc["id"], "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
    res = api.check_in(ws["id"], make_supervisor_headers(sup["id"]),
                       {"check_in_at": "2026-06-10T09:00:00Z"})
    validate_error(res, "ERR_PLACEMENT_NOT_ACTIVE", 409)
    after = validate_success(api.get_work_session(ws["id"], COORD), 200)
    assert after["attendance_status"] == "SCHEDULED"


def test_checkin_succeeds_once_placement_active(api):
    """PRD §3.5: "Checking in advances a session from `SCHEDULED` to `CHECKED_IN`, but only while the
    placement is `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/cesd_checkin_requires_placement_active
    """
    s = fx.active_placement_scenario(court_case_number="CR-14B")
    ws = fx.new_session(s["placement_id"], "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
    res = api.check_in(ws["id"], make_supervisor_headers(s["supervisor_id"]),
                       {"check_in_at": "2026-06-10T09:00:00Z"})
    data = validate_success(res, 200)
    assert data["attendance_status"] == "CHECKED_IN"


# ============================ Corner: placement-activation validations
def test_activate_placement_without_waiver_rejected(api):
    """PRD §3.3: "The waiver must be signed, or the request is refused with `ERR_WAIVER_REQUIRED` (HTTP 409)."

    Design: Corner/validations/activate_placement_without_waiver_on_accepting_site_rejected
    """
    base = fx.accepting_site_with_supervisor()
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-D11")
    plc = fx.new_placement(ref["id"], base["site"]["id"], base["supervisor"]["id"])
    res = api.activate_placement(plc["id"], COORD)
    validate_error(res, "ERR_WAIVER_REQUIRED", 409)


def test_activate_placement_insurance_expired_after_site_active_rejected(api):
    """PRD §3.3: "The site must carry a `VERIFIED`, non-expired insurance policy, or `ERR_INSURANCE_INVALID`
    (HTTP 409)."
    PRD §3.1: "A policy is considered valid coverage only while `VERIFIED` and while the clock has not yet
    reached its `expiry_date`."

    Design: Corner/validations/activate_placement_insurance_expired_after_site_active_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    site = fx.new_site()
    pol = fx.new_policy(site["id"], expiry="2026-07-01T00:00:00Z")
    fx.verify_policy(pol["id"])
    fx.activate_site(site["id"])
    sup = fx.new_supervisor(site["id"])
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-D12")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    fx.sign_waiver(plc["id"], part["id"])
    fx.set_clock("2026-08-01T00:00:00Z")  # past policy expiry
    res = api.activate_placement(plc["id"], COORD)
    validate_error(res, "ERR_INSURANCE_INVALID", 409)


def test_placement_supervisor_from_other_site_mismatch(api):
    """PRD §3.3: "the named supervisor must belong to the named site, otherwise the request is rejected with
    `ERR_SUPERVISOR_SITE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/placement_supervisor_from_other_site_mismatch
    """
    site_a = fx.new_site(name="Site A")
    site_b = fx.new_site(name="Site B", agency_type="GOVERNMENT")
    sup_a = fx.new_supervisor(site_a["id"], full_name="Sup A")
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-D7")
    res = api.create_placement(
        create_placement_payload(ref["id"], site_b["id"], sup_a["id"]), COORD)
    validate_error(res, "ERR_SUPERVISOR_SITE_MISMATCH", 422)
