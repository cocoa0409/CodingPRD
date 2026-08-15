"""Molds, machine lines, cavity blockouts, OCC on mold version, and the cycle-throughput preview with labeler cap and blockout derating."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_line, create_mold, install_mold, open_blockout,
    create_cavity_blockout_payload, create_mold_payload,
    setup_qualified_plant,
    api_client, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]
LOGISTICS = TEST_USERS["logistics_coordinator"]


def _setup_installed_mold():
    line = create_line()
    mold = create_mold()
    mold = install_mold(mold["id"], line["id"])
    return line, mold


class TestEffectiveCavities:
    def test_effective_cavities_reconciled_on_blockout_and_clear(self, api):
        """PRD §3.3: "The mold's `effective_cavities` is always its `base_cavities` minus the number of its `OPEN` blockouts — cleared ones no longer count". "The `active_blockout_count` tracks the same `OPEN` population." "Clearing an `OPEN` blockout moves it to `CLEARED`, stamps `cleared_at` from the logical clock, and recomputes both mold figures".

Design: Corner/entities/mold_effective_cavities_computed_and_reconciled"""
        line, mold = _setup_installed_mold()
        blk = open_blockout(mold["id"], 4, "DAMAGE",
                            expected_mold_version=mold["version"])
        mold_mid = get_success_data(api.get_mold(mold["id"], ENGINEER))
        assert mold_mid["effective_cavities"] == 7
        assert mold_mid["active_blockout_count"] == 1

        cleared = validate_success(api.clear_cavity_blockout(blk["id"], ENGINEER), 200)
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_at"] is not None
        mold_after = get_success_data(api.get_mold(mold["id"], ENGINEER))
        assert mold_after["effective_cavities"] == 8
        assert mold_after["active_blockout_count"] == 0


class TestBlockoutViolations:
    def test_cavity_index_out_of_range_rejected(self, api):
        """PRD §3.3: "The `cavity_index` is 1-based and must lie between 1 and the mold's `base_cavities` inclusive, else `ERR_CAVITY_OUT_OF_RANGE`".

Design: Corner/validations/cavity_index_out_of_range_rejected"""
        line, mold = _setup_installed_mold()
        res = api.create_cavity_blockout(
            mold["id"],
            create_cavity_blockout_payload(9, "DAMAGE", mold["version"]),
            ENGINEER)
        validate_error(res, ApiErrorId.ERR_CAVITY_OUT_OF_RANGE)

    def test_cavity_already_blocked_rejected(self, api):
        """PRD §3.3: "opening a second `OPEN` blockout on the same mold and cavity is refused with `ERR_CAVITY_ALREADY_BLOCKED`".

Design: Corner/validations/cavity_already_blocked_rejected"""
        line, mold = _setup_installed_mold()
        open_blockout(mold["id"], 4, "DAMAGE",
                      expected_mold_version=mold["version"])
        fresh = get_success_data(api.get_mold(mold["id"], ENGINEER))
        res = api.create_cavity_blockout(
            mold["id"],
            create_cavity_blockout_payload(4, "PREVENTIVE", fresh["version"]),
            ENGINEER)
        validate_error(res, ApiErrorId.ERR_CAVITY_ALREADY_BLOCKED)


class TestMoldInstall:
    def test_second_mold_install_on_occupied_line_rejected(self, api):
        """PRD §3.3: "Installing a mold requires the mold in `STORAGE` and the target line, named by `machine_line_id`, in `IDLE` with no other mold currently `INSTALLED` on it; a line that already hosts a mold rejects the install with `ERR_LINE_BUSY`."

Design: Corner/validations/second_mold_install_on_occupied_line_rejected"""
        line, mold = _setup_installed_mold()
        mold2 = create_mold(mold_code="M9", base_cavities=6)
        res = api.install_mold(mold2["id"], {"machine_line_id": line["id"]},
                               ENGINEER)
        validate_error(res, ApiErrorId.ERR_LINE_BUSY)


class TestOccOnMoldVersion:
    def test_stale_mold_version_rejected_on_blockout_create(self, api):
        """PRD §2.7: "Opening a cavity blockout against a mold requires `expected_mold_version` to equal that mold's current `version`. If another writer has advanced the mold's version since the client last read it — for example by opening another blockout or by installing the mold — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)".

