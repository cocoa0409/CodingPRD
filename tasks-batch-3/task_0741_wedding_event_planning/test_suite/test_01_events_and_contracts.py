"""Event founding, the contract state machine, and the event-confirmation gate.

Covers queue B entity-creation / contract-transition corners plus the queue A
non-linear contract revision cycle and the cross-entity confirm-requires-
countersigned dependency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    create_event_payload,
    PLANNER,
    make_client_headers,
    setup_draft_contract_event,
    setup_sent_contract_event,
    setup_signed_contract_event,
    setup_event_in_booking,
)


# ---------------------------------------------------------------------------
# Queue B — entity creation
# ---------------------------------------------------------------------------
def test_create_event_returns_201_envelope(api):
    """PRD §4: "Operations that create a new stand-alone resource return `201 Created`."
    PRD §3.1: "A newly created event opens in `DRAFT` status with every computed budget
    and headcount field at 0 and `active_contract_id` unset."
    PRD §2.4: "The `version` field is an integer that begins at 1 when the resource is
    created and increments by one on every subsequent mutation."

    Design: Corner/entities/create_event_returns_201_with_envelope
    """
    resp = api.create_event(create_event_payload(total_budget_cents=9_000_000), PLANNER)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["committed_spend_cents"] == 0
    assert data["budget_balance_cents"] == 9_000_000


def test_event_system_fields_generated(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
    PRD §2.4: "The `created_at` field is an ISO 8601 UTC timestamp with three
    fractional digits, fixed at creation."
    PRD §3.1: "A newly created event opens in `DRAFT` status with every computed budget
    and headcount field at 0 and `active_contract_id` unset."

    Design: Corner/entities/event_system_fields_generated
    """
    data = validate_success(
        api.create_event(
            create_event_payload(package_type="DAY_OF", total_budget_cents=2_000_000), PLANNER
        ),
        201,
    )
    assert is_valid_uuid(data["id"]), "id must be a bare UUID with no prefix"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["status"] == "DRAFT"


def test_create_event_missing_required_field_rejected(api):
    """PRD §2.7: "Body well-formedness means required fields are present, every
    enumerated field holds a permitted member, and every integer field that must be
    non-negative is non-negative; violations return `ERR_VALIDATION`."

    Design: Corner/entities/create_event_missing_required_field_returns_validation
    """
    payload = create_event_payload()
    del payload["total_budget_cents"]
    validate_error(api.create_event(payload, PLANNER), ApiErrorId.ERR_VALIDATION.value)


def test_create_event_invalid_package_enum_rejected(api):
    """PRD §2.7: "Body well-formedness means required fields are present, every
    enumerated field holds a permitted member, and every integer field that must be
    non-negative is non-negative; violations return `ERR_VALIDATION`."
    PRD §3.1: "The `package_type` is the tier of service and is one of `FULL`,
    `PARTIAL`, or `DAY_OF`."

    Design: Corner/entities/create_event_invalid_package_enum_returns_validation
    """
    validate_error(
        api.create_event(create_event_payload(package_type="GOLD"), PLANNER),
        ApiErrorId.ERR_VALIDATION.value,
    )


# ---------------------------------------------------------------------------
# Queue B — contract state-machine conflicts
# ---------------------------------------------------------------------------
def test_send_contract_not_draft_rejected(api):
    """PRD §3.1: "A `DRAFT` contract is sent to the client, moving `DRAFT → SENT`; this
    is permitted only when the contract is in `DRAFT`, otherwise the attempt is rejected
    with `ERR_CONTRACT_NOT_DRAFT`."

    Design: Corner/state_machines/send_contract_not_draft_returns_conflict
    """
    _event, contract = setup_sent_contract_event()
    validate_error(api.send_contract(contract["id"], PLANNER), ApiErrorId.ERR_CONTRACT_NOT_DRAFT.value)


def test_sign_contract_not_sent_rejected(api):
    """PRD §3.1: "The `Client` who owns the event may sign it, moving `SENT → SIGNED`
    and stamping `signed_at` with the current logical clock; signing requires the
    contract to be `SENT` (otherwise `ERR_CONTRACT_NOT_SENT`) and requires the acting
    client to own the event."

    Design: Corner/state_machines/sign_contract_not_sent_returns_conflict
    """
    event, contract = setup_draft_contract_event()
    validate_error(
        api.sign_contract(contract["id"], make_client_headers(event["id"])),
        ApiErrorId.ERR_CONTRACT_NOT_SENT.value,
    )


