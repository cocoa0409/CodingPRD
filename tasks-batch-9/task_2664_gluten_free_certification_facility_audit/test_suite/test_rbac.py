"""Identity and authorization, taken one layer at a time: the missing headers that
precede every lookup, two role exclusions, the read carved out of the applicant's set,
the ownership comparison on `X-User-ID`, and the segregation rule on a remedy decision.
"""

from test_helpers import (
    AirHandlingClass,
    ApiErrorId,
    AssayMethod,
    Decision,
    NON_EXISTENT_UUID,
    NcCategory,
    NcSeverity,
    NcSourceType,
    create_applicant,
    create_product,
    make_admin_headers,
    make_applicant_contact_headers,
    make_lab_technician_headers,
    make_reviewer_headers,
    raise_nonconformance,
    read_applicant,
    read_facility,
    read_nonconformance,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    start_audit,
    submit_corrective_action,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
SANITATION_EXPIRY = "2027-08-01T00:00:00Z"
DAY_AFTER_EXPIRY = "2027-08-02T00:00:00Z"


def test_a_request_with_no_headers_is_answered_before_the_payload_is_resolved(api):
    """The `applicant_id` in the body does not exist, yet the missing identity headers are
    answered first, so the reply is 401 rather than a not-found on the applicant.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the six role names
    below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "5. **Body reference existence.** Every foreign key carried in the request body
    resolves to a live row, checked in the order the endpoint declares its inputs, again
    returning the matching not-found code with HTTP 404."

    Design: Corner/rbac/request_with_no_identity_headers_is_unauthenticated
    """
    set_clock(api, CLOCK_START)

    response = api.create_facility(
        {},
        applicant_id=NON_EXISTENT_UUID,
        site_name="Ghost Plant",
        air_handling_class=AirHandlingClass.FILTERED_ZONED,
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

    _rows, meta = validate_paginated(api.list_facilities(make_admin_headers()))
    assert meta["total_count"] == 0


def test_the_laboratory_user_is_refused_issuance_before_any_gate_speaks(api):
    """The product would fail almost every substantive issuance gate, and the reply still
    reports the role refusal rather than leaking which gate would have failed.

    PRD: "2. **Role authorization.** The acting role appears in the called endpoint's
    authorized-role list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."
    PRD: "Issuance is the program's most heavily guarded write, and only a
    `CertificationDecisionMaker` may perform it."

    Design: Corner/rbac/lab_technician_cannot_issue_a_certificate
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )

    response = api.issue_certificate(
        make_lab_technician_headers("lab-1"),
        product_id=product["id"],
        expected_product_version=product["version"],
    )
    validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

    _rows, meta = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=product["id"])
    )
    assert meta["total_count"] == 0
    assert read_applicant(api, context.applicant_id)["active_certified_product_count"] == 0


def test_complaint_records_are_the_read_the_applicant_does_not_get(api):
    """The same contact reads its own product without trouble, so the complaint refusal is
    a per-endpoint carve-out and not a blanket ownership rule.

    PRD: "| GET | `/gfco/consumer-complaints/{complaintId}` | Read one consumer complaint
    with its triage priority, recall scope and recall action. | `CertificationReviewer`,
    `FieldAuditor`, `CertificationDecisionMaker`, `ProgramAdministrator` |"
    PRD: "2. **Role authorization.** The acting role appears in the called endpoint's
    authorized-role list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."

    Design: Corner/rbac/applicant_contact_cannot_read_consumer_complaints
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    headers = make_applicant_contact_headers(context.applicant_id)
    own_product = validate_success(api.get_product(product["id"], headers))
    assert own_product["id"] == product["id"]

    response = api.get_complaint(NON_EXISTENT_UUID, headers)
    validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)


def test_the_regulated_party_cannot_drive_its_own_surveillance_clock(api):
    """The sanitation record has already lapsed on the calendar, and the refused sweep
    leaves the facility VALIDATED rather than applying the transition part way.

    PRD: "- **`ProgramAdministrator`** — program operations. Registers applicants and
    suppliers, changes supplier standing, files consumer complaints, runs the surveillance
    sweep and drives the logical clock."
    PRD: "Once `sanitation_expires_on` has been reached, the next surveillance sweep moves
    the facility from `VALIDATED` to `EXPIRED`."

    Design: Corner/rbac/applicant_contact_cannot_run_the_surveillance_sweep
    """
    context = setup_applicant_with_facility(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
    )
    assert context.facility["sanitation_expires_on"] == SANITATION_EXPIRY
    assert context.facility["sanitation_method"] == AssayMethod.R5_ELISA

    set_clock(api, DAY_AFTER_EXPIRY)
    response = api.run_surveillance(make_applicant_contact_headers(context.applicant_id))
    validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

    row = read_facility(api, context.facility_id)
    assert row["sanitation_validation_status"] == "VALIDATED"
    assert row["sanitation_expires_on"] == SANITATION_EXPIRY


def test_one_contact_cannot_declare_a_site_in_another_companys_name(api):
    """Both applicants exist and the payload is otherwise valid, so the refusal is the
    ownership comparison on `X-User-ID` and neither company gains a site.

    PRD: "6. **Resource ownership.** When the acting role is `ApplicantContact`, the owning
    applicant reached from the target resource equals `X-User-ID` — otherwise
    `ERR_NOT_RESOURCE_OWNER` (403). This guards facility declaration, ingredient
    declaration, ingredient submission for review, supplier-document upload, product
    declaration, formula-line linking, corrective-action plan submission and
    change-notification filing."
    PRD: "Concretely, an `ApplicantContact` may only act where the owning applicant reached
    from the target resource — the `applicant_id` of a facility, of an ingredient, of a
    product or of a nonconformance, or the `applicant_id` of the certificate named by a
    change notification — equals `X-User-ID`."

    Design: Corner/rbac/applicant_contact_cannot_declare_a_facility_for_another_applicant
    """
    set_clock(api, CLOCK_START)
    northgate = create_applicant(api, legal_name="Northgate Bakehouse Ltd")
    southbank = create_applicant(
        api, legal_name="Southbank Snacks Inc", contact_email="qa@southbank.example"
    )

    response = api.create_facility(
        make_applicant_contact_headers(northgate["id"]),
        applicant_id=southbank["id"],
        site_name="Plant 12",
        air_handling_class=AirHandlingClass.FILTERED_ZONED,
    )
    validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    for applicant_id in (northgate["id"], southbank["id"]):
        _rows, meta = validate_paginated(
            api.list_facilities(make_admin_headers(), applicant_id=applicant_id)
        )
        assert meta["total_count"] == 0


def test_the_reviewer_who_raised_the_finding_may_not_accept_its_remedy(api):
    """rev-1 holds the right role and the record is in the right state, so the only fault
    is the identity, and the record keeps its plan, its version and its penalty points.

    PRD: "When a corrective-action plan is decided, the acting `CertificationReviewer` must
    differ from the nonconformance's `raised_by_user_id` — the person who found the problem
    may not be the person who accepts the promise to fix it."
    PRD: "A successful submission records `ca_plan_text`, replacing any previous text on a
    resubmission, moves the record to `CA_SUBMITTED`, refreshes `updated_at` to the logical
    clock, increases `version` by 1, and recomputes the adjudicated score of the audit named
    by `audit_id` if there is one."

    Design: Corner/rbac/corrective_action_decision_by_the_raiser_is_rejected_under_segregation_of_duties
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    audit = schedule_audit(
        api,
        context.facility_id,
        onsite_start_at=CLOCK_START,
        onsite_end_at="2026-08-01T17:00:00Z",
    )
    start_audit(api, audit["id"])
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        raiser_user_id="rev-1",
        role="reviewer",
        source_type=NcSourceType.AUDIT,
        category=NcCategory.SANITATION,
        severity=NcSeverity.MAJOR,
        description="Swab log gap for the 2026-07 sanitation cycle",
        audit_id=audit["id"],
    )
    assert finding["raised_by_user_id"] == "rev-1"
    assert finding["ca_due_on"] == "2026-08-31T00:00:00Z"

    submitted = submit_corrective_action(
        api, context.applicant_id, finding["id"], finding["version"]
    )
    assert submitted["status"] == "CA_SUBMITTED"
    assert submitted["ca_revision_count"] == 0

    response = api.decide_corrective_action(
        finding["id"], make_reviewer_headers("rev-1"), decision=Decision.ACCEPT
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == "CA_SUBMITTED"
    assert row["ca_decided_by_user_id"] is None
    assert row["ca_revision_count"] == 0
    assert row["version"] == submitted["version"]

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_cycle"] == 92
