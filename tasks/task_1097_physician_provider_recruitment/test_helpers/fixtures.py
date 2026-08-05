"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the harness restarts the server (empty DB) before every test.
Setup calls use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: entity-backed roles always act through per-instance header
builders keyed on the real backing entity id (StaffUser id, or Client id for
ClientContact), never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .test_users import (
    make_platform_admin_headers,
    make_recruiter_headers,
    make_account_manager_headers,
    make_credentialing_coordinator_headers,
    make_client_contact_headers,
)
from . import factories as f

ADMIN = make_platform_admin_headers()


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def create_staff(role, **overrides) -> dict:
    return get_success_data(
        api.create_staff_user(f.create_staff_user_payload(role, **overrides), ADMIN)
    )


def create_recruiter(covered_specialties=None, **overrides) -> dict:
    if covered_specialties is None:
        covered_specialties = ["CARDIOLOGY"]
    fields = {"full_name": "Rio Rec", "email": "rec@x.com",
              "covered_specialties": covered_specialties}
    fields.update(overrides)
    return create_staff("RECRUITER", **fields)


def create_account_manager(**overrides) -> dict:
    fields = {"full_name": "Amy AM", "email": "am@x.com"}
    fields.update(overrides)
    return create_staff("ACCOUNT_MANAGER", **fields)


def create_coordinator(**overrides) -> dict:
    fields = {"full_name": "Cora Coord", "email": "coord@x.com"}
    fields.update(overrides)
    return create_staff("CREDENTIALING_COORDINATOR", **fields)


def set_clock(iso: str):
    return get_success_data(api.set_clock(iso, ADMIN))


def deactivate_staff(staff_id):
    return get_success_data(api.transition_staff_user(staff_id, "DEACTIVATE", ADMIN))


def create_client_entity(am_id, **overrides) -> dict:
    return get_success_data(
        api.create_client(
            f.create_client_payload(am_id, **overrides),
            make_account_manager_headers(am_id),
        )
    )


def create_opening(am_id, client_id, **overrides) -> dict:
    return get_success_data(
        api.create_job_opening(
            f.create_job_opening_payload(client_id, **overrides),
            make_account_manager_headers(am_id),
        )
    )


def publish_opening(am_id, opening_id) -> dict:
    return get_success_data(
        api.transition_job_opening(opening_id, "PUBLISH", make_account_manager_headers(am_id))
    )


def create_candidate_entity(rec_id, **overrides) -> dict:
    return get_success_data(
        api.create_candidate(
            f.create_candidate_payload(rec_id, **overrides), make_recruiter_headers(rec_id)
        )
    )


def create_application_entity(rec_id, cand_id, opening_id) -> dict:
    return get_success_data(
        api.create_application(
            f.create_application_payload(cand_id, opening_id), make_recruiter_headers(rec_id)
        )
    )


def screen_application(rec_id, app_id) -> dict:
    return get_success_data(
        api.advance_application(app_id, "SCREEN", make_recruiter_headers(rec_id))
    )


def submit_application(rec_id, app_id) -> dict:
    return get_success_data(
        api.advance_application(app_id, "SUBMIT", make_recruiter_headers(rec_id))
    )


def advance_to_interview(client_id, app_id) -> dict:
    return get_success_data(
        api.advance_application(
            app_id, "ADVANCE_TO_INTERVIEW", make_client_contact_headers(client_id)
        )
    )


def create_site_visit_entity(rec_id, app_id, interviewer_id, **overrides) -> dict:
    return get_success_data(
        api.create_site_visit(
            f.create_site_visit_payload(app_id, interviewer_id, **overrides),
            make_recruiter_headers(rec_id),
        )
    )


def complete_site_visit(rec_id, sv_id) -> dict:
    return get_success_data(
        api.transition_site_visit(sv_id, "COMPLETE", make_recruiter_headers(rec_id))
    )


def create_offer_entity(am_id, app_id, **overrides) -> dict:
    return get_success_data(
        api.create_offer(
            f.create_offer_payload(app_id, **overrides), make_account_manager_headers(am_id)
        )
    )


def accept_offer(rec_id, offer_id) -> dict:
    return get_success_data(
        api.transition_offer(offer_id, "ACCEPT", make_recruiter_headers(rec_id))
    )


