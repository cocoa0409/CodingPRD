"""Request-body builders.

Each builder returns only the fields a client is allowed to supply for that
endpoint; server-computed fields are never included. Every builder accepts
keyword overrides so a test can pin an exact value.
"""
import itertools

from test_helpers.constants import CONCESSION, TEST_DEFAULTS

_SEQUENCE = itertools.count(1)


def _next_seq():
    return next(_SEQUENCE)


def unique_nmls_id():
    """A six-to-eight digit NMLS unique identifier not used by another test."""
    return "9{:06d}".format(_next_seq() % 1_000_000)


def unique_course_code():
    """A globally unique catalogue code, four to twenty-four characters."""
    return "CE-COURSE-{:05d}".format(_next_seq())


def unique_license_number():
    """A state-issued licence number, four to thirty-two characters."""
    return "LIC-{:06d}".format(_next_seq())


def unique_exam_reference():
    """A globally unique regulator examination reference."""
    return "EXAM-REF-{:05d}".format(_next_seq())


def unique_borrower_reference():
    """An opaque borrower file reference."""
    return "BORROWER-{:05d}".format(_next_seq())


JUSTIFICATION_40 = (
    "Documented compliance basis for this entry, retained for examination review."
)
JUSTIFICATION_120 = (
    "Documented compliance basis for this pricing decision, retained in full for "
    "state examination review, describing the rate sheet error, the corrective "
    "credit applied and the supervisory sign-off obtained."
)
VARIABLE_JUSTIFICATION = (
    "Measures the originator's own production effort rather than any term of the "
    "transaction, per the compensation design policy."
)


