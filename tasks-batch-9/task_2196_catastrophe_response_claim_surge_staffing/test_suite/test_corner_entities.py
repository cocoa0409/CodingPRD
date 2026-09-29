"""Queue B — corner coverage, section: entities.

Record shape and lifecycle-independent record behaviour: creation envelopes,
retrieval echo, pagination, not-found handling, required-field and range
rejection, defaults, computed fields, clock-stamped system fields, ledger
immutability and flat-topology cross-reference integrity.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.corner_support_d import (
    CE,
    CLOCK_START,
    CM,
    DC,
    declared_event,
    mint_estimate,
    new_adjuster,
    new_claim,
)


# ---------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------
def test_registering_an_event_returns_201_with_the_full_monitoring_initial_state(api):
    """PRD §3.1: "A newly registered event begins with `status` of `MONITORING`, a
    `posture` of `OPEN`, a `version` of 1, and a `declared_at_utc` of null."
    PRD §4: "Endpoints that bring a new resource into existence answer 201 Created;
    every other successful call answers 200 OK."
    PRD §3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."
    PRD §2.6: "On startup the clock reads exactly 2026-08-01T00:00:00Z, and until a
    caller moves it, every rule that consults the current instant observes that
    default."

    Design: Corner/entities/corner_entity_creation_catastrophe_event_201_envelope_and_initial_state
    """
    response = api.create_event(
        {
            "cat_code": "CAT-2026-1001",
            "peril_type": "HURRICANE",
            "jurisdiction_state": "FL",
            "event_start_utc": "2026-07-25T00:00:00.000Z",
            "exposure_count": 2000,
            "avg_insured_value": 310000,
            "expected_severity_index": 0.3000,
        },
        CM,
    )
    data = validate_success(response, 201)
    body = response.json()

    assert body["meta"]["api_request_id"], "meta.api_request_id must be non-empty"
    assert body["meta"]["api_request_timestamp"], "meta.api_request_timestamp must be present"
    assert body["response_type"] == "object", f"expected object, got {body['response_type']}"

    assert isinstance(data["id"], str) and data["id"], "id must be a non-empty string"
    assert data["cat_code"] == "CAT-2026-1001"
    assert data["peril_type"] == "HURRICANE"
    assert data["jurisdiction_state"] == "FL"
    assert data["event_start_utc"] == "2026-07-25T00:00:00.000Z"
    assert data["exposure_count"] == 2000
    assert data["avg_insured_value"] == 310000
    assert float(data["expected_severity_index"]) == 0.3000

    assert data["status"] == "MONITORING", f"expected MONITORING, got {data['status']}"
    assert data["posture"] == "OPEN", f"expected OPEN, got {data['posture']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["declared_at_utc"] is None, "declared_at_utc must be null before declaration"

    assert data["open_claim_count"] == 0
    assert_money_equals(data["case_reserve_total"], 0.00, "case_reserve_total")
    assert_money_equals(data["paid_total"], 0.00, "paid_total")
    assert_money_equals(data["incurred_total"], 0.00, "incurred_total")
    assert_money_equals(data["housing_committed_cost"], 0.00, "housing_committed_cost")
    assert_money_equals(data["deployment_settled_cost"], 0.00, "deployment_settled_cost")
    assert data["surge_adjuster_count"] == 0
    assert data["moratorium_active"] is False
    assert data["created_at"] == CLOCK_START, (
        f"created_at must be stamped from the logical clock, got {data['created_at']}"
    )


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------
def test_reading_a_new_adjuster_echoes_inputs_and_exposes_a_perfect_capacity_score(api):
    """PRD §3.3: "A newly registered adjuster is `AVAILABLE` on the deployment axis and
    `VALID` on the credential axis — except that the licence windows are evaluated
    against the clock at registration time, so an adjuster registered with an already-lapsed
    `license_expiry_utc` is stamped `EXPIRED` immediately, and one registered inside the
    warning window is stamped `EXPIRING` immediately."
    PRD §3.3: "The **availability term** starts from the adjuster's `open_assignment_count`
    — the number of their inspection assignments currently in `SCHEDULED` or `IN_PROGRESS`
    — divided by their `max_open_claims`; that load ratio is capped at 1, subtracted from 1,
    and multiplied by 100, so an idle adjuster contributes 100 points and a fully loaded one
    contributes zero."
    PRD §3.3: "Finally the **certification bonus** is added: 5 points if `desk_certified` is
    true plus a further 5 points if `aerial_certified` is true, for a maximum of 10."
    PRD §3.3: "The result is clamped so that it is not below 0 and not above 100, and only
    then rounded half up to 2 decimal places into `surge_capacity_score`."

    Design: Corner/entities/corner_entity_retrieval_adjuster_by_id_returns_stored_and_derived_fields
    """
    created = new_adjuster(
        api,
        "Dana Reyes",
        employment_type="INDEPENDENT",
        home_state="TX",
        licensed_states=["TX", "OK", "LA"],
        license_expiry_utc="2027-06-30T00:00:00.000Z",
        max_open_claims=12,
        daily_rate=700,
        per_diem_rate=85,
        desk_certified=True,
        aerial_certified=True,
    )

    response = api.get_adjuster(created["id"], DC)
    data = validate_success(response)
    assert response.json()["response_type"] == "object"

    assert data["id"] == created["id"]
    assert data["full_name"] == "Dana Reyes"
    assert data["employment_type"] == "INDEPENDENT"
    assert data["home_state"] == "TX"
    assert data["licensed_states"] == ["TX", "OK", "LA"]
    assert data["license_expiry_utc"] == "2027-06-30T00:00:00.000Z"
    assert data["max_open_claims"] == 12
    assert data["daily_rate"] == 700
    assert data["per_diem_rate"] == 85
    assert data["desk_certified"] is True
    assert data["aerial_certified"] is True

    assert data["credential_status"] == "VALID", f"got {data['credential_status']}"
    assert data["deployment_status"] == "AVAILABLE", f"got {data['deployment_status']}"
    assert data["open_assignment_count"] == 0
    assert_money_equals(data["cumulative_deployed_hours"], 0.00, "cumulative_deployed_hours")
    # availability 100.0 - credential 0.0 (VALID) - fatigue 0.0 + certs 10.0, clamped to 100.
    assert_money_equals(data["surge_capacity_score"], 100.00, "surge_capacity_score")
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------
def test_claim_listing_pages_by_limit_and_offset_with_filtered_total_count(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit`
    controls page size: its default is 10, its minimum accepted value is 1, and its
    maximum accepted value is 100. `offset` controls the starting position: its default
    is 0 and its minimum accepted value is 0."
    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true when rows remain beyond the current page."

    Design: Corner/entities/corner_entity_listing_claims_pagination_limit_offset_total_count_has_more
    """
    event = declared_event(api, "CAT-2026-1003", peril_type="WINTER_STORM", jurisdiction_state="GA")
    ids = set()
    for suffix in ("A", "B", "C"):
        claim = new_claim(
            api,
            f"POL-1003{suffix}",
            event["id"],
            loss_state="GA",
            reported_loss_amount=4000,
            coverage_lines=[
                {
                    "coverage_code": "DWELLING",
                    "limit_amount": 100000,
                    "deductible_amount": 500,
                    "estimated_damage_amount": 5000,
                }
            ],
        )
        ids.add(claim["id"])

    first_resp = api.list_claims(CE, params={"event_id": event["id"], "limit": 2, "offset": 0})
    page_one, meta_one = validate_paginated(first_resp)
    assert first_resp.json()["response_type"] == "array"
    assert len(page_one) == 2, f"expected 2 rows on page one, got {len(page_one)}"
    assert meta_one["total_count"] == 3, f"expected total_count 3, got {meta_one['total_count']}"
    assert meta_one["has_more"] is True, "rows remain beyond page one, so has_more must be true"
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_claims(CE, params={"event_id": event["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, f"expected 1 row on page two, got {len(page_two)}"
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False, "no rows remain after page two"
    assert meta_two["offset"] == 2

    paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(paged_ids) == len(set(paged_ids)), "no claim may appear on both pages"
    assert set(paged_ids) == ids, "the two pages together must cover every claim exactly once"


# ---------------------------------------------------------------------------
# not_found
# ---------------------------------------------------------------------------
def test_reading_an_unknown_claim_id_returns_err_claim_not_found_in_the_error_envelope(api):
    """PRD §2.4: "A reference that does not resolve produces the corresponding not-found
    error at HTTP 404: `ERR_EVENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ADJUSTER_NOT_FOUND`,
    `ERR_HOUSING_BLOCK_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_ADVANCE_NOT_FOUND`, `ERR_VENDOR_FIRM_NOT_FOUND`, `ERR_VENDOR_ASSIGNMENT_NOT_FOUND`,
    `ERR_BULLETIN_NOT_FOUND`, and `ERR_BATCH_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/corner_entity_not_found_unknown_claim_id_returns_err_claim_not_found
    """
    real_claim = new_claim(api, "POL-1004A", loss_state="FL")

    response = api.get_claim(NON_EXISTENT_UUID, CE)
    error = validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error", f"got {body['response_type']}"
    assert isinstance(error["message"], str) and error["message"].strip()
    assert body["meta"]["api_request_id"], "error envelope still carries meta.api_request_id"

    # The collection itself is reachable, so the 404 is attributable to the id.
    still_there = validate_success(api.get_claim(real_claim["id"], CE))
    assert still_there["id"] == real_claim["id"]


# ---------------------------------------------------------------------------
# required_fields
# ---------------------------------------------------------------------------
def test_registering_an_adjuster_without_licensed_states_is_rejected_as_a_schema_violation(api):
    """PRD §3.3: "Registration carries the adjuster's `full_name`; their `employment_type`,
    which is either `STAFF` or `INDEPENDENT` and drives both cost formulas and waiver
    eligibility; their `home_state` as a two-letter uppercase resident state code;
    `licensed_states`, the array of two-letter uppercase codes in which they hold an active
    licence; the `license_expiry_utc` instant at which that licence lapses; `max_open_claims`,
    the hard ceiling on concurrently open inspection assignments, from 1 through 60 inclusive;
    `daily_rate`, the contracted day rate in whole dollars, which must be greater than zero;
    and `per_diem_rate`, the daily per-diem in whole dollars, which may be zero but never
    negative."
    PRD §3.3: "Two optional booleans, `desk_certified` and `aerial_certified`, each default to
    false and gate the adjuster out of desk and aerial inspection work respectively."
    PRD §2.11: "Position 15 is request-schema validation, covering required fields, type
    correctness, enum membership and numeric ranges: `rooms_total` from 0 through 400,
    `max_open_claims` from 1 through 60, `expected_severity_index` from 0.0 through 1.0,
    `mandated_advance_pct` from 0.0 through 1.0, `deadline_extension_days` from 0 through 365,
    `coverage_lines` holding 1 through 6 entries with no repeated coverage code,
    `performance_score` from 0 through 100, and `limit` and `offset` within their pagination
    bounds; the failure is `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/corner_entity_required_fields_missing_licensed_states_rejected
    """
    response = api.create_adjuster(
        {
            "full_name": "No License Listed",
            "employment_type": "STAFF",
            "home_state": "TX",
            "license_expiry_utc": "2027-06-30T00:00:00.000Z",
            "max_open_claims": 6,
            "daily_rate": 500,
            "per_diem_rate": 50,
        },
        DC,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 422)
    assert response.json()["response_type"] == "error"

    _, meta = validate_paginated(api.list_adjusters(DC))
    assert meta["total_count"] == 0, "a rejected registration must not write a partial row"


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------
def test_omitted_access_status_and_certifications_take_their_declared_defaults(api):
    """PRD §3.6: "Two fields are optional: `event_id` may be supplied at intake if the
    catastrophe code is already known, or left null and attached later; and `access_status`
    defaults to `ACCESSIBLE` and otherwise takes `INACCESSIBLE` or `RESTRICTED`, asserting how
    reachable the property is."
    PRD §3.3: "Two optional booleans, `desk_certified` and `aerial_certified`, each default to
    false and gate the adjuster out of desk and aerial inspection work respectively."
    PRD §3.6: "To that product add the access adjustment for the claim's `access_status`:
    nothing for `ACCESSIBLE`, 6 points for `RESTRICTED`, and 12 points for `INACCESSIBLE`."
    PRD §3.6: "The score then selects the band recorded in `triage_tier`: a score of 75.00 or
    more is `CAT_SEVERE`, a score of 50.00 or more but below 75.00 is `COMPLEX`, a score of
    25.00 or more but below 50.00 is `STANDARD`, and anything below 25.00 is `FAST_TRACK`."
    PRD §3.6: "First compute the eligible damage of each coverage line as the line's
    `estimated_damage_amount` capped at its `limit_amount`, less its `deductible_amount`, with
    a floor of zero; sum those **raw, unrounded** line values; take the greater of that sum and
    the claim's `reported_loss_amount` as the basis; multiply the basis by the tier reserve
    factor for the claim's `triage_tier` — 0.85 for `CAT_SEVERE`, 0.65 for `COMPLEX`, 0.45 for
    `STANDARD`, 0.25 for `FAST_TRACK` — and round half up to 2 decimal places **once, at the
    end**."
    PRD §3.6: "In every remaining case the mode is `FIELD`."

    Design: Corner/entities/corner_entity_defaults_claim_access_status_and_adjuster_certifications
    """
    event = declared_event(api, "CAT-2026-1006")
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Uncertified Ann",
                "employment_type": "STAFF",
                "home_state": "TX",
                "licensed_states": ["TX"],
                "license_expiry_utc": "2027-06-30T00:00:00.000Z",
                "max_open_claims": 6,
                "daily_rate": 500,
                "per_diem_rate": 50,
            },
            DC,
        ),
        201,
    )
    # The intake payload omits access_status entirely, and the registration payload
    # above omits both certification booleans.
    claim = new_claim(api, "POL-1006A", event["id"])

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert adjuster["desk_certified"] is False, "desk_certified defaults to false"
    assert adjuster["aerial_certified"] is False, "aerial_certified defaults to false"
    # No certification bonus, but the availability term alone already clamps to 100.
    assert_money_equals(adjuster["surge_capacity_score"], 100.00, "surge_capacity_score")

    assert triaged["access_status"] == "ACCESSIBLE", "access_status defaults to ACCESSIBLE"
    # base 100.0 * min(1, 40000/100000) = 40.00; 40.00 * 0.95 (HAIL) + 0.0 access + 0 ALE
    # + 20.0 * 0.0000 = 38.00.
    assert_money_equals(triaged["severity_score"], 38.00, "severity_score")
    assert triaged["triage_tier"] == "STANDARD", f"got {triaged['triage_tier']}"
    assert triaged["inspection_mode"] == "FIELD", f"got {triaged['inspection_mode']}"
    # basis = max(50000 - 0, 40000) = 50000.00; 50000.00 * 0.45 = 22500.00.
    assert_money_equals(triaged["case_reserve"], 22500.00, "case_reserve")


