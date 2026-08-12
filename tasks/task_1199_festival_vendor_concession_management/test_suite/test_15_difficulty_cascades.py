"""Difficulty: transitive_cascade — strike contagion depth-3; no-show cascade depth-4."""
from test_helpers import (
    TEST_USERS,
    accept_application,
    advance_festival,
    api_client,
    book_reservation,
    confirm_assignment,
    create_assignment,
    create_booth,
    create_festival,
    create_slot,
    create_vendor,
    create_zone,
    decide_application,
    get_application,
    get_assignment,
    get_booth,
    get_reservation,
    get_vendor,
    get_zone,
    issue_fine,
    make_vendor_headers,
    pay_fine,
    respond_fine,
    set_clock,
    setup_open_festival,
    start_review,
    submit_application,
    sweep_festival,
    validate_paginated,
    validate_success,
)

VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]


def _setup_strike_contagion():
    """F1 CURATED with vendor V's RESERVED assignment; two fines already PAID
    (strikes == 2); F2 APPLICATIONS_OPEN with V's application still SUBMITTED;
    a third fine issued and ACKNOWLEDGED on the F1 assignment."""
    f1 = setup_open_festival(name="Strike Fest 1")
    vendor = create_vendor(legal_name="Messy Moe LLC", contact_email="m@moe.com")
    app1 = submit_application(vendor, f1["festival"]["id"])
    start_review(app1["id"])
    app1 = accept_application(app1["id"], "FLAT_FEE", flat_fee_cents=50000)
    advance_festival(f1["festival"]["id"], "CURATED")
    booth = create_booth(f1["zone"]["id"])
    asg = create_assignment(app1["id"], booth["id"], power_draw_amps=20)

    for ftype in ("WASTE_SORTING", "GREASE_DISPOSAL"):
        fine = issue_fine(asg["id"], type=ftype, amount_cents=10000)
        respond_fine(fine["id"], vendor, "ACKNOWLEDGED")
        pay_fine(fine["id"])

    f2 = create_festival(name="Strike Fest 2", event_start="2026-08-01T12:00:00Z",
                         event_end="2026-08-02T23:00:00Z")
    create_zone(f2["id"], name="South")
    advance_festival(f2["id"], "APPLICATIONS_OPEN")
    app2 = submit_application(vendor, f2["id"])  # stays SUBMITTED (never reviewed)

    fine3 = issue_fine(asg["id"], type="COMPOST_CONTAMINATION", amount_cents=10000)
    respond_fine(fine3["id"], vendor, "ACKNOWLEDGED")
    return {"f1": f1, "f2": f2, "vendor": vendor, "app1": app1, "app2": app2,
            "assignment": asg, "fine3": fine3}


class TestStrikeContagionDepth3:
    def test_third_paid_fine_suspends_and_sweeps_pending_applications(self, api):
        """PRD §3.7: "When a vendor's strike count reaches 3 — exactly three
        suspends; the threshold is inclusive — the vendor moves to `SUSPENDED`,
        and in the same request every application of that vendor in `SUBMITTED`,
        `UNDER_REVIEW`, `CHANGES_REQUESTED`, or `WAITLISTED` is moved to
        `REJECTED` by strike contagion."

        Design: Difficulty/transitive_cascade/fine_payment_strike_contagion_depth3
        """
        scen = _setup_strike_contagion()
        paid = pay_fine(scen["fine3"]["id"])
        assert paid["status"] == "PAID", "link 1: fine paid"

        vendor = get_vendor(scen["vendor"]["id"])
        assert vendor["compliance_strikes"] == 3
        assert vendor["status"] == "SUSPENDED", "link 2: suspension fires exactly at >= 3"

        app2 = get_application(scen["app2"]["id"])
        assert app2["status"] == "REJECTED", "link 3: pending application in another festival swept"
        app1 = get_application(scen["app1"]["id"])
        assert app1["status"] == "ACCEPTED", "terminal applications are not swept"

    def test_two_paid_fines_stay_below_the_inclusive_threshold(self, api):
        """PRD §3.7: "A `FinanceLead` marks an `ACKNOWLEDGED` fine `PAID`, which
        increments the vendor's `compliance_strikes` by one."
        PRD §3.7: "exactly three suspends; the threshold is inclusive".

        Design: Difficulty/transitive_cascade/fine_payment_strike_contagion_depth3
        """
        scen = _setup_strike_contagion()  # two paid, third ACKNOWLEDGED but unpaid
        vendor = get_vendor(scen["vendor"]["id"])
        assert vendor["compliance_strikes"] == 2
        assert vendor["status"] == "APPROVED", "2 < 3: no suspension yet"
        assert get_application(scen["app2"]["id"])["status"] == "SUBMITTED", (
            "contagion has not fired below the threshold"
        )
        pay_fine(scen["fine3"]["id"])
        assert get_vendor(scen["vendor"]["id"])["status"] == "SUSPENDED"
        assert get_application(scen["app2"]["id"])["status"] == "REJECTED"


