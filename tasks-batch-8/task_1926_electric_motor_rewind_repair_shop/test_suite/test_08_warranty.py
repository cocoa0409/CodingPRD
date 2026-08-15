"""Warranty claim adjudication and remedies (PRD §3.7): close gating, the
prorated-credit cascade into the payment waterfall, the approval window edge,
covered-mode exclusions, and the free-rewind resolution loop."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    approve_claim,
    create_claim_approval_payload,
    deliver_work_order,
    deny_claim,
    diagnose_work_order,
    file_warranty_claim,
    get_customer,
    get_single_invoice,
    get_work_order,
    intake_work_order,
    issue_quote,
    make_customer_headers,
    record_coil_data,
    record_final_test,
    record_incoming_test,
    record_payment,
    release_work_order,
    send_quote,
    set_clock,
    setup_delivered_work_order,
    start_rewind,
    start_review_claim,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]


def _delivered_with_claim(api, failure_mode="BEARING_FAILURE"):
    bundle = setup_delivered_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    claim = file_warranty_claim(
        bundle["shop"]["id"], bundle["work_order"]["id"], bundle["customer"]["id"], failure_mode
    )
    return bundle, claim


# ─── Close blocked by open claim (Difficulty/cross_entity_state_dependency) ───

def test_close_rejected_while_warranty_claim_filed(api):
    """PRD §3.5: "Close is blocked with `ERR_CLAIMS_OPEN` (HTTP 409) while any
    warranty claim on the order sits in `FILED`, `UNDER_REVIEW`, or
    `APPROVED`, or while any pool loan for the order has yet to be returned."

    Design: Difficulty/cross_entity_state_dependency/work_order_close_blocked_by_open_warranty_claim
    """
    bundle, claim = _delivered_with_claim(api)
    assert claim["status"] == "FILED"
    res = api.close_work_order(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER)
    validate_error(res, "ERR_CLAIMS_OPEN", expected_status=409)


def test_close_succeeds_after_claim_denied(api):
    """PRD §3.7: "Denial needs no further ceremony and moves the claim to the
    terminal `DENIED`."
    PRD §3.5: "A successful close stamps `closed_at` and moves the order to
    the terminal `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/work_order_close_blocked_by_open_warranty_claim
    """
    bundle, claim = _delivered_with_claim(api)
    res = api.close_work_order(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER)
    validate_error(res, "ERR_CLAIMS_OPEN", expected_status=409)

    start_review_claim(bundle["shop"]["id"], claim["id"])  # FILED -> UNDER_REVIEW
    denied = deny_claim(bundle["shop"]["id"], claim["id"])
    assert denied["status"] == "DENIED"

    closed = validate_success(
        api.close_work_order(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER), 200
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None


# ─── Prorated credit cascade (Difficulty/transitive_cascade) ───

def _approved_credit_setup(api):
    """Delivered work order (invoice 187900c) with a claim filed five whole
    months after delivery and approved for prorated credit."""
    bundle = setup_delivered_work_order(
        rewind_hours=12, materials_cents=38000, replacement_cost_cents=9999999,
        core_loss_watts=3200,
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2020},
    )
    shop, customer = bundle["shop"], bundle["customer"]
    assert bundle["invoice"]["total_cents"] == 187900

    set_clock("2027-01-15T00:00:00Z")
    claim = file_warranty_claim(shop["id"], bundle["work_order"]["id"], customer["id"], "WINDING_SHORT")
    start_review_claim(shop["id"], claim["id"])
    return bundle, claim


def test_prorated_credit_approval_posts_credit_and_resolves(api):
    """PRD §3.7: "A `PRORATED_CREDIT` computes `credit_cents` as the work
    order's `invoice_total_cents` multiplied by the remaining covered months —
    `warranty_months` minus `months_elapsed`, never below zero — and divided
    by `warranty_months`, rounded half-up to integer cents."
    PRD §3.7: "The credit posts immediately into the customer's
    `account_credit_cents`, and the claim moves straight to `RESOLVED` on
    posting."

    Design: Difficulty/transitive_cascade/claim_approval_credits_customer_and_credit_offsets_next_payment
    """
    bundle, claim = _approved_credit_setup(api)
    approved = approve_claim(bundle["shop"]["id"], claim["id"], "PRORATED_CREDIT")
    # round_half_up(187900 * (12 - 5) / 12) = 109608.
    assert approved["months_elapsed"] == 5
    assert approved["credit_cents"] == 109608
    assert approved["status"] == "RESOLVED"

    customer = get_customer(bundle["shop"]["id"], bundle["customer"]["id"])
    assert customer["account_credit_cents"] == 109608


def test_payment_after_credit_leaves_credit_bucket_intact(api):
    """PRD §3.5: "Each invoice in turn absorbs the smaller of the remaining
    payment and its own `balance_due_cents`, growing `amount_paid_cents` and
    shrinking `balance_due_cents` by the applied amount".
    PRD §3.5: "Any unapplied remainder lands in the customer's
    `account_credit_cents`."

    Design: Difficulty/transitive_cascade/claim_approval_credits_customer_and_credit_offsets_next_payment
    """
    bundle, claim = _approved_credit_setup(api)
    approve_claim(bundle["shop"]["id"], claim["id"], "PRORATED_CREDIT")

    result = record_payment(bundle["shop"]["id"], bundle["customer"]["id"], 50000)
    assert result["applied"][0]["invoice_id"] == bundle["invoice"]["id"]
    assert result["applied"][0]["applied_cents"] == 50000
    assert result["credit_added_cents"] == 0

    invoice = validate_success(
        api.get_invoice(bundle["shop"]["id"], bundle["invoice"]["id"], MANAGER), 200
    )
    assert invoice["balance_due_cents"] == 137900

    customer = get_customer(bundle["shop"]["id"], bundle["customer"]["id"])
    assert customer["account_credit_cents"] == 109608


# ─── Window edge (Corner/validations) ───

def test_warranty_approval_at_window_edge_rejected(api):
    """PRD §3.7: "the claim must still be in window: `months_elapsed` strictly
    less than the shop's `warranty_months` — a claim whose elapsed months
    equal the warranty window is already out of it and is rejected with
    `ERR_WARRANTY_OUT_OF_WINDOW` (HTTP 422)."
    PRD §3.7: "Filing stamps `filed_at` with the server timestamp, computes
    `months_elapsed` as the whole months between `delivered_at` and `filed_at`
    floored".

    Design: Corner/validations/warranty_approval_at_window_edge_rejected
    """
    bundle = setup_delivered_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    shop, customer = bundle["shop"], bundle["customer"]
    set_clock("2027-08-01T00:00:00Z")  # exactly twelve months after delivery

    claim = file_warranty_claim(shop["id"], bundle["work_order"]["id"], customer["id"], "WINDING_SHORT")
    assert claim["months_elapsed"] == 12
    start_review_claim(shop["id"], claim["id"])

    res = api.approve_claim(shop["id"], claim["id"], create_claim_approval_payload("PRORATED_CREDIT"), MANAGER)
    validate_error(res, "ERR_WARRANTY_OUT_OF_WINDOW", expected_status=422)


# ─── Excluded failure mode (Corner/validations) ───

def test_warranty_excluded_failure_mode_rejected(api):
    """PRD §3.7: "`WINDING_SHORT`, `GROUND_FAULT`, and `BEARING_FAILURE` are
    the covered set, while `OVERLOAD`, `INGRESS`, `MISAPPLICATION`, and
    `UNAUTHORIZED_REPAIR` are exclusions rejected with
    `ERR_WARRANTY_EXCLUDED_MODE` (HTTP 422)."

    Design: Corner/validations/warranty_excluded_failure_mode_rejected
    """
    bundle, claim = _delivered_with_claim(api, failure_mode="OVERLOAD")
    start_review_claim(bundle["shop"]["id"], claim["id"])

    res = api.approve_claim(
        bundle["shop"]["id"], claim["id"], create_claim_approval_payload("FREE_REWIND"), MANAGER
    )
    validate_error(res, "ERR_WARRANTY_EXCLUDED_MODE", expected_status=422)


# ─── Free-rewind resolution loop (Corner/state_machines) ───

def test_warranty_claim_resolve_waits_for_free_rewind_delivery(api):
    """PRD §3.7: "A `FREE_REWIND` instead creates a brand-new work order for
    the same motor and customer with `priority` forced to `STANDARD` and
    `no_charge` set — guaranteeing its invoice totals zero at release —
    records it as the claim's `resolution_work_order_id`, and pulls the
    motor's custody back to `IN_SHOP` for the resolution intake. The claim
    then waits in `APPROVED` until the resolution work order reaches
    `DELIVERED`, at which point the system moves the claim to `RESOLVED`."

    Design: Corner/state_machines/warranty_claim_resolve_waits_for_free_rewind_delivery
    """
    bundle = setup_delivered_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    shop, customer = bundle["shop"], bundle["customer"]
    claim = file_warranty_claim(shop["id"], bundle["work_order"]["id"], customer["id"], "GROUND_FAULT")
    start_review_claim(shop["id"], claim["id"])

    approved = approve_claim(shop["id"], claim["id"], "FREE_REWIND")
    assert approved["status"] == "APPROVED"  # waits for the resolution delivery
    resolution_id = approved["resolution_work_order_id"]
    assert resolution_id

    resolution = get_work_order(shop["id"], resolution_id)
    assert resolution["no_charge"] is True
    assert resolution["priority"] == "STANDARD"
    assert resolution["motor_id"] == bundle["motor"]["id"]
    assert resolution["customer_id"] == customer["id"]

    # Drive the resolution order through the full pipeline.
    record_incoming_test(shop["id"], resolution_id)
    diagnose_work_order(shop["id"], resolution_id)
    quote = issue_quote(shop["id"], resolution_id)
    send_quote(shop["id"], resolution_id, quote["id"])
    accept_quote(shop["id"], resolution_id, quote["id"], customer["id"])
    start_rewind(shop["id"], resolution_id)
    record_coil_data(shop["id"], resolution_id)
    record_final_test(shop["id"], resolution_id, 2.0)
    released = release_work_order(shop["id"], resolution_id)
    assert released["invoice_total_cents"] == 0  # no-charge resolution order
    resolution_invoice = get_single_invoice(shop["id"], resolution_id)
    assert resolution_invoice["total_cents"] == 0

    deliver_work_order(shop["id"], resolution_id)

    resolved = validate_success(api.get_warranty_claim(shop["id"], claim["id"], MANAGER), 200)
    assert resolved["status"] == "RESOLVED"
