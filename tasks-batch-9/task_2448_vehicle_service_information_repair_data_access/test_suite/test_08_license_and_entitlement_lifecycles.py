"""License and entitlement lifecycles: valid moves, preconditions, terminal states.

Covers the activation transition and its version bump, the license state a
pending entitlement reads at activation time, the lockdown that follows
termination, the zero-day exit arm, and the initial state of freshly created rows.
"""

import pytest

from test_helpers import (
    CONTENT_PUBLISHER_1_USER_ID,
    ApiErrorId,
    DistributionStatus,
    EntitlementStatus,
    IdentityStatus,
    LicenseModel,
    LicenseStatus,
    ReviewStatus,
    SettlementStatus,
    assert_entitlement,
    assert_license,
    assert_publication_version,
    factories,
    fixtures,
    make_content_publisher_headers,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _license_row(api, manufacturer_id, license_id, headers, params=None):
    rows, _meta = validate_paginated(
        api.list_manufacturer_licenses(
            manufacturer_id, headers, dict(params or {}, limit=100)
        )
    )
    return next(row for row in rows if row["id"] == license_id)


class TestLicenseActivationTransition:
    """DRAFT to ACTIVE is a plain versioned move on a compliant OEM."""

    def test_activating_a_draft_license_advances_status_and_version(self, api):
        """The activate call answers ACTIVE at version 2 with no suspension reason.

        PRD 3.2: "A successful activation sets the status to `ACTIVE` and advances
        the license's `version` by 1", the parity gate passes because "the granting
        OEM's stored `parity_status` must read `COMPLIANT`", and a freshly drafted
        license "opens in `DRAFT` with its `suspension_reason` null".

        Design: Corner/state_machines/license_draft_to_active_valid_transition
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_license(
            api, ctx, activate=False, covered_area_codes=("POWERTRAIN",)
        )
        drafted = ctx["license"]
        assert drafted["status"] == LicenseStatus.DRAFT
        assert drafted["version"] == 1

        activated = validate_success(
            api.activate_license(drafted["id"], make_platform_admin_headers())
        )

        assert_license(activated)
        assert activated["status"] == LicenseStatus.ACTIVE
        assert activated["version"] == 2
        assert activated["suspension_reason"] is None

        rows, meta = validate_paginated(
            api.list_manufacturer_licenses(
                ctx["manufacturer"]["id"],
                make_platform_admin_headers(),
                {"status": LicenseStatus.ACTIVE},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == drafted["id"]


class TestEntitlementActivationReadsLicenseState:
    """The license is re-read at activation time, not remembered from purchase."""

    def test_a_suspended_license_blocks_activation_and_keeps_the_charge(self, api):
        """The pending entitlement is refused and its debit is left untouched.

        PRD 3.2: what suspension blocks "is new business — buying a new entitlement
        against this license, and activating a `PENDING` one, are both refused with
        `ERR_LICENSE_NOT_ACTIVE` (HTTP 409)", and suspension "stamps the supplied
        `reason` into `suspension_reason`". PRD 3.4 requires of activation "that its
        license is still `ACTIVE`".

        Design: Corner/state_machines/entitlement_activate_under_suspended_license_precondition_enforced
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), activate_entitlement=False
        )
        suspended = validate_success(
            api.suspend_license(
                ctx["license"]["id"],
                factories.reason_payload("OEM_AUDIT"),
                make_platform_admin_headers(),
            )
        )
        assert suspended["status"] == LicenseStatus.SUSPENDED
        assert suspended["suspension_reason"] == "OEM_AUDIT"

        validate_error(
            api.activate_entitlement(
                ctx["entitlement"]["id"], ctx["manager_headers"]
            ),
            ApiErrorId.LICENSE_NOT_ACTIVE,
            409,
        )

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert entitlement["status"] == EntitlementStatus.PENDING
        assert entitlement["charged_cents"] == 85000
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 115000


class TestTerminatedLicenseIsTerminal:
    """After termination every remaining trigger is refused."""

    def test_no_trigger_reopens_a_terminated_license(self, api):
        """Activate, suspend and terminate all return ERR_INVALID_STATE.

        PRD 3.2: a license lives through four states, "`DRAFT`, `ACTIVE`,
        `SUSPENDED` and `TERMINATED`, the last of which is terminal — and moves
        between them only through the transitions described below; any other
        attempt yields `ERR_INVALID_STATE`". The terminate call has already written
        its `reason` to `suspension_reason`.

        Design: Corner/state_machines/license_terminated_is_terminal_no_reactivation
        """
        ctx = fixtures.build_licensed_catalogue(
            api, area_codes=("POWERTRAIN",), covered_area_codes=("POWERTRAIN",)
        )
        admin = make_platform_admin_headers()
        license_id = ctx["license"]["id"]
        terminated = validate_success(
            api.terminate_license(
                license_id, factories.reason_payload("OEM_EXIT"), admin
            )
        )
        assert terminated["status"] == LicenseStatus.TERMINATED
        version_after_termination = terminated["version"]

        validate_error(
            api.activate_license(license_id, admin), ApiErrorId.INVALID_STATE, 409
        )
        validate_error(
            api.suspend_license(
                license_id, factories.reason_payload("SECOND_THOUGHTS"), admin
            ),
            ApiErrorId.INVALID_STATE,
            409,
        )
        validate_error(
            api.terminate_license(license_id, factories.reason_payload("AGAIN"), admin),
            ApiErrorId.INVALID_STATE,
            409,
        )

        stored = _license_row(api, ctx["manufacturer"]["id"], license_id, admin)
        assert stored["status"] == LicenseStatus.TERMINATED
        assert stored["suspension_reason"] == "OEM_EXIT"
        assert stored["version"] == version_after_termination


