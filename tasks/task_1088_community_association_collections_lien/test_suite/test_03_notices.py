"""FDCPA notice lifecycle: dispute/re-send cycle, cooldown window, invalid
transitions, and the automatic-stay block on sending."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]


def _account(api, name):
    assoc, acct = fixtures.setup_account(api, {"name": name})
    return acct


def _draft_notice(api, account_id, notice_type):
    return get_success_data(
        api.create_notice({"account_id": account_id, "notice_type": notice_type}, AGENT))


# --- non_linear_state_machine / nlsm_notice_dispute_cycle (queue A, >=2 tests) ---

def test_notice_resend_restamps_sent_date(api):
    """PRD §3.4: "The agent responds by mailing verification, moving the notice from
    `DISPUTED` back to `SENT`; this resets `sent_date` to now (restarting the validation
    clock) and clears `dispute_date`."

    Design: Difficulty/non_linear_state_machine/nlsm_notice_dispute_cycle
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = _account(api, "Elm HOA")
    notice = _draft_notice(api, acct["id"], "DEMAND")
    validate_success(api.transition_notice(notice["id"], "SENT", AGENT))
    fixtures.set_clock(api, "2026-05-10T00:00:00Z")
    validate_success(api.transition_notice(notice["id"], "DISPUTED", AGENT))
    resent = validate_success(api.transition_notice(notice["id"], "SENT", AGENT))
    assert resent["status"] == "SENT"
    assert resent["sent_date"] == "2026-05-10T00:00:00Z", resent["sent_date"]


def test_notice_resend_clears_dispute_date(api):
    """PRD §3.4: "A notice may therefore cycle `SENT → DISPUTED → SENT` any number of times."
    PRD §3.4: "The agent responds by mailing verification, moving the notice from
    `DISPUTED` back to `SENT`; this resets `sent_date` to now (restarting the validation
    clock) and clears `dispute_date`."

    Design: Difficulty/non_linear_state_machine/nlsm_notice_dispute_cycle
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = _account(api, "Elm HOA")
    notice = _draft_notice(api, acct["id"], "DEMAND")
    validate_success(api.transition_notice(notice["id"], "SENT", AGENT))
    fixtures.set_clock(api, "2026-05-10T00:00:00Z")
    disputed = validate_success(api.transition_notice(notice["id"], "DISPUTED", AGENT))
    assert disputed["status"] == "DISPUTED"
    resent = validate_success(api.transition_notice(notice["id"], "SENT", AGENT))
    assert resent["dispute_date"] is None, resent["dispute_date"]


# --- resource_temporal_overlap / ov_notice_cooldown_halfopen (queue A, >=2 tests) ---

def test_second_same_type_notice_inside_cooldown_rejected(api):
    """PRD §3.4: "the window runs from that prior notice's `sent_date` up to but not including
    `sent_date` plus 30 days (a half-open interval), and any prior notice in `SENT` or
    `DISPUTED` whose window contains now blocks the new send with `ERR_NOTICE_COOLDOWN`."

    Design: Difficulty/resource_temporal_overlap/ov_notice_cooldown_halfopen
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = _account(api, "Dune HOA")
    n1 = _draft_notice(api, acct["id"], "DEMAND")
    validate_success(api.transition_notice(n1["id"], "SENT", AGENT))
    n2 = _draft_notice(api, acct["id"], "DEMAND")
    fixtures.set_clock(api, "2026-05-20T00:00:00Z")
    resp = api.transition_notice(n2["id"], "SENT", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOTICE_COOLDOWN.value)


def test_notice_blocked_by_cooldown_stays_draft(api):
    """PRD §3.4: "A send is blocked, however, if a same-`notice_type` notice already sent on
    the account is still inside its cooldown window"

    Design: Difficulty/resource_temporal_overlap/ov_notice_cooldown_halfopen
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = _account(api, "Dune HOA")
    n1 = _draft_notice(api, acct["id"], "DEMAND")
    validate_success(api.transition_notice(n1["id"], "SENT", AGENT))
    n2 = _draft_notice(api, acct["id"], "DEMAND")
    fixtures.set_clock(api, "2026-05-20T00:00:00Z")
    validate_error(api.transition_notice(n2["id"], "SENT", AGENT),
                   ApiErrorId.ERR_NOTICE_COOLDOWN.value)
    after = get_success_data(api.get_notice(n2["id"], AGENT))
    assert after["status"] == "DRAFT"


# --- Queue B: state_machines / validations ---

def test_notice_draft_to_expired_invalid(api):
    """PRD §3.4: "A `SENT` notice may be moved to `EXPIRED` only once its validation period
    has fully run — (now minus `sent_date`) at least 30 days — else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/notice_invalid_transition_draft_to_expired
    """
    acct = _account(api, "Fig HOA")
    notice = _draft_notice(api, acct["id"], "DEMAND")
    resp = api.transition_notice(notice["id"], "EXPIRED", AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_notice_cooldown_day30_boundary_allowed(api):
    """PRD §3.4: "the window runs from that prior notice's `sent_date` up to but not including
    `sent_date` plus 30 days (a half-open interval), and any prior notice in `SENT` or
    `DISPUTED` whose window contains now blocks the new send with `ERR_NOTICE_COOLDOWN`."

    Design: Corner/validations/notice_cooldown_boundary_day30_allowed
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = _account(api, "Wisp HOA")
    n1 = _draft_notice(api, acct["id"], "DEMAND")
    validate_success(api.transition_notice(n1["id"], "SENT", AGENT))
    n2 = _draft_notice(api, acct["id"], "DEMAND")
    fixtures.set_clock(api, "2026-05-31T00:00:00Z")
    sent = validate_success(api.transition_notice(n2["id"], "SENT", AGENT))
    assert sent["status"] == "SENT"
    assert sent["sent_date"] == "2026-05-31T00:00:00Z", sent["sent_date"]


def test_automatic_stay_blocks_notice_send(api):
    """PRD §3.7: "While the account is in `BANKRUPTCY`, no lien recording, foreclosure
    referral or advance, or notice send is permitted — each is refused with
    `ERR_AUTOMATIC_STAY`."

    Design: Corner/rbac/automatic_stay_blocks_notice_send
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=100000)
    acct_id = base["account"]["id"]
    notice = _draft_notice(api, acct_id, "DEMAND")
    fixtures.file_bankruptcy(api, acct_id, "2026-05-01T00:00:00Z",
                             officer_id="officer-2", chapter="CH13", case_number="26-77")
    resp = api.transition_notice(notice["id"], "SENT", AGENT)
    validate_error(resp, ApiErrorId.ERR_AUTOMATIC_STAY.value)
