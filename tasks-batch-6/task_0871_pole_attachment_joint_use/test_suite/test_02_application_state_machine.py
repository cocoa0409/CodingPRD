"""Application / attachment / dispute state-machine claims.

Queue B — state_machines section: invalid transitions, terminal lockdown,
retire preconditions, idempotency, transfer side effects.
Queue A — non_linear_state_machine: permit-denied fork, cyclic dispute rounds.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_application_payload, create_survey_payload,
    TEST_USERS, make_attacher_headers, make_engineer_headers, make_permit_officer_headers,
    setup_base, setup_owner, setup_pole, setup_attacher, setup_crew,
    submit_application, create_surveyed_application, create_accepted_application,
    create_granted_application, create_finding, get_attachment_for_application,
    open_dispute_on_finding, dispute_to_under_review, dispute_request_info,
    dispute_respond, deny_permit, COMPLEX_SURVEY,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── Queue B: state_machines ───────────────────────────────────────────────
def test_estimate_before_survey_rejected(api):
    """PRD §3.3: "Once an application is `SURVEYED`, the same `Engineer` staff
    issue the engineering estimate, advancing it `SURVEYED → ESTIMATE_ISSUED`."
    PRD §2.10: "Then the target's state validity for the requested transition,
    yielding `ERR_INVALID_STATE` (409) or a more specific state error."

    Design: Corner/state_machines/estimate_before_survey_rejected
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    app = submit_application(pole["id"], attacher["id"])
    res = api.estimate_application(
        app["id"], {"expected_application_version": app["version"]},
        make_engineer_headers("eng-1"),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_survey_on_withdrawn_application_rejected(api):
    """PRD §3.4: "At any point before it reaches a terminal outcome, the acting
    `Attacher` may withdraw the application, moving it to `WITHDRAWN`".
    PRD §2.10: "Then the target's state validity for the requested transition,
    yielding `ERR_INVALID_STATE` (409) or a more specific state error."

    Design: Corner/state_machines/withdraw_then_survey_on_terminal_rejected
    """
    ctx = setup_base()
    app = submit_application(ctx["pole"]["id"], ctx["attacher"]["id"])
    get_success_data(api_client.withdraw_application(app["id"], make_attacher_headers(ctx["attacher"]["id"])))
    res = api.survey_application(
        app["id"], create_survey_payload(ctx["crew"]["id"]), make_engineer_headers("eng-1")
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_retire_pole_with_open_application_rejected(api):
    """PRD §3.9: "Retirement is allowed only when the pole is entirely clear:
    its `occupied_space_inches` and its `reserved_space_inches` must both be
    zero, and no application on that pole may sit in a non-terminal status —
    none in `SUBMITTED`, `SURVEYED`, `ESTIMATE_ISSUED`, or `ESTIMATE_ACCEPTED`.
    If any attachment, reservation, or open application remains, retirement is
    rejected with `ERR_POLE_HAS_ATTACHMENTS`."

    Design: Corner/state_machines/retire_pole_with_open_application_rejected
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    submit_application(pole["id"], attacher["id"])
    res = api.retire_pole(pole["id"], COORD)
    validate_error(res, "ERR_POLE_HAS_ATTACHMENTS", expected_status=409)


def test_pay_already_paid_invoice_rejected(api):
    """PRD §3.7: "An attempt to pay an invoice already `PAID` or `VOID` is
    rejected with `ERR_INVOICE_ALREADY_TERMINAL`."

    Design: Corner/state_machines/pay_already_paid_invoice_rejected
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"])
    inv_id = finding["penalty_invoice_id"]
    att_headers = make_attacher_headers(attacher["id"])
    get_success_data(api_client.pay_invoice(inv_id, att_headers))
    res = api.pay_invoice(inv_id, att_headers)
    validate_error(res, "ERR_INVOICE_ALREADY_TERMINAL", expected_status=409)


def test_attachment_transfer_creates_new_active_owner(api):
    """PRD §3.5: "The old attachment moves to `TRANSFERRED`, and a fresh
    `Attachment` is created in `ACTIVE` on the same pole with the same
    `allotted_space_inches` and `position_inches`, `authorized` true, owned by
    the new attacher, and carrying `transferred_from_attacher_id` set to the
    prior owner as an audit pointer. Because the old attachment leaves the
    `ACTIVE` set as the new one enters it, the pole's `occupied_space_inches` is
    net unchanged."

    Design: Corner/state_machines/attachment_transfer_creates_new_active_owner
    """
    ctx = create_granted_application(
        app_overrides={"requested_space_inches": 6, "requested_position_inches": 240},
    )
    att_a = ctx["attacher"]
    att_b = setup_attacher(company_name="B", cin="CINB", contact_email="b@x.com")
    old = ctx["attachment"]
    res = api.transfer_attachment(old["id"], {"new_attacher_id": att_b["id"]},
                                  make_attacher_headers(att_a["id"]))
    updated_old = validate_success(res, 200)
    assert updated_old["status"] == "TRANSFERRED"
    pole = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole["occupied_space_inches"] == 6


# ─── Queue A: non_linear_state_machine ─────────────────────────────────────
def test_application_fork_to_permit_denied_status(api):
    """PRD §3.4: "A denial moves the application `ESTIMATE_ACCEPTED →
    PERMIT_DENIED`. It records `permit_officer_user_id`, sets `permit_decision`
    to `DENIED`, stamps `permit_issued_at`, releases the reservation by
    returning the application's `reserved_space_inches` to zero (lowering the
    pole's `reserved_space_inches`)".

    Design: Difficulty/non_linear_state_machine/application_fork_estimate_accepted_to_permit_denied
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    res = api.permit_application(ctx["app"]["id"], {"decision": "DENIED"},
                                 make_permit_officer_headers("po-1"))
    app = validate_success(res, 200)
    assert app["status"] == "PERMIT_DENIED"
    assert app["reserved_space_inches"] == 0


def test_application_fork_permit_denied_releases_pole_reservation(api):
    """PRD §3.4: "A denial moves the application `ESTIMATE_ACCEPTED →
    PERMIT_DENIED`. It records `permit_officer_user_id`, sets `permit_decision`
    to `DENIED`, stamps `permit_issued_at`, releases the reservation by
    returning the application's `reserved_space_inches` to zero (lowering the
    pole's `reserved_space_inches`)".

    Design: Difficulty/non_linear_state_machine/application_fork_estimate_accepted_to_permit_denied
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    pole_before = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole_before["reserved_space_inches"] == 6
    deny_permit(ctx["app"]["id"])
    pole_after = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole_after["reserved_space_inches"] == 0


def test_dispute_cyclic_round_count_after_two_cycles(api):
    """PRD §3.8: "The owning `Attacher` responds, moving it `INFO_REQUESTED →
    UNDER_REVIEW`; each such response is one completed negotiation cycle and
    increments `round_count` by one. This `UNDER_REVIEW ↔ INFO_REQUESTED` loop
    may repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_review_info_requested_rounds
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    disp = open_dispute_on_finding(attacher["id"], finding["id"])
    dispute_to_under_review(disp["id"])
    dispute_request_info(disp["id"])
    dispute_respond(disp["id"], attacher["id"])          # round 1
    dispute_request_info(disp["id"])
    res = api.transition_dispute(disp["id"], {"to_state": "UNDER_REVIEW"},
                                 make_attacher_headers(attacher["id"]))  # round 2
    dispute = validate_success(res, 200)
    assert dispute["round_count"] == 2
    assert dispute["status"] == "UNDER_REVIEW"


def test_dispute_cyclic_status_returns_to_under_review(api):
    """PRD §3.8: "The owning `Attacher` responds, moving it `INFO_REQUESTED →
    UNDER_REVIEW`; each such response is one completed negotiation cycle and
    increments `round_count` by one. This `UNDER_REVIEW ↔ INFO_REQUESTED` loop
    may repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_review_info_requested_rounds
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    disp = open_dispute_on_finding(attacher["id"], finding["id"])
    dispute_to_under_review(disp["id"])
    dispute_request_info(disp["id"])
    after_one = dispute_respond(disp["id"], attacher["id"])
    assert after_one["round_count"] == 1
    assert after_one["status"] == "UNDER_REVIEW"
