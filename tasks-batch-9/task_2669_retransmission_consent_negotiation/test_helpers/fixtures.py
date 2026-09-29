"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints, so a
test can start against an empty database and still reach a late lifecycle
state. Setup calls use the lenient validator so a broken precondition reports
as a setup failure rather than as a confusing assertion failure.

Identity threading: the two entity-backed roles always act through the
per-instance header builders, so a StationGroupNegotiator call carries the
Station's own id and a DistributorRep call carries the Distributor's own id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accept_offer_payload,
    create_affiliation_agreement_payload,
    create_audit_finding_payload,
    create_blackout_notice_payload,
    create_distributor_payload,
    create_election_payload,
    create_fee_settlement_payload,
    create_good_faith_log_payload,
    create_interim_extension_payload,
    create_offer_payload,
    create_rights_dispute_payload,
    create_station_payload,
    create_subscriber_report_payload,
    declare_impasse_payload,
    execute_agreement_payload,
    network_approval_payload,
    resolve_audit_finding_payload,
    resolve_rights_dispute_payload,
    set_clock_payload,
    true_up_payload,
)
from .test_users import (
    ACCEPTING_COUNSEL_USER_ID,
    EXECUTING_COUNSEL_USER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_distributor_rep_headers,
    make_group_counsel_headers,
    make_network_representative_headers,
    make_station_negotiator_headers,
)

ADMIN = TEST_USERS["carriage_admin_headers"]


# --------------------------------------------------------------- logical clock
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock and return the clock endpoint's response data."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    )


def run_expiration_sweep() -> dict:
    """Trigger the time-driven maintenance pass and return its five counts."""
    return get_success_data(api_client.run_expiration_sweep({}, ADMIN))


# ------------------------------------------------------------- single-step steps
def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_station(create_station_payload(**overrides), ADMIN)
    )


def create_affiliation_agreement(station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_affiliation_agreement(
            station_id, create_affiliation_agreement_payload(**overrides), ADMIN
        )
    )


def create_distributor(**overrides) -> dict:
    return get_success_data(
        api_client.create_distributor(create_distributor_payload(**overrides), ADMIN)
    )


