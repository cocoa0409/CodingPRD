"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "customer id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["wallet_credit_cents"], int)
    assert 0 <= data["risk_score"] <= 100, "risk_score is an integer in 0..100"
    assert isinstance(data["approved_claim_count"], int)
    assert isinstance(data["pending_claim_count"], int)


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "order id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["fulfillment_status"] in (
        "QUOTED",
        "AWAITING_MEDIA",
        "RECEIVED",
        "PROCESSING",
        "READY",
    )
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED")
    assert isinstance(data["estimate_total_cents"], int)
    assert isinstance(data["version"], int)


def assert_media_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "media item id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["media_type"] in ("TAPE", "FILM", "PHOTO", "AUDIO")
    assert data["status"] in (
        "LOGGED",
        "PREPPED",
        "SCANNING",
        "QC_PENDING",
        "QC_FAIL",
        "OUTPUT_READY",
        "WRITTEN_OFF",
    )
    assert isinstance(data["qc_attempts"], int) and data["qc_attempts"] >= 0


def assert_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "batch id must be a valid UUID"
    assert data["status"] in ("OPEN", "LOADED", "RUNNING", "COMPLETED", "FAILED")
    assert isinstance(data["loaded_count"], int) and data["loaded_count"] >= 0


def assert_output_artifact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "artifact id must be a valid UUID"
    assert data["output_type"] in ("CLOUD", "USB", "DVD")
    assert data["status"] in ("AVAILABLE", "REVOKED", "EXPIRED")
    assert isinstance(data["download_count"], int) and data["download_count"] >= 0


def assert_damage_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "claim id must be a valid UUID"
    assert data["claim_type"] in ("LOST", "DAMAGED")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED")
    assert isinstance(data["payout_cents"], int)


def assert_qc_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "qc review id must be a valid UUID"
    assert data["decision"] in ("PASS", "FAIL")
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_download_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "download event id must be a valid UUID"
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1


def assert_refund_conserves_cents(payout_cents: int, refunded_delta: int, wallet_delta: int):
    """The claim payout is conserved: the amount credited to the customer's
    wallet equals the amount added to the order's refund equals the payout."""
    assert payout_cents == refunded_delta == wallet_delta, (
        f"cents not conserved: payout={payout_cents}, refunded_delta={refunded_delta}, "
        f"wallet_delta={wallet_delta}"
    )
