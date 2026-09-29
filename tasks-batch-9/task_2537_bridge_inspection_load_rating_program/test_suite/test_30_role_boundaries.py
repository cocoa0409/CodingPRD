"""
Where each role's write surface stops: the permit officer's three verbs, the federal
reviewer's single one, the cross-role refusals that outrank every later check, and the
two duty separations that are keyed on the acting identity rather than on the role.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import (
    FHWA_REVIEWER_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    fhwa_reviewer_headers,
    make_district_engineer_headers,
    make_headers,
    permit_officer_headers,
    program_admin_headers,
)

WINDOW_START = "2026-09-02T08:00:00Z"
WINDOW_END = "2026-09-02T16:00:00Z"
OBSERVED_AT = "2026-09-02T10:00:00Z"

# Four axles that already sit on whole tenths, so the pinned per-axle rounding of
# PRD §3.7 leaves them alone and the gross weight is exactly the 36.0-ton
# rating-vehicle weight.
FOUR_AXLES = [10.0, 10.0, 10.0, 6.0]

THREE_GROUPS = (f.BASELINE_DECK, f.BASELINE_GIRDER, f.BASELINE_ABUTMENT)


# ─── The permit officer's three verbs ───────────────────────────────────────
def test_the_permit_officer_files_a_route_and_the_gross_weight_is_derived_at_filing(
    client, bridge
):
    """
    Filing is the officer's own write, and the two derived fields land in the same
    request while everything the analysis will decide is still deliberately unset.

    PRD §3.7: "Two fields are derived from the axle array at filing: `axle_count`, the
    number of entries, and `gross_weight_tons`."
    PRD §3.7: "A newly received application is `RECEIVED`, carries a
    `recommended_decision` of `PENDING` and a null `governing_analysis_min_rf`, and has
    no analysis rows at all."
    PRD §2.1: "When `X-User-Role` is `PermitOfficer`, `X-User-ID` is likewise an opaque
    operator identifier with no roster entry behind it and no ownership comparison."

    Design: Corner/rbac/permit_officer_owns_the_permit_lifecycle
    """
    permit = fx.receive_permit(
        client,
        "OW-2026-0015",
        [bridge["id"]],
        axle_loads_tons=FOUR_AXLES,
        carrier_name="Northline Heavy Haul",
        speed_category="NORMAL",
    )

    assert permit["status"] == "RECEIVED"
    assert permit["axle_count"] == 4
    assert permit["gross_weight_tons"] == 36.0
    a.assert_one_decimal(permit["gross_weight_tons"], "gross_weight_tons")
    assert permit["recommended_decision"] == "PENDING"
    assert permit["governing_analysis_min_rf"] is None
    assert permit["speed_category"] == "NORMAL"
    assert fx.analyses_for_permit(client, permit["id"]) == []


def test_the_analysis_denies_an_unrated_route_and_the_officer_issues_that_decision(
    client, bridge
):
    """
    The second and third verbs are the officer's too: the run resolves the single
    structure through the ladder's unrated branch, and the decision the officer then
    issues is the only one the analysis permits.

    PRD §3.7: "Otherwise, if the structure has no governing rating,
    `rating_factor_permit` is null, `analysis_result` is `DENIED` and `result_reason` is
    `NO_APPROVED_RATING` — an unrated structure is not permissible, and the system never
    guesses a capacity."
    PRD §3.7: "if any row is `DENIED` the recommendation is `DENY`"
    PRD §3.7: "The decision **must equal** the analysis-derived `recommended_decision`;
    an officer may not approve a movement the analysis denied, nor deny one it approved,
    nor waive conditions the analysis attached."

    Design: Corner/rbac/permit_officer_owns_the_permit_lifecycle
    """
    permit = fx.receive_permit(
        client,
        "OW-2026-0015",
        [bridge["id"]],
        axle_loads_tons=FOUR_AXLES,
        carrier_name="Northline Heavy Haul",
    )

    analyzed = fx.analyze_permit(client, permit["id"])

    assert analyzed["status"] == "ANALYZED"
    assert analyzed["recommended_decision"] == "DENY"
    assert analyzed["governing_analysis_min_rf"] is None

    rows = fx.analyses_for_permit(client, permit["id"])
    assert len(rows) == 1, f"one row per route entry, got {len(rows)}"
    assert rows[0]["bridge_id"] == bridge["id"]
    assert rows[0]["sequence_index"] == 0
    assert rows[0]["analysis_result"] == "DENIED"
    assert rows[0]["result_reason"] == "NO_APPROVED_RATING"
    assert rows[0]["rating_factor_permit"] is None
    assert rows[0]["governing_load_rating_id"] is None

    decided = fx.decide_permit(
        client,
        permit["id"],
        "DENY",
        decision_note="No approved load rating on the route",
    )
    assert decided["status"] == "DENIED"
    a.assert_instant_equals(decided["decided_at"], c.BASE_CLOCK, "decided_at")


def test_the_officer_reads_the_rating_surface_it_is_not_allowed_to_write(
    client, roster, bridge
):
    """
    The rating data the analysis consumes is readable from the officer's credentials and
    explains the refusal it just issued — but originating a rating belongs to the
    engineer, so the same credentials cannot supply the capacity they lack.

    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API is
    available to all seven roles."
    PRD §3.4: "A `RatingEngineer` originates a rating against a structure."
    PRD §2.8: "2. **Role authorisation** — the authenticated role appears in the
    endpoint's authorised list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
    endpoint."

    Design: Corner/rbac/permit_officer_owns_the_permit_lifecycle
    """
    structure = validate_success(
        client.get_bridge(bridge["id"], permit_officer_headers()), 200
    )
    assert structure["governing_load_rating_id"] is None
    assert structure["posting_required"] is False
    assert structure["posted_limit_tons"] is None

    _, meta = validate_paginated(
        client.list_load_ratings(permit_officer_headers(), {"bridge_id": bridge["id"]})
    )
    assert meta["total_count"] == 0

    refused = client.create_load_rating(
        bridge["id"],
        f.load_rating_payload(bridge["version"], NON_EXISTENT_UUID),
        permit_officer_headers(),
    )

    validate_error(refused, e.ERR_ROLE_NOT_PERMITTED, 403)
    assert refused.json()["data"]["error_id"] != e.ERR_INSPECTION_RECORD_NOT_FOUND
    _, after = validate_paginated(
        client.list_load_ratings(roster.engineer_headers, {"bridge_id": bridge["id"]})
    )
    assert after["total_count"] == 0


# ─── The federal reviewer's single verb ─────────────────────────────────────
def _a_sent_package_over_two_compliant_structures(client):
    """
    Two structures registered at the base clock — so both due dates are two years out
    and neither is overdue — with the annual package built, locked and sent by the
    administrator.
    """
    fx.pin_base_clock(client)
    fx.create_cedar_creek(client)
    fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
        ),
    )
    cycle = fx.create_cycle(client)
    submission = fx.start_submission(client, cycle["id"])
    fx.lock_cycle(client, cycle["id"])
    sent = fx.send_submission(client, submission["id"])
    return {"cycle": cycle, "submission": sent}


def test_the_federal_reviewer_accepts_a_compliant_package_and_closes_the_cycle(client):
    """
    Review is the reviewer's whole write surface, and accepting is the only route to the
    cycle's terminal state: the package the administrator sent is read, then accepted,
    and the cycle behind it closes in the same request.

    PRD §3.9: "`inspection_compliance_pct` is 100 if there are no structures at all;
    otherwise it is 100 multiplied by the compliant count, which is the total minus the
    overdue count, divided by the total, rounded half up to two decimal places."
    PRD §3.9: "Review is an `FhwaReviewer` action permitted only from `SUBMITTED`, and
    the reviewer's own identifier must differ from `submitted_by_user_id`"
    PRD §3.9: "Acceptance moves the submission `SUBMITTED → ACCEPTED`, stamps
    `reviewed_at` from the logical clock, records `reviewer_user_id`, and moves the
    owning cycle `SUBMITTED → CLOSED` with `closed_at` stamped."

    Design: Corner/rbac/fhwa_reviewer_owns_submission_review_only
    """
    state = _a_sent_package_over_two_compliant_structures(client)
    assert state["submission"]["status"] == "SUBMITTED"
    assert state["submission"]["total_bridge_count"] == 2
    assert state["submission"]["overdue_inspection_count"] == 0
    assert state["submission"]["inspection_compliance_pct"] == 100.00
    assert state["submission"]["submitted_by_user_id"] == PROGRAM_ADMIN_USER_ID

    as_read = validate_success(
        client.get_federal_submission(
            state["submission"]["id"], fhwa_reviewer_headers()
        ),
        200,
    )
    assert as_read["inspection_compliance_pct"] == 100.00

    accepted = fx.review_submission(
        client, state["submission"]["id"], "ACCEPT", fhwa_reviewer_headers()
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewer_user_id"] == FHWA_REVIEWER_USER_ID
    a.assert_instant_equals(accepted["reviewed_at"], c.BASE_CLOCK, "reviewed_at")

    cycle = fx.read_cycle(client, state["cycle"]["id"])
    assert cycle["status"] == "CLOSED"
    a.assert_instant_equals(cycle["closed_at"], c.BASE_CLOCK, "closed_at")


def test_the_federal_reviewer_may_not_build_or_send_the_package_it_reviews(client):
    """
    Both halves of the package's construction are the administrator's, so the reviewer
    that is about to judge the numbers cannot manufacture them: the refusals leave the
    submission exactly where the administrator left it.

    PRD §3.9: "A `ProgramAdmin` starts a submission against a cycle, supplying a
    `submission_type` of `NBI_ANNUAL`, `ELEMENT_DATA` or `SCOUR_POA`."
    PRD §3.9: "Submission is a `ProgramAdmin` action permitted from either `BUILDING` or
    `REJECTED` — the latter is the resubmission path."
    PRD §2.1: "An `FhwaReviewer` is the federal compliance reviewer who accepts or
    rejects the state's submissions and may never review a submission they sent."

    Design: Corner/rbac/fhwa_reviewer_owns_submission_review_only
    """
    fx.pin_base_clock(client)
    fx.create_cedar_creek(client)
    cycle = fx.create_cycle(client)

    refused_build = client.create_federal_submission(
        cycle["id"], f.federal_submission_payload(), fhwa_reviewer_headers()
    )
    validate_error(refused_build, e.ERR_ROLE_NOT_PERMITTED, 403)

    submission = fx.start_submission(client, cycle["id"])
    assert submission["status"] == "BUILDING"
    fx.lock_cycle(client, cycle["id"])

    refused_send = client.submit_federal_submission(
        submission["id"], fhwa_reviewer_headers()
    )
    validate_error(refused_send, e.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = validate_success(
        client.get_federal_submission(submission["id"], fhwa_reviewer_headers()), 200
    )
    assert unchanged["status"] == "BUILDING"
    assert unchanged["submitted_by_user_id"] is None
    assert unchanged["submitted_at"] is None
    assert fx.read_cycle(client, cycle["id"])["status"] == "LOCKED"


# ─── Cross-role refusals outrank every later check ──────────────────────────
def _eight_cross_role_writes(client):
    """
    Eight writes, each issued by a role the endpoint does not authorise, and each
    pointed at a path identifier the system has never issued. Returns the responses
    paired with a label naming the surface each one reaches for.
    """
    return [
        (
            "inventory create as an inspector",
            client.create_bridge(
                f.bridge_payload(
                    "STR-000009",
                    name="Unauthorised Bridge",
                    structure_type="TRUSS",
                    deck_area_sqm=100,
                    year_built=1960,
                    adt=200,
                    detour_length_km=1.0,
                ),
                make_headers("insp-x", c.ROLE_BRIDGE_INSPECTOR),
            ),
        ),
        (
            "element row as a reviewer",
            client.create_element_condition(
                NON_EXISTENT_UUID,
                f.element_condition_payload("DECK", "SQM", 10, cs1_qty=10),
                make_headers("qa-x", c.ROLE_QA_REVIEWER),
            ),
        ),
        (
            "QA claim as an engineer",
            client.qa_claim_inspection(
                NON_EXISTENT_UUID, make_headers("eng-x", c.ROLE_RATING_ENGINEER)
            ),
        ),
        (
            "rating seal as a district engineer",
            client.seal_load_rating(
                NON_EXISTENT_UUID,
                {"sealed_by_id": NON_EXISTENT_UUID},
                make_headers("dist-x", c.ROLE_DISTRICT_ENGINEER),
            ),
        ),
        (
            "closure authority as a permit officer",
            client.impose_restriction(
                NON_EXISTENT_UUID,
                f.restriction_payload("CLOSE", NON_EXISTENT_UUID),
                permit_officer_headers(),
            ),
        ),
        (
            "permit analysis as an administrator",
            client.analyze_permit_application(
                NON_EXISTENT_UUID, program_admin_headers()
            ),
        ),
        (
            "federal review as an administrator",
            client.review_federal_submission(
                NON_EXISTENT_UUID, f.review_payload("ACCEPT"), program_admin_headers()
            ),
        ),
        (
            "federal send as a federal reviewer",
            client.submit_federal_submission(
                NON_EXISTENT_UUID, fhwa_reviewer_headers()
            ),
        ),
    ]


def test_every_cross_role_write_is_refused_before_the_path_is_even_resolved(client):
    """
    Each of the eight calls breaks two rules at once — the wrong role and an identifier
    that resolves to nothing — and every one of them answers with the role refusal,
    because the role gate sits at position two and path existence only at position four.

    PRD §2.8: "2. **Role authorisation** — the authenticated role appears in the
    endpoint's authorised list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
    endpoint."
    PRD §2.8: "4. **Path existence** — every resource named in the path exists, validated
    left to right, else the matching family-scoped 404 code. Applies to every endpoint
    with a path parameter."
    PRD §2.1: "Write access is narrow and is enumerated per endpoint in §4."

    Design: Corner/rbac/cross_role_exclusive_operations_returns_403
    """
    fx.pin_base_clock(client)

    for label, response in _eight_cross_role_writes(client):
        validate_error(response, e.ERR_ROLE_NOT_PERMITTED, 403)
        reported = response.json()["data"]["error_id"]
        assert reported != e.ERR_INVALID_REQUEST, (
            f"{label}: the role gate outranks the body check, got {reported}"
        )
        for not_found in (
            e.ERR_BRIDGE_NOT_FOUND,
            e.ERR_PERSONNEL_NOT_FOUND,
            e.ERR_INSPECTION_RECORD_NOT_FOUND,
            e.ERR_RATING_RECORD_NOT_FOUND,
            e.ERR_PERMIT_NOT_FOUND,
            e.ERR_PROGRAM_RECORD_NOT_FOUND,
        ):
            assert reported != not_found, (
                f"{label}: the role gate outranks path existence, got {reported}"
            )


def test_the_refused_sweep_wrote_nothing_and_left_every_shared_read_open(client):
    """
    None of the eight refusals leaked a row into the system, and the same seven roles
    that were individually refused a write can each still perform the reads — the
    narrow-write, broad-read split of the role model.

    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API is
    available to all seven roles."
    PRD §2.1: "The system recognises exactly seven roles: `ProgramAdmin`,
    `BridgeInspector`, `QaReviewer`, `RatingEngineer`, `DistrictEngineer`,
    `PermitOfficer`, and `FhwaReviewer`."

    Design: Corner/rbac/cross_role_exclusive_operations_returns_403
    """
    fx.pin_base_clock(client)
    _eight_cross_role_writes(client)

    for role in c.ALL_ROLES:
        headers = make_headers("sweep-reader", role)
        _, bridges = validate_paginated(client.list_bridges(headers))
        assert bridges["total_count"] == 0, (
            f"{role} must read an empty inventory, got {bridges['total_count']}"
        )
        _, people = validate_paginated(client.list_personnel(headers))
        assert people["total_count"] == 0

    _, inspections = validate_paginated(client.list_inspections(program_admin_headers()))
    assert inspections["total_count"] == 0
    _, permits = validate_paginated(
        client.list_permit_applications(program_admin_headers())
    )
    assert permits["total_count"] == 0


# ─── The two duty separations, keyed on the acting identity ─────────────────
def _an_immediate_finding_and_a_sent_package(client, roster, bridge):
    """
    A `SUBMITTED` report with a severe girder row, the `IMMEDIATE` finding its team
    leader raised from it, and the annual package the administrator sent afterwards.
    """
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    rows = [fx.add_element(client, inspection["id"], roster, row) for row in THREE_GROUPS]
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    fx.submit_report(client, inspection["id"], roster, inspection_date=OBSERVED_AT)
    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        inspection["id"],
        "IMMEDIATE",
        element_condition_id=rows[1]["id"],
        description="Girder web loss threatening collapse",
    )
    cycle = fx.create_cycle(client)
    submission = fx.start_submission(client, cycle["id"])
    fx.lock_cycle(client, cycle["id"])
    sent = fx.send_submission(client, submission["id"])
    return {
        "inspection": inspection,
        "finding": finding,
        "cycle": cycle,
        "submission": sent,
    }


def test_the_administrator_that_sent_the_package_may_not_review_it(
    client, roster, bridge
):
    """
    The role on the header is exactly the one the endpoint wants, so the refusal can only
    come from the identity behind it: the reviewer id is compared against the stored
    submitter id and nothing else.

    PRD §2.10: "The federal reviewer of a submission may not be the user who submitted
    it."
    PRD §2.1: "When `X-User-Role` is `FhwaReviewer`, `X-User-ID` is again opaque; it is
    recorded as `reviewer_user_id` on the submission being reviewed and is compared only
    against the stored `submitted_by_user_id` of that same submission, never against a
    `Personnel` row."
    PRD §3.9: "A self-review is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_blocks_self_review_and_own_finding_authority_returns_403
    """
    state = _an_immediate_finding_and_a_sent_package(client, roster, bridge)
    assert state["submission"]["submitted_by_user_id"] == PROGRAM_ADMIN_USER_ID

    refused = client.review_federal_submission(
        state["submission"]["id"],
        f.review_payload("ACCEPT"),
        make_headers(PROGRAM_ADMIN_USER_ID, c.ROLE_FHWA_REVIEWER),
    )

    validate_error(refused, e.ERR_SEGREGATION_OF_DUTIES, 403)
    assert refused.json()["data"]["error_id"] != e.ERR_ROLE_NOT_PERMITTED
    unchanged = fx.read_submission(client, state["submission"]["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["reviewer_user_id"] is None
    assert unchanged["reviewed_at"] is None
    assert fx.read_cycle(client, state["cycle"]["id"])["status"] == "SUBMITTED"


def test_the_team_leader_may_not_authorise_the_closure_its_own_report_produced(
    client, roster, bridge
):
    """
    The finding really is `IMMEDIATE`, so the severity gate that would otherwise refuse a
    closure has nothing to say — and the request still fails, because the duty check runs
    eleven places earlier than that gate. The unrelated engineer's identical request then
    closes the structure.

    PRD §2.10: "And the person authorising a restriction or closure may not be the team
    leader of the inspection that surfaced the finding."
    PRD §2.8: "11. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403), detailed
    in §2.10. Applies to QA claim, QA decision, load-rating approval, federal-submission
    review, and restriction imposition."
    PRD §2.8: "22. **Closure severity** — `ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE` (422).
    Applies to restriction imposition."

    Design: Corner/rbac/segregation_of_duties_blocks_self_review_and_own_finding_authority_returns_403
    """
    state = _an_immediate_finding_and_a_sent_package(client, roster, bridge)
    finding_id = state["finding"]["id"]
    assert state["finding"]["severity"] == "IMMEDIATE"

    refused = client.impose_restriction(
        finding_id,
        f.restriction_payload("CLOSE", roster.inspector_id),
        make_district_engineer_headers(roster.inspector_id),
    )

    validate_error(refused, e.ERR_SEGREGATION_OF_DUTIES, 403)
    assert (
        refused.json()["data"]["error_id"] != e.ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE
    )
    held = fx.read_finding(client, finding_id)
    assert held["restriction_action"] == "NONE"
    assert held["restriction_authorized_by_id"] is None
    assert held["restriction_imposed_at"] is None
    assert fx.read_bridge(client, bridge["id"])["service_posture"] == "OPEN"

    closed = fx.impose(client, finding_id, roster, "CLOSE")
    assert closed["restriction_action"] == "CLOSE"
    assert closed["restriction_authorized_by_id"] == roster.district_id
    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "CLOSED"
    assert structure["inspection_interval_months"] == 6


def test_an_unrelated_reviewer_accepts_the_package_the_submitter_could_not(
    client, roster, bridge
):
    """
    The refused self-review left the package reviewable rather than spent, so a different
    federal identity accepts the same numbers — and the open immediate finding rides
    along in the snapshot as an error without blocking the acceptance, which turns only
    on the compliance percentage.

    PRD §3.9: "`open_immediate_finding_count` is the number of critical findings whose
    `severity` is `IMMEDIATE` and whose `finding_status` is `OPEN` or `MITIGATED`; a
    mitigated immediate finding still counts as an open error, and `URGENT` findings never
    count regardless of status."
    PRD §3.9: "`ACCEPT` additionally requires the submission's stored
    `inspection_compliance_pct` to be at least 90.00, compared at the *rounded*
    two-decimal value: exactly 90.00 is acceptable, and anything below it fails with
    `ERR_COMPLIANCE_BELOW_THRESHOLD`."
    PRD §3.9: "`ACCEPTED` is terminal for the submission and `CLOSED` is terminal for the
    cycle."

    Design: Corner/rbac/segregation_of_duties_blocks_self_review_and_own_finding_authority_returns_403
    """
    state = _an_immediate_finding_and_a_sent_package(client, roster, bridge)
    assert state["submission"]["inspection_compliance_pct"] == 100.00
    assert state["submission"]["open_immediate_finding_count"] == 1
    assert state["submission"]["error_count"] == 1

    validate_error(
        client.review_federal_submission(
            state["submission"]["id"],
            f.review_payload("ACCEPT"),
            make_headers(PROGRAM_ADMIN_USER_ID, c.ROLE_FHWA_REVIEWER),
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    accepted = fx.review_submission(
        client, state["submission"]["id"], "ACCEPT", fhwa_reviewer_headers()
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewer_user_id"] == FHWA_REVIEWER_USER_ID
    assert accepted["rejection_reason_code"] == "NONE"
    a.assert_instant_equals(accepted["reviewed_at"], c.FIELD_DAY_CLOCK, "reviewed_at")
    assert fx.read_cycle(client, state["cycle"]["id"])["status"] == "CLOSED"
