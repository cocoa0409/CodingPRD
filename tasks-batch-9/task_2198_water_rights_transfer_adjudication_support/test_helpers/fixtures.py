"""Composite setup helpers.

Every helper builds its preconditions from an empty database using only the
endpoints the PRD declares, and uses the lenient `get_success_data()` validator
so a broken precondition surfaces as a setup failure rather than as a confusing
assertion failure inside a test.

PRD §2.4: the logical clock is the sole time source, so every helper pins it
before doing anything else.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    condition_entry,
    create_adjudication_claim_payload,
    create_beneficial_use_record_payload,
    create_claimant_payload,
    create_decree_docket_payload,
    create_deposit_payload,
    create_hcu_study_payload,
    create_injury_analysis_payload,
    create_lease_assignment_payload,
    create_point_of_diversion_payload,
    create_protest_payload,
    create_transfer_application_payload,
    create_water_bank_account_payload,
    create_water_right_payload,
    decide_payload,
    resolve_protest_payload,
)
from .test_users import TEST_USERS, make_claimant_headers

CLOCK_BASE = TEST_DEFAULTS["CLOCK_BASE"]

ANALYST = TEST_USERS["analyst_headers"]
HEARING_OFFICER = TEST_USERS["hearing_officer_headers"]
DECIDER = TEST_USERS["decision_authority_headers"]
ADJUDICATOR = TEST_USERS["basin_adjudicator_headers"]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def set_clock(instant: str, headers: dict = ANALYST) -> dict:
    """PRD §2.4 — move the logical clock to `instant`."""
    return get_success_data(api_client.set_clock(instant, headers))


def create_claimant(legal_name: str = None, **overrides) -> dict:
    payload = create_claimant_payload(**overrides)
    if legal_name is not None:
        payload["legal_name"] = legal_name
    return get_success_data(api_client.create_claimant(payload, ANALYST))


def create_water_right(claimant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_water_right(
            create_water_right_payload(claimant_id, **overrides), ANALYST
        )
    )


def add_use_record(right_id: str, use_year: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_beneficial_use_record(
            right_id, create_beneficial_use_record_payload(use_year, **overrides), ANALYST
        )
    )


def add_point_of_diversion(right_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_point_of_diversion(
            right_id, create_point_of_diversion_payload(**overrides), ANALYST
        )
    )


def activate_right(right_id: str) -> dict:
    return get_success_data(api_client.activate_water_right(right_id, ANALYST))


def read_right(right_id: str) -> dict:
    return get_success_data(api_client.get_water_right(right_id, ANALYST))


def right_version(right_id: str) -> int:
    """PRD §2.7 — the caller must declare the `version` it last observed."""
    return read_right(right_id)["version"]


def read_account(account_id: str) -> dict:
    return get_success_data(api_client.get_water_bank_account(account_id, ANALYST))


def account_version(account_id: str) -> int:
    return read_account(account_id)["version"]


def read_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_transfer_application(application_id, ANALYST)
    )


def read_lease(lease_id: str) -> dict:
    return get_success_data(api_client.get_lease_assignment(lease_id, ANALYST))


def read_condition(condition_id: str) -> dict:
    return get_success_data(api_client.get_approval_condition(condition_id, ANALYST))


def read_claimant(claimant_id: str) -> dict:
    return get_success_data(api_client.get_claimant(claimant_id, ANALYST))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_adjudication_claim(claim_id, ADJUDICATOR))


def read_docket(docket_id: str) -> dict:
    return get_success_data(api_client.get_decree_docket(docket_id, ADJUDICATOR))


# ---------------------------------------------------------------------------
# Tier 1 — state progression on a water right
# ---------------------------------------------------------------------------
def setup_documented_right(clock: str = CLOCK_BASE, **right_overrides) -> dict:
    """Clock pinned, one claimant of record, one `UNADJUDICATED` right.

    Returns {"claimant": ..., "right": ...}.
    """
    set_clock(clock)
    claimant = create_claimant()
    right = create_water_right(claimant["id"], **right_overrides)
    return {"claimant": claimant, "right": right}


def setup_base_right(
    clock: str = CLOCK_BASE,
    use_years=(2023, 2024, 2025),
    reported_diversion_af: float = None,
    irrigated_acres: float = None,
    verification_source: str = "METER",
    activate: bool = True,
    pod_specs=(),
    **right_overrides,
) -> dict:
    """The perfected right every quantification scenario starts from.

    Claimant of record, a right at 400.00 AF / 120.00 acres / 5.000 CFS, one
    beneficial-use record per year in `use_years`, then activation
    (PRD §3.2 — metered evidence perfects the right and authorizes its
    headgates).

    Any `pod_specs` entries are registered *before* activation, so PRD §3.2
    carries them `PROPOSED -> AUTHORIZED` as part of perfecting the right.

    Returns {"claimant", "right", "records", "pods"}.
    """
    bundle = setup_documented_right(clock, **right_overrides)
    pods = [
        add_point_of_diversion(bundle["right"]["id"], **spec) for spec in pod_specs
    ]
    if reported_diversion_af is None:
        reported_diversion_af = TEST_DEFAULTS["REPORTED_DIVERSION_AF"]
    if irrigated_acres is None:
        irrigated_acres = TEST_DEFAULTS["IRRIGATED_ACRES"]
    records = []
    for year in use_years:
        records.append(
            add_use_record(
                bundle["right"]["id"],
                year,
                reported_diversion_af=reported_diversion_af,
                irrigated_acres=irrigated_acres,
                verification_source=verification_source,
            )
        )
    if activate:
        bundle["right"] = activate_right(bundle["right"]["id"])
        pods = [
            get_success_data(api_client.get_point_of_diversion(pod["id"], ANALYST))
            for pod in pods
        ]
    bundle["records"] = records
    bundle["pods"] = pods
    return bundle


def add_use_records_from_spec(right_id: str, spec) -> list:
    """Append one record per (use_year, reported_diversion_af, irrigated_acres,
    verification_source) tuple."""
    created = []
    for use_year, diverted, acres, source in spec:
        created.append(
            add_use_record(
                right_id,
                use_year,
                reported_diversion_af=diverted,
                irrigated_acres=acres,
                verification_source=source,
            )
        )
    return created


def create_study(right_id: str, start_year: int, end_year: int, method: str = "DIVERSION_BASED"):
    """PRD §3.3 — the quantification runs synchronously at creation."""
    return api_client.create_hcu_study(
        right_id,
        create_hcu_study_payload(start_year, end_year, method=method),
        ANALYST,
    )


def certify_study(study_id: str, right_id: str, headers: dict = ANALYST) -> dict:
    """PRD §2.7 — capture the right's `version` immediately before certifying."""
    observed = right_version(right_id)
    return get_success_data(
        api_client.certify_hcu_study(study_id, observed, headers)
    )


