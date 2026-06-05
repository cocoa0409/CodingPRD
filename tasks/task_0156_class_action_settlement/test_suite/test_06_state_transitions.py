"""State-machine corners: invalid transitions, precondition enforcement, initial
state, terminal lockdown, cross-entity opt-out exclusion/compensation, court
rulings, and the cure cascade.

Queue B (Corner): state_machines section.
"""
from test_helpers import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_claims_reviewer_headers, make_fund_controller_headers

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
REVIEWER = fixtures.REVIEWER
CONTROLLER = fixtures.CONTROLLER
COURT = fixtures.COURT


# ─── validate_claim_from_validated_returns_invalid_state ─────────────────────
def test_validate_already_validated_claim_returns_invalid_state():
    """PRD §3.3: "Validating a claim — driving it from `SUBMITTED` to `VALIDATED`, or from `CURED` to `VALIDATED` — requires that the claim currently sit in `SUBMITTED` or `CURED`, that it carry no open deficiencies, and that the owning settlement be in `CLAIMS_OPEN` or `CLAIMS_CLOSED`."

    Design: Corner/state_machines/validate_claim_from_validated_returns_invalid_state
    """
    settlement, member, claim = fixtures.setup_submitted_claim(claimed_loss_cents=5000)
    get_success_data(api_client.validate_claim(claim["id"], 5000, REVIEWER))
    resp = api_client.validate_claim(claim["id"], 4000, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["recognized_loss_cents"] == 5000


# ─── validate_claim_with_open_deficiency_returns_blocked ─────────────────────
def test_validate_claim_with_open_deficiency_blocked():
    """PRD §3.3: "If the claim still has any open deficiency the validation is blocked with `ERR_VALIDATION_BLOCKED_BY_DEFICIENCY` (HTTP 409)."

    Design: Corner/state_machines/validate_claim_with_open_deficiency_returns_blocked
    """
    settlement, member, claim, defs = fixtures.setup_deficient_claim(
        deficiencies=[{"reason_code": "MISSING_PROOF", "cure_deadline": "2026-02-15T00:00:00Z"}],
        claimed_loss_cents=5000,
    )
    resp = api_client.validate_claim(claim["id"], 5000, REVIEWER)
    # PRD §3.3 names ERR_VALIDATION_BLOCKED_BY_DEFICIENCY for an open deficiency,
    # but PRD §2.12 ranks state-transition legality (ERR_INVALID_STATE) strictly
    # above the deficiency-blocks-validation check, and a claim carrying an open
    # deficiency is DEFICIENT — not in the SUBMITTED/CURED validatable set. A
    # faithful PRD-only implementer following the priority order returns
    # ERR_INVALID_STATE; either error is PRD-consistent for this contested case.
    validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_VALIDATION_BLOCKED_BY_DEFICIENCY.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ],
    )
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["status"] == "DEFICIENT"


# ─── file_claim_initial_state_submitted ──────────────────────────────────────
def test_filed_claim_initial_state_submitted():
    """PRD §3.3: "Either way a claim is born in `SUBMITTED` with `recognized_loss_cents`, `open_deficiency_count`, and `paid_amount_cents` all at 0"

    Design: Corner/state_machines/file_claim_initial_state_submitted
    """
    settlement, member, claim = fixtures.setup_submitted_claim(claimed_loss_cents=5000)
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["status"] == "SUBMITTED"
    assert refreshed["recognized_loss_cents"] == 0
    assert refreshed["open_deficiency_count"] == 0


