from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_AMENDED_STATEMENT_NOT_FINAL,
    ERR_EMPTY_STATEMENT,
    ERR_GROSS_MISMATCH,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_CONFIRMED_SPLIT_SET,
    ERR_NO_MATCHED_LINES,
    ERR_STATEMENT_ALREADY_SUPERSEDED,
    ERR_STATEMENT_PERIOD_OVERLAP,
    ERR_VALIDATION,
    ERR_WORK_NOT_REGISTERED,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import allocation_line_view, statement_line_view, statement_view
from services import (
    apply_recoupment,
    auto_match_line,
    compute_allocations,
    confirmed_split_set,
    get_or_404,
    new_record,
    recompute_work_rollup,
    recompute_writer_rollups,
    sorted_all,
    statement_lines_of,
    supersede_statement,
    touch,
)
from validators import (
    body_json, opt_str, paginate, pagination_params, req_dt, req_enum,
    req_int, req_str,
)

bp = Blueprint("statements", __name__)

SOURCE_TYPES = ["SOCIETY", "LICENSEE", "SUB_PUBLISHER"]
INCOME_TYPES = ["PERFORMANCE", "MECHANICAL", "SYNC", "PRINT", "OTHER"]
SOURCE_COLLECTIONS = {
    "SOCIETY": "societies",
    "LICENSEE": "licensees",
    "SUB_PUBLISHER": "sub_publishers",
}


def _validate_statement_lines(raw):
    if not isinstance(raw, list):
        raise ApiError(ERR_VALIDATION, 422, "lines must be an array")
    seen_numbers = set()
    lines = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError(ERR_VALIDATION, 422, "lines[%d] must be an object" % idx)
        line_number = req_int(item, "line_number", lo=1)
        if line_number in seen_numbers:
            raise ApiError(ERR_VALIDATION, 422,
                           "line_number must be unique within the statement")
        seen_numbers.add(line_number)
        reported_title = req_str(item, "reported_title")
        reported_iswc = opt_str(item, "reported_iswc")
        reported_work_code = opt_str(item, "reported_work_code")
        gross_cents = req_int(item, "gross_cents", lo=1)
        lines.append({
            "line_number": line_number,
            "reported_title": reported_title,
            "reported_iswc": reported_iswc,
            "reported_work_code": reported_work_code,
            "gross_cents": gross_cents,
        })
    return lines


@bp.route("/royalty-statements", methods=["POST"], strict_slashes=False)
def create_statement():
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    body = body_json()
    # reference resolution (tier 3)
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    source_id = body.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise ApiError(ERR_VALIDATION, 422, "source_id is required")
    get_or_404(SOURCE_COLLECTIONS[source_type], source_id, "statement source")
    amends_id = body.get("amends_statement_id")
    target = None
    if amends_id is not None:
        if not isinstance(amends_id, str) or not amends_id:
            raise ApiError(ERR_VALIDATION, 422,
                           "amends_statement_id must be a string or null")
        target = get_or_404("royalty_statements", amends_id, "amended statement")
    # request shape (tier 4)
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    territory_code = req_str(body, "territory_code")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_start > period_end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "period_end must be on or after period_start")
    gross_amount_cents = req_int(body, "gross_amount_cents", lo=0)
    lines = _validate_statement_lines(body.get("lines", []))
    # amendment state gates (tier 5; superseded checked before not-final)
    if target is not None:
        if target["status"] == "SUPERSEDED":
            raise ApiError(ERR_STATEMENT_ALREADY_SUPERSEDED, 409,
                           "the amended statement is already SUPERSEDED")
        if target["status"] != "FINALIZED":
            raise ApiError(ERR_AMENDED_STATEMENT_NOT_FINAL, 409,
                           "only a FINALIZED statement may be amended")
    # period overlap (tier 8): closed-inclusive, same source/income/territory,
    # excluding REJECTED / SUPERSEDED statements and the amends target
    for other in STORE["royalty_statements"].values():
        if target is not None and other["id"] == target["id"]:
            continue
        if other["status"] in ("REJECTED", "SUPERSEDED"):
            continue
        if other["source_type"] != source_type or other["source_id"] != source_id:
            continue
        if other["income_type"] != income_type:
            continue
        if other["territory_code"] != territory_code:
            continue
        if other["period_start"] <= period_end and period_start <= other["period_end"]:
            raise ApiError(ERR_STATEMENT_PERIOD_OVERLAP, 409,
                           "statement period overlaps an existing statement "
                           "for the same source, income type and territory")
    st = new_record()
    st.update({
        "source_type": source_type,
        "source_id": source_id,
        "income_type": income_type,
        "territory_code": territory_code,
        "period_start": period_start,
        "period_end": period_end,
        "gross_amount_cents": gross_amount_cents,
        "amends_statement_id": amends_id,
        "status": "RECEIVED",
        "retained_cents": 0,
        "suspense_cents": 0,
        "allocated_total_cents": 0,
    })
    STORE["royalty_statements"][st["id"]] = st
    for spec in lines:
        line = new_record()
        line.update({
            "statement_id": st["id"],
            "line_number": spec["line_number"],
            "reported_title": spec["reported_title"],
            "reported_iswc": spec["reported_iswc"],
            "reported_work_code": spec["reported_work_code"],
            "gross_cents": spec["gross_cents"],
            "work_id": None,
            "match_status": "UNMATCHED",
        })
        STORE["statement_lines"][line["id"]] = line
    if target is not None:
        supersede_statement(target)
    return success(statement_view(st), status=201)


