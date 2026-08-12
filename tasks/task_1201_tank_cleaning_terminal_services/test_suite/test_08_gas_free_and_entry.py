"""Gas-free certification, entry permits, and their parallel dimensions
(PRD §2.9, §2.10, §3.6)."""
from datetime import timedelta

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    build_user_headers,
    create_gas_free_certificate_payload, create_entry_permit_payload,
    new_ctx, create_job,
    setup_ctx_gas_free_pending, setup_ctx_gas_free_certified,
    setup_ctx_entry_in_progress,
    add_permit, issue_certificate, contractor_headers, set_clock, parse_ts,
    get_job,
)

OPERATOR = TEST_USERS["operator_headers"]
CHEMIST = TEST_USERS["chemist_headers"]
EHS = TEST_USERS["ehs_headers"]


class TestGasFreeLimits:
    def test_lel_exactly_10_pct_rejected(self, api):
        """PRD §2.9: "the lower-explosive-limit reading `lel_pct` strictly below 10.0 percent"
        PRD §2.9: "A certificate request breaching any one of these is rejected with `ERR_GAS_FREE_LIMITS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/lel_strict_boundary_at_10pct
        """
        ctx = setup_ctx_gas_free_pending()
        res = api.create_gas_free_certificate(
            create_gas_free_certificate_payload(ctx["job"]["id"], lel_pct=10.0),
            CHEMIST)
        validate_error(res, ApiErrorId.ERR_GAS_FREE_LIMITS_EXCEEDED)
        assert get_job(ctx)["status"] == "GAS_FREE_PENDING"

    def test_lel_just_below_10_pct_certifies(self, api):
        """PRD §2.9: "the lower-explosive-limit reading `lel_pct` strictly below 10.0 percent"
        PRD §3.6: "the job itself advances `GAS_FREE_PENDING` to `GAS_FREE_CERTIFIED` without further action."

        Design: Difficulty/boundary_precision_check/lel_strict_boundary_at_10pct
        """
        ctx = setup_ctx_gas_free_pending()
        cert = validate_success(api.create_gas_free_certificate(
            create_gas_free_certificate_payload(ctx["job"]["id"], lel_pct=9.9),
            CHEMIST), 201)
        assert cert["status"] == "VALID"
        assert get_job(ctx)["status"] == "GAS_FREE_CERTIFIED"

    def test_o2_below_closed_band_rejected_then_inclusive_bounds_pass(self, api):
        """PRD §2.9: "the oxygen reading `o2_pct` within the closed band from 19.5 to 23.5 percent inclusive, the hydrogen sulfide reading `h2s_ppm` at most 10.0 ppm inclusive"
        PRD §2.9: "A certificate request breaching any one of these is rejected with `ERR_GAS_FREE_LIMITS_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/o2_and_h2s_closed_band_boundaries
        """
        ctx = setup_ctx_gas_free_pending()
        res = api.create_gas_free_certificate(
            create_gas_free_certificate_payload(ctx["job"]["id"], o2_pct=19.4),
            CHEMIST)
        validate_error(res, ApiErrorId.ERR_GAS_FREE_LIMITS_EXCEEDED)
        # o2 19.5 (closed lower bound) and h2s 10.0 (inclusive limit) pass.
        cert = validate_success(api.create_gas_free_certificate(
            create_gas_free_certificate_payload(ctx["job"]["id"], o2_pct=19.5,
                                                h2s_ppm=10.0),
            CHEMIST), 201)
        assert cert["status"] == "VALID"


class TestCertificateRevalidation:
    def test_revalidate_extends_once_and_second_attempt_rejected(self, api):
        """PRD §3.6: "the one-shot flag is examined next, and a certificate already revalidated once rejects with `ERR_CERT_ALREADY_REVALIDATED` (HTTP 409). A successful revalidation extends `expires_at` by six hours and sets `revalidated`."
        PRD §2.9: "A certificate's `expires_at` is set twelve hours after its `issued_at`; exactly one revalidation is permitted and adds a further six hours."

        Design: Corner/state_machines/cert_revalidate_once_only
        """
        ctx = setup_ctx_gas_free_certified()
        cert = ctx["cert"]
        revalidated = validate_success(
            api.revalidate_certificate(cert["id"], CHEMIST), 200)
        assert revalidated["revalidated"] is True
        # 12h validity + 6h extension = issued_at + 18h.
        delta = parse_ts(revalidated["expires_at"]) - parse_ts(cert["issued_at"])
        assert delta == timedelta(hours=18)

        res = api.revalidate_certificate(cert["id"], CHEMIST)
        validate_error(res, ApiErrorId.ERR_CERT_ALREADY_REVALIDATED)


