"""Distribution runs: allocation, posting, reversal and reconciliation.

PRD section 3.7 for the allocation and the money movement, PRD section 3.9 for
the cent-conservation identity.
"""

import calc
import clock
from db import base_record, db, ordered, touch
from errors import ApiError
from services import conference_service, member_service

ELIGIBLE_MEMBER_STATUSES = ("ADMITTED_PHASING", "FULL_SHARE", "WITHDRAWAL_NOTICED")

PROVISIONAL_MEDIA_GAME_STATUSES = ("SCHEDULED", "PLAYED")
FINAL_MEDIA_GAME_STATUSES = ("PLAYED",)
PROVISIONAL_BERTH_STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
)
FINAL_BERTH_STATUSES = ("APPROVED",)


def eligible_members(conference_id):
    return [
        member
        for member in member_service.conference_members(conference_id)
        if member["status"] in ELIGIBLE_MEMBER_STATUSES
    ]


def _media_appearance_count(member_id, fiscal_year, variant):
    statuses = (
        FINAL_MEDIA_GAME_STATUSES
        if variant == "FINAL_AUDITED"
        else PROVISIONAL_MEDIA_GAME_STATUSES
    )
    count = 0
    for game in db.schedule_games.values():
        if game["fiscal_year"] != fiscal_year:
            continue
        if not game["media_designated"]:
            continue
        if game["status"] not in statuses:
            continue
        if member_id not in (game["home_member_id"], game["away_member_id"]):
            continue
        count += 1
    return count


def _postseason_berth_count(member_id, fiscal_year, variant):
    statuses = (
        FINAL_BERTH_STATUSES if variant == "FINAL_AUDITED" else PROVISIONAL_BERTH_STATUSES
    )
    count = 0
    for appearance in db.bowl_appearances.values():
        if appearance["member_id"] != member_id:
            continue
        if appearance["fiscal_year"] != fiscal_year:
            continue
        if appearance["status"] not in statuses:
            continue
        count += 1
    return count


def compute_run(pool, variant, memo, user_id):
    """Create a COMPUTED run with one ACTIVE line per line member."""
    conference = db.conference

    # Step one - the net pool.
    expense_basis = (
        pool["estimated_expense_cents"]
        if variant == "PROVISIONAL"
        else pool["audited_expense_cents"]
    )
    net_pool = calc.net_pool_cents(pool["gross_revenue_cents"], expense_basis)

    # Step two - the reserve sweep.
    reserve_draw = calc.reserve_draw_cents(
        net_pool,
        conference["reserve_posture"],
        conference["reserve_target_cents"],
        conference["reserve_balance_cents"],
    )
    distributable = net_pool - reserve_draw

    # Step three - the per-member weight, enumerated in created_at ASC order.
    members = eligible_members(pool["conference_id"])
    weighted = []
    for member in members:
        unit_count = member_service.validated_unit_count(
            member["id"], fiscal_year=pool["fiscal_year"]
        )
        raw_bps = calc.raw_weight_bps(
            pool["allocation_method"],
            unit_count,
            _media_appearance_count(member["id"], pool["fiscal_year"], variant),
            _postseason_berth_count(member["id"], pool["fiscal_year"], variant),
        )
        weight_bps = calc.phased_weight_bps(raw_bps, member["distribution_phase_bps"])
        if weight_bps == 0:
            # A zero-weight member receives no line, and is never charged the
            # governance service fee either.
            continue
        weighted.append((member, weight_bps))

    total_weight = sum(weight for _member, weight in weighted)
    if total_weight == 0:
        raise ApiError("ERR_EMPTY_ALLOCATION_BASIS")

    run = base_record()
    run.update(
        {
            "revenue_pool_id": pool["id"],
            "variant": variant,
            "status": "COMPUTED",
            "net_pool_cents": net_pool,
            "reserve_draw_cents": reserve_draw,
            "distributable_cents": distributable,
            "total_weight_bps": total_weight,
            "computed_by_user_id": user_id,
            "posted_by_user_id": None,
            "posted_at": None,
            "superseded_by_run_id": None,
            "memo": memo,
        }
    )

    # Step four - the pinned rounding pass.  The receiving order is weight_bps
    # descending and, among equal weights, Member.created_at ascending.
    deal_order = sorted(
        weighted, key=lambda pair: (-pair[1], pair[0]["created_at"], pair[0]["_seq"])
    )
    shares, _total = calc.allocate_shares(
        distributable, [(member["id"], weight) for member, weight in deal_order]
    )

    # Lines are created in Member.created_at ASC order.
    for member, weight_bps in weighted:
        gross_share, remainder_cent = shares[member["id"]]
        withheld = calc.withheld_cents(gross_share, variant)
        governance_fee = calc.GOVERNANCE_SERVICE_FEE_CENTS
        available = gross_share - withheld - governance_fee
        gor_offset = calc.gor_offset_cents(
            member["status"],
            member.get("grant_of_rights_through_fiscal_year"),
            pool["fiscal_year"],
            member["exit_settlement_total_cents"],
            member["exit_settlement_paid_cents"],
            available,
        )
        line = base_record(versioned=False)
        line.update(
            {
                "distribution_run_id": run["id"],
                "member_id": member["id"],
                "weight_bps": weight_bps,
                "gross_share_cents": gross_share,
                "remainder_cent_awarded": remainder_cent,
                "withheld_cents": withheld,
                "governance_fee_cents": governance_fee,
                "gor_offset_cents": gor_offset,
                "net_payable_cents": available - gor_offset,
                "status": "ACTIVE",
            }
        )
        db.distribution_lines[line["id"]] = line

    db.distribution_runs[run["id"]] = run

    # Any earlier run on the same pool still COMPUTED is superseded.
    supersede_computed_runs(pool, superseded_by_run_id=run["id"], exclude_run_id=run["id"])

    touch(pool)
    return run


