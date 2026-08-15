"""AdoptionCycle endpoints (PRD §3.1-§3.6, §3.10): CRUD, state machine,
board decision, award (OCC), budget appropriation / ledger / forecast, and
the cycle-scoped nested creates (materials, pilots, quotes, purchase orders).
"""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import serializers
from db import bump, new_id, now_clock, refresh, stamp_new, store
from errors import (ERR_ALIGNMENT_COVERAGE, ERR_BID_RULE_NOT_SATISFIED,
                    ERR_COMPOSITE_BELOW_THRESHOLD, ERR_FRAMEWORK_MISMATCH,
                    ERR_INVALID_STATE, ERR_NO_VETTED_MATERIALS,
                    ERR_OPEN_WORK_REMAINS, ERR_PARTICIPATION_BELOW_FLOOR,
                    ERR_PUBLIC_REVIEW_NOT_CLOSED,
                    ERR_PUBLIC_REVIEW_WINDOW_CONFLICT,
                    ERR_QUOTE_MATERIAL_MISMATCH, ERR_QUOTE_NOT_AWARD_WINNER,
                    ERR_QUOTE_NOT_SELECTED, ERR_UNRESOLVED_PILOTS,
                    budget_exceeded, conflict, invalid_state, stale_cycle_version,
                    validation)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, opt_enum,
                        opt_int, opt_decimal, req_decimal, req_enum, req_int,
                        req_str, require_roles)
from response import paginate, sort_created, success_object
from services import cascades
from services.calculations import (ADOPTION_COVERAGE_THRESHOLD_PCT,
                                   COMPOSITE_THRESHOLD, FORMAL_BID_THRESHOLD,
                                   PARTICIPATION_FLOOR, best_value_scores,
                                   budget_forecast, bundled_pricing_total,
                                   ledger_available)

bp = Blueprint("cycles", __name__)

SUBJECT_AREAS = ("MATHEMATICS", "ENGLISH_LANGUAGE_ARTS", "SCIENCE",
                 "SOCIAL_STUDIES", "WORLD_LANGUAGES")
GRADE_BANDS = ("K_5", "GRADES_6_8", "GRADES_9_12")
AWARD_METHODS = ("LOWEST_RESPONSIVE", "BEST_VALUE")

# Per-target-state role gating (SCAFFOLD §1.7 shared_operations).
CYCLE_TRANSITION_ROLES = {
    "ALIGNMENT_REVIEW": ("InstructionalSpecialist",),
    "PILOT_OPEN": ("InstructionalSpecialist",),
    "DRAFT": ("CurriculumDirector",),
    "SCORING": ("CurriculumDirector",),
    "PUBLIC_REVIEW": ("BoardSecretary",),
    "BOARD_PENDING": ("BoardSecretary",),
    "ACTIVE": ("CurriculumDirector",),
    "SUNSET": ("CurriculumDirector",),
}

PUBLIC_REVIEW_WINDOW_DAYS = 30
PUBLIC_REVIEW_CLEAR_GAP_DAYS = 30


def _get_cycle(cycle_id):
    return get_or_404(store.cycles, cycle_id, "AdoptionCycle")


