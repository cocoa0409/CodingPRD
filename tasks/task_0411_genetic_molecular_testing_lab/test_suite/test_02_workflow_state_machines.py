"""Pipeline state-machine claims: invalid-from rejection, terminal lockdown,
idempotency, precondition enforcement, and key state side effects (QNS branch,
specimen supersede, reclassification cycle).

Translates queue B (Corner) section `state_machines`, plus queue A
boundary_precision_check/qns_quantity_threshold_inclusive_boundary and
non_linear_state_machine/variant_reclassification_cycle_vus_pathogenic.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    TEST_USERS,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
MOLECULAR = TEST_USERS["molecular_headers"]


def test_submit_without_requisition_returns_not_found(api):
    """PRD §3.2: "Submitting the requisition ... is permitted only while the order's
    `pipeline_status` is `ORDERED` (otherwise `ERR_ORDER_BAD_PIPELINE_STATE`) and
    only when a requisition in `PENDING` status exists (otherwise
    `ERR_REQUISITION_NOT_FOUND`)."

    Design: Corner/state_machines/requisition_submit_from_ordered_without_requisition_returns_not_found
    """
    ctx = FX.setup_ordered(gene_symbols=("GSM1",), name="SM1")
    resp = api.submit_requisition(ctx["order"]["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_FOUND.value, 404)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ORDERED"


def test_sequencing_start_from_ordered_rejected(api):
    """PRD §3.5: "Once an order is `ACCESSIONED`, an `AccessioningTech` starts
    sequencing, which advances the order's `pipeline_status` from `ACCESSIONED` to
    `SEQUENCING` (permitted only from `ACCESSIONED`, else
    `ERR_ORDER_BAD_PIPELINE_STATE`)."

    Design: Corner/state_machines/sequencing_start_from_ordered_returns_order_bad_pipeline_state
    """
    ctx = FX.setup_ordered(gene_symbols=("GSM2",), name="SM2")
    resp = api.start_sequencing(ctx["order"]["id"], ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_ORDER_BAD_PIPELINE_STATE.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ORDERED"


def test_reaccession_accessioned_specimen_rejected(api):
    """PRD §3.4: "Accessioning a specimen is the gate into the sequencing pipeline
    and is permitted only while the order is in `REQUISITIONED` `pipeline_status`
    (otherwise `ERR_ORDER_BAD_PIPELINE_STATE`) and the specimen is in `RECEIVED`
    `status` (otherwise `ERR_SPECIMEN_BAD_STATE`)."

    After a successful accession both preconditions are now violated (order is
    ACCESSIONED, specimen is ACCESSIONED); the PRD does not pin which of the two
    state errors is reported first, so either is accepted.

    Design: Corner/state_machines/accession_already_accessioned_specimen_returns_specimen_bad_state
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GSM3",), name="SM3")
    spec = FX.add_specimen(ctx["order"]["id"])
    FX.accession(ctx["order"]["id"], spec["id"])
    resp = api.accession_specimen(ctx["order"]["id"], spec["id"], ACCESSIONING)
    validate_error_is_one_of(resp, [ApiErrorId.ERR_SPECIMEN_BAD_STATE.value,
                                    ApiErrorId.ERR_ORDER_BAD_PIPELINE_STATE.value])
    reread = validate_success(api.get_specimen(spec["id"], ACCESSIONING), 200)
    assert reread["status"] == "ACCESSIONED"


