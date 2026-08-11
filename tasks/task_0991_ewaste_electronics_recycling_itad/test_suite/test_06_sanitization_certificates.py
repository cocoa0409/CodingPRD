"""Data sanitization, segregation of duties, the verification state machine,
and Certificate of Data Destruction issuance (PRD §3.5, §3.6)."""
import re

from test_helpers import (
    ApiErrorId,
    INTAKE,
    assert_certificate,
    list_item,
    log_sanitization,
    make_compliance_officer_headers,
    new_account,
    new_active_policy,
    new_manifest,
    receive_manifest,
    scan_item,
    schedule_manifest,
    setup_triaged_item,
    triage_item,
    validate_error,
    validate_success,
    verify_sanitization_record,
)

TECH = "tech-1"
OFFICER = "co-1"


def _setup_logged_sanitization(api, method="NIST_CLEAR", outcome="PASS",
                               policy_methods=None):
    """Policy active + data-bearing item triaged REFURB + one logged attempt.
    Returns (context, record)."""
    new_active_policy(sanitization_methods_allowed=policy_methods
                      or ["CRYPTO_ERASE", "NIST_CLEAR", "NIST_PURGE", "PHYSICAL_DESTROY"])
    ctx = setup_triaged_item(disposition="REFURB", data_bearing=True, declared_grade="B")
    record = log_sanitization(ctx["item"]["id"], method=method, outcome=outcome, tech_id=TECH)
    return ctx, record


class TestSanitizationOutcome:
    def test_fail_outcome_record_stays_logged(self, api):
        """PRD §3.5: "A logged attempt starts in `LOGGED` status with `logged_by_id` recorded from the technician's `X-User-ID`; when the outcome is `PASS` the item's `data_status` advances to `SANITIZED`, while a `FAIL` outcome leaves it at `PENDING`."

        Design: Corner/state_machines/sanitize_fail_keeps_data_pending
        """
        _ctx, record = _setup_logged_sanitization(api, outcome="FAIL",
                                                  policy_methods=["NIST_CLEAR"])
        assert record["status"] == "LOGGED"
        assert record["logged_by_id"] == TECH

    def test_fail_outcome_keeps_item_data_pending(self, api, destruction_technician_headers):
        """PRD §3.5: "A logged attempt starts in `LOGGED` status with `logged_by_id` recorded from the technician's `X-User-ID`; when the outcome is `PASS` the item's `data_status` advances to `SANITIZED`, while a `FAIL` outcome leaves it at `PENDING`."

        Design: Corner/state_machines/sanitize_fail_keeps_data_pending
        """
        ctx, _record = _setup_logged_sanitization(api, outcome="FAIL",
                                                  policy_methods=["NIST_CLEAR"])
        item = validate_success(api.get_item(ctx["item"]["id"], destruction_technician_headers))
        assert item["data_status"] == "PENDING"


class TestVerificationStateMachine:
    def test_verify_already_verified_rejected(self, api):
        """PRD §3.5: "A `ComplianceOfficer` reviews a `LOGGED` record by submitting a `verdict` of `APPROVE` or `REJECT`; a record in any other state refuses the transition with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/verify_already_verified_returns_409
        """
        _ctx, record = _setup_logged_sanitization(api)
        verify_sanitization_record(record["id"], verdict="APPROVE", officer_id=OFFICER)

        resp = api.verify_sanitization(record["id"], {"verdict": "APPROVE"},
                                       make_compliance_officer_headers(OFFICER))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_verify_by_logging_user_rejected(self, api):
        """PRD §3.5: "Segregation of duties is enforced before the verdict itself is considered: the verifier's `X-User-ID` must differ from the record's `logged_by_id`, and a technician attempting to verify their own work — or an officer verifying a record they themselves logged — is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_same_user_verify_rejected
        """
        _ctx, record = _setup_logged_sanitization(api, policy_methods=["NIST_CLEAR"])
        # An officer whose X-User-ID equals the logging technician's id.
        resp = api.verify_sanitization(record["id"], {"verdict": "APPROVE"},
                                       make_compliance_officer_headers(TECH))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403


