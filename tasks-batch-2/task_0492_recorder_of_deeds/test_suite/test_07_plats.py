"""Plat/survey lot-range reservation: overlap, adjacency, invalid range, reject branch."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Difficulty: resource_temporal_overlap / plat_lot_range_closed_interval_overlap
# ===========================================================================
def test_overlapping_plat_lot_range_rejected_on_approve(api):
    """PRD Section 3.6: "no already-RECORDED plat on the same office_id,
    subdivision_name, and block_number have a closed inclusive lot range that overlaps
    this plat's range, or the request is rejected with ERR_LOT_RANGE_OVERLAP. Two closed
    inclusive ranges overlap whenever each one's start is not greater than the other's end."

    A RECORDED plat [1,10] in MAPLE block 1 blocks approval of a new plat [10,15]
    (shares lot 10).

    Design: Difficulty/resource_temporal_overlap/plat_lot_range_closed_interval_overlap
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Surveyor",
                                                            submitter_type="ATTORNEY")
    fixtures.create_recorded_plat(office["id"], submitter["id"], 1, 10,
                                  subdivision_name="MAPLE", block_number=1)
    plat2 = fixtures.create_plat(office["id"], submitter["id"], 10, 15,
                                 subdivision_name="MAPLE", block_number=1)
    resp = api.approve_plat(plat2["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_LOT_RANGE_OVERLAP)


def test_overlapping_plat_stays_submitted(api):
    """PRD Section 3.6: "An Examiner approves a submitted plat, advancing it from
    SUBMITTED to APPROVED. Approval requires ... or the request is rejected with
    ERR_LOT_RANGE_OVERLAP."
    PRD Section 3.6: "The plat is born SUBMITTED."

    The rejected plat remains SUBMITTED.

    Design: Difficulty/resource_temporal_overlap/plat_lot_range_closed_interval_overlap
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Surveyor",
                                                            submitter_type="ATTORNEY")
    fixtures.create_recorded_plat(office["id"], submitter["id"], 1, 10,
                                  subdivision_name="MAPLE", block_number=1)
    plat2 = fixtures.create_plat(office["id"], submitter["id"], 10, 15,
                                 subdivision_name="MAPLE", block_number=1)
    api.approve_plat(plat2["id"], fixtures._examiner())
    data = validate_success(api.get_plat(plat2["id"], fixtures._clerk()))
    assert data["status"] == "SUBMITTED", f"plat must stay SUBMITTED, got {data['status']}"


# ===========================================================================
# Corner: validations / plat_adjacent_lot_range_allowed
# ===========================================================================
def test_adjacent_plat_lot_range_approved(api):
    """PRD Section 3.6: "Two closed inclusive ranges overlap whenever each one's start is
    not greater than the other's end."
    PRD Section 3.6: "An Examiner approves a submitted plat, advancing it from SUBMITTED to
    APPROVED."

    A new plat [11,20] adjacent to a RECORDED plat [1,10] (no shared lot) is approved.

    Design: Corner/validations/plat_adjacent_lot_range_allowed
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Surveyor",
                                                            submitter_type="ATTORNEY")
    fixtures.create_recorded_plat(office["id"], submitter["id"], 1, 10,
                                  subdivision_name="MAPLE", block_number=1)
    plat2 = fixtures.create_plat(office["id"], submitter["id"], 11, 20,
                                 subdivision_name="MAPLE", block_number=1)
    resp = api.approve_plat(plat2["id"], fixtures._examiner())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "APPROVED", f"adjacent plat must be APPROVED, got {data['status']}"


# ===========================================================================
# Corner: validations / plat_invalid_lot_range
# ===========================================================================
def test_plat_invalid_lot_range_rejected(api):
    """PRD Section 3.6: "Approval requires that end_lot be at least start_lot, or the
    request is rejected with ERR_INVALID_LOT_RANGE."

    Approving a plat with end_lot 3 < start_lot 8 returns ERR_INVALID_LOT_RANGE (422).

    Design: Corner/validations/plat_invalid_lot_range
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Surveyor",
                                                            submitter_type="ATTORNEY")
    plat = fixtures.create_plat(office["id"], submitter["id"], 8, 3,
                                subdivision_name="ELM", block_number=1)
    resp = api.approve_plat(plat["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_RANGE)


# ===========================================================================
# Corner: state_machines / plat_reject_branch
# ===========================================================================
def test_plat_can_be_rejected(api):
    """PRD Section 3.6: "An examiner may instead reject a submitted plat, moving it to
    REJECTED with no preconditions."

    A SUBMITTED plat branches to REJECTED via /plats/{id}/reject.

    Design: Corner/state_machines/plat_reject_branch
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Surveyor",
                                                            submitter_type="ATTORNEY")
    plat = fixtures.create_plat(office["id"], submitter["id"], 1, 5,
                                subdivision_name="OAK", block_number=2)
    resp = api.reject_plat(plat["id"], fixtures._examiner())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "REJECTED", f"plat must be REJECTED, got {data['status']}"
