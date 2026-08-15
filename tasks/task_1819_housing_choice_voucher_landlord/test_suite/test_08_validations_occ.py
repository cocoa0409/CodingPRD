"""Validation-rule and optimistic-concurrency tests (PRD §2.5, §3.3, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, ADMIN,
    create_landlord, create_property, create_unit, create_voucher_family,
    setup_priced_unit, setup_active_scenario,
    create_draft_contract, create_increase_request, open_recertification,
    complete_recertification_payload,
    make_landlord_headers,
)


class TestVoucherSizeMismatch:
    def test_undersized_voucher_rejected(self, api):
        """PRD §3.3: "the family's `voucher_bedroom_size` must be at least the
        unit's `bedroom_count`, since a family may under-occupy a smaller unit
        but may not over-occupy a larger one (`ERR_VOUCHER_SIZE_MISMATCH`)"

        Design: Corner/validations/voucher_size_mismatch_rejected
        """
        landlord = create_landlord(legal_name="CL8", tax_id="CT8")
        prop = create_property(landlord["id"], address="8 S St", zip_code="90305")
        unit = create_unit(prop["id"], unit_label="CU8", bedroom_count=2)
        family = create_voucher_family(
            family_code="CF8", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOUCHER_SIZE_MISMATCH)


class TestOneLiveContractPerUnit:
    def test_second_contract_on_same_unit_rejected(self, api):
        """PRD §3.3: "the unit must not already have another HAP contract in
        `DRAFT`, `PENDING_INSPECTION`, `APPROVED`, `ACTIVE`, or `ABATED`
        (`ERR_UNIT_ALREADY_UNDER_CONTRACT`)"
        PRD §3.3: "The unit simultaneously flips from `LISTED` to
        `UNDER_CONTRACT` and its `version` is bumped — this is the version bump
        that a competing contract-creation request would observe."

        Design: Difficulty/resource_temporal_overlap/unit_single_live_contract_temporal_exclusion
        """
        landlord = create_landlord(legal_name="L 16", tax_id="T16")
        prop = create_property(landlord["id"], address="16 P St", zip_code="90017")
        unit = create_unit(prop["id"], unit_label="UG", bedroom_count=1)
        family = create_voucher_family(
            family_code="FG", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        headers = make_landlord_headers(landlord["id"])
        first = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            headers,
        )
        validate_success(first, expected_status=201)
        # The unit's version was bumped by the first create, so the replayed
        # expected_unit_version is stale; a fresh read would instead hit the
        # one-live-contract exclusion. Either way the second create is rejected.
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            headers,
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_STALE_VERSION,
                ApiErrorId.ERR_INVALID_STATE,
                ApiErrorId.ERR_UNIT_ALREADY_UNDER_CONTRACT,
            ],
        )

    def test_second_contract_with_fresh_version_rejected_live_contract(self, api):
        """PRD §3.3: "the unit must not already have another HAP contract in
        `DRAFT`, `PENDING_INSPECTION`, `APPROVED`, `ACTIVE`, or `ABATED`
        (`ERR_UNIT_ALREADY_UNDER_CONTRACT`)"

        Design: Difficulty/resource_temporal_overlap/unit_single_live_contract_temporal_exclusion
        """
        landlord = create_landlord(legal_name="L 16b", tax_id="T16b")
        prop = create_property(landlord["id"], address="16 P St", zip_code="90017")
        unit = create_unit(prop["id"], unit_label="UG2", bedroom_count=1)
        family = create_voucher_family(
            family_code="FG2", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        headers = make_landlord_headers(landlord["id"])
        first = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            headers,
        )
        validate_success(first, expected_status=201)
        # Re-read the unit so expected_unit_version is current; the rejection
        # must now come from the state/live-contract rules, not OCC.
        fresh_unit = get_success_data(api.get_unit(unit["id"], headers))
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": fresh_unit["version"],
            },
            headers,
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_UNIT_ALREADY_UNDER_CONTRACT],
        )


class TestContractCreateStaleUnitOcc:
    def test_stale_expected_unit_version_rejected(self, api):
        """PRD §2.5: "Creating a HAP contract carries a required
        `expected_unit_version` field whose value must equal the target unit's
        current `version`; if the unit's version has advanced since the client
        last read it (for example because another writer has just created a
        contract for that same unit, flipping it from `LISTED` to
        `UNDER_CONTRACT` and bumping its version), the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/contract_create_stale_unit_version_occ
        """
        landlord = create_landlord(legal_name="CL15", tax_id="CT15")
        prop = create_property(landlord["id"], address="15 S St", zip_code="90313")
        unit = create_unit(prop["id"], unit_label="CU15", bedroom_count=1)
        family = create_voucher_family(
            family_code="CF15", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        headers = make_landlord_headers(landlord["id"])
        first = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            headers,
        )
        validate_success(first, expected_status=201)
        # Replay with the now-stale expected_unit_version.
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            headers,
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )


class TestRentIncreaseTooEarly:
    def test_effective_date_before_next_recert_rejected(self, api):
        """PRD §3.7: "The effective date must be on or after the contract's
        `next_recert_due_date` — an earlier date is rejected with
        `ERR_INCREASE_TOO_EARLY` both at request time and again at approval
        time, so an increase cannot slip in mid-year even if the anniversary
        moves between the two calls."

        Design: Corner/validations/rent_increase_too_early_rejected
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90306", family_code="CF9", lease_start_date="2026-08-01",
        )
        # next_recert_due_date is 2027-08-01 (one year after lease start).
        resp = api.create_rent_increase_request(
            {
                "contract_id": contract["id"],
                "requested_rent_cents": 160_000,
                "effective_date": "2027-01-01",
            },
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INCREASE_TOO_EARLY)


