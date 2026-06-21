"""Utility apportionment: per-capita vs sub-meter variants, largest-remainder
rounding, the conservation invariant, and the apportion preconditions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

MGR = TEST_USERS["manager_headers"]

# Three lots with residents household_size 4 / 2 / 1 — the canonical PER_CAPITA
# split of a 10000c bill: weights 4/2/1 over total 7 -> 5714.28.., 2857.14..,
# 1428.57.. -> floors 5714/2857/1428 (sum 9999); the single remainder cent goes
# to the largest fractional part (.571, lot 3) -> 5714/2857/1429.
PER_CAPITA_SPECS = [
    {"lot": {"lot_number": "A1"}, "resident": {"household_size": 4}},
    {"lot": {"lot_number": "A2"}, "resident": {"household_size": 2}},
    {"lot": {"lot_number": "A3"}, "resident": {"household_size": 1}},
]


def _charge_for_lot(charges, lot_id):
    matches = [c for c in charges if c["lot_id"] == lot_id]
    assert len(matches) == 1, f"expected exactly one charge for lot {lot_id}, got {len(matches)}"
    return matches[0]


class TestApportionmentVariants:
    def test_per_capita_apportionment_splits_by_household_size(self, api):
        """PRD §3.5: "Under the `PER_CAPITA` variant (the default) a lot's weight
        is the `household_size` of the resident on the lot's active lease, and
        meter readings are ignored entirely."
        PRD §3.5: "The leftover remainder — `master_charge_cents` minus the sum of
        the floors — is then distributed one cent at a time to lots in descending
        order of their fractional remainder, with ties broken by `created_at`
        ascending."

        Design: Difficulty/dual_variant_calc/apportionment_per_capita_vs_sub_meter
        """
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert _charge_for_lot(charges, rows[0][0]["id"])["amount_cents"] == 5714
        assert _charge_for_lot(charges, rows[1][0]["id"])["amount_cents"] == 2857
        assert _charge_for_lot(charges, rows[2][0]["id"])["amount_cents"] == 1429
        assert bill_after["apportioned_total_cents"] == 10000

    def test_per_capita_ignores_meter_readings(self, api):
        """PRD §3.5: "Under the `PER_CAPITA` variant (the default) a lot's weight
        is the `household_size` of the resident on the lot's active lease, and
        meter readings are ignored entirely."

        Design: Difficulty/dual_variant_calc/apportionment_per_capita_vs_sub_meter
        """
        # Same 3 lots/household sizes, but attach misleading sub-meter readings.
        # PER_CAPITA must ignore them and still split 5714/2857/1429.
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            readings=[(0, 1), (1, 1), (2, 98)],
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert _charge_for_lot(charges, rows[0][0]["id"])["amount_cents"] == 5714
        assert _charge_for_lot(charges, rows[1][0]["id"])["amount_cents"] == 2857
        assert _charge_for_lot(charges, rows[2][0]["id"])["amount_cents"] == 1429

    def test_sub_meter_apportionment_splits_by_metered_units(self, api):
        """PRD §3.5: "Under the `SUB_METER` variant a lot's weight is the sum of
        that lot's `metered_units` for this bill, and household size is ignored
        entirely."

        Design: Corner/calculations/sub_meter_apportionment_exact_split
        """
        specs = [
            {"lot": {"lot_number": "U1"}, "resident": {"household_size": 2}},
            {"lot": {"lot_number": "U2"}, "resident": {"household_size": 2}},
            {"lot": {"lot_number": "U3"}, "resident": {"household_size": 2}},
        ]
        community, rows, bill = fx.setup_apportionment_ready(
            specs,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "SUB_METER"},
            bill_overrides={"master_charge_cents": 10000},
            readings=[(0, 30), (1, 50), (2, 20)],
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert _charge_for_lot(charges, rows[0][0]["id"])["amount_cents"] == 3000
        assert _charge_for_lot(charges, rows[1][0]["id"])["amount_cents"] == 5000
        assert _charge_for_lot(charges, rows[2][0]["id"])["amount_cents"] == 2000


class TestLargestRemainderRounding:
    def test_remainder_cent_goes_to_largest_fractional_part(self, api):
        """PRD §3.5: "First each lot's raw share is floored to whole cents. The
        leftover remainder — `master_charge_cents` minus the sum of the floors —
        is then distributed one cent at a time to lots in descending order of
        their fractional remainder, with ties broken by `created_at` ascending."

        Design: Difficulty/combinatorial_formula/apportionment_largest_remainder_rounding_order
        """
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        # Lot 3 (.571 fractional remainder, the largest) gets the single cent.
        assert _charge_for_lot(charges, rows[2][0]["id"])["amount_cents"] == 1429
        assert sum(c["amount_cents"] for c in charges) == 10000

    def test_floor_then_distribute_sums_to_master(self, api):
        """PRD §3.5: "This guarantees the apportioned shares sum to exactly
        `master_charge_cents`."

        Design: Difficulty/combinatorial_formula/apportionment_largest_remainder_rounding_order
        """
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert sum(c["amount_cents"] for c in charges) == 10000


class TestApportionmentConservation:
    def test_apportioned_total_equals_master_charge(self, api):
        """PRD §3.5: "Its computed `apportioned_total_cents` is the sum of all
        generated charge amounts and must equal `master_charge_cents`."

        Design: Difficulty/compensating_invariant/apportionment_conservation_sum_equals_master
        """
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            api=api,
        )
        bill_after = get_success_data(api.apportion_bill(bill["id"], MGR))
        assert bill_after["apportioned_total_cents"] == 10000
        assert bill_after["apportioned_total_cents"] == bill_after["master_charge_cents"]

    def test_charges_sum_equals_apportioned_total(self, api):
        """PRD §3.5: "Because raw shares are fractional, the system uses a
        largest-remainder distribution to land exactly on the master charge."

        Design: Difficulty/compensating_invariant/apportionment_conservation_sum_equals_master
        """
        community, rows, bill = fx.setup_apportionment_ready(
            PER_CAPITA_SPECS,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 10000},
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert sum(c["amount_cents"] for c in charges) == bill_after["apportioned_total_cents"]


class TestApportionmentImmediacyAndImmutability:
    def test_apportion_response_carries_apportioned_state_immediately(self, api):
        """PRD §3.5: "A new bill is `DRAFT`; once apportioned it becomes
        `APPORTIONED`."
        PRD §2.5: "These derived values are always returned in their current
        computed form on the relevant GET endpoints."

        Design: Corner/consistency_model/apportion_charges_visible_same_request
        """
        specs = [{"lot": {"lot_number": "IM2"}, "resident": {"household_size": 2}}]
        community, rows, bill = fx.setup_apportionment_ready(
            specs,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 5000},
            api=api,
        )
        resp = api.apportion_bill(bill["id"], MGR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPORTIONED"
        assert data["apportioned_total_cents"] == 5000

    def test_utility_charge_has_no_version_field(self, api):
        """PRD §2.4: "Four entities are append-only or immutable records and
        therefore carry only `id` and `created_at`, with no `updated_at` and no
        `version`: `UtilityReading` (an append-only sub-meter reading),
        `UtilityCharge` (an immutable apportionment line item), `ConversionBallot`
        (one immutable ballot per lot per vote), and `LotLedgerEntry` (an
        append-only ledger row)."

        Design: Corner/entities/utility_charge_immutable_no_version_field
        """
        specs = [{"lot": {"lot_number": "M1"}, "resident": {"household_size": 2}}]
        community, rows, bill = fx.setup_apportionment_ready(
            specs,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "PER_CAPITA"},
            bill_overrides={"master_charge_cents": 5000},
            api=api,
        )
        bill_after, charges = fx.apportion_and_charges(bill["id"], api=api)
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 5000
        assert "version" not in charges[0]
        assert "updated_at" not in charges[0]


class TestApportionmentPreconditions:
    def test_apportion_with_zero_occupied_lots_rejected(self, api):
        """PRD §3.5: "Running apportionment moves the bill `DRAFT → APPORTIONED`.
        It requires the bill to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and
        the community to have at least one `OCCUPIED` lot; with zero occupied lots
        the run is rejected with `ERR_NO_OCCUPIED_LOTS` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/apportion_empty_occupied_set_boundary
        """
        community = fx.create_community(
            api, state_code="CA", utility_apportionment_method="PER_CAPITA"
        )
        fx.create_lot(community["id"], api, lot_number="B2", base_rent_cents=60000)
        bill = get_success_data(
            api.create_utility_bill(
                fx.f.create_utility_bill_payload(community["id"], master_charge_cents=10000),
                MGR,
            )
        )
        resp = api.apportion_bill(bill["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_NO_OCCUPIED_LOTS.value)

    def test_apportion_with_vacant_only_lots_does_not_apportion(self, api):
        """PRD §3.5: "It requires the bill to be `DRAFT` (otherwise
        `ERR_INVALID_STATE`) and the community to have at least one `OCCUPIED` lot;
        with zero occupied lots the run is rejected with `ERR_NO_OCCUPIED_LOTS`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/apportion_empty_occupied_set_boundary
        """
        # Two VACANT lots (count == 0 occupied) — the empty candidate set is
        # rejected and the bill stays DRAFT.
        community = fx.create_community(
            api, state_code="CA", utility_apportionment_method="PER_CAPITA"
        )
        fx.create_lot(community["id"], api, lot_number="V1", base_rent_cents=60000)
        fx.create_lot(community["id"], api, lot_number="V2", base_rent_cents=60000)
        bill = get_success_data(
            api.create_utility_bill(
                fx.f.create_utility_bill_payload(community["id"], master_charge_cents=10000),
                MGR,
            )
        )
        resp = api.apportion_bill(bill["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_NO_OCCUPIED_LOTS.value)
        bill_after = get_success_data(api.get_utility_bill(bill["id"], MGR))
        assert bill_after["status"] == "DRAFT"

    def test_sub_meter_apportion_with_zero_readings_rejected(self, api):
        """PRD §3.5: "Under `SUB_METER` the summed metered consumption across the
        bill's readings must be greater than zero; if it is zero the run is
        rejected with `ERR_NO_METER_READINGS` (HTTP 409)."

        Design: Corner/calculations/sub_meter_with_zero_readings_returns_no_meter_readings
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api,
            community_overrides={"state_code": "CA", "utility_apportionment_method": "SUB_METER"},
            lot_overrides={"lot_number": "Z0"},
        )
        bill = get_success_data(
            api.create_utility_bill(
                fx.f.create_utility_bill_payload(community["id"], master_charge_cents=10000),
                MGR,
            )
        )
        resp = api.apportion_bill(bill["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_NO_METER_READINGS.value)