def run_lines(run_id, statuses=None):
    lines = [
        line
        for line in db.distribution_lines.values()
        if line["distribution_run_id"] == run_id
        and (statuses is None or line["status"] in statuses)
    ]
    # A run's lines are listed in the members' created_at ascending order.
    def sort_key(line):
        member = db.members.get(line["member_id"])
        if member is None:
            return (line["created_at"], line["_seq"])
        return (member["created_at"], member["_seq"])

    return sorted(lines, key=sort_key)


def supersede_computed_runs(pool, superseded_by_run_id=None, exclude_run_id=None):
    """Mark every COMPUTED run on the pool SUPERSEDED and void its ACTIVE lines."""
    for run in ordered(list(db.distribution_runs.values())):
        if run["revenue_pool_id"] != pool["id"]:
            continue
        if exclude_run_id is not None and run["id"] == exclude_run_id:
            continue
        if run["status"] != "COMPUTED":
            continue
        run["status"] = "SUPERSEDED"
        run["superseded_by_run_id"] = superseded_by_run_id
        touch(run)
        for line in run_lines(run["id"], statuses=("ACTIVE",)):
            line["status"] = "VOIDED"


def reconciliation(run):
    """PRD section 3.9: the cent-conservation identity over ACTIVE lines only."""
    lines = run_lines(run["id"], statuses=("ACTIVE",))
    total_net_payable = sum(line["net_payable_cents"] for line in lines)
    total_withheld = sum(line["withheld_cents"] for line in lines)
    total_governance_fee = sum(line["governance_fee_cents"] for line in lines)
    total_gor_offset = sum(line["gor_offset_cents"] for line in lines)
    delta = run["net_pool_cents"] - (
        run["reserve_draw_cents"]
        + total_net_payable
        + total_withheld
        + total_governance_fee
        + total_gor_offset
    )
    return {
        "distribution_run_id": run["id"],
        "net_pool_cents": run["net_pool_cents"],
        "reserve_draw_cents": run["reserve_draw_cents"],
        "total_net_payable_cents": total_net_payable,
        "total_withheld_cents": total_withheld,
        "total_governance_fee_cents": total_governance_fee,
        "total_gor_offset_cents": total_gor_offset,
        "reconciliation_delta_cents": delta,
    }


def post_run(run, pool, user_id):
    conference = db.conference
    lines = run_lines(run["id"], statuses=("ACTIVE",))

    run["status"] = "POSTED"
    run["posted_at"] = clock.now()
    run["posted_by_user_id"] = user_id
    touch(run)

    conference["reserve_balance_cents"] += run["reserve_draw_cents"]
    conference_service.derive_reserve_posture(conference)
    conference["escrow_balance_cents"] += sum(line["withheld_cents"] for line in lines)
    conference["governance_fee_revenue_cents"] += sum(
        line["governance_fee_cents"] for line in lines
    )

    write_last_full = (
        run["variant"] == "FINAL_AUDITED" and pool["pool_type"] == "MEDIA_RIGHTS"
    )
    for line in lines:
        member = db.members.get(line["member_id"])
        if member is None:
            continue
        mutated = False
        if line["gor_offset_cents"] > 0:
            member["exit_settlement_paid_cents"] += line["gor_offset_cents"]
            mutated = True
        if write_last_full:
            member["last_full_annual_distribution_cents"] = line["gross_share_cents"]
            mutated = True
        if mutated:
            touch(member)

    touch(conference)


def reverse_run(run, pool, reason):
    conference = db.conference
    lines = run_lines(run["id"], statuses=("ACTIVE",))

    run["status"] = "REVERSED"
    touch(run)

    for line in lines:
        line["status"] = "VOIDED"

    conference["reserve_balance_cents"] -= run["reserve_draw_cents"]
    conference_service.derive_reserve_posture(conference)
    conference["escrow_balance_cents"] -= sum(line["withheld_cents"] for line in lines)
    conference["governance_fee_revenue_cents"] -= sum(
        line["governance_fee_cents"] for line in lines
    )

    for line in lines:
        member = db.members.get(line["member_id"])
        if member is None:
            continue
        if line["gor_offset_cents"] > 0:
            member["exit_settlement_paid_cents"] -= line["gor_offset_cents"]
            touch(member)

    touch(conference)
