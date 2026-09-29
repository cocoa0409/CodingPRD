"""Derived-field recomputation and the three synchronous cascades (PRD 2.11)."""

from db import bump, db, order_created_asc
from services import calc

IN_PRODUCTION_STATES = ("ON_FLOOR", "DRUM_DONE", "BEARINGS_DONE", "QA_HOLD")


# ---- collection helpers ------------------------------------------------
def builds_of_model(model_id):
    return [b for b in db.builds.values() if b["model_id"] == model_id]


def logs_of_build(build_id):
    return [l for l in db.logs.values() if l["build_order_id"] == build_id]


def claims_of_build(build_id):
    return [c for c in db.claims.values() if c["build_order_id"] == build_id]


def claims_of_part(part_id):
    return [c for c in db.claims.values() if c["part_id"] == part_id]


def lines_of_quote(quote_id):
    return order_created_asc([l for l in db.quote_lines.values()
                              if l["quote_id"] == quote_id])


def dossiers_of_model(model_id):
    return order_created_asc([d for d in db.dossiers.values()
                              if d["model_id"] == model_id])


def certified_dossier(model_id):
    for dossier in dossiers_of_model(model_id):
        if dossier["dossier_state"] == "CERTIFIED":
            return dossier
    return None


# ---- derived-field recomputation --------------------------------------
def refresh_build_derived(build):
    """labor_minutes_total and station_pass_count; caller owns the version bump."""
    logs = logs_of_build(build["id"])
    build["labor_minutes_total"] = sum(l["labor_minutes"] for l in logs)
    build["station_pass_count"] = len([l for l in logs if l["outcome"] == "PASS"])


def refresh_model_counts(model):
    """Recompute the model's production counters and yield.

    Returns True when the model is in yield breach (PRD 3.6): at least one
    terminal unit exists and first_pass_yield_pct is strictly below the floor.
    """
    builds = builds_of_model(model["id"])
    accepted = len([b for b in builds if b["build_state"] == "ACCEPTED"])
    scrapped = len([b for b in builds if b["build_state"] == "SCRAPPED"])
    on_hold = len([b for b in builds if b["build_state"] == "QUALITY_HOLD"])
    yield_pct = calc.first_pass_yield_pct(builds)
    terminal = accepted + scrapped
    changed = (model["accepted_unit_count"] != accepted
               or model["scrapped_unit_count"] != scrapped
               or model["quality_hold_unit_count"] != on_hold
               or model["first_pass_yield_pct"] != yield_pct)
    model["accepted_unit_count"] = accepted
    model["scrapped_unit_count"] = scrapped
    model["quality_hold_unit_count"] = on_hold
    model["first_pass_yield_pct"] = yield_pct
    if changed:
        bump(model)
    return terminal >= 1 and yield_pct < model["min_first_pass_yield_pct"]


def refresh_open_claim_count(distributor):
    count = len([c for c in db.claims.values()
                 if c["distributor_id"] == distributor["id"]
                 and c["claim_state"] == "SUBMITTED"])
    if distributor["open_claim_count"] != count:
        distributor["open_claim_count"] = count
        bump(distributor)


def refresh_open_claim_counts(distributor_ids):
    for distributor_id in sorted(set(distributor_ids)):
        distributor = db.distributors.get(distributor_id)
        if distributor is not None:
            refresh_open_claim_count(distributor)


# ---- scrap and rework -------------------------------------------------
def scrap_if_over_limit(build, model):
    """PRD 3.6: a rework_count strictly greater than the ceiling scraps at once."""
    if build["rework_count"] > model["max_rework_cycles"]:
        build["build_state"] = "SCRAPPED"
        build["scrap_reason"] = "REWORK_LIMIT"
        bump(build)
        return True
    return False


def finish_terminal_transition(model):
    """Model bookkeeping after a unit reached a terminal state, plus hops 4-6."""
    breach = refresh_model_counts(model)
    if breach:
        yield_breach_cascade(model)


# ---- yield-breach cascade (PRD 3.6, hops 4-6) -------------------------
def yield_breach_cascade(model):
    dossier = certified_dossier(model["id"])
    if dossier is None:
        return
    # hop 4: the compliance record
    dossier["dossier_state"] = "RESURVEY_REQUIRED"
    dossier["resurvey_reason"] = "YIELD_BREACH"
    dossier["resurvey_count"] = dossier["resurvey_count"] + 1
    dossier["qualified_program_codes"] = []
    dossier["rebate_amount_cents"] = 0
    bump(dossier)
    # hop 5: the model itself
    if model["certification_state"] not in ("RELEASED", "CERTIFIED"):
        return
    model["certification_state"] = "SUSPENDED"
    model["suspended_reason"] = "YIELD_RESURVEY"
    model["rebate_program_codes"] = []
    model["rebate_amount_cents"] = 0
    bump(model)
    # hop 6: production in flight (no integrity_hold is raised here)
    for build in order_created_asc(builds_of_model(model["id"])):
        if build["build_state"] in IN_PRODUCTION_STATES:
            build["build_state"] = "QUALITY_HOLD"
            bump(build)
    refresh_model_counts(model)


