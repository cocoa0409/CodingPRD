"""TCM claim preparation, the money waterfall and the bounded appeal loop (PRD 3.8)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("claims", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/tcm/episodes/<episode_id>/claims")
def prepare_claim(episode_id):
    user_id, _role = G.auth(["BillingSpecialist"])
    data = G.body()
    visit_id = G.req_string(data, "visit_id")

    episode = G.get_episode(episode_id)
    visit = G.get_row("visits", visit_id)

    # rung 7 - the named visit must belong to this episode
    if visit["episode_id"] != episode["id"]:
        raise ApiError("ERR_ENTITY_LINK_MISMATCH")

    G.require_open_records(episode)

    # rung 26 - the episode-status requirement, deliberately reported here
    if episode["status"] != "SERVICE_PERIOD_CLOSED":
        raise ApiError("ERR_SERVICE_PERIOD_OPEN")

    # rung 28 - there must be a billable service
    if visit["encounter_status"] != "COMPLETED" or visit["documentation_status"] not in (
        "ATTESTED",
        "AMENDED",
    ):
        raise ApiError("ERR_CLAIM_NOT_BILLABLE")

    # rung 29 - no TCM code covers a later encounter
    moderate_deadline = store.end_of_day(
        store.add_days(episode["discharge_date"], C.VISIT_DUE_DAYS_MODERATE_COMPLEXITY)
    )
    if visit["completed_at"] > moderate_deadline:
        raise ApiError("ERR_VISIT_WINDOW_MISSED")

    # rung 31 - one billable TCM claim per patient per service period
    start = episode["discharge_date"]
    end = episode["service_period_end_date"]
    for other in DB["claims"].values():
        if other["patient_id"] != episode["patient_id"] or other["status"] == "VOIDED":
            continue
        if _overlaps(
            start, end, other["service_period_start_date"], other["service_period_end_date"]
        ):
            raise ApiError("ERR_DUPLICATE_TCM_CLAIM")

    selection = domain.claim_code_selection(episode, visit)
    if selection is None:
        raise ApiError("ERR_VISIT_WINDOW_MISSED")
    payable_code, payable_variant, base_rate_cents = selection
    payer = DB["payers"][episode["payer_id"]]
    money = domain.claim_money(base_rate_cents, payer)

    fields = {
        "episode_id": episode["id"],
        "patient_id": episode["patient_id"],
        "visit_id": visit["id"],
        "payer_id": episode["payer_id"],
        "service_period_start_date": start,
        "service_period_end_date": end,
        "payable_code": payable_code,
        "payable_variant": payable_variant,
        "base_rate_cents": base_rate_cents,
    }
    fields.update(money)
    fields.update(
        {
            "status": "PREPARED",
            "appeal_count": 0,
            "denial_reason_code": None,
            "prepared_by_user_id": user_id,
            "submitted_by_user_id": None,
            "readmission_flagged": False,
            "paid_at": None,
        }
    )
    claim = store.new_row("claims", fields)

    episode["claim_id"] = claim["id"]
    store.touch(episode)
    domain.evaluate_freeze(episode)
    return envelope.created(serialize(claim))


@bp.get("/tcm/claims/<claim_id>")
def read_claim(claim_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("claims", claim_id)))


@bp.get("/tcm/claims")
def list_claims():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "patient_id", "visit_id", "payer_id", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("claims", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/claims/<claim_id>/submit")
def submit_claim(claim_id):
    user_id, _role = G.auth(["BillingSpecialist"])
    claim = G.get_row("claims", claim_id)
    episode = DB["episodes"][claim["episode_id"]]
    G.require_open_records(episode)

    if claim["status"] != "PREPARED":
        raise ApiError("ERR_INVALID_STATE", "Only a PREPARED claim may be submitted.")
    if episode["status"] != "SERVICE_PERIOD_CLOSED":
        raise ApiError("ERR_INVALID_STATE", "The episode is not in SERVICE_PERIOD_CLOSED.")
    if not episode["billing_eligible"]:
        raise ApiError("ERR_INVALID_STATE", "The episode is no longer billing eligible.")
    if user_id == claim["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if not episode["medrec_complete"]:
        raise ApiError("ERR_MEDREC_NOT_COMPLETE")
    if not episode["contact_timely"]:
        raise ApiError("ERR_CONTACT_NOT_TIMELY")

    claim["status"] = "SUBMITTED"
    claim["submitted_by_user_id"] = user_id
    store.touch(claim)
    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(claim))


@bp.post("/tcm/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    G.auth(["ProgramAdmin"])
    data = G.body()
    outcome = G.req_string(data, "outcome")
    denial_reason_code = G.opt_string(data, "denial_reason_code")
    G.enum(outcome, C.ADJUDICATION_OUTCOMES, "outcome")
    if denial_reason_code is not None:
        G.enum(denial_reason_code, C.DENIAL_REASON_CODES, "denial_reason_code")

    claim = G.get_row("claims", claim_id)
    episode = DB["episodes"][claim["episode_id"]]
    G.require_open_records(episode)

    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED or APPEALED claim may be adjudicated.")

    if outcome == "PAID":
        claim["status"] = "PAID"
        claim["paid_at"] = store.now()
        store.touch(claim)
        if episode["status"] == "SERVICE_PERIOD_CLOSED":
            episode["status"] = "BILLED"
            store.touch(episode)
            domain.recompute_navigator(episode["navigator_id"])
            domain.recompute_patient(episode["patient_id"])
    else:
        claim["status"] = "DENIED"
        claim["denial_reason_code"] = denial_reason_code
        store.touch(claim)

    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(claim))


@bp.post("/tcm/claims/<claim_id>/appeal")
def appeal_claim(claim_id):
    G.auth(["BillingSpecialist"])
    claim = G.get_row("claims", claim_id)
    episode = DB["episodes"][claim["episode_id"]]
    G.require_open_records(episode)

    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "Only a DENIED claim may be appealed.")

    if claim["appeal_count"] >= C.MAX_CLAIM_APPEALS:
        # The rejection is returned only after the status flip is persisted.
        claim["status"] = "DENIED_FINAL"
        claim["net_payable_cents"] = 0
        store.touch(claim)
        domain.evaluate_freeze(episode)
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")

    claim["status"] = "APPEALED"
    claim["appeal_count"] += 1
    store.touch(claim)
    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(claim))


@bp.post("/tcm/claims/<claim_id>/void")
def void_claim_endpoint(claim_id):
    G.auth(["ProgramAdmin"])
    claim = G.get_row("claims", claim_id)
    episode = DB["episodes"][claim["episode_id"]]
    G.require_open_records(episode)

    if claim["status"] not in C.NON_TERMINAL_CLAIM_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "Only a non-terminal claim may be voided.")

    domain.void_claim(claim)
    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(claim))
