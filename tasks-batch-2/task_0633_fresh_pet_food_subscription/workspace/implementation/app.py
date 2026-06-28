"""Fresh Pet-Food Subscription API — entry point and route handlers.

All state is in-memory (store.py). No seeding at startup. Boots empty every time.
"""
import os

from flask import Flask, request

import auth
import calc
import domain
import errors
import requtil as rq
import response as resp
import serialize
from store import (
    clock, iso_millis,
    accounts, pets, recipes, subscriptions, weight_logs, orders,
    shipments, referral_credits,
)

app = Flask(__name__)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return resp.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return resp.error("ERR_INVALID_REQUEST", "Resource not found", 400)


@app.errorhandler(405)
def handle_405(e):
    return resp.error("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return resp.error(e.error_id, e.message, e.http_status)
    return resp.error("ERR_INVALID_REQUEST", str(e), 400)


# --------------------------------------------------------------------------
# Existence helpers (left-to-right resolution, PRD §2.10)
# --------------------------------------------------------------------------
def get_account_or_404(account_id):
    a = accounts.get(account_id)
    if a is None:
        errors.fail(errors.ERR_ACCOUNT_NOT_FOUND)
    return a


def get_pet_or_404(pet_id):
    p = pets.get(pet_id)
    if p is None:
        errors.fail(errors.ERR_PET_NOT_FOUND)
    return p


def get_recipe_or_404(recipe_id):
    r = recipes.get(recipe_id)
    if r is None:
        errors.fail(errors.ERR_RECIPE_NOT_FOUND)
    return r


def get_subscription_or_404(sub_id):
    s = subscriptions.get(sub_id)
    if s is None:
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_FOUND)
    return s


def get_order_or_404(order_id):
    o = orders.get(order_id)
    if o is None:
        errors.fail(errors.ERR_ORDER_NOT_FOUND)
    return o


def get_shipment_or_404(shipment_id):
    sh = shipments.get(shipment_id)
    if sh is None:
        errors.fail(errors.ERR_SHIPMENT_NOT_FOUND)
    return sh


def get_referral_credit_or_404(rc_id):
    rc = referral_credits.get(rc_id)
    if rc is None:
        errors.fail(errors.ERR_REFERRAL_CREDIT_NOT_FOUND)
    return rc


def paginate_and_respond(items_records, serializer, status=200):
    """Sort by creation order (created_at asc, _seq tie-break), paginate, envelope."""
    items_records = sorted(items_records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items_records)
    limit, offset = rq.pagination()
    page = items_records[offset:offset + limit]
    data = [serializer(r) for r in page]
    return resp.list_success(data, limit, offset, total, status=status)


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Any authenticated role may set; anonymous endpoints list excludes this in
    # the auth applies_to, so no user-context required.
    body = rq.get_body()
    rq.require_fields(body, "to_iso8601")
    dt = rq.parse_datetime(body["to_iso8601"], "to_iso8601")
    clock.set(dt)
    return resp.success({"current_utc": iso_millis(clock.now())}, status=200)


@app.route("/_clock", methods=["GET"])
def get_clock():
    return resp.success({"current_utc": iso_millis(clock.now())}, status=200)


# ==========================================================================
# Accounts & referral
# ==========================================================================
@app.route("/api/accounts/register", methods=["POST"])
def register_account():
    body = rq.get_body()
    email = rq.as_str(body, "email", required=True)
    full_name = rq.as_str(body, "full_name", required=True)
    country_code = rq.as_str(body, "country_code", default="US")
    referral_code = rq.as_str(body, "referral_code", default=None)

    if country_code not in ("US", "CA"):
        errors.fail(errors.ERR_INVALID_REQUEST, "country_code must be US or CA")

    # Fiscal/uniqueness checks (priority 10).
    if domain.find_account_by_email(email) is not None:
        errors.fail(errors.ERR_EMAIL_TAKEN)

    referrer = None
    if referral_code is not None:
        referrer = domain.find_account_by_referral_code(referral_code)
        if referrer is None or referrer["status"] != "ACTIVE":
            errors.fail(errors.ERR_REFERRAL_CODE_INVALID)

    referred_by = referrer["id"] if referrer is not None else None
    acct = domain.create_account(email, full_name, country_code, referred_by)

    if referrer is not None:
        # Self-referral check: a code resolving to the account being registered.
        if referrer["id"] == acct["id"]:
            # Should not happen (new id), but guard the rule.
            errors.fail(errors.ERR_SELF_REFERRAL)
        domain.mint_signup_credits(referrer, acct)

    return resp.success(serialize.ser_account(acct), status=201)


