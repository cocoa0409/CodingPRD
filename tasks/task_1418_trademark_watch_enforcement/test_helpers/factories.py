"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Brands",
        "industry": "consumer goods",
        "enforcement_budget_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(client_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "client_id": client_id,
        "mark_text": f"ACME-{n}",
        "mark_type": "WORD",
        "jurisdiction": "US",
        "nice_classes": [9],
        "application_number": f"US-90{n}",
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(trademark_record_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "trademark_record_id": trademark_record_id,
        "source": "WATCH_SERVICE",
        "conflicting_mark_text": f"AKME-{n}",
        "conflicting_owner": "Rival Co",
        "conflicting_classes": [9],
        "similarity_mark": 80,
        "similarity_goods": 70,
        "similarity_channels": 60,
    }
    defaults.update(overrides)
    return defaults


def assess_payload(expected_watch_alert_version, **overrides) -> dict:
    defaults = {
        "weight_mark": 0.6,
        "weight_goods": 0.3,
        "weight_channels": 0.1,
        "fame_adjustment": 5,
        "rationale": "strong",
        "expected_watch_alert_version": expected_watch_alert_version,
    }
    defaults.update(overrides)
    return defaults


def docket_deadline_payload(**overrides) -> dict:
    defaults = {
        "deadline_type": "RESPONSE_DUE",
        "statutory_basis": "37 CFR 2.196",
        "basis_date": "2026-08-07T09:00:00Z",
        "offset_days": 5,
    }
    defaults.update(overrides)
    return defaults


def draft_letter_payload(**overrides) -> dict:
    defaults = {
        "demand_type": "CEASE_USE",
        "recipient_name": "Rival Co",
        "recipient_address": "1 Rival Way",
        "response_due_days": 14,
    }
    defaults.update(overrides)
    return defaults


def takedown_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "platform": "META",
        "listing_url": f"https://meta.example/shop/{n}",
        "basis": "COUNTERFEIT",
    }
    defaults.update(overrides)
    return defaults


def agreement_payload(**overrides) -> dict:
    defaults = {
        "counterparty_name": "Rival Co",
        "territory_codes": ["US"],
        "effective_start": "2026-09-01T00:00:00Z",
        "effective_end": "2027-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def propose_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "terms_text": "terms",
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def evidence_payload(**overrides) -> dict:
    defaults = {
        "nice_class": 9,
        "specimen_type": "LABEL",
        "specimen_date": "2031-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def maintenance_filing_payload(**overrides) -> dict:
    defaults = {
        "filing_type": "SECTION_8",
        "evidence_item_ids": [],
    }
    defaults.update(overrides)
    return defaults


def clearance_search_payload(client_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "client_id": client_id,
        "proposed_mark": f"ACMEPRO-{n}",
        "proposed_classes": [9],
    }
    defaults.update(overrides)
    return defaults


def recordation_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "customs_authority": "US_CBP",
        "recordation_number": f"CBP-{n}",
        "term_start": "2026-08-15T00:00:00Z",
        "term_end": "2027-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def referral_payload(**overrides) -> dict:
    defaults = {
        "referral_channel": "LAW_ENFORCEMENT",
        "seizure_lines": [{"units": 2, "unit_value_cents": 5000}],
    }
    defaults.update(overrides)
    return defaults
