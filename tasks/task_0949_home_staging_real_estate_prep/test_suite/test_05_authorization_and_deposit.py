"""Authorizing the contract, the authority ceilings and the deposit that follows."""

from test_helpers import (
    CLERK,
    COORD,
    ApiErrorId,
    assert_deposit,
    assert_deposit_conservation,
    assert_money,
    assert_same_instant,
    make_listing_agent_headers,
    make_seller_headers,
    setup_occupied_agent_draft,
    setup_occupied_agent_over_cap_draft,
    setup_occupied_over_hard_cap_draft,
    setup_occupied_pay_at_closing_authorized,
    setup_occupied_small_contract_authorized,
    setup_vacant_project_draft,
    setup_vacant_project_staged,
    validate_error,
    validate_success,
)


def test_agent_over_own_cap_on_a_seller_payer_project_needs_seller_consent(api):
    """PRD §2.7: "Rung 41: when a `ListingAgent` authorizes above their own
    `effective_authorization_cap`, the payer client — who must be of `client_type` `SELLER`
    — carries `consent_on_file` true; otherwise `ERR_SELLER_CONSENT_REQUIRED`, HTTP 403."
    PRD §3.2: "A listing agent reaching above their own ceiling with no seller consent on
    file is separately refused with `ERR_SELLER_CONSENT_REQUIRED`."

    Design: Corner/validations/listing_agent_over_own_cap_on_seller_payer_needs_consent
    """
    ctx = setup_vacant_project_draft()

    resp = api.authorize_project(ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"]))

    validate_error(resp, ApiErrorId.ERR_SELLER_CONSENT_REQUIRED.value, 403)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "DRAFT"
    assert_money(project["contract_value"], 7690.00, "project.contract_value")
    agent = validate_success(api.get_client(ctx["agent_id"], COORD))
    assert_money(agent["effective_authorization_cap"], 4500.00, "effective_authorization_cap")
    seller = validate_success(api.get_client(ctx["seller_id"], COORD))
    assert seller["consent_on_file"] is False


def test_seller_consent_unblocks_the_over_cap_agent_authorization(api):
    """PRD §3.1: "A seller — and only the seller in question, acting on their own record, or
    an operator superuser — may set that flag true; it is the standing permission that lets
    their listing agent authorize a project above the agent's own ceiling."
    PRD §3.2: "`authorized_by_client_id` is set to the acting principal and
    `authorized_amount` is snapshotted from the current `contract_value`, so that a later
    upgrade pushing past that snapshot re-opens the cap question."
    PRD §3.3: "Under `SELLER` the homeowner is billed and the deposit is 30 percent."
    PRD §3.2: "And a deposit row is created in state `REQUIRED` carrying its computed
    `amount`."

    Design: Corner/validations/seller_consent_unblocks_the_over_cap_agent_authorization
    """
    ctx = setup_vacant_project_draft()
    validate_success(api.record_seller_consent(
        ctx["seller_id"], make_seller_headers(ctx["seller_id"])))

    resp = api.authorize_project(ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"]))

    validate_success(resp)
    seller = validate_success(api.get_client(ctx["seller_id"], COORD))
    assert seller["consent_on_file"] is True
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "AUTHORIZED"
    assert project["authorized_by_client_id"] == ctx["agent_id"]
    assert_money(project["authorized_amount"], 7690.00, "project.authorized_amount")
    deposits = validate_success(api.list_deposits(CLERK, params={"project_id": ctx["proj_id"]}))
    assert len(deposits) == 1
    assert_deposit(deposits[0])
    assert_money(deposits[0]["amount"], 2307.00, "deposit.amount")
    assert deposits[0]["state"] == "REQUIRED"


def test_agent_over_cap_on_an_agent_payer_project_is_a_cap_breach(api):
    """PRD §2.7: "Rung 39: the acting principal's `effective_authorization_cap` is greater
    than or equal to the project's `contract_value`, the comparison being inclusive so that
    headroom of exactly 0.00 authorizes; otherwise `ERR_AUTHORIZATION_CAP_EXCEEDED`, HTTP
    403."
    PRD §3.2: "Negative headroom is authorized only when the payer client carries
    `consent_on_file` true; otherwise it is refused with `ERR_AUTHORIZATION_CAP_EXCEEDED`."

    Design: Corner/validations/agent_over_cap_on_agent_payer_project_has_no_consent_path
    """
    ctx = setup_occupied_agent_over_cap_draft()

    resp = api.authorize_project(ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"]))

    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_CAP_EXCEEDED.value, 403)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 7445.00, "project.contract_value")
    assert project["workflow_state"] == "DRAFT"


def test_contract_above_the_platform_ceiling_is_refused_even_for_the_seller(api):
    """PRD §2.7: "Rung 40: the project's `contract_value` does not exceed 15000.00,
    regardless of who authorizes and regardless of whether seller consent is on file;
    otherwise `ERR_BROKERAGE_CAP_EXCEEDED`, HTTP 403."
    PRD §3.2: "And above every private arrangement sits the platform's own ceiling: a
    `contract_value` above 15000.00 is refused with `ERR_BROKERAGE_CAP_EXCEEDED` no matter
    who is acting and no matter what consent exists."

    Design: Corner/validations/contract_above_the_brokerage_hard_cap_is_refused_even_for_the_seller
    """
    ctx = setup_occupied_over_hard_cap_draft()

    resp = api.authorize_project(ctx["proj_id"], make_seller_headers(ctx["seller_id"]))

    validate_error(resp, ApiErrorId.ERR_BROKERAGE_CAP_EXCEEDED.value, 403)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 15695.00, "project.contract_value")
    assert project["workflow_state"] == "DRAFT"