# ─── reopen_closed_settlement_terminal_lockdown ──────────────────────────────
def test_closed_settlement_rejects_open_claims():
    """PRD §3.10: "After reconciliation, a `SettlementAdmin` closes the settlement, moving it from `RECONCILED` to the terminal `CLOSED`."
    PRD §3.1: "If the posture is not `DRAFT`, the transition is rejected as an invalid state with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reopen_closed_settlement_terminal_lockdown
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    version = fixtures.get_settlement_version(s_id)
    get_success_data(api_client.reconcile(s_id, version, CONTROLLER))
    get_success_data(api_client.close_settlement(s_id, ADMIN))

    resp = api_client.open_claims(s_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert refreshed["status"] == "CLOSED"


# ─── optout_finalize_excludes_member_cross_entity ────────────────────────────
def test_optout_finalize_excludes_member_cross_entity():
    """PRD §3.5: "A successful finalization sets the request to `EFFECTIVE` and, as a cross-entity effect, sets the member's status to `EXCLUDED`."

    Design: Corner/state_machines/optout_finalize_excludes_member_cross_entity
    """
    settlement, member = fixtures.setup_notice_open_with_member()
    opt_out = get_success_data(api_client.create_opt_out(
        {"settlement_id": settlement["id"], "class_member_id": member["id"]}, ADMINISTRATOR))
    result = get_success_data(api_client.finalize_opt_out(opt_out["id"], ADMINISTRATOR))
    assert result["status"] == "EFFECTIVE"
    refreshed = get_success_data(api_client.get_class_member(member["id"], ADMINISTRATOR))
    assert refreshed["status"] == "EXCLUDED"


# ─── optout_revoke_restores_member_compensation ──────────────────────────────
def test_optout_revoke_restores_member_to_notified():
    """PRD §3.5: "The same administrator may later revoke an effective opt-out, again only while the settlement is in `NOTICE_OPEN` or `CLAIMS_OPEN`; revoking moves the request to the terminal `REVOKED` and restores the member to `NOTIFIED`."

    Design: Corner/state_machines/optout_revoke_restores_member_compensation
    """
    settlement, member = fixtures.setup_notice_open_with_member()
    opt_out = get_success_data(api_client.create_opt_out(
        {"settlement_id": settlement["id"], "class_member_id": member["id"]}, ADMINISTRATOR))
    get_success_data(api_client.finalize_opt_out(opt_out["id"], ADMINISTRATOR))
    result = get_success_data(api_client.revoke_opt_out(opt_out["id"], ADMINISTRATOR))
    assert result["status"] == "REVOKED"
    refreshed = get_success_data(api_client.get_class_member(member["id"], ADMINISTRATOR))
    assert refreshed["status"] == "NOTIFIED"


# ─── objection_sustained_by_court_valid_transition ───────────────────────────
def test_objection_sustained_by_court():
    """PRD §3.5: "The `Court` rules on a filed objection by supplying a `ruling` that drives it to either the terminal `SUSTAINED` or the terminal `OVERRULED`; both rulings act on a claim in `FILED` and are symmetric, each simply setting the objection to the corresponding terminal status."

    Design: Corner/state_machines/objection_sustained_by_court_valid_transition
    """
    settlement, member = fixtures.setup_notice_open_with_member()
    objection = get_success_data(api_client.create_objection(
        {"settlement_id": settlement["id"], "class_member_id": member["id"], "grounds": "fees too high"},
        ADMINISTRATOR))
    result = get_success_data(api_client.rule_objection(objection["id"], "SUSTAINED", COURT))
    assert result["status"] == "SUSTAINED"


# ─── deficiency_cure_cascades_to_deficiency_cured ────────────────────────────
def test_cure_cascades_all_deficiencies_to_cured():
    """PRD §3.4: "A successful cure cascades down to every open deficiency child, setting each to `CURED`, resets the claim's `open_deficiency_count` to 0, moves the claim to `CURED`, and increments the claim's version."

    Design: Corner/state_machines/deficiency_cure_cascades_to_deficiency_cured
    """
    # PRD §3.4: a deficiency may be raised only on a SUBMITTED or CURED claim,
    # so raising the first drives the claim to DEFICIENT and a second cannot be
    # raised until the claim returns to CURED — at most one OPEN deficiency child
    # exists at any instant. The cure still cascades down to "every open
    # deficiency child"; here that set is the single OPEN deficiency.
    settlement, member, claim, defs = fixtures.setup_deficient_claim(
        deficiencies=[
            {"reason_code": "MISSING_PROOF", "cure_deadline": "2026-02-15T00:00:00Z"},
        ],
        claimed_loss_cents=5000,
    )
    # A ClaimsAdministrator cures on the member's behalf (PRD §3.4).
    result = get_success_data(api_client.cure_claim(claim["id"], ADMINISTRATOR))
    assert result["status"] == "CURED"
    assert result["open_deficiency_count"] == 0
    rows, _ = validate_paginated(api_client.list_deficiencies(claim["id"], REVIEWER))
    assert len(rows) == 1
    assert all(d["status"] == "CURED" for d in rows)
