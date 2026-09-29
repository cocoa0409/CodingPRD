"""Pytest configuration for the Draft & Combine Operations compliance suite.

Re-exports the shared client fixture, the opaque-role header fixtures and the
composite state fixtures so every test module can request them by name. The
three entity-backed roles have no standalone fixture: a ``ClubGM``,
``ClubMedicalDirector`` or ``ProspectAgent`` must always act as a real club or
prospect id, so tests build those headers from the entity under test with
``make_club_gm_headers`` / ``make_club_medical_director_headers`` /
``make_prospect_agent_headers``.
"""

from test_helpers.fixtures import (  # noqa: F401
    admin_headers,
    api,
    combine_week,
    combine_week_start,
    combine_week_with_station,
    committee_headers,
    completed_medical_exam,
    cycle_setup,
    cycle_with_two_clubs,
    declaration_open,
    draft_live,
    draft_live_on_clock,
    examiner_headers,
    first_selection,
    granted_share,
    medical_evaluation,
    order_final,
    order_pending,
    seven_round_order_final,
    signed_drafted_contract,
    udfa_window,
    waiver_under_review,
)
