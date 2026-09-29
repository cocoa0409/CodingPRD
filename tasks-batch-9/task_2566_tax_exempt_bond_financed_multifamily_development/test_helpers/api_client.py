"""A thin, typed wrapper over every operation the contract publishes (PRD §4).

One method per endpoint. Path parameters come first, body or query fields arrive
as keyword arguments, and ``headers`` is a mapping built by
``test_helpers.test_users``. A field the caller does not mention is left out of
the body entirely, so a test can distinguish "field absent" from "field
explicitly null" — several declared defaults and several required-field rules
depend on exactly that distinction. Unknown keys may also be passed through with
``**extra``, because the contract ignores them rather than rejecting them.

Every collection is a top-level peer resource: a draw request is addressed at
``/draw-requests/{id}``, never underneath its bond issue.
"""

from prd_bench_local_runner.testing import GenericApiClient


class _Omit:
    """Sentinel marking an argument the caller did not supply at all."""

    def __repr__(self):
        return "<omitted>"


_OMIT = _Omit()
OMIT = _OMIT


def _payload(**fields):
    """Drop keys the caller did not supply, keeping explicit ``None`` values."""
    return {key: value for key, value in fields.items() if value is not _OMIT}


class ApiClient(GenericApiClient):
    """Domain-named client for the tax-exempt bond multifamily API."""

    # ─── Transport helpers ────────────────────────────

    def _send_get(self, path, params=None, headers=None):
        """GET with query parameters, keeping headers and params distinct."""
        return self._request("GET", path, payload=params or None, headers=headers)

    def _send_post(self, path, body=None, headers=None):
        """POST with a JSON body, which may legitimately be empty."""
        return self._request(
            "POST", path, payload=body if body is not None else {}, headers=headers
        )

    def _send_patch(self, path, body=None, headers=None):
        return self._request(
            "PATCH", path, payload=body if body is not None else {}, headers=headers
        )

    # ─── The logical clock (PRD §2.4, §3.9) ───────────

    def set_clock(self, current_utc, headers=None):
        """Move the logical clock and evaluate every time-gated transition."""
        return self._send_post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    # ─── Development sponsors (PRD §3.1) ──────────────

    def create_developer(self, headers, name=_OMIT, tax_id=_OMIT, contact_email=_OMIT,
                         **extra):
        body = _payload(name=name, tax_id=tax_id, contact_email=contact_email)
        body.update(extra)
        return self._send_post("/developers", body, headers=headers)

    def get_developer(self, developer_id, headers):
        return self._send_get("/developers/{0}".format(developer_id), headers=headers)

    def sanction_developer(self, developer_id, headers, action=_OMIT, reason=_OMIT,
                           **extra):
        body = _payload(action=action, reason=reason)
        body.update(extra)
        return self._send_post(
            "/developers/{0}/sanctions".format(developer_id), body, headers=headers
        )

    # ─── Tax-credit investors (PRD §3.1) ──────────────

    def create_investor(self, headers, name=_OMIT, tax_id=_OMIT, investor_type=_OMIT,
                        **extra):
        body = _payload(name=name, tax_id=tax_id, investor_type=investor_type)
        body.update(extra)
        return self._send_post("/investors", body, headers=headers)

    def get_investor(self, investor_id, headers):
        return self._send_get("/investors/{0}".format(investor_id), headers=headers)

    # ─── Program-year cap pools (PRD §3.1) ────────────

    def create_cap_pool(self, headers, program_year=_OMIT, base_cap_cents=_OMIT,
                        carryforward_cents=_OMIT, **extra):
        body = _payload(
            program_year=program_year,
            base_cap_cents=base_cap_cents,
            carryforward_cents=carryforward_cents,
        )
        body.update(extra)
        return self._send_post("/cap-pools", body, headers=headers)

    def get_cap_pool(self, cap_pool_id, headers):
        """The read that supplies the expected pool version for an award."""
        return self._send_get("/cap-pools/{0}".format(cap_pool_id), headers=headers)

    # ─── Developments (PRD §3.2) ──────────────────────

    def create_project(self, headers, developer_id=_OMIT, name=_OMIT, total_units=_OMIT,
                       total_floor_space_sqft=_OMIT, land_cost_cents=_OMIT,
                       depreciable_basis_cents=_OMIT, set_aside_election=_OMIT, **extra):
        body = _payload(
            developer_id=developer_id,
            name=name,
            total_units=total_units,
            total_floor_space_sqft=total_floor_space_sqft,
            land_cost_cents=land_cost_cents,
            depreciable_basis_cents=depreciable_basis_cents,
            set_aside_election=set_aside_election,
        )
        body.update(extra)
        return self._send_post("/projects", body, headers=headers)

    def get_project(self, project_id, headers):
        return self._send_get("/projects/{0}".format(project_id), headers=headers)

    def list_projects(self, headers, developer_id=_OMIT, development_status=_OMIT,
                      limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            developer_id=developer_id,
            development_status=development_status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/projects", params, headers=headers)

    # ─── Unit designations (PRD §3.2) ─────────────────

    def create_unit_restriction(self, headers, project_id=_OMIT, unit_number=_OMIT,
                                bedroom_count=_OMIT, floor_space_sqft=_OMIT,
                                designation=_OMIT, utility_allowance_cents=_OMIT,
                                market_rent_cents=_OMIT, ami_percent=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            unit_number=unit_number,
            bedroom_count=bedroom_count,
            floor_space_sqft=floor_space_sqft,
            designation=designation,
            utility_allowance_cents=utility_allowance_cents,
            market_rent_cents=market_rent_cents,
            ami_percent=ami_percent,
        )
        body.update(extra)
        return self._send_post("/unit-restrictions", body, headers=headers)

    def get_unit_restriction(self, unit_restriction_id, headers):
        return self._send_get(
            "/unit-restrictions/{0}".format(unit_restriction_id), headers=headers
        )

    def patch_unit_restriction(self, unit_restriction_id, headers, designation=_OMIT,
                               ami_percent=_OMIT, utility_allowance_cents=_OMIT,
                               market_rent_cents=_OMIT, **extra):
        body = _payload(
            designation=designation,
            ami_percent=ami_percent,
            utility_allowance_cents=utility_allowance_cents,
            market_rent_cents=market_rent_cents,
        )
        body.update(extra)
        return self._send_patch(
            "/unit-restrictions/{0}".format(unit_restriction_id), body, headers=headers
        )

    def list_unit_restrictions(self, headers, project_id=_OMIT, designation=_OMIT,
                               status=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id,
            designation=designation,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/unit-restrictions", params, headers=headers)

    # ─── Volume cap allocations (PRD §3.3) ────────────

    def create_volume_cap_allocation(self, headers, project_id=_OMIT, cap_pool_id=_OMIT,
                                     requested_amount_cents=_OMIT,
                                     requested_closing_date=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            cap_pool_id=cap_pool_id,
            requested_amount_cents=requested_amount_cents,
            requested_closing_date=requested_closing_date,
        )
        body.update(extra)
        return self._send_post("/volume-cap-allocations", body, headers=headers)

    def get_volume_cap_allocation(self, allocation_id, headers):
        return self._send_get(
            "/volume-cap-allocations/{0}".format(allocation_id), headers=headers
        )

    def decide_volume_cap_allocation(self, allocation_id, headers, decision=_OMIT,
                                     expected_cap_pool_version=_OMIT,
                                     awarded_amount_cents=_OMIT, expiry_date=_OMIT,
                                     denial_reason=_OMIT, **extra):
        body = _payload(
            decision=decision,
            expected_cap_pool_version=expected_cap_pool_version,
            awarded_amount_cents=awarded_amount_cents,
            expiry_date=expiry_date,
            denial_reason=denial_reason,
        )
        body.update(extra)
        return self._send_post(
            "/volume-cap-allocations/{0}/decision".format(allocation_id),
            body,
            headers=headers,
        )

    def return_volume_cap_allocation(self, allocation_id, headers, return_reason=_OMIT,
                                     **extra):
        body = _payload(return_reason=return_reason)
        body.update(extra)
        return self._send_post(
            "/volume-cap-allocations/{0}/return".format(allocation_id),
            body,
            headers=headers,
        )

    def revise_volume_cap_allocation(self, allocation_id, headers,
                                     requested_amount_cents=_OMIT,
                                     requested_closing_date=_OMIT, **extra):
        body = _payload(
            requested_amount_cents=requested_amount_cents,
            requested_closing_date=requested_closing_date,
        )
        body.update(extra)
        return self._send_post(
            "/volume-cap-allocations/{0}/revise".format(allocation_id),
            body,
            headers=headers,
        )

    def list_volume_cap_allocations(self, headers, project_id=_OMIT, cap_pool_id=_OMIT,
                                    status=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id,
            cap_pool_id=cap_pool_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/volume-cap-allocations", params, headers=headers)

    # ─── Land-use restriction agreements (PRD §3.4) ───

    def create_regulatory_agreement(self, headers, project_id=_OMIT,
                                    set_aside_election=_OMIT,
                                    compliance_period_years=_OMIT,
                                    extended_use_years=_OMIT, recording_county=_OMIT,
                                    **extra):
        body = _payload(
            project_id=project_id,
            set_aside_election=set_aside_election,
            compliance_period_years=compliance_period_years,
            extended_use_years=extended_use_years,
            recording_county=recording_county,
        )
        body.update(extra)
        return self._send_post("/regulatory-agreements", body, headers=headers)

    def get_regulatory_agreement(self, agreement_id, headers):
        return self._send_get(
            "/regulatory-agreements/{0}".format(agreement_id), headers=headers
        )

    def record_regulatory_agreement(self, agreement_id, headers, instrument_number=_OMIT,
                                    **extra):
        body = _payload(instrument_number=instrument_number)
        body.update(extra)
        return self._send_post(
            "/regulatory-agreements/{0}/record".format(agreement_id),
            body,
            headers=headers,
        )

    def amend_regulatory_agreement(self, agreement_id, headers, amendment_reason=_OMIT,
                                   compliance_period_years=_OMIT,
                                   extended_use_years=_OMIT, set_aside_election=_OMIT,
                                   **extra):
        body = _payload(
            amendment_reason=amendment_reason,
            compliance_period_years=compliance_period_years,
            extended_use_years=extended_use_years,
            set_aside_election=set_aside_election,
        )
        body.update(extra)
        return self._send_post(
            "/regulatory-agreements/{0}/amend".format(agreement_id),
            body,
            headers=headers,
        )

    def list_regulatory_agreements(self, headers, project_id=_OMIT, status=_OMIT,
                                   limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/regulatory-agreements", params, headers=headers)

    # ─── Bond issues (PRD §3.5, §3.7) ─────────────────

    def create_bond_issue(self, headers, project_id=_OMIT,
                          volume_cap_allocation_id=_OMIT, eligible_cost_cents=_OMIT,
                          capitalized_interest_cents=_OMIT, bond_yield_bps=_OMIT,
                          investment_yield_bps=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            volume_cap_allocation_id=volume_cap_allocation_id,
            eligible_cost_cents=eligible_cost_cents,
            capitalized_interest_cents=capitalized_interest_cents,
            bond_yield_bps=bond_yield_bps,
            investment_yield_bps=investment_yield_bps,
        )
        body.update(extra)
        return self._send_post("/bond-issues", body, headers=headers)

    def get_bond_issue(self, bond_issue_id, headers):
        """The read that supplies the expected issue version for a draw."""
        return self._send_get("/bond-issues/{0}".format(bond_issue_id), headers=headers)

    def issue_bond_issue(self, bond_issue_id, headers, closing_date=_OMIT, **extra):
        body = _payload(closing_date=closing_date)
        body.update(extra)
        return self._send_post(
            "/bond-issues/{0}/issue".format(bond_issue_id), body, headers=headers
        )

    def record_operating_month(self, bond_issue_id, headers, month_index=_OMIT,
                               noi_cents=_OMIT, debt_service_cents=_OMIT,
                               occupied_units=_OMIT, **extra):
        body = _payload(
            month_index=month_index,
            noi_cents=noi_cents,
            debt_service_cents=debt_service_cents,
            occupied_units=occupied_units,
        )
        body.update(extra)
        return self._send_post(
            "/bond-issues/{0}/operating-months".format(bond_issue_id),
            body,
            headers=headers,
        )

    def convert_bond_issue(self, bond_issue_id, headers, conversion_date=_OMIT,
                           dscr_basis=_OMIT, **extra):
        body = _payload(conversion_date=conversion_date, dscr_basis=dscr_basis)
        body.update(extra)
        return self._send_post(
            "/bond-issues/{0}/convert".format(bond_issue_id), body, headers=headers
        )

    def mandatory_redeem_bond_issue(self, bond_issue_id, headers, redemption_date=_OMIT,
                                    reason=_OMIT, **extra):
        body = _payload(redemption_date=redemption_date, reason=reason)
        body.update(extra)
        return self._send_post(
            "/bond-issues/{0}/mandatory-redeem".format(bond_issue_id),
            body,
            headers=headers,
        )

    def list_bond_issues(self, headers, project_id=_OMIT,
                         volume_cap_allocation_id=_OMIT, status=_OMIT, limit=_OMIT,
                         offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id,
            volume_cap_allocation_id=volume_cap_allocation_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/bond-issues", params, headers=headers)

    # ─── Construction draws (PRD §3.6) ────────────────

    def create_draw_request(self, headers, bond_issue_id=_OMIT, draw_number=_OMIT,
                            period_start=_OMIT, period_end=_OMIT,
                            requested_amount_cents=_OMIT,
                            expected_bond_issue_version=_OMIT, **extra):
        body = _payload(
            bond_issue_id=bond_issue_id,
            draw_number=draw_number,
            period_start=period_start,
            period_end=period_end,
            requested_amount_cents=requested_amount_cents,
            expected_bond_issue_version=expected_bond_issue_version,
        )
        body.update(extra)
        return self._send_post("/draw-requests", body, headers=headers)

    def get_draw_request(self, draw_request_id, headers):
        return self._send_get(
            "/draw-requests/{0}".format(draw_request_id), headers=headers
        )

    def decide_draw_request(self, draw_request_id, headers, decision=_OMIT,
                            approved_amount_cents=_OMIT, rejection_reason=_OMIT, **extra):
        body = _payload(
            decision=decision,
            approved_amount_cents=approved_amount_cents,
            rejection_reason=rejection_reason,
        )
        body.update(extra)
        return self._send_post(
            "/draw-requests/{0}/decision".format(draw_request_id), body, headers=headers
        )

    def fund_draw_request(self, draw_request_id, headers, funding_date=_OMIT, **extra):
        body = _payload(funding_date=funding_date)
        body.update(extra)
        return self._send_post(
            "/draw-requests/{0}/fund".format(draw_request_id), body, headers=headers
        )

    def void_draw_request(self, draw_request_id, headers, void_reason=_OMIT, **extra):
        body = _payload(void_reason=void_reason)
        body.update(extra)
        return self._send_post(
            "/draw-requests/{0}/void".format(draw_request_id), body, headers=headers
        )

    def list_draw_requests(self, headers, bond_issue_id=_OMIT, status=_OMIT, limit=_OMIT,
                           offset=_OMIT, **extra):
        params = _payload(
            bond_issue_id=bond_issue_id, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/draw-requests", params, headers=headers)

    # ─── Cost certifications (PRD §3.8) ───────────────

    def create_cost_certification(self, headers, project_id=_OMIT,
                                  certified_land_cost_cents=_OMIT,
                                  certified_depreciable_basis_cents=_OMIT,
                                  certified_eligible_basis_cents=_OMIT,
                                  preparer_name=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            certified_land_cost_cents=certified_land_cost_cents,
            certified_depreciable_basis_cents=certified_depreciable_basis_cents,
            certified_eligible_basis_cents=certified_eligible_basis_cents,
            preparer_name=preparer_name,
        )
        body.update(extra)
        return self._send_post("/cost-certifications", body, headers=headers)

    def get_cost_certification(self, cost_certification_id, headers):
        return self._send_get(
            "/cost-certifications/{0}".format(cost_certification_id), headers=headers
        )

    def submit_cost_certification(self, cost_certification_id, headers,
                                  certified_land_cost_cents=_OMIT,
                                  certified_depreciable_basis_cents=_OMIT,
                                  certified_eligible_basis_cents=_OMIT, **extra):
        body = _payload(
            certified_land_cost_cents=certified_land_cost_cents,
            certified_depreciable_basis_cents=certified_depreciable_basis_cents,
            certified_eligible_basis_cents=certified_eligible_basis_cents,
        )
        body.update(extra)
        return self._send_post(
            "/cost-certifications/{0}/submit".format(cost_certification_id),
            body,
            headers=headers,
        )

    def review_cost_certification(self, cost_certification_id, headers, decision=_OMIT,
                                  deficiency_notes=_OMIT, **extra):
        body = _payload(decision=decision, deficiency_notes=deficiency_notes)
        body.update(extra)
        return self._send_post(
            "/cost-certifications/{0}/review".format(cost_certification_id),
            body,
            headers=headers,
        )

    def list_cost_certifications(self, headers, project_id=_OMIT, status=_OMIT,
                                 limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/cost-certifications", params, headers=headers)

    # ─── Final credit allocations (PRD §3.8) ──────────

    def create_credit_allocation(self, headers, project_id=_OMIT,
                                 cost_certification_id=_OMIT,
                                 credit_percentage_bps=_OMIT,
                                 placed_in_service_date=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            cost_certification_id=cost_certification_id,
            credit_percentage_bps=credit_percentage_bps,
            placed_in_service_date=placed_in_service_date,
        )
        body.update(extra)
        return self._send_post("/credit-allocations", body, headers=headers)

    def get_credit_allocation(self, credit_allocation_id, headers):
        """The read that supplies the expected allocation version for a delivery."""
        return self._send_get(
            "/credit-allocations/{0}".format(credit_allocation_id), headers=headers
        )

    def issue_credit_allocation(self, credit_allocation_id, headers,
                                form_8609_number=_OMIT, **extra):
        body = _payload(form_8609_number=form_8609_number)
        body.update(extra)
        return self._send_post(
            "/credit-allocations/{0}/issue".format(credit_allocation_id),
            body,
            headers=headers,
        )

    def list_credit_allocations(self, headers, project_id=_OMIT,
                                cost_certification_id=_OMIT, status=_OMIT, limit=_OMIT,
                                offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id,
            cost_certification_id=cost_certification_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/credit-allocations", params, headers=headers)

    # ─── Credit deliveries to investors (PRD §3.8) ────

    def create_investor_delivery(self, headers, credit_allocation_id=_OMIT,
                                 investor_id=_OMIT, requested_credit_cents=_OMIT,
                                 capital_contribution_cents=_OMIT,
                                 expected_credit_allocation_version=_OMIT, **extra):
        body = _payload(
            credit_allocation_id=credit_allocation_id,
            investor_id=investor_id,
            requested_credit_cents=requested_credit_cents,
            capital_contribution_cents=capital_contribution_cents,
            expected_credit_allocation_version=expected_credit_allocation_version,
        )
        body.update(extra)
        return self._send_post("/investor-deliveries", body, headers=headers)

    def get_investor_delivery(self, delivery_id, headers):
        return self._send_get(
            "/investor-deliveries/{0}".format(delivery_id), headers=headers
        )

    def accept_investor_delivery(self, delivery_id, headers, **extra):
        body = _payload(**extra)
        return self._send_post(
            "/investor-deliveries/{0}/accept".format(delivery_id), body, headers=headers
        )

    def rescind_investor_delivery(self, delivery_id, headers, rescind_reason=_OMIT,
                                  **extra):
        body = _payload(rescind_reason=rescind_reason)
        body.update(extra)
        return self._send_post(
            "/investor-deliveries/{0}/rescind".format(delivery_id), body, headers=headers
        )

    def list_investor_deliveries(self, headers, credit_allocation_id=_OMIT,
                                 investor_id=_OMIT, status=_OMIT, limit=_OMIT,
                                 offset=_OMIT, **extra):
        params = _payload(
            credit_allocation_id=credit_allocation_id,
            investor_id=investor_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/investor-deliveries", params, headers=headers)

    # ─── Annual compliance reports (PRD §3.9) ─────────

    def create_compliance_report(self, headers, project_id=_OMIT, reporting_year=_OMIT,
                                 restricted_units_occupied=_OMIT,
                                 total_units_occupied=_OMIT, average_ami_percent=_OMIT,
                                 **extra):
        body = _payload(
            project_id=project_id,
            reporting_year=reporting_year,
            restricted_units_occupied=restricted_units_occupied,
            total_units_occupied=total_units_occupied,
            average_ami_percent=average_ami_percent,
        )
        body.update(extra)
        return self._send_post("/compliance-reports", body, headers=headers)

    def get_compliance_report(self, report_id, headers):
        return self._send_get(
            "/compliance-reports/{0}".format(report_id), headers=headers
        )

    def review_compliance_report(self, report_id, headers, finding=_OMIT,
                                 finding_notes=_OMIT, **extra):
        body = _payload(finding=finding, finding_notes=finding_notes)
        body.update(extra)
        return self._send_post(
            "/compliance-reports/{0}/review".format(report_id), body, headers=headers
        )

    def list_compliance_reports(self, headers, project_id=_OMIT, reporting_year=_OMIT,
                                status=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id,
            reporting_year=reporting_year,
            status=status,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/compliance-reports", params, headers=headers)

    # ─── Physical inspections (PRD §3.9) ──────────────

    def create_physical_inspection(self, headers, project_id=_OMIT, window_start=_OMIT,
                                   window_end=_OMIT, inspector_name=_OMIT, **extra):
        body = _payload(
            project_id=project_id,
            window_start=window_start,
            window_end=window_end,
            inspector_name=inspector_name,
        )
        body.update(extra)
        return self._send_post("/physical-inspections", body, headers=headers)

    def get_physical_inspection(self, inspection_id, headers):
        return self._send_get(
            "/physical-inspections/{0}".format(inspection_id), headers=headers
        )

    def complete_physical_inspection(self, inspection_id, headers, completed_date=_OMIT,
                                     score=_OMIT, deficiency_count=_OMIT, **extra):
        body = _payload(
            completed_date=completed_date, score=score, deficiency_count=deficiency_count
        )
        body.update(extra)
        return self._send_post(
            "/physical-inspections/{0}/complete".format(inspection_id),
            body,
            headers=headers,
        )

    def list_physical_inspections(self, headers, project_id=_OMIT, status=_OMIT,
                                  limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            project_id=project_id, status=status, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/physical-inspections", params, headers=headers)

    # ─── Generic read helpers used by cross-entity probes ──

    def get_by_entity(self, entity, row_id, headers):
        """Fetch by entity name, for probes that walk all fourteen resources."""
        reader = getattr(self, "get_{0}".format(entity))
        return reader(row_id, headers)


api_client = ApiClient()
