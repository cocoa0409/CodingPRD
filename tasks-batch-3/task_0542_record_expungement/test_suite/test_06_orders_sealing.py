"""Court orders and sealing distributions: the grant cascade, the FAILED->QUEUED retry
loop and its cap, vendor acknowledgement, and vacatur compensation."""
from test_helpers import fixtures, validate_success, validate_error, validate_paginated, ApiErrorId

CLERK = fixtures.CLERK
JUDGE = fixtures.JUDGE


def _distros(api, order_id, recipient_type=None):
    params = {"court_order_id": order_id}
    if recipient_type is not None:
        params["recipient_type"] = recipient_type
    return validate_paginated(api.list_sealing_distributions(CLERK, params=params))


# ---- grant_order_seals_records_queues_distributions (Difficulty) ----------
def test_granted_order_grants_petition_and_seals_record(api):
    """PRD §3.8: "A `GRANTED` order drives the signature cascade of the whole system.
    First, the petition moves from `HEARING_SET` to `GRANTED`. Second, every item of
    that petition whose `eligibility_at_screening` is `ELIGIBLE` has its underlying
    criminal record moved from `ELIGIBLE` to `SEALED`."

    Design: Difficulty/transitive_cascade/grant_order_seals_records_queues_distributions
    """
    ctx = fixtures.setup_granted_order(api)
    petition = validate_success(api.get_petition(ctx["petition"]["id"], CLERK))
    record = validate_success(api.get_criminal_record(ctx["record"]["id"], CLERK))
    assert petition["status"] == "GRANTED"
    assert record["status"] == "SEALED"


def test_granted_order_queues_three_agency_distributions(api):
    """PRD §3.8: "Third, each newly sealed record fans out a set of
    `SealingDistribution` rows attached to the order: one row for each agency
    recipient — `DA`, `ARRESTING_AGENCY`, and `STATE_REPOSITORY` — plus one row for
    each registered `BackgroundVendor`, every row created in the `QUEUED` state."

    Design: Difficulty/transitive_cascade/grant_order_seals_records_queues_distributions
    """
    ctx = fixtures.setup_granted_order(api, with_vendor=False)
    distros, meta = _distros(api, ctx["court_order"]["id"])
    assert meta["total_count"] == 3, "no vendor registered -> exactly the 3 agency rows"
    assert all(d["status"] == "QUEUED" for d in distros)


# ---- sealing_distribution_failed_retry_cycle (Difficulty) -----------------
def test_distribution_failed_then_requeued_increments_attempt_count(api):
    """PRD §3.9: "Alternatively, a sent distribution that fails to deliver is moved
    to `FAILED`. A failed distribution may be retried, moving it back to `QUEUED`,
    but only while its `attempt_count` is below the maximum of 2 retries; each retry
    increments `attempt_count` by one."

    Design: Difficulty/non_linear_state_machine/sealing_distribution_failed_retry_cycle
    """
    ctx = fixtures.setup_granted_order(api)
    d = ctx["distributions"][0]["id"]
    validate_success(api.transition_sealing_distribution(d, {"to_status": "SENT"}, CLERK))
    validate_success(api.transition_sealing_distribution(d, {"to_status": "FAILED"}, CLERK))
    requeued = validate_success(api.transition_sealing_distribution(d, {"to_status": "QUEUED"}, CLERK))
    assert requeued["status"] == "QUEUED"
    assert requeued["attempt_count"] == 1


def test_distribution_second_retry_increments_attempt_count_to_two(api):
    """PRD §3.9: "A failed distribution may be retried, moving it back to `QUEUED`,
    but only while its `attempt_count` is below the maximum of 2 retries; each retry
    increments `attempt_count` by one."

    Design: Difficulty/non_linear_state_machine/sealing_distribution_failed_retry_cycle
    """
    ctx = fixtures.setup_granted_order(api)
    d = ctx["distributions"][0]["id"]
    for _ in range(2):
        validate_success(api.transition_sealing_distribution(d, {"to_status": "SENT"}, CLERK))
        validate_success(api.transition_sealing_distribution(d, {"to_status": "FAILED"}, CLERK))
        requeued = validate_success(api.transition_sealing_distribution(d, {"to_status": "QUEUED"}, CLERK))
    assert requeued["attempt_count"] == 2


