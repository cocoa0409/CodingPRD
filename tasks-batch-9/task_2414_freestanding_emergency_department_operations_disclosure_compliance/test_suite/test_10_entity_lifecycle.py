"""The rows themselves: what a create writes, what a read returns, what is refused.

These cases stay deliberately close to the surface of each entity — the envelope a
creation comes back in, the defaults a row starts life with, the fields the server
stamps for itself, the paging window over a collection, and the four ways a
reference or an input can be wrong.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_ordered_oldest_first,
    assert_meta,
    assert_mou_unit_ledger,
    assert_posture,
    assert_total_count,
)
from test_helpers.constants import RESTRICTED_CODES_WHEN_RESTRICTED
from test_helpers.factories import (
    make_encounter_payload,
    make_facility_payload,
    make_physician_shift_payload,
    make_transfer_order_payload,
    make_volume_forecast_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PHYSICIAN,
    create_payer_contract,
    ledger_entries,
    open_facility,
    read_ambulance_mou,
    read_encounter,
    register_encounter,
    set_clock,
    transfer_ready_encounter,
)
from test_helpers.test_users import CLERK_USER_ID, CO_USER_ID
from test_helpers.types import assert_ledger_entry_shape

WORKING_INSTANT = "2026-08-01T08:00:00Z"
DEADLINE_INSTANT = "2026-08-01T08:30:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
# PRD 3.6: a facility fee of 145000 plus the 35000-cent acuity-2 allowance is a
# base subtotal of 180000, which draws the five-percent band and a 9000-cent
# surcharge.
ACUITY_TWO_ESTIMATE_CENTS = 189000


def test_registering_a_facility_returns_the_new_row_inside_the_success_envelope():
    """The creation answers 201, in the standard envelope, with every derived default.

    PRD 4: "Endpoints that create a new resource return HTTP 201 with the created
    resource in `data`".  PRD 2.2 fixes the wrapper around it: "The `api_request_id` is
    a server-generated unique identifier for the request that starts with `req_`." and
    "The `response_type` is either "object" for a single resource or "array" for a list
    of resources."  PRD 3.1 pins what a brand-new facility holds: "Its
    `signage_attestation_status` is `PENDING` with `signage_attested_at`,
    `signage_expires_at` and `signage_attested_by_user_id` all null;
    `observation_beds_occupied`, `open_compliance_defect_count` are 0 and
    `current_published_template_id` is null; `ambulance_units_committed_total` and
    `ambulance_units_reserved_total` are 0 with `transfer_capacity_state` reading
    `SATURATED`; `coverage_deficit_flag` is false; and `version` is 1."  The stamps come
    from PRD 2.4's clock, because "All domain time in this system comes from a **logical
    clock**, not from wall-clock time."

    Design: Corner/entities/create_facility_returns_the_declared_entity_inside_the_success_envelope
    """
    set_clock(WORKING_INSTANT)

    response = api_client.create_facility(make_facility_payload(**NARROW_FACILITY), ADMIN)
    facility = validate_success(response, expected_status=201)

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert envelope["meta"]["api_request_timestamp"]


    assert isinstance(facility["id"], str) and facility["id"]
    assert facility["version"] == 1
    assert facility["name"] == "Cedar Freestanding ED"
    assert facility["state_code"] == "TX"
    assert facility["license_category"] == "INDEPENDENT_FREESTANDING_ED"
    assert facility["license_status"] == "ACTIVE"
    assert facility["observation_bed_count"] == 2
    assert facility["max_concurrent_physicians"] == 2
    assert facility["pharmacy_scope_tier"] == "EMERGENCY_ONLY"

    assert facility["observation_beds_occupied"] == 0
    assert facility["open_compliance_defect_count"] == 0
    assert facility["current_published_template_id"] is None
    assert facility["ambulance_units_committed_total"] == 0
    assert facility["coverage_deficit_flag"] is False

    assert_instant_equals(facility["created_at"], WORKING_INSTANT, "created_at")
    assert_instant_equals(facility["updated_at"], WORKING_INSTANT, "updated_at")


def test_reading_the_facility_back_returns_the_configuration_it_was_stood_up_with():
    """A read is a read: the licensed scope, the published template and the posture.

    PRD 3.1: "An accepted attestation sets `signage_attestation_status` to `ATTESTED`,
    stamps `signage_attested_at` with the logical clock, computes `signage_expires_at` as
    that instant plus one year of validity (365 days), and records the acting operator as
    `signage_attested_by_user_id`."  With the template published as well, PRD 2.8's ladder
    ends at "otherwise the posture is `OPEN`", and PRD 2.8 adds that "When the posture is
    `OPEN` the list is empty."

    Design: Corner/entities/get_facility_returns_the_stored_configuration_unchanged
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    facility = validate_success(
        api_client.get_facility(context["facility_id"], ADMIN)
    )

    assert facility["id"] == context["facility_id"]
    assert facility["imaging_scope"] == ["XRAY", "CT"]
    assert facility["lab_scope"] == ["CBC", "TROPONIN"]
    assert facility["current_published_template_id"] == context["template_id"]
    assert facility["signage_attestation_status"] == "ATTESTED"
    assert facility["signage_attested_by_user_id"] == CO_USER_ID
    assert_posture(facility, "OPEN")


