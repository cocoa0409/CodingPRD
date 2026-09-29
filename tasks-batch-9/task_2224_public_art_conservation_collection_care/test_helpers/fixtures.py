"""Composite setup helpers.

The register starts empty for every test, so each helper below builds the state
it names from scratch through the API itself.  Every helper unwraps its
responses with `get_success_data()` so that a broken setup fails loudly at the
line that broke rather than deep inside an assertion, and every helper takes
`**overrides` (or per-entity override dictionaries) so a caller can vary one
field of an otherwise canonical scenario.

Identity is threaded, never assumed: helpers that act as an artist or as a
conservation vendor build their headers from the entity row they just created.
"""

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    artist_consultation_payload,
    artist_payload,
    artwork_payload,
    assessment_photo_payload,
    condition_assessment_payload,
    conservator_payload,
    damage_incident_payload,
    deaccession_case_payload,
    funding_allocation_payload,
    funding_pool_payload,
    line_item_payload,
    maintenance_protocol_payload,
    maintenance_visit_payload,
    moral_rights_notice_payload,
    site_payload,
    treatment_proposal_payload,
)
from .test_users import (
    COMMISSION_MEMBER_USER_IDS,
    TEST_USERS,
    make_artist_representative_headers,
    make_commission_member_headers,
    make_conservator_vendor_headers,
)

DEFAULT_PHOTO_VIEW_CODES = ["FRONT", "SIDE", "DETAIL"]

# The two canonical cost lines of the reference estimate: 12.5 hours of COATING
# work with 82500 cents of materials, then 12.5 hours of SURFACE work with
# 15000 cents of materials.
DEFAULT_PROPOSAL_LINES = [
    {"labor_hours": 12.5, "complexity_class": "COATING", "materials_cents": 82_500},
    {"labor_hours": 12.5, "complexity_class": "SURFACE", "materials_cents": 15_000},
]


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> dict:
    """Move the logical clock; the manager alone holds this capability."""
    return get_success_data(
        api.set_current_utc({"to_iso8601": to_iso8601}, TEST_USERS["manager_headers"])
    )


# --------------------------------------------------------------------------
# Tier 1 — single rows
# --------------------------------------------------------------------------
def create_artist(api, **overrides) -> dict:
    return get_success_data(
        api.create_artist(artist_payload(**overrides), TEST_USERS["registrar_headers"]),
        201,
    )


def create_site(api, **overrides) -> dict:
    return get_success_data(
        api.create_site(site_payload(**overrides), TEST_USERS["registrar_headers"]), 201
    )


def create_artwork(api, artist_id: str, site_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_artwork(
            artwork_payload(artist_id, site_id, **overrides),
            TEST_USERS["registrar_headers"],
        ),
        201,
    )


def create_conservator(api, **overrides) -> dict:
    return get_success_data(
        api.create_conservator(
            conservator_payload(**overrides), TEST_USERS["manager_headers"]
        ),
        201,
    )


def create_protocol(api, **overrides) -> dict:
    return get_success_data(
        api.create_maintenance_protocol(
            maintenance_protocol_payload(**overrides),
            TEST_USERS["chief_conservator_headers"],
        ),
        201,
    )


def create_pool(api, **overrides) -> dict:
    return get_success_data(
        api.create_funding_pool(
            funding_pool_payload(**overrides), TEST_USERS["finance_headers"]
        ),
        201,
    )


# --------------------------------------------------------------------------
# Tier 2 — the register: artist, site and an accessioned work
# --------------------------------------------------------------------------
def setup_register(api, artist=None, site=None, artwork=None) -> dict:
    """An artist of record, an installation site and one work accessioned there."""
    artist_row = create_artist(api, **(artist or {}))
    site_row = create_site(api, **(site or {}))
    artwork_row = create_artwork(
        api, artist_row["id"], site_row["id"], **(artwork or {})
    )
    return {"artist": artist_row, "site": site_row, "artwork": artwork_row}


# --------------------------------------------------------------------------
# Tier 3 — condition surveys through their lifecycle
# --------------------------------------------------------------------------
def create_assessment(api, artwork_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_condition_assessment(
            condition_assessment_payload(artwork_id, **overrides),
            headers or TEST_USERS["surveyor_headers"],
        ),
        201,
    )


