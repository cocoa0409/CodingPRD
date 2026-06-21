"""Screening-hit disposition lifecycle, confirmability, and conservation."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_customer_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]


# ==========================================================================
# Queue A — compensating_invariant (open_hit_count escalate/reopen)
# ==========================================================================
def test_open_hit_count_conserved_escalate_then_reopen(api):
    """PRD §2.12: "The first is `open_hit_count`: the number of that customer's
    screening hits whose `disposition` is either `PENDING` or `ESCALATED`."
    PRD §3.5: "An `ESCALATED` hit can be walked back: reopening it returns the
    hit to `PENDING` for re-review."

    Both PENDING and ESCALATED are counted, so an ESCALATE then reopen round trip
    leaves open_hit_count unchanged (net-zero).

    Design: Difficulty/compensating_invariant/open_hit_count_conserved_escalate_then_reopen
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Inv Co", date_of_birth="1991-01-01"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Inv Co", "match_score": 0.97}, CO), 201)
    before = validate_success(api.get_customer(cid, CO))
    assert before["open_hit_count"] == 1

    escalated = validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    assert escalated["disposition"] == "ESCALATED"
    reopened = validate_success(api.reopen_hit(hit["id"], CO))
    assert reopened["disposition"] == "PENDING"

    after = validate_success(api.get_customer(cid, CO))
    assert after["open_hit_count"] == 1, f"open_hit_count not conserved: {after['open_hit_count']}"


def test_open_hit_count_decrements_on_false_positive(api):
    """PRD §2.12: "The first is `open_hit_count`: the number of that customer's
    screening hits whose `disposition` is either `PENDING` or `ESCALATED`."
    PRD §3.5: "Reaching `FALSE_POSITIVE` recomputes the customer's
    `open_hit_count` (decrementing it) and recomputes `edd_required`."

    A PENDING (counted) hit dispositioned FALSE_POSITIVE (not counted) drops
    open_hit_count from 1 to 0 — distinguishing the conserved round trip above
    from a true decrement.

    Design: Difficulty/compensating_invariant/open_hit_count_conserved_escalate_then_reopen
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Fp Co", date_of_birth="1992-02-02"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "PEP", "matched_name": "Fp Co", "match_score": 0.50}, CO), 201)
    assert validate_success(api.get_customer(cid, CO))["open_hit_count"] == 1
    fp = validate_success(api.disposition_hit(hit["id"], {"decision": "FALSE_POSITIVE"}, CO))
    assert fp["disposition"] == "FALSE_POSITIVE"
    assert validate_success(api.get_customer(cid, CO))["open_hit_count"] == 0


# ==========================================================================
# Queue A — priority_pair_validation_conflict (state beats business_safety)
# ==========================================================================
def test_state_beats_safety_on_confirm_terminal_hit(api):
    """PRD §2.7: "State-machine legality of a requested transition
    (`ERR_INVALID_STATE`) is then checked for all transition endpoints, and the
    optimistic-concurrency version check (`ERR_STALE_VERSION`) follows the state
    check on the two endpoints that carry a version. The remaining business-
    safety, referential, temporal, fiscal, and decision-validity rules described
    in §3 are each evaluated after these".

    A CONFIRM on a hit already in terminal FALSE_POSITIVE (state check, priority
    7) takes precedence over the non-confirmable business-safety check (priority
    10) -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_confirm_terminal_hit
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Pri Co", date_of_birth="1970-07-07"), CO), 201)
    cid = customer["id"]
    # PEP hit at 0.50: non-derogatory AND below CONFIRM_FLOOR — also non-confirmable.
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "PEP", "matched_name": "Pri Co", "match_score": 0.50}, CO), 201)
    fp = validate_success(api.disposition_hit(hit["id"], {"decision": "FALSE_POSITIVE"}, CO))
    assert fp["disposition"] == "FALSE_POSITIVE"
    validate_error(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_low_score_hit_not_confirmable(api):
    """PRD §3.5: "An `ESCALATED` hit can instead be confirmed, moving it to the
    terminal `CONFIRMED` state, but confirmation is permitted only when the hit
    is derogatory and its `match_score` is at least 0.95. Attempting to confirm a
    hit that is not derogatory, or whose `match_score` is below 0.95, is rejected
    with `ERR_HIT_NOT_CONFIRMABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_confirm_terminal_hit
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="LowScore", date_of_birth="1989-09-09"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "LowScore", "match_score": 0.80}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    validate_error(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO),
                   ApiErrorId.ERR_HIT_NOT_CONFIRMABLE.value)


# ==========================================================================
# Queue B — screening-hit corner instances
# ==========================================================================
def test_confirm_not_confirmable_low_score_409(api):
    """PRD §3.5: "Attempting to confirm a hit that is not derogatory, or whose
    `match_score` is below 0.95, is rejected with `ERR_HIT_NOT_CONFIRMABLE`."

    Design: Corner/state_machines/hit_confirm_not_confirmable_low_score_excluded
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="LowScore2", date_of_birth="1989-09-09"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "LowScore2", "match_score": 0.80}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    validate_error(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO),
                   ApiErrorId.ERR_HIT_NOT_CONFIRMABLE.value)