# ---------------------------------------------------------------------------
# Cycle CRUD
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles", methods=["POST"])
def create_cycle():
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector",))
    body = get_body()
    # Tier 3 (body FK existence) precedes remaining tier-4 shape checks
    # (PRD §2.7): resolve framework_id when present.
    framework = None
    raw_framework_id = body.get("framework_id")
    if isinstance(raw_framework_id, str) and raw_framework_id:
        framework = get_or_404(store.frameworks, raw_framework_id,
                               "CurriculumFramework")
    subject_area = req_enum(body, "subject_area", SUBJECT_AREAS)
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    school_year_start = req_int(body, "school_year_start")
    framework_id = req_str(body, "framework_id")
    if framework is None:
        framework = get_or_404(store.frameworks, framework_id,
                               "CurriculumFramework")
    district_enrollment = req_int(body, "district_enrollment", minimum=0)
    award_method = opt_enum(body, "award_method", AWARD_METHODS,
                            default="LOWEST_RESPONSIVE")
    # Tier 11 (referential): framework must be ACTIVE and match subject/grade.
    if (framework["status"] != "ACTIVE"
            or framework["subject_area"] != subject_area
            or framework["grade_band"] != grade_band):
        raise conflict(ERR_FRAMEWORK_MISMATCH,
                       "framework is retired or does not match the cycle's "
                       "subject_area/grade_band")
    cycle = {
        "id": new_id(),
        "subject_area": subject_area,
        "grade_band": grade_band,
        "school_year_start": school_year_start,
        "framework_id": framework_id,
        "award_method": award_method,
        "district_enrollment": district_enrollment,
        "status": "DRAFT",
        "public_review_opens_at": None,
        "public_review_closes_at": None,
        "adopted_material_id": None,
        "pinned_quote_id": None,
        "quote_version_pin": None,
        "open_backorder_count": 0,
        "replacement_due": False,
    }
    stamp_new(cycle)
    store.cycles[cycle["id"]] = cycle
    # BudgetLedger auto-created with the cycle, all totals zero (PRD §2.10).
    ledger = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "appropriation_total": Decimal("0"),
        "encumbered_total": Decimal("0"),
        "expended_total": Decimal("0"),
    }
    stamp_new(ledger)
    store.ledgers[cycle["id"]] = ledger
    return success_object(serializers.cycle(cycle), status=201)


@bp.route("/adoption-cycles", methods=["GET"])
def list_cycles():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.cycles.values())
    framework_id = request.args.get("framework_id")
    subject_area = request.args.get("subject_area")
    status = request.args.get("status")
    if framework_id is not None:
        items = [c for c in items if c["framework_id"] == framework_id]
    if subject_area is not None:
        items = [c for c in items if c["subject_area"] == subject_area]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(sort_created(items), serializers.cycle)


@bp.route("/adoption-cycles/<cycleId>", methods=["GET"])
def get_cycle(cycleId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.cycle(_get_cycle(cycleId)))


