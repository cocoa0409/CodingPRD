"""Enrollment application channel: drafting, submission gates, the
info-request cycle, and terminal-state lockdown (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_second,
    create_draft_application,
    create_payer_config,
    create_submitted_application,
    get_success_data,
    set_clock,
    setup_group_provider_payer,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestInfoRequestCycle:
    def test_submit_request_info_resubmit_approve_cycle(self, api):
        """PRD §3.3: "The specialist answers by resubmitting, which returns the
        application `PENDING_INFO → SUBMITTED` under the same two compliance
        gates and refreshes `submitted_at`; this information-request loop may
        repeat any number of times."
        PRD §3.3: "From `SUBMITTED`, a `PayerRepresentative` may push the
        application into `PENDING_INFO` with a request for more information,
        supplying a `reason` that is recorded as `info_request_reason`."

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_draft_application(
            provider["id"], payer["id"], enrollment_scope="GROUP_LINK",
        )

        s1 = validate_success(api.submit_application(app["id"], SPECIALIST), 200)
        assert s1["status"] == "SUBMITTED"

        s2 = validate_success(
            api.request_info_application(app["id"], {"reason": "need W-9"}, PAYER_REP), 200
        )
        assert s2["status"] == "PENDING_INFO"
        assert s2["info_request_reason"] == "need W-9"

        s3 = validate_success(api.resubmit_application(app["id"], SPECIALIST), 200)
        assert s3["status"] == "SUBMITTED", "cycle closes back, not a new application"
        assert s3["id"] == app["id"]

        s4 = validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        assert s4["status"] == "APPROVED"
        assert s4["info_request_reason"] == "need W-9"

    def test_info_request_loop_repeats_and_refreshes_submitted_at(self, api):
        """PRD §3.3: "The specialist answers by resubmitting, which returns the
        application `PENDING_INFO → SUBMITTED` under the same two compliance
        gates and refreshes `submitted_at`; this information-request loop may
        repeat any number of times."

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_draft_application(provider["id"], payer["id"])

        first = validate_success(api.submit_application(app["id"], SPECIALIST), 200)
        assert_timestamp_second(first["submitted_at"], "2026-08-01T00:00:00")

        # First loop.
        validate_success(
            api.request_info_application(app["id"], {"reason": "need W-9"}, PAYER_REP), 200
        )
        set_clock("2026-08-05T00:00:00Z")
        second = validate_success(api.resubmit_application(app["id"], SPECIALIST), 200)
        assert second["status"] == "SUBMITTED"
        assert_timestamp_second(second["submitted_at"], "2026-08-05T00:00:00")

        # Second loop — the cycle may repeat any number of times.
        validate_success(
            api.request_info_application(app["id"], {"reason": "need CV"}, PAYER_REP), 200
        )
        set_clock("2026-08-09T00:00:00Z")
        third = validate_success(api.resubmit_application(app["id"], SPECIALIST), 200)
        assert third["status"] == "SUBMITTED"
        assert_timestamp_second(third["submitted_at"], "2026-08-09T00:00:00")
        assert third["info_request_reason"] == "need CV"

        final = validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        assert final["status"] == "APPROVED"


class TestApproveGatedByCaqhAttestation:
    def test_approve_blocked_when_profile_lapsed_after_submission(self, api):
        """PRD §3.3: "A `PayerRepresentative` approving a `SUBMITTED`
        application re-checks both compliance gates at approval time — a
        provider terminated mid-adjudication yields `ERR_PROVIDER_TERMINATED`,
        and a CAQH profile that has since lapsed yields
        `ERR_CAQH_ATTESTATION_NOT_CURRENT` — and then enforces enrollment
        exclusivity".

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_lapsed_caqh
        """
        _, provider, _, payer = setup_group_provider_payer()
        # Attested at the startup clock 2026-08-01 -> due_at 2026-11-29.
        app = create_submitted_application(provider["id"], payer["id"])

        set_clock("2026-12-01T00:00:00Z")  # strictly past due_at -> LAPSED
        res = api.approve_application(app["id"], PAYER_REP)
        validate_error(res, ApiErrorId.ERR_CAQH_ATTESTATION_NOT_CURRENT)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "SUBMITTED"
        records = get_success_data(
            api.list_enrollment_records(
                SPECIALIST, params={"provider_id": provider["id"], "payer_id": payer["id"]}
            )
        )
        assert records == [], "no EnrollmentRecord may be created by a blocked approval"

    def test_approve_succeeds_while_profile_in_due_window(self, api):
        """PRD §3.2: "Submitting, resubmitting, or approving an enrollment
        application requires the provider's profile to be `ATTESTED` or `DUE`;
        a profile that is `NEVER_ATTESTED` or `LAPSED` blocks all three with
        `ERR_CAQH_ATTESTATION_NOT_CURRENT` (§3.3)."

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_lapsed_caqh
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(provider["id"], payer["id"])

        # Attested 2026-08-01 -> due_at 2026-11-29; warning window opens
        # 2026-10-30, so 2026-11-15 is inside the window (DUE, not LAPSED).
        set_clock("2026-11-15T00:00:00Z")
        approved = validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        assert approved["status"] == "APPROVED"
        record = get_success_data(
            api.list_enrollment_records(
                SPECIALIST, params={"source_application_id": app["id"]}
            )
        )[0]
        # APPROVAL_DATE policy: the requested date is ignored entirely.
        assert record["effective_date"] == "2026-11-15"


