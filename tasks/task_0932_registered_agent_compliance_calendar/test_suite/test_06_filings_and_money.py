"""Filings, the fee breakdown, the allocation waterfall and the refile cycle."""
from test_helpers import (
    ADMIN,
    AGENT,
    DE_RULE_EXPEDITE,
    DE_RULE_MIN,
    DE_RULE_MIN_DISSOLUTION,
    DE_RULE_MIN_LATE,
    OFFICER,
    ApiErrorId,
    assert_filing_total,
    assert_payment_identity,
    capture,
    draft_obligation_filing,
    draft_standalone_filing,
    fund_and_submit,
    make_compliance_officer_headers,
    make_filing_agent_headers,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    new_payment,
    publish_rule,
    read_client,
    read_filing,
    read_payment,
    record_filing_outcome,
    set_clock,
    setup_pending_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_waterfall_funds_the_earliest_deadline_first(api):
    """PRD §3.8: "Candidates are ordered by earliest statutory deadline first. Each
    candidate's sort key is the `due_date` of the obligation it is attached to; a
    standalone filing, having no obligation, sorts as though its deadline were
    `9999-12-31`, which places every standalone filing after every obligation-backed
    one."
    PRD §3.8: "For each candidate it computes the shortfall as `total_fee_cents` minus
    `paid_amount_cents`, and the amount to place as the lesser of the remaining funds
    and that shortfall."

    Design: Corner/calculations/corner_waterfall_orders_by_due_date_and_partially_fills_the_later_filing
    """
    scene = setup_pending_home_registration(DE_RULE_MIN_LATE)
    obligation_2028 = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2028)
    obligation_2027 = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing_2028 = draft_obligation_filing(obligation_2028, "ANNUAL_REPORT")
    filing_2027 = draft_obligation_filing(obligation_2027, "ANNUAL_REPORT")
    payment = new_payment(scene["client"]["id"], 12000)

    capture(payment["id"], 12000)

    # Each filing is 5000 state fee + 0 tax + 0 late fee + 4900 service = 9900. The
    # 2027 row is due 2027-03-01 and the 2028 row 2028-03-01, so 9900 lands on the
    # 2027 filing first and the remaining 2100 partially funds the 2028 filing.
    assert read_filing(filing_2027["id"])["paid_amount_cents"] == 9900
    assert read_filing(filing_2028["id"])["paid_amount_cents"] == 2100

    rows_2027, meta_2027 = validate_paginated(
        api.list_filing_allocations(filing_2027["id"], ADMIN)
    )
    assert meta_2027["total_count"] == 1
    assert rows_2027[0]["amount_cents"] == 9900
    assert rows_2027[0]["sequence_index"] == 0

    rows_2028, meta_2028 = validate_paginated(
        api.list_filing_allocations(filing_2028["id"], ADMIN)
    )
    assert meta_2028["total_count"] == 1
    assert rows_2028[0]["amount_cents"] == 2100
    assert rows_2028[0]["sequence_index"] == 1

    settled = read_payment(payment["id"])
    assert settled["allocated_amount_cents"] == 12000
    assert settled["unallocated_amount_cents"] == 0
    assert_payment_identity(settled)


def test_waterfall_remainder_parks_in_unallocated(api):
    """PRD §3.8: "When the walk finishes, the payment's `allocated_amount_cents` is
    `capture_amount_cents` less whatever remainder is left, and
    `unallocated_amount_cents` is that remainder."
    PRD §2.7: "For every `Payment`, `captured_amount_cents` equals the sum of
    `allocated_amount_cents`, `unallocated_amount_cents` and `refunded_amount_cents`, as
    exact integers with no tolerance."

    Design: Corner/calculations/corner_waterfall_remainder_lands_in_unallocated
    """
    scene = setup_pending_home_registration(DE_RULE_MIN_LATE)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT")
    payment = new_payment(scene["client"]["id"], 25000)

    capture(payment["id"], 25000)

    settled = read_payment(payment["id"])
    assert settled["captured_amount_cents"] == 25000
    assert settled["allocated_amount_cents"] == 9900
    # 25000 captured less the single 9900 shortfall leaves 15100 unplaced.
    assert settled["unallocated_amount_cents"] == 15100
    assert settled["refunded_amount_cents"] == 0
    assert settled["status"] == "CAPTURED"
    assert_payment_identity(settled)
    assert read_filing(filing["id"])["paid_amount_cents"] == 9900


