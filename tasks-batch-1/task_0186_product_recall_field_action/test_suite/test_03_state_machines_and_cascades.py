"""Parallel dispositions, cyclic quarantine holds, transitive announce/settle
cascades, and the compensating invariants.

Difficulty queue: non_linear_state_machine, transitive_cascade,
compensating_invariant.
Corner queue: state_machines section (valid/invalid transitions, preconditions).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    TEST_USERS, make_headers,
    ApiErrorId,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall,
    draft_and_submit_initial_report, send_all_notifications,
    setup_draft_recall_with_lot, setup_classified_recall,
    setup_announced_recall, setup_monitoring_recall,
    setup_recall_with_recovery,
    open_disposition, open_and_return_disposition, open_returned_owed_refund,
    settle_refund, get_first_quarantine_hold, get_first_notification,
)

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
AGENT = TEST_USERS["field_service_agent_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# non_linear_state_machine — Disposition parallel logistics x financial
# ===========================================================================
def test_disposition_parallel_axes_logistics_returned_financial_owed(api):
    """PRD §3.9: "it carries two independent state dimensions on one row: a
    `logistics_status` and a `financial_status` that evolve in parallel." PRD
    §3.9: "a `FinanceClerk` accrues a refund liability, moving `financial_status`
    from `NOT_OWED` to `OWED`; this is permitted only when the `disposition_type`
    is `REFUND` ... and the unit's return has already been received".

    Design: Difficulty/non_linear_state_machine/disposition_parallel_logistics_and_financial
    """
    _p, _l, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "TEMPORARY"}
    )
    cust = create_customer(contact_address="cp@x.com")
    # affected lot already declared; register the unit AFTER announce so affected recompute applies
    lot_id = _l["id"]
    unit = create_unit(lot_id, cust["id"], serial_number=5, sale_price_cents=7000)
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    assert disp["logistics_status"] == "RETURNED", disp["logistics_status"]
    assert disp["financial_status"] == "OWED", disp["financial_status"]


def test_disposition_logistics_advances_while_financial_stays_not_owed(api):
    """PRD §3.9: "A newly opened disposition starts with `logistics_status` of
    `PENDING` and `financial_status` of `NOT_OWED`". PRD §3.9: "a
    `FieldServiceAgent` records a return receipt, moving `logistics_status` from
    `PENDING` to `RETURNED` ... and it recomputes the recall's
    `recovered_unit_count` and `effectiveness_pct`."

    Design: Difficulty/non_linear_state_machine/disposition_parallel_logistics_and_financial
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "TEMPORARY"},
        classifier_user_id="user-par-1", announcer_user_id="user-par-2",
    )
    cust = create_customer(contact_address="par@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=6, sale_price_cents=7000)
    opened = open_disposition(recall["id"], unit["id"], disposition_type="REFUND", refund_basis="SALE_PRICE")
    assert opened["logistics_status"] == "PENDING", opened["logistics_status"]
    assert opened["financial_status"] == "NOT_OWED", opened["financial_status"]
    # Advance the logistics axis only; financial axis untouched.
    returned = validate_success(api.receive_return(opened["id"], AGENT), 200)
    assert returned["logistics_status"] == "RETURNED", returned["logistics_status"]
    assert returned["financial_status"] == "NOT_OWED", returned["financial_status"]


def test_quarantine_hold_cyclic_lift_then_reimpose(api):
    """PRD §3.7: "Lifting increments `lifted_count` by one". PRD §3.7: "A
    `LIFTED` hold may be re-imposed back to `ACTIVE` by a `RecallCoordinator`,
    forming a cyclic `ACTIVE → LIFTED → ACTIVE` loop, but only while the owning
    recall is neither `TERMINATED` nor `EFFECTIVE`".

    Design: Difficulty/non_linear_state_machine/quarantine_hold_cyclic_lift_reimpose
    """
    _p, _l, recall = setup_monitoring_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
    )
    hold = get_first_quarantine_hold(recall["id"])
    validate_success(api.lift_hold(hold["id"], COORD), 200)
    reimposed = validate_success(api.reimpose_hold(hold["id"], COORD), 200)
    assert reimposed["status"] == "ACTIVE", reimposed["status"]
    assert reimposed["lifted_count"] == 1, reimposed["lifted_count"]


