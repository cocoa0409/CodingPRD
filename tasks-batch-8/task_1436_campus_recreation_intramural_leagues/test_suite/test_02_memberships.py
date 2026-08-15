"""Membership pricing variants, proration rounding order, supersede, lazy
expiry, cancellation, and the member-version OCC guard (PRD §2.5, §3.1)."""
from test_helpers import (
    REC_ADMIN,
    ApiErrorId,
    api_client,
    create_eligible_member,
    create_member,
    create_membership_payload,
    create_pool,
    make_member_headers,
    purchase_membership,
    set_clock,
    sign_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_membership_full_variant_on_term_day_one():
    """PRD §3.1: "Purchasing within the first seven days of the term — day 1
    through day 7, inclusive — yields `pricing_variant` `FULL` and a
    `fee_cents` equal to the flat affiliation term fee."
    PRD §3.1: "Flat term fees are 6000 cents for `STUDENT`, 20000 cents for
    `FACULTY`, and 32000 cents for `COMMUNITY`."

    Design: Difficulty/dual_variant_calc/membership_full_vs_prorated_term_fee
    """
    set_clock("2026-08-24T00:00:00Z")  # FALL_2026 day 1
    member = create_member("fa@x.edu", full_name="Fac A",
                           affiliation="FACULTY")
    resp = api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "FALL_2026"),
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["pricing_variant"] == "FULL"
    assert data["fee_cents"] == 20000
    assert data["status"] == "ACTIVE"


def test_membership_prorated_variant_from_day_eight():
    """PRD §3.1: "Purchasing on day 8 or later yields `pricing_variant`
    `PRORATED`: the weekly rate is computed by dividing the affiliation term
    fee by the term's whole-week count (the term's inclusive day count divided
    by 7, rounded up) and rounding that weekly rate half-up to whole cents
    *first*; the remaining-week count is the number of days from the purchase
    date through the term end, inclusive, divided by 7 and rounded up;
    `fee_cents` is then the rounded weekly rate *multiplied* by the remaining
    weeks."

    Design: Difficulty/dual_variant_calc/membership_full_vs_prorated_term_fee
    """
    set_clock("2026-08-31T00:00:00Z")  # FALL_2026 day 8
    member = create_member("fb@x.edu", full_name="Fac B",
                           affiliation="FACULTY")
    resp = api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "FALL_2026"),
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["pricing_variant"] == "PRORATED"
    # weekly = round_half_up(20000/16) = 1250 FIRST; days_remaining = 103;
    # weeks = ceil(103/7) = 15 SECOND -> 1250 * 15.
    assert data["fee_cents"] == 18750
    assert data["fee_cents"] != 20000, (
        "the two pricing variants must disagree on identical term+affiliation"
    )


def test_membership_summer_proration_fee_rounds_weekly_first():
    """PRD §3.1: "Purchasing on day 8 or later yields `pricing_variant`
    `PRORATED`: the weekly rate is computed by dividing the affiliation term
    fee by the term's whole-week count (the term's inclusive day count divided
    by 7, rounded up) and rounding that weekly rate half-up to whole cents
    *first*; the remaining-week count is the number of days from the purchase
    date through the term end, inclusive, divided by 7 and rounded up;
    `fee_cents` is then the rounded weekly rate *multiplied* by the remaining
    weeks."
    PRD §3.1: "`SUMMER_2027` runs 2027-05-24 through 2027-08-06 (75 days,
    11 weeks)."

    Design: Difficulty/combinatorial_formula/membership_proration_weekly_rounding_order
    """
    set_clock("2027-06-07T00:00:00Z")  # SUMMER_2027 day 15
    member = create_member("ss@x.edu", full_name="Sum Stu",
                           affiliation="STUDENT")
    resp = api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "SUMMER_2027"),
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    # weekly = round_half_up(6000/11) = 545 FIRST; days_remaining = 61;
    # weeks = ceil(61/7) = 9 SECOND -> 545 * 9.
    assert data["fee_cents"] == 4905


def test_membership_summer_proration_variant_is_prorated():
    """PRD §3.1: "Purchasing on day 8 or later yields `pricing_variant`
    `PRORATED`."
    PRD §3.1: "This round-then-multiply order deliberately diverges from a
    naive daily-proration interpretation."

    Design: Difficulty/combinatorial_formula/membership_proration_weekly_rounding_order
    """
    set_clock("2027-06-07T00:00:00Z")
    member = create_member("ss@x.edu", full_name="Sum Stu",
                           affiliation="STUDENT")
    data = validate_success(api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "SUMMER_2027"),
        make_member_headers(member["id"]),
    ), 201)
    assert data["pricing_variant"] == "PRORATED"
    assert data["fee_cents"] != 4880, (
        "the naive day-ratio reading (6000 * 61/75) must not be produced"
    )


