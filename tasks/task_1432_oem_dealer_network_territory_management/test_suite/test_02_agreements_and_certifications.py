"""Dealer agreements, certification gates, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    activate_agreement,
    assert_agreement,
    assert_certification,
    create_agreement,
    create_agreement_payload,
    create_and_verify_certification,
    create_dealer,
    register_certification,
    setup_active_dealer,
    validate_error,
    validate_success,
    verify_certification,
)


class TestCertificationGate:
    """Activation requires at least two ACTIVE certifications (PRD 3.1)."""

    def test_activation_with_fewer_than_two_certs_rejected(
            self, api, oem_admin_headers):
        """PRD section 3.1: "Activating a dealer agreement requires the dealer to hold **at least two** certifications in `ACTIVE` status; an activation attempt with fewer is rejected with `ERR_CERTIFICATION_COMPLIANCE`."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_certifications
        """
        dealer = create_dealer("DL-M1", name="Dealer M1")
        create_and_verify_certification(dealer["id"], "CTE-M1")
        agreement = create_agreement(dealer["id"], "AGR-M1")

        resp = api.activate_agreement(
            agreement["id"],
            {"expected_dealer_version": dealer["version"]},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_COMPLIANCE)

        # A rejected activation commits nothing: the same observed dealer
        # version must still be current when the activation is retried later.
        still = validate_success(api.get_dealer(dealer["id"],
                                                oem_admin_headers), 200)
        assert still["version"] == dealer["version"], (
            "failed activation must not advance Dealer.version: "
            f"{still['version']} != {dealer['version']}"
        )
        assert still["status"] == "ONBOARDING"

    def test_first_successful_activation_graduates_dealer(
            self, api, oem_admin_headers):
        """PRD section 3.1: "And when that first activation succeeds, the dealer itself graduates from `ONBOARDING` to `ACTIVE`, with `Dealer.version` incrementing as part of the same operation."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_certifications
        """
        dealer = create_dealer("DL-M2", name="Dealer M2")
        create_and_verify_certification(dealer["id"], "CTE-M1")
        agreement = create_agreement(dealer["id"], "AGR-M2")

        blocked = api.activate_agreement(
            agreement["id"],
            {"expected_dealer_version": dealer["version"]},
            oem_admin_headers,
        )
        validate_error(blocked, ApiErrorId.ERR_CERTIFICATION_COMPLIANCE)

        create_and_verify_certification(dealer["id"], "CTE-M2")
        activated = validate_success(
            api.activate_agreement(
                agreement["id"],
                {"expected_dealer_version": dealer["version"]},
                oem_admin_headers,
            ),
            200,
        )
        assert_agreement(activated)
        assert activated["status"] == "ACTIVE"

        dealer_after = validate_success(api.get_dealer(dealer["id"],
                                                       oem_admin_headers), 200)
        assert dealer_after["status"] == "ACTIVE"
        assert dealer_after["version"] == dealer["version"] + 1


class TestAgreementInputValidation:

    def test_invalid_agreement_date_range_rejected(self, api,
                                                   oem_admin_headers):
        """PRD section 3.2: "The commercial relationship is papered by a **DealerAgreement**, drafted by an `OemNetworkAdmin` with the target `dealer_id`, a unique `agreement_code` (duplicates rejected with `ERR_DUPLICATE_AGREEMENT_CODE`), an inclusive `effective_date`, and an inclusive `expiry_date` that must be strictly later than `effective_date` (`ERR_INVALID_DATE_RANGE`)."

        Design: Corner/validations/invalid_agreement_date_range_rejected
        """
        dealer = create_dealer("DL-DR1", name="Dealer DR1")
        resp = api.create_agreement(
            create_agreement_payload(
                dealer_id=dealer["id"], agreement_code="AGR-DR1",
                effective_date="2026-12-31", expiry_date="2026-01-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_duplicate_agreement_code_rejected(self, api, oem_admin_headers):
        """PRD section 3.2: "The commercial relationship is papered by a **DealerAgreement**, drafted by an `OemNetworkAdmin` with the target `dealer_id`, a unique `agreement_code` (duplicates rejected with `ERR_DUPLICATE_AGREEMENT_CODE`), an inclusive `effective_date`, and an inclusive `expiry_date` that must be strictly later than `effective_date` (`ERR_INVALID_DATE_RANGE`)."

        Design: Corner/validations/duplicate_agreement_code_rejected
        """
        dealer = create_dealer("DL-DG1", name="Dealer DG1")
        validate_success(
            api.create_agreement(
                create_agreement_payload(dealer_id=dealer["id"],
                                         agreement_code="AGR-DUP"),
                oem_admin_headers,
            ),
            expected_status=201,
        )
        resp = api.create_agreement(
            create_agreement_payload(
                dealer_id=dealer["id"], agreement_code="AGR-DUP",
                effective_date="2027-01-01", expiry_date="2027-12-31",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGREEMENT_CODE)


class TestAgreementStateMachine:

    def test_agreement_double_activate_rejected(self, api, oem_admin_headers):
        """PRD section 3.2: "The agreement must currently be `DRAFT` (`ERR_AGREEMENT_NOT_IN_DRAFT`); the request must carry `expected_dealer_version` matching the dealer's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` per §2.7; the dealer must be in `ONBOARDING` or `ACTIVE` status (`ERR_DEALER_NOT_ACTIVE`); the two-active-certification gate of §3.1 must pass (`ERR_CERTIFICATION_COMPLIANCE`); and the new agreement's inclusive date window must not collide with another `ACTIVE` agreement for the same dealer."

        Design: Corner/validations/agreement_double_activate_rejected
        """
        ctx = setup_active_dealer("DL-AD1", name="Dealer AD1")
        agreement = ctx["agreement"]
        fresh_version = ctx["dealer"]["version"]

        resp = api.activate_agreement(
            agreement["id"],
            {"expected_dealer_version": fresh_version},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_DRAFT)

        unchanged = validate_success(api.get_agreement(agreement["id"],
                                                       oem_admin_headers), 200)
        assert unchanged["status"] == "ACTIVE"

    def test_agreement_expire_before_expiry_rejected(self, api,
                                                     oem_admin_headers):
        """PRD section 3.2: "Once the current logical date has passed an `ACTIVE` agreement's `expiry_date`, an administrator may expire it into `EXPIRED`, which likewise releases its `ACTIVE` assignments and re-queues their leads; attempting expiry before that date is rejected with `ERR_AGREEMENT_NOT_YET_EXPIRED`, and expiry of a non-active agreement fails with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/validations/agreement_expire_before_expiry_rejected
        """
        ctx = setup_active_dealer("DL-AX1", name="Dealer AX1")
        agreement = ctx["agreement"]

        resp = api.expire_agreement(agreement["id"], oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_YET_EXPIRED)

        unchanged = validate_success(api.get_agreement(agreement["id"],
                                                       oem_admin_headers), 200)
        assert unchanged["status"] == "ACTIVE"


class TestAgreementInclusiveOverlap:
    """Agreement windows compare inclusively at both ends (PRD 3.2)."""

    def _setup_touching_agreements(self, api, oem_admin_headers):
        ctx = setup_active_dealer("DL-Q1", name="Dealer Q1")
        dealer = ctx["dealer"]
        second = create_agreement(
            dealer["id"], "AGR-Q2",
            effective_date="2026-12-31", expiry_date="2027-12-31")
        return ctx, second

    def test_touching_agreement_windows_count_as_overlap(
            self, api, oem_admin_headers):
        """PRD section 3.2: "On that last point, the comparison is **inclusive at both ends** — touching dates count as overlap. When an overlap exists, activation proceeds only if the caller sets `supersede_existing` to true, in which case the previously active overlapping agreement is moved to `SUPERSEDED` as part of the same operation; without that flag the activation is rejected with `ERR_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_activation_inclusive_overlap
        """
        ctx, second = self._setup_touching_agreements(api, oem_admin_headers)
        dealer = ctx["dealer"]

        resp = api.activate_agreement(
            second["id"],
            {"expected_dealer_version": dealer["version"],
             "supersede_existing": False},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)

        still_draft = validate_success(api.get_agreement(second["id"],
                                                         oem_admin_headers),
                                       200)
        assert still_draft["status"] == "DRAFT"
        first = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                   oem_admin_headers), 200)
        assert first["status"] == "ACTIVE"

    def test_supersede_existing_retires_overlapping_agreement(
            self, api, oem_admin_headers):
        """PRD section 3.2: "When an overlap exists, activation proceeds only if the caller sets `supersede_existing` to true, in which case the previously active overlapping agreement is moved to `SUPERSEDED` as part of the same operation; without that flag the activation is rejected with `ERR_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_activation_inclusive_overlap
        """
        ctx, second = self._setup_touching_agreements(api, oem_admin_headers)
        dealer = ctx["dealer"]

        activated = validate_success(
            api.activate_agreement(
                second["id"],
                {"expected_dealer_version": dealer["version"],
                 "supersede_existing": True},
                oem_admin_headers,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"

        first = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                   oem_admin_headers), 200)
        assert first["status"] == "SUPERSEDED", (
            "the previously active overlapping agreement must be SUPERSEDED, "
            f"got {first['status']}"
        )


class TestAgreementActivationOcc:

    def test_occ_stale_dealer_version_rejected(self, api, oem_admin_headers):
        """PRD section 2.7: "If the dealer's current `version` on the server does not match `expected_dealer_version` — because another writer has advanced the dealer's version since the client last read it, for instance by activating a different agreement that bumped the dealer's version and possibly superseded the previously active one — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change occurs."
        PRD section 3.2: "A successful activation moves the agreement to `ACTIVE`, increments `Dealer.version` by one, supersedes the displaced agreement when applicable, and — on the dealer's first activation — flips the dealer from `ONBOARDING` to `ACTIVE`."

        Design: Corner/cross_cutting_layers/occ_stale_dealer_version_rejected
        """
        # Capture the dealer's version as last observed BEFORE the first
        # agreement activation; activation then advances it, making the
        # captured value stale for the second activation.
        dealer = create_dealer("DL-OCC", name="Dealer OCC")
        create_and_verify_certification(dealer["id"], "CTE-OC1")
        create_and_verify_certification(dealer["id"], "CTE-OC2")
        first = create_agreement(dealer["id"], "AGR-OCC1")
        activate_agreement(first["id"], dealer["version"])
        stale_version = dealer["version"]

        second = create_agreement(
            dealer["id"], "AGR-OCC2",
            effective_date="2027-01-01", expiry_date="2027-12-31")

        resp = api.activate_agreement(
            second["id"],
            {"expected_dealer_version": stale_version},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_dealer(dealer["id"],
                                                oem_admin_headers), 200)
        assert fresh["version"] > stale_version, (
            "the first activation must have advanced Dealer.version"
        )

        activated = validate_success(
            api.activate_agreement(
                second["id"],
                {"expected_dealer_version": fresh["version"]},
                oem_admin_headers,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        after = validate_success(api.get_dealer(dealer["id"],
                                                oem_admin_headers), 200)
        assert after["version"] == fresh["version"] + 1, (
            "a successful activation increments Dealer.version by one"
        )


class TestCertificationStateMachine:

    def test_cert_verify_twice_rejected(self, api, auditor_headers,
                                        oem_admin_headers):
        """PRD section 3.1: "An `OemAuditor` then adjudicates it through a `decision`: a `decision` of `VERIFY` moves it to `ACTIVE`, while `REJECT` moves it to the terminal `REJECTED` state; either decision requires the certification to still be `PENDING_VERIFICATION` (`ERR_CERT_INVALID_STATE`)."

        Design: Corner/validations/cert_verify_twice_rejected
        """
        dealer = create_dealer("DL-CV1", name="Dealer CV1")
        cert = register_certification(dealer["id"], "CTE-CV1")
        verified = verify_certification(cert["id"])
        assert_certification(verified)
        assert verified["status"] == "ACTIVE"

        resp = api.decide_certification(cert["id"], {"decision": "VERIFY"},
                                        auditor_headers)
        validate_error(resp, ApiErrorId.ERR_CERT_INVALID_STATE)

        unchanged = validate_success(api.get_certification(cert["id"],
                                                           oem_admin_headers),
                                     200)
        assert unchanged["status"] == "ACTIVE"

    def test_cert_expire_before_expiry_rejected(self, api, auditor_headers,
                                                oem_admin_headers):
        """PRD section 3.1: "An auditor may also expire an `ACTIVE` certification once the current logical date has passed its `expires_on`, moving it to `EXPIRED`; attempting expiry too early is rejected with `ERR_CERT_NOT_YET_EXPIRED`, and expiry of a certification that is not `ACTIVE` fails with `ERR_CERT_INVALID_STATE`."

        Design: Corner/validations/cert_expire_before_expiry_rejected
        """
        dealer = create_dealer("DL-CE1", name="Dealer CE1")
        cert = create_and_verify_certification(dealer["id"], "CTE-CE1")

        resp = api.expire_certification(cert["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_YET_EXPIRED)

        unchanged = validate_success(api.get_certification(cert["id"],
                                                           oem_admin_headers),
                                     200)
        assert unchanged["status"] == "ACTIVE"
