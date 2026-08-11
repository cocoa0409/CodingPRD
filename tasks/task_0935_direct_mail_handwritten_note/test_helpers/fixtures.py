"""Composite setup helpers.

Every helper here drives the public API and nothing else: the harness restarts
the server before each test, so each fixture builds the whole world it needs
from an empty database using only declared endpoints.

Setup calls use ``get_success_data`` so a broken precondition reports as a
setup failure rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    DEFAULTS,
    SINGLE_RECORD_ROSTER,
    account_payload,
    campaign_payload,
    drip_schedule_payload,
    drip_step_payload,
    eddm_route_payload,
    handwriting_style_payload,
    ink_lot_payload,
    machine_payload,
    mail_job_payload,
    mailing_list_payload,
    postage_topup_payload,
    proof_payload,
    production_run_payload,
    template_payload,
)
from .test_users import (
    CAMPAIGN_MANAGER,
    LIST_OPERATOR,
    PLATFORM_ADMIN,
    PRODUCTION_OPERATOR,
    make_account_owner_headers,
)

SUBMITTER_USER_ID = "cm-1"


# --------------------------------------------------------------------------
# Tier 0: single-call primitives
# --------------------------------------------------------------------------
def set_clock(to_iso8601=CLOCK_DEFAULT_UTC):
    """Move the logical clock and return the resulting payload."""
    return get_success_data(api_client.set_clock(to_iso8601, PLATFORM_ADMIN))


def create_account(permit_number="PMT-100", **overrides):
    payload = account_payload(permit_number=permit_number, **overrides)
    return get_success_data(api_client.create_account(payload, PLATFORM_ADMIN))


def topup(account_id, amount_cents=DEFAULTS["SEED_ESCROW_CENTS"], reason="seed escrow"):
    payload = postage_topup_payload(amount_cents=amount_cents, reason=reason)
    return get_success_data(
        api_client.create_postage_topup(account_id, payload, PLATFORM_ADMIN)
    )


def create_handwriting_style(**overrides):
    payload = handwriting_style_payload(**overrides)
    return get_success_data(
        api_client.create_handwriting_style(payload, PRODUCTION_OPERATOR)
    )


def create_template(account_id, handwriting_style_id, **overrides):
    payload = template_payload(account_id, handwriting_style_id, **overrides)
    return get_success_data(api_client.create_template(payload, CAMPAIGN_MANAGER))


def create_campaign(account_id, **overrides):
    payload = campaign_payload(account_id, **overrides)
    return get_success_data(api_client.create_campaign(payload, CAMPAIGN_MANAGER))


def create_machine(machine_code="SLOT-BIG", **overrides):
    payload = machine_payload(machine_code=machine_code, **overrides)
    return get_success_data(api_client.create_machine(payload, PRODUCTION_OPERATOR))


def create_ink_lot(lot_code="LOT-A", **overrides):
    payload = ink_lot_payload(lot_code=lot_code, **overrides)
    return get_success_data(api_client.create_ink_lot(payload, PRODUCTION_OPERATOR))


def create_blackout_date(blackout_date, reason="carrier holiday"):
    payload = {"blackout_date": blackout_date, "reason": reason}
    return get_success_data(api_client.create_blackout_date(payload, CAMPAIGN_MANAGER))


def create_blackout_dates(dates, reason="carrier holiday"):
    return [create_blackout_date(one, reason) for one in dates]


def read_template(template_id):
    return get_success_data(api_client.get_template(template_id, CAMPAIGN_MANAGER))


def template_version(template_id):
    """The template's current optimistic-concurrency version."""
    return read_template(template_id)["version"]


def read_mail_job(mail_job_id):
    return get_success_data(api_client.get_mail_job(mail_job_id, CAMPAIGN_MANAGER))


def mail_job_version(mail_job_id):
    return read_mail_job(mail_job_id)["version"]


def read_campaign(campaign_id):
    return get_success_data(api_client.get_campaign(campaign_id, CAMPAIGN_MANAGER))


def read_ink_lot(ink_lot_id):
    return get_success_data(api_client.get_ink_lot(ink_lot_id, PRODUCTION_OPERATOR))


def read_machine(machine_id):
    return get_success_data(api_client.get_machine(machine_id, PRODUCTION_OPERATOR))