class TestPolicyMethodRestriction:
    def test_method_outside_active_policy_rejected(self, api, destruction_technician_headers):
        """PRD §3.5: "The chosen method must appear in the active compliance policy's `sanitization_methods_allowed`; a method outside the policy is refused with `ERR_SANITIZATION_METHOD_NOT_ALLOWED`."

        Design: Corner/validations/policy_method_restriction_rejected
        """
        new_active_policy(standard="E_STEWARDS",
                          sanitization_methods_allowed=["NIST_PURGE", "PHYSICAL_DESTROY"],
                          weight_cert_freshness=0.3, weight_volume=0.2, weight_violations=0.5)
        ctx = setup_triaged_item(disposition="REFURB", data_bearing=True, declared_grade="B")

        resp = api.create_sanitization(
            ctx["item"]["id"], {"method": "NIST_CLEAR", "outcome": "PASS"},
            destruction_technician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SANITIZATION_METHOD_NOT_ALLOWED)
        assert resp.status_code == 422


class TestCertificateOfDataDestruction:
    def test_codd_rejected_while_sanitization_only_logged(self, api):
        """PRD §3.5: "Once a data-bearing item reaches `VERIFIED`, a `ComplianceOfficer` may issue it a **Certificate of Data Destruction**: the request's `cert_type` must be `DATA_DESTRUCTION` (any other value is rejected with `ERR_VALIDATION`), and the data gate of §2.6 applies in full — issuing the certificate for a data-bearing item whose `data_status` is anything but `VERIFIED` is rejected with `ERR_DATA_SANITIZATION_UNVERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/codd_blocked_until_sanitization_verified
        """
        ctx, _record = _setup_logged_sanitization(api)  # PASS logged -> SANITIZED, not VERIFIED
        resp = api.create_item_certificate(
            ctx["item"]["id"], {"cert_type": "DATA_DESTRUCTION"},
            make_compliance_officer_headers(OFFICER),
        )
        validate_error(resp, ApiErrorId.ERR_DATA_SANITIZATION_UNVERIFIED)
        assert resp.status_code == 422

    def test_codd_issued_after_verification(self, api):
        """PRD §3.5: "The certificate is created `ISSUED`, stamped with a server-minted `certificate_number` consisting of the prefix `CERT-` followed by eight uppercase hexadecimal characters, linked to its `item_id`, and attributed to the issuing officer via `issued_by_id`."

        Design: Difficulty/cross_entity_state_dependency/codd_blocked_until_sanitization_verified
        """
        ctx, record = _setup_logged_sanitization(api)
        verify_sanitization_record(record["id"], verdict="APPROVE", officer_id=OFFICER)

        resp = api.create_item_certificate(
            ctx["item"]["id"], {"cert_type": "DATA_DESTRUCTION"},
            make_compliance_officer_headers(OFFICER),
        )
        cert = validate_success(resp, 201)
        assert_certificate(cert)
        assert cert["status"] == "ISSUED"
        assert re.match(r"^CERT-[0-9A-F]{8}$", cert["certificate_number"])
        assert cert["item_id"] == ctx["item"]["id"]
        assert cert["issued_by_id"] == OFFICER