@app.route("/api/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin")
    a = get_account_or_404(account_id)
    auth.require_owner(caller, a["id"])
    return resp.success(serialize.ser_account(a), status=200)


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    caller = auth.require_context()
    auth.require_role(caller, "BillingAdmin")
    referred_by = rq.query("referred_by_account_id")
    recs = list(accounts.values())
    if referred_by is not None:
        recs = [a for a in recs if a["referred_by_account_id"] == referred_by]
    return paginate_and_respond(recs, serialize.ser_account)


@app.route("/api/referrals/redeem-preview", methods=["POST"])
def redeem_preview():
    body = rq.get_body()
    code = rq.as_str(body, "referral_code", required=True)
    referrer = domain.find_account_by_referral_code(code)
    if referrer is None or referrer["status"] != "ACTIVE":
        errors.fail(errors.ERR_REFERRAL_CODE_INVALID)
    referrer_grant = calc.referrer_grant_cents(
        serialize.compute_lifetime_grants(referrer["id"]))
    referred_grant = calc.referred_grant_cents()
    return resp.success({
        "referrer_grant_cents": referrer_grant,
        "referred_grant_cents": referred_grant,
        "referrer_account_id": referrer["id"],
    }, status=200)


@app.route("/api/referral-credits", methods=["GET"])
def list_referral_credits():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin")
    recs = list(referral_credits.values())
    referrer_id = rq.query("referrer_account_id")
    referred_id = rq.query("referred_account_id")
    beneficiary = rq.query("beneficiary")
    status = rq.query("status")
    if referrer_id is not None:
        recs = [r for r in recs if r["referrer_account_id"] == referrer_id]
    if referred_id is not None:
        recs = [r for r in recs if r["referred_account_id"] == referred_id]
    if beneficiary is not None:
        recs = [r for r in recs if r["beneficiary"] == beneficiary]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if caller.role == "PetParent":
        recs = [r for r in recs
                if r["referrer_account_id"] == caller.user_id
                or r["referred_account_id"] == caller.user_id]
    return paginate_and_respond(recs, serialize.ser_referral_credit)


@app.route("/api/referral-credits/<rc_id>", methods=["GET"])
def get_referral_credit(rc_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin")
    rc = get_referral_credit_or_404(rc_id)
    if caller.role == "PetParent" and \
            caller.user_id not in (rc["referrer_account_id"], rc["referred_account_id"]):
        errors.fail(errors.ERR_FORBIDDEN_ROLE)
    return resp.success(serialize.ser_referral_credit(rc), status=200)


# ==========================================================================
# Recipes
# ==========================================================================
@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    caller = auth.require_context()
    auth.require_role(caller, "NutritionVet")
    body = rq.get_body()
    name = rq.as_str(body, "name", required=True)
    species = rq.as_str(body, "species", required=True)
    kcal_per_gram = rq.as_number(body, "kcal_per_gram", required=True)
    price_per_100g_cents = rq.as_int(body, "price_per_100g_cents", required=True)
    ingredient_allergens = rq.as_list(body, "ingredient_allergens", default=[])
    availability_regions = rq.as_list(body, "availability_regions", default=[])
    vet_formulated = rq.as_bool(body, "vet_formulated", default=False)

    if species not in ("DOG", "CAT"):
        errors.fail(errors.ERR_INVALID_REQUEST, "species must be DOG or CAT")
    if kcal_per_gram <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "kcal_per_gram must be > 0")
    if price_per_100g_cents <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "price_per_100g_cents must be > 0")

    rec = domain.create_recipe(name, species, kcal_per_gram, price_per_100g_cents,
                               ingredient_allergens, availability_regions, vet_formulated)
    return resp.success(serialize.ser_recipe(rec), status=201)


