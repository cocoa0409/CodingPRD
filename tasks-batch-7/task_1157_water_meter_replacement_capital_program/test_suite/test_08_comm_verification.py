"""AMI communication verification boundaries: exactly 4 reads, exactly
-95 dBm (PRD 3.6)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, get_success_data, ingest_reads, register_endpoint,
    setup_program_wave_contractor, setup_work_order_reconciled,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
AMI = TEST_USERS["ami_operator_headers"]


def test_exactly_four_reads_verifies_and_chains_work_order(api):
    """PRD §3.6: "Communication is verified when the window holds at least
    four reads and the average signal strength across them is −95 dBm or
    stronger, with the average computed exactly, without rounding; the
    boundary is inclusive, so exactly four reads at exactly −95 dBm passes. A
    passing verification moves the registration `REGISTERED` → `COMM_VERIFIED`
    and chains the work order `RECONCILED` → `AMI_VERIFIED` → `QA_REVIEW` in
    one automatic sequence."

    Design: Difficulty/boundary_precision_check/comm_verification_exact_min_reads
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_reconciled(contr["id"])
    reg = register_endpoint(ctx["work_order"]["id"])
    ingest_reads(reg["id"], 4, rssi_dbm=-90)
    resp = api.verify_endpoint_registration(reg["id"], AMI)
    data = validate_success(resp)
    assert data["status"] == "COMM_VERIFIED"
    assert data["reads_received_count"] == 4
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "QA_REVIEW"


def test_three_reads_fail_then_replacement_at_rssi_floor_verifies(api):
    """PRD §3.6: "Communication is verified when the window holds at least
    four reads and the average signal strength across them is −95 dBm or
    stronger, with the average computed exactly, without rounding; the
    boundary is inclusive, so exactly four reads at exactly −95 dBm passes."
    PRD §3.6: "A failing verification moves the registration `REGISTERED` →
    `COMM_FAILED` with no work-order effect."
    PRD §3.6: "The old registration moves to `REPLACED`, and a fresh
    registration is created for the same work order in `REGISTERED` status
    with `registered_at` restamped from the clock and both counters reset."

    Design: Difficulty/boundary_precision_check/comm_verification_exact_min_reads
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_reconciled(contr["id"])
    reg = register_endpoint(ctx["work_order"]["id"], endpoint_serial="EP-B")
    ingest_reads(reg["id"], 3, rssi_dbm=-90)  # one below the 4-read minimum
    failed = validate_success(api.verify_endpoint_registration(reg["id"], AMI))
    assert failed["status"] == "COMM_FAILED"
    assert failed["reads_received_count"] == 3
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "RECONCILED"  # no auto-advance on failure
    # Replace and re-verify at exactly -95 dBm average (inclusive floor).
    reg2 = validate_success(api.replace_endpoint_registration(
        reg["id"], {"new_endpoint_serial": "EP-B2"}, AMI), expected_status=201)
    assert reg2["status"] == "REGISTERED"
    assert reg2["reads_received_count"] == 0
    assert reg2["rssi_sum_dbm"] == 0
    old = get_success_data(api_client.get_endpoint_registration(reg["id"], AMI))
    assert old["status"] == "REPLACED"
    ingest_reads(reg2["id"], 4, rssi_dbm=-95)
    verified = validate_success(api.verify_endpoint_registration(reg2["id"], AMI))
    assert verified["status"] == "COMM_VERIFIED"
    assert verified["reads_received_count"] == 4
