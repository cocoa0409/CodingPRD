"""Requests that break two rules at once, where only one error may be reported.

Three different category pairs are exercised: a clinical-state rule against a
safety certification, a posture gate against a licensed-scope gate, and an
agreement's date window against its capability match.  In each case the losing
check is shown to be genuinely live by removing the winning condition and watching
the second error surface.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_mou_unit_ledger, assert_posture
from test_helpers.factories import (
    make_ancillary_order_payload,
    make_transfer_order_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    PHYSICIAN,
    acknowledge_disclosure,
    create_ambulance_mou,
    create_transfer_agreement,
    discharge,
    open_facility,
    patch_facility,
    read_ambulance_mou,
    read_encounter,
    read_facility,
    register_encounter,
    restore_licence,
    screen_encounter,
    transfer_ready_encounter,
)

SCOPE_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT", "ULTRASOUND"],
    "lab_scope": ["CBC", "TROPONIN"],
}
MRI_ORDER = {"category": "IMAGING", "code": "MRI", "quantity": 1}


def _discharged_patient_with_transfer_arrangements():
    """A closed encounter that still has a live agreement and memorandum to name."""
    context = transfer_ready_encounter(acuity_level=4, service_line="CARDIAC")
    closed = discharge(context["encounter_id"])
    context["encounter_version"] = closed["version"]
    return context


def test_discharged_encounter_reports_the_state_error_not_the_certification_error():
    """The clinical-state check at step 9 outranks the certification check at step 13.

    PRD 2.6 step 9: "An encounter's `clinical_state` must be a declared source state
    for the requested clinical transition and must not be terminal, else
    `ERR_INVALID_ENCOUNTER_STATE` (409)."  PRD 2.6 step 13 comes later: "
    `clinical_benefit_certified` must be true on a transfer order, else
    `ERR_TRANSFER_CERTIFICATION_REQUIRED` (422)."  PRD 2.6 also states the tie-break
    rule outright: "the checks are evaluated in the order below and the **first**
    failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/discharged_encounter_with_uncertified_transfer_yields_state_error_not_certification_error
    """
    context = _discharged_patient_with_transfer_arrangements()

    response = api_client.create_transfer_order(
        context["encounter_id"],
        make_transfer_order_payload(
            context["agreement_id"],
            context["mou_id"],
            context["encounter_version"],
            clinical_benefit_certified=False,
        ),
        PHYSICIAN,
    )

    reported = validate_error(response, ApiErrorId.ERR_INVALID_ENCOUNTER_STATE.value)
    assert (
        reported["error_id"] != ApiErrorId.ERR_TRANSFER_CERTIFICATION_REQUIRED.value
    )
    assert read_encounter(context["encounter_id"])["clinical_state"] == "DISCHARGED"


def test_the_refused_uncertified_transfer_order_reserves_nothing_at_all():
    """A rejected transfer order is not a transfer order: nothing is written.

    PRD 3.8 pins what a *created* order does: "A created order is `REQUESTED`, with
    `requested_at` stamped, `certifying_physician_user_id` set to the acting
    physician, and `reserved_unit_count` of 1."  None of that may happen here, and
    PRD 2.10 keeps the memorandum's books straight regardless: "`units_available`
    equals `units_committed` minus `units_reserved`".

    Design: Difficulty/priority_pair_validation_conflict/discharged_encounter_with_uncertified_transfer_yields_state_error_not_certification_error
    """
    context = _discharged_patient_with_transfer_arrangements()

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"],
                context["mou_id"],
                context["encounter_version"],
                clinical_benefit_certified=False,
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_INVALID_ENCOUNTER_STATE.value,
    )

    orders, meta = validate_paginated(
        api_client.list_transfer_orders(
            PHYSICIAN, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert orders == []
    assert meta["total_count"] == 0
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def _restricted_facility_with_a_screened_patient():
    """An OPEN facility driven to RESTRICTED by a licence downgrade, mid-encounter."""
    context = open_facility(facility_overrides=SCOPE_FACILITY)
    facility_id = context["facility_id"]
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-8001",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    downgraded = patch_facility(
        facility_id, read_facility(facility_id)["version"], ADMIN,
        license_status="PROBATION",
    )
    context.update(
        {
            "encounter_id": encounter["id"],
            "facility": downgraded,
            "facility_version": downgraded["version"],
        }
    )
    return context


def test_restricted_posture_reports_the_posture_error_not_the_out_of_scope_error():
    """The posture gate at step 16 outranks the licensed-scope gate at step 19.

    PRD 2.6 step 16: "The facility posture gate: a `SUSPENDED` posture blocks
    registration, observation admission and every ancillary order, and a `RESTRICTED`
    posture blocks an ancillary order whose `code` appears in the facility's
    `restricted_service_codes`; either way the rejection is
    `ERR_FACILITY_POSTURE_BLOCKED` (409)."  Step 19 sits behind it: "The ordered
    `code` must fall inside the facility's licensed scope, else
    `ERR_OUT_OF_SCOPE_SERVICE` (422)."  A licence on probation reaches the restricted
    rung by PRD 2.8's ladder — "otherwise if `license_status` is `PROBATION`, the
    posture is `RESTRICTED`" — and PRD 2.8 fixes the list: "When the posture is
    `RESTRICTED` the list is exactly `MRI` and `THROMBOLYTIC`."

    Design: Difficulty/priority_pair_validation_conflict/restricted_posture_with_out_of_scope_mri_yields_posture_error_not_scope_error
    """
    context = _restricted_facility_with_a_screened_patient()

    assert_posture(context["facility"], "RESTRICTED")
    assert "MRI" not in context["facility"]["imaging_scope"]

    response = api_client.create_ancillary_order(
        context["encounter_id"], make_ancillary_order_payload(**MRI_ORDER), PHYSICIAN
    )

    reported = validate_error(response, ApiErrorId.ERR_FACILITY_POSTURE_BLOCKED.value)
    assert reported["error_id"] != ApiErrorId.ERR_OUT_OF_SCOPE_SERVICE.value

    orders, meta = validate_paginated(
        api_client.list_ancillary_orders(context["encounter_id"], PHYSICIAN)
    )
    assert orders == []
    assert meta["total_count"] == 0


def test_clearing_the_posture_reveals_the_licensed_scope_gate_behind_it():
    """The losing check is live: restore the licence and the scope error surfaces.

    PRD 3.7 describes the two gates as consecutive rather than alternative: "Two further
    gates then apply, in this order: the posture gate, where a `SUSPENDED` facility
    blocks every ancillary order and a `RESTRICTED` facility blocks any order whose
    `code` appears in `restricted_service_codes`, both reported as
    `ERR_FACILITY_POSTURE_BLOCKED`; and the licensed-scope gate, where an `IMAGING` code
    must appear in the facility's `imaging_scope`".  With the posture back to `OPEN`,
    PRD 2.8's "When the posture is `OPEN` the list is empty" empties
    `restricted_service_codes`, and the same MRI request now fails PRD 2.6 step 19
    instead — "The ordered `code` must fall inside the facility's licensed scope, else
    `ERR_OUT_OF_SCOPE_SERVICE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/restricted_posture_with_out_of_scope_mri_yields_posture_error_not_scope_error
    """
    context = _restricted_facility_with_a_screened_patient()

    reopened = restore_licence(context["facility_id"], context["facility_version"], ADMIN)
    assert_posture(reopened, "OPEN")
    assert reopened["restricted_service_codes"] == []

    validate_error(
        api_client.create_ancillary_order(
            context["encounter_id"], make_ancillary_order_payload(**MRI_ORDER), PHYSICIAN
        ),
        ApiErrorId.ERR_OUT_OF_SCOPE_SERVICE.value,
    )

    licensed = validate_success(
        api_client.create_ancillary_order(
            context["encounter_id"],
            make_ancillary_order_payload(category="IMAGING", code="CT", quantity=1),
            PHYSICIAN,
        ),
        expected_status=201,
    )
    assert licensed["code"] == "CT"
    assert licensed["status"] == "ORDERED"


def _acuity_five_patient_with_an_expired_low_tier_agreement():
    """An EXPIRED GENERAL_MEDICAL tier-1 agreement offered for an acuity-5 CARDIAC patient."""
    context = open_facility(facility_overrides=SCOPE_FACILITY)
    facility_id = context["facility_id"]
    expired = create_transfer_agreement(
        facility_id,
        ADMIN,
        destination_hospital_name="Sabine County Hospital",
        service_line="GENERAL_MEDICAL",
        capability_tier=1,
        accepts_unstable=False,
        effective_start_date="2026-06-01",
        effective_end_date="2026-06-30",
    )
    mou = create_ambulance_mou(
        facility_id, ADMIN, level_of_care="CRITICAL_CARE", units_committed=2
    )
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-9001",
        acuity_level=5,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screened = screen_encounter(encounter["id"], "STABLE")
    context.update(
        {
            "expired_agreement": expired,
            "expired_agreement_id": expired["id"],
            "mou_id": mou["id"],
            "encounter_id": encounter["id"],
            "encounter_version": screened["version"],
        }
    )
    return context


def test_expired_agreement_reports_the_window_error_not_the_capability_error():
    """The agreement-window check at step 22 outranks the capability match at step 25.

    PRD 2.6 step 22: "The referenced transfer agreement must be `ACTIVE` at order
    creation and again at acceptance, else `ERR_AGREEMENT_NOT_ACTIVE` (422)."  Step 25
    is later: "The agreement's `service_line` must equal the encounter's
    `presenting_service_line` and its `capability_tier` must meet the acuity's required
    tier, else `ERR_TRANSFER_CAPABILITY_INSUFFICIENT` (422)."  A June window is behind
    the clock, and PRD 3.5 makes the status derivation explicit: "`PENDING` while the
    clock date is before `effective_start_date`, `ACTIVE` while the clock date falls
    within the window inclusive of both endpoints, and `EXPIRED` once the clock date has
    passed `effective_end_date`."

    Design: Difficulty/priority_pair_validation_conflict/expired_agreement_with_insufficient_capability_yields_temporal_error_not_referential_error
    """
    context = _acuity_five_patient_with_an_expired_low_tier_agreement()

    assert context["expired_agreement"]["status"] == "EXPIRED"

    response = api_client.create_transfer_order(
        context["encounter_id"],
        make_transfer_order_payload(
            context["expired_agreement_id"],
            context["mou_id"],
            context["encounter_version"],
        ),
        PHYSICIAN,
    )

    reported = validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    assert (
        reported["error_id"] != ApiErrorId.ERR_TRANSFER_CAPABILITY_INSUFFICIENT.value
    )
    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def test_an_active_but_mismatched_agreement_reveals_the_capability_check_behind_it():
    """The losing check is live: an in-window agreement fails on service line and tier.

    PRD 3.8 spells out both halves of the referential rule this acuity-5 patient
    breaks: "acuity 1 and acuity 2 both require tier 1, acuity 3 requires tier 2,
    acuity 4 requires tier 3, and acuity 5 requires tier 4. A wrong service line or an
    insufficient tier is `ERR_TRANSFER_CAPABILITY_INSUFFICIENT`."  Because the
    replacement agreement's window covers the clock, the step-22 check no longer fires
    and the step-25 check is the first failure instead.

    Design: Difficulty/priority_pair_validation_conflict/expired_agreement_with_insufficient_capability_yields_temporal_error_not_referential_error
    """
    context = _acuity_five_patient_with_an_expired_low_tier_agreement()

    in_window = create_transfer_agreement(
        context["facility_id"],
        ADMIN,
        destination_hospital_name="Bluff Creek Medical Center",
        service_line="GENERAL_MEDICAL",
        capability_tier=1,
        accepts_unstable=False,
        effective_start_date="2026-07-01",
        effective_end_date="2026-12-31",
    )
    assert in_window["status"] == "ACTIVE"

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                in_window["id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_TRANSFER_CAPABILITY_INSUFFICIENT.value,
    )

    orders, meta = validate_paginated(
        api_client.list_transfer_orders(
            PHYSICIAN, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert orders == []
    assert meta["total_count"] == 0
