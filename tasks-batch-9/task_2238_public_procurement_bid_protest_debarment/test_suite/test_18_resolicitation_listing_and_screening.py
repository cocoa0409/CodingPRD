"""Putting a cancelled procurement back out to market, publishing the debarred
vendor file and screening the parties who never bid.

Three narrow seams meet here. Resolicitation is a two-row outcome from a single
officer action: the cancelled predecessor becomes terminal and a fresh draft
successor appears carrying only the requirements of the original advertisement.
The debarred-vendor list is a snapshot rather than a plain filter, so an
interim-suspended respondent stays off it until the reader asks for suspensions,
and a debarment whose window closes exactly at the as-of instant has already
dropped off. Subcontractor screening resolves inside the request that creates
it, and refuses a self-loop or an out-of-range tier before any row is written.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import OFFICER_HEADERS

# The procurement calendar these cases run on.
NOTICE_UTC = "2026-08-01T00:00:00Z"
DECISION_UTC = "2026-08-16T00:00:00Z"
DEBARMENT_END_UTC = "2027-08-16T00:00:00Z"

# The successor's freshly advertised dates.
SUCCESSOR_BID_DUE_UTC = "2026-10-01T00:00:00Z"
SUCCESSOR_QUESTION_DEADLINE_UTC = "2026-09-24T00:00:00Z"

# REPEATED_NONPERFORMANCE 20 + SAFETY_VIOLATION 15, no mitigation, no prior
# strike, which reads off the twelve-month tier.
FINAL_SEVERITY = 35.00
PERIOD_MONTHS = 12


def _instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant so that two renderings of the same instant
    compare equal rather than by string shape."""
    assert isinstance(value, str), "expected an ISO 8601 instant, got {!r}".format(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _requirement_codes(rows) -> list:
    return [row["requirement_code"] for row in rows]


# ==========================================================================
# Resolicitation
# ==========================================================================
def _build_cancelled_procurement_with_an_addendum_requirement() -> Dict[str, Any]:
    """One advertised procurement whose addendum introduced a second material
    requirement, then cancelled for lack of appropriation."""
    fx.reset_clock()

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C41",
        title="Culvert Lining Package",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-BASE",
                description="cured in place liner",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation_id = solicitation["id"]
    fx.issue_solicitation(solicitation_id)
    fx.add_addendum(
        solicitation_id,
        summary="adds a bypass pumping requirement",
        extends_bid_due_by_days=0,
        acknowledgment_required=True,
        new_requirement_codes=[
            fac.requirement_payload(
                requirement_code="REQ-ADD",
                description="bypass pumping plan",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    fx.cancel_solicitation(solicitation_id, cancellation_reason="funding withdrawn")

    predecessor = fx.read_solicitation(solicitation_id)
    assert predecessor["status"] == "CANCELLED"

    return {
        "solicitation_id": solicitation_id,
        "predecessor_at_cancellation": predecessor,
    }


@pytest.fixture
def resolicited_procurement() -> Dict[str, Any]:
    """The cancelled procurement, put back out to market as a new draft."""
    state = _build_cancelled_procurement_with_an_addendum_requirement()
    response = api_client.resolicit_solicitation(
        state["solicitation_id"],
        fac.resolicit_payload(
            new_solicitation_number="SOL-2238-C41-R1",
            original_bid_due_utc=SUCCESSOR_BID_DUE_UTC,
            original_question_deadline_utc=SUCCESSOR_QUESTION_DEADLINE_UTC,
        ),
        OFFICER_HEADERS,
    )
    state["resolicit_response"] = response
    state["successor"] = validate_success(response, expected_status=201)
    return state


class TestResolicitingACancelledProcurement:
    """The successor draft, the requirements it inherits and the terminal
    posture of the predecessor it replaces."""

    def test_the_successor_is_a_fresh_draft_pointing_at_its_predecessor(
        self, resolicited_procurement
    ):
        """A successor solicitation is created in `DRAFT` with its `predecessor_solicitation_id` pointing at the predecessor and its `solicitation_number` taken from the supplied `new_solicitation_number` — conventionally the predecessor's number suffixed with `-R` and the successor generation number — which must not already be in use, else `ERR_DUPLICATE_SOLICITATION_NUMBER`.

        The officer supplies a `new_solicitation_number` for the successor, together with the successor's `original_bid_due_utc` and `original_question_deadline_utc`.

        Design: Corner/endpoints/corner_resolicit_creates_a_linked_draft_successor
        """
        successor = validate_success(
            resolicited_procurement["resolicit_response"], expected_status=201
        )

        assertions.assert_mutable_audit_fields(successor)
        assert successor["solicitation_number"] == "SOL-2238-C41-R1"
        assert successor["status"] == "DRAFT"
        assert (
            successor["predecessor_solicitation_id"]
            == resolicited_procurement["solicitation_id"]
        )

        # A brand new row: its own counter starts at 1 and it carries no
        # amendment history of its own.
        assert successor["version"] == 1
        assert successor["addendum_count"] == 0

        # The dates the officer advertised for the successor are the successor's
        # own historical record, not the predecessor's.
        assert _instant(successor["original_bid_due_utc"]) == _instant(
            SUCCESSOR_BID_DUE_UTC
        )
        assert _instant(successor["original_question_deadline_utc"]) == _instant(
            SUCCESSOR_QUESTION_DEADLINE_UTC
        )

    def test_only_the_original_advertisement_requirements_are_carried_over(
        self, resolicited_procurement
    ):
        """Every mandatory requirement of the predecessor whose `introduced_by_addendum_sequence` is 0, that is every requirement from the original advertisement, is copied onto the successor; requirements that arrived by addendum are not carried over, since the successor's own amendment history starts empty.

        Design: Corner/endpoints/corner_resolicit_creates_a_linked_draft_successor
        """
        successor_id = resolicited_procurement["successor"]["id"]

        rows, meta = validate_paginated(
            api_client.list_requirements(successor_id, OFFICER_HEADERS)
        )
        assertions.assert_pagination_meta(
            meta, total_count=1, limit=10, offset=0, has_more=False
        )
        assert len(rows) == 1
        assert _requirement_codes(rows) == ["REQ-BASE"]
        assert rows[0]["introduced_by_addendum_sequence"] == 0
        assert rows[0]["materiality"] == "MATERIAL"
        assert rows[0]["solicitation_id"] == successor_id

        # The predecessor keeps both requirements, so the omission above is a
        # copy rule rather than a lost row.
        predecessor_rows, predecessor_meta = validate_paginated(
            api_client.list_requirements(
                resolicited_procurement["solicitation_id"], OFFICER_HEADERS
            )
        )
        assertions.assert_pagination_meta(predecessor_meta, total_count=2, has_more=False)
        assert sorted(_requirement_codes(predecessor_rows)) == ["REQ-ADD", "REQ-BASE"]

    def test_the_predecessor_becomes_terminal_and_versions_exactly_once(
        self, resolicited_procurement
    ):
        """On success the predecessor moves `CANCELLED → RESOLICITED`, which is terminal, and its `version` increments by 1.

        Design: Corner/endpoints/corner_resolicit_creates_a_linked_draft_successor
        """
        predecessor = fx.read_solicitation(resolicited_procurement["solicitation_id"])

        assert predecessor["status"] == "RESOLICITED"
        assert (
            predecessor["version"]
            == resolicited_procurement["predecessor_at_cancellation"]["version"] + 1
        )
        # The link is recorded on the successor, never on the predecessor.
        assert predecessor["predecessor_solicitation_id"] is None


# ==========================================================================
# The debarred-vendor list snapshot
# ==========================================================================
def _build_one_debarred_and_one_suspended_vendor() -> Dict[str, Any]:
    """Two respondents on the compliance docket: one carried to a final
    debarment on the default branch, one merely suspended at notice time."""
    fx.reset_clock()

    debarred_vendor = fx.create_vendor(
        legal_name="Garrick Hauling",
        tax_id="100000085",
        contact_email="v85@example.gov",
    )
    suspended_vendor = fx.create_vendor(
        legal_name="Halloran Hauling",
        tax_id="100000086",
        contact_email="v86@example.gov",
    )

    debarment_proceeding = fx.open_proceeding(
        debarred_vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    suspension_proceeding = fx.open_proceeding(
        suspended_vendor["id"],
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD"],
        mitigating_factor_codes=[],
        interim_suspension=True,
    )

    fx.set_clock(DECISION_UTC)
    fx.hold_debarment_hearing(
        debarment_proceeding["id"], hearing_summary="no response filed"
    )
    decided = fx.decide_debarment(
        debarment_proceeding["id"],
        outcome="DEBARRED",
        rationale="repeated nonperformance with a safety violation",
    )

    # The window the snapshot will be read against.
    assert decided["severity_score"] == pytest.approx(FINAL_SEVERITY, abs=0.01)
    assert decided["debarment_period_months"] == PERIOD_MONTHS
    assert _instant(decided["debarment_end_utc"]) == _instant(DEBARMENT_END_UTC)
    assert suspension_proceeding["debarment_end_utc"] is None

    return {
        "debarred_vendor_id": debarred_vendor["id"],
        "suspended_vendor_id": suspended_vendor["id"],
        "debarment_proceeding_id": debarment_proceeding["id"],
        "suspension_proceeding_id": suspension_proceeding["id"],
    }


@pytest.fixture
def debarment_file() -> Dict[str, Any]:
    return _build_one_debarred_and_one_suspended_vendor()


class TestTheDebarredVendorListSnapshot:
    """What the maintained public list admits by default, what the suspension
    flag adds to it and when a served window drops off it."""

    def test_the_default_snapshot_carries_debarments_only(self, debarment_file):
        """The reader may also supply `include_suspended`: when it is false or omitted, only vendors whose `eligibility_status` is `DEBARRED` are in scope; when it is true, vendors whose `eligibility_status` is `SUSPENDED` are in scope as well.

        Design: Corner/endpoints/corner_debarred_vendor_list_admits_suspensions_only_behind_the_flag
        """
        # The suspended respondent really is on the vendor file and suspended,
        # so its absence below is the flag's default rather than a missing row.
        suspended = fx.read_vendor(debarment_file["suspended_vendor_id"])
        assert suspended["eligibility_status"] == "SUSPENDED"

        rows, meta = validate_paginated(
            api_client.list_debarred_vendors(OFFICER_HEADERS)
        )
        assertions.assert_pagination_meta(
            meta, total_count=1, limit=10, offset=0, has_more=False
        )
        assert len(rows) == 1
        assert rows[0]["id"] == debarment_file["debarred_vendor_id"]
        assert rows[0]["eligibility_status"] == "DEBARRED"
        assert rows[0]["active_debarment_id"] == debarment_file[
            "debarment_proceeding_id"
        ]
        assert debarment_file["suspended_vendor_id"] not in [row["id"] for row in rows]

    def test_the_suspension_flag_admits_the_interim_suspended_respondent(
        self, debarment_file
    ):
        """The reader may also supply `include_suspended`: when it is false or omitted, only vendors whose `eligibility_status` is `DEBARRED` are in scope; when it is true, vendors whose `eligibility_status` is `SUSPENDED` are in scope as well.

        Rows are ordered by the referenced proceeding's `debarment_end_utc` descending, with rows whose `debarment_end_utc` is null sorting first, and ties broken by the vendor's `created_at` ascending.

        Design: Corner/endpoints/corner_debarred_vendor_list_admits_suspensions_only_behind_the_flag
        """
        rows, meta = validate_paginated(
            api_client.list_debarred_vendors(
                OFFICER_HEADERS, params={"include_suspended": "true"}
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=2, limit=10, offset=0, has_more=False
        )
        assert len(rows) == 2

        # The suspension's proceeding has no end instant yet, so it sorts ahead
        # of the twelve-month debarment.
        assert [row["id"] for row in rows] == [
            debarment_file["suspended_vendor_id"],
            debarment_file["debarred_vendor_id"],
        ]
        assert rows[0]["eligibility_status"] == "SUSPENDED"
        assert rows[0]["active_debarment_id"] == debarment_file[
            "suspension_proceeding_id"
        ]
        assert rows[1]["eligibility_status"] == "DEBARRED"
        assert rows[1]["active_debarment_id"] == debarment_file[
            "debarment_proceeding_id"
        ]

    def test_a_window_ending_at_the_as_of_instant_has_already_expired(
        self, debarment_file
    ):
        """Within that status scope, a vendor appears only when its `active_debarment_id` is not null and the proceeding that identifier names either has a null `debarment_end_utc` or has a `debarment_end_utc` strictly greater than the as-of instant — a debarment whose end instant equals the as-of instant has expired and drops off the list.

        Design: Corner/endpoints/corner_debarred_vendor_list_admits_suspensions_only_behind_the_flag
        """
        rows, meta = validate_paginated(
            api_client.list_debarred_vendors(
                OFFICER_HEADERS, params={"as_of_utc": DEBARMENT_END_UTC}
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=0, limit=10, offset=0, has_more=False
        )
        assert rows == []


# ==========================================================================
# Subcontractor screening
# ==========================================================================
def _build_prime_and_debarred_subcontractor() -> Dict[str, Any]:
    """An eligible prime, an advertised solicitation for the subcontract to sit
    under, and a proposed subcontractor already debarred for repeated
    nonperformance."""
    fx.reset_clock()

    prime = fx.create_vendor(
        legal_name="Ingram Prime Contractors",
        tax_id="100000087",
        contact_email="v87@example.gov",
    )
    sub = fx.create_vendor(
        legal_name="Jessup Steel Erectors",
        tax_id="100000088",
        contact_email="v88@example.gov",
    )

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C44",
        title="Pedestrian Bridge Erection",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-09-30T00:00:00Z",
        original_question_deadline_utc="2026-09-23T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-ERECT",
                description="certified steel erector",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    fx.issue_solicitation(solicitation["id"])

    proceeding = fx.open_proceeding(
        sub["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock(DECISION_UTC)
    fx.hold_debarment_hearing(proceeding["id"], hearing_summary="no response filed")
    fx.decide_debarment(
        proceeding["id"],
        outcome="DEBARRED",
        rationale="repeated nonperformance established",
    )

    assert fx.read_vendor(prime["id"])["eligibility_status"] == "ELIGIBLE"
    assert fx.read_vendor(sub["id"])["eligibility_status"] == "DEBARRED"

    return {
        "solicitation_id": solicitation["id"],
        "prime_vendor_id": prime["id"],
        "sub_vendor_id": sub["id"],
        "proceeding_id": proceeding["id"],
    }


@pytest.fixture
def screening_ground() -> Dict[str, Any]:
    return _build_prime_and_debarred_subcontractor()


class TestScreeningAProposedSubcontractor:
    """The screening verdict returned by the very request that creates the
    screening, on a debarred subcontractor and on an eligible one."""

    def test_a_debarred_subcontractor_is_blocked_in_the_creating_request(
        self, screening_ground
    ):
        """The screening is evaluated in the same request that creates it, so it never lingers in `PENDING`.

        When it is `DEBARRED`, `result` becomes `BLOCKED_DEBARRED` with `blocked_reason_code` set the same way.

        Design: Corner/endpoints/corner_screening_blocks_a_debarred_subcontractor_in_the_same_response
        """
        response = api_client.create_subcontractor_screening(
            fac.screening_payload(
                screening_ground["solicitation_id"],
                screening_ground["prime_vendor_id"],
                screening_ground["sub_vendor_id"],
                tier=1,
            ),
            OFFICER_HEADERS,
        )
        screening = validate_success(response, expected_status=201)

        assertions.assert_mutable_audit_fields(screening)
        assert screening["result"] == "BLOCKED_DEBARRED"
        assert screening["result"] != "PENDING"
        assert screening["blocked_reason_code"] == "REPEATED_NONPERFORMANCE"
        assert _instant(screening["screened_at_utc"]) == _instant(DECISION_UTC)
        assert screening["rescreened_count"] == 0
        assert screening["tier"] == 1
        assert screening["prime_vendor_id"] == screening_ground["prime_vendor_id"]
        assert screening["sub_vendor_id"] == screening_ground["sub_vendor_id"]

        rows, meta = validate_paginated(
            api_client.list_subcontractor_screenings(
                OFFICER_HEADERS,
                params={
                    "sub_vendor_id": screening_ground["sub_vendor_id"],
                    "result": "BLOCKED_DEBARRED",
                },
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=1, limit=10, offset=0, has_more=False
        )
        assert [row["id"] for row in rows] == [screening["id"]]

    def test_an_eligible_subcontractor_clears_with_no_blocked_reason(
        self, screening_ground
    ):
        """When the subcontractor's `eligibility_status` is `ELIGIBLE`, `result` becomes `CLEARED` and `blocked_reason_code` is null.

        Design: Corner/endpoints/corner_screening_blocks_a_debarred_subcontractor_in_the_same_response
        """
        # The same two vendors, with the eligible one proposed as the sub.
        response = api_client.create_subcontractor_screening(
            fac.screening_payload(
                screening_ground["solicitation_id"],
                screening_ground["sub_vendor_id"],
                screening_ground["prime_vendor_id"],
                tier=1,
            ),
            OFFICER_HEADERS,
        )
        screening = validate_success(response, expected_status=201)

        assert screening["result"] == "CLEARED"
        assert screening["blocked_reason_code"] is None
        assert screening["rescreened_count"] == 0
        assert _instant(screening["screened_at_utc"]) == _instant(DECISION_UTC)

        rows, meta = validate_paginated(
            api_client.list_subcontractor_screenings(
                OFFICER_HEADERS,
                params={
                    "solicitation_id": screening_ground["solicitation_id"],
                    "result": "CLEARED",
                },
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=1, limit=10, offset=0, has_more=False
        )
        assert [row["id"] for row in rows] == [screening["id"]]


def _build_eligible_vendor_and_issued_solicitation() -> Dict[str, Any]:
    """One eligible vendor and one advertised solicitation, and nothing else."""
    fx.reset_clock()

    vendor = fx.create_vendor(
        legal_name="Kelsford Utilities",
        tax_id="100000089",
        contact_email="v89@example.gov",
    )
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C45",
        title="Water Main Relocation",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-09-30T00:00:00Z",
        original_question_deadline_utc="2026-09-23T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-WATER",
                description="wet tap certification",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    fx.issue_solicitation(solicitation["id"])

    return {"vendor_id": vendor["id"], "solicitation_id": solicitation["id"]}


@pytest.fixture
def structural_screening_ground() -> Dict[str, Any]:
    return _build_eligible_vendor_and_issued_solicitation()


class TestStructurallyImpossibleSubcontracts:
    """The two shape rules of the prime-to-sub edge, both refused before any
    eligibility question is reached."""

    def test_a_vendor_may_not_subcontract_to_itself(self, structural_screening_ground):
        """A vendor may not subcontract to itself, so a request whose `prime_vendor_id` equals its `sub_vendor_id` is refused with `ERR_SELF_SUBCONTRACT` (HTTP 422).

        Design: Corner/endpoints/corner_self_subcontract_screening_is_rejected
        """
        vendor_id = structural_screening_ground["vendor_id"]

        response = api_client.create_subcontractor_screening(
            fac.screening_payload(
                structural_screening_ground["solicitation_id"],
                vendor_id,
                vendor_id,
                tier=1,
            ),
            OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_SELF_SUBCONTRACT.value, expected_status=422)

        # Nothing was written: the refusal precedes the row, so no screening is
        # left behind waiting to be evaluated.
        rows, meta = validate_paginated(
            api_client.list_subcontractor_screenings(
                OFFICER_HEADERS,
                params={
                    "solicitation_id": structural_screening_ground["solicitation_id"]
                },
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=0, limit=10, offset=0, has_more=False
        )
        assert rows == []

        # The rejection is structural: the very same vendor is eligible and
        # would have screened clear as somebody else's subcontractor.
        assert fx.read_vendor(vendor_id)["eligibility_status"] == "ELIGIBLE"

    def test_a_tier_outside_the_supported_range_is_refused(
        self, structural_screening_ground
    ):
        """The tier must be 1, 2 or 3; a value outside that range is refused with `ERR_SUBCONTRACT_TIER_UNSUPPORTED` (HTTP 422).

        Design: Corner/endpoints/corner_self_subcontract_screening_is_rejected
        """
        other_vendor = fx.create_vendor(legal_name="Loxley Boring Company")

        response = api_client.create_subcontractor_screening(
            fac.screening_payload(
                structural_screening_ground["solicitation_id"],
                structural_screening_ground["vendor_id"],
                other_vendor["id"],
                tier=4,
            ),
            OFFICER_HEADERS,
        )
        validate_error(
            response,
            ApiErrorId.ERR_SUBCONTRACT_TIER_UNSUPPORTED.value,
            expected_status=422,
        )

        rows, meta = validate_paginated(
            api_client.list_subcontractor_screenings(
                OFFICER_HEADERS,
                params={
                    "solicitation_id": structural_screening_ground["solicitation_id"]
                },
            )
        )
        assertions.assert_pagination_meta(
            meta, total_count=0, limit=10, offset=0, has_more=False
        )
        assert rows == []
