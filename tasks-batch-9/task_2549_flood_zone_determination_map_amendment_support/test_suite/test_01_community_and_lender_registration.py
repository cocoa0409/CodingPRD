"""Registering the parties: NFIP communities, their coverage gate, and lenders.

These are the two registrations everything else in the API hangs off, so the
checks here pin what the server derives at creation, what it defaults, who may
write it and who may read it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ALL_ROLES,
    ApiErrorId,
    api_client,
    assert_community,
    assert_lender,
    create_community,
    create_lender,
    create_property,
    make_agency_headers,
    make_analyst_headers,
    make_borrower_headers,
    make_lender_headers,
    make_reviewer_headers,
    open_folio,
    publish_panel,
    role_only_headers,
    set_clock,
    user_id_only_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
CLOCK_STAMP = "2026-08-01T00:00:00.000Z"


def test_community_creation_returns_every_declared_field():
    """A fully specified community registration echoes all nine business fields
    and derives ``coverage_availability`` rather than accepting it.

    PRD §3.1: "A `ProviderAnalyst` registers one by supplying the community's six-character NFIP community identification number as `community_id_code`, which must be unique across all communities; the community `name` as printed on the FIRM; and a two-letter USPS `state_code`, which must be one of `CA`, `FL`, `TX` or `NC`."
    PRD §3.1: "On creation the system derives `coverage_availability` by the clause ladder of Section 2.9, sets `last_participation_change_at` to the current logical instant — which at creation is the same instant as `created_at` — and initialises `active_folio_count` to 0."
    PRD §2.9: "Each community carries a `participation_status` describing its standing in the national program and a `cbrs_flag` recording whether it sits inside a Coastal Barrier Resources System unit, and from those two inputs the system derives `coverage_availability` by evaluating the following clauses from top to bottom and taking the first that matches: if `cbrs_flag` is true the availability is `UNAVAILABLE`; otherwise if `participation_status` is `SUSPENDED`, `NON_PARTICIPATING` or `WITHDRAWN` the availability is `UNAVAILABLE`; otherwise if `participation_status` is `EMERGENCY` the availability is `EMERGENCY_LIMITS_ONLY`; otherwise if `participation_status` is `PROBATION` the availability is `FULL_WITH_SURCHARGE`; otherwise — that is, when `participation_status` is `REGULAR` — the availability is `FULL`."
    PRD §2.4: "Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`."

    Design: Corner/entities/corner_community_creation_returns_every_declared_field
    """
    set_clock(CLOCK)
    response = api_client.create_community(
        {
            "community_id_code": "125129",
            "name": "Coastal County FL",
            "state_code": "FL",
            "participation_status": "PROBATION",
            "cbrs_flag": False,
            "probation_surcharge_cents": 5000,
        },
        headers=make_analyst_headers(),
    )
    community = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert_community(community)

    assert community["community_id_code"] == "125129"
    assert community["name"] == "Coastal County FL"
    assert community["state_code"] == "FL"
    assert community["participation_status"] == "PROBATION"
    assert community["cbrs_flag"] is False
    assert community["probation_surcharge_cents"] == 5000

    # PROBATION falls through the cbrs and unavailable clauses to FULL_WITH_SURCHARGE.
    assert community["coverage_availability"] == "FULL_WITH_SURCHARGE"
    assert community["active_folio_count"] == 0
    assert community["last_participation_change_at"] == CLOCK_STAMP

    assert community["version"] == 1
    assert community["created_at"] == CLOCK_STAMP
    assert community["updated_at"] == CLOCK_STAMP
    assert "_" not in community["id"] and community["id"].count("-") == 4


def test_community_optional_inputs_take_declared_defaults():
    """Omitting the three optional inputs yields REGULAR / false / 0, so the
    availability lands on FULL; flipping only ``cbrs_flag`` proves the default.

    PRD §3.1: "Three further inputs are optional at registration and each has a default: `participation_status` defaults to `REGULAR` and must be one of `REGULAR`, `EMERGENCY`, `PROBATION`, `SUSPENDED`, `NON_PARTICIPATING` or `WITHDRAWN`; `cbrs_flag` defaults to false and records whether the community sits inside a Coastal Barrier Resources System unit; and `probation_surcharge_cents` defaults to 0, must be zero or greater, and carries the annual probation surcharge."
    PRD §2.9: "The clause order matters: a community inside a Coastal Barrier Resources System unit whose `participation_status` is `REGULAR` is still `UNAVAILABLE`, because federal flood insurance is unavailable in such a unit regardless of participation standing."

    Design: Corner/entities/corner_community_optional_inputs_take_declared_defaults
    """
    set_clock(CLOCK)
    defaulted = validate_success(
        api_client.create_community(
            {
                "community_id_code": "125129",
                "name": "Coastal County FL",
                "state_code": "FL",
            },
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert defaulted["participation_status"] == "REGULAR"
    assert defaulted["cbrs_flag"] is False
    assert defaulted["probation_surcharge_cents"] == 0
    assert defaulted["coverage_availability"] == "FULL"

    barrier = validate_success(
        api_client.create_community(
            {
                "community_id_code": "125130",
                "name": "Barrier Island FL",
                "state_code": "FL",
                "cbrs_flag": True,
            },
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert barrier["participation_status"] == "REGULAR"
    assert barrier["cbrs_flag"] is True
    # The first clause fires before the REGULAR fall-through.
    assert barrier["coverage_availability"] == "UNAVAILABLE"


def test_lender_detail_get_returns_stored_row():
    """The lender detail read echoes what the registration stored, including both
    authorization flags and the computed count, and mutates nothing.

    PRD §3.1: "A `ProviderAnalyst` supplies the institution `name` and a `contact_email` used as the delivery address for compliance notices, and may override two flags that both default to true: `force_placement_authorized_flag` is false when the lender's servicing agreement forbids force placement, and `escrow_servicing_flag` is false when the lender does not escrow and therefore may not have force-placed premiums debited."
    PRD §3.1: "A newly registered lender has `open_force_placement_count` initialised to 0; thereafter that field is a re-count of the loan folios naming this lender whose `insurance_status` is `FORCE_PLACED`, and it is re-derived whenever a force placement is executed or settled."
    PRD §2.4: "`version` starts at 1 when the row is created and increases by exactly 1 on every mutation of that row; `updated_at` is refreshed to the current logical instant on every mutation."

    Design: Corner/entities/corner_lender_detail_get_returns_stored_row
    """
    set_clock(CLOCK)
    created = validate_success(
        api_client.create_lender(
            {
                "name": "First Coastal Bank",
                "contact_email": "ops@firstcoastal.example",
                "force_placement_authorized_flag": True,
                "escrow_servicing_flag": True,
            },
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert created["version"] == 1

    lender = validate_success(
        api_client.get_lender(created["id"], headers=make_lender_headers(created["id"]))
    )
    assert_lender(lender)
    assert lender["name"] == "First Coastal Bank"
    assert lender["contact_email"] == "ops@firstcoastal.example"
    assert lender["force_placement_authorized_flag"] is True
    assert lender["escrow_servicing_flag"] is True
    assert lender["open_force_placement_count"] == 0

    # A read is not a mutation, so neither version nor updated_at moved.
    assert lender["version"] == 1
    assert lender["updated_at"] == lender["created_at"]


def test_write_without_acting_user_is_unauthenticated():
    """The identity gate is the first rung and it applies to writes only: the
    same body is 401 without an acting user and 201 with one, while list reads
    stay open with no ``X-User-ID`` at all.

    PRD §2.1: "`X-User-ID` must be present and non-empty on every request that is not a `GET`; read-only requests may omit it."
    PRD §2.1: "A request that fails either of these checks is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), whether the failure is a missing header, an empty header, or a role string outside the recognised five."
    PRD §2.5: "When one request violates two rules, the violation with the smaller priority number supplies both the `error_id` and the HTTP status of the response, and the lower-priority violation is never reported."

    Design: Corner/errors/corner_write_without_acting_user_is_unauthenticated
    """
    set_clock(CLOCK)
    payload = {
        "community_id_code": "125129",
        "name": "Coastal County FL",
        "state_code": "FL",
        "participation_status": "REGULAR",
    }

    # No X-User-ID on a write.
    validate_error(
        api_client.create_community(payload, headers=role_only_headers("ProviderAnalyst")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    # No X-User-Role: both headers together form the identity.
    validate_error(
        api_client.create_community(payload, headers=user_id_only_headers("analyst-1")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    # Priority 1 outranks the priority-4 shape check: an empty body still reports 401.
    validate_error(
        api_client.create_community({}, headers=role_only_headers("ProviderAnalyst")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    rows, meta = validate_paginated(
        api_client.list_communities(headers=role_only_headers("ProviderAnalyst"))
    )
    assert meta["total_count"] == 0, "a rejected write must not persist a row"
    assert rows == []

    community = validate_success(
        api_client.create_community(payload, headers=make_analyst_headers()), 201
    )
    rows, meta = validate_paginated(
        api_client.list_communities(headers=role_only_headers("Borrower"))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == community["id"]


def test_role_outside_the_endpoint_roles_is_forbidden():
    """Panel publication is authorised for the agency alone, and the role check
    fires ahead of foreign-key resolution.

    PRD §2.1: "Once the caller is authenticated, the role is matched against the set of roles authorised for the target operation as listed in Section 4; a caller whose role is not in that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/flood-zone/map-panels` | Publish a FIRM panel; first-sequence panels are created effective, later sequences enter the preliminary path | AgencyOfficer |"
    PRD §2.5: "Third (3) the caller's role must appear in the target endpoint's authorised role list, reporting `ERR_FORBIDDEN_ROLE`."
    PRD §3.2: "An initial FIRM is published, not revised: when `revision_sequence` is 1 the panel's `revision_status` is set directly to `EFFECTIVE` at creation rather than to `PRELIMINARY`, its `effective_date` is stored from the request body, `supersedes_panel_id` must be null, and no other panel with the same community and `map_panel_number` may already be `EFFECTIVE`."

    Design: Corner/errors/corner_role_outside_the_endpoint_roles_is_forbidden
    """
    set_clock(CLOCK)
    community = create_community()
    payload = {
        "community_id": community["id"],
        "map_panel_number": "12086C0312K",
        "revision_sequence": 1,
        "zone_code": "AE",
        "base_flood_elevation_ft": 7.75,
        "effective_date": "2020-06-05T00:00:00Z",
    }

    validate_error(
        api_client.create_map_panel(payload, headers=make_borrower_headers("borrower-a")),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    # Panel authorship is exclusive to the agency, not merely restricted to staff.
    validate_error(
        api_client.create_map_panel(payload, headers=make_analyst_headers()),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api_client.create_map_panel(payload, headers=make_reviewer_headers()),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    # Priority 3 precedes the priority-6 body foreign-key check.
    unknown_community = dict(payload, community_id="8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2")
    validate_error(
        api_client.create_map_panel(
            unknown_community, headers=make_borrower_headers("borrower-a")
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    panel = validate_success(
        api_client.create_map_panel(payload, headers=make_agency_headers()), 201
    )
    assert panel["revision_status"] == "EFFECTIVE"


def test_loan_side_roles_are_walled_off_from_directory_and_projection_reads():
    """The read grant carries per-role carve-outs: the borrower loses the lender
    directory and the projection, the lender loses only the projection, and every
    other read stays open to all five roles.

    PRD §4: "| GET | `/flood-zone/lenders` | List lenders | ProviderAnalyst, ProviderReviewer, AgencyOfficer, Lender |"
    PRD §4: "| GET | `/flood-zone/map-panels/{map_panel_id}/impact-analysis` | Read-only preliminary-map impact projection for a panel that has not yet become effective | ProviderAnalyst, ProviderReviewer, AgencyOfficer |"
    PRD §3.3: "A read-only projection capability, available to `ProviderAnalyst`, `ProviderReviewer` and `AgencyOfficer` callers only, evaluates a panel that has not yet gone live and reports the damage."
    PRD §3.5: "`compliance_posture` is `COMPLIANT`, because with no determination yet the required coverage is zero; and the community's `active_folio_count` is re-counted."

    Design: Corner/rbac/corner_loan_side_roles_are_walled_off_from_directory_and_projection_reads
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    first = publish_panel(community["id"])
    preliminary = publish_panel(
        community["id"],
        revision_sequence=2,
        supersedes_panel_id=first["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    prop = create_property(community["id"])
    folio = open_folio(lender["id"], prop["id"])

    lender_headers = make_lender_headers(lender["id"])
    borrower_headers = make_borrower_headers(folio["borrower_user_id"])

    # The lender directory is open to the lender and closed to the borrower.
    directory_row = validate_success(
        api_client.get_lender(lender["id"], headers=lender_headers)
    )
    assert directory_row["name"] == "First Coastal Bank"
    validate_error(
        api_client.get_lender(lender["id"], headers=borrower_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api_client.list_lenders(headers=borrower_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    # The projection is open to the three staff roles only.
    for headers in (make_analyst_headers(), make_reviewer_headers(), make_agency_headers()):
        projection = validate_success(
            api_client.get_impact_analysis(preliminary["id"], headers=headers)
        )
        assert projection["map_panel_id"] == preliminary["id"]
    # The carve-out is not an ownership rule: the owning lender is refused too.
    validate_error(
        api_client.get_impact_analysis(preliminary["id"], headers=lender_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api_client.get_impact_analysis(preliminary["id"], headers=borrower_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    # A folio read is not scoped to its own borrower, and the borrower keeps it.
    folio_read = validate_success(
        api_client.get_loan_folio(folio["id"], headers=borrower_headers)
    )
    assert folio_read["compliance_posture"] == "COMPLIANT"

    # Only the two carve-outs are withheld; the rest of the map is shared.
    for role in ALL_ROLES:
        headers = role_only_headers(role)
        validate_paginated(api_client.list_communities(headers=headers))
        panel_read = validate_success(
            api_client.get_map_panel(preliminary["id"], headers=headers)
        )
        assert panel_read["revision_status"] == "PRELIMINARY"
