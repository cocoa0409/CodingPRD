"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DISPOSITION_TO_MODULE_STATUS,
    GRADE_TO_DERIVED_DISPOSITION,
    HAZMAT_CAP_PCT,
    HAZMAT_FLAT_CENTS,
    HAZMAT_PER_KG_CENTS,
    PAYABLE_METALS,
    PAYABLE_SHARE,
)

# --------------------------------------------------------------------------
# Precision helpers (PRD §2.9)
# --------------------------------------------------------------------------

def assert_mass_precision(value, label="mass"):
    """Masses in kilogrammes are carried to three decimal places."""
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-12, 3)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must be carried to three decimals, got {value}"
    )


def assert_percentage_precision(value, label="percentage", decimals=2):
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-12, decimals)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must be carried to {decimals} decimals, got {value}"
    )


def assert_whole_cents(value, label="amount"):
    """All money is held in whole cents as integers."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of whole cents, got {value!r}"
    )


def assert_timestamp_with_three_fractional_digits(value, label="timestamp"):
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"
    assert "." in value and value.endswith("Z"), (
        f"{label} must carry exactly three fractional digits and a Z suffix, got {value!r}"
    )
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_identity_fields(data, label="resource"):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert "_" not in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert_timestamp_with_three_fractional_digits(data.get("created_at"), f"{label}.created_at")
    assert_timestamp_with_three_fractional_digits(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_immutable_ledger_row(data, label="ledger row"):
    """MetalIndexPrice and RecoveryOutput carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert_timestamp_with_three_fractional_digits(data.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in data, f"{label} must not expose updated_at"
    assert "version" not in data, f"{label} must not expose version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_facility(data):
    assert_identity_fields(data, "facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be two uppercase letters"
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert float(data["mech_capacity_kg_per_day"]) > 0
    assert float(data["hydro_capacity_kg_per_day"]) > 0


def assert_supplier(data):
    assert_identity_fields(data, "supplier")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["channel"] in ("AUTOMAKER", "DISMANTLER", "CONSUMER_COLLECTION")
    assert_whole_cents(data["credit_limit_cents"], "supplier.credit_limit_cents")
    assert data["credit_limit_cents"] >= 0
    assert_whole_cents(data["payable_balance_cents"], "supplier.payable_balance_cents")
    assert_whole_cents(data["paid_to_date_cents"], "supplier.paid_to_date_cents")
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["quality_strike_count"], int)
    assert data["quality_strike_count"] >= 0


def assert_metal_index_price(data):
    assert_immutable_ledger_row(data, "metal index quote")
    assert data["metal"] in ("NI", "CO", "LI", "CU", "MN", "GRAPHITE")
    assert_timestamp_with_three_fractional_digits(data["effective_date"], "effective_date")
    assert_whole_cents(data["price_cents_per_kg"], "price_cents_per_kg")
    assert data["price_cents_per_kg"] > 0


def assert_intake(data):
    assert_identity_fields(data, "intake")
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["facility_id"])
    assert_timestamp_with_three_fractional_digits(data["received_at"], "intake.received_at")
    assert data["declared_chemistry"] in ("NMC622", "NCA", "LMO", "LFP")
    assert data.get("identified_chemistry") in (None, "NMC622", "NCA", "LMO", "LFP")
    assert float(data["gross_mass_kg"]) > 0
    assert 0.0 <= float(data["packaging_tare_kg"]) < float(data["gross_mass_kg"])
    assert_mass_precision(data["net_mass_kg"], "intake.net_mass_kg")
    for field in (
        "declared_ni_pct", "declared_co_pct", "declared_li_pct", "declared_cu_pct",
        "moisture_pct", "foreign_material_pct",
    ):
        assert 0.0 <= float(data[field]) <= 100.0, f"{field} must be between 0.0 and 100.0"
    assert data["custody_state"] in (
        "RECEIVED", "IDENTIFIED", "DISCHARGED", "PACKAGED", "RELEASED", "QUARANTINED",
    )
    assert data["compliance_state"] in (
        "MANIFEST_DRAFT", "MANIFEST_SUBMITTED", "MANIFEST_CLOSED", "MANIFEST_REJECTED",
    )
    assert data.get("hold_reason") in (None, "MANIFEST_REJECTED", "SUPPLIER_CREDIT_HOLD")
    if data["custody_state"] != "QUARANTINED":
        assert data.get("hold_reason") is None, (
            "hold_reason is null whenever custody_state is anything other than QUARANTINED"
        )
    assert_mass_precision(data["module_mass_total_kg"], "intake.module_mass_total_kg")
    assert_mass_precision(data["assigned_mass_kg"], "intake.assigned_mass_kg")
    assert_mass_precision(data["unassigned_mass_kg"], "intake.unassigned_mass_kg")
    assert_intake_mass_conservation(data)


