"""Domain assertions derived from the PRD's invariants and formulae.

Only rules the PRD states are encoded here; anything the specification leaves
open is not asserted.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ALLEGATION_BASE_SCORE,
    ASSESSMENT_PERCENT,
    CE_BASE_HOURS,
    CE_BLOCK_MONTHS,
    CE_ESCALATION_HOURS_PER_BLOCK,
    CE_HOUR_CAP,
    BOOK_BASIS_SENTINEL_CUTOFF,
    CE_MAKEUP_PER_HOUR_CENTS,
    CE_MONTH_DAYS,
    HARM_TERM_CAP,
    HARM_UNIT_CENTS,
    LATE_PERIOD_CAP,
    LATE_SURCHARGE_PER_PERIOD_CENTS,
    POSTURE_BUMP_COMPLIANT,
    POSTURE_BUMP_RESTRICTED_OR_FROZEN,
    POSTURE_BUMP_WATCH,
    PRIORITY_SCORE_CAP,
    PRIOR_POINTS_PER_SANCTION,
    PRIOR_TERM_CAP,
    REINSTATEMENT_BASE_CENTS,
    REQUEST_ID_PREFIX,
    SHORTAGE_RESTRICT_THRESHOLD_CENTS,
)


# --------------------------------------------------------------- envelope

def assert_envelope(body: Dict[str, Any], expected_response_type: str) -> None:
    """The response envelope's `meta` block and `response_type` discriminator."""
    assert "meta" in body, "response must carry a meta block"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        "api_request_id must be prefixed with 'req_'"
    )
    timestamp = meta.get("api_request_timestamp")
    assert isinstance(timestamp, str)
    assert is_iso8601_timestamp(timestamp), "api_request_timestamp must be ISO-8601"
    assert meta.get("response_type") == expected_response_type


def assert_error_payload(body: Dict[str, Any], expected_error_id: str) -> None:
    """An error response's `data` block names the error and carries a message."""
    assert_envelope(body, "error")
    data = body["data"]
    assert data.get("error_id") == expected_error_id
    assert isinstance(data.get("message"), str) and data["message"], (
        "an error must carry a human-readable message"
    )


# ------------------------------------------------------------ shared shape

def assert_audit_triple(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """`created_at`, `updated_at` and an integer `version` that starts at 1."""
    assert is_valid_uuid(entity["id"]), "id must be an unprefixed UUID"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, saw {entity['version']}"
        )


