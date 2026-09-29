"""Common elements, vendor contracts and maintenance work orders (PRD 3.6)."""
from datetime import timedelta

from flask import request

import clock
import db
import money
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import contracts

ELEMENT_CLASSES = ("ROOF", "ELEVATOR", "FACADE", "POOL", "GARAGE", "LIFE_SAFETY",
                   "LANDSCAPE")
LIFE_SAFETY_CLASSES = ("ELEVATOR", "LIFE_SAFETY")
ELEMENT_STATUSES = ("SERVICEABLE", "IMPAIRED", "OUT_OF_SERVICE", "DECOMMISSIONED")
ELEMENT_PATCHABLE = ("replacement_cost_cents", "useful_life_years",
                     "effective_age_years", "status", "reserve_designated_cents")
BLOCKING_CLAIM_STATUSES = ("UNDER_REVIEW", "ADJUSTED_ASSOCIATION", "ADJUSTED_SPLIT")


def element_of(contract):
    return db.get("common_elements", contract["covered_element_id"])


def set_element_status(element, status):
    element["status"] = status
    db.touch(element)


def register(app):

    # -------------------------------------------------------- common elements

    @app.post("/associations/<association_id>/common-elements")
    def create_common_element(association_id):
        authenticate(("CommunityManager",))
        V.resolve_path(association_id=association_id)
        body = V.body_of()
        name = V.require_str(body, "name", min_len=1)
        element_class = V.require_enum(body, "element_class", ELEMENT_CLASSES)
        replacement_cost = V.require_int(body, "replacement_cost_cents", minimum=0)
        useful_life = V.require_int(body, "useful_life_years", minimum=1)
        effective_age = V.require_int(body, "effective_age_years", minimum=0)

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "name": name,
            "element_class": element_class,
            "is_life_safety": element_class in LIFE_SAFETY_CLASSES,
            "status": "SERVICEABLE",
            "replacement_cost_cents": replacement_cost,
            "useful_life_years": useful_life,
            "effective_age_years": effective_age,
            "reserve_designated_cents": 0,
            "last_serviced_at": None,
        })
        db.insert("common_elements", row)
        return response.created(serialize.view(row))

    @app.get("/common-elements")
    def list_common_elements():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "TitleAgent"))
        limit, offset = V.pagination()
        args = request.args
        element_class = args.get("element_class")
        if element_class is not None and element_class not in ELEMENT_CLASSES:
            V.fail("Query parameter 'element_class' is not recognized.")
        status = args.get("status")
        if status is not None and status not in ELEMENT_STATUSES:
            V.fail("Query parameter 'status' is not recognized.")

        def keep(c):
            want = args.get("association_id")
            if want and c["association_id"] != want:
                return False
            if element_class and c["element_class"] != element_class:
                return False
            if status and c["status"] != status:
                return False
            return True

        rows = db.sorted_rows("common_elements", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.patch("/common-elements/<common_element_id>")
    def patch_common_element(common_element_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(common_element_id=common_element_id)
        element = found["common_element_id"]
        body = V.body_of()
        for key in body:
            if key not in ELEMENT_PATCHABLE:
                V.fail("Field '%s' may not be revised." % key)
        if "replacement_cost_cents" in body:
            element["replacement_cost_cents"] = V.require_int(
                body, "replacement_cost_cents", minimum=0)
        if "useful_life_years" in body:
            element["useful_life_years"] = V.require_int(body, "useful_life_years",
                                                         minimum=1)
        if "effective_age_years" in body:
            element["effective_age_years"] = V.require_int(body, "effective_age_years",
                                                           minimum=0)
        if "reserve_designated_cents" in body:
            element["reserve_designated_cents"] = V.require_int(
                body, "reserve_designated_cents", minimum=0)
        if "status" in body:
            element["status"] = V.require_enum(body, "status", ELEMENT_STATUSES)
        db.touch(element)
        return response.ok(serialize.view(element))

    # -------------------------------------------------------- vendor contracts

    @app.post("/associations/<association_id>/vendor-contracts")
    def create_vendor_contract(association_id):
        authenticate(("CommunityManager",))
        V.resolve_path(association_id=association_id)
        body = V.body_of()
        element_id = body.get("covered_element_id")
        element = db.get("common_elements", element_id) if element_id else None
        if element_id is not None and element is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        if element is None:
            V.fail("Field 'covered_element_id' is required.")
        vendor_name = V.require_str(body, "vendor_name", min_len=1)
        cap = V.require_int(body, "contract_cap_cents", minimum=1)
        insurance_cert_expires_at = V.require_dt(body, "insurance_cert_expires_at")
        effective_from = V.require_dt(body, "effective_from")
        effective_to = V.require_dt(body, "effective_to")
        V.scope_match(association_id, element)

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "covered_element_id": element["id"],
            "vendor_name": vendor_name,
            "contract_cap_cents": cap,
            "committed_cents": 0,
            "invoiced_cents": 0,
            "insurance_cert_expires_at": insurance_cert_expires_at,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
            "approval_yes_count": 0,
            "pinned_element_version": None,
            "suspension_reason": "NONE",
        })
        db.insert("vendor_contracts", row)
        return response.created(serialize.view(row))

    @app.get("/vendor-contracts")
    def list_vendor_contracts():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in contracts.CONTRACT_STATUSES:
            V.fail("Query parameter 'status' is not recognized.")

        def keep(c):
            for name in ("association_id", "covered_element_id"):
                want = args.get(name)
                if want and c.get(name) != want:
                    return False
            if status and c["status"] != status:
                return False
            return True

        rows = db.sorted_rows("vendor_contracts", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.patch("/vendor-contracts/<vendor_contract_id>/insurance-certificate")
    def renew_insurance_certificate(vendor_contract_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        body = V.body_of()
        contract["insurance_cert_expires_at"] = V.require_dt(
            body, "insurance_cert_expires_at")
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/submit")
    def submit_vendor_contract(vendor_contract_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        V.body_of()
        # Rung 12.
        if contract["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        element = element_of(contract)
        # Rung 18 precedes rung 55 in the ladder.
        if element is None or element["status"] == "DECOMMISSIONED":
            raise ApiError("ERR_ELEMENT_NOT_SERVICEABLE")
        # Rung 55.
        if not contract["effective_from"] < contract["effective_to"]:
            raise ApiError("ERR_CONTRACT_TERM_INVALID")
        if contract["insurance_cert_expires_at"] < contract["effective_to"]:
            raise ApiError("ERR_CONTRACT_TERM_INVALID")

        contract["status"] = "PENDING_APPROVAL"
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/approve")
    def approve_vendor_contract(vendor_contract_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        assoc = db.get("associations", contract["association_id"])
        V.body_of()
        # Rung 12.
        if contract["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        element = element_of(contract)
        # Rung 18.
        if element is None or element["status"] not in ("SERVICEABLE", "IMPAIRED"):
            raise ApiError("ERR_ELEMENT_NOT_SERVICEABLE")

        # Counted board votes cast at a CONTRACT_AWARD meeting that is in session or
        # already adjourned.
        yes_count = 0
        for v in db.store["votes"].values():
            if v["subject_type"] != "VENDOR_CONTRACT" or v["subject_id"] != contract["id"]:
                continue
            if not v["counted"] or v["choice"] != "YES":
                continue
            meeting = db.get("board_meetings", v.get("meeting_id"))
            if meeting is None:
                continue
            if "CONTRACT_AWARD" not in (meeting["agenda_kinds"] or []):
                continue
            if meeting["status"] not in ("IN_SESSION", "ADJOURNED"):
                continue
            yes_count += 1
        # Rung 33.
        if yes_count < assoc["board_quorum_seats"]:
            raise ApiError("ERR_AGENDA_KIND_MISSING")

        contract["approval_yes_count"] = yes_count
        contract["pinned_element_version"] = element["version"]
        contract["status"] = "APPROVED"
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/activate")
    def activate_vendor_contract(vendor_contract_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        V.body_of()
        now = clock.now()
        # Rung 12.
        if contract["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        if not (contract["effective_from"] <= now < contract["effective_to"]):
            raise ApiError("ERR_INVALID_CONTRACT_STATE",
                           "The logical clock is outside the contract term.")
        # Rung 16.
        if not contract["insurance_cert_expires_at"] > now:
            raise ApiError("ERR_VENDOR_INSURANCE_LAPSED")
        element = element_of(contract)
        # Rung 20.
        if element is None or element["version"] != contract["pinned_element_version"]:
            raise ApiError("ERR_ELEMENT_SPEC_CHANGED")

        contract["status"] = "ACTIVE"
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/suspend")
    def suspend_vendor_contract(vendor_contract_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        body = V.body_of()
        reason = V.require_enum(body, "suspension_reason",
                                contracts.SUSPENSION_REASONS)
        # Rung 12.
        if contract["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")

        contract["status"] = "SUSPENDED"
        contract["suspension_reason"] = reason
        contracts.hold_open_orders(contract, "CONTRACT_SUSPENDED")
        contracts.recompute_committed(contract)
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/reinstate")
    def reinstate_vendor_contract(vendor_contract_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        V.body_of()
        now = clock.now()
        # Rung 12.
        if contract["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        # Rung 16.
        if not contract["insurance_cert_expires_at"] > now:
            raise ApiError("ERR_VENDOR_INSURANCE_LAPSED")
        if not now < contract["effective_to"]:
            raise ApiError("ERR_INVALID_CONTRACT_STATE",
                           "The contract term has already ended.")
        element = element_of(contract)
        # Rung 20.
        if element is None or element["version"] != contract["pinned_element_version"]:
            raise ApiError("ERR_ELEMENT_SPEC_CHANGED")

        contract["status"] = "ACTIVE"
        contract["suspension_reason"] = "NONE"
        for order in contracts.orders_of(contract["id"]):
            if (order["status"] == "ON_HOLD"
                    and order["hold_reason"] == "CONTRACT_SUSPENDED"):
                order["status"] = "SCHEDULED"
                order["hold_reason"] = "NONE"
                db.touch(order)
        contracts.recompute_committed(contract)
        db.touch(contract)
        return response.ok(serialize.view(contract))

    @app.post("/vendor-contracts/<vendor_contract_id>/terminate")
    def terminate_vendor_contract(vendor_contract_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(vendor_contract_id=vendor_contract_id)
        contract = found["vendor_contract_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if contract["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        # Rung 52 -- only the ACTIVE leg is guarded.
        if contract["status"] == "ACTIVE":
            for order in contracts.orders_of(contract["id"]):
                if order["status"] == "IN_PROGRESS":
                    raise ApiError("ERR_WORK_IN_PROGRESS")

        contract["status"] = "TERMINATED"
        contracts.cancel_open_orders(contract, ("SCHEDULED", "ON_HOLD"))
        contracts.recompute_committed(contract)
        db.touch(contract)
        return response.ok(serialize.view(contract))

    # ------------------------------------------------------------ work orders

    @app.post("/work-orders")
    def create_work_order():
        authenticate(("CommunityManager",))
        body = V.body_of()
        fk = V.resolve_body_fk(body, "contract_id", "element_id", "claim_id")
        contract = fk["contract_id"]
        element = fk["element_id"]
        claim = fk["claim_id"]
        if contract is None:
            V.fail("Field 'contract_id' is required.")
        if element is None:
            V.fail("Field 'element_id' is required.")
        scope = V.require_str(body, "scope", min_len=1)
        window_start = V.require_dt(body, "window_start")
        window_end = V.require_dt(body, "window_end")
        estimated = V.require_int(body, "estimated_cost_cents", minimum=0)
        is_emergency = V.require_bool(body, "is_emergency", default=False)
        V.require_int(body, "expected_contract_version", minimum=0)
        association_id = contract["association_id"]
        # Rung 8.
        V.scope_match(association_id, element, claim)
        # Rung 9.
        V.occ(body, "expected_contract_version", contract, "ERR_STALE_CONTRACT_VERSION")
        # Rung 19.
        if element["id"] != contract["covered_element_id"]:
            raise ApiError("ERR_ELEMENT_CONTRACT_MISMATCH")
        # Rung 28.
        if not (window_start < window_end
                and contract["effective_from"] <= window_start
                and window_end < contract["effective_to"]):
            raise ApiError("ERR_WINDOW_OUTSIDE_CONTRACT_TERM")
        # Rung 29 -- the buffered closed-interval collision test.
        assoc = db.get("associations", association_id)
        buffer = timedelta(hours=assoc["element_window_buffer_hours"])
        for other in db.sorted_rows(
                "work_orders",
                lambda w: w["element_id"] == element["id"]
                and w["status"] in ("SCHEDULED", "IN_PROGRESS", "ON_HOLD")):
            if (window_start <= other["window_end"] + buffer
                    and window_end >= other["window_start"] - buffer):
                raise ApiError("ERR_ELEMENT_WINDOW_CONFLICT")
        # Rung 44 -- equality is admitted.
        if (estimated + contract["committed_cents"] + contract["invoiced_cents"]
                > contract["contract_cap_cents"]):
            raise ApiError("ERR_CONTRACT_CAP_EXCEEDED")

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "contract_id": contract["id"],
            "element_id": element["id"],
            "claim_id": claim["id"] if claim else None,
            "scope": scope,
            "window_start": window_start,
            "window_end": window_end,
            "estimated_cost_cents": estimated,
            "final_cost_cents": None,
            "encumbered_cents": estimated,
            "is_emergency": bool(is_emergency),
            "hold_reason": "NONE",
            "status": "SCHEDULED",
        })
        db.insert("work_orders", row)
        contracts.recompute_committed(contract)
        db.touch(contract)
        return response.created(serialize.view(row))

    @app.get("/work-orders")
    def list_work_orders():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in contracts.ORDER_STATUSES:
            V.fail("Query parameter 'status' is not recognized.")

        def keep(w):
            for name in ("association_id", "contract_id", "element_id", "claim_id"):
                want = args.get(name)
                if want and w.get(name) != want:
                    return False
            if status and w["status"] != status:
                return False
            return True

        rows = db.sorted_rows("work_orders", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/work-orders/<work_order_id>/start")
    def start_work_order(work_order_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(work_order_id=work_order_id)
        order = found["work_order_id"]
        V.body_of()
        contract = db.get("vendor_contracts", order["contract_id"])
        element = db.get("common_elements", order["element_id"])
        # Rung 12.
        if order["status"] not in ("SCHEDULED", "ON_HOLD"):
            raise ApiError("ERR_INVALID_WORK_ORDER_STATE")
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_CONTRACT_STATE")
        from_scheduled = order["status"] == "SCHEDULED"
        # Rung 16 -- only the SCHEDULED leg checks the certificate against window_end.
        if from_scheduled and not (
                contract["insurance_cert_expires_at"] > order["window_end"]):
            raise ApiError("ERR_VENDOR_INSURANCE_LAPSED")
        # Rung 18.
        if element is None or element["status"] == "DECOMMISSIONED":
            raise ApiError("ERR_ELEMENT_NOT_SERVICEABLE")
        # Rung 53 -- only the SCHEDULED leg.
        if from_scheduled and clock.now() < order["window_start"]:
            raise ApiError("ERR_WINDOW_NOT_STARTED")

        order["status"] = "IN_PROGRESS"
        order["hold_reason"] = "NONE"
        set_element_status(element,
                          "OUT_OF_SERVICE" if element["is_life_safety"] else "IMPAIRED")
        db.touch(order)
        return response.ok(serialize.view(order))

    @app.post("/work-orders/<work_order_id>/hold")
    def hold_work_order(work_order_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(work_order_id=work_order_id)
        order = found["work_order_id"]
        body = V.body_of()
        reason = V.require_enum(body, "hold_reason", contracts.HOLD_REASONS)
        # Rung 12.
        if order["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_WORK_ORDER_STATE")

        order["status"] = "ON_HOLD"
        order["hold_reason"] = reason
        element = db.get("common_elements", order["element_id"])
        if element is not None:
            set_element_status(element, "IMPAIRED")
        db.touch(order)
        return response.ok(serialize.view(order))

    @app.post("/work-orders/<work_order_id>/complete")
    def complete_work_order(work_order_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(work_order_id=work_order_id)
        order = found["work_order_id"]
        body = V.body_of()
        resets_component = V.require_bool(body, "resets_component", default=False)
        # Rung 12.
        if order["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_WORK_ORDER_STATE")
        # Rung 53.
        if clock.now() < order["window_start"]:
            raise ApiError("ERR_WINDOW_NOT_STARTED")

        order["status"] = "COMPLETED"
        element = db.get("common_elements", order["element_id"])
        if element is not None:
            element["status"] = "SERVICEABLE"
            element["last_serviced_at"] = clock.now()
            if resets_component:
                element["effective_age_years"] = 0
            db.touch(element)
        db.touch(order)
        return response.ok(serialize.view(order))

    @app.post("/work-orders/<work_order_id>/invoice")
    def invoice_work_order(work_order_id):
        authenticate(("CommunityManager", "BoardTreasurer"))
        found = V.resolve_path(work_order_id=work_order_id)
        order = found["work_order_id"]
        body = V.body_of()
        final_cost = V.require_int(body, "final_cost_cents", minimum=0)
        contract = db.get("vendor_contracts", order["contract_id"])
        assoc = db.get("associations", order["association_id"])
        # Rung 12.
        if order["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_WORK_ORDER_STATE")
        # Rung 45 -- a ten percent overrun, inclusive of the boundary.
        tolerance = money.floor_div(order["estimated_cost_cents"] * 11, 10)
        if final_cost > tolerance:
            raise ApiError("ERR_INVOICE_EXCEEDS_TOLERANCE")
        if contract["invoiced_cents"] + final_cost > contract["contract_cap_cents"]:
            raise ApiError("ERR_INVOICE_EXCEEDS_TOLERANCE")
        # Rung 46.
        if assoc["operating_cash_cents"] < final_cost:
            raise ApiError("ERR_INSUFFICIENT_OPERATING_CASH")

        order["final_cost_cents"] = final_cost
        order["encumbered_cents"] = 0
        order["status"] = "INVOICED"
        contracts.recompute_committed(contract)
        db.touch(contract)
        assoc["operating_cash_cents"] -= final_cost
        db.touch(assoc)
        db.touch(order)
        return response.ok(serialize.view(order))

    @app.post("/work-orders/<work_order_id>/cancel")
    def cancel_work_order(work_order_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(work_order_id=work_order_id)
        order = found["work_order_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if order["status"] not in ("SCHEDULED", "ON_HOLD"):
            raise ApiError("ERR_INVALID_WORK_ORDER_STATE")
        from_scheduled = order["status"] == "SCHEDULED"

        order["status"] = "CANCELLED"
        order["encumbered_cents"] = 0
        if from_scheduled:
            order["hold_reason"] = "NONE"
        contract = db.get("vendor_contracts", order["contract_id"])
        if contract is not None:
            contracts.recompute_committed(contract)
            db.touch(contract)
        if from_scheduled:
            element = db.get("common_elements", order["element_id"])
            if element is not None and element_free(element):
                set_element_status(element, "SERVICEABLE")
        db.touch(order)
        return response.ok(serialize.view(order))


def element_free(element):
    """True when nothing else keeps the element out of service."""
    for w in db.store["work_orders"].values():
        if w["element_id"] == element["id"] and w["status"] in ("IN_PROGRESS",
                                                                "ON_HOLD"):
            return False
    for c in db.store["insurance_claims"].values():
        if (c.get("element_id") == element["id"]
                and c["adjustment_status"] in BLOCKING_CLAIM_STATUSES):
            return False
    return True
