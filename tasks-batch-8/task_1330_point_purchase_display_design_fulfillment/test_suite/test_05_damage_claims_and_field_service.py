"""Damage claims: kit-state gating, adjudication, and rejection side-effect
conservation; field service request referential integrity."""
import pytest

from test_helpers import (
    CLAIMS_ADJUSTER,
    FIELD_SERVICE_MANAGER,
    WAREHOUSE_OPERATOR,
    ApiErrorId,
    api_client,
    create_client,
    create_damage_claim_entity,
    create_damage_claim_payload,
    create_field_service_request_payload,
    create_program,
    create_store,
    get_kit,
    list_kits_for_run,
    mark_kitted,
    setup_delivered,
    setup_kitted_kit,
    setup_produced_run,
    setup_shipped,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClaimKitStateGate:
    """A claim may only be reported against a kit in SHIPPED or DELIVERED."""

    def test_claim_against_pending_kit_returns_referential(self):
        """PRD §3.5: "The referenced kit must be in `SHIPPED` or `DELIVERED`
        status — a claim against a kit in any other state is rejected with
        `ERR_REFERENTIAL` — and the `replacement_quantity` must be at least 1,
        else `ERR_INVALID_REQUEST`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_claim_create
        """
        ctx = setup_produced_run(store_count=3, num_stores=1)
        kit = ctx["kits"][0]
        assert kit["status"] == "PENDING"

        resp = api_client.create_damage_claim(
            create_damage_claim_payload(kit["id"], replacement_quantity=2),
            CLAIMS_ADJUSTER)
        error = validate_error(resp, ApiErrorId.ERR_REFERENTIAL)
        assert error["error_id"] != "ERR_WINDOW_VIOLATION"

    def test_claim_against_kitted_kit_returns_referential(self):
        """PRD §3.5: "The referenced kit must be in `SHIPPED` or `DELIVERED`
        status — a claim against a kit in any other state is rejected with
        `ERR_REFERENTIAL`".

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_claim_create
        """
        ctx = setup_kitted_kit(store_count=3, num_stores=1)
        kit = ctx["kit"]
        assert kit["status"] == "KITTED"

        resp = api_client.create_damage_claim(
            create_damage_claim_payload(kit["id"], replacement_quantity=2),
            CLAIMS_ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL)


class TestClaimRejectionConservation:

    def test_reject_claim_on_delivered_kit_leaves_kit_untouched(self):
        """PRD §3.5: "Rejection moves a `REPORTED` claim to `REJECTED` with no
        side effects beyond the claim's own version bump."

        Design: Difficulty/compensating_invariant/damage_claim_reject_conserves_kit_count_and_status
        """
        ctx = setup_delivered(store_count=3, num_stores=1)
        kit = ctx["kit"]
        assert kit["status"] == "DELIVERED"
        claim = create_damage_claim_entity(kit["id"], replacement_quantity=2)
        assert claim["status"] == "REPORTED"

        rejected = validate_success(
            api_client.reject_claim(claim["id"], CLAIMS_ADJUSTER), 200)
        assert rejected["status"] == "REJECTED"

        kit_after = get_kit(kit["id"])
        assert kit_after["status"] == "DELIVERED", \
            f"rejecting the claim must not mutate the kit, got {kit_after['status']}"
        kits = list_kits_for_run(ctx["run"]["id"])
        assert len(kits) == 1, \
            f"kit count must be conserved at 1, got {len(kits)}"

    def test_reject_claim_on_shipped_kit_leaves_kit_shipped(self):
        """PRD §3.5: "Rejection moves a `REPORTED` claim to `REJECTED` with no
        side effects beyond the claim's own version bump."
        PRD §3.5: "Approval also carries the workflow's sharpest cascade: if the
        kit is still in `SHIPPED` status, it moves to the terminal `DAMAGED`
        state in the same transaction" — rejection carries no such cascade.

        Design: Difficulty/compensating_invariant/damage_claim_reject_conserves_kit_count_and_status
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        kit = ctx["kit"]
        assert kit["status"] == "SHIPPED"
        claim = create_damage_claim_entity(kit["id"], replacement_quantity=1)

        rejected = validate_success(
            api_client.reject_claim(claim["id"], CLAIMS_ADJUSTER), 200)
        assert rejected["status"] == "REJECTED"
        assert get_kit(kit["id"])["status"] == "SHIPPED", \
            "a rejected claim must not move the kit to DAMAGED"
        assert len(list_kits_for_run(ctx["run"]["id"])) == 1


class TestFieldServiceReferentialIntegrity:

    def test_fsr_program_store_mismatch_returns_referential(self):
        """PRD §3.6: "The `program_id` must match the program the named store
        actually belongs to; a mismatched pairing is rejected with
        `ERR_REFERENTIAL`."

        Design: Corner/errors/error_referential_on_fsr_program_store_mismatch
        """
        client = create_client()
        prog_a = create_program(client["id"], store_count=3,
                                program_revenue_cents=1000000, program_name="A")
        prog_b = create_program(client["id"], store_count=3,
                                program_revenue_cents=1000000, program_name="B")
        store = create_store(prog_a["id"], store_number="S1")

        resp = api_client.create_field_service_request(
            create_field_service_request_payload(
                store["id"], prog_b["id"], issue_type="ASSEMBLY_HELP"),
            FIELD_SERVICE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL)
