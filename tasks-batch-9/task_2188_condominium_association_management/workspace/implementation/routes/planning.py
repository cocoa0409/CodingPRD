"""Budgets (draft -> propose -> notice -> ratify) and the billing-run checkpoint."""
from flask import request

import clock
import db
import money
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import alloc, assessment, certificate, contracts, ledger

BUDGET_STATUSES = ("DRAFT", "PROPOSED", "NOTICED", "ADOPTED", "REJECTED", "SUPERSEDED")


# --------------------------------------------------------------------- helpers


def budget_votes(budget_id):
    return [v for v in db.store["votes"].values()
            if v["subject_type"] == "BUDGET" and v["subject_id"] == budget_id]


def clear_budget_votes(budget_id):
    for v in budget_votes(budget_id):
        v["counted"] = False


def reserve_minimum(assoc, operating_total_cents):
    return money.round_half_up(
        operating_total_cents * assoc["reserve_contribution_min_bp"], 10000)


def other_adopted(assoc_id, fiscal_year, exclude_id=None):
    for b in db.store["budgets"].values():
        if (b["association_id"] == assoc_id and b["fiscal_year"] == fiscal_year
                and b["status"] == "ADOPTED" and b["id"] != exclude_id):
            return b
    return None


def fiscal_year_of_period(assoc, period):
    """The fiscal year a YYYY-MM period belongs to, honouring
    fiscal_year_start_month."""
    year = int(period[:4])
    month = int(period[5:])
    if month >= assoc["fiscal_year_start_month"]:
        return year
    return year - 1


def run_allocation(budget):
    """Hop 1 of the adoption cascade: the MONTHLY_OPERATING allocation variant."""
    assoc_id = budget["association_id"]
    units = alloc.participants(assoc_id)
    pool = money.round_half_up(budget["assessment_total_cents"], 12)
    shares, base, drift = alloc.allocate(pool, units)
    snapshot = []
    for unit, share, raw in zip(units, shares, base):
        unit["monthly_assessment_cents"] = share
        db.touch(unit)
        snapshot.append({
            "unit_id": unit["id"],
            "interest_bp": unit["interest_bp"],
            "monthly_cents": share,
            "remainder_cent_awarded": share != raw,
        })
    budget["allocation_snapshot"] = snapshot
    budget["_allocation_drift"] = drift
    return units


def adoption_cascade(budget):
    """Hops 1-5 of the NOTICED -> ADOPTED cascade."""
    units = run_allocation(budget)
    unit_ids = set(u["id"] for u in units)
    # Hops 2, 3, 4 and (through recompute) 5.
    for cert in db.sorted_rows(
            "resale_certificates",
            lambda c: c["unit_id"] in unit_ids and c["status"] == "ISSUED"
            and c.get("pinned_budget_id") != budget["id"]):
        certificate.cascade_void(cert, db.get("units", cert["unit_id"]))
    # Hop 5 is also run unconditionally so a balloting assessment always reflects
    # the association's current eligible weight.
    ledger.recompute_balloting_eligibility(budget["association_id"])
    for sa in db.store["special_assessments"].values():
        if sa["association_id"] == budget["association_id"]:
            assessment.refresh_money(sa)
    assessment.refresh_restricted_cash(budget["association_id"])


