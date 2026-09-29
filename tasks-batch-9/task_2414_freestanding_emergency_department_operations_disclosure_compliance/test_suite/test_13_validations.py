"""The rules that refuse work: scope, segregation, uniqueness, windows and bounds.

Each test isolates one rule by satisfying every other rule around it, so a refusal
can only be the rule under examination — and where the design pairs a refusal with
the request that should have been accepted, both halves are exercised in the same
test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_defect_count,
    assert_facility_unit_totals,
    assert_instant_equals,
    assert_ledger_entry,
    assert_mou_unit_ledger,
    assert_no_ledger_entry,
    assert_posture,
    assert_total_count,
)
from test_helpers.constants import CANONICAL_BILLED_TOTAL_CENTS
from test_helpers.factories import (
    make_ancillary_order_payload,
    make_claim_payload,
    make_disclosure_decision_payload,
    make_offer_payload,
    make_signage_attestation_payload,
    make_template_payload,
    make_transfer_order_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PAYER,
    PHYSICIAN,
    SECOND_CLERK,
    acknowledge_disclosure,
    adjudicated_claim,
    attest_signage,
    closed_encounter_with_canonical_lines,
    create_ambulance_mou,
    create_claim,
    create_dispute_case,
    create_facility,
    create_payer_contract,
    create_transfer_agreement,
    create_transfer_order,
    draft_template,
    exhausted_dispute_case,
    ledger_entries,
    negotiate_rounds,
    open_facility,
    order_ancillary,
    publish_template,
    read_ambulance_mou,
    read_claim,
    read_encounter,
    read_facility,
    register_encounter,
    screen_encounter,
    set_clock,
    transfer_ready_encounter,
    unprotected_contract,
)
from test_helpers.test_users import (
    ADMIN_USER_ID,
    CLERK_USER_ID,
    PHYSICIAN_USER_ID,
    SECOND_CLERK_USER_ID,
    make_compliance_officer_headers,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
SECOND_HOSPITAL = "Bluff Creek Medical Center"
SECOND_CARRIER = "Colorado River Critical Transport"
MOU_COVERAGE_END_INSTANT = "2026-09-01T00:00:00Z"
THREE_ELEMENT_ATTESTATION = [
    "LICENSE_CATEGORY_SIGN",
    "FEE_DISCLOSURE_SIGN",
    "NETWORK_STATUS_SIGN",
]


def _read_dispute_case(case_id, headers=OFFICER):
    return validate_success(api_client.get_dispute_case(case_id, headers))


def test_a_transfer_that_clears_every_gate_reserves_exactly_one_ambulance_unit():
    """The accepted path through the most heavily validated operation in the system.

    PRD 3.8: "A created order is `REQUESTED`, with `requested_at` stamped,
    `certifying_physician_user_id` set to the acting physician, and `reserved_unit_count`
    of 1. Its `round_index` is 1 plus the number of `DECLINED` orders already on that
    encounter, so the first attempt is round 1 and the order created after two declines is
    round 3. The encounter's `clinical_state` becomes `TRANSFER_PENDING`" and "The
    memorandum's `units_reserved`, `units_available` and `saturation_state` are recomputed,
    and so are the facility's `ambulance_units_reserved_total` and
    `transfer_capacity_state`, with the facility's `version` incremented by 1."  The gates
    it clears are the acuity-driven pair — "acuity 4 requires tier 3" and "acuity 4 requires
    `ALS` or `CRITICAL_CARE`" — plus the certification, the agreement window and the
    availability check.

    Design: Corner/validations/transfer_order_with_active_agreement_and_covering_mou_is_accepted
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )

    order = validate_success(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"],
                context["mou_id"],
                context["encounter_version"],
            ),
            PHYSICIAN,
        ),
        201,
    )

    assert order["status"] == "REQUESTED"
    assert order["reserved_unit_count"] == 1
    assert order["round_index"] == 1
    assert order["certifying_physician_user_id"] == PHYSICIAN_USER_ID
    assert_instant_equals(order["requested_at"], WORKING_INSTANT, "requested_at")

    assert read_encounter(context["encounter_id"])["clinical_state"] == "TRANSFER_PENDING"
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=1, available=1)

    facility = read_facility(context["facility_id"])
    assert_facility_unit_totals(facility, committed=2, reserved=1)
    assert_defect_count(facility, 0)


