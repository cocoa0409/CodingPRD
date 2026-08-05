"""Lifecycle transitions: loan revision cycle, parallel artwork axes, and
invalid-transition lockdowns."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, assert_condition_report,
    set_clock, make_client, make_artwork, make_loan, make_vault, make_placement,
    setup_placed_artwork,
    client_payload, artwork_payload, condition_report_payload, invoice_payload,
    REG, APPR, BILL,
    api_client as api,
)


# ==========================================================================
# Loan revision cycle (cyclic state machine)
# ==========================================================================
def test_submitted_to_draft_revision_allowed():
    """PRD §3.6: "A submitted loan can be sent back to `DRAFT` for revision and
    resubmitted any number of times — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/loan_revision_cycle
    """
    c = make_client(client_type="INDIVIDUAL")
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    loan = make_loan(a["id"], c["id"], loan_start="2026-06-01T00:00:00Z",
                     loan_end="2026-07-01T00:00:00Z")
    get_success_data(api.transition_loan(loan["id"], {"to_status": "SUBMITTED"}, REG))
    data = validate_success(api.transition_loan(loan["id"], {"to_status": "DRAFT"}, REG))
    assert data["status"] == "DRAFT", data


def test_resubmit_after_revision_returns_submitted():
    """PRD §3.6: "The registrar submits it, moving `DRAFT` to `SUBMITTED`;
    submission records `submitted_by_user_id` as the submitting caller's
    `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/loan_revision_cycle
    """
    c = make_client(client_type="INDIVIDUAL")
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    loan = make_loan(a["id"], c["id"], loan_start="2026-06-01T00:00:00Z",
                     loan_end="2026-07-01T00:00:00Z")
    get_success_data(api.transition_loan(loan["id"], {"to_status": "SUBMITTED"}, REG))
    get_success_data(api.transition_loan(loan["id"], {"to_status": "DRAFT"}, REG))
    data = validate_success(api.transition_loan(loan["id"], {"to_status": "SUBMITTED"}, REG))
    assert data["status"] == "SUBMITTED", data


# ==========================================================================
# Parallel artwork axes: custody vs condition
# ==========================================================================
def test_damage_report_moves_condition_to_minor():
    """PRD §3.3: "When a report notes damage (its `damage_noted` is true) and
    grades the work `C` or `D`, an artwork that was `SOUND` moves to
    `MINOR_DAMAGE`."

    Design: Difficulty/non_linear_state_machine/artwork_parallel_custody_condition
    """
    s = setup_placed_artwork()
    get_success_data(api.create_condition_report(
        condition_report_payload(s["artwork"]["id"], report_type="PERIODIC",
                                 condition_grade="C", damage_noted=True,
                                 notes="surface scuff, lower left"), REG))
    data = validate_success(api.get_artwork(s["artwork"]["id"], REG))
    assert data["condition_status"] == "MINOR_DAMAGE", data


def test_condition_change_leaves_custody_in_storage():
    """PRD §2.8: "Neither axis constrains the transitions of the other, but both
    feed into the guards that gate transport, loans, and viewings."

    Design: Difficulty/non_linear_state_machine/artwork_parallel_custody_condition
    """
    s = setup_placed_artwork()
    get_success_data(api.create_condition_report(
        condition_report_payload(s["artwork"]["id"], report_type="PERIODIC",
                                 condition_grade="C", damage_noted=True), REG))
    data = validate_success(api.get_artwork(s["artwork"]["id"], REG))
    assert data["custody_status"] == "IN_STORAGE", data


# ==========================================================================
# Entity creation, defaults, required-fields, not-found
# ==========================================================================
def test_client_create_returns_201_with_system_defaults():
    """PRD §3.1: "A newly registered client starts with `account_status` of
    `ACTIVE` and an `outstanding_balance_cents` of 0."

    Design: Corner/entities/client_create_returns_201_with_system_defaults
    """
    created = validate_success(api.create_client(
        client_payload(name="New Client", client_type="INDIVIDUAL",
                       billing_email="c@x.example"), REG), 201)
    data = validate_success(api.get_client(created["id"], REG))
    assert data["account_status"] == "ACTIVE", data
    assert data["outstanding_balance_cents"] == 0, data


def test_artwork_missing_size_class_returns_invalid_request():
    """PRD §2.7: "Body well-formedness follows — required fields present and enum
    values in range — yielding `ERR_VALIDATION`."

    Design: Corner/entities/artwork_missing_size_class_returns_invalid_request
    """
    c = make_client(client_type="DEALER")
    payload = artwork_payload(c["id"], fragility_class="LOW", climate_class="AMBIENT")
    payload.pop("size_class")
    resp = api.create_artwork(payload, REG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_get_artwork_not_found_returns_404():
    """PRD §2.7: "Existence of the path resource and of every referenced
    foreign-key id is checked next, left to right along the request, yielding
    `ERR_NOT_FOUND` on the first missing id."

    Design: Corner/entities/get_artwork_not_found_returns_404
    """
    resp = api.get_artwork(NON_EXISTENT_UUID, REG)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_condition_report_created_and_retrievable():
    """PRD §2.4: "The sole exception is the condition report: a `ConditionReport`
    is an immutable inspection record that carries only `id` and `created_at` — it
    has neither `updated_at` nor `version`, because it is never modified after it
    is filed."

    Design: Corner/entities/condition_report_created_and_retrievable
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    created = validate_success(api.create_condition_report(
        condition_report_payload(a["id"], report_type="INTAKE", condition_grade="A",
                                 damage_noted=False, notes="clean intake"), REG), 201)
    data = validate_success(api.get_condition_report(created["id"], REG))
    assert data["report_type"] == "INTAKE", data
    assert_condition_report(data)


# ==========================================================================
# Invalid transitions / terminal lockdown
# ==========================================================================
def test_vault_decommission_with_occupancy_returns_invalid_state():
    """PRD §3.1: "It can be permanently `DECOMMISSIONED` from `OPERATIONAL`, but
    only when it holds no active occupants — if its `occupied_slots` is not zero,
    the decommission is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/vault_decommission_with_occupancy_returns_invalid_state
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=1)
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    make_placement(a["id"], v["id"])
    resp = api.transition_vault(v["id"], {"to_status": "DECOMMISSIONED"}, REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_loan_resubmit_from_rejected_returns_invalid_state():
    """PRD §3.6: "A submitted loan may instead be `REJECTED` by an approver
    (terminal)".
    PRD §2.7: "a lifecycle request names its requested target state in a
    `to_status` field, and if that target is not reachable from the resource's
    current state the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/loan_resubmit_from_rejected_returns_invalid_state
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    loan = make_loan(a["id"], c["id"], loan_start="2026-06-01T00:00:00Z",
                     loan_end="2026-07-01T00:00:00Z")
    get_success_data(api.transition_loan(loan["id"], {"to_status": "SUBMITTED"}, REG))
    get_success_data(api.transition_loan(loan["id"], {"to_status": "REJECTED"}, APPR))
    resp = api.transition_loan(loan["id"], {"to_status": "SUBMITTED"}, REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_invoice_pay_from_draft_returns_invalid_state():
    """PRD §3.8: "Paying an issued invoice moves it to `PAID` and decrements the
    client's `outstanding_balance_cents` by the same `total_cents`."
    PRD §2.7: "if that target is not reachable from the resource's current state
    the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invoice_pay_from_draft_returns_invalid_state
    """
    c = make_client()
    inv = get_success_data(api.create_invoice(
        invoice_payload(c["id"], manual_line_items=[{"description": "S", "amount_cents": 1000}]), BILL))
    resp = api.transition_invoice(inv["id"], {"to_status": "PAID"}, BILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
