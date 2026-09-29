"""Composite setup helpers.

Every test starts against an empty database, so each helper rebuilds its
preconditions from scratch through the endpoints the PRD declares. Helpers
thread a mutable ``env`` dict so a test can start anywhere along the chain and
still reach the entities the earlier steps created.

env keys, as they become available:
    jurisdiction, taxability_rules (fee_code -> rule), property, channel,
    program, fees (code -> fee), inclusions (service_code -> inclusion),
    profile, booking, folio, folio_lines, opt_out, complaint, inquiry
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ARRIVAL_DATE,
    OCCUPANCY_TAX_RATE_BPS,
)
from .factories import (
    create_booking_payload,
    create_channel_payload,
    create_destination_fee_payload,
    create_fee_program_payload,
    create_guest_complaint_payload,
    create_jurisdiction_payload,
    create_profile_payload,
    create_property_payload,
    create_regulator_inquiry_payload,
    create_resort_fee_payload,
    create_wifi_fee_payload,
)
from .test_users import (
    TEST_USERS,
    make_channel_operator_headers,
    make_guest_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVENUE = TEST_USERS["revenue_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]
LIAISON = TEST_USERS["regulatory_liaison_headers"]
LIAISON_2 = TEST_USERS["regulatory_liaison_2_headers"]
AGENT = TEST_USERS["guest_services_agent_headers"]

# The canonical three mandatory fees and the taxability of each.
CANONICAL_TAXABILITY = {
    "RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS),
    "DESTINATION": ("TAXABLE_IF_MANDATORY", OCCUPANCY_TAX_RATE_BPS),
    "WIFI_PREMIUM": ("EXEMPT", None),
}

# One value-bearing inclusion per mandatory fee, which is what drives an
# inclusion_coverage_ratio of 1.0000 at publication.
CANONICAL_INCLUSIONS = {
    "RESORT": {
        "service_code": "POOL_ACCESS",
        "service_label": "Pool and cabana access",
        "retail_value_cents": 1500,
        "units": 1,
    },
    "DESTINATION": {
        "service_code": "SHUTTLE",
        "service_label": "Airport shuttle",
        "retail_value_cents": 1200,
        "units": 1,
    },
    "WIFI_PREMIUM": {
        "service_code": "WIFI_TIER2",
        "service_label": "Tier-2 Wi-Fi for two devices",
        "retail_value_cents": 400,
        "units": 2,
    },
}


def _ok(response, label: str) -> dict:
    """Lenient extraction so a broken precondition reads as a setup failure."""
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(f"Setup failed at {label}: {exc}") from exc


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def move_clock_to(instant: str) -> str:
    """Move the logical clock and return the instant the server reports."""
    data = _ok(api_client.set_clock(instant, ADMIN), f"set clock to {instant}")
    return data["current_utc"]


def read_clock() -> str:
    return _ok(api_client.get_clock(), "read clock")["current_utc"]


# --------------------------------------------------------------------------
# Reference data primitives
# --------------------------------------------------------------------------
def create_jurisdiction(**overrides) -> dict:
    payload = create_jurisdiction_payload(**overrides)
    return _ok(api_client.create_jurisdiction(payload, ADMIN), "create jurisdiction")


def create_taxability_rule(jurisdiction_id, fee_code, taxability, tax_rate_bps) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "fee_code": fee_code,
        "taxability": taxability,
        "tax_rate_bps": tax_rate_bps,
    }
    return _ok(
        api_client.create_taxability_rule(payload, ADMIN),
        f"create taxability rule for {fee_code}",
    )


def create_taxability_rules(jurisdiction_id, spec=None) -> dict:
    """Create one rule per entry of ``spec``; returns them keyed by fee code."""
    spec = CANONICAL_TAXABILITY if spec is None else spec
    rules = {}
    for fee_code, (taxability, rate) in spec.items():
        rules[fee_code] = create_taxability_rule(
            jurisdiction_id, fee_code, taxability, rate
        )
    return rules


def create_property(jurisdiction_id, **overrides) -> dict:
    payload = create_property_payload(jurisdiction_id, **overrides)
    return _ok(api_client.create_property(payload, ADMIN), "create property")


def create_channel(**overrides) -> dict:
    payload = create_channel_payload(**overrides)
    return _ok(api_client.create_channel(payload, ADMIN), "create channel")


def read_property(property_id, headers=None) -> dict:
    return _ok(
        api_client.get_property(property_id, headers or ADMIN), "read property"
    )


def read_fee_program(program_id, headers=None) -> dict:
    return _ok(
        api_client.get_fee_program(program_id, headers or REVENUE), "read fee program"
    )


def read_profile(profile_id, headers=None) -> dict:
    return _ok(
        api_client.get_channel_disclosure_profile(profile_id, headers or COMPLIANCE),
        "read disclosure profile",
    )


def read_booking(booking_id, headers=None) -> dict:
    return _ok(api_client.get_booking(booking_id, headers or AGENT), "read booking")


def read_folio(folio_id, headers=None) -> dict:
    return _ok(api_client.get_folio(folio_id, headers or AGENT), "read folio")


def read_folio_lines(folio_id, headers=None) -> list:
    response = api_client.list_folio_lines(headers or AGENT, {"folio_id": folio_id, "limit": 100})
    data = _ok(response, "list folio lines")
    return data if isinstance(data, list) else data.get("items", [])


def read_disclosure_summary(property_id, headers=None) -> dict:
    return _ok(
        api_client.get_disclosure_summary(property_id, headers or COMPLIANCE),
        "read disclosure summary",
    )


# --------------------------------------------------------------------------
# Configuration tier: jurisdiction + taxability rules + property + channel
# --------------------------------------------------------------------------
def setup_configuration(
    jurisdiction_overrides=None,
    property_overrides=None,
    channel_overrides=None,
    taxability_spec=None,
) -> dict:
    """Reference data every later tier depends on."""
    env = {}
    env["jurisdiction"] = create_jurisdiction(**(jurisdiction_overrides or {}))
    env["taxability_rules"] = create_taxability_rules(
        env["jurisdiction"]["id"], taxability_spec
    )
    env["property"] = create_property(
        env["jurisdiction"]["id"], **(property_overrides or {})
    )
    env["channel"] = create_channel(**(channel_overrides or {}))
    return env


def add_channel(env, key, **overrides) -> dict:
    """Register an extra channel and file it in env under ``key``."""
    channel = create_channel(**overrides)
    env[key] = channel
    return channel


# --------------------------------------------------------------------------
# Fee program tier
# --------------------------------------------------------------------------
def default_fee_payloads() -> list:
    return [
        create_resort_fee_payload(),
        create_destination_fee_payload(),
        create_wifi_fee_payload(),
    ]


def add_fee(program_id, payload, headers=None) -> dict:
    return _ok(
        api_client.create_fee(program_id, payload, headers or REVENUE),
        f"add fee {payload.get('code')}",
    )


def add_inclusion(fee_id, payload, headers=None) -> dict:
    return _ok(
        api_client.create_fee_inclusion(fee_id, payload, headers or REVENUE),
        f"add inclusion {payload.get('service_code')}",
    )


def setup_draft_program(
    env=None,
    fee_payloads=None,
    inclusion_spec=None,
    program_overrides=None,
    **configuration_kwargs,
) -> dict:
    """A DRAFT program on an ACTIVE property, with fees and their inclusions.

    ``fee_payloads`` defaults to the three canonical mandatory fees.
    ``inclusion_spec`` maps a fee code to a single inclusion payload, or to a
    list of them; pass ``{}`` for a program with no inclusion evidence at all.
    """
    env = setup_configuration(**configuration_kwargs) if env is None else env
    payload = create_fee_program_payload(
        env["property"]["id"], env["property"]["version"], **(program_overrides or {})
    )
    env["program"] = _ok(
        api_client.create_fee_program(payload, REVENUE), "create fee program"
    )
    fee_payloads = default_fee_payloads() if fee_payloads is None else fee_payloads
    inclusion_spec = CANONICAL_INCLUSIONS if inclusion_spec is None else inclusion_spec
    env.setdefault("fees", {})
    env.setdefault("inclusions", {})
    for fee_payload in fee_payloads:
        fee = add_fee(env["program"]["id"], fee_payload)
        env["fees"][fee["code"]] = fee
        wanted = inclusion_spec.get(fee["code"])
        if wanted is None:
            continue
        for inclusion_payload in wanted if isinstance(wanted, list) else [wanted]:
            inclusion = add_inclusion(fee["id"], inclusion_payload)
            env["inclusions"][inclusion["service_code"]] = inclusion
    env["program"] = read_fee_program(env["program"]["id"])
    return env


def setup_program_under_review(env=None, **kwargs) -> dict:
    """A DRAFT program advanced to UNDER_REVIEW."""
    env = setup_draft_program(**kwargs) if env is None else env
    env["program"] = _ok(
        api_client.submit_fee_program_for_review(env["program"]["id"], REVENUE),
        "submit fee program for review",
    )
    return env


def setup_published_program(
    env=None, attestation_note="Attested against the county disclosure mandate.", **kwargs
) -> dict:
    """A PUBLISHED program. Authored by the revenue manager, attested by the
    compliance officer, so segregation of duties is satisfied."""
    env = setup_program_under_review(**kwargs) if env is None else env
    env["program"] = _ok(
        api_client.publish_fee_program(
            env["program"]["id"], attestation_note, COMPLIANCE
        ),
        "publish fee program",
    )
    env["property"] = read_property(env["property"]["id"])
    return env


# --------------------------------------------------------------------------
# Disclosure profile tier
# --------------------------------------------------------------------------
def add_draft_profile(env, channel=None, headers=None, **profile_overrides) -> dict:
    """Create a DRAFT booking path bound to the env's published program.

    A successful create increments the bound program's version, so the env's
    copy of the program is refreshed on both sides of the call and any number of
    paths may be opened in sequence against a current concurrency token.
    """
    channel = channel or env["channel"]
    env["program"] = read_fee_program(env["program"]["id"])
    payload = create_profile_payload(
        env["property"]["id"],
        channel["id"],
        env["program"]["id"],
        env["program"]["version"],
        **profile_overrides,
    )
    profile = _ok(
        api_client.create_channel_disclosure_profile(
            payload, headers or make_channel_operator_headers(channel["id"])
        ),
        "create channel disclosure profile",
    )
    env["program"] = read_fee_program(env["program"]["id"])
    return profile


def setup_draft_profile(env=None, profile_overrides=None, **kwargs) -> dict:
    env = setup_published_program(**kwargs) if env is None else env
    env["profile"] = add_draft_profile(env, **(profile_overrides or {}))
    env["program"] = read_fee_program(env["program"]["id"])
    return env


def deploy_profile(env, profile=None, headers=None) -> dict:
    profile = profile or env["profile"]
    return _ok(
        api_client.deploy_profile(profile["id"], headers or COMPLIANCE),
        "deploy disclosure profile",
    )


def setup_deployed_profile(env=None, profile_overrides=None, **kwargs) -> dict:
    """A DEPLOYED, therefore bookable, disclosure profile."""
    env = (
        setup_draft_profile(profile_overrides=profile_overrides, **kwargs)
        if env is None
        else env
    )
    env["profile"] = deploy_profile(env)
    env["property"] = read_property(env["property"]["id"])
    return env


def setup_flagged_profile(env=None, profile_overrides=None, **kwargs) -> dict:
    """A DEPLOYED profile audited below the compliance floor, so FLAGGED.

    Callers must supply switches that score under 60; the default is a path
    that shows no total, itemises nothing and buries disclosure at checkout.
    """
    if profile_overrides is None:
        profile_overrides = {
            "first_quote_shows_total": True,
            "itemized_at_first_quote": False,
            "disclosure_placement": "CHECKOUT",
        }
    env = (
        setup_deployed_profile(profile_overrides=profile_overrides, **kwargs)
        if env is None
        else env
    )
    env["profile"] = _ok(
        api_client.audit_profile(env["profile"]["id"], COMPLIANCE), "audit profile"
    )
    env["property"] = read_property(env["property"]["id"])
    return env


def remediate_profile(env, payload, profile=None, headers=None) -> dict:
    profile = profile or env["profile"]
    return _ok(
        api_client.remediate_profile(
            profile["id"],
            payload,
            headers or make_channel_operator_headers(env["channel"]["id"]),
        ),
        "remediate disclosure profile",
    )


# --------------------------------------------------------------------------
# Booking tier
# --------------------------------------------------------------------------
def add_booking(env, profile=None, channel=None, headers=None, **booking_overrides) -> dict:
    profile = profile or env["profile"]
    channel = channel or env["channel"]
    payload = create_booking_payload(
        env["property"]["id"], channel["id"], profile["id"], **booking_overrides
    )
    return _ok(api_client.create_booking(payload, headers or AGENT), "create booking")


def setup_quoted_booking(env=None, booking_overrides=None, **kwargs) -> dict:
    """A QUOTED / PENDING_AUDIT booking on a deployed path."""
    env = setup_deployed_profile(**kwargs) if env is None else env
    env["booking"] = add_booking(env, **(booking_overrides or {}))
    return env


def setup_confirmed_booking(env=None, **kwargs) -> dict:
    env = setup_quoted_booking(**kwargs) if env is None else env
    env["booking"] = _ok(
        api_client.confirm_booking(env["booking"]["id"], AGENT), "confirm booking"
    )
    return env


def setup_in_house_booking(env=None, arrival_instant=ARRIVAL_DATE, **kwargs) -> dict:
    """A CHECKED-IN booking with its single OPEN folio.

    The logical clock is moved to the arrival instant, which is the earliest
    moment check-in is permitted.
    """
    env = setup_confirmed_booking(**kwargs) if env is None else env
    move_clock_to(arrival_instant)
    env["booking"] = _ok(
        api_client.check_in_booking(env["booking"]["id"], AGENT), "check in booking"
    )
    folios = _ok(
        api_client.list_booking_folios(env["booking"]["id"], AGENT),
        "list folios of booking",
    )
    env["folio"] = folios[0]
    return env


def setup_itemized_folio(env=None, **kwargs) -> dict:
    """An ITEMIZED folio carrying the room line and every mandatory-fee line."""
    env = setup_in_house_booking(**kwargs) if env is None else env
    env["folio"] = _ok(
        api_client.itemize_folio(env["folio"]["id"], AGENT), "itemize folio"
    )
    env["folio_lines"] = read_folio_lines(env["folio"]["id"])
    env["booking"] = read_booking(env["booking"]["id"])
    return env


def setup_checked_out_booking(env=None, departure_instant="2026-09-14T00:00:00Z", **kwargs) -> dict:
    """An ITEMIZED folio whose booking has reached CHECKED_OUT."""
    env = setup_itemized_folio(**kwargs) if env is None else env
    move_clock_to(departure_instant)
    env["booking"] = _ok(
        api_client.check_out_booking(env["booking"]["id"], AGENT), "check out booking"
    )
    return env


def setup_posted_folio(env=None, **kwargs) -> dict:
    """A POSTED folio on a CHECKED_OUT booking — the adjustable ledger state."""
    env = setup_checked_out_booking(**kwargs) if env is None else env
    env["folio"] = _ok(api_client.post_folio(env["folio"]["id"], AGENT), "post folio")
    env["folio_lines"] = read_folio_lines(env["folio"]["id"])
    env["booking"] = read_booking(env["booking"]["id"])
    return env


def advance_to_posted_folio(env, arrival_instant=ARRIVAL_DATE,
                            departure_instant="2026-09-14T00:00:00Z") -> dict:
    """Walk an already-confirmed booking through check-in, itemisation,
    check-out and posting, leaving the folio POSTED and adjustable."""
    setup_in_house_booking(env=env, arrival_instant=arrival_instant)
    setup_itemized_folio(env=env)
    setup_checked_out_booking(env=env, departure_instant=departure_instant)
    setup_posted_folio(env=env)
    return env


# --------------------------------------------------------------------------
# Opt-out tier
#
# An opt-out request is only accepted while the fee's opt-out window is still
# open, so it must be filed before the clock reaches the arrival instant; the
# decision on it happens later, once the folio is adjustable.
# --------------------------------------------------------------------------
def add_opt_out_request(env, fee_code="DESTINATION", headers=None, fee_id=None) -> dict:
    booking = env["booking"]
    fee_id = fee_id or env["fees"][fee_code]["id"]
    return _ok(
        api_client.create_opt_out_request(
            booking["id"], fee_id, headers or make_guest_headers(booking["id"])
        ),
        f"create opt-out request for {fee_code}",
    )


def setup_requested_opt_out(env=None, fee_code="DESTINATION", **kwargs) -> dict:
    """A REQUESTED opt-out on a CONFIRMED booking, filed inside the window."""
    env = setup_confirmed_booking(**kwargs) if env is None else env
    env["opt_out"] = add_opt_out_request(env, fee_code)
    return env


def setup_requested_opt_out_on_posted_folio(
    env=None, fee_code="DESTINATION", **kwargs
) -> dict:
    """A REQUESTED opt-out whose booking has since reached a POSTED folio."""
    env = setup_requested_opt_out(fee_code=fee_code, **kwargs) if env is None else env
    advance_to_posted_folio(env)
    env["opt_out"] = _ok(
        api_client.get_opt_out_request(env["opt_out"]["id"], AGENT),
        "read opt-out request",
    )
    return env


def setup_granted_opt_out(env=None, fee_code="DESTINATION", **kwargs) -> dict:
    """A GRANTED opt-out, so the folio carries its reversing credit line."""
    env = (
        setup_requested_opt_out_on_posted_folio(fee_code=fee_code, **kwargs)
        if env is None
        else env
    )
    env["opt_out"] = _ok(
        api_client.grant_opt_out_request(env["opt_out"]["id"], AGENT),
        "grant opt-out request",
    )
    env["folio"] = read_folio(env["folio"]["id"])
    env["folio_lines"] = read_folio_lines(env["folio"]["id"])
    env["booking"] = read_booking(env["booking"]["id"])
    return env


# --------------------------------------------------------------------------
# Complaint tier
# --------------------------------------------------------------------------
def add_complaint(env, folio_line_id=None, fee_code="WIFI_PREMIUM", headers=None,
                  **payload_overrides) -> dict:
    booking = env["booking"]
    if folio_line_id is None:
        lines = env.get("folio_lines") or read_folio_lines(env["folio"]["id"])
        matches = [line for line in lines if line.get("fee_code") == fee_code]
        assert matches, f"Setup failed: no folio line for fee code {fee_code}"
        folio_line_id = matches[0]["id"]
    payload = create_guest_complaint_payload(folio_line_id, **payload_overrides)
    return _ok(
        api_client.create_guest_complaint(
            booking["id"], payload, headers or make_guest_headers(booking["id"])
        ),
        "create guest complaint",
    )


def setup_submitted_complaint(env=None, fee_code="WIFI_PREMIUM",
                              complaint_overrides=None, **kwargs) -> dict:
    """A SUBMITTED complaint against a mandatory-fee line on a POSTED folio."""
    env = setup_posted_folio(**kwargs) if env is None else env
    env["complaint"] = add_complaint(env, fee_code=fee_code, **(complaint_overrides or {}))
    return env


def setup_investigated_complaint(env=None, **kwargs) -> dict:
    """A complaint moved to UNDER_INVESTIGATION by the first compliance officer."""
    env = setup_submitted_complaint(**kwargs) if env is None else env
    env["complaint"] = _ok(
        api_client.investigate_complaint(env["complaint"]["id"], COMPLIANCE),
        "investigate complaint",
    )
    return env


def setup_substantiated_complaint(env=None, **kwargs) -> dict:
    """A SUBSTANTIATED complaint. The second compliance officer adjudicates so
    the segregation-of-duties check against the investigator is satisfied."""
    env = setup_investigated_complaint(**kwargs) if env is None else env
    env["complaint"] = _ok(
        api_client.substantiate_complaint(env["complaint"]["id"], COMPLIANCE_2),
        "substantiate complaint",
    )
    env["booking"] = read_booking(env["booking"]["id"])
    env["profile"] = read_profile(env["profile"]["id"])
    env["property"] = read_property(env["property"]["id"])
    return env


# --------------------------------------------------------------------------
# Regulator inquiry tier
# --------------------------------------------------------------------------
def add_inquiry(env, headers=None, **overrides) -> dict:
    payload = create_regulator_inquiry_payload(
        env["jurisdiction"]["id"], env["property"]["id"], **overrides
    )
    return _ok(
        api_client.create_regulator_inquiry(payload, headers or LIAISON),
        "create regulator inquiry",
    )


def setup_received_inquiry(env=None, inquiry_overrides=None, **kwargs) -> dict:
    """A RECEIVED docket over a property that already has a quoted booking."""
    env = setup_quoted_booking(**kwargs) if env is None else env
    env["inquiry"] = add_inquiry(env, **(inquiry_overrides or {}))
    env["property"] = read_property(env["property"]["id"])
    return env


def setup_drafted_inquiry(env=None, response_summary="Operator response drafted.",
                          **kwargs) -> dict:
    env = setup_received_inquiry(**kwargs) if env is None else env
    env["inquiry"] = _ok(
        api_client.draft_inquiry_response(
            env["inquiry"]["id"], response_summary, LIAISON
        ),
        "draft inquiry response",
    )
    return env


def setup_submitted_inquiry(env=None, **kwargs) -> dict:
    """A RESPONSE_SUBMITTED docket. The second liaison submits so the
    segregation-of-duties check against the drafter is satisfied."""
    env = setup_drafted_inquiry(**kwargs) if env is None else env
    env["inquiry"] = _ok(
        api_client.submit_inquiry_response(env["inquiry"]["id"], LIAISON_2),
        "submit inquiry response",
    )
    return env


def setup_remediation_required_inquiry(
    env=None, remediation_directive="Repair every in-scope booking path.", **kwargs
) -> dict:
    """A REMEDIATION_REQUIRED docket whose flagging cascade has fired."""
    env = setup_submitted_inquiry(**kwargs) if env is None else env
    env["inquiry"] = _ok(
        api_client.require_inquiry_remediation(
            env["inquiry"]["id"], remediation_directive, ADMIN
        ),
        "require inquiry remediation",
    )
    env["profile"] = read_profile(env["profile"]["id"])
    env["booking"] = read_booking(env["booking"]["id"])
    env["property"] = read_property(env["property"]["id"])
    return env


# --------------------------------------------------------------------------
# Special-purpose scenario builders
# --------------------------------------------------------------------------
SINGLE_FEE_INCLUSIONS = {"RESORT": CANONICAL_INCLUSIONS["RESORT"]}


def setup_single_fee_published_program(**kwargs) -> dict:
    """A published program carrying only the percent-of-room resort fee.

    Used wherever a scenario needs exactly one mandatory fee so the reference
    per-night burden is the single 2243-cent contribution.
    """
    return setup_published_program(
        fee_payloads=[create_resort_fee_payload()],
        inclusion_spec=SINGLE_FEE_INCLUSIONS,
        taxability_spec={"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)},
        **kwargs,
    )


def setup_single_fee_deployed_profile(profile_overrides=None, **kwargs) -> dict:
    env = setup_single_fee_published_program(**kwargs)
    env["profile"] = add_draft_profile(env, **(profile_overrides or {}))
    env["profile"] = deploy_profile(env)
    env["property"] = read_property(env["property"]["id"])
    return env


def setup_tier_boundary_configuration(base_room_rate_cents, **kwargs) -> dict:
    """A published single-fee program on a property whose reference rate places
    the roll-in model on a commission-tier boundary."""
    return setup_single_fee_published_program(
        property_overrides={"base_room_rate_cents": base_room_rate_cents},
        **kwargs,
    )


def add_second_property(env, key="property_2", **overrides) -> dict:
    env[key] = create_property(env["jurisdiction"]["id"], **overrides)
    return env[key]


def add_second_jurisdiction(env, key="jurisdiction_2", **overrides) -> dict:
    defaults = {
        "code": "US-AZ-MARICOPA",
        "name": "Maricopa County, Arizona",
        "occupancy_tax_rate_bps": 1250,
    }
    defaults.update(overrides)
    env[key] = create_jurisdiction(**defaults)
    return env[key]
