"""Cross-cutting: the two optimistic-concurrency guards and immediate recomputation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]
VALIDATOR = TEST_USERS["bca_validator_headers"]
APPROVER = TEST_USERS["project_approver_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]


# ─── The parcel guard, tripped by the writer's own sibling write ───────────────

def test_a_deduction_posted_after_the_read_invalidates_the_offer_token(api):
    """The identical body fails and then succeeds, and the offer finally sees the deduction.

    "Creating a purchase offer on a parcel requires the request to carry
    `expected_parcel_version`, a non-optional integer of at least 1 holding the `version`
    of that `Parcel` as the client last observed it. If it does not match the parcel's
    current `version`, the create is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP
    412)."

    "Recording a benefit recomputes `dob_deduction_total_cents` and advances the parcel's
    `version` by 1."

    "The new offer opens in `status` `DRAFT` at `version` 1 with `presented_at`,
    `expires_at`, `withdrawal_reason` and `superseded_by_offer_id` all null, and the
    parcel's `version` advances by 1."

    Design: Corner/cross_cutting_complexity_layers/a_parcel_version_captured_before_a_deduction_record_no_longer_authorises_the_offer
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.parcel_value_established(
        api,
        indicated_value_cents=20_000_000,
        project_overrides={"project_code": "CC-OCC-P1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-CC-OCC-1", "site_address": "4901 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel_id = state["parcel"]["id"]
    review_id = state["review_appraisal"]["id"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    before = validate_success(api.get_parcel(parcel_id, coordinator))
    assert before["dob_deduction_total_cents"] == 0
    version_before = before["version"]

    dob = fixtures.record_dob(
        api, project, parcel_id, benefit_source="ICC", amount_cents=500_000,
        received_on="2026-06-15",
    )
    assert dob["deductible_cents"] == 500_000

    after = validate_success(api.get_parcel(parcel_id, coordinator))
    assert after["dob_deduction_total_cents"] == 500_000
    assert after["version"] == version_before + 1
    version_after = after["version"]

    validate_error(
        api.create_purchase_offer(
            parcel_id,
            factories.create_purchase_offer_payload(
                parcel_id, review_id, version_before
            ),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_PARCEL_VERSION.value,
        412,
    )

    nothing, meta = validate_paginated(
        api.list_purchase_offers(ADMIN, params={"parcel_id": parcel_id})
    )
    assert meta["total_count"] == 0
    assert nothing == []

    offer = validate_success(
        api.create_purchase_offer(
            parcel_id,
            factories.create_purchase_offer_payload(
                parcel_id, review_id, version_after
            ),
            coordinator,
        ),
        201,
    )
    assert offer["status"] == "DRAFT"
    assert offer["base_value_cents"] == 20_000_000
    assert offer["dob_deduction_cents"] == 500_000

    carrying_the_offer = validate_success(api.get_parcel(parcel_id, ADMIN))
    assert carrying_the_offer["acquisition_status"] == "VALUE_ESTABLISHED"
    assert carrying_the_offer["version"] == version_after + 1


# ─── The project guard, tripped by the writer's own previous success ───────────

def test_the_ledger_write_invalidates_the_version_token_it_was_posted_with(api):
    """One read cannot authorise two entries, and the balance moves only once.

    "Posting a program income ledger entry against a project requires the request to
    carry `expected_project_version`, a non-optional integer of at least 1 holding the
    `version` of that `MitigationProject` as the client last observed it. If it does not
    match the project's current `version`, the post is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    "Posting is guarded by optimistic concurrency control on the project as described in
    §2.7: `expected_project_version` must equal the project's live `version`, otherwise
    `ERR_STALE_PROJECT_VERSION`."

    "Every entry's federal share is computed against the project's live
    `cost_share_federal_pct` and validated against the running
    `program_income_balance_cents`, and both of those move whenever any parcel-level
    cascade touches the project, so an entry posted from a stale view would book a
    federal share against a superseded cost-share basis."

    Design: Corner/cross_cutting_complexity_layers/a_project_version_reused_for_a_second_ledger_entry_is_stale
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(
        api,
        project_overrides={"project_code": "CC-OCC-PR1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-CC-OCC-PR1", "site_address": "5001 River Rd", "acreage": 0.34,
            "occupancy_type": "VACANT", "structure_type": "NONE",
        },
    )
    project_id = state["project"]["id"]
    parcel_id = state["parcel"]["id"]
    coordinator = make_subrecipient_coordinator_headers(project_id)

    opening = validate_success(api.get_mitigation_project(project_id, coordinator))
    assert opening["program_income_balance_cents"] == 0
    version_once = opening["version"]

    lease = validate_success(
        api.create_program_income_entry(
            project_id,
            factories.create_program_income_entry_payload(
                project_id, version_once, entry_type="LEASE_REVENUE",
                amount_cents=100_000, posted_on="2026-08-01",
                applied_to_parcel_id=parcel_id,
            ),
            coordinator,
        ),
        201,
    )
    assert lease["federal_share_cents"] == 75_000

    credited = validate_success(api.get_mitigation_project(project_id, ADMIN))
    assert credited["program_income_balance_cents"] == 75_000

    validate_error(
        api.create_program_income_entry(
            project_id,
            factories.create_program_income_entry_payload(
                project_id, version_once, entry_type="SALVAGE_PROCEEDS",
                amount_cents=40_000, posted_on="2026-08-01",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION.value,
        412,
    )

    unmoved = validate_success(api.get_mitigation_project(project_id, coordinator))
    assert unmoved["program_income_balance_cents"] == 75_000
    version_twice = unmoved["version"]
    assert version_twice == version_once + 1

    salvage = validate_success(
        api.create_program_income_entry(
            project_id,
            factories.create_program_income_entry_payload(
                project_id, version_twice, entry_type="SALVAGE_PROCEEDS",
                amount_cents=40_000, posted_on="2026-08-01",
            ),
            coordinator,
        ),
        201,
    )
    assert salvage["federal_share_cents"] == 30_000

    settled = validate_success(api.get_mitigation_project(project_id, ADMIN))
    assert settled["program_income_balance_cents"] == 105_000

    entries, meta = validate_paginated(
        api.list_program_income_entries(ADMIN, params={"project_id": project_id})
    )
    assert meta["total_count"] == 2
    assert len(entries) == 2


# ─── No deferred recomputation anywhere on the write path ─────────────────────

def test_the_write_response_already_agrees_with_the_read_that_follows_it(api):
    """Validation and approval both hand back the recomputed values, byte for byte.

    "`VALIDATE` moves the analysis to `VALIDATED`, stamps its `validated_by_user_id` with
    the acting `X-User-ID`, and pushes three values up onto the project: `validated_bcr`
    takes the analysis's `bcr`, `validated_bca_method` takes its `analysis_method`, and
    the project's `validated_by_user_id` takes the same acting `X-User-ID` that SoD-2
    will later read."

    "On approval the project moves to `APPROVED`, the whole neighborhood-viability family
    (`participating_parcel_count`, `holdout_parcel_count`,
    `contiguous_open_space_parcel_count`, `largest_component_parcel_ids`,
    `neighborhood_viability_ratio`, `viability_status`) is recomputed, and the project's
    `version` advances by 1."

    "Both methods then converge: `bcr` is `npv_benefits_cents` divided by
    `mitigation_cost_cents`, rounded half up to three decimal places."

    Design: Corner/consistency_model/every_write_response_already_carries_the_recomputed_derived_fields
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_submitted_project(
        api,
        project_overrides={"project_code": "CM-IMM-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-CM-IMM-1", "site_address": "5101 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project_id = state["project"]["id"]

    validated = validate_success(
        api.validate_benefit_cost_analysis(
            state["bca"]["id"],
            factories.validate_bca_payload(state["bca"]["id"], "VALIDATE"),
            VALIDATOR,
        )
    )
    assert validated["status"] == "VALIDATED"
    assert float(validated["bcr"]) == 2.667
    assert validated["validated_by_user_id"] == "pa-validator"

    pushed_up = validate_success(api.get_mitigation_project(project_id, ADMIN))
    assert float(pushed_up["validated_bcr"]) == 2.667
    assert pushed_up["validated_bca_method"] == "PRE_CALCULATED_BENEFIT"
    assert pushed_up["validated_by_user_id"] == "pa-validator"

    approved = validate_success(
        api.approve_mitigation_project(
            project_id,
            factories.approve_project_payload(project_id, "APPROVE"),
            APPROVER,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["viability_status"] == "NONVIABLE"
    assert float(approved["neighborhood_viability_ratio"]) == 0.0
    assert approved["participating_parcel_count"] == 1
    assert approved["holdout_parcel_count"] == 0
    assert approved["contiguous_open_space_parcel_count"] == 0
    assert approved["largest_component_parcel_ids"] == []

    reread = validate_success(api.get_mitigation_project(project_id, MONITOR))
    for field in (
        "status",
        "version",
        "validated_bcr",
        "validated_bca_method",
        "validated_by_user_id",
        "viability_status",
        "neighborhood_viability_ratio",
        "participating_parcel_count",
        "holdout_parcel_count",
        "contiguous_open_space_parcel_count",
        "largest_component_parcel_ids",
        "federal_obligated_cents",
        "program_income_balance_cents",
        "protected_open_space_acres",
    ):
        assert reread[field] == approved[field]
