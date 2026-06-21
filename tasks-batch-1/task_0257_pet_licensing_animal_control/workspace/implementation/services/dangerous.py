"""DangerousDogCase state machine + designation cascade (PRD §3.7, SCAFFOLD §1.2).

States: REPORTED, INVESTIGATING, DESIGNATED, APPEALED, OVERTURNED, DISMISSED.
(OVERTURNED, DISMISSED terminal.)
"""
from db import db
from errors import err
from services import calc
from services.core import append_audit, licenses_of_pet, touch


def _actor():
    from flask import request
    return request.headers.get("X-User-Role", "")


def investigate(case):
    if case["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", "Case is not REPORTED.")
    case["status"] = "INVESTIGATING"
    touch(case)
    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_INVESTIGATION_STARTED", _actor())


def designate(case):
    if case["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "Case is not INVESTIGATING.")
    # no other DESIGNATED case for the same pet
    for other in db.dangerous_dog_cases.values():
        if (other["id"] != case["id"] and other["pet_id"] == case["pet_id"]
                and other["status"] == "DESIGNATED"):
            raise err("ERR_ALREADY_DESIGNATED", "Pet already has a DESIGNATED case.")

    case["surcharge_cents"] = calc.dangerous_surcharge(case["severity"])
    case["status"] = "DESIGNATED"
    touch(case)

    # cascade hop 1: pet.is_dangerous = true
    pet = db.pets[case["pet_id"]]
    pet["is_dangerous"] = True
    touch(pet)

    # cascade hop 2: add surcharge to each ACTIVE/GRACE license of the pet
    for lic in licenses_of_pet(case["pet_id"]):
        if lic["status"] in ("ACTIVE", "GRACE"):
            lic["final_fee_cents"] = lic["final_fee_cents"] + case["surcharge_cents"]
            touch(lic)

    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_DESIGNATED", _actor())


def dismiss(case):
    if case["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "Case is not INVESTIGATING.")
    case["status"] = "DISMISSED"
    touch(case)
    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_CASE_DISMISSED", _actor())


def appeal(case):
    if case["status"] != "DESIGNATED":
        raise err("ERR_INVALID_STATE", "Case is not DESIGNATED.")
    case["status"] = "APPEALED"
    touch(case)
    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_DESIGNATION_APPEALED", _actor())


def uphold(case):
    if case["status"] != "APPEALED":
        raise err("ERR_INVALID_STATE", "Case is not APPEALED.")
    case["status"] = "DESIGNATED"  # surcharge already applied; no double-apply
    touch(case)
    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_DESIGNATION_UPHELD", _actor())


def overturn(case):
    if case["status"] != "APPEALED":
        raise err("ERR_INVALID_STATE", "Case is not APPEALED.")
    case["status"] = "OVERTURNED"
    touch(case)

    # compensating reversal. hop 1: clear is_dangerous if no OTHER DESIGNATED case
    pet = db.pets[case["pet_id"]]
    other_designated = any(
        c["id"] != case["id"] and c["pet_id"] == case["pet_id"]
        and c["status"] == "DESIGNATED"
        for c in db.dangerous_dog_cases.values()
    )
    if not other_designated:
        pet["is_dangerous"] = False
        touch(pet)

    # hop 2: subtract this case's surcharge from each ACTIVE/GRACE license
    for lic in licenses_of_pet(case["pet_id"]):
        if lic["status"] in ("ACTIVE", "GRACE"):
            lic["final_fee_cents"] = lic["final_fee_cents"] - case["surcharge_cents"]
            touch(lic)

    append_audit("DANGEROUS_DOG_CASE", case["id"], "DOG_DESIGNATION_OVERTURNED", _actor())
