"""Pole register, budget uniqueness, and the OCC-guarded GIS patch (PRD §2.7, §3.1)."""
import pytest

from test_helpers import (
    CLOCK_DEFAULT_ISO,
    ApiErrorId,
    assert_budget_invariant,
    assert_instant_equals,
    assert_pole,
    assert_program_budget,
    create_budget_payload,
    create_pole,
    create_pole_payload,
    gis_patch_payload,
    validate_error,
    validate_success,
)


class TestPoleCreation:
    def test_pole_creation_applies_defaults(self, api, program_manager_headers):
        """PRD §3.1: "A pole begins `IN_SERVICE`; its lifecycle states are `IN_SERVICE`,
        `MONITOR`, `PRIORITY_REJECT`, and the terminal `REPLACED`."
        PRD §3.1: "Joint-use presence is declared through the optional `joint_use` flag,
        defaulting to false, and `attachment_count_declared`, the number of third-party
        attachments on record, defaulting to zero and never negative."
        PRD §3.1: "Computed condition fields — `current_remaining_strength_pct`,
        `current_classification` (initially `NONE`), `last_inspection_date`,
        `last_treatment_date`, and `open_treatment_count` — start empty or zero and are
        maintained by the inspection and treatment workflows below."

        Design: Corner/entities/pole_creation_applies_defaults
        """
        resp = api.create_pole(
            create_pole_payload(
                pole_number="P-DEF", species="LARCH", original_class="2",
                install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                gis_tag="RURAL", height_ft=35,
            ),
            program_manager_headers,
        )
        pole = validate_success(resp, expected_status=201)
        assert_pole(pole)
        assert pole["status"] == "IN_SERVICE"
        assert pole["joint_use"] is False
        assert pole["attachment_count_declared"] == 0
        assert pole["current_classification"] == "NONE"
        assert pole["current_remaining_strength_pct"] is None
        assert pole["open_treatment_count"] == 0
        assert pole["last_inspection_date"] is None
        assert pole["last_treatment_date"] is None
        # PRD §2.5: "At server startup the logical clock is set to exactly
        # `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time."
        assert_instant_equals(pole["created_at"], CLOCK_DEFAULT_ISO, "pole.created_at")

    def test_pole_create_missing_required_field_rejected(self, api, program_manager_headers):
        """PRD §3.1: "Registering a `Pole` requires a unique non-empty `pole_number`".
        PRD §2.8: "required body fields are present, types are valid, enum values are in
        their declared domains, and numeric ranges are respected, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/pole_create_missing_required_field_rejected
        """
        payload = create_pole_payload(
            species="LARCH", original_class="2", install_date="2001-05-01",
            gis_lat=46.0, gis_lon=-121.0, gis_tag="RURAL", height_ft=35,
        )
        payload.pop("pole_number")
        resp = api.create_pole(payload, program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pole_create_invalid_enum_rejected(self, api, program_manager_headers):
        """PRD §3.1: "a `species` of `SOUTHERN_PINE`, `DOUGLAS_FIR`, `WESTERN_RED_CEDAR`,
        or `LARCH`".
        PRD §2.8: "required body fields are present, types are valid, enum values are in
        their declared domains, and numeric ranges are respected, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/pole_create_invalid_enum_rejected
        """
        resp = api.create_pole(
            create_pole_payload(
                pole_number="P-IE", species="OAK", original_class="2",
                install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                gis_tag="RURAL", height_ft=35,
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pole_duplicate_number_rejected(self, api, program_manager_headers):
        """PRD §3.1: "Registering a `Pole` requires a unique non-empty `pole_number`
        (a duplicate is rejected with `ERR_DUPLICATE_POLE_NUMBER`)".

        Design: Corner/entities/pole_duplicate_number_rejected
        """
        first = api.create_pole(
            create_pole_payload(
                pole_number="P-DUP", species="LARCH", original_class="2",
                install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                gis_tag="RURAL", height_ft=35,
            ),
            program_manager_headers,
        )
        validate_success(first, expected_status=201)
        resp = api.create_pole(
            create_pole_payload(
                pole_number="P-DUP", species="DOUGLAS_FIR", original_class="1",
                install_date="1999-01-01", gis_lat=46.1, gis_lon=-121.1,
                gis_tag="URBAN", height_ft=45,
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLE_NUMBER)


class TestBudgetUniqueness:
    def test_duplicate_fiscal_year_rejected(self, api, program_manager_headers):
        """PRD §3.1: "the fiscal year must be unique across all budgets — a duplicate
        is rejected with `ERR_DUPLICATE_FISCAL_YEAR`".

        Design: Corner/validations/duplicate_fiscal_year_rejected
        """
        first = api.create_budget(
            create_budget_payload(fiscal_year=2026, total_cents=1000),
            program_manager_headers,
        )
        budget = validate_success(first, expected_status=201)
        assert_program_budget(budget)
        assert_budget_invariant(budget)
        resp = api.create_budget(
            create_budget_payload(fiscal_year=2026, total_cents=2000),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR)


class TestGisAttributePatchOcc:
    def test_gis_patch_success_updates_attributes(self, api, program_manager_headers):
        """PRD §3.1: "a `ProgramManager` may supersede a pole's `gis_lat`, `gis_lon`,
        and `gis_tag` through the GIS-attribute patch" and "a successful patch
        increments the pole's `version` by one."

        Design: Corner/complexity_layers/gis_patch_success_updates_attributes
        """
        pole = create_pole(
            pole_number="P-GIS", species="LARCH", original_class="2",
            install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
            gis_tag="RURAL", height_ft=35,
        )
        resp = api.patch_pole_gis_attributes(
            pole["id"],
            gis_patch_payload(pole["version"], gis_lat=46.9, gis_lon=-121.9,
                              gis_tag="COASTAL"),
            program_manager_headers,
        )
        patched = validate_success(resp, expected_status=200)
        assert patched["gis_tag"] == "COASTAL"
        assert patched["gis_lat"] == pytest.approx(46.9)
        assert patched["gis_lon"] == pytest.approx(-121.9)
        assert patched["version"] == pole["version"] + 1, (
            f"GIS patch must increment version by one: {pole['version']} -> "
            f"{patched['version']}"
        )

    def test_occ_stale_pole_version_rejected(self, api, program_manager_headers):
        """PRD §2.7: "If the pole's current `version` has advanced — for example because
        a quality-review cascade refreshed the pole's classification fields after the
        client's read — the patch is rejected with `ERR_STALE_POLE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_pole_version_rejected
        """
        pole = create_pole(
            pole_number="P-OCC", species="LARCH", original_class="2",
            install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
            gis_tag="RURAL", height_ft=35,
        )
        first = api.patch_pole_gis_attributes(
            pole["id"],
            gis_patch_payload(pole["version"], gis_lat=46.5, gis_lon=-121.5,
                              gis_tag="URBAN"),
            program_manager_headers,
        )
        patched = validate_success(first, expected_status=200)
        assert patched["gis_tag"] == "URBAN"
        assert patched["version"] == pole["version"] + 1

        stale = api.patch_pole_gis_attributes(
            pole["id"],
            gis_patch_payload(pole["version"], gis_lat=47.0, gis_lon=-122.0,
                              gis_tag="COASTAL"),
            program_manager_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_POLE_VERSION)

        reread = validate_success(api.get_pole(pole["id"], program_manager_headers))
        assert reread["gis_tag"] == "URBAN", "stale patch must not overwrite gis_tag"
        assert reread["version"] == patched["version"]