def test_the_encounter_list_hands_back_three_registrations_two_at_a_time():
    """Two pages over three rows, with the window reported and the remainder flagged.

    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before the
    window was applied, and `has_more` as a boolean that is true when rows remain beyond
    the current window."  PRD 2.2 pins the shape of a list body: "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/list_encounters_paginates_with_total_count_and_has_more
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    registered = [
        register_encounter(
            context["facility_id"],
            CLERK,
            patient_reference=reference,
            acuity_level=2,
            presenting_service_line="GENERAL_MEDICAL",
        )["id"]
        for reference in ("PT-0001", "PT-0002", "PT-0003")
    ]

    first_response = api_client.list_encounters(
        OFFICER, params={"facility_id": context["facility_id"], "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)

    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_page, second_meta = validate_paginated(
        api_client.list_encounters(
            OFFICER,
            params={"facility_id": context["facility_id"], "limit": 2, "offset": 2},
        )
    )

    assert len(second_page) == 1
    assert_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    windowed = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(windowed) == len(set(windowed))
    assert set(windowed) == set(registered)


def test_reading_an_encounter_id_that_was_never_minted_is_a_not_found_error():
    """The answer is the error envelope, not an empty object.

    PRD 2.6: "Path-referenced resources must exist, and are resolved in the order they
    appear in the URL".  The miss for this segment is named in the same step —
    `ERR_ENCOUNTER_NOT_FOUND` — and PRD 2.2 pins what the body must carry: "The
    `error_id` is a unique, machine-readable string that identifies the specific error."
    and "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_encounter_with_unknown_id_returns_not_found
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    response = api_client.get_encounter(NON_EXISTENT_UUID, PHYSICIAN)
    reported = validate_error(response, ApiErrorId.ERR_ENCOUNTER_NOT_FOUND.value)

    assert response.json()["response_type"] == "error"
    assert reported["message"].strip()

    _, meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": context["facility_id"]})
    )
    assert_total_count(meta, 0)


