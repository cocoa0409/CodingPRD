"""Cascades: inspection-failure suspension (depth 2) and condemnation (depth 3),
plus condemnation/notice state guards.
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, get_success_data,
    validate_success, validate_error,
    setup_property_with_active_license, setup_property_with_violations,
    run_periodic_with_fail_items, list_property_violations, get_property,
    create_landlord, create_property, create_notice, create_condemnation_order,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TENANT = TEST_USERS["tenant_headers"]


def _condemnation_ready(api):
    """ACTIVE (then cascaded-SUSPENDED) license, two OPEN CRITICAL violations one ESCALATED,
    and a DRAFT condemnation order citing it."""
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980)
    get_success_data(api.set_clock("2026-06-05T09:00:00Z", REGISTRAR))
    run_periodic_with_fail_items(
        api, ctx,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"},
                    {"category": "HABITABILITY", "code": "MOLD", "severity": "CRITICAL"}],
        scheduled_date="2026-06-05T09:00:00Z",
    )
    violations = list_property_violations(api, ctx["property_id"])
    v_crit = violations[0]
    get_success_data(api.escalate_violation(v_crit["id"], REGISTRAR))
    order = create_condemnation_order(api, ctx["property_id"], basis="two critical life-safety",
                                      triggering_violation_id=v_crit["id"])
    ctx["v_crit"] = v_crit
    ctx["order"] = order
    return ctx


# --- Difficulty: transitive_cascade / condemnation_issue_depth3_cascade ---

def test_condemnation_issue_condemns_property(api):
    """PRD §3.8: "Issuance is permitted only when the order is DRAFT and the property has at
    least one violation currently in ESCALATED".
    PRD §3.8: "First, the property — whether it was REGISTERED or SUSPENDED — transitions to the
    terminal CONDEMNED state, and one CONDEMNATION_NOTICE tenant notice (status SENT) is generated
    for the property."

    Design: Difficulty/transitive_cascade/condemnation_issue_depth3_cascade
    """
    ctx = _condemnation_ready(api)
    order = get_success_data(api.issue_condemnation_order(ctx["order"]["id"], REGISTRAR))
    assert order["status"] == "ISSUED"
    assert get_property(api, ctx["property_id"])["registration_status"] == "CONDEMNED"


def test_condemnation_issue_revokes_license_and_condemns_violations(api):
    """PRD §3.8: "Second, the property's non-terminal license — one currently ACTIVE, EXPIRED, or
    SUSPENDED — is transitioned to the terminal REVOKED state. Third, as a consequence of that
    revocation, every one of the property's non-terminal violations — those in OPEN,
    REMEDIATION_SUBMITTED, or ESCALATED — is transitioned to the terminal CONDEMNED_BASIS state."

    Design: Difficulty/transitive_cascade/condemnation_issue_depth3_cascade
    """
    ctx = _condemnation_ready(api)
    get_success_data(api.issue_condemnation_order(ctx["order"]["id"], REGISTRAR))
    lic = get_success_data(api.list_property_licenses(ctx["property_id"], REGISTRAR))[0]
    assert lic["status"] == "REVOKED"
    v = validate_success(api.get_violation(ctx["v_crit"]["id"], REGISTRAR))
    assert v["status"] == "CONDEMNED_BASIS"


# --- Difficulty: transitive_cascade / inspection_fail_depth2_cascade ------

def test_inspection_fail_opens_violation(api):
    """PRD §3.4: "When a PERIODIC or COMPLAINT inspection fails, each checklist item whose result
    is FAIL produces a new violation in status OPEN."
    PRD §3.4: "The property's open_violation_count rises by the number of violations created."

    Design: Difficulty/transitive_cascade/inspection_fail_depth2_cascade
    """
    ctx = setup_property_with_violations(
        api,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"}],
        pass_items=[{"category": "HABITABILITY", "code": "HEAT"}],
    )
    assert ctx["inspection"]["status"] == "FAILED"
    assert get_property(api, ctx["property_id"])["open_violation_count"] == 1


def test_critical_violation_suspends_property(api):
    """PRD §3.4: "Then, as a second cascade hop, every newly opened violation whose severity is
    CRITICAL drives the property from REGISTERED to SUSPENDED".
    PRD §2.9: "the property's registration_status always reflects whether it currently holds any
    open critical violation."

    Design: Difficulty/transitive_cascade/inspection_fail_depth2_cascade
    """
    ctx = setup_property_with_violations(
        api,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"}],
        pass_items=[{"category": "HABITABILITY", "code": "HEAT"}],
    )
    prop = get_property(api, ctx["property_id"])
    assert prop["open_critical_violation_count"] == 1
    assert prop["registration_status"] == "SUSPENDED"


# --- Corner: state_machines / issue_condemnation_twice_returns_invalid_state

def test_issue_condemnation_twice_returns_invalid_state(api):
    """PRD §3.8: "A Registrar then issues the order, moving it from DRAFT to ISSUED."
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/issue_condemnation_twice_returns_invalid_state
    """
    ctx = _condemnation_ready(api)
    get_success_data(api.issue_condemnation_order(ctx["order"]["id"], REGISTRAR))
    resp = api.issue_condemnation_order(ctx["order"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: validations / issue_condemnation_without_escalated_returns_no_basis

def test_issue_condemnation_without_escalated_returns_no_basis(api):
    """PRD §3.8: "Issuance is permitted only when the order is DRAFT and the property has at
    least one violation currently in ESCALATED; without such a basis, issuance is rejected with
    ERR_NO_CONDEMNATION_BASIS."

    Design: Corner/validations/issue_condemnation_without_escalated_returns_no_basis
    """
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    prop = create_property(api, landlord["id"], unit_count=3, year_built=1980)
    order = create_condemnation_order(api, prop["id"], basis="no basis yet")
    resp = api.issue_condemnation_order(order["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NO_CONDEMNATION_BASIS.value)
    data = validate_success(api.get_condemnation_order(order["id"], REGISTRAR))
    assert data["status"] == "DRAFT", "unchanged"


# --- Corner: state_machines / acknowledge_twice_returns_invalid_state -----

def test_acknowledge_twice_returns_invalid_state(api):
    """PRD §3.7: "A Tenant acknowledges a notice before its window closes, moving it from SENT to
    ACKNOWLEDGED and recording acknowledged_at from the clock."
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/acknowledge_twice_returns_invalid_state
    """
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    prop = create_property(api, landlord["id"], unit_count=3, year_built=1980)
    notice = create_notice(api, prop["id"], notice_type="INSPECTION_NOTICE")
    acked = get_success_data(api.acknowledge_notice(notice["id"], TENANT))
    assert acked["status"] == "ACKNOWLEDGED"
    resp = api.acknowledge_notice(notice["id"], TENANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: validations / acknowledge_after_deadline_returns_notice_expired

def test_acknowledge_after_deadline_returns_notice_expired(api):
    """PRD §3.7: "A notice is created in status SENT with its sent_at read from the logical clock,
    and its ack_deadline is set to sent_at plus 30 days."
    PRD §3.7: "Acknowledgement is allowed only while the notice is SENT and the clock is at or
    before the ack_deadline; acknowledging after the deadline is rejected with ERR_NOTICE_EXPIRED."

    Design: Corner/validations/acknowledge_after_deadline_returns_notice_expired
    """
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    landlord = create_landlord(api)
    prop = create_property(api, landlord["id"], unit_count=3, year_built=1980)
    notice = create_notice(api, prop["id"], notice_type="LEAD_PAINT_DISCLOSURE")
    get_success_data(api.set_clock("2026-07-02T00:00:00Z", REGISTRAR))  # past ack_deadline 2026-07-01
    resp = api.acknowledge_notice(notice["id"], TENANT)
    validate_error(resp, ApiErrorId.ERR_NOTICE_EXPIRED.value)