def read_account(account_id):
    return get_success_data(api_client.get_account(account_id, PLATFORM_ADMIN))


def read_list_record(list_record_id):
    return get_success_data(api_client.get_list_record(list_record_id, LIST_OPERATOR))


def list_record_version(list_record_id):
    return read_list_record(list_record_id)["version"]


def read_mailing_list(mailing_list_id):
    return get_success_data(api_client.get_mailing_list(mailing_list_id, LIST_OPERATOR))


def read_proof(proof_id):
    return get_success_data(api_client.get_proof(proof_id, CAMPAIGN_MANAGER))


def read_production_run(production_run_id):
    return get_success_data(
        api_client.get_production_run(production_run_id, PRODUCTION_OPERATOR)
    )


def read_drip_schedule(drip_schedule_id):
    return get_success_data(
        api_client.get_drip_schedule(drip_schedule_id, CAMPAIGN_MANAGER)
    )


def drip_schedule_version(drip_schedule_id):
    return read_drip_schedule(drip_schedule_id)["version"]


def read_drip_step(drip_step_id):
    return get_success_data(api_client.get_drip_step(drip_step_id, CAMPAIGN_MANAGER))


def read_reprint_request(reprint_request_id):
    return get_success_data(
        api_client.get_reprint_request(reprint_request_id, PRODUCTION_OPERATOR)
    )


def read_return_event(return_event_id):
    return get_success_data(api_client.get_return_event(return_event_id, LIST_OPERATOR))


def ledger_rows(account_id=None, campaign_id=None, mail_job_id=None, entry_type=None):
    params = {"limit": 100}
    if account_id:
        params["account_id"] = account_id
    if campaign_id:
        params["campaign_id"] = campaign_id
    if mail_job_id:
        params["mail_job_id"] = mail_job_id
    if entry_type:
        params["entry_type"] = entry_type
    response = api_client.list_postage_ledger_entries(PLATFORM_ADMIN, params=params)
    return response.json()["data"]


def production_runs_for(mail_job_id=None, machine_id=None, run_date=None):
    params = {"limit": 100}
    if mail_job_id:
        params["mail_job_id"] = mail_job_id
    if machine_id:
        params["machine_id"] = machine_id
    if run_date:
        params["run_date"] = run_date
    response = api_client.list_production_runs(PRODUCTION_OPERATOR, params=params)
    return response.json()["data"]


# --------------------------------------------------------------------------
# Tier 1: the recipient list pipeline
# --------------------------------------------------------------------------
def build_mailing_list(account_id, roster=SINGLE_RECORD_ROSTER, name="Spring List",
                       cass=True, dedupe_mode=None, lock=False):
    """Create a list, import ``roster`` and walk the import pipeline.

    Returns ``(mailing_list, records)`` where ``records`` are in import order.
    """
    mailing_list = get_success_data(
        api_client.create_mailing_list(mailing_list_payload(account_id, name=name),
                                       LIST_OPERATOR)
    )
    records = []
    for entry in roster:
        records.append(
            get_success_data(
                api_client.create_list_record(mailing_list["id"], dict(entry), LIST_OPERATOR)
            )
        )
    if cass:
        mailing_list = get_success_data(
            api_client.create_cass_run(mailing_list["id"], LIST_OPERATOR)
        )
    if dedupe_mode:
        mailing_list = get_success_data(
            api_client.create_dedupe_run(mailing_list["id"], {"mode": dedupe_mode},
                                         LIST_OPERATOR)
        )
    if lock:
        mailing_list = get_success_data(
            api_client.lock_mailing_list(mailing_list["id"], LIST_OPERATOR)
        )
    return mailing_list, records


def apply_ncoa_move(list_record_id, new_address_line1, **extra):
    payload = {"new_address_line1": new_address_line1}
    payload.update(extra)
    return get_success_data(
        api_client.create_ncoa_move(list_record_id, payload, LIST_OPERATOR)
    )


# --------------------------------------------------------------------------
# Tier 2: proof submission and approval
# --------------------------------------------------------------------------
def create_proof(mail_job_id, template_id):
    return get_success_data(
        api_client.create_proof(proof_payload(mail_job_id, template_id), CAMPAIGN_MANAGER)
    )