def attach_photos(api, assessment_id: str, view_codes=None, headers=None) -> dict:
    """Attach one photographic record per view code; three is the minimum."""
    headers = headers or TEST_USERS["surveyor_headers"]
    result = None
    for view_code in view_codes or DEFAULT_PHOTO_VIEW_CODES:
        result = get_success_data(
            api.add_assessment_photo(
                assessment_id, assessment_photo_payload(view_code), headers
            )
        )
    return result


def setup_assessment_submitted(
    api, artwork_id: str, submitter_headers=None, view_codes=None, **overrides
) -> dict:
    """A survey documented with three photographs and submitted for review."""
    submitter_headers = submitter_headers or TEST_USERS["surveyor_headers"]
    assessment = create_assessment(
        api, artwork_id, headers=submitter_headers, **overrides
    )
    attach_photos(
        api, assessment["id"], view_codes=view_codes, headers=submitter_headers
    )
    return get_success_data(
        api.submit_condition_assessment(assessment["id"], {}, submitter_headers)
    )


def setup_assessment_finalized(
    api,
    artwork_id: str,
    submitter_headers=None,
    finalizer_headers=None,
    view_codes=None,
    **overrides,
) -> dict:
    """A finalized survey: the index is computed and Cascade A has run."""
    assessment = setup_assessment_submitted(
        api,
        artwork_id,
        submitter_headers=submitter_headers,
        view_codes=view_codes,
        **overrides,
    )
    return get_success_data(
        api.finalize_condition_assessment(
            assessment["id"],
            {},
            finalizer_headers or TEST_USERS["chief_conservator_headers"],
        )
    )


# --------------------------------------------------------------------------
# Tier 3 — proposals, money and the approval path
# --------------------------------------------------------------------------
def current_artwork_version(api, artwork_id: str) -> int:
    """Re-read the work; drafting a proposal moves its own version."""
    return get_success_data(
        api.get_artwork(artwork_id, TEST_USERS["chief_conservator_headers"])
    )["version"]


def current_pool_version(api, pool_id: str) -> int:
    """Re-read the pool; every reservation and settlement moves its version."""
    return get_success_data(
        api.get_funding_pool(pool_id, TEST_USERS["finance_headers"])
    )["version"]


def create_proposal_with_lines(
    api,
    artwork_id: str,
    conservator_id: str,
    assessment_id: str,
    lines=None,
    **overrides,
) -> dict:
    """A draft proposal carrying the canonical two-line estimate."""
    payload = treatment_proposal_payload(
        artwork_id,
        conservator_id,
        assessment_id,
        current_artwork_version(api, artwork_id),
        **overrides,
    )
    proposal = get_success_data(
        api.create_treatment_proposal(payload, TEST_USERS["chief_conservator_headers"]),
        201,
    )
    result = proposal
    for line in DEFAULT_PROPOSAL_LINES if lines is None else lines:
        result = get_success_data(
            api.add_proposal_line_item(
                proposal["id"],
                line_item_payload(**line),
                TEST_USERS["chief_conservator_headers"],
            )
        )
    return result


def submit_proposal(api, proposal_id: str) -> dict:
    return get_success_data(
        api.submit_treatment_proposal(
            proposal_id, {}, TEST_USERS["chief_conservator_headers"]
        )
    )


def reserve_allocation(
    api,
    pool_id: str,
    purpose: str = "TREATMENT",
    amount_cents: int = None,
    proposal_id: str = None,
    visit_id: str = None,
    **overrides,
) -> dict:
    """Reserve money against a pool, re-reading its version immediately first."""
    payload = funding_allocation_payload(
        pool_id, current_pool_version(api, pool_id), purpose=purpose, **overrides
    )
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    if proposal_id is not None:
        payload["proposal_id"] = proposal_id
    if visit_id is not None:
        payload["visit_id"] = visit_id
    return get_success_data(
        api.create_funding_allocation(payload, TEST_USERS["finance_headers"]), 201
    )


def setup_submitted_proposal(
    api,
    artist=None,
    site=None,
    artwork=None,
    conservator=None,
    assessment=None,
    proposal=None,
    lines=None,
    pool=None,
) -> dict:
    """A submitted proposal with a finalized survey behind it and a funded pool."""
    register = setup_register(api, artist=artist, site=site, artwork=artwork)
    conservator_row = create_conservator(api, **(conservator or {}))
    pool_row = create_pool(api, **(pool or {}))
    assessment_row = setup_assessment_finalized(
        api, register["artwork"]["id"], **(assessment or {})
    )
    proposal_row = create_proposal_with_lines(
        api,
        register["artwork"]["id"],
        conservator_row["id"],
        assessment_row["id"],
        lines=lines,
        **(proposal or {}),
    )
    proposal_row = submit_proposal(api, proposal_row["id"])
    return {
        **register,
        "conservator": conservator_row,
        "pool": pool_row,
        "assessment": assessment_row,
        "proposal": proposal_row,
    }


