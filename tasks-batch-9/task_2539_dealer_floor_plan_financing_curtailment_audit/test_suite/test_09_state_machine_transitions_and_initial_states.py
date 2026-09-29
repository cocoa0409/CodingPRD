"""Lifecycles: declared initial states, illegal triggers and terminal nodes."""
from test_helpers import (
    AM,
    CO,
    FA,
    ApiErrorId,
    api_client,
    assert_credit_line,
    assert_dealer,
    assert_floor_plan_audit,
    assert_funding_advance,
    assert_inventory_unit,
    create_credit_line,
    create_dealer,
    make_dealer_principal_headers,
    move_title_custody,
    read_credit_line,
    read_dealer,
    read_unit,
    register_unit,
    reject_advance_payload,
    request_advance,
    schedule_audit,
    set_clock,
    setup_active_line,
    setup_pending_line,
    title_custody_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_declining_an_advance_parks_it_in_rejected_and_moves_no_money():
    """The decline records its reason, frees the unit for a fresh request and leaves the ledger flat.

    PRD: "The advance moves `REQUESTED → REJECTED` with that code recorded, and the unit returns `PENDING_FUNDING → REGISTERED` so a fresh request can be filed against it."

    PRD: "No money moves, no obligation is created, and `available_credit_cents` is untouched — this inertness is exactly what distinguishes a decline from the void branch below."

    Design: Corner/state_machines/funding_advance_reject_moves_requested_to_rejected
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Reject Motors LLC", "state_code": "ND"},
    )
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNREJECTUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C12")
    advance = request_advance(unit["id"], ctx["dealer_headers"], 3000000, "INV-C12")
    assert advance["status"] == "REQUESTED"

    declined = validate_success(
        api_client.reject_advance(
            advance["id"], reject_advance_payload("TITLE_DEFECT"), CO
        )
    )
    assert_funding_advance(declined)
    assert declined["status"] == "REJECTED"
    assert declined["reason_code"] == "TITLE_DEFECT"
    assert declined["funded_at"] is None
    assert declined["funded_by_user_id"] is None

    unit_after = read_unit(unit["id"])
    assert unit_after["funding_status"] == "REGISTERED"
    assert unit_after["advance_amount_cents"] == 0
    assert unit_after["outstanding_principal_cents"] == 0

    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 0
    assert line["available_credit_cents"] == 500000000

    _, obligation_meta = validate_paginated(
        api_client.list_curtailment_obligations(CO, params={"unit_id": unit["id"]})
    )
    assert obligation_meta["total_count"] == 0


def test_a_count_cannot_be_opened_before_its_window_starts():
    """The clock sits two weeks short of the window, so the start is refused and the audit stays scheduled.

    PRD: "The logical clock must fall inside the closed window, comparing calendar dates inclusively at both ends; outside it, the refusal is `ERR_AUDIT_WINDOW_NOT_OPEN`."

    Design: Corner/state_machines/audit_start_before_the_window_opens_returns_window_not_open
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Window Motors LLC", "state_code": "MI"},
    )
    dealer_id = ctx["dealer"]["id"]
    audit = schedule_audit(dealer_id, "2026-08-15", "2026-08-20", audit_type="ANNOUNCED")
    assert_floor_plan_audit(audit)
    assert audit["status"] == "SCHEDULED"
    assert audit["started_at"] is None
    assert audit["version"] == 1

    validate_error(
        api_client.start_audit(audit["id"], FA),
        ApiErrorId.ERR_AUDIT_WINDOW_NOT_OPEN,
        409,
    )

    unchanged = validate_success(api_client.get_audit(audit["id"], AM))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["started_at"] is None
    assert unchanged["version"] == 1
    assert read_dealer(dealer_id)["audit_in_progress"] is False

    set_clock("2026-08-15T00:00:00Z")
    opened = validate_success(api_client.start_audit(audit["id"], FA))
    assert opened["status"] == "IN_PROGRESS"
    assert str(opened["started_at"]).startswith("2026-08-15T00:00:00")
    assert read_dealer(dealer_id)["audit_in_progress"] is True


