"""Claim adjudication: the deficiency-cure revision loop, the cross-entity
dependence of validation on the settlement posture, the opt-out finalize gate,
and the half-open claim-filing window boundary.

Queue A (Difficulty): non_linear_state_machine (claim loop), the second half of
boundary_precision_check (claim deadline), cross_entity_state_dependency.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
REVIEWER = fixtures.REVIEWER


# ─── non_linear_state_machine: claim_cured_deficient_cured_revision_loop ─────
def test_claim_revision_loop_reaches_validated():
    """PRD §3.3: "The claim machine is `SUBMITTED → {VALIDATED, DEFICIENT}`, with
    a deficiency-cure revision loop `DEFICIENT → CURED → {VALIDATED, DEFICIENT}`
    and a rejection door reachable from `SUBMITTED`, `DEFICIENT`, or `CURED`."
    PRD §3.4: "From `CURED` the claim can be validated again or sent back into
    `DEFICIENT` by a fresh deficiency, closing the revision loop."

    Design: Difficulty/non_linear_state_machine/claim_cured_deficient_cured_revision_loop
    """
    settlement, member, claim = fixtures.setup_submitted_claim(
        clock="2026-01-05T00:00:00Z", claimed_loss_cents=5000
    )
    cid = claim["id"]
    # first deficiency from SUBMITTED -> DEFICIENT
    get_success_data(api_client.raise_deficiency(
        cid, {"reason_code": "MISSING_PROOF", "cure_deadline": "2026-02-15T00:00:00Z"}, REVIEWER))
    # cure -> CURED (Claimant owns it)
    fixtures.cure_claim(cid, member["id"])
    # second deficiency from CURED -> DEFICIENT (re-entry into the loop)
    get_success_data(api_client.raise_deficiency(
        cid, {"reason_code": "SIGNATURE_MISSING", "cure_deadline": "2026-02-20T00:00:00Z"}, REVIEWER))
    # cure again -> CURED
    fixtures.cure_claim(cid, member["id"])
    # validate from CURED -> VALIDATED
    result = get_success_data(api_client.validate_claim(cid, 5000, REVIEWER))
    assert result["status"] == "VALIDATED"
    assert result["open_deficiency_count"] == 0


def test_revision_loop_leaves_both_deficiencies_cured():
    """PRD §3.4: "A successful cure cascades down to every open deficiency child, setting each to `CURED`, resets the claim's `open_deficiency_count` to 0, moves the claim to `CURED`, and increments the claim's version."

    Design: Difficulty/non_linear_state_machine/claim_cured_deficient_cured_revision_loop
    """
    settlement, member, claim = fixtures.setup_submitted_claim(
        clock="2026-01-05T00:00:00Z", claimed_loss_cents=5000
    )
    cid = claim["id"]
    get_success_data(api_client.raise_deficiency(
        cid, {"reason_code": "MISSING_PROOF", "cure_deadline": "2026-02-15T00:00:00Z"}, REVIEWER))
    fixtures.cure_claim(cid, member["id"])
    get_success_data(api_client.raise_deficiency(
        cid, {"reason_code": "SIGNATURE_MISSING", "cure_deadline": "2026-02-20T00:00:00Z"}, REVIEWER))
    fixtures.cure_claim(cid, member["id"])
    get_success_data(api_client.validate_claim(cid, 5000, REVIEWER))

    defs, _ = validate_paginated(api_client.list_deficiencies(cid, REVIEWER))
    assert len(defs) == 2
    assert all(d["status"] == "CURED" for d in defs)


# ─── cross_entity_state_dependency: claim_validate_requires_settlement_claims_phase ─
def test_validate_succeeds_while_settlement_claims_open():
    """PRD §3.3: "Validating a claim — driving it from `SUBMITTED` to `VALIDATED`, or from `CURED` to `VALIDATED` — requires that the claim currently sit in `SUBMITTED` or `CURED`, that it carry no open deficiencies, and that the owning settlement be in `CLAIMS_OPEN` or `CLAIMS_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/claim_validate_requires_settlement_claims_phase
    """
    settlement, member, claim = fixtures.setup_submitted_claim(
        clock="2026-01-05T00:00:00Z", claimed_loss_cents=5000
    )
    result = get_success_data(api_client.validate_claim(claim["id"], 5000, REVIEWER))
    assert result["status"] == "VALIDATED"
    assert result["recognized_loss_cents"] == 5000


def test_validate_sets_recognized_loss_to_supplied_value():
    """PRD §3.3: "A successful validation sets `recognized_loss_cents` to the supplied value, moves the claim to `VALIDATED`, and increments the claim's version."

    Design: Difficulty/cross_entity_state_dependency/claim_validate_requires_settlement_claims_phase
    """
    settlement, member, claim = fixtures.setup_submitted_claim(
        clock="2026-01-05T00:00:00Z", claimed_loss_cents=5000
    )
    result = get_success_data(api_client.validate_claim(claim["id"], 4200, REVIEWER))
    assert result["status"] == "VALIDATED"
    assert result["recognized_loss_cents"] == 4200


# ─── cross_entity_state_dependency: optout_finalize_requires_member_has_no_active_claim ─
def test_finalize_optout_blocked_by_non_rejected_claim():
    """PRD §3.5: "Finalization is permitted only while the owning settlement is in `NOTICE_OPEN` or `CLAIMS_OPEN`, and only if the member has no non-rejected claim — participation and exclusion are mutually exclusive, so finalizing for a member who holds any claim that is not `REJECTED` is refused with `ERR_MEMBER_HAS_CLAIM` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/optout_finalize_requires_member_has_no_active_claim
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z",
        objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Dep2",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    opt_out = get_success_data(api_client.create_opt_out(
        {"settlement_id": s_id, "class_member_id": member["id"]}, ADMINISTRATOR))
    get_success_data(api_client.open_claims(s_id, ADMIN))
    fixtures.file_claim(s_id, member["id"], claimed_loss_cents=5000)

    resp = api_client.finalize_opt_out(opt_out["id"], ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_MEMBER_HAS_CLAIM.value)
    refreshed = get_success_data(api_client.get_opt_out(opt_out["id"], ADMINISTRATOR))
    assert refreshed["status"] == "REQUESTED"


