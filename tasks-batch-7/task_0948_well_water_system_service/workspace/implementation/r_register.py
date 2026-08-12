"""Clock, accounts, properties, well profiles, shared-well agreements,
technicians and the parts catalog."""

import calc
import common
import serialize
from core import (
    ApiError, F, JURISDICTION_CODES, ROLES, add_days, cents, d, db, endpoint,
    iso, whole_days_between,
)

ALL_ROLES = list(ROLES)


# ==========================================================================
# 4.1 Logical clock
# ==========================================================================

def _clock_backward(ctx):
    if ctx.body["to_iso8601"] < db.clock:
        raise ApiError("ERR_CLOCK_BACKWARD", "The logical clock may not move backwards.")


@endpoint("POST", "/water-service/_clock/set_current_utc", ["PlatformAdmin"],
          fields=[F("to_iso8601", "datetime")], g8_post=_clock_backward)
def set_clock(ctx):
    previous = db.clock
    db.clock = ctx.body["to_iso8601"]
    return {"current_utc": iso(db.clock), "previous_utc": iso(previous)}


@endpoint("GET", "/water-service/_clock", ALL_ROLES, read=True)
def get_clock(ctx):
    return {"current_utc": iso(db.clock)}


# ==========================================================================
# 4.2 Accounts
# ==========================================================================

MEMBERSHIP_TIERS = ["NONE", "SELECT", "PREMIER"]


