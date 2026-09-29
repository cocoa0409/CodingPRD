"""Half-open engagement windows, closed blackouts and open-ended domain occupation."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    admit_panelist,
    answer_verification,
    api_client,
    appointment_payload,
    assert_all_mandatory_grounds,
    build_docket,
    case_payload,
    case_version,
    clear_compliance,
    dispatch_notification,
    file_complaint,
    file_response,
    first_verification,
    get_success_data,
    make_complainant_headers,
    make_panelist_headers,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_complainant,
    read_panelist,
    record_delivery,
    register_domain,
    replace_seat,
    screen_seat,
    seat_panelist_cleanly,
    set_availability,
    set_clock,
    validate_error,
    validate_paginated,
    withdraw_case,
)

TOUCH_DOCKET = {
    "iana_id": "IANA-2313",
    "domain_name": "touch1.example",
    "legal_name": "Touch Ltd",
    "country_code": "FR",
}
BLACKOUT_DOCKET = {
    "iana_id": "IANA-2414",
    "domain_name": "blackout.example",
    "legal_name": "Blackout NV",
    "country_code": "FR",
}
OCCUPY_DOCKET = {
    "iana_id": "IANA-2515",
    "domain_name": "occupied.example",
    "legal_name": "Occupy SA",
    "country_code": "FR",
}
CAPACITY_DOCKET = {
    "iana_id": "IANA-2616",
    "domain_name": "cap1.example",
    "legal_name": "Capacity Oy",
    "country_code": "FR",
}


def _responded_chain(shared, domain):
    """Carry one domain of a shared docket to a RESPONSE_RECEIVED case."""
    case = file_complaint(shared["complainant"], domain)
    assert_all_mandatory_grounds(case, shared["complainant"], evidence_count=1)
    post_ledger_line(
        case["id"], case["complainant_share_cents"],
        reference="WIRE-%s" % domain["domain_name"],
    )
    bundle = {
        "registrar": shared["registrar"],
        "complainant": shared["complainant"],
        "domain": domain,
        "case": case,
    }
    clear_compliance(case["id"], headers=CASE_MANAGER_ALT)
    bundle["verification"] = first_verification(case["id"])
    answer_verification(bundle)
    bundle["notification"] = dispatch_notification(case["id"])
    record_delivery(bundle, "DELIVERED", deemed_received_at="2026-08-01T00:00:00Z")
    bundle["response"] = file_response(bundle)
    bundle["case"] = read_case(case["id"])
    return bundle


def _named_nomination(case_id, panelist_id, seat="SOLE"):
    """A nomination request that names its candidate, pinned to the stored version."""
    payload = appointment_payload(seat, case_version(case_id), nominated_by="PROVIDER")
    payload["panelist_id"] = panelist_id
    return api_client.create_appointment(case_id, payload, CASE_MANAGER)


class TestTouchingEngagementWindows:
    def _one_engagement_and_a_second_case(self):
        shared = build_docket(**TOUCH_DOCKET)
        first = _responded_chain(shared, shared["domain"])
        second = _responded_chain(
            shared, register_domain(shared["registrar"]["id"], "touch2.example")
        )
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z", max_overlapping_engagements=5,
        )
        set_clock("2026-08-10T00:00:00Z")
        seated = seat_panelist_cleanly(first["case"]["id"], "SOLE", panelist)
        assert seated["accepted_at"] == "2026-08-10T00:00:00.000Z"
        assert seated["decision_due_at"] == "2026-08-24T00:00:00.000Z"
        first["appointment"] = seated
        return panelist, first, second

    def test_one_second_of_overlap_with_a_live_engagement_is_refused(self):
        """PRD §3.6: "The temporal conditions are then evaluated against the
        prospective engagement window, which runs from the current logical clock to
        14 days later and is half-open: it includes its start instant and excludes
        its end."
        PRD §3.6: "The first is an overlap with another engagement: every seat the
        candidate holds in `ACCEPTED` on some other non-terminal case occupies the
        interval from its `accepted_at` to its `decision_due_at`, also half-open, so
        a new window that begins exactly when an existing engagement ends does
        **not** collide — back-to-back engagements are allowed."

        Design: Difficulty/resource_temporal_overlap/engagement_windows_that_merely_touch_are_allowed_one_second_of_overlap_is_not
        """
        panelist, _first, second = self._one_engagement_and_a_second_case()
        case_id = second["case"]["id"]
        set_clock("2026-08-23T23:59:59Z")
        version_before = case_version(case_id)
        refused = _named_nomination(case_id, panelist["id"])
        validate_error(refused, ApiErrorId.ERR_PANELIST_WINDOW_CONFLICT.value, 409)
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        unchanged = read_case(case_id)
        assert unchanged["status"] == "RESPONSE_RECEIVED"
        assert unchanged["version"] == version_before

    def test_a_window_that_starts_where_the_other_ends_is_admitted(self):
        """PRD §3.6: "Anything below 30 seats the neutral directly: the
        engagement-window and capacity checks are re-run at this moment against the
        same half-open window and the same closed blackout interval, and if they
        pass, the seat moves to `ACCEPTED` with `accepted_at` stamped from the clock,
        `decision_due_at` set 14 days later, and the neutral's `active_case_load`
        incremented by one."
        PRD §3.6: "Appointments can be listed across the docket with filters on
        `case_id`, on `panelist_id`, on `status` and on `seat`, which is how the
        successor row minted by a replacement is located."

        Design: Difficulty/resource_temporal_overlap/engagement_windows_that_merely_touch_are_allowed_one_second_of_overlap_is_not
        """
        panelist, first, second = self._one_engagement_and_a_second_case()
        case_id = second["case"]["id"]
        set_clock("2026-08-24T00:00:00Z")
        nominated = get_success_data(_named_nomination(case_id, panelist["id"]), 201)
        assert nominated["status"] == "NOMINATED"
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"

        accepted = screen_seat(nominated["id"], panelist["id"])
        assert accepted["status"] == "ACCEPTED"
        assert float(accepted["conflict_score"]) == 0.00
        assert accepted["accepted_at"] == "2026-08-24T00:00:00.000Z"
        assert accepted["decision_due_at"] == "2026-09-07T00:00:00.000Z"

        earlier = read_appointment(first["appointment"]["id"])
        assert earlier["status"] == "ACCEPTED"
        assert earlier["decision_due_at"] == "2026-08-24T00:00:00.000Z", (
            "one window's exclusive end is the other's inclusive start"
        )
        assert read_panelist(panelist["id"])["active_case_load"] == 2

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER,
                params={
                    "panelist_id": panelist["id"], "status": "ACCEPTED",
                    "limit": 10, "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 2
        assert [row["created_at"] for row in rows] == sorted(row["created_at"] for row in rows)


class TestClosedBlackoutInterval:
    def _panelist_with_a_blackout(self):
        shared = build_docket(**BLACKOUT_DOCKET)
        bundle = _responded_chain(shared, shared["domain"])
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z", max_overlapping_engagements=5,
        )
        declared = set_availability(
            panelist["id"], make_panelist_headers(panelist["id"]),
            unavailable_from="2026-08-24T00:00:00Z",
            unavailable_to="2026-08-30T00:00:00Z",
        )
        assert declared["unavailable_from"] == "2026-08-24T00:00:00Z"
        assert declared["unavailable_to"] == "2026-08-30T00:00:00Z"
        assert declared["active_case_load"] == 0
        set_clock("2026-08-10T00:00:00Z")
        return panelist, bundle

    def test_a_window_that_only_touches_the_blackout_start_still_collides(self):
        """PRD §3.6: "The second is an overlap with the candidate's declared
        blackout, the interval from `unavailable_from` to `unavailable_to`, which is
        closed at both ends, so a window that merely touches either boundary **does**
        collide."
        PRD §3.1: "Because the blackout interval is closed at both ends, an
        engagement window that merely touches `unavailable_to` still collides with
        it — a deliberate asymmetry against engagement windows, which are treated as
        half-open."

        Design: Difficulty/resource_temporal_overlap/blackout_interval_is_closed_so_a_touching_engagement_window_is_refused
        """
        panelist, bundle = self._panelist_with_a_blackout()
        case_id = bundle["case"]["id"]
        version_before = case_version(case_id)
        refused = _named_nomination(case_id, panelist["id"])
        validate_error(refused, ApiErrorId.ERR_PANELIST_WINDOW_CONFLICT.value, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_PANELIST_CAPACITY_EXCEEDED.value
        assert read_panelist(panelist["id"])["active_case_load"] == 0
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert case_version(case_id) == version_before

    def test_moving_the_blackout_one_day_out_admits_the_identical_nomination(self):
        """PRD §3.1: "A panelist's own availability can be revised later, either by
        the neutral or by a provider administrator, in a single call that carries any
        subset of four attributes: `status`, which may be `AVAILABLE`, `UNAVAILABLE`
        or `SUSPENDED`; `unavailable_from` and `unavailable_to`, the inclusive start
        and inclusive end of a declared blackout window; and
        `max_overlapping_engagements`."
        PRD §3.6: "The panel becomes constituted at the moment the count of seats in
        `ACCEPTED` on the case reaches `required_seat_count` and those seats cover
        the required set exactly once — `SOLE` alone on a single-member case, or
        `PRESIDING`, `CO_PANELIST_1` and `CO_PANELIST_2` on a three-member case."

        Design: Difficulty/resource_temporal_overlap/blackout_interval_is_closed_so_a_touching_engagement_window_is_refused
        """
        panelist, bundle = self._panelist_with_a_blackout()
        case_id = bundle["case"]["id"]
        refused = _named_nomination(case_id, panelist["id"])
        validate_error(refused, ApiErrorId.ERR_PANELIST_WINDOW_CONFLICT.value, 409)

        moved = set_availability(
            panelist["id"], make_panelist_headers(panelist["id"]),
            unavailable_from="2026-08-25T00:00:00Z",
            unavailable_to="2026-08-30T00:00:00Z",
        )
        assert moved["unavailable_from"] == "2026-08-25T00:00:00Z"

        nominated = get_success_data(_named_nomination(case_id, panelist["id"]), 201)
        assert nominated["status"] == "NOMINATED"
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"

        accepted = screen_seat(nominated["id"], panelist["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_at"] == "2026-08-10T00:00:00.000Z"
        assert accepted["decision_due_at"] == "2026-08-24T00:00:00.000Z"
        assert read_panelist(panelist["id"])["active_case_load"] == 1
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"


class TestDomainOccupationHasNoRightEndpoint:
    def _filed_case_left_open(self):
        shared = build_docket(**OCCUPY_DOCKET)
        case = file_complaint(shared["complainant"], shared["domain"])
        assert_all_mandatory_grounds(case, shared["complainant"], evidence_count=1)
        post_ledger_line(case["id"], case["complainant_share_cents"], reference="WIRE-2515")
        shared["case"] = read_case(case["id"])
        return shared

    def _refile(self, shared, domain=None, remedy_requested="TRANSFER"):
        target = domain or shared["domain"]
        return api_client.create_case(
            case_payload(
                shared["complainant"]["id"], target["id"],
                remedy_requested=remedy_requested,
            ),
            make_complainant_headers(shared["complainant"]["id"]),
        )

    def test_a_case_left_open_blocks_its_domain_indefinitely_and_only_its_domain(self):
        """PRD §3.2: "A domain is occupied by any case on it that has not reached a
        terminal status, and that occupation interval is open-ended on the right — it
        simply has no end until the case closes."
        PRD §3.2: "The bar is domain-scoped, not party-scoped — the identity of the
        earlier complainant is irrelevant, and cases on other domains never
        participate."

        Design: Difficulty/resource_temporal_overlap/domain_occupation_has_no_right_endpoint_until_the_case_closes
        """
        shared = self._filed_case_left_open()
        spare = register_domain(shared["registrar"]["id"], "spare.example")
        set_clock("2026-09-15T00:00:00Z")
        still_open = read_case(shared["case"]["id"])
        assert still_open["status"] == "FILED"
        assert still_open["closed_at"] is None

        blocked = self._refile(shared, remedy_requested="CANCELLATION")
        validate_error(blocked, ApiErrorId.ERR_DOMAIN_PROCEEDING_OVERLAP.value, 409)

        elsewhere = get_success_data(self._refile(shared, domain=spare), 201)
        assert elsewhere["status"] == "FILED"
        assert read_complainant(shared["complainant"]["id"])["open_case_count"] == 2

    def test_closing_the_case_swaps_the_open_ended_occupation_for_a_bounded_bar(self):
        """PRD §3.2: "A closed case leaves behind a cooling-off interval on that same
        domain instead, running from its `closed_at` to its `refiling_bar_until`,
        where `refiling_bar_until` is `closed_at` plus 30 days."
        PRD §3.2: "Both endpoints of that interval are inclusive, so a filing
        attempted at the exact instant of `refiling_bar_until` is still barred with
        `ERR_REFILING_BAR_ACTIVE` and the domain frees up one instant later."

        Design: Difficulty/resource_temporal_overlap/domain_occupation_has_no_right_endpoint_until_the_case_closes
        """
        shared = self._filed_case_left_open()
        set_clock("2026-09-15T00:00:00Z")
        withdrawn = withdraw_case(
            shared["case"]["id"], shared["complainant"]["id"],
            reason="Refiling with better evidence.",
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["closed_at"] == "2026-09-15T00:00:00.000Z"
        assert withdrawn["refiling_bar_until"] == "2026-10-15T00:00:00.000Z"

        set_clock("2026-09-20T00:00:00Z")
        barred = self._refile(shared)
        validate_error(barred, ApiErrorId.ERR_REFILING_BAR_ACTIVE.value, 409)
        assert barred.json()["data"]["error_id"] != ApiErrorId.ERR_DOMAIN_PROCEEDING_OVERLAP.value

        set_clock("2026-10-15T00:00:00Z")
        still_barred = self._refile(shared)
        validate_error(still_barred, ApiErrorId.ERR_REFILING_BAR_ACTIVE.value, 409)

        set_clock("2026-10-15T00:00:01Z")
        refiled = get_success_data(self._refile(shared), 201)
        assert refiled["status"] == "FILED"
        assert refiled["created_at"] == "2026-10-15T00:00:01.000Z"
        assert refiled["version"] == 1
        assert refiled["assessed_fee_cents"] == 150000

        rows, meta = validate_paginated(
            api_client.list_cases(
                CASE_MANAGER,
                params={"domain_id": shared["domain"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["WITHDRAWN", "FILED"]
        assert read_complainant(shared["complainant"]["id"])["open_case_count"] == 1


class TestCapacityCeilingIsAPureCount:
    def _two_adjacent_engagements_and_a_third_case(self):
        shared = build_docket(**CAPACITY_DOCKET)
        first = _responded_chain(shared, shared["domain"])
        second = _responded_chain(
            shared, register_domain(shared["registrar"]["id"], "cap2.example")
        )
        third = _responded_chain(
            shared, register_domain(shared["registrar"]["id"], "cap3.example")
        )
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z", max_overlapping_engagements=2,
        )
        substitute = admit_panelist(
            full_name="Bram de Vries", nationality_code="NL",
            roster_admitted_at="2018-11-11T00:00:00Z", max_overlapping_engagements=5,
        )
        set_clock("2026-08-10T00:00:00Z")
        first["appointment"] = seat_panelist_cleanly(first["case"]["id"], "SOLE", panelist)
        set_clock("2026-08-24T00:00:00Z")
        second["appointment"] = seat_panelist_cleanly(second["case"]["id"], "SOLE", panelist)
        set_clock("2026-09-07T00:00:00Z")
        return panelist, substitute, first, second, third

    def test_three_disjoint_windows_still_hit_the_aggregate_ceiling(self):
        """PRD §3.6: "After the window check, the load ceiling is tested and a
        candidate whose `active_case_load` has reached `max_overlapping_engagements`
        is refused with `ERR_PANELIST_CAPACITY_EXCEEDED` — the window conflict is
        deliberately reported in preference to the capacity ceiling when both are
        true."
        PRD §3.6: "The candidate's `active_case_load` must be strictly less than
        their own `max_overlapping_engagements`."

        Design: Difficulty/resource_temporal_overlap/capacity_ceiling_is_a_pure_count_and_bites_even_when_no_window_overlaps
        """
        panelist, _substitute, first, second, third = self._two_adjacent_engagements_and_a_third_case()
        assert first["appointment"]["accepted_at"] == "2026-08-10T00:00:00.000Z"
        assert first["appointment"]["decision_due_at"] == "2026-08-24T00:00:00.000Z"
        assert second["appointment"]["accepted_at"] == "2026-08-24T00:00:00.000Z"
        assert second["appointment"]["decision_due_at"] == "2026-09-07T00:00:00.000Z"
        assert read_panelist(panelist["id"])["active_case_load"] == 2

        case_id = third["case"]["id"]
        refused = _named_nomination(case_id, panelist["id"])
        validate_error(refused, ApiErrorId.ERR_PANELIST_CAPACITY_EXCEEDED.value, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_PANELIST_WINDOW_CONFLICT.value, (
            "the candidate window only touches the second engagement's exclusive end"
        )
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0

    def test_releasing_one_seat_frees_the_count_without_moving_any_window(self):
        """PRD §3.6: "Only seats in `ACCEPTED` on non-terminal cases are visible to
        any of these three checks: a merely nominated seat, an unscreened seat, and
        every seat on a withdrawn, closed, implemented or court-terminated case are
        all invisible."
        PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything that
        acceptance had built: the seat's `honoraria_cents` returns to 0, the neutral's
        `active_case_load` drops by one, the case falls back from `PANEL_CONSTITUTED`
        to `PANEL_APPOINTMENT`, and every decision on the case still in `DRAFT` is
        moved to `VOIDED` with `voided_at` stamped from the clock."

        Design: Difficulty/resource_temporal_overlap/capacity_ceiling_is_a_pure_count_and_bites_even_when_no_window_overlaps
        """
        panelist, substitute, first, second, third = self._two_adjacent_engagements_and_a_third_case()
        case_id = third["case"]["id"]
        refused = _named_nomination(case_id, panelist["id"])
        validate_error(refused, ApiErrorId.ERR_PANELIST_CAPACITY_EXCEEDED.value, 409)

        vacated = replace_seat(
            first["appointment"]["id"], replacement_panelist_id=substitute["id"],
            reason="The neutral is released to take a more urgent seat.",
        )
        assert vacated["status"] == "REPLACED"
        assert read_panelist(panelist["id"])["active_case_load"] == 1
        assert read_case(first["case"]["id"])["status"] == "PANEL_APPOINTMENT"
        successor = read_appointment(vacated["replaced_by_appointment_id"])
        assert successor["status"] == "NOMINATED"
        assert successor["panelist_id"] == substitute["id"]
        untouched = read_appointment(second["appointment"]["id"])
        assert untouched["status"] == "ACCEPTED"
        assert untouched["decision_due_at"] == "2026-09-07T00:00:00.000Z"

        nominated = get_success_data(_named_nomination(case_id, panelist["id"]), 201)
        assert nominated["status"] == "NOMINATED"
        accepted = screen_seat(nominated["id"], panelist["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_at"] == "2026-09-07T00:00:00.000Z"
        assert accepted["decision_due_at"] == "2026-09-21T00:00:00.000Z"
        assert read_panelist(panelist["id"])["active_case_load"] == 2

        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER,
                params={"panelist_id": panelist["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 3
