"""Participation sales: hold conservation, nested fee-share rounding with the bank
remainder, headroom bounds, and letter-state gates (PRD section 3.8).
"""
from test_helpers import (
    ApiErrorId, api_client, deal_approved, deal_commitment, deal_documentation,
    deal_letter_issued, get_application, get_letter, propose_participation,
    setup_officers, validate_error, validate_paginated, validate_success,
    create_borrower, loan_application_payload,
)


def _commitment_200m():
    """Clean 200,000,000 deal in DOCUMENTATION with letter ACCEPTED (fee 1,750,000)."""
    return deal_documentation(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")


def _cold_storage_issued_letter():
    """80,000,000 SMALL deal in COMMITMENT with the letter ISSUED (not accepted);
    bank_hold 80,000,000, fee 800,000."""
    return deal_letter_issued(
        borrower_kw={"legal_name": "Cold Storage Partners", "naics_code": "493120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 80_000_000, "term_months": 60},
        statement_shape="COLD",
        appraised_value_cents=160_000_000, orderly_liquidation_value_cents=150_000_000,
        level="SMALL", session_window=("2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z"))


def test_tiered_fee_and_first_share_rounding():
    """PRD section 3.6: "the first $1,000,000.00 is charged at 1.00%, the next
    $4,000,000.00 at 0.75%". PRD section 3.8: "Each participation in `COMMITTED` or
    `FUNDED` status, visited in ascending `created_at` order, is assigned a
    `fee_share_cents` equal to the letter's `origination_fee_cents` multiplied by
    the participation's `allocated_amount_cents` and divided by the letter's
    `committed_amount_cents`, with each share rounded half-up to whole cents
    individually."

    Design: Difficulty/combinatorial_formula/participation_fee_rounding_order_remainder
    """
    ctx = _commitment_200m()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    letter = get_letter(o, app_id)
    assert letter["origination_fee_cents"] == 1_750_000, (
        "tier1 100,000,000 x 0.0100 + tier2 100,000,000 x 0.0075")

    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=66_666_667)
    committed = validate_success(api_client.commit_participation(p1["id"], o["rm"]["headers"]), 200)
    assert committed["fee_share_cents"] == 583_333, (
        "round_half_up(1,750,000 x 66,666,667 / 200,000,000)")


def test_bank_remainder_absorbs_rounding():
    """PRD section 3.8: "The bank's retained share, `bank_hold_fee_cents`, is never
    itself rounded: it is the exact remainder — the letter's `origination_fee_cents`
    minus the sum of the participant shares — so the shares and the bank remainder
    always sum back to the letter fee exactly."

    Design: Difficulty/combinatorial_formula/participation_fee_rounding_order_remainder
    """
    ctx = _commitment_200m()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=66_666_667)
    validate_success(api_client.commit_participation(p1["id"], o["rm"]["headers"]), 200)
    p2 = propose_participation(o, app_id, participant_bank_name="Bank South",
                               allocated_amount_cents=66_666_667)
    committed2 = validate_success(api_client.commit_participation(p2["id"], o["rm"]["headers"]), 200)
    assert committed2["fee_share_cents"] == 583_333

    app = get_application(o, app_id)
    assert app["bank_hold_fee_cents"] == 583_334, (
        "remainder absorber: 1,750,000 - 583,333 - 583,333")
    assert 583_333 + 583_333 + app["bank_hold_fee_cents"] == 1_750_000, (
        "allocation conserves the fee exactly")
    assert app["bank_hold_amount_cents"] == 66_666_666, (
        "200,000,000 - 2 x 66,666,667")


