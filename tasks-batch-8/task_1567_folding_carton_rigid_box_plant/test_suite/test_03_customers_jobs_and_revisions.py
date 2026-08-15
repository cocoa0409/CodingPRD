"""Master-data creation defaults, lookup/shape errors, job version counters,
and the design-revision supersede/renumber write."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_job,
    create_customer,
    create_customer_payload,
    create_design_revision_payload,
    create_job,
    get_job,
    start_engineering,
    validate_error,
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import ADMIN, DESIGNER
from test_helpers.api_client import api_client


def test_customer_creation_defaults(api):
    """PRD §3.1: "New customers start in `ACTIVE` status."
    PRD §2.5: "`id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix."
    PRD §4: "Operations that create a new resource return a `201 Created` status code"

    Design: Corner/entities/customer_creation_defaults
    """
    res = api.create_customer(create_customer_payload(name="Acme", brand_code="ACM"),
                              ADMIN)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["version"] == 1
    # ISO 8601 UTC timestamps with three fractional digits.
    millis = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert millis.match(
        customer["created_at"]
    ), f"created_at lacks millisecond precision: {customer['created_at']}"
    assert millis.match(customer["updated_at"])


def test_job_lookup_errors_not_found(api):
    """PRD §2.6: "Fourth, existence: every path identifier and every body foreign-key reference — `customer_id`, `job_id`, `color_standard_id`, `design_revision_id`, `press_id`, `line_id` — must resolve to an existing resource; where a path or payload carries several identifiers they are validated left to right, and the first unresolvable one yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/job_lookup_errors_not_found
    """
    res = api.get_job(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    payload = {
        "customer_id": NON_EXISTENT_UUID,
        "quantity_ordered": 3000,
        "blank_w_cin": 900,
        "blank_h_cin": 600,
        "grain_rotation_allowed": True,
        "substrate_code": "SBS18",
        "caliper_pts": 18,
        "finish_coat": False,
        "finish_foil": False,
        "finish_emboss": False,
        "required_ink_slots": [],
        "requires_retail_compliance": False,
    }
    res2 = api.create_job(payload, ADMIN)
    validate_error(res2, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_request_shape_validation_errors(api):
    """PRD §2.6: "Fifth, request shape: required fields must be present, enum values must be members of their declared sets, integer quantities must be at least one where applicable, `sheets_good` must not exceed `sheets_printed`, `kits_completed` must not exceed `kits_planned`, and `components` must be non-empty with every entry's `units_per_kit` at least one; violations return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/request_shape_validation_errors
    """
    # Missing required field customer_id.
    missing = {
        "quantity_ordered": 3000,
        "blank_w_cin": 900,
        "blank_h_cin": 600,
        "grain_rotation_allowed": True,
        "substrate_code": "SBS18",
        "caliper_pts": 18,
        "finish_coat": False,
        "finish_foil": False,
        "finish_emboss": False,
        "required_ink_slots": [],
        "requires_retail_compliance": False,
    }
    res1 = api.create_job(missing, ADMIN)
    validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    # Unknown enum member for press_type.
    bad_enum = {
        "press_code": "P-X",
        "press_type": "FLEXO",
        "max_sheet_w_cin": 5000,
        "max_sheet_h_cin": 4000,
        "max_sheets_per_booking": 100,
    }
    res2 = api.create_press(bad_enum, ADMIN)
    validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_job_version_increments_on_mutation(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources."

    Design: Corner/entities/job_version_increments_on_mutation
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[])
    assert job["version"] == 1

    engineered = start_engineering(job["id"])
    assert engineered["version"] == 2

    cancelled = validate_success(api.cancel_job(job["id"], ADMIN), 200)
    assert cancelled["version"] == 3
    assert cancelled["status"] == "CANCELLED"


def test_design_revision_supersede_and_renumber(api):
    """PRD §3.3: "Creation is a superseding write: the job's prior non-`SUPERSEDED` revision, whatever its state among `DRAFT`, `SAMPLE_MADE`, or `BRAND_APPROVED`, becomes `SUPERSEDED`, and the job's `version` increments by one."
    PRD §3.3: "Each revision receives a `revision_number` that is one-based per job and increments with every new revision."

    Design: Corner/state_machines/design_revision_supersede_and_renumber
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[])
    job = start_engineering(job["id"])
    assert job["version"] == 2

    rev1 = get_success_data(
        api_client.create_design_revision(
            create_design_revision_payload(job["id"], job["version"], cad_ref="CAD-1"),
            DESIGNER,
        )
    )
    assert rev1["revision_number"] == 1
    job = get_job(job["id"])
    assert job["version"] == 3

    rev2 = get_success_data(
        api_client.create_design_revision(
            create_design_revision_payload(job["id"], job["version"], cad_ref="CAD-2"),
            DESIGNER,
        )
    )
    assert rev2["revision_number"] == 2
    assert rev2["status"] == "DRAFT"

    rev1_after = validate_success(api.get_design_revision(rev1["id"], ADMIN), 200)
    assert rev1_after["status"] == "SUPERSEDED"

    job = get_job(job["id"])
    assert job["version"] == 4, "each superseding create bumps job version by 1"
