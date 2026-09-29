"""Elections: filing, superseding, amending, cancelling and funding reversal."""

from flask import Blueprint

import serialize
from auth import (
    authenticate,
    require_employee_scope,
    resolve_category,
    resolve_election,
    resolve_media,
    resolve_employee,
    resolve_window,
)
from calc import (
    exclusion_split,
    post_entry,
    recompute_commitment,
    rederive_fulfillment,
    resolve_account_for,
)
from cascades import cancel_election
from errors import fail
from guards import (
    TERMINAL_ELECTION_FUNDING,
    require_allocation_allowed,
    require_before_cutoff,
    require_category_active,
    require_employer_active,
    require_media_active,
    require_media_eligible,
    require_no_hold,
    require_not_terminal,
    require_ordinance_ok,
    require_transition,
)
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    FULFILLMENT_STATUSES,
    FUNDING_STATUSES,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("elections", __name__)

MID_MONTH_CHANGE_LIMIT = 1
AMENDABLE_FUNDING_STATUSES = ("PENDING", "HELD", "FUNDED")
LIVE_FUNDING_STATUSES = ("PENDING", "HELD")


@bp.post("/benefits/elections")
def create_election():
    principal = authenticate(["Employee", "ProgramAdmin"])
    specs = [
        field("employee_id", "id", required=True),
        field("election_window_id", "id", required=True),
        field("benefit_category_id", "id", required=True),
        field("pretax_amount_cents", "integer", required=True, minimum=0),
        field("posttax_amount_cents", "integer", default=0, minimum=0),
        field("transit_media_id", "id", default=None, nullable=True),
        field("media_quantity", "integer", default=0, minimum=0),
        field("expected_account_version", "integer", required=True),
    ]
    _body, values = parse_body(specs)

    # ladder 7 - body identifier resolution
    employee = resolve_employee(values["employee_id"])
    window = resolve_window(values["election_window_id"])
    category = resolve_category(values["benefit_category_id"])
    media = None
    if values["transit_media_id"] is not None:
        media = resolve_media(values["transit_media_id"])

    # ladder 8 - employee ownership
    require_employee_scope(principal, employee["id"])

    # ladder 9 - owning employer program active
    employer = store.employers.get(window["employer_id"])
    require_employer_active(employer)

    # ladder 10 - window posture
    if window["status"] != "OPEN":
        fail("ERR_ELECTION_WINDOW_NOT_OPEN",
             "Election window %s is not OPEN." % window["id"])

    # ladder 15, 17, 18
    require_ordinance_ok(employer)
    require_no_hold(employee)
    require_category_active(category)

    # ladder 19, 20
    if media is not None:
        require_media_eligible(media, category, employee)
        require_media_active(media)

    # ladder 21 - account coherence
    account = resolve_account_for(employee["id"], category["id"])
    if account is None:
        fail("ERR_ACCOUNT_MISMATCH",
             "No benefit account exists for this employee and benefit category pair.")

    pretax = values["pretax_amount_cents"]
    posttax = values["posttax_amount_cents"]

    # ladder 22, 23
    require_allocation_allowed(category, pretax, posttax)
    require_before_cutoff(window)

    # ladder 31 - optimistic concurrency on the parent account
    if values["expected_account_version"] != account["version"]:
        fail("ERR_STALE_ACCOUNT_VERSION",
             "The supplied expected_account_version does not match the current "
             "version of benefit account %s." % account["id"])

    # ladder 32 - the exclusion waterfall under the elected basis
    split = exclusion_split(employer, category, employee["id"], window["id"],
                            pretax, posttax, "ELECTED_BASIS")

    # supersede any prior live election for the same triple
    prior_rows = [e for e in store.elections.values()
                  if e["employee_id"] == employee["id"]
                  and e["election_window_id"] == window["id"]
                  and e["benefit_category_id"] == category["id"]
                  and e["funding_status"] in LIVE_FUNDING_STATUSES]
    prior = sorted_rows(prior_rows)[-1] if prior_rows else None
    if prior is not None:
        cancel_election(prior)

    row = {
        "employee_id": employee["id"],
        "election_window_id": window["id"],
        "benefit_category_id": category["id"],
        "benefit_account_id": account["id"],
        "transit_media_id": None if media is None else media["id"],
        "superseded_election_id": None if prior is None else prior["id"],
        "pretax_amount_cents": pretax,
        "posttax_amount_cents": posttax,
        "total_amount_cents": split["total_amount_cents"],
        "excluded_amount_cents": split["excluded_amount_cents"],
        "posttax_spill_cents": split["posttax_spill_cents"],
        "posttax_effective_cents": split["posttax_effective_cents"],
        "exclusion_basis": "ELECTED_BASIS",
        "entitled_media_units": values["media_quantity"],
        "change_count": 0,
        "funding_status": "PENDING",
        "fulfillment_status": "NOT_REQUIRED",
    }
    stamp_new(row)
    store.elections[row["id"]] = row
    rederive_fulfillment(row)
    bump(account)
    return created_response(serialize.election(row))


