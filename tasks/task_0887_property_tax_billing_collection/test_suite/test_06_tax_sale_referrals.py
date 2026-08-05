"""Tax-sale referrals: fork to sold, auto-redeem cascade, thresholds, overlap, SoD, OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_tax_year, create_parcel, issue_bill, set_clock,
    setup_year_parcel_bill, setup_delinquent_second_installment, setup_referred_bill,
    open_referral, redeem_referral, sell_referral, post_payment,
    bill_version, get_bill, installment_seq,
    create_referral_payload, sell_payload,
    make_treasurer_headers, make_collections_headers,
    TEST_USERS,
)

COLLECTIONS = TEST_USERS["collections_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# ---- Difficulty: referral_fork_to_sold (test 1 of 2) ----
def test_sell_moves_referral_to_sold_and_records_seller(api):
    """PRD 3.8: "The sale accepts an optional winning bid `sale_price_cents`, moves the
    referral to `SOLD`, sets the bill's `sale_status` to the terminal `SOLD`, and
    records `sold_by_user_id` and `sale_price_cents`."

    Design: Difficulty/non_linear_state_machine/referral_fork_to_sold
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    set_clock(api, "2027-09-16T00:00:00Z")
    sold = sell_referral(api, referral["id"], sale_price_cents=70000, user_id="tr-1")
    assert sold["status"] == "SOLD"
    assert sold["sold_by_user_id"] == "tr-1"


# ---- Difficulty: referral_fork_to_sold (test 2 of 2) ----
def test_sell_sets_bill_sale_status_sold(api):
    """PRD 3.8: "sets the bill's `sale_status` to the terminal `SOLD`, and records
    `sold_by_user_id` and `sale_price_cents`."

    Design: Difficulty/non_linear_state_machine/referral_fork_to_sold
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    set_clock(api, "2027-09-16T00:00:00Z")
    sell_referral(api, referral["id"], sale_price_cents=70000, user_id="tr-1")
    assert get_bill(api, bill["id"])["sale_status"] == "SOLD"


# ---- Difficulty: payment_clears_bill_auto_redeems_referral (test 1 of 2) ----
def test_full_payment_clears_delinquent_bill(api):
    """PRD 3.4: "a `DELINQUENT` installment whose penalty, interest, and principal are all
    cleared becomes `PAID`, while one that is reduced without clearing
    becomes `PARTIALLY_PAID`."

    Design: Difficulty/transitive_cascade/payment_clears_bill_auto_redeems_referral
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    post_payment(api, bill["id"], 52500, tender_type="CASH")
    assert installment_seq(api, bill["id"], 2)["status"] == "PAID"
    assert get_bill(api, bill["id"])["collection_status"] == "PAID"


# ---- Difficulty: payment_clears_bill_auto_redeems_referral (test 2 of 2) ----
def test_full_payment_auto_redeems_open_referral(api):
    """PRD 3.4: "if a payment drives the bill's balance to zero while a `REFERRED` tax-sale
    referral is open, that referral is auto-redeemed and the bill's
    `sale_status` becomes `REDEEMED`"

    Design: Difficulty/transitive_cascade/payment_clears_bill_auto_redeems_referral
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    post_payment(api, bill["id"], 52500, tender_type="CASH")
    assert get_bill(api, bill["id"])["sale_status"] == "REDEEMED"
    assert validate_success(api.get_referral(referral["id"], COLLECTIONS))["status"] == "REDEEMED"


# ---- Difficulty: referral_threshold_at_exact_floor (test 1 of 2) ----
def test_referral_at_exact_threshold_is_created(api):
    """PRD 3.8: "the bill's `delinquent_principal_cents` must be at least the statutory
    lien-referral threshold `LIEN_REFERRAL_THRESHOLD_CENTS` of fifty
    thousand cents (50000), else `ERR_BELOW_REFERRAL_THRESHOLD` — a
    delinquent principal exactly equal to 50000 satisfies the check and is
    referred"

    Design: Difficulty/boundary_precision_check/referral_threshold_at_exact_floor
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=5000000, clock="2026-09-16")
    referral = open_referral(api, bill["id"], opener_user_id="co-1")
    assert referral["status"] == "REFERRED"
    assert referral["delinquent_principal_at_referral_cents"] == 50000


