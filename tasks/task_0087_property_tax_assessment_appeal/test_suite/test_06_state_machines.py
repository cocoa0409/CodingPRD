"""State-machine transitions, terminal lockdown, preconditions, and cascades.

Covers corner queue (B) section: state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_taxpayer_headers,
    make_hearing_officer_headers,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
    setup_draft_assessment,
    setup_final_assessment,
    setup_under_review_appeal,
    setup_scheduled_hearing,
    claim_exemption,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]


def test_notice_already_noticed_assessment_invalid_state(api):
    """PRD §3.5: "On a successful notice the assessment recomputes its values and moves
    `DRAFT → NOTICED`."
    PRD §2.8: "State preconditions follow: the generic transition-allowed check
    (`ERR_INVALID_STATE`), then the roll-open, open-appeal, held-hearing, and
    assessments-final state gates."

    Design: Corner/state_machines/notice_already_noticed_assessment_invalid_state
    """
    owner, roll, parcel, asmt = setup_draft_assessment(market_value=90000, reassessment_event="NONE")
    validate_success(api.notice_assessment(asmt["id"], ASSESSOR))
    resp = api.notice_assessment(asmt["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_finalize_terminal_assessment_invalid_state(api):
    """PRD §3.5: "A successful finalize moves the assessment `NOTICED → FINAL`, which is
    terminal, and freezes `final_taxable_value` at its current value: the plain
    `taxable_value` if no appeal touched it, or the `appealed_value` an appeal resolution
    wrote into it."
    PRD §2.8: "State preconditions follow: the generic transition-allowed check
    (`ERR_INVALID_STATE`), then the roll-open, open-appeal, held-hearing, and
    assessments-final state gates."

    Design: Corner/state_machines/finalize_terminal_assessment_invalid_state
    """
    owner, roll, parcel, final = setup_final_assessment(market_value=90000, reassessment_event="SALE")
    assert final["status"] == "FINAL"
    resp = api.finalize_assessment(final["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_assessment_starts_in_draft(api):
    """PRD §3.3: "A fresh assessment begins in `DRAFT`."

    Design: Corner/state_machines/new_assessment_starts_in_draft
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    asmt = create_assessment(parcel["id"], roll["id"], 90000, reassessment_event="NONE")
    assert asmt["status"] == "DRAFT"