def test_a_culture_the_facility_is_not_licensed_for_is_out_of_scope():
    """The lab scope gate fires on `BLOOD_CULTURE` and stays silent on `CBC`.

    PRD 3.7: "the licensed-scope gate, where an `IMAGING` code must appear in the facility's
    `imaging_scope`, a `LABORATORY` code must appear in its `lab_scope`, and a `PHARMACY`
    code must be permitted by its `pharmacy_scope_tier` — `EMERGENCY_ONLY` permitting
    `ANALGESIC` and `ANTIBIOTIC`, `EXTENDED` additionally permitting `THROMBOLYTIC` — with a
    breach reported as `ERR_OUT_OF_SCOPE_SERVICE`."  The posture gate ahead of it is silent
    because the facility is `OPEN`: it only bites when "a `SUSPENDED` facility blocks every
    ancillary order and a `RESTRICTED` facility blocks any order whose `code` appears in
    `restricted_service_codes`".

    Design: Corner/validations/lab_code_outside_the_licensed_scope_returns_out_of_scope_service
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1501",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")

    validate_error(
        api_client.create_ancillary_order(
            encounter["id"],
            make_ancillary_order_payload("LABORATORY", "BLOOD_CULTURE", 1),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_OUT_OF_SCOPE_SERVICE.value,
    )

    in_scope = order_ancillary(encounter["id"], "LABORATORY", "CBC", 1)
    assert in_scope["line_total_cents"] == 4500

    _, meta = validate_paginated(
        api_client.list_ancillary_orders(encounter["id"], PHYSICIAN)
    )
    assert_total_count(meta, 1)
    assert_posture(read_facility(context["facility_id"]), "OPEN")


def test_the_clerk_who_registered_the_patient_may_not_waive_the_conversation():
    """Segregation of duties on the waiver, with the acuity threshold already met.

    PRD 3.6: "the acting operator must differ from the encounter's `registered_by_user_id`,
    otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES`." and "A waiver appends an
    informational entry with `event_type` `EMERGENT_WAIVER_RECORDED` and `defect_counted`
    false; no defect is counted, because waiving the conversation for a critically ill
    patient is a compliant outcome, not a failure."  The acuity fence ahead of it is
    satisfied: "The encounter's `acuity_level` must be at least 4".

    Design: Corner/validations/emergent_waiver_recorded_by_the_registering_clerk_returns_segregation_of_duties
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1601",
        acuity_level=5,
        presenting_service_line="CARDIAC",
    )
    assert encounter["registered_by_user_id"] == CLERK_USER_ID

    waiver_payload = make_disclosure_decision_payload(
        "EMERGENT_WAIVER", waiver_reason="cardiac arrest en route"
    )
    validate_error(
        api_client.record_disclosure_decision(encounter["id"], waiver_payload, CLERK),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert read_encounter(encounter["id"])["disclosure_state"] == "DISCLOSURE_PRESENTED"

    waived = validate_success(
        api_client.record_disclosure_decision(
            encounter["id"], waiver_payload, SECOND_CLERK
        )
    )

    assert waived["disclosure_state"] == "DISCLOSURE_WAIVED_EMERGENT"
    assert waived["disclosure_decided_by_user_id"] == SECOND_CLERK_USER_ID

    assert_ledger_entry(
        ledger_entries(context["facility_id"]),
        "EMERGENT_WAIVER_RECORDED",
        defect_counted=False,
        count=1,
    )
    assert_defect_count(read_facility(context["facility_id"]), 0)


def test_a_walk_in_patient_is_not_sick_enough_to_waive_the_disclosure():
    """The waiver is a clinical judgement, and acuity 2 does not support one.

    PRD 3.6: "The encounter's `acuity_level` must be at least 4, otherwise the request fails
    with `ERR_WAIVER_NOT_EMERGENT` — a waiver is a clinical judgement about urgency, not a
    convenience."  The segregation control is silent here because a different clerk is
    acting, and the refused decision leaves the dimension where PRD 3.6 put it: "In all three
    outcomes the acting operator is recorded as `disclosure_decided_by_user_id`".

    Design: Corner/validations/emergent_waiver_on_a_low_acuity_encounter_returns_waiver_not_emergent
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1701",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )

    validate_error(
        api_client.record_disclosure_decision(
            encounter["id"],
            make_disclosure_decision_payload(
                "EMERGENT_WAIVER", waiver_reason="patient in a hurry"
            ),
            SECOND_CLERK,
        ),
        ApiErrorId.ERR_WAIVER_NOT_EMERGENT.value,
    )

    undecided = read_encounter(encounter["id"])
    assert undecided["disclosure_state"] == "DISCLOSURE_PRESENTED"
    assert undecided["disclosure_decided_by_user_id"] is None
    assert_defect_count(read_facility(context["facility_id"]), 0)


def test_the_operator_who_published_the_disclosure_may_not_certify_the_signage():
    """The second segregation control, read off the published template's operator.

    PRD 2.9: "A `ComplianceOfficer` filing a signage attestation for a facility may not be
    the same operator who published that facility's currently published disclosure template —
    that is, the acting `X-User-ID` must differ from the `published_by_user_id` recorded on
    the template referenced by the facility's `current_published_template_id`." and "Both
    breaches surface as `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."  With the attestation
    refused the facility keeps the
    posture PRD 3.1 gives a facility that has not certified its signage: "Because signage is
    `PENDING` and no template is published, the very first posture computation lands on
    `RESTRICTED`".

    Design: Corner/validations/signage_attestation_filed_by_the_publisher_returns_segregation_of_duties
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)
    published = publish_template(template["id"], facility["version"], ADMIN)
    assert published["published_by_user_id"] == ADMIN_USER_ID

    validate_error(
        api_client.create_signage_attestation(
            facility["id"],
            make_signage_attestation_payload(),
            make_compliance_officer_headers(ADMIN_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    unattested = read_facility(facility["id"])
    assert unattested["signage_attestation_status"] == "PENDING"
    assert unattested["signage_attested_by_user_id"] is None
    assert_posture(unattested, "RESTRICTED")
    assert_no_ledger_entry(ledger_entries(facility["id"]), "SIGNAGE_ATTESTED")


def test_an_attestation_missing_the_not_urgent_care_placard_is_incomplete():
    """Three of the four required placards is not enough for a freestanding ED.

    PRD 3.1: "The elements are drawn from `LICENSE_CATEGORY_SIGN`, `FEE_DISCLOSURE_SIGN`,
    `NETWORK_STATUS_SIGN` and `NOT_A_URGENT_CARE_SIGN`, and what the facility must show
    depends on how the state licenses it: an `INDEPENDENT_FREESTANDING_ED` must post all
    four, while a `HOSPITAL_OUTPATIENT_DEPARTMENT_OFF_CAMPUS` — which patients can reasonably
    read as part of a hospital — must post the first three and is not required to post the
    not-urgent-care placard. `attested_elements` must contain every element required by the
    category and, when the facility has a published template, every element in that
    template's `required_signage_elements` as well; anything less is rejected with
    `ERR_SIGNAGE_ELEMENTS_INCOMPLETE`."

    Design: Corner/validations/attestation_missing_a_required_signage_element_returns_signage_elements_incomplete
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)
    publish_template(template["id"], facility["version"], ADMIN)

    validate_error(
        api_client.create_signage_attestation(
            facility["id"],
            make_signage_attestation_payload(
                attested_elements=THREE_ELEMENT_ATTESTATION
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_SIGNAGE_ELEMENTS_INCOMPLETE.value,
    )

    refused = read_facility(facility["id"])
    assert refused["signage_attestation_status"] == "PENDING"
    assert_posture(refused, "RESTRICTED")

    attested = attest_signage(facility["id"], OFFICER)
    assert attested["signage_attestation_status"] == "ATTESTED"
    assert_posture(attested, "OPEN")


def test_an_encounter_may_carry_only_one_claim_for_its_whole_life():
    """The second claim on the same visit is refused, and the first is untouched.

    PRD 3.9: "At most one claim may ever exist per encounter, and a second attempt is
    rejected with `ERR_CLAIM_ALREADY_EXISTS`."  The surviving claim keeps what creation froze
    onto it: "`billed_total_cents` is the sum of those two figures. The claim is created with
    `status` `DRAFT`, with `negotiation_rounds_used` 0".

    Design: Corner/validations/second_claim_on_the_same_encounter_returns_claim_already_exists
    """
    context = closed_encounter_with_canonical_lines(clock=WORKING_INSTANT)
    contract = create_payer_contract(
        context["facility_id"],
        OFFICER,
        network_status="OUT_OF_NETWORK",
        state_protection_regime="FEDERAL_NSA_ONLY",
    )
    first_claim = create_claim(context["encounter_id"], contract["id"], OFFICER)

    validate_error(
        api_client.create_claim(
            context["encounter_id"], make_claim_payload(contract["id"]), OFFICER
        ),
        ApiErrorId.ERR_CLAIM_ALREADY_EXISTS.value,
    )

    rows, meta = validate_paginated(
        api_client.list_claims(OFFICER, params={"encounter_id": context["encounter_id"]})
    )
    assert_total_count(meta, 1)
    assert rows[0]["id"] == first_claim["id"]

    stored = read_claim(first_claim["id"])
    assert stored["status"] == "DRAFT"
    assert stored["billed_total_cents"] == CANONICAL_BILLED_TOTAL_CENTS


def test_a_second_template_cannot_reuse_a_version_label_already_taken():
    """`V1` is spent for the life of the facility, published or not.

    PRD 3.2: "The `version_label` must be unique among that facility's templates, whatever
    their status; a collision is `ERR_DUPLICATE_TEMPLATE_VERSION`."  Nothing about the
    facility moves, because PRD 3.2 says a draft "has no effect whatsoever on the facility —
    neither `current_published_template_id` nor the posture moves."

    Design: Corner/validations/duplicate_template_version_label_returns_duplicate_template_version
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    validate_error(
        api_client.create_disclosure_template(
            context["facility_id"],
            make_template_payload(version_label="V1", facility_fee_cents=150000),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_TEMPLATE_VERSION.value,
    )

    _, meta = validate_paginated(
        api_client.list_disclosure_templates(context["facility_id"], ADMIN)
    )
    assert_total_count(meta, 1)
    assert (
        read_facility(context["facility_id"])["current_published_template_id"]
        == context["template_id"]
    )


def test_a_contract_whose_window_closed_last_month_cannot_be_billed_under():
    """The contract terminated itself when the clock moved past its window.

    PRD 3.3: "`status` reads `ACTIVE` when the logical clock's date falls on or after
    `effective_start_date` and on or before `effective_end_date`, and `TERMINATED` otherwise;
    it is re-evaluated on every read and on every validation that consults it, so advancing
    the clock past a window silently terminates the contract with no sweep."  PRD 3.9 names
    the refusal: "The referenced contract's `status` must be `ACTIVE` on the logical clock's
    date, else `ERR_PAYER_CONTRACT_NOT_ACTIVE`."

    Design: Corner/validations/claim_creation_under_a_terminated_contract_returns_payer_contract_not_active
    """
    context = closed_encounter_with_canonical_lines(clock=WORKING_INSTANT)
    contract = create_payer_contract(
        context["facility_id"],
        OFFICER,
        network_status="OUT_OF_NETWORK",
        state_protection_regime="FEDERAL_NSA_ONLY",
        effective_start_date="2026-06-01",
        effective_end_date="2026-06-30",
    )
    assert contract["status"] == "TERMINATED"

    validate_error(
        api_client.create_claim(
            context["encounter_id"], make_claim_payload(contract["id"]), OFFICER
        ),
        ApiErrorId.ERR_PAYER_CONTRACT_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api_client.list_claims(OFFICER, params={"encounter_id": context["encounter_id"]})
    )
    assert_total_count(meta, 0)


def test_a_state_exempt_contract_offers_no_dispute_to_escalate_into():
    """`idr_eligible` false closes the dispute door before it opens.

    PRD 3.3: "`idr_eligible` is true exactly when `network_status` is `OUT_OF_NETWORK` **and**
    `state_protection_regime` is anything other than `STATE_EXEMPT_FSED`." and "A claim whose
    contract has `idr_eligible` false can be adjudicated but can never enter a dispute case;
    attempting either to open a dispute or to escalate one is `ERR_IDR_NOT_ELIGIBLE`."  PRD
    3.9 states the precondition it fails: "A `ComplianceOfficer` opens a dispute case on a
    claim that is `ADJUDICATED` (otherwise `ERR_INVALID_CLAIM_STATE`) whose payer contract has
    `idr_eligible` true (otherwise `ERR_IDR_NOT_ELIGIBLE`)".

    Design: Corner/validations/dispute_on_a_state_exempt_contract_returns_idr_not_eligible
    """
    context = adjudicated_claim(contract_builder=unprotected_contract)

    assert context["contract"]["idr_eligible"] is False
    assert context["claim"]["protection_variant"] == "UNPROTECTED"

    validate_error(
        api_client.create_dispute_case(context["claim_id"], {}, OFFICER),
        ApiErrorId.ERR_IDR_NOT_ELIGIBLE.value,
    )

    assert read_claim(context["claim_id"])["status"] == "ADJUDICATED"
    _, meta = validate_paginated(
        api_client.list_dispute_cases(context["claim_id"], OFFICER)
    )
    assert_total_count(meta, 0)


def test_basic_life_support_transport_cannot_carry_the_sickest_patient():
    """The acuity floor on transport level, with the same facility's critical-care unit
    accepted straight afterwards.

    PRD 3.8: "The memorandum's `level_of_care` must clear the acuity floor as well: acuity 4
    requires `ALS` or `CRITICAL_CARE`, and acuity 5 requires `CRITICAL_CARE`; anything less is
    `ERR_MOU_LEVEL_INSUFFICIENT`. Acuity levels 1 through 3 impose no level-of-care floor, so
    `BLS` transport is acceptable for them."  The refusal reserves nothing, because PRD 2.10
    counts reservations off live orders only: "`units_reserved` equals the number of transfer
    orders referencing that memorandum whose status is `REQUESTED` or `ACCEPTED`".

    Design: Corner/validations/bls_ambulance_mou_for_an_acuity_five_transfer_returns_mou_level_insufficient
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=5,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
        agreement_overrides={"capability_tier": 4},
        mou_overrides={"level_of_care": "BLS"},
    )
    critical_care_mou = create_ambulance_mou(
        context["facility_id"],
        ADMIN,
        carrier_name=SECOND_CARRIER,
        level_of_care="CRITICAL_CARE",
    )

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_MOU_LEVEL_INSUFFICIENT.value,
    )

    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)
    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"

    order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        critical_care_mou["id"],
        context["encounter_version"],
    )

    assert order["status"] == "REQUESTED"
    assert order["reserved_unit_count"] == 1
    assert_mou_unit_ledger(
        read_ambulance_mou(critical_care_mou["id"]), reserved=1, available=1
    )
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def test_a_transfer_requested_at_the_exact_instant_coverage_ends_is_outside_the_window():
    """The memorandum's window is half-open, so its closing instant is already too late.

    PRD 3.8: "The order's `requested_at`, stamped from the logical clock, must fall inside
    the memorandum's half-open coverage window — at or after `coverage_start_at` and strictly
    before `coverage_end_at`, so an instant exactly equal to `coverage_end_at` is outside —
    else `ERR_MOU_WINDOW_NOT_COVERING`."  The memorandum has aged out on its own, since PRD
    3.5 says "`status` is `ACTIVE` while the logical clock is before `coverage_end_at` and
    `EXPIRED` from that instant onward, re-evaluated on every read and validation", while the
    agreement's inclusive window still reads "`ACTIVE` while the clock date falls within the
    window inclusive of both endpoints".

    Design: Corner/validations/transfer_requested_exactly_at_coverage_end_returns_mou_window_not_covering
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
        mou_overrides={"coverage_end_at": MOU_COVERAGE_END_INSTANT},
    )
    set_clock(MOU_COVERAGE_END_INSTANT)

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_MOU_WINDOW_NOT_COVERING.value,
    )

    assert read_ambulance_mou(context["mou_id"])["status"] == "EXPIRED"
    agreement = validate_success(
        api_client.get_transfer_agreement(context["agreement_id"], ADMIN)
    )
    assert agreement["status"] == "ACTIVE"

    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"
    _, meta = validate_paginated(
        api_client.list_transfer_orders(
            PHYSICIAN, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert_total_count(meta, 0)


def test_a_memorandum_committing_no_units_can_never_carry_anybody():
    """Legal to record, and saturated from the instant it exists.

    PRD 3.5: "`saturation_state` is `SATURATED` at creation when `units_committed` is 0 and
    `AVAILABLE` otherwise" and "A memorandum committing zero units is legal to record and
    useless to transfer with: the availability check in Section 3.8 requires at least one
    available unit, and a commitment of 0 can never satisfy it."  PRD 3.8 states that check:
    "the memorandum must actually have a unit to give: `units_available` must be at least 1,
    else `ERR_AMBULANCE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/mou_with_no_committed_units_returns_ambulance_capacity_exceeded
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
        mou_overrides={"units_committed": 0},
    )

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_AMBULANCE_CAPACITY_EXCEEDED.value,
    )

    mou = read_ambulance_mou(context["mou_id"])
    assert mou["units_committed"] == 0
    assert_mou_unit_ledger(mou, reserved=0, available=0)

    assert_facility_unit_totals(
        read_facility(context["facility_id"]), committed=0, reserved=0
    )
    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"


def test_a_transfer_the_physician_will_not_certify_is_refused_outright():
    """The EMTALA certification is mandatory, and its absence reserves nothing.

    PRD 3.8: "That certification must be true; a false value is rejected with
    `ERR_TRANSFER_CERTIFICATION_REQUIRED`, because an uncertified transfer out of an
    emergency department is exactly the transfer regulators care most about."  The check sits
    after the state check and before the capability rules: "Certification is checked next."

    Design: Corner/validations/uncertified_transfer_order_returns_transfer_certification_required
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
                context["mou_id"],
                context["encounter_version"],
                clinical_benefit_certified=False,
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_TRANSFER_CERTIFICATION_REQUIRED.value,
    )

    assert read_encounter(context["encounter_id"])["clinical_state"] == "MSE_COMPLETE"
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)
    _, meta = validate_paginated(
        api_client.list_transfer_orders(
            PHYSICIAN, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert_total_count(meta, 0)


def test_a_basic_receiving_hospital_cannot_take_the_sickest_patient():
    """Acuity 5 demands tier 4, and the tier-2 destination is refused for it.

    PRD 3.8: "The agreement's `service_line` must equal the encounter's
    `presenting_service_line`, and its `capability_tier` must be at least the tier the acuity
    demands: acuity 1 and acuity 2 both require tier 1, acuity 3 requires tier 2, acuity 4
    requires tier 3, and acuity 5 requires tier 4. A wrong service line or an insufficient
    tier is `ERR_TRANSFER_CAPABILITY_INSUFFICIENT`."  The two agreements coexist because PRD
    3.5 says "Agreements for a different hospital or a different service line are not
    compared at all."

    Design: Corner/validations/agreement_tier_below_the_acuity_requirement_returns_transfer_capability_insufficient
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=5,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
        agreement_overrides={"capability_tier": 2},
    )
    comprehensive = create_transfer_agreement(
        context["facility_id"],
        ADMIN,
        destination_hospital_name=SECOND_HOSPITAL,
        service_line="CARDIAC",
        capability_tier=4,
    )

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_TRANSFER_CAPABILITY_INSUFFICIENT.value,
    )
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)

    order = create_transfer_order(
        context["encounter_id"],
        comprehensive["id"],
        context["mou_id"],
        context["encounter_version"],
    )

    assert order["transfer_agreement_id"] == comprehensive["id"]
    assert order["status"] == "REQUESTED"
    assert read_encounter(context["encounter_id"])["clinical_state"] == "TRANSFER_PENDING"


def test_an_unstable_patient_may_only_go_where_unstable_patients_are_accepted():
    """The destination's willingness is read alongside the transport's capability.

    PRD 3.8: "Then, for an encounter whose `stabilization_status` is `UNSTABLE`, the
    destination and the transport must both be capable of it: the agreement's
    `accepts_unstable` must be true and the memorandum's `level_of_care` must be
    `CRITICAL_CARE`, or the order is rejected with `ERR_STABILIZATION_REQUIRED`."  The
    stabilization finding itself never changes, because PRD 3.7 gives it exactly one writer:
    "Completing the screening moves the encounter `MSE_IN_PROGRESS → MSE_COMPLETE`, stamps
    `mse_completed_at`, and requires the physician to record a `stabilization_status` of
    either `STABLE` or `UNSTABLE`."

    Design: Corner/validations/unstable_patient_transfer_to_an_agreement_refusing_unstable_returns_stabilization_required
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=5,
        service_line="CARDIAC",
        stabilization_status="UNSTABLE",
        facility_overrides=NARROW_FACILITY,
        agreement_overrides={"capability_tier": 4, "accepts_unstable": False},
    )
    accepting = create_transfer_agreement(
        context["facility_id"],
        ADMIN,
        destination_hospital_name=SECOND_HOSPITAL,
        service_line="CARDIAC",
        capability_tier=4,
        accepts_unstable=True,
    )

    validate_error(
        api_client.create_transfer_order(
            context["encounter_id"],
            make_transfer_order_payload(
                context["agreement_id"], context["mou_id"], context["encounter_version"]
            ),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_STABILIZATION_REQUIRED.value,
    )

    refused = read_encounter(context["encounter_id"])
    assert refused["clinical_state"] == "MSE_COMPLETE"
    assert refused["stabilization_status"] == "UNSTABLE"
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)

    order = create_transfer_order(
        context["encounter_id"],
        accepting["id"],
        context["mou_id"],
        context["encounter_version"],
    )

    assert order["status"] == "REQUESTED"
    moved = read_encounter(context["encounter_id"])
    assert moved["clinical_state"] == "TRANSFER_PENDING"
    assert moved["stabilization_status"] == "UNSTABLE"


def test_a_fourth_facility_offer_has_no_round_left_to_be_made_in():
    """Three completed rounds close the negotiation loop to further offers.

    PRD 3.9: "A `ComplianceOfficer` submitting a facility offer requires the case to be in
    `OPEN_NEGOTIATION` and its `round_index` to be strictly below the three-round bound" and
    "a facility offer attempted when `round_index` has already reached 3 is
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."  The round counter is the payer's to move: "A
    `PayerRepresentative` posting a counteroffer requires the case to be in `OFFER_PENDING`;
    it writes `last_counteroffer_cents` and `last_offer_by_user_id`, increments `round_index`
    by 1, mirrors that value onto the claim's `negotiation_rounds_used`, and returns the case
    `OFFER_PENDING → OPEN_NEGOTIATION`."

    Design: Corner/validations/fourth_facility_offer_returns_negotiation_rounds_exhausted
    """
    context = exhausted_dispute_case(
        rounds=((240000, 200000), (235000, 205000), (230000, 210000))
    )

    validate_error(
        api_client.submit_offer(
            context["case_id"], make_offer_payload(228000), OFFICER
        ),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
    )

    case = _read_dispute_case(context["case_id"])
    assert case["status"] == "OPEN_NEGOTIATION"
    assert case["round_index"] == 3
    assert case["last_offer_cents"] == 230000
    assert case["last_counteroffer_cents"] == 210000

    claim = read_claim(context["claim_id"])
    assert claim["status"] == "NEGOTIATION"
    assert claim["negotiation_rounds_used"] == 3


def test_escalating_after_one_round_leaves_the_negotiation_unexhausted():
    """The bound cuts both ways: too few rounds is as fatal as too many.

    PRD 3.9: "The loop **must be exhausted** before independent dispute resolution may be
    initiated: escalation requires `round_index` to be at least 3, and an attempt with fewer
    completed rounds is rejected with `ERR_NEGOTIATION_NOT_EXHAUSTED`."  Nothing about the
    successful escalation happens, so neither does its ledger record: "the case moves
    `OPEN_NEGOTIATION → IDR_INITIATED`, the claim moves `NEGOTIATION → IDR_PENDING` with
    `negotiation_rounds_used` set to the case's `round_index`, and a ledger entry with
    `event_type` `IDR_INITIATED` is appended."

    Design: Corner/validations/idr_initiation_before_three_rounds_returns_negotiation_not_exhausted
    """
    context = adjudicated_claim()
    case = create_dispute_case(context["claim_id"], OFFICER)
    negotiate_rounds(case["id"], ((240000, 200000),))

    validate_error(
        api_client.initiate_idr(
            case["id"], {"certified_entity_name": "Certified IDRE Alpha"}, OFFICER
        ),
        ApiErrorId.ERR_NEGOTIATION_NOT_EXHAUSTED.value,
    )

    unescalated = _read_dispute_case(case["id"])
    assert unescalated["status"] == "OPEN_NEGOTIATION"
    assert unescalated["round_index"] == 1
    assert read_claim(context["claim_id"])["status"] == "NEGOTIATION"
    assert_no_ledger_entry(ledger_entries(context["facility_id"]), "IDR_INITIATED")


def test_the_payer_cannot_counter_an_offer_that_was_never_made():
    """A counteroffer needs an offer pending, and a fresh case has none.

    PRD 3.9: "A `PayerRepresentative` posting a counteroffer requires the case to be in
    `OFFER_PENDING`" and "An offer submitted in the wrong status is
    `ERR_INVALID_DISPUTE_STATE`".  The case is still exactly as PRD 3.9 created it: "The case
    is created with `status` `OPEN_NEGOTIATION`, its `claim_id` naming the out-of-network
    claim under dispute, `round_index` 0, `initiated_by_user_id` set to the acting officer,
    and `last_offer_cents`, `last_counteroffer_cents`, `last_offer_by_user_id`,
    `idr_award_cents` and `awarded_at` all null".

    Design: Corner/validations/counteroffer_while_no_offer_is_pending_returns_invalid_dispute_state
    """
    context = adjudicated_claim()
    case = create_dispute_case(context["claim_id"], OFFICER)
    assert case["status"] == "OPEN_NEGOTIATION"

    validate_error(
        api_client.submit_offer(case["id"], make_offer_payload(200000), PAYER),
        ApiErrorId.ERR_INVALID_DISPUTE_STATE.value,
    )

    untouched = _read_dispute_case(case["id"])
    assert untouched["status"] == "OPEN_NEGOTIATION"
    assert untouched["round_index"] == 0
    assert untouched["last_offer_cents"] is None
    assert untouched["last_counteroffer_cents"] is None
    assert read_claim(context["claim_id"])["negotiation_rounds_used"] == 0
