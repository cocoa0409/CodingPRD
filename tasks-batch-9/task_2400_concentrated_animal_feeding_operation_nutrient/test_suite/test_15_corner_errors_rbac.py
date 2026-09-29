"""Role-based access control corner cases: the ordering of the authentication,
authorisation and ownership gates, the positive permission matrix, and the
segregation-of-duties rule on both routes into a closed inspection.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client as client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_posture,
    assert_quantity,
    assert_storage_balance,
)
from test_helpers.factories import inspection_response_payload
from test_helpers.fixtures import (
    conduct_inspection,
    initiate_transfer,
    record_application,
    register_hauler,
    register_operation,
    schedule_inspection,
    set_clock,
    setup_ready_operation,
    setup_scenario,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_HEADERS,
    headers_without_identity,
    make_hauler_headers,
    make_headers,
    make_operator_headers,
)



def _instant(value):
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _same_instant(actual, expected, label="instant"):
    assert actual is not None, f"{label} is missing"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def test_absent_or_unrecognised_identity_headers_fail_authentication():
    """A request with no identity headers, and a request declaring a role that is
    not one of the five recognised strings, both fail authentication — the
    unknown role never reaches the endpoint's role list.

    PRD: "If either header is absent, or if `X-User-Role` is not one of those five strings, the request fails with `ERR_UNAUTHENTICATED`."
    Design: Corner/rbac/header_role_and_ownership_failures_are_rejected_in_priority_order
    """
    ctx = setup_scenario(stage="OPERATION")
    operation_id = ctx["operation"]["id"]

    # The resource exists and an Operator may read it, but no identity is sent.
    validate_error(
        client.get_operation(operation_id, headers_without_identity()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        client.create_hauler(
            {
                "business_name": "Ghost Hauling",
                "license_number": "HL-9999",
                "license_expires_on": "2027-06-30T00:00:00Z",
            },
            make_headers("ghost-1", "Regulator"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_role_outside_the_endpoints_role_list_is_unauthorized():
    """Well-formed headers whose role is not listed for the endpoint fail
    authorisation, even when the same role may call a neighbouring endpoint.

    PRD: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called (see the table in §4), the request fails with `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/header_role_and_ownership_failures_are_rejected_in_priority_order
    """
    ctx = setup_scenario(stage="OPERATION")
    operation_id = ctx["operation"]["id"]
    operator_headers = make_operator_headers(operation_id)

    validate_error(
        client.create_operation(
            {
                "name": "Self Registered Dairy",
                "county": "Linn",
                "animal_type": "DAIRY_COW",
                "head_count": 10,
                "manure_handling": "DRY",
                "discharge_potential": "NONE",
            },
            operator_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    validate_error(
        client.list_operations(PLANNER_HEADERS, params={"county": "Linn"}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # The same planner may still read a single operation.
    validate_success(client.get_operation(operation_id, PLANNER_HEADERS))


def test_entity_backed_identities_must_match_the_row_they_act_on():
    """An Operator presenting another operation's id, and a Hauler presenting
    another hauler's transfer, are both refused as ownership violations before
    any state or payload check — and nothing is written.

    PRD: "When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operation`; ownership checks on any resource that references an `Operation` compare the resource's foreign-key field to `X-User-ID`."
    PRD: "When `X-User-Role` is `Hauler`, `X-User-ID` is the `id` of the acting `Hauler`; ownership checks compare the target transfer's `hauler_id` to `X-User-ID`, and a hauler acting on a transfer assigned to a different hauler is refused with `ERR_OWNERSHIP_VIOLATION`."
    PRD: "Acknowledgement stamps `recipient_ack_signed_at` from the logical clock and moves the volume from reservation to fact: `gallons_transferred` is released from the structure's `committed_outflow_gallons` and added to its `cumulative_outflow_gallons`, after which `current_volume_gallons` and `available_capacity_gallons` are recomputed."
    Design: Corner/rbac/header_role_and_ownership_failures_are_rejected_in_priority_order
    """
    ctx = setup_scenario(
        stage="COVERED", intake_gallons=1000000, with_hauler=True,
        hauler={"business_name": "Kroeger Pumping", "license_number": "HL-1001"},
    )
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]
    hauler_one = ctx["hauler"]

    other = register_operation(
        name="Prairie Ridge Swine",
        county="Story",
        animal_type="SWINE_FINISHING",
        head_count=400,
        manure_handling="LIQUID",
        open_lot_area_sqft=0,
        discharge_potential="STORMWATER_ONLY",
        has_conservation_plan=False,
    )
    hauler_two = register_hauler(
        business_name="Vandermeer Hauling",
        license_number="HL-1002",
        certified_applicator=False,
    )

    transfer = initiate_transfer(
        operation_id,
        storage_id,
        hauler_one["id"],
        operator_headers,
        recipient_name="Duvall Row Crop",
        recipient_address="2244 340th St, Linn",
        transferred_on="2026-07-20T00:00:00Z",
        gallons_transferred=200000,
    )

    validate_error(
        client.update_operation(other["id"], {"head_count": 900}, operator_headers),
        ApiErrorId.ERR_OWNERSHIP_VIOLATION.value,
    )
    untouched = validate_success(client.get_operation(other["id"], ADMIN_HEADERS))
    assert untouched["head_count"] == 400
    assert_quantity(untouched["animal_units"], 160.00, "animal_units")
    assert untouched["version"] == other["version"], (
        "the refused patch must not advance the other operation's version"
    )

    validate_error(
        client.acknowledge_manure_transfer(
            transfer["id"], make_hauler_headers(hauler_two["id"])
        ),
        ApiErrorId.ERR_OWNERSHIP_VIOLATION.value,
    )
    still_open = validate_success(
        client.get_manure_transfer(transfer["id"], operator_headers)
    )
    assert still_open["transfer_status"] == "INITIATED"
    assert still_open["recipient_ack_signed_at"] is None

    acknowledged = validate_success(
        client.acknowledge_manure_transfer(
            transfer["id"], make_hauler_headers(hauler_one["id"])
        )
    )
    assert acknowledged["transfer_status"] == "ACKNOWLEDGED"
    _same_instant(
        acknowledged["recipient_ack_signed_at"],
        "2026-08-01T00:00:00Z",
        "recipient_ack_signed_at",
    )

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert_storage_balance(
        structure,
        intake=1000000.00,
        outflow=200000.00,
        current=800000.00,
        committed=0.00,
    )


def test_each_role_exercises_its_own_exclusive_operations_end_to_end():
    """One fixture drives an exclusive operation of every declared role: the
    Operator records the application and the transfer, the CertifiedPlanner
    verifies, the StateReviewer reads the plan it approved, the Hauler
    acknowledges and completes, and the ComplianceAdmin voids and moves the
    clock — the void compensating a ledger that role never wrote.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts."
    PRD: "It is born `RECORDED`; a `CertifiedPlanner` may verify it, advancing `RECORDED → VERIFIED`, which is admissible only while the owning plan's `plan_status` is `APPROVED` — otherwise `ERR_PLAN_NOT_APPROVED` — and which changes neither ledger, because both the budget's applied total and the structure's outflow total already count `RECORDED` and `VERIFIED` records alike."
    PRD: "Only a `ComplianceAdmin` may void a record, and voiding is available from either `RECORDED` or `VERIFIED`; attempting to verify or void a record whose `event_status` is already `VOIDED` is refused with `ERR_EVENT_ALREADY_TERMINAL`, and `VOIDED` is terminal."
    Design: Corner/rbac/each_role_exercises_its_own_exclusive_operations_end_to_end
    """
    ctx = setup_ready_operation(
        with_hauler=True,
        hauler={"business_name": "Kroeger Pumping", "license_number": "HL-1001"},
    )
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    budget_id = ctx["budget"]["id"]
    operator_headers = ctx["operator_headers"]
    hauler_headers = make_hauler_headers(ctx["hauler"]["id"])

    event = record_application(
        operation_id,
        ctx["plan"]["id"],
        budget_id,
        storage_id,
        operator_headers,
        applied_on="2026-07-10T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
        precipitation_forecast_in_24h=0.1,
    )
    assert_quantity(event["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    assert_quantity(event["n_applied_lbs"], 1560.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 1000.00, "p2o5_applied_lbs")

    verified = validate_success(
        client.verify_application_event(event["id"], PLANNER_HEADERS)
    )
    assert verified["event_status"] == "VERIFIED"
    after_verify = validate_success(client.get_field_budget(budget_id, PLANNER_HEADERS))
    assert_budget_ledger(
        after_verify, applied=100000.00, remaining=314396, total=414396
    )

    transfer = initiate_transfer(
        operation_id,
        storage_id,
        ctx["hauler"]["id"],
        operator_headers,
        recipient_name="Duvall Row Crop",
        recipient_address="2244 340th St, Linn",
        transferred_on="2026-07-20T00:00:00Z",
        gallons_transferred=200000,
    )
    assert_quantity(transfer["recipient_n_lbs"], 4800.00, "recipient_n_lbs")
    assert_quantity(transfer["recipient_p2o5_lbs"], 2000.00, "recipient_p2o5_lbs")

    validate_success(
        client.acknowledge_manure_transfer(transfer["id"], hauler_headers)
    )
    completed = validate_success(
        client.complete_manure_transfer(transfer["id"], hauler_headers)
    )
    assert completed["transfer_status"] == "COMPLETED"

    reviewed = validate_success(
        client.get_nutrient_plan(ctx["plan"]["id"], REVIEWER_HEADERS)
    )
    assert reviewed["plan_status"] == "APPROVED"

    voided = validate_success(
        client.void_application_event(event["id"], ADMIN_HEADERS)
    )
    assert voided["event_status"] == "VOIDED"
    after_void = validate_success(client.get_field_budget(budget_id, PLANNER_HEADERS))
    assert_budget_ledger(after_void, applied=0.00, remaining=414396, total=414396)
    field = validate_success(client.get_field(ctx["field"]["id"], PLANNER_HEADERS))
    assert field["last_application_on"] is None

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert_storage_balance(
        structure,
        intake=1000000.00,
        outflow=200000.00,
        current=800000.00,
        committed=0.00,
    )

    checkpoints = set_clock("2026-08-02T00:00:00Z")
    _same_instant(checkpoints["current_utc"], "2026-08-02T00:00:00Z", "current_utc")
    assert checkpoints["haulers_lapsed_count"] == 0, (
        "the hauler licence runs well past the new clock value"
    )


def test_conducting_reviewer_cannot_take_the_zero_findings_close_route():
    """On the no-findings route straight out of CONDUCTED, the reviewer who
    conducted the inspection is refused, while the ComplianceAdmin who shares
    the close operation succeeds.

    PRD: "Closing an inspection whose recorded `inspector_user_id` equals the caller's `X-User-ID` is refused with `ERR_SEGREGATION_OF_DUTIES`, and this holds on both routes into the closed state — the no-findings route straight from the conducted state, and the route that follows an operator's corrective-action response."
    PRD: "When `findings_count` is 0, a `StateReviewer` or a `ComplianceAdmin` may instead close the inspection directly, advancing `CONDUCTED → CLOSED` and stamping `closed_by_user_id` with the closing actor's `X-User-ID`, provided that actor differs from the recorded `inspector_user_id`."
    Design: Corner/rbac/inspector_of_record_cannot_close_their_own_inspection
    """
    ctx = setup_scenario(stage="COVERED")
    operation_id = ctx["operation"]["id"]

    inspection = schedule_inspection(
        operation_id,
        ctx["permit"]["id"],
        REVIEWER_2_HEADERS,
        scheduled_on="2026-07-15T00:00:00Z",
    )
    conducted = conduct_inspection(inspection["id"], 0, REVIEWER_2_HEADERS)
    assert conducted["inspection_status"] == "CONDUCTED"
    assert conducted["inspector_user_id"] == "reviewer-2", (
        "conduct stamps the inspector from the acting user id"
    )
    assert conducted["findings_count"] == 0

    validate_error(
        client.close_inspection(inspection["id"], REVIEWER_2_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    unchanged = validate_success(
        client.get_inspection(inspection["id"], REVIEWER_HEADERS)
    )
    assert unchanged["inspection_status"] == "CONDUCTED"
    assert unchanged["closed_by_user_id"] is None

    closed = validate_success(client.close_inspection(inspection["id"], ADMIN_HEADERS))
    assert closed["inspection_status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "admin-1"


def test_conducting_reviewer_cannot_close_after_the_corrective_response():
    """On the notice-of-violation route the same rule holds: the inspector of
    record is refused from RESPONSE_SUBMITTED, and a peer reviewer's closure is
    what unwinds the finding count, the permit's compliance dimension and the
    operation's posture.

    PRD: "Closing an inspection whose recorded `inspector_user_id` equals the caller's `X-User-ID` is refused with `ERR_SEGREGATION_OF_DUTIES`, and this holds on both routes into the closed state — the no-findings route straight from the conducted state, and the route that follows an operator's corrective-action response."
    PRD: "Issuance stamps `response_due_on` as `conducted_on` plus 30 days — so an inspection conducted at the start of 1 August 2026 and served with a notice is due a response by the start of 31 August 2026 — increments the operation's `open_finding_count`, and starts the compliance cascade."
    PRD: "The response also advances the permit's compliance dimension `NOTICE_ISSUED → CORRECTIVE_ACTION`; the operation's posture stays `RESTRICTED`, because `CORRECTIVE_ACTION` is itself a restricting `compliance_status`."
    Design: Corner/rbac/inspector_of_record_cannot_close_their_own_inspection
    """
    ctx = setup_scenario(stage="COVERED")
    operation_id = ctx["operation"]["id"]
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    inspection = schedule_inspection(
        operation_id,
        permit_id,
        REVIEWER_HEADERS,
        scheduled_on="2026-07-28T00:00:00Z",
        inspection_kind="COMPLAINT",
    )
    conducted = conduct_inspection(
        inspection["id"],
        2,
        REVIEWER_HEADERS,
        deficiency_categories=["FREEBOARD", "RECORDKEEPING"],
    )
    assert conducted["inspector_user_id"] == "reviewer-1"

    noticed = validate_success(client.issue_nov(inspection["id"], REVIEWER_HEADERS))
    assert noticed["inspection_status"] == "NOV_ISSUED"
    _same_instant(noticed["response_due_on"], "2026-08-31T00:00:00Z", "response_due_on")

    operation = validate_success(client.get_operation(operation_id, operator_headers))
    assert_posture(operation, "RESTRICTED", findings=1)
    permit = validate_success(client.get_permit(permit_id, operator_headers))
    assert permit["compliance_status"] == "NOTICE_ISSUED"
    assert permit["coverage_status"] == "COVERED"

    responded = validate_success(
        client.submit_inspection_response(
            inspection["id"], inspection_response_payload(), operator_headers
        )
    )
    assert responded["inspection_status"] == "RESPONSE_SUBMITTED"
    permit = validate_success(client.get_permit(permit_id, operator_headers))
    assert permit["compliance_status"] == "CORRECTIVE_ACTION"
    assert permit["coverage_status"] == "COVERED"

    validate_error(
        client.close_inspection(inspection["id"], REVIEWER_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    still_open = validate_success(
        client.get_inspection(inspection["id"], ADMIN_HEADERS)
    )
    assert still_open["inspection_status"] == "RESPONSE_SUBMITTED"
    assert still_open["closed_by_user_id"] is None

    closed = validate_success(
        client.close_inspection(inspection["id"], REVIEWER_2_HEADERS)
    )
    assert closed["inspection_status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "reviewer-2"

    operation = validate_success(client.get_operation(operation_id, operator_headers))
    assert_posture(operation, "OPEN", findings=0)
    permit = validate_success(client.get_permit(permit_id, operator_headers))
    assert permit["compliance_status"] == "IN_GOOD_STANDING"
