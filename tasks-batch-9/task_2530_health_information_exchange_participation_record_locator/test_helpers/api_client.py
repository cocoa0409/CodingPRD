"""Typed client for every operation in the PRD endpoint table.

One method per row of the endpoint table (28 writes, 30 reads). Every method
returns the raw ``requests.Response`` so a test can hand it to
``validate_success`` / ``validate_error`` / ``validate_paginated`` and assert on
the HTTP status itself.

Conventions used throughout:

* ``headers`` is always the first positional argument and is expected to come
  from one of the builders in ``test_helpers.test_users``.
* Optional request fields default to ``_OMIT``; a field left at ``_OMIT`` is not
  transmitted at all, which is distinct from transmitting it as ``null``. Pass
  ``None`` explicitly when a test needs an explicit JSON null.
* ``**extra`` on the write methods lets a test add unknown or malformed fields
  without a bespoke helper.
* List reads accept ``limit`` / ``offset`` plus their declared filters, and
  additionally ``**extra_params`` so out-of-range or unknown query values can be
  probed.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_OMIT = object()


def _body(fields: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Drop omitted fields, keep explicit nulls, then merge test-supplied extras."""
    payload = {key: value for key, value in fields.items() if value is not _OMIT}
    if extra:
        payload.update(extra)
    return payload


def _params(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not _OMIT}