# ---- vacate_unseals_record_count (Difficulty) -----------------------------
def test_vacate_granted_order_unseals_record(api):
    """PRD §3.8: "Either way, vacatur is a compensation: every record of the order's
    petition that is currently `SEALED` is moved back to `ELIGIBLE` (unsealed),
    restoring the conservation invariant that a vacated grant leaves no record
    sealed."

    Design: Difficulty/compensating_invariant/vacate_unseals_record_count
    """
    ctx = fixtures.setup_granted_order(api)
    order = validate_success(api.vacate_court_order(ctx["court_order"]["id"], JUDGE))
    assert order["status"] == "VACATED"
    record = validate_success(api.get_criminal_record(ctx["record"]["id"], CLERK))
    assert record["status"] == "ELIGIBLE"


def test_vacate_entered_order_cancels_distributions(api):
    """PRD §3.8: "When vacating an order still in `ENTERED`, every non-terminal
    `SealingDistribution` of the order — those not already acknowledged or cancelled —
    is moved to `CANCELLED`."

    Design: Difficulty/compensating_invariant/vacate_unseals_record_count
    """
    ctx = fixtures.setup_granted_order(api)  # order ENTERED, distributions QUEUED (non-terminal)
    validate_success(api.vacate_court_order(ctx["court_order"]["id"], JUDGE))
    distros, _meta = _distros(api, ctx["court_order"]["id"])
    assert distros, "order should still have its distribution rows"
    assert all(d["status"] == "CANCELLED" for d in distros)


# ---- Corner: retry cap & vendor acknowledgement ---------------------------
def test_distribution_retry_past_cap_rejected(api):
    """PRD §3.9: "A retry attempted when `attempt_count` has already reached 2 is
    rejected with `ERR_MAX_RETRIES_EXCEEDED` (409)."

    Design: Corner/state_machines/distribution_retry_cap_max_attempts_exceeded
    """
    ctx = fixtures.setup_granted_order(api)
    d = ctx["distributions"][0]["id"]
    for _ in range(2):  # two successful retries -> attempt_count == 2
        validate_success(api.transition_sealing_distribution(d, {"to_status": "SENT"}, CLERK))
        validate_success(api.transition_sealing_distribution(d, {"to_status": "FAILED"}, CLERK))
        validate_success(api.transition_sealing_distribution(d, {"to_status": "QUEUED"}, CLERK))
    current = validate_success(api.get_sealing_distribution(d, CLERK))
    assert current["attempt_count"] == 2
    validate_success(api.transition_sealing_distribution(d, {"to_status": "SENT"}, CLERK))
    validate_success(api.transition_sealing_distribution(d, {"to_status": "FAILED"}, CLERK))
    resp = api.transition_sealing_distribution(d, {"to_status": "QUEUED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_MAX_RETRIES_EXCEEDED.value)


def test_vendor_acknowledgement_increments_records_updated_count(api):
    """PRD §3.9: "A sent distribution may be acknowledged, moving it to
    `ACKNOWLEDGED`; when the acknowledged distribution's `recipient_type` is
    `BACKGROUND_VENDOR`, the `BackgroundVendor` identified by the distribution's
    `recipient_ref` has its `records_updated_count` incremented by one."

    Design: Corner/cross_cutting_complexity_layers/background_vendor_ack_increments_counter
    """
    ctx = fixtures.setup_granted_order(api, with_vendor=True)
    vendor_distros, _meta = _distros(api, ctx["court_order"]["id"], recipient_type="BACKGROUND_VENDOR")
    assert len(vendor_distros) == 1
    vd = vendor_distros[0]["id"]
    validate_success(api.transition_sealing_distribution(vd, {"to_status": "SENT"}, CLERK))
    validate_success(api.transition_sealing_distribution(vd, {"to_status": "ACKNOWLEDGED"}, CLERK))
    vendor = validate_success(api.get_background_vendor(ctx["vendor"]["id"], CLERK))
    assert vendor["records_updated_count"] == 1