def setup_certified_right(
    clock: str = CLOCK_BASE,
    method: str = "DIVERSION_BASED",
    study_start_year: int = 2023,
    study_end_year: int = 2025,
    **kwargs,
) -> dict:
    """A right whose consumptive use has been quantified and certified.

    With the default records this certifies `transferable_cu_af` 195.00 onto the
    right, so `certified_hcu_af` and `transferable_af` both read 195.00.

    Returns {"claimant", "right", "records", "study"}.
    """
    bundle = setup_base_right(clock, **kwargs)
    study = get_success_data(
        create_study(bundle["right"]["id"], study_start_year, study_end_year, method)
    )
    certify_study(study["id"], bundle["right"]["id"])
    bundle["study"] = get_success_data(
        api_client.get_hcu_study(study["id"], ANALYST)
    )
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3 — the transfer application lifecycle
# ---------------------------------------------------------------------------
def draft_application(
    right_id: str, study_id: str, requested_af: float, **overrides
) -> dict:
    return get_success_data(
        api_client.create_transfer_application(
            create_transfer_application_payload(
                right_id, study_id, requested_af, **overrides
            ),
            ANALYST,
        )
    )


def submit_application(application_id: str, right_id: str, headers: dict = ANALYST) -> dict:
    """PRD §2.7 — read the right's `version` immediately before submitting."""
    observed = right_version(right_id)
    return get_success_data(
        api_client.submit_transfer_application(application_id, observed, headers)
    )


