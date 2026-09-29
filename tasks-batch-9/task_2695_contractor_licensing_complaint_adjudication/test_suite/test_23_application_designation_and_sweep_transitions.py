"""Application, designation and sweep transition corners.

Covers the transitions that move a file through the licensing side of the
board: the enforcement case the board opens on its own initiative, the two ways
an undecided application can end, the designation withdrawal that strips a
licence of its qualifier of record, and the ops checkpoint that expires a run-out
term without disturbing the people standing behind it.
"""

from test_helpers import (
    assert_investigation,
    assert_license,
    assert_qualification_count,
    assert_qualifier_assignment,
    assert_coverage_record,
    assert_license_application,
    fixtures as X,
    make_investigator_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_sting_case_opens_in_open_under_the_opening_investigator(
    api, licensing_analyst_headers
):
    """A board-initiated sting opens as an untouched OPEN case owned by its opener.

    "The case opens in `OPEN` with `opened_on` set to the clock date and
    `assigned_investigator_user_id` recorded from the opening actor's
    `X-User-ID`."

    Design: Corner/state_machines/corner_investigation_starts_open_on_creation
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    payload = {"origin": "STING", "subject_business_name": "Unlicensed Bob Remodeling"}
    opened = validate_success(
        api.create_investigation(payload, make_investigator_headers("inv-sting-1")),
        expected_status=201,
    )
    assert opened["status"] == "OPEN", (
        f"a new case opens in OPEN, got {opened['status']!r}"
    )

    stored = validate_success(
        api.get_investigation(opened["id"], licensing_analyst_headers)
    )
    assert_investigation(
        stored,
        origin="STING",
        complaint_id=None,
        assigned_investigator_user_id="inv-sting-1",
        finding_severity=None,
        closed_on=None,
    )


def test_withdrawing_a_draft_application_mints_no_licence(api, licensing_analyst_headers):
    """A file pulled before submission simply ends; nothing downstream is created.

    "**Withdrawal** is available to the owning contracting entity from `DRAFT`,
    `SUBMITTED` or `DEFICIENT`, moving the application to `WITHDRAWN` with no
    cross-entity effect."

    Design: Corner/state_machines/corner_withdrawing_a_draft_application_reaches_the_terminal_state
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    licensee = X.register_licensee(
        api, legal_name="Withdraw Electric LLC", contact_email="wd@x.test"
    )
    individual = X.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        full_name="Will Withdraw",
    )
    application = X.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )
    assert application["status"] == "DRAFT", (
        f"a filed application starts in DRAFT, got {application['status']!r}"
    )

    withdrawn = validate_success(
        api.withdraw_application(
            application["id"], make_licensee_headers(licensee["id"])
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"withdrawal is terminal, got {withdrawn['status']!r}"
    )

    stored = validate_success(
        api.get_application(application["id"], licensing_analyst_headers)
    )
    assert_license_application(stored, status="WITHDRAWN")

    _, meta = validate_paginated(
        api.list_licenses(
            licensing_analyst_headers, {"application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a withdrawn application mints no licence, got {meta['total_count']}"
    )


def test_curing_an_application_that_is_not_deficient_is_refused(
    api, licensing_analyst_headers
):
    """Cure answers a deficiency finding, so a DRAFT file cannot be cured into shape.

    "Attempting an action from the wrong state — submitting an
    already-`SUBMITTED` application, curing one that is not `DEFICIENT`,
    deciding a `WITHDRAWN` one, or withdrawing a decided one — draws
    `ERR_APPLICATION_STATE_INVALID`."

    Design: Corner/state_machines/corner_curing_a_draft_application_is_refused
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    licensee = X.register_licensee(
        api, legal_name="Cure Electric LLC", contact_email="cure@x.test"
    )
    individual = X.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        full_name="Cora Cure",
    )
    application = X.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )

    validate_error(
        api.cure_application(
            application["id"],
            {"declared_net_worth_cents": 900000},
            make_licensee_headers(licensee["id"]),
        ),
        "ERR_APPLICATION_STATE_INVALID",
        expected_status=409,
    )

    stored = validate_success(
        api.get_application(application["id"], licensing_analyst_headers)
    )
    assert_license_application(
        stored, status="DRAFT", declared_net_worth_cents=400000
    )


def test_withdrawing_the_only_designation_leaves_the_licence_without_a_qualifier(
    api, licensing_analyst_headers
):
    """One withdrawal moves the designation, the person's count and the licence.

    "The withdrawal stores `withdrawn_on`, rewrites `effective_to` to that same
    date, and lowers the person's `active_qualification_count` by one."

    "If the licence's `qualifying_individual_id` named the withdrawn person,
    that field is cleared to null and the licence's `compliance_posture` is
    recomputed — which, per §2.6, lands it at `NON_COMPLIANT`, because a licence
    with no qualifier of record is by definition out of compliance."

    Design: Corner/state_machines/corner_withdrawing_the_sole_designation_nulls_the_qualifier_of_record
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Solo Electric LLC",
        contact_email="solo@x.test",
        full_name="Sol Solo",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    designation = ctx.assignment
    assert designation is not None, "the approval cascade mints the sole designation"

    X.set_clock(api, "2026-09-01T00:00:00Z")
    withdrawn = validate_success(
        api.withdraw_qualifier_assignment(
            designation["id"], {"withdrawn_on": "2026-09-01"}, licensing_analyst_headers
        )
    )
    assert_qualifier_assignment(
        withdrawn,
        status="WITHDRAWN",
        effective_to="2026-09-01",
        withdrawn_on="2026-09-01",
    )

    individual = validate_success(
        api.get_qualifying_individual(ctx.individual_id, licensing_analyst_headers)
    )
    assert_qualification_count(individual, 0)

    licence = X.read_license(api, ctx.license_id)
    assert_license(
        licence,
        qualifying_individual_id=None,
        compliance_posture="NON_COMPLIANT",
        status="ACTIVE",
    )


def test_the_sweep_expires_a_run_out_term_and_leaves_the_designation_standing(
    api, licensing_analyst_headers
):
    """A term that has run out expires without disturbing coverage or qualifiers.

    "It moves every licence from `ACTIVE → EXPIRED` whose term has run, meaning
    the clock date is strictly past `expires_on`, recomputing that licence's
    `compliance_posture` while deliberately leaving its qualifier designations
    untouched."

    "The checkpoint reports what it did as `lapsed_coverage_count`,
    `expired_license_count`, `suspended_license_count` and the `swept_on` date
    it ran against."

    Design: Corner/state_machines/corner_compliance_sweep_expires_the_term_but_keeps_the_designation
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Sweep Electric LLC",
        contact_email="swp@x.test",
        full_name="Sam Sweep",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    bond = X.verify_bond(
        api,
        ctx.license_id,
        amount_cents=1500000,
        effective_date="2026-08-01",
        expiration_date="2029-01-01",
        carrier_name="Surety One",
        policy_number="BND-SWP",
    )
    designation = ctx.assignment
    assert designation is not None, "the approval cascade mints the sole designation"

    X.set_clock(api, "2028-08-02T00:00:00Z")
    report = validate_success(api.run_compliance_sweep(licensing_analyst_headers))
    assert report["expired_license_count"] == 1, (
        f"one term has run out, got {report['expired_license_count']}"
    )
    assert report["lapsed_coverage_count"] == 0, (
        f"the bond still runs to 2029-01-01, got {report['lapsed_coverage_count']}"
    )
    assert report["suspended_license_count"] == 0, (
        f"nothing is suspended by this sweep, got {report['suspended_license_count']}"
    )
    assert report["swept_on"] == "2028-08-02", (
        f"the sweep reports the clock date it ran against, got {report['swept_on']!r}"
    )

    licence = X.read_license(api, ctx.license_id)
    assert_license(
        licence, status="EXPIRED", qualifying_individual_id=ctx.individual_id
    )

    stored_designation = validate_success(
        api.get_qualifier_assignment(designation["id"], licensing_analyst_headers)
    )
    assert_qualifier_assignment(stored_designation, status="ACTIVE")

    individual = validate_success(
        api.get_qualifying_individual(ctx.individual_id, licensing_analyst_headers)
    )
    assert_qualification_count(individual, 1)

    stored_bond = validate_success(
        api.get_coverage_record(bond["id"], licensing_analyst_headers)
    )
    assert_coverage_record(stored_bond, status="VERIFIED", expiration_date="2029-01-01")