class TestParallelStateDimensions:
    def _walk_reject_retry_and_processing_loop(self, api):
        """Data dimension PENDING -> SANITIZED -> PENDING (reject) -> SANITIZED
        -> VERIFIED while processing loops INTAKE -> FOR_REFURB -> FOR_RESALE
        -> LISTED -> FOR_RESALE. Returns (context, observed data statuses)."""
        new_active_policy()
        account = new_account("Loop Co", "l@loop.example")
        manifest = new_manifest(account)
        manifest = schedule_manifest(manifest["id"])
        manifest = receive_manifest(manifest["id"])
        item = scan_item(manifest["id"], serial_number="SN-X1", category="LAPTOP",
                         weight_kg=2.5, data_bearing=True, declared_grade="B")
        item = triage_item(item["id"], "REFURB")

        statuses = []
        r1 = log_sanitization(item["id"], method="NIST_CLEAR", outcome="PASS", tech_id=TECH)
        statuses.append(_data_status(api, item["id"]))  # SANITIZED
        verify_sanitization_record(r1["id"], verdict="REJECT", officer_id=OFFICER)
        statuses.append(_data_status(api, item["id"]))  # PENDING again
        r2 = log_sanitization(item["id"], method="NIST_PURGE", outcome="PASS", tech_id=TECH)
        statuses.append(_data_status(api, item["id"]))  # SANITIZED
        verify_sanitization_record(r2["id"], verdict="APPROVE", officer_id=OFFICER)
        statuses.append(_data_status(api, item["id"]))  # VERIFIED

        item = triage_item(item["id"], "RESALE")
        listing = list_item(item["id"], asking_price_cents=30000, floor_price_cents=20000)
        validate_success(api.withdraw_listing(listing["id"], INTAKE))
        return {"account": account, "manifest": manifest, "item_id": item["id"]}, statuses

    def test_data_dimension_survives_reject_retry_loop(self, api):
        """PRD §3.5: "On `REJECT`, the record becomes `REJECTED`, `verified_by_id` is still recorded, and the item's `data_status` falls back to `PENDING`, opening a retry loop in which a fresh sanitization attempt may be logged and verified."
        PRD §3.5: "On `APPROVE`, the attempt's `outcome` must be `PASS` — a failed attempt can never be verified, and the request fails with `ERR_INVALID_STATE` — after which the record becomes `VERIFIED`, `verified_by_id` is set to the verifier, and the item's `data_status` advances to `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/item_parallel_data_dim_and_refurb_reroute_loop
        """
        _ctx, statuses = self._walk_reject_retry_and_processing_loop(api)
        assert statuses == ["SANITIZED", "PENDING", "SANITIZED", "VERIFIED"]

    def test_processing_loop_leaves_verified_data_untouched(self, api, intake_operator_headers):
        """PRD §3.4: "An item carries two independent state dimensions from this point on."
        PRD §3.6: "Alternatively, an unsold listing may be withdrawn: `ACTIVE` → `WITHDRAWN` is terminal for the listing and returns the item `LISTED` → `FOR_RESALE`, free to be relisted through a fresh listing or retriaged to recycling."

        Design: Difficulty/non_linear_state_machine/item_parallel_data_dim_and_refurb_reroute_loop
        """
        ctx, _statuses = self._walk_reject_retry_and_processing_loop(api)
        item = validate_success(api.get_item(ctx["item_id"], intake_operator_headers))
        assert item["processing_status"] == "FOR_RESALE"
        assert item["disposition"] == "RESALE"
        assert item["data_status"] == "VERIFIED"


def _data_status(api, item_id):
    return validate_success(api.get_item(item_id, INTAKE))["data_status"]


class TestListingGateRelaxed:
    def test_listing_allowed_when_policy_flag_false(self, api):
        """PRD §3.6: "for a data-bearing item, listing requires `data_status` `VERIFIED` whenever the active policy's `resale_requires_verified_sanitization` flag is true — which is also the strict default applied when no policy is active at all — and requires `SANITIZED` or `VERIFIED` when the flag is false; breaching the gate yields `ERR_DATA_SANITIZATION_UNVERIFIED`."

        Design: Corner/cross_cutting_complexity_layers/listing_gate_relaxed_when_policy_flag_false
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"],
                          resale_requires_verified_sanitization=False)
        ctx = setup_triaged_item(disposition="RESALE", data_bearing=True, declared_grade="B")
        # PASS logged but never verified -> data_status SANITIZED only.
        log_sanitization(ctx["item"]["id"], method="NIST_CLEAR", outcome="PASS", tech_id=TECH)

        listing = list_item(ctx["item"]["id"], asking_price_cents=30000, floor_price_cents=20000)
        assert listing["status"] == "ACTIVE"