@app.route("/api/recipes/<recipe_id>/publish", methods=["POST"])
def publish_recipe(recipe_id):
    caller = auth.require_context()
    auth.require_role(caller, "NutritionVet")
    r = get_recipe_or_404(recipe_id)
    if r["status"] != "DRAFT":
        errors.fail(errors.ERR_RECIPE_NOT_DRAFT)
    r["status"] = "PUBLISHED"
    domain.touch(r)
    return resp.success(serialize.ser_recipe(r), status=200)


@app.route("/api/recipes/<recipe_id>/retire", methods=["POST"])
def retire_recipe(recipe_id):
    caller = auth.require_context()
    auth.require_role(caller, "NutritionVet")
    r = get_recipe_or_404(recipe_id)
    if r["status"] != "PUBLISHED":
        errors.fail(errors.ERR_RECIPE_NOT_PUBLISHED)
    r["status"] = "RETIRED"
    domain.touch(r)
    return resp.success(serialize.ser_recipe(r), status=200)


@app.route("/api/recipes/<recipe_id>", methods=["GET"])
def get_recipe(recipe_id):
    caller = auth.require_context()
    auth.require_role(caller, "NutritionVet", "PetParent", "BillingAdmin")
    r = get_recipe_or_404(recipe_id)
    return resp.success(serialize.ser_recipe(r), status=200)


@app.route("/api/recipes", methods=["GET"])
def list_recipes():
    caller = auth.require_context()
    auth.require_role(caller, "NutritionVet", "PetParent", "BillingAdmin")
    recs = list(recipes.values())
    species = rq.query("species")
    status = rq.query("status")
    if species is not None:
        recs = [r for r in recs if r["species"] == species]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate_and_respond(recs, serialize.ser_recipe)


# ==========================================================================
# Pets
# ==========================================================================
@app.route("/api/pets", methods=["POST"])
def create_pet():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    body = rq.get_body()
    account_id = rq.as_str(body, "account_id", required=True)
    name = rq.as_str(body, "name", required=True)
    species = rq.as_str(body, "species", required=True)
    sex = rq.as_str(body, "sex", required=True)
    birth_date = rq.as_datetime(body, "birth_date", required=True)
    initial_weight_kg = rq.as_number(body, "initial_weight_kg", required=True)
    ideal_weight_kg = rq.as_number(body, "ideal_weight_kg", required=True)
    activity_level = rq.as_str(body, "activity_level", default="MODERATE")
    neutered = rq.as_bool(body, "neutered", default=True)
    body_condition_goal = rq.as_str(body, "body_condition_goal", default="MAINTAIN")
    allergen_exclusions = rq.as_list(body, "allergen_exclusions", default=[])

    if species not in ("DOG", "CAT"):
        errors.fail(errors.ERR_INVALID_REQUEST, "species must be DOG or CAT")
    if sex not in ("MALE", "FEMALE"):
        errors.fail(errors.ERR_INVALID_REQUEST, "sex must be MALE or FEMALE")
    if activity_level not in ("LOW", "MODERATE", "HIGH"):
        errors.fail(errors.ERR_INVALID_REQUEST, "invalid activity_level")
    if body_condition_goal not in ("LOSE", "MAINTAIN", "GAIN"):
        errors.fail(errors.ERR_INVALID_REQUEST, "invalid body_condition_goal")
    if initial_weight_kg <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "initial_weight_kg must be > 0")
    if ideal_weight_kg <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "ideal_weight_kg must be > 0")

    # Existence + ownership: account must exist and equal the acting parent.
    get_account_or_404(account_id)
    auth.require_owner(caller, account_id)

    rec = domain.create_pet(account_id, name, species, sex, birth_date,
                            initial_weight_kg, ideal_weight_kg, activity_level,
                            neutered, body_condition_goal, allergen_exclusions)
    return resp.success(serialize.ser_pet(rec), status=201)


