"""Request payload factories.

Every factory returns a plain dict of JSON-native values only: ints for cents,
floats for liters, strings for dates.  No money value is ever produced as a
string, because PRD §2.7 says no monetary value is ever represented as a string.
"""

from .constants import (
    CANONICAL_LINE,
    CANONICAL_SHIP_TO,
    CARRIER_PROGRAM_GSO_TX,
    CONSUMER_ADA,
    PERMIT_TX_2026,
    STATE_RULE_NM,
    STATE_RULE_TX,
    WINERY_ESTATE_1,
)


def _merge(base, overrides):
    payload = dict(base)
    payload.update(overrides or {})
    return payload


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def winery_payload(**overrides):
    return _merge(WINERY_ESTATE_1, overrides)


def winery_status_payload(status, suspension_reason=None):
    payload = {"status": status}
    if suspension_reason is not None:
        payload["suspension_reason"] = suspension_reason
    return payload


def state_rule_payload(**overrides):
    return _merge(STATE_RULE_TX, overrides)


def state_rule_nm_payload(**overrides):
    return _merge(STATE_RULE_NM, overrides)


def prohibited_zip_payload(zip_code="78701", reason="DRY_COUNTY",
                           effective_from="2026-01-01", **overrides):
    return _merge(
        {
            "zip_code": zip_code,
            "reason": reason,
            "effective_from": effective_from,
        },
        overrides,
    )


def carrier_program_payload(**overrides):
    return _merge(CARRIER_PROGRAM_GSO_TX, overrides)


def consumer_payload(**overrides):
    return _merge(CONSUMER_ADA, overrides)


def id_verification_payload(method="DOCUMENT"):
    return {"id_verification_method": method}


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------
def state_permit_payload(winery_id, **overrides):
    payload = _merge(PERMIT_TX_2026, overrides)
    payload["winery_id"] = winery_id
    return payload


def file_renewal_payload(renewal_reference="RENEW-1"):
    return {"renewal_reference": renewal_reference}


def approve_renewal_payload(expiration_date):
    return {"expiration_date": expiration_date}


def revoke_payload(revocation_reason="License revoked by the state board"):
    return {"revocation_reason": revocation_reason}


# ---------------------------------------------------------------------------
# Carrier enrollments
# ---------------------------------------------------------------------------
def carrier_enrollment_payload(winery_id, carrier_program_id,
                               expected_winery_version, account_number="ACCT-1",
                               **overrides):
    return _merge(
        {
            "winery_id": winery_id,
            "carrier_program_id": carrier_program_id,
            "account_number": account_number,
            "expected_winery_version": expected_winery_version,
        },
        overrides,
    )


def enrollment_decision_payload(decision, note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def order_line(sku="CAB-750", bottle_ml=750, bottles=6, unit_price_cents=4200):
    return {
        "sku": sku,
        "bottle_ml": bottle_ml,
        "bottles": bottles,
        "unit_price_cents": unit_price_cents,
    }


def canonical_lines(bottles=6, unit_price_cents=4200):
    return [
        order_line(
            sku=CANONICAL_LINE["sku"],
            bottle_ml=CANONICAL_LINE["bottle_ml"],
            bottles=bottles,
            unit_price_cents=unit_price_cents,
        )
    ]


def order_payload(winery_id, consumer_id, expected_consumer_version, lines=None,
                  **overrides):
    payload = {
        "winery_id": winery_id,
        "consumer_id": consumer_id,
        "lines": lines if lines is not None else canonical_lines(),
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(CANONICAL_SHIP_TO)
    payload.update(overrides or {})
    return payload


def compliance_exception_payload(raised_rule, justification="Long-standing member"):
    return {"raised_rule": raised_rule, "justification": justification}


def exception_decision_payload(decision, decision_note=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# ---------------------------------------------------------------------------
# Shipments and scans
# ---------------------------------------------------------------------------
def shipment_payload(order_id, carrier_enrollment_id,
                     replacement_of_shipment_id=None):
    payload = {"order_id": order_id, "carrier_enrollment_id": carrier_enrollment_id}
    if replacement_of_shipment_id is not None:
        payload["replacement_of_shipment_id"] = replacement_of_shipment_id
    return payload


def scan_payload(scan_type, **fields):
    payload = {"scan_type": scan_type}
    payload.update(fields)
    return payload


def pickup_scan():
    return scan_payload("PICKUP")


def exception_scan(exception_code="WEATHER"):
    return scan_payload("EXCEPTION", exception_code=exception_code)


def reroute_scan(reroute_zip, reroute_state_code):
    return scan_payload(
        "REROUTE_ACCEPTED",
        reroute_zip=reroute_zip,
        reroute_state_code=reroute_state_code,
    )


def delivered_scan(signed_by="Ada Buyer", signer_age_verified=True):
    return scan_payload(
        "DELIVERED", signed_by=signed_by, signer_age_verified=signer_age_verified
    )


def return_scan():
    return scan_payload("RETURN_TO_SENDER")


# ---------------------------------------------------------------------------
# Club subscriptions and runs
# ---------------------------------------------------------------------------
def club_subscription_payload(consumer_id, winery_id, next_run_date="2026-08-20",
                              **overrides):
    return _merge(
        {
            "consumer_id": consumer_id,
            "winery_id": winery_id,
            "cadence": "MONTHLY",
            "sku": "CLUB-750",
            "bottles_per_shipment": 6,
            "bottle_ml": 750,
            "unit_price_cents": 2600,
            "next_run_date": next_run_date,
            "annual_allotment": 12,
        },
        overrides,
    )


def weather_hold_payload(hold_start_date, hold_release_date,
                         hold_reason="WEATHER_HEAT"):
    return {
        "hold_start_date": hold_start_date,
        "hold_release_date": hold_release_date,
        "hold_reason": hold_reason,
    }


def release_hold_payload(reset_missed_runs=None):
    if reset_missed_runs is None:
        return {}
    return {"reset_missed_runs": reset_missed_runs}


def club_run_payload(winery_id, run_date, **overrides):
    return _merge({"winery_id": winery_id, "run_date": run_date}, overrides)


# ---------------------------------------------------------------------------
# Volume ledger
# ---------------------------------------------------------------------------
def manual_adjustment_payload(consumer_id, winery_id, liters, state_code="TX",
                              occurred_at="2026-07-15T00:00:00Z",
                              reason="Pre-platform volume for this consumer",
                              **overrides):
    return _merge(
        {
            "consumer_id": consumer_id,
            "winery_id": winery_id,
            "state_code": state_code,
            "liters": liters,
            "occurred_at": occurred_at,
            "reason": reason,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Remittances
# ---------------------------------------------------------------------------
def remittance_payload(winery_id, state_code, period_start, period_end,
                       period_type="MONTHLY", basis="ACCRUAL_BASIS", **overrides):
    return _merge(
        {
            "winery_id": winery_id,
            "state_code": state_code,
            "period_type": period_type,
            "period_start": period_start,
            "period_end": period_end,
            "basis": basis,
        },
        overrides,
    )


def remit_payload(payment_reference="PAY-1"):
    return {"payment_reference": payment_reference}
