"""Role boundaries, peer isolation, and the two segregation-of-duties pairs.

Telemetry ingest belongs to the device-side identity alone.  The technician's
hold test and the carrier's finalize cannot be swapped.  A homeowner is a peer
role scoped to its own account.  And two operator identities recorded earlier in
a claim's life are compared against the acting one before money moves.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    claim_decision_payload,
    telemetry_payload,
    verify_install_payload,
)
from test_helpers.fixtures import (
    approve_claim,
    begin_claim_review,
    create_buyer,
    file_claim,
    finalize_attestation,
    ingest_quiet_reading,
    open_attestation,
    pay_claim,
    read_attestation_list,
    read_claim,
    read_device,
    read_policy,
    read_property,
    read_telemetry,
    set_clock,
    setup_armed_device,
    setup_armed_device_with_policy,
    setup_second_registered_device,
    verify_install,
)
from test_helpers.test_users import (
    ADJUSTER_USER_ID,
    GATEWAY_USER_ID,
    INSTALLER_TECH_USER_ID,
    INSURER_ANALYST_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    make_claims_adjuster_headers,
    make_gateway_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_insurer_analyst_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers(PROGRAM_ADMIN_USER_ID)
ANALYST = make_insurer_analyst_headers(INSURER_ANALYST_USER_ID)
GATEWAY = make_gateway_headers(GATEWAY_USER_ID)
INSTALLER = make_installer_tech_headers(INSTALLER_TECH_USER_ID)
POLICY_YEAR_START = "2026-08-01T00:00:00Z"
INGEST_AT = "2026-08-01T06:10:00Z"
QUIET_SAMPLE = telemetry_payload(INGEST_AT, 60.0, 0.0, 0, 0.0)


def _an_armed_device_with_three_readings(api: ApiClient) -> dict:
    """The clock is moved to the ingest instant so only the role can differ."""
    state = setup_armed_device(api)
    assert len(read_telemetry(api, state["device_id"])) == 3
    set_clock(api, INGEST_AT)
    return state


class TestTelemetryIngestBelongsToTheGatewayAlone:
    def test_neither_the_owner_nor_the_admin_may_write_a_reading(
        self, api: ApiClient
    ):
        """Ownership and breadth of support powers are both irrelevant here.

        "A `DeviceGateway` is the device-side ingest identity and the only principal in the
        system permitted to write telemetry."
        "Once authentication passes, the second gate is role permission: if the acting
        `X-User-Role` is not listed among the authorised roles for the endpoint in §4, the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/only_device_gateway_may_ingest_telemetry
        """
        state = _an_armed_device_with_three_readings(api)

        validate_error(
            api.create_telemetry_reading(
                state["device_id"],
                dict(QUIET_SAMPLE),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_telemetry_reading(
                state["device_id"], dict(QUIET_SAMPLE), ADMIN
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        assert len(read_telemetry(api, state["device_id"])) == 3
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T00:40:00"
        )

    def test_the_identical_body_from_the_gateway_is_accepted(self, api: ApiClient):
        """Only the role changed between the refusals and this acceptance.

        "This exclusivity is deliberate: no human role can fabricate uptime coverage or
        manufacture an anomaly."
        "They may act on a homeowner's behalf for support operations, but they cannot write
        telemetry, cannot verify an install, and cannot make the carrier's policy or
        claim-decision calls."

        Design: Corner/rbac/only_device_gateway_may_ingest_telemetry
        """
        state = _an_armed_device_with_three_readings(api)
        validate_error(
            api.create_telemetry_reading(
                state["device_id"], dict(QUIET_SAMPLE), ADMIN
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        accepted = ingest_quiet_reading(api, state["device_id"], INGEST_AT)
        assert accepted["reading_at"].startswith("2026-08-01T06:10:00")

        readings, meta = validate_paginated(
            api.list_telemetry_readings(state["device_id"], GATEWAY)
        )
        assert meta["total_count"] == 4
        assert len(readings) == 4
        assert read_device(api, state["device_id"])["last_reading_at"].startswith(
            "2026-08-01T06:10:00"
        )


FIRST_PERIOD = ("2026-08-01T00:00:00Z", "2026-08-01T04:00:00Z")


def _one_finalizable_period(api: ApiClient) -> dict:
    """The period ended at 04:00, so the 06:05 clock may already finalize it."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    state["attestation"] = open_attestation(api, state["policy_id"], *FIRST_PERIOD)
    state["attestation_id"] = state["attestation"]["id"]
    return state


