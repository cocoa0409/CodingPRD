"""Shared lookups, mutation helpers, and cascading side effects (PRD 2.6, 3.x)."""
from db import DB, now_iso
from errors import ApiError


def _get(collection, key, label):
    entity = DB[collection].get(key)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return entity


def get_customer(customer_id):
    return _get("customers", customer_id, "Customer")


def get_substrate(substrate_id):
    return _get("substrates", substrate_id, "Substrate")


def get_ink_recipe(recipe_id):
    return _get("ink_recipes", recipe_id, "Ink recipe")


def get_die(die_id):
    return _get("dies", die_id, "Die")


def get_press(press_id):
    return _get("presses", press_id, "Press")


def get_job(job_id):
    return _get("jobs", job_id, "Job")


def get_artwork(customer_id, artwork_id):
    """Nested lookup: the revision must belong to the customer in the path."""
    art = DB["artworks"].get(artwork_id)
    if art is None or art["customer_id"] != customer_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Artwork revision not found")
    return art


def get_measurement(job_id, measurement_id):
    m = DB["measurements"].get(measurement_id)
    if m is None or m["job_id"] != job_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Color measurement not found")
    return m


def get_roll(job_id, roll_id):
    r = DB["rolls"].get(roll_id)
    if r is None or r["job_id"] != job_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Rewind roll not found")
    return r


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def sorted_created(items):
    """List endpoints sort by created_at ascending (PRD 2.3)."""
    return sorted(items, key=lambda e: e["created_at"])


def release_die_charge(job):
    """Compensating die-charge release (PRD 3.8): the charge follows the die.

    If this job billed the die's tooling charge and is still the die's billing
    job, the die returns to the un-billed state and the job's applied charge
    is released.
    """
    if job["die_charge_applied_cents"] > 0:
        die = DB["dies"].get(job["die_id"])
        if die is not None and die["charge_collected"]:
            die["charge_collected"] = False
            touch(die)
        job["die_charge_applied_cents"] = 0


def cancel_job(job):
    """Cancel a job and release any die charge billed to it (PRD 3.8)."""
    release_die_charge(job)
    job["status"] = "CANCELLED"
    touch(job)


def approve_artwork(art):
    """Approve a SUBMITTED revision; supersession cascade (PRD 3.3).

    Any other APPROVED revision of the same (customer_id, artwork_code) flips
    to OBSOLETE; every QUOTED/APPROVED/RELEASED job still referencing the
    now-OBSOLETE revision flips to CANCELLED with die-charge release.
    """
    art["status"] = "APPROVED"
    touch(art)
    for other in list(DB["artworks"].values()):
        if (
            other["id"] != art["id"]
            and other["customer_id"] == art["customer_id"]
            and other["artwork_code"] == art["artwork_code"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "OBSOLETE"
            touch(other)
            for job in list(DB["jobs"].values()):
                if job["artwork_version_id"] == other["id"] and job["status"] in (
                    "QUOTED",
                    "APPROVED",
                    "RELEASED",
                ):
                    cancel_job(job)


def maybe_advance_to_rewound(job):
    """Auto-transition PRINTED -> REWOUND (PRD 3.7): when every recorded roll
    has been judged (ACCEPTED or REJECTED) and at least one is ACCEPTED."""
    if job["status"] != "PRINTED":
        return
    rolls = [r for r in DB["rolls"].values() if r["job_id"] == job["id"]]
    if (
        rolls
        and all(r["status"] in ("ACCEPTED", "REJECTED") for r in rolls)
        and any(r["status"] == "ACCEPTED" for r in rolls)
    ):
        job["status"] = "REWOUND"
        touch(job)
