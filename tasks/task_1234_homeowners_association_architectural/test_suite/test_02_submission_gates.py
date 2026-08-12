"""Submission gates: state, completeness, window length, and the lien posture gate."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_application_payload, create_attachment_payload,
    create_association, register_owner, register_property,
    create_draft_application, create_complete_draft, add_required_attachments,
    submit_application, start_review, read_application, read_property,
    set_logical_clock, setup_liened_property,
    make_homeowner_headers,
)

MANAGER = TEST_USERS["manager_headers"]


def test_submit_twice_rejected(api):
    """Submission is defined only from DRAFT; a second submit fails and restamps nothing.

    PRD §3.3: "Submission moves the application from `DRAFT` to `SUBMITTED` and is
    where the pipeline's first gates bite."
    PRD §3.3: "A successful submission stamps `submitted_at` — this stamp is written
    on the first submission only and is never restamped by any later resubmission"
    PRD §2.9: "State: the target resource is in a state from which the requested
    transition is defined; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/submit_twice_rejected
    """
    assoc = create_association(name="Twice HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="T-2",
                             address="2 Twice Ct")
    set_logical_clock("2026-05-01T09:00:00Z")
    app = create_complete_draft(prop["id"], owner)
    first = submit_application(app["id"], owner["id"])
    assert first["status"] == "SUBMITTED"
    first_stamp = first["submitted_at"]

    res = api.submit_application(app["id"], make_homeowner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = read_application(app["id"])
    assert after["status"] == "SUBMITTED"
    assert after["submitted_at"] == first_stamp, (
        "a rejected re-submission must not restamp submitted_at")


def test_decide_from_draft_rejected(api):
    """The committee decision is defined only from UNDER_REVIEW, not from DRAFT.

    PRD §3.4: "The decision itself is applied by a `Manager` and begins with the
    tally." (of ballots cast while the application is UNDER_REVIEW)
    PRD §2.9: "State: the target resource is in a state from which the requested
    transition is defined; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/decide_from_draft_rejected
    """
    assoc = create_association(name="Draft HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="D-2",
                             address="2 Draft Ct")
    app = create_draft_application(prop["id"], owner)

    res = api.decide_application(app["id"], {"conditions": []}, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert read_application(app["id"])["status"] == "DRAFT"


def test_submit_missing_material_sample_rejected(api):
    """Submission needs one DRAWING and one MATERIAL_SAMPLE; either missing fails.

    PRD §3.3: "Completeness is checked next: the application must carry at least one
    attachment of `kind` `DRAWING` and at least one of `kind` `MATERIAL_SAMPLE`, and
    a submission missing either is rejected with `ERR_INCOMPLETE_SUBMISSION`."

    Design: Corner/validations/submit_missing_material_sample_rejected
    """
    assoc = create_association(name="Inc HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="I-11",
                             address="11 Incomplete Ct")
    app = create_draft_application(prop["id"], owner)
    headers = make_homeowner_headers(owner["id"])
    validate_success(api.create_attachment(
        app["id"], create_attachment_payload("DRAWING"), headers), 201)

    res = api.submit_application(app["id"], headers)
    validate_error(res, ApiErrorId.ERR_INCOMPLETE_SUBMISSION)

    validate_success(api.create_attachment(
        app["id"], create_attachment_payload("MATERIAL_SAMPLE"), headers), 201)
    ok = validate_success(api.submit_application(app["id"], headers), 200)
    assert ok["status"] == "SUBMITTED"


def test_create_application_window_too_long_rejected(api):
    """A requested window longer than max_window_days fails at creation.

    PRD §3.3: "The requested window is a half-open interval per §2.8, and its length
    in whole days must not exceed the association's `max_window_days`; an over-long
    window is rejected with `ERR_WINDOW_TOO_LONG`."

    Design: Corner/validations/create_application_window_too_long_rejected
    """
    assoc = create_association(name="Long HOA", max_window_days=180)
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="W-9",
                             address="9 Window Ct")
    payload = create_application_payload(
        owner["id"], project_type="ADDITION", guideline_section="SEC-9.0",
        description="huge addition",
        requested_window_start="2026-06-01", requested_window_end="2027-01-01")
    res = api.create_application(prop["id"], payload,
                                 make_homeowner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_WINDOW_TOO_LONG)
    data, _meta = validate_paginated(api.list_property_applications(prop["id"], MANAGER))
    assert data == [], "a rejected creation must not leave an application row"


class TestLienedPropertySubmissionGate:
    """Posture gate (P7) outranks completeness (P9) and blocks regardless of attachments."""

    def test_incomplete_application_on_liened_property_reports_posture_gate(self, api):
        """On a LIENED property the posture gate fires before the completeness check.

        PRD §3.3: "The posture gate fires first: if the property's
        `compliance_posture` is `LIENED`, the submission is rejected with
        `ERR_PROPERTY_LIENED`. Completeness is checked next"
        PRD §2.9: "Every request is validated against the rules below in the listed
        order, and the first failing rule produces the response error."
        PRD §3.8: "The daily checkpoint auto-files a lien on a property when three
        conditions hold together: the property's `outstanding_fine_balance_cents` is
        at or above the association's `lien_threshold_cents`, the oldest unpaid fine
        is at least `lien_min_age_days` old, and no `FILED` lien already exists for
        the property."

        Design: Difficulty/priority_pair_validation_conflict/submit_liened_property_safety_beats_completeness
        """
        bundle = setup_liened_property()  # base 10000 == threshold; lien filed at day 2
        assert bundle["sweep_report"]["liens_filed"] == 1

        # DRAFT application with NO attachments: posture gate AND completeness both fail.
        app = create_draft_application(bundle["property"]["id"], bundle["owner"])
        res = api.submit_application(
            app["id"], make_homeowner_headers(bundle["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_PROPERTY_LIENED)
        assert read_application(app["id"])["status"] == "DRAFT"

    def test_complete_application_on_liened_property_still_blocked(self, api):
        """Complete attachments do not rescue a submission on a LIENED property.

        PRD §2.5: "the property's posture in turn gates behavior elsewhere, most
        notably blocking new application submissions while the property is `LIENED`
        (rejected with `ERR_PROPERTY_LIENED`)."
        PRD §3.3: "The posture gate fires first: if the property's
        `compliance_posture` is `LIENED`, the submission is rejected with
        `ERR_PROPERTY_LIENED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_liened_property_safety_beats_completeness
        """
        bundle = setup_liened_property()
        app = create_complete_draft(bundle["property"]["id"], bundle["owner"])
        res = api.submit_application(
            app["id"], make_homeowner_headers(bundle["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_PROPERTY_LIENED)
        assert read_application(app["id"])["status"] == "DRAFT"

    def test_posture_is_liend_once_lien_files(self, api):
        """A FILED lien flips the derived posture to LIENED.

        PRD §2.5: "`compliance_posture` is derived in a fixed order: `LIENED` if any
        lien of the property is in `FILED` status; otherwise `FINES_OUTSTANDING` if
        `outstanding_fine_balance_cents` is greater than zero; otherwise `CLEAR`."
        PRD §3.8: "The lien captures the property's balance at that instant in
        `amount_at_filing_cents`, stamps `filed_at`, and starts in `FILED` status"

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_property_posture
        """
        bundle = setup_liened_property()
        prop = read_property(bundle["property"]["id"])
        assert prop["compliance_posture"] == "LIENED"
        assert bundle["lien"]["status"] == "FILED"
        assert bundle["lien"]["amount_at_filing_cents"] >= 10000

    def test_submit_on_liened_property_rejected_application_stays_draft(self, api):
        """The cross-entity posture gate rejects submission purely from Property state.

        PRD §2.9: "Posture gate: application submission requires the property's
        `compliance_posture` to be other than `LIENED`; otherwise
        `ERR_PROPERTY_LIENED` (409)."
        PRD §2.5: "most notably blocking new application submissions while the
        property is `LIENED` (rejected with `ERR_PROPERTY_LIENED`)."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_property_posture
        """
        bundle = setup_liened_property()
        app = create_complete_draft(bundle["property"]["id"], bundle["owner"])
        res = api.submit_application(
            app["id"], make_homeowner_headers(bundle["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_PROPERTY_LIENED)
        assert read_application(app["id"])["status"] == "DRAFT"