Design: Corner/cross_cutting_layers/occ_blockout_stale_version_rejected"""
        line, mold = _setup_installed_mold()
        stale_version = mold["version"]
        open_blockout(mold["id"], 1, "DAMAGE",
                      expected_mold_version=stale_version)  # advances version
        res = api.create_cavity_blockout(
            mold["id"],
            create_cavity_blockout_payload(2, "PREVENTIVE", stale_version),
            ENGINEER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_success_data(api.get_mold(mold["id"], ENGINEER))
        retry = api.create_cavity_blockout(
            mold["id"],
            create_cavity_blockout_payload(2, "PREVENTIVE", fresh["version"]),
            ENGINEER)
        blk = validate_success(retry, 201)
        assert blk["status"] == "OPEN"
        assert blk["cavity_index"] == 2


class TestThroughputPreview:
    def _setup_preview_scenario(self, api):
        """Qualified spec needing a labeler + mold installed on a labeler line with two OPEN blockouts (cavities 1 and 2)."""
        ctx = setup_qualified_plant()
        ctx["mold"] = install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        open_blockout(ctx["mold"]["id"], 1, "DAMAGE")
        open_blockout(ctx["mold"]["id"], 2, "PREVENTIVE")
        return ctx

    def test_preview_caps_cycles_per_hour_at_labeler_limit(self, api):
        """PRD §3.3: "The cycle time is ten seconds plus eight-hundredths of a second for every gram by which the planned weight exceeds the mold's `reference_weight_g` — a lighter-than-reference plan never goes below the ten-second base — rounded half-up to two decimal places. Dividing 3600 by that cycle time gives the raw cycles per hour, carried unrounded; when the spec requires inline labeling and the line actually has an inline labeler, the figure is capped at 240 cycles per hour".

Design: Difficulty/combinatorial_formula/cycle_throughput_labeler_cap_blockout_tradeoff"""
        ctx = self._setup_preview_scenario(api)
        res = api.get_throughput_preview(
            ctx["line"]["id"], ENGINEER,
            params={"mold_id": ctx["mold"]["id"],
                    "bottle_spec_id": ctx["spec"]["id"],
                    "planned_weight_g": 22})
        preview = validate_success(res, 200)
        # cycle: 10.0 + 0.08 * max(0, 22 - 20) = 10.16 s
        assert preview["cycle_time_s"] == pytest.approx(10.16, abs=1e-9)
        # raw 3600 / 10.16 = 354.33... is capped at 240 (labeler on both sides)
        assert preview["cycles_per_hour"] == 240, (
            f"raw 354.33 cph must be capped at 240, got "
            f"{preview['cycles_per_hour']}")

    def test_preview_derates_output_for_open_blockouts(self, api):
        """PRD §3.3: "The `hourly_output` is the cycles per hour multiplied by the effective cavities and by a yield fraction of 0.97, rounded down to a whole bottle — so a mold nursing open blockouts previews proportionally lower output, derated linearly with its remaining cavities."

Design: Difficulty/combinatorial_formula/cycle_throughput_labeler_cap_blockout_tradeoff"""
        ctx = self._setup_preview_scenario(api)
        res = api.get_throughput_preview(
            ctx["line"]["id"], ENGINEER,
            params={"mold_id": ctx["mold"]["id"],
                    "bottle_spec_id": ctx["spec"]["id"],
                    "planned_weight_g": 22})
        preview = validate_success(res, 200)
        # 8 base cavities - 2 OPEN blockouts
        assert preview["effective_cavities"] == 6
        # floor(240 * 6 * 0.97) = 1396
        assert preview["hourly_output"] == 1396