class TestPermitParallelDimensions:
    def test_alarm_suspend_resume_clear_cycle_moves_dimensions_independently(self, api):
        """PRD §3.6: "Permits carry two independent dimensions — a `status` lifecycle and an `atmosphere` dimension that moves in parallel without disturbing the status."
        PRD §3.6: "Resuming a suspended permit requires the anchoring certificate valid and unexpired (`ERR_CERT_EXPIRED`) and the atmosphere `CLEAR` (`ERR_ATMOSPHERE_NOT_CLEAR`), moving `SUSPENDED` back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/entry_permit_parallel_dimensions
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=True, activate=True)

        # raise-alarm: atmosphere moves, status untouched.
        after_alarm = validate_success(
            api.raise_alarm(permit["id"], contractor_headers(ctx)), 200)
        assert after_alarm["status"] == "ACTIVE"
        assert after_alarm["atmosphere"] == "ALARM"

        # suspend: status moves, atmosphere untouched.
        after_suspend = validate_success(api.suspend_permit(permit["id"], EHS), 200)
        assert after_suspend["status"] == "SUSPENDED"
        assert after_suspend["atmosphere"] == "ALARM"

        validate_success(api.resolve_alarm(permit["id"], EHS), 200)
        res = api.resume_permit(permit["id"], EHS)
        validate_error(res, ApiErrorId.ERR_ATMOSPHERE_NOT_CLEAR)

        cleared = validate_success(api.clear_atmosphere(permit["id"], EHS), 200)
        assert cleared["atmosphere"] == "CLEAR"
        resumed = validate_success(api.resume_permit(permit["id"], EHS), 200)
        assert resumed["status"] == "ACTIVE"
        assert resumed["atmosphere"] == "CLEAR"

    def test_raise_alarm_on_requested_permit_is_invalid_transition(self, api):
        """PRD §3.6: "Raising an alarm — available to the owning supervisor and to an `EHSOfficer` — moves `CLEAR` to `ALARM` while the permit's status is `ISSUED`, `ACTIVE`, or `SUSPENDED`; against any other status the attempt is an invalid transition."

        Design: Difficulty/non_linear_state_machine/entry_permit_parallel_dimensions
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=False)  # still REQUESTED
        res = api.raise_alarm(permit["id"], contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert after["status"] == "REQUESTED"
        assert after["atmosphere"] == "CLEAR"


class TestPermitResumeVsCertificate:
    def test_resume_blocked_after_certificate_expiry_sweep(self, api):
        """PRD §2.9: "A certificate anchors downstream operations only while its status is `VALID` and the logical clock is strictly before `expires_at`; at or past that instant, use-sites fail with `ERR_CERT_EXPIRED` (HTTP 409), and the clock sweep of §2.5 marks the certificate `EXPIRED`."
        PRD §3.6: "Resuming a suspended permit requires the anchoring certificate valid and unexpired (`ERR_CERT_EXPIRED`)"

        Design: Difficulty/cross_entity_state_dependency/permit_resume_blocked_by_expired_cert
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=True)  # ISSUED, cert expires 12h later
        cert = ctx["cert"]

        # Advance to exactly expires_at: the sweep expires the cert and the
        # cascade suspends the ISSUED permit.
        set_clock(cert["expires_at"])
        cert_after = validate_success(
            api.get_gas_free_certificate(cert["id"], OPERATOR), 200)
        assert cert_after["status"] == "EXPIRED"
        permit_after = validate_success(
            api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert permit_after["status"] == "SUSPENDED"

        res = api.resume_permit(permit["id"], EHS)
        validate_error(res, ApiErrorId.ERR_CERT_EXPIRED)

    def test_resume_succeeds_while_certificate_unexpired(self, api):
        """PRD §3.6: "Resuming a suspended permit requires the anchoring certificate valid and unexpired (`ERR_CERT_EXPIRED`) and the atmosphere `CLEAR` (`ERR_ATMOSPHERE_NOT_CLEAR`), moving `SUSPENDED` back to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/permit_resume_blocked_by_expired_cert
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=True)
        suspended = validate_success(api.suspend_permit(permit["id"], EHS), 200)
        assert suspended["status"] == "SUSPENDED"
        resumed = validate_success(api.resume_permit(permit["id"], EHS), 200)
        assert resumed["status"] == "ACTIVE"
        assert resumed["atmosphere"] == "CLEAR"


