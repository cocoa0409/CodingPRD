"""The refusals that have to be told apart: who you are, what exists, what is spent.

Each test here pins one error identifier to one cause — an unrecognised role, a missing
row, a terminal status, a screening that has not finished — and then reads back the state
that the refusal must have left exactly as it was.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_ledger_entry, assert_mou_unit_ledger, assert_total_count
from test_helpers.factories import (
    make_ancillary_resolve_payload,
    make_encounter_payload,
    make_observation_payload,
    make_publish_payload,
    make_transfer_accept_payload,
    make_transfer_complete_payload,
    make_transfer_decline_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    COORDINATOR,
    OFFICER,
    PHYSICIAN,
    acknowledge_disclosure,
    admit_to_observation,
    begin_mse,
    complete_mse,
    create_facility,
    create_transfer_order,
    draft_template,
    ledger_entries,
    open_facility,
    order_ancillary,
    read_ambulance_mou,
    read_encounter,
    read_facility,
    register_encounter,
    resolve_ancillary,
    screen_encounter,
    set_clock,
    transfer_ready_encounter,
)
from test_helpers.test_users import make_role_headers

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
UNKNOWN_ROLE = make_role_headers("Auditor", "who-1")
RESULTED_CT_PAIR_CENTS = 98000


def test_an_unrecognised_role_is_turned_away_before_anything_else_is_looked_at():
    """The same 401 whether the facility in the path exists or not.

    PRD 2.1: "Every request to every endpoint, including the two logical-clock endpoints,
    must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`,
    naming the role that operator is acting under." and "If either header is absent, or if
    `X-User-Role` is not one of the seven role names below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." with the ordering that makes the second call a 401 and
    not a 404: "Authentication is checked before authorisation, and both are checked before
    anything else about the request is examined."  PRD 2.6 puts the same rule first on the
    ladder: "`X-User-Role` and `X-User-ID` must be present and `X-User-Role` must be one of
    the seven declared roles, else `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_or_unknown_role_header_returns_unauthenticated
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    entries_before = ledger_entries(facility_id)

    validate_error(
        api_client.get_facility(facility_id, UNKNOWN_ROLE),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api_client.get_facility(NON_EXISTENT_UUID, UNKNOWN_ROLE),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    assert len(ledger_entries(facility_id)) == len(entries_before)


def test_each_role_is_confined_to_its_own_endpoints_and_the_refusals_change_nothing():
    """A clerk publishing, a physician registering, a clerk reading the ledger.

    PRD 2.1: "If both headers are well formed but the named role is not among the roles
    authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."  The three endpoints name their own audiences: "POST |
    `/disclosure-templates/{id}/publish` | Publish a draft disclosure template, retiring the
    previously published one, under facility-level optimistic concurrency |
    `FacilityAdministrator`", "POST | `/facilities/{id}/encounters` | Register a patient at
    the emergency desk, pinning the published disclosure and computing the good-faith estimate
    | `RegistrationClerk`", and "GET | `/facilities/{id}/compliance-ledger-entries` |
    Append-only compliance ledger for the facility, oldest first | `FacilityAdministrator`,
    `ComplianceOfficer`".

    Design: Corner/errors/registration_clerk_cannot_publish_a_template_or_read_the_compliance_ledger
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)

    validate_error(
        api_client.publish_disclosure_template(
            template["id"], make_publish_payload(facility["version"]), CLERK
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.register_encounter(
            facility["id"],
            make_encounter_payload(
                patient_reference="PT-3401",
                acuity_level=2,
                presenting_service_line="GENERAL_MEDICAL",
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.list_compliance_ledger_entries(facility["id"], CLERK),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    unpublished = validate_success(
        api_client.get_disclosure_template(template["id"], ADMIN)
    )
    assert unpublished["status"] == "DRAFT"

    unchanged = read_facility(facility["id"])
    assert unchanged["current_published_template_id"] is None
    assert unchanged["version"] == facility["version"]

    _, meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": facility["id"]})
    )
    assert_total_count(meta, 0)


def test_every_read_path_names_the_entity_it_could_not_find():
    """Eleven unminted ids, eleven different codes, and one query-string miss.

    PRD 2.6: "Path-referenced resources must exist, and are resolved in the order they
    appear in the URL: the facility first, then the disclosure template, payer contract,
    physician shift, volume forecast, transfer agreement, ambulance memorandum, encounter,
    ancillary order, transfer order, claim, or dispute case named deeper in the path. A miss
    yields the not-found error for the segment that failed — `ERR_FACILITY_NOT_FOUND`,
    `ERR_DISCLOSURE_TEMPLATE_NOT_FOUND`, `ERR_PAYER_CONTRACT_NOT_FOUND`,
    `ERR_PHYSICIAN_SHIFT_NOT_FOUND`, `ERR_VOLUME_FORECAST_NOT_FOUND`,
    `ERR_TRANSFER_AGREEMENT_NOT_FOUND`, `ERR_AMBULANCE_MOU_NOT_FOUND`,
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_ANCILLARY_ORDER_NOT_FOUND`,
    `ERR_TRANSFER_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_DISPUTE_CASE_NOT_FOUND` —
    each at HTTP 404."  The coverage-summary miss comes from the next step, which covers
    references arriving other than through the path: "Resources referenced from the request
    body or query string must exist and must belong to the same facility as the path
    resource, checked in this declared field order: `transfer_agreement_id`, then
    `ambulance_mou_id`, then `payer_contract_id`, then `volume_forecast_id`, yielding
    `ERR_TRANSFER_AGREEMENT_NOT_FOUND`, `ERR_AMBULANCE_MOU_NOT_FOUND`,
    `ERR_PAYER_CONTRACT_NOT_FOUND`, or `ERR_VOLUME_FORECAST_NOT_FOUND` at HTTP 404."

    Design: Corner/errors/every_single_read_path_returns_its_own_not_found_error
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    version_before = read_facility(facility_id)["version"]

    expected_per_read = (
        (
            api_client.get_facility(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
        ),
        (
            api_client.get_disclosure_template(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_DISCLOSURE_TEMPLATE_NOT_FOUND.value,
        ),
        (
            api_client.get_payer_contract(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PAYER_CONTRACT_NOT_FOUND.value,
        ),
        (
            api_client.get_physician_shift(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PHYSICIAN_SHIFT_NOT_FOUND.value,
        ),
        (
            api_client.get_volume_forecast(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_VOLUME_FORECAST_NOT_FOUND.value,
        ),
        (
            api_client.get_transfer_agreement(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_TRANSFER_AGREEMENT_NOT_FOUND.value,
        ),
        (
            api_client.get_ambulance_mou(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AMBULANCE_MOU_NOT_FOUND.value,
        ),
        (
            api_client.get_ancillary_order(NON_EXISTENT_UUID, PHYSICIAN),
            ApiErrorId.ERR_ANCILLARY_ORDER_NOT_FOUND.value,
        ),
        (
            api_client.get_transfer_order(NON_EXISTENT_UUID, PHYSICIAN),
            ApiErrorId.ERR_TRANSFER_ORDER_NOT_FOUND.value,
        ),
        (
            api_client.get_claim(NON_EXISTENT_UUID, OFFICER),
            ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
        ),
        (
            api_client.get_dispute_case(NON_EXISTENT_UUID, OFFICER),
            ApiErrorId.ERR_DISPUTE_CASE_NOT_FOUND.value,
        ),
    )
    for response, expected_error_id in expected_per_read:
        validate_error(response, expected_error_id, 404)

    validate_error(
        api_client.get_coverage_summary(
            facility_id, OFFICER, params={"volume_forecast_id": NON_EXISTENT_UUID}
        ),
        ApiErrorId.ERR_VOLUME_FORECAST_NOT_FOUND.value,
        404,
    )

    assert read_facility(facility_id)["version"] == version_before


def test_a_template_can_only_be_published_once():
    """The second publish is refused on status, not on the concurrency token.

    PRD 3.2: "Only a `FacilityAdministrator` may publish, only a `DRAFT` template may be
    published (otherwise `ERR_TEMPLATE_NOT_PUBLISHABLE`), and the request must carry
    `expected_facility_version` matching the facility's current `version` (otherwise
    `ERR_STALE_FACILITY_VERSION` at HTTP 412, as Section 2.5 sets out)."  PRD 2.6 restates it
    as its own ladder step: "A template must be in `DRAFT` before it can be published, else
    `ERR_TEMPLATE_NOT_PUBLISHABLE` (409)."  A successful publication is what appends the
    entry that must not appear twice: "a ledger entry with `event_type` `TEMPLATE_PUBLISHED`
    is appended, the facility's `version` is incremented by 1, and the posture is
    recomputed".

    Design: Corner/errors/publish_of_an_already_published_template_returns_template_not_publishable
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    template_id = context["template_id"]
    current_version = read_facility(facility_id)["version"]

    validate_error(
        api_client.publish_disclosure_template(
            template_id, make_publish_payload(current_version), ADMIN
        ),
        ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHABLE.value,
        409,
    )

    still_published = validate_success(
        api_client.get_disclosure_template(template_id, ADMIN)
    )
    assert still_published["status"] == "PUBLISHED"

    assert_ledger_entry(
        ledger_entries(facility_id, OFFICER, params={"event_type": "TEMPLATE_PUBLISHED"}),
        "TEMPLATE_PUBLISHED",
        count=1,
    )
    assert read_facility(facility_id)["version"] == current_version


def test_a_resulted_study_cannot_be_cancelled_afterwards():
    """`RESULTED` is terminal, so the money on the line cannot be taken back.

    PRD 3.7: "The physician resolves an order with an `outcome` of `RESULTED` or `CANCELLED`
    plus an optional `result_note`, and the order must still be `ORDERED` (otherwise
    `ERR_INVALID_ANCILLARY_ORDER_STATE`)." and "Both `RESULTED` and `CANCELLED` are
    terminal."  The line total the refusal must preserve is fixed at creation: "`unit_charge_cents`
    is looked up by `code`: 12000 for `XRAY`, 49000 for `CT`, 24000 for `ULTRASOUND`, 145000
    for `MRI`, 4500 for `CBC`, 6200 for `CHEMISTRY`, 15500 for `TROPONIN`, 11500 for
    `BLOOD_CULTURE`, 8500 for `ANALGESIC`, 7400 for `ANTIBIOTIC`, and 210000 for
    `THROMBOLYTIC`."

    Design: Corner/errors/resolving_an_already_resolved_ancillary_order_returns_invalid_ancillary_order_state
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-3501",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    order = order_ancillary(encounter["id"], "IMAGING", "CT", 2)
    resolved = resolve_ancillary(order["id"], "RESULTED")
    assert resolved["line_total_cents"] == RESULTED_CT_PAIR_CENTS

    validate_error(
        api_client.resolve_ancillary_order(
            order["id"], make_ancillary_resolve_payload("CANCELLED"), PHYSICIAN
        ),
        ApiErrorId.ERR_INVALID_ANCILLARY_ORDER_STATE.value,
        409,
    )

    unchanged = validate_success(
        api_client.get_ancillary_order(order["id"], PHYSICIAN)
    )
    assert unchanged["status"] == "RESULTED"
    assert unchanged["line_total_cents"] == RESULTED_CT_PAIR_CENTS


def test_a_declined_transfer_order_accepts_no_further_coordinator_action():
    """Both remaining coordinator verbs are refused, and no unit is re-reserved.

    PRD 3.8: "`DECLINED`, `CANCELLED` and `COMPLETED` are all terminal for a transfer
    order."  PRD 2.6 gives the code: "The status of the acted-upon child must permit the
    requested transition: an ancillary order must be `ORDERED` before it is resolved
    (`ERR_INVALID_ANCILLARY_ORDER_STATE`), a transfer order's status must match the requested
    transition (`ERR_INVALID_TRANSFER_ORDER_STATE`), a claim's status must match
    (`ERR_INVALID_CLAIM_STATE`), and a dispute case's status must match
    (`ERR_INVALID_DISPUTE_STATE`) — all at HTTP 409."  The decline itself already unwound
    everything, per PRD 3.8: "`reserved_unit_count` drops to 0; because the order has left
    the reserving statuses, the memorandum's `units_reserved` decreases by one and
    `units_available` is recomputed as `units_committed` less `units_reserved`" and "The
    encounter's `declined_transfer_count` is incremented by 1 and its `clinical_state`
    returns along one of two paths: `TRANSFER_PENDING → OBSERVATION` when
    `observation_bed_held` is true, and `TRANSFER_PENDING → MSE_COMPLETE` when it is false."

    Design: Corner/errors/accepting_a_declined_transfer_order_returns_invalid_transfer_order_state
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )
    order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        context["mou_id"],
        context["encounter_version"],
    )
    declined = validate_success(
        api_client.decline_transfer_order(
            order["id"], make_transfer_decline_payload("CAPACITY"), COORDINATOR
        )
    )
    assert declined["status"] == "DECLINED"

    for response in (
        api_client.accept_transfer_order(
            order["id"], make_transfer_accept_payload(), COORDINATOR
        ),
        api_client.complete_transfer_order(
            order["id"], make_transfer_complete_payload(), COORDINATOR
        ),
    ):
        validate_error(response, ApiErrorId.ERR_INVALID_TRANSFER_ORDER_STATE.value, 409)

    terminal = validate_success(
        api_client.get_transfer_order(order["id"], COORDINATOR)
    )
    assert terminal["status"] == "DECLINED"
    assert terminal["decline_reason"] == "CAPACITY"
    assert terminal["reserved_unit_count"] == 0

    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)

    returned = read_encounter(context["encounter_id"])
    assert returned["clinical_state"] == "MSE_COMPLETE"
    assert returned["declined_transfer_count"] == 1


def test_no_bed_is_taken_until_the_screening_is_finished():
    """The sequencing error has its own code, and the retry afterwards works.

    PRD 3.7: "Observation admission — the choice a facility with no inpatient beds makes when
    a patient needs watching but not admitting — accepts an optional `observation_plan_note`
    and requires four things: the encounter must be in `MSE_COMPLETE` (an attempt from
    `ARRIVED` or `MSE_IN_PROGRESS` is `ERR_MSE_NOT_COMPLETE`, and one from a terminal or
    transfer-pending state is `ERR_INVALID_ENCOUNTER_STATE`), `stabilization_status` must be
    anything other than `NOT_ASSESSED`, the facility's `compliance_posture` must not be
    `SUSPENDED` (otherwise `ERR_FACILITY_POSTURE_BLOCKED`), and `observation_beds_occupied`
    must be strictly below `observation_bed_count` (otherwise
    `ERR_OBSERVATION_CAPACITY_EXCEEDED`)." and "On success the encounter moves
    `MSE_COMPLETE → OBSERVATION`, `observation_bed_held` becomes true, `observation_started_at`
    is stamped with the logical clock on first entry into observation, the facility's
    `observation_beds_occupied` is recomputed upward by one, and the facility's `version` is
    incremented by 1."  PRD 2.6 names the step: "The medical screening examination must be
    complete — `clinical_state` must be neither `ARRIVED` nor `MSE_IN_PROGRESS` — before an
    observation admission or a transfer order, else `ERR_MSE_NOT_COMPLETE` (409)."

    Design: Corner/errors/observation_before_the_screening_is_complete_returns_mse_not_complete
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-3701",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    begin_mse(encounter["id"])

    validate_error(
        api_client.admit_to_observation(
            encounter["id"],
            make_observation_payload(observation_plan_note="too early"),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_MSE_NOT_COMPLETE.value,
        409,
    )

    refused = read_encounter(encounter["id"])
    assert refused["clinical_state"] == "MSE_IN_PROGRESS"
    assert refused["observation_bed_held"] is False
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 0

    complete_mse(encounter["id"], "STABLE")
    admitted = admit_to_observation(
        encounter["id"], PHYSICIAN, observation_plan_note="serial troponins"
    )

    assert admitted["clinical_state"] == "OBSERVATION"
    assert admitted["observation_bed_held"] is True
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 1