def test_propose_commit_hold_invariant():
    """PRD section 3.8: "`bank_hold_amount_cents` equals the letter's
    `committed_amount_cents` minus the sum of `allocated_amount_cents` over all
    participations in `PROPOSED`, `COMMITTED`, or `FUNDED` status" and "A new
    participation starts in `PROPOSED`, and its allocation immediately reduces the
    bank's hold."

    Design: Difficulty/compensating_invariant/participation_hold_conserved_across_commit_release
    """
    ctx = _cold_storage_issued_letter()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    app0 = get_application(o, app_id)
    assert app0["bank_hold_amount_cents"] == 80_000_000

    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=50_000_000)
    assert p1["status"] == "PROPOSED"
    app1 = get_application(o, app_id)
    assert app1["bank_hold_amount_cents"] == 30_000_000
    assert app1["bank_hold_amount_cents"] + 50_000_000 == 80_000_000

    committed = validate_success(api_client.commit_participation(p1["id"], o["rm"]["headers"]), 200)
    assert committed["status"] == "COMMITTED"
    assert committed["fee_share_cents"] == 500_000, (
        "round_half_up(800,000 x 50,000,000 / 80,000,000)")
    app2 = get_application(o, app_id)
    assert app2["bank_hold_amount_cents"] == 30_000_000, "COMMITTED stays allocated"
    assert app2["bank_hold_fee_cents"] == 300_000, "800,000 - 500,000"


def test_release_restores_hold_and_fee():
    """PRD section 3.8: "Releasing a participation — permitted from `PROPOSED` or
    `COMMITTED` — moves it to `RELEASED` and returns its `allocated_amount_cents`
    to `bank_hold_amount_cents`." and "When a committed participation is released,
    its fee share returns to the bank hold — `bank_hold_fee_cents` increases by the
    released share — and the participation's `fee_share_cents` is cleared".

    Design: Difficulty/compensating_invariant/participation_hold_conserved_across_commit_release
    """
    ctx = _cold_storage_issued_letter()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=50_000_000)
    validate_success(api_client.commit_participation(p1["id"], o["rm"]["headers"]), 200)
    p2 = propose_participation(o, app_id, participant_bank_name="Bank South",
                               allocated_amount_cents=10_000_000)
    app_mid = get_application(o, app_id)
    assert app_mid["bank_hold_amount_cents"] == 20_000_000
    assert 20_000_000 + 50_000_000 + 10_000_000 == 80_000_000

    released = validate_success(api_client.release_participation(p1["id"], o["rm"]["headers"]), 200)
    assert released["status"] == "RELEASED"
    assert released.get("fee_share_cents") is None, "the fee share is cleared on release"

    app_end = get_application(o, app_id)
    assert app_end["bank_hold_amount_cents"] == 70_000_000
    assert 70_000_000 + 10_000_000 == 80_000_000
    assert app_end["bank_hold_fee_cents"] == 800_000, "the 500,000 share returned to the bank"

    letter = get_letter(o, app_id)
    assert letter["committed_amount_cents"] == 80_000_000, (
        "the conserved quantity itself never moved")