class TestRecertificationOccAndLockdown:
    def test_complete_with_stale_contract_version_rejected(self, api):
        """PRD §2.5: "Completing a recertification carries a required
        `expected_contract_version` field whose value must equal the parent
        contract's current `version`; because completing a recertification
        advances the contract's `next_recert_due_date` and increments the
        contract's `version`, a client that has not observed the most recent
        write is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being
        allowed to double-apply the anniversary advance."

        Design: Corner/cross_cutting/recert_complete_stale_contract_version_occ
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90314", family_code="CF16",
        )
        rec = open_recertification(
            contract["id"], due_date="2027-08-01", new_family_income_cents=3_000_000
        )
        # Bump the contract's version after the client snapshot by approving a
        # rent increase (PRD §3.7: approval updates the contract's rents and
        # recomputes portions; §2.4: version increments on every mutation).
        rir = create_increase_request(
            contract["id"], landlord,
            requested_rent_cents=150_000, effective_date="2027-08-01",
        )
        validate_success(api.approve_rent_increase_request(rir["id"], ADMIN))
        resp = api.complete_recertification(
            rec["id"],
            complete_recertification_payload(contract["version"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_complete_twice_rejected(self, api):
        """PRD §3.7: "On success, the recertification moves from `OPEN` to
        `COMPLETED`, the voucher family's `annual_income_cents` is overwritten
        with `new_family_income_cents`, the HAP split is recomputed against the
        new income to refresh `hap_portion_cents` and `tenant_portion_cents`,
        the contract's `next_recert_due_date` advances by one year, and a new
        `Recertification` row is auto-created with its `due_date` set to the
        newly advanced `next_recert_due_date`."

        Design: Corner/state_machines/recertification_terminal_lockdown
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90302", family_code="CF4",
        )
        rec = open_recertification(
            contract["id"], due_date="2027-08-01", new_family_income_cents=3_000_000
        )
        first = api.complete_recertification(
            rec["id"],
            complete_recertification_payload(contract["version"]),
            ADMIN,
        )
        completed = validate_success(first)
        assert completed["status"] == "COMPLETED"
        # Replaying the completion hits the state and/or OCC guard; both are
        # sanctioned rejections for a second completion of the same row.
        resp = api.complete_recertification(
            rec["id"],
            complete_recertification_payload(contract["version"]),
            ADMIN,
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_STALE_VERSION]
        )
