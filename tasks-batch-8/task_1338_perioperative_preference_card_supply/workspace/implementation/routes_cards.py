"""Routes: preference cards and preference card lines."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

SCA = "SupplyChainAnalyst"


def register_routes(app):

    # -------------------------------------------------------- preference cards
    @app.route("/perioperative/preference-cards", methods=["POST"])
    def create_card():
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        surgeon_id = U.req_str(body, "surgeon_id")
        procedure_name = U.req_str(body, "procedure_name")
        surgeon = D.get_or_404(db.surgeons, surgeon_id, "Surgeon")
        if surgeon["status"] != "ACTIVE":
            raise ApiError(E.ERR_SURGEON_INACTIVE,
                           "Surgeon is INACTIVE", 409)
        existing = [c["version_number"] for c in db.preference_cards.values()
                    if c["surgeon_id"] == surgeon_id
                    and c["procedure_name"] == procedure_name]
        version_number = (max(existing) + 1) if existing else 1
        card = {
            "surgeon_id": surgeon_id,
            "procedure_name": procedure_name,
            "version_number": version_number,
            "status": "DRAFT",
            "estimated_cost_cents": 0,
            "flagged_audit_count": 0,
            "rolling_line_match_pct": None,
            "_lines_created": 0,
        }
        D.stamp_new(card)
        db.preference_cards[card["id"]] = card
        return U.success_object(D.ser_card(card), 201)

    @app.route("/perioperative/preference-cards", methods=["GET"])
    def list_cards():
        U.authenticate()
        limit, offset = U.pagination_params()
        cards = U.apply_filters(list(db.preference_cards.values()), [
            ("surgeon_id", "surgeon_id"),
            ("procedure_name", "procedure_name"),
            ("status", "status"),
        ])
        page, total = U.paginate(cards, limit, offset)
        return U.success_list([D.ser_card(c) for c in page],
                              total, limit, offset)

    @app.route("/perioperative/preference-cards/<cid>", methods=["GET"])
    def get_card(cid):
        U.authenticate()
        card = D.get_or_404(db.preference_cards, cid, "PreferenceCard")
        return U.success_object(D.ser_card(card), 200)

    @app.route("/perioperative/preference-cards/<cid>/publish", methods=["POST"])
    def publish_card(cid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        expected_card_version = U.req_int(body, "expected_card_version")
        card = D.get_or_404(db.preference_cards, cid, "PreferenceCard")
        # State precondition
        if card["status"] != "DRAFT":
            raise ApiError(E.ERR_CARD_NOT_DRAFT,
                           "Card is not DRAFT", 409)
        # OCC: after state, before business rules (PRD section 2.6)
        if expected_card_version != card["version"]:
            raise ApiError(E.ERR_STALE_VERSION,
                           "expected_card_version does not match the card's "
                           "current version", 412)
        # Business rules, in the order PRD section 3.2 pins for publish
        lines = D.lines_of_card(card["id"])
        if not lines:
            raise ApiError(E.ERR_CARD_EMPTY,
                           "Card has no lines", 409)
        for line in lines:
            item = db.supply_items.get(line["supply_item_id"])
            if item is None or item["status"] != "ACTIVE":
                raise ApiError(E.ERR_ITEM_NOT_ACTIVE,
                               "A card line references a non-ACTIVE item", 409)
        surgeon = db.surgeons.get(card["surgeon_id"])
        if surgeon is None or surgeon["status"] != "ACTIVE":
            raise ApiError(E.ERR_SURGEON_INACTIVE,
                           "Card's surgeon is INACTIVE", 409)
        # Commit: supersede any other ACTIVE card of the same pair
        for other in db.preference_cards.values():
            if (other["id"] != card["id"] and other["status"] == "ACTIVE"
                    and other["surgeon_id"] == card["surgeon_id"]
                    and other["procedure_name"] == card["procedure_name"]):
                other["status"] = "SUPERSEDED"
                D.bump(other)
        card["status"] = "ACTIVE"
        D.bump(card)
        return U.success_object(D.ser_card(card), 200)

    @app.route("/perioperative/preference-cards/<cid>/retire", methods=["POST"])
    def retire_card(cid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        card = D.get_or_404(db.preference_cards, cid, "PreferenceCard")
        if card["status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError(E.ERR_INVALID_STATE,
                           "Card cannot be retired from its current state", 409)
        if card["status"] == "ACTIVE":
            in_flight = any(
                c["card_id"] == card["id"]
                and c["status"] in ("SCHEDULED", "PICKING_RELEASED", "IN_PROGRESS")
                for c in db.cases.values()
            )
            if in_flight:
                raise ApiError(E.ERR_CARD_IN_USE,
                               "An in-flight case is pinned to this card", 409)
        card["status"] = "RETIRED"
        D.bump(card)
        return U.success_object(D.ser_card(card), 200)

    # -------------------------------------------------- preference card lines
    @app.route("/perioperative/preference-card-lines", methods=["POST"])
    def create_card_line():
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        card_id = U.req_str(body, "card_id")
        supply_item_id = U.req_str(body, "supply_item_id")
        quantity = U.req_int(body, "quantity")
        if quantity < 1:
            raise ApiError(E.ERR_INVALID_QUANTITY,
                           "Field 'quantity' must be >= 1", 400)
        designation = U.req_enum(body, "designation", {"OPEN", "HOLD"})
        pick_sequence = U.opt_int(body, "pick_sequence")
        notes = U.opt_str(body, "notes")
        card = D.get_or_404(db.preference_cards, card_id, "PreferenceCard")
        item = D.get_or_404(db.supply_items, supply_item_id, "SupplyItem")
        if card["status"] != "DRAFT":
            raise ApiError(E.ERR_CARD_NOT_DRAFT,
                           "Card is not DRAFT", 409)
        if item["status"] != "ACTIVE":
            raise ApiError(E.ERR_ITEM_NOT_ACTIVE,
                           "Supply item is not ACTIVE", 409)
        if any(l["card_id"] == card_id and l["supply_item_id"] == supply_item_id
               for l in db.card_lines.values()):
            raise ApiError(E.ERR_DUPLICATE_CARD_LINE,
                           "A line for this item already exists on the card",
                           409)
        card["_lines_created"] = card.get("_lines_created", 0) + 1
        if pick_sequence is None:
            pick_sequence = card["_lines_created"]
        line = {
            "card_id": card_id,
            "supply_item_id": supply_item_id,
            "quantity": quantity,
            "designation": designation,
            "pick_sequence": pick_sequence,
            "notes": notes,
        }
        D.stamp_new(line)
        db.card_lines[line["id"]] = line
        D.recompute_card_estimated_cost(card)
        D.bump(card)
        return U.success_object(D.ser_card_line(line), 201)

    @app.route("/perioperative/preference-card-lines", methods=["GET"])
    def list_card_lines():
        U.authenticate()
        limit, offset = U.pagination_params()
        lines = U.apply_filters(list(db.card_lines.values()), [
            ("card_id", "card_id"),
            ("supply_item_id", "supply_item_id"),
        ])
        page, total = U.paginate(
            lines, limit, offset,
            sort_key=lambda l: (l["pick_sequence"], l["created_at"], l["_seq"]),
        )
        return U.success_list([D.ser_card_line(l) for l in page],
                              total, limit, offset)

    @app.route("/perioperative/preference-card-lines/<lid>", methods=["GET"])
    def get_card_line(lid):
        U.authenticate()
        line = D.get_or_404(db.card_lines, lid, "PreferenceCardLine")
        return U.success_object(D.ser_card_line(line), 200)

    @app.route("/perioperative/preference-card-lines/<lid>", methods=["DELETE"])
    def delete_card_line(lid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        line = D.get_or_404(db.card_lines, lid, "PreferenceCardLine")
        card = db.preference_cards.get(line["card_id"])
        if card is None or card["status"] != "DRAFT":
            raise ApiError(E.ERR_CARD_NOT_DRAFT,
                           "Card is not DRAFT", 409)
        del db.card_lines[lid]
        D.recompute_card_estimated_cost(card)
        D.bump(card)
        return "", 204
