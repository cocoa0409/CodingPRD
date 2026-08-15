"""Assessment notices and the appeal fork-join lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_appeal,
    audit_event_types,
    client_headers_for,
    create_appeal_payload,
    create_client_account,
    create_hearing_payload,
    create_decision_payload,
    create_notice_payload,
    create_tax_bill_payload,
    list_audit_events,
    new_analyst,
    new_manager,
    set_logical_clock,
    setup_decided_appeal,
    setup_filed_rendition,
    setup_notice_for_filed,
    setup_validated_bill,
    setup_classified_asset,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["assessor_clerk_headers"]


def _setup_decided_appeal_with_validated_bill():
    """Filed 2027 rendition (800000), ACCEPTED notice 800000, bill imported by the
    analyst and validated MATCHED at 20000, then an appeal taken to DECIDED with
    a GRANTED_REDUCTION at 600000. Notice is PROTESTED at return."""
    ctx = setup_validated_bill(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "F1", "acquisition_cost_cents": 800000},
        bill_overrides={"billed_amount_cents": 20000, "tax_rate": 0.025,
                        "due_date": "2027-06-30"},
    )
    assert ctx["bill"]["validated_amount_cents"] == 20000, "setup sanity"
    assert ctx["bill"]["validation_status"] == "MATCHED"
    appeal = validate_success(api_client.create_appeal(
        ctx["notice"]["id"], create_appeal_payload(claimed_value_cents=600000),
        ctx["analyst"]["headers"]), 201)
    ctx["appeal"] = appeal
    return ctx


def _drive_to_decided(ctx, decided_value_cents=600000):
    """FILED -> HEARING_SCHEDULED -> DECIDED (GRANTED_REDUCTION)."""
    validate_success(api_client.schedule_hearing(ctx["appeal"]["id"],
                                                 create_hearing_payload(), CLERK), 200)
    ctx["appeal"] = validate_success(api_client.record_decision(
        ctx["appeal"]["id"],
        create_decision_payload(decision="GRANTED_REDUCTION",
                                decided_value_cents=decided_value_cents),
        CLERK), 200)
    return ctx


def test_appeal_escalate_branch_changes_nothing(api):
    """PRD §3.5: "Escalating (`resolution` of `ESCALATE`) instead moves the appeal
    from `DECIDED` to `ESCALATED` and deliberately changes nothing else: the
    notice stays `PROTESTED`, its value is not adjusted, and no bill revalidation
    fires."

    Design: Difficulty/non_linear_state_machine/appeal_decision_fork_join
    """
    ctx = _drive_to_decided(_setup_decided_appeal_with_validated_bill())

    escalated = validate_success(api_client.resolve_appeal(
        ctx["appeal"]["id"], {"resolution": "ESCALATE"},
        client_headers_for(ctx["client"])), 200)
    assert escalated["appeal_status"] == "ESCALATED"

    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "PROTESTED", (
        "the ESCALATE branch must not finalize the notice"
    )
    bill = validate_success(api_client.get_tax_bill(ctx["bill"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert bill["validated_amount_cents"] == 20000, "no bill revalidation fires"
    assert bill["validation_status"] == "MATCHED"


def test_appeal_board_close_joins_the_fork(api):
    """PRD §3.5: "An escalated appeal concludes when an `AssessorClerk` closes it
    with the board's decision value — `board_value_cents` must be present and
    strictly greater than zero — which moves the appeal from `ESCALATED` to
    `CLOSED`, records the board value, and finalizes the notice at
    `final_value_cents` equal to `board_value_cents` with the same bill and
    forecast cascade as acceptance, appending `APPEAL_RESOLVED`."

    Design: Difficulty/non_linear_state_machine/appeal_decision_fork_join
    """
    ctx = _drive_to_decided(_setup_decided_appeal_with_validated_bill())
    validate_success(api_client.resolve_appeal(
        ctx["appeal"]["id"], {"resolution": "ESCALATE"},
        client_headers_for(ctx["client"])), 200)

    closed = validate_success(api_client.close_appeal(
        ctx["appeal"]["id"], {"board_value_cents": 550000}, CLERK), 200)
    assert_appeal(closed)
    assert closed["appeal_status"] == "CLOSED"
    assert closed["board_value_cents"] == 550000

    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "FINALIZED"
    assert notice["final_value_cents"] == 550000

    bill = validate_success(api_client.get_tax_bill(ctx["bill"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert bill["validated_amount_cents"] == 13750, "round_half_up(550000 * 0.025)"
    assert bill["validation_status"] == "DISCREPANCY", "variance 6250 exceeds 100"
    assert bill["variance_cents"] == 6250


def test_finalized_notice_beats_protest_window(api):
    """PRD §2.9: "Incoming requests are checked against a fixed, ascending
    sequence of rules, and the first failing rule determines the error response —
    earlier checks mask later ones." and "8. Notice appealability: an appeal may
    be created only on a notice in `RECEIVED` or `ACCEPTED` status —
    `ERR_NOTICE_NOT_APPEALABLE` (HTTP 409)." and "15. Protest window: the current
    clock date must be on or before the notice's protest deadline —
    `ERR_PROTEST_WINDOW_CLOSED` (HTTP 422)." and PRD §3.5: "if the clock advances
    past the `protest_deadline_date` while the notice is still `RECEIVED` or
    `ACCEPTED` and no appeal has been filed, the sweep finalizes the notice"

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_protest_window
    """
    # Notice stays RECEIVED; the clock jump past the protest deadline finalizes
    # it, so the appeal fails the state gate (which outranks the window gate).
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "W1", "acquisition_cost_cents": 800000},
        accept=False,
    )
    set_logical_clock("2027-06-15T00:00:00Z")

    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "FINALIZED"
    assert notice["final_value_cents"] == 800000

    res = api_client.create_appeal(
        ctx["notice"]["id"],
        create_appeal_payload(claimed_value_cents=700000,
                              grounds="late and finalized"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_NOTICE_NOT_APPEALABLE, expected_status=409)


def test_finalized_accepted_notice_also_beats_protest_window(api):
    """PRD §2.9: "8. Notice appealability: an appeal may be created only on a
    notice in `RECEIVED` or `ACCEPTED` status — `ERR_NOTICE_NOT_APPEALABLE`
    (HTTP 409)." and "15. Protest window: the current clock date must be on or
    before the notice's protest deadline — `ERR_PROTEST_WINDOW_CLOSED` (HTTP 422)."
    and PRD §3.5: "the sweep finalizes the notice: `final_value_cents` is set to
    the `notice_value_cents`, a `FILED` rendition linked to the notice moves to
    `ACCEPTED`, and `NOTICE_FINALIZED` is appended to the audit trail."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_protest_window
    """
    # Notice ACCEPTED first, then the clock jump finalizes it; the appeal now
    # fails both rule 8 and rule 15, and the state error must win.
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "W2", "acquisition_cost_cents": 800000},
        accept=True,
    )
    set_logical_clock("2027-06-15T00:00:00Z")

    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "FINALIZED"
    rendition = validate_success(api_client.get_rendition(ctx["rendition"]["id"],
                                                          ctx["analyst"]["headers"]), 200)
    assert rendition["rendition_status"] == "ACCEPTED"

    res = api_client.create_appeal(
        ctx["notice"]["id"],
        create_appeal_payload(claimed_value_cents=700000,
                              grounds="late and finalized"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_NOTICE_NOT_APPEALABLE, expected_status=409)

    appeals = validate_success(api_client.list_appeals(ctx["notice"]["id"],
                                                       ctx["analyst"]["headers"]), 200)
    assert appeals == [], "a rejected appeal persists no record"
    events = list_audit_events(ctx["client"]["id"])
    assert "NOTICE_FINALIZED" in audit_event_types(events)


def test_appeal_withdraw_after_decision_rejected(api):
    """PRD §3.5: "Before any decision, a `TaxAnalyst` may withdraw an appeal in
    `FILED` or `HEARING_SCHEDULED` status." and "Appeal actions are gated by
    status throughout — recording a decision before a hearing is scheduled,
    resolving before a decision exists, closing from `FILED`, or taking any action
    on a `CLOSED` or `WITHDRAWN` appeal is rejected with
    `ERR_APPEAL_NOT_ACTIONABLE` (HTTP 409)."

    Design: Corner/state_machines/appeal_withdraw_after_decision_rejected
    """
    ctx = setup_decided_appeal(
        claimed_value_cents=700000, decided_value_cents=700000,
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "W1", "acquisition_cost_cents": 800000},
    )
    assert ctx["appeal"]["appeal_status"] == "DECIDED"

    res = api_client.withdraw_appeal(ctx["appeal"]["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_APPEAL_NOT_ACTIONABLE, expected_status=409)

    appeal = validate_success(api_client.get_appeal(ctx["appeal"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert appeal["appeal_status"] == "DECIDED"


def test_appeal_withdraw_restores_notice_prior_status(api):
    """PRD §3.5: "Withdrawal moves the appeal to `WITHDRAWN` and returns the
    notice from `PROTESTED` to its pre-appeal standing: `RECEIVED` if it had never
    been accepted, `ACCEPTED` if it had."

    Design: Corner/state_machines/appeal_withdraw_restores_notice_prior_status
    """
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "RS1", "acquisition_cost_cents": 800000},
        accept=True,
    )
    appeal = validate_success(api_client.create_appeal(
        ctx["notice"]["id"], create_appeal_payload(claimed_value_cents=700000),
        ctx["analyst"]["headers"]), 201)
    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "PROTESTED"

    withdrawn = validate_success(api_client.withdraw_appeal(
        appeal["id"], ctx["analyst"]["headers"]), 200)
    assert withdrawn["appeal_status"] == "WITHDRAWN"

    restored = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                      ctx["analyst"]["headers"]), 200)
    assert restored["notice_status"] == "ACCEPTED", (
        "the notice returns to its pre-appeal standing, not to RECEIVED"
    )


def test_appeal_action_after_close_rejected(api):
    """PRD §3.5: "Appeal actions are gated by status throughout — recording a
    decision before a hearing is scheduled, resolving before a decision exists,
    closing from `FILED`, or taking any action on a `CLOSED` or `WITHDRAWN` appeal
    is rejected with `ERR_APPEAL_NOT_ACTIONABLE` (HTTP 409)." and "The client may
    subsequently close the accepted appeal, moving it to `CLOSED`."

    Design: Corner/state_machines/appeal_action_after_close_rejected
    """
    ctx = setup_decided_appeal(
        claimed_value_cents=700000, decided_value_cents=700000,
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "CL1", "acquisition_cost_cents": 800000},
    )
    validate_success(api_client.resolve_appeal(
        ctx["appeal"]["id"], {"resolution": "ACCEPT"},
        client_headers_for(ctx["client"])), 200)
    closed = validate_success(api_client.close_appeal(
        ctx["appeal"]["id"], {}, client_headers_for(ctx["client"])), 200)
    assert closed["appeal_status"] == "CLOSED"

    res = api_client.withdraw_appeal(ctx["appeal"]["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_APPEAL_NOT_ACTIONABLE, expected_status=409)

    appeal = validate_success(api_client.get_appeal(ctx["appeal"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert appeal["appeal_status"] == "CLOSED"
    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "FINALIZED"
    assert notice["final_value_cents"] == 700000


def test_appeal_claim_above_notice_rejected(api):
    """PRD §3.5: "The claimed value may not exceed the `notice_value_cents`
    (otherwise `ERR_CLAIM_EXCEEDS_NOTICE`, HTTP 422)"

    Design: Corner/validations/appeal_claim_above_notice_rejected
    """
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "CM1", "acquisition_cost_cents": 800000},
        accept=False,
    )
    res = api_client.create_appeal(
        ctx["notice"]["id"],
        create_appeal_payload(claimed_value_cents=900000,
                              grounds="claim above notice"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_CLAIM_EXCEEDS_NOTICE, expected_status=422)


def test_client_cannot_resolve_other_clients_appeal_forbidden(api):
    """PRD §3.5: "The acting client's `X-User-ID` must equal the client reached by
    walking the appeal's notice to its rendition and reading that rendition's
    `client_id`; anyone else is refused with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/client_cannot_resolve_other_clients_appeal_forbidden
    """
    ctx = setup_decided_appeal(
        claimed_value_cents=700000, decided_value_cents=700000,
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "OW1", "acquisition_cost_cents": 800000},
    )
    other_client = create_client_account(legal_name="OwnerTwo",
                                         contact_email="o2@x.com")

    res = api_client.resolve_appeal(ctx["appeal"]["id"], {"resolution": "ACCEPT"},
                                    client_headers_for(other_client))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    appeal = validate_success(api_client.get_appeal(ctx["appeal"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert appeal["appeal_status"] == "DECIDED"
