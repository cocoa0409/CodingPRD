"""Treatment cycle protocol axis: the fertilization fork, consent gating, state
preconditions, revert, donor reservation, cancellation fee tiers, and version
increment on mutation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_patient_headers,
)
import test_helpers.factories as f
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine / cycle_fork_fertilization_to_transfer_or_freeze
# ===========================================================================
def _two_fertilization_cycles():
    cid = fx.create_clinic(name="Fork Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    fx.setup_patient_with_consent(cid, pat, required_for=["CYCLE_START", "RETRIEVAL", "TRANSFER"])
    cycA = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cycA, NURSE))
    get_success_data(api_client.retrieve(cid, cycA, {"oocytes_retrieved": 10}, NURSE))
    get_success_data(api_client.fertilize(cid, cycA, {"embryos_fertilized": 6}, EMBRYO))
    cycB = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cycB, NURSE))
    get_success_data(api_client.retrieve(cid, cycB, {"oocytes_retrieved": 8}, NURSE))
    get_success_data(api_client.fertilize(cid, cycB, {"embryos_fertilized": 5}, EMBRYO))
    return cid, cycA, cycB


def test_fork_transfer_branch():
    """PRD 3.2: "An `Embryologist` may perform a **fresh transfer**, advancing
    `FERTILIZATION → FRESH_TRANSFER`; this branch consumes an embryo into transfer and
    auto-creates no cryo specimen."

    Design: Difficulty/non_linear_state_machine/cycle_fork_fertilization_to_transfer_or_freeze
    """
    cid, cycA, _ = _two_fertilization_cycles()
    res = validate_success(api_client.transfer(cid, cycA, EMBRYO))
    assert res["protocol_status"] == "FRESH_TRANSFER"


def test_fork_freeze_branch():
    """PRD 3.2: "Alternatively an `Embryologist` may elect **freeze-all**, advancing
    `FERTILIZATION → FREEZE_ALL`; this branch creates no specimen automatically either
    — instead the caller subsequently records specimen rows for freezing, as in §3.7."

    Design: Difficulty/non_linear_state_machine/cycle_fork_fertilization_to_transfer_or_freeze
    """
    cid, _, cycB = _two_fertilization_cycles()
    res = validate_success(api_client.freeze_all(cid, cycB, EMBRYO))
    assert res["protocol_status"] == "FREEZE_ALL"


# ===========================================================================
# Queue A — priority_pair_validation_conflict / state_beats_consent_safety_on_start_stim
# (PRD 2.6 fixes that the state-machine precondition is evaluated before the
#  business-safety consent rule, so the state error wins.)
# ===========================================================================
def _retrieval_cycle_with_revoked_consent():
    cid = fx.create_clinic(name="Prio Clinic A")["id"]
    pat = fx.create_patient(cid)["id"]
    form = fx.publish_consent_form(cid, required_for=["CYCLE_START", "RETRIEVAL"])
    consent = fx.sign_consent(cid, pat, form["id"])
    cyc = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 5}, NURSE))
    get_success_data(api_client.revoke_patient_consent(cid, consent["id"], make_patient_headers(pat)))
    return cid, cyc


def test_state_precondition_beats_consent_on_start_stim():
    """PRD 2.6: "Only after these structural checks does the system evaluate the
    optimistic-concurrency version match (where applicable), then the state-machine
    precondition that the target resource is in a state from which the requested
    transition is defined, and finally the business-referential and business-safety
    rules described in §3." PRD 3.2: "A `Nurse` begins stimulation, advancing
    `DRAFT → STIM`; this requires the cycle to currently be `DRAFT`
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`)..."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_consent_safety_on_start_stim
    """
    cid, cyc = _retrieval_cycle_with_revoked_consent()
    resp = api_client.start_stim(cid, cyc, NURSE)
    validate_error(resp, ApiErrorId.ERR_CYCLE_BAD_PROTOCOL_STATE.value)


def test_state_precondition_beats_consent_cycle_unchanged():
    """PRD 3.2: "A `Nurse` begins stimulation, advancing `DRAFT → STIM`; this requires
    the cycle to currently be `DRAFT` (`ERR_CYCLE_BAD_PROTOCOL_STATE`), the patient to
    be `ACTIVE` (`ERR_PATIENT_INACTIVE`), and an active consent covering the
    `CYCLE_START` gate (see §3.6, `ERR_CONSENT_MISSING`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_consent_safety_on_start_stim
    """
    cid, cyc = _retrieval_cycle_with_revoked_consent()
    resp = api_client.start_stim(cid, cyc, NURSE)
    validate_error(resp, ApiErrorId.ERR_CYCLE_BAD_PROTOCOL_STATE.value)
    cur = get_success_data(api_client.get_cycle(cid, cyc, NURSE))
    assert cur["protocol_status"] == "RETRIEVAL"


# ===========================================================================
# Queue A — cross_entity_state_dependency / start_stim_requires_active_patientconsent
# ===========================================================================
def test_start_stim_without_consent_rejected():
    """PRD 3.6: "For each gate, the patient must hold at least one `ACTIVE` patient
    consent whose signed, `PUBLISHED` consent form lists the relevant member in its
    `required_for` array; absence of such a consent is rejected with
    `ERR_CONSENT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/start_stim_requires_active_patientconsent
    """
    cid = fx.create_clinic(name="XDep Clinic A")["id"]
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    resp = api_client.start_stim(cid, cyc, NURSE)
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING.value)


def test_start_stim_without_consent_leaves_cycle_in_draft():
    """PRD 3.2: "A `Nurse` begins stimulation, advancing `DRAFT → STIM`; this requires
    the cycle to currently be `DRAFT` (`ERR_CYCLE_BAD_PROTOCOL_STATE`), the patient to
    be `ACTIVE` (`ERR_PATIENT_INACTIVE`), and an active consent covering the
    `CYCLE_START` gate (see §3.6, `ERR_CONSENT_MISSING`)."

    Design: Difficulty/cross_entity_state_dependency/start_stim_requires_active_patientconsent
    """
    cid = fx.create_clinic(name="XDep Clinic A2")["id"]
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    resp = api_client.start_stim(cid, cyc, NURSE)
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING.value)
    cur = get_success_data(api_client.get_cycle(cid, cyc, NURSE))
    assert cur["protocol_status"] == "DRAFT"


# ===========================================================================
# Queue B — state_machines
# ===========================================================================
def test_cancel_already_cancelled_cycle_rejected():
    """PRD 3.2: "A `Nurse` may cancel a cycle from any non-terminal protocol state —
    that is, when `protocol_status` is anything other than `COMPLETED` or `CANCELLED`
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`)..."

    Design: Corner/state_machines/cancel_already_cancelled_cycle_rejected
    """
    cid = fx.create_clinic(name="SM Clinic A")["id"]
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    v1 = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    get_success_data(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v1}, NURSE))
    v2 = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    resp = api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v2}, NURSE)
    validate_error(resp, ApiErrorId.ERR_CYCLE_BAD_PROTOCOL_STATE.value)
    assert get_success_data(api_client.get_cycle(cid, cyc, NURSE))["protocol_status"] == "CANCELLED"


def test_fertilize_from_stim_invalid_state():
    """PRD 3.2: "Recording **fertilization** is an `Embryologist` action advancing
    `RETRIEVAL → FERTILIZATION`; it requires the cycle to be `RETRIEVAL`
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`)..."

    Design: Corner/state_machines/fertilize_from_stim_invalid_state
    """
    ctx = fx.setup_cycle_in_stim(name="SM Clinic B", required_for=["CYCLE_START"])
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    resp = api_client.fertilize(cid, cyc, {"embryos_fertilized": 1}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_CYCLE_BAD_PROTOCOL_STATE.value)


def test_complete_without_outcome_rejected():
    """PRD 3.2: "completion requires the cycle to be in one of those two states
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and requires that an outcome report already exists
    for the cycle (`ERR_OUTCOME_REQUIRED`)."

    Design: Corner/state_machines/complete_without_outcome_rejected
    """
    ctx = fx.setup_cycle_in_fertilization(name="SM Clinic C",
                                          required_for=["CYCLE_START", "RETRIEVAL", "TRANSFER"],
                                          oocytes_retrieved=6, embryos_fertilized=3)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    get_success_data(api_client.transfer(cid, cyc, EMBRYO))
    resp = api_client.complete_cycle(cid, cyc, NURSE)
    validate_error(resp, ApiErrorId.ERR_OUTCOME_REQUIRED.value)
    assert get_success_data(api_client.get_cycle(cid, cyc, NURSE))["protocol_status"] == "FRESH_TRANSFER"


def test_embryos_exceed_oocytes_rejected():
    """PRD 3.2: "an `embryos_fertilized` count in the request that is an integer at
    least zero and no greater than the recorded `oocytes_retrieved`
    (`ERR_EMBRYO_COUNT_EXCEEDS_OOCYTES`)..."

    Design: Corner/state_machines/embryos_exceed_oocytes_rejected
    """
    ctx = fx.setup_cycle_in_retrieval(name="SM Clinic D",
                                      required_for=["CYCLE_START", "RETRIEVAL"], oocytes_retrieved=5)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    resp = api_client.fertilize(cid, cyc, {"embryos_fertilized": 7}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_EMBRYO_COUNT_EXCEEDS_OOCYTES.value)


def test_revert_to_stim_resets_oocytes():
    """PRD 3.2: "A `Nurse` may **revert a retrieval back to stimulation**, moving
    `RETRIEVAL → STIM`; this requires the cycle to be `RETRIEVAL`
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and resets `oocytes_retrieved` to 0."

    Design: Corner/state_machines/revert_to_stim_resets_oocytes
    """
    ctx = fx.setup_cycle_in_retrieval(name="SM Clinic E",
                                      required_for=["CYCLE_START", "RETRIEVAL"], oocytes_retrieved=9)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    res = validate_success(api_client.revert_to_stim(cid, cyc, NURSE))
    assert res["protocol_status"] == "STIM"
    assert res["oocytes_retrieved"] == 0


def test_donor_reserved_on_cycle_create():
    """PRD 3.2: "If a `donor_profile_id` is supplied, that donor must be `AVAILABLE`
    (`ERR_DONOR_NOT_AVAILABLE`); on success the donor moves `AVAILABLE → RESERVED`."

    Design: Corner/state_machines/donor_reserved_on_cycle_create
    """
    cid = fx.create_clinic(name="Donor Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    donor = fx.create_donor(cid, code="D-001", donor_type="EGG")["id"]
    get_success_data(api_client.create_cycle(cid, f.create_cycle_payload(pat, donor_profile_id=donor), NURSE))
    cur = get_success_data(api_client.get_donor(cid, donor, ADMIN))
    assert cur["status"] == "RESERVED"


# ===========================================================================
# Queue B — calculations / cancellation_fee_tier_retrieval
# ===========================================================================
def test_cancellation_fee_tier_retrieval():
    """PRD 3.9: "If it had reached `RETRIEVAL`, the fee is 150000 cents (1,500 dollars)."

    Design: Corner/calculations/cancellation_fee_tier_retrieval
    """
    ctx = fx.setup_cycle_in_retrieval(name="Fee Clinic",
                                      required_for=["CYCLE_START", "RETRIEVAL"], oocytes_retrieved=6)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    v = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    res = validate_success(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v}, NURSE))
    assert res["cancellation_fee_cents"] == 150000
    assert res["protocol_status"] == "CANCELLED"


# ===========================================================================
# Queue B — validations (cross-entity / referential / safety on the protocol axis)
# ===========================================================================
def test_create_cycle_against_retired_package_rejected():
    """PRD 3.2: "A cycle may not be created against an `INACTIVE` patient
    (`ERR_PATIENT_INACTIVE`) nor against a `RETIRED` insurance package
    (`ERR_PACKAGE_RETIRED`)."

    Design: Corner/validations/create_cycle_against_retired_package_rejected
    """
    cid = fx.create_clinic(name="Val Clinic B")["id"]
    pkg = fx.create_package(cid, name="Old Pkg", base_price_cents=100000, coverage_pct=0.5,
                            lifetime_coverage_cap_cents=100000)["id"]
    pat = fx.create_patient(cid, insurance_package_id=pkg)["id"]
    get_success_data(api_client.retire_package(cid, pkg, ADMIN))
    resp = api_client.create_cycle(cid, f.create_cycle_payload(pat), NURSE)
    validate_error(resp, ApiErrorId.ERR_PACKAGE_RETIRED.value)


def test_transfer_with_zero_embryos_rejected():
    """PRD 3.2: "Both branches require the cycle to be `FERTILIZATION`
    (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and require at least one embryo fertilized — that
    is, `embryos_fertilized` of at least 1 (`ERR_NO_EMBRYOS_AVAILABLE`)."

    Design: Corner/validations/transfer_with_zero_embryos_rejected
    """
    ctx = fx.setup_cycle_in_fertilization(name="Val Clinic C",
                                          required_for=["CYCLE_START", "RETRIEVAL", "TRANSFER"],
                                          oocytes_retrieved=3, embryos_fertilized=0)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    resp = api_client.transfer(cid, cyc, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_NO_EMBRYOS_AVAILABLE.value)


def test_settle_before_finalize_rejected():
    """PRD 3.9: "Settlement requires the cycle to be `ESTIMATED` (`ERR_BILLING_BAD_STATE`),
    the `protocol_status` to be finalized — that is, `COMPLETED` or `CANCELLED`
    (`ERR_CYCLE_NOT_FINALIZED`)..."

    Design: Corner/validations/settle_before_finalize_rejected
    """
    cid = fx.create_clinic(name="Fin Clinic")["id"]
    pkg = fx.create_package(cid, name="Fin Pkg", base_price_cents=100000, coverage_pct=0.5,
                            lifetime_coverage_cap_cents=100000)["id"]
    pat = fx.create_patient(cid, insurance_package_id=pkg)["id"]
    fx.setup_patient_with_consent(cid, pat, required_for=["CYCLE_START"])
    cyc = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
    v = get_success_data(api_client.get_cycle(cid, cyc, BILLING))["version"]
    resp = api_client.settle_billing(cid, cyc, {"expected_cycle_version": v}, BILLING)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FINALIZED.value)


def test_link_unavailable_donor_rejected():
    """PRD 3.2: "If a `donor_profile_id` is supplied, that donor must be `AVAILABLE`
    (`ERR_DONOR_NOT_AVAILABLE`); on success the donor moves `AVAILABLE → RESERVED`."

    Design: Corner/validations/link_unavailable_donor_rejected
    """
    cid = fx.create_clinic(name="Donor2 Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    donor = fx.create_donor(cid, code="D-RES", donor_type="SPERM")["id"]
    get_success_data(api_client.create_cycle(cid, f.create_cycle_payload(pat, donor_profile_id=donor), NURSE))
    resp = api_client.create_cycle(cid, f.create_cycle_payload(pat, donor_profile_id=donor), NURSE)
    validate_error(resp, ApiErrorId.ERR_DONOR_NOT_AVAILABLE.value)
    assert get_success_data(api_client.get_donor(cid, donor, ADMIN))["status"] == "RESERVED"


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_version_increments_on_mutation
# ===========================================================================
def test_cycle_version_increments_on_start_stim():
    """PRD 2.4: "an integer `version` that begins at its initial value and increments
    by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_mutation
    """
    cid = fx.create_clinic(name="Ver Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    fx.setup_patient_with_consent(cid, pat, required_for=["CYCLE_START"])
    cyc = fx.create_cycle(cid, pat)
    assert cyc["version"] == 1
    res = validate_success(api_client.start_stim(cid, cyc["id"], NURSE))
    assert res["version"] == 2