def test_variant_call_off_sequencing_rejected(api):
    """PRD §3.5: "While the order is in `SEQUENCING`, a `MolecularTechnologist` calls
    variants." (Variant calling requires the SEQUENCING pipeline state; calling at
    ACCESSIONED is not a defined transition and yields the bad-pipeline-state error
    per PRD §2.8 state-check layer.)
    PRD §2.8: "whether the target resource is in a state from which the requested
    transition is defined (the bad-state family: `ERR_ORDER_BAD_PIPELINE_STATE` ...)."

    Design: Corner/state_machines/classify_from_ordered_pipeline_returns_order_bad_pipeline_state
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GSM4",), name="SM4")
    spec = FX.add_specimen(ctx["order"]["id"])
    FX.accession(ctx["order"]["id"], spec["id"])  # order now ACCESSIONED, not SEQUENCING
    resp = api.create_variant(ctx["order"]["id"],
                              F.create_variant_payload(ctx["genes"][0]["id"], hgvs="c.60A>T"),
                              MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_ORDER_BAD_PIPELINE_STATE.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ACCESSIONED"


def test_cancel_signed_out_order_rejected(api):
    """PRD §3.13: "an attempt to cancel an order already in a terminal state
    (`SIGNED_OUT` or `CANCELLED`) is rejected with `ERR_ORDER_NOT_CANCELLABLE`
    (HTTP 409)."

    Design: Corner/state_machines/cancel_already_signed_out_order_returns_not_cancellable
    """
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GSM5",), name="SM5")
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "too late"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "SIGNED_OUT"


def test_complete_classification_with_unclassified_rejected(api):
    """PRD §3.5: "Finalizing classification advances the order from `SEQUENCING` to
    `CLASSIFIED` (permitted only from `SEQUENCING`). It requires that no variant on
    the order remains `UNCLASSIFIED`; if any does, the request is rejected with
    `ERR_UNCLASSIFIED_VARIANTS_EXIST` (HTTP 409)."

    Design: Corner/state_machines/classification_complete_with_unclassified_variant_returns_unclassified_exist
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GSM6",), name="SM6")
    FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.62A>T")
    resp = api.complete_classification(ctx["order"]["id"], MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_UNCLASSIFIED_VARIANTS_EXIST.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "SEQUENCING"


def test_create_report_from_sequencing_rejected(api):
    """PRD §3.8: "A draft report is created against a `CLASSIFIED` order by either a
    `LabDirector` or a `MolecularTechnologist`."
    PRD §2.8: "whether the target resource is in a state from which the requested
    transition is defined (the bad-state family: `ERR_ORDER_BAD_PIPELINE_STATE` ...)."

    Design: Corner/state_machines/report_create_from_sequencing_returns_order_bad_pipeline_state
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GSM7",), name="SM7")
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.63A>T")
    FX.classify(ctx["order"]["id"], var["id"], "BENIGN")  # still SEQUENCING (no complete)
    resp = api.create_report(ctx["order"]["id"], MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_ORDER_BAD_PIPELINE_STATE.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "SEQUENCING"


def test_amend_draft_report_rejected(api):
    """PRD §3.9: "Amendment is performed by a `LabDirector` and is permitted only
    while the report is in `SIGNED_OUT` `status` (otherwise `ERR_REPORT_BAD_STATE`)."

    Design: Corner/state_machines/report_amend_on_draft_report_returns_report_bad_state
    """
    ctx = FX.setup_draft_report(classification="BENIGN", insurance_payer="SELF_PAY",
                                gene_symbols=("GSM8",), name="SM8")
    order = FX.get_order(ctx["order"]["id"])
    resp = api.amend_report(ctx["order"]["id"], ctx["report"]["id"],
                            F.amend_payload(order["version"]), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_REPORT_BAD_STATE.value, 409)
    reread = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert reread["status"] == "DRAFT"


def test_auth_decision_from_open_rejected(api):
    """PRD §3.6: "The decision is permitted only while the billing record is in
    `AUTH_REQUESTED` `status` (otherwise `ERR_BILLING_BAD_STATE`)."

    Design: Corner/state_machines/billing_auth_decision_from_open_returns_billing_bad_state
    """
    # Requisition created but NOT submitted -> billing still OPEN.
    ctx = FX.setup_ordered(gene_symbols=("GSM9",), name="SM9")
    FX.add_requisition(ctx["order"]["id"], "COMMERCIAL")
    resp = api.auth_decision(ctx["order"]["id"],
                             F.auth_decision_payload("APPROVED", 20000),
                             TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_BILLING_BAD_STATE.value, 409)


def test_schedule_already_scheduled_referral_rejected(api):
    """PRD §3.11: "scheduling is permitted only from `REQUESTED` `status` (otherwise
    `ERR_REFERRAL_BAD_STATE`)."

    Design: Corner/state_machines/referral_schedule_from_scheduled_returns_referral_bad_state
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Sched")
    ctx = FX.setup_ordered(gene_symbols=("GSM10",), name="SM10")
    ref = FX.request_referral(ctx["order"]["id"], gc["id"])
    FX.schedule_referral(ctx["order"]["id"], ref["id"],
                         "2026-06-25T10:00:00.000Z", "2026-06-25T11:00:00.000Z")
    resp = api.schedule_referral(ctx["order"]["id"], ref["id"],
                                 F.schedule_referral_payload("2026-06-25T12:00:00.000Z",
                                                             "2026-06-25T13:00:00.000Z"),
                                 TEST_USERS["counselor_headers"])
    validate_error(resp, ApiErrorId.ERR_REFERRAL_BAD_STATE.value, 409)
    reread = validate_success(api.get_referral(ref["id"], DIRECTOR), 200)
    assert reread["status"] == "SCHEDULED"


