"""Buyouts: cooling-off fork, rescission deadline boundary, escrow conservation, completion.

Sources: Difficulty/non_linear_state_machine, Difficulty/boundary_precision_check,
Difficulty/compensating_invariant, Corner/validations.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error,
    make_tenant_headers,
    set_clock, setup_buyout_filed,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/buyout_fork_rescind_branch
# ---------------------------------------------------------------------------
def test_rescind_branch_releases_escrow(api):
    """PRD §3.7: "Rescission moves the buyout FILED → RESCINDED, subtracts the
    relocation_amount_cents back out of the landlord's escrow_committed_cents, and leaves
    the tenancy untouched (the tenant keeps the unit)."

    Design: Difficulty/non_linear_state_machine/buyout_fork_rescind_branch
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=1000000)
    buyout = validate_success(api.rescind_buyout(ctx["buyout_id"], make_tenant_headers(ctx["tenant_id"])))
    assert buyout["status"] == "RESCINDED"
    landlord = validate_success(api.get_landlord(ctx["landlord_id"], CLERK))
    assert landlord["escrow_committed_cents"] == 0


def test_rescind_branch_leaves_tenancy_active(api):
    """PRD §3.7: "and leaves the tenancy untouched (the tenant keeps the unit) ... only
    completion vacates the unit."

    Design: Difficulty/non_linear_state_machine/buyout_fork_rescind_branch
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=1000000)
    validate_success(api.rescind_buyout(ctx["buyout_id"], make_tenant_headers(ctx["tenant_id"])))
    tenancy = validate_success(api.get_tenancy(ctx["tenancy_id"], CLERK))
    assert tenancy["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/rescind_deadline_inclusive_boundary
# ---------------------------------------------------------------------------
def test_rescind_at_exact_deadline_allowed(api):
    """PRD §3.7: "The tenant may rescind while the cooling-off window is open — that is,
    while the current logical time is at or before the rescind_deadline".
    PRD §3.7: "computes rescind_deadline as filed_at plus thirty days".

    Design: Difficulty/boundary_precision_check/rescind_deadline_inclusive_boundary
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=800000)
    # filed_at is the default clock 2026-05-01T00:00:00Z; deadline is 2026-05-31T00:00:00Z.
    assert ctx["buyout"]["rescind_deadline"].startswith("2026-05-31T00:00:00")
    set_clock(api, "2026-05-31T00:00:00Z")
    buyout = validate_success(api.rescind_buyout(ctx["buyout_id"], make_tenant_headers(ctx["tenant_id"])))
    assert buyout["status"] == "RESCINDED"


def test_rescind_one_second_after_deadline_rejected(api):
    """PRD §3.7: "a rescission attempted after that instant is rejected with
    ERR_COOLING_OFF_EXPIRED."

    Design: Difficulty/boundary_precision_check/rescind_deadline_inclusive_boundary
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=800000)
    set_clock(api, "2026-05-31T00:00:01Z")
    resp = api.rescind_buyout(ctx["buyout_id"], make_tenant_headers(ctx["tenant_id"]))
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_EXPIRED)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/buyout_file_rescind_conserves_escrow
# ---------------------------------------------------------------------------
def test_escrow_committed_after_file(api):
    """PRD §3.7: "On success the buyout records ... and adds the relocation_amount_cents to
    the landlord's escrow_committed_cents."
    PRD §2.9: "Filing a buyout adds its relocation amount to the landlord's committed escrow".

    Design: Difficulty/compensating_invariant/buyout_file_rescind_conserves_escrow
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=1000000)
    landlord = validate_success(api.get_landlord(ctx["landlord_id"], CLERK))
    assert landlord["escrow_committed_cents"] == 1000000


def test_file_then_rescind_conserves_escrow_to_zero(api):
    """PRD §2.9: "rescinding or completing a filed buyout subtracts that same amount back
    out. Because each buyout contributes its relocation amount exactly once while FILED and
    removes it exactly once when it leaves FILED, the committed total is a conserved quantity."

    Design: Difficulty/compensating_invariant/buyout_file_rescind_conserves_escrow
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=1000000)
    validate_success(api.rescind_buyout(ctx["buyout_id"], make_tenant_headers(ctx["tenant_id"])))
    landlord = validate_success(api.get_landlord(ctx["landlord_id"], CLERK))
    assert landlord["escrow_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/validations
# ---------------------------------------------------------------------------
def test_buyout_complete_before_cooling_off_rejected(api):
    """PRD §3.7: "the board clerk may complete the buyout only once the cooling-off window
    has elapsed — that is, when the current logical time is at or after the rescind_deadline;
    a completion attempted before that instant is rejected with ERR_COOLING_OFF_NOT_ELAPSED."

    Design: Corner/validations/buyout_complete_before_cooling_off_rejected
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=900000)  # clock still at default
    resp = api.complete_buyout(ctx["buyout_id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED)


def test_buyout_complete_after_cooling_off_ends_tenancy(api):
    """PRD §3.7: "Completion moves the buyout `FILED → COMPLETED`, subtracts the
    `relocation_amount_cents` back out of the landlord's `escrow_committed_cents`, and
    cascades to the tenancy: the tenant's `ACTIVE` tenancy on the unit transitions to
    `ENDED` with its `end_date` set to the completion date."

    Design: Corner/validations/buyout_complete_after_cooling_off_ends_tenancy
    """
    ctx = setup_buyout_filed(api, relocation_amount_cents=900000)
    set_clock(api, "2026-06-05T00:00:00Z")
    buyout = validate_success(api.complete_buyout(ctx["buyout_id"], CLERK))
    assert buyout["status"] == "COMPLETED"
    landlord = validate_success(api.get_landlord(ctx["landlord_id"], CLERK))
    assert landlord["escrow_committed_cents"] == 0
    tenancy = validate_success(api.get_tenancy(ctx["tenancy_id"], CLERK))
    assert tenancy["status"] == "ENDED"
