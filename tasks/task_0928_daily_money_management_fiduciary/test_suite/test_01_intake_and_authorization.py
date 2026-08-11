"""Intake, decisional capacity, and the authorization instrument."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_authorization,
    assert_client,
    assert_same_instant,
    change_client_status,
    create_account,
    create_active_authorization,
    create_active_client,
    create_client,
    create_client_payload,
    draft_authorization,
    enrol_family_recipient,
    execute_authorization,
    list_ledger_entries,
    make_client_headers,
    payment_request,
    read_account,
    read_authorization,
    read_budget_category,
    read_bond,
    read_client,
    read_family_recipient,
    read_payment,
    record_consent,
    register_bond,
    revoke_authorization,
    run_checkpoint,
    schedule_payment,
    set_clock,
    setup_billpay_world,
    TEST_USERS,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_new_client_lands_in_intake_with_no_capacity_finding():
    """PRD §3.1: "The new client lands in status `INTAKE` with
    `capacity_determination` reading `NOT_DETERMINED`, and with `activated_on`,
    `closed_on` and `capacity_determined_on` all null."
    PRD §2.5: "`version` is an integer that begins at 1 when the row is created
    and increases by exactly 1 each time the platform counts the row as mutated"

    Design: Corner/entities/corner_client_creation_returns_intake_status_and_system_fields
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api_client.create_client(
        create_client_payload(intake_reference="INT-C001"), MANAGER
    )
    client = validate_success(response, 201)

    assert_client(client)
    assert client["status"] == "INTAKE"
    assert client["capacity_determination"] == "NOT_DETERMINED"
    assert client["capacity_determined_on"] is None
    assert client["activated_on"] is None
    assert client["closed_on"] is None
    assert client["version"] == 1


