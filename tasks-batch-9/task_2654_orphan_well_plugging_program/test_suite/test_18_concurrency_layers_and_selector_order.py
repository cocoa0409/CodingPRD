"""Where an observed version, a second dimension and a pinned pool order interact."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_ids_exactly,
    assert_null_fields,
    assert_page,
)
from test_helpers.constants import CANONICAL_JOB_ESTIMATE


def test_a_site_access_write_invalidates_the_version_a_determination_carries(api):
    """The observed version is spent by a write to the other dimension of the row.

    Opening a surface-access request touches nothing the determination cares about, but it
    increments the same row's version, so the create carrying the version observed at well
    creation is refused; the identical call carrying the re-read version is accepted.

    PRD: "If it does not equal the well's current `version`, the create is rejected with
    `ERR_STALE_WELL_VERSION` (HTTP 412)." ... "The well's access dimension mirrors the new
    row, moving `NO_ACCESS_REQUESTED → ACCESS_PENDING` or, when a previous attempt was
    refused, `ACCESS_DENIED → ACCESS_PENDING`, and the well's `version` increments." ... "The
    two dimensions never constrain one another: a well may be `ACCESS_PENDING` while still
    `PRODUCING`"

    Design: Corner/cross_cutting_complexity_layers/stale_well_version_blocks_the_determination_create_and_a_reread_unblocks_it
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    well = fx.make_well(api, operator["id"], api_well_number="49-001-26001")
    assert_fields(
        well, version=1, status="PRODUCING", access_status="NO_ACCESS_REQUESTED"
    )
    observed_version = well["version"]

    fx.open_site_access(api, well["id"], mode="AGREEMENT")
    after_access = fx.read_well(api, well["id"])
    assert_fields(
        after_access, version=2, access_status="ACCESS_PENDING", status="PRODUCING"
    )

    validate_error(
        api.create_orphan_determination(
            well["id"],
            f.determination_payload(observed_version),
            users.INSPECTOR,
        ),
        e.ERR_STALE_WELL_VERSION,
        412,
    )
    assert_page(
        api.list_well_orphan_determinations(well["id"], users.INSPECTOR),
        0,
        expected_total=0,
    )
    unchanged = fx.read_well(api, well["id"])
    assert_fields(
        unchanged, version=2, status="PRODUCING", access_status="ACCESS_PENDING"
    )

    determination = validate_success(
        api.create_orphan_determination(
            well["id"],
            f.determination_payload(unchanged["version"]),
            users.INSPECTOR,
        ),
        201,
    )
    assert_fields(determination, status="DRAFT", well_id=well["id"], revision_round=0)
    assert_null_fields(determination, "submitted_at", "decided_at", "decided_by_user_id")
    assert_ids_exactly(
        assert_page(
            api.list_well_orphan_determinations(well["id"], users.INSPECTOR),
            1,
            expected_total=1,
        ),
        [determination["id"]],
    )
    reclassified = fx.read_well(api, well["id"])
    assert_fields(reclassified, status="INACTIVE", access_status="ACCESS_PENDING")


