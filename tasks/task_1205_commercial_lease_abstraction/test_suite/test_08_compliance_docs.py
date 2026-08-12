"""Compliance documents: rejection reason requirement and the
ACCEPTED-only coverage-overlap semantics."""
from test_helpers import (
    ApiErrorId,
    create_compliance_doc_on,
    create_lease,
    create_property,
    review_compliance_doc,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PROP_MGR = TEST_USERS["property_manager_headers"]


class TestComplianceDocReject:
    def test_compliance_doc_reject_requires_reason(self, api):
        """PRD §3.7: "Rejection requires a non-empty `rejection_reason` in the
        request, else `ERR_REJECTION_REASON_REQUIRED` (HTTP 400), and moves the
        document to `REJECTED`."

        Design: Corner/validations/compliance_doc_reject_requires_reason
        """
        set_clock()
        prop = create_property()
        lease = create_lease(prop["id"], recovery_structure="GROSS",
                             pro_rata_share_bps=0)
        doc = create_compliance_doc_on(lease["id"], kind="INSURANCE_CERT")
        review_compliance_doc(doc["id"])
        resp = api.reject_compliance_doc(doc["id"], {"rejection_reason": ""}, PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_REJECTION_REASON_REQUIRED)


class TestCoverageOverlapAcceptedOnly:
    def _setup_docs(self, api):
        """INSURANCE_CERT docs: A ACCEPTED [2027-01-01, 2028-01-01), B REJECTED
        with the same window, C UNDER_REVIEW overlapping A, D UNDER_REVIEW
        adjacent to A."""
        set_clock()
        prop = create_property()
        lease = create_lease(
            prop["id"], expiration_date="2029-12-31",
            recovery_structure="GROSS", pro_rata_share_bps=0,
        )
        doc_a = create_compliance_doc_on(lease["id"], kind="INSURANCE_CERT")
        review_compliance_doc(doc_a["id"])
        accepted = validate_success(api.accept_compliance_doc(doc_a["id"], PROP_MGR))
        assert accepted["status"] == "ACCEPTED"
        doc_b = create_compliance_doc_on(lease["id"], kind="INSURANCE_CERT")
        review_compliance_doc(doc_b["id"])
        rejected = validate_success(
            api.reject_compliance_doc(
                doc_b["id"], {"rejection_reason": "insufficient coverage limit"},
                PROP_MGR,
            )
        )
        assert rejected["status"] == "REJECTED"
        doc_c = create_compliance_doc_on(
            lease["id"], kind="INSURANCE_CERT",
            period_start="2027-06-01", period_end="2028-06-01",
        )
        review_compliance_doc(doc_c["id"])
        doc_d = create_compliance_doc_on(
            lease["id"], kind="INSURANCE_CERT",
            period_start="2028-01-01", period_end="2029-01-01",
        )
        review_compliance_doc(doc_d["id"])
        return {"A": doc_a, "B": doc_b, "C": doc_c, "D": doc_d}

    def test_overlap_with_accepted_doc_rejected(self, api):
        """PRD §3.7: "Acceptance is guarded by a coverage exclusivity rule: no
        other `ACCEPTED` document of the same kind on the same lease may have an
        overlapping coverage window, else `ERR_COVERAGE_OVERLAP`; accepting an
        insurance certificate whose period covers the current date leaves the
        lease's lifecycle untouched, as does any other acceptance."
        (The rule names only ACCEPTED documents: the REJECTED doc B sharing
        A's window does not participate, and doc C's one-day-plus overlap with
        A is what triggers the guard.)

        Design: Difficulty/resource_temporal_overlap/compliance_doc_coverage_overlap_accepted_only
        """
        docs = self._setup_docs(api)
        resp = api.accept_compliance_doc(docs["C"]["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)

    def test_adjacent_doc_accepted_despite_rejected_history(self, api):
        """PRD §3.7: "Acceptance is guarded by a coverage exclusivity rule: no
        other `ACCEPTED` document of the same kind on the same lease may have an
        overlapping coverage window, else `ERR_COVERAGE_OVERLAP`; accepting an
        insurance certificate whose period covers the current date leaves the
        lease's lifecycle untouched, as does any other acceptance."
        (Doc D's window starts exactly where A's ends — touching at the
        endpoint is not an overlap — and the REJECTED doc B is not part of the
        guard at all.)

        Design: Difficulty/resource_temporal_overlap/compliance_doc_coverage_overlap_accepted_only
        """
        docs = self._setup_docs(api)
        accepted = validate_success(api.accept_compliance_doc(docs["D"]["id"], PROP_MGR))
        assert accepted["status"] == "ACCEPTED", (
            f"adjacent window (start == prior end) must be acceptable, got "
            f"{accepted['status']}"
        )
