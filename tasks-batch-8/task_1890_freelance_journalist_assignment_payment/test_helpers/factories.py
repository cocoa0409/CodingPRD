"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Contributor",
    "BRIEF": "Test brief body",
    "TITLE": "Test Story",
    "WORD_COUNT": 100,
    "DEADLINE": "2026-08-10T00:00:00Z",
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "KILL_FEE_PCT": 25,
    "FLAT_FEE_CENTS": 50000,
    "PER_WORD_RATE_CENTS": 75,
    "TIN_LAST4": "1234",
    "PAY_DATE": "2026-08-20T00:00:00Z",
}


def create_contributor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "email": "contributor@example.com",
        "tax_residency": "DOMESTIC_US",
    }
    defaults.update(overrides)
    return defaults


def create_rate_agreement_payload(**overrides) -> dict:
    defaults = {
        "pricing_mode": "FLAT",
        "flat_fee_cents": DEFAULTS["FLAT_FEE_CENTS"],
        "kill_fee_pct_num": DEFAULTS["KILL_FEE_PCT"],
        "rights_default": "FIRST",
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "contributor_id": "",
        "title": DEFAULTS["TITLE"],
        "brief": DEFAULTS["BRIEF"],
        "commissioned_word_count": DEFAULTS["WORD_COUNT"],
        "deadline_utc": DEFAULTS["DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_expense_claim_payload(**overrides) -> dict:
    defaults = {
        "category": "TRAVEL",
        "requested_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def expense_decision_payload(decision="APPROVE") -> dict:
    return {"decision": decision}


def submit_expense_payload(claimed_cents=1000, receipt_attached=False) -> dict:
    return {"claimed_cents": claimed_cents,
            "receipt_attached": receipt_attached}


def settle_decision_payload(decision="REIMBURSE") -> dict:
    return {"decision": decision}


def record_result_payload(similarity_score_bps=0, ai_probability_bps=0) -> dict:
    return {"similarity_score_bps": similarity_score_bps,
            "ai_probability_bps": ai_probability_bps}


def adjudicate_payload(outcome="DISMISSED",
                       adjudication_note="reviewed") -> dict:
    return {"outcome": outcome, "adjudication_note": adjudication_note}


def create_tax_document_payload(**overrides) -> dict:
    defaults = {
        "doc_kind": "W9",
        "tin_last4": DEFAULTS["TIN_LAST4"],
    }
    defaults.update(overrides)
    return defaults


def tax_doc_decision_payload(decision="VERIFY") -> dict:
    return {"decision": decision}


def create_invoice_payload(fee_claim_cents=0, expense_claim_cents=0) -> dict:
    return {"fee_claim_cents": fee_claim_cents,
            "expense_claim_cents": expense_claim_cents}


def invoice_decision_payload(decision="VERIFY") -> dict:
    return {"decision": decision}


def create_payment_batch_payload(
        scheduled_pay_date=DEFAULTS["PAY_DATE"]) -> dict:
    return {"scheduled_pay_date": scheduled_pay_date}


def add_invoice_payload(invoice_id) -> dict:
    return {"invoice_id": invoice_id}


def release_batch_payload(expected_batch_version) -> dict:
    return {"expected_batch_version": expected_batch_version}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def accept_for_publication_payload(final_word_count=100) -> dict:
    return {"final_word_count": final_word_count}
