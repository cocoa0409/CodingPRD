"""Buyback: dual-variant pricing, quota boundary, ticket lifecycle, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_buyback_ticket,
    accept_buyback_ticket,
    create_buyback_ticket,
    get_success_data,
    make_student_headers,
    setup_buyback_open_with_demand,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def test_buyback_needs_vs_wholesale_same_copy(api):
    """PRD §3.9: "When the quota is positive and not yet fully consumed, the
    ticket's `pricing_variant` is `NEEDS_BASED` and its `quoted_price_cents` is
    50% of the title's `list_price_cents` rounded half-up — a flat half of new
    list regardless of condition. Otherwise the variant is `WHOLESALE` and the
    quoted price is the `price_cents` of the unique wholesale quote for the
    title and declared condition whose half-open window contains now."

    Design: Difficulty/dual_variant_calc/buyback_needs_vs_wholesale_same_copy
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=1, isbn="9780000000001"
    )
    student_headers = make_student_headers(base["student"]["id"])

    tk1 = create_buyback_ticket(
        base["title"]["id"], base["t2"]["id"], base["title"]["version"],
        base["student"]["id"],
    )
    assert_buyback_ticket(tk1)
    assert tk1["pricing_variant"] == "NEEDS_BASED"
    assert tk1["quoted_price_cents"] == 5000

    accept_buyback_ticket(tk1["id"], base["student"]["id"])

    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    tk2 = create_buyback_ticket(
        base["title"]["id"], base["t2"]["id"], title["version"],
        base["student"]["id"],
    )
    assert tk2["pricing_variant"] == "WHOLESALE"
    assert tk2["quoted_price_cents"] == 2200


def test_buyback_quota_equality_boundary(api):
    """PRD §3.9: "The demand quota for a title and upcoming term is the sum of
    `qty_used_requested` over the `APPROVED` adoptions of that title in that
    term, and the consumed count is the number of tickets for the same pair
    already in `ACCEPTED` or `PAID`. When the quota is positive and not yet
    fully consumed, the ticket's `pricing_variant` is `NEEDS_BASED` and its
    `quoted_price_cents` is 50% of the title's `list_price_cents` rounded
    half-up — a flat half of new list regardless of condition. Otherwise the
    variant is `WHOLESALE` and the quoted price is the `price_cents` of the
    unique wholesale quote for the title and declared condition whose half-open
    window contains now."

    Design: Difficulty/boundary_precision_check/buyback_quota_equality_boundary
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=2, isbn="9780000000010"
    )
    student_id = base["student"]["id"]

    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    tk1 = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id
    )
    assert tk1["pricing_variant"] == "NEEDS_BASED"
    accept_buyback_ticket(tk1["id"], student_id)

    title = get_success_data(api.get_title(title["id"], MANAGER))
    tk2 = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id
    )
    assert tk2["pricing_variant"] == "NEEDS_BASED"
    accept_buyback_ticket(tk2["id"], student_id)

    title = get_success_data(api.get_title(title["id"], MANAGER))
    tk3 = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id
    )
    # accepted_count 2 == quota 2: the equality case flips to wholesale.
    assert tk3["pricing_variant"] == "WHOLESALE"
    assert tk3["quoted_price_cents"] == 2200


def test_buyback_reject_from_accepted_compensates(api):
    """PRD §3.9: "Alternatively, a manager rejects a ticket: from `QUOTED` this
    simply lands in terminal `REJECTED` with an optional `reason`, but from
    `ACCEPTED` — the intake condition-mismatch case — rejection compensates: the
    title's `used_stock_qty` is decremented by one, the demand quota consumption
    is released, and the ticket lands in `REJECTED`."

    Design: Corner/state_machines/buyback_reject_from_accepted_compensates
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=1, isbn="9780000001006"
    )
    student_id = base["student"]["id"]

    tk = create_buyback_ticket(
        base["title"]["id"], base["t2"]["id"], base["title"]["version"],
        student_id,
    )
    accept_buyback_ticket(tk["id"], student_id)
    title_after_accept = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title_after_accept["used_stock_qty"] == 1

    rejected = validate_success(
        api.reject_buyback_ticket(tk["id"], {"reason": "water damage"}, MANAGER)
    )
    assert rejected["status"] == "REJECTED"

    title_after_reject = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title_after_reject["used_stock_qty"] == 0

    # The released quota unit lets the next ticket price NEEDS_BASED again.
    tk2 = create_buyback_ticket(
        base["title"]["id"], base["t2"]["id"], title_after_reject["version"],
        student_id,
    )
    assert tk2["pricing_variant"] == "NEEDS_BASED"


