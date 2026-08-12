"""Temporal overlap resources: half-open tariff-measure windows (adjacency
allowed) versus closed claim periods (shared date is an overlap)."""
from test_helpers import ApiErrorId, add_claim, add_measure, api_client, onboard_client, TEST_USERS, validate_error, validate_paginated

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_adjacent_measure_windows_are_accepted(api):
    """PRD 3.3: "Two `ACTIVE` measures sharing the same `measure_type` and
    `hts_code_prefix` may not have overlapping half-open windows, though
    adjacency — one measure's `effective_to` landing exactly on the other's
    `effective_from` — is allowed; overlaps are rejected with
    `ERR_MEASURE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/measure_half_open_adjacency
    """
    first = add_measure(
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z"
    )
    assert first["status"] == "ACTIVE"

    adjacent = add_measure(
        surcharge_bps=750, effective_from="2026-06-01T00:00:00Z"
    )
    assert adjacent["status"] == "ACTIVE", (
        "from == prior to is adjacency, not overlap, under half-open windows"
    )

    data, meta = validate_paginated(
        api_client.list_tariff_measures(
            ADMIN, params={"hts_code_prefix": "6203", "measure_type": "SECTION_301"}
        )
    )
    assert meta["total_count"] == 2


def test_overlapping_measure_window_is_rejected(api):
    """PRD 3.3: "Two `ACTIVE` measures sharing the same `measure_type` and
    `hts_code_prefix` may not have overlapping half-open windows, though
    adjacency — one measure's `effective_to` landing exactly on the other's
    `effective_from` — is allowed; overlaps are rejected with
    `ERR_MEASURE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/measure_half_open_adjacency
    """
    add_measure(
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z"
    )

    res = api_client.create_tariff_measure(
        {
            "hts_code_prefix": "6203",
            "measure_type": "SECTION_301",
            "surcharge_bps": 500,
            "effective_from": "2026-05-15T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_MEASURE_WINDOW_OVERLAP)

    data, meta = validate_paginated(
        api_client.list_tariff_measures(
            ADMIN, params={"hts_code_prefix": "6203", "measure_type": "SECTION_301"}
        )
    )
    assert meta["total_count"] == 1


def test_back_to_back_claim_periods_are_accepted(api):
    """PRD 3.4: "the new claim's period must not overlap the period of any other
    claim of the same client and same `claim_type` that is not in a terminal
    state; because periods are closed intervals, two claims that share even a
    single date are overlapping (`ERR_CLAIM_PERIOD_OVERLAP`), while genuinely
    back-to-back periods are allowed."

    Design: Difficulty/resource_temporal_overlap/claim_closed_period_shared_date
    """
    client = onboard_client()
    first = add_claim(
        client["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-03-31T00:00:00Z"
    )
    assert first["status"] == "DRAFT"

    second = add_claim(
        client["id"], period_start="2026-04-01T00:00:00Z", period_end="2026-06-30T00:00:00Z"
    )
    assert second["status"] == "DRAFT", (
        "next start == prior end + 1 day: back-to-back periods share no date"
    )

    data, meta = validate_paginated(
        api_client.list_claims(ANALYST, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 2


def test_claim_periods_sharing_a_single_date_overlap(api):
    """PRD 3.4: "because periods are closed intervals, two claims that share
    even a single date are overlapping (`ERR_CLAIM_PERIOD_OVERLAP`), while
    genuinely back-to-back periods are allowed."

    Design: Difficulty/resource_temporal_overlap/claim_closed_period_shared_date
    """
    client = onboard_client()
    add_claim(
        client["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-03-31T00:00:00Z"
    )

    res = api_client.create_claim(
        {
            "client_id": client["id"],
            "claim_type": "DIRECT_IDENTIFICATION",
            "period_start": "2026-03-31T00:00:00Z",
            "period_end": "2026-05-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_PERIOD_OVERLAP)

    data, meta = validate_paginated(
        api_client.list_claims(ANALYST, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 1, "the overlapping claim must not persist"