@endpoint("POST", "/water-service/accounts", ["PlatformAdmin"], code=201, fields=[
    F("legal_name", "string", min_len=1, max_len=120),
    F("billing_jurisdiction_code", "string", one_of=JURISDICTION_CODES),
    F("contact_email", "string", contains="@"),
    F("membership_tier", "string", required=False, enum=MEMBERSHIP_TIERS,
      default="NONE"),
])
def create_account(ctx):
    row = ctx.new("Account", {
        "legal_name": ctx.body["legal_name"],
        "billing_jurisdiction_code": ctx.body["billing_jurisdiction_code"],
        "membership_tier": ctx.body["membership_tier"],
        "balance_cents": 0,
        "lifetime_invoiced_cents": 0,
        "lifetime_paid_cents": 0,
        "credit_hold": False,
        "contact_email": ctx.body["contact_email"],
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/accounts/<account_id>",
          ["PlatformAdmin", "BillingClerk", "Estimator", "Dispatcher", "CustomerContact"],
          read=True, path_params=[("account_id", "Account")],
          scope=common.scope(customer=lambda c: c.path["account_id"]["id"]))
def read_account(ctx):
    return serialize.dump(ctx.path["account_id"])


@endpoint("GET", "/water-service/accounts", ["PlatformAdmin", "BillingClerk"],
          read=True, paginated=True, filters=["membership_tier", "credit_hold"])
def list_accounts(ctx):
    return db.all("Account")


@endpoint("PATCH", "/water-service/accounts/<account_id>", ["PlatformAdmin"],
          path_params=[("account_id", "Account")],
          fields=[F("membership_tier", "string", enum=MEMBERSHIP_TIERS)])
def patch_account(ctx):
    account = ctx.path["account_id"]
    account["membership_tier"] = ctx.body["membership_tier"]
    ctx.touch(account)
    return serialize.dump(account)


@endpoint("GET", "/water-service/accounts/<account_id>/invoices",
          ["PlatformAdmin", "BillingClerk", "CustomerContact"], read=True,
          paginated=True, path_params=[("account_id", "Account")],
          scope=common.scope(customer=lambda c: c.path["account_id"]["id"]))
def account_invoices(ctx):
    return common.rows_where("Invoice", account_id=ctx.path["account_id"]["id"])


# ==========================================================================
# 4.3 Properties
# ==========================================================================

@endpoint("POST", "/water-service/properties", ["PlatformAdmin", "Dispatcher"],
          code=201, fields=[
              F("account_id", "string"),
              F("address_line", "string"),
              F("jurisdiction_code", "string", one_of=JURISDICTION_CODES),
              F("distance_miles", "number", minimum=0.0),
              F("household_size", "integer", minimum=1, maximum=12),
              F("has_vulnerable_occupant", "boolean", required=False, default=False),
          ])
def create_property(ctx):
    common.resolve("Account", ctx.body["account_id"])
    row = ctx.new("Property", {
        "account_id": ctx.body["account_id"],
        "address_line": ctx.body["address_line"],
        "jurisdiction_code": ctx.body["jurisdiction_code"],
        "distance_miles": ctx.body["distance_miles"],
        "household_size": ctx.body["household_size"],
        "has_vulnerable_occupant": ctx.body["has_vulnerable_occupant"],
        "service_zone": calc.service_zone(ctx.body["distance_miles"]),
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/properties/<property_id>",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician", "BillingClerk",
           "CustomerContact"], read=True, path_params=[("property_id", "Property")])
def read_property(ctx):
    return serialize.dump(ctx.path["property_id"])


@endpoint("GET", "/water-service/properties",
          ["PlatformAdmin", "Dispatcher", "Estimator", "BillingClerk"], read=True,
          paginated=True,
          filters=["account_id", "jurisdiction_code", "service_zone"])
def list_properties(ctx):
    return db.all("Property")


@endpoint("GET", "/water-service/properties/<property_id>/well-profiles",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician", "ComplianceOfficer"],
          read=True, paginated=True, path_params=[("property_id", "Property")])
def property_wells(ctx):
    return common.rows_where("WellProfile", property_id=ctx.path["property_id"]["id"])


# ==========================================================================
# 4.4 Well profiles
# ==========================================================================

@endpoint("POST", "/water-service/well-profiles", ["PlatformAdmin", "Dispatcher"],
          code=201, fields=[
              F("property_id", "string"),
              F("jurisdiction_code", "string", one_of=JURISDICTION_CODES),
              F("well_type", "string", enum=["DRILLED", "DRIVEN", "DUG"]),
              F("depth_feet", "number", minimum=10.0, maximum=1200.0),
              F("pressure_tank_drawdown_gallons", "number", required=False,
                default=6.0, minimum=1.0, maximum=120.0),
          ])
def create_well(ctx):
    common.resolve("Property", ctx.body["property_id"])
    row = ctx.new("WellProfile", {
        "property_id": ctx.body["property_id"],
        "jurisdiction_code": ctx.body["jurisdiction_code"],
        "well_type": ctx.body["well_type"],
        "depth_feet": ctx.body["depth_feet"],
        "measured_yield_gpm": None,
        "pressure_tank_drawdown_gallons": ctx.body["pressure_tank_drawdown_gallons"],
        "duty_cycle_ratio": None,
        "duty_cycle_class": None,
        "treatment_media": "NONE",
        "hardness_gpg": None,
        "potability_status": "UNKNOWN",
        "last_inspection_completed_at": None,
        "advisory_reason": None,
    })
    calc.apply_duty_cycle(row)
    return serialize.dump(row)


@endpoint("GET", "/water-service/well-profiles/<well_profile_id>",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician",
           "ComplianceOfficer", "CustomerContact"], read=True,
          path_params=[("well_profile_id", "WellProfile")])
def read_well(ctx):
    return serialize.dump(ctx.path["well_profile_id"])


@endpoint("GET", "/water-service/well-profiles",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician", "ComplianceOfficer"],
          read=True, paginated=True,
          filters=["property_id", "potability_status", "duty_cycle_class"])
def list_wells(ctx):
    return db.all("WellProfile")


@endpoint("POST",
          "/water-service/well-profiles/<well_profile_id>/pressure-tank-replacement",
          ["PlatformAdmin", "Technician"],
          path_params=[("well_profile_id", "WellProfile")],
          fields=[F("new_drawdown_gallons", "number", minimum=1.0, maximum=120.0)])