class TestApplicationCreationGuards:
    def test_missing_requested_effective_date_returns_invalid_request(self, api):
        """PRD §2.8: "4. **Request schema** — required fields present, enum
        members valid, date fields parse as `YYYY-MM-DD`, integer fields are
        integers, a claim's `amount_cents` is positive, and an agreement's
        `expiry_date` is strictly later than its `effective_date`, else
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/application_create_missing_required_field_returns_invalid_request
        """
        _, provider, _, payer = setup_group_provider_payer(attest=False)
        res = api.create_enrollment_application(
            {
                "provider_id": provider["id"],
                "payer_id": payer["id"],
                "enrollment_scope": "INDIVIDUAL",
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_retro_window_boundary_on_application_create(self, api):
        """PRD §3.3: "Creation itself is guarded: the requested date may be no
        earlier than ninety days before the current logical date, or the
        request fails with `ERR_RETRO_WINDOW_EXCEEDED`".

        Design: Corner/validations/retro_window_boundary_on_application_create
        """
        group, provider, _, payer_a = setup_group_provider_payer(attest=False)
        payer_b = create_payer_config(payer_code="PAYER-B", name="Payer B")

        # At the startup clock 2026-08-01 the earliest acceptable date is
        # exactly 2026-05-03 (inclusive).
        ok = validate_success(
            api.create_enrollment_application(
                {
                    "provider_id": provider["id"],
                    "payer_id": payer_a["id"],
                    "enrollment_scope": "INDIVIDUAL",
                    "requested_effective_date": "2026-05-03",
                },
                SPECIALIST,
            ),
            201,
        )
        assert ok["status"] == "DRAFT"

        res = api.create_enrollment_application(
            {
                "provider_id": provider["id"],
                "payer_id": payer_b["id"],
                "enrollment_scope": "INDIVIDUAL",
                "requested_effective_date": "2026-05-02",
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_RETRO_WINDOW_EXCEEDED)

    def test_application_in_flight_conflict_then_freed_by_withdrawal(self, api):
        """PRD §3.3: "at most one application per provider–payer pair may be in
        flight — that is, in `DRAFT`, `SUBMITTED`, or `PENDING_INFO` — or
        creation fails with `ERR_APPLICATION_IN_FLIGHT`".

        Design: Corner/validations/application_in_flight_conflict
        """
        _, provider, _, payer = setup_group_provider_payer(attest=False)
        app1 = create_draft_application(provider["id"], payer["id"])

        res = api.create_enrollment_application(
            {
                "provider_id": provider["id"],
                "payer_id": payer["id"],
                "enrollment_scope": "GROUP_LINK",
                "requested_effective_date": "2026-09-01",
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_IN_FLIGHT)

        validate_success(api.withdraw_application(app1["id"], SPECIALIST), 200)
        app2 = validate_success(
            api.create_enrollment_application(
                {
                    "provider_id": provider["id"],
                    "payer_id": payer["id"],
                    "enrollment_scope": "GROUP_LINK",
                    "requested_effective_date": "2026-09-01",
                },
                SPECIALIST,
            ),
            201,
        )
        assert app2["status"] == "DRAFT"


class TestSubmitGateAndWrongState:
    def test_submit_blocked_without_attestation(self, api):
        """PRD §3.3: "Two compliance gates guard the transition: the provider
        must still be `ACTIVE` (else `ERR_PROVIDER_TERMINATED`) and the
        provider's CAQH profile must be `ATTESTED` or `DUE` (else
        `ERR_CAQH_ATTESTATION_NOT_CURRENT`)."

        Design: Corner/validations/submit_blocked_without_attestation
        """
        _, provider, _, payer = setup_group_provider_payer(attest=False)
        app = create_draft_application(provider["id"], payer["id"])
        assert app["status"] == "DRAFT", "creation itself is allowed without attestation"

        res = api.submit_application(app["id"], SPECIALIST)
        validate_error(res, ApiErrorId.ERR_CAQH_ATTESTATION_NOT_CURRENT)

    def test_approve_from_draft_rejected(self, api):
        """PRD §2.8: "7. **State guards** — the target resource's state permits
        the transition, else `ERR_INVALID_STATE_TRANSITION`,
        `ERR_ROSTER_LINE_NOT_PENDING`, `ERR_CLAIM_NOT_RECOUPED`, or
        `ERR_REVALIDATION_NOT_DUE` (409)."

        Design: Corner/state_machines/approve_from_wrong_state_rejected
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_draft_application(provider["id"], payer["id"])

        res = api.approve_application(app["id"], PAYER_REP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "DRAFT"
        records = get_success_data(
            api.list_enrollment_records(
                SPECIALIST, params={"source_application_id": app["id"]}
            )
        )
        assert records == [], "no EnrollmentRecord may be created from a DRAFT approve"


class TestRejectedApplicationTerminalLockdown:
    @pytest.mark.parametrize("transition", ["approve", "submit", "request-info", "withdraw"])
    def test_rejected_application_rejects_further_transitions(self, api, transition):
        """PRD §3.3: "`APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal;
        invoking any further transition on a terminal application is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/rejected_application_terminal_lockdown
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(provider["id"], payer["id"])
        rejected = validate_success(
            api.reject_application(app["id"], {"reason": "incomplete"}, PAYER_REP), 200
        )
        assert rejected["status"] == "REJECTED"

        if transition == "approve":
            res = api.approve_application(app["id"], PAYER_REP)
        elif transition == "submit":
            res = api.submit_application(app["id"], SPECIALIST)
        elif transition == "request-info":
            res = api.request_info_application(app["id"], {"reason": "again"}, PAYER_REP)
        else:
            res = api.withdraw_application(app["id"], SPECIALIST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "REJECTED"
        assert after["decision_reason"] == "incomplete"