# ---------------------------------------------------------------------------
# computed_fields
# ---------------------------------------------------------------------------
def test_housing_room_counts_and_night_count_are_derived_not_written(api):
    """PRD §3.4: "From that span the system computes `block_night_count`, the number of whole
    days from `block_start_date` up to but not including `block_end_date`."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."
    PRD §3.5: "It adds the deployment's `rooms_reserved` to the block's `rooms_occupied` and
    recomputes `rooms_available`, taking the block `ACTIVE → EXHAUSTED` if availability lands
    on zero."
    PRD §3.5: "Step two computes labour: the adjuster's `daily_rate` multiplied by a rate
    factor and by the nights, rounded to 2 decimal places, where the rate factor is exactly 1
    for a `STAFF` adjuster and 1.35 for an `INDEPENDENT` one."
    PRD §3.5: "Step four picks the tier **from that subtotal alone, never from the post-premium
    total**, so no iteration is needed and the answer is well-defined in a single pass: a
    subtotal of 20000.00 or more is `TIER_HIGH` at a premium rate of 11 percent; a subtotal of
    5000.00 or more but below 20000.00 is `TIER_MID` at 6 percent; anything below 5000.00 is
    `TIER_NONE` at zero."
    PRD §3.1: "`surge_adjuster_count` is the number of deployments on the event whose status is
    `CONFIRMED` or `ON_SITE`."

    Design: Corner/entities/corner_entity_computed_fields_housing_rooms_derive_from_deployments
    """
    event = declared_event(api, "CAT-2026-1007", peril_type="FLOOD", jurisdiction_state="LA")
    created_block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Six Room Court",
                "city": "Metairie",
                "rooms_total": 6,
                "nightly_rate": 150,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-08T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    assert created_block["block_night_count"] == 7, "whole days in 2026-09-01 -> 2026-09-08"
    assert created_block["rooms_occupied"] == 0
    validate_success(api.open_housing_block(created_block["id"], DC))

    adjuster = new_adjuster(
        api,
        "Derive Dan",
        home_state="LA",
        licensed_states=["LA"],
        daily_rate=600,
        per_diem_rate=80,
    )
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-02T00:00:00.000Z",
                "window_end_utc": "2026-09-05T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": created_block["id"],
                "rooms_reserved": 2,
            },
            DC,
        ),
        201,
    )

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    block = validate_success(api.get_housing_block(created_block["id"], DC))
    assert block["rooms_total"] == 6
    assert block["rooms_occupied"] == 2, "the confirmation drew exactly rooms_reserved"
    assert block["rooms_available"] == 4, "6 - 2, recomputed rather than written"
    assert block["block_night_count"] == 7
    assert block["status"] == "ACTIVE", "4 rooms still free, so no EXHAUSTED flip"

    # nights = 3; labour 600*1.00*3 = 1800.00, per-diem 80*3*1 = 240.00,
    # housing 150*2*3 = 900.00 -> subtotal 2940.00, below the TIER_MID floor.
    assert_money_equals(confirmed["provisional_cost"], 2940.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_NONE", f"got {confirmed['surge_premium_tier']}"

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["surge_adjuster_count"] == 1


# ---------------------------------------------------------------------------
# system_fields
# ---------------------------------------------------------------------------
def test_system_fields_are_stamped_from_the_logical_clock_and_version_increments_by_one(api):
    """PRD §2.6: "An operator of any role may set the clock to an arbitrary instant by
    supplying a `to_iso8601` value."
    PRD §3.1: "Declaration stamps `declared_at_utc` with the current logical-clock instant and
    recomputes posture; an event still in `MONITORING` always reads `OPEN`."
    PRD §2.5: "Most resources additionally carry `updated_at`, refreshed to the mutation
    instant on every change, and an integer `version` that starts at 1 when the resource is
    created and increases by exactly 1 on each mutation of that resource."
    PRD §3.6: "A new claim is `INTAKE` on the handling axis and `NONE` on the payment axis,
    with `reported_at_utc` stamped at the current logical-clock instant, `severity_score` of
    0.00, `reopen_count` of 0, and `triage_tier`, `inspection_mode`, `deadline_utc` and
    `verified_damage_amount` all null."

    Design: Corner/entities/corner_entity_system_fields_clock_stamped_timestamps_and_version_bump
    """
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-1008",
                "peril_type": "EARTHQUAKE",
                "jurisdiction_state": "CA",
                "event_start_utc": "2026-07-31T00:00:00.000Z",
                "exposure_count": 900,
                "avg_insured_value": 520000,
                "expected_severity_index": 0.2500,
            },
            CM,
        ),
        201,
    )
    assert event["created_at"] == CLOCK_START
    assert event["version"] == 1

    validate_success(api.set_clock("2026-08-04T09:30:00.000Z", CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-1008A",
                "loss_state": "CA",
                "loss_date_utc": "2026-07-31T00:00:00.000Z",
                "reported_loss_amount": 30000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 150000,
                        "deductible_amount": 2000,
                        "estimated_damage_amount": 35000,
                    }
                ],
            },
            CE,
        ),
        201,
    )

    declared = validate_success(api.declare_event(event["id"], CM))

    assert declared["status"] == "DECLARED"
    assert declared["declared_at_utc"] == "2026-08-04T09:30:00.000Z", (
        f"declared_at_utc must read the clock, got {declared['declared_at_utc']}"
    )
    assert declared["updated_at"] == "2026-08-04T09:30:00.000Z"
    assert declared["created_at"] == CLOCK_START, "created_at is never re-stamped"
    assert declared["version"] == 2, f"one mutation, so 1 -> 2, got {declared['version']}"

    fresh_claim = validate_success(api.get_claim(claim["id"], CE))
    assert fresh_claim["reported_at_utc"] == "2026-08-04T09:30:00.000Z"
    assert fresh_claim["event_id"] is None, "the claim was taken before any cat code"
    assert fresh_claim["handling_status"] == "INTAKE"
    assert fresh_claim["payment_status"] == "NONE"
    assert_money_equals(fresh_claim["severity_score"], 0.00, "severity_score")
    assert fresh_claim["reopen_count"] == 0
    assert fresh_claim["version"] == 1


