"""Who may act, whose row it is, and what a refusal looks like on the wire.

Authorisation here has three independent layers that are easy to conflate: the
role listed for the endpoint, the vendor identity behind an entity-backed role,
and the segregation-of-duties rule that compares user identifiers inside a single
role. The last three cases pin the refusal envelope itself and the two checks
that sit at the very top of the rejection ordering.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    DUAL_ROLE_AUDITOR_HEADERS,
    DUAL_ROLE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_PREPARER_USER_ID,
    OFFICER_SIGNER_HEADERS,
    OFFICER_SIGNER_USER_ID,
    PLATFORM_OPERATOR_HEADERS,
    ROLE_PLAN_SPONSOR_ADMIN,
    SPONSOR_ADMIN_HEADERS,
    UNKNOWN_VENDOR_USER_ID,
    ApiClient,
    ApiErrorId,
    ATTESTATION_ACCEPTED,
    ATTESTATION_DRAFT,
    ATTESTATION_SUBMITTED,
    CYCLE_PENDING,
    NON_EXISTENT_UUID,
    PACKAGE_EXPECTED,
    PACKAGE_RECEIVED,
    POSTURE_COMPLIANT,
    RX_ASSEMBLING,
    VENDOR_TYPE_BROKER,
    factories as f,
    fixtures as fx,
    headers_without_user_id,
    make_vendor_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CYCLE_OPEN_CLOCK = "2027-03-01T09:00:00Z"
CYCLE_CERTIFY_CLOCK = "2027-04-02T09:00:00Z"
FREEZE_CLOCK = "2027-04-01T09:00:00Z"
PACKAGE_CLOCK = "2027-08-01T09:00:00Z"
VENDOR_READ_CLOCK = "2027-02-01T09:00:00Z"
ROSTER_CLOCK = "2027-12-01T09:00:00Z"
ATTESTATION_CLOCK = "2028-01-10T09:00:00Z"
REGISTRY_CLOCK = "2027-01-02T09:00:00Z"

DELIVERED_FIGURES = {
    "record_count": 1200,
    "plan_paid_cents": 6_000_000,
    "member_paid_cents": 1_000_000,
    "rebate_cents": 1_500_000,
}
FREEZE_REASON = "Officer wants the penalties paused pending review."
ENTITY_FIELDS = ("id", "plan_year_label", "version")


def _plan_year_with_pending_march_cycle(api: ApiClient) -> dict:
    """An active plan year whose March refresh cycle is still inside its grace."""
    fx.set_clock(api, CYCLE_OPEN_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    cycle = fx.open_refresh_cycle(
        api,
        setup["plan_year"]["id"],
        period_month="2027-03",
        period_start="2027-03-01",
        period_end="2027-03-31",
    )
    fx.set_clock(api, CYCLE_CERTIFY_CLOCK)
    return {"plan_year_id": setup["plan_year"]["id"], "cycle": cycle}


def _attestation_prepared_by(api: ApiClient, preparer_headers) -> dict:
    """A gag-clear plan year carrying one draft attestation from a named preparer."""
    fx.set_clock(api, ROSTER_CLOCK)
    setup = fx.activated_plan_year_with_roster(api, covered_lives=6000)
    fx.clear_gag_on_every_material_contract(api, setup)
    fx.set_clock(api, ATTESTATION_CLOCK)
    setup["attestation"] = fx.attestation_draft(
        api, setup["plan_year"]["id"], preparer_headers
    )
    return setup


class TestRoleExclusiveOperations:
    """Three operations that belong to exactly one role each."""

    def test_the_sponsor_who_opened_a_refresh_cycle_may_not_certify_it(
        self, api: ApiClient
    ) -> None:
        """Certification is a compliance judgement, not a sponsor's own sign-off.

        PRD 2.1: "A `PlanSponsorAdmin` may not certify refresh cycles, assess
        compensation disclosures, prepare, submit or adjudicate attestations, or
        reverse penalty ledger entries."

        PRD 2.1: "When `X-User-Role` is absent, holds a value that is not a
        recognised role, or holds a recognised role that is not listed for the
        addressed endpoint in §4, the request is refused with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/plan_sponsor_admin_cannot_certify_refresh_cycle
        """
        built = _plan_year_with_pending_march_cycle(api)

        validate_error(
            api.certify_refresh_cycle(
                built["cycle"]["id"], SPONSOR_ADMIN_HEADERS, f.certify_cycle_payload()
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            expected_status=403,
        )

        unchanged = validate_success(
            api.get_refresh_cycle(built["cycle"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == CYCLE_PENDING
        assert unchanged["certified_by_user_id"] is None
        assert unchanged["on_time"] is None
        assert unchanged["certified_at"] is None

    def test_the_officer_who_drives_compliance_runs_may_not_freeze_the_plan_year(
        self, api: ApiClient
    ) -> None:
        """Suspending the evidence trail is the independent auditor's call.

        PRD 2.1: "Accepts or rejects submitted attestations, freezes and
        unfreezes plan years, and reverses penalty ledger entries."

        PRD 2.9: "**Role authorization.** `X-User-Role` present and listed for
        the endpoint, on every endpoint — otherwise `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/compliance_officer_cannot_freeze_plan_year
        """
        fx.set_clock(api, FREEZE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        validate_error(
            api.freeze_plan_year(
                plan_year_id, {"reason": FREEZE_REASON}, COMPLIANCE_OFFICER_HEADERS
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            expected_status=403,
        )

        unchanged = fx.read_plan_year(api, plan_year_id)
        assert unchanged["freeze_flag"] is False
        assert unchanged["freeze_reason"] is None
        assert unchanged["compliance_posture"] == POSTURE_COMPLIANT
        assert unchanged["version"] == 2

    def test_the_vendor_that_delivered_a_package_may_not_adjudicate_it(
        self, api: ApiClient
    ) -> None:
        """Delivery and validation are deliberately different hands.

        PRD 2.1: "Submits gag-clause remediation, counters amendments, and
        delivers or resubmits its own prescription-drug data packages."

        PRD 2.1: "Runs gag-clause reviews, certifies refresh cycles, scores tool
        uptime, assesses compensation disclosures, validates and rejects vendor
        data packages, reconciles and files prescription-drug data, prepares,
        submits and revises attestations, drives compliance runs, and owns
        remediation plans."

        Design: Corner/rbac/vendor_contact_cannot_validate_its_own_package
        """
        fx.set_clock(api, PACKAGE_CLOCK)
        setup = fx.rx_submission_with_secured_vendor(api, covered_lives=6000)
        vendor_id = setup["pbm_vendor"]["id"]
        package_id = setup["package"]["id"]
        fx.delivered_package(api, package_id, vendor_id, **DELIVERED_FIGURES)

        validate_error(
            api.validate_package(package_id, make_vendor_contact_headers(vendor_id)),
            ApiErrorId.FORBIDDEN_ROLE,
            expected_status=403,
        )

        held = validate_success(
            api.get_vendor_data_package(package_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert held["status"] == PACKAGE_RECEIVED
        assert held["validated_at"] is None

        submission = validate_success(
            api.get_rx_submission(setup["submission"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert submission["status"] == RX_ASSEMBLING
        assert submission["assembled_record_count"] == 0


class TestVendorIdentityScoping:
    """The one entity-backed role, and its two distinct failures."""

    def test_one_vendor_cannot_deliver_another_vendors_package(
        self, api: ApiClient
    ) -> None:
        """The broker's own missing data rights never even get looked at.

        PRD 2.1: "If the addressed contract, amendment or data package belongs to
        a different vendor, the request is refused with
        `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403) — the role is permitted on the
        endpoint, but the row is not the caller's."

        PRD 2.9: "**Vendor scope.** A `VendorContact` may act only on rows whose
        owning `vendor_id` equals `X-User-ID`. This applies to gag-remediation
        submission, amendment counter, package delivery and package resubmission
        — four operations. Cross-vendor access is refused with
        `ERR_VENDOR_SCOPE_VIOLATION` (403) even though the role itself is
        permitted on the endpoint."

        Design: Corner/rbac/vendor_contact_cross_vendor_delivery_forbidden
        """
        fx.set_clock(api, PACKAGE_CLOCK)
        setup = fx.rx_submission_with_secured_vendor(api, covered_lives=6000)
        package_id = setup["package"]["id"]
        broker = fx.add_contract_for_vendor_type(
            api,
            setup["plan_year"]["id"],
            VENDOR_TYPE_BROKER,
            annual_fee_cents=2_400_000,
        )

        validate_error(
            api.deliver_package(
                package_id,
                f.deliver_package_payload(**DELIVERED_FIGURES),
                make_vendor_contact_headers(broker["vendor"]["id"]),
            ),
            ApiErrorId.VENDOR_SCOPE_VIOLATION,
            expected_status=403,
        )

        held = validate_success(
            api.get_vendor_data_package(package_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert held["status"] == PACKAGE_EXPECTED
        assert held["delivery_round"] == 0

        delivered = validate_success(
            api.deliver_package(
                package_id,
                f.deliver_package_payload(**DELIVERED_FIGURES),
                make_vendor_contact_headers(setup["pbm_vendor"]["id"]),
            )
        )
        assert delivered["status"] == PACKAGE_RECEIVED
        assert delivered["delivery_round"] == 1

    def test_a_vendor_identity_matching_no_registered_vendor_is_a_mismatch(
        self, api: ApiClient
    ) -> None:
        """A bogus identity fails differently from a real but foreign one.

        PRD 2.1: "If instead the presented `X-User-ID` does not resolve to any
        registered vendor at all, the request is refused with
        `ERR_ROLE_ENTITY_MISMATCH` (HTTP 403)."

        PRD 2.1: "When `X-User-Role` is `VendorContact`, `X-User-ID` is the `id`
        of the acting `Vendor` row; ownership checks on any resource that
        references a vendor compare that resource's `vendor_id` to `X-User-ID`."

        Design: Corner/rbac/vendor_contact_identity_not_a_vendor_rejected
        """
        fx.set_clock(api, VENDOR_READ_CLOCK)
        vendor = fx.create_pbm_vendor(api)

        validate_error(
            api.get_vendor(
                vendor["id"], make_vendor_contact_headers(UNKNOWN_VENDOR_USER_ID)
            ),
            ApiErrorId.ROLE_ENTITY_MISMATCH,
            expected_status=403,
        )

        seen = validate_success(
            api.get_vendor(vendor["id"], make_vendor_contact_headers(vendor["id"]))
        )
        assert seen["legal_name"] == f.PBM_LEGAL_NAME
        assert seen["id"] == vendor["id"]


class TestSegregationOfDuties:
    """Two identifiers inside one workflow must not be the same person."""

    def test_a_preparer_cannot_sign_off_on_their_own_attestation(
        self, api: ApiClient
    ) -> None:
        """A second officer signs the identical record without complaint.

        PRD 2.1: "Beyond role and ownership, the attestation workflow enforces a
        segregation-of-duties rule that no role assignment can satisfy on its
        own: the `X-User-ID` submitting an attestation must differ from the
        attestation's `prepared_by_user_id`, and the auditor accepting or
        rejecting it must differ from both `prepared_by_user_id` and
        `submitted_by_user_id`."

        Design: Corner/rbac/preparer_cannot_submit_own_attestation
        """
        setup = _attestation_prepared_by(api, OFFICER_PREPARER_HEADERS)
        attestation_id = setup["attestation"]["id"]
        assert setup["attestation"]["prepared_by_user_id"] == OFFICER_PREPARER_USER_ID

        validate_error(
            api.submit_attestation(
                attestation_id,
                f.submit_attestation_payload(),
                OFFICER_PREPARER_HEADERS,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        held = validate_success(
            api.get_attestation(attestation_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert held["status"] == ATTESTATION_DRAFT
        assert held["submitted_by_user_id"] is None

        submitted = validate_success(
            api.submit_attestation(
                attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )
        assert submitted["status"] == ATTESTATION_SUBMITTED
        assert submitted["submitted_by_user_id"] == OFFICER_SIGNER_USER_ID

        plan_year = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert plan_year["attestation_status"] == ATTESTATION_SUBMITTED

    def test_changing_role_does_not_let_a_preparer_adjudicate_their_own_work(
        self, api: ApiClient
    ) -> None:
        """The check compares user identifiers, so a second hat does not help.

        PRD 2.1: "Beyond role and ownership, the attestation workflow enforces a
        segregation-of-duties rule that no role assignment can satisfy on its
        own: the `X-User-ID` submitting an attestation must differ from the
        attestation's `prepared_by_user_id`, and the auditor accepting or
        rejecting it must differ from both `prepared_by_user_id` and
        `submitted_by_user_id`."

        PRD 2.1: "Any breach is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        Design: Corner/rbac/auditor_cannot_accept_an_attestation_they_prepared
        """
        setup = _attestation_prepared_by(api, DUAL_ROLE_OFFICER_HEADERS)
        attestation_id = setup["attestation"]["id"]
        validate_success(
            api.submit_attestation(
                attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )

        validate_error(
            api.accept_attestation(
                attestation_id,
                DUAL_ROLE_AUDITOR_HEADERS,
                f.accept_attestation_payload(),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        held = validate_success(
            api.get_attestation(attestation_id, EXTERNAL_AUDITOR_HEADERS)
        )
        assert held["status"] == ATTESTATION_SUBMITTED

        accepted = validate_success(
            api.accept_attestation(
                attestation_id,
                EXTERNAL_AUDITOR_HEADERS,
                f.accept_attestation_payload(),
            )
        )
        assert accepted["status"] == ATTESTATION_ACCEPTED

        plan_year = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert plan_year["attestation_status"] == ATTESTATION_ACCEPTED
        assert plan_year["deficiency_points"] == 0


class TestSharedReadOperations:
    """Some reads are shared by the three business roles and by no one else."""

    def test_three_business_roles_read_the_contract_roster_identically(
        self, api: ApiClient
    ) -> None:
        """The automation identity, holding no judgement, is refused outright.

        PRD 2.1: "It holds no business judgement authority whatsoever: it cannot
        review contracts, assess disclosures, certify cycles, or touch
        attestations."

        PRD 2.1: "When `X-User-Role` is absent, holds a value that is not a
        recognised role, or holds a recognised role that is not listed for the
        addressed endpoint in §4, the request is refused with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/shared_read_operations_available_to_peer_roles
        """
        fx.set_clock(api, VENDOR_READ_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        params = {"plan_year_id": plan_year_id}

        seen = []
        for headers in (
            SPONSOR_ADMIN_HEADERS,
            COMPLIANCE_OFFICER_HEADERS,
            EXTERNAL_AUDITOR_HEADERS,
        ):
            rows, meta = validate_paginated(api.list_contracts(headers, params=params))
            assert meta["total_count"] == 1
            assert meta["has_more"] is False
            assert rows[0]["id"] == setup["tpa_contract"]["id"]
            seen.append(rows)
        assert seen[0] == seen[1] == seen[2]

        validate_error(
            api.list_contracts(PLATFORM_OPERATOR_HEADERS, params=params),
            ApiErrorId.FORBIDDEN_ROLE,
            expected_status=403,
        )


class TestErrorEnvelope:
    """The shape of a refusal, and the two checks that precede every other one."""

    def test_a_domain_refusal_carries_only_an_identifier_and_a_message(
        self, api: ApiClient
    ) -> None:
        """No half-written entity leaks out beside the error.

        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_domain_error
        """
        fx.set_clock(api, REGISTRY_CLOCK)
        fx.create_plan_year(api, covered_lives=6000)

        response = api.create_plan_year(
            f.plan_year_payload(covered_lives=6000), SPONSOR_ADMIN_HEADERS
        )
        body = validate_error(
            response, ApiErrorId.DUPLICATE_PLAN_YEAR_LABEL, expected_status=409
        )
        assert isinstance(body["message"], str)
        assert body["message"].strip()
        for entity_field in ENTITY_FIELDS:
            assert entity_field not in body

        envelope = response.json()
        assert envelope["response_type"] == "error"
        assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}

    def test_an_empty_caller_identifier_is_refused_before_the_role_is_read(
        self, api: ApiClient
    ) -> None:
        """The role header is perfectly valid, and it is still a 401.

        PRD 2.1: "When `X-User-ID` is absent or present but empty, the request is
        refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD 2.9: "**Authentication.** `X-User-ID` present and non-empty, on every
        endpoint — otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/missing_x_user_id_returns_unauthenticated
        """
        fx.set_clock(api, REGISTRY_CLOCK)
        plan_year = fx.create_plan_year(api, covered_lives=6000)

        body = validate_error(
            api.get_plan_year(
                plan_year["id"], headers_without_user_id(ROLE_PLAN_SPONSOR_ADMIN)
            ),
            ApiErrorId.UNAUTHENTICATED,
            expected_status=401,
        )
        assert body["error_id"] != ApiErrorId.FORBIDDEN_ROLE

        seen = validate_success(
            api.get_plan_year(plan_year["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert seen["plan_year_label"] == f.DEFAULT_PLAN_YEAR_LABEL

    def test_an_action_on_an_unknown_plan_year_is_a_404_not_a_precondition(
        self, api: ApiClient
    ) -> None:
        """There is no row to be missing a TPA contract in the first place.

        PRD 2.9: "**Path existence.** Every `{id}` path parameter resolves to an
        existing row of the addressed collection, on every endpoint that carries
        one — otherwise the entity-specific 404: `ERR_PLAN_YEAR_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AMENDMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
        `ERR_MRF_NOT_FOUND`, `ERR_REFRESH_CYCLE_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`,
        `ERR_RX_SUBMISSION_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`,
        `ERR_ATTESTATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or
        `ERR_REMEDIATION_PLAN_NOT_FOUND`."

        PRD 2.9: "**TPA contract present.** On plan year activation only: at
        least one service provider contract of the plan year has `contract_type`
        `TPA`, otherwise `ERR_TPA_CONTRACT_REQUIRED` (409)."

        Design: Corner/errors/unknown_plan_year_on_action_endpoint_not_found
        """
        fx.set_clock(api, REGISTRY_CLOCK)

        body = validate_error(
            api.activate_plan_year(NON_EXISTENT_UUID, SPONSOR_ADMIN_HEADERS),
            ApiErrorId.PLAN_YEAR_NOT_FOUND,
            expected_status=404,
        )
        assert body["error_id"] != ApiErrorId.TPA_CONTRACT_REQUIRED

        rows, meta = validate_paginated(api.list_plan_years(COMPLIANCE_OFFICER_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0