def test_wholesale_missing_when_no_quote(api):
    """PRD §3.9: "Otherwise the variant is `WHOLESALE` and the quoted price is
    the `price_cents` of the unique wholesale quote for the title and declared
    condition whose half-open window contains now; if no such quote exists,
    creation fails with `ERR_WHOLESALE_QUOTE_MISSING`."

    Design: Corner/errors/wholesale_missing_when_no_quote
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=0, with_wholesale_quote=False,
        isbn="9780000001015",
    )
    resp = api.create_buyback_ticket(
        {
            "title_id": base["title"]["id"],
            "condition": "GOOD",
            "upcoming_term_id": base["t2"]["id"],
            "expected_title_version": base["title"]["version"],
        },
        make_student_headers(base["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WHOLESALE_QUOTE_MISSING)

    # No ticket persisted: the title's version is untouched.
    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title["version"] == base["title"]["version"]


def test_occ_buyback_create_stale_title_rejected(api):
    """PRD §2.7: "Creating a buyback ticket requires `expected_title_version`
    matching the title's current `version`. Needs-based versus wholesale
    variant selection depends on demand-quota consumption and stock movements,
    both of which advance the title's `version`."

    Design: Corner/cross_cutting_layers/occ_buyback_create_stale_title_rejected
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=2, isbn="9780000001021"
    )
    student_headers = make_student_headers(base["student"]["id"])

    tk1 = create_buyback_ticket(
        base["title"]["id"], base["t2"]["id"], base["title"]["version"],
        base["student"]["id"],
    )
    assert tk1["status"] == "QUOTED"

    resp = api.create_buyback_ticket(
        {
            "title_id": base["title"]["id"],
            "condition": "GOOD",
            "upcoming_term_id": base["t2"]["id"],
            "expected_title_version": base["title"]["version"],
        },
        student_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_used_stock_conservation_buyback_sale_return(api):
    """PRD §3.6: "Placement decrements stock: a `NEW` line reduces
    `new_stock_qty`, a `USED` line reduces `used_stock_qty`, a `RENTAL` line
    reduces `rental_stock_qty`, and `DIGITAL` touches no stock counter."
    PRD §3.7: "Restocking mirrors placement: a returned `NEW` line adds `qty`
    back to the title's `new_stock_qty`, `USED` to `used_stock_qty`, `RENTAL`
    to `rental_stock_qty`, and `DIGITAL` restocks nothing."
    PRD §3.9: "Acceptance consumes one unit of the demand quota (the
    accepted/paid count increments), adds one to the title's `used_stock_qty`
    with a title `version` bump, and moves the ticket to `ACCEPTED`."

    Design: Difficulty/compensating_invariant/used_stock_conservation_buyback_sale_return
    """
    from test_helpers import (
        CLOCK_AT_CENSUS,
        CLOCK_IN_BUYBACK_WINDOW,
        create_approved_adoption,
        create_faculty,
        create_publisher_with_agreement,
        create_section,
        create_student,
        create_term,
        create_spring_term,
        create_title,
        drive_term_to_buyback_open,
        drive_term_to_sales_open,
        get_first_order_line,
        open_section,
        open_term_adoption,
        place_order,
        reset_clock,
        set_clock,
    )

    reset_clock()
    t1 = create_term()
    t2 = create_spring_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000014", has_rental=False, has_digital=False,
        initial_used_stock_qty=1,
    )
    faculty = create_faculty()
    student = create_student()
    sec1 = create_section(t1["id"], faculty["id"])
    sec2 = create_section(t2["id"], faculty["id"])
    open_term_adoption(t1["id"])
    open_term_adoption(t2["id"])
    opened1 = open_section(sec1["id"])
    opened2 = open_section(sec2["id"])
    # Demand quota 1 for the upcoming term.
    create_approved_adoption(
        sec2["id"], title["id"], faculty["id"], opened2["version"],
        qty_used=1, posted_price_cents=9000,
    )
    ado1 = create_approved_adoption(
        sec1["id"], title["id"], faculty["id"], opened1["version"],
        qty_used=1, posted_price_cents=8000,
    )
    drive_term_to_sales_open(t1["id"])
    set_clock("2026-08-20T00:00:00Z")

    # Forward: the used sale takes stock 1 -> 0.
    order = place_order(
        t1["id"], student["id"],
        [{"adoption_id": ado1["id"], "format": "USED", "qty": 1}],
    )
    title = get_success_data(api.get_title(title["id"], MANAGER))
    assert title["used_stock_qty"] == 0

    # Compensating: the return takes stock 0 -> 1.
    line = get_first_order_line(order["id"])
    validate_success(
        api.return_order_line(
            order["id"], line["id"], {}, make_student_headers(student["id"])
        )
    )
    title = get_success_data(api.get_title(title["id"], MANAGER))
    assert title["used_stock_qty"] == 1

    drive_term_to_buyback_open(t1["id"], census_clock=CLOCK_AT_CENSUS)
    set_clock(CLOCK_IN_BUYBACK_WINDOW)

    # The buyback accept adds exactly one unit.
    tk = create_buyback_ticket(
        title["id"], t2["id"], title["version"], student["id"]
    )
    assert tk["pricing_variant"] == "NEEDS_BASED"
    assert tk["quoted_price_cents"] == 5000
    accept_buyback_ticket(tk["id"], student["id"])
    title = get_success_data(api.get_title(title["id"], MANAGER))
    assert title["used_stock_qty"] == 2


