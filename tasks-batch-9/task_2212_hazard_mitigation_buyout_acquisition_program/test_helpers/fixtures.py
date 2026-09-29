"""Composite state builders.

The service is restarted with an empty database before every test, so each
builder drives the public API from nothing up to the posture a test needs. The
builders are layered: later ones call earlier ones rather than repeating chains.

Every builder returns a plain dict of the entities it created, keyed by role in
the chain ("project", "parcel", "initial_appraisal", ...), so a test can reach
whichever link it needs to perturb.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .test_users import TEST_USERS, make_subrecipient_coordinator_headers


def _data(response, expected_status=None):
    return get_success_data(response, expected_status)


def _list(response):
    return validate_paginated(response)


# ─── Tier 1: the project container ────────────────────────────────────────────

def create_draft_project(api, headers=None, **overrides):
    """A brand-new project in DRAFT at version 1."""
    return _data(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(**overrides),
            headers or TEST_USERS["program_administrator_headers"],
        ),
        201,
    )


def create_parcel(api, project, **overrides):
    """A parcel on a project that is still in DRAFT or SUBMITTED."""
    return _data(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(project["id"], **overrides),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )


def create_benefit_cost_analysis(api, project, **overrides):
    """A benefit-cost analysis attached while the project is in DRAFT or SUBMITTED."""
    return _data(
        api.create_benefit_cost_analysis(
            project["id"],
            factories.create_benefit_cost_analysis_payload(project["id"], **overrides),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )


# ─── Tier 2: project lifecycle shortcuts ──────────────────────────────────────

def create_submitted_project(api, parcel_overrides=None, bca_overrides=None,
                             project_overrides=None):
    """A project in SUBMITTED carrying one parcel and one SUBMITTED analysis."""
    project = create_draft_project(api, **(project_overrides or {}))
    parcel = create_parcel(api, project, **(parcel_overrides or {}))
    bca = create_benefit_cost_analysis(api, project, **(bca_overrides or {}))
    project = _data(
        api.submit_mitigation_project(
            project["id"], make_subrecipient_coordinator_headers(project["id"])
        )
    )
    return {"project": project, "parcel": parcel, "bca": bca}


def create_validated_project(api, **kwargs):
    """A project in SUBMITTED whose analysis has been VALIDATED by pa-validator."""
    state = create_submitted_project(api, **kwargs)
    state["bca"] = _data(
        api.validate_benefit_cost_analysis(
            state["bca"]["id"],
            factories.validate_bca_payload(state["bca"]["id"], "VALIDATE"),
            TEST_USERS["bca_validator_headers"],
        )
    )
    state["project"] = _data(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


def create_approved_project(api, **kwargs):
    """A project in APPROVED, approved by pa-approver so SoD-2 is satisfied."""
    state = create_validated_project(api, **kwargs)
    state["project"] = _data(
        api.approve_mitigation_project(
            state["project"]["id"],
            factories.approve_project_payload(state["project"]["id"], "APPROVE"),
            TEST_USERS["project_approver_headers"],
        )
    )
    return state


def create_approved_project_with_parcels(api, parcel_specs, bca_overrides=None,
                                         project_overrides=None):
    """An APPROVED project carrying one parcel per entry in ``parcel_specs``.

    All parcels are created before submission, because a parcel may only be added
    while the project is in DRAFT or SUBMITTED.
    """
    project = create_draft_project(api, **(project_overrides or {}))
    parcels = [create_parcel(api, project, **spec) for spec in parcel_specs]
    bca = create_benefit_cost_analysis(api, project, **(bca_overrides or {}))
    project = _data(
        api.submit_mitigation_project(
            project["id"], make_subrecipient_coordinator_headers(project["id"])
        )
    )
    bca = _data(
        api.validate_benefit_cost_analysis(
            bca["id"],
            factories.validate_bca_payload(bca["id"], "VALIDATE"),
            TEST_USERS["bca_validator_headers"],
        )
    )
    project = _data(
        api.approve_mitigation_project(
            project["id"],
            factories.approve_project_payload(project["id"], "APPROVE"),
            TEST_USERS["project_approver_headers"],
        )
    )
    return {"project": project, "parcels": parcels, "bca": bca}


# ─── Tier 3: parcel progression on the two dimensions ─────────────────────────

def parcel_with_pre_event_value(api, **kwargs):
    """An APPROVED project whose parcel carries a pre-event fair market value."""
    state = create_approved_project(api, **kwargs)
    state["parcel"] = _data(
        api.record_pre_event_value(
            state["parcel"]["id"],
            factories.pre_event_value_payload(state["parcel"]["id"]),
            TEST_USERS["staff_appraiser_headers"],
        )
    )
    return state


def parcel_interested(api, **kwargs):
    """A parcel whose owner has expressed interest."""
    state = parcel_with_pre_event_value(api, **kwargs)
    state["parcel"] = _data(
        api.record_participation(
            state["parcel"]["id"],
            factories.participation_payload(state["parcel"]["id"], "INTERESTED"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    return state


def parcel_voluntary_confirmed(api, **kwargs):
    """A parcel whose owner has signed the voluntary acknowledgement."""
    state = parcel_interested(api, **kwargs)
    state["parcel"] = _data(
        api.record_participation(
            state["parcel"]["id"],
            factories.participation_payload(state["parcel"]["id"], "CONFIRM_VOLUNTARY"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    return state


# ─── Tier 4: appraisal and independent review ─────────────────────────────────

def accepted_initial_appraisal(api, parcel_id, staff_headers=None, review_headers=None,
                               **overrides):
    """One INITIAL appraisal authored, submitted and ACCEPTED by a review appraiser."""
    staff_headers = staff_headers or TEST_USERS["staff_appraiser_headers"]
    review_headers = review_headers or TEST_USERS["review_appraiser_headers"]
    appraisal = _data(
        api.create_appraisal(
            parcel_id,
            factories.create_appraisal_payload(parcel_id, **overrides),
            staff_headers,
        ),
        201,
    )
    appraisal = _data(api.submit_appraisal(appraisal["id"], staff_headers))
    appraisal = _data(
        api.review_appraisal(
            appraisal["id"],
            factories.review_decision_payload(appraisal["id"], "ACCEPT"),
            review_headers,
        )
    )
    return appraisal


def accepted_review_appraisal(api, parcel_id, initial_appraisal,
                              author_headers=None, accepter_headers=None, **overrides):
    """One REVIEW appraisal over an accepted INITIAL appraisal, itself ACCEPTED.

    The author and the accepter are different review appraisers, and neither is
    the staff appraiser who authored the initial opinion, so both limbs of the
    review segregation-of-duties rule hold.
    """
    author_headers = author_headers or TEST_USERS["review_appraiser_headers"]
    accepter_headers = accepter_headers or TEST_USERS["review_appraiser_2_headers"]
    review = _data(
        api.create_appraisal(
            parcel_id,
            factories.create_review_appraisal_payload(
                parcel_id, initial_appraisal["id"], **overrides
            ),
            author_headers,
        ),
        201,
    )
    review = _data(api.submit_appraisal(review["id"], author_headers))
    review = _data(
        api.review_appraisal(
            review["id"],
            factories.review_decision_payload(review["id"], "ACCEPT"),
            accepter_headers,
        )
    )
    return review


def parcel_value_established(api, indicated_value_cents=None, **kwargs):
    """A parcel at acquisition_status VALUE_ESTABLISHED with an accepted review appraisal."""
    state = parcel_voluntary_confirmed(api, **kwargs)
    initial_overrides = {}
    review_overrides = {}
    if indicated_value_cents is not None:
        initial_overrides["indicated_value_cents"] = indicated_value_cents
        review_overrides["indicated_value_cents"] = indicated_value_cents
    state["initial_appraisal"] = accepted_initial_appraisal(
        api, state["parcel"]["id"], **initial_overrides
    )
    state["review_appraisal"] = accepted_review_appraisal(
        api, state["parcel"]["id"], state["initial_appraisal"], **review_overrides
    )
    state["parcel"] = _data(
        api.get_parcel(state["parcel"]["id"], TEST_USERS["program_administrator_headers"])
    )
    return state


def progress_parcel_to_value_established(api, project, parcel, pre_event_fmv_cents=None,
                                         indicated_value_cents=None,
                                         appraisal_overrides=None):
    """Drive one named parcel of an APPROVED project all the way to VALUE_ESTABLISHED.

    Useful when a test needs several parcels of the same project at that posture,
    which the single-parcel builders above cannot express.
    """
    value_overrides = {}
    if pre_event_fmv_cents is not None:
        value_overrides["pre_event_fmv_cents"] = pre_event_fmv_cents
    parcel = _data(
        api.record_pre_event_value(
            parcel["id"],
            factories.pre_event_value_payload(parcel["id"], **value_overrides),
            TEST_USERS["staff_appraiser_headers"],
        )
    )
    coordinator = make_subrecipient_coordinator_headers(project["id"])
    parcel = _data(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(parcel["id"], "INTERESTED"),
            coordinator,
        )
    )
    parcel = _data(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(parcel["id"], "CONFIRM_VOLUNTARY"),
            coordinator,
        )
    )
    overrides = dict(appraisal_overrides or {})
    if indicated_value_cents is not None:
        overrides["indicated_value_cents"] = indicated_value_cents
    initial = accepted_initial_appraisal(api, parcel["id"], **overrides)
    review = accepted_review_appraisal(api, parcel["id"], initial, **overrides)
    parcel = _data(
        api.get_parcel(parcel["id"], TEST_USERS["program_administrator_headers"])
    )
    return {"parcel": parcel, "initial_appraisal": initial, "review_appraisal": review}


def record_dob(api, project, parcel_id, **overrides):
    """One duplication-of-benefits record on a parcel of an APPROVED project."""
    return _data(
        api.create_dob_record(
            parcel_id,
            factories.create_dob_record_payload(parcel_id, **overrides),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )


# ─── Tier 5: offers ───────────────────────────────────────────────────────────

def build_offer(api, project, parcel_id, review_appraisal, headers=None, **overrides):
    """A DRAFT purchase offer built from an accepted review appraisal.

    The parcel version is re-read immediately before the call so the stale-read
    guard sees the live value.
    """
    headers = headers or make_subrecipient_coordinator_headers(project["id"])
    parcel = _data(api.get_parcel(parcel_id, TEST_USERS["program_administrator_headers"]))
    return _data(
        api.create_purchase_offer(
            parcel_id,
            factories.create_purchase_offer_payload(
                parcel_id, review_appraisal["id"], parcel["version"], **overrides
            ),
            headers,
        ),
        201,
    )


def parcel_with_draft_offer(api, **kwargs):
    """A parcel carrying one DRAFT offer."""
    state = parcel_value_established(api, **kwargs)
    state["offer"] = build_offer(
        api, state["project"], state["parcel"]["id"], state["review_appraisal"]
    )
    return state


def parcel_with_presented_offer(api, **kwargs):
    """A parcel at OFFER_OUTSTANDING with the federal share obligated."""
    state = parcel_with_draft_offer(api, **kwargs)
    state["offer"] = _data(
        api.present_purchase_offer(
            state["offer"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    state["project"] = _data(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


def parcel_with_accepted_offer(api, **kwargs):
    """A parcel at OFFER_ACCEPTED, ready for a closing to be scheduled."""
    state = parcel_with_presented_offer(api, **kwargs)
    state["offer"] = _data(
        api.respond_to_purchase_offer(
            state["offer"]["id"],
            factories.owner_response_payload(state["offer"]["id"], "ACCEPT"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    state["parcel"] = _data(
        api.get_parcel(state["parcel"]["id"], TEST_USERS["program_administrator_headers"])
    )
    return state


# ─── Tier 6: closing, title and the deed ──────────────────────────────────────

def parcel_with_scheduled_closing(api, closing_overrides=None, **kwargs):
    """A closing in SCHEDULED against the parcel's accepted offer."""
    state = parcel_with_accepted_offer(api, **kwargs)
    state["closing"] = _data(
        api.create_closing_record(
            state["parcel"]["id"],
            factories.create_closing_record_payload(
                state["parcel"]["id"],
                state["offer"]["id"],
                **(closing_overrides or {}),
            ),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        201,
    )
    return state


def parcel_closed(api, **kwargs):
    """A funded closing: the parcel has reached CLOSED and title has passed."""
    state = parcel_with_scheduled_closing(api, **kwargs)
    state["closing"] = _data(
        api.fund_closing_record(
            state["closing"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    state["parcel"] = _data(
        api.get_parcel(state["parcel"]["id"], TEST_USERS["program_administrator_headers"])
    )
    state["project"] = _data(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


# ─── Tier 7: contractors, work orders and utilities ───────────────────────────

def create_contractor(api, headers=None, **overrides):
    """An ACTIVE demolition contractor."""
    return _data(
        api.create_demolition_contractor(
            factories.create_demolition_contractor_payload(**overrides),
            headers or TEST_USERS["program_administrator_headers"],
        ),
        201,
    )


def issue_work_order(api, project, parcel_id, contractor_id, **overrides):
    """A work order in ISSUED for a parcel under a given contractor."""
    return _data(
        api.create_demolition_work_order(
            parcel_id,
            factories.create_work_order_payload(parcel_id, contractor_id, **overrides),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )


def order_all_utility_disconnections(api, project, work_order_id):
    """One PENDING disconnection per required utility; the parent falls to UTILITY_HOLD."""
    headers = make_subrecipient_coordinator_headers(project["id"])
    disconnections = {}
    for utility_type in ("WATER", "ELECTRIC", "GAS", "SEWER"):
        disconnections[utility_type] = _data(
            api.create_utility_disconnection(
                work_order_id,
                factories.create_utility_disconnection_payload(work_order_id, utility_type),
                headers,
            ),
            201,
        )
    return disconnections


def confirm_all_utility_disconnections(api, project, disconnections):
    """Confirm every disconnection so the parent work order becomes READY."""
    headers = make_subrecipient_coordinator_headers(project["id"])
    confirmed = {}
    for utility_type, disconnection in disconnections.items():
        confirmed[utility_type] = _data(
            api.resolve_utility_disconnection(
                disconnection["id"],
                factories.resolve_disconnection_payload(disconnection["id"], "CONFIRMED"),
                headers,
            )
        )
    return confirmed


def work_order_ready(api, contractor_overrides=None, work_order_overrides=None, **kwargs):
    """A CLOSED parcel whose work order is READY: all four utilities confirmed."""
    state = parcel_closed(api, **kwargs)
    state["contractor"] = create_contractor(api, **(contractor_overrides or {}))
    state["work_order"] = issue_work_order(
        api,
        state["project"],
        state["parcel"]["id"],
        state["contractor"]["id"],
        **(work_order_overrides or {}),
    )
    state["disconnections"] = order_all_utility_disconnections(
        api, state["project"], state["work_order"]["id"]
    )
    state["disconnections"] = confirm_all_utility_disconnections(
        api, state["project"], state["disconnections"]
    )
    state["work_order"] = _data(
        api.get_demolition_work_order(
            state["work_order"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


def work_order_in_progress(api, **kwargs):
    """A mobilized work order in IN_PROGRESS."""
    state = work_order_ready(api, **kwargs)
    state["work_order"] = _data(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    return state


def parcel_demolished(api, complete_overrides=None, **kwargs):
    """A completed demolition: the parcel has reached DEMOLISHED."""
    state = work_order_in_progress(api, **kwargs)
    state["work_order"] = _data(
        api.complete_demolition_work_order(
            state["work_order"]["id"],
            factories.complete_work_order_payload(
                state["work_order"]["id"], **(complete_overrides or {})
            ),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    state["parcel"] = _data(
        api.get_parcel(state["parcel"]["id"], TEST_USERS["program_administrator_headers"])
    )
    return state


# ─── Tier 8: the perpetual open-space restriction ─────────────────────────────

def parcel_open_space_recorded(api, record_overrides=None, **kwargs):
    """A recorded deed: the parcel is OPEN_SPACE_RECORDED and a restriction exists."""
    state = parcel_demolished(api, **kwargs)
    state["closing"] = _data(
        api.record_closing_deed(
            state["closing"]["id"],
            factories.record_deed_payload(
                state["closing"]["id"], **(record_overrides or {})
            ),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    restrictions, _meta = _list(
        api.list_deed_restrictions(
            TEST_USERS["program_administrator_headers"],
            params={"parcel_id": state["parcel"]["id"]},
        )
    )
    state["restriction"] = restrictions[0]
    state["parcel"] = _data(
        api.get_parcel(state["parcel"]["id"], TEST_USERS["program_administrator_headers"])
    )
    state["project"] = _data(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


def restriction_with_open_violation(api, prohibited_use_code="NEW_STRUCTURE",
                                   monitor_headers=None, **kwargs):
    """A restriction in VIOLATION_OPEN, reported by cm-1."""
    state = parcel_open_space_recorded(api, **kwargs)
    monitor_headers = monitor_headers or TEST_USERS["compliance_monitor_headers"]
    state["inspection"] = _data(
        api.create_monitoring_inspection(
            state["restriction"]["id"],
            factories.create_monitoring_inspection_payload(
                state["restriction"]["id"],
                finding="PROHIBITED_USE_OBSERVED",
                prohibited_use_code=prohibited_use_code,
            ),
            monitor_headers,
        ),
        201,
    )
    state["restriction"] = _data(
        api.get_deed_restriction(
            state["restriction"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


# ─── Tier 9: relocation ───────────────────────────────────────────────────────

def open_relocation_case(api, parcel_id, headers=None, **overrides):
    """A relocation case in OPENED on a parcel."""
    return _data(
        api.create_relocation_case(
            parcel_id,
            factories.create_relocation_case_payload(parcel_id, **overrides),
            headers or TEST_USERS["relocation_specialist_headers"],
        ),
        201,
    )


def relocation_case_determined(api, case_overrides=None, **kwargs):
    """A parcel with an accepted offer and a case at ELIGIBILITY_DETERMINED."""
    state = parcel_with_accepted_offer(api, **kwargs)
    state["case"] = open_relocation_case(
        api, state["parcel"]["id"], **(case_overrides or {})
    )
    state["case"] = _data(
        api.determine_relocation_eligibility(
            state["case"]["id"], TEST_USERS["relocation_specialist_headers"]
        )
    )
    return state


def relocation_case_submitted(api, **kwargs):
    """A relocation case at CLAIM_SUBMITTED."""
    state = relocation_case_determined(api, **kwargs)
    state["case"] = _data(
        api.submit_relocation_claim(
            state["case"]["id"], TEST_USERS["relocation_specialist_headers"]
        )
    )
    return state


def relocation_case_paid(api, **kwargs):
    """A relocation case at CLAIM_PAID, its federal share booked on the project."""
    state = relocation_case_submitted(api, **kwargs)
    state["case"] = _data(
        api.resolve_relocation_claim(
            state["case"]["id"],
            factories.resolve_claim_payload(state["case"]["id"], "PAY"),
            TEST_USERS["program_administrator_headers"],
        )
    )
    state["project"] = _data(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    return state


def relocation_case_denied(api, **kwargs):
    """A relocation case at CLAIM_DENIED, still open to appeal."""
    state = relocation_case_submitted(api, **kwargs)
    state["case"] = _data(
        api.resolve_relocation_claim(
            state["case"]["id"],
            factories.resolve_claim_payload(
                state["case"]["id"], "DENY", denial_reason="insufficient documentation"
            ),
            TEST_USERS["program_administrator_headers"],
        )
    )
    return state


# ─── Tier 10: the program income ledger ───────────────────────────────────────

def post_program_income(api, project_id, **overrides):
    """Post one ledger entry, re-reading the project version for the OCC guard."""
    project = _data(
        api.get_mitigation_project(project_id, TEST_USERS["program_administrator_headers"])
    )
    return _data(
        api.create_program_income_entry(
            project_id,
            factories.create_program_income_entry_payload(
                project_id, project["version"], **overrides
            ),
            make_subrecipient_coordinator_headers(project_id),
        ),
        201,
    )


def project_ready_for_closeout(api, **kwargs):
    """A project whose only parcel is OPEN_SPACE_RECORDED, so INITIATE may be called."""
    return parcel_open_space_recorded(api, **kwargs)


def project_in_closeout_pending(api, **kwargs):
    """A project moved to CLOSEOUT_PENDING."""
    state = project_ready_for_closeout(api, **kwargs)
    state["project"] = _data(
        api.closeout_mitigation_project(
            state["project"]["id"],
            factories.closeout_payload(state["project"]["id"], "INITIATE"),
            TEST_USERS["program_administrator_headers"],
        )
    )
    return state