def submit_proof(proof_id, submitter_user_id=SUBMITTER_USER_ID):
    from .test_users import headers_for

    return get_success_data(
        api_client.submit_proof(proof_id, headers_for("CampaignManager", submitter_user_id))
    )


def approve_proof(proof_id, account_id, expected_template_version=None, template_id=None):
    """Approve as the AccountOwner, carrying the template's live version."""
    if expected_template_version is None:
        assert template_id, "supply either expected_template_version or template_id"
        expected_template_version = template_version(template_id)
    return get_success_data(
        api_client.approve_proof(
            proof_id,
            {"expected_template_version": expected_template_version},
            make_account_owner_headers(account_id),
        )
    )


def approve_job_proof(mail_job_id, template_id, account_id,
                      submitter_user_id=SUBMITTER_USER_ID):
    """Create, submit and approve one proof, driving the job DRAFT -> PROOFED."""
    proof = create_proof(mail_job_id, template_id)
    submit_proof(proof["id"], submitter_user_id)
    approve_proof(proof["id"], account_id, template_id=template_id)
    return read_proof(proof["id"])


# --------------------------------------------------------------------------
# Tier 3: the addressed job pipeline
# --------------------------------------------------------------------------
STAGES = ("draft", "proofed", "scheduled", "committed", "in_production", "mailed")


def build_addressed_scenario(
    permit_number="PMT-100",
    topup_cents=DEFAULTS["SEED_ESCROW_CENTS"],
    roster=SINGLE_RECORD_ROSTER,
    list_name="Spring List",
    cass=True,
    dedupe_mode="EXACT",
    lock=True,
    mail_class="MARKETING_MAIL",
    target_in_home_date="2026-06-15",
    schedule_target=None,
    stage="committed",
    character_count=DEFAULTS["TEMPLATE_CHARACTER_COUNT"],
    style_overrides=None,
    with_plant=False,
    machine_code="SLOT-BIG",
    machine_capacity_minutes=DEFAULTS["MACHINE_CAPACITY_MINUTES"],
    machine_status=None,
    lot_code="LOT-A",
    lot_ink_type="INK_BLUE_A",
    lot_volume_ul=DEFAULTS["INK_LOT_VOLUME_UL"],
    run_date="2026-06-05",
    run_piece_count=1,
    run_capacity_variant="SINGLE_PASS",
    clock=CLOCK_DEFAULT_UTC,
):
    """Build an ADDRESSED job and walk it to ``stage``.

    Returns a bundle keyed by ``account``, ``style``, ``template``, ``campaign``,
    ``mailing_list``, ``records``, ``job`` and -- where the stage or the flags
    call for them -- ``proof``, ``machine``, ``ink_lot`` and ``run``.
    """
    assert stage in STAGES, f"unknown stage {stage!r}"
    set_clock(clock)

    account = create_account(permit_number=permit_number)
    if topup_cents:
        account = topup(account["id"], topup_cents)

    style = create_handwriting_style(**(style_overrides or {}))
    template = create_template(account["id"], style["id"], character_count=character_count)
    campaign = create_campaign(account["id"])

    mailing_list, records = build_mailing_list(
        account["id"], roster=roster, name=list_name,
        cass=cass, dedupe_mode=dedupe_mode, lock=lock,
    )

    job_extra = {"mailing_list_id": mailing_list["id"], "mail_class": mail_class}
    if target_in_home_date is not None:
        job_extra["target_in_home_date"] = target_in_home_date
    job = get_success_data(
        api_client.create_mail_job(
            mail_job_payload(campaign["id"], template["id"], **job_extra), CAMPAIGN_MANAGER
        )
    )

    bundle = {
        "account": account,
        "style": style,
        "template": template,
        "campaign": campaign,
        "mailing_list": mailing_list,
        "records": records,
        "job": job,
    }

    machine = ink_lot = None
    needs_plant = with_plant or stage in ("in_production", "mailed")
    if needs_plant:
        machine_extra = {"daily_capacity_minutes": machine_capacity_minutes}
        if machine_status is not None:
            machine_extra["status"] = machine_status
        machine = create_machine(machine_code, **machine_extra)
        ink_lot = create_ink_lot(lot_code, ink_type=lot_ink_type,
                                 initial_volume_ul=lot_volume_ul)
        bundle["machine"] = machine
        bundle["ink_lot"] = ink_lot

    if stage == "draft":
        return bundle

    bundle["proof"] = approve_job_proof(job["id"], template["id"], account["id"])
    bundle["job"] = read_mail_job(job["id"])
    if stage == "proofed":
        return bundle

    schedule_body = {}
    anchor = schedule_target if schedule_target is not None else target_in_home_date
    if anchor is not None:
        schedule_body["target_in_home_date"] = anchor
    bundle["job"] = get_success_data(
        api_client.schedule_mail_job(job["id"], schedule_body, CAMPAIGN_MANAGER)
    )
    if stage == "scheduled":
        return bundle

    bundle["job"] = get_success_data(
        api_client.commit_mail_job(job["id"], CAMPAIGN_MANAGER)
    )
    if stage == "committed":
        return bundle

    run = get_success_data(
        api_client.create_production_run(
            job["id"],
            production_run_payload(
                machine["id"], ink_lot["id"], bundle["job"]["version"],
                run_date=run_date, piece_count=run_piece_count,
                capacity_variant=run_capacity_variant,
            ),
            PRODUCTION_OPERATOR,
        )
    )
    bundle["run"] = get_success_data(
        api_client.start_production_run(run["id"], PRODUCTION_OPERATOR)
    )
    bundle["job"] = read_mail_job(job["id"])
    if stage == "in_production":
        return bundle

    bundle["run"] = get_success_data(
        api_client.complete_production_run(run["id"], PRODUCTION_OPERATOR)
    )
    bundle["job"] = get_success_data(
        api_client.mail_mail_job(job["id"], PRODUCTION_OPERATOR)
    )
    return bundle


