"""Scrap credit ledger: posting, surrender vs keep, void conservation, OCC,
and the source-ownership guard."""
from test_helpers import (
    CLERK,
    MGR,
    ApiErrorId,
    accept_quote,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    find_remnant_for_order,
    get_customer,
    list_customer_credits,
    post_scrap_credit,
    validate_error,
    validate_success,
)

NEST_LINE = {"bbox_width_mm": 300, "bbox_height_mm": 200, "hole_count": 5,
             "hole_diameter_mm": 20, "corner_fillet_count": 2, "bend_count": 4,
             "weld_inches": 0, "finish": "NONE"}


def _order_with_remnant():
    """10x 300x200 on a full sheet leaves a qualifying remnant (>= 2000 cm2)."""
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    create_machine("BRAKE")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=NEST_LINE, qty=10)
    order = accept_quote(submitted["id"], customer["id"])
    remnant = find_remnant_for_order(order["id"])
    assert remnant is not None, "Setup failed: expected a stocked remnant"
    return grade, customer, order, remnant


# --- surrender vs keep (Difficulty: remnant_yield_scrap_path_vs_inventory_path_diverge)

def test_remnant_surrender_posts_capped_credit(api):
    """PRD §3.2: "The credited area, `credited_area_cm2`, is the smallest of
    three ceilings: the source sheet's own area, ten percent of the standard
    sheet area — ten percent of 28,800 square centimeters, which is 2,880
    square centimeters — and a hard cap of 90,000 square centimeters per
    event. The credit itself, `credit_cents`, is the credited area multiplied
    by the grade's `scrap_rate_cents_per_cm2`, rounded half-up to integer
    cents. The credit lands in POSTED status, the customer's
    `scrap_credit_balance_cents` increases by exactly that amount, and the
    customer's `version` increments."

    Design: Difficulty/dual_variant_calc/remnant_yield_scrap_path_vs_inventory_path_diverge
    """
    grade, customer, order, remnant = _order_with_remnant()

    resp = api.create_scrap_credit(
        {"customer_id": customer["id"], "sheet_stock_id": remnant["id"]}, CLERK)
    credit = validate_success(resp, 201)
    # The remnant's own area exceeds the cap, so the 10%-of-standard ceiling
    # (2,880 cm2) binds regardless of the remnant's exact dimensions.
    assert credit["credited_area_cm2"] == 2880
    assert credit["credit_cents"] == 58  # round_half_up(2880 * 0.020)
    assert credit["status"] == "POSTED"

    cust = get_customer(customer["id"])
    assert cust["scrap_credit_balance_cents"] == 58

    stocked = validate_success(api.get_sheet_stock(remnant["id"], CLERK))
    assert stocked["status"] != "AVAILABLE", (
        "a surrendered remnant leaves the reusable pool"
    )


def test_remnant_kept_in_inventory_posts_no_credit(api):
    """PRD §3.2: "when the leftover offcut qualifies, a child REMNANT row is
    created in AVAILABLE status and linked to the consuming order through
    `source_order_id`." PRD §3.2: "Posting a scrap credit takes a
    `customer_id` and a `sheet_stock_id`." (No posting, no balance movement.)

    Design: Difficulty/dual_variant_calc/remnant_yield_scrap_path_vs_inventory_path_diverge
    """
    grade, customer, order, remnant = _order_with_remnant()

    stocked = validate_success(api.get_sheet_stock(remnant["id"], CLERK))
    assert stocked["status"] == "AVAILABLE"
    assert stocked["kind"] == "REMNANT"

    cust = get_customer(customer["id"])
    assert cust["scrap_credit_balance_cents"] == 0, (
        "keeping the offcut as stock carries value 0 to the credit ledger"
    )
    assert list_customer_credits(customer["id"]) == []


# --- ownership guard (Difficulty: business_safety_vs_business_referential_on_scrap_credit)