def assert_hazmat_manifest(data):
    assert_identity_fields(data, "manifest")
    assert is_valid_uuid(data["intake_id"])
    assert data["un_number"] in ("UN3480", "UN3481", "UN3536")
    assert data["packing_group"] in ("I", "II", "III")
    assert isinstance(data["transporter_name"], str) and data["transporter_name"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("SUBMITTED", "CLOSED", "REJECTED")
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_module(data):
    assert_identity_fields(data, "module")
    assert is_valid_uuid(data["intake_id"])
    assert isinstance(data["serial_code"], str) and data["serial_code"]
    assert data["chemistry"] in ("NMC622", "NCA", "LMO", "LFP")
    assert float(data["mass_kg"]) > 0
    assert 0.0 <= float(data["min_cell_capacity_pct"]) <= 100.0
    assert float(data["min_cell_capacity_pct"]) <= float(data["mean_cell_capacity_pct"]) <= 100.0
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0
    assert data["status"] in (
        "PENDING_TRIAGE", "REFURB_QUEUE", "SECOND_LIFE_QUEUE", "RECOVERY_QUEUE",
        "CHARGED", "CONSUMED", "SHIPPED",
    )
    assert data.get("grade") in (None, "A", "B", "C", "D")
    if data.get("second_life_score") is not None:
        assert_percentage_precision(data["second_life_score"], "module.second_life_score")


def assert_triage_decision(data):
    assert_identity_fields(data, "triage decision")
    assert is_valid_uuid(data["module_id"])
    assert data["scoring_variant"] in ("CONSERVATIVE", "FLEET_AVERAGE")
    assert_percentage_precision(data["score"], "decision.score")
    assert data["grade"] in ("A", "B", "C", "D")
    assert data["derived_disposition"] in ("REFURBISH", "SECOND_LIFE", "MATERIAL_RECOVERY")
    assert data["disposition"] in ("REFURBISH", "SECOND_LIFE", "MATERIAL_RECOVERY")
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert isinstance(data["decided_by_user_id"], str) and data["decided_by_user_id"]
    assert data["derived_disposition"] == GRADE_TO_DERIVED_DISPOSITION[data["grade"]], (
        "derived_disposition follows from the grade alone"
    )


def assert_processing_line(data):
    assert_identity_fields(data, "processing line")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["line_type"] in ("MECHANICAL", "HYDROMET")
    assert data["chemistry_family"] in ("NICKEL_RICH", "IRON_PHOSPHATE")
    assert float(data["throughput_kg_per_hour"]) > 0
    assert int(data["changeover_buffer_hours"]) >= 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_processing_campaign(data):
    assert_identity_fields(data, "campaign")
    assert is_valid_uuid(data["line_id"])
    assert data["chemistry_family"] in ("NICKEL_RICH", "IRON_PHOSPHATE")
    assert_timestamp_with_three_fractional_digits(data["window_start"], "window_start")
    assert_timestamp_with_three_fractional_digits(data["window_end"], "window_end")
    assert data["window_end"] > data["window_start"], "window_end must be after window_start"
    assert float(data["planned_input_kg"]) > 0
    assert_mass_precision(data["committed_input_kg"], "campaign.committed_input_kg")
    assert data["status"] in ("SCHEDULED", "RUNNING", "CLOSED", "CANCELLED")


def assert_recovery_lot(data):
    assert_identity_fields(data, "lot")
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert_mass_precision(data["charged_mass_kg"], "lot.charged_mass_kg")
    assert_mass_precision(data["recovered_mass_kg"], "lot.recovered_mass_kg")
    assert data["status"] in ("OPEN", "CHARGED", "FINALIZED", "VOIDED")
    for field in ("residue_mass_kg", "accounted_mass_kg", "unaccounted_mass_kg"):
        if data.get(field) is not None:
            assert_mass_precision(data[field], f"lot.{field}")
    for field in ("mass_balance_pct", "recycled_content_pct"):
        if data.get(field) is not None:
            assert_percentage_precision(data[field], f"lot.{field}")


def assert_recovery_output(data):
    assert_immutable_ledger_row(data, "recovery output")
    assert is_valid_uuid(data["lot_id"])
    assert data["metal"] in ("NI", "CO", "LI", "CU", "MN", "GRAPHITE")
    assert float(data["recovered_mass_kg"]) > 0
    assert 0.0 < float(data["assay_purity_pct"]) <= 100.0
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_settlement(data):
    assert_identity_fields(data, "settlement")
    assert is_valid_uuid(data["intake_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["state"] in (
        "DRAFT", "POSTED", "DISPUTED", "UMPIRE_ROUND", "SETTLED", "VOIDED",
    )
    assert_timestamp_with_three_fractional_digits(
        data["price_basis_date"], "settlement.price_basis_date"
    )
    for field in (
        "gross_cents", "processing_fee_cents", "quality_deduction_cents",
        "pre_surcharge_net_cents", "hazmat_surcharge_cents", "net_payable_cents",
        "posted_amount_cents",
    ):
        assert_whole_cents(data[field], f"settlement.{field}")
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0
    assert_percentage_precision(
        data["quality_deduction_pct"], "settlement.quality_deduction_pct", decimals=4
    )
    if data.get("max_variance_pp") is not None:
        assert_percentage_precision(data["max_variance_pp"], "settlement.max_variance_pp")
    assert isinstance(data["line_breakdown"], list)
    assert_settlement_line_breakdown(data)
    assert_settlement_waterfall(data)


def assert_settlement_line_breakdown(data):
    """The four payable metals in the fixed order NI, CO, LI, CU."""
    lines = data["line_breakdown"]
    assert [line["metal"] for line in lines] == PAYABLE_METALS, (
        f"line_breakdown must walk NI, CO, LI, CU in order, got "
        f"{[line['metal'] for line in lines]}"
    )
    total = 0
    for line in lines:
        assert_mass_precision(line["contained_kg"], f"{line['metal']} contained_kg")
        assert_whole_cents(line["line_cents"], f"{line['metal']} line_cents")
        assert float(line["payable_share"]) == PAYABLE_SHARE[line["metal"]], (
            f"{line['metal']} payable_share must be {PAYABLE_SHARE[line['metal']]}"
        )
        total += line["line_cents"]
    assert data["gross_cents"] == total, (
        f"gross_cents must be the sum of the already-rounded lines: "
        f"expected {total}, got {data['gross_cents']}"
    )


def assert_settlement_waterfall(data):
    """Steps five and seven of the payable waterfall are exact identities."""
    expected_pre = (
        data["gross_cents"] - data["processing_fee_cents"] - data["quality_deduction_cents"]
    )
    assert data["pre_surcharge_net_cents"] == expected_pre, (
        f"pre_surcharge_net_cents must be gross less fee less quality deduction: "
        f"expected {expected_pre}, got {data['pre_surcharge_net_cents']}"
    )
    expected_net = data["pre_surcharge_net_cents"] - data["hazmat_surcharge_cents"]
    assert data["net_payable_cents"] == expected_net, (
        f"net_payable_cents must be the pre-surcharge net less the hazmat surcharge: "
        f"expected {expected_net}, got {data['net_payable_cents']}"
    )
    cap_candidate = round_half_up_cents(data["pre_surcharge_net_cents"] * HAZMAT_CAP_PCT)
    assert data["hazmat_surcharge_cents"] <= cap_candidate, (
        "hazmat_surcharge_cents must not exceed five percent of the pre-surcharge net"
    )


def assert_permit_allotment(data):
    assert_identity_fields(data, "allotment")
    assert is_valid_uuid(data["facility_id"])
    assert data["medium"] in ("AIR", "WATER")
    assert isinstance(data["permit_no"], str) and data["permit_no"]
    assert_timestamp_with_three_fractional_digits(data["valid_from"], "valid_from")
    assert_timestamp_with_three_fractional_digits(data["valid_to"], "valid_to")
    assert data["valid_to"] > data["valid_from"]
    assert float(data["daily_cap_kg"]) > 0
    assert_mass_precision(data["consumed_kg"], "allotment.consumed_kg")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_discharge_event(data):
    assert_identity_fields(data, "discharge event")
    assert is_valid_uuid(data["allotment_id"])
    assert is_valid_uuid(data["lot_id"])
    assert_timestamp_with_three_fractional_digits(data["event_date"], "event_date")
    assert float(data["mass_kg"]) > 0
    assert data["analyte"] in ("NICKEL_DISSOLVED", "FLUORIDE", "TSS")
    assert data["status"] in ("POSTED", "VOIDED")


def assert_battery_passport(data):
    assert_identity_fields(data, "passport")
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["passport_code"], str) and data["passport_code"]
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert_percentage_precision(data["recycled_content_pct"], "passport.recycled_content_pct")
    assert isinstance(data["metal_content"], list)
    for entry in data["metal_content"]:
        assert entry["metal"] in ("NI", "CO", "LI", "CU", "MN", "GRAPHITE")
        assert_mass_precision(entry["recovered_mass_kg"], "metal_content.recovered_mass_kg")
    assert data["status"] in ("ISSUED", "REVOKED")
    assert_timestamp_with_three_fractional_digits(data["issued_at"], "passport.issued_at")


# --------------------------------------------------------------------------
# Ledger invariants (PRD §2.10)
# --------------------------------------------------------------------------

def assert_intake_mass_conservation(intake):
    """assigned_mass_kg plus unassigned_mass_kg equals module_mass_total_kg."""
    total = float(intake["assigned_mass_kg"]) + float(intake["unassigned_mass_kg"])
    assert abs(total - float(intake["module_mass_total_kg"])) < 1e-6, (
        f"assigned {intake['assigned_mass_kg']} + unassigned "
        f"{intake['unassigned_mass_kg']} must equal module_mass_total_kg "
        f"{intake['module_mass_total_kg']}"
    )


def assert_supplier_obligation_invariant(supplier, settlements):
    """payable_balance_cents equals the sum of posted_amount_cents over the
    supplier's settlements in POSTED, DISPUTED, UMPIRE_ROUND or SETTLED, less
    paid_to_date_cents."""
    obligation_states = ("POSTED", "DISPUTED", "UMPIRE_ROUND", "SETTLED")
    posted_sum = sum(
        s["posted_amount_cents"] for s in settlements if s["state"] in obligation_states
    )
    expected = posted_sum - supplier["paid_to_date_cents"]
    assert supplier["payable_balance_cents"] == expected, (
        f"payable_balance_cents must be {expected} "
        f"(posted sum {posted_sum} less paid_to_date {supplier['paid_to_date_cents']}), "
        f"got {supplier['payable_balance_cents']}"
    )


def assert_permit_allowance_invariant(allotment, events):
    """consumed_kg equals the sum of mass_kg over the allotment's POSTED events."""
    posted = sum(
        float(e["mass_kg"]) for e in events if e["status"] == "POSTED"
    )
    assert abs(float(allotment["consumed_kg"]) - posted) < 1e-6, (
        f"consumed_kg must equal the POSTED discharge mass {posted}, "
        f"got {allotment['consumed_kg']}"
    )


def assert_credit_hold_consistent(supplier):
    """credit_hold is true exactly while payable_balance_cents is greater than
    credit_limit_cents."""
    expected = supplier["payable_balance_cents"] > supplier["credit_limit_cents"]
    assert supplier["credit_hold"] is expected, (
        f"credit_hold must be {expected} for payable "
        f"{supplier['payable_balance_cents']} against limit "
        f"{supplier['credit_limit_cents']}"
    )


def assert_module_status_matches_disposition(module, decision):
    expected = DISPOSITION_TO_MODULE_STATUS[decision["disposition"]]
    assert module["status"] == expected, (
        f"a {decision['disposition']} disposition must move the module to "
        f"{expected}, got {module['status']}"
    )
    assert module["second_life_score"] == decision["score"], (
        "the score is copied onto the module as second_life_score"
    )
    assert module["grade"] == decision["grade"], "the grade is copied onto the module"


# --------------------------------------------------------------------------
# Small arithmetic helpers used by expected-value checks
# --------------------------------------------------------------------------

def round_half_up(value, decimals=0):
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_cents(value) -> int:
    return int(round_half_up(value, 0))


def hazmat_surcharge_candidates(net_mass_kg, pre_surcharge_net_cents):
    """The two candidates of waterfall step six."""
    flat = round_half_up_cents(HAZMAT_FLAT_CENTS + net_mass_kg * HAZMAT_PER_KG_CENTS)
    capped = round_half_up_cents(pre_surcharge_net_cents * HAZMAT_CAP_PCT)
    return flat, capped
