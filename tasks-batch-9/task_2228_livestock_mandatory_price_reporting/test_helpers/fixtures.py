"""Composable setup builders.

Every builder drives the public API only -- there is no back door into the
store -- and each returns the resources a test needs to assert against.  The
database is empty at the start of every test, so a builder never assumes any
prior state beyond what it creates itself.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants as k
from . import factories as f
from . import test_users as u
from .types import (
    BasisVariant,
    EntityType,
    ReportClass,
    ReviewDecision,
    Species,
    ViolationType,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(client, current_utc):
    """Move the logical clock, as a ProgramAdmin."""
    return get_success_data(client.set_clock(current_utc, u.PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single resources
# ---------------------------------------------------------------------------


def create_entity(client, legal_name="Alpha Packing Company", **overrides):
    return get_success_data(
        client.create_reporting_entity(
            f.reporting_entity_payload(legal_name=legal_name, **overrides),
            u.PROGRAM_ADMIN,
        )
    )


def create_plant(client, reporting_entity_id, **overrides):
    return get_success_data(
        client.create_plant(
            f.plant_payload(reporting_entity_id, **overrides), u.PROGRAM_ADMIN
        )
    )


def create_window(client, **overrides):
    return get_success_data(
        client.create_reporting_window(
            f.reporting_window_payload(**overrides), u.PROGRAM_ADMIN
        )
    )


def create_standard_window(client, **overrides):
    """An OPEN weekly CATTLE LIVE_ANIMAL window with explicit guidelines.

    Three reporters, a 70.00 percent share ceiling and a 1,000-head volume
    floor, which 1,250 head across three reporters clears on all three.
    """
    standard = {
        "min_reporter_count": 3,
        "max_single_reporter_share_pct": 70.00,
        "min_reported_head": 1000,
    }
    standard.update(overrides)
    return create_window(client, **standard)


def create_relaxed_window(client, **overrides):
    """An OPEN window whose guidelines a single reporter can clear."""
    return get_success_data(
        client.create_reporting_window(
            f.relaxed_guideline_window_payload(**overrides), u.PROGRAM_ADMIN
        )
    )


def read_window(client, window_id):
    return get_success_data(client.get_reporting_window(window_id, u.PROGRAM_ADMIN))


def window_version(client, window_id):
    """The window's current version, for the mandatory expected_window_version."""
    return read_window(client, window_id)["version"]


def read_entity(client, entity_id):
    return get_success_data(client.get_reporting_entity(entity_id, u.PROGRAM_ADMIN))


def entity_version(client, entity_id):
    """The firm's current version, for expected_reporting_entity_version."""
    return read_entity(client, entity_id)["version"]


def read_plant(client, plant_id):
    return get_success_data(client.get_plant(plant_id, u.PROGRAM_ADMIN))


def read_registration(client, registration_id):
    return get_success_data(client.get_registration(registration_id, u.PROGRAM_ADMIN))


def read_submission(client, submission_id):
    return get_success_data(client.get_submission(submission_id, u.PROGRAM_ADMIN))


def read_report(client, report_id):
    return get_success_data(client.get_market_report(report_id, u.MARKET_ANALYST))


def read_case(client, case_id):
    return get_success_data(client.get_audit_case(case_id, u.COMPLIANCE_AUDITOR))


def read_penalty(client, assessment_id):
    return get_success_data(client.get_penalty_assessment(assessment_id, u.PENALTY_OFFICER))


