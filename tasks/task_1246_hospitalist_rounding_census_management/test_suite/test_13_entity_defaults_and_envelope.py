"""Entity creation defaults, observation-axis initialization, not-found,
request-shape validation, and pagination envelope tests.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    create_hospitalist, create_patient, NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestCreateHospitalistAppliesDefaults:
    """Corner instance: create_hospitalist_applies_defaults."""

    def test_defaults_applied(self, api):
        """PRD §3.1: "Creating a hospitalist takes `full_name`; a `specialty`
        of `INTERNAL_MEDICINE`, `FAMILY_MEDICINE`, or `ICU`; an optional
        `employment_status` defaulting to `ACTIVE` (the other values being
        `ON_LEAVE` and `INACTIVE`); an optional `max_census_cap` defaulting
        to 16 and never below 1; and an optional `night_eligible` flag,
        defaulting to true".
        PRD §2.5: "`current_census` is the count of that hospitalist's
        assignments in status `ACTIVE`" — zero on a fresh hospitalist;
        "`pending_offers` is the count of admissions in status `OFFERED`
        whose `offered_to_hospitalist_id` names this hospitalist" — zero on
        a fresh hospitalist; "`distribution_eligible` begins as true".

        Design: Corner/entities/create_hospitalist_applies_defaults
        """
        resp = api.create_hospitalist({"full_name": "H Def", "specialty": "ICU"}, ADMIN)
        h = validate_success(resp, expected_status=201)
        assert h["max_census_cap"] == 16
        assert h["night_eligible"] is True
        assert h["employment_status"] == "ACTIVE"
        assert h["current_census"] == 0
        assert h["pending_offers"] == 0
        assert h["distribution_eligible"] is True
        assert h["version"] == 1


class TestCreatePatientObservationInitializesObsFields:
    """Corner instance: create_patient_observation_initializes_obs_fields."""

    def test_observation_stay_initializes_obs_active(self, api):
        """PRD §3.2: "The observation axis, `observation_status`, begins at
        `OBS_ACTIVE` when `stay_type` is `OBSERVATION` and at `NONE`
        otherwise; `observation_started_at` equals `admitted_at` for
        observation patients and is null for inpatients."
        PRD §3.2: "The admission axis, `admission_status`, begins at
        `ADMITTED`".
        PRD §2.2: "All timestamps are ISO 8601 UTC with three fractional
        digits" — so 2026-05-01T08:00:00Z renders as
        2026-05-01T08:00:00.000Z.

        Design: Corner/entities/create_patient_observation_initializes_obs_fields
        """
        p_obs = create_patient(mrn="C001", acuity="LOW", admit_source="ED",
                               stay_type="OBSERVATION", admitted_at="2026-05-01T08:00:00Z")
        assert p_obs["observation_status"] == "OBS_ACTIVE"
        assert p_obs["observation_started_at"] == "2026-05-01T08:00:00.000Z"
        assert p_obs["admission_status"] == "ADMITTED"

        p_in = create_patient(mrn="C002", acuity="LOW", admit_source="ED",
                              stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        assert p_in["observation_status"] == "NONE"
        assert p_in["observation_started_at"] is None
        assert p_in["admission_status"] == "ADMITTED"


class TestGetPatientNotFound:
    """Corner instance: get_patient_not_found_returns_404."""

    def test_get_missing_patient_returns_404(self, api):
        """PRD §2.7 item 4: "Identifiers referenced in the path and in the
        body exist, validated left-to-right along the request — the first
        missing id yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard error envelope format" with `response_type` "error".

        Design: Corner/entities/get_patient_not_found_returns_404
        """
        resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"


class TestCreatePatientMissingRequiredMrn:
    """Corner instance: create_patient_missing_required_mrn_returns_invalid_request."""

    def test_missing_mrn_rejected(self, api):
        """PRD §2.7 item 3: "Required fields are present, types are valid,
        enum members are known, date and datetime formats parse ... —
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "Registration is a `GroupAdmin` act capturing `mrn` — the
        medical record number, unique across all patients ... plus `acuity`
        ..., `admit_source` ..., and `stay_type`" — mrn is a required input.

        Design: Corner/entities/create_patient_missing_required_mrn_returns_invalid_request
        """
        resp = api.create_patient(
            {"acuity": "MEDIUM", "admit_source": "ED", "stay_type": "INPATIENT"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCreatePatientInvalidEnumAcuity:
    """Corner instance: create_patient_invalid_enum_acuity_rejected."""

    def test_unknown_acuity_rejected(self, api):
        """PRD §2.7 item 3: "Required fields are present, types are valid,
        enum members are known ... — `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "`acuity` (`HIGH`, `MEDIUM`, or `LOW`)".

        Design: Corner/entities/create_patient_invalid_enum_acuity_rejected
        """
        resp = api.create_patient(
            {"mrn": "C004", "acuity": "CRITICAL", "admit_source": "ED",
             "stay_type": "INPATIENT"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestListHospitalistsPaginationEnvelope:
    """Corner instance: list_hospitalists_pagination_envelope."""

    def test_limit_offset_paginate(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0. Every list response orders its rows by
        `created_at` ascending, and its `meta` object carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_hospitalists_pagination_envelope
        """
        for name in ("H One", "H Two", "H Three"):
            create_hospitalist(name, "ICU")
        # Page 1: limit=2, offset=0
        rows1, meta1 = validate_paginated(api.list_hospitalists(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        # Page 2: limit=2, offset=2
        rows2, meta2 = validate_paginated(api.list_hospitalists(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_default_limit_applied_when_omitted(self, api):
        """PRD §2.3: "`limit`, defaulting to 10 with a minimum of 1 and a
        maximum of 100, and `offset`, defaulting to 0."

        Design: Corner/entities/list_hospitalists_pagination_envelope
        """
        create_hospitalist("H Only", "ICU")
        rows, meta = validate_paginated(api.list_hospitalists(ADMIN))
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestSuccessEnvelopeOnRead:
    """Corner instance: success_envelope_on_read."""

    def test_object_read_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        `meta.api_request_id`, `meta.api_request_timestamp`,
        `response_type` of "object" for a single resource, and the resource
        under `data`.
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/success_envelope_on_read
        """
        h = create_hospitalist("H One", "ICU")
        resp = api.get_hospitalist(h["id"], ADMIN)
        data = validate_success(resp)
        assert data["id"] == h["id"]