def test_registering_without_an_acuity_level_is_a_malformed_request():
    """The triage level is not optional, and nothing is written when it is missing.

    PRD 3.6: "The clerk supplies an opaque `patient_reference` of 1 to 64 characters, a
    triage `acuity_level` from 1 (least acute) to 5 (most acute), and the
    `presenting_service_line` the presentation belongs to, drawn from the same six-value
    vocabulary the transfer agreements use: `GENERAL_MEDICAL`, `CARDIAC`, `STROKE`,
    `TRAUMA`, `PEDIATRIC`, `PSYCHIATRIC`."  PRD 2.6 puts the omission on the request-shape
    rung: "Required fields must be present, enum members must be declared values,
    integers must satisfy their declared minimums" and "Any breach is
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_encounter_without_acuity_level_returns_invalid_request
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    validate_error(
        api_client.register_encounter(
            context["facility_id"],
            {"patient_reference": "PT-0101", "presenting_service_line": "GENERAL_MEDICAL"},
            CLERK,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": context["facility_id"]})
    )
    assert_total_count(meta, 0)


def test_omitting_the_licence_status_leaves_the_facility_active_but_still_restricted():
    """The one optional input defaults, and the facility is nonetheless not yet open.

    PRD 3.1 names it as optional: "an optional `license_status` that defaults to `ACTIVE`
    and may otherwise be `PROBATION` or `SUSPENDED`".  An active licence is not enough on
    its own, because PRD 3.1 continues: "Its `signage_attestation_status` is `PENDING`
    with `signage_attested_at`, `signage_expires_at` and `signage_attested_by_user_id` all
    null" and "Because signage is `PENDING` and no template is published, the very first
    posture computation lands on `RESTRICTED` with `restricted_service_codes` holding
    `MRI` and `THROMBOLYTIC`."

    Design: Corner/entities/omitting_license_status_defaults_the_facility_to_active
    """
    set_clock(WORKING_INSTANT)

    facility = validate_success(
        api_client.create_facility(
            {
                "name": "Cedar Freestanding ED",
                "state_code": "TX",
                "license_category": "INDEPENDENT_FREESTANDING_ED",
                "observation_bed_count": 2,
                "imaging_scope": ["XRAY", "CT"],
                "lab_scope": ["CBC", "TROPONIN"],
                "pharmacy_scope_tier": "EMERGENCY_ONLY",
                "max_concurrent_physicians": 2,
            },
            ADMIN,
        ),
        expected_status=201,
    )

    assert facility["license_status"] == "ACTIVE"
    assert facility["signage_attestation_status"] == "PENDING"
    assert facility["signage_attested_at"] is None
    assert facility["signage_expires_at"] is None
    assert_posture(facility, "RESTRICTED")
    assert sorted(facility["restricted_service_codes"]) == sorted(
        RESTRICTED_CODES_WHEN_RESTRICTED
    )


def test_dispute_eligibility_is_derived_from_the_network_status_and_the_state_regime():
    """Three contracts differing only in those two inputs land on two different answers.

    PRD 3.3: "Neither of the contract's two derived fields is ever supplied by a client."
    The rule itself is stated in the same paragraph: "`idr_eligible` is true exactly when
    `network_status` is `OUT_OF_NETWORK` **and** `state_protection_regime` is anything
    other than `STATE_EXEMPT_FSED`."  The companion derivation pins the status: "`status`
    reads `ACTIVE` when the logical clock's date falls on or after `effective_start_date`
    and on or before `effective_end_date`, and `TERMINATED` otherwise".

    Design: Corner/entities/payer_contract_idr_eligible_is_computed_from_network_status_and_regime
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    federal = create_payer_contract(
        facility_id,
        OFFICER,
        payer_name="Lone Star Health",
        network_status="OUT_OF_NETWORK",
        state_protection_regime="FEDERAL_NSA_ONLY",
    )
    exempt = create_payer_contract(
        facility_id,
        OFFICER,
        payer_name="Pecos Exempt Plan",
        network_status="OUT_OF_NETWORK",
        state_protection_regime="STATE_EXEMPT_FSED",
    )
    in_network = create_payer_contract(
        facility_id,
        OFFICER,
        payer_name="Hill Country HMO",
        network_status="IN_NETWORK",
        state_protection_regime="STATE_PROTECTED_FSED",
    )

    assert federal["idr_eligible"] is True
    assert federal["status"] == "ACTIVE"
    assert exempt["idr_eligible"] is False
    assert in_network["idr_eligible"] is False


