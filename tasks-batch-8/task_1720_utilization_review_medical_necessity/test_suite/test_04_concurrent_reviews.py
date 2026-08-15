"""Concurrent continued-stay reviews: parent-state gating, the cadence
schedule, deadline precision, and certified-interval overlap (PRD §2.9,
§3.4)."""
from test_helpers import (
    ApiErrorId,
    REVIEW_DUE_FIRST,
    TEST_USERS,
    assert_timestamp_instant_equal,
    concurrent_review_decision_payload,
    create_concurrent_review_payload,
    get_case,
    get_concurrent_review,
    list_concurrent_reviews,
    make_concurrent_review,
    set_clock,
    setup_approved_auth,
    setup_submitted_auth,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]


class TestParentStateGate:
    def test_concurrent_review_rejected_while_auth_submitted(self, api):
        """PRD §3.4: "A `URNurse` submits a **ConcurrentReview** against an `APPROVED` authorization request — the request's `id` becomes the review's `authorization_request_id` — with a `clinical_update` narrative and a `requested_additional_day_count` (at least 1)."
        PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/concurrent_review_requires_auth_approved
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-CE1")
        auth = ctx["auth"]
        assert auth["status"] == "SUBMITTED"

        resp = api.create_concurrent_review(
            auth["id"],
            create_concurrent_review_payload(
                clinical_update="Day 2: still on IV diuresis, net negative 1.5L.",
                requested_additional_day_count=2),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert list_concurrent_reviews(auth["id"]) == []

    def test_concurrent_review_created_after_approval(self, api):
        """PRD §3.4: "The server assigns `sequence_index` — the 1-based ordinal among reviews of the same authorization — stamps `submitted_at`, and computes `review_due_at` by the cadence rule: for the first review of the authorization the anchor is the parent authorization's `APPROVED`-transition `decided_at`, and for each subsequent review the anchor is the previous review's `decided_at`; the deadline is the anchor plus the payer's `concurrent_review_cadence_hours`."

        Design: Difficulty/cross_entity_state_dependency/concurrent_review_requires_auth_approved
        """
        ctx = setup_approved_auth(patient_mrn="MRN-CE1B")
        review = validate_success(api.create_concurrent_review(
            ctx["auth"]["id"],
            create_concurrent_review_payload(
                clinical_update="Day 2: still on IV diuresis, net negative 1.5L.",
                requested_additional_day_count=2),
            NURSE), expected_status=201)
        assert review["status"] == "SUBMITTED"
        assert review["sequence_index"] == 1
        # Approval decided at 2026-08-02T12:00:00Z + 48h cadence.
        assert_timestamp_instant_equal(review["review_due_at"], REVIEW_DUE_FIRST,
                                       "review_due_at")


class TestCadenceSchedule:
    def test_review_due_at_chronological_anchor(self, api):
        """PRD §3.4: "for the first review of the authorization the anchor is the parent authorization's `APPROVED`-transition `decided_at`, and for each subsequent review the anchor is the previous review's `decided_at`; the deadline is the anchor plus the payer's `concurrent_review_cadence_hours`."

        Design: Corner/calculations/review_due_at_chronological_anchor
        """
        ctx = setup_approved_auth(patient_mrn="MRN-CAD", requested_day_count=5)
        auth = ctx["auth"]
        cr1 = make_concurrent_review(
            auth["id"],
            clinical_update="Day 2 update: persistent hypoxia, continuing IV therapy.",
            requested_additional_day_count=2)
        assert_timestamp_instant_equal(cr1["review_due_at"],
                                       "2026-08-04T12:00:00Z",
                                       "first review_due_at")

        set_clock("2026-08-03T09:00:00Z")
        decided1 = validate_success(api.concurrent_review_payer_decision(
            cr1["id"],
            concurrent_review_decision_payload(
                "APPROVE", approved_day_count=2, certified_day_start=4),
            PAYER_REVIEWER))
        assert decided1["status"] == "APPROVED"

        cr2 = make_concurrent_review(
            auth["id"],
            clinical_update="Day 4 update: weaning diuresis, monitoring electrolytes.",
            requested_additional_day_count=2)
        assert cr2["sequence_index"] == 2
        # The second review anchors on the first review's decided_at
        # (2026-08-03T09:00:00Z + 48h).
        assert_timestamp_instant_equal(cr2["review_due_at"],
                                       "2026-08-05T09:00:00Z",
                                       "second review_due_at")

    def test_review_overdue_and_exact_deadline(self, api):
        """PRD §3.4: "Submission after the deadline fails: when logical now is past `review_due_at` the create is rejected with `ERR_REVIEW_OVERDUE`, with equality allowed — submission at exactly `review_due_at` is on time."
        PRD §2.11: "A `URDirector` may advance the clock to a supplied `to_iso8601` instant via an admin-only test-driving capability; monotonicity is not enforced, so tests may rewind."

        Design: Corner/validations/review_overdue_and_exact_deadline
        """
        ctx = setup_approved_auth(patient_mrn="MRN-OVD")
        auth = ctx["auth"]

        set_clock("2026-08-04T12:00:01Z")  # one second past review_due_at
        resp = api.create_concurrent_review(
            auth["id"],
            create_concurrent_review_payload(
                clinical_update="Late submission attempt.",
                requested_additional_day_count=2),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_REVIEW_OVERDUE, expected_status=422)

        set_clock("2026-08-04T12:00:00Z")  # exactly the deadline instant
        review = validate_success(api.create_concurrent_review(
            auth["id"],
            create_concurrent_review_payload(
                clinical_update="On-time submission at the exact deadline.",
                requested_additional_day_count=2),
            NURSE), expected_status=201)
        assert review["status"] == "SUBMITTED"


class TestPayerDecisionOnReview:
    def test_concurrent_review_partial_approval(self, api):
        """PRD §3.4: "A full approval sets `approved_day_count` equal to `requested_additional_day_count`; a partial approval requires an `approved_day_count` strictly between 1 and the requested count; both grant an interval beginning at the payload's `certified_day_start`, tagged with the parent authorization's level of care, subject to the same overlap and budget rules as an initial approval."

        Design: Corner/endpoints/concurrent_review_partial_approval
        """
        ctx = setup_approved_auth(patient_mrn="MRN-PRT")
        review = make_concurrent_review(
            ctx["auth"]["id"],
            clinical_update="Day 2: improving but still hypoxic on exertion.",
            requested_additional_day_count=2)

        decided = validate_success(api.concurrent_review_payer_decision(
            review["id"],
            concurrent_review_decision_payload(
                "PARTIAL", approved_day_count=1, certified_day_start=4),
            PAYER_REVIEWER))
        assert decided["status"] == "PARTIALLY_APPROVED"
        assert decided["approved_day_count"] == 1
        assert decided["certified_day_start"] == 4
        assert decided["certified_day_end"] == 5
        assert get_case(ctx["case"]["id"])["certified_day_count"] == 4


class TestCertifiedIntervalOverlap:
    def _setup_review_on_approved_auth(self, api):
        ctx = setup_approved_auth(patient_mrn="MRN-ADJ")
        review = make_concurrent_review(
            ctx["auth"]["id"],
            clinical_update="Day 2: persistent hypoxia, continued monitoring required.",
            requested_additional_day_count=2)
        return ctx, review

    def test_certified_interval_overlap_rejected(self, api):
        """PRD §2.9: "Intervals on the same case may be adjacent — a new interval starting exactly at an existing interval's end is allowed — but may never intersect; an overlapping grant is rejected with `ERR_CERTIFIED_DAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certified_day_interval_adjacency
        """
        ctx, review = self._setup_review_on_approved_auth(api)
        # Existing certified interval [1,4); start 3 intersects it.
        resp = api.concurrent_review_payer_decision(
            review["id"],
            concurrent_review_decision_payload(
                "APPROVE", approved_day_count=2, certified_day_start=3),
            PAYER_REVIEWER)
        validate_error(resp, ApiErrorId.ERR_CERTIFIED_DAY_OVERLAP,
                       expected_status=409)
        current = get_concurrent_review(ctx["auth"]["id"], review["id"])
        assert current["status"] == "SUBMITTED", (
            "a rejected decision leaves the review decidable")

    def test_certified_interval_adjacency_allowed(self, api):
        """PRD §2.9: "Payer approvals grant certified bed days as half-open intervals on a 1-based hospital-day index: an approval carries `certified_day_start` (inclusive) and a day count, and the granted interval ends at `certified_day_end` (exclusive), so the interval is the range from `certified_day_start` up to but not including `certified_day_end`."
        PRD §2.9: "Intervals on the same case may be adjacent — a new interval starting exactly at an existing interval's end is allowed — but may never intersect; an overlapping grant is rejected with `ERR_CERTIFIED_DAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certified_day_interval_adjacency
        """
        ctx, review = self._setup_review_on_approved_auth(api)
        # Start 4 is exactly the existing interval's exclusive end.
        decided = validate_success(api.concurrent_review_payer_decision(
            review["id"],
            concurrent_review_decision_payload(
                "APPROVE", approved_day_count=2, certified_day_start=4),
            PAYER_REVIEWER))
        assert decided["status"] == "APPROVED"
        assert decided["certified_day_start"] == 4
        assert decided["certified_day_end"] == 6
        assert get_case(ctx["case"]["id"])["certified_day_count"] == 5