def test_start_running_run_rejected(api):
    """PRD §3.5: "A run may then be started (advancing `SCHEDULED` to `RUNNING`,
    permitted only from `SCHEDULED`) ... any state-mismatch on these three yields
    `ERR_RUN_BAD_STATE`."

    Design: Corner/state_machines/sequencer_run_start_from_running_returns_run_bad_state
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-RUN")
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GSM11",), name="SM11")
    run = FX.schedule_run(seq["id"], ctx["order"]["id"],
                          "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z")
    get_success_data(api.start_run(seq["id"], run["id"], ACCESSIONING))
    resp = api.start_run(seq["id"], run["id"], ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_RUN_BAD_STATE.value, 409)
    reread = validate_success(api.get_run(run["id"], ACCESSIONING), 200)
    assert reread["status"] == "RUNNING"


def test_aborted_run_window_freed_for_rescheduling(api):
    """PRD §3.12: "Aborting a run frees its window: aborted runs are excluded from
    this check and may have their time re-scheduled."

    Design: Corner/state_machines/aborted_run_window_freed_for_rescheduling
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-ABT", turnaround_buffer_minutes=60)
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GSM12",), name="SM12")
    run1 = FX.schedule_run(seq["id"], ctx["order"]["id"],
                           "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z")
    get_success_data(api.abort_run(seq["id"], run1["id"], ACCESSIONING))
    resp = api.schedule_run(seq["id"],
                            F.schedule_run_payload(ctx["order"]["id"],
                                                   "2026-06-20T10:00:00.000Z",
                                                   "2026-06-20T12:00:00.000Z"),
                            ACCESSIONING)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_revoked_consent_blocks_accession(api):
    """PRD §3.3: "When the ordered panel's `requires_consent` was true ... a consent
    in `SIGNED` status must exist before a specimen can be accessioned; absent one,
    accessioning is rejected with `ERR_CONSENT_REQUIRED` (HTTP 409)."
    PRD §3.3: "revoking it moves a `DRAFT` or `SIGNED` consent to `REVOKED`."

    Design: Corner/state_machines/consent_revoke_then_accession_blocked_consent_required
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", requires_consent=True,
                                 gene_symbols=("GSM13",), name="SM13")
    consent = get_success_data(api.create_consent(
        ctx["order"]["id"], F.create_consent_payload(incidental_findings_opt_in=False),
        INTAKE))
    get_success_data(api.sign_consent(ctx["order"]["id"], consent["id"], INTAKE))
    get_success_data(api.revoke_consent(ctx["order"]["id"], consent["id"], INTAKE))
    spec = FX.add_specimen(ctx["order"]["id"])
    resp = api.accession_specimen(ctx["order"]["id"], spec["id"], ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 409)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "REQUISITIONED"


def test_qns_reject_then_resubmit_supersedes(api):
    """PRD §3.4: "If this accession is a replacement for an earlier rejected specimen
    on the same order, that earlier specimen — which is sitting in `QNS_REJECTED` —
    is moved to `SUPERSEDED`, and its `superseded_by_specimen_id` is set to the id
    of the newly accessioned specimen."

    Design: Corner/state_machines/qns_reject_then_resubmit_supersedes_prior_specimen
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GSM14",), name="SM14")
    low = FX.add_specimen(ctx["order"]["id"], specimen_type="BLOOD", quantity_ng=49)
    FX.accession(ctx["order"]["id"], low["id"])  # QNS rejected (recorded outcome)
    ok = FX.add_specimen(ctx["order"]["id"], specimen_type="BLOOD", quantity_ng=50,
                         collected_at="2026-06-18T01:00:00.000Z")
    resp = api.accession_specimen(ctx["order"]["id"], ok["id"], ACCESSIONING)
    validate_success(resp, 200)
    low_re = validate_success(api.get_specimen(low["id"], ACCESSIONING), 200)
    ok_re = validate_success(api.get_specimen(ok["id"], ACCESSIONING), 200)
    assert low_re["status"] == "SUPERSEDED"
    assert low_re["superseded_by_specimen_id"] == ok["id"]
    assert ok_re["status"] == "ACCESSIONED"
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ACCESSIONED"


