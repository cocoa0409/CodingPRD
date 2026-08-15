"""Agreements, rate-schedule window arithmetic, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    add_rate_schedule,
    assert_agreement,
    create_agreement_payload,
    create_artist,
    create_draft_agreement,
    get_success_data,
    patch_agreement_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]


class TestRateScheduleWindowArithmetic:
    def test_rate_schedule_adjacent_window_allowed(self, api):
        """PRD: "Pure adjacency — one window's start equalling the other's end —
        is allowed."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency
        """
        artist = create_artist(stage_name="Rate Act")
        agreement = create_draft_agreement(artist)
        first = add_rate_schedule(agreement["id"], "TOURING", effective_to="2026-07-01")
        activate_agreement(agreement["id"])

        resp = api.create_rate_schedule(
            {
                "agreement_id": agreement["id"],
                "income_type": "TOURING",
                "in_term_rate_bps": 1600,
                "sunset_rate_bps": 800,
                "sunset_months": 12,
                "effective_from_date": "2026-07-01",
            },
            ADMIN,
        )
        second = validate_success(resp, 201)
        assert second["effective_from_date"] == "2026-07-01", (
            "A successor starting exactly at the predecessor's effective_to_date is legal"
        )
        assert second["agreement_id"] == agreement["id"]
        assert first["effective_to_date"] == "2026-07-01"

    def test_rate_schedule_overlap_rejected(self, api):
        """PRD: "Windows for the same agreement and income type must not overlap:
        a new window conflicts with an existing one when the new start falls before
        the existing end (or the existing window is open-ended) and the existing
        start falls before the new end (or the new window is open-ended)."
        PRD: "A conflict is rejected with `ERR_RATE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency
        """
        artist = create_artist(stage_name="Rate Act 2")
        agreement = create_draft_agreement(artist)
        add_rate_schedule(agreement["id"], "TOURING", effective_to="2026-07-01")
        activate_agreement(agreement["id"])
        get_success_data(api.create_rate_schedule(
            {
                "agreement_id": agreement["id"],
                "income_type": "TOURING",
                "in_term_rate_bps": 1600,
                "sunset_rate_bps": 800,
                "sunset_months": 12,
                "effective_from_date": "2026-07-01",
            },
            ADMIN,
        ))

        resp = api.create_rate_schedule(
            {
                "agreement_id": agreement["id"],
                "income_type": "TOURING",
                "in_term_rate_bps": 1700,
                "sunset_rate_bps": 850,
                "sunset_months": 12,
                "effective_from_date": "2026-06-15",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP)


class TestOptimisticConcurrency:
    def test_occ_agreement_create_rejects_stale_artist_version(self, api):
        """PRD: "Creating an agreement (`POST /agreements`) requires
        `expected_artist_version`, compared against the artist's current
        `version`; a mismatch is rejected with `ERR_STALE_ARTIST_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_agreement_create_rejects_stale_artist_version
        """
        artist = create_artist(stage_name="Occ Act")
        first = create_draft_agreement(artist)
        add_rate_schedule(first["id"], "TOURING")
        pre_activation = get_success_data(api.get_artist(artist["id"], ADMIN))
        activate_agreement(first["id"])  # bumps the artist's version

        resp = api.create_agreement(
            create_agreement_payload(artist["id"], pre_activation["version"],
                                     term_start_date="2028-01-01",
                                     term_end_date="2029-12-31"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ARTIST_VERSION)

        fresh = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert fresh["version"] == pre_activation["version"] + 1
        created = validate_success(api.create_agreement(
            create_agreement_payload(artist["id"], fresh["version"],
                                     term_start_date="2028-01-01",
                                     term_end_date="2029-12-31"),
            ADMIN), 201)
        assert_agreement(created)
        assert created["status"] == "DRAFT"
        after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert after["version"] == fresh["version"] + 1, (
            "A successful agreement create itself increments the artist's version"
        )

    def test_occ_agreement_patch_rejects_stale_version(self, api):
        """PRD: "Editing an agreement (`PATCH /agreements/{id}`) requires
        `expected_agreement_version`, compared against the agreement's current
        `version`; a mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION`
        (HTTP 412)."
        PRD: "While an agreement remains `DRAFT`, an administrator may edit its
        term dates and both policy selectors"

        Design: Corner/cross_cutting_layers/occ_agreement_patch_rejects_stale_version
        """
        artist = create_artist(stage_name="Patch Act")
        agreement = create_draft_agreement(artist)
        v1 = agreement["version"]

        edited = validate_success(api.patch_agreement(
            agreement["id"],
            patch_agreement_payload(v1, term_end_date="2028-06-30"),
            ADMIN))
        assert edited["version"] == v1 + 1

        resp = api.patch_agreement(
            agreement["id"],
            patch_agreement_payload(v1, recoupment_policy="PRO_RATA"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
        unchanged = get_success_data(api.get_agreement(agreement["id"], ADMIN))
        assert unchanged["term_end_date"] == "2028-06-30"
        assert unchanged["recoupment_policy"] == "FIFO"

        applied = validate_success(api.patch_agreement(
            agreement["id"],
            patch_agreement_payload(edited["version"], recoupment_policy="PRO_RATA"),
            ADMIN))
        assert applied["recoupment_policy"] == "PRO_RATA"
        assert applied["version"] == edited["version"] + 1
