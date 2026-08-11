"""The billing-hold gate, posting rejections, the prepaid block and repeats."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    block_purchase,
    make_clinic_user_headers,
    new_clinic,
    new_contract,
    new_specialist,
    open_invoice,
    post_study,
    qc_study,
    read_and_finalize,
    set_billing_hold,
    set_clock,
    setup_telerad_scene,
    upload_study,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# The billing-hold gate pre-empts the study-state rung — difficulty instance
# --------------------------------------------------------------------------
def _ordered_study_under_a_clinic_on_billing_hold(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Arrears Vet", address_zone="Z10", species="FELINE",
        requested_modality="RADIOGRAPHY", study_modality="RADIOGRAPHY",
        body_regions=("LEFT_HOCK",), upload=False,
    )
    set_billing_hold(scene["clinic"]["id"], "HOLD")
    return scene


def test_the_billing_hold_gate_wins_over_the_study_state_rung_on_a_repeat(api):
    """PRD §2.9: "**G2 — the clinic billing hold (`ERR_CLINIC_BILLING_HOLD`, 409).**
    Intake writes for a clinic whose `billing_hold_status` is `HOLD` are refused.
    Exactly five operations are guarded: `POST /referrals`, `POST /appointments`,
    `POST /studies`, `POST /studies/{study_id}/escalate-stat` and `POST
    /studies/{study_id}/repeat`."
    PRD §2.9: "Gate order is absolute and independent of how many gates a single
    request trips"
    PRD §2.8 rung 19: "Study workflow precondition.** Internal order: a study already in a terminal
    workflow state — `CANCELLED` or `NOT_PERFORMED` — raises `ERR_STUDY_TERMINAL`
    (409); any other wrong from-state raises `ERR_STUDY_INVALID_STATE` (409).
    Applies to every study action endpoint."

    Design: Difficulty/priority_pair_validation_conflict/billing_hold_gate_preempts_study_state_rung_on_repeat
    """
    scene = _ordered_study_under_a_clinic_on_billing_hold(api)
    study = scene["studies"][0]

    response = api.repeat_study(
        study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"},
        make_clinic_user_headers(scene["clinic"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CLINIC_BILLING_HOLD.value)


def test_the_refused_repeat_writes_nothing_and_the_gate_also_bars_new_referrals(api):
    """PRD §2.9: "Work already in flight is untouched — acquisition, image QC, reading,
    reporting and billing all continue normally for a held clinic."
    PRD §3.2: "A clinic on billing hold cannot submit at all: gate G2 refuses with
    `ERR_CLINIC_BILLING_HOLD`."
    PRD §3.9: "A successful repeat creates a fresh study whose `repeat_of_study_id`
    points at the source, increments the source's `repeat_count` by 1, refreshes the
    appointment's disposition counters"

    Design: Difficulty/priority_pair_validation_conflict/billing_hold_gate_preempts_study_state_rung_on_repeat
    """
    scene = _ordered_study_under_a_clinic_on_billing_hold(api)
    study = scene["studies"][0]
    validate_error(
        api.repeat_study(study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"},
                         make_clinic_user_headers(scene["clinic"]["id"])),
        ApiErrorId.ERR_CLINIC_BILLING_HOLD.value,
    )

    unchanged = validate_success(api.get_study(study["id"], SCHED))
    assert unchanged["workflow_status"] == "ORDERED"
    assert unchanged["repeat_count"] == 0
    replacements, _meta = validate_paginated(
        api.list_studies(SCHED, params={"repeat_of_study_id": study["id"]})
    )
    assert replacements == []

    referral_response = api.create_referral(
        {
            "clinic_id": scene["clinic"]["id"],
            "patient_name": "Toby Two",
            "species": "FELINE",
            "study_kind": "TELERAD",
            "requested_modality": "RADIOGRAPHY",
            "priority": "ROUTINE",
            "clinical_history": "limping",
        },
        make_clinic_user_headers(scene["clinic"]["id"]),
    )
    validate_error(referral_response, ApiErrorId.ERR_CLINIC_BILLING_HOLD.value)


# --------------------------------------------------------------------------
# Posting rejections, isolated in ladder order
# --------------------------------------------------------------------------
def _three_clinics_with_uploaded_studies_and_three_invoices(api):
    set_clock("2026-05-04T09:00:00Z")
    expired_scene = setup_telerad_scene(
        clinic_name="Expired Contract Vet", address_zone="S6", qc_result=None, image_count=4,
    )
    new_contract(expired_scene["clinic"]["id"], kind="PER_STUDY_LIST",
                 valid_from="2026-01-01T00:00:00Z", valid_until="2026-02-01T00:00:00Z")
    good_scene = setup_telerad_scene(
        clinic_name="Good Contract Vet", address_zone="S6",
        contract_kind="PER_STUDY_LIST", qc_result=None, image_count=4,
    )
    other_scene = setup_telerad_scene(
        clinic_name="Third Party Vet", address_zone="S6",
        contract_kind="PER_STUDY_LIST", qc_result=None, image_count=4,
    )
    return {
        "expired": expired_scene,
        "good": good_scene,
        "other": other_scene,
        "expired_invoice": open_invoice(expired_scene["clinic"]["id"]),
        "good_may_invoice": open_invoice(good_scene["clinic"]["id"]),
        "good_june_invoice": open_invoice(good_scene["clinic"]["id"],
                                          period_start="2026-06-01", period_end="2026-06-30"),
    }


def test_posting_under_an_expired_contract_is_refused_before_every_billing_rule(api):
    """PRD §2.8 rung 16: "Contract is active.** The clinic must have exactly one `ClinicContract` whose
    computed `status` is `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` (409).
    Applies to `POST /invoices/{invoice_id}/post-study` and `POST
    /contracts/{contract_id}/block-purchase`."
    PRD §3.1: "From those three inputs the contract's `status` is computed, never
    stored: it is `EXPIRED` whenever the logical clock is at or after `valid_until` or
    strictly before `valid_from`; otherwise it is `SUSPENDED` when `suspended` is
    true; otherwise it is `ACTIVE`."

    Design: Corner/errors/billing_posting_rejection_sweep_across_contract_scope_and_state
    """
    world = _three_clinics_with_uploaded_studies_and_three_invoices(api)
    study = world["expired"]["studies"][0]
    invoice = world["expired_invoice"]

    response = api.post_study_to_invoice(
        invoice["id"],
        {"study_id": study["id"], "expected_invoice_version": invoice["version"]},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    assert validate_success(api.get_invoice(invoice["id"], BILLING))["total_cents"] == 0


def test_posting_a_study_belonging_to_another_clinic_is_a_scope_mismatch(api):
    """PRD §2.8 rung 47: "Invoice scope match**, on `POST /invoices/{invoice_id}/post-study`. Internal order:
    first, the study's clinic must equal the invoice's `clinic_id`, otherwise
    `ERR_CLINIC_MISMATCH` (422)"

    Both clinics involved hold exactly one contract computing to ACTIVE, so rung 16 is
    satisfied whichever clinic it is read against and the scope rung is the first that
    can fail.

    Design: Corner/errors/billing_posting_rejection_sweep_across_contract_scope_and_state
    """
    world = _three_clinics_with_uploaded_studies_and_three_invoices(api)
    foreign_study = world["other"]["studies"][0]
    invoice = world["good_may_invoice"]

    response = api.post_study_to_invoice(
        invoice["id"],
        {"study_id": foreign_study["id"], "expected_invoice_version": invoice["version"]},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_CLINIC_MISMATCH.value)
    assert validate_success(api.get_invoice(invoice["id"], BILLING))["total_cents"] == 0


def test_posting_a_study_acquired_outside_the_invoice_period_is_refused(api):
    """PRD §2.8 rung 47: "second, the study's `acquired_at` date — or, for a
    cancellation-fee-only posting, its `updated_at` date — must fall inside the
    invoice's `period_start` through `period_end` range inclusive, otherwise
    `ERR_STUDY_OUTSIDE_INVOICE_PERIOD` (422)."

    Derivation: the study is uploaded on 2026-05-04 while the invoice covers
    2026-06-01 through 2026-06-30, so its billable date falls outside the period.

    Design: Corner/errors/billing_posting_rejection_sweep_across_contract_scope_and_state
    """
    world = _three_clinics_with_uploaded_studies_and_three_invoices(api)
    study = world["good"]["studies"][0]
    june_invoice = world["good_june_invoice"]

    response = api.post_study_to_invoice(
        june_invoice["id"],
        {"study_id": study["id"], "expected_invoice_version": june_invoice["version"]},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_STUDY_OUTSIDE_INVOICE_PERIOD.value)
    assert validate_success(api.get_invoice(june_invoice["id"], BILLING))["total_cents"] == 0


def test_posting_a_study_that_is_neither_finalized_nor_carrying_a_fee_is_refused(api):
    """PRD §2.8 rung 48: "Study is postable** — its `workflow_status` is `FINALIZED`, or its
    `cancellation_fee_cents` is greater than zero for a fee-only posting; otherwise
    `ERR_STUDY_NOT_FINALIZED` (409)."

    Design: Corner/errors/billing_posting_rejection_sweep_across_contract_scope_and_state
    """
    world = _three_clinics_with_uploaded_studies_and_three_invoices(api)
    study = world["good"]["studies"][0]
    may_invoice = world["good_may_invoice"]

    response = api.post_study_to_invoice(
        may_invoice["id"],
        {"study_id": study["id"], "expected_invoice_version": may_invoice["version"]},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_STUDY_NOT_FINALIZED.value)
    assert validate_success(api.get_study(study["id"], SCHED))["billing_status"] == "UNBILLED"
    assert validate_success(api.get_invoice(may_invoice["id"], BILLING))["total_cents"] == 0


# --------------------------------------------------------------------------
# Optimistic concurrency on the invoice and on the contract
# --------------------------------------------------------------------------
def test_reposting_with_the_pre_posting_invoice_version_is_a_stale_version(api):
    """PRD §2.7: "Posting a study's charges to an invoice (`POST
    /invoices/{invoice_id}/post-study`) requires `expected_invoice_version`, matched
    against the target `Invoice`'s current `version`."
    PRD §2.8 rung 50: "Study is not already posted** — a study whose `billing_status` is `POSTED` may not
    be posted again until its lines have been reversed, and the attempt raises
    `ERR_STUDY_ALREADY_POSTED` (409)."

    Derivation: a telerad ultrasound study has no trip share, so it posts 26000 plus
    3 percent of 26000 = 780, an invoice total of 26780 carried by exactly two lines.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_repeat_posting_returns_412
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="OCC Vet 5", address_zone="O4",
                                contract_kind="PER_STUDY_LIST", technician_name="T O4",
                                image_count=5)
    specialist = new_specialist("Dr O4", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    read_and_finalize(study["id"], specialist["id"], findings="normal")
    invoice = open_invoice(scene["clinic"]["id"])
    stale_version = invoice["version"]
    posted = post_study(invoice["id"], study["id"], expected_invoice_version=stale_version)
    assert posted["total_cents"] == 26780

    response = api.post_study_to_invoice(
        invoice["id"],
        {"study_id": study["id"], "expected_invoice_version": stale_version},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert validate_success(api.get_invoice(invoice["id"], BILLING))["total_cents"] == 26780
    assert validate_success(api.get_study(study["id"], SCHED))["billing_status"] == "POSTED"
    lines, _meta = validate_paginated(
        api.list_charge_lines(BILLING, params={"invoice_id": invoice["id"]})
    )
    assert len(lines) == 2
    assert {line["kind"] for line in lines} == {"STUDY_READ", "ADMIN_FEE"}


def test_a_second_block_top_up_replaying_the_earlier_contract_version_is_refused(api):
    """PRD §2.7: "Topping up a prepaid block (`POST
    /contracts/{contract_id}/block-purchase`) requires `expected_contract_version`,
    matched against the target `ClinicContract`'s current `version`."
    PRD §2.7: "The field is **not optional**: omitting it is a request-shape failure
    reported as `ERR_VALIDATION`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_second_block_purchase_returns_412
    """
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("OCC Vet 4", "O3")
    contract = new_contract(clinic["id"], kind="PREPAID_BLOCK", block_purchased_studies=1)
    stale_version = contract["version"]
    after_first = block_purchase(contract["id"], 2, expected_contract_version=stale_version)
    assert after_first["block_purchased_studies"] == 3

    response = api.block_purchase(
        contract["id"],
        {"additional_studies": 2, "expected_contract_version": stale_version},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    final = validate_success(api.get_contract(contract["id"], BILLING))
    assert final["block_purchased_studies"] == 3
    assert final["block_remaining_studies"] == 3
    assert final["block_consumed_studies"] == 0


# --------------------------------------------------------------------------
# Repeats
# --------------------------------------------------------------------------
def test_a_quality_failure_repeat_is_free_and_links_back_to_its_source(api):
    """PRD §3.9: "**The cause decides who pays**, and it is a pure branch with no
    arithmetic: a repeat caused by `QC_FAILURE` or `EQUIPMENT_QUARANTINE` is provider
    fault and the replacement is created with `billing_status` of `NON_BILLABLE`, so
    its base price, trip share, surcharge and administrative fee are all 0, it never
    draws a block unit and it never joins its stop's trip-share allocation."
    PRD §3.9: "A successful repeat creates a fresh study whose `repeat_of_study_id`
    points at the source, increments the source's `repeat_count` by 1, refreshes the
    appointment's disposition counters, and — when the source was sitting in
    `REPEAT_PENDING` — closes the source out by moving it `REPEAT_PENDING →
    NOT_PERFORMED` now that its replacement exists."

    Design: Corner/entities/study_repeat_link_is_discoverable_through_the_self_referential_filter
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Redo Vet", address_zone="ZR", technician_name="Hub QC Three",
        technician_modalities=("RADIOGRAPHY",), requested_modality="RADIOGRAPHY",
        study_modality="RADIOGRAPHY", body_regions=("ELBOW",),
        image_count=2, qc_result="REPEAT_REQUIRED",
    )
    source = scene["studies"][0]

    replacement = validate_success(
        api.repeat_study(source["id"], {"repeat_cause": "QC_FAILURE"},
                         make_clinic_user_headers(scene["clinic"]["id"])),
        expected_status=201,
    )

    assert replacement["repeat_of_study_id"] == source["id"]
    assert replacement["billing_status"] == "NON_BILLABLE"
    assert replacement["workflow_status"] == "ORDERED"
    assert replacement["repeat_cause"] == "QC_FAILURE"
    source_after = validate_success(api.get_study(source["id"], SCHED))
    assert source_after["workflow_status"] == "NOT_PERFORMED"
    assert source_after["repeat_count"] == 1
    rows, _meta = validate_paginated(
        api.list_studies(SCHED, params={"repeat_of_study_id": source["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == replacement["id"]
    appointment = validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))
    assert appointment["ordered_studies_count"] == 2
    assert appointment["pending_studies_count"] == 1
    assert appointment["not_performed_studies_count"] == 1


def _finalized_clean_telerad_study(api, clinic_name="Free Redo Vet", zone="VA"):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name=clinic_name, address_zone=zone,
                                technician_name="T Ten", image_count=5)
    specialist = new_specialist("Dr Clean", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    read_and_finalize(study["id"], specialist["id"], findings="normal")
    return scene, study


def test_a_clean_study_cannot_claim_a_quality_failure_repeat(api):
    """PRD §3.9: "The stated cause must be supported by the source study's own
    condition — `EQUIPMENT_QUARANTINE` requires the study's acquiring equipment to be
    in `QUARANTINED`, `QC_FAILURE` requires the study's `qc_status` to be
    `REPEAT_REQUIRED` or `NON_DIAGNOSTIC`, and `CLINICIAN_EXTRA_VIEWS` requires the
    study to be `FINALIZED` with `qc_status` of `ACCEPTED` — and an unsupported claim
    is refused with `ERR_REPEAT_CAUSE_NOT_SUPPORTED`."

    Design: Corner/validations/repeat_cause_qc_failure_on_a_clean_study_returns_cause_not_supported
    """
    scene, study = _finalized_clean_telerad_study(api)

    response = api.repeat_study(
        study["id"], {"repeat_cause": "QC_FAILURE"},
        make_clinic_user_headers(scene["clinic"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REPEAT_CAUSE_NOT_SUPPORTED.value)
    assert validate_success(api.get_study(study["id"], SCHED))["repeat_count"] == 0


def test_the_same_verb_produces_a_priced_replacement_under_clinician_extra_views(api):
    """PRD §3.9: "A repeat caused by `CLINICIAN_EXTRA_VIEWS` is the clinician's own
    request: the identical verb produces a replacement with `billing_status` of
    `UNBILLED`, priced exactly like any first-time study, which does draw a block unit
    when one is available and does join its stop's trip-share allocation — thereby
    lowering every sibling's share."

    Design: Corner/validations/repeat_cause_qc_failure_on_a_clean_study_returns_cause_not_supported
    """
    scene, study = _finalized_clean_telerad_study(api)
    validate_error(
        api.repeat_study(study["id"], {"repeat_cause": "QC_FAILURE"},
                         make_clinic_user_headers(scene["clinic"]["id"])),
        ApiErrorId.ERR_REPEAT_CAUSE_NOT_SUPPORTED.value,
    )

    replacement = validate_success(
        api.repeat_study(study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"},
                         make_clinic_user_headers(scene["clinic"]["id"])),
        expected_status=201,
    )

    assert replacement["billing_status"] == "UNBILLED"
    assert replacement["repeat_of_study_id"] == study["id"]
    source_after = validate_success(api.get_study(study["id"], SCHED))
    assert source_after["workflow_status"] == "FINALIZED"
    assert source_after["repeat_count"] == 1


def test_a_third_repeat_of_the_same_study_breaches_the_repeat_cap(api):
    """PRD §3.9: "A study may spawn at most two replacements: a source whose
    `repeat_count` has reached 2 is refused with `ERR_REPEAT_CAP_EXCEEDED`."
    PRD §2.8 rung 46: "Repeat eligibility**, on `POST /studies/{study_id}/repeat`. Internal order: first, a
    source study whose `repeat_count` has reached 2 raises `ERR_REPEAT_CAP_EXCEEDED`
    (409)"

    Design: Corner/errors/route_stop_cap_and_repeat_cap_both_refuse_the_one_past_the_limit
    """
    scene, study = _finalized_clean_telerad_study(api, clinic_name="Cap Vet 4", zone="S8")
    clinic_headers = make_clinic_user_headers(scene["clinic"]["id"])
    first_redo = validate_success(
        api.repeat_study(study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"}, clinic_headers),
        expected_status=201,
    )
    second_redo = validate_success(
        api.repeat_study(study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"}, clinic_headers),
        expected_status=201,
    )

    response = api.repeat_study(
        study["id"], {"repeat_cause": "CLINICIAN_EXTRA_VIEWS"}, clinic_headers
    )

    validate_error(response, ApiErrorId.ERR_REPEAT_CAP_EXCEEDED.value)
    assert validate_success(api.get_study(study["id"], SCHED))["repeat_count"] == 2
    rows, _meta = validate_paginated(
        api.list_studies(SCHED, params={"repeat_of_study_id": study["id"]})
    )
    assert len(rows) == 2
    assert validate_success(api.get_study(first_redo["id"], SCHED))["billing_status"] == "UNBILLED"
    assert validate_success(api.get_study(second_redo["id"], SCHED))["billing_status"] == "UNBILLED"


def test_a_non_billable_replacement_may_never_be_posted_even_once_finalized(api):
    """PRD §2.8 rung 49: "Study is billable** — a study whose `billing_status` is `NON_BILLABLE` may never be
    posted, and the attempt raises `ERR_STUDY_NON_BILLABLE` (422)."
    PRD §3.9: "The fourth value on this axis, `NON_BILLABLE`, is terminal and is
    reached by a cancellation with a zero fee, by a stop bump, or by creating a repeat
    whose cause is `QC_FAILURE` or `EQUIPMENT_QUARANTINE`."

    Design: Corner/errors/non_billable_repeat_study_cannot_be_posted_even_when_finalized
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Free Repeat Vet", address_zone="S7", contract_kind="PER_STUDY_LIST",
        technician_name="T S7", image_count=3, qc_result="REPEAT_REQUIRED",
    )
    specialist = new_specialist("Dr S7", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    clinic_id = scene["clinic"]["id"]
    source = scene["studies"][0]
    replacement = validate_success(
        api.repeat_study(source["id"], {"repeat_cause": "QC_FAILURE"},
                         make_clinic_user_headers(clinic_id)),
        expected_status=201,
    )
    assert replacement["billing_status"] == "NON_BILLABLE"
    upload_study(replacement["id"], clinic_id, image_count=9)
    qc_study(replacement["id"], scene["technician"]["id"], "ACCEPTED")
    read_and_finalize(replacement["id"], specialist["id"], findings="diagnostic quality achieved")
    invoice = open_invoice(clinic_id)

    response = api.post_study_to_invoice(
        invoice["id"],
        {"study_id": replacement["id"], "expected_invoice_version": invoice["version"]},
        BILLING,
    )

    validate_error(response, ApiErrorId.ERR_STUDY_NON_BILLABLE.value)
    final = validate_success(api.get_study(replacement["id"], SCHED))
    assert final["workflow_status"] == "FINALIZED"
    assert final["billing_status"] == "NON_BILLABLE"
    assert validate_success(api.get_study(source["id"], SCHED))["workflow_status"] == "NOT_PERFORMED"
    assert validate_success(api.get_invoice(invoice["id"], BILLING))["total_cents"] == 0
    lines, _meta = validate_paginated(
        api.list_charge_lines(BILLING, params={"invoice_id": invoice["id"]})
    )
    assert lines == []


# --------------------------------------------------------------------------
# A cancelled study is terminal
# --------------------------------------------------------------------------
def test_cancelling_an_already_cancelled_study_reports_the_terminal_code(api):
    """PRD §2.8 rung 19: "Study workflow precondition.** Internal order: a study already in a terminal
    workflow state — `CANCELLED` or `NOT_PERFORMED` — raises `ERR_STUDY_TERMINAL`
    (409); any other wrong from-state raises `ERR_STUDY_INVALID_STATE` (409).
    Applies to every study action endpoint."
    PRD §3.9: "If the study's `study_kind` is `TELERAD`, the fee is 0: there is no
    stop, no lead time and no trip."

    Design: Corner/state_machines/cancel_study_twice_second_attempt_returns_study_terminal
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Twice Vet", address_zone="ZT",
                                body_regions=("ABDOMEN",), upload=False)
    study = scene["studies"][0]
    clinic_headers = make_clinic_user_headers(scene["clinic"]["id"])
    first = validate_success(
        api.cancel_study(study["id"], {"cancel_reason": "owner withdrew"}, clinic_headers)
    )
    assert first["workflow_status"] == "CANCELLED"
    assert first["cancellation_fee_cents"] == 0

    response = api.cancel_study(
        study["id"], {"cancel_reason": "owner withdrew again"}, clinic_headers
    )

    validate_error(response, ApiErrorId.ERR_STUDY_TERMINAL.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["cancellation_fee_cents"] == 0
    assert after["billing_status"] == "NON_BILLABLE"
