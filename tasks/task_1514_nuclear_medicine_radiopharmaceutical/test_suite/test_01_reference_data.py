"""Reference data, response envelope, pagination, and append-only records."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_dose_administration,
    assert_isotope_product,
    assert_patient,
    create_isotope,
    create_isotope_product_payload,
    create_license,
    create_license_payload,
    create_patient_payload,
    is_iso8601_timestamp,
    make_technologist_headers,
    set_clock,
    setup_f18_calibrated_vial,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestIsotopeRegistration:
    def test_decay_constant_computed_at_registration(self, api):
        """PRD §2.5: "When an isotope product is registered, the server also
        computes its `decay_constant_per_minute` as the natural logarithm of two
        divided by `half_life_minutes`, rounded half-up to six decimal places."

        ln(2)/110 = 0.006301... -> 0.006301.

        Design: Corner/entities/create_isotope_product_computes_decay_constant
        """
        set_clock("2026-08-01T08:00:00Z")
        data = validate_success(
            api.create_isotope_product(create_isotope_product_payload(), ADMIN), 201
        )
        assert_isotope_product(data)
        assert data["decay_constant_per_minute"] == pytest.approx(0.006301, abs=1e-9)
        assert is_iso8601_timestamp(data["created_at"]), "created_at is server-stamped"

    def test_missing_half_life_rejected(self, api):
        """PRD §2.9: "Generic field validation (`ERR_VALIDATION`, HTTP 400) covers
        missing required fields, invalid enum values, a non-positive
        `half_life_minutes`, ..."

        Design: Corner/entities/create_isotope_product_missing_required_half_life
        """
        payload = create_isotope_product_payload()
        del payload["half_life_minutes"]
        res = api.create_isotope_product(payload, ADMIN)
        validate_error(res, "ERR_VALIDATION", expected_status=400)

        _, meta = validate_paginated(api.list_isotope_products(ADMIN))
        assert meta["total_count"] == 0, "rejected registration must persist nothing"


class TestNotFound:
    def test_get_nonexistent_order_returns_not_found(self, api):
        """PRD §2.10: "identifiers are validated left to right, and identifiers
        inside the request body are validated after path identifiers; the first
        identifier that does not correspond to an existing resource yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_order_returns_not_found
        """
        res = api.get_dose_order(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestListPagination:
    def test_patient_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned...
        The `offset` parameter skips that many items from the start of the result
        set... The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`." and "every
        list endpoint returns resources sorted by their creation timestamp in
        ascending order."

        The clock is advanced between registrations so the creation-timestamp
        ordering is strict.

        Design: Corner/entities/patient_list_pagination_envelope
        """
        tech = TEST_USERS["technologist_headers"]
        set_clock("2026-08-01T08:00:00Z")
        p1 = validate_success(
            api.create_patient(create_patient_payload(full_name="P One", weight_kg=70), tech),
            201,
        )
        set_clock("2026-08-01T08:01:00Z")
        p2 = validate_success(
            api.create_patient(create_patient_payload(full_name="P Two", weight_kg=80), tech),
            201,
        )
        for p in (p1, p2):
            assert_patient(p)

        page1, meta1 = validate_paginated(
            api.list_patients(ADMIN, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == p1["id"], "ascending creation order: oldest first"

        page2, meta2 = validate_paginated(
            api.list_patients(ADMIN, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] == p2["id"]


class TestAdministrationRecordAppendOnly:
    def test_administration_record_carries_no_version_or_updated_at(self, api):
        """PRD §2.11: "A `DoseAdministration` record and a `RadiationSurvey`
        record each carry only `id` and `created_at`; both `updated_at` and
        `version` are absent on these two resources, because neither is ever
        modified after creation."

        Design: Corner/entities/administration_record_is_append_only
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220)
        set_clock("2026-08-01T10:20:00Z")
        adm = validate_success(
            api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("tech-2")),
            201,
        )
        assert_dose_administration(adm)
        assert "version" not in adm and "updated_at" not in adm
        assert "id" in adm and "created_at" in adm

        fetched = validate_success(api.get_dose_administration(adm["id"], ADMIN), 200)
        assert "version" not in fetched and "updated_at" not in fetched


class TestLicenseUniqueness:
    def test_duplicate_license_number_rejected(self, api):
        """PRD §3.1: "The radiopharmacy license is registered with a
        `license_number` that must be unique across all licenses — a duplicate
        is rejected with `ERR_DUPLICATE_LICENSE_NUMBER` (HTTP 409)..."

        Design: Corner/validations/duplicate_license_number_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        create_license(iso["id"], license_number="L-100")

        res = api.create_license(
            create_license_payload(
                iso["id"],
                license_number="L-100",
                max_possession_mbq=5000,
                isotope_conditions=[
                    {
                        "isotope_product_id": iso["id"],
                        "max_possession_mbq": 4000,
                        "allowed_use": "DIAGNOSTIC",
                    }
                ],
            ),
            ADMIN,
        )
        validate_error(res, "ERR_DUPLICATE_LICENSE_NUMBER", expected_status=409)
