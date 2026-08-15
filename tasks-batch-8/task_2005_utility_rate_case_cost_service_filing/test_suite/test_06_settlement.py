"""Settlement rounds: circulation, unanimous-consent bubble-up, rescind cycle,
supersede mechanics, ownership scoping, and OCC on round creation (PRD §2.1,
§2.8, §2.9, §3.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    advance_to_hearing,
    assert_instant_equals,
    assert_version_incremented,
    circulate_proposal,
    create_proposal,
    create_settlement_proposal_payload,
    get_case,
    get_proposal,
    get_signatory,
    list_signatories,
    setup_assented_case,
    setup_circulated_proposal,
    setup_discovery_case,
    setup_settlement_case,
    sign_signatory,
    sign_all_signatories,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    make_intervenor_rep_headers,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]


def _sig_for(signatories, intervenor_id):
    for s in signatories:
        if s["intervenor_id"] == intervenor_id:
            return s
    raise AssertionError(f"no signatory row for intervenor {intervenor_id}")


# ─── Difficulty: transitive_cascade / signatory_unanimity_bubble ─────────────

def test_first_signature_does_not_bubble_second_does(api):
    """PRD §3.5: "On signing, the row moves to `SIGNED`, `signed_at` is stamped
    with the current clock, and the proposal's `signature_count` (the count of its
    signatories in `SIGNED`) is recomputed. If after a sign the proposal's
    `signature_count` equals its `required_signature_count` and
    `required_signature_count` is greater than zero, the proposal bubbles up to
    `ASSENTED` and the case's `assented_proposal_count` is incremented by one."

    Design: Difficulty/transitive_cascade/signatory_unanimity_bubble_cascade
    """
    s = setup_circulated_proposal(num_intervenors=2)
    sig1 = _sig_for(s.signatories, s.i1["id"])
    sig2 = _sig_for(s.signatories, s.i2["id"])
    sign_signatory(sig1["id"], s.i1["id"])
    mid = get_proposal(s.sp1["id"])
    assert mid["status"] == "UNDER_NEGOTIATION", "no premature bubble at 1 of 2"
    assert mid["signature_count"] == 1
    signed2 = sign_signatory(sig2["id"], s.i2["id"])
    assert signed2["status"] == "SIGNED"
    assert_instant_equals(signed2["signed_at"], DEFAULT_CLOCK_ISO,
                          "logical clock untouched")
    final = get_proposal(s.sp1["id"])
    assert final["status"] == "ASSENTED"
    assert final["signature_count"] == 2
    assert final["required_signature_count"] == 2


def test_unanimity_bubble_increments_case_counter(api):
    """PRD §3.5: "the proposal bubbles up to `ASSENTED` and the case's
    `assented_proposal_count` is incremented by one."

    Design: Difficulty/transitive_cascade/signatory_unanimity_bubble_cascade
    """
    s = setup_circulated_proposal(num_intervenors=2)
    assert get_case(s.case["id"])["assented_proposal_count"] == 0
    sign_all_signatories(s.signatories)
    assert get_proposal(s.sp1["id"])["status"] == "ASSENTED"
    assert get_case(s.case["id"])["assented_proposal_count"] == 1


# ─── Difficulty: non_linear_state_machine / assent_rescind cycle ─────────────

def test_rescind_drops_assented_proposal_back(api):
    """PRD §3.5: "Rescind is available on a `SIGNED` row while the owning proposal
    is in `UNDER_NEGOTIATION` or `ASSENTED`: the row moves to `RESCINDED`, the
    proposal's `signature_count` is recomputed, and if the proposal was `ASSENTED`
    it drops back to `UNDER_NEGOTIATION` and the case's `assented_proposal_count`
    is decremented by one."

    Design: Difficulty/non_linear_state_machine/settlement_proposal_assent_rescind_cycle
    """
    s = setup_assented_case(num_intervenors=2)
    assert s.sp1["status"] == "ASSENTED"
    assert s.sp1["signature_count"] == 2
    assert s.sp1["required_signature_count"] == 2
    sig2 = _sig_for(s.signatories, s.i2["id"])
    rescinded = validate_success(api.rescind_signatory(
        sig2["id"], make_intervenor_rep_headers(s.i2["id"])), 200)
    assert rescinded["status"] == "RESCINDED"
    after = get_proposal(s.sp1["id"])
    assert after["status"] == "UNDER_NEGOTIATION", "cycle edge ASSENTED -> UNDER_NEGOTIATION"
    assert after["signature_count"] == 1


def test_rescind_decrements_case_assented_counter(api):
    """PRD §3.5: "if the proposal was `ASSENTED` it drops back to
    `UNDER_NEGOTIATION` and the case's `assented_proposal_count` is decremented by
    one."
    PRD §2.10: "it is incremented on the bubble-up to `ASSENTED` and decremented
    on a rescind that drops an `ASSENTED` proposal back to `UNDER_NEGOTIATION`."

    Design: Difficulty/non_linear_state_machine/settlement_proposal_assent_rescind_cycle
    """
    s = setup_assented_case(num_intervenors=2)
    assert get_case(s.case["id"])["assented_proposal_count"] == 1
    sig2 = _sig_for(s.signatories, s.i2["id"])
    validate_success(api.rescind_signatory(
        sig2["id"], make_intervenor_rep_headers(s.i2["id"])), 200)
    assert get_case(s.case["id"])["assented_proposal_count"] == 0, (
        "bubble-up reversed without drift"
    )


# ─── Difficulty: cross_entity / proposal create requires SETTLEMENT ──────────

def _setup_hearing_case():
    s = setup_discovery_case()
    advance_to_hearing(s.case["id"])
    s.case = get_case(s.case["id"])
    return s


def test_proposal_create_requires_settlement_phase(api):
    """PRD §3.5: "While the case is in `SETTLEMENT`, a `UtilityFiler` may open a
    new settlement round by creating a SettlementProposal with `rate_case_id`,
    `proposed_revenue_requirement_cents`, `terms`, and the OCC field
    `expected_rate_case_version`."

    Design: Difficulty/cross_entity_state_dependency/proposal_create_requires_settlement_phase
    """
    s = _setup_hearing_case()
    version = get_case(s.case["id"])["version"]
    res = api.create_settlement_proposal(
        create_settlement_proposal_payload(s.case["id"], version), UF)
    validate_error(res, ApiErrorId.ERR_INVALID_CASE_STATE, expected_status=409)


def test_proposal_create_succeeds_after_settlement_window_opens(api):
    """PRD §3.5: "The new proposal's `round_number` is one for the case's first
    proposal, otherwise one more than the maximum existing `round_number`; it
    enters `DRAFT`; and the create increments the case's `version`."

    Design: Difficulty/cross_entity_state_dependency/proposal_create_requires_settlement_phase
    """
    s = _setup_hearing_case()
    v_before = get_case(s.case["id"])["version"]
    validate_success(api.open_settlement_window(s.case["id"], ALJ), 200)
    v_mid = get_case(s.case["id"])["version"]
    sp = create_proposal(s.case["id"])
    assert sp["status"] == "DRAFT"
    assert sp["round_number"] == 1
    assert_version_incremented(get_case(s.case["id"])["version"], v_mid)
    assert v_mid > v_before, "open-settlement-window advanced the case version"


# ─── Corner: invalid-from cluster around a circulated proposal ───────────────

def test_proposal_and_signatory_invalid_from_cluster(api):
    """PRD §3.5: "the signatory must be in `PENDING` (otherwise
    `ERR_INVALID_SIGNATORY_STATE`)" and "Circulation moves a `DRAFT` proposal to
    `UNDER_NEGOTIATION` (requiring the owning case in `SETTLEMENT`, otherwise
    `ERR_INVALID_CASE_STATE`; a proposal not in `DRAFT` is
    `ERR_INVALID_PROPOSAL_STATE`)" and "Decline is the terminal negative voice: an
    `IntervenorRep` declines their own `PENDING` row, moving it to `DECLINED`" and
    "Rescind is available on a `SIGNED` row while the owning proposal is in
    `UNDER_NEGOTIATION` or `ASSENTED`".

    Design: Corner/state_machines/proposal_and_signatory_invalid_from_cluster
    """
    s = setup_circulated_proposal(num_intervenors=2)
    sig1 = _sig_for(s.signatories, s.i1["id"])
    res1 = api.recommend_proposal(s.sp1["id"], ALJ)
    validate_error(res1, ApiErrorId.ERR_INVALID_PROPOSAL_STATE, expected_status=409)
    res2 = api.rescind_signatory(sig1["id"], make_intervenor_rep_headers(s.i1["id"]))
    validate_error(res2, ApiErrorId.ERR_INVALID_SIGNATORY_STATE, expected_status=409)
    declined = validate_success(api.decline_signatory(
        sig1["id"], make_intervenor_rep_headers(s.i1["id"])), 200)
    assert declined["status"] == "DECLINED"
    res3 = api.sign_signatory(sig1["id"], make_intervenor_rep_headers(s.i1["id"]))
    validate_error(res3, ApiErrorId.ERR_INVALID_SIGNATORY_STATE, expected_status=409)
    res4 = api.circulate_proposal(s.sp1["id"], UF)
    validate_error(res4, ApiErrorId.ERR_INVALID_PROPOSAL_STATE, expected_status=409)
    final = get_proposal(s.sp1["id"])
    assert final["status"] == "UNDER_NEGOTIATION"
    assert final["signature_count"] == 0


def test_advance_order_pending_requires_recommendation(api):
    """PRD §3.5: "With at least one `RECOMMENDED` proposal on the case, the ALJ
    certifies the record by advancing the case to `ORDER_PENDING`; if no proposal
    is `RECOMMENDED`, the advance is rejected with `ERR_NO_RECOMMENDED_SETTLEMENT`."

    Design: Corner/state_machines/advance_order_pending_requires_recommendation
    """
    s = setup_settlement_case(num_intervenors=1)
    res1 = api.advance_to_order_pending(s.case["id"], ALJ)
    validate_error(res1, ApiErrorId.ERR_NO_RECOMMENDED_SETTLEMENT, expected_status=409)
    sp = create_proposal(s.case["id"])
    circulate_proposal(sp["id"])
    res2 = api.advance_to_order_pending(s.case["id"], ALJ)
    validate_error(res2, ApiErrorId.ERR_NO_RECOMMENDED_SETTLEMENT, expected_status=409)
    assert get_case(s.case["id"])["status"] == "SETTLEMENT"


def test_intervenor_withdraw_voids_pending_signatories(api):
    """PRD §3.9: "fourth, every SettlementSignatory whose `intervenor_id` is this
    party and whose status is `PENDING` moves to `VOID`, with each affected
    proposal recomputing `signature_count` and `required_signature_count` with
    `VOID` rows excluded from both."
    PRD §3.5: "If after a sign the proposal's `signature_count` equals its
    `required_signature_count` and `required_signature_count` is greater than
    zero, the proposal bubbles up to `ASSENTED`"

    Design: Corner/state_machines/intervenor_withdraw_voids_pending_signatories
    """
    s = setup_circulated_proposal(num_intervenors=2)
    sig1 = _sig_for(s.signatories, s.i1["id"])
    sig2 = _sig_for(s.signatories, s.i2["id"])
    validate_success(api.withdraw_intervenor(
        s.i2["id"], make_intervenor_rep_headers(s.i2["id"])), 200)
    assert get_signatory(sig2["id"])["status"] == "VOID"
    assert get_proposal(s.sp1["id"])["required_signature_count"] == 1, (
        "VOID rows shrink the unanimity denominator"
    )
    validate_success(api.sign_signatory(
        sig1["id"], make_intervenor_rep_headers(s.i1["id"])), 200)
    final = get_proposal(s.sp1["id"])
    assert final["status"] == "ASSENTED"
    assert final["signature_count"] == 1
    assert get_case(s.case["id"])["assented_proposal_count"] == 1


# ─── Corner: ownership scoping on signatories ────────────────────────────────

def test_ownership_scope_enforced_on_signatory(api):
    """PRD §2.1: "signing, declining, or rescinding a SettlementSignatory
    requires `X-User-ID` equal to the signatory's `intervenor_id`" and
    "`ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) rejects ownership violations on the
    ownership-scoped endpoints".

    Design: Corner/validations/ownership_scope_enforced_on_signatory
    """
    s = setup_circulated_proposal(num_intervenors=2)
    sig2 = _sig_for(s.signatories, s.i2["id"])
    res = api.sign_signatory(sig2["id"], make_intervenor_rep_headers(s.i1["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)
    signed = validate_success(api.sign_signatory(
        sig2["id"], make_intervenor_rep_headers(s.i2["id"])), 200)
    assert signed["status"] == "SIGNED"


def test_ownership_beats_state_on_void_signatory(api):
    """PRD §2.9: "After shape and date checks, authentication header presence,
    then role authorization, then ownership scope, then segregation of duties.
    After auth come existence checks (each `ERR_*_NOT_FOUND`), then state-machine
    guards"
    PRD §3.5: "if the case has an existing proposal in `DRAFT` or
    `UNDER_NEGOTIATION`, that proposal moves to `SUPERSEDED` and each of its
    signatories in `PENDING` or `SIGNED` moves to `VOID`"

    Design: Corner/validations/ownership_beats_state_on_void_signatory
    """
    s = setup_circulated_proposal(num_intervenors=2)
    sig2 = _sig_for(s.signatories, s.i2["id"])
    sp2 = create_proposal(s.case["id"], rr=1840000000,
                          terms="Round 2 supersedes round 1")
    assert get_proposal(s.sp1["id"])["status"] == "SUPERSEDED"
    assert get_signatory(sig2["id"])["status"] == "VOID"
    res = api.sign_signatory(sig2["id"], make_intervenor_rep_headers(s.i1["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)
    assert get_proposal(sp2["id"])["round_number"] == 2


def test_assented_proposal_blocks_new_round(api):
    """PRD §3.5: "if the case has an existing proposal in `ASSENTED`,
    `RECOMMENDED`, or `ADOPTED`, the new round is rejected with
    `ERR_PROPOSAL_NOT_SUPERSEDABLE`."

    Design: Corner/validations/assented_proposal_blocks_new_round
    """
    s = setup_assented_case(num_intervenors=1)
    version = get_case(s.case["id"])["version"]
    res = api.create_settlement_proposal(
        create_settlement_proposal_payload(
            s.case["id"], version, proposed_revenue_requirement_cents=1840000000,
            terms="Round 2 attempt"), UF)
    validate_error(res, ApiErrorId.ERR_PROPOSAL_NOT_SUPERSEDABLE, expected_status=409)
    assert get_proposal(s.sp1["id"])["status"] == "ASSENTED", "incumbent untouched"
    data, meta = validate_paginated(api.list_settlement_proposals(
        UF, params={"rate_case_id": s.case["id"]}))
    assert meta["total_count"] == 1, "no new round persisted"


def test_settlement_above_filed_rejected(api):
    """PRD §3.5: "The settlement's revenue requirement must not exceed the case's
    `proposed_revenue_requirement_cents` — a settlement above the filed claim is
    `ERR_SETTLEMENT_ABOVE_FILED`."

    Design: Corner/validations/settlement_above_filed_rejected
    """
    s = setup_settlement_case(num_intervenors=1)
    version = get_case(s.case["id"])["version"]
    res = api.create_settlement_proposal(
        create_settlement_proposal_payload(
            s.case["id"], version, proposed_revenue_requirement_cents=1897500001,
            terms="One cent over the filed ask"), UF)
    validate_error(res, ApiErrorId.ERR_SETTLEMENT_ABOVE_FILED, expected_status=422)
    data, meta = validate_paginated(api.list_settlement_proposals(
        UF, params={"rate_case_id": s.case["id"]}))
    assert meta["total_count"] == 0, "nothing persisted"


def test_occ_stale_version_settlement_create_rejected(api):
    """PRD §2.8: "If `expected_rate_case_version` does not equal the case's
    current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from composing a round (or a filing) that
    would supersede state it has not observed."
    PRD §3.5: "The new proposal's `round_number` is one for the case's first
    proposal, otherwise one more than the maximum existing `round_number`"

    Design: Corner/complexity_layers/occ_stale_version_settlement_create_rejected
    """
    s = setup_settlement_case(num_intervenors=1)
    v0 = get_case(s.case["id"])["version"]
    sp1 = validate_success(api.create_settlement_proposal(
        create_settlement_proposal_payload(s.case["id"], v0, terms="Round 1"), UF), 201)
    assert sp1["round_number"] == 1
    res = api.create_settlement_proposal(
        create_settlement_proposal_payload(
            s.case["id"], v0, proposed_revenue_requirement_cents=1840000000,
            terms="Round 2 with stale version"), UF)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    v1 = get_case(s.case["id"])["version"]
    assert_version_incremented(v1, v0)
    sp2 = validate_success(api.create_settlement_proposal(
        create_settlement_proposal_payload(
            s.case["id"], v1, proposed_revenue_requirement_cents=1840000000,
            terms="Round 2 with fresh version"), UF), 201)
    assert sp2["round_number"] == 2
    assert get_proposal(sp1["id"])["status"] == "SUPERSEDED"
