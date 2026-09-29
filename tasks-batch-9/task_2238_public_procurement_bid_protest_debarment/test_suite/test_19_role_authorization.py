"""Who may write, and what the refusal looks like when the wrong hat is worn.

Four write endpoints are exercised by a caller who holds a real, well-formed
credential for a role that the endpoint does not list. In each case the refusal
has to arrive before the checks that sit further down the pipeline, nothing may
be persisted, and the reading surface — which is open to every role — has to
stay open. Where the endpoint does list the caller's role but binds the write to
the caller's own vendor identity, the identity refusal is the one that must
surface instead of the role refusal.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    DEBARMENT_AUTHORITY_HEADERS,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)

# --------------------------------------------------------------------------
# Local composition helpers. Each builds its state exclusively through the
# public API, because every test starts against an empty database.
# --------------------------------------------------------------------------
def _protest_filed_by_a_prospective_bidder(
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    legal_name: str,
    tax_id: str,
    contact_email: str,
    question_text: str,
    narrative: str,
) -> Dict[str, Any]:
    """One funded vendor, one advertised solicitation the vendor asked a written
    question about, and that vendor's solicitation-impropriety protest, which is
    still sitting in FILED with an empty agency record."""
    fx.reset_clock()

    vendor = fx.create_vendor(
        legal_name=legal_name, tax_id=tax_id, contact_email=contact_email
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, 100000)

    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            {
                "requirement_code": requirement_code,
                "description": requirement_description,
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    fx.submit_question(solicitation_id, vendor_id, question_text=question_text)
    protest = fx.file_protest(
        solicitation_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative=narrative,
    )

    return {
        "vendor_id": vendor_id,
        "solicitation_id": solicitation_id,
        "protest_id": protest["id"],
        "protest": protest,
    }


class TestVendorCannotDraftASolicitation:
    """Drafting a solicitation is an officer's act, and the refusal of a vendor
    who attempts it does not wait for the body to be inspected."""

    def test_the_role_refusal_arrives_before_the_body_is_inspected(self):
        """If both headers are well formed but the named role does not appear in the authorized-role list for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

        Officers draft, advertise and amend solicitations, close the question period, open bids, record responsiveness determinations, issue and execute awards, cancel and resolicit procurements, file the agency report into a protest record, screen subcontractors, and may override an automatic stay on written urgency findings.

        When a request violates more than one rule, exactly one error is returned, and which one is determined by a fixed evaluation order rather than by the order the checks happen to appear in an implementation.

        Design: Corner/rbac/corner_vendor_cannot_draft_a_solicitation
        """
        fx.reset_clock()
        vendor = fx.create_vendor(
            legal_name="Lindmoor Excavating",
            tax_id="100000090",
            contact_email="v90@example.gov",
        )

        # The body is deliberately defective as well: mandatory_requirements is
        # absent, which on its own would be a shape violation.
        defective_body = {
            "solicitation_number": "SOL-2238-C46",
            "title": "Vendor Authored Solicitation",
            "issuing_agency_code": "DOT",
            "estimated_value_cents": 10000000,
            "original_bid_due_utc": "2026-09-30T00:00:00Z",
            "original_question_deadline_utc": "2026-09-23T00:00:00Z",
        }

        response = api_client.create_solicitation(
            defective_body, make_vendor_headers(vendor["id"])
        )
        error = validate_error(
            response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
            "the role refusal must precede the body-shape check, but the "
            "validation error came back instead"
        )

        # Nothing was drafted.
        rows, meta = validate_paginated(api_client.list_solicitations(OFFICER_HEADERS))
        assert meta["total_count"] == 0
        assert rows == []

        # The identical payload, completed with the mandatory requirement list
        # and sent by the role the endpoint does list, is accepted.
        authorized_body = dict(defective_body)
        authorized_body["mandatory_requirements"] = [
            {
                "requirement_code": "REQ-VENDOR-C46",
                "description": "traffic control plan",
                "materiality": "MATERIAL",
                "is_waivable": False,
            }
        ]
        created = validate_success(
            api_client.create_solicitation(authorized_body, OFFICER_HEADERS),
            expected_status=201,
        )
        assert created["solicitation_number"] == "SOL-2238-C46"
        assert created["status"] == "DRAFT"


class TestDebarmentAuthorityCannotDecideAProtest:
    """Protest adjudication is the hearing officer's, and the suspension and
    debarment official is turned away before the merits preconditions are read."""

    def test_the_role_refusal_precedes_the_protest_state_and_hearing_checks(self):
        """A `HearingOfficer` presides over protest hearings: scheduling, convening, continuing and concluding them, and issuing the protest decision.

        The decision is issued by a `HearingOfficer` from `UNDER_REVIEW`, supplying the `outcome`, a `rationale`, and — with a sustained outcome — a `remedy_code`.

        When a request violates more than one rule, exactly one error is returned, and which one is determined by a fixed evaluation order rather than by the order the checks happen to appear in an implementation.

        Design: Corner/rbac/corner_debarment_authority_cannot_decide_a_protest
        """
        state = _protest_filed_by_a_prospective_bidder(
            solicitation_number="SOL-2238-C47",
            title="Shoulder Widening",
            requirement_code="REQ-SHOULDER",
            requirement_description="paved shoulder profile",
            legal_name="Marchmont Roadway",
            tax_id="100000091",
            contact_email="v91@example.gov",
            question_text="is the shoulder profile negotiable?",
            narrative="the profile favours one supplier",
        )
        protest_id = state["protest_id"]
        assert state["protest"]["status"] == "FILED"

        # The protest is in FILED and no hearing has ever been concluded, so two
        # further refusals are available further down the pipeline.
        response = api_client.decide_protest(
            protest_id,
            {"outcome": "DENIED", "rationale": "decided by the debarment official"},
            DEBARMENT_AUTHORITY_HEADERS,
        )
        error = validate_error(
            response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_PROTEST_STATE.value, (
            "the role refusal must precede the protest-state check"
        )
        assert error["error_id"] != ApiErrorId.ERR_HEARING_NOT_CONCLUDED.value, (
            "the role refusal must precede the concluded-hearing check"
        )

        protest = fx.read_protest(protest_id)
        assert protest["status"] == "FILED"
        assert protest["stay_status"] == "ACTIVE"
        assert protest["decision_outcome"] is None


class TestResponsibilityReviewerCannotFileIntoTheAgencyRecord:
    """The agency record is shared by three roles, and the responsibility
    reviewer is not one of them — though it may still read the record."""

    def test_the_reviewer_write_is_refused_while_the_reviewer_read_stays_open(self):
        """A protest is decided on a documentary record, and the record is built one item at a time by a `ProcurementOfficer`, a `HearingOfficer` or a `Vendor`.

        A `ResponsibilityReviewer` belongs to the responsibility review unit and scores the apparent low bidder's financial capacity, past performance and business integrity.

        Read access is deliberately wide: every listed role, including `Vendor`, may read any single resource and any list.

        Design: Corner/rbac/corner_responsibility_reviewer_cannot_file_into_the_agency_record
        """
        state = _protest_filed_by_a_prospective_bidder(
            solicitation_number="SOL-2238-C48",
            title="Storm Drainage Improvements",
            requirement_code="REQ-DRAIN",
            requirement_description="hydraulic model deliverable",
            legal_name="Netherby Drainage",
            tax_id="100000092",
            contact_email="v92@example.gov",
            question_text="which hydraulic model is required?",
            narrative="the model requirement is undisclosed",
        )
        protest_id = state["protest_id"]
        assert state["protest"]["record_item_count"] == 0

        response = api_client.create_record_item(
            protest_id,
            {"item_type": "AGENCY_REPORT", "document_ref": "AR-C48-001"},
            REVIEWER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
        )

        protest = fx.read_protest(protest_id)
        assert protest["status"] == "FILED"
        assert protest["record_item_count"] == 0

        # The very same role may read the record it may not write to.
        rows, meta = validate_paginated(
            api_client.list_record_items(protest_id, REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_officers_identical_filing_is_accepted_and_opens_the_review(self):
        """The first item filed with `item_type` `AGENCY_REPORT` by a caller acting as `ProcurementOfficer` advances the protest `FILED → UNDER_REVIEW` in the same request — the agency report is the pleading that opens the review.

        The server appends the item with a `sequence_number` equal to the protest's current `record_item_count` plus 1, stamps `submitted_at_utc` from the logical clock and `submitted_by_role` with the caller's `X-User-Role`, then recomputes the protest's `record_item_count` and increments the protest's `version` by 1.

        Design: Corner/rbac/corner_responsibility_reviewer_cannot_file_into_the_agency_record
        """
        state = _protest_filed_by_a_prospective_bidder(
            solicitation_number="SOL-2238-C48",
            title="Storm Drainage Improvements",
            requirement_code="REQ-DRAIN",
            requirement_description="hydraulic model deliverable",
            legal_name="Netherby Drainage",
            tax_id="100000092",
            contact_email="v92@example.gov",
            question_text="which hydraulic model is required?",
            narrative="the model requirement is undisclosed",
        )
        protest_id = state["protest_id"]

        refused = api_client.create_record_item(
            protest_id,
            {"item_type": "AGENCY_REPORT", "document_ref": "AR-C48-001"},
            REVIEWER_HEADERS,
        )
        validate_error(
            refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
        )

        # Same path, same body, a role the endpoint does list.
        item = validate_success(
            api_client.create_record_item(
                protest_id,
                {"item_type": "AGENCY_REPORT", "document_ref": "AR-C48-001"},
                OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert item["sequence_number"] == 1
        assert item["item_type"] == "AGENCY_REPORT"
        assert item["submitted_by_role"] == "ProcurementOfficer"

        protest = fx.read_protest(protest_id)
        assert protest["status"] == "UNDER_REVIEW"
        assert protest["record_item_count"] == 1


class TestVendorCannotScreenASubcontractorForAnotherPrime:
    """A vendor may request a screening, but only for the subcontracts hanging
    off its own prime contract."""

    def test_the_identity_refusal_wins_over_a_role_refusal(self):
        """When the caller acts as `Vendor`, its `X-User-ID` must equal the `prime_vendor_id`.

        A mismatch is rejected with `ERR_VENDOR_IDENTITY_MISMATCH` (HTTP 403).

        When the subcontractor's `eligibility_status` is `ELIGIBLE`, `result` becomes `CLEARED` and `blocked_reason_code` is null.

        Design: Corner/rbac/corner_vendor_cannot_screen_a_subcontractor_for_another_prime
        """
        fx.reset_clock()

        prime_a = fx.create_vendor(
            legal_name="Oakhurst Prime",
            tax_id="100000093",
            contact_email="v93@example.gov",
        )
        prime_b = fx.create_vendor(
            legal_name="Pelham Prime",
            tax_id="100000094",
            contact_email="v94@example.gov",
        )
        sub = fx.create_vendor(
            legal_name="Quinlan Rebar",
            tax_id="100000095",
            contact_email="v95@example.gov",
        )

        solicitation = fx.create_solicitation(
            solicitation_number="SOL-2238-C49",
            title="Retaining Wall Construction",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc="2026-09-30T00:00:00Z",
            original_question_deadline_utc="2026-09-23T00:00:00Z",
            mandatory_requirements=[
                {
                    "requirement_code": "REQ-WALL",
                    "description": "MSE wall design",
                    "materiality": "MATERIAL",
                    "is_waivable": False,
                }
            ],
        )
        solicitation = fx.issue_solicitation(solicitation["id"])
        solicitation_id = solicitation["id"]

        body = {
            "solicitation_id": solicitation_id,
            "prime_vendor_id": prime_b["id"],
            "sub_vendor_id": sub["id"],
            "tier": 1,
        }

        # Vendor A holds a role the endpoint does list, so it clears the role
        # gate and is then stopped on its own identity.
        response = api_client.create_subcontractor_screening(
            body, make_vendor_headers(prime_a["id"])
        )
        error = validate_error(
            response, ApiErrorId.ERR_VENDOR_IDENTITY_MISMATCH.value, expected_status=403
        )
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
            "a vendor is a permitted caller on this endpoint, so the refusal "
            "must be the identity mismatch rather than the role refusal"
        )

        rows, meta = validate_paginated(
            api_client.list_subcontractor_screenings(
                OFFICER_HEADERS, params={"solicitation_id": solicitation_id}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

        # The identical body sent by the named prime is accepted, and the
        # eligible subcontractor clears.
        screening = validate_success(
            api_client.create_subcontractor_screening(
                body, make_vendor_headers(prime_b["id"])
            ),
            expected_status=201,
        )
        assert screening["prime_vendor_id"] == prime_b["id"]
        assert screening["sub_vendor_id"] == sub["id"]
        assert screening["result"] == "CLEARED"
        assert screening["blocked_reason_code"] is None