def read_methodology_change(client, change_id):
    return get_success_data(client.get_methodology_change(change_id, u.PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: registration state progression
# ---------------------------------------------------------------------------


def draft_registration(client, reporting_entity_id, **overrides):
    return get_success_data(
        client.create_registration(
            f.registration_payload(reporting_entity_id, **overrides), u.PROGRAM_ADMIN
        )
    )


def determined_registration(client, reporting_entity_id, **overrides):
    """DRAFT then DETERMINED."""
    registration = draft_registration(client, reporting_entity_id, **overrides)
    return get_success_data(
        client.determine_registration(registration["id"], u.PROGRAM_ADMIN)
    )


def active_registration(client, reporting_entity_id, **overrides):
    """DRAFT then DETERMINED then ACTIVE."""
    registration = determined_registration(client, reporting_entity_id, **overrides)
    return get_success_data(
        client.activate_registration(registration["id"], u.PROGRAM_ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 3: entity hierarchy -- firm with a plant under an active obligation
# ---------------------------------------------------------------------------


DEFAULT_PLANT_OVERRIDES = {
    "boxed_beef_volume_lbs_prior_year": 2500000,
    "forward_commitment_cap_head": 3000,
}


def firm_with_plants(
    client,
    plant_specs,
    legal_name="Alpha Packing Company",
    entity_type=None,
    species_scope=Species.CATTLE.value,
    activate=True,
    determination_year=2026,
    basis_variant=None,
):
    """A firm with one plant per spec and, by default, an ACTIVE registration.

    Each spec is a dict of plant payload overrides; `plant_code` and the
    slaughter history default to the shared literals when a spec omits them.
    """
    entity_kwargs = {"legal_name": legal_name, "species_scope": species_scope}
    if entity_type is not None:
        entity_kwargs["entity_type"] = entity_type
    entity = create_entity(client, **entity_kwargs)

    plants = []
    for spec in plant_specs:
        overrides = dict(DEFAULT_PLANT_OVERRIDES)
        overrides.update(spec)
        plants.append(create_plant(client, entity["id"], **overrides))

    registration_kwargs = {"determination_year": determination_year}
    if basis_variant is not None:
        registration_kwargs["basis_variant"] = basis_variant
    registration = (
        active_registration(client, entity["id"], **registration_kwargs)
        if activate
        else determined_registration(client, entity["id"], **registration_kwargs)
    )
    return {"entity": entity, "plants": plants, "registration": registration}


def obligated_firm(
    client,
    legal_name="Alpha Packing Company",
    plant_code="EST-101",
    species=Species.CATTLE.value,
    species_scope=Species.CATTLE.value,
    annual_head_history=None,
    plant_overrides=None,
    entity_type=None,
    activate=True,
    determination_year=2026,
    basis_variant=None,
):
    """A firm with one plant and an ACTIVE MANDATORY registration for 2026."""
    spec = {"plant_code": plant_code, "species": species}
    if annual_head_history is not None:
        spec["annual_head_history"] = annual_head_history
    spec.update(plant_overrides or {})
    built = firm_with_plants(
        client,
        [spec],
        legal_name=legal_name,
        entity_type=entity_type,
        species_scope=species_scope,
        activate=activate,
        determination_year=determination_year,
        basis_variant=basis_variant,
    )
    return {
        "entity": built["entity"],
        "plant": built["plants"][0],
        "registration": built["registration"],
    }


# ---------------------------------------------------------------------------
# Tier 3: filing state progression
# ---------------------------------------------------------------------------


def draft_filing(client, entity_id, plant_id, window_id, **overrides):
    """A DRAFT filing, created with a freshly read expected_window_version."""
    payload = f.submission_payload(
        plant_id, window_id, window_version(client, window_id), **overrides
    )
    return get_success_data(client.create_submission(payload, u.reporter_agent(entity_id)))


def add_transaction(client, entity_id, submission_id, payload=None, **overrides):
    return get_success_data(
        client.add_transaction(
            submission_id,
            payload if payload is not None else f.transaction_payload(**overrides),
            u.reporter_agent(entity_id),
        )
    )


def add_wholesale_lot(client, entity_id, submission_id, payload=None, **overrides):
    return get_success_data(
        client.add_wholesale_lot(
            submission_id,
            payload if payload is not None else f.wholesale_lot_payload(**overrides),
            u.reporter_agent(entity_id),
        )
    )


def submitted_filing(client, entity_id, plant_id, window_id, lines=None, **overrides):
    """A SUBMITTED filing carrying the given transaction lines."""
    submission = draft_filing(client, entity_id, plant_id, window_id, **overrides)
    for line in lines if lines is not None else [f.transaction_payload()]:
        add_transaction(client, entity_id, submission["id"], line)
    return get_success_data(
        client.submit_submission(submission["id"], u.reporter_agent(entity_id))
    )


def accept_filing(client, submission_id, review_note=None):
    """Review with a decision of ACCEPT, as a MarketAnalyst."""
    payload = (
        f.review_payload(review_note=review_note)
        if review_note is not None
        else f.review_payload()
    )
    return get_success_data(
        client.review_submission(submission_id, payload, u.MARKET_ANALYST)
    )


def reject_filing(client, submission_id, review_note="Figures inconsistent."):
    return get_success_data(
        client.review_submission(
            submission_id,
            f.review_payload(decision=ReviewDecision.REJECT.value, review_note=review_note),
            u.MARKET_ANALYST,
        )
    )


def accepted_filing(client, entity_id, plant_id, window_id, lines=None, **overrides):
    """A filing carried all the way to ACCEPTED, so its head is in the ledger."""
    submission = submitted_filing(
        client, entity_id, plant_id, window_id, lines=lines, **overrides
    )
    return accept_filing(client, submission["id"])


def reopen_filing(client, submission_id, correction_reason=None):
    """ACCEPTED to UNDER_CORRECTION, as a ComplianceAuditor."""
    payload = (
        f.correction_payload(correction_reason=correction_reason)
        if correction_reason is not None
        else f.correction_payload()
    )
    return get_success_data(
        client.open_correction(submission_id, payload, u.COMPLIANCE_AUDITOR)
    )


def resubmit_filing(client, entity_id, submission_id):
    return get_success_data(
        client.resubmit_submission(submission_id, u.reporter_agent(entity_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: window lifecycle shortcuts
# ---------------------------------------------------------------------------


def lock_window(client, window_id, at=k.WINDOW_PERIOD_END):
    """Advance the clock to the period end, then lock the window."""
    set_clock(client, at)
    return get_success_data(client.lock_reporting_window(window_id, u.PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: market report lifecycle shortcuts
# ---------------------------------------------------------------------------


def create_report(client, window_id, **overrides):
    return get_success_data(
        client.create_market_report(
            f.market_report_payload(window_id, **overrides), u.MARKET_ANALYST
        )
    )


def computed_report(client, window_id, **overrides):
    """A market report whose aggregation_state is COMPUTED."""
    report = create_report(client, window_id, **overrides)
    return get_success_data(
        client.compute_market_report(report["id"], u.MARKET_ANALYST)
    )


def reviewed_report(client, window_id, **overrides):
    """A computed report that has been through the confidentiality review."""
    report = computed_report(client, window_id, **overrides)
    return get_success_data(
        client.disclosure_review_market_report(report["id"], u.MARKET_ANALYST)
    )


def published_report(client, window_id, release_at=k.WINDOW_PUBLICATION_RELEASE, **overrides):
    """A report taken through compute, disclosure review, window lock and release."""
    report = reviewed_report(client, window_id, **overrides)
    lock_window(client, window_id)
    set_clock(client, release_at)
    return get_success_data(client.publish_market_report(report["id"], u.MARKET_ANALYST))


# ---------------------------------------------------------------------------
# Tier 4: audit case lifecycle shortcuts
# ---------------------------------------------------------------------------


def fieldwork_case(client, submission_id, opener=None, **overrides):
    """An audit case advanced to FIELDWORK, opened by auditor-1 by default."""
    headers = opener if opener is not None else u.COMPLIANCE_AUDITOR
    case = get_success_data(
        client.create_audit_case(f.audit_case_payload(submission_id, **overrides), headers)
    )
    return get_success_data(client.start_fieldwork(case["id"], headers))


def finalize_case(client, case_id, verified_head, verified_value_dollars, finalizer=None):
    """Finalize under a second identity, as segregation of duties requires."""
    return get_success_data(
        client.finalize_audit_case(
            case_id,
            f.finalize_audit_payload(verified_head, verified_value_dollars),
            finalizer if finalizer is not None else u.COMPLIANCE_AUDITOR_2,
        )
    )


def discrepant_case(client, submission_id, verified_head, verified_value_dollars, **overrides):
    """A case finalized on a material finding, so it sits in DISCREPANCY."""
    case = fieldwork_case(client, submission_id, **overrides)
    return finalize_case(client, case["id"], verified_head, verified_value_dollars)


# ---------------------------------------------------------------------------
# Tier 5: penalty accumulation targeting
# ---------------------------------------------------------------------------


def assess_penalty(client, entity_id, violation_type, officer=None, **overrides):
    """Assess one penalty with a freshly read expected_reporting_entity_version."""
    payload = f.penalty_assessment_payload(
        entity_id, violation_type, entity_version(client, entity_id), **overrides
    )
    return get_success_data(
        client.create_penalty_assessment(
            payload, officer if officer is not None else u.PENALTY_OFFICER
        ),
        expected_status=201,
    )


def assess_non_registration_penalties(client, entity_id, count):
    """Assess `count` NON_REGISTRATION penalties in sequence.

    Each row's repeat_index counts the firm's earlier assessments of the same
    violation type, so the amounts escalate across the sequence.
    """
    return [
        assess_penalty(client, entity_id, ViolationType.NON_REGISTRATION.value)
        for _ in range(count)
    ]


def pay_penalty(client, assessment_id, paid_amount_cents):
    return get_success_data(
        client.pay_penalty_assessment(
            assessment_id, f.payment_payload(paid_amount_cents), u.PENALTY_OFFICER
        )
    )


def waive_penalty(client, assessment_id, waiver_reason=None):
    payload = (
        f.waiver_payload(waiver_reason=waiver_reason)
        if waiver_reason is not None
        else f.waiver_payload()
    )
    return get_success_data(
        client.waive_penalty_assessment(assessment_id, payload, u.PENALTY_OFFICER)
    )


# ---------------------------------------------------------------------------
# Tier 5: methodology docket shortcuts
# ---------------------------------------------------------------------------


def open_docket(client, **overrides):
    return get_success_data(
        client.create_methodology_change(
            f.methodology_change_payload(**overrides), u.PROGRAM_ADMIN
        )
    )


def add_comment(client, change_id, headers=None, **overrides):
    return get_success_data(
        client.create_public_comment(
            change_id,
            f.public_comment_payload(**overrides),
            headers if headers is not None else u.PUBLIC_USER,
        )
    )


def commented_closed_docket(client, comment_period_end="2026-09-05T00:00:00Z", **overrides):
    """A docket with one comment, its period closed, ready to adopt."""
    docket = open_docket(client, comment_period_end=comment_period_end, **overrides)
    add_comment(client, docket["id"])
    set_clock(client, comment_period_end)
    return get_success_data(client.close_comment_period(docket["id"], u.PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Composite scenarios reused across many tests
# ---------------------------------------------------------------------------


def single_reporter_accepted_window(
    client,
    head_count=100,
    avg_net_price_per_cwt=280.00,
    avg_carcass_weight_cwt=8.00,
    window_overrides=None,
):
    """One firm, one ACCEPTED filing, on a window with relaxed guidelines.

    The window's confidentiality guidelines are set to one reporter, a 100
    percent share ceiling and a one-head floor, so a lone filing clears the
    guideline sequence rather than being withheld.
    """
    firm = alpha_firm(client)
    window = create_relaxed_window(client, **(window_overrides or {}))
    submission = accepted_filing(
        client,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=head_count,
                avg_net_price_per_cwt=avg_net_price_per_cwt,
                avg_carcass_weight_cwt=avg_carcass_weight_cwt,
            )
        ],
    )
    return {
        "entity": firm["entity"],
        "plant": firm["plant"],
        "registration": firm["registration"],
        "window": window,
        "submission": submission,
    }


# The three reporters of the shared CATTLE weekly scenario.  Alpha files a
# negotiated and a formula line, Bravo a grid and a packer-owned line, and the
# cooperative a single negotiated line.
ALPHA_LINES = [
    f.transaction_payload(
        head_count=200, avg_net_price_per_cwt=279.75, avg_carcass_weight_cwt=8.60
    ),
    f.formula_transaction_payload(
        head_count=300, avg_net_price_per_cwt=292.25, avg_carcass_weight_cwt=9.40
    ),
]
BRAVO_LINES = [
    f.grid_transaction_payload(
        head_count=200, avg_net_price_per_cwt=285.50, avg_carcass_weight_cwt=8.80
    ),
    f.packer_owned_transaction_payload(
        head_count=300, avg_net_price_per_cwt=288.00, avg_carcass_weight_cwt=9.00
    ),
]
COOP_LINES = [
    f.transaction_payload(
        head_count=250, avg_net_price_per_cwt=282.40, avg_carcass_weight_cwt=8.20
    )
]


def alpha_firm(client, **overrides):
    """Alpha Packing: one CATTLE plant EST-101, ACTIVE MANDATORY 2026."""
    return obligated_firm(client, legal_name="Alpha Packing", **overrides)


def bravo_firm(client, **overrides):
    """Bravo Beef, whose history measures above threshold only on the prior year."""
    return obligated_firm(
        client,
        legal_name="Bravo Beef",
        plant_code="EST-202",
        annual_head_history=dict(k.HISTORY_BELOW_CATTLE_FLOOR),
        plant_overrides={
            "boxed_beef_volume_lbs_prior_year": 0,
            "forward_commitment_cap_head": 1000,
        },
        basis_variant=BasisVariant.PRIOR_YEAR_ACTUAL.value,
        **overrides,
    )


def coop_firm(client, **overrides):
    """Cattle Coop: a packer-processor whose five lookback years are flat."""
    return obligated_firm(
        client,
        legal_name="Cattle Coop",
        plant_code="EST-303",
        entity_type=EntityType.PACKER_PROCESSOR.value,
        annual_head_history={
            "2021": 125000,
            "2022": 125000,
            "2023": 125000,
            "2024": 125000,
            "2025": 125000,
        },
        plant_overrides={
            "boxed_beef_volume_lbs_prior_year": 0,
            "forward_commitment_cap_head": 1000,
        },
        **overrides,
    )


def three_reporter_cattle_window(client, window_overrides=None):
    """Three firms each with one ACCEPTED filing on one CATTLE weekly window.

    Alpha books 500 head, Bravo 500 head and the cooperative 250, so the
    window ledger reads 1,250 head over three accepted filings and the largest
    single reporter holds exactly 40.00 percent of it.
    """
    alpha = alpha_firm(client)
    bravo = bravo_firm(client)
    coop = coop_firm(client)
    window = create_standard_window(client, **(window_overrides or {}))

    submissions = {}
    for key, firm, lines in (
        ("alpha", alpha, ALPHA_LINES),
        ("bravo", bravo, BRAVO_LINES),
        ("coop", coop, COOP_LINES),
    ):
        submissions[key] = accepted_filing(
            client,
            firm["entity"]["id"],
            firm["plant"]["id"],
            window["id"],
            lines=lines,
        )

    return {
        "alpha": alpha,
        "bravo": bravo,
        "coop": coop,
        "window": window,
        "submissions": submissions,
    }


def boxed_beef_firm_and_window(client, boxed_beef_volume_lbs_prior_year=2500000):
    """A firm authorized for wholesale reporting, and a BOXED_BEEF window."""
    firm = obligated_firm(
        client,
        plant_overrides={
            "boxed_beef_volume_lbs_prior_year": boxed_beef_volume_lbs_prior_year
        },
    )
    window = create_relaxed_window(
        client,
        report_class=ReportClass.BOXED_BEEF.value,
        min_reported_head=1,
    )
    return {"firm": firm, "window": window}
