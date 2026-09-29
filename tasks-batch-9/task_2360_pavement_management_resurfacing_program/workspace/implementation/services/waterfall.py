"""The budget waterfall and the two projection arms (PRD 3.4)."""
import calc
import db
from calc import D
from middleware import touch
from services import derive

STRATEGIES = ("WORST_FIRST", "BENEFIT_COST", "HYBRID")
POOL_STATUSES = ("RECOMMENDED", "OVERRIDDEN", "CONSUMED")
HYBRID_TRIAGE_THRESHOLD = D("40.0")


def _area_of(candidate):
    segment = db.segments.get(candidate["segment_id"])
    return D(segment["area_sy"]) if segment else D(0)


def rank_pool(candidates, strategy):
    rows = list(candidates)
    if strategy == "WORST_FIRST":
        rows.sort(key=lambda c: (
            D(c["selection_condition_index"]), -_area_of(c),
            c["created_at"], c["_seq"],
        ))
    elif strategy == "BENEFIT_COST":
        rows.sort(key=lambda c: (
            -D(c["benefit_cost_ratio"]), D(c["estimated_cost_cents"]),
            c["created_at"], c["_seq"],
        ))
    else:  # HYBRID — the whole triage partition precedes the whole remainder.
        def key(c):
            snapshot = D(c["selection_condition_index"])
            if snapshot < HYBRID_TRIAGE_THRESHOLD:
                return (0, snapshot, c["created_at"], c["_seq"])
            return (1, -D(c["benefit_cost_ratio"]), c["created_at"], c["_seq"])

        rows.sort(key=key)
    return rows


def pool_for(scenario):
    rows = [
        c for c in db.candidates.values()
        if c["survey_id"] == scenario["survey_id"]
        and c["candidate_status"] in POOL_STATUSES
    ]
    return rank_pool(rows, scenario["strategy"])


def next_rank(scenario_id):
    ranks = [a["rank"] for a in derive.allocations_of_scenario(scenario_id)]
    return (max(ranks) + 1) if ranks else 1


def new_allocation(scenario_id, candidate_id, rank, status, allocated, source):
    row = {
        "id": db.new_id(),
        "scenario_id": scenario_id,
        "candidate_id": candidate_id,
        "rank": rank,
        "allocation_status": status,
        "allocated_cents": allocated,
        "source": source,
    }
    row.update(db.audit())
    db.allocations[row["id"]] = row
    return row


def projections(scenario):
    """Returns (projected_network_pci, do_nothing_network_pci)."""
    accepted = [
        o for o in derive.observations_of(scenario["survey_id"])
        if o["qc_status"] == "ACCEPTED"
    ]
    horizon = D(scenario["horizon_years"])
    funded_by_segment = {}
    for alloc in derive.allocations_of_scenario(scenario["id"]):
        if alloc["allocation_status"] != "FUNDED":
            continue
        candidate = db.candidates.get(alloc["candidate_id"])
        if candidate is not None:
            funded_by_segment[candidate["segment_id"]] = candidate

    funded_pairs = []
    do_nothing_pairs = []
    for obs in db.ordered(accepted):
        segment = db.segments.get(obs["segment_id"])
        if segment is None:
            continue
        anchor = segment.get("last_treatment_date") or segment["created_at"]
        age = calc.whole_years(anchor, scenario["analysis_date"])
        pre = D(segment["decay_coefficient"])
        knee = D(segment["decay_knee_coefficient"])
        loss = (
            pre * horizon
            + knee * D(max(0, (age + int(scenario["horizon_years"])) - calc.KNEE_YEARS))
            - knee * D(max(0, age - calc.KNEE_YEARS))
        )
        unfunded = calc.rhu(
            calc.clamp(D(segment["condition_index"]) - loss, 0, 100), 1
        )
        do_nothing_pairs.append((segment["area_sy"], unfunded))

        candidate = funded_by_segment.get(segment["id"])
        if candidate is None:
            funded_pairs.append((segment["area_sy"], unfunded))
        else:
            post = min(
                D("100.0"),
                D(candidate["selection_condition_index"])
                + D(candidate["treatment_pci_gain"]),
            )
            horizon_beyond_knee = D(
                max(0, int(scenario["horizon_years"]) - calc.KNEE_YEARS)
            )
            projected = calc.rhu(calc.clamp(
                post - pre * horizon - knee * horizon_beyond_knee, 0, 100
            ), 1)
            funded_pairs.append((segment["area_sy"], projected))

    return (calc.area_weighted_index(funded_pairs),
            calc.area_weighted_index(do_nothing_pairs))


def run(scenario):
    for alloc in list(derive.allocations_of_scenario(scenario["id"])):
        if alloc["source"] == "AUTO_RUN":
            db.allocations.pop(alloc["id"], None)

    remaining = scenario["funding_cents"]
    rank = 1
    for candidate in pool_for(scenario):
        cost = candidate["estimated_cost_cents"]
        if cost <= remaining:
            new_allocation(scenario["id"], candidate["id"], rank,
                           "FUNDED", cost, "AUTO_RUN")
            remaining -= cost
        else:
            new_allocation(scenario["id"], candidate["id"], rank,
                           "DEFERRED", 0, "AUTO_RUN")
        rank += 1

    projected, do_nothing = projections(scenario)
    derive.apply_updates(scenario, {
        "scenario_status": "COMPUTED",
        "projected_network_pci": projected,
        "do_nothing_network_pci": do_nothing,
    })
    derive.recompute_scenario_totals(scenario)
    # PRD 2.9: "Every scenario run, adoption, award, award cancellation and prior
    # manual add advances that `version`." A re-run that reproduces an identical
    # allocation table still rebuilt the table, so the version must advance even
    # when no stored field changed value.
    touch(scenario)
