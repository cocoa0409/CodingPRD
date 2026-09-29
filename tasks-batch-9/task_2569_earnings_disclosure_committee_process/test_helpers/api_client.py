"""One method per endpoint of the Earnings Disclosure Committee Process API.

Every method returns the raw response so a test can assert on the status code
as well as the envelope. List methods take their filters and the ``limit`` /
``offset`` pagination parameters as keyword arguments; a keyword left at
``None`` is not sent at all, so the server's own defaults apply.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/disclosure"


def _query(**kwargs):
    """Drop unset keywords so the server sees the parameter as absent."""
    return {k: v for k, v in kwargs.items() if v is not None}


class DisclosureApiClient(GenericApiClient):
    """HTTP surface of the disclosure committee service."""

    # ---------------------------------------------------------------- clock

    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- charters

    def list_charters(self, headers=None, limit=None, offset=None):
        return self._request(
            "GET", f"{BASE}/charters", _query(limit=limit, offset=offset), headers
        )

    def get_charter(self, charter_id, headers=None):
        return self._request("GET", f"{BASE}/charters/{charter_id}", None, headers)

    def create_charter(self, payload, headers=None):
        return self._request("POST", f"{BASE}/charters", payload, headers)

    def transition_charter(self, charter_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/charters/{charter_id}/transitions", payload, headers
        )

    def create_member(self, charter_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/charters/{charter_id}/members", payload, headers
        )

    # ------------------------------------------------------ committee members

    def list_members(
        self,
        headers=None,
        charter_id=None,
        function=None,
        status=None,
        is_officer=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/committee-members",
            _query(
                charter_id=charter_id,
                function=function,
                status=status,
                is_officer=is_officer,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_member(self, member_id, headers=None):
        return self._request(
            "GET", f"{BASE}/committee-members/{member_id}", None, headers
        )

    def transition_member(self, member_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/committee-members/{member_id}/transitions", payload, headers
        )

    # ------------------------------------------------------- reporting cycles

    def list_cycles(
        self,
        headers=None,
        charter_id=None,
        status=None,
        form_type=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/reporting-cycles",
            _query(
                charter_id=charter_id,
                status=status,
                form_type=form_type,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_cycle(self, cycle_id, headers=None):
        return self._request("GET", f"{BASE}/reporting-cycles/{cycle_id}", None, headers)

    def get_readiness(self, cycle_id, headers=None):
        return self._request(
            "GET", f"{BASE}/reporting-cycles/{cycle_id}/readiness", None, headers
        )

    def create_cycle(self, payload, headers=None):
        return self._request("POST", f"{BASE}/reporting-cycles", payload, headers)

    def transition_cycle(self, cycle_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/reporting-cycles/{cycle_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------- milestones

    def list_cycle_milestones(self, cycle_id, headers=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BASE}/reporting-cycles/{cycle_id}/milestones",
            _query(limit=limit, offset=offset),
            headers,
        )

    def create_milestone(self, cycle_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/reporting-cycles/{cycle_id}/milestones", payload, headers
        )

    def transition_milestone(self, milestone_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/milestones/{milestone_id}/transitions", payload, headers
        )

    # ------------------------------------------------------ sub-certifications

    def list_subcerts(
        self,
        headers=None,
        cycle_id=None,
        member_id=None,
        status=None,
        scope_area=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/sub-certifications",
            _query(
                cycle_id=cycle_id,
                member_id=member_id,
                status=status,
                scope_area=scope_area,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_subcert(self, subcert_id, headers=None):
        return self._request(
            "GET", f"{BASE}/sub-certifications/{subcert_id}", None, headers
        )

    def create_subcert(self, payload, headers=None):
        return self._request("POST", f"{BASE}/sub-certifications", payload, headers)

    def transition_subcert(self, subcert_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/sub-certifications/{subcert_id}/transitions", payload, headers
        )

    # --------------------------------------------------- officer certifications

    def list_officer_certs(
        self,
        headers=None,
        cycle_id=None,
        officer_member_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/officer-certifications",
            _query(
                cycle_id=cycle_id,
                officer_member_id=officer_member_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_officer_cert(self, cert_id, headers=None):
        return self._request(
            "GET", f"{BASE}/officer-certifications/{cert_id}", None, headers
        )

    def create_officer_cert(self, payload, headers=None):
        return self._request("POST", f"{BASE}/officer-certifications", payload, headers)

    def sign_officer_cert(self, cert_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/officer-certifications/{cert_id}/sign", payload, headers
        )

    # -------------------------------------------------------------- documents

    def list_documents(
        self,
        headers=None,
        cycle_id=None,
        author_member_id=None,
        doc_type=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/documents",
            _query(
                cycle_id=cycle_id,
                author_member_id=author_member_id,
                doc_type=doc_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_document(self, document_id, headers=None):
        return self._request("GET", f"{BASE}/documents/{document_id}", None, headers)

    def create_document(self, payload, headers=None):
        return self._request("POST", f"{BASE}/documents", payload, headers)

    def transition_document(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/documents/{document_id}/transitions", payload, headers
        )

    # ----------------------------------------------------------- tie-out items

    def list_tie_out_items(
        self,
        headers=None,
        document_id=None,
        preparer_member_id=None,
        reviewer_member_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/tie-out-items",
            _query(
                document_id=document_id,
                preparer_member_id=preparer_member_id,
                reviewer_member_id=reviewer_member_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_tie_out_item(self, item_id, headers=None):
        return self._request("GET", f"{BASE}/tie-out-items/{item_id}", None, headers)

    def create_tie_out_item(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/documents/{document_id}/tie-out-items", payload, headers
        )

    def review_tie_out_item(self, item_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/tie-out-items/{item_id}/review", payload, headers
        )

    # -------------------------------------------------------- adjusted measures

    def list_adjusted_measures(self, document_id, headers=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BASE}/documents/{document_id}/adjusted-measures",
            _query(limit=limit, offset=offset),
            headers,
        )

    def create_adjusted_measure(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/documents/{document_id}/adjusted-measures", payload, headers
        )

    def reconcile_adjusted_measure(self, measure_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/adjusted-measures/{measure_id}/reconcile", payload, headers
        )

    # ------------------------------------------------------------- q&a items

    def list_qa_items(self, document_id, headers=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BASE}/documents/{document_id}/qa-items",
            _query(limit=limit, offset=offset),
            headers,
        )

    def create_qa_item(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/documents/{document_id}/qa-items", payload, headers
        )

    def clear_qa_item(self, qa_item_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/qa-items/{qa_item_id}/clear", payload, headers
        )

    # --------------------------------------------------------- material events

    def list_material_events(
        self,
        headers=None,
        cycle_id=None,
        linked_document_id=None,
        assessment_status=None,
        category=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/material-events",
            _query(
                cycle_id=cycle_id,
                linked_document_id=linked_document_id,
                assessment_status=assessment_status,
                category=category,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_material_event(self, event_id, headers=None):
        return self._request("GET", f"{BASE}/material-events/{event_id}", None, headers)

    def create_material_event(self, cycle_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/reporting-cycles/{cycle_id}/material-events", payload, headers
        )

    def transition_material_event(self, event_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/material-events/{event_id}/transitions", payload, headers
        )

    # ----------------------------------------------------------------- filings

    def list_filings(
        self,
        headers=None,
        cycle_id=None,
        document_id=None,
        amends_filing_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/filings",
            _query(
                cycle_id=cycle_id,
                document_id=document_id,
                amends_filing_id=amends_filing_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_filing(self, filing_id, headers=None):
        return self._request("GET", f"{BASE}/filings/{filing_id}", None, headers)

    def create_filing(self, payload, headers=None):
        return self._request("POST", f"{BASE}/filings", payload, headers)

    # ------------------------------------------------------------- corrections

    def list_corrections(
        self,
        headers=None,
        filing_id=None,
        status=None,
        classification=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/corrections",
            _query(
                filing_id=filing_id,
                status=status,
                classification=classification,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_correction(self, correction_id, headers=None):
        return self._request("GET", f"{BASE}/corrections/{correction_id}", None, headers)

    def create_correction(self, filing_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/filings/{filing_id}/corrections", payload, headers
        )

    def transition_correction(self, correction_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/corrections/{correction_id}/transitions", payload, headers
        )

    # ---------------------------------------------------- control deficiencies

    def list_control_deficiencies(
        self, correction_id, headers=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{BASE}/corrections/{correction_id}/control-deficiencies",
            _query(limit=limit, offset=offset),
            headers,
        )

    def mitigate_control_deficiency(self, deficiency_id, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/control-deficiencies/{deficiency_id}/mitigate", payload, headers
        )