def test_buyback_needs_based_price_is_condition_independent(api):
    """PRD §3.9: "When the quota is positive and not yet fully consumed, the
    ticket's `pricing_variant` is `NEEDS_BASED` and its `quoted_price_cents` is
    50% of the title's `list_price_cents` rounded half-up — a flat half of new
    list regardless of condition."

    Design: Difficulty/dual_variant_calc/buyback_needs_vs_wholesale_same_copy
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=3, isbn="9780000000040"
    )
    student_id = base["student"]["id"]

    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    tk_like_new = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id,
        condition="LIKE_NEW",
    )
    assert tk_like_new["pricing_variant"] == "NEEDS_BASED"
    assert tk_like_new["quoted_price_cents"] == 5000

    title = get_success_data(api.get_title(title["id"], MANAGER))
    tk_acceptable = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id,
        condition="ACCEPTABLE",
    )
    # Same flat half-of-list price even for the lowest condition grade.
    assert tk_acceptable["pricing_variant"] == "NEEDS_BASED"
    assert tk_acceptable["quoted_price_cents"] == 5000


def test_buyback_quota_counts_only_accepted_and_paid(api):
    """PRD §3.9: "The demand quota for a title and upcoming term is the sum of
    `qty_used_requested` over the `APPROVED` adoptions of that title in that
    term, and the consumed count is the number of tickets for the same pair
    already in `ACCEPTED` or `PAID`. When the quota is positive and not yet
    fully consumed, the ticket's `pricing_variant` is `NEEDS_BASED` and its
    `quoted_price_cents` is 50% of the title's `list_price_cents` rounded
    half-up — a flat half of new list regardless of condition."

    Design: Difficulty/boundary_precision_check/buyback_quota_equality_boundary
    """
    base = setup_buyback_open_with_demand(
        qty_used_requested=1, isbn="9780000000041"
    )
    student_id = base["student"]["id"]

    # A QUOTED ticket does not consume the quota: the next ticket for the
    # same pair still prices NEEDS_BASED (consumed count is still 0 < 1).
    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    tk1 = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id
    )
    assert tk1["status"] == "QUOTED"

    title = get_success_data(api.get_title(title["id"], MANAGER))
    tk2 = create_buyback_ticket(
        title["id"], base["t2"]["id"], title["version"], student_id
    )
    assert tk2["pricing_variant"] == "NEEDS_BASED"
    assert tk2["quoted_price_cents"] == 5000


def test_used_stock_sale_and_return_qty_weighted(api):
    """PRD §3.6: "Placement decrements stock: a `NEW` line reduces
    `new_stock_qty`, a `USED` line reduces `used_stock_qty`, a `RENTAL` line
    reduces `rental_stock_qty`, and `DIGITAL` touches no stock counter."
    PRD §3.7: "Restocking mirrors placement: a returned `NEW` line adds `qty`
    back to the title's `new_stock_qty`, `USED` to `used_stock_qty`, `RENTAL`
    to `rental_stock_qty`, and `DIGITAL` restocks nothing."

    Design: Difficulty/compensating_invariant/used_stock_conservation_buyback_sale_return
    """
    from test_helpers import (
        get_first_order_line,
        place_order,
        setup_sales_open_with_approved_adoption,
    )

    base = setup_sales_open_with_approved_adoption(
        qty_used=2,
        posted_price_cents=8000,
        title_overrides={"initial_used_stock_qty": 2, "has_rental": False,
                         "has_digital": False},
        isbn="9780000000042",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 2}],
    )
    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title["used_stock_qty"] == 0

    line = get_first_order_line(order["id"])
    validate_success(
        api.return_order_line(
            order["id"], line["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title["used_stock_qty"] == 2
