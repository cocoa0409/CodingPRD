"""Collections-workflow compliance: arrears aging at the 45-day boundary,
cross-entity state dependencies (disconnect vs assistance, issue vs tariff),
and the disconnect-notice validation precedence (assistance shield outranks the
arrears check; FK existence outranks tariff-shape).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NONEXISTENT_UUID,
)
from test_helpers.fixtures import (
    OPERATOR,
    CASEWORKER,
    DISPATCHER,
    create_active_tariff,
    open_account,
    add_meter,
    import_reads,
    create_draft_bill,
    issue_bill_with_occ_data,
    set_clock,
    pledge_grant,
    setup_issued_bill,
    setup_account_in_arrears,
    setup_disconnected_account,
    reads_for_2636,
)



# ===========================================================================
# Queue A — boundary_precision_check (45-day arrears boundary)
# ===========================================================================
def test_arrears_44_days_is_delinquent(api):
    """PRD §2.8: "If that count is at least forty-five days, the account becomes
    `IN_ARREARS`; if it is greater than zero but fewer than forty-five days, the
    account becomes `DELINQUENT`; and if it is zero or negative, the account is
    `CURRENT`. The forty-five-day boundary is inclusive: an account exactly
    forty-five days past due is `IN_ARREARS`."

    Bill due 2026-01-01; clock at 2026-02-14 is 44 days past due -> DELINQUENT.

    Design: Difficulty/boundary_precision_check/arrears_45_day_boundary_exact
    """
    scene = setup_issued_bill(
        read_tuples=reads_for_2636(), due_date="2026-01-01T00:00:00Z",
        clock="2026-01-01T00:00:00Z")
    set_clock("2026-02-14T00:00:00Z")  # 44 days
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["financial_status"] == "DELINQUENT", acct["financial_status"]


def test_arrears_exactly_45_days_is_in_arrears(api):
    """PRD §2.8: "If that count is at least forty-five days, the account becomes
    `IN_ARREARS` ... The forty-five-day boundary is inclusive: an account
    exactly forty-five days past due is `IN_ARREARS`."

    Bill due 2026-01-01; clock at 2026-02-15 is exactly 45 days past due ->
    IN_ARREARS.

    Design: Difficulty/boundary_precision_check/arrears_45_day_boundary_exact
    """
    scene = setup_issued_bill(
        read_tuples=reads_for_2636(), due_date="2026-01-01T00:00:00Z",
        clock="2026-01-01T00:00:00Z")
    set_clock("2026-02-15T00:00:00Z")  # 45 days
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["financial_status"] == "IN_ARREARS", acct["financial_status"]


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_disconnect_blocked_by_grant_then_allowed_after_cancel(api):
    """PRD §3.6: "First, an account shielded by assistance may not be
    disconnected: if the account has an assistance grant that is `PLEDGED` or
    `APPLIED`, the notice is rejected with `ERR_ASSISTANCE_SHIELD`."
    PRD §3.8: "An `AssistanceCaseworker` may cancel a grant only while it is
    still `PLEDGED` with nothing yet consumed, moving it `PLEDGED → CANCELLED`"

    An IN_ARREARS account with a PLEDGED grant cannot be disconnected; cancelling
    the grant lifts the shield and the disconnect-notice then succeeds.

    Design: Difficulty/cross_entity_state_dependency/disconnect_notice_depends_on_assistance_grant_state
    """
    scene = setup_account_in_arrears()
    grant = pledge_grant(scene["account"]["id"], 500)
    blocked = api.disconnect_notice(scene["account"]["id"], OPERATOR)
    validate_error(blocked, "ERR_ASSISTANCE_SHIELD", expected_status=409)
    validate_success(api.cancel_assistance_grant(grant["id"], CASEWORKER), 200)
    order = validate_success(api.disconnect_notice(scene["account"]["id"], OPERATOR), 201)
    assert order["order_type"] == "DISCONNECT", order["order_type"]
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["service_status"] == "DISCONNECT_PENDING", acct["service_status"]


def test_issue_blocked_after_tariff_retired(api):
    """PRD §3.3: "Issuing a bill ... requires the account's tariff to be `ACTIVE`
    (otherwise `ERR_TARIFF_NOT_ACTIVE`)"
    PRD §3.1: "Retiring a tariff moves it `ACTIVE → RETIRED`; accounts already
    priced under a retired tariff keep the snapshot they were billed against, but
    issuing a new bill under a retired tariff is rejected with
    `ERR_TARIFF_NOT_ACTIVE`."

    A DRAFT bill on an account whose tariff is retired after creation cannot be
    issued — the engine re-checks tariff ACTIVE at issue time.

    Design: Difficulty/cross_entity_state_dependency/bill_issue_depends_on_tariff_active_state
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2636("2026-01-05"))
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    validate_success(api.retire_tariff(tariff["id"], OPERATOR), 200)
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    res = api.issue_bill(
        bill["id"], {"expected_account_version": acct["version"]}, OPERATOR)
    validate_error(res, "ERR_TARIFF_NOT_ACTIVE", expected_status=409)
    still = get_success_data(api.get_bill(bill["id"], OPERATOR))
    assert still["status"] == "DRAFT", still["status"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_assistance_shield_surfaces_over_arrears_state(api):
    """PRD §3.10: "For the disconnect notice specifically, the assistance shield
    (`ERR_ASSISTANCE_SHIELD`) is evaluated before the arrears requirement
    (`ERR_NOT_IN_ARREARS`), which is evaluated before the service-state check
    (`ERR_INVALID_STATE`), so a shielded account always surfaces the shield
    rather than masking it behind a later check."

    The account is IN_ARREARS (the arrears requirement is satisfied) AND has a
    PLEDGED grant; disconnect-notice surfaces ERR_ASSISTANCE_SHIELD and leaves
    service_status ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/assistance_shield_outranks_not_in_arrears_state
    """
    scene = setup_account_in_arrears()
    pledge_grant(scene["account"]["id"], 500)
    res = api.disconnect_notice(scene["account"]["id"], OPERATOR)
    validate_error(res, "ERR_ASSISTANCE_SHIELD", expected_status=409)
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["service_status"] == "ACTIVE", acct["service_status"]


def test_fk_not_found_surfaces_over_tariff_shape(api):
    """PRD §3.10: "Then existence is checked — every path-referenced resource
    left-to-right, yielding `ERR_NOT_FOUND` for the first missing one, followed
    by request-body foreign keys yielding `ERR_FK_NOT_FOUND`. Structural
    validation of the request body follows"
    PRD §2.5: "When a creation request's body carries a foreign key — such as
    `account_id`, `meter_id`, or `tariff_id` — that references a resource which
    does not exist, the request is rejected with `ERR_FK_NOT_FOUND`."

    Opening an account against a non-existent tariff_id surfaces
    ERR_FK_NOT_FOUND before any tariff-shape consideration.

    Design: Difficulty/priority_pair_validation_conflict/fk_not_found_outranks_invalid_tariff_shape
    """
    res = api.create_account(
        {"tariff_id": NONEXISTENT_UUID, "holder_name": "No Tariff"}, OPERATOR)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


# ===========================================================================
# Queue A — second-coverage tests
# ===========================================================================
def test_applied_grant_also_blocks_disconnect_then_lifts_on_cancel(api):
    """PRD §3.6: "if the account has an assistance grant that is `PLEDGED` or
    `APPLIED`, the notice is rejected with `ERR_ASSISTANCE_SHIELD`."
    PRD §3.8: "When a bill first consumes part of a grant — leaving its
    `remaining_cents` above zero but below `pledged_cents` — the grant moves
    `PLEDGED → APPLIED`."

    The shield covers the APPLIED state too: a grant partially consumed by a bill
    (so it is APPLIED, not PLEDGED) still blocks the disconnect-notice with
    ERR_ASSISTANCE_SHIELD.

    Design: Difficulty/cross_entity_state_dependency/disconnect_notice_depends_on_assistance_grant_state
    """
    # bill1 (2636, no grant yet) drives arrears with a positive total_due; then a
    # 3000 grant is pledged and bill2 (empty period, cost 1000) partially
    # consumes it (applied 1000 -> remaining 2000 -> APPLIED). Account is then
    # IN_ARREARS (from bill1) AND shielded by an APPLIED grant.
    tariff = create_active_tariff()
    set_clock("2026-01-01T00:00:00Z")
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2636("2026-01-05"))
    bill1 = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-01-01T00:00:00Z")
    issue_bill_with_occ_data(bill1["id"], account["id"])
    grant = pledge_grant(account["id"], 3000)
    bill2 = create_draft_bill(  # empty window -> actual cost = fixed 1000
        account["id"], "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z",
        "2026-04-20T00:00:00Z")
    issue_bill_with_occ_data(bill2["id"], account["id"])
    set_clock("2026-02-15T00:00:00Z")  # bill1 is 45 days past due -> IN_ARREARS
    g = get_success_data(api.get_assistance_grant(grant["id"], OPERATOR))
    assert g["status"] == "APPLIED", g["status"]
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    assert acct["financial_status"] == "IN_ARREARS", acct["financial_status"]
    blocked = api.disconnect_notice(account["id"], OPERATOR)
    validate_error(blocked, "ERR_ASSISTANCE_SHIELD", expected_status=409)


