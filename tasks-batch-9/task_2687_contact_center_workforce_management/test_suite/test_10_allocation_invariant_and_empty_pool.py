"""The waterfall over an empty candidate pool, and revoke as the exact undo of commit."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_settlement_fields_null,
)
from test_helpers.constants import (
    ALLOCATION_COMMITTED,
    ALLOCATION_REVOKED,
    BILLING_DELIVERED_ONLY,
    PARTNER_STATUS_ACTIVE,
)
from test_helpers.fixtures import (
    build_partner_week,
    commit_allocation,
    make_outsource_partner,
    propose_allocation,
    read_allocation,
    read_interval,
    read_partner,
    revoke_allocation,
)
from test_helpers.test_users import SOURCING_HEADERS


def _voice_only_world(api):
    """A CHAT_EN interval grid whose only registered partner is certified for voice."""
    world = build_partner_week(api, cycle_overrides={"name": "W37-EMPTY"})
    world["partner"] = make_outsource_partner(
        api,
        legal_name="Voice Only Partners BV",
        skill_codes=["VOICE_EN"],
        rate_per_contact_millicents=9000,
        billing_basis=BILLING_DELIVERED_ONLY,
    )
    world["interval"] = world["intervals"][0]
    return world


class TestEmptyPartnerPoolGenerateReturnsEmpty:
    """A waterfall with no qualifying candidate still answers, and changes nothing."""

    def test_the_waterfall_answers_with_a_created_empty_array(self, api):
        """No partner holds the interval's skill, so the run creates nothing and says so.

        "The response is the array of allocations created, in the order the
        waterfall created them, cheapest partner first; when no candidate qualifies
        the response is an empty array."

        Design: Difficulty/boundary_precision_check/empty_partner_pool_generate_returns_empty
        """
        world = _voice_only_world(api)

        response = api.generate_partner_allocations(
            f.generate_allocations_payload(world["interval"]["id"]), SOURCING_HEADERS
        )

        assert validate_success(response, 201) == []

    def test_no_allocation_row_survives_the_run(self, api):
        """Listing the interval's allocations afterwards finds none.

        "Allocations are readable individually, addressed by
        `partner_allocation_id`, and listable with optional `outsource_partner_id`,
        `interval_plan_id` and `status` filters — and a `PartnerRep` may only list
        to their own partner identifier."

        Design: Difficulty/boundary_precision_check/empty_partner_pool_generate_returns_empty
        """
        world = _voice_only_world(api)
        api.generate_partner_allocations(
            f.generate_allocations_payload(world["interval"]["id"]), SOURCING_HEADERS
        )

        listed, meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, {"interval_plan_id": world["interval"]["id"]}
            )
        )

        assert listed == []
        assert meta["total_count"] == 0

    def test_the_interval_keeps_its_whole_volume_unserved(self, api):
        """With nobody staffed and nobody committed, all eighty-two contacts stay unserved.

        "`allocatable_volume` is `volume_forecast` minus that internal capacity,
        floored at zero. `partner_committed_volume` is the sum of `allocated_volume`
        over the interval's partner allocations whose status is `COMMITTED` or
        `SETTLED`; proposed and revoked allocations contribute nothing, which means
        settling a commitment leaves the interval's committed volume unchanged while
        revoking one releases it. `unserved_volume` is `allocatable_volume` minus
        `partner_committed_volume`, floored at zero."

        Design: Difficulty/boundary_precision_check/empty_partner_pool_generate_returns_empty
        """
        world = _voice_only_world(api)
        api.generate_partner_allocations(
            f.generate_allocations_payload(world["interval"]["id"]), SOURCING_HEADERS
        )

        interval = read_interval(api, world["interval"]["id"])
        assert interval["volume_forecast"] == 82
        assert_interval_outsourcing(
            interval,
            internal_capacity_volume=0,
            allocatable_volume=82,
            partner_committed_volume=0,
            unserved_volume=82,
        )

    def test_the_ineligible_partner_carries_no_commitment(self, api):
        """The voice-only partner is left exactly as registered.

        "A new partner starts at `status` `ACTIVE`, `version` 1,
        `performance_report_count` zero, `latest_sl_attainment_pcts` an empty list,
        `rolling_sl_attainment_pct` null, `consecutive_breach_count` zero,
        `committed_volume_outstanding` zero and `invoice_total_cents` zero."

        Design: Difficulty/boundary_precision_check/empty_partner_pool_generate_returns_empty
        """
        world = _voice_only_world(api)
        api.generate_partner_allocations(
            f.generate_allocations_payload(world["interval"]["id"]), SOURCING_HEADERS
        )

        assert_partner_ledgers(
            read_partner(api, world["partner"]["id"]),
            status=PARTNER_STATUS_ACTIVE,
            committed_volume_outstanding=0,
            invoice_total_cents=0,
        )


def _committed_world(api):
    """One fifty-contact commitment standing against an eighty-two-contact interval."""
    world = build_partner_week(api, cycle_overrides={"name": "W37-UNDO"})
    partner = make_outsource_partner(
        api,
        legal_name="Undo Contact BV",
        interval_max_volume=50,
        commitment_floor_volume=10,
        billing_basis=BILLING_DELIVERED_ONLY,
    )
    interval = world["intervals"][0]
    allocation = propose_allocation(api, partner["id"], interval["id"], 50)
    world.update(
        {
            "partner": partner,
            "interval": interval,
            "allocation": commit_allocation(
                api, allocation["id"], partner["version"]
            ),
        }
    )
    return world


class TestAllocationRevokeRestoresPartnerCommittedVolume:
    """Commit and revoke are an exactly compensating pair on a conserved quantity."""

    def test_the_commitment_holds_fifty_against_the_interval_before_the_undo(self, api):
        """The pre-revoke picture is fifty committed and thirty-two still unserved.

        "On success the system stamps `committed_by_user_id`, adds
        `allocated_volume` to the partner's `committed_volume_outstanding`,
        recomputes the interval's `partner_committed_volume` and `unserved_volume`,
        and increments the partner's own `version` by 1."

        Design: Difficulty/compensating_invariant/allocation_revoke_restores_partner_committed_volume
        """
        world = _committed_world(api)

        assert world["allocation"]["status"] == ALLOCATION_COMMITTED
        assert_interval_outsourcing(
            read_interval(api, world["interval"]["id"]),
            partner_committed_volume=50,
            unserved_volume=32,
        )
        assert_partner_ledgers(
            read_partner(api, world["partner"]["id"]),
            committed_volume_outstanding=50,
        )

    def test_revoking_returns_the_interval_to_its_pre_commitment_numbers(self, api):
        """The interval goes back to zero committed and the full eighty-two unserved.

        "`COMMITTED → REVOKED` — reachable either from an operator's explicit
        revocation or from the partner-suspension cascade — likewise requires only
        that the cycle is not frozen, and it subtracts `allocated_volume` from the
        partner's `committed_volume_outstanding` and recomputes the interval's
        `partner_committed_volume` and `unserved_volume`."

        Design: Difficulty/compensating_invariant/allocation_revoke_restores_partner_committed_volume
        """
        world = _committed_world(api)

        revoked = revoke_allocation(api, world["allocation"]["id"])

        assert revoked["status"] == ALLOCATION_REVOKED
        assert_interval_outsourcing(
            read_interval(api, world["interval"]["id"]),
            partner_committed_volume=0,
            unserved_volume=82,
        )

    def test_revoking_restores_the_partner_outstanding_ledger_exactly(self, api):
        """The partner's outstanding commitment returns to its pre-commit zero.

        "Revocation restores the outstanding-commitment ledger to exactly its
        pre-commitment value, making commit and revoke an exactly compensating pair
        on a conserved quantity."

        Design: Difficulty/compensating_invariant/allocation_revoke_restores_partner_committed_volume
        """
        world = _committed_world(api)

        revoke_allocation(api, world["allocation"]["id"])

        assert_partner_ledgers(
            read_partner(api, world["partner"]["id"]),
            committed_volume_outstanding=0,
        )

    def test_a_revoked_allocation_is_never_billed(self, api):
        """Revocation writes no settlement figures and adds nothing to the invoice.

        "`invoice_total_cents` aggregates only allocations whose `status` is
        `SETTLED`, while `committed_volume_outstanding` aggregates only those whose
        `status` is `COMMITTED`."

        Design: Difficulty/compensating_invariant/allocation_revoke_restores_partner_committed_volume
        """
        world = _committed_world(api)

        revoke_allocation(api, world["allocation"]["id"])

        assert_settlement_fields_null(read_allocation(api, world["allocation"]["id"]))
        assert_partner_ledgers(
            read_partner(api, world["partner"]["id"]), invoice_total_cents=0
        )
