"""Workshop enrollment: capacity boundary, waitlist promotion, billing
waterfall, and track/duplicate gates (PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    create_open_workshop,
    enroll,
    enroll_ok,
    make_family_headers,
    setup_active_plan_scenario,
    setup_capacity_workshop,
    setup_waitlist_workshop,
    validate_error,
    validate_success,
)


def test_enrollment_fills_to_capacity_then_waitlists(api, admin_headers):
    """PRD §3.10: "When a seat is free (`seats_taken` below `capacity`), the
    enrollment begins `ENROLLED`; otherwise it begins `WAITLISTED` with a
    `waitlist_position` assigned one-based among waitlisted entries by creation
    ascending, and a `billing_source` of `NONE` while it waits."

    Design: Difficulty/boundary_precision_check/workshop_capacity_exactly_full_boundary
    """
    ctx = setup_capacity_workshop(capacity=2)
    workshop, family = ctx["workshop"], ctx["family"]
    c1, c2, _c3 = ctx["clients"]

    e1 = enroll_ok(workshop["id"], c1["id"], family["id"])
    e2 = enroll_ok(workshop["id"], c2["id"], family["id"])
    assert e1["status"] == "ENROLLED"
    assert e2["status"] == "ENROLLED", "seats_taken 1 < capacity 2 at creation"

    workshop_after = validate_success(api.get_workshop(workshop["id"], admin_headers))
    assert workshop_after["seats_taken"] == 2


def test_third_enrollment_waitlisted_with_billing_none(api):
    """PRD §3.10: "When a seat is free (`seats_taken` below `capacity`), the
    enrollment begins `ENROLLED`; otherwise it begins `WAITLISTED` with a
    `waitlist_position` assigned one-based among waitlisted entries by creation
    ascending, and a `billing_source` of `NONE` while it waits."

    Design: Difficulty/boundary_precision_check/workshop_capacity_exactly_full_boundary
    """
    ctx = setup_capacity_workshop(capacity=2)
    workshop, family = ctx["workshop"], ctx["family"]
    c1, c2, c3 = ctx["clients"]
    enroll_ok(workshop["id"], c1["id"], family["id"])
    enroll_ok(workshop["id"], c2["id"], family["id"])

    # seats_taken == capacity: the boundary rejects the seat, not the enrollment.
    e3 = enroll_ok(workshop["id"], c3["id"], family["id"])
    assert e3["status"] == "WAITLISTED"
    assert e3["waitlist_position"] == 1
    assert e3["billing_source"] == "NONE"


def test_enrolled_drop_refunds_money(api, admin_headers):
    """PRD §3.10: "An enrolled drop refunds by source: a money-billed
    enrollment refunds `charged_cents` into the family's `total_refunded_cents`
    when the drop occurs no later than 7 days before the workshop's
    `window_start` — the boundary is inclusive — and refunds nothing inside
    that window"

    Design: Difficulty/transitive_cascade/enrollment_drop_promotion_cascade
    """
    ctx = setup_waitlist_workshop()
    enrollment_a = ctx["enrollment_a"]
    assert enrollment_a["status"] == "ENROLLED"
    assert ctx["enrollment_b"]["status"] == "WAITLISTED"
    assert ctx["enrollment_b"]["waitlist_position"] == 1

    # Drop at 2026-08-01, window_start 2026-09-05: 35 days before, inside the
    # full-refund window.
    fam_a_h = make_family_headers(ctx["A"]["family"]["id"])
    dropped = validate_success(api.drop_enrollment(enrollment_a["id"], fam_a_h))
    assert dropped["status"] == "DROPPED"

    family_a = validate_success(
        api.get_family(ctx["A"]["family"]["id"], admin_headers)
    )
    assert family_a["total_refunded_cents"] == 15000
    assert family_a["total_charged_cents"] == 15000
    assert family_a["outstanding_balance_cents"] == 0


def test_enrolled_drop_promotes_waitlist_head_and_charges(api, admin_headers):
    """PRD §3.10: "The drop decrements `seats_taken` by one and then promotes
    the waitlist: the earliest-created `WAITLISTED` enrollment moves to
    `ENROLLED`, its position clears, its billing is computed by the same
    waterfall, `seats_taken` rises by one, and positions recompute."
    PRD §3.10: "When no candidate exists, the enrollment bills in money:
    `billing_source` is `MONEY`, `charged_cents` equals the workshop's
    `price_cents`, and the amount is added to the family's
    `total_charged_cents`"

    Design: Difficulty/transitive_cascade/enrollment_drop_promotion_cascade
    """
    ctx = setup_waitlist_workshop()
    fam_a_h = make_family_headers(ctx["A"]["family"]["id"])
    validate_success(api.drop_enrollment(ctx["enrollment_a"]["id"], fam_a_h))

    enrollments = validate_success(
        api.list_enrollments(ctx["workshop"]["id"], admin_headers)
    )
    by_id = {e["id"]: e for e in enrollments}
    promoted = by_id[ctx["enrollment_b"]["id"]]
    assert promoted["status"] == "ENROLLED", "promotion cascade from the drop"
    assert promoted["billing_source"] == "MONEY"
    assert promoted["charged_cents"] == 15000
    assert promoted["waitlist_position"] is None

    family_b = validate_success(
        api.get_family(ctx["B"]["family"]["id"], admin_headers)
    )
    assert family_b["total_charged_cents"] == 15000, (
        "the charge is caused by the promotion, not by the drop directly"
    )

    workshop_after = validate_success(
        api.get_workshop(ctx["workshop"]["id"], admin_headers)
    )
    assert workshop_after["seats_taken"] == 1


def test_individual_track_enrollment_rejected(api):
    """PRD §3.10: "the family must be `ACTIVE` (`ERR_FAMILY_NOT_ACTIVE`), the
    client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`), and the client's track
    must be `GROUP` or `HYBRID` — an `INDIVIDUAL`-track student is rejected
    with `ERR_TRACK_MISMATCH`."

    Design: Corner/validations/individual_track_enrollment_rejected
    """
    ctx = setup_active_plan_scenario(account_name="Fam IT", primary_email="it@example.com")
    workshop = create_open_workshop(ctx["coach"]["id"], title="Track Lab",
                                    capacity=5, price_cents=1000)
    resp = enroll(workshop["id"], ctx["clients"][0]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_TRACK_MISMATCH)


def test_duplicate_enrollment_rejected(api):
    """PRD §3.10: "A duplicate — any existing non-terminal enrollment for the
    same workshop and client — is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam DE", primary_email="de@example.com", tracks=["HYBRID"]
    )
    workshop = create_open_workshop(ctx["coach"]["id"], title="Dup Lab",
                                    capacity=5, price_cents=1000)
    enroll_ok(workshop["id"], ctx["clients"][0]["id"], ctx["family"]["id"])
    resp = enroll(workshop["id"], ctx["clients"][0]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


def test_group_credit_selector_funds_enrollment(api, admin_headers):
    """PRD §3.10: "The system looks among the family's packages for one with
    track `GROUP`, status `ACTIVE`, and at least one credit remaining,
    preferring the package with the earliest `expires_at` and breaking ties
    toward the earliest created. When such a candidate exists, the enrollment's
    `billing_source` is `PACKAGE_CREDIT`, the package's `credits_consumed`
    rises by one with a status recompute, and `charged_cents` is zero."

    Design: Corner/calculations/group_credit_selector_funds_enrollment
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam GC",
        primary_email="gc@example.com",
        tracks=["HYBRID"],
        package={"track": "GROUP", "credits_total": 2},
    )
    family, client, coach = ctx["family"], ctx["clients"][0], ctx["coach"]
    package = ctx["packages"][0]
    workshop = create_open_workshop(coach["id"], title="Credit Lab", capacity=5,
                                    price_cents=9999)

    enrollment = enroll_ok(workshop["id"], client["id"], family["id"])
    assert enrollment["billing_source"] == "PACKAGE_CREDIT"
    assert enrollment["charged_cents"] == 0

    package_after = validate_success(api.get_package(package["id"], admin_headers))
    assert package_after["credits_consumed"] == 1
    assert package_after["credits_remaining"] == 1

    family_after = validate_success(api.get_family(family["id"], admin_headers))
    # GROUP 2 credits, one client: 2 x round(15000 x 0.6) + 2500 = 20500.
    assert family_after["total_charged_cents"] == 20500, (
        "the enrollment added nothing to the ledger"
    )