def get_placement_for_offer(am_id, offer_id) -> dict:
    data = get_success_data(
        api.list_placements(make_account_manager_headers(am_id), params={"offer_id": offer_id})
    )
    return data[0]


def get_cfile_for_placement(coord_id, placement_id) -> dict:
    data = get_success_data(
        api.list_credentialing_files(
            make_credentialing_coordinator_headers(coord_id),
            params={"placement_id": placement_id},
        )
    )
    return data[0]


def add_credential_item(coord_id, cfile_id, item_type="STATE_LICENSE", **overrides) -> dict:
    return get_success_data(
        api.create_credential_item(
            cfile_id, f.create_credential_item_payload(item_type, **overrides),
            make_credentialing_coordinator_headers(coord_id),
        )
    )


def item_transition(coord_id, item_id, action) -> dict:
    return get_success_data(
        api.transition_credential_item(
            item_id, action, make_credentialing_coordinator_headers(coord_id)
        )
    )


def clear_credentialing(coord_id, cfile_id) -> dict:
    """Add one required STATE_LICENSE item, SUBMIT then VERIFY it -> file CLEARED."""
    item = add_credential_item(coord_id, cfile_id, "STATE_LICENSE", is_required=True)
    item_transition(coord_id, item["id"], "SUBMIT")
    item_transition(coord_id, item["id"], "VERIFY")
    return item


def onboard_placement(coord_id, placement_id) -> dict:
    return get_success_data(
        api.transition_placement(
            placement_id, {"action": "ONBOARD"},
            make_credentialing_coordinator_headers(coord_id),
        )
    )


def invoice_placement(am_id, placement_id, final_first_year_comp_cents) -> dict:
    return get_success_data(
        api.transition_placement(
            placement_id,
            {"action": "INVOICE", "final_first_year_comp_cents": final_first_year_comp_cents},
            make_account_manager_headers(am_id),
        )
    )


def file_claim(am_id, placement_id, fell_out_date, **overrides) -> dict:
    return get_success_data(
        api.create_guarantee_claim(
            f.create_guarantee_claim_payload(placement_id, fell_out_date, **overrides),
            make_account_manager_headers(am_id),
        )
    )


def approve_claim(am_id, claim_id) -> dict:
    return get_success_data(
        api.transition_guarantee_claim(
            claim_id, {"action": "APPROVE"}, make_account_manager_headers(am_id)
        )
    )


def resolve_refund(am_id, claim_id) -> dict:
    return get_success_data(
        api.transition_guarantee_claim(
            claim_id, {"action": "RESOLVE_REFUND"}, make_account_manager_headers(am_id)
        )
    )


def resolve_replacement(am_id, claim_id, replacement_placement_id) -> dict:
    return get_success_data(
        api.transition_guarantee_claim(
            claim_id,
            {"action": "RESOLVE_REPLACEMENT",
             "replacement_placement_id": replacement_placement_id},
            make_account_manager_headers(am_id),
        )
    )


# --------------------------------------------------------------------------
# Composite tiers
# --------------------------------------------------------------------------
def setup_staff(with_coord=True) -> dict:
    """Provision AM + RECRUITER(CARDIOLOGY) [+ COORD]. Returns id ctx."""
    am = create_account_manager()
    rec = create_recruiter(["CARDIOLOGY"])
    ctx = {"am_id": am["id"], "rec_id": rec["id"], "am": am, "rec": rec}
    if with_coord:
        coord = create_coordinator()
        ctx["coord_id"] = coord["id"]
        ctx["coord"] = coord
    return ctx


def setup_open_opening(specialty="CARDIOLOGY", positions_total=1,
                       is_hard_to_fill=False, comp_min_cents=None, comp_max_cents=None,
                       with_coord=True, region="West", region_state="CA") -> dict:
    """Staff + client + PUBLISHed OPEN opening. Returns ctx with client/opening."""
    ctx = setup_staff(with_coord=with_coord)
    opening_kwargs = {
        "specialty": specialty, "positions_total": positions_total,
        "is_hard_to_fill": is_hard_to_fill, "region": region, "region_state": region_state,
    }
    if comp_min_cents is not None:
        opening_kwargs["comp_min_cents"] = comp_min_cents
    if comp_max_cents is not None:
        opening_kwargs["comp_max_cents"] = comp_max_cents
    client = create_client_entity(ctx["am_id"])
    opening = create_opening(ctx["am_id"], client["id"], **opening_kwargs)
    publish_opening(ctx["am_id"], opening["id"])
    ctx.update({"client_id": client["id"], "client": client,
                "opening_id": opening["id"], "opening": opening})
    return ctx