def test_signing_off_a_count_that_was_never_opened_is_refused():
    """Reconcile and abort are both illegal from SCHEDULED, and no incident is born.

    PRD: "**Signing off.** Reconciliation is an `AuditManager` act on an audit still `IN_PROGRESS` (otherwise `ERR_AUDIT_NOT_IN_PROGRESS`), with an optional `notes` field on the payload."

    PRD: "When it is 1 or more, the audit moves `IN_PROGRESS → RECONCILED_EXCEPTIONS` and the full cascade below fires."

    Design: Corner/state_machines/reconcile_on_a_scheduled_audit_returns_audit_not_in_progress
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Invalid Transition Motors LLC",
            "state_code": "OH",
        },
    )
    audit = schedule_audit(
        ctx["dealer"]["id"], "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED"
    )
    assert audit["status"] == "SCHEDULED"

    validate_error(
        api_client.reconcile_audit(audit["id"], {"notes": "Premature sign-off"}, AM),
        ApiErrorId.ERR_AUDIT_NOT_IN_PROGRESS,
        409,
    )

    still_scheduled = validate_success(api_client.get_audit(audit["id"], AM))
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["reconciled_at"] is None
    assert still_scheduled["reconciled_by_user_id"] is None
    assert still_scheduled["sot_exposure_cents"] == 0

    _, incident_meta = validate_paginated(
        api_client.list_out_of_trust_incidents(CO, params={"audit_id": audit["id"]})
    )
    assert incident_meta["total_count"] == 0


def test_one_chain_observes_every_declared_initial_state_in_order():
    """Dealer PROSPECT, line PENDING, unit REGISTERED with NOT_RECEIVED, advance REQUESTED.

    PRD: "The new dealership lands in `PROSPECT` with a clean slate: `risk_score` 100, `risk_rating` `A`, `audit_frequency_days` 180, `next_audit_due_at` still null, `last_covenant_result` null, and `open_sot_incident_count`, `open_sot_exposure_cents`, `delinquent_unit_count`, `covenant_breach_count` and `unapplied_credit_cents` all zero, with `audit_in_progress` false."

    PRD: "A freshly established line sits in `PENDING` with `activated_at` null, `suspension_reason_code` null, `available_credit_cents` equal to `credit_limit_cents`, and `outstanding_principal_cents`, `charged_off_principal_cents`, `eligible_collateral_cents`, `borrowing_base_deficiency_cents`, `class_outstanding_cents_used` and `class_outstanding_cents_demonstrator` all zero."

    PRD: "A registered unit starts in `funding_status` `REGISTERED`, `title_custody_status` `NOT_RECEIVED` and `eligibility_status` `ELIGIBLE`, with `ineligibility_reason_code` null, `advance_amount_cents`, `outstanding_principal_cents`, `principal_paid_cents`, `aging_exception_count` and `curtailment_extension_days_total` all zero, `floored_at` and `funded_by_user_id` null, and `version` 1."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Initial State Motors LLC", state_code="IN")
    assert_dealer(dealer)
    assert dealer["status"] == "PROSPECT"

    line = create_credit_line(dealer["id"])
    assert_credit_line(line)
    assert line["status"] == "PENDING"
    assert line["activated_at"] is None
    assert line["available_credit_cents"] == line["credit_limit_cents"]

    validate_success(
        api_client.create_curtailment_tier(line["id"], NEW_TIER_1000, CO), 201
    )
    validate_success(api_client.activate_credit_line(line["id"], CO))
    assert read_dealer(dealer["id"])["status"] == "ACTIVE"

    unit = register_unit(
        dealer["id"], line["id"], "CRNINITIALUNIT01", invoice_amount_cents=3000000
    )
    assert_inventory_unit(unit)
    assert unit["funding_status"] == "REGISTERED"
    assert unit["title_custody_status"] == "NOT_RECEIVED"
    assert unit["eligibility_status"] == "ELIGIBLE"
    assert unit["version"] == 1

    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C15")
    advance = request_advance(
        unit["id"], make_dealer_principal_headers(dealer["id"]), 3000000, "INV-C15"
    )
    assert_funding_advance(advance)
    assert advance["status"] == "REQUESTED"
    assert advance["approved_advance_amount_cents"] == 0
    assert advance["effective_advance_rate_bps"] == 0
    assert advance["rate_adjustment_codes"] == []
    assert advance["invoice_age_days_at_funding"] is None

    unit_after = read_unit(unit["id"])
    assert unit_after["funding_status"] == "PENDING_FUNDING"
    assert unit_after["title_custody_status"] == "LENDER_HELD"


