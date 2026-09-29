"""Validation rules whose boundary is the whole point: the timeliness instant a
protest may still be filed at, the identity that may not decide both sides of a
bid, the cumulative extension allowance an addendum may not breach, the trigger
event a ground needs before its window can be dated, the solicitation a
challenged bid must sit on, and the deadline that turns a question into a
record-only filing.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    DUAL_HAT_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    REVIEWER_USER_ID,
    make_officer_headers,
    make_reviewer_headers,
    make_vendor_headers,
)

# ---------------------------------------------------------------- the calendar
CLOCK_START = "2026-08-01T00:00:00Z"
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"
BID_DUE_UTC = "2026-08-27T00:00:00Z"

# One day before the advertised bid due instant: the deadline a
# SOLICITATION_IMPROPRIETY protest is measured against.
IMPROPRIETY_DEADLINE_UTC = "2026-08-26T00:00:00Z"
ONE_MILLISECOND_LATE_UTC = "2026-08-26T00:00:00.001Z"

# A ten-million-cent procurement: the top of the first ad valorem rate tier.
ESTIMATED_VALUE_CENTS = 10000000

# 25000 flat base + 7500 ad valorem (10000000 * 0.00075)
# + 3138 grounds surcharge (25000 * 0.1255 = 3137.5, rounded half-up).
IMPROPRIETY_FEE_CENTS = 35638
FUNDED_BALANCE_CENTS = 100000
BALANCE_AFTER_FEE_CENTS = FUNDED_BALANCE_CENTS - IMPROPRIETY_FEE_CENTS


def _instant(value: str) -> datetime:
    """Parse a rendered ISO 8601 UTC instant, whose fractional digits are
    optional, into a comparable datetime."""
    assert isinstance(value, str) and value, "expected an ISO 8601 instant, got {!r}".format(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual: Any, expected_iso: str, label: str = "instant") -> None:
    assert _instant(actual) == _instant(expected_iso), "{} should be {}, got {}".format(
        label, expected_iso, actual
    )


def _requirement(code: str, description: str) -> Dict[str, Any]:
    return {
        "requirement_code": code,
        "description": description,
        "materiality": "MATERIAL",
        "is_waivable": False,
    }


def _funded_vendor(legal_name: str, tax_id: str) -> Dict[str, Any]:
    vendor = fx.create_vendor(
        legal_name=legal_name,
        tax_id=tax_id,
        contact_email="v{}@example.gov".format(tax_id[-2:]),
    )
    fx.fund_vendor(vendor["id"], FUNDED_BALANCE_CENTS)
    return vendor


def _issued_solicitation(
    solicitation_number: str,
    title: str,
    requirement: Dict[str, Any],
    estimated_value_cents: int = ESTIMATED_VALUE_CENTS,
) -> Dict[str, Any]:
    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=estimated_value_cents,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[requirement],
    )
    return fx.issue_solicitation(solicitation["id"])


def _protest_count_on(solicitation_id: str) -> int:
    _rows, meta = validate_paginated(
        api_client.list_protests(OFFICER_HEADERS, params={"solicitation_id": solicitation_id})
    )
    return meta["total_count"]


def _vendor_balance(vendor_id: str) -> int:
    return fx.read_vendor(vendor_id)["protest_fee_balance_cents"]


def _escrow(solicitation_id: str) -> int:
    return fx.read_solicitation(solicitation_id)["protest_escrow_cents"]


# ==========================================================================
# The timeliness boundary of a solicitation-impropriety protest
# ==========================================================================
class TestProtestTimelinessDeadlineBoundary:
    """A protest filed at the deadline instant itself, and the same protest one
    millisecond later."""

    @staticmethod
    def _setup_prospective_bidder():
        """A vendor with a funded purse and a pending question on an advertised
        solicitation, which is what gives it prospective-bidder standing."""
        fx.set_clock(CLOCK_START)
        vendor = _funded_vendor("Ashford Culvert Works", "100000055")
        solicitation = _issued_solicitation(
            "SOL-2238-C22",
            "Box Culvert Extension",
            _requirement("REQ-PRECAST", "precast plant certification"),
        )
        fx.submit_question(
            solicitation["id"],
            vendor["id"],
            question_text="will a cast in place alternate be allowed?",
        )
        return vendor["id"], solicitation["id"]

    def test_protest_filed_at_exactly_the_deadline_instant_is_accepted(self):
        """A filing is timely when the logical clock is at or before
        `timeliness_deadline_utc`; filing at exactly the deadline instant is timely.
        For `SOLICITATION_IMPROPRIETY`, the trigger event is the solicitation's
        `effective_bid_due_utc`, and the deadline is one day *before* that instant
        — improprieties in the solicitation itself must be raised before bids are
        due, not after.

        Design: Corner/validations/corner_protest_filed_at_exactly_the_timeliness_deadline_is_accepted
        """
        vendor_id, solicitation_id = self._setup_prospective_bidder()

        fx.set_clock(IMPROPRIETY_DEADLINE_UTC)
        response = api_client.create_protest(
            fac.protest_payload(
                solicitation_id,
                vendor_id,
                grounds_code="SOLICITATION_IMPROPRIETY",
                narrative="the precast plant certification excludes cast in place construction",
            ),
            make_vendor_headers(vendor_id),
        )
        protest = validate_success(response, expected_status=201)

        assert protest["status"] == "FILED"
        assert protest["stay_status"] == "ACTIVE"
        _assert_instant(protest["filed_at_utc"], IMPROPRIETY_DEADLINE_UTC, "filed_at_utc")
        _assert_instant(
            protest["timeliness_deadline_utc"],
            IMPROPRIETY_DEADLINE_UTC,
            "timeliness_deadline_utc",
        )
        assert _instant(protest["filed_at_utc"]) == _instant(protest["timeliness_deadline_utc"])

        assert protest["filing_fee_cents"] == IMPROPRIETY_FEE_CENTS
        assert protest["standing_basis"] == "PROSPECTIVE_BIDDER"

        assert _vendor_balance(vendor_id) == BALANCE_AFTER_FEE_CENTS
        assert _escrow(solicitation_id) == IMPROPRIETY_FEE_CENTS

    def test_protest_filed_one_millisecond_after_the_deadline_is_untimely(self):
        """A filing after it is refused with `ERR_PROTEST_UNTIMELY`. Timeliness is
        evaluated before the fee is debited.

        Design: Corner/validations/corner_protest_filed_at_exactly_the_timeliness_deadline_is_accepted
        """
        vendor_id, solicitation_id = self._setup_prospective_bidder()

        fx.set_clock(ONE_MILLISECOND_LATE_UTC)
        response = api_client.create_protest(
            fac.protest_payload(
                solicitation_id,
                vendor_id,
                grounds_code="SOLICITATION_IMPROPRIETY",
                narrative="the precast plant certification excludes cast in place construction",
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(response, ApiErrorId.ERR_PROTEST_UNTIMELY.value, expected_status=409)

        assert _protest_count_on(solicitation_id) == 0
        assert _vendor_balance(vendor_id) == FUNDED_BALANCE_CENTS
        assert _escrow(solicitation_id) == 0


# ==========================================================================
# Segregation of duties between the two determinations on one bid
# ==========================================================================
class TestResponsibilityReviewerSegregationOfDuties:
    """The individual who recorded the responsiveness determination is refused
    the responsibility review of the same bid, while a colleague is not."""

    REVIEW_PAYLOAD = {
        "financial_capacity_score": 80,
        "past_performance_score": 85,
        "integrity_score": 90,
        "determination": "RESPONSIBLE",
        "notes": "same individual attempting both determinations",
    }

    @staticmethod
    def _setup_responsive_bid_decided_by_the_dual_hat_officer():
        """One bid walked to a RESPONSIVE determination recorded by the operator
        who will then try to review responsibility as well."""
        fx.set_clock(CLOCK_START)
        vendor = fx.create_vendor(
            legal_name="Brookfield Signage",
            tax_id="100000056",
            contact_email="v56@example.gov",
        )
        solicitation = _issued_solicitation(
            "SOL-2238-C23",
            "Overhead Sign Structure Inspection",
            _requirement("REQ-NDT", "non destructive testing technician"),
        )
        solicitation_id = solicitation["id"]

        bid = fx.submit_bid(
            solicitation_id,
            vendor["id"],
            total_price_cents=8000000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(solicitation_id),
        )

        fx.set_clock(QUESTION_DEADLINE_UTC)
        fx.close_question_period(solicitation_id)
        fx.set_clock(BID_DUE_UTC)
        fx.open_bids(solicitation_id)

        fx.determine_responsiveness(
            bid["id"],
            headers=make_officer_headers(DUAL_HAT_USER_ID),
            determination="RESPONSIVE",
            reason_codes=[],
        )
        return solicitation_id, bid["id"]

    def test_the_responsiveness_decider_is_refused_the_responsibility_review(self):
        """The `X-User-ID` of the acting `ResponsibilityReviewer` must differ from
        the `responsiveness_decided_by_user_id` stamped on the bid; if they match,
        the review is rejected with `ERR_REVIEWER_CONFLICT`.

        Design: Corner/validations/corner_responsibility_review_by_the_responsiveness_decider_rejected
        """
        solicitation_id, bid_id = self._setup_responsive_bid_decided_by_the_dual_hat_officer()

        response = api_client.create_responsibility_review(
            bid_id,
            fac.responsibility_review_payload(**self.REVIEW_PAYLOAD),
            make_reviewer_headers(DUAL_HAT_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_REVIEWER_CONFLICT.value, expected_status=403)

        bid = fx.read_bid(bid_id)
        assert bid["responsibility_status"] == "NOT_REVIEWED"
        assert bid["responsiveness_decided_by_user_id"] == DUAL_HAT_USER_ID

        # The refused review did not fire the automatic advance out of EVALUATION.
        assert fx.read_solicitation(solicitation_id)["status"] == "EVALUATION"

        _rows, meta = validate_paginated(
            api_client.list_responsibility_reviews(bid_id, OFFICER_HEADERS)
        )
        assert meta["total_count"] == 0

    def test_a_reviewer_who_did_not_decide_responsiveness_records_the_same_review(self):
        """The officer who determined a bid's responsiveness may not also review
        that bidder's responsibility.

        Design: Corner/validations/corner_responsibility_review_by_the_responsiveness_decider_rejected
        """
        _solicitation_id, bid_id = self._setup_responsive_bid_decided_by_the_dual_hat_officer()

        conflicted = api_client.create_responsibility_review(
            bid_id,
            fac.responsibility_review_payload(**self.REVIEW_PAYLOAD),
            make_reviewer_headers(DUAL_HAT_USER_ID),
        )
        validate_error(conflicted, ApiErrorId.ERR_REVIEWER_CONFLICT.value, expected_status=403)

        accepted = api_client.create_responsibility_review(
            bid_id,
            fac.responsibility_review_payload(**self.REVIEW_PAYLOAD),
            REVIEWER_HEADERS,
        )
        review = validate_success(accepted, expected_status=201)

        assert review["reviewer_user_id"] == REVIEWER_USER_ID
        assert review["determination"] == "RESPONSIBLE"
        assert review["composite_score"] == pytest.approx(85.00, abs=0.01)
        assert fx.read_bid(bid_id)["responsibility_status"] == "RESPONSIBLE"


# ==========================================================================
# The cumulative bid-due extension allowance
# ==========================================================================
class TestCumulativeExtensionCap:
    """Two individually legal extensions whose sum is not."""

    def test_addendum_breaching_the_cumulative_cap_is_rejected_in_full(self):
        """If adding the requested `extends_bid_due_by_days` to the existing
        cumulative total would push it past 21 days, the addendum is rejected in
        full with `ERR_EXTENSION_CAP_EXCEEDED` — no partial extension is applied,
        no requirement rows are created, and `addendum_count` is not incremented.

        Design: Corner/validations/corner_addendum_breaching_the_cumulative_extension_cap_is_rejected_whole
        """
        fx.set_clock(CLOCK_START)
        solicitation = _issued_solicitation(
            "SOL-2238-C24",
            "District Salt Shed Construction",
            _requirement("REQ-FABRIC", "fabric structure engineering seal"),
        )
        solicitation_id = solicitation["id"]

        fx.add_addendum(
            solicitation_id,
            summary="revised foundation details",
            extends_bid_due_by_days=15,
            acknowledgment_required=True,
            new_requirement_codes=[],
        )

        response = api_client.create_addendum(
            solicitation_id,
            fac.addendum_payload(
                summary="added a geotechnical report",
                extends_bid_due_by_days=7,
                acknowledgment_required=True,
                new_requirement_codes=[],
            ),
            OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED.value, expected_status=422
        )

        # Neither the whole 7 days nor the 6 that would have fitted were applied.
        after = fx.read_solicitation(solicitation_id)
        assert after["cumulative_extension_days"] == 15
        assert after["addendum_count"] == 1
        _assert_instant(
            after["effective_bid_due_utc"], "2026-09-11T00:00:00Z", "effective_bid_due_utc"
        )
        _assert_instant(
            after["question_deadline_utc"], "2026-09-04T00:00:00Z", "question_deadline_utc"
        )

        rows, meta = validate_paginated(api_client.list_addenda(solicitation_id, OFFICER_HEADERS))
        assert meta["total_count"] == 1
        assert [row["sequence_number"] for row in rows] == [1]


# ==========================================================================
# The trigger event an award-impropriety ground needs
# ==========================================================================
class TestAwardImproprietyProtestWithoutAnAward:
    """The ground names an award as its trigger event, and there is none."""

    def test_award_impropriety_protest_without_an_award_is_refused(self):
        """For `AWARD_IMPROPRIETY`, the trigger event is the `created_at` of the
        award on the solicitation with the greatest `created_at` among awards whose
        `status` is `PENDING_STAY` or `EXECUTED`; if no such award exists, the
        filing is refused with `ERR_PROTEST_TRIGGER_EVENT_MISSING`. Timeliness is
        evaluated before the fee is debited.

        Design: Corner/validations/corner_award_impropriety_protest_without_an_award_is_rejected
        """
        fx.set_clock(CLOCK_START)
        vendor = _funded_vendor("Coldspring Fabricators", "100000057")
        vendor_id = vendor["id"]
        solicitation = _issued_solicitation(
            "SOL-2238-C25",
            "Sign Post Fabrication",
            _requirement("REQ-STEEL", "domestic steel certification"),
        )
        solicitation_id = solicitation["id"]

        bid = fx.submit_bid(
            solicitation_id,
            vendor_id,
            total_price_cents=8000000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(solicitation_id),
        )

        fx.set_clock(QUESTION_DEADLINE_UTC)
        fx.close_question_period(solicitation_id)
        fx.set_clock(BID_DUE_UTC)
        fx.open_bids(solicitation_id)
        fx.determine_responsiveness(bid["id"], determination="RESPONSIVE", reason_codes=[])

        response = api_client.create_protest(
            fac.protest_payload(
                solicitation_id,
                vendor_id,
                grounds_code="AWARD_IMPROPRIETY",
                narrative="the agency intends to award to a higher bidder",
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(
            response,
            ApiErrorId.ERR_PROTEST_TRIGGER_EVENT_MISSING.value,
            expected_status=422,
        )

        assert _protest_count_on(solicitation_id) == 0
        assert _vendor_balance(vendor_id) == FUNDED_BALANCE_CENTS
        assert _escrow(solicitation_id) == 0


# ==========================================================================
# The solicitation a challenged bid must belong to
# ==========================================================================
class TestChallengedBidMustBelongToTheProtestedSolicitation:
    """A bid that resolves, but on the wrong procurement."""

    def test_challenged_bid_from_another_solicitation_is_refused(self):
        """When supplied, the challenged bid must belong to the protested
        solicitation, else `ERR_BID_NOT_ON_SOLICITATION`.

        Design: Corner/validations/corner_challenged_bid_from_another_solicitation_is_rejected
        """
        fx.set_clock(CLOCK_START)
        vendor = _funded_vendor("Dunmore Paving", "100000058")
        vendor_id = vendor["id"]

        protested = _issued_solicitation(
            "SOL-2238-C26",
            "Shoulder Widening District Four",
            _requirement("REQ-AGG", "aggregate source approval"),
        )
        other = _issued_solicitation(
            "SOL-2238-C27",
            "Shoulder Widening District Five",
            _requirement("REQ-AGG", "aggregate source approval"),
        )
        protested_id = protested["id"]
        other_id = other["id"]

        # A bid on the protested procurement, which is what confers
        # ACTUAL_BIDDER standing there.
        fx.submit_bid(
            protested_id,
            vendor_id,
            total_price_cents=8600000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(protested_id),
        )
        # And a bid on the other procurement, carried far enough for its
        # responsiveness determination — the trigger event a
        # RESPONSIVENESS_DETERMINATION protest is dated from — to exist.
        foreign_bid = fx.submit_bid(
            other_id,
            vendor_id,
            total_price_cents=8500000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(other_id),
        )
        fx.set_clock(QUESTION_DEADLINE_UTC)
        fx.close_question_period(other_id)
        fx.set_clock(BID_DUE_UTC)
        fx.open_bids(other_id)
        foreign_bid = fx.determine_responsiveness(
            foreign_bid["id"], determination="RESPONSIVE"
        )

        response = api_client.create_protest(
            fac.protest_payload(
                protested_id,
                vendor_id,
                grounds_code="RESPONSIVENESS_DETERMINATION",
                narrative="the responsiveness determination misread the aggregate source clause",
                challenged_bid_id=foreign_bid["id"],
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(
            response, ApiErrorId.ERR_BID_NOT_ON_SOLICITATION.value, expected_status=422
        )

        assert _protest_count_on(protested_id) == 0
        assert _vendor_balance(vendor_id) == FUNDED_BALANCE_CENTS
        assert _escrow(protested_id) == 0


# ==========================================================================
# The question deadline, and the record-only filing it produces
# ==========================================================================
class TestQuestionAfterTheDeadline:
    """A late question is a row rather than an error, until the period closes."""

    @staticmethod
    def _setup_issued_solicitation_past_its_question_deadline():
        """An advertised solicitation whose question deadline has passed while it
        is still open, plus a funded vendor with nothing else on the record."""
        fx.set_clock(CLOCK_START)
        vendor = _funded_vendor("Eastgate Traffic Control", "100000059")
        solicitation = _issued_solicitation(
            "SOL-2238-C28",
            "Work Zone Traffic Control Services",
            _requirement("REQ-FLAG", "certified flagger roster"),
        )
        fx.set_clock("2026-08-21T00:00:00Z")
        return vendor["id"], solicitation["id"]

    @staticmethod
    def _late_question_payload(vendor_id: str) -> Dict[str, Any]:
        return fac.question_payload(
            vendor_id,
            question_text="may flaggers be certified by a neighbouring state?",
        )

    def test_question_after_the_deadline_is_created_rejected_late(self):
        """A question filed after that instant, while the solicitation is still
        `ISSUED`, is created directly in `status` `REJECTED_LATE` and can never be
        answered — the row exists so that the record shows the question was asked,
        and its `answer_summary` and `answered_via_addendum_sequence` both stay
        null forever.

        Design: Corner/validations/corner_question_submitted_after_the_deadline_is_stamped_rejected_late
        """
        vendor_id, solicitation_id = self._setup_issued_solicitation_past_its_question_deadline()

        response = api_client.submit_question(
            solicitation_id,
            self._late_question_payload(vendor_id),
            make_vendor_headers(vendor_id),
        )
        question = validate_success(response, expected_status=201)

        assert question["status"] == "REJECTED_LATE"
        _assert_instant(question["submitted_at_utc"], "2026-08-21T00:00:00Z", "submitted_at_utc")
        assert question["answer_summary"] is None
        assert question["answered_via_addendum_sequence"] is None

    def test_a_rejected_late_question_confers_no_prospective_bidder_standing(self):
        """Alternatively, and only for the `SOLICITATION_IMPROPRIETY` ground, a
        protester that filed a question submission on the solicitation whose
        `status` is `PENDING` or `ANSWERED` has standing as a `PROSPECTIVE_BIDDER`.
        Where neither basis is satisfied, the filing is refused with
        `ERR_PROTESTER_LACKS_STANDING` (HTTP 403).

        Design: Corner/validations/corner_question_submitted_after_the_deadline_is_stamped_rejected_late
        """
        vendor_id, solicitation_id = self._setup_issued_solicitation_past_its_question_deadline()

        late = validate_success(
            api_client.submit_question(
                solicitation_id,
                self._late_question_payload(vendor_id),
                make_vendor_headers(vendor_id),
            ),
            expected_status=201,
        )
        assert late["status"] == "REJECTED_LATE"

        response = api_client.create_protest(
            fac.protest_payload(
                solicitation_id,
                vendor_id,
                grounds_code="SOLICITATION_IMPROPRIETY",
                narrative="the certified flagger roster clause is unduly restrictive",
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(
            response, ApiErrorId.ERR_PROTESTER_LACKS_STANDING.value, expected_status=403
        )

        assert _protest_count_on(solicitation_id) == 0
        assert _vendor_balance(vendor_id) == FUNDED_BALANCE_CENTS
        assert _escrow(solicitation_id) == 0

    def test_the_same_question_is_refused_outright_once_the_period_closes(self):
        """Once the solicitation has advanced to `QUESTION_PERIOD_CLOSED` or
        beyond, a question submission is refused outright with
        `ERR_QUESTION_PERIOD_CLOSED` and no row is created at all.

        Design: Corner/validations/corner_question_submitted_after_the_deadline_is_stamped_rejected_late
        """
        vendor_id, solicitation_id = self._setup_issued_solicitation_past_its_question_deadline()

        validate_success(
            api_client.submit_question(
                solicitation_id,
                self._late_question_payload(vendor_id),
                make_vendor_headers(vendor_id),
            ),
            expected_status=201,
        )

        fx.close_question_period(solicitation_id)

        response = api_client.submit_question(
            solicitation_id,
            self._late_question_payload(vendor_id),
            make_vendor_headers(vendor_id),
        )
        validate_error(
            response, ApiErrorId.ERR_QUESTION_PERIOD_CLOSED.value, expected_status=409
        )

        rows, meta = validate_paginated(
            api_client.list_questions(solicitation_id, OFFICER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["status"] for row in rows] == ["REJECTED_LATE"]
