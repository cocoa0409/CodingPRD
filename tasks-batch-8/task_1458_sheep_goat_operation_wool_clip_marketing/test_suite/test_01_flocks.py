"""Flock lifecycle: creation defaults, envelope, validation, not-found, pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_flock,
    create_flock,
    create_flock_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFlockCreation:

    def test_create_flock_applies_defaults(self, api, ranch_manager_headers):
        """PRD §3.1: "A `RanchManager` opens a flock by supplying a `flock_name`
        (unique across all flocks), a `species` of either `SHEEP` or `GOAT`
        (immutable once created), a `baseline_headcount` of at least 1, and
        optionally a `guardian_dog_count` recording the livestock guardian dogs
        currently assigned (defaulting to 0 and never negative). The flock is
        born `ACTIVE` in its `flock_status`, and its `current_headcount` is
        initialized to `baseline_headcount`."
        PRD §2.4: "Every persisted resource is addressed by an `id` that is a
        server-minted UUID with no type prefix."

        Design: Corner/entities/create_flock_applies_defaults
        """
        resp = api.create_flock(
            {"flock_name": "Default Ranch", "species": "GOAT", "baseline_headcount": 120},
            ranch_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_flock(data)
        assert data["guardian_dog_count"] == 0, "guardian_dog_count must default to 0"
        assert data["flock_status"] == "ACTIVE", "flock is born ACTIVE"
        assert data["current_headcount"] == 120, (
            "current_headcount initialized from baseline_headcount"
        )
        assert data["version"] == 1
        assert data["withdrawal_until"] is None, "no treatments -> no live withdrawal gate"

    def test_create_flock_missing_required_species_returns_400(self, api, ranch_manager_headers):
        """PRD §2.8: "Request shape — required fields present, enum values valid,
        numeric ranges respected (weights and acres strictly positive, head
        counts and `ewes_bred` at least 1, percentages between 0 and 100
        inclusive), start dates strictly before end dates, and conditional
        field shapes satisfied (a `MEAT` sale carries `avg_weight_lbs` and
        `base_price_per_cwt_cents` and must not carry `per_head_price_cents`,
        while a `BREEDING` sale carries `per_head_price_cents` and must not
        carry the meat pair; a grazing move carries exactly one of
        `pasture_id` or `contract_id`), else `ERR_VALIDATION`."

        Design: Corner/entities/create_flock_missing_required_species_returns_400
        """
        resp = api.create_flock(
            {"flock_name": "No Species Ranch", "baseline_headcount": 100},
            ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)
        _, meta = validate_paginated(api.list_flocks(ranch_manager_headers))
        assert meta["total_count"] == 0, "rejected creation must not persist a flock"

    def test_create_flock_invalid_enum_species_returns_400(self, api, ranch_manager_headers):
        """PRD §3.1: "a `species` of either `SHEEP` or `GOAT`".
        PRD §2.8: "Request shape — required fields present, enum values valid,
        numeric ranges respected (weights and acres strictly positive, head
        counts and `ewes_bred` at least 1, percentages between 0 and 100
        inclusive), start dates strictly before end dates, and conditional
        field shapes satisfied (a `MEAT` sale carries `avg_weight_lbs` and
        `base_price_per_cwt_cents` and must not carry `per_head_price_cents`,
        while a `BREEDING` sale carries `per_head_price_cents` and must not
        carry the meat pair; a grazing move carries exactly one of
        `pasture_id` or `contract_id`), else `ERR_VALIDATION`."

        Design: Corner/entities/create_flock_invalid_enum_species_returns_400
        """
        resp = api.create_flock(
            {"flock_name": "Llama Ranch", "species": "LLAMA", "baseline_headcount": 100},
            ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    def test_get_flock_not_found_returns_404(self, api, ranch_manager_headers):
        """PRD §2.8: "Existence — path identifiers resolve left-to-right, then
        body foreign-key references (`flock_id`, `season_id`, `clip_id`,
        `lot_id`, `pasture_id`, `contract_id`, `crew_id`) resolve to existing
        rows, else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_flock_not_found_returns_404
        """
        resp = api.get_flock(NON_EXISTENT_UUID, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_list_flocks_pagination_envelope(self, api, ranch_manager_headers):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10, with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0."
        PRD §3.1: "Flocks can be listed with `limit` and `offset` and filtered
        by `species` or `flock_status`".

        Design: Corner/entities/list_flocks_pagination_envelope
        """
        for name, species in (("P1", "SHEEP"), ("P2", "SHEEP"), ("P3", "GOAT")):
            create_flock(flock_name=name, species=species, baseline_headcount=100)

        page1, meta1 = validate_paginated(
            api.list_flocks(ranch_manager_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        goats, meta_goats = validate_paginated(
            api.list_flocks(ranch_manager_headers, params={"limit": 2, "offset": 0, "species": "GOAT"}))
        assert len(goats) == 1, "exactly one GOAT flock was created"
        assert meta_goats["total_count"] == 1
        assert meta_goats["has_more"] is False
        assert goats[0]["species"] == "GOAT"
