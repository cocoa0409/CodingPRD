"""A thin, typed wrapper over every operation the contract publishes (PRD §4).

One method per endpoint. Each method takes the path parameters positionally, the
body or query fields as keyword arguments, and a ``headers`` mapping built by
``test_helpers.test_users``. Optional fields are omitted from the payload unless
the caller passes them, so a test can distinguish "field absent" from
"field explicitly null" -- a distinction several defaults depend on.
"""

from prd_bench_local_runner.testing import GenericApiClient


def _payload(**fields):
    """Drop keys the caller did not supply, keeping explicit ``None`` values."""
    return {key: value for key, value in fields.items() if value is not _OMIT}


class _Omit:
    """Sentinel marking an argument the caller did not supply at all."""

    def __repr__(self):
        return "<omitted>"


_OMIT = _Omit()
OMIT = _OMIT


class ApiClient(GenericApiClient):
    """Domain-named client for the historic rehabilitation credit service."""

    # ─── Transport helpers ────────────────────────────

    def _send_get(self, path, params=None, headers=None):
        """GET with query parameters, keeping headers and params distinct."""
        return self._request("GET", path, payload=params or None, headers=headers)

    def _send_patch(self, path, body=None, headers=None):
        """PATCH with a JSON body."""
        return self._request("PATCH", path, payload=body, headers=headers)

    # ─── Logical clock (PRD §2.4) ─────────────────────

    def set_clock(self, to_iso8601, headers=None):
        """Move the logical clock; the one operation that needs no identity."""
        return self.post(
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers=headers or {"Content-Type": "application/json"},
        )

    # ─── Developers (PRD §3.1) ───────────────────────

    def create_developer(
        self,
        headers,
        legal_name=_OMIT,
        taxpayer_id_last4=_OMIT,
        entity_type=_OMIT,
        contact_email=_OMIT,
        **extra,
    ):
        body = _payload(
            legal_name=legal_name,
            taxpayer_id_last4=taxpayer_id_last4,
            entity_type=entity_type,
            contact_email=contact_email,
        )
        body.update(extra)
        return self.post("/developers", body, headers=headers)

    def get_developer(self, developer_id, headers):
        return self._send_get("/developers/{0}".format(developer_id), headers=headers)

    # ─── Reviewers (PRD §3.1) ────────────────────────

    def create_reviewer(
        self,
        headers,
        full_name=_OMIT,
        agency=_OMIT,
        state_code=_OMIT,
        credential_status=_OMIT,
        **extra,
    ):
        body = _payload(
            full_name=full_name,
            agency=agency,
            state_code=state_code,
            credential_status=credential_status,
        )
        body.update(extra)
        return self.post("/reviewers", body, headers=headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._send_get("/reviewers/{0}".format(reviewer_id), headers=headers)

    # ─── Properties (PRD §3.1) ───────────────────────

    def create_property(
        self,
        headers,
        name=_OMIT,
        street_address=_OMIT,
        city=_OMIT,
        state_code=_OMIT,
        year_built=_OMIT,
        listing_status=_OMIT,
        **extra,
    ):
        body = _payload(
            name=name,
            street_address=street_address,
            city=city,
            state_code=state_code,
            year_built=year_built,
            listing_status=listing_status,
        )
        body.update(extra)
        return self.post("/properties", body, headers=headers)

    def get_property(self, property_id, headers):
        return self._send_get("/properties/{0}".format(property_id), headers=headers)

    # ─── Projects (PRD §3.2) ─────────────────────────

    def create_project(
        self,
        headers,
        developer_id=_OMIT,
        property_id=_OMIT,
        project_name=_OMIT,
        structure_type=_OMIT,
        adjusted_basis_cents=_OMIT,
        measuring_period_months=_OMIT,
        measuring_period_start_date=_OMIT,
        **extra,
    ):
        body = _payload(
            developer_id=developer_id,
            property_id=property_id,
            project_name=project_name,
            structure_type=structure_type,
            adjusted_basis_cents=adjusted_basis_cents,
            measuring_period_months=measuring_period_months,
            measuring_period_start_date=measuring_period_start_date,
        )
        body.update(extra)
        return self.post("/projects", body, headers=headers)

    def get_project(self, project_id, headers):
        return self._send_get("/projects/{0}".format(project_id), headers=headers)

    def list_projects(
        self,
        headers,
        developer_id=_OMIT,
        property_id=_OMIT,
        certification_status=_OMIT,
        compliance_status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            developer_id=developer_id,
            property_id=property_id,
            certification_status=certification_status,
            compliance_status=compliance_status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/projects", params, headers=headers)

    def patch_project(
        self,
        project_id,
        headers,
        expected_project_version=_OMIT,
        adjusted_basis_cents=_OMIT,
        measuring_period_start_date=_OMIT,
        measuring_period_months=_OMIT,
        **extra,
    ):
        body = _payload(
            expected_project_version=expected_project_version,
            adjusted_basis_cents=adjusted_basis_cents,
            measuring_period_start_date=measuring_period_start_date,
            measuring_period_months=measuring_period_months,
        )
        body.update(extra)
        return self._send_patch(
            "/projects/{0}".format(project_id), body, headers=headers
        )

    def place_in_service(
        self, project_id, headers, placed_in_service_date=_OMIT, **extra
    ):
        body = _payload(placed_in_service_date=placed_in_service_date)
        body.update(extra)
        return self.post(
            "/projects/{0}/place-in-service".format(project_id), body, headers=headers
        )

    def get_qre_summary(self, project_id, headers, variant=_OMIT, **extra):
        params = _payload(variant=variant)
        params.update(extra)
        return self._send_get(
            "/projects/{0}/qre-summary".format(project_id), params, headers=headers
        )

    def list_project_cost_line_items(
        self,
        project_id,
        headers,
        classification=_OMIT,
        category=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            classification=classification,
            category=category,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get(
            "/projects/{0}/cost-line-items".format(project_id), params, headers=headers
        )

    def list_project_investor_interests(
        self, project_id, headers, kind=_OMIT, status=_OMIT, limit=_OMIT, offset=_OMIT,
        **extra,
    ):
        params = _payload(kind=kind, status=status, limit=limit, offset=offset)
        params.update(extra)
        return self._send_get(
            "/projects/{0}/investor-interests".format(project_id),
            params,
            headers=headers
        )

    def list_project_credit_claims(
        self,
        project_id,
        headers,
        status=_OMIT,
        tax_year=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(status=status, tax_year=tax_year, limit=limit, offset=offset)
        params.update(extra)
        return self._send_get(
            "/projects/{0}/credit-claims".format(project_id), params, headers=headers
        )

    def list_project_recapture_events(
        self,
        project_id,
        headers,
        event_type=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            event_type=event_type, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get(
            "/projects/{0}/recapture-events".format(project_id), params, headers=headers
        )

    def list_project_compliance_covenants(
        self,
        project_id,
        headers,
        covenant_type=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            covenant_type=covenant_type, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get(
            "/projects/{0}/compliance-covenants".format(project_id),
            params,
            headers=headers
        )

    # ─── Part applications (PRD §3.3, §3.4) ──────────

    def create_part_application(
        self,
        headers,
        project_id=_OMIT,
        part_number=_OMIT,
        narrative=_OMIT,
        expected_project_version=_OMIT,
        **extra,
    ):
        body = _payload(
            project_id=project_id,
            part_number=part_number,
            narrative=narrative,
            expected_project_version=expected_project_version,
        )
        body.update(extra)
        return self.post("/part-applications", body, headers=headers)

    def get_part_application(self, part_application_id, headers):
        return self._send_get(
            "/part-applications/{0}".format(part_application_id), headers=headers
        )

    def list_part_applications(
        self,
        headers,
        project_id=_OMIT,
        part_number=_OMIT,
        status=_OMIT,
        shpo_reviewer_id=_OMIT,
        nps_reviewer_id=_OMIT,
        supersedes_application_id=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            project_id=project_id,
            part_number=part_number,
            status=status,
            shpo_reviewer_id=shpo_reviewer_id,
            nps_reviewer_id=nps_reviewer_id,
            supersedes_application_id=supersedes_application_id,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/part-applications", params, headers=headers)

    def submit_part_application(
        self, part_application_id, headers, shpo_reviewer_id=_OMIT, **extra
    ):
        body = _payload(shpo_reviewer_id=shpo_reviewer_id)
        body.update(extra)
        return self.post(
            "/part-applications/{0}/submit".format(part_application_id),
            body,
            headers=headers,
        )

    def shpo_recommend(
        self,
        part_application_id,
        headers,
        recommendation=_OMIT,
        review_note=_OMIT,
        **extra,
    ):
        body = _payload(recommendation=recommendation, review_note=review_note)
        body.update(extra)
        return self.post(
            "/part-applications/{0}/shpo-recommend".format(part_application_id),
            body,
            headers=headers,
        )

    def nps_determination(
        self,
        part_application_id,
        headers,
        determination=_OMIT,
        waived_finding_ids=_OMIT,
        review_note=_OMIT,
        **extra,
    ):
        body = _payload(
            determination=determination,
            waived_finding_ids=waived_finding_ids,
            review_note=review_note,
        )
        body.update(extra)
        return self.post(
            "/part-applications/{0}/nps-determination".format(part_application_id),
            body,
            headers=headers,
        )

    def resubmit_part_application(
        self, part_application_id, headers, narrative=_OMIT, **extra
    ):
        body = _payload(narrative=narrative)
        body.update(extra)
        return self.post(
            "/part-applications/{0}/resubmit".format(part_application_id),
            body,
            headers=headers,
        )

    # ─── Standard findings (PRD §3.4) ────────────────

    def create_finding(
        self,
        part_application_id,
        headers,
        standard_number=_OMIT,
        severity=_OMIT,
        description=_OMIT,
        **extra,
    ):
        body = _payload(
            standard_number=standard_number, severity=severity, description=description
        )
        body.update(extra)
        return self.post(
            "/part-applications/{0}/findings".format(part_application_id),
            body,
            headers=headers,
        )

    def list_findings(
        self,
        part_application_id,
        headers,
        severity=_OMIT,
        resolution_state=_OMIT,
        standard_number=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            severity=severity,
            resolution_state=resolution_state,
            standard_number=standard_number,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get(
            "/part-applications/{0}/findings".format(part_application_id),
            params,
            headers=headers,
        )

    def get_finding(self, finding_id, headers):
        return self._send_get("/findings/{0}".format(finding_id), headers=headers)

    # ─── Cost line items (PRD §3.6) ──────────────────

    def create_cost_line_item(
        self,
        headers,
        project_id=_OMIT,
        vendor_name=_OMIT,
        category=_OMIT,
        amount_cents=_OMIT,
        incurred_date=_OMIT,
        classification=_OMIT,
        **extra,
    ):
        body = _payload(
            project_id=project_id,
            vendor_name=vendor_name,
            category=category,
            amount_cents=amount_cents,
            incurred_date=incurred_date,
            classification=classification,
        )
        body.update(extra)
        return self.post("/cost-line-items", body, headers=headers)

    def classify_cost_line_item(
        self,
        cost_line_item_id,
        headers,
        classification=_OMIT,
        exclusion_reason=_OMIT,
        **extra,
    ):
        body = _payload(
            classification=classification, exclusion_reason=exclusion_reason
        )
        body.update(extra)
        return self.post(
            "/cost-line-items/{0}/classify".format(cost_line_item_id),
            body,
            headers=headers,
        )

    def get_cost_line_item(self, cost_line_item_id, headers):
        return self._send_get(
            "/cost-line-items/{0}".format(cost_line_item_id), headers=headers
        )

    # ─── Amendments (PRD §3.5) ───────────────────────

    def create_amendment(
        self,
        headers,
        project_id=_OMIT,
        part_application_id=_OMIT,
        scope_category=_OMIT,
        change_description=_OMIT,
        cost_delta_cents=_OMIT,
        addresses_finding_id=_OMIT,
        **extra,
    ):
        body = _payload(
            project_id=project_id,
            part_application_id=part_application_id,
            scope_category=scope_category,
            change_description=change_description,
            cost_delta_cents=cost_delta_cents,
            addresses_finding_id=addresses_finding_id,
        )
        body.update(extra)
        return self.post("/amendments", body, headers=headers)

    def get_amendment(self, amendment_id, headers):
        return self._send_get("/amendments/{0}".format(amendment_id), headers=headers)

    def list_amendments(
        self,
        headers,
        project_id=_OMIT,
        part_application_id=_OMIT,
        addresses_finding_id=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra,
    ):
        params = _payload(
            project_id=project_id,
            part_application_id=part_application_id,
            addresses_finding_id=addresses_finding_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/amendments", params, headers=headers)

    def submit_amendment(self, amendment_id, headers, **extra):
        body = dict(extra)
        return self.post(
            "/amendments/{0}/submit".format(amendment_id), body, headers=headers
        )

    def concur_amendment(
        self, amendment_id, headers, decision=_OMIT, concurrence_note=_OMIT, **extra
    ):
        body = _payload(decision=decision, concurrence_note=concurrence_note)
        body.update(extra)
        return self.post(
            "/amendments/{0}/concur".format(amendment_id), body, headers=headers
        )

    # ─── Investor interests (PRD §3.7) ───────────────

    def create_investor_interest(
        self,
        headers,
        project_id=_OMIT,
        kind=_OMIT,
        party_legal_name=_OMIT,
        party_tax_status=_OMIT,
        capital_committed_cents=_OMIT,
        credit_allocation_pct=_OMIT,
        lease_term_years=_OMIT,
        **extra,
    ):
        body = _payload(
            project_id=project_id,
            kind=kind,
            party_legal_name=party_legal_name,
            party_tax_status=party_tax_status,
            capital_committed_cents=capital_committed_cents,
            credit_allocation_pct=credit_allocation_pct,
            lease_term_years=lease_term_years,
        )
        body.update(extra)
        return self.post("/investor-interests", body, headers=headers)

    def elect_pass_through(self, investor_interest_id, headers, **extra):
        body = dict(extra)
        return self.post(
            "/investor-interests/{0}/elect-pass-through".format(investor_interest_id),
            body,
            headers=headers,
        )

    def get_investor_interest(self, investor_interest_id, headers):
        return self._send_get(
            "/investor-interests/{0}".format(investor_interest_id), headers=headers
        )

    # ─── Credit claims (PRD §3.9) ────────────────────

    def create_credit_claim(
        self, headers, project_id=_OMIT, tax_year=_OMIT, **extra
    ):
        body = _payload(project_id=project_id, tax_year=tax_year)
        body.update(extra)
        return self.post("/credit-claims", body, headers=headers)

    def file_credit_claim(self, credit_claim_id, headers, **extra):
        body = dict(extra)
        return self.post(
            "/credit-claims/{0}/file".format(credit_claim_id), body, headers=headers
        )

    def get_credit_claim(self, credit_claim_id, headers):
        return self._send_get(
            "/credit-claims/{0}".format(credit_claim_id), headers=headers
        )

    # ─── Compliance covenants (PRD §3.8) ─────────────

    def create_compliance_covenant(
        self,
        headers,
        project_id=_OMIT,
        covenant_type=_OMIT,
        monitoring_frequency=_OMIT,
        window_start_date=_OMIT,
        window_end_date=_OMIT,
        **extra,
    ):
        body = _payload(
            project_id=project_id,
            covenant_type=covenant_type,
            monitoring_frequency=monitoring_frequency,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        )
        body.update(extra)
        return self.post("/compliance-covenants", body, headers=headers)

    def attest_covenant(
        self,
        covenant_id,
        headers,
        period_end_date=_OMIT,
        outcome=_OMIT,
        **extra,
    ):
        body = _payload(period_end_date=period_end_date, outcome=outcome)
        body.update(extra)
        return self.post(
            "/compliance-covenants/{0}/attest".format(covenant_id),
            body,
            headers=headers,
        )

    def get_compliance_covenant(self, covenant_id, headers):
        return self._send_get(
            "/compliance-covenants/{0}".format(covenant_id), headers=headers
        )

    # ─── Recapture events (PRD §3.8) ─────────────────

    def create_recapture_event(
        self, headers, project_id=_OMIT, event_type=_OMIT, event_date=_OMIT, **extra
    ):
        body = _payload(
            project_id=project_id, event_type=event_type, event_date=event_date
        )
        body.update(extra)
        return self.post("/recapture-events", body, headers=headers)

    def get_recapture_event(self, recapture_event_id, headers):
        return self._send_get(
            "/recapture-events/{0}".format(recapture_event_id), headers=headers
        )
