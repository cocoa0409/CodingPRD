"""Declared transitions, the transitions that are not declared, and their side effects.

Several of these triggers retire or supersede a sibling row in the same call:
publication supersedes the previous release, activation retires the incumbent
program, and acceptance supersedes the previously accepted finding. Each is a
side effect of one call, never a second call.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exception_agreement,
    assert_inspection_finding,
    assert_rate_program,
    assert_tariff_version,
    factories,
    make_pricing_analyst_headers,
    make_shipper_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
AUDITOR_LIST_HEADERS = fx.AUDITOR_HEADERS

CLOCK = "2026-01-10T08:00:00Z"


def _findings_for(shipment_line_id):
    rows, _meta = validate_paginated(
        api_client.list_inspection_findings(
            AUDITOR_LIST_HEADERS,
            params={"shipment_line_id": shipment_line_id, "limit": 100},
        )
    )
    return rows


def _programs_for(customer_id):
    rows, _meta = validate_paginated(
        api_client.list_rate_programs(
            ANALYST, params={"customer_id": customer_id, "limit": 100}
        )
    )
    return rows


# ==========================================================================
# The classification standard release
# ==========================================================================


def test_a_new_classification_standard_starts_as_a_draft():
    """A release whose effective instant is already in the past is still only DRAFT.

    PRD: "The release is created in `status` `DRAFT`, with `published_at` and
    `superseded_by_tariff_version_id` both null."

    Design: Corner/state_machines/tariff_version_initial_state_is_draft
    """
    fx.set_clock(CLOCK)

    response = api_client.create_tariff_version(
        factories.create_tariff_version_payload(
            code="NMFC-2026A", effective_at="2026-01-01T00:00:00Z"
        ),
        ANALYST,
    )

    release = validate_success(response, expected_status=201)

    assert_tariff_version(release)
    assert release["status"] == "DRAFT", (
        f"an unpublished release is never auto-published, got {release['status']}"
    )
    assert release["published_at"] is None
    assert release["superseded_by_tariff_version_id"] is None
    assert release["effective_at"].startswith("2026-01-01T00:00:00")
    assert release["version"] == 1


def test_publishing_a_later_release_supersedes_the_incumbent_in_the_same_call():
    """Supersession is a side effect of publish, with a back-link to the new release.

    PRD: "As a side effect the previously newest published release moves
    `PUBLISHED → SUPERSEDED` and has its `superseded_by_tariff_version_id` set to
    the newly published release's `id`."

    Design: Corner/state_machines/publishing_later_standard_supersedes_earlier_published_one
    """
    fx.set_clock(CLOCK)
    first_draft = fx.create_draft_tariff_version(
        code="NMFC-2026A", effective_at="2026-01-01T00:00:00Z"
    )
    fx.create_commodity_profile(first_draft["id"])
    first_published = fx.publish_tariff_version(first_draft["id"])
    second_draft = fx.create_draft_tariff_version(
        code="NMFC-2026B", effective_at="2026-02-01T00:00:00Z"
    )
    fx.create_commodity_profile(second_draft["id"])

    response = api_client.publish_tariff_version(second_draft["id"], {}, ANALYST)

    second_published = validate_success(response, expected_status=200)
    first_after = fx.get_tariff_version(first_draft["id"])

    assert second_published["status"] == "PUBLISHED"
    assert second_published["published_at"] is not None
    assert second_published["published_at"].startswith("2026-01-10T08:00:00"), (
        f"published_at is stamped from the logical clock, "
        f"got {second_published['published_at']}"
    )
    assert first_after["status"] == "SUPERSEDED"
    assert first_after["superseded_by_tariff_version_id"] == second_draft["id"]
    assert first_after["version"] > first_published["version"], (
        f"the superseded release was mutated, so its version moved past "
        f"{first_published['version']}, got {first_after['version']}"
    )


# ==========================================================================
# The pricing program
# ==========================================================================


def test_activating_a_program_that_was_never_approved_is_refused():
    """Activation is declared only out of APPROVED, so a MODELING program is inert.

    PRD: "Activating a program that is not `APPROVED` is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/rate_program_activation_before_approval_is_rejected
    """
    fx.set_clock(CLOCK)
    customer = fx.create_customer()
    program = fx.create_rate_program(customer["id"])

    response = api_client.activate_rate_program(
        program["id"],
        factories.activate_rate_program_payload(customer["version"]),
        ANALYST,
    )

    validate_error(
        response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
    )
    stored = fx.get_rate_program(program["id"])
    customer_after = fx.get_customer(customer["id"])
    assert stored["status"] == "MODELING"
    assert stored["pinned_tariff_version_id"] is None
    assert stored["effective_from"] is None
    assert customer_after["active_program_type"] is None
    assert customer_after["version"] == customer["version"], (
        f"a refused activation does not consume the guarded customer version, "
        f"got {customer_after['version']}"
    )


def test_activating_a_second_program_retires_the_incumbent_one():
    """At most one program is ACTIVE per shipper, maintained by retiring the old one.

    PRD: "As a side effect, whichever program of that shipper was previously
    `ACTIVE` moves `ACTIVE → RETIRED` with its `effective_to` stamped — shipments
    already pinned to it keep rating against it — the shipper's
    `active_program_type` is set to the newly activated program's `program_type`,
    and the shipper's `version` is incremented by one."

    Design: Corner/state_machines/activating_second_program_retires_the_incumbent
    """
    fx.set_clock(CLOCK)
    fx.create_published_standard()
    customer = fx.create_customer()
    incumbent = fx.create_active_rate_program(
        customer["id"],
        program_type="CLASS_BASED",
        base_rate_per_cwt_cents=3000,
        discount_pct=0.20,
        min_charge_cents=12500,
    )
    challenger = fx.create_approved_rate_program(
        customer["id"],
        program_type="DENSITY_BASED",
        base_rate_per_cwt_cents=4200,
        discount_pct=0.35,
        min_charge_cents=12500,
    )

    activated = fx.activate_rate_program(challenger["id"], customer["id"])

    assert_rate_program(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["effective_from"] is not None
    assert activated["effective_from"].startswith("2026-01-10T08:00:00")
    retired = fx.get_rate_program(incumbent["id"])
    assert retired["status"] == "RETIRED"
    assert retired["effective_to"] is not None
    assert retired["effective_to"].startswith("2026-01-10T08:00:00")
    customer_after = fx.get_customer(customer["id"])
    assert customer_after["active_program_type"] == "DENSITY_BASED"
    active = [row for row in _programs_for(customer["id"]) if row["status"] == "ACTIVE"]
    assert len(active) == 1, (
        f"exactly one program of the shipper stays ACTIVE, found {len(active)}"
    )
    assert active[0]["id"] == challenger["id"]


# ==========================================================================
# The shipment and its shipper's posture
# ==========================================================================


def test_billing_a_shipment_twice_is_refused_and_does_not_reprice_it():
    """The second call is refused outright rather than recomputing the charge.

    PRD: "Billing a shipment a second time is rejected with
    `ERR_SHIPMENT_ALREADY_BILLED`."

    Design: Corner/state_machines/billing_an_already_billed_shipment_is_rejected
    """
    scenario = fx.setup_single_line_billed_shipment(pro_number="PROE007")
    first_billed = scenario["shipment"]
    assert first_billed["original_charge_cents"] == 12500, (
        f"the 9937-cent computed charge is floored at the 12500 minimum, "
        f"got {first_billed['original_charge_cents']}"
    )

    response = api_client.bill_shipment(scenario["shipment_id"], {}, ANALYST)

    validate_error(
        response, ApiErrorId.ERR_SHIPMENT_ALREADY_BILLED.value, expected_status=409
    )
    stored = fx.get_shipment(scenario["shipment_id"])
    assert stored["billing_status"] == "BILLED"
    assert stored["original_charge_cents"] == 12500
    assert stored["assessed_total_cents"] == 12500
    assert stored["billed_at"].startswith("2026-01-10T08:00:00"), (
        f"billed_at is not restamped by the refused call, got {stored['billed_at']}"
    )


def test_a_closed_shipper_cannot_tender_but_can_still_be_read():
    """Closure blocks the write without hiding the account itself.

    PRD: "any of the five guarded operations attempted while the account is
    `CLOSED` is rejected with `ERR_CUSTOMER_CLOSED`."

    Design: Corner/state_machines/closed_customer_cannot_tender_new_shipment
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    fx.change_posture(env["customer_id"], "CLOSED")

    response = api_client.create_shipment(
        factories.create_shipment_payload(
            env["customer_id"], env["terminal_id"], "PROE008"
        ),
        make_shipper_headers(env["customer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_CLOSED.value, expected_status=409)
    customer = fx.get_customer(env["customer_id"])
    assert customer["billing_posture"] == "CLOSED", (
        "the read still succeeds after closure"
    )
    rows, _meta = validate_paginated(
        api_client.list_shipments(
            ANALYST, params={"customer_id": env["customer_id"], "limit": 100}
        )
    )
    assert [row["pro_number"] for row in rows] == [], (
        f"the refused tender created no shipment, found {[r['pro_number'] for r in rows]}"
    )


# ==========================================================================
# The negotiated exception and the inspection finding
# ==========================================================================


def test_approving_an_exception_agreement_gives_it_rating_force():
    """The proposed type and class are frozen by the transition that activates them.

    PRD: "Approval by a `PricingAnalyst` moves the agreement `PENDING → ACTIVE`,
    stamps `approved_by_user_id` from the acting `X-User-ID` and `approved_at` from
    the logical clock, and requires both that the shipper is not `CLOSED` and that
    no other `ACTIVE` agreement overlaps the same shipper-and-commodity interval."

    Design: Corner/state_machines/exception_agreement_approval_activates_the_override
    """
    fx.set_clock(CLOCK)
    customer = fx.create_customer()
    standard = fx.create_published_standard()
    pending = fx.create_exception_agreement(
        customer["id"],
        standard["commodity_profile_id"],
        "2026-01-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        agreement_type="FAK",
        agreed_class_code=92.5,
    )
    assert pending["status"] == "PENDING", (
        "a proposed agreement carries no rating force until it is approved"
    )
    assert pending["version"] == 1

    response = api_client.approve_exception_agreement(pending["id"], {}, ANALYST)

    approved = validate_success(response, expected_status=200)

    assert_exception_agreement(approved)
    assert approved["status"] == "ACTIVE"
    assert approved["approved_at"] is not None
    assert approved["approved_at"].startswith("2026-01-10T08:00:00")
    assert approved["approved_by_user_id"] == "analyst-1", (
        f"the approver is the acting analyst, got {approved['approved_by_user_id']}"
    )
    assert approved["agreement_type"] == "FAK"
    assert approved["agreed_class_code"] == 92.5
    assert approved["version"] > pending["version"]


def test_accepting_a_second_finding_supersedes_the_first_accepted_one():
    """Only one accepted finding may ever govern a line's classification.

    PRD: "Any finding on the same line that was previously `ACCEPTED` moves
    `ACCEPTED → SUPERSEDED` and stops contributing to that line's classification —
    only the single currently-accepted finding on a line ever participates in
    classification, and `RECORDED` and `SUPERSEDED` findings are ignored entirely."

    Design: Corner/state_machines/accepting_second_finding_supersedes_the_first
    """
    scenario = fx.setup_single_line_billed_shipment(pro_number="PROE009")
    line_id = scenario["line_ids"][0]
    first = fx.record_finding(
        line_id,
        found_class_code=250,
        evidence_photo_count=3,
        notes="Boxes gapped on pallet; density well below declared",
    )
    second = fx.record_finding(
        line_id,
        found_class_code=175,
        evidence_photo_count=4,
        notes="Re-measured after restack; density recomputed",
    )
    fx.accept_finding(first["id"])

    accepted = fx.accept_finding(second["id"])

    assert_inspection_finding(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None
    assert accepted["accepted_at"].startswith("2026-01-10T08:00:00")
    assert accepted["accepted_by_user_id"] == "aud-1"
    rows = _findings_for(line_id)
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    still_accepted = [row for row in rows if row["status"] == "ACCEPTED"]
    assert len(still_accepted) == 1, (
        f"exactly one finding on the line stays ACCEPTED, found {len(still_accepted)}"
    )
    assert still_accepted[0]["id"] == second["id"]