def test_registration_stamps_the_arrival_the_deadline_and_the_estimate_itself():
    """Four of the encounter's most consequential fields are the server's to write.

    PRD 3.6: "`arrival_at` is stamped with the logical clock and `registered_by_user_id`
    with the acting clerk." and "`mse_start_deadline_at` is computed as `arrival_at` plus
    half an hour (30 minutes), with `mse_timeliness` reading `PENDING` until screening
    actually begins."  The pinning and the quote follow from the same paragraph:
    "`pinned_disclosure_template_id` is set to the facility's
    `current_published_template_id` and never changes again for the life of the
    encounter, no matter how many later templates are published or retired." and
    "`clinical_state` starts at `ARRIVED` and `disclosure_state` at
    `DISCLOSURE_PRESENTED` — two independent dimensions on one row, each with its own
    transition rules."  The estimate is the acuity-2 arithmetic PRD 3.6 lays out: "the
    base subtotal is the template's `facility_fee_cents` plus the acuity allowance for the
    encounter's acuity level, where the allowance is 15000 cents at acuity 1, 35000 cents
    at acuity 2, 70000 cents at acuity 3, 130000 cents at acuity 4, and 220000 cents at
    acuity 5."

    Design: Corner/entities/encounter_system_fields_are_stamped_by_the_server_and_input_is_ignored
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    encounter = validate_success(
        api_client.register_encounter(
            context["facility_id"],
            make_encounter_payload(
                patient_reference="PT-0201",
                acuity_level=2,
                presenting_service_line="GENERAL_MEDICAL",
            ),
            CLERK,
        ),
        expected_status=201,
    )

    assert_instant_equals(encounter["arrival_at"], WORKING_INSTANT, "arrival_at")
    assert encounter["registered_by_user_id"] == CLERK_USER_ID
    assert_instant_equals(
        encounter["mse_start_deadline_at"], DEADLINE_INSTANT, "mse_start_deadline_at"
    )
    assert encounter["mse_timeliness"] == "PENDING"
    assert encounter["pinned_disclosure_template_id"] == context["template_id"]
    assert encounter["disclosed_estimate_cents"] == ACUITY_TWO_ESTIMATE_CENTS
    assert encounter["clinical_state"] == "ARRIVED"
    assert encounter["disclosure_state"] == "DISCLOSURE_PRESENTED"
    assert encounter["observation_bed_held"] is False
    assert encounter["declined_transfer_count"] == 0


def test_four_out_of_range_or_undeclared_inputs_are_each_a_malformed_request():
    """An acuity above the range, an unknown category, a zero-length shift, a zero period.

    PRD 2.6 puts all four on the same rung: "Required fields must be present, enum members
    must be declared values, integers must satisfy their declared minimums" and "`end_utc`
    must be strictly later than `start_utc`", with "Any breach is `ERR_INVALID_REQUEST`
    (400)."  The ranges themselves are declared where the inputs are: PRD 3.6 gives "a
    triage `acuity_level` from 1 (least acute) to 5 (most acute)", PRD 3.1 gives "the state
    licensure `license_category` — either `INDEPENDENT_FREESTANDING_ED` or
    `HOSPITAL_OUTPATIENT_DEPARTMENT_OFF_CAMPUS`", and PRD 3.4 gives "the `period_days` in
    the period (from 1 to 90)".

    Design: Corner/entities/out_of_range_and_invalid_enum_inputs_are_rejected_with_invalid_request
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    validate_error(
        api_client.register_encounter(
            facility_id,
            make_encounter_payload(
                patient_reference="PT-0301",
                acuity_level=6,
                presenting_service_line="GENERAL_MEDICAL",
            ),
            CLERK,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.create_facility(
            make_facility_payload(
                name="Bad Category ED", license_category="URGENT_CARE_CENTER"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.create_physician_shift(
            facility_id,
            make_physician_shift_payload(
                start_utc="2026-08-03T08:00:00Z", end_utc="2026-08-03T08:00:00Z"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.create_volume_forecast(
            facility_id,
            make_volume_forecast_payload(
                period_start_date="2026-09-01",
                period_days=0,
                historical_daily_volumes=[12],
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, encounter_meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": facility_id})
    )
    assert_total_count(encounter_meta, 0)
    _, shift_meta = validate_paginated(
        api_client.list_physician_shifts(facility_id, ADMIN)
    )
    assert_total_count(shift_meta, 0)
    _, forecast_meta = validate_paginated(
        api_client.list_volume_forecasts(facility_id, ADMIN)
    )
    assert_total_count(forecast_meta, 0)


def test_the_compliance_ledger_is_append_only_and_its_entries_carry_no_version():
    """The thirteenth kind of row is the exception, and the read proves it.

    PRD 2.4: "A `ComplianceLedgerEntry` carries only `id` and `created_at`: it has **no**
    `updated_at` and **no** `version`, because the ledger is append-only and an entry is
    never modified after it is written."  PRD 2.8 lists what each entry does name: "Each
    entry names the `facility_id` it is recorded against, an `event_type` drawn from
    `DISCLOSURE_PRESENTED`, `DISCLOSURE_ACKNOWLEDGED`, `DISCLOSURE_REFUSED`,
    `DISCLOSURE_DEFECT`, `EMERGENT_WAIVER_RECORDED`, `SCREENING_DELAY`,
    `TEMPLATE_PUBLISHED`, `SIGNAGE_ATTESTED`, `POSTURE_CHANGE`,
    `TRANSFER_DECLINED_FOR_INSURANCE`, `BALANCE_BILL_ISSUED`, `IDR_INITIATED`,
    `IDR_AWARDED`, and `IDR_AWARD_WITHDRAWN`".  The order is PRD 2.3's: "The append-only
    compliance ledger is therefore returned oldest entry first, which is the same rule
    stated from the domain's point of view."

    Design: Corner/entities/compliance_ledger_entries_are_append_only_and_carry_no_version
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-0401",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )

    entries = ledger_entries(context["facility_id"])

    assert entries
    for entry in entries:
        assert_ledger_entry_shape(entry)
        assert entry["facility_id"] == context["facility_id"]
        assert_instant_equals(entry["recorded_at"], WORKING_INSTANT, "recorded_at")

    observed = {entry["event_type"] for entry in entries}
    assert {
        "TEMPLATE_PUBLISHED",
        "SIGNAGE_ATTESTED",
        "POSTURE_CHANGE",
        "DISCLOSURE_PRESENTED",
    } <= observed
    assert_ledger_ordered_oldest_first(entries)


def test_registering_under_a_facility_that_does_not_exist_is_a_not_found_error():
    """A perfectly valid registration payload still needs a parent that exists.

    PRD 2.6: "Path-referenced resources must exist, and are resolved in the order they
    appear in the URL: the facility first, then the disclosure template, payer contract,
    physician shift, volume forecast, transfer agreement, ambulance memorandum, encounter,
    ancillary order, transfer order, claim, or dispute case named deeper in the path."  The
    facility is the first segment, so its miss is the one reported.

    Design: Corner/entities/register_encounter_under_unknown_facility_returns_facility_not_found
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    validate_error(
        api_client.register_encounter(
            NON_EXISTENT_UUID,
            make_encounter_payload(
                patient_reference="PT-0501",
                acuity_level=2,
                presenting_service_line="GENERAL_MEDICAL",
            ),
            CLERK,
        ),
        ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
    )

    _, meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": context["facility_id"]})
    )
    assert_total_count(meta, 0)


def test_an_unknown_ambulance_memorandum_is_refused_before_any_unit_is_reserved():
    """The reference is resolved first, so the reservation never happens.

    PRD 2.6: "Resources referenced from the request body or query string must exist and
    must belong to the same facility as the path resource, checked in this declared field
    order: `transfer_agreement_id`, then `ambulance_mou_id`, then `payer_contract_id`,
    then `volume_forecast_id`, yielding `ERR_TRANSFER_AGREEMENT_NOT_FOUND`,
    `ERR_AMBULANCE_MOU_NOT_FOUND`, `ERR_PAYER_CONTRACT_NOT_FOUND`, or
    `ERR_VOLUME_FORECAST_NOT_FOUND` at HTTP 404."  That rung sits above every reservation
    consequence PRD 3.8 describes, and PRD 2.10 pins what the untouched memorandum must
    still read: "`units_available` equals `units_committed` minus `units_reserved`".

    Design: Corner/entities/transfer_order_body_with_unknown_mou_id_returns_not_found_before_any_reservation
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"],
                NON_EXISTENT_UUID,
                context["encounter_version"],
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_AMBULANCE_MOU_NOT_FOUND.value,
    )

    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)

    _, meta = validate_paginated(
        api_client.list_transfer_orders(
            PHYSICIAN, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert_total_count(meta, 0)