class TestTheInstallerAndTheAnalystCannotSwapExclusiveVerbs:
    def test_each_role_is_refused_on_the_other_s_exclusive_operation(
        self, api: ApiClient
    ):
        """The role gate runs before any state precondition on either call.

        "Install verification is the technician's sign-off and the only operation in the system
        reserved exclusively to `InstallerTech`."
        "An `InsurerAnalyst` is carrier-side."

        Design: Corner/rbac/installer_and_analyst_cannot_swap_exclusive_operations
        """
        state = _one_finalizable_period(api)
        state["second_device_id"] = setup_second_registered_device(api, state)["id"]

        validate_error(
            api.finalize_credit_attestation(state["attestation_id"], {}, INSTALLER),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.verify_install(
                state["second_device_id"], verify_install_payload(), ANALYST
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        rows = read_attestation_list(api, state["policy_id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["finalized_at"] is None

        second = read_device(api, state["second_device_id"])
        assert second["lifecycle_state"] == "REGISTERED"
        assert second["install_verified_by_user_id"] is None
        assert second["install_verified_at"] is None

    def test_the_same_bodies_from_the_right_roles_both_succeed(self, api: ApiClient):
        """Nothing but the acting role stood between refusal and acceptance.

        "It records `install_verified_by_user_id` as the acting technician's `X-User-ID` and
        `install_verified_at` as the current logical clock, persists the submitted
        `installed_static_pressure_psi` onto the device, and advances `lifecycle_state` through
        `REGISTERED → INSTALL_VERIFIED → LEARNING` inside the single request — the intermediate
        state is real and enumerable, but no client action sits between the two hops."
        "A denial moves the attestation `OPEN → FINALIZED_DENIED` and writes `covered_minutes`,
        `uptime_pct`, `offline_gap_count`, `denial_reason`, and `finalized_at`, leaving
        `credit_cents_awarded` at 0 and `tier_pct` at 0."

        Design: Corner/rbac/installer_and_analyst_cannot_swap_exclusive_operations
        """
        state = _one_finalizable_period(api)

        # The carrier's own verb lands on the period the technician could not touch.
        scored = finalize_attestation(api, state["attestation_id"])
        assert scored["status"] == "FINALIZED_DENIED"
        assert scored["denial_reason"] == "UPTIME_BELOW_FLOOR"
        assert scored["finalized_at"].startswith("2026-08-01T06:05:00")
        assert scored["credit_cents_awarded"] == 0

        second_device_id = setup_second_registered_device(api, state)["id"]
        validate_error(
            api.verify_install(second_device_id, verify_install_payload(), ANALYST),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        verified = verify_install(api, second_device_id)
        assert verified["lifecycle_state"] == "LEARNING"
        assert verified["install_verified_by_user_id"] == INSTALLER_TECH_USER_ID
        assert verified["install_verified_at"].startswith("2026-08-01T06:05:00")


def _a_second_household_with_nothing_of_its_own(api: ApiClient) -> dict:
    """A valid Homeowner role holder who owns no property at all."""
    state = setup_armed_device(api)
    peer = create_buyer(api)
    state["peer_id"] = peer["id"]
    state["peer_headers"] = make_homeowner_headers(peer["id"])
    return state


class TestHomeownerIsScopedToItsOwnAccount:
    def test_a_peer_homeowner_is_refused_on_property_device_and_telemetry(
        self, api: ApiClient
    ):
        """The role is authorised on all three endpoints; the resource is not theirs.

        "A `Homeowner` acting on a resource whose resolved owner is a different homeowner is
        refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        "The resolution walk is transitive — a property resolves to its `homeowner_id`, a
        device resolves through its property, an anomaly event or telemetry reading resolves
        through its device, an escalation ticket through its event, a policy through its
        property, and a claim through the homeowner recorded as its submitter."

        Design: Corner/rbac/homeowner_cannot_read_another_accounts_property
        """
        state = _a_second_household_with_nothing_of_its_own(api)
        peer = state["peer_headers"]

        validate_error(
            api.get_property(state["property_id"], peer),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.get_device(state["device_id"], peer),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.list_telemetry_readings(state["device_id"], peer),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

    def test_the_admin_reads_what_the_peer_cannot_and_the_peer_owns_nothing(
        self, api: ApiClient
    ):
        """The refusal follows the resource rather than the endpoint shape.

        "**Ownership scoping** — a `Homeowner` may act only within their own account:
        `ERR_NOT_RESOURCE_OWNER` (403)."
        "That count is not a stored tally the client maintains; it is derived on read as the
        number of properties whose owner is this account and whose `property_state` is either
        `ACTIVE` or `TRANSFER_PENDING` — a property that has been archived stops counting."

        Design: Corner/rbac/homeowner_cannot_read_another_accounts_property
        """
        state = _a_second_household_with_nothing_of_its_own(api)
        validate_error(
            api.get_property(state["property_id"], state["peer_headers"]),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

        assert read_property(api, state["property_id"])["property_state"] == "ACTIVE"
        _, meta = validate_paginated(
            api.list_homeowner_properties(state["peer_id"], state["peer_headers"])
        )
        assert meta["total_count"] == 0


WARRANTY_LOSS_CENTS = 90000


def _a_warranty_claim_under_review(api: ApiClient) -> dict:
    """The device was certified by tech-01 and adj-01 opened the review."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    claim = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WARRANTY_DEVICE",
        WARRANTY_LOSS_CENTS,
        state["homeowner_id"],
    )
    state["claim_id"] = claim["id"]
    state["claim"] = begin_claim_review(api, state["claim_id"], ADJUSTER_USER_ID)
    return state


def _attempt_decision(api: ApiClient, claim_id: str, decision: str, headers):
    return api.decide_claim(claim_id, claim_decision_payload(decision), headers)


class TestSegregationOfDutiesBlocksTwoDifferentIdentityPairs:
    def test_the_certifying_technician_may_not_approve_the_warranty_payout(
        self, api: ApiClient
    ):
        """The acting identifier collides with the one recorded on the device.

        "Approving a warranty claim requires that the acting `X-User-ID` differ from the
        `install_verified_by_user_id` recorded on the device the claim names — the technician
        who certified the installation cannot later bless a hardware-failure payout on it."
        "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/same_user_cannot_verify_then_approve_nor_approve_then_pay
        """
        state = _a_warranty_claim_under_review(api)
        assert (
            read_device(api, state["device_id"])["install_verified_by_user_id"]
            == INSTALLER_TECH_USER_ID
        )

        validate_error(
            _attempt_decision(
                api,
                state["claim_id"],
                "APPROVE",
                make_claims_adjuster_headers(INSTALLER_TECH_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        claim = read_claim(api, state["claim_id"])
        assert claim["status"] == "UNDER_REVIEW"
        assert claim["decided_by_user_id"] is None
        assert claim["approved_payout_cents"] == 0
        assert claim["payout_variant"] is None

    def test_a_different_adjuster_in_the_same_role_approves_the_flat_warranty(
        self, api: ApiClient
    ):
        """Only the operator identifier changed, and the payout is the flat form.

        "Under `WARRANTY_FLAT`, `deductible_applied_cents` is 0 and `approved_payout_cents` is
        the smaller of `documented_loss_cents` and a warranty cap of 150000 cents."
        "A `WARRANTY_DEVICE` claim may omit it, and when it does the payout takes the flat
        warranty form regardless of any mitigation history."

        Design: Corner/rbac/same_user_cannot_verify_then_approve_nor_approve_then_pay
        """
        state = _a_warranty_claim_under_review(api)
        validate_error(
            _attempt_decision(
                api,
                state["claim_id"],
                "APPROVE",
                make_claims_adjuster_headers(INSTALLER_TECH_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        approved = approve_claim(api, state["claim_id"], SECOND_ADJUSTER_USER_ID)
        assert approved["status"] == "APPROVED"
        assert approved["payout_variant"] == "WARRANTY_FLAT"
        assert approved["approved_payout_cents"] == WARRANTY_LOSS_CENTS
        assert approved["deductible_applied_cents"] == 0
        assert approved["decided_by_user_id"] == SECOND_ADJUSTER_USER_ID
        # The policy's own deductible of 100000 cents is deliberately not applied.
        assert read_policy(api, state["policy_id"])["deductible_cents"] == 100000

    def test_the_approving_adjuster_may_not_disburse_what_they_approved(
        self, api: ApiClient
    ):
        """The second pair compares the payer against the recorded decider.

        "Paying a claim requires that the acting `X-User-ID` differ from the
        `decided_by_user_id` recorded when the claim was approved — the adjuster who approved a
        payout cannot also disburse it."
        "It re-checks the annual cap against `approved_payout_cents`, refuses when the paying
        `X-User-ID` equals the recorded `decided_by_user_id`, and on success stamps `paid_at` at
        the clock, moves the claim `APPROVED → PAID`, and increases the policy's
        `paid_payout_cents_total` by `approved_payout_cents` along with the policy's `version`."

        Design: Corner/rbac/same_user_cannot_verify_then_approve_nor_approve_then_pay
        """
        state = _a_warranty_claim_under_review(api)
        approve_claim(api, state["claim_id"], SECOND_ADJUSTER_USER_ID)

        # The correct payer role is not enough when the identifier collides.
        validate_error(
            _attempt_decision(
                api,
                state["claim_id"],
                "PAY",
                make_insurer_analyst_headers(SECOND_ADJUSTER_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert read_claim(api, state["claim_id"])["status"] == "APPROVED"
        assert read_policy(api, state["policy_id"])["paid_payout_cents_total"] == 0

        paid = pay_claim(api, state["claim_id"])
        assert paid["status"] == "PAID"
        assert paid["paid_at"].startswith("2026-08-01T06:05:00")
        assert (
            read_policy(api, state["policy_id"])["paid_payout_cents_total"]
            == WARRANTY_LOSS_CENTS
        )
