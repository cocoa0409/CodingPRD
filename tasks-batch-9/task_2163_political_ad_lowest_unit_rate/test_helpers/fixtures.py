"""Composite setup helpers.

Most claims in this API need the platform in a state that takes eight to twenty
calls to reach: a station has to be registered, an election declared, a rate
class published, a buyer taken through the classification review loop, an order
opened, spotted, submitted, accepted, settled, aired or preempted, and only then
does the interesting behaviour become reachable.  These helpers build those
preambles once so tests can carry assertions rather than plumbing.

Every helper uses the lenient success reader, so a broken preamble surfaces as a
setup failure instead of as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    complaint_payload,
    complaint_response_payload,
    create_advertiser_payload,
    create_candidate_advertiser_payload,
    create_election_payload,
    create_order_payload,
    create_rate_class_payload,
    create_spot_payload,
    create_station_payload,
    eo_request_payload,
    luc_determination_payload,
    order_decision_payload,
    payment_payload,
)
from .test_users import (
    OFFICER_ALPHA_USER_ID,
    OFFICER_BETA_USER_ID,
    TEST_USERS,
    make_advertiser_agent_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]
TRAFFIC = TEST_USERS["traffic_scheduler_headers"]
PUBLIC = TEST_USERS["public_complainant_headers"]


def _merged(base: dict, overrides):
    if overrides:
        base = dict(base)
        base.update(overrides)
    return base


# ------------------------------------------------------ single-step steps ---


def set_clock(to_iso8601: str = None) -> str:
    """Move the logical clock and return the resulting current_utc."""
    to_iso8601 = to_iso8601 or D["CLOCK"]
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data.get("current_utc", to_iso8601)


def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_station(create_station_payload(**overrides), ADMIN)
    )


def create_election(station_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_election(
            create_election_payload(station_id, **overrides), ADMIN
        )
    )


def create_rate_class(station_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_class(
            create_rate_class_payload(station_id, **overrides), ADMIN
        )
    )


def withdraw_rate_class(rate_class_id) -> dict:
    return get_success_data(api_client.withdraw_rate_class(rate_class_id, ADMIN))


def intake_advertiser(station_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_advertiser(
            create_advertiser_payload(station_id, **overrides), OFFICER_ALPHA
        )
    )


def intake_candidate_advertiser(station_id, election_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_advertiser(
            create_candidate_advertiser_payload(station_id, election_id, **overrides),
            OFFICER_ALPHA,
        )
    )


def open_review(advertiser_id) -> dict:
    return get_success_data(api_client.review_advertiser(advertiser_id, OFFICER_ALPHA))


def decide_classification(advertiser_id, decision, reason=None, officer=None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.decide_advertiser(advertiser_id, payload, officer or OFFICER_ALPHA)
    )


def classify_issue_advertiser(station_id, **overrides) -> dict:
    """Intake, open the review, and record CLASSIFY_ISSUE."""
    advertiser = intake_advertiser(station_id, **overrides)
    open_review(advertiser["id"])
    return decide_classification(
        advertiser["id"], "CLASSIFY_ISSUE", "Non-candidate issue advocacy"
    )


def classify_candidate_advertiser(station_id, election_id, **overrides) -> dict:
    """Intake, open the review, and record CLASSIFY_CANDIDATE."""
    advertiser = intake_candidate_advertiser(station_id, election_id, **overrides)
    open_review(advertiser["id"])
    return decide_classification(
        advertiser["id"], "CLASSIFY_CANDIDATE", "Ballot access confirmed"
    )


def create_order(station_id, advertiser_id, rate_class_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(station_id, advertiser_id, rate_class_id, **overrides),
            make_advertiser_agent_headers(advertiser_id),
        )
    )


def add_spot(order_id, advertiser_id, **overrides) -> dict:
    return get_success_data(
        api_client.add_spot(
            order_id,
            create_spot_payload(**overrides),
            make_advertiser_agent_headers(advertiser_id),
        )
    )


def submit_order(order_id, advertiser_id) -> dict:
    return get_success_data(
        api_client.submit_order(order_id, make_advertiser_agent_headers(advertiser_id))
    )


def accept_order(order_id, officer_user_id=OFFICER_BETA_USER_ID) -> dict:
    return get_success_data(
        api_client.decide_order(
            order_id, order_decision_payload("ACCEPT"), make_officer_headers(officer_user_id)
        )
    )


def reject_order(order_id, rejection_reason, officer_user_id=OFFICER_BETA_USER_ID) -> dict:
    return get_success_data(
        api_client.decide_order(
            order_id,
            order_decision_payload("REJECT", rejection_reason=rejection_reason),
            make_officer_headers(officer_user_id),
        )
    )


def read_order(order_id, advertiser_id=None) -> dict:
    headers = (
        make_advertiser_agent_headers(advertiser_id) if advertiser_id else ADMIN
    )
    return get_success_data(api_client.get_order(order_id, headers))


def read_order_version(order_id, advertiser_id=None) -> int:
    return read_order(order_id, advertiser_id)["version"]


def charge_order(order_id, advertiser_id, amount_cents, expected_order_version=None) -> dict:
    """Settle the invoice with the exact outstanding amount."""
    if expected_order_version is None:
        expected_order_version = read_order_version(order_id, advertiser_id)
    return get_success_data(
        api_client.record_payment(
            order_id,
            payment_payload("CHARGE", amount_cents, expected_order_version),
            make_advertiser_agent_headers(advertiser_id),
        )
    )


def refund_order(order_id, advertiser_id, amount_cents, expected_order_version=None) -> dict:
    if expected_order_version is None:
        expected_order_version = read_order_version(order_id, advertiser_id)
    return get_success_data(
        api_client.record_payment(
            order_id,
            payment_payload("REFUND", amount_cents, expected_order_version),
            make_advertiser_agent_headers(advertiser_id),
        )
    )


def cancel_order(order_id, advertiser_id=None, cancellation_reason="Buyer withdrew the flight") -> dict:
    headers = (
        make_advertiser_agent_headers(advertiser_id) if advertiser_id else OFFICER_ALPHA
    )
    return get_success_data(
        api_client.cancel_order(
            order_id, {"cancellation_reason": cancellation_reason}, headers
        )
    )


def air_spot(spot_id) -> dict:
    return get_success_data(
        api_client.set_spot_disposition(spot_id, {"disposition": "AIRED"}, TRAFFIC)
    )


def preempt_spot(spot_id, preemption_reason="Breaking news override") -> dict:
    return get_success_data(
        api_client.set_spot_disposition(
            spot_id,
            {"disposition": "PREEMPTED", "preemption_reason": preemption_reason},
            TRAFFIC,
        )
    )


def read_spot(spot_id) -> dict:
    return get_success_data(api_client.get_spot(spot_id, ADMIN))


def read_station(station_id) -> dict:
    return get_success_data(api_client.get_station(station_id, ADMIN))


def read_advertiser(advertiser_id) -> dict:
    return get_success_data(api_client.get_advertiser(advertiser_id, ADMIN))


def read_election(election_id) -> dict:
    return get_success_data(api_client.get_election(election_id, ADMIN))


def read_election_version(election_id) -> int:
    return read_election(election_id)["version"]


def read_rate_class(rate_class_id) -> dict:
    return get_success_data(api_client.get_rate_class(rate_class_id, ADMIN))


def read_file_entry(entry_id) -> dict:
    return get_success_data(api_client.get_file_entry(entry_id, ADMIN))


def read_eo_request(request_id) -> dict:
    return get_success_data(api_client.get_eo_request(request_id, ADMIN))


def read_determination(determination_id) -> dict:
    return get_success_data(api_client.get_luc_determination(determination_id, ADMIN))


def read_complaint(complaint_id) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, ADMIN))


def read_rebate(rebate_id) -> dict:
    return get_success_data(api_client.get_rebate(rebate_id, ADMIN))


def list_file_entries(**params) -> list:
    body = api_client.list_file_entries(ADMIN, params=params).json()
    return body["data"]


def list_rebates(**params) -> list:
    body = api_client.list_rebates(ADMIN, params=params).json()
    return body["data"]


def list_determinations(**params) -> list:
    body = api_client.list_luc_determinations(ADMIN, params=params).json()
    return body["data"]


def post_file_entry(entry_id, public_file_url="https://publicfiles.example/entry") -> dict:
    return get_success_data(
        api_client.post_file_entry(
            entry_id, {"public_file_url": public_file_url}, OFFICER_ALPHA
        )
    )


def run_audit_sweep(station_id) -> dict:
    return get_success_data(api_client.audit_sweep(station_id, ADMIN))


def file_complaint(station_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_complaint(complaint_payload(station_id, **overrides), PUBLIC)
    )


def respond_to_complaint(
    complaint_id, response_text, remedy_code, officer_user_id=OFFICER_ALPHA_USER_ID
) -> dict:
    return get_success_data(
        api_client.respond_complaint(
            complaint_id,
            complaint_response_payload(response_text, remedy_code),
            make_officer_headers(officer_user_id),
        )
    )


def create_determination(
    election_id, rate_class_id, variant, expected_election_version=None,
    officer_user_id=OFFICER_BETA_USER_ID,
) -> dict:
    if expected_election_version is None:
        expected_election_version = read_election_version(election_id)
    return get_success_data(
        api_client.create_luc_determination(
            election_id,
            luc_determination_payload(rate_class_id, variant, expected_election_version),
            make_officer_headers(officer_user_id),
        )
    )


def file_eo_request(station_id, requesting_advertiser_id, trigger_order_id) -> dict:
    return get_success_data(
        api_client.create_eo_request(
            eo_request_payload(station_id, requesting_advertiser_id, trigger_order_id),
            make_advertiser_agent_headers(requesting_advertiser_id),
        )
    )


def grant_eo_request(request_id, granted_order_id, officer_user_id=OFFICER_BETA_USER_ID) -> dict:
    return get_success_data(
        api_client.respond_eo_request(
            request_id,
            {"decision": "GRANT", "granted_order_id": granted_order_id},
            make_officer_headers(officer_user_id),
        )
    )


def deny_eo_request(request_id, denial_reason, officer_user_id=OFFICER_BETA_USER_ID) -> dict:
    return get_success_data(
        api_client.respond_eo_request(
            request_id,
            {"decision": "DENY", "denial_reason": denial_reason},
            make_officer_headers(officer_user_id),
        )
    )


# ------------------------------------------------------ spot list helpers ---


def hourly_spots(count, air_date=None, prefix="EN", duration_seconds=30,
                 first_offset=0, step=3600):
    """A list of spot payload fragments an hour apart, so none of them collide."""
    air_date = air_date or D["AIR_DATE"]
    return [
        {
            "air_date": air_date,
            "start_offset_seconds": first_offset + index * step,
            "duration_seconds": duration_seconds,
            "program_code": f"{prefix}-{index + 1}",
        }
        for index in range(count)
    ]


def _add_spots(order_id, advertiser_id, spots):
    return [add_spot(order_id, advertiser_id, **spot) for spot in (spots or [])]


# ------------------------------------------- Tier 2/3: issue-buyer orders ---


def setup_issue_order(
    call_sign="WISS-TV",
    market_code="DMA-200",
    legal_name=None,
    station_overrides=None,
    rate_class_overrides=None,
    order_overrides=None,
    spots=None,
    classification="ISSUE",
    submit=False,
    accept=False,
    charge_amount_cents=None,
    clock=None,
):
    """Station + rate class + issue buyer + order, walked as far as asked.

    ``classification`` is ``"ISSUE"`` for a fully classified issue advertiser,
    ``"REVIEW"`` to stop at UNDER_REVIEW, or ``None`` to leave the buyer in
    SUBMITTED.  Set ``submit``/``accept``/``charge_amount_cents`` to drive the
    order further along its lifecycle.
    """
    legal_name = legal_name or D["ISSUE_LEGAL_NAME"]
    set_clock(clock)
    station = create_station(
        **_merged({"call_sign": call_sign, "market_code": market_code}, station_overrides)
    )
    rate_class = create_rate_class(station["id"], **(rate_class_overrides or {}))

    if classification == "ISSUE":
        advertiser = classify_issue_advertiser(station["id"], legal_name=legal_name)
    elif classification == "REVIEW":
        advertiser = intake_advertiser(station["id"], legal_name=legal_name)
        advertiser = open_review(advertiser["id"])
    else:
        advertiser = intake_advertiser(station["id"], legal_name=legal_name)

    order = create_order(
        station["id"],
        advertiser["id"],
        rate_class["id"],
        **_merged(
            {"sponsorship_disclosure_text": "PAID FOR BY " + legal_name},
            order_overrides,
        ),
    )
    created_spots = _add_spots(order["id"], advertiser["id"], spots)

    if submit or accept or charge_amount_cents is not None:
        order = submit_order(order["id"], advertiser["id"])
    if accept or charge_amount_cents is not None:
        order = accept_order(order["id"])
    if charge_amount_cents is not None:
        order = charge_order(order["id"], advertiser["id"], charge_amount_cents)

    return {
        "station": station,
        "rate_class": rate_class,
        "advertiser": advertiser,
        "order": order,
        "spots": created_spots,
    }


# ------------------------------------ Tier 2/3: legally qualified candidate --


def setup_candidate_order(
    call_sign="WCND-TV",
    market_code="DMA-201",
    legal_name="Rivera For Senate",
    candidate_name="Dana Rivera",
    qualification_evidence_ref="FEC-F2-2026-0088",
    station_overrides=None,
    election_overrides=None,
    rate_class_overrides=None,
    order_overrides=None,
    spots=None,
    classify=True,
    submit=False,
    accept=False,
    charge_amount_cents=None,
    clock=None,
    include_authorization=True,
):
    """Station + election + rate class + legally qualified candidate + order."""
    set_clock(clock)
    station = create_station(
        **_merged({"call_sign": call_sign, "market_code": market_code}, station_overrides)
    )
    election = create_election(station["id"], **(election_overrides or {}))
    rate_class = create_rate_class(station["id"], **(rate_class_overrides or {}))

    intake_kwargs = {
        "legal_name": legal_name,
        "candidate_name": candidate_name,
        "qualification_evidence_ref": qualification_evidence_ref,
    }
    if classify:
        advertiser = classify_candidate_advertiser(
            station["id"], election["id"], **intake_kwargs
        )
    else:
        advertiser = intake_candidate_advertiser(
            station["id"], election["id"], **intake_kwargs
        )

    disclosure = "PAID FOR BY " + legal_name
    if include_authorization:
        disclosure = disclosure + "; AUTHORIZED BY " + legal_name
    order = create_order(
        station["id"],
        advertiser["id"],
        rate_class["id"],
        **_merged(
            {
                "payment_terms": "NET_30",
                "sponsorship_disclosure_text": disclosure,
                "election_id": election["id"],
            },
            order_overrides,
        ),
    )
    created_spots = _add_spots(order["id"], advertiser["id"], spots)

    if submit or accept or charge_amount_cents is not None:
        order = submit_order(order["id"], advertiser["id"])
    if accept or charge_amount_cents is not None:
        order = accept_order(order["id"])
    if charge_amount_cents is not None:
        order = charge_order(order["id"], advertiser["id"], charge_amount_cents)

    return {
        "station": station,
        "election": election,
        "rate_class": rate_class,
        "advertiser": advertiser,
        "order": order,
        "spots": created_spots,
    }


# --------------------------- Tier 4: opposing candidates and the EO clock ---


def setup_two_candidate_orders(
    call_sign="WEQO-TV",
    market_code="DMA-355",
    eo_parity_basis="SPOT_COUNT",
    station_overrides=None,
    rate_class_overrides=None,
    election_overrides=None,
    trigger_spots=None,
    granted_spots=None,
    air_trigger=True,
    air_at="2026-08-10T12:00:00Z",
    build_granted_order=True,
    clock=None,
):
    """Two legally qualified candidates in one election, ready for parity work.

    The opponent's order is accepted and, unless ``air_trigger`` is false, its
    first spot is aired at ``air_at`` so the order reaches RUNNING and stamps
    ``first_air_at`` -- the instant the seven-day request window counts from.
    The requester's own order is accepted so a grant can attach to it.
    """
    set_clock(clock)
    station = create_station(
        **_merged(
            {
                "call_sign": call_sign,
                "market_code": market_code,
                "licensee_name": "Equal Time Broadcasting",
                "political_file_posting_deadline_hours": 24,
                "daily_political_seconds_cap": 300,
                "eo_parity_basis": eo_parity_basis,
            },
            station_overrides,
        )
    )
    election = create_election(
        station["id"],
        **_merged({"office_sought": "Governor", "election_type": "PRIMARY"}, election_overrides),
    )
    rate_class = create_rate_class(station["id"], **(rate_class_overrides or {}))

    opponent = classify_candidate_advertiser(
        station["id"],
        election["id"],
        legal_name="Okafor For Governor",
        candidate_name="Lena Okafor",
        office_sought="Governor",
        qualification_evidence_ref="FEC-F2-2026-0101",
    )
    requester = classify_candidate_advertiser(
        station["id"],
        election["id"],
        legal_name="Whitlock For Governor",
        candidate_name="Ray Whitlock",
        office_sought="Governor",
        qualification_evidence_ref="FEC-F2-2026-0102",
    )

    if trigger_spots is None:
        trigger_spots = [
            {
                "air_date": "2026-08-10",
                "start_offset_seconds": 0,
                "duration_seconds": 30,
                "program_code": "EN-T1",
            }
        ]
    trigger_order = create_order(
        station["id"],
        opponent["id"],
        rate_class["id"],
        payment_terms="NET_30",
        sponsorship_disclosure_text=(
            "PAID FOR BY Okafor For Governor; AUTHORIZED BY Okafor For Governor"
        ),
        election_id=election["id"],
    )
    trigger_spot_rows = _add_spots(trigger_order["id"], opponent["id"], trigger_spots)
    submit_order(trigger_order["id"], opponent["id"])
    trigger_order = accept_order(trigger_order["id"])

    if air_trigger:
        set_clock(air_at)
        air_spot(trigger_spot_rows[0]["id"])
        trigger_order = read_order(trigger_order["id"])

    granted_order = None
    granted_spot_rows = []
    if build_granted_order:
        if granted_spots is None:
            granted_spots = [
                {
                    "air_date": "2026-08-25",
                    "start_offset_seconds": 0,
                    "duration_seconds": 30,
                    "program_code": "EN-G1",
                }
            ]
        granted_order = create_order(
            station["id"],
            requester["id"],
            rate_class["id"],
            payment_terms="NET_30",
            sponsorship_disclosure_text=(
                "PAID FOR BY Whitlock For Governor; AUTHORIZED BY Whitlock For Governor"
            ),
            election_id=election["id"],
        )
        granted_spot_rows = _add_spots(granted_order["id"], requester["id"], granted_spots)
        submit_order(granted_order["id"], requester["id"])
        granted_order = accept_order(granted_order["id"])

    return {
        "station": station,
        "election": election,
        "rate_class": rate_class,
        "opponent": opponent,
        "requester": requester,
        "trigger_order": trigger_order,
        "trigger_spots": trigger_spot_rows,
        "granted_order": granted_order,
        "granted_spots": granted_spot_rows,
    }


# ------------------- Tier 4/5: overdue public file, frozen posture, sweep ---


def setup_station_with_two_overdue_adjustments(
    call_sign="WSWP-TV",
    market_code="DMA-604",
    advertiser_kind="CANDIDATE",
    sweep_clock="2026-08-08T09:00:00Z",
    run_sweep=False,
):
    """Drive a station to two unposted RATE_ADJUSTMENT entries past their deadline.

    A MORNING order of three thirty-second spots is accepted and settled at
    22221 cents; preempting two of them writes two rebates and files two
    RATE_ADJUSTMENT entries, while the ORDER_ACCEPTED entry is posted on time.
    The clock then moves past the two adjustment deadlines.  With ``run_sweep``
    the audit checkpoint is executed, leaving the station FROZEN with the order
    SUSPENDED.
    """
    rate_class_overrides = {
        "class_code": "RC-AM",
        "daypart": "MORNING",
        "preemptible": True,
        "preemption_priority": 3,
        "posted_rate_cents": D["POSTED_RATE_MORNING"],
    }
    station_overrides = {
        "licensee_name": "Sweep Broadcasting LLC",
        "political_file_posting_deadline_hours": 24,
        "daily_political_seconds_cap": 300,
    }
    spots = hourly_spots(3, prefix="AM")

    if advertiser_kind == "CANDIDATE":
        built = setup_candidate_order(
            call_sign=call_sign,
            market_code=market_code,
            station_overrides=station_overrides,
            rate_class_overrides=rate_class_overrides,
            spots=spots,
            charge_amount_cents=22221,
        )
    else:
        built = setup_issue_order(
            call_sign=call_sign,
            market_code=market_code,
            station_overrides=station_overrides,
            rate_class_overrides=rate_class_overrides,
            spots=spots,
            charge_amount_cents=22221,
        )

    order = built["order"]
    advertiser = built["advertiser"]
    station = built["station"]

    preempt_spot(built["spots"][0]["id"], "Breaking news override")
    preempt_spot(built["spots"][1]["id"], "Weather cut-in")

    accepted_entries = list_file_entries(
        order_id=order["id"], event_type="ORDER_ACCEPTED"
    )
    accepted_entry = post_file_entry(
        accepted_entries[0]["id"], "https://publicfiles.example/accept-1"
    )
    adjustment_entries = list_file_entries(
        order_id=order["id"], event_type="RATE_ADJUSTMENT"
    )

    set_clock(sweep_clock)
    swept_station = None
    if run_sweep:
        swept_station = run_audit_sweep(station["id"])

    built.update(
        {
            "order": read_order(order["id"], advertiser["id"]),
            "accepted_entry": accepted_entry,
            "adjustment_entries": adjustment_entries,
            "swept_station": swept_station,
        }
    )
    return built
