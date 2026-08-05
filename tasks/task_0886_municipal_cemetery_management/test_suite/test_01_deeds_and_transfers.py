"""Deed sale, care-fund contribution, transfer cycle, surrender cascade, OCC."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_right_holder_headers, TEST_USERS,
    create_deed_payload, create_holder_payload, create_plot_payload,
    setup_pending_deed, setup_issued_deed, setup_scheduled_interment,
    create_cemetery, create_holder, create_plot, pay_invoice,
    setup_approved_marker, get_cemetery_balance,
)

REG = TEST_USERS["registrar_headers"]
DIR = TEST_USERS["cemetery_director_headers"]


# ── Difficulty: dual_variant_calc / care_fund_new_sale_vs_resale_contribution ──

def test_new_sale_care_fund_contribution_floored_percentage(api):
    """PRD §3.2: "For a NEW_SALE, the contribution is the greater of the purchase
    price multiplied by 15% (0.15) and rounded half-up, or a statutory floor of
    25,000 cents ($250.00) — whichever is larger."

    Design: Difficulty/dual_variant_calc/care_fund_new_sale_vs_resale_contribution
    """
    r = setup_pending_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    assert r["deed"]["care_fund_contribution_cents"] == 150000


def test_resale_care_fund_contribution_lower_rate_no_floor(api):
    """PRD §3.2: "For a RESALE, the contribution is the purchase price multiplied by
    10% (0.10) and rounded half-up, with no statutory floor."

    Design: Difficulty/dual_variant_calc/care_fund_new_sale_vs_resale_contribution
    """
    r = setup_pending_deed(purchase_price_cents=1000000, sale_type="RESALE")
    assert r["deed"]["care_fund_contribution_cents"] == 100000


# ── Difficulty: non_linear_state_machine / deed_transfer_cycle_returns_to_issued ──

def test_accept_transfer_returns_deed_to_issued(api):
    """PRD §3.2: "On acceptance the deed moves TRANSFER_PENDING → ISSUED, holder_id
    is updated to the pending holder, and pending_new_holder_id is cleared."

    Design: Difficulty/non_linear_state_machine/deed_transfer_cycle_returns_to_issued
    """
    r = setup_issued_deed()
    holder2 = create_holder(full_name="Holder Two", email="h2@x.com", phone="2")
    validate_success(api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder2["id"]}, REG), 200)
    accepted = validate_success(
        api.accept_transfer(r["deed"]["id"], make_right_holder_headers(holder2["id"])), 200)
    assert accepted["status"] == "ISSUED"
    assert accepted.get("pending_new_holder_id") in (None, "")


def test_accept_transfer_rewrites_holder_id(api):
    """PRD §3.2: "On acceptance the deed moves TRANSFER_PENDING → ISSUED, holder_id
    is updated to the pending holder, and pending_new_holder_id is cleared."

    Design: Difficulty/non_linear_state_machine/deed_transfer_cycle_returns_to_issued
    """
    r = setup_issued_deed()
    holder2 = create_holder(full_name="Holder Two", email="h2@x.com", phone="2")
    validate_success(api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder2["id"]}, REG), 200)
    accepted = validate_success(
        api.accept_transfer(r["deed"]["id"], make_right_holder_headers(holder2["id"])), 200)
    assert accepted["holder_id"] == holder2["id"]


def test_issued_deed_can_be_transferred_again_after_cycle(api):
    """PRD §3.2: "Because acceptance returns the deed to ISSUED, a deed may be
    transferred repeatedly over its life."

    Design: Difficulty/non_linear_state_machine/deed_transfer_cycle_returns_to_issued
    """
    r = setup_issued_deed()
    holder2 = create_holder(full_name="Holder Two", email="h2@x.com", phone="2")
    holder3 = create_holder(full_name="Holder Three", email="h3@x.com", phone="3")
    validate_success(api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder2["id"]}, REG), 200)
    validate_success(api.accept_transfer(r["deed"]["id"], make_right_holder_headers(holder2["id"])), 200)
    # Second cycle: now-ISSUED deed transferred to holder3
    validate_success(api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder3["id"]}, REG), 200)
    accepted = validate_success(
        api.accept_transfer(r["deed"]["id"], make_right_holder_headers(holder3["id"])), 200)
    assert accepted["status"] == "ISSUED"
    assert accepted["holder_id"] == holder3["id"]


# ── Difficulty: transitive_cascade / payment_activates_deed_and_posts_contribution ──

def test_deed_sale_payment_issues_deed_and_sells_plot(api):
    """PRD §3.7: "a paid DEED_SALE issues the deed (PENDING_PAYMENT → ISSUED),
    advances the plot to SOLD, and posts the CONTRIBUTION care-fund entry"

    Design: Difficulty/transitive_cascade/payment_activates_deed_and_posts_contribution
    """
    r = setup_pending_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    pay_invoice(r["sale_invoice_id"])
    invoice = validate_success(api.get_invoice(r["sale_invoice_id"], DIR), 200)
    assert invoice["status"] == "PAID"
    deed = validate_success(api.get_deed(r["deed"]["id"], REG), 200)
    assert deed["status"] == "ISSUED"
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["status"] == "SOLD"


def test_deed_sale_payment_posts_care_fund_contribution(api):
    """PRD §3.2: "a CONTRIBUTION care-fund entry equal to the deed's pinned
    care_fund_contribution_cents is posted with its source_deed_id set to the deed."

    Design: Difficulty/transitive_cascade/payment_activates_deed_and_posts_contribution
    """
    r = setup_pending_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    assert get_cemetery_balance(r["cemetery"]["id"]) == 0
    pay_invoice(r["sale_invoice_id"])
    assert get_cemetery_balance(r["cemetery"]["id"]) == 150000


# ── Difficulty: transitive_cascade / deed_surrender_reclaims_plot_and_cancels_marker ──

def test_surrender_moves_deed_to_surrendered(api):
    """PRD §3.2: "Surrendering an ISSUED deed (whose plot is SOLD) moves the deed to
    the terminal SURRENDERED, returns the plot to AVAILABLE, cancels any non-terminal
    marker permits on the plot (those in APPLIED or APPROVED move to CANCELLED)"

    Design: Difficulty/transitive_cascade/deed_surrender_reclaims_plot_and_cancels_marker
    """
    r = setup_approved_marker()
    deed = validate_success(api.surrender_deed(r["deed"]["id"], REG), 200)
    assert deed["status"] == "SURRENDERED"


def test_surrender_reclaims_plot_to_available(api):
    """PRD §3.2: "Surrendering an ISSUED deed (whose plot is SOLD) moves the deed to
    the terminal SURRENDERED, returns the plot to AVAILABLE, cancels any non-terminal
    marker permits on the plot (those in APPLIED or APPROVED move to CANCELLED)"

    Design: Difficulty/transitive_cascade/deed_surrender_reclaims_plot_and_cancels_marker
    """
    r = setup_approved_marker(pay_foundation=False)
    validate_success(api.surrender_deed(r["deed"]["id"], REG), 200)
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["status"] == "AVAILABLE"


def test_surrender_cascades_marker_permit_to_cancelled(api):
    """PRD §3.5: "When a plot is reclaimed by a deed surrender, its non-terminal
    permits — those in APPLIED or APPROVED — move to CANCELLED, and any still-unpaid
    MARKER_FOUNDATION invoice is voided."

    Design: Difficulty/transitive_cascade/deed_surrender_reclaims_plot_and_cancels_marker
    """
    r = setup_approved_marker(pay_foundation=False)
    validate_success(api.surrender_deed(r["deed"]["id"], REG), 200)
    permit = validate_success(api.get_marker_permit(r["permit"]["id"], REG), 200)
    assert permit["status"] == "CANCELLED"


# ── Corner: cross_cutting / occ_stale_plot_version_on_second_deed ──

def test_second_deed_with_stale_plot_version_rejected(api):
    """PRD §2.4: "if another writer has advanced the plot's version since the client
    last read it — for example by already creating a deed that legitimately reserves
    the plot — the create is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting/occ_stale_plot_version_on_second_deed
    """
    cem = create_cemetery()
    holder = create_holder()
    plot = create_plot(cem["id"])
    stale_version = plot["version"]
    validate_success(api.create_deed(
        create_deed_payload(plot["id"], holder["id"], stale_version), REG), 201)
    res = api.create_deed(
        create_deed_payload(plot["id"], holder["id"], stale_version,
                            purchase_price_cents=900000), REG)
    validate_error(res, "ERR_STALE_VERSION")


# ── Corner: errors / transfer_to_unknown_holder_not_found ──

def test_transfer_to_unknown_holder_not_found(api):
    """PRD §3.2: "The proposed holder must reference an existing RightHolder —
    otherwise ERR_HOLDER_NOT_FOUND — and must differ from the current holder_id."

    Design: Corner/errors/transfer_to_unknown_holder_not_found
    """
    r = setup_issued_deed()
    res = api.transfer_deed(
        r["deed"]["id"], {"new_holder_id": "00000000-0000-4000-8000-0000000000ff"}, REG)
    validate_error(res, "ERR_HOLDER_NOT_FOUND")


# ── Corner: errors / accept_transfer_wrong_holder_not_pending ──

def test_accept_transfer_by_wrong_holder_rejected(api):
    """PRD §3.2: "the acting RightHolder's X-User-ID must equal the deed's
    pending_new_holder_id, otherwise the acceptance is rejected with
    ERR_NOT_PENDING_HOLDER."

    Design: Corner/errors/accept_transfer_wrong_holder_not_pending
    """
    r = setup_issued_deed()
    holder2 = create_holder(full_name="H Two", email="h2@x.com", phone="2")
    holder3 = create_holder(full_name="H Three", email="h3@x.com", phone="3")
    validate_success(api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder2["id"]}, REG), 200)
    res = api.accept_transfer(r["deed"]["id"], make_right_holder_headers(holder3["id"]))
    validate_error(res, "ERR_NOT_PENDING_HOLDER")


# ── Corner: state_machines / transfer_surrendered_deed_terminal_lockdown ──

def test_transfer_surrendered_deed_invalid_state(api):
    """PRD §3.2: "Surrendering an ISSUED deed (whose plot is SOLD) moves the deed to
    the terminal SURRENDERED"

    Design: Corner/state_machines/transfer_surrendered_deed_terminal_lockdown
    """
    r = setup_issued_deed()
    holder2 = create_holder(full_name="H Two", email="h2@x.com", phone="2")
    validate_success(api.surrender_deed(r["deed"]["id"], REG), 200)
    res = api.transfer_deed(r["deed"]["id"], {"new_holder_id": holder2["id"]}, REG)
    validate_error(res, "ERR_INVALID_STATE")


# ── Corner: state_machines / surrender_deed_with_active_interment_occupied ──

def test_surrender_deed_with_active_interment_rejected(api):
    """PRD §3.2: "Surrender is only permitted when the plot has no interment in
    SCHEDULED, OPENED, or COMPLETED status; an attempt while such an active interment
    exists is rejected with ERR_PLOT_OCCUPIED."

    Design: Corner/state_machines/surrender_deed_with_active_interment_occupied
    """
    r = setup_scheduled_interment()
    res = api.surrender_deed(r["deed"]["id"], REG)
    validate_error(res, "ERR_PLOT_OCCUPIED")
