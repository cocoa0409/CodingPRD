"""Tests where one entity's operation is decided by the state of a different entity.

A restricted-fund transfer that is fully ready on the fund's own terms is still
gated by the parent deal's status (PRD 2.7 rule 16, PRD 3.6), and a brand-new
integration task reads its initial status off the deal's restricted-asset posture
rather than off anything on the task (PRD 3.8).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_DEAL_STATE
from test_helpers.assertions import assert_field, assert_money_equals, assert_null
from test_helpers.test_users import INTEGRATION_MANAGER, PLATFORM_ADMIN, TRUST_COUNSEL

FUND_VALUE_CENTS = 62000000  # principal 50000000 plus appreciation 12000000


def test_transfer_refused_while_the_parent_deal_is_still_in_diligence(api):
    """A CONSENT_GRANTED fund cannot be transferred while its authorising deal is in DILIGENCE.

    PRD 3.6 admits a transfer only where "the deal must be in STRUCTURE_SELECTED,
    BOARD_APPROVAL, REGULATORY_REVIEW or INTEGRATION, else
    ERR_INVALID_DEAL_STATE". Every precondition local to the fund is satisfied -
    transfer_status is CONSENT_GRANTED, restriction_conflict is false, the
    declared DONOR_CONSENT basis matches the branch the fund travelled and the
    holder is a deal party - so the only reason to refuse is the state of the
    Restructuring row.

    Design: Difficulty/cross_entity_state_dependency/restricted_fund_transfer_gated_by_the_other_entity_deal_status
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])

    assert_field(fund, "transfer_status", "CONSENT_GRANTED")
    assert_money_equals(
        fund["transferable_amount_cents"], FUND_VALUE_CENTS, "transferable_amount_cents"
    )
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE")

    response = api.transfer_restricted_fund(
        fund["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
    )
    validate_error(response, ERR_INVALID_DEAL_STATE, 409)

    after = validate_success(api.get_restricted_fund(fund["id"], PLATFORM_ADMIN))
    assert_field(after, "transfer_status", "CONSENT_GRANTED")
    assert_money_equals(after["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_null(after, "transferred_to_org_id")
    assert_money_equals(
        validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))[
            "restricted_corpus_cents"
        ],
        0,
        "org_b.restricted_corpus_cents",
    )


def test_transfer_still_refused_while_the_parent_deal_is_diligence_closed(api):
    """DILIGENCE_CLOSED is not one of the four deal statuses that admit a transfer.

    PRD 3.6 lists the admitting statuses exhaustively as "STRUCTURE_SELECTED,
    BOARD_APPROVAL, REGULATORY_REVIEW or INTEGRATION", so a deal that has closed
    diligence but not yet committed to a structure still refuses the transfer with
    ERR_INVALID_DEAL_STATE even though the fund itself is unchanged and ready.

    Design: Difficulty/cross_entity_state_dependency/restricted_fund_transfer_gated_by_the_other_entity_deal_status
    """
    ctx = fx.setup_deal_diligence(api)
    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    ctx = fx.setup_deal_diligence_closed(api, ctx)
    deal_id = ctx["deal"]["id"]
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE_CLOSED")

    response = api.transfer_restricted_fund(
        fund["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
    )
    validate_error(response, ERR_INVALID_DEAL_STATE, 409)


def test_identical_transfer_succeeds_once_the_deal_reaches_structure_selected(api):
    """The identical transfer call succeeds once the deal advances, with nothing on the fund changed.

    PRD 3.6 hop one moves the fund to TRANSFERRED writing transferred_amount_cents
    "equal to the previously fixed transferable_amount_cents" and
    transferred_to_org_id "set to the counterparty organization"; hop two
    recomputes restricted_corpus_cents on both parties by the three-part sum of
    PRD 3.1, which leaves the holder with only its retained amount and credits the
    recipient with what moved; hop three flips restricted_asset_posture
    "RESTRICTED_PENDING -> CLEARED at the moment the unresolved count reaches
    zero".

    Design: Difficulty/cross_entity_state_dependency/restricted_fund_transfer_gated_by_the_other_entity_deal_status
    """
    ctx = fx.setup_deal_diligence(api)
    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    deal_id = ctx["deal"]["id"]
    validate_error(
        api.transfer_restricted_fund(
            fund["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
        ),
        ERR_INVALID_DEAL_STATE,
        409,
    )

    ctx = fx.setup_deal_diligence_closed(api, ctx)
    ctx = fx.setup_deal_structure_selected(api, ctx)
    assert_field(fx.read_deal(api, deal_id), "status", "STRUCTURE_SELECTED")

    moved = validate_success(
        api.transfer_restricted_fund(
            fund["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
        )
    )

    assert_field(moved, "transfer_status", "TRANSFERRED")
    assert_field(moved, "transfer_basis", "DONOR_CONSENT")
    assert_field(moved, "transferred_to_org_id", ctx["org_b"]["id"])
    assert_field(moved, "transfer_restructuring_id", deal_id)
    assert_money_equals(
        moved["transferred_amount_cents"], FUND_VALUE_CENTS, "transferred_amount_cents"
    )
    assert_money_equals(moved["retained_amount_cents"], 0, "retained_amount_cents")
    assert_field(moved, "unwind_count", 0)

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_money_equals(org_a["restricted_corpus_cents"], 0, "org_a.restricted_corpus_cents")
    assert_money_equals(
        org_b["restricted_corpus_cents"], FUND_VALUE_CENTS, "org_b.restricted_corpus_cents"
    )

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "status", "STRUCTURE_SELECTED")
    assert_field(deal, "restricted_asset_posture", "CLEARED")
    assert_field(deal, "unresolved_restricted_fund_count", 0)


def test_program_continuity_task_is_held_under_a_restricted_pending_posture(api):
    """A new PROGRAM_CONTINUITY task is HELD under RESTRICTED_PENDING while STAFFING is PLANNED.

    PRD 3.8 makes the initial status conditional on the parent deal: "where the
    workstream is PROGRAM_CONTINUITY and the deal's restricted_asset_posture is
    RESTRICTED_PENDING or BLOCKED, the task is created directly in HELD with
    held_reason set to RESTRICTED_ASSETS_UNRESOLVED", while "every other
    combination of workstream and posture creates the task in PLANNED with
    held_reason null". A single CONSENT_GRANTED fund leaves one unresolved party
    fund and no denied fund, which PRD 3.6 makes RESTRICTED_PENDING.

    Design: Difficulty/cross_entity_state_dependency/integration_task_initial_state_branches_on_the_deal_restricted_posture
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "RESTRICTED_PENDING")

    continuity = fx.create_task(
        api,
        deal_id,
        workstream="PROGRAM_CONTINUITY",
        crew_code="CREW-PROG1",
        title="Rebadge afterschool sites",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )
    staffing = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Harmonise pay bands",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )

    assert_field(continuity, "status", "HELD")
    assert_field(continuity, "held_reason", "RESTRICTED_ASSETS_UNRESOLVED")
    assert_null(continuity, "started_at")
    assert_field(staffing, "status", "PLANNED")
    assert_null(staffing, "held_reason")


def test_program_continuity_task_is_held_under_a_blocked_posture(api):
    """A denied donor consent makes the posture BLOCKED, which also creates the task HELD.

    PRD 3.6 decides the posture by first matching branch, so "if any party fund is
    in CONSENT_DENIED the posture is BLOCKED", and PRD 3.8 holds a new
    PROGRAM_CONTINUITY task where the posture "is RESTRICTED_PENDING or BLOCKED",
    setting held_reason to RESTRICTED_ASSETS_UNRESOLVED.

    Design: Difficulty/cross_entity_state_dependency/integration_task_initial_state_branches_on_the_deal_restricted_posture
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fx.setup_fund_consent_denied(api, ctx["org_a"]["id"])
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "BLOCKED")

    continuity = fx.create_task(
        api,
        deal_id,
        workstream="PROGRAM_CONTINUITY",
        crew_code="CREW-PROG3",
        title="Freeze client intake",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )

    assert_field(continuity, "status", "HELD")
    assert_field(continuity, "held_reason", "RESTRICTED_ASSETS_UNRESOLVED")


def test_program_continuity_task_created_after_the_posture_clears_lands_planned(api):
    """Once the transfer clears the posture, the held task is released and a new one starts PLANNED.

    PRD 3.6 hop four states that on a transfer that drives the posture to CLEARED
    "every integration task of that deal whose workstream is PROGRAM_CONTINUITY
    and whose status is HELD moves HELD -> PLANNED with held_reason cleared to
    null". A task created after that point meets none of the holding conditions of
    PRD 3.8, so it is created in PLANNED with held_reason null even though its
    workstream is PROGRAM_CONTINUITY.

    Design: Difficulty/cross_entity_state_dependency/integration_task_initial_state_branches_on_the_deal_restricted_posture
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    held = fx.create_task(
        api,
        deal_id,
        workstream="PROGRAM_CONTINUITY",
        crew_code="CREW-PROG1",
        title="Rebadge afterschool sites",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )
    assert_field(held, "status", "HELD")

    fx.transfer_fund(api, fund["id"], deal_id, "DONOR_CONSENT")
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "CLEARED")

    released = validate_success(api.get_integration_task(held["id"], PLATFORM_ADMIN))
    assert_field(released, "status", "PLANNED")
    assert_null(released, "held_reason")

    fresh = validate_success(
        api.create_integration_task(
            f.integration_task_payload(
                deal_id,
                workstream="PROGRAM_CONTINUITY",
                crew_code="CREW-PROG2",
                title="Transfer client records",
                planned_start_date="2026-09-01",
                planned_end_date="2026-09-15",
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    assert_field(fresh, "status", "PLANNED")
    assert_null(fresh, "held_reason")
