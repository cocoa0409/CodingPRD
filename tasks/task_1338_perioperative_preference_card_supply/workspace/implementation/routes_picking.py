"""Routes: pick lists and pick list lines."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

CT = "CartTechnician"


def _resolve_list_stage(list_obj):
    """Auto-transition after a line resolves: when no PENDING or SHORT lines
    remain, an IN_PICKING list moves to STAGED."""
    lines = D.lines_of_pick_list(list_obj["id"])
    open_lines = [l for l in lines if l["status"] in ("PENDING", "SHORT")]
    if not open_lines and list_obj["status"] == "IN_PICKING":
        list_obj["status"] = "STAGED"
        D.bump(list_obj)


def register_routes(app):

    # ------------------------------------------------------------ pick lists
    @app.route("/perioperative/pick-lists", methods=["GET"])
    def list_pick_lists():
        U.authenticate()
        limit, offset = U.pagination_params()
        lists = U.apply_filters(list(db.pick_lists.values()), [
            ("case_id", "case_id"),
            ("card_id", "card_id"),
            ("status", "status"),
        ])
        page, total = U.paginate(lists, limit, offset)
        return U.success_list([D.ser_pick_list(p) for p in page],
                              total, limit, offset)

    @app.route("/perioperative/pick-lists/<pid>", methods=["GET"])
    def get_pick_list(pid):
        U.authenticate()
        pl = D.get_or_404(db.pick_lists, pid, "PickList")
        return U.success_object(D.ser_pick_list(pl), 200)

    @app.route("/perioperative/pick-lists/<pid>/begin-picking", methods=["POST"])
    def begin_picking(pid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        pl = D.get_or_404(db.pick_lists, pid, "PickList")
        if pl["status"] != "GENERATED":
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not GENERATED", 409)
        pl["status"] = "IN_PICKING"
        D.bump(pl)
        return U.success_object(D.ser_pick_list(pl), 200)

    @app.route("/perioperative/pick-lists/<pid>/dispatch", methods=["POST"])
    def dispatch(pid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        pl = D.get_or_404(db.pick_lists, pid, "PickList")
        if pl["status"] != "STAGED":
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not STAGED", 409)
        pl["status"] = "DISPATCHED"
        D.bump(pl)
        case = db.cases.get(pl["case_id"])
        if case is not None and case["status"] == "PICKING_RELEASED":
            case["status"] = "IN_PROGRESS"
            D.bump(case)
        return U.success_object(D.ser_pick_list(pl), 200)

    @app.route("/perioperative/pick-lists/<pid>/return", methods=["POST"])
    def return_list(pid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        body = U.get_body()
        raw_entries = U.req_list(body, "return_entries")
        entries = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Each return entry must be an object", 400)
            line_id = entry.get("pick_list_line_id")
            if not isinstance(line_id, str) or line_id == "":
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Field 'pick_list_line_id' is required and must "
                               "be a non-empty string", 400)
            qty = entry.get("qty_returned_unopened")
            if isinstance(qty, bool) or not isinstance(qty, int):
                raise ApiError(E.ERR_INVALID_REQUEST,
                               "Field 'qty_returned_unopened' is required and "
                               "must be an integer", 400)
            entries.append((line_id, qty))
        pl = D.get_or_404(db.pick_lists, pid, "PickList")
        entry_lines = [D.get_or_404(db.pick_list_lines, lid, "PickListLine")
                       for lid, _q in entries]
        if pl["status"] != "DISPATCHED":
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not DISPATCHED", 409)
        for line in entry_lines:
            if line["pick_list_id"] != pid:
                raise ApiError(E.ERR_LINE_CASE_MISMATCH,
                               "Return entry references a pick line that does "
                               "not belong to this pick list", 409)
        for line, (_lid, qty) in zip(entry_lines, entries):
            if qty < 0 or qty > line["qty_picked"]:
                raise ApiError(E.ERR_INVALID_QUANTITY,
                               "qty_returned_unopened must lie between 0 and "
                               "the line's qty_picked", 400)
        # Commit (duplicate entries for a line: the last one wins)
        final_by_line = {}
        for line_id, qty in entries:
            final_by_line[line_id] = qty
        for line_id, qty in final_by_line.items():
            line = db.pick_list_lines[line_id]
            line["qty_returned_unopened"] = qty
            D.bump(line)
            if qty > 0:
                item = D.picked_item_of_line(line)
                if item is not None:
                    item["on_hand_quantity"] += qty
                    D.bump(item)
        pl["status"] = "RETURNED"
        D.bump(pl)
        return U.success_object(D.ser_pick_list(pl), 200)

    # ------------------------------------------------------- pick list lines
    @app.route("/perioperative/pick-list-lines", methods=["GET"])
    def list_pick_list_lines():
        U.authenticate()
        limit, offset = U.pagination_params()
        lines = U.apply_filters(list(db.pick_list_lines.values()), [
            ("pick_list_id", "pick_list_id"),
            ("supply_item_id", "supply_item_id"),
            ("substituted_item_id", "substituted_item_id"),
            ("status", "status"),
        ])
        page, total = U.paginate(
            lines, limit, offset,
            sort_key=lambda l: (l["pick_sequence"], l["created_at"], l["_seq"]),
        )
        return U.success_list([D.ser_pick_list_line(l) for l in page],
                              total, limit, offset)

    @app.route("/perioperative/pick-list-lines/<lid>", methods=["GET"])
    def get_pick_list_line(lid):
        U.authenticate()
        line = D.get_or_404(db.pick_list_lines, lid, "PickListLine")
        return U.success_object(D.ser_pick_list_line(line), 200)

    @app.route("/perioperative/pick-list-lines/<lid>/pick", methods=["POST"])
    def pick_line(lid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        line = D.get_or_404(db.pick_list_lines, lid, "PickListLine")
        if line["status"] != "PENDING":
            raise ApiError(E.ERR_LINE_NOT_PENDING,
                           "Pick line is not PENDING", 409)
        pl = db.pick_lists.get(line["pick_list_id"])
        if pl is None or pl["status"] not in ("IN_PICKING", "PICKING_EXCEPTION"):
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not IN_PICKING or PICKING_EXCEPTION",
                           409)
        item = db.supply_items.get(line["supply_item_id"])
        if item is None or item["on_hand_quantity"] < line["qty_requested"]:
            raise ApiError(E.ERR_INSUFFICIENT_STOCK,
                           "Insufficient stock for the requested quantity",
                           409)
        line["qty_picked"] = line["qty_requested"]
        line["status"] = "PICKED"
        D.bump(line)
        item["on_hand_quantity"] -= line["qty_requested"]
        D.bump(item)
        _resolve_list_stage(pl)
        return U.success_object(D.ser_pick_list_line(line), 200)

    @app.route("/perioperative/pick-list-lines/<lid>/mark-short",
               methods=["POST"])
    def mark_short(lid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        body = U.get_body()
        reason_code = U.req_str(body, "reason_code")
        line = D.get_or_404(db.pick_list_lines, lid, "PickListLine")
        if line["status"] != "PENDING":
            raise ApiError(E.ERR_LINE_NOT_PENDING,
                           "Pick line is not PENDING", 409)
        pl = db.pick_lists.get(line["pick_list_id"])
        if pl is None or pl["status"] not in ("IN_PICKING", "PICKING_EXCEPTION"):
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not IN_PICKING or PICKING_EXCEPTION",
                           409)
        line["status"] = "SHORT"
        line["short_reason_code"] = reason_code
        D.bump(line)
        # Entering PICKING_EXCEPTION increments the case's exception counter;
        # a repeated short while already in exception does not.
        if pl["status"] == "IN_PICKING":
            pl["status"] = "PICKING_EXCEPTION"
            D.bump(pl)
            case = db.cases.get(pl["case_id"])
            if case is not None:
                case["pick_exception_count"] += 1
                D.bump(case)
        return U.success_object(D.ser_pick_list_line(line), 200)

    @app.route("/perioperative/pick-list-lines/<lid>/substitute",
               methods=["POST"])
    def substitute(lid):
        _, role = U.authenticate()
        U.authorize(role, [CT])
        body = U.get_body()
        substitute_id = U.req_str(body, "substitute_supply_item_id")
        override = U.opt_bool(body, "override_price_threshold", False)
        line = D.get_or_404(db.pick_list_lines, lid, "PickListLine")
        sub = D.get_or_404(db.supply_items, substitute_id, "SupplyItem")
        if line["status"] != "SHORT":
            raise ApiError(E.ERR_LINE_NOT_SHORT,
                           "Pick line is not SHORT", 409)
        pl = db.pick_lists.get(line["pick_list_id"])
        if pl is None or pl["status"] not in ("IN_PICKING", "PICKING_EXCEPTION"):
            raise ApiError(E.ERR_PICK_LIST_INVALID_STATE,
                           "Pick list is not IN_PICKING or PICKING_EXCEPTION",
                           409)
        # Clinical safety, in scaffold precondition order
        if substitute_id == line["supply_item_id"]:
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Substitute must differ from the planned item", 400)
        if sub["status"] != "ACTIVE":
            raise ApiError(E.ERR_ITEM_NOT_ACTIVE,
                           "Substitute item is not ACTIVE", 409)
        planned = db.supply_items.get(line["supply_item_id"])
        planned_group = planned["substitute_group"] if planned else None
        if (sub["substitute_group"] is None or planned_group is None
                or sub["substitute_group"] != planned_group):
            raise ApiError(E.ERR_SUBSTITUTE_GROUP_MISMATCH,
                           "Substitute is not in the planned item's "
                           "substitute group", 409)
        if sub["on_hand_quantity"] < line["qty_requested"]:
            raise ApiError(E.ERR_INSUFFICIENT_STOCK,
                           "Insufficient stock of the substitute item", 409)
        # Fiscal guard: 1.25x threshold (exact 1.25x allowed); integer-exact
        if not override and 4 * sub["unit_cost_cents"] > 5 * line["unit_cost_cents"]:
            raise ApiError(E.ERR_SUBSTITUTE_PRICE_THRESHOLD,
                           "Substitute exceeds 1.25x the planned line's unit "
                           "cost", 402)
        line["qty_picked"] = line["qty_requested"]
        line["unit_cost_cents"] = sub["unit_cost_cents"]
        line["substituted_item_id"] = sub["id"]
        line["status"] = "SUBSTITUTED"
        D.bump(line)
        sub["on_hand_quantity"] -= line["qty_requested"]
        D.bump(sub)
        # List transitions: clear of SHORT -> back to IN_PICKING; if also
        # clear of PENDING -> continue into STAGED.
        lines = D.lines_of_pick_list(pl["id"])
        shorts = [l for l in lines if l["status"] == "SHORT"]
        pendings = [l for l in lines if l["status"] == "PENDING"]
        if not shorts and pl["status"] == "PICKING_EXCEPTION":
            pl["status"] = "IN_PICKING"
            D.bump(pl)
        if not shorts and not pendings and pl["status"] == "IN_PICKING":
            pl["status"] = "STAGED"
            D.bump(pl)
        return U.success_object(D.ser_pick_list_line(line), 200)