def test_reopen_pending_hit_returns_invalid_state(api):
    """PRD §3.5: "An `ESCALATED` hit can be walked back: reopening it returns the
    hit to `PENDING` for re-review."
    PRD §3.5: "A disposition or reopen attempted from a state in which the
    requested edge is not defined is rejected with `ERR_INVALID_STATE`."

    Reopen is defined only from ESCALATED; a PENDING hit reopen -> ERR_INVALID_STATE.

    Design: Corner/state_machines/reopen_pending_hit_returns_invalid_state
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Reop Co", date_of_birth="1992-02-02"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Reop Co", "match_score": 0.97}, CO), 201)
    validate_error(api.reopen_hit(hit["id"], CO), ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_decision_value_returns_422(api):
    """PRD §3.5: "The decision value supplied to a hit disposition must be one of
    `FALSE_POSITIVE`, `ESCALATE`, or `CONFIRM`; any other value is rejected with
    `ERR_INVALID_DECISION`."

    Design: Corner/validations/invalid_decision_value_returns_422
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Dec Co", date_of_birth="1997-07-07"), CO), 201)
    cid = customer["id"]
    hit = validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Dec Co", "match_score": 0.97}, CO), 201)
    validate_error(api.disposition_hit(hit["id"], {"decision": "MAYBE"}, CO),
                   ApiErrorId.ERR_INVALID_DECISION.value)


def test_open_hits_block_clearance_409(api):
    """PRD §3.1: "An attempt to clear screening while `open_hit_count` is greater
    than zero, or while the rating is `PROHIBITED`, is rejected with
    `ERR_OPEN_HITS_BLOCK_CLEARANCE`."

    Design: Corner/validations/open_hits_block_clearance_409
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=3, product_factor=2, pep_factor=3, adverse_media_factor=2),
        date_of_birth="1996-06-06")
    cid = rated["id"]
    assert rated["risk_rating"] == "MEDIUM"
    validate_success(api.create_screening_hit(
        cid, {"list_type": "OFAC_SDN", "matched_name": "Block Co", "match_score": 0.97}, CO), 201)
    validate_error(api.clear_screening(cid, CO), ApiErrorId.ERR_OPEN_HITS_BLOCK_CLEARANCE.value)


def test_ubo_screen_hit_creates_screening_hit(api):
    """PRD §3.4: "A `HIT` outcome sets `screening_status` to `HIT` and, in
    addition, creates a `ScreeningHit` whose `beneficial_owner_id` points at this
    owner and whose `disposition` begins at `PENDING`".
    PRD §3.5: "a hit is derogatory when its `list_type` is `OFAC_SDN` or
    `EU_SANCTIONS` (a true-positive sanctions match)".

    Design: Corner/endpoints/ubo_screen_hit_creates_screening_hit
    """
    cust = fx.create_legal_entity(legal_name="UboHit Co", incorporation_date="1992-02-02")
    ubo = validate_success(api.create_beneficial_owner(
        cust["id"], {"full_name": "UBO One", "ownership_pct": 30.00,
                     "country_code": "IR", "is_control_person": True}, CO), 201)
    screened = validate_success(api.screen_beneficial_owner(
        ubo["id"], {"outcome": "HIT", "list_type": "OFAC_SDN",
                    "matched_name": "UBO One", "match_score": 0.98}, CO))
    assert screened["screening_status"] == "HIT"
    hits, _ = fx._list(api.list_bo_screening_hits(ubo["id"], CO))
    assert hits[0]["beneficial_owner_id"] == ubo["id"]
    assert hits[0]["is_derogatory"] is True
