"""Estimate creation guards, OCC, issue preconditions, and cross-entity state.

Difficulty instances cesd_issue_requires_contract_active and
ppvc_contract_state_beats_no_rate_fiscal each carry a complementary second test
that removes the winning violation to prove the pre-empted rule was genuinely
present.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_estimate_payload, create_line_payload,
    fixtures, TEST_USERS, NON_EXISTENT_UUID,
)

PROVIDER = TEST_USERS["provider_staff_headers"]


# --------------------------------------------------------------------------
# Corner — creation guards
# --------------------------------------------------------------------------
def test_create_estimate_contract_not_found(api):
    """PRD §2.7: "Every request that references other resources — through a path
    identifier or through a foreign-key field in the body — is validated for
    existence before any business rule runs ... the stale-version guard where
    applicable" runs only after existence. ERR_CONTRACT_NOT_FOUND is the 404 for
    a missing contract.

    Design: Corner/entities/create_estimate_contract_not_found
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    payload = create_estimate_payload(
        patient["id"], patient["version"], estimate_type="GFE_INSURED",
        contract_id=NON_EXISTENT_UUID)
    resp = api.create_estimate(payload, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)


def test_create_estimate_type_contract_mismatch(api):
    """PRD §3.4: "Supplying a contract_id on a self-pay estimate, or omitting it
    on an insured estimate, is rejected with ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH."

    Design: Corner/entities/create_estimate_type_contract_mismatch
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_contract(api)
    payload = create_estimate_payload(
        patient["id"], patient["version"], estimate_type="GFE_SELFPAY",
        contract_id=contract["id"])
    resp = api.create_estimate(payload, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH.value, 422)


def test_stale_patient_version_on_second_create(api):
    """PRD §2.6: "If expected_patient_version does not equal the patient's current
    version, the create is rejected with ERR_STALE_PATIENT_VERSION (HTTP 412) ...
    Each successful create itself advances the patient's version, so a second
    create replaying a pre-create version is deterministically rejected."

    Design: Corner/cross_cutting_complexity_layers/occ_estimate_stale_patient_version_conflict
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    stale_version = patient["version"]  # version 1
    fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY",
                          expected_patient_version=stale_version)  # advances to 2
    payload = create_estimate_payload(
        patient["id"], stale_version, estimate_type="GFE_SELFPAY")
    resp = api.create_estimate(payload, PROVIDER)
    validate_error(resp, ApiErrorId.ERR_STALE_PATIENT_VERSION.value, 412)


# --------------------------------------------------------------------------
# Corner — issue / accept precondition states
# --------------------------------------------------------------------------
def test_issue_already_issued_returns_invalid_state(api):
    """PRD §3.4: "Issuing a draft estimate is the pricing event, and it may
    proceed only when the estimate is in DRAFT." PRD §2.7 names ERR_INVALID_STATE
    as the target resource's own-state precondition failure.

    Design: Corner/state_machines/issue_already_issued_estimate_returns_invalid_state
    """
    b = fixtures.setup_insured_issued_single_line(api)
    resp = api.issue_estimate(b["estimate"]["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_accept_draft_estimate_returns_invalid_state(api):
    """PRD §3.5: "accepting anything not currently `ISSUED` is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_draft_estimate_returns_invalid_state
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY")
    resp = api.accept_estimate(estimate["id"], fixtures.make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_issue_estimate_with_no_lines(api):
    """PRD §3.4: "Issuing an estimate with no lines is rejected with
    ERR_ESTIMATE_NO_LINES."

    Design: Corner/state_machines/issue_estimate_with_no_lines_returns_no_lines
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    resp = api.issue_estimate(estimate["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NO_LINES.value, 422)


# --------------------------------------------------------------------------
# Corner — listing / pagination
# --------------------------------------------------------------------------
def test_list_estimates_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100." PRD
    §2.3: "The `meta` object of every list response includes `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_estimates_pagination
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY")
    fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY")
    resp = api.list_estimates(PROVIDER, params={"patient_id": patient["id"],
                                                "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# --------------------------------------------------------------------------
# Difficulty — cross-entity: issue requires ACTIVE contract
# --------------------------------------------------------------------------
def _draft_contract_insured_estimate(api, ingest_rate=True):
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_contract(api)  # DRAFT, never activated
    procedure = fixtures.new_procedure(api)
    if ingest_rate:
        fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000,
                                  expected_contract_version=contract["version"])
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], procedure["id"])
    return contract, estimate


def test_issue_draft_contract_rejected(api):
    """PRD §3.4: "issuing an insured estimate whose contract is not ACTIVE is
    rejected with ERR_CONTRACT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cesd_issue_requires_contract_active
    """
    _, estimate = _draft_contract_insured_estimate(api, ingest_rate=True)
    resp = api.issue_estimate(estimate["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)


def test_issue_succeeds_once_contract_active(api):
    """PRD §3.2: "ACTIVE is a required precondition before any insured estimate
    that references the contract may be issued." (Activating the same contract
    then permits issue, proving the contract-state gate was the block.)

    Design: Difficulty/cross_entity_state_dependency/cesd_issue_requires_contract_active
    """
    contract, estimate = _draft_contract_insured_estimate(api, ingest_rate=True)
    fixtures.activate_contract(api, contract["id"])
    issued = validate_success(api.issue_estimate(estimate["id"], PROVIDER), 200)
    assert issued["status"] == "ISSUED"
    assert issued["allowed_amount_cents"] == 200000


# --------------------------------------------------------------------------
# Difficulty — priority conflict: contract-state beats no-rate fiscal
# --------------------------------------------------------------------------
def test_contract_state_beats_no_rate(api):
    """PRD §2.7: "then the target resource's own-state precondition
    (ERR_INVALID_STATE), then cross-entity state and the remaining domain rules."
    PRD §3.4: "issuing an insured estimate whose contract is not ACTIVE is
    rejected with ERR_CONTRACT_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_contract_state_beats_no_rate_fiscal
    """
    # DRAFT contract AND no negotiated rate: cross-entity state wins.
    _, estimate = _draft_contract_insured_estimate(api, ingest_rate=False)
    resp = api.issue_estimate(estimate["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)


def test_no_rate_fires_once_contract_active(api):
    """PRD §3.4: "issuing an insured estimate any of whose line procedures lacks
    a non-superseded negotiated rate under the contract is rejected with
    ERR_NO_NEGOTIATED_RATE." (With the contract ACTIVE the fiscal rule surfaces,
    confirming it was the pre-empted violation.)

    Design: Difficulty/priority_pair_validation_conflict/ppvc_contract_state_beats_no_rate_fiscal
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)  # ACTIVE, but no rate ingested
    procedure = fixtures.new_procedure(api)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], procedure["id"])
    resp = api.issue_estimate(estimate["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_NO_NEGOTIATED_RATE.value, 422)