def test_finalize_optout_succeeds_when_member_claim_free():
    """PRD §3.5: "A successful finalization sets the request to `EFFECTIVE` and, as a cross-entity effect, sets the member's status to `EXCLUDED`."

    Design: Difficulty/cross_entity_state_dependency/optout_finalize_requires_member_has_no_active_claim
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z",
        objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Dep2ok",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    opt_out = get_success_data(api_client.create_opt_out(
        {"settlement_id": s_id, "class_member_id": member["id"]}, ADMINISTRATOR))

    result = get_success_data(api_client.finalize_opt_out(opt_out["id"], ADMINISTRATOR))
    assert result["status"] == "EFFECTIVE"
    refreshed_member = get_success_data(api_client.get_class_member(member["id"], ADMINISTRATOR))
    assert refreshed_member["status"] == "EXCLUDED"


# ─── boundary_precision_check: claim_filed_at_exact_deadline_instant_rejected ─
def test_claim_filed_at_exact_deadline_is_rejected():
    """PRD §3.3: "A claim must be filed strictly before the settlement's `claim_filing_deadline` — a filing with the clock at or after that instant is untimely and rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_filed_at_exact_deadline_instant_rejected
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Deadline",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    fixtures.set_clock("2026-02-01T00:00:00Z")  # exactly the deadline instant

    resp = api_client.create_claim(
        {"settlement_id": s_id, "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)


def test_claim_filed_just_before_deadline_accepted():
    """PRD §3.3: "A claim must be filed strictly before the settlement's `claim_filing_deadline` — a filing with the clock at or after that instant is untimely and rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_filed_at_exact_deadline_instant_rejected
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re DeadlineOk",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    fixtures.set_clock("2026-01-31T23:59:59Z")  # one second before the deadline

    result = validate_success(api_client.create_claim(
        {"settlement_id": s_id, "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR,
    ), expected_status=201)
    assert result["status"] == "SUBMITTED"
