"""Declared initial states, refused from-states, absorbing terminal states and disposition guards."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_cents,
    assert_cold_chain_excursion,
    assert_compliance_violation,
    assert_instant,
    assert_shrink_event,
    assert_temperature,
    assert_weight,
)
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_COLD_USER_ID,
    OFFICER_COOL_USER_ID,
    OFFICER_LEDGER_USER_ID,
    OFFICER_SAMPLING_USER_ID,
    OFFICER_SIMP_USER_ID,
    make_compliance_officer_headers,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
    make_supplier_rep_headers,
)


def _one_of_every_entity(api) -> dict:
    """One freshly created row of every entity that declares an initial state."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    document = fixtures.create_simp_document(
        api,
        supplier_id,
        lot["id"],
        harvesting_vessel_name="Northern Dawn",
        chain_of_custody_ref="COC-11001",
    )
    certification = fixtures.file_certification(api, counter_id, supplier_id, env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    item = fixtures.draft_ad_item(api, counter_id, lot["id"], ad_end_at="2026-08-01T18:00:00Z")
    sample = fixtures.draw_sample(api, lot["id"])
    event = fixtures.create_shrink_event(
        api, counter_id, lot["id"], shrink_weight_kg=1.000, conversion_requested_kg=0.000
    )
    env.update(
        {
            "lot": lot,
            "document": document,
            "certification": certification,
            "label": label,
            "ad_item": item,
            "sample": sample,
            "shrink_event": event,
        }
    )
    return env


def _five_machines_asked_for_an_illegal_move(api) -> dict:
    """A cased lot, a withdrawn label, a DRAFT advertisement and a DRAFT sample."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    fixtures.withdraw_case_label(api, counter_id, label["id"], "MANUAL")
    item = fixtures.draft_ad_item(api, counter_id, lot["id"], ad_end_at="2026-08-01T18:00:00Z")
    sample = fixtures.draw_sample(api, lot["id"])
    env.update({"lot": lot, "label": label, "ad_item": item, "sample": sample})
    return env


def _refused_moves_out_of_five_machines(api, env: dict) -> dict:
    """Fire one illegal transition per machine and return the five refusal codes."""
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)

    lot_error = validate_error(
        api.case_lot(env["lot"]["id"], {"case_slot": 2}, manager),
        ApiErrorId.ERR_LOT_STATE_INVALID.value,
        expected_status=409,
    )
    label_dimension_error = validate_error(
        api.relabel_lot(
            env["lot"]["id"],
            {"corrected_species_id": env["cod"]["id"], "corrected_market_name": "Cod"},
            manager,
        ),
        ApiErrorId.ERR_LABEL_STATE_INVALID.value,
        expected_status=409,
    )
    case_label_error = validate_error(
        api.withdraw_case_label(env["label"]["id"], {"reason": "MANUAL"}, manager),
        ApiErrorId.ERR_CASE_LABEL_STATE_INVALID.value,
        expected_status=409,
    )
    ad_error = validate_error(
        api.publish_ad_item(env["ad_item"]["id"], {}, make_merchandising_lead_headers()),
        ApiErrorId.ERR_AD_ITEM_STATE_INVALID.value,
        expected_status=409,
    )
    sample_error = validate_error(
        api.record_sample_result(
            env["sample"]["id"],
            {"observed_species_id": env["cod"]["id"]},
            make_compliance_officer_headers(OFFICER_SAMPLING_USER_ID),
        ),
        ApiErrorId.ERR_SAMPLE_STATE_INVALID.value,
        expected_status=409,
    )
    return {
        "lot": lot_error["error_id"],
        "label_dimension": label_dimension_error["error_id"],
        "case_label": case_label_error["error_id"],
        "ad_item": ad_error["error_id"],
        "sample": sample_error["error_id"],
    }


def _five_machines_parked_in_terminal_states(api) -> dict:
    """An ACCEPTED document, a REVOKED certificate, a CLOSED ad, a REVERSED shrink and an EXPUNGED finding."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.publish_case_label(api, counter_id, lot["id"])

    document = fixtures.create_simp_document(
        api,
        supplier_id,
        lot["id"],
        harvesting_vessel_name="Northern Dawn",
        chain_of_custody_ref="COC-11001",
    )
    fixtures.submit_simp_document(api, supplier_id, document["id"])
    fixtures.review_simp_document(
        api, document["id"], "ACCEPT", "documentation complete", officer_id=OFFICER_SIMP_USER_ID
    )

    certification = fixtures.file_certification(api, counter_id, supplier_id, env["cod"]["id"])
    fixtures.review_certification(
        api,
        certification["id"],
        "REJECT",
        "certificate scope does not cover this fishery",
        officer_id=OFFICER_CLAIM_USER_ID,
    )

    item = fixtures.draft_ad_item(api, counter_id, lot["id"], ad_end_at="2026-08-01T10:00:00Z")
    fixtures.clear_ad_cool(api, item["id"], officer_id=OFFICER_COOL_USER_ID)
    fixtures.clear_ad_claim(api, item["id"], officer_id=OFFICER_CLAIM_USER_ID)
    fixtures.publish_ad_item(api, item["id"])
    fixtures.set_clock(api, "2026-08-01T11:00:00Z")
    closed = validate_success(
        api.close_ad_item(item["id"], {}, make_merchandising_lead_headers()), expected_status=200
    )

    event = fixtures.create_shrink_event(
        api, counter_id, lot["id"], shrink_weight_kg=2.000, conversion_requested_kg=0.000
    )
    fixtures.post_shrink_event(api, counter_id, event["id"])
    fixtures.reverse_shrink_event(
        api,
        event["id"],
        "shrink was written against the wrong lot",
        officer_id=OFFICER_LEDGER_USER_ID,
    )

    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    excursion = fixtures.open_excursion_on_slot(api, counter_id, 1, "2026-08-01T13:00:00Z", 6.0)
    fixtures.resolve_excursion(
        api,
        excursion["id"],
        "DISPOSE",
        "product condemned at the case",
        officer_id=OFFICER_COLD_USER_ID,
    )
    violation = fixtures.only_violation(api, counter_id, {"category": "COLD_CHAIN"})
    fixtures.expunge_violation(
        api,
        violation["id"],
        "probe was later found out of calibration",
        officer_id=OFFICER_COLD_USER_ID,
    )

    env.update(
        {
            "lot": lot,
            "document": document,
            "certification": certification,
            "ad_item": closed,
            "shrink_event": event,
            "violation": violation,
        }
    )
    return env


def _refused_moves_out_of_five_terminal_states(api, env: dict) -> dict:
    """Ask each absorbing state for one more transition and return the five refusal codes."""
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)

    simp_error = validate_error(
        api.submit_simp_document(
            env["document"]["id"], {}, make_supplier_rep_headers(env["supplier"]["id"])
        ),
        ApiErrorId.ERR_SIMP_STATE_INVALID.value,
        expected_status=409,
    )
    certification_error = validate_error(
        api.enforce_certification(
            env["certification"]["id"],
            {"decision": "REVOKE", "note": "program bulletin"},
            make_compliance_officer_headers(OFFICER_CLAIM_USER_ID),
        ),
        ApiErrorId.ERR_CERTIFICATION_STATE_INVALID.value,
        expected_status=409,
    )
    ad_error = validate_error(
        api.retract_ad_item(
            env["ad_item"]["id"], {"reason": "MANUAL"}, make_merchandising_lead_headers()
        ),
        ApiErrorId.ERR_AD_ITEM_STATE_INVALID.value,
        expected_status=409,
    )
    shrink_error = validate_error(
        api.post_shrink_event(env["shrink_event"]["id"], {}, manager),
        ApiErrorId.ERR_SHRINK_STATE_INVALID.value,
        expected_status=409,
    )
    violation_error = validate_error(
        api.cure_violation(
            env["violation"]["id"], {"cure_note": "retraining completed"}, manager
        ),
        ApiErrorId.ERR_VIOLATION_STATE_INVALID.value,
        expected_status=409,
    )
    return {
        "document": simp_error["error_id"],
        "certification": certification_error["error_id"],
        "ad_item": ad_error["error_id"],
        "shrink_event": shrink_error["error_id"],
        "violation": violation_error["error_id"],
    }