def resubmit_application(
    application_id: str, right_id: str, requested_af: float, headers: dict = ANALYST
) -> dict:
    observed = right_version(right_id)
    return get_success_data(
        api_client.resubmit_transfer_application(
            application_id, requested_af, observed, headers
        )
    )


def add_injury_analysis(
    application_id: str,
    method: str = "SEASONAL_AVERAGE",
    pod_move_miles: float = 0.00,
    headers: dict = ANALYST,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_injury_analysis(
            application_id,
            create_injury_analysis_payload(method, pod_move_miles, **overrides),
            headers,
        )
    )


def publish_application(application_id: str) -> dict:
    return get_success_data(
        api_client.publish_transfer_application(application_id, ANALYST)
    )


def setup_draft_application(
    requested_af: float = 100.00,
    clock: str = CLOCK_BASE,
    application_type: str = "CHANGE_OF_USE",
    **kwargs,
) -> dict:
    """Certified right plus one `DRAFT` application escrowing nothing.

    Returns {"claimant", "right", "records", "study", "application"}.
    """
    scope = {}
    if application_type in ("CHANGE_OF_USE", "COMBINED"):
        scope["proposed_purpose_of_use"] = "MUNICIPAL"
    if application_type in ("PLACE_OF_USE_CHANGE", "COMBINED"):
        scope["proposed_place_of_use_acres"] = 60.00
    application_scope = kwargs.pop("application_scope", None)
    if application_scope is not None:
        scope = application_scope
    bundle = setup_certified_right(clock, **kwargs)
    payload_overrides = dict(scope)
    payload_overrides["application_type"] = application_type
    if "proposed_purpose_of_use" not in payload_overrides:
        payload_overrides["proposed_purpose_of_use"] = None
    bundle["application"] = get_success_data(
        api_client.create_transfer_application(
            _scoped_application_payload(
                bundle["right"]["id"],
                bundle["study"]["id"],
                requested_af,
                payload_overrides,
            ),
            ANALYST,
        )
    )
    return bundle


def _scoped_application_payload(
    right_id: str, study_id: str, requested_af: float, overrides: dict
) -> dict:
    """PRD §3.4 — a scope field must be *absent*, not null, when its type does
    not call for it."""
    payload = create_transfer_application_payload(right_id, study_id, requested_af)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def setup_submitted_application(
    requested_af: float = 70.00, clock: str = CLOCK_BASE, **kwargs
) -> dict:
    """A `SUBMITTED` application with `requested_af` escrowed out of the right."""
    bundle = setup_draft_application(requested_af, clock, **kwargs)
    bundle["application"] = submit_application(
        bundle["application"]["id"], bundle["right"]["id"]
    )
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


def setup_published_application(
    requested_af: float = 60.00,
    clock: str = CLOCK_BASE,
    injury_method: str = "SEASONAL_AVERAGE",
    pod_move_miles: float = 0.00,
    analysis_overrides: dict = None,
    **kwargs,
) -> dict:
    """A `PROTEST_PERIOD` application with a `DRAFT` injury analysis on record.

    PRD §3.5 — `protest_deadline` is stamped thirty days out on a first
    publication.

    Returns {..., "application", "analysis"}.
    """
    bundle = setup_submitted_application(requested_af, clock, **kwargs)
    bundle["analysis"] = add_injury_analysis(
        bundle["application"]["id"],
        injury_method,
        pod_move_miles,
        **(analysis_overrides or {}),
    )
    bundle["application"] = publish_application(bundle["application"]["id"])
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


