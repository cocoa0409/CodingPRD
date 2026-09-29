"""Carrier records, market-analysis cycle records and analysis score rows.

Every test builds its own state from an empty database through the endpoints the
PRD declares and asserts only what the PRD states.
"""

from test_helpers import (
    ANALYST,
    SUPERVISOR,
    ApiErrorId,
    analysis_cycle_payload,
    api_client,
    assert_analysis_cycle,
    assert_analysis_score,
    assert_insurer,
    create_analysis_cycle,
    insurer_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    refresh_market_data,
    register_insurer,
    score_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

api = api_client

AURORA = {
    "name": "Aurora Mutual Insurance Company",
    "naic_code": "10001",
    "annual_premium_written_cents": 1_200_000_000,
    "policy_count_in_force": 40_000,
    "confirmed_complaints_12mo": 120,
    "financial_stress_score": 60,
    "consumer_trend_score": 50,
}
BOREAL = {
    "name": "Boreal Casualty Company",
    "naic_code": "10002",
    "annual_premium_written_cents": 6_000_000_000,
    "policy_count_in_force": 100_000,
    "confirmed_complaints_12mo": 500,
    "financial_stress_score": 80,
    "consumer_trend_score": 70,
}
CEDAR = {
    "name": "Cedar Indemnity Company",
    "naic_code": "10003",
    "annual_premium_written_cents": 300_000_000,
    "policy_count_in_force": 100_000,
    "confirmed_complaints_12mo": 99,
    "financial_stress_score": 20,
    "consumer_trend_score": 10,
    "license_status": "SUSPENDED",
}


def test_insurer_creation_computes_the_complaint_ratio_and_risk_tier():
    """Registration derives the surveillance figures in the creation response itself.

    PRD §3.1: "The complaint ratio is the trailing-twelve-month confirmed complaint count multiplied by one thousand and divided by policies in force, rounded half up to two decimal places, and stored as `complaint_ratio_per_1k`."
    PRD §3.1: "Otherwise `risk_tier` is read off the rounded ratio: `HIGH` when the ratio is 5.00 or more, otherwise `ELEVATED` when it is 2.50 or more, otherwise `MODERATE` when it is 1.00 or more, otherwise `LOW`."
    PRD §3.1: "Registration also initialises the three enforcement counters — `open_exam_count`, `pending_enforcement_exam_count` and `lifetime_restitution_ordered_cents` — to 0."

    Design: Corner/entities/insurer_creation_returns_every_declared_field_with_computed_ratio_and_tier
    """
    data = validate_success(api.register_insurer(insurer_payload(**AURORA), ANALYST), 201)
    assert_insurer(data)
    assert data["name"] == "Aurora Mutual Insurance Company"
    assert data["naic_code"] == "10001"
    # 120 * 1000 / 40000 = 3.00, which is at least 2.50 and below 5.00.
    assert data["complaint_ratio_per_1k"] == 3.00
    assert data["risk_tier"] == "ELEVATED"
    assert data["open_exam_count"] == 0
    assert data["pending_enforcement_exam_count"] == 0
    assert data["lifetime_restitution_ordered_cents"] == 0
    assert data["license_status"] == "LICENSED"
    assert data["version"] == 1


def test_insurer_retrieval_returns_the_stored_row_unchanged():
    """A pure read returns the persisted ratio and tier and mutates nothing.

    PRD §3.1: "The complaint ratio is the trailing-twelve-month confirmed complaint count multiplied by one thousand and divided by policies in force, rounded half up to two decimal places, and stored as `complaint_ratio_per_1k`."
    PRD §2.4: "Most record types additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record — including mutations that touch only derived counters."

    Design: Corner/entities/insurer_retrieval_returns_the_stored_row_unchanged
    """
    created = register_insurer(**AURORA)

    data = validate_success(api.get_insurer(created["id"], SUPERVISOR))
    assert_insurer(data)
    assert data["id"] == created["id"]
    assert data["complaint_ratio_per_1k"] == 3.00
    assert data["risk_tier"] == "ELEVATED"
    assert data["annual_premium_written_cents"] == 1_200_000_000
    assert data["policy_count_in_force"] == 40_000
    assert data["confirmed_complaints_12mo"] == 120
    # The read is not a mutation, so the version stays where creation left it.
    assert data["version"] == 1


def test_insurer_listing_reports_the_pagination_envelope_and_honours_filters():
    """The list envelope carries the declared pagination fields, and the filters narrow the same query.

    PRD §2.3: "`limit` defaults to 10, may be no lower than 1 and no higher than 100."
    PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`, `total_count` (the count of rows matching the filter before the window is applied) and `has_more` (true when rows remain beyond the current window)."
    PRD §3.1: "Carriers may be listed with an optional `license_status` filter and an optional `risk_tier` filter."

    Design: Corner/entities/insurer_listing_returns_the_pagination_envelope_and_honours_filters
    """
    register_insurer(**AURORA)
    boreal = register_insurer(**BOREAL)
    cedar = register_insurer(**CEDAR)

    rows, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3

    page1, meta1 = validate_paginated(api.list_insurers(ANALYST, {"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_insurers(ANALYST, {"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    # BOREAL alone reaches 500 * 1000 / 100000 = 5.00 and therefore risk tier HIGH.
    high_rows, high_meta = validate_paginated(api.list_insurers(ANALYST, {"risk_tier": "HIGH"}))
    assert high_meta["total_count"] == 1
    assert [row["id"] for row in high_rows] == [boreal["id"]]
    assert high_rows[0]["risk_tier"] == "HIGH"

    susp_rows, susp_meta = validate_paginated(
        api.list_insurers(ANALYST, {"license_status": "SUSPENDED"})
    )
    assert susp_meta["total_count"] == 1
    assert [row["id"] for row in susp_rows] == [cedar["id"]]
    assert susp_rows[0]["license_status"] == "SUSPENDED"


def test_pagination_limit_bounds_are_enforced_on_list_endpoints():
    """limit is inclusive on both ends of 1..100, and a value outside the range is malformed.

    PRD §2.3: "`limit` defaults to 10, may be no lower than 1 and no higher than 100. `offset` defaults to 0 and may be no lower than 0. A value outside those ranges is a malformed request."
    PRD §2.11: "6. **Request shape** — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/pagination_limit_bounds_are_enforced_on_list_endpoints
    """
    register_insurer(**AURORA)

    validate_error(
        api.list_insurers(ANALYST, {"limit": 0}), ApiErrorId.ERR_INVALID_REQUEST.value
    )
    validate_error(
        api.list_insurers(ANALYST, {"limit": 101}), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    rows, meta = validate_paginated(api.list_insurers(ANALYST, {"limit": 1}))
    assert len(rows) == 1
    assert meta["limit"] == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api.list_insurers(ANALYST, {"limit": 100, "offset": 0}))
    assert len(rows) == 1
    assert meta["limit"] == 100
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_insurer_required_fields_are_each_individually_mandatory():
    """Omitting either naic_code or policy_count_in_force is independently fatal and persists nothing.

    PRD §3.1: "A `MarketAnalyst` registers a regulated carrier by supplying its `name` (between 1 and 120 characters), its `naic_code` (exactly five digits, unique across all carriers — a collision is `ERR_DUPLICATE_IDENTIFIER`), its `annual_premium_written_cents` for the reference period, its `policy_count_in_force` at period end, its `confirmed_complaints_12mo`, and the two supplied indicators: `financial_stress_score` and `consumer_trend_score`, each an integer between 0 and 100 inclusive."
    PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing;"

    Design: Corner/entities/insurer_required_fields_are_each_individually_mandatory
    """
    without_naic = insurer_payload(**AURORA)
    without_naic.pop("naic_code")
    validate_error(
        api.register_insurer(without_naic, ANALYST), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    without_policy_count = insurer_payload(**AURORA)
    without_policy_count.pop("policy_count_in_force")
    validate_error(
        api.register_insurer(without_policy_count, ANALYST),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["total_count"] == 0
    assert rows == []


def test_insurer_license_status_defaults_to_licensed_when_omitted():
    """An omitted license_status yields LICENSED; an explicit value wins over the default.

    PRD §3.1: "An optional `license_status` records the certificate-of-authority position in the examining state and defaults to `LICENSED`; the other permitted values are `SUSPENDED` and `WITHDRAWN`."

    Design: Corner/entities/insurer_license_status_defaults_to_licensed_when_omitted
    """
    defaulted = validate_success(api.register_insurer(insurer_payload(**AURORA), ANALYST), 201)
    assert defaulted["license_status"] == "LICENSED"

    explicit = validate_success(
        api.register_insurer(
            insurer_payload(**dict(BOREAL, license_status="WITHDRAWN")), ANALYST
        ),
        201,
    )
    assert explicit["license_status"] == "WITHDRAWN"


def test_insurer_computed_fields_are_rederived_on_every_market_data_patch():
    """Patching only the denominator re-derives both computed fields and bumps the version.

    PRD §3.1: "Every refresh re-derives `complaint_ratio_per_1k` and `risk_tier` by exactly the rule above and increments the carrier's `version` by 1."

    Design: Corner/entities/insurer_computed_fields_are_rederived_on_every_market_data_patch
    """
    created = register_insurer(**AURORA)
    assert created["complaint_ratio_per_1k"] == 3.00
    assert created["risk_tier"] == "ELEVATED"
    assert created["version"] == 1

    # 120 * 1000 / 20000 = 6.00, which is 5.00 or more and therefore HIGH.
    refreshed = refresh_market_data(created["id"], policy_count_in_force=20_000)
    assert refreshed["complaint_ratio_per_1k"] == 6.00
    assert refreshed["risk_tier"] == "HIGH"
    assert refreshed["policy_count_in_force"] == 20_000
    assert refreshed["confirmed_complaints_12mo"] == 120
    assert refreshed["version"] == 2


def test_insurer_system_fields_are_server_minted():
    """id, version and the audit stamps come from the server and the logical clock.

    PRD §2.4: "Every record the service persists is addressed by an `id`: a server-minted UUID with no type prefix."
    PRD §2.4: "All server-generated time originates from a **logical clock**, never from wall-clock time."
    PRD §2.4: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/entities/insurer_system_fields_are_server_minted
    """
    payload = insurer_payload(**AURORA)
    data = validate_success(api.register_insurer(payload, ANALYST), 201)

    assert is_valid_uuid(data["id"])
    assert "id" not in payload
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert data["created_at"].startswith("2026-08-01T00:00:00")
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["updated_at"] == data["created_at"]


def test_insurer_enum_and_numeric_range_constraints_are_enforced():
    """An out-of-set enum, an out-of-band indicator and a negative count all reject and persist nothing.

    PRD §3.1: "An optional `license_status` records the certificate-of-authority position in the examining state and defaults to `LICENSED`; the other permitted values are `SUSPENDED` and `WITHDRAWN`."
    PRD §3.1: "All four numeric inputs from premium through complaints must be zero or greater."
    PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative;"

    Design: Corner/entities/insurer_enum_and_numeric_range_constraints_are_enforced
    """
    validate_error(
        api.register_insurer(
            insurer_payload(**dict(AURORA, license_status="REVOKED")), ANALYST
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    # financial_stress_score is declared an integer between 0 and 100 inclusive.
    validate_error(
        api.register_insurer(
            insurer_payload(**dict(AURORA, financial_stress_score=101)), ANALYST
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.register_insurer(
            insurer_payload(**dict(AURORA, confirmed_complaints_12mo=-1)), ANALYST
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["total_count"] == 0
    assert rows == []


def test_analysis_cycle_creation_applies_its_default_mode_and_slot_ledger():
    """A new cycle opens in DRAFT with the slot ledger balanced and the default exam mode applied.

    PRD §3.2: "An optional `default_exam_mode` is stamped onto every examination the cycle creates and defaults to `ON_SITE`; the only alternative is `DESK`."
    PRD §3.2: "A new cycle opens in `DRAFT` with `slots_committed` at 0, `slots_available` equal to `target_slot_capacity`, and `scored_insurer_count` and `selected_target_count` both 0."

    Design: Corner/entities/analysis_cycle_creation_applies_its_default_mode_and_slot_ledger
    """
    payload = analysis_cycle_payload(
        cycle_label="2026-H2-MARKET-ANALYSIS",
        reference_period_start="2025-07-01",
        reference_period_end="2026-06-30",
        target_slot_capacity=3,
        default_fieldwork_start="2026-09-01",
        default_fieldwork_end="2026-11-30",
    )
    assert "default_exam_mode" not in payload

    data = validate_success(api.create_analysis_cycle(payload, ANALYST), 201)
    assert_analysis_cycle(data)
    assert data["default_exam_mode"] == "ON_SITE"
    assert data["status"] == "DRAFT"
    assert data["scored_insurer_count"] == 0
    assert data["selected_target_count"] == 0
    assert data["target_slot_capacity"] == 3
    assert data["slots_committed"] == 0
    assert data["slots_available"] == 3


def test_analysis_cycle_period_and_window_ordering_are_enforced():
    """A zero-length reference period, a zero-length fieldwork window and a zero capacity are all malformed.

    PRD §3.2: "A `MarketAnalyst` opens a **market-analysis cycle** by supplying a `cycle_label` of 1 to 40 characters, unique across cycles (a collision is `ERR_DUPLICATE_IDENTIFIER`); the data reference period as `reference_period_start` and `reference_period_end`, the latter strictly after the former; a `target_slot_capacity` of at least 1, being the number of examiner slots the division can staff from this cycle; and the fieldwork window every examination the cycle spawns will inherit, as `default_fieldwork_start` and `default_fieldwork_end`, the latter again strictly after the former."
    PRD §2.11: "`reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`;"

    Design: Corner/entities/analysis_cycle_period_and_window_ordering_are_enforced
    """
    validate_error(
        api.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="BAD-PERIOD",
                reference_period_start="2026-06-30",
                reference_period_end="2026-06-30",
                target_slot_capacity=2,
                default_fieldwork_start="2026-09-01",
                default_fieldwork_end="2026-11-30",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="BAD-WINDOW",
                reference_period_start="2025-07-01",
                reference_period_end="2026-06-30",
                target_slot_capacity=2,
                default_fieldwork_start="2026-09-01",
                default_fieldwork_end="2026-09-01",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="ZERO-CAPACITY",
                reference_period_start="2025-07-01",
                reference_period_end="2026-06-30",
                target_slot_capacity=0,
                default_fieldwork_start="2026-09-01",
                default_fieldwork_end="2026-11-30",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api.list_analysis_cycles(ANALYST))
    assert meta["total_count"] == 0
    assert rows == []


def test_analysis_score_rows_are_child_reads_of_both_their_cycle_and_their_insurer():
    """One score row per scored carrier, reachable through its cycle in rank order and through its carrier.

    PRD §3.2: "The pass writes one `AnalysisScore` per scored carrier, each recording its `cycle_id` and `insurer_id` and snapshotting the carrier's current `complaint_ratio_per_1k` into `complaint_ratio_at_scoring`, so that later data refreshes cannot retroactively alter a completed scoring run."
    PRD §3.2: "Every score row also receives a 1-based `rank_position`, assigned by the cycle's ranking expression: `composite_score` descending, then `complaint_ratio_at_scoring` descending, then the score row's own `created_at` ascending."
    PRD §3.2: "Score rows are readable per cycle in rank order, filtered optionally by `selected` or `selection_reason`, and per carrier across all cycles, filtered optionally by `cycle_id` or `selected`."

    Design: Corner/entities/analysis_score_rows_are_child_reads_of_both_their_cycle_and_their_insurer
    """
    aurora = register_insurer(**AURORA)
    boreal = register_insurer(**BOREAL)
    cycle = create_analysis_cycle(
        cycle_label="2026-H2-MARKET-ANALYSIS",
        reference_period_start="2025-07-01",
        reference_period_end="2026-06-30",
        target_slot_capacity=3,
        default_fieldwork_start="2026-09-01",
        default_fieldwork_end="2026-11-30",
    )
    scored = score_cycle(cycle["id"])
    assert scored["scored_insurer_count"] == 2
    assert scored["status"] == "SCORED"

    # BOREAL: 40 + 24.00 + 14.00 = 78.00, times the 1.10 volume multiplier = 85.80.
    # AURORA: 28 + 18.00 + 10.00 = 56.00, times 1.00 = 56.00.
    cycle_scores, cycle_meta = validate_paginated(api.list_cycle_scores(cycle["id"], ANALYST))
    assert cycle_meta["total_count"] == 2
    for row in cycle_scores:
        assert_analysis_score(row)
        assert row["cycle_id"] == cycle["id"]
    assert cycle_scores[0]["rank_position"] == 1
    assert cycle_scores[0]["insurer_id"] == boreal["id"]
    assert cycle_scores[0]["composite_score"] == 85.80
    assert cycle_scores[0]["complaint_ratio_at_scoring"] == 5.00

    carrier_scores, carrier_meta = validate_paginated(
        api.list_insurer_analysis_scores(aurora["id"], ANALYST)
    )
    assert carrier_meta["total_count"] == 1
    assert_analysis_score(carrier_scores[0])
    assert carrier_scores[0]["insurer_id"] == aurora["id"]
    assert carrier_scores[0]["cycle_id"] == cycle["id"]
    assert carrier_scores[0]["composite_score"] == 56.00
    assert carrier_scores[0]["complaint_ratio_at_scoring"] == 3.00

    filtered, filtered_meta = validate_paginated(
        api.list_insurer_analysis_scores(
            aurora["id"], ANALYST, {"cycle_id": cycle["id"], "selected": "false"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == carrier_scores[0]["id"]
    assert filtered[0]["selected"] is False
