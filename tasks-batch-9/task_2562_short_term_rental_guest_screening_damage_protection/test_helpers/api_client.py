"""A thin, typed wrapper over every operation the contract publishes (PRD §4).

One method per endpoint. Path parameters come first, body or query fields arrive
as keyword arguments, and ``headers`` is a mapping built by
``test_helpers.test_users``. A field the caller does not mention is left out of
the body entirely, so a test can distinguish "field absent" from "field
explicitly null" — several declared defaults depend on that distinction.
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
    """Domain-named client for the guest-screening and damage-protection API."""

    # ─── Transport helpers ────────────────────────────

    def _send_get(self, path, params=None, headers=None):
        """GET with query parameters, keeping headers and params distinct."""
        return self._request("GET", path, payload=params or None, headers=headers)

    def _send_post(self, path, body=None, headers=None):
        """POST with a JSON body, which may legitimately be empty."""
        return self._request("POST", path, payload=body if body is not None else {},
                             headers=headers)

    # ─── Logical clock (PRD §2.5) ─────────────────────

    def set_clock(self, current_utc, headers=None):
        """Move the logical clock to an explicit instant."""
        return self._send_post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    # ─── Guests (PRD §3.2) ────────────────────────────

    def create_guest(self, headers, full_name=_OMIT, email=_OMIT, country_code=_OMIT,
                     **extra):
        body = _payload(full_name=full_name, email=email, country_code=country_code)
        body.update(extra)
        return self._send_post("/rentals/guests", body, headers=headers)

    def get_guest(self, guest_id, headers):
        return self._send_get("/rentals/guests/{0}".format(guest_id), headers=headers)

    def list_guests(self, headers, risk_tier=_OMIT, verification_state=_OMIT,
                    limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            risk_tier=risk_tier,
            verification_state=verification_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/guests", params, headers=headers)

    def get_guest_risk_profile(self, guest_id, headers):
        return self._send_get(
            "/rentals/guests/{0}/risk-profile".format(guest_id), headers=headers
        )

    def record_payment_signal(self, guest_id, headers, payment_risk_signal=_OMIT,
                              chargeback_count=_OMIT, **extra):
        body = _payload(
            payment_risk_signal=payment_risk_signal, chargeback_count=chargeback_count
        )
        body.update(extra)
        return self._send_post(
            "/rentals/guests/{0}/payment-signals".format(guest_id), body, headers=headers
        )

    # ─── Hosts (PRD §3.2) ─────────────────────────────

    def create_host(self, headers, legal_name=_OMIT, email=_OMIT, **extra):
        body = _payload(legal_name=legal_name, email=email)
        body.update(extra)
        return self._send_post("/rentals/hosts", body, headers=headers)

    def get_host(self, host_id, headers):
        return self._send_get("/rentals/hosts/{0}".format(host_id), headers=headers)

    def list_hosts(self, headers, payout_hold=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(payout_hold=payout_hold, limit=limit, offset=offset)
        params.update(extra)
        return self._send_get("/rentals/hosts", params, headers=headers)

    # ─── Jurisdiction rule sets (PRD §3.1) ────────────

    def create_jurisdiction_rule(self, headers, jurisdiction_code=_OMIT,
                                 min_stay_nights=_OMIT, max_occupancy_cap=_OMIT,
                                 events_prohibited=_OMIT, registration_required=_OMIT,
                                 indoor_camera_allowed=_OMIT, indoor_audio_allowed=_OMIT,
                                 sensor_notice_required=_OMIT, noise_threshold_db=_OMIT,
                                 **extra):
        body = _payload(
            jurisdiction_code=jurisdiction_code,
            min_stay_nights=min_stay_nights,
            max_occupancy_cap=max_occupancy_cap,
            events_prohibited=events_prohibited,
            registration_required=registration_required,
            indoor_camera_allowed=indoor_camera_allowed,
            indoor_audio_allowed=indoor_audio_allowed,
            sensor_notice_required=sensor_notice_required,
            noise_threshold_db=noise_threshold_db,
        )
        body.update(extra)
        return self._send_post("/rentals/jurisdiction-rules", body, headers=headers)

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._send_get(
            "/rentals/jurisdiction-rules/{0}".format(rule_id), headers=headers
        )

    def list_jurisdiction_rules(self, headers, jurisdiction_code=_OMIT, limit=_OMIT,
                                offset=_OMIT, **extra):
        params = _payload(
            jurisdiction_code=jurisdiction_code, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/rentals/jurisdiction-rules", params, headers=headers)

    # ─── Listings (PRD §3.1) ──────────────────────────

    def create_property(self, headers, host_id=_OMIT, jurisdiction_rule_id=_OMIT,
                        address_line=_OMIT, city=_OMIT, registration_number=_OMIT,
                        max_occupancy=_OMIT, bedrooms=_OMIT, nightly_rate_cents=_OMIT,
                        protection_product=_OMIT, deposit_amount_cents=_OMIT,
                        waiver_nightly_fee_cents=_OMIT, claim_ceiling_cents=_OMIT,
                        event_policy=_OMIT, turnover_buffer_nights=_OMIT, **extra):
        body = _payload(
            host_id=host_id,
            jurisdiction_rule_id=jurisdiction_rule_id,
            address_line=address_line,
            city=city,
            registration_number=registration_number,
            max_occupancy=max_occupancy,
            bedrooms=bedrooms,
            nightly_rate_cents=nightly_rate_cents,
            protection_product=protection_product,
            deposit_amount_cents=deposit_amount_cents,
            waiver_nightly_fee_cents=waiver_nightly_fee_cents,
            claim_ceiling_cents=claim_ceiling_cents,
            event_policy=event_policy,
            turnover_buffer_nights=turnover_buffer_nights,
        )
        body.update(extra)
        return self._send_post("/rentals/properties", body, headers=headers)

    def get_property(self, property_id, headers):
        return self._send_get(
            "/rentals/properties/{0}".format(property_id), headers=headers
        )

    def list_properties(self, headers, host_id=_OMIT, jurisdiction_rule_id=_OMIT,
                        listing_state=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            host_id=host_id,
            jurisdiction_rule_id=jurisdiction_rule_id,
            listing_state=listing_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/properties", params, headers=headers)

    def activate_property(self, property_id, headers, **extra):
        return self._send_post(
            "/rentals/properties/{0}/activate".format(property_id),
            dict(extra),
            headers=headers,
        )

    def get_coverage_summary(self, property_id, headers):
        return self._send_get(
            "/rentals/properties/{0}/coverage-summary".format(property_id),
            headers=headers,
        )

    # ─── Monitoring devices (PRD §3.1) ────────────────

    def create_monitoring_device(self, headers, property_id=_OMIT, device_type=_OMIT,
                                 placement_zone=_OMIT, records_audio=_OMIT,
                                 guest_disclosure_text=_OMIT, **extra):
        body = _payload(
            property_id=property_id,
            device_type=device_type,
            placement_zone=placement_zone,
            records_audio=records_audio,
            guest_disclosure_text=guest_disclosure_text,
        )
        body.update(extra)
        return self._send_post("/rentals/monitoring-devices", body, headers=headers)

    def get_monitoring_device(self, device_id, headers):
        return self._send_get(
            "/rentals/monitoring-devices/{0}".format(device_id), headers=headers
        )

    def list_monitoring_devices(self, headers, property_id=_OMIT, disclosure_state=_OMIT,
                                limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            property_id=property_id,
            disclosure_state=disclosure_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/monitoring-devices", params, headers=headers)

    def submit_device_for_review(self, device_id, headers, guest_disclosure_text=_OMIT,
                                 **extra):
        body = _payload(guest_disclosure_text=guest_disclosure_text)
        body.update(extra)
        return self._send_post(
            "/rentals/monitoring-devices/{0}/submit-for-review".format(device_id),
            body,
            headers=headers,
        )

    def review_monitoring_device(self, device_id, headers, decision=_OMIT,
                                 reject_reason_code=_OMIT, **extra):
        body = _payload(decision=decision, reject_reason_code=reject_reason_code)
        body.update(extra)
        return self._send_post(
            "/rentals/monitoring-devices/{0}/review".format(device_id),
            body,
            headers=headers,
        )

    # ─── Identity documents (PRD §3.2) ────────────────

    def create_identity_document(self, headers, guest_id=_OMIT, doc_type=_OMIT,
                                 issuing_country=_OMIT, document_ref=_OMIT,
                                 expires_on=_OMIT, **extra):
        body = _payload(
            guest_id=guest_id,
            doc_type=doc_type,
            issuing_country=issuing_country,
            document_ref=document_ref,
            expires_on=expires_on,
        )
        body.update(extra)
        return self._send_post("/rentals/identity-documents", body, headers=headers)

    def get_identity_document(self, document_id, headers):
        return self._send_get(
            "/rentals/identity-documents/{0}".format(document_id), headers=headers
        )

    def list_identity_documents(self, headers, guest_id=_OMIT, review_state=_OMIT,
                                limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            guest_id=guest_id, review_state=review_state, limit=limit, offset=offset
        )
        params.update(extra)
        return self._send_get("/rentals/identity-documents", params, headers=headers)

    def review_identity_document(self, document_id, headers, decision=_OMIT,
                                 reject_reason_code=_OMIT, **extra):
        body = _payload(decision=decision, reject_reason_code=reject_reason_code)
        body.update(extra)
        return self._send_post(
            "/rentals/identity-documents/{0}/review".format(document_id),
            body,
            headers=headers,
        )

    # ─── Reservations (PRD §3.3, §3.4) ────────────────

    def create_reservation(self, headers, guest_id=_OMIT, property_id=_OMIT,
                           check_in=_OMIT, check_out=_OMIT, guest_count=_OMIT,
                           event_declared=_OMIT, expected_property_version=_OMIT, **extra):
        body = _payload(
            guest_id=guest_id,
            property_id=property_id,
            check_in=check_in,
            check_out=check_out,
            guest_count=guest_count,
            event_declared=event_declared,
            expected_property_version=expected_property_version,
        )
        body.update(extra)
        return self._send_post("/rentals/reservations", body, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._send_get(
            "/rentals/reservations/{0}".format(reservation_id), headers=headers
        )

    def list_reservations(self, headers, guest_id=_OMIT, property_id=_OMIT,
                          stay_state=_OMIT, screening_state=_OMIT, deposit_state=_OMIT,
                          limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            guest_id=guest_id,
            property_id=property_id,
            stay_state=stay_state,
            screening_state=screening_state,
            deposit_state=deposit_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/reservations", params, headers=headers)

    def get_charge_breakdown(self, reservation_id, headers):
        return self._send_get(
            "/rentals/reservations/{0}/charge-breakdown".format(reservation_id),
            headers=headers,
        )

    def decide_screening(self, reservation_id, headers, decision=_OMIT, note=_OMIT,
                         **extra):
        body = _payload(decision=decision, note=note)
        body.update(extra)
        return self._send_post(
            "/rentals/reservations/{0}/screening-decision".format(reservation_id),
            body,
            headers=headers,
        )

    def confirm_reservation(self, reservation_id, headers, **extra):
        return self._send_post(
            "/rentals/reservations/{0}/confirm".format(reservation_id),
            dict(extra),
            headers=headers,
        )

    def check_in_reservation(self, reservation_id, headers, **extra):
        return self._send_post(
            "/rentals/reservations/{0}/check-in".format(reservation_id),
            dict(extra),
            headers=headers,
        )

    def complete_reservation(self, reservation_id, headers, **extra):
        return self._send_post(
            "/rentals/reservations/{0}/complete".format(reservation_id),
            dict(extra),
            headers=headers,
        )

    def cancel_reservation(self, reservation_id, headers, **extra):
        return self._send_post(
            "/rentals/reservations/{0}/cancel".format(reservation_id),
            dict(extra),
            headers=headers,
        )

    # ─── Incidents (PRD §3.5) ─────────────────────────

    def create_incident(self, headers, reservation_id=_OMIT, sensor_device_id=_OMIT,
                        incident_type=_OMIT, severity=_OMIT, source=_OMIT,
                        detected_at=_OMIT, description=_OMIT, decibel_reading=_OMIT,
                        observed_occupancy=_OMIT, complainant_ref=_OMIT, **extra):
        body = _payload(
            reservation_id=reservation_id,
            sensor_device_id=sensor_device_id,
            incident_type=incident_type,
            severity=severity,
            source=source,
            detected_at=detected_at,
            description=description,
            decibel_reading=decibel_reading,
            observed_occupancy=observed_occupancy,
            complainant_ref=complainant_ref,
        )
        body.update(extra)
        return self._send_post("/rentals/incidents", body, headers=headers)

    def get_incident(self, incident_id, headers):
        return self._send_get(
            "/rentals/incidents/{0}".format(incident_id), headers=headers
        )

    def list_incidents(self, headers, reservation_id=_OMIT, sensor_device_id=_OMIT,
                       incident_state=_OMIT, source=_OMIT, limit=_OMIT, offset=_OMIT,
                       **extra):
        params = _payload(
            reservation_id=reservation_id,
            sensor_device_id=sensor_device_id,
            incident_state=incident_state,
            source=source,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/incidents", params, headers=headers)

    def acknowledge_incident(self, incident_id, headers, **extra):
        return self._send_post(
            "/rentals/incidents/{0}/acknowledge".format(incident_id),
            dict(extra),
            headers=headers,
        )

    def dismiss_incident(self, incident_id, headers, dismiss_reason_code=_OMIT, **extra):
        body = _payload(dismiss_reason_code=dismiss_reason_code)
        body.update(extra)
        return self._send_post(
            "/rentals/incidents/{0}/dismiss".format(incident_id), body, headers=headers
        )

    def escalate_incident(self, incident_id, headers, law_enforcement_ref=_OMIT, **extra):
        body = _payload(law_enforcement_ref=law_enforcement_ref)
        body.update(extra)
        return self._send_post(
            "/rentals/incidents/{0}/escalate".format(incident_id), body, headers=headers
        )

    def close_incident(self, incident_id, headers, **extra):
        return self._send_post(
            "/rentals/incidents/{0}/close".format(incident_id),
            dict(extra),
            headers=headers,
        )

    # ─── Damage claims (PRD §3.6, §3.8) ───────────────

    def create_damage_claim(self, headers, reservation_id=_OMIT, incident_id=_OMIT,
                            claimed_amount_cents=_OMIT, description=_OMIT,
                            expected_reservation_version=_OMIT, **extra):
        body = _payload(
            reservation_id=reservation_id,
            incident_id=incident_id,
            claimed_amount_cents=claimed_amount_cents,
            description=description,
            expected_reservation_version=expected_reservation_version,
        )
        body.update(extra)
        return self._send_post("/rentals/damage-claims", body, headers=headers)

    def get_damage_claim(self, claim_id, headers):
        return self._send_get(
            "/rentals/damage-claims/{0}".format(claim_id), headers=headers
        )

    def list_damage_claims(self, headers, reservation_id=_OMIT, incident_id=_OMIT,
                           host_id=_OMIT, claim_state=_OMIT, limit=_OMIT, offset=_OMIT,
                           **extra):
        params = _payload(
            reservation_id=reservation_id,
            incident_id=incident_id,
            host_id=host_id,
            claim_state=claim_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/damage-claims", params, headers=headers)

    def get_settlement_summary(self, claim_id, headers):
        return self._send_get(
            "/rentals/damage-claims/{0}/settlement-summary".format(claim_id),
            headers=headers,
        )

    def submit_claim_for_review(self, claim_id, headers, **extra):
        return self._send_post(
            "/rentals/damage-claims/{0}/submit-for-review".format(claim_id),
            dict(extra),
            headers=headers,
        )

    def request_claim_evidence(self, claim_id, headers, note=_OMIT, **extra):
        body = _payload(note=note)
        body.update(extra)
        return self._send_post(
            "/rentals/damage-claims/{0}/request-evidence".format(claim_id),
            body,
            headers=headers,
        )

    def decide_damage_claim(self, claim_id, headers, decision=_OMIT,
                            decision_reason_code=_OMIT, approved_amount_cents=_OMIT,
                            **extra):
        body = _payload(
            decision=decision,
            decision_reason_code=decision_reason_code,
            approved_amount_cents=approved_amount_cents,
        )
        body.update(extra)
        return self._send_post(
            "/rentals/damage-claims/{0}/decide".format(claim_id), body, headers=headers
        )

    def appeal_damage_claim(self, claim_id, headers, note=_OMIT, **extra):
        body = _payload(note=note)
        body.update(extra)
        return self._send_post(
            "/rentals/damage-claims/{0}/appeal".format(claim_id), body, headers=headers
        )

    def decide_appeal(self, claim_id, headers, decision=_OMIT,
                      decision_reason_code=_OMIT, approved_amount_cents=_OMIT, **extra):
        body = _payload(
            decision=decision,
            decision_reason_code=decision_reason_code,
            approved_amount_cents=approved_amount_cents,
        )
        body.update(extra)
        return self._send_post(
            "/rentals/damage-claims/{0}/appeal-decision".format(claim_id),
            body,
            headers=headers,
        )

    # ─── Claim evidence (PRD §3.6) ────────────────────

    def create_claim_evidence(self, headers, claim_id=_OMIT, evidence_type=_OMIT,
                              amount_cents=_OMIT, captured_at=_OMIT, file_ref=_OMIT,
                              **extra):
        body = _payload(
            claim_id=claim_id,
            evidence_type=evidence_type,
            amount_cents=amount_cents,
            captured_at=captured_at,
            file_ref=file_ref,
        )
        body.update(extra)
        return self._send_post("/rentals/claim-evidence", body, headers=headers)

    def get_claim_evidence(self, evidence_id, headers):
        return self._send_get(
            "/rentals/claim-evidence/{0}".format(evidence_id), headers=headers
        )

    def list_claim_evidence(self, headers, claim_id=_OMIT, evidence_type=_OMIT,
                            evidence_round=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            claim_id=claim_id,
            evidence_type=evidence_type,
            evidence_round=evidence_round,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/claim-evidence", params, headers=headers)

    # ─── Coverage layers (PRD §3.1) ───────────────────

    def create_coverage_layer(self, headers, source=_OMIT, layer_order=_OMIT,
                              limit_cents=_OMIT, deductible_cents=_OMIT,
                              coverage_pct=_OMIT, scope=_OMIT, property_id=_OMIT,
                              **extra):
        body = _payload(
            source=source,
            layer_order=layer_order,
            limit_cents=limit_cents,
            deductible_cents=deductible_cents,
            coverage_pct=coverage_pct,
            scope=scope,
            property_id=property_id,
        )
        body.update(extra)
        return self._send_post("/rentals/coverage-layers", body, headers=headers)

    def get_coverage_layer(self, layer_id, headers):
        return self._send_get(
            "/rentals/coverage-layers/{0}".format(layer_id), headers=headers
        )

    def list_coverage_layers(self, headers, property_id=_OMIT, scope=_OMIT, source=_OMIT,
                             layer_state=_OMIT, limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            property_id=property_id,
            scope=scope,
            source=source,
            layer_state=layer_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/coverage-layers", params, headers=headers)

    # ─── Settlement allocations (PRD §3.7) ────────────

    def get_settlement_allocation(self, allocation_id, headers):
        return self._send_get(
            "/rentals/settlement-allocations/{0}".format(allocation_id), headers=headers
        )

    def list_settlement_allocations(self, headers, claim_id=_OMIT,
                                    coverage_layer_id=_OMIT, voided=_OMIT, limit=_OMIT,
                                    offset=_OMIT, **extra):
        params = _payload(
            claim_id=claim_id,
            coverage_layer_id=coverage_layer_id,
            voided=voided,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/settlement-allocations", params, headers=headers)

    # ─── Blocklist entries (PRD §3.9) ─────────────────

    def create_blocklist_entry(self, headers, guest_id=_OMIT, scope=_OMIT,
                               property_id=_OMIT, host_id=_OMIT,
                               supersedes_entry_id=_OMIT, reason_code=_OMIT,
                               expected_guest_version=_OMIT, **extra):
        body = _payload(
            guest_id=guest_id,
            scope=scope,
            property_id=property_id,
            host_id=host_id,
            supersedes_entry_id=supersedes_entry_id,
            reason_code=reason_code,
            expected_guest_version=expected_guest_version,
        )
        body.update(extra)
        return self._send_post("/rentals/blocklist-entries", body, headers=headers)

    def get_blocklist_entry(self, entry_id, headers):
        return self._send_get(
            "/rentals/blocklist-entries/{0}".format(entry_id), headers=headers
        )

    def list_blocklist_entries(self, headers, guest_id=_OMIT, property_id=_OMIT,
                               host_id=_OMIT, supersedes_entry_id=_OMIT, scope=_OMIT,
                               entry_state=_OMIT, dispute_window_state=_OMIT,
                               limit=_OMIT, offset=_OMIT, **extra):
        params = _payload(
            guest_id=guest_id,
            property_id=property_id,
            host_id=host_id,
            supersedes_entry_id=supersedes_entry_id,
            scope=scope,
            entry_state=entry_state,
            dispute_window_state=dispute_window_state,
            limit=limit,
            offset=offset,
        )
        params.update(extra)
        return self._send_get("/rentals/blocklist-entries", params, headers=headers)

    def dispute_blocklist_entry(self, entry_id, headers, dispute_statement_code=_OMIT,
                                **extra):
        body = _payload(dispute_statement_code=dispute_statement_code)
        body.update(extra)
        return self._send_post(
            "/rentals/blocklist-entries/{0}/dispute".format(entry_id),
            body,
            headers=headers,
        )

    def decide_blocklist_dispute(self, entry_id, headers, dispute_reason_code=_OMIT,
                                 **extra):
        body = _payload(dispute_reason_code=dispute_reason_code)
        body.update(extra)
        return self._send_post(
            "/rentals/blocklist-entries/{0}/dispute-decision".format(entry_id),
            body,
            headers=headers,
        )

    def lift_blocklist_entry(self, entry_id, headers, **extra):
        return self._send_post(
            "/rentals/blocklist-entries/{0}/lift".format(entry_id),
            dict(extra),
            headers=headers,
        )

    # ─── Epoch sweep (PRD §3.10) ──────────────────────

    def run_adjudication_sweep(self, headers, **extra):
        return self._send_post(
            "/rentals/ops/adjudication-sweep", dict(extra), headers=headers
        )


# A module-level instance is convenient for fixtures that do not take the
# ``api`` pytest fixture; every test body uses the fixture instead.
api_client = ApiClient()