# ---------------------------------------------------------------------------
# Cycle state machine (PRD §3.1-§3.4, §3.7)
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles/<cycleId>/transitions", methods=["POST"])
def cycle_transition(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector", "InstructionalSpecialist",
                         "BoardSecretary"))
    cycle = _get_cycle(cycleId)
    body = get_body()
    to_state = req_enum(body, "to_state", tuple(CYCLE_TRANSITION_ROLES))
    require_roles(role, CYCLE_TRANSITION_ROLES[to_state])

    status = cycle["status"]

    if to_state == "ALIGNMENT_REVIEW":
        if status != "DRAFT":
            raise invalid_state("cycle must be DRAFT to enter ALIGNMENT_REVIEW")
    elif to_state == "DRAFT":
        if status != "ALIGNMENT_REVIEW":
            raise invalid_state("cycle must be ALIGNMENT_REVIEW to return to DRAFT")
    elif to_state == "PILOT_OPEN":
        if status != "ALIGNMENT_REVIEW":
            raise invalid_state("cycle must be ALIGNMENT_REVIEW to open pilots")
        vetted = [m for m in store.materials.values()
                  if m["cycle_id"] == cycle["id"]
                  and m["adoption_status"] == "VETTED"]
        if not vetted:
            raise conflict(ERR_NO_VETTED_MATERIALS,
                           "no VETTED material exists in this cycle")
        for m in vetted:
            if m["coverage_pct"] < ADOPTION_COVERAGE_THRESHOLD_PCT:
                raise conflict(
                    ERR_ALIGNMENT_COVERAGE,
                    "VETTED material %s coverage_pct is below 85.00" % m["id"])
    elif to_state == "SCORING":
        if status != "PILOT_OPEN":
            raise invalid_state("cycle must be PILOT_OPEN to enter SCORING")
        unresolved = [p for p in store.pilots.values()
                      if p["cycle_id"] == cycle["id"]
                      and p["status"] not in ("CLOSED", "CANCELLED")]
        if unresolved:
            raise conflict(ERR_UNRESOLVED_PILOTS,
                           "every pilot of the cycle must be CLOSED or CANCELLED")
    elif to_state == "PUBLIC_REVIEW":
        if status == "SCORING":
            _check_public_review_gap(cycle)
        elif status == "BOARD_PENDING":
            pass  # remand: window re-opens below
        else:
            raise invalid_state(
                "cycle must be SCORING or BOARD_PENDING to enter PUBLIC_REVIEW")
    elif to_state == "BOARD_PENDING":
        if status != "PUBLIC_REVIEW":
            raise invalid_state("cycle must be PUBLIC_REVIEW to reach BOARD_PENDING")
        if now_clock() < cycle["public_review_closes_at"]:
            raise conflict(ERR_PUBLIC_REVIEW_NOT_CLOSED,
                           "the public review window has not closed")
    elif to_state == "ACTIVE":
        if status != "DISTRIBUTING":
            raise invalid_state("cycle must be DISTRIBUTING to become ACTIVE")
        open_pos = [po for po in store.purchase_orders.values()
                    if po["cycle_id"] == cycle["id"]
                    and po["order_status"] not in ("CLOSED", "CANCELLED", "SUPERSEDED")]
        open_dos = [
            do for do in store.distribution_orders.values()
            if do["material_id"] == cycle.get("adopted_material_id")
            and do["status"] not in ("RECEIVED", "CANCELLED")
        ]
        if open_pos or open_dos:
            raise conflict(ERR_OPEN_WORK_REMAINS,
                           "purchase orders or distribution orders are still open")
    elif to_state == "SUNSET":
        if status != "ACTIVE":
            raise invalid_state("cycle must be ACTIVE to sunset")

    # --- side effects -------------------------------------------------------
    if to_state == "SCORING":
        cascades.close_pilots_scoring(cycle)
    if to_state == "PUBLIC_REVIEW":
        # Both the initial opening (from SCORING) and the remand (from
        # BOARD_PENDING) stamp a fresh 30-day window (PRD §3.4).
        opens = now_clock()
        cycle["public_review_opens_at"] = opens
        cycle["public_review_closes_at"] = opens + timedelta(
            days=PUBLIC_REVIEW_WINDOW_DAYS)
    cycle["status"] = to_state
    bump(cycle)
    return success_object(serializers.cycle(cycle))


def _check_public_review_gap(cycle):
    """Temporal gap rule (PRD §3.4): for every other cycle with the same
    subject_area, status != NOT_ADOPTED, and a recorded window, the new
    [now, now+30d] window must leave a clear 30-day gap; a gap of exactly
    30 days conflicts."""
    new_opens = now_clock()
    new_closes = new_opens + timedelta(days=PUBLIC_REVIEW_WINDOW_DAYS)
    gap = timedelta(days=PUBLIC_REVIEW_CLEAR_GAP_DAYS)
    for other in store.cycles.values():
        if other["id"] == cycle["id"]:
            continue
        if other["subject_area"] != cycle["subject_area"]:
            continue
        if other["status"] == "NOT_ADOPTED":
            continue
        existing_opens = other.get("public_review_opens_at")
        if existing_opens is None:
            continue
        existing_closes = other["public_review_closes_at"]
        if new_opens > existing_closes + gap:
            continue
        if existing_opens > new_closes + gap:
            continue
        raise conflict(ERR_PUBLIC_REVIEW_WINDOW_CONFLICT,
                       "the new public review window does not stand clear of "
                       "an existing same-subject window by 30 days")


