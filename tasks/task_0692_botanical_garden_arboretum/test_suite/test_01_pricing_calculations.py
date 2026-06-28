"""Pricing and calculation tests: membership join/renewal fees, reservation
admission, event-ticket rounding, rental quote/discount, donation deductibility,
program tuition, and the conservancy match.

These exercise the dual-variant, combinatorial, and boundary calculation rules.
"""
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_plan,
    create_active_membership,
    create_pending_membership,
    create_venue,
    create_time_slot,
    setup_active_membership,
    setup_open_fund,
    create_donation,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
RENTAL = TEST_USERS["rental_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]
VISITOR = TEST_USERS["visitor_headers"]


# =============================================================================
# dual_variant_calc — membership join full fee vs renewal credit
# =============================================================================
def test_renewal_credits_unused_term_vs_full_join_fee(api):
    """PRD §3.2: "On activation the join fee is charged: because a brand-new
    annual term begins now, the member pays the full `annual_fee_cents` with no
    proration of any prior term, `paid_total_cents` is set to that charge".
    PRD §3.2: "multiply that daily value by the unused-days count and round the
    product half-up to whole cents — rounding exactly once, after the
    multiplication — to obtain the credit."

    On a 12000 plan, activation charges 12000 (no credit); an early renewal with
    30 unused days credits 986, charging 11014, so paid_total_cents == 23014.

    Design: Difficulty/dual_variant_calc/dvc_membership_join_full_fee_vs_renewal_credit
    """
    garden = create_garden(name="Fernwood")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Ada", auto_renew=False)
    m_id = membership["id"]
    activated = validate_success(api.activate_membership(m_id, make_visitor_headers(m_id)))
    assert activated["paid_total_cents"] == 12000, "activation charges the full annual fee"
    set_clock("2027-03-02T00:00:00Z")
    renewed = validate_success(api.renew_membership(m_id, make_visitor_headers(m_id)))
    assert renewed["paid_total_cents"] == 23014, f"expected 23014 after renewal, got {renewed['paid_total_cents']}"
    assert renewed["term_end"].startswith("2028-03-31T00:00:00")
    assert renewed["renewal_count"] == 1


def test_join_fee_no_credit_then_renewal_credit_diverge(api):
    """PRD §3.2: "The charge on renewal credits the unused remainder of the
    current term against the new annual fee". PRD §3.2: "the member pays the
    full `annual_fee_cents` with no proration of any prior term".

    The join fee (full 12000) and the renewal charge (11014, credited) differ:
    the renewal is strictly below the join fee because of the 986 credit.

    Design: Difficulty/dual_variant_calc/dvc_membership_join_full_fee_vs_renewal_credit
    """
    garden = create_garden(name="Fernwood2")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Ada", auto_renew=False)
    m_id = membership["id"]
    validate_success(api.activate_membership(m_id, make_visitor_headers(m_id)))
    set_clock("2027-03-02T00:00:00Z")
    renewed = validate_success(api.renew_membership(m_id, make_visitor_headers(m_id)))
    # join fee 12000 + renewal charge 11014 == 23014; renewal charge < join fee.
    renewal_charge = renewed["paid_total_cents"] - 12000
    assert renewal_charge == 11014, f"renewal charge expected 11014, got {renewal_charge}"
    assert renewal_charge < 12000, "renewal charge must be below the full join fee due to credit"


# =============================================================================
# dual_variant_calc — rental quoted vs final (lapsed loses discount)
# =============================================================================
def test_rental_quoted_with_discount_final_without_after_lapse(api):
    """PRD §3.6: "if a patron membership lapsed between request and confirm, the
    discount eligibility is lost at confirm and `final_cents` exceeds
    `quoted_cents`." PRD §3.6: "the discount applies only when a membership is
    attached and `ACTIVE`, its plan's `tier` is `PATRON`, and the subtotal is at
    least 50000 cents".

    quoted 102000 (15% off 120000) at request; after lapse, final 120000.

    Design: Difficulty/dual_variant_calc/dvc_rental_quoted_vs_final_lapsed_loses_discount
    """
    garden = create_garden(name="Bloomvale")
    plan = create_plan(garden["id"], tier="PATRON", annual_fee_cents=30000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Cyrus")
    m_id = membership["id"]
    venue = create_venue(garden["id"], name="Conservatory Hall", hourly_rate_cents=30000,
                         buffer_minutes=60, member_rental_discount_pct=0.15)
    rental = validate_success(api.create_rental(
        {"garden_id": garden["id"], "venue_id": venue["id"],
         "starts_at": "2026-05-01T10:00:00Z", "ends_at": "2026-05-01T13:30:00Z",
         "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    assert rental["quoted_cents"] == 102000, f"quoted expected 102000, got {rental['quoted_cents']}"
    set_clock("2027-04-01T00:00:00Z")  # advance past term_end -> membership LAPSES
    confirmed = validate_success(api.confirm_rental(rental["id"], RENTAL))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["final_cents"] == 120000, f"final expected 120000, got {confirmed['final_cents']}"


def test_rental_final_exceeds_quoted_by_exact_discount(api):
    """PRD §3.6: "On a clean confirm the price is recomputed by the identical
    pinned formula but using the membership's tier and status as observed *now*,
    at confirm time, and stored as the locked `final_cents`; the original
    `quoted_cents` is preserved for audit."

    The divergence equals exactly the lost 18000 discount (120000 - 102000).

    Design: Difficulty/dual_variant_calc/dvc_rental_quoted_vs_final_lapsed_loses_discount
    """
    garden = create_garden(name="Bloomvale2")
    plan = create_plan(garden["id"], tier="PATRON", annual_fee_cents=30000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Cyrus")
    m_id = membership["id"]
    venue = create_venue(garden["id"], name="Conservatory Hall", hourly_rate_cents=30000,
                         buffer_minutes=60, member_rental_discount_pct=0.15)
    rental = validate_success(api.create_rental(
        {"garden_id": garden["id"], "venue_id": venue["id"],
         "starts_at": "2026-05-01T10:00:00Z", "ends_at": "2026-05-01T13:30:00Z",
         "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    quoted = rental["quoted_cents"]
    set_clock("2027-04-01T00:00:00Z")
    confirmed = validate_success(api.confirm_rental(rental["id"], RENTAL))
    assert confirmed["final_cents"] - quoted == 18000, "final must exceed quoted by the lost discount"


# =============================================================================
# combinatorial_formula — mode (a): reservation admission reciprocal branch
# =============================================================================
def test_reservation_admission_reciprocal_discounted_per_head(api):
    """PRD §3.3: "when `reciprocal` is true, the per-head rate is the slot's
    `ga_price_cents` multiplied by one minus the garden's
    `reciprocal_discount_pct`, rounded half-up to whole cents". PRD §3.3: "The
    per-head rate is rounded *before* it is multiplied by `paid_heads`, and
    `admission_cents` is that rounded rate times `paid_heads`."

    ga 2500, reciprocal 0.5 -> per-head 1250 -> 2 heads = 2500.

    Design: Difficulty/combinatorial_formula/cf_reservation_admission_reciprocal_branch_mode_a
    """
    garden = create_garden(name="Aster Gardens", reciprocal_network_code="AHS", reciprocal_discount_pct=0.5)
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=10, ga_price_cents=2500)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 2, "reciprocal": True},
        make_visitor_headers("anon-recip"),
    ), expected_status=201)
    assert res["admission_cents"] == 2500, f"expected 2500, got {res['admission_cents']}"
    assert res["party_size"] == 2


def test_reservation_admission_non_reciprocal_full_ga(api):
    """PRD §3.3: "when `reciprocal` is false, the per-head rate is simply
    `ga_price_cents`." PRD §3.3: "`admission_cents` is that rounded rate times
    `paid_heads`."

    With reciprocal false, the same 2-head party at ga 2500 is charged 5000 —
    the non-discounted branch of the per-head rate decision.

    Design: Difficulty/combinatorial_formula/cf_reservation_admission_reciprocal_branch_mode_a
    """
    garden = create_garden(name="Aster Gardens NR", reciprocal_network_code="AHS", reciprocal_discount_pct=0.5)
    slot = create_time_slot(garden["id"], "2026-04-02T10:00:00Z", "2026-04-02T12:00:00Z",
                           capacity=10, ga_price_cents=2500)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 2, "reciprocal": False},
        make_visitor_headers("anon-fullga"),
    ), expected_status=201)
    assert res["admission_cents"] == 5000, f"expected 5000 at full GA, got {res['admission_cents']}"
    assert res["party_size"] == 2


# =============================================================================
# combinatorial_formula — mode (b): event-ticket round-per-ticket-then-sum
# =============================================================================
def test_event_ticket_member_rounds_per_ticket_then_multiplies(api):
    """PRD §3.4: "the per-ticket price is the `list_price_cents` multiplied by
    one minus the plan's `event_discount_pct`, rounded half-up to whole cents,
    and the `charged_cents` is that rounded per-ticket price multiplied by
    `quantity`." PRD §3.4: "The discounted per-ticket price is rounded *before*
    multiplying by `quantity` — rounding per ticket then summing, never summing
    then rounding, because the two differ by cents."

    list 1599, discount 0.2 -> per-ticket round(1279.2)=1279 -> *3 = 3837
    (NOT sum-then-round 3838).

    Design: Difficulty/combinatorial_formula/cf_event_ticket_round_per_ticket_then_sum_mode_b
    """
    garden = create_garden(name="Camellia Park")
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000, event_discount_pct=0.2)
    membership = create_active_membership(garden["id"], plan["id"],
                                          primary_member_name="Dora", household_member_names=["Ben"])
    m_id = membership["id"]
    ticket = validate_success(api.create_event_ticket(
        {"garden_id": garden["id"], "exhibit_name": "Orchid Show",
         "list_price_cents": 1599, "quantity": 3, "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    assert ticket["charged_cents"] == 3837, f"expected 3837 (round-per-ticket), got {ticket['charged_cents']}"
    assert ticket["status"] == "PURCHASED"


def test_event_ticket_non_member_full_list_times_quantity(api):
    """PRD §3.4: "When there is no membership or the membership is not `ACTIVE`,
    each ticket is charged at the full `list_price_cents` and `charged_cents` is
    `list_price_cents` times `quantity`."

    Non-member buyer: 1599 * 3 = 4797 with no rounding artifact (contrast with
    the member round-per-ticket path).

    Design: Difficulty/combinatorial_formula/cf_event_ticket_round_per_ticket_then_sum_mode_b
    """
    garden = create_garden(name="Camellia Park NM")
    ticket = validate_success(api.create_event_ticket(
        {"garden_id": garden["id"], "exhibit_name": "Orchid Show",
         "list_price_cents": 1599, "quantity": 3},
        make_visitor_headers("anon-nm"),
    ), expected_status=201)
    assert ticket["charged_cents"] == 4797, f"expected 4797, got {ticket['charged_cents']}"


# =============================================================================
# combinatorial_formula — mode (c): rental subtotal-keyed discount eligibility
# =============================================================================
def test_rental_below_subtotal_floor_gets_no_discount(api):
    """PRD §3.6: "eligibility for the member discount is evaluated against the
    subtotal — the discount applies only when a membership is attached and
    `ACTIVE`, its plan's `tier` is `PATRON`, and the subtotal is at least 50000
    cents (five hundred dollars)". PRD §3.6: "first the billable hours are the
    rental's span (`ends_at` minus `starts_at`) expressed in hours and rounded
    *up* to a whole hour for any partial hour; second the subtotal is those
    hours multiplied by the venue's `hourly_rate_cents`".

    1h * 30000 = 30000 < 50000 floor -> no discount even for a PATRON, so
    quoted_cents stays 30000.

    Design: Difficulty/combinatorial_formula/cf_rental_subtotal_keyed_discount_mode_c
    """
    garden = create_garden(name="Dahlia Grove")
    plan = create_plan(garden["id"], tier="PATRON", annual_fee_cents=30000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Edith")
    m_id = membership["id"]
    venue = create_venue(garden["id"], name="Glasshouse", hourly_rate_cents=30000,
                         buffer_minutes=60, member_rental_discount_pct=0.15)
    rental = validate_success(api.create_rental(
        {"garden_id": garden["id"], "venue_id": venue["id"],
         "starts_at": "2026-05-02T10:00:00Z", "ends_at": "2026-05-02T11:00:00Z",
         "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    assert rental["quoted_cents"] == 30000, f"expected 30000 (no discount below floor), got {rental['quoted_cents']}"
    assert rental["status"] == "REQUESTED"


def test_rental_above_subtotal_floor_gets_patron_discount(api):
    """PRD §3.6: "when eligible, the discount is the subtotal multiplied by the
    venue's `member_rental_discount_pct`, rounded half-up to whole cents, and
    otherwise the discount is 0; fifth, the price is the subtotal minus the
    discount."

    A 4-hour (ceil 13:30-10:00) PATRON rental: subtotal 120000 >= 50000, so the
    15% discount applies -> quoted 102000, proving the same eligibility gate
    flips once the computed subtotal clears the floor.

    Design: Difficulty/combinatorial_formula/cf_rental_subtotal_keyed_discount_mode_c
    """
    garden = create_garden(name="Dahlia Grove Big")
    plan = create_plan(garden["id"], tier="PATRON", annual_fee_cents=30000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Edith")
    m_id = membership["id"]
    venue = create_venue(garden["id"], name="Glasshouse", hourly_rate_cents=30000,
                         buffer_minutes=60, member_rental_discount_pct=0.15)
    rental = validate_success(api.create_rental(
        {"garden_id": garden["id"], "venue_id": venue["id"],
         "starts_at": "2026-05-02T10:00:00Z", "ends_at": "2026-05-02T13:30:00Z",
         "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    assert rental["quoted_cents"] == 102000, f"expected 102000 (15% off 120000), got {rental['quoted_cents']}"


# =============================================================================
# boundary_precision_check — renewal credit zero at expiry
# =============================================================================
def test_renewal_at_exact_expiry_zero_credit_full_fee(api):
    """PRD §3.2: "When a renewal happens exactly at expiry, with the current
    clock equal to `term_end`, the unused days are 0, the credit is 0, and the
    charge is the full annual fee."

    Activate at default (term_end 2027-04-01), advance to exactly 2027-04-01,
    renew with auto_renew -> charge full 12000 -> paid_total_cents == 24000.

    Design: Difficulty/boundary_precision_check/bpc_renewal_credit_zero_at_expiry
    """
    garden = create_garden(name="Lupine Ledge")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Mona", auto_renew=True)
    m_id = membership["id"]
    validate_success(api.activate_membership(m_id, make_visitor_headers(m_id)))
    set_clock("2027-04-01T00:00:00Z")
    renewed = validate_success(api.renew_membership(m_id, make_visitor_headers(m_id)))
    assert renewed["paid_total_cents"] == 24000, f"expected 24000 (full fee, no credit), got {renewed['paid_total_cents']}"
    assert renewed["status"] == "ACTIVE"


def test_renewal_inside_window_credits_below_full_fee(api):
    """PRD §3.2: "the renewal charge is the `annual_fee_cents` minus that credit,
    floored at 0 so it is never negative."

    Renewing 30 days early (unused_days > 0) credits a positive amount, so the
    cumulative paid is strictly below the no-credit boundary of 24000 — the
    other side of the unused-days zero edge.

    Design: Difficulty/boundary_precision_check/bpc_renewal_credit_zero_at_expiry
    """
    garden = create_garden(name="Lupine Ledge Early")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Mona", auto_renew=True)
    m_id = membership["id"]
    validate_success(api.activate_membership(m_id, make_visitor_headers(m_id)))
    set_clock("2027-03-02T00:00:00Z")  # 30 unused days remaining
    renewed = validate_success(api.renew_membership(m_id, make_visitor_headers(m_id)))
    assert renewed["paid_total_cents"] == 23014, f"expected 23014 (credited), got {renewed['paid_total_cents']}"
    assert renewed["paid_total_cents"] < 24000, "early renewal credit must reduce the charge below the full fee"


# =============================================================================
# Corner: calculations section
# =============================================================================
def test_donation_general_above_threshold_subtracts_fmv(api):
    """PRD §3.7: "a benefit is recognized only for a `GENERAL` gift of at least
    25000 cents (a token-gift premium), in which case `tax_deductible_cents` is
    the `amount_cents` minus 2000 cents (the premium's fair-market value)."

    GENERAL 30000 (>= 25000) -> 30000 - 2000 = 28000.

    Design: Corner/calculations/donation_deductible_general_above_threshold_subtracts_fmv
    """
    garden = create_garden(name="Fuchsia Fields")
    donation = validate_success(api.create_donation(
        {"garden_id": garden["id"], "amount_cents": 30000, "designation": "GENERAL"}, DEV,
    ), expected_status=201)
    assert donation["tax_deductible_cents"] == 28000, f"expected 28000, got {donation['tax_deductible_cents']}"
    assert donation["status"] == "RECORDED"


def test_donation_general_below_threshold_fully_deductible(api):
    """PRD §3.7: "For a `GENERAL` gift below that threshold, and for every
    `CONSERVANCY` or `CAPITAL` gift regardless of amount, the full `amount_cents`
    is deductible."

    GENERAL 20000 (< 25000) -> fully deductible 20000, no FMV subtracted.

    Design: Corner/calculations/donation_deductible_general_below_threshold_fully_deductible
    """
    garden = create_garden(name="Geranium Glen")
    donation = validate_success(api.create_donation(
        {"garden_id": garden["id"], "amount_cents": 20000, "designation": "GENERAL"},
        make_visitor_headers("anon-don"),
    ), expected_status=201)
    assert donation["tax_deductible_cents"] == 20000, f"expected 20000, got {donation['tax_deductible_cents']}"


def test_conservancy_match_caps_at_remaining_then_zero(api):
    """PRD §3.7: "compute the raw match as the donation's `amount_cents`
    multiplied by the fund's `match_ratio`, rounded half-up to whole cents;
    compute the remaining cap as the fund's `match_cap_cents` minus its current
    `matched_total_cents`, floored at 0; the applied match is the smaller of the
    raw match and the remaining cap." PRD §3.7: "the donation's `amount_cents` is
    added to the fund's `pledged_total_cents`".

    First 30000 gift (raw 15000) clamps to cap 10000; a second 4000 gift adds 0
    more match (remaining cap 0) but still pledges -> pledged 34000, matched 10000.

    Design: Corner/calculations/conservancy_match_caps_at_remaining_then_zero
    """
    garden, fund = setup_open_fund(match_ratio=0.5, match_cap_cents=10000)
    create_donation(garden["id"], amount_cents=30000, designation="CONSERVANCY")
    create_donation(garden["id"], amount_cents=4000, designation="CONSERVANCY")
    refreshed = validate_success(api.get_conservancy_fund(fund["id"], DEV))
    assert refreshed["pledged_total_cents"] == 34000, f"expected pledged 34000, got {refreshed['pledged_total_cents']}"
    assert refreshed["matched_total_cents"] == 10000, f"expected matched 10000, got {refreshed['matched_total_cents']}"


def test_conservancy_match_zero_after_campaign_closed(api):
    """PRD §3.7: "A `DevelopmentOfficer` closes the campaign, moving
    `campaign_status` from `OPEN` to `CLOSED`, after which conservancy gifts
    still pledge but accrue no further match". PRD §3.7: "While the campaign is
    `CLOSED`, no match accrues and the applied match is 0."

    A CONSERVANCY gift after close pledges 8000 but matches 0.

    Design: Corner/calculations/conservancy_match_zero_after_campaign_closed
    """
    garden, fund = setup_open_fund(match_ratio=0.5, match_cap_cents=10000)
    validate_success(api.close_campaign(fund["id"], DEV))
    create_donation(garden["id"], amount_cents=8000, designation="CONSERVANCY")
    refreshed = validate_success(api.get_conservancy_fund(fund["id"], DEV))
    assert refreshed["pledged_total_cents"] == 8000, f"expected pledged 8000, got {refreshed['pledged_total_cents']}"
    assert refreshed["matched_total_cents"] == 0, f"expected matched 0, got {refreshed['matched_total_cents']}"


def test_event_ticket_non_member_full_list_price_corner(api):
    """PRD §3.4: "When there is no membership or the membership is not `ACTIVE`,
    each ticket is charged at the full `list_price_cents` and `charged_cents` is
    `list_price_cents` times `quantity`."

    Non-member purchase 1599 * 3 = 4797.

    Design: Corner/calculations/event_ticket_non_member_full_list_price
    """
    garden = create_garden(name="Jonquil Junction")
    ticket = validate_success(api.create_event_ticket(
        {"garden_id": garden["id"], "exhibit_name": "Bonsai Expo",
         "list_price_cents": 1599, "quantity": 3},
        make_visitor_headers("anon-nm2"),
    ), expected_status=201)
    assert ticket["charged_cents"] == 4797, f"expected 4797, got {ticket['charged_cents']}"


def test_program_tuition_member_discount_at_create(api):
    """PRD §3.5: "The member program discount applies only when a membership is
    attached and that membership is `ACTIVE` at the instant tuition is charged:
    in that case `charged_cents` is the session's `tuition_cents` multiplied by
    one minus the plan's `program_discount_pct`, rounded half-up to whole cents".

    plan discount 0.1 on tuition 10000 -> charged 9000.

    Design: Corner/calculations/program_tuition_member_discount_at_create
    """
    garden = create_garden(name="Kniphofia Keep")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000, program_discount_pct=0.1)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Kim")
    m_id = membership["id"]
    session = validate_success(api.create_program_session(
        {"garden_id": garden["id"], "title": "Pruning Workshop",
         "starts_at": "2026-09-01T09:00:00Z", "capacity": 5, "tuition_cents": 10000}, STAFF,
    ), expected_status=201)
    reg = validate_success(api.create_registration(
        {"garden_id": garden["id"], "program_session_id": session["id"],
         "participant_name": "Kim Jr", "membership_id": m_id},
        make_visitor_headers(m_id),
    ), expected_status=201)
    assert reg["charged_cents"] == 9000, f"expected 9000, got {reg['charged_cents']}"
    assert reg["status"] == "ENROLLED"
