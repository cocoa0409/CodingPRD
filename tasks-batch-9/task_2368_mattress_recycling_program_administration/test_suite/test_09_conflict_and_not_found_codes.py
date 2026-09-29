"""Wrong-edge conflicts and reference resolution: each refused request names the code
belonging to the rule it broke, and nothing behind it moves."""

import pytest

from test_helpers import (
    AUDITOR_1_USER_ID,
    TEST_USERS,
    adjudicate_claim,
    attach_claim,
    complete_take_back,
    create_active_rate,
    create_ca_program,
    create_certified_recycler,
    create_enrolled_site,
    create_registrant,
    create_remittance,
    create_take_back,
    create_verified_commodity_output,
    create_wa_program,
    file_remittance,
    make_recycler_headers,
    make_registrant_headers,
    open_audit,
    pay_remittance,
    propose_rate,
    read_program,
    setup_delivered_order,
    setup_filed_remittance,
    setup_paid_remittance,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
AUDITOR_2 = TEST_USERS["auditor_2_headers"]

UNKNOWN_IDS = {
    "hauler": "00000000-0000-4000-8000-00000000aa01",
    "recycler": "00000000-0000-4000-8000-00000000aa02",
    "pickup_order": "00000000-0000-4000-8000-00000000aa03",
    "take_back": "00000000-0000-4000-8000-00000000aa04",
    "schedule": "00000000-0000-4000-8000-00000000aa05",
    "registrant": "00000000-0000-4000-8000-00000000aa06",
    "remittance": "00000000-0000-4000-8000-00000000aa07",
    "volume_report": "00000000-0000-4000-8000-00000000aa08",
    "commodity_record": "00000000-0000-4000-8000-00000000aa09",
}


def claim_under_audit(api):
    """A California filing of 500 mattress units with one 50-unit documented claim,
    paid at 495,000 cents and opened for audit."""
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    claim = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="OUT_OF_STATE_SHIPMENT",
        unit_class="MATTRESS",
        units=50,
        documentation_reference="BOL-2026-0630",
    )
    file_remittance(api, remittance["id"], registrant["id"])
    pay_remittance(api, remittance["id"], registrant["id"], 495_000)
    open_audit(api, remittance["id"])
    return {
        "program_id": program["id"],
        "registrant_id": registrant["id"],
        "remittance_id": remittance["id"],
        "claim_id": claim["id"],
    }


def test_a_claim_cannot_be_back_fitted_to_a_stamped_self_assessment(api):
    """PRD §3.3: "While a remittance is in `DRAFT` the registrant may attach exemption
    claims to it, as described in §3.4, and may then file it. Filing is only legal
    from `DRAFT`; attempting to file — or to attach a claim — to a remittance in any
    other status is rejected with `ERR_REMITTANCE_NOT_DRAFT`."

    Design: Corner/errors/err_remittance_not_draft_on_a_claim_attached_after_filing
    """
    chain = setup_filed_remittance(api)

    late_claim = api.create_exemption_claim(
        chain["remittance_id"],
        {"claim_type": "EXEMPT_SALE", "unit_class": "MATTRESS", "units": 10},
        chain["registrant_headers"],
    )
    second_file = api.file_sales_remittance(
        chain["remittance_id"], chain["registrant_headers"]
    )

    validate_error(late_claim, "ERR_REMITTANCE_NOT_DRAFT", 409)
    validate_error(second_file, "ERR_REMITTANCE_NOT_DRAFT", 409)
    stored = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert stored["status"] == "FILED"
    assert stored["fee_self_assessed_cents"] == 550_000
    _, meta = validate_paginated(
        api.list_exemption_claims(chain["remittance_id"], chain["registrant_headers"])
    )
    assert meta["total_count"] == 0