# ---------------------------------------------------------------------------
# Board decision (PRD §3.4)
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles/<cycleId>/board-decision", methods=["POST"])
def board_decision(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("BoardSecretary",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    # Tier 3 body FK resolution precedes the remaining shape checks.
    material = None
    raw_material_id = body.get("material_id")
    if isinstance(raw_material_id, str) and raw_material_id:
        material = get_or_404(store.materials, raw_material_id,
                              "InstructionalMaterial")
    decision = req_enum(body, "decision", ("ADOPT", "REJECT"))
    material_id = req_str(body, "material_id")
    if material is None:
        material = get_or_404(store.materials, material_id,
                              "InstructionalMaterial")

    if cycle["status"] != "BOARD_PENDING":
        raise invalid_state("board decision requires the cycle BOARD_PENDING")

    if decision == "ADOPT":
        if (material["cycle_id"] != cycle["id"]
                or material["adoption_status"] != "PILOT_CANDIDATE"):
            raise invalid_state(
                "the adopted material must be a PILOT_CANDIDATE of this cycle")
        # Composite gate runs first; the participation gate only after it.
        official = material.get("official_composite")
        if official is None or official < COMPOSITE_THRESHOLD:
            raise conflict(ERR_COMPOSITE_BELOW_THRESHOLD,
                           "official_composite is below 3.20")
        participation = material.get("participation_rate")
        if participation is None or participation < PARTICIPATION_FLOOR:
            raise conflict(ERR_PARTICIPATION_BELOW_FLOOR,
                           "participation_rate is below 0.60")
        material["adoption_status"] = "ADOPTED"
        material["adopted_at"] = now_clock()
        bump(material)
        cycle["adopted_material_id"] = material["id"]
        for other in store.materials.values():
            if (other["cycle_id"] == cycle["id"] and other["id"] != material["id"]
                    and other["adoption_status"] == "PILOT_CANDIDATE"):
                other["adoption_status"] = "REJECTED"
                bump(other)
        cycle["status"] = "ADOPTED"
    else:  # REJECT — the slate-killer
        for other in store.materials.values():
            if (other["cycle_id"] == cycle["id"]
                    and other["adoption_status"] == "PILOT_CANDIDATE"):
                other["adoption_status"] = "REJECTED"
                bump(other)
        cycle["status"] = "NOT_ADOPTED"
    bump(cycle)
    return success_object(serializers.cycle(cycle))


# ---------------------------------------------------------------------------
# Award (PRD §3.5, OCC-guarded per §2.8)
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles/<cycleId>/award", methods=["POST"])
def award(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    quote = None
    raw_quote_id = body.get("quote_id")
    if isinstance(raw_quote_id, str) and raw_quote_id:
        quote = get_or_404(store.quotes, raw_quote_id, "PublisherQuote")
    quote_id = req_str(body, "quote_id")
    expected_cycle_version = req_int(body, "expected_cycle_version")
    if quote is None:
        quote = get_or_404(store.quotes, quote_id, "PublisherQuote")

    # Tier 5 state preconditions, then tier 6 OCC, then business rules
    # (endpoint-pinned order: material match -> pool size -> winner rule).
    if cycle["status"] not in ("ADOPTED", "PROCURING"):
        raise invalid_state("award requires the cycle ADOPTED or PROCURING")
    if quote["status"] != "UNDER_EVALUATION":
        raise invalid_state("award target quote must be UNDER_EVALUATION")
    if expected_cycle_version != cycle["version"]:
        raise stale_cycle_version()

    if quote["material_id"] != cycle.get("adopted_material_id"):
        raise conflict(ERR_QUOTE_MATERIAL_MISMATCH,
                       "the quote's material is not the cycle's adopted material")

    pool = [q for q in store.quotes.values()
            if q["cycle_id"] == cycle["id"]
            and q["status"] == "UNDER_EVALUATION"
            and q["material_id"] == cycle["adopted_material_id"]]
    required = (3 if quote["evaluated_total"] >= FORMAL_BID_THRESHOLD else 2)
    if len(pool) < required:
        raise conflict(ERR_BID_RULE_NOT_SATISFIED,
                       "responsive pool smaller than the bid rule requires")

    if cycle["award_method"] == "BEST_VALUE":
        scores = best_value_scores(pool)
        # Winner: highest score, ties broken by earliest created_at.
        ranked = sorted(pool,
                        key=lambda q: (q["created_at"], q.get("_seq", 0)))
        best = None
        for q in ranked:
            if best is None or scores[q["id"]] > scores[best["id"]]:
                best = q
        winner = best
    else:  # LOWEST_RESPONSIVE: lowest evaluated_total, earliest created_at.
        ranked = sorted(pool,
                        key=lambda q: (q["evaluated_total"], q["created_at"],
                                       q.get("_seq", 0)))
        winner = ranked[0]
        scores = None

    if winner["id"] != quote["id"]:
        raise conflict(ERR_QUOTE_NOT_AWARD_WINNER,
                       "the award target is not the rule winner")

    # --- side effects (atomic: all checks passed) ---------------------------
    if cycle["award_method"] == "BEST_VALUE":
        for q in pool:
            q["best_value_score"] = scores[q["id"]]
            refresh(q)
    previous_pin = cycle.get("pinned_quote_id")
    if previous_pin is not None:
        previous = store.quotes.get(previous_pin)
        if previous is not None and previous["status"] == "SELECTED":
            previous["status"] = "SUPERSEDED"
            bump(previous)
    quote["status"] = "SELECTED"
    bump(quote)
    for q in pool:
        if q["id"] != quote["id"]:
            q["status"] = "REJECTED"
            bump(q)
    cycle["pinned_quote_id"] = quote["id"]
    cycle["quote_version_pin"] = quote["version"]
    if cycle["status"] == "ADOPTED":
        cycle["status"] = "PROCURING"
    bump(cycle)
    return success_object(serializers.cycle(cycle))


# ---------------------------------------------------------------------------
# Budget appropriation / ledger / forecast (PRD §3.1, §2.10, §3.10)
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles/<cycleId>/budget-appropriation", methods=["POST"])
def budget_appropriation(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("DistrictAdmin",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    amount = req_decimal(body, "amount", minimum=Decimal("0"),
                         exclusive_minimum=True)
    ledger = store.ledgers[cycle["id"]]
    ledger["appropriation_total"] += amount
    refresh(ledger)
    return success_object(serializers.budget_ledger(ledger))


@bp.route("/adoption-cycles/<cycleId>/budget-ledger", methods=["GET"])
def budget_ledger(cycleId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    cycle = _get_cycle(cycleId)
    ledger = store.ledgers.get(cycle["id"])
    items = [ledger] if ledger is not None else []
    return paginate(sort_created(items), serializers.budget_ledger)


@bp.route("/adoption-cycles/<cycleId>/budget-forecast", methods=["GET"])
def budget_forecast_endpoint(cycleId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    cycle = _get_cycle(cycleId)
    variant = request.args.get("variant")
    if variant not in ("ROLLING", "STRAIGHT_LINE"):
        raise validation("query parameter variant must be ROLLING or STRAIGHT_LINE")
    result = budget_forecast(cycle, variant)
    return success_object({
        "variant": result["variant"],
        "base_amount": float(result["base_amount"]),
        "contingency_rate": float(result["contingency_rate"]),
        "forecast_total": float(result["forecast_total"]),
    })


# ---------------------------------------------------------------------------
# Nested creates under a cycle: materials, pilots, quotes, purchase orders
# ---------------------------------------------------------------------------


@bp.route("/adoption-cycles/<cycleId>/materials", methods=["POST"])
def create_material(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    title = req_str(body, "title")
    publisher_name = req_str(body, "publisher_name")
    isbn = body.get("isbn")
    if isbn is not None and not isinstance(isbn, str):
        raise validation("field isbn must be a string")
    material_type = opt_enum(body, "material_type", ("CORE", "SUPPLEMENTAL"),
                             default="CORE")
    if cycle["status"] not in ("DRAFT", "ALIGNMENT_REVIEW"):
        raise invalid_state(
            "materials may only be submitted while the cycle is DRAFT or "
            "ALIGNMENT_REVIEW")
    material = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "title": title,
        "publisher_name": publisher_name,
        "isbn": isbn,
        "material_type": material_type,
        "adoption_status": "SUBMITTED",
        "availability_status": "USABLE",
        "coverage_pct": Decimal("0.00"),
        "provisional_composite": None,
        "official_composite": None,
        "participation_rate": None,
        "adopted_at": None,
    }
    stamp_new(material)
    store.materials[material["id"]] = material
    return success_object(serializers.material(material), status=201)


@bp.route("/adoption-cycles/<cycleId>/pilots", methods=["POST"])
def create_pilot(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    material = None
    raw_material_id = body.get("material_id")
    if isinstance(raw_material_id, str) and raw_material_id:
        material = get_or_404(store.materials, raw_material_id,
                              "InstructionalMaterial")
    school_code = req_str(body, "school_code")
    from middleware import req_iso_date
    starts_on = req_iso_date(body, "starts_on")
    ends_on = req_iso_date(body, "ends_on")
    teacher_count = req_int(body, "teacher_count", minimum=1)
    material_id = req_str(body, "material_id")
    if material is None:
        material = get_or_404(store.materials, material_id,
                              "InstructionalMaterial")
    if ends_on <= starts_on:
        raise validation("ends_on must be after starts_on")
    # Tier 5 state gates: cycle PILOT_OPEN; material of this cycle and VETTED.
    if cycle["status"] != "PILOT_OPEN":
        raise invalid_state("pilots may only be planned while the cycle is "
                            "PILOT_OPEN")
    if material["cycle_id"] != cycle["id"] or material["adoption_status"] != "VETTED":
        raise invalid_state("the piloted material must belong to this cycle and "
                            "be VETTED")
    # Tier 8 interval occupation: half-open [starts_on, ends_on) overlap with
    # PLANNED/ACTIVE pilots at the same school for the cycle's subject.
    for other in store.pilots.values():
        if other["school_code"] != school_code:
            continue
        if other["status"] not in ("PLANNED", "ACTIVE"):
            continue
        other_cycle = store.cycles.get(other["cycle_id"])
        if other_cycle is None or other_cycle["subject_area"] != cycle["subject_area"]:
            continue
        if starts_on < other["ends_on"] and other["starts_on"] < ends_on:
            from errors import ERR_PILOT_WINDOW_CONFLICT
            raise conflict(ERR_PILOT_WINDOW_CONFLICT,
                           "the pilot window overlaps an existing pilot at this "
                           "school for this subject")
    pilot = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "material_id": material["id"],
        "school_code": school_code,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "teacher_count": teacher_count,
        "status": "PLANNED",
    }
    stamp_new(pilot)
    store.pilots[pilot["id"]] = pilot
    return success_object(serializers.pilot(pilot), status=201)


QUOTE_CYCLE_STATES = ("PILOT_OPEN", "SCORING", "PUBLIC_REVIEW", "BOARD_PENDING",
                      "ADOPTED", "PROCURING")
QUOTE_MATERIAL_STATES = ("VETTED", "PILOT_CANDIDATE", "ADOPTED")
QUOTE_PRICING_FIELDS = ("print_unit_price", "print_quantity", "digital_seat_rate",
                        "digital_seat_count", "bundle_discount_pct",
                        "training_sessions", "license_years")


@bp.route("/adoption-cycles/<cycleId>/quotes", methods=["POST"])
def create_quote(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    material = None
    raw_material_id = body.get("material_id")
    if isinstance(raw_material_id, str) and raw_material_id:
        material = get_or_404(store.materials, raw_material_id,
                              "InstructionalMaterial")
    publisher_name = req_str(body, "publisher_name")
    print_unit_price = req_decimal(body, "print_unit_price", minimum=Decimal("0"))
    print_quantity = req_int(body, "print_quantity", minimum=0)
    digital_seat_rate = req_decimal(body, "digital_seat_rate", minimum=Decimal("0"))
    digital_seat_count = req_int(body, "digital_seat_count", minimum=0)
    bundle_discount_pct = opt_decimal(body, "bundle_discount_pct",
                                      minimum=Decimal("0"), maximum=Decimal("1"),
                                      default=Decimal("0"))
    training_sessions = req_int(body, "training_sessions", minimum=0)
    license_years = req_int(body, "license_years", minimum=0)
    material_id = req_str(body, "material_id")
    if material is None:
        material = get_or_404(store.materials, material_id,
                              "InstructionalMaterial")
    if cycle["status"] not in QUOTE_CYCLE_STATES:
        raise invalid_state("quotes may only be submitted while the cycle is in "
                            "PILOT_OPEN, SCORING, PUBLIC_REVIEW, BOARD_PENDING, "
                            "ADOPTED, or PROCURING")
    if (material["cycle_id"] != cycle["id"]
            or material["adoption_status"] not in QUOTE_MATERIAL_STATES):
        raise invalid_state("the quoted material must belong to this cycle and be "
                            "VETTED, PILOT_CANDIDATE, or ADOPTED")
    quote = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "material_id": material["id"],
        "publisher_name": publisher_name,
        "print_unit_price": print_unit_price,
        "print_quantity": print_quantity,
        "digital_seat_rate": digital_seat_rate,
        "digital_seat_count": digital_seat_count,
        "bundle_discount_pct": bundle_discount_pct,
        "training_sessions": training_sessions,
        "license_years": license_years,
        "evaluated_total": None,
        "best_value_score": None,
        "status": "SUBMITTED",
        "submitted_at": now_clock(),
    }
    stamp_new(quote)
    store.quotes[quote["id"]] = quote
    return success_object(serializers.quote(quote), status=201)


@bp.route("/adoption-cycles/<cycleId>/purchase-orders", methods=["POST"])
def create_purchase_order(cycleId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    cycle = _get_cycle(cycleId)
    body = get_body()
    quote = None
    raw_quote_id = body.get("quote_id")
    if isinstance(raw_quote_id, str) and raw_quote_id:
        quote = get_or_404(store.quotes, raw_quote_id, "PublisherQuote")
    print_quantity = req_int(body, "print_quantity", minimum=1)
    digital_seat_count = req_int(body, "digital_seat_count", minimum=0)
    expected_cycle_version = req_int(body, "expected_cycle_version")
    quote_id = req_str(body, "quote_id")
    if quote is None:
        quote = get_or_404(store.quotes, quote_id, "PublisherQuote")

    # Tier 6 OCC before the tier-10 pin/business rules (PRD §2.7).
    if expected_cycle_version != cycle["version"]:
        raise stale_cycle_version()
    if (quote["status"] != "SELECTED"
            or quote["id"] != cycle.get("pinned_quote_id")
            or quote["version"] != cycle.get("quote_version_pin")):
        raise conflict(ERR_QUOTE_NOT_SELECTED,
                       "the quote is not the cycle's currently pinned SELECTED "
                       "quote")
    total_amount = bundled_pricing_total(
        quote["print_unit_price"], print_quantity,
        quote["digital_seat_rate"], digital_seat_count,
        quote.get("bundle_discount_pct") or Decimal("0"))
    ledger = store.ledgers[cycle["id"]]
    if ledger_available(ledger) < total_amount:
        raise budget_exceeded()

    for existing in store.purchase_orders.values():
        if existing["cycle_id"] == cycle["id"] and existing["order_status"] == "DRAFT":
            existing["order_status"] = "SUPERSEDED"
            bump(existing)
    po = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "quote_id": quote["id"],
        "print_quantity": print_quantity,
        "digital_seat_count": digital_seat_count,
        "total_amount": total_amount,
        "amount_paid": Decimal("0"),
        "received_print_qty": 0,
        "quote_version_pin": quote["version"],
        "order_status": "DRAFT",
        "payment_status": "UNENCUMBERED",
    }
    stamp_new(po)
    store.purchase_orders[po["id"]] = po
    bump(cycle)  # PO creation bumps the cycle version (SCAFFOLD §1.5)
    return success_object(serializers.purchase_order(po), status=201)