def assert_immutable_row(entity: Dict[str, Any]) -> None:
    """Ledger entries and course completions carry only `id` and `created_at`."""
    assert is_valid_uuid(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity, "this record carries no updated_at"
    assert "version" not in entity, "this record carries no version"


def assert_license_number(license_number: str, person_type: str) -> None:
    """`SP-` or `BR-` followed by a six-digit zero-padded counter."""
    prefix = "SP-" if person_type == "SALESPERSON" else "BR-"
    assert license_number.startswith(prefix), (
        f"a {person_type} licence number must begin with {prefix}"
    )
    suffix = license_number[len(prefix):]
    assert len(suffix) == 6 and suffix.isdigit(), (
        "the licence number's counter is zero-padded to six digits"
    )


def assert_case_number(case_number: str) -> None:
    """`CMP-` followed by a six-digit zero-padded global counter."""
    assert case_number.startswith("CMP-")
    suffix = case_number[4:]
    assert len(suffix) == 6 and suffix.isdigit()


# ---------------------------------------------------- trust-account figures

def expected_book_figures(entries: List[Dict[str, Any]], as_of_date: Optional[str] = None):
    """The three figures the account stores, derived from the ledger.

    Obligation is the opened amounts less the released amounts; available cash
    is deposits less disbursements plus corrections; the shortage is the excess
    of obligation over available cash, floored at zero.  The stored triple
    applies no date filter, which is the sentinel cut-off `9999-12-31`.
    """
    cutoff = as_of_date or BOOK_BASIS_SENTINEL_CUTOFF
    obligation = 0
    available = 0
    for entry in entries:
        if entry["effective_date"] > cutoff:
            continue
        kind = entry["entry_type"]
        amount = entry["amount_cents"]
        if kind == "OBLIGATION_OPENED":
            obligation += amount
        elif kind == "OBLIGATION_RELEASED":
            obligation -= amount
        elif kind == "DEPOSIT":
            available += amount
        elif kind == "DISBURSEMENT":
            available -= amount
        elif kind == "CORRECTION":
            available += amount
    return obligation, available, max(0, obligation - available)


def expected_bank_basis_shortage(
    entries: List[Dict[str, Any]], as_of_date: str, cleared_through_date: str
) -> int:
    """The bank-basis shortage: only cleared cash counts, obligations do not filter on clearing."""
    cash_cutoff = min(as_of_date, cleared_through_date)
    obligation = 0
    available = 0
    for entry in entries:
        kind = entry["entry_type"]
        amount = entry["amount_cents"]
        if kind in ("OBLIGATION_OPENED", "OBLIGATION_RELEASED"):
            if entry["effective_date"] > as_of_date:
                continue
            obligation += amount if kind == "OBLIGATION_OPENED" else -amount
            continue
        cleared = entry.get("cleared_date")
        if not cleared or cleared > cash_cutoff:
            continue
        if kind == "DEPOSIT":
            available += amount
        elif kind == "DISBURSEMENT":
            available -= amount
        elif kind == "CORRECTION":
            available += amount
    return max(0, obligation - available)


def assert_book_position(account: Dict[str, Any], obligation: int, available: int) -> None:
    """The stored account agrees with the ledger-derived book position."""
    assert account["book_obligation_cents"] == obligation, (
        f"book obligation expected {obligation}, saw {account['book_obligation_cents']}"
    )
    assert account["book_available_cents"] == available, (
        f"book available expected {available}, saw {account['book_available_cents']}"
    )
    assert account["shortage_cents"] == max(0, obligation - available), (
        "the shortage is the obligation less available cash, floored at zero"
    )


def expected_posture(
    open_shortage_cents: int,
    overdue_remediation_count: int,
    open_complaint_count: int,
    frozen: bool = False,
) -> str:
    """First-match-wins evaluation of the brokerage's four posture tiers."""
    if frozen:
        return "FROZEN"
    if open_shortage_cents >= SHORTAGE_RESTRICT_THRESHOLD_CENTS or overdue_remediation_count > 0:
        return "RESTRICTED"
    if open_shortage_cents > 0 or open_complaint_count >= 3:
        return "WATCH"
    return "COMPLIANT"


def assert_posture(brokerage: Dict[str, Any], expected: str) -> None:
    assert brokerage["supervision_posture"] == expected, (
        f"supervision posture expected {expected}, saw {brokerage['supervision_posture']}"
    )


# ------------------------------------------------------------ priority score

def expected_priority_score(
    allegation_type: str,
    alleged_loss_cents: int,
    prior_sanction_count: int = 0,
    supervision_posture: Optional[str] = None,
    include_prior_and_posture: bool = False,
) -> int:
    """The complaint priority score under the intake or investigation variant.

    The intake variant sums the allegation base and the harm term only; the
    investigation variant adds the prior-discipline term and the posture bump.
    Both are capped at 100.
    """
    score = ALLEGATION_BASE_SCORE[allegation_type]
    score += min(alleged_loss_cents // HARM_UNIT_CENTS, HARM_TERM_CAP)
    if include_prior_and_posture:
        score += min(prior_sanction_count * PRIOR_POINTS_PER_SANCTION, PRIOR_TERM_CAP)
        if supervision_posture in ("RESTRICTED", "FROZEN"):
            score += POSTURE_BUMP_RESTRICTED_OR_FROZEN
        elif supervision_posture == "WATCH":
            score += POSTURE_BUMP_WATCH
        else:
            score += POSTURE_BUMP_COMPLIANT
    return min(score, PRIORITY_SCORE_CAP)


# ------------------------------------------- continuing education and fees

def expected_ce_hours_required(license_status: str, inactive_seconds: int = 0) -> int:
    """The escalating CE requirement for a parked or expired licence."""
    if license_status not in ("INACTIVE", "EXPIRED"):
        return CE_BASE_HOURS
    thirty_day_months = inactive_seconds // (CE_MONTH_DAYS * 86400)
    blocks = thirty_day_months // CE_BLOCK_MONTHS
    return min(CE_BASE_HOURS + CE_ESCALATION_HOURS_PER_BLOCK * blocks, CE_HOUR_CAP)


def expected_reinstatement_fee_cents(ce_hours_required: int, inactive_seconds: int) -> int:
    """Base plus CE make-up plus the per-period-rounded late surcharge."""
    makeup = CE_MAKEUP_PER_HOUR_CENTS * (ce_hours_required - CE_BASE_HOURS)
    periods = min(inactive_seconds // (CE_MONTH_DAYS * 86400), LATE_PERIOD_CAP)
    surcharge = LATE_SURCHARGE_PER_PERIOD_CENTS * periods
    return REINSTATEMENT_BASE_CENTS + makeup + surcharge


def assert_ce_standing(licensee: Dict[str, Any], valid: int, required: int) -> None:
    """Both CE figures and the deficiency flag they imply."""
    assert licensee["ce_hours_valid"] == valid, (
        f"ce_hours_valid expected {valid}, saw {licensee['ce_hours_valid']}"
    )
    assert licensee["ce_hours_required"] == required, (
        f"ce_hours_required expected {required}, saw {licensee['ce_hours_required']}"
    )
    assert licensee["ce_deficient"] is (valid < required), (
        "ce_deficient is true exactly when valid hours fall short of the requirement"
    )


# ------------------------------------------------------- recovery fund

def assert_fund_identity(fund: Dict[str, Any]) -> None:
    """The fund's stated balance identity holds at every observable moment."""
    expected = (
        fund["appropriated_cents"]
        + fund["fine_credits_cents"]
        + fund["clawed_back_cents"]
        - fund["awarded_cents"]
        - fund["assessment_cents"]
    )
    assert fund["balance_cents"] == expected, (
        "balance_cents must equal appropriated + fine credits + clawed back "
        f"- awarded - assessment ({expected}), saw {fund['balance_cents']}"
    )


def assert_fund_counters(fund: Dict[str, Any], **expected: int) -> None:
    for field, value in expected.items():
        assert fund[field] == value, f"{field} expected {value}, saw {fund[field]}"
    assert_fund_identity(fund)


def expected_assessment_cents(total_awarded_cents: int) -> int:
    """Two percent of the round's awards, rounded half up to a whole cent."""
    doubled = total_awarded_cents * ASSESSMENT_PERCENT
    return (doubled + 50) // 100
