"""Calendar-range validation, the response deadline guard and the booking ladder.

The tests here are about *which* rule fires, not merely that something failed:
each one arranges two or more violated rules at once and pins the single error
the §2.9 ordering demands, then proves the rejected write left nothing behind.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
SECOND_PHYSICIAN = TEST_USERS["second_physician_headers"]

CLOCK_EPOCH = C.CLOCK_EPOCH  # 2026-08-01T00:00:00Z


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, whatever fractional precision it carries."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_inverted_calendar_range_is_rejected_and_never_blocks_a_day(api):
    """PRD §3.2: "If `date_to` is earlier than `date_from`, the window is refused with `ERR_INVALID_DATE_RANGE`."
    PRD §3.2: "A liaison may block its own donor's calendar by hand, supplying `date_from`, `date_to` and a `reason` of either `PERSONAL` or `MEDICAL_HOLD`."
    PRD §3.2: "The other two reasons in the enumeration, `DEFERRAL` and `COLLECTION_WINDOW`, are system-created only and a client that supplies either of them is refused with `ERR_INVALID_REQUEST`."
    PRD §2.9: "Rules are therefore evaluated in a strict ascending priority order, and the **first** violated rule alone decides the response; no later rule can mask or override it."
    PRD §2.9: "The third rung is body schema conformance on every write endpoint (`ERR_INVALID_REQUEST`): required fields present, types correct, enum values in range, numeric bounds respected, HLA typing objects carrying all five loci with exactly two strings each, and a non-empty consented-methods list."
    PRD §2.9: "The remaining rungs are the safety, referential, temporal and constraint rules, in this exact order: infectious-disease panel validity at the requested collection date (`ERR_IDM_RESULT_EXPIRED`); donor consent for the requested method (`ERR_DONOR_METHOD_NOT_CONSENTED`); screening outcome and deferral class agreement (`ERR_SCREENING_OUTCOME_MISMATCH`); adverse-event grade plausibility (`ERR_ADVERSE_EVENT_GRADE_INVALID`); delivered product dose adequacy (`ERR_PRODUCT_DOSE_INADEQUATE`); donor registry cooperation (`ERR_REGISTRY_NOT_COOPERATING`); reported typing being allele-level (`ERR_CT_TYPING_NOT_ALLELE_LEVEL`); typing response inside the contractual deadline (`ERR_CT_DEADLINE_PASSED`); conditioning start date not in the past (`ERR_CONDITIONING_DATE_IN_PAST`); calendar window date order (`ERR_INVALID_DATE_RANGE`); collection date inside the conditioning-derived window (`ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW`); donor calendar non-overlap (`ERR_DONOR_CALENDAR_CONFLICT`); product viability at infusion (`ERR_PRODUCT_VIABILITY_EXPIRED`); collection-centre buffered capacity (`ERR_CENTER_SLOT_CONFLICT`); confirmatory-typing attempt budget (`ERR_CT_ATTEMPTS_EXHAUSTED`); no duplicate open workup for the candidate (`ERR_DUPLICATE_OPEN_WORKUP`); no second concurrent search for the patient (`ERR_SEARCH_ALREADY_ACTIVE`); patient medical-record-number uniqueness (`ERR_MRN_ALREADY_EXISTS`); registry code uniqueness (`ERR_REGISTRY_CODE_ALREADY_EXISTS`); donor code uniqueness within a registry (`ERR_DONOR_CODE_ALREADY_EXISTS`); and last of all, the patient's case budget (`ERR_PATIENT_BUDGET_EXCEEDED`)."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."

    Design: Corner/validations/an_inverted_calendar_range_is_rejected_and_never_blocks_a_day
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)
    liaison = ctx["liaison_headers"]
    assert donor["blocked_day_count"] == 0, (
        f"a fresh donor's calendar is empty, got {donor['blocked_day_count']}"
    )

    # The same inverted range twice; only the reason differs.
    validate_error(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload("2026-09-10", "2026-09-09", "PERSONAL"),
            liaison,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE,
        422,
    )
    validate_error(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload(
                "2026-09-10", "2026-09-09", "COLLECTION_WINDOW"
            ),
            liaison,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    reread = validate_success(api.get_donor(donor["id"], liaison))
    assert reread["blocked_day_count"] == 0, (
        "a rejected window adds no day to blocked_day_count, got "
        f"{reread['blocked_day_count']}"
    )
    assert reread["availability_status"] == "AVAILABLE", (
        f"neither rejection touches availability_status, got {reread['availability_status']}"
    )

    windows, meta = validate_paginated(
        api.list_unavailability_windows(donor["id"], liaison, params={"limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"no partially created window may survive a rejected request, got {windows!r}"
    )


def test_single_day_window_is_accepted_and_manually_releasable(api):
    """PRD §3.2: "A donor's calendar is a set of unavailability windows, each spanning a closed inclusive date range from `date_from` through `date_to`."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."
    PRD §3.2: "A new window starts with `status` `ACTIVE` and `released_at` null."
    PRD §3.2: "A manually created window leaves `source_booking_id` null; only windows auto-created by booking confirmation carry a `source_booking_id` pointing back at the booking that generated them."
    PRD §3.2: "A window whose `reason` is `PERSONAL` or `MEDICAL_HOLD` may be released at any time while it is `ACTIVE`."
    PRD §3.2: "A successful release sets the window's `status` to `RELEASED`, stamps `released_at` from the logical clock, and lowers the donor's `blocked_day_count` by that window's `day_count`; the call returns no body."
    PRD §3.2: "Adjacency remains legal: a window that ends on the day immediately before another begins is not a conflict."
    PRD §3.2: "Donor profiles can be listed and filtered by home registry through `registry_id` and by availability through `availability_status`, and each donor's calendar windows can be listed with optional filters on `status` and on `reason`."

    Design: Corner/validations/a_single_day_window_is_accepted_and_manually_releasable
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)
    liaison = ctx["liaison_headers"]

    # date_to == date_from is the satisfying edge of the very rule an inverted
    # range violates: the closed interval is one day long, not zero.
    single = validate_success(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload("2026-09-10", "2026-09-10", "PERSONAL"),
            liaison,
        ),
        201,
    )
    A.assert_unavailability_window(single)
    assert single["status"] == "ACTIVE", f"a new window opens ACTIVE, got {single['status']}"
    assert single["released_at"] is None
    assert single["source_booking_id"] is None, (
        f"a hand-made window has no source_booking_id, got {single['source_booking_id']!r}"
    )
    assert single["reason"] == "PERSONAL"
    assert single["day_count"] == 1, (
        f"2026-09-10..2026-09-10 is one closed-inclusive day, got {single['day_count']}"
    )

    # Adjacent, so it is not a calendar conflict.
    three_day = validate_success(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload(
                "2026-09-11", "2026-09-13", "MEDICAL_HOLD"
            ),
            liaison,
        ),
        201,
    )
    assert three_day["day_count"] == 3, (
        f"2026-09-11..2026-09-13 spans three days, got {three_day['day_count']}"
    )

    blocked = validate_success(api.get_donor(donor["id"], liaison))
    assert blocked["blocked_day_count"] == 4, (
        f"1 + 3 blocked days are on the donor, got {blocked['blocked_day_count']}"
    )

    release = api.release_unavailability_window(donor["id"], single["id"], liaison)
    A.assert_no_content(release)

    after = validate_success(api.get_donor(donor["id"], liaison))
    assert after["blocked_day_count"] == 3, (
        "the release lowers blocked_day_count by exactly the released window's day_count, "
        f"got {after['blocked_day_count']}"
    )
    assert after["availability_status"] == "AVAILABLE", (
        "the donor was never deferred, so releasing a PERSONAL window leaves "
        f"availability_status AVAILABLE, got {after['availability_status']}"
    )

    active, meta = validate_paginated(
        api.list_unavailability_windows(
            donor["id"], liaison, params={"status": "ACTIVE", "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the MEDICAL_HOLD window is still ACTIVE, got {active!r}"
    )
    assert active[0]["id"] == three_day["id"]
    assert active[0]["reason"] == "MEDICAL_HOLD"

    released, released_meta = validate_paginated(
        api.list_unavailability_windows(
            donor["id"], liaison, params={"status": "RELEASED", "limit": 100}
        )
    )
    assert released_meta["total_count"] == 1, (
        f"the released row still exists, it is only excluded by the filter, got {released!r}"
    )
    assert released[0]["id"] == single["id"]
    assert released[0]["status"] == "RELEASED"
    assert _instant(released[0]["released_at"]) == _utc(CLOCK_EPOCH), (
        f"released_at is stamped from the logical clock, got {released[0]['released_at']}"
    )


D5_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "05:01"],
}
DONOR_D5 = {
    "donor_code": "D-0005",
    "age_years": 30,
    "sex": "F",
    "weight_kg": 72.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": D5_HLA,
    "consented_methods": ["PBSC", "MARROW"],
    "ambiguous_loci": [],
    "prior_donation_count": 0,
}


def test_deadline_guard_rejects_a_late_response_without_any_sweep(api):
    """PRD §3.4: "Timeliness is judged against the frozen deadline: a response filed strictly after `deadline_at` is refused with `ERR_CT_DEADLINE_PASSED`, while a response filed at exactly the deadline instant is accepted."
    PRD §3.4: "The typing request must still be in `REQUESTED` status — a request that is already `RESPONDED`, `EXPIRED` or `CANCELLED` is refused with `ERR_TYPING_REQUEST_NOT_OPEN` — and the acting liaison must be the donor's own registry."
    PRD §3.4: "A valid response stamps `responded_at` from the logical clock, stores the reported typing and the supplied `donor_available_flag`, and moves the request `REQUESTED → RESPONDED`."
    PRD §3.4: "That string is stored as the request's `reported_match_grade` and copied onto the candidate's `confirmed_match_grade`, and the candidate moves `TYPING_REQUESTED → TYPING_RESPONDED`."
    PRD §3.4: "The programme will not transplant below nine matched alleles out of ten, so a candidate whose matched-allele count is lower than nine is moved straight to `EXCLUDED` inside the same response call — its `confirmed_score` is still stored for audit, but it never rests in `TYPING_RESPONDED` — and if that candidate was the search's primary, the promotion cascade runs."
    PRD §3.4: "Requests do not expire on their own; expiry is an explicit operations act scoped to one search."
    PRD §3.4: "The deadline is computed once, at request time, and then frozen."
    PRD §2.9: "Rules are therefore evaluated in a strict ascending priority order, and the **first** violated rule alone decides the response; no later rule can mask or override it."

    Design: Corner/validations/the_deadline_guard_rejects_a_late_response_without_any_sweep
    """
    ctx = fixtures.setup_programme(
        with_center=False, registry_overrides={"ct_response_deadline_hours": 168}
    )
    liaison = ctx["liaison_headers"]
    d1 = fixtures.add_donor(ctx, donor_code="D-0001")
    d5 = fixtures.add_donor(ctx, **DONOR_D5)

    patient = fixtures.create_patient()
    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"]), COORDINATOR
        ),
        201,
    )
    candidates, _ = validate_paginated(
        api.list_match_candidates(
            COORDINATOR, params={"search_request_id": search["id"], "limit": 100}
        )
    )
    by_donor = {candidate["donor_id"]: candidate for candidate in candidates}
    primary_id = by_donor[d1["id"]]["id"]
    backup_id = by_donor[d5["id"]]["id"]

    # Both requests are raised at the same instant, so both freeze the same deadline.
    deadline = "2026-08-08T00:00:00Z"
    requests = {}
    for label, candidate_id in (("primary", primary_id), ("backup", backup_id)):
        created = validate_success(
            api.create_typing_request(
                candidate_id, f.create_typing_request_payload(), COORDINATOR
            ),
            201,
        )
        assert _instant(created["deadline_at"]) == _utc(deadline), (
            f"the {label} request's frozen deadline is {deadline}, got "
            f"{created['deadline_at']}"
        )
        requests[label] = created

    # A response filed at exactly the deadline instant is accepted.
    fixtures.set_clock(deadline)
    answered = validate_success(
        api.respond_typing_request(
            requests["backup"]["id"],
            f.typing_response_payload(reported_hla_typing=D5_HLA),
            liaison,
        )
    )
    assert answered["status"] == "RESPONDED", (
        f"a response at exactly the deadline is accepted, got {answered['status']}"
    )
    assert _instant(answered["responded_at"]) == _utc(deadline), (
        f"responded_at is stamped from the logical clock, got {answered['responded_at']}"
    )
    assert answered["reported_match_grade"] == "6/10", (
        f"D5 matches six alleles of ten, got {answered['reported_match_grade']!r}"
    )

    # Accepting the response and accepting the donor are separate outcomes.
    excluded = validate_success(api.get_match_candidate(backup_id, COORDINATOR))
    assert excluded["confirmed_match_grade"] == "6/10", (
        f"the grade string is copied onto the candidate, got "
        f"{excluded['confirmed_match_grade']!r}"
    )
    assert excluded["status"] == "EXCLUDED", (
        "six matched alleles are below the nine-of-ten floor, so the candidate goes "
        f"straight to EXCLUDED, got {excluded['status']}"
    )
    assert excluded["confirmed_score"] is not None, (
        "the confirmed score is still stored for audit on an excluded candidate"
    )

    # One second later the same response is refused, with no sweep anywhere.
    fixtures.set_clock("2026-08-08T00:00:01Z")
    validate_error(
        api.respond_typing_request(
            requests["primary"]["id"], f.typing_response_payload(), liaison
        ),
        ApiErrorId.ERR_CT_DEADLINE_PASSED,
        422,
    )

    rows, _ = validate_paginated(api.list_typing_requests(primary_id, COORDINATOR))
    assert len(rows) == 1, f"the primary holds exactly one request, got {rows!r}"
    late = rows[0]
    assert late["status"] == "REQUESTED", (
        "the late row passed the open-state check and was refused on timeliness alone, so "
        f"it is still REQUESTED, got {late['status']}"
    )
    assert late["responded_at"] is None, (
        f"the refused response stored nothing, got responded_at {late['responded_at']!r}"
    )
    assert late["expired_by_sweep_at"] is None, (
        "no sweep ran, so expired_by_sweep_at stays null, got "
        f"{late['expired_by_sweep_at']!r}"
    )
    still_requested = validate_success(api.get_match_candidate(primary_id, COORDINATOR))
    assert still_requested["status"] == "TYPING_REQUESTED", (
        "lateness alone does not expire a request or move its candidate, got "
        f"{still_requested['status']}"
    )


def test_booking_checks_run_as_a_ladder_method_then_clearance_then_window(api):
    """PRD §3.7: "Five substantive gates then apply, and they fire in the order §2.9 fixes: the case must be `OPEN`; its `collection_method` must already be set, or the request is refused with `ERR_METHOD_NOT_DECIDED`; its `clearance_status` must be `CLEARED`, or the request is refused with `ERR_CLEARANCE_NOT_COMPLETE`; the quoted case version must be current, or the request is refused with `ERR_STALE_WORKUP_VERSION`; then the infectious-disease validity, conditioning-window and centre-capacity checks below."
    PRD §2.9: "Rules are therefore evaluated in a strict ascending priority order, and the **first** violated rule alone decides the response; no later rule can mask or override it."
    PRD §3.6: "The workup case records its `match_candidate_id`, stamps `opened_by_user_id` from `X-User-ID`, and opens with `case_status` `OPEN`, `clearance_status` `PENDING`, `logistics_status` `UNSCHEDULED`, `collection_method` null, `method_decided_by_user_id` null, `physical_cleared_by_user_id` null, `idm_resulted_at` null and `abort_reason` null."
    PRD §3.6: "The two dimensions evolve independently of one another until booking creation couples them by demanding that clearance be complete; a `MedicalDirector` can perfectly well decide the method while clearance is still `IN_PROGRESS`."
    PRD §3.6: "The decision stores `collection_method` and stamps `method_decided_by_user_id` from `X-User-ID`, moves the case `UNSCHEDULED → METHOD_SET` on its logistics dimension, sets `planned_window_days` to 6 for `PBSC` or 8 for `MARROW`, and increments the case's `version` by one — which matters immediately, because that version is what the next booking attempt must quote."
    PRD §3.6: "A passing result on the last item still pending, with the other two already carrying `PASS`, moves the case `IN_PROGRESS → CLEARED`."
    PRD §3.6: "A passing `IDM_PANEL` sets that item's `expires_at` to its `resulted_at` plus thirty days — infectious-disease results are considered valid for one month and no longer — and surfaces the same instant as the case's `idm_resulted_at`, which stays null unless the panel actually passed."
    PRD §3.7: "The infectious-disease panel result must still be valid on the day of collection: the booking's `collection_date` must fall on or before the UTC calendar date of the `IDM_PANEL` clearance item's `expires_at`."
    PRD §3.7: "A booking whose `collection_date` falls outside that span, or a booking attempted while the patient is not yet in `SCHEDULED` or `STARTED` conditioning at all, is refused with `ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW`."
    PRD §3.7: "Creating it adds its `duration_minutes` to the centre's `committed_slot_minutes`, moves the case `METHOD_SET → BOOKED` on the logistics dimension, and increments the case's `version` by one."

    Design: Corner/validations/booking_checks_run_as_a_ladder_method_then_clearance_then_window
    """
    ctx = fixtures.setup_pipeline(
        "workup_open", center_overrides={"concurrent_collection_capacity": 2}
    )
    case_id = ctx["workup_case_id"]
    center_id = ctx["center_id"]
    center_ops = ctx["center_ops_headers"]
    start_at = "2026-08-20T08:00:00Z"

    def attempt_booking():
        """The identical booking request, always quoting the case's current version."""
        current = validate_success(api.get_workup_case(case_id, COORDINATOR))
        payload = f.create_booking_payload(
            case_id, center_id, start_at, current["version"]
        )
        return api.create_collection_booking(payload, center_ops)

    opened = validate_success(api.get_workup_case(case_id, COORDINATOR))
    assert opened["case_status"] == "OPEN"
    assert opened["clearance_status"] == "PENDING", (
        f"a freshly opened case has clearance_status PENDING, got {opened['clearance_status']}"
    )
    assert opened["logistics_status"] == "UNSCHEDULED"
    assert opened["collection_method"] is None

    # Rung one: the method gate wins over the clearance gate that is also violated.
    validate_error(attempt_booking(), ApiErrorId.ERR_METHOD_NOT_DECIDED, 409)

    decided = validate_success(
        api.decide_collection_method(
            case_id,
            f.collection_method_payload(
                method="PBSC",
                rationale="Recipient benefits from faster engraftment; donor consented to PBSC.",
            ),
            SECOND_PHYSICIAN,
        )
    )
    assert decided["collection_method"] == "PBSC"
    assert decided["logistics_status"] == "METHOD_SET", (
        f"the decision moves logistics UNSCHEDULED → METHOD_SET, got {decided['logistics_status']}"
    )
    assert decided["planned_window_days"] == 6, (
        f"PBSC plans a six-day window, got {decided['planned_window_days']}"
    )
    assert decided["clearance_status"] == "PENDING", (
        "the two dimensions are independent, so nothing forced clearance first; got "
        f"{decided['clearance_status']}"
    )
    assert decided["version"] == opened["version"] + 1, (
        f"the decision increments the case version, got {decided['version']}"
    )

    # Rung two: repairing rung one exposes the next rung, it does not succeed.
    validate_error(attempt_booking(), ApiErrorId.ERR_CLEARANCE_NOT_COMPLETE, 409)

    items, _ = validate_paginated(api.list_clearance_items(case_id, PHYSICIAN))
    assert [item["item_type"] for item in items] == [
        "PHYSICAL_EXAM",
        "IDM_PANEL",
        "CONSENT",
    ], f"the three items are listed in their created order, got {items!r}"

    for item in items:
        resulted = validate_success(
            api.record_clearance_result(
                item["id"], f.clearance_result_payload(result="PASS"), PHYSICIAN
            )
        )
        A.assert_clearance_item(resulted)
        assert resulted["result"] == "PASS"
        if item["item_type"] == "IDM_PANEL":
            assert _instant(resulted["expires_at"]) == _utc("2026-08-31T00:00:00Z"), (
                "a passing IDM panel expires thirty days after its resulted_at "
                f"{CLOCK_EPOCH}, got {resulted['expires_at']}"
            )
        else:
            assert resulted["expires_at"] is None, (
                f"{item['item_type']} carries no expires_at, got {resulted['expires_at']!r}"
            )

    cleared = validate_success(api.get_workup_case(case_id, COORDINATOR))
    assert cleared["clearance_status"] == "CLEARED", (
        f"the last passing item moves the case to CLEARED, got {cleared['clearance_status']}"
    )

    # Rung three: the collection date 2026-08-20 is well inside the IDM validity, so
    # the next surviving check is the conditioning window the patient does not have.
    validate_error(
        attempt_booking(), ApiErrorId.ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW, 422
    )

    center = validate_success(api.get_collection_center(center_id, center_ops))
    assert center["committed_slot_minutes"] == 0, (
        "no rejected attempt may move the centre's ledger, got "
        f"{center['committed_slot_minutes']}"
    )
    final = validate_success(api.get_workup_case(case_id, COORDINATOR))
    assert final["logistics_status"] == "METHOD_SET", (
        f"no booking was created, so logistics stays METHOD_SET, got {final['logistics_status']}"
    )
