"""Awards, appeals, the vacatur cascade, and the cyclic re-draft."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_party_headers,
    create_award_payload, create_appeal_payload,
)
from test_helpers.fixtures import (
    ADMIN, get_case, set_clock,
    setup_hearing_case, setup_issued_award, setup_appeal_under_review,
)

ADM = ADMIN


def _award(api, case_id, award_id):
    for a in validate_success(api.list_case_awards(case_id, ADM), 200):
        if a["id"] == award_id:
            return a
    raise AssertionError("award not found")


# ---- Difficulty: appeal-grant transitive cascade -------------------------

def test_appeal_grant_vacates_award_and_reverts_case(api):
    """PRD 3.9: "Granting an appeal triggers the vacatur cascade: the linked award
    (identified by the appeal's `award_id`) moves from `ISSUED` to `VACATED`, and that in
    turn bubbles the case from `AWARD_ISSUED` back to `HEARING` for re-arbitration."

    Design: Difficulty/transitive_cascade/appeal_grant_vacates_award_reverts_case_restores_balance
    """
    ctx = setup_appeal_under_review(api, claim_amount_cents=10_000_000,
                                    award_amount_cents=500_000, deposit_cents=500_000)
    granted = validate_success(api.transition_appeal(ctx["appeal"]["id"], {"to_status": "GRANTED"}, ADM), 200)
    assert granted["status"] == "GRANTED"
    assert _award(api, ctx["case"]["id"], ctx["award"]["id"])["status"] == "VACATED"
    assert get_case(api, ctx["case"]["id"])["status"] == "HEARING"


def test_appeal_grant_restores_deposit_balance(api):
    """PRD 3.9: "Returning to `HEARING` re-derives the case's `deposit_balance_cents` — the
    final administrative fee is no longer debited once the award is vacated". PRD 3.8:
    "The case's `deposit_balance_cents` is the paid deposits less the posted fees less the
    administrative fee".

    Design: Difficulty/transitive_cascade/appeal_grant_vacates_award_reverts_case_restores_balance
    """
    ctx = setup_appeal_under_review(api, claim_amount_cents=10_000_000,
                                    award_amount_cents=500_000, deposit_cents=500_000)
    validate_success(api.transition_appeal(ctx["appeal"]["id"], {"to_status": "GRANTED"}, ADM), 200)
    assert get_case(api, ctx["case"]["id"])["deposit_balance_cents"] == 500_000


# ---- Difficulty: cyclic vacatur -> re-draft ------------------------------

def test_award_vacatur_then_redraft_cycle(api):
    """PRD 3.9: "After a vacatur, the administrator may re-draft the vacated award from
    `VACATED` back to `DRAFT` (permitted while the case is in `HEARING`) so that a fresh
    award can be issued, closing the cycle."

    Design: Difficulty/non_linear_state_machine/award_vacatur_redraft_cycle
    """
    ctx = setup_appeal_under_review(api, claim_amount_cents=2_000_000,
                                    award_amount_cents=500_000, deposit_cents=500_000,
                                    ground="EVIDENT_PARTIALITY")
    validate_success(api.transition_appeal(ctx["appeal"]["id"], {"to_status": "GRANTED"}, ADM), 200)
    redrafted = validate_success(api.transition_award(ctx["award"]["id"], {"to_status": "DRAFT"}, ADM), 200)
    assert redrafted["status"] == "DRAFT"
    assert get_case(api, ctx["case"]["id"])["status"] == "HEARING"


def test_award_redraft_can_be_reissued(api):
    """PRD 3.9: "so that a fresh award can be issued, closing the cycle." PRD 3.9: "Issuing
    an award moves it from `DRAFT` to `ISSUED` ... and bubbles the case forward from
    `HEARING` to `AWARD_ISSUED`."

    Design: Difficulty/non_linear_state_machine/award_vacatur_redraft_cycle
    """
    ctx = setup_appeal_under_review(api, claim_amount_cents=2_000_000,
                                    award_amount_cents=500_000, deposit_cents=500_000,
                                    ground="EVIDENT_PARTIALITY")
    validate_success(api.transition_appeal(ctx["appeal"]["id"], {"to_status": "GRANTED"}, ADM), 200)
    validate_success(api.transition_award(ctx["award"]["id"], {"to_status": "DRAFT"}, ADM), 200)
    reissued = validate_success(api.transition_award(ctx["award"]["id"], {"to_status": "ISSUED"}, ADM), 200)
    assert reissued["status"] == "ISSUED"
    assert get_case(api, ctx["case"]["id"])["status"] == "AWARD_ISSUED"


# ---- Corner: award / appeal business gates -------------------------------

def test_draft_second_award_while_one_stands_returns_award_exists(api):
    """PRD 3.9: "A case may hold only one standing award: drafting a new award while the
    case already has an award in any status other than `VACATED` is rejected with
    `ERR_AWARD_EXISTS`."

    Design: Corner/validations/draft_second_award_while_one_stands_returns_award_exists
    """
    ctx = setup_hearing_case(api, claim_amount_cents=2_000_000)
    validate_success(api.create_award(ctx["case"]["id"], create_award_payload(
        award_type="MONETARY", award_amount_cents=500_000), ADM), 201)
    resp = api.create_award(ctx["case"]["id"], create_award_payload(
        award_type="MONETARY", award_amount_cents=600_000), ADM)
    validate_error(resp, ApiErrorId.ERR_AWARD_EXISTS.value)


def test_file_appeal_after_window_returns_appeal_window_closed(api):
    """PRD 3.9: "The filing must fall within the appeal window: it is allowed only when the
    logical clock is within thirty days (`APPEAL_WINDOW_DAYS`) of the target award's
    `issued_at`, and a filing after that window is rejected with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/file_appeal_after_window_returns_appeal_window_closed
    """
    ctx = setup_issued_award(api, claim_amount_cents=2_000_000, award_amount_cents=500_000,
                             clock="2026-06-01T00:00:00Z")
    set_clock(api, "2026-07-05T00:00:00Z")
    resp = api.create_appeal(create_appeal_payload(
        award_id=ctx["award"]["id"], ground="PROCEDURAL"),
        make_party_headers(ctx["pA"]["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)
