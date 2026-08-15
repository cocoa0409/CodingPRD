"""Review session close: quorum tally and Item lifecycle transitions (PRD §3.3)."""
from db import db
from errors import (
    raise_error,
    ERR_INCOMPLETE_AGENDA,
    ERR_NO_QUORUM_REACHED,
)
from services.common import touch
from util import program_clock_iso


def _active_verdicts(session_id, item_id):
    return [
        v
        for v in db["review_verdicts"].values()
        if v["session_id"] == session_id and v["item_id"] == item_id and not v["soft_deleted"]
    ]


def tally_outcome(verdicts, quorum_size):
    """Quorum tally with strict evaluation order (scaffold §1.3 session_quorum_tally):
    ACCEPT first; then REJECT iff it reaches quorum AND dominates ACCEPT+REVISE;
    then REVISE quorum; a contested REJECT de-escalates to REVISE."""
    n_a = sum(1 for v in verdicts if v["verdict"] == "ACCEPT")
    n_r = sum(1 for v in verdicts if v["verdict"] == "REJECT")
    n_v = sum(1 for v in verdicts if v["verdict"] == "REVISE")
    if n_a >= quorum_size:
        return "ACCEPT"
    if n_r >= quorum_size and n_r >= (n_a + n_v):
        return "REJECT"
    if n_v >= quorum_size:
        return "REVISE"
    if n_r >= quorum_size and n_r < (n_a + n_v):
        return "REVISE"
    return None


def _cascade_variants_rejected(item):
    for variant in db["item_variants"].values():
        if variant["item_id"] == item["id"] and variant["status"] not in ("APPROVED", "REJECTED"):
            variant["status"] = "REJECTED"
            touch(variant)


def cascade_item_terminal_variants(item):
    """An item that becomes REJECTED or RETIRED drags non-terminal variants to REJECTED."""
    _cascade_variants_rejected(item)


def _apply_content_outcome(item, outcome):
    if outcome == "ACCEPT":
        item["status"] = "BIAS_REVIEW"
        item["content_review_outcome"] = "PASSED"
    elif outcome == "REVISE":
        item["content_review_outcome"] = "REVISE"
        item["revision_cycle_count"] += 1
        if item["revision_cycle_count"] > 3:
            item["status"] = "REJECTED"
            _cascade_variants_rejected(item)
        else:
            item["status"] = "DRAFT"
    elif outcome == "REJECT":
        item["status"] = "REJECTED"
        item["content_review_outcome"] = "FAILED"
        item["retirement_reason"] = "CONTENT_DEPRECATED"
        _cascade_variants_rejected(item)
    touch(item)


def _apply_bias_outcome(item, outcome, program):
    if outcome == "ACCEPT":
        item["status"] = "FIELD_TEST_ELIGIBLE"
        item["bias_review_outcome"] = "PASSED"
        item["security_posture"] = "SECURED"
    elif outcome == "REVISE":
        item["bias_review_outcome"] = "REVISE"
        item["revision_cycle_count"] += 1
        item["status"] = "DRAFT"
    elif outcome == "REJECT":
        item["status"] = "REJECTED"
        item["bias_review_outcome"] = "FAILED"
        item["retirement_reason"] = "BIAS_CONFIRMED"
        _cascade_variants_rejected(item)
    touch(item)


def close_session(session, program, committee):
    """Close an OPEN session: verify per-item verdict presence and quorum for the
    whole agenda first (aborting the entire close on any failure), then fire the
    Item lifecycle transitions per tally."""
    agenda = session["agenda_item_ids"]
    tallies = {}
    for item_id in agenda:
        verdicts = _active_verdicts(session["id"], item_id)
        if not verdicts:
            raise_error(
                ERR_INCOMPLETE_AGENDA,
                f"agenda item {item_id} has no verdicts",
            )
        outcome = tally_outcome(verdicts, committee["quorum_size"])
        if outcome is None:
            raise_error(
                ERR_NO_QUORUM_REACHED,
                f"agenda item {item_id} did not reach quorum",
            )
        tallies[item_id] = outcome

    session["status"] = "CLOSED"
    session["closed_at"] = program_clock_iso(program)
    touch(session)

    expected_state = "CONTENT_REVIEW" if committee["committee_kind"] == "CONTENT" else "BIAS_REVIEW"
    for item_id in agenda:
        item = db["items"].get(item_id)
        if item is None or item["status"] != expected_state:
            continue
        outcome = tallies[item_id]
        if committee["committee_kind"] == "CONTENT":
            _apply_content_outcome(item, outcome)
        else:
            _apply_bias_outcome(item, outcome, program)
