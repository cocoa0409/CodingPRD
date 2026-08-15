"""Species verification: mismatch three-link cascade, mislabel relabel
resolution, and quarantine-release gating on open corrective actions."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_supplier,
    create_lot,
    create_released_entry,
    get_success_data,
    make_compliance_manager_headers,
    make_receiving_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
QA = TEST_USERS["qa_tech_headers"]
RI = TEST_USERS["receiving_inspector_headers"]


def _setup_tuna_lot_for_mismatch(api, frn="FRN-5001", entry_number="E-5001",
                                 country="MX"):
    """Approved supplier + RELEASED entry + one TUNA lot UNDER_INSPECTION."""
    supplier = create_approved_supplier(name="Crimson Gulf Fisheries",
                                        country=country, frn=frn)
    entry = create_released_entry(
        supplier["id"], entry_number=entry_number, species="TUNA",
        transport_mode="VESSEL", goods_value_cents=600000,
        freight_cost_cents=25000, duty_rate_pct=0.03, total_weight_kg=90)
    lot = create_lot(entry["id"], species="TUNA", grade="B",
                     quantity_received_kg=90, harvest_country_code=country,
                     catch_area_code="FAO77", vessel_name="FV Golfo",
                     receiving_temp_c=2.0)
    return supplier, entry, lot


class TestSpeciesMismatchCascade:
    def test_mismatch_quarantines_lot_and_creates_ca(self, api):
        """PRD: "If they do not match, the verification enters `MISMATCH`
        status and a three-link cascade fires:"
        PRD: "1. The lot transitions from `UNDER_INSPECTION` or `ACCEPTED` to
        `QUARANTINED` (if not already quarantined), incrementing the ReceiptLot
        version."
        PRD: "2. The quarantine entry auto-creates a CorrectiveAction with
        `source_type` `SPECIES_MISMATCH`, `receipt_lot_id` set to the lot,
        `supplier_id` traced through the lot's import entry to its supplier,
        `opened_by` set to the requesting `X-User-ID`, and `status` `OPEN`."

        Design: Difficulty/transitive_cascade/species_mismatch_cascade_depth3
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(api)
        ri01 = make_receiving_inspector_headers("ri-01")

        ver = validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)
        assert ver["is_match"] is False
        assert ver["status"] == "MISMATCH"

        after_lot = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert after_lot["status"] == "QUARANTINED"

        cas, meta = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 1
        ca = cas[0]
        assert ca["source_type"] == "SPECIES_MISMATCH"
        assert ca["status"] == "OPEN"
        assert ca["opened_by"] == "ri-01"
        assert ca["supplier_id"] == supplier["id"]

    def test_mismatch_updates_supplier_counters_and_risk(self, api):
        """PRD: "3. The CorrectiveAction creation increments the supplier's
        `open_corrective_action_count` by 1 and `total_species_mismatches` by
        1, then recomputes the supplier's `risk_score` and `risk_tier` (see
        §3.8), incrementing the ForeignSupplier version."
        PRD: "The `risk_score` is 40% of the evaluation component plus 30% of
        the open penalty plus 30% of the history penalty, rounded half-up to 2
        decimal places."

        Design: Difficulty/transitive_cascade/species_mismatch_cascade_depth3
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(api)
        before = validate_success(api.get_supplier(supplier["id"], CM))
        # 90/90/90 -> eval component 10 -> 0.4*10 = 4.00, no penalties.
        assert before["risk_score"] == pytest.approx(4.00, abs=0.005)
        assert before["risk_tier"] == "LOW"

        ri01 = make_receiving_inspector_headers("ri-01")
        validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)

        after = validate_success(api.get_supplier(supplier["id"], CM))
        assert after["total_species_mismatches"] == 1
        assert after["open_corrective_action_count"] == 1
        # 0.4*10 + 0.3*10 + 0.3*25 = 4 + 3 + 7.5 = 14.50
        assert after["risk_score"] == pytest.approx(14.50, abs=0.005)
        assert after["risk_tier"] == "LOW"


class TestMislabelRelabelResolution:
    def test_relabel_resolution_flow(self, api):
        """PRD: "With `RELABEL_AS_VERIFIED`, the lot's `species_declared` is
        overwritten to the verified species, `species_verified` is set, and
        `mislabel_flag` is set to `true`. The verification transitions to
        `RESOLVED_RELABELED`. The lot remains `QUARANTINED` until the linked
        corrective action is resolved and quarantine-release is called."

        Design: Corner/validations/mislabel_relabel_resolution_flow
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(
            api, frn="FRN-V13", entry_number="E-V13")
        ri01 = make_receiving_inspector_headers("ri-01")
        ver = validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)

        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        ca_id = cas[0]["id"]
        cm02 = make_compliance_manager_headers("cm-02")
        get_success_data(api.investigate_corrective_action(ca_id, cm02))
        get_success_data(api.resolve_corrective_action(
            ca_id, "relabel approved", cm02))

        resolved = validate_success(api.resolve_species_verification(
            ver["id"], "RELABEL_AS_VERIFIED", QA))
        assert resolved["status"] == "RESOLVED_RELABELED"

        lot_mid = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert lot_mid["species_declared"] == "ESCOLAR"
        assert lot_mid["mislabel_flag"] is True
        assert lot_mid["status"] == "QUARANTINED"

        released = validate_success(
            api.quarantine_release_receipt_lot(lot["id"], CM))
        assert released["status"] == "ACCEPTED"

    def test_reject_lot_resolution(self, api):
        """PRD: "With `REJECT_LOT`, the lot transitions to `REJECTED` and the
        verification to `RESOLVED_REJECTED`."

        Design: Corner/validations/mislabel_relabel_resolution_flow
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(
            api, frn="FRN-V13B", entry_number="E-V13B")
        ri01 = make_receiving_inspector_headers("ri-01")
        ver = validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)

        resolved = validate_success(api.resolve_species_verification(
            ver["id"], "REJECT_LOT", QA))
        assert resolved["status"] == "RESOLVED_REJECTED"
        lot_after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert lot_after["status"] == "REJECTED"


class TestQuarantineReleaseOpenCaGate:
    def test_quarantine_release_blocked_by_open_ca(self, api):
        """PRD: "The lot must be `QUARANTINED`, no linked CorrectiveAction may
        be `OPEN` or `INVESTIGATING` (`ERR_OPEN_CORRECTIVE_ACTIONS`)."

        Design: Corner/validations/quarantine_release_blocked_by_open_ca
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(
            api, frn="FRN-V03", entry_number="E-V03")
        ri01 = make_receiving_inspector_headers("ri-01")
        ver = validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)
        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        ca_id = cas[0]["id"]

        # CA still OPEN -> release blocked.
        resp = api.quarantine_release_receipt_lot(lot["id"], CM)
        validate_error(resp, ApiErrorId.ERR_OPEN_CORRECTIVE_ACTIONS)

        # Resolve by a different user, resolve the verification, then release.
        cm02 = make_compliance_manager_headers("cm-02")
        get_success_data(api.investigate_corrective_action(ca_id, cm02))
        get_success_data(api.resolve_corrective_action(
            ca_id, "lot relabeled to verified species", cm02))
        get_success_data(api.resolve_species_verification(
            ver["id"], "RELABEL_AS_VERIFIED", QA))
        released = validate_success(
            api.quarantine_release_receipt_lot(lot["id"], CM))
        assert released["status"] == "ACCEPTED"

    def test_quarantine_release_requires_resolved_ca_even_after_investigation(self, api):
        """PRD: "no linked CorrectiveAction may be `OPEN` or `INVESTIGATING`
        (`ERR_OPEN_CORRECTIVE_ACTIONS`)" — an INVESTIGATING (not yet RESOLVED)
        CA still blocks the release.

        Design: Corner/validations/quarantine_release_blocked_by_open_ca
        """
        supplier, entry, lot = _setup_tuna_lot_for_mismatch(
            api, frn="FRN-V03B", entry_number="E-V03B")
        ri01 = make_receiving_inspector_headers("ri-01")
        validate_success(api.create_species_verification(
            {"receipt_lot_id": lot["id"], "test_method": "DNA_BARCODING",
             "sample_size": 5, "verified_species": "ESCOLAR"},
            ri01), 201)
        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        ca_id = cas[0]["id"]
        cm02 = make_compliance_manager_headers("cm-02")
        get_success_data(api.investigate_corrective_action(ca_id, cm02))

        # INVESTIGATING still blocks.
        resp = api.quarantine_release_receipt_lot(lot["id"], CM)
        validate_error(resp, ApiErrorId.ERR_OPEN_CORRECTIVE_ACTIONS)
