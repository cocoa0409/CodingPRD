"""Assessment area delineation: creation defaults, validation, existence,
demographic profiles, OCC guards, review cycle, period/tract integrity, and
read-after-write consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_demographic_profile,
    assert_assessment_area,
    assert_demographic_profile,
    create_active_area,
    create_area,
    create_assessment_area_payload,
    create_branch_payload,
    create_draft_application,
    create_demographic_profile_payload,
    create_exam_cycle_payload,
    create_loan,
    create_submitted_activity,
    get_area,
    validate_error,
    validate_paginated,
    validate_success,
)

MISSING_AREA = NON_EXISTENT_UUID


# ---------------------------------------------------------------------------
# Queue B — Corner/entities
# ---------------------------------------------------------------------------

def test_create_assessment_area_returns_defaults(api, cra_officer_headers):
    """PRD §3.1: "The new area starts in `DRAFT` status with `version` 1, a null
    `effective_end_date`, and both computed counters — `confirmed_loan_count` and
    `qualified_cd_total_cents` — at zero."

    Design: Corner/entities/create_assessment_area_returns_defaults
    """
    resp = api.create_assessment_area(
        create_assessment_area_payload(
            area_code="AA-E1", name="Entity Area", msa_code="10180",
            state_code="CA", census_tracts=["T1"],
            effective_start_date="2023-01-01", annual_cd_budget_cents=500000,
        ),
        cra_officer_headers,
    )
    data = validate_success(resp, 201)
    assert_assessment_area(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["confirmed_loan_count"] == 0
    assert data["qualified_cd_total_cents"] == 0
    assert data["effective_end_date"] is None


def test_create_assessment_area_missing_required_field_returns_400(api, cra_officer_headers):
    """PRD §2.11: "at the same tier malformed bodies, missing required fields,
    invalid enum values, non-positive amounts, an `lmi_benefit_pct` outside the
    inclusive range 0 to 1, or an `lmi_population` exceeding `total_population`
    yield `ERR_VALIDATION`."

    Design: Corner/entities/create_assessment_area_missing_required_field_returns_400
    """
    payload = create_assessment_area_payload(msa_code="10180")
    del payload["area_code"]
    resp = api.create_assessment_area(payload, cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_assessment_area_not_found_returns_404(api, cra_officer_headers):
    """PRD §2.6: "The server resolves each path-template identifier in sequence
    and rejects the request at the first identifier that does not resolve,
    returning that segment's not-found error: `ERR_ASSESSMENT_AREA_NOT_FOUND`
    for an assessment area segment".

    Design: Corner/entities/assessment_area_not_found_returns_404
    """
    resp = api.get_assessment_area(MISSING_AREA, cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_AREA_NOT_FOUND)


def test_duplicate_area_code_rejected(api, cra_officer_headers):
    """PRD §2.9: "`area_code` is unique across all assessment areas; an attempt
    to create an area with an `area_code` that already exists is rejected with
    `ERR_DUPLICATE_AREA_CODE`."

    Design: Corner/validations/duplicate_area_code_rejected
    """
    first = create_assessment_area_payload(
        area_code="AA-DUP", name="First", msa_code="10180", census_tracts=["T1"]
    )
    validate_success(api.create_assessment_area(first, cra_officer_headers), 201)
    second = create_assessment_area_payload(
        area_code="AA-DUP", name="Second", msa_code="12060", state_code="GA",
        census_tracts=["T2"],
    )
    resp = api.create_assessment_area(second, cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_AREA_CODE)


def test_demographic_profile_computed_percentages(api, cra_officer_headers):
    """PRD §3.2: "`lmi_population_pct` is the ratio of `lmi_population` to
    `total_population`, rounded half up to four decimal places, and is 0 when
    `total_population` is zero. `lmi_tract_pct` is the ratio of the sum of
    `low_income_tracts` and `moderate_income_tracts` to `total_tracts`, rounded
    half up to four decimal places, and is 0 when `total_tracts` is zero."
    PRD §3.2: "A successful creation itself mutates the area — its `version`
    increments by one".

    Design: Corner/entities/demographic_profile_computed_percentages
    """
    area = create_area(area_code="AA-E2", msa_code="12060", state_code="GA")
    profile, area_after = add_demographic_profile(
        area, data_year=2020, total_tracts=10, low_income_tracts=2,
        moderate_income_tracts=2, total_population=10000, lmi_population=4500,
        median_family_income=60000,
    )
    assert_demographic_profile(profile)
    assert profile["lmi_population_pct"] == pytest.approx(0.45, abs=1e-9)
    assert profile["lmi_tract_pct"] == pytest.approx(0.4, abs=1e-9)
    assert profile["status"] == "CURRENT"
    assert area_after["version"] == area["version"] + 1


def test_demographic_profile_zero_denominators_yield_zero(api, cra_officer_headers):
    """PRD §3.2: "`lmi_population_pct` is the ratio of `lmi_population` to
    `total_population`, rounded half up to four decimal places, and is 0 when
    `total_population` is zero. `lmi_tract_pct` is the ratio of the sum of
    `low_income_tracts` and `moderate_income_tracts` to `total_tracts`, rounded
    half up to four decimal places, and is 0 when `total_tracts` is zero."

    Design: Corner/entities/demographic_profile_zero_denominators_yield_zero
    """
    area = create_area(area_code="AA-E3", msa_code="12060", state_code="GA")
    profile, _area = add_demographic_profile(
        area, data_year=2021, total_tracts=0, low_income_tracts=0,
        moderate_income_tracts=0, total_population=0, lmi_population=0,
        median_family_income=0,
    )
    assert profile["lmi_population_pct"] == 0
    assert profile["lmi_tract_pct"] == 0


# ---------------------------------------------------------------------------
# Queue B — Corner/state_machines
# ---------------------------------------------------------------------------

def test_initial_states_on_creation(
    api, cra_officer_headers, compliance_analyst_headers,
    bank_examiner_headers, bank_executive_headers,
):
    """PRD §3.1: "The new area starts in `DRAFT` status with `version` 1".
    PRD §3.3: "The record starts in `DRAFT`."
    PRD §3.4: "The activity starts as `SUBMITTED`".
    PRD §3.5: "Either way, `branch_code` is unique across all branches and the
    branch starts as `PROPOSED`."
    PRD §3.7: "A valid exam starts as `SCHEDULED`."
    PRD §3.8: "The draft starts in `DRAFT` with `linked_branch_id` and
    `decision_reason` null."

    Design: Corner/state_machines/initial_states_on_creation
    """
    area = create_area(area_code="AA-SM1", census_tracts=["T1"])
    assert area["status"] == "DRAFT"

    loan = create_loan(area["id"], action_date="2025-01-10")
    assert loan["status"] == "DRAFT"

    activity = create_submitted_activity(area["id"], submitter_user_id="analyst-1")
    assert activity["status"] == "SUBMITTED"

    branch_resp = api.create_branch(
        create_branch_payload(area["id"], branch_code="BR-I"), bank_executive_headers
    )
    assert validate_success(branch_resp, 201)["status"] == "PROPOSED"

    exam_resp = api.create_exam_cycle(create_exam_cycle_payload(), bank_examiner_headers)
    assert validate_success(exam_resp, 201)["status"] == "SCHEDULED"

    app = create_draft_application(area["id"], "MERGER")
    assert app["status"] == "DRAFT"
    assert app["linked_branch_id"] is None
    assert app["decision_reason"] is None


def test_activate_already_active_area_returns_invalid_state(api, cra_officer_headers):
    """PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_area_returns_invalid_state
    """
    area = create_active_area(area_code="AA-SM2", census_tracts=["T1"])
    resp = api.activate_assessment_area(area["id"], cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_area(area["id"])["status"] == "ACTIVE"


def test_retired_area_is_terminal(api, cra_officer_headers):
    """PRD §3.1: "Retiring moves an `ACTIVE` area to `RETIRED`, stamping
    `effective_end_date` with the logical-clock date as the exclusive end of its
    window; `RETIRED` is terminal."
    PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retired_area_is_terminal
    """
    area = create_active_area(area_code="AA-SM4", msa_code="19100", state_code="TX")
    retired = validate_success(
        api.retire_assessment_area(area["id"], cra_officer_headers)
    )
    assert retired["status"] == "RETIRED"
    resp = api.begin_review_assessment_area(area["id"], cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_area(area["id"])["status"] == "RETIRED"


# ---------------------------------------------------------------------------
# Queue B — Corner/cross_cutting_complexity_layers (OCC)
# ---------------------------------------------------------------------------

def test_occ_supersede_rejected_with_stale_area_version(api, cra_officer_headers):
    """PRD §2.7: "When the supplied value no longer matches the area's current
    `version` — because any intervening area mutation has advanced it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must
    re-read the area and retry on fresh state."
    PRD §3.2: "posting a profile whose (`assessment_area_id`, `data_year`) pair
    matches an existing `CURRENT` profile retires that earlier profile to
    `SUPERSEDED`".

    Design: Corner/cross_cutting_complexity_layers/occ_supersede_rejected_with_stale_area_version
    """
    area = create_area(area_code="AA-CC1")
    profile1, area_v2 = add_demographic_profile(area, data_year=2020)
    assert area_v2["version"] == area["version"] + 1

    # Replay with the stale observed version: rejected.
    stale_payload = create_demographic_profile_payload(
        expected_assessment_area_version=area_v2["version"] - 1,
        data_year=2020, total_tracts=11, low_income_tracts=3,
        moderate_income_tracts=2, total_population=11000, lmi_population=5000,
        median_family_income=61000,
    )
    stale_resp = api.create_demographic_profile(area["id"], stale_payload, cra_officer_headers)
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)

    # Retry on the fresh version: succeeds and supersedes the first profile.
    fresh_payload = create_demographic_profile_payload(
        expected_assessment_area_version=area_v2["version"],
        data_year=2020, total_tracts=11, low_income_tracts=3,
        moderate_income_tracts=2, total_population=11000, lmi_population=5000,
        median_family_income=61000,
    )
    profile2 = validate_success(
        api.create_demographic_profile(area["id"], fresh_payload, cra_officer_headers),
        201,
    )
    assert profile2["status"] == "CURRENT"

    list_resp = api.list_demographic_profiles(
        area["id"], cra_officer_headers, params={"data_year": 2020}
    )
    profiles, meta = validate_paginated(list_resp)
    assert meta["total_count"] == 2
    by_id = {p["id"]: p for p in profiles}
    assert by_id[profile1["id"]]["status"] == "SUPERSEDED"
    assert by_id[profile2["id"]]["status"] == "CURRENT"


def test_occ_patch_rejected_with_stale_area_version(api, cra_officer_headers):
    """PRD §2.7: "Both requests must carry `expected_assessment_area_version` as
    a non-optional input field holding the `version` of the area the client most
    recently observed. When the supplied value no longer matches the area's
    current `version` — because any intervening area mutation has advanced it —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
    must re-read the area and retry on fresh state."

    Design: Corner/cross_cutting_complexity_layers/occ_patch_rejected_with_stale_area_version
    """
    area = create_area(area_code="AA-CC2", msa_code="12060", state_code="GA")
    renamed = validate_success(
        api.patch_assessment_area(
            area["id"],
            {"expected_assessment_area_version": area["version"],
             "name": "Patch Area Renamed"},
            cra_officer_headers,
        )
    )
    assert renamed["version"] == area["version"] + 1

    stale_resp = api.patch_assessment_area(
        area["id"],
        {"expected_assessment_area_version": renamed["version"] - 1,
         "name": "Stale Rename"},
        cra_officer_headers,
    )
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)

    current = get_area(area["id"])
    assert current["name"] == "Patch Area Renamed"
    assert current["version"] == renamed["version"]


# ---------------------------------------------------------------------------
# Queue B — Corner/consistency_model
# ---------------------------------------------------------------------------

def test_mutations_immediately_visible(api, cra_officer_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.1: "every transition increments the area's `version` by one and
    refreshes `updated_at`."

    Design: Corner/consistency_model/mutations_immediately_visible
    """
    area = create_area(area_code="AA-CM1", msa_code="16980", state_code="IL")
    activated = validate_success(
        api.activate_assessment_area(area["id"], cra_officer_headers)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2

    fetched = validate_success(api.get_assessment_area(area["id"], cra_officer_headers))
    assert fetched["status"] == activated["status"] == "ACTIVE"
    assert fetched["version"] == activated["version"] == 2


# ---------------------------------------------------------------------------
# Queue A — Difficulty/non_linear_state_machine/assessment_area_review_cycle_returns_active
# ---------------------------------------------------------------------------

def test_review_cycle_returns_active_with_mid_cycle_tract_edit(api, cra_officer_headers):
    """PRD §3.1: "From `ACTIVE`, the officer may move the area to `UNDER_REVIEW`
    to rework a delineation, and completing that review returns it from
    `UNDER_REVIEW` to `ACTIVE` subject to the same two checks as activation —
    the review loop `ACTIVE → UNDER_REVIEW → ACTIVE` may repeat indefinitely."
    PRD §3.1: "While an area is `DRAFT` or `UNDER_REVIEW`, the officer may edit
    its `name` and/or its `census_tracts`".

    Design: Difficulty/non_linear_state_machine/assessment_area_review_cycle_returns_active
    """
    area = create_area(
        area_code="AA-NL1", msa_code="12060", state_code="GA",
        census_tracts=["T1", "T2"], annual_cd_budget_cents=1000000,
    )
    validate_success(api.activate_assessment_area(area["id"], cra_officer_headers))
    under_review = validate_success(
        api.begin_review_assessment_area(area["id"], cra_officer_headers)
    )
    assert under_review["status"] == "UNDER_REVIEW"

    edited = validate_success(
        api.patch_assessment_area(
            area["id"],
            {"expected_assessment_area_version": under_review["version"],
             "census_tracts": ["T1", "T2", "T3"]},
            cra_officer_headers,
        )
    )
    assert edited["census_tracts"] == ["T1", "T2", "T3"]

    completed = validate_success(
        api.complete_review_assessment_area(area["id"], cra_officer_headers)
    )
    assert completed["status"] == "ACTIVE"
    assert completed["census_tracts"] == ["T1", "T2", "T3"]


def test_review_cycle_may_repeat(api, cra_officer_headers):
    """PRD §3.1: "the review loop `ACTIVE → UNDER_REVIEW → ACTIVE` may repeat
    indefinitely."

    Design: Difficulty/non_linear_state_machine/assessment_area_review_cycle_returns_active
    """
    area = create_active_area(
        area_code="AA-NL1B", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    for _round in range(2):
        under_review = validate_success(
            api.begin_review_assessment_area(area["id"], cra_officer_headers)
        )
        assert under_review["status"] == "UNDER_REVIEW"
        back = validate_success(
            api.complete_review_assessment_area(area["id"], cra_officer_headers)
        )
        assert back["status"] == "ACTIVE"
    assert get_area(area["id"])["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/resource_temporal_overlap/area_period_half_open_adjacency_allowed
# ---------------------------------------------------------------------------

def test_area_period_half_open_adjacency_allowed(api, cra_officer_headers):
    """PRD §2.9: "Each area's effective window is half-open: it begins at
    `effective_start_date` (inclusive) and ends at `effective_end_date`
    (exclusive). A retired area closes its window at its recorded
    `effective_end_date`; an area that has not been retired is open-ended. A
    newly created area's window may not intersect the window of any other area
    sharing the same `msa_code`; a violation is rejected with
    `ERR_AREA_PERIOD_OVERLAP`. Adjacency is permitted — a new area whose
    `effective_start_date` equals another same-`msa_code` area's
    `effective_end_date` does not overlap it."

    Design: Difficulty/resource_temporal_overlap/area_period_half_open_adjacency_allowed
    """
    old = create_active_area(
        area_code="AA-OL1", msa_code="10180", census_tracts=["T9"],
        effective_start_date="2023-01-01",
    )
    retired = validate_success(
        api.retire_assessment_area(old["id"], cra_officer_headers)
    )
    assert retired["effective_end_date"] == "2026-08-01"

    # Adjacent at the retired area's exclusive end: allowed.
    adjacent_resp = api.create_assessment_area(
        create_assessment_area_payload(
            area_code="AA-OL2", msa_code="10180", census_tracts=["T8"],
            effective_start_date="2026-08-01",
        ),
        cra_officer_headers,
    )
    adjacent = validate_success(adjacent_resp, 201)
    assert adjacent["status"] == "DRAFT"

    # Starting before the exclusive end: overlaps the retired area's window.
    overlap_resp = api.create_assessment_area(
        create_assessment_area_payload(
            area_code="AA-OL3", msa_code="10180", census_tracts=["T7"],
            effective_start_date="2026-07-15",
        ),
        cra_officer_headers,
    )
    validate_error(overlap_resp, ApiErrorId.ERR_AREA_PERIOD_OVERLAP)


def test_area_period_overlap_scoped_per_msa(api, cra_officer_headers):
    """PRD §2.9: "A newly created area's window may not intersect the window of
    any other area sharing the same `msa_code`; a violation is rejected with
    `ERR_AREA_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/area_period_half_open_adjacency_allowed
    """
    create_area(
        area_code="AA-OL4", msa_code="10180", census_tracts=["T1"],
        effective_start_date="2023-01-01",
    )
    # Identical window but a different msa_code: no conflict.
    other_msa = api.create_assessment_area(
        create_assessment_area_payload(
            area_code="AA-OL5", msa_code="12060", state_code="GA",
            census_tracts=["T2"], effective_start_date="2023-01-01",
        ),
        cra_officer_headers,
    )
    assert validate_success(other_msa, 201)["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/compensating_invariant/tract_partition_move_conserves_union
# ---------------------------------------------------------------------------

def test_tract_partition_move_conserves_union(api, cra_officer_headers):
    """PRD §3.1: "While an area is `DRAFT` or `UNDER_REVIEW`, the officer may
    edit its `name` and/or its `census_tracts`". A tract moves between areas
    via a compensating pair of OCC-guarded edits, conserving the union. (The
    §2.9 exclusivity invariant is pairwise over ACTIVE/UNDER_REVIEW areas only;
    a DRAFT area holding a live area's tract is rejected at activation — see
    test_tract_overlap_rejected_at_activation — not uniquely determined at
    edit time.)

    Design: Difficulty/compensating_invariant/tract_partition_move_conserves_union
    """
    area_a = create_area(
        area_code="AA-CI1", msa_code="12060", state_code="GA",
        census_tracts=["T1", "T2"], effective_start_date="2023-01-01",
        annual_cd_budget_cents=1000000,
    )
    validate_success(api.activate_assessment_area(area_a["id"], cra_officer_headers))
    a_review = validate_success(
        api.begin_review_assessment_area(area_a["id"], cra_officer_headers)
    )
    # Distinct msa_code keeps the period-overlap rule of PRD §2.9 out of scope;
    # tract exclusivity is system-wide over ACTIVE/UNDER_REVIEW areas.
    area_b = create_area(
        area_code="AA-CI2", msa_code="10180", state_code="CA",
        census_tracts=["T3"], effective_start_date="2024-01-01",
        annual_cd_budget_cents=1000000,
    )

    # Compensating pair: remove T1 from A, then add it to B.
    a_after = validate_success(
        api.patch_assessment_area(
            area_a["id"],
            {"expected_assessment_area_version": a_review["version"],
             "census_tracts": ["T2"]},
            cra_officer_headers,
        )
    )
    b_after = validate_success(
        api.patch_assessment_area(
            area_b["id"],
            {"expected_assessment_area_version": area_b["version"],
             "census_tracts": ["T3", "T1"]},
            cra_officer_headers,
        )
    )
    assert a_after["census_tracts"] == ["T2"]
    assert b_after["census_tracts"] == ["T3", "T1"]
    union = set(a_after["census_tracts"]) | set(b_after["census_tracts"])
    assert union == {"T1", "T2", "T3"}
    assert len(union) == 3


def test_tract_overlap_rejected_at_activation(api, cra_officer_headers):
    """PRD §2.9: "The check runs whenever tracts are edited, at activation, and
    at review completion, and a violation is rejected with `ERR_TRACT_OVERLAP`."
    PRD §3.1: "Activation moves the area from `DRAFT` to `ACTIVE`. It requires a
    non-empty `census_tracts` (an empty list is `ERR_VALIDATION`) and re-verifies
    that no tract collides with another `ACTIVE` or `UNDER_REVIEW` area
    (`ERR_TRACT_OVERLAP`)."

    Design: Difficulty/compensating_invariant/tract_partition_move_conserves_union
    """
    create_active_area(
        area_code="AA-CI3", msa_code="19100", state_code="TX", census_tracts=["T5"],
    )
    contender = create_area(
        area_code="AA-CI4", msa_code="12060", state_code="GA", census_tracts=["T5"],
    )
    resp = api.activate_assessment_area(contender["id"], cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_TRACT_OVERLAP)
    assert get_area(contender["id"])["status"] == "DRAFT"
