"""Business validations and cross-reference link checks: recognized-exceeds,
objection-window, member-settlement mismatch, invalid supersede, duplicate
email, excluded-member, cure-window, and the two not-found link errors. Also the
tax-form correct/no-issue computed reads.

Queue B (Corner): validations and endpoints sections.
"""
from test_helpers import (
    get_success_data,
    validate_error,
    validate_paginated,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
REVIEWER = fixtures.REVIEWER
CONTROLLER = fixtures.CONTROLLER


# ─── recognized_exceeds_claimed_returns_422 ──────────────────────────────────
def test_recognized_exceeds_claimed_rejected():
    """PRD §3.3: "this supplied amount must not exceed the claim's `claimed_loss_cents`, or the request is rejected with `ERR_RECOGNIZED_EXCEEDS_CLAIMED` (HTTP 422)."

    Design: Corner/validations/recognized_exceeds_claimed_returns_422
    """
    settlement, member, claim = fixtures.setup_submitted_claim(claimed_loss_cents=5000)
    resp = api_client.validate_claim(claim["id"], 6000, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_RECOGNIZED_EXCEEDS_CLAIMED.value)
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["status"] == "SUBMITTED"


# ─── objection_after_deadline_window_closed ──────────────────────────────────
def test_objection_after_deadline_window_closed():
    """PRD §3.5: "an objection must name a member belonging to the settlement and must be filed strictly before the `objection_deadline`, on pain of the same membership and timing rejections."

    Design: Corner/validations/objection_after_deadline_window_closed
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z",
        objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re ObjLate",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    fixtures.set_clock("2026-02-01T00:00:00Z")
    resp = api_client.create_objection(
        {"settlement_id": s_id, "class_member_id": member["id"], "grounds": "late"}, ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED.value)


# ─── member_settlement_mismatch_on_claim_create ──────────────────────────────
def test_member_settlement_mismatch_on_claim_create():
    """PRD §3.3: "The named member must belong to the same settlement named in the body, or the request is rejected with `ERR_MEMBER_SETTLEMENT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/member_settlement_mismatch_on_claim_create
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    sa = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z", objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re A")
    sb = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z", objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re B")
    get_success_data(api_client.open_notice(sa["id"], ADMIN))
    member = fixtures.register_member(sa["id"], full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(sa["id"], ADMIN))
    get_success_data(api_client.open_notice(sb["id"], ADMIN))
    # PRD §3.1: opening the claims window requires at least one class member
    # under the settlement, so seed sb with its own member before open-claims.
    fixtures.register_member(sb["id"], full_name="N", email="n@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(sb["id"], ADMIN))

    resp = api_client.create_claim(
        {"settlement_id": sb["id"], "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_MEMBER_SETTLEMENT_MISMATCH.value)


# ─── invalid_supersede_points_to_non_rejected_claim ──────────────────────────
def test_invalid_supersede_points_to_non_rejected_claim():
    """PRD §3.3: "When `supersedes_claim_id` is present the filing is a refile, and the superseded claim must be a `REJECTED` claim belonging to the same member and must not itself already have been superseded; a refile that breaks either condition is rejected with `ERR_INVALID_SUPERSEDE` (HTTP 422)."

    Design: Corner/validations/invalid_supersede_points_to_non_rejected_claim
    """
    settlement, member, claim = fixtures.setup_submitted_claim(claimed_loss_cents=5000)
    resp = api_client.create_claim({
        "settlement_id": settlement["id"],
        "class_member_id": member["id"],
        "claimed_loss_cents": 6000,
        "supersedes_claim_id": claim["id"],
    }, ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE.value)


# ─── duplicate_member_email_within_settlement ────────────────────────────────
def test_duplicate_member_email_within_settlement():
    """PRD §3.2: "Email must be unique within a settlement: registering a second member with an email already present under that settlement is rejected with `ERR_DUPLICATE_MEMBER_EMAIL` (HTTP 409)."

    Design: Corner/validations/duplicate_member_email_within_settlement
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(case_caption="In re Dup")
    s_id = settlement["id"]
    fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    resp = api_client.create_class_member(
        s_id, {"full_name": "M2", "email": "m@x.com", "tin_on_file": True}, ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBER_EMAIL.value)


# ─── excluded_member_cannot_file_claim ───────────────────────────────────────
def test_excluded_member_cannot_file_claim():
    """PRD §3.3: "A member who has been excluded cannot file at all; such an attempt is rejected with `ERR_MEMBER_EXCLUDED` (HTTP 409)."

    Design: Corner/validations/excluded_member_cannot_file_claim
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z", objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re Excl")
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    opt_out = get_success_data(api_client.create_opt_out(
        {"settlement_id": s_id, "class_member_id": member["id"]}, ADMINISTRATOR))
    get_success_data(api_client.finalize_opt_out(opt_out["id"], ADMINISTRATOR))
    get_success_data(api_client.open_claims(s_id, ADMIN))

    resp = api_client.create_claim(
        {"settlement_id": s_id, "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_MEMBER_EXCLUDED.value)


# ─── cure_after_deadline_window_closed ───────────────────────────────────────
def test_cure_after_deadline_window_closed():
    """PRD §3.4: "A cure is permitted only when every open deficiency on the claim still has a `cure_deadline` strictly after the clock; if the clock has reached or passed any open deficiency's cure deadline, the cure is untimely and rejected with `ERR_CURE_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/cure_after_deadline_window_closed
    """
    settlement, member, claim, defs = fixtures.setup_deficient_claim(
        deficiencies=[{"reason_code": "MISSING_PROOF", "cure_deadline": "2026-01-15T00:00:00Z"}],
        claimed_loss_cents=5000,
    )
    fixtures.set_clock("2026-01-15T00:00:00Z")  # exactly the cure deadline
    resp = api_client.cure_claim(claim["id"], ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED.value)
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["status"] == "DEFICIENT"


# ─── referenced_settlement_not_found_on_class_member_create ──────────────────
def test_referenced_settlement_not_found_on_class_member_create():
    """PRD §2.5: "the system validates each identifier left-to-right and rejects the request at the first identifier that does not resolve. A request against a path-referenced settlement (or any other primary path resource) that does not exist is rejected with `ERR_SETTLEMENT_NOT_FOUND` (HTTP 404)."

    Design: Corner/endpoints/referenced_settlement_not_found_on_class_member_create
    """
    resp = api_client.create_class_member(
        "00000000-0000-4000-8000-000000000000",
        {"full_name": "M", "email": "m@x.com", "tin_on_file": True},
        ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value)


# ─── claim_body_fk_member_not_found_returns_404 ──────────────────────────────
def test_claim_body_fk_member_not_found_returns_404():
    """PRD §2.5: "when a create request names a foreign key in its body — `settlement_id`, `class_member_id`, `claim_id`, `distribution_batch_id`, `payment_id`, or `supersedes_claim_id` — and that key points to no existing row, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/endpoints/claim_body_fk_member_not_found_returns_404
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z", objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re FK")
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    # PRD §3.1: opening the claims window requires at least one class member
    # under the settlement. The bogus FK below is distinct from this real member.
    fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    resp = api_client.create_claim({
        "settlement_id": s_id,
        "class_member_id": "00000000-0000-4000-8000-000000000000",
        "claimed_loss_cents": 5000,
    }, ADMINISTRATOR)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)


# ─── tax_form_correct_refreshes_amounts ──────────────────────────────────────
def test_tax_form_correct_refreshes_amounts():
    """PRD §3.9: "A `FundController` may correct an issued form, provided the referenced payment is still `COMMITTED`; correction refreshes `reportable_cents` from the payment's current `gross_amount_cents` and `withheld_cents` from its `withholding_cents`, moves the form to `CORRECTED`, and increments the form's version."

    Design: Corner/endpoints/tax_form_correct_refreshes_amounts
    """
    ctx = fixtures.setup_single_claim_posted(
        gross_fund_cents=80000, claimed_loss_cents=80000, recognized_loss_cents=80000,
        tin_on_file=False)
    batch_id = ctx["batch"]["id"]
    payments, _ = validate_paginated(api_client.list_batch_payments(batch_id, CONTROLLER))
    pay_id = payments[0]["id"]
    forms, _ = validate_paginated(api_client.list_tax_forms(CONTROLLER, params={"payment_id": pay_id}))
    assert len(forms) == 1
    tf_id = forms[0]["id"]

    result = get_success_data(api_client.correct_tax_form(tf_id, CONTROLLER))
    assert result["status"] == "CORRECTED"
    assert result["reportable_cents"] == 80000
    assert result["withheld_cents"] == 19200


# ─── tax_form_auto_issued_only_for_no_tin_over_threshold ─────────────────────
def test_no_tax_form_for_tin_on_file_claimant():
    """PRD §3.9: "When a batch posts, the system issues a tax form for each committed payment whose claimant has no taxpayer identification on file and whose `gross_amount_cents` is at least the 60000-cent reporting threshold — the same population subjected to backup withholding."

    Design: Corner/endpoints/tax_form_auto_issued_only_for_no_tin_over_threshold
    """
    ctx = fixtures.setup_single_claim_posted(
        gross_fund_cents=80000, claimed_loss_cents=80000, recognized_loss_cents=80000,
        tin_on_file=True)
    batch_id = ctx["batch"]["id"]
    payments, _ = validate_paginated(api_client.list_batch_payments(batch_id, CONTROLLER))
    pay_id = payments[0]["id"]
    forms, meta = validate_paginated(api_client.list_tax_forms(CONTROLLER, params={"payment_id": pay_id}))
    assert len(forms) == 0
    assert meta["total_count"] == 0