def setup_application_ready_for_decision(
    requested_af: float = 60.00,
    clock: str = CLOCK_BASE,
    deadline_reached_at: str = "2026-04-01T00:00:00Z",
    **kwargs,
) -> dict:
    """An unprotested application carried through to `READY_FOR_DECISION`.

    PRD §3.5 — closing the window requires the logical clock to have reached
    `protest_deadline`, so the clock is advanced to `deadline_reached_at` first.
    """
    bundle = setup_published_application(requested_af, clock, **kwargs)
    set_clock(deadline_reached_at)
    bundle["application"] = get_success_data(
        api_client.close_protest_period(bundle["application"]["id"], ANALYST)
    )
    bundle["analysis"] = get_success_data(
        api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
    )
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Protests (PRD §3.6)
# ---------------------------------------------------------------------------
def file_protest(
    application_id: str,
    protestant_claimant_id: str,
    claimed_injury_af: float,
    **overrides,
) -> dict:
    """PRD §2.1 — filing is ownership-gated, so the protestant's own id is used
    as `X-User-ID`."""
    return get_success_data(
        api_client.create_protest(
            create_protest_payload(
                application_id, protestant_claimant_id, claimed_injury_af, **overrides
            ),
            make_claimant_headers(protestant_claimant_id),
        )
    )


def route_protest(protest_id: str, track: str) -> dict:
    return get_success_data(
        api_client.route_protest(protest_id, track, HEARING_OFFICER)
    )


