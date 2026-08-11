"""Payload factories — one per created resource, input fields only."""

DEFAULTS = {
    "SHELTER_NAME": "Harbor Rescue",
    "PARTNER_NAME": "Cascade Partner Rescue",
    "SHELTER_STATE": "OR",
    "PARTNER_STATE": "WA",
    "VET_LICENSE": "VET-4410",
    "MICROCHIP": "985141000123456",
}


def organization_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SHELTER_NAME"],
        "org_type": "SHELTER",
        "state_code": DEFAULTS["SHELTER_STATE"],
    }
    payload.update(overrides)
    return payload


def partner_organization_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PARTNER_NAME"],
        "org_type": "PARTNER_RESCUE",
        "state_code": DEFAULTS["PARTNER_STATE"],
    }
    payload.update(overrides)
    return payload


def person_payload(full_name="Dana Reed", email="dana@example.test", **overrides) -> dict:
    payload = {"full_name": full_name, "email": email}
    payload.update(overrides)
    return payload


def permissive_adopter_payload(
    full_name="Dana Reed", email="dana@example.test", **overrides
) -> dict:
    """A household that satisfies every placement restriction by default."""
    payload = {
        "full_name": full_name,
        "email": email,
        "youngest_child_age_years": 99,
        "resident_cat_count": 0,
        "resident_dog_count": 0,
        "housing_type": "HOUSE",
        "has_fenced_yard": True,
    }
    payload.update(overrides)
    return payload


def driver_payload(
    full_name="Milo Frey", email="milo@example.test", license_number="CDL-8891", **overrides
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "driver_license_number": license_number,
    }
    payload.update(overrides)
    return payload


def animal_payload(organization_id, **overrides) -> dict:
    payload = {
        "name": "Rex",
        "species": "DOG",
        "size_class": "MEDIUM",
        "weight_lb": 40.0,
        "date_of_birth": "2022-01-01T00:00:00Z",
        "current_organization_id": organization_id,
    }
    payload.update(overrides)
    return payload


def litter_payload(label="Maple litter", **overrides) -> dict:
    payload = {"label": label}
    payload.update(overrides)
    return payload


def intake_record_payload(intake_type="OWNER_SURRENDER",
                          intake_datetime="2026-05-01T00:00:00Z", **overrides) -> dict:
    payload = {"intake_type": intake_type, "intake_datetime": intake_datetime}
    payload.update(overrides)
    return payload


def hold_payload(hold_type="MEDICAL", reason="post-op recovery", **overrides) -> dict:
    payload = {"hold_type": hold_type, "reason": reason}
    payload.update(overrides)
    return payload


def foster_home_payload(person_id, label="Voss Home", max_headcount=4, **overrides) -> dict:
    payload = {
        "person_id": person_id,
        "label": label,
        "max_headcount": max_headcount,
        "dog_slot_capacity": 2,
        "cat_slot_capacity": 0,
        "min_child_age_years": 99,
        "has_fenced_yard": True,
    }
    payload.update(overrides)
    return payload


def foster_application_payload(person_id, foster_home_id,
                               species_requested="DOG", **overrides) -> dict:
    payload = {
        "person_id": person_id,
        "foster_home_id": foster_home_id,
        "species_requested": species_requested,
    }
    payload.update(overrides)
    return payload


def foster_placement_payload(animal_id, foster_home_id, foster_application_id,
                             expected_foster_home_version, **overrides) -> dict:
    payload = {
        "animal_id": animal_id,
        "foster_home_id": foster_home_id,
        "foster_application_id": foster_application_id,
        "expected_foster_home_version": expected_foster_home_version,
        "count_basis": "INDIVIDUAL",
    }
    payload.update(overrides)
    return payload


def medical_record_payload(procedure_type="TREATMENT", expense_category="MEDICAL",
                           cost_cents=1000, scheduled_at="2026-05-01T00:00:00Z",
                           **overrides) -> dict:
    payload = {
        "procedure_type": procedure_type,
        "expense_category": expense_category,
        "cost_cents": cost_cents,
        "scheduled_at": scheduled_at,
        "funding_required": False,
    }
    payload.update(overrides)
    return payload


def health_certificate_payload(issued_at="2026-05-01T00:00:00Z",
                               destination_state="WA", **overrides) -> dict:
    payload = {
        "issued_at": issued_at,
        "destination_state": destination_state,
        "vet_license_number": DEFAULTS["VET_LICENSE"],
    }
    payload.update(overrides)
    return payload


def transport_run_payload(origin_organization_id, run_type="RESCUE_LEG",
                          origin_hub_code="HUB-A", destination_hub_code="HUB-B",
                          **overrides) -> dict:
    payload = {
        "origin_organization_id": origin_organization_id,
        "run_type": run_type,
        "origin_hub_code": origin_hub_code,
        "destination_hub_code": destination_hub_code,
    }
    payload.update(overrides)
    return payload


def transport_leg_payload(driver_person_id, sequence_no=1, origin_hub_code="HUB-A",
                          destination_hub_code="HUB-B",
                          scheduled_depart_at="2026-05-05T08:00:00Z",
                          scheduled_arrive_at="2026-05-05T12:00:00Z",
                          crate_capacity_units=10, weight_capacity_lb=400.0,
                          **overrides) -> dict:
    payload = {
        "driver_person_id": driver_person_id,
        "sequence_no": sequence_no,
        "origin_hub_code": origin_hub_code,
        "destination_hub_code": destination_hub_code,
        "scheduled_depart_at": scheduled_depart_at,
        "scheduled_arrive_at": scheduled_arrive_at,
        "crate_capacity_units": crate_capacity_units,
        "weight_capacity_lb": weight_capacity_lb,
    }
    payload.update(overrides)
    return payload


def manifest_entry_payload(animal_id, expected_leg_version, **overrides) -> dict:
    payload = {"animal_id": animal_id, "expected_leg_version": expected_leg_version}
    payload.update(overrides)
    return payload


def adoption_application_payload(animal_id, applicant_person_id, **overrides) -> dict:
    payload = {"animal_id": animal_id, "applicant_person_id": applicant_person_id}
    payload.update(overrides)
    return payload


def adoption_payload(adoption_application_id, expected_animal_version,
                     credit_application_order="CREDIT_FIRST", refund_basis="FEE_PAID",
                     deposit_basis="FLAT", **overrides) -> dict:
    payload = {
        "adoption_application_id": adoption_application_id,
        "expected_animal_version": expected_animal_version,
        "credit_application_order": credit_application_order,
        "refund_basis": refund_basis,
        "deposit_basis": deposit_basis,
    }
    payload.update(overrides)
    return payload


def outcome_payload(outcome_type="DIED_IN_CARE", **overrides) -> dict:
    payload = {"outcome_type": outcome_type}
    payload.update(overrides)
    return payload


def contribution_payload(donor_person_id, amount_cents, donor_reference,
                         **overrides) -> dict:
    payload = {
        "donor_person_id": donor_person_id,
        "amount_cents": amount_cents,
        "donor_reference": donor_reference,
    }
    payload.update(overrides)
    return payload


def partner_commitment_payload(organization_id, species="DOG", slots_total=2,
                               expires_at="2026-07-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "species": species,
        "slots_total": slots_total,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload
