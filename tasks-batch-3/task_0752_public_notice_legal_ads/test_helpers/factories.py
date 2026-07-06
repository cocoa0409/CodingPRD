"""Payload factories — one per entity, input fields only."""

# A 80-char body: word_count == 15, and at chars_per_line == 40, line_count == 2.
PROBATE_BODY_80 = "PUBLIC NOTICE: The estate of John Doe is in probate; creditors must file by date"
# A body whose length ceils to 3 lines at chars_per_line == 40 (100-char foreclosure copy).
FORECLOSURE_BODY_100 = (
    "NOTICE OF FORECLOSURE SALE. The property secured by the deed of trust "
    "will be sold at auction today."
)


def create_newspaper_payload(**overrides) -> dict:
    defaults = {
        "name": "Springfield Times",
        "county": "SPRINGFIELD",
        "circulation_qualified": True,
        "pricing_basis": "PER_LINE",
        "chars_per_line": 40,
        "line_rate_first_cents": 500,
        "line_rate_subsequent_cents": 300,
        "word_rate_cents": 50,
        "affidavit_fee_cents": 2500,
        "edition_line_capacity": 100,
        "publication_weekday": 6,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Law",
        "account_type": "LAW_FIRM",
        "credit_limit_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_statutory_requirement_payload(**overrides) -> dict:
    defaults = {
        "notice_type": "PROBATE",
        "county": "SPRINGFIELD",
        "min_insertions": 2,
        "min_days_before_deadline": 5,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(account_id, newspaper_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "newspaper_id": newspaper_id,
        "notice_type": "PROBATE",
        "county": "SPRINGFIELD",
        "title": "Estate of John Doe",
        "body_text": PROBATE_BODY_80,
        "deadline_date": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


def schedule_notice_payload(first_publication_date, expected_notice_version, **overrides) -> dict:
    defaults = {
        "first_publication_date": first_publication_date,
        "expected_notice_version": expected_notice_version,
    }
    defaults.update(overrides)
    return defaults


def add_insertion_payload(scheduled_date, **overrides) -> dict:
    defaults = {"scheduled_date": scheduled_date}
    defaults.update(overrides)
    return defaults


def publish_insertion_payload(line_count_actual, **overrides) -> dict:
    defaults = {"line_count_actual": line_count_actual}
    defaults.update(overrides)
    return defaults


def issue_affidavit_payload(sworn_by="Pat Publisher", **overrides) -> dict:
    defaults = {"sworn_by": sworn_by}
    defaults.update(overrides)
    return defaults


def payment_payload(invoice_id, amount_cents, **overrides) -> dict:
    defaults = {"invoice_id": invoice_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
