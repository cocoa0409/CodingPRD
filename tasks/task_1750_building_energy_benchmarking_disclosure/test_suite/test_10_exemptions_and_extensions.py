"""Exemption and extension requests: filing gates, adjudication, appeal loop (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_open_cycle,
    create_building,
    create_exemption,
    create_owner,
    make_owner_headers,
    review_and_decide_exemption,
    setup_verified_report,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


def _setup_building_no_report():
    owner = create_owner()
    cycle = create_and_open_cycle()
    building = create_building(owner["id"])
    return owner, cycle, building


class TestAppealLoop:
    def test_appeal_reopens_review_after_first_denial(self, api):
        """PRD §3.8: "A first `DENIED` decision — one where `appeal_used` is still
        false — moves the request `UNDER_REVIEW → DENIED`. The owner may appeal
        exactly once: the appeal requires the request in `DENIED`, the caller to own
        the building (`ERR_NOT_RESOURCE_OWNER`), `appeal_used` still false (a second
        appeal attempt fails with `ERR_INVALID_STATE_TRANSITION`), and an
        `appeal_note` of at least ten characters (`ERR_INVALID_REQUEST`). A
        successful appeal moves the request `DENIED → APPEALED` and sets
        `appeal_used` true, from which the officer restarts review."
        PRD §3.8: "Starting review moves the request `SUBMITTED → UNDER_REVIEW`, and
        the same action restarts review of an `APPEALED` request"

        Design: Difficulty/non_linear_state_machine/exemption_appeal_loop_reenters_review
        """
        owner, cycle, building = _setup_building_no_report()
        request = create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXEMPTION",
            reason="Building gut renovation, vacant all year",
        )

        denied = review_and_decide_exemption(
            request["id"], "DENIED", "Insufficient vacancy evidence"
        )
        assert denied["status"] == "DENIED"
        assert denied["appeal_used"] is False

        appealed = validate_success(
            api.appeal_exemption(
                request["id"],
                {"appeal_note": "Attaching utility disconnect records"},
                make_owner_headers(owner["id"]),
            )
        )
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_used"] is True

        # The DENIED -> APPEALED -> UNDER_REVIEW loop re-enters review.
        restarted = validate_success(api.start_exemption_review(request["id"], OFFICER))
        assert restarted["status"] == "UNDER_REVIEW"

    def test_second_denial_after_appeal_is_final(self, api):
        """PRD §3.8: "A `DENIED` decision rendered after the appeal has been used —
        `appeal_used` true — instead moves the request `UNDER_REVIEW → DENIED_FINAL`."
        PRD §3.8: "`APPROVED` and `DENIED_FINAL` are terminal."
        PRD §3.8: "The owner may appeal exactly once: the appeal requires the request
        in `DENIED`, the caller to own the building (`ERR_NOT_RESOURCE_OWNER`),
        `appeal_used` still false (a second appeal attempt fails with
        `ERR_INVALID_STATE_TRANSITION`), and an `appeal_note` of at least ten
        characters (`ERR_INVALID_REQUEST`)."

        Design: Difficulty/non_linear_state_machine/exemption_appeal_loop_reenters_review
        """
        owner, cycle, building = _setup_building_no_report()
        request = create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXEMPTION",
            reason="Building gut renovation, vacant all year",
        )
        review_and_decide_exemption(request["id"], "DENIED", "Insufficient vacancy evidence")
        validate_success(
            api.appeal_exemption(
                request["id"],
                {"appeal_note": "Attaching utility disconnect records"},
                make_owner_headers(owner["id"]),
            )
        )

        final = review_and_decide_exemption(
            request["id"], "DENIED", "Evidence still insufficient"
        )
        assert final["status"] == "DENIED_FINAL"

        resp = api.appeal_exemption(
            request["id"],
            {"appeal_note": "Second appeal attempt"},
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestFilingAndDecisionGates:
    def test_decide_before_review_rejected(self, api):
        """PRD §3.8: "Adjudication belongs to the `ComplianceOfficer`. Starting
        review moves the request `SUBMITTED → UNDER_REVIEW`, and the same action
        restarts review of an `APPEALED` request; from any other state the attempt
        fails with `ERR_INVALID_STATE_TRANSITION`. The officer then decides with a
        `decision` of `APPROVED` or `DENIED`"
        PRD §2.8: "The target resource's current state must allow the requested
        transition (`ERR_INVALID_STATE_TRANSITION`)."

        A decision rendered while the request is still SUBMITTED skips the mandatory
        review step.

        Design: Corner/state_machines/s_exemption_decide_before_review_rejected
        """
        owner, cycle, building = _setup_building_no_report()
        request = create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXEMPTION",
            reason="Building fully vacant this cycle",
        )

        resp = api.decide_exemption(
            request["id"], {"decision": "APPROVED", "decision_note": "Skipping review"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = validate_success(api.get_exemption_request(request["id"], OFFICER))
        assert still["status"] == "SUBMITTED"

    def test_exemption_blocked_once_report_filed(self, api):
        """PRD §3.8: "And an `EXEMPTION` request may not be filed once a report in
        `SUBMITTED`, `VERIFIED`, or `CERTIFIED` exists for the building and cycle;
        such a filing is rejected with `ERR_REPORT_ALREADY_FILED`."

        Design: Corner/validations/v_exemption_blocked_when_report_filed
        """
        ctx = setup_verified_report()
        resp = api.create_exemption_request(
            ctx["building"]["id"],
            {
                "cycle_id": ctx["cycle"]["id"],
                "request_type": "EXEMPTION",
                "reason": "Late exemption attempt after filing",
            },
            make_owner_headers(ctx["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_ALREADY_FILED)

    def test_extension_days_above_ninety_rejected(self, api):
        """PRD §3.8: "an `EXTENSION` asks that the filing deadline be moved, and then
        `requested_extension_days` is required and must lie between one and ninety
        days inclusive — for `EXEMPTION` requests the field is ignored."

        91 days exceeds the inclusive 1..90 bound.

        Design: Corner/validations/v_extension_days_out_of_range
        """
        owner, cycle, building = _setup_building_no_report()
        resp = api.create_exemption_request(
            building["id"],
            {
                "cycle_id": cycle["id"],
                "request_type": "EXTENSION",
                "reason": "Need more time for meter data",
                "requested_extension_days": 91,
            },
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_open_exemption_request_rejected(self, api):
        """PRD §3.8: "At most one request per building and cycle may be open — that
        is, in `SUBMITTED`, `UNDER_REVIEW`, or `APPEALED` — and a second open request
        is refused with `ERR_EXEMPTION_REQUEST_OPEN`."

        Design: Corner/validations/v_second_exemption_request_open_rejected
        """
        owner, cycle, building = _setup_building_no_report()
        create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXTENSION",
            reason="Awaiting utility data feed",
            requested_extension_days=30,
        )

        resp = api.create_exemption_request(
            building["id"],
            {
                "cycle_id": cycle["id"],
                "request_type": "EXEMPTION",
                "reason": "Trying to file a second open request",
            },
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_REQUEST_OPEN)

    def test_second_approved_extension_rejected(self, api):
        """PRD §3.8: "One further constraint guards approval of an `EXTENSION`: at
        most one approved extension may exist per building and cycle, and a duplicate
        approval fails with `ERR_EXTENSION_ALREADY_GRANTED`."
        PRD §3.8: "An approved `EXTENSION` sets the request's `extended_deadline_at`
        to the cycle's `filing_deadline_at` plus `requested_extension_days` days"

        The first extension's extended_deadline_at is exactly 2027-06-01 + 30 days.

        Design: Corner/validations/v_second_approved_extension_rejected
        """
        owner, cycle, building = _setup_building_no_report()
        er1 = create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXTENSION",
            reason="Awaiting utility data feed",
            requested_extension_days=30,
        )
        approved = review_and_decide_exemption(er1["id"], "APPROVED", "Granted 30 days")
        assert approved["status"] == "APPROVED"
        assert str(approved["extended_deadline_at"]).startswith("2027-07-01T00:00:00")

        er2 = create_exemption(
            building["id"],
            owner["id"],
            cycle["id"],
            request_type="EXTENSION",
            reason="Second request for more time",
            requested_extension_days=15,
        )
        validate_success(api.start_exemption_review(er2["id"], OFFICER))
        resp = api.decide_exemption(
            er2["id"], {"decision": "APPROVED", "decision_note": "Trying to stack extensions"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_GRANTED)
        still = validate_success(api.get_exemption_request(er2["id"], OFFICER))
        assert still["status"] == "UNDER_REVIEW"
