"""Bicycle registration: serial canonicalization, fee tiers, rounding order,
ledger posting, duplicate-serial rejection (PRD §2.7, §2.8, §3.2)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_owner,
    register_bicycle,
    owner_headers,
    get_all_ledger_entries,
    assert_bicycle,
    assert_ledger_entry,
    create_bicycle_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestSerialNormalizationAndComputedFields:
    def test_bicycle_initial_states_on_create(self, api):
        """PRD §3.2: "The bicycle begins life with `registry_status` `REGISTERED`
        and `integrity_status` `CLEAR`."

        Design: Corner/state_machines/bicycle_initial_states_on_create
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="INIT10")
        assert bicycle["registry_status"] == "REGISTERED", (
            f"expected REGISTERED, got {bicycle['registry_status']}"
        )
        assert bicycle["integrity_status"] == "CLEAR", (
            f"expected CLEAR, got {bicycle['integrity_status']}"
        )


class TestRegistrationFeeCalculation:
    @pytest.mark.parametrize(
        "declared_value_cents,expected_fee_cents",
        [
            (49999, 1030),    # below 50000 -> 1000 + round(0.03*1000)=30
            (50000, 2060),    # at 50000 -> 2000 + round(0.03*2000)=60
            (200000, 2060),   # at most 200000 -> 2000 + 60
            (200001, 3605),   # above 200000 -> 3500 + round(0.03*3500)=105
        ],
        ids=["49999-tier1", "50000-tier2-floor", "200000-tier2-ceiling", "200001-tier3"],
    )
    def test_registration_fee_tier_boundaries(
        self, api, declared_value_cents, expected_fee_cents
    ):
        """PRD §3.2: "a tier base of 1000 cents when the declared value is below
        50000 cents, 2000 cents when it is at least 50000 and at most 200000 cents,
        or 3500 cents when it exceeds 200000 cents"
        PRD §3.2: "a processing component of three percent of the sum of the tier
        base, insurance, and engraving components, rounded half-up."

        Design: Corner/calculations/registration_fee_tier_boundaries
        """
        owner = register_owner("tiers@x.com", "Tier Owner")
        bicycle = register_bicycle(
            owner,
            serial_number=f"TIER{declared_value_cents}",
            declared_value_cents=declared_value_cents,
            photo_url=f"https://x/{declared_value_cents}.jpg",
        )
        assert bicycle["registration_fee_cents"] == expected_fee_cents, (
            f"declared {declared_value_cents}: expected fee {expected_fee_cents}, "
            f"got {bicycle['registration_fee_cents']}"
        )

    def test_registration_fee_per_component_rounding_order_both_extras(self, api):
        """PRD §3.2: "rounding happens per component first, and the rounded
        components are then summed — computing the sum of unrounded components and
        rounding once at the end is a different, forbidden order."
        PRD §3.2: "an insurance component equal to eight percent of the declared
        value, rounded half-up, when `insurance_opt_in` is set, and zero otherwise;
        an engraving component of a flat 1500 cents when `engraving_opt_in` is set"

        Declared 12345 with both extras: 1000 + round(0.08*12345)=988 + 1500 +
        round(0.03*3488)=105 == 3593; sum-then-round would produce 3592.

        Design: Difficulty/combinatorial_formula/registration_fee_per_component_rounding_order
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(
            owner,
            serial_number="FEE123",
            declared_value_cents=12345,
            engraving_opt_in=True,
            insurance_opt_in=True,
        )
        assert bicycle["registration_fee_cents"] == 3593, (
            f"expected pinned per-component fee 3593, got "
            f"{bicycle['registration_fee_cents']} (sum-then-round gives 3592)"
        )

    def test_registration_fee_per_component_rounding_order_insurance_only(self, api):
        """PRD §3.2: "rounding happens per component first, and the rounded
        components are then summed — computing the sum of unrounded components and
        rounding once at the end is a different, forbidden order."
        PRD §3.2: "an insurance component equal to eight percent of the declared
        value, rounded half-up, when `insurance_opt_in` is set, and zero otherwise"

        Declared 12345 with insurance only: 1000 + 988 + round(0.03*1988)=60 == 2048;
        the forbidden order yields round(1000 + 987.6 + 59.628) == 2047.

        Design: Difficulty/combinatorial_formula/registration_fee_per_component_rounding_order
        """
        owner = register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(
            owner,
            serial_number="FEE124",
            declared_value_cents=12345,
            insurance_opt_in=True,
        )
        assert bicycle["registration_fee_cents"] == 2048, (
            f"expected pinned per-component fee 2048, got "
            f"{bicycle['registration_fee_cents']} (sum-then-round gives 2047)"
        )


class TestRegistrationLedgerPosting:
    def test_ledger_entry_immutable_shape(self, api):
        """PRD §2.5: "One entity breaks this convention deliberately: `LedgerEntry`
        is an append-only financial record and carries only `id` and `created_at`.
        Both `updated_at` and `version` are absent from ledger entries."
        PRD §3.2: "the fee posts a balanced ledger pair: a `DEBIT` to the `OWNER`
        account and a `CREDIT` to the `PROGRAM` account, both of type
        `REGISTRATION_FEE` for the computed amount"

        Design: Corner/entities/ledger_entry_immutable_shape
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="IMM100", declared_value_cents=40000)
        entries = get_all_ledger_entries({"bicycle_id": bicycle["id"]})
        assert len(entries) == 2, (
            f"registration must post exactly one balanced pair, got {len(entries)} entries"
        )
        for entry in entries:
            assert_ledger_entry(entry)
            assert entry["entry_type"] == "REGISTRATION_FEE"
            assert entry["amount_cents"] == 1030
            assert entry["bicycle_id"] == bicycle["id"]
        directions = sorted(e["direction"] for e in entries)
        assert directions == ["CREDIT", "DEBIT"], (
            f"expected one DEBIT and one CREDIT, got {directions}"
        )
        by_direction = {e["direction"]: e for e in entries}
        assert by_direction["DEBIT"]["account"] == "OWNER"
        assert by_direction["DEBIT"]["owner_id"] == owner["id"]
        assert by_direction["CREDIT"]["account"] == "PROGRAM"


class TestDuplicateSerialRejection:
    def test_duplicate_serial_exact_rejected(self, api):
        """PRD §3.2: "An exact `serial_normalized` equality with an existing `CLEAR`
        bicycle is rejected outright with `ERR_DUPLICATE_SERIAL_ACTIVE` (HTTP 409) —
        the platform will not register a second live record for the same canonical
        serial."

        Design: Corner/validations/duplicate_serial_exact_rejected
        """
        owner = register_owner("o1@x.com", "O One")
        register_bicycle(owner, serial_number="abc-123")  # normalizes to ABC123
        resp = api.create_bicycle(
            create_bicycle_payload(serial_number="ABC123", photo_url="https://x/2.jpg"),
            owner_headers(owner),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL_ACTIVE, expected_status=409)
        # A hard reject is not a suspect flag: no DuplicateFlag may be created.
        flags, meta = validate_paginated(api.list_duplicate_flags(REGISTRAR))
        assert meta["total_count"] == 0, (
            f"exact-serial collisions must not create DuplicateFlags, got {meta['total_count']}"
        )
