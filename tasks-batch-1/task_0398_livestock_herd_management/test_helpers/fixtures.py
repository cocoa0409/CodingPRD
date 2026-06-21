"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Helpers use the
lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

All five roles are OPAQUE-identity (PRD §2.1), so role headers are shared
constants from TEST_USERS — there is no ownership threading to do.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
CLERK = TEST_USERS["sale_clerk_headers"]
FEED = TEST_USERS["feedlot_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Unique-suffix counter so premises_id / ear_tag stay unique within one test.
_counter = itertools.count(1)


def _uid() -> int:
    return next(_counter)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=HM):
    """Set the system clock. Returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# --------------------------------------------------------------------------
# Tier 1/2: base aggregates
# --------------------------------------------------------------------------
def create_herd(species="CATTLE", name=None, premises_id=None):
    """Create a herd. Returns the herd dict."""
    n = _uid()
    payload = {
        "name": name or f"Herd-{n}",
        "species": species,
        "premises_id": premises_id or f"PR-{n:05d}",
    }
    return get_success_data(api_client.create_herd(payload, HM))


def create_pasture(kind="PEN", capacity_au=10.0, rest_days=None, name=None):
    """Create a pasture or pen. Returns the pasture dict."""
    payload = {"name": name or f"Place-{_uid()}", "kind": kind, "capacity_au": capacity_au}
    if rest_days is not None:
        payload["rest_days"] = rest_days
    return get_success_data(api_client.create_pasture(payload, HM))


def create_drug(route_withdrawals=None, category="ANTIBIOTIC", name=None):
    """Create a drug product. Returns the drug dict."""
    payload = {
        "name": name or f"Drug-{_uid()}",
        "category": category,
        "route_withdrawals": route_withdrawals or {"INJECTION_IM": 28},
    }
    return get_success_data(api_client.create_drug_product(payload, VET))


def create_ration(target_dmi_kg, ingredients, name=None):
    """Create a feed ration. Returns the ration dict."""
    payload = {
        "name": name or f"Ration-{_uid()}",
        "target_dmi_kg": target_dmi_kg,
        "ingredients": ingredients,
    }
    return get_success_data(api_client.create_feed_ration(payload, FEED))


def create_animal(herd_id, sex="STEER", birth_date="2024-01-01",
                  birth_weight_kg=40.0, ear_tag=None, **overrides):
    """Register an animal. Returns the animal dict."""
    payload = {
        "herd_id": herd_id,
        "ear_tag": ear_tag or f"ET-{_uid()}",
        "sex": sex,
        "birth_date": birth_date,
        "birth_weight_kg": birth_weight_kg,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_animal(payload, HM))


def record_weight(animal_id, weight_kg, weighed_at, source=None, headers=HM):
    """Record a weight. Returns the WeightRecord dict."""
    payload = {"weighed_at": weighed_at, "weight_kg": weight_kg}
    if source is not None:
        payload["source"] = source
    return get_success_data(api_client.create_weight(animal_id, payload, headers))


def create_weighed_animal(herd_id, weight_kg, weighed_at="2026-03-20",
                          sex="STEER", birth_date="2024-01-01",
                          birth_weight_kg=40.0, ear_tag=None):
    """Register an animal and immediately record one weight against it.
    Returns the animal dict re-read AFTER the weighing (latest_weight_kg reflects it)."""
    animal = create_animal(
        herd_id, sex=sex, birth_date=birth_date,
        birth_weight_kg=birth_weight_kg, ear_tag=ear_tag,
    )
    record_weight(animal["id"], weight_kg, weighed_at)
    return get_success_data(api_client.get_animal(animal["id"], HM))


# --------------------------------------------------------------------------
# Tier 3: movement lifecycle shortcuts
# --------------------------------------------------------------------------
def plan_and_apply_movement(animal_id, to_pasture_id, effective_from,
                            effective_to=None):
    """Plan a movement and apply it (OCC-correct: reads the live animal version
    immediately before apply). Returns the applied MovementRecord dict."""
    payload = {
        "animal_id": animal_id,
        "to_pasture_id": to_pasture_id,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    mv = get_success_data(api_client.create_movement_record(payload, HM))
    animal = get_success_data(api_client.get_animal(animal_id, HM))
    return get_success_data(
        api_client.apply_movement(
            mv["id"], {"expected_animal_version": animal["version"]}, HM
        )
    )


def plan_movement(animal_id, to_pasture_id, effective_from, effective_to=None):
    """Plan a movement only (status PLANNED). Returns the MovementRecord dict."""
    payload = {
        "animal_id": animal_id,
        "to_pasture_id": to_pasture_id,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api_client.create_movement_record(payload, HM))


# --------------------------------------------------------------------------
# Tier 3: health-treatment / withhold shortcuts
# --------------------------------------------------------------------------
def treat_animal(animal_id, drug_product_id, route="INJECTION_IM",
                 first_dose_on="2026-05-01", last_dose_on="2026-05-01",
                 dose_count=None):
    """Record a health treatment. Returns the HealthTreatment dict."""
    payload = {
        "animal_id": animal_id,
        "drug_product_id": drug_product_id,
        "route": route,
        "first_dose_on": first_dose_on,
        "last_dose_on": last_dose_on,
    }
    if dose_count is not None:
        payload["dose_count"] = dose_count
    return get_success_data(api_client.create_health_treatment(payload, VET))


def setup_withheld_animal(weight_kg=500.0, weighed_at="2026-04-20",
                          first_dose_on="2026-05-01", last_dose_on="2026-05-01",
                          im_days=28):
    """Clock 2026-05-01; herd + weighed animal + IM treatment that withholds.
    Returns (herd, animal_after_treatment, drug, treatment). Caller is responsible
    for having set the clock to 2026-05-01 if a different date is needed."""
    herd = create_herd()
    animal = create_weighed_animal(herd["id"], weight_kg, weighed_at=weighed_at)
    drug = create_drug(route_withdrawals={"INJECTION_IM": im_days})
    treatment = treat_animal(
        animal["id"], drug["id"], route="INJECTION_IM",
        first_dose_on=first_dose_on, last_dose_on=last_dose_on,
    )
    animal = get_success_data(api_client.get_animal(animal["id"], HM))
    return herd, animal, drug, treatment


# --------------------------------------------------------------------------
# Tier 3: sale-lot shortcuts
# --------------------------------------------------------------------------
def create_sale_lot(herd_id, channel="AUCTION", pencil_shrink_pct=0,
                    commission_pct=0.05):
    """Open a sale lot. Returns the SaleLot dict (carries version)."""
    payload = {
        "herd_id": herd_id,
        "channel": channel,
        "pencil_shrink_pct": pencil_shrink_pct,
        "commission_pct": commission_pct,
    }
    return get_success_data(api_client.create_sale_lot(payload, CLERK))


def add_ticket(lot_id, animal_id, gross_weight_kg, expected_sale_lot_version):
    """Attach a weight ticket. Returns the WeightTicket dict."""
    payload = {
        "animal_id": animal_id,
        "gross_weight_kg": gross_weight_kg,
        "expected_sale_lot_version": expected_sale_lot_version,
    }
    return get_success_data(api_client.add_ticket(lot_id, payload, CLERK))


def setup_lot_with_one_ticket(herd_id, animal_id, gross_weight_kg,
                              channel="AUCTION", pencil_shrink_pct=0,
                              commission_pct=0.05):
    """Open a lot and attach one ticket for animal_id.
    Returns (lot, ticket). Lot version is read from the create response."""
    lot = create_sale_lot(
        herd_id, channel=channel, pencil_shrink_pct=pencil_shrink_pct,
        commission_pct=commission_pct,
    )
    ticket = add_ticket(lot["id"], animal_id, gross_weight_kg, lot["version"])
    return lot, ticket


# --------------------------------------------------------------------------
# Tier 3: breeding-record shortcuts
# --------------------------------------------------------------------------
def create_breeding_record(dam_animal_id, bred_on="2026-02-01", sire_animal_id=None):
    """Open a breeding record. Returns the BreedingRecord dict."""
    payload = {"dam_animal_id": dam_animal_id, "bred_on": bred_on}
    if sire_animal_id is not None:
        payload["sire_animal_id"] = sire_animal_id
    return get_success_data(api_client.create_breeding_record(payload, HM))


def transition_breeding(record_id, to_status, headers=HM, **extra):
    """Drive a breeding record transition. Returns the BreedingRecord dict."""
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_breeding_record(record_id, payload, headers)
    )


def setup_confirmed_pregnant_record(species="CATTLE", bred_on="2026-02-01"):
    """Herd + FEMALE dam + breeding record taken OPEN->BRED->CONFIRMED_PREGNANT.
    Returns (herd, dam, record). Note: CONFIRMED_PREGNANT requires Veterinarian."""
    herd = create_herd(species=species)
    dam = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01",
                        birth_weight_kg=42.0)
    record = create_breeding_record(dam["id"], bred_on=bred_on)
    transition_breeding(record["id"], "BRED", headers=HM)
    record = transition_breeding(record["id"], "CONFIRMED_PREGNANT", headers=VET)
    return herd, dam, record


# --------------------------------------------------------------------------
# Tier 3: mortality shortcuts
# --------------------------------------------------------------------------
def record_mortality(animal_id, died_on="2026-03-30", cause="DISEASE",
                     disposal_method=None):
    """Record a death. Returns the MortalityRecord dict."""
    payload = {"animal_id": animal_id, "died_on": died_on, "cause": cause}
    if disposal_method is not None:
        payload["disposal_method"] = disposal_method
    return get_success_data(api_client.create_mortality_record(payload, HM))
