"""Impound occupancy accounting, boarding-fee arithmetic, and OCC on create."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS,
    set_clock, investigating_case, make_kennel, make_impound,
    create_impound_payload,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]

BITE_COMPLAINT = {"animal_type": "DOG", "complaint_type": "BITE"}


# ==========================================================================
# Difficulty: combinatorial_formula / impound_boarding_fee_per_line_rounding
# ==========================================================================
def test_boarding_fee_uses_per_line_rounding(api):
    """PRD 3.6: "Each line is then grossed up by a tax rate of 0.075 — that is,
    multiplied by 1.075 — and each grossed-up line is rounded half up to two
    decimal places individually; the boarding_fee is the sum of those three
    separately-rounded amounts. The per-line rounding is mandatory and is not
    equivalent to rounding a single combined total."

    Design: Difficulty/combinatorial_formula/impound_boarding_fee_per_line_rounding
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-1")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-10T00:00:00Z",
                           licensed=False)
    set_clock(api, "2026-03-04T00:00:00Z")  # 3 boarding days
    released = validate_success(api.release_impound(impound["id"], {"disposition": "REDEEMED"}, SUPERVISOR))
    # 40.31 + 16.13 + 24.46 = 80.90 (per-line), distinct from the 80.89 sum-then-round.
    assert released["boarding_fee"] == pytest.approx(80.90, abs=0.001)


def test_boarding_fee_release_sets_redeemed_status(api):
    """PRD 3.6: "Any of these drives the impound from HELD to the corresponding
    terminal status, lowers the kennel's occupied_slots by one, and computes the
    owner-facing boarding_fee."

    Design: Difficulty/combinatorial_formula/impound_boarding_fee_per_line_rounding
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-1b")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-10T00:00:00Z",
                           licensed=False)
    set_clock(api, "2026-03-04T00:00:00Z")
    released = validate_success(api.release_impound(impound["id"], {"disposition": "REDEEMED"}, SUPERVISOR))
    assert released["status"] == "REDEEMED"
    assert released["boarding_fee"] == pytest.approx(80.90, abs=0.001)


# ==========================================================================
# Difficulty: resource_temporal_overlap / kennel_impound_touching_windows_allowed
# ==========================================================================
def _touching_impounds(api):
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-4")
    make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                 impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-04T00:00:00Z")
    # Recording impound1 bumped the case version; re-read it for impound2's OCC.
    case_now = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    impound2 = make_impound(api, ctx["case"]["id"], kennel["id"], case_now["version"],
                            impounded_at="2026-03-04T00:00:00Z", hold_until="2026-03-07T00:00:00Z")
    return kennel, impound2


def test_impound_sharing_endpoint_is_accepted(api):
    """PRD 3.6: "within one kennel, the closed occupancy interval from
    impounded_at to hold_until of a new impound may not overlap that of any
    impound already in HELD there, though intervals that merely touch at a shared
    endpoint are permitted; a genuine overlap is ERR_KENNEL_OCCUPIED."

    Design: Difficulty/resource_temporal_overlap/kennel_impound_touching_windows_allowed
    """
    _, impound2 = _touching_impounds(api)
    assert impound2["status"] == "HELD"


def test_two_touching_impounds_occupy_two_slots(api):
    """PRD 2.7: "A Kennel carries occupied_slots, the number of impounds in that
    kennel currently in HELD. It starts at 0, rises by one when an impound is
    recorded there, and falls by one when that impound is released (under any
    disposition, including a euthanasia driven by cascade)."

    Design: Difficulty/resource_temporal_overlap/kennel_impound_touching_windows_allowed
    """
    kennel, _ = _touching_impounds(api)
    kennel_after = validate_success(api.get_kennel(kennel["id"], SUPERVISOR))
    assert kennel_after["occupied_slots"] == 2


# ==========================================================================
# Difficulty: compensating_invariant / kennel_occupied_slots_conserved
# ==========================================================================
def test_occupied_slots_conserved_across_create_and_release(api):
    """PRD 2.7: "A Kennel carries occupied_slots, the number of impounds in that
    kennel currently in HELD. It starts at 0, rises by one when an impound is
    recorded there, and falls by one when that impound is released (under any
    disposition, including a euthanasia driven by cascade)."

    Design: Difficulty/compensating_invariant/kennel_occupied_slots_conserved
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-5")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-05T00:00:00Z")
    assert validate_success(api.get_kennel(kennel["id"], SUPERVISOR))["occupied_slots"] == 1
    set_clock(api, "2026-03-05T00:00:00Z")
    released = validate_success(api.release_impound(impound["id"], {"disposition": "REDEEMED"}, SUPERVISOR))
    assert released["status"] == "REDEEMED"
    assert validate_success(api.get_kennel(kennel["id"], SUPERVISOR))["occupied_slots"] == 0


def test_release_lowers_occupied_slots_to_zero(api):
    """PRD 3.6: "A successful impound is created in status HELD. Recording it
    raises the kennel's occupied_slots by one and increments the parent case's
    version by one."

    Design: Difficulty/compensating_invariant/kennel_occupied_slots_conserved
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-5b")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-05T00:00:00Z")
    set_clock(api, "2026-03-05T00:00:00Z")
    validate_success(api.release_impound(impound["id"], {"disposition": "REDEEMED"}, SUPERVISOR))
    assert validate_success(api.get_kennel(kennel["id"], SUPERVISOR))["occupied_slots"] == 0


# ==========================================================================
# Corner: cross_cutting (optimistic concurrency)
# ==========================================================================
def test_stale_case_version_on_second_impound_rejected(api):
    """PRD 2.8: "Every impound-creation request must carry expected_case_version,
    the version of the target Case as the client last observed it. If
    expected_case_version does not equal the case's current version, the creation
    is rejected with ERR_STALE_CASE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/impound_create_stale_case_version_conflict
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel1 = make_kennel(api, code="K-A")
    kennel2 = make_kennel(api, code="K-B")
    stale_version = ctx["case_version"]
    make_impound(api, ctx["case"]["id"], kennel1["id"], stale_version,
                 impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-05T00:00:00Z")
    # Second impound in a DIFFERENT kennel (so kennel overlap is not the cause),
    # still carrying the pre-impound1 version.
    resp = api.create_impound(create_impound_payload(
        ctx["case"]["id"], kennel2["id"], stale_version,
        impounded_at="2026-03-01T00:00:00Z", hold_until="2026-03-05T00:00:00Z"), SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


# ==========================================================================
# Corner: errors
# ==========================================================================
def test_release_missing_impound_returns_404(api):
    """PRD 2.6: "the first unresolved id yields the matching not-found error
    (ERR_COMPLAINT_NOT_FOUND, ERR_OFFICER_NOT_FOUND, ERR_KENNEL_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND, ERR_CASE_NOT_FOUND, ERR_QUARANTINE_HOLD_NOT_FOUND,
    ERR_IMPOUND_NOT_FOUND, ERR_CITATION_NOT_FOUND, or
    ERR_RABIES_REPORT_NOT_FOUND), all 404."

    Design: Corner/errors/impound_release_not_found
    """
    resp = api.release_impound(NON_EXISTENT_UUID, {"disposition": "REDEEMED"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_IMPOUND_NOT_FOUND)