@app.route("/api/pets/<pet_id>", methods=["GET"])
def get_pet(pet_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "NutritionVet", "BillingAdmin")
    p = get_pet_or_404(pet_id)
    auth.require_owner(caller, p["account_id"])
    return resp.success(serialize.ser_pet(p), status=200)


@app.route("/api/pets", methods=["GET"])
def list_pets():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "NutritionVet", "BillingAdmin")
    recs = list(pets.values())
    account_id = rq.query("account_id")
    status = rq.query("status")
    if account_id is not None:
        recs = [p for p in recs if p["account_id"] == account_id]
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    if caller.role == "PetParent":
        recs = [p for p in recs if p["account_id"] == caller.user_id]
    return paginate_and_respond(recs, serialize.ser_pet)


@app.route("/api/pets/<pet_id>", methods=["PATCH"])
def update_pet(pet_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    p = get_pet_or_404(pet_id)
    auth.require_owner(caller, p["account_id"])
    body = rq.get_body()

    if "activity_level" in body and body["activity_level"] is not None:
        val = rq.as_str(body, "activity_level")
        if val not in ("LOW", "MODERATE", "HIGH"):
            errors.fail(errors.ERR_INVALID_REQUEST, "invalid activity_level")
        p["activity_level"] = val
    if "neutered" in body and body["neutered"] is not None:
        p["neutered"] = rq.as_bool(body, "neutered")
    if "body_condition_goal" in body and body["body_condition_goal"] is not None:
        val = rq.as_str(body, "body_condition_goal")
        if val not in ("LOSE", "MAINTAIN", "GAIN"):
            errors.fail(errors.ERR_INVALID_REQUEST, "invalid body_condition_goal")
        p["body_condition_goal"] = val
    if "ideal_weight_kg" in body and body["ideal_weight_kg"] is not None:
        val = rq.as_number(body, "ideal_weight_kg")
        if val <= 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "ideal_weight_kg must be > 0")
        p["ideal_weight_kg"] = val
    if "allergen_exclusions" in body and body["allergen_exclusions"] is not None:
        p["allergen_exclusions"] = rq.as_list(body, "allergen_exclusions")

    domain.recompute_pet_nutrition(p)
    domain.touch(p)
    return resp.success(serialize.ser_pet(p), status=200)


@app.route("/api/pets/<pet_id>/archive", methods=["POST"])
def archive_pet(pet_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    p = get_pet_or_404(pet_id)
    auth.require_owner(caller, p["account_id"])
    if domain.pet_has_blocking_subscription(p["id"]):
        errors.fail(errors.ERR_PET_HAS_ACTIVE_SUBSCRIPTION)
    p["status"] = "ARCHIVED"
    domain.touch(p)
    return resp.success(serialize.ser_pet(p), status=200)


# ==========================================================================
# Weight logs
# ==========================================================================
@app.route("/api/weight-logs", methods=["POST"])
def create_weight_log():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    body = rq.get_body()
    pet_id = rq.as_str(body, "pet_id", required=True)
    weight_kg = rq.as_number(body, "weight_kg", required=True)
    effective_date = rq.as_datetime(body, "effective_date", default=None)

    if weight_kg <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "weight_kg must be > 0")

    p = get_pet_or_404(pet_id)
    auth.require_owner(caller, p["account_id"])

    if effective_date is None:
        effective_date = clock.now()
    # Temporal gate: effective_date must not be in the future.
    if effective_date > clock.now():
        errors.fail(errors.ERR_WEIGHTLOG_FUTURE_DATED)

    rec = domain.create_weight_log(p, weight_kg, effective_date)
    domain.touch(p)
    return resp.success(serialize.ser_weight_log(rec), status=201)


