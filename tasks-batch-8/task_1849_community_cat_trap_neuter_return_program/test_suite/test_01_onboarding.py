"""Onboarding: caretakers, colonies, cats, surveys, complaint derivation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    make_coordinator_headers, make_clinic_staff_headers, make_officer_headers,
    create_caretaker, setup_caretaker_with_colony, create_cat,
    create_colony,
    create_partner_clinic, create_clinic_day, list_slots,
    create_survey, create_complaint,
    assert_caretaker, assert_cat, assert_population_survey,
)


class TestCaretakerCreation:
    def test_caretaker_creation_defaults_and_response(self, api):
        """PRD §3.1: "A caretaker account's standing is tracked in `status` as
        `ACTIVE` or `SUSPENDED` and begins `ACTIVE`."
        PRD §3.1: "Registration also records whether the caretaker completed the
        municipal TNR certification course via `certified_tnr`, which defaults to
        false when omitted."

        Design: Corner/entities/caretaker_creation_defaults_and_response
        """
        resp = api.create_caretaker(
            {"full_name": "New Carer", "phone": "555-100", "email": "new@x.com"},
            make_coordinator_headers())
        data = validate_success(resp, expected_status=201)
        assert_caretaker(data)
        assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
        assert data["certified_tnr"] is False, \
            f"certified_tnr must default to false, got {data['certified_tnr']}"
        assert isinstance(data["version"], int)

    def test_caretaker_missing_email_rejected(self, api):
        """PRD §3.1: "A `ProgramCoordinator` registers each caretaker with a
        `full_name`, a free-form contact `phone`, and a contact `email`; the
        `email` must be unique across all caretakers, and a duplicate is rejected
        with `ERR_UNIQUENESS_VIOLATION` (HTTP 409)."
        PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format"

        Design: Corner/entities/caretaker_missing_email_rejected
        """
        resp = api.create_caretaker(
            {"full_name": "No Mail", "phone": "555-101"},
            make_coordinator_headers())
        body = resp.json()
        assert body.get("response_type") == "error", \
            f"expected error envelope, got {resp.status_code}: {resp.text}"
        assert resp.status_code in (400, 422), \
            f"expected 400 or 422 for missing required email, got {resp.status_code}"


class TestCatIntake:
    def test_cat_is_kitten_computed_from_age(self, api):
        """PRD §3.1: "From the age the server derives `is_kitten`, true when the
        cat is younger than six months."

        Design: Corner/entities/cat_is_kitten_computed_from_age
        """
        ct, cth, col = setup_caretaker_with_colony()
        ch = make_coordinator_headers()
        k5 = create_cat(col, headers=ch, intake_tag="K5", sex="MALE",
                        approximate_age_months=5)
        k6 = create_cat(col, headers=ch, intake_tag="K6", sex="FEMALE",
                        approximate_age_months=6)
        assert k5["is_kitten"] is True, \
            f"5 months is younger than six, expected is_kitten true: {k5}"
        assert k6["is_kitten"] is False, \
            f"6 months is NOT younger than six, expected is_kitten false: {k6}"

    def test_cat_initial_state_at_large(self, api):
        """PRD §3.1: "A new cat starts `AT_LARGE`, with `ear_tipped` and
        `vaccinated_rabies` both false and `pathway` unset (null)."

        Design: Corner/state_machines/cat_initial_state_at_large
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="I1", sex="UNKNOWN", approximate_age_months=12)
        assert_cat(cat)
        assert cat["status"] == "AT_LARGE"
        assert cat["ear_tipped"] is False
        assert cat["vaccinated_rabies"] is False
        assert cat.get("pathway") is None

    def test_cat_intake_tag_unique_per_colony(self, api):
        """PRD §3.1: "Intake captures a human-assigned `intake_tag` — a trap log
        number or similar — which must be unique within its colony, with
        duplicates rejected by `ERR_UNIQUENESS_VIOLATION`"

        Design: Corner/entities/cat_intake_tag_unique_per_colony
        """
        ct, cth = create_caretaker()
        ch = make_coordinator_headers()
        col1 = get_success_data(api.create_colony(
            {"name": "T Col 1", "address": "1 T", "caretaker_id": ct["id"],
             "estimated_population": 1}, ch))
        col2 = get_success_data(api.create_colony(
            {"name": "T Col 2", "address": "2 T", "caretaker_id": ct["id"],
             "estimated_population": 1}, ch))
        create_cat(col1, headers=ch, intake_tag="DUP", approximate_age_months=12)

        dup = api.create_cat(col1["id"],
                             {"intake_tag": "DUP", "sex": "FEMALE",
                              "approximate_age_months": 12}, ch)
        validate_error(dup, ApiErrorId.ERR_UNIQUENESS_VIOLATION, expected_status=409)

        other = api.create_cat(col2["id"],
                               {"intake_tag": "DUP", "sex": "FEMALE",
                                "approximate_age_months": 12}, ch)
        data = validate_success(other, expected_status=201)
        assert_cat(data)