def test_checkout_rejected_after_membership_expiry():
    """PRD §2.9: "Each requires, in order: the member's `status` must be
    `ACTIVE` (a member under an injury hold is `SUSPENDED` and is rejected
    with `ERR_MEMBER_SUSPENDED`); the member must hold a waiver valid for the
    current academic year per §3.1 (otherwise `ERR_WAIVER_INVALID`); and the
    member must hold a membership whose lazily evaluated status is `ACTIVE`
    (otherwise `ERR_MEMBERSHIP_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_membership_state
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_eligible_member("mm@x.edu", full_name="Mem M")
    pool = create_pool()
    set_clock("2026-12-12T09:00:00Z")  # one day past the FALL_2026 term end
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-12-13T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    # The waiver (signed 2026-08-24) is still inside its academic year, so the
    # membership gate is what fires.
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_INACTIVE)


def test_membership_reads_expired_after_term_end_and_no_debit():
    """PRD §3.1: "Expiry is lazy: on every read of a membership and on every
    eligibility check, if the logical current date is after the term's end
    date, the membership is treated as `EXPIRED` — the term's end date itself
    is still inclusive-active."
    PRD §3.9: "`available_qty` starts equal to `total_qty`, and the pool
    maintains the invariant that `available_qty` plus the quantities of all
    checkouts still `OUT` equals `total_qty`."

    Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_membership_state
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    member = sign_waiver(member)
    membership = purchase_membership(member, "FALL_2026")
    pool = create_pool()
    set_clock("2026-12-12T09:00:00Z")
    resp = api_client.create_equipment_checkout(
        {"equipment_pool_id": pool["id"], "member_id": member["id"],
         "quantity": 1, "due_at": "2026-12-13T17:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_INACTIVE)
    data = validate_success(api_client.get_membership(
        membership["id"], REC_ADMIN))
    assert data["status"] == "EXPIRED", (
        "2026-12-12 is after the FALL_2026 end date 2026-12-11"
    )
    pool_after = validate_success(api_client.get_equipment_pool(
        pool["id"], REC_ADMIN))
    assert pool_after["available_qty"] == 5, (
        "the rejected checkout must not debit the pool"
    )


def test_membership_day7_boundary_stays_full():
    """PRD §3.1: "Purchasing within the first seven days of the term — day 1
    through day 7, inclusive — yields `pricing_variant` `FULL` and a
    `fee_cents` equal to the flat affiliation term fee."

    Design: Corner/calculations/membership_day7_boundary_full
    """
    set_clock("2026-08-30T00:00:00Z")  # FALL_2026 day 7 (inclusive bound)
    member = create_member("fb@x.edu", full_name="Fac B",
                           affiliation="FACULTY")
    data = validate_success(api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "FALL_2026"),
        make_member_headers(member["id"]),
    ), 201)
    assert data["pricing_variant"] == "FULL"
    assert data["fee_cents"] == 20000


def test_membership_supersede_backlink():
    """PRD §3.1: "If the member already has an `ACTIVE` membership, the new
    purchase is a create-with-supersede: the prior membership moves to
    `SUPERSEDED`, the new membership becomes the member's unique active one,
    and its `supersedes_membership_id` points at the superseded row. At most
    one membership per member is `ACTIVE` at any time; `SUPERSEDED`,
    `CANCELLED`, and `EXPIRED` are terminal."

    Design: Corner/entities/membership_supersede_backlink
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("ms@x.edu", full_name="Mem S")
    first = purchase_membership(member, "FALL_2026")
    set_clock("2026-08-31T00:00:00Z")  # day 8: the repurchase is PRORATED
    member = validate_success(api_client.get_member(member["id"], REC_ADMIN))
    second = validate_success(api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], "FALL_2026"),
        make_member_headers(member["id"]),
    ), 201)
    assert second["status"] == "ACTIVE"
    assert second["supersedes_membership_id"] == first["id"]
    # weekly = round_half_up(6000/16) = 375; weeks = ceil(103/7) = 15.
    assert second["fee_cents"] == 5625
    first_after = validate_success(api_client.get_membership(
        first["id"], REC_ADMIN))
    assert first_after["status"] == "SUPERSEDED"
    _, meta = validate_paginated(api_client.list_memberships(
        REC_ADMIN, params={"member_id": member["id"], "status": "ACTIVE"}))
    assert meta["total_count"] == 1, (
        "at most one ACTIVE membership per member"
    )


def test_membership_cancel_twice_returns_invalid_state():
    """PRD §3.1: "A membership addressed by its `membership_id` may be
    cancelled by its owning member or a `RecAdmin` while `ACTIVE`;
    cancellation transitions it to `CANCELLED`, issues no refund, and the
    member immediately loses membership-gated eligibility on subsequent checks
    (attempting to cancel a non-`ACTIVE` membership is `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/membership_cancel_twice_returns_invalid_state
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("mc@x.edu", full_name="Mem C")
    membership = purchase_membership(member, "FALL_2026")
    cancelled = validate_success(api_client.cancel_membership(
        membership["id"], make_member_headers(member["id"])))
    assert cancelled["status"] == "CANCELLED"
    resp = api_client.cancel_membership(
        membership["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_membership_stale_version():
    """PRD §2.5: "Purchasing a membership for a member must carry
    `expected_member_version` equal to the member's current `version`. Because
    purchasing supersedes any currently `ACTIVE` membership — legitimate
    renewal behavior — the guard exists so a client that priced the
    transaction against an older member aggregate (before a waiver
    re-signature or another purchase advanced the version) does not proceed on
    a stale read. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.5: "Mutations that ripple through a parent-child relationship bump
    the parent's `version` as well where this document says so — for example,
    signing a waiver, purchasing a membership, and paying a fine each
    increment the member's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_membership_stale_version
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    assert member["version"] == 1
    member = sign_waiver(member)
    assert member["version"] == 2
    # Stale observation (version 1, captured before the waiver signature).
    resp = api_client.create_membership(
        member["id"], create_membership_payload(1, "FALL_2026"),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # The current view succeeds — OCC rejects the stale view, not the operation.
    data = validate_success(api_client.create_membership(
        member["id"], create_membership_payload(2, "FALL_2026"),
        make_member_headers(member["id"]),
    ), 201)
    assert data["status"] == "ACTIVE"
    member_after = validate_success(api_client.get_member(
        member["id"], REC_ADMIN))
    assert member_after["version"] == 3
