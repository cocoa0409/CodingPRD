"""
Shared test-suite plumbing for the Individual Artist Fellowship Grants API.

The harness restarts the API server against an empty database before every
individual test, so there is no cross-test state to reset here. What this module
provides is the handful of literals and tiny builders that more than one test
file needs, so no test re-invents a setup chain that `test_helpers.fixtures`
already owns.
"""

from typing import Dict, List, Optional

from test_helpers import (
    PROGRAM_OFFICER,
    api_client,
    get_success_data,
)

# A well-formed UUID that names no row in any collection.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

# The value a decline, a rescission or a forfeiture must restore a cycle to when
# nothing else is committed against a 6,000,000-cent appropriation.
FULL_BUDGET_CENTS = 6_000_000


def nominate(
    panel_id: str,
    person_email: str,
    full_name: str,
    region: str,
    expertise_codes: Optional[List[str]] = None,
    is_chair: bool = False,
) -> str:
    """Nominate one panelist onto a forming panel and return its id."""
    return get_success_data(
        api_client.create_panelist(
            {
                "panel_id": panel_id,
                "person_email": person_email,
                "full_name": full_name,
                "region": region,
                "expertise_codes": expertise_codes or ["LITERARY_ARTS"],
                "is_chair": is_chair,
            },
            PROGRAM_OFFICER,
        )
    )["id"]


def seat(panelist_id: str) -> Dict:
    """Seat a nominated panelist and return the updated panelist row."""
    return get_success_data(api_client.seat_panelist(panelist_id, PROGRAM_OFFICER))


def create_panel(
    cycle_id: str,
    discipline_category_id: str,
    required_seats: int = 3,
    required_regions: Optional[List[str]] = None,
    window_start: str = "2026-11-01T00:00:00Z",
    window_end: str = "2026-12-01T00:00:00Z",
) -> str:
    """Create one FORMING panel with an explicit deliberation window."""
    return get_success_data(
        api_client.create_panel(
            {
                "cycle_id": cycle_id,
                "discipline_category_id": discipline_category_id,
                "required_seats": required_seats,
                "required_regions": required_regions or ["NORTH", "CENTRAL", "SOUTH"],
                "deliberation_window_start": window_start,
                "deliberation_window_end": window_end,
            },
            PROGRAM_OFFICER,
        )
    )["id"]


def register_artist(
    legal_name: str,
    email: str,
    residency_start_date: str,
    region: str,
    residency_county: str = "Harbor",
    tin_status: str = "ON_FILE",
    is_enrolled_student: bool = False,
) -> str:
    """Register one artist and return its id."""
    return get_success_data(
        api_client.create_artist(
            {
                "legal_name": legal_name,
                "email": email,
                "residency_start_date": residency_start_date,
                "residency_county": residency_county,
                "region": region,
                "is_enrolled_student": is_enrolled_student,
                "tin_status": tin_status,
            },
            PROGRAM_OFFICER,
        )
    )["id"]


def build_application(
    cycle_id: str,
    discipline_category_id: str,
    artist_id: str,
    headers: Dict[str, str],
    statement: str = "Prose poems about harbour towns and the ferries that no longer run.",
    narrative: str = "Twelve years of small-press publication and two library residencies.",
    page_counts=(11, 8),
    submit: bool = True,
) -> str:
    """Create a draft application, attach manuscript samples and optionally submit."""
    application_id = get_success_data(
        api_client.create_application(
            {
                "cycle_id": cycle_id,
                "discipline_category_id": discipline_category_id,
                "artist_id": artist_id,
                "artist_statement": statement,
                "career_narrative": narrative,
            },
            headers,
        )
    )["id"]
    for ordinal, pages in enumerate(page_counts or (), start=1):
        get_success_data(
            api_client.create_work_sample(
                {
                    "application_id": application_id,
                    "medium": "MANUSCRIPT_PAGES",
                    "ordinal": ordinal,
                    "page_count": pages,
                    "contains_identifying_metadata": False,
                },
                headers,
            )
        )
    if submit:
        get_success_data(api_client.submit_application(application_id, headers))
    return application_id
