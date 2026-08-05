"""Acceptance/fallout cascades, the guarantee window, guarantee credits, and the
conserved-quantity ledgers (money and headcount)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_open_opening, setup_placement_pre_start, setup_placement_active,
    setup_placement_invoiced,
    create_account_manager, create_recruiter, create_coordinator,
    create_client_entity, create_opening, publish_opening,
    create_candidate_entity, create_application_entity,
    screen_application, submit_application, advance_to_interview,
    create_site_visit_entity, complete_site_visit,
    create_offer_entity, accept_offer,
    get_placement_for_offer, get_cfile_for_placement, clear_credentialing,
    set_clock, onboard_placement, invoice_placement,
    file_claim, approve_claim, resolve_refund, resolve_replacement,
    make_account_manager_headers,
)


# --------------------------------------------------------------------------
# accept -> fill -> reject sibling -> rescind sibling offer (depth-4 cascade)
# --------------------------------------------------------------------------
def _two_extended_offers_one_position(api):
    ctx = setup_open_opening(positions_total=1)
    # Application A
    cand_a = create_candidate_entity(ctx["rec_id"], full_name="Dr A")
    app_a = create_application_entity(ctx["rec_id"], cand_a["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app_a["id"])
    submit_application(ctx["rec_id"], app_a["id"])
    advance_to_interview(ctx["client_id"], app_a["id"])
    sv_a = create_site_visit_entity(
        ctx["rec_id"], app_a["id"], ctx["rec_id"],
        scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
    )
    complete_site_visit(ctx["rec_id"], sv_a["id"])
    offer_a = create_offer_entity(ctx["am_id"], app_a["id"], sign_on_bonus_cents=2_500_000)
    # Application B
    cand_b = create_candidate_entity(ctx["rec_id"], full_name="Dr B")
    app_b = create_application_entity(ctx["rec_id"], cand_b["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app_b["id"])
    submit_application(ctx["rec_id"], app_b["id"])
    advance_to_interview(ctx["client_id"], app_b["id"])
    sv_b = create_site_visit_entity(
        ctx["rec_id"], app_b["id"], ctx["rec_id"],
        scheduled_start="2026-05-04T15:00:00Z", scheduled_end="2026-05-04T16:00:00Z",
    )
    complete_site_visit(ctx["rec_id"], sv_b["id"])
    offer_b = create_offer_entity(
        ctx["am_id"], app_b["id"], base_salary_cents=25_000_000, sign_on_bonus_cents=1_000_000
    )
    return ctx, app_a, offer_a, app_b, offer_b


def test_accept_fills_single_position_opening(api):
    """PRD §3.6: "the opening's positions_filled is increased by one; if that
    increase makes positions_filled equal positions_total, the opening moves
    OPEN → FILLED".

    Design: Difficulty/transitive_cascade/accept_fills_opening_rejects_sibling_and_rescinds_offer
    """
    ctx, app_a, offer_a, app_b, offer_b = _two_extended_offers_one_position(api)
    accept_offer(ctx["rec_id"], offer_a["id"])
    opening = validate_success(
        api.get_job_opening(ctx["opening_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert opening["status"] == "FILLED"
    assert opening["positions_filled"] == 1


def test_fill_rejects_sibling_application_and_rescinds_its_offer(api):
    """PRD §3.6: "all still-live applications on the opening are rejected with
    reject_reason OPENING_FILLED, and their EXTENDED or COUNTERED offers are
    rescinded."

    Design: Difficulty/transitive_cascade/accept_fills_opening_rejects_sibling_and_rescinds_offer
    """
    ctx, app_a, offer_a, app_b, offer_b = _two_extended_offers_one_position(api)
    accept_offer(ctx["rec_id"], offer_a["id"])
    got_app_b = validate_success(
        api.get_application(app_b["id"], make_account_manager_headers(ctx["am_id"]))
    )
    got_offer_b = validate_success(
        api.get_offer(offer_b["id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert got_app_b["stage"] == "REJECTED"
    assert got_app_b["reject_reason"] == "OPENING_FILLED"
    assert got_offer_b["status"] == "RESCINDED"


# --------------------------------------------------------------------------
# claim approve -> fell out -> reopen opening (depth-2+ cascade)
# --------------------------------------------------------------------------
def test_claim_approve_fells_out_placement_and_credits_fee(api):
    """PRD §3.9: "the placement moves ACTIVE → FELL_OUT, its fee_status becomes
    CREDITED, and the opening's positions_filled is decremented by one".

    Design: Difficulty/transitive_cascade/claim_approve_fells_out_and_reopens_opening
    """
    ctx = setup_placement_active()
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-07-01T00:00:00Z")
    approve_claim(ctx["am_id"], claim["id"])
    placement = validate_success(
        api.get_placement(ctx["placement_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert placement["placement_status"] == "FELL_OUT"
    assert placement["fee_status"] == "CREDITED"


def test_claim_approve_reopens_filled_opening(api):
    """PRD §3.9: "the opening's positions_filled is decremented by one, reopening a
    FILLED opening to OPEN if the count now falls below positions_total."

    Design: Difficulty/transitive_cascade/claim_approve_fells_out_and_reopens_opening
    """
    ctx = setup_placement_active()
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-07-01T00:00:00Z")
    approve_claim(ctx["am_id"], claim["id"])
    opening = validate_success(
        api.get_job_opening(ctx["opening_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert opening["status"] == "OPEN"
    assert opening["positions_filled"] == 0


# --------------------------------------------------------------------------
# guarantee window inclusive-end boundary
# --------------------------------------------------------------------------
def test_claim_on_guarantee_end_date_is_inside_window(api):
    """PRD §3.9: "the fell_out_date must be on or before the placement's
    guarantee_end_date — the boundary is inclusive — otherwise the claim is rejected
    with ERR_GUARANTEE_WINDOW_EXPIRED."

    Design: Difficulty/boundary_precision_check/guarantee_window_inclusive_end_date
    """
    ctx = setup_placement_active()  # start 2026-06-01, guarantee_end 2026-08-30 (90 days)
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-08-30T00:00:00Z")
    approved = approve_claim(ctx["am_id"], claim["id"])
    assert approved["status"] == "APPROVED"
    assert approved["days_worked"] == 90


def test_claim_one_day_past_guarantee_end_rejected(api):
    """PRD §3.9: "the fell_out_date must be on or before the placement's
    guarantee_end_date — the boundary is inclusive — otherwise the claim is rejected
    with ERR_GUARANTEE_WINDOW_EXPIRED."

    Design: Difficulty/boundary_precision_check/guarantee_window_inclusive_end_date
    """
    ctx = setup_placement_active()
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-08-31T00:00:00Z")
    resp = api.transition_guarantee_claim(
        claim["id"], {"action": "APPROVE"}, make_account_manager_headers(ctx["am_id"])
    )
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_WINDOW_EXPIRED.value)


# --------------------------------------------------------------------------
# guarantee credit: refund (pro-rata) vs replacement (capped full fee)
# --------------------------------------------------------------------------
def _refund_claim_ctx(api):
    ctx = setup_placement_invoiced(final_first_year_comp_cents=25_000_000, is_hard_to_fill=True)
    # placement_fee_cents = 25,000,000 x0.20 x1.20 = 6,000,000
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-07-01T00:00:00Z")
    approve_claim(ctx["am_id"], claim["id"])
    ctx["claim_id"] = claim["id"]
    return ctx


def test_guarantee_refund_days_worked_and_status(api):
    """PRD §3.9: "its days_worked is computed as the whole-day count from the
    placement's start_date to the fell_out_date, floored to a whole number of days."
    PRD §3.9: "A refund resolution (APPROVED → RESOLVED_REFUND) returns cash pro-rata
    to the unworked portion of the guarantee."

    Design: Difficulty/dual_variant_calc/guarantee_credit_refund_prorated
    """
    ctx = _refund_claim_ctx(api)
    resolved = resolve_refund(ctx["am_id"], ctx["claim_id"])
    assert resolved["status"] == "RESOLVED_REFUND"
    assert resolved["days_worked"] == 30


def test_guarantee_refund_credit_is_prorated(api):
    """PRD §3.9: "Compute the unworked fraction as the client's guarantee_days minus
    the claim's days_worked, divided by guarantee_days, floored at zero so it is
    never negative; the credit_cents is the placement's placement_fee_cents
    multiplied by that unworked fraction, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/guarantee_credit_refund_prorated
    """
    # 6,000,000 * ((90-30)/90) = 6,000,000 * 0.6667 = 4,000,000
    ctx = _refund_claim_ctx(api)
    resolved = resolve_refund(ctx["am_id"], ctx["claim_id"])
    assert resolved["credit_cents"] == 4_000_000


def test_guarantee_replacement_credit_capped_at_replacement_estimate(api):
    """PRD §3.9: "here credit_cents is not time-prorated but is the full original
    placement_fee_cents, capped at the replacement placement's fee_estimate_cents
    (that is, the smaller of the two)."

    Design: Corner/calculations/guarantee_credit_replacement_variant_capped_full_fee
    """
    am = create_account_manager()
    rec = create_recruiter(["CARDIOLOGY"])
    coord = create_coordinator()
    client = create_client_entity(am["id"])
    opening = create_opening(am["id"], client["id"], positions_total=2, is_hard_to_fill=False)
    publish_opening(am["id"], opening["id"])

    def drive_offer(name, base):
        cand = create_candidate_entity(rec["id"], full_name=name, desired_comp_cents=base)
        app = create_application_entity(rec["id"], cand["id"], opening["id"])
        screen_application(rec["id"], app["id"])
        submit_application(rec["id"], app["id"])
        advance_to_interview(client["id"], app["id"])
        sv = create_site_visit_entity(
            rec["id"], app["id"], rec["id"],
            scheduled_start="2026-05-03T15:00:00Z", scheduled_end="2026-05-03T16:00:00Z",
        )
        complete_site_visit(rec["id"], sv["id"])
        return create_offer_entity(am["id"], app["id"], base_salary_cents=base)

    offer_a = drive_offer("Dr A", 30_000_000)  # fee_estimate 6,000,000
    # Use a non-overlapping day for B's visit interviewer to avoid double-booking.
    cand_b = create_candidate_entity(rec["id"], full_name="Dr B", desired_comp_cents=25_000_000)
    app_b = create_application_entity(rec["id"], cand_b["id"], opening["id"])
    screen_application(rec["id"], app_b["id"])
    submit_application(rec["id"], app_b["id"])
    advance_to_interview(client["id"], app_b["id"])
    sv_b = create_site_visit_entity(
        rec["id"], app_b["id"], rec["id"],
        scheduled_start="2026-05-04T15:00:00Z", scheduled_end="2026-05-04T16:00:00Z",
    )
    complete_site_visit(rec["id"], sv_b["id"])
    offer_b = create_offer_entity(am["id"], app_b["id"], base_salary_cents=25_000_000)

    accept_offer(rec["id"], offer_a["id"])
    accept_offer(rec["id"], offer_b["id"])
    placement_a = get_placement_for_offer(am["id"], offer_a["id"])
    placement_b = get_placement_for_offer(am["id"], offer_b["id"])  # fee_estimate 5,000,000

    cfile_a = get_cfile_for_placement(coord["id"], placement_a["id"])
    clear_credentialing(coord["id"], cfile_a["id"])
    set_clock("2026-06-01T00:00:00Z")
    onboard_placement(coord["id"], placement_a["id"])
    invoice_placement(am["id"], placement_a["id"], 30_000_000)  # placement_fee 6,000,000

    claim = file_claim(am["id"], placement_a["id"], "2026-07-01T00:00:00Z")
    approve_claim(am["id"], claim["id"])
    resolved = resolve_replacement(am["id"], claim["id"], placement_b["id"])
    assert resolved["status"] == "RESOLVED_REPLACEMENT"
    assert resolved["credit_cents"] == 5_000_000  # min(6,000,000, 5,000,000)


# --------------------------------------------------------------------------
# conserved-quantity ledgers: money and headcount
# --------------------------------------------------------------------------
def test_client_ledger_recognizes_invoiced_fee(api):
    """PRD §3.8: "the recognized total sums placement_fee_cents across the client's
    placements whose fee_status is INVOICED, PAID, or CREDITED".

    Design: Difficulty/compensating_invariant/net_client_fee_ledger_invoice_then_refund
    """
    ctx = setup_placement_invoiced(final_first_year_comp_cents=25_000_000, is_hard_to_fill=True)
    client = validate_success(
        api.get_client(ctx["client_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert client["net_placement_fee_cents"] == 6_000_000


def test_client_ledger_nets_invoice_minus_refund_without_drift(api):
    """PRD §3.8: "A credited placement deliberately stays inside the recognized total
    so that an invoice-then-credit pair nets to billed-minus-credit with no drift;
    the ledger invariant is that net always equals recognized minus credited."

    Design: Difficulty/compensating_invariant/net_client_fee_ledger_invoice_then_refund
    """
    ctx = _refund_claim_ctx(api)  # invoiced fee 6,000,000
    resolve_refund(ctx["am_id"], ctx["claim_id"])  # credit 4,000,000
    client = validate_success(
        api.get_client(ctx["client_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert client["net_placement_fee_cents"] == 2_000_000  # 6,000,000 - 4,000,000


def test_positions_ledger_fill_sets_one(api):
    """PRD §3.2: "positions_filled is always the count of that opening's placements
    whose placement_status is PRE_START, ACTIVE, or GUARANTEE_MET".

    Design: Difficulty/compensating_invariant/opening_positions_ledger_fill_then_fallout
    """
    ctx = setup_placement_pre_start()  # single position accepted -> filled
    opening = validate_success(
        api.get_job_opening(ctx["opening_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert opening["positions_filled"] == 1
    assert opening["status"] == "FILLED"


def test_positions_ledger_fallout_returns_to_zero(api):
    """PRD §3.9: "the opening's positions_filled is decremented by one, reopening a
    FILLED opening to OPEN if the count now falls below positions_total."

    Design: Difficulty/compensating_invariant/opening_positions_ledger_fill_then_fallout
    """
    ctx = setup_placement_active()
    claim = file_claim(ctx["am_id"], ctx["placement_id"], "2026-07-01T00:00:00Z")
    approve_claim(ctx["am_id"], claim["id"])
    opening = validate_success(
        api.get_job_opening(ctx["opening_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert opening["positions_filled"] == 0
    assert opening["status"] == "OPEN"