def setup_protested_application(
    requested_af: float = 60.00,
    claimed_injury_af: float = 12.00,
    clock: str = CLOCK_BASE,
    protest_filed_at: str = "2026-03-05T00:00:00Z",
    track: str = None,
    **kwargs,
) -> dict:
    """A published application carried to `UNDER_PROTEST` by one protest.

    A second claimant is registered as the protestant, because PRD §3.6 forbids
    a claimant protesting its own transfer.

    Returns {..., "protestant", "protest"}.
    """
    bundle = setup_published_application(requested_af, clock, **kwargs)
    protestant = create_claimant(legal_name="Rill Farms")
    set_clock(protest_filed_at)
    protest = file_protest(
        bundle["application"]["id"], protestant["id"], claimed_injury_af
    )
    if track is not None:
        protest = route_protest(protest["id"], track)
    bundle["protestant"] = protestant
    bundle["protest"] = protest
    bundle["application"] = read_application(bundle["application"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 5 — the disposition and the conditions it imposes (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------
def decide(application_id: str, disposition: str, headers: dict = DECIDER, **overrides) -> dict:
    return get_success_data(
        api_client.decide_transfer_application(
            application_id, decide_payload(disposition, **overrides), headers
        )
    )


def conditions_of(application_id: str) -> list:
    body = api_client.list_approval_conditions(application_id, ANALYST).json()
    return body["data"]


def setup_conditionally_approved_application(
    requested_af: float = 60.00,
    conditions=None,
    clock: str = CLOCK_BASE,
    **kwargs,
) -> dict:
    """An application approved with conditions, plus the condition rows created.

    PRD §3.7 — the summed `required_af` over `MITIGATION_PAYMENT` and
    `DRY_YEAR_FORBEARANCE` entries must reach the finalized `net_injury_af`, so
    the default condition set covers the default 60.00 AF request outright.

    Returns {..., "conditions": [...]}.
    """
    bundle = setup_application_ready_for_decision(requested_af, clock, **kwargs)
    if conditions is None:
        conditions = [
            condition_entry("MITIGATION_PAYMENT", bundle["analysis"]["net_injury_af"])
        ]
    bundle["application"] = decide(
        bundle["application"]["id"], "APPROVE_WITH_CONDITIONS", conditions=conditions
    )
    bundle["conditions"] = conditions_of(bundle["application"]["id"])
    bundle["right"] = read_right(bundle["right"]["id"])
    bundle["claimant"] = read_claimant(bundle["claimant"]["id"])
    return bundle


def setup_paid_condition(
    condition_type: str = "MEASUREMENT_DEVICE",
    required_af: float = 60.00,
    clock: str = CLOCK_BASE,
    compliance_due_date: str = None,
    **kwargs,
) -> dict:
    """One imposed condition whose fiscal dimension no longer blocks sign-off.

    PRD §3.8 — a `MEASUREMENT_DEVICE` condition is born `NOT_APPLICABLE` on the
    fiscal axis, so nothing needs paying; a `MITIGATION_PAYMENT` condition is
    paid here so the guard is cleared either way.

    Returns {..., "conditions", "condition"}.
    """
    entries = [
        condition_entry("MITIGATION_PAYMENT", required_af),
    ]
    if condition_type != "MITIGATION_PAYMENT":
        entries = [
            condition_entry("DRY_YEAR_FORBEARANCE", required_af),
            condition_entry(condition_type, 0.00, compliance_due_date),
        ]
    bundle = setup_conditionally_approved_application(
        max(required_af, 1.00), entries, clock, **kwargs
    )
    target = next(
        c for c in bundle["conditions"] if c["condition_type"] == condition_type
    )
    if target["payment_status"] == "OUTSTANDING":
        target = get_success_data(
            api_client.pay_approval_condition(
                target["id"], make_claimant_headers(bundle["claimant"]["id"])
            )
        )
    bundle["condition"] = target
    return bundle


def setup_violated_condition(
    clock: str = CLOCK_BASE, required_af: float = 60.00, **kwargs
) -> dict:
    """A condition driven to `VIOLATED`, which suspends the right behind it.

    PRD §3.8 — recording non-compliance is `WaterRightsAnalyst` field work.

    Returns {..., "condition"}.
    """
    bundle = setup_paid_condition(
        "MEASUREMENT_DEVICE", required_af, clock, **kwargs
    )
    bundle["condition"] = get_success_data(
        api_client.violate_approval_condition(
            bundle["condition"]["id"], "No device installed at the headgate.", ANALYST
        )
    )
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Water banking and delivery leases (PRD §3.9)
# ---------------------------------------------------------------------------
def open_account(claimant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_water_bank_account(
            create_water_bank_account_payload(claimant_id, **overrides), ANALYST
        )
    )


def deposit(account_id: str, right_id: str, deposit_af: float, headers: dict = ANALYST) -> dict:
    """PRD §2.7 — the account's `version` is read immediately before depositing."""
    observed = account_version(account_id)
    return get_success_data(
        api_client.create_deposit(
            account_id,
            create_deposit_payload(right_id, deposit_af, observed),
            headers,
        )
    )


def setup_bank_account(
    deposit_af: float = 90.00, clock: str = CLOCK_BASE, **kwargs
) -> dict:
    """A funded bank account on a certified, bank-enrolled right.

    PRD §3.9 — a deposit requires `bank_enrolled` to be set on the source right,
    so the right is documented with that flag from the outset.

    Returns {"claimant", "right", "records", "pods", "study", "account"}.
    """
    kwargs.setdefault("bank_enrolled", True)
    bundle = setup_certified_right(clock, **kwargs)
    account = open_account(bundle["claimant"]["id"])
    if deposit_af:
        deposit(account["id"], bundle["right"]["id"], deposit_af)
    bundle["account"] = read_account(account["id"])
    bundle["right"] = read_right(bundle["right"]["id"])
    return bundle


def setup_authorized_headgate_account(
    deposit_af: float = 90.00,
    clock: str = CLOCK_BASE,
    max_rate_cfs: float = 5.000,
    **kwargs,
) -> dict:
    """A funded account whose right carries one `AUTHORIZED` headgate.

    This is the precondition for every lease reservation, because PRD §3.9 takes
    no new lease at a `PROPOSED` headgate. PRD §3.2 authorizes the headgate as
    part of perfecting the right, so the headgate is registered before
    activation.

    Returns {..., "account", "pod"}.
    """
    pod_specs = kwargs.pop("pod_specs", None)
    if pod_specs is None:
        pod_specs = [{"max_rate_cfs": max_rate_cfs}]
    bundle = setup_bank_account(deposit_af, clock, pod_specs=pod_specs, **kwargs)
    bundle["pod"] = bundle["pods"][0]
    return bundle


def reserve_lease(
    account_id: str,
    right_id: str,
    pod_id: str,
    lease_start_date: str,
    lease_end_date: str,
    requested_af: float,
    headers: dict = ANALYST,
    **overrides,
):
    """Returns the raw response so gate-ordering tests can read the error id."""
    return api_client.create_lease_assignment(
        create_lease_assignment_payload(
            account_id,
            right_id,
            pod_id,
            lease_start_date,
            lease_end_date,
            requested_af,
            **overrides,
        ),
        headers,
    )


def setup_reserved_lease(
    requested_af: float = 20.00,
    lease_start_date: str = "2026-04-01T00:00:00Z",
    lease_end_date: str = "2026-07-30T00:00:00Z",
    clock: str = CLOCK_BASE,
    deposit_af: float = 90.00,
    **kwargs,
) -> dict:
    """A `RESERVED` lease with its credit committed but not yet delivered.

    Returns {..., "account", "pod", "lease"}.
    """
    lease_overrides = kwargs.pop("lease_overrides", {})
    bundle = setup_authorized_headgate_account(deposit_af, clock, **kwargs)
    bundle["lease"] = get_success_data(
        reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pod"]["id"],
            lease_start_date,
            lease_end_date,
            requested_af,
            **lease_overrides,
        )
    )
    bundle["account"] = read_account(bundle["account"]["id"])
    return bundle


def setup_active_lease(
    requested_af: float = 20.00,
    lease_start_date: str = "2026-04-01T00:00:00Z",
    lease_end_date: str = "2026-07-30T00:00:00Z",
    activated_at: str = "2026-04-02T00:00:00Z",
    clock: str = CLOCK_BASE,
    **kwargs,
) -> dict:
    """A lease under delivery.

    PRD §3.9 — activation needs the clock at or after `lease_start_date` and
    strictly before `lease_end_date`, so the clock is advanced to
    `activated_at` first.
    """
    bundle = setup_reserved_lease(
        requested_af, lease_start_date, lease_end_date, clock, **kwargs
    )
    set_clock(activated_at)
    bundle["lease"] = get_success_data(
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
    )
    bundle["account"] = read_account(bundle["account"]["id"])
    return bundle


def resolve_protest(protest_id: str, outcome: str = "STIPULATE", **overrides) -> dict:
    return get_success_data(
        api_client.resolve_protest(
            protest_id, resolve_protest_payload(outcome, **overrides), HEARING_OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Basin adjudication (PRD §3.10)
# ---------------------------------------------------------------------------
def open_docket(claim_filing_deadline: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_decree_docket(
            create_decree_docket_payload(claim_filing_deadline, **overrides),
            ADJUDICATOR,
        )
    )


def file_claim(
    docket_id: str,
    right_id: str,
    claimed_priority_date: str = None,
    claimed_af: float = 100.00,
    headers: dict = ADJUDICATOR,
    **overrides,
) -> dict:
    if claimed_priority_date is None:
        claimed_priority_date = TEST_DEFAULTS["PRIORITY_DATE"]
    return get_success_data(
        api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                docket_id, right_id, claimed_priority_date, claimed_af, **overrides
            ),
            headers,
        )
    )


def setup_docket_with_claim(
    clock: str = CLOCK_BASE,
    claim_filing_deadline: str = "2026-06-01T00:00:00Z",
    claimed_af: float = 100.00,
    claimed_priority_date: str = None,
    **kwargs,
) -> dict:
    """One `OPEN_FOR_CLAIMS` docket holding one `FILED`, `UNVERIFIED` claim.

    Returns {"claimant", "right", "records", "docket", "claim"}.
    """
    bundle = setup_base_right(clock, **kwargs)
    bundle["docket"] = open_docket(claim_filing_deadline)
    bundle["claim"] = file_claim(
        bundle["docket"]["id"],
        bundle["right"]["id"],
        claimed_priority_date,
        claimed_af,
    )
    bundle["docket"] = read_docket(bundle["docket"]["id"])
    return bundle


def setup_docket_in_examination(
    clock: str = CLOCK_BASE,
    claim_filing_deadline: str = "2026-06-01T00:00:00Z",
    deadline_reached_at: str = "2026-06-01T00:00:00Z",
    **kwargs,
) -> dict:
    """A docket advanced to `EXAMINATION` with its one claim still `FILED`.

    PRD §3.10 — the advance needs the clock to have reached
    `claim_filing_deadline` and the docket to hold at least one claim.
    """
    bundle = setup_docket_with_claim(clock, claim_filing_deadline, **kwargs)
    set_clock(deadline_reached_at)
    bundle["docket"] = get_success_data(
        api_client.advance_docket_phase(
            bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
        )
    )
    return bundle


def examine_claim(claim_id: str, examiner_recommended_af: float) -> dict:
    return get_success_data(
        api_client.examine_adjudication_claim(
            claim_id, examiner_recommended_af, "Field examination complete.", ADJUDICATOR
        )
    )


def verify_claim(claim_id: str, outcome: str = "FIELD_VERIFIED") -> dict:
    return get_success_data(
        api_client.verify_adjudication_claim(
            claim_id, outcome, "Headgate inspected on site.", ANALYST
        )
    )


def setup_docket_in_objection_period(
    clock: str = CLOCK_BASE,
    examiner_recommended_af: float = 90.00,
    verify: bool = True,
    **kwargs,
) -> dict:
    """A docket in `OBJECTION_PERIOD` whose single claim is `EXAMINED`.

    PRD §3.10 — advancing to `OBJECTION_PERIOD` requires every claim to have
    left `FILED`, so the claim is examined first; `verify` also carries the
    evidentiary axis to `FIELD_VERIFIED`, which is the decree gate.
    """
    bundle = setup_docket_in_examination(clock, **kwargs)
    bundle["claim"] = examine_claim(bundle["claim"]["id"], examiner_recommended_af)
    if verify:
        bundle["claim"] = verify_claim(bundle["claim"]["id"])
    bundle["docket"] = get_success_data(
        api_client.advance_docket_phase(
            bundle["docket"]["id"], "OBJECTION_PERIOD", ADJUDICATOR
        )
    )
    return bundle


# ---------------------------------------------------------------------------
# Forfeiture (PRD §3.2)
# ---------------------------------------------------------------------------
def setup_forfeiture_eligible_right(
    clock: str = CLOCK_BASE, nonuse_years: int = 7, **kwargs
) -> dict:
    """An activated right whose recent record is a run of non-use years.

    The right is perfected on metered evidence from 2016 onward and then carries
    `nonuse_years` consecutive years of de-minimis diversion at the end of the
    ten-year look-back, so PRD §3.2's five-year statutory threshold is met.

    Returns {"claimant", "right", "records"}.
    """
    used_years = [y for y in range(2016, 2026 - nonuse_years)]
    spec = [(y, 300.000, 100.00, "METER") for y in used_years]
    spec += [
        (y, 0.000, 0.00, "METER") for y in range(2026 - nonuse_years, 2026)
    ]
    bundle = setup_documented_right(clock, **kwargs)
    bundle["records"] = add_use_records_from_spec(bundle["right"]["id"], spec)
    bundle["right"] = activate_right(bundle["right"]["id"])
    return bundle
