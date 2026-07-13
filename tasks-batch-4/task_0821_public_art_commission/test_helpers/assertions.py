"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "BUDGET_CERTIFIED")
    assert isinstance(data["art_budget_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["uncommitted_cents"], int)


def assert_budget_invariant(data: dict):
    """art_budget_cents == uncommitted_cents + committed_cents (PRD §2.7)."""
    assert data["art_budget_cents"] == data["uncommitted_cents"] + data["committed_cents"], (
        f"budget invariant broken: art={data['art_budget_cents']} "
        f"uncommitted={data['uncommitted_cents']} committed={data['committed_cents']}"
    )


def assert_commission(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "AWARDED", "CONTRACTED", "FULFILLED", "CANCELLED")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETED")


def assert_payment_invariant(data: dict):
    """contract_amount_cents == paid_cents + remaining_cents (PRD §2.7)."""
    assert data["contract_amount_cents"] == data["paid_cents"] + data["remaining_cents"], (
        f"payment invariant broken: amount={data['contract_amount_cents']} "
        f"paid={data['paid_cents']} remaining={data['remaining_cents']}"
    )


def assert_submission(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "REVISION_REQUESTED", "SCORED", "DISQUALIFIED",
        "AWARDED", "REJECTED", "WITHDRAWN",
    )


def assert_score(data: dict):
    _assert_common(data)
    for f in ("artistic_merit", "feasibility", "community_impact", "durability"):
        assert 0 <= data[f] <= 100


def assert_artwork(data: dict):
    _assert_common(data)
    assert data["location_status"] in ("FABRICATION", "FABRICATED", "INSTALLED", "DEACCESSIONED")
    assert data["condition_status"] in ("GOOD", "FAIR", "POOR", "NEEDS_TREATMENT")


def assert_site(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "OCCUPIED")


def assert_conservation_record(data: dict):
    """Append-only event log: only id + created_at are guaranteed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ConservationRecord is append-only; must not carry version"
    assert "updated_at" not in data, "ConservationRecord is append-only; must not carry updated_at"
