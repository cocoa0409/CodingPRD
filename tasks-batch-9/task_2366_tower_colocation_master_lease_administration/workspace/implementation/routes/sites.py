"""Towers, landlords, ground leases, landlord remittances and the logical clock."""
from decimal import Decimal

import calc
import find
import serializers
import services
from db import bump, db, new_immutable_record, new_record, sorted_records
from errors import ApiError
from middleware import (
    ALL_ROLES,
    Body,
    auth,
    paginate,
    pagination,
    query_enum,
    query_value,
    require_landlord_scope,
    resolve_identity,
)
from response import array_response, object_response
from util import (
    add_days,
    add_years,
    dec,
    is_first_of_month,
    is_last_of_month,
    iso,
    month_starts_within,
)

STRUCTURE_TYPES = ("MONOPOLE", "SELF_SUPPORT", "GUYED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
LEASE_STATUSES = ("ACTIVE", "RENEWAL_NEGOTIATION", "EXPIRED", "BOUGHT_OUT")


def _date_text(value):
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def register(app):

    # -----------------------------------------------------------------------
    # Towers
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/towers", methods=["POST"])
    def create_tower():
        auth("PortfolioAdmin")
        body = Body()
        site_name = body.string("site_name", max_len=120)
        structure_type = body.enum("structure_type", STRUCTURE_TYPES)
        rated = body.number("rated_capacity_load_units", exclusive_min=0)
        min_elev = body.number("min_colocation_elevation_ft", minimum=0)
        max_elev = body.number("max_elevation_ft", exclusive_min=min_elev)
        ground_total = body.number("ground_space_total_sqft", exclusive_min=0)
        baseline_load = body.number("baseline_reserved_load_units", required=False,
                                    minimum=0, default=Decimal(0))
        if baseline_load >= rated:
            raise ApiError("ERR_INVALID_REQUEST",
                           "baseline_reserved_load_units must be < rated_capacity_load_units.")
        baseline_ground = body.number("baseline_reserved_ground_sqft", required=False,
                                      minimum=0, default=Decimal(0))
        if baseline_ground >= ground_total:
            raise ApiError("ERR_INVALID_REQUEST",
                           "baseline_reserved_ground_sqft must be < ground_space_total_sqft.")
        record = new_record(
            site_name=site_name,
            structure_type=structure_type,
            rated_capacity_load_units=rated,
            min_colocation_elevation_ft=min_elev,
            max_elevation_ft=max_elev,
            ground_space_total_sqft=ground_total,
            baseline_reserved_load_units=baseline_load,
            baseline_reserved_ground_sqft=baseline_ground,
        )
        db.towers[record["id"]] = record
        return object_response(serializers.tower(record), 201)

    @app.route("/tower-colo/towers", methods=["GET"])
    def list_towers():
        user_id, role = auth(*ALL_ROLES)
        posture = query_enum("capacity_posture", POSTURES)
        structure_type = query_enum("structure_type", STRUCTURE_TYPES)
        limit, offset = pagination()
        resolve_identity(user_id, role)
        items = sorted_records(db.towers.values())
        if structure_type is not None:
            items = [t for t in items if t["structure_type"] == structure_type]
        if posture is not None:
            items = [t for t in items if services.tower_capacity_posture(t) == posture]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.tower(t) for t in page], meta)

    @app.route("/tower-colo/towers/<tower_id>", methods=["GET"])
    def read_tower(tower_id):
        user_id, role = auth(*ALL_ROLES)
        tower = find.tower(tower_id)
        resolve_identity(user_id, role)
        return object_response(serializers.tower(tower))

    @app.route("/tower-colo/towers/<tower_id>/capacity-summary", methods=["GET"])
    def tower_capacity_summary(tower_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer",
                             "ComplianceAuditor", "Tenant")
        tower = find.tower(tower_id)
        resolve_identity(user_id, role)
        return object_response(serializers.capacity_summary(tower))

    # -----------------------------------------------------------------------
    # Landlords
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/landlords", methods=["POST"])
    def create_landlord():
        auth("PortfolioAdmin")
        body = Body()
        legal_name = body.string("legal_name", max_len=160)
        email = body.string("remit_contact_email", max_len=320)
        if "@" not in email:
            raise ApiError("ERR_INVALID_REQUEST",
                           "remit_contact_email must contain '@'.")
        w9 = body.boolean("w9_on_file", required=False, default=False)
        record = new_record(legal_name=legal_name, remit_contact_email=email, w9_on_file=w9)
        db.landlords[record["id"]] = record
        return object_response(serializers.landlord(record), 201)

    # -----------------------------------------------------------------------
    # Ground leases
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/ground-leases", methods=["POST"])
    def create_ground_lease():
        auth("PortfolioAdmin")
        body = Body()
        tower_id = body.ident("tower_id")
        landlord_id = body.ident("landlord_id")
        base_rent = body.integer("base_monthly_rent_cents", exclusive_min=0)
        escalator = body.number("escalator_pct", minimum=0, maximum=25)
        commencement = body.moment("commencement_date")
        term_end = body.moment("term_end_date")
        if term_end <= commencement:
            raise ApiError("ERR_INVALID_REQUEST",
                           "term_end_date must be after commencement_date.")
        option_count = body.integer("renewal_option_count", minimum=0)
        term_years = body.integer("renewal_term_years", minimum=1)
        buyout_price = body.integer("buyout_price_cents", minimum=0)

        tower = find.tower(tower_id)
        find.landlord(landlord_id)

        record = new_record(
            tower_id=tower_id,
            landlord_id=landlord_id,
            base_monthly_rent_cents=base_rent,
            escalator_pct=escalator,
            commencement_date=commencement,
            term_end_date=term_end,
            renewal_option_count=option_count,
            renewal_term_years=term_years,
            buyout_price_cents=buyout_price,
            status="ACTIVE",
            renewals_exercised=0,
            paid_through_date=None,
            buyout_paid_cents=0,
            _date_raw=body.raw_dates(),
        )
        db.ground_leases[record["id"]] = record
        bump(tower)
        return object_response(serializers.ground_lease(record), 201)

    @app.route("/tower-colo/ground-leases", methods=["GET"])
    def list_ground_leases():
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Landlord")
        status = query_enum("status", LEASE_STATUSES)
        tower_id = query_value("tower_id")
        landlord_id = query_value("landlord_id")
        limit, offset = pagination()
        resolve_identity(user_id, role)
        if role == "Landlord":
            if landlord_id is not None and landlord_id != user_id:
                raise ApiError("ERR_LANDLORD_SCOPE_VIOLATION",
                               "Landlord may list only its own ground leases.")
            landlord_id = user_id
        items = sorted_records(db.ground_leases.values())
        if tower_id is not None:
            items = [g for g in items if g["tower_id"] == tower_id]
        if landlord_id is not None:
            items = [g for g in items if g["landlord_id"] == landlord_id]
        if status is not None:
            items = [g for g in items if g["status"] == status]
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.ground_lease(g) for g in page], meta)

    @app.route("/tower-colo/ground-leases/<lease_id>", methods=["GET"])
    def read_ground_lease(lease_id):
        user_id, role = auth("PortfolioAdmin", "StructuralEngineer", "Landlord")
        lease = find.ground_lease(lease_id)
        resolve_identity(user_id, role)
        return object_response(serializers.ground_lease(lease))

    @app.route("/tower-colo/ground-leases/<lease_id>/open-renewal", methods=["POST"])
    def open_renewal(lease_id):
        auth("PortfolioAdmin")
        Body()
        lease = find.ground_lease(lease_id)
        if lease["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_LEASE_STATE",
                           "Renewal may only be opened on an ACTIVE ground lease.")
        if not services.renewal_window_open(lease):
            raise ApiError("ERR_RENEWAL_WINDOW_CLOSED",
                           "The renewal window has not opened yet.")
        if lease["renewals_exercised"] >= lease["renewal_option_count"]:
            raise ApiError("ERR_NO_RENEWAL_OPTIONS_REMAINING",
                           "No renewal option remains on this lease.")
        lease["status"] = "RENEWAL_NEGOTIATION"
        bump(lease)
        return object_response(serializers.ground_lease(lease))

    @app.route("/tower-colo/ground-leases/<lease_id>/renew", methods=["POST"])
    def renew_ground_lease(lease_id):
        auth("PortfolioAdmin")
        Body()
        lease = find.ground_lease(lease_id)
        if lease["status"] != "RENEWAL_NEGOTIATION":
            raise ApiError("ERR_INVALID_LEASE_STATE",
                           "Only a lease in RENEWAL_NEGOTIATION may be renewed.")
        if lease["renewals_exercised"] >= lease["renewal_option_count"]:
            raise ApiError("ERR_NO_RENEWAL_OPTIONS_REMAINING",
                           "No renewal option remains on this lease.")
        old_end = lease["term_end_date"]
        lease["base_monthly_rent_cents"] = calc.ground_lease_rent_at(
            lease["base_monthly_rent_cents"], lease["escalator_pct"],
            lease["commencement_date"], old_end)
        new_commencement = add_days(old_end, 1)
        new_end = add_years(old_end, int(lease["renewal_term_years"]))
        lease["commencement_date"] = new_commencement
        lease["term_end_date"] = new_end
        raws = dict(lease.get("_date_raw", {}))
        raws["commencement_date"] = _date_text(new_commencement)
        raws["term_end_date"] = _date_text(new_end)
        lease["_date_raw"] = raws
        lease["renewals_exercised"] += 1
        lease["status"] = "ACTIVE"
        bump(lease)
        bump(find.tower(lease["tower_id"]))
        return object_response(serializers.ground_lease(lease))

    @app.route("/tower-colo/ground-leases/<lease_id>/buyout", methods=["POST"])
    def buyout_ground_lease(lease_id):
        auth("PortfolioAdmin")
        Body()
        lease = find.ground_lease(lease_id)
        if lease["status"] not in ("ACTIVE", "RENEWAL_NEGOTIATION"):
            raise ApiError("ERR_INVALID_LEASE_STATE",
                           "Only an ACTIVE or RENEWAL_NEGOTIATION lease may be bought out.")
        if lease["buyout_price_cents"] <= 0:
            raise ApiError("ERR_BUYOUT_NOT_AVAILABLE",
                           "No buyout right was negotiated on this lease.")
        lease["status"] = "BOUGHT_OUT"
        lease["buyout_paid_cents"] = lease["buyout_price_cents"]
        lease["paid_through_date"] = lease["term_end_date"]
        raws = dict(lease.get("_date_raw", {}))
        raws["paid_through_date"] = raws.get("term_end_date",
                                             _date_text(lease["term_end_date"]))
        lease["_date_raw"] = raws
        bump(lease)
        bump(find.tower(lease["tower_id"]))
        return object_response(serializers.ground_lease(lease))

    # -----------------------------------------------------------------------
    # Landlord payments
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/landlord-payments", methods=["POST"])
    def create_landlord_payment():
        auth("PortfolioAdmin")
        body = Body()
        lease_id = body.ident("ground_lease_id")
        period_start = body.moment("period_start_date")
        period_end = body.moment("period_end_date")
        if period_end <= period_start:
            raise ApiError("ERR_INVALID_REQUEST",
                           "period_end_date must be after period_start_date.")
        lease = find.ground_lease(lease_id)

        paid_through = lease["paid_through_date"]
        if paid_through is not None and period_start.date() <= paid_through.date():
            raise ApiError("ERR_PAYMENT_PERIOD_OVERLAP",
                           "The period re-covers ground already paid.")
        if paid_through is not None and period_start.date() != add_days(paid_through, 1).date():
            raise ApiError("ERR_PAYMENT_PERIOD_GAP",
                           "The period must start the day after paid_through_date.")
        if not is_first_of_month(period_start) or not is_last_of_month(period_end):
            raise ApiError("ERR_PAYMENT_PERIOD_NOT_WHOLE_MONTHS",
                           "The period must cover whole calendar months.")
        landlord = find.landlord(lease["landlord_id"])
        if not landlord["w9_on_file"]:
            raise ApiError("ERR_LANDLORD_W9_MISSING",
                           "The landlord has no tax documentation on file.")

        months = month_starts_within(period_start, period_end)
        amount = 0
        for first_day in months:
            amount += calc.ground_lease_rent_at(
                lease["base_monthly_rent_cents"], lease["escalator_pct"],
                lease["commencement_date"], first_day)

        record = new_immutable_record(
            ground_lease_id=lease_id,
            period_start_date=period_start,
            period_end_date=period_end,
            months_covered=len(months),
            amount_cents=amount,
            _date_raw=body.raw_dates(),
        )
        db.landlord_payments[record["id"]] = record
        lease["paid_through_date"] = period_end
        raws = dict(lease.get("_date_raw", {}))
        raws["paid_through_date"] = body.raw_dates().get(
            "period_end_date", _date_text(period_end))
        lease["_date_raw"] = raws
        bump(lease)
        return object_response(serializers.landlord_payment(record), 201)

    @app.route("/tower-colo/ground-leases/<lease_id>/landlord-payments", methods=["GET"])
    def list_landlord_payments(lease_id):
        user_id, role = auth("PortfolioAdmin", "Landlord")
        limit, offset = pagination()
        lease = find.ground_lease(lease_id)
        resolve_identity(user_id, role)
        items = [p for p in db.landlord_payments.values()
                 if p["ground_lease_id"] == lease["id"]]
        items.sort(key=lambda p: (p["period_start_date"], p["_seq"]))
        page, meta = paginate(items, limit, offset)
        return array_response([serializers.landlord_payment(p) for p in page], meta)

    # -----------------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------------
    @app.route("/tower-colo/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        auth("PortfolioAdmin")
        body = Body()
        target = body.moment("to_iso8601")
        if target <= db.clock:
            raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                           "The requested instant must be after the current clock.")

        postures_before = dict(
            (tower["id"], services.tower_capacity_posture(tower))
            for tower in db.towers.values())
        db.clock = target

        expired_leases = 0
        frozen_towers = []
        for lease in sorted_records(db.ground_leases.values()):
            if lease["status"] in ("ACTIVE", "RENEWAL_NEGOTIATION") \
                    and lease["term_end_date"] < db.clock:
                lease["status"] = "EXPIRED"
                bump(lease)
                expired_leases += 1
                if lease["tower_id"] not in frozen_towers:
                    frozen_towers.append(lease["tower_id"])

        for tower_id in frozen_towers:
            tower = db.towers.get(tower_id)
            if tower is None:
                continue
            services.freeze_pushback(tower)
            bump(tower)

        expired_mlas = 0
        for mla in sorted_records(db.mlas.values()):
            if mla["status"] == "ACTIVE" and mla["expires_on"] < db.clock:
                mla["status"] = "EXPIRED"
                bump(mla)
                expired_mlas += 1
                for application in services.mla_applications(mla["id"]):
                    if application["status"] in ("SUBMITTED", "UNDER_STRUCTURAL_REVIEW"):
                        application["status"] = "ON_HOLD"
                        bump(application)

        frozen_count = 0
        for tower in db.towers.values():
            if services.tower_capacity_posture(tower) == "FROZEN" \
                    and postures_before.get(tower["id"]) != "FROZEN":
                frozen_count += 1

        return object_response({
            "current_utc": iso(db.clock),
            "expired_ground_lease_count": expired_leases,
            "expired_master_lease_count": expired_mlas,
            "frozen_tower_count": frozen_count,
        })