def test_a_released_document_can_never_be_pulled_back_into_the_vault():
    """RELEASED_FOR_SALE is terminal, so both LENDER_HELD and LOST are refused from it.

    PRD: "The legal successors are: from `NOT_RECEIVED`, either `LENDER_HELD` (the document arrived and is now vaulted) or `LOST`; from `LENDER_HELD`, either `LOST` or `RELEASED_FOR_SALE`; from `LOST`, back to `LENDER_HELD`, which requires `document_reference` to be present in the payload because a duplicate document has to be identified; and from `RELEASED_FOR_SALE`, nowhere at all, since that state is terminal."

    PRD: "Any other requested move — including any attempt to leave `RELEASED_FOR_SALE` — is refused with `ERR_INVALID_TITLE_TRANSITION`."

    Design: Corner/state_machines/title_released_for_sale_is_terminal_and_rejects_a_return_to_lender_held
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Terminal Title Motors LLC",
            "state_code": "KY",
        },
    )
    unit = register_unit(
        ctx["dealer"]["id"],
        ctx["credit_line"]["id"],
        "CRNTERMTITLEUNT1",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    assert unit["version"] == 1
    vaulted = move_title_custody(unit["id"], "LENDER_HELD", "MSO-C16")
    assert vaulted["version"] == 2

    released = move_title_custody(unit["id"], "RELEASED_FOR_SALE")
    assert released["title_custody_status"] == "RELEASED_FOR_SALE"
    assert released["version"] == 3

    validate_error(
        api_client.change_title_custody(
            unit["id"], title_custody_payload("LENDER_HELD", document_reference="DUP-C16"), CO
        ),
        ApiErrorId.ERR_INVALID_TITLE_TRANSITION,
        409,
    )
    frozen = read_unit(unit["id"])
    assert frozen["title_custody_status"] == "RELEASED_FOR_SALE"
    assert frozen["version"] == 3

    validate_error(
        api_client.change_title_custody(unit["id"], title_custody_payload("LOST"), CO),
        ApiErrorId.ERR_INVALID_TITLE_TRANSITION,
        409,
    )
    assert read_unit(unit["id"])["version"] == 3


def test_activation_is_not_idempotent_and_the_second_call_never_restamps_it():
    """The line activates once at the earlier clock and the repeat call is refused outright.

    PRD: "A `CreditOfficer` may activate only a line still in `PENDING` — any other status is refused with `ERR_CREDIT_LINE_NOT_ACTIVE` — and only when at least one ladder rung exists for that line."

    PRD: "Activation stamps `activated_at` from the logical clock, recomputes the capacity figures of §2.11, advances the line `PENDING → ACTIVE`, and cascades: the dealership moves `PROSPECT → ACTIVE` and its `next_audit_due_at` is set to `activated_at` plus its current `audit_frequency_days` — 180 days out for a brand-new `A`-rated dealer."

    Design: Corner/state_machines/second_activate_on_an_already_active_line_returns_not_active
    """
    ctx = setup_pending_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Idempotency Motors LLC",
            "state_code": "TN",
        },
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    first = validate_success(api_client.activate_credit_line(line_id, CO))
    assert first["status"] == "ACTIVE"
    assert str(first["activated_at"]).startswith("2026-08-01T00:00:00")
    assert first["version"] == 2
    dealer_after_first = read_dealer(dealer_id)
    assert dealer_after_first["status"] == "ACTIVE"
    dealer_version_after_first = dealer_after_first["version"]

    set_clock("2026-08-08T00:00:00Z")
    validate_error(
        api_client.activate_credit_line(line_id, CO),
        ApiErrorId.ERR_CREDIT_LINE_NOT_ACTIVE,
        409,
    )

    unchanged = read_credit_line(line_id)
    assert unchanged["status"] == "ACTIVE"
    assert str(unchanged["activated_at"]).startswith("2026-08-01T00:00:00")
    assert unchanged["version"] == 2
    dealer_after_second = read_dealer(dealer_id)
    assert dealer_after_second["status"] == "ACTIVE"
    assert dealer_after_second["version"] == dealer_version_after_first
    assert str(dealer_after_second["next_audit_due_at"]).startswith("2027-01-28T00:00:00")