def test_two_enforcement_actions_cannot_be_driven_from_one_observation(api):
    """The second action needs its own read even though it is a declared edge.

    Declaring insolvency at version 1 is legal and leaves version 2, so the bond forfeiture
    replayed at version 1 is refused with nothing minted, and the same forfeiture at the
    re-read version carries the four-hop cascade through.

    PRD: "A mismatch with the operator's current `version` is rejected with
    `ERR_STALE_OPERATOR_VERSION` (HTTP 412). Successive enforcement actions against one
    operator are each individually legal - a declaration of insolvency followed by a bond
    forfeiture, or a revocation after a bond deficiency - so no state precondition would
    reject the second action." ... "First, a new funding source is created with `kind`
    `FORFEITED_BOND`, `name` formed as the literal text `FORFEITED BOND ` followed by the
    operator's `name`, `authorized_cents` equal to the operator's pre-forfeiture
    `bond_amount_cents`, `bond_operator_id` set to this operator, `allowable_cost_categories`
    set to `PLUGGING` and `RECLAMATION`, `expires_at` set to the logical clock plus 3650 days
    (a ten-year obligation term), and `status` `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/successive_enforcement_actions_each_require_a_freshly_read_operator_version
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=400000,
    )
    assert_fields(operator, version=1, status="ACTIVE")
    stale_version = operator["version"]

    insolvent = validate_success(
        api.operator_enforcement(
            operator["id"],
            f.enforcement_payload("DECLARE_INSOLVENT", stale_version, "receiver appointed"),
            users.ADMIN,
        ),
        200,
    )
    assert_fields(insolvent, status="INSOLVENT", version=2)

    validate_error(
        api.operator_enforcement(
            operator["id"],
            f.enforcement_payload("FORFEIT_BOND", stale_version),
            users.ADMIN,
        ),
        e.ERR_STALE_OPERATOR_VERSION,
        412,
    )
    held = fx.read_operator(api, operator["id"])
    assert_fields(held, status="INSOLVENT", version=2)
    assert_cents(held["bond_amount_cents"], 400000, "bond_amount_cents")
    assert_null_fields(held, "bond_forfeited_at")
    assert_page(
        api.list_funding_sources(users.FUNDING, {"kind": "FORFEITED_BOND"}),
        0,
        expected_total=0,
    )

    revoked = validate_success(
        api.operator_enforcement(
            operator["id"],
            f.enforcement_payload("FORFEIT_BOND", held["version"]),
            users.ADMIN,
        ),
        200,
    )
    assert_fields(
        revoked,
        status="REVOKED",
        version=3,
        bond_forfeited_at="2026-08-01T00:00:00Z",
    )
    assert_cents(revoked["bond_amount_cents"], 0, "bond_amount_cents after forfeiture")

    minted = assert_page(
        api.list_funding_sources(users.FUNDING, {"kind": "FORFEITED_BOND"}),
        1,
        expected_total=1,
    )[0]
    assert_fields(
        minted,
        kind="FORFEITED_BOND",
        name="FORFEITED BOND Cottonwood Energy LLC",
        bond_operator_id=operator["id"],
        expires_at="2036-07-29T00:00:00Z",
        status="ACTIVE",
    )
    assert_cents(minted["authorized_cents"], 400000, "authorized_cents")


def test_the_pool_ranks_the_soonest_expiry_and_breaks_ties_on_creation(api):
    """Within one kind the order is expiry first, creation second, size never.

    Three state funds of different sizes and expiries are offered to a 6070196 need: the
    smaller of the two funds sharing the sooner expiry takes rank 1 because it was created a
    day earlier, the larger one covers the remainder at rank 2, and the fund with the later
    expiry is never reached even though it was created first.

    PRD: "then, within a kind, by `expires_at` ascending, so authority that is about to lapse
    is used first; then by `created_at` ascending. The row `id` is never part of the
    ordering." ... "A source that does contribute produces one allocation carrying its
    `source_id`, the contributed `allocated_cents`, and a `waterfall_rank` recording the
    1-based position that source occupied in the ordered list." ... "any source whose
    `committed_cents` thereby reaches `authorized_cents` flips `ACTIVE → EXHAUSTED`"

    Design: Corner/cross_cutting_complexity_layers/same_kind_funding_sources_are_ordered_by_expiry_then_by_creation
    """
    bundle = fx.make_scheduled_job(api)
    job = bundle["job"]
    assert_cents(
        job["plugging_cost_estimate_cents"],
        CANONICAL_JOB_ESTIMATE,
        "plugging_cost_estimate_cents",
    )

    late = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Late expiry small fund",
        authorized_cents=1000000,
        expires_at="2027-06-30T00:00:00Z",
    )
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    soon_first = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Soon expiry medium fund",
        authorized_cents=2000000,
        expires_at="2027-01-31T00:00:00Z",
    )
    fx.set_clock(api, "2026-08-03T00:00:00Z")
    soon_second = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Soon expiry large fund",
        authorized_cents=10000000,
        expires_at="2027-01-31T00:00:00Z",
    )
    assert_fields(late, created_at="2026-08-01T00:00:00Z")
    assert_fields(soon_first, created_at="2026-08-02T00:00:00Z")
    assert_fields(soon_second, created_at="2026-08-03T00:00:00Z")

    allocations = fx.commit_funding(api, job["id"])
    assert len(allocations) == 2, "expected exactly two allocations: %r" % (allocations,)
    by_rank = {row["waterfall_rank"]: row for row in allocations}
    assert sorted(by_rank) == [1, 2], "expected the ranks 1 and 2, got %r" % (
        sorted(row["waterfall_rank"] for row in allocations),
    )

    assert_fields(by_rank[1], source_id=soon_first["id"], status="COMMITTED")
    assert_cents(by_rank[1]["allocated_cents"], 2000000, "rank 1 allocated_cents")
    assert_fields(by_rank[2], source_id=soon_second["id"], status="COMMITTED")
    assert_cents(by_rank[2]["allocated_cents"], 4070196, "rank 2 allocated_cents")
    assert by_rank[1]["source_id"] != soon_second["id"], (
        "rank 1 must be the earlier created fund, not the larger balance"
    )

    exhausted = fx.read_source(api, soon_first["id"])
    assert_cents(exhausted["committed_cents"], 2000000, "soon_first committed_cents")
    assert_fields(exhausted, status="EXHAUSTED")

    partial = fx.read_source(api, soon_second["id"])
    assert_cents(partial["committed_cents"], 4070196, "soon_second committed_cents")
    assert_fields(partial, status="ACTIVE")

    untouched = fx.read_source(api, late["id"])
    assert_cents(untouched["committed_cents"], 0, "late committed_cents")
    assert_fields(untouched, status="ACTIVE")

    assert 2000000 + 4070196 == CANONICAL_JOB_ESTIMATE, "the two ranks must cover the need"
    assert_cents(
        fx.read_job(api, job["id"])["funded_cents"], CANONICAL_JOB_ESTIMATE, "funded_cents"
    )
