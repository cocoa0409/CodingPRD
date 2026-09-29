"""Role authorisation and the duty separations inside the qualified-individual role."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    FDA_INSPECTOR_HEADERS,
    NO_AUTH_HEADERS,
    make_qualified_individual_headers,
)


def test_request_without_identity_headers_is_unauthenticated(api: ApiClient):
    """PRD 2.1: "A request missing either header, carrying an empty value for
    either, or naming a role outside the five recognised names is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.11: "Header presence and role recognition — `ERR_UNAUTHENTICATED`
    (401), on every endpoint."
    PRD 2.10: "An importer's `dnb_number` is unique across all importers." —
    replaying the identical payload successfully proves the refused call wrote
    no importer row.

    Design: Corner/rbac/unauthenticated_request_missing_x_user_headers_returns_unauthenticated
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    payload = f.importer_payload()

    refused = api.create_importer(payload, NO_AUTH_HEADERS)
    validate_error(refused, err.ERR_UNAUTHENTICATED)

    # The very same payload, now carrying an identity, is accepted: the unique
    # dnb_number was never consumed, so no importer row was written above.
    accepted = validate_success(
        api.create_importer(payload, COMPLIANCE_OFFICER_HEADERS), 201
    )
    assert accepted["dnb_number"] == payload["dnb_number"]


def test_entry_filer_cannot_create_a_supplier_food_pair(api: ApiClient):
    """PRD 2.1: "A request whose role is recognised but is not authorised for the
    target operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.1: "It may create entry lines and read entry lines, and nothing else."
    PRD 3.2: "A combination whose `supplier_id` and `food_id` duplicate an
    existing combination is refused with `ERR_DUPLICATE_SUPPLIER_FOOD_PAIR`
    unless every such existing combination has `verification_status` equal to
    `RETIRED` — retirement frees the pairing for a fresh start."
    PRD 2.5: "`version`, a monotonically increasing integer that starts at 1 and
    increments by exactly one on every mutation of that row, including mutations
    the row's owner never requested (a recomputed roll-up counts as a mutation)."

    Design: Corner/rbac/entry_filer_cannot_create_a_supplier_food_pair
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(api, importer["id"])
    payload = f.pair_payload(importer["id"], supplier["id"], food["id"], qi_a["id"])

    refused = api.create_supplier_food_pair(payload, ENTRY_FILER_HEADERS)
    validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)

    # The identical request from the compliance office is accepted, and is not
    # refused as a duplicate pairing: the filer's call created no combination.
    created = validate_success(
        api.create_supplier_food_pair(payload, COMPLIANCE_OFFICER_HEADERS), 201
    )
    assert created["version"] == 1, f"expected version 1, got {created['version']}"


def test_compliance_officer_cannot_sign_the_pair_verification_approval(api: ApiClient):
    """PRD 2.1: "It never performs the technical FSVP judgements."
    PRD 3.5: "Only the individual named in the combination's `designated_qi_id`
    may sign it, and the request carries an `approval_note`."
    PRD 2.1: "A request whose role is recognised but is not authorised for the
    target operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 3.3: "The combination's `verification_status` advances
    `DRAFT → HAZARD_ANALYZED`, or self-loops `HAZARD_ANALYZED → HAZARD_ANALYZED`
    when a newer analysis replaces an earlier approved one."

    Design: Corner/rbac/compliance_officer_cannot_sign_the_pair_verification_approval
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)

    refused = api.post_pair_verification_approval(
        world.pair_id,
        f.verification_approval_payload(
            approval_note="Approving on behalf of the qualified individual"
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)

    unchanged = fx.get_pair(api, world.pair_id)
    assert unchanged["verification_status"] == "HAZARD_ANALYZED", (
        "the refused signature must leave the verification dimension where the "
        f"hazard-analysis approval left it, got {unchanged['verification_status']}"
    )

    # The very same call, signed by the pair's designated individual, succeeds.
    signed = validate_success(
        api.post_pair_verification_approval(
            world.pair_id,
            f.verification_approval_payload(),
            make_qualified_individual_headers(world.qi_a_id),
        )
    )
    assert signed["verification_status"] == "VERIFICATION_APPROVED"


def test_qualified_individual_cannot_decide_a_missing_corrective_action(api: ApiClient):
    """PRD 2.12: "Recording a supplier's `regulatory_compliance_status` and
    deciding or closing a corrective action, including import suspension, are
    reserved to `ComplianceOfficer` and are never available to the qualified
    individual who authored the underlying technical judgement."
    PRD 2.11: "Rules are evaluated in ascending priority order, the first
    violated rule determines the response, and no later rule is evaluated."
    PRD 2.11: "Role authorisation for the target endpoint —
    `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint." precedes "The `{id}`
    path segment resolves to a `CorrectiveAction` —
    `ERR_CORRECTIVE_ACTION_NOT_FOUND` (404), on the action read, decision and
    closure."

    Design: Corner/rbac/qualified_individual_cannot_decide_a_corrective_action_even_for_a_missing_action
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    version_before = fx.get_supplier(api, supplier["id"])["version"]

    refused = api.post_corrective_action_decision(
        NON_EXISTENT_UUID,
        f.corrective_action_decision_payload(
            "IMPORT_SUSPENSION",
            version_before,
            rationale=(
                "Attempting to suspend imports without compliance-office authority"
            ),
        ),
        make_qualified_individual_headers(qi_a["id"]),
    )
    # The role check outranks the corrective-action lookup, so the caller learns
    # nothing about which action ids exist.
    validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)

    after = fx.get_supplier(api, supplier["id"])
    assert after["status"] == "UNEVALUATED", f"got {after['status']}"
    assert after["version"] == version_before, (
        f"supplier version moved from {version_before} to {after['version']} on a "
        "refused decision"
    )


def test_qualified_individual_cannot_read_an_entry_submission(api: ApiClient):
    """PRD 2.1: "Entry-line reads are available to `ComplianceOfficer`,
    `EntryFiler` and `FdaInspector` — a `QualifiedIndividual` has no read access
    to entry lines."
    PRD 2.1: "`ComplianceOfficer`, `QualifiedIndividual` and `FdaInspector` may
    read the importer roll-up, qualified individuals, suppliers, foods,
    supplier-food combinations, hazard analyses, hazards, verification
    activities, verification records and corrective actions."

    Design: Corner/rbac/qualified_individual_cannot_read_an_entry_submission
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    qi_headers = make_qualified_individual_headers(qi_a["id"])

    refused = api.get_entry_submission(NON_EXISTENT_UUID, qi_headers)
    validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)

    # The same individual still reads the importer roll-up, so the refusal is a
    # per-resource read partition and not a blanket read restriction.
    roll_up = validate_success(api.get_importer(importer["id"], qi_headers))
    assert roll_up["id"] == importer["id"]


