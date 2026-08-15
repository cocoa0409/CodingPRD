"""Hardship payment cascade: derived-field reconciliation, document retention,
terminal withdraw, suspension window, election restart, mark-reported
idempotency (PRD §3.3, §3.9)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_hardship_fully,
    create_contribution_election_payload,
    create_hardship_request_payload,
    create_loan_payload,
    create_plan_payload,
    enroll_participant,
    list_hardship_tasks,
    make_participant_headers,
    set_clock,
    setup_paid_hardship,
    setup_plan_and_participant,
    upload_document,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]


# ---------------------------------------------------------------------------
# Corner: derived_fields_reconcile_after_hardship_payment
# ---------------------------------------------------------------------------


def test_derived_fields_reconcile_after_hardship_payment_participant(api):
    """PRD §3.9: "Payment stamps `paid_on` with the logical clock date, debits
    `vested_balance_cents` by the gross withdrawal ... Payment also creates a
    `TaxEvent` whose `source_type` is `HARDSHIP_DISTRIBUTION`, whose
    `taxable_amount_cents` equals the `gross_withdrawal_cents` directly, and
    whose `event_date` is `paid_on`, adding the gross into
    `ytd_taxable_distributions_cents`".

    Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_hardship_payment
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    # ACTIVE election before the hardship so we can observe contribution_status
    validate_success(
        api.put_contribution_election(
            participant["id"],
            create_contribution_election_payload(deferral_pct=0.1),
            make_participant_headers(participant["id"]),
        ),
        200,
    )
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000,
                amount_semantics="NET",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    # Default chain has 2 steps; document + approve both
    upload_document(
        participant, h["id"], amount_cents=800_000, document_type="MEDICAL_BILL"
    )
    approve_hardship_fully(h["id"])
    paid = validate_success(api.pay_hardship_request(h["id"], ADMIN), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_on"] == "2026-05-01T00:00:00Z"

    participant_after = validate_success(
        api.get_participant(participant["id"], ADMIN), 200
    )
    # NET 800,000 -> gross 1,006,250; vested drops by that gross
    assert participant_after["vested_balance_cents"] == 18_993_750
    assert participant_after["ytd_taxable_distributions_cents"] == 1_006_250
    assert participant_after["contribution_status"] == "SUSPENDED"


def test_derived_fields_reconcile_after_hardship_payment_suspension_record(api):
    """PRD §3.3: "its `starts_on` equals the paying hardship request's
    `paid_on`, its `ends_on` is `paid_on` plus the plan's
    `hardship_suspension_months` calendar months on the same day-of-month".

    Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_hardship_payment
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000,
                amount_semantics="NET",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    upload_document(
        participant, h["id"], amount_cents=800_000, document_type="MEDICAL_BILL"
    )
    approve_hardship_fully(h["id"])
    validate_success(api.pay_hardship_request(h["id"], ADMIN), 200)
    susp, _ = validate_paginated(
        api.get_hardship_suspension_record(h["id"], ADMIN)
    )
    assert len(susp) == 1
    rec = susp[0]
    assert rec["starts_on"] == "2026-05-01T00:00:00Z"
    assert rec["ends_on"] == "2026-11-01T00:00:00Z"  # 6 months, same day-of-month
    assert rec["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: document_retention_stamp_seven_years_after_payment
# ---------------------------------------------------------------------------


def test_document_retention_stamp_seven_years_after_payment(api):
    """PRD §3.9: "it stamps `retained_until` as `paid_on` plus seven calendar
    years on every document of the request, fixing the retention deadline."
    PRD §3.9: each document "carries a `retained_until` that stays null until
    the request is paid".

    Design: Corner/calculations/document_retention_stamp_seven_years_after_payment
    """
    _, participant, h = setup_paid_hardship(
        amount_cents=200_000,
        amount_semantics="GROSS",
        vested_balance_cents=20_000_000,
        document_amount_cents=200_000,
    )
    docs, _ = validate_paginated(api.list_hardship_documents(h["id"], ADMIN))
    assert len(docs) == 1
    # paid at startup clock 2026-05-01 -> retained_until = +7 calendar years
    assert docs[0]["retained_until"] == "2033-05-01T00:00:00Z"


def test_document_retention_stamp_null_before_payment(api):
    """PRD §3.9: each document "carries a `retained_until` that stays null
    until the request is paid".

    Design: Corner/calculations/document_retention_stamp_seven_years_after_payment
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=200_000,
                amount_semantics="GROSS",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    doc = upload_document(
        participant, h["id"], amount_cents=200_000, document_type="MEDICAL_BILL"
    )
    assert doc["retained_until"] is None


# ---------------------------------------------------------------------------
# Corner: withdraw_paid_hardship_returns_invalid_state
# ---------------------------------------------------------------------------


def test_withdraw_paid_hardship_returns_invalid_state(api):
    """PRD §3.9: "While `UNDER_REVIEW` or `PENDING_DOCUMENTS`, the participant
    may withdraw the request" — PAID is neither, so the withdraw fails the
    from-state check. PRD §2.8 priority 6: "all other from-state failures carry
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_paid_hardship_returns_invalid_state
    """
    _, participant, h = setup_paid_hardship(
        amount_cents=200_000,
        amount_semantics="GROSS",
        vested_balance_cents=20_000_000,
        document_amount_cents=200_000,
    )
    res = api.withdraw_hardship_request(
        h["id"], make_participant_headers(participant["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    h_after = validate_success(api.get_hardship_request(h["id"], ADMIN), 200)
    assert h_after["status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner: mark_reported_twice_returns_already_reported
# ---------------------------------------------------------------------------


def test_mark_reported_twice_returns_already_reported(api):
    """PRD §3.9: "marking an already-`REPORTED` event is rejected with
    `ERR_TAX_EVENT_ALREADY_REPORTED`."

    Design: Corner/state_machines/mark_reported_twice_returns_already_reported
    """
    _, participant, h = setup_paid_hardship(
        amount_cents=200_000,
        amount_semantics="GROSS",
        vested_balance_cents=20_000_000,
        document_amount_cents=200_000,
    )
    events, _ = validate_paginated(
        api.list_participant_tax_events(participant["id"], ADMIN)
    )
    ev_id = events[0]["id"]
    first = validate_success(api.mark_tax_event_reported(ev_id, ADMIN), 200)
    assert first["status"] == "REPORTED"
    res = api.mark_tax_event_reported(ev_id, ADMIN)
    validate_error(
        res, ApiErrorId.ERR_TAX_EVENT_ALREADY_REPORTED, expected_status=409
    )


# ---------------------------------------------------------------------------
# Difficulty: hardship_suspension_window_overlap_rejected
# ---------------------------------------------------------------------------


def _setup_active_suspension(api):
    """Pay a hardship at 2026-05-01 (startup clock) opening suspension
    [2026-05-01, 2026-11-01). Returns (plan, participant, paid_request)."""
    return setup_paid_hardship(
        amount_cents=200_000,
        amount_semantics="GROSS",
        vested_balance_cents=20_000_000,
        document_amount_cents=200_000,
    )


def test_hardship_suspension_window_overlap_rejected_inside(api):
    """PRD §3.3: "The window is half-open — it includes `starts_on` and excludes
    `ends_on` — so a new loan request or hardship request created while the
    current date falls within the window is rejected with
    `ERR_SUSPENSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/hardship_suspension_window_overlap_rejected
    """
    _, participant, _ = _setup_active_suspension(api)
    # One day before ends_on
    set_clock("2026-10-31T00:00:00Z")
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="FUNERAL", amount_cents=100_000, amount_semantics="GROSS"
        ),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SUSPENSION_OVERLAP, expected_status=422)


def test_hardship_suspension_window_overlap_rejected_at_boundary_accepted(api):
    """PRD §3.3: "The window is half-open — it includes `starts_on` and excludes
    `ends_on`". At exactly ends_on (2026-11-01) the window has closed, so the
    request is accepted.

    Design: Difficulty/resource_temporal_overlap/hardship_suspension_window_overlap_rejected
    """
    _, participant, _ = _setup_active_suspension(api)
    # At exactly ends_on (2026-11-01)
    set_clock("2026-11-01T00:00:00Z")
    h2 = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="FUNERAL", amount_cents=100_000,
                amount_semantics="GROSS",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    assert h2["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Difficulty: election_restart_gated_by_suspension_expiry
# ---------------------------------------------------------------------------


def _setup_suspended_election(api):
    """Pay a hardship at clock 2026-06-10 with an ACTIVE election; suspension
    [2026-06-10, 2026-12-10). Returns (plan, participant, paid_request)."""
    plan = validate_success(
        api.create_plan(
            create_plan_payload(hardship_approval_chain=["RECORDKEEPER_ADMIN"]),
            ADMIN,
        ),
        201,
    )
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    validate_success(
        api.put_contribution_election(
            participant["id"],
            create_contribution_election_payload(deferral_pct=0.08),
            make_participant_headers(participant["id"]),
        ),
        200,
    )
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000,
                amount_semantics="NET",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    upload_document(
        participant, h["id"], amount_cents=800_000, document_type="MEDICAL_BILL"
    )
    approve_hardship_fully(h["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(api.pay_hardship_request(h["id"], ADMIN), 200)
    return plan, participant, h


def test_election_restart_gated_by_suspension_expiry_blocked(api):
    """PRD §3.3: "restarting deferrals is an explicit participant action,
    permitted only once every suspension record for the participant has expired
    — the logical clock has reached each record's `ends_on` — and rejected with
    `ERR_SUSPENSION_STILL_ACTIVE` while any suspension remains `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/election_restart_gated_by_suspension_expiry
    """
    _, participant, _ = _setup_suspended_election(api)
    # Mid-payment the election moved to SUSPENDED
    election, _ = validate_paginated(
        api.get_contribution_election(participant["id"], ADMIN)
    )
    assert election[0]["status"] == "SUSPENDED"
    # At 2026-12-09 (one day before ends_on 2026-12-10) restart is blocked
    set_clock("2026-12-09T00:00:00Z")
    res = api.restart_contribution_election(
        participant["id"], make_participant_headers(participant["id"])
    )
    validate_error(res, ApiErrorId.ERR_SUSPENSION_STILL_ACTIVE, expected_status=422)


def test_election_restart_gated_by_suspension_expiry_at_boundary(api):
    """PRD §3.3: "A successful restart moves the election from `SUSPENDED` back
    to `ACTIVE`, restores `contribution_status` to `ACTIVE`". At exactly
    ends_on (half-open window) the suspension has expired and restart succeeds.

    Design: Difficulty/cross_entity_state_dependency/election_restart_gated_by_suspension_expiry
    """
    _, participant, _ = _setup_suspended_election(api)
    # At exactly ends_on 2026-12-10 the suspension has EXPIRED
    set_clock("2026-12-10T00:00:00Z")
    election = validate_success(
        api.restart_contribution_election(
            participant["id"], make_participant_headers(participant["id"])
        ),
        200,
    )
    assert election["status"] == "ACTIVE"
    participant_after = validate_success(
        api.get_participant(participant["id"], ADMIN), 200
    )
    assert participant_after["contribution_status"] == "ACTIVE"