@bp.get("/benefits/elections/<election_id>")
def read_election(election_id):
    authenticate(["ProgramAdmin", "Employee", "OrderDesk", "ComplianceReviewer",
                  "PayrollProcessor"])
    row = resolve_election(election_id)
    return object_response(serialize.election(row))


@bp.get("/benefits/elections")
def list_elections():
    authenticate(["ProgramAdmin", "Employee", "OrderDesk", "ComplianceReviewer",
                  "PayrollProcessor"])
    employee_id = str_filter("employee_id")
    window_id = str_filter("election_window_id")
    category_id = str_filter("benefit_category_id")
    account_id = str_filter("benefit_account_id")
    media_id = str_filter("transit_media_id")
    superseded_id = str_filter("superseded_election_id")
    funding_status = enum_filter("funding_status", FUNDING_STATUSES)
    fulfillment_status = enum_filter("fulfillment_status", FULFILLMENT_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.elections.values():
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if window_id is not None and row["election_window_id"] != window_id:
            continue
        if category_id is not None and row["benefit_category_id"] != category_id:
            continue
        if account_id is not None and row["benefit_account_id"] != account_id:
            continue
        if media_id is not None and row["transit_media_id"] != media_id:
            continue
        if superseded_id is not None and row["superseded_election_id"] != superseded_id:
            continue
        if funding_status is not None and row["funding_status"] != funding_status:
            continue
        if fulfillment_status is not None and \
                row["fulfillment_status"] != fulfillment_status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.election(r) for r in page], limit, offset, total)


