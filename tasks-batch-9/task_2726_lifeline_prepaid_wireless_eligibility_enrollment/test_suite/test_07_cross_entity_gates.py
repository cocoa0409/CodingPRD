"""Cross-entity gates: a dwelling's duplicate posture and a gaining carrier's operating status."""

from test_helpers import (
    ApiErrorId,
    address_hash_for,
    assert_date_component,
    assert_instant,
    assert_service_transfer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

CANONICAL_HASH = "1200NMAINST|APT4B|ELPASO|TX|79901"
BENEFIT_START = "2026-08-01T00:00:00Z"
PORT_FREEZE_UNTIL = "2026-09-30T00:00:00Z"


def _flagged_cohort_with_a_waiting_applicant(api):
    """Two spellings of one dwelling, flagged, with a verified applicant attached to the first."""
    fx.set_clock(api, BENEFIT_START)
    provider = fx.register_provider(api)
    dwelling = fx.register_address(
        api,
        address_line1="1200 N Main St",
        unit_designator="Apt 4B",
        city="El Paso",
        state_code="TX",
        postal_code="79901",
    )
    applicant = fx.eligible_applicant(api, dwelling["id"])
    twin = fx.register_address(
        api,
        address_line1="1200 n. main st.",
        unit_designator="apt 4-b",
        city="EL PASO",
        state_code="TX",
        postal_code="799012214",
    )
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "dwelling": dwelling,
        "twin": twin,
        "applicant": applicant,
    }


def test_enrollment_is_refused_while_the_dwelling_sits_in_an_unresolved_cohort(api):
    """The benefit cannot be created until a program administrator adjudicates the cohort.

    PRD: "Then the certified dwelling must not be sitting in `DUPLICATE_FLAGGED`, otherwise
    `ERR_ADDRESS_DUPLICATE_UNRESOLVED` — an unresolved cohort must be adjudicated by a
    `ProgramAdministrator` before any of its dwellings can take a new benefit."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_gated_on_household_address_duplicate_resolution
    """
    context = _flagged_cohort_with_a_waiting_applicant(api)
    dwelling = fx.refresh_address(api, context["dwelling"]["id"])

    assert dwelling["address_hash"] == CANONICAL_HASH, (
        f"the canonical form is the stored value, got {dwelling['address_hash']}"
    )
    assert address_hash_for("1200 N Main St", "Apt 4B", "El Paso", "TX", "79901") == CANONICAL_HASH
    assert dwelling["cohort_address_count"] == 2, "two spellings share the hash"
    assert dwelling["status"] == "DUPLICATE_FLAGGED"
    assert dwelling["max_permitted_benefit_slots"] == 1
    assert (
        fx.refresh_subscriber(api, context["applicant"]["subscriber"]["id"])["status"]
        == "VERIFIED_ELIGIBLE"
    ), "an applicant created before the flag keeps its verified posture"

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["applicant"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=context["applicant"]["check"]["id"],
            certified_address_id=dwelling["id"],
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.ADDRESS_DUPLICATE_UNRESOLVED.value, 409)

    assert fx.refresh_address(api, dwelling["id"])["occupied_benefit_slots"] == 0
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 0


def test_adjudicating_the_cohort_as_multi_household_opens_the_gate(api):
    """Resolving the one dwelling admits the benefit and leaves the twin spelling flagged.

    PRD: "Both values are written onto the dwelling, its posture becomes
    `RESOLVED_MULTI_HOUSEHOLD`, `max_permitted_benefit_slots` recomputes to the declared
    count, every applicant held at that dwelling behind a duplicate hold is released as
    described in §3.3, and `version` advances by one."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_gated_on_household_address_duplicate_resolution
    """
    context = _flagged_cohort_with_a_waiting_applicant(api)
    resolved = fx.resolve_multi_household(
        api, context["dwelling"]["id"], declared_household_count=2, worksheet_ref="WS-1"
    )
    assert resolved["status"] == "RESOLVED_MULTI_HOUSEHOLD"
    assert resolved["declared_household_count"] == 2
    assert resolved["independent_household_worksheet_ref"] == "WS-1"
    assert resolved["max_permitted_benefit_slots"] == 2

    twin = fx.refresh_address(api, context["twin"]["id"])
    assert twin["status"] == "DUPLICATE_FLAGGED", (
        "resolving one row does not adjudicate the other row in the cohort"
    )
    assert twin["max_permitted_benefit_slots"] == 1

    enrollment = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                subscriber_id=context["applicant"]["subscriber"]["id"],
                provider_id=context["provider"]["id"],
                eligibility_check_id=context["applicant"]["check"]["id"],
                certified_address_id=context["dwelling"]["id"],
            ),
            context["agent"],
        ),
        201,
    )
    assert enrollment["benefit_status"] == "ACTIVE"
    assert fx.refresh_address(api, context["dwelling"]["id"])["occupied_benefit_slots"] == 1
    assert (
        fx.refresh_subscriber(api, context["applicant"]["subscriber"]["id"])["status"]
        == "ENROLLED"
    )
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 1