def test_fda_inspector_reads_the_records_package(api: ApiClient):
    """PRD 2.1: "The records-availability package is available to `FdaInspector`
    and `ComplianceOfficer` only."
    PRD 3.9: "The package reports the `importer_id`, the importer's live
    `program_status` and `qualified_individual_designated`, a `generated_at`
    instant recording when the package was produced, and four counts:
    `retained_record_count`, the number of records regardless of status;
    `available_for_inspection_count`, the number of non-rescinded records whose
    `retained_until` is at or after the evaluation instant;
    `expired_record_count`, the number of non-rescinded records whose
    `retained_until` is strictly before the evaluation instant; and
    `rescinded_record_count`, the number of records whose `record_status` is
    `RESCINDED`."
    PRD 2.7: "An importer with no combinations at all but one `ACTIVE` qualified
    individual is `COMPLIANT`; an importer with no `ACTIVE` qualified individual
    is `NON_COMPLIANT` no matter how healthy its combinations look, which is why
    lapsing a single designation is enough to flip the programme status."

    Design: Corner/rbac/fda_inspector_reads_the_records_package_shared_with_the_compliance_officer
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    fx.create_qualified_individual(api, importer["id"])

    package = validate_success(
        api.get_records_package(importer["id"], FDA_INSPECTOR_HEADERS)
    )
    assert package["importer_id"] == importer["id"]
    assert package["program_status"] == "COMPLIANT", f"got {package['program_status']}"
    assert package["qualified_individual_designated"] is True
    assert package["retained_record_count"] == 0
    assert package["available_for_inspection_count"] == 0
    assert package["expired_record_count"] == 0
    assert package["rescinded_record_count"] == 0

    # The package answers identically for the compliance office.
    officer_view = validate_success(
        api.get_records_package(importer["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    for field in (
        "importer_id",
        "program_status",
        "qualified_individual_designated",
        "retained_record_count",
        "available_for_inspection_count",
        "expired_record_count",
        "rescinded_record_count",
    ):
        assert officer_view[field] == package[field], (
            f"{field} differs between the inspector and the officer view: "
            f"{officer_view[field]} vs {package[field]}"
        )


def test_fda_inspector_cannot_patch_the_supplier_compliance_status(api: ApiClient):
    """PRD 2.1: "It is strictly read-only across the importer's programme,
    including the records-availability package."
    PRD 2.12: "Recording a supplier's `regulatory_compliance_status` and
    deciding or closing a corrective action, including import suspension, are
    reserved to `ComplianceOfficer` and are never available to the qualified
    individual who authored the underlying technical judgement."
    PRD 2.1: "A request whose role is recognised but is not authorised for the
    target operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/fda_inspector_cannot_patch_the_supplier_compliance_status
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    supplier = fx.create_supplier(api, importer["id"])
    version_before = supplier["version"]

    refused = api.patch_supplier_compliance_status(
        supplier["id"],
        f.compliance_status_payload(
            "IMPORT_ALERT",
            source_reference="FDA import alert 99-05 published 2026-08-28",
        ),
        FDA_INSPECTOR_HEADERS,
    )
    validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)

    # The regulator may still read the establishment it may not write.
    unchanged = validate_success(
        api.get_foreign_supplier(supplier["id"], FDA_INSPECTOR_HEADERS)
    )
    assert unchanged["regulatory_compliance_status"] == "NO_ADVERSE_FINDINGS", (
        f"got {unchanged['regulatory_compliance_status']}"
    )
    assert unchanged["version"] == version_before, (
        f"supplier version moved from {version_before} to {unchanged['version']} on a "
        "refused write"
    )