def setup_approved_proposal(
    api,
    artist=None,
    site=None,
    artwork=None,
    conservator=None,
    assessment=None,
    proposal=None,
    lines=None,
    pool=None,
    reserve_cents: int = 700_000,
) -> dict:
    """A proposal carried all the way to APPROVED: funded, pinned, Cascade C run."""
    state = setup_submitted_proposal(
        api,
        artist=artist,
        site=site,
        artwork=artwork,
        conservator=conservator,
        assessment=assessment,
        proposal=proposal,
        lines=lines,
        pool=pool,
    )
    state["allocation"] = reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=reserve_cents,
        proposal_id=state["proposal"]["id"],
    )
    state["proposal"] = get_success_data(
        api.approve_treatment_proposal(
            state["proposal"]["id"], {}, TEST_USERS["manager_headers"]
        )
    )
    return state


def start_execution(api, proposal_id: str, conservator_id: str) -> dict:
    """The engaged vendor, and no one else, starts the treatment."""
    return get_success_data(
        api.start_treatment_execution(
            proposal_id, {}, make_conservator_vendor_headers(conservator_id)
        )
    )


# --------------------------------------------------------------------------
# Tier 3 — routine care visits
# --------------------------------------------------------------------------
def schedule_visit(api, artwork_id: str, protocol_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_maintenance_visit(
            maintenance_visit_payload(artwork_id, protocol_id, **overrides),
            TEST_USERS["crew_headers"],
        ),
        201,
    )


def setup_scheduled_visit(
    api, artist=None, site=None, artwork=None, protocol=None, visit=None
) -> dict:
    """A work under a routine care protocol with one visit scheduled."""
    register = setup_register(api, artist=artist, site=site, artwork=artwork)
    protocol_row = create_protocol(api, **(protocol or {}))
    visit_row = schedule_visit(
        api, register["artwork"]["id"], protocol_row["id"], **(visit or {})
    )
    return {**register, "protocol": protocol_row, "visit": visit_row}


def setup_visit_in_progress(api, **kwargs) -> dict:
    """A visit started inside its own window."""
    state = setup_scheduled_visit(api, **kwargs)
    set_clock(api, state["visit"]["window_start"])
    state["visit"] = get_success_data(
        api.start_maintenance_visit(state["visit"]["id"], {}, TEST_USERS["crew_headers"])
    )
    return state


# --------------------------------------------------------------------------
# Tier 3 — consultations and statutory notices
# --------------------------------------------------------------------------
def open_consultation(api, artwork_id: str, artist_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_artist_consultation(
            artist_consultation_payload(artwork_id, artist_id, **overrides),
            TEST_USERS["chief_conservator_headers"],
        ),
        201,
    )


def answer_consultation(api, consultation_id: str, artist_id: str, response: str) -> dict:
    """The artist answers through their representative, for their own work only."""
    return get_success_data(
        api.respond_to_consultation(
            consultation_id,
            {"response": response},
            make_artist_representative_headers(artist_id),
        )
    )


def send_notice(api, artwork_id: str, artist_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_moral_rights_notice(
            moral_rights_notice_payload(artwork_id, artist_id, **overrides),
            TEST_USERS["manager_headers"],
        ),
        201,
    )


def setup_acknowledged_notice(
    api, artwork_id: str, artist_id: str, action_type: str = "RELOCATION"
) -> dict:
    """A notice the artist has acknowledged; its waiting period still runs."""
    notice = send_notice(api, artwork_id, artist_id, action_type=action_type)
    return get_success_data(
        api.acknowledge_moral_rights_notice(
            notice["id"], {}, make_artist_representative_headers(artist_id)
        )
    )


# --------------------------------------------------------------------------
# Tier 4/5 — deaccession cases up to and past the ballot
# --------------------------------------------------------------------------
def open_case(api, artwork_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_deaccession_case(
            deaccession_case_payload(artwork_id, **overrides),
            TEST_USERS["manager_headers"],
        ),
        201,
    )