def test_the_audit_verbs_are_refused_on_a_paid_but_unaudited_filing(api):
    """PRD §3.4: "Requesting an amendment moves `UNDER_AUDIT → AMENDMENT_REQUIRED`,
    carries a `note` explaining what is wanted, and records the requesting auditor as
    `amendment_requested_by_user_id`, overwriting any previous value. It is legal only
    from `UNDER_AUDIT` — otherwise `ERR_REMITTANCE_NOT_UNDER_AUDIT` — and only while
    `amendment_round` is less than 2; a third request is refused with
    `ERR_AMENDMENT_LIMIT_EXCEEDED`."

    Design: Corner/errors/err_remittance_not_under_audit_on_request_amendment_while_paid
    """
    chain = setup_paid_remittance(api)

    amendment_request = api.request_remittance_amendment(
        chain["remittance_id"], {"note": "Units look understated"}, AUDITOR
    )
    closure = api.close_remittance_audit(chain["remittance_id"], AUDITOR)

    validate_error(amendment_request, "ERR_REMITTANCE_NOT_UNDER_AUDIT", 409)
    validate_error(closure, "ERR_REMITTANCE_NOT_UNDER_AUDIT", 409)
    stored = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert stored["status"] == "PAID"
    assert stored["amendment_round"] == 0
    assert stored["fee_reconciled_cents"] is None


def test_an_adjudicated_claim_cannot_be_decided_a_second_time(api):
    """PRD §3.4: "A claim may only be adjudicated while it is `PENDING` and while its
    parent remittance is `UNDER_AUDIT`; otherwise the request is refused with
    `ERR_CLAIM_ALREADY_ADJUDICATED`."

    Design: Corner/errors/err_claim_already_adjudicated_on_a_second_decision
    """
    chain = claim_under_audit(api)
    adjudicate_claim(api, chain["claim_id"], "SUBSTANTIATE")

    response = api.adjudicate_exemption_claim(
        chain["claim_id"],
        {"decision": "DISALLOW", "disallow_reason": "MISSING_DOCUMENTATION"},
        AUDITOR,
    )

    validate_error(response, "ERR_CLAIM_ALREADY_ADJUDICATED", 409)
    claims, _ = validate_paginated(
        api.list_exemption_claims(chain["remittance_id"], AUDITOR)
    )
    stored = next(row for row in claims if row["id"] == chain["claim_id"])
    assert stored["status"] == "SUBSTANTIATED"
    assert stored["disallow_reason"] is None


def test_enrolling_or_reinstating_an_enrolled_site_is_the_wrong_edge(api):
    """PRD §3.5: "Each of these three transitions insists on the right starting status
    — `APPLIED` to enroll, `ENROLLED` to suspend, `SUSPENDED` to reinstate — and
    rejects a mismatch with `ERR_SITE_ENROLLMENT_STATE_INVALID`."

    Design: Corner/errors/err_site_enrollment_state_invalid_on_a_second_enroll
    """
    program = create_ca_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )

    second_enroll = api.enroll_collection_site(site["id"], ADMIN)
    reinstate = api.reinstate_collection_site(site["id"], ADMIN)

    validate_error(second_enroll, "ERR_SITE_ENROLLMENT_STATE_INVALID", 409)
    validate_error(reinstate, "ERR_SITE_ENROLLMENT_STATE_INVALID", 409)
    stored = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored["enrollment_status"] == "ENROLLED"


def test_settlement_waits_for_the_inspection_that_can_only_happen_once(api):
    """PRD §3.7: "Finalizing moves `fulfillment_status` `DELIVERED → CLOSED` and
    `settlement_status` to `FINALIZED`, and it requires all three of: the order in
    `DELIVERED`, its `settlement_status` in either `ESTIMATED` or `DISPUTED`, and an
    inspection already recorded against it. A wrong fulfillment status is
    `ERR_PICKUP_STATE_INVALID`; a settlement status outside those two values, or a
    missing inspection, is `ERR_SETTLEMENT_NOT_READY`."

    Design: Corner/errors/err_load_already_inspected_and_err_settlement_not_ready
    """
    chain = setup_delivered_order(api, units_delivered=240)

    premature = api.finalize_settlement(chain["order_id"], ADMIN)
    validate_error(premature, "ERR_SETTLEMENT_NOT_READY", 409)
    assert (
        validate_success(api.get_pickup_order(chain["order_id"], ADMIN))["settlement_status"]
        == "ESTIMATED"
    )

    inspection = validate_success(
        api.create_load_inspection(
            chain["order_id"],
            {"contaminated_unit_count": 0, "infestation_finding": "NONE"},
            chain["recycler_headers"],
        ),
        201,
    )
    second = api.create_load_inspection(
        chain["order_id"],
        {"contaminated_unit_count": 5, "infestation_finding": "NONE"},
        chain["recycler_headers"],
    )

    assert inspection["disposition"] == "PARTIAL_ACCEPT"
    assert inspection["units_accepted"] == 240
    validate_error(second, "ERR_LOAD_ALREADY_INSPECTED", 409)
    inspections, meta = validate_paginated(
        api.list_load_inspections(chain["order_id"], chain["recycler_headers"])
    )
    assert meta["total_count"] == 1
    assert inspections[0]["id"] == inspection["id"]
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_recycled_count"] == 240
    assert site["contamination_strike_count"] == 0


