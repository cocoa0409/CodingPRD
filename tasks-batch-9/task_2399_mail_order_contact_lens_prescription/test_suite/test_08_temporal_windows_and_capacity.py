"""Half-open prescription validity intervals, the business-hour contact cooldown
and the prescriber's aggregate pending-request ceiling.

Every scenario below pins the logical clock explicitly, because each rule under
test is decided by a comparison against that clock and by the business-hour walk
that derives deadlines and cooldown ends from it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    ApiErrorId,
    make_compliance_headers,
    make_customer_headers,
    make_prescriber_headers,
    new_customer,
    new_doctor_lookup_prescription,
    new_prescriber,
    new_prescription,
    new_product,
    send_verification_request,
    set_clock,
    setup_verification_round,
    submit_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)

# The whole file works from one Tuesday morning inside business hours, so the
# four-business-hour cooldown and the eight-business-hour deadline both start
# from an instant that needs no normalisation.
TUESDAY_10AM = "2026-09-08T10:00:00Z"
COOLDOWN_END = "2026-09-08T14:00:00Z"
ONE_SECOND_AFTER_COOLDOWN_END = "2026-09-08T14:00:01Z"

FIRST_ROUND_DEADLINE = "2026-09-09T09:00:00.000Z"
SECOND_ROUND_DEADLINE = "2026-09-09T13:00:01.000Z"


def _setup_supersession_interval_scenario() -> dict:
    """One patient with two verified prescriptions on adjacent intervals, plus two
    DRAFT captures: one that genuinely overlaps the incumbent and one that covers
    the incumbent's identical interval while naming it as superseded.
    """
    set_clock(TUESDAY_10AM)
    product = new_product()
    customer = new_customer()
    customer_id = customer["id"]

    incumbent = new_prescription(
        customer_id,
        product["id"],
        document_reference="scan-a",
        issue_date="2026-07-01",
        expiry_date="2027-07-01",
    )
    incumbent = submit_prescription(incumbent["id"], customer_id)

    adjacent = new_prescription(
        customer_id,
        product["id"],
        document_reference="scan-b",
        issue_date="2027-07-01",
        expiry_date="2028-07-01",
    )
    adjacent_submitted = submit_prescription(adjacent["id"], customer_id)

    overlapping = new_prescription(
        customer_id,
        product["id"],
        document_reference="scan-c",
        issue_date="2026-12-01",
        expiry_date="2027-06-01",
    )

    replacement = new_prescription(
        customer_id,
        product["id"],
        document_reference="scan-d",
        issue_date="2026-07-01",
        expiry_date="2027-07-01",
        od_sphere=-2.50,
        supersedes_prescription_id=incumbent["id"],
    )

    return {
        "product": product,
        "customer": customer,
        "customer_headers": make_customer_headers(customer_id),
        "incumbent": incumbent,
        "adjacent": adjacent_submitted,
        "overlapping": overlapping,
        "replacement": replacement,
    }


def _setup_three_outstanding_rounds_for_one_prescriber() -> dict:
    """One patient with four adjacent-interval DOCTOR_LOOKUP prescriptions naming
    the same directory-verified provider, three of which already carry an
    outstanding first round.
    """
    set_clock(TUESDAY_10AM)
    product = new_product()
    prescriber = new_prescriber(directory_verified=True, contact_channel="PORTAL")
    customer = new_customer()
    customer_id = customer["id"]

    intervals = [
        ("2026-09-01", "2026-10-01"),
        ("2026-10-01", "2026-11-01"),
        ("2026-11-01", "2026-12-01"),
        ("2026-12-01", "2027-01-01"),
    ]
    prescriptions = []
    for issue_date, expiry_date in intervals:
        rx = new_doctor_lookup_prescription(
            customer_id,
            product["id"],
            prescriber["id"],
            issue_date=issue_date,
            expiry_date=expiry_date,
            boxes_authorized_total=6,
        )
        prescriptions.append(submit_prescription(rx["id"], customer_id))

    outstanding = [
        send_verification_request(rx["id"], prescriber["id"], actor=CO_ALPHA)
        for rx in prescriptions[:3]
    ]

    return {
        "product": product,
        "prescriber": prescriber,
        "customer": customer,
        "prescriptions": prescriptions,
        "uncontacted_prescription": prescriptions[3],
        "outstanding_requests": outstanding,
    }


class TestPrescriptionValidityIntervalOverlap:
    """The submit-time overlap check treats [issue_date, expiry_date) as
    half-open and lets a declared supersession through it."""

    def test_overlapping_interval_submit_is_refused(self, api):
        """PRD §3.3: "Before it does, an overlap check runs: no other prescription
        of the same customer in `VERIFIED_ACTIVE` or `PENDING_VERIFICATION` may
        have a half-open validity interval that overlaps this one's interval from
        `issue_date` inclusive to `expiry_date` exclusive."

        PRD §3.3: "An overlap is rejected with `ERR_PRESCRIPTION_INTERVAL_OVERLAP`
        unless `supersedes_prescription_id` names precisely the overlapping
        prescription, which is the legitimate case of a patient replacing an old
        prescription mid-interval."

        Design: Difficulty/resource_temporal_overlap/prescription_validity_intervals_are_half_open_with_supersede_bypass
        """
        scenario = _setup_supersession_interval_scenario()
        overlapping_id = scenario["overlapping"]["id"]

        response = api.submit_prescription(overlapping_id, scenario["customer_headers"])
        validate_error(response, ApiErrorId.ERR_PRESCRIPTION_INTERVAL_OVERLAP.value)

        unchanged = validate_success(
            api.get_prescription(overlapping_id, ADMIN_HEADERS)
        )
        assert unchanged["status"] == "DRAFT", (
            "a refused submit must leave the prescription in DRAFT"
        )

    def test_touching_interval_submit_is_permitted(self, api):
        """PRD §3.3: "Intervals that merely touch — where one prescription's
        `expiry_date` equals the other's `issue_date` — do not overlap and are
        permitted."

        Design: Difficulty/resource_temporal_overlap/prescription_validity_intervals_are_half_open_with_supersede_bypass
        """
        scenario = _setup_supersession_interval_scenario()

        adjacent = validate_success(
            api.get_prescription(scenario["adjacent"]["id"], ADMIN_HEADERS)
        )
        assert adjacent["status"] == "VERIFIED_ACTIVE", (
            "a prescription whose issue_date equals the incumbent's expiry_date "
            "must submit through to VERIFIED_ACTIVE"
        )
        assert adjacent["issue_date"] == scenario["incumbent"]["expiry_date"]

    def test_supersede_bypass_accepts_the_identical_interval_and_invalidates_the_predecessor(
        self, api
    ):
        """PRD §3.3: "An overlap is rejected with
        `ERR_PRESCRIPTION_INTERVAL_OVERLAP` unless `supersedes_prescription_id`
        names precisely the overlapping prescription, which is the legitimate case
        of a patient replacing an old prescription mid-interval."

        PRD §3.3: "When `supersedes_prescription_id` is set, the superseded
        prescription is driven to `INVALIDATED` and every one of its `ACTIVE`
        auto-reorder schedules moves to `CANCELLED`, after which the affected
        customer's `active_schedule_count` and `auto_reorder_enabled` are
        reconciled."

        Design: Difficulty/resource_temporal_overlap/prescription_validity_intervals_are_half_open_with_supersede_bypass
        """
        scenario = _setup_supersession_interval_scenario()
        customer_id = scenario["customer"]["id"]
        replacement_id = scenario["replacement"]["id"]
        incumbent_id = scenario["incumbent"]["id"]

        submitted = validate_success(
            api.submit_prescription(replacement_id, scenario["customer_headers"])
        )
        assert submitted["status"] == "VERIFIED_ACTIVE", (
            "the declared replacement must submit through despite covering the "
            "incumbent's identical interval"
        )

        superseded = validate_success(
            api.get_prescription(incumbent_id, ADMIN_HEADERS)
        )
        assert superseded["status"] == "INVALIDATED"

        verified, meta = validate_paginated(
            api.list_prescriptions(
                ADMIN_HEADERS,
                params={"customer_id": customer_id, "status": "VERIFIED_ACTIVE"},
            )
        )
        assert meta["total_count"] == 2, (
            "only the adjacent prescription and the replacement remain verified"
        )
        assert {row["id"] for row in verified} == {
            scenario["adjacent"]["id"],
            replacement_id,
        }


class TestPrescriberContactCooldownWindow:
    """The four-business-hour cooldown is closed at its far end, so the boundary
    instant itself is still blocked."""

    def test_contact_at_the_exact_cooldown_end_is_refused(self, api):
        """PRD §3.3: "The cooldown window is computed by advancing four business
        hours from the earlier contact's send instant using the business-hour walk
        of §2.5, and the window is **closed** at that end: a new contact attempted
        at an instant that is at or before the computed cooldown end is blocked,
        and only an instant strictly after it is allowed."

        PRD §3.3: "Both variants of the round-opening are governed by the same four
        gates, evaluated in the order given in §2.10: the named provider's `status`
        must be `ACTIVE`, or the contact is refused with `ERR_PRESCRIBER_SUSPENDED`;
        the same provider must not already have been contacted about the same
        prescription inside the four-business-hour cooldown window, or the contact
        is refused with `ERR_PRESCRIBER_CONTACT_COOLDOWN` at HTTP 429; the provider
        must currently hold fewer than three verification requests in `SENT` status
        counted across every prescription in the system, or the contact is refused
        with `ERR_PRESCRIBER_REQUEST_CAPACITY`; and the prescription's
        `verification_rounds` must be strictly less than the round cap of three, or
        the contact is refused with `ERR_MAX_VERIFICATION_ROUNDS`."

        Design: Difficulty/resource_temporal_overlap/prescriber_contact_cooldown_window_is_closed_at_both_ends
        """
        scenario = setup_verification_round(clock=TUESDAY_10AM, directory_verified=True)
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]

        set_clock(COOLDOWN_END)
        response = api.send_verification_request(
            prescription_id, {"prescriber_id": prescriber_id}, CO_ALPHA_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIBER_CONTACT_COOLDOWN.value)

        prescription = validate_success(
            api.get_prescription(prescription_id, ADMIN_HEADERS)
        )
        assert prescription["verification_rounds"] == 1, (
            "a blocked contact must not consume a verification round"
        )

        _, meta = validate_paginated(
            api.list_verification_requests(
                CO_ALPHA_HEADERS, params={"prescription_id": prescription_id}
            )
        )
        assert meta["total_count"] == 1, "no second verification request may exist"

    def test_contact_one_second_after_the_cooldown_end_opens_a_second_round(self, api):
        """PRD §3.3: "The cooldown window is computed by advancing four business
        hours from the earlier contact's send instant using the business-hour walk
        of §2.5, and the window is **closed** at that end: a new contact attempted
        at an instant that is at or before the computed cooldown end is blocked,
        and only an instant strictly after it is allowed."

        PRD §3.3: "Its `round_number` is a one-based index within the prescription,
        set to the prescription's `verification_rounds` plus one, and the
        prescription's `verification_rounds` is then incremented."

        PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing a
        business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        Design: Difficulty/resource_temporal_overlap/prescriber_contact_cooldown_window_is_closed_at_both_ends
        """
        scenario = setup_verification_round(clock=TUESDAY_10AM, directory_verified=True)
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]

        set_clock(ONE_SECOND_AFTER_COOLDOWN_END)
        second_round = validate_success(
            api.send_verification_request(
                prescription_id, {"prescriber_id": prescriber_id}, CO_ALPHA_HEADERS
            ),
            201,
        )
        assert second_round["round_number"] == 2
        assert second_round["passive_deadline_at"] == SECOND_ROUND_DEADLINE, (
            "eight business hours from 14:00:01 on a Tuesday must land at "
            f"{SECOND_ROUND_DEADLINE}"
        )

        prescription = validate_success(
            api.get_prescription(prescription_id, ADMIN_HEADERS)
        )
        assert prescription["verification_rounds"] == 2

    def test_the_two_rounds_carry_independent_deadlines(self, api):
        """PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing
        a business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        PRD §3.3: "The request's `status` begins at `SENT` and ends in one of four
        terminal values — `CONFIRMED`, `CORRECTED`, `DENIED` or `PASSIVE_TIMEOUT` —
        and its `response_type` stays null until a provider actually answers, at
        which point it takes the value `CONFIRMED`, `CORRECTED` or `DENIED`."

        Design: Difficulty/resource_temporal_overlap/prescriber_contact_cooldown_window_is_closed_at_both_ends
        """
        scenario = setup_verification_round(clock=TUESDAY_10AM, directory_verified=True)
        first_request_id = scenario["verification_request"]["id"]
        assert (
            scenario["verification_request"]["passive_deadline_at"]
            == FIRST_ROUND_DEADLINE
        ), (
            "eight business hours from 10:00 on a Tuesday must land at "
            f"{FIRST_ROUND_DEADLINE}"
        )

        set_clock(ONE_SECOND_AFTER_COOLDOWN_END)
        second_round = validate_success(
            api.send_verification_request(
                scenario["prescription"]["id"],
                {"prescriber_id": scenario["prescriber"]["id"]},
                CO_ALPHA_HEADERS,
            ),
            201,
        )
        assert second_round["passive_deadline_at"] == SECOND_ROUND_DEADLINE

        first_request = validate_success(
            api.get_verification_request(first_request_id, CO_ALPHA_HEADERS)
        )
        assert first_request["status"] == "SENT", (
            "opening a later round is not one of the four things that ends a "
            "request's SENT status"
        )
        assert first_request["passive_deadline_at"] == FIRST_ROUND_DEADLINE, (
            "the first round keeps the deadline computed from its own sent_at"
        )


class TestPrescriberPendingRequestCapacity:
    """The pending-request ceiling counts the provider's SENT rows across every
    prescription, not per prescription."""

    def test_fourth_round_is_refused_while_three_rounds_are_outstanding(self, api):
        """PRD §3.3: "Both variants of the round-opening are governed by the same
        four gates, evaluated in the order given in §2.10: the named provider's
        `status` must be `ACTIVE`, or the contact is refused with
        `ERR_PRESCRIBER_SUSPENDED`; the same provider must not already have been
        contacted about the same prescription inside the four-business-hour
        cooldown window, or the contact is refused with
        `ERR_PRESCRIBER_CONTACT_COOLDOWN` at HTTP 429; the provider must currently
        hold fewer than three verification requests in `SENT` status counted across
        every prescription in the system, or the contact is refused with
        `ERR_PRESCRIBER_REQUEST_CAPACITY`; and the prescription's
        `verification_rounds` must be strictly less than the round cap of three, or
        the contact is refused with `ERR_MAX_VERIFICATION_ROUNDS`."

        Design: Difficulty/resource_temporal_overlap/prescriber_pending_request_capacity_is_an_aggregate_limit
        """
        scenario = _setup_three_outstanding_rounds_for_one_prescriber()
        prescriber_id = scenario["prescriber"]["id"]
        uncontacted_id = scenario["uncontacted_prescription"]["id"]

        response = api.send_verification_request(
            uncontacted_id, {"prescriber_id": prescriber_id}, CO_ALPHA_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIBER_REQUEST_CAPACITY.value)

        _, meta = validate_paginated(
            api.list_verification_requests(
                CO_ALPHA_HEADERS,
                params={"prescriber_id": prescriber_id, "status": "SENT"},
            )
        )
        assert meta["total_count"] == 3, (
            "the refused contact must not add a fourth SENT request"
        )

        never_contacted = validate_success(
            api.get_prescription(uncontacted_id, ADMIN_HEADERS)
        )
        assert never_contacted["verification_rounds"] == 0, (
            "the aggregate ceiling bites on a prescription that has no cooldown "
            "of its own"
        )

    def test_answering_one_outstanding_round_frees_capacity_for_the_fourth(self, api):
        """PRD §3.4: "A `CONFIRMED` response sets the request's `status` and
        `response_type` both to `CONFIRMED` and promotes the prescription from
        `PENDING_VERIFICATION` to `VERIFIED_ACTIVE`."

        PRD §3.3: "Both variants of the round-opening are governed by the same four
        gates, evaluated in the order given in §2.10: the named provider's `status`
        must be `ACTIVE`, or the contact is refused with `ERR_PRESCRIBER_SUSPENDED`;
        the same provider must not already have been contacted about the same
        prescription inside the four-business-hour cooldown window, or the contact
        is refused with `ERR_PRESCRIBER_CONTACT_COOLDOWN` at HTTP 429; the provider
        must currently hold fewer than three verification requests in `SENT` status
        counted across every prescription in the system, or the contact is refused
        with `ERR_PRESCRIBER_REQUEST_CAPACITY`; and the prescription's
        `verification_rounds` must be strictly less than the round cap of three, or
        the contact is refused with `ERR_MAX_VERIFICATION_ROUNDS`."

        Design: Difficulty/resource_temporal_overlap/prescriber_pending_request_capacity_is_an_aggregate_limit
        """
        scenario = _setup_three_outstanding_rounds_for_one_prescriber()
        prescriber_id = scenario["prescriber"]["id"]
        uncontacted_id = scenario["uncontacted_prescription"]["id"]
        first_request_id = scenario["outstanding_requests"][0]["id"]

        answered = validate_success(
            api.respond_to_verification_request(
                first_request_id,
                {"response_type": "CONFIRMED"},
                make_prescriber_headers(prescriber_id),
            )
        )
        assert answered["status"] == "CONFIRMED"

        _, meta = validate_paginated(
            api.list_verification_requests(
                CO_ALPHA_HEADERS,
                params={"prescriber_id": prescriber_id, "status": "SENT"},
            )
        )
        assert meta["total_count"] == 2, (
            "the answered round no longer counts against the provider's ceiling"
        )

        admitted = validate_success(
            api.send_verification_request(
                uncontacted_id,
                {"prescriber_id": prescriber_id},
                make_compliance_headers(CO_ALPHA),
            ),
            201,
        )
        assert admitted["round_number"] == 1, (
            "the freed slot admits the first round on the uncontacted prescription"
        )
        assert admitted["prescription_id"] == uncontacted_id
        assert admitted["status"] == "SENT"
