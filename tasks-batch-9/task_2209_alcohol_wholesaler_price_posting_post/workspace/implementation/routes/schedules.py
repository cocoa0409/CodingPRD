"""Price schedules, schedule items, posted-price resolution and the posting run.

PRD sections 3.3, 3.4 and 3.7.
"""

from flask import Blueprint

import calc
import services
from auth import (
    ALL_ROLES,
    ROLE_CERTIFYING_OFFICER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FILING_AGENT,
    authenticate,
    require_scope,
)
from envelope import object_response
from errors import raise_err
from serialize import out
from store import (
    bump,
    db,
    dt_of,
    fmt_iso,
    new_record,
    now_dt,
    now_iso,
    seq_of,
    sorted_records,
)
from validators import (
    Field,
    collection_response,
    must_find,
    query_enum,
    query_instant,
    validate_body,
)

bp = Blueprint("schedules", __name__)

SCHEDULE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "POSTED",
    "EFFECTIVE",
    "SUPERSEDED",
    "WITHDRAWN",
)
ITEM_STATUSES = ("DRAFT", "POSTED", "EFFECTIVE", "SUPERSEDED", "WITHDRAWN")
POSTED_PRICE_VARIANTS = ("as_amended", "as_certified")


# ---------------------------------------------------------------------------
# price schedules
# ---------------------------------------------------------------------------
@bp.post("/price-schedules")
def create_price_schedule():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("wholesaler_id", "string"),
            Field("state_program_id", "string"),
            Field("posting_month", "month"),
        ]
    )
    must_find("wholesaler", values["wholesaler_id"])
    must_find("state_program", values["state_program_id"])
    require_scope(actor, values["wholesaler_id"])

    # Priority 14 -- one live schedule per wholesaler per posting month.
    for existing in db.price_schedules.values():
        if existing["wholesaler_id"] != values["wholesaler_id"]:
            continue
        if existing["posting_month"] != values["posting_month"]:
            continue
        if existing["status"] == "WITHDRAWN":
            continue
        raise_err("ERR_DUPLICATE_POSTING_MONTH")

    record = new_record(
        {
            "wholesaler_id": values["wholesaler_id"],
            "state_program_id": values["state_program_id"],
            "posting_month": values["posting_month"],
            "effective_date": calc.schedule_effective_date(values["posting_month"]),
            "status": "DRAFT",
            "filed_at": None,
            "filed_by_user_id": None,
            "certified_at": None,
            "certified_by_user_id": None,
            "hold_window_ends_at": None,
            "is_late": False,
            "return_reason": None,
            "return_count": 0,
            "correction_count": 0,
            "item_count": 0,
            "superseded_by_schedule_id": None,
        }
    )
    db.price_schedules[record["id"]] = record
    return object_response(out(record), 201)


@bp.post("/price-schedules/<record_id>/submit")
def submit_price_schedule(record_id):
    actor = authenticate([ROLE_FILING_AGENT])
    schedule = must_find("price_schedule", record_id)
    require_scope(actor, schedule["wholesaler_id"])
    if schedule["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE")

    wholesaler = db.wholesalers[schedule["wholesaler_id"]]
    program = db.state_programs[schedule["state_program_id"]]

    # Priority 9 -- licence standing.
    if wholesaler["license_status"] != "ACTIVE":
        raise_err("ERR_LICENSE_NOT_ACTIVE")

    # Priority 10 -- brand registration prerequisite.
    items = sorted_records(services.items_of_schedule(schedule["id"]))
    effective_date = dt_of(schedule["effective_date"])
    for item in items:
        brand = db.brands[item["brand_id"]]
        if brand["registration_status"] != "APPROVED":
            raise_err("ERR_BRAND_NOT_REGISTERED")
        registered_from = dt_of(brand["registration_effective_from"])
        registered_to = dt_of(brand["registration_expires_on"])
        if not (registered_from <= effective_date <= registered_to):
            raise_err("ERR_BRAND_NOT_REGISTERED")

    # Priority 19 -- cardinality.
    if not items:
        raise_err("ERR_SCHEDULE_HAS_NO_ITEMS")

    filed_at = now_dt()
    schedule["status"] = "SUBMITTED"
    schedule["filed_at"] = fmt_iso(filed_at)
    schedule["filed_by_user_id"] = actor.user["id"]
    schedule["is_late"] = calc.is_late_filing(
        schedule["posting_month"], program["posting_deadline_day"], filed_at
    )
    bump(schedule)

    if schedule["is_late"]:
        wholesaler["late_filing_count"] += 1
        wholesaler["late_filing_penalty_accrued_cents"] += program[
            "late_filing_penalty_cents"
        ]
        services.recompute_exposure(wholesaler)
        bump(wholesaler)

    return object_response(out(schedule))


