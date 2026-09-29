"""Payload factories — one per resource, carrying only client-supplied fields."""

DEFAULTS = {
    "REGISTRAR_NAME": "Northwind Registrar",
    "REGISTRAR_EMAIL": "abuse@northwind.example",
    "REGISTRANT_NAME_PUBLIC": "Privacy Proxy Holder",
    "REGISTRANT_EMAIL_PUBLIC": "holder@proxy.example",
    "REGISTRATION_DATE": "2020-01-01T00:00:00Z",
    "EXPIRY_DATE": "2027-01-01T00:00:00Z",
    "COMPLAINANT_NAME": "Marque SA",
    "COMPLAINANT_COUNTRY": "FR",
    "COMPLAINANT_EMAIL": "ip@marque.example",
    "MUTUAL_JURISDICTION": "US",
    "ASSERTION_TEXT": (
        "The disputed domain is confusingly similar to the complainant's "
        "registered mark and was acquired in bad faith."
    ),
    "DRAFT_SUMMARY": (
        "The panel finds the disputed domain confusingly similar to the "
        "complainant's mark and orders the requested remedy."
    ),
    "CONTENT_SUMMARY": (
        "The respondent denies bad faith and asserts a legitimate business "
        "interest in the disputed domain name."
    ),
}


def registrar_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["REGISTRAR_NAME"],
        "iana_id": "IANA-1001",
        "contact_email": DEFAULTS["REGISTRAR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def domain_payload(registrar_id: str, domain_name: str = "disputed.example", **overrides) -> dict:
    payload = {
        "domain_name": domain_name,
        "registrar_id": registrar_id,
        "registrant_name_public": DEFAULTS["REGISTRANT_NAME_PUBLIC"],
        "registrant_email_public": DEFAULTS["REGISTRANT_EMAIL_PUBLIC"],
        "registration_date": DEFAULTS["REGISTRATION_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def complainant_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["COMPLAINANT_NAME"],
        "country_code": DEFAULTS["COMPLAINANT_COUNTRY"],
        "email": DEFAULTS["COMPLAINANT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def panelist_payload(**overrides) -> dict:
    payload = {
        "full_name": "Anna Bauer",
        "nationality_code": "DE",
        "roster_admitted_at": "2019-01-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def case_payload(complainant_id: str, domain_id: str, **overrides) -> dict:
    payload = {
        "complainant_id": complainant_id,
        "domain_id": domain_id,
        "mutual_jurisdiction": DEFAULTS["MUTUAL_JURISDICTION"],
        "remedy_requested": "TRANSFER",
    }
    payload.update(overrides)
    return payload


def ground_payload(ground_type: str, evidence_count: int = 2, **overrides) -> dict:
    payload = {
        "ground_type": ground_type,
        "assertion_text": DEFAULTS["ASSERTION_TEXT"],
        "evidence_count": evidence_count,
    }
    if ground_type == "TRADEMARK_RIGHTS":
        payload["mark_registration_number"] = "EM-0099123"
        payload["mark_jurisdiction"] = "FR"
        payload["similarity_claim"] = "CONFUSINGLY_SIMILAR"
    payload.update(overrides)
    return payload


def fee_transaction_payload(amount_cents: int, **overrides) -> dict:
    payload = {
        "kind": "FILING_FEE",
        "payer": "COMPLAINANT",
        "amount_cents": amount_cents,
        "reference": "WIRE-0001",
    }
    payload.update(overrides)
    return payload


def deficiency_notice_payload(**overrides) -> dict:
    payload = {"deficiency_codes": ["MISSING_SIGNATURE"]}
    payload.update(overrides)
    return payload


def correction_payload(notice_id: str, **overrides) -> dict:
    payload = {"notice_id": notice_id, "correction_notes": "Signature page added."}
    payload.update(overrides)
    return payload


def verification_response_payload(**overrides) -> dict:
    payload = {
        "lock_applied": True,
        "verified_registrant_name": "True Registrant Ltd",
        "verified_registrant_email": "registrant@true.example",
    }
    payload.update(overrides)
    return payload


def notification_payload(channel: str = "EMAIL", **overrides) -> dict:
    payload = {"channel": channel, "address": "registrant@true.example"}
    payload.update(overrides)
    return payload


def delivery_payload(outcome: str = "DELIVERED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def response_payload(respondent_email: str = "registrant@true.example", **overrides) -> dict:
    payload = {
        "respondent_email": respondent_email,
        "content_summary": DEFAULTS["CONTENT_SUMMARY"],
    }
    payload.update(overrides)
    return payload


def appointment_payload(seat: str, expected_case_version: int, **overrides) -> dict:
    payload = {
        "seat": seat,
        "nominated_by": "PROVIDER",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def conflict_screening_payload(**overrides) -> dict:
    payload = {
        "disclosed_prior_representation": False,
        "disclosed_same_firm": False,
        "disclosed_financial_interest": False,
        "prior_appointments_with_complainant": 0,
    }
    payload.update(overrides)
    return payload


def waiver_payload(**overrides) -> dict:
    payload = {"waiver_complainant": True, "waiver_respondent": True}
    payload.update(overrides)
    return payload


def replace_payload(**overrides) -> dict:
    payload = {"reason": "Seat vacated by the provider."}
    payload.update(overrides)
    return payload


def decision_payload(expected_case_version: int, drafted_by_panelist_id: str, **overrides) -> dict:
    payload = {
        "expected_case_version": expected_case_version,
        "drafted_by_panelist_id": drafted_by_panelist_id,
        "draft_summary": DEFAULTS["DRAFT_SUMMARY"],
    }
    payload.update(overrides)
    return payload


def vote_payload(seat: str, vote: str, **overrides) -> dict:
    payload = {"seat": seat, "vote": vote}
    payload.update(overrides)
    return payload


def publish_payload(redaction_level: str = "NONE", **overrides) -> dict:
    payload = {"redaction_level": redaction_level, "precedent_tags": ["identical_mark"]}
    payload.update(overrides)
    return payload


def court_challenge_payload(filed_by: str = "RESPONDENT", **overrides) -> dict:
    payload = {
        "jurisdiction": "US",
        "docket_number": "1:26-cv-00811",
        "filed_by": filed_by,
    }
    payload.update(overrides)
    return payload


def resolve_challenge_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_note": "Court disposition recorded."}
    payload.update(overrides)
    return payload
