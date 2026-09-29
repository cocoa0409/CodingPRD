"""Clock-driven expiry, and the four hops each caused by the one before it."""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_premium_transaction

STORAGE_PART_PLAN = (
    ("TEMPORARY_STORAGE", 400000000),
    ("SOFT_COST", 300000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def _account_with_storage_and_open_endorsement():
    """An in-force policy holding stored material and an undecided endorsement."""
    facility = fx.register_facility(
        name="Northgate Bonded Warehouse",
        site_code="STG-NORTH-01",
        distance_from_site_miles=42.5,
        aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED",
    )
    account = fx.in_force_account(parts=STORAGE_PART_PLAN)
    assignment = fx.assign_storage(
        account, facility, 300000000,
        "2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")
    endorsement = fx.file_endorsement(account, 30)
    return account, facility, assignment, endorsement


def test_expiring_the_policy_releases_stored_material_and_frees_the_shared_facility():
    """Advancing the clock to or past term_end_date expires the policy, and the
    cascade then closes its ACTIVE coverage parts, releases its APPROVED storage
    assignments with a release_reason of POLICY_EXPIRY, and recomputes
    committed_value_cents on every facility those assignments referenced. The
    facility is never named in the triggering call.

    Design: Difficulty/transitive_cascade/clock_expiry_cascades_policy_parts_storage_and_facility
    """
    account, facility, assignment, _ = _account_with_storage_and_open_endorsement()

    before = get_success_data(api_client.get_facility(facility["id"], fx.RE))
    assert before["committed_value_cents"] == 300000000, before

    fx.set_clock("2027-07-01T00:00:00Z")

    policy = account.refresh_policy()
    assert policy["status"] == "EXPIRED", policy["status"]

    for part_type, part in account.refresh_parts().items():
        assert part["status"] == "CLOSED", f"{part_type} stayed {part['status']}"

    released = get_success_data(api_client.get_storage_assignment(
        assignment["id"], fx.UW))
    assert released["status"] == "RELEASED", released["status"]
    assert released["release_reason"] == "POLICY_EXPIRY", released["release_reason"]
    assert released["released_at"] == "2027-07-01T00:00:00Z", released["released_at"]

    after = get_success_data(api_client.get_facility(facility["id"], fx.RE))
    assert after["committed_value_cents"] == 0, after["committed_value_cents"]


def test_the_expiry_sweep_reports_its_counters_and_lapses_the_open_endorsement_unpriced():
    """The sweep reports what it did through expired_policy_count,
    closed_coverage_part_count, released_assignment_count and
    lapsed_endorsement_count, and it lapses every REQUESTED endorsement without
    writing any ledger entry, so the premium ledger still holds only the
    INITIAL row written at binding.

    Design: Difficulty/transitive_cascade/clock_expiry_cascades_policy_parts_storage_and_facility
    """
    account, _, _, endorsement = _account_with_storage_and_open_endorsement()

    counters = fx.set_clock("2027-07-01T00:00:00Z")

    assert counters["expired_policy_count"] == 1, counters
    assert counters["closed_coverage_part_count"] == 3, (
        "all three ACTIVE parts of the expiring policy close, " f"got {counters}")
    assert counters["released_assignment_count"] == 1, counters
    assert counters["lapsed_endorsement_count"] == 1, counters

    lapsed = get_success_data(api_client.get_extension_endorsement(
        endorsement["id"], fx.UW))
    assert lapsed["status"] == "LAPSED", lapsed["status"]

    ledger = fx.premium_ledger(account)
    assert len(ledger) == 1, f"a lapsed endorsement posts nothing: {ledger}"
    assert_premium_transaction(ledger[0], txn_type="INITIAL")