def test_a_certified_facility_can_be_neither_certified_nor_recertified(api):
    """PRD §3.7: "All three transitions insist on the correct starting status —
    `PROVISIONAL` to certify, `CERTIFIED` to suspend, `SUSPENDED` to recertify —
    rejecting a mismatch with `ERR_RECYCLER_CERT_STATE_INVALID`."

    Design: Corner/errors/err_recycler_cert_state_invalid_on_a_second_certify
    """
    program = create_wa_program(api)
    recycler = create_certified_recycler(api, program["id"])

    second_certify = api.certify_recycler(recycler["id"], ADMIN)
    recertify = api.recertify_recycler(recycler["id"], ADMIN)

    validate_error(second_certify, "ERR_RECYCLER_CERT_STATE_INVALID", 409)
    validate_error(recertify, "ERR_RECYCLER_CERT_STATE_INVALID", 409)
    stored = validate_success(api.get_recycler(recycler["id"], ADMIN))
    assert stored["certification_status"] == "CERTIFIED"
    assert stored["diversion_rate_pct"] == pytest.approx(0.00)


def test_a_met_obligation_can_be_neither_waived_nor_reported_again(api):
    """PRD §3.8: "A delivery leaves `SCHEDULED` in exactly one of three ways, and
    `OBLIGATION_MET`, `OBLIGATION_BREACHED` and `WAIVED` are all terminal. Any of the
    three requires the delivery to still be in `SCHEDULED`, refusing otherwise with
    `ERR_TAKEBACK_NOT_SCHEDULED`."

    Design: Corner/errors/err_takeback_not_scheduled_on_waive_after_completion
    """
    program = create_ca_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)
    registrant_headers = make_registrant_headers(registrant["id"])
    delivery = create_take_back(
        api,
        registrant["id"],
        site["id"],
        delivery_reference="DEL-4001",
        units_delivered_new=10,
        units_takeback_offered=10,
    )
    complete_take_back(api, delivery["id"], registrant["id"], 10)

    waive = api.waive_takeback(
        delivery["id"], {"waiver_reference": "WVR-9"}, registrant_headers
    )
    second_report = api.complete_takeback(
        delivery["id"], {"units_takeback_collected": 0}, registrant_headers
    )

    validate_error(waive, "ERR_TAKEBACK_NOT_SCHEDULED", 409)
    validate_error(second_report, "ERR_TAKEBACK_NOT_SCHEDULED", 409)
    stored = validate_success(api.get_take_back_delivery(delivery["id"], registrant_headers))
    assert stored["status"] == "OBLIGATION_MET"
    assert stored["units_takeback_collected"] == 10
    assert stored["waiver_reference"] is None
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 10
    assert stored_site["units_reported_total"] == 10


