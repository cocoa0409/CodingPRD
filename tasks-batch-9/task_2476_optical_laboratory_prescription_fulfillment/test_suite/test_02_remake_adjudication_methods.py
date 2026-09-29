"""Two adjudication methods reading the same defect codes and the same basis."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.test_users import MANAGER_A_HEADERS, OPTICIAN_A_HEADERS

FAILING_OD = {
    "measured_sphere": -3.2,
    "measured_cylinder": -1.2,
    "measured_axis": 96,
    "measured_prism": 0.5,
}
DEFECT_CODES = ["POWER_OUT_OF_TOL", "AXIS_OUT_OF_TOL"]


def _case_on_first_job(api):
    """An expedited surfaced order whose first job failed its OD reading."""
    scenario = fixtures.surfaced_edged_job(api)
    inspection = fixtures.inspect_eye(api, scenario["job_id"], "OD", **FAILING_OD)
    case = validate_success(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["job_id"],
                quality_inspection_id=inspection["id"],
                defect_codes=DEFECT_CODES,
                warranty_claim=False,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["first_case_id"] = case["id"]
    scenario["first_inspection_id"] = inspection["id"]
    return scenario


def _case_on_second_job(api, scenario):
    """A replacement job driven through the identical failing reading."""
    fixtures.stock_replacement_job(api, scenario)
    fixtures.surfaced_surfaced_job(
        api, scenario, "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z"
    )
    fixtures.surfaced_edged_job(
        api, scenario, "2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z"
    )
    inspection = fixtures.inspect_eye(api, scenario["job_id"], "OD", **FAILING_OD)
    case = validate_success(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["job_id"],
                quality_inspection_id=inspection["id"],
                defect_codes=DEFECT_CODES,
                warranty_claim=False,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["second_case_id"] = case["id"]
    return scenario


def test_tolerance_delta_dilutes_two_bad_metrics_with_two_good_ones(api):
    """Sphere and axis are capped at 1, cylinder is 0.38 and prism is 0, so 60.

    PRD 3.8: "For each of sphere, cylinder, axis and prism, form the ratio of that
    metric's delta on the linked inspection to that metric's tolerance on the
    standard the inspection resolved, and cap the ratio at 1."

    Design: Difficulty/dual_variant_calc/remake_responsibility_process_audit_versus_tolerance_delta_on_remake_case
    """
    scenario = _case_on_first_job(api)

    case = validate_success(
        api.adjudicate_remake_case(
            scenario["first_case_id"],
            f.create_adjudication_payload("TOLERANCE_DELTA"),
            MANAGER_A_HEADERS,
        )
    )

    assert case["lab_share_pct"] == 60
    assert case["responsibility"] == "SPLIT"
    assert case["lab_chargeback_cents"] == 29991
    assert case["status"] == "ADJUDICATED"


def test_process_audit_reads_the_defect_codes_alone_and_charges_the_whole_basis(api):
    """Both codes are lab-owned, so the share is 100 and the basis is 49985.

    PRD 3.8: "When every code on the case is lab-attributable, `lab_share_pct` is
    100."

    Design: Difficulty/dual_variant_calc/remake_responsibility_process_audit_versus_tolerance_delta_on_remake_case
    """
    scenario = _case_on_first_job(api)

    case = validate_success(
        api.adjudicate_remake_case(
            scenario["first_case_id"],
            f.create_adjudication_payload("PROCESS_AUDIT"),
            MANAGER_A_HEADERS,
        )
    )

    # 31995 lens plus the 4500 surfacing surcharge plus 10995 and 2495 of coatings.
    assert case["lab_chargeback_cents"] == 49985
    assert case["lab_share_pct"] == 100
    assert case["responsibility"] == "LAB"


def test_the_two_methods_disagree_on_byte_identical_defect_codes(api):
    """Identical evidence, identical basis, 60 against 100 on method alone.

    PRD 3.8: "The two methods can disagree sharply on the same case: a single
    out-of-tolerance sphere reading yields 100 under `PROCESS_AUDIT`, but a
    fractional share under `TOLERANCE_DELTA`, because the three metrics that were
    in tolerance dilute it."

    Design: Difficulty/dual_variant_calc/remake_responsibility_process_audit_versus_tolerance_delta_on_remake_case
    """
    scenario = _case_on_first_job(api)
    scenario = _case_on_second_job(api, scenario)

    delta_case = validate_success(
        api.adjudicate_remake_case(
            scenario["first_case_id"],
            f.create_adjudication_payload("TOLERANCE_DELTA"),
            MANAGER_A_HEADERS,
        )
    )
    audit_case = validate_success(
        api.adjudicate_remake_case(
            scenario["second_case_id"],
            f.create_adjudication_payload("PROCESS_AUDIT"),
            MANAGER_A_HEADERS,
        )
    )

    assert delta_case["defect_codes"] == audit_case["defect_codes"] == DEFECT_CODES
    assert (delta_case["lab_share_pct"], delta_case["lab_chargeback_cents"]) == (
        60,
        29991,
    )
    assert (audit_case["lab_share_pct"], audit_case["lab_chargeback_cents"]) == (
        100,
        49985,
    )
    assert delta_case["status"] == "ADJUDICATED"
    assert audit_case["status"] == "ADJUDICATED"

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["remake_count"] == 2