def test_state_error_precedes_fiscal_error():
    """PRD section 2.8: "Where several of these checks guard the same endpoint, the
    numeric order above governs their relative priority" — commitment presence and
    state (stage 8) precedes participation headroom (stage 33). PRD section 3.8:
    "While the application is in `COMMITMENT`, `DOCUMENTATION`, `CLOSING`, or
    `FUNDED` and its letter is `ISSUED`, `ACCEPTED`, or `FUNDED` (otherwise
    `ERR_COMMITMENT_NOT_ACCEPTED`)".

    Design: Difficulty/priority_pair_validation_conflict/participation_state_error_beats_fiscal_error
    """
    # TERM_SHEET_NEGOTIATION: no letter exists and headroom is 0 — both rules fail.
    ctx = deal_approved(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    resp = api_client.create_participation(
        {"loan_application_id": app_id, "participant_bank_name": "Vulture Fund LP",
         "allocated_amount_cents": 10_000_000}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_ACCEPTED, 409)
    assert resp.json()["data"]["error_id"] != "ERR_PARTICIPATION_OVERALLOCATION"


def test_no_participation_persisted_on_rejection():
    """PRD section 3.8: "an over-allocation is rejected with
    `ERR_PARTICIPATION_OVERALLOCATION` (HTTP 422)" and the state gate "otherwise
    `ERR_COMMITMENT_NOT_ACCEPTED`" — a rejected proposal persists nothing;
    "Participations can be listed per application."

    Design: Difficulty/priority_pair_validation_conflict/participation_state_error_beats_fiscal_error
    """
    ctx = deal_approved(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        officer_keys=("rm", "an", "po", "apm", "ch", "m1", "m2", "m3", "m4", "adm"))
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    validate_error(api_client.create_participation(
        {"loan_application_id": app_id, "participant_bank_name": "Vulture Fund LP",
         "allocated_amount_cents": 10_000_000}, o["rm"]["headers"]),
        ApiErrorId.ERR_COMMITMENT_NOT_ACCEPTED)

    rows, meta = validate_paginated(api_client.list_application_participations(app_id, o["rm"]["headers"]))
    assert rows == [] and meta["total_count"] == 0, "no Participation row was created"

    # Control: once the letter exists (ISSUED), an in-headroom proposal succeeds.
    from test_helpers import issue_term_sheet, respond_sheet, issue_letter
    sheet = issue_term_sheet(o, app_id, 200_000_000)
    respond_sheet(o, sheet["id"], "ACCEPTED")
    letter = get_letter(o, app_id)
    issue_letter(o, letter["id"])
    ok = validate_success(api_client.create_participation(
        {"loan_application_id": app_id, "participant_bank_name": "Bank North",
         "allocated_amount_cents": 10_000_000}, o["rm"]["headers"]), 201)
    assert ok["status"] == "PROPOSED"


def test_participation_headroom_equality_then_overflow():
    """PRD section 3.8: "The allocation may not exceed the application's current
    unallocated headroom — its `bank_hold_amount_cents` — with exact equality
    permitted; an over-allocation is rejected with `ERR_PARTICIPATION_OVERALLOCATION`
    (HTTP 422)."

    Design: Corner/validations/participation_headroom_equality_then_overflow
    """
    ctx = _cold_storage_issued_letter()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    full = propose_participation(o, app_id, participant_bank_name="Bank North",
                                 allocated_amount_cents=80_000_000)
    assert full["status"] == "PROPOSED", "equality with the 80,000,000 hold is allowed"
    app = get_application(o, app_id)
    assert app["bank_hold_amount_cents"] == 0

    over = api_client.create_participation(
        {"loan_application_id": app_id, "participant_bank_name": "Bank South",
         "allocated_amount_cents": 1}, o["rm"]["headers"])
    validate_error(over, ApiErrorId.ERR_PARTICIPATION_OVERALLOCATION)

    rows, meta = validate_paginated(api_client.list_application_participations(app_id, o["rm"]["headers"]))
    assert meta["total_count"] == 1


def test_participation_requires_issued_letter():
    """PRD section 3.8: "While the application is in `COMMITMENT`, `DOCUMENTATION`,
    `CLOSING`, or `FUNDED` and its letter is `ISSUED`, `ACCEPTED`, or `FUNDED`
    (otherwise `ERR_COMMITMENT_NOT_ACCEPTED`), a `RelationshipManager` may propose
    selling a share" — a DRAFT letter does not satisfy the gate.

    Design: Corner/validations/participation_requires_issued_letter
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    assert ctx["letter"]["status"] == "DRAFT"

    resp = api_client.create_participation(
        {"loan_application_id": ctx["application"]["id"],
         "participant_bank_name": "Bank North", "allocated_amount_cents": 10_000_000},
        o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_ACCEPTED)

    rows, meta = validate_paginated(api_client.list_application_participations(
        ctx["application"]["id"], o["rm"]["headers"]))
    assert rows == []


def test_participation_create_denied_for_credit_administrator():
    """PRD section 4: proposing a participation is restricted to
    `RelationshipManager`. PRD section 2.8: "Role permission. The caller's role is
    permitted for this operation, including the operation-level restrictions that
    only a `CreditPolicyOfficer` may drive a checklist item to `WAIVED` and only a
    `CommitteeChair` may cast a REMAND vote; otherwise `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403). Applies to every endpoint." — the role check is stage 2, ahead of
    the commitment state check at stage 8.

    Design: Corner/rbac/participation_create_denied_for_credit_administrator
    """
    o = setup_officers(["rm", "adm"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)

    resp = api_client.create_participation(
        {"loan_application_id": app["id"], "participant_bank_name": "Bank North",
         "allocated_amount_cents": 1_000_000}, o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    assert resp.json()["data"]["error_id"] != "ERR_COMMITMENT_NOT_ACCEPTED"