def test_refile_carries_the_service_portion_and_credits_nothing(api):
    """PRD §3.7: "On success the rejected filing moves `REJECTED → ABANDONED` and its
    `version` increases by 1, and a **successor** filing is created in `DRAFT` carrying
    the same `registration_id`, the same `compliance_obligation_id` and the same
    `filing_kind` as its predecessor, with `attempt_number` one greater than the
    predecessor's, `prepared_by_user_id` set to the acting `X-User-ID`, and
    `paid_amount_cents` 0."
    PRD §3.7: "Its `service_fee_cents` is 0 — the predecessor's allocated service
    portion is **carried**, consumed by the successor rather than returned — and its
    `service_portion_cents` is therefore just the service half of its own expedite tier.
    The client's `credit_balance_cents` does not move at all on a refile, and no
    reversal allocation is created."

    Design: Corner/calculations/corner_refile_carries_service_portion_without_crediting_the_client
    """
    scene = setup_pending_home_registration(DE_RULE_MIN_LATE)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    original = draft_obligation_filing(obligation, "ANNUAL_REPORT")
    payment = new_payment(scene["client"]["id"], 9900)
    capture(payment["id"], 9900)
    validate_success(api.submit_filing(original["id"], AGENT))
    record_filing_outcome(original["id"], "REJECTED", "Wrong schedule attached")

    set_clock("2026-05-05T00:00:00Z")
    validate_success(
        api.refile_filing(
            original["id"],
            make_compliance_officer_headers("officer-1"),
            {"expedite_tier": "NONE"},
        ),
        201,
    )

    predecessor = read_filing(original["id"])
    assert predecessor["status"] == "ABANDONED"
    # Rejected at clock 2026-05-01 plus 15 calendar days is 2026-05-16.
    assert predecessor["refile_window_end"] == "2026-05-16"

    rows, meta = validate_paginated(
        api.list_filings(ADMIN, params={"compliance_obligation_id": obligation["id"]})
    )
    assert meta["total_count"] == 2
    successors = [row for row in rows if row["id"] != original["id"]]
    assert len(successors) == 1
    successor = successors[0]

    assert successor["status"] == "DRAFT"
    assert successor["attempt_number"] == 2
    assert successor["service_fee_cents"] == 0
    # The obligation's late fee is still 0 at 2026-05-05, well inside its grace
    # window, so the successor's state fee is the obligation's own 5000.
    assert successor["state_fee_cents"] == 5000
    assert successor["total_fee_cents"] == 5000
    assert_filing_total(successor)

    assert read_client(scene["client"]["id"])["credit_balance_cents"] == 0
    settled = read_payment(payment["id"])
    assert settled["refunded_amount_cents"] == 0
    assert settled["allocated_amount_cents"] == 9900


def test_expedite_fee_splits_across_the_state_and_service_portions(api):
    """PRD §3.7: "The expedite component splits in two. Its service half is 0 cents at
    tier `NONE`, 5000 cents at `STANDARD`, 12500 cents at `RUSH` and 30000 cents at
    `SAME_DAY`. Its state half is 0 at tier `NONE`, and at any other tier is the
    jurisdiction rule's `expedite_surcharge_cents`. `expedite_fee_cents` is the sum of
    those two halves."
    PRD §3.7: "The two portions are then formed: `state_portion_cents` is
    `state_fee_cents` plus the state half of the expedite fee, and
    `service_portion_cents` is `service_fee_cents` plus the service half.
    `total_fee_cents` is the sum of the two portions."

    Design: Corner/calculations/corner_expedite_tier_splits_across_state_and_service_portions
    """
    scene = setup_pending_home_registration(DE_RULE_EXPEDITE)

    data = validate_success(
        api.create_standalone_filing(
            scene["registration"]["id"],
            {"filing_kind": "DISSOLUTION", "expedite_tier": "RUSH"},
            OFFICER,
        ),
        201,
    )

    # RUSH: service half 12500 plus state half 10000 gives 22500.
    assert data["expedite_fee_cents"] == 22500
    assert data["state_fee_cents"] == 4900
    assert data["service_fee_cents"] == 4900
    # 4900 + 10000 = 14900 state portion; 4900 + 12500 = 17400 service portion.
    assert data["state_portion_cents"] == 14900
    assert data["service_portion_cents"] == 17400
    assert data["total_fee_cents"] == 32300
    assert_filing_total(data)