def create_election(station_id: str, distributor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_election(
            create_election_payload(station_id, distributor_id, **overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def file_election(election_id: str, station_id: str) -> dict:
    return get_success_data(
        api_client.file_election(
            election_id, {}, make_station_negotiator_headers(station_id)
        )
    )


def negotiation_of_election(election_id: str) -> dict:
    """The single negotiation that filing a retransmission-consent election opens."""
    data = get_success_data(api_client.list_election_negotiations(election_id, ADMIN))
    assert data, f"filing election {election_id} should have opened one negotiation"
    return data[0]


def create_subscriber_report(station_id: str, distributor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber_report(
            create_subscriber_report_payload(station_id, **overrides),
            make_distributor_rep_headers(distributor_id),
        )
    )


def submit_station_offer(
    negotiation_id: str, station_id: str, subscriber_report_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_offer(
            negotiation_id,
            create_offer_payload(subscriber_report_id, **overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def submit_distributor_offer(
    negotiation_id: str, distributor_id: str, subscriber_report_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_offer(
            negotiation_id,
            create_offer_payload(subscriber_report_id, **overrides),
            make_distributor_rep_headers(distributor_id),
        )
    )


def negotiation_version(negotiation_id: str) -> int:
    return get_success_data(api_client.get_negotiation(negotiation_id, ADMIN))["version"]


def agreement_version(agreement_id: str) -> int:
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))["version"]


def read_negotiation(negotiation_id: str) -> dict:
    return get_success_data(api_client.get_negotiation(negotiation_id, ADMIN))


def read_election(election_id: str) -> dict:
    return get_success_data(api_client.get_election(election_id, ADMIN))


def read_station(station_id: str) -> dict:
    return get_success_data(api_client.get_station(station_id, ADMIN))


def read_distributor(distributor_id: str) -> dict:
    return get_success_data(api_client.get_distributor(distributor_id, ADMIN))


def read_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_offer(offer_id, ADMIN))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def read_subscriber_report(report_id: str) -> dict:
    return get_success_data(api_client.get_subscriber_report(report_id, ADMIN))


def read_settlements(agreement_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_fee_settlements(agreement_id, TEST_USERS["group_counsel_headers"], params)
    )


def read_extensions(agreement_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_interim_extensions(agreement_id, ADMIN, params)
    )


def read_rights_disputes(agreement_id: str, params=None) -> list:
    return get_success_data(api_client.list_rights_disputes(agreement_id, ADMIN, params))


def read_blackout_notices(negotiation_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_blackout_notices(negotiation_id, ADMIN, params)
    )


def read_offers_of_negotiation(negotiation_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_negotiation_offers(negotiation_id, ADMIN, params)
    )


def accept_offer(
    offer_id: str, negotiation_id: str, counsel_user_id: str = ACCEPTING_COUNSEL_USER_ID,
    **overrides
) -> dict:
    """Accept an outstanding offer on the negotiation's current version."""
    payload = accept_offer_payload(negotiation_version(negotiation_id), **overrides)
    return get_success_data(
        api_client.accept_offer(
            offer_id, payload, make_group_counsel_headers(counsel_user_id)
        )
    )


def approve_network(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_network_approval(
            agreement_id,
            network_approval_payload("APPROVE", **overrides),
            make_network_representative_headers(),
        )
    )


def execute_agreement(
    agreement_id: str, counsel_user_id: str = EXECUTING_COUNSEL_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.execute_agreement(
            agreement_id,
            execute_agreement_payload(**overrides),
            make_group_counsel_headers(counsel_user_id),
        )
    )


def issue_settlement(
    agreement_id: str,
    subscriber_report_id: str,
    counsel_user_id: str = ACCEPTING_COUNSEL_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_fee_settlement(
            agreement_id,
            create_fee_settlement_payload(subscriber_report_id, **overrides),
            make_group_counsel_headers(counsel_user_id),
        )
    )


def true_up_settlement(
    settlement_id: str, counsel_user_id: str = ACCEPTING_COUNSEL_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.true_up_fee_settlement(
            settlement_id,
            true_up_payload(**overrides),
            make_group_counsel_headers(counsel_user_id),
        )
    )


def create_interim_extension(
    agreement_id: str, station_id: str, expected_version=None, **overrides
) -> dict:
    version = (
        agreement_version(agreement_id) if expected_version is None else expected_version
    )
    return get_success_data(
        api_client.create_interim_extension(
            agreement_id,
            create_interim_extension_payload(version, **overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def raise_rights_dispute(
    agreement_id: str, station_id: str, disputed_term: str = "STREAMING", **overrides
) -> dict:
    return get_success_data(
        api_client.create_rights_dispute(
            agreement_id,
            create_rights_dispute_payload(disputed_term, **overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def resolve_rights_dispute(dispute_id: str, resolution: str = "EXCLUDED", **overrides) -> dict:
    return get_success_data(
        api_client.resolve_rights_dispute(
            dispute_id,
            resolve_rights_dispute_payload(resolution, **overrides),
            make_compliance_officer_headers(),
        )
    )


def open_audit_finding(report_id: str, station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_finding(
            report_id,
            create_audit_finding_payload(**overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def resolve_audit_finding(
    finding_id: str, resolution: str = "SUBSTANTIATED", **overrides
) -> dict:
    return get_success_data(
        api_client.resolve_audit_finding(
            finding_id,
            resolve_audit_finding_payload(resolution, **overrides),
            make_compliance_officer_headers(),
        )
    )


def append_good_faith_entry(negotiation_id: str, headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_good_faith_log_entry(
            negotiation_id, create_good_faith_log_payload(**overrides), headers
        )
    )


def declare_impasse(negotiation_id: str, station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.declare_impasse(
            negotiation_id,
            declare_impasse_payload(**overrides),
            make_station_negotiator_headers(station_id),
        )
    )


def serve_blackout_notice(negotiation_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_blackout_notice(
            negotiation_id,
            create_blackout_notice_payload(**overrides),
            make_compliance_officer_headers(),
        )
    )


# --------------------------------------------------------- composite scenarios
STAGE_ORDER = [
    "station",
    "distributor",
    "election",
    "filed",
    "report",
    "offer",
    "accepted",
    "approved",
    "executed",
    "settled",
]


def _reached(stage: str, target: str) -> bool:
    return STAGE_ORDER.index(stage) <= STAGE_ORDER.index(target)


def build_carriage_scenario(
    stage: str = "executed",
    station=None,
    affiliation=None,
    with_affiliation: bool = True,
    distributor=None,
    election=None,
    report=None,
    offer=None,
    accept=None,
    settlement=None,
    accepting_counsel: str = ACCEPTING_COUNSEL_USER_ID,
    executing_counsel: str = EXECUTING_COUNSEL_USER_ID,
) -> dict:
    """Walk the carriage cycle from station registration up to `stage`.

    Each of the payload arguments is a dict of overrides applied to the
    corresponding factory, so a test can pin exactly the inputs it cares about
    (base rate, escalator, term, reported subscriber count, video households,
    split premium, reverse-compensation floor, permitted tiers, rights flags,
    distributor type, measurement method, carriage term) and inherit sensible
    defaults for everything else.

    Returns a dict carrying every entity created plus ready-made headers for
    the two entity-backed roles.
    """
    assert stage in STAGE_ORDER, f"unknown stage {stage}"
    ctx: dict = {}

    ctx["station"] = create_station(**(station or {}))
    station_id = ctx["station"]["id"]
    ctx["negotiator_headers"] = make_station_negotiator_headers(station_id)
    if with_affiliation:
        ctx["affiliation"] = create_affiliation_agreement(
            station_id, **(affiliation or {})
        )
    if not _reached("distributor", stage):
        return ctx

    ctx["distributor"] = create_distributor(**(distributor or {}))
    distributor_id = ctx["distributor"]["id"]
    ctx["rep_headers"] = make_distributor_rep_headers(distributor_id)
    if not _reached("election", stage):
        return ctx

    ctx["election"] = create_election(station_id, distributor_id, **(election or {}))
    if not _reached("filed", stage):
        return ctx

    ctx["election"] = file_election(ctx["election"]["id"], station_id)
    if ctx["election"]["election_type"] == "RETRANS_CONSENT":
        ctx["negotiation"] = negotiation_of_election(ctx["election"]["id"])
    if not _reached("report", stage):
        return ctx

    ctx["report"] = create_subscriber_report(
        station_id, distributor_id, **(report or {})
    )
    if not _reached("offer", stage):
        return ctx

    ctx["offer"] = submit_station_offer(
        ctx["negotiation"]["id"], station_id, ctx["report"]["id"], **(offer or {})
    )
    if not _reached("accepted", stage):
        return ctx

    ctx["agreement"] = accept_offer(
        ctx["offer"]["id"],
        ctx["negotiation"]["id"],
        counsel_user_id=accepting_counsel,
        **(accept or {}),
    )
    if not _reached("approved", stage):
        return ctx

    if ctx["agreement"]["network_approval_status"] == "PENDING_NETWORK":
        ctx["agreement"] = approve_network(ctx["agreement"]["id"])
    if not _reached("executed", stage):
        return ctx

    ctx["agreement"] = execute_agreement(
        ctx["agreement"]["id"], counsel_user_id=executing_counsel
    )
    if not _reached("settled", stage):
        return ctx

    ctx["settlement"] = issue_settlement(
        ctx["agreement"]["id"],
        ctx["report"]["id"],
        counsel_user_id=accepting_counsel,
        **(settlement or {}),
    )
    return ctx


def setup_station_and_distributor(**kwargs) -> dict:
    """One station with its network affiliation contract, plus one distributor."""
    return build_carriage_scenario(stage="distributor", **kwargs)


def setup_draft_election(**kwargs) -> dict:
    """Station, affiliation, distributor and a DRAFT carriage election."""
    return build_carriage_scenario(stage="election", **kwargs)


def setup_open_negotiation(**kwargs) -> dict:
    """A filed retransmission-consent election with its OPEN negotiation."""
    return build_carriage_scenario(stage="filed", **kwargs)


def setup_negotiation_with_report(**kwargs) -> dict:
    """An OPEN negotiation plus the distributor's subscriber report for a period."""
    return build_carriage_scenario(stage="report", **kwargs)


def setup_submitted_station_offer(**kwargs) -> dict:
    """A negotiation carrying one SUBMITTED station-group offer."""
    return build_carriage_scenario(stage="offer", **kwargs)


def setup_accepted_agreement(**kwargs) -> dict:
    """A carriage agreement in PENDING_EXECUTION awaiting the network."""
    return build_carriage_scenario(stage="accepted", **kwargs)


def setup_network_approved_agreement(**kwargs) -> dict:
    """A carriage agreement approved by the network but not yet executed."""
    return build_carriage_scenario(stage="approved", **kwargs)


def setup_executed_agreement(**kwargs) -> dict:
    """A fully EXECUTED carriage agreement."""
    return build_carriage_scenario(stage="executed", **kwargs)


def setup_issued_settlement(**kwargs) -> dict:
    """An EXECUTED agreement with one ISSUED fee settlement on it."""
    return build_carriage_scenario(stage="settled", **kwargs)


def setup_impasse_ready(meeting_count: int = 3, exchange_offers: bool = True, **kwargs) -> dict:
    """A negotiation with offers from both sides and `meeting_count` meetings logged.

    Meetings are appended as MEETING_HELD entries by the station-group side; a
    distributor counter is submitted so that both sides have tabled something.
    """
    ctx = build_carriage_scenario(stage="offer", **kwargs)
    if exchange_offers:
        ctx["distributor_offer"] = submit_distributor_offer(
            ctx["negotiation"]["id"],
            ctx["distributor"]["id"],
            ctx["report"]["id"],
            base_rate_per_sub_cents=180,
        )
    for index in range(meeting_count):
        append_good_faith_entry(
            ctx["negotiation"]["id"],
            ctx["negotiator_headers"],
            event_type="MEETING_HELD",
            summary=f"Bargaining session {index + 1} held with both principals present",
        )
    ctx["negotiation"] = read_negotiation(ctx["negotiation"]["id"])
    return ctx


def setup_adjusted_report(adjustment_subscribers: int = 6000, **kwargs) -> dict:
    """A scenario whose subscriber report has one SUBSTANTIATED audit finding."""
    ctx = kwargs.pop("scenario", None) or build_carriage_scenario(
        stage="settled", **kwargs
    )
    ctx["finding"] = open_audit_finding(
        ctx["report"]["id"],
        ctx["station"]["id"],
        adjustment_subscribers=adjustment_subscribers,
    )
    ctx["finding"] = resolve_audit_finding(ctx["finding"]["id"], "SUBSTANTIATED")
    ctx["report"] = read_subscriber_report(ctx["report"]["id"])
    return ctx


def setup_excluded_rights_dispute(disputed_term: str = "STREAMING", **kwargs) -> dict:
    """A settled scenario whose granted right `disputed_term` is resolved EXCLUDED."""
    ctx = kwargs.pop("scenario", None) or build_carriage_scenario(
        stage="settled", **kwargs
    )
    ctx["dispute"] = raise_rights_dispute(
        ctx["agreement"]["id"], ctx["station"]["id"], disputed_term
    )
    ctx["dispute"] = resolve_rights_dispute(ctx["dispute"]["id"], "EXCLUDED")
    ctx["agreement"] = read_agreement(ctx["agreement"]["id"])
    return ctx
