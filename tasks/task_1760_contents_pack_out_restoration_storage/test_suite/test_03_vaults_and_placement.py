"""Vault placement gates and the occupancy conservation invariant
(PRD §2.7, §2.8, §3.4).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, assert_vault_invariants,
    setup_job_with_room, setup_cleaned_item, drive_item_to_cleaned,
    create_vault, get_vault, place_item, release_placement, get_item,
)

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]


def _cleaned_items(room_id, specs):
    """Register + clean a series of items. specs: list of item overrides."""
    out = []
    for spec in specs:
        item, _task = drive_item_to_cleaned(room_id, spec)
        out.append(item)
    return out


class TestVaultCapacityBoundary:
    def _setup(self):
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-BP1", "property_address": "18 Spruce St"},
            room_overrides={"name": "Storage", "room_type": "BASEMENT"})
        a, b, c = _cleaned_items(room["id"], [
            {"barcode": "BC-BP1A", "description": "A", "declared_value_cents": 100,
             "volume_cu_ft": 900},
            {"barcode": "BC-BP1B", "description": "B", "declared_value_cents": 100,
             "volume_cu_ft": 100},
            {"barcode": "BC-BP1C", "description": "C", "declared_value_cents": 100,
             "volume_cu_ft": 1},
        ])
        vault = create_vault(code="V-BP1", climate_class="CLIMATE_CONTROLLED",
                             capacity_cu_ft=1000, monthly_rate_cents_per_cu_ft=100)
        return job, (a, b, c), vault

    def test_vault_capacity_exact_fit_allowed_and_fills_vault(self, api):
        """PRD §3.4: "the vault's current `occupied_cu_ft` plus the item's
        `volume_cu_ft` must not exceed `capacity_cu_ft`, with an exact fit — the
        sum landing precisely on capacity — allowed; overflow is rejected with
        `ERR_VAULT_CAPACITY_EXCEEDED`."
        PRD §2.8: "its `posture` reads `FULL` exactly when `occupied_cu_ft` equals
        `capacity_cu_ft`, otherwise `OPEN`."

        Design: Difficulty/boundary_precision_check/vault_capacity_exact_fit_allowed
        """
        _job, (a, b, _c), vault = self._setup()

        plc_a = place_item(a["id"], vault["id"])
        plc_b = place_item(b["id"], vault["id"])
        assert plc_a["status"] == "ACTIVE" and plc_b["status"] == "ACTIVE", (
            "900 + 100 == 1000 <= 1000 — the exact fit must be allowed")

        vault_after = get_vault(vault["id"])
        assert vault_after["occupied_cu_ft"] == 1000, (
            f"expected occupancy 1000 after the exact fit, got {vault_after['occupied_cu_ft']}")
        assert vault_after["posture"] == "FULL", (
            f"occupancy == capacity must read FULL, got {vault_after['posture']}")
        assert_vault_invariants(vault_after)

    def test_vault_capacity_one_cu_ft_over_rejected(self, api):
        """PRD §3.4: "the vault's current `occupied_cu_ft` plus the item's
        `volume_cu_ft` must not exceed `capacity_cu_ft`, with an exact fit — the
        sum landing precisely on capacity — allowed; overflow is rejected with
        `ERR_VAULT_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/vault_capacity_exact_fit_allowed
        """
        _job, (a, b, c), vault = self._setup()
        place_item(a["id"], vault["id"])
        place_item(b["id"], vault["id"])

        res = api.create_placement(c["id"], {"vault_id": vault["id"]}, TECH)
        validate_error(res, ApiErrorId.ERR_VAULT_CAPACITY_EXCEEDED, expected_status=422)

        vault_after = get_vault(vault["id"])
        assert vault_after["occupied_cu_ft"] == 1000, (
            "the rejected 1001st cubic foot must not change occupancy")
        assert get_item(c["id"])["processing_status"] == "CLEANED"


class TestHighValueThreshold:
    def _setup(self):
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-BP2", "property_address": "20 Chestnut Ave"},
            room_overrides={"name": "Den", "room_type": "LIVING"})
        x, y = _cleaned_items(room["id"], [
            {"barcode": "BC-BP2X", "description": "Grand piano",
             "item_category": "FURNITURE", "declared_value_cents": 1000000,
             "volume_cu_ft": 30},
            {"barcode": "BC-BP2Y", "description": "Oak table",
             "item_category": "FURNITURE", "declared_value_cents": 999999,
             "volume_cu_ft": 30},
        ])
        vault = create_vault(code="V-BP2", climate_class="STANDARD",
                             capacity_cu_ft=1000, monthly_rate_cents_per_cu_ft=100)
        return x, y, vault

    def test_high_value_at_exact_threshold_requires_specialty_referral(self, api):
        """PRD §3.1: "The platform derives `is_high_value` for each item: an item is
        high-value exactly when its `declared_value_cents` is at least 1000000
        cents — ten thousand dollars — with the boundary itself included."
        PRD §3.4: "a high-value item — one whose `is_high_value` derives true — may
        be placed only if the item already has a `QA_ACCEPTED` specialty referral;
        placement without one is rejected with `ERR_SPECIALTY_REQUIRED`."

        Design: Difficulty/boundary_precision_check/high_value_threshold_exact_boundary
        """
        x, _y, vault = self._setup()
        assert x["is_high_value"] is True, (
            f"declared_value_cents exactly 1000000 must derive true, got {x['is_high_value']}")

        res = api.create_placement(x["id"], {"vault_id": vault["id"]}, TECH)
        validate_error(res, ApiErrorId.ERR_SPECIALTY_REQUIRED, expected_status=422)

    def test_below_threshold_not_high_value_and_places_freely(self, api):
        """PRD §3.1: "The platform derives `is_high_value` for each item: an item is
        high-value exactly when its `declared_value_cents` is at least 1000000
        cents — ten thousand dollars — with the boundary itself included."

        Design: Difficulty/boundary_precision_check/high_value_threshold_exact_boundary
        """
        _x, y, vault = self._setup()
        assert y["is_high_value"] is False, (
            f"declared_value_cents 999999 is below the inclusive boundary, got {y['is_high_value']}")

        plc = place_item(y["id"], vault["id"])
        assert plc["status"] == "ACTIVE", (
            "the threshold binds only at >= 1000000; 999999 places without a referral")
        assert get_item(y["id"])["processing_status"] == "IN_STORAGE"


class TestPlacementSafetyPrecedence:
    def _setup(self):
        """Vault capacity 10 fully occupied by cleaned item A (vol 10); hazmat
        item B (vol 1) cleaned and ready."""
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-PP2", "property_address": "16 Juniper Dr"},
            room_overrides={"name": "Shed", "room_type": "GARAGE"})
        a, b = _cleaned_items(room["id"], [
            {"barcode": "BC-PP2A", "description": "Toolbox", "declared_value_cents": 2000,
             "volume_cu_ft": 10},
            {"barcode": "BC-PP2B", "description": "Chem-soaked rug",
             "declared_value_cents": 500, "volume_cu_ft": 1, "hazmat_flag": True},
        ])
        vault = create_vault(code="V-PP2", climate_class="CLIMATE_CONTROLLED",
                             capacity_cu_ft=10, monthly_rate_cents_per_cu_ft=100)
        place_item(a["id"], vault["id"])
        return b, vault

    def test_hazmat_safety_error_beats_capacity_constraint(self, api):
        """PRD §2.7: "When a single request would fail more than one rule, the
        failure reported is the one with the highest priority in the following
        fixed order." — "Eighth, business safety rules — hazmat storage, climate
        compatibility, hazmat manifest requirements — yield
        `ERR_HAZMAT_STORAGE_FORBIDDEN`, `ERR_CLIMATE_CLASS_INCOMPATIBLE`, or
        `ERR_HAZMAT_MANIFEST_REQUIRED`." — "Ninth, business constraints — duplicate
        barcodes, vault capacity, subcontractor capacity, crew window overlap, and
        statement period validity — yield `ERR_DUPLICATE_BARCODE`,
        `ERR_VAULT_CAPACITY_EXCEEDED`, `ERR_SUBCONTRACTOR_AT_CAPACITY`,
        `ERR_CREW_WINDOW_OVERLAP`, or `ERR_VALIDATION`."
        PRD §3.4: "A hazmat-flagged item may never enter any vault: rejection
        `ERR_HAZMAT_STORAGE_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/hazmat_safety_error_beats_capacity_constraint
        """
        b, vault = self._setup()
        assert get_vault(vault["id"])["occupied_cu_ft"] == 10, (
            "precondition: vault exactly full, so capacity is also violated")

        res = api.create_placement(b["id"], {"vault_id": vault["id"]}, TECH)
        validate_error(res, ApiErrorId.ERR_HAZMAT_STORAGE_FORBIDDEN, expected_status=422)

    def test_rejected_hazmat_placement_leaves_no_trace(self, api):
        """PRD §3.4: "A hazmat-flagged item may never enter any vault: rejection
        `ERR_HAZMAT_STORAGE_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/hazmat_safety_error_beats_capacity_constraint
        """
        b, vault = self._setup()
        res = api.create_placement(b["id"], {"vault_id": vault["id"]}, TECH)
        validate_error(res, ApiErrorId.ERR_HAZMAT_STORAGE_FORBIDDEN, expected_status=422)

        vault_after = get_vault(vault["id"])
        assert vault_after["occupied_cu_ft"] == 10, (
            f"rejected placement must not occupy volume, got {vault_after['occupied_cu_ft']}")
        placements = get_success_data(api.list_item_placements(b["id"], TECH))
        assert placements == [], f"no placement may be persisted, got {placements}"
        assert get_item(b["id"])["processing_status"] == "CLEANED"


class TestOccupancyConservation:
    def _setup(self):
        _job, _room, item, _task = setup_cleaned_item(
            job_overrides={"claim_number": "CLM-CI1", "property_address": "34 Hickory St"},
            room_overrides={"name": "Den"},
            item_overrides={"barcode": "BC-CI1", "description": "Armoire",
                            "declared_value_cents": 7000, "volume_cu_ft": 100})
        vault = create_vault(code="V-CI1", climate_class="CLIMATE_CONTROLLED",
                             capacity_cu_ft=500, monthly_rate_cents_per_cu_ft=200)
        return item, vault

    def test_activate_release_pair_restores_occupancy(self, api):
        """PRD §2.8: "Vault occupancy is conserved: activating a placement adds
        exactly the item's `volume_cu_ft` to `occupied_cu_ft`, and the paired
        release — whatever its reason — subtracts exactly the same amount, so an
        activate-release pair leaves occupancy unchanged."

        Design: Difficulty/compensating_invariant/vault_occupancy_activate_release_compensation
        """
        item, vault = self._setup()
        assert get_vault(vault["id"])["occupied_cu_ft"] == 0

        plc = place_item(item["id"], vault["id"])
        assert get_vault(vault["id"])["occupied_cu_ft"] == 100, (
            "activation adds exactly volume_cu_ft (100)")

        release_placement(plc["id"])
        assert get_vault(vault["id"])["occupied_cu_ft"] == 0, (
            "the paired release subtracts exactly the same amount")

    def test_manual_release_marks_placement_and_reopens_vault(self, api):
        """PRD §3.4: "A manual release by an `InventoryTechnician` — permitted only
        while the placement is `ACTIVE`, otherwise `ERR_INVALID_TRANSITION` —
        stamps `released_on` from the logical clock, sets `release_reason` to
        `MANUAL`, moves the item from `IN_STORAGE` back to `CLEANED`, decrements
        the vault's occupancy by exactly the added volume, and recomputes
        provisional accrual and the job total."
        PRD §2.8: "its `posture` reads `FULL` exactly when `occupied_cu_ft` equals
        `capacity_cu_ft`, otherwise `OPEN`."

        Design: Difficulty/compensating_invariant/vault_occupancy_activate_release_compensation
        """
        item, vault = self._setup()
        plc = place_item(item["id"], vault["id"])

        released = release_placement(plc["id"])
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "MANUAL"

        vault_after = get_vault(vault["id"])
        assert vault_after["posture"] == "OPEN", (
            f"after release occupancy 0 < 500 must read OPEN, got {vault_after['posture']}")
        assert_vault_invariants(vault_after)
        assert get_item(item["id"])["processing_status"] == "CLEANED"


class TestClimateGate:
    def test_climate_gate_textile_into_standard_vault(self, api):
        """PRD §3.4: "Items in the climate-required categories `TEXTILE`,
        `DOCUMENT`, `ARTWORK`, and `ELECTRONICS` may be placed only into
        `CLIMATE_CONTROLLED` vaults; placement of such an item into a `STANDARD`
        or `COLD_STORAGE` vault is rejected with `ERR_CLIMATE_CLASS_INCOMPATIBLE`."

        Design: Corner/validations/climate_gate_textile_into_standard_vault
        """
        job, room, item, _task = setup_cleaned_item(
            job_overrides={"claim_number": "CLM-V2", "property_address": "68 Oak St"},
            room_overrides={"name": "Bedroom", "room_type": "BEDROOM"},
            item_overrides={"barcode": "BC-V2", "description": "Wardrobe textiles",
                            "item_category": "TEXTILE", "declared_value_cents": 2500,
                            "volume_cu_ft": 8})
        vault_s = create_vault(code="V-V2S", climate_class="STANDARD",
                               capacity_cu_ft=1000, monthly_rate_cents_per_cu_ft=100)
        vault_c = create_vault(code="V-V2C", climate_class="CLIMATE_CONTROLLED",
                               capacity_cu_ft=1000, monthly_rate_cents_per_cu_ft=150)

        res = api.create_placement(item["id"], {"vault_id": vault_s["id"]}, TECH)
        validate_error(res, ApiErrorId.ERR_CLIMATE_CLASS_INCOMPATIBLE, expected_status=422)

        plc = place_item(item["id"], vault_c["id"])
        assert plc["status"] == "ACTIVE", (
            "the same item into a CLIMATE_CONTROLLED vault passes the climate gate")