def test_reading_an_unknown_client_id_returns_the_client_specific_not_found_code():
    """PRD §2.7: "Two distinct 404 codes report the failure and the split is by
    entity type, not by position: a missing `Client` yields
    `ERR_CLIENT_NOT_FOUND`, and a missing row of any other type — an
    authorization, an account, a payee, a budget line, a payment, a dispute, a
    period, a statement line, a ledger entry, an alert, an application, a bond,
    a recipient, a report, or a coordination request — yields
    `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/corner_client_get_with_unknown_uuid_returns_not_found
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api_client.get_client(NON_EXISTENT_UUID, MANAGER)

    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)


def test_activation_before_a_capacity_finding_is_refused():
    """PRD §3.1: "Moving `INTAKE` → `ACTIVE` requires the client to be in
    `INTAKE` and requires `capacity_determination` to be anything other than
    `NOT_DETERMINED` — a violation of either is `ERR_INVALID_STATE`; on success
    the current logical date is written to `activated_on`."

    Design: Corner/state_machines/corner_client_activation_without_capacity_determination_is_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_client(intake_reference="INT-C012")

    response = api_client.change_client_status(
        client["id"], {"to_status": "ACTIVE"}, MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = read_client(client["id"])
    assert after["status"] == "INTAKE"
    assert after["activated_on"] is None


def test_executing_a_second_instrument_supersedes_the_first_without_a_cascade():
    """PRD §3.1: "On execution, the current logical instant is written to
    `executed_at`, and **every other instrument of the same client whose
    `status` is `ACTIVE` moves to `SUPERSEDED`**."
    PRD §3.1: "Superseding is a bookkeeping relabel and nothing more: it does
    **not** run the revocation cascade, because the successor instrument keeps
    the client's scheduled payments, family subscriptions and pending benefit
    applications alive."

    Design: Corner/state_machines/corner_executing_a_second_instrument_supersedes_the_first
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(determination="LACKS_CAPACITY", intake_reference="INT-C011")
    first = create_active_authorization(
        client["id"], scope_tier="FULL_AGENCY", instrument_reference="AGR-C011-A"
    )
    second = draft_authorization(
        client["id"],
        scope_tier="REP_PAYEE",
        instrument_reference="AGR-C011-B",
        effective_date="2026-06-01",
        expiry_date="2027-05-31",
    )

    executed = execute_authorization(second["id"])

    assert_authorization(executed)
    assert executed["status"] == "ACTIVE"
    assert_same_instant(
        executed["executed_at"], "2026-06-01T09:00:00Z", "Authorization.executed_at"
    )
    superseded = read_authorization(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["cascaded_payments_cancelled"] == 0
    assert superseded["revoked_at"] is None


def test_checkpoint_expires_an_instrument_only_the_day_after_its_expiry_date():
    """PRD §3.9: "It moves every `ACTIVE` authorization instrument whose
    `expiry_date` falls **strictly before** the current logical date into
    `EXPIRED`, counting them as `authorizations_expired` — an instrument is
    still in force on its expiry date itself, so only the day after does it
    sweep."

    Design: Corner/state_machines/corner_checkpoint_expires_a_lapsed_authorization
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-C013")
    authorization = create_active_authorization(
        client["id"],
        scope_tier="LIMITED_BILLPAY",
        instrument_reference="AGR-C013",
        effective_date="2026-01-01",
        expiry_date="2026-06-30",
    )

    set_clock("2026-06-30T23:00:00Z")
    on_expiry_day = run_checkpoint()
    assert on_expiry_day["authorizations_expired"] == 0
    assert read_authorization(authorization["id"])["status"] == "ACTIVE"

    set_clock("2026-07-01T00:30:00Z")
    day_after = run_checkpoint()

    assert day_after["authorizations_expired"] == 1
    assert read_authorization(authorization["id"])["status"] == "EXPIRED"


def test_suspending_and_reinstating_a_client_cycles_the_family_subscription():
    """PRD §3.1: "Moving `ACTIVE` → `SUSPENDED` suspends the file temporarily,
    and it carries a cascade: every family recipient of that client whose
    `subscription_status` is `ACTIVE` moves to `SUSPENDED`. The reverse move,
    `SUSPENDED` → `ACTIVE`, is symmetric — every family recipient of that
    client whose `subscription_status` is `SUSPENDED` moves back to `ACTIVE`."

    Design: Corner/state_machines/corner_client_suspend_and_reinstate_cycles_the_family_subscription
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-C015")
    authorization = create_active_authorization(
        client["id"], scope_tier="FULL_AGENCY", instrument_reference="AGR-C015"
    )
    recipient = enrol_family_recipient(client["id"], authorization["id"])
    record_consent(
        recipient["id"], ["BUDGET", "CARE_TEAM"], headers=make_client_headers(client["id"])
    )

    change_client_status(client["id"], "SUSPENDED", note="Client hospitalised.")
    assert read_family_recipient(recipient["id"])["subscription_status"] == "SUSPENDED"

    change_client_status(client["id"], "ACTIVE")

    reinstated = read_family_recipient(recipient["id"])
    assert reinstated["subscription_status"] == "ACTIVE"
    assert reinstated["permitted_categories"] == ["BUDGET", "CARE_TEAM"]
    assert read_client(client["id"])["status"] == "ACTIVE"


def test_revoking_an_instrument_cancels_its_scheduled_payment():
    """PRD §3.1: "Caused by step 1: every payment whose governing instrument is
    this one and whose `settlement_status` is `SCHEDULED` moves `SCHEDULED` →
    `CANCELLED`."
    PRD §3.1: "The instrument then records what it destroyed:
    `cascaded_payments_cancelled`, `cascaded_recipients_terminated` and
    `cascaded_applications_withdrawn` are set to the respective counts, which
    are zero when nothing of that kind was outstanding."

    Design: Difficulty/transitive_cascade/authorization_revoke_cancels_payment_and_restores_budget_line
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    revoked = revoke_authorization(
        world["authorization"]["id"], "Client executed a successor power of attorney."
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["cascaded_payments_cancelled"] == 1
    cancelled = read_payment(payment["id"])
    assert cancelled["settlement_status"] == "CANCELLED"
    assert cancelled["approval_status"] == "APPROVED"


def test_revocation_cascade_restores_the_budget_line_account_and_bond():
    """PRD §3.1: "Caused by step 2: each of those cancellations decrements the
    payment's budget line's `committed_cents` by that payment's `amount_cents`
    and recomputes that line's `remaining_cents`, `variance_full_cents`,
    `variance_ptd_cents` and `variance_direction`."
    PRD §3.1: "Also caused by step 2: each cancellation decrements the
    account's `committed_disbursements_cents` by that payment's
    `total_charge_cents`, recomputes the account's `available_balance_cents`,
    and decrements the `IN_FORCE` bond's `exposure_committed_cents` by that
    payment's `amount_cents`."
    PRD §3.4: "Crucially, **cancellation appends no ledger entry at all** — no
    money ever left the account, so there is nothing to record and there is
    deliberately no cancellation entry type in the ledger's vocabulary."

    Design: Difficulty/transitive_cascade/authorization_revoke_cancels_payment_and_restores_budget_line
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    schedule_payment(world, amount_cents=80000, channel="ACH")

    revoke_authorization(
        world["authorization"]["id"], "Client executed a successor power of attorney."
    )

    line = read_budget_category(world["budget_category"]["id"])
    assert line["committed_cents"] == 0
    assert line["remaining_cents"] == 300000
    assert line["variance_full_cents"] == 300000

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["available_balance_cents"] == 5000000

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 0

    assert list_ledger_entries(world["account"]["id"]) == []


def test_scheduling_a_payment_for_a_suspended_client_is_refused():
    """PRD §2.9 rung 11: "**Client active.** The `Client` governing the request
    has status `ACTIVE`; otherwise `ERR_CLIENT_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_depends_on_client_status
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    change_client_status(
        world["client"]["id"],
        "SUSPENDED",
        note="Guardianship petition pending in probate court.",
    )

    response = payment_request(world, amount_cents=80000, channel="ACH")

    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value, 409)


def test_only_the_client_axis_moved_when_a_payment_is_refused_for_client_status():
    """PRD §3.1: "Moving `ACTIVE` → `SUSPENDED` suspends the file temporarily,
    and it carries a cascade: every family recipient of that client whose
    `subscription_status` is `ACTIVE` moves to `SUSPENDED`."
    PRD §2.5: "Third, **a rejected request increments nothing**: when any rung
    of §2.9 refuses a request, no version anywhere moves and no field anywhere
    is written, apart from the single audit entry the request appends."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_depends_on_client_status
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    change_client_status(
        world["client"]["id"],
        "SUSPENDED",
        note="Guardianship petition pending in probate court.",
    )

    payment_request(world, amount_cents=80000, channel="ACH")

    assert read_client(world["client"]["id"])["status"] == "SUSPENDED"
    assert read_authorization(world["authorization"]["id"])["status"] == "ACTIVE"
    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