def test_authorize_response_already_carries_the_derived_service_window(api):
    """PRD §3.2: "`authorized_at` is stamped with the logical clock. On an `OCCUPIED_PREP`
    project, `service_window_end_date` is derived from that instant."
    PRD §3.2: "`service_window_end_date` is the authorization instant plus 45 days plus the
    `window_extension_count` multiplied by 15 days; on a vacant-arm project it is null."
    PRD §2.4: "The same applies to every computed attribute — a response body reflects
    post-write state, never a snapshot taken before the handler's own effects landed."

    Design: Corner/consistency_model/authorize_response_already_carries_the_derived_service_window
    """
    ctx = setup_occupied_agent_draft()

    resp = api.authorize_project(ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"]))

    data = validate_success(resp)
    assert data["workflow_state"] == "AUTHORIZED"
    assert_money(data["authorized_amount"], 4145.00, "project.authorized_amount")
    assert_same_instant(data["authorized_at"], "2026-06-01T00:00:00Z", "project.authorized_at")
    assert_same_instant(data["service_window_end_date"], "2026-07-16T00:00:00Z",
                        "project.service_window_end_date")
    assert data["pipeline"] == "OCCUPIED_PREP"


def test_authorizing_a_project_twice_is_an_invalid_project_state(api):
    """PRD §2.7: "Rung 19: the project's `workflow_state` is a legal origin for the
    requested transition; otherwise `ERR_PROJECT_INVALID_STATE`, HTTP 409."
    PRD §3.2: "It requires the project to be in `DRAFT` and the consultation to be in
    `SCOPE_APPROVED`, and it runs the authority arithmetic: headroom is the acting
    principal's `effective_authorization_cap` minus the project's `contract_value`, and the
    comparison is inclusive — headroom of exactly 0.00 authorizes."

    Design: Corner/state_machines/project_authorize_twice_rejected_as_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.authorize_project(ctx["proj_id"], make_seller_headers(ctx["seller_id"]))

    validate_error(resp, ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "STAGED"
    assert_money(project["authorized_amount"], 7690.00, "project.authorized_amount")
    deposits = validate_success(api.list_deposits(CLERK, params={"project_id": ctx["proj_id"]}))
    assert len(deposits) == 1, "a refused second authorization creates no second deposit"


def test_a_second_project_on_the_same_property_is_a_duplicate(api):
    """PRD §2.7: "Rung 65: no other project on the same property sits in a `workflow_state`
    other than `CLOSED`; otherwise `ERR_DUPLICATE_ACTIVE_PROJECT`, HTTP 409."
    PRD §3.2: "Creation is refused with `ERR_SCOPE_NOT_APPROVED` unless the named
    consultation is in `SCOPE_APPROVED`, and refused with `ERR_DUPLICATE_ACTIVE_PROJECT` if
    any other project on that same property sits in a `workflow_state` other than `CLOSED`."

    Design: Corner/validations/duplicate_active_project_on_one_property_rejected
    """
    ctx = setup_vacant_project_staged()

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_sig"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PROJECT.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "STAGED"
    projects = validate_success(api.list_projects(COORD))
    assert len(projects) == 1, "the duplicate must not have been stored"


def test_a_deposit_below_the_minimum_cannot_be_collected(api):
    """PRD §2.7: "Rung 67: the deposit's `amount` is either exactly 0.00 or at least 500.00
    at collection; otherwise `ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422."
    PRD §3.3: "A non-zero requirement below the 500.00 minimum is carried onto the deposit
    row exactly as computed and is refused later, at collection, by the fiscal rung: the
    amount is computed honestly and rejected explicitly rather than being quietly lifted."
    PRD §3.3: "Under `AGENT` the listing agent is billed and the deposit is 20 percent of
    the contract value."

    Design: Corner/errors/sub_minimum_deposit_cannot_be_collected
    """
    ctx = setup_occupied_small_contract_authorized()

    resp = api.collect_deposit(ctx["dep_id"], CLERK)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM.value, 422)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 2495.00, "project.contract_value")
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 499.00, "deposit.amount")
    assert deposit["state"] == "REQUIRED"


def test_collecting_a_held_deposit_a_second_time_is_an_invalid_deposit_state(api):
    """PRD §2.7: "Rung 32: the deposit's `state` is a legal origin for the requested
    transition; otherwise `ERR_DEPOSIT_INVALID_STATE`, HTTP 409."
    PRD §3.3: "Collecting the deposit moves it `REQUIRED → HELD`, sets `held_remaining` to
    the full `amount`, and drives the project's `payment_state` `UNBILLED → DEPOSIT_HELD`."

    Design: Corner/state_machines/deposit_collect_twice_rejected_as_deposit_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.collect_deposit(ctx["dep_id"], CLERK)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INVALID_STATE.value, 409)
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert deposit["state"] == "HELD"
    assert_money(deposit["amount"], 2307.00, "deposit.amount")
    assert_money(deposit["held_remaining"], 2307.00, "deposit.held_remaining")
    assert_deposit_conservation(deposit)


def test_scheduling_a_visit_before_the_deposit_is_held_is_refused(api):
    """PRD §2.7: "Rung 66: the project's deposit is in state `HELD` before execution work
    may begin; otherwise `ERR_DEPOSIT_NOT_HELD`, HTTP 402."
    PRD §3.3: "That state is a gate on execution: scheduling visits, scheduling an install
    and completing an install all require the deposit to be `HELD`, and a request that
    arrives earlier is refused with `ERR_DEPOSIT_NOT_HELD` (HTTP 402)."

    Design: Corner/errors/visits_before_the_deposit_is_held_returns_deposit_not_held
    """
    ctx = setup_occupied_agent_draft()
    validate_success(api.authorize_project(
        ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"])))

    resp = api.schedule_visit(ctx["proj_id"], "2026-06-05T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_HELD.value, 402)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "AUTHORIZED"


def test_the_third_service_window_extension_is_refused(api):
    """PRD §2.7: "Rung 64: the project's `window_extension_count` is strictly less than 2;
    otherwise `ERR_WINDOW_EXTENSION_LIMIT`, HTTP 409."
    PRD §3.2: "Extending the window increments `window_extension_count`, re-derives
    `service_window_end_date`, and books an extension fee of 250.00 into the invoice's
    `package` component."
    PRD §3.2: "The count may never reach 2 — the check is strictly less than 2, so at most
    two extensions are ever granted, and a third attempt is `ERR_WINDOW_EXTENSION_LIMIT`."

    Design: Corner/errors/third_service_window_extension_hits_the_limit
    """
    ctx = setup_occupied_agent_draft()
    validate_success(api.authorize_project(
        ctx["proj_id"], make_listing_agent_headers(ctx["agent_id"])))
    validate_success(api.extend_window(ctx["proj_id"], COORD))
    validate_success(api.extend_window(ctx["proj_id"], COORD))

    resp = api.extend_window(ctx["proj_id"], COORD)

    validate_error(resp, ApiErrorId.ERR_WINDOW_EXTENSION_LIMIT.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["window_extension_count"] == 2
    assert_same_instant(project["service_window_end_date"], "2026-08-15T00:00:00Z",
                        "project.service_window_end_date")


def test_the_pay_at_closing_deposit_is_half_the_contract_value(api):
    """PRD §3.3: "Under `PAY_AT_CLOSING` the deposit is 50 percent, taken up front precisely
    because the invoice will not be due until a closing event that may never happen."
    PRD §3.3: "The deposit `amount` is the project's `contract_value` at the instant of
    authorization multiplied by that percentage, rounded half-up to two decimal places, and
    **no floor is applied at this point**."

    Design: Difficulty/compensating_invariant/deposit_apply_then_refund_conserves_the_deposit_amount
    """
    ctx = setup_occupied_pay_at_closing_authorized()

    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))

    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 12395.00, "project.contract_value")
    assert_money(deposit["amount"], 6197.50, "deposit.amount")
    assert deposit["state"] == "REQUIRED"
    assert_deposit_conservation(deposit)
