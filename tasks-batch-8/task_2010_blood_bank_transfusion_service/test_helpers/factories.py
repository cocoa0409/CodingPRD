"""Payload factories — one per creatable resource, input fields only."""

DEFAULT_COLLECTED_AT = "2026-08-01T00:00:00Z"


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": "M-1001",
        "full_name": "Alex Doe",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": "SanguiServe",
        "license_number": "LIC-100",
        "default_lead_time_hours": 48,
    }
    defaults.update(overrides)
    return defaults


def supplier_order_line(product_type="RBC", abo_type="O", rh_type="NEG",
                        quantity=1) -> dict:
    return {
        "product_type": product_type,
        "abo_type": abo_type,
        "rh_type": rh_type,
        "quantity": quantity,
    }


def create_supplier_order_payload(supplier_id, lines, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "is_emergency": False,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def receive_unit_descriptor(unit_number, **overrides) -> dict:
    defaults = {
        "unit_number": unit_number,
        "product_type": "RBC",
        "abo_type": "O",
        "rh_type": "NEG",
        "volume_ml": 300,
        "collected_at": DEFAULT_COLLECTED_AT,
        "donor_id": "D-500",
        "lot_number": "LOT-1",
        "antigen_negative": [],
    }
    defaults.update(overrides)
    return defaults


def receive_payload(units) -> dict:
    return {"units": units}


def create_type_and_screen_payload(patient_id, specimen_collected_at,
                                   expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "specimen_collected_at": specimen_collected_at,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def ts_result_payload(abo_result="A", rh_result="POS", antibody_screen="NEGATIVE",
                      antibody_identifications=None, **overrides) -> dict:
    defaults = {
        "abo_result": abo_result,
        "rh_result": rh_result,
        "antibody_screen": antibody_screen,
        "antibody_identifications": (
            [] if antibody_identifications is None else antibody_identifications),
    }
    defaults.update(overrides)
    return defaults


def reject_specimen_payload(reason="hemolyzed specimen") -> dict:
    return {"reason": reason}


def create_transfusion_order_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "product_type": "RBC",
        "units_requested": 1,
        "urgency": "ROUTINE",
        "indication_code": "ANEMIA",
    }
    defaults.update(overrides)
    return defaults


def reject_order_payload(rejection_reason="duplicate order") -> dict:
    return {"rejection_reason": rejection_reason}


def cancel_order_payload(cancel_reason="order entry error") -> dict:
    return {"cancel_reason": cancel_reason}


def create_crossmatch_payload(order_id, unit_id=None) -> dict:
    payload = {"order_id": order_id}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    return payload


def crossmatch_result_payload(result="COMPATIBLE") -> dict:
    return {"result": result}


def create_issue_record_payload(order_id, verified_by_user_id, unit_id=None,
                                is_emergency_release=None,
                                emergency_justification=None) -> dict:
    payload = {"order_id": order_id, "verified_by_user_id": verified_by_user_id}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if is_emergency_release is not None:
        payload["is_emergency_release"] = is_emergency_release
    if emergency_justification is not None:
        payload["emergency_justification"] = emergency_justification
    return payload


def return_issue_payload(seal_intact=True, temperature_excursion=False) -> dict:
    return {"seal_intact": seal_intact,
            "temperature_excursion": temperature_excursion}


def create_mtp_activation_payload(patient_id,
                                  activation_reason="trauma bay hemorrhage protocol"
                                  ) -> dict:
    return {"patient_id": patient_id, "activation_reason": activation_reason}


def dispatch_pack_payload(verified_by_user_id="tech-b") -> dict:
    return {"verified_by_user_id": verified_by_user_id}


def create_reaction_payload(issue_record_id, reaction_type="SEPTIC",
                            severity="LIFE_THREATENING", symptoms=None) -> dict:
    payload = {"issue_record_id": issue_record_id,
               "reaction_type": reaction_type, "severity": severity}
    if symptoms is not None:
        payload["symptoms"] = symptoms
    return payload


def workup_payload(clerical_check_passed=True, dat_result="NEGATIVE",
                   hemolysis_present=False) -> dict:
    return {"clerical_check_passed": clerical_check_passed,
            "dat_result": dat_result, "hemolysis_present": hemolysis_present}


def conclude_payload(conclusion="CONFIRMED", final_classification=None) -> dict:
    payload = {"conclusion": conclusion}
    if final_classification is not None:
        payload["final_classification"] = final_classification
    return payload


def create_recall_case_payload(scope_type="DONOR", reason="donor deferral notice",
                               disposition="DESTRUCTION", donor_id=None,
                               lot_number=None, unit_id=None,
                               implicated_since=None) -> dict:
    payload = {"scope_type": scope_type, "reason": reason, "disposition": disposition}
    if donor_id is not None:
        payload["donor_id"] = donor_id
    if lot_number is not None:
        payload["lot_number"] = lot_number
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if implicated_since is not None:
        payload["implicated_since"] = implicated_since
    return payload


def record_notification_payload(issue_record_id) -> dict:
    return {"issue_record_id": issue_record_id}


def create_par_level_policy_payload(product_type="RBC", abo_type="O", rh_type="NEG",
                                    watch_threshold=6, shortage_threshold=4,
                                    critical_threshold=2,
                                    min_shelf_life_hours=4, **overrides) -> dict:
    defaults = {
        "product_type": product_type,
        "abo_type": abo_type,
        "rh_type": rh_type,
        "watch_threshold": watch_threshold,
        "shortage_threshold": shortage_threshold,
        "critical_threshold": critical_threshold,
        "min_shelf_life_hours": min_shelf_life_hours,
    }
    defaults.update(overrides)
    return defaults


def update_par_level_policy_payload(expected_policy_version, **overrides) -> dict:
    defaults = {"expected_policy_version": expected_policy_version}
    defaults.update(overrides)
    return defaults


def create_cooler_payload(cooler_tag="C-1") -> dict:
    return {"cooler_tag": cooler_tag}


def create_cooler_checkout_payload(cooler_id, planned_start, planned_end) -> dict:
    return {"cooler_id": cooler_id, "planned_start": planned_start,
            "planned_end": planned_end}
