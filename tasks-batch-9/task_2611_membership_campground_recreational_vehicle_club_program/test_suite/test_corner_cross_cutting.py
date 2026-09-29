"""Optimistic concurrency tokens and the dues ageing thresholds from both sides."""

from test_helpers import (
    ADMIN,
    assert_membership_axes,
    build_user_headers,
    create_classic_tier,
    create_member,
    create_park,
    list_invoices,
    make_capital_decision_payload,
    make_park_manager_headers,
    make_payment_payload,
    make_transfer_request_payload,
    open_park,
    propose_project,
    read_invoice,
    read_membership,
    read_park,
    read_project,
    reset_clock,
    run_delinquency_sweep,
    sell_membership_to_new_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_dues_payment_invalidates_the_version_a_transfer_pinned(api):
    """The token goes stale on an unrelated axis, so no state precondition would object.

    PRD §2.7: "If that value does not equal the membership's current `version`, the
    submission is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412). The
    product reason is that a great deal can legitimately have moved the membership
    since the client read it: a prior transfer request may have just been decided, a
    dues payment may have advanced `dues_paid_through`, or a reservation may have
    shifted the entitlement counters."

    Design: Corner/cross_cutting_complexity_layers/transfer_submission_requires_the_membership_version_the_client_actually_read
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    stale_version = read_membership(api, holder["membership_id"])["version"]
    assert stale_version == 1, "the sale is the membership's first write"

    settled = validate_success(
        api.pay_dues_invoice(holder["invoice_id"], make_payment_payload(45360), holder["headers"]),
        200,
    )
    assert settled["status"] == "PAID"

    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                holder["membership_id"], receiver["id"], "GIFT", stale_version
            ),
            holder["headers"],
        ),
        "ERR_STALE_MEMBERSHIP_VERSION",
        412,
    )
    refused = read_membership(api, holder["membership_id"])
    # Nothing about the transfer itself is wrong here: the contract is ACTIVE and
    # its dues are CURRENT, so only the version test can be doing the refusing.
    assert_membership_axes(refused, "ACTIVE", "CURRENT")
    assert refused["version"] == 2, "the accepted payment bumped it once; the refusal not at all"

    accepted = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                holder["membership_id"], receiver["id"], "GIFT", refused["version"]
            ),
            holder["headers"],
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["transfer_fee_cents"] == 30000
    final = read_membership(api, holder["membership_id"])
    assert final["membership_status"] == "TRANSFER_PENDING"
    assert final["version"] == 3, "every accepted write increments by exactly 1, with no gaps"


def test_an_inspection_invalidates_the_park_version_a_capital_decision_pinned(api):
    """The stale token reports even when the same call is also a self-decision.

    PRD §2.7: "A mismatch with the park's current `version` is rejected with
    `ERR_STALE_PARK_VERSION` (HTTP 412). A funding decision is only meaningful
    against the park state that produced the project's `priority_score`, and an
    intervening amenity inspection, satisfaction survey, maintenance cascade or
    sibling funding decision changes that score; rejecting the stale decision forces
    the approver to re-read and re-judge."

    Design: Corner/cross_cutting_complexity_layers/capital_decision_requires_the_park_version_that_produced_the_score
    """
    reset_clock(api)
    park = create_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    assert open_park(api, park["id"])["park_status"] == "OPEN"
    manager = make_park_manager_headers(park["id"])
    project = propose_project(
        api,
        park["id"],
        manager,
        title="Sable Creek bathhouse rebuild",
        category="SAFETY",
        requested_cost_cents=3000000,
        fiscal_year=2027,
    )
    assert project["status"] == "PROPOSED"
    # 1.40 category x 1.00 compliant x (1 + 1.50 gap) x 1.0000 usage x 1.20 cost.
    assert project["priority_score"] == 4200
    stale_version = read_park(api, park["id"])["version"]

    inspection = validate_success(
        api.file_amenity_inspection(
            park["id"],
            {"restroom_score": 2, "hookup_score": 2, "utility_score": 2, "road_score": 2},
            manager,
        ),
        201,
    )
    assert inspection["composite_score"] == 2.00
    assert inspection["result"] == "FAIL"
    inspected = read_park(api, park["id"])
    assert inspected["amenity_compliance_status"] == "NON_COMPLIANT"
    assert inspected["version"] == stale_version + 1, "the inspection is what aged the token"

    validate_error(
        api.decide_capital_project(
            project["id"], make_capital_decision_payload("APPROVE", stale_version), ADMIN
        ),
        "ERR_STALE_PARK_VERSION",
        412,
    )
    # The proposer deciding its own project also breaks segregation of duties at
    # priority 41, yet the version test at priority 18 is reached first.
    validate_error(
        api.decide_capital_project(
            project["id"],
            make_capital_decision_payload("APPROVE", stale_version),
            build_user_headers(park["id"], "ClubAdmin"),
        ),
        "ERR_STALE_PARK_VERSION",
        412,
    )
    mid = read_project(api, project["id"])
    assert mid["status"] == "PROPOSED", "a refused decision writes nothing"
    assert mid["priority_score"] == 5460, (
        "the inspection re-scored the project, so the stale view really was superseded"
    )
    assert read_park(api, park["id"])["version"] == stale_version + 1

    approved = validate_success(
        api.decide_capital_project(
            project["id"],
            make_capital_decision_payload("APPROVE", stale_version + 1),
            ADMIN,
        ),
        200,
    )
    assert approved["status"] == "APPROVED", "a SAFETY project may be funded at a failing park"
    assert read_park(api, park["id"])["version"] == stale_version + 2


def test_one_sweep_lands_six_memberships_on_the_three_ageing_bands(api):
    """Every dues threshold is pinned from both sides inside a single sweep.

    PRD §3.7: "A membership with an `OPEN` or `PAST_DUE` invoice whose
    `days_past_due` is at least 1 and below 30 moves from `CURRENT` to `GRACE`. A
    membership whose invoice has reached at least 30 days past due but is still
    below 120 moves to `DELINQUENT`, whether it arrives from `CURRENT` or from
    `GRACE`; a membership can therefore reach `DELINQUENT` having never been
    observed in `GRACE`, simply because no sweep happened to run while it sat inside
    the grace band. A membership already `DELINQUENT` whose `PAST_DUE` invoice has
    reached 120 days past due moves to `WRITTEN_OFF`, and the invoice itself moves to
    `WRITTEN_OFF`; both are terminal."

    Design: Corner/cross_cutting_complexity_layers/one_delinquency_sweep_lands_six_memberships_on_five_different_outcomes
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    sold = {}
    # The sweep instant is fixed; the sale dates are staggered instead, so the six
    # invoices are 120, 119, 30, 29, 1 and 0 days past due in the one pass.
    for label, sale_date, full_name, email in (
        ("write_off", "2026-04-08", "Dana Whitlock", "dana.whitlock@example.com"),
        ("just_short_of_write_off", "2026-04-09", "Nathan Boyle", "nathan.boyle@example.com"),
        ("at_delinquent", "2026-07-07", "Priya Raman", "priya.raman@example.com"),
        ("just_short_of_delinquent", "2026-07-08", "Owen Deleon", "owen.deleon@example.com"),
        ("at_grace", "2026-08-05", "Sofia Marquez", "sofia.marquez@example.com"),
        ("due_today", "2026-08-06", "Terrence Ives", "terrence.ives@example.com"),
    ):
        set_clock(api, sale_date)
        sold[label] = sell_membership_to_new_member(
            api,
            tier["id"],
            member_overrides={"full_name": full_name, "email": email},
        )
    # DUES_NET_DAYS of 30 fixes each due date at its sale date plus 30 days.
    assert read_invoice(api, sold["write_off"]["invoice_id"])["due_date"] == "2026-05-08"
    assert read_invoice(api, sold["at_delinquent"]["invoice_id"])["due_date"] == "2026-08-06"
    assert read_invoice(api, sold["due_today"]["invoice_id"])["due_date"] == "2026-09-05"

    result = run_delinquency_sweep(api, at_instant="2026-09-05")

    assert result["invoices_swept"] == 6
    assert result["memberships_to_grace"] == 2
    assert result["memberships_written_off"] == 1

    written_off_invoice = read_invoice(api, sold["write_off"]["invoice_id"])
    assert written_off_invoice["days_past_due"] == 120
    assert written_off_invoice["status"] == "WRITTEN_OFF"
    # ceil(120 / 30) is 4 months: round_half_up(45360 x 0.015 x 4) = 2722.
    assert written_off_invoice["late_fee_cents"] == 2722
    written_off = read_membership(api, sold["write_off"]["membership_id"])
    assert_membership_axes(written_off, "TERMINATED", "WRITTEN_OFF")

    near_miss_invoice = read_invoice(api, sold["just_short_of_write_off"]["invoice_id"])
    assert near_miss_invoice["days_past_due"] == 119
    assert near_miss_invoice["status"] == "PAST_DUE"
    assert near_miss_invoice["late_fee_cents"] == 2722, (
        "ceil(119 / 30) is also 4, so the write-off edge is a day count, not a fee level"
    )
    near_miss = read_membership(api, sold["just_short_of_write_off"]["membership_id"])
    assert_membership_axes(
        near_miss, "SUSPENDED", "DELINQUENT", suspension_reason="DUES_DELINQUENCY"
    )

    at_delinquent_invoice = read_invoice(api, sold["at_delinquent"]["invoice_id"])
    assert at_delinquent_invoice["days_past_due"] == 30
    # ceil(30 / 30) is one month, not two: round_half_up(45360 x 0.015) = 680.
    assert at_delinquent_invoice["late_fee_cents"] == 680
    at_delinquent = read_membership(api, sold["at_delinquent"]["membership_id"])
    assert_membership_axes(
        at_delinquent, "SUSPENDED", "DELINQUENT", suspension_reason="DUES_DELINQUENCY"
    )

    below_delinquent_invoice = read_invoice(api, sold["just_short_of_delinquent"]["invoice_id"])
    assert below_delinquent_invoice["days_past_due"] == 29
    assert below_delinquent_invoice["late_fee_cents"] == 680
    below_delinquent = read_membership(api, sold["just_short_of_delinquent"]["membership_id"])
    assert_membership_axes(below_delinquent, "ACTIVE", "GRACE", suspension_reason=None)
    assert below_delinquent["dues_balance_cents"] == 46040, "45360 of dues plus the 680 fee"

    at_grace_invoice = read_invoice(api, sold["at_grace"]["invoice_id"])
    assert at_grace_invoice["days_past_due"] == 1
    assert at_grace_invoice["late_fee_cents"] == 680, "one day late is already one month late"
    at_grace = read_membership(api, sold["at_grace"]["membership_id"])
    assert_membership_axes(at_grace, "ACTIVE", "GRACE", suspension_reason=None)
    assert at_grace["dues_balance_cents"] == 46040

    due_today_invoice = read_invoice(api, sold["due_today"]["invoice_id"])
    assert due_today_invoice["days_past_due"] == 0
    assert due_today_invoice["status"] == "OPEN"
    assert due_today_invoice["late_fee_cents"] == 0
    due_today = read_membership(api, sold["due_today"]["membership_id"])
    assert_membership_axes(due_today, "ACTIVE", "CURRENT")
    assert due_today["dues_balance_cents"] == 45360
    assert due_today["version"] == 1, "a row merely due today is not rewritten at all"

    graced_rows, graced_meta = validate_paginated(
        api.list_memberships(ADMIN, {"dues_status": "GRACE"})
    )
    assert graced_meta["total_count"] == 2
    assert {row["id"] for row in graced_rows} == {
        sold["just_short_of_delinquent"]["membership_id"],
        sold["at_grace"]["membership_id"],
    }


def test_a_cured_invoice_stops_accruing_and_later_sweeps_add_nothing(api):
    """Two further sweeps 40 and 80 days on leave the settled row untouched.

    PRD §3.7: "For every invoice whose `status` is `OPEN` or `PAST_DUE`, it
    recomputes `days_past_due` as the current logical date minus the invoice's
    `due_date` in whole days, floored at 0 so that an invoice not yet due reports 0."

    Design: Corner/cross_cutting_complexity_layers/cured_dues_reset_the_late_fee_clock_and_later_sweeps_add_nothing
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    assert read_invoice(api, holder["invoice_id"])["due_date"] == "2026-08-31"

    first_sweep = run_delinquency_sweep(api, at_instant="2026-09-29")
    assert first_sweep["memberships_to_grace"] == 1
    aged = read_invoice(api, holder["invoice_id"])
    assert aged["status"] == "PAST_DUE"
    assert aged["days_past_due"] == 29
    assert aged["late_fee_cents"] == 680, "ceil(29 / 30) is one month"
    assert_membership_axes(read_membership(api, holder["membership_id"]), "ACTIVE", "GRACE")

    cured_invoice = validate_success(
        api.pay_dues_invoice(holder["invoice_id"], make_payment_payload(46040), holder["headers"]),
        200,
    )
    assert cured_invoice["status"] == "PAID"
    assert cured_invoice["paid_amount_cents"] == 46040, "45360 of dues plus the 680 fee"
    cured = read_membership(api, holder["membership_id"])
    assert_membership_axes(cured, "ACTIVE", "CURRENT")
    assert cured["dues_balance_cents"] == 0
    assert cured["dues_paid_through"] == "2027-08-31", "the due date plus the 365-day cycle"

    second_sweep = run_delinquency_sweep(api, at_instant="2026-11-08")
    assert second_sweep["invoices_swept"] == 0, "a settled invoice is not in the sweep's input set"
    assert second_sweep["memberships_to_grace"] == 0
    resettled = read_invoice(api, holder["invoice_id"])
    assert resettled["status"] == "PAID"
    assert resettled["late_fee_cents"] == 680, (
        "69 days past the due date now, yet the fee did not move"
    )
    after_second = read_membership(api, holder["membership_id"])
    assert_membership_axes(after_second, "ACTIVE", "CURRENT")
    assert after_second["dues_balance_cents"] == 0
    assert after_second["version"] == cured["version"], "the untouched row was not rewritten"

    third_sweep = run_delinquency_sweep(api, at_instant="2026-12-18")
    assert third_sweep["invoices_swept"] == 0
    after_third = read_membership(api, holder["membership_id"])
    # 109 days past due on paper, past both the grace and the delinquency edges.
    assert_membership_axes(after_third, "ACTIVE", "CURRENT")
    assert after_third["dues_balance_cents"] == 0
    assert after_third["version"] == cured["version"]
    assert len(list_invoices(api, holder["membership_id"])) == 1, (
        "no sweep minted a replacement invoice; only the annual dues run issues the next cycle"
    )