# --------------------------------------------------------------------------
# Tier 4: the EDDM saturation pipeline
# --------------------------------------------------------------------------
SATURATION_ROUTES_FIVE_PIECES = [
    {"route_code": "C001", "total_deliveries": 3,
     "residential_piece_count": 2, "business_piece_count": 1},
    {"route_code": "C002", "total_deliveries": 2,
     "residential_piece_count": 2, "business_piece_count": 0},
]
SATURATION_ROUTES_FOUR_PIECES = [
    {"route_code": "C003", "total_deliveries": 4,
     "residential_piece_count": 3, "business_piece_count": 1},
]
FULLY_COVERED_TWELVE_PIECE_ROUTES = [
    {"route_code": "C001", "total_deliveries": 6,
     "residential_piece_count": 4, "business_piece_count": 2},
    {"route_code": "C002", "total_deliveries": 6,
     "residential_piece_count": 4, "business_piece_count": 2},
]


def add_eddm_route(mail_job_id, **overrides):
    return get_success_data(
        api_client.create_eddm_route(mail_job_id, eddm_route_payload(**overrides),
                                     CAMPAIGN_MANAGER)
    )


def build_eddm_scenario(
    permit_number="PMT-100",
    topup_cents=DEFAULTS["SEED_ESCROW_CENTS"],
    routes=None,
    eddm_rate_variant="SATURATION",
    target_in_home_date="2026-06-15",
    stage="committed",
    with_plant=False,
    template_name="EDDM Card",
    campaign_name="Neighbourhood 2026",
    activate_campaign=False,
    clock=CLOCK_DEFAULT_UTC,
):
    """Build an EDDM job and walk it to ``stage``.

    Valid stages are ``draft``, ``proofed``, ``scheduled``, ``committed`` and
    ``mailed``: an EDDM job never enters production, so it moves from
    ``COMMITTED`` straight to ``MAILED``.
    """
    set_clock(clock)
    account = create_account(permit_number=permit_number)
    if topup_cents:
        account = topup(account["id"], topup_cents)
    style = create_handwriting_style()
    template = create_template(account["id"], style["id"], name=template_name,
                               body_text="Local neighbours")
    campaign = create_campaign(account["id"], name=campaign_name)
    if activate_campaign:
        campaign = get_success_data(
            api_client.activate_campaign(campaign["id"], CAMPAIGN_MANAGER)
        )

    job_extra = {
        "job_kind": "EDDM",
        "mail_class": "EDDM",
        "eddm_rate_variant": eddm_rate_variant,
    }
    if target_in_home_date is not None:
        job_extra["target_in_home_date"] = target_in_home_date
    job = get_success_data(
        api_client.create_mail_job(
            mail_job_payload(campaign["id"], template["id"], **job_extra), CAMPAIGN_MANAGER
        )
    )

    route_rows = []
    for route in (routes if routes is not None else SATURATION_ROUTES_FIVE_PIECES):
        route_rows.append(add_eddm_route(job["id"], **route))

    bundle = {
        "account": account,
        "style": style,
        "template": template,
        "campaign": campaign,
        "job": read_mail_job(job["id"]),
        "routes": route_rows,
    }
    if with_plant:
        bundle["machine"] = create_machine("SLOT-BIG")
        bundle["ink_lot"] = create_ink_lot("LOT-A")

    if stage == "draft":
        return bundle

    bundle["proof"] = approve_job_proof(job["id"], template["id"], account["id"])
    bundle["job"] = read_mail_job(job["id"])
    if stage == "proofed":
        return bundle

    schedule_body = {}
    if target_in_home_date is not None:
        schedule_body["target_in_home_date"] = target_in_home_date
    bundle["job"] = get_success_data(
        api_client.schedule_mail_job(job["id"], schedule_body, CAMPAIGN_MANAGER)
    )
    if stage == "scheduled":
        return bundle

    bundle["job"] = get_success_data(
        api_client.commit_mail_job(job["id"], CAMPAIGN_MANAGER)
    )
    if stage == "committed":
        return bundle

    bundle["job"] = get_success_data(
        api_client.mail_mail_job(job["id"], PRODUCTION_OPERATOR)
    )
    return bundle


