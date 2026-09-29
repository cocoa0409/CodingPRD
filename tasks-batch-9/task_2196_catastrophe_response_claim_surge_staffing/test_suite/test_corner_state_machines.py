"""§1.9 Scaffold Corner Design — section: state_machines.

One test per non-stub design instance. Every precondition is built inside the
test through the API's own endpoints, because the server restarts before each
test and starts from an empty database with the clock at 2026-08-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.corner_support_d import (
    CE,
    CLOCK_START,
    CM,
    DC,
    active_block,
    declared_event,
    mint_estimate,
    new_adjuster,
    new_claim,
    new_event,
    triaged_claim,
)
from test_helpers.test_users import make_adjuster_headers, make_vendor_coordinator_headers

# POST /vendor-firms mints the row, so no firm id exists yet to bind the caller
# to; §2.11 position 17 only binds a VendorCoordinator to a vendor ASSIGNMENT.
VC = make_vendor_coordinator_headers("vc_1")


# ---------------------------------------------------------------------------
# corner_sm_initial_state_advance_issued_and_vendor_network_inactive
# ---------------------------------------------------------------------------
def _triaged_claim_and_fresh_firm(api):
    """CAT-2026-1101 DECLARED with one claim TRIAGED to STANDARD (severity
    40.00 * 0.95 = 38.00, case_reserve max(40000, 50000) * 0.45 = 22500.00) and
    one just-registered TARP firm."""
    event = declared_event(api, "CAT-2026-1101")
    claim = triaged_claim(api, "POL-1101A", event["id"])
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Lone Star Tarp Co",
                "vendor_type": "TARP",
                "service_states": ["TX"],
                "max_concurrent_jobs": 3,
                "performance_score": 90.00,
            },
            VC,
        ),
        201,
    )
    return event, claim, firm


def test_an_advance_is_born_issued_and_a_registered_firm_is_born_network_inactive(api):
    """PRD §3.9: "A registered firm sits in `NETWORK_INACTIVE` with
    `activated_for_event_id` null and `open_job_count` of zero."
    PRD §3.8: "Issuance creates the advance in `ISSUED`, refreshes the claim's
    `advance_cap`, and appends a `PAYMENT` ledger entry whose paid movement is the
    issued `amount` and whose case-reserve movement is the negation of that amount,
    recording that row's identifier in the advance's `reserve_entry_id`."
    PRD §3.8: "The claim moves `NONE → ADVANCE_ISSUED` on the payment axis and, when
    `advance_issuing_examiner_user_id` was previously null, the acting `X-User-ID` is
    recorded there as the segregation-of-duties anchor that will later block this same
    user from closing the claim."

    Design: Corner/state_machines/corner_sm_initial_state_advance_issued_and_vendor_network_inactive
    """
    event, claim, firm = _triaged_claim_and_fresh_firm(api)
    # There is no DRAFT/PENDING first state on the vendor machine either: the firm
    # is unusable until it is activated onto an event.
    assert firm["status"] == "NETWORK_INACTIVE"
    assert firm["activated_for_event_id"] is None
    assert firm["open_job_count"] == 0

    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 500, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    # No approval hop: the money and its ledger row exist the instant POST returns.
    assert advance["status"] == "ISSUED"
    assert_money_equals(advance["amount"], 500.00, "amount")
    assert advance["basis"] == "STRUCTURE_PARTIAL"
    assert advance["reserve_entry_id"] is not None

    refreshed = validate_success(api.get_claim(claim["id"], CE))
    # round(round(50000 * 0.30, 2) * 0.60, 2) = 9000.00 with no mandate floor.
    assert_money_equals(refreshed["advance_cap"], 9000.00, "advance_cap")
    assert_money_equals(refreshed["advance_paid_total"], 500.00, "advance_paid_total")
    assert refreshed["payment_status"] == "ADVANCE_ISSUED"
    assert refreshed["handling_status"] == "TRIAGED"
    assert_money_equals(refreshed["paid_amount"], 500.00, "paid_amount")
    assert_money_equals(refreshed["case_reserve"], 22000.00, "case_reserve")
    assert refreshed["advance_issuing_examiner_user_id"] == "ce_1"

    rows, meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 2
    assert rows[1]["entry_type"] == "PAYMENT"
    assert_money_equals(rows[1]["delta_paid"], 500.00, "delta_paid")
    assert_money_equals(rows[1]["delta_case_reserve"], -500.00, "delta_case_reserve")
    assert rows[1]["sequence_no"] == 2
    assert rows[1]["id"] == advance["reserve_entry_id"]

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["paid_total"], 500.00, "paid_total")
    assert_money_equals(refreshed_event["case_reserve_total"], 22000.00, "case_reserve_total")
    assert_money_equals(refreshed_event["incurred_total"], 22500.00, "incurred_total")

    firms, firm_meta = validate_paginated(
        api.list_vendor_firms(CM, params={"status": "NETWORK_INACTIVE"})
    )
    assert firm_meta["total_count"] == 1
    assert firms[0]["id"] == firm["id"]


# ---------------------------------------------------------------------------
# corner_sm_valid_transition_declared_to_surge_active_with_both_gates_met
# ---------------------------------------------------------------------------
def test_surge_activation_lands_once_active_housing_and_a_fresh_estimate_both_exist(api):
    """PRD §3.1: "The event must be in `DECLARED`, or the request fails with
    `ERR_EVENT_NOT_DECLARED`."
    PRD §3.1: "At least one housing block on the event must be in `ACTIVE`, or the
    request fails with `ERR_NO_ACTIVE_HOUSING` — a carrier does not surge people into a
    market it has not booked rooms in."
    PRD §3.1: "And at least one loss-estimate snapshot on the event must be non-stale,
    or the request fails with `ERR_LOSS_ESTIMATE_STALE`; an event with no snapshots at
    all fails this check too, since zero rows satisfy the requirement vacuously in the
    wrong direction."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but below
    8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."

    Design: Corner/state_machines/corner_sm_valid_transition_declared_to_surge_active_with_both_gates_met
    """
    event = declared_event(api, "CAT-2026-1102")
    block = active_block(api, event["id"], hotel_name="Gulf Suites")
    assert block["status"] == "ACTIVE"
    triaged = triaged_claim(api, "POL-1102A", event["id"])
    assert triaged["triage_tier"] == "STANDARD"

    before = validate_success(api.get_event(event["id"], CM))
    assert before["posture"] == "OPEN"
    # Minted only now, so the snapshot's high-water sits at the INITIAL_CASE entry
    # triage appended rather than behind it.
    snapshot = mint_estimate(api, event["id"])
    assert snapshot["input_reserve_sequence_high_water"] == 1
    assert snapshot["stale"] is False

    activated = validate_success(api.activate_surge(event["id"], CM))

    assert activated["status"] == "SURGE_ACTIVE"
    # Strain is 0: the one claim is STANDARD, the snapshot is fresh, no moratorium.
    assert activated["posture"] == "OPEN"
    assert activated["declared_at_utc"] == CLOCK_START
    assert activated["version"] > before["version"]
    assert activated["open_claim_count"] == 1
    assert activated["surge_adjuster_count"] == 0
    assert_money_equals(activated["case_reserve_total"], 22500.00, "case_reserve_total")
    assert_money_equals(activated["incurred_total"], 22500.00, "incurred_total")
    assert_money_equals(activated["paid_total"], 0.00, "paid_total")

    estimates, est_meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"]})
    )
    assert est_meta["total_count"] == 1
    assert estimates[0]["id"] == snapshot["id"]
    # activate-surge appends no ledger row, so nothing overtook the snapshot.
    assert estimates[0]["stale"] is False

    blocks, block_meta = validate_paginated(
        api.list_housing_blocks(DC, params={"event_id": event["id"], "status": "ACTIVE"})
    )
    assert block_meta["total_count"] == 1
    assert blocks[0]["id"] == block["id"]


# ---------------------------------------------------------------------------
# corner_sm_precondition_enforcement_surge_gates_fail_in_declared_order
# ---------------------------------------------------------------------------
def test_each_surge_precondition_is_isolated_to_its_own_error(api):
    """PRD §3.1: "At least one housing block on the event must be in `ACTIVE`, or the
    request fails with `ERR_NO_ACTIVE_HOUSING` — a carrier does not surge people into a
    market it has not booked rooms in."
    PRD §3.1: "And at least one loss-estimate snapshot on the event must be non-stale,
    or the request fails with `ERR_LOSS_ESTIMATE_STALE`; an event with no snapshots at
    all fails this check too, since zero rows satisfy the requirement vacuously in the
    wrong direction."
    PRD §3.8: "Its `stale` flag is a computed property re-evaluated on every read: it
    reads true exactly when a ledger entry exists on the event whose `sequence_no` is
    greater than the snapshot's recorded high-water mark."
    PRD §3.4: "Opening a block moves it `PENDING → ACTIVE` and is refused with
    `ERR_HOUSING_NOT_PENDING` from any other status."

    Design: Corner/state_machines/corner_sm_precondition_enforcement_surge_gates_fail_in_declared_order
    """
    event = declared_event(api, "CAT-2026-1103")
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Bayou Lodge",
                "city": "Houston",
                "rooms_total": 4,
                "nightly_rate": 140,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-06T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    assert block["status"] == "PENDING"
    claim = new_claim(api, "POL-1103A", event["id"])
    # Minted while the event has no ledger rows at all, so it is born non-stale on a
    # high-water mark of 0.
    snapshot = mint_estimate(api, event["id"])
    assert snapshot["input_reserve_sequence_high_water"] == 0
    assert snapshot["stale"] is False

    # Only the housing gate is unsatisfied: the snapshot is still fresh.
    validate_error(
        api.activate_surge(event["id"], CM), ApiErrorId.ERR_NO_ACTIVE_HOUSING, 409
    )
    assert validate_success(api.get_event(event["id"], CM))["status"] == "DECLARED"

    assert validate_success(api.open_housing_block(block["id"], DC))["status"] == "ACTIVE"
    # Triage appends INITIAL_CASE as sequence_no 1, which overtakes the snapshot's
    # recorded high-water of 0 and is the only route the API offers to staleness.
    validate_success(api.triage_claim(claim["id"], CE))

    # Now only the snapshot gate is left unsatisfied.
    validate_error(
        api.activate_surge(event["id"], CM), ApiErrorId.ERR_LOSS_ESTIMATE_STALE, 409
    )

    refreshed = validate_success(api.get_event(event["id"], CM))
    assert refreshed["status"] == "DECLARED"
    # Strain 3 arrives purely from the stale latest snapshot, so the band tightens.
    assert refreshed["posture"] == "RESTRICTED"

    estimates, est_meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"]})
    )
    assert est_meta["total_count"] == 1
    assert estimates[0]["id"] == snapshot["id"]
    assert estimates[0]["input_reserve_sequence_high_water"] == 0
    assert estimates[0]["stale"] is True

    _, block_meta = validate_paginated(
        api.list_housing_blocks(DC, params={"event_id": event["id"], "status": "ACTIVE"})
    )
    assert block_meta["total_count"] == 1

    rows, row_meta = validate_paginated(
        api.list_reserve_entries(CM, params={"event_id": event["id"]})
    )
    assert row_meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"
    assert rows[0]["sequence_no"] == 1


# ---------------------------------------------------------------------------
# corner_sm_invalid_transition_five_illegal_hops_each_own_error
# ---------------------------------------------------------------------------
def _monitoring_event_and_uncoded_claim(api):
    """CAT-2026-1104 left in MONITORING (never declared) plus a claim taken with no
    `event_id`, so it sits in INTAKE with a null parent."""
    event = new_event(
        api,
        "CAT-2026-1104",
        peril_type="WINTER_STORM",
        jurisdiction_state="GA",
        event_start_utc="2026-07-28T00:00:00.000Z",
        exposure_count=120,
        avg_insured_value=140000,
        expected_severity_index=0.1000,
    )
    claim = new_claim(
        api,
        "POL-1104A",
        loss_state="GA",
        loss_date_utc="2026-07-28T00:00:00.000Z",
        reported_loss_amount=9000,
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 120000,
                "deductible_amount": 1000,
                "estimated_damage_amount": 9000,
            }
        ],
    )
    return event, claim


def test_five_undeclared_hops_each_answer_with_their_own_transition_error(api):
    """PRD §3.1: "The event must be in `DECLARED`, or the request fails with
    `ERR_EVENT_NOT_DECLARED`."
    PRD §3.1: "The event must be in `SURGE_ACTIVE` (`ERR_EVENT_NOT_SURGE_ACTIVE`); the
    event's `moratorium_active` flag must be false (`ERR_MORATORIUM_ACTIVE`), because a
    carrier may not wind down its catastrophe operation while the regulator's
    cancellation moratorium is still in force; and no claim on the event may sit in
    `INTAKE` or `TRIAGED` (`ERR_UNTRIAGED_CLAIMS_REMAIN`), because those are files nobody
    has scheduled work on."
    PRD §3.6: "Four preconditions guard it: the claim must be in `INTAKE`
    (`ERR_CLAIM_NOT_IN_INTAKE`); its `event_id` must not be null
    (`ERR_CLAIM_NOT_CAT_CODED`); the parent event's `status` must be `DECLARED` or
    `SURGE_ACTIVE` (`ERR_EVENT_NOT_DECLARED`); and the parent event's posture must not be
    `FROZEN` (`ERR_EVENT_POSTURE_FROZEN`)."
    PRD §3.6: "The claim must be `INSPECTED` (`ERR_CLAIM_NOT_INSPECTED`)."
    PRD §3.6: "The claim must be `CLOSED` (`ERR_CLAIM_NOT_CLOSED`); its `reopen_count`
    must be strictly below 2, so a claim that has already been reopened twice is refused
    with `ERR_REOPEN_LIMIT_REACHED`; and the parent event must not be `CLOSED`
    (`ERR_EVENT_CLOSED`)."

    Design: Corner/state_machines/corner_sm_invalid_transition_five_illegal_hops_each_own_error
    """
    event, claim = _monitoring_event_and_uncoded_claim(api)
    assert event["status"] == "MONITORING"
    assert event["version"] == 1
    assert claim["version"] == 1

    probes = [
        # MONITORING cannot skip the declaration hop straight to SURGE_ACTIVE.
        (api.activate_surge(event["id"], CM), ApiErrorId.ERR_EVENT_NOT_DECLARED),
        (api.demobilize_event(event["id"], CM), ApiErrorId.ERR_EVENT_NOT_SURGE_ACTIVE),
        # The claim IS in INTAKE, so the null parent is the precondition that fails.
        (api.triage_claim(claim["id"], CE), ApiErrorId.ERR_CLAIM_NOT_CAT_CODED),
        (api.close_claim(claim["id"], CE), ApiErrorId.ERR_CLAIM_NOT_INSPECTED),
        (api.reopen_claim(claim["id"], CE), ApiErrorId.ERR_CLAIM_NOT_CLOSED),
    ]
    for response, expected in probes:
        validate_error(response, expected, 409)
        assert response.json()["meta"]["api_request_id"].startswith("req_")

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["status"] == "MONITORING"
    assert refreshed_event["posture"] == "OPEN"
    assert refreshed_event["version"] == event["version"]
    assert refreshed_event["declared_at_utc"] is None
    assert refreshed_event["open_claim_count"] == 0
    assert_money_equals(refreshed_event["case_reserve_total"], 0.00, "case_reserve_total")

    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["handling_status"] == "INTAKE"
    assert refreshed_claim["payment_status"] == "NONE"
    assert refreshed_claim["version"] == claim["version"]
    assert_money_equals(refreshed_claim["severity_score"], 0.00, "severity_score")
    assert refreshed_claim["triage_tier"] is None
    assert refreshed_claim["inspection_mode"] is None
    assert refreshed_claim["deadline_utc"] is None
    assert refreshed_claim["reopen_count"] == 0
    assert_money_equals(refreshed_claim["case_reserve"], 0.00, "case_reserve")

    # Five rejected hops appended nothing to the append-only ledger.
    _, row_meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": claim["id"]})
    )
    assert row_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# corner_sm_terminal_state_lockdown_closed_event_and_released_block
# ---------------------------------------------------------------------------
def _stood_down_event_and_released_block(api):
    """CAT-2026-1105 taken DECLARED → CLOSED down the stand-down branch (no claims,
    no surge adjusters), which drags its PENDING block to RELEASED."""
    event = declared_event(
        api,
        "CAT-2026-1105",
        exposure_count=90,
        avg_insured_value=130000,
        expected_severity_index=0.0500,
    )
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Standdown Suites",
                "city": "Austin",
                "rooms_total": 3,
                "nightly_rate": 110,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-04T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    closed = validate_success(api.close_event(event["id"], CM))
    return closed, block


def test_a_closed_event_and_its_released_block_refuse_every_further_hop(api):
    """PRD §3.1: "It requires the event to be in `DECLARED` with `open_claim_count` of
    zero and `surge_adjuster_count` of zero; a `DECLARED` event failing either count is
    refused with `ERR_EVENT_NOT_STANDDOWN_ELIGIBLE`."
    PRD §3.1: "Its side-effect set is strictly smaller than the full path's: every
    housing block on the event in `PENDING` or `ACTIVE` moves to `RELEASED`, and `posture`
    becomes `FROZEN`."
    PRD §3.1: "It requires that the event still be in `MONITORING` — otherwise
    `ERR_EVENT_NOT_MONITORING` — and re-checks that the `cat_code` is set and held by no
    other event, refusing with `ERR_CAT_CODE_TAKEN` if another event has taken it in the
    meantime."
    PRD §3.4: "Releasing a block hands the inventory back to the hotel and is available
    from `PENDING`, `ACTIVE` or `EXHAUSTED`; a block already `RELEASED` is refused with
    `ERR_HOUSING_NOT_RELEASABLE`."

    Design: Corner/state_machines/corner_sm_terminal_state_lockdown_closed_event_and_released_block
    """
    closed, block = _stood_down_event_and_released_block(api)
    assert closed["status"] == "CLOSED"
    assert closed["posture"] == "FROZEN"

    # Re-declaring a closed event is the hop that looks like a harmless restart.
    validate_error(
        api.declare_event(closed["id"], CM), ApiErrorId.ERR_EVENT_NOT_MONITORING, 409
    )
    validate_error(
        api.activate_surge(closed["id"], CM), ApiErrorId.ERR_EVENT_NOT_DECLARED, 409
    )
    validate_error(
        api.demobilize_event(closed["id"], CM), ApiErrorId.ERR_EVENT_NOT_SURGE_ACTIVE, 409
    )
    # RELEASED has no outgoing transition either, so a second release is not a no-op.
    validate_error(
        api.release_housing_block(block["id"], DC), ApiErrorId.ERR_HOUSING_NOT_RELEASABLE, 409
    )

    refreshed = validate_success(api.get_event(closed["id"], CM))
    assert refreshed["status"] == "CLOSED"
    assert refreshed["posture"] == "FROZEN"
    assert refreshed["version"] == closed["version"]
    assert refreshed["declared_at_utc"] == CLOCK_START

    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["status"] == "RELEASED"
    assert refreshed_block["rooms_occupied"] == 0
    assert refreshed_block["rooms_available"] == 3

    blocks, block_meta = validate_paginated(
        api.list_housing_blocks(
            DC, params={"event_id": closed["id"], "status": "RELEASED"}
        )
    )
    assert block_meta["total_count"] == 1
    assert blocks[0]["id"] == block["id"]


# ---------------------------------------------------------------------------
# corner_sm_idempotency_repeat_triage_void_and_open_are_rejected_not_replayed
# ---------------------------------------------------------------------------
def _triaged_claim_with_a_voided_advance(api):
    """CAT-2026-1106 DECLARED with an ACTIVE 2-room block, one claim TRIAGED to
    STANDARD (ReserveEntry 1) and a 500.00 advance issued (entry 2) then voided
    (entry 3)."""
    event = declared_event(api, "CAT-2026-1106")
    block = active_block(
        api,
        event["id"],
        hotel_name="Replay Inn",
        rooms_total=2,
        nightly_rate=130,
        block_end_date="2026-09-05T00:00:00.000Z",
    )
    triaged = triaged_claim(api, "POL-1106A", event["id"])
    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": triaged["id"], "requested_amount": 500, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    voided = validate_success(
        api.void_advance_payment(advance["id"], {"void_reason": "Duplicate issuance"}, CE)
    )
    return event, block, triaged, voided


def test_replaying_triage_void_and_open_is_refused_without_replaying_any_side_effect(api):
    """PRD §3.6: "Four preconditions guard it: the claim must be in `INTAKE`
    (`ERR_CLAIM_NOT_IN_INTAKE`); its `event_id` must not be null
    (`ERR_CLAIM_NOT_CAT_CODED`); the parent event's `status` must be `DECLARED` or
    `SURGE_ACTIVE` (`ERR_EVENT_NOT_DECLARED`); and the parent event's posture must not be
    `FROZEN` (`ERR_EVENT_POSTURE_FROZEN`)."
    PRD §3.8: "Three preconditions guard it: the advance's `status` must be `ISSUED`
    (`ERR_ADVANCE_NOT_ISSUED`); the claim's `payment_status` must not be `SETTLED`
    (`ERR_CLAIM_ALREADY_SETTLED`); and the void must not drop the claim's
    `advance_paid_total` below the mandated floor of any `EFFECTIVE`
    `ADVANCE_PAYMENT_MANDATE` bulletin covering the current instant, so the void is
    permitted either when no such mandate is in force or when the remaining advanced
    total still satisfies the floor (`ERR_ADVANCE_MANDATE_FLOOR`, HTTP 409)."
    PRD §3.4: "Opening a block moves it `PENDING → ACTIVE` and is refused with
    `ERR_HOUSING_NOT_PENDING` from any other status."
    PRD §2.10: "The compensating-action guarantee that follows is exact, not approximate:
    issuing an advance payment on a claim and then voiding that same advance leaves the
    event's `incurred_total`, the claim's `case_reserve` and the claim's `paid_amount`
    each exactly equal to their pre-issuance values."
    PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED → NONE` on
    the payment axis when `advance_paid_total` returns to exactly 0.00 — and
    `advance_issuing_examiner_user_id` is **retained**, because a void does not erase the
    fact that this user once released money on the file."

    Design: Corner/state_machines/corner_sm_idempotency_repeat_triage_void_and_open_are_rejected_not_replayed
    """
    event, block, triaged, voided = _triaged_claim_with_a_voided_advance(api)
    assert_money_equals(triaged["severity_score"], 38.00, "severity_score")
    assert voided["status"] == "VOIDED"
    assert voided["voided_at_utc"] == CLOCK_START
    before = validate_success(api.get_claim(triaged["id"], CE))

    validate_error(
        api.triage_claim(triaged["id"], CE), ApiErrorId.ERR_CLAIM_NOT_IN_INTAKE, 409
    )
    validate_error(
        api.void_advance_payment(voided["id"], {"void_reason": "Duplicate issuance"}, CE),
        ApiErrorId.ERR_ADVANCE_NOT_ISSUED,
        409,
    )
    validate_error(
        api.open_housing_block(block["id"], DC), ApiErrorId.ERR_HOUSING_NOT_PENDING, 409
    )

    after = validate_success(api.get_claim(triaged["id"], CE))
    assert after["severity_score"] == before["severity_score"]
    assert after["deadline_utc"] == before["deadline_utc"]
    assert after["version"] == before["version"]
    assert after["handling_status"] == "TRIAGED"
    assert after["payment_status"] == "NONE"
    assert_money_equals(after["case_reserve"], 22500.00, "case_reserve")
    assert_money_equals(after["paid_amount"], 0.00, "paid_amount")
    assert_money_equals(after["advance_paid_total"], 0.00, "advance_paid_total")
    assert after["advance_issuing_examiner_user_id"] == "ce_1"

    rows, row_meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": triaged["id"]})
    )
    assert row_meta["total_count"] == 3
    assert [row["entry_type"] for row in rows] == ["INITIAL_CASE", "PAYMENT", "REVERSAL"]
    assert [row["sequence_no"] for row in rows] == [1, 2, 3]

    advances, advance_meta = validate_paginated(
        api.list_advance_payments(CE, params={"claim_id": triaged["id"]})
    )
    assert advance_meta["total_count"] == 1
    assert advances[0]["voided_at_utc"] == voided["voided_at_utc"]

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["incurred_total"], 22500.00, "incurred_total")
    assert_money_equals(refreshed_event["case_reserve_total"], 22500.00, "case_reserve_total")
    assert_money_equals(refreshed_event["paid_total"], 0.00, "paid_total")

    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["status"] == "ACTIVE"
    assert refreshed_block["rooms_available"] == 2
    assert refreshed_block["rooms_occupied"] == 0


# ---------------------------------------------------------------------------
# corner_sm_side_effect_execution_no_access_reresolves_mode_without_a_revision
# ---------------------------------------------------------------------------
def _in_progress_field_inspection(api):
    """CAT-2026-1107 DECLARED with one desk-certified STAFF adjuster, one claim TRIAGED
    to STANDARD/FIELD (ReserveEntry 1 only) and that claim's FIELD assignment driven to
    IN_PROGRESS with the clock inside the assignment window.

    The funding deployment is deliberately left in `REQUESTED`: §3.7 lists the six checks
    standing between the request and a scheduled assignment, and none of them requires
    the named deployment to have been confirmed.
    """
    event = declared_event(api, "CAT-2026-1107")
    adjuster = new_adjuster(api, "No Access Nate", desk_certified=True)
    triaged = triaged_claim(api, "POL-1107A", event["id"])
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-10T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": triaged["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-09-02T00:00:00.000Z",
                "window_end_utc": "2026-09-03T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "deployment_id": deployment["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-02T08:00:00.000Z", DC))
    adjuster_headers = make_adjuster_headers(adjuster["id"])
    started = validate_success(api.start_inspection(assignment["id"], adjuster_headers))
    return event, triaged, adjuster, assignment, adjuster_headers, started


def test_reporting_no_access_reroutes_the_claim_without_touching_the_ledger(api):
    """PRD §3.7: "It stamps `report_submitted_at_utc`, flips the claim's `access_status`
    to `INACCESSIBLE`, re-resolves the claim's `inspection_mode` through the branch ladder
    of §3.6 (which for a severe claim now yields `AERIAL` and for a lighter one `DESK`),
    and pushes the claim `INSPECTION_PENDING → INSPECTED` — but with
    `verified_damage_amount` left null and **no** `REVISION` ledger entry, because nothing
    was verified."
    PRD §3.6: "**The inspection mode** is resolved by taking the first matching branch,
    top to bottom, and is recomputed at triage, on reopen, and when an adjuster reports the
    property inaccessible."
    PRD §3.6: "Otherwise, if `access_status` is `INACCESSIBLE`, the mode is `DESK`."
    PRD §3.3: "The result is clamped so that it is not below 0 and not above 100, and only
    then rounded half up to 2 decimal places into `surge_capacity_score`."

    Design: Corner/state_machines/corner_sm_side_effect_execution_no_access_reresolves_mode_without_a_revision
    """
    event, triaged, adjuster, assignment, adjuster_headers, started = (
        _in_progress_field_inspection(api)
    )
    assert_money_equals(triaged["severity_score"], 38.00, "severity_score")
    assert triaged["inspection_mode"] == "FIELD"
    assert triaged["access_status"] == "ACCESSIBLE"
    assert_money_equals(triaged["case_reserve"], 22500.00, "case_reserve")
    assert started["status"] == "IN_PROGRESS"

    reported = validate_success(api.report_no_access(assignment["id"], adjuster_headers))

    assert reported["status"] == "NO_ACCESS"
    assert reported["report_submitted_at_utc"] == "2026-09-02T08:00:00.000Z"
    assert reported["verified_damage_amount"] is None

    refreshed_claim = validate_success(api.get_claim(triaged["id"], CE))
    assert refreshed_claim["access_status"] == "INACCESSIBLE"
    # INACCESSIBLE with tier STANDARD misses the AERIAL branch, which needs COMPLEX or
    # CAT_SEVERE, so the ladder falls through to DESK.
    assert refreshed_claim["inspection_mode"] == "DESK"
    assert refreshed_claim["handling_status"] == "INSPECTED"
    assert refreshed_claim["verified_damage_amount"] is None
    # Severity is stamped at triage and on reopen only; it is never re-derived here.
    assert refreshed_claim["severity_score"] == triaged["severity_score"]
    assert refreshed_claim["triage_tier"] == "STANDARD"
    assert_money_equals(refreshed_claim["case_reserve"], 22500.00, "case_reserve")

    rows, row_meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": triaged["id"]})
    )
    assert row_meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 22500.00, "case_reserve_total")
    assert_money_equals(refreshed_event["incurred_total"], 22500.00, "incurred_total")
    assert_money_equals(refreshed_event["paid_total"], 0.00, "paid_total")

    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    # The assignment left the SCHEDULED/IN_PROGRESS population, so load is zero again:
    # 100 * (1 - 0/8) - 0 credential - 0 fatigue + 5 desk bonus, clamped to 100.
    assert refreshed_adjuster["open_assignment_count"] == 0
    assert_money_equals(
        refreshed_adjuster["surge_capacity_score"], 100.00, "surge_capacity_score"
    )

    assignments, assignment_meta = validate_paginated(
        api.list_inspection_assignments(
            DC, params={"claim_id": triaged["id"], "status": "NO_ACCESS"}
        )
    )
    assert assignment_meta["total_count"] == 1
    assert assignments[0]["id"] == assignment["id"]