def register(app):

    # ---------------------------------------------------------------- budgets

    @app.post("/associations/<association_id>/budgets")
    def create_budget(association_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        body = V.body_of()
        fk = V.resolve_body_fk(body, "ratification_meeting_id")
        meeting = fk["ratification_meeting_id"]
        fiscal_year = V.require_int(body, "fiscal_year", minimum=2020, maximum=2100)
        operating_total = V.require_int(body, "operating_total_cents", minimum=0)
        reserve_contribution = V.require_int(body, "reserve_contribution_cents",
                                             minimum=0)
        V.require_int(body, "expected_association_version", minimum=0)
        if meeting is not None:
            V.scope_match(association_id, meeting)
        V.occ(body, "expected_association_version", assoc,
              "ERR_STALE_ASSOCIATION_VERSION")

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "supersedes_budget_id": None,
            "ratification_meeting_id": meeting["id"] if meeting else None,
            "fiscal_year": fiscal_year,
            "operating_total_cents": operating_total,
            "reserve_contribution_cents": reserve_contribution,
            "assessment_total_cents": 0,
            "monthly_assessable_cents": 0,
            "status": "DRAFT",
            "notice_sent_at": None,
            "revision_round": 0,
            "no_weight_bp": 0,
            "allocation_snapshot": [],
            "adopted_at": None,
        })

        # Creation is deliberately destructive of stale work.
        predecessors = db.sorted_rows(
            "budgets",
            lambda b: b["association_id"] == association_id
            and b["fiscal_year"] == fiscal_year
            and b["status"] in ("DRAFT", "PROPOSED"))
        for pred in predecessors:
            was_draft = pred["status"] == "DRAFT"
            pred["status"] = "SUPERSEDED"
            row["supersedes_budget_id"] = pred["id"]
            # Only the DRAFT -> SUPERSEDED leg clears the ballot record.
            if was_draft:
                clear_budget_votes(pred["id"])
            db.touch(pred)

        db.insert("budgets", row)
        db.touch(assoc)
        return response.created(serialize.view(row))

    @app.get("/budgets")
    def list_budgets():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "TitleAgent"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in BUDGET_STATUSES:
            V.fail("Query parameter 'status' is not a recognized budget status.")
        fiscal_year = args.get("fiscal_year")
        if fiscal_year is not None and fiscal_year != "":
            try:
                fiscal_year = int(fiscal_year)
            except (TypeError, ValueError):
                V.fail("Query parameter 'fiscal_year' must be an integer.")
        else:
            fiscal_year = None

        def keep(b):
            for name in ("association_id", "supersedes_budget_id",
                         "ratification_meeting_id"):
                want = args.get(name)
                if want and b.get(name) != want:
                    return False
            if status and b["status"] != status:
                return False
            if fiscal_year is not None and b["fiscal_year"] != fiscal_year:
                return False
            return True

        rows = db.sorted_rows("budgets", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/budgets/<budget_id>/propose")
    def propose_budget(budget_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(budget_id=budget_id)
        budget = found["budget_id"]
        assoc = db.get("associations", budget["association_id"])
        body = V.body_of()
        fk = V.resolve_body_fk(body, "ratification_meeting_id")
        meeting = fk["ratification_meeting_id"]
        if meeting is not None:
            V.scope_match(budget["association_id"], meeting)
        # Rung 12.
        if budget["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_BUDGET_STATE")
        # Rung 35.
        if assoc["total_interest_bp"] != 10000:
            raise ApiError("ERR_INTEREST_SUM_INVALID")
        # Rung 43.
        if budget["reserve_contribution_cents"] < reserve_minimum(
                assoc, budget["operating_total_cents"]):
            raise ApiError("ERR_RESERVE_CONTRIBUTION_TOO_LOW")
        # Rung 49.
        if other_adopted(budget["association_id"], budget["fiscal_year"], budget["id"]):
            raise ApiError("ERR_DUPLICATE_ADOPTED_BUDGET")

        if meeting is not None:
            budget["ratification_meeting_id"] = meeting["id"]
        budget["status"] = "PROPOSED"
        budget["assessment_total_cents"] = (budget["operating_total_cents"]
                                            + budget["reserve_contribution_cents"])
        budget["monthly_assessable_cents"] = money.round_half_up(
            budget["assessment_total_cents"], 12)
        db.touch(budget)
        return response.ok(serialize.view(budget))

    @app.post("/budgets/<budget_id>/send-notice")
    def send_budget_notice(budget_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(budget_id=budget_id)
        budget = found["budget_id"]
        assoc = db.get("associations", budget["association_id"])
        V.body_of()
        # Rung 12.
        if budget["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_BUDGET_STATE")
        if not budget.get("ratification_meeting_id"):
            raise ApiError("ERR_INVALID_BUDGET_STATE",
                           "The budget has no ratification meeting.")
        meeting = db.get("board_meetings", budget["ratification_meeting_id"])
        if meeting is None or meeting["status"] not in ("SCHEDULED", "NOTICED"):
            raise ApiError("ERR_INVALID_MEETING_STATE")
        # Rung 25 precedes rung 33.
        deadline = clock.add_days(clock.now(), assoc["budget_notice_days"])
        if meeting["scheduled_start"] < deadline:
            raise ApiError("ERR_NOTICE_PERIOD_NOT_SATISFIED")
        # Rung 33.
        if "BUDGET_RATIFICATION" not in (meeting["agenda_kinds"] or []):
            raise ApiError("ERR_AGENDA_KIND_MISSING")

        now = clock.now()
        budget["notice_sent_at"] = now
        budget["status"] = "NOTICED"
        if meeting["status"] == "SCHEDULED":
            meeting["status"] = "NOTICED"
            meeting["notice_sent_at"] = now
            db.touch(meeting)
        db.touch(budget)
        return response.ok(serialize.view(budget))

    @app.post("/budgets/<budget_id>/return-to-draft")
    def return_budget_to_draft(budget_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(budget_id=budget_id)
        budget = found["budget_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        status = budget["status"]
        # Rung 12.
        if status not in ("PROPOSED", "NOTICED", "REJECTED"):
            raise ApiError("ERR_INVALID_BUDGET_STATE")
        if status == "NOTICED":
            meeting = db.get("board_meetings", budget.get("ratification_meeting_id"))
            if meeting is not None and meeting["status"] == "IN_SESSION":
                raise ApiError("ERR_INVALID_MEETING_STATE")

        # The three legs have deliberately different side-effect sets.
        if status == "PROPOSED":
            budget["revision_round"] += 1
        elif status == "NOTICED":
            budget["notice_sent_at"] = None
            budget["revision_round"] += 1
            clear_budget_votes(budget["id"])
        else:
            budget["revision_round"] += 1
            budget["notice_sent_at"] = None
            budget["no_weight_bp"] = 0
            clear_budget_votes(budget["id"])
        budget["status"] = "DRAFT"
        db.touch(budget)
        return response.ok(serialize.view(budget))

    @app.post("/budgets/<budget_id>/ratify")
    def ratify_budget(budget_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(budget_id=budget_id)
        budget = found["budget_id"]
        assoc = db.get("associations", budget["association_id"])
        V.body_of()
        # Rung 12.
        if budget["status"] != "NOTICED":
            raise ApiError("ERR_INVALID_BUDGET_STATE")
        meeting = db.get("board_meetings", budget.get("ratification_meeting_id"))
        # Rung 13.
        if meeting is None or meeting["status"] != "IN_SESSION":
            raise ApiError("ERR_MEETING_NOT_IN_SESSION")
        # Rung 14.
        if not meeting["quorum_met"]:
            raise ApiError("ERR_BOARD_QUORUM_NOT_MET")
        # Rung 25.
        ready_at = clock.add_days(budget["notice_sent_at"], assoc["budget_notice_days"])
        if clock.now() < ready_at:
            raise ApiError("ERR_NOTICE_PERIOD_NOT_SATISFIED")

        # The veto tally: voting_eligible is NOT applied here.
        ballots = assessment.subject_ballots("BUDGET", budget["id"],
                                             budget["notice_sent_at"])
        surviving, superseded = assessment.survivors(ballots)
        for v in superseded:
            v["counted"] = False
        no_weight = sum(v["weight_bp"] for v in surviving if v["choice"] == "NO")
        rejected = no_weight >= assoc["budget_veto_bp"]

        if not rejected:
            # Rung 35.
            if assoc["total_interest_bp"] != 10000:
                raise ApiError("ERR_INTEREST_SUM_INVALID")
            # Rung 43.
            if budget["reserve_contribution_cents"] < reserve_minimum(
                    assoc, budget["operating_total_cents"]):
                raise ApiError("ERR_RESERVE_CONTRIBUTION_TOO_LOW")
            # Rung 49.
            if other_adopted(budget["association_id"], budget["fiscal_year"],
                             budget["id"]):
                raise ApiError("ERR_DUPLICATE_ADOPTED_BUDGET")

        budget["no_weight_bp"] = no_weight
        if rejected:
            budget["status"] = "REJECTED"
        else:
            budget["status"] = "ADOPTED"
            budget["adopted_at"] = clock.now()
            adoption_cascade(budget)
        db.touch(budget)
        return response.ok(serialize.view(budget))

    # ----------------------------------------------------------- billing runs

    @app.post("/associations/<association_id>/billing-runs")
    def create_billing_run(association_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        body = V.body_of()
        fk = V.resolve_body_fk(body, "source_budget_id")
        budget = fk["source_budget_id"]
        if budget is None:
            V.fail("Field 'source_budget_id' is required.")
        period = V.require_period(body, "period")
        due_on = V.require_dt(body, "due_on")
        V.scope_match(association_id, budget)
        # Rung 37.
        for r in db.store["billing_runs"].values():
            if r["association_id"] == association_id and r["period"] == period:
                raise ApiError("ERR_PERIOD_ALREADY_BILLED")
        # Rung 38.
        if budget["status"] != "ADOPTED":
            raise ApiError("ERR_BUDGET_NOT_ADOPTED")
        if budget["fiscal_year"] != fiscal_year_of_period(assoc, period):
            raise ApiError("ERR_BUDGET_NOT_ADOPTED")

        now = clock.now()
        run = db.base_fields()
        run.update({
            "association_id": association_id,
            "source_budget_id": budget["id"],
            "period": period,
            "due_on": due_on,
            "assessment_charged_cents": 0,
            "remainder_cents_allocated": 0,
            "late_fees_charged_cents": 0,
            "charged_unit_count": 0,
            "escalated_unit_count": 0,
            "fines_finalized_count": 0,
            "executed_at": now,
        })
        db.insert("billing_runs", run)

        # -- step 1: post the period's assessments from the allocation snapshot.
        charged_units = []
        for line in budget["allocation_snapshot"] or []:
            unit = db.get("units", line["unit_id"])
            if unit is None:
                continue
            ledger.post_entry(unit, "ASSESSMENT", line["monthly_cents"], period,
                              due_on=due_on, billing_run_id=run["id"])
            run["assessment_charged_cents"] += line["monthly_cents"]
            charged_units.append(unit)
        run["charged_unit_count"] = len(charged_units)
        drift = budget.get("_allocation_drift")
        if drift is None:
            drift = sum(1 for line in budget["allocation_snapshot"] or []
                        if line.get("remainder_cent_awarded"))
        run["remainder_cents_allocated"] = abs(drift)

        # -- step 2: late fees, evaluated per unit after its assessment is posted.
        for unit in charged_units:
            fee = late_fee_for(assoc, unit, run)
            if fee > 0:
                ledger.post_entry(unit, "LATE_FEE", fee, period, due_on=due_on,
                                  billing_run_id=run["id"])
                run["late_fees_charged_cents"] += fee

        # -- step 3: age every account and re-derive every posture.
        for unit in db.sorted_rows("units",
                                   lambda u: u["association_id"] == association_id):
            ledger.recompute_unit(unit, run=run)

        # -- step 4: finalize unappealed fines.
        for case in db.sorted_rows(
                "violation_cases",
                lambda c: c["association_id"] == association_id
                and c["status"] == "FINE_ASSESSED"):
            deadline = case.get("appeal_deadline_at")
            if deadline is not None and now > deadline:
                case["status"] = "FINE_UPHELD"
                run["fines_finalized_count"] += 1
                db.touch(case)

        # -- step 5: sweep vendor contracts.
        for contract in db.sorted_rows(
                "vendor_contracts",
                lambda c: c["association_id"] == association_id):
            contracts.sweep_insurance_lapse(contract)
            contracts.sweep_term_expiry(contract)

        # -- step 6: sweep stale resale certificates.
        for cert in db.sorted_rows("resale_certificates",
                                   lambda c: c["status"] == "ISSUED"):
            unit = db.get("units", cert["unit_id"])
            if unit is None or unit["association_id"] != association_id:
                continue
            expires = cert.get("expires_at")
            if expires is None or now < expires:
                continue
            cert["status"] = "EXPIRED"
            unit["transfer_blocked"] = True
            db.touch(unit)
            db.touch(cert)

        for sa in db.store["special_assessments"].values():
            if sa["association_id"] == association_id:
                assessment.refresh_money(sa)
        assessment.refresh_restricted_cash(association_id)
        return response.created(serialize.view(run))

    @app.get("/billing-runs")
    def list_billing_runs():
        authenticate(("CommunityManager", "BoardTreasurer", "BoardDirector"))
        limit, offset = V.pagination()
        args = request.args

        def keep(r):
            for name in ("association_id", "source_budget_id", "period"):
                want = args.get(name)
                if want and r.get(name) != want:
                    return False
            return True

        rows = db.sorted_rows("billing_runs", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)


def late_fee_for(assoc, unit, run):
    """PRD 3.5 step 2 -- the late-fee assessment calculation."""
    executed_at = run["executed_at"]
    principal = 0
    for e in db.store["ledger_entries"].values():
        if e["unit_id"] != unit["id"]:
            continue
        if e["status"] != "POSTED" or e["bucket"] != "ASSESSMENT":
            continue
        if e["amount_cents"] <= 0 or e["due_on"] is None:
            continue
        age = clock.floor_days(executed_at, e["due_on"])
        if age > assoc["late_fee_grace_days"]:
            principal += e["amount_cents"] - e["applied_cents"]
    if principal <= 0:
        return 0
    if unit["delinquency_stage"] == "FORECLOSURE_REFERRAL":
        fee = assoc["late_fee_min_cents"]
    else:
        fee = money.round_half_up(principal * assoc["late_fee_percent_bp"], 10000)
        fee = max(fee, assoc["late_fee_min_cents"])
        fee = min(fee, assoc["late_fee_cap_cents"])
    # Never two late fees for one period.
    for e in db.store["ledger_entries"].values():
        if (e["unit_id"] == unit["id"] and e["status"] == "POSTED"
                and e["entry_type"] == "LATE_FEE"
                and e["effective_period"] == run["period"]):
            return 0
    return fee