@bp.patch("/benefits/elections/<election_id>")
def amend_election(election_id):
    principal = authenticate(["Employee", "ProgramAdmin"])
    row = resolve_election(election_id)
    specs = [
        field("pretax_amount_cents", "integer", minimum=0),
        field("posttax_amount_cents", "integer", minimum=0),
        field("media_quantity", "integer", minimum=0),
    ]
    body, values = parse_body(specs)

    # ladder 8
    require_employee_scope(principal, row["employee_id"])

    window = store.election_windows.get(row["election_window_id"])
    employer = store.employers.get(window["employer_id"]) if window else None
    category = store.benefit_categories.get(row["benefit_category_id"])
    employee = store.employees.get(row["employee_id"])

    # ladder 9
    require_employer_active(employer)

    # ladder 10
    if window["status"] not in ("OPEN", "LOCKED"):
        fail("ERR_ELECTION_WINDOW_NOT_OPEN",
             "Election window %s is neither OPEN nor LOCKED." % window["id"])

    # ladder 13 - amendment eligibility
    if row["funding_status"] not in AMENDABLE_FUNDING_STATUSES:
        fail("ERR_ELECTION_ALREADY_FUNDED",
             "Election %s is closed to amendment in funding status %s."
             % (row["id"], row["funding_status"]))

    # ladder 15, 17
    require_ordinance_ok(employer)
    require_no_hold(employee)

    pretax = values.get("pretax_amount_cents", row["pretax_amount_cents"])
    posttax = values.get("posttax_amount_cents", row["posttax_amount_cents"])
    media_units = values.get("media_quantity", row["entitled_media_units"])

    # ladder 22, 23
    require_allocation_allowed(category, pretax, posttax)
    require_before_cutoff(window)

    # ladder 26, 27 - the mid-month gates, in this order
    if window["status"] == "LOCKED":
        if not window["mid_month_change_allowed"]:
            fail("ERR_MID_MONTH_CHANGE_NOT_ALLOWED",
                 "Election window %s does not permit mid-month changes."
                 % window["id"])
        if row["change_count"] >= MID_MONTH_CHANGE_LIMIT:
            fail("ERR_CHANGE_LIMIT_EXCEEDED",
                 "Election %s has already absorbed its single permitted mid-month "
                 "change." % row["id"])

    # ladder 32
    split = exclusion_split(employer, category, row["employee_id"], window["id"],
                            pretax, posttax, "ELECTED_BASIS",
                            exclude_election_id=row["id"])

    old_total = row["total_amount_cents"]
    row["pretax_amount_cents"] = pretax
    row["posttax_amount_cents"] = posttax
    row["entitled_media_units"] = media_units
    row["total_amount_cents"] = split["total_amount_cents"]
    row["excluded_amount_cents"] = split["excluded_amount_cents"]
    row["posttax_spill_cents"] = split["posttax_spill_cents"]
    row["posttax_effective_cents"] = split["posttax_effective_cents"]
    row["exclusion_basis"] = "ELECTED_BASIS"
    row["change_count"] += 1
    rederive_fulfillment(row)

    if row["funding_status"] == "FUNDED":
        delta = row["total_amount_cents"] - old_total
        account = store.benefit_accounts.get(row["benefit_account_id"])
        if delta != 0 and account is not None:
            account["contributed_cents"] += delta
            post_entry(account, "CONTRIBUTION_ADJUSTMENT", delta, "Election",
                       row["id"],
                       "Contribution adjusted by a mid-month amendment.")
            bump(account)
        recompute_commitment(employer)
        bump(employer)

    bump(row)
    return object_response(serialize.election(row))


@bp.post("/benefits/elections/<election_id>/cancel")
def cancel_election_endpoint(election_id):
    principal = authenticate(["Employee", "ProgramAdmin"])
    row = resolve_election(election_id)
    require_employee_scope(principal, row["employee_id"])
    require_not_terminal(row, "funding_status", TERMINAL_ELECTION_FUNDING, "Election")
    window = store.election_windows.get(row["election_window_id"])
    require_transition(row["funding_status"] in LIVE_FUNDING_STATUSES,
                       "Election %s cannot be cancelled from funding status %s."
                       % (row["id"], row["funding_status"]))
    require_transition(window is not None and window["status"] in ("OPEN", "LOCKED"),
                       "Election %s cannot be cancelled because its window is not "
                       "OPEN or LOCKED." % row["id"])
    cancel_election(row)
    return object_response(serialize.election(row))


@bp.post("/benefits/elections/<election_id>/reverse-funding")
def reverse_funding(election_id):
    authenticate(["ProgramAdmin"])
    row = resolve_election(election_id)
    _body, values = parse_body([field("reason", "string", required=True)])
    require_not_terminal(row, "funding_status", TERMINAL_ELECTION_FUNDING, "Election")
    window = store.election_windows.get(row["election_window_id"])
    require_transition(row["funding_status"] == "FUNDED",
                       "Election %s cannot have its funding reversed from status %s."
                       % (row["id"], row["funding_status"]))
    require_transition(window is not None and window["status"] == "LOCKED",
                       "Election %s cannot have its funding reversed because its "
                       "window is not LOCKED." % row["id"])

    amount = row["total_amount_cents"]
    row["funding_status"] = "REVERSED"
    account = store.benefit_accounts.get(row["benefit_account_id"])
    if account is not None:
        account["reversed_cents"] += amount
        post_entry(account, "FUNDING_REVERSAL", -amount, "Election", row["id"],
                   values["reason"])
        bump(account)
    employer = store.employers.get(window["employer_id"]) if window else None
    if employer is not None:
        recompute_commitment(employer)
        bump(employer)
    bump(row)
    return object_response(serialize.election(row))