class TestColonyReads:
    def test_colony_not_found(self, api):
        """PRD §2.10: "each identifier in the path is resolved in turn, and the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing record."

        Design: Corner/entities/colony_not_found
        """
        resp = api.get_colony(NON_EXISTENT_UUID, make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_colonies_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "`limit` caps the number of items returned: it defaults to 10,
        with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/colonies_list_pagination_envelope
        """
        ct, cth = create_caretaker()
        ch = make_coordinator_headers()
        create_colony(ct, name="P Col 1")
        create_colony(ct, name="P Col 2")
        resp = api.list_colonies(ch, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, \
            f"expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert len(data) == 1


class TestSurveyImmutability:
    def test_population_survey_immutable_no_version(self, api):
        """PRD §2.5: "`PopulationSurvey` is the single exception: as an
        append-only field observation it carries only `id` and `created_at`;
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/population_survey_immutable_no_version
        """
        ct, cth, col = setup_caretaker_with_colony()
        resp = api.create_population_survey(
            col["id"],
            {"surveyed_on": "2026-08-01T00:00:00Z", "observed_count": 5,
             "eartipped_count": 2},
            make_coordinator_headers())
        data = validate_success(resp, expected_status=201)
        assert_population_survey(data)


class TestComplaintDerivation:
    def test_complaint_severity_derived_from_category(self, api):
        """PRD §3.7: "The server stamps `filed_at` from the logical clock and
        derives `severity`: `HIGH` for `PROPERTY_DAMAGE` or `WILDLIFE_CONFLICT`,
        `STANDARD` for the remaining categories."

        Design: Corner/entities/complaint_severity_derived_from_category
        """
        ct, cth, col = setup_caretaker_with_colony()
        oh = make_officer_headers()
        high = create_complaint(col, officer_headers=oh, complainant_name="N1",
                                category="PROPERTY_DAMAGE")
        std = create_complaint(col, officer_headers=oh, complainant_name="N2",
                               category="NOISE")
        assert high["severity"] == "HIGH", \
            f"PROPERTY_DAMAGE must derive HIGH, got {high['severity']}"
        assert std["severity"] == "STANDARD", \
            f"NOISE must derive STANDARD, got {std['severity']}"


class TestReverseReachability:
    def test_fk_reverse_reachability_slots_and_cats(self, api):
        """PRD §3.2: "On creation the server materializes the day's full slot
        inventory — `base_capacity` plus `surge_capacity` `ClinicSlot` rows, each
        recorded against the day's `clinic_day_id`, each standing `OPEN`, and each
        assigned a sequential `slot_index` starting at 1"
        PRD §3.1: "The cats of a colony can be listed with a `status` filter"

        Design: Corner/entities/fk_reverse_reachability_slots_and_cats
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="R1", approximate_age_months=12)
        clinic = create_partner_clinic(name="RevVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-30T00:00:00Z",
                                base_capacity=3, surge_capacity=0)

        cats, _ = validate_paginated(
            api.list_colony_cats(col["id"], make_coordinator_headers()))
        assert any(c["id"] == cat["id"] for c in cats), \
            "colony cats list must contain the created cat"

        slots, _ = validate_paginated(
            api.list_clinic_day_slots(day["id"], make_clinic_staff_headers()))
        assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"
        assert sorted(s["slot_index"] for s in slots) == [1, 2, 3], \
            f"slot_index must be sequential from 1: {[s['slot_index'] for s in slots]}"
        assert all(s["status"] == "OPEN" for s in slots)