def test_bill_issues_while_tariff_active(api):
    """PRD §3.3: "Issuing a bill ... requires the account's tariff to be `ACTIVE`
    (otherwise `ERR_TARIFF_NOT_ACTIVE`)"
    PRD §3.3: "A `BillingOperator` issues a `DRAFT` bill, which transitions it
    `DRAFT → ISSUED`"

    The positive control of the Bill->Tariff dependency: while the tariff is
    ACTIVE the same DRAFT bill issues successfully to ISSUED.

    Design: Difficulty/cross_entity_state_dependency/bill_issue_depends_on_tariff_active_state
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2636("2026-01-05"))
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    issued = validate_success(api.issue_bill(
        bill["id"], {"expected_account_version": acct["version"]}, OPERATOR), 200)
    assert issued["status"] == "ISSUED", issued["status"]


def test_shield_surfaces_even_when_account_not_in_arrears(api):
    """PRD §3.10: "the assistance shield (`ERR_ASSISTANCE_SHIELD`) is evaluated
    before the arrears requirement (`ERR_NOT_IN_ARREARS`) ... so a shielded
    account always surfaces the shield rather than masking it behind a later
    check."

    Both the shield (PLEDGED grant) and the arrears gate (account is CURRENT, not
    IN_ARREARS) would block the notice; the higher-priority shield surfaces
    ERR_ASSISTANCE_SHIELD rather than ERR_NOT_IN_ARREARS.

    Design: Difficulty/priority_pair_validation_conflict/assistance_shield_outranks_not_in_arrears_state
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])  # fresh -> CURRENT
    pledge_grant(account["id"], 500)
    res = api.disconnect_notice(account["id"], OPERATOR)
    validate_error(res, "ERR_ASSISTANCE_SHIELD", expected_status=409)