@bp.post("/price-schedules/<record_id>/return-for-correction")
def return_price_schedule(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    schedule = must_find("price_schedule", record_id)
    values = validate_body([Field("return_reason", "string")])
    if schedule["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE")
    schedule["status"] = "DRAFT"
    schedule["return_reason"] = values["return_reason"]
    schedule["return_count"] += 1
    bump(schedule)
    return object_response(out(schedule))


@bp.post("/price-schedules/<record_id>/certify")
def certify_price_schedule(record_id):
    actor = authenticate([ROLE_CERTIFYING_OFFICER])
    schedule = must_find("price_schedule", record_id)
    require_scope(actor, schedule["wholesaler_id"])
    if schedule["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE")

    # Priority 16 -- segregation of duties.
    if schedule["filed_by_user_id"] is not None and (
        actor.user["id"] == schedule["filed_by_user_id"]
    ):
        raise_err("ERR_SEGREGATION_OF_DUTIES")

    program = db.state_programs[schedule["state_program_id"]]
    certified_at = now_dt()
    window_end = calc.hold_window_end(certified_at, program["hold_window_days"])

    # Priority 21 -- the hold window must end strictly before the effective date.
    if not window_end < dt_of(schedule["effective_date"]):
        raise_err("ERR_HOLD_WINDOW_OVERRUNS_EFFECTIVE")

    schedule["status"] = "POSTED"
    schedule["certified_at"] = fmt_iso(certified_at)
    schedule["certified_by_user_id"] = actor.user["id"]
    schedule["hold_window_ends_at"] = fmt_iso(window_end)
    bump(schedule)

    for item in sorted_records(services.items_of_schedule(schedule["id"])):
        if item["status"] != "DRAFT":
            continue
        item["status"] = "POSTED"
        item["certified_case_price_cents"] = item["case_price_cents"]
        item["certified_unit_price_cents"] = item["unit_price_cents"]
        bump(item)

    return object_response(out(schedule))


@bp.post("/price-schedules/<record_id>/withdraw")
def withdraw_price_schedule(record_id):
    actor = authenticate([ROLE_FILING_AGENT])
    schedule = must_find("price_schedule", record_id)
    require_scope(actor, schedule["wholesaler_id"])
    if schedule["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE")

    for item in sorted_records(services.items_of_schedule(schedule["id"])):
        if item["status"] == "WITHDRAWN":
            continue
        item["status"] = "WITHDRAWN"
        bump(item)

    was_late = schedule["is_late"]
    schedule["status"] = "WITHDRAWN"
    bump(schedule)

    if was_late:
        wholesaler = db.wholesalers[schedule["wholesaler_id"]]
        program = db.state_programs[schedule["state_program_id"]]
        wholesaler["late_filing_count"] -= 1
        wholesaler["late_filing_penalty_accrued_cents"] -= program[
            "late_filing_penalty_cents"
        ]
        services.recompute_exposure(wholesaler)
        bump(wholesaler)

    return object_response(out(schedule))


@bp.get("/price-schedules/<record_id>")
def get_price_schedule(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("price_schedule", record_id)))


@bp.get("/price-schedules")
def list_price_schedules():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.price_schedules.values()),
        {
            "wholesaler_id": None,
            "state_program_id": None,
            "posting_month": None,
            "status": SCHEDULE_STATUSES,
            "filed_by_user_id": None,
            "certified_by_user_id": None,
            "superseded_by_schedule_id": None,
        },
        out,
    )


# ---------------------------------------------------------------------------
# price schedule items
# ---------------------------------------------------------------------------
@bp.post("/price-schedule-items")
def create_price_schedule_item():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("schedule_id", "string"),
            Field("brand_id", "string"),
            Field("size_ml", "int", minimum=1),
            Field("bottles_per_case", "int", minimum=1),
            Field("case_price_cents", "int", minimum=1),
            Field("unit_price_cents", "int", minimum=1),
        ]
    )
    schedule = must_find("price_schedule", values["schedule_id"])
    must_find("brand", values["brand_id"])
    require_scope(actor, schedule["wholesaler_id"])

    # Priority 14 -- brand, size and package are unique inside one schedule.
    for existing in services.items_of_schedule(schedule["id"]):
        if (
            existing["brand_id"] == values["brand_id"]
            and existing["size_ml"] == values["size_ml"]
            and existing["bottles_per_case"] == values["bottles_per_case"]
        ):
            raise_err("ERR_DUPLICATE_SCHEDULE_ITEM")

    # Priority 17 -- a case may not cost more than the bottles bought separately.
    if values["unit_price_cents"] * values["bottles_per_case"] < values["case_price_cents"]:
        raise_err("ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE")

    record = new_record(
        {
            "schedule_id": values["schedule_id"],
            "brand_id": values["brand_id"],
            "size_ml": values["size_ml"],
            "bottles_per_case": values["bottles_per_case"],
            "case_price_cents": values["case_price_cents"],
            "unit_price_cents": values["unit_price_cents"],
            "certified_case_price_cents": None,
            "certified_unit_price_cents": None,
            "status": "DRAFT",
            "amendment_count": 0,
            "correction_count": 0,
            "supersedes_item_id": None,
        }
    )
    db.price_schedule_items[record["id"]] = record
    schedule["item_count"] += 1
    bump(schedule)
    return object_response(out(record), 201)