def _port_request_to_a_suspended_carrier(api):
    """A portable benefit at carrier A with a request outstanding to suspended carrier B."""
    fx.set_clock(api, BENEFIT_START)
    losing = fx.register_provider(api, name="SafeLink Wireless")
    suspended = fx.register_provider(api, name="Assurance Mobile", status="SUSPENDED")
    gaining = fx.register_provider(api, name="TruConnect")

    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    enrollment = fx.enroll(
        api,
        losing,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=BENEFIT_START,
    )
    assert_instant(enrollment["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")

    fx.set_clock(api, PORT_FREEZE_UNTIL)
    request = fx.request_transfer(api, losing, enrollment["id"], suspended["id"])
    return {
        "losing": losing,
        "suspended": suspended,
        "gaining": gaining,
        "enrollment": enrollment,
        "request": request,
    }


def test_acceptance_is_refused_when_the_gaining_carrier_is_not_active(api):
    """The bar is read off the target carrier's own row, not the caller's.

    PRD: "The gaining carrier's `status` must be `ACTIVE`, or the acceptance is refused with
    `ERR_PROVIDER_NOT_ACTIVE`; note that this bar is evaluated against the *target* carrier
    here, not the caller's own record in some other sense."

    Design: Difficulty/cross_entity_state_dependency/transfer_acceptance_gated_on_target_provider_active_status
    """
    context = _port_request_to_a_suspended_carrier(api)
    request = context["request"]
    assert_service_transfer(request)
    assert request["status"] == "REQUESTED"
    assert context["suspended"]["status"] == "SUSPENDED"

    response = api.accept_service_transfer(
        request["id"],
        f.transfer_accept_payload(),
        fx.provider_headers(context["suspended"]),
    )
    validate_error(response, ApiErrorId.PROVIDER_NOT_ACTIVE.value, 409)

    unchanged = fx.refresh_transfer(api, request["id"])
    assert unchanged["status"] == "REQUESTED", (
        f"the refused acceptance leaves the request open, got {unchanged['status']}"
    )
    assert unchanged["completed_at"] is None

    benefit = fx.refresh_enrollment(api, context["enrollment"]["id"])
    assert benefit["provider_id"] == context["losing"]["id"], "the benefit never moved"
    assert benefit["transfer_count"] == 0
    assert fx.refresh_provider(api, context["losing"]["id"])["active_enrollment_count"] == 1
    assert fx.refresh_provider(api, context["suspended"]["id"])["active_enrollment_count"] == 0


def test_a_fresh_request_to_an_active_carrier_supersedes_and_completes_the_port(api):
    """Redirecting the port to an ACTIVE carrier supersedes the dead request and completes.

    PRD: "Crucially, `benefit_start_date`, `port_freeze_until` and `recert_due_date` are
    **preserved verbatim**."

    Design: Difficulty/cross_entity_state_dependency/transfer_acceptance_gated_on_target_provider_active_status
    """
    context = _port_request_to_a_suspended_carrier(api)
    second = fx.request_transfer(
        api, context["losing"], context["enrollment"]["id"], context["gaining"]["id"]
    )

    superseded = fx.refresh_transfer(api, context["request"]["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the older open request is superseded, got {superseded['status']}"
    )
    assert_instant(superseded["completed_at"], PORT_FREEZE_UNTIL, "completed_at")

    accepted = fx.accept_transfer(api, second["id"], context["gaining"])
    assert accepted["status"] == "ACCEPTED_COMPLETED"
    assert_instant(accepted["completed_at"], PORT_FREEZE_UNTIL, "completed_at")

    benefit = fx.refresh_enrollment(api, context["enrollment"]["id"])
    assert benefit["provider_id"] == context["gaining"]["id"], "link one rewrites the carrier"
    assert benefit["transfer_count"] == 1
    assert_instant(benefit["benefit_start_date"], BENEFIT_START, "benefit_start_date")
    assert_instant(benefit["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")
    assert_date_component(benefit["recert_due_date"], "2027-08-01", "recert_due_date")
    assert benefit["usage_status"] == "PENDING_FIRST_USE", "the porting does not touch usage"
    assert benefit["audit_risk_score"] == 15, (
        f"a ported benefit picks up the transfer weighting, got {benefit['audit_risk_score']}"
    )

    assert fx.refresh_provider(api, context["losing"]["id"])["active_enrollment_count"] == 0
    assert fx.refresh_provider(api, context["gaining"]["id"])["active_enrollment_count"] == 1
    assert fx.refresh_provider(api, context["suspended"]["id"])["active_enrollment_count"] == 0