def test_scrap_credit_for_another_customers_remnant_rejected(api):
    """PRD §3.2: "The source is polymorphic: either a REMNANT surrendered from
    inventory, which must belong to that customer as traced through the
    remnant's source order, or a walk-in sheet registered with no source
    order. A source that is the wrong kind, belongs to another customer, or is
    already CONSUMED or SCRAPPED is rejected with `ERR_SCRAP_SOURCE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_scrap_credit
    """
    grade, owner, order, remnant = _order_with_remnant()
    stranger = create_customer(company_name="Lambda-B", email="lb@x.com")

    resp = api.create_scrap_credit(
        {"customer_id": stranger["id"], "sheet_stock_id": remnant["id"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_SCRAP_SOURCE_INVALID, 422)

    assert get_customer(stranger["id"])["scrap_credit_balance_cents"] == 0
    stocked = validate_success(api.get_sheet_stock(remnant["id"], CLERK))
    assert stocked["status"] == "AVAILABLE", "a rejected posting mutates nothing"


def test_scrap_credit_rejected_source_leaves_no_partial_credit(api):
    """PRD §3.2: "A source that is the wrong kind, belongs to another
    customer, or is already CONSUMED or SCRAPPED is rejected with
    `ERR_SCRAP_SOURCE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_scrap_credit
    """
    grade, owner, order, remnant = _order_with_remnant()
    stranger = create_customer(company_name="Lambda-C", email="lc@x.com")

    validate_error(
        api.create_scrap_credit(
            {"customer_id": stranger["id"], "sheet_stock_id": remnant["id"]},
            CLERK),
        ApiErrorId.ERR_SCRAP_SOURCE_INVALID, 422,
    )
    assert list_customer_credits(stranger["id"]) == []
    # The legitimate owner can still surrender the same remnant afterwards.
    credit = post_scrap_credit(owner["id"], remnant["id"])
    assert credit["status"] == "POSTED"
    assert get_customer(owner["id"])["scrap_credit_balance_cents"] == 58


# --- post/void conservation (Difficulty: scrap_credit_post_then_void_conserves_balance)

def _customer_with_posted_credit():
    grade = create_grade()
    customer = create_customer()
    sheet = create_full_sheet(grade["id"])  # walk-in source (no source order)
    credit = post_scrap_credit(customer["id"], sheet["id"])
    return grade, customer, credit


def test_post_then_void_conserves_balance(api):
    """PRD §3.2: "The void is a compensating reversal:
    `scrap_credit_balance_cents` is debited by the credit's `credit_cents`,
    the customer's `version` increments by one, the credit moves to VOID, and
    a CREDIT_VOIDED audit event is appended."

    Design: Difficulty/compensating_invariant/scrap_credit_post_then_void_conserves_balance
    """
    grade, customer, credit = _customer_with_posted_credit()

    after_post = get_customer(customer["id"])
    assert after_post["scrap_credit_balance_cents"] == 58

    resp = api.void_scrap_credit(credit["id"], after_post["version"], MGR)
    voided = validate_success(resp, 200)
    assert voided["status"] == "VOID"

    after_void = get_customer(customer["id"])
    assert after_void["scrap_credit_balance_cents"] == 0, (
        "posting (+58) followed by voiding (-58) restores the balance exactly"
    )
    assert after_void["version"] == after_post["version"] + 1, (
        "the customer's version increments by one on the void"
    )


def test_void_of_non_posted_credit_rejected(api):
    """PRD §3.2: "Voiding a credit in any status other than POSTED is rejected
    with `ERR_CREDIT_NOT_VOIDABLE` ..."

    Design: Difficulty/compensating_invariant/scrap_credit_post_then_void_conserves_balance
    """
    grade, customer, credit = _customer_with_posted_credit()
    current = get_customer(customer["id"])
    validate_success(api.void_scrap_credit(credit["id"], current["version"], MGR))

    fresh = get_customer(customer["id"])
    resp = api.void_scrap_credit(credit["id"], fresh["version"], MGR)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_VOIDABLE, 409)
    assert get_customer(customer["id"])["scrap_credit_balance_cents"] == 0


# --- OCC on void (Corner: occ_stale_version_on_credit_void) -----------------

def test_occ_stale_version_on_credit_void(api):
    """PRD §2.7: "Voiding a scrap credit likewise requires
    `expected_customer_version` matching the customer's current `version`; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a credit
    application or a new posting may have moved `scrap_credit_balance_cents`
    since the caller last read it, and the void would debit a balance the
    caller never observed."

    Design: Corner/validations/occ_stale_version_on_credit_void
    """
    grade, customer, credit = _customer_with_posted_credit()
    current = get_customer(customer["id"])

    resp = api.void_scrap_credit(credit["id"], current["version"] - 1, MGR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    unchanged = get_customer(customer["id"])
    assert unchanged["scrap_credit_balance_cents"] == 58
    row = validate_success(api.get_scrap_credit(credit["id"], MGR))
    assert row["status"] == "POSTED"


# --- RBAC on void (Corner: inventory_clerk_cannot_void_credit) --------------

def test_inventory_clerk_cannot_void_credit(api):
    """PRD §2.1: "`ShopManager` is the shop owner: master data (grades,
    machines, vendors), customer administration, credit voids, audit access,
    and the logical clock." PRD §2.1: "A caller whose role is not in the
    endpoint's list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/inventory_clerk_cannot_void_credit
    """
    grade, customer, credit = _customer_with_posted_credit()
    current = get_customer(customer["id"])

    resp = api.void_scrap_credit(credit["id"], current["version"], CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    row = validate_success(api.get_scrap_credit(credit["id"], MGR))
    assert row["status"] == "POSTED"