def _critical_excursion_on_slot_two(api) -> dict:
    """A four-hour exposure on slot 2, which lands the excursion in CRITICAL."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 2)
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    fixtures.submit_reading(api, counter_id, 2, "2026-08-01T09:00:00Z", 5.0)
    fixtures.submit_reading(api, counter_id, 2, "2026-08-01T13:00:00Z", 4.9)
    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 2, "status": "OPEN"})
    assert len(excursions) == 1, f"expected exactly one open excursion, got {len(excursions)}"
    env.update({"lot": lot, "excursion": excursions[0]})
    return env


def _disposed_slot_one_lot(api) -> dict:
    """A 10.000 kg lot at 1700 cents per kilogram, disposed of after a single 6.0 C breach."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    excursion = fixtures.open_excursion_on_slot(api, counter_id, 1, "2026-08-01T13:00:00Z", 6.0)
    resolved = fixtures.resolve_excursion(
        api, excursion["id"], "DISPOSE", "ice bed failed overnight", officer_id=OFFICER_COLD_USER_ID
    )
    env.update({"lot": lot, "excursion": excursion, "resolved": resolved})
    return env


def _submitted_snapper_document(api) -> dict:
    """A covered-species lot whose import-monitoring record has been submitted once."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    snapper = fixtures.register_red_snapper(api)
    lot = fixtures.receive_snapper_lot(api, counter_id, supplier_id, snapper["id"])
    document = fixtures.create_simp_document(api, supplier_id, lot["id"])
    submitted = fixtures.submit_simp_document(api, supplier_id, document["id"])
    env.update({"snapper": snapper, "lot": lot, "document": document, "submitted": submitted})
    return env


def test_01_a_new_lot_document_certificate_advertisement_and_sample_start_where_declared(api):
    """PRD §3.8: "The sample is created with `status` `DRAFT`, its `cycle_index` stamped from
    the owning counter's current `verification_cycle_index`, and `observed_species_id`,
    `lab_reference`, `dispute_reason` and `result_recorded_at` all null with `retest_count` 0."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    env = _one_of_every_entity(api)

    lot = env["lot"]
    assert lot["intake_status"] == "RECEIVED"
    assert lot["label_status"] == "UNVERIFIED"
    assert lot["chargeback_status"] == "NONE"

    assert env["document"]["status"] == "DRAFT"
    assert env["document"]["amendment_count"] == 0
    assert env["certification"]["status"] == "PENDING_REVIEW"

    item = env["ad_item"]
    assert item["status"] == "DRAFT"
    assert item["cool_review_status"] == "COOL_PENDING"
    assert item["claim_review_status"] == "CLAIM_PENDING"

    sample = env["sample"]
    assert sample["status"] == "DRAFT"
    assert sample["retest_count"] == 0
    assert sample["cycle_index"] == 0
    assert sample["observed_species_id"] is None

    assert fixtures.read_counter(api, env["counter"]["id"])["posture"] == "OPEN"


