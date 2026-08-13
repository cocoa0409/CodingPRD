"""Routes: surgical cases (schedule, release, repin, cancel, complete)."""

from datetime import timedelta
from decimal import Decimal

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

SCA = "SupplyChainAnalyst"
CN = "CirculatingNurse"


def _case_interval(c):
    start = c["scheduled_start"]
    end = start + timedelta(minutes=c["expected_duration_min"])
    return start, end


def register_routes(app):

    # ---------------------------------------------------------------- cases
    @app.route("/perioperative/cases", methods=["POST"])
    def create_case():
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        surgeon_id = U.req_str(body, "surgeon_id")
        card_id = U.req_str(body, "card_id")
        scheduled_start = U.req_dt(body, "scheduled_start")
        expected_duration_min = U.req_int(body, "expected_duration_min")
        if expected_duration_min < 1:
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Field 'expected_duration_min' must be >= 1", 400)
        room = U.req_str(body, "room")
        consignment_budget_cents = U.opt_int(body, "consignment_budget_cents")
        if (consignment_budget_cents is not None
                and consignment_budget_cents < 1):
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Field 'consignment_budget_cents' must be >= 1 "
                           "when present", 400)
        # Existence (body-referenced ids, in request order)
        surgeon = D.get_or_404(db.surgeons, surgeon_id, "Surgeon")
        card = D.get_or_404(db.preference_cards, card_id, "PreferenceCard")
        # Cross-entity coherence, pinned order: card ACTIVE, surgeon match,
        # surgeon ACTIVE (PRD section 2.7 tier 8)
        if card["status"] != "ACTIVE":
            raise ApiError(E.ERR_PINNED_CARD_NOT_ACTIVE,
                           "Pinned card is not ACTIVE", 409)
        if card["surgeon_id"] != surgeon_id:
            raise ApiError(E.ERR_CARD_SURGEON_MISMATCH,
                           "Case surgeon differs from the card's surgeon", 409)
        if surgeon["status"] != "ACTIVE":
            raise ApiError(E.ERR_SURGEON_INACTIVE,
                           "Surgeon is INACTIVE", 409)
        # Scheduling conflicts: room overlap first, then surgeon buffer
        new_start = scheduled_start
        new_end = new_start + timedelta(minutes=expected_duration_min)
        for other in db.cases.values():
            if other["status"] == "CANCELLED" or other["room"] != room:
                continue
            o_start, o_end = _case_interval(other)
            # Half-open interval intersection; touching endpoints allowed
            if new_start < o_end and o_start < new_end:
                raise ApiError(E.ERR_ROOM_DOUBLE_BOOKED,
                               "Room has a conflicting case", 409)
        buffer = timedelta(minutes=D.SURGEON_TURNOVER_MINUTES)
        for other in db.cases.values():
            if other["status"] == "CANCELLED" or other["surgeon_id"] != surgeon_id:
                continue
            o_start, o_end = _case_interval(other)
            # Mandatory 30-minute turnover gap; exactly 30 minutes is allowed
            if o_start < new_end + buffer and o_end > new_start - buffer:
                raise ApiError(E.ERR_SURGEON_SCHEDULE_CONFLICT,
                               "Surgeon has a case within the 30-minute "
                               "turnover buffer", 409)
        case = {
            "surgeon_id": surgeon_id,
            "card_id": card_id,
            "pinned_card_version_number": card["version_number"],
            "procedure_name": card["procedure_name"],
            "scheduled_start": new_start,
            "expected_duration_min": expected_duration_min,
            "room": room,
            "consignment_budget_cents": consignment_budget_cents,
            "status": "SCHEDULED",
            "standard_cost_cents": None,
            "actual_cost_cents": None,
            "waste_cost_cents": None,
            "pick_exception_count": 0,
        }
        D.stamp_new(case)
        db.cases[case["id"]] = case
        return U.success_object(D.ser_case(case), 201)

    @app.route("/perioperative/cases", methods=["GET"])
    def list_cases():
        U.authenticate()
        limit, offset = U.pagination_params()
        cases = U.apply_filters(list(db.cases.values()), [
            ("surgeon_id", "surgeon_id"),
            ("card_id", "card_id"),
            ("status", "status"),
            ("room", "room"),
        ])
        page, total = U.paginate(cases, limit, offset)
        return U.success_list([D.ser_case(c) for c in page],
                              total, limit, offset)

    @app.route("/perioperative/cases/<cid>", methods=["GET"])
    def get_case(cid):
        U.authenticate()
        case = D.get_or_404(db.cases, cid, "SurgicalCase")
        return U.success_object(D.ser_case(case), 200)

    @app.route("/perioperative/cases/<cid>/release-pick-list", methods=["POST"])
    def release_pick_list(cid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        case = D.get_or_404(db.cases, cid, "SurgicalCase")
        if case["status"] != "SCHEDULED":
            raise ApiError(E.ERR_CASE_NOT_SCHEDULED,
                           "Case is not SCHEDULED", 409)
        if D.pick_list_for_case(cid) is not None:
            raise ApiError(E.ERR_PICK_LIST_EXISTS,
                           "Case already has a pick list", 409)
        card = db.preference_cards.get(case["card_id"])
        if card is None or card["status"] != "ACTIVE":
            raise ApiError(E.ERR_PINNED_CARD_NOT_ACTIVE,
                           "Pinned card is not ACTIVE", 409)
        # Create the pick list with one snapshot line per pinned card line
        pick_list = {
            "case_id": cid,
            "card_id": case["card_id"],
            "card_version_number": case["pinned_card_version_number"],
            "status": "GENERATED",
        }
        D.stamp_new(pick_list)
        db.pick_lists[pick_list["id"]] = pick_list
        standard_cost = 0
        for cl in D.lines_of_card(card["id"]):
            item = db.supply_items.get(cl["supply_item_id"])
            unit_cost = item["unit_cost_cents"] if item else 0
            pl_line = {
                "pick_list_id": pick_list["id"],
                "supply_item_id": cl["supply_item_id"],
                "designation": cl["designation"],
                "qty_requested": cl["quantity"],
                "qty_picked": 0,
                "qty_returned_unopened": 0,
                "unit_cost_cents": unit_cost,
                "pick_sequence": cl["pick_sequence"],
                "status": "PENDING",
                "substituted_item_id": None,
                "short_reason_code": None,
            }
            D.stamp_new(pl_line)
            db.pick_list_lines[pl_line["id"]] = pl_line
            standard_cost += cl["quantity"] * unit_cost
        case["standard_cost_cents"] = standard_cost
        case["status"] = "PICKING_RELEASED"
        D.bump(case)
        return U.success_object(D.ser_pick_list(pick_list), 201)

    @app.route("/perioperative/cases/<cid>/repin-card", methods=["POST"])
    def repin_card(cid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        card_id = U.req_str(body, "card_id")
        expected_case_version = U.req_int(body, "expected_case_version")
        case = D.get_or_404(db.cases, cid, "SurgicalCase")
        card = D.get_or_404(db.preference_cards, card_id, "PreferenceCard")
        if case["status"] != "SCHEDULED":
            raise ApiError(E.ERR_CASE_NOT_SCHEDULED,
                           "Case is not SCHEDULED", 409)
        # OCC: after state, before business rules (PRD section 2.6)
        if expected_case_version != case["version"]:
            raise ApiError(E.ERR_STALE_VERSION,
                           "expected_case_version does not match the case's "
                           "current version", 412)
        if card["status"] != "ACTIVE":
            raise ApiError(E.ERR_PINNED_CARD_NOT_ACTIVE,
                           "Target card is not ACTIVE", 409)
        if card["surgeon_id"] != case["surgeon_id"]:
            raise ApiError(E.ERR_CARD_SURGEON_MISMATCH,
                           "Target card belongs to a different surgeon", 409)
        if card["procedure_name"] != case["procedure_name"]:
            raise ApiError(E.ERR_CARD_SURGEON_MISMATCH,
                           "Target card is for a different procedure", 409)
        case["card_id"] = card_id
        case["pinned_card_version_number"] = card["version_number"]
        case["procedure_name"] = card["procedure_name"]
        D.bump(case)
        return U.success_object(D.ser_case(case), 200)

    @app.route("/perioperative/cases/<cid>/cancel", methods=["POST"])
    def cancel_case(cid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        case = D.get_or_404(db.cases, cid, "SurgicalCase")
        pick_list = D.pick_list_for_case(cid)
        cancellable = case["status"] in ("SCHEDULED", "PICKING_RELEASED")
        if cancellable and pick_list is not None:
            cancellable = pick_list["status"] in (
                "GENERATED", "IN_PICKING", "PICKING_EXCEPTION")
        if not cancellable:
            raise ApiError(E.ERR_CASE_NOT_CANCELLABLE,
                           "Case cannot be cancelled in its current state", 409)
        # Restock every picked quantity back to the item it was drawn from
        if pick_list is not None:
            for line in D.lines_of_pick_list(pick_list["id"]):
                if line["qty_picked"] > 0:
                    item = D.picked_item_of_line(line)
                    if item is not None:
                        item["on_hand_quantity"] += line["qty_picked"]
                        D.bump(item)
            pick_list["status"] = "CANCELLED"
            D.bump(pick_list)
        case["status"] = "CANCELLED"
        D.bump(case)
        return U.success_object(D.ser_case(case), 200)

    @app.route("/perioperative/cases/<cid>/complete", methods=["POST"])
    def complete_case(cid):
        _, role = U.authenticate()
        U.authorize(role, [CN])
        body = U.get_body()
        raw_entries = U.req_list(body, "usage_entries")
        # Body shape: every entry well-formed, qty_used >= 0
        entries = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Each usage entry must be an object", 400)
            line_id = entry.get("pick_list_line_id")
            if not isinstance(line_id, str) or line_id == "":
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Field 'pick_list_line_id' is required and must "
                               "be a non-empty string", 400)
            qty_used = entry.get("qty_used")
            if isinstance(qty_used, bool) or not isinstance(qty_used, int):
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Field 'qty_used' is required and must be an "
                               "integer", 400)
            if qty_used < 0:
                raise ApiError(E.ERR_INVALID_QUANTITY,
                               "Field 'qty_used' must be >= 0", 400)
            entries.append((line_id, qty_used))
        case = D.get_or_404(db.cases, cid, "SurgicalCase")
        # Existence of every referenced pick line
        entry_lines = []
        for line_id, _qty in entries:
            entry_lines.append(
                D.get_or_404(db.pick_list_lines, line_id, "PickListLine"))
        # State
        pick_list = D.pick_list_for_case(cid)
        if (case["status"] != "IN_PROGRESS" or pick_list is None
                or pick_list["status"] != "RETURNED"):
            raise ApiError(E.ERR_CASE_NOT_COMPLETABLE,
                           "Case is not IN_PROGRESS with a RETURNED pick list",
                           409)
        # Clinical safety: usage within opened quantity
        for line, (_lid, qty_used) in zip(entry_lines, entries):
            qty_opened = line["qty_picked"] - line["qty_returned_unopened"]
            if qty_used > qty_opened:
                raise ApiError(E.ERR_USAGE_EXCEEDS_OPENED,
                               "qty_used exceeds the line's opened quantity",
                               422)
        # Coherence: every entry line belongs to this case's pick list
        for line in entry_lines:
            if line["pick_list_id"] != pick_list["id"]:
                raise ApiError(E.ERR_LINE_CASE_MISMATCH,
                               "Usage entry references a pick line that does "
                               "not belong to this case's pick list", 409)
        # ---- Everything below is computed first, committed atomically ----
        used_by_line = {}
        for line_id, qty_used in entries:
            used_by_line[line_id] = qty_used  # last entry wins on duplicates

        usage_specs = []
        for line in D.lines_of_pick_list(pick_list["id"]):
            if line["status"] not in ("PICKED", "SUBSTITUTED"):
                continue
            qty_opened = line["qty_picked"] - line["qty_returned_unopened"]
            qty_used = used_by_line.get(line["id"], 0)
            consumed_item = D.picked_item_of_line(line)
            spec = {
                "case_id": cid,
                "pick_list_line_id": line["id"],
                "supply_item_id": (consumed_item["id"] if consumed_item
                                   else line["supply_item_id"]),
                "qty_opened": qty_opened,
                "qty_used": qty_used,
                "qty_wasted": qty_opened - qty_used,
                "unit_cost_cents": line["unit_cost_cents"],
                "_item": consumed_item,
                "_designation": line["designation"],
                "_line": line,
            }
            spec["waste_charge_cents"] = D.waste_charge_for(
                spec, consumed_item, line["designation"])
            usage_specs.append(spec)

        used_cost = sum(s["qty_used"] * s["unit_cost_cents"]
                        for s in usage_specs)
        waste_cost = sum(s["waste_charge_cents"] for s in usage_specs)
        actual_cost = used_cost + waste_cost

        # Consignment charges: bill on open, not on use
        charge_specs = []
        for s in usage_specs:
            item = s["_item"]
            if (item is not None and item["consignment_flag"]
                    and s["qty_opened"] > 0):
                charge_specs.append({
                    "case_id": cid,
                    "supply_item_id": item["id"],
                    "qty_billed": s["qty_opened"],
                    "unit_cost_cents": s["unit_cost_cents"],
                    "amount_cents": s["qty_opened"] * s["unit_cost_cents"],
                    "_usage_spec": s,
                })
        # Fiscal guard (priority 11) runs before any mutation
        budget = case["consignment_budget_cents"]
        if budget is not None:
            total_charges = sum(c["amount_cents"] for c in charge_specs)
            if total_charges > budget:
                raise ApiError(E.ERR_CONSIGNMENT_BUDGET_EXCEEDED,
                               "Resulting consignment charges exceed the "
                               "case's consignment budget", 402)

        # ---- Audit scoring (computed pre-commit from the specs) ----
        pick_lines = D.lines_of_pick_list(pick_list["id"])
        total_line_count = len(pick_lines)
        matched = 0
        for line in pick_lines:
            if line["status"] == "PICKED":
                qty_used = used_by_line.get(line["id"], 0)
                if qty_used == line["qty_requested"]:
                    matched += 1
        if total_line_count > 0:
            line_match_pct = D.round_pct(
                Decimal(matched) * Decimal(100) / Decimal(total_line_count))
        else:
            line_match_pct = 0.0
        standard_cost = case["standard_cost_cents"] or 0
        if standard_cost == 0:
            spend_match_pct = 100.0 if actual_cost == 0 else 0.0
            waste_pct = 0.0
        else:
            ratio = (Decimal(abs(actual_cost - standard_cost))
                     / Decimal(standard_cost))
            spend_match_pct = D.round_pct(max(Decimal(0), Decimal(1) - ratio)
                                          * Decimal(100))
            waste_pct = D.round_pct(Decimal(waste_cost) * Decimal(100)
                                    / Decimal(standard_cost))
        waste_flag = Decimal(str(waste_pct)) >= D.WASTE_FLAG_THRESHOLD_PCT

        # ---- Atomic commit ----
        for s in usage_specs:
            record = {
                "case_id": s["case_id"],
                "pick_list_line_id": s["pick_list_line_id"],
                "supply_item_id": s["supply_item_id"],
                "qty_opened": s["qty_opened"],
                "qty_used": s["qty_used"],
                "qty_wasted": s["qty_wasted"],
                "unit_cost_cents": s["unit_cost_cents"],
                "waste_charge_cents": s["waste_charge_cents"],
            }
            D.stamp_new(record)
            db.usage_records[record["id"]] = record
            s["_record"] = record
        for c in charge_specs:
            charge = {
                "case_id": c["case_id"],
                "usage_record_id": c["_usage_spec"]["_record"]["id"],
                "supply_item_id": c["supply_item_id"],
                "qty_billed": c["qty_billed"],
                "unit_cost_cents": c["unit_cost_cents"],
                "amount_cents": c["amount_cents"],
                "status": "PENDING",
            }
            D.stamp_new(charge)
            db.consignment_charges[charge["id"]] = charge
        audit = {
            "case_id": cid,
            "card_id": case["card_id"],
            "card_version_number": case["pinned_card_version_number"],
            "matched_line_count": matched,
            "total_line_count": total_line_count,
            "line_match_pct": line_match_pct,
            "spend_match_pct": spend_match_pct,
            "waste_pct": waste_pct,
            "waste_flag": waste_flag,
            "status": "GENERATED",
            "dispute_comment": None,
        }
        D.stamp_new(audit)
        db.audits[audit["id"]] = audit
        # Card rollup: flagged count + rolling mean of line_match_pct
        card = db.preference_cards.get(case["card_id"])
        if card is not None:
            if waste_flag:
                card["flagged_audit_count"] += 1
            pcts = [Decimal(str(a["line_match_pct"]))
                    for a in db.audits.values()
                    if a["card_id"] == card["id"]]
            if pcts:
                mean = sum(pcts) / Decimal(len(pcts))
                card["rolling_line_match_pct"] = D.round_pct(mean)
            D.bump(card)
        case["actual_cost_cents"] = actual_cost
        case["waste_cost_cents"] = waste_cost
        case["status"] = "COMPLETED"
        D.bump(case)
        pick_list["status"] = "CLOSED"
        D.bump(pick_list)
        return U.success_object(D.ser_case(case), 200)
