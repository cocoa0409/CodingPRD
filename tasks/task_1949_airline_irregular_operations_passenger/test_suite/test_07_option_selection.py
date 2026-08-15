"""Recovery-option selector: priority scoring, ranking, interline candidates,
quota enforcement, and agreement lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_passenger, add_flight, add_event, add_booking, add_agreement,
    event_to_assessing, event_to_recovery,
    cancel_flight_under_event, get_case_for_booking, offer_case, offer_and_commit,
    commit_option, cabin_inventory, cost_entries, get_booking, get_option,
    setup_disrupted_booking, setup_offered_case, commit_cases,
    generate_options_payload, commit_payload,
)

AGENT = TEST_USERS["agent_headers"]
OPS = TEST_USERS["ops_controller_headers"]
ADMIN = TEST_USERS["ops_admin_headers"]


class TestPriorityScoreWeightedMultiFactor:
    def _setup_two_cases(self):
        set_clock("2026-08-10T06:00:00Z")
        pa = add_passenger(full_name="Pia A", contact_email="pia@x.com",
                           loyalty_tier="PLATINUM", special_service_codes=["UMNR"])
        pb = add_passenger(full_name="Gil B", contact_email="gil@x.com",
                           loyalty_tier="GOLD")
        f5 = add_flight(flight_number="OC500",
                        sched_dep_utc="2026-08-10T07:30:00Z",
                        sched_arr_utc="2026-08-10T08:30:00Z",
                        distance_km=1200,
                        cabins=[{"cabin": "BUSINESS", "capacity": 20}])
        f6 = add_flight(flight_number="OC600",
                        sched_dep_utc="2026-08-10T12:00:00Z",
                        sched_arr_utc="2026-08-10T13:00:00Z",
                        distance_km=1200)
        event = add_event(event_code="MECH-3", cost_cap_cents=1_000_000)
        event_to_assessing(event["id"])
        ba = add_booking(pa["id"], f5["id"], fare_cents=80000, cabin="BUSINESS")
        bb = add_booking(pb["id"], f6["id"], fare_cents=30000, party_size=3)
        cancel_flight_under_event(f5["id"], event["id"], expected_version=f5["version"])
        cancel_flight_under_event(f6["id"], event["id"], expected_version=f6["version"])
        cases = validate_success(api_client.list_reaccommodation_cases(
            AGENT, params={"disruption_event_id": event["id"]}))
        return ba, bb, cases

    def test_priority_score_combines_all_weighted_factors(self, api):
        """PRD §3.4: "It starts with one thousand points times the loyalty
        weight of the passenger's `loyalty_tier` — zero for `NONE`, one for
        `SILVER`, two for `GOLD`, four for `PLATINUM`. It adds ten points times
        the cabin weight of the booking's cabin — one for `ECONOMY`, two for
        `PREMIUM`, three for `BUSINESS`, four for `FIRST`. It adds an urgency
        bonus based on the minutes from the case's creation to the disrupted
        segment's scheduled departure at that moment: five hundred points when
        the gap is under 120 minutes, two hundred fifty points when the gap is
        at least 120 but under 360 minutes, and zero when the gap is 360 minutes
        or more. It adds a special-service bonus summed over the passenger's
        `special_service_codes` — three hundred for `UMNR`, two hundred for
        `WCHR`, fifty for `PETC` — capped at four hundred points in total.
        Finally it subtracts a group penalty: fifty points for each traveler
        beyond the first, counting at most four extra travelers."

        Design: Difficulty/combinatorial_formula/priority_score_weighted_multi_factor
        """
        ba, bb, cases = self._setup_two_cases()
        by_booking = {c["booking_id"]: c for c in cases}
        # A: 1000*4 (PLATINUM) + 10*3 (BUSINESS) + 500 (90 min < 120)
        #    + 300 (UMNR) - 0 (party 1) = 4830
        assert by_booking[ba["id"]]["priority_score"] == 4830
        # B: 1000*2 (GOLD) + 10*1 (ECONOMY) + 0 (exactly 360 min)
        #    + 0 (no SSR) - 50*2 (party 3) = 1910
        assert by_booking[bb["id"]]["priority_score"] == 1910

    def test_case_listing_serves_higher_scores_first(self, api):
        """PRD §3.4: "the queue order is the `priority_score`: higher scores are
        served first, and ties fall to the booking with the earlier
        `created_at`, with identifiers never participating."
        PRD §2.3: "the reaccommodation-case listing is ordered by
        `priority_score` descending with ties broken by the associated booking's
        `created_at` ascending (earlier bookings first)".

        Design: Difficulty/combinatorial_formula/priority_score_weighted_multi_factor
        """
        ba, bb, cases = self._setup_two_cases()
        assert cases[0]["booking_id"] == ba["id"], (
            "4830 sorts ahead of 1910 in priority_score DESC order")
        assert cases[0]["priority_score"] == 4830
        assert cases[1]["booking_id"] == bb["id"]
        assert cases[1]["priority_score"] == 1910


def test_equal_scores_break_ties_by_earlier_booking_created_at(api):
    """PRD §3.4: "the queue order is the `priority_score`: higher scores are
    served first, and ties fall to the booking with the earlier `created_at`,
    with identifiers never participating."

    Design: Corner/calculations/priority_tiebreak_uses_created_at
    """
    set_clock("2026-08-10T05:00:00Z")
    p1 = add_passenger(full_name="Gal G", contact_email="gal@x.com")
    p2 = add_passenger(full_name="Her H", contact_email="her@x.com")
    flight = add_flight(flight_number="OC38",
                        sched_dep_utc="2026-08-10T12:00:00Z",
                        sched_arr_utc="2026-08-10T13:00:00Z")
    event = add_event(event_code="MECH-C12", cost_cap_cents=100000)
    event_to_assessing(event["id"])
    ba = add_booking(p1["id"], flight["id"])
    set_clock("2026-08-10T05:00:01Z")
    bb = add_booking(p2["id"], flight["id"])
    cancel_flight_under_event(flight["id"], event["id"],
                              expected_version=flight["version"])

    cases = validate_success(api_client.list_reaccommodation_cases(
        AGENT, params={"disruption_event_id": event["id"]}))
    assert len(cases) == 2
    assert cases[0]["priority_score"] == cases[1]["priority_score"], (
        "identical profiles must produce identical scores")
    assert cases[0]["booking_id"] == ba["id"], (
        "the booking created one second earlier wins the tie-break")
    assert cases[1]["booking_id"] == bb["id"]


def test_selector_ranks_earliest_final_arrival_first(api):
    """PRD §3.5: "Eligible candidates are ranked by a `rank_score` in which
    lower sorts first: one million points per stop in the itinerary, plus ten
    points per minute from generation until the itinerary's final arrival, plus
    one point when the option is interline and zero otherwise; ties break to the
    candidate whose first-leg flight has the earlier `created_at`, and
    identifiers never participate. At most three options are materialized."

    Design: Corner/cross_cutting_layers/selector_ranking_earliest_arrival_first
    """
    ctx = setup_offered_case(
        event_code="MECH-C22",
        flight_overrides={"flight_number": "OC84",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[
            {"flight_number": "OC85",  # late: arr 18:00
             "sched_dep_utc": "2026-08-10T17:00:00Z",
             "sched_arr_utc": "2026-08-10T18:00:00Z"},
            {"flight_number": "OC86",  # early: arr 15:00
             "sched_dep_utc": "2026-08-10T14:00:00Z",
             "sched_arr_utc": "2026-08-10T15:00:00Z"},
            {"flight_number": "OC87",  # mid: arr 16:30
             "sched_dep_utc": "2026-08-10T15:30:00Z",
             "sched_arr_utc": "2026-08-10T16:30:00Z"},
        ])
    options = ctx["options"]
    assert len(options) == 3, "three eligible candidates -> three materialized options"
    by_number = {f["flight_number"]: f for f in ctx["extra_flights"]}
    # All nonstop own-metal: minutes-until-arrival decides; earliest first.
    assert options[0]["legs"][0]["flight_id"] == by_number["OC86"]["id"]
    assert options[1]["legs"][0]["flight_id"] == by_number["OC87"]["id"]
    assert options[2]["legs"][0]["flight_id"] == by_number["OC85"]["id"]
    assert options[0]["rank_score"] < options[1]["rank_score"] < options[2]["rank_score"]
    for opt in options:
        assert opt["option_status"] == "PROPOSED"
        assert opt["is_interline"] is False


def _setup_interline_scenario(event_code, quota=4, party_size=1, booking_count=1):
    """Own flight cancelled; a ZZ partner flight is the only candidate."""
    set_clock("2026-08-10T06:00:00Z")
    paxs = [add_passenger(full_name=f"Pax {i}", contact_email=f"pax{i}@x.com")
            for i in range(booking_count)]
    own = add_flight(flight_number="OC37",
                     sched_dep_utc="2026-08-10T09:00:00Z",
                     sched_arr_utc="2026-08-10T10:00:00Z",
                     distance_km=3200)
    partner = add_flight(flight_number="ZZ1", operating_carrier="ZZ",
                         sched_dep_utc="2026-08-10T14:00:00Z",
                         sched_arr_utc="2026-08-10T16:00:00Z",
                         distance_km=3200,
                         cabins=[{"cabin": "ECONOMY", "capacity": 10}])
    event = add_event(event_code=event_code, cost_cap_cents=500000)
    event_to_assessing(event["id"])
    agreement = add_agreement(partner_carrier="ZZ", origin="HUB", destination="DST",
                              cabin_map={"ECONOMY": "Y"}, settlement_rate_pct=60,
                              seats_quota_per_flight=quota)
    bookings = [add_booking(p["id"], own["id"], fare_cents=50000,
                            party_size=party_size) for p in paxs]
    cancel_flight_under_event(own["id"], event["id"], expected_version=own["version"])
    event_to_recovery(event["id"])
    cases = [get_case_for_booking(b["id"]) for b in bookings]
    return {"passengers": paxs, "own": own, "partner": partner, "event": event,
            "agreement": agreement, "bookings": bookings, "cases": cases}


def test_interline_commit_posts_settlement_accrual(api):
    """PRD §3.5: "An interline option is marked `is_interline` and records the
    `interline_agreement_id` and an `interline_fare_cents` face value equal to
    the `party_size` multiplied by the partner leg's distance in kilometers
    multiplied by five cents per kilometer; own-metal options carry no agreement
    and a zero interline fare."
    PRD §3.5: "For an interline option, the commit posts an `INTERLINE`
    `ACCRUAL` cost entry to the event equal to the option's
    `interline_fare_cents` multiplied by the agreement's `settlement_rate_pct`
    percent, divided by one hundred and rounded half up."
    PRD §3.5: "each partner leg instead increases the flight's
    `interline_seats_committed` by `party_size`."

    Design: Corner/calculations/interline_settlement_cost_entry
    """
    ctx = _setup_interline_scenario("MECH-C11")
    case = ctx["cases"][0]
    offered, options = offer_case(case["id"], include_interline=True)
    assert len(options) == 1
    option = options[0]
    assert option["is_interline"] is True
    assert option["interline_agreement_id"] == ctx["agreement"]["id"]
    # 1 passenger * 3200 km * 5 cents/km = 16000
    assert option["interline_fare_cents"] == 16000

    commit_option(case["id"], option["id"], offered["version"])

    entries = cost_entries(ctx["event"]["id"])
    interline = [e for e in entries if e["source_type"] == "INTERLINE"]
    assert len(interline) == 1
    # round_half_up(16000 * 60 / 100) = 9600
    assert interline[0]["entry_kind"] == "ACCRUAL"
    assert interline[0]["amount_cents"] == 9600
    assert interline[0]["source_id"] == option["id"]

    partner_cabin = cabin_inventory(ctx["partner"]["id"], "ECONOMY")
    assert partner_cabin["interline_seats_committed"] == 1
    assert partner_cabin["seats_sold"] == 0


def test_interline_commit_blocked_when_agreement_suspended(api):
    """PRD §3.5: "Finally, an interline option requires its agreement to still
    be `ACTIVE`, otherwise `ERR_INTERLINE_AGREEMENT_INACTIVE` (HTTP 422);
    cabin-map coverage was already enforced at generation and is not re-checked
    here."

    Design: Corner/errors/interline_commit_blocked_when_suspended
    """
    ctx = _setup_interline_scenario("MECH-C17")
    case = ctx["cases"][0]
    offered, options = offer_case(case["id"], include_interline=True)
    option = options[0]
    validate_success(api_client.suspend_interline_agreement(ctx["agreement"]["id"], ADMIN))

    res = api_client.commit_case(
        case["id"], commit_payload(option["id"], offered["version"]), AGENT)
    validate_error(res, ApiErrorId.ERR_INTERLINE_AGREEMENT_INACTIVE)

    assert get_option(option["id"])["option_status"] == "PROPOSED"
    interline = [e for e in cost_entries(ctx["event"]["id"])
                 if e["source_type"] == "INTERLINE"]
    assert interline == [], "rejected commit posts no INTERLINE entry"
    assert get_booking(ctx["bookings"][0]["id"])["booking_status"] == "DISRUPTED"


def test_interline_quota_exhaustion_empties_candidate_set(api):
    """PRD §3.5: "Interline candidates are considered only when
    `include_interline` is set, and only when the first leg's
    `operating_carrier` matches an interline agreement in `ACTIVE` status whose
    route scope covers the origin and destination, whose `cabin_map` contains
    the booking's cabin, and under which the partner flight still has quota
    headroom — the seats already committed interline plus the `party_size` must
    not exceed the agreement's `seats_quota_per_flight`."
    PRD §3.5: "If the selector finds no eligible candidate at all, the request
    fails with `ERR_NO_REACCOM_OPTIONS` (HTTP 422) and the case is left in the
    status it had — `QUEUED` or `ESCALATED`."

    Design: Corner/cross_cutting_layers/interline_quota_exhausted_falls_back_to_error
    """
    ctx = _setup_interline_scenario("MECH-C23", quota=2, party_size=2,
                                    booking_count=2)
    # First case commits the interline option: 0 + 2 <= 2 (inclusive headroom).
    case1, _ = offer_and_commit(ctx["cases"][0]["id"], include_interline=True)
    assert case1["case_status"] == "COMMITTED"
    partner_cabin = cabin_inventory(ctx["partner"]["id"], "ECONOMY")
    assert partner_cabin["interline_seats_committed"] == 2

    # Second party-2 case: 2 + 2 > 2 -> partner excluded; no own candidates.
    res = api_client.generate_options(
        ctx["cases"][1]["id"], generate_options_payload(True), AGENT)
    validate_error(res, ApiErrorId.ERR_NO_REACCOM_OPTIONS)
    from test_helpers import get_case
    assert get_case(ctx["cases"][1]["id"])["case_status"] == "QUEUED"


def test_agreement_suspend_toggles_status_and_version(api):
    """PRD §3.5: "An agreement begins `ACTIVE`; the suspend operation toggles it
    between `ACTIVE` and `SUSPENDED`, incrementing its `version` each time."

    Design: Corner/state_machines/interline_suspend_toggle_cycle
    """
    agreement = add_agreement(partner_carrier="ZZ")
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement["version"] == 1

    first = validate_success(api_client.suspend_interline_agreement(agreement["id"], ADMIN))
    assert first["agreement_status"] == "SUSPENDED"
    assert first["version"] == 2

    second = validate_success(api_client.suspend_interline_agreement(agreement["id"], ADMIN))
    assert second["agreement_status"] == "ACTIVE"
    assert second["version"] == 3
