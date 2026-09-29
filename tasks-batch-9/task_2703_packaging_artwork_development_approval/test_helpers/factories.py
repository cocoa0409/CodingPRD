"""Payload factories — one per entity, input fields only."""

import copy

from .constants import ELEMENT_ORDER

DEFAULTS = {
    "SKU_CODE": "SKU-1001",
    "PRODUCT_NAME": "Northgate Cocoa Carton 340g",
    "PRINTER_NAME": "Cascade Print Co",
    "SECOND_PRINTER_NAME": "Riverside Litho",
    "RECOVERY_LIABILITY_CAP_CENTS": 5000000,
    "PLATE_BUDGET_CENTS": 500000,
    "RUNOUT_START_UTC": "2026-08-03T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Mandatory element payloads
# ---------------------------------------------------------------------------

#: A `mandatory_elements` payload in which all seven sub-rules pass under
#: FDA_FOOD (which is the only scheme that also examines the US pair).
ALL_ELEMENTS_PASSING = {
    "net_contents": {
        "metric_value": 340,
        "metric_uom": "G",
        "us_value": 12,
        "us_uom": "OZ",
    },
    "ingredient_statement": {
        "text": "Cocoa mass, sugar, cocoa butter, natural vanilla flavouring",
        "descending_order": True,
    },
    "allergen_statement": {
        "text": "Contains milk and soya.",
        "allergen_emphasis": True,
    },
    "date_code_zone": {"zone_mm2": 300, "position": "BASE_PANEL"},
    "barcode": {"gtin14": "01234567890123"},
    "recycling_mark": {"present": True},
    "address_block": {
        "text": "Northgate Foods Ltd, 14 Harbour Road, Bristol BS1 4TR"
    },
}


def all_elements_passing(**overrides) -> dict:
    """Deep copy of the all-passing element payload, with sub-objects replaced."""
    payload = copy.deepcopy(ALL_ELEMENTS_PASSING)
    payload.update(copy.deepcopy(overrides))
    return payload


def elements_without(*element_keys) -> dict:
    """All-passing payload with the named sub-objects removed entirely.

    An absent sub-object is a FAIL whose detail reads ELEMENT_ABSENT.
    """
    payload = copy.deepcopy(ALL_ELEMENTS_PASSING)
    for key in element_keys:
        payload.pop(key, None)
    return payload


ELEMENT_KEY_BY_CODE = {
    "NET_CONTENTS": "net_contents",
    "INGREDIENT_STATEMENT": "ingredient_statement",
    "ALLERGEN_STATEMENT": "allergen_statement",
    "DATE_CODE_ZONE": "date_code_zone",
    "BARCODE": "barcode",
    "RECYCLING_MARK": "recycling_mark",
    "ADDRESS_BLOCK": "address_block",
}


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


def create_brief_payload(**overrides) -> dict:
    defaults = {
        "sku_code": DEFAULTS["SKU_CODE"],
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "regulatory_scheme": "FDA_FOOD",
        "market_codes": ["US"],
        "language_codes": ["en"],
        "required_element_codes": list(ELEMENT_ORDER),
        "structural_spec": {
            "component_type": "CARTON",
            "dimensions_mm": {"l": 120, "w": 60, "h": 200},
            "substrate_class": "COATED_PAPER",
            "print_process": "OFFSET",
        },
        "net_contents_declaration": {
            "metric_value": 340,
            "metric_uom": "G",
            "us_value": 12,
            "us_uom": "OZ",
        },
    }
    defaults.update(overrides)
    return defaults


def brief_decision_payload(decision="APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "APPROVED":
        payload["review_note"] = "Scheme and net contents confirmed."
    else:
        payload["review_note"] = "Net contents declaration is inconsistent."
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Marketing claim
# ---------------------------------------------------------------------------


def create_marketing_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_code": "CLM-NAS-01",
        "claim_text": "No artificial sweeteners.",
        "claim_type": "FREE_FROM",
        "market_code": "US",
        "substantiation_ref": "DOSSIER-NAS-2026-01",
    }
    defaults.update(overrides)
    return defaults


def clearance_payload(
    decision="CLEARED",
    cleared_from_utc="2026-09-01T00:00:00Z",
    cleared_until_utc="2026-10-01T00:00:00Z",
    **overrides,
) -> dict:
    if decision == "CLEARED":
        payload = {
            "decision": "CLEARED",
            "cleared_from_utc": cleared_from_utc,
            "cleared_until_utc": cleared_until_utc,
        }
    else:
        payload = {
            "decision": "REJECTED",
            "rejection_reason": "Substantiation dossier retracted by the supplier.",
        }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Artwork asset and version
# ---------------------------------------------------------------------------


def create_artwork_asset_payload(brief_id, **overrides) -> dict:
    defaults = {
        "brief_id": brief_id,
        "market_code": "US",
        "language_codes": ["en"],
        "component_type": "CARTON",
        "substrate_class": "COATED_PAPER",
        "brand_critical_color": False,
        "plate_budget_cents": DEFAULTS["PLATE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_artwork_version_payload(expected_artwork_asset_version, **overrides) -> dict:
    defaults = {
        "expected_artwork_asset_version": expected_artwork_asset_version,
        "reason_for_change_code": "NEW_LAUNCH",
        "change_description": "First production artwork for the Northgate cocoa carton.",
        "mandatory_elements": all_elements_passing(),
    }
    defaults.update(overrides)
    return defaults


def verify_elements_payload(**overrides) -> dict:
    payload = {"verification_note": "Verification run on the current draft."}
    payload.update(overrides)
    return payload


def submit_payload(**overrides) -> dict:
    payload = {"submit_note": "Routing pass opened."}
    payload.update(overrides)
    return payload


def revise_payload(**overrides) -> dict:
    payload = {"revise_note": "Re-open the rejected version for edit."}
    payload.update(overrides)
    return payload


def release_payload(**overrides) -> dict:
    payload = {"release_note": "Released to the print vendor."}
    payload.update(overrides)
    return payload


def waiver_payload(**overrides) -> dict:
    payload = {
        "waiver_justification": "Residual risk accepted; corrective action tracked.",
    }
    payload.update(overrides)
    return payload


def task_decision_payload(decision="APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "APPROVED":
        payload["comment"] = "Approved without reservation."
    elif decision == "REJECTED":
        payload["comment"] = "Logo lock-up clears the allergen panel; revise."
    elif decision == "CONDITIONAL":
        payload["condition_code"] = "COND-COLOR-01"
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Printer and proof
# ---------------------------------------------------------------------------


def create_printer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRINTER_NAME"],
        "color_standard": "G7_MASTER",
        "certified_substrates": ["COATED_PAPER", "FILM"],
        "recovery_liability_cap_cents": DEFAULTS["RECOVERY_LIABILITY_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_printer_proof_payload(artwork_version_id, printer_id, **overrides) -> dict:
    defaults = {
        "artwork_version_id": artwork_version_id,
        "printer_id": printer_id,
        "substrate_code": "COATED_PAPER",
        "proof_note": "Wet proof pulled on the production press.",
    }
    defaults.update(overrides)
    return defaults


def color_decision_payload(measured_delta_e_max=1.2, **overrides) -> dict:
    payload = {"measured_delta_e_max": measured_delta_e_max}
    payload.update(overrides)
    return payload


def substrate_decision_payload(decision="SUBSTRATE_APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def press_check_payload(
    press_line_code="LINE-A",
    press_check_start_utc="2026-09-10T08:00:00Z",
    press_check_end_utc="2026-09-10T12:00:00Z",
    attended_by_user_id="u_qa",
    **overrides,
) -> dict:
    payload = {
        "press_line_code": press_line_code,
        "press_check_start_utc": press_check_start_utc,
        "press_check_end_utc": press_check_end_utc,
    }
    if attended_by_user_id is not None:
        payload["attended_by_user_id"] = attended_by_user_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plate order
# ---------------------------------------------------------------------------


def create_plate_order_payload(
    artwork_version_id, printer_id, printer_proof_id, plate_set_count=6, **overrides
) -> dict:
    defaults = {
        "artwork_version_id": artwork_version_id,
        "printer_id": printer_id,
        "printer_proof_id": printer_proof_id,
        "plate_set_count": plate_set_count,
        "expedite": False,
    }
    defaults.update(overrides)
    return defaults


def cancel_plate_order_payload(**overrides) -> dict:
    payload = {"cancel_reason": "Print run deferred; plates not yet cut."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inventory runout
# ---------------------------------------------------------------------------


def create_inventory_runout_payload(
    artwork_asset_id, obsolete_version_id, on_hand_qty=5000, weekly_usage_qty=1200,
    **overrides,
) -> dict:
    defaults = {
        "artwork_asset_id": artwork_asset_id,
        "obsolete_version_id": obsolete_version_id,
        "on_hand_qty": on_hand_qty,
        "weekly_usage_qty": weekly_usage_qty,
        "runout_start_utc": DEFAULTS["RUNOUT_START_UTC"],
    }
    defaults.update(overrides)
    return defaults


def depletion_records_payload(records) -> dict:
    """`records` is a list of {week_start_utc, units_consumed} objects."""
    return {"records": records}


def disposition_payload(disposition="RUNOUT", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def disposition_reversal_payload(**overrides) -> dict:
    payload = {
        "reversal_reason": (
            "Runout reversed: the obsolete stock was recovered from a distributor "
            "return."
        )
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Error escape
# ---------------------------------------------------------------------------


def create_error_escape_payload(
    artwork_version_id, printer_id, discovered_stage="MARKET", units_affected=12500,
    **overrides,
) -> dict:
    defaults = {
        "artwork_version_id": artwork_version_id,
        "printer_id": printer_id,
        "defect_code": "WRONG_ALLERGEN",
        "discovered_stage": discovered_stage,
        "units_affected": units_affected,
        "discovery_note": "Retailer complaint traced to the printed allergen panel.",
    }
    defaults.update(overrides)
    return defaults


def root_cause_payload(
    root_cause_party="SHARED", printer_share_pct=0.65, **overrides
) -> dict:
    payload = {
        "root_cause_party": root_cause_party,
        "printer_share_pct": printer_share_pct,
        "investigation_note": "Press operator ran the superseded plate set.",
    }
    payload.update(overrides)
    return payload


def recovery_claim_payload(expected_error_escape_version, **overrides) -> dict:
    payload = {"expected_error_escape_version": expected_error_escape_version}
    payload.update(overrides)
    return payload


def dispute_payload(**overrides) -> dict:
    payload = {"dispute_reason": "The brand supplied the superseded plate file."}
    payload.update(overrides)
    return payload


def settle_payload(resolution="SETTLED", **overrides) -> dict:
    if resolution == "SETTLED":
        payload = {
            "resolution": "SETTLED",
            "actual_reprint_cost_cents": 800010,
            "actual_scrap_cost_cents": 100010,
            "actual_expedite_freight_cents": 60010,
            "settlement_note": "Printer invoices reconciled.",
        }
    else:
        payload = {
            "resolution": "WRITTEN_OFF",
            "settlement_note": "Claim abandoned; commercial settlement out of band.",
        }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