# --------------------------------------------------------------------------
# Tier 5: drip schedules
# --------------------------------------------------------------------------
def build_drip_scenario(
    permit_number="PMT-161",
    job_count=1,
    anchor_variant="ANCHOR_IN_HOME",
    schedule_name="Spring Drip",
    approve_jobs=False,
    clock=CLOCK_DEFAULT_UTC,
):
    """One campaign, ``job_count`` DRAFT ADDRESSED jobs and one drip schedule.

    The jobs deliberately carry no ``target_in_home_date`` because a drip step
    supplies its own anchor date.  With ``approve_jobs`` the jobs are driven to
    ``PROOFED`` so that new steps land straight in ``SCHEDULED``.
    """
    set_clock(clock)
    account = create_account(permit_number=permit_number)
    style = create_handwriting_style()
    template = create_template(account["id"], style["id"])
    campaign = create_campaign(account["id"])
    mailing_list, records = build_mailing_list(
        account["id"], name="Mini List", cass=True, dedupe_mode=None, lock=False
    )

    jobs = []
    for _ in range(job_count):
        job = get_success_data(
            api_client.create_mail_job(
                mail_job_payload(campaign["id"], template["id"],
                                 mailing_list_id=mailing_list["id"]),
                CAMPAIGN_MANAGER,
            )
        )
        if approve_jobs:
            approve_job_proof(job["id"], template["id"], account["id"])
            job = read_mail_job(job["id"])
        jobs.append(job)

    schedule = get_success_data(
        api_client.create_drip_schedule(
            drip_schedule_payload(campaign["id"], name=schedule_name,
                                  anchor_variant=anchor_variant),
            CAMPAIGN_MANAGER,
        )
    )
    return {
        "account": account,
        "style": style,
        "template": template,
        "campaign": campaign,
        "mailing_list": mailing_list,
        "records": records,
        "jobs": jobs,
        "schedule": schedule,
    }


def add_drip_step(schedule_id, mail_job_id, sequence_no, anchor_date,
                  expected_drip_schedule_version=None):
    """Add one step, reading the schedule's live version unless one is given."""
    if expected_drip_schedule_version is None:
        expected_drip_schedule_version = drip_schedule_version(schedule_id)
    return api_client.create_drip_step(
        schedule_id,
        drip_step_payload(mail_job_id, sequence_no, anchor_date,
                          expected_drip_schedule_version),
        CAMPAIGN_MANAGER,
    )


def add_drip_step_ok(schedule_id, mail_job_id, sequence_no, anchor_date,
                     expected_drip_schedule_version=None):
    return get_success_data(
        add_drip_step(schedule_id, mail_job_id, sequence_no, anchor_date,
                      expected_drip_schedule_version)
    )