def build_originator(**overrides):
    """Payload for registering an originator (PRD 3.1)."""
    payload = {
        "nmls_unique_id": unique_nmls_id(),
        "legal_name": "Jordan Avery Blake",
        "hire_date": "2026-01-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def build_license_registration(originator_id, **overrides):
    """Payload for filing a state licence (PRD 3.1)."""
    payload = {
        "originator_id": originator_id,
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "license_number": unique_license_number(),
        "issue_date": "2026-02-01T00:00:00Z",
        "expiration_date": "2027-01-31T00:00:00Z",
        "renewal_window_opens_at": "2026-11-01T00:00:00Z",
        "ce_reporting_year": TEST_DEFAULTS["CE_REPORTING_YEAR"],
    }
    payload.update(overrides)
    return payload


def build_sponsorship_transfer(expected_license_registration_version, **overrides):
    """Payload for claiming sponsorship of a licence (PRD 3.1, 2.7)."""
    payload = {
        "sponsoring_institution_code": TEST_DEFAULTS["INSTITUTION_CODE"],
        "effective_at": "2026-08-01T00:00:00Z",
        "expected_license_registration_version": expected_license_registration_version,
    }
    payload.update(overrides)
    return payload


def build_license_status_action(action, **overrides):
    """Payload for a surrender, revocation or reinstatement (PRD 3.1, 3.2)."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def build_ce_course(**overrides):
    """Payload for adding a course to the catalogue (PRD 3.2)."""
    payload = {
        "course_code": unique_course_code(),
        "credit_hours": 3,
        "category": "FEDERAL_LAW",
    }
    payload.update(overrides)
    return payload


def build_ce_credit(originator_id, ce_course_id, **overrides):
    """Payload for filing a continuing-education credit (PRD 3.2)."""
    payload = {
        "originator_id": originator_id,
        "ce_course_id": ce_course_id,
        "completion_date": "2026-06-15T00:00:00Z",
        "reporting_period_year": TEST_DEFAULTS["CE_REPORTING_YEAR"],
    }
    payload.update(overrides)
    return payload


def build_compensation_plan(**overrides):
    """Payload for drafting a compensation plan (PRD 3.3)."""
    payload = {
        "plan_name": "Retail Production Plan {:04d}".format(_next_seq()),
        "base_basis_points": TEST_DEFAULTS["BASE_BASIS_POINTS"],
        "min_fee_cents": TEST_DEFAULTS["MIN_FEE_CENTS"],
        "max_fee_cents": TEST_DEFAULTS["MAX_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def build_compensation_variable(**overrides):
    """Payload for declaring a pay variable on a draft plan (PRD 3.3)."""
    payload = {
        "variable_type": "LOAN_VOLUME_UNITS",
        "weight_pct": 100,
        "justification_text": VARIABLE_JUSTIFICATION,
    }
    payload.update(overrides)
    return payload


def build_plan_decision(decision, **overrides):
    """Payload for a plan approval or rejection (PRD 3.3)."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def build_plan_assignment(compensation_plan_id, expected_originator_version, **overrides):
    """Payload for assigning a plan over a closed interval (PRD 3.3, 2.7)."""
    payload = {
        "compensation_plan_id": compensation_plan_id,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-12-31T00:00:00Z",
        "expected_originator_version": expected_originator_version,
    }
    payload.update(overrides)
    return payload


def build_loan_application(originator_id, **overrides):
    """Payload for taking a loan application (PRD 3.4)."""
    payload = {
        "originator_id": originator_id,
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "borrower_reference": unique_borrower_reference(),
        "product_type": TEST_DEFAULTS["PRODUCT_TYPE"],
        "requested_amount_cents": TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "par_rate_bps": TEST_DEFAULTS["PAR_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def build_loan_lock(**overrides):
    """Payload for locking the rate (PRD 3.4)."""
    payload = {
        "note_rate_bps": TEST_DEFAULTS["PAR_RATE_BPS"],
        "locked_amount_cents": TEST_DEFAULTS["LOCKED_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def build_loan_close(**overrides):
    """Payload for closing a locked loan (PRD 3.5)."""
    payload = {
        "funded_amount_cents": TEST_DEFAULTS["FUNDED_AMOUNT_CENTS"],
        "funded_at": "2026-08-01T00:00:00Z",
        "lender_paid_comp_cents": 0,
        "borrower_paid_comp_cents": 0,
        "file_quality_score": TEST_DEFAULTS["FILE_QUALITY_SCORE"],
        "hours_worked_pct": TEST_DEFAULTS["HOURS_WORKED_PCT"],
    }
    payload.update(overrides)
    return payload


def build_loan_payoff(payoff_date, **overrides):
    """Payload for posting a payoff (PRD 3.7)."""
    payload = {"payoff_date": payoff_date}
    payload.update(overrides)
    return payload


def build_pricing_exception(**overrides):
    """Payload for requesting a pricing exception (PRD 3.6)."""
    payload = {
        "requested_rate_bps": 625,
        "concession_cents": 100_000,
        "reason_code": "COMPETITIVE_MATCH",
        "justification_text": JUSTIFICATION_40,
    }
    payload.update(overrides)
    return payload


def build_pricing_exception_decision(decision, **overrides):
    """Payload for deciding a pricing exception (PRD 3.6)."""
    payload = {
        "decision": decision,
        "decision_note": "Reviewed against the rate sheet and the concession cap.",
    }
    payload.update(overrides)
    return payload


def build_advertisement(originator_id, **overrides):
    """Payload for drafting an advertisement (PRD 3.8)."""
    payload = {
        "originator_id": originator_id,
        "medium": "PRINT",
        "content_text": "Home financing tailored to your family. Speak with our team today.",
        "target_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
    }
    payload.update(overrides)
    return payload


def build_advertisement_review(decision, **overrides):
    """Payload for reviewing an advertisement (PRD 3.8)."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def build_advertisement_revision(content_text, **overrides):
    """Payload for revising a rejected advertisement (PRD 3.8)."""
    payload = {"content_text": content_text}
    payload.update(overrides)
    return payload


def build_examination_inquiry(**overrides):
    """Payload for logging an examination inquiry (PRD 3.9)."""
    payload = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "exam_reference": unique_exam_reference(),
        "response_due_at": "2026-09-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def build_examination_response(**overrides):
    """Payload for filing an examination response (PRD 3.9)."""
    payload = {
        "narrative": "The requested licence and compensation records are enclosed in full.",
    }
    payload.update(overrides)
    return payload


def build_examination_info_request(**overrides):
    """Payload for recording a regulator's further-information request (PRD 3.9)."""
    payload = {"request_note": "Regulator asks for the sponsorship interval history."}
    payload.update(overrides)
    return payload


def build_investigation(loan_application_id, **overrides):
    """Payload for manually opening an investigation (PRD 3.9)."""
    payload = {
        "loan_application_id": loan_application_id,
        "trigger_reason": "MANUAL_REFERRAL",
    }
    payload.update(overrides)
    return payload


def build_investigation_finding(finding, restitution_cents, **overrides):
    """Payload for entering an investigation finding (PRD 3.9)."""
    payload = {"finding": finding, "restitution_cents": restitution_cents}
    payload.update(overrides)
    return payload


def build_investigation_remediation(**overrides):
    """Payload for recording remediation of a substantiated case (PRD 3.9)."""
    payload = {"remediation_note": "Restitution paid to the borrower and evidenced."}
    payload.update(overrides)
    return payload


def build_clock(to_iso8601):
    """Payload for moving the logical compliance clock (PRD 2.4)."""
    return {"to_iso8601": to_iso8601}


def text_of_length(length, filler="a"):
    """A filler string of exactly `length` characters."""
    return filler * length


def justification_for_pricing_error():
    """A justification long enough for the heightened PRICING_ERROR floor."""
    return JUSTIFICATION_120


def max_concession_for(locked_amount_cents):
    """The largest concession the per-loan cap permits on this loan (PRD 3.6)."""
    return (locked_amount_cents * CONCESSION["CAP_NUMERATOR"]) // CONCESSION["CAP_DENOMINATOR"]
