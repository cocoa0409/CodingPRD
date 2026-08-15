"""Support packages: tier pricing with the repeat-client variant, pinned rounding
order, coverage-window overlap, credit application, and auto-depletion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_package,
    book_session_for_case,
    complete_session,
    get_family,
    get_package,
    make_parent_headers,
    purchase_package_for_case,
    purchase_package_payload,
    send_case_message,
    setup_case_in_planning,
    setup_case_with_package,
    setup_repeat_family_with_planning_case,
    validate_error,
)

ADMIN = TEST_USERS["practice_admin_headers"]


def test_package_price_new_client_pays_full_gross(api):
    """PRD §3.4: "The tier base is 29,900 cents for `BASIC`, 54,900 for `STANDARD`,
    and 89,900 for `PREMIUM`; when the case's age band is `NEWBORN`, a 4,950-cent
    newborn surcharge is added, and the sum is the `gross_price_cents`. A family that
    `is_repeat_client` at the moment of purchase earns a `repeat_discount_cents` of
    fifteen percent of the gross, rounded half up to whole cents first and then
    subtracted — the pinned order matters, since rounding after subtraction would
    give a different cent — while a first-time family's discount is zero."
    PRD §3.4: "The `net_price_cents` is the gross minus the repeat discount minus the
    applied credit, so two purchases of the same tier for the same age band price
    differently when one family is a repeat client."

    New client, STANDARD, NEWBORN child: gross = 54900 + 4950 = 59850, discount 0,
    net 59850.

    Design: Difficulty/dual_variant_calc/package_price_new_vs_repeat_client
    """
    bundle = setup_case_in_planning(child_birth_date="2026-05-01")
    case, family = bundle["case"], bundle["family"]
    package = purchase_package_for_case(
        case["id"], family, tier="STANDARD", kind="INITIAL", starts_on="2026-08-01"
    )
    assert_package(package)
    assert package["gross_price_cents"] == 59850
    assert package["repeat_discount_cents"] == 0
    assert package["net_price_cents"] == 59850


def test_package_price_repeat_client_gets_discount(api):
    """PRD §3.4: "A family that `is_repeat_client` at the moment of purchase earns a
    `repeat_discount_cents` of fifteen percent of the gross, rounded half up to whole
    cents first and then subtracted — the pinned order matters, since rounding after
    subtraction would give a different cent — while a first-time family's discount is
    zero."
    PRD §3.1: "the repeat flag later becomes true as soon as the family has at least
    one case in `COMPLETED` status, and it too is recomputed on every read and at
    case completion."

    Repeat client (a prior case COMPLETED), same STANDARD tier and NEWBORN band:
    gross 59850, discount round_half_up(59850 * 0.15) = 8978, net 50872 — the variant
    diverges solely on the repeat flag.

    Design: Difficulty/dual_variant_calc/package_price_new_vs_repeat_client
    """
    bundle = setup_repeat_family_with_planning_case(child_birth_date="2026-05-01")
    family, case2 = bundle["family"], bundle["case2"]
    assert get_family(family["id"])["is_repeat_client"] is True
    package = purchase_package_for_case(
        case2["id"], family, tier="STANDARD", kind="INITIAL", starts_on="2026-08-15"
    )
    assert package["gross_price_cents"] == 59850
    assert package["repeat_discount_cents"] == 8978, (
        f"round_half_up(59850 * 0.15) must be 8978, got {package['repeat_discount_cents']}"
    )
    assert package["net_price_cents"] == 50872


def test_package_discount_rounding_order_basic(api):
    """PRD §3.4: "A family that `is_repeat_client` at the moment of purchase earns a
    `repeat_discount_cents` of fifteen percent of the gross, rounded half up to whole
    cents first and then subtracted — the pinned order matters, since rounding after
    subtraction would give a different cent — while a first-time family's discount is
    zero."

    Repeat client, BASIC, NEWBORN: gross = 29900 + 4950 = 34850; the discount is
    rounded half up FIRST — round_half_up(34850 * 0.15) = round_half_up(5227.5) =
    5228 — then subtracted: net = 34850 - 5228 = 29622 (not 29623).

    Design: Difficulty/combinatorial_formula/package_discount_rounding_order
    """
    bundle = setup_repeat_family_with_planning_case(child_birth_date="2026-05-01")
    family, case2 = bundle["family"], bundle["case2"]
    package = purchase_package_for_case(
        case2["id"], family, tier="BASIC", kind="INITIAL", starts_on="2026-08-15"
    )
    assert package["gross_price_cents"] == 34850
    assert package["repeat_discount_cents"] == 5228, (
        f"discount must be rounded half-up before subtraction (5228), got "
        f"{package['repeat_discount_cents']}"
    )
    assert package["net_price_cents"] == 29622


def test_package_discount_rounding_order_premium(api):
    """PRD §3.4: "A family that `is_repeat_client` at the moment of purchase earns a
    `repeat_discount_cents` of fifteen percent of the gross, rounded half up to whole
    cents first and then subtracted — the pinned order matters, since rounding after
    subtraction would give a different cent — while a first-time family's discount is
    zero."

    Repeat client, PREMIUM, NEWBORN: gross = 89900 + 4950 = 94850; discount =
    round_half_up(94850 * 0.15) = round_half_up(14227.5) = 14228; net = 80622 — a
    second half-up rounding checkpoint on a different tier.

    Design: Difficulty/combinatorial_formula/package_discount_rounding_order
    """
    bundle = setup_repeat_family_with_planning_case(child_birth_date="2026-05-01")
    family, case2 = bundle["family"], bundle["case2"]
    package = purchase_package_for_case(
        case2["id"], family, tier="PREMIUM", kind="INITIAL", starts_on="2026-08-15"
    )
    assert package["gross_price_cents"] == 94850
    assert package["repeat_discount_cents"] == 14228
    assert package["net_price_cents"] == 80622


def test_clock_default_purchased_at(api):
    """PRD §2.5: "At startup the clock reads exactly 2026-08-01T00:00:00Z, and it
    never silently falls back to the host's real time."
    PRD §3.4: "The purchase is stamped `purchased_at` from the logical clock, and the
    package begins `ACTIVE`."
    PRD §3.4: "Coverage is a closed date interval: `expires_on` falls one day before
    the date `duration_weeks` weeks after `starts_on`, so both `starts_on` and
    `expires_on` are inside the coverage window."

    No clock-set call is ever made; BASIC runs two weeks, so starts_on 2026-08-01
    yields expires_on 2026-08-14.

    Design: Corner/entities/clock_default_purchased_at
    """
    bundle = setup_case_in_planning(child_birth_date="2026-05-01")
    package = purchase_package_for_case(
        bundle["case"]["id"], bundle["family"], tier="BASIC", starts_on="2026-08-01"
    )
    assert package["purchased_at"].startswith("2026-08-01T00:00:00"), (
        f"purchased_at must be the startup logical clock, got {package['purchased_at']}"
    )
    assert package["expires_on"] == "2026-08-14"
    assert package["status"] == "ACTIVE"


def test_credit_application_over_balance_rejected(api):
    """PRD §3.4: "The requested `apply_credit_cents` becomes the
    `credit_applied_cents`, and it must lie between zero and the smaller of the
    family's current `credit_balance_cents` and the gross-minus-discount remainder;
    anything else is rejected with `ERR_INVALID_REQUEST`, and the applied amount is
    debited from the family's balance at purchase."

    The family's balance is zero, so a 500-cent application is out of range.

    Design: Corner/validations/credit_application_over_balance_rejected
    """
    bundle = setup_case_in_planning(child_birth_date="2026-05-01")
    case, family = bundle["case"], bundle["family"]
    assert get_family(family["id"])["credit_balance_cents"] == 0
    res = api.purchase_package(
        case["id"],
        purchase_package_payload(
            tier="BASIC", kind="INITIAL", starts_on="2026-08-01", apply_credit_cents=500
        ),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    assert get_family(family["id"])["credit_balance_cents"] == 0


def test_package_depleted_auto_transition(api):
    """PRD §3.4: "Whenever a consumption leaves both `remaining_calls` and
    `remaining_messages` at zero, the package moves from `ACTIVE` to `DEPLETED` and
    its `version` increments."
    PRD §3.7: "The assigned consultant marks a session completed, which requires it
    to be `SCHEDULED` — anything else is rejected with `ERR_SESSION_INVALID_STATE` —
    and moves it to `COMPLETED`; the call entitlement stays consumed, with no release
    on completion."
    PRD §3.7: "A successful booking creates the session `SCHEDULED`, consumes one
    call entitlement (the package's `remaining_calls` drops by one), increments the
    package `version` by one, and re-evaluates depletion."

    BASIC (1 call, 5 messages): book + complete the call, then send 5 messages.

    Design: Corner/state_machines/package_depleted_auto_transition
    """
    bundle = setup_case_with_package(tier="BASIC", starts_on="2026-08-01")
    case, family, consultant, package = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["package"],
    )
    version_at_creation = package["version"]

    session = book_session_for_case(
        case["id"], package["id"], make_parent_headers(family["id"]),
        session_type="REGRESSION",
        scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T11:00:00Z",
    )
    complete_session(session["id"], consultant)
    mid = get_package(package["id"])
    assert mid["remaining_calls"] == 0, "completion keeps the call consumed"
    assert mid["status"] == "ACTIVE", "messages remain, so no DEPLETED transition yet"

    for i in range(5):
        send_case_message(case["id"], family, body=f"m{i + 1}")

    final = get_package(package["id"])
    assert final["remaining_calls"] == 0 and final["remaining_messages"] == 0
    assert final["status"] == "DEPLETED", (
        f"both entitlements at zero must flip the package to DEPLETED, got {final['status']}"
    )
    # Pinned increments: booking (+1) and the DEPLETED transition (+1).
    assert final["version"] >= version_at_creation + 2, (
        f"version {final['version']} must have advanced past {version_at_creation}"
    )


def test_package_closed_interval_touching_boundary_conflicts(api):
    """PRD §3.4: "An `INITIAL` purchase must not double-cover the case: its closed
    coverage interval conflicts with any other `ACTIVE` package of the case unless
    the new interval ends entirely before the existing one begins or begins entirely
    after the existing one ends. Touching boundaries do conflict — a new `starts_on`
    equal to an existing package's `expires_on` overlaps on that shared date — and a
    conflicting purchase is rejected with `ERR_PACKAGE_WINDOW_OVERLAP`."

    Existing package P1 covers the closed interval [2026-08-01, 2026-08-14]; a new
    package starting 2026-08-14 shares that date (conflict), while 2026-08-15 begins
    entirely after (allowed).

    Design: Difficulty/resource_temporal_overlap/package_closed_interval_overlap
    """
    bundle = setup_case_in_planning(child_birth_date="2026-05-01")
    case, family = bundle["case"], bundle["family"]
    p1 = purchase_package_for_case(case["id"], family, tier="BASIC", starts_on="2026-08-01")
    assert p1["expires_on"] == "2026-08-14"

    res = api.purchase_package(
        case["id"],
        purchase_package_payload(tier="BASIC", kind="INITIAL", starts_on="2026-08-14"),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PACKAGE_WINDOW_OVERLAP.value, expected_status=409)

    p2 = purchase_package_for_case(case["id"], family, tier="BASIC", starts_on="2026-08-15")
    assert p2["starts_on"] == "2026-08-15"
    assert p2["expires_on"] == "2026-08-28"
    assert get_package(p1["id"])["status"] == "ACTIVE"
    assert get_package(p2["id"])["status"] == "ACTIVE"


def test_package_closed_interval_left_disjoint_allowed_right_touch_conflicts(api):
    """PRD §3.4: "An `INITIAL` purchase must not double-cover the case: its closed
    coverage interval conflicts with any other `ACTIVE` package of the case unless
    the new interval ends entirely before the existing one begins or begins entirely
    after the existing one ends. Touching boundaries do conflict — a new `starts_on`
    equal to an existing package's `expires_on` overlaps on that shared date — and a
    conflicting purchase is rejected with `ERR_PACKAGE_WINDOW_OVERLAP`."

    Existing package P1 covers [2026-08-15, 2026-08-28]. A new package covering
    [2026-08-01, 2026-08-14] ends entirely before P1 begins (allowed); one starting
    on 2026-08-28 touches P1's expires_on (conflict).

    Design: Difficulty/resource_temporal_overlap/package_closed_interval_overlap
    """
    bundle = setup_case_in_planning(child_birth_date="2026-05-01")
    case, family = bundle["case"], bundle["family"]
    p1 = purchase_package_for_case(case["id"], family, tier="BASIC", starts_on="2026-08-15")
    assert p1["expires_on"] == "2026-08-28"

    p2 = purchase_package_for_case(case["id"], family, tier="BASIC", starts_on="2026-08-01")
    assert p2["expires_on"] == "2026-08-14", "ends entirely before P1 begins: disjoint"
    assert p2["status"] == "ACTIVE"

    res = api.purchase_package(
        case["id"],
        purchase_package_payload(tier="BASIC", kind="INITIAL", starts_on="2026-08-28"),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PACKAGE_WINDOW_OVERLAP.value, expected_status=409)
