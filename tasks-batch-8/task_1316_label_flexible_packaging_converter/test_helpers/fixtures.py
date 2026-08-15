"""Composite setup helpers for multi-step test prerequisites.

Most claims require a full plant (customer, approved artwork, substrate, ink,
die, press) plus a job walked part-way down its pipeline. These helpers build
that state from PRD-declared endpoints only. They use get_success_data()
(lenient validator) so setup failures surface as clear "setup failed" errors
instead of confusing assertion failures.

All roles are opaque per PRD §2.1, so the shared TEST_USERS headers are used
throughout.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_artwork_version_payload,
    create_color_measurement_payload,
    create_compliance_letter_payload,
    create_customer_payload,
    create_die_payload,
    create_ink_recipe_payload,
    create_job_payload,
    create_press_payload,
    create_rewind_roll_payload,
    create_substrate_payload,
)
from .test_users import TEST_USERS

EST = TEST_USERS["estimator_headers"]
PREPRESS = TEST_USERS["prepress_operator_headers"]
PRESS_OP = TEST_USERS["press_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


# ─── Tier 0: single-entity creators ────────────────────


def create_customer(**overrides) -> dict:
    """Create a customer (Estimator). Returns the customer."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), EST))


def register_artwork(customer_id: str, approve: bool = True,
                     submit: bool = True, **overrides) -> dict:
    """Register an artwork revision (born DRAFT), optionally submit it, and
    optionally approve it. Returns the revision as of its last transition.
    submit=False leaves it DRAFT; submit=True + approve=False leaves it
    SUBMITTED; approve=True walks it to APPROVED."""
    artwork = get_success_data(api_client.create_artwork_version(
        customer_id, create_artwork_version_payload(**overrides), PREPRESS))
    if submit:
        artwork = get_success_data(
            api_client.submit_artwork(customer_id, artwork["id"], PREPRESS))
    if approve:
        artwork = get_success_data(
            api_client.approve_artwork(customer_id, artwork["id"], PREPRESS))
    return artwork


def create_substrate(**overrides) -> dict:
    return get_success_data(
        api_client.create_substrate(create_substrate_payload(**overrides),
                                    EST))


def create_ink_recipe(**overrides) -> dict:
    return get_success_data(
        api_client.create_ink_recipe(create_ink_recipe_payload(**overrides),
                                     EST))


def create_shelf_die(**overrides) -> dict:
    """Register an existing die already on the shelf (no tooling charge)."""
    return get_success_data(
        api_client.create_die(create_die_payload(**overrides), EST))


def create_purchased_die(**overrides) -> dict:
    """Order a new die from the toolmaker (carries the new-die charge)."""
    return get_success_data(
        api_client.purchase_die(create_die_payload(**overrides), EST))


def create_press(**overrides) -> dict:
    return get_success_data(
        api_client.create_press(create_press_payload(**overrides), EST))


# ─── Tier 1: plant assembly ────────────────────────────


def setup_plant(**cfg) -> dict:
    """Customer + artwork + substrate + ink recipe + die + press.

    Recognized cfg keys (defaults in parentheses):
      account_name ("Chain Co"), credit_hold (False)
      artwork_code ("AW-CHAIN"), color_count (2), plate_set_cost_cents (120000),
      approve_artwork (True)
      substrate_code ("SUB-CHAIN"), width_mm (1000), cost_per_msq_cents (40)
      recipe_code ("INK-CHAIN"), cost_per_lb_cents (300)
      die_mode ("shelf"|"purchase"), die_code ("D-CHAIN"), cavities_across (4)
      press_code ("P-CHAIN"), station_count (4), setup_waste_ft (300),
      run_waste_pct_numerator (5)
      food_contact (False) — shortcut setting substrate food_contact_certified,
        ink food_contact_compliant (the job flag is set in create_job_for)
      substrate_food_certified / ink_food_compliant — explicit overrides
    """
    food_contact = cfg.get("food_contact", False)
    customer = create_customer(
        account_name=cfg.get("account_name", "Chain Co"),
        credit_hold=cfg.get("credit_hold", False),
    )
    artwork = register_artwork(
        customer["id"],
        approve=cfg.get("approve_artwork", True),
        submit=cfg.get("submit_artwork", True),
        artwork_code=cfg.get("artwork_code", "AW-CHAIN"),
        revision_no=cfg.get("revision_no", 1),
        color_count=cfg.get("color_count", 2),
        plate_set_cost_cents=cfg.get("plate_set_cost_cents", 120000),
    )
    substrate = create_substrate(
        substrate_code=cfg.get("substrate_code", "SUB-CHAIN"),
        width_mm=cfg.get("width_mm", 1000),
        cost_per_msq_cents=cfg.get("cost_per_msq_cents", 40),
        food_contact_certified=cfg.get("substrate_food_certified", food_contact),
    )
    ink = create_ink_recipe(
        recipe_code=cfg.get("recipe_code", "INK-CHAIN"),
        cost_per_lb_cents=cfg.get("cost_per_lb_cents", 300),
        food_contact_compliant=cfg.get("ink_food_compliant", food_contact),
    )
    die_factory = create_purchased_die if cfg.get("die_mode") == "purchase" \
        else create_shelf_die
    die = die_factory(
        die_code=cfg.get("die_code", "D-CHAIN"),
        shape_description=cfg.get("shape_description", "rect 76x50"),
        cavities_across=cfg.get("cavities_across", 4),
    )
    press = create_press(
        press_code=cfg.get("press_code", "P-CHAIN"),
        station_count=cfg.get("station_count", 4),
        setup_waste_ft=cfg.get("setup_waste_ft", 300),
        run_waste_pct_numerator=cfg.get("run_waste_pct_numerator", 5),
    )
    return {
        "customer": customer,
        "artwork": artwork,
        "substrate": substrate,
        "ink": ink,
        "die": die,
        "press": press,
    }


