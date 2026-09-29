"""calculations.prize_award_generation, bonus_determination and
withholding_computation (PRD 3.8)."""
from decimal import ROUND_HALF_UP, Decimal

from constants import (
    AGGREGATE_DE_MINIMIS_CENTS,
    BONUS_CATEGORIES,
    CATEGORY_ORDER,
    DE_MINIMIS_AWARD_CENTS,
    DOMESTIC_TAX_COUNTRY,
    PLACE_CATEGORIES,
    STATUTORY_WITHHOLDING_BPS,
    WHEELCHAIR_BONUS_FACTOR_BPS,
)
from db import db, new_record, order_key, sorted_rows, touch
from services import lookup, places


def round_half_up(numerator, denominator):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _create_award(edition, result, category, place, tie_share_count, gross):
    record = new_record(
        race_edition_id=edition["id"],
        race_result_id=result["id"],
        athlete_id=result["athlete_id"],
        category=category,
        place=place,
        tie_share_count=tie_share_count,
        gross_amount_cents=gross,
        withholding_variant="NONE",
        withholding_bps=0,
        withholding_cents=0,
        net_amount_cents=gross,
        status="COMPUTED",
        approved_by_user_id=None,
        paid_by_user_id=None,
        payment_reference=None,
        paid_at=None,
    )
    db.prize_awards[record["id"]] = record
    return record


def compute_awards(edition):
    edition_id = edition["id"]

    # STEP 0 — supersede prior COMPUTED awards.
    for award in lookup.edition_awards(edition_id):
        if award["status"] == "COMPUTED":
            award["status"] = "VOID"
            touch(award)

    # STEP 1 — re-run the place-and-tie assignment over the current CERTIFIED set.
    places.assign_places(edition)

    certified = [
        r for r in lookup.edition_results(edition_id)
        if r["certification_status"] == "CERTIFIED"
    ]
    gender_of = {r["id"]: places.athlete_gender(r) for r in certified}
    lines = lookup.edition_purse_lines(edition_id)
    fresh = []

    # STEP 2..4 — place prizes, in the fixed category order.
    for category in PLACE_CATEGORIES:
        groups = {}
        for result in certified:
            gender = gender_of[result["id"]]
            if category == "OVERALL":
                if result["division"] not in ("ELITE", "SUB_ELITE"):
                    continue
                place = result["place_overall"]
                partition = (None, gender)
            elif category == "DIVISION":
                place = result["place_division"]
                partition = (result["division"], gender)
            else:
                if not (result["division"] == "ELITE" and result["is_masters"]):
                    continue
                place = result["place_masters"]
                partition = (None, gender)
            if place is None:
                continue
            groups.setdefault((partition, place), []).append(result)

        ordered_groups = sorted(
            groups.keys(),
            key=lambda gp: (gp[1], gp[0][0] or "", gp[0][1] or ""),
        )
        for partition, place in ordered_groups:
            tied = sorted_rows(groups[(partition, place)])
            count = len(tied)
            pool = sum(
                line["amount_cents"]
                for line in lines
                if line["category"] == category
                and line["gender"] == partition[1]
                and line["division"] == partition[0]
                and line["place"] is not None
                and place <= line["place"] <= place + count - 1
            )
            share = pool // count
            remainder = pool - share * count
            for index, result in enumerate(tied):
                gross = share + (1 if index < remainder else 0)
                if gross == 0:
                    continue
                fresh.append(
                    _create_award(edition, result, category, place, count, gross)
                )

    # STEP 5 — bonuses.
    consumed = sum(
        award["gross_amount_cents"]
        for award in lookup.edition_awards(edition_id)
        if award["category"] in BONUS_CATEGORIES
        and award["status"] in ("APPROVED", "PAID", "CLAWBACK_PENDING")
    )
    bonus_order = sorted(
        certified, key=lambda r: (r["official_seconds"],) + order_key(r)
    )
    for result in bonus_order:
        gender = gender_of[result["id"]]
        time_amounts = [
            line["amount_cents"]
            for line in lines
            if line["category"] == "TIME_BONUS"
            and line["division"] == result["division"]
            and line["gender"] == gender
            and line["threshold_seconds"] is not None
            and result["official_seconds"] <= line["threshold_seconds"]
        ]
        time_candidate = max(time_amounts) if time_amounts else 0
        if result["division"] == "WHEELCHAIR":
            time_candidate = (time_candidate * WHEELCHAIR_BONUS_FACTOR_BPS) // 10000
        record_candidate = 0
        if result["record_claim_status"] == "RATIFIED":
            record_amounts = [
                line["amount_cents"]
                for line in lines
                if line["category"] == "RECORD_BONUS"
                and line["division"] == result["division"]
                and line["gender"] == gender
            ]
            record_candidate = max(record_amounts) if record_amounts else 0
        candidate = max(record_candidate, time_candidate)
        category = (
            "RECORD_BONUS"
            if (record_candidate > 0 and record_candidate >= time_candidate)
            else "TIME_BONUS"
        )
        headroom = max(0, edition["bonus_pool_cap_cents"] - consumed)
        paid = min(candidate, headroom)
        if paid > 0:
            fresh.append(_create_award(edition, result, category, None, 1, paid))
            consumed += paid

    # STEP 6 — withholding.
    apply_withholding(fresh)
    return fresh


def _set_withholding(award, variant, bps, cents):
    award["withholding_variant"] = variant
    award["withholding_bps"] = bps
    award["withholding_cents"] = cents
    award["net_amount_cents"] = award["gross_amount_cents"] - cents


def apply_withholding(fresh_awards):
    by_athlete = {}
    for award in fresh_awards:
        by_athlete.setdefault(award["athlete_id"], []).append(award)

    for athlete_id, awards in by_athlete.items():
        athlete = lookup.soft_get("athletes", athlete_id)
        residency = athlete["tax_residency_country"] if athlete else None
        if residency == DOMESTIC_TAX_COUNTRY:
            for award in awards:
                _set_withholding(award, "NONE", 0, 0)
            continue

        if athlete and athlete["w8ben_on_file"]:
            rate = athlete["treaty_withholding_bps"]
            ordered = sorted(
                awards,
                key=lambda a: (CATEGORY_ORDER[a["category"]],) + order_key(a),
            )
            for award in ordered:
                gross = award["gross_amount_cents"]
                if gross < DE_MINIMIS_AWARD_CENTS:
                    cents = 0
                else:
                    cents = round_half_up(gross * rate, 10000)
                _set_withholding(award, "PER_AWARD", rate, cents)
            continue

        rate = STATUTORY_WITHHOLDING_BPS
        aggregate = sum(a["gross_amount_cents"] for a in awards)
        if aggregate <= AGGREGATE_DE_MINIMIS_CENTS:
            for award in awards:
                _set_withholding(award, "AGGREGATED", rate, 0)
            continue
        total = round_half_up(aggregate * rate, 10000)
        allocations = []
        for award in awards:
            product = total * award["gross_amount_cents"]
            base = product // aggregate
            numerator = product - base * aggregate
            allocations.append([award, base, numerator])
        leftover = total - sum(item[1] for item in allocations)
        allocations.sort(key=lambda item: (-item[2],) + order_key(item[0]))
        for index, item in enumerate(allocations):
            extra = 1 if index < leftover else 0
            _set_withholding(item[0], "AGGREGATED", rate, item[1] + extra)
