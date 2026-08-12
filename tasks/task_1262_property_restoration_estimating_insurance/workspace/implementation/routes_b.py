"""Routes: estimates, lines, negotiation rounds/dispositions, supplements,
code upgrades, work authorizations, invoices, payments."""
from datetime import timedelta

from flask import request

from store import DB, now, fmt_clock, new_id, stamp_new, touch, dec, rhu, WA_VALIDITY_DAYS
from errors import (ApiError, ok_object, page, public, auth, require_roles,
                    body, req_field, opt_field, as_str, as_bool, as_int,
                    as_num, as_enum, as_dt)
from domain import (get, find, claim_of_estimate, carrier_of_claim,
                    policy_of_claim, lines_of_estimate, rounds_of_estimate,
                    dispositions_of_round, compute_line_money,
                    estimate_totals, recompute_estimate,
                    recompute_claim_aggregates, recompute_claim_ledger,
                    recompute_ordinance_consumed, recompute_round_disputed,
                    apply_disposition, approve_estimate, maybe_resolve_round,
                    active_invoice, create_payment)

CA = "ContractorAdmin"
EST = "Estimator"
FT = "FieldTechnician"
ADJ = "Adjuster"
CUST = "Customer"

CLAIM_TERMINAL = {"CLOSED", "DENIED", "WITHDRAWN"}
PAYABLE_STATES = {"AUTHORIZED", "IN_PROGRESS", "ON_HOLD", "COMPLETE", "INVOICED"}


def claim_visible_to(claim, uid, role):
    if role == CUST and claim["customer_id"] != uid:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found")


def next_revision_number(claim_id):
    revs = [e["revision_number"] for e in DB["estimates"].values()
            if e["claim_id"] == claim_id]
    return (max(revs) if revs else 0) + 1


