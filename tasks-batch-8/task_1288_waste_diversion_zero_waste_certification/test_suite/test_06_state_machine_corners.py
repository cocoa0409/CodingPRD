"""State-machine corner coverage: invalid transitions, terminal lockdown,
valid transition loops, and cascade side effects (PRD §3.1–§3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, setup_closed_period_with_rate,
    setup_application_under_review,
    create_site, create_vendor, create_active_contract, create_period,
    create_ticket, validate_ticket, reject_ticket, create_goal,
    set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_vendor_user_headers, make_manager_headers,
    make_officer_headers,
)

MGR = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
STEWARD = TEST_USERS["steward_headers"]


def test_validate_already_validated_ticket_rejected(api):
    """PRD §3.3: "Validation by a DataSteward moves the ticket from PENDING to
    VALIDATED and applies five gates, evaluated in order: the ticket must be
    PENDING (ERR_TICKET_NOT_PENDING) ..."

    Design: Corner/state_machines/validate_already_validated_ticket_rejected
    """
    site, vendor, contract, period = setup_open_period_scenario("Site VV")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=3000, tare_weight_lbs=1000,
                       external_ticket_ref="VV-T1")
    validate_ticket(t1["id"])
    validate_error(api.validate_ticket(t1["id"], STEWARD),
                   ApiErrorId.ERR_TICKET_NOT_PENDING)
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["total_waste_lbs_validated"] == 2000


def test_voided_ticket_terminal_lockdown(api):
    """PRD §3.3: "VOIDED is terminal."
    PRD §3.3: "Validation by a DataSteward moves the ticket from PENDING to
    VALIDATED and applies five gates, evaluated in order: the ticket must be
    PENDING (ERR_TICKET_NOT_PENDING)."

    Design: Corner/state_machines/voided_ticket_terminal_lockdown
    """
    site, vendor, contract, period = setup_open_period_scenario("Site VT")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=3000, tare_weight_lbs=1000,
                       external_ticket_ref="VT-T1")
    validate_ticket(t1["id"])
    get_success_data(api.void_ticket(t1["id"], {"reason": "entered twice"}, STEWARD))
    validate_error(api.validate_ticket(t1["id"], STEWARD),
                   ApiErrorId.ERR_TICKET_NOT_PENDING)
    t = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t["validation_status"] == "VOIDED"


def test_decide_approved_application_terminal(api):
    """PRD §3.8: "Three checks apply, in order. The application must be
    `UNDER_REVIEW`, otherwise `ERR_APPLICATION_NOT_IN_REVIEW`."

    Design: Corner/state_machines/decide_approved_application_terminal
    """
    site, period, app = setup_application_under_review(
        "Site DA", level="BRONZE", submitter_id="mgr-1",
        tickets=[{"disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                  "tare_weight_lbs": 1000, "external_ticket_ref": "DA-T1"}],
    )
    get_success_data(api.decide_application(
        app["id"], {"outcome": "APPROVED"}, make_officer_headers("officer-1")
    ))
    validate_error(
        api.decide_application(app["id"], {"outcome": "REJECTED"},
                               make_officer_headers("officer-1")),
        ApiErrorId.ERR_APPLICATION_NOT_IN_REVIEW,
    )
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "APPROVED"


def test_cancel_achieved_goal_rejected(api):
    """PRD §3.6: "a SustainabilityManager may cancel an ACTIVE goal, moving it
    to CANCELLED; cancelling from any other state is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_achieved_goal_rejected
    """
    site, vendor, contract, period = setup_open_period_scenario("Site GA")
    goal = create_goal(site["id"], metric="DIVERSION_RATE", target_value=50)
    t = create_ticket(site["id"], vendor["id"], contract["id"],
                      disposal_route="RECYCLING", gross_weight_lbs=2000,
                      tare_weight_lbs=1000, external_ticket_ref="GA-T1")
    validate_ticket(t["id"])
    get_success_data(api.close_period(period["id"], OFFICER))
    g = get_success_data(api.get_goal(goal["id"], OFFICER))
    assert g["status"] == "ACHIEVED"
    validate_error(api.cancel_goal(goal["id"], MGR), ApiErrorId.ERR_INVALID_STATE)
    g2 = get_success_data(api.get_goal(goal["id"], OFFICER))
    assert g2["status"] == "ACHIEVED"


def test_application_revise_rejected_returns_to_draft(api):
    """PRD §3.8: "a SustainabilityManager may revise a rejected application,
    returning it from REJECTED to DRAFT with submitted_by, decided_by, and
    decided_at cleared for another attempt; revision from any other state is
    rejected with ERR_APPLICATION_NOT_DRAFT."

    Design: Corner/state_machines/application_revise_rejected_returns_to_draft
    """
    site, period, app = setup_application_under_review(
        "Site RV", level="BRONZE", submitter_id="mgr-1",
        tickets=[{"disposal_route": "RECYCLING", "gross_weight_lbs": 2000,
                  "tare_weight_lbs": 1000, "external_ticket_ref": "RV-T1"}],
    )
    get_success_data(api.decide_application(
        app["id"], {"outcome": "REJECTED", "notes": "incomplete documentation"},
        make_officer_headers("officer-1"),
    ))
    revised = get_success_data(api.revise_application(app["id"], MGR))
    assert revised["status"] == "DRAFT"
    assert revised.get("submitted_by") is None
    resubmitted = get_success_data(
        api.submit_application(app["id"], make_manager_headers("mgr-2"))
    )
    assert resubmitted["status"] == "SUBMITTED"


def test_contract_terminate_rejects_pending_tickets(api):
    """PRD §3.2: "A SustainabilityManager may terminate it — permitted from
    either ACTIVE or SUSPENDED and rejected with ERR_INVALID_STATE from any
    other state — moving it to TERMINATED and rejecting every PENDING ticket
    riding on it with rejection_reason set to CONTRACT_TERMINATED, shrinking
    the containing periods' provisional totals."

    Design: Corner/state_machines/contract_terminate_rejects_pending_tickets
    """
    site, vendor, contract, period = setup_open_period_scenario("Site TM")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="TM-T1")
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=3000, tare_weight_lbs=1000,
                       external_ticket_ref="TM-T2")
    validate_ticket(t2["id"])
    c = get_success_data(api.terminate_contract(contract["id"], MGR))
    assert c["status"] == "TERMINATED"
    t1_after = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t1_after["validation_status"] == "REJECTED"
    assert t1_after["rejection_reason"] == "CONTRACT_TERMINATED"
    t2_after = get_success_data(api.get_ticket(t2["id"], OFFICER))
    assert t2_after["validation_status"] == "VALIDATED"
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["total_waste_lbs_provisional"] == 2000


def test_vendor_reactivate_restores_contracts_not_tickets(api):
    """PRD §3.1: "Setting to_status back to ACTIVE — permitted only from
    SUSPENDED — returns the vendor's SUSPENDED contracts to ACTIVE, but
    tickets rejected during the suspension stay REJECTED; there is no
    automatic reopen, and the vendor must correct and resubmit each one
    individually (see §3.3)."

    Design: Corner/state_machines/vendor_reactivate_restores_contracts_not_tickets
    """
    site, vendor, contract, period = setup_open_period_scenario("Site RA")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       gross_weight_lbs=2000, tare_weight_lbs=1000,
                       external_ticket_ref="RA-T1")
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "SUSPENDED"}, OFFICER))
    v = get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "ACTIVE"}, OFFICER))
    assert v["status"] == "ACTIVE"
    c = get_success_data(api.get_contract(contract["id"], OFFICER))
    assert c["status"] == "ACTIVE"
    t = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t["validation_status"] == "REJECTED"