@bp.route("/royalty-statements", methods=["GET"], strict_slashes=False)
def list_statements():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("royalty_statements")
    source_id = request.args.get("source_id")
    income_type = request.args.get("income_type")
    status = request.args.get("status")
    amends = request.args.get("amends_statement_id")
    if source_id is not None:
        items = [s for s in items if s["source_id"] == source_id]
    if income_type is not None:
        items = [s for s in items if s["income_type"] == income_type]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if amends is not None:
        items = [s for s in items if s["amends_statement_id"] == amends]
    page, meta = paginate(items, limit, offset)
    return success([statement_view(s) for s in page],
                   response_type="array", pagination=meta)


@bp.route("/royalty-statements/<sid>", methods=["GET"], strict_slashes=False)
def get_statement(sid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    st = get_or_404("royalty_statements", sid, "royalty statement")
    return success(statement_view(st))


@bp.route("/royalty-statements/<sid>/match", methods=["POST"], strict_slashes=False)
def match_statement(sid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    st = get_or_404("royalty_statements", sid, "royalty statement")
    if st["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "match requires status RECEIVED")
    lines = statement_lines_of(st["id"])
    if not lines:
        raise ApiError(ERR_EMPTY_STATEMENT, 409,
                       "the statement has no lines")
    for line in lines:
        if line["match_status"] == "UNMATCHED":
            auto_match_line(line)
    st["status"] = "MATCHING_REVIEW"
    touch(st)
    return success(statement_view(st))


@bp.route("/royalty-statements/<sid>/allocate", methods=["POST"], strict_slashes=False)
def allocate_statement(sid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    st = get_or_404("royalty_statements", sid, "royalty statement")
    if st["status"] != "MATCHING_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "allocate requires status MATCHING_REVIEW")
    lines = statement_lines_of(st["id"])
    if not lines:
        raise ApiError(ERR_EMPTY_STATEMENT, 409,
                       "the statement has no lines")
    if sum(l["gross_cents"] for l in lines) != st["gross_amount_cents"]:
        raise ApiError(ERR_GROSS_MISMATCH, 409,
                       "sum of line gross_cents does not equal gross_amount_cents")
    matched = [l for l in lines
               if l["match_status"] in ("AUTO_MATCHED", "MANUAL_MATCHED")]
    if not matched:
        raise ApiError(ERR_NO_MATCHED_LINES, 409,
                       "at least one line must be matched")
    for line in matched:
        if confirmed_split_set(line["work_id"]) is None:
            raise ApiError(ERR_NO_CONFIRMED_SPLIT_SET, 409,
                           "every matched work must have a CONFIRMED split set")
    rows, retained_total, _unmatched = compute_allocations(st, "provisional")
    for row in rows:
        sl = row["split_line"]
        al = new_record()
        al.update({
            "statement_line_id": row["statement_line"]["id"],
            "split_line_id": sl["id"],
            "statement_id": st["id"],
            "writer_id": sl["writer_id"] if sl["participant_type"] == "WRITER" else None,
            "participant_type": sl["participant_type"],
            "provisional_amount_cents": row["amount"],
            "final_amount_cents": None,
            "advance_applied_cents": 0,
            "net_payable_cents": 0,
            "status": "PROVISIONAL",
        })
        STORE["allocation_lines"][al["id"]] = al
    st["retained_cents"] = retained_total
    st["suspense_cents"] = 0
    st["allocated_total_cents"] = sum(r["amount"] for r in rows)
    st["status"] = "ALLOCATED"
    touch(st)
    return success(statement_view(st))


@bp.route("/royalty-statements/<sid>/finalize", methods=["POST"], strict_slashes=False)
def finalize_statement(sid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    st = get_or_404("royalty_statements", sid, "royalty statement")
    if st["status"] != "ALLOCATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "finalize requires status ALLOCATED")
    # allocation stays pinned to the SplitSets CONFIRMED at allocation time
    existing_rows = sorted(
        [r for r in STORE["allocation_lines"].values()
         if r["statement_id"] == st["id"]],
        key=lambda r: (r["created_at"], r["id"]),
    )
    pinned = {}
    for row in existing_rows:
        sl = STORE["split_lines"][row["split_line_id"]]
        pinned.setdefault(row["statement_line_id"], []).append(sl)
    for lid in pinned:
        pinned[lid].sort(key=lambda sl: (sl["created_at"], sl["id"]))
    computed, retained_total, unmatched_total = compute_allocations(
        st, "final", pinned_split_lines=pinned)
    amounts = {}
    for c in computed:
        amounts[(c["statement_line"]["id"], c["split_line"]["id"])] = c["amount"]
    for row in existing_rows:
        row["final_amount_cents"] = amounts[(row["statement_line_id"], row["split_line_id"])]
        row["status"] = "FINAL"
        touch(row)
    affected_writers = {}
    for row in existing_rows:
        if row["participant_type"] == "WRITER":
            writer = apply_recoupment(row)
            if writer is not None:
                affected_writers[writer["id"]] = writer
    for writer in affected_writers.values():
        recompute_writer_rollups(writer)
    st["retained_cents"] = retained_total
    st["suspense_cents"] = unmatched_total
    st["allocated_total_cents"] = sum(r["final_amount_cents"] for r in existing_rows)
    st["status"] = "FINALIZED"
    touch(st)
    work_ids = set()
    for line in statement_lines_of(st["id"]):
        if line["work_id"] is not None:
            work_ids.add(line["work_id"])
    for wid in work_ids:
        work = STORE["works"].get(wid)
        if work is not None:
            recompute_work_rollup(work)
    return success(statement_view(st))


@bp.route("/royalty-statements/<sid>/reject", methods=["POST"], strict_slashes=False)
def reject_statement(sid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    st = get_or_404("royalty_statements", sid, "royalty statement")
    body = body_json()
    req_str(body, "reason")
    if st["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "reject requires status RECEIVED")
    st["status"] = "REJECTED"
    touch(st)
    return success(statement_view(st))


# ---------------------------------------------------------------------------
# statement lines
# ---------------------------------------------------------------------------

@bp.route("/statement-lines", methods=["GET"], strict_slashes=False)
def list_statement_lines():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("statement_lines")
    statement_id = request.args.get("statement_id")
    work_id = request.args.get("work_id")
    match_status = request.args.get("match_status")
    if statement_id is not None:
        items = [l for l in items if l["statement_id"] == statement_id]
    if work_id is not None:
        items = [l for l in items if l["work_id"] == work_id]
    if match_status is not None:
        items = [l for l in items if l["match_status"] == match_status]
    page, meta = paginate(items, limit, offset)
    return success([statement_line_view(l) for l in page],
                   response_type="array", pagination=meta)


@bp.route("/statement-lines/<lid>", methods=["GET"], strict_slashes=False)
def get_statement_line(lid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    line = get_or_404("statement_lines", lid, "statement line")
    return success(statement_line_view(line))


@bp.route("/statement-lines/<lid>/match", methods=["POST"], strict_slashes=False)
def manual_match_line(lid):
    uid, role = auth_context()
    require_roles(role, ["RoyaltyAnalyst"])
    line = get_or_404("statement_lines", lid, "statement line")
    body = body_json()
    work_id = body.get("work_id")
    if not isinstance(work_id, str) or not work_id:
        raise ApiError(ERR_VALIDATION, 422, "work_id is required")
    work = get_or_404("works", work_id, "work")
    st = STORE["royalty_statements"][line["statement_id"]]
    if line["match_status"] != "UNMATCHED" or st["status"] not in ("RECEIVED", "MATCHING_REVIEW"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "manual match requires an UNMATCHED line on a statement "
                       "in RECEIVED or MATCHING_REVIEW")
    if work["registration_status"] != "REGISTERED":
        raise ApiError(ERR_WORK_NOT_REGISTERED, 409,
                       "the work's registration_status is not REGISTERED")
    line["work_id"] = work["id"]
    line["match_status"] = "MANUAL_MATCHED"
    touch(line)
    return success(statement_line_view(line))


# ---------------------------------------------------------------------------
# allocation lines
# ---------------------------------------------------------------------------

@bp.route("/allocation-lines", methods=["GET"], strict_slashes=False)
def list_allocation_lines():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("allocation_lines")
    statement_line_id = request.args.get("statement_line_id")
    split_line_id = request.args.get("split_line_id")
    statement_id = request.args.get("statement_id")
    writer_id = request.args.get("writer_id")
    if statement_line_id is not None:
        items = [a for a in items if a["statement_line_id"] == statement_line_id]
    if split_line_id is not None:
        items = [a for a in items if a["split_line_id"] == split_line_id]
    if statement_id is not None:
        items = [a for a in items if a["statement_id"] == statement_id]
    if writer_id is not None:
        items = [a for a in items if a["writer_id"] == writer_id]
    page, meta = paginate(items, limit, offset)
    return success([allocation_line_view(a) for a in page],
                   response_type="array", pagination=meta)


@bp.route("/allocation-lines/<aid>", methods=["GET"], strict_slashes=False)
def get_allocation_line(aid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    al = get_or_404("allocation_lines", aid, "allocation line")
    return success(allocation_line_view(al))