def register(a):
    # --------------------------------------------------------- estimates
    @a.post("/v1/claims/<cid>/estimates")
    def create_estimate(cid):
        uid, role = auth()
        require_roles(role, {EST})
        claim = get("claims", cid)
        data = body()
        expected = as_int(req_field(data, "expected_claim_version"), "expected_claim_version")
        if expected != claim["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_claim_version does not match the claim's current version")
        if claim["status"] not in ("ASSESSING", "ESTIMATING", "NEGOTIATING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Estimate creation requires claim ASSESSING, ESTIMATING, or NEGOTIATING")
        for e in DB["estimates"].values():
            if e["claim_id"] == cid and e["type"] == "INITIAL":
                raise ApiError("ERR_DUPLICATE_INITIAL_ESTIMATE",
                               "The claim already has an INITIAL estimate")
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "supplement_id": None,
            "type": "INITIAL",
            "revision_number": next_revision_number(cid),
            "status": "DRAFT",
            "rcv_total_cents": 0,
            "tax_total_cents": 0,
            "overhead_profit_total_cents": 0,
            "depreciation_total_cents": 0,
            "recoverable_depreciation_cents": 0,
            "acv_total_cents": 0,
            "grand_total_cents": 0,
            "submitted_at": None,
            "approved_at": None,
        }
        stamp_new(rec)
        DB["estimates"][rec["id"]] = rec
        touch(claim)
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/estimates")
    def list_estimates(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        items = [e for e in DB["estimates"].values() if e["claim_id"] == cid]
        return page(items, {"status": request.args.get("status"),
                            "type": request.args.get("type")})

    @a.get("/v1/estimates/<eid>")
    def get_estimate(eid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        est = get("estimates", eid)
        claim_visible_to(DB["claims"][est["claim_id"]], uid, role)
        return ok_object(public(est))

    # ------------------------------------------------------------- lines
    @a.post("/v1/estimates/<eid>/lines")
    def add_line(eid):
        uid, role = auth()
        require_roles(role, {EST})
        est = get("estimates", eid)
        data = body()
        ple_id = opt_field(data, "price_list_entry_id")
        if ple_id is not None and isinstance(ple_id, str) and ple_id in DB["price_list_entries"]:
            entry = DB["price_list_entries"][ple_id]
        else:
            ple_id = as_str(req_field(data, "price_list_entry_id"), "price_list_entry_id")
            if ple_id not in DB["price_list_entries"]:
                raise ApiError("ERR_RESOURCE_NOT_FOUND", "price_list_entry_id does not resolve")
            entry = DB["price_list_entries"][ple_id]
        qty = as_num(req_field(data, "qty"), "qty")
        if not dec(qty) > 0:
            raise ApiError("ERR_INVALID_REQUEST", "qty must be > 0")
        depreciation_pct = opt_field(data, "depreciation_pct", None)
        if depreciation_pct is None:
            depreciation_pct = entry["default_depreciation_pct"]
        else:
            depreciation_pct = as_num(depreciation_pct, "depreciation_pct")
        depreciation_recoverable = as_bool(opt_field(data, "depreciation_recoverable", True),
                                           "depreciation_recoverable")
        description = as_str(opt_field(data, "description", ""), "description")
        if est["status"] not in ("DRAFT", "REVISED"):
            raise ApiError("ERR_ESTIMATE_NOT_EDITABLE",
                           "Lines may be added only while the estimate is DRAFT or REVISED")
        line = {
            "id": new_id(),
            "estimate_id": eid,
            "price_list_entry_id": ple_id,
            "category_code": entry["category_code"],
            "trade": entry["trade"],
            "kind": entry["kind"],
            "description": description,
            "qty": qty,
            "unit_price_cents": entry["unit_price_cents"],
            "depreciation_pct": depreciation_pct,
            "depreciation_recoverable": depreciation_recoverable,
            "tax_applicable": entry["tax_applicable"],
            "o_and_p_eligible": entry["o_and_p_eligible"],
            "negotiation_status": "PENDING",
            "qty_actual": None,
            "extended_cents": 0,
            "depreciation_cents": 0,
            "tax_cents": 0,
        }
        stamp_new(line)
        DB["estimate_lines"][line["id"]] = line
        recompute_estimate(est)
        touch(est)
        return ok_object(public(line), 201)

    @a.get("/v1/estimates/<eid>/lines")
    def list_lines(eid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        est = get("estimates", eid)
        claim_visible_to(DB["claims"][est["claim_id"]], uid, role)
        items = lines_of_estimate(eid)
        return page(items, {"negotiation_status": request.args.get("negotiation_status")})

    def resolve_line(eid, line_id):
        est = get("estimates", eid)
        line = DB["estimate_lines"].get(line_id)
        if line is None or line["estimate_id"] != eid:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Line not found on this estimate")
        return est, line

    @a.patch("/v1/estimates/<eid>/lines/<line_id>")
    def patch_line(eid, line_id):
        uid, role = auth()
        require_roles(role, {EST})
        est, line = resolve_line(eid, line_id)
        data = body()
        expected = as_int(req_field(data, "expected_estimate_version"), "expected_estimate_version")
        new_qty = opt_field(data, "qty")
        new_price = opt_field(data, "unit_price_cents")
        if new_qty is not None:
            new_qty = as_num(new_qty, "qty")
            if not dec(new_qty) > 0:
                raise ApiError("ERR_INVALID_REQUEST", "qty must be > 0")
        if new_price is not None:
            new_price = as_int(new_price, "unit_price_cents")
            if new_price < 0:
                raise ApiError("ERR_INVALID_REQUEST", "unit_price_cents must be >= 0")
        if expected != est["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_estimate_version does not match the estimate's current version")
        if est["status"] not in ("DRAFT", "REVISED"):
            raise ApiError("ERR_ESTIMATE_NOT_EDITABLE",
                           "Lines may be edited only while the estimate is DRAFT or REVISED")
        if new_qty is not None:
            line["qty"] = new_qty
        if new_price is not None:
            line["unit_price_cents"] = new_price
        touch(line)
        recompute_estimate(est)
        touch(est)
        return ok_object(public(line))

    @a.post("/v1/estimates/<eid>/lines/<line_id>/remove")
    def remove_line(eid, line_id):
        uid, role = auth()
        require_roles(role, {EST})
        est, line = resolve_line(eid, line_id)
        if est["status"] not in ("DRAFT", "REVISED"):
            raise ApiError("ERR_ESTIMATE_NOT_EDITABLE",
                           "Lines may be removed only while the estimate is DRAFT or REVISED")
        line["negotiation_status"] = "REMOVED"
        touch(line)
        recompute_estimate(est)
        touch(est)
        return ok_object(public(line))

    # ------------------------------------------------- estimate actions
    @a.post("/v1/estimates/<eid>/submit")
    def submit_estimate(eid):
        uid, role = auth()
        require_roles(role, {EST})
        est = get("estimates", eid)
        claim = DB["claims"][est["claim_id"]]
        lines = [l for l in lines_of_estimate(eid) if l["negotiation_status"] != "REMOVED"]
        if len(lines) < 1:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The estimate must hold at least one non-removed line")
        if est["status"] not in ("DRAFT", "REVISED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a DRAFT or REVISED estimate can be submitted")
        if est["type"] == "INITIAL":
            if claim["status"] not in ("ESTIMATING", "NEGOTIATING"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "An INITIAL estimate submits only while the claim is ESTIMATING or NEGOTIATING")
        else:
            if claim["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "A SUPPLEMENT estimate submits only while the claim is IN_PROGRESS")
        completed = [i for i in DB["inspections"].values()
                     if i["claim_id"] == claim["id"] and i["status"] == "COMPLETED"]
        if not completed:
            raise ApiError("ERR_INSPECTION_INCOMPLETE",
                           "The claim has no COMPLETED inspection")
        dol = claim["_date_of_loss"]
        for l in lines:
            entry = DB["price_list_entries"].get(l["price_list_entry_id"])
            if entry is None:
                raise ApiError("ERR_PRICE_WINDOW_VIOLATION",
                               "A line's price list entry no longer resolves")
            if not (entry["_effective_from"] <= dol < entry["_effective_to"]):
                raise ApiError("ERR_PRICE_WINDOW_VIOLATION",
                               "A line's price list entry window does not cover the date of loss")
        if est["status"] == "REVISED":
            for l in lines_of_estimate(eid):
                if l["negotiation_status"] == "DISPUTED":
                    l["negotiation_status"] = "PENDING"
                    touch(l)
        est["status"] = "SUBMITTED"
        est["submitted_at"] = fmt_clock(now())
        touch(est)
        if est["type"] == "INITIAL" and claim["status"] == "ESTIMATING":
            claim["status"] = "NEGOTIATING"
            touch(claim)
        return ok_object(public(est))

    @a.post("/v1/estimates/<eid>/revise")
    def revise_estimate(eid):
        uid, role = auth()
        require_roles(role, {EST})
        est = get("estimates", eid)
        if est["status"] != "COUNTERED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a COUNTERED estimate can be revised")
        for l in lines_of_estimate(eid):
            if l["negotiation_status"] == "DISPUTED":
                l["negotiation_status"] = "PENDING"
                touch(l)
        est["status"] = "REVISED"
        touch(est)
        return ok_object(public(est))

    @a.post("/v1/estimates/<eid>/concede")
    def concede_estimate(eid):
        uid, role = auth()
        require_roles(role, {EST})
        est = get("estimates", eid)
        if est["status"] != "COUNTERED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a COUNTERED estimate can be conceded")
        open_rounds = [r for r in rounds_of_estimate(eid) if r["status"] == "OPEN"]
        if not open_rounds:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No OPEN negotiation round exists for this estimate")
        rnd = sorted(open_rounds, key=lambda r: r["_seq"])[-1]
        for d in dispositions_of_round(rnd["id"]):
            if d["status"] == "PENDING":
                d["status"] = "ACCEPTED"
                touch(d)
                apply_disposition(d)
        rnd["status"] = "RESOLVED"
        touch(rnd)
        recompute_round_disputed(rnd)
        recompute_estimate(est)
        approve_estimate(est)
        return ok_object(public(est))

    @a.post("/v1/estimates/<eid>/approve")
    def approve_estimate_ep(eid):
        uid, role = auth()
        require_roles(role, {ADJ})
        est = get("estimates", eid)
        if est["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SUBMITTED estimate can be approved")
        for l in lines_of_estimate(eid):
            if l["negotiation_status"] != "REMOVED":
                l["negotiation_status"] = "AGREED"
                touch(l)
        approve_estimate(est)
        return ok_object(public(est))

    @a.post("/v1/estimates/<eid>/deny")
    def deny_estimate(eid):
        uid, role = auth()
        require_roles(role, {ADJ})
        est = get("estimates", eid)
        if est["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SUBMITTED estimate can be denied")
        est["status"] = "DENIED"
        touch(est)
        claim = DB["claims"][est["claim_id"]]
        if est["type"] == "INITIAL" and claim["status"] == "NEGOTIATING":
            claim["status"] = "DENIED"
            touch(claim)
        return ok_object(public(est))

    @a.post("/v1/estimates/<eid>/record-actuals")
    def record_actuals(eid):
        uid, role = auth()
        require_roles(role, {EST})
        est = get("estimates", eid)
        data = body()
        entries = req_field(data, "entries")
        if not isinstance(entries, list):
            raise ApiError("ERR_INVALID_REQUEST", "entries must be a list")
        resolved = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ApiError("ERR_INVALID_REQUEST", "each entry must be an object")
            line_id = as_str(req_field(entry, "estimate_line_id"), "estimate_line_id")
            line = DB["estimate_lines"].get(line_id)
            if line is None:
                raise ApiError("ERR_RESOURCE_NOT_FOUND", "estimate_line_id does not resolve")
            qa = as_num(req_field(entry, "qty_actual"), "qty_actual")
            if not dec(qa) >= 0:
                raise ApiError("ERR_INVALID_REQUEST", "qty_actual must be >= 0")
            resolved.append((line, qa))
        claim = DB["claims"][est["claim_id"]]
        if est["status"] != "APPROVED" or claim["status"] not in ("IN_PROGRESS", "COMPLETE"):
            raise ApiError("ERR_ESTIMATE_NOT_EDITABLE",
                           "Actuals may be recorded only while the estimate is APPROVED and the claim IN_PROGRESS or COMPLETE")
        for line, qa in resolved:
            if line["estimate_id"] != eid:
                raise ApiError("ERR_INVALID_REQUEST",
                               "estimate_line_id does not belong to this estimate")
        for line, qa in resolved:
            line["qty_actual"] = qa
            touch(line)
        touch(est)
        return ok_object(public(est))

    # ------------------------------------------------- negotiation rounds
    def parse_dispositions(data):
        disps = req_field(data, "dispositions")
        if not isinstance(disps, list):
            raise ApiError("ERR_INVALID_REQUEST", "dispositions must be a list")
        parsed = []
        for d in disps:
            if not isinstance(d, dict):
                raise ApiError("ERR_INVALID_REQUEST", "each disposition must be an object")
            line_id = as_str(req_field(d, "estimate_line_id"), "estimate_line_id")
            line = DB["estimate_lines"].get(line_id)
            if line is None:
                raise ApiError("ERR_RESOURCE_NOT_FOUND", "estimate_line_id does not resolve")
            pq = opt_field(d, "proposed_qty")
            pp = opt_field(d, "proposed_unit_price_cents")
            pr = as_bool(opt_field(d, "propose_removal", False), "propose_removal")
            if pq is not None:
                pq = as_num(pq, "proposed_qty")
                if not dec(pq) > 0:
                    raise ApiError("ERR_INVALID_REQUEST", "proposed_qty must be > 0")
            if pp is not None:
                pp = as_int(pp, "proposed_unit_price_cents")
                if pp < 0:
                    raise ApiError("ERR_INVALID_REQUEST", "proposed_unit_price_cents must be >= 0")
            parsed.append({"line": line, "proposed_qty": pq,
                           "proposed_unit_price_cents": pp, "propose_removal": pr})
        return parsed

    def create_disposition(rnd_id, p):
        rec = {
            "id": new_id(),
            "negotiation_round_id": rnd_id,
            "estimate_line_id": p["line"]["id"],
            "proposed_qty": p["proposed_qty"],
            "proposed_unit_price_cents": p["proposed_unit_price_cents"],
            "propose_removal": p["propose_removal"],
            "status": "PENDING",
        }
        stamp_new(rec)
        DB["line_dispositions"][rec["id"]] = rec
        line = p["line"]
        if line["negotiation_status"] == "PENDING":
            line["negotiation_status"] = "DISPUTED"
            touch(line)
        return rec

    @a.post("/v1/estimates/<eid>/negotiation-rounds")
    def create_round(eid):
        uid, role = auth()
        require_roles(role, {ADJ})
        est = get("estimates", eid)
        data = body()
        parsed = parse_dispositions(data)
        if est["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SUBMITTED estimate can be countered")
        for p in parsed:
            if p["line"]["estimate_id"] != eid:
                raise ApiError("ERR_DISPOSITION_LINE_MISMATCH",
                               "A disposition targets a line that does not belong to this estimate")
        claim = DB["claims"][est["claim_id"]]
        carrier = carrier_of_claim(claim)
        due = now() + timedelta(days=carrier["negotiation_response_days"])
        rnd = {
            "id": new_id(),
            "estimate_id": eid,
            "round_number": (max([r["round_number"] for r in rounds_of_estimate(eid)])
                             if rounds_of_estimate(eid) else 0) + 1,
            "status": "OPEN",
            "due_at": fmt_clock(due),
            "disputed_amount_cents": 0,
            "_due_at_instant": due,
        }
        stamp_new(rnd)
        DB["negotiation_rounds"][rnd["id"]] = rnd
        for p in parsed:
            create_disposition(rnd["id"], p)
        recompute_round_disputed(rnd)
        est["status"] = "COUNTERED"
        touch(est)
        return ok_object(public(rnd), 201)

    @a.get("/v1/estimates/<eid>/negotiation-rounds")
    def list_rounds(eid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("estimates", eid)
        return page(rounds_of_estimate(eid), {"status": request.args.get("status")})

    @a.get("/v1/negotiation-rounds/<rid>")
    def get_round(rid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        return ok_object(public(get("negotiation_rounds", rid)))

    @a.post("/v1/negotiation-rounds/<rid>/dispositions")
    def append_dispositions(rid):
        uid, role = auth()
        require_roles(role, {ADJ})
        rnd = get("negotiation_rounds", rid)
        data = body()
        expected = as_int(req_field(data, "expected_negotiation_round_version"),
                          "expected_negotiation_round_version")
        parsed = parse_dispositions(data)
        if expected != rnd["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_negotiation_round_version does not match the round's current version")
        if rnd["status"] != "OPEN":
            raise ApiError("ERR_ROUND_NOT_OPEN", "The negotiation round is not OPEN")
        for p in parsed:
            if p["line"]["estimate_id"] != rnd["estimate_id"]:
                raise ApiError("ERR_DISPOSITION_LINE_MISMATCH",
                               "A disposition targets a line that does not belong to the round's estimate")
        for p in parsed:
            create_disposition(rnd["id"], p)
        touch(rnd)
        recompute_round_disputed(rnd)
        return ok_object(public(rnd), 201)

    @a.get("/v1/negotiation-rounds/<rid>/dispositions")
    def list_dispositions(rid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("negotiation_rounds", rid)
        items = dispositions_of_round(rid)
        return page(items, {"status": request.args.get("status")})

    @a.post("/v1/dispositions/<did>/respond")
    def respond_disposition(did):
        uid, role = auth()
        require_roles(role, {EST})
        disp = get("line_dispositions", did)
        data = body()
        outcome = as_enum(req_field(data, "outcome"), "outcome", {"ACCEPT", "REJECT"})
        if disp["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a PENDING disposition can be answered")
        rnd = DB["negotiation_rounds"][disp["negotiation_round_id"]]
        if rnd["status"] != "OPEN":
            raise ApiError("ERR_ROUND_NOT_OPEN", "The negotiation round is not OPEN")
        est = DB["estimates"][rnd["estimate_id"]]
        if outcome == "ACCEPT":
            disp["status"] = "ACCEPTED"
            touch(disp)
            apply_disposition(disp)
            recompute_estimate(est)
            touch(est)
        else:
            disp["status"] = "REJECTED"
            touch(disp)
        touch(rnd)
        recompute_round_disputed(rnd)
        maybe_resolve_round(rnd)
        return ok_object(public(disp))

    # -------------------------------------------------------- supplements
    @a.post("/v1/claims/<cid>/supplements")
    def create_supplement(cid):
        uid, role = auth()
        require_roles(role, {EST})
        claim = get("claims", cid)
        data = body()
        narrative = as_str(req_field(data, "narrative"), "narrative")
        if claim["status"] != "IN_PROGRESS":
            raise ApiError("ERR_SUPPLEMENT_NOT_PERMITTED",
                           "Supplements may be created only while the claim is IN_PROGRESS")
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "narrative": narrative,
            "status": "DRAFT",
            "submitted_at": None,
            "decided_at": None,
        }
        stamp_new(rec)
        DB["supplements"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/supplements")
    def list_supplements(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("claims", cid)
        items = [s for s in DB["supplements"].values() if s["claim_id"] == cid]
        return page(items, {"status": request.args.get("status")})

    @a.get("/v1/supplements/<sid>")
    def get_supplement(sid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        return ok_object(public(get("supplements", sid)))

    @a.post("/v1/supplements/<sid>/submit")
    def submit_supplement(sid):
        uid, role = auth()
        require_roles(role, {EST})
        supp = get("supplements", sid)
        if supp["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a DRAFT supplement can be submitted")
        claim = DB["claims"][supp["claim_id"]]
        if claim["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The claim must be IN_PROGRESS to submit a supplement")
        photos = [p for p in DB["photos"].values()
                  if p.get("supplement_id") == sid and p["tag"] == "SUPPLEMENT_EVIDENCE"]
        if not supp["narrative"] or len(photos) < 2:
            raise ApiError("ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT",
                           "A non-empty narrative and at least 2 SUPPLEMENT_EVIDENCE photos are required")
        supp["status"] = "SUBMITTED"
        supp["submitted_at"] = fmt_clock(now())
        touch(supp)
        return ok_object(public(supp))

    @a.post("/v1/supplements/<sid>/approve")
    def approve_supplement(sid):
        uid, role = auth()
        require_roles(role, {ADJ})
        supp = get("supplements", sid)
        if supp["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SUBMITTED supplement can be approved")
        supp["status"] = "APPROVED"
        supp["decided_at"] = fmt_clock(now())
        touch(supp)
        claim = DB["claims"][supp["claim_id"]]
        touch(claim)
        est = {
            "id": new_id(),
            "claim_id": claim["id"],
            "supplement_id": sid,
            "type": "SUPPLEMENT",
            "revision_number": next_revision_number(claim["id"]),
            "status": "DRAFT",
            "rcv_total_cents": 0,
            "tax_total_cents": 0,
            "overhead_profit_total_cents": 0,
            "depreciation_total_cents": 0,
            "recoverable_depreciation_cents": 0,
            "acv_total_cents": 0,
            "grand_total_cents": 0,
            "submitted_at": None,
            "approved_at": None,
        }
        stamp_new(est)
        DB["estimates"][est["id"]] = est
        return ok_object(public(supp))

    @a.post("/v1/supplements/<sid>/deny")
    def deny_supplement(sid):
        uid, role = auth()
        require_roles(role, {ADJ})
        supp = get("supplements", sid)
        if supp["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SUBMITTED supplement can be denied")
        supp["status"] = "DENIED"
        supp["decided_at"] = fmt_clock(now())
        touch(supp)
        return ok_object(public(supp))

    @a.get("/v1/supplements/<sid>/estimates")
    def list_supplement_estimates(sid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("supplements", sid)
        items = [e for e in DB["estimates"].values() if e.get("supplement_id") == sid]
        return page(items)

    # ------------------------------------------------------- code upgrades
    @a.post("/v1/claims/<cid>/code-upgrades")
    def create_code_upgrade(cid):
        uid, role = auth()
        require_roles(role, {EST})
        claim = get("claims", cid)
        data = body()
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "code_citation": as_str(req_field(data, "code_citation"), "code_citation"),
            "description": as_str(req_field(data, "description"), "description"),
            "estimated_cost_cents": as_int(req_field(data, "estimated_cost_cents"), "estimated_cost_cents"),
            "approved_cost_cents": None,
            "covered_cents": None,
            "customer_responsibility_cents": None,
            "status": "IDENTIFIED",
            "approved_at": None,
        }
        if rec["estimated_cost_cents"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "estimated_cost_cents must be > 0")
        if claim["status"] in CLAIM_TERMINAL:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Code upgrades may not be created on a terminal claim")
        stamp_new(rec)
        DB["code_upgrades"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/code-upgrades")
    def list_code_upgrades(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("claims", cid)
        items = [c for c in DB["code_upgrades"].values() if c["claim_id"] == cid]
        return page(items, {"status": request.args.get("status")})

    @a.post("/v1/code-upgrades/<cid>/approve")
    def approve_code_upgrade(cid):
        uid, role = auth()
        require_roles(role, {ADJ})
        cu = get("code_upgrades", cid)
        data = body()
        override = opt_field(data, "approved_cost_cents")
        if override is not None:
            override = as_int(override, "approved_cost_cents")
            if override <= 0:
                raise ApiError("ERR_INVALID_REQUEST", "approved_cost_cents must be > 0")
        if cu["status"] != "IDENTIFIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an IDENTIFIED code upgrade can be approved")
        claim = DB["claims"][cu["claim_id"]]
        if claim["status"] in CLAIM_TERMINAL:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The claim is terminal")
        policy = policy_of_claim(claim)
        if policy["ordinance_limit_cents"] <= 0:
            raise ApiError("ERR_ORDINANCE_NOT_COVERED",
                           "The policy has no ordinance & law coverage")
        consumed = sum(c["covered_cents"] or 0 for c in DB["code_upgrades"].values()
                       if c["claim_id"] == claim["id"] and c["status"] == "APPROVED")
        remaining = policy["ordinance_limit_cents"] - consumed
        if remaining <= 0:
            raise ApiError("ERR_ORDINANCE_CAP_EXHAUSTED",
                           "The ordinance & law bucket is exhausted")
        approved = override if override is not None else cu["estimated_cost_cents"]
        cu["approved_cost_cents"] = approved
        cu["covered_cents"] = min(approved, remaining)
        cu["customer_responsibility_cents"] = approved - cu["covered_cents"]
        cu["approved_at"] = fmt_clock(now())
        cu["status"] = "APPROVED"
        touch(cu)
        recompute_ordinance_consumed(claim)
        return ok_object(public(cu))

    @a.post("/v1/code-upgrades/<cid>/deny")
    def deny_code_upgrade(cid):
        uid, role = auth()
        require_roles(role, {ADJ})
        cu = get("code_upgrades", cid)
        if cu["status"] != "IDENTIFIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an IDENTIFIED code upgrade can be denied")
        cu["status"] = "DENIED"
        touch(cu)
        return ok_object(public(cu))

    @a.post("/v1/code-upgrades/<cid>/withdraw")
    def withdraw_code_upgrade(cid):
        uid, role = auth()
        require_roles(role, {EST})
        cu = get("code_upgrades", cid)
        if cu["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an APPROVED code upgrade can be withdrawn")
        cu["status"] = "WITHDRAWN"
        touch(cu)
        claim = DB["claims"][cu["claim_id"]]
        recompute_ordinance_consumed(claim)
        return ok_object(public(cu))

    # ------------------------------------------------- work authorizations
    @a.post("/v1/claims/<cid>/work-authorizations")
    def create_wa(cid):
        uid, role = auth()
        require_roles(role, {CA})
        claim = get("claims", cid)
        data = body()
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "direct_pay_assignment": as_bool(req_field(data, "direct_pay_assignment"), "direct_pay_assignment"),
            "deductible_acknowledged": as_bool(req_field(data, "deductible_acknowledged"), "deductible_acknowledged"),
            "status": "DRAFT",
            "scope_rcv_cents": None,
            "signed_at": None,
            "expires_at": None,
            "voided_reason": None,
        }
        if claim["status"] not in ("APPROVED", "ON_HOLD"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Work authorizations require the claim APPROVED or ON_HOLD")
        stamp_new(rec)
        DB["work_authorizations"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/work-authorizations")
    def list_was(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        items = [w for w in DB["work_authorizations"].values() if w["claim_id"] == cid]
        return page(items, {"status": request.args.get("status")})

    @a.post("/v1/work-authorizations/<wid>/sign")
    def sign_wa(wid):
        uid, role = auth()
        require_roles(role, {CUST})
        wa = get("work_authorizations", wid)
        claim = DB["claims"][wa["claim_id"]]
        claim_visible_to(claim, uid, role)
        if wa["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a DRAFT work authorization can be signed")
        if claim["status"] not in ("APPROVED", "ON_HOLD"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The claim must be APPROVED or ON_HOLD to sign")
        signed = now()
        expires = signed + timedelta(days=WA_VALIDITY_DAYS)
        wa["scope_rcv_cents"] = claim["rcv_total_cents"]
        wa["signed_at"] = fmt_clock(signed)
        wa["expires_at"] = fmt_clock(expires)
        wa["_expires_at_instant"] = expires
        wa["status"] = "SIGNED"
        touch(wa)
        if claim["status"] == "APPROVED":
            claim["status"] = "AUTHORIZED"
            touch(claim)
            if wa["direct_pay_assignment"]:
                advance = max(0, claim["acv_total_cents"] - claim["deductible_cents"])
                if advance > 0:
                    create_payment(claim["id"], "ACV_ADVANCE", advance, True)
        else:  # ON_HOLD
            claim["status"] = "IN_PROGRESS"
            touch(claim)
        return ok_object(public(wa))

    # ------------------------------------------------------------ invoices
    @a.post("/v1/claims/<cid>/invoices")
    def create_invoice(cid):
        uid, role = auth()
        require_roles(role, {CA})
        claim = get("claims", cid)
        if claim["status"] != "COMPLETE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Invoice creation requires the claim COMPLETE")
        if active_invoice(cid) is not None:
            raise ApiError("ERR_DUPLICATE_ACTIVE_INVOICE",
                           "The claim already has a non-voided invoice")
        policy = policy_of_claim(claim)
        carrier = carrier_of_claim(claim)
        approved = [e for e in DB["estimates"].values()
                    if e["claim_id"] == cid and e["status"] in ("APPROVED", "LOCKED")]
        total = 0
        for est in approved:
            totals = estimate_totals(lines_of_estimate(est["id"]), carrier,
                                     policy["recoverable_depreciation"],
                                     variant="final")
            total += totals["grand_total_cents"]
        cleared_sum = sum(p["amount_cents"] for p in DB["payments"].values()
                          if p["claim_id"] == cid and p["status"] == "CLEARED")
        applied = min(cleared_sum, total)
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "status": "DRAFT",
            "total_cents": total,
            "applied_cents": applied,
            "outstanding_cents": total - applied,
            "created_by_user_id": uid,
            "issued_at": None,
            "voided_at": None,
        }
        stamp_new(rec)
        DB["invoices"][rec["id"]] = rec
        for est in approved:
            if est["status"] == "APPROVED":
                est["status"] = "LOCKED"
                touch(est)
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/invoices")
    def list_invoices(cid):
        uid, role = auth()
        require_roles(role, {CA, ADJ, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        items = [i for i in DB["invoices"].values() if i["claim_id"] == cid]
        return page(items, {"status": request.args.get("status")})

    @a.get("/v1/invoices/<iid>")
    def get_invoice(iid):
        uid, role = auth()
        require_roles(role, {CA, ADJ, CUST})
        inv = get("invoices", iid)
        claim_visible_to(DB["claims"][inv["claim_id"]], uid, role)
        return ok_object(public(inv))

    @a.post("/v1/invoices/<iid>/issue")
    def issue_invoice(iid):
        uid, role = auth()
        require_roles(role, {CA})
        inv = get("invoices", iid)
        claim = DB["claims"][inv["claim_id"]]
        if inv["status"] != "DRAFT" or claim["status"] != "COMPLETE":
            raise ApiError("ERR_INVOICE_NOT_ISSUABLE",
                           "Invoice issue requires a DRAFT invoice and a COMPLETE claim")
        inv["status"] = "ISSUED"
        inv["issued_at"] = fmt_clock(now())
        touch(inv)
        claim["status"] = "INVOICED"
        touch(claim)
        claim["outstanding_balance_cents"] = inv["outstanding_cents"]
        acv_advance_paid = sum(p["amount_cents"] for p in DB["payments"].values()
                               if p["claim_id"] == claim["id"]
                               and p["type"] == "ACV_ADVANCE" and p["status"] == "CLEARED")
        gap = max(0, inv["total_cents"] - acv_advance_paid - claim["deductible_cents"])
        recovery = min(claim["recoverable_depreciation_cents"], gap)
        if recovery > 0:
            create_payment(claim["id"], "DEPRECIATION_RECOVERY", recovery, True,
                           invoice_id=inv["id"])
        recompute_claim_ledger(claim)
        return ok_object(public(inv))

    @a.post("/v1/invoices/<iid>/void")
    def void_invoice(iid):
        uid, role = auth()
        require_roles(role, {CA})
        inv = get("invoices", iid)
        if uid == inv["created_by_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION",
                           "The invoice creator may not void it")
        if inv["status"] not in ("DRAFT", "ISSUED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a DRAFT or ISSUED invoice can be voided")
        claim = DB["claims"][inv["claim_id"]]
        was_issued = inv["status"] == "ISSUED"
        inv["status"] = "VOIDED"
        inv["voided_at"] = fmt_clock(now())
        touch(inv)
        if was_issued:
            for p in DB["payments"].values():
                if (p.get("invoice_id") == iid and p["auto_created"]
                        and p["type"] == "DEPRECIATION_RECOVERY"
                        and p["status"] == "REQUESTED"):
                    p["status"] = "VOIDED"
                    touch(p)
            if claim["status"] == "INVOICED":
                claim["status"] = "COMPLETE"
            touch(claim)
            recompute_claim_ledger(claim)
        else:
            touch(claim)
        return ok_object(public(inv))

    @a.get("/v1/invoices/<iid>/payments")
    def list_invoice_payments(iid):
        uid, role = auth()
        require_roles(role, {CA, ADJ, CUST})
        inv = get("invoices", iid)
        claim_visible_to(DB["claims"][inv["claim_id"]], uid, role)
        items = [p for p in DB["payments"].values() if p.get("invoice_id") == iid]
        return page(items)

    # ------------------------------------------------------------ payments
    @a.post("/v1/claims/<cid>/payments")
    def create_payment_ep(cid):
        uid, role = auth()
        require_roles(role, {CA, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        data = body()
        ptype = as_enum(req_field(data, "type"), "type",
                        {"ACV_ADVANCE", "DEPRECIATION_RECOVERY", "DEDUCTIBLE", "CUSTOMER_BALANCE"})
        amount = as_int(req_field(data, "amount_cents"), "amount_cents")
        if amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0")
        if ptype in ("ACV_ADVANCE", "DEPRECIATION_RECOVERY"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Carrier-direction payment types are only system-created")
        if ptype == "DEDUCTIBLE" and role != CUST:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Only a Customer may record DEDUCTIBLE payments")
        if ptype == "CUSTOMER_BALANCE" and role != CA:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Only a ContractorAdmin may record CUSTOMER_BALANCE payments")
        if claim["status"] not in PAYABLE_STATES:
            raise ApiError("ERR_CLAIM_NOT_PAYABLE",
                           "The claim is not in a payable state")
        if ptype == "CUSTOMER_BALANCE":
            inv = active_invoice(cid)
            if inv is not None and inv["status"] in ("ISSUED", "SETTLED"):
                if amount > inv["outstanding_cents"]:
                    raise ApiError("ERR_PAYMENT_EXCEEDS_OUTSTANDING",
                                   "CUSTOMER_BALANCE exceeds the active invoice's outstanding amount")
        if ptype == "DEDUCTIBLE":
            pending = sum(p["amount_cents"] for p in DB["payments"].values()
                          if p["claim_id"] == cid and p["type"] == "DEDUCTIBLE"
                          and p["status"] in ("CLEARED", "ISSUED", "APPROVED", "REQUESTED"))
            if pending + amount > claim["deductible_cents"]:
                raise ApiError("ERR_DEDUCTIBLE_OVERPAID",
                               "DEDUCTIBLE payments would exceed the claim's deductible")
        rec = create_payment(cid, ptype, amount, False)
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/payments")
    def list_payments(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        items = [p for p in DB["payments"].values() if p["claim_id"] == cid]
        return page(items, {"type": request.args.get("type"),
                            "status": request.args.get("status")})

    def check_direction_role(payment, role):
        if payment["direction"] == "CARRIER_TO_CONTRACTOR" and role != ADJ:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Carrier-direction payments require the Adjuster")
        if payment["direction"] == "CUSTOMER_TO_CONTRACTOR" and role != CA:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Customer-direction payments require the ContractorAdmin")

    @a.post("/v1/payments/<pid>/approve")
    def approve_payment(pid):
        uid, role = auth()
        require_roles(role, {ADJ, CA})
        payment = get("payments", pid)
        check_direction_role(payment, role)
        if payment["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a REQUESTED payment can be approved")
        if payment["direction"] == "CARRIER_TO_CONTRACTOR":
            was = [w for w in DB["work_authorizations"].values()
                   if w["claim_id"] == payment["claim_id"]
                   and w["status"] == "SIGNED" and w["deductible_acknowledged"]]
            if not was:
                raise ApiError("ERR_AUTHORIZATION_MISSING",
                               "Carrier payment approval requires a signed, deductible-acknowledged work authorization")
        payment["status"] = "APPROVED"
        touch(payment)
        return ok_object(public(payment))

    @a.post("/v1/payments/<pid>/issue")
    def issue_payment(pid):
        uid, role = auth()
        require_roles(role, {ADJ, CA})
        payment = get("payments", pid)
        check_direction_role(payment, role)
        if payment["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an APPROVED payment can be issued")
        payment["status"] = "ISSUED"
        touch(payment)
        return ok_object(public(payment))

    @a.post("/v1/payments/<pid>/clear")
    def clear_payment(pid):
        uid, role = auth()
        require_roles(role, {CA})
        payment = get("payments", pid)
        if payment["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an ISSUED payment can be cleared")
        payment["status"] = "CLEARED"
        touch(payment)
        claim = DB["claims"][payment["claim_id"]]
        recompute_claim_ledger(claim)
        return ok_object(public(payment))

    @a.post("/v1/payments/<pid>/return")
    def return_payment(pid):
        uid, role = auth()
        require_roles(role, {CA})
        payment = get("payments", pid)
        if payment["status"] not in ("ISSUED", "CLEARED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an ISSUED or CLEARED payment can be returned")
        payment["status"] = "RETURNED"
        touch(payment)
        claim = DB["claims"][payment["claim_id"]]
        recompute_claim_ledger(claim)
        return ok_object(public(payment))

    @a.post("/v1/payments/<pid>/requeue")
    def requeue_payment(pid):
        uid, role = auth()
        require_roles(role, {CA})
        payment = get("payments", pid)
        if payment["status"] != "RETURNED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a RETURNED payment can be requeued")
        payment["status"] = "REQUESTED"
        touch(payment)
        return ok_object(public(payment))
