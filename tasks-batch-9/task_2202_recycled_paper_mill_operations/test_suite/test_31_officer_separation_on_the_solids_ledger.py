"""The widest segregation-of-duties bar in the mill — the officer who logged discharge
may not sign the hauler's manifest — and the proof that the bar is read from live
ledger state and keyed on identifiers rather than role names.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, register_permit, setup_available_lot, setup_approved_batch,
    setup_completed_run, declare_tl_140, log_reading, prepare_manifest,
    solids_rows, solids_summary, sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_LOGGER = TEST_USERS["env_logger_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]
ENV_SIGNER = TEST_USERS["env_signer_headers"]

MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _permit_reading_and_draft_manifest():
    """One logged day, one 2.000-ton pending reject row, one DRAFT manifest claiming it."""
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)
    reading = log_reading(permit["id"], headers=ENV_LOGGER, reading_date="2026-08-01",
                          flow_m3=4000.00, bod_kg=100.00, tss_kg=50.00)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    row = solids_rows(source_ref_id=bundle["batch"]["id"],
                      source_kind="PULP_REJECT")[0]
    manifest = prepare_manifest([row["id"]], headers=ENV_PREPARER,
                                manifest_number="MAN-0001", destination="LANDFILL")
    return permit, reading, row, manifest


def test_the_officer_who_logged_the_window_s_discharge_may_not_sign_the_manifest():
    """PRD §3.7: "It then requires that the acting `X-User-ID` differ from the manifest's
    `prepared_by_user_id` **and** that the acting `X-User-ID` is not the
    `logged_by_user_id` of any non-voided reading inside the permit's current rolling
    window; a violation of either half is rejected with `ERR_SOD_SAME_ENV_OFFICER` (HTTP
    409)."
    PRD §3.7: "Signing records `signed_by_user_id`, sets `manifest_id` on each claimed
    solids row, and moves each of those rows' `disposition` from `PENDING` to
    `MANIFESTED`."
    PRD §2.9: "Signing a manifest moves tonnage from pending to manifested and voiding it
    moves the tonnage back, leaving `net_solids_tons` identical before and after."

    Design: Corner/rbac/a_manifest_cannot_be_signed_by_an_officer_who_logged_a_reading_in_the_window
    """
    permit, reading, row, manifest = _permit_reading_and_draft_manifest()
    assert reading["logged_by_user_id"] == "eo_log"

    validate_error(api_client.sign_sludge_manifest(manifest["id"], ENV_LOGGER),
                   ApiErrorId.ERR_SOD_SAME_ENV_OFFICER.value, 409)
    validate_error(api_client.sign_sludge_manifest(manifest["id"], ENV_PREPARER),
                   ApiErrorId.ERR_SOD_SAME_ENV_OFFICER.value, 409)

    unsigned = get_success_data(api_client.get_sludge_manifest(manifest["id"], ENV))
    assert unsigned["status"] == "DRAFT"
    assert unsigned["signed_by_user_id"] is None
    assert unsigned["total_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert get_success_data(api_client.get_reject_stream(
        row["id"], ENV))["disposition"] == "PENDING"

    signed = validate_success(api_client.sign_sludge_manifest(
        manifest["id"], ENV_SIGNER))
    assert signed["status"] == "SIGNED"
    assert signed["signed_by_user_id"] == "eo_sign", \
        "a third officer, neither preparer nor logger, may sign"
    hauled = get_success_data(api_client.get_reject_stream(row["id"], ENV))
    assert hauled["disposition"] == "MANIFESTED"
    assert hauled["manifest_id"] == manifest["id"]
    summary = solids_summary()
    assert summary["manifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)


def test_voiding_the_reading_returns_its_officer_to_the_signing_pool():
    """PRD §3.7: "It then requires that the acting `X-User-ID` differ from the manifest's
    `prepared_by_user_id` **and** that the acting `X-User-ID` is not the
    `logged_by_user_id` of any non-voided reading inside the permit's current rolling
    window; a violation of either half is rejected with `ERR_SOD_SAME_ENV_OFFICER` (HTTP
    409)."
    PRD §3.7: "Both logging and voiding recompute the permit's rolling posture from
    scratch. If the permit has no non-voided readings at all, `rolling_bod_kg_per_day` and
    `rolling_tss_kg_per_day` are 0.000, `exceedance_day_count` is 0, and the posture is
    `COMPLIANT`."

    Design: Corner/rbac/voiding_the_reading_releases_the_officer_who_logged_it
    """
    permit, reading, row, manifest = _permit_reading_and_draft_manifest()
    validate_error(api_client.sign_sludge_manifest(manifest["id"], ENV_LOGGER),
                   ApiErrorId.ERR_SOD_SAME_ENV_OFFICER.value, 409)

    voided = validate_success(api_client.void_effluent_reading(reading["id"], ENV))
    assert voided["voided"] is True

    emptied = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert emptied["rolling_bod_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert emptied["rolling_tss_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert emptied["exceedance_day_count"] == 0
    assert emptied["compliance_posture"] == "COMPLIANT"

    signed = validate_success(api_client.sign_sludge_manifest(
        manifest["id"], ENV_LOGGER))
    assert signed["status"] == "SIGNED"
    assert signed["signed_by_user_id"] == "eo_log", \
        "the bar is read from the live ledger on every attempt"
    listing = api_client.list_permit_readings(
        permit["id"], ENV, {"voided": True}).json()
    assert listing["meta"]["total_count"] == 1


def test_the_duty_split_is_keyed_on_identifiers_and_not_on_role_names():
    """PRD §2.1: "It may, however, be *recorded* where a transition captures it — as
    `sampled_by_user_id` and `dispositioned_by_user_id` on a fiber receipt, as
    `started_by_user_id` and `certified_by_user_id` on a production run, as
    `logged_by_user_id` on an effluent reading, and as `prepared_by_user_id` and
    `signed_by_user_id` on a sludge manifest — and the segregation-of-duties rules compare
    those recorded values against the current `X-User-ID`."
    PRD §3.5: "Certification, `PROVISIONAL → CERTIFIED`, is a `QualityLab` act with four
    requirements evaluated in this order: the quality axis must read `PROVISIONAL`; the
    acting `X-User-ID` must differ from the run's `started_by_user_id`, and an operator
    certifying their own run is rejected with `ERR_SOD_SAME_OPERATOR` (HTTP 409);
    `off_spec_reel_count` must be exactly 0; and the certified quality index must be at
    least 85.00."
    PRD §3.2: "All three branches require the receipt to be in `SAMPLED`, failing which the
    request is rejected with `ERR_RECEIPT_INVALID_STATE` (HTTP 409), and all three enforce
    segregation of duties: the acting `X-User-ID` must differ from the receipt's
    `sampled_by_user_id`, and an operator attempting to disposition the truck they sampled
    is rejected with `ERR_SOD_SAME_SAMPLER` (HTTP 409)."

    Design: Corner/rbac/segregation_of_duties_compares_user_ids_not_role_names
    """
    set_clock("2026-08-01T00:00:00Z")
    bundle = setup_completed_run(run_overrides={"pulp_draw_tons": 20.000})
    machine, run = bundle["machine"], bundle["run"]
    assert run["started_by_user_id"] == "mo_1"

    certified = validate_success(api_client.certify_run(
        machine["id"], run["id"], DISPOSER))

    assert certified["quality_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "ql_dispo"
    assert certified["started_by_user_id"] == "mo_1", \
        "two identifiers in two different roles clear the run's duty split"
    receipt = get_success_data(api_client.get_receipt(bundle["receipt"]["id"], BUYER))
    assert receipt["status"] == "ACCEPTED"
    assert receipt["sampled_by_user_id"] == "ql_sample"
    assert receipt["dispositioned_by_user_id"] == "ql_dispo", \
        "the same lab identifier that judged the truck may certify the run"
    posture = get_success_data(api_client.get_supplier(
        bundle["supplier"]["id"], BUYER))
    assert posture["contamination_strike_count"] == 0
    assert posture["qualification_status"] == "QUALIFIED"
