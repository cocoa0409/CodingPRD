"""Calculations: month-end clamping, the zero-quantity waiver and graph topology."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]
STAFF = TEST_USERS["staff_appraiser_headers"]


# ─── The 12-month validity window and its conditional clamp ───────────────────

ANCHORS = (
    ("APN-CALC-WIN-A", "3101 River Rd", 0.34, "2028-02-29", "2029-02-28"),
    ("APN-CALC-WIN-B", "3102 River Rd", 0.41, "2028-01-31", "2029-01-31"),
    ("APN-CALC-WIN-C", "3103 River Rd", 0.52, "2028-08-31", "2029-08-31"),
)


def test_only_the_leap_day_anchor_is_clamped_when_twelve_months_are_added(api):
    """Two 31-day month ends keep their day-of-month; 29 February does not exist in 2029.

    "**Month arithmetic** adds whole calendar months and, when the anchor
    day-of-month does not exist in the target month, clamps to the last day of the
    target month - so an anchor of 31 January plus 36 months lands on 31 January
    three years later, and an anchor of 30 November plus 36 months lands on 30
    November three years later."

    "The server stamps `appraiser_user_id` with the acting `X-User-ID`, and the row
    opens in `status` `DRAFT` with `revision_count` 0, `validity_end_date` null and
    `version` 1."

    "On submission the server computes `validity_end_date` as `effective_date` plus
    12 calendar months, clamped to month end where the anchor day-of-month does not
    exist in the target month."

    Design: Corner/calculations/appraisal_validity_end_clamps_to_month_end_only_when_the_anchor_day_is_missing
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {
                "apn": apn,
                "site_address": address,
                "acreage": acreage,
                "occupancy_type": "OWNER_OCCUPIED",
                "structure_type": "SINGLE_FAMILY",
            }
            for apn, address, acreage, _effective, _end in ANCHORS
        ],
    )

    appraisals = []
    for parcel, (_apn, _address, _acreage, effective, _end) in zip(
        state["parcels"], ANCHORS
    ):
        appraisal = validate_success(
            api.create_appraisal(
                parcel["id"],
                factories.create_appraisal_payload(
                    parcel["id"], appraisal_type="INITIAL", valuation_basis="PRE_EVENT",
                    appraiser_license_no="LIC-SA-1", effective_date=effective,
                    indicated_value_cents=20_000_000,
                ),
                STAFF,
            ),
            201,
        )
        assert appraisal["status"] == "DRAFT"
        assert appraisal["revision_count"] == 0
        assert appraisal["validity_end_date"] is None
        appraisals.append(appraisal)

    for appraisal, (_apn, _address, _acreage, _effective, end) in zip(
        appraisals, ANCHORS
    ):
        submitted = validate_success(api.submit_appraisal(appraisal["id"], STAFF))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["validity_end_date"] == end


# ─── The zero-quantity diversion waiver ───────────────────────────────────────

