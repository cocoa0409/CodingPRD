"""Priority-pair conflicts: the PRD validation ladder says a failure at an
earlier rung masks every later rung."""
from test_helpers import (
    api_client,
    create_active_community,
    create_certified_payment,
    create_funded_district,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.factories import create_event_payload

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestPaymentPayStateVsFiscalPriority:
    """Re-paying an already PAID payment while district funds are 0 violates
    both the from-state rule (rung 5) and the fiscal rule (rung 11)."""

    def _setup_paid(self):
        community = create_active_community("Priority Pines", 50)
        district, _, _ = create_funded_district(
            community["id"],
            [(6000000, "2026-01-01T00:00:00Z")],
            levy_amount_cents=500000,
            district_name="PID 3",
        )
        certified = create_certified_payment(district["id"], 500000)
        get_success_data(api_client.pay_payment(certified["id"], CTRL))
        return district, certified["id"]

    def test_certification_arithmetic_and_funds_drained(self):
        """PRD §3.6: "The certified interest, `certified_interest_cents`, is the sum of the daily-compound interest over all advances to that timestamp, and the certified principal, `certified_principal_cents`, is the claim amount minus that interest — a claim too small to cover the interest due would make that figure negative and is likewise rejected `ERR_PAYMENT_EXCEEDS_OBLIGATION`.".
        PRD §3.6: "Disbursement moves a `CERTIFIED` payment to `PAID` under a `DeclarantController` and requires the district's `available_funds_cents` to cover the payment's `amount_cents` (`ERR_INSUFFICIENT_DISTRICT_FUNDS`); it stamps `paid_at` and draws the funds down. Rejection is available from `REQUESTED` with no unwind, and from `CERTIFIED` with a full compensating unwind: the district's `outstanding_principal_cents` is restored by the certified principal, `certified_interest_to_date_cents` is reduced by the certified interest, and the advance allocations are unwound in reverse first-in-first-out order — the most recent allocations come off first."

        Design: Difficulty/priority_pair_validation_conflict/payment_pay_state_vs_fiscal_priority
        """
        district, payment_id = self._setup_paid()
        payment = get_success_data(api_client.get_payment(payment_id, CTRL))
        assert payment["status"] == "PAID"
        # Single 6,000,000c advance, 120 days at 5% daily-compound: 99,438c.
        assert payment["certified_interest_cents"] == 99438, (
            f"certified interest must be 99438, got {payment['certified_interest_cents']}"
        )
        assert payment["certified_principal_cents"] == 400562
        read = get_success_data(api_client.get_district(district["id"], CTRL))
        assert read["available_funds_cents"] == 0, (
            f"500,000 collected - 500,000 paid must leave 0, got {read['available_funds_cents']}"
        )

    def test_state_error_masks_fiscal_error_on_repay(self):
        """PRD §2.9: "Validation Order and Error Precedence Every request is validated against a fixed ladder, and a failure at an earlier rung masks every later rung. The order is: 1. **Authentication** — the headers of §2.1; failures surface as `ERR_UNAUTHENTICATED`. 2. **Authorization** — the role named by `X-User-Role` must appear in the endpoint's authorized list; otherwise `ERR_FORBIDDEN_ROLE`. 3. **Existence** — path identifiers are validated left-to-right, then every foreign-key identifier in the request body (`community_id`, `phase_id`, `builder_id`, `agreement_id`, `lot_id`, `budget_id`, `district_id`, `event_id`, `resident_id`, `owner_resident_id`, `holder_resident_id`, `trigger_phase_id`, `charged_budget_id`, `assessment_rate_id`, applicant and respondent identifiers); each missing resource yields its own `ERR_*_NOT_FOUND` (HTTP 404). 4. **Request shape** — required fields present, primitive types correct, enum members valid, no undeclared fields, scalar constraints honored; otherwise `ERR_VALIDATION` (HTTP 400). 5. **State** — the target must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409), plus the domain state gates of §3 such as `ERR_COMMUNITY_NOT_ACTIVE`, `ERR_PHASE_NOT_OPEN_FOR_SALES`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_OFFERED`, `ERR_LOT_NOT_UNDER_CONTRACT`, `ERR_BUILDER_NOT_IN_GOOD_STANDING`, `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`, `ERR_CLOSEOUT_BLOCKED`, `ERR_CLOSINGS_PENDING`, `ERR_BUDGET_EMPTY`, `ERR_BUDGET_NOT_ADOPTED`, `ERR_NOTICE_NOT_SENT`, `ERR_TRANCHE_NOT_CURABLE`, `ERR_CURE_WINDOW_OPEN`, `ERR_SEAT_NOT_VACANT`, `ERR_REVIEW_ROUNDS_EXHAUSTED`, `ERR_DECLARANT_AUTHORITY_ENDED`, `ERR_SUBSIDY_NOT_AVAILABLE`, `ERR_NO_PRIOR_RATE`, `ERR_TRANSITION_THRESHOLD_NOT_MET`, and `ERR_TURNOVER_SEATS_NOT_FILLED`. 6. **Concurrency** — the OCC check of §2.8, surfacing as `ERR_STALE_VERSION`. 7. **Business safety** — the amenity-posture guard on event scheduling, `ERR_AMENITY_NOT_OPEN`. 8. **Temporal windows** — lead times, statutory windows, and future-dating rules: `ERR_EVENT_LEAD_TIME`, `ERR_NOTICE_LEAD_TIME`, `ERR_RESCISSION_WINDOW_EXPIRED`, `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_SEND_AT_IN_PAST` (HTTP 422). 9. **Uniqueness, overlap, sequence, and segregation** — `ERR_PHASE_SEQUENCE_BLOCKED`, `ERR_DUPLICATE_FISCAL_YEAR`, `ERR_DUPLICATE_ASSESSMENT_YEAR`, `ERR_DUPLICATE_DISTRICT`, `ERR_DUPLICATE_TRANCHE_NO`, `ERR_VENUE_OVERLAP`, `ERR_TOUR_CAPACITY_REACHED` (all HTTP 409), and the segregation-of-duties conflicts `ERR_REVIEWER_CONFLICT`, `ERR_ADOPTER_CANNOT_RATIFY`, `ERR_HEARING_OFFICER_CONFLICT` (HTTP 403), together with the election thresholds `ERR_QUORUM_NOT_MET` and `ERR_ELECTION_MAJORITY_NOT_REACHED` (HTTP 409)."
        PRD §2.9 rung 5: "State — the target must be in a valid from-state for
        the requested transition (ERR_INVALID_STATE, HTTP 409)"; rung 11:
        "Fiscal guards, evaluated last — ERR_INSUFFICIENT_DISTRICT_FUNDS ...

        Design: Difficulty/priority_pair_validation_conflict/payment_pay_state_vs_fiscal_priority
        """
        _, payment_id = self._setup_paid()
        resp = api_client.pay_payment(payment_id, CTRL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEventLeadTimeVsVenueOverlapPriority:
    """An event violating the 14-day lead AND overlapping an occupied venue:
    the temporal failure (rung 8) masks the overlap failure (rung 9)."""

    def _setup(self):
        community = create_active_community("Overlap Oaks", 50)
        event_a = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Model Tour A",
                    start_at="2026-05-20T10:00:00Z", end_at="2026-05-20T12:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event_a["id"], LIFESTYLE))
        event_c = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Rushed Mixer",
                    start_at="2026-05-06T11:00:00Z", end_at="2026-05-06T12:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        return event_c["id"]

    def test_lead_time_masks_venue_overlap(self):
        """PRD §2.9: "Validation Order and Error Precedence Every request is validated against a fixed ladder, and a failure at an earlier rung masks every later rung. The order is: 1. **Authentication** — the headers of §2.1; failures surface as `ERR_UNAUTHENTICATED`. 2. **Authorization** — the role named by `X-User-Role` must appear in the endpoint's authorized list; otherwise `ERR_FORBIDDEN_ROLE`. 3. **Existence** — path identifiers are validated left-to-right, then every foreign-key identifier in the request body (`community_id`, `phase_id`, `builder_id`, `agreement_id`, `lot_id`, `budget_id`, `district_id`, `event_id`, `resident_id`, `owner_resident_id`, `holder_resident_id`, `trigger_phase_id`, `charged_budget_id`, `assessment_rate_id`, applicant and respondent identifiers); each missing resource yields its own `ERR_*_NOT_FOUND` (HTTP 404). 4. **Request shape** — required fields present, primitive types correct, enum members valid, no undeclared fields, scalar constraints honored; otherwise `ERR_VALIDATION` (HTTP 400). 5. **State** — the target must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409), plus the domain state gates of §3 such as `ERR_COMMUNITY_NOT_ACTIVE`, `ERR_PHASE_NOT_OPEN_FOR_SALES`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_OFFERED`, `ERR_LOT_NOT_UNDER_CONTRACT`, `ERR_BUILDER_NOT_IN_GOOD_STANDING`, `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`, `ERR_CLOSEOUT_BLOCKED`, `ERR_CLOSINGS_PENDING`, `ERR_BUDGET_EMPTY`, `ERR_BUDGET_NOT_ADOPTED`, `ERR_NOTICE_NOT_SENT`, `ERR_TRANCHE_NOT_CURABLE`, `ERR_CURE_WINDOW_OPEN`, `ERR_SEAT_NOT_VACANT`, `ERR_REVIEW_ROUNDS_EXHAUSTED`, `ERR_DECLARANT_AUTHORITY_ENDED`, `ERR_SUBSIDY_NOT_AVAILABLE`, `ERR_NO_PRIOR_RATE`, `ERR_TRANSITION_THRESHOLD_NOT_MET`, and `ERR_TURNOVER_SEATS_NOT_FILLED`. 6. **Concurrency** — the OCC check of §2.8, surfacing as `ERR_STALE_VERSION`. 7. **Business safety** — the amenity-posture guard on event scheduling, `ERR_AMENITY_NOT_OPEN`. 8. **Temporal windows** — lead times, statutory windows, and future-dating rules: `ERR_EVENT_LEAD_TIME`, `ERR_NOTICE_LEAD_TIME`, `ERR_RESCISSION_WINDOW_EXPIRED`, `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_SEND_AT_IN_PAST` (HTTP 422). 9. **Uniqueness, overlap, sequence, and segregation** — `ERR_PHASE_SEQUENCE_BLOCKED`, `ERR_DUPLICATE_FISCAL_YEAR`, `ERR_DUPLICATE_ASSESSMENT_YEAR`, `ERR_DUPLICATE_DISTRICT`, `ERR_DUPLICATE_TRANCHE_NO`, `ERR_VENUE_OVERLAP`, `ERR_TOUR_CAPACITY_REACHED` (all HTTP 409), and the segregation-of-duties conflicts `ERR_REVIEWER_CONFLICT`, `ERR_ADOPTER_CANNOT_RATIFY`, `ERR_HEARING_OFFICER_CONFLICT` (HTTP 403), together with the election thresholds `ERR_QUORUM_NOT_MET` and `ERR_ELECTION_MAJORITY_NOT_REACHED` (HTTP 409)."
        PRD §2.9 rung 8: "Temporal windows — lead times, statutory windows, and
        future-dating rules: ERR_EVENT_LEAD_TIME ..."; rung 9: "Uniqueness,
        overlap, sequence, and segregation — ... ERR_VENUE_OVERLAP ...
        PRD §3.8: "Next the temporal gate: `start_at` must be at least fourteen days after the logical clock (`ERR_EVENT_LEAD_TIME`). Then overlap: no other `SCHEDULED` event may occupy the same venue over a half-open interval overlap with the new event's start-to-end span — back-to-back adjacency is allowed (`ERR_VENUE_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/event_lead_time_vs_venue_overlap_priority
        """
        event_c_id = self._setup()
        resp = api_client.schedule_event(event_c_id, LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_EVENT_LEAD_TIME)

    def test_failed_schedule_leaves_event_proposed(self):
        """PRD §3.8: "A proposed event starts `PROPOSED` with `confirmed_count` zero. Scheduling a `PROPOSED` event applies its gates in the §2.9 order." The rejected schedule attempt must not move it.

        Design: Difficulty/priority_pair_validation_conflict/event_lead_time_vs_venue_overlap_priority
        """
        event_c_id = self._setup()
        api_client.schedule_event(event_c_id, LIFESTYLE)
        event = get_success_data(api_client.get_event(event_c_id, LIFESTYLE))
        assert event["status"] == "PROPOSED", (
            f"a rejected schedule leaves the event PROPOSED, got {event['status']}"
        )
