"""Cross-aggregate reference walks: BagLot -> PrintJob -> FilmRoll -> Run -> Line."""

from store import store


def recipe_of_run(run):
    return store.blend_recipes.get(run["blend_recipe_id"])


def product_of_recipe(recipe):
    if recipe is None:
        return None
    return store.products.get(recipe["product_id"])


def product_of_run(run):
    return product_of_recipe(recipe_of_run(run))


def line_of_run(run):
    return store.extrusion_lines.get(run["line_id"])


def run_of_roll(roll):
    return store.extrusion_runs.get(roll["extrusion_run_id"])


def roll_of_job(job):
    return store.film_rolls.get(job["film_roll_id"])


def plate_of_job(job):
    return store.plate_sets.get(job["plate_set_id"])


def press_of_job(job):
    return store.print_presses.get(job["press_id"])


def job_of_lot(lot):
    return store.print_jobs.get(lot["print_job_id"])


def product_of_lot(lot):
    return store.products.get(lot["product_id"])


def lot_chain(lot):
    """Return (job, roll, run, line, recipe, plate) for a bag lot; members may be None."""
    job = job_of_lot(lot)
    roll = roll_of_job(job) if job else None
    run = run_of_roll(roll) if roll else None
    line = line_of_run(run) if run else None
    recipe = recipe_of_run(run) if run else None
    plate = plate_of_job(job) if job else None
    return job, roll, run, line, recipe, plate


def rolls_of_run(run):
    return [r for r in store.sorted_values(store.film_rolls) if r["extrusion_run_id"] == run["id"]]


def runs_of_line(line):
    return [r for r in store.sorted_values(store.extrusion_runs) if r["line_id"] == line["id"]]


def rolls_of_line(line):
    out = []
    for run in runs_of_line(line):
        out.extend(rolls_of_run(run))
    return out


def runs_of_recipe(recipe):
    return [
        r
        for r in store.sorted_values(store.extrusion_runs)
        if r["blend_recipe_id"] == recipe["id"]
    ]


def jobs_of_plate(plate):
    return [
        j for j in store.sorted_values(store.print_jobs) if j["plate_set_id"] == plate["id"]
    ]


def transactions_of_pool(pool):
    return [
        t
        for t in store.sorted_values(store.regrind_transactions)
        if t["pool_id"] == pool["id"]
    ]


def transactions_of_run(run):
    return [
        t
        for t in store.sorted_values(store.regrind_transactions)
        if t.get("extrusion_run_id") == run["id"]
    ]


def dossiers_of_lot(lot):
    return [
        d
        for d in store.sorted_values(store.compliance_dossiers)
        if d["bag_lot_id"] == lot["id"]
    ]


def is_reversed(transaction):
    tid = transaction["id"]
    for other in store.regrind_transactions.values():
        if other.get("reverses_transaction_id") == tid:
            return True
    return False


def eligible_pool(polymer_family, food_contact_required):
    """The pool matching a polymer family and the product's food-contact status."""
    if polymer_family is None:
        return None
    wanted = "FOOD_CONTACT_ELIGIBLE" if food_contact_required else "NON_FOOD_ONLY"
    for pool in store.sorted_values(store.regrind_pools):
        if pool["polymer_family"] == polymer_family and pool["food_contact_status"] == wanted:
            return pool
    return None