def _drive_to_interviewing(ctx, cand_overrides=None):
    """From an OPEN opening ctx: create candidate -> application -> SCREEN ->
    SUBMIT -> ADVANCE_TO_INTERVIEW. Returns (cand, app)."""
    cand = create_candidate_entity(ctx["rec_id"], **(cand_overrides or {}))
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    submit_application(ctx["rec_id"], app["id"])
    advance_to_interview(ctx["client_id"], app["id"])
    return cand, app


def setup_interviewing_application(cand_overrides=None, **opening_opts) -> dict:
    """OPEN opening + application driven to INTERVIEWING (no site visit yet)."""
    ctx = setup_open_opening(**opening_opts)
    cand, app = _drive_to_interviewing(ctx, cand_overrides)
    ctx.update({"cand_id": cand["id"], "cand": cand, "app_id": app["id"], "app": app})
    return ctx


def setup_offer_extended(cand_overrides=None, offer_overrides=None, **opening_opts) -> dict:
    """Application INTERVIEWING with a COMPLETED site visit, then an EXTENDED
    offer (application -> OFFER_STAGE). Returns ctx with sv_id + offer."""
    ctx = setup_interviewing_application(cand_overrides=cand_overrides, **opening_opts)
    sv = create_site_visit_entity(ctx["rec_id"], ctx["app_id"], ctx["rec_id"])
    complete_site_visit(ctx["rec_id"], sv["id"])
    offer = create_offer_entity(ctx["am_id"], ctx["app_id"], **(offer_overrides or {}))
    ctx.update({"sv_id": sv["id"], "sv": sv, "offer_id": offer["id"], "offer": offer})
    return ctx


def setup_placement_pre_start(cand_overrides=None, offer_overrides=None, **opening_opts) -> dict:
    """Accept the EXTENDED offer -> Placement PRE_START (fee PENDING) + a
    NOT_STARTED CredentialingFile. Returns ctx with placement + cfile_id."""
    ctx = setup_offer_extended(
        cand_overrides=cand_overrides, offer_overrides=offer_overrides, **opening_opts
    )
    accept_offer(ctx["rec_id"], ctx["offer_id"])
    placement = get_placement_for_offer(ctx["am_id"], ctx["offer_id"])
    cfile = get_cfile_for_placement(ctx["coord_id"], placement["id"])
    ctx.update({"placement_id": placement["id"], "placement": placement,
                "cfile_id": cfile["id"], "cfile": cfile})
    return ctx


def setup_placement_active(start_date=None, cand_overrides=None, offer_overrides=None,
                           **opening_opts) -> dict:
    """Placement ONBOARDed to ACTIVE: credentialing CLEARED, clock advanced to
    start_date, ONBOARD. Returns ctx with the ACTIVE placement."""
    ctx = setup_placement_pre_start(
        cand_overrides=cand_overrides, offer_overrides=offer_overrides, **opening_opts
    )
    clear_credentialing(ctx["coord_id"], ctx["cfile_id"])
    set_clock(start_date or TEST_DEFAULTS["START_DATE"])
    placement = onboard_placement(ctx["coord_id"], ctx["placement_id"])
    ctx["placement"] = placement
    return ctx


def setup_placement_invoiced(final_first_year_comp_cents=25_000_000, start_date=None,
                             cand_overrides=None, offer_overrides=None, **opening_opts) -> dict:
    """ACTIVE placement then INVOICEd (fee_status INVOICED, placement_fee_cents set)."""
    ctx = setup_placement_active(
        start_date=start_date, cand_overrides=cand_overrides,
        offer_overrides=offer_overrides, **opening_opts
    )
    placement = invoice_placement(ctx["am_id"], ctx["placement_id"], final_first_year_comp_cents)
    ctx["placement"] = placement
    return ctx
