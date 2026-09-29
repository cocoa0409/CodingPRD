"""Payload factories -- one per create endpoint, client-supplied fields only."""

from .constants import TEST_DEFAULTS as D


def _merged(defaults: dict, overrides: dict) -> dict:
    merged = dict(defaults)
    merged.update(overrides)
    return merged


def create_station_payload(**overrides) -> dict:
    """Minimal registration supplies only call_sign, licensee_name and market_code."""
    return _merged(
        {
            "call_sign": "WTST-TV",
            "licensee_name": "Test Licensee LLC",
            "market_code": "DMA-100",
        },
        overrides,
    )


def create_election_payload(station_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "office_sought": "US Senate",
            "election_type": "PRIMARY",
            "election_date": D["ELECTION_DATE"],
        },
        overrides,
    )


def create_advertiser_payload(station_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "legal_name": D["ISSUE_LEGAL_NAME"],
            "requested_class": "ISSUE",
        },
        overrides,
    )


def create_candidate_advertiser_payload(station_id, election_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "legal_name": D["CANDIDATE_LEGAL_NAME"],
            "requested_class": "CANDIDATE",
            "election_id": election_id,
            "candidate_name": "Dana Rivera",
            "office_sought": "US Senate",
            "qualification_evidence_ref": "FEC-F2-2026-0088",
        },
        overrides,
    )


def create_rate_class_payload(station_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "class_code": "RC-EN",
            "daypart": "EARLY_NEWS",
            "preemptible": True,
            "preemption_priority": 2,
            "posted_rate_cents": D["POSTED_RATE_EARLY_NEWS"],
        },
        overrides,
    )


def create_order_payload(station_id, advertiser_id, rate_class_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "advertiser_id": advertiser_id,
            "rate_class_id": rate_class_id,
            "payment_terms": "PREPAY",
            "sponsorship_disclosure_text": "PAID FOR BY " + D["ISSUE_LEGAL_NAME"],
            "disclosure_duration_seconds": D["DISCLOSURE_DURATION_SECONDS"],
            "agency_placed": False,
        },
        overrides,
    )


def create_spot_payload(**overrides) -> dict:
    return _merged(
        {
            "air_date": D["AIR_DATE"],
            "start_offset_seconds": 0,
            "duration_seconds": 30,
            "program_code": "EN-1",
        },
        overrides,
    )


def order_decision_payload(decision="ACCEPT", **overrides) -> dict:
    return _merged({"decision": decision}, overrides)


def payment_payload(direction, amount_cents, expected_order_version, **overrides) -> dict:
    return _merged(
        {
            "direction": direction,
            "amount_cents": amount_cents,
            "expected_order_version": expected_order_version,
        },
        overrides,
    )


def luc_determination_payload(rate_class_id, variant, expected_election_version, **ov) -> dict:
    return _merged(
        {
            "rate_class_id": rate_class_id,
            "variant": variant,
            "expected_election_version": expected_election_version,
        },
        ov,
    )


def eo_request_payload(station_id, requesting_advertiser_id, trigger_order_id, **ov) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "requesting_advertiser_id": requesting_advertiser_id,
            "trigger_order_id": trigger_order_id,
        },
        ov,
    )


def complaint_payload(station_id, **overrides) -> dict:
    return _merged(
        {
            "station_id": station_id,
            "complainant_name": "Ida Brennan",
            "allegation_code": "FILE_TIMELINESS",
            "narrative": "Political file entries were not posted within one business day.",
        },
        overrides,
    )


def complaint_response_payload(response_text, remedy_code, **overrides) -> dict:
    return _merged(
        {"response_text": response_text, "remedy_code": remedy_code}, overrides
    )
