"""Cross-cutting layers: optimistic concurrency on refund-open, scheduled
retainer actions, and immediate ledger consistency (PRD §2.7, §2.8, §3.10, §3.11)."""
from test_helpers import (
    validate_success, validate_error,
    setup_case_active, setup_plan_approved, create_financing,
    setup_active_retainer,
    create_refund_payload,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_second_refund_open_with_stale_case_version_rejected(api):
    """PRD §2.7: "Opening a refund request requires the field
    `expected_case_version`, carrying the client's last observed `version` of the
    target `TreatmentCase`. If that value does not match the case's current
    `version`, the open is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."
    PRD §3.11: "Opening a refund increments the case's `version` by one."

    After one refund-open bumps the case version, a second open reusing the
    pre-bump version is stale and rejected with ERR_STALE_CASE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_refund_open
    """
    ctx = setup_case_active(proposed_step_count=10, list_price_cents=375000,
                            down_payment_cents=300000)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    observed_version = case["version"]
    # First open succeeds and bumps the version.
    validate_success(
        api.create_refund(
            create_refund_payload(ctx["case"]["id"], observed_version, reason="GOODWILL"),
            BILLING,
        ),
        201,
    )
    # Second open with the now-stale version is rejected.
    res = api.create_refund(
        create_refund_payload(ctx["case"]["id"], observed_version, reason="PATIENT_CANCEL"),
        BILLING,
    )
    validate_error(res, "ERR_STALE_CASE_VERSION", expected_status=412)


def test_refund_open_increments_case_version(api):
    """PRD §3.11: "Opening a refund increments the case's `version` by one."
    PRD §3.11: "A refund begins in `OPEN`".

    POST /refunds with the observed version succeeds (201, OPEN) and the case's
    version increments by exactly one, so the same expected_case_version cannot
    be reused.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_refund_open
    """
    ctx = setup_case_active(proposed_step_count=10, list_price_cents=375000,
                            down_payment_cents=300000)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    observed_version = case["version"]
    refund = validate_success(
        api.create_refund(
            create_refund_payload(ctx["case"]["id"], observed_version, reason="GOODWILL"),
            BILLING,
        ),
        201,
    )
    assert refund["status"] == "OPEN", refund["status"]
    after = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert after["version"] == observed_version + 1, after["version"]


def test_resume_paused_retainer_returns_to_active(api):
    """PRD §3.10: "The patient may pause it (from `ACTIVE` to `PAUSED`), resume
    it (from `PAUSED` back to `ACTIVE`, which advances `next_ship_at` by one
    cadence interval from the current clock)".

    Resuming a PAUSED retainer returns its status to ACTIVE.

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_retainer_next_ship_advances_on_resume
    """
    ctx = setup_active_retainer(cadence="QUARTERLY", per_shipment_fee_cents=5000)
    ret_id = ctx["retainer"]["id"]
    validate_success(api.pause_retainer(ret_id, ctx["pat_headers"]), 200)
    resumed = validate_success(api.resume_retainer(ret_id, ctx["pat_headers"]), 200)
    assert resumed["status"] == "ACTIVE", resumed["status"]


def test_financing_activation_ledger_visible_in_same_read(api):
    """PRD §2.8: "the same holds for every secondary resource a cascade touches.
    The ledger fields on a case (`amount_collected_cents` ...) are maintained by
    these side effects".
    PRD §3.7: "posts the down payment by adding `down_payment_cents` to the
    case's `amount_collected_cents`".
    PRD §1 (intro): "every state change must settle its downstream consequences -
    ledger debits, case posture, shipment status - atomically within the request
    that triggered it".

    Immediately after financing activation (down 300000), a synchronous GET
    /cases/{id} reflects amount_collected_cents=300000 with no eventual lag.

    Design: Corner/consistency_model/immediate_ledger_visible_in_same_response
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    fin = create_financing(ctx["case"]["id"], term_months=12,
                          down_payment_cents=300000, apr_bps=0)
    validate_success(
        api.activate_financing_plan(
            fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
        ),
        200,
    )
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["amount_collected_cents"] == 300000, case["amount_collected_cents"]