@app.route("/api/weight-logs", methods=["GET"])
def list_weight_logs():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "NutritionVet", "BillingAdmin")
    recs = list(weight_logs.values())
    pet_id = rq.query("pet_id")
    status = rq.query("status")
    if pet_id is not None:
        recs = [w for w in recs if w["pet_id"] == pet_id]
    if status is not None:
        recs = [w for w in recs if w["status"] == status]
    if caller.role == "PetParent":
        owned = {p["id"] for p in pets.values() if p["account_id"] == caller.user_id}
        recs = [w for w in recs if w["pet_id"] in owned]
    return paginate_and_respond(recs, serialize.ser_weight_log)


@app.route("/api/weight-logs/<wl_id>", methods=["GET"])
def get_weight_log(wl_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "NutritionVet", "BillingAdmin")
    w = weight_logs.get(wl_id)
    if w is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "weight log not found")
    if caller.role == "PetParent":
        p = pets.get(w["pet_id"])
        if p is None or p["account_id"] != caller.user_id:
            errors.fail(errors.ERR_FORBIDDEN_ROLE)
    return resp.success(serialize.ser_weight_log(w), status=200)


# ==========================================================================
# Subscriptions
# ==========================================================================
def _run_referential_gate(sub_account, pet, recipe):
    """Activation / swap gate, in PRD order: published, species, allergen, region.

    Caller is responsible for the DRAFT/state check before this for activation.
    """
    if recipe["status"] != "PUBLISHED":
        errors.fail(errors.ERR_RECIPE_NOT_PUBLISHED)
    if recipe["species"] != pet["species"]:
        errors.fail(errors.ERR_RECIPE_SPECIES_MISMATCH)
    if set(recipe["ingredient_allergens"]) & set(pet["allergen_exclusions"]):
        errors.fail(errors.ERR_ALLERGEN_CONFLICT)
    if sub_account["country_code"] not in recipe["availability_regions"]:
        errors.fail(errors.ERR_RECIPE_REGION_UNAVAILABLE)


@app.route("/api/subscriptions", methods=["POST"])
def create_subscription():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    body = rq.get_body()
    account_id = rq.as_str(body, "account_id", required=True)
    pet_id = rq.as_str(body, "pet_id", required=True)
    recipe_id = rq.as_str(body, "recipe_id", required=True)
    cadence_days = rq.as_int(body, "cadence_days", default=28)

    # Existence left-to-right: account, then pet, then recipe.
    acct = get_account_or_404(account_id)
    auth.require_owner(caller, account_id)
    p = get_pet_or_404(pet_id)
    r = get_recipe_or_404(recipe_id)

    # pet must belong to account_id.
    if p["account_id"] != account_id:
        errors.fail(errors.ERR_PET_NOT_FOUND)

    # Allergen safety at create (priority 6) is reported before domain
    # constraints such as cadence (priority 8), per PRD §2.9 validation ordering.
    if set(r["ingredient_allergens"]) & set(p["allergen_exclusions"]):
        errors.fail(errors.ERR_ALLERGEN_CONFLICT)

    # Domain constraint: cadence (priority 8).
    if cadence_days not in (14, 21, 28):
        errors.fail(errors.ERR_INVALID_CADENCE)

    rec = domain.create_subscription(account_id, pet_id, recipe_id, cadence_days, p, r)
    return resp.success(serialize.ser_subscription(rec), status=201)


@app.route("/api/subscriptions/<sub_id>", methods=["GET"])
def get_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin", "FulfillmentOps")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions", methods=["GET"])
def list_subscriptions():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin", "FulfillmentOps")
    recs = list(subscriptions.values())
    account_id = rq.query("account_id")
    pet_id = rq.query("pet_id")
    recipe_id = rq.query("recipe_id")
    status = rq.query("status")
    if account_id is not None:
        recs = [s for s in recs if s["account_id"] == account_id]
    if pet_id is not None:
        recs = [s for s in recs if s["pet_id"] == pet_id]
    if recipe_id is not None:
        recs = [s for s in recs if s["recipe_id"] == recipe_id]
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    if caller.role == "PetParent":
        recs = [s for s in recs if s["account_id"] == caller.user_id]
    return paginate_and_respond(recs, serialize.ser_subscription)