def test_quarantine_hold_lift_increments_lifted_count(api):
    """PRD §3.7: "a `lifted_count` that starts at 0 and counts how many times the
    hold has gone from `ACTIVE` to `LIFTED`." PRD §3.7: "Lifting increments
    `lifted_count` by one and recomputes the target lot's `quarantine_status`".

    Design: Difficulty/non_linear_state_machine/quarantine_hold_cyclic_lift_reimpose
    """
    _p, _l, recall = setup_monitoring_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
    )
    hold = get_first_quarantine_hold(recall["id"])
    assert hold["lifted_count"] == 0, hold["lifted_count"]
    lifted = validate_success(api.lift_hold(hold["id"], COORD), 200)
    assert lifted["status"] == "LIFTED", lifted["status"]
    assert lifted["lifted_count"] == 1, lifted["lifted_count"]


# ===========================================================================
# transitive_cascade — announce -> hold ACTIVE -> lot HELD (depth 3)
# ===========================================================================
def test_announce_cascade_creates_active_hold(api):
    """PRD §3.6: "The quarantine cascade creates one new `ACTIVE`
    `QuarantineHold` for each affected lot that does not already have one".

    Design: Difficulty/transitive_cascade/announce_cascade_recall_hold_lot
    """
    _p, lot, recall = setup_classified_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-cas-1",
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-cas-2", "QualityOfficer")), 200
    )
    holds, meta = _list(api.list_quarantine_holds(COORD, params={"recall_id": recall["id"], "lot_id": lot["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert holds[0]["status"] == "ACTIVE", holds[0]["status"]


def test_announce_cascade_drives_lot_to_held(api):
    """PRD §3.6: "each newly active hold in turn drives its target lot's
    `quarantine_status` to `HELD`. The framing matters: the lot status change is
    caused by the hold's `ACTIVE` state, not directly by the recall."

    Design: Difficulty/transitive_cascade/announce_cascade_recall_hold_lot
    """
    _p, lot, recall = setup_classified_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-cas-3",
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-cas-4", "QualityOfficer")), 200
    )
    lot_after = validate_success(api.get_lot(lot["id"], COORD), 200)
    assert lot_after["quarantine_status"] == "HELD", lot_after["quarantine_status"]


# ===========================================================================
# transitive_cascade — settle-refund -> REFUNDED -> recall ledger (depth 2)
# ===========================================================================
def test_settle_refund_updates_recall_total_refund_cents(api):
    """PRD §3.10: "Settlement fixes `refund_amount_cents` via the refund-amount
    rule below and recomputes the recall's `total_refund_cents`." PRD §3.10:
    "`total_refund_cents` is the exact integer sum of `refund_amount_cents`
    across every disposition of the recall whose `financial_status` is
    `REFUNDED`."

    Design: Difficulty/transitive_cascade/settle_refund_cascade_disposition_recall_ledger
    """
    product = create_product(regulator="FDA", unit_list_price_cents=10000)
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="cf@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=7, sale_price_cents=12000)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-led-1", "RecallCoordinator"))
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-led-2", "QualityOfficer")), 200
    )
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    settled = settle_refund(disp["id"])
    assert settled["refund_amount_cents"] == 12000, settled["refund_amount_cents"]
    recall_after = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert recall_after["total_refund_cents"] == 12000, recall_after["total_refund_cents"]


def test_settle_refund_flips_financial_to_refunded(api):
    """PRD §3.9: "A `FinanceClerk` then settles the refund, moving
    `financial_status` from `OWED` to `REFUNDED`". PRD §3.10: "`total_refund_cents`
    is the exact integer sum of `refund_amount_cents` across every disposition of
    the recall whose `financial_status` is `REFUNDED`."

    Design: Difficulty/transitive_cascade/settle_refund_cascade_disposition_recall_ledger
    """
    product = create_product(regulator="FDA", unit_list_price_cents=10000)
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="cf2@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=7, sale_price_cents=12000)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-led-3", "RecallCoordinator"))
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-led-4", "QualityOfficer")), 200
    )
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    settled = settle_refund(disp["id"])
    assert settled["financial_status"] == "REFUNDED", settled["financial_status"]


