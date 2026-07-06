"""DMCA takedown / counter-notice state gating.

Covers Difficulty queue instance counter_notice_requires_takedown_effective and
the restore-from-effective invalid-state corner instance.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty — counter_notice_requires_takedown_effective
# ==========================================================================
def test_counter_notice_on_filed_takedown_rejected(api, complainant_headers, rightsholder_headers):
    """PRD §3.8: "A counter-notice may only be filed while the takedown is EFFECTIVE;
    filing against a takedown in any other state is rejected with
    ERR_TAKEDOWN_NOT_EFFECTIVE."

    Design: Difficulty/cross_entity_state_dependency/counter_notice_requires_takedown_effective
    """
    work = fx.create_work(work_type="VISUAL_ARTS")
    td = fx.get_success_data(
        api.create_dmca_takedown(fac.create_dmca_takedown_payload(work["id"]), complainant_headers)
    )  # FILED, not processed
    resp = api.create_counter_notice(fac.create_counter_notice_payload(td["id"]), rightsholder_headers)
    validate_error(resp, ApiErrorId.ERR_TAKEDOWN_NOT_EFFECTIVE)


def test_counter_notice_on_effective_takedown_succeeds(api, rightsholder_headers):
    """PRD §3.8: "Filing a counter-notice creates it in FORWARDED ... and forwards it
    to the complainant: as a side effect the takedown moves from EFFECTIVE to
    COUNTERED."

    Design: Difficulty/cross_entity_state_dependency/counter_notice_requires_takedown_effective
    """
    _work, td = fx.setup_effective_takedown()
    cn = validate_success(
        api.create_counter_notice(fac.create_counter_notice_payload(td["id"]), rightsholder_headers), 201
    )
    assert cn["status"] == "FORWARDED"
    assert fx.get_success_data(api.get_dmca_takedown(td["id"], rightsholder_headers))["status"] == "COUNTERED"


# ==========================================================================
# Corner — restore from EFFECTIVE (wrong source state)
# ==========================================================================
def test_restore_from_effective_rejected(api, examiner_headers):
    """PRD §3.8: "State-transition attempts made from the wrong source state —
    processing something that is not FILED, restoring something that is not
    COUNTERED, and so on — are rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/dmca_restore_from_effective_returns_invalid_state
    """
    _work, td = fx.setup_effective_takedown()  # EFFECTIVE, no counter-notice
    validate_error(api.restore_dmca_takedown(td["id"], examiner_headers), ApiErrorId.ERR_INVALID_STATE)