# ---- certification-revocation cascade (PRD 3.4) -----------------------
def revocation_cascade(technician):
    implicated = []
    for build in order_created_asc(db.builds.values()):
        if any(l["technician_id"] == technician["id"]
               for l in logs_of_build(build["id"])):
            implicated.append(build)

    held_ids = []
    touched_models = []
    for build in implicated:
        if build["build_state"] == "SCRAPPED":
            continue  # a scrapped unit is left entirely untouched
        if build["build_state"] in IN_PRODUCTION_STATES:
            build["build_state"] = "QUALITY_HOLD"
        build["integrity_hold"] = True
        bump(build)
        held_ids.append(build["id"])
        if build["model_id"] not in touched_models:
            touched_models.append(build["model_id"])

    for model_id in touched_models:
        model = db.models.get(model_id)
        if model is not None:
            refresh_model_counts(model)

    # hop 3: every SUBMITTED claim on those units is blocked
    blocked_distributors = []
    claims = [c for c in db.claims.values()
              if c["build_order_id"] in held_ids and c["claim_state"] == "SUBMITTED"]
    for claim in order_created_asc(claims):
        claim["claim_state"] = "FULFILLMENT_BLOCKED"
        claim["block_reason"] = "BUILD_INTEGRITY_HOLD"
        bump(claim)
        blocked_distributors.append(claim["distributor_id"])

    # hop 4: distributor counters
    refresh_open_claim_counts(blocked_distributors)


# ---- certification-regrant cascade (PRD 3.4) --------------------------
def regrant_cascade():
    released_ids = []
    touched_models = []
    for build in order_created_asc(db.builds.values()):
        if not build["integrity_hold"]:
            continue
        logs = logs_of_build(build["id"])
        technicians = [db.technicians.get(l["technician_id"]) for l in logs]
        if not all(t is not None and t["cert_state"] == "ACTIVE" for t in technicians):
            continue
        build["integrity_hold"] = False
        model = db.models.get(build["model_id"])
        if build["build_state"] == "QUALITY_HOLD":
            build["build_state"] = "REWORK"
            build["rework_count"] = build["rework_count"] + 1
            bump(build)
            if model is not None:
                scrap_if_over_limit(build, model)
        else:
            bump(build)
        released_ids.append(build["id"])
        if build["model_id"] not in touched_models:
            touched_models.append(build["model_id"])

    for model_id in touched_models:
        model = db.models.get(model_id)
        if model is not None:
            refresh_model_counts(model)

    # hop 2: unblock integrity-blocked claims when the part is on the shelf
    affected_distributors = []
    claims = [c for c in db.claims.values()
              if c["build_order_id"] in released_ids
              and c["claim_state"] == "FULFILLMENT_BLOCKED"
              and c["block_reason"] == "BUILD_INTEGRITY_HOLD"]
    for claim in order_created_asc(claims):
        part = db.parts.get(claim["part_id"])
        if part is None or part["stock_state"] == "BACKORDERED":
            continue
        claim["claim_state"] = "SUBMITTED"
        claim["block_reason"] = "NONE"
        bump(claim)
        affected_distributors.append(claim["distributor_id"])

    # hop 3: distributor counters
    refresh_open_claim_counts(affected_distributors)


# ---- part stock projection cascades (PRD 3.9) -------------------------
def reproject_part_stock(part):
    """Re-project stock_state and run the BACKORDERED entry/exit claim cascades."""
    previous = part["stock_state"]
    part["stock_state"] = calc.project_stock_state(part["on_hand_qty"],
                                                  part["reorder_point_qty"])
    if part["stock_state"] == previous:
        return
    affected_distributors = []
    if part["stock_state"] == "BACKORDERED":
        claims = [c for c in claims_of_part(part["id"])
                  if c["claim_state"] == "SUBMITTED"]
        for claim in order_created_asc(claims):
            claim["claim_state"] = "FULFILLMENT_BLOCKED"
            claim["block_reason"] = "PART_BACKORDERED"
            bump(claim)
            affected_distributors.append(claim["distributor_id"])
    elif previous == "BACKORDERED":
        claims = [c for c in claims_of_part(part["id"])
                  if c["claim_state"] == "FULFILLMENT_BLOCKED"
                  and c["block_reason"] == "PART_BACKORDERED"]
        for claim in order_created_asc(claims):
            build = db.builds.get(claim["build_order_id"])
            if build is not None and build["integrity_hold"]:
                continue  # unblocking is conjunctive (PRD 3.9)
            claim["claim_state"] = "SUBMITTED"
            claim["block_reason"] = "NONE"
            bump(claim)
            affected_distributors.append(claim["distributor_id"])
    refresh_open_claim_counts(affected_distributors)