# ---- Difficulty: referral_threshold_at_exact_floor (test 2 of 2) ----
def test_referral_at_exact_threshold_moves_bill_in_tax_sale(api):
    """PRD 3.8: "the bill's `sale_status` moves to `IN_TAX_SALE`, and the bill's
    `version` increments by one."

    Design: Difficulty/boundary_precision_check/referral_threshold_at_exact_floor
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=5000000, clock="2026-09-16")
    open_referral(api, bill["id"], opener_user_id="co-1")
    assert get_bill(api, bill["id"])["sale_status"] == "IN_TAX_SALE"


# ---- Difficulty: not_delinquent_beats_below_threshold (test 1 of 2) ----
def test_current_bill_referral_returns_not_delinquent(api):
    """PRD 3.8: "the bill's `collection_status` must be `DELINQUENT` with at least one
    installment in `DELINQUENT`, else `ERR_NOT_DELINQUENT`; the bill's
    `delinquent_principal_cents` must be at least the statutory
    lien-referral threshold"

    Design: Difficulty/priority_pair_validation_conflict/not_delinquent_beats_below_threshold
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=5000000)
    ver = bill_version(api, bill["id"], COLLECTIONS)
    resp = api.create_referral(create_referral_payload(bill["id"], ver), COLLECTIONS)
    validate_error(resp, ApiErrorId.ERR_NOT_DELINQUENT.value)


# ---- Difficulty: not_delinquent_beats_below_threshold (test 2 of 2) ----
def test_not_delinquent_precedence_over_below_threshold(api):
    """PRD 2.6: "that a referral checks delinquency posture before the threshold"

    Design: Difficulty/priority_pair_validation_conflict/not_delinquent_beats_below_threshold
    """
    # delinquent_principal is 0 here, so it is ALSO below the 50000 threshold; the
    # state check must win, yielding ERR_NOT_DELINQUENT (not ERR_BELOW_REFERRAL_THRESHOLD).
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=5000000)
    assert bill["delinquent_principal_cents"] == 0
    ver = bill_version(api, bill["id"], COLLECTIONS)
    resp = api.create_referral(create_referral_payload(bill["id"], ver), COLLECTIONS)
    err = validate_error(resp, ApiErrorId.ERR_NOT_DELINQUENT.value)
    assert err["error_id"] != "ERR_BELOW_REFERRAL_THRESHOLD"


# ---- Difficulty: referral_rejected_when_no_installment_delinquent (test 1 of 2) ----
def test_referral_all_installments_pending_rejected(api):
    """PRD 3.8: "the bill's `collection_status` must be `DELINQUENT` with at least one
    installment in `DELINQUENT`, else `ERR_NOT_DELINQUENT`"

    Design: Difficulty/cross_entity_state_dependency/referral_rejected_when_no_installment_delinquent
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=5000000)
    assert installment_seq(api, bill["id"], 1)["status"] == "PENDING"
    assert installment_seq(api, bill["id"], 2)["status"] == "PENDING"
    ver = bill_version(api, bill["id"], COLLECTIONS)
    resp = api.create_referral(create_referral_payload(bill["id"], ver), COLLECTIONS)
    validate_error(resp, ApiErrorId.ERR_NOT_DELINQUENT.value)


# ---- Difficulty: referral_rejected_when_no_installment_delinquent (test 2 of 2) ----
def test_referral_on_non_delinquent_bill_leaves_sale_status_none(api):
    """PRD 3.8: "the bill's `collection_status` must be `DELINQUENT` with at least one
    installment in `DELINQUENT`, else `ERR_NOT_DELINQUENT`"

    Design: Difficulty/cross_entity_state_dependency/referral_rejected_when_no_installment_delinquent
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=5000000)
    ver = bill_version(api, bill["id"], COLLECTIONS)
    api.create_referral(create_referral_payload(bill["id"], ver), COLLECTIONS)
    assert get_bill(api, bill["id"])["sale_status"] == "NONE"


# ---- Difficulty: referral_window_half_open_overlap (test 1 of 2) ----
def _setup_two_bills_one_referred(api):
    ty24 = create_tax_year(api, year=2024,
                           first_installment_due_date="2025-06-15T00:00:00Z",
                           second_installment_due_date="2025-09-15T00:00:00Z")
    ty25 = create_tax_year(api, year=2025)
    parcel = create_parcel(api, parcel_number="APN-D16", assessed_value_cents=5000000)
    bill24 = issue_bill(api, parcel["id"], ty24["id"])
    bill25 = issue_bill(api, parcel["id"], ty25["id"])
    set_clock(api, "2026-01-01T00:00:00Z")
    open_referral(api, bill24["id"], opener_user_id="co-1")
    set_clock(api, "2026-09-16T00:00:00Z")
    return bill24, bill25