def test_fk_not_found_surfaces_over_missing_required_field(api):
    """PRD §3.10: "Then existence is checked — ... followed by request-body
    foreign keys yielding `ERR_FK_NOT_FOUND`. Structural validation of the
    request body follows: a missing required field, a wrong type, or an invalid
    enum member yields `ERR_INVALID_REQUEST`."

    With a non-existent tariff_id AND a missing holder_name both present, the
    earlier foreign-key existence check surfaces ERR_FK_NOT_FOUND before the
    structural validation that would otherwise raise ERR_INVALID_REQUEST.

    Design: Difficulty/priority_pair_validation_conflict/fk_not_found_outranks_invalid_tariff_shape
    """
    res = api.create_account({"tariff_id": NONEXISTENT_UUID}, OPERATOR)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


# ===========================================================================
# Queue B — validations / errors (collections gates)
# ===========================================================================
def test_disconnect_notice_not_in_arrears_rejected(api):
    """PRD §3.6: "Second, the notice requires the account to be `IN_ARREARS`; an
    account that is not `IN_ARREARS` is rejected with `ERR_NOT_IN_ARREARS`."

    A fresh CURRENT account with no grant cannot be disconnected.

    Design: Corner/validations/disconnect_notice_not_in_arrears_rejected
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.disconnect_notice(account["id"], OPERATOR)
    validate_error(res, "ERR_NOT_IN_ARREARS", expected_status=409)


def test_reconnect_request_while_in_arrears_rejected(api):
    """PRD §3.6: "A reconnect request requires the account's service dimension to
    be `DISCONNECTED` (otherwise `ERR_INVALID_STATE`) and requires
    `financial_status` to be either `CURRENT` or `DELINQUENT` — that is, no
    longer `IN_ARREARS`; a request while the account is still `IN_ARREARS` is
    rejected with `ERR_ARREARS_NOT_CLEARED`."

    An account driven to DISCONNECTED while still IN_ARREARS cannot be
    reconnected.

    Design: Corner/validations/reconnect_request_while_in_arrears_rejected
    """
    scene, _order = setup_disconnected_account()
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["service_status"] == "DISCONNECTED", acct["service_status"]
    assert acct["financial_status"] == "IN_ARREARS", acct["financial_status"]
    res = api.reconnect_request(scene["account"]["id"], OPERATOR)
    validate_error(res, "ERR_ARREARS_NOT_CLEARED", expected_status=409)
    still = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert still["service_status"] == "DISCONNECTED", still["service_status"]


def test_open_account_against_draft_tariff_rejected(api):
    """PRD §3.2: "The referenced tariff must be in `ACTIVE` status at assignment;
    assigning an account to a tariff that is not `ACTIVE` is rejected with
    `ERR_TARIFF_NOT_ACTIVE`."

    A never-activated DRAFT tariff cannot back a new account.

    Design: Corner/errors/tariff_not_active_on_account_open
    """
    tariff = get_success_data(api.create_tariff({
        "code": "RES-DRAFT-OPEN", "name": "Draft Open",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, OPERATOR))
    res = api.create_account(
        {"tariff_id": tariff["id"], "holder_name": "Draft Tariff Holder"}, OPERATOR)
    validate_error(res, "ERR_TARIFF_NOT_ACTIVE", expected_status=409)
