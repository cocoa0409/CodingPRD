"""Authentication, authorization, existence checks, and pipeline priority ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_rate_schedule_payload, create_adl_log_payload,
    create_home, add_caregiver, create_licensed_home,
    create_pending_admission_scenario, make_caregiver_headers, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
PROVIDER2 = TEST_USERS["provider2_headers"]
NURSE = TEST_USERS["nurse_headers"]

MISSING_UUID = "11111111-2222-3333-4444-555555555555"
CAREGIVER_ROLE_ONLY = {"X-User-Role": "CaregiverRole",
                       "Content-Type": "application/json"}


class TestExistenceChecks:
    def test_get_nonexistent_home_returns_404(self, api):
        """PRD §2.10: "Requests that target nested resources are validated
        left-to-right along the path: the first identifier that does not resolve to
        an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later
        identifier or body reference is examined."

        Design: Corner/entities/get_nonexistent_resources_return_404
        """
        res = api.get_home(MISSING_UUID, PROVIDER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_get_nonexistent_resident_returns_404(self, api):
        """PRD §2.10: "Requests that target nested resources are validated
        left-to-right along the path: the first identifier that does not resolve to
        an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later
        identifier or body reference is examined."

        Design: Corner/entities/get_nonexistent_resources_return_404
        """
        res = api.get_resident(MISSING_UUID, PROVIDER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestAuthentication:
    def test_entity_backed_role_missing_user_id_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `CaregiverRole`, `X-User-ID` is the `id`
        of the acting `Caregiver`; ownership checks on any resource that references a
        caregiver compare the resource's foreign-key field to `X-User-ID`, and a
        missing or unknown caregiver identifier fails authentication."
        PRD §2.1: "A request whose `X-User-Role` header is missing or names no
        declared role — or whose `X-User-ID` is missing or unresolvable where the
        role requires it — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_entity_backed_missing_user_id
        """
        res = api.create_adl_log(
            create_adl_log_payload(MISSING_UUID, MISSING_UUID,
                                   "2026-06-02T15:00:00Z"),
            CAREGIVER_ROLE_ONLY)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_unauthenticated_beats_not_found(self, api):
        """PRD §2.9: "Every request passes through a fixed, globally ordered
        validation pipeline, and the first failing check determines the error
        returned."
        PRD §2.9: "1. Authentication — headers per §2.1; failure yields
        `ERR_UNAUTHENTICATED`."
        PRD §2.9: "3. Existence — every identifier referenced in the path and in the
        body exists, validated left-to-right (§2.10); failure yields
        `ERR_NOT_FOUND`."

        Design: Corner/validations/unauthenticated_beats_not_found
        """
        res = api.get_resident(MISSING_UUID, CAREGIVER_ROLE_ONLY)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_not_found_beats_state_on_admission_approve(self, api):
        """PRD §2.9: "Every request passes through a fixed, globally ordered
        validation pipeline, and the first failing check determines the error
        returned."
        PRD §2.9: "3. Existence — every identifier referenced in the path and in the
        body exists, validated left-to-right (§2.10); failure yields
        `ERR_NOT_FOUND`."
        PRD §2.9: "5. State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/validations/not_found_beats_state_on_admission_approve
        """
        res = api.approve_admission(MISSING_UUID, PROVIDER2)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestAuthorization:
    def test_nurse_cannot_approve_admission(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.3: "Approval — a `Provider` decision moving `PENDING` → `APPROVED` —
        enforces its checks in the pipeline order of §2.9."

        Design: Corner/rbac/nurse_cannot_approve_admission
        """
        ctx = create_licensed_home(name="RBAC Nurse", bed_label="1A")
        adm = create_pending_admission_scenario(ctx["home"]["id"], ctx["bed"]["id"])
        res = api.approve_admission(adm["admission"]["id"], NURSE)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "PENDING", \
            "a denied approval must leave the admission PENDING"

    def test_caregiver_cannot_create_rate_schedule(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.7: "A `Provider` publishes a rate schedule for a home with a
        `payer_type` marking which payer population it prices, a positive
        `room_and_board_daily_cents`, and three band add-ons —
        `care_low_daily_cents` at zero or more, `care_medium_daily_cents` at least
        the low figure, and `care_high_daily_cents` at least the medium figure —
        together with an inclusive `effective_from` date and an optional exclusive
        `effective_to` date, where null means open-ended."

        Design: Corner/rbac/caregiver_cannot_create_rate_schedule
        """
        home = create_home(name="RBAC Cg Rate", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg RR")
        res = api.create_rate_schedule(
            home["id"], create_rate_schedule_payload(),
            make_caregiver_headers(caregiver["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