def test_02_a_label_is_born_published_and_a_shrink_event_is_born_valued(api):
    """PRD §3.4: "A published label starts with `status` `PUBLISHED`, `published_at` stamped
    from the logical clock, and `withdraw_reason` and `withdrawn_at` both null."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    env = _one_of_every_entity(api)

    label = env["label"]
    assert label["status"] == "PUBLISHED"
    assert_instant(label["published_at"], "2026-08-01T08:00:00Z")
    assert label["withdraw_reason"] is None
    assert label["withdrawn_at"] is None

    event = env["shrink_event"]
    assert_shrink_event(event)
    assert event["status"] == "VALUED"
    assert_weight(event["approved_conversion_kg"], 0.000)
    assert_weight(event["allowance_kg"], 0.000)
    assert_weight(event["cook_yield_kg"], 0.000)
    assert_cents(event["final_value_cents"], 0)
    assert_cents(event["recovery_credit_cents"], 0)
    assert event["posted_at"] is None
    assert event["reversed_at"] is None
    assert event["reversal_note"] is None


def test_03_five_machines_each_refuse_with_their_own_dimension_code(api):
    """PRD §3.8: "It requires the lot's `label_status` to be `MISMATCHED`, failing which the
    request is rejected with `ERR_LABEL_STATE_INVALID`."

    Design: Corner/state_machines/invalid_from_state_sweep_across_five_machines
    """
    env = _five_machines_asked_for_an_illegal_move(api)

    errors = _refused_moves_out_of_five_machines(api, env)

    assert errors["lot"] == ApiErrorId.ERR_LOT_STATE_INVALID.value
    assert errors["label_dimension"] == ApiErrorId.ERR_LABEL_STATE_INVALID.value
    assert errors["case_label"] == ApiErrorId.ERR_CASE_LABEL_STATE_INVALID.value
    assert errors["ad_item"] == ApiErrorId.ERR_AD_ITEM_STATE_INVALID.value
    assert errors["sample"] == ApiErrorId.ERR_SAMPLE_STATE_INVALID.value
    assert len(set(errors.values())) == 5, f"expected five distinct codes, got {errors}"


def test_04_the_five_refusals_leave_every_machine_exactly_where_it_stood(api):
    """PRD §3.4: "`WITHDRAWN` is terminal — a second withdrawal attempt on the same label fails
    with `ERR_CASE_LABEL_STATE_INVALID`."

    Design: Corner/state_machines/invalid_from_state_sweep_across_five_machines
    """
    env = _five_machines_asked_for_an_illegal_move(api)
    counter_id = env["counter"]["id"]
    _refused_moves_out_of_five_machines(api, env)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["case_slot"] == 1
    assert lot["intake_status"] == "CASED"
    assert lot["label_status"] == "SAMPLED"

    label = fixtures.read_case_label(api, counter_id, env["label"]["id"])
    assert label["status"] == "WITHDRAWN"
    assert label["withdraw_reason"] == "MANUAL"

    assert fixtures.read_ad_item(api, env["ad_item"]["id"])["status"] == "DRAFT"

    sample = fixtures.read_sample(api, env["sample"]["id"])
    assert sample["status"] == "DRAFT"
    assert sample["observed_species_id"] is None


def test_05_each_terminal_state_answers_with_its_own_machines_code(api):
    """PRD §3.2: "`ACCEPTED` is the terminal state of an import-monitoring record; `DEFICIENT`
    is not, because the amendment loop exists precisely so a dealer can correct and resubmit."

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    env = _five_machines_parked_in_terminal_states(api)

    errors = _refused_moves_out_of_five_terminal_states(api, env)

    assert errors["document"] == ApiErrorId.ERR_SIMP_STATE_INVALID.value
    assert errors["certification"] == ApiErrorId.ERR_CERTIFICATION_STATE_INVALID.value
    assert errors["ad_item"] == ApiErrorId.ERR_AD_ITEM_STATE_INVALID.value
    assert errors["shrink_event"] == ApiErrorId.ERR_SHRINK_STATE_INVALID.value
    assert errors["violation"] == ApiErrorId.ERR_VIOLATION_STATE_INVALID.value


