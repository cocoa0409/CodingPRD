"""The refusal pathways that guard identity, the registry keys and the
debarment proceeding's deadlines.

Every test here provokes exactly one refusal and then reads the target row back
to prove the refused write left it untouched: an unauthenticated caller never
reaches the body, an unknown path segment names its own resource family, a
repeated registry key never lands a second row, a vendor never acts for another
vendor, and the proceeding's response window, interim threshold and severity
floor each hold their state when the request is turned away.
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
    ADMIN_HEADERS,
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_HEADERS,
    NO_AUTH_HEADERS,
    OFFICER_HEADERS,
    make_headers,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# Calendar instants this file works against.
# --------------------------------------------------------------------------
# The notice instant of 2026-08-01T00:00:00Z plus fourteen days.
RESPONSE_DEADLINE_UTC = "2026-08-15T00:00:00Z"
# One millisecond past that deadline, the finest granularity comparisons use.
JUST_PAST_DEADLINE_UTC = "2026-08-15T00:00:00.001Z"
AFTER_WINDOW_UTC = "2026-08-16T00:00:00Z"

# A twelve-month debarment decided on 2026-08-16 ends on 2027-08-16 and admits
# a petition from 2027-02-16.
DEBARMENT_END_UTC = "2027-08-16T00:00:00Z"
AFTER_OCCUPANCY_UTC = "2027-09-01T00:00:00Z"
PETITION_FILING_UTC = "2027-03-01T00:00:00Z"

# Well-formed identifiers that name nothing, one per resource family so that a
# collapsed mapping is visible in the failure message.
UNKNOWN_HEARING_ID = "0a000000-0000-4000-8000-000000000001"
UNKNOWN_BID_ID = "0b000000-0000-4000-8000-000000000002"
UNKNOWN_PROTEST_ID = "0c000000-0000-4000-8000-000000000003"
UNKNOWN_AWARD_ID = "0d000000-0000-4000-8000-000000000004"
UNKNOWN_PROCEEDING_ID = "0e000000-0000-4000-8000-000000000005"
UNKNOWN_PETITION_ID = "0f000000-0000-4000-8000-000000000006"
UNKNOWN_SCREENING_ID = "1a000000-0000-4000-8000-000000000007"

POLE_REQUIREMENT = {
    "requirement_code": "REQ-POLE",
    "description": "utility coordination plan",
    "materiality": "MATERIAL",
    "is_waivable": False,
}
ADA_REQUIREMENT = {
    "requirement_code": "REQ-ADA",
    "description": "ADA ramp detail compliance",
    "materiality": "MATERIAL",
    "is_waivable": False,
}


# --------------------------------------------------------------------------
# Small local helpers.
# --------------------------------------------------------------------------
def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the fractional-second form."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _register_vendor(legal_name: str, tax_id: str, contact_email: str) -> Dict[str, Any]:
    return fx.create_vendor(
        legal_name=legal_name, tax_id=tax_id, contact_email=contact_email
    )


def _draft_solicitation(
    solicitation_number: str, title: str, requirement: Dict[str, Any]
) -> Dict[str, Any]:
    return fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[dict(requirement)],
    )


def _list_total(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


class TestUnauthenticatedRequests:
    """The header check that runs before every other check in the pipeline."""

    def test_read_with_no_identity_headers_is_unauthenticated(self):
        """If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        These two checks run before anything else, including body shape validation, so a malformed payload sent by an unauthenticated caller yields the authentication error rather than a validation error.

        Design: Corner/errors/corner_request_without_identity_headers_is_rejected
        """
        fx.reset_clock()

        response = api_client.list_vendors(
            NO_AUTH_HEADERS, params={"limit": 10, "offset": 0}
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_unrecognised_role_name_is_unauthenticated_rather_than_forbidden(self):
        """The six roles are `ProcurementOfficer`, `ResponsibilityReviewer`, `HearingOfficer`, `DebarmentAuthority`, `Vendor` and `SystemAdmin`.

        If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/errors/corner_request_without_identity_headers_is_rejected
        """
        fx.reset_clock()

        response = api_client.list_vendors(
            make_headers("U-AUDITOR-1", "Auditor"), params={"limit": 10, "offset": 0}
        )
        # A role string outside the declared six is not a forbidden role, it is
        # no role at all, so the caller is never authenticated in the first place.
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_declared_role_without_a_caller_id_is_unauthenticated(self):
        """Every request to the API carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the authority the caller is exercising.

        If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/errors/corner_request_without_identity_headers_is_rejected
        """
        fx.reset_clock()

        role_only_headers = {
            "X-User-Role": "ProcurementOfficer",
            "Content-Type": "application/json",
        }
        response = api_client.list_vendors(
            role_only_headers, params={"limit": 10, "offset": 0}
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


_UNKNOWN_PATH_SEGMENT_CASES = [
    (
        "hearing",
        lambda: api_client.get_hearing(UNKNOWN_HEARING_ID, HEARING_OFFICER_HEADERS),
        ApiErrorId.ERR_HEARING_NOT_FOUND.value,
    ),
    (
        "bid",
        lambda: api_client.get_bid(UNKNOWN_BID_ID, OFFICER_HEADERS),
        ApiErrorId.ERR_BID_NOT_FOUND.value,
    ),
    (
        "protest",
        lambda: api_client.get_protest(UNKNOWN_PROTEST_ID, OFFICER_HEADERS),
        ApiErrorId.ERR_PROTEST_NOT_FOUND.value,
    ),
    (
        "award",
        lambda: api_client.get_award(UNKNOWN_AWARD_ID, OFFICER_HEADERS),
        ApiErrorId.ERR_AWARD_NOT_FOUND.value,
    ),
    (
        "proceeding",
        lambda: api_client.get_debarment_proceeding(
            UNKNOWN_PROCEEDING_ID, DEBARMENT_AUTHORITY_HEADERS
        ),
        ApiErrorId.ERR_PROCEEDING_NOT_FOUND.value,
    ),
    (
        "proceeding_parent_of_petitions",
        lambda: api_client.list_reinstatement_petitions(
            UNKNOWN_PROCEEDING_ID, DEBARMENT_AUTHORITY_HEADERS
        ),
        ApiErrorId.ERR_PROCEEDING_NOT_FOUND.value,
    ),
    (
        "petition",
        lambda: api_client.decide_reinstatement_petition(
            UNKNOWN_PETITION_ID,
            fac.petition_decision_payload(
                outcome="GRANTED", decision_rationale="x"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        ),
        ApiErrorId.ERR_PETITION_NOT_FOUND.value,
    ),
    (
        "screening",
        lambda: api_client.get_subcontractor_screening(
            UNKNOWN_SCREENING_ID, OFFICER_HEADERS
        ),
        ApiErrorId.ERR_SCREENING_NOT_FOUND.value,
    ),
]


class TestUnknownPathIdentifiers:
    """Each resource family answers an unknown identifier with its own 404."""

    @pytest.mark.parametrize(
        "segment,invoke,expected_error_id",
        _UNKNOWN_PATH_SEGMENT_CASES,
        ids=[case[0] for case in _UNKNOWN_PATH_SEGMENT_CASES],
    )
    def test_each_unknown_path_segment_names_its_own_resource_family(
        self, segment, invoke, expected_error_id
    ):
        """The per-segment mapping is: a vendor segment yields `ERR_VENDOR_NOT_FOUND`, a solicitation segment `ERR_SOLICITATION_NOT_FOUND`, a bid segment `ERR_BID_NOT_FOUND`, a protest segment `ERR_PROTEST_NOT_FOUND`, a hearing segment `ERR_HEARING_NOT_FOUND`, an award segment `ERR_AWARD_NOT_FOUND`, a debarment-proceeding segment `ERR_PROCEEDING_NOT_FOUND`, a reinstatement-petition segment `ERR_PETITION_NOT_FOUND` and a subcontractor-screening segment `ERR_SCREENING_NOT_FOUND`.

        Nested URLs are resolved strictly left to right, and the first segment that fails to resolve determines the error.

        Design: Corner/errors/corner_each_unknown_path_id_returns_its_own_not_found_error
        """
        fx.reset_clock()

        response = invoke()
        validate_error(response, expected_error_id, 404)


@pytest.fixture
def registry_state() -> Dict[str, Any]:
    """One registered vendor and one drafted solicitation, so that every
    registry key the tests below reuse is already taken."""
    fx.reset_clock()
    vendor = _register_vendor("Fairhaven Utilities", "100000060", "v60@example.gov")
    solicitation = _draft_solicitation(
        "SOL-2238-C29", "Utility Pole Relocation", POLE_REQUIREMENT
    )
    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
    }


class TestRegistryUniqueness:
    """Three uniqueness scopes that share one place in the pipeline and keep
    three distinct error identifiers."""

    def test_second_registration_reusing_a_tax_id_is_refused(self, registry_state):
        """The `tax_id` is a state taxpayer identifier consisting of exactly nine digits and must be unique across the whole vendor file; a second registration reusing an existing identifier is refused with `ERR_DUPLICATE_TAX_ID`.

        Callers can search the vendor file by `eligibility_status`, by `tax_id` and by `active_debarment_id`, which is useful for asking "which vendors are currently attached to this proceeding".

        Design: Corner/errors/corner_duplicate_registry_keys_are_rejected
        """
        response = api_client.create_vendor(
            fac.vendor_payload(
                legal_name="Fairhaven Utilities Holdings",
                tax_id="100000060",
                contact_email="v60b@example.gov",
            ),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_TAX_ID.value, 409)

        rows, meta = validate_paginated(
            api_client.list_vendors(ADMIN_HEADERS, params={"tax_id": "100000060"})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [registry_state["vendor_id"]]

    def test_second_solicitation_reusing_a_number_is_refused(self, registry_state):
        """Uniqueness: a vendor's `tax_id` is unique across the whole vendor file (`ERR_DUPLICATE_TAX_ID` when a vendor is registered); a `solicitation_number` is unique across all solicitations (`ERR_DUPLICATE_SOLICITATION_NUMBER` when a solicitation is drafted or a successor is created by resolicitation); a `requirement_code` is unique within one solicitation (`ERR_DUPLICATE_REQUIREMENT_CODE` when a solicitation is drafted or an addendum introduces requirements).

        Design: Corner/errors/corner_duplicate_registry_keys_are_rejected
        """
        response = api_client.create_solicitation(
            fac.solicitation_payload(
                solicitation_number="SOL-2238-C29",
                title="Utility Pole Relocation Phase Two",
                issuing_agency_code="DOT",
                estimated_value_cents=10000000,
                mandatory_requirements=[dict(ADA_REQUIREMENT)],
            ),
            OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_SOLICITATION_NUMBER.value, 409
        )

        assert _list_total(api_client.list_solicitations(OFFICER_HEADERS)) == 1

    def test_requirement_code_repeated_inside_one_draft_is_refused(
        self, registry_state
    ):
        """A repeated `requirement_code` within the same solicitation is refused with `ERR_DUPLICATE_REQUIREMENT_CODE`.

        Third, a cascade never partially applies: if any step of the originating operation fails a check, nothing is written at all.

        Design: Corner/errors/corner_duplicate_registry_keys_are_rejected
        """
        twice = {
            "requirement_code": "REQ-TWICE",
            "description": "duplicated bond clause",
            "materiality": "MATERIAL",
            "is_waivable": False,
        }
        response = api_client.create_solicitation(
            fac.solicitation_payload(
                solicitation_number="SOL-2238-C29B",
                title="Duplicated Requirement Draft",
                issuing_agency_code="DOT",
                estimated_value_cents=10000000,
                mandatory_requirements=[dict(twice), dict(twice)],
            ),
            OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_REQUIREMENT_CODE.value, 409)

        # Only the solicitation built by the setup exists; the refused draft
        # left no row behind.
        assert _list_total(api_client.list_solicitations(OFFICER_HEADERS)) == 1

    def test_addendum_reintroducing_an_existing_requirement_code_is_refused(
        self, registry_state
    ):
        """Uniqueness: a vendor's `tax_id` is unique across the whole vendor file (`ERR_DUPLICATE_TAX_ID` when a vendor is registered); a `solicitation_number` is unique across all solicitations (`ERR_DUPLICATE_SOLICITATION_NUMBER` when a solicitation is drafted or a successor is created by resolicitation); a `requirement_code` is unique within one solicitation (`ERR_DUPLICATE_REQUIREMENT_CODE` when a solicitation is drafted or an addendum introduces requirements).

        Design: Corner/errors/corner_duplicate_registry_keys_are_rejected
        """
        solicitation_id = registry_state["solicitation_id"]
        # Advertised first, so the only thing wrong with the amendment below is
        # the requirement code it tries to bring into being a second time.
        fx.issue_solicitation(solicitation_id)

        response = api_client.create_addendum(
            solicitation_id,
            fac.addendum_payload(
                summary="restates the utility coordination plan",
                extends_bid_due_by_days=0,
                acknowledgment_required=True,
                new_requirement_codes=[dict(POLE_REQUIREMENT)],
            ),
            OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_REQUIREMENT_CODE.value, 409)

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["addendum_count"] == 0
        assert (
            _list_total(api_client.list_addenda(solicitation_id, OFFICER_HEADERS)) == 0
        )
        assert (
            _list_total(api_client.list_requirements(solicitation_id, OFFICER_HEADERS))
            == 1
        )


class TestVendorIdentityOwnership:
    """The vendor role is backed by a persisted row, so a vendor may only act
    for itself."""

    def test_vendor_filing_a_bid_for_another_vendor_is_refused(self):
        """When `X-User-Role` is `Vendor`, by contrast, `X-User-ID` is the `id` of the acting `Vendor` row, and ownership checks on any resource that references a vendor compare the resource's vendor-bearing field to `X-User-ID`: `vendor_id` on a bid, `vendor_id` on a question submission, `protester_vendor_id` on a protest, `vendor_id` on a debarment proceeding, and `prime_vendor_id` on a subcontractor screening.

        The `vendor_id` in the body must equal the acting vendor's `X-User-ID`, else `ERR_VENDOR_IDENTITY_MISMATCH`.

        Design: Corner/errors/corner_vendor_acting_on_another_vendors_bid_is_rejected
        """
        fx.reset_clock()
        acting_vendor = _register_vendor(
            "Glenridge Concrete", "100000061", "v61@example.gov"
        )
        named_vendor = _register_vendor(
            "Havenwood Concrete", "100000062", "v62@example.gov"
        )
        solicitation = _draft_solicitation(
            "SOL-2238-C30", "Sidewalk Replacement Program", ADA_REQUIREMENT
        )
        solicitation_id = solicitation["id"]
        fx.issue_solicitation(solicitation_id)
        version_before = fx.read_solicitation(solicitation_id)["version"]

        response = api_client.create_bid(
            fac.bid_payload(
                solicitation_id,
                named_vendor["id"],
                total_price_cents=8000000,
                acknowledged_addendum_sequences=[],
                expected_solicitation_version=version_before,
            ),
            make_vendor_headers(acting_vendor["id"]),
        )
        # Vendor is a permitted role on this endpoint, so the refusal is about
        # whose bid it is, not about which authority was exercised.
        validate_error(response, ApiErrorId.ERR_VENDOR_IDENTITY_MISMATCH.value, 403)

        assert (
            _list_total(
                api_client.list_bids(
                    OFFICER_HEADERS, params={"solicitation_id": solicitation_id}
                )
            )
            == 0
        )
        assert fx.read_solicitation(solicitation_id)["version"] == version_before


class TestFactorCodeDistinctness:
    """A repeated aggravating code is refused outright rather than deduplicated
    or double-counted into the aggravating total."""

    def test_repeated_aggravating_code_opens_no_proceeding(self):
        """Distinctness of the code lists: `aggravating_factor_codes`, `mitigating_factor_codes` and `remediation_evidence_codes` must each contain no repeated member.

        A repeated member in either list is refused with `ERR_DUPLICATE_FACTOR_CODE`.

        Design: Corner/errors/corner_repeated_aggravating_factor_code_is_rejected
        """
        fx.reset_clock()
        vendor = _register_vendor(
            "Ivyhurst Contracting", "100000063", "v63@example.gov"
        )
        vendor_id = vendor["id"]

        response = api_client.create_debarment_proceeding(
            fac.proceeding_payload(
                vendor_id,
                cause_code="FRAUD",
                aggravating_factor_codes=["FRAUD", "FRAUD"],
                mitigating_factor_codes=[],
                interim_suspension=False,
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_FACTOR_CODE.value, 422)

        assert (
            _list_total(
                api_client.list_debarment_proceedings(
                    DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": vendor_id}
                )
            )
            == 0
        )
        respondent = fx.read_vendor(vendor_id)
        assert respondent["eligibility_status"] == "ELIGIBLE"
        assert respondent["debarment_strike_count"] == 0


class TestInterimSuspensionThreshold:
    """Interim suspension at notice time is gated on the interim severity."""

    def test_interim_suspension_below_the_threshold_opens_no_proceeding(self):
        """Interim suspension is permitted only when that severity reaches 35; below it the request is refused with `ERR_INTERIM_SUSPENSION_THRESHOLD_NOT_MET` (HTTP 422).

        Under the **interim-suspension variant**, which reflects the adequate-evidence standard applicable at notice time, mitigation is ignored entirely and prior strikes do not escalate: `mitigating_credit_points` is 0 and `severity_score` is the aggravating total, capped at 100.

        Design: Corner/errors/corner_interim_suspension_below_the_threshold_is_rejected
        """
        fx.reset_clock()
        vendor = _register_vendor(
            "Jasper Hollow Supply", "100000064", "v64@example.gov"
        )
        vendor_id = vendor["id"]

        response = api_client.create_debarment_proceeding(
            fac.proceeding_payload(
                vendor_id,
                cause_code="ADMINISTRATIVE_DEFAULT",
                aggravating_factor_codes=["ADMINISTRATIVE_DEFAULT"],
                mitigating_factor_codes=[],
                interim_suspension=True,
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INTERIM_SUSPENSION_THRESHOLD_NOT_MET.value, 422
        )

        respondent = fx.read_vendor(vendor_id)
        assert respondent["eligibility_status"] == "ELIGIBLE"
        assert respondent["suspension_reason_code"] is None
        assert respondent["active_debarment_id"] is None
        assert respondent["debarment_strike_count"] == 0
        assert (
            _list_total(
                api_client.list_debarment_proceedings(
                    DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": vendor_id}
                )
            )
            == 0
        )

    def test_same_factors_without_interim_suspension_open_the_proceeding(self):
        """The proceeding is created in `status` `NOTICE_ISSUED` with `interim_status` `NONE`, `notice_issued_at_utc` stamped from the logical clock, and `response_deadline_utc` set to two weeks — fourteen days — after that notice instant.

        Its `response_narrative` starts null, its `decided_at_utc` starts null, its `debarment_period_months` starts at 0, its `debarment_start_utc` and `debarment_end_utc` start null, and its `strikes_applied` starts at 0.

        Design: Corner/errors/corner_interim_suspension_below_the_threshold_is_rejected
        """
        fx.reset_clock()
        vendor = _register_vendor(
            "Jasper Hollow Supply", "100000064", "v64@example.gov"
        )
        vendor_id = vendor["id"]

        response = api_client.create_debarment_proceeding(
            fac.proceeding_payload(
                vendor_id,
                cause_code="ADMINISTRATIVE_DEFAULT",
                aggravating_factor_codes=["ADMINISTRATIVE_DEFAULT"],
                mitigating_factor_codes=[],
                interim_suspension=False,
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        proceeding = validate_success(response, expected_status=201)

        assert proceeding["status"] == "NOTICE_ISSUED"
        assert proceeding["interim_status"] == "NONE"
        assert proceeding["strikes_applied"] == 0
        assert fx.read_vendor(vendor_id)["eligibility_status"] == "ELIGIBLE"


@pytest.fixture
def unanswered_proceeding() -> Dict[str, Any]:
    """A notice issued on 2026-08-01 against an eligible respondent, with the
    response window running to 2026-08-15 and no response filed."""
    fx.reset_clock()
    vendor = _register_vendor("Kettlebrook Roofing", "100000065", "v65@example.gov")
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": proceeding,
    }


class TestDefaultBranchHearingRights:
    """The default-branch hearing needs the response window to have expired,
    strictly."""

    def test_hearing_at_exactly_the_response_deadline_is_refused(
        self, unanswered_proceeding
    ):
        """On the other branch the respondent never answers, and the authority takes the hearing directly from `NOTICE_ISSUED → HEARING_HELD` — but only once the response window has actually expired, that is once the logical clock is strictly after `response_deadline_utc`; an earlier attempt is refused with `ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED`.

        Instants are compared at millisecond precision.

        Design: Corner/errors/corner_debarment_hearing_at_exactly_the_response_deadline_is_rejected
        """
        proceeding_id = unanswered_proceeding["proceeding_id"]
        assert _instant(
            unanswered_proceeding["proceeding"]["response_deadline_utc"]
        ) == _instant(RESPONSE_DEADLINE_UTC)

        fx.set_clock(RESPONSE_DEADLINE_UTC)
        response = api_client.hold_debarment_hearing(
            proceeding_id,
            fac.debarment_hearing_payload(
                hearing_summary="attempting the default branch on the deadline instant"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            response,
            ApiErrorId.ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED.value,
            409,
        )

        unmoved = fx.read_proceeding(proceeding_id)
        assert unmoved["status"] == "NOTICE_ISSUED"
        assert _instant(unmoved["response_deadline_utc"]) == _instant(
            RESPONSE_DEADLINE_UTC
        )

    def test_hearing_one_millisecond_past_the_deadline_is_accepted(
        self, unanswered_proceeding
    ):
        """On the other branch the respondent never answers, and the authority takes the hearing directly from `NOTICE_ISSUED → HEARING_HELD` — but only once the response window has actually expired, that is once the logical clock is strictly after `response_deadline_utc`; an earlier attempt is refused with `ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED`.

        That branch records that hearing rights were exhausted by default and likewise increments `version` by 1.

        Design: Corner/errors/corner_debarment_hearing_at_exactly_the_response_deadline_is_rejected
        """
        proceeding_id = unanswered_proceeding["proceeding_id"]

        fx.set_clock(RESPONSE_DEADLINE_UTC)
        refused = api_client.hold_debarment_hearing(
            proceeding_id,
            fac.debarment_hearing_payload(
                hearing_summary="attempting the default branch on the deadline instant"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            refused, ApiErrorId.ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED.value, 409
        )

        fx.set_clock(JUST_PAST_DEADLINE_UTC)
        accepted = api_client.hold_debarment_hearing(
            proceeding_id,
            fac.debarment_hearing_payload(
                hearing_summary="attempting the default branch on the deadline instant"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        held = validate_success(accepted, expected_status=200)
        assert held["status"] == "HEARING_HELD"


@pytest.fixture
def respondent_proceeding() -> Dict[str, Any]:
    """A notice issued on 2026-08-01 whose respondent has filed nothing yet, so
    the response window is the only thing standing between it and a response."""
    fx.reset_clock()
    vendor = _register_vendor("Lockridge Mechanical", "100000066", "v66@example.gov")
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    return {"vendor_id": vendor["id"], "proceeding_id": proceeding["id"]}


class TestRespondentResponseWindow:
    """The respondent's written response is admitted up to and including the
    deadline instant, and not one millisecond later."""

    def test_response_one_millisecond_past_the_deadline_merges_nothing(
        self, respondent_proceeding
    ):
        """On one branch, the respondent `Vendor` files a written response, supplying a `response_narrative` and optionally further `mitigating_factor_codes`; this moves the proceeding `NOTICE_ISSUED → RESPONSE_RECEIVED`, requires the acting `X-User-ID` to equal the respondent's `vendor_id` (else `ERR_VENDOR_IDENTITY_MISMATCH`) and requires the logical clock to be at or before `response_deadline_utc` (else `ERR_RESPONSE_WINDOW_CLOSED`).

        The supplied codes are merged into the proceeding's `mitigating_factor_codes`, and the proceeding's `version` increments by 1.

        Design: Corner/errors/corner_vendor_response_after_the_window_closes_is_rejected
        """
        proceeding_id = respondent_proceeding["proceeding_id"]
        vendor_id = respondent_proceeding["vendor_id"]

        fx.set_clock(JUST_PAST_DEADLINE_UTC)
        response = api_client.file_debarment_response(
            proceeding_id,
            fac.debarment_response_payload(
                response_narrative="the terminations were for convenience",
                mitigating_factor_codes=["SELF_DISCLOSURE", "RESTITUTION_PAID"],
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(response, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value, 409)

        unmoved = fx.read_proceeding(proceeding_id)
        assert unmoved["status"] == "NOTICE_ISSUED"
        assert unmoved["response_narrative"] is None
        assert unmoved["mitigating_factor_codes"] == []
        assert unmoved["mitigating_credit_points"] == pytest.approx(0, abs=0.01)

    def test_response_at_exactly_the_deadline_is_accepted_and_merges_its_codes(
        self, respondent_proceeding
    ):
        """On one branch, the respondent `Vendor` files a written response, supplying a `response_narrative` and optionally further `mitigating_factor_codes`; this moves the proceeding `NOTICE_ISSUED → RESPONSE_RECEIVED`, requires the acting `X-User-ID` to equal the respondent's `vendor_id` (else `ERR_VENDOR_IDENTITY_MISMATCH`) and requires the logical clock to be at or before `response_deadline_utc` (else `ERR_RESPONSE_WINDOW_CLOSED`).

        Design: Corner/errors/corner_vendor_response_after_the_window_closes_is_rejected
        """
        proceeding_id = respondent_proceeding["proceeding_id"]
        vendor_id = respondent_proceeding["vendor_id"]

        fx.set_clock(JUST_PAST_DEADLINE_UTC)
        refused = api_client.file_debarment_response(
            proceeding_id,
            fac.debarment_response_payload(
                response_narrative="the terminations were for convenience",
                mitigating_factor_codes=["SELF_DISCLOSURE", "RESTITUTION_PAID"],
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(refused, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value, 409)

        # The very same filing, made on the deadline instant itself, is in time.
        fx.set_clock(RESPONSE_DEADLINE_UTC)
        accepted = api_client.file_debarment_response(
            proceeding_id,
            fac.debarment_response_payload(
                response_narrative="the terminations were for convenience",
                mitigating_factor_codes=["SELF_DISCLOSURE", "RESTITUTION_PAID"],
            ),
            make_vendor_headers(vendor_id),
        )
        answered = validate_success(accepted, expected_status=200)
        assert answered["status"] == "RESPONSE_RECEIVED"
        assert sorted(answered["mitigating_factor_codes"]) == [
            "RESTITUTION_PAID",
            "SELF_DISCLOSURE",
        ]


@pytest.fixture
def low_severity_proceeding_at_hearing_held() -> Dict[str, Any]:
    """A proceeding whose only aggravating factor is the lightest of the six,
    carried to HEARING_HELD through the default branch."""
    fx.reset_clock()
    vendor = _register_vendor("Marloway Striping", "100000067", "v67@example.gov")
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="ADMINISTRATIVE_DEFAULT",
        aggravating_factor_codes=["ADMINISTRATIVE_DEFAULT"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock(AFTER_WINDOW_UTC)
    fx.hold_debarment_hearing(
        proceeding["id"], hearing_summary="no response filed; default branch recorded"
    )
    return {"vendor_id": vendor["id"], "proceeding_id": proceeding["id"]}


class TestDebarmentSeverityFloor:
    """A debarment outcome needs a severity that buys a period."""

    def test_debarred_outcome_below_the_floor_is_refused(
        self, low_severity_proceeding_at_hearing_held
    ):
        """Below 20 the period would be 0 months, and a debarment outcome is therefore refused with `ERR_SEVERITY_BELOW_DEBARMENT_FLOOR` (HTTP 422).

        **The period** is read off a tier table from the final severity: 60 months at a severity of 80 or more, 36 months at 60 or more, 24 months at 40 or more, and 12 months at 20 or more.

        Design: Corner/errors/corner_debarment_decision_below_the_severity_floor_is_rejected
        """
        proceeding_id = low_severity_proceeding_at_hearing_held["proceeding_id"]
        vendor_id = low_severity_proceeding_at_hearing_held["vendor_id"]

        response = api_client.decide_debarment(
            proceeding_id,
            fac.debarment_decision_payload(
                outcome="DEBARRED", rationale="late reporting only"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_SEVERITY_BELOW_DEBARMENT_FLOOR.value, 422
        )

        unmoved = fx.read_proceeding(proceeding_id)
        assert unmoved["status"] == "HEARING_HELD"
        assert unmoved["severity_score"] == pytest.approx(5.00, abs=0.01)
        assert unmoved["debarment_period_months"] == 0
        assert unmoved["debarment_start_utc"] is None
        assert unmoved["strikes_applied"] == 0

        respondent = fx.read_vendor(vendor_id)
        assert respondent["eligibility_status"] == "ELIGIBLE"
        assert respondent["active_debarment_id"] is None

    def test_dismissal_on_the_same_proceeding_is_accepted(
        self, low_severity_proceeding_at_hearing_held
    ):
        """A **dismissal** outcome moves the proceeding `HEARING_HELD → DISMISSED`, also terminal, and its side-effect set diverges sharply from the debarment branch.

        Below 20 the period would be 0 months, and a debarment outcome is therefore refused with `ERR_SEVERITY_BELOW_DEBARMENT_FLOOR` (HTTP 422).

        Design: Corner/errors/corner_debarment_decision_below_the_severity_floor_is_rejected
        """
        proceeding_id = low_severity_proceeding_at_hearing_held["proceeding_id"]

        refused = api_client.decide_debarment(
            proceeding_id,
            fac.debarment_decision_payload(
                outcome="DEBARRED", rationale="late reporting only"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(
            refused, ApiErrorId.ERR_SEVERITY_BELOW_DEBARMENT_FLOOR.value, 422
        )

        accepted = api_client.decide_debarment(
            proceeding_id,
            fac.debarment_decision_payload(
                outcome="DISMISSED", rationale="late reporting only"
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        dismissed = validate_success(accepted, expected_status=200)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["debarment_period_months"] == 0


def _debar_vendor_through_the_default_branch(
    legal_name: str, tax_id: str, contact_email: str
) -> Dict[str, Any]:
    """A respondent carried to DEBARRED for twelve months on 2026-08-16."""
    fx.reset_clock()
    vendor = _register_vendor(legal_name, tax_id, contact_email)
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock(AFTER_WINDOW_UTC)
    fx.hold_debarment_hearing(
        proceeding["id"], hearing_summary="no response filed; default branch recorded"
    )
    decided = fx.decide_debarment(
        proceeding["id"],
        outcome="DEBARRED",
        rationale="pattern of nonperformance with an open safety citation",
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": decided,
    }


class TestProceedingsAgainstDebarredVendors:
    """A vendor already carrying a debarment cannot be noticed a second time."""

    def test_fresh_notice_after_the_occupancy_interval_closes_is_still_refused(self):
        """A respondent whose `eligibility_status` is already `DEBARRED` cannot be the subject of a new proceeding and the attempt is refused with `ERR_VENDOR_ALREADY_DEBARRED`.

        Each proceeding occupies a closed interval on its respondent's compliance docket, running from its `notice_issued_at_utc` to an occupancy end that depends on its `status`: `debarment_end_utc` once the proceeding is `DEBARRED`, `decided_at_utc` once it is `DISMISSED`, and its own `notice_issued_at_utc` plus ten years — 3,650 days — while it is still live in `NOTICE_ISSUED`, `RESPONSE_RECEIVED` or `HEARING_HELD`.

        Design: Corner/errors/corner_second_proceeding_against_a_debarred_vendor_is_rejected
        """
        state = _debar_vendor_through_the_default_branch(
            "Norbury Demolition", "100000068", "v68@example.gov"
        )
        vendor_id = state["vendor_id"]
        first_proceeding_id = state["proceeding_id"]
        assert _instant(state["proceeding"]["debarment_end_utc"]) == _instant(
            DEBARMENT_END_UTC
        )

        # The clock is moved strictly past the first proceeding's occupancy end,
        # so the docket is clear and only the respondent's posture can bite.
        fx.set_clock(AFTER_OCCUPANCY_UTC)
        response = api_client.create_debarment_proceeding(
            fac.proceeding_payload(
                vendor_id,
                cause_code="FRAUD",
                aggravating_factor_codes=["FRAUD"],
                mitigating_factor_codes=[],
                interim_suspension=False,
            ),
            DEBARMENT_AUTHORITY_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_VENDOR_ALREADY_DEBARRED.value, 409)

        rows, meta = validate_paginated(
            api_client.list_debarment_proceedings(
                DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": vendor_id}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_proceeding_id]

        respondent = fx.read_vendor(vendor_id)
        assert respondent["eligibility_status"] == "DEBARRED"
        assert respondent["debarment_strike_count"] == 1
        assert respondent["active_debarment_id"] == first_proceeding_id


class TestReinstatementPetitionQueue:
    """Only one petition may be pending on a proceeding at a time."""

    def test_second_petition_while_the_first_is_still_filed_is_refused(self):
        """No petition on that proceeding may already be in `FILED`, else `ERR_PETITION_ALREADY_PENDING`.

        When a debarment is decided, the respondent's `reinstatement_earliest_petition_utc` is stamped as the proceeding's `debarment_start_utc` plus a number of calendar months equal to half the `debarment_period_months`, rounded up to a whole month.

        Design: Corner/errors/corner_second_reinstatement_petition_while_one_is_pending_is_rejected
        """
        state = _debar_vendor_through_the_default_branch(
            "Overton Bridge Services", "100000069", "v69@example.gov"
        )
        vendor_id = state["vendor_id"]
        proceeding_id = state["proceeding_id"]

        fx.set_clock(PETITION_FILING_UTC)
        first_petition = fx.file_petition(
            proceeding_id,
            vendor_id,
            remediation_evidence_codes=["TRAINING_COMPLETED"],
            narrative="supervisors retrained",
        )
        assert first_petition["status"] == "FILED"

        # The pin carried by the second filing is the proceeding's current
        # version, so the refusal cannot be a concurrency refusal.
        current_version = fx.proceeding_version(proceeding_id)
        response = api_client.create_reinstatement_petition(
            proceeding_id,
            fac.petition_payload(
                remediation_evidence_codes=["COMPLIANCE_AUDIT_PASSED"],
                narrative="an independent audit also passed",
                expected_proceeding_version=current_version,
            ),
            make_vendor_headers(vendor_id),
        )
        validate_error(response, ApiErrorId.ERR_PETITION_ALREADY_PENDING.value, 409)

        rows, meta = validate_paginated(
            api_client.list_reinstatement_petitions(
                proceeding_id, DEBARMENT_AUTHORITY_HEADERS
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_petition["id"]]
        assert rows[0]["status"] == "FILED"

        assert fx.read_vendor(vendor_id)["eligibility_status"] == "DEBARRED"
