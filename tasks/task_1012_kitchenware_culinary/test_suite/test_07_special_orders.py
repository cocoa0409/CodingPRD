"""Special orders: the quote/revision cycle and optimistic-concurrency control
on quoting."""
from test_helpers import (
    validate_success, validate_error,
    setup_special_order, quote_special_order, make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOC = TEST_USERS["associate_headers"]


def _run_quote_revision_cycle(api):
    """DRAFT(v1) -> quote(v2) -> request-revision(v3) -> re-quote(v4). Returns the
    dict of observed states at each step."""
    store, member, so = setup_special_order(state_code="NY", estimated_cost_cents=40000,
                                            description="Monogrammed knife block")
    q1 = quote_special_order(so["id"], so["version"], 42000, deposit_cents=10000)
    rev = validate_success(api.request_revision(so["id"], make_member_headers(member["id"])), 200)
    q2 = quote_special_order(so["id"], rev["version"], 39000, deposit_cents=9000)
    return {"so": so, "q1": q1, "rev": rev, "q2": q2}


# ── non_linear_state_machine / special_order_quote_revision_cycle ──
def test_requote_returns_to_quoted_with_revision_two_version_four(api):
    """PRD §3.7: "A store associate then re-quotes the revision-requested order — the heart
    of the cycle — which returns it from `REVISION_REQUESTED` back to `QUOTED`: the quoted
    total and deposit are updated, the quote revision counter again increases by one, and
    the version again increments by one."

    Design: Difficulty/non_linear_state_machine/special_order_quote_revision_cycle
    """
    steps = _run_quote_revision_cycle(api)
    q2 = steps["q2"]
    assert q2["status"] == "QUOTED"
    assert q2["quote_revision"] == 2
    assert q2["version"] == 4


def test_cycle_intermediate_states_progress(api):
    """PRD §3.7: "On a successful quote, the quoted total and deposit are recorded, the
    `quote_revision` counter increases by one, the version increments by one, and the status
    becomes `QUOTED`."
    PRD §3.7: "From `QUOTED`, the member may request a revision, which moves the request to
    `REVISION_REQUESTED` and increments the version by one."

    Design: Difficulty/non_linear_state_machine/special_order_quote_revision_cycle
    """
    steps = _run_quote_revision_cycle(api)
    assert steps["q1"]["status"] == "QUOTED"
    assert steps["q1"]["version"] == 2
    assert steps["q1"]["quote_revision"] == 1
    assert steps["rev"]["status"] == "REVISION_REQUESTED"
    assert steps["rev"]["version"] == 3


# ── Corner/cross_cutting_concerns/occ_quote_stale_version_returns_412 ──
def test_stale_version_quote_rejected(api):
    """PRD §2.11: "If that value does not match the special order's current `version` —
    because a prior quote or a member's revision request has already advanced the version
    since the client last read it — the request is rejected with `ERR_STALE_VERSION` at HTTP
    412, and the newer quote is preserved."

    Design: Corner/cross_cutting_concerns/occ_quote_stale_version_returns_412
    """
    store, member, so = setup_special_order(state_code="NY", estimated_cost_cents=20000,
                                            description="Custom cutting board")
    stale_version = so["version"]  # 1
    quote_special_order(so["id"], stale_version, 22000)  # advances version to 2
    res = api.quote_special_order(so["id"],
                                  {"expected_special_order_version": stale_version,
                                   "quoted_total_cents": 21000}, ASSOC)
    validate_error(res, "ERR_STALE_VERSION")


# ── Corner/cross_cutting_concerns/occ_quote_increments_version ──
def test_quote_with_current_version_increments(api):
    """PRD §3.7: "On a successful quote, the quoted total and deposit are recorded, the
    `quote_revision` counter increases by one, the version increments by one, and the status
    becomes `QUOTED`."

    Design: Corner/cross_cutting_concerns/occ_quote_increments_version
    """
    store, member, so = setup_special_order(state_code="NY", estimated_cost_cents=30000,
                                            description="Engraved decanter")
    quoted = quote_special_order(so["id"], so["version"], 31000)
    assert quoted["version"] == 2
    assert quoted["quote_revision"] == 1
    assert quoted["status"] == "QUOTED"