class TestPermitIssuanceOrder:
    def _job_back_in_gas_free_pending(self, api):
        """Job certified, permit REQUESTED, then cert revoked with no issued
        permits: job reverts to GAS_FREE_PENDING, permit stays REQUESTED."""
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=False)
        validate_success(api.revoke_certificate(ctx["cert"]["id"], CHEMIST), 200)
        assert get_job(ctx)["status"] == "GAS_FREE_PENDING"
        return ctx, permit

    def test_issue_state_failure_beats_segregation_of_duties(self, api):
        """PRD §3.6: "Issuance is the `EHSOfficer`'s act and is evaluated after the state checks: the job must stand in `GAS_FREE_CERTIFIED`, failing which the transition is invalid"
        PRD §2.11: "Every request is evaluated against a fixed validation pipeline, and the first failing check determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_beats_sod
        """
        ctx, permit = self._job_back_in_gas_free_pending(api)
        # Caller reuses the cert issuer's X-User-ID: SoD is also violated, but
        # the job-state failure is earlier in the pipeline.
        res = api.issue_permit(
            permit["id"], build_user_headers("chemist-1", "EHSOfficer"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert after["status"] == "REQUESTED"

    def test_issue_state_failure_alone_returns_invalid_transition(self, api):
        """PRD §3.6: "Issuance is the `EHSOfficer`'s act and is evaluated after the state checks: the job must stand in `GAS_FREE_CERTIFIED`, failing which the transition is invalid"

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_beats_sod
        """
        ctx, permit = self._job_back_in_gas_free_pending(api)
        # A different officer: only the job-state precondition fails.
        res = api.issue_permit(permit["id"], EHS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert after["status"] == "REQUESTED"

    def test_issue_by_certificate_issuer_violates_segregation_of_duties(self, api):
        """PRD §2.10: "The EHS officer issuing an entry permit must differ from the marine chemist who issued the anchoring gas-free certificate."
        PRD §2.10: "in each case the rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID` appears on both sides of the step."

        Design: Corner/validations/permit_issue_same_user_as_cert_issuer_rejected
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=False)
        res = api.issue_permit(
            permit["id"], build_user_headers("chemist-1", "EHSOfficer"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert after["status"] == "REQUESTED"


class TestEntryGates:
    def test_begin_entry_without_active_permit_rejected(self, api):
        """PRD §3.6: "moving `GAS_FREE_CERTIFIED` to `ENTRY_IN_PROGRESS` requires at least one permit of the job standing `ACTIVE` with atmosphere `CLEAR`, failing which `ERR_NO_VALID_ENTRY_PERMIT` (HTTP 409)."

        Design: Corner/validations/begin_entry_without_active_permit_rejected
        """
        ctx = setup_ctx_gas_free_certified()
        add_permit(ctx, issue=True)  # ISSUED but never ACTIVATED
        res = api.begin_entry(ctx["job"]["id"], contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_NO_VALID_ENTRY_PERMIT)
        assert get_job(ctx)["status"] == "GAS_FREE_CERTIFIED"

    def test_active_permit_blocks_complete_entry_and_cancel(self, api):
        """PRD §3.6: "Completing entry requires every permit of the job to stand in `CLOSED` or `VOIDED` — any permit still `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED` rejects the completion with `ERR_PERMITS_NOT_CLOSED` (HTTP 409)"
        PRD §3.8: "From `GAS_FREE_CERTIFIED` or `PAUSED`, a job holding any `ACTIVE` entry permit cannot be cancelled at all — the attempt is rejected with `ERR_JOB_HAS_ACTIVE_PERMIT` (HTTP 409)"

        Design: Corner/validations/active_permit_blocks_complete_entry_and_cancel
        """
        # (a) ENTRY_IN_PROGRESS with an ACTIVE permit: completion is blocked.
        ctx = setup_ctx_entry_in_progress()  # one ACTIVE permit
        res1 = api.complete_entry(ctx["job"]["id"], contractor_headers(ctx))
        validate_error(res1, ApiErrorId.ERR_PERMITS_NOT_CLOSED)
        assert get_job(ctx)["status"] == "ENTRY_IN_PROGRESS"

        # (b) PRD scopes ERR_JOB_HAS_ACTIVE_PERMIT to cancellation from
        # GAS_FREE_CERTIFIED or PAUSED (cancellation is not defined from
        # ENTRY_IN_PROGRESS at all — that would be ERR_INVALID_STATE_TRANSITION).
        ctx2 = setup_ctx_gas_free_certified()
        add_permit(ctx2, issue=True, activate=True)
        res2 = api.cancel_job(ctx2["job"]["id"], OPERATOR)
        validate_error(res2, ApiErrorId.ERR_JOB_HAS_ACTIVE_PERMIT)
        assert get_job(ctx2)["status"] == "GAS_FREE_CERTIFIED"