def pressure_tank_replacement(ctx):
    well = ctx.path["well_profile_id"]
    well["pressure_tank_drawdown_gallons"] = ctx.body["new_drawdown_gallons"]
    calc.apply_duty_cycle(well)
    common.recompute_plans_for_well(ctx, well)
    ctx.touch(well)
    return serialize.dump(well)


@endpoint("GET", "/water-service/well-profiles/<well_profile_id>/maintenance-plans",
          ["PlatformAdmin", "Dispatcher", "Technician", "CustomerContact"],
          read=True, paginated=True,
          path_params=[("well_profile_id", "WellProfile")])
def well_plans(ctx):
    return common.rows_where("MaintenancePlan",
                             well_profile_id=ctx.path["well_profile_id"]["id"])


@endpoint("POST",
          "/water-service/well-profiles/<well_profile_id>/treatment-recommendations",
          ["ComplianceOfficer", "PlatformAdmin"], code=201,
          path_params=[("well_profile_id", "WellProfile")],
          occ=("expected_well_profile_version", "ERR_STALE_WELL_PROFILE_VERSION",
               lambda c: c.path["well_profile_id"]),
          fields=[F("water_test_id", "string"),
                  F("expected_well_profile_version", "integer")])
def create_recommendation(ctx):
    well = ctx.path["well_profile_id"]
    test = common.resolve("WaterTest", ctx.body["water_test_id"])
    if test["panel_type"] != "CHEMICAL" \
            or test["result_status"] != "ANALYZED_CHEMICAL_EXCEEDANCE":
        raise ApiError("ERR_NO_TREATMENT_INDICATED",
                       "The cited test is not a chemical exceedance panel.")
    media = calc.recommended_media_selection(test)
    if media is None:
        raise ApiError("ERR_NO_TREATMENT_INDICATED",
                       "No analyte on the cited panel indicates a treatment.")

    design_grains = selected_capacity = salt_per_regen = monthly_salt = None
    if media == "SOFTENER_RESIN":
        prop = db.get("Property", well["property_id"])
        design_grains = calc.softener_design_grains(test["hardness_gpg"],
                                                    prop["household_size"])
        selected_capacity, salt_per_regen = calc.softener_capacity_selection(design_grains)
        monthly_salt = calc.softener_monthly_salt_lbs(salt_per_regen)
        salt_per_regen = float(salt_per_regen)

    row = ctx.new("TreatmentRecommendation", {
        "well_profile_id": well["id"],
        "water_test_id": test["id"],
        "superseded_by_id": None,
        "recommended_media": media,
        "design_grains": design_grains,
        "selected_capacity": selected_capacity,
        "salt_lbs_per_regen": salt_per_regen,
        "monthly_salt_lbs": monthly_salt,
        "expires_at": calc.recommendation_expires_at(test["sample_datetime"]),
        "status": "PROPOSED",
    })
    for earlier in common.rows_where("TreatmentRecommendation",
                                     well_profile_id=well["id"]):
        if earlier["id"] == row["id"]:
            continue
        if earlier["status"] in ("PROPOSED", "ACCEPTED"):
            earlier["status"] = "SUPERSEDED"
            earlier["superseded_by_id"] = row["id"]
            ctx.touch(earlier)
    ctx.touch(well)
    return serialize.dump(row)


# ==========================================================================
# 4.5 Shared-well agreements
# ==========================================================================

@endpoint("POST", "/water-service/shared-well-agreements",
          ["PlatformAdmin", "BillingClerk"], code=201, fields=[
              F("well_profile_id", "string"),
              F("account_id", "string"),
              F("split_pct", "number", minimum=0.01, maximum=100.00),
          ])