def test_activity_proposer_cannot_review_their_own_proposal(api: ApiClient):
    """PRD 2.12: "The individual who proposed a verification activity may not
    review it: on review, `X-User-ID` must differ from the activity's
    `proposed_by_qi_id`."
    PRD 2.12: "All separations compare `X-User-ID` against a stored foreign key,
    and every violation reports `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 3.4: "A second `QualifiedIndividual` reviews a proposal with a `decision`
    of `APPROVE`, `REQUEST_CHANGES` or `WITHDRAW` and a `reviewer_note`; in every
    case the reviewer's `X-User-ID` must differ from the activity's
    `proposed_by_qi_id`, or the review is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.4: "The new row starts in `status` `PROPOSED` with `revision_count` 0,
    `reviewed_by_qi_id` null, and `proposed_by_qi_id` copied from `X-User-ID`;
    its `coverage_weight` is computed immediately, and the assigned individual's
    `active_assignment_count` is recomputed."

    Design: Corner/rbac/activity_proposer_reviewing_their_own_activity_returns_segregation_of_duties
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    spec = dict(fx.ACTIVITY_SAMPLING)
    spec["frequency_per_year"] = 3
    activity = fx.create_activity(api, world.pair_id, world.qi_a_id, world.qi_b_id, **spec)
    assert activity["proposed_by_qi_id"] == world.qi_a_id

    # Both parties hold the same role, so only the stored proposer key separates
    # them.
    refused = api.post_activity_review(
        activity["id"],
        f.activity_review_payload(
            "APPROVE", reviewer_note="Reviewing my own frequency justification"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(refused, err.ERR_SEGREGATION_OF_DUTIES)

    untouched = fx.get_activity(api, activity["id"])
    assert untouched["status"] == "PROPOSED", f"got {untouched['status']}"
    assert untouched["reviewed_by_qi_id"] is None, (
        f"reviewed_by_qi_id was stamped to {untouched['reviewed_by_qi_id']} by a "
        "refused review"
    )
    assert untouched["revision_count"] == 0, f"got {untouched['revision_count']}"

    # The identical review from the second individual is accepted.
    approved = validate_success(
        api.post_activity_review(
            activity["id"],
            f.activity_review_payload("APPROVE"),
            make_qualified_individual_headers(world.qi_b_id),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_qi_id"] == world.qi_b_id