@bp.get("/price-schedule-items/<record_id>")
def get_price_schedule_item(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("price_schedule_item", record_id)))


@bp.get("/price-schedule-items")
def list_price_schedule_items():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.price_schedule_items.values()),
        {
            "schedule_id": None,
            "brand_id": None,
            "supersedes_item_id": None,
            "status": ITEM_STATUSES,
        },
        out,
    )


@bp.get("/price-schedule-items/<record_id>/posted-price")
def item_posted_price(record_id):
    authenticate(ALL_ROLES)
    item = must_find("price_schedule_item", record_id)
    as_of = query_instant("as_of", now_dt())
    variant = query_enum("variant", POSTED_PRICE_VARIANTS, "as_amended")
    resolved = calc.resolve_posted_item(item, as_of)
    posted_case, posted_unit = calc.posted_prices(resolved, variant)
    return object_response(
        {
            "item_id": item["id"],
            "variant": variant,
            "as_of": fmt_iso(as_of),
            "resolved_item_id": resolved["id"] if resolved is not None else None,
            "posted_case_price_cents": posted_case if resolved is not None else None,
            "posted_unit_price_cents": posted_unit if resolved is not None else None,
        }
    )


# ---------------------------------------------------------------------------
# posting run (PRD section 3.7)
# ---------------------------------------------------------------------------
def _prior_effective_item(item, current_schedule_id):
    """The item currently EFFECTIVE under the same posting key, if there is one."""
    key = calc.posting_key(item)
    best = None
    best_rank = None
    for candidate in db.price_schedule_items.values():
        if candidate["id"] == item["id"]:
            continue
        if candidate["schedule_id"] == current_schedule_id:
            continue
        if candidate["status"] != "EFFECTIVE":
            continue
        if calc.posting_key(candidate) != key:
            continue
        schedule = db.price_schedules[candidate["schedule_id"]]
        rank = (
            dt_of(schedule["effective_date"]),
            dt_of(schedule["certified_at"]) or dt_of(schedule["created_at"]),
            dt_of(candidate["created_at"]),
            seq_of(candidate),
        )
        if best is None or calc._resolution_better(rank, best_rank):
            best = candidate
            best_rank = rank
    return best


@bp.post("/posting-runs")
def posting_run():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body([Field("state_program_id", "string")])
    program = must_find("state_program", values["state_program_id"])

    run_at = now_dt()
    eligible = []
    for schedule in db.price_schedules.values():
        if schedule["state_program_id"] != program["id"]:
            continue
        if schedule["status"] != "POSTED":
            continue
        effective_date = dt_of(schedule["effective_date"])
        window_end = dt_of(schedule["hold_window_ends_at"])
        if effective_date is None or effective_date > run_at:
            continue
        if window_end is None or window_end > run_at:
            continue
        eligible.append(schedule)

    eligible.sort(
        key=lambda s: (
            dt_of(s["effective_date"]),
            dt_of(s["certified_at"]) or dt_of(s["created_at"]),
            dt_of(s["created_at"]),
            seq_of(s),
        )
    )

    effective_schedules = []
    superseded_schedules = []
    for schedule in eligible:
        newly_effective = []
        for item in sorted_records(services.items_of_schedule(schedule["id"])):
            if item["status"] != "POSTED":
                continue
            item["status"] = "EFFECTIVE"
            bump(item)
            newly_effective.append(item)
        schedule["status"] = "EFFECTIVE"
        bump(schedule)
        effective_schedules.append(schedule)

        displaced_schedule_ids = []
        for item in newly_effective:
            prior = _prior_effective_item(item, schedule["id"])
            if prior is None:
                continue
            prior["status"] = "SUPERSEDED"
            bump(prior)
            item["supersedes_item_id"] = prior["id"]
            bump(item)
            for tier in services.tiers_of_item(prior["id"]):
                if tier["status"] != "ACTIVE":
                    continue
                tier["status"] = "INACTIVE"
                bump(tier)
            if prior["schedule_id"] not in displaced_schedule_ids:
                displaced_schedule_ids.append(prior["schedule_id"])

        for schedule_id in displaced_schedule_ids:
            older = db.price_schedules[schedule_id]
            if older["status"] != "EFFECTIVE":
                continue
            older_items = services.items_of_schedule(schedule_id)
            if not older_items:
                continue
            if any(i["status"] != "SUPERSEDED" for i in older_items):
                continue
            older["status"] = "SUPERSEDED"
            older["superseded_by_schedule_id"] = schedule["id"]
            bump(older)
            superseded_schedules.append(older)

    return object_response(
        {
            "state_program_id": program["id"],
            "run_at": fmt_iso(run_at),
            "processed_schedule_count": len(effective_schedules),
            "effective_schedule_ids": [
                s["id"] for s in sorted_records(effective_schedules)
            ],
            "superseded_schedule_ids": [
                s["id"] for s in sorted_records(superseded_schedules)
            ],
        }
    )
