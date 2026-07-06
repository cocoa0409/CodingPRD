"""Bar-kit reservation overlap, breakage reconciliation, and the settle-charge
cascade.

Design queues:
  A (Difficulty): resource_temporal_overlap/kit_reservation_no_buffer_overlap,
                  transitive_cascade/breakage_settle_charges_event_depth2,
                  cross_entity_state_dependency/breakage_create_requires_kit_returned,
                  compensating_invariant/breakage_glassware_unit_conservation
  B (Corner): breakage_count_mismatch, kit_return_before_deploy_invalid_state
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_draft_event, create_bar_kit, setup_returned_kit, setup_deployed_kit,
    create_kit_reservation_payload, create_breakage_report_payload,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / kit_reservation_no_buffer_overlap
# ---------------------------------------------------------------------------
def test_overlapping_kit_reservations_rejected(api):
    """PRD §3.6: "if the new half-open window overlaps any other non-terminal
    reservation for the same kit, the create is rejected with
    ERR_KIT_DOUBLE_BOOKED (HTTP 409), though exact end-to-start adjacency is
    allowed."

    Design: Difficulty/resource_temporal_overlap/kit_reservation_no_buffer_overlap
    """
    kit = create_bar_kit(api)
    a = create_draft_event(api, title="A", event_start="2026-06-01T18:00:00Z",
                           event_end="2026-06-01T23:00:00Z")
    b = create_draft_event(api, title="B", event_start="2026-06-01T23:00:00Z",
                           event_end="2026-06-02T03:00:00Z")
    get_success_data(api.create_kit_reservation(
        a["event"]["id"], create_kit_reservation_payload(
            kit["id"], reserve_start="2026-06-01T16:00:00Z",
            reserve_end="2026-06-01T23:00:00Z"), COORD))
    resp = api.create_kit_reservation(
        b["event"]["id"], create_kit_reservation_payload(
            kit["id"], reserve_start="2026-06-01T22:00:00Z",
            reserve_end="2026-06-02T02:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_KIT_DOUBLE_BOOKED.value)


def test_exact_adjacent_kit_reservations_allowed(api):
    """PRD §2.9: "two reservations for the same kit conflict only when their
    half-open intervals actually overlap, and exact adjacency — one window
    ending precisely when the next begins — is permitted."

    Design: Difficulty/resource_temporal_overlap/kit_reservation_no_buffer_overlap
    """
    kit = create_bar_kit(api)
    a = create_draft_event(api, title="A", event_start="2026-06-01T18:00:00Z",
                           event_end="2026-06-01T23:00:00Z")
    b = create_draft_event(api, title="B", event_start="2026-06-01T23:00:00Z",
                           event_end="2026-06-02T03:00:00Z")
    get_success_data(api.create_kit_reservation(
        a["event"]["id"], create_kit_reservation_payload(
            kit["id"], reserve_start="2026-06-01T16:00:00Z",
            reserve_end="2026-06-01T23:00:00Z"), COORD))
    # Second window begins exactly when the first ends (23:00) — adjacency.
    resp = api.create_kit_reservation(
        b["event"]["id"], create_kit_reservation_payload(
            kit["id"], reserve_start="2026-06-01T23:00:00Z",
            reserve_end="2026-06-02T02:00:00Z"), COORD)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / breakage_settle_charges_event_depth2
# ---------------------------------------------------------------------------
def _draft_breakage_report(api, items_broken, items_returned):
    bundle = setup_returned_kit(api, glassware_count=200)
    report = get_success_data(api.create_breakage_report(
        bundle["event"]["id"],
        create_breakage_report_payload(bundle["kit"]["id"], items_broken, items_returned),
        COORD))
    bundle["report"] = report
    return bundle


def test_settle_computes_breakage_fee(api):
    """PRD §3.9: "A free-breakage allowance is the items_checked_out baseline
    multiplied by 2 percent, rounded up. The chargeable broken count is the
    amount by which items_broken exceeds that allowance, or zero if it does not
    exceed it. The breakage fee (breakage_fee_cents) is the chargeable broken
    count multiplied by 500 cents of replacement cost per item."

    Design: Difficulty/transitive_cascade/breakage_settle_charges_event_depth2
    """
    bundle = _draft_breakage_report(api, 10, 190)
    settled = validate_success(api.settle_breakage_report(bundle["report"]["id"], COORD))
    assert settled["status"] == "SETTLED"
    assert settled["breakage_fee_cents"] == 3000


def test_settle_charge_recomputes_event_balance(api):
    """PRD §3.9: "When the breakage fee is greater than 0, settling creates a
    BREAKAGE_CHARGE payment equal to the fee; that new charge then flows back
    through the ledger, recomputing the event's balance_due_cents and
    payment_status."
    PRD §3.2: "The balance due (balance_due_cents) for a non-terminal event is
    the final grand total, plus every BREAKAGE_CHARGE and every CANCELLATION_FEE
    posted against the event, less amount_paid_cents".

    Design: Difficulty/transitive_cascade/breakage_settle_charges_event_depth2
    """
    bundle = _draft_breakage_report(api, 10, 190)
    validate_success(api.settle_breakage_report(bundle["report"]["id"], COORD))
    ev = get_success_data(api.get_event(bundle["event"]["id"], COORD))
    # final 311440 + breakage 3000 - deposit paid 138720 = 175720.
    assert ev["balance_due_cents"] == 175720


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / breakage_create_requires_kit_returned
# ---------------------------------------------------------------------------
def test_breakage_report_requires_returned_reservation(api):
    """PRD §3.9: "A report can only be filed when a kit reservation for that
    event_id and kit_id pairing has reached RETURNED; without a returned
    reservation the filing is rejected with ERR_KIT_NOT_RETURNED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/breakage_create_requires_kit_returned
    """
    bundle = setup_deployed_kit(api, glassware_count=200)  # DEPLOYED, not returned
    resp = api.create_breakage_report(
        bundle["event"]["id"],
        create_breakage_report_payload(bundle["kit"]["id"], 5, 195), COORD)
    validate_error(resp, ApiErrorId.ERR_KIT_NOT_RETURNED.value)


def test_breakage_report_allowed_once_reservation_returned(api):
    """PRD §3.9: "A report can only be filed when a kit reservation for that
    event_id and kit_id pairing has reached RETURNED".

    Design: Difficulty/cross_entity_state_dependency/breakage_create_requires_kit_returned
    """
    bundle = setup_returned_kit(api, glassware_count=200)
    resp = api.create_breakage_report(
        bundle["event"]["id"],
        create_breakage_report_payload(bundle["kit"]["id"], 5, 195), COORD)
    report = validate_success(resp, 201)
    assert report["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / breakage_glassware_unit_conservation
# ---------------------------------------------------------------------------
def test_breakage_report_copies_checked_out_baseline(api):
    """PRD §3.9: "On creation the report copies the returned reservation's
    items_checked_out as its own conservation baseline and opens with status of
    DRAFT."

    Design: Difficulty/compensating_invariant/breakage_glassware_unit_conservation
    """
    bundle = _draft_breakage_report(api, 10, 190)
    report = bundle["report"]
    assert report["items_checked_out"] == 200
    assert report["status"] == "DRAFT"


def test_breakage_report_conserves_broken_plus_returned(api):
    """PRD §3.9: "Glassware must conserve: `items_broken` plus `items_returned`
    must equal that `items_checked_out` baseline, else the filing is rejected
    with `ERR_BREAKAGE_COUNT_MISMATCH` (HTTP 422)."

    Design: Difficulty/compensating_invariant/breakage_glassware_unit_conservation
    """
    bundle = _draft_breakage_report(api, 10, 190)
    report = bundle["report"]
    assert report["items_broken"] == 10
    assert report["items_returned"] == 190
    assert report["items_broken"] + report["items_returned"] == report["items_checked_out"]


# ---------------------------------------------------------------------------
# Queue B — breakage count mismatch and invalid-state return
# ---------------------------------------------------------------------------
def test_breakage_count_mismatch_rejected(api):
    """PRD §3.9: "Glassware must conserve: `items_broken` plus `items_returned`
    must equal that `items_checked_out` baseline, else the filing is rejected
    with `ERR_BREAKAGE_COUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/breakage_count_mismatch
    """
    bundle = setup_returned_kit(api, glassware_count=200)
    resp = api.create_breakage_report(
        bundle["event"]["id"],
        create_breakage_report_payload(bundle["kit"]["id"], 10, 185), COORD)
    validate_error(resp, ApiErrorId.ERR_BREAKAGE_COUNT_MISMATCH.value)


def test_return_reserved_kit_is_invalid_state(api):
    """PRD §3.6: "A reservation may be deployed once the event is in service ...
    A deployed kit is later returned, advancing DEPLOYED → RETURNED."
    PRD §2.7: "State legality — the target resource is in a status from which
    the requested transition is defined, else ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/kit_return_before_deploy_invalid_state
    """
    bundle = create_draft_event(api)
    kit = create_bar_kit(api)
    resv = get_success_data(api.create_kit_reservation(
        bundle["event"]["id"], create_kit_reservation_payload(kit["id"]), COORD))
    resp = api.return_kit_reservation(resv["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
