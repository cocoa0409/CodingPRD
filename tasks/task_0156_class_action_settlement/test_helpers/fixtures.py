"""Composite setup helpers for the Class Action Settlement Administration API.

Most interesting claims require the fund to be in a specific posture reached
through 5-20 API calls (create settlement -> open notice -> open claims ->
register members -> file & validate claims -> close claims -> begin distribution
-> create/compute/post a batch -> reconcile). These helpers encapsulate those
chains so test files focus on assertions.

The harness restarts the server (empty DB, clock reset) before every test, so
every helper builds its preconditions from scratch using only PRD endpoints.

Identity discipline:
  * The validating ClaimsReviewer id is recorded by the server at validation
    time. The posting FundController id MUST differ, or the segregation-of-duties
    rule (PRD §2.10) rejects the post. These helpers default the reviewer to
    "reviewer-1" and the controller to "controller-1".
  * Claimant is entity_backed:ClassMember — ownership-gated calls pass the
    member id as X-User-ID via make_claimant_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_claims_reviewer_headers,
    make_fund_controller_headers,
    make_claimant_headers,
)

ADMIN = TEST_USERS["settlement_admin_headers"]
ADMINISTRATOR = TEST_USERS["claims_administrator_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]
CONTROLLER = TEST_USERS["fund_controller_headers"]
COURT = TEST_USERS["court_headers"]

DEFAULT_REVIEWER_ID = "reviewer-1"
DEFAULT_CONTROLLER_ID = "controller-1"


# ─── clock ────────────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server's logical now for deadline checks (PRD §3.11)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: settlement creation + posture progression ──────────────────────
def create_settlement(
    *,
    gross_fund_cents=100000,
    attorney_fee_cents=0,
    admin_cost_cents=0,
    distribution_method="PRO_RATA",
    tier_a_amount_cents=None,
    tier_b_amount_cents=None,
    claim_filing_deadline="2026-02-01T00:00:00Z",
    objection_deadline="2026-01-20T00:00:00Z",
    cy_pres_floor_cents=0,
    case_caption="In re Fixture",
):
    """Create a DRAFT settlement. Returns the settlement dict."""
    payload = {
        "case_caption": case_caption,
        "gross_fund_cents": gross_fund_cents,
        "attorney_fee_cents": attorney_fee_cents,
        "admin_cost_cents": admin_cost_cents,
        "distribution_method": distribution_method,
        "claim_filing_deadline": claim_filing_deadline,
        "objection_deadline": objection_deadline,
        "cy_pres_floor_cents": cy_pres_floor_cents,
    }
    if tier_a_amount_cents is not None:
        payload["tier_a_amount_cents"] = tier_a_amount_cents
    if tier_b_amount_cents is not None:
        payload["tier_b_amount_cents"] = tier_b_amount_cents
    return get_success_data(api_client.create_settlement(payload, ADMIN))


def register_member(settlement_id, *, full_name, email, claimant_tier=None, tin_on_file=True):
    payload = {"full_name": full_name, "email": email, "tin_on_file": tin_on_file}
    if claimant_tier is not None:
        payload["claimant_tier"] = claimant_tier
    return get_success_data(
        api_client.create_class_member(settlement_id, payload, ADMINISTRATOR)
    )


def file_claim(settlement_id, member_id, *, claimed_loss_cents, supersedes_claim_id=None):
    payload = {
        "settlement_id": settlement_id,
        "class_member_id": member_id,
        "claimed_loss_cents": claimed_loss_cents,
    }
    if supersedes_claim_id is not None:
        payload["supersedes_claim_id"] = supersedes_claim_id
    return get_success_data(api_client.create_claim(payload, ADMINISTRATOR))


def validate_claim(claim_id, recognized_loss_cents, *, reviewer_id=DEFAULT_REVIEWER_ID):
    headers = make_claims_reviewer_headers(reviewer_id)
    return get_success_data(
        api_client.validate_claim(claim_id, recognized_loss_cents, headers)
    )


def get_settlement_version(settlement_id):
    s = get_success_data(api_client.get_settlement(settlement_id, ADMIN))
    return s["version"]


def begin_distribution(settlement_id):
    return get_success_data(api_client.begin_distribution(settlement_id, CONTROLLER))


# ─── Tier 2 / 3: lifecycle shortcuts to a DISTRIBUTING fund ──────────────────
def setup_distributing_settlement(
    *,
    distribution_method="PRO_RATA",
    gross_fund_cents=100000,
    attorney_fee_cents=0,
    admin_cost_cents=0,
    tier_a_amount_cents=None,
    tier_b_amount_cents=None,
    cy_pres_floor_cents=0,
    members,
    reviewer_id=DEFAULT_REVIEWER_ID,
    case_caption="In re Distributing",
    approve_cy_pres=None,
):
    """Drive a settlement from DRAFT all the way to DISTRIBUTING with a set of
    members each holding one VALIDATED claim.

    `members` is a list of dicts, each:
        {
          "email": str,                 # required, unique within settlement
          "full_name": str,             # optional, defaults to email local part
          "claimant_tier": "TIER_A"|"TIER_B"|None,
          "tin_on_file": bool,          # defaults True
          "claimed_loss_cents": int,    # required
          "recognized_loss_cents": int, # required
        }

    `approve_cy_pres` (optional): list of {"recipient_name", "share_bps"} created
    and APPROVED before notice opens (so open-notice's cy-pres coherence
    precondition is satisfied when cy_pres_floor_cents > 0).

    Clock is set to 2026-01-01 for the working window and advanced to
    2026-02-01 (== claim_filing_deadline) before close-claims.

    Returns dict: {settlement, members: [...], claims: [...], cy_pres: [...]}.
    """
    set_clock("2026-01-01T00:00:00Z")
    settlement = create_settlement(
        gross_fund_cents=gross_fund_cents,
        attorney_fee_cents=attorney_fee_cents,
        admin_cost_cents=admin_cost_cents,
        distribution_method=distribution_method,
        tier_a_amount_cents=tier_a_amount_cents,
        tier_b_amount_cents=tier_b_amount_cents,
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=cy_pres_floor_cents,
        case_caption=case_caption,
    )
    s_id = settlement["id"]

    cy_pres = []
    if approve_cy_pres:
        for spec in approve_cy_pres:
            d = get_success_data(
                api_client.create_cy_pres_designation(
                    s_id,
                    {"recipient_name": spec["recipient_name"], "share_bps": spec["share_bps"]},
                    ADMIN,
                )
            )
            get_success_data(api_client.approve_cy_pres_designation(d["id"], COURT))
            cy_pres.append(d)

    get_success_data(api_client.open_notice(s_id, ADMIN))

    member_rows = []
    for spec in members:
        m = register_member(
            s_id,
            full_name=spec.get("full_name", spec["email"].split("@")[0]),
            email=spec["email"],
            claimant_tier=spec.get("claimant_tier"),
            tin_on_file=spec.get("tin_on_file", True),
        )
        member_rows.append(m)

    get_success_data(api_client.open_claims(s_id, ADMIN))

    claim_rows = []
    for spec, m in zip(members, member_rows):
        c = file_claim(s_id, m["id"], claimed_loss_cents=spec["claimed_loss_cents"])
        validate_claim(c["id"], spec["recognized_loss_cents"], reviewer_id=reviewer_id)
        claim_rows.append(c)

    set_clock("2026-02-01T00:00:00Z")
    get_success_data(api_client.close_claims(s_id, ADMIN))
    begin_distribution(s_id)

    # refresh claims so callers see post-validate state.
    # PRD §4 authorizes FundController (not SettlementAdmin) for GET /claims/{id}.
    claim_rows = [get_success_data(api_client.get_claim(c["id"], CONTROLLER)) for c in claim_rows]
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    return {
        "settlement": settlement,
        "members": member_rows,
        "claims": claim_rows,
        "cy_pres": cy_pres,
    }


def create_batch(settlement_id, *, sequence_no=1):
    return get_success_data(
        api_client.create_distribution_batch(
            {"settlement_id": settlement_id, "sequence_no": sequence_no}, CONTROLLER
        )
    )


def setup_computed_batch(*, sequence_no=1, **kwargs):
    """setup_distributing_settlement + create a batch + compute it.
    Returns the distributing dict plus {batch: <COMPUTED batch>}."""
    ctx = setup_distributing_settlement(**kwargs)
    s_id = ctx["settlement"]["id"]
    batch = create_batch(s_id, sequence_no=sequence_no)
    batch = get_success_data(api_client.compute_batch(batch["id"], CONTROLLER))
    ctx["batch"] = batch
    return ctx


def post_batch(settlement_id, batch_id, *, controller_id=DEFAULT_CONTROLLER_ID):
    """Read the live settlement version and post the batch with it. The posting
    controller id must differ from the validating reviewer id (PRD §2.10)."""
    version = get_settlement_version(settlement_id)
    headers = make_fund_controller_headers(controller_id)
    return get_success_data(api_client.post_batch(batch_id, version, headers))


def setup_posted_batch(*, controller_id=DEFAULT_CONTROLLER_ID, **kwargs):
    """setup_computed_batch + post it. Returns the context dict with the POSTED
    batch under 'batch' and refreshed settlement/claims."""
    ctx = setup_computed_batch(**kwargs)
    s_id = ctx["settlement"]["id"]
    batch = post_batch(s_id, ctx["batch"]["id"], controller_id=controller_id)
    ctx["batch"] = batch
    ctx["settlement"] = get_success_data(api_client.get_settlement(s_id, ADMIN))
    ctx["claims"] = [
        get_success_data(api_client.get_claim(c["id"], CONTROLLER)) for c in ctx["claims"]
    ]
    return ctx


# ─── Single-claim convenience (the most common shape) ───────────────────────
def setup_single_claim_posted(
    *,
    gross_fund_cents=50000,
    claimed_loss_cents=50000,
    recognized_loss_cents=50000,
    tin_on_file=True,
    distribution_method="PRO_RATA",
    cy_pres_floor_cents=0,
    controller_id=DEFAULT_CONTROLLER_ID,
    reviewer_id=DEFAULT_REVIEWER_ID,
):
    """One no-frills member with one VALIDATED-then-PAID claim through a POSTED
    batch. Returns the posted context dict."""
    return setup_posted_batch(
        distribution_method=distribution_method,
        gross_fund_cents=gross_fund_cents,
        cy_pres_floor_cents=cy_pres_floor_cents,
        members=[{
            "email": "m@x.com",
            "full_name": "M",
            "tin_on_file": tin_on_file,
            "claimed_loss_cents": claimed_loss_cents,
            "recognized_loss_cents": recognized_loss_cents,
        }],
        controller_id=controller_id,
        reviewer_id=reviewer_id,
    )


# ─── Claims-phase helpers (settlement left in CLAIMS_OPEN) ───────────────────
def setup_claims_open_with_member(
    *,
    clock="2026-01-05T00:00:00Z",
    claim_filing_deadline="2026-03-01T00:00:00Z",
    objection_deadline="2026-02-01T00:00:00Z",
    distribution_method="PRO_RATA",
    gross_fund_cents=100000,
    member_email="m@x.com",
    member_tin_on_file=True,
    member_tier=None,
):
    """A CLAIMS_OPEN settlement with one NOTIFIED member and no claim yet.
    Returns (settlement, member)."""
    set_clock(clock)
    settlement = create_settlement(
        gross_fund_cents=gross_fund_cents,
        distribution_method=distribution_method,
        claim_filing_deadline=claim_filing_deadline,
        objection_deadline=objection_deadline,
        cy_pres_floor_cents=0,
        case_caption="In re ClaimsOpen",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = register_member(
        s_id, full_name="M", email=member_email,
        claimant_tier=member_tier, tin_on_file=member_tin_on_file,
    )
    get_success_data(api_client.open_claims(s_id, ADMIN))
    return settlement, member


def setup_notice_open_with_member(
    *,
    clock="2026-01-05T00:00:00Z",
    claim_filing_deadline="2026-03-01T00:00:00Z",
    objection_deadline="2026-02-01T00:00:00Z",
):
    """A NOTICE_OPEN settlement with one NOTIFIED member. Returns (settlement, member)."""
    set_clock(clock)
    settlement = create_settlement(
        claim_filing_deadline=claim_filing_deadline,
        objection_deadline=objection_deadline,
        cy_pres_floor_cents=0,
        case_caption="In re NoticeOpen",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    return settlement, member


def setup_submitted_claim(**kwargs):
    """CLAIMS_OPEN settlement, one member, one SUBMITTED claim.
    Returns (settlement, member, claim)."""
    claimed = kwargs.pop("claimed_loss_cents", 5000)
    settlement, member = setup_claims_open_with_member(**kwargs)
    claim = file_claim(settlement["id"], member["id"], claimed_loss_cents=claimed)
    return settlement, member, claim


def setup_deficient_claim(
    *,
    deficiencies=None,
    claimed_loss_cents=5000,
    clock="2026-01-05T00:00:00Z",
):
    """CLAIMS_OPEN settlement, one member, one DEFICIENT claim with the given
    OPEN deficiencies. `deficiencies` is a list of {"reason_code","cure_deadline"}
    (defaults to a single MISSING_PROOF due 2026-02-15).
    Returns (settlement, member, claim, [deficiency...])."""
    if deficiencies is None:
        deficiencies = [{"reason_code": "MISSING_PROOF", "cure_deadline": "2026-02-15T00:00:00Z"}]
    settlement, member, claim = setup_submitted_claim(
        clock=clock, claimed_loss_cents=claimed_loss_cents
    )
    rows = []
    for d in deficiencies:
        row = get_success_data(api_client.raise_deficiency(claim["id"], d, REVIEWER))
        rows.append(row)
    claim = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    return settlement, member, claim, rows


def cure_claim(claim_id, member_id):
    """Cure as the entity-backed Claimant who owns the claim (ownership-gated)."""
    return get_success_data(
        api_client.cure_claim(claim_id, make_claimant_headers(member_id))
    )