def create_share(ctx):
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Account", ctx.body["account_id"])
    existing = common.rows_where("SharedWellAgreement",
                                 well_profile_id=ctx.body["well_profile_id"],
                                 status="ACTIVE")
    for row in existing:
        if row["account_id"] == ctx.body["account_id"]:
            raise ApiError("ERR_DUPLICATE_SHARED_WELL_AGREEMENT",
                           "This account already shares this well.")
    total = sum((d(r["split_pct"]) for r in existing), d(0)) + d(ctx.body["split_pct"])
    if total > d("100.00") or len(existing) + 1 > calc.SHARED_WELL_MAX_PARTIES:
        raise ApiError("ERR_SHARED_WELL_SPLIT_INVALID",
                       "The shared-well split is invalid.")
    row = ctx.new("SharedWellAgreement", {
        "well_profile_id": ctx.body["well_profile_id"],
        "account_id": ctx.body["account_id"],
        "split_pct": ctx.body["split_pct"],
        "status": "ACTIVE",
    })
    return serialize.dump(row)


@endpoint("GET",
          "/water-service/shared-well-agreements/<shared_well_agreement_id>",
          ["PlatformAdmin", "BillingClerk", "CustomerContact"], read=True,
          path_params=[("shared_well_agreement_id", "SharedWellAgreement")])
def read_share(ctx):
    return serialize.dump(ctx.path["shared_well_agreement_id"])


@endpoint("GET", "/water-service/shared-well-agreements",
          ["PlatformAdmin", "BillingClerk"], read=True, paginated=True,
          filters=["well_profile_id", "account_id", "status"])
def list_shares(ctx):
    return db.all("SharedWellAgreement")


@endpoint("POST",
          "/water-service/shared-well-agreements/<shared_well_agreement_id>/terminate",
          ["PlatformAdmin"],
          path_params=[("shared_well_agreement_id", "SharedWellAgreement")])
def terminate_share(ctx):
    row = ctx.path["shared_well_agreement_id"]
    row["status"] = "TERMINATED"
    ctx.touch(row)
    return serialize.dump(row)


# ==========================================================================
# 4.6 Technicians
# ==========================================================================

TIERS = ["APPRENTICE", "JOURNEYMAN", "MASTER"]


