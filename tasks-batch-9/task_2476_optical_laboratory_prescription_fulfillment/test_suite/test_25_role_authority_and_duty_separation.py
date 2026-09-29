"""Who may call what, and who may not sign off their own work."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.test_users import (
    BENEFITS_A_HEADERS,
    INSPECTOR_A,
    INSPECTOR_A_HEADERS,
    MANAGER_A,
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A,
    TECHNICIAN_A_HEADERS,
    make_inspector_headers,
    make_manager_headers,
)

# 17990 cents of basis (the 11995 lens plus the 5995 coating, no surfacing
# surcharge on a stock edging route) at a 25 percent share, half up from 4497.5.
SPLIT_CHARGEBACK = 4498
SECOND_WINDOW = ("2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z")


def _released_job_with_a_cited_failing_inspection(api):
    """A remake case citing the cycle-0 failing reading that INSPECTOR_A took."""
    scenario = fixtures.stock_edged_job(api)
    scenario = fixtures.failing_inspection_rework_cycle(
        api, scenario, window_start=SECOND_WINDOW[0], window_end=SECOND_WINDOW[1]
    )
    failing = scenario["failing_inspection"]
    assert failing["verdict"] == "FAIL"
    assert failing["sphere_delta"] == 0.30
    assert failing["inspector_user_id"] == INSPECTOR_A
    scenario = fixtures.stock_passed_job(api, scenario)
    assert scenario["inspection_od"]["cycle_index"] == 1
    scenario = fixtures.stock_released_job(api, scenario)

    case = validate_success(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["job_id"],
                defect_codes=["POWER_OUT_OF_TOL"],
                warranty_claim=False,
                quality_inspection_id=failing["id"],
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["case"] = case
    scenario["case_id"] = case["id"]
    return scenario


def test_a_technician_may_not_open_an_order(api):
    """The payload is impeccable and is never looked at.

    PRD 2.1: "If either header is absent, if `X-User-Role` names something that is not
    a recognised role, or if the named role is not authorised for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/lab_and_benefits_roles_cannot_perform_optician_only_writes
    """
    scenario = fixtures.stock_draft_order(api)

    validate_error(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )

    rows, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["order_id"]


def test_a_benefits_administrator_may_not_trace_a_frame(api):
    """The authorisation answer precedes the version rule the request satisfies.

    PRD 2.1: "This authorisation gate is evaluated after the request body has been
    structurally checked and after the addressed and referenced entities have been
    resolved, but before any domain rule specific to the endpoint."

    Design: Corner/rbac/lab_and_benefits_roles_cannot_perform_optician_only_writes
    """
    scenario = fixtures.stock_draft_order(api)

    error = validate_error(
        api.create_frame_layout(
            f.create_frame_layout_payload(
                scenario["order_id"], scenario["order_version"]
            ),
            BENEFITS_A_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.STALE_RX_ORDER_VERSION.value

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["version"] == scenario["order_version"]
    _, meta = validate_paginated(
        api.list_order_frame_layouts(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 0


def test_either_front_of_store_or_lab_management_may_register_a_prescriber(api):
    """Registration is shared, and each row keeps the standing it was created with.

    PRD 3.1: "Either a `StoreOptician` or a `LabManager` may register a prescriber of
    record."

    Design: Corner/rbac/prescriber_registration_is_shared_but_standing_changes_are_manager_only
    """
    fixtures.set_clock(api)

    by_optician = validate_success(
        api.create_prescriber(f.create_prescriber_payload(), OPTICIAN_A_HEADERS),
        expected_status=201,
    )
    by_manager = validate_success(
        api.create_prescriber(
            f.create_prescriber_payload(
                npi=TEST_DEFAULTS["npi_secondary"],
                full_name="Dr Paul Osei",
                license_state="NV",
                max_rx_validity_months=24,
            ),
            MANAGER_A_HEADERS,
        ),
        expected_status=201,
    )

    assert by_optician["status"] == "ACTIVE"
    assert by_manager["status"] == "ACTIVE"
    assert by_manager["max_rx_validity_months"] == 24
    _, meta = validate_paginated(api.list_prescribers(MANAGER_A_HEADERS))
    assert meta["total_count"] == 2


def test_only_lab_management_may_change_a_prescriber_s_standing(api):
    """The refused PATCH bumps nothing, so the manager's PATCH lands on version 2.

    PRD 3.1: "The `status` field takes one of `ACTIVE`, `SUSPENDED` or `RETIRED`, and
    only a `LabManager` may change it."

    Design: Corner/rbac/prescriber_registration_is_shared_but_standing_changes_are_manager_only
    """
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)

    validate_error(
        api.patch_prescriber_status(
            prescriber["id"], {"status": "SUSPENDED"}, OPTICIAN_A_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    assert fixtures.read_prescriber(api, prescriber["id"])["status"] == "ACTIVE"

    patched = validate_success(
        api.patch_prescriber_status(
            prescriber["id"], {"status": "SUSPENDED"}, MANAGER_A_HEADERS
        )
    )

    assert patched["status"] == "SUSPENDED"
    assert patched["version"] == 2


def test_the_technician_who_ran_the_edger_may_not_inspect_the_result(api):
    """The role is right; the identity is the one that ran the machine.

    PRD 2.9: "The user recording an inspection may not be a user who performed
    production work on the job being inspected: if `X-User-ID` equals the
    `performed_by_user_id` of any completed operation of that job, the inspection is
    refused."

    Design: Corner/rbac/the_technician_who_ran_the_edger_may_not_inspect_the_result
    """
    scenario = fixtures.stock_edged_job(api)
    assert scenario["operation"]["performed_by_user_id"] == TECHNICIAN_A
    assert scenario["operation"]["status"] == "COMPLETED"

    error = validate_error(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(scenario["job_id"], "OD"),
            make_inspector_headers(TECHNICIAN_A),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value

    inspection = validate_success(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(scenario["job_id"], "OD"),
            INSPECTOR_A_HEADERS,
        ),
        expected_status=201,
    )

    assert inspection["verdict"] == "PASS"
    assert inspection["inspector_user_id"] == INSPECTOR_A
    rows, meta = validate_paginated(
        api.list_quality_inspections(
            INSPECTOR_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == inspection["id"]
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGED"


def test_the_inspector_of_record_may_not_adjudicate_the_case_citing_them(api):
    """Holding the manager role does not clear the identity that took the reading.

    PRD 2.9: "The manager adjudicating a remake case may not be the inspector whose
    measurement evidences it: if `X-User-ID` equals the `inspector_user_id` of the
    case's linked inspection, adjudication is refused."

    Design: Corner/rbac/the_inspector_of_record_may_not_adjudicate_the_case_that_cites_their_reading
    """
    scenario = _released_job_with_a_cited_failing_inspection(api)

    validate_error(
        api.adjudicate_remake_case(
            scenario["case_id"],
            f.create_adjudication_payload("TOLERANCE_DELTA"),
            make_manager_headers(INSPECTOR_A),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )

    case = fixtures.read_case(api, scenario["case_id"])
    assert case["status"] == "SUBMITTED"
    assert case["lab_share_pct"] is None
    assert case["adjudication_method"] is None
    assert case["responsibility"] == "UNASSIGNED"


def test_an_independent_manager_dilutes_the_one_failing_metric_to_a_quarter(api):
    """Sphere saturates at 1 while the other three ratios contribute nothing.

    PRD 3.8: "`TOLERANCE_DELTA` instead grades measurement severity across four
    equally weighted metrics."

    PRD 3.8: "`lab_share_pct` is 100 multiplied by the sum of the four ratios, divided
    by 4, rounded half up to a whole percent."

    PRD 3.8: "At any share strictly between 0 and 100, `responsibility` is `SPLIT` and
    `lab_chargeback_cents` is the job cost basis multiplied by the share and divided by
    100, rounded half up to whole cents."

    Design: Corner/rbac/the_inspector_of_record_may_not_adjudicate_the_case_that_cites_their_reading
    """
    scenario = _released_job_with_a_cited_failing_inspection(api)
    validate_error(
        api.adjudicate_remake_case(
            scenario["case_id"],
            f.create_adjudication_payload("TOLERANCE_DELTA"),
            make_manager_headers(INSPECTOR_A),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )

    adjudicated = validate_success(
        api.adjudicate_remake_case(
            scenario["case_id"],
            f.create_adjudication_payload("TOLERANCE_DELTA"),
            make_manager_headers(MANAGER_A),
        )
    )

    assert adjudicated["lab_share_pct"] == 25
    assert adjudicated["responsibility"] == "SPLIT"
    assert adjudicated["lab_chargeback_cents"] == SPLIT_CHARGEBACK
    assert adjudicated["adjudication_method"] == "TOLERANCE_DELTA"
    assert adjudicated["status"] == "ADJUDICATED"

    case = fixtures.read_case(api, scenario["case_id"])
    assert case["lab_share_pct"] == 25
    assert case["lab_chargeback_cents"] == SPLIT_CHARGEBACK
    assert case["quality_inspection_id"] == scenario["failing_inspection_id"]