def test_cancel_cascade_voids_requisition_and_referral(api):
    """PRD §3.13: "Any requisition in `PENDING` or `SUBMITTED` status is moved to
    `VOID`." ... "Any counselor referral in `REQUESTED` or `SCHEDULED` status is
    moved to `CANCELLED`."

    Design: Corner/state_machines/cancel_cascade_voids_requisition_and_cancels_referral
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Cascade")
    ctx = FX.setup_ordered(gene_symbols=("GSM15",), name="SM15")
    req = FX.add_requisition(ctx["order"]["id"], "SELF_PAY")
    FX.submit_requisition(ctx["order"]["id"])
    ref = FX.request_referral(ctx["order"]["id"], gc["id"])
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "withdrawn"}, INTAKE)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "CANCELLED"
    req_re = validate_success(api.get_requisition(req["id"], DIRECTOR), 200)
    assert req_re["status"] == "VOID"
    ref_re = validate_success(api.get_referral(ref["id"], DIRECTOR), 200)
    assert ref_re["status"] == "CANCELLED"


# --------------------------------------------------------------------------- #
# Queue A — boundary precision + reclassification cycle
# --------------------------------------------------------------------------- #
def test_qns_threshold_inclusive_boundary_blood_50_vs_49(api):
    """PRD §3.4: "blood requires at least 50 nanograms ... A specimen is
    **sufficient** when its `quantity_ng` is greater than or equal to the minimum
    for its type — the boundary is inclusive, so a yield exactly equal to the
    minimum passes."
    PRD §3.4: "On the insufficient branch, the specimen is moved from `RECEIVED` to
    `QNS_REJECTED` and the order's `pipeline_status` stays at `REQUISITIONED`."

    Design: Difficulty/boundary_precision_check/qns_quantity_threshold_inclusive_boundary
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GB1",), name="PB")
    low = FX.add_specimen(ctx["order"]["id"], specimen_type="BLOOD", quantity_ng=49)
    low_after = validate_success(api.accession_specimen(ctx["order"]["id"], low["id"], ACCESSIONING), 200)
    assert low_after["status"] == "QNS_REJECTED"
    ok = FX.add_specimen(ctx["order"]["id"], specimen_type="BLOOD", quantity_ng=50)
    ok_after = validate_success(api.accession_specimen(ctx["order"]["id"], ok["id"], ACCESSIONING), 200)
    assert ok_after["status"] == "ACCESSIONED"
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ACCESSIONED"


def test_qns_threshold_inclusive_boundary_other_types(api):
    """PRD §3.4: "saliva at least 30 nanograms, and tissue at least 100 nanograms. A
    specimen is **sufficient** when its `quantity_ng` is greater than or equal to
    the minimum for its type — the boundary is inclusive, so a yield exactly equal
    to the minimum passes."

    Design: Difficulty/boundary_precision_check/qns_quantity_threshold_inclusive_boundary
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GB2",), name="PB2")
    low = FX.add_specimen(ctx["order"]["id"], specimen_type="SALIVA", quantity_ng=29)
    low_after = validate_success(api.accession_specimen(ctx["order"]["id"], low["id"], ACCESSIONING), 200)
    assert low_after["status"] == "QNS_REJECTED"
    ok = FX.add_specimen(ctx["order"]["id"], specimen_type="SALIVA", quantity_ng=30)
    ok_after = validate_success(api.accession_specimen(ctx["order"]["id"], ok["id"], ACCESSIONING), 200)
    assert ok_after["status"] == "ACCESSIONED"


def test_variant_reclassification_cycle_vus_pathogenic_vus(api):
    """PRD §3.5: "a variant currently at `VUS` may be moved to `PATHOGENIC`, and a
    variant currently at `PATHOGENIC` may be moved back to `VUS` — the cycle is
    symmetric and uses the same classify operation — and these reclassifications
    are permitted while the order is in either `SEQUENCING` or `CLASSIFIED`."

    Design: Difficulty/non_linear_state_machine/variant_reclassification_cycle_vus_pathogenic
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GX",), name="PX")
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.5G>A")
    FX.classify(ctx["order"]["id"], var["id"], "VUS")
    FX.classify(ctx["order"]["id"], var["id"], "PATHOGENIC")
    final = validate_success(
        api.classify_variant(ctx["order"]["id"], var["id"], F.classify_payload("VUS"), MOLECULAR), 200)
    assert final["classification"] == "VUS"


def test_variant_reclassification_round_trip_back_to_pathogenic(api):
    """PRD §3.5: "a variant currently at `VUS` may be moved to `PATHOGENIC`, and a
    variant currently at `PATHOGENIC` may be moved back to `VUS` — the cycle is
    symmetric and uses the same classify operation."

    Design: Difficulty/non_linear_state_machine/variant_reclassification_cycle_vus_pathogenic
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GX2",), name="PX2")
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.6G>A")
    FX.classify(ctx["order"]["id"], var["id"], "VUS")
    FX.classify(ctx["order"]["id"], var["id"], "PATHOGENIC")
    FX.classify(ctx["order"]["id"], var["id"], "VUS")
    final = validate_success(
        api.classify_variant(ctx["order"]["id"], var["id"], F.classify_payload("PATHOGENIC"), MOLECULAR), 200)
    assert final["classification"] == "PATHOGENIC"