def test_voided_authorization_can_never_be_captured(api):
    """PRD §3.8: "The payment must be in `AUTHORIZED`; from any other status the request
    is rejected with `ERR_INVALID_STATE`. On success the status becomes `VOIDED` and the
    `version` increases by 1. Nothing else moves — no allocation is created, no filing
    is touched, no credit is issued. `VOIDED` is terminal."

    Design: Corner/state_machines/corner_payment_void_from_authorized_is_terminal
    """
    client = new_client()
    payment = new_payment(client["id"], 5000)

    voided = validate_success(api.void_payment(payment["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert voided["captured_amount_cents"] == 0

    response = api.capture_payment(payment["id"], {"capture_amount_cents": 5000}, ADMIN)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_preparer_may_not_lodge_its_own_filing(api):
    """PRD §3.7: "then the acting `X-User-ID` must differ from the filing's
    `prepared_by_user_id`, failing which it is rejected with
    `ERR_SEGREGATION_OF_DUTIES`; then `paid_amount_cents` must have reached
    `total_fee_cents`, failing which it is rejected with
    `ERR_INSUFFICIENT_CAPTURED_FUNDS`."
    PRD §2.9.1: "Segregation of duties is checked before funding, so a preparer trying
    to submit an underfunded filing it prepared sees `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/corner_segregation_of_duties_blocks_the_preparer_from_submitting
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", preparer_user_id="officer-1")

    response = api.submit_filing(filing["id"], make_filing_agent_headers("officer-1"))

    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = read_filing(filing["id"])
    assert after["status"] == "DRAFT"
    assert after["submitted_by_user_id"] is None
    assert after["prepared_by_user_id"] == "officer-1"


def test_unfunded_filing_cannot_be_lodged(api):
    """PRD §2.9: "the filing's `paid_amount_cents` is greater than or equal to its
    `total_fee_cents`; an underfunded filing cannot be lodged with a jurisdiction.
    Applies to `POST /filings/{id}/submit`. Failure returns
    `ERR_INSUFFICIENT_CAPTURED_FUNDS` (HTTP 402)."

    Design: Corner/validations/corner_unfunded_filing_cannot_be_submitted
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", preparer_user_id="officer-1")

    response = api.submit_filing(filing["id"], make_filing_agent_headers("agent-9"))

    assert response.status_code == 402
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CAPTURED_FUNDS.value)

    after = read_filing(filing["id"])
    # 5000 state fee + 4900 service fee = 9900 owed, none of it paid.
    assert after["total_fee_cents"] == 9900
    assert after["paid_amount_cents"] == 0
    assert after["status"] == "DRAFT"


def test_refile_after_the_window_closes_is_refused(api):
    """PRD §3.7: "the current clock date must be on or before `refile_window_end`, else
    `ERR_REFILE_WINDOW_CLOSED`; and `attempt_number` must be strictly below 3, else
    `ERR_REFILE_LIMIT_REACHED`."
    PRD §3.7: "and sets `refile_window_end` to `outcome_recorded_on` plus 15 calendar
    days."

    Design: Corner/validations/corner_refile_after_the_window_closes_is_refused
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", preparer_user_id="officer-1")
    fund_and_submit(scene["client"]["id"], filing, target=False)
    record_filing_outcome(filing["id"], "REJECTED", "Missing exhibit B")

    set_clock("2026-05-17T00:00:00Z")
    response = api.refile_filing(filing["id"], make_compliance_officer_headers("officer-1"))

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_REFILE_WINDOW_CLOSED.value)

    after = read_filing(filing["id"])
    # Rejected at the default clock date 2026-05-01 plus 15 days is 2026-05-16.
    assert after["refile_window_end"] == "2026-05-16"
    assert after["status"] == "REJECTED"

    _rows, meta = validate_paginated(
        api.list_filings(ADMIN, params={"compliance_obligation_id": obligation["id"]})
    )
    assert meta["total_count"] == 1, "no successor draft is created"


def test_allocation_target_from_another_client_is_invalid(api):
    """PRD §3.8: "and when `target_filing_id` is supplied it must name a filing
    belonging to the paying client, in status `DRAFT`, `SUBMITTED` or `REJECTED`, whose
    `paid_amount_cents` is strictly below its `total_fee_cents`, else
    `ERR_ALLOCATION_TARGET_INVALID`."

    Design: Corner/validations/corner_allocation_target_belonging_to_another_client_is_invalid
    """
    publish_rule(DE_RULE_MIN_DISSOLUTION)
    client_a = new_client()
    client_b = new_client(legal_name="Beacon Holdings", billing_email="ap@beacon.example")
    entity_b = new_entity(
        client_b["id"], legal_name="Southwind Widgets LLC", formation_date="2026-02-15"
    )
    registration_b = new_home_registration(entity_b["id"])
    filing_b = draft_standalone_filing(registration_b["id"], "DISSOLUTION")
    payment_a = new_payment(client_a["id"], 5000)

    response = api.capture_payment(
        payment_a["id"],
        {"capture_amount_cents": 5000, "target_filing_id": filing_b["id"]},
        ADMIN,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_ALLOCATION_TARGET_INVALID.value)

    settled = read_payment(payment_a["id"])
    assert settled["status"] == "AUTHORIZED"
    assert settled["captured_amount_cents"] == 0
    assert read_filing(filing_b["id"])["paid_amount_cents"] == 0