# ===========================================================================
# compensating_invariant — cancel-return restores recovered_unit_count
# ===========================================================================
def test_cancel_return_restores_recovered_count(api):
    """PRD §3.9: "cancellation in any case recomputes `recovered_unit_count` and
    `effectiveness_pct`." PRD §3.11: "`recovered_unit_count` is the number of
    dispositions of this recall whose `logistics_status` is either `RETURNED` or
    `REPLACED` and whose dispositioned unit is affected — cancelled dispositions
    never count as recovered."

    Design: Difficulty/compensating_invariant/cancel_return_restores_recovered_count_invariant
    """
    _p, lot, recall = setup_announced_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-ci-1",
        announcer_user_id="user-ci-2",
    )
    cust = create_customer(contact_address="ci@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=4, sale_price_cents=5000)
    disp = open_and_return_disposition(recall["id"], unit["id"], disposition_type="RETURN")
    after_return = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert after_return["recovered_unit_count"] == 1, after_return["recovered_unit_count"]
    validate_success(api.cancel_disposition(disp["id"], AGENT), 200)
    after_cancel = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert after_cancel["recovered_unit_count"] == 0, after_cancel["recovered_unit_count"]
    assert after_cancel["effectiveness_pct"] == 0, after_cancel["effectiveness_pct"]


# ===========================================================================
# compensating_invariant — cancel OWED voids without touching refund ledger
# ===========================================================================
def test_cancel_owed_voids_and_ledger_unchanged(api):
    """PRD §3.9: "When a disposition is cancelled while its `financial_status` is
    `OWED`, that financial status is set to `VOID`". PRD §3.10:
    "`total_refund_cents` is the exact integer sum of `refund_amount_cents`
    across every disposition of the recall whose `financial_status` is
    `REFUNDED`."

    Design: Difficulty/compensating_invariant/cancel_owed_voids_without_touching_refund_ledger_invariant
    """
    _p, lot, recall = setup_announced_recall(
        product_overrides={"regulator": "CPSC", "unit_list_price_cents": 15000},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-ci-3",
        announcer_user_id="user-ci-4",
    )
    cust = create_customer(contact_address="ci2@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=6, sale_price_cents=15000)
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    cancelled = validate_success(api.cancel_disposition(disp["id"], AGENT), 200)
    assert cancelled["financial_status"] == "VOID", cancelled["financial_status"]
    recall_after = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert recall_after["total_refund_cents"] == 0, recall_after["total_refund_cents"]


def test_cancel_owed_disposition_moves_logistics_to_cancelled(api):
    """PRD §3.9: "An agent may also cancel a disposition, moving
    `logistics_status` from `PENDING` to `CANCELLED`". PRD §3.9: "When a
    disposition is cancelled while its `financial_status` is `OWED`, that
    financial status is set to `VOID`".

    Design: Difficulty/compensating_invariant/cancel_owed_voids_without_touching_refund_ledger_invariant
    """
    _p, lot, recall = setup_announced_recall(
        product_overrides={"regulator": "CPSC", "unit_list_price_cents": 15000},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-ci-5",
        announcer_user_id="user-ci-6",
    )
    cust = create_customer(contact_address="ci3@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=6, sale_price_cents=15000)
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    cancelled = validate_success(api.cancel_disposition(disp["id"], AGENT), 200)
    assert cancelled["logistics_status"] == "CANCELLED", cancelled["logistics_status"]
    assert cancelled["financial_status"] == "VOID", cancelled["financial_status"]


def test_cancel_return_drops_effectiveness_back_to_pre_return(api):
    """PRD §3.11: "`recovered_unit_count` is the number of dispositions of this
    recall whose `logistics_status` is either `RETURNED` or `REPLACED` and whose
    dispositioned unit is affected — cancelled dispositions never count as
    recovered." PRD §3.11: "otherwise `effectiveness_pct` is `recovered_unit_count`
    divided by `affected_unit_count`, multiplied by 100, rounded half-up to two
    decimal places."

    Design: Difficulty/compensating_invariant/cancel_return_restores_recovered_count_invariant
    """
    # Two affected units, both returned -> 100%; cancel one -> 50%.
    _p, _l, recall, units = setup_recall_with_recovery(
        num_units=2, num_returned=2,
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        sale_price_cents=5000,
    )
    before = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert before["recovered_unit_count"] == 2, before["recovered_unit_count"]
    assert before["effectiveness_pct"] == pytest.approx(100.00, abs=0.001), before["effectiveness_pct"]
    # Find the disposition for units[0] and cancel it.
    listing = api.list_dispositions(COORD, params={"recall_id": recall["id"], "unit_id": units[0]["id"]})
    disp_data, _meta = _list(listing)
    validate_success(api.cancel_disposition(disp_data[0]["id"], AGENT), 200)
    after = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert after["recovered_unit_count"] == 1, after["recovered_unit_count"]
    assert after["effectiveness_pct"] == pytest.approx(50.00, abs=0.001), after["effectiveness_pct"]


# ===========================================================================
# Corner: state_machines — invalid transitions, valid transitions, preconditions
# ===========================================================================
def test_classify_from_announced_returns_invalid_state(api):
    """PRD §3.3: "a `RecallCoordinator` classifies it, advancing it from `DRAFT`
    to `CLASSIFIED`." PRD §2.7: "The generic state check comes sixth: a
    transition attempted from a state that does not permit it yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/classify_from_announced_returns_invalid_state
    """
    _p, _l, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-sm-1",
        announcer_user_id="user-sm-2",
    )
    resp = api.classify_recall(recall["id"], make_headers("user-sm-1", "RecallCoordinator"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reclassify_clears_classification(api):
    """PRD §3.3: "A `RecallCoordinator` may reclassify a `CLASSIFIED` recall back
    to `DRAFT`". PRD §3.3: "Reclassification clears the derived `classification`,
    `notification_deadline_hours`, and `classified_by_user_id`".

    Design: Corner/state_machines/reclassify_loop_clears_classification
    """
    _p, _l, recall = setup_classified_recall(
        recall_overrides={"hazard_severity": "MINOR"}, classifier_user_id="user-rc-1"
    )
    data = validate_success(
        api.reclassify_recall(recall["id"], COORD, {"hazard_severity": "SERIOUS", "injury_reported": True}),
        200,
    )
    assert data["status"] == "DRAFT", data["status"]
    assert data["classification"] is None, data["classification"]


def test_terminate_from_announced_returns_invalid_state(api):
    """PRD §3.11: "The administrative close advances the recall from `MONITORING`
    to `TERMINATED`". PRD §2.7: "The generic state check comes sixth: a
    transition attempted from a state that does not permit it yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminate_from_announced_returns_invalid_state
    """
    _p, _l, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-tm-1",
        announcer_user_id="user-tm-2",
    )
    resp = api.terminate_recall(recall["id"], make_headers("user-tm-2", "QualityOfficer"), {"force_terminate": True})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminate_to_effective_without_final_report_returns_409(api):
    """PRD §3.11: "The successful close advances the recall from `MONITORING` to
    `EFFECTIVE`: it requires that the latest `EffectivenessCheck` for the recall
    has `outcome` of `PASS` ... and that a `FINAL` regulatory report for the
    recall is `SUBMITTED` or `ACKNOWLEDGED` (otherwise
    `ERR_FINAL_REPORT_REQUIRED`)."

    Design: Corner/state_machines/terminate_to_effective_requires_final_report
    """
    # CLASS_III recall, 1 of 1 returned -> 100% -> PASS check; no FINAL report.
    _p, _l, recall, _units = setup_recall_with_recovery(
        num_units=1,
        num_returned=1,
        recall_overrides={"hazard_severity": "MINOR"},
        sale_price_cents=5000,
    )
    from test_helpers import record_effectiveness_check
    check = record_effectiveness_check(recall["id"])
    assert check["outcome"] == "PASS", check["outcome"]
    resp = api.terminate_recall(recall["id"], make_headers("user-announcer-1", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_FINAL_REPORT_REQUIRED.value)


def test_lift_hold_while_announced_locked_by_recall(api):
    """PRD §3.7: "A `RecallCoordinator` may lift an `ACTIVE` hold, moving it to
    `LIFTED`, but only when the owning recall has progressed far enough — its
    status must be `MONITORING`, `EFFECTIVE`, or `TERMINATED`; an attempt while
    the recall is in any earlier state is rejected with
    `ERR_HOLD_LOCKED_BY_RECALL`."

    Design: Corner/state_machines/lift_hold_while_recall_announced_returns_409
    """
    _p, _l, recall = setup_classified_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-hl-1",
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-hl-2", "QualityOfficer")), 200
    )
    hold = get_first_quarantine_hold(recall["id"])
    resp = api.lift_hold(hold["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_HOLD_LOCKED_BY_RECALL.value)


def _list(response):
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]
