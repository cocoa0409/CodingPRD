"""Payload factories — one per entity, input fields only.

Required vs optional fields follow the PRD: optional/defaulted fields are
omitted unless overridden. NPIs default to a per-call unique value to avoid
collisions on the unique-npi constraint.
"""
import itertools

_npi_counter = itertools.count(1)


def create_gene_payload(symbol="BRCA1", **overrides) -> dict:
    payload = {"symbol": symbol}
    payload.update(overrides)
    return payload


def create_panel_payload(name="Test Panel", list_price_cents=40000, **overrides) -> dict:
    payload = {"name": name, "list_price_cents": list_price_cents}
    payload.update(overrides)
    return payload


def add_panel_gene_payload(gene_id, **overrides) -> dict:
    payload = {"gene_id": gene_id}
    payload.update(overrides)
    return payload


def create_provider_payload(npi=None, full_name="Dr Test", **overrides) -> dict:
    if npi is None:
        npi = f"{1000000000 + next(_npi_counter):010d}"
    payload = {"npi": npi, "full_name": full_name}
    payload.update(overrides)
    return payload


def create_test_order_payload(panel_id, ordering_provider_id,
                              patient_mrn="MRN-TEST", patient_dob="1990-01-01",
                              **overrides) -> dict:
    payload = {
        "patient_mrn": patient_mrn,
        "patient_dob": patient_dob,
        "panel_id": panel_id,
        "ordering_provider_id": ordering_provider_id,
    }
    payload.update(overrides)
    return payload


def create_requisition_payload(clinical_indication="dx",
                              insurance_payer="SELF_PAY", **overrides) -> dict:
    payload = {
        "clinical_indication": clinical_indication,
        "insurance_payer": insurance_payer,
    }
    payload.update(overrides)
    return payload


def create_consent_payload(incidental_findings_opt_in=True,
                           signed_by_name="Patient", **overrides) -> dict:
    payload = {
        "incidental_findings_opt_in": incidental_findings_opt_in,
        "signed_by_name": signed_by_name,
    }
    payload.update(overrides)
    return payload


def create_specimen_payload(specimen_type="BLOOD",
                            collected_at="2026-06-18T00:00:00.000Z",
                            quantity_ng=80, **overrides) -> dict:
    payload = {
        "specimen_type": specimen_type,
        "collected_at": collected_at,
        "quantity_ng": quantity_ng,
    }
    payload.update(overrides)
    return payload


def create_variant_payload(gene_id, hgvs="c.100A>T", **overrides) -> dict:
    payload = {"gene_id": gene_id, "hgvs": hgvs}
    payload.update(overrides)
    return payload


def classify_payload(classification, **overrides) -> dict:
    payload = {"classification": classification}
    payload.update(overrides)
    return payload


def auth_decision_payload(decision, allowed_amount_cents=None, **overrides) -> dict:
    payload = {"decision": decision}
    if allowed_amount_cents is not None:
        payload["allowed_amount_cents"] = allowed_amount_cents
    payload.update(overrides)
    return payload


def collect_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_sequencer_payload(instrument_name="NovaSeq", **overrides) -> dict:
    payload = {"instrument_name": instrument_name}
    payload.update(overrides)
    return payload


def schedule_run_payload(test_order_id, window_start, window_end, **overrides) -> dict:
    payload = {
        "test_order_id": test_order_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_counselor_payload(counselor_name="GC One", **overrides) -> dict:
    payload = {"counselor_name": counselor_name}
    payload.update(overrides)
    return payload


def create_referral_payload(counselor_id, reason="PATIENT_REQUEST", **overrides) -> dict:
    payload = {"counselor_id": counselor_id, "reason": reason}
    payload.update(overrides)
    return payload


def schedule_referral_payload(slot_start, slot_end, **overrides) -> dict:
    payload = {"slot_start": slot_start, "slot_end": slot_end}
    payload.update(overrides)
    return payload


def amend_payload(expected_test_order_version, **overrides) -> dict:
    payload = {"expected_test_order_version": expected_test_order_version}
    payload.update(overrides)
    return payload