@endpoint("POST", "/water-service/technicians", ["PlatformAdmin"], code=201, fields=[
    F("full_name", "string"),
    F("tier", "string", enum=TIERS),
    F("home_jurisdiction_code", "string", one_of=JURISDICTION_CODES),
    F("status", "string", required=False, enum=["AVAILABLE", "OFF_DUTY"],
      default="AVAILABLE"),
])
def create_technician(ctx):
    row = ctx.new("Technician", {
        "full_name": ctx.body["full_name"],
        "tier": ctx.body["tier"],
        "status": ctx.body["status"],
        "home_jurisdiction_code": ctx.body["home_jurisdiction_code"],
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/technicians/<technician_id>",
          ["PlatformAdmin", "Dispatcher", "Technician", "ComplianceOfficer"],
          read=True, path_params=[("technician_id", "Technician")])
def read_technician(ctx):
    return serialize.dump(ctx.path["technician_id"])


@endpoint("GET", "/water-service/technicians", ["PlatformAdmin", "Dispatcher"],
          read=True, paginated=True,
          filters=["tier", "status", "home_jurisdiction_code"])
def list_technicians(ctx):
    return db.all("Technician")


@endpoint("PATCH", "/water-service/technicians/<technician_id>",
          ["PlatformAdmin", "Dispatcher"],
          path_params=[("technician_id", "Technician")],
          fields=[F("status", "string", enum=["AVAILABLE", "OFF_DUTY"])])
def patch_technician(ctx):
    row = ctx.path["technician_id"]
    row["status"] = ctx.body["status"]
    ctx.touch(row)
    return serialize.dump(row)


# ==========================================================================
# 4.7 Part catalog
# ==========================================================================

PART_CATEGORIES = ["PUMP", "PRESSURE_TANK", "FILTRATION", "CONTROL", "CONSUMABLE"]
MEDIA_KINDS = ["NONE", "SEDIMENT", "CARBON", "SOFTENER_RESIN"]


@endpoint("POST", "/water-service/part-catalog-items", ["PlatformAdmin"], code=201,
          fields=[
              F("part_number", "string"),
              F("category", "string", enum=PART_CATEGORIES),
              F("unit_cost_cents", "integer", minimum=1, maximum=5000000),
              F("rated_gpm", "number", required=False),
              F("rated_drawdown_gallons", "number", required=False, minimum=1.0,
                maximum=120.0),
              F("grain_capacity", "integer", required=False),
              F("media_kind", "string", required=False, enum=MEDIA_KINDS,
                default="NONE"),
              F("on_hand_qty", "integer", required=False, default=0, minimum=0),
              F("status", "string", required=False, enum=["ACTIVE", "DISCONTINUED"],
                default="ACTIVE"),
          ])
def create_part(ctx):
    category = ctx.body["category"]
    media_kind = ctx.body["media_kind"]
    rated_gpm = ctx.body["rated_gpm"]
    rated_drawdown = ctx.body["rated_drawdown_gallons"]
    grain_capacity = ctx.body["grain_capacity"]
    if category == "PUMP":
        if rated_gpm is None:
            raise ApiError("ERR_VALIDATION", "rated_gpm is required for a PUMP part.")
    else:
        rated_gpm = None
    if category == "PRESSURE_TANK":
        if rated_drawdown is None:
            raise ApiError("ERR_VALIDATION",
                           "rated_drawdown_gallons is required for a PRESSURE_TANK part.")
    else:
        rated_drawdown = None
    if category == "FILTRATION" and media_kind == "SOFTENER_RESIN":
        if grain_capacity is None:
            raise ApiError("ERR_VALIDATION",
                           "grain_capacity is required for a softener resin part.")
    else:
        grain_capacity = None
    row = ctx.new("PartCatalogItem", {
        "part_number": ctx.body["part_number"],
        "category": category,
        "unit_cost_cents": ctx.body["unit_cost_cents"],
        "rated_gpm": rated_gpm,
        "rated_drawdown_gallons": rated_drawdown,
        "grain_capacity": grain_capacity,
        "media_kind": media_kind,
        "on_hand_qty": ctx.body["on_hand_qty"],
        "status": ctx.body["status"],
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/part-catalog-items/<part_catalog_item_id>",
          ["PlatformAdmin", "Estimator", "Technician", "Dispatcher", "ComplianceOfficer"],
          read=True, path_params=[("part_catalog_item_id", "PartCatalogItem")])
def read_part(ctx):
    return serialize.dump(ctx.path["part_catalog_item_id"])


@endpoint("GET", "/water-service/part-catalog-items",
          ["PlatformAdmin", "Estimator", "Technician", "Dispatcher"], read=True,
          paginated=True, filters=["category", "media_kind", "status"])
def list_parts(ctx):
    return db.all("PartCatalogItem")


@endpoint("PATCH", "/water-service/part-catalog-items/<part_catalog_item_id>",
          ["PlatformAdmin"],
          path_params=[("part_catalog_item_id", "PartCatalogItem")],
          fields=[
              F("unit_cost_cents", "integer", required=False, minimum=1,
                maximum=5000000),
              F("on_hand_qty", "integer", required=False, minimum=0),
              F("status", "string", required=False, enum=["ACTIVE", "DISCONTINUED"]),
          ])
def patch_part(ctx):
    row = ctx.path["part_catalog_item_id"]
    for name in ("unit_cost_cents", "on_hand_qty", "status"):
        if ctx.body.get(name) is not None:
            row[name] = ctx.body[name]
    ctx.touch(row)
    return serialize.dump(row)