@app.route("/api/subscriptions/<sub_id>/activate", methods=["POST"])
def activate_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])

    if s["status"] != "DRAFT":
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_DRAFT)

    pet = pets[s["pet_id"]]
    recipe = recipes[s["recipe_id"]]
    acct = accounts[s["account_id"]]

    # Referential gate order (PRD §3.5): pet ACTIVE, recipe PUBLISHED, species,
    # allergen, region.
    if pet["status"] != "ACTIVE":
        errors.fail(errors.ERR_PET_ARCHIVED)
    _run_referential_gate(acct, pet, recipe)

    s["status"] = "ACTIVE"
    s["transition_remaining_cycles"] = calc.TRANSITION_CYCLES
    domain.compute_estimate(s, pet, recipe)
    s["next_order_date"] = clock.now()
    s["consecutive_failed_charges"] = 0
    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/pause", methods=["POST"])
def pause_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    if s["status"] != "ACTIVE":
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)
    if domain.sub_has_charging_order(s["id"]):
        errors.fail(errors.ERR_ORDER_IN_FLIGHT)
    body = rq.get_body()
    resume_at = rq.as_datetime(body, "resume_at", default=None)
    s["status"] = "PAUSED"
    s["pause_until"] = resume_at
    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/resume", methods=["POST"])
def resume_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    if s["status"] != "PAUSED":
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_PAUSED)
    s["status"] = "ACTIVE"
    s["pause_until"] = None
    nod = s["next_order_date"]
    now = clock.now()
    s["next_order_date"] = max(nod, now) if nod is not None else now
    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/swap-recipe", methods=["POST"])