def test_06_the_refused_transitions_write_nothing_onto_the_absorbing_rows(api):
    """PRD §3.9: "A `ComplianceOfficer` expunges a finding by submitting an `expunge_note`,
    which moves it from `OPEN` or from `CURED` to the terminal `EXPUNGED`, stamps `expunged_at`
    from the logical clock, and re-derives the posture with that finding contributing nothing."

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    env = _five_machines_parked_in_terminal_states(api)
    counter_id = env["counter"]["id"]
    _refused_moves_out_of_five_terminal_states(api, env)

    document = fixtures.read_simp_document(api, env["supplier"]["id"], env["document"]["id"])
    assert document["status"] == "ACCEPTED"
    assert document["amendment_count"] == 0

    certification = fixtures.read_certification(
        api, env["supplier"]["id"], env["certification"]["id"]
    )
    assert certification["status"] == "REVOKED"

    item = fixtures.read_ad_item(api, env["ad_item"]["id"])
    assert item["status"] == "CLOSED"
    assert item["retract_reason"] is None

    event = fixtures.read_shrink_event(api, counter_id, env["shrink_event"]["id"])
    assert event["status"] == "REVERSED"

    violation = fixtures.only_violation(api, counter_id, {"category": "COLD_CHAIN"})
    assert violation["status"] == "EXPUNGED"
    assert violation["cure_note"] is None

    counter = fixtures.read_counter(api, counter_id)
    assert counter["violation_points"] == 0
    assert counter["posture"] == "OPEN"


def test_07_a_critical_excursion_may_not_be_released_back_to_sale(api):
    """PRD §3.7: "A `resolution` of `RELEASE` requires the excursion's `status` to be `OPEN` and
    its `severity` to be `MINOR` or `MAJOR` — a `CRITICAL` excursion may not be released, and
    the attempt fails with `ERR_EXCURSION_STATE_INVALID`."

    Design: Corner/state_machines/excursion_release_requires_non_critical_severity
    """
    env = _critical_excursion_on_slot_two(api)
    counter_id = env["counter"]["id"]
    excursion = env["excursion"]

    assert_cold_chain_excursion(excursion)
    assert excursion["severity"] == "CRITICAL"
    assert excursion["exposure_minutes"] == 240
    assert_temperature(excursion["peak_temperature_c"], 5.0)

    response = api.resolve_excursion(
        excursion["id"],
        {"resolution": "RELEASE", "note": "counter asked to return the product to sale"},
        make_compliance_officer_headers(OFFICER_COLD_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_EXCURSION_STATE_INVALID.value, expected_status=409)

    assert fixtures.read_excursion(api, counter_id, excursion["id"])["status"] == "OPEN"
    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["intake_status"] == "HELD"


def test_08_disposal_is_the_only_route_left_for_that_same_excursion(api):
    """PRD §3.7: "A `resolution` of `DISPOSE` requires only that the excursion's `status` be
    `OPEN` and is therefore the only route available for a `CRITICAL` excursion."

    Design: Corner/state_machines/excursion_release_requires_non_critical_severity
    """
    env = _critical_excursion_on_slot_two(api)
    counter_id = env["counter"]["id"]
    excursion = env["excursion"]
    validate_error(
        api.resolve_excursion(
            excursion["id"],
            {"resolution": "RELEASE", "note": "counter asked to return the product to sale"},
            make_compliance_officer_headers(OFFICER_COLD_USER_ID),
        ),
        ApiErrorId.ERR_EXCURSION_STATE_INVALID.value,
        expected_status=409,
    )

    response = api.resolve_excursion(
        excursion["id"],
        {"resolution": "DISPOSE", "note": "product condemned after a four-hour exposure"},
        make_compliance_officer_headers(OFFICER_COLD_USER_ID),
    )
    resolved = validate_success(response, expected_status=200)

    assert resolved["status"] == "RESOLVED_DISPOSED"
    assert resolved["resolution"] == "DISPOSE"

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["intake_status"] == "DISPOSED"
    assert lot["case_slot"] is None
    assert_instant(lot["vacated_at"], "2026-08-01T14:00:00Z")


def test_09_disposal_writes_the_disposal_factor_shrink_and_the_cold_chain_finding(api):
    """PRD §3.7: "Disposal moves the excursion to `RESOLVED_DISPOSED` and, for every lot on the
    counter in that slot whose `intake_status` is `HELD`, moves that lot to `DISPOSED`, stamps
    its `vacated_at` from the logical clock, clears its `case_slot` to null, creates a
    `ShrinkEvent` against it with `reason` `COLD_CHAIN_DISPOSAL`, `shrink_weight_kg` equal to
    that lot's `remaining_weight_kg`, `conversion_requested_kg` 0.000 and `status` `VALUED`, and
    raises a `ComplianceViolation` with `category` `COLD_CHAIN` and `points` 3."

    Design: Corner/state_machines/excursion_dispose_writes_shrink_violation_and_reopens_posture
    """
    env = _disposed_slot_one_lot(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]

    lot = fixtures.read_lot(api, counter_id, lot_id)
    assert lot["intake_status"] == "DISPOSED"
    assert lot["case_slot"] is None
    assert_instant(lot["vacated_at"], "2026-08-01T14:00:00Z")
    assert_weight(lot["remaining_weight_kg"], 10.000)

    events = fixtures.list_shrink_events(
        api, counter_id, {"lot_id": lot_id, "reason": "COLD_CHAIN_DISPOSAL"}
    )
    assert len(events) == 1, f"expected exactly one disposal shrink event, got {len(events)}"
    event = events[0]
    assert_shrink_event(event)
    assert event["status"] == "VALUED"
    assert_weight(event["shrink_weight_kg"], 10.000)
    assert_weight(event["conversion_requested_kg"], 0.000)
    assert_cents(event["provisional_value_cents"], 18650)
    assert event["provisional_value_cents"] != 15850

    violation = fixtures.only_violation(api, counter_id, {"category": "COLD_CHAIN"})
    assert_compliance_violation(violation)
    assert violation["points"] == 3
    assert violation["status"] == "OPEN"
    assert violation["lot_id"] == lot_id


def test_10_the_disposition_clears_the_open_excursion_and_reopens_the_counter(api):
    """PRD §3.7: "Either disposition decreases the counter's `open_excursion_count` by one and
    re-derives the posture, which is how a suspended department climbs back toward `OPEN`."

    Design: Corner/state_machines/excursion_dispose_writes_shrink_violation_and_reopens_posture
    """
    env = _disposed_slot_one_lot(api)
    counter_id = env["counter"]["id"]

    assert env["resolved"]["status"] == "RESOLVED_DISPOSED"
    counter = fixtures.read_counter(api, counter_id)
    assert counter["open_excursion_count"] == 0
    assert counter["violation_points"] == 3
    assert counter["posture"] == "OPEN"
    assert_cents(counter["shrink_gross_cents"], 0)


def test_11_submitting_an_already_submitted_document_is_not_idempotent(api):
    """PRD §3.2: "Submitting a record advances it from `DRAFT` to `SUBMITTED`, again requiring
    that `harvest_date` be no later than `landing_date`; the submission may optionally carry a
    `chain_of_custody_ref`, and when it does, the supplied value replaces the stored one. The
    same submission action is also the amendment path: a record sitting in `DEFICIENT` returns
    to `SUBMITTED` and its `amendment_count` increases by one."

    Design: Corner/state_machines/repeat_submit_of_an_accepted_import_document_is_rejected
    """
    env = _submitted_snapper_document(api)
    supplier_id = env["supplier"]["id"]
    assert env["submitted"]["status"] == "SUBMITTED"

    response = api.submit_simp_document(
        env["document"]["id"],
        {"chain_of_custody_ref": "COC-55210-REV2"},
        make_supplier_rep_headers(supplier_id),
    )
    validate_error(response, ApiErrorId.ERR_SIMP_STATE_INVALID.value, expected_status=409)

    document = fixtures.read_simp_document(api, supplier_id, env["document"]["id"])
    assert document["status"] == "SUBMITTED"
    assert document["amendment_count"] == 0
    assert document["chain_of_custody_ref"] == "COC-55210"
    assert document["reviewed_at"] is None