def test_countersign_contract_not_signed_rejected(api):
    """PRD §3.1: "A `SIGNED` contract is countersigned by the `Planner`, moving
    `SIGNED → COUNTERSIGNED`; this requires the contract to be `SIGNED`, otherwise
    `ERR_CONTRACT_NOT_SIGNED`."

    Design: Corner/state_machines/countersign_contract_not_signed_returns_conflict
    """
    _event, contract = setup_sent_contract_event()
    validate_error(
        api.countersign_contract(contract["id"], PLANNER),
        ApiErrorId.ERR_CONTRACT_NOT_SIGNED.value,
    )


def test_confirm_event_not_draft_rejected(api):
    """PRD §3.1: "Confirmation requires the event to be in `DRAFT` (otherwise
    `ERR_EVENT_NOT_DRAFT`) and requires the event's active contract to exist and be in
    `COUNTERSIGNED` status; if the active contract is anything other than
    `COUNTERSIGNED`, the confirmation is rejected with `ERR_CONTRACT_NOT_COUNTERSIGNED`."

    Design: Corner/state_machines/confirm_event_not_draft_returns_conflict
    """
    event, _contract = setup_event_in_booking()
    validate_error(api.confirm_event(event["id"], PLANNER), ApiErrorId.ERR_EVENT_NOT_DRAFT.value)


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: contract revision cycle
# ---------------------------------------------------------------------------
def test_request_revision_increments_count_and_returns_to_draft(api):
    """PRD §3.1: "either the `Client` who owns the event or the `Planner` may request a
    revision, moving `SENT → DRAFT` and incrementing `revision_count` by one; this too
    requires the contract to be `SENT` (otherwise `ERR_CONTRACT_NOT_SENT`), and when the
    actor is the client the ownership check applies."

    Design: Difficulty/non_linear_state_machine/contract_revision_cycle
    """
    event, contract = setup_sent_contract_event(package_type="DAY_OF", total_budget_cents=3_000_000)
    data = validate_success(api.request_revision(contract["id"], make_client_headers(event["id"])))
    assert data["status"] == "DRAFT"
    assert data["revision_count"] == 1


def test_contract_cycles_back_to_sent_after_revision(api):
    """PRD §3.1: "This `DRAFT → SENT → DRAFT` loop may repeat any number of times."

    The revision loop returns the contract to SENT with revision_count still 1 —
    proving the machine is cyclic rather than linear.

    Design: Difficulty/non_linear_state_machine/contract_revision_cycle
    """
    event, contract = setup_sent_contract_event(package_type="DAY_OF", total_budget_cents=3_000_000)
    validate_success(api.request_revision(contract["id"], make_client_headers(event["id"])))
    data = validate_success(api.send_contract(contract["id"], PLANNER))
    assert data["status"] == "SENT"
    assert data["revision_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: confirm requires countersigned contract
# ---------------------------------------------------------------------------
def test_confirm_with_signed_contract_rejected(api):
    """PRD §3.1: "Confirmation requires the event to be in `DRAFT` (otherwise
    `ERR_EVENT_NOT_DRAFT`) and requires the event's active contract to exist and be in
    `COUNTERSIGNED` status; if the active contract is anything other than
    `COUNTERSIGNED`, the confirmation is rejected with `ERR_CONTRACT_NOT_COUNTERSIGNED`."

    The contract is only SIGNED (not yet countersigned).

    Design: Difficulty/cross_entity_state_dependency/event_confirm_requires_contract_countersigned
    """
    event, _contract = setup_signed_contract_event(total_budget_cents=8_000_000)
    validate_error(
        api.confirm_event(event["id"], PLANNER),
        ApiErrorId.ERR_CONTRACT_NOT_COUNTERSIGNED.value,
    )


def test_confirm_succeeds_after_countersign(api):
    """PRD §3.1: "Confirmation requires the event to be in `DRAFT` (otherwise
    `ERR_EVENT_NOT_DRAFT`) and requires the event's active contract to exist and be in
    `COUNTERSIGNED` status; if the active contract is anything other than
    `COUNTERSIGNED`, the confirmation is rejected with `ERR_CONTRACT_NOT_COUNTERSIGNED`."
    PRD §3.1: "Entering `BOOKING` is the gate that unlocks vendor booking."

    Design: Difficulty/cross_entity_state_dependency/event_confirm_requires_contract_countersigned
    """
    event, contract = setup_signed_contract_event(total_budget_cents=8_000_000)
    validate_success(api.countersign_contract(contract["id"], PLANNER))
    data = validate_success(api.confirm_event(event["id"], PLANNER))
    assert data["status"] == "BOOKING"