def swap_recipe(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    body = rq.get_body()
    recipe_id = rq.as_str(body, "recipe_id", required=True)
    new_recipe = get_recipe_or_404(recipe_id)

    pet = pets[s["pet_id"]]
    acct = accounts[s["account_id"]]
    # Re-run referential + allergen + region gate.
    _run_referential_gate(acct, pet, new_recipe)

    s["recipe_id"] = recipe_id
    domain.compute_estimate(s, pet, new_recipe)
    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/resize", methods=["POST"])
def resize_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    body = rq.get_body()
    expected_version = rq.as_int(body, "expected_subscription_version", required=True)
    effective_at = rq.as_datetime(body, "effective_at", default=None)

    if effective_at is None:
        effective_at = clock.now()
    # Temporal gate (priority 7): effective_at must be at or after the clock.
    if effective_at < clock.now():
        errors.fail(errors.ERR_RESIZE_EFFECTIVE_IN_PAST)

    # OCC (priority 9).
    if expected_version != s["version"]:
        errors.fail(errors.ERR_STALE_SUBSCRIPTION_VERSION)

    pet = pets[s["pet_id"]]
    recipe = recipes[s["recipe_id"]]
    # Recompute grams from the pet's CURRENT daily_calorie_target.
    new_gpd = int(calc.round_half_up(
        pet["daily_calorie_target"] / recipe["kcal_per_gram"], 0))
    s["pending_resize_grams_per_day"] = new_gpd
    s["resize_effective_at"] = effective_at

    # If effective at or before the clock, realize immediately.
    if effective_at <= clock.now():
        domain.realize_resize(s, pet, recipe)

    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/cancel", methods=["POST"])
def cancel_subscription(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    s = get_subscription_or_404(sub_id)
    auth.require_owner(caller, s["account_id"])
    if s["status"] not in ("ACTIVE", "PAUSED", "PAST_DUE"):
        errors.fail(errors.ERR_SUBSCRIPTION_ALREADY_CANCELLED)
    if domain.sub_has_charging_order(s["id"]):
        errors.fail(errors.ERR_ORDER_IN_FLIGHT)
    s["status"] = "CANCELLED"
    domain.cancel_cascade(s)
    domain.touch(s)
    return resp.success(serialize.ser_subscription(s), status=200)


@app.route("/api/subscriptions/<sub_id>/orders", methods=["POST"])
def generate_order(sub_id):
    caller = auth.require_context()
    auth.require_role(caller, "BillingAdmin", "FulfillmentOps")
    s = get_subscription_or_404(sub_id)
    body = rq.get_body()
    expected_version = rq.as_int(body, "expected_subscription_version", required=True)
    # OCC (priority 9).
    if expected_version != s["version"]:
        errors.fail(errors.ERR_STALE_SUBSCRIPTION_VERSION)
    rec = domain.generate_order(s)
    return resp.success(serialize.ser_order(rec), status=201)


# ==========================================================================
# Orders
# ==========================================================================
@app.route("/api/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin", "FulfillmentOps")
    o = get_order_or_404(order_id)
    auth.require_owner(caller, o["account_id"])
    return resp.success(serialize.ser_order(o), status=200)


@app.route("/api/orders", methods=["GET"])
def list_orders():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "BillingAdmin", "FulfillmentOps")
    recs = list(orders.values())
    subscription_id = rq.query("subscription_id")
    account_id = rq.query("account_id")
    status = rq.query("status")
    if subscription_id is not None:
        recs = [o for o in recs if o["subscription_id"] == subscription_id]
    if account_id is not None:
        recs = [o for o in recs if o["account_id"] == account_id]
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    if caller.role == "PetParent":
        recs = [o for o in recs if o["account_id"] == caller.user_id]
    return paginate_and_respond(recs, serialize.ser_order)


@app.route("/api/orders/<order_id>/skip", methods=["POST"])
def skip_order(order_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent")
    o = get_order_or_404(order_id)
    auth.require_owner(caller, o["account_id"])
    s = subscriptions[o["subscription_id"]]
    if o["status"] != "SCHEDULED":
        errors.fail(errors.ERR_ORDER_NOT_SCHEDULED)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)
    # Temporal gate: current clock date strictly before scheduled_ship_date.
    if clock.now() >= o["scheduled_ship_date"]:
        errors.fail(errors.ERR_SKIP_WINDOW_CLOSED)
    o["status"] = "SKIPPED"
    domain.touch(o)
    domain._advance_next_order_date(s)
    domain.touch(s)
    return resp.success(serialize.ser_order(o), status=200)


@app.route("/api/orders/<order_id>/charge", methods=["POST"])
def charge_order(order_id):
    caller = auth.require_context()
    auth.require_role(caller, "BillingAdmin", "FulfillmentOps")
    o = get_order_or_404(order_id)
    s = subscriptions[o["subscription_id"]]
    if o["status"] != "SCHEDULED":
        errors.fail(errors.ERR_ORDER_NOT_SCHEDULED)
    if s["status"] not in ("ACTIVE", "PAST_DUE"):
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_CHARGEABLE)
    # Temporal gate: clock date on/after scheduled_ship_date.
    if clock.now() < o["scheduled_ship_date"]:
        errors.fail(errors.ERR_CHARGE_BEFORE_SHIP_DATE)
    o["status"] = "CHARGING"
    domain.finalize_billing(o, o["account_id"])
    domain.touch(o)
    return resp.success(serialize.ser_order(o), status=200)


@app.route("/api/orders/<order_id>/settle-charge", methods=["POST"])
def settle_charge_order(order_id):
    caller = auth.require_context()
    auth.require_role(caller, "BillingAdmin", "FulfillmentOps")
    o = get_order_or_404(order_id)
    body = rq.get_body()
    outcome = rq.as_str(body, "outcome", required=True)
    if outcome not in ("SUCCEEDED", "DECLINED"):
        errors.fail(errors.ERR_INVALID_REQUEST, "outcome must be SUCCEEDED or DECLINED")
    if o["status"] != "CHARGING":
        errors.fail(errors.ERR_ORDER_NOT_CHARGING)
    s = subscriptions[o["subscription_id"]]
    if outcome == "SUCCEEDED":
        domain.settle_succeeded(o, s)
    else:
        domain.settle_declined(o, s)
    return resp.success(serialize.ser_order(o), status=200)


