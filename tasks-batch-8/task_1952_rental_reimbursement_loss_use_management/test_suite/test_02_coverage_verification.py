"""Coverage verification: decisions, supersession, OCC, and the booking gate."""
import pytest

from test_helpers import (
    ADJUSTER,
    DESK,
    NON_EXISTENT_UUID,
    SETTLEMENT,
    ApiErrorId,
    ReservationStatus,
    add_approved_repair_order,
    assert_rental_reservation,
    create_pending_verification,
    decide_coverage_verification_payload,
    decide_verification,
    get_claim_view,
    open_claim,
    register_policyholder,
    register_rental_partner,
    register_repair_shop,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim_coverage,
)


class TestExistencePrecedence:
    def test_existence_beats_state_on_nested_path(self, api):
        """PRD §2.8: "For any endpoint whose URL path contains resource
        identifiers, the system validates existence sequentially, left to right,
        and the first identifier that does not resolve to an existing resource
        produces its type-specific `404 Not Found` error; later path segments are
        never examined."

        Design: Corner/validations/existence_beats_state_on_nested_path
        """
        resp = api.decide_coverage_verification(
            NON_EXISTENT_UUID,
            decide_coverage_verification_payload(decision="VERIFIED"),
            ADJUSTER,
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_VERIFICATION_NOT_FOUND)


