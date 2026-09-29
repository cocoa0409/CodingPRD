"""Operations guarded on the state of an entity outside the request path."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_settlement_conservation,
    execute_agreement_payload,
    open_audit_finding,
    read_agreement,
    read_distributor,
    read_offer,
    read_settlements,
    read_subscriber_report,
    resolve_audit_finding_payload,
    run_expiration_sweep,
    set_clock,
    setup_issued_settlement,
    setup_network_approved_agreement,
    true_up_payload,
    validate_error,
    validate_success,
)

SHORT_AFFILIATION = {"term_end_utc": "2026-09-01T00:00:00Z"}


def _approved_agreement_with_an_expiring_affiliation():
    return setup_network_approved_agreement(affiliation=SHORT_AFFILIATION)


def test_sweep_expires_an_affiliation_whose_term_end_has_arrived(api):
    """The maintenance pass ages the affiliation out of ACTIVE.

    PRD §3.9: "Affiliation agreements in `ACTIVE` whose `term_end_utc` is at or
    before the clock move to `EXPIRED`, after which no carriage agreement of that
    station may be executed until an `ACTIVE` affiliation exists again."

    Design: Difficulty/cross_entity_state_dependency/agreement_execution_guarded_on_affiliation_agreement_state
    """
    ctx = _approved_agreement_with_an_expiring_affiliation()
    set_clock("2026-09-02T00:00:00Z")

    response = api.run_expiration_sweep({}, TEST_USERS["carriage_admin_headers"])
    counts = validate_success(response, 200)
    assert counts["expired_affiliation_count"] == 1

    affiliations = validate_success(
        api.list_affiliation_agreements(
            ctx["station"]["id"], TEST_USERS["carriage_admin_headers"]
        ),
        200,
    )
    assert [item["status"] for item in affiliations] == ["EXPIRED"]


def test_execution_is_refused_once_the_station_affiliation_has_expired(api):
    """An otherwise executable agreement is blocked by a third entity's state.

    PRD §3.7: "The station must hold an affiliation agreement in status `ACTIVE` at
    the moment of execution, failing which the refusal is
    `ERR_AFFILIATION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/agreement_execution_guarded_on_affiliation_agreement_state
    """
    ctx = _approved_agreement_with_an_expiring_affiliation()
    set_clock("2026-09-02T00:00:00Z")
    run_expiration_sweep()

    response = api.execute_agreement(
        ctx["agreement"]["id"],
        execute_agreement_payload(),
        TEST_USERS["second_group_counsel_headers"],
    )
    validate_error(response, ApiErrorId.ERR_AFFILIATION_NOT_ACTIVE.value, 422)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["execution_status"] == "PENDING_EXECUTION"
    assert agreement["network_approval_status"] == "NETWORK_APPROVED"
    assert agreement["executed_by_user_id"] is None
    assert read_offer(ctx["offer"]["id"])["status"] == "ACCEPTED"


def test_true_up_is_refused_while_the_report_carries_no_adjustment(api):
    """Without a substantiated finding on the report there is nothing to true up.

    PRD §3.9: "A `GroupCounsel` trues up a settlement by supplying a `true_up_note`;
    the settlement must be in `ISSUED`, and the referenced subscriber report's
    `audit_adjustment_subscribers` must be non-zero - an unadjusted report has nothing
    to true up, and the attempt is refused with `ERR_TRUE_UP_NOT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/settlement_true_up_guarded_on_subscriber_report_adjustment_state
    """
    ctx = setup_issued_settlement()
    assert read_subscriber_report(ctx["report"]["id"])["audit_adjustment_subscribers"] == 0

    response = api.true_up_fee_settlement(
        ctx["settlement"]["id"],
        true_up_payload(),
        TEST_USERS["group_counsel_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TRUE_UP_NOT_REQUIRED.value, 422)

    settlement = read_settlements(ctx["agreement"]["id"])[0]
    assert settlement["status"] == "ISSUED"
    assert settlement["basis_variant"] == "AS_REPORTED"
    assert settlement["billable_subscriber_basis_snapshot"] == 100000
    assert settlement["true_up_required"] is False


def test_true_up_succeeds_once_the_report_has_reached_adjusted(api):
    """The same call is permitted after the report's state changes underneath it.

    PRD §3.9: "`true_up_required` is cleared back to false, the parent agreement's
    `lifetime_gross_fee_cents` and `lifetime_net_retained_cents` are re-derived, and
    the distributor's `open_true_up_count` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/settlement_true_up_guarded_on_subscriber_report_adjustment_state
    """
    ctx = setup_issued_settlement()
    set_clock("2027-03-01T00:00:00Z")
    finding = open_audit_finding(
        ctx["report"]["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )
    validate_success(
        api.resolve_audit_finding(
            finding["id"],
            resolve_audit_finding_payload("SUBSTANTIATED"),
            TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )
    assert read_subscriber_report(ctx["report"]["id"])["status"] == "ADJUSTED"

    response = api.true_up_fee_settlement(
        ctx["settlement"]["id"],
        true_up_payload(),
        TEST_USERS["group_counsel_headers"],
    )
    settlement = validate_success(response, 200)

    assert settlement["status"] == "TRUED_UP"
    assert settlement["basis_variant"] == "AUDITED"
    assert settlement["billable_subscriber_basis_snapshot"] == 106000
    assert settlement["gross_fee_cents"] == 26500000
    assert settlement["reverse_comp_cents"] == 14575000
    assert settlement["net_retained_cents"] == 11925000
    assert settlement["true_up_required"] is False
    assert_settlement_conservation(settlement)
    assert read_distributor(ctx["distributor"]["id"])["open_true_up_count"] == 0