def test_certify_roll_copies_capped_base_to_parcel(api):
    """PRD §3.1: "Certification is also the moment the ledger synchronizes to the parcels:
    for each assessment on the roll, its `capped_base_value` is copied into the corresponding
    `Parcel.last_certified_capped_base`, refreshing that parcel's `updated_at` and advancing
    its `version`".

    Design: Corner/state_machines/certify_roll_copies_capped_base_to_parcel
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    # First-ever assessment, market_rebase -> capped_base 100000.
    asmt = create_assessment(parcel["id"], roll["id"], 100000, reassessment_event="NONE")
    validate_success(api.notice_assessment(asmt["id"], ASSESSOR))
    validate_success(api.finalize_assessment(asmt["id"], ASSESSOR))
    certified = validate_success(api.certify_tax_roll(roll["id"], ASSESSOR))
    assert certified["status"] == "CERTIFIED"
    parcel_after = validate_success(api.get_parcel(parcel["id"], ASSESSOR))
    assert parcel_after["last_certified_capped_base"] == 100000, (
        f"certify must copy capped_base 100000 to the parcel, "
        f"got {parcel_after['last_certified_capped_base']}"
    )


def test_open_roll_prior_not_certified_rejected(api):
    """PRD §3.1: "Opening a roll is permitted only when, if a `prior_roll_id` was given, that
    prior roll is itself `CERTIFIED`; otherwise the open is refused with
    `ERR_PRIOR_ROLL_NOT_CERTIFIED`."

    Design: Corner/state_machines/open_roll_prior_not_certified_rejected
    """
    roll1 = validate_success(
        api.create_tax_roll(f.create_tax_roll_payload(tax_year=2025), ASSESSOR), expected_status=201
    )  # left in DRAFT
    roll2 = validate_success(
        api.create_tax_roll(f.create_tax_roll_payload(tax_year=2026, prior_roll_id=roll1["id"]), ASSESSOR),
        expected_status=201,
    )
    resp = api.open_tax_roll(roll2["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_PRIOR_ROLL_NOT_CERTIFIED)


def test_notice_with_pending_exemption_rejected(api):
    """PRD §3.5: "Noticing is permitted only when the parent roll is `OPEN` — otherwise the
    notice is refused with `ERR_ROLL_NOT_OPEN` — and only when no exemption on the assessment
    is still `CLAIMED`; a lingering pending claim blocks the notice with
    `ERR_EXEMPTIONS_PENDING`."

    Design: Corner/state_machines/notice_with_pending_exemption_rejected
    """
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE", parcel_overrides={"is_primary_residence": True}
    )
    claim_exemption(asmt["id"], "HOMESTEAD")  # remains CLAIMED
    resp = api.notice_assessment(asmt["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_EXEMPTIONS_PENDING)


def test_settle_appeal_cascades_to_assessment(api):
    """PRD §3.6: "A **settlement** moves the appeal `UNDER_REVIEW → SETTLED` at an
    officer-supplied `settled_value`; that value must lie between the `requested_taxable_value`
    (inclusive) and the assessment's current `taxable_value` (inclusive), and a value outside
    that closed range is rejected with `ERR_SETTLEMENT_OUT_OF_RANGE`."
    PRD §3.6: "On settlement `determined_taxable_value` is set to `settled_value`."
    PRD §3.6: "When the appeal ends `SETTLED` or `GRANTED`, the value-lowering branch fires:
    the assessment's `appealed_value` is set to the appeal's `determined_taxable_value`, and
    its `final_taxable_value` is overwritten with that same determined value, so the bill will
    reflect the Board's decision rather than the original taxable value."
    PRD §3.6: "In both branches the assessment returns to `NOTICED`, where it can finally be
    finalized."

    Design: Corner/state_machines/appeal_settle_assessment_bubbles_under_appeal_to_noticed
    """
    # requested 80000, taxable 100000 -> settle at 90000 is within [80000, 100000].
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    settled = validate_success(api.settle_appeal(appeal["id"], {"settled_value": 90000}, ho))
    assert settled["status"] == "SETTLED"
    assert settled["determined_taxable_value"] == 90000
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["appealed_value"] == 90000
    assert asmt_after["final_taxable_value"] == 90000
    assert asmt_after["status"] == "NOTICED"


def test_cancel_scheduled_hearing_frees_slot(api):
    """PRD §3.7: "Cancelling a hearing moves it `SCHEDULED → CANCELLED` and frees its slot,
    so a previously conflicting reschedule can then succeed."

    Design: Corner/state_machines/cancel_scheduled_hearing_frees_slot
    """
    owner, roll, parcel, asmt, appeal, panel, hearing, ho_id = setup_scheduled_hearing(
        market_value=100000, panel_overrides={"setup_buffer_minutes": 15},
        starts_at="2026-07-01T10:00:00.000Z", ends_at="2026-07-01T11:00:00.000Z",
    )
    ho = make_hearing_officer_headers(ho_id)
    cancelled = validate_success(api.cancel_hearing(hearing["id"], ho))
    assert cancelled["status"] == "CANCELLED"
    # A 10:30-11:30 slot overlapped the original; after cancel it now fits.
    rescheduled = validate_success(
        api.create_hearing(
            f.create_hearing_payload(
                appeal["id"], panel["id"], ho_id,
                "2026-07-01T10:30:00.000Z", "2026-07-01T11:30:00.000Z",
            ),
            ho,
        ),
        expected_status=201,
    )
    assert rescheduled["status"] == "SCHEDULED"