class TestVerificationDecision:
    def test_verification_decide_twice_rejected(self, api):
        """PRD §3.2: "Only a `PENDING` verification can be decided; deciding an
        already-decided record fails with `ERR_VERIFICATION_ALREADY_DECIDED`."

        Design: Corner/state_machines/verification_decide_twice_rejected
        """
        policyholder = register_policyholder()
        claim = open_claim(policyholder["id"])
        verification = create_pending_verification(claim["id"])
        decide_verification(verification["id"], "VERIFIED", True, True)
        resp = api.decide_coverage_verification(
            verification["id"],
            decide_coverage_verification_payload(decision="DENIED",
                                                 denial_reason="late"),
            ADJUSTER,
        )
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_ALREADY_DECIDED)

    def test_settlement_approver_cannot_decide_verification_forbidden(self, api):
        """PRD §2.9: "The `SettlementApprover` settles invoices, pays approved
        loss-of-use claims, and settles and closes claims — but can never verify
        coverage or audit an invoice."
        PRD §2.1: "A caller whose role is not on an endpoint's authorized list is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/settlement_approver_cannot_decide_verification_forbidden
        """
        policyholder = register_policyholder()
        claim = open_claim(policyholder["id"])
        verification = create_pending_verification(claim["id"])
        resp = api.decide_coverage_verification(
            verification["id"],
            decide_coverage_verification_payload(decision="VERIFIED"),
            SETTLEMENT,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        listed, meta = validate_paginated(
            api.list_claim_coverage_verifications(claim["id"], ADJUSTER))
        assert listed[0]["status"] == "PENDING", (
            f"Verification must remain PENDING after a forbidden decide, "
            f"got {listed[0]['status']}"
        )


class TestVerificationOptimisticConcurrency:
    def test_verification_create_stale_claim_version_rejected(self, api):
        """PRD §2.10: "Creating a coverage verification supersedes any pending
        verification on the claim, so the creation request must carry
        `expected_claim_version`, the claim `version` the client last observed."
        PRD §2.10: "If that value no longer matches the claim's current `version`
        — because another writer has since created or decided a verification,
        advancing the claim's version — the create is rejected as stale with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding a
        decision it never observed."
        PRD §3.2: "its creation automatically moves any still-pending earlier
        verification on the same claim to `SUPERSEDED` — at most one verification
        per claim is ever awaiting decision."

        Design: Corner/cross_cutting_complexity/verification_create_stale_claim_version_rejected
        """
        policyholder = register_policyholder()
        claim = open_claim(policyholder["id"])
        first = create_pending_verification(claim["id"],
                                            expected_claim_version=claim["version"])

        # Stale arm: the first create advanced the claim's version, so replaying
        # the pre-create version must be rejected.
        stale = api.create_coverage_verification(
            {"claim_id": claim["id"], "expected_claim_version": claim["version"]},
            ADJUSTER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        # Fresh arm: re-read the claim and create against the current version.
        fresh_version = get_claim_view(claim["id"])["version"]
        third = api.create_coverage_verification(
            {"claim_id": claim["id"], "expected_claim_version": fresh_version},
            ADJUSTER,
        )
        third_data = validate_success(third, 201)
        assert third_data["status"] == "PENDING"

        listed, meta = validate_paginated(
            api.list_claim_coverage_verifications(claim["id"], ADJUSTER))
        assert meta["total_count"] == 2, (
            f"Expected 2 verifications (the stale create persists nothing), "
            f"got {meta['total_count']}"
        )
        by_id = {v["id"]: v for v in listed}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[third_data["id"]]["status"] == "PENDING"


class TestReservationRequiresVerifiedCoverage:
    def test_booking_before_verification_rejected(self, api):
        """PRD §3.4: "The claim must be `OPEN` (`ERR_CLAIM_NOT_OPEN`) and its
        rental track must be `COVERAGE_VERIFIED` — booking on an unverified or
        denied claim fails with `ERR_COVERAGE_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_verified_coverage
        """
        ctx = _setup_unverified_claim_with_order(api)
        claim = get_claim_view(ctx["claim_id"])
        resp = api.create_rental_reservation(
            _reservation_payload(ctx, expected_claim_version=claim["version"]), DESK)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_VERIFIED)

    def test_booking_after_verification_succeeds(self, api):
        """PRD §3.4: "The claim must be `OPEN` (`ERR_CLAIM_NOT_OPEN`) and its
        rental track must be `COVERAGE_VERIFIED` — booking on an unverified or
        denied claim fails with `ERR_COVERAGE_NOT_VERIFIED`."
        PRD §3.4: "The reservation lands in `DRAFT` status, with
        `actual_pickup_date`, `actual_return_date`, and `consumed_days` all null,
        `unnecessary_days` zero"

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_verified_coverage
        """
        ctx = _setup_unverified_claim_with_order(api)
        verify_claim_coverage(ctx["claim_id"], rental_eligible=True,
                              loss_of_use_eligible=True)
        claim = get_claim_view(ctx["claim_id"])
        assert claim["rental_track_status"] == "COVERAGE_VERIFIED"
        resp = api.create_rental_reservation(
            _reservation_payload(ctx, expected_claim_version=claim["version"]), DESK)
        reservation = validate_success(resp, 201)
        assert_rental_reservation(reservation)
        assert reservation["status"] == ReservationStatus.DRAFT.value


# --------------------------------------------------------------- local utils


def _setup_unverified_claim_with_order(api) -> dict:
    """Claim OPEN (no verification) + repair order APPROVED + ACTIVE partner."""
    policyholder = register_policyholder()
    shop = register_repair_shop()
    partner = register_rental_partner()
    claim = open_claim(policyholder["id"])
    ctx = {"policyholder": policyholder, "shop": shop, "partner": partner,
           "claim": claim}
    add_approved_repair_order(ctx)
    return {
        "claim_id": claim["id"],
        "partner_id": partner["id"],
        "repair_order_id": ctx["repair_order"]["id"],
    }


def _reservation_payload(ctx, expected_claim_version) -> dict:
    return {
        "claim_id": ctx["claim_id"],
        "rental_partner_id": ctx["partner_id"],
        "repair_order_id": ctx["repair_order_id"],
        "vehicle_class": "STANDARD",
        "pickup_date": "2026-08-05",
        "authorized_return_date": "2026-08-15",
        "expected_claim_version": expected_claim_version,
    }
