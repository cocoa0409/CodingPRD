"""Each role is confined to the operations §4 lists for it, and the authentication check runs ahead
of the authorisation check, so a request with no `X-User-ID` answers 401 even where the role fits."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    camp_payload,
    medication_record_payload,
    standards_set_payload,
    state_license_payload,
)
from test_helpers.test_users import (
    STATE_AGENT_HEADERS,
    headers_without_user_id,
    make_camp_director_headers,
    make_visitor_headers,
)
from test_helpers.types import (
    AdministeredByRole,
    CampType,
    Certification,
    HealthStaffingLevel,
    MedicationClass,
    PopulationServed,
    Role,
    StateLicenseStatus,
    VisitorStatus,
)
from prd_bench_local_runner.testing import validate_error, validate_success


def _one_camp_and_one_visitor(api):
    """Both rows are the national office's creations, and nothing else exists."""
    fx.reset_clock(api)
    camp = fx.register_camp(
        api,
        name="Rbac Camp",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        health_staffing_level=HealthStaffingLevel.RN_ONSITE,
    )
    visitor = fx.add_visitor(
        api, "Rbac Visitor", certifications=[Certification.LEAD_VISITOR]
    )
    return camp, visitor


def test_a_camp_identity_cannot_reach_the_operations_reserved_to_others(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not among the roles
    authorised for the target endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/other_roles_exclusive_operations_cannot_be_reached_and_a_missing_x_user_header_returns_401
    """
    camp, _visitor = _one_camp_and_one_visitor(api)
    director = make_camp_director_headers(camp["id"])

    # Registration belongs to the national office.
    validate_error(
        api.create_camp(
            camp_payload(
                name="Self Registered Camp",
                camp_type=CampType.DAY,
                state_code="OH",
                population_served=PopulationServed.YOUTH_ONLY,
            ),
            director,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # The licence axis belongs to the state, even on the director's own camp.
    validate_error(
        api.patch_state_license(
            camp["id"], state_license_payload(StateLicenseStatus.ACTIVE), director
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # Health care staff share the camp identity but not this operation.
    validate_error(
        api.create_medication_record(
            medication_record_payload(
                camp["id"],
                camper_reference="CR-R1",
                medication_class=MedicationClass.OTC,
                dose_units=1,
                administered_at="2026-08-01T09:00:00.000Z",
                administered_by_role=AdministeredByRole.RN,
            ),
            director,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    held = fx.read_camp(api, camp["id"])
    assert held["state_license_status"] == StateLicenseStatus.NONE
    assert held["version"] == camp["version"]
    assert fx.list_medication_records_for_camp(api, camp["id"])[1]["total_count"] == 0


def test_neither_the_visitor_nor_the_licensing_agent_gains_standing_it_lacks(api):
    """PRD §2.1: "The same separation is expressed structurally elsewhere — a `Visitor` scores
    standards but never adjudicates a written plan, a correction plan or a decision; a
    `CampDirector` authors self-assessments and correction plans but never verifies them; a
    `StateLicensingAgent` moves the licensing axis and reads for oversight but has no standing in
    the accreditation decision at all."

    Design: Corner/rbac/other_roles_exclusive_operations_cannot_be_reached_and_a_missing_x_user_header_returns_401
    """
    _camp, visitor = _one_camp_and_one_visitor(api)

    # Roster removal is the office's call, not the visitor's.
    validate_error(
        api.deactivate_visitor(
            visitor["id"],
            {"deactivated_reason": "self removal"},
            make_visitor_headers(visitor["id"]),
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # The roster is not among the licensing agent's shared reads.
    validate_error(
        api.get_visitor(visitor["id"], STATE_AGENT_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # Nor is the standards catalogue.
    validate_error(
        api.create_standards_set(
            standards_set_payload("ACA-2026-RBX", 2026), STATE_AGENT_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    held = fx.read_visitor(api, visitor["id"])
    assert held["status"] == VisitorStatus.ACTIVE
    assert held["deactivated_reason"] is None
    assert held["version"] == visitor["version"]


def test_a_missing_user_header_answers_before_the_role_list_is_consulted(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is any string other than those
    five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/other_roles_exclusive_operations_cannot_be_reached_and_a_missing_x_user_header_returns_401
    """
    camp, _visitor = _one_camp_and_one_visitor(api)

    # The camp read does list CampDirector, so only the authentication rule can answer.
    validate_error(
        api.get_camp(camp["id"], headers_without_user_id(Role.CAMP_DIRECTOR)),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    # With the identity supplied the same read succeeds.
    readable = validate_success(
        api.get_camp(camp["id"], make_camp_director_headers(camp["id"]))
    )
    assert readable["id"] == camp["id"]