# ─── Tier 2: job pipeline steps ────────────────────────


def create_job_for(plant: dict, **overrides) -> dict:
    """Create a job (quote) under the plant's customer. Returns QUOTED job."""
    cfg = plant.get("cfg", {})
    food_contact = cfg.get("food_contact", False)
    payload = create_job_payload(
        plant["artwork"]["id"], plant["substrate"]["id"], plant["ink"]["id"],
        plant["die"]["id"], plant["press"]["id"], **overrides)
    if "requires_food_contact_letter" not in overrides and food_contact:
        payload["requires_food_contact_letter"] = True
    return get_success_data(
        api_client.create_job(plant["customer"]["id"], payload, EST))


def current_artwork_version(plant: dict) -> int:
    """Freshly observed version of the plant's artwork revision."""
    artwork = get_success_data(api_client.get_artwork_version(
        plant["customer"]["id"], plant["artwork"]["id"], EST))
    return artwork["version"]


def current_job_version(job_id: str) -> int:
    return get_success_data(api_client.get_job(job_id, EST))["version"]


def approve_job(job_id: str) -> dict:
    return get_success_data(api_client.approve_job(job_id, EST))


def release_job(job_id: str, expected_artwork_version: int) -> dict:
    return get_success_data(api_client.release_job(
        job_id, {"expected_artwork_version": expected_artwork_version}, EST))


def start_press(job_id: str) -> dict:
    return get_success_data(api_client.start_press(job_id, PRESS_OP))


def record_measurement(job_id: str, station_no: int = 1,
                       delta_e: float = 1.0) -> dict:
    return get_success_data(api_client.record_color_measurement(
        job_id,
        create_color_measurement_payload(station_no=station_no,
                                         delta_e=delta_e),
        PRESS_OP))


def judge_measurement(job_id: str, measurement_id: str,
                      verdict: str = "PASS") -> dict:
    return get_success_data(api_client.judge_color_measurement(
        job_id, measurement_id, {"verdict": verdict}, QM))


def complete_press(job_id: str, good_quantity_produced: int) -> dict:
    return get_success_data(api_client.complete_press(
        job_id, {"good_quantity_produced": good_quantity_produced}, PRESS_OP))


def record_roll(job_id: str, roll_seq: int, label_count: int,
                splice_count: int) -> dict:
    return get_success_data(api_client.record_rewind_roll(
        job_id,
        create_rewind_roll_payload(roll_seq=roll_seq, label_count=label_count,
                                   splice_count=splice_count),
        PRESS_OP))


def accept_roll(job_id: str, roll_id: str) -> dict:
    return get_success_data(api_client.accept_rewind_roll(job_id, roll_id, QM))


def reject_roll(job_id: str, roll_id: str) -> dict:
    return get_success_data(api_client.reject_rewind_roll(job_id, roll_id, QM))


def issue_letter(job_id: str, **overrides) -> dict:
    return get_success_data(api_client.issue_compliance_letter(
        job_id, create_compliance_letter_payload(**overrides), QM))


def ship_job(job_id: str, expected_job_version: int) -> dict:
    return get_success_data(api_client.ship_job(
        job_id, {"expected_job_version": expected_job_version}, QM))