# --------------------------------------------------------------------------
# Tier 6: returns and reprints
# --------------------------------------------------------------------------
def record_return(list_record_id, return_reason="VACANT"):
    return get_success_data(
        api_client.create_return(list_record_id, {"return_reason": return_reason},
                                 LIST_OPERATOR)
    )


def request_reprint(list_record_id, return_event_id, campaign_id,
                    expected_list_record_version=None):
    if expected_list_record_version is None:
        expected_list_record_version = list_record_version(list_record_id)
    return api_client.create_reprint_request(
        {
            "list_record_id": list_record_id,
            "return_event_id": return_event_id,
            "campaign_id": campaign_id,
            "expected_list_record_version": expected_list_record_version,
        },
        LIST_OPERATOR,
    )


def request_reprint_ok(list_record_id, return_event_id, campaign_id,
                       expected_list_record_version=None):
    return get_success_data(
        request_reprint(list_record_id, return_event_id, campaign_id,
                        expected_list_record_version)
    )


def build_returned_record_scenario(
    permit_number="PMT-152",
    move_applied=False,
    mail_class="MARKETING_MAIL",
    return_reason="VACANT",
):
    """Mail one addressed piece and record its return.

    With ``move_applied`` an NCOA move is applied before standardization, so the
    record carries ``MOVE_APPLIED`` and the return earns the reprint
    entitlement; without it the record stays at ``NONE`` and the return earns
    the refund settlement.
    """
    set_clock()
    account = create_account(permit_number=permit_number)
    account = topup(account["id"])
    style = create_handwriting_style()
    machine = create_machine("SLOT-BIG")
    ink_lot = create_ink_lot("LOT-A")
    template = create_template(account["id"], style["id"])
    campaign = create_campaign(account["id"])

    mailing_list = get_success_data(
        api_client.create_mailing_list(
            mailing_list_payload(account["id"], name="Mini List"), LIST_OPERATOR
        )
    )
    from .factories import BOB_JONES

    record = get_success_data(
        api_client.create_list_record(mailing_list["id"], dict(BOB_JONES), LIST_OPERATOR)
    )
    if move_applied:
        apply_ncoa_move(record["id"], "250 Oak Ave", new_city="Chicago",
                        new_state_code="IL", new_zip5="60602",
                        new_dpv_confirmation_code="Y")
    get_success_data(api_client.create_cass_run(mailing_list["id"], LIST_OPERATOR))
    get_success_data(
        api_client.create_dedupe_run(mailing_list["id"], {"mode": "EXACT"}, LIST_OPERATOR)
    )
    mailing_list = get_success_data(
        api_client.lock_mailing_list(mailing_list["id"], LIST_OPERATOR)
    )

    job = get_success_data(
        api_client.create_mail_job(
            mail_job_payload(campaign["id"], template["id"],
                             mailing_list_id=mailing_list["id"],
                             mail_class=mail_class,
                             target_in_home_date="2026-06-15"),
            CAMPAIGN_MANAGER,
        )
    )
    proof = approve_job_proof(job["id"], template["id"], account["id"])
    get_success_data(
        api_client.schedule_mail_job(job["id"], {"target_in_home_date": "2026-06-15"},
                                     CAMPAIGN_MANAGER)
    )
    job = get_success_data(api_client.commit_mail_job(job["id"], CAMPAIGN_MANAGER))
    run = get_success_data(
        api_client.create_production_run(
            job["id"],
            production_run_payload(machine["id"], ink_lot["id"], job["version"]),
            PRODUCTION_OPERATOR,
        )
    )
    get_success_data(api_client.start_production_run(run["id"], PRODUCTION_OPERATOR))
    get_success_data(api_client.complete_production_run(run["id"], PRODUCTION_OPERATOR))
    job = get_success_data(api_client.mail_mail_job(job["id"], PRODUCTION_OPERATOR))

    return_event = record_return(record["id"], return_reason)
    return {
        "account": account,
        "style": style,
        "machine": machine,
        "ink_lot": ink_lot,
        "template": template,
        "campaign": campaign,
        "mailing_list": mailing_list,
        "record": read_list_record(record["id"]),
        "job": read_mail_job(job["id"]),
        "proof": proof,
        "run": read_production_run(run["id"]),
        "return_event": return_event,
    }