def setup_case_at_board_review(api, artwork_id: str, **overrides) -> dict:
    """A case whose public comment period has opened and then closed."""
    case = open_case(api, artwork_id, **overrides)
    case = get_success_data(
        api.advance_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"])
    )
    set_clock(api, case["public_comment_closes_at"])
    return get_success_data(
        api.advance_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"])
    )


def cast_ballots(api, case_id: str, ballots) -> dict:
    """Cast one ballot per commission member, in member order."""
    result = None
    for member_user_id, ballot in zip(COMMISSION_MEMBER_USER_IDS, ballots):
        result = get_success_data(
            api.cast_deaccession_ballot(
                case_id,
                {"ballot": ballot},
                make_commission_member_headers(member_user_id),
            )
        )
    return result


def setup_case_approved(api, artwork_id: str, **overrides) -> dict:
    """A case carried to APPROVED by five approving commission ballots."""
    case = setup_case_at_board_review(api, artwork_id, **overrides)
    return cast_ballots(api, case["id"], ["APPROVE"] * 5)


# --------------------------------------------------------------------------
# Tier 3 — damage incidents and claims
# --------------------------------------------------------------------------
def report_incident(api, artwork_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_damage_incident(
            damage_incident_payload(artwork_id, **overrides),
            TEST_USERS["registrar_headers"],
        ),
        201,
    )


def setup_incident_triaged(
    api, artwork_id: str, triage_class: str = "CONSERVATOR_TREATMENT", **overrides
) -> dict:
    """A reported incident triaged onto a response route, ready to be claimed."""
    incident = report_incident(api, artwork_id, **overrides)
    return get_success_data(
        api.triage_damage_incident(
            incident["id"],
            {"triage_class": triage_class},
            TEST_USERS["chief_conservator_headers"],
        )
    )


def file_claim(api, incident_id: str, claim_basis: str, **overrides) -> dict:
    payload = {"claim_basis": claim_basis}
    payload.update(overrides)
    return get_success_data(
        api.file_insurance_claim(incident_id, payload, TEST_USERS["finance_headers"])
    )


# --------------------------------------------------------------------------
# Convenience reads
# --------------------------------------------------------------------------
def read_artwork(api, artwork_id: str) -> dict:
    return get_success_data(
        api.get_artwork(artwork_id, TEST_USERS["registrar_headers"])
    )


def read_site(api, site_id: str) -> dict:
    return get_success_data(api.get_site(site_id, TEST_USERS["registrar_headers"]))


def read_pool(api, pool_id: str) -> dict:
    return get_success_data(api.get_funding_pool(pool_id, TEST_USERS["finance_headers"]))


def read_allocation(api, allocation_id: str) -> dict:
    return get_success_data(
        api.get_funding_allocation(allocation_id, TEST_USERS["finance_headers"])
    )


def read_proposal(api, proposal_id: str) -> dict:
    return get_success_data(
        api.get_treatment_proposal(proposal_id, TEST_USERS["manager_headers"])
    )


def read_visit(api, visit_id: str) -> dict:
    return get_success_data(
        api.get_maintenance_visit(visit_id, TEST_USERS["crew_headers"])
    )


def read_assessment(api, assessment_id: str) -> dict:
    return get_success_data(
        api.get_condition_assessment(
            assessment_id, TEST_USERS["chief_conservator_headers"]
        )
    )


def read_case(api, case_id: str) -> dict:
    return get_success_data(
        api.get_deaccession_case(case_id, TEST_USERS["manager_headers"])
    )


def read_consultation(api, consultation_id: str) -> dict:
    return get_success_data(
        api.get_artist_consultation(
            consultation_id, TEST_USERS["chief_conservator_headers"]
        )
    )


def read_notice(api, notice_id: str) -> dict:
    return get_success_data(
        api.get_moral_rights_notice(notice_id, TEST_USERS["manager_headers"])
    )


def read_incident(api, incident_id: str) -> dict:
    return get_success_data(
        api.get_damage_incident(incident_id, TEST_USERS["registrar_headers"])
    )


def read_conservator(api, conservator_id: str) -> dict:
    return get_success_data(
        api.get_conservator(conservator_id, TEST_USERS["manager_headers"])
    )


def read_artist(api, artist_id: str) -> dict:
    return get_success_data(api.get_artist(artist_id, TEST_USERS["registrar_headers"]))