# ---------------------------------------------------------------------------
# type_constraints
# ---------------------------------------------------------------------------
def test_enum_and_numeric_range_probes_just_outside_their_bounds_are_all_rejected(api):
    """PRD §3.1: "The registration payload carries the industry `cat_code` the carrier intends
    to use (between 3 and 24 characters, and unique across all events in the system, compared
    case-sensitively — a collision is refused with `ERR_CAT_CODE_TAKEN`), the `peril_type`
    driving the loss, which is one of `HURRICANE`, `WILDFIRE`, `HAIL`, `FLOOD`, `WINTER_STORM`
    or `EARTHQUAKE`; the `jurisdiction_state` whose regulator will govern the response, as a
    two-letter uppercase state code; the `event_start_utc` first-loss instant of the footprint;
    and three underwriting inputs describing the exposed book — `exposure_count`, the number of
    insured risks inside the footprint, which may be zero but never negative;
    `avg_insured_value`, the average total insured value per exposed risk in whole dollars,
    likewise never negative; and `expected_severity_index`, the damage-ratio expectation for
    this peril footprint, a value from 0.0 through 1.0 inclusive carried to 4 decimal places."
    PRD §2.11: "Position 15 is request-schema validation, covering required fields, type
    correctness, enum membership and numeric ranges: `rooms_total` from 0 through 400,
    `max_open_claims` from 1 through 60, `expected_severity_index` from 0.0 through 1.0,
    `mandated_advance_pct` from 0.0 through 1.0, `deadline_extension_days` from 0 through 365,
    `coverage_lines` holding 1 through 6 entries with no repeated coverage code,
    `performance_score` from 0 through 100, and `limit` and `offset` within their pagination
    bounds; the failure is `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/corner_entity_type_constraints_enum_and_numeric_range_rejections
    """
    event = declared_event(api, "CAT-2026-1009", expected_severity_index=0.0500)

    # TORNADO is not one of the six declared peril types.
    validate_error(
        api.create_event(
            {
                "cat_code": "CAT-2026-1009B",
                "peril_type": "TORNADO",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-26T00:00:00.000Z",
                "exposure_count": 200,
                "avg_insured_value": 140000,
                "expected_severity_index": 0.0500,
            },
            CM,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    # expected_severity_index runs 0.0 through 1.0 inclusive.
    validate_error(
        api.create_event(
            {
                "cat_code": "CAT-2026-1009C",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-26T00:00:00.000Z",
                "exposure_count": 200,
                "avg_insured_value": 140000,
                "expected_severity_index": 1.5000,
            },
            CM,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    # rooms_total runs 0 through 400 inclusive, so 401 is out of range.
    validate_error(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Too Many Rooms",
                "city": "Lubbock",
                "rooms_total": 401,
                "nightly_rate": 100,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-05T00:00:00.000Z",
            },
            DC,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    # max_open_claims runs 1 through 60 inclusive, so 61 is out of range.
    validate_error(
        api.create_adjuster(
            {
                "full_name": "Over Capacity",
                "employment_type": "STAFF",
                "home_state": "TX",
                "licensed_states": ["TX"],
                "license_expiry_utc": "2027-06-30T00:00:00.000Z",
                "max_open_claims": 61,
                "daily_rate": 500,
                "per_diem_rate": 50,
                "desk_certified": False,
                "aerial_certified": False,
            },
            DC,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    _, event_meta = validate_paginated(api.list_events(CM))
    assert event_meta["total_count"] == 1, "only the setup event survived"
    _, block_meta = validate_paginated(api.list_housing_blocks(DC))
    assert block_meta["total_count"] == 0, "the out-of-range block was never written"
    _, adjuster_meta = validate_paginated(api.list_adjusters(DC))
    assert adjuster_meta["total_count"] == 0, "the out-of-range adjuster was never written"


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------
def test_a_ledger_correction_appends_a_row_and_leaves_the_original_and_snapshot_untouched(api):
    """PRD §2.5: "`ReserveEntry` rows and `LossEstimateSnapshot` rows are immutable once
    written: they carry `id` and `created_at` only, and both `updated_at` and `version` are
    absent from their representations."
    PRD §2.5: "This is a direct consequence of the ledger being append-only — a reserve entry
    is never edited, and a mistaken movement is corrected by appending a compensating entry
    rather than by mutating the original."
    PRD §3.8: "The append is written with the next per-event `sequence_no`, an `effective_utc`
    of the current instant, and a null `reverses_entry_id`."
    PRD §3.8: "The ledger may be listed filtered by `event_id`, by `claim_id`, by
    `reverses_entry_id` and by `entry_type`, and it is returned in `sequence_no` ascending
    order — the same order the incurred-development estimator replays."
    PRD §3.8: "Its `stale` flag is a computed property re-evaluated on every read: it reads
    true exactly when a ledger entry exists on the event whose `sequence_no` is greater than
    the snapshot's recorded high-water mark."
    PRD §2.10: "At any instant, an event's `incurred_total` equals the sum, over every reserve
    entry belonging to that event, of the entry's change to case reserve plus its change to
    paid loss, rounded to 2 decimal places."
    PRD §2.5: "any operation that changes a claim's own fields, its handling or payment axis,
    or its reserve position increments that claim's `version` by 1."

    Design: Corner/entities/corner_entity_immutability_ledger_and_snapshot_rows_are_append_only
    """
    event = declared_event(api, "CAT-2026-1010")
    claim = new_claim(api, "POL-1010A", event["id"])
    validate_success(api.triage_claim(claim["id"], CE))

    initial_rows, _ = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert len(initial_rows) == 1, "triage appended exactly one INITIAL_CASE row"
    first = initial_rows[0]
    assert first["sequence_no"] == 1
    assert_money_equals(first["delta_case_reserve"], 22500.00, "delta_case_reserve")

    snapshot = mint_estimate(api, event["id"])
    assert snapshot["input_reserve_sequence_high_water"] == 1
    assert snapshot["stale"] is False, "a fresh snapshot is born non-stale"

    claim_version = validate_success(api.get_claim(claim["id"], CE))["version"]
    response = api.create_reserve_entry(
        claim["id"],
        {
            "expected_claim_version": claim_version,
            "entry_type": "REVISION",
            "delta_case_reserve": 5000,
            "delta_paid": 0,
        },
        CE,
    )
    appended = validate_success(response, 201)

    assert appended["entry_type"] == "REVISION"
    assert appended["sequence_no"] == 2, "the next per-event sequence number"
    assert appended["reverses_entry_id"] is None
    assert_money_equals(appended["delta_case_reserve"], 5000.00, "delta_case_reserve")
    assert_money_equals(appended["delta_paid"], 0.00, "delta_paid")
    assert appended["effective_utc"] == CLOCK_START
    assert "version" not in appended, "a ReserveEntry carries no version"
    assert "updated_at" not in appended, "a ReserveEntry carries no updated_at"

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2
    assert [row["sequence_no"] for row in rows] == [1, 2], "returned in sequence_no ascending order"
    assert rows[0]["id"] == first["id"], "the correction appended; it did not rewrite"
    assert_money_equals(rows[0]["delta_case_reserve"], first["delta_case_reserve"], "delta_case_reserve")
    assert rows[0]["effective_utc"] == first["effective_utc"]
    assert "version" not in rows[0] and "updated_at" not in rows[0]

    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed_claim["case_reserve"], 27500.00, "case_reserve")
    assert refreshed_claim["version"] == 3, "create 1 -> triage 2 -> manual revision 3"

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 27500.00, "case_reserve_total")
    assert_money_equals(refreshed_event["paid_total"], 0.00, "paid_total")
    assert_money_equals(refreshed_event["incurred_total"], 27500.00, "incurred_total")

    snapshots, snap_meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"]})
    )
    assert snap_meta["total_count"] == 1
    stored = snapshots[0]
    assert stored["id"] == snapshot["id"]
    assert_money_equals(stored["gross_estimate"], snapshot["gross_estimate"], "gross_estimate")
    assert_money_equals(stored["reported_component"], snapshot["reported_component"], "reported_component")
    assert_money_equals(stored["ibnr_component"], snapshot["ibnr_component"], "ibnr_component")
    assert stored["input_reserve_sequence_high_water"] == 1, "the snapshot was not re-based"
    assert stored["stale"] is True, "sequence_no 2 now exceeds the recorded high-water mark of 1"
    assert "version" not in stored and "updated_at" not in stored


# ---------------------------------------------------------------------------
# parent_relationships
# ---------------------------------------------------------------------------
def test_an_unresolvable_event_reference_is_rejected_before_anything_is_written(api):
    """PRD §2.4: "A reference that does not resolve produces the corresponding not-found error
    at HTTP 404: `ERR_EVENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ADJUSTER_NOT_FOUND`,
    `ERR_HOUSING_BLOCK_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_ADVANCE_NOT_FOUND`, `ERR_VENDOR_FIRM_NOT_FOUND`, `ERR_VENDOR_ASSIGNMENT_NOT_FOUND`,
    `ERR_BULLETIN_NOT_FOUND`, and `ERR_BATCH_NOT_FOUND`."
    PRD §3.6: "Two fields are optional: `event_id` may be supplied at intake if the catastrophe
    code is already known, or left null and attached later; and `access_status` defaults to
    `ACCESSIBLE` and otherwise takes `INACCESSIBLE` or `RESTRICTED`, asserting how reachable the
    property is."
    PRD §3.6: "**Cat coding** attaches an intake claim to a declared or surge-active catastrophe
    event by supplying that event's `event_id`; the claim's own `event_id` is set, and the
    event's `open_claim_count` and posture are recomputed."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."

    Design: Corner/entities/corner_entity_parent_relationships_unknown_event_rejected_before_any_write
    """
    event = declared_event(api, "CAT-2026-1011", expected_severity_index=0.0500)
    claim = new_claim(api, "POL-1011A")
    assert claim["event_id"] is None, "the optional parent is still null at intake"

    orphan_block = {
        "event_id": NON_EXISTENT_UUID,
        "hotel_name": "Orphan Inn",
        "city": "Waco",
        "rooms_total": 5,
        "nightly_rate": 120,
        "block_start_date": "2026-09-01T00:00:00.000Z",
        "block_end_date": "2026-09-05T00:00:00.000Z",
    }
    validate_error(
        api.create_housing_block(orphan_block, DC), ApiErrorId.ERR_EVENT_NOT_FOUND, 404
    )
    validate_error(
        api.assign_cat_code(claim["id"], {"event_id": NON_EXISTENT_UUID}, CE),
        ApiErrorId.ERR_EVENT_NOT_FOUND,
        404,
    )
    untouched = validate_success(api.get_claim(claim["id"], CE))
    assert untouched["event_id"] is None, "the failed reference mutated nothing"
    assert untouched["handling_status"] == "INTAKE"

    orphan_block["event_id"] = event["id"]
    block = validate_success(api.create_housing_block(orphan_block, DC), 201)
    assert block["status"] == "PENDING"
    assert block["rooms_total"] == 5
    assert block["rooms_occupied"] == 0
    assert block["rooms_available"] == 5
    assert block["block_night_count"] == 4, "whole days in 2026-09-01 -> 2026-09-05"
    assert block["event_id"] == event["id"]

    coded = validate_success(api.assign_cat_code(claim["id"], {"event_id": event["id"]}, CE))
    assert coded["event_id"] == event["id"]
    assert coded["handling_status"] == "INTAKE", "cat coding does not move the handling axis"

    _, block_meta = validate_paginated(api.list_housing_blocks(DC, params={"event_id": event["id"]}))
    assert block_meta["total_count"] == 1, "the 404 attempt left no orphan block behind"
    _, claim_meta = validate_paginated(api.list_claims(CE, params={"event_id": event["id"]}))
    assert claim_meta["total_count"] == 1
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["open_claim_count"] == 1


# ---------------------------------------------------------------------------
# topology
# ---------------------------------------------------------------------------
def test_an_assignment_whose_deployment_names_another_event_is_refused_for_scope(api):
    """PRD §3.7: "And the funding deployment must belong to the same event as the claim,
    otherwise `ERR_EVENT_SCOPE_MISMATCH`."
    PRD §3.7: "A created assignment is `SCHEDULED`, records `EXPLICIT_ADJUSTER` or
    `SELECTOR_RANKED` in `selection_reason`, and starts with `report_submitted_at_utc` and
    `verified_damage_amount` both null."
    PRD §3.7: "Creation also pulls the claim onto the inspection track: a claim in `TRIAGED`
    moves `TRIAGED → INSPECTION_PENDING`, and a claim in `REOPENED` moves
    `REOPENED → INSPECTION_PENDING`; both branches are driven by the same event — an assignment
    for the claim coming into existence in `SCHEDULED` — and both leave no further side effects
    of their own."
    PRD §3.3: "The **availability term** starts from the adjuster's `open_assignment_count` —
    the number of their inspection assignments currently in `SCHEDULED` or `IN_PROGRESS` —
    divided by their `max_open_claims`; that load ratio is capped at 1, subtracted from 1, and
    multiplied by 100, so an idle adjuster contributes 100 points and a fully loaded one
    contributes zero."

    Design: Corner/entities/corner_entity_topology_flat_cross_reference_integrity_across_two_events
    """
    event_a = declared_event(api, "CAT-2026-1012A", jurisdiction_state="TX")
    event_b = declared_event(
        api, "CAT-2026-1012B", jurisdiction_state="OK", exposure_count=250, avg_insured_value=130000
    )
    adjuster_both = new_adjuster(api, "Both States Bo", licensed_states=["TX", "OK"])
    adjuster_tx = new_adjuster(api, "Texas Only Tia", licensed_states=["TX"])

    claim = new_claim(api, "POL-1012A", event_a["id"])
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["triage_tier"] == "STANDARD"
    assert triaged["inspection_mode"] == "FIELD"

    window = {
        "window_start_utc": "2026-09-01T00:00:00.000Z",
        "window_end_utc": "2026-09-10T00:00:00.000Z",
    }
    deployment_b = validate_success(
        api.create_deployment(
            {"event_id": event_b["id"], "role_type": "FIELD", "adjuster_id": adjuster_both["id"], **window},
            DC,
        ),
        201,
    )
    deployment_a = validate_success(
        api.create_deployment(
            {"event_id": event_a["id"], "role_type": "FIELD", "adjuster_id": adjuster_tx["id"], **window},
            DC,
        ),
        201,
    )

    # The claim lives on event A; this funding deployment lives on event B.
    validate_error(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-09-02T00:00:00.000Z",
                "window_end_utc": "2026-09-03T00:00:00.000Z",
                "adjuster_id": adjuster_both["id"],
                "deployment_id": deployment_b["id"],
            },
            DC,
        ),
        ApiErrorId.ERR_EVENT_SCOPE_MISMATCH,
        409,
    )
    still_triaged = validate_success(api.get_claim(claim["id"], CE))
    assert still_triaged["handling_status"] == "TRIAGED", "no assignment came into existence"
    _, none_meta = validate_paginated(
        api.list_inspection_assignments(DC, params={"claim_id": claim["id"]})
    )
    assert none_meta["total_count"] == 0

    # Same call against a deployment on the claim's own event succeeds.
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-09-02T00:00:00.000Z",
                "window_end_utc": "2026-09-03T00:00:00.000Z",
                "adjuster_id": adjuster_tx["id"],
                "deployment_id": deployment_a["id"],
            },
            DC,
        ),
        201,
    )
    assert assignment["status"] == "SCHEDULED"
    assert assignment["selection_reason"] == "EXPLICIT_ADJUSTER"
    assert assignment["mode"] == "FIELD"
    assert assignment["report_submitted_at_utc"] is None
    assert assignment["verified_damage_amount"] is None

    pulled = validate_success(api.get_claim(claim["id"], CE))
    assert pulled["handling_status"] == "INSPECTION_PENDING"

    # Every relationship is an identifier field, reachable in both directions via filters.
    _, meta = validate_paginated(
        api.list_inspection_assignments(DC, params={"deployment_id": deployment_a["id"]})
    )
    assert meta["total_count"] == 1
    _, meta = validate_paginated(
        api.list_inspection_assignments(DC, params={"deployment_id": deployment_b["id"]})
    )
    assert meta["total_count"] == 0
    _, meta = validate_paginated(api.list_deployments(DC, params={"event_id": event_a["id"]}))
    assert meta["total_count"] == 1
    _, meta = validate_paginated(api.list_deployments(DC, params={"event_id": event_b["id"]}))
    assert meta["total_count"] == 1
    _, meta = validate_paginated(api.list_claims(CE, params={"event_id": event_a["id"]}))
    assert meta["total_count"] == 1
    _, meta = validate_paginated(api.list_claims(CE, params={"event_id": event_b["id"]}))
    assert meta["total_count"] == 0

    assert validate_success(api.get_adjuster(adjuster_tx["id"], DC))["open_assignment_count"] == 1
    assert validate_success(api.get_adjuster(adjuster_both["id"], DC))["open_assignment_count"] == 0
