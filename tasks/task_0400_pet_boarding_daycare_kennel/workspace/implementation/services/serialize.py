"""Public serialization of each entity. Returns a copy so internal bookkeeping
keys never leak. Field sets follow scaffold §1.1 and PRD §2.4.

VaccinationRecord and PackageRedemption carry only id + created_at (no
updated_at / version) per PRD §2.4.
"""

_FACILITY = ["id", "name", "daycare_cutoff_time", "deposit_policy",
             "overbook_grace", "current_date", "created_at", "updated_at", "version"]
_OWNER = ["id", "facility_id", "full_name", "email", "phone", "status",
          "wallet_credit_cents", "created_at", "updated_at", "version"]
_PET = ["id", "owner_id", "facility_id", "name", "species", "weight_kg",
        "temperament", "size_class", "vaccination_status", "temperament_clearance",
        "created_at", "updated_at", "version"]
_VACC = ["id", "pet_id", "vaccine", "administered_on", "expires_on",
         "superseded", "created_at"]
_RUN = ["id", "facility_id", "label", "kind", "size_class", "daycare_capacity",
        "status", "created_at", "updated_at", "version"]
_RESERVATION = ["id", "facility_id", "pet_id", "owner_id", "package_id",
                "service_type", "start_date", "end_date", "nights", "care_plan",
                "belongings", "incidents", "deposit_cents", "deposit_paid_cents",
                "total_cents", "refund_cents", "redeemed_credit", "status",
                "created_at", "updated_at", "version"]
_ASSIGNMENT = ["id", "reservation_id", "run_id", "window_start_date",
               "window_end_date", "status", "created_at", "updated_at", "version"]
_ADDON = ["id", "reservation_id", "kind", "scheduled_date", "price_cents",
          "status", "created_at", "updated_at", "version"]
_PACKAGE = ["id", "owner_id", "facility_id", "tier", "credits_total",
            "credits_remaining", "cycle_start_date", "auto_renew", "status",
            "created_at", "updated_at", "version"]
_REDEMPTION = ["id", "package_id", "reservation_id", "credits_used",
               "redeemed_on", "reversed", "created_at"]


def _pick(entity, keys):
    return {k: entity.get(k) for k in keys if k in entity}


def facility(e):
    return _pick(e, _FACILITY)


def owner(e):
    return _pick(e, _OWNER)


def pet(e):
    return _pick(e, _PET)


def vaccination(e):
    return _pick(e, _VACC)


def run(e):
    return _pick(e, _RUN)


def reservation(e):
    return _pick(e, _RESERVATION)


def assignment(e):
    return _pick(e, _ASSIGNMENT)


def addon(e):
    return _pick(e, _ADDON)


def package(e):
    return _pick(e, _PACKAGE)


def redemption(e):
    return _pick(e, _REDEMPTION)