def test_referral_window_overlap_rejected(api):
    """PRD 3.8: "the half-open window `[referral_date, redemption_deadline)` must not
    overlap a non-terminal referral already open on the same parcel —
    adjacency exactly at a deadline is allowed — else
    `ERR_REFERRAL_WINDOW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/referral_window_half_open_overlap
    """
    bill24, bill25 = _setup_two_bills_one_referred(api)
    ver25 = bill_version(api, bill25["id"], COLLECTIONS)
    resp = api.create_referral(create_referral_payload(bill25["id"], ver25), COLLECTIONS)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_WINDOW_OVERLAP.value)


# ---- Difficulty: referral_window_half_open_overlap (test 2 of 2) ----
def test_referral_window_overlap_leaves_second_bill_none(api):
    """PRD 3.8: "the half-open window `[referral_date, redemption_deadline)` must not
    overlap a non-terminal referral already open on the same parcel"

    Design: Difficulty/resource_temporal_overlap/referral_window_half_open_overlap
    """
    bill24, bill25 = _setup_two_bills_one_referred(api)
    ver25 = bill_version(api, bill25["id"], COLLECTIONS)
    api.create_referral(create_referral_payload(bill25["id"], ver25), COLLECTIONS)
    assert get_bill(api, bill25["id"])["sale_status"] == "NONE"


# ---- Corner: state_machines/redeem_already_redeemed_referral_invalid_state ----
def test_redeem_already_redeemed_referral_invalid_state(api):
    """PRD 3.8: "Redeeming or selling a referral that is not in `REFERRED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/redeem_already_redeemed_referral_invalid_state
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    redeem_referral(api, referral["id"], user_id="co-1")
    resp = api.redeem_referral(referral["id"], make_collections_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- Corner: validations/redeem_after_deadline_expired_rejected ----
def test_redeem_after_deadline_expired_rejected(api):
    """PRD 3.8: "It is redeemed by a `CollectionsOfficer` or `Treasurer` while the current
    clock is strictly before the `redemption_deadline`; a redemption
    attempted at or after the deadline is rejected with
    `ERR_REDEMPTION_EXPIRED`."

    Design: Corner/validations/redeem_after_deadline_expired_rejected
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    set_clock(api, "2027-09-16T00:00:00Z")
    resp = api.redeem_referral(referral["id"], make_collections_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXPIRED.value)


# ---- Corner: validations/sell_before_deadline_not_expired_rejected ----
def test_sell_before_deadline_not_expired_rejected(api):
    """PRD 3.8: "the current clock must be at or after the `redemption_deadline`, and a
    sale attempted before it is rejected with
    `ERR_REDEMPTION_NOT_EXPIRED`."

    Design: Corner/validations/sell_before_deadline_not_expired_rejected
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    resp = api.sell_referral(referral["id"], sell_payload(60000), make_treasurer_headers("tr-1"))
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_NOT_EXPIRED.value)


# ---- Corner: rbac/referral_opener_cannot_sell_sod ----
def test_referral_opener_cannot_execute_sale(api):
    """PRD 3.8: "The executing treasurer must not be the officer who opened the referral —
    the acting `X-User-ID` must differ from `created_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/referral_opener_cannot_sell_sod
    """
    ty, parcel, bill, referral = setup_referred_bill(
        api, assessed_value_cents=5000000, clock="2026-09-16", opener_user_id="co-1")
    set_clock(api, "2027-09-16T00:00:00Z")
    resp = api.sell_referral(referral["id"], sell_payload(60000), make_treasurer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---- Corner: cross_cutting_complexity_layers/referral_create_stale_bill_version_rejected ----
def test_referral_create_stale_bill_version_rejected(api):
    """PRD 2.7: "A create-referral request must likewise include `expected_bill_version`
    equal to the bill's current `version`. If the bill's `version` has
    advanced since the client read it — for instance because a payment
    reduced the delinquency below the referral threshold — the referral is
    rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/referral_create_stale_bill_version_rejected
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C25", assessed_value_cents=8000000)
    bill = issue_bill(api, parcel["id"], ty["id"])
    set_clock(api, "2026-09-16T00:00:00Z")
    stale_ver = bill_version(api, bill["id"], COLLECTIONS)
    post_payment(api, bill["id"], 10000, tender_type="CASH")
    resp = api.create_referral(create_referral_payload(bill["id"], stale_ver), COLLECTIONS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
