"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_public_body(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert 1 <= data["quorum_size"] <= data["seat_count"]


def assert_meeting(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "NOTICED", "IN_SESSION", "ADJOURNED", "CANCELLED"]
    assert data["minutes_status"] in ["NONE", "DRAFT", "APPROVED", "AMENDED"]


def assert_agenda_item(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "OPEN", "CLOSED", "CANCELLED"]
    assert data["item_type"] in ["ACTION", "DISCUSSION", "CONSENT"]


def assert_speaker_slip(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "QUEUED", "CALLED", "SPOKEN", "YIELDED", "WITHDRAWN", "EXPIRED"]


def assert_motion(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "OPEN", "CARRIED", "FAILED", "TABLED", "VOIDED"]
    assert_vote_tally_invariant(data)


def assert_records_request(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "RECEIVED", "UNDER_REVIEW", "GRANTED", "PARTIALLY_GRANTED",
        "DENIED", "CLOSED", "WITHDRAWN"]
    assert data["decision"] in [
        "NONE", "GRANTED", "PARTIALLY_GRANTED", "DENIED"]


def assert_document(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "IDENTIFIED", "REVIEWED", "RELEASED", "REDACTED",
        "EXEMPT", "DISPOSED", "CANCELLED"]


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "UPHELD", "OVERTURNED", "REMANDED"]


# ---- domain invariants ------------------------------------------------------

def assert_fee_ledger_invariant(data: dict):
    """PRD §2.9: assessed_fee == waiver + payments + balance for a determined request."""
    assessed = data["assessed_fee_cents"]
    waived = data["amount_waived_cents"]
    paid = data["amount_paid_cents"]
    balance = data["fee_balance_cents"]
    assert assessed == waived + paid + balance, (
        f"ledger conservation broken: assessed={assessed} != waived={waived} "
        f"+ paid={paid} + balance={balance}")


def assert_vote_tally_invariant(data: dict):
    """PRD §3.5: ballot_count == yea + nay + abstain + recused."""
    total = (data["yea_count"] + data["nay_count"]
             + data["abstain_count"] + data["recused_count"])
    assert data["ballot_count"] == total, (
        f"ballot_count {data['ballot_count']} != sum of value counts {total}")
