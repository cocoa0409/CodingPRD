"""Payload factories — one per creatable resource, input fields only (PRD §3-§4)."""

DEFAULTS = {
    "TOTAL_SHARES_AUTHORIZED": 1_000_000,
    "FULL_NAME": "Dr Test",
    "HIRE_DATE": "2015-01-01T00:00:00Z",
    "SEAT_CLASS": "AT_LARGE",
    "TERM_START": "2026-08-01T00:00:00Z",
    "TERM_END": "2029-08-01T00:00:00Z",
    "COMMITTEE_NAME": "Quality Committee",
    "COMMITTEE_TYPE": "QUALITY",
    "QUORUM_COUNT": 1,
    "APPROVAL_THRESHOLD": "SIMPLE_MAJORITY",
    "DUE_DATE": "2026-08-20T00:00:00Z",
    "PURPOSE": "General purposes",
    "COUNTERPARTY_NAME": "Regional Health",
    "EXCHANGE_RATIO_X1000": 1250,
    "CASH_CONSIDERATION_CENTS": 900000000,
    "DESCRIPTION": "Conflict disclosure",
}


def create_policy_payload(**overrides) -> dict:
    payload = {"total_shares_authorized": DEFAULTS["TOTAL_SHARES_AUTHORIZED"]}
    payload.update(overrides)
    return payload


def create_physician_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FULL_NAME"],
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    payload.update(overrides)
    return payload


def set_standing_payload(standing: str, **overrides) -> dict:
    payload = {"standing": standing}
    payload.update(overrides)
    return payload


def create_board_seat_payload(**overrides) -> dict:
    payload = {
        "seat_label": "SEAT-1",
        "seat_class": DEFAULTS["SEAT_CLASS"],
    }
    payload.update(overrides)
    return payload


def appoint_seat_payload(physician_id: str, **overrides) -> dict:
    payload = {
        "physician_id": physician_id,
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_committee_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COMMITTEE_NAME"],
        "committee_type": DEFAULTS["COMMITTEE_TYPE"],
        "quorum_count": DEFAULTS["QUORUM_COUNT"],
        "approval_threshold": DEFAULTS["APPROVAL_THRESHOLD"],
    }
    payload.update(overrides)
    return payload


def add_member_payload(physician_id: str, committee_role: str = "MEMBER") -> dict:
    return {"physician_id": physician_id, "committee_role": committee_role}


def create_buy_in_offer_payload(physician_id: str, **overrides) -> dict:
    payload = {
        "physician_id": physician_id,
        "target_tier": "PARTNER_TRACK",
        "share_grant": 0,
        "installment_count": 1,
    }
    payload.update(overrides)
    return payload


def respond_offer_payload(decision: str) -> dict:
    return {"decision": decision}


def pay_installment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


# --- Motion payload builders (PRD §3.4 payload shapes pinned by type) -------


def capital_call_payload(amount_cents: int, due_date: str = None, purpose: str = None) -> dict:
    return {
        "amount_cents": amount_cents,
        "due_date": due_date or DEFAULTS["DUE_DATE"],
        "purpose": purpose or DEFAULTS["PURPOSE"],
    }


def distribution_payload(
    amount_cents: int,
    method: str = "PRO_RATA",
    fiscal_net_income_before_bonus_cents: int = 800000000,
) -> dict:
    return {
        "amount_cents": amount_cents,
        "method": method,
        "fiscal_net_income_before_bonus_cents": fiscal_net_income_before_bonus_cents,
    }


def charter_amendment_payload(**overrides) -> dict:
    return dict(overrides)


def comp_policy_payload(new_bonus_pool_pct: float) -> dict:
    return {"new_bonus_pool_pct": new_bonus_pool_pct}


def buyout_approval_payload(exit_valuation_id: str) -> dict:
    return {"exit_valuation_id": exit_valuation_id}


def merger_motion_payload(merger_proposal_id: str) -> dict:
    return {"merger_proposal_id": merger_proposal_id}


def create_motion_payload(
    motion_type: str,
    sponsor_physician_id: str,
    payload: dict,
    committee_id: str = None,
    supersedes_motion_id: str = None,
    **overrides,
) -> dict:
    body = {
        "motion_type": motion_type,
        "sponsor_physician_id": sponsor_physician_id,
        "payload": payload,
    }
    if committee_id is not None:
        body["committee_id"] = committee_id
    if supersedes_motion_id is not None:
        body["supersedes_motion_id"] = supersedes_motion_id
    body.update(overrides)
    return body


def vote_payload(vote_choice: str) -> dict:
    return {"vote_choice": vote_choice}


def pay_assessment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_exit_valuation_payload(physician_id: str, trigger_type: str = "VOLUNTARY") -> dict:
    return {"physician_id": physician_id, "trigger_type": trigger_type}


def appraise_payload(appraised_practice_value_cents: int, expected_valuation_version: int) -> dict:
    return {
        "appraised_practice_value_cents": appraised_practice_value_cents,
        "expected_valuation_version": expected_valuation_version,
    }


def finalize_payload(motion_id: str) -> dict:
    return {"motion_id": motion_id}


def create_coi_disclosure_payload(
    description: str = None, related_motion_id: str = None
) -> dict:
    payload = {"description": description or DEFAULTS["DESCRIPTION"]}
    if related_motion_id is not None:
        payload["related_motion_id"] = related_motion_id
    return payload


def review_coi_payload(outcome: str, review_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def create_merger_proposal_payload(**overrides) -> dict:
    payload = {
        "counterparty_name": DEFAULTS["COUNTERPARTY_NAME"],
        "exchange_ratio_x1000": DEFAULTS["EXCHANGE_RATIO_X1000"],
        "cash_consideration_cents": DEFAULTS["CASH_CONSIDERATION_CENTS"],
    }
    payload.update(overrides)
    return payload