def test_a_demolition_that_generated_no_debris_completes_at_a_diversion_of_zero(api):
    """Zero over zero is not evaluated: the waiver passes a percentage far below the floor.

    "`diversion_pct` is 0.00 when `total_debris_tons` is 0, and otherwise
    `recycled_tons` divided by `total_debris_tons`, multiplied by 100, rounded half
    up to two decimal places. The gate is then: a `total_debris_tons` of 0 passes
    under the zero-quantity waiver, since a work order that generated no debris
    cannot be held to a diversion percentage; otherwise a `diversion_pct` of at least
    25.0 passes; anything else is `ERR_DEBRIS_DIVERSION_BELOW_MINIMUM`."

    "Completion stores the four reported fields and `diversion_pct`, moves `status`
    to `COMPLETED`, moves the parcel's `acquisition_status` from `CLOSED` to
    `DEMOLISHED`, recomputes the contractor's `active_work_order_count` - which now
    drops the completed row and releases its buffered window capacity - and advances
    the work order's, the parcel's and the contractor's `version` each by 1."

    Design: Corner/calculations/a_zero_tonnage_demolition_passes_the_diversion_gate_under_the_waiver
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(api, grant_program="FMA")
    parcel = fixtures.create_parcel(
        api, project, apn="APN-CALC-DEB-1", site_address="3201 River Rd",
        acreage=0.34, occupancy_type="VACANT", structure_type="NONE",
    )
    assert parcel["acquisition_status"] == "NOT_STARTED"

    contractor = fixtures.create_contractor(
        api, name="Riverbend Wrecking", license_no="DEM-1",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-09-01T08:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
    )
    disconnections = fixtures.order_all_utility_disconnections(
        api, project, work_order["id"]
    )
    fixtures.confirm_all_utility_disconnections(api, project, disconnections)

    coordinator = make_subrecipient_coordinator_headers(project["id"])
    validate_success(api.start_demolition_work_order(work_order["id"], coordinator))

    completed = validate_success(
        api.complete_demolition_work_order(
            work_order["id"],
            factories.complete_work_order_payload(
                work_order["id"], total_debris_tons=0.00, recycled_tons=0.00,
                disposal_manifest_no="MAN-ZERO", disposal_facility_type="LANDFILL",
            ),
            coordinator,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert float(completed["diversion_pct"]) == 0.00
    assert float(completed["total_debris_tons"]) == 0.00
    assert float(completed["recycled_tons"]) == 0.00

    settled = validate_success(api.get_parcel(parcel["id"], ADMIN))
    assert settled["acquisition_status"] == "NOT_STARTED"

    released = validate_success(
        api.get_demolition_contractor(contractor["id"], ADMIN)
    )
    assert released["active_work_order_count"] == 0


# ─── The holdout that severs an adjacency edge ────────────────────────────────

def test_an_adjacency_with_one_acquired_endpoint_contributes_no_edge_to_the_graph(api):
    """One acquired parcel out of two adjacent ones is its own component, so the ratio is 0.5.

    "Then the **edge set**: every `ParcelAdjacency` of this project whose
    `parcel_a_id` and `parcel_b_id` are **both** members of the node set. An adjacency
    with exactly one acquired endpoint contributes no edge at all."

    "Then `contiguous_open_space_parcel_count` is the size of the largest component,
    or 0 when the node set is empty. `largest_component_parcel_ids` holds the `id`
    values of that winning component's members ordered by their `created_at`
    ascending, or an empty array when the node set is empty."

    "Finally `viability_status` reads off the rounded ratio against two inclusive
    lower bounds: `VIABLE` when the ratio is at least 0.75; `AT_RISK` when the ratio
    is at least 0.50 and below 0.75; `NONVIABLE` otherwise. A ratio of exactly 0.5000
    is `AT_RISK`, not `NONVIABLE`, and a ratio of exactly 0.7500 is `VIABLE`, not
    `AT_RISK`."

    "`holdout_parcel_count` is separately the count of parcels of this project whose
    `participation_status` is exactly `DECLINED`."

    Design: Corner/calculations/declining_a_holdout_parcel_raises_the_viability_ratio_by_shrinking_the_denominator
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {
                "apn": "APN-CALC-VIAB-1", "site_address": "3301 River Rd",
                "acreage": 0.34, "occupancy_type": "OWNER_OCCUPIED",
                "structure_type": "SINGLE_FAMILY",
            },
            {
                "apn": "APN-CALC-VIAB-2", "site_address": "3302 River Rd",
                "acreage": 0.41, "occupancy_type": "OWNER_OCCUPIED",
                "structure_type": "SINGLE_FAMILY",
            },
        ],
    )
    project = state["project"]
    first, second = state["parcels"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    validate_success(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                project["id"], first["id"], second["id"], shared_boundary_feet=118.0
            ),
            coordinator,
        ),
        201,
    )

    valued = fixtures.progress_parcel_to_value_established(
        api, project, first, pre_event_fmv_cents=20_000_000,
        indicated_value_cents=20_000_000,
    )
    offer = fixtures.build_offer(
        api, project, first["id"], valued["review_appraisal"]
    )
    validate_success(api.present_purchase_offer(offer["id"], coordinator))
    accepted = validate_success(
        api.respond_to_purchase_offer(
            offer["id"], factories.owner_response_payload(offer["id"], "ACCEPT"),
            coordinator,
        )
    )
    closing = validate_success(
        api.create_closing_record(
            first["id"],
            factories.create_closing_record_payload(
                first["id"], accepted["id"], scheduled_closing_date="2026-08-15",
                settlement_cost_cents=400_000,
            ),
            coordinator,
        ),
        201,
    )
    validate_success(api.fund_closing_record(closing["id"], ADMIN))

    severed = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert severed["participating_parcel_count"] == 2
    assert severed["contiguous_open_space_parcel_count"] == 1
    assert severed["largest_component_parcel_ids"] == [first["id"]]
    assert float(severed["neighborhood_viability_ratio"]) == 0.5
    assert severed["viability_status"] == "AT_RISK"
    assert severed["holdout_parcel_count"] == 0
    assert float(severed["protected_open_space_acres"]) == 0.00

    declined = validate_success(
        api.record_participation(
            second["id"],
            factories.participation_payload(
                second["id"], "DECLINE", decision_note="owner will not sell"
            ),
            coordinator,
        )
    )
    assert declined["participation_status"] == "DECLINED"

    with_holdout = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert with_holdout["holdout_parcel_count"] == 1
    assert with_holdout["contiguous_open_space_parcel_count"] == 1

    revived = validate_success(
        api.record_participation(
            second["id"],
            factories.participation_payload(second["id"], "INTERESTED"),
            coordinator,
        )
    )
    assert revived["participation_status"] == "INTERESTED"

    final = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert final["participating_parcel_count"] == 2
    assert final["holdout_parcel_count"] == 0
    assert float(final["neighborhood_viability_ratio"]) == 0.5
    assert final["viability_status"] == "AT_RISK"