def get_job(job_id: str) -> dict:
    return get_success_data(api_client.get_job(job_id, EST))


def get_die(die_id: str) -> dict:
    return get_success_data(api_client.get_die(die_id, EST))


def retire_die(die_id: str) -> dict:
    return get_success_data(api_client.retire_die(die_id, EST))


def pass_color_gate(job_id: str, station_no: int = 1,
                    delta_e: float = 1.0) -> dict:
    """Record one measurement and judge it PASS. Returns the measurement."""
    measurement = record_measurement(job_id, station_no=station_no,
                                     delta_e=delta_e)
    return judge_measurement(job_id, measurement["id"], "PASS")


def run_press_cycle(job_id: str, good_quantity_produced: int,
                    delta_e: float = 1.0) -> dict:
    """ON_PRESS -> PRINTED: one PASSed measurement, then complete-press."""
    pass_color_gate(job_id, delta_e=delta_e)
    return complete_press(job_id, good_quantity_produced)


# ─── Tier 3: full lifecycle driver ─────────────────────


def job_chain(stop_at: str = "QUOTED", **cfg) -> dict:
    """Build a plant and walk a job down its pipeline to `stop_at`.

    stop_at ladder: QUOTED -> APPROVED -> RELEASED -> ON_PRESS -> PRINTED
    -> REWOUND -> SHIPPED. Requires the artwork to be approved (default) for
    RELEASED and beyond.

    Extra cfg keys beyond setup_plant's:
      quantity_ordered (1000), repeat_length_mm (76),
      rewind_max_rolls (2), max_splices_per_roll (1),
      requires_food_contact_letter (defaults to food_contact)
      good_quantity_produced (defaults to quantity_ordered)
      delta_e (1.0), station_no (1)
      rolls — list of {"label_count": int, "splice_count": int};
              default one roll with the full good quantity and 0 splices
      roll_action — "accept" (default) applied to every recorded roll
      issue_letter (False) — issue a FOOD_CONTACT letter before shipping
    """
    plant = setup_plant(**cfg)
    plant["cfg"] = cfg
    job = create_job_for(
        plant,
        quantity_ordered=cfg.get("quantity_ordered", 1000),
        repeat_length_mm=cfg.get("repeat_length_mm", 76),
        rewind_max_rolls=cfg.get("rewind_max_rolls", 2),
        max_splices_per_roll=cfg.get("max_splices_per_roll", 1),
        **({"requires_food_contact_letter": cfg["requires_food_contact_letter"]}
           if "requires_food_contact_letter" in cfg else {}),
    )
    result = {"plant": plant, "job": job, "measurements": [], "rolls": [],
              "letter": None}
    if stop_at == "QUOTED":
        return result

    result["job"] = approve_job(job["id"])
    if stop_at == "APPROVED":
        return result

    av_version = current_artwork_version(plant)
    result["job"] = release_job(job["id"], av_version)
    if stop_at == "RELEASED":
        return result

    result["job"] = start_press(job["id"])
    if stop_at == "ON_PRESS":
        return result

    good_qty = cfg.get("good_quantity_produced",
                       cfg.get("quantity_ordered", 1000))
    measurement = pass_color_gate(
        job["id"], station_no=cfg.get("station_no", 1),
        delta_e=cfg.get("delta_e", 1.0))
    result["measurements"].append(measurement)
    result["job"] = complete_press(job["id"], good_qty)
    if stop_at == "PRINTED":
        return result

    roll_specs = cfg.get("rolls")
    if roll_specs is None:
        roll_specs = [{"label_count": good_qty, "splice_count": 0}]
    # PRD 3.7: rolls are recorded while the job is PRINTED, and the automatic
    # PRINTED -> REWOUND advance fires after a judgment once every recorded
    # roll has been judged. Interleaving record/accept would advance the job
    # after the first accept and make later recordings fail — so record all
    # rolls first, then judge them.
    recorded = [
        record_roll(job["id"], idx, spec["label_count"],
                    spec.get("splice_count", 0))
        for idx, spec in enumerate(roll_specs, start=1)
    ]
    for roll in recorded:
        if cfg.get("roll_action", "accept") == "accept":
            roll = accept_roll(job["id"], roll["id"])
        result["rolls"].append(roll)
    result["job"] = get_job(job["id"])
    if stop_at == "REWOUND":
        return result

    if cfg.get("issue_letter", False):
        result["letter"] = issue_letter(job["id"])

    result["job"] = ship_job(job["id"], current_job_version(job["id"]))
    return result