def _setup_noshow_cascade():
    """Festival CURATED: app A (FOOD_HOT, 30A) ACCEPTED with a CONFIRMED
    assignment on booth N-01; app B (FOOD_COLD, 40A) WAITLISTED; A holds a
    1-vehicle reservation in slot 08:00-11:00; clock moved past the grace
    boundary and past event_start."""
    base = setup_open_festival(name="NoShow Fest", zone_power=100, zone_water=1)
    fest_id = base["festival"]["id"]
    va = create_vendor(legal_name="Absent Annie", contact_email="a@annie.com")
    vb = create_vendor(legal_name="Backup Bob", contact_email="b@bob.com")
    appa = submit_application(va, fest_id, category="FOOD_HOT", power_needed_amps=30)
    appb = submit_application(vb, fest_id, category="FOOD_COLD", power_needed_amps=40,
                              proposed_flat_fee_cents=40000)
    start_review(appa["id"])
    accept_application(appa["id"], "FLAT_FEE", flat_fee_cents=50000)
    start_review(appb["id"])
    decide_application(appb["id"], "WAITLISTED")
    advance_festival(fest_id, "CURATED")
    booth = create_booth(base["zone"]["id"])
    asg_a = create_assignment(appa["id"], booth["id"], power_draw_amps=30)
    confirm_assignment(asg_a["id"])
    slot = create_slot(fest_id, window_start="2026-07-10T08:00:00Z",
                       window_end="2026-07-10T11:00:00Z", max_vehicles=10)
    res = book_reservation(asg_a["id"], slot["id"], vehicle_count=1)
    set_clock("2026-07-13T00:00:00Z")  # past grace AND past event_start
    return {**base, "va": va, "vb": vb, "appa": appa, "appb": appb,
            "booth": booth, "assignment": asg_a, "reservation": res}


class TestNoShowForfeitPromotionDepth4:
    def test_noshow_marks_and_forfeits_never_activated_assignment(self, api):
        """PRD §3.5: "every such new no-show decrements the slot's reserved count
        and auto-issues a `NO_SHOW_PENALTY` fine of 25,000 cents (two hundred
        fifty dollars) on the reservation's assignment, recorded with
        `created_by_user_id` `system` in status `ISSUED`."
        PRD §3.5: "Every assignment of the festival still in `CONFIRMED` once the
        clock is past `event_start` is moved to `FORFEITED`".

        Design: Difficulty/transitive_cascade/noshow_forfeit_release_waitlist_promotion_depth4
        """
        scen = _setup_noshow_cascade()
        sweep = sweep_festival(scen["festival"]["id"])
        assert sweep["no_shows_marked"] == 1
        assert get_reservation(scen["reservation"]["id"])["status"] == "NO_SHOW", "link 1"

        fines, _ = validate_paginated(
            api.list_fines(OPS, params={"assignment_id": scen["assignment"]["id"]})
        )
        assert len(fines) == 1
        assert fines[0]["type"] == "NO_SHOW_PENALTY"
        assert fines[0]["amount_cents"] == 25000
        assert fines[0]["created_by_user_id"] == "system", "auto-issued fine"

        asg = get_assignment(scen["assignment"]["id"])
        assert asg["status"] == "FORFEITED", "link 2"
        assert scen["assignment"]["id"] in sweep["forfeited_assignment_ids"]

    def test_forfeit_releases_capacity_and_promotes_waitlist(self, api):
        """PRD §3.5: "moved to `FORFEITED`, which returns its booth to
        `AVAILABLE`, decrements the zone's reserved totals, and runs waitlist
        promotion".
        PRD §3.5: "exactly one candidate — the top-ranked — moves from
        `WAITLISTED` to `UNDER_REVIEW`."

        Design: Difficulty/transitive_cascade/noshow_forfeit_release_waitlist_promotion_depth4
        """
        scen = _setup_noshow_cascade()
        sweep = sweep_festival(scen["festival"]["id"])
        assert get_booth(scen["booth"]["id"])["status"] == "AVAILABLE", "link 3: booth freed"
        assert get_zone(scen["zone"]["id"])["reserved_power_amps"] == 0, "link 3: budget freed"

        appb = get_application(scen["appb"]["id"])
        assert appb["status"] == "UNDER_REVIEW", "link 4: waitlisted application promoted"
        assert scen["appb"]["id"] in sweep["promoted_application_ids"]