@app.route("/api/orders/<order_id>/retry-charge", methods=["POST"])
def retry_charge_order(order_id):
    caller = auth.require_context()
    auth.require_role(caller, "BillingAdmin")
    o = get_order_or_404(order_id)
    s = subscriptions[o["subscription_id"]]
    if o["status"] != "FAILED":
        errors.fail(errors.ERR_ORDER_NOT_FAILED)
    if s["status"] != "PAST_DUE":
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_PAST_DUE)
    o["status"] = "CHARGING"
    domain.finalize_billing(o, o["account_id"])
    domain.touch(o)
    return resp.success(serialize.ser_order(o), status=200)


# ==========================================================================
# Shipments
# ==========================================================================
@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "FulfillmentOps", "BillingAdmin")
    recs = list(shipments.values())
    order_id = rq.query("order_id")
    status = rq.query("status")
    if order_id is not None:
        recs = [sh for sh in recs if sh["order_id"] == order_id]
    if status is not None:
        recs = [sh for sh in recs if sh["status"] == status]
    if caller.role == "PetParent":
        owned = {o["id"] for o in orders.values() if o["account_id"] == caller.user_id}
        recs = [sh for sh in recs if sh["order_id"] in owned]
    return paginate_and_respond(recs, serialize.ser_shipment)


@app.route("/api/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    caller = auth.require_context()
    auth.require_role(caller, "PetParent", "FulfillmentOps", "BillingAdmin")
    sh = get_shipment_or_404(shipment_id)
    if caller.role == "PetParent":
        o = orders.get(sh["order_id"])
        if o is None or o["account_id"] != caller.user_id:
            errors.fail(errors.ERR_FORBIDDEN_ROLE)
    return resp.success(serialize.ser_shipment(sh), status=200)


@app.route("/api/shipments/<shipment_id>", methods=["PATCH"])
def update_shipment(shipment_id):
    caller = auth.require_context()
    auth.require_role(caller, "FulfillmentOps")
    sh = get_shipment_or_404(shipment_id)
    if sh["status"] != "PENDING":
        errors.fail(errors.ERR_SHIPMENT_NOT_PENDING)
    body = rq.get_body()
    transit_days = rq.as_int(body, "transit_days", required=True)
    if transit_days < 1 or transit_days > 5:
        errors.fail(errors.ERR_INVALID_TRANSIT_DAYS)
    sh["transit_days"] = transit_days
    o = orders[sh["order_id"]]
    domain.recompute_coolant(sh, o)
    domain.touch(sh)
    return resp.success(serialize.ser_shipment(sh), status=200)


@app.route("/api/shipments/<shipment_id>/dispatch", methods=["POST"])
def dispatch_shipment(shipment_id):
    caller = auth.require_context()
    auth.require_role(caller, "FulfillmentOps")
    sh = get_shipment_or_404(shipment_id)
    o = orders[sh["order_id"]]
    if sh["status"] != "PENDING":
        errors.fail(errors.ERR_SHIPMENT_NOT_PENDING)
    if o["status"] != "PAID":
        errors.fail(errors.ERR_ORDER_NOT_PAID)
    required = calc.coolant_packs(o["food_grams"], sh["transit_days"])
    if sh["coolant_packs"] < required:
        errors.fail(errors.ERR_INSUFFICIENT_COOLANT)
    sh["status"] = "DISPATCHED"
    sh["dispatched_at"] = clock.now()
    domain.touch(sh)
    return resp.success(serialize.ser_shipment(sh), status=200)


@app.route("/api/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    caller = auth.require_context()
    auth.require_role(caller, "FulfillmentOps")
    sh = get_shipment_or_404(shipment_id)
    if sh["status"] == "SPOILED":
        errors.fail(errors.ERR_SHIPMENT_SPOILED)
    if sh["status"] != "DISPATCHED":
        errors.fail(errors.ERR_SHIPMENT_NOT_DISPATCHED)
    elapsed_days = (clock.now() - sh["dispatched_at"]).days
    if elapsed_days <= sh["transit_days"]:
        sh["status"] = "DELIVERED"
        domain.touch(sh)
    else:
        sh["status"] = "SPOILED"
        domain.touch(sh)
        o = orders[sh["order_id"]]
        domain.mint_make_good(o)
    return resp.success(serialize.ser_shipment(sh), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