class TestCancellingBeforeTheWindowOpens:
    """The zero-elapsed-day arm settles at nothing and refunds everything."""

    def test_cancelling_a_pending_entitlement_refunds_the_whole_charge(self, api):
        """Zero elapsed days settle at 0 and the balance returns to the funded total.

        PRD 3.4: "Cancelling from `PENDING` follows the identical path, and because
        a window that has not started yields zero elapsed days, `settled_cents`
        comes out at 0 and the shop receives a full refund", with "the refund is
        added to the shop's `data_credit_balance_cents`" and `settlement_status`
        becoming `SETTLED`.

        Design: Corner/state_machines/entitlement_cancel_from_pending_yields_zero_settlement_full_refund
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), activate_entitlement=False
        )

        cancelled = validate_success(
            api.cancel_entitlement(
                ctx["entitlement"]["id"],
                factories.reason_payload("BOUGHT_IN_ERROR"),
                ctx["manager_headers"],
            )
        )

        assert_entitlement(cancelled)
        assert cancelled["status"] == EntitlementStatus.CANCELLED
        assert cancelled["charged_cents"] == 85000
        assert cancelled["settled_cents"] == 0
        assert cancelled["settlement_status"] == SettlementStatus.SETTLED

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 200000
        assert shop["funded_credit_total_cents"] == 200000
        assert shop["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)


class TestInitialStates:
    """Four freshly created rows each open in their declared initial state."""

    def test_every_new_row_opens_in_its_declared_initial_state(self, api):
        """License DRAFT, technician UNVERIFIED, entitlement PENDING, version DRAFT.

        PRD 3.2: "A freshly drafted license opens in `DRAFT` with its
        `suspension_reason` null." PRD 3.5: "a new technician opens in
        `identity_status` of `UNVERIFIED`". PRD 3.3: "the new entitlement opens with
        `status` of `PENDING`, `settlement_status` of `UNSETTLED`, `settled_cents`
        of 0, `seats_assigned` of 0". PRD 3.6: "The new version opens with
        `review_status` of `DRAFT`, `distribution_status` of `WITHHELD`,
        `validated_by_user_id` and `published_by_user_id` both null, and
        `active_pin_count` at 0", beneath a publication whose `current_version_no`
        starts at 0 with `published_version_id` null.

        Design: Corner/state_machines/initial_state_sweep_license_draft_technician_unverified_entitlement_pending
        """
        ctx = fixtures.build_funded_shop(api, covered_area_codes=("POWERTRAIN",))
        admin = make_platform_admin_headers()
        author = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)

        second_license = validate_success(
            api.create_license(
                factories.license_payload(
                    ctx["manufacturer"]["id"],
                    fixtures.area_ids(ctx, ("POWERTRAIN",)),
                    license_model=LicenseModel.PER_VEHICLE,
                ),
                admin,
            ),
            201,
        )
        assert second_license["status"] == LicenseStatus.DRAFT
        assert second_license["suspension_reason"] is None

        technician = validate_success(
            api.create_technician(
                factories.technician_payload(ctx["shop"]["id"]), ctx["manager_headers"]
            ),
            201,
        )
        assert technician["identity_status"] == IdentityStatus.UNVERIFIED

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                ctx["manager_headers"],
            ),
            201,
        )
        assert_entitlement(entitlement)
        assert entitlement["status"] == EntitlementStatus.PENDING
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED
        assert entitlement["seats_assigned"] == 0
        assert entitlement["settled_cents"] == 0

        publication = validate_success(
            api.create_publication(
                factories.publication_payload(
                    ctx["vehicle_model"]["id"], ctx["areas"]["POWERTRAIN"]["id"]
                ),
                author,
            ),
            201,
        )
        read_back = validate_success(api.get_publication(publication["id"], author))
        assert read_back["current_version_no"] == 0
        assert read_back["published_version_id"] is None

        version = validate_success(
            api.create_publication_version(
                publication["id"],
                factories.publication_version_payload(read_back["version"]),
                author,
            ),
            201,
        )
        assert_publication_version(version)
        assert version["version_no"] == 1
        assert version["review_status"] == ReviewStatus.DRAFT
        assert version["distribution_status"] == DistributionStatus.WITHHELD
        assert version["active_pin_count"] == 0
        assert version["validated_by_user_id"] is None
        assert version["published_by_user_id"] is None
