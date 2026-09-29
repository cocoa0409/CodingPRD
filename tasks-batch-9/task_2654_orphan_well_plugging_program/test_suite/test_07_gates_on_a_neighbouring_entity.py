"""Transitions refused because of state living on an entity the request never names."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CONTRACTOR_NOT_ELIGIBLE,
    ERR_SITE_ACCESS_NOT_AUTHORIZED,
    ERR_STATUTORY_NOTICE_PERIOD_ACTIVE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_null_fields,
    assert_page,
    assert_score,
    created,
)
from test_helpers.factories import site_access_resolution_payload

CITATION = "Tex. Nat. Res. Code 89.043"


def _scheduled_job_awaiting_a_statutory_notice(api):
    """A SCHEDULED job whose well is only ACCESS_PENDING under a running notice."""
    bundle = fx.make_scheduled_job(
        api, scheduled_start="2026-09-01T00:00:00Z", authorize_access=False
    )
    bundle["access"] = fx.open_site_access(
        api,
        bundle["well"]["id"],
        mode="STATUTORY_ENTRY",
        surface_owner_name="Hollis Vance",
        waiting_period_days=30,
        compensation_cents=0,
    )
    return bundle


def test_mobilization_is_blocked_by_the_access_row_not_by_the_job_itself(api):
    """Nothing about the job or its contract is wrong, and it still cannot mobilize.

    The job is SCHEDULED, the contract is ACTIVE and the contractor is in good standing;
    the only obstacle is the notice window running on a site-access row, which projects
    ACCESS_PENDING onto the well.

    PRD: "The `access_status` dimension tracks the agency's legal right to set foot on
    the site and moves among `NO_ACCESS_REQUESTED`, `ACCESS_PENDING`,
    `AGREEMENT_EXECUTED`, `ENTRY_ORDERED` and `ACCESS_DENIED`"

    Design: Difficulty/cross_entity_state_dependency/job_mobilization_gated_by_site_access_state_on_a_different_entity
    """
    bundle = _scheduled_job_awaiting_a_statutory_notice(api)
    access = bundle["access"]
    assert_fields(
        access,
        status="REQUESTED",
        mode="STATUTORY_ENTRY",
        waiting_period_days=30,
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-31T00:00:00Z",
    )
    assert_fields(fx.read_well(api, bundle["well"]["id"]), access_status="ACCESS_PENDING")
    assert_fields(fx.read_contract(api, bundle["contract"]["id"]), status="ACTIVE")

    refused = api.mobilize_plugging_job(bundle["job"]["id"], users.INSPECTOR)
    validate_error(refused, ERR_SITE_ACCESS_NOT_AUTHORIZED)

    job = fx.read_job(api, bundle["job"]["id"])
    assert_fields(job, status="SCHEDULED")
    assert_null_fields(job, "mobilized_at")


def test_ordering_entry_at_the_window_end_unblocks_the_waiting_job(api):
    """The order that unblocks the job is itself gated by the notice clock.

    Entry cannot be ordered while the surface owner's period is still running; at the
    exact window end it can, and the resolved row projects ENTRY_ORDERED onto the well
    without disturbing the well's separate lifecycle state, which lets the crew move.

    PRD: "The clock standing exactly at `window_end_at` is sufficient, because the
    notice window is closed and has therefore fully elapsed at that instant."

    Design: Difficulty/cross_entity_state_dependency/job_mobilization_gated_by_site_access_state_on_a_different_entity
    """
    bundle = _scheduled_job_awaiting_a_statutory_notice(api)
    access_id = bundle["access"]["id"]
    well_id = bundle["well"]["id"]

    too_early = api.resolve_site_access(
        access_id, site_access_resolution_payload("ORDER_ENTRY", CITATION), users.ADMIN
    )
    validate_error(too_early, ERR_STATUTORY_NOTICE_PERIOD_ACTIVE)
    assert_fields(fx.read_site_access(api, access_id), status="REQUESTED")

    fx.set_clock(api, "2026-08-31T00:00:00Z")

    ordered = fx.resolve_site_access(api, access_id, "ORDER_ENTRY", CITATION)
    assert_fields(
        ordered,
        status="ENTRY_ORDERED",
        legal_authority_citation=CITATION,
        resolved_at="2026-08-31T00:00:00Z",
    )

    well = fx.read_well(api, well_id)
    assert_fields(well, access_status="ENTRY_ORDERED", status="PLUGGING_SCHEDULED")

    mobilized = fx.mobilize(api, bundle["job"]["id"])
    assert_fields(mobilized, status="MOBILIZED", mobilized_at="2026-08-31T00:00:00Z")


def _evaluating_solicitation_with_a_suspended_bidder(api):
    """One RESPONSIVE bid on an EVALUATING solicitation, from a suspended contractor."""
    contractor = fx.make_contractor(
        api, name="Neches Abandonment", bond_amount_cents=2000000, performance_score=87
    )
    solicitation = fx.make_open_solicitation(
        api,
        region_code="TX",
        scope_description="district TX orphan well package B",
    )
    bid = fx.place_bid(api, solicitation["id"], contractor["id"], technical_score=92)
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(api, bid["id"], "RESPONSIVE")
    fx.set_license_status(
        api, contractor["id"], "SUSPEND_LICENSE", "unpaid state severance assessment"
    )
    return {"contractor": contractor, "solicitation": solicitation, "bid": bid}


def test_the_award_is_blocked_by_the_winning_contractors_licence(api):
    """The award body is empty, and the refusal comes from the bidder's own row.

    The solicitation is in the right state and the pool holds one responsive bid; the
    only defect lives on the contractor, and the award writes nothing at all.

    PRD: "a winning contractor whose `license_status` has since fallen out of
    `GOOD_STANDING` is rejected with `ERR_CONTRACTOR_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_contractor_license_state_on_a_different_entity
    """
    bundle = _evaluating_solicitation_with_a_suspended_bidder(api)
    solicitation_id = bundle["solicitation"]["id"]

    refused = api.award_solicitation(solicitation_id, users.AWARD)
    validate_error(refused, ERR_CONTRACTOR_NOT_ELIGIBLE)

    assert_fields(fx.read_solicitation(api, solicitation_id), status="EVALUATING")
    assert_fields(fx.read_bid(api, bundle["bid"]["id"]), status="RESPONSIVE")
    assert_page(
        api.list_unit_cost_contracts(
            users.PROCUREMENT, {"solicitation_id": solicitation_id}
        ),
        0,
        expected_total=0,
    )


def test_reinstating_the_contractor_lets_the_identical_award_through(api):
    """Restoring the licence on the other entity is the whole difference.

    The award request is byte-identical - it has no body - and it now produces the
    contract, with the single candidate scoring the full 100.00 on price.

    PRD: "Reinstating is available only from `SUSPENDED`: it returns `license_status` to
    `GOOD_STANDING`, clears `suspended_at` back to null"

    Design: Difficulty/cross_entity_state_dependency/award_gated_by_contractor_license_state_on_a_different_entity
    """
    bundle = _evaluating_solicitation_with_a_suspended_bidder(api)
    solicitation_id = bundle["solicitation"]["id"]
    bid_id = bundle["bid"]["id"]

    validate_error(
        api.award_solicitation(solicitation_id, users.AWARD), ERR_CONTRACTOR_NOT_ELIGIBLE
    )

    reinstated = fx.set_license_status(
        api, bundle["contractor"]["id"], "REINSTATE", "assessment paid in full"
    )
    assert_fields(reinstated, license_status="GOOD_STANDING")
    assert_null_fields(reinstated, "suspended_at")

    contract = created(api.award_solicitation(solicitation_id, users.AWARD))
    assert_fields(
        contract,
        status="ACTIVE",
        winning_bid_id=bid_id,
        contractor_id=bundle["contractor"]["id"],
        solicitation_id=solicitation_id,
    )
    assert_cents(contract["ceiling_cents"], 20000000, "ceiling_cents")
    assert_cents(contract["obligated_cents"], 0, "obligated_cents")

    assert_fields(fx.read_solicitation(api, solicitation_id), status="AWARDED")
    awarded_bid = fx.read_bid(api, bid_id)
    assert_fields(awarded_bid, status="AWARDED")
    assert_cents(
        awarded_bid["evaluated_unit_cost_cents"], 7366835, "evaluated_unit_cost_cents"
    )
    assert_score(awarded_bid["price_score"], 100.00, "price_score")
    assert_score(awarded_bid["composite_score"], 96.80, "composite_score")