def test_a_verified_record_is_not_verified_twice_into_the_weight_total(api):
    """PRD §3.7: "A `ProgramAuditor` verifies a record, moving `SUBMITTED → VERIFIED`
    and recording `verified_by_user_id`; verification is legal only from `SUBMITTED`,
    otherwise `ERR_COMMODITY_RECORD_NOT_SUBMITTED`."

    Design: Corner/errors/err_commodity_record_not_submitted_on_a_double_verify
    """
    program = create_wa_program(api)
    recycler = create_certified_recycler(api, program["id"])
    record = create_verified_commodity_output(
        api,
        recycler["id"],
        commodity="STEEL",
        output_weight_kg=1200.5,
        source_period_month="2026-07",
    )

    response = api.verify_commodity_output_record(record["id"], AUDITOR_2)

    validate_error(response, "ERR_COMMODITY_RECORD_NOT_SUBMITTED", 409)
    records, _ = validate_paginated(
        api.list_commodity_output_records(
            recycler["id"], make_recycler_headers(recycler["id"])
        )
    )
    stored = next(row for row in records if row["id"] == record["id"])
    assert stored["record_status"] == "VERIFIED"
    assert stored["verified_by_user_id"] == AUDITOR_1_USER_ID
    stored_recycler = validate_success(api.get_recycler(recycler["id"], ADMIN))
    assert stored_recycler["verified_output_weight_kg"] == pytest.approx(1200.5)


def test_a_schedule_that_was_never_approved_cannot_be_activated(api):
    """PRD §3.2: "Activation moves a schedule `APPROVED → ACTIVE`. It is only legal
    from `APPROVED` — otherwise `ERR_RATE_SCHEDULE_NOT_APPROVABLE` — and only once
    the logical clock has reached or passed the schedule's `effective_from`;
    activating early is refused with `ERR_RATE_NOT_YET_EFFECTIVE`."

    Design: Corner/errors/err_rate_schedule_not_approvable_on_activating_a_proposed_schedule
    """
    program = create_ca_program(api)
    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )

    response = api.activate_fee_rate_schedule(schedule["id"], ADMIN)

    validate_error(response, "ERR_RATE_SCHEDULE_NOT_APPROVABLE", 409)
    stored = validate_success(api.get_fee_rate_schedule(schedule["id"], ADMIN))
    assert stored["status"] == "PROPOSED"
    assert stored["approved_by_user_id"] is None


def test_every_collection_answers_an_unknown_id_with_its_own_code(api):
    """PRD §2.5: "The per-entity 404 codes are `ERR_STATE_PROGRAM_NOT_FOUND`,
    `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_REGISTRANT_NOT_FOUND`,
    `ERR_REMITTANCE_NOT_FOUND`, `ERR_EXEMPTION_CLAIM_NOT_FOUND`,
    `ERR_COLLECTION_SITE_NOT_FOUND`, `ERR_VOLUME_REPORT_NOT_FOUND`,
    `ERR_HAULER_NOT_FOUND`, `ERR_RECYCLER_NOT_FOUND`, `ERR_PICKUP_ORDER_NOT_FOUND`,
    `ERR_COMMODITY_RECORD_NOT_FOUND` and `ERR_TAKE_BACK_DELIVERY_NOT_FOUND`."

    Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
    """
    program = create_ca_program(api)

    validate_error(api.get_hauler(UNKNOWN_IDS["hauler"], ADMIN), "ERR_HAULER_NOT_FOUND", 404)
    validate_error(
        api.get_recycler(UNKNOWN_IDS["recycler"], ADMIN), "ERR_RECYCLER_NOT_FOUND", 404
    )
    validate_error(
        api.get_pickup_order(UNKNOWN_IDS["pickup_order"], ADMIN),
        "ERR_PICKUP_ORDER_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_take_back_delivery(UNKNOWN_IDS["take_back"], ADMIN),
        "ERR_TAKE_BACK_DELIVERY_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_fee_rate_schedule(UNKNOWN_IDS["schedule"], ADMIN),
        "ERR_RATE_SCHEDULE_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_registrant(UNKNOWN_IDS["registrant"], ADMIN), "ERR_REGISTRANT_NOT_FOUND", 404
    )
    validate_error(
        api.get_sales_remittance(UNKNOWN_IDS["remittance"], ADMIN),
        "ERR_REMITTANCE_NOT_FOUND",
        404,
    )
    validate_error(
        api.accept_volume_report(UNKNOWN_IDS["volume_report"], ADMIN),
        "ERR_VOLUME_REPORT_NOT_FOUND",
        404,
    )
    validate_error(
        api.verify_commodity_output_record(UNKNOWN_IDS["commodity_record"], AUDITOR),
        "ERR_COMMODITY_RECORD_NOT_FOUND",
        404,
    )
    assert read_program(api, program["id"])["version"] == 1