class ApiClient(GenericApiClient):
    """Health Information Exchange record locator API client."""

    # ------------------------------------------------------------------
    # Escape hatches for malformed-request probes
    # ------------------------------------------------------------------

    def post_raw(self, path: str, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", path, payload=payload, headers=headers)

    def get_raw(self, path: str, headers: Optional[Dict[str, str]] = None, params: Any = None):
        return self._request("GET", path, headers=headers, params=params)

    # ==================================================================
    # Participant onboarding
    # ==================================================================

    def register_participant(
        self,
        headers,
        legal_name=_OMIT,
        org_type=_OMIT,
        declared_annual_patient_volume=_OMIT,
        primary_contact_email=_OMIT,
        **extra,
    ):
        """POST /hie/participants -> 201."""
        return self._request(
            "POST",
            "/hie/participants",
            payload=_body(
                {
                    "legal_name": legal_name,
                    "org_type": org_type,
                    "declared_annual_patient_volume": declared_annual_patient_volume,
                    "primary_contact_email": primary_contact_email,
                },
                extra,
            ),
            headers=headers,
        )

    def transition_onboarding(
        self,
        headers,
        participant_id,
        action=_OMIT,
        agreement_version=_OMIT,
        signed_at=_OMIT,
        reason=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/onboarding-transitions -> 200."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/onboarding-transitions",
            payload=_body(
                {
                    "action": action,
                    "agreement_version": agreement_version,
                    "signed_at": signed_at,
                    "reason": reason,
                },
                extra,
            ),
            headers=headers,
        )

    def schedule_conformance_test(
        self,
        headers,
        participant_id,
        profile=_OMIT,
        scheduled_start=_OMIT,
        scheduled_end=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/conformance-tests -> 201."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/conformance-tests",
            payload=_body(
                {
                    "profile": profile,
                    "scheduled_start": scheduled_start,
                    "scheduled_end": scheduled_end,
                },
                extra,
            ),
            headers=headers,
        )

    def submit_conformance_result(
        self,
        headers,
        conformance_test_id,
        assertions_total=_OMIT,
        assertions_passed=_OMIT,
        failure_categories=_OMIT,
        **extra,
    ):
        """POST /hie/conformance-tests/{id}/results -> 200."""
        return self._request(
            "POST",
            f"/hie/conformance-tests/{conformance_test_id}/results",
            payload=_body(
                {
                    "assertions_total": assertions_total,
                    "assertions_passed": assertions_passed,
                    "failure_categories": failure_categories,
                },
                extra,
            ),
            headers=headers,
        )

    def waive_conformance_test(self, headers, conformance_test_id, waiver_reason=_OMIT, **extra):
        """POST /hie/conformance-tests/{id}/waiver -> 200."""
        return self._request(
            "POST",
            f"/hie/conformance-tests/{conformance_test_id}/waiver",
            payload=_body({"waiver_reason": waiver_reason}, extra),
            headers=headers,
        )

    # ==================================================================
    # Statewide governance generations
    # ==================================================================

    def draft_consent_policy(
        self,
        headers,
        policy_version=_OMIT,
        model=_OMIT,
        sensitive_categories_segmented=_OMIT,
        default_share_for_treatment=_OMIT,
        effective_from=_OMIT,
        effective_until=_OMIT,
        **extra,
    ):
        """POST /hie/consent-policies -> 201."""
        return self._request(
            "POST",
            "/hie/consent-policies",
            payload=_body(
                {
                    "policy_version": policy_version,
                    "model": model,
                    "sensitive_categories_segmented": sensitive_categories_segmented,
                    "default_share_for_treatment": default_share_for_treatment,
                    "effective_from": effective_from,
                    "effective_until": effective_until,
                },
                extra,
            ),
            headers=headers,
        )

    def activate_consent_policy(self, headers, consent_policy_id, **extra):
        """POST /hie/consent-policies/{id}/activation -> 200."""
        return self._request(
            "POST",
            f"/hie/consent-policies/{consent_policy_id}/activation",
            payload=_body({}, extra),
            headers=headers,
        )

    def draft_match_threshold_config(
        self,
        headers,
        config_label=_OMIT,
        auto_link_threshold=_OMIT,
        review_lower_bound=_OMIT,
        score_variant_mode=_OMIT,
        weight_family_name=_OMIT,
        weight_given_name=_OMIT,
        weight_birth_date=_OMIT,
        weight_ssn_last4=_OMIT,
        weight_postal_code=_OMIT,
        weight_phone_digits=_OMIT,
        partial_credit_factor=_OMIT,
        **extra,
    ):
        """POST /hie/match-threshold-configs -> 201."""
        return self._request(
            "POST",
            "/hie/match-threshold-configs",
            payload=_body(
                {
                    "config_label": config_label,
                    "auto_link_threshold": auto_link_threshold,
                    "review_lower_bound": review_lower_bound,
                    "score_variant_mode": score_variant_mode,
                    "weight_family_name": weight_family_name,
                    "weight_given_name": weight_given_name,
                    "weight_birth_date": weight_birth_date,
                    "weight_ssn_last4": weight_ssn_last4,
                    "weight_postal_code": weight_postal_code,
                    "weight_phone_digits": weight_phone_digits,
                    "partial_credit_factor": partial_credit_factor,
                },
                extra,
            ),
            headers=headers,
        )

    def activate_match_threshold_config(self, headers, threshold_config_id, **extra):
        """POST /hie/match-threshold-configs/{id}/activation -> 200."""
        return self._request(
            "POST",
            f"/hie/match-threshold-configs/{threshold_config_id}/activation",
            payload=_body({}, extra),
            headers=headers,
        )

    # ==================================================================
    # Patient records, identity resolution and stewardship
    # ==================================================================

    def contribute_patient_record(
        self,
        headers,
        participant_id,
        source_mrn=_OMIT,
        given_name=_OMIT,
        family_name=_OMIT,
        birth_date=_OMIT,
        sex=_OMIT,
        ssn_last4=_OMIT,
        postal_code=_OMIT,
        phone_digits=_OMIT,
        sensitive_categories=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/patient-records -> 201."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/patient-records",
            payload=_body(
                {
                    "source_mrn": source_mrn,
                    "given_name": given_name,
                    "family_name": family_name,
                    "birth_date": birth_date,
                    "sex": sex,
                    "ssn_last4": ssn_last4,
                    "postal_code": postal_code,
                    "phone_digits": phone_digits,
                    "sensitive_categories": sensitive_categories,
                },
                extra,
            ),
            headers=headers,
        )

    def record_steward_decision(
        self,
        headers,
        match_link_id,
        decision=_OMIT,
        expected_cluster_version=_OMIT,
        review_note=_OMIT,
        **extra,
    ):
        """POST /hie/match-links/{id}/steward-decision -> 200."""
        return self._request(
            "POST",
            f"/hie/match-links/{match_link_id}/steward-decision",
            payload=_body(
                {
                    "decision": decision,
                    "expected_cluster_version": expected_cluster_version,
                    "review_note": review_note,
                },
                extra,
            ),
            headers=headers,
        )

    def unlink_match_link(
        self,
        headers,
        match_link_id,
        expected_cluster_version=_OMIT,
        unlink_reason=_OMIT,
        **extra,
    ):
        """POST /hie/match-links/{id}/unlink -> 200."""
        return self._request(
            "POST",
            f"/hie/match-links/{match_link_id}/unlink",
            payload=_body(
                {
                    "expected_cluster_version": expected_cluster_version,
                    "unlink_reason": unlink_reason,
                },
                extra,
            ),
            headers=headers,
        )

    # ==================================================================
    # Consent directives
    # ==================================================================

    def record_consent_directive(
        self,
        headers,
        cluster_id,
        directive_type=_OMIT,
        scope=_OMIT,
        expected_cluster_version=_OMIT,
        restricted_categories=_OMIT,
        scoped_participant_id=_OMIT,
        effective_from=_OMIT,
        **extra,
    ):
        """POST /hie/identity-clusters/{id}/consent-directives -> 201."""
        return self._request(
            "POST",
            f"/hie/identity-clusters/{cluster_id}/consent-directives",
            payload=_body(
                {
                    "directive_type": directive_type,
                    "scope": scope,
                    "expected_cluster_version": expected_cluster_version,
                    "restricted_categories": restricted_categories,
                    "scoped_participant_id": scoped_participant_id,
                    "effective_from": effective_from,
                },
                extra,
            ),
            headers=headers,
        )

    def revoke_consent_directive(self, headers, directive_id, revocation_reason=_OMIT, **extra):
        """POST /hie/consent-directives/{id}/revocation -> 200."""
        return self._request(
            "POST",
            f"/hie/consent-directives/{directive_id}/revocation",
            payload=_body({"revocation_reason": revocation_reason}, extra),
            headers=headers,
        )

    # ==================================================================
    # Record locator queries
    # ==================================================================

    def submit_record_locator_query(
        self,
        headers,
        querying_participant_id=_OMIT,
        purpose_of_use=_OMIT,
        family_name=_OMIT,
        given_name=_OMIT,
        birth_date=_OMIT,
        sex=_OMIT,
        ssn_last4=_OMIT,
        postal_code=_OMIT,
        phone_digits=_OMIT,
        break_glass_id=_OMIT,
        **extra,
    ):
        """POST /hie/record-locator-queries -> 201."""
        return self._request(
            "POST",
            "/hie/record-locator-queries",
            payload=_body(
                {
                    "querying_participant_id": querying_participant_id,
                    "purpose_of_use": purpose_of_use,
                    "family_name": family_name,
                    "given_name": given_name,
                    "birth_date": birth_date,
                    "sex": sex,
                    "ssn_last4": ssn_last4,
                    "postal_code": postal_code,
                    "phone_digits": phone_digits,
                    "break_glass_id": break_glass_id,
                },
                extra,
            ),
            headers=headers,
        )

    # ==================================================================
    # Break-the-glass emergency access and post-hoc review
    # ==================================================================

    def open_break_glass_access(
        self,
        headers,
        cluster_id=_OMIT,
        invoking_participant_id=_OMIT,
        emergency_category=_OMIT,
        justification_text=_OMIT,
        **extra,
    ):
        """POST /hie/break-glass-accesses -> 201."""
        return self._request(
            "POST",
            "/hie/break-glass-accesses",
            payload=_body(
                {
                    "cluster_id": cluster_id,
                    "invoking_participant_id": invoking_participant_id,
                    "emergency_category": emergency_category,
                    "justification_text": justification_text,
                },
                extra,
            ),
            headers=headers,
        )

    def close_break_glass_access(self, headers, break_glass_id, **extra):
        """POST /hie/break-glass-accesses/{id}/closure -> 200."""
        return self._request(
            "POST",
            f"/hie/break-glass-accesses/{break_glass_id}/closure",
            payload=_body({}, extra),
            headers=headers,
        )

    def claim_break_glass_review(self, headers, break_glass_id, **extra):
        """POST /hie/break-glass-accesses/{id}/review-claim -> 200."""
        return self._request(
            "POST",
            f"/hie/break-glass-accesses/{break_glass_id}/review-claim",
            payload=_body({}, extra),
            headers=headers,
        )

    def decide_break_glass_review(
        self, headers, break_glass_id, outcome=_OMIT, review_note=_OMIT, **extra
    ):
        """POST /hie/break-glass-accesses/{id}/review-decision -> 200."""
        return self._request(
            "POST",
            f"/hie/break-glass-accesses/{break_glass_id}/review-decision",
            payload=_body({"outcome": outcome, "review_note": review_note}, extra),
            headers=headers,
        )

    # ==================================================================
    # Data feeds and quality sampling
    # ==================================================================

    def provision_data_feed(
        self,
        headers,
        participant_id,
        feed_type=_OMIT,
        expected_participant_version=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/data-feeds -> 201."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/data-feeds",
            payload=_body(
                {
                    "feed_type": feed_type,
                    "expected_participant_version": expected_participant_version,
                },
                extra,
            ),
            headers=headers,
        )

    def record_quality_sample(
        self,
        headers,
        data_feed_id,
        period_start=_OMIT,
        period_end=_OMIT,
        messages_received=_OMIT,
        messages_rejected=_OMIT,
        required_fields_missing_count=_OMIT,
        duplicate_count=_OMIT,
        timeliness_p95_seconds=_OMIT,
        **extra,
    ):
        """POST /hie/data-feeds/{id}/quality-samples -> 201."""
        return self._request(
            "POST",
            f"/hie/data-feeds/{data_feed_id}/quality-samples",
            payload=_body(
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "messages_received": messages_received,
                    "messages_rejected": messages_rejected,
                    "required_fields_missing_count": required_fields_missing_count,
                    "duplicate_count": duplicate_count,
                    "timeliness_p95_seconds": timeliness_p95_seconds,
                },
                extra,
            ),
            headers=headers,
        )

    def transition_data_feed_status(self, headers, data_feed_id, action=_OMIT, reason=_OMIT, **extra):
        """POST /hie/data-feeds/{id}/status-transitions -> 200."""
        return self._request(
            "POST",
            f"/hie/data-feeds/{data_feed_id}/status-transitions",
            payload=_body({"action": action, "reason": reason}, extra),
            headers=headers,
        )

    # ==================================================================
    # Notification subscriptions
    # ==================================================================

    def create_notification_subscription(
        self,
        headers,
        participant_id,
        subscription_scope=_OMIT,
        event_types=_OMIT,
        delivery_endpoint_url=_OMIT,
        cluster_id=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/notification-subscriptions -> 201."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/notification-subscriptions",
            payload=_body(
                {
                    "subscription_scope": subscription_scope,
                    "event_types": event_types,
                    "delivery_endpoint_url": delivery_endpoint_url,
                    "cluster_id": cluster_id,
                },
                extra,
            ),
            headers=headers,
        )

    def transition_subscription_lifecycle(
        self, headers, subscription_id, action=_OMIT, reason=_OMIT, **extra
    ):
        """POST /hie/notification-subscriptions/{id}/lifecycle-transitions -> 200."""
        return self._request(
            "POST",
            f"/hie/notification-subscriptions/{subscription_id}/lifecycle-transitions",
            payload=_body({"action": action, "reason": reason}, extra),
            headers=headers,
        )

    # ==================================================================
    # Participation invoicing
    # ==================================================================

    def issue_participation_invoice(
        self,
        headers,
        participant_id,
        billing_period_start=_OMIT,
        billing_period_end=_OMIT,
        basis_variant=_OMIT,
        due_date=_OMIT,
        **extra,
    ):
        """POST /hie/participants/{id}/participation-invoices -> 201."""
        return self._request(
            "POST",
            f"/hie/participants/{participant_id}/participation-invoices",
            payload=_body(
                {
                    "billing_period_start": billing_period_start,
                    "billing_period_end": billing_period_end,
                    "basis_variant": basis_variant,
                    "due_date": due_date,
                },
                extra,
            ),
            headers=headers,
        )

    def pay_participation_invoice(self, headers, invoice_id, amount_paid_cents=_OMIT, **extra):
        """POST /hie/participation-invoices/{id}/payment -> 200."""
        return self._request(
            "POST",
            f"/hie/participation-invoices/{invoice_id}/payment",
            payload=_body({"amount_paid_cents": amount_paid_cents}, extra),
            headers=headers,
        )

    def administer_participation_invoice(
        self, headers, invoice_id, action=_OMIT, reason=_OMIT, **extra
    ):
        """POST /hie/participation-invoices/{id}/administrative-transitions -> 200."""
        return self._request(
            "POST",
            f"/hie/participation-invoices/{invoice_id}/administrative-transitions",
            payload=_body({"action": action, "reason": reason}, extra),
            headers=headers,
        )

    # ==================================================================
    # Logical clock
    # ==================================================================

    def set_logical_clock(self, headers, to_iso8601=_OMIT, **extra):
        """POST /hie/_clock/set_current_utc -> 200."""
        return self._request(
            "POST",
            "/hie/_clock/set_current_utc",
            payload=_body({"to_iso8601": to_iso8601}, extra),
            headers=headers,
        )

    # ==================================================================
    # Reads: participants
    # ==================================================================

    def get_participant(self, headers, participant_id):
        """GET /hie/participants/{id} -> 200."""
        return self._request("GET", f"/hie/participants/{participant_id}", headers=headers)

    def list_participants(
        self,
        headers,
        onboarding_status=_OMIT,
        org_type=_OMIT,
        fee_tier=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/participants -> 200 (paginated)."""
        params = _params(
            {
                "onboarding_status": onboarding_status,
                "org_type": org_type,
                "fee_tier": fee_tier,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/participants", headers=headers, params=params)

    def get_participant_scorecard(self, headers, participant_id):
        """GET /hie/participants/{id}/scorecard -> 200."""
        return self._request(
            "GET", f"/hie/participants/{participant_id}/scorecard", headers=headers
        )

    def list_participant_conformance_tests(
        self, headers, participant_id, profile=_OMIT, status=_OMIT, limit=_OMIT, offset=_OMIT, **extra_params
    ):
        """GET /hie/participants/{id}/conformance-tests -> 200 (paginated)."""
        params = _params(
            {"profile": profile, "status": status, "limit": limit, "offset": offset}
        )
        params.update(extra_params)
        return self._request(
            "GET",
            f"/hie/participants/{participant_id}/conformance-tests",
            headers=headers,
            params=params,
        )

    def get_conformance_test(self, headers, conformance_test_id):
        """GET /hie/conformance-tests/{id} -> 200."""
        return self._request(
            "GET", f"/hie/conformance-tests/{conformance_test_id}", headers=headers
        )

    # ==================================================================
    # Reads: governance generations
    # ==================================================================

    def get_consent_policy(self, headers, consent_policy_id):
        """GET /hie/consent-policies/{id} -> 200."""
        return self._request("GET", f"/hie/consent-policies/{consent_policy_id}", headers=headers)

    def list_consent_policies(
        self, headers, status=_OMIT, model=_OMIT, limit=_OMIT, offset=_OMIT, **extra_params
    ):
        """GET /hie/consent-policies -> 200 (paginated)."""
        params = _params({"status": status, "model": model, "limit": limit, "offset": offset})
        params.update(extra_params)
        return self._request("GET", "/hie/consent-policies", headers=headers, params=params)

    def get_match_threshold_config(self, headers, threshold_config_id):
        """GET /hie/match-threshold-configs/{id} -> 200."""
        return self._request(
            "GET", f"/hie/match-threshold-configs/{threshold_config_id}", headers=headers
        )

    def list_match_threshold_configs(
        self,
        headers,
        status=_OMIT,
        score_variant_mode=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/match-threshold-configs -> 200 (paginated)."""
        params = _params(
            {
                "status": status,
                "score_variant_mode": score_variant_mode,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/match-threshold-configs", headers=headers, params=params)

    # ==================================================================
    # Reads: records, clusters, links
    # ==================================================================

    def get_patient_record(self, headers, record_id):
        """GET /hie/patient-records/{id} -> 200."""
        return self._request("GET", f"/hie/patient-records/{record_id}", headers=headers)

    def list_patient_records(
        self,
        headers,
        participant_id=_OMIT,
        cluster_id=_OMIT,
        prior_cluster_id=_OMIT,
        match_state=_OMIT,
        source_mrn=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/patient-records -> 200 (paginated)."""
        params = _params(
            {
                "participant_id": participant_id,
                "cluster_id": cluster_id,
                "prior_cluster_id": prior_cluster_id,
                "match_state": match_state,
                "source_mrn": source_mrn,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/patient-records", headers=headers, params=params)

    def get_identity_cluster(self, headers, cluster_id):
        """GET /hie/identity-clusters/{id} -> 200."""
        return self._request("GET", f"/hie/identity-clusters/{cluster_id}", headers=headers)

    def list_identity_clusters(
        self,
        headers,
        primary_record_id=_OMIT,
        merged_into_cluster_id=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/identity-clusters -> 200 (paginated)."""
        params = _params(
            {
                "primary_record_id": primary_record_id,
                "merged_into_cluster_id": merged_into_cluster_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/identity-clusters", headers=headers, params=params)

    def get_match_link(self, headers, match_link_id):
        """GET /hie/match-links/{id} -> 200."""
        return self._request("GET", f"/hie/match-links/{match_link_id}", headers=headers)

    def list_match_links(
        self,
        headers,
        left_record_id=_OMIT,
        right_record_id=_OMIT,
        threshold_config_id=_OMIT,
        cluster_id=_OMIT,
        merged_away_cluster_id=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/match-links -> 200 (paginated)."""
        params = _params(
            {
                "left_record_id": left_record_id,
                "right_record_id": right_record_id,
                "threshold_config_id": threshold_config_id,
                "cluster_id": cluster_id,
                "merged_away_cluster_id": merged_away_cluster_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/match-links", headers=headers, params=params)

    # ==================================================================
    # Reads: consent directives
    # ==================================================================

    def get_consent_directive(self, headers, directive_id):
        """GET /hie/consent-directives/{id} -> 200."""
        return self._request("GET", f"/hie/consent-directives/{directive_id}", headers=headers)

    def list_consent_directives(
        self,
        headers,
        cluster_id=_OMIT,
        policy_id=_OMIT,
        scoped_participant_id=_OMIT,
        supersedes_directive_id=_OMIT,
        status=_OMIT,
        directive_type=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/consent-directives -> 200 (paginated)."""
        params = _params(
            {
                "cluster_id": cluster_id,
                "policy_id": policy_id,
                "scoped_participant_id": scoped_participant_id,
                "supersedes_directive_id": supersedes_directive_id,
                "status": status,
                "directive_type": directive_type,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/consent-directives", headers=headers, params=params)

    # ==================================================================
    # Reads: queries and the audit trail
    # ==================================================================

    def get_record_locator_query(self, headers, query_id):
        """GET /hie/record-locator-queries/{id} -> 200."""
        return self._request("GET", f"/hie/record-locator-queries/{query_id}", headers=headers)

    def list_record_locator_queries(
        self,
        headers,
        querying_participant_id=_OMIT,
        cluster_id=_OMIT,
        break_glass_id=_OMIT,
        governing_policy_id=_OMIT,
        governing_directive_id=_OMIT,
        consent_decision=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/record-locator-queries -> 200 (paginated)."""
        params = _params(
            {
                "querying_participant_id": querying_participant_id,
                "cluster_id": cluster_id,
                "break_glass_id": break_glass_id,
                "governing_policy_id": governing_policy_id,
                "governing_directive_id": governing_directive_id,
                "consent_decision": consent_decision,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/record-locator-queries", headers=headers, params=params)

    def get_access_audit_entry(self, headers, audit_entry_id):
        """GET /hie/access-audit-entries/{id} -> 200."""
        return self._request("GET", f"/hie/access-audit-entries/{audit_entry_id}", headers=headers)

    def list_access_audit_entries(
        self,
        headers,
        query_id=_OMIT,
        record_id=_OMIT,
        disclosing_participant_id=_OMIT,
        action=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/access-audit-entries -> 200 (paginated)."""
        params = _params(
            {
                "query_id": query_id,
                "record_id": record_id,
                "disclosing_participant_id": disclosing_participant_id,
                "action": action,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/access-audit-entries", headers=headers, params=params)

    # ==================================================================
    # Reads: break-the-glass sessions
    # ==================================================================

    def get_break_glass_access(self, headers, break_glass_id):
        """GET /hie/break-glass-accesses/{id} -> 200."""
        return self._request("GET", f"/hie/break-glass-accesses/{break_glass_id}", headers=headers)

    def list_break_glass_accesses(
        self,
        headers,
        cluster_id=_OMIT,
        invoking_participant_id=_OMIT,
        session_status=_OMIT,
        review_status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/break-glass-accesses -> 200 (paginated)."""
        params = _params(
            {
                "cluster_id": cluster_id,
                "invoking_participant_id": invoking_participant_id,
                "session_status": session_status,
                "review_status": review_status,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/hie/break-glass-accesses", headers=headers, params=params)

    # ==================================================================
    # Reads: notification subscriptions
    # ==================================================================

    def get_notification_subscription(self, headers, subscription_id):
        """GET /hie/notification-subscriptions/{id} -> 200."""
        return self._request(
            "GET", f"/hie/notification-subscriptions/{subscription_id}", headers=headers
        )

    def list_notification_subscriptions(
        self,
        headers,
        subscriber_participant_id=_OMIT,
        cluster_id=_OMIT,
        activating_conformance_test_id=_OMIT,
        status=_OMIT,
        subscription_scope=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/notification-subscriptions -> 200 (paginated)."""
        params = _params(
            {
                "subscriber_participant_id": subscriber_participant_id,
                "cluster_id": cluster_id,
                "activating_conformance_test_id": activating_conformance_test_id,
                "status": status,
                "subscription_scope": subscription_scope,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request(
            "GET", "/hie/notification-subscriptions", headers=headers, params=params
        )

    # ==================================================================
    # Reads: data feeds, quality samples, invoices
    # ==================================================================

    def get_data_feed(self, headers, data_feed_id):
        """GET /hie/data-feeds/{id} -> 200."""
        return self._request("GET", f"/hie/data-feeds/{data_feed_id}", headers=headers)

    def list_participant_data_feeds(
        self,
        headers,
        participant_id,
        feed_type=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/participants/{id}/data-feeds -> 200 (paginated)."""
        params = _params({"feed_type": feed_type, "status": status, "limit": limit, "offset": offset})
        params.update(extra_params)
        return self._request(
            "GET", f"/hie/participants/{participant_id}/data-feeds", headers=headers, params=params
        )

    def list_data_feed_quality_samples(
        self, headers, data_feed_id, limit=_OMIT, offset=_OMIT, **extra_params
    ):
        """GET /hie/data-feeds/{id}/quality-samples -> 200 (paginated)."""
        params = _params({"limit": limit, "offset": offset})
        params.update(extra_params)
        return self._request(
            "GET", f"/hie/data-feeds/{data_feed_id}/quality-samples", headers=headers, params=params
        )

    def get_participation_invoice(self, headers, invoice_id):
        """GET /hie/participation-invoices/{id} -> 200."""
        return self._request("GET", f"/hie/participation-invoices/{invoice_id}", headers=headers)

    def list_participant_participation_invoices(
        self,
        headers,
        participant_id,
        status=_OMIT,
        basis_variant=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /hie/participants/{id}/participation-invoices -> 200 (paginated)."""
        params = _params(
            {"status": status, "basis_variant": basis_variant, "limit": limit, "offset": offset}
        )
        params.update(extra_params)
        return self._request(
            "GET",
            f"/hie/participants/{participant_id}/participation-invoices",
            headers=headers,
            params=params,
        )


# Module-level singleton used by every fixture and test.
api_client = ApiClient()
