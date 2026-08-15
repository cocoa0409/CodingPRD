"""Rent-increase approval ceiling tests (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN,
    setup_active_scenario,
    create_increase_request,
    make_landlord_headers,
)


class TestRentNotReasonableOnApprove:
    def test_approve_above_ceiling_rejected(self, api):
        """PRD §3.7: "To approve it, the admin's approval call re-runs rent
        reasonableness against the requested rent: the requested
        `requested_rent_cents` must be at most the lesser of the applicable
        payment standard and the comparable-median times 1.10 when comparables
        exist, or at most the payment standard when they do not. A request that
        exceeds the ceiling is rejected with `ERR_RENT_NOT_REASONABLE`."

        Design: Corner/errors/err_rent_not_reasonable_triggerable
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90310", family_code="CF13", lease_start_date="2026-08-01",
        )
        # No comparables exist, so the ceiling is the payment standard 150000;
        # 200000 exceeds it. Effective date 2027-08-01 == next_recert_due_date.
        rir = create_increase_request(
            contract["id"], landlord,
            requested_rent_cents=200_000, effective_date="2027-08-01",
        )
        resp = api.approve_rent_increase_request(rir["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RENT_NOT_REASONABLE)

    def test_approve_at_ceiling_succeeds(self, api):
        """PRD §3.7: "Approval moves the request from `PENDING` to `APPROVED`,
        updates the contract's `contract_rent_cents` and `approved_rent_cents`
        to the requested figure, and recomputes `hap_portion_cents` and
        `tenant_portion_cents` effective from `effective_date` forward — prior
        periods are unchanged."

        Design: Corner/errors/err_rent_not_reasonable_triggerable
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90310", family_code="CF13b", lease_start_date="2026-08-01",
        )
        # Requested rent equals the payment standard -> at the ceiling, allowed.
        rir = create_increase_request(
            contract["id"], landlord,
            requested_rent_cents=150_000, effective_date="2027-08-01",
        )
        data = validate_success(api.approve_rent_increase_request(rir["id"], ADMIN))
        assert data["status"] == "APPROVED"
        ctr = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert ctr["approved_rent_cents"] == 150_000, (
            f"approval updates approved_rent_cents to the requested figure, got "
            f"{ctr['approved_rent_cents']}"
        )
